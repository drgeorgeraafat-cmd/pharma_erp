from __future__ import annotations

import frappe

from pharma_erp.controlled_product_listing import _catalog_brand


def get_context(context):
    context.no_cache = 1
    context.title = "Online Order Received"
    context.brand = _catalog_brand()
    return context
