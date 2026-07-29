from __future__ import annotations

from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
    "Online Order": [
        {
            "fieldname": "custom_website_user",
            "label": "Website User",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "customer_resolution_status",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_customer_resolution_method",
            "label": "Customer Resolution Method",
            "fieldtype": "Select",
            "options": "\nWebsite User\nMobile\nEmail\nManual Confirmation",
            "insert_after": "custom_website_user",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_customer_resolution_notes",
            "label": "Customer Resolution Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_customer_resolution_method",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_customer_resolved_by",
            "label": "Customer Resolved By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_customer_resolution_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_customer_resolved_at",
            "label": "Customer Resolved At",
            "fieldtype": "Datetime",
            "insert_after": "custom_customer_resolved_by",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_final_confirmation_readiness_status",
            "label": "Final Confirmation Readiness",
            "fieldtype": "Select",
            "options": "Pending\nReady\nBlocked",
            "default": "Pending",
            "insert_after": "confirmed_at",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_final_confirmation_checked_by",
            "label": "Final Readiness Checked By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_final_confirmation_readiness_status",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_final_confirmation_checked_at",
            "label": "Final Readiness Checked At",
            "fieldtype": "Datetime",
            "insert_after": "custom_final_confirmation_checked_by",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_final_confirmation_notes",
            "label": "Final Readiness Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_final_confirmation_checked_at",
            "read_only": 1,
            "no_copy": 1,
        },
    ]
}


REQUIRED_STANDARD_FIELDS = (
    "customer",
    "customer_name",
    "mobile_no",
    "email_id",
    "customer_resolution_status",
    "customer_address",
    "address_line1",
    "city",
    "delivery_zone",
    "warehouse",
    "delivery_fee",
    "delivery_fee_rule",
    "estimated_delivery_time_mins",
    "products_subtotal",
    "grand_total",
    "items",
)

REQUIRED_CUSTOM_FIELDS = tuple(
    field["fieldname"] for field in CUSTOM_FIELDS["Online Order"]
)


def _missing_fields(doctype: str, fieldnames: tuple[str, ...]) -> list[str]:
    meta = frappe.get_meta(doctype)
    return [fieldname for fieldname in fieldnames if not meta.has_field(fieldname)]


def execute() -> dict:
    installed_apps = set(frappe.get_installed_apps())
    if "pharma_erp" not in installed_apps:
        frappe.throw("pharma_erp is not installed on this site.")

    for doctype in (
        "Online Order",
        "Online Order Item",
        "Customer",
        "Address",
        "Contact",
        "Dynamic Link",
        "Delivery Zone",
        "Warehouse",
    ):
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType is missing: {doctype}")

    missing_standard = _missing_fields("Online Order", REQUIRED_STANDARD_FIELDS)
    if missing_standard:
        frappe.throw(
            "Online Order customer and delivery foundation is incomplete. Missing fields: "
            + ", ".join(missing_standard)
        )

    address_meta = frappe.get_meta("Address")
    if not address_meta.has_field("custom_delivery_zone"):
        frappe.throw("Address.custom_delivery_zone is required for saved delivery addresses.")

    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Online Order")
    frappe.clear_cache(doctype="Customer")
    frappe.clear_cache(doctype="Address")

    missing_custom = _missing_fields("Online Order", REQUIRED_CUSTOM_FIELDS)
    if missing_custom:
        frappe.throw(
            "Step 3B.5 custom fields were not installed: " + ", ".join(missing_custom)
        )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    required_files = (
        app_path / "controlled_cart_checkout.py",
        app_path / "controlled_online_order_review.py",
        app_path / "public" / "js" / "controlled_cart_checkout.js",
        app_path / "www" / "pharmacy-checkout" / "index.html",
        app_path
        / "pharma_erp"
        / "page"
        / "controlled_online_order_review"
        / "controlled_online_order_review.js",
    )
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        frappe.throw("Step 3B.5 source files are missing: " + ", ".join(missing_files))

    try:
        frappe.db.add_index("Online Order", ["custom_website_user"])
    except Exception:
        pass

    frappe.clear_cache()
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "3B.5",
        "desk_route": "/app/controlled-online-order-review",
        "checkout_route": "/pharmacy-checkout/",
        "checkout_identity_api": "pharma_erp.controlled_cart_checkout.get_checkout_identity",
        "customer_context_api": (
            "pharma_erp.controlled_online_order_review.get_customer_resolution_context"
        ),
        "customer_resolution_api": (
            "pharma_erp.controlled_online_order_review.apply_customer_resolution"
        ),
        "delivery_zone_context_api": (
            "pharma_erp.controlled_online_order_review.get_delivery_zone_context"
        ),
        "delivery_zone_api": (
            "pharma_erp.controlled_online_order_review.apply_delivery_zone"
        ),
        "final_readiness_api": (
            "pharma_erp.controlled_online_order_review.verify_final_confirmation_readiness"
        ),
        "uses_standard_customer_portal_users": 1,
        "uses_standard_customer_addresses": 1,
        "ambiguous_match_auto_link": 0,
        "creates_customer": 0,
        "creates_address": 0,
        "creates_quotation": 0,
        "creates_sales_order": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
        "installed_custom_fields": len(REQUIRED_CUSTOM_FIELDS),
    }
