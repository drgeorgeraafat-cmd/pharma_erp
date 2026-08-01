from __future__ import annotations

import frappe

from pharma_erp.controlled_product_listing import _catalog_brand
from pharma_erp.customer_order_tracking import _set_no_store_headers


def get_context(context):
    context.no_cache = 1
    context.title = "تتبع طلب الصيدلية"
    context.brand = _catalog_brand()
    _set_no_store_headers()
    return context
