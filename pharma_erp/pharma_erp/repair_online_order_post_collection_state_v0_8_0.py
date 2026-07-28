from __future__ import annotations

import inspect

import frappe
from frappe import _
from frappe.utils import cint, flt

from pharma_erp.pharma_erp.doctype.online_order.online_order import (
    _latest_delivery_attempt_name,
    sync_home_delivery_after_collection,
)


def _financial_snapshot(invoice_name, payment_name):
    rows = frappe.db.sql(
        """
        SELECT
            voucher_type,
            voucher_no,
            COUNT(*) AS entries_count,
            COALESCE(SUM(debit), 0) AS total_debit,
            COALESCE(SUM(credit), 0) AS total_credit
        FROM `tabGL Entry`
        WHERE IFNULL(is_cancelled, 0) = 0
          AND (
                (voucher_type = 'Sales Invoice' AND voucher_no = %s)
                OR
                (voucher_type = 'Payment Entry' AND voucher_no = %s)
              )
        GROUP BY voucher_type, voucher_no
        ORDER BY voucher_type
        """,
        (invoice_name, payment_name),
        as_dict=True,
    )

    stock = {
        "sales_invoice": frappe.db.count(
            "Stock Ledger Entry",
            {
                "voucher_type": "Sales Invoice",
                "voucher_no": invoice_name,
            },
        ),
        "payment_entry": frappe.db.count(
            "Stock Ledger Entry",
            {
                "voucher_type": "Payment Entry",
                "voucher_no": payment_name,
            },
        ),
    }

    return {
        "gl": [
            {
                "voucher_type": row.voucher_type,
                "voucher_no": row.voucher_no,
                "entries_count": cint(row.entries_count),
                "total_debit": flt(row.total_debit),
                "total_credit": flt(row.total_credit),
                "difference": flt(row.total_debit)
                - flt(row.total_credit),
            }
            for row in rows
        ],
        "stock": stock,
    }


def _validate(invoice, order, payment):
    if cint(invoice.docstatus) != 1:
        frappe.throw(_("Sales Invoice must be submitted."))
    if invoice.get("custom_delivery_status") != "Delivered":
        frappe.throw(_("Sales Invoice must be Delivered."))
    if invoice.get(
        "custom_collection_verification_status"
    ) != "Confirmed":
        frappe.throw(
            _("Delivery collection must be Confirmed.")
        )
    if flt(invoice.outstanding_amount) > 0.01:
        frappe.throw(
            _("Sales Invoice must have zero outstanding.")
        )
    if cint(payment.docstatus) != 1:
        frappe.throw(_("Payment Entry must be submitted."))
    if order.fulfilment_method != "Home Delivery":
        frappe.throw(_("Online Order is not Home Delivery."))
    if order.sales_invoice != invoice.name:
        frappe.throw(
            _("Online Order does not link this Sales Invoice.")
        )


@frappe.whitelist()
def repair(invoice_name=None):
    frappe.set_user("Administrator")

    invoice_name = str(invoice_name or "").strip()
    if not invoice_name:
        frappe.throw(_("Sales Invoice is required."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    order_name = str(
        invoice.get("custom_online_order") or ""
    ).strip()
    payment_name = str(
        invoice.get(
            "custom_collection_payment_entry"
        )
        or ""
    ).strip()

    if not order_name or not payment_name:
        frappe.throw(
            _("Online Order or Payment Entry link is missing.")
        )

    order = frappe.get_doc("Online Order", order_name)
    payment = frappe.get_doc(
        "Payment Entry",
        payment_name,
    )
    _validate(invoice, order, payment)

    before = _financial_snapshot(
        invoice.name,
        payment.name,
    )

    sync_result = sync_home_delivery_after_collection(
        invoice.name
    )

    order.reload()
    after = _financial_snapshot(
        invoice.name,
        payment.name,
    )

    latest_attempt = _latest_delivery_attempt_name(
        invoice.name
    )

    repaired_state_valid = bool(
        order.status == "Delivered"
        and order.payment_status == "Verified"
        and flt(order.verified_paid_amount)
        == flt(invoice.grand_total)
        and order.payment_verified_by
        == invoice.get(
            "custom_collection_confirmed_by"
        )
        and order.payment_verified_at
        and order.payment_entry == payment.name
        and latest_attempt
        and order.delivery_attempt == latest_attempt
    )

    if before != after:
        frappe.throw(
            _(
                "Accounting or stock state changed during repair."
            )
        )

    if not repaired_state_valid:
        frappe.throw(
            _("Repaired Online Order state is incomplete.")
        )

    order.add_comment(
        "Info",
        _(
            "Post-collection Home Delivery state repaired from "
            "Sales Invoice {0}; payment verified and latest "
            "Delivery Attempt {1} retained."
        ).format(invoice.name, latest_attempt),
    )

    frappe.db.commit()

    output = {
        "post_collection_repair_completed": True,
        "online_order": order.name,
        "sales_invoice": invoice.name,
        "payment_entry": payment.name,
        "latest_delivery_attempt": latest_attempt,
        "status": order.status,
        "payment_status": order.payment_status,
        "verified_paid_amount": flt(
            order.verified_paid_amount
        ),
        "payment_verified_by": (
            order.payment_verified_by
        ),
        "payment_verified_at": str(
            order.payment_verified_at or ""
        ),
        "delivery_attempt": order.delivery_attempt,
        "sync_result": sync_result,
        "financial_snapshot": after,
        "ok": repaired_state_valid,
    }
    print(output)
    print(frappe.as_json(output))
    return output


@frappe.whitelist()
def verify(invoice_name=None):
    invoice_name = str(invoice_name or "").strip()
    if not invoice_name:
        frappe.throw(_("Sales Invoice is required."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    order = frappe.get_doc(
        "Online Order",
        invoice.get("custom_online_order"),
    )
    payment_name = str(
        invoice.get(
            "custom_collection_payment_entry"
        )
        or ""
    ).strip()
    latest_attempt = _latest_delivery_attempt_name(
        invoice.name
    )
    financial = _financial_snapshot(
        invoice.name,
        payment_name,
    )

    gl_balanced = bool(
        financial["gl"]
        and all(
            abs(row["difference"]) <= 0.000001
            for row in financial["gl"]
        )
    )
    stock_safe = all(
        count == 0
        for count in financial["stock"].values()
    )

    trusted_source = inspect.getsource(
        sync_home_delivery_after_collection
    )
    snapshot_source = inspect.getsource(
        __import__(
            "pharma_erp.pharma_erp.doctype.online_order.online_order",
            fromlist=["_sync_home_delivery_snapshot"],
        )._sync_home_delivery_snapshot
    )

    output = {
        "step2e4_verified": True,
        "online_order": order.name,
        "sales_invoice": invoice.name,
        "payment_entry": payment_name,
        "latest_delivery_attempt": latest_attempt,
        "order_status": order.status,
        "payment_status": order.payment_status,
        "verified_paid_amount": flt(
            order.verified_paid_amount
        ),
        "payment_verified_by": (
            order.payment_verified_by
        ),
        "payment_verified_at": str(
            order.payment_verified_at or ""
        ),
        "delivery_attempt": order.delivery_attempt,
        "trusted_post_collection_sync_present": (
            "_sync_home_delivery_order_from_invoice"
            in trusted_source
        ),
        "latest_attempt_fallback_present": (
            "_latest_delivery_attempt_name"
            in snapshot_source
        ),
        "payment_verified": bool(
            order.payment_status == "Verified"
            and flt(order.verified_paid_amount)
            == flt(invoice.grand_total)
            and order.payment_verified_by
            == invoice.get(
                "custom_collection_confirmed_by"
            )
            and order.payment_verified_at
            and order.payment_entry == payment_name
        ),
        "attempt_snapshot_retained": bool(
            latest_attempt
            and order.delivery_attempt
            == latest_attempt
        ),
        "accounting_balanced": gl_balanced,
        "stock_safety_preserved": stock_safe,
        "financial_snapshot": financial,
    }

    output["ok"] = all(
        output[key]
        for key in (
            "trusted_post_collection_sync_present",
            "latest_attempt_fallback_present",
            "payment_verified",
            "attempt_snapshot_retained",
            "accounting_balanced",
            "stock_safety_preserved",
        )
    )

    print(output)
    print(frappe.as_json(output))
    return output
