from __future__ import annotations

import frappe

EXPECTED = {
    "validate": "pharma_erp.online_order_sales_invoice_events.validate_linked_online_order_invoice",
    "before_submit": "pharma_erp.online_order_sales_invoice_events.before_submit_linked_online_order_invoice",
    "on_submit": "pharma_erp.online_order_sales_invoice_events.on_submit_linked_online_order_invoice",
    "on_update_after_submit": "pharma_erp.online_order_sales_invoice_events.sync_online_order_after_invoice_update",
    "before_cancel": "pharma_erp.online_order_sales_invoice_events.before_cancel_linked_online_order_invoice",
    "on_cancel": "pharma_erp.online_order_sales_invoice_events.on_cancel_linked_online_order_invoice",
}


def _contains(value, expected):
    if isinstance(value, str):
        return value == expected
    return expected in (value or [])


def install():
    frappe.clear_cache()
    return verify()


def verify():
    hooks = frappe.get_hooks("doc_events") or {}
    sales_invoice_hooks = hooks.get("Sales Invoice") or {}

    result = {
        "submit_method": False,
        "event_module": False,
        "sales_invoice_hooks": all(
            _contains(sales_invoice_hooks.get(event), handler)
            for event, handler in EXPECTED.items()
        ),
    }

    try:
        from pharma_erp.pharma_erp.doctype.online_order.online_order import (
            submit_linked_sales_invoice,
        )

        result["submit_method"] = callable(submit_linked_sales_invoice)
    except Exception:
        result["submit_method"] = False

    try:
        from pharma_erp import online_order_sales_invoice_events as event_module

        result["event_module"] = all(
            callable(getattr(event_module, function_name, None))
            for function_name in (
                "validate_linked_online_order_invoice",
                "before_submit_linked_online_order_invoice",
                "on_submit_linked_online_order_invoice",
                "sync_online_order_after_invoice_update",
                "before_cancel_linked_online_order_invoice",
                "on_cancel_linked_online_order_invoice",
            )
        )
    except Exception:
        result["event_module"] = False

    result["ok"] = all(result.values())
    print(result)
    return result
