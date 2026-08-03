from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from pharma_erp.customer_order_status_timeline import bootstrap_existing_orders


def run() -> dict:
    if not frappe.db.exists("DocType", "Online Order"):
        frappe.throw("Online Order DocType is required before Step 4B installation.")

    create_custom_fields(
        {
            "Online Order": [
                {
                    "fieldname": "custom_customer_status_key",
                    "label": "Customer Status Key",
                    "fieldtype": "Data",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "hidden": 1,
                    "insert_after": "custom_tracking_last_rotated_by",
                },
                {
                    "fieldname": "custom_customer_status_updated_at",
                    "label": "Customer Status Updated At",
                    "fieldtype": "Datetime",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "hidden": 1,
                    "insert_after": "custom_customer_status_key",
                },
                {
                    "fieldname": "custom_customer_status_events",
                    "label": "Customer Status Events",
                    "fieldtype": "Table",
                    "options": "Online Order Customer Status Event",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "hidden": 1,
                    "insert_after": "custom_customer_status_updated_at",
                },
            ]
        },
        update=True,
    )
    frappe.clear_cache(doctype="Online Order")
    bootstrap = bootstrap_existing_orders()
    frappe.db.commit()
    return {
        "status": "ok",
        "step": "4B",
        "customer_status_key_field": 1,
        "customer_status_updated_at_field": 1,
        "customer_status_events_field": 1,
        "event_doctype": int(
            bool(frappe.db.exists("DocType", "Online Order Customer Status Event"))
        ),
        "bootstrap": bootstrap,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "notifications_enabled": 0,
        "core_changes": 0,
    }
