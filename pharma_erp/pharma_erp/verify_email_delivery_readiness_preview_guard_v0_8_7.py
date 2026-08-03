
from __future__ import annotations

from pathlib import Path

import frappe

from pharma_erp.customer_notification_delivery import (
    ATTEMPT_DOCTYPE,
    DELIVERY_MODE_PREVIEW,
    SETTINGS_DOCTYPE,
    _readiness_payload,
)
from pharma_erp.customer_order_notifications import NOTIFICATION_DOCTYPE


def _count(sql: str) -> int:
    rows = frappe.db.sql(sql, as_list=True)
    return int(rows[0][0] or 0) if rows else 0


def run() -> dict:
    settings_meta = frappe.get_meta(SETTINGS_DOCTYPE)
    attempt_meta = frappe.get_meta(ATTEMPT_DOCTYPE)
    settings = frappe.get_single(SETTINGS_DOCTYPE)
    readiness = _readiness_payload()

    raw_recipient_fields = {
        "recipient",
        "recipient_email",
        "recipient_mobile",
        "email",
        "mobile_no",
        "phone",
        "raw_recipient",
    }
    attempt_raw_fields = sorted(
        field.fieldname
        for field in attempt_meta.fields
        if field.fieldname in raw_recipient_fields
    )

    notifications = frappe.db.count(NOTIFICATION_DOCTYPE)
    deferred = frappe.db.count(
        NOTIFICATION_DOCTYPE, {"notification_status": "Deferred"}
    )
    active_outbound = _count(
        f"""
        SELECT COUNT(*)
        FROM `tab{NOTIFICATION_DOCTYPE}`
        WHERE notification_status IN ('Pending', 'Sent', 'Failed')
        """
    )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    hooks_text = (app_path / "hooks.py").read_text(encoding="utf-8")
    delivery_text = (
        app_path / "customer_notification_delivery.py"
    ).read_text(encoding="utf-8")
    outbox_js = (
        app_path
        / "public"
        / "js"
        / "online_order_customer_notification.js"
    ).read_text(encoding="utf-8")
    settings_js = (
        app_path
        / "public"
        / "js"
        / "online_order_notification_delivery_settings.js"
    ).read_text(encoding="utf-8")

    return {
        "status": "ok",
        "step": "4D",
        "delivery_settings_doctype": int(bool(settings_meta)),
        "delivery_attempt_doctype": int(bool(attempt_meta)),
        "delivery_mode": settings.delivery_mode,
        "preview_only": int(settings.delivery_mode == DELIVERY_MODE_PREVIEW),
        "outbound_email_enabled": int(
            bool(settings.outbound_email_enabled)
        ),
        "preview_ready": readiness["preview_ready"],
        "external_delivery_ready": readiness["external_delivery_ready"],
        "notification_intents": notifications,
        "deferred_intents": deferred,
        "active_outbound_rows": active_outbound,
        "delivery_attempts": frappe.db.count(ATTEMPT_DOCTYPE),
        "attempt_raw_recipient_fields": attempt_raw_fields,
        "attempt_raw_recipient_storage": int(not attempt_raw_fields),
        "recipient_hash_match_required": int(
            bool(settings.require_recipient_hash_match)
        ),
        "response_header_hook_installed": int(
            "apply_notification_delivery_response_headers" in hooks_text
        ),
        "outbox_desk_preview_installed": int(
            "preview_notification" in outbox_js
            and "request_controlled_delivery" in outbox_js
        ),
        "settings_readiness_button_installed": int(
            "get_delivery_readiness" in settings_js
        ),
        "no_sendmail_call": int("frappe.sendmail" not in delivery_text),
        "no_email_queue_insert": int("Email Queue" not in delivery_text),
        "creates_email_queue": 0,
        "creates_communication": 0,
        "sends_external_email": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }
