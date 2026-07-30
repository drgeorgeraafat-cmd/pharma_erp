from __future__ import annotations

from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
    "Online Order": [
        {
            "fieldname": "custom_submit_readiness_status",
            "label": "Sales Invoice Submit Readiness",
            "fieldtype": "Select",
            "options": "Pending\nReady\nBlocked",
            "default": "Pending",
            "insert_after": "custom_post_conversion_checked_at",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_submit_readiness_notes",
            "label": "Sales Invoice Submit Readiness Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_submit_readiness_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_submit_readiness_checked_by",
            "label": "Sales Invoice Submit Readiness Checked By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_submit_readiness_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_submit_readiness_checked_at",
            "label": "Sales Invoice Submit Readiness Checked At",
            "fieldtype": "Datetime",
            "insert_after": "custom_submit_readiness_checked_by",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_submit_execution_status",
            "label": "Controlled Sales Invoice Submit",
            "fieldtype": "Select",
            "options": "Pending\nSubmitted\nBlocked",
            "default": "Pending",
            "insert_after": "custom_submit_readiness_checked_at",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_submit_execution_notes",
            "label": "Controlled Sales Invoice Submit Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_submit_execution_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_submitted_by",
            "label": "Controlled Sales Invoice Submitted By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_submit_execution_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_submitted_at",
            "label": "Controlled Sales Invoice Submitted At",
            "fieldtype": "Datetime",
            "insert_after": "custom_submitted_by",
            "read_only": 1,
            "no_copy": 1,
        },
    ]
}

REQUIRED_STEP3B7_FIELDS = (
    "custom_conversion_execution_status",
    "custom_post_conversion_integrity_status",
    "custom_post_conversion_checked_by",
    "custom_post_conversion_checked_at",
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
        "GL Entry",
        "Stock Ledger Entry",
        "Payment Entry",
        "Pharmacy Shift Closing",
    ):
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType is missing: {doctype}")

    missing_step3b7 = _missing_fields("Online Order", REQUIRED_STEP3B7_FIELDS)
    if missing_step3b7:
        frappe.throw(
            "Step 3B.7 must be installed first. Missing fields: "
            + ", ".join(missing_step3b7)
        )

    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Online Order")

    missing_custom = _missing_fields("Online Order", REQUIRED_CUSTOM_FIELDS)
    if missing_custom:
        frappe.throw(
            "Step 3B.8 custom fields were not installed: "
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
        frappe.throw("Step 3B.8 source files are missing: " + ", ".join(missing_files))

    for fields in (
        ["custom_submit_readiness_status"],
        ["custom_submit_execution_status"],
    ):
        try:
            frappe.db.add_index("Online Order", fields)
        except Exception:
            pass

    frappe.clear_cache()
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "3B.8",
        "desk_route": "/app/controlled-online-order-review",
        "submit_context_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "get_sales_invoice_submit_context"
        ),
        "submit_readiness_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "verify_sales_invoice_submit_readiness"
        ),
        "controlled_submit_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "submit_controlled_sales_invoice"
        ),
        "submits_sales_invoice": 1,
        "creates_payment_entry": 0,
        "creates_gl_entries": 1,
        "creates_stock_entries": 0,
        "requires_open_shift_for_home_delivery": 1,
        "requires_post_conversion_integrity": 1,
        "stale_readiness_reset_on_draft_edit": 1,
        "idempotent_submit_replay": 1,
        "core_changes": 0,
        "installed_custom_fields": len(REQUIRED_CUSTOM_FIELDS),
    }
