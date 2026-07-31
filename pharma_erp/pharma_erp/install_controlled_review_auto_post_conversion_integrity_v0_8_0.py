from __future__ import annotations

from pathlib import Path

import frappe


def execute() -> dict:
    if "pharma_erp" not in set(frappe.get_installed_apps()):
        frappe.throw("pharma_erp is not installed on this site.")

    app_path = Path(frappe.get_app_path("pharma_erp"))
    confirmation = app_path / "controlled_online_order_confirmation.py"
    review_page = (
        app_path
        / "pharma_erp"
        / "page"
        / "controlled_online_order_review"
        / "controlled_online_order_review.js"
    )

    missing = [str(path) for path in (confirmation, review_page) if not path.exists()]
    if missing:
        frappe.throw("Step 3B.10 R2 source files are missing: " + ", ".join(missing))

    confirmation_text = confirmation.read_text(encoding="utf-8")
    page_text = review_page.read_text(encoding="utf-8")

    source_checks = {
        "automatic_integrity_ready": (
            '_set_if_has(order, "custom_post_conversion_integrity_status", "Ready")'
            in confirmation_text
        ),
        "automatic_integrity_audit": (
            '"automatic_verification": 1' in confirmation_text
            and '"automatic_post_conversion_integrity": 1' in confirmation_text
        ),
        "manual_button_hidden_when_ready": (
            'order.custom_post_conversion_integrity_status !== "Ready"' in page_text
        ),
        "automatic_success_message": (
            "post-conversion integrity verified automatically" in page_text
        ),
    }
    failed = [name for name, passed in source_checks.items() if not passed]
    if failed:
        frappe.throw("Step 3B.10 R2 source verification failed: " + ", ".join(failed))

    frappe.clear_cache(doctype="Online Order")
    frappe.clear_cache(doctype="Sales Invoice")
    frappe.clear_cache()
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "3B.10-R2",
        "automatic_post_conversion_integrity": 1,
        "manual_integrity_click_removed": 1,
        "manual_recheck_available_when_not_ready": 1,
        "creates_sales_invoice": 0,
        "submits_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
        "source_checks": source_checks,
    }
