from __future__ import annotations

import frappe

from pharma_erp.controlled_product_listing import _catalog_brand

no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.title = "طلباتي"
    context.brand = _catalog_brand()
    context.is_guest = frappe.session.user == "Guest"
    context.csrf_token = frappe.sessions.get_csrf_token()
    # Reuse the account response-header hook without expanding the public API surface.
    frappe.flags.customer_account_no_store = True
    return context
