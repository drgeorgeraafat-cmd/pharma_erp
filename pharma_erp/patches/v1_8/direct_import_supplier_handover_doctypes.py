from __future__ import annotations

import json
import os

import frappe
from frappe.modules.import_file import import_file_by_path


REQUIREMENTS = {
    "Pharmacy Return Case": (
        "returns_with_supplier_warehouse",
        "handover_stock_entry",
        "handed_over_quantity",
    ),
    "Pharmacy Return Item": (
        "delivered_qty",
        "rejected_qty",
        "approved_rate",
    ),
}


def _files():
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
    for doctype, path in _files().items():
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
        missing = [
            field for field in fields
            if not frappe.db.has_column(doctype, field)
        ]
        if missing:
            missing_columns[doctype] = missing

    if missing_columns:
        frappe.throw(
            "Direct DocType import did not create required columns: "
            + frappe.as_json(missing_columns)
        )

    supplier_warehouse_cache = {}
    cases = frappe.get_all(
        "Pharmacy Return Case",
        filters={"return_type": "Regulatory Batch Recall"},
        fields=["name", "company", "returns_with_supplier_warehouse"],
    )
    for row in cases:
        if row.returns_with_supplier_warehouse:
            continue

        warehouse = supplier_warehouse_cache.get(row.company)
        if warehouse is None:
            warehouse = frappe.db.get_value(
                "Warehouse",
                {
                    "company": row.company,
                    "warehouse_name": "Returns With Supplier",
                    "is_group": 0,
                    "disabled": 0,
                },
                "name",
            )
            supplier_warehouse_cache[row.company] = warehouse

        if warehouse:
            frappe.db.set_value(
                "Pharmacy Return Case",
                row.name,
                "returns_with_supplier_warehouse",
                warehouse,
                update_modified=False,
            )
