from __future__ import annotations

import frappe

WAREHOUSES = (
    "Recall Quarantine",
    "Expired Drugs",
    "Returns With Supplier",
)


def execute():
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
