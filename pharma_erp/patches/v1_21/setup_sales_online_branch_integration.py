from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from pharma_erp.pharma_erp.branch_operational_integration import (
    branch_from_canonical_warehouse,
    resolve_online_context,
)


CUSTOM_FIELDS = {
    "Sales Invoice": [
        {
            "fieldname": "custom_pharmacy_branch",
            "label": "Pharmacy Branch",
            "fieldtype": "Link",
            "options": "Branch",
            "insert_after": "company",
            "read_only": 0,
            "in_standard_filter": 1,
            "description": "Canonical branch attribution written by controlled Pharmacy POS / Online Order workflows.",
        }
    ]
}


def _reload_app_schema():
    frappe.reload_doc("pharma_erp", "doctype", "delivery_zone", force=True)
    frappe.reload_doc("pharma_erp", "doctype", "online_order", force=True)
    frappe.db.updatedb("Delivery Zone")
    frappe.db.updatedb("Online Order")


def _backfill_delivery_zones():
    for row in frappe.get_all(
        "Delivery Zone",
        filters={"branch": ["is", "not set"]},
        fields=["name", "warehouse"],
        order_by="name asc",
        limit_page_length=10000,
    ):
        if not row.warehouse:
            continue
        company = frappe.db.get_value("Warehouse", row.warehouse, "company") or ""
        branch = branch_from_canonical_warehouse(
            warehouse=row.warehouse,
            company=company,
        )
        context = resolve_online_context(
            company=company,
            fulfilment_method="Home Delivery",
            requested_branch=branch,
            submitted_warehouse=row.warehouse,
        )
        frappe.db.set_value(
            "Delivery Zone",
            row.name,
            {"branch": context["branch"], "warehouse": context["warehouse"]},
            update_modified=False,
        )


def _backfill_online_orders():
    for row in frappe.get_all(
        "Online Order",
        filters={"branch": ["is", "not set"]},
        fields=["name", "company", "fulfilment_method", "warehouse"],
        order_by="creation asc",
        limit_page_length=100000,
    ):
        # Historical rows without an explicit Warehouse remain intentionally
        # Not Attributable. No name/suffix/default inference is permitted.
        if not row.warehouse:
            continue
        branch = branch_from_canonical_warehouse(
            warehouse=row.warehouse,
            company=row.company,
        )
        context = resolve_online_context(
            company=row.company,
            fulfilment_method=row.fulfilment_method,
            requested_branch=branch,
            submitted_warehouse=row.warehouse,
        )
        frappe.db.set_value(
            "Online Order",
            row.name,
            {"branch": context["branch"], "warehouse": context["warehouse"]},
            update_modified=False,
        )


def execute():
    _reload_app_schema()
    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Sales Invoice")
    _backfill_delivery_zones()
    _backfill_online_orders()
