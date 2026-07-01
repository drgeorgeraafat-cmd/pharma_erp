from __future__ import annotations

import frappe
from frappe.utils import flt


def _financial_document(case):
    return case.get("approved_debit_note") or case.get("purchase_return")


def _settlement_base(case, financial_document):
    if financial_document and frappe.db.exists(
        "Purchase Invoice",
        financial_document,
    ):
        note = frappe.db.get_value(
            "Purchase Invoice",
            financial_document,
            ["docstatus", "is_return", "grand_total"],
            as_dict=True,
        )
        if note and note.is_return and note.docstatus < 2:
            return abs(flt(note.grand_total))

    if case.return_type == "Regulatory Batch Recall":
        return flt(case.approved_return_value)

    return (
        flt(case.approved_return_value)
        or flt(case.requested_return_value)
    )


def _status_before_claim(case):
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


def execute():
    cases = frappe.get_all(
        "Pharmacy Return Case",
        fields=["name"],
        filters={
            "return_type": [
                "in",
                [
                    "Return Against Invoice",
                    "Regulatory Batch Recall",
                    "Expired Drugs Return",
                ],
            ]
        },
        limit_page_length=0,
    )

    for row in cases:
        case = frappe.get_doc("Pharmacy Return Case", row.name)
        financial_document = _financial_document(case)
        settlement_base = _settlement_base(
            case,
            financial_document,
        )

        if settlement_base <= 0:
            continue

        case.approved_return_value = settlement_base
        case.rejected_return_value = max(
            0.0,
            flt(case.requested_return_value) - settlement_base,
        )

        claim_name = case.get("supplier_claim")
        if not claim_name or not frappe.db.exists(
            "Supplier Claim",
            claim_name,
        ):
            case.settled_amount = (
                flt(case.claim_deduction_amount)
                + flt(case.refund_amount)
            )
            case.remaining_settlement_amount = max(
                0.0,
                settlement_base - flt(case.settled_amount),
            )
            case.save(ignore_permissions=True)
            continue

        claim = frappe.db.get_value(
            "Supplier Claim",
            claim_name,
            ["docstatus", "status"],
            as_dict=True,
        )
        deduction = (
            abs(
                flt(
                    frappe.db.get_value(
                        "Supplier Claim Invoice",
                        {
                            "parent": claim_name,
                            "parenttype": "Supplier Claim",
                            "purchase_invoice": financial_document,
                        },
                        "included_amount",
                    )
                )
            )
            if financial_document
            else 0
        )
        deduction = min(settlement_base, deduction)
        refund = flt(case.refund_amount)

        if claim.docstatus == 0:
            case.planned_claim_deduction_amount = (
                deduction or settlement_base
            )
            case.claim_deduction_amount = 0
            case.settled_amount = refund
            case.remaining_settlement_amount = max(
                0.0,
                settlement_base - refund,
            )
            case.settlement_status = "Claim Deduction Draft"
            case.operational_status = (
                "Claim Deduction Draft Created"
            )
        elif claim.docstatus == 1:
            case.planned_claim_deduction_amount = deduction
            case.claim_deduction_amount = deduction
            case.settled_amount = deduction + refund
            case.remaining_settlement_amount = max(
                0.0,
                settlement_base - deduction - refund,
            )
            if (
                claim.status == "Paid"
                and case.remaining_settlement_amount <= 0.01
            ):
                case.settlement_status = "Settled"
                case.operational_status = "Financially Settled"
            else:
                case.settlement_status = (
                    "Claim Deduction Confirmed"
                    if case.remaining_settlement_amount <= 0.01
                    else "Partially Settled"
                )
                case.operational_status = (
                    "Claim Deduction Confirmed"
                )
        else:
            case.planned_claim_deduction_amount = 0
            case.claim_deduction_amount = 0
            case.settled_amount = refund
            case.remaining_settlement_amount = max(
                0.0,
                settlement_base - refund,
            )
            case.settlement_status = (
                "Partially Settled"
                if refund > 0
                else "Cancelled"
            )
            case.operational_status = _status_before_claim(case)

        case.save(ignore_permissions=True)
