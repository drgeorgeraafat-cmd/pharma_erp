import frappe


LEGACY_PAGE = "pharmacy-shift-manag"


def execute():
    """Remove the obsolete Pharmacy Shift Management page metadata."""
    if frappe.db.exists("Page", LEGACY_PAGE):
        frappe.delete_doc(
            "Page",
            LEGACY_PAGE,
            force=True,
            ignore_permissions=True,
        )

    frappe.clear_cache()
