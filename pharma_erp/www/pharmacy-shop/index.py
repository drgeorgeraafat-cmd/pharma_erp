from __future__ import annotations

import frappe

from pharma_erp.controlled_product_listing import _catalog_brand


def get_context(context):
    context.no_cache = 1
    context.title = "Online Pharmacy Catalog"
    context.brand = _catalog_brand()
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context
