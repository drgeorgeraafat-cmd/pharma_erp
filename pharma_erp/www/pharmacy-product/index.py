from __future__ import annotations

import frappe

from pharma_erp.controlled_product_listing import get_public_product


def get_context(context):
    context.no_cache = 1
    item_code = frappe.form_dict.get("item")
    product = get_public_product(item_code)
    if not product:
        frappe.throw(
            "This product is not published or is not available online.",
            frappe.DoesNotExistError,
        )

    context.product = product
    context.title = product["item_name"]
    return context
