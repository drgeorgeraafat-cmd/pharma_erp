from __future__ import annotations

import frappe


def execute():
    for company in frappe.get_all("Company", pluck="name"):
        abbr = frappe.get_cached_value("Company", company, "abbr")
        parent = f"All Warehouses - {abbr}"
        if not frappe.db.exists("Warehouse", parent):
            continue

        if not frappe.db.exists(
            "Warehouse",
            {"company": company, "warehouse_name": "Returns With Supplier"},
        ):
            warehouse = frappe.new_doc("Warehouse")
            warehouse.warehouse_name = "Returns With Supplier"
            warehouse.company = company
            warehouse.parent_warehouse = parent
            warehouse.is_group = 0
            warehouse.insert(ignore_permissions=True)

    if not frappe.db.exists("DocType", "Pharmacy Return Case"):
        return

    returns_warehouse_by_company = {}
    cases = frappe.get_all(
        "Pharmacy Return Case",
        filters={"return_type": "Regulatory Batch Recall"},
        fields=["name", "company", "returns_with_supplier_warehouse"],
    )
    for row in cases:
        if row.returns_with_supplier_warehouse:
            continue
        warehouse = returns_warehouse_by_company.get(row.company)
        if warehouse is None:
            warehouse = frappe.db.get_value(
                "Warehouse",
                {
                    "company": row.company,
                    "warehouse_name": "Returns With Supplier",
                    "is_group": 0,
                },
                "name",
            )
            returns_warehouse_by_company[row.company] = warehouse
        if warehouse:
            frappe.db.set_value(
                "Pharmacy Return Case",
                row.name,
                "returns_with_supplier_warehouse",
                warehouse,
                update_modified=False,
            )
