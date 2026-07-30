from __future__ import annotations

from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
    "Online Order": [
        {
            "fieldname": "custom_delivery_sync_status",
            "label": "Controlled Delivery Synchronization",
            "fieldtype": "Select",
            "options": "Pending\nSynchronized\nBlocked",
            "default": "Pending",
            "insert_after": "custom_submitted_at",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_delivery_sync_notes",
            "label": "Controlled Delivery Synchronization Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_delivery_sync_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_delivery_synced_by",
            "label": "Controlled Delivery Synchronized By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_delivery_sync_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_delivery_synced_at",
            "label": "Controlled Delivery Synchronized At",
            "fieldtype": "Datetime",
            "insert_after": "custom_delivery_synced_by",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_delivery_completion_readiness_status",
            "label": "Delivery Completion Readiness",
            "fieldtype": "Select",
            "options": "Pending\nReady\nBlocked",
            "default": "Pending",
            "insert_after": "custom_delivery_synced_at",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_delivery_completion_readiness_notes",
            "label": "Delivery Completion Readiness Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_delivery_completion_readiness_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_delivery_completion_checked_by",
            "label": "Delivery Completion Readiness Checked By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_delivery_completion_readiness_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_delivery_completion_checked_at",
            "label": "Delivery Completion Readiness Checked At",
            "fieldtype": "Datetime",
            "insert_after": "custom_delivery_completion_checked_by",
            "read_only": 1,
            "no_copy": 1,
        },
    ]
}

REQUIRED_STEP3B8_FIELDS = (
    "custom_submit_readiness_status",
    "custom_submit_execution_status",
    "custom_submitted_by",
    "custom_submitted_at",
)

REQUIRED_ONLINE_ORDER_DELIVERY_FIELDS = (
    "delivery_status_snapshot",
    "delivery_boy",
    "delivery_trip",
    "delivery_attempt",
    "delivery_departure_at",
    "delivery_delivered_at",
    "delivery_completed_by",
    "delivery_completed_at",
    "delivery_completion_notes",
)

REQUIRED_SALES_INVOICE_FIELDS = (
    "custom_online_order",
    "custom_delivery_status",
    "custom_collection_verification_status",
    "custom_confirmed_customer_payment_method",
    "custom_collection_payment_entry",
    "custom_pharmacy_shift",
    "custom_delivery_shift",
)

REQUIRED_CUSTOM_FIELDS = tuple(
    field["fieldname"] for field in CUSTOM_FIELDS["Online Order"]
)


def _missing_fields(doctype: str, fieldnames: tuple[str, ...]) -> list[str]:
    meta = frappe.get_meta(doctype)
    return [fieldname for fieldname in fieldnames if not meta.has_field(fieldname)]


def execute() -> dict:
    if "pharma_erp" not in set(frappe.get_installed_apps()):
        frappe.throw("pharma_erp is not installed on this site.")

    for doctype in (
        "Online Order",
        "Sales Invoice",
        "Payment Entry",
        "GL Entry",
        "Stock Ledger Entry",
        "Pharmacy Shift Closing",
    ):
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType is missing: {doctype}")

    missing_step3b8 = _missing_fields("Online Order", REQUIRED_STEP3B8_FIELDS)
    if missing_step3b8:
        frappe.throw(
            "Step 3B.8 must be installed first. Missing fields: "
            + ", ".join(missing_step3b8)
        )

    missing_order_delivery = _missing_fields(
        "Online Order",
        REQUIRED_ONLINE_ORDER_DELIVERY_FIELDS,
    )
    if missing_order_delivery:
        frappe.throw(
            "Online Order delivery foundation is incomplete. Missing fields: "
            + ", ".join(missing_order_delivery)
        )

    missing_invoice = _missing_fields("Sales Invoice", REQUIRED_SALES_INVOICE_FIELDS)
    if missing_invoice:
        frappe.throw(
            "Sales Invoice delivery integration is incomplete. Missing fields: "
            + ", ".join(missing_invoice)
        )

    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Online Order")

    missing_custom = _missing_fields("Online Order", REQUIRED_CUSTOM_FIELDS)
    if missing_custom:
        frappe.throw(
            "Step 3B.9 custom fields were not installed: "
            + ", ".join(missing_custom)
        )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    required_files = (
        app_path / "controlled_online_order_confirmation.py",
        app_path / "controlled_online_order_review.py",
        app_path / "online_order_sales_invoice_events.py",
        app_path / "pharma_erp" / "page" / "controlled_online_order_review" / "controlled_online_order_review.js",
    )
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        frappe.throw("Step 3B.9 source files are missing: " + ", ".join(missing_files))

    for fields in (
        ["custom_delivery_sync_status"],
        ["custom_delivery_completion_readiness_status"],
    ):
        try:
            frappe.db.add_index("Online Order", fields)
        except Exception:
            pass

    frappe.clear_cache()
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "3B.9",
        "desk_route": "/app/controlled-online-order-review",
        "delivery_context_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "get_delivery_execution_context"
        ),
        "delivery_sync_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "sync_controlled_delivery_execution"
        ),
        "completion_readiness_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "verify_delivery_completion_readiness"
        ),
        "completion_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "complete_controlled_home_delivery"
        ),
        "uses_existing_delivery_management": 1,
        "requires_submitted_sales_invoice": 1,
        "requires_delivered_invoice": 1,
        "requires_collection_ready": 1,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "idempotent_sync_replay": 1,
        "idempotent_completion_replay": 1,
        "core_changes": 0,
        "installed_custom_fields": len(REQUIRED_CUSTOM_FIELDS),
    }
