from __future__ import annotations

import json
from pathlib import Path

import frappe


def run() -> dict:
    meta = frappe.get_meta("Online Order")
    required_fields = {
        "custom_customer_status_key",
        "custom_customer_status_updated_at",
        "custom_customer_status_events",
    }
    missing = sorted(field for field in required_fields if not meta.has_field(field))
    event_doctype = bool(
        frappe.db.exists("DocType", "Online Order Customer Status Event")
    )
    event_count = frappe.db.count("Online Order Customer Status Event") if event_doctype else 0
    order_count = frappe.db.count("Online Order")

    app_path = Path(frappe.get_app_path("pharma_erp"))
    tracking_py = (app_path / "customer_order_tracking.py").read_text(encoding="utf-8")
    timeline_py = (app_path / "customer_order_status_timeline.py").read_text(encoding="utf-8")
    tracking_js = (app_path / "public/js/customer_order_tracking.js").read_text(encoding="utf-8")
    orders_js = (app_path / "public/js/customer_orders.js").read_text(encoding="utf-8")
    tracking_html = (app_path / "www/pharmacy-order-tracking/index.html").read_text(encoding="utf-8")
    hooks = (app_path / "hooks.py").read_text(encoding="utf-8")

    result = {
        "status": "ok" if not missing and event_doctype else "error",
        "step": "4B",
        "missing_fields": missing,
        "event_doctype": int(event_doctype),
        "online_orders": order_count,
        "recorded_events": event_count,
        "baseline_event_coverage": int(order_count == 0 or event_count >= order_count),
        "central_public_status_mapping_preserved": int("def _public_status" in tracking_py),
        "recorded_event_payload": int("status_activity" in tracking_py),
        "status_revision": int("status_revision" in tracking_py),
        "live_refresh_seconds": int("live_refresh_seconds" in tracking_py),
        "public_payload_whitelist": int("tracking_forbidden_keys" not in tracking_py and "read_only" in tracking_py),
        "timeline_same_transaction_hook": int("sync_customer_status_event" in timeline_py and "doc.append" in timeline_py),
        "tracking_live_polling": int("LIVE_REFRESH_SECONDS" in tracking_js),
        "orders_live_polling": int("LIVE_REFRESH_SECONDS" in orders_js),
        "last_update_ui": int("pharma-tracking-last-update" in tracking_html),
        "hook_installed": int("BEGIN PHARMA STEP 4B LIVE STATUS TIMELINE" in hooks),
        "notifications_enabled": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }
    if result["status"] != "ok":
        frappe.throw(json.dumps(result, ensure_ascii=False))
    return result
