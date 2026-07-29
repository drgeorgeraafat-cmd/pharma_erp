from __future__ import annotations

from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
    "Online Order": [
        {
            "fieldname": "custom_payment_selection_status",
            "label": "Controlled Payment Selection",
            "fieldtype": "Select",
            "options": "Pending\nReady\nAwaiting Verification\nBlocked",
            "default": "Pending",
            "insert_after": "payment_status",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_payment_selection_notes",
            "label": "Controlled Payment Selection Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_payment_selection_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_payment_selected_by",
            "label": "Controlled Payment Selected By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_payment_selection_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_payment_selected_at",
            "label": "Controlled Payment Selected At",
            "fieldtype": "Datetime",
            "insert_after": "custom_payment_selected_by",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_order_confirmation_readiness_status",
            "label": "Order Confirmation Readiness",
            "fieldtype": "Select",
            "options": "Pending\nReady\nBlocked",
            "default": "Pending",
            "insert_after": "custom_final_confirmation_notes",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_order_confirmation_notes",
            "label": "Order Confirmation Readiness Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_order_confirmation_readiness_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_order_confirmation_checked_by",
            "label": "Order Confirmation Checked By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_order_confirmation_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_order_confirmation_checked_at",
            "label": "Order Confirmation Checked At",
            "fieldtype": "Datetime",
            "insert_after": "custom_order_confirmation_checked_by",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_conversion_readiness_status",
            "label": "Sales Invoice Conversion Readiness",
            "fieldtype": "Select",
            "options": "Pending\nReady\nBlocked",
            "default": "Pending",
            "insert_after": "converted_at",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_conversion_readiness_notes",
            "label": "Sales Invoice Conversion Readiness Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_conversion_readiness_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_conversion_readiness_checked_by",
            "label": "Sales Invoice Conversion Checked By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_conversion_readiness_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_conversion_readiness_checked_at",
            "label": "Sales Invoice Conversion Checked At",
            "fieldtype": "Datetime",
            "insert_after": "custom_conversion_readiness_checked_by",
            "read_only": 1,
            "no_copy": 1,
        },
    ]
}

REQUIRED_STANDARD_FIELDS = (
    "status",
    "fulfilment_method",
    "customer",
    "customer_resolution_status",
    "customer_address",
    "delivery_zone",
    "warehouse",
    "delivery_fee",
    "grand_total",
    "payment_timing",
    "payment_method",
    "mode_of_payment",
    "payment_status",
    "declared_paid_amount",
    "verified_paid_amount",
    "transaction_reference",
    "payment_proof",
    "payment_review_notes",
    "payment_verified_by",
    "payment_verified_at",
    "payment_entry",
    "confirmed_at",
    "conversion_path",
    "sales_order",
    "sales_invoice",
    "converted_by",
    "converted_at",
    "items",
)

REQUIRED_STEP3B5_FIELDS = (
    "custom_website_user",
    "custom_customer_resolution_method",
    "custom_final_confirmation_readiness_status",
    "custom_final_confirmation_checked_by",
    "custom_final_confirmation_checked_at",
    "custom_final_confirmation_notes",
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
        "Customer",
        "Mode of Payment",
        "Payment Entry",
        "Sales Invoice",
        "Pharmacy POS Settings",
    ):
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType is missing: {doctype}")

    missing_standard = _missing_fields("Online Order", REQUIRED_STANDARD_FIELDS)
    if missing_standard:
        frappe.throw(
            "Online Order payment and conversion foundation is incomplete. Missing fields: "
            + ", ".join(missing_standard)
        )

    missing_step3b5 = _missing_fields("Online Order", REQUIRED_STEP3B5_FIELDS)
    if missing_step3b5:
        frappe.throw(
            "Step 3B.5 must be installed first. Missing fields: "
            + ", ".join(missing_step3b5)
        )

    for mode in ("Cash", "Insta Pay", "Wallet"):
        if not frappe.db.exists("Mode of Payment", {"name": mode, "enabled": 1}):
            frappe.throw(f"Required enabled Mode of Payment is missing: {mode}")

    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Online Order")

    missing_custom = _missing_fields("Online Order", REQUIRED_CUSTOM_FIELDS)
    if missing_custom:
        frappe.throw(
            "Step 3B.6 custom fields were not installed: " + ", ".join(missing_custom)
        )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    required_files = (
        app_path / "controlled_cart_checkout.py",
        app_path / "controlled_online_order_review.py",
        app_path / "controlled_online_order_confirmation.py",
        app_path / "public" / "js" / "controlled_cart_checkout.js",
        app_path / "public" / "css" / "controlled_cart_checkout.css",
        app_path / "www" / "pharmacy-checkout" / "index.html",
        app_path
        / "pharma_erp"
        / "page"
        / "controlled_online_order_review"
        / "controlled_online_order_review.js",
    )
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        frappe.throw("Step 3B.6 source files are missing: " + ", ".join(missing_files))

    for fields in (
        ["custom_payment_selection_status"],
        ["custom_order_confirmation_readiness_status"],
        ["custom_conversion_readiness_status"],
    ):
        try:
            frappe.db.add_index("Online Order", fields)
        except Exception:
            pass

    frappe.clear_cache()
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "3B.6",
        "desk_route": "/app/controlled-online-order-review",
        "checkout_route": "/pharmacy-checkout/",
        "public_payment_options_api": (
            "pharma_erp.controlled_online_order_confirmation.get_public_payment_options"
        ),
        "payment_context_api": (
            "pharma_erp.controlled_online_order_confirmation.get_payment_selection_context"
        ),
        "payment_selection_api": (
            "pharma_erp.controlled_online_order_confirmation.apply_payment_selection"
        ),
        "confirmation_readiness_api": (
            "pharma_erp.controlled_online_order_confirmation."
            "verify_order_confirmation_readiness"
        ),
        "confirm_order_api": (
            "pharma_erp.controlled_online_order_confirmation.confirm_online_order"
        ),
        "conversion_readiness_api": (
            "pharma_erp.controlled_online_order_confirmation.verify_conversion_readiness"
        ),
        "sales_invoice_draft_api": (
            "pharma_erp.pharma_erp.doctype.online_order.online_order."
            "create_sales_invoice_draft"
        ),
        "home_delivery_public_payment_options": ["Cash on Delivery"],
        "pickup_public_payment_options": [
            "Cash at Pharmacy",
            "InstaPay",
            "Mobile Wallet",
        ],
        "prepaid_confirmation_requires_submitted_payment_entry": 1,
        "creates_quotation": 0,
        "creates_sales_order": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
        "installed_custom_fields": len(REQUIRED_CUSTOM_FIELDS),
    }
