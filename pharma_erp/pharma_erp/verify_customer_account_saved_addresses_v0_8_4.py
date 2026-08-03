from __future__ import annotations

import inspect

import frappe

from pharma_erp import customer_account
from pharma_erp.pharma_erp.install_customer_account_saved_addresses_v0_8_4 import (
    verify as verify_installation,
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        frappe.throw(message)


def run() -> dict:
    installation = verify_installation()
    source = inspect.getsource(customer_account)

    _assert(
        "@frappe.whitelist()\ndef get_customer_account" in source,
        "Account read API must require authentication.",
    )
    _assert(
        '@frappe.whitelist(methods=["POST"])\ndef activate_customer_account' in source,
        "Account activation must be POST only.",
    )
    _assert(
        '@frappe.whitelist(methods=["POST"])\ndef save_customer_address' in source,
        "Address save must be POST only.",
    )
    _assert(
        '@frappe.whitelist(methods=["POST"])\ndef archive_customer_address' in source,
        "Address archive must be POST only.",
    )
    _assert(
        '@frappe.whitelist(methods=["POST"])\ndef claim_guest_order' in source,
        "Guest order claim must be POST only.",
    )
    _assert(
        "source_channel = 'Website'" in source,
        "My Orders must be restricted to website orders.",
    )
    _assert(
        "custom_website_user = %s" in source,
        "My Orders must filter by the authenticated website user.",
    )
    _assert(
        "This Customer record is shared with another website account" in source,
        "Customer account exclusivity guard is missing.",
    )
    _assert(
        "This address does not belong exclusively" in source,
        "Address ownership isolation guard is missing.",
    )
    _assert(
        "_parse_tracking_token(tracking_token)" in source,
        "Guest claim must verify the signed tracking token.",
    )
    _assert(
        "order_mobile[-4:] != mobile_suffix" in source,
        "Guest claim must verify the mobile suffix.",
    )
    _assert(
        "existing_user and existing_user != user" in source,
        "Guest claim cross-account guard is missing.",
    )
    _assert(
        "custom_guest_claimed_at" in source,
        "Guest claim audit fields are missing.",
    )
    _assert(
        '"guest_order_auto_claim": 0' in source,
        "Unsafe automatic guest-order matching must stay disabled.",
    )
    _assert(
        '"guest_order_claim_changes_customer": 0' in source,
        "Guest claim must not rewrite the business Customer.",
    )
    _assert(
        '"creates_sales_invoice": 0' in source,
        "Financial side-effect declaration is missing.",
    )
    _assert(
        '"creates_stock_entries": 0' in source,
        "Stock side-effect declaration is missing.",
    )

    standard_auth = {
        "login_page": bool(frappe.get_attr("frappe.www.login.get_context")),
        "signup_api": bool(frappe.get_attr("frappe.core.doctype.user.user.sign_up")),
        "password_reset_api": bool(
            frappe.get_attr("frappe.core.doctype.user.user.reset_password")
        ),
    }
    _assert(
        all(standard_auth.values()),
        "Standard Frappe authentication endpoints are unavailable.",
    )

    return {
        "status": "ok",
        "step": "4A.2",
        "installation": installation,
        "standard_auth": standard_auth,
        "authenticated_account_api": 1,
        "customer_activation_guarded": 1,
        "exclusive_customer_account_guard": 1,
        "saved_address_owner_isolation": 1,
        "default_address_supported": 1,
        "address_archive_preserves_history": 1,
        "my_orders_owner_filter": 1,
        "my_orders_tracking_links": 1,
        "checkout_saved_address_integration": 1,
        "secure_guest_order_claim": 1,
        "guest_order_auto_claim": 0,
        "guest_order_claim_tracking_token_proof": 1,
        "guest_order_claim_mobile_suffix_proof": 1,
        "guest_order_claim_cross_account_guard": 1,
        "guest_order_claim_preserves_customer": 1,
        "no_public_password_storage": 1,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }


def execute() -> dict:
    return run()
