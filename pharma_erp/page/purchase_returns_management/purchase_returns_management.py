"""Operational API for Purchase Returns Management."""
from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

READ_ROLES = {
    "Purchase User", "Purchase Manager", "Accounts User", "Accounts Manager",
    "Stock User", "Stock Manager", "System Manager",
}
SPECIAL_WAREHOUSE_NAMES = {
    "recall": "Recall Quarantine",
    "expired": "Expired Drugs",
    "supplier": "Returns With Supplier",
}
PROGRESSIVE_RETURN_TYPES = {"Regulatory Batch Recall", "Expired Drugs Return"}


def _is_progressive_return_type(return_type: str | None) -> bool:
    return (return_type or "") in PROGRESSIVE_RETURN_TYPES


def _default_progressive_reason(return_type: str | None) -> str:
    return "Expired" if return_type == "Expired Drugs Return" else "Health Authority Recall"


def _progressive_quarantine_key(return_type: str | None) -> str:
    return "expired" if return_type == "Expired Drugs Return" else "recall"

VAT_KEYWORDS = (
    "vat",
    "value added",
    "value-added",
    "ضريبة القيمة",
    "القيمة المضافة",
)
VAT_ENTRY_MODES = (
    "No VAT",
    "Auto by VAT %",
    "VAT Per Unit",
    "Total VAT for Line",
)


def _normalize_purchase_invoice_vat_entry_mode(
    value: Any,
    taxable: bool = False,
) -> str:
    """Normalize legacy/custom VAT mode text before inserting mapped returns.

    Some historical Purchase Invoice Item rows contain malformed values such
    as ``Auto by VAT %/%``. Frappe validates Select values on insert, so a
    mapped Purchase Return must never copy that malformed text unchanged.
    """
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if text in VAT_ENTRY_MODES:
        return text

    lowered = text.lower()
    if "no vat" in lowered or "exempt" in lowered:
        return "No VAT"
    if "total" in lowered and "vat" in lowered:
        return "Total VAT for Line"
    if "per unit" in lowered and "vat" in lowered:
        return "VAT Per Unit"
    if "auto" in lowered and "vat" in lowered:
        return "Auto by VAT %"

    return "Auto by VAT %" if taxable else "No VAT"


def _require_read() -> None:
    if not READ_ROLES.intersection(set(frappe.get_roles())):
        frappe.throw(_("You are not permitted to access Purchase Returns Management."), frappe.PermissionError)
    if not frappe.has_permission("Purchase Invoice", "read"):
        frappe.throw(_("You are not permitted to read Purchase Invoices."), frappe.PermissionError)


def _require_create() -> None:
    _require_read()
    if not frappe.has_permission("Pharmacy Return Case", "create"):
        frappe.throw(_("You are not permitted to create Pharmacy Return Cases."), frappe.PermissionError)


def _parse(payload: Any) -> dict:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            frappe.throw(_("Invalid return payload."))
    if not isinstance(payload, dict):
        frappe.throw(_("Invalid return payload."))
    return dict(payload)


def _safe_json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _looks_like_vat(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return any(keyword in text for keyword in VAT_KEYWORDS)


def _clamp_discount(value: Any) -> float:
    return min(100.0, max(0.0, flt(value)))


def _pricing_pair(
    base_rate: Any,
    discount_percentage: Any,
    net_rate: Any,
    mode: str | None,
) -> tuple[float, float, float, str]:
    base = max(0.0, flt(base_rate))
    discount = _clamp_discount(discount_percentage)
    net = max(0.0, flt(net_rate))
    selected_mode = (
        mode
        if mode in {"Discount Percentage", "Net Unit Value"}
        else "Discount Percentage"
    )

    if base <= 0 and net > 0:
        base = net

    if selected_mode == "Net Unit Value":
        if base > 0:
            net = min(net, base)
            discount = _clamp_discount((base - net) * 100.0 / base)
        else:
            discount = 0.0
    else:
        net = base * (1.0 - discount / 100.0)

    return base, discount, net, selected_mode




def _pricing_pair_vat_aware(
    base_rate: Any,
    discount_percentage: Any,
    net_rate: Any,
    mode: str | None,
    vat_rate: Any,
    is_vat_taxable: Any,
) -> tuple[float, float, float, str]:
    # Approved values in the return page use Base Price as the supplier gross
    # price when the item is VAT-taxable. Therefore a discount percentage must
    # be applied to the gross price first, then the VAT-exclusive rate is derived.
    # Example: gross 100, VAT 14%, discount 20% -> gross credit 80,
    # net rate 70.175439, VAT 9.824561.
    base = max(0.0, flt(base_rate))
    discount = _clamp_discount(discount_percentage)
    net = max(0.0, flt(net_rate))
    selected_mode = (
        mode
        if mode in {"Discount Percentage", "Net Unit Value"}
        else "Discount Percentage"
    )
    vat = max(0.0, flt(vat_rate)) if cint(is_vat_taxable) else 0.0
    vat_factor = 1.0 + (vat / 100.0) if vat > 0 else 1.0

    if base <= 0 and net > 0:
        base = net * vat_factor

    if selected_mode == "Net Unit Value":
        if base > 0:
            max_net = base / vat_factor
            net = min(net, max_net)
            gross_equivalent = net * vat_factor
            discount = _clamp_discount((base - gross_equivalent) * 100.0 / base)
        else:
            discount = 0.0
    else:
        gross_after_discount = base * (1.0 - discount / 100.0)
        net = gross_after_discount / vat_factor

    return base, discount, net, selected_mode

def _default_company() -> str | None:
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.defaults.get_global_default("company")
        or frappe.db.get_value("Company", {}, "name", order_by="is_group asc, creation asc")
    )


def _default_warehouse(company: str | None) -> str | None:
    warehouse = frappe.defaults.get_user_default("Warehouse")
    if not warehouse and frappe.db.exists("DocType", "Pharmacy POS Settings"):
        warehouse = frappe.db.get_single_value("Pharmacy POS Settings", "default_warehouse")
    if warehouse and frappe.db.exists("Warehouse", warehouse):
        row = frappe.db.get_value("Warehouse", warehouse, ["company", "is_group", "disabled"], as_dict=True)
        if row and not row.is_group and not row.disabled and (not company or row.company == company):
            return warehouse
    if not company:
        return None
    special = set(filter(None, _special_warehouses(company).values()))
    rows = frappe.get_all(
        "Warehouse",
        filters={"company": company, "is_group": 0, "disabled": 0},
        fields=["name"],
        order_by="creation asc",
        limit_page_length=200,
    )
    for row in rows:
        if row.name not in special:
            return row.name
    return None


def _special_warehouses(company: str | None) -> dict[str, str | None]:
    if not company:
        return {key: None for key in SPECIAL_WAREHOUSE_NAMES}
    result = {}
    for key, warehouse_name in SPECIAL_WAREHOUSE_NAMES.items():
        result[key] = frappe.db.get_value(
            "Warehouse",
            {"company": company, "warehouse_name": warehouse_name, "is_group": 0},
            "name",
        )
    return result


def _sync_case_operational_status(doc) -> None:
    if not _is_progressive_return_type(doc.return_type):
        return

    protected_statuses = {"Financially Settled", "Closed", "Cancelled"}
    if doc.operational_status in protected_statuses:
        return

    quarantine_status = (
        frappe.db.get_value("Stock Entry", doc.quarantine_stock_entry, "docstatus")
        if doc.quarantine_stock_entry else None
    )
    handover_status = (
        frappe.db.get_value("Stock Entry", doc.get("handover_stock_entry"), "docstatus")
        if doc.get("handover_stock_entry") else None
    )
    rejection_status = (
        frappe.db.get_value("Stock Entry", doc.get("rejection_return_stock_entry"), "docstatus")
        if doc.get("rejection_return_stock_entry") else None
    )
    debit_note = (
        frappe.db.get_value(
            "Purchase Invoice",
            doc.get("approved_debit_note"),
            [
                "docstatus",
                "status",
                "grand_total",
                "rounded_total",
                "disable_rounded_total",
                "outstanding_amount",
                "is_return",
                "update_stock",
            ],
            as_dict=True,
        )
        if doc.get("approved_debit_note") else None
    )

    if quarantine_status == 1:
        quarantined_total = 0.0
        for row in doc.items:
            target_qty = flt(row.return_qty)
            quarantined_total += target_qty
            if flt(row.quarantined_qty) != target_qty:
                row.db_set("quarantined_qty", target_qty, update_modified=False)
                row.quarantined_qty = target_qty
        if flt(doc.quarantined_quantity) != quarantined_total:
            doc.db_set("quarantined_quantity", quarantined_total, update_modified=False)
            doc.quarantined_quantity = quarantined_total

    handed_over = sum(flt(row.delivered_qty) for row in doc.items)
    accepted = sum(flt(row.accepted_qty) for row in doc.items)
    rejected = sum(flt(row.rejected_qty) for row in doc.items)
    pending = max(0.0, handed_over - accepted - rejected)

    if handover_status == 1:
        if flt(doc.get("handed_over_quantity")) != handed_over:
            doc.db_set("handed_over_quantity", handed_over, update_modified=False)
            doc.handed_over_quantity = handed_over

        if rejection_status == 1:
            returned = 0.0
            for row in doc.items:
                target_qty = flt(row.rejected_qty)
                returned += target_qty
                if flt(row.rejected_returned_qty) != target_qty:
                    row.db_set("rejected_returned_qty", target_qty, update_modified=False)
                    row.rejected_returned_qty = target_qty
            if flt(doc.get("rejected_return_quantity")) != returned:
                doc.db_set("rejected_return_quantity", returned, update_modified=False)
                doc.rejected_return_quantity = returned

    totals = {
        "accepted_quantity": accepted,
        "rejected_quantity": rejected,
        "pending_response_quantity": pending,
    }
    for fieldname, value in totals.items():
        if abs(flt(doc.get(fieldname)) - value) > 0.000001:
            doc.db_set(fieldname, value, update_modified=False)
            setattr(doc, fieldname, value)

    if debit_note:
        note_amount, note_outstanding = _return_invoice_total_and_outstanding(debit_note)
        note_status = debit_note.status or (
            "Draft" if debit_note.docstatus == 0
            else "Submitted" if debit_note.docstatus == 1
            else "Cancelled"
        )
        note_values = {
            "approved_debit_note_amount": note_amount,
            "approved_debit_note_outstanding": note_outstanding,
            "approved_debit_note_status": note_status,
            "accepted_stock_finalized_quantity": accepted if debit_note.docstatus == 1 else 0,
        }
        for fieldname, value in note_values.items():
            current = doc.get(fieldname)
            changed = (
                abs(flt(current) - flt(value)) > 0.000001
                if fieldname != "approved_debit_note_status"
                else (current or "") != (value or "")
            )
            if changed:
                doc.db_set(fieldname, value, update_modified=False)
                setattr(doc, fieldname, value)

    desired = None
    if debit_note and debit_note.docstatus == 0:
        desired = "Approved Debit Note Draft Created"
    elif debit_note and debit_note.docstatus == 1:
        desired = "Approved Debit Note Submitted"
    elif rejection_status == 0:
        desired = "Rejection Return Draft Created"
    elif handover_status == 1:
        if handed_over <= 0:
            desired = "Handed Over"
        elif accepted <= 0 and rejected <= 0:
            desired = "Awaiting Supplier Approval"
        elif pending > 0.000001:
            desired = "Partially Accepted"
        elif accepted > 0 and rejected > 0:
            desired = "Partially Accepted"
        elif accepted + 0.000001 >= handed_over:
            desired = "Accepted"
        elif rejected + 0.000001 >= handed_over:
            desired = "Rejected"
        else:
            desired = "Partially Accepted"
    elif handover_status == 0:
        desired = "Handover Transfer Draft Created"
    elif quarantine_status == 1:
        desired = "Quarantined"
    elif quarantine_status == 0:
        desired = "Quarantine Transfer Draft Created"
    elif quarantine_status == 2:
        desired = "Under Review"

    if desired and doc.operational_status != desired:
        doc.db_set("operational_status", desired, update_modified=False)
        doc.operational_status = desired

def _case_settlement_document(doc) -> str | None:
    direct = doc.get("approved_debit_note") or doc.get("purchase_return")
    if direct and frappe.db.exists("Purchase Invoice", direct):
        return direct

    purchase_invoice_meta = frappe.get_meta("Purchase Invoice")

    # Best fallback: a return invoice explicitly linked to this return case.
    if purchase_invoice_meta.has_field("custom_pharmacy_return_case"):
        linked = frappe.db.get_value(
            "Purchase Invoice",
            {
                "custom_pharmacy_return_case": doc.name,
                "is_return": 1,
                "docstatus": ["<", 2],
            },
            "name",
            order_by="posting_date desc, creation desc",
        )
        if linked:
            return linked

    # Legacy fallback: inspect the linked Supplier Claim rows and locate
    # the return/debit note belonging to this case or original invoice.
    if doc.get("supplier_claim"):
        claim_rows = frappe.get_all(
            "Supplier Claim Invoice",
            filters={
                "parent": doc.get("supplier_claim"),
                "parenttype": "Supplier Claim",
                "is_return": 1,
            },
            fields=["purchase_invoice", "included_amount"],
            order_by="idx asc",
        )
        for row in claim_rows:
            purchase_invoice = row.purchase_invoice
            if not purchase_invoice:
                continue

            if purchase_invoice_meta.has_field("custom_pharmacy_return_case"):
                linked_case = frappe.db.get_value(
                    "Purchase Invoice",
                    purchase_invoice,
                    "custom_pharmacy_return_case",
                )
                if linked_case == doc.name:
                    return purchase_invoice

            if doc.return_type == "Return Against Invoice":
                note = frappe.db.get_value(
                    "Purchase Invoice",
                    purchase_invoice,
                    [
                        "return_against",
                        "supplier",
                        "company",
                        "is_return",
                        "docstatus",
                    ],
                    as_dict=True,
                )
                if (
                    note
                    and note.is_return
                    and note.docstatus < 2
                    and note.supplier == doc.supplier
                    and note.company == doc.company
                    and note.return_against == doc.original_purchase_invoice
                ):
                    return purchase_invoice

    # Last fallback for old Return Against Invoice records.
    if (
        doc.return_type == "Return Against Invoice"
        and doc.original_purchase_invoice
    ):
        return frappe.db.get_value(
            "Purchase Invoice",
            {
                "return_against": doc.original_purchase_invoice,
                "supplier": doc.supplier,
                "company": doc.company,
                "is_return": 1,
                "docstatus": ["<", 2],
            },
            "name",
            order_by="posting_date desc, creation desc",
        )

    return None


def _case_settlement_base(doc) -> float:
    financial_document = _case_settlement_document(doc)
    if financial_document and frappe.db.exists(
        "Purchase Invoice",
        financial_document,
    ):
        note = frappe.db.get_value(
            "Purchase Invoice",
            financial_document,
            [
                "docstatus",
                "is_return",
                "grand_total",
                "rounded_total",
                "disable_rounded_total",
                "outstanding_amount",
            ],
            as_dict=True,
        )
        if note and note.is_return and note.docstatus < 2:
            total, ignored_outstanding = _return_invoice_total_and_outstanding(note)
            return total

    if _is_progressive_return_type(doc.return_type):
        return flt(doc.approved_return_value)

    return (
        flt(doc.approved_return_value)
        or flt(doc.requested_return_value)
    )


def _case_status_before_claim(doc) -> str:
    if doc.return_type == "Return Against Invoice":
        purchase_return = doc.get("purchase_return")
        if purchase_return:
            status = frappe.db.get_value(
                "Purchase Invoice",
                purchase_return,
                "docstatus",
            )
            if status == 1:
                return "Purchase Return Submitted"
            if status == 0:
                return "Purchase Return Draft Created"
        return "Under Review"

    if doc.get("approved_debit_note"):
        status = frappe.db.get_value(
            "Purchase Invoice",
            doc.get("approved_debit_note"),
            "docstatus",
        )
        if status == 1:
            return "Approved Debit Note Submitted"
        if status == 0:
            return "Approved Debit Note Draft Created"

    return doc.operational_status or "Under Review"


def _get_case_refund_payment_entries(case_name: str) -> list[dict]:
    meta = frappe.get_meta("Payment Entry")
    if not meta.has_field("custom_pharmacy_return_case"):
        return []

    return frappe.get_all(
        "Payment Entry",
        filters={
            "custom_pharmacy_return_case": case_name,
            "docstatus": ["<", 2],
        },
        fields=[
            "name",
            "docstatus",
            "status",
            "payment_type",
            "posting_date",
            "mode_of_payment",
            "paid_from",
            "paid_to",
            "paid_amount",
            "received_amount",
            "reference_no",
            "reference_date",
            "custom_supplier_refund_method",
            "custom_supplier_refund_notes",
            "creation",
        ],
        order_by="creation asc",
        limit_page_length=0,
    )


def _refund_entry_amount(entry) -> float:
    if entry.payment_type != "Receive":
        return 0.0
    return abs(flt(entry.received_amount) or flt(entry.paid_amount))


def _sync_supplier_claim_settlement(doc) -> None:
    settlement_base = _case_settlement_base(doc)
    if settlement_base <= 0:
        return

    if abs(flt(doc.approved_return_value) - settlement_base) > 0.01:
        doc.db_set("approved_return_value", settlement_base, update_modified=False)
        doc.approved_return_value = settlement_base

    settlement_document = _case_settlement_document(doc)
    settlement_document_status = (
        frappe.db.get_value("Purchase Invoice", settlement_document, "docstatus")
        if settlement_document
        else None
    )

    claim = None
    planned_claim = 0.0
    confirmed_claim = 0.0
    claim_closed = False
    claim_settlement_date = None
    if doc.get("supplier_claim") and frappe.db.exists(
        "Supplier Claim", doc.get("supplier_claim")
    ):
        claim = frappe.db.get_value(
            "Supplier Claim",
            doc.get("supplier_claim"),
            ["docstatus", "status", "payment_entry"],
            as_dict=True,
        )
        claim_row_amount = (
            abs(
                flt(
                    frappe.db.get_value(
                        "Supplier Claim Invoice",
                        {
                            "parent": doc.get("supplier_claim"),
                            "parenttype": "Supplier Claim",
                            "purchase_invoice": settlement_document,
                        },
                        "included_amount",
                    )
                )
            )
            if settlement_document
            else 0
        )
        if claim.docstatus == 0:
            planned_claim = claim_row_amount or settlement_base
        elif claim.docstatus == 1:
            planned_claim = claim_row_amount
            confirmed_claim = min(settlement_base, claim_row_amount)
            claim_closed = claim.status == "Paid"
            if claim_closed:
                if claim.payment_entry and frappe.db.exists(
                    "Payment Entry", claim.payment_entry
                ):
                    claim_settlement_date = frappe.db.get_value(
                        "Payment Entry", claim.payment_entry, "posting_date"
                    )
                claim_settlement_date = claim_settlement_date or nowdate()

    refund_entries = _get_case_refund_payment_entries(doc.name)
    draft_entries = [entry for entry in refund_entries if entry.docstatus == 0]
    submitted_entries = [entry for entry in refund_entries if entry.docstatus == 1]

    draft_refund = sum(_refund_entry_amount(entry) for entry in draft_entries)
    confirmed_refund = sum(
        _refund_entry_amount(entry) for entry in submitted_entries
    )
    latest_entry = refund_entries[-1] if refund_entries else None

    remaining = max(0.0, settlement_base - confirmed_claim - confirmed_refund)
    confirmed_total = confirmed_claim + confirmed_refund

    if confirmed_claim > 0 or planned_claim > 0:
        settlement_method = (
            "Mixed Settlement"
            if confirmed_refund > 0 or draft_refund > 0
            else "Deduct from Supplier Claim"
        )
    elif confirmed_refund > 0 or draft_refund > 0:
        settlement_method = "Cash / Bank Refund"
    else:
        settlement_method = "Pending Settlement"

    if claim and claim.docstatus == 0:
        utilization_status = "Planned in Draft Claim"
    elif claim and claim.docstatus == 1 and claim_closed:
        utilization_status = (
            "Fully Utilized" if remaining <= 0.01 else "Partially Utilized"
        )
    elif claim and claim.docstatus == 1:
        utilization_status = "Confirmed in Submitted Claim"
    else:
        utilization_status = "Not Applied"

    if draft_entries:
        settlement_status = (
            "Mixed Settlement Draft"
            if confirmed_claim > 0 or planned_claim > 0 or confirmed_refund > 0
            else "Refund Draft"
        )
        desired = "Refund Payment Draft Created"
    elif claim_closed and confirmed_claim > 0:
        if remaining <= 0.01:
            settlement_status = "Settled Through Supplier Claim"
            desired = "Financially Settled"
        else:
            settlement_status = "Partially Settled"
            desired = "Partially Settled"
    elif remaining <= 0.01 and confirmed_refund > 0:
        settlement_status = "Settled"
        desired = "Financially Settled"
    elif confirmed_refund > 0:
        settlement_status = "Partially Settled"
        desired = "Partially Settled"
    elif claim and claim.docstatus == 0:
        settlement_status = "Claim Deduction Draft"
        desired = "Claim Deduction Draft Created"
    elif claim and claim.docstatus == 1:
        if remaining <= 0.01:
            settlement_status = "Claim Deduction Confirmed"
            desired = "Claim Deduction Confirmed"
        else:
            settlement_status = "Partially Settled"
            desired = "Claim Deduction Confirmed"
    elif claim and claim.docstatus == 2:
        settlement_status = (
            "Credited to Supplier Account"
            if settlement_document_status == 1
            else "Pending Settlement"
        )
        desired = _case_status_before_claim(doc)
    else:
        settlement_status = (
            "Credited to Supplier Account"
            if settlement_document_status == 1
            else "Pending Settlement"
        )
        desired = _case_status_before_claim(doc)

    latest_status = None
    latest_name = None
    if latest_entry:
        latest_name = latest_entry.name
        latest_status = latest_entry.status or (
            "Draft"
            if latest_entry.docstatus == 0
            else "Submitted"
            if latest_entry.docstatus == 1
            else "Cancelled"
        )

    values = {
        "settlement_method": settlement_method,
        "planned_claim_deduction_amount": planned_claim,
        "claim_deduction_amount": confirmed_claim,
        "refund_amount": confirmed_refund,
        "settled_amount": confirmed_total,
        "remaining_settlement_amount": remaining,
        "settlement_status": settlement_status,
        "claim_utilization_status": utilization_status,
        "claim_settlement_date": claim_settlement_date,
        "refund_payment_entry": latest_name,
        "refund_payment_entry_status": latest_status,
        "refund_entries_count": len(refund_entries),
        "refund_request_amount": draft_refund if draft_entries else 0,
    }

    text_fields = {
        "settlement_method",
        "settlement_status",
        "claim_utilization_status",
        "refund_payment_entry",
        "refund_payment_entry_status",
    }
    date_fields = {"claim_settlement_date"}
    for fieldname, value in values.items():
        if not doc.meta.has_field(fieldname):
            continue
        current = doc.get(fieldname)
        if fieldname in text_fields or fieldname in date_fields:
            changed = (current or "") != (value or "")
        else:
            changed = abs(flt(current) - flt(value)) > 0.000001
        if changed:
            doc.db_set(fieldname, value, update_modified=False)
            setattr(doc, fieldname, value)

    if (
        desired
        and doc.operational_status not in {"Closed", "Cancelled"}
        and doc.operational_status != desired
    ):
        doc.db_set("operational_status", desired, update_modified=False)
        doc.operational_status = desired


@frappe.whitelist()
def repair_all_return_case_claim_settlements():
    repaired = []
    skipped = []

    cases = frappe.get_all(
        "Pharmacy Return Case",
        filters={"supplier_claim": ["is", "set"]},
        fields=["name"],
        limit_page_length=0,
    )

    for row in cases:
        doc = frappe.get_doc("Pharmacy Return Case", row.name)
        financial_document = _case_settlement_document(doc)
        if not financial_document:
            skipped.append({
                "case": doc.name,
                "reason": "No linked return/debit note found",
            })
            continue

        note = frappe.db.get_value(
            "Purchase Invoice",
            financial_document,
            [
                "docstatus",
                "is_return",
                "grand_total",
                "return_against",
            ],
            as_dict=True,
        )
        if not note or not note.is_return or note.docstatus >= 2:
            skipped.append({
                "case": doc.name,
                "reason": "Financial document is not an active submitted/draft return",
            })
            continue

        if (
            doc.return_type == "Return Against Invoice"
            and not doc.get("purchase_return")
        ):
            doc.db_set(
                "purchase_return",
                financial_document,
                update_modified=False,
            )
            doc.purchase_return = financial_document

        _sync_supplier_claim_settlement(doc)

        repaired.append({
            "case": doc.name,
            "financial_document": financial_document,
            "approved_value": flt(doc.approved_return_value),
            "claim_deduction": flt(doc.claim_deduction_amount),
            "remaining": flt(doc.remaining_settlement_amount),
            "settlement_status": doc.settlement_status,
        })

    frappe.db.commit()
    return {
        "repaired": repaired,
        "skipped": skipped,
        "repaired_count": len(repaired),
        "skipped_count": len(skipped),
    }




def _parse_filter_date(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    ddmmyyyy = re.match(r"^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})$", text)
    if ddmmyyyy:
        day, month, year = ddmmyyyy.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    yyyymmdd = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if yyyymmdd:
        year, month, day = yyyymmdd.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return None


def _normalize_smart_search(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u0600-\u06ff]+", "", str(value or "").lower())


def _without_english_vowels(value: str) -> str:
    return re.sub(r"[aeiou]", "", value)


def _smart_search_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9\u0600-\u06ff]+", str(value or "").lower()) if token]


def _ordered_chars_match(needle: str, haystack: str) -> bool:
    pos = 0
    for ch in needle:
        found = haystack.find(ch, pos)
        if found < 0:
            return False
        pos = found + 1
    return True


def _smart_text_matches(query: str | None, values: list[Any]) -> bool:
    raw = str(query or "").strip().lower()
    if not raw:
        return True
    hay = " | ".join(str(v or "") for v in values).lower()
    compact_hay = _normalize_smart_search(hay)
    compact_query = _normalize_smart_search(raw)
    hay_no_vowels = _without_english_vowels(compact_hay)
    query_no_vowels = _without_english_vowels(compact_query)
    if raw in hay:
        return True
    if compact_query and compact_query in compact_hay:
        return True
    if query_no_vowels and query_no_vowels in hay_no_vowels:
        return True
    tokens = _smart_search_tokens(raw)
    if tokens:
        token_match = True
        for token in tokens:
            compact_token = _normalize_smart_search(token)
            token_no_vowels = _without_english_vowels(compact_token)
            if not (
                token in hay
                or (compact_token and compact_token in compact_hay)
                or (token_no_vowels and token_no_vowels in hay_no_vowels)
            ):
                token_match = False
                break
        if token_match:
            return True
    if compact_query and _ordered_chars_match(compact_query, compact_hay):
        return True
    if query_no_vowels and _ordered_chars_match(query_no_vowels, hay_no_vowels):
        return True
    return False


def _recent_cases(company: str | None, limit: int = 50, search_text: str | None = None, from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    from_date = _parse_filter_date(from_date) or None
    to_date = _parse_filter_date(to_date) or None
    filters = []
    if company:
        filters.append(["company", "=", company])
    if from_date:
        filters.append(["posting_date", ">=", from_date])
    if to_date:
        filters.append(["posting_date", "<=", to_date])
    rows = frappe.get_list(
        "Pharmacy Return Case",
        filters=filters,
        fields=[
            "name", "posting_date", "return_type", "supplier", "original_purchase_invoice",
            "purchase_return", "quarantine_stock_entry", "handover_stock_entry",
            "rejection_return_stock_entry", "approved_debit_note",
            "approved_debit_note_amount", "approved_debit_note_outstanding",
            "approved_debit_note_status", "supplier_claim",
            "settlement_status", "planned_claim_deduction_amount",
            "claim_utilization_status", "claim_settlement_date",
            "claim_deduction_amount", "refund_amount", "settled_amount",
            "remaining_settlement_amount", "refund_payment_entry",
            "refund_payment_entry_status", "refund_entries_count",
            "operational_status",
            "requested_return_value", "approved_return_value", "settlement_method",
            "handed_over_quantity", "accepted_quantity", "rejected_quantity",
            "pending_response_quantity", "modified",
        ],
        order_by="modified desc",
        limit_page_length=max(1, min(cint(limit) or 20, 300)),
    )
    def _supplier_invoice_no(purchase_invoice: str | None) -> str | None:
        if not purchase_invoice:
            return None
        return frappe.db.get_value("Purchase Invoice", purchase_invoice, "bill_no")

    for row in rows:
        case_doc = frappe.get_doc("Pharmacy Return Case", row.name)
        _sync_supplier_claim_settlement(case_doc)
        for fieldname in (
            "purchase_return",
            "approved_return_value",
            "claim_deduction_amount",
            "planned_claim_deduction_amount",
            "refund_amount",
            "refund_payment_entry",
            "refund_payment_entry_status",
            "refund_entries_count",
            "settled_amount",
            "remaining_settlement_amount",
            "settlement_status",
            "claim_utilization_status",
            "claim_settlement_date",
            "operational_status",
        ):
            row[fieldname] = case_doc.get(fieldname)

        row.original_supplier_invoice_no = _supplier_invoice_no(row.get("original_purchase_invoice"))
        row.return_supplier_invoice_no = _supplier_invoice_no(row.get("purchase_return"))
        row.debit_note_supplier_invoice_no = _supplier_invoice_no(row.get("approved_debit_note"))

        settlement_status = row.get("settlement_status") or ""
        settlement_operational_status = {
            "Claim Deduction Draft": "Claim Deduction Draft Created",
            "Claim Deduction Confirmed": "Claim Deduction Confirmed",
            "Refund Draft": "Refund Payment Draft Created",
            "Refund Confirmed": "Refund Payment Submitted",
            "Mixed Settlement Draft": "Refund Payment Draft Created",
            "Mixed Settlement Confirmed": "Mixed Settlement Confirmed",
            "Partially Settled": "Partially Settled",
            "Settled Through Supplier Claim": "Financially Settled",
            "Settled": "Financially Settled",
        }.get(settlement_status)

        if settlement_operational_status:
            # Financial settlement state has priority over the earlier
            # stock / supplier-response / Debit Note workflow states.
            row.operational_status = settlement_operational_status

        elif _is_progressive_return_type(row.return_type):
            debit_note = (
                frappe.db.get_value(
                    "Purchase Invoice",
                    row.get("approved_debit_note"),
                    ["docstatus", "status", "grand_total", "rounded_total", "disable_rounded_total", "outstanding_amount"],
                    as_dict=True,
                )
                if row.get("approved_debit_note") else None
            )
            rejection_status = (
                frappe.db.get_value("Stock Entry", row.get("rejection_return_stock_entry"), "docstatus")
                if row.get("rejection_return_stock_entry") else None
            )
            handover_status = (
                frappe.db.get_value("Stock Entry", row.get("handover_stock_entry"), "docstatus")
                if row.get("handover_stock_entry") else None
            )
            quarantine_status = (
                frappe.db.get_value("Stock Entry", row.quarantine_stock_entry, "docstatus")
                if row.quarantine_stock_entry else None
            )
            if debit_note and debit_note.docstatus == 0:
                row.operational_status = "Approved Debit Note Draft Created"
                note_amount, note_outstanding = _return_invoice_total_and_outstanding(debit_note)
                row.approved_debit_note_amount = note_amount
                row.approved_debit_note_outstanding = note_outstanding
                row.approved_debit_note_status = debit_note.status or "Draft"
            elif debit_note and debit_note.docstatus == 1:
                row.operational_status = "Approved Debit Note Submitted"
                note_amount, note_outstanding = _return_invoice_total_and_outstanding(debit_note)
                row.approved_debit_note_amount = note_amount
                row.approved_debit_note_outstanding = note_outstanding
                row.approved_debit_note_status = debit_note.status or "Return"
            elif rejection_status == 0:
                row.operational_status = "Rejection Return Draft Created"
            elif handover_status == 1:
                handed = flt(row.handed_over_quantity)
                accepted = flt(row.accepted_quantity)
                rejected = flt(row.rejected_quantity)
                pending = max(0.0, handed - accepted - rejected)
                if accepted <= 0 and rejected <= 0:
                    row.operational_status = "Awaiting Supplier Approval"
                elif pending > 0.000001 or (accepted > 0 and rejected > 0):
                    row.operational_status = "Partially Accepted"
                elif accepted + 0.000001 >= handed:
                    row.operational_status = "Accepted"
                elif rejected + 0.000001 >= handed:
                    row.operational_status = "Rejected"
            elif handover_status == 0:
                row.operational_status = "Handover Transfer Draft Created"
            elif quarantine_status == 1:
                row.operational_status = "Quarantined"
            elif quarantine_status == 0:
                row.operational_status = "Quarantine Transfer Draft Created"
            elif quarantine_status == 2:
                row.operational_status = "Under Review"

    q = (search_text or "").strip()
    if q:
        def _matches(row):
            values = [
                row.get("name"), row.get("posting_date"), row.get("return_type"), row.get("supplier"),
                row.get("original_purchase_invoice"), row.get("purchase_return"),
                row.get("quarantine_stock_entry"), row.get("handover_stock_entry"),
                row.get("rejection_return_stock_entry"), row.get("approved_debit_note"),
                row.get("supplier_claim"), row.get("refund_payment_entry"),
                row.get("original_supplier_invoice_no"), row.get("return_supplier_invoice_no"),
                row.get("debit_note_supplier_invoice_no"), row.get("operational_status"),
                row.get("settlement_status"),
            ]
            return _smart_text_matches(q, values)
        rows = [row for row in rows if _matches(row)]

    return rows


@frappe.whitelist()
def get_bootstrap(company: str | None = None, purchase_invoice: str | None = None):
    _require_read()
    company = company or _default_company()
    result = {
        "company": company,
        "posting_date": nowdate(),
        "default_warehouse": _default_warehouse(company),
        "recent_cases": _recent_cases(company),
        "special_warehouses": _special_warehouses(company),
        "can_create_case": bool(frappe.has_permission("Pharmacy Return Case", "create")),
        "can_create_purchase_invoice": bool(frappe.has_permission("Purchase Invoice", "create")),
        "can_create_stock_entry": bool(frappe.has_permission("Stock Entry", "create")),
    }
    if purchase_invoice:
        result["invoice"] = get_invoice_for_return(purchase_invoice)
    return result


def _returned_qty_by_original_item(
    invoice_name: str,
    exclude_purchase_return: str | None = None,
) -> dict[str, float]:
    conditions = [
        "pi.return_against = %(invoice_name)s",
        "pi.is_return = 1",
        "pi.docstatus < 2",
        "ifnull(pii.purchase_invoice_item, '') != ''",
    ]
    values = {"invoice_name": invoice_name}
    if exclude_purchase_return:
        conditions.append("pi.name != %(exclude_purchase_return)s")
        values["exclude_purchase_return"] = exclude_purchase_return

    rows = frappe.db.sql(
        f"""
        select pii.purchase_invoice_item, sum(abs(pii.qty)) as returned_qty
        from `tabPurchase Invoice Item` pii
        inner join `tabPurchase Invoice` pi on pi.name = pii.parent
        where {' and '.join(conditions)}
        group by pii.purchase_invoice_item
        """,
        values,
        as_dict=True,
    )
    return {row.purchase_invoice_item: flt(row.returned_qty) for row in rows}


def _purchase_invoice_row_batch_no(row) -> str:
    """Return the trusted batch number stored on an original invoice row."""
    if row.meta.has_field("batch_no") and row.get("batch_no"):
        return row.get("batch_no") or ""
    if row.meta.has_field("custom_batch_number") and row.get("custom_batch_number"):
        return row.get("custom_batch_number") or ""
    return ""


def _item_has_batch_no(item_code: str | None) -> int:
    if not item_code:
        return 0
    return cint(frappe.db.get_value("Item", item_code, "has_batch_no"))


def _physical_stock_qty(
    item_code: str,
    warehouse: str | None,
    batch_no: str | None = None,
) -> float:
    """Return current sellable physical stock for an invoice-return source row.

    Batch stock must be checked at batch + warehouse level. For non-batched
    stock items, Bin.actual_qty is the authoritative current warehouse stock.
    Non-stock items are not constrained by warehouse stock.
    """
    if not item_code:
        return 0.0

    is_stock_item = cint(frappe.db.get_value("Item", item_code, "is_stock_item"))
    if not is_stock_item:
        return float("inf")
    if not warehouse:
        return 0.0

    if batch_no:
        from erpnext.stock.doctype.batch.batch import get_batch_qty

        qty = get_batch_qty(
            batch_no=batch_no,
            warehouse=warehouse,
            item_code=item_code,
            for_stock_levels=True,
            consider_negative_batches=True,
            ignore_reserved_stock=True,
        )
        return max(0.0, flt(qty))

    qty = frappe.db.get_value(
        "Bin",
        {"item_code": item_code, "warehouse": warehouse},
        "actual_qty",
    )
    return max(0.0, flt(qty))


def _invoice_return_stock_limits(original_row, already_returned_qty: float) -> dict:
    original_qty = abs(flt(original_row.qty))
    invoice_returnable_qty = max(0.0, original_qty - flt(already_returned_qty))
    warehouse = original_row.warehouse
    has_batch_no = _item_has_batch_no(original_row.item_code)
    batch_no = _purchase_invoice_row_batch_no(original_row) if has_batch_no else ""
    physical_stock_qty = _physical_stock_qty(
        original_row.item_code,
        warehouse,
        batch_no if has_batch_no else None,
    )
    if physical_stock_qty == float("inf"):
        physical_stock_qty = invoice_returnable_qty
    available_to_return_qty = max(
        0.0,
        min(invoice_returnable_qty, physical_stock_qty),
    )
    return {
        "original_qty": original_qty,
        "invoice_returnable_qty": invoice_returnable_qty,
        "physical_stock_qty": physical_stock_qty,
        "available_to_return_qty": available_to_return_qty,
        "warehouse": warehouse,
        "batch_no": batch_no,
        "has_batch_no": has_batch_no,
    }


def _vat_from_item_tax_template(template_name: str | None, company: str | None = None) -> dict:
    if not template_name or not frappe.db.exists("Item Tax Template", template_name):
        return {
            "is_vat_taxable": 0,
            "vat_rate": 0.0,
            "vat_account": None,
            "item_tax_template": template_name,
            "vat_source": "Not Taxable",
        }

    template = frappe.get_doc("Item Tax Template", template_name)
    positive = []
    for tax in template.get("taxes") or []:
        account = tax.get("tax_type")
        rate = flt(tax.get("tax_rate"))
        if rate <= 0:
            continue
        if company and account:
            account_company = frappe.db.get_value("Account", account, "company")
            if account_company and account_company != company:
                continue
        positive.append((account, rate))

    vat_rows = [row for row in positive if _looks_like_vat(row[0])]
    selected = vat_rows or (positive if len(positive) == 1 else [])
    if not selected:
        return {
            "is_vat_taxable": 0,
            "vat_rate": 0.0,
            "vat_account": None,
            "item_tax_template": template_name,
            "vat_source": "Item Tax Template - No VAT",
        }

    account, rate = selected[0]
    return {
        "is_vat_taxable": 1,
        "vat_rate": max(0.0, flt(rate)),
        "vat_account": account,
        "item_tax_template": template_name,
        "vat_source": f"Item Tax Template: {template_name}",
    }


def _item_default_vat_info(item_code: str, company: str | None = None) -> dict:
    if not item_code or not frappe.db.exists("Item", item_code):
        return _vat_from_item_tax_template(None, company)

    item_meta = frappe.get_meta("Item")
    if not item_meta.has_field("taxes"):
        return _vat_from_item_tax_template(None, company)

    rows = frappe.get_all(
        "Item Tax",
        filters={"parent": item_code, "parenttype": "Item"},
        fields=["item_tax_template", "tax_category", "valid_from", "idx"],
        order_by="valid_from desc, idx asc",
        limit_page_length=20,
    )
    for row in rows:
        if not row.item_tax_template:
            continue
        info = _vat_from_item_tax_template(row.item_tax_template, company)
        if info["is_vat_taxable"]:
            return info
    return _vat_from_item_tax_template(None, company)


def _purchase_invoice_item_vat_info(invoice, item_row) -> dict:
    net_amount = abs(flt(item_row.get("net_amount") or item_row.get("amount")))
    item_tax_amount = abs(flt(item_row.get("item_tax_amount")))
    item_tax_template = item_row.get("item_tax_template") or None

    rate_map = _safe_json_dict(item_row.get("item_tax_rate"))
    positive_rates = [
        (account, flt(rate))
        for account, rate in rate_map.items()
        if flt(rate) > 0
    ]
    vat_rates = [row for row in positive_rates if _looks_like_vat(row[0])]
    selected = vat_rates or (positive_rates if len(positive_rates) == 1 else [])
    if selected:
        account, rate = selected[0]
        return {
            "is_vat_taxable": 1,
            "vat_rate": max(0.0, flt(rate)),
            "vat_account": account,
            "item_tax_template": item_tax_template,
            "vat_source": f"Original Purchase Invoice: {invoice.name}",
        }

    detail_candidates = []
    for tax in invoice.get("taxes") or []:
        details = _safe_json_dict(tax.get("item_wise_tax_detail"))
        detail = details.get(item_row.item_code)
        if not detail:
            continue
        if isinstance(detail, (list, tuple)):
            rate = flt(detail[0]) if len(detail) > 0 else 0.0
            amount = abs(flt(detail[1])) if len(detail) > 1 else 0.0
        elif isinstance(detail, dict):
            rate = flt(detail.get("tax_rate") or detail.get("rate"))
            amount = abs(flt(detail.get("tax_amount") or detail.get("amount")))
        else:
            rate = 0.0
            amount = 0.0
        account = tax.get("account_head")
        if rate > 0 or amount > 0:
            detail_candidates.append((account, rate, amount))

    vat_details = [row for row in detail_candidates if _looks_like_vat(row[0])]
    selected_detail = vat_details or (
        detail_candidates if len(detail_candidates) == 1 else []
    )
    if selected_detail:
        account, rate, amount = selected_detail[0]
        if rate <= 0 and amount > 0 and net_amount > 0:
            rate = amount * 100.0 / net_amount
        return {
            "is_vat_taxable": 1,
            "vat_rate": max(0.0, flt(rate)),
            "vat_account": account,
            "item_tax_template": item_tax_template,
            "vat_source": f"Original Purchase Invoice: {invoice.name}",
        }

    if item_tax_amount > 0 and net_amount > 0:
        return {
            "is_vat_taxable": 1,
            "vat_rate": item_tax_amount * 100.0 / net_amount,
            "vat_account": None,
            "item_tax_template": item_tax_template,
            "vat_source": f"Original Purchase Invoice: {invoice.name}",
        }

    if item_tax_template:
        template_info = _vat_from_item_tax_template(
            item_tax_template,
            invoice.company,
        )
        if template_info["is_vat_taxable"]:
            template_info["vat_source"] = f"Original Purchase Invoice: {invoice.name}"
            return template_info

    return {
        "is_vat_taxable": 0,
        "vat_rate": 0.0,
        "vat_account": None,
        "item_tax_template": item_tax_template,
        "vat_source": f"Original Purchase Invoice: {invoice.name} - Not Taxable",
    }


def _pricing_from_purchase_invoice_row(invoice, item_row) -> dict:
    base_rate = abs(flt(item_row.get("price_list_rate") or item_row.get("rate")))
    net_rate = abs(flt(item_row.get("net_rate") or item_row.get("rate")))
    if base_rate <= 0:
        base_rate = net_rate
    discount_percentage = (
        _clamp_discount((base_rate - net_rate) * 100.0 / base_rate)
        if base_rate > 0
        else 0.0
    )
    vat = _purchase_invoice_item_vat_info(invoice, item_row)
    return {
        "base_rate": base_rate,
        "discount_percentage": discount_percentage,
        "pricing_input_mode": "Net Unit Value",
        "rate": net_rate,
        **vat,
    }


def _latest_purchase_pricing(
    item_code: str,
    batch_no: str,
    company: str,
    supplier: str | None = None,
) -> dict:
    meta = frappe.get_meta("Purchase Invoice Item")
    fields = {df.fieldname for df in meta.fields if df.fieldname}
    batch_field = (
        "batch_no"
        if "batch_no" in fields
        else "custom_batch_number"
        if "custom_batch_number" in fields
        else None
    )
    batch_condition = ""
    supplier_condition = ""
    values: list[Any] = [company, item_code]
    if supplier:
        supplier_condition = " and pi.supplier = %s"
        values.append(supplier)
    if batch_field and batch_no:
        batch_condition = f" and pii.`{batch_field}` = %s"
        values.append(batch_no)
    rows = frappe.db.sql(
        f"""
        select pii.name, pii.parent
        from `tabPurchase Invoice Item` pii
        inner join `tabPurchase Invoice` pi on pi.name = pii.parent
        where pi.docstatus = 1 and ifnull(pi.is_return, 0) = 0
          and pi.company = %s and pii.item_code = %s
          {supplier_condition}
          {batch_condition}
        order by pi.posting_date desc, pi.posting_time desc, pi.creation desc
        limit 1
        """,
        values,
        as_dict=True,
    )
    if rows:
        invoice = frappe.get_doc("Purchase Invoice", rows[0].parent)
        item_row = next((row for row in invoice.items if row.name == rows[0].name), None)
        if item_row:
            result = _pricing_from_purchase_invoice_row(invoice, item_row)
            result["source_purchase_invoice"] = invoice.name
            return result

    vat = _item_default_vat_info(item_code, company)
    return {
        "base_rate": 0.0,
        "discount_percentage": 0.0,
        "pricing_input_mode": "Discount Percentage",
        "rate": 0.0,
        "source_purchase_invoice": None,
        **vat,
    }


def _trusted_row_vat(
    item_code: str,
    batch_no: str | None,
    company: str,
    supplier: str | None = None,
) -> dict:
    pricing = _latest_purchase_pricing(
        item_code, batch_no or "", company, supplier
    )
    return {
        key: pricing.get(key)
        for key in (
            "is_vat_taxable",
            "vat_rate",
            "vat_account",
            "item_tax_template",
            "vat_source",
        )
    }


@frappe.whitelist()
def get_invoice_for_return(name: str):
    _require_read()
    if not name or not frappe.db.exists("Purchase Invoice", name):
        frappe.throw(_("Purchase Invoice does not exist."))
    doc = frappe.get_doc("Purchase Invoice", name)
    if doc.docstatus != 1:
        frappe.throw(_("Only submitted Purchase Invoices can be returned."))
    if cint(doc.is_return):
        frappe.throw(_("A return document cannot be used as the original invoice."))

    returned = _returned_qty_by_original_item(doc.name)
    item_meta = frappe.get_meta("Purchase Invoice Item")
    item_fields = {df.fieldname for df in item_meta.fields if df.fieldname}
    result_items = []
    for row in doc.items:
        already = flt(returned.get(row.name))
        limits = _invoice_return_stock_limits(row, already)
        batch_no = limits["batch_no"]
        has_batch_no = cint(limits.get("has_batch_no"))
        expiry_date = (row.get("custom_expiry_date") if "custom_expiry_date" in item_fields else None) if has_batch_no else None
        pricing = _pricing_from_purchase_invoice_row(doc, row)
        result_items.append({
            "original_purchase_invoice_item": row.name,
            "item_code": row.item_code,
            "item_name": row.item_name,
            "description": row.description,
            "warehouse": limits["warehouse"],
            "batch_no": batch_no,
            "has_batch_no": has_batch_no,
            "expiry_date": expiry_date,
            "stock_uom": row.stock_uom or row.uom,
            "original_qty": limits["original_qty"],
            "already_returned_qty": already,
            "invoice_returnable_qty": limits["invoice_returnable_qty"],
            "physical_stock_qty": limits["physical_stock_qty"],
            "available_to_return_qty": limits["available_to_return_qty"],
            "return_qty": 0,
            "base_rate": pricing["base_rate"],
            "discount_percentage": pricing["discount_percentage"],
            "pricing_input_mode": pricing["pricing_input_mode"],
            "rate": pricing["rate"],
            "is_vat_taxable": pricing["is_vat_taxable"],
            "vat_rate": pricing["vat_rate"],
            "vat_account": pricing["vat_account"],
            "item_tax_template": pricing["item_tax_template"],
            "vat_source": pricing["vat_source"],
            "net_return_amount": 0,
            "tax_amount": 0,
            "return_amount": 0,
            "return_reason": "Normal Return",
            "notes": "",
        })

    return {
        "name": doc.name,
        "company": doc.company,
        "supplier": doc.supplier,
        "supplier_name": doc.supplier_name,
        "posting_date": doc.posting_date,
        "bill_no": doc.bill_no,
        "currency": doc.currency,
        "grand_total": doc.grand_total,
        "update_stock": cint(doc.update_stock),
        "items": result_items,
    }


def _stock_valuation_rate(item_code: str, warehouse: str, batch_no: str | None = None) -> float:
    filters = {
        "item_code": item_code,
        "warehouse": warehouse,
        "is_cancelled": 0,
    }
    if batch_no:
        filters["batch_no"] = batch_no
    rows = frappe.get_all(
        "Stock Ledger Entry",
        filters=filters,
        fields=["valuation_rate"],
        order_by="posting_date desc, posting_time desc, creation desc",
        limit_page_length=1,
    )
    rate = rows[0].valuation_rate if rows else None
    if rate is None:
        rate = frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            "valuation_rate",
        )
    return flt(rate)



def _recall_search_pattern(txt: str | None) -> tuple[str, str, str]:
    """Use the tolerant Pharmacy POS / Sales search behaviour."""
    raw = (txt or "").strip()
    tokens = [token for token in re.split(r"[\s*%]+", raw) if token]
    like_pattern = "%" + "%".join(tokens) + "%" if tokens else "%"
    compact = re.sub(r"[\s*%_-]+", "", raw).lower()
    return raw, like_pattern, compact


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_recall_items(doctype, txt, searchfield, start, page_len, filters):
    """Search recalled items using the pharmacy-wide item search behaviour.

    Supports item code, English/Arabic name, aliases, keywords, barcode,
    spaces, percent signs and asterisks. Only batch-controlled items with
    positive stock in the selected source warehouse are returned.
    """
    _require_read()
    raw, like_txt, compact_txt = _recall_search_pattern(txt)
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    warehouse = (filters.get("warehouse") or "").strip()
    company = (filters.get("company") or "").strip()
    if not warehouse or not frappe.db.exists("Warehouse", warehouse):
        return []

    wh = frappe.db.get_value(
        "Warehouse", warehouse, ["company", "is_group", "disabled"], as_dict=True
    )
    if not wh or wh.is_group or wh.disabled or (company and wh.company != company):
        return []

    item_meta = frappe.get_meta("Item")
    arabic_field = (
        "custom_item_name_ar"
        if item_meta.has_field("custom_item_name_ar")
        else None
    )
    keywords_field = None
    for candidate in ("custom_search_keywords", "custom_search_keywords__aliases"):
        if item_meta.has_field(candidate):
            keywords_field = candidate
            break

    arabic_sql = f"i.`{arabic_field}`" if arabic_field else "''"
    keywords_sql = f"i.`{keywords_field}`" if keywords_field else "''"
    start = max(cint(start), 0)
    page_len = max(1, min(cint(page_len) or 20, 100))

    return frappe.db.sql(
        f"""
        SELECT
            i.name,
            i.item_name,
            {arabic_sql} AS item_name_ar,
            SUM(bin.actual_qty) AS actual_qty,
            i.stock_uom
        FROM `tabItem` i
        INNER JOIN `tabBin` bin
            ON bin.item_code = i.name
           AND bin.warehouse = %(warehouse)s
           AND bin.actual_qty > 0
        LEFT JOIN `tabItem Barcode` ib ON ib.parent = i.name
        WHERE IFNULL(i.disabled, 0) = 0
          AND IFNULL(i.has_batch_no, 0) = 1
          AND (
              i.name LIKE %(like_txt)s
              OR IFNULL(i.item_name, '') LIKE %(like_txt)s
              OR IFNULL({arabic_sql}, '') LIKE %(like_txt)s
              OR IFNULL({keywords_sql}, '') LIKE %(like_txt)s
              OR IFNULL(ib.barcode, '') LIKE %(like_txt)s
              OR REPLACE(REPLACE(LOWER(IFNULL(i.item_name, '')), ' ', ''), '-', '') LIKE %(compact_like)s
              OR REPLACE(REPLACE(LOWER(IFNULL({arabic_sql}, '')), ' ', ''), '-', '') LIKE %(compact_like)s
              OR REPLACE(REPLACE(LOWER(IFNULL({keywords_sql}, '')), ' ', ''), '-', '') LIKE %(compact_like)s
          )
        GROUP BY i.name, i.item_name, {arabic_sql}, i.stock_uom
        HAVING SUM(bin.actual_qty) > 0
        ORDER BY
            MAX(CASE WHEN ib.barcode = %(raw)s THEN 0 ELSE 1 END),
            CASE WHEN i.name = %(raw)s THEN 0 ELSE 1 END,
            CASE WHEN LOWER(i.item_name) = LOWER(%(raw)s) THEN 0 ELSE 1 END,
            CASE WHEN LOWER(IFNULL({arabic_sql}, '')) = LOWER(%(raw)s) THEN 0 ELSE 1 END,
            CASE WHEN i.name LIKE %(starts)s THEN 0 ELSE 1 END,
            CASE WHEN i.item_name LIKE %(starts)s THEN 0 ELSE 1 END,
            i.item_name ASC, i.name ASC
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "raw": raw,
            "like_txt": like_txt,
            "compact_like": f"%{compact_txt}%",
            "starts": f"{raw}%",
            "warehouse": warehouse,
            "start": start,
            "page_len": page_len,
        },
    )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_recall_batches(doctype, txt, searchfield, start, page_len, filters):
    """Return only batches with positive stock for the selected item/warehouse."""
    _require_read()
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    item_code = (filters.get("item_code") or "").strip()
    warehouse = (filters.get("warehouse") or "").strip()
    company = (filters.get("company") or "").strip()
    if not item_code or not warehouse:
        return []
    if not frappe.db.exists("Item", item_code):
        return []

    wh = frappe.db.get_value(
        "Warehouse", warehouse, ["company", "is_group", "disabled"], as_dict=True
    )
    if not wh or wh.is_group or wh.disabled or (company and wh.company != company):
        return []

    raw = (txt or "").strip()
    like_txt = f"%{raw}%"
    candidates = frappe.db.sql(
        """
        SELECT name, expiry_date
        FROM `tabBatch`
        WHERE item = %(item_code)s
          AND IFNULL(disabled, 0) = 0
          AND (
              name LIKE %(like_txt)s
              OR IFNULL(CAST(expiry_date AS CHAR), '') LIKE %(like_txt)s
          )
        ORDER BY
            CASE WHEN name = %(raw)s THEN 0 ELSE 1 END,
            CASE WHEN name LIKE %(starts)s THEN 0 ELSE 1 END,
            expiry_date ASC,
            name ASC
        LIMIT 300
        """,
        {
            "item_code": item_code,
            "raw": raw,
            "starts": f"{raw}%",
            "like_txt": like_txt,
        },
        as_dict=True,
    )

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    positive = []
    for batch in candidates:
        qty = flt(
            get_batch_qty(
                batch_no=batch.name,
                warehouse=warehouse,
                item_code=item_code,
                for_stock_levels=True,
                consider_negative_batches=True,
                ignore_reserved_stock=True,
            )
        )
        if qty <= 0:
            continue
        positive.append([
            batch.name,
            batch.expiry_date or "",
            qty,
        ])

    start = max(cint(start), 0)
    page_len = max(1, min(cint(page_len) or 20, 100))
    return positive[start:start + page_len]


@frappe.whitelist()
def get_batch_stock_for_recall(
    batch_no: str,
    company: str | None = None,
    item_code: str | None = None,
    source_warehouse: str | None = None,
    supplier: str | None = None,
):
    _require_read()
    company = company or _default_company()
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Select a valid recalled Item first."))
    item = frappe.db.get_value(
        "Item", item_code,
        ["item_name", "stock_uom", "disabled", "has_batch_no"],
        as_dict=True,
    )
    if not item or item.disabled or not item.has_batch_no:
        frappe.throw(_("The selected item is disabled or is not batch controlled."))
    if not batch_no or not frappe.db.exists("Batch", {"name": batch_no, "item": item_code}):
        frappe.throw(_("Select a valid Batch No belonging to item {0}.").format(frappe.bold(item_code)))
    batch = frappe.db.get_value(
        "Batch", batch_no,
        ["name", "item", "item_name", "expiry_date", "disabled", "stock_uom"],
        as_dict=True,
    )
    if source_warehouse:
        warehouse = frappe.db.get_value(
            "Warehouse", source_warehouse,
            ["company", "is_group", "disabled"],
            as_dict=True,
        )
        if not warehouse or warehouse.company != company or warehouse.is_group or warehouse.disabled:
            frappe.throw(_("Select an active Source Warehouse for the same company."))
        if source_warehouse in set(filter(None, _special_warehouses(company).values())):
            frappe.throw(_("The Source Warehouse must be a normal sellable warehouse, not a quarantine or returns warehouse."))

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    special = set(filter(None, _special_warehouses(company).values()))
    balances = get_batch_qty(
        batch_no=batch_no,
        item_code=batch.item,
        for_stock_levels=True,
        consider_negative_batches=True,
        ignore_reserved_stock=True,
    ) or []
    pricing = _latest_purchase_pricing(
        batch.item, batch_no, company, supplier
    )
    expected_rate = flt(pricing.get("rate"))
    rows = []
    for balance in balances:
        warehouse_name = balance.get("warehouse")
        qty = flt(balance.get("qty"))
        if not warehouse_name or qty <= 0 or warehouse_name in special:
            continue
        if source_warehouse and warehouse_name != source_warehouse:
            continue
        warehouse_company = frappe.db.get_value("Warehouse", warehouse_name, "company")
        if warehouse_company != company:
            continue
        valuation_rate = _stock_valuation_rate(batch.item, warehouse_name, batch_no)
        rows.append({
            "item_code": batch.item,
            "item_name": item.item_name or batch.item_name or batch.item,
            "warehouse": warehouse_name,
            "batch_no": batch_no,
            "expiry_date": batch.expiry_date,
            "stock_uom": item.stock_uom or batch.stock_uom,
            "original_qty": qty,
            "already_returned_qty": 0,
            "available_to_return_qty": qty,
            "return_qty": qty,
            "stock_valuation_rate": valuation_rate,
            "stock_value": qty * valuation_rate,
            "base_rate": flt(pricing.get("base_rate")),
            "discount_percentage": flt(pricing.get("discount_percentage")),
            "pricing_input_mode": pricing.get("pricing_input_mode") or "Discount Percentage",
            "rate": expected_rate,
            "is_vat_taxable": cint(pricing.get("is_vat_taxable")),
            "vat_rate": flt(pricing.get("vat_rate")),
            "vat_account": pricing.get("vat_account"),
            "item_tax_template": pricing.get("item_tax_template"),
            "vat_source": pricing.get("vat_source"),
            "net_return_amount": qty * expected_rate,
            "tax_amount": qty * expected_rate * flt(pricing.get("vat_rate")) / 100.0 if cint(pricing.get("is_vat_taxable")) else 0,
            "return_amount": qty * expected_rate * (1.0 + flt(pricing.get("vat_rate")) / 100.0) if cint(pricing.get("is_vat_taxable")) else qty * expected_rate,
            "approved_discount_percentage": 0,
            "approved_pricing_input_mode": "Discount Percentage",
            "approved_rate": 0,
            "approved_net_amount": 0,
            "approved_tax_amount": 0,
            "approved_total_credit": 0,
            "return_reason": "Health Authority Recall",
            "notes": "",
        })
    if not rows:
        frappe.throw(_("No positive stock was found for batch {0} in normal warehouses.").format(frappe.bold(batch_no)))
    return {
        "batch_no": batch_no,
        "item_code": batch.item,
        "item_name": item.item_name or batch.item_name,
        "expiry_date": batch.expiry_date,
        "disabled": cint(batch.disabled),
        "estimated_rate": expected_rate,
        "pricing": pricing,
        "rows": rows,
    }


def _validate_invoice_case_payload(
    payload: dict,
    exclude_purchase_return: str | None = None,
) -> None:
    if payload.get("return_type") != "Return Against Invoice":
        return
    if not payload.get("original_purchase_invoice"):
        frappe.throw(_("Select the original Purchase Invoice."))
    invoice = frappe.get_doc("Purchase Invoice", payload.get("original_purchase_invoice"))
    if invoice.docstatus != 1 or cint(invoice.is_return):
        frappe.throw(_("Select a submitted original Purchase Invoice."))
    if payload.get("supplier") and payload.get("supplier") != invoice.supplier:
        frappe.throw(_("The receiving supplier must match the original invoice supplier for an invoice-linked return."))
    selected = [frappe._dict(row) for row in (payload.get("items") or []) if flt(row.get("return_qty")) > 0]
    if not selected:
        frappe.throw(_("Enter a return quantity for at least one item."))
    source = {row.name: row for row in invoice.items}
    already = _returned_qty_by_original_item(
        invoice.name,
        exclude_purchase_return=exclude_purchase_return,
    )
    for row in selected:
        original = source.get(row.original_purchase_invoice_item)
        if not original:
            frappe.throw(_("Invalid original invoice item in return rows."))

        limits = _invoice_return_stock_limits(
            original,
            flt(already.get(original.name)),
        )
        requested_qty = flt(row.return_qty)
        if requested_qty > limits["invoice_returnable_qty"] + 0.000001:
            frappe.throw(
                _("Return quantity for {0} cannot exceed the invoice-returnable quantity {1}.").format(
                    frappe.bold(original.item_code),
                    limits["invoice_returnable_qty"],
                )
            )
        if requested_qty > limits["physical_stock_qty"] + 0.000001:
            stock_reference = (
                _("batch {0} in warehouse {1}").format(
                    frappe.bold(limits["batch_no"]),
                    frappe.bold(limits["warehouse"]),
                )
                if limits["batch_no"]
                else _("warehouse {0}").format(frappe.bold(limits["warehouse"]))
            )
            frappe.throw(
                _(
                    "Return quantity for item {0} cannot exceed the current physical stock {1} in {2}. "
                    "Choose stock that is physically available, use the warehouse that actually holds it, "
                    "or correct the stock ledger before creating the Purchase Return."
                ).format(
                    frappe.bold(original.item_code),
                    limits["physical_stock_qty"],
                    stock_reference,
                )
            )
        if not row.get("return_reason"):
            frappe.throw(_("Select a return reason for item {0}.").format(frappe.bold(original.item_code)))


def _normalize_payload_row_pricing(
    payload: dict,
    row: frappe._dict,
    invoice=None,
    invoice_row=None,
) -> frappe._dict:
    return_type = payload.get("return_type") or "Return Against Invoice"

    if return_type == "Return Against Invoice":
        if not invoice or not invoice_row:
            frappe.throw(_("Original Purchase Invoice pricing could not be resolved."))
        source = _pricing_from_purchase_invoice_row(invoice, invoice_row)
        base_rate = source["base_rate"]
        discount_percentage = source["discount_percentage"]
        pricing_input_mode = source["pricing_input_mode"]
        net_rate = source["rate"]
        vat = {
            key: source.get(key)
            for key in (
                "is_vat_taxable",
                "vat_rate",
                "vat_account",
                "item_tax_template",
                "vat_source",
            )
        }
    else:
        base_rate, discount_percentage, net_rate, pricing_input_mode = _pricing_pair(
            row.get("base_rate"),
            row.get("discount_percentage"),
            row.get("rate"),
            row.get("pricing_input_mode"),
        )
        vat = _trusted_row_vat(
            row.get("item_code"),
            row.get("batch_no"),
            payload.get("company"),
            payload.get("supplier"),
        )

    return_qty = max(0.0, flt(row.get("return_qty")))
    vat_rate = flt(vat.get("vat_rate")) if cint(vat.get("is_vat_taxable")) else 0.0
    net_return_amount = return_qty * net_rate
    tax_amount = net_return_amount * vat_rate / 100.0
    return_amount = net_return_amount + tax_amount

    accepted_qty = max(0.0, flt(row.get("accepted_qty")))
    approved_input_present = (
        accepted_qty > 0
        or flt(row.get("approved_rate")) > 0
        or flt(row.get("approved_discount_percentage")) > 0
    )
    if approved_input_present:
        approved_rate_input = flt(row.get("approved_rate"))
        approved_discount_input = flt(row.get("approved_discount_percentage"))
        approved_mode_input = row.get("approved_pricing_input_mode")
        if accepted_qty > 0 and approved_rate_input <= 0 and approved_discount_input <= 0:
            approved_rate_input = net_rate
            approved_discount_input = discount_percentage
            approved_mode_input = "Net Unit Value"
        ignored_base_rate, approved_discount, approved_rate, approved_mode = _pricing_pair_vat_aware(
            base_rate,
            approved_discount_input,
            approved_rate_input,
            approved_mode_input,
            vat_rate,
            cint(vat.get("is_vat_taxable")),
        )
    else:
        approved_discount = 0.0
        approved_rate = 0.0
        approved_mode = "Discount Percentage"
    approved_net_amount = accepted_qty * approved_rate
    approved_tax_amount = approved_net_amount * vat_rate / 100.0
    approved_total_credit = approved_net_amount + approved_tax_amount

    row.update(
        {
            "base_rate": base_rate,
            "discount_percentage": discount_percentage,
            "pricing_input_mode": pricing_input_mode,
            "rate": net_rate,
            "is_vat_taxable": cint(vat.get("is_vat_taxable")),
            "vat_rate": vat_rate,
            "vat_account": vat.get("vat_account"),
            "item_tax_template": vat.get("item_tax_template"),
            "vat_source": vat.get("vat_source"),
            "net_return_amount": net_return_amount,
            "tax_amount": tax_amount,
            "return_amount": return_amount,
            "approved_discount_percentage": approved_discount,
            "approved_pricing_input_mode": approved_mode,
            "approved_rate": approved_rate,
            "approved_net_amount": approved_net_amount,
            "approved_tax_amount": approved_tax_amount,
            "approved_total_credit": approved_total_credit,
            "accepted_amount": approved_total_credit,
        }
    )
    return row


def _validate_regulatory_case_payload(payload: dict, validate_source_stock: bool = True) -> None:
    if not _is_progressive_return_type(payload.get("return_type")):
        return
    is_regulatory = payload.get("return_type") == "Regulatory Batch Recall"
    if is_regulatory:
        if not payload.get("authority_notification_no"):
            frappe.throw(_("Enter the Authority Notification Number."))
        if not payload.get("authority_notification_date"):
            frappe.throw(_("Enter the Authority Notification Date."))
    if not payload.get("recall_source_warehouse"):
        frappe.throw(_("Select the Source Warehouse."))
    quarantine = payload.get("recall_quarantine_warehouse")
    if not quarantine:
        frappe.throw(_("Select the Quarantine / Expired Drugs Warehouse."))
    warehouse = frappe.db.get_value("Warehouse", quarantine, ["company", "is_group", "disabled"], as_dict=True)
    if not warehouse or warehouse.company != payload.get("company") or warehouse.is_group or warehouse.disabled:
        frappe.throw(_("Select an active quarantine warehouse for the same company."))
    selected = [frappe._dict(row) for row in (payload.get("items") or []) if flt(row.get("return_qty")) > 0]
    if not selected:
        frappe.throw(_("Enter a return quantity for at least one warehouse row."))

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    for row in selected:
        if row.warehouse != payload.get("recall_source_warehouse"):
            frappe.throw(_("Return row warehouse must match the selected Source Warehouse."))
        if not row.batch_no or not frappe.db.exists("Batch", row.batch_no):
            frappe.throw(_("Select a valid Batch No for item {0}.").format(frappe.bold(row.item_code)))
        batch_item = frappe.db.get_value("Batch", row.batch_no, "item")
        if batch_item != row.item_code:
            frappe.throw(_("Batch {0} does not belong to item {1}.").format(frappe.bold(row.batch_no), frappe.bold(row.item_code)))
        if validate_source_stock:
            current = flt(get_batch_qty(
                batch_no=row.batch_no,
                warehouse=row.warehouse,
                item_code=row.item_code,
                for_stock_levels=True,
                consider_negative_batches=True,
                ignore_reserved_stock=True,
            ))
            if flt(row.return_qty) > current + 0.000001:
                frappe.throw(
                    _("Return quantity for batch {0} in {1} cannot exceed current stock {2}.").format(
                        frappe.bold(row.batch_no),
                        frappe.bold(row.warehouse),
                        current,
                    )
                )
        delivered = flt(row.get("delivered_qty"))
        quarantined = flt(row.get("quarantined_qty")) or flt(row.return_qty)
        if delivered < 0:
            frappe.throw(_("Handover quantity cannot be negative for batch {0}.").format(frappe.bold(row.batch_no)))
        if delivered > quarantined + 0.000001:
            frappe.throw(
                _("Handover quantity for batch {0} cannot exceed quarantined quantity {1}.").format(
                    frappe.bold(row.batch_no), quarantined
                )
            )

        accepted = flt(row.get("accepted_qty"))
        rejected = flt(row.get("rejected_qty"))
        approved_rate = flt(row.get("approved_rate"))
        base_rate = flt(row.get("base_rate"))
        discount_percentage = flt(row.get("discount_percentage"))
        approved_discount = flt(row.get("approved_discount_percentage"))
        net_rate = flt(row.get("rate"))
        if base_rate < 0 or net_rate < 0:
            frappe.throw(_("Return pricing cannot be negative."))
        if discount_percentage < 0 or discount_percentage > 100:
            frappe.throw(_("Discount Percentage must be between 0 and 100."))
        if approved_discount < 0 or approved_discount > 100:
            frappe.throw(_("Approved Discount Percentage must be between 0 and 100."))
        if base_rate > 0 and net_rate > base_rate + 0.000001:
            frappe.throw(_("Net Unit Value cannot exceed Base Price."))
        if base_rate > 0 and approved_rate > base_rate + 0.000001:
            frappe.throw(_("Approved Net Unit Value cannot exceed Base Price."))
        if accepted < 0 or rejected < 0 or approved_rate < 0:
            frappe.throw(_("Supplier response quantities and rate cannot be negative."))
        if accepted + rejected > delivered + 0.000001:
            frappe.throw(
                _("Accepted plus rejected quantity for batch {0} cannot exceed handed-over quantity {1}.").format(
                    frappe.bold(row.batch_no), delivered
                )
            )
        if accepted > 0 and approved_rate <= 0:
            frappe.throw(
                _("Approved Settlement Rate is required for accepted quantity in batch {0}.").format(
                    frappe.bold(row.batch_no)
                )
            )
        if rejected > 0 and not (row.get("rejection_reason") or "").strip():
            frappe.throw(
                _("Supplier Rejection Reason is required for batch {0}.").format(
                    frappe.bold(row.batch_no)
                )
            )


def _validate_locked_regulatory_rows(doc, payload: dict) -> None:
    if not _is_progressive_return_type(doc.return_type):
        return

    quarantine_status = (
        frappe.db.get_value("Stock Entry", doc.quarantine_stock_entry, "docstatus")
        if doc.quarantine_stock_entry else None
    )
    handover_status = (
        frappe.db.get_value("Stock Entry", doc.get("handover_stock_entry"), "docstatus")
        if doc.get("handover_stock_entry") else None
    )
    incoming = {
        (row.get("item_code"), row.get("batch_no"), row.get("warehouse")): frappe._dict(row)
        for row in (payload.get("items") or [])
        if flt(row.get("return_qty")) > 0
    }
    existing = {
        (row.item_code, row.batch_no, row.warehouse): row
        for row in doc.items
        if flt(row.return_qty) > 0
    }

    if quarantine_status == 1:
        if set(incoming) != set(existing):
            frappe.throw(_("Return lines cannot be added or removed after the quarantine transfer is submitted."))
        for key, old_row in existing.items():
            if abs(flt(incoming[key].return_qty) - flt(old_row.return_qty)) > 0.000001:
                frappe.throw(_("Return quantities cannot be changed after the quarantine transfer is submitted."))

    if handover_status == 1:
        for key, old_row in existing.items():
            if key not in incoming:
                frappe.throw(_("Handover lines cannot be removed after supplier handover is submitted."))
            if abs(flt(incoming[key].get("delivered_qty")) - flt(old_row.delivered_qty)) > 0.000001:
                frappe.throw(_("Handover quantities cannot be changed after supplier handover is submitted."))

    debit_note_status = (
        frappe.db.get_value(
            "Purchase Invoice",
            doc.get("approved_debit_note"),
            "docstatus",
        )
        if doc.get("approved_debit_note") else None
    )
    if debit_note_status in (0, 1):
        for key, old_row in existing.items():
            new_row = incoming.get(key)
            if not new_row:
                frappe.throw(_("Supplier response lines cannot be removed while the Approved Debit Note exists."))
            for fieldname in (
                "accepted_qty",
                "rejected_qty",
                "approved_discount_percentage",
                "approved_rate",
                "approved_net_amount",
                "approved_tax_amount",
                "approved_total_credit",
                "rejection_reason",
            ):
                old_value = old_row.get(fieldname) or ""
                new_value = new_row.get(fieldname) or ""
                if fieldname == "rejection_reason":
                    changed = str(new_value).strip() != str(old_value).strip()
                else:
                    changed = abs(flt(new_value) - flt(old_value)) > 0.000001
                if changed:
                    frappe.throw(
                        _("Supplier response cannot be changed while Approved Debit Note {0} exists.").format(
                            frappe.bold(doc.get("approved_debit_note"))
                        )
                    )

    rejection_status = (
        frappe.db.get_value(
            "Stock Entry",
            doc.get("rejection_return_stock_entry"),
            "docstatus",
        )
        if doc.get("rejection_return_stock_entry") else None
    )
    if rejection_status == 1:
        for key, old_row in existing.items():
            new_row = incoming.get(key)
            if not new_row:
                frappe.throw(_("Supplier response lines cannot be removed after rejected stock is returned."))
            # Once rejected stock has physically returned to quarantine, the supplier
            # decision itself is final, but the next workflow stage (approved pricing)
            # must remain editable until an Approved Debit Note exists.
            locked_fields = (
                "accepted_qty",
                "rejected_qty",
                "rejection_reason",
            )
            for fieldname in locked_fields:
                old_value = old_row.get(fieldname) or ""
                new_value = new_row.get(fieldname) or ""
                if fieldname != "rejection_reason":
                    changed = abs(flt(new_value) - flt(old_value)) > 0.000001
                else:
                    changed = str(new_value).strip() != str(old_value).strip()
                if changed:
                    frappe.throw(
                        _("Supplier response cannot be changed after rejected stock is returned to quarantine.")
                    )


def _set_case_values(doc, payload: dict) -> None:
    return_type = payload.get("return_type") or "Return Against Invoice"
    doc.return_type = return_type
    doc.company = payload.get("company")
    doc.posting_date = payload.get("posting_date") or nowdate()
    doc.supplier = payload.get("supplier")
    doc.original_purchase_invoice = payload.get("original_purchase_invoice") or None
    doc.settlement_method = payload.get("settlement_method") or "Pending Settlement"
    doc.remarks = payload.get("remarks") or ""
    doc.operational_status = doc.operational_status or "Draft"
    doc.authority_notification_no = payload.get("authority_notification_no") or None
    doc.authority_notification_date = payload.get("authority_notification_date") or None
    doc.authority_notification_attachment = payload.get("authority_notification_attachment") or None
    doc.recall_source_warehouse = payload.get("recall_source_warehouse") or None
    doc.recall_item_code = None
    default_quarantine_warehouse = (
        _special_warehouses(doc.company).get(_progressive_quarantine_key(return_type))
        if _is_progressive_return_type(return_type)
        else None
    )
    doc.recall_quarantine_warehouse = (
        payload.get("recall_quarantine_warehouse")
        or doc.get("recall_quarantine_warehouse")
        or default_quarantine_warehouse
        or None
    )
    doc.returns_with_supplier_warehouse = (
        payload.get("returns_with_supplier_warehouse")
        or doc.get("returns_with_supplier_warehouse")
        or _special_warehouses(doc.company).get("supplier")
        or None
    )
    doc.handover_date = payload.get("handover_date") or None
    doc.handover_reference = payload.get("handover_reference") or None
    doc.handover_attachment = payload.get("handover_attachment") or None
    doc.supplier_response_date = payload.get("supplier_response_date") or None
    doc.supplier_response_reference = payload.get("supplier_response_reference") or None
    doc.supplier_response_attachment = payload.get("supplier_response_attachment") or None
    doc.supplier_response_notes = payload.get("supplier_response_notes") or None
    doc.supplier_claim = payload.get("supplier_claim") or doc.get("supplier_claim") or None
    doc.refund_posting_date = payload.get("refund_posting_date") or doc.get("refund_posting_date") or nowdate()
    doc.refund_mode_of_payment = payload.get("refund_mode_of_payment") or doc.get("refund_mode_of_payment") or None
    doc.refund_account = payload.get("refund_account") or doc.get("refund_account") or None
    doc.refund_request_amount = flt(payload.get("refund_request_amount"))
    doc.refund_reference_no = payload.get("refund_reference_no") or None
    doc.refund_reference_date = payload.get("refund_reference_date") or None
    doc.refund_notes = payload.get("refund_notes") or None
    doc.approved_debit_note_posting_date = (
        payload.get("approved_debit_note_posting_date")
        or doc.get("approved_debit_note_posting_date")
        or payload.get("supplier_response_date")
        or None
    )
    invoice_doc = None
    invoice_rows = {}
    returned_by_original_item = {}
    if return_type == "Return Against Invoice" and doc.original_purchase_invoice:
        invoice_doc = frappe.get_doc("Purchase Invoice", doc.original_purchase_invoice)
        invoice_rows = {row.name: row for row in invoice_doc.items}
        returned_by_original_item = _returned_qty_by_original_item(
            doc.original_purchase_invoice,
            exclude_purchase_return=doc.get("purchase_return"),
        )

    doc.set("items", [])
    for source in payload.get("items") or []:
        row = frappe._dict(source)
        if flt(row.return_qty) <= 0:
            continue
        invoice_row = (
            invoice_rows.get(row.get("original_purchase_invoice_item"))
            if invoice_rows
            else None
        )
        row = _normalize_payload_row_pricing(
            payload,
            row,
            invoice=invoice_doc,
            invoice_row=invoice_row,
        )
        if invoice_row:
            limits = _invoice_return_stock_limits(
                invoice_row,
                flt(returned_by_original_item.get(invoice_row.name)),
            )
            row.warehouse = limits["warehouse"]
            row.batch_no = limits["batch_no"]
            row.has_batch_no = cint(limits.get("has_batch_no"))
            row.original_qty = limits["original_qty"]
            row.already_returned_qty = flt(
                returned_by_original_item.get(invoice_row.name)
            )
            row.invoice_returnable_qty = limits["invoice_returnable_qty"]
            row.physical_stock_qty = limits["physical_stock_qty"]
            row.available_to_return_qty = limits["available_to_return_qty"]
        doc.append("items", {
            "original_purchase_invoice_item": row.get("original_purchase_invoice_item"),
            "item_code": row.item_code,
            "item_name": row.item_name,
            "warehouse": row.warehouse,
            "batch_no": row.batch_no,
            "expiry_date": row.expiry_date,
            "stock_uom": row.stock_uom,
            "original_qty": flt(row.original_qty),
            "already_returned_qty": flt(row.already_returned_qty),
            "invoice_returnable_qty": flt(row.get("invoice_returnable_qty")),
            "physical_stock_qty": flt(row.get("physical_stock_qty")),
            "available_to_return_qty": flt(row.available_to_return_qty),
            "quarantine_warehouse": (
                payload.get("recall_quarantine_warehouse")
                if _is_progressive_return_type(return_type)
                else row.get("quarantine_warehouse")
            ),
            "return_qty": flt(row.return_qty),
            "stock_valuation_rate": flt(row.get("stock_valuation_rate")),
            "stock_value": flt(row.return_qty) * flt(row.get("stock_valuation_rate")),
            "base_rate": flt(row.get("base_rate")),
            "discount_percentage": flt(row.get("discount_percentage")),
            "pricing_input_mode": row.get("pricing_input_mode") or "Discount Percentage",
            "rate": flt(row.rate),
            "is_vat_taxable": cint(row.get("is_vat_taxable")),
            "vat_rate": flt(row.get("vat_rate")),
            "vat_account": row.get("vat_account"),
            "item_tax_template": row.get("item_tax_template"),
            "vat_source": row.get("vat_source"),
            "net_return_amount": flt(row.get("net_return_amount")),
            "tax_amount": flt(row.tax_amount),
            "return_amount": flt(row.get("return_amount")),
            "return_reason": _default_progressive_reason(return_type) if _is_progressive_return_type(return_type) else (row.return_reason or "Normal Return"),
            "delivered_qty": flt(row.get("delivered_qty")),
            "accepted_qty": flt(row.get("accepted_qty")),
            "rejected_qty": flt(row.get("rejected_qty")),
            "approved_discount_percentage": flt(row.get("approved_discount_percentage")),
            "approved_pricing_input_mode": row.get("approved_pricing_input_mode") or "Discount Percentage",
            "approved_rate": flt(row.get("approved_rate")),
            "approved_net_amount": flt(row.get("approved_net_amount")),
            "approved_tax_amount": flt(row.get("approved_tax_amount")),
            "approved_total_credit": flt(row.get("approved_total_credit")),
            "accepted_amount": flt(row.get("approved_total_credit")),
            "rejection_reason": row.get("rejection_reason") or "",
            "rejected_returned_qty": flt(row.get("rejected_returned_qty")),
            "notes": row.notes or "",
        })

    if _is_progressive_return_type(return_type):
        unique_items = sorted({row.item_code for row in doc.items if row.item_code})
        doc.recall_item_code = unique_items[0] if len(unique_items) == 1 else None


@frappe.whitelist()
def save_case(payload):
    _require_create()
    payload = _parse(payload)
    if not payload.get("company") or not frappe.db.exists("Company", payload.get("company")):
        frappe.throw(_("Select a valid company."))
    if not payload.get("supplier") or not frappe.db.exists("Supplier", payload.get("supplier")):
        frappe.throw(_("Select the company or distributor receiving the return."))

    doc = None
    quarantine_submitted = False
    if payload.get("name"):
        doc = frappe.get_doc("Pharmacy Return Case", payload.get("name"))
        if doc.docstatus != 0:
            frappe.throw(_("Only a draft Return Case can be edited."))
        _validate_locked_regulatory_rows(doc, payload)
        quarantine_submitted = bool(
            doc.quarantine_stock_entry
            and frappe.db.get_value(
                "Stock Entry",
                doc.quarantine_stock_entry,
                "docstatus",
            ) == 1
        )

    response_entered = any(
        flt(row.get("accepted_qty")) > 0
        or flt(row.get("rejected_qty")) > 0
        or flt(row.get("approved_rate")) > 0
        or bool((row.get("rejection_reason") or "").strip())
        for row in (payload.get("items") or [])
    )
    if response_entered:
        if not payload.get("supplier_response_date"):
            frappe.throw(_("Enter the Supplier Response Date."))
        if not payload.get("supplier_response_reference"):
            frappe.throw(_("Enter the Supplier Response Reference."))

    _validate_invoice_case_payload(
        payload,
        exclude_purchase_return=(doc.purchase_return if doc else None),
    )
    _validate_regulatory_case_payload(
        payload,
        validate_source_stock=not quarantine_submitted,
    )

    if doc is None:
        doc = frappe.new_doc("Pharmacy Return Case")

    _set_case_values(doc, payload)
    doc.save()
    return get_case(doc.name)


def _supplier_handover_schema_requirements():
    return {
        "Pharmacy Return Case": (
            "returns_with_supplier_warehouse",
            "handover_stock_entry",
            "handed_over_quantity",
            "supplier_response_date",
            "supplier_response_reference",
            "supplier_response_attachment",
            "supplier_response_notes",
            "accepted_quantity",
            "rejected_quantity",
            "pending_response_quantity",
            "rejection_return_stock_entry",
            "rejected_return_quantity",
            "approved_debit_note_posting_date",
            "approved_debit_note",
            "approved_debit_note_status",
            "approved_debit_note_amount",
            "approved_debit_note_outstanding",
            "accepted_stock_finalized_quantity",
            "supplier_claim",
            "settlement_status",
            "planned_claim_deduction_amount",
            "settled_amount",
            "refund_posting_date",
            "refund_mode_of_payment",
            "refund_account",
            "refund_request_amount",
            "refund_reference_no",
            "refund_reference_date",
            "refund_payment_entry",
            "refund_payment_entry_status",
            "refund_entries_count",
            "refund_notes",
        ),
        "Pharmacy Return Item": (
            "delivered_qty",
            "accepted_qty",
            "rejected_qty",
            "invoice_returnable_qty",
            "physical_stock_qty",
            "base_rate",
            "discount_percentage",
            "pricing_input_mode",
            "is_vat_taxable",
            "vat_rate",
            "vat_source",
            "vat_account",
            "item_tax_template",
            "net_return_amount",
            "approved_discount_percentage",
            "approved_pricing_input_mode",
            "approved_rate",
            "approved_net_amount",
            "approved_tax_amount",
            "approved_total_credit",
            "rejection_reason",
            "rejected_returned_qty",
        ),
    }


def _supplier_handover_doctype_files():
    return {
        "Pharmacy Return Case": frappe.get_app_path(
            "pharma_erp",
            "pharma_erp",
            "doctype",
            "pharmacy_return_case",
            "pharmacy_return_case.json",
        ),
        "Pharmacy Return Item": frappe.get_app_path(
            "pharma_erp",
            "pharma_erp",
            "doctype",
            "pharmacy_return_item",
            "pharmacy_return_item.json",
        ),
    }


def _sync_supplier_handover_schema():
    import json
    import os

    from frappe.modules.import_file import import_file_by_path

    requirements = _supplier_handover_schema_requirements()
    files = _supplier_handover_doctype_files()

    for doctype, path in files.items():
        if not os.path.exists(path):
            frappe.throw(
                _("Supplier handover DocType file is missing: {0}").format(path)
            )

        with open(path, encoding="utf-8") as source:
            data = json.load(source)

        source_fields = {
            field.get("fieldname")
            for field in (data.get("fields") or [])
            if field.get("fieldname")
        }
        missing_from_file = [
            field for field in requirements[doctype]
            if field not in source_fields
        ]
        if missing_from_file:
            frappe.throw(
                _(
                    "Installed DocType file {0} is outdated. Missing fields: {1}"
                ).format(
                    path,
                    ", ".join(missing_from_file),
                )
            )

        # Import the exact JSON file by absolute path. This avoids module-path
        # resolution and guarantees the file copied by this update is used.
        import_file_by_path(path, force=True)

    frappe.clear_cache()
    frappe.db.updatedb("Pharmacy Return Case")
    frappe.db.updatedb("Pharmacy Return Item")
    frappe.clear_cache()


@frappe.whitelist()
def repair_supplier_handover_schema():
    _sync_supplier_handover_schema()
    return verify_supplier_handover_schema()


@frappe.whitelist()
def verify_supplier_handover_schema():
    requirements = _supplier_handover_schema_requirements()
    missing_meta = {}
    missing_columns = {}

    for doctype, fields in requirements.items():
        meta = frappe.get_meta(doctype, cached=False)
        meta_missing = [field for field in fields if not meta.has_field(field)]
        column_missing = [
            field for field in fields
            if not frappe.db.has_column(doctype, field)
        ]

        if meta_missing:
            missing_meta[doctype] = meta_missing
        if column_missing:
            missing_columns[doctype] = column_missing

    if missing_meta or missing_columns:
        frappe.throw(
            _(
                "Supplier handover schema is incomplete. "
                "Missing DocType fields: {0}. Missing database columns: {1}."
            ).format(
                frappe.as_json(missing_meta) if missing_meta else "None",
                frappe.as_json(missing_columns) if missing_columns else "None",
            )
        )

    return {
        "requirements": requirements,
        "doctype_files": _supplier_handover_doctype_files(),
        "physical_columns_verified": 1,
        "ok": 1,
    }


@frappe.whitelist()
def get_case(name: str):
    _require_read()
    doc = frappe.get_doc("Pharmacy Return Case", name)
    if doc.get("purchase_return") and not frappe.db.exists(
        "Purchase Invoice", doc.get("purchase_return")
    ):
        doc.db_set("purchase_return", None, update_modified=False)
        doc.purchase_return = None
        if doc.operational_status == "Purchase Return Draft Created":
            doc.db_set("operational_status", "Under Review", update_modified=False)
            doc.operational_status = "Under Review"
    purchase_return_details = (
        frappe.db.get_value(
            "Purchase Invoice",
            doc.get("purchase_return"),
            ["docstatus", "status", "is_return"],
            as_dict=True,
        )
        if doc.get("purchase_return") else None
    )
    _sync_case_operational_status(doc)
    _sync_supplier_claim_settlement(doc)
    quarantine_docstatus = (
        frappe.db.get_value("Stock Entry", doc.quarantine_stock_entry, "docstatus")
        if doc.quarantine_stock_entry else None
    )
    handover_docstatus = (
        frappe.db.get_value("Stock Entry", doc.get("handover_stock_entry"), "docstatus")
        if doc.get("handover_stock_entry") else None
    )
    rejection_return_docstatus = (
        frappe.db.get_value(
            "Stock Entry",
            doc.get("rejection_return_stock_entry"),
            "docstatus",
        )
        if doc.get("rejection_return_stock_entry") else None
    )
    refund_payments = _get_case_refund_payment_entries(doc.name)
    latest_refund_payment = refund_payments[-1] if refund_payments else None
    debit_note_details = (
        frappe.db.get_value(
            "Purchase Invoice",
            doc.get("approved_debit_note"),
            [
                "docstatus",
                "status",
                "grand_total",
                "rounded_total",
                "disable_rounded_total",
                "outstanding_amount",
                "is_return",
                "update_stock",
            ],
            as_dict=True,
        )
        if doc.get("approved_debit_note") else None
    )
    returned_by_original_item = (
        _returned_qty_by_original_item(doc.original_purchase_invoice)
        if doc.return_type == "Return Against Invoice" and doc.original_purchase_invoice
        else {}
    )
    source_invoice = (
        frappe.get_doc("Purchase Invoice", doc.original_purchase_invoice)
        if doc.return_type == "Return Against Invoice" and doc.original_purchase_invoice
        else None
    )
    source_invoice_rows = (
        {row.name: row for row in source_invoice.items}
        if source_invoice
        else {}
    )
    item_rows = []
    for row in doc.items:
        values = row.as_dict()
        if doc.return_type == "Return Against Invoice":
            original_item = values.get("original_purchase_invoice_item")
            original_row = source_invoice_rows.get(original_item)
            already_returned = flt(
                returned_by_original_item.get(
                    original_item,
                    values.get("already_returned_qty"),
                )
            )
            if original_row:
                limits = _invoice_return_stock_limits(
                    original_row,
                    already_returned,
                )
                values["warehouse"] = limits["warehouse"]
                values["batch_no"] = limits["batch_no"]
                values["has_batch_no"] = cint(limits.get("has_batch_no"))
                values["original_qty"] = limits["original_qty"]
                values["already_returned_qty"] = already_returned
                values["invoice_returnable_qty"] = limits["invoice_returnable_qty"]
                values["physical_stock_qty"] = limits["physical_stock_qty"]
                values["available_to_return_qty"] = limits["available_to_return_qty"]
                if not doc.purchase_return:
                    values["return_qty"] = min(
                        flt(values.get("return_qty")),
                        limits["available_to_return_qty"],
                    )
        values = _normalize_payload_row_pricing(
            {
                "return_type": doc.return_type,
                "company": doc.company,
            },
            frappe._dict(values),
            invoice=source_invoice,
            invoice_row=source_invoice_rows.get(
                values.get("original_purchase_invoice_item")
            ),
        )
        if (
            _is_progressive_return_type(doc.return_type)
            and quarantine_docstatus == 1
            and handover_docstatus != 1
            and flt(values.get("delivered_qty")) <= 0
        ):
            values["delivered_qty"] = flt(values.get("quarantined_qty")) or flt(values.get("return_qty"))
        item_rows.append(values)
    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "return_type": doc.return_type,
        "company": doc.company,
        "posting_date": doc.posting_date,
        "supplier": doc.supplier,
        "original_purchase_invoice": doc.original_purchase_invoice,
        "purchase_return": doc.purchase_return,
        "purchase_return_docstatus": purchase_return_details.docstatus if purchase_return_details else None,
        "purchase_return_status": purchase_return_details.status if purchase_return_details else None,
        "quarantine_stock_entry": doc.quarantine_stock_entry,
        "handover_stock_entry": doc.get("handover_stock_entry"),
        "rejection_return_stock_entry": doc.get("rejection_return_stock_entry"),
        "approved_debit_note": doc.get("approved_debit_note"),
        "approved_debit_note_posting_date": doc.get("approved_debit_note_posting_date"),
        "approved_debit_note_docstatus": debit_note_details.docstatus if debit_note_details else None,
        "approved_debit_note_status": debit_note_details.status if debit_note_details else doc.get("approved_debit_note_status"),
        "approved_debit_note_amount": _return_invoice_total_and_outstanding(debit_note_details)[0] if debit_note_details else flt(doc.get("approved_debit_note_amount")),
        "approved_debit_note_outstanding": _return_invoice_total_and_outstanding(debit_note_details)[1] if debit_note_details else flt(doc.get("approved_debit_note_outstanding")),
        "approved_debit_note_update_stock": debit_note_details.update_stock if debit_note_details else None,
        "supplier_claim": doc.get("supplier_claim"),
        "refund_posting_date": doc.get("refund_posting_date"),
        "refund_mode_of_payment": doc.get("refund_mode_of_payment"),
        "refund_account": doc.get("refund_account"),
        "refund_request_amount": flt(doc.get("refund_request_amount")),
        "refund_reference_no": doc.get("refund_reference_no"),
        "refund_reference_date": doc.get("refund_reference_date"),
        "refund_payment_entry": doc.get("refund_payment_entry"),
        "refund_payment_entry_status": doc.get("refund_payment_entry_status"),
        "refund_entries_count": cint(doc.get("refund_entries_count")),
        "refund_notes": doc.get("refund_notes"),
        "refund_payments": refund_payments,
        "has_open_refund_draft": any(row.docstatus == 0 for row in refund_payments),
        "settlement_status": doc.get("settlement_status"),
        "claim_utilization_status": doc.get("claim_utilization_status") or "Not Applied",
        "claim_settlement_date": doc.get("claim_settlement_date"),
        "planned_claim_deduction_amount": flt(doc.get("planned_claim_deduction_amount")),
        "claim_deduction_amount": flt(doc.claim_deduction_amount),
        "refund_amount": flt(doc.refund_amount),
        "settled_amount": flt(doc.get("settled_amount")),
        "remaining_settlement_amount": flt(doc.remaining_settlement_amount),
        "quarantine_docstatus": quarantine_docstatus,
        "handover_docstatus": handover_docstatus,
        "rejection_return_docstatus": rejection_return_docstatus,
        "recall_source_warehouse": doc.recall_source_warehouse,
        "recall_item_code": doc.recall_item_code,
        "recall_quarantine_warehouse": doc.recall_quarantine_warehouse,
        "returns_with_supplier_warehouse": doc.get("returns_with_supplier_warehouse"),
        "handover_date": doc.handover_date,
        "handover_reference": doc.handover_reference,
        "handover_attachment": doc.handover_attachment,
        "supplier_response_date": doc.get("supplier_response_date"),
        "supplier_response_reference": doc.get("supplier_response_reference"),
        "supplier_response_attachment": doc.get("supplier_response_attachment"),
        "supplier_response_notes": doc.get("supplier_response_notes"),
        "authority_notification_no": doc.authority_notification_no,
        "authority_notification_date": doc.authority_notification_date,
        "authority_notification_attachment": doc.authority_notification_attachment,
        "settlement_method": doc.settlement_method,
        "operational_status": doc.operational_status,
        "requested_return_value": doc.requested_return_value,
        "approved_return_value": doc.approved_return_value,
        "quarantined_quantity": doc.quarantined_quantity,
        "handed_over_quantity": doc.get("handed_over_quantity"),
        "accepted_quantity": doc.get("accepted_quantity"),
        "rejected_quantity": doc.get("rejected_quantity"),
        "pending_response_quantity": doc.get("pending_response_quantity"),
        "rejected_return_quantity": doc.get("rejected_return_quantity"),
        "accepted_stock_finalized_quantity": doc.get("accepted_stock_finalized_quantity"),
        "remarks": doc.remarks,
        "items": item_rows,
    }


def _make_standard_debit_note(original_invoice: str):
    from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note
    return make_debit_note(original_invoice)


def _match_mapped_item(mapped, case_row):
    original_name = case_row.original_purchase_invoice_item
    for row in mapped.items:
        if row.get("purchase_invoice_item") == original_name:
            return row
    candidates = [row for row in mapped.items if row.item_code == case_row.item_code and (not case_row.warehouse or row.warehouse == case_row.warehouse)]
    return candidates[0] if len(candidates) == 1 else None


def _submit_linked_return_document(doctype: str, name: str):
    """Submit a draft official document created for Purchase Returns Management.

    The helper keeps the user's normal submit permissions intact and makes
    Create & Submit idempotent: if a linked document is already submitted,
    it is returned without creating or submitting a second document.
    """
    if not name or not frappe.db.exists(doctype, name):
        frappe.throw(_("Linked {0} could not be found.").format(doctype))

    doc = frappe.get_doc(doctype, name)
    if doc.docstatus == 1:
        return doc, True
    if doc.docstatus == 2:
        frappe.throw(
            _("{0} {1} is cancelled and cannot be submitted.").format(
                doctype,
                frappe.bold(name),
            )
        )

    if not frappe.has_permission(doctype, "submit", doc=doc):
        frappe.throw(
            _("You are not permitted to submit {0}.").format(doctype),
            frappe.PermissionError,
        )

    doc.submit()
    return doc, False


def _refresh_case_after_official_submit(case_name: str):
    case = frappe.get_doc("Pharmacy Return Case", case_name)
    _sync_case_operational_status(case)
    _sync_supplier_claim_settlement(case)
    return case


@frappe.whitelist()
def delete_purchase_return_draft(case_name: str):
    """Safely unlink and delete a draft Purchase Return created by this page.

    Frappe correctly blocks deleting a Purchase Invoice while a Pharmacy Return
    Case still links to it. This method validates both documents, clears the
    case link inside the same transaction, then deletes only a Draft return.
    Submitted or cancelled accounting documents are never deleted here.
    """
    _require_read()
    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if not frappe.has_permission("Pharmacy Return Case", "write", doc=case):
        frappe.throw(
            _("You are not permitted to update Pharmacy Return Case {0}.").format(
                frappe.bold(case.name)
            ),
            frappe.PermissionError,
        )

    purchase_return = case.get("purchase_return")
    if not purchase_return:
        return {"case": case.name, "deleted": 0, "purchase_return": None}

    if not frappe.db.exists("Purchase Invoice", purchase_return):
        case.db_set("purchase_return", None, update_modified=False)
        if case.operational_status == "Purchase Return Draft Created":
            case.db_set("operational_status", "Under Review", update_modified=False)
        return {"case": case.name, "deleted": 0, "purchase_return": purchase_return}

    return_doc = frappe.get_doc("Purchase Invoice", purchase_return)
    if return_doc.docstatus != 0:
        frappe.throw(
            _("Only a Draft Purchase Return can be deleted. {0} has status {1}.").format(
                frappe.bold(return_doc.name),
                frappe.bold(return_doc.status or return_doc.docstatus),
            )
        )
    if not cint(return_doc.get("is_return")):
        frappe.throw(_("Linked Purchase Invoice {0} is not a return document.").format(frappe.bold(return_doc.name)))
    if return_doc.get("return_against") and return_doc.get("return_against") != case.original_purchase_invoice:
        frappe.throw(_("Purchase Return {0} is linked to a different original invoice.").format(frappe.bold(return_doc.name)))
    if return_doc.meta.has_field("custom_pharmacy_return_case"):
        linked_case = return_doc.get("custom_pharmacy_return_case")
        if linked_case and linked_case != case.name:
            frappe.throw(_("Purchase Return {0} belongs to another Pharmacy Return Case.").format(frappe.bold(return_doc.name)))
    if not frappe.has_permission("Purchase Invoice", "delete", doc=return_doc):
        frappe.throw(
            _("You are not permitted to delete Draft Purchase Return {0}.").format(
                frappe.bold(return_doc.name)
            ),
            frappe.PermissionError,
        )

    # Clear the incoming Link first; otherwise Frappe's link protection blocks
    # deletion. Both operations are part of one request/transaction.
    case.db_set("purchase_return", None, update_modified=False)
    if case.operational_status == "Purchase Return Draft Created":
        case.db_set("operational_status", "Under Review", update_modified=False)
    frappe.delete_doc("Purchase Invoice", return_doc.name)

    return {
        "case": case.name,
        "deleted": 1,
        "purchase_return": return_doc.name,
        "operational_status": "Under Review",
    }


@frappe.whitelist()
def create_purchase_return_draft(case_name: str):
    _require_create()
    if not frappe.has_permission("Purchase Invoice", "create"):
        frappe.throw(_("You are not permitted to create Purchase Returns."), frappe.PermissionError)
    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if case.return_type != "Return Against Invoice":
        frappe.throw(_("This action is only for invoice-linked returns."))
    if case.purchase_return:
        if frappe.db.exists("Purchase Invoice", case.purchase_return):
            return {"case": case.name, "purchase_return": case.purchase_return, "already_exists": 1}
        case.purchase_return = None
    if not case.original_purchase_invoice:
        frappe.throw(_("Original Purchase Invoice is required."))

    payload = {
        "return_type": case.return_type,
        "original_purchase_invoice": case.original_purchase_invoice,
        "supplier": case.supplier,
        "items": [row.as_dict() for row in case.items],
    }
    _validate_invoice_case_payload(payload)

    mapped = _make_standard_debit_note(case.original_purchase_invoice)
    mapped.posting_date = case.posting_date or nowdate()
    mapped.set_posting_time = 0
    mapped.update_stock = 1
    mapped.remarks = _("Created from Pharmacy Return Case {0}").format(case.name)

    new_items = []
    for case_row in case.items:
        if flt(case_row.return_qty) <= 0:
            continue
        mapped_row = _match_mapped_item(mapped, case_row)
        if not mapped_row:
            frappe.throw(_("Could not match original row for item {0}.").format(frappe.bold(case_row.item_code)))
        mapped_row.qty = -abs(flt(case_row.return_qty))
        if mapped_row.meta.has_field("rejected_qty"):
            mapped_row.rejected_qty = 0
        if mapped_row.meta.has_field("received_qty"):
            mapped_row.received_qty = mapped_row.qty
        mapped_row.stock_qty = mapped_row.qty * (flt(mapped_row.conversion_factor) or 1)
        mapped_row.warehouse = case_row.warehouse or mapped_row.warehouse
        if mapped_row.meta.has_field("rejected_warehouse"):
            mapped_row.rejected_warehouse = None
        if mapped_row.meta.has_field("rejected_serial_and_batch_bundle"):
            mapped_row.rejected_serial_and_batch_bundle = None
        if mapped_row.meta.has_field("rejected_serial_no"):
            mapped_row.rejected_serial_no = None
        item_has_batch = _item_has_batch_no(case_row.item_code)
        if mapped_row.meta.has_field("batch_no"):
            mapped_row.batch_no = case_row.batch_no if item_has_batch and case_row.batch_no else None
        if mapped_row.meta.has_field("serial_and_batch_bundle"):
            mapped_row.serial_and_batch_bundle = None
        if mapped_row.meta.has_field("use_serial_batch_fields"):
            mapped_row.use_serial_batch_fields = 1 if item_has_batch and case_row.batch_no else 0

        # Do not copy malformed historical Select values such as
        # ``Auto by VAT %/%`` into the new Purchase Return. The return-case
        # row contains the trusted VAT classification resolved from the
        # original Purchase Invoice / item tax setup.
        taxable = bool(
            cint(case_row.get("is_vat_taxable"))
            and flt(case_row.get("vat_rate")) > 0
        )
        if mapped_row.meta.has_field("custom_tax_entry_mode"):
            mapped_row.custom_tax_entry_mode = (
                _normalize_purchase_invoice_vat_entry_mode(
                    mapped_row.get("custom_tax_entry_mode"),
                    taxable=taxable,
                )
                if taxable
                else "No VAT"
            )
        if mapped_row.meta.has_field("custom_vat_rate"):
            mapped_row.custom_vat_rate = (
                max(0.0, flt(case_row.get("vat_rate"))) if taxable else 0.0
            )
        if mapped_row.meta.has_field("custom_vat_per_unit"):
            mapped_row.custom_vat_per_unit = (
                abs(flt(case_row.get("tax_amount")))
                / max(abs(flt(case_row.get("return_qty"))), 0.000001)
                if taxable
                else 0.0
            )

        new_items.append(mapped_row)
    mapped.set("items", new_items)

    if mapped.meta.has_field("custom_pharmacy_return_case"):
        mapped.custom_pharmacy_return_case = case.name
    mapped.insert()

    case.purchase_return = mapped.name
    case.operational_status = "Purchase Return Draft Created"
    case.save(ignore_permissions=True)
    return {"case": case.name, "purchase_return": mapped.name, "already_exists": 0}



@frappe.whitelist()
def create_and_submit_purchase_return(case_name: str):
    result = create_purchase_return_draft(case_name)
    purchase_return, already_submitted = _submit_linked_return_document(
        "Purchase Invoice",
        result.get("purchase_return"),
    )

    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if case.return_type != "Return Against Invoice":
        frappe.throw(_("This action is only for invoice-linked returns."))

    case.operational_status = _case_status_before_claim(case)
    case.save(ignore_permissions=True)
    _sync_supplier_claim_settlement(case)
    case.reload()

    return {
        "case": case.name,
        "purchase_return": purchase_return.name,
        "docstatus": purchase_return.docstatus,
        "already_exists": cint(result.get("already_exists")),
        "already_submitted": cint(already_submitted),
        "operational_status": case.operational_status,
        "outstanding": flt(purchase_return.get("outstanding_amount")),
    }


@frappe.whitelist()
def create_quarantine_transfer_draft(case_name: str):
    _require_create()
    if not frappe.has_permission("Stock Entry", "create"):
        frappe.throw(_("You are not permitted to create Stock Entries."), frappe.PermissionError)
    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if not _is_progressive_return_type(case.return_type):
        frappe.throw(_("This action is only for progressive Recall / Expired return cases."))
    _sync_case_operational_status(case)
    if case.quarantine_stock_entry:
        if frappe.db.exists("Stock Entry", case.quarantine_stock_entry):
            return {"case": case.name, "stock_entry": case.quarantine_stock_entry, "already_exists": 1}
        case.quarantine_stock_entry = None

    payload = {
        "return_type": case.return_type,
        "company": case.company,
        "supplier": case.supplier,
        "authority_notification_no": case.authority_notification_no,
        "authority_notification_date": case.authority_notification_date,
        "recall_source_warehouse": case.recall_source_warehouse,
        "recall_item_code": case.recall_item_code,
        "recall_quarantine_warehouse": case.recall_quarantine_warehouse,
        "items": [row.as_dict() for row in case.items],
    }
    _validate_regulatory_case_payload(payload)

    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.company = case.company
    stock_entry.purpose = "Material Transfer"
    stock_entry.posting_date = case.posting_date or nowdate()
    stock_entry.set_posting_time = 0
    stock_entry.to_warehouse = case.recall_quarantine_warehouse
    reference = case.authority_notification_no if case.return_type == "Regulatory Batch Recall" else case.name
    stock_entry.remarks = _("{0} quarantine transfer for Pharmacy Return Case {1}. Reference: {2}").format(case.return_type, case.name, reference)

    for row in case.items:
        qty = flt(row.return_qty)
        if qty <= 0:
            continue
        stock_entry.append("items", {
            "item_code": row.item_code,
            "qty": qty,
            "uom": row.stock_uom,
            "stock_uom": row.stock_uom,
            "conversion_factor": 1,
            "s_warehouse": row.warehouse,
            "t_warehouse": case.recall_quarantine_warehouse,
            "batch_no": row.batch_no,
            "use_serial_batch_fields": 1 if row.batch_no else 0,
        })
    if hasattr(stock_entry, "set_stock_entry_type"):
        stock_entry.set_stock_entry_type()
    stock_entry.insert()

    case.quarantine_stock_entry = stock_entry.name
    case.operational_status = "Quarantine Transfer Draft Created"
    for row in case.items:
        row.quarantine_warehouse = case.recall_quarantine_warehouse
    case.save(ignore_permissions=True)
    return {"case": case.name, "stock_entry": stock_entry.name, "already_exists": 0}


@frappe.whitelist()
def create_and_submit_quarantine_transfer(case_name: str):
    result = create_quarantine_transfer_draft(case_name)
    stock_entry, already_submitted = _submit_linked_return_document(
        "Stock Entry",
        result.get("stock_entry"),
    )
    case = _refresh_case_after_official_submit(case_name)
    return {
        "case": case.name,
        "stock_entry": stock_entry.name,
        "docstatus": stock_entry.docstatus,
        "already_exists": cint(result.get("already_exists")),
        "already_submitted": cint(already_submitted),
        "operational_status": case.operational_status,
    }


@frappe.whitelist()
def create_supplier_handover_draft(case_name: str):
    _require_create()
    verify_supplier_handover_schema()
    if not frappe.has_permission("Stock Entry", "create"):
        frappe.throw(_("You are not permitted to create Stock Entries."), frappe.PermissionError)

    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if not _is_progressive_return_type(case.return_type):
        frappe.throw(_("Supplier handover is only available for progressive Recall / Expired return cases."))

    _sync_case_operational_status(case)

    if not case.quarantine_stock_entry:
        frappe.throw(_("Create and submit the quarantine transfer before supplier handover."))
    quarantine_status = frappe.db.get_value("Stock Entry", case.quarantine_stock_entry, "docstatus")
    if quarantine_status != 1:
        frappe.throw(_("The quarantine Stock Entry must be submitted before supplier handover."))

    if case.get("handover_stock_entry"):
        if frappe.db.exists("Stock Entry", case.get("handover_stock_entry")):
            return {
                "case": case.name,
                "stock_entry": case.get("handover_stock_entry"),
                "already_exists": 1,
            }
        case.handover_stock_entry = None

    if not case.handover_date:
        frappe.throw(_("Enter the Supplier Handover Date."))
    if not case.handover_reference:
        frappe.throw(_("Enter the Supplier Handover Receipt Number."))
    if not case.get("returns_with_supplier_warehouse"):
        default_supplier_warehouse = _special_warehouses(case.company).get("supplier")
        if default_supplier_warehouse:
            case.returns_with_supplier_warehouse = default_supplier_warehouse
            case.db_set(
                "returns_with_supplier_warehouse",
                default_supplier_warehouse,
                update_modified=False,
            )
        else:
            frappe.throw(_("Select the Returns With Supplier Warehouse."))

    target = frappe.db.get_value(
        "Warehouse", case.get("returns_with_supplier_warehouse"),
        ["company", "is_group", "disabled"], as_dict=True,
    )
    if not target or target.company != case.company or target.is_group or target.disabled:
        frappe.throw(_("Select an active Returns With Supplier Warehouse for the same company."))
    if case.get("returns_with_supplier_warehouse") == case.recall_quarantine_warehouse:
        frappe.throw(_("Returns With Supplier Warehouse must differ from the quarantine warehouse."))

    selected = [row for row in case.items if flt(row.delivered_qty) > 0]
    if not selected:
        frappe.throw(_("Enter a Handover Quantity for at least one recalled item."))

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.company = case.company
    stock_entry.purpose = "Material Transfer"
    stock_entry.posting_date = case.handover_date
    stock_entry.set_posting_time = 0
    stock_entry.from_warehouse = case.recall_quarantine_warehouse
    stock_entry.to_warehouse = case.get("returns_with_supplier_warehouse")
    stock_entry.remarks = _(
        "Supplier handover for Pharmacy Return Case {0}. "
        "Case type: {1}. Receipt: {2}"
    ).format(case.name, case.return_type, case.handover_reference)

    total_delivered = 0.0
    for row in selected:
        qty = flt(row.delivered_qty)
        quarantined = flt(row.quarantined_qty) or flt(row.return_qty)
        if qty > quarantined + 0.000001:
            frappe.throw(
                _("Handover quantity for batch {0} cannot exceed quarantined quantity {1}.").format(
                    frappe.bold(row.batch_no), quarantined
                )
            )

        current = flt(
            get_batch_qty(
                batch_no=row.batch_no,
                warehouse=case.recall_quarantine_warehouse,
                item_code=row.item_code,
                for_stock_levels=True,
                consider_negative_batches=True,
                ignore_reserved_stock=True,
            )
        )
        if qty > current + 0.000001:
            frappe.throw(
                _("Handover quantity for batch {0} cannot exceed current quarantine stock {1}.").format(
                    frappe.bold(row.batch_no), current
                )
            )

        stock_entry.append("items", {
            "item_code": row.item_code,
            "qty": qty,
            "uom": row.stock_uom,
            "stock_uom": row.stock_uom,
            "conversion_factor": 1,
            "s_warehouse": case.recall_quarantine_warehouse,
            "t_warehouse": case.get("returns_with_supplier_warehouse"),
            "batch_no": row.batch_no,
            "use_serial_batch_fields": 1 if row.batch_no else 0,
        })
        total_delivered += qty

    if hasattr(stock_entry, "set_stock_entry_type"):
        stock_entry.set_stock_entry_type()
    stock_entry.insert()

    case.handover_stock_entry = stock_entry.name
    case.handed_over_quantity = total_delivered
    case.operational_status = "Handover Transfer Draft Created"
    case.save(ignore_permissions=True)

    return {
        "case": case.name,
        "stock_entry": stock_entry.name,
        "already_exists": 0,
    }


@frappe.whitelist()
def create_and_submit_supplier_handover(case_name: str):
    result = create_supplier_handover_draft(case_name)
    stock_entry, already_submitted = _submit_linked_return_document(
        "Stock Entry",
        result.get("stock_entry"),
    )
    case = _refresh_case_after_official_submit(case_name)
    return {
        "case": case.name,
        "stock_entry": stock_entry.name,
        "docstatus": stock_entry.docstatus,
        "already_exists": cint(result.get("already_exists")),
        "already_submitted": cint(already_submitted),
        "operational_status": case.operational_status,
    }


@frappe.whitelist()
def create_rejected_quantity_return_draft(case_name: str):
    _require_create()
    verify_supplier_handover_schema()

    if not frappe.has_permission("Stock Entry", "create"):
        frappe.throw(_("You are not permitted to create Stock Entries."), frappe.PermissionError)

    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if not _is_progressive_return_type(case.return_type):
        frappe.throw(_("Rejected quantity return is only available for Regulatory Batch Recall cases."))

    _sync_case_operational_status(case)

    if not case.get("handover_stock_entry"):
        frappe.throw(_("Create and submit the Supplier Handover Stock Entry first."))
    handover_status = frappe.db.get_value(
        "Stock Entry",
        case.get("handover_stock_entry"),
        "docstatus",
    )
    if handover_status != 1:
        frappe.throw(_("Submit the Supplier Handover Stock Entry first."))

    if case.get("rejection_return_stock_entry"):
        if frappe.db.exists("Stock Entry", case.get("rejection_return_stock_entry")):
            return {
                "case": case.name,
                "stock_entry": case.get("rejection_return_stock_entry"),
                "already_exists": 1,
            }
        case.rejection_return_stock_entry = None

    if not case.get("supplier_response_date"):
        frappe.throw(_("Enter the Supplier Response Date."))
    if not case.get("supplier_response_reference"):
        frappe.throw(_("Enter the Supplier Response Reference."))

    handed = sum(flt(row.delivered_qty) for row in case.items)
    accepted = sum(flt(row.accepted_qty) for row in case.items)
    rejected = sum(flt(row.rejected_qty) for row in case.items)
    pending = max(0.0, handed - accepted - rejected)

    if pending > 0.000001:
        frappe.throw(
            _("Complete the supplier response for all handed-over quantities before returning rejected stock. Pending quantity: {0}.").format(
                pending
            )
        )

    selected = [row for row in case.items if flt(row.rejected_qty) > 0]
    if not selected:
        frappe.throw(_("There is no rejected quantity to return to quarantine."))

    source = case.get("returns_with_supplier_warehouse")
    target = case.recall_quarantine_warehouse
    if not source or not target:
        frappe.throw(_("Returns With Supplier Warehouse and Recall Quarantine Warehouse are required."))
    if source == target:
        frappe.throw(_("Rejected quantity source and target warehouses must be different."))

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.company = case.company
    stock_entry.purpose = "Material Transfer"
    stock_entry.posting_date = case.get("supplier_response_date")
    stock_entry.set_posting_time = 0
    stock_entry.from_warehouse = source
    stock_entry.to_warehouse = target
    stock_entry.remarks = _(
        "Supplier-rejected quantity returned to recall quarantine for Pharmacy Return Case {0}. "
        "Supplier response reference: {1}"
    ).format(case.name, case.get("supplier_response_reference"))

    total_rejected = 0.0
    for row in selected:
        qty = flt(row.rejected_qty)
        delivered = flt(row.delivered_qty)
        if qty > delivered + 0.000001:
            frappe.throw(
                _("Rejected quantity for batch {0} cannot exceed handed-over quantity {1}.").format(
                    frappe.bold(row.batch_no), delivered
                )
            )
        if not (row.rejection_reason or "").strip():
            frappe.throw(
                _("Supplier Rejection Reason is required for batch {0}.").format(
                    frappe.bold(row.batch_no)
                )
            )

        current = flt(
            get_batch_qty(
                batch_no=row.batch_no,
                warehouse=source,
                item_code=row.item_code,
                for_stock_levels=True,
                consider_negative_batches=True,
                ignore_reserved_stock=True,
            )
        )
        if qty > current + 0.000001:
            frappe.throw(
                _("Rejected quantity for batch {0} cannot exceed current stock {1} in {2}.").format(
                    frappe.bold(row.batch_no),
                    current,
                    frappe.bold(source),
                )
            )

        stock_entry.append("items", {
            "item_code": row.item_code,
            "qty": qty,
            "uom": row.stock_uom,
            "stock_uom": row.stock_uom,
            "conversion_factor": 1,
            "s_warehouse": source,
            "t_warehouse": target,
            "batch_no": row.batch_no,
            "use_serial_batch_fields": 1 if row.batch_no else 0,
        })
        total_rejected += qty

    if hasattr(stock_entry, "set_stock_entry_type"):
        stock_entry.set_stock_entry_type()
    stock_entry.insert()

    case.rejection_return_stock_entry = stock_entry.name
    case.rejected_return_quantity = 0
    case.operational_status = "Rejection Return Draft Created"
    case.save(ignore_permissions=True)

    return {
        "case": case.name,
        "stock_entry": stock_entry.name,
        "rejected_quantity": total_rejected,
        "already_exists": 0,
    }


@frappe.whitelist()
def create_and_submit_rejected_quantity_return(case_name: str):
    result = create_rejected_quantity_return_draft(case_name)
    stock_entry, already_submitted = _submit_linked_return_document(
        "Stock Entry",
        result.get("stock_entry"),
    )
    case = _refresh_case_after_official_submit(case_name)
    return {
        "case": case.name,
        "stock_entry": stock_entry.name,
        "docstatus": stock_entry.docstatus,
        "rejected_quantity": flt(result.get("rejected_quantity")),
        "already_exists": cint(result.get("already_exists")),
        "already_submitted": cint(already_submitted),
        "operational_status": case.operational_status,
    }


@frappe.whitelist()
def create_approved_debit_note_draft(case_name: str):
    _require_create()
    verify_supplier_handover_schema()

    if not frappe.has_permission("Purchase Invoice", "create"):
        frappe.throw(_("You are not permitted to create Purchase Debit Notes."), frappe.PermissionError)

    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if not _is_progressive_return_type(case.return_type):
        frappe.throw(_("Approved Debit Note is only available for progressive Recall / Expired return cases."))

    _sync_case_operational_status(case)

    if case.get("approved_debit_note"):
        if frappe.db.exists("Purchase Invoice", case.get("approved_debit_note")):
            existing_status = frappe.db.get_value(
                "Purchase Invoice",
                case.get("approved_debit_note"),
                "docstatus",
            )
            if existing_status in (0, 1):
                return {
                    "case": case.name,
                    "purchase_invoice": case.get("approved_debit_note"),
                    "already_exists": 1,
                }
        case.approved_debit_note = None

    handover_status = (
        frappe.db.get_value("Stock Entry", case.get("handover_stock_entry"), "docstatus")
        if case.get("handover_stock_entry") else None
    )
    if handover_status != 1:
        frappe.throw(_("Submit the Supplier Handover Stock Entry before creating the Approved Debit Note."))

    pending = max(
        0.0,
        sum(flt(row.delivered_qty) for row in case.items)
        - sum(flt(row.accepted_qty) for row in case.items)
        - sum(flt(row.rejected_qty) for row in case.items),
    )
    if pending > 0.000001:
        frappe.throw(
            _("Complete the supplier response first. Pending quantity: {0}.").format(pending)
        )

    accepted_rows = [row for row in case.items if flt(row.accepted_qty) > 0]
    if not accepted_rows:
        frappe.throw(_("There is no accepted quantity for an Approved Debit Note."))

    rejected = sum(flt(row.rejected_qty) for row in case.items)
    if rejected > 0:
        rejection_status = (
            frappe.db.get_value(
                "Stock Entry",
                case.get("rejection_return_stock_entry"),
                "docstatus",
            )
            if case.get("rejection_return_stock_entry") else None
        )
        if rejection_status != 1:
            frappe.throw(
                _("Submit the Rejected Quantity Return Stock Entry before creating the Approved Debit Note.")
            )

    source_warehouse = case.get("returns_with_supplier_warehouse")
    if not source_warehouse:
        frappe.throw(_("Returns With Supplier Warehouse is required."))

    warehouse = frappe.db.get_value(
        "Warehouse",
        source_warehouse,
        ["company", "is_group", "disabled"],
        as_dict=True,
    )
    if not warehouse or warehouse.company != case.company or warehouse.is_group or warehouse.disabled:
        frappe.throw(_("Select an active Returns With Supplier Warehouse for the same company."))

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    for row in accepted_rows:
        accepted_qty = flt(row.accepted_qty)
        if not row.batch_no:
            frappe.throw(_("Batch No is required for accepted item {0}.").format(frappe.bold(row.item_code)))
        current = flt(
            get_batch_qty(
                batch_no=row.batch_no,
                warehouse=source_warehouse,
                item_code=row.item_code,
                for_stock_levels=True,
                consider_negative_batches=True,
                ignore_reserved_stock=True,
            )
        )
        if accepted_qty > current + 0.000001:
            frappe.throw(
                _("Accepted quantity for batch {0} cannot exceed current stock {1} in {2}.").format(
                    frappe.bold(row.batch_no),
                    current,
                    frappe.bold(source_warehouse),
                )
            )
        if flt(row.approved_rate) <= 0:
            frappe.throw(
                _("Approved Settlement Rate is required for accepted item {0}.").format(
                    frappe.bold(row.item_code)
                )
            )

    # Safety normalization for existing saved cases. The UI and save_case path both
    # store approved_rate as VAT-exclusive. This block prevents old rows, saved before
    # v1.0.1, from creating a debit note where VAT is added twice.
    for row in accepted_rows:
        if cint(row.get("is_vat_taxable")) and flt(row.get("vat_rate")) > 0:
            ignored_base_rate, fixed_discount, fixed_rate, fixed_mode = _pricing_pair_vat_aware(
                row.get("base_rate"),
                row.get("approved_discount_percentage"),
                row.get("approved_rate"),
                row.get("approved_pricing_input_mode"),
                row.get("vat_rate"),
                row.get("is_vat_taxable"),
            )
            row.approved_discount_percentage = fixed_discount
            row.approved_rate = fixed_rate
            row.approved_pricing_input_mode = fixed_mode
            row.approved_net_amount = flt(row.accepted_qty) * fixed_rate
            row.approved_tax_amount = row.approved_net_amount * flt(row.get("vat_rate")) / 100.0
            row.approved_total_credit = row.approved_net_amount + row.approved_tax_amount
            row.accepted_amount = row.approved_total_credit

    debit_note = frappe.new_doc("Purchase Invoice")
    debit_note.company = case.company
    debit_note.supplier = case.supplier
    debit_note.posting_date = (
        case.get("approved_debit_note_posting_date")
        or case.get("supplier_response_date")
        or nowdate()
    )
    debit_note.set_posting_time = 0
    debit_note.is_return = 1
    debit_note.update_stock = 1
    debit_note.update_outstanding_for_self = 1
    debit_note.ignore_pricing_rule = 1
    debit_note.apply_tds = 0
    debit_note.return_against = None
    debit_note.remarks = _(
        "Approved supplier debit note for Pharmacy Return Case {0}. "
        "Case type: {1}. Supplier response: {2}. "
        "Accepted stock is issued from {3}."
    ).format(
        case.name,
        case.return_type,
        case.get("supplier_response_reference") or "-",
        source_warehouse,
    )

    selected_rows = []
    for case_row in accepted_rows:
        qty = -abs(flt(case_row.accepted_qty))
        debit_note.append(
            "items",
            {
                "item_code": case_row.item_code,
                "item_name": case_row.item_name,
                "qty": qty,
                "received_qty": qty,
                "stock_qty": qty,
                "rate": flt(case_row.approved_rate),
                "price_list_rate": flt(case_row.approved_rate),
                "discount_percentage": 0,
                "uom": case_row.stock_uom,
                "stock_uom": case_row.stock_uom,
                "conversion_factor": 1,
                "warehouse": source_warehouse,
                "batch_no": case_row.batch_no,
                "use_serial_batch_fields": 1,
            },
        )
        selected_rows.append(case_row)

    debit_note.run_method("set_missing_values")

    # Supplier-approved prices are final. VAT is added only for rows that the
    # item/original purchasing setup identifies as VAT taxable.
    debit_note.taxes_and_charges = None
    debit_note.set("taxes", [])
    debit_note.apply_tds = 0
    debit_note.tax_withholding_category = None

    vat_accounts = {}
    resolved_row_vat_accounts = {}
    for case_row in selected_rows:
        if not cint(case_row.get("is_vat_taxable")) or flt(case_row.get("vat_rate")) <= 0:
            continue
        account = case_row.get("vat_account")
        if not account and case_row.get("item_tax_template"):
            template_vat = _vat_from_item_tax_template(
                case_row.get("item_tax_template"),
                case.company,
            )
            account = template_vat.get("vat_account")
        if not account:
            frappe.throw(
                _(
                    "VAT Account could not be resolved for taxable item {0}. "
                    "Set an Item Tax Template or use a prior Purchase Invoice with VAT."
                ).format(frappe.bold(case_row.item_code))
            )
        resolved_row_vat_accounts[case_row.name] = account
        vat_accounts[account] = max(
            flt(vat_accounts.get(account)),
            flt(case_row.get("vat_rate")),
        )

    for account, default_rate in vat_accounts.items():
        debit_note.append(
            "taxes",
            {
                "charge_type": "On Net Total",
                "account_head": account,
                "description": account,
                "rate": default_rate,
                "category": "Total",
                "add_deduct_tax": "Add",
                "included_in_print_rate": 0,
            },
        )

    for invoice_row, case_row in zip(debit_note.items, selected_rows):
        qty = -abs(flt(case_row.accepted_qty))
        invoice_row.qty = qty
        invoice_row.received_qty = qty
        invoice_row.conversion_factor = 1
        invoice_row.stock_qty = qty
        invoice_row.rate = flt(case_row.approved_rate)
        invoice_row.price_list_rate = flt(case_row.approved_rate)
        invoice_row.discount_percentage = 0
        invoice_row.discount_amount = 0
        invoice_row.warehouse = source_warehouse
        invoice_row.batch_no = case_row.batch_no
        if invoice_row.meta.has_field("serial_and_batch_bundle"):
            invoice_row.serial_and_batch_bundle = None
        if invoice_row.meta.has_field("use_serial_batch_fields"):
            invoice_row.use_serial_batch_fields = 1
        if invoice_row.meta.has_field("item_tax_template"):
            invoice_row.item_tax_template = case_row.get("item_tax_template") or None
        if invoice_row.meta.has_field("item_tax_rate") and vat_accounts:
            item_rates = {}
            for account in vat_accounts:
                item_rates[account] = (
                    flt(case_row.get("vat_rate"))
                    if cint(case_row.get("is_vat_taxable"))
                    and account == resolved_row_vat_accounts.get(case_row.name)
                    else 0.0
                )
            invoice_row.item_tax_rate = frappe.as_json(item_rates)

    debit_note.run_method("calculate_taxes_and_totals")

    expected_value = sum(flt(row.get("approved_total_credit")) for row in accepted_rows)
    actual_value, actual_outstanding = _return_invoice_total_and_outstanding(debit_note)

    # ERPNext may round VAT-inclusive discounted rates at invoice line precision,
    # causing a small 0.01 currency difference, e.g. expected 160.00 vs actual 160.01.
    # Accept small currency rounding differences and settle using the actual debit-note total.
    rounding_difference = abs(flt(actual_value, 2) - flt(expected_value, 2))
    if rounding_difference > 0.05:
        frappe.throw(
            _("Approved Debit Note total {0} does not match approved supplier value {1}.").format(
                actual_value,
                expected_value,
            )
        )

    if debit_note.meta.has_field("custom_pharmacy_return_case"):
        debit_note.custom_pharmacy_return_case = case.name

    debit_note.insert()

    case.approved_debit_note = debit_note.name
    case.approved_debit_note_posting_date = debit_note.posting_date
    case.approved_debit_note_amount = actual_value
    case.approved_debit_note_outstanding = actual_outstanding
    case.remaining_settlement_amount = actual_outstanding or actual_value
    case.approved_debit_note_outstanding = actual_value
    case.approved_debit_note_status = "Draft"
    case.accepted_stock_finalized_quantity = 0
    case.operational_status = "Approved Debit Note Draft Created"
    case.save(ignore_permissions=True)

    return {
        "case": case.name,
        "purchase_invoice": debit_note.name,
        "approved_value": actual_value,
        "accepted_quantity": sum(flt(row.accepted_qty) for row in accepted_rows),
        "source_warehouse": source_warehouse,
        "update_stock": 1,
        "already_exists": 0,
    }


@frappe.whitelist()
def create_and_submit_approved_debit_note(case_name: str):
    result = create_approved_debit_note_draft(case_name)
    debit_note, already_submitted = _submit_linked_return_document(
        "Purchase Invoice",
        result.get("purchase_invoice"),
    )
    case = _refresh_case_after_official_submit(case_name)
    approved_value, outstanding = _return_invoice_total_and_outstanding(debit_note)
    return {
        "case": case.name,
        "purchase_invoice": debit_note.name,
        "docstatus": debit_note.docstatus,
        "approved_value": approved_value,
        "outstanding": outstanding,
        "already_exists": cint(result.get("already_exists")),
        "already_submitted": cint(already_submitted),
        "operational_status": case.operational_status,
        "settlement_status": case.get("settlement_status"),
    }


@frappe.whitelist()
def create_or_link_supplier_claim_deduction(case_name: str, supplier_claim: str | None = None):
    _require_create()
    verify_supplier_handover_schema()
    if not frappe.has_permission("Supplier Claim", "create"):
        frappe.throw(_("You are not permitted to create Supplier Claims."), frappe.PermissionError)
    case=frappe.get_doc("Pharmacy Return Case",case_name)
    if not _is_progressive_return_type(case.return_type):
        frappe.throw(_("Supplier Claim deduction is only available for progressive Recall / Expired return cases."))
    _sync_case_operational_status(case); _sync_supplier_claim_settlement(case)
    debit_note=case.get("approved_debit_note")
    if not debit_note:
        frappe.throw(_("Create and submit the Approved Supplier Debit Note first."))
    note=frappe.db.get_value("Purchase Invoice",debit_note,["docstatus","company","supplier","posting_date","bill_no","bill_date","grand_total","rounded_total","disable_rounded_total","outstanding_amount","is_return","status"],as_dict=True)
    if not note or note.docstatus != 1 or not note.is_return:
        frappe.throw(_("Submit the Approved Supplier Debit Note first."))
    approved=flt(case.approved_return_value); deduction, note_outstanding = _return_invoice_total_and_outstanding(note)
    if abs(deduction-approved)>0.01:
        frappe.throw(_("Debit Note amount {0} does not match Approved Return Value {1}.").format(deduction,approved))
    meta=frappe.get_meta("Purchase Invoice")
    linked=frappe.db.get_value("Purchase Invoice",debit_note,"custom_supplier_claim") if meta.has_field("custom_supplier_claim") else None
    if linked and linked != supplier_claim:
        frappe.throw(_("Approved Debit Note is already linked to Supplier Claim {0}.").format(frappe.bold(linked)))
    selected=supplier_claim or case.get("supplier_claim")
    if selected:
        claim=frappe.get_doc("Supplier Claim",selected)
        if claim.docstatus != 0:
            return {"case":case.name,"supplier_claim":claim.name,"already_exists":1,"docstatus":claim.docstatus,"planned_deduction":deduction}
        if claim.company != case.company or claim.supplier != case.supplier:
            frappe.throw(_("Supplier Claim belongs to another company or supplier."))
    else:
        from frappe.utils import get_first_day,get_last_day
        claim=frappe.new_doc("Supplier Claim")
        claim.company=case.company; claim.supplier=case.supplier
        claim.period_from=get_first_day(note.posting_date); claim.period_to=get_last_day(note.posting_date)
        claim.claim_basis="Supplier Invoice Date"; claim.status="Draft"
        # This Draft initially contains only the approved Debit Note.
        claim.supplier_printed_claim_total=0
        claim.net_amount_to_pay=0
    existing=next((row for row in claim.invoices if row.purchase_invoice==debit_note),None)
    values={"purchase_invoice":debit_note,"supplier_invoice_no":note.bill_no,"supplier_invoice_date":note.bill_date or note.posting_date,"posting_date":note.posting_date,"grand_total":flt(note.grand_total),"outstanding_amount":flt(note.outstanding_amount),"included_amount":-deduction,"is_return":1,"invoice_status":note.status}
    if existing:
        for k,v in values.items(): setattr(existing,k,v)
    else:
        claim.append("invoices",values)
    claim.save()
    case.supplier_claim=claim.name; case.settlement_method="Deduct from Supplier Claim"
    case.settlement_status="Claim Deduction Draft"; case.planned_claim_deduction_amount=deduction
    case.claim_deduction_amount=0; case.settled_amount=flt(case.refund_amount)
    case.remaining_settlement_amount=max(0.0,approved-flt(case.refund_amount))
    case.operational_status="Claim Deduction Draft Created"
    case.save(ignore_permissions=True)
    return {"case":case.name,"supplier_claim":claim.name,"planned_deduction":deduction,"system_claim_total":flt(claim.system_claim_total),"already_exists":0,"docstatus":claim.docstatus}


@frappe.whitelist()
def create_supplier_refund_payment_draft(
    case_name: str,
    amount,
    posting_date,
    mode_of_payment,
    refund_account,
    reference_no: str | None = None,
    reference_date: str | None = None,
    notes: str | None = None,
):
    _require_create()
    verify_supplier_handover_schema()

    if not frappe.has_permission("Payment Entry", "create"):
        frappe.throw(
            _("You are not permitted to create Payment Entries."),
            frappe.PermissionError,
        )

    case = frappe.get_doc("Pharmacy Return Case", case_name)
    _sync_supplier_claim_settlement(case)

    settlement_document = _case_settlement_document(case)
    if not settlement_document:
        frappe.throw(
            _("A submitted Purchase Return / Approved Debit Note is required.")
        )

    note = frappe.db.get_value(
        "Purchase Invoice",
        settlement_document,
        [
            "docstatus",
            "is_return",
            "company",
            "supplier",
            "outstanding_amount",
            "grand_total",
            "rounded_total",
            "disable_rounded_total",
        ],
        as_dict=True,
    )
    if not note or note.docstatus != 1 or not note.is_return:
        frappe.throw(
            _("Submit the Purchase Return / Approved Debit Note first.")
        )
    if note.company != case.company or note.supplier != case.supplier:
        frappe.throw(
            _("The settlement document belongs to another company or supplier.")
        )

    note_outstanding = flt(note.outstanding_amount)
    document_remaining = abs(note_outstanding)

    if not document_remaining:
        frappe.throw(_("This return case is already fully settled."))

    amount = flt(amount)
    remaining = max(flt(case.remaining_settlement_amount), document_remaining)

    if amount <= 0:
        frappe.throw(_("Refund Amount to Receive must be greater than zero."))

    # If the entered amount only differs from the real supplier balance by rounding,
    # use the exact ERPNext outstanding balance.
    if abs(amount - document_remaining) <= 0.05:
        amount = document_remaining

    if amount > document_remaining + 0.01:
        frappe.throw(
            _("Refund amount {0} cannot exceed outstanding supplier credit {1}.").format(
                amount,
                document_remaining,
            )
        )

    existing_drafts = [
        row
        for row in _get_case_refund_payment_entries(case.name)
        if row.docstatus == 0
    ]
    if existing_drafts:
        return {
            "case": case.name,
            "payment_entry": existing_drafts[-1].name,
            "already_exists": 1,
            "amount": _refund_entry_amount(existing_drafts[-1]),
        }

    account = frappe.db.get_value(
        "Account",
        refund_account,
        [
            "company",
            "is_group",
            "disabled",
            "account_type",
            "account_currency",
        ],
        as_dict=True,
    )
    if (
        not account
        or account.company != case.company
        or account.is_group
        or account.disabled
        or account.account_type not in ("Bank", "Cash")
    ):
        frappe.throw(
            _("Select an active Bank or Cash account for the same company.")
        )

    if not mode_of_payment or not frappe.db.exists(
        "Mode of Payment",
        mode_of_payment,
    ):
        frappe.throw(_("Select a valid Refund Mode of Payment."))

    if account.account_type == "Bank":
        if not reference_no:
            frappe.throw(
                _("Transaction Reference is required for a Bank refund.")
            )
        if not reference_date:
            frappe.throw(
                _("Reference Date is required for a Bank refund.")
            )

    from erpnext.accounts.doctype.payment_entry.payment_entry import (
        get_payment_entry,
    )

    payment_entry = get_payment_entry(
        "Purchase Invoice",
        settlement_document,
        party_amount=-abs(amount),
        bank_account=refund_account,
        payment_type="Receive",
        reference_date=reference_date or posting_date,
    )

    payment_entry.payment_type = "Receive"
    payment_entry.posting_date = posting_date or nowdate()
    payment_entry.mode_of_payment = mode_of_payment
    payment_entry.paid_to = refund_account
    payment_entry.reference_no = reference_no or case.name
    payment_entry.reference_date = reference_date or posting_date or nowdate()
    payment_entry.remarks = _(
        "Supplier refund for Pharmacy Return Case {0} against {1}. {2}"
    ).format(
        case.name,
        settlement_document,
        notes or "",
    )

    payment_entry.paid_amount = abs(amount)
    payment_entry.received_amount = abs(amount)
    for row in payment_entry.references:
        if (
            row.reference_doctype == "Purchase Invoice"
            and row.reference_name == settlement_document
        ):
            invoice_total = (
                flt(note.rounded_total)
                if not cint(note.get("disable_rounded_total"))
                else flt(note.grand_total)
            ) or flt(note.grand_total)

            # Purchase Return / Supplier Debit Note has negative outstanding.
            # Allocation must keep the same sign as outstanding_amount.
            row.total_amount = -abs(invoice_total)
            row.outstanding_amount = note_outstanding
            row.allocated_amount = -abs(amount)

    payment_entry.custom_pharmacy_return_case = case.name
    payment_entry.custom_supplier_refund_method = (
        "Bank Refund"
        if account.account_type == "Bank"
        else "Cash Refund"
    )
    payment_entry.custom_supplier_refund_notes = notes or None
    payment_entry.insert()

    case.refund_posting_date = payment_entry.posting_date
    case.refund_mode_of_payment = mode_of_payment
    case.refund_account = refund_account
    case.refund_reference_no = payment_entry.reference_no
    case.refund_reference_date = payment_entry.reference_date
    case.refund_payment_entry = payment_entry.name
    case.refund_payment_entry_status = "Draft"
    case.refund_request_amount = amount
    case.refund_notes = notes or None
    case.operational_status = "Refund Payment Draft Created"
    case.settlement_status = (
        "Mixed Settlement Draft"
        if flt(case.claim_deduction_amount)
        or flt(case.planned_claim_deduction_amount)
        else "Refund Draft"
    )
    case.settlement_method = (
        "Mixed Settlement"
        if flt(case.claim_deduction_amount)
        or flt(case.planned_claim_deduction_amount)
        else "Cash / Bank Refund"
    )
    case.save(ignore_permissions=True)

    return {
        "case": case.name,
        "payment_entry": payment_entry.name,
        "amount": amount,
        "payment_type": payment_entry.payment_type,
        "paid_from": payment_entry.paid_from,
        "paid_to": payment_entry.paid_to,
        "settlement_document": settlement_document,
        "already_exists": 0,
    }


@frappe.whitelist()
def create_and_submit_supplier_refund_payment(
    case_name: str,
    amount,
    posting_date,
    mode_of_payment,
    refund_account,
    reference_no: str | None = None,
    reference_date: str | None = None,
    notes: str | None = None,
):
    result = create_supplier_refund_payment_draft(
        case_name=case_name,
        amount=amount,
        posting_date=posting_date,
        mode_of_payment=mode_of_payment,
        refund_account=refund_account,
        reference_no=reference_no,
        reference_date=reference_date,
        notes=notes,
    )
    payment_entry, already_submitted = _submit_linked_return_document(
        "Payment Entry",
        result.get("payment_entry"),
    )
    case = _refresh_case_after_official_submit(case_name)
    return {
        "case": case.name,
        "payment_entry": payment_entry.name,
        "docstatus": payment_entry.docstatus,
        "amount": _refund_entry_amount(payment_entry),
        "payment_type": payment_entry.payment_type,
        "paid_from": payment_entry.paid_from,
        "paid_to": payment_entry.paid_to,
        "settlement_document": result.get("settlement_document"),
        "already_exists": cint(result.get("already_exists")),
        "already_submitted": cint(already_submitted),
        "operational_status": case.operational_status,
        "settlement_status": case.get("settlement_status"),
        "remaining_settlement_amount": flt(case.get("remaining_settlement_amount")),
    }


@frappe.whitelist()
def repair_all_return_case_refund_settlements():
    repaired = []
    cases = frappe.get_all(
        "Pharmacy Return Case",
        fields=["name"],
        limit_page_length=0,
    )
    for row in cases:
        doc = frappe.get_doc("Pharmacy Return Case", row.name)
        if _case_settlement_base(doc) <= 0:
            continue
        _sync_supplier_claim_settlement(doc)
        repaired.append(
            {
                "case": doc.name,
                "refund_amount": flt(doc.refund_amount),
                "claim_deduction": flt(doc.claim_deduction_amount),
                "remaining": flt(doc.remaining_settlement_amount),
                "settlement_status": doc.settlement_status,
            }
        )

    frappe.db.commit()
    return {
        "repaired_count": len(repaired),
        "repaired": repaired,
    }


@frappe.whitelist()
def list_recent_cases(company: str | None = None, limit: int = 100, search_text: str | None = None, from_date: str | None = None, to_date: str | None = None):
    _require_read()
    return _recent_cases(company or _default_company(), limit, search_text, from_date, to_date)


def _return_invoice_total_and_outstanding(note):
    """Return accounting total and supplier outstanding using ERPNext rounding rules."""
    from frappe.utils import cint as _cint

    if isinstance(note, str):
        note = frappe.db.get_value(
            "Purchase Invoice",
            note,
            ["grand_total", "rounded_total", "disable_rounded_total", "outstanding_amount"],
            as_dict=True,
        ) or {}

    grand_total = flt(note.get("grand_total"))
    rounded_total = flt(note.get("rounded_total"))
    disable_rounded_total = _cint(note.get("disable_rounded_total"))
    outstanding_amount = flt(note.get("outstanding_amount"))

    accounting_total = abs(grand_total) if disable_rounded_total else (abs(rounded_total) or abs(grand_total))
    outstanding = abs(outstanding_amount)

    return accounting_total, outstanding

