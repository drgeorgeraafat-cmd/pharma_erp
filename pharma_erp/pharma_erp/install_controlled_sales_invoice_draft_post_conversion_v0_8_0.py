
from __future__ import annotations

from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
    "Online Order": [
        {
            "fieldname": "custom_conversion_execution_status",
            "label": "Controlled Conversion Execution",
            "fieldtype": "Select",
            "options": "Pending\nDraft Created\nBlocked",
            "default": "Pending",
            "insert_after": "custom_conversion_readiness_checked_at",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_conversion_execution_notes",
            "label": "Controlled Conversion Execution Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_conversion_execution_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_conversion_executed_by",
            "label": "Controlled Conversion Executed By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_conversion_execution_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_conversion_executed_at",
            "label": "Controlled Conversion Executed At",
            "fieldtype": "Datetime",
            "insert_after": "custom_conversion_executed_by",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_post_conversion_integrity_status",
            "label": "Post-Conversion Integrity",
            "fieldtype": "Select",
            "options": "Pending\nReady\nBlocked",
            "default": "Pending",
            "insert_after": "custom_conversion_executed_at",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_post_conversion_integrity_notes",
            "label": "Post-Conversion Integrity Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_post_conversion_integrity_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_post_conversion_checked_by",
            "label": "Post-Conversion Integrity Checked By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_post_conversion_integrity_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_post_conversion_checked_at",
            "label": "Post-Conversion Integrity Checked At",
            "fieldtype": "Datetime",
            "insert_after": "custom_post_conversion_checked_by",
            "read_only": 1,
            "no_copy": 1,
        },
    ]
}

REQUIRED_STEP3B6_FIELDS = (
    "custom_payment_selection_status",
    "custom_order_confirmation_readiness_status",
    "custom_conversion_readiness_status",
    "custom_conversion_readiness_checked_by",
    "custom_conversion_readiness_checked_at",
)

REQUIRED_STANDARD_FIELDS = (
    "status",
    "customer",
    "customer_address",
    "warehouse",
    "delivery_zone",
    "grand_total",
    "payment_timing",
    "payment_method",
    "payment_status",
    "confirmed_at",
    "conversion_path",
    "sales_order",
    "sales_invoice",
    "converted_by",
    "converted_at",
    "items",
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
        "Online Order Item",
        "Sales Invoice",
        "Sales Invoice Item",
        "GL Entry",
        "Stock Ledger Entry",
    ):
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType is missing: {doctype}")

    missing_standard = _missing_fields("Online Order", REQUIRED_STANDARD_FIELDS)
    if missing_standard:
        frappe.throw(
            "Online Order conversion foundation is incomplete. Missing fields: "
            + ", ".join(missing_standard)
        )

    missing_step3b6 = _missing_fields("Online Order", REQUIRED_STEP3B6_FIELDS)
    if missing_step3b6:
        frappe.throw(
            "Step 3B.6 must be installed first. Missing fields: "
            + ", ".join(missing_step3b6)
        )

    sales_invoice_meta = frappe.get_meta("Sales Invoice")
    for fieldname in ("custom_online_order", "custom_order_type"):
        if not sales_invoice_meta.has_field(fieldname):
            frappe.throw(f"Required Sales Invoice field is missing: {fieldname}")

    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Online Order")

    missing_custom = _missing_fields("Online Order", REQUIRED_CUSTOM_FIELDS)
    if missing_custom:
        frappe.throw(
            "Step 3B.7 custom fields were not installed: "
            + ", ".join(missing_custom)
        )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    required_files = (
        app_path / "controlled_online_order_confirmation.py",
        app_path / "controlled_online_order_review.py",
        app_path / "online_order_sales_invoice_events.py",
        app_path
        / "pharma_erp"
        / "page"
        / "controlled_online_order_review"
        / "controlled_online_order_review.js",
        app_path
        / "pharma_erp"
        / "doctype"
        / "online_order"
        / "online_order.py",
    )
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        frappe.throw("Step 3B.7 source files are missing: " + ", ".join(missing_files))

    for fields in (
        ["custom_conversion_execution_status"],
        ["custom_post_conversion_integrity_status"],
    ):
        try:
            frappe.db.add_index("Online Order", fields)
        except Exception:
            pass

    frappe.clear_cache()
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "3B.7",
        "desk_route": "/app/controlled-online-order-review",
        "draft_context_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "get_sales_invoice_draft_context"
        ),
        "draft_creation_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "create_controlled_sales_invoice_draft"
        ),
        "post_conversion_integrity_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "verify_post_conversion_integrity"
        ),
        "creates_sales_invoice_draft": 1,
        "submits_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "duplicate_active_invoice_allowed": 0,
        "requires_post_conversion_integrity_before_submit": 1,
        "core_changes": 0,
        "installed_custom_fields": len(REQUIRED_CUSTOM_FIELDS),
    }
