from __future__ import annotations

import frappe


def execute():
    if not frappe.db.exists("DocType", "Pharmacy Return Case"):
        return

    frappe.reload_doc(
        "pharma_erp",
        "doctype",
        "pharmacy_return_case",
        force=True,
    )
    frappe.reload_doc(
        "pharma_erp",
        "doctype",
        "pharmacy_return_item",
        force=True,
    )
    frappe.db.updatedb("Pharmacy Return Case")
    frappe.db.updatedb("Pharmacy Return Item")

    meta = frappe.get_meta("Pharmacy Return Case", cached=False)
    if not meta.has_field("returns_with_supplier_warehouse"):
        return

    for company in frappe.get_all("Company", pluck="name"):
        warehouse = frappe.db.get_value(
            "Warehouse",
            {
                "company": company,
                "warehouse_name": "Returns With Supplier",
                "is_group": 0,
                "disabled": 0,
            },
            "name",
        )
        if not warehouse:
            continue

        frappe.db.sql(
            """
            update `tabPharmacy Return Case`
            set returns_with_supplier_warehouse = %s
            where company = %s
              and return_type = 'Regulatory Batch Recall'
              and ifnull(returns_with_supplier_warehouse, '') = ''
            """,
            (warehouse, company),
        )
