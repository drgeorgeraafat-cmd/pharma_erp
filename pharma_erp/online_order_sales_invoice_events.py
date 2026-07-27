from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from pharma_erp.pharma_erp.doctype.online_order.online_order import (
    _active_conversion_rows,
    _default_invoice_warehouse,
    _delivery_fee_item,
)

MONEY_TOLERANCE = 0.01
QTY_TOLERANCE = 0.000001
LATE_EXECUTION_STATUSES = {"Out for Delivery", "Delivered", "Returned", "Completed"}
DELIVERY_STATUS_MAP = {
    "Ready for Delivery": "Ready for Delivery",
    "Out for Delivery": "Out for Delivery",
    "Delivered": "Delivered",
    "Returning to Pharmacy": "Returned",
    "Returned to Pharmacy": "Returned",
}


def _online_order_name(doc) -> str:
    return str(doc.get("custom_online_order") or "").strip()


def _get_order(doc):
    order_name = _online_order_name(doc)
    if not order_name:
        return None
    if not frappe.db.exists("Online Order", order_name):
        frappe.throw(_("Linked Online Order {0} was not found.").format(order_name))
    return frappe.get_doc("Online Order", order_name)


def _assert_equal(label, actual, expected):
    if (actual or "") != (expected or ""):
        frappe.throw(
            _("Online Order submit guard failed: {0} must be {1}, not {2}.").format(
                label, expected or _("blank"), actual or _("blank")
            )
        )


def _assert_close(label, actual, expected, tolerance=MONEY_TOLERANCE):
    if abs(flt(actual) - flt(expected)) > tolerance:
        frappe.throw(
            _("Online Order submit guard failed: {0} must be {1}, not {2}.").format(
                label, flt(expected), flt(actual)
            )
        )


def _expected_item_code(order_row):
    if cint(order_row.alternative_accepted) and order_row.alternative_item:
        return order_row.alternative_item
    return order_row.item_code


def _invoice_rows_for_order(order, invoice):
    rows_by_name = {row.name: row for row in invoice.items if row.name}
    active_rows = _active_conversion_rows(order)
    resolved = []
    used_names = set()

    for index, order_row in enumerate(active_rows):
        invoice_row = None
        if order_row.sales_invoice_item:
            invoice_row = rows_by_name.get(order_row.sales_invoice_item)
        if not invoice_row and index < len(invoice.items):
            invoice_row = invoice.items[index]
        if not invoice_row:
            frappe.throw(
                _("Online Order submit guard failed: invoice row for Online Order row {0} is missing.").format(
                    order_row.idx
                )
            )
        if invoice_row.name:
            used_names.add(invoice_row.name)
        resolved.append((order_row, invoice_row))

    remaining = [row for row in invoice.items if not row.name or row.name not in used_names]
    return resolved, remaining


def validate_linked_online_order_invoice(doc, method=None):
    order = _get_order(doc)
    if not order:
        return

    if cint(doc.is_return):
        frappe.throw(_("A return/credit note cannot be the active invoice of an Online Order."))
    if cint(doc.is_pos):
        frappe.throw(_("Online Order conversion must remain a non-POS Sales Invoice."))
    if cint(doc.update_stock):
        frappe.throw(_("Online Order Sales Invoice must keep Update Stock disabled."))
    if order.sales_order:
        frappe.throw(_("This Online Order is using the Sales Order conversion path."))
    if order.sales_invoice and order.sales_invoice != doc.name:
        frappe.throw(
            _("Online Order {0} is linked to another Sales Invoice: {1}.").format(
                order.name, order.sales_invoice
            )
        )

    _assert_equal(_("Customer"), doc.customer, order.customer)
    _assert_equal(_("Company"), doc.company, order.company)
    _assert_equal(_("Currency"), doc.currency, order.currency)
    _assert_equal(_("Selling Price List"), doc.selling_price_list, order.price_list)
    _assert_equal(
        _("Order Type"),
        doc.get("custom_order_type"),
        "Home Delivery" if order.fulfilment_method == "Home Delivery" else "Walk In",
    )

    if order.fulfilment_method == "Home Delivery":
        _assert_equal(_("Customer Address"), doc.customer_address, order.customer_address)
        _assert_equal(_("Shipping Address"), doc.shipping_address_name, order.customer_address)
        _assert_equal(_("Delivery Zone"), doc.get("custom_delivery_zone"), order.delivery_zone)
        _assert_close(_("Delivery Fee"), doc.get("custom_delivery_fee"), order.delivery_fee)

    expected_warehouse = _default_invoice_warehouse(order)
    mapped_rows, remaining_rows = _invoice_rows_for_order(order, doc)
    for order_row, invoice_row in mapped_rows:
        expected_item = _expected_item_code(order_row)
        _assert_equal(_("Item in row {0}").format(order_row.idx), invoice_row.item_code, expected_item)
        _assert_close(
            _("Quantity in row {0}").format(order_row.idx),
            invoice_row.qty,
            order_row.approved_qty,
            QTY_TOLERANCE,
        )
        _assert_close(
            _("Rate in row {0}").format(order_row.idx),
            invoice_row.rate,
            order_row.approved_rate or order_row.listed_rate,
        )
        _assert_close(
            _("Discount % in row {0}").format(order_row.idx),
            invoice_row.discount_percentage,
            order_row.discount_percentage,
            QTY_TOLERANCE,
        )
        if cint(frappe.db.get_value("Item", expected_item, "is_stock_item")):
            _assert_equal(
                _("Warehouse in row {0}").format(order_row.idx),
                invoice_row.warehouse,
                order_row.warehouse or expected_warehouse,
            )

    expected_fee_item = _delivery_fee_item() if flt(order.delivery_fee) > 0 else ""
    if expected_fee_item:
        if len(remaining_rows) != 1:
            frappe.throw(_("Online Order submit guard failed: exactly one delivery fee row is required."))
        fee_row = remaining_rows[0]
        _assert_equal(_("Delivery Fee Item"), fee_row.item_code, expected_fee_item)
        _assert_close(_("Delivery Fee Qty"), fee_row.qty, 1, QTY_TOLERANCE)
        _assert_close(_("Delivery Fee Rate"), fee_row.rate, order.delivery_fee)
    elif remaining_rows:
        frappe.throw(_("Online Order submit guard failed: unexpected Sales Invoice item rows exist."))

    _assert_close(_("Invoice Grand Total"), doc.grand_total, order.grand_total)
    _assert_close(
        _("Invoice Net Total"),
        doc.net_total,
        flt(order.products_subtotal) + flt(order.delivery_fee),
    )
    _assert_close(_("Invoice Discount Amount"), doc.discount_amount, order.discount_amount)


def before_submit_linked_online_order_invoice(doc, method=None):
    order = _get_order(doc)
    if not order:
        return
    validate_linked_online_order_invoice(doc, method)

    if order.sales_invoice != doc.name:
        frappe.throw(_("The Online Order must actively link this Sales Invoice before submit."))
    if order.status not in {"Confirmed", "Preparing"}:
        frappe.throw(
            _("Online Order must be Confirmed or Preparing before Sales Invoice submit.")
        )
    order._guard_confirmation_ready()

    if order.status == "Confirmed":
        order.status = "Preparing"
        order.save(ignore_permissions=True)
        order.reload()

    if order.fulfilment_method == "Home Delivery" and doc.meta.has_field(
        "custom_delivery_status"
    ):
        doc.custom_delivery_status = "Ready for Delivery"


def _save_order_status(order, target_status, delivery_snapshot=""):
    if order.status != target_status:
        order.flags.ignore_online_order_transition = True
        order.status = target_status
    if order.meta.has_field("delivery_status_snapshot"):
        order.delivery_status_snapshot = delivery_snapshot or ""
    order.save(ignore_permissions=True)


def on_submit_linked_online_order_invoice(doc, method=None):
    order = _get_order(doc)
    if not order:
        return
    if order.sales_invoice != doc.name:
        frappe.throw(_("Online Order active Sales Invoice link changed during submit."))

    if order.fulfilment_method == "Home Delivery":
        target = "Ready for Delivery"
        snapshot = "Ready for Delivery"
    else:
        target = "Ready for Pickup"
        snapshot = ""

    _save_order_status(order, target, snapshot)
    order.add_comment(
        "Info",
        _("Sales Invoice {0} submitted; Online Order moved to {1}.").format(
            doc.name, target
        ),
    )


def sync_online_order_after_invoice_update(doc, method=None):
    order = _get_order(doc)
    if not order or cint(doc.docstatus) != 1:
        return
    if order.fulfilment_method != "Home Delivery":
        return

    invoice_delivery_status = str(doc.get("custom_delivery_status") or "").strip()
    target = DELIVERY_STATUS_MAP.get(invoice_delivery_status)
    if not target:
        return

    if order.status == target and order.delivery_status_snapshot == invoice_delivery_status:
        return

    _save_order_status(order, target, invoice_delivery_status)


def before_cancel_linked_online_order_invoice(doc, method=None):
    order = _get_order(doc)
    if not order:
        return
    if order.sales_invoice != doc.name:
        frappe.throw(_("This Sales Invoice is not the active invoice linked to the Online Order."))
    if order.status in LATE_EXECUTION_STATUSES:
        frappe.throw(
            _(
                "Sales Invoice cannot be cancelled after delivery execution has started. "
                "Use the controlled return/reversal process."
            )
        )
    if order.payment_entry and frappe.db.exists("Payment Entry", order.payment_entry):
        payment_docstatus = cint(
            frappe.db.get_value("Payment Entry", order.payment_entry, "docstatus")
        )
        if payment_docstatus < 2:
            frappe.throw(
                _(
                    "Cancel or delete active pickup Payment Entry {0} before cancelling this Sales Invoice."
                ).format(order.payment_entry)
            )


def on_cancel_linked_online_order_invoice(doc, method=None):
    order = _get_order(doc)
    if not order:
        return
    cancelled_invoice = doc.name

    order.flags.ignore_online_order_transition = True
    order.status = "Preparing"
    order.sales_invoice = None
    order.conversion_path = None
    order.converted_by = None
    order.converted_at = None
    order.payment_entry = None
    order.verified_paid_amount = 0
    order.payment_verified_by = None
    order.payment_verified_at = None
    order.payment_status = (
        "No Collection Required"
        if order.payment_timing == "No Collection Required"
        else "Pending Collection"
    )
    if order.meta.has_field("delivery_status_snapshot"):
        order.delivery_status_snapshot = ""
    for row in order.items:
        row.sales_invoice_item = None
    order.save(ignore_permissions=True)
    order.add_comment(
        "Info",
        _(
            "Sales Invoice {0} was cancelled. Active conversion links were cleared and the order returned to Preparing."
        ).format(cancelled_invoice),
    )
