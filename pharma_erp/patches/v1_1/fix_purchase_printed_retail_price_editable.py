"""Make Printed Retail Price editable and retire the legacy invoice-rate client script."""

import frappe


def execute():
    custom_field_name = frappe.db.get_value(
        "Custom Field",
        {
            "dt": "Purchase Invoice Item",
            "fieldname": "custom_selling_price",
        },
        "name",
    )

    if custom_field_name:
        custom_field = frappe.get_doc("Custom Field", custom_field_name)
        custom_field.read_only = 0
        custom_field.fetch_from = ""
        if custom_field.meta.has_field("fetch_if_empty"):
            custom_field.fetch_if_empty = 0
        custom_field.flags.ignore_permissions = True
        custom_field.save(ignore_permissions=True)

    # This calculation has moved into the pharma_erp controller and bundled JS.
    # Keeping the old Client Script active makes Frappe calculate the row twice.
    if frappe.db.exists("Client Script", "Purchase Invoice V1"):
        frappe.db.set_value(
            "Client Script",
            "Purchase Invoice V1",
            "enabled",
            0,
            update_modified=False,
        )

    frappe.clear_cache(doctype="Purchase Invoice Item")
    frappe.clear_cache(doctype="Purchase Invoice")
