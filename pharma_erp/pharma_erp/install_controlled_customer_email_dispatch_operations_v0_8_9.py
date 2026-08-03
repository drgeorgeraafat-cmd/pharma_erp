from __future__ import annotations

import frappe

from pharma_erp.customer_notification_delivery import (
    ATTEMPT_DOCTYPE,
    DELIVERY_MODE_PREVIEW,
    SETTINGS_DOCTYPE,
    bootstrap_delivery_settings,
    get_settings,
)
from pharma_erp.customer_order_notifications import NOTIFICATION_DOCTYPE


def run() -> dict:
    required = (
        NOTIFICATION_DOCTYPE,
        SETTINGS_DOCTYPE,
        ATTEMPT_DOCTYPE,
        "Online Order",
        "User",
        "Email Queue",
        "Email Account",
    )
    missing = [
        doctype
        for doctype in required
        if not frappe.db.exists("DocType", doctype)
    ]
    if missing:
        frappe.throw(
            "Step 4F required DocTypes are missing after migrate: "
            + ", ".join(missing)
        )

    bootstrap_delivery_settings()
    settings = get_settings()
    settings.delivery_mode = DELIVERY_MODE_PREVIEW
    settings.outbound_email_enabled = 0
    settings.activation_status = "Inactive"
    settings.pilot_mode_enabled = 0
    settings.customer_mode_enabled = 0
    settings.automatic_customer_dispatch_enabled = 0
    settings.allow_actual_customer_recipient = 0
    settings.customer_dispatch_scope = "Post-Cutover Events Only"
    settings.daily_customer_dispatch_limit = max(
        1, int(settings.daily_customer_dispatch_limit or 20)
    )
    settings.last_readiness_status = "Not Checked"
    settings.readiness_details = (
        "Step 4F installed in safe inactive mode. No customer dispatch cutover "
        "has been established. Existing Deferred intents remain protected."
    )
    settings.activation_note = (
        "Step 4F is installed in Preview Only mode. Controlled Customer and "
        "automatic dispatch require separate explicit System Manager actions."
    )
    settings.flags.ignore_permissions = True
    settings.flags.step4e_controlled_update = True
    settings.flags.step4f_controlled_update = True
    settings.save()
    frappe.db.commit()

    deferred = frappe.db.count(
        NOTIFICATION_DOCTYPE, {"notification_status": "Deferred"}
    )
    sent = frappe.db.count(
        NOTIFICATION_DOCTYPE, {"notification_status": "Sent"}
    )

    return {
        "status": "ok",
        "step": "4F",
        "delivery_settings_doctype": 1,
        "delivery_attempt_doctype": 1,
        "delivery_mode": settings.delivery_mode,
        "outbound_email_enabled": int(settings.outbound_email_enabled or 0),
        "customer_mode_enabled": int(settings.customer_mode_enabled or 0),
        "automatic_customer_dispatch_enabled": int(
            settings.automatic_customer_dispatch_enabled or 0
        ),
        "actual_customer_recipient_enabled": int(
            settings.allow_actual_customer_recipient or 0
        ),
        "customer_dispatch_cutover_established": int(
            bool(settings.customer_dispatch_cutover_at)
        ),
        "protected_existing_deferred": deferred,
        "sent_intents_preserved": sent,
        "notification_intents": frappe.db.count(NOTIFICATION_DOCTYPE),
        "delivery_attempts": frappe.db.count(ATTEMPT_DOCTYPE),
        "email_queues_created_by_install": 0,
        "communications_created_by_install": 0,
        "customer_activation_required": 1,
        "automatic_dispatch_activation_required": 1,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }
