import frappe


def execute():
    # Code-only guard. Keeping a patch entry documents the installed behavior
    # and ensures the migration log records this safety update.
    frappe.reload_doc("pharma_erp", "doctype", "supplier_claim", force=True)
    frappe.reload_doc("pharma_erp", "doctype", "supplier_claim_invoice", force=True)
