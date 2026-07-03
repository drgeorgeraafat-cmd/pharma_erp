from __future__ import annotations

import json
import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.modules.import_file import import_file_by_path


CASE_FIELDS = (
    "refund_posting_date",
    "refund_mode_of_payment",
    "refund_account",
    "refund_request_amount",
    "refund_reference_no",
    "refund_reference_date",
    "refund_payment_entry",
    "refund_payment_entry_status",
    "refund_entries_count",
    "refund_notes",
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
            "Supplier Refund settlement schema sync failed: "
            + frappe.as_json(absent)
        )

    create_custom_fields(
        {
            "Payment Entry": [
                {
                    "fieldname": "custom_pharmacy_return_case",
                    "label": "Pharmacy Return Case",
                    "fieldtype": "Link",
                    "options": "Pharmacy Return Case",
                    "insert_after": "reference_date",
                    "read_only": 1,
                    "no_copy": 1,
                    "allow_on_submit": 1,
                },
                {
                    "fieldname": "custom_supplier_refund_method",
                    "label": "Supplier Refund Method",
                    "fieldtype": "Select",
                    "options": "\nCash Refund\nBank Refund",
                    "insert_after": "custom_pharmacy_return_case",
                    "read_only": 1,
                    "no_copy": 1,
                    "allow_on_submit": 1,
                },
                {
                    "fieldname": "custom_supplier_refund_notes",
                    "label": "Supplier Refund Notes",
                    "fieldtype": "Small Text",
                    "insert_after": "custom_supplier_refund_method",
                    "read_only": 1,
                    "no_copy": 1,
                    "allow_on_submit": 1,
                },
            ]
        },
        update=True,
    )
    frappe.clear_cache()
