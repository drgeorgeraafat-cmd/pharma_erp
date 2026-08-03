
from __future__ import annotations

import frappe

from pharma_erp.customer_order_notifications import (
    NOTIFICATION_DOCTYPE,
    OUTBOUND_DELIVERY_ENABLED,
    PREFERENCE_DOCTYPE,
    STATUS_EVENT_DOCTYPE,
    bootstrap_existing_notification_intents,
    bootstrap_notification_preferences,
)


def run() -> dict:
    required = ("Online Order", STATUS_EVENT_DOCTYPE, PREFERENCE_DOCTYPE, NOTIFICATION_DOCTYPE)
    missing = [doctype for doctype in required if not frappe.db.exists("DocType", doctype)]
    if missing:
        frappe.throw(
            "Step 4C required DocTypes are missing after migrate: " + ", ".join(missing)
        )

    preference_bootstrap = bootstrap_notification_preferences()
    notification_bootstrap = bootstrap_existing_notification_intents()
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "4C",
        "preference_doctype": 1,
        "notification_outbox_doctype": 1,
        "preference_bootstrap": preference_bootstrap,
        "notification_bootstrap": notification_bootstrap,
        "outbound_delivery_enabled": int(OUTBOUND_DELIVERY_ENABLED),
        "email_delivery_enabled": 0,
        "whatsapp_delivery_enabled": 0,
        "sms_delivery_enabled": 0,
        "stores_raw_recipient": 0,
        "creates_communication": 0,
        "creates_email_queue": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }
