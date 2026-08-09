from __future__ import annotations

import frappe

from pharma_erp.pharma_erp.branch_operational_integration import (
    online_role,
    resolve_operational_branch,
    resolve_role_context,
)


def _clean(value) -> str:
    return str(value or "").strip()


def _invoice_role(doc) -> tuple[str, str]:
    online_order = _clean(doc.get("custom_online_order")) if doc.meta.has_field("custom_online_order") else ""
    if online_order:
        values = frappe.db.get_value(
            "Online Order",
            online_order,
            ["branch", "company", "fulfilment_method"],
            as_dict=True,
        )
        if not values:
            frappe.throw(f"Linked Online Order {online_order} was not found.")
        if values.company and doc.company and values.company != doc.company:
            frappe.throw("Linked Online Order belongs to another company.")
        if not _clean(values.branch):
            frappe.throw(
                f"Linked Online Order {online_order} has no canonical Branch attribution."
            )
        return online_role(values.fulfilment_method), _clean(values.branch)

    if int(doc.get("is_return") or 0):
        return "Customer Return", ""
    if int(doc.get("is_pos") or 0):
        return "POS", ""
    return "Sales", ""


def _stock_item_codes(doc) -> set[str]:
    codes = sorted({row.item_code for row in (doc.items or []) if row.item_code})
    if not codes:
        return set()
    rows = frappe.get_all(
        "Item",
        filters={"name": ["in", codes]},
        fields=["name", "is_stock_item"],
        limit_page_length=max(100, len(codes) + 10),
    )
    return {row.name for row in rows if int(row.is_stock_item or 0)}


def validate_sales_invoice_branch(doc, method=None):
    """Canonical Branch/Warehouse guard for new and attributed Sales Invoices.

    Existing legacy invoices that predate `custom_pharmacy_branch` are left
    untouched. Once an invoice has explicit branch attribution, every stock
    warehouse is server-validated against the appropriate operational role.
    """

    if not doc.meta.has_field("custom_pharmacy_branch"):
        return

    current_branch = _clean(doc.get("custom_pharmacy_branch"))
    if not doc.is_new() and not current_branch:
        return

    role, forced_branch = _invoice_role(doc)
    requested_branch = forced_branch or current_branch
    if not requested_branch:
        requested_branch = resolve_operational_branch(company=doc.company)

    context = resolve_role_context(
        company=doc.company,
        role=role,
        requested_branch=requested_branch,
        submitted_warehouse=doc.get("set_warehouse"),
    )

    doc.custom_pharmacy_branch = context["branch"]
    doc.set_warehouse = context["warehouse"]

    stock_items = _stock_item_codes(doc)
    for row in doc.items or []:
        if row.item_code not in stock_items:
            continue
        if row.warehouse and row.warehouse != context["warehouse"]:
            frappe.throw(
                "Sales Invoice item {0} warehouse {1} conflicts with canonical {2} warehouse {3} for Branch {4}.".format(
                    row.item_code,
                    row.warehouse,
                    role,
                    context["warehouse"],
                    context["branch"],
                )
            )
        row.warehouse = context["warehouse"]
