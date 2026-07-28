from __future__ import annotations

import frappe


EXPECTED_SALES_INVOICE_HOOKS = {
    "on_update_after_submit": (
        "pharma_erp.online_order_sales_invoice_events."
        "sync_online_order_after_invoice_update"
    ),
}

EXPECTED_PAYMENT_ENTRY_HOOKS = {
    "validate": (
        "pharma_erp.online_order_payment_entry_events."
        "validate_linked_online_order_payment"
    ),
    "on_submit": (
        "pharma_erp.online_order_payment_entry_events."
        "on_submit_linked_online_order_payment"
    ),
    "before_cancel": (
        "pharma_erp.online_order_payment_entry_events."
        "before_cancel_linked_online_order_payment"
    ),
}


def _contains(value, expected):
    if isinstance(value, str):
        return value == expected
    return expected in (value or [])


def install():
    frappe.reload_doc("pharma_erp", "doctype", "online_order", force=True)
    frappe.clear_cache(doctype="Online Order")
    frappe.clear_cache(doctype="Sales Invoice")
    frappe.clear_cache(doctype="Payment Entry")
    frappe.db.commit()
    return verify()


def verify():
    online_meta = frappe.get_meta("Online Order")
    hooks = frappe.get_hooks("doc_events") or {}
    sales_invoice_hooks = hooks.get("Sales Invoice") or {}
    payment_entry_hooks = hooks.get("Payment Entry") or {}

    result = {
        "home_delivery_audit_fields": all(
            online_meta.has_field(fieldname)
            for fieldname in (
                "delivery_boy",
                "delivery_trip",
                "delivery_attempt",
                "delivery_departure_at",
                "delivery_delivered_at",
                "delivery_completed_by",
                "delivery_completed_at",
                "delivery_completion_notes",
            )
        ),
        "sales_invoice_delivery_sync_hook": all(
            _contains(sales_invoice_hooks.get(event), handler)
            for event, handler in EXPECTED_SALES_INVOICE_HOOKS.items()
        ),
        "payment_entry_inference_hooks": all(
            _contains(payment_entry_hooks.get(event), handler)
            for event, handler in EXPECTED_PAYMENT_ENTRY_HOOKS.items()
        ),
        "home_delivery_methods": False,
        "sales_invoice_event_module": False,
        "payment_entry_event_module": False,
        "payment_reference_inference": False,
    }

    try:
        from pharma_erp.pharma_erp.doctype.online_order.online_order import (
            complete_home_delivery,
            sync_home_delivery_execution,
        )

        result["home_delivery_methods"] = callable(
            sync_home_delivery_execution
        ) and callable(complete_home_delivery)
    except Exception:
        result["home_delivery_methods"] = False

    try:
        from pharma_erp import online_order_sales_invoice_events as sales_events

        result["sales_invoice_event_module"] = callable(
            getattr(sales_events, "sync_online_order_after_invoice_update", None)
        )
    except Exception:
        result["sales_invoice_event_module"] = False

    try:
        from pharma_erp import online_order_payment_entry_events as payment_events

        result["payment_entry_event_module"] = all(
            callable(getattr(payment_events, function_name, None))
            for function_name in (
                "validate_linked_online_order_payment",
                "on_submit_linked_online_order_payment",
                "before_cancel_linked_online_order_payment",
                "on_cancel_linked_online_order_payment",
                "on_trash_linked_online_order_payment",
            )
        )
        result["payment_reference_inference"] = (
            getattr(
                payment_events,
                "HOME_DELIVERY_PAYMENT_INFERENCE_VERSION",
                None,
            )
            == "v0.8.0-step2e"
        )
    except Exception:
        result["payment_entry_event_module"] = False
        result["payment_reference_inference"] = False

    result["ok"] = all(result.values())
    print(result)
    return result
