from __future__ import annotations

import json
import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.modules.import_file import import_file_by_path


CASE_FIELDS = (
    "approved_debit_note_posting_date",
    "approved_debit_note",
    "approved_debit_note_status",
    "approved_debit_note_amount",
    "approved_debit_note_outstanding",
    "accepted_stock_finalized_quantity",
)


def execute():
    path = frappe.get_app_path(
        "pharma_erp",
        "pharma_erp",
        "doctype",
        "pharmacy_return_case",
        "pharmacy_return_case.json",
    )
    if not os.path.exists(path):
        frappe.throw(f"Missing DocType JSON file: {path}")

    with open(path, encoding="utf-8") as source:
        data = json.load(source)

    fieldnames = {
        field.get("fieldname")
        for field in (data.get("fields") or [])
        if field.get("fieldname")
    }
    missing = [field for field in CASE_FIELDS if field not in fieldnames]
    if missing:
        frappe.throw(
            f"Outdated Pharmacy Return Case JSON. Missing fields: {', '.join(missing)}"
        )

    import_file_by_path(path, force=True)
    frappe.clear_cache()
    frappe.db.updatedb("Pharmacy Return Case")

    absent = [
        field for field in CASE_FIELDS
        if not frappe.db.has_column("Pharmacy Return Case", field)
    ]
    if absent:
        frappe.throw(
            "Approved Debit Note schema sync failed: "
            + frappe.as_json(absent)
        )

    create_custom_fields(
        {
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
        },
        update=True,
    )
    frappe.clear_cache()
