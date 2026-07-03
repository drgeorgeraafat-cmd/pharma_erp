from __future__ import annotations

import json
import os

import frappe
from frappe.modules.import_file import import_file_by_path


FIELDS = (
    "invoice_returnable_qty",
    "physical_stock_qty",
)


def execute():
    path = frappe.get_app_path(
        "pharma_erp",
        "pharma_erp",
        "doctype",
        "pharmacy_return_item",
        "pharmacy_return_item.json",
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
    missing = [field for field in FIELDS if field not in fieldnames]
    if missing:
        frappe.throw(
            "Outdated Pharmacy Return Item JSON. Missing physical-stock fields: "
            + ", ".join(missing)
        )

    import_file_by_path(path, force=True)
    frappe.clear_cache()
    frappe.db.updatedb("Pharmacy Return Item")

    absent = [
        field
        for field in FIELDS
        if not frappe.db.has_column("Pharmacy Return Item", field)
    ]
    if absent:
        frappe.throw(
            "Invoice return physical-stock schema sync failed: "
            + frappe.as_json(absent)
        )

    frappe.clear_cache()
