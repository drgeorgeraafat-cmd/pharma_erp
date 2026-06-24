# Copyright (c) 2026, ZeePharaoh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt, get_datetime, now, now_datetime


class DeliverySettlement(Document):
    def before_submit(self):
        self._validate_final_settlement()

    def before_cancel(self):
        self._validate_no_submitted_handovers()

    def on_cancel(self):
        self._clear_linked_invoices()

    def _validate_final_settlement(self):
        if self.settlement_status not in ("Settled", "Disputed"):
            frappe.throw(
                "لا يمكن اعتماد التسوية قبل تنفيذ التسوية النهائية."
            )

        difference = flt(self.final_difference)
        if abs(difference) > 0.01 and not self.difference_reason:
            frappe.throw(
                "يوجد فرق في التسوية. برجاء تسجيل سبب الفرق."
            )

        trip_rows = frappe.get_all(
            "Delivery Trip",
            filters={"custom_shift_reference": self.shift_reference},
            fields=["name"],
            limit_page_length=500,
        )
        trip_names = [row.name for row in trip_rows]

        if trip_names:
            active_orders = frappe.get_all(
                "Sales Invoice",
                filters={
                    "docstatus": 1,
                    "custom_delivery_boy": self.delivery_boy,
                    "custom_delivery_trip": ["in", trip_names],
                    "custom_delivery_status": "Out for Delivery",
                },
                fields=["name"],
                limit_page_length=100,
            )
            if active_orders:
                frappe.throw(
                    "لا يمكن إتمام التسوية النهائية لأن الطيار لديه أوردرات خارج الصيدلية."
                )

            unlinked_confirmed = frappe.get_all(
                "Sales Invoice",
                filters={
                    "docstatus": 1,
                    "custom_delivery_boy": self.delivery_boy,
                    "custom_delivery_trip": ["in", trip_names],
                    "custom_delivery_status": "Delivered",
                    "custom_collection_verification_status": "Confirmed",
                    "custom_collection_received_by": "Delivery Boy",
                },
                fields=["name", "custom_delivery_settlement"],
                limit_page_length=500,
            )
            missing_invoices = [
                row.name
                for row in unlinked_confirmed
                if not row.custom_delivery_settlement
                or row.custom_delivery_settlement != self.name
            ]
            if missing_invoices:
                frappe.throw(
                    "توجد تحصيلات مؤكدة لم تتم إضافتها إلى التسوية. "
                    "اضغط تحديث تحصيلات الطيار أولًا: "
                    + ", ".join(missing_invoices)
                )

            delivered_orders = frappe.get_all(
                "Sales Invoice",
                filters={
                    "docstatus": 1,
                    "custom_delivery_boy": self.delivery_boy,
                    "custom_delivery_trip": ["in", trip_names],
                    "custom_delivery_status": "Delivered",
                },
                fields=[
                    "name",
                    "custom_driver_reported_collected_amount",
                    "custom_collection_verification_status",
                ],
                limit_page_length=500,
            )
            pending_reviews = [
                row.name
                for row in delivered_orders
                if flt(row.custom_driver_reported_collected_amount) > 0
                and row.custom_collection_verification_status != "Confirmed"
            ]
            if pending_reviews:
                frappe.throw(
                    "توجد تحصيلات أعلنها الطيار وما زالت تنتظر المراجعة: "
                    + ", ".join(pending_reviews)
                )

        self.settled_at = now()
        self.settled_by = frappe.session.user

    def _validate_no_submitted_handovers(self):
        submitted_handovers = frappe.get_all(
            "Delivery Handover",
            filters={
                "delivery_settlement": self.name,
                "docstatus": 1,
            },
            fields=["name"],
            limit_page_length=100,
        )
        if submitted_handovers:
            frappe.throw(
                "يجب إلغاء التوريدات المرتبطة أولًا: "
                + ", ".join(row.name for row in submitted_handovers)
            )

    def _clear_linked_invoices(self):
        linked_invoices = frappe.get_all(
            "Sales Invoice",
            filters={"custom_delivery_settlement": self.name},
            fields=["name"],
            limit_page_length=500,
        )
        for invoice in linked_invoices:
            frappe.db.set_value(
                "Sales Invoice",
                invoice.name,
                "custom_delivery_settlement",
                None,
            )


@frappe.whitelist()
def get_delivery_settlement_data(
    delivery_boy=None,
    shift_reference=None,
    settlement_name=None,
):
    """Return the confirmed driver collections and submitted handovers for a shift."""
    delivery_boy = delivery_boy or frappe.form_dict.get("delivery_boy")
    shift_reference = shift_reference or frappe.form_dict.get("shift_reference")
    settlement_name = (
        settlement_name
        if settlement_name is not None
        else frappe.form_dict.get("settlement_name")
    ) or ""

    if not delivery_boy:
        frappe.throw("Please select the delivery boy.")
    if not shift_reference:
        frappe.throw("Please select the shift.")
    if not frappe.db.exists("Pharmacy Shift Closing", shift_reference):
        frappe.throw("The selected shift does not exist.")

    shift = frappe.get_doc("Pharmacy Shift Closing", shift_reference)
    start_time = shift.start_time or shift.creation
    end_time = shift.end_time or now_datetime()

    trip_rows = frappe.get_all(
        "Delivery Trip",
        filters={"custom_shift_reference": shift_reference},
        fields=["name"],
        limit_page_length=500,
    )
    trip_names = [row.name for row in trip_rows]

    invoice_rows = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "custom_order_type": "Home Delivery",
            "custom_delivery_boy": delivery_boy,
            "custom_delivery_status": "Delivered",
            "custom_collection_verification_status": "Confirmed",
            "custom_collection_received_by": "Delivery Boy",
        },
        fields=[
            "name",
            "customer_name",
            "custom_confirmed_collected_amount",
            "custom_confirmed_customer_payment_method",
            "custom_collection_payment_entry",
            "custom_delivery_trip",
            "custom_collection_confirmed_at",
            "custom_delivery_settlement",
        ],
        order_by="custom_collection_confirmed_at asc",
        limit_page_length=500,
    )

    mode_map = {
        "Cash": "Cash",
        "InstaPay": "Insta Pay",
        "Mobile Wallet": "Wallet",
        "Card": "Credit Card",
        "Bank Transfer": "Bank Transfer",
        "Mixed": "Mixed",
        "No Collection": "",
    }

    items = []
    total_collected = 0.0
    shift_start = get_datetime(start_time) if start_time else None
    shift_end = get_datetime(end_time) if end_time else None

    for invoice in invoice_rows:
        if (
            invoice.custom_delivery_settlement
            and invoice.custom_delivery_settlement != settlement_name
        ):
            continue

        belongs_to_shift = bool(
            invoice.custom_delivery_trip
            and invoice.custom_delivery_trip in trip_names
        )

        if (
            not belongs_to_shift
            and invoice.custom_collection_confirmed_at
            and shift_start
            and shift_end
        ):
            confirmed_at = get_datetime(invoice.custom_collection_confirmed_at)
            belongs_to_shift = shift_start <= confirmed_at <= shift_end

        if not belongs_to_shift:
            continue

        amount = flt(invoice.custom_confirmed_collected_amount)
        if amount <= 0:
            continue

        original_method = invoice.custom_confirmed_customer_payment_method or ""
        mode_of_payment = mode_map.get(original_method, original_method)
        if mode_of_payment and not frappe.db.exists(
            "Mode of Payment", mode_of_payment
        ):
            mode_of_payment = ""

        items.append(
            {
                "invoice_number": invoice.name,
                "customer_name": invoice.customer_name,
                "amount": amount,
                "mode_of_payment": mode_of_payment,
                "collection_received_by": "Delivery Boy",
                "payment_entry": invoice.custom_collection_payment_entry,
                "confirmed_collection_amount": amount,
                "collection_status": "Confirmed",
                "delivery_trip": invoice.custom_delivery_trip,
                "collected_at": invoice.custom_collection_confirmed_at,
            }
        )
        total_collected += amount

    handover_rows = []
    if settlement_name:
        handover_rows = frappe.get_all(
            "Delivery Handover",
            filters={
                "delivery_settlement": settlement_name,
                "docstatus": 1,
            },
            fields=[
                "name",
                "handover_type",
                "handover_method",
                "amount",
                "received_at",
            ],
            order_by="received_at asc",
            limit_page_length=500,
        )

    total_handed_over = 0.0
    paid_cash = 0.0
    paid_non_cash = 0.0
    handover_count = 0
    last_handover_at = None
    final_handover_exists = False

    for handover in handover_rows:
        amount = flt(handover.amount)
        total_handed_over += amount
        handover_count += 1

        if handover.handover_method == "Cash":
            paid_cash += amount
        else:
            paid_non_cash += amount

        if handover.handover_type == "Final Settlement":
            final_handover_exists = True

        if handover.received_at and (
            not last_handover_at
            or get_datetime(handover.received_at) > get_datetime(last_handover_at)
        ):
            last_handover_at = handover.received_at

    return {
        "items": items,
        "total_collected": total_collected,
        "total_handed_over": total_handed_over,
        "paid_cash": paid_cash,
        "paid_non_cash": paid_non_cash,
        "handover_count": handover_count,
        "last_handover_at": last_handover_at,
        "final_handover_exists": final_handover_exists,
    }
