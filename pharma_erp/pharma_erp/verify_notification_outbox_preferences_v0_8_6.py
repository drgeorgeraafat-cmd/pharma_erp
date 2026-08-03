
from __future__ import annotations

from pathlib import Path

import frappe

from pharma_erp.customer_order_notifications import (
    ELIGIBLE_SOURCE_STATUSES,
    NOTIFICATION_DOCTYPE,
    OUTBOUND_DELIVERY_ENABLED,
    PREFERENCE_DOCTYPE,
)


def _count(sql: str, values=None) -> int:
    row = frappe.db.sql(sql, values or (), as_list=True)
    return int(row[0][0] or 0) if row else 0


def run() -> dict:
    preference_meta = frappe.get_meta(PREFERENCE_DOCTYPE)
    notification_meta = frappe.get_meta(NOTIFICATION_DOCTYPE)

    raw_field_names = {
        "recipient",
        "recipient_email",
        "recipient_mobile",
        "email",
        "mobile_no",
        "phone",
        "raw_recipient",
    }
    present_raw_fields = sorted(
        field.fieldname
        for field in notification_meta.fields
        if field.fieldname in raw_field_names
    )

    preferences = frappe.db.count(PREFERENCE_DOCTYPE)
    notifications = frappe.db.count(NOTIFICATION_DOCTYPE)
    deferred = frappe.db.count(
        NOTIFICATION_DOCTYPE, {"notification_status": "Deferred"}
    )
    active_delivery_rows = _count(
        f"""
        SELECT COUNT(*)
        FROM `tab{NOTIFICATION_DOCTYPE}`
        WHERE notification_status IN ('Pending', 'Sent', 'Failed')
        """
    )
    duplicate_idempotency = _count(
        f"""
        SELECT COUNT(*)
        FROM (
            SELECT idempotency_key
            FROM `tab{NOTIFICATION_DOCTYPE}`
            GROUP BY idempotency_key
            HAVING COUNT(*) > 1
        ) duplicates
        """
    )

    eligible_statuses = tuple(ELIGIBLE_SOURCE_STATUSES)
    placeholders = ", ".join(["%s"] * len(eligible_statuses))
    eligible_events = _count(
        f"""
        SELECT COUNT(*)
        FROM `tabOnline Order Customer Status Event` event
        INNER JOIN `tabOnline Order` order_doc
            ON order_doc.name = event.parent
        INNER JOIN `tabUser` website_user
            ON website_user.name = order_doc.custom_website_user
           AND website_user.enabled = 1
           AND website_user.user_type = 'Website User'
        INNER JOIN `tab{PREFERENCE_DOCTYPE}` preference
            ON preference.website_user = order_doc.custom_website_user
           AND preference.order_updates_enabled = 1
           AND preference.email_enabled = 1
        WHERE event.source_status IN ({placeholders})
        """,
        eligible_statuses,
    )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    hooks_text = (app_path / "hooks.py").read_text(encoding="utf-8")
    account_html = (
        app_path / "www" / "pharmacy-account" / "index.html"
    ).read_text(encoding="utf-8")
    account_js = (
        app_path / "public" / "js" / "customer_account.js"
    ).read_text(encoding="utf-8")
    module_text = (
        app_path / "customer_order_notifications.py"
    ).read_text(encoding="utf-8")

    return {
        "status": "ok",
        "step": "4C",
        "preference_doctype": int(bool(preference_meta)),
        "notification_outbox_doctype": int(bool(notification_meta)),
        "preferences": preferences,
        "notification_intents": notifications,
        "eligible_events": eligible_events,
        "eligible_event_coverage": int(notifications == eligible_events),
        "all_intents_deferred": int(notifications == deferred),
        "active_delivery_rows": active_delivery_rows,
        "duplicate_idempotency_keys": duplicate_idempotency,
        "raw_recipient_fields": present_raw_fields,
        "raw_recipient_storage": int(not present_raw_fields),
        "masked_recipient_field": int(
            notification_meta.has_field("recipient_masked")
        ),
        "recipient_hash_field": int(
            notification_meta.has_field("recipient_hash")
        ),
        "preference_unique_user": int(
            bool(preference_meta.get_field("website_user").unique)
        ),
        "outbound_delivery_enabled": int(OUTBOUND_DELIVERY_ENABLED),
        "email_delivery_enabled": 0,
        "whatsapp_delivery_enabled": 0,
        "sms_delivery_enabled": 0,
        "order_update_hook_installed": int(
            "BEGIN PHARMA STEP 4C CONTROLLED CUSTOMER NOTIFICATION FOUNDATION"
            in hooks_text
            and "capture_order_notification_intents" in hooks_text
        ),
        "response_header_hook_installed": int(
            "apply_customer_notification_response_headers" in hooks_text
        ),
        "account_preferences_ui": int(
            "pharma-account-notification-form" in account_html
            and "notification-preferences-endpoint" in account_html
            and "Step 4C" in account_html
        ),
        "account_preferences_js": int(
            "initNotificationPreferences" in account_js
            and "updateNotificationPreferences" not in account_js
            and "notificationPreferencesUpdateEndpoint" in account_js
        ),
        "no_sendmail_call": int("frappe.sendmail" not in module_text),
        "no_email_queue_insert": int("Email Queue" not in module_text),
        "creates_communication": 0,
        "creates_email_queue": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }
