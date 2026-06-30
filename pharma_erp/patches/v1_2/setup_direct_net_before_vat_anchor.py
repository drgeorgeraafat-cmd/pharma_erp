"""Persist the supplier-entered Net Before VAT before any additional discount."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields(
        {
            "Purchase Invoice Item": [
                {
                    "fieldname": "custom_entered_net_before_vat",
                    "label": "Entered Net Before VAT",
                    "fieldtype": "Currency",
                    "insert_after": "custom_vat_rate",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "description": "Supplier net before VAT and before the separate Additional Discount.",
                }
            ]
        },
        update=True,
    )
    frappe.clear_cache()
