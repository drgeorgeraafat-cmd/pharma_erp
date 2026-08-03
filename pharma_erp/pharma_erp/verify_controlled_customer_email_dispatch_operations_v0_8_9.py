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
    sent = frappe.db.count(
        NOTIFICATION_DOCTYPE, {"notification_status": "Sent"}
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
        app_path / "public" / "js"
        / "online_order_customer_notification.js"
    ).read_text(encoding="utf-8")
    settings_js = (
        app_path / "public" / "js"
        / "online_order_notification_delivery_settings.js"
    ).read_text(encoding="utf-8")

    return {
        "status": "ok",
        "step": "4F",
        "delivery_settings_doctype": int(bool(settings_meta)),
        "delivery_attempt_doctype": int(bool(attempt_meta)),
        "delivery_mode": settings.delivery_mode,
        "safe_inactive_state": int(
            settings.delivery_mode == DELIVERY_MODE_PREVIEW
            and not settings.outbound_email_enabled
            and not settings.pilot_mode_enabled
            and not settings.customer_mode_enabled
            and not settings.automatic_customer_dispatch_enabled
            and not settings.allow_actual_customer_recipient
            and settings.activation_status != "Active"
        ),
        "outbound_email_enabled": int(bool(settings.outbound_email_enabled)),
        "pilot_mode_enabled": int(bool(settings.pilot_mode_enabled)),
        "customer_mode_enabled": int(bool(settings.customer_mode_enabled)),
        "automatic_customer_dispatch_enabled": int(
            bool(settings.automatic_customer_dispatch_enabled)
        ),
        "actual_customer_recipient_enabled": int(
            bool(settings.allow_actual_customer_recipient)
        ),
        "customer_dispatch_cutover_established": int(
            bool(settings.customer_dispatch_cutover_at)
        ),
        "customer_dispatch_scope_locked": int(
            settings.customer_dispatch_scope == "Post-Cutover Events Only"
        ),
        "preview_ready": readiness["preview_ready"],
        "activation_ready": readiness["activation_ready"],
        "customer_active": readiness["customer_active"],
        "auto_dispatch_active": readiness["auto_dispatch_active"],
        "protected_legacy_deferred": readiness[
            "protected_legacy_deferred"
        ],
        "eligible_post_cutover": readiness["eligible_post_cutover"],
        "notification_intents": notifications,
        "deferred_intents": deferred,
        "sent_intents": sent,
        "active_outbound_rows": active_outbound,
        "delivery_attempts": frappe.db.count(ATTEMPT_DOCTYPE),
        "attempt_raw_recipient_fields": attempt_raw_fields,
        "attempt_raw_recipient_storage": int(not attempt_raw_fields),
        "dispatch_source_audit_field": int(
            bool(attempt_meta.get_field("dispatch_source"))
        ),
        "recipient_hash_match_required": int(
            bool(settings.require_recipient_hash_match)
        ),
        "pilot_recipient_password_field": int(
            settings_meta.get_field("pilot_recipient_email").fieldtype
            == "Password"
        ),
        "customer_cutover_field_installed": int(
            bool(settings_meta.get_field("customer_dispatch_cutover_at"))
        ),
        "customer_daily_limit_field_installed": int(
            bool(settings_meta.get_field("daily_customer_dispatch_limit"))
        ),
        "scheduler_reconciliation_installed": int(
            "reconcile_pending_dispatches" in hooks_text
            and "*/5 * * * *" in hooks_text
        ),
        "scheduler_customer_dispatch_installed": int(
            "dispatch_eligible_customer_notifications" in hooks_text
            and "*/5 * * * *" in hooks_text
        ),
        "explicit_customer_activation_phrase": int(
            "ACTIVATE STEP 4F CUSTOMER" in delivery_text
        ),
        "explicit_customer_deactivation_phrase": int(
            "DEACTIVATE STEP 4F CUSTOMER" in delivery_text
        ),
        "explicit_customer_dispatch_phrase": int(
            "QUEUE STEP 4F CUSTOMER" in delivery_text
        ),
        "explicit_auto_enable_phrase": int(
            "ENABLE STEP 4F AUTO" in delivery_text
        ),
        "explicit_auto_disable_phrase": int(
            "DISABLE STEP 4F AUTO" in delivery_text
        ),
        "single_customer_queue_api_installed": int(
            "queue_customer_notification" in delivery_text
            and "Pharma-Step4F-Customer" in delivery_text
            and "frappe.sendmail" in delivery_text
        ),
        "post_cutover_guard_installed": int(
            "This legacy intent is protected by the Step 4F cutover."
            in delivery_text
        ),
        "order_ownership_guard_installed": int(
            "The Website User does not own the Online Order."
            in delivery_text
        ),
        "preference_guard_installed": int(
            "The customer has disabled email order updates."
            in delivery_text
        ),
        "retry_limit_guard_installed": int(
            "The retry delay has not elapsed yet." in delivery_text
            and "The maximum dispatch attempts have been reached."
            in delivery_text
        ),
        "automatic_dispatch_safe_gate": int(
            "automatic_customer_dispatch_inactive" in delivery_text
            and "auto_dispatch_active" in delivery_text
        ),
        "outbox_customer_controls_installed": int(
            "Queue Customer Email" in outbox_js
            and "Check Customer Eligibility" in outbox_js
            and "Refresh Dispatch Status" in outbox_js
        ),
        "settings_customer_controls_installed": int(
            "Activate Controlled Customer" in settings_js
            and "Deactivate Controlled Customer" in settings_js
            and "Enable Automatic Dispatch" in settings_js
            and "Disable Automatic Dispatch" in settings_js
        ),
        "email_queues_created_by_install": 0,
        "communications_created_by_install": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }
