from __future__ import annotations

import json
import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate

import erpnext
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_dimensions
from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
    reconcile_dr_cr_note,
)
from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import reconcile_against_document

TOLERANCE = 0.01
ROUNDING_TOLERANCE = 1.0
DISCOUNT_ACCOUNT_NAME = "Supplier Settlement Discount"


def _round(value):
    return flt(value, 6)


def _money_equal(left, right, tolerance=TOLERANCE):
    return abs(_round(left) - _round(right)) <= tolerance


def ensure_supplier_settlement_discount_account(company: str) -> str:
    """Return/create the company income account used for supplier settlement discounts."""
    existing = frappe.db.get_value(
        "Account",
        {
            "company": company,
            "account_name": DISCOUNT_ACCOUNT_NAME,
            "is_group": 0,
            "disabled": 0,
        },
        "name",
    )
    if existing:
        return existing

    abbr = frappe.db.get_value("Company", company, "abbr")
    preferred = [
        f"Indirect Income - {abbr}" if abbr else None,
        f"Income - {abbr}" if abbr else None,
    ]
    parent = next(
        (
            name
            for name in preferred
            if name
            and frappe.db.exists("Account", name)
            and frappe.db.get_value("Account", name, "is_group")
        ),
        None,
    )
    if not parent:
        parent = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": "Income",
                "is_group": 1,
                "disabled": 0,
            },
            "name",
            order_by="lft desc",
        )
    if not parent:
        frappe.throw(
            _("No enabled Income account group was found for Company {0}.").format(company)
        )

    account = frappe.get_doc(
        {
            "doctype": "Account",
            "account_name": DISCOUNT_ACCOUNT_NAME,
            "company": company,
            "parent_account": parent,
            "is_group": 0,
            "root_type": "Income",
            "report_type": "Profit and Loss",
        }
    )
    account.insert(ignore_permissions=True)
    return account.name


def _party_account(claim):
    accounts = {
        frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "credit_to")
        for row in claim.invoices
        if row.purchase_invoice
    }
    accounts.discard(None)
    if len(accounts) > 1:
        frappe.throw(
            _("All Purchase Invoices in a Supplier Claim must use the same payable account.")
        )
    return next(iter(accounts), None) or get_party_account(
        "Supplier", claim.supplier, claim.company
    )


def _payment_unallocated_amount(payment_entry):
    return abs(flt(payment_entry.unallocated_amount))


def _allocate(source_name, source_amount, targets):
    allocations = []
    remaining = _round(source_amount)
    for target in targets:
        if remaining <= TOLERANCE:
            break
        capacity = _round(target["remaining"])
        if capacity <= TOLERANCE:
            continue
        amount = min(remaining, capacity)
        allocations.append(
            {
                "source": source_name,
                "target": target["purchase_invoice"],
                "amount": _round(amount),
            }
        )
        target["remaining"] = _round(capacity - amount)
        remaining = _round(remaining - amount)
    if remaining > TOLERANCE:
        frappe.throw(
            _("Unable to allocate {0}; unallocated amount is {1}.").format(
                source_name, frappe.bold(remaining)
            )
        )
    return allocations


def _line_snapshot(row, claim):
    invoice = frappe.db.get_value(
        "Purchase Invoice",
        row.purchase_invoice,
        [
            "name",
            "docstatus",
            "company",
            "supplier",
            "posting_date",
            "is_return",
            "grand_total",
            "outstanding_amount",
            "currency",
            "conversion_rate",
            "credit_to",
            "status",
            "custom_supplier_claim",
        ],
        as_dict=True,
    )
    if not invoice:
        frappe.throw(
            _("Purchase Invoice {0} does not exist.").format(row.purchase_invoice)
        )
    if invoice.docstatus != 1:
        frappe.throw(
            _("Purchase Invoice {0} must be submitted.").format(invoice.name)
        )
    if invoice.company != claim.company or invoice.supplier != claim.supplier:
        frappe.throw(
            _("Purchase Invoice {0} does not belong to this Supplier Claim party/company.").format(
                invoice.name
            )
        )

    claim_included = _round(row.included_amount)
    if claim_included > TOLERANCE and invoice.is_return:
        frappe.throw(_("Return invoice {0} cannot have a positive Included Amount.").format(invoice.name))
    if claim_included < -TOLERANCE and not invoice.is_return:
        frappe.throw(_("Purchase Invoice {0} cannot have a negative Included Amount.").format(invoice.name))

    outstanding_before = _round(invoice.outstanding_amount)
    accounting_included = claim_included
    rounding_adjustment = 0.0

    # Supplier Claim rows can be created from the supplier printed amount / grand_total,
    # while ERPNext accounting closes against outstanding_amount, which may be rounded
    # (for example grand_total 149.62 but outstanding_amount 150.00).  If the live
    # outstanding differs only by a small rounding delta, settle the accounting value
    # and normalize the submitted claim row during verification.
    if abs(outstanding_before) > TOLERANCE and abs(claim_included) > TOLERANCE:
        same_sign = (outstanding_before > 0 and claim_included > 0) or (outstanding_before < 0 and claim_included < 0)
        diff = _round(outstanding_before - claim_included)
        if same_sign and abs(diff) > TOLERANCE and abs(diff) <= ROUNDING_TOLERANCE:
            accounting_included = outstanding_before
            rounding_adjustment = diff

    allocated_before = _round(row.get("accounting_allocated_amount"))
    accounting_status = row.get("accounting_status") or "Pending"
    return {
        "row_name": row.name,
        "purchase_invoice": invoice.name,
        "posting_date": invoice.posting_date,
        "is_return": bool(invoice.is_return),
        "claim_included_amount": claim_included,
        "included_amount": _round(accounting_included),
        "rounding_adjustment": _round(rounding_adjustment),
        "amount": abs(_round(accounting_included)),
        "outstanding_before": outstanding_before,
        "grand_total": _round(invoice.grand_total),
        "currency": invoice.currency,
        "conversion_rate": _round(invoice.conversion_rate or 1),
        "credit_to": invoice.credit_to,
        "status": invoice.status,
        "linked_claim": invoice.custom_supplier_claim,
        "accounting_allocated_before": allocated_before,
        "accounting_status_before": accounting_status,
    }


def build_supplier_claim_settlement_plan(claim_name: str, payment_entry: str | None = None):
    claim = frappe.get_doc("Supplier Claim", claim_name)
    if claim.docstatus != 1:
        frappe.throw(_("Submit Supplier Claim {0} before accounting settlement.").format(claim.name))
    if claim.status == "Cancelled":
        frappe.throw(_("Cancelled Supplier Claim cannot be settled."))

    rows = [_line_snapshot(row, claim) for row in claim.invoices if abs(flt(row.included_amount)) > TOLERANCE]
    if not rows:
        frappe.throw(_("Supplier Claim has no non-zero invoice rows."))

    positive = [row for row in rows if row["included_amount"] > 0]
    returns = [row for row in rows if row["included_amount"] < 0]
    if not positive:
        frappe.throw(_("Supplier Claim must contain at least one positive Purchase Invoice."))

    currencies = {row["currency"] for row in rows}
    if len(currencies) != 1:
        frappe.throw(_("Multi-currency Supplier Claims are not supported by this settlement utility."))
    currency = next(iter(currencies))
    company_currency = frappe.db.get_value("Company", claim.company, "default_currency")
    if currency != company_currency or any(not _money_equal(row["conversion_rate"], 1) for row in rows):
        frappe.throw(_("This settlement utility currently requires Company Currency invoices."))

    for row in rows:
        if row["linked_claim"] and row["linked_claim"] != claim.name:
            frappe.throw(
                _("Purchase Invoice {0} belongs to Supplier Claim {1}.").format(
                    row["purchase_invoice"], row["linked_claim"]
                )
            )
        if row["accounting_status_before"] == "Reconciled":
            continue
        if row["accounting_allocated_before"] > TOLERANCE:
            frappe.throw(
                _("Claim row {0} has a partial accounting allocation and requires manual review.").format(
                    row["purchase_invoice"]
                )
            )
        expected_open = row["included_amount"]
        if not _money_equal(row["outstanding_before"], expected_open):
            frappe.throw(
                _(
                    "Purchase Invoice {0} Outstanding {1} does not equal the Claim Included Amount {2}. "
                    "It may already be partly allocated outside this claim."
                ).format(
                    row["purchase_invoice"],
                    frappe.bold(row["outstanding_before"]),
                    frappe.bold(expected_open),
                )
            )

    gross = _round(sum(row["amount"] for row in positive))
    return_credit = _round(sum(row["amount"] for row in returns))
    system_total = _round(gross - return_credit)

    claim_gross = _round(sum(abs(row["claim_included_amount"]) for row in positive))
    claim_return_credit = _round(sum(abs(row["claim_included_amount"]) for row in returns))
    claim_system_total = _round(claim_gross - claim_return_credit)
    rounding_adjustment_total = _round(system_total - claim_system_total)

    net_due = _round(max(0, flt(claim.net_amount_to_pay)))
    claim_discount = _round(max(0, flt(claim.settlement_discount_amount)))
    discount = _round(max(0, system_total - net_due))

    if abs(rounding_adjustment_total) > ROUNDING_TOLERANCE:
        frappe.throw(
            _(
                "Supplier Claim accounting rounding adjustment {0} exceeds allowed tolerance. Review claim rows manually."
            ).format(frappe.bold(rounding_adjustment_total))
        )
    if not _money_equal(claim_gross, flt(claim.gross_claim_total)):
        frappe.throw(_("Gross Claim Total does not match the included positive invoices."))
    if not _money_equal(claim_return_credit, flt(claim.purchase_returns_total)):
        frappe.throw(_("Purchase Returns Total does not match the included Debit Notes."))
    if not _money_equal(claim_system_total, flt(claim.system_claim_total)):
        frappe.throw(_("System Claim Total is inconsistent with claim rows."))
    if not _money_equal(system_total, net_due + discount):
        frappe.throw(
            _("Net payment plus settlement discount must equal the accounting System Claim Total.")
        )
    if abs((discount - claim_discount) - rounding_adjustment_total) > ROUNDING_TOLERANCE:
        frappe.throw(
            _(
                "Settlement discount {0} plus accounting rounding adjustment {1} is inconsistent with Net Amount To Pay {2}."
            ).format(claim_discount, rounding_adjustment_total, net_due)
        )

    payment_entry = payment_entry or claim.payment_entry or None
    payment = None
    if net_due > TOLERANCE:
        if not payment_entry:
            frappe.throw(_("Select a submitted supplier Payment Entry."))
        payment = frappe.get_doc("Payment Entry", payment_entry)
        if payment.docstatus != 1 or payment.payment_type != "Pay":
            frappe.throw(_("Payment Entry must be a submitted Pay entry."))
        if payment.party_type != "Supplier" or payment.party != claim.supplier:
            frappe.throw(_("Payment Entry must belong to Supplier {0}.").format(claim.supplier))
        if payment.company != claim.company:
            frappe.throw(_("Payment Entry belongs to another company."))
        linked_claim = payment.get("custom_supplier_claim")
        if linked_claim and linked_claim != claim.name:
            frappe.throw(
                _("Payment Entry {0} is already linked to Supplier Claim {1}.").format(
                    payment.name, linked_claim
                )
            )
        available = _round(_payment_unallocated_amount(payment))
        if available + TOLERANCE < net_due:
            frappe.throw(
                _("Payment Entry unallocated amount {0} is less than Net Amount To Pay {1}.").format(
                    frappe.bold(available), frappe.bold(net_due)
                )
            )
    else:
        available = 0

    targets = [
        {
            "purchase_invoice": row["purchase_invoice"],
            "remaining": row["amount"],
            "posting_date": row["posting_date"],
            "currency": row["currency"],
            "exchange_rate": row["conversion_rate"],
        }
        for row in positive
    ]

    discount_allocations = _allocate("Settlement Discount", discount, targets) if discount > TOLERANCE else []
    return_allocations = []
    for row in returns:
        return_allocations.extend(_allocate(row["purchase_invoice"], row["amount"], targets))
    payment_allocations = _allocate(payment_entry, net_due, targets) if net_due > TOLERANCE else []

    unfilled = _round(sum(target["remaining"] for target in targets))
    if unfilled > TOLERANCE:
        frappe.throw(_("Claim settlement plan leaves {0} unallocated.").format(unfilled))

    return {
        "supplier_claim": claim.name,
        "company": claim.company,
        "supplier": claim.supplier,
        "party_account": _party_account(claim),
        "currency": currency,
        "gross_invoices": gross,
        "return_credits": return_credit,
        "system_claim_total": system_total,
        "printed_system_claim_total": claim_system_total,
        "accounting_rounding_adjustment": rounding_adjustment_total,
        "net_payment": net_due,
        "settlement_discount": discount,
        "printed_settlement_discount": claim_discount,
        "payment_entry": payment_entry,
        "payment_unallocated_before": available,
        "positive_rows": positive,
        "return_rows": returns,
        "discount_allocations": discount_allocations,
        "return_allocations": return_allocations,
        "payment_allocations": payment_allocations,
    }


def _create_discount_journal(claim, plan, discount_account):
    if plan["settlement_discount"] <= TOLERANCE:
        return None

    existing = claim.get("settlement_discount_journal_entry")
    if existing and frappe.db.exists("Journal Entry", existing):
        status = frappe.db.get_value("Journal Entry", existing, "docstatus")
        if status == 1:
            return existing
        frappe.throw(_("Existing Settlement Discount Journal Entry is not submitted."))

    posting_date = nowdate()
    if plan["payment_entry"]:
        posting_date = frappe.db.get_value("Payment Entry", plan["payment_entry"], "posting_date") or posting_date

    cost_center = erpnext.get_default_cost_center(claim.company)
    accounts = []
    for allocation in plan["discount_allocations"]:
        accounts.append(
            {
                "account": plan["party_account"],
                "party_type": "Supplier",
                "party": claim.supplier,
                "debit_in_account_currency": allocation["amount"],
                "reference_type": "Purchase Invoice",
                "reference_name": allocation["target"],
                "cost_center": cost_center,
            }
        )
    accounts.append(
        {
            "account": discount_account,
            "credit_in_account_currency": plan["settlement_discount"],
            "cost_center": cost_center,
        }
    )

    journal = frappe.get_doc(
        {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "company": claim.company,
            "posting_date": posting_date,
            "user_remark": _("Supplier settlement discount for Supplier Claim {0}").format(claim.name),
            "accounts": accounts,
        }
    )
    if journal.meta.has_field("custom_supplier_claim"):
        journal.custom_supplier_claim = claim.name
    journal.insert(ignore_permissions=True)
    journal.submit()
    return journal.name


def _reconcile_returns(claim, plan):
    if not plan["return_allocations"]:
        return []
    source_map = {row["purchase_invoice"]: row for row in plan["return_rows"]}
    cost_center = erpnext.get_default_cost_center(claim.company)
    entries = []
    for allocation in plan["return_allocations"]:
        source = source_map[allocation["source"]]
        entries.append(
            frappe._dict(
                {
                    "voucher_type": "Purchase Invoice",
                    "voucher_no": source["purchase_invoice"],
                    "voucher_detail_no": None,
                    "against_voucher_type": "Purchase Invoice",
                    "against_voucher": allocation["target"],
                    "account": plan["party_account"],
                    "exchange_rate": source["conversion_rate"],
                    "party_type": "Supplier",
                    "party": claim.supplier,
                    "is_advance": 0,
                    "dr_or_cr": "debit_in_account_currency",
                    "unreconciled_amount": source["amount"],
                    "unadjusted_amount": source["amount"],
                    "allocated_amount": allocation["amount"],
                    "difference_amount": 0,
                    "difference_account": None,
                    "difference_posting_date": None,
                    "debit_or_credit_note_posting_date": source["posting_date"],
                    "currency": source["currency"],
                    "cost_center": cost_center,
                }
            )
        )

    before = set(
        frappe.get_all(
            "Journal Entry",
            filters={"company": claim.company, "is_system_generated": 1},
            pluck="name",
            limit_page_length=0,
        )
    )
    dimensions = get_dimensions(with_cost_center_and_project=True)[0]
    reconcile_dr_cr_note(entries, claim.company, dimensions)
    after = set(
        frappe.get_all(
            "Journal Entry",
            filters={"company": claim.company, "is_system_generated": 1},
            pluck="name",
            limit_page_length=0,
        )
    )
    created = sorted(after - before)
    if frappe.get_meta("Journal Entry").has_field("custom_supplier_claim"):
        for journal_name in created:
            frappe.db.set_value(
                "Journal Entry",
                journal_name,
                "custom_supplier_claim",
                claim.name,
                update_modified=False,
            )
    return created


def _reconcile_payment(claim, plan):
    if not plan["payment_allocations"]:
        return
    payment = frappe.get_doc("Payment Entry", plan["payment_entry"])
    cost_center = erpnext.get_default_cost_center(claim.company)
    entries = []
    remaining = plan["net_payment"]
    for allocation in plan["payment_allocations"]:
        target = frappe.db.get_value(
            "Purchase Invoice",
            allocation["target"],
            ["grand_total", "outstanding_amount"],
            as_dict=True,
        )
        entries.append(
            frappe._dict(
                {
                    "voucher_type": "Payment Entry",
                    "voucher_no": payment.name,
                    "voucher_detail_no": None,
                    "against_voucher_type": "Purchase Invoice",
                    "against_voucher": allocation["target"],
                    "account": plan["party_account"],
                    "exchange_rate": 1,
                    "grand_total": flt(target.grand_total),
                    "outstanding_amount": flt(target.outstanding_amount),
                    "dimensions": {},
                    "party_type": "Supplier",
                    "party": claim.supplier,
                    "is_advance": 1,
                    "dr_or_cr": "debit_in_account_currency",
                    "unreconciled_amount": plan["net_payment"],
                    "unadjusted_amount": remaining,
                    "allocated_amount": allocation["amount"],
                    "difference_amount": 0,
                    "difference_account": None,
                    "difference_posting_date": None,
                    "debit_or_credit_note_posting_date": None,
                    "currency": plan["currency"],
                    "cost_center": cost_center,
                }
            )
        )
        remaining = _round(remaining - allocation["amount"])

    dimensions = get_dimensions(with_cost_center_and_project=True)[0]
    reconcile_against_document(entries, False, dimensions)


def _verify_and_mark(claim, plan, discount_journal, reconciliation_journals):
    verification = []
    for row in plan["positive_rows"] + plan["return_rows"]:
        current = _round(
            frappe.db.get_value("Purchase Invoice", row["purchase_invoice"], "outstanding_amount")
        )
        expected = _round(row["outstanding_before"] - row["included_amount"])
        ok = _money_equal(current, expected)
        verification.append(
            {
                "purchase_invoice": row["purchase_invoice"],
                "outstanding_before": row["outstanding_before"],
                "included_amount": row["included_amount"],
                "expected_outstanding": expected,
                "actual_outstanding": current,
                "ok": ok,
            }
        )
        if not ok:
            frappe.throw(
                _("Accounting verification failed for {0}: expected Outstanding {1}, found {2}.").format(
                    row["purchase_invoice"], expected, current
                )
            )

    payment_unallocated_after = 0
    if plan["payment_entry"]:
        payment_unallocated_after = _round(
            frappe.db.get_value("Payment Entry", plan["payment_entry"], "unallocated_amount")
        )
        expected_payment_unallocated = _round(
            plan["payment_unallocated_before"] - plan["net_payment"]
        )
        if not _money_equal(payment_unallocated_after, expected_payment_unallocated):
            frappe.throw(
                _("Payment Entry verification failed: expected unallocated {0}, found {1}.").format(
                    expected_payment_unallocated, payment_unallocated_after
                )
            )

    for child in claim.invoices:
        matching = next(
            (row for row in plan["positive_rows"] + plan["return_rows"] if row["row_name"] == child.name),
            None,
        )
        if not matching:
            continue
        # Do NOT change child.included_amount after submit.
        # It is the supplier/printed claim amount and may intentionally differ
        # from ERPNext outstanding by a small rounding delta.  The actual
        # accounting amount is stored in accounting_allocated_amount and
        # accounting_settlement_details.
        child.accounting_allocated_amount = abs(flt(matching["included_amount"]))
        child.accounting_outstanding_after = frappe.db.get_value(
            "Purchase Invoice", child.purchase_invoice, "outstanding_amount"
        )
        child.accounting_status = "Reconciled"

    # Do NOT update gross_claim_total / purchase_returns_total / system_claim_total
    # after submission. These are the approved Supplier Claim printed values.
    # If accounting outstanding differs by a small ERPNext rounding delta, the
    # settlement journals/reconciliation use the accounting value, while the
    # delta is documented in accounting_settlement_details below.

    claim.payment_entry = plan["payment_entry"]
    claim.settlement_discount_account = (
        claim.settlement_discount_account if plan["settlement_discount"] > TOLERANCE else None
    )
    claim.settlement_discount_journal_entry = discount_journal
    claim.accounting_reconciliation_journal_entries = "\n".join(reconciliation_journals)
    claim.accounting_settlement_status = "Reconciled"
    claim.accounting_settlement_date = nowdate()
    claim.accounting_settlement_details = json.dumps(
        {
            "verified_at": str(now_datetime()),
            "payment_entry": plan["payment_entry"],
            "payment_unallocated_after": payment_unallocated_after,
            "discount_journal_entry": discount_journal,
            "return_reconciliation_journal_entries": reconciliation_journals,
            "documents": verification,
            "accounting_rounding_adjustment": plan.get("accounting_rounding_adjustment"),
            "printed_system_claim_total": plan.get("printed_system_claim_total"),
            "accounting_system_claim_total": plan.get("system_claim_total"),
            "printed_settlement_discount": plan.get("printed_settlement_discount"),
            "accounting_settlement_discount": plan.get("settlement_discount"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    claim.status = "Paid"
    claim.save(ignore_permissions=True)

    if plan["payment_entry"] and frappe.get_meta("Payment Entry").has_field("custom_supplier_claim"):
        frappe.db.set_value(
            "Payment Entry",
            plan["payment_entry"],
            "custom_supplier_claim",
            claim.name,
            update_modified=False,
        )

    return {
        "verification": verification,
        "payment_unallocated_after": payment_unallocated_after,
    }


def settle_supplier_claim_accounting(
    claim_name: str,
    payment_entry: str | None = None,
    dry_run: bool | int | str = False,
):
    dry_run = str(dry_run).lower() in {"1", "true", "yes"} if isinstance(dry_run, str) else bool(dry_run)
    claim = frappe.get_doc("Supplier Claim", claim_name)
    if claim.get("accounting_settlement_status") == "Reconciled":
        return {
            "already_reconciled": 1,
            "supplier_claim": claim.name,
            "payment_entry": claim.payment_entry,
            "settlement_discount_journal_entry": claim.get("settlement_discount_journal_entry"),
        }

    plan = build_supplier_claim_settlement_plan(claim_name, payment_entry)
    if dry_run:
        return {"dry_run": 1, "plan": plan}

    discount_account = None
    if plan["settlement_discount"] > TOLERANCE:
        discount_account = claim.get("settlement_discount_account") or ensure_supplier_settlement_discount_account(
            claim.company
        )
        claim.settlement_discount_account = discount_account

    discount_journal = _create_discount_journal(claim, plan, discount_account)
    reconciliation_journals = _reconcile_returns(claim, plan)
    _reconcile_payment(claim, plan)
    verification = _verify_and_mark(
        claim, plan, discount_journal, reconciliation_journals
    )

    return {
        "supplier_claim": claim.name,
        "status": "Paid",
        "accounting_settlement_status": "Reconciled",
        "payment_entry": plan["payment_entry"],
        "settlement_discount_account": discount_account,
        "settlement_discount_journal_entry": discount_journal,
        "return_reconciliation_journal_entries": reconciliation_journals,
        **verification,
    }


@frappe.whitelist()
def preview_supplier_claim_accounting(claim_name: str, payment_entry: str | None = None):
    claim = frappe.get_doc("Supplier Claim", claim_name)
    claim.check_permission("read")
    return settle_supplier_claim_accounting(claim_name, payment_entry, dry_run=True)


@frappe.whitelist()
def repair_supplier_claim_accounting(
    claim_name: str,
    payment_entry: str | None = None,
    dry_run: bool | int | str = True,
):
    claim = frappe.get_doc("Supplier Claim", claim_name)
    claim.check_permission("write")
    return settle_supplier_claim_accounting(claim_name, payment_entry, dry_run=dry_run)


def has_reconciled_accounting(claim_name: str) -> bool:
    return (
        frappe.db.get_value("Supplier Claim", claim_name, "accounting_settlement_status")
        == "Reconciled"
    )


def validate_supplier_claim_payment_cancel(doc, method=None):
    if getattr(frappe.flags, "supplier_claim_accounting_reversal", False):
        return
    linked = frappe.get_all(
        "Supplier Claim",
        filters={
            "docstatus": 1,
            "payment_entry": doc.name,
            "accounting_settlement_status": "Reconciled",
        },
        pluck="name",
        limit_page_length=20,
    )
    if linked:
        frappe.throw(
            _(
                "Payment Entry {0} is part of reconciled Supplier Claim(s): {1}. "
                "Reverse the Supplier Claim accounting settlement first."
            ).format(doc.name, ", ".join(linked))
        )


def validate_supplier_claim_journal_cancel(doc, method=None):
    if getattr(frappe.flags, "supplier_claim_accounting_reversal", False):
        return
    claim_name = doc.get("custom_supplier_claim")
    if claim_name and has_reconciled_accounting(claim_name):
        frappe.throw(
            _(
                "Journal Entry {0} is part of reconciled Supplier Claim {1}. "
                "Reverse the Supplier Claim accounting settlement first."
            ).format(doc.name, claim_name)
        )

@frappe.whitelist()
def audit_supplier_claim_accounting(claim_name: str):
    claim = frappe.get_doc("Supplier Claim", claim_name)
    claim.check_permission("read")
    rows = []
    for row in claim.invoices:
        rows.append(
            {
                "purchase_invoice": row.purchase_invoice,
                "included_amount": flt(row.included_amount),
                "is_return": bool(row.is_return),
                "outstanding_amount": flt(
                    frappe.db.get_value(
                        "Purchase Invoice", row.purchase_invoice, "outstanding_amount"
                    )
                ),
                "accounting_allocated_amount": flt(
                    row.get("accounting_allocated_amount")
                ),
                "accounting_status": row.get("accounting_status") or "Pending",
            }
        )

    payment = None
    if claim.payment_entry and frappe.db.exists("Payment Entry", claim.payment_entry):
        payment = frappe.db.get_value(
            "Payment Entry",
            claim.payment_entry,
            [
                "name",
                "docstatus",
                "payment_type",
                "party_type",
                "party",
                "paid_amount",
                "unallocated_amount",
                "custom_supplier_claim",
            ],
            as_dict=True,
        )

    return {
        "supplier_claim": claim.name,
        "claim_status": claim.status,
        "accounting_settlement_status": claim.get("accounting_settlement_status"),
        "system_claim_total": flt(claim.system_claim_total),
        "net_amount_to_pay": flt(claim.net_amount_to_pay),
        "settlement_discount_amount": flt(claim.settlement_discount_amount),
        "settlement_discount_account": claim.get("settlement_discount_account"),
        "settlement_discount_journal_entry": claim.get(
            "settlement_discount_journal_entry"
        ),
        "accounting_reconciliation_journal_entries": claim.get(
            "accounting_reconciliation_journal_entries"
        ),
        "payment_entry": payment,
        "invoices": rows,
        "all_claim_invoice_outstanding_zero": all(
            abs(flt(row["outstanding_amount"])) <= TOLERANCE for row in rows
        ),
    }


@frappe.whitelist()
def apply_supplier_claim_accounting_repair(
    claim_name: str,
    payment_entry: str | None = None,
):
    """Bench/administrator repair entry point with an explicit final commit."""
    result = settle_supplier_claim_accounting(
        claim_name, payment_entry=payment_entry, dry_run=False
    )
    frappe.db.commit()
    return result
