from __future__ import annotations

from pathlib import Path

import frappe


REQUIRED_ONLINE_ORDER_FIELDS = (
    "status",
    "source_channel",
    "customer",
    "customer_name",
    "mobile_no",
    "customer_resolution_status",
    "fulfilment_method",
    "delivery_zone",
    "warehouse",
    "grand_total",
    "prescription_required",
    "prescription_attachment",
    "prescription_review_status",
    "prescription_review_notes",
    "prescription_reviewed_by",
    "prescription_reviewed_at",
    "payment_timing",
    "payment_status",
    "items",
)

REQUIRED_ONLINE_ORDER_ITEM_FIELDS = (
    "item_code",
    "requested_qty",
    "approved_qty",
    "warehouse",
    "availability_status",
    "stock_review_status",
    "alternative_item",
    "alternative_accepted",
    "requires_prescription_snapshot",
    "prescription_item_status",
    "prescription_item_notes",
)


def _missing_fields(doctype: str, fieldnames: tuple[str, ...]) -> list[str]:
    meta = frappe.get_meta(doctype)
    return [fieldname for fieldname in fieldnames if not meta.has_field(fieldname)]


def execute() -> dict:
    installed_apps = set(frappe.get_installed_apps())
    if "pharma_erp" not in installed_apps:
        frappe.throw("pharma_erp is not installed on this site.")

    for doctype in ("Online Order", "Online Order Item", "Warehouse", "Bin"):
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType is missing: {doctype}")

    missing_order_fields = _missing_fields("Online Order", REQUIRED_ONLINE_ORDER_FIELDS)
    missing_item_fields = _missing_fields(
        "Online Order Item", REQUIRED_ONLINE_ORDER_ITEM_FIELDS
    )
    if missing_order_fields or missing_item_fields:
        frappe.throw(
            "Online Order review foundation is incomplete. Missing fields: "
            + ", ".join(missing_order_fields + missing_item_fields)
        )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    required_files = (
        app_path / "controlled_online_order_review.py",
        app_path
        / "pharma_erp"
        / "page"
        / "controlled_online_order_review"
        / "controlled_online_order_review.json",
        app_path
        / "pharma_erp"
        / "page"
        / "controlled_online_order_review"
        / "controlled_online_order_review.js",
    )
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        frappe.throw(
            "Controlled Online Order review source files are missing: "
            + ", ".join(missing_files)
        )

    frappe.reload_doc(
        "pharma_erp",
        "page",
        "controlled_online_order_review",
        force=True,
    )
    frappe.clear_cache()

    if not frappe.db.exists("Page", "controlled-online-order-review"):
        frappe.throw("Controlled Online Order Review page was not installed.")

    return {
        "status": "ok",
        "step": "3B.4",
        "desk_route": "/app/controlled-online-order-review",
        "queue_api": "pharma_erp.controlled_online_order_review.get_review_queue",
        "snapshot_api": "pharma_erp.controlled_online_order_review.get_review_snapshot",
        "start_review_api": "pharma_erp.controlled_online_order_review.start_review",
        "prescription_review_api": (
            "pharma_erp.controlled_online_order_review.apply_prescription_review"
        ),
        "stock_review_api": "pharma_erp.controlled_online_order_review.apply_stock_review",
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
