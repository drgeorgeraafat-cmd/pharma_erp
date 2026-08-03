from __future__ import annotations

import frappe

from pharma_erp.controlled_product_listing import _catalog_brand
from pharma_erp.customer_account import ACCOUNT_ROUTE

no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.title = "حسابي"
    context.brand = _catalog_brand()
    context.account_route = ACCOUNT_ROUTE
    context.is_guest = frappe.session.user == "Guest"
    context.disable_signup = int(bool(frappe.get_website_settings("disable_signup")))
    context.csrf_token = frappe.sessions.get_csrf_token()
    return context
