from __future__ import annotations

import json
import os

import frappe
from frappe.modules.import_file import import_file_by_path


REQUIREMENTS = {
    "Pharmacy Return Case": (
        "supplier_response_date",
        "supplier_response_reference",
        "supplier_response_attachment",
        "supplier_response_notes",
        "accepted_quantity",
        "rejected_quantity",
        "pending_response_quantity",
        "rejection_return_stock_entry",
        "rejected_return_quantity",
    ),
    "Pharmacy Return Item": (
        "accepted_qty",
        "rejected_qty",
        "approved_rate",
        "rejection_reason",
        "rejected_returned_qty",
    ),
}


def _doctype_files():
    return {
        "Pharmacy Return Case": frappe.get_app_path(
            "pharma_erp",
            "pharma_erp",
            "doctype",
            "pharmacy_return_case",
            "pharmacy_return_case.json",
        ),
        "Pharmacy Return Item": frappe.get_app_path(
            "pharma_erp",
            "pharma_erp",
            "doctype",
            "pharmacy_return_item",
            "pharmacy_return_item.json",
        ),
    }


def execute():
    for doctype, path in _doctype_files().items():
        if not os.path.exists(path):
            frappe.throw(f"Missing DocType JSON file: {path}")

        with open(path, encoding="utf-8") as source:
            data = json.load(source)

        fieldnames = {
            field.get("fieldname")
            for field in (data.get("fields") or [])
            if field.get("fieldname")
        }
        missing = [
            field for field in REQUIREMENTS[doctype]
            if field not in fieldnames
        ]
        if missing:
            frappe.throw(
                f"Outdated DocType JSON file {path}. "
                f"Missing fields: {', '.join(missing)}"
            )

        import_file_by_path(path, force=True)

    frappe.clear_cache()
    frappe.db.updatedb("Pharmacy Return Case")
    frappe.db.updatedb("Pharmacy Return Item")
    frappe.clear_cache()

    missing_columns = {}
    for doctype, fields in REQUIREMENTS.items():
        absent = [
            field for field in fields
            if not frappe.db.has_column(doctype, field)
        ]
        if absent:
            missing_columns[doctype] = absent

    if missing_columns:
        frappe.throw(
            "Supplier response schema sync failed: "
            + frappe.as_json(missing_columns)
        )
