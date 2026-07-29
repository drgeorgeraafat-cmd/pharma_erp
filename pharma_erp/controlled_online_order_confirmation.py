from __future__ import annotations

import html
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, strip_html

from pharma_erp.controlled_online_order_review import _snapshot as _review_snapshot

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
    _set_if_has(order, "custom_post_conversion_integrity_status", "Pending")
    _set_if_has(order, "custom_post_conversion_integrity_notes", "")
    _set_if_has(order, "custom_post_conversion_checked_by", None)
    _set_if_has(order, "custom_post_conversion_checked_at", None)
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
