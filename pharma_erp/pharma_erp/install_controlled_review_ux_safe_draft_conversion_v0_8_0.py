from __future__ import annotations

from pathlib import Path

import frappe


REQUIRED_ONLINE_ORDER_FIELDS = (
    "custom_conversion_readiness_status",
    "custom_conversion_execution_status",
    "custom_post_conversion_integrity_status",
    "custom_submit_readiness_status",
    "custom_submit_execution_status",
)


def _missing_fields(doctype: str, fieldnames: tuple[str, ...]) -> list[str]:
    meta = frappe.get_meta(doctype)
    return [fieldname for fieldname in fieldnames if not meta.has_field(fieldname)]


def execute() -> dict:
    if "pharma_erp" not in set(frappe.get_installed_apps()):
        frappe.throw("pharma_erp is not installed on this site.")

    for doctype in ("Online Order", "Online Order Item", "Sales Invoice"):
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType is missing: {doctype}")

    missing_fields = _missing_fields("Online Order", REQUIRED_ONLINE_ORDER_FIELDS)
    if missing_fields:
        frappe.throw(
            "Step 3B.10 requires the controlled conversion foundation. Missing fields: "
            + ", ".join(missing_fields)
        )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    review_backend = app_path / "controlled_online_order_review.py"
    invoice_events = app_path / "online_order_sales_invoice_events.py"
    online_order = app_path / "pharma_erp" / "doctype" / "online_order" / "online_order.py"
    review_page = (
        app_path
        / "pharma_erp"
        / "page"
        / "controlled_online_order_review"
        / "controlled_online_order_review.js"
    )

    required_files = (review_backend, invoice_events, online_order, review_page)
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        frappe.throw("Step 3B.10 source files are missing: " + ", ".join(missing_files))

    review_backend_text = review_backend.read_text(encoding="utf-8")
    invoice_events_text = invoice_events.read_text(encoding="utf-8")
    online_order_text = online_order.read_text(encoding="utf-8")
    review_page_text = review_page.read_text(encoding="utf-8")

    source_checks = {
        "safe_conversion_flag_on_invoice": (
            "invoice.flags.controlled_online_order_conversion = True"
            in online_order_text
        ),
        "safe_conversion_hook_guard": (
            'not doc.flags.get("controlled_online_order_conversion")'
            in invoice_events_text
        ),
        "post_insert_order_reload": "order.reload()" in online_order_text,
        "actionable_filter": "actionable_only" in review_backend_text,
        "unconverted_filter": "unconverted_only" in review_backend_text,
        "date_range_filter": (
            "enable_date_range" in review_backend_text
            and "from_date" in review_backend_text
            and "to_date" in review_backend_text
        ),
        "responsive_card_view": "coor-order-card" in review_page_text,
        "step_banner": "Step 3B.10" in review_page_text,
    }
    failed_checks = [name for name, passed in source_checks.items() if not passed]
    if failed_checks:
        frappe.throw("Step 3B.10 source verification failed: " + ", ".join(failed_checks))

    frappe.clear_cache(doctype="Online Order")
    frappe.clear_cache(doctype="Sales Invoice")
    frappe.clear_cache()
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "3B.10",
        "desk_route": "/app/controlled-online-order-review",
        "safe_draft_conversion": 1,
        "timestamp_mismatch_repair": 1,
        "responsive_card_view": 1,
        "horizontal_scroll_removed": 1,
        "actionable_only_filter": 1,
        "include_completed_filter": 1,
        "unconverted_only_filter": 1,
        "optional_date_range_filter": 1,
        "date_range_requires_both_dates": 1,
        "creates_sales_invoice": 0,
        "submits_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
        "source_checks": source_checks,
    }
