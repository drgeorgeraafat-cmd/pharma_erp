from __future__ import annotations

import hashlib
from typing import Any

import frappe
from frappe.utils import cint, now_datetime

EVENT_DOCTYPE = "Online Order Customer Status Event"
EVENT_TABLE_FIELD = "custom_customer_status_events"
STATUS_KEY_FIELD = "custom_customer_status_key"
STATUS_UPDATED_AT_FIELD = "custom_customer_status_updated_at"

_EXCEPTIONAL_KEYS = {"attention", "returned", "rejected", "cancelled"}


def _event_source(status: str) -> str:
    if status in {"Ready for Delivery", "Out for Delivery", "Delivered", "Returned"}:
        return "Delivery"
    if status in {"Ready for Payment", "Payment Verification", "Payment Failed"}:
        return "Payment"
    return "Online Order"


def _event_hash(order_name: str, status: str, event_key: str, event_at: Any) -> str:
    value = f"{order_name}|{status}|{event_key}|{event_at}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _timeline_available() -> bool:
    if not frappe.db.exists("DocType", "Online Order"):
        return False
    if not frappe.db.exists("DocType", EVENT_DOCTYPE):
        return False
    meta = frappe.get_meta("Online Order")
    return all(
        meta.has_field(fieldname)
        for fieldname in (EVENT_TABLE_FIELD, STATUS_KEY_FIELD, STATUS_UPDATED_AT_FIELD)
    )


def sync_customer_status_event(doc, method=None) -> None:
    """Append one safe customer-facing event when the public order status changes.

    The event is saved in the same Online Order transaction. It never creates or
    updates Sales Invoice, Payment Entry, GL Entry, Stock Ledger Entry, Delivery
    Trip, or inventory documents.
    """
    if getattr(doc, "doctype", "") != "Online Order" or not _timeline_available():
        return

    from pharma_erp.customer_order_tracking import _public_status

    status = str(doc.get("status") or "Draft")
    public = _public_status(status)
    event_key = str(public.get("key") or "review")
    label_ar = str(public.get("label_ar") or "قيد المراجعة")
    message_ar = str(public.get("message_ar") or "")

    rows = list(doc.get(EVENT_TABLE_FIELD) or [])
    last = rows[-1] if rows else None
    if last:
        last_key = str(last.get("event_key") or "")
        last_status = str(last.get("source_status") or "")
        if last_key == event_key and last_status == status:
            doc.set(STATUS_KEY_FIELD, event_key)
            if not doc.get(STATUS_UPDATED_AT_FIELD):
                doc.set(STATUS_UPDATED_AT_FIELD, last.get("event_at"))
            return

    event_at = now_datetime()
    doc.append(
        EVENT_TABLE_FIELD,
        {
            "event_key": event_key,
            "label_ar": label_ar,
            "message_ar": message_ar,
            "source_status": status,
            "event_at": event_at,
            "event_source": _event_source(status),
            "is_exceptional": cint(event_key in _EXCEPTIONAL_KEYS),
            "event_hash": _event_hash(doc.name or "new", status, event_key, event_at),
        },
    )
    doc.set(STATUS_KEY_FIELD, event_key)
    doc.set(STATUS_UPDATED_AT_FIELD, event_at)


def bootstrap_existing_orders() -> dict[str, int]:
    """Create one baseline event for existing orders without changing business state."""
    if not _timeline_available():
        return {"orders_seen": 0, "events_created": 0}

    from pharma_erp.customer_order_tracking import _public_status

    orders = frappe.get_all(
        "Online Order",
        fields=["name", "status", "creation", "modified"],
        order_by="creation asc",
    )
    created = 0
    for order in orders:
        if frappe.db.exists(EVENT_DOCTYPE, {"parent": order.name, "parenttype": "Online Order"}):
            continue
        status = str(order.status or "Draft")
        public = _public_status(status)
        event_at = order.modified or order.creation or now_datetime()
        event_key = str(public.get("key") or "review")
        child = frappe.get_doc(
            {
                "doctype": EVENT_DOCTYPE,
                "parent": order.name,
                "parenttype": "Online Order",
                "parentfield": EVENT_TABLE_FIELD,
                "event_key": event_key,
                "label_ar": public.get("label_ar") or "قيد المراجعة",
                "message_ar": public.get("message_ar") or "",
                "source_status": status,
                "event_at": event_at,
                "event_source": _event_source(status),
                "is_exceptional": cint(event_key in _EXCEPTIONAL_KEYS),
                "event_hash": _event_hash(order.name, status, event_key, event_at),
            }
        )
        child.insert(ignore_permissions=True)
        frappe.db.set_value(
            "Online Order",
            order.name,
            {
                STATUS_KEY_FIELD: event_key,
                STATUS_UPDATED_AT_FIELD: event_at,
            },
            update_modified=False,
        )
        created += 1

    return {"orders_seen": len(orders), "events_created": created}
