import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate


class SupplierClaim(Document):
    def validate(self):
        if self.period_from and self.period_to and getdate(self.period_from) > getdate(self.period_to):
            frappe.throw(_("Period From cannot be after Period To."))
        self._calculate_totals()

    def before_submit(self):
        self._calculate_totals()
        self._validate_invoice_rows_are_open()
        if not self.invoices:
            frappe.throw(_("Fetch at least one eligible supplier invoice."))
        if self.match_status != "Matched":
            frappe.throw(_("Supplier Printed Claim Total must match the System Claim Total exactly."))
        meta = frappe.get_meta("Purchase Invoice")
        for row in self.invoices:
            linked = frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim") if meta.has_field("custom_supplier_claim") else None
            if linked and linked != self.name:
                frappe.throw(_("Purchase Invoice {0} already belongs to Supplier Claim {1}.").format(row.purchase_invoice, linked))
        self.status = "Approved"

    def on_submit(self):
        meta = frappe.get_meta("Purchase Invoice")
        for row in self.invoices:
            if meta.has_field("custom_supplier_claim"):
                frappe.db.set_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim", self.name, update_modified=False)
        self._sync_return_cases(cancel=False)

    def on_update_after_submit(self):
        self._sync_return_cases(cancel=False)

    def before_cancel(self):
        if self.get("accounting_settlement_status") == "Reconciled":
            frappe.throw(
                _(
                    "Supplier Claim accounting is reconciled. Reverse the accounting settlement before cancelling the claim."
                )
            )

    def on_cancel(self):
        meta = frappe.get_meta("Purchase Invoice")
        for row in self.invoices:
            if meta.has_field("custom_supplier_claim") and frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim") == self.name:
                frappe.db.set_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim", None, update_modified=False)
        self._sync_return_cases(cancel=True)
        self.db_set("status", "Cancelled", update_modified=False)

    def _calculate_totals(self):
        positives = sum(flt(row.included_amount) for row in self.invoices if flt(row.included_amount) >= 0)
        returns = abs(sum(flt(row.included_amount) for row in self.invoices if flt(row.included_amount) < 0))
        system_total = positives - returns
        self.gross_claim_total = positives
        self.purchase_returns_total = returns
        self.system_claim_total = system_total
        printed = flt(self.supplier_printed_claim_total)
        self.match_status = "Matched" if self.supplier_printed_claim_total not in (None, "") and round(printed,2)==round(system_total,2) else ("Mismatch" if self.supplier_printed_claim_total not in (None, "") else "Not Checked")
        net = flt(self.net_amount_to_pay)
        if system_total <= 0:
            # A new claim may temporarily contain only the approved Debit Note.
            # Until positive supplier invoices are fetched, nothing is payable.
            if abs(net) > 0.005:
                frappe.throw(
                    _(
                        "Net Amount To Pay must be zero while the claim contains "
                        "only purchase returns / debit notes."
                    )
                )
            self.settlement_discount_amount = 0
            self.settlement_discount_percentage = 0
        else:
            if net < 0 or net > system_total:
                frappe.throw(
                    _("Net Amount To Pay must be between zero and the System Claim Total.")
                )
            self.settlement_discount_amount = system_total - net
            self.settlement_discount_percentage = (
                self.settlement_discount_amount / system_total * 100
            )

    def _validate_invoice_rows_are_open(self):
        """Validate that every claim row can still be settled now.

        Draft Supplier Claims may live for a while. During that time a debit note
        can be refunded in cash/bank or another invoice can be reconciled. The
        submitted Supplier Claim must therefore validate against the *live*
        Purchase Invoice outstanding amount, not against the stale child-row
        snapshot that was captured when the row was fetched.
        """
        meta = frappe.get_meta("Purchase Invoice")
        has_claim_link = meta.has_field("custom_supplier_claim")
        has_return_case_link = meta.has_field("custom_pharmacy_return_case")
        seen = set()
        tolerance = 0.01

        for row in self.invoices:
            if not row.purchase_invoice:
                continue

            if row.purchase_invoice in seen:
                frappe.throw(
                    _("Purchase Invoice {0} is duplicated in this Supplier Claim.").format(
                        frappe.bold(row.purchase_invoice)
                    )
                )
            seen.add(row.purchase_invoice)

            fields = [
                "name",
                "docstatus",
                "company",
                "supplier",
                "is_return",
                "grand_total",
                "outstanding_amount",
                "status",
            ]
            if has_claim_link:
                fields.append("custom_supplier_claim")
            if has_return_case_link:
                fields.append("custom_pharmacy_return_case")

            invoice = frappe.db.get_value(
                "Purchase Invoice",
                row.purchase_invoice,
                fields,
                as_dict=True,
            )
            if not invoice:
                frappe.throw(
                    _("Purchase Invoice {0} does not exist.").format(
                        frappe.bold(row.purchase_invoice)
                    )
                )
            if invoice.docstatus != 1:
                frappe.throw(
                    _("Purchase Invoice {0} must be submitted before it can be included in a Supplier Claim.").format(
                        frappe.bold(row.purchase_invoice)
                    )
                )
            if invoice.company != self.company or invoice.supplier != self.supplier:
                frappe.throw(
                    _("Purchase Invoice {0} belongs to another company or supplier.").format(
                        frappe.bold(row.purchase_invoice)
                    )
                )

            linked_claim = invoice.get("custom_supplier_claim") if has_claim_link else None
            if linked_claim and linked_claim != self.name:
                frappe.throw(
                    _("Purchase Invoice {0} already belongs to Supplier Claim {1}.").format(
                        frappe.bold(row.purchase_invoice), frappe.bold(linked_claim)
                    )
                )

            included = flt(row.included_amount)
            outstanding = flt(invoice.outstanding_amount)
            invoice_is_return = bool(invoice.is_return)

            if invoice_is_return or included < 0:
                if not invoice_is_return or included >= 0:
                    frappe.throw(
                        _("Purchase Invoice {0} is not a valid return credit row.").format(
                            frappe.bold(row.purchase_invoice)
                        )
                    )
                if outstanding >= -tolerance:
                    message = _(
                        "Purchase Return / Debit Note {0} has no open supplier credit outstanding and cannot be included in this Supplier Claim. It may already be refunded, reconciled, or settled."
                    ).format(frappe.bold(row.purchase_invoice))
                    case_name = invoice.get("custom_pharmacy_return_case") if has_return_case_link else None
                    if case_name:
                        case_state = frappe.db.get_value(
                            "Pharmacy Return Case",
                            case_name,
                            [
                                "operational_status",
                                "settlement_status",
                                "refund_payment_entry",
                                "remaining_settlement_amount",
                            ],
                            as_dict=True,
                        )
                        if case_state:
                            message += " " + _(
                                "Linked Return Case {0}: {1} / {2}; Refund Payment: {3}; Remaining: {4}."
                            ).format(
                                frappe.bold(case_name),
                                case_state.operational_status or "-",
                                case_state.settlement_status or "-",
                                case_state.refund_payment_entry or "-",
                                flt(case_state.remaining_settlement_amount),
                            )
                    frappe.throw(message)
                if abs(included) - abs(outstanding) > tolerance:
                    frappe.throw(
                        _(
                            "Included amount {0} for Purchase Return {1} exceeds its open supplier credit outstanding {2}."
                        ).format(
                            abs(included),
                            frappe.bold(row.purchase_invoice),
                            abs(outstanding),
                        )
                    )
            else:
                if outstanding <= tolerance:
                    frappe.throw(
                        _(
                            "Purchase Invoice {0} has no payable outstanding and cannot be included in this Supplier Claim."
                        ).format(frappe.bold(row.purchase_invoice))
                    )
                if included - outstanding > tolerance:
                    frappe.throw(
                        _(
                            "Included amount {0} for Purchase Invoice {1} exceeds its open payable outstanding {2}."
                        ).format(
                            included,
                            frappe.bold(row.purchase_invoice),
                            outstanding,
                        )
                    )

    def _return_case_settlement_base(self, case, row):
        note_total = abs(
            flt(
                frappe.db.get_value(
                    "Purchase Invoice",
                    row.purchase_invoice,
                    "grand_total",
                )
            )
        )
        if note_total:
            return note_total

        if case.return_type == "Regulatory Batch Recall":
            return flt(case.approved_return_value)

        return (
            flt(case.approved_return_value)
            or flt(case.requested_return_value)
            or abs(flt(row.included_amount))
        )

    def _status_before_claim(self, case):
        if case.return_type == "Return Against Invoice":
            if case.purchase_return:
                docstatus = frappe.db.get_value(
                    "Purchase Invoice",
                    case.purchase_return,
                    "docstatus",
                )
                if docstatus == 1:
                    return "Purchase Return Submitted"
                if docstatus == 0:
                    return "Purchase Return Draft Created"
            return "Under Review"

        if case.get("approved_debit_note"):
            docstatus = frappe.db.get_value(
                "Purchase Invoice",
                case.get("approved_debit_note"),
                "docstatus",
            )
            if docstatus == 1:
                return "Approved Debit Note Submitted"
            if docstatus == 0:
                return "Approved Debit Note Draft Created"

        return case.operational_status or "Under Review"

    def _claim_settlement_date(self):
        if self.payment_entry and frappe.db.exists("Payment Entry", self.payment_entry):
            posting_date = frappe.db.get_value(
                "Payment Entry", self.payment_entry, "posting_date"
            )
            if posting_date:
                return posting_date
        return nowdate()

    def _sync_return_cases(self, cancel=False):
        meta = frappe.get_meta("Purchase Invoice")
        if not meta.has_field("custom_pharmacy_return_case"):
            return

        for row in self.invoices:
            if not row.is_return:
                continue

            case_name = frappe.db.get_value(
                "Purchase Invoice",
                row.purchase_invoice,
                "custom_pharmacy_return_case",
            )
            if not case_name or not frappe.db.exists(
                "Pharmacy Return Case", case_name
            ):
                continue

            case = frappe.get_doc("Pharmacy Return Case", case_name)
            settlement_base = self._return_case_settlement_base(case, row)
            deduction = min(settlement_base, abs(flt(row.included_amount)))
            refund = flt(case.refund_amount)

            case.approved_return_value = settlement_base
            case.rejected_return_value = max(
                0.0, flt(case.requested_return_value) - settlement_base
            )

            if cancel:
                case.supplier_claim = None
                case.planned_claim_deduction_amount = 0
                case.claim_deduction_amount = 0
                case.settled_amount = refund
                case.remaining_settlement_amount = max(
                    0.0, settlement_base - refund
                )
                case.settlement_status = (
                    "Partially Settled"
                    if refund > 0
                    else "Credited to Supplier Account"
                )
                case.operational_status = self._status_before_claim(case)
                if case.meta.has_field("claim_utilization_status"):
                    case.claim_utilization_status = "Not Applied"
                if case.meta.has_field("claim_settlement_date"):
                    case.claim_settlement_date = None
                case.save(ignore_permissions=True)
                continue

            case.supplier_claim = self.name
            case.settlement_method = (
                "Mixed Settlement" if refund > 0 else "Deduct from Supplier Claim"
            )
            case.planned_claim_deduction_amount = deduction
            case.claim_deduction_amount = deduction
            case.settled_amount = deduction + refund
            case.remaining_settlement_amount = max(
                0.0, settlement_base - deduction - refund
            )

            claim_is_closed = (
                self.status == "Paid"
                and self.get("accounting_settlement_status") == "Reconciled"
            )
            full_claim_use = (
                deduction > 0
                and case.remaining_settlement_amount <= 0.01
            )

            if claim_is_closed:
                if full_claim_use:
                    case.settlement_status = "Settled Through Supplier Claim"
                    case.operational_status = "Financially Settled"
                    utilization = "Fully Utilized"
                else:
                    case.settlement_status = "Partially Settled"
                    case.operational_status = "Partially Settled"
                    utilization = "Partially Utilized"
                settlement_date = self._claim_settlement_date()
            else:
                case.settlement_status = (
                    "Claim Deduction Confirmed"
                    if case.remaining_settlement_amount <= 0.01
                    else "Partially Settled"
                )
                case.operational_status = "Claim Deduction Confirmed"
                utilization = "Confirmed in Submitted Claim"
                settlement_date = None

            if case.meta.has_field("claim_utilization_status"):
                case.claim_utilization_status = utilization
            if case.meta.has_field("claim_settlement_date"):
                case.claim_settlement_date = settlement_date

            case.save(ignore_permissions=True)


def _validate_claim_payment_entry(claim, payment_entry):
    # Kept as a compatibility wrapper for integrations that imported this helper.
    from pharma_erp.pharma_erp.supplier_claim_accounting import (
        build_supplier_claim_settlement_plan,
    )

    if not payment_entry:
        return None
    build_supplier_claim_settlement_plan(claim.name, payment_entry)
    return frappe.db.get_value(
        "Payment Entry",
        payment_entry,
        [
            "docstatus",
            "payment_type",
            "party_type",
            "party",
            "company",
            "posting_date",
            "paid_amount",
            "received_amount",
            "base_paid_amount",
            "unallocated_amount",
        ],
        as_dict=True,
    )


@frappe.whitelist()
def preview_claim_accounting_settlement(claim_name, payment_entry=None):
    from pharma_erp.pharma_erp.supplier_claim_accounting import (
        preview_supplier_claim_accounting,
    )

    return preview_supplier_claim_accounting(claim_name, payment_entry)


@frappe.whitelist()
def close_claim_as_paid(claim_name, payment_entry=None):
    from pharma_erp.pharma_erp.supplier_claim_accounting import (
        settle_supplier_claim_accounting,
    )

    claim = frappe.get_doc("Supplier Claim", claim_name)
    claim.check_permission("write")
    return settle_supplier_claim_accounting(
        claim_name,
        payment_entry or claim.payment_entry or None,
        dry_run=False,
    )


@frappe.whitelist()
def get_eligible_invoices(
    supplier,
    company,
    period_from,
    period_to,
    claim_basis="Supplier Invoice Date",
):
    if not frappe.has_permission("Purchase Invoice", "read"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)

    period_from = getdate(period_from)
    period_to = getdate(period_to)
    claim_basis = claim_basis or "Supplier Invoice Date"

    if claim_basis == "Posting Date":
        date_condition = "`posting_date` between %(period_from)s and %(period_to)s"
    else:
        # Supplier Invoice Date is preferred. For invoices/debit notes where
        # Bill Date is empty, Posting Date is the operational fallback.
        date_condition = (
            "coalesce(`bill_date`, `posting_date`) "
            "between %(period_from)s and %(period_to)s"
        )

    rows = frappe.db.sql(
        f"""
        select
            name,
            bill_no,
            bill_date,
            posting_date,
            grand_total,
            outstanding_amount,
            is_return,
            status
        from `tabPurchase Invoice`
        where supplier = %(supplier)s
          and company = %(company)s
          and docstatus = 1
          and abs(outstanding_amount) > 0.005
          and {date_condition}
        order by
            coalesce(bill_date, posting_date) asc,
            posting_date asc,
            name asc
        """,
        {
            "supplier": supplier,
            "company": company,
            "period_from": period_from,
            "period_to": period_to,
        },
        as_dict=True,
    )

    result = []
    meta = frappe.get_meta("Purchase Invoice")
    tolerance = 0.01
    for row in rows:
        classification = (
            frappe.db.get_value(
                "Purchase Invoice",
                row.name,
                "custom_payment_classification",
            )
            if meta.has_field("custom_payment_classification")
            else ""
        )
        excluded = (
            frappe.db.get_value(
                "Purchase Invoice",
                row.name,
                "custom_exclude_from_supplier_claim",
            )
            if meta.has_field("custom_exclude_from_supplier_claim")
            else 0
        )
        linked = (
            frappe.db.get_value(
                "Purchase Invoice",
                row.name,
                "custom_supplier_claim",
            )
            if meta.has_field("custom_supplier_claim")
            else ""
        )

        if linked or excluded:
            continue
        if classification and classification != "Claim Invoice" and not row.is_return:
            continue

        outstanding = flt(row.outstanding_amount)
        if row.is_return:
            # A return/debit note is eligible only while it still carries an
            # open supplier credit. Cash-refunded or reconciled returns have
            # outstanding_amount = 0 and must never be fetched into a claim.
            if outstanding >= -tolerance:
                continue
            amount = -abs(outstanding)
        else:
            # Positive supplier invoices are eligible only while payable.
            if outstanding <= tolerance:
                continue
            amount = outstanding

        result.append(
            {
                "purchase_invoice": row.name,
                "supplier_invoice_no": row.bill_no,
                "supplier_invoice_date": row.bill_date or row.posting_date,
                "posting_date": row.posting_date,
                "grand_total": flt(row.grand_total),
                "outstanding_amount": outstanding,
                "included_amount": amount,
                "is_return": row.is_return,
                "invoice_status": row.status,
            }
        )

    return result
