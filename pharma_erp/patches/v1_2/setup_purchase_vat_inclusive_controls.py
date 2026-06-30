"""Add per-line VAT inclusion audit field and clarify supplier invoice price."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields(
        {
            "Purchase Invoice Item": [
                {
                    "fieldname": "custom_vat_inclusive_in_final_rate",
                    "label": "VAT Included in Final Net Rate",
                    "fieldtype": "Check",
                    "default": "1",
                    "insert_after": "custom_tax_entry_mode",
                    "allow_on_submit": 1,
                }
            ]
        },
        update=True,
    )

    supplier_price_field = frappe.db.get_value(
        "Custom Field",
        {"dt": "Purchase Invoice Item", "fieldname": "custom_supplier_base_price"},
        "name",
    )
    if supplier_price_field:
        frappe.db.set_value(
            "Custom Field",
            supplier_price_field,
            "label",
            "Supplier Invoice Price",
            update_modified=False,
        )

    frappe.clear_cache()
