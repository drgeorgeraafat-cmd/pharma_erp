import frappe
from frappe import _
from frappe.utils import flt

TOLERANCE = 0.01


def _row_state(claim, row):
    invoice = frappe.db.get_value(
        "Purchase Invoice",
        row.purchase_invoice,
        [
            "name",
            "docstatus",
            "company",
            "supplier",
            "is_return",
            "grand_total",
            "outstanding_amount",
            "status",
            "custom_supplier_claim",
            "custom_pharmacy_return_case",
        ],
        as_dict=True,
    )
    state = {
        "row_name": row.name,
        "idx": row.idx,
        "purchase_invoice": row.purchase_invoice,
        "included_amount": flt(row.included_amount),
        "stored_outstanding_amount": flt(row.outstanding_amount),
        "action": "KEEP",
        "reason": "OK",
    }
    if not invoice:
        state.update({"action": "REMOVE", "reason": "Purchase Invoice not found"})
        return state

    state.update(
        {
            "is_return": int(invoice.is_return or 0),
            "grand_total": flt(invoice.grand_total),
            "live_outstanding_amount": flt(invoice.outstanding_amount),
            "invoice_status": invoice.status,
            "linked_supplier_claim": invoice.custom_supplier_claim,
            "return_case": invoice.custom_pharmacy_return_case,
        }
    )

    if invoice.docstatus != 1:
        state.update({"action": "REMOVE", "reason": "Purchase Invoice is not submitted"})
    elif invoice.company != claim.company or invoice.supplier != claim.supplier:
        state.update({"action": "REMOVE", "reason": "Different company or supplier"})
    elif invoice.custom_supplier_claim and invoice.custom_supplier_claim != claim.name:
        state.update(
            {
                "action": "REMOVE",
                "reason": f"Already linked to Supplier Claim {invoice.custom_supplier_claim}",
            }
        )
    elif invoice.is_return or flt(row.included_amount) < 0:
        if flt(invoice.outstanding_amount) >= -TOLERANCE:
            state.update(
                {
                    "action": "REMOVE",
                    "reason": "Return/Debit Note has no open supplier credit outstanding",
                }
            )
        elif abs(flt(row.included_amount)) - abs(flt(invoice.outstanding_amount)) > TOLERANCE:
            state.update(
                {
                    "action": "ADJUST_OR_REMOVE",
                    "reason": "Included return amount exceeds live outstanding",
                    "suggested_included_amount": -abs(flt(invoice.outstanding_amount)),
                }
            )
    else:
        if flt(invoice.outstanding_amount) <= TOLERANCE:
            state.update(
                {
                    "action": "REMOVE",
                    "reason": "Positive invoice has no payable outstanding",
                }
            )
        elif flt(row.included_amount) - flt(invoice.outstanding_amount) > TOLERANCE:
            state.update(
                {
                    "action": "ADJUST_OR_REMOVE",
                    "reason": "Included invoice amount exceeds live outstanding",
                    "suggested_included_amount": flt(invoice.outstanding_amount),
                }
            )

    if state.get("return_case"):
        case = frappe.db.get_value(
            "Pharmacy Return Case",
            state["return_case"],
            [
                "operational_status",
                "settlement_status",
                "refund_payment_entry",
                "remaining_settlement_amount",
            ],
            as_dict=True,
        )
        if case:
            state["return_case_state"] = case

    return state


@frappe.whitelist()
def audit_supplier_claim_rows(claim_name):
    claim = frappe.get_doc("Supplier Claim", claim_name)
    rows = [_row_state(claim, row) for row in claim.invoices]
    return {
        "supplier_claim": claim.name,
        "docstatus": claim.docstatus,
        "status": claim.status,
        "rows": rows,
        "problem_rows": [row for row in rows if row["action"] != "KEEP"],
    }


@frappe.whitelist()
def remove_closed_supplier_claim_rows(claim_name, apply=0):
    claim = frappe.get_doc("Supplier Claim", claim_name)
    if claim.docstatus != 0:
        frappe.throw(_("Only Draft Supplier Claims can be cleaned automatically."))

    audit = audit_supplier_claim_rows(claim_name)
    remove_names = {
        row["row_name"]
        for row in audit["rows"]
        if row["action"] == "REMOVE"
    }
    if not remove_names:
        return {"supplier_claim": claim.name, "removed": [], "message": "No closed rows found."}

    if not int(apply):
        return {
            "supplier_claim": claim.name,
            "dry_run": 1,
            "would_remove": [row for row in audit["rows"] if row["row_name"] in remove_names],
        }

    kept = []
    removed = []
    for row in claim.invoices:
        if row.name in remove_names:
            removed.append(row.purchase_invoice)
        else:
            kept.append(row)
    claim.set("invoices", kept)
    claim.save(ignore_permissions=True)
    return {
        "supplier_claim": claim.name,
        "removed": removed,
        "after": audit_supplier_claim_rows(claim.name),
    }
