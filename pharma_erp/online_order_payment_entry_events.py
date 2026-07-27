from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

PAYMENT_TOLERANCE = 0.01
EXACT_PICKUP_AMOUNT_GUARD_VERSION = "v0.8.0-step2d2"


def _online_order_name(doc) -> str:
    return str(doc.get("custom_online_order") or "").strip()


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


def validate_linked_online_order_payment(doc, method=None):
    order = _get_order(doc)
    if not order:
        return

    if order.fulfilment_method != "Pharmacy Pickup":
        frappe.throw(_("Pickup collection Payment Entries are only valid for Pharmacy Pickup orders."))
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
                "Pickup Payment Entry cannot be cancelled after the Online Order is Completed. Use the controlled return/reversal process."
            )
        )


def on_cancel_linked_online_order_payment(doc, method=None):
    order = _get_order(doc)
    if not order:
        return

    invoice = frappe.get_doc("Sales Invoice", order.sales_invoice) if order.sales_invoice else None
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
            _("Pickup Payment Entry cannot be deleted after the Online Order is Completed.")
        )
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
