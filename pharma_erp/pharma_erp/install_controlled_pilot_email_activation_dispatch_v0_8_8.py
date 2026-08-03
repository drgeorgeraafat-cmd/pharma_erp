
from __future__ import annotations

import frappe

from pharma_erp.customer_notification_delivery import (
    ATTEMPT_DOCTYPE,
    SETTINGS_DOCTYPE,
    bootstrap_delivery_settings,
)
from pharma_erp.customer_order_notifications import NOTIFICATION_DOCTYPE


def run() -> dict:
    required = (
        NOTIFICATION_DOCTYPE,
        SETTINGS_DOCTYPE,
        ATTEMPT_DOCTYPE,
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
            "Step 4E required DocTypes are missing after migrate: "
            + ", ".join(missing)
        )

    settings = bootstrap_delivery_settings()
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "4E",
        "delivery_settings_doctype": 1,
        "delivery_attempt_doctype": 1,
        "settings": settings,
        "notification_intents": frappe.db.count(NOTIFICATION_DOCTYPE),
        "delivery_attempts": frappe.db.count(ATTEMPT_DOCTYPE),
        "email_queues_created": 0,
        "communications_created": 0,
        "automatic_bulk_dispatch_enabled": 0,
        "actual_customer_recipient_enabled": 0,
        "pilot_activation_required": 1,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }
