from __future__ import annotations

import inspect

import frappe
from frappe import _
from frappe.utils import cint, flt

from pharma_erp.pharma_erp import payment_card_management as shift_finance
from pharma_erp.online_order_sales_invoice_events import (
    _bind_home_delivery_invoice_to_active_shift,
)
from pharma_erp.pharma_erp.page.delivery_management.delivery_management import (
    get_delivery_orders,
)


READY_STATUS = "Ready for Delivery"


def _require_sales_invoice_fields():
    meta = frappe.get_meta("Sales Invoice")
    required = (
        "custom_online_order",
        "custom_order_type",
        "custom_delivery_status",
        "custom_delivery_shift",
        "custom_pharmacy_shift",
    )
    missing = [
        fieldname
        for fieldname in required
        if not meta.has_field(fieldname)
    ]
    if missing:
        frappe.throw(
            _("Required Sales Invoice shift fields are missing: {0}").format(
                ", ".join(missing)
            )
        )
    return meta


def _active_shift_name(company):
    shift = shift_finance._current_open_shift(company)
    if not shift:
        frappe.throw(
            _(
                "No open Pharmacy Shift exists for company {0}."
            ).format(company)
        )
    return shift.name


def _validate_repair_candidate(invoice):
    if cint(invoice.docstatus) != 1:
        frappe.throw(_("Sales Invoice must be submitted."))
    if cint(invoice.is_return):
        frappe.throw(_("Return invoices are not eligible for this repair."))
    if invoice.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("Sales Invoice must be Home Delivery."))
    if invoice.get("custom_delivery_status") != READY_STATUS:
        frappe.throw(
            _(
                "Sales Invoice must be Ready for Delivery before shift repair."
            )
        )
    if not invoice.get("custom_online_order"):
        frappe.throw(_("Sales Invoice is not linked to an Online Order."))
    if invoice.get("custom_delivery_boy"):
        frappe.throw(
            _("Cannot repair shift after a delivery driver is assigned.")
        )
    if invoice.get("custom_delivery_trip"):
        frappe.throw(
            _("Cannot repair shift after a Delivery Trip is linked.")
        )

    order = frappe.get_doc(
        "Online Order",
        invoice.get("custom_online_order"),
    )
    if order.fulfilment_method != "Home Delivery":
        frappe.throw(_("Linked Online Order is not Home Delivery."))
    if order.status != READY_STATUS:
        frappe.throw(
            _(
                "Linked Online Order must be Ready for Delivery."
            )
        )
    if order.sales_invoice != invoice.name:
        frappe.throw(
            _("Online Order does not actively link this Sales Invoice.")
        )

    return order


def _invoice_financial_snapshot(invoice_name):
    gl = frappe.db.sql(
        """
        SELECT
            COUNT(*) AS entries,
            COALESCE(SUM(debit), 0) AS debit,
            COALESCE(SUM(credit), 0) AS credit
        FROM `tabGL Entry`
        WHERE voucher_type = 'Sales Invoice'
          AND voucher_no = %s
          AND IFNULL(is_cancelled, 0) = 0
        """,
        (invoice_name,),
        as_dict=True,
    )[0]

    return {
        "gl_entries": cint(gl.entries),
        "gl_debit": flt(gl.debit),
        "gl_credit": flt(gl.credit),
        "stock_ledger_entries": frappe.db.count(
            "Stock Ledger Entry",
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": invoice_name,
            },
        ),
    }


@frappe.whitelist()
def repair(invoice_name=None):
    """Repair one eligible invoice, or all blank-shift Online Order invoices."""
    frappe.set_user("Administrator")
    meta = _require_sales_invoice_fields()

    if invoice_name:
        names = [invoice_name]
    else:
        names = frappe.get_all(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "is_return": 0,
                "custom_order_type": "Home Delivery",
                "custom_delivery_status": READY_STATUS,
            },
            pluck="name",
            order_by="creation asc",
            limit_page_length=5000,
        )

    repaired = []
    skipped = []

    for name in names:
        invoice = frappe.get_doc("Sales Invoice", name)

        try:
            order = _validate_repair_candidate(invoice)
        except Exception as exc:
            if invoice_name:
                raise
            skipped.append(
                {
                    "sales_invoice": name,
                    "reason": str(exc),
                }
            )
            frappe.db.rollback()
            continue

        active_shift = _active_shift_name(invoice.company)
        current_shift = str(
            invoice.get("custom_delivery_shift")
            or invoice.get("custom_pharmacy_shift")
            or ""
        ).strip()

        if current_shift and current_shift != active_shift:
            message = _(
                "Invoice belongs to shift {0}; active shift is {1}."
            ).format(current_shift, active_shift)
            if invoice_name:
                frappe.throw(message)
            skipped.append(
                {
                    "sales_invoice": name,
                    "reason": message,
                }
            )
            continue

        before = _invoice_financial_snapshot(name)
        values = {}

        if not invoice.get("custom_pharmacy_shift"):
            values["custom_pharmacy_shift"] = active_shift
        if not invoice.get("custom_delivery_shift"):
            values["custom_delivery_shift"] = active_shift
        if (
            meta.has_field("custom_original_delivery_shift")
            and not invoice.get("custom_original_delivery_shift")
        ):
            values["custom_original_delivery_shift"] = active_shift

        if values:
            frappe.db.set_value(
                "Sales Invoice",
                name,
                values,
                update_modified=False,
            )

            invoice.add_comment(
                "Info",
                _(
                    "Online Order Home Delivery invoice linked to active "
                    "delivery shift {0} by controlled repair."
                ).format(active_shift),
            )
            order.add_comment(
                "Info",
                _(
                    "Linked Sales Invoice {0} assigned to active delivery "
                    "shift {1}."
                ).format(name, active_shift),
            )

        after = _invoice_financial_snapshot(name)

        if before != after:
            frappe.throw(
                _(
                    "Financial or stock state changed during shift repair."
                )
            )

        repaired.append(
            {
                "sales_invoice": name,
                "online_order": order.name,
                "active_shift": active_shift,
                "values_written": values,
                "financial_snapshot": after,
            }
        )

    frappe.db.commit()

    result = {
        "repair_completed": True,
        "repaired": repaired,
        "skipped": skipped,
        "repaired_count": len(repaired),
        "skipped_count": len(skipped),
    }
    print(frappe.as_json(result))
    return result


@frappe.whitelist()
def verify(invoice_name=None):
    """Verify future submit protection and current operational visibility."""
    frappe.set_user("Administrator")
    _require_sales_invoice_fields()

    helper_source = inspect.getsource(
        _bind_home_delivery_invoice_to_active_shift
    )
    handler_source = inspect.getsource(
        __import__(
            "pharma_erp.online_order_sales_invoice_events",
            fromlist=["before_submit_linked_online_order_invoice"],
        ).before_submit_linked_online_order_invoice
    )

    result = {
        "future_submit_shift_guard_present": all(
            token in helper_source
            for token in (
                "_current_open_shift",
                "custom_pharmacy_shift",
                "custom_delivery_shift",
                "custom_original_delivery_shift",
            )
        ),
        "before_submit_calls_shift_guard": (
            "_bind_home_delivery_invoice_to_active_shift"
            in handler_source
        ),
    }

    if invoice_name:
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        order = frappe.get_doc(
            "Online Order",
            invoice.get("custom_online_order"),
        )
        active_shift = _active_shift_name(invoice.company)
        current_shift = (
            invoice.get("custom_delivery_shift")
            or invoice.get("custom_pharmacy_shift")
            or ""
        )

        board = get_delivery_orders()
        board_orders = board.get("orders") or []
        board_names = [
            row.get("name")
            for row in board_orders
        ]

        financial = _invoice_financial_snapshot(invoice.name)

        result.update(
            {
                "sales_invoice": invoice.name,
                "online_order": order.name,
                "active_shift": active_shift,
                "custom_pharmacy_shift": invoice.get(
                    "custom_pharmacy_shift"
                ),
                "custom_delivery_shift": invoice.get(
                    "custom_delivery_shift"
                ),
                "custom_original_delivery_shift": invoice.get(
                    "custom_original_delivery_shift"
                ),
                "invoice_linked_to_active_shift": (
                    current_shift == active_shift
                ),
                "invoice_visible_on_delivery_board": (
                    invoice.name in board_names
                ),
                "online_order_status": order.status,
                "payment_status": order.payment_status,
                "invoice_delivery_status": invoice.get(
                    "custom_delivery_status"
                ),
                "invoice_outstanding": flt(
                    invoice.outstanding_amount
                ),
                "financial_snapshot": financial,
                "accounting_balanced": (
                    abs(
                        financial["gl_debit"]
                        - financial["gl_credit"]
                    )
                    <= 0.000001
                ),
                "stock_safety_preserved": (
                    financial["stock_ledger_entries"] == 0
                ),
                "board_order_names": board_names,
            }
        )

    result["ok"] = all(
        value
        for key, value in result.items()
        if key in {
            "future_submit_shift_guard_present",
            "before_submit_calls_shift_guard",
            "invoice_linked_to_active_shift",
            "invoice_visible_on_delivery_board",
            "accounting_balanced",
            "stock_safety_preserved",
        }
    )

    print(result)
    print(frappe.as_json(result))
    return result
