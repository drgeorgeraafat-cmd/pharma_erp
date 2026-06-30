from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Purchase Invoice": [
            {
                "fieldname": "custom_pharmacy_return_case",
                "label": "Pharmacy Return Case",
                "fieldtype": "Link",
                "options": "Pharmacy Return Case",
                "insert_after": "return_against",
                "read_only": 1,
                "no_copy": 1,
                "allow_on_submit": 1,
            }
        ]
    }, update=True)
