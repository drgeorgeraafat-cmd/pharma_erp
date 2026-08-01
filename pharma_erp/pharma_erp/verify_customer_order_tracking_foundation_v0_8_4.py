from __future__ import annotations

from typing import Any

import frappe

from pharma_erp.customer_order_tracking import (
    _build_tracking_token,
    get_public_order_tracking,
)
from pharma_erp.pharma_erp.install_customer_order_tracking_foundation_v0_8_4 import (
    verify as verify_installation,
)

FORBIDDEN_PUBLIC_KEYS = {
    "customer",
    "customer_name",
    "mobile_no",
    "email_id",
    "address_line1",
    "address_line2",
    "formatted_address",
    "customer_address",
    "sales_invoice",
    "payment_entry",
    "pharmacy_shift",
    "delivery_shift",
    "collection_shift",
    "gl_entries",
    "internal_notes",
    "payment_review_notes",
}


def _business_snapshot(order_name: str) -> dict[str, Any]:
    order = frappe.db.get_value(
        "Online Order",
        order_name,
        [
            "name",
            "status",
            "payment_status",
            "sales_invoice",
            "payment_entry",
            "modified",
        ],
        as_dict=True,
    ) or {}
    return {
        "order": order,
        "sales_invoices": frappe.db.count("Sales Invoice"),
        "payment_entries": frappe.db.count("Payment Entry"),
        "gl_entries": frappe.db.count("GL Entry"),
        "stock_ledger_entries": frappe.db.count("Stock Ledger Entry"),
    }


def _token_for_order(order_name: str) -> str:
    values = frappe.db.get_value(
        "Online Order",
        order_name,
        ["custom_tracking_token_id", "custom_tracking_token_version"],
        as_dict=True,
    ) or {}
    return _build_tracking_token(
        int(values.get("custom_tracking_token_version") or 1),
        str(values.get("custom_tracking_token_id") or ""),
    )


def _audit_order(order_name: str) -> dict[str, Any]:
    before = _business_snapshot(order_name)
    payload = get_public_order_tracking(_token_for_order(order_name))
    after = _business_snapshot(order_name)

    if before != after:
        frappe.throw(f"Public tracking changed business state for {order_name}.")
    leaked = sorted(FORBIDDEN_PUBLIC_KEYS & set(payload))
    if leaked:
        frappe.throw("Public tracking payload exposes forbidden keys: " + ", ".join(leaked))
    if int(payload.get("read_only") or 0) != 1:
        frappe.throw("Public tracking payload is not marked read-only.")
    if payload.get("online_order") != order_name:
        frappe.throw("Public tracking returned another Online Order.")
    if not payload.get("timeline"):
        frappe.throw("Public tracking timeline is empty.")
    if not payload.get("customer_status"):
        frappe.throw("Public customer status is missing.")

    return {
        "online_order": order_name,
        "status_label": payload["customer_status"]["label_ar"],
        "fulfilment_method": payload.get("fulfilment_method"),
        "payment_status": payload.get("payment_status_label_ar"),
        "timeline_steps": len(payload.get("timeline") or []),
        "item_rows": len(payload.get("items") or []),
        "business_state_unchanged": 1,
        "forbidden_keys_exposed": 0,
    }


def run() -> dict:
    installation = verify_installation()
    candidates = [
        name
        for name in ("OO-2026-00004", "OO-2026-00006")
        if frappe.db.exists("Online Order", name)
    ]
    if not candidates:
        candidates = frappe.get_all(
            "Online Order",
            filters={"docstatus": ["<", 2]},
            pluck="name",
            order_by="modified desc",
            limit=2,
        )
    if not candidates:
        frappe.throw("No Online Order is available for the tracking audit.")

    audited = [_audit_order(name) for name in candidates]

    invalid_token_rejected = 0
    try:
        get_public_order_tracking(
            "TRK1.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA."
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        )
    except Exception:
        invalid_token_rejected = 1
    if not invalid_token_rejected:
        frappe.throw("Invalid customer tracking token was not rejected.")

    frappe.db.rollback()
    return {
        "status": "ok",
        "step": "4A.1",
        "installation": installation,
        "audited_orders": audited,
        "invalid_token_rejected": invalid_token_rejected,
        "public_business_state_immutable": 1,
        "public_payload_whitelist": 1,
        "public_route_read_only": 1,
    }
