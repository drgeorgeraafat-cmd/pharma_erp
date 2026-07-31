from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from pharma_erp.pharma_erp.doctype.online_order.online_order import (
    _home_delivery_collection_state,
    _sync_home_delivery_order_from_invoice,
)

PAYMENT_TOLERANCE = 0.01
EXACT_PICKUP_AMOUNT_GUARD_VERSION = "v0.8.0-step2d2"
HOME_DELIVERY_PAYMENT_INFERENCE_VERSION = "v0.8.0-step2e"


def _online_order_name(doc) -> str:
    direct = str(doc.get("custom_online_order") or "").strip()
    if direct:
        return direct

    order_names = set()
    for row in doc.get("references") or []:
        if row.reference_doctype != "Sales Invoice" or flt(row.allocated_amount) <= 0:
            continue
        order_name = str(
            frappe.db.get_value(
                "Sales Invoice",
                row.reference_name,
                "custom_online_order",
            )
            or ""
        ).strip()
        if order_name:
            order_names.add(order_name)

    if len(order_names) == 1:
        return next(iter(order_names))
    return ""


def _get_order(doc):
    order_name = _online_order_name(doc)
    if not order_name:
        return None
    if not frappe.db.exists("Online Order", order_name):
        frappe.throw(_("Linked Online Order {0} was not found.").format(order_name))
    return frappe.get_doc("Online Order", order_name)


def _allocated_invoice_rows(doc, invoice_name):
    return [
        row
        for row in doc.references
        if row.reference_doctype == "Sales Invoice"
        and row.reference_name == invoice_name
        and flt(row.allocated_amount) > 0
    ]


def _assert_controlled_reference(doc, order):
    if not order.sales_invoice:
        frappe.throw(_("Online Order has no active Sales Invoice."))
    if cint(frappe.db.get_value("Sales Invoice", order.sales_invoice, "docstatus")) != 1:
        frappe.throw(_("The linked Sales Invoice must be submitted."))

    allocated_rows = [row for row in doc.references if flt(row.allocated_amount) > 0]
    matching_rows = _allocated_invoice_rows(doc, order.sales_invoice)
    if len(allocated_rows) != 1 or len(matching_rows) != 1:
        frappe.throw(
            _(
                "Online Order pickup collection Payment Entry must allocate exactly one reference: Sales Invoice {0}."
            ).format(order.sales_invoice)
        )


def _assert_exact_collection_amount(doc, order):
    if cint(doc.docstatus) != 0:
        return

    invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)
    current_outstanding = max(0, flt(invoice.outstanding_amount))
    if current_outstanding <= PAYMENT_TOLERANCE:
        frappe.throw(_("The linked Sales Invoice has no outstanding amount to collect."))

    matching_rows = _allocated_invoice_rows(doc, order.sales_invoice)
    if len(matching_rows) != 1:
        frappe.throw(
            _("Pickup collection must allocate exactly one row to Sales Invoice {0}.").format(
                order.sales_invoice
            )
        )

    allocated_amount = flt(matching_rows[0].allocated_amount)
    paid_amount = flt(doc.paid_amount)
    total_allocated_amount = flt(doc.total_allocated_amount)
    unallocated_amount = flt(doc.unallocated_amount)

    if abs(allocated_amount - current_outstanding) > PAYMENT_TOLERANCE:
        frappe.throw(
            _("Pickup collection allocated amount must equal the current Sales Invoice outstanding amount: {0}.").format(
                current_outstanding
            )
        )
    if abs(paid_amount - current_outstanding) > PAYMENT_TOLERANCE:
        frappe.throw(
            _("Pickup collection paid amount must equal the current Sales Invoice outstanding amount: {0}.").format(
                current_outstanding
            )
        )
    if abs(total_allocated_amount - current_outstanding) > PAYMENT_TOLERANCE:
        frappe.throw(
            _("Pickup collection total allocated amount must equal the current Sales Invoice outstanding amount: {0}.").format(
                current_outstanding
            )
        )
    if abs(unallocated_amount) > PAYMENT_TOLERANCE:
        frappe.throw(_("Pickup collection cannot keep an unallocated amount."))


def _payment_method_label(mode_of_payment: str) -> str:
    value = str(mode_of_payment or "").strip().lower().replace("_", " ")
    if "cash" in value:
        return "Cash"
    if "insta" in value:
        return "InstaPay"
    if "wallet" in value:
        return "Mobile Wallet"
    if "card" in value:
        return "Card"
    if "bank" in value or "transfer" in value:
        return "Bank Transfer"
    return ""


def _set_invoice_collection_fields(invoice_name, values):
    meta = frappe.get_meta("Sales Invoice")
    updates = {key: value for key, value in values.items() if meta.has_field(key)}
    if updates:
        frappe.db.set_value("Sales Invoice", invoice_name, updates, update_modified=False)


def _validate_home_delivery_payment(doc, order):
    prepaid_stage = bool(
        order.payment_timing in {"Prepaid", "Partially Prepaid"}
        and order.status not in {"Delivered", "Returned", "Completed"}
    )
    if order.status not in {"Delivered", "Completed"} and not prepaid_stage:
        frappe.throw(
            _("Home Delivery collection can only be posted after the order is Delivered.")
        )
    if doc.payment_type != "Receive":
        frappe.throw(_("Home Delivery collection Payment Entry must use Payment Type Receive."))
    if doc.party_type != "Customer" or doc.party != order.customer:
        frappe.throw(
            _("Home Delivery collection customer must match the Online Order customer.")
        )
    if doc.company != order.company:
        frappe.throw(
            _("Home Delivery collection company must match the Online Order company.")
        )
    if not order.sales_invoice:
        frappe.throw(_("Online Order has no active Sales Invoice."))
    if cint(frappe.db.get_value("Sales Invoice", order.sales_invoice, "docstatus")) != 1:
        frappe.throw(_("The linked Sales Invoice must be submitted."))
    if not _allocated_invoice_rows(doc, order.sales_invoice):
        frappe.throw(
            _("Home Delivery collection must allocate an amount to Sales Invoice {0}.").format(
                order.sales_invoice
            )
        )


def validate_linked_online_order_payment(doc, method=None):
    order = _get_order(doc)
    if not order:
        return

    if doc.meta.has_field("custom_online_order") and not doc.get("custom_online_order"):
        doc.custom_online_order = order.name

    if order.fulfilment_method == "Home Delivery":
        _validate_home_delivery_payment(doc, order)
        return

    if order.fulfilment_method != "Pharmacy Pickup":
        frappe.throw(_("Unsupported Online Order fulfilment method for collection."))
    if order.status not in {"Ready for Pickup", "Completed"}:
        frappe.throw(_("Online Order must be Ready for Pickup before collection."))
    if doc.payment_type != "Receive":
        frappe.throw(_("Pickup collection Payment Entry must use Payment Type Receive."))
    if doc.party_type != "Customer" or doc.party != order.customer:
        frappe.throw(_("Pickup collection Payment Entry customer must match the Online Order customer."))
    if doc.company != order.company:
        frappe.throw(_("Pickup collection Payment Entry company must match the Online Order company."))

    _assert_controlled_reference(doc, order)
    _assert_exact_collection_amount(doc, order)

    from pharma_erp.pharma_erp import payment_card_management as shift_finance

    active_shift = shift_finance._current_open_shift(order.company)
    if not active_shift:
        frappe.throw(
            _("An open Pharmacy Shift is required before pickup collection submit.")
        )
    active_shift_name = str(active_shift.name or "").strip()
    payment_shift = str(doc.get("custom_pharmacy_shift") or "").strip()
    delivery_shift = str(doc.get("custom_delivery_shift") or "").strip()
    if payment_shift != active_shift_name:
        frappe.throw(
            _(
                "Pickup Payment Entry must be linked to the active Pharmacy Shift {0}."
            ).format(active_shift_name)
        )

    # Older Payment Entry shift normalization may mirror the canonical pharmacy
    # shift into the legacy Delivery Shift field while validate hooks run.
    # Pharmacy Pickup never owns a delivery shift, so canonicalize the field
    # back to empty at the final Online Order validation boundary.
    if delivery_shift and doc.meta.has_field("custom_delivery_shift"):
        doc.custom_delivery_shift = None
        delivery_shift = ""

    if delivery_shift:
        frappe.throw(
            _(
                "Pickup Payment Entry must not use Delivery Shift {0}."
            ).format(delivery_shift)
        )

    if order.payment_entry and order.payment_entry != doc.name:
        linked_status = cint(
            frappe.db.get_value("Payment Entry", order.payment_entry, "docstatus")
        )
        if linked_status < 2:
            frappe.throw(
                _("Online Order is already linked to active Payment Entry {0}.").format(
                    order.payment_entry
                )
            )


def on_submit_linked_online_order_payment(doc, method=None):
    order = _get_order(doc)
    if not order:
        return

    validate_linked_online_order_payment(doc, method)

    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()

    invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)

    if order.fulfilment_method == "Home Delivery":
        order.payment_entry = doc.name
        result = _sync_home_delivery_order_from_invoice(order, invoice, save=True)
        order.add_comment(
            "Info",
            _(
                "Payment Entry {0} submitted for Home Delivery collection. Payment status: {1}."
            ).format(doc.name, result["payment_status"]),
        )
        return

    outstanding = max(0, flt(invoice.outstanding_amount))
    verified_amount = max(0, flt(invoice.grand_total) - outstanding)

    order.payment_entry = doc.name
    order.verified_paid_amount = verified_amount
    order.payment_status = "Verified" if outstanding <= PAYMENT_TOLERANCE else "Partially Verified"
    order.payment_verified_by = frappe.session.user
    order.payment_verified_at = now_datetime()
    order.save(ignore_permissions=True)

    invoice_values = {
        "custom_collection_payment_entry": doc.name,
        "custom_collection_verification_status": (
            "Confirmed" if outstanding <= PAYMENT_TOLERANCE else "Awaiting Confirmation"
        ),
        "custom_collection_received_by": "Pharmacy Direct",
        "custom_collection_confirmed_by": frappe.session.user,
        "custom_collection_confirmed_at": now_datetime(),
    }
    payment_method = _payment_method_label(doc.mode_of_payment)
    if payment_method:
        invoice_values["custom_confirmed_customer_payment_method"] = payment_method
    _set_invoice_collection_fields(invoice.name, invoice_values)

    order.add_comment(
        "Info",
        _(
            "Payment Entry {0} submitted for pickup collection. Remaining Sales Invoice outstanding: {1}."
        ).format(doc.name, outstanding),
    )


def before_cancel_linked_online_order_payment(doc, method=None):
    order = _get_order(doc)
    if not order:
        return
    if order.status == "Completed":
        frappe.throw(
            _(
                "Online Order collection Payment Entry cannot be cancelled after the Online Order is Completed. Use the controlled return/reversal process."
            )
        )


def on_cancel_linked_online_order_payment(doc, method=None):
    order = _get_order(doc)
    if not order:
        return

    invoice = frappe.get_doc("Sales Invoice", order.sales_invoice) if order.sales_invoice else None

    if order.fulfilment_method == "Home Delivery":
        if order.payment_entry == doc.name:
            order.payment_entry = None
        if invoice and invoice.get("custom_collection_payment_entry") == doc.name:
            _set_invoice_collection_fields(
                invoice.name,
                {
                    "custom_collection_payment_entry": None,
                    "custom_collection_verification_status": "Awaiting Confirmation",
                    "custom_collection_confirmed_by": None,
                    "custom_collection_confirmed_at": None,
                },
            )
            invoice.reload()
        if invoice:
            _sync_home_delivery_order_from_invoice(order, invoice, save=True)
        else:
            order.payment_status = "Pending Collection"
            order.verified_paid_amount = 0
            order.payment_verified_by = None
            order.payment_verified_at = None
            order.save(ignore_permissions=True)
        order.add_comment(
            "Info",
            _("Payment Entry {0} was cancelled; Home Delivery collection was refreshed.").format(
                doc.name
            ),
        )
        return

    outstanding = max(0, flt(invoice.outstanding_amount)) if invoice else flt(order.grand_total)
    verified_amount = max(0, flt(order.grand_total) - outstanding)

    if order.payment_entry == doc.name:
        order.payment_entry = None
    order.verified_paid_amount = verified_amount
    if order.payment_timing == "No Collection Required":
        order.payment_status = "No Collection Required"
    elif verified_amount > PAYMENT_TOLERANCE:
        order.payment_status = "Partially Verified"
    else:
        order.payment_status = "Pending Collection"
        order.payment_verified_by = None
        order.payment_verified_at = None
    order.save(ignore_permissions=True)

    if invoice:
        _set_invoice_collection_fields(
            invoice.name,
            {
                "custom_collection_payment_entry": None,
                "custom_collection_verification_status": "Awaiting Confirmation",
                "custom_collection_confirmed_by": None,
                "custom_collection_confirmed_at": None,
            },
        )

    order.add_comment(
        "Info",
        _("Payment Entry {0} was cancelled; pickup collection returned to pending.").format(
            doc.name
        ),
    )


def on_trash_linked_online_order_payment(doc, method=None):
    order = _get_order(doc)
    if not order:
        return
    if order.status == "Completed":
        frappe.throw(
            _("Online Order collection Payment Entry cannot be deleted after completion.")
        )

    if order.fulfilment_method == "Home Delivery":
        if order.payment_entry == doc.name:
            order.payment_entry = None
            order.payment_status = (
                "No Collection Required"
                if order.payment_timing == "No Collection Required"
                else "Pending Collection"
            )
            order.verified_paid_amount = 0
            order.payment_verified_by = None
            order.payment_verified_at = None
            order.save(ignore_permissions=True)
            order.add_comment(
                "Info",
                _("Home Delivery Payment Entry Draft {0} was deleted.").format(doc.name),
            )
        return

    if order.payment_entry == doc.name:
        order.payment_entry = None
        order.payment_status = (
            "No Collection Required"
            if order.payment_timing == "No Collection Required"
            else "Pending Collection"
        )
        order.save(ignore_permissions=True)
        if order.sales_invoice:
            _set_invoice_collection_fields(
                order.sales_invoice,
                {
                    "custom_collection_payment_entry": None,
                    "custom_collection_verification_status": "Awaiting Confirmation",
                },
            )
        order.add_comment(
            "Info",
            _("Pickup Payment Entry Draft {0} was deleted; collection returned to pending.").format(
                doc.name
            ),
        )
