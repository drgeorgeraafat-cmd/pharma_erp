from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
    "Payment Entry": [
        {
            "fieldname": "custom_online_order",
            "label": "Online Order",
            "fieldtype": "Link",
            "options": "Online Order",
            "insert_after": "mode_of_payment",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        }
    ]
}

EXPECTED_PAYMENT_HOOKS = {
    "validate": "pharma_erp.online_order_payment_entry_events.validate_linked_online_order_payment",
    "on_submit": "pharma_erp.online_order_payment_entry_events.on_submit_linked_online_order_payment",
    "before_cancel": "pharma_erp.online_order_payment_entry_events.before_cancel_linked_online_order_payment",
    "on_cancel": "pharma_erp.online_order_payment_entry_events.on_cancel_linked_online_order_payment",
    "on_trash": "pharma_erp.online_order_payment_entry_events.on_trash_linked_online_order_payment",
}


def _contains(value, expected):
    if isinstance(value, str):
        return value == expected
    return expected in (value or [])


def install():
    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Online Order")
    frappe.clear_cache(doctype="Payment Entry")
    frappe.clear_cache(doctype="Sales Invoice")
    frappe.db.commit()
    return verify()


def verify():
    online_meta = frappe.get_meta("Online Order")
    payment_status = online_meta.get_field("payment_status")
    payment_status_options = {
        value.strip()
        for value in str(payment_status.options or "").splitlines()
        if value.strip()
    }

    hooks = frappe.get_hooks("doc_events") or {}
    payment_hooks = hooks.get("Payment Entry") or {}

    result = {
        "payment_entry_online_order_link": frappe.get_meta("Payment Entry").has_field(
            "custom_online_order"
        ),
        "collection_draft_status": "Collection Draft Created" in payment_status_options,
        "pickup_audit_fields": all(
            online_meta.has_field(fieldname)
            for fieldname in (
                "pickup_completed_by",
                "pickup_completed_at",
                "pickup_completion_notes",
            )
        ),
        "payment_entry_hooks": all(
            _contains(payment_hooks.get(event), handler)
            for event, handler in EXPECTED_PAYMENT_HOOKS.items()
        ),
        "pickup_methods": False,
        "payment_event_module": False,
        "exact_pickup_amount_guard": False,
    }

    try:
        from pharma_erp.pharma_erp.doctype.online_order.online_order import (
            complete_pharmacy_pickup,
            create_pickup_payment_draft,
        )

        result["pickup_methods"] = callable(create_pickup_payment_draft) and callable(
            complete_pharmacy_pickup
        )
    except Exception:
        result["pickup_methods"] = False

    try:
        from pharma_erp import online_order_payment_entry_events as event_module

        result["payment_event_module"] = all(
            callable(getattr(event_module, function_name, None))
            for function_name in (
                "validate_linked_online_order_payment",
                "on_submit_linked_online_order_payment",
                "before_cancel_linked_online_order_payment",
                "on_cancel_linked_online_order_payment",
                "on_trash_linked_online_order_payment",
            )
        )
        result["exact_pickup_amount_guard"] = (
            getattr(event_module, "EXACT_PICKUP_AMOUNT_GUARD_VERSION", None)
            == "v0.8.0-step2d2"
            and callable(getattr(event_module, "_assert_exact_collection_amount", None))
        )
    except Exception:
        result["payment_event_module"] = False

    result["ok"] = all(result.values())
    print(result)
    return result
