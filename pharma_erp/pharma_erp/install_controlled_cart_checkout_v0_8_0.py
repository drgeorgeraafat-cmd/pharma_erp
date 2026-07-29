from __future__ import annotations

from pathlib import Path

import frappe

REQUIRED_ONLINE_ORDER_FIELDS = (
    "status",
    "source_channel",
    "external_reference",
    "external_created_at",
    "company",
    "order_type",
    "fulfilment_method",
    "customer_name",
    "mobile_no",
    "email_id",
    "customer_resolution_status",
    "address_line1",
    "address_line2",
    "city",
    "state",
    "country",
    "address_phone",
    "formatted_address",
    "delivery_fee",
    "delivery_fee_rule",
    "delivery_instructions",
    "items",
    "currency",
    "products_subtotal",
    "grand_total",
    "prescription_required",
    "prescription_review_status",
    "payment_timing",
    "payment_method",
    "payment_status",
    "placed_at",
)

REQUIRED_ONLINE_ORDER_ITEM_FIELDS = (
    "item_code",
    "item_name_snapshot",
    "requested_qty",
    "approved_qty",
    "uom",
    "listed_rate",
    "approved_rate",
    "net_rate",
    "net_amount",
    "availability_status",
    "stock_review_status",
    "requires_prescription_snapshot",
    "prescription_item_status",
)


def _missing_fields(doctype: str, fieldnames: tuple[str, ...]) -> list[str]:
    meta = frappe.get_meta(doctype)
    return [fieldname for fieldname in fieldnames if not meta.has_field(fieldname)]


def execute() -> dict:
    installed_apps = set(frappe.get_installed_apps())
    required_apps = {"pharma_erp", "webshop"}
    missing_apps = sorted(required_apps - installed_apps)
    if missing_apps:
        frappe.throw(f"Missing required apps: {', '.join(missing_apps)}")

    for doctype in ("Online Order", "Online Order Item", "Website Item"):
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType is missing: {doctype}")

    missing_order_fields = _missing_fields("Online Order", REQUIRED_ONLINE_ORDER_FIELDS)
    missing_item_fields = _missing_fields(
        "Online Order Item", REQUIRED_ONLINE_ORDER_ITEM_FIELDS
    )
    if missing_order_fields or missing_item_fields:
        frappe.throw(
            "Online Order foundation is incomplete. Missing fields: "
            + ", ".join(missing_order_fields + missing_item_fields)
        )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    required_files = (
        app_path / "controlled_cart_checkout.py",
        app_path / "public" / "css" / "controlled_cart_checkout.css",
        app_path / "public" / "js" / "controlled_cart_checkout.js",
        app_path / "www" / "pharmacy-cart" / "index.py",
        app_path / "www" / "pharmacy-cart" / "index.html",
        app_path / "www" / "pharmacy-checkout" / "index.py",
        app_path / "www" / "pharmacy-checkout" / "index.html",
        app_path / "www" / "pharmacy-order-success" / "index.py",
        app_path / "www" / "pharmacy-order-success" / "index.html",
    )
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        frappe.throw("Controlled cart source files are missing: " + ", ".join(missing_files))

    frappe.clear_cache()

    return {
        "status": "ok",
        "step": "3B.3",
        "cart_route": "/pharmacy-cart/",
        "checkout_route": "/pharmacy-checkout/",
        "success_route": "/pharmacy-order-success/",
        "creates_online_order": 1,
        "creates_quotation": 0,
        "creates_sales_order": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
        "verified_online_order_fields": len(REQUIRED_ONLINE_ORDER_FIELDS),
        "verified_online_order_item_fields": len(REQUIRED_ONLINE_ORDER_ITEM_FIELDS),
    }
