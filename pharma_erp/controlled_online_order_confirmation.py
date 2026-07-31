from __future__ import annotations

import html
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate, strip_html

from pharma_erp.controlled_online_order_review import _snapshot as _review_snapshot
from pharma_erp.online_order_sales_invoice_events import (
    validate_linked_online_order_invoice,
)
from pharma_erp.pharma_erp import payment_card_management as shift_finance
from pharma_erp.pharma_erp.doctype.online_order.online_order import (
    _home_delivery_collection_state,
    _sync_home_delivery_order_from_invoice,
    complete_home_delivery,
)

PAYMENT_TOLERANCE = 0.01
POST_CONVERSION_TOLERANCE = 0.01
PAYMENT_SELECTION_STATUSES = {"Ready for Payment", "Payment Verification"}
CONFIRMABLE_STATUSES = {"Ready for Payment", "Payment Verification"}
CONVERSION_STATUSES = {"Confirmed", "Preparing"}

PAYMENT_OPTIONS: dict[str, dict[str, Any]] = {
    "Cash on Delivery": {
        "label_ar": "الدفع عند الاستلام",
        "payment_timing": "Collect on Delivery",
        "mode_of_payment": "Cash",
        "fulfilment_methods": {"Home Delivery"},
        "prepaid": 0,
    },
    "Cash at Pharmacy": {
        "label_ar": "الدفع عند الاستلام من الصيدلية",
        "payment_timing": "Collect on Delivery",
        "mode_of_payment": "Cash",
        "fulfilment_methods": {"Pharmacy Pickup"},
        "prepaid": 0,
    },
    "InstaPay": {
        "label_ar": "InstaPay — دفع مسبق",
        "payment_timing": "Prepaid",
        "mode_of_payment": "Insta Pay",
        "fulfilment_methods": {"Home Delivery", "Pharmacy Pickup"},
        "prepaid": 1,
    },
    "Mobile Wallet": {
        "label_ar": "محفظة إلكترونية — دفع مسبق",
        "payment_timing": "Prepaid",
        "mode_of_payment": "Wallet",
        "fulfilment_methods": {"Home Delivery", "Pharmacy Pickup"},
        "prepaid": 1,
    },
}

PUBLIC_PAYMENT_OPTIONS = {
    "Home Delivery": ("Cash on Delivery",),
    "Pharmacy Pickup": ("Cash at Pharmacy", "InstaPay", "Mobile Wallet"),
}


def _clean_text(value: Any, limit: int = 500) -> str:
    return " ".join(strip_html(str(value or "")).split())[:limit]


def _require_authenticated_user() -> None:
    if frappe.session.user == "Guest":
        frappe.throw(_("Login is required."), frappe.PermissionError)


def _get_order(online_order: str | None, permission: str = "read"):
    _require_authenticated_user()
    name = _clean_text(online_order, 140)
    if not name or not frappe.db.exists("Online Order", name):
        frappe.throw(_("Online Order was not found."), frappe.DoesNotExistError)
    order = frappe.get_doc("Online Order", name)
    if not frappe.has_permission("Online Order", permission, doc=order):
        frappe.throw(
            _("You do not have permission for this Online Order."),
            frappe.PermissionError,
        )
    return order


def _set_if_has(order, fieldname: str, value: Any) -> None:
    if order.meta.has_field(fieldname):
        order.set(fieldname, value)


def _audit_comment(order, title: str, details: dict[str, Any]) -> None:
    safe_details = json.dumps(details, ensure_ascii=False, sort_keys=True, default=str)
    order.add_comment(
        "Info",
        "<b>{0}</b><br><code>{1}</code>".format(
            html.escape(title),
            html.escape(safe_details),
        ),
    )


def _payment_option_rows(order, public_only: bool = False) -> list[dict[str, Any]]:
    fulfilment = str(order.fulfilment_method or "")
    allowed_public = set(PUBLIC_PAYMENT_OPTIONS.get(fulfilment, ()))
    rows: list[dict[str, Any]] = []
    for name, config in PAYMENT_OPTIONS.items():
        if fulfilment not in config["fulfilment_methods"]:
            continue
        if public_only and name not in allowed_public:
            continue
        rows.append(
            {
                "name": name,
                "label_ar": config["label_ar"],
                "payment_timing": config["payment_timing"],
                "mode_of_payment": config["mode_of_payment"],
                "prepaid": cint(config["prepaid"]),
                "requires_transaction_reference": cint(config["prepaid"]),
                "requires_full_declared_amount": cint(config["prepaid"]),
            }
        )
    return rows


def _submitted_payment_entry(order) -> bool:
    payment_entry = str(order.payment_entry or "").strip()
    if not payment_entry or not frappe.db.exists("Payment Entry", payment_entry):
        return False
    return cint(frappe.db.get_value("Payment Entry", payment_entry, "docstatus")) == 1


def _standard_confirmation_blockers(order) -> list[str]:
    snapshot = _review_snapshot(order)
    blockers = list(snapshot.get("review_blockers") or [])
    blockers.extend(snapshot.get("confirmation_blockers") or [])
    return blockers


def _payment_confirmation_blockers(order) -> list[str]:
    blockers: list[str] = []
    selection_status = getattr(order, "custom_payment_selection_status", "Pending") or "Pending"
    if selection_status != "Ready":
        blockers.append(_("Controlled payment selection is not Ready."))

    timing = str(order.payment_timing or "")
    method = str(order.payment_method or "")
    option = PAYMENT_OPTIONS.get(method)
    if not option:
        blockers.append(_("Select a supported controlled payment method."))
        return blockers
    if timing != option["payment_timing"]:
        blockers.append(_("Payment Timing does not match the selected payment method."))
    if order.fulfilment_method not in option["fulfilment_methods"]:
        blockers.append(_("The selected payment method is not valid for this fulfilment method."))

    if timing == "Collect on Delivery":
        if order.payment_status not in {"Pending Collection", "Not Declared"}:
            blockers.append(_("Collect on Delivery must remain Pending Collection before confirmation."))
        if flt(order.declared_paid_amount) > PAYMENT_TOLERANCE:
            blockers.append(_("Collect on Delivery cannot have a declared prepaid amount."))
        if flt(order.verified_paid_amount) > PAYMENT_TOLERANCE:
            blockers.append(_("Collect on Delivery cannot have a verified prepaid amount."))
    elif timing == "Prepaid":
        if order.payment_status != "Verified":
            blockers.append(_("Prepaid payment must be Verified before confirmation."))
        if abs(flt(order.declared_paid_amount) - flt(order.grand_total)) > PAYMENT_TOLERANCE:
            blockers.append(_("Declared prepaid amount must equal the Online Order grand total."))
        if abs(flt(order.verified_paid_amount) - flt(order.grand_total)) > PAYMENT_TOLERANCE:
            blockers.append(_("Verified prepaid amount must equal the Online Order grand total."))
        if not order.transaction_reference and not order.payment_proof:
            blockers.append(_("Prepaid payment requires a transaction reference or payment proof."))
        if not _submitted_payment_entry(order):
            blockers.append(_("Verified prepaid payment must be linked to a submitted Payment Entry."))
    elif timing == "Partially Prepaid":
        if order.payment_status != "Partially Verified":
            blockers.append(_("Partial prepayment must be Partially Verified before confirmation."))
        if flt(order.verified_paid_amount) <= PAYMENT_TOLERANCE:
            blockers.append(_("Partial prepayment requires a verified paid amount."))
        if flt(order.verified_paid_amount) >= flt(order.grand_total) - PAYMENT_TOLERANCE:
            blockers.append(_("Use Prepaid when the full grand total is verified."))
        if not _submitted_payment_entry(order):
            blockers.append(_("Verified partial prepayment must be linked to a submitted Payment Entry."))
    elif timing == "No Collection Required":
        if order.payment_status != "No Collection Required":
            blockers.append(_("No Collection Required payment status is inconsistent."))
    else:
        blockers.append(_("Select a valid Payment Timing."))
    return blockers


def _confirmation_blockers(order) -> list[str]:
    blockers = _standard_confirmation_blockers(order)
    if (
        getattr(order, "custom_final_confirmation_readiness_status", "Pending")
        != "Ready"
    ):
        blockers.append(_("Step 3B.5 final confirmation readiness is not Ready."))
    blockers.extend(_payment_confirmation_blockers(order))
    if order.status not in CONFIRMABLE_STATUSES:
        blockers.append(_("Online Order status must be Ready for Payment or Payment Verification."))
    if order.sales_order:
        blockers.append(_("A Sales Order is already linked to this Online Order."))
    if order.sales_invoice:
        blockers.append(_("A Sales Invoice is already linked to this Online Order."))
    return list(dict.fromkeys(blockers))


def _delivery_fee_item_blockers(order) -> list[str]:
    if flt(order.delivery_fee) <= PAYMENT_TOLERANCE:
        return []
    if not frappe.db.exists("DocType", "Pharmacy POS Settings"):
        return [_('Pharmacy POS Settings is required for delivery-fee conversion.')]
    item_code = str(
        frappe.db.get_single_value("Pharmacy POS Settings", "delivery_fee_item") or ""
    ).strip()
    if not item_code:
        return [_('Configure Delivery Fee Item in Pharmacy POS Settings.')]
    values = frappe.db.get_value(
        "Item",
        item_code,
        ["disabled", "is_stock_item"],
        as_dict=True,
    )
    if not values:
        return [_('Configured Delivery Fee Item was not found.')]
    if cint(values.get("disabled")):
        return [_('Configured Delivery Fee Item is disabled.')]
    if cint(values.get("is_stock_item")):
        return [_('Delivery Fee Item must be a non-stock Item.')]
    return []


def _conversion_blockers(order) -> list[str]:
    blockers: list[str] = []
    if order.status not in CONVERSION_STATUSES:
        blockers.append(_("Online Order must be Confirmed or Preparing before conversion."))
    if order.sales_order:
        blockers.append(_("A Sales Order is already linked to this Online Order."))
    if order.sales_invoice:
        blockers.append(_("A Sales Invoice is already linked to this Online Order."))
    if (
        getattr(order, "custom_order_confirmation_readiness_status", "Pending")
        != "Ready"
    ):
        blockers.append(_("Order confirmation readiness is not Ready."))
    if getattr(order, "custom_payment_selection_status", "Pending") != "Ready":
        blockers.append(_("Controlled payment selection is not Ready."))
    blockers.extend(_standard_confirmation_blockers(order))
    blockers.extend(_payment_confirmation_blockers(order))
    blockers.extend(_delivery_fee_item_blockers(order))
    return list(dict.fromkeys(blockers))


def _state_snapshot(order) -> dict[str, Any]:
    confirmation_blockers = _confirmation_blockers(order)
    conversion_blockers = _conversion_blockers(order)
    return {
        "online_order": order.name,
        "status": order.status,
        "fulfilment_method": order.fulfilment_method,
        "customer": order.customer or "",
        "customer_address": order.customer_address or "",
        "warehouse": order.warehouse or "",
        "delivery_zone": order.delivery_zone or "",
        "currency": order.currency,
        "products_subtotal": flt(order.products_subtotal),
        "delivery_fee": flt(order.delivery_fee),
        "grand_total": flt(order.grand_total),
        "payment_timing": order.payment_timing or "",
        "payment_method": order.payment_method or "",
        "mode_of_payment": order.mode_of_payment or "",
        "payment_status": order.payment_status or "",
        "declared_paid_amount": flt(order.declared_paid_amount),
        "verified_paid_amount": flt(order.verified_paid_amount),
        "transaction_reference": order.transaction_reference or "",
        "payment_proof": order.payment_proof or "",
        "payment_entry": order.payment_entry or "",
        "payment_selection_status": getattr(
            order, "custom_payment_selection_status", "Pending"
        )
        or "Pending",
        "final_confirmation_readiness_status": getattr(
            order, "custom_final_confirmation_readiness_status", "Pending"
        )
        or "Pending",
        "order_confirmation_readiness_status": getattr(
            order, "custom_order_confirmation_readiness_status", "Pending"
        )
        or "Pending",
        "conversion_readiness_status": getattr(
            order, "custom_conversion_readiness_status", "Pending"
        )
        or "Pending",
        "conversion_execution_status": getattr(
            order, "custom_conversion_execution_status", "Pending"
        )
        or "Pending",
        "post_conversion_integrity_status": getattr(
            order, "custom_post_conversion_integrity_status", "Pending"
        )
        or "Pending",
        "submit_readiness_status": getattr(
            order, "custom_submit_readiness_status", "Pending"
        )
        or "Pending",
        "submit_execution_status": getattr(
            order, "custom_submit_execution_status", "Pending"
        )
        or "Pending",
        "delivery_sync_status": getattr(
            order, "custom_delivery_sync_status", "Pending"
        )
        or "Pending",
        "delivery_completion_readiness_status": getattr(
            order, "custom_delivery_completion_readiness_status", "Pending"
        )
        or "Pending",
        "delivery_status_snapshot": getattr(order, "delivery_status_snapshot", "") or "",
        "delivery_boy": getattr(order, "delivery_boy", "") or "",
        "delivery_trip": getattr(order, "delivery_trip", "") or "",
        "delivery_attempt": getattr(order, "delivery_attempt", "") or "",
        "delivery_departure_at": getattr(order, "delivery_departure_at", None),
        "delivery_delivered_at": getattr(order, "delivery_delivered_at", None),
        "delivery_completed_by": getattr(order, "delivery_completed_by", "") or "",
        "delivery_completed_at": getattr(order, "delivery_completed_at", None),
        "confirmed_at": order.confirmed_at,
        "sales_order": order.sales_order or "",
        "sales_invoice": order.sales_invoice or "",
        "payment_options": _payment_option_rows(order),
        "confirmation_blockers": confirmation_blockers,
        "confirmation_ready": cint(not confirmation_blockers),
        "conversion_blockers": conversion_blockers,
        "conversion_ready": cint(not conversion_blockers),
        "sales_invoice_draft_api": (
            "pharma_erp.pharma_erp.doctype.online_order.online_order."
            "create_sales_invoice_draft"
        ),
        "creates_quotation": 0,
        "creates_sales_order": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
    }


@frappe.whitelist(allow_guest=True)
def get_public_payment_options(fulfilment_method: str | None = None) -> dict[str, Any]:
    fulfilment = _clean_text(fulfilment_method, 40)
    if fulfilment not in PUBLIC_PAYMENT_OPTIONS:
        frappe.throw(_("Select a valid fulfilment method."))
    rows = []
    for name in PUBLIC_PAYMENT_OPTIONS[fulfilment]:
        config = PAYMENT_OPTIONS[name]
        rows.append(
            {
                "name": name,
                "label_ar": config["label_ar"],
                "payment_timing": config["payment_timing"],
                "mode_of_payment": config["mode_of_payment"],
                "prepaid": cint(config["prepaid"]),
                "requires_transaction_reference": cint(config["prepaid"]),
            }
        )
    return {
        "fulfilment_method": fulfilment,
        "options": rows,
        "delivery_fee_pending_review": cint(fulfilment == "Home Delivery"),
        "home_delivery_prepaid_public_checkout": 0,
        "creates_payment_entry": 0,
    }


@frappe.whitelist()
def get_payment_selection_context(online_order: str | None = None) -> dict[str, Any]:
    order = _get_order(online_order, "read")
    result = _state_snapshot(order)
    result["controlled_payment_selection"] = 1
    return result


@frappe.whitelist(methods=["POST"])
def apply_payment_selection(
    online_order: str | None = None,
    payment_method: str | None = None,
    declared_paid_amount: float | str | None = None,
    transaction_reference: str | None = None,
    payment_proof: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    if order.status not in PAYMENT_SELECTION_STATUSES:
        frappe.throw(_("Payment selection is only allowed before order confirmation."))
    if order.sales_order or order.sales_invoice:
        frappe.throw(_("Payment selection is locked after ERP conversion starts."))
    if (
        getattr(order, "custom_final_confirmation_readiness_status", "Pending")
        != "Ready"
    ):
        frappe.throw(_("Verify Step 3B.5 final readiness before payment selection."))

    method = _clean_text(payment_method, 80)
    option = PAYMENT_OPTIONS.get(method)
    if not option or order.fulfilment_method not in option["fulfilment_methods"]:
        frappe.throw(_("Select a supported payment method for this fulfilment method."))

    if order.payment_entry and frappe.db.exists("Payment Entry", order.payment_entry):
        if cint(frappe.db.get_value("Payment Entry", order.payment_entry, "docstatus")) < 2:
            frappe.throw(_("Cancel the linked Payment Entry before changing payment selection."))

    order.payment_method = method
    order.payment_timing = option["payment_timing"]
    order.mode_of_payment = option["mode_of_payment"]
    order.payment_review_notes = _clean_text(notes, 1000)

    if cint(option["prepaid"]):
        declared = flt(declared_paid_amount)
        if abs(declared - flt(order.grand_total)) > PAYMENT_TOLERANCE:
            frappe.throw(_("Full prepaid amount must equal the Online Order grand total."))
        reference = _clean_text(transaction_reference, 140)
        proof = _clean_text(payment_proof, 500)
        if not reference and not proof:
            frappe.throw(_("Add a transaction reference or payment proof."))
        order.declared_paid_amount = declared
        order.verified_paid_amount = 0
        order.transaction_reference = reference
        order.payment_proof = proof
        order.payment_status = "Awaiting Verification"
        order.payment_verified_by = None
        order.payment_verified_at = None
        if order.status == "Ready for Payment":
            order.status = "Payment Verification"
        selection_status = "Awaiting Verification"
        _set_if_has(order, "custom_final_confirmation_readiness_status", "Pending")
        _set_if_has(order, "custom_final_confirmation_checked_by", None)
        _set_if_has(order, "custom_final_confirmation_checked_at", None)
        _set_if_has(
            order,
            "custom_final_confirmation_notes",
            "Payment changed to prepaid and requires verification.",
        )
    else:
        order.declared_paid_amount = 0
        order.verified_paid_amount = 0
        order.transaction_reference = None
        order.payment_proof = None
        order.payment_status = "Pending Collection"
        order.payment_verified_by = None
        order.payment_verified_at = None
        selection_status = "Ready"

    _set_if_has(order, "custom_payment_selection_status", selection_status)
    _set_if_has(order, "custom_payment_selection_notes", _clean_text(notes, 1000))
    _set_if_has(order, "custom_payment_selected_by", frappe.session.user)
    _set_if_has(order, "custom_payment_selected_at", now_datetime())
    _set_if_has(order, "custom_order_confirmation_readiness_status", "Pending")
    _set_if_has(order, "custom_order_confirmation_notes", "")
    _set_if_has(order, "custom_order_confirmation_checked_by", None)
    _set_if_has(order, "custom_order_confirmation_checked_at", None)
    _set_if_has(order, "custom_conversion_readiness_status", "Pending")
    _set_if_has(order, "custom_conversion_readiness_notes", "")
    _set_if_has(order, "custom_conversion_readiness_checked_by", None)
    _set_if_has(order, "custom_conversion_readiness_checked_at", None)
    _set_if_has(order, "custom_conversion_execution_status", "Pending")
    _set_if_has(order, "custom_conversion_execution_notes", "")
    _set_if_has(order, "custom_conversion_executed_by", None)
    _set_if_has(order, "custom_conversion_executed_at", None)
    _set_if_has(order, "custom_post_conversion_integrity_status", "Pending")
    _set_if_has(order, "custom_post_conversion_integrity_notes", "")
    _set_if_has(order, "custom_post_conversion_checked_by", None)
    _set_if_has(order, "custom_post_conversion_checked_at", None)
    _set_if_has(order, "custom_submit_readiness_status", "Pending")
    _set_if_has(order, "custom_submit_readiness_notes", "")
    _set_if_has(order, "custom_submit_readiness_checked_by", None)
    _set_if_has(order, "custom_submit_readiness_checked_at", None)
    _set_if_has(order, "custom_submit_execution_status", "Pending")
    _set_if_has(order, "custom_submit_execution_notes", "")
    _set_if_has(order, "custom_submitted_by", None)
    _set_if_has(order, "custom_submitted_at", None)
    order.save(ignore_permissions=True)

    _audit_comment(
        order,
        _("Controlled Payment Selection"),
        {
            "payment_timing": order.payment_timing,
            "payment_method": order.payment_method,
            "mode_of_payment": order.mode_of_payment,
            "payment_status": order.payment_status,
            "declared_paid_amount": flt(order.declared_paid_amount),
            "grand_total": flt(order.grand_total),
            "selection_status": selection_status,
            "selected_by": frappe.session.user,
            "selected_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "creates_financial_or_stock_documents": 0,
        },
    )
    return _state_snapshot(order)


@frappe.whitelist(methods=["POST"])
def verify_order_confirmation_readiness(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    blockers = _confirmation_blockers(order)
    readiness = "Ready" if not blockers else "Blocked"
    _set_if_has(order, "custom_order_confirmation_readiness_status", readiness)
    _set_if_has(order, "custom_order_confirmation_notes", _clean_text(notes, 1000))
    _set_if_has(order, "custom_order_confirmation_checked_by", frappe.session.user)
    _set_if_has(order, "custom_order_confirmation_checked_at", now_datetime())
    order.save(ignore_permissions=True)
    _audit_comment(
        order,
        _("Controlled Order Confirmation Readiness"),
        {
            "readiness_status": readiness,
            "blockers": blockers,
            "payment_timing": order.payment_timing,
            "payment_method": order.payment_method,
            "payment_status": order.payment_status,
            "checked_by": frappe.session.user,
            "checked_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "creates_financial_or_stock_documents": 0,
        },
    )
    return _state_snapshot(order)


@frappe.whitelist(methods=["POST"])
def confirm_online_order(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()
    if order.status == "Confirmed":
        result = _state_snapshot(order)
        result["confirmed"] = 0
        result["idempotent_replay"] = 1
        return result
    if order.status not in CONFIRMABLE_STATUSES:
        frappe.throw(_("Online Order cannot be confirmed from its current status."))
    if (
        getattr(order, "custom_order_confirmation_readiness_status", "Pending")
        != "Ready"
    ):
        frappe.throw(_("Verify order confirmation readiness first."))
    blockers = _confirmation_blockers(order)
    if blockers:
        frappe.throw(_("Order confirmation is blocked: {0}").format(" | ".join(blockers)))

    order.status = "Confirmed"
    _set_if_has(order, "custom_conversion_readiness_status", "Pending")
    _set_if_has(order, "custom_conversion_readiness_notes", "")
    _set_if_has(order, "custom_conversion_readiness_checked_by", None)
    _set_if_has(order, "custom_conversion_readiness_checked_at", None)
    _set_if_has(order, "custom_conversion_execution_status", "Pending")
    _set_if_has(order, "custom_conversion_execution_notes", "")
    _set_if_has(order, "custom_conversion_executed_by", None)
    _set_if_has(order, "custom_conversion_executed_at", None)
    _set_if_has(order, "custom_post_conversion_integrity_status", "Pending")
    _set_if_has(order, "custom_post_conversion_integrity_notes", "")
    _set_if_has(order, "custom_post_conversion_checked_by", None)
    _set_if_has(order, "custom_post_conversion_checked_at", None)
    order.save(ignore_permissions=True)
    _audit_comment(
        order,
        _("Controlled Online Order Confirmation"),
        {
            "status": order.status,
            "confirmed_at": order.confirmed_at,
            "customer": order.customer,
            "customer_address": order.customer_address,
            "delivery_zone": order.delivery_zone,
            "warehouse": order.warehouse,
            "grand_total": flt(order.grand_total),
            "payment_timing": order.payment_timing,
            "payment_method": order.payment_method,
            "payment_status": order.payment_status,
            "confirmed_by": frappe.session.user,
            "notes": _clean_text(notes, 1000),
            "creates_financial_or_stock_documents": 0,
        },
    )
    result = _state_snapshot(order)
    result["confirmed"] = 1
    result["idempotent_replay"] = 0
    return result


@frappe.whitelist()
def get_conversion_readiness(online_order: str | None = None) -> dict[str, Any]:
    order = _get_order(online_order, "read")
    result = _state_snapshot(order)
    result["controlled_conversion_readiness"] = 1
    return result


@frappe.whitelist(methods=["POST"])
def verify_conversion_readiness(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    blockers = _conversion_blockers(order)
    readiness = "Ready" if not blockers else "Blocked"
    _set_if_has(order, "custom_conversion_readiness_status", readiness)
    _set_if_has(order, "custom_conversion_readiness_notes", _clean_text(notes, 1000))
    _set_if_has(order, "custom_conversion_readiness_checked_by", frappe.session.user)
    _set_if_has(order, "custom_conversion_readiness_checked_at", now_datetime())
    order.save(ignore_permissions=True)
    _audit_comment(
        order,
        _("Controlled Sales Invoice Conversion Readiness"),
        {
            "readiness_status": readiness,
            "blockers": blockers,
            "status": order.status,
            "sales_order": order.sales_order or "",
            "sales_invoice": order.sales_invoice or "",
            "checked_by": frappe.session.user,
            "checked_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "creates_sales_invoice": 0,
            "creates_financial_or_stock_documents": 0,
        },
    )
    return _state_snapshot(order)


def _active_sales_invoice(order):
    invoice_name = str(order.sales_invoice or "").strip()
    if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
        return None
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if cint(invoice.docstatus) == 2:
        return None
    return invoice


def _sales_invoice_creation_blockers(order) -> list[str]:
    blockers = list(_conversion_blockers(order))
    if getattr(order, "custom_conversion_readiness_status", "Pending") != "Ready":
        blockers.append(_("Sales Invoice conversion readiness is not Ready."))
    if _active_sales_invoice(order):
        blockers.append(
            _("An active Sales Invoice Draft is already linked to this Online Order.")
        )
    return list(dict.fromkeys(blockers))


def _post_conversion_integrity_blockers(order, invoice=None) -> list[str]:
    blockers: list[str] = []
    invoice = invoice or _active_sales_invoice(order)
    if not invoice:
        return [_('An active linked Sales Invoice Draft is required.')]

    if order.sales_order:
        blockers.append(_("The Online Order must not use the Sales Order conversion path."))
    if order.sales_invoice != invoice.name:
        blockers.append(_("The Online Order active Sales Invoice link is inconsistent."))
    if order.conversion_path != "Direct Sales Invoice":
        blockers.append(_("Conversion Path must be Direct Sales Invoice."))
    if cint(invoice.docstatus) != 0:
        blockers.append(_("The linked Sales Invoice must remain Draft during Step 3B.7."))
    if cint(invoice.update_stock):
        blockers.append(_("The linked Sales Invoice Draft must keep Update Stock disabled."))
    if cint(invoice.is_pos):
        blockers.append(_("The linked Sales Invoice Draft must remain non-POS."))
    if cint(invoice.is_return):
        blockers.append(
            _("A return Sales Invoice cannot be linked as the active conversion draft.")
        )
    if str(invoice.get("custom_online_order") or "").strip() != order.name:
        blockers.append(
            _("Sales Invoice custom_online_order does not match the Online Order.")
        )
    if invoice.customer != order.customer:
        blockers.append(_("Sales Invoice Customer does not match the Online Order."))
    if invoice.company != order.company:
        blockers.append(_("Sales Invoice Company does not match the Online Order."))
    if invoice.currency != order.currency:
        blockers.append(_("Sales Invoice Currency does not match the Online Order."))
    if (
        abs(flt(invoice.grand_total) - flt(order.grand_total))
        > POST_CONVERSION_TOLERANCE
    ):
        blockers.append(_("Sales Invoice grand total does not match the Online Order."))

    if order.fulfilment_method == "Home Delivery":
        if invoice.customer_address != order.customer_address:
            blockers.append(
                _("Sales Invoice Customer Address does not match the Online Order.")
            )
        if invoice.shipping_address_name != order.customer_address:
            blockers.append(
                _("Sales Invoice Shipping Address does not match the Online Order.")
            )
        if str(invoice.get("custom_delivery_zone") or "") != str(
            order.delivery_zone or ""
        ):
            blockers.append(
                _("Sales Invoice Delivery Zone does not match the Online Order.")
            )
        if (
            abs(flt(invoice.get("custom_delivery_fee")) - flt(order.delivery_fee))
            > POST_CONVERSION_TOLERANCE
        ):
            blockers.append(
                _("Sales Invoice Delivery Fee does not match the Online Order.")
            )

    active_invoice_count = frappe.db.count(
        "Sales Invoice",
        {"custom_online_order": order.name, "docstatus": ["<", 2]},
    )
    if cint(active_invoice_count) != 1:
        blockers.append(
            _("Exactly one active Sales Invoice must exist for this Online Order.")
        )

    mapped_rows = 0
    for row in order.items:
        if flt(row.approved_qty) <= 0:
            continue
        if str(row.availability_status or "") in {"Removed", "Unavailable"}:
            continue
        mapped_rows += 1
        invoice_item = str(row.sales_invoice_item or "").strip()
        if not invoice_item:
            blockers.append(
                _(
                    "Online Order item row {0} is not linked to a Sales Invoice Item."
                ).format(row.idx)
            )
            continue
        if not frappe.db.exists(
            "Sales Invoice Item",
            {"name": invoice_item, "parent": invoice.name},
        ):
            blockers.append(
                _(
                    "Sales Invoice Item link for Online Order row {0} is invalid."
                ).format(row.idx)
            )
    if not mapped_rows:
        blockers.append(
            _("No approved Online Order items are linked to the Sales Invoice Draft.")
        )

    gl_entries = frappe.db.count(
        "GL Entry",
        {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
    )
    stock_entries = frappe.db.count(
        "Stock Ledger Entry",
        {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
    )
    if gl_entries:
        blockers.append(_("A Draft Sales Invoice must not create GL Entries."))
    if stock_entries:
        blockers.append(
            _("A non-stock Draft Sales Invoice must not create Stock Ledger Entries.")
        )
    return list(dict.fromkeys(blockers))


def _sales_invoice_draft_context(order) -> dict[str, Any]:
    invoice = _active_sales_invoice(order)
    creation_blockers = _sales_invoice_creation_blockers(order)
    integrity_blockers = (
        _post_conversion_integrity_blockers(order, invoice) if invoice else []
    )
    invoice_state: dict[str, Any] = {}
    if invoice:
        invoice_state = {
            "name": invoice.name,
            "docstatus": cint(invoice.docstatus),
            "update_stock": cint(invoice.update_stock),
            "is_pos": cint(invoice.is_pos),
            "is_return": cint(invoice.is_return),
            "customer": invoice.customer or "",
            "company": invoice.company or "",
            "currency": invoice.currency or "",
            "customer_address": invoice.customer_address or "",
            "shipping_address_name": invoice.shipping_address_name or "",
            "grand_total": flt(invoice.grand_total),
            "outstanding_amount": flt(invoice.outstanding_amount),
            "custom_online_order": invoice.get("custom_online_order") or "",
            "custom_delivery_zone": invoice.get("custom_delivery_zone") or "",
            "custom_delivery_fee": flt(invoice.get("custom_delivery_fee")),
            "item_count": len(invoice.items or []),
            "gl_entry_count": frappe.db.count(
                "GL Entry",
                {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
            ),
            "stock_ledger_entry_count": frappe.db.count(
                "Stock Ledger Entry",
                {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
            ),
        }

    return {
        **_state_snapshot(order),
        "conversion_execution_status": getattr(
            order, "custom_conversion_execution_status", "Pending"
        )
        or "Pending",
        "post_conversion_integrity_status": getattr(
            order, "custom_post_conversion_integrity_status", "Pending"
        )
        or "Pending",
        "invoice": invoice_state,
        "creation_blockers": creation_blockers,
        "can_create_draft": cint(not creation_blockers and not invoice),
        "integrity_blockers": integrity_blockers,
        "post_conversion_ready": cint(bool(invoice) and not integrity_blockers),
        "controlled_sales_invoice_draft_creation": 1,
        "submits_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
    }


@frappe.whitelist()
def get_sales_invoice_draft_context(
    online_order: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "read")
    return _sales_invoice_draft_context(order)


@frappe.whitelist(methods=["POST"])
def create_controlled_sales_invoice_draft(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()

    existing = _active_sales_invoice(order)
    if existing:
        result = _sales_invoice_draft_context(order)
        result["created"] = 0
        result["idempotent_replay"] = 1
        return result

    blockers = _sales_invoice_creation_blockers(order)
    if blockers:
        frappe.throw(
            _("Controlled Sales Invoice Draft creation is blocked: {0}").format(
                " | ".join(blockers)
            )
        )

    from pharma_erp.pharma_erp.doctype.online_order.online_order import (
        create_sales_invoice_draft,
    )

    creation_result = create_sales_invoice_draft(order.name)
    order.reload()
    invoice = _active_sales_invoice(order)
    integrity_blockers = _post_conversion_integrity_blockers(order, invoice)
    if integrity_blockers:
        frappe.throw(
            _(
                "Created Sales Invoice Draft failed controlled integrity checks: {0}"
            ).format(" | ".join(integrity_blockers))
        )

    _set_if_has(order, "custom_conversion_execution_status", "Draft Created")
    _set_if_has(
        order,
        "custom_conversion_execution_notes",
        _clean_text(notes, 1000),
    )
    _set_if_has(order, "custom_conversion_executed_by", frappe.session.user)
    _set_if_has(order, "custom_conversion_executed_at", now_datetime())

    # The integrity checks have already passed immediately after draft creation.
    # Persist that verified state automatically so the pharmacist does not need
    # a second operational click before moving to submit-readiness review.
    automatic_integrity_note = _("Automatically verified during controlled draft creation.")
    automatic_integrity_checked_at = now_datetime()
    _set_if_has(order, "custom_post_conversion_integrity_status", "Ready")
    _set_if_has(
        order,
        "custom_post_conversion_integrity_notes",
        automatic_integrity_note,
    )
    _set_if_has(order, "custom_post_conversion_checked_by", frappe.session.user)
    _set_if_has(
        order,
        "custom_post_conversion_checked_at",
        automatic_integrity_checked_at,
    )
    _set_if_has(order, "custom_submit_readiness_status", "Pending")
    _set_if_has(order, "custom_submit_readiness_notes", "")
    _set_if_has(order, "custom_submit_readiness_checked_by", None)
    _set_if_has(order, "custom_submit_readiness_checked_at", None)
    _set_if_has(order, "custom_submit_execution_status", "Pending")
    _set_if_has(order, "custom_submit_execution_notes", "")
    _set_if_has(order, "custom_submitted_by", None)
    _set_if_has(order, "custom_submitted_at", None)
    order.save(ignore_permissions=True)

    _audit_comment(
        order,
        _("Controlled Sales Invoice Draft Creation"),
        {
            "sales_invoice": order.sales_invoice,
            "docstatus": cint(invoice.docstatus),
            "update_stock": cint(invoice.update_stock),
            "grand_total": flt(invoice.grand_total),
            "online_order_total": flt(order.grand_total),
            "conversion_path": order.conversion_path,
            "created_by": frappe.session.user,
            "created_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "creates_sales_invoice_draft": 1,
            "automatic_post_conversion_integrity": 1,
            "post_conversion_integrity_status": "Ready",
            "submits_sales_invoice": 0,
            "creates_payment_entry": 0,
            "creates_gl_entries": 0,
            "creates_stock_entries": 0,
        },
    )
    _audit_comment(
        order,
        _("Controlled Post-Conversion Integrity Verification"),
        {
            "integrity_status": "Ready",
            "blockers": [],
            "sales_invoice": order.sales_invoice or "",
            "docstatus": cint(invoice.docstatus),
            "update_stock": cint(invoice.update_stock),
            "grand_total": flt(invoice.grand_total),
            "checked_by": frappe.session.user,
            "checked_at": automatic_integrity_checked_at,
            "notes": automatic_integrity_note,
            "automatic_verification": 1,
            "submits_sales_invoice": 0,
            "creates_payment_entry": 0,
            "creates_gl_entries": 0,
            "creates_stock_entries": 0,
        },
    )
    result = _sales_invoice_draft_context(order)
    result["created"] = 1
    result["idempotent_replay"] = 0
    result["underlying_result"] = creation_result
    return result


@frappe.whitelist(methods=["POST"])
def verify_post_conversion_integrity(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()
    invoice = _active_sales_invoice(order)
    blockers = _post_conversion_integrity_blockers(order, invoice)
    readiness = "Ready" if not blockers else "Blocked"

    _set_if_has(order, "custom_post_conversion_integrity_status", readiness)
    _set_if_has(
        order,
        "custom_post_conversion_integrity_notes",
        _clean_text(notes, 1000),
    )
    _set_if_has(order, "custom_post_conversion_checked_by", frappe.session.user)
    _set_if_has(order, "custom_post_conversion_checked_at", now_datetime())
    _set_if_has(order, "custom_submit_readiness_status", "Pending")
    _set_if_has(order, "custom_submit_readiness_notes", "")
    _set_if_has(order, "custom_submit_readiness_checked_by", None)
    _set_if_has(order, "custom_submit_readiness_checked_at", None)
    _set_if_has(order, "custom_submit_execution_status", "Pending")
    _set_if_has(order, "custom_submit_execution_notes", "")
    _set_if_has(order, "custom_submitted_by", None)
    _set_if_has(order, "custom_submitted_at", None)
    order.save(ignore_permissions=True)

    _audit_comment(
        order,
        _("Controlled Post-Conversion Integrity Verification"),
        {
            "integrity_status": readiness,
            "blockers": blockers,
            "sales_invoice": order.sales_invoice or "",
            "docstatus": cint(invoice.docstatus) if invoice else None,
            "update_stock": cint(invoice.update_stock) if invoice else None,
            "grand_total": flt(invoice.grand_total) if invoice else 0,
            "checked_by": frappe.session.user,
            "checked_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "submits_sales_invoice": 0,
            "creates_payment_entry": 0,
            "creates_gl_entries": 0,
            "creates_stock_entries": 0,
        },
    )
    return _sales_invoice_draft_context(order)


def _submit_invoice_state(invoice) -> dict[str, Any]:
    if not invoice:
        return {}
    return {
        "name": invoice.name,
        "docstatus": cint(invoice.docstatus),
        "update_stock": cint(invoice.update_stock),
        "is_pos": cint(invoice.is_pos),
        "customer": invoice.customer or "",
        "company": invoice.company or "",
        "currency": invoice.currency or "",
        "grand_total": flt(invoice.grand_total),
        "outstanding_amount": flt(invoice.outstanding_amount),
        "posting_date": str(invoice.posting_date or ""),
        "posting_time": str(invoice.posting_time or ""),
        "due_date": str(invoice.due_date or ""),
        "set_posting_time": cint(invoice.get("set_posting_time")),
        "custom_online_order": invoice.get("custom_online_order") or "",
        "custom_delivery_shift": invoice.get("custom_delivery_shift") or "",
        "custom_pharmacy_shift": invoice.get("custom_pharmacy_shift") or "",
        "gl_entry_count": frappe.db.count(
            "GL Entry",
            {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
        ),
        "stock_ledger_entry_count": frappe.db.count(
            "Stock Ledger Entry",
            {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
        ),
    }


def _sales_invoice_submit_blockers(order, invoice=None) -> list[str]:
    blockers: list[str] = []
    invoice = invoice or _active_sales_invoice(order)
    if not invoice:
        return [_('An active linked Sales Invoice is required before submit.')]
    if order.sales_invoice != invoice.name:
        blockers.append(_('The Online Order active Sales Invoice link is inconsistent.'))
    if cint(invoice.docstatus) == 1:
        return blockers
    if cint(invoice.docstatus) != 0:
        blockers.append(_('The linked Sales Invoice must be Draft before controlled submit.'))
        return list(dict.fromkeys(blockers))
    if getattr(order, "custom_post_conversion_integrity_status", "Pending") != "Ready":
        blockers.append(_('Post-Conversion Integrity must be Ready before submit.'))
    if getattr(order, "custom_conversion_execution_status", "Pending") != "Draft Created":
        blockers.append(_('Controlled Conversion Execution must be Draft Created.'))
    try:
        validate_linked_online_order_invoice(invoice, method="submit_readiness")
    except frappe.ValidationError as exc:
        blockers.append(_clean_text(exc, 1000))

    if order.fulfilment_method in {"Home Delivery", "Pharmacy Pickup"}:
        active_shift = shift_finance._current_open_shift(invoice.company)
        if not active_shift:
            blockers.append(
                _(
                    'An open Pharmacy Shift is required before {0} invoice submit.'
                ).format(order.fulfilment_method)
            )
        else:
            active_shift_name = str(active_shift.name or "").strip()
            current_sales_shift = str(
                invoice.get("custom_pharmacy_shift") or ""
            ).strip()
            current_delivery_shift = str(
                invoice.get("custom_delivery_shift") or ""
            ).strip()

            if current_sales_shift and current_sales_shift != active_shift_name:
                blockers.append(
                    _(
                        'Sales Invoice is linked to Pharmacy Shift {0}, but the active shift is {1}.'
                    ).format(current_sales_shift, active_shift_name)
                )

            if order.fulfilment_method == "Home Delivery":
                if current_delivery_shift and current_delivery_shift != active_shift_name:
                    blockers.append(
                        _(
                            'Sales Invoice is linked to delivery shift {0}, but the active shift is {1}.'
                        ).format(current_delivery_shift, active_shift_name)
                    )
            elif current_delivery_shift:
                blockers.append(
                    _(
                        'Pharmacy Pickup Sales Invoice must not use Delivery Shift {0}.'
                    ).format(current_delivery_shift)
                )
    return list(dict.fromkeys(blockers))


def _prepare_controlled_submit_dates(invoice) -> dict[str, Any]:
    original_posting_date = str(invoice.posting_date or "")
    original_due_date = str(invoice.due_date or "")
    original_set_posting_time = cint(invoice.get("set_posting_time"))

    effective_posting_date = getdate(
        invoice.posting_date
        if original_set_posting_time and invoice.posting_date
        else nowdate()
    )

    due_date_updated = False
    if not invoice.due_date or getdate(invoice.due_date) < effective_posting_date:
        invoice.due_date = effective_posting_date
        due_date_updated = True

    payment_schedule_rows_updated = 0
    for row in invoice.get("payment_schedule") or []:
        if not row.due_date or getdate(row.due_date) < effective_posting_date:
            row.due_date = effective_posting_date
            payment_schedule_rows_updated += 1

    return {
        "original_posting_date": original_posting_date,
        "original_due_date": original_due_date,
        "set_posting_time": original_set_posting_time,
        "effective_posting_date": str(effective_posting_date),
        "due_date_updated": cint(due_date_updated),
        "payment_schedule_rows_updated": payment_schedule_rows_updated,
    }


def _sales_invoice_submit_context(order) -> dict[str, Any]:
    invoice = _active_sales_invoice(order)
    blockers = _sales_invoice_submit_blockers(order, invoice)
    invoice_state = _submit_invoice_state(invoice)
    submitted = bool(invoice and cint(invoice.docstatus) == 1)
    active_shift = ""
    if invoice and order.fulfilment_method in {"Home Delivery", "Pharmacy Pickup"}:
        shift = shift_finance._current_open_shift(invoice.company)
        active_shift = str(shift.name or "") if shift else ""
    readiness = getattr(order, "custom_submit_readiness_status", "Pending") or "Pending"
    execution = getattr(order, "custom_submit_execution_status", "Pending") or "Pending"
    return {
        **_state_snapshot(order),
        "invoice": invoice_state,
        "submit_blockers": blockers,
        "submit_readiness_status": readiness,
        "submit_execution_status": execution,
        "active_pharmacy_shift": active_shift,
        "can_verify_submit_readiness": cint(bool(invoice) and not submitted),
        "can_submit": cint(
            bool(invoice)
            and not submitted
            and not blockers
            and readiness == "Ready"
        ),
        "already_submitted": cint(submitted),
        "controlled_sales_invoice_submit": 1,
        "submits_sales_invoice": 1,
        "creates_payment_entry": 0,
        "creates_gl_entries": 1,
        "creates_stock_entries": 0,
    }


@frappe.whitelist()
def get_sales_invoice_submit_context(
    online_order: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "read")
    return _sales_invoice_submit_context(order)


@frappe.whitelist(methods=["POST"])
def verify_sales_invoice_submit_readiness(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()
    invoice = _active_sales_invoice(order)
    blockers = _sales_invoice_submit_blockers(order, invoice)
    readiness = "Ready" if invoice and cint(invoice.docstatus) == 0 and not blockers else "Blocked"

    _set_if_has(order, "custom_submit_readiness_status", readiness)
    _set_if_has(order, "custom_submit_readiness_notes", _clean_text(notes, 1000))
    _set_if_has(order, "custom_submit_readiness_checked_by", frappe.session.user)
    _set_if_has(order, "custom_submit_readiness_checked_at", now_datetime())
    _set_if_has(order, "custom_submit_execution_status", "Pending")
    _set_if_has(order, "custom_submit_execution_notes", "")
    _set_if_has(order, "custom_submitted_by", None)
    _set_if_has(order, "custom_submitted_at", None)
    order.save(ignore_permissions=True)

    _audit_comment(
        order,
        _("Controlled Sales Invoice Submit Readiness"),
        {
            "readiness_status": readiness,
            "blockers": blockers,
            "sales_invoice": invoice.name if invoice else "",
            "docstatus": cint(invoice.docstatus) if invoice else None,
            "update_stock": cint(invoice.update_stock) if invoice else None,
            "active_pharmacy_shift": (
                _sales_invoice_submit_context(order).get("active_pharmacy_shift") or ""
            ),
            "checked_by": frappe.session.user,
            "checked_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "submits_sales_invoice": 0,
            "creates_payment_entry": 0,
            "creates_gl_entries": 0,
            "creates_stock_entries": 0,
        },
    )
    return _sales_invoice_submit_context(order)


@frappe.whitelist(methods=["POST"])
def submit_controlled_sales_invoice(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()
    invoice = _active_sales_invoice(order)
    if invoice and cint(invoice.docstatus) == 1:
        result = _sales_invoice_submit_context(order)
        result["submitted"] = 0
        result["idempotent_replay"] = 1
        return result
    if not invoice:
        frappe.throw(_('An active linked Sales Invoice Draft is required.'))
    if getattr(order, "custom_submit_readiness_status", "Pending") != "Ready":
        frappe.throw(_('Verify Controlled Sales Invoice Submit Readiness first.'))

    blockers = _sales_invoice_submit_blockers(order, invoice)
    if blockers:
        _set_if_has(order, "custom_submit_execution_status", "Blocked")
        _set_if_has(order, "custom_submit_execution_notes", _clean_text(notes, 1000))
        order.save(ignore_permissions=True)
        frappe.throw(
            _('Controlled Sales Invoice submit is blocked: {0}').format(
                " | ".join(blockers)
            )
        )

    payment_entry_count_before = frappe.db.count("Payment Entry")
    _set_if_has(order, "custom_submit_execution_notes", _clean_text(notes, 1000))
    order.save(ignore_permissions=True)

    submit_date_context = _prepare_controlled_submit_dates(invoice)
    invoice.flags.controlled_online_order_submit = True
    invoice.submit()
    invoice.reload()
    order.reload()

    invoice_gl_entries = frappe.db.count(
        "GL Entry",
        {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
    )
    invoice_stock_entries = frappe.db.count(
        "Stock Ledger Entry",
        {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
    )
    payment_entry_count_after = frappe.db.count("Payment Entry")

    if cint(invoice.docstatus) != 1:
        frappe.throw(_('Controlled Sales Invoice submit did not complete.'))
    if getdate(invoice.due_date) < getdate(invoice.posting_date):
        frappe.throw(
            _('Submitted Sales Invoice Due Date is before its Posting Date.')
        )
    if cint(invoice.update_stock):
        frappe.throw(_('Submitted Online Order Sales Invoice changed Update Stock.'))
    if invoice_stock_entries:
        frappe.throw(_('Controlled Sales Invoice submit created unexpected Stock Ledger Entries.'))
    if flt(invoice.grand_total) > POST_CONVERSION_TOLERANCE and not invoice_gl_entries:
        frappe.throw(_('Submitted Sales Invoice did not create the expected GL Entries.'))
    if payment_entry_count_before != payment_entry_count_after:
        frappe.throw(_('Controlled Sales Invoice submit created an unexpected Payment Entry.'))

    if order.fulfilment_method in {"Home Delivery", "Pharmacy Pickup"}:
        active_shift = shift_finance._current_open_shift(invoice.company)
        active_shift_name = str(active_shift.name or "").strip() if active_shift else ""
        invoice_sales_shift = str(
            invoice.get("custom_pharmacy_shift") or ""
        ).strip()
        invoice_delivery_shift = str(
            invoice.get("custom_delivery_shift") or ""
        ).strip()
        if not active_shift_name or invoice_sales_shift != active_shift_name:
            frappe.throw(
                _('Submitted Online Order Sales Invoice is not linked to the active Pharmacy Shift.')
            )
        if order.fulfilment_method == "Home Delivery":
            if invoice_delivery_shift != active_shift_name:
                frappe.throw(
                    _('Submitted Home Delivery Sales Invoice is not linked to the active Delivery Shift.')
                )
        elif invoice_delivery_shift:
            frappe.throw(
                _('Submitted Pharmacy Pickup Sales Invoice must not have a Delivery Shift.')
            )

    _set_if_has(order, "custom_submit_execution_status", "Submitted")
    _set_if_has(order, "custom_submit_execution_notes", _clean_text(notes, 1000))
    _set_if_has(order, "custom_submitted_by", frappe.session.user)
    _set_if_has(order, "custom_submitted_at", now_datetime())
    order.save(ignore_permissions=True)

    _audit_comment(
        order,
        _("Controlled Sales Invoice Submit"),
        {
            "sales_invoice": invoice.name,
            "docstatus": cint(invoice.docstatus),
            "update_stock": cint(invoice.update_stock),
            "online_order_status": order.status,
            "invoice_gl_entries": invoice_gl_entries,
            "invoice_stock_entries": invoice_stock_entries,
            "payment_entries_created": payment_entry_count_after - payment_entry_count_before,
            "posting_date": str(invoice.posting_date or ""),
            "due_date": str(invoice.due_date or ""),
            "submit_date_guard": submit_date_context,
            "pharmacy_shift": invoice.get("custom_pharmacy_shift") or "",
            "delivery_shift": invoice.get("custom_delivery_shift") or "",
            "submitted_by": frappe.session.user,
            "submitted_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "submits_sales_invoice": 1,
            "creates_payment_entry": 0,
            "creates_gl_entries": 1,
            "creates_stock_entries": 0,
        },
    )
    result = _sales_invoice_submit_context(order)
    result["submitted"] = 1
    result["idempotent_replay"] = 0
    return result


def _delivery_invoice_state(invoice) -> dict[str, Any]:
    if not invoice:
        return {}
    return {
        "name": invoice.name,
        "docstatus": cint(invoice.docstatus),
        "status": invoice.status or "",
        "update_stock": cint(invoice.update_stock),
        "is_pos": cint(invoice.is_pos),
        "company": invoice.company or "",
        "currency": invoice.currency or "",
        "grand_total": flt(invoice.grand_total),
        "outstanding_amount": max(0, flt(invoice.outstanding_amount)),
        "custom_online_order": invoice.get("custom_online_order") or "",
        "custom_delivery_status": invoice.get("custom_delivery_status") or "",
        "custom_delivery_boy": invoice.get("custom_delivery_boy") or "",
        "custom_delivery_trip": invoice.get("custom_delivery_trip") or "",
        "custom_current_delivery_attempt": invoice.get("custom_current_delivery_attempt") or "",
        "custom_departure_time": invoice.get("custom_departure_time"),
        "custom_delivery_time": invoice.get("custom_delivery_time"),
        "custom_collection_verification_status": (
            invoice.get("custom_collection_verification_status") or ""
        ),
        "custom_confirmed_customer_payment_method": (
            invoice.get("custom_confirmed_customer_payment_method") or ""
        ),
        "custom_collection_payment_entry": (
            invoice.get("custom_collection_payment_entry") or ""
        ),
        "custom_prepaid_payment_entry": (
            invoice.get("custom_prepaid_payment_entry") or ""
        ),
        "custom_pharmacy_shift": invoice.get("custom_pharmacy_shift") or "",
        "custom_delivery_shift": invoice.get("custom_delivery_shift") or "",
        "gl_entry_count": frappe.db.count(
            "GL Entry",
            {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
        ),
        "stock_ledger_entry_count": frappe.db.count(
            "Stock Ledger Entry",
            {"voucher_type": "Sales Invoice", "voucher_no": invoice.name},
        ),
    }


def _delivery_sync_blockers(order, invoice=None) -> list[str]:
    blockers: list[str] = []
    if order.fulfilment_method != "Home Delivery":
        blockers.append(_("Controlled delivery sync is only valid for Home Delivery orders."))
        return blockers
    invoice = invoice or _active_sales_invoice(order)
    if not invoice:
        blockers.append(_("A linked active Sales Invoice is required for delivery sync."))
        return blockers
    if order.sales_invoice != invoice.name:
        blockers.append(_("The Online Order Sales Invoice link is inconsistent."))
    if cint(invoice.docstatus) != 1:
        blockers.append(_("The linked Sales Invoice must be submitted before delivery sync."))
    if getattr(order, "custom_submit_execution_status", "Pending") != "Submitted":
        blockers.append(_("Controlled Sales Invoice Submit must be Submitted before delivery sync."))
    if invoice.get("custom_online_order") != order.name:
        blockers.append(_("The linked Sales Invoice does not point back to this Online Order."))
    return list(dict.fromkeys(blockers))


def _delivery_completion_blockers(order, invoice=None) -> list[str]:
    blockers = _delivery_sync_blockers(order, invoice)
    invoice = invoice or _active_sales_invoice(order)
    if blockers or not invoice:
        return blockers
    if order.status == "Completed":
        return []
    if order.status == "Returned":
        blockers.append(_("Returned deliveries require the controlled return workflow, not completion."))
        return list(dict.fromkeys(blockers))
    if order.status != "Delivered":
        blockers.append(_("Online Order must be Delivered before final completion."))
    invoice_delivery_status = str(invoice.get("custom_delivery_status") or "").strip()
    if invoice_delivery_status != "Delivered":
        blockers.append(_("The linked Sales Invoice delivery status must be Delivered."))
    collection = _home_delivery_collection_state(order, invoice)
    if not collection["collection_ready"]:
        if collection["outstanding"] > PAYMENT_TOLERANCE:
            blockers.append(
                _("Delivery collection is incomplete. Remaining outstanding: {0}.").format(
                    collection["outstanding"]
                )
            )
        else:
            blockers.append(_("Delivery collection verification must be Confirmed before completion."))
    return list(dict.fromkeys(blockers))


def _delivery_execution_context(order) -> dict[str, Any]:
    invoice = _active_sales_invoice(order)
    sync_blockers = _delivery_sync_blockers(order, invoice)
    completion_blockers = _delivery_completion_blockers(order, invoice)
    collection = (
        _home_delivery_collection_state(order, invoice)
        if invoice and cint(invoice.docstatus) == 1 and order.fulfilment_method == "Home Delivery"
        else {
            "outstanding": 0.0,
            "grand_total": flt(order.grand_total),
            "collection_status": "",
            "confirmed_method": "",
            "payment_entry": "",
            "payment_entry_submitted": False,
            "payment_status": order.payment_status or "",
            "verified_amount": flt(order.verified_paid_amount),
            "no_collection": False,
            "collection_ready": False,
        }
    )
    completed = order.status == "Completed"
    completion_readiness = getattr(
        order,
        "custom_delivery_completion_readiness_status",
        "Pending",
    ) or "Pending"
    return {
        **_state_snapshot(order),
        "invoice": _delivery_invoice_state(invoice),
        "delivery_sync_blockers": sync_blockers,
        "delivery_completion_blockers": completion_blockers,
        "delivery_sync_status": getattr(order, "custom_delivery_sync_status", "Pending") or "Pending",
        "delivery_sync_notes": getattr(order, "custom_delivery_sync_notes", "") or "",
        "delivery_synced_by": getattr(order, "custom_delivery_synced_by", "") or "",
        "delivery_synced_at": getattr(order, "custom_delivery_synced_at", None),
        "delivery_completion_readiness_status": completion_readiness,
        "delivery_completion_readiness_notes": getattr(
            order,
            "custom_delivery_completion_readiness_notes",
            "",
        ) or "",
        "delivery_completion_checked_by": getattr(
            order,
            "custom_delivery_completion_checked_by",
            "",
        ) or "",
        "delivery_completion_checked_at": getattr(
            order,
            "custom_delivery_completion_checked_at",
            None,
        ),
        "collection": collection,
        "can_sync_delivery": cint(bool(invoice) and not sync_blockers and not completed),
        "can_verify_delivery_completion": cint(bool(invoice) and not completed),
        "can_complete_delivery": cint(
            bool(invoice)
            and not completed
            and not completion_blockers
            and completion_readiness == "Ready"
        ),
        "already_completed": cint(completed),
        "uses_delivery_management": 1,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "submits_sales_invoice": 0,
    }


@frappe.whitelist()
def get_delivery_execution_context(
    online_order: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "read")
    return _delivery_execution_context(order)


@frappe.whitelist(methods=["POST"])
def sync_controlled_delivery_execution(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()
    invoice = _active_sales_invoice(order)
    blockers = _delivery_sync_blockers(order, invoice)
    if blockers:
        _set_if_has(order, "custom_delivery_sync_status", "Blocked")
        _set_if_has(order, "custom_delivery_sync_notes", _clean_text(notes, 1000))
        _set_if_has(order, "custom_delivery_synced_by", frappe.session.user)
        _set_if_has(order, "custom_delivery_synced_at", now_datetime())
        order.save(ignore_permissions=True)
        _audit_comment(
            order,
            _("Controlled Delivery & Collection Synchronization"),
            {
                "sync_status": "Blocked",
                "blockers": blockers,
                "sales_invoice": invoice.name if invoice else "",
                "notes": _clean_text(notes, 1000),
                "creates_payment_entry": 0,
                "creates_gl_entries": 0,
                "creates_stock_entries": 0,
            },
        )
        return _delivery_execution_context(order)

    before = (
        order.status,
        order.payment_status,
        flt(order.verified_paid_amount),
        str(order.payment_entry or ""),
        str(getattr(order, "delivery_status_snapshot", "") or ""),
        str(getattr(order, "delivery_boy", "") or ""),
        str(getattr(order, "delivery_trip", "") or ""),
        str(getattr(order, "delivery_attempt", "") or ""),
    )
    _sync_home_delivery_order_from_invoice(order, invoice, save=False)
    after = (
        order.status,
        order.payment_status,
        flt(order.verified_paid_amount),
        str(order.payment_entry or ""),
        str(getattr(order, "delivery_status_snapshot", "") or ""),
        str(getattr(order, "delivery_boy", "") or ""),
        str(getattr(order, "delivery_trip", "") or ""),
        str(getattr(order, "delivery_attempt", "") or ""),
    )
    already_synchronized = (
        before == after
        and getattr(order, "custom_delivery_sync_status", "Pending") == "Synchronized"
    )
    if already_synchronized:
        result = _delivery_execution_context(order)
        result["synchronized"] = 0
        result["idempotent_replay"] = 1
        return result

    _set_if_has(order, "custom_delivery_sync_status", "Synchronized")
    _set_if_has(order, "custom_delivery_sync_notes", _clean_text(notes, 1000))
    _set_if_has(order, "custom_delivery_synced_by", frappe.session.user)
    _set_if_has(order, "custom_delivery_synced_at", now_datetime())
    _set_if_has(order, "custom_delivery_completion_readiness_status", "Pending")
    _set_if_has(order, "custom_delivery_completion_readiness_notes", "")
    _set_if_has(order, "custom_delivery_completion_checked_by", None)
    _set_if_has(order, "custom_delivery_completion_checked_at", None)
    order.save(ignore_permissions=True)

    collection = _home_delivery_collection_state(order, invoice)
    _audit_comment(
        order,
        _("Controlled Delivery & Collection Synchronization"),
        {
            "sync_status": "Synchronized",
            "before_order_status": before[0],
            "online_order_status": order.status,
            "invoice_delivery_status": invoice.get("custom_delivery_status") or "",
            "payment_status": order.payment_status,
            "collection_status": collection["collection_status"],
            "collection_ready": cint(collection["collection_ready"]),
            "outstanding": flt(collection["outstanding"]),
            "sales_invoice": invoice.name,
            "delivery_shift": invoice.get("custom_delivery_shift") or "",
            "delivery_trip": invoice.get("custom_delivery_trip") or "",
            "delivery_boy": invoice.get("custom_delivery_boy") or "",
            "notes": _clean_text(notes, 1000),
            "creates_payment_entry": 0,
            "creates_gl_entries": 0,
            "creates_stock_entries": 0,
        },
    )
    result = _delivery_execution_context(order)
    result["synchronized"] = 1
    result["idempotent_replay"] = 0
    return result


@frappe.whitelist(methods=["POST"])
def verify_delivery_completion_readiness(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()
    invoice = _active_sales_invoice(order)
    sync_blockers = _delivery_sync_blockers(order, invoice)
    if not sync_blockers and invoice:
        _sync_home_delivery_order_from_invoice(order, invoice, save=False)
    blockers = _delivery_completion_blockers(order, invoice)
    readiness = "Ready" if not blockers and order.status == "Delivered" else "Blocked"

    _set_if_has(order, "custom_delivery_sync_status", "Synchronized" if not sync_blockers else "Blocked")
    _set_if_has(order, "custom_delivery_sync_notes", _clean_text(notes, 1000))
    _set_if_has(order, "custom_delivery_synced_by", frappe.session.user)
    _set_if_has(order, "custom_delivery_synced_at", now_datetime())
    _set_if_has(order, "custom_delivery_completion_readiness_status", readiness)
    _set_if_has(
        order,
        "custom_delivery_completion_readiness_notes",
        _clean_text(notes, 1000),
    )
    _set_if_has(order, "custom_delivery_completion_checked_by", frappe.session.user)
    _set_if_has(order, "custom_delivery_completion_checked_at", now_datetime())
    order.save(ignore_permissions=True)

    collection = (
        _home_delivery_collection_state(order, invoice)
        if invoice and cint(invoice.docstatus) == 1
        else {}
    )
    _audit_comment(
        order,
        _("Controlled Delivery Completion Readiness"),
        {
            "readiness_status": readiness,
            "blockers": blockers,
            "online_order_status": order.status,
            "invoice_delivery_status": invoice.get("custom_delivery_status") if invoice else "",
            "collection_status": collection.get("collection_status", ""),
            "collection_ready": cint(collection.get("collection_ready", False)),
            "outstanding": flt(collection.get("outstanding", 0)),
            "sales_invoice": invoice.name if invoice else "",
            "checked_by": frappe.session.user,
            "checked_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "creates_payment_entry": 0,
            "creates_gl_entries": 0,
            "creates_stock_entries": 0,
        },
    )
    return _delivery_execution_context(order)


@frappe.whitelist(methods=["POST"])
def complete_controlled_home_delivery(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()
    if order.status == "Completed":
        result = _delivery_execution_context(order)
        result["completed"] = 0
        result["idempotent_replay"] = 1
        return result

    invoice = _active_sales_invoice(order)
    if getattr(order, "custom_delivery_completion_readiness_status", "Pending") != "Ready":
        frappe.throw(_("Verify Controlled Delivery Completion Readiness first."))
    blockers = _delivery_completion_blockers(order, invoice)
    if blockers:
        frappe.throw("<br>".join(blockers))

    completion_result = complete_home_delivery(
        order.name,
        completion_notes=_clean_text(notes, 1000),
    )
    order.reload()
    _set_if_has(order, "custom_delivery_sync_status", "Synchronized")
    _set_if_has(order, "custom_delivery_sync_notes", _clean_text(notes, 1000))
    _set_if_has(order, "custom_delivery_synced_by", frappe.session.user)
    _set_if_has(order, "custom_delivery_synced_at", now_datetime())
    order.save(ignore_permissions=True)

    invoice = _active_sales_invoice(order)
    collection = _home_delivery_collection_state(order, invoice) if invoice else {}
    _audit_comment(
        order,
        _("Controlled Home Delivery Completion"),
        {
            "online_order_status": order.status,
            "sales_invoice": invoice.name if invoice else "",
            "invoice_delivery_status": invoice.get("custom_delivery_status") if invoice else "",
            "payment_status": order.payment_status,
            "collection_status": collection.get("collection_status", ""),
            "collection_ready": cint(collection.get("collection_ready", False)),
            "outstanding": flt(collection.get("outstanding", 0)),
            "completed_by": frappe.session.user,
            "completed_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "creates_payment_entry": 0,
            "creates_gl_entries": 0,
            "creates_stock_entries": 0,
        },
    )
    result = _delivery_execution_context(order)
    result["completed"] = 1
    result["idempotent_replay"] = 0
    result["underlying_result"] = completion_result
    return result
