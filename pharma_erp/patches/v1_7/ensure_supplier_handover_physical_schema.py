from __future__ import annotations

import frappe


CASE_FIELDS = (
    "returns_with_supplier_warehouse",
    "handover_stock_entry",
    "handed_over_quantity",
)
ITEM_FIELDS = (
    "delivered_qty",
    "rejected_qty",
    "approved_rate",
)


def execute():
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

    missing = {}
    for doctype, fields in (
        ("Pharmacy Return Case", CASE_FIELDS),
        ("Pharmacy Return Item", ITEM_FIELDS),
    ):
        absent = [
            field for field in fields
            if not frappe.db.has_column(doctype, field)
        ]
        if absent:
            missing[doctype] = absent

    if missing:
        frappe.throw(
            "Supplier handover physical schema sync failed: "
            + frappe.as_json(missing)
        )

    warehouse_cache = {}
    cases = frappe.get_all(
        "Pharmacy Return Case",
        filters={"return_type": "Regulatory Batch Recall"},
        fields=["name", "company", "returns_with_supplier_warehouse"],
    )
    for row in cases:
        if row.returns_with_supplier_warehouse:
            continue

        warehouse = warehouse_cache.get(row.company)
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
            warehouse_cache[row.company] = warehouse

        if warehouse:
            frappe.db.set_value(
                "Pharmacy Return Case",
                row.name,
                "returns_with_supplier_warehouse",
                warehouse,
                update_modified=False,
            )

    frappe.clear_cache()
