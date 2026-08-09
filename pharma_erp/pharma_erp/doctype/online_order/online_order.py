from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime, today

from pharma_erp.pharma_erp.branch_operational_integration import (
    require_online_order_context,
    resolve_online_context,
)


TERMINAL_STATUSES = {"Completed", "Rejected", "Cancelled"}
PAYMENT_TOLERANCE = 0.01

# Once an order has been confirmed, its commercial/customer/address/item data
# becomes an auditable snapshot. Operational links and status fields may still
# be updated by controlled server actions. Terminal orders are locked as well.
IMMUTABLE_HEADER_FIELDS = (
    "source_channel",
    "external_reference",
    "external_created_at",
    "company",
    "branch",
    "order_type",
    "fulfilment_method",
    "customer",
    "customer_name",
    "mobile_no",
    "email_id",
    "customer_resolution_status",
    "customer_address",
    "address_title",
    "address_line1",
    "address_line2",
    "city",
    "state",
    "country",
    "address_phone",
    "formatted_address",
    "delivery_zone",
    "warehouse",
    "delivery_fee",
    "delivery_fee_rule",
    "estimated_delivery_time_mins",
    "delivery_instructions",
    "currency",
    "price_list",
    "products_subtotal",
    "discount_amount",
    "grand_total",
    "prescription_required",
    "prescription_attachment",
    "prescription_review_status",
    "prescription_review_notes",
    "prescription_reviewed_by",
    "prescription_reviewed_at",
    "payment_timing",
    "payment_method",
    "mode_of_payment",
    "declared_paid_amount",
    "transaction_reference",
    "payment_proof",
)

IMMUTABLE_ITEM_FIELDS = (
    "item_code",
    "item_name_snapshot",
    "image_snapshot",
    "online_category_snapshot",
    "description_snapshot",
    "requested_qty",
    "approved_qty",
    "uom",
    "warehouse",
    "listed_rate",
    "approved_rate",
    "discount_percentage",
    "discount_amount",
    "net_rate",
    "net_amount",
    "availability_status",
    "stock_review_status",
    "alternative_item",
    "alternative_accepted",
    "requires_prescription_snapshot",
    "prescription_item_status",
    "prescription_item_notes",
)

ALLOWED_TRANSITIONS = {
    "Draft": {"Placed", "Cancelled"},
    "Placed": {"Under Review", "Cancelled"},
    "Under Review": {
        "Prescription Review",
        "Stock Review",
        "Ready for Payment",
        "On Hold",
        "Rejected",
        "Cancelled",
    },
    "Prescription Review": {
        "Stock Review",
        "Partially Available",
        "Awaiting Customer Decision",
        "On Hold",
        "Rejected",
        "Cancelled",
    },
    "Stock Review": {
        "Partially Available",
        "Awaiting Customer Decision",
        "Ready for Payment",
        "On Hold",
        "Rejected",
        "Cancelled",
    },
    "Partially Available": {
        "Awaiting Customer Decision",
        "Stock Review",
        "Ready for Payment",
        "Cancelled",
    },
    "Awaiting Customer Decision": {"Stock Review", "Ready for Payment", "Cancelled"},
    "Ready for Payment": {"Payment Verification", "Confirmed", "On Hold", "Cancelled"},
    "Payment Verification": {"Confirmed", "Payment Failed", "On Hold", "Cancelled"},
    "Payment Failed": {"Ready for Payment", "Cancelled"},
    "Confirmed": {"Preparing", "Cancelled"},
    "Preparing": {"Ready for Delivery", "Ready for Pickup", "On Hold", "Cancelled"},
    "Ready for Delivery": {"Out for Delivery", "Cancelled"},
    "Ready for Pickup": {"Completed", "Cancelled"},
    "Out for Delivery": {"Delivered", "Returned"},
    "Delivered": {"Completed", "Returned"},
    "Returned": {"Completed"},
    "On Hold": {
        "Under Review",
        "Prescription Review",
        "Stock Review",
        "Ready for Payment",
        "Preparing",
        "Rejected",
        "Cancelled",
    },
    "Completed": set(),
    "Rejected": set(),
    "Cancelled": set(),
}


class OnlineOrder(Document):
    def before_insert(self):
        self._apply_defaults()

    def validate(self):
        self._apply_defaults()
        self._validate_status_transition()
        self._normalise_mobile()
        self._populate_customer_snapshot()
        self._populate_address_snapshot()
        self._populate_item_snapshots_and_totals()
        self._validate_prescription_state()
        self._validate_payment_state()
        self._validate_delivery_state()
        self._validate_conversion_links()
        self._validate_confirmed_order_lock()
        self._validate_status_guards()
        self._set_status_timestamps()

    def _apply_defaults(self):
        if not self.status:
            self.status = "Draft"
        if not self.source_channel:
            self.source_channel = "Internal Entry"
        if not self.fulfilment_method:
            self.fulfilment_method = "Home Delivery"
        if not self.customer_resolution_status:
            self.customer_resolution_status = "Unresolved"
        if not self.currency:
            self.currency = frappe.db.get_single_value("Global Defaults", "default_currency")
        if not self.company:
            self.company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not self.price_list:
            self.price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")

        # New Online Orders always start with an explicit canonical branch and
        # warehouse. Existing legacy orders without branch attribution are not
        # guessed or silently backfilled during ordinary saves.
        if self.is_new():
            context = resolve_online_context(
                company=self.company,
                fulfilment_method=self.fulfilment_method,
                requested_branch=self.branch,
                submitted_warehouse=self.warehouse,
            )
            self.branch = context["branch"]
            self.warehouse = context["warehouse"]
        elif self.branch:
            context = resolve_online_context(
                company=self.company,
                fulfilment_method=self.fulfilment_method,
                requested_branch=self.branch,
                submitted_warehouse=self.warehouse,
            )
            self.warehouse = context["warehouse"]

        if not self.payment_timing:
            self.payment_timing = "Collect on Delivery"
        if not self.payment_status:
            self.payment_status = "Not Declared"

    def _validate_status_transition(self):
        if getattr(self.flags, "ignore_online_order_transition", False):
            return

        if self.is_new():
            if self.status not in {"Draft", "Placed"}:
                frappe.throw(_("A new Online Order must start as Draft or Placed."))
            return

        previous = self.get_doc_before_save()
        if not previous or previous.status == self.status:
            return

        if previous.status in TERMINAL_STATUSES:
            frappe.throw(_("Online Order {0} is terminal and cannot change status.").format(self.name))

        allowed = ALLOWED_TRANSITIONS.get(previous.status, set())
        if self.status not in allowed:
            frappe.throw(
                _("Status transition from {0} to {1} is not allowed.").format(
                    frappe.bold(previous.status), frappe.bold(self.status)
                )
            )

    def _validate_confirmed_order_lock(self):
        if self.is_new():
            return

        previous = self.get_doc_before_save()
        if not previous:
            return

        was_confirmed = bool(previous.get("confirmed_at"))
        was_terminal = previous.status in TERMINAL_STATUSES
        if not was_confirmed and not was_terminal:
            return

        changed_fields = []
        for fieldname in IMMUTABLE_HEADER_FIELDS:
            if previous.get(fieldname) != self.get(fieldname):
                changed_fields.append(self.meta.get_label(fieldname) or fieldname)

        if self._locked_item_signature(previous.get("items")) != self._locked_item_signature(
            self.get("items")
        ):
            changed_fields.append(_("Items"))

        if changed_fields:
            frappe.throw(
                _(
                    "Confirmed or terminal Online Orders are locked. "
                    "Create a controlled amendment/cancellation instead of editing: {0}"
                ).format(", ".join(changed_fields))
            )

    @staticmethod
    def _locked_item_signature(rows):
        signature = []
        for row in rows or []:
            signature.append(
                tuple(row.get(fieldname) for fieldname in IMMUTABLE_ITEM_FIELDS)
            )
        return tuple(signature)

    def _normalise_mobile(self):
        raw = str(self.mobile_no or "").strip()
        if not raw:
            return
        prefix = "+" if raw.startswith("+") else ""
        digits = re.sub(r"\D", "", raw)
        self.mobile_no = prefix + digits
        if len(digits) < 8:
            frappe.throw(_("Enter a valid mobile number."))

    def _populate_customer_snapshot(self):
        if not self.customer:
            return
        if not frappe.db.exists("Customer", self.customer):
            frappe.throw(_("Customer {0} was not found.").format(self.customer))
        customer = frappe.db.get_value(
            "Customer",
            self.customer,
            ["customer_name", "mobile_no", "email_id"],
            as_dict=True,
        ) or {}
        self.customer_name = self.customer_name or customer.get("customer_name")
        self.mobile_no = self.mobile_no or customer.get("mobile_no")
        self.email_id = self.email_id or customer.get("email_id")

    def _populate_address_snapshot(self):
        if not self.customer_address:
            return
        if not frappe.db.exists("Address", self.customer_address):
            frappe.throw(_("Address {0} was not found.").format(self.customer_address))

        address = frappe.db.get_value(
            "Address",
            self.customer_address,
            [
                "address_title",
                "address_line1",
                "address_line2",
                "city",
                "state",
                "country",
                "phone",
                "custom_delivery_zone",
                "disabled",
            ],
            as_dict=True,
        ) or {}
        if cint(address.get("disabled")):
            frappe.throw(_("The selected address is disabled."))

        if self.customer:
            linked = frappe.db.exists(
                "Dynamic Link",
                {
                    "parenttype": "Address",
                    "parent": self.customer_address,
                    "link_doctype": "Customer",
                    "link_name": self.customer,
                },
            )
            if not linked:
                frappe.throw(_("The selected address is not linked to Customer {0}.").format(self.customer))

        self.address_title = self.address_title or address.get("address_title")
        self.address_line1 = self.address_line1 or address.get("address_line1")
        self.address_line2 = self.address_line2 or address.get("address_line2")
        self.city = self.city or address.get("city")
        self.state = self.state or address.get("state")
        self.country = self.country or address.get("country")
        self.address_phone = self.address_phone or address.get("phone")
        self.delivery_zone = self.delivery_zone or address.get("custom_delivery_zone")
        self.formatted_address = self._formatted_address()

    def _formatted_address(self):
        return ", ".join(
            str(value).strip()
            for value in (self.address_line1, self.address_line2, self.city, self.state, self.country)
            if str(value or "").strip()
        )

    def _populate_item_snapshots_and_totals(self):
        if not self.items:
            self.products_subtotal = 0
            self.grand_total = max(0, flt(self.delivery_fee) - flt(self.discount_amount))
            self.prescription_required = 0
            return

        subtotal = 0.0
        prescription_required = False
        for row in self.items:
            if flt(row.requested_qty) <= 0:
                frappe.throw(_("Requested Qty must be greater than zero in row {0}.").format(row.idx))
            if not row.item_code or not frappe.db.exists("Item", row.item_code):
                frappe.throw(_("Select a valid Item in row {0}.").format(row.idx))

            item = frappe.db.get_value(
                "Item",
                row.item_code,
                [
                    "item_name",
                    "stock_uom",
                    "image",
                    "disabled",
                    "custom_online_category",
                    "custom_online_description_ar",
                    "custom_online_description_en",
                    "custom_requires_prescription",
                ],
                as_dict=True,
            ) or {}
            if cint(item.get("disabled")):
                frappe.throw(_("Item {0} is disabled.").format(row.item_code))

            row.item_name_snapshot = item.get("item_name") or row.item_code
            row.uom = row.uom or item.get("stock_uom")
            row.image_snapshot = item.get("image") or ""
            row.online_category_snapshot = item.get("custom_online_category") or ""
            row.description_snapshot = (
                item.get("custom_online_description_ar")
                or item.get("custom_online_description_en")
                or ""
            )
            row.requires_prescription_snapshot = cint(item.get("custom_requires_prescription"))
            if row.requires_prescription_snapshot:
                prescription_required = True
                if row.prescription_item_status == "Not Required":
                    row.prescription_item_status = "Pending"
            elif not row.prescription_item_status:
                row.prescription_item_status = "Not Required"

            if flt(row.approved_qty) <= 0 and row.availability_status not in {"Unavailable", "Removed"}:
                row.approved_qty = flt(row.requested_qty)
            if flt(row.approved_rate) <= 0:
                row.approved_rate = flt(row.listed_rate)
            row.discount_percentage = max(0, min(100, flt(row.discount_percentage)))
            gross_rate = flt(row.approved_rate)
            row.discount_amount = gross_rate * flt(row.discount_percentage) / 100
            row.net_rate = max(0, gross_rate - flt(row.discount_amount))
            row.net_amount = flt(row.approved_qty) * flt(row.net_rate)
            subtotal += flt(row.net_amount)

        self.prescription_required = cint(prescription_required)
        self.products_subtotal = subtotal
        self.discount_amount = max(0, flt(self.discount_amount))
        self.delivery_fee = max(0, flt(self.delivery_fee))
        self.grand_total = max(0, subtotal - self.discount_amount + self.delivery_fee)

    def _validate_prescription_state(self):
        if not self.prescription_required:
            self.prescription_review_status = "Not Required"
            return

        if not self.prescription_attachment and self.prescription_review_status in {
            "Not Required",
            "Awaiting Review",
            "Approved",
            "Partially Approved",
        }:
            self.prescription_review_status = "Required - Not Uploaded"
        elif self.prescription_attachment and self.prescription_review_status in {
            "Not Required",
            "Required - Not Uploaded",
        }:
            self.prescription_review_status = "Awaiting Review"

    def _validate_payment_state(self):
        declared = max(0, flt(self.declared_paid_amount))
        verified = max(0, flt(self.verified_paid_amount))
        self.declared_paid_amount = declared
        self.verified_paid_amount = verified

        if verified > flt(self.grand_total) + 0.01:
            frappe.throw(_("Verified Paid Amount cannot exceed the Online Order grand total."))

        if self.payment_timing == "No Collection Required":
            self.payment_status = "No Collection Required"
        elif self.payment_timing == "Collect on Delivery" and self.payment_status == "Not Declared":
            self.payment_status = "Pending Collection"
        elif self.payment_timing in {"Prepaid", "Partially Prepaid"}:
            if declared <= 0:
                frappe.throw(_("Declared Paid Amount is required for prepaid orders."))
            if not self.transaction_reference and not self.payment_proof:
                frappe.throw(_("Add a transaction reference or payment proof for prepaid orders."))
            if self.payment_status in {"Not Declared", "Pending Collection"}:
                self.payment_status = "Awaiting Verification"

    def _validate_delivery_state(self):
        if self.fulfilment_method != "Home Delivery":
            return
        if not self.delivery_zone:
            return
        zone = frappe.db.get_value(
            "Delivery Zone",
            self.delivery_zone,
            ["is_active", "warehouse", "estimated_time_mins"],
            as_dict=True,
        )
        if not zone:
            frappe.throw(_("Delivery Zone {0} was not found.").format(self.delivery_zone))
        if not cint(zone.get("is_active")):
            frappe.throw(_("Delivery Zone {0} is inactive.").format(self.delivery_zone))
        if not self.warehouse:
            self.warehouse = zone.get("warehouse")
        elif zone.get("warehouse") and self.warehouse != zone.get("warehouse"):
            frappe.throw(_("Warehouse must match the selected Delivery Zone warehouse."))
        if not self.estimated_delivery_time_mins:
            self.estimated_delivery_time_mins = cint(zone.get("estimated_time_mins"))

    def _validate_conversion_links(self):
        if self.sales_order and not frappe.db.exists("Sales Order", self.sales_order):
            frappe.throw(_("Linked Sales Order {0} was not found.").format(self.sales_order))
        if self.sales_invoice and not frappe.db.exists("Sales Invoice", self.sales_invoice):
            frappe.throw(_("Linked Sales Invoice {0} was not found.").format(self.sales_invoice))
        if self.sales_order and self.conversion_path == "Direct Sales Invoice":
            frappe.throw(_("Direct Sales Invoice conversion cannot have a Sales Order link."))

    def _validate_status_guards(self):
        if self.status in {"Placed", "Under Review", "Prescription Review", "Stock Review"}:
            if not self.customer_name or not self.mobile_no:
                frappe.throw(_("Customer Name and Mobile No are required."))
            if not self.items:
                frappe.throw(_("Add at least one item to the Online Order."))

        if self.status in {
            "Confirmed",
            "Preparing",
            "Ready for Delivery",
            "Ready for Pickup",
            "Out for Delivery",
            "Delivered",
            "Completed",
        }:
            self._guard_confirmation_ready()

        if self.status == "Ready for Delivery":
            if self.fulfilment_method != "Home Delivery":
                frappe.throw(_("Ready for Delivery is only valid for Home Delivery orders."))
            self._guard_submitted_sales_invoice(_("Ready for Delivery"))

        if self.status == "Ready for Pickup":
            if self.fulfilment_method != "Pharmacy Pickup":
                frappe.throw(_("Ready for Pickup is only valid for Pharmacy Pickup orders."))
            self._guard_submitted_sales_invoice(_("Ready for Pickup"))

        if self.status in {"Out for Delivery", "Delivered", "Returned"}:
            if self.fulfilment_method != "Home Delivery":
                frappe.throw(_("Delivery execution statuses are only valid for Home Delivery orders."))

        if self.status == "Completed" and self.fulfilment_method == "Home Delivery":
            self._guard_home_delivery_completion_state()

        if self.status in {"Out for Delivery", "Delivered"}:
            if not self.sales_invoice:
                frappe.throw(_("A linked Sales Invoice is required for delivery status sync."))
            invoice_status = frappe.db.get_value(
                "Sales Invoice", self.sales_invoice, "custom_delivery_status"
            )
            expected = "Out for Delivery" if self.status == "Out for Delivery" else "Delivered"
            if invoice_status != expected:
                frappe.throw(
                    _("Linked Sales Invoice delivery status must be {0}.").format(expected)
                )

        if self.status == "Cancelled" and not self.cancellation_reason:
            frappe.throw(_("Cancellation Reason is required."))
        if self.status == "Rejected" and not self.rejection_reason:
            frappe.throw(_("Rejection Reason is required."))
        if self.status == "On Hold" and not self.on_hold_reason:
            frappe.throw(_("On Hold Reason is required."))


    def _guard_home_delivery_completion_state(self):
        if not self.sales_invoice:
            frappe.throw(_("A linked Sales Invoice is required before Home Delivery completion."))
        invoice = frappe.get_doc("Sales Invoice", self.sales_invoice)
        if cint(invoice.docstatus) != 1:
            frappe.throw(_("The linked Sales Invoice must be submitted."))
        if str(invoice.get("custom_delivery_status") or "").strip() != "Delivered":
            frappe.throw(_("The linked Sales Invoice delivery status must be Delivered."))

        collection = _home_delivery_collection_state(self, invoice)
        if not collection["collection_ready"]:
            if collection["outstanding"] > PAYMENT_TOLERANCE:
                frappe.throw(
                    _("Delivery collection is incomplete. Remaining Sales Invoice outstanding: {0}.").format(
                        collection["outstanding"]
                    )
                )
            frappe.throw(
                _("Delivery collection must be confirmed before completing the Online Order.")
            )

    def _guard_submitted_sales_invoice(self, target_label):
        if not self.sales_invoice:
            frappe.throw(
                _("A linked Sales Invoice is required before {0}.").format(target_label)
            )
        if cint(frappe.db.get_value("Sales Invoice", self.sales_invoice, "docstatus")) != 1:
            frappe.throw(_("The linked Sales Invoice must be submitted."))

    def _guard_confirmation_ready(self):
        if not self.customer:
            frappe.throw(_("Resolve and link a Customer before confirmation."))
        if self.customer_resolution_status not in {"Matched", "Confirmed"}:
            frappe.throw(_("Customer Resolution Status must be Matched or Confirmed."))
        if not self.items:
            frappe.throw(_("Add at least one item."))

        active_rows = [
            row
            for row in self.items
            if row.availability_status not in {"Unavailable", "Removed"}
            and flt(row.approved_qty) > 0
        ]
        if not active_rows:
            frappe.throw(_("At least one approved and available item is required."))
        for row in active_rows:
            if row.stock_review_status not in {"Reviewed", "Approved"}:
                frappe.throw(_("Complete stock review for row {0}.").format(row.idx))
            if row.requires_prescription_snapshot and row.prescription_item_status not in {
                "Approved",
                "Alternative Suggested",
            }:
                frappe.throw(_("Prescription decision is incomplete for row {0}.").format(row.idx))

        if self.prescription_required and self.prescription_review_status not in {
            "Approved",
            "Partially Approved",
        }:
            frappe.throw(_("Prescription review must be approved before confirmation."))

        if self.fulfilment_method == "Home Delivery":
            if not self.address_line1 or not self.city or not self.delivery_zone or not self.warehouse:
                frappe.throw(_("Complete the delivery address, zone and warehouse before confirmation."))

        if self.payment_timing == "Prepaid" and self.payment_status != "Verified":
            frappe.throw(_("Prepaid payment must be verified before confirmation."))
        if self.payment_timing == "Partially Prepaid" and self.payment_status not in {
            "Verified",
            "Partially Verified",
        }:
            frappe.throw(_("Partial prepayment must be verified before confirmation."))
        if self.payment_timing == "Collect on Delivery":
            allowed_collection_statuses = {"Pending Collection", "Not Declared"}
            if self.status in {
                "Ready for Delivery",
                "Ready for Pickup",
                "Out for Delivery",
                "Delivered",
                "Returned",
                "Completed",
            }:
                allowed_collection_statuses.update(
                    {"Collection Draft Created", "Partially Verified", "Verified"}
                )
            if self.payment_status not in allowed_collection_statuses:
                frappe.throw(
                    _("Collect on Delivery payment status is not valid for the current order stage.")
                )

    def _set_status_timestamps(self):
        previous = self.get_doc_before_save()
        previous_status = previous.status if previous else None
        if self.status == previous_status:
            return
        now = now_datetime()
        if self.status == "Placed" and not self.placed_at:
            self.placed_at = now
        elif self.status == "Confirmed" and not self.confirmed_at:
            self.confirmed_at = now
        elif self.status == "Cancelled":
            self.cancelled_at = now
            self.cancelled_by = frappe.session.user
        elif self.status == "Rejected":
            self.rejected_at = now
            self.rejected_by = frappe.session.user


def _has_field(doctype: str, fieldname: str) -> bool:
    return bool(frappe.get_meta(doctype).has_field(fieldname))


def _set_if_has(doc, fieldname: str, value):
    if doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


def _active_conversion_rows(order):
    return [
        row
        for row in order.items
        if row.availability_status not in {"Unavailable", "Removed"}
        and flt(row.approved_qty) > 0
    ]


def _default_invoice_warehouse(order):
    return require_online_order_context(order)["warehouse"]


def _conversion_factor(item_code: str, uom: str | None) -> float:
    stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
    if not uom or uom == stock_uom:
        return 1.0
    factor = frappe.db.get_value(
        "UOM Conversion Detail",
        {"parent": item_code, "uom": uom},
        "conversion_factor",
    )
    if not factor:
        frappe.throw(
            _("UOM {0} has no conversion factor for Item {1}.").format(uom, item_code)
        )
    return flt(factor)


def _prepaid_method(order):
    mapping = {
        "InstaPay": "InstaPay",
        "Mobile Wallet": "Mobile Wallet",
        "Card Payment Link": "Card Payment Link",
        "Bank Transfer": "Bank Transfer",
        "Cash at Pharmacy": "Cash at Pharmacy",
        "Other": "Other",
    }
    return mapping.get(str(order.payment_method or "").strip(), "")


def _prepaid_verification_status(order):
    if order.payment_status in {"Verified", "Partially Verified"}:
        return "Confirmed"
    if order.payment_status == "Awaiting Verification":
        return "Awaiting Confirmation"
    if order.payment_status in {"Rejected", "Failed"}:
        return "Rejected"
    return "Not Declared"


def _delivery_fee_item():
    if not frappe.db.exists("DocType", "Pharmacy POS Settings"):
        return ""
    return str(
        frappe.db.get_single_value("Pharmacy POS Settings", "delivery_fee_item") or ""
    ).strip()


def _mode_of_payment_account(mode_of_payment: str, company: str) -> str:
    mode_of_payment = str(mode_of_payment or "").strip()
    if not mode_of_payment or not frappe.db.exists("Mode of Payment", mode_of_payment):
        frappe.throw(_("Select a valid Mode of Payment."))

    account = frappe.db.get_value(
        "Mode of Payment Account",
        {
            "parent": mode_of_payment,
            "parenttype": "Mode of Payment",
            "parentfield": "accounts",
            "company": company,
        },
        "default_account",
    )
    if not account:
        frappe.throw(
            _("Set a Default Account for company {0} in Mode of Payment {1}.").format(
                company, mode_of_payment
            )
        )

    values = frappe.db.get_value(
        "Account",
        account,
        ["company", "is_group", "disabled", "account_type"],
        as_dict=True,
    )
    if not values:
        frappe.throw(_("Mode of Payment account {0} was not found.").format(account))
    if values.get("company") != company:
        frappe.throw(_("Mode of Payment account belongs to another company."))
    if cint(values.get("is_group")):
        frappe.throw(_("Mode of Payment account cannot be a group account."))
    if cint(values.get("disabled")):
        frappe.throw(_("Mode of Payment account is disabled."))
    if values.get("account_type") not in {"Bank", "Cash"}:
        frappe.throw(_("Mode of Payment default account must be a Bank or Cash account."))
    return account


def _payment_entry_references_invoice(payment_entry, invoice_name: str) -> bool:
    return any(
        row.reference_doctype == "Sales Invoice"
        and row.reference_name == invoice_name
        and flt(row.allocated_amount) > 0
        for row in payment_entry.references
    )


def _set_invoice_collection_fields(invoice_name: str, values: dict):
    meta = frappe.get_meta("Sales Invoice")
    updates = {key: value for key, value in values.items() if meta.has_field(key)}
    if updates:
        frappe.db.set_value("Sales Invoice", invoice_name, updates, update_modified=False)


HOME_DELIVERY_INVOICE_STATUS_MAP = {
    "Ready for Delivery": "Ready for Delivery",
    "Out for Delivery": "Out for Delivery",
    "Delivered": "Delivered",
    "Returning to Pharmacy": "Returned",
    "Returned to Pharmacy": "Returned",
}


def _submitted_payment_entry(payment_name: str | None) -> bool:
    payment_name = str(payment_name or "").strip()
    return bool(
        payment_name
        and frappe.db.exists("Payment Entry", payment_name)
        and cint(frappe.db.get_value("Payment Entry", payment_name, "docstatus")) == 1
    )


def _home_delivery_collection_state(order, invoice):
    outstanding = max(0, flt(invoice.outstanding_amount))
    grand_total = max(0, flt(invoice.grand_total or order.grand_total))
    collection_status = str(
        invoice.get("custom_collection_verification_status") or ""
    ).strip()
    confirmed_method = str(
        invoice.get("custom_confirmed_customer_payment_method") or ""
    ).strip()
    prepaid_status = str(
        invoice.get("custom_prepaid_verification_status") or ""
    ).strip()

    collection_payment = str(
        invoice.get("custom_collection_payment_entry") or ""
    ).strip()
    prepaid_payment = str(invoice.get("custom_prepaid_payment_entry") or "").strip()
    linked_payment = collection_payment or prepaid_payment or str(order.payment_entry or "").strip()

    # The Sales Invoice collection verification field may default to
    # "Not Required" before delivery collection starts. That default must
    # not bypass Collect on Delivery or prepaid verification.
    no_collection = bool(
        order.payment_timing == "No Collection Required"
        or confirmed_method == "No Collection"
    )

    collection_payment_submitted = _submitted_payment_entry(collection_payment)
    prepaid_payment_submitted = _submitted_payment_entry(prepaid_payment)
    linked_payment_submitted = _submitted_payment_entry(linked_payment)

    if no_collection:
        payment_status = "No Collection Required"
        verified_amount = 0.0
        collection_ready = True
    else:
        if order.payment_timing == "Prepaid":
            evidence_confirmed = bool(
                prepaid_status == "Confirmed"
                or (
                    order.payment_status == "Verified"
                    and linked_payment_submitted
                )
            )
        elif order.payment_timing == "Partially Prepaid":
            evidence_confirmed = bool(
                collection_status == "Confirmed"
                and (collection_payment_submitted or linked_payment_submitted)
            )
        else:
            evidence_confirmed = bool(
                collection_status == "Confirmed"
                and (collection_payment_submitted or linked_payment_submitted)
            )

        collection_ready = bool(
            outstanding <= PAYMENT_TOLERANCE and evidence_confirmed
        )
        verified_amount = max(0, grand_total - outstanding)

        if collection_ready:
            payment_status = "Verified"
            verified_amount = grand_total
        elif verified_amount > PAYMENT_TOLERANCE:
            payment_status = "Partially Verified"
        elif collection_status in {"Awaiting Confirmation", "Confirmed", "Disputed"}:
            payment_status = "Awaiting Verification"
        else:
            payment_status = "Pending Collection"

    return {
        "outstanding": outstanding,
        "grand_total": grand_total,
        "collection_status": collection_status,
        "confirmed_method": confirmed_method,
        "payment_entry": linked_payment,
        "payment_entry_submitted": linked_payment_submitted,
        "payment_status": payment_status,
        "verified_amount": verified_amount,
        "no_collection": no_collection,
        "collection_ready": collection_ready,
    }


def _latest_delivery_attempt_name(invoice_name: str) -> str:
    if not frappe.db.exists("DocType", "Delivery Attempt"):
        return ""

    rows = frappe.get_all(
        "Delivery Attempt",
        filters={"parent_delivery_invoice": invoice_name},
        fields=["name"],
        order_by="attempt_number desc, creation desc",
        limit_page_length=1,
    )
    return str(rows[0].name or "").strip() if rows else ""


def _sync_home_delivery_snapshot(order, invoice):
    latest_attempt = (
        str(invoice.get("custom_current_delivery_attempt") or "").strip()
        or _latest_delivery_attempt_name(invoice.name)
        or str(order.get("delivery_attempt") or "").strip()
    )

    mappings = {
        "delivery_boy": "custom_delivery_boy",
        "delivery_trip": "custom_delivery_trip",
        "delivery_departure_at": "custom_departure_time",
        "delivery_delivered_at": "custom_delivery_time",
    }
    for target, source in mappings.items():
        if order.meta.has_field(target):
            order.set(target, invoice.get(source))

    if order.meta.has_field("delivery_attempt"):
        order.delivery_attempt = latest_attempt

    if order.meta.has_field("delivery_status_snapshot"):
        order.delivery_status_snapshot = str(
            invoice.get("custom_delivery_status") or ""
        ).strip()


def _apply_home_delivery_collection_state(order, invoice):
    collection = _home_delivery_collection_state(order, invoice)
    order.payment_status = collection["payment_status"]
    order.verified_paid_amount = collection["verified_amount"]

    if collection["payment_entry"]:
        order.payment_entry = collection["payment_entry"]

    if collection["collection_ready"]:
        verified_by = (
            invoice.get("custom_collection_confirmed_by")
            or invoice.get("custom_prepaid_confirmed_by")
            or frappe.session.user
        )
        verified_at = (
            invoice.get("custom_collection_confirmed_at")
            or invoice.get("custom_prepaid_confirmed_at")
            or now_datetime()
        )
        order.payment_verified_by = verified_by
        order.payment_verified_at = verified_at
    elif collection["payment_status"] == "Pending Collection":
        order.payment_verified_by = None
        order.payment_verified_at = None

    return collection


def _sync_home_delivery_order_from_invoice(order, invoice, save=True):
    if order.fulfilment_method != "Home Delivery":
        frappe.throw(_("Home Delivery sync is only valid for Home Delivery orders."))
    if order.sales_invoice != invoice.name:
        frappe.throw(_("Sales Invoice is not the active invoice linked to this Online Order."))
    if cint(invoice.docstatus) != 1:
        frappe.throw(_("The linked Sales Invoice must be submitted."))

    invoice_delivery_status = str(
        invoice.get("custom_delivery_status") or ""
    ).strip()
    target_status = HOME_DELIVERY_INVOICE_STATUS_MAP.get(invoice_delivery_status)

    if (
        target_status
        and order.status not in TERMINAL_STATUSES
        and order.status != target_status
    ):
        order.flags.ignore_online_order_transition = True
        order.status = target_status

    _sync_home_delivery_snapshot(order, invoice)
    collection = _apply_home_delivery_collection_state(order, invoice)

    if save:
        order.save(ignore_permissions=True)

    return {
        "online_order": order.name,
        "online_order_status": order.status,
        "invoice_delivery_status": invoice_delivery_status,
        "payment_status": order.payment_status,
        "payment_entry": order.payment_entry,
        "verified_paid_amount": flt(order.verified_paid_amount),
        "outstanding": collection["outstanding"],
        "collection_ready": collection["collection_ready"],
    }


def sync_home_delivery_after_collection(invoice_name: str):
    """Trusted backend resync after delivery collection fields are final."""
    invoice_name = str(invoice_name or "").strip()
    if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
        frappe.throw(_("Linked Sales Invoice was not found."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    order_name = str(invoice.get("custom_online_order") or "").strip()
    if not order_name:
        return {
            "sales_invoice": invoice.name,
            "online_order": "",
            "synced": False,
        }

    if not frappe.db.exists("Online Order", order_name):
        frappe.throw(
            _("Linked Online Order {0} was not found.").format(order_name)
        )

    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order_name,),
    )

    order = frappe.get_doc("Online Order", order_name)
    invoice.reload()

    if order.fulfilment_method != "Home Delivery":
        return {
            "sales_invoice": invoice.name,
            "online_order": order.name,
            "synced": False,
        }

    result = _sync_home_delivery_order_from_invoice(
        order,
        invoice,
        save=True,
    )
    result["synced"] = True
    return result


def _build_sales_invoice_draft(order):
    invoice = frappe.new_doc("Sales Invoice")
    invoice.customer = order.customer
    invoice.company = order.company
    _set_if_has(invoice, "custom_pharmacy_branch", order.branch)
    invoice.posting_date = today()
    invoice.due_date = today()
    invoice.currency = order.currency
    invoice.selling_price_list = order.price_list
    invoice.update_stock = 0
    invoice.is_pos = 0
    invoice.ignore_pricing_rule = 1

    default_warehouse = _default_invoice_warehouse(order)
    if default_warehouse:
        invoice.set_warehouse = default_warehouse

    _set_if_has(invoice, "custom_online_order", order.name)
    _set_if_has(
        invoice,
        "custom_order_type",
        "Home Delivery" if order.fulfilment_method == "Home Delivery" else "Walk In",
    )

    if order.fulfilment_method == "Home Delivery":
        _set_if_has(invoice, "custom_delivery_status", "Draft")
        _set_if_has(invoice, "custom_delivery_zone", order.delivery_zone)
        _set_if_has(invoice, "custom_delivery_fee", flt(order.delivery_fee))
        _set_if_has(invoice, "custom_delivery_fee_rule", order.delivery_fee_rule)
        _set_if_has(
            invoice,
            "custom_estimated_delivery_time",
            cint(order.estimated_delivery_time_mins),
        )

    if order.customer_address:
        invoice.customer_address = order.customer_address
        if order.fulfilment_method == "Home Delivery":
            invoice.shipping_address_name = order.customer_address
    if order.formatted_address:
        invoice.address_display = order.formatted_address
        if order.fulfilment_method == "Home Delivery":
            invoice.shipping_address = order.formatted_address
    if order.mobile_no:
        invoice.contact_mobile = order.mobile_no

    _set_if_has(invoice, "custom_delivery_payment_timing", order.payment_timing)
    _set_if_has(invoice, "custom_prepaid_amount", flt(order.verified_paid_amount))
    _set_if_has(invoice, "custom_prepaid_method", _prepaid_method(order))
    _set_if_has(invoice, "custom_prepaid_transaction_reference", order.transaction_reference)
    _set_if_has(invoice, "custom_prepaid_payment_proof", order.payment_proof)
    _set_if_has(
        invoice,
        "custom_prepaid_verification_status",
        _prepaid_verification_status(order),
    )
    if order.payment_entry:
        _set_if_has(invoice, "custom_prepaid_payment_entry", order.payment_entry)
    if order.prescription_attachment:
        _set_if_has(
            invoice,
            "custom_prescription_attachment",
            order.prescription_attachment,
        )

    notes = [_('Created from Online Order {0}.').format(order.name)]
    if order.external_reference:
        notes.append(_("External Reference: {0}").format(order.external_reference))
    if order.delivery_instructions:
        notes.append(_("Delivery Instructions: {0}").format(order.delivery_instructions))
    invoice.remarks = "\n".join(notes)

    mapped_rows = []
    for order_row in _active_conversion_rows(order):
        item_code = (
            order_row.alternative_item
            if cint(order_row.alternative_accepted) and order_row.alternative_item
            else order_row.item_code
        )
        item_is_stock = cint(frappe.db.get_value("Item", item_code, "is_stock_item"))
        warehouse = str(order_row.warehouse or default_warehouse or "").strip()
        if item_is_stock and not warehouse:
            frappe.throw(
                _("Resolve a Warehouse before converting Item {0}.").format(item_code)
            )
        uom = order_row.uom or frappe.db.get_value("Item", item_code, "stock_uom")
        gross_rate = flt(order_row.approved_rate or order_row.listed_rate)
        invoice_row = invoice.append(
            "items",
            {
                "item_code": item_code,
                "qty": flt(order_row.approved_qty),
                "uom": uom,
                "conversion_factor": _conversion_factor(item_code, uom),
                "warehouse": warehouse if item_is_stock else "",
                "price_list_rate": gross_rate,
                "rate": gross_rate,
                "discount_percentage": flt(order_row.discount_percentage),
            },
        )
        mapped_rows.append((order_row, invoice_row, gross_rate))

    if flt(order.delivery_fee) > 0:
        fee_item = _delivery_fee_item()
        if not fee_item:
            frappe.throw(
                _("Configure Delivery Fee Item in Pharmacy POS Settings before conversion.")
            )
        fee_values = frappe.db.get_value(
            "Item",
            fee_item,
            ["disabled", "is_stock_item", "stock_uom"],
            as_dict=True,
        )
        if not fee_values:
            frappe.throw(_("Delivery Fee Item {0} was not found.").format(fee_item))
        if cint(fee_values.get("disabled")):
            frappe.throw(_("Delivery Fee Item {0} is disabled.").format(fee_item))
        if cint(fee_values.get("is_stock_item")):
            frappe.throw(_("Delivery Fee Item must be a non-stock Item."))
        fee_rate = flt(order.delivery_fee)
        fee_row = invoice.append(
            "items",
            {
                "item_code": fee_item,
                "qty": 1,
                "uom": fee_values.get("stock_uom"),
                "conversion_factor": 1,
                "price_list_rate": fee_rate,
                "rate": fee_rate,
                "discount_percentage": 0,
            },
        )
        mapped_rows.append((None, fee_row, fee_rate))

    if not invoice.items:
        frappe.throw(_("No approved Online Order items are available for conversion."))

    invoice.run_method("set_missing_values")

    # Keep the reviewed Online Order prices authoritative for this draft.
    for order_row, invoice_row, gross_rate in mapped_rows:
        invoice_row.price_list_rate = gross_rate
        invoice_row.rate = gross_rate
        invoice_row.discount_percentage = (
            flt(order_row.discount_percentage) if order_row else 0
        )

    invoice.apply_discount_on = "Net Total"
    invoice.discount_amount = flt(order.discount_amount)
    invoice.calculate_taxes_and_totals()

    difference = abs(flt(invoice.grand_total) - flt(order.grand_total))
    if difference > 0.01:
        frappe.throw(
            _(
                "Sales Invoice draft total ({0}) does not match Online Order total ({1}). "
                "Review taxes, rates and delivery fee before conversion."
            ).format(invoice.grand_total, order.grand_total)
        )

    return invoice, mapped_rows


@frappe.whitelist()
def create_sales_invoice_draft(order_name: str):
    order = frappe.get_doc("Online Order", order_name)
    if not frappe.has_permission("Online Order", "write", doc=order):
        frappe.throw(
            _("You do not have permission to update this Online Order."),
            frappe.PermissionError,
        )
    if not frappe.has_permission("Sales Invoice", "create"):
        frappe.throw(
            _("You do not have permission to create Sales Invoice."),
            frappe.PermissionError,
        )
    if not _has_field("Sales Invoice", "custom_online_order"):
        frappe.throw(_("Sales Invoice.custom_online_order is not installed."))

    # Serialize conversion requests for the same order to prevent double-click races.
    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()

    if order.status not in {"Confirmed", "Preparing"}:
        frappe.throw(
            _("Sales Invoice Draft can only be created from Confirmed or Preparing orders.")
        )
    if order.sales_order:
        frappe.throw(
            _("This Online Order is already using the Sales Order conversion path: {0}").format(
                order.sales_order
            )
        )
    if order.sales_invoice:
        linked_docstatus = cint(
            frappe.db.get_value("Sales Invoice", order.sales_invoice, "docstatus")
        )
        if linked_docstatus != 2:
            frappe.throw(
                _("Sales Invoice {0} is already linked to this Online Order.").format(
                    order.sales_invoice
                )
            )
        order.sales_invoice = None
        order.conversion_path = None
        order.converted_by = None
        order.converted_at = None
        for order_row in order.items:
            order_row.sales_invoice_item = None
        order.save(ignore_permissions=True)

    duplicate = frappe.db.get_value(
        "Sales Invoice",
        {"custom_online_order": order.name, "docstatus": ["<", 2]},
        "name",
    )
    if duplicate:
        frappe.throw(
            _("Sales Invoice {0} already exists for this Online Order.").format(duplicate)
        )

    order._guard_confirmation_ready()
    invoice, mapped_rows = _build_sales_invoice_draft(order)

    # The Sales Invoice validate hook normally resets downstream readiness when a
    # user edits an existing draft. Initial controlled conversion is different:
    # saving the Online Order from that hook would advance its modified timestamp
    # while this function still holds an older document instance, causing a
    # TimestampMismatchError immediately after invoice.insert().
    invoice.flags.controlled_online_order_conversion = True
    order_row_links = [
        (order_row.name if order_row else "", invoice_row)
        for order_row, invoice_row, _gross_rate in mapped_rows
    ]
    invoice.insert()

    if cint(invoice.docstatus) != 0 or cint(invoice.update_stock):
        frappe.throw(_("Controlled conversion must create a non-stock Draft Sales Invoice."))

    # Reload after insert so any legitimate insert-time integration cannot leave
    # the Online Order instance stale. Reconnect child rows by their stable names.
    invoice_item_links = [
        (order_row_name, invoice_row.name)
        for order_row_name, invoice_row in order_row_links
        if order_row_name
    ]
    order.reload()
    order_rows_by_name = {row.name: row for row in order.items}

    order.sales_invoice = invoice.name
    order.conversion_path = "Direct Sales Invoice"
    order.converted_by = frappe.session.user
    order.converted_at = now_datetime()
    for order_row_name, invoice_row_name in invoice_item_links:
        order_row = order_rows_by_name.get(order_row_name)
        if not order_row:
            frappe.throw(
                _("Online Order item row changed during controlled conversion: {0}.").format(
                    order_row_name
                )
            )
        order_row.sales_invoice_item = invoice_row_name
    order.save(ignore_permissions=True)
    order.add_comment(
        "Info",
        _("Sales Invoice Draft {0} created from this Online Order.").format(invoice.name),
    )

    return {
        "online_order": order.name,
        "sales_invoice": invoice.name,
        "docstatus": cint(invoice.docstatus),
        "update_stock": cint(invoice.update_stock),
        "grand_total": flt(invoice.grand_total),
        "status": order.status,
    }


@frappe.whitelist()
def submit_linked_sales_invoice(order_name: str):
    order = frappe.get_doc("Online Order", order_name)
    if not frappe.has_permission("Online Order", "write", doc=order):
        frappe.throw(
            _("You do not have permission to update this Online Order."),
            frappe.PermissionError,
        )
    if not order.sales_invoice:
        frappe.throw(_("Create and link a Sales Invoice Draft first."))

    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()

    invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)
    if not frappe.has_permission("Sales Invoice", "submit", doc=invoice):
        frappe.throw(
            _("You do not have permission to submit Sales Invoice."),
            frappe.PermissionError,
        )
    if cint(invoice.docstatus) == 1:
        frappe.throw(_("Sales Invoice {0} is already submitted.").format(invoice.name))
    if cint(invoice.docstatus) == 2:
        frappe.throw(_("Sales Invoice {0} is cancelled.").format(invoice.name))
    if invoice.get("custom_online_order") != order.name:
        frappe.throw(_("The linked Sales Invoice does not point back to this Online Order."))
    if order.status not in {"Confirmed", "Preparing"}:
        frappe.throw(
            _("A linked Sales Invoice can only be submitted from Confirmed or Preparing orders.")
        )

    invoice.submit()
    order.reload()

    return {
        "online_order": order.name,
        "online_order_status": order.status,
        "sales_invoice": invoice.name,
        "sales_invoice_docstatus": cint(invoice.docstatus),
        "update_stock": cint(invoice.update_stock),
        "grand_total": flt(invoice.grand_total),
    }


@frappe.whitelist()
def create_pickup_payment_draft(
    order_name: str,
    mode_of_payment: str,
    amount: float | None = None,
    reference_no: str | None = None,
    reference_date: str | None = None,
    collection_notes: str | None = None,
):
    order = frappe.get_doc("Online Order", order_name)
    if not frappe.has_permission("Online Order", "write", doc=order):
        frappe.throw(
            _("You do not have permission to update this Online Order."),
            frappe.PermissionError,
        )
    if not frappe.has_permission("Payment Entry", "create"):
        frappe.throw(
            _("You do not have permission to create Payment Entry."),
            frappe.PermissionError,
        )
    if not _has_field("Payment Entry", "custom_online_order"):
        frappe.throw(_("Payment Entry.custom_online_order is not installed."))

    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()

    if order.fulfilment_method != "Pharmacy Pickup":
        frappe.throw(_("Pickup payment can only be created for Pharmacy Pickup orders."))
    if order.status != "Ready for Pickup":
        frappe.throw(_("Online Order must be Ready for Pickup before collection."))
    if order.payment_timing == "No Collection Required":
        frappe.throw(_("This Online Order does not require collection."))
    if not order.sales_invoice:
        frappe.throw(_("A linked Sales Invoice is required."))

    invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)
    if cint(invoice.docstatus) != 1:
        frappe.throw(_("The linked Sales Invoice must be submitted."))
    if invoice.get("custom_online_order") != order.name:
        frappe.throw(_("The linked Sales Invoice does not point back to this Online Order."))

    from pharma_erp.pharma_erp import payment_card_management as shift_finance

    active_shift = shift_finance._current_open_shift(order.company)
    if not active_shift:
        frappe.throw(
            _("An open Pharmacy Shift is required before pickup collection.")
        )
    active_shift_name = str(active_shift.name or "").strip()
    invoice_sales_shift = str(
        invoice.get("custom_pharmacy_shift") or ""
    ).strip()
    invoice_delivery_shift = str(
        invoice.get("custom_delivery_shift") or ""
    ).strip()
    if not invoice_sales_shift:
        frappe.throw(
            _("Sales Invoice must be linked to a Pharmacy Shift before pickup collection.")
        )
    if not frappe.db.exists("Pharmacy Shift Closing", invoice_sales_shift):
        frappe.throw(
            _("Sales Invoice Pharmacy Shift {0} was not found.").format(
                invoice_sales_shift
            )
        )
    if invoice_delivery_shift:
        frappe.throw(
            _(
                "Pharmacy Pickup Sales Invoice must not use Delivery Shift {0}."
            ).format(invoice_delivery_shift)
        )

    outstanding = max(0, flt(invoice.outstanding_amount))
    if outstanding <= PAYMENT_TOLERANCE:
        frappe.throw(_("The linked Sales Invoice has no outstanding amount to collect."))

    requested_amount = flt(amount or outstanding)
    if abs(requested_amount - outstanding) > PAYMENT_TOLERANCE:
        frappe.throw(
            _("Pickup collection amount must equal the current outstanding amount: {0}.").format(
                outstanding
            )
        )

    stale_payment_link_cleared = False
    if order.payment_entry:
        if not frappe.db.exists("Payment Entry", order.payment_entry):
            order.payment_entry = None
            stale_payment_link_cleared = True
        elif cint(frappe.db.get_value("Payment Entry", order.payment_entry, "docstatus")) < 2:
            frappe.throw(
                _("Payment Entry {0} is already linked to this Online Order.").format(
                    order.payment_entry
                )
            )
        else:
            order.payment_entry = None
            stale_payment_link_cleared = True

    if stale_payment_link_cleared:
        order.payment_status = "Pending Collection"
        order.verified_paid_amount = 0
        order.payment_verified_by = None
        order.payment_verified_at = None
        order.save(ignore_permissions=True)
        order.reload()

    duplicate = frappe.db.get_value(
        "Payment Entry",
        {"custom_online_order": order.name, "docstatus": ["<", 2]},
        "name",
    )
    if duplicate:
        frappe.throw(
            _("Active Payment Entry {0} already exists for this Online Order.").format(
                duplicate
            )
        )

    bank_account = _mode_of_payment_account(mode_of_payment, order.company)
    account_values = frappe.db.get_value(
        "Account",
        bank_account,
        ["account_type", "account_currency"],
        as_dict=True,
    )
    account_type = str(account_values.get("account_type") or "")
    reference_no = str(reference_no or "").strip()
    if account_type == "Bank" and not reference_no:
        frappe.throw(_("Reference No is required for bank collection."))

    receivable_values = frappe.db.get_value(
        "Account",
        invoice.debit_to,
        ["company", "is_group", "disabled", "account_type", "account_currency"],
        as_dict=True,
    )
    if not receivable_values:
        frappe.throw(_("Sales Invoice receivable account was not found."))
    if receivable_values.get("company") != order.company:
        frappe.throw(_("Sales Invoice receivable account belongs to another company."))
    if cint(receivable_values.get("is_group")) or cint(receivable_values.get("disabled")):
        frappe.throw(_("Sales Invoice receivable account is not available for posting."))
    if receivable_values.get("account_type") != "Receivable":
        frappe.throw(_("Sales Invoice debit account must be a Receivable account."))

    company_currency = frappe.get_cached_value(
        "Company", order.company, "default_currency"
    )
    party_currency = (
        receivable_values.get("account_currency")
        or invoice.get("party_account_currency")
        or company_currency
    )
    destination_currency = account_values.get("account_currency") or company_currency
    received_amount = requested_amount
    if party_currency != destination_currency:
        if destination_currency == company_currency:
            received_amount = flt(requested_amount * flt(invoice.conversion_rate or 1), 6)
        else:
            frappe.throw(
                _("Pickup collection does not support this account currency combination.")
            )

    from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
        get_accounting_dimensions,
    )
    from pharma_erp.pharma_erp.delivery_collection import (
        ControlledDeliveryPaymentEntry,
    )

    posting_date = today()
    payment_entry = ControlledDeliveryPaymentEntry(
        {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "company": order.company,
            "company_currency": company_currency,
            "cost_center": invoice.get("cost_center"),
            "posting_date": posting_date,
            "reference_date": reference_date or posting_date,
            "mode_of_payment": mode_of_payment,
            "party_type": "Customer",
            "party": order.customer,
            "contact_person": invoice.get("contact_person"),
            "paid_from": invoice.debit_to,
            "paid_to": bank_account,
            "paid_from_account_currency": party_currency,
            "paid_to_account_currency": destination_currency,
            "paid_from_account_type": receivable_values.get("account_type"),
            "paid_to_account_type": account_type,
            "paid_amount": requested_amount,
            "received_amount": received_amount,
            "letter_head": invoice.get("letter_head"),
        }
    )

    payment_entry.project = invoice.get("project") or next(
        (
            row.get("project")
            for row in invoice.get("items") or []
            if row.get("project")
        ),
        None,
    )
    for dimension in get_accounting_dimensions():
        payment_entry.set(dimension, invoice.get(dimension))

    payment_entry.reference_no = reference_no or order.name
    payment_entry.reference_date = reference_date or posting_date
    payment_entry.remarks = _(
        "Pharmacy pickup collection for Online Order {0} against Sales Invoice {1}."
    ).format(order.name, invoice.name)
    payment_entry.custom_online_order = order.name
    if payment_entry.meta.has_field("custom_pharmacy_shift"):
        payment_entry.custom_pharmacy_shift = active_shift_name
    if payment_entry.meta.has_field("custom_delivery_shift"):
        payment_entry.custom_delivery_shift = None

    payment_entry.append(
        "references",
        {
            "reference_doctype": "Sales Invoice",
            "reference_name": invoice.name,
            "allocated_amount": outstanding,
        },
    )

    previous_ignore_account_permission = bool(
        getattr(frappe.flags, "ignore_account_permission", False)
    )
    frappe.flags.ignore_account_permission = True
    try:
        payment_entry.flags.ignore_permissions = True
        payment_entry.insert(ignore_permissions=True)
    finally:
        frappe.flags.ignore_account_permission = previous_ignore_account_permission

    if cint(payment_entry.docstatus) != 0:
        frappe.throw(_("Pickup collection must create a Draft Payment Entry only."))
    if payment_entry.get("custom_pharmacy_shift") != active_shift_name:
        frappe.throw(_("Pickup Payment Entry was not linked to the active Pharmacy Shift."))
    if payment_entry.get("custom_delivery_shift"):
        frappe.throw(_("Pickup Payment Entry must not use a Delivery Shift."))

    order.payment_entry = payment_entry.name
    order.payment_status = "Collection Draft Created"
    if collection_notes:
        order.payment_review_notes = str(collection_notes).strip()
    order.save(ignore_permissions=True)

    _set_invoice_collection_fields(
        invoice.name,
        {
            "custom_collection_payment_entry": payment_entry.name,
            "custom_collection_verification_status": "Awaiting Confirmation",
            "custom_collection_received_by": "Pharmacy Direct",
            "custom_collection_review_notes": str(collection_notes or "").strip(),
        },
    )
    order.add_comment(
        "Info",
        _(
            "Pickup Payment Entry Draft {0} created for {1} in Pharmacy Shift {2}."
        ).format(payment_entry.name, outstanding, active_shift_name),
    )

    return {
        "online_order": order.name,
        "sales_invoice": invoice.name,
        "payment_entry": payment_entry.name,
        "payment_entry_docstatus": cint(payment_entry.docstatus),
        "pharmacy_shift": active_shift_name,
        "amount": flt(outstanding),
        "payment_status": order.payment_status,
    }


@frappe.whitelist()
def complete_pharmacy_pickup(order_name: str, pickup_notes: str | None = None):
    order = frappe.get_doc("Online Order", order_name)
    if not frappe.has_permission("Online Order", "write", doc=order):
        frappe.throw(
            _("You do not have permission to update this Online Order."),
            frappe.PermissionError,
        )

    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()

    if order.fulfilment_method != "Pharmacy Pickup":
        frappe.throw(_("This action is only valid for Pharmacy Pickup orders."))
    if order.status != "Ready for Pickup":
        frappe.throw(_("Online Order must be Ready for Pickup before completion."))
    if not order.sales_invoice:
        frappe.throw(_("A linked Sales Invoice is required."))

    invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)
    if cint(invoice.docstatus) != 1:
        frappe.throw(_("The linked Sales Invoice must be submitted."))

    no_collection = order.payment_timing == "No Collection Required"
    if no_collection:
        order.payment_status = "No Collection Required"
        order.verified_paid_amount = 0
        _set_invoice_collection_fields(
            invoice.name,
            {
                "custom_collection_verification_status": "Not Required",
                "custom_confirmed_customer_payment_method": "No Collection",
                "custom_collection_received_by": "No Collection",
                "custom_collection_confirmed_by": frappe.session.user,
                "custom_collection_confirmed_at": now_datetime(),
            },
        )
    else:
        outstanding = max(0, flt(invoice.outstanding_amount))
        if outstanding > PAYMENT_TOLERANCE:
            frappe.throw(
                _("Collect the full Sales Invoice outstanding amount before completing pickup: {0}.").format(
                    outstanding
                )
            )
        if not order.payment_entry or not frappe.db.exists("Payment Entry", order.payment_entry):
            frappe.throw(_("A submitted pickup Payment Entry is required before completion."))
        payment_entry = frappe.get_doc("Payment Entry", order.payment_entry)
        if cint(payment_entry.docstatus) != 1:
            frappe.throw(_("The linked pickup Payment Entry must be submitted."))
        if payment_entry.get("custom_online_order") != order.name:
            frappe.throw(_("The linked Payment Entry does not point back to this Online Order."))
        if not _payment_entry_references_invoice(payment_entry, invoice.name):
            frappe.throw(_("The linked Payment Entry is not allocated to the active Sales Invoice."))

        order.payment_status = "Verified"
        order.verified_paid_amount = flt(invoice.grand_total)
        order.payment_verified_by = frappe.session.user
        order.payment_verified_at = now_datetime()

    order.status = "Completed"
    if order.meta.has_field("pickup_completed_by"):
        order.pickup_completed_by = frappe.session.user
    if order.meta.has_field("pickup_completed_at"):
        order.pickup_completed_at = now_datetime()
    if order.meta.has_field("pickup_completion_notes"):
        order.pickup_completion_notes = str(pickup_notes or "").strip()
    order.save(ignore_permissions=True)
    order.add_comment(
        "Info",
        _("Pharmacy pickup completed by {0}.").format(frappe.session.user),
    )

    return {
        "online_order": order.name,
        "status": order.status,
        "sales_invoice": invoice.name,
        "payment_entry": order.payment_entry,
        "payment_status": order.payment_status,
        "verified_paid_amount": flt(order.verified_paid_amount),
    }


@frappe.whitelist()
def sync_home_delivery_execution(order_name: str):
    order = frappe.get_doc("Online Order", order_name)
    if not frappe.has_permission("Online Order", "write", doc=order):
        frappe.throw(
            _("You do not have permission to update this Online Order."),
            frappe.PermissionError,
        )

    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()

    if order.fulfilment_method != "Home Delivery":
        frappe.throw(_("This action is only valid for Home Delivery orders."))
    if not order.sales_invoice:
        frappe.throw(_("A linked Sales Invoice is required."))

    invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)
    before_status = order.status
    before_payment_status = order.payment_status
    result = _sync_home_delivery_order_from_invoice(order, invoice, save=True)

    if before_status != order.status or before_payment_status != order.payment_status:
        order.add_comment(
            "Info",
            _(
                "Home Delivery state refreshed from Sales Invoice {0}: order {1}, payment {2}."
            ).format(invoice.name, order.status, order.payment_status),
        )

    return result


@frappe.whitelist()
def complete_home_delivery(order_name: str, completion_notes: str | None = None):
    order = frappe.get_doc("Online Order", order_name)
    if not frappe.has_permission("Online Order", "write", doc=order):
        frappe.throw(
            _("You do not have permission to update this Online Order."),
            frappe.PermissionError,
        )

    frappe.db.sql(
        "select name from `tabOnline Order` where name=%s for update",
        (order.name,),
    )
    order.reload()

    if order.fulfilment_method != "Home Delivery":
        frappe.throw(_("This action is only valid for Home Delivery orders."))
    if order.status != "Delivered":
        frappe.throw(_("Online Order must be Delivered before completion."))
    if not order.sales_invoice:
        frappe.throw(_("A linked Sales Invoice is required."))

    invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)
    _sync_home_delivery_order_from_invoice(order, invoice, save=False)

    if order.status != "Delivered":
        frappe.throw(
            _("The linked Sales Invoice is not currently marked Delivered.")
        )

    collection = _home_delivery_collection_state(order, invoice)
    if not collection["collection_ready"]:
        if collection["outstanding"] > PAYMENT_TOLERANCE:
            frappe.throw(
                _("Confirm delivery collection first. Remaining outstanding: {0}.").format(
                    collection["outstanding"]
                )
            )
        frappe.throw(
            _("Delivery collection verification must be Confirmed before completion.")
        )

    order.status = "Completed"
    if order.meta.has_field("delivery_completed_by"):
        order.delivery_completed_by = frappe.session.user
    if order.meta.has_field("delivery_completed_at"):
        order.delivery_completed_at = now_datetime()
    if order.meta.has_field("delivery_completion_notes"):
        order.delivery_completion_notes = str(completion_notes or "").strip()
    order.save(ignore_permissions=True)
    order.add_comment(
        "Info",
        _("Home Delivery completed by {0}.").format(frappe.session.user),
    )

    return {
        "online_order": order.name,
        "status": order.status,
        "sales_invoice": invoice.name,
        "invoice_delivery_status": invoice.get("custom_delivery_status"),
        "payment_entry": order.payment_entry,
        "payment_status": order.payment_status,
        "verified_paid_amount": flt(order.verified_paid_amount),
    }


@frappe.whitelist()
def transition_status(order_name: str, target_status: str, reason: str | None = None):
    order = frappe.get_doc("Online Order", order_name)
    if not frappe.has_permission("Online Order", "write", doc=order):
        frappe.throw(_("You do not have permission to update this Online Order."), frappe.PermissionError)

    target_status = str(target_status or "").strip()
    if target_status not in ALLOWED_TRANSITIONS:
        frappe.throw(_("Invalid Online Order status: {0}").format(target_status))

    if (
        target_status == "Completed"
        and order.fulfilment_method == "Pharmacy Pickup"
    ):
        frappe.throw(_("Use the controlled Complete Pharmacy Pickup action."))

    if order.fulfilment_method == "Home Delivery" and target_status in {
        "Ready for Delivery",
        "Out for Delivery",
        "Delivered",
        "Returned",
        "Completed",
    }:
        frappe.throw(
            _(
                "Use Delivery Management for execution, then use Refresh Delivery & Collection Status or Complete Home Delivery."
            )
        )

    if target_status == "Cancelled":
        order.cancellation_reason = str(reason or order.cancellation_reason or "").strip()
    elif target_status == "Rejected":
        order.rejection_reason = str(reason or order.rejection_reason or "").strip()
    elif target_status == "On Hold":
        order.on_hold_reason = str(reason or order.on_hold_reason or "").strip()

    order.status = target_status
    order.save()
    return {
        "name": order.name,
        "status": order.status,
        "grand_total": order.grand_total,
    }
