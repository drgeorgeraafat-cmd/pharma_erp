from __future__ import annotations

import os

import frappe
from frappe.modules.import_file import import_file_by_path


WAREHOUSES = (
    "Recall Quarantine",
    "Expired Drugs",
    "Returns With Supplier",
)


def _import_doctype(doctype_folder: str, doctype_name: str) -> None:
    path = frappe.get_app_path(
        "pharma_erp", "pharma_erp", "doctype", doctype_folder, f"{doctype_folder}.json"
    )
    if not os.path.exists(path):
        frappe.throw(f"Missing DocType JSON file: {path}")
    import_file_by_path(path, force=True)
    frappe.clear_cache(doctype=doctype_name)
    frappe.db.updatedb(doctype_name)


def _ensure_special_warehouses() -> None:
    for company in frappe.get_all("Company", pluck="name"):
        abbr = frappe.get_cached_value("Company", company, "abbr")
        parent = f"All Warehouses - {abbr}"
        if not frappe.db.exists("Warehouse", parent):
            continue
        for warehouse_name in WAREHOUSES:
            if frappe.db.exists("Warehouse", {"company": company, "warehouse_name": warehouse_name}):
                continue
            doc = frappe.new_doc("Warehouse")
            doc.warehouse_name = warehouse_name
            doc.company = company
            doc.parent_warehouse = parent
            doc.is_group = 0
            doc.insert(ignore_permissions=True)


def execute() -> None:
    _ensure_special_warehouses()
    _import_doctype("pharmacy_return_case", "Pharmacy Return Case")
    _import_doctype("pharmacy_return_item", "Pharmacy Return Item")
    frappe.clear_cache()
