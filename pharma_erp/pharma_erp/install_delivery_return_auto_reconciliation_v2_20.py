import frappe
from frappe.utils import cint, flt

VERSION = "2.20"


def repair(invoice_name):
    from pharma_erp.pharma_erp.delivery_return_workflow import reconcile_delivery_return

    result = reconcile_delivery_return(invoice_name, finalize=True)
    frappe.db.commit()
    return result


def verify(invoice_name=None):
    result = {
        "version": VERSION,
        "module_ready": True,
        "invoice_name": invoice_name or "",
    }
    if not invoice_name:
        result["ready"] = True
        return result

    source = frappe.get_doc("Sales Invoice", invoice_name)
    notes = frappe.get_all(
        "Sales Invoice",
        filters={"is_return": 1, "return_against": invoice_name, "docstatus": 1},
        fields=["name", "outstanding_amount", "grand_total"],
        order_by="creation asc",
        limit_page_length=2000,
    )
    result.update(
        {
            "original_outstanding": flt(source.outstanding_amount, 2),
            "delivery_status": source.get("custom_delivery_status") or "",
            "return_status": source.get("custom_delivery_return_status") or "",
            "credit_notes": notes,
            "ready": abs(flt(source.outstanding_amount)) <= 0.009,
        }
    )
    return result
