from __future__ import annotations

import html
import json
import re
from collections import Counter
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, strip_html


REVIEW_QUEUE_STATUSES = (
    "Placed",
    "Under Review",
    "Prescription Review",
    "Stock Review",
    "Partially Available",
    "Awaiting Customer Decision",
    "Ready for Payment",
    "Payment Verification",
    "Confirmed",
    "Preparing",
    "Ready for Pickup",
    "Ready for Delivery",
    "On Hold",
)

PRESCRIPTION_HEADER_DECISIONS = {
    "Approved",
    "Partially Approved",
    "Rejected",
    "Replacement Requested",
}
PRESCRIPTION_ITEM_DECISIONS = {
    "Approved",
    "Rejected",
    "Alternative Suggested",
}
STOCK_DECISIONS = {
    "Available",
    "Partially Available",
    "Unavailable",
    "Removed",
    "Alternative Suggested",
}
TERMINAL_STATUSES = {"Confirmed", "Completed", "Rejected", "Cancelled"}

DIRECT_TRANSITIONS = {
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
    "On Hold": {
        "Under Review",
        "Prescription Review",
        "Stock Review",
        "Ready for Payment",
        "Preparing",
        "Rejected",
        "Cancelled",
    },
}


def _clean_text(value: Any, limit: int = 500) -> str:
    return " ".join(strip_html(str(value or "")).split())[:limit]


def _json_list(value: str | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if isinstance(value, list):
        parsed = value
    elif not value:
        parsed = []
    else:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            frappe.throw(_("Invalid review rows."))
    if not isinstance(parsed, list) or any(not isinstance(row, dict) for row in parsed):
        frappe.throw(_("Invalid review rows."))
    return parsed


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
        frappe.throw(_("You do not have permission for this Online Order."), frappe.PermissionError)
    if order.status in TERMINAL_STATUSES:
        frappe.throw(_("This Online Order is already locked or terminal."))
    return order


def _save_status(order, target_status: str):
    target_status = _clean_text(target_status, 60)
    if order.status == target_status:
        return order
    allowed = DIRECT_TRANSITIONS.get(str(order.status or ""), set())
    if target_status not in allowed:
        frappe.throw(
            _("Status transition from {0} to {1} is not allowed.").format(
                frappe.bold(order.status), frappe.bold(target_status)
            )
        )
    order.status = target_status
    order.save(ignore_permissions=True)
    return order


def _prepare_review_stage(order, target_stage: str):
    if order.status == "Placed":
        _save_status(order, "Under Review")
    if order.status == "On Hold":
        _save_status(order, target_stage)
        return order
    if order.status == target_stage:
        return order
    if target_stage == "Prescription Review" and order.status == "Under Review":
        _save_status(order, target_stage)
    elif target_stage == "Stock Review" and order.status in {
        "Under Review",
        "Prescription Review",
        "Partially Available",
        "Awaiting Customer Decision",
    }:
        _save_status(order, target_stage)
    return order


def _warehouse_state(warehouse: str, company: str | None) -> dict[str, Any]:
    values = frappe.db.get_value(
        "Warehouse",
        warehouse,
        ["name", "company", "is_group", "disabled"],
        as_dict=True,
    )
    if not values:
        frappe.throw(_("Warehouse {0} was not found.").format(frappe.bold(warehouse)))
    if cint(values.get("is_group")):
        frappe.throw(_("Warehouse {0} is a group warehouse.").format(frappe.bold(warehouse)))
    if cint(values.get("disabled")):
        frappe.throw(_("Warehouse {0} is disabled.").format(frappe.bold(warehouse)))
    if company and values.get("company") and values.get("company") != company:
        frappe.throw(_("Warehouse {0} belongs to another company.").format(frappe.bold(warehouse)))
    return values


def _item_stock(item_code: str, warehouse: str | None) -> dict[str, Any]:
    item = frappe.db.get_value(
        "Item",
        item_code,
        ["item_name", "stock_uom", "is_stock_item", "disabled"],
        as_dict=True,
    )
    if not item:
        frappe.throw(_("Item {0} was not found.").format(frappe.bold(item_code)))
    if cint(item.get("disabled")):
        frappe.throw(_("Item {0} is disabled.").format(frappe.bold(item_code)))

    bin_values: dict[str, Any] = {}
    if warehouse and cint(item.get("is_stock_item")):
        bin_values = frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            ["actual_qty", "projected_qty", "reserved_qty"],
            as_dict=True,
        ) or {}

    return {
        "item_name": item.get("item_name") or item_code,
        "stock_uom": item.get("stock_uom") or "",
        "is_stock_item": cint(item.get("is_stock_item")),
        "actual_qty": flt(bin_values.get("actual_qty")),
        "projected_qty": flt(bin_values.get("projected_qty")),
        "reserved_qty": flt(bin_values.get("reserved_qty")),
    }


def _display_availability(row) -> str:
    if row.alternative_item and not cint(row.alternative_accepted) and row.availability_status in {
        "Unavailable",
        "Removed",
    }:
        return "Alternative Suggested"
    return row.availability_status or "Pending Review"


def _row_snapshot(order, row) -> dict[str, Any]:
    selected_warehouse = str(row.warehouse or order.warehouse or "").strip()
    stock = _item_stock(row.item_code, selected_warehouse)
    alternative_stock = None
    if row.alternative_item:
        alternative_stock = _item_stock(row.alternative_item, selected_warehouse)

    return {
        "name": row.name,
        "idx": row.idx,
        "item_code": row.item_code,
        "item_name": row.item_name_snapshot or stock["item_name"],
        "requested_qty": flt(row.requested_qty),
        "approved_qty": flt(row.approved_qty),
        "uom": row.uom or stock["stock_uom"],
        "warehouse": selected_warehouse,
        "listed_rate": flt(row.listed_rate),
        "approved_rate": flt(row.approved_rate),
        "net_amount": flt(row.net_amount),
        "availability_status": row.availability_status,
        "display_availability_status": _display_availability(row),
        "stock_review_status": row.stock_review_status,
        "requires_prescription": cint(row.requires_prescription_snapshot),
        "prescription_item_status": row.prescription_item_status,
        "prescription_item_notes": row.prescription_item_notes or "",
        "alternative_item": row.alternative_item or "",
        "alternative_accepted": cint(row.alternative_accepted),
        "is_stock_item": stock["is_stock_item"],
        "actual_qty": stock["actual_qty"],
        "projected_qty": stock["projected_qty"],
        "reserved_qty": stock["reserved_qty"],
        "alternative_actual_qty": (
            alternative_stock["actual_qty"] if alternative_stock else 0.0
        ),
    }


def _review_blockers(order, rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    review: list[str] = []
    confirmation: list[str] = []

    active_rows = [
        row
        for row in rows
        if row["availability_status"] not in {"Unavailable", "Removed"}
        and row["approved_qty"] > 0
    ]

    if not active_rows:
        review.append(_("No approved and available order row remains."))

    if cint(order.prescription_required):
        if not order.prescription_attachment:
            review.append(_("Prescription attachment is missing."))
        if order.prescription_review_status not in {"Approved", "Partially Approved"}:
            review.append(_("Prescription review is not approved."))
        for row in active_rows:
            if row["requires_prescription"] and row["prescription_item_status"] not in {
                "Approved",
                "Alternative Suggested",
            }:
                review.append(
                    _("Prescription decision is incomplete for item {0}.").format(
                        row["item_code"]
                    )
                )

    for row in active_rows:
        if row["stock_review_status"] not in {"Reviewed", "Approved"}:
            review.append(
                _("Stock review is incomplete for item {0}.").format(row["item_code"])
            )
        if row["is_stock_item"] and not row["warehouse"]:
            review.append(
                _("Warehouse is missing for stock item {0}.").format(row["item_code"])
            )

    if any(row["display_availability_status"] == "Alternative Suggested" for row in rows):
        review.append(_("An alternative item is awaiting customer decision."))

    if not order.customer:
        confirmation.append(_("Customer is not resolved or linked."))
    if order.customer_resolution_status not in {"Matched", "Confirmed"}:
        confirmation.append(_("Customer Resolution Status is not Matched or Confirmed."))
    if order.fulfilment_method == "Home Delivery":
        if not order.address_line1 or not order.city:
            confirmation.append(_("Home Delivery address is incomplete."))
        if not order.delivery_zone:
            confirmation.append(_("Delivery Zone is not selected."))
        if not order.warehouse:
            confirmation.append(_("Order Warehouse is not selected."))
    if order.payment_timing == "Prepaid" and order.payment_status != "Verified":
        confirmation.append(_("Prepaid payment is not verified."))
    if order.payment_timing == "Partially Prepaid" and order.payment_status not in {
        "Verified",
        "Partially Verified",
    }:
        confirmation.append(_("Partial prepayment is not verified."))

    return {
        "review": list(dict.fromkeys(review)),
        "confirmation": list(dict.fromkeys(confirmation)),
    }


def _snapshot(order) -> dict[str, Any]:
    rows = [_row_snapshot(order, row) for row in order.items]
    blockers = _review_blockers(order, rows)
    return {
        "name": order.name,
        "status": order.status,
        "source_channel": order.source_channel,
        "external_reference": order.external_reference,
        "customer": order.customer or "",
        "customer_name": order.customer_name,
        "mobile_no": order.mobile_no,
        "email_id": order.email_id or "",
        "customer_resolution_status": order.customer_resolution_status or "Unresolved",
        "customer_resolution_method": getattr(order, "custom_customer_resolution_method", "") or "",
        "website_user": getattr(order, "custom_website_user", "") or "",
        "customer_address": order.customer_address or "",
        "fulfilment_method": order.fulfilment_method,
        "company": order.company,
        "warehouse": order.warehouse or "",
        "delivery_zone": order.delivery_zone or "",
        "currency": order.currency,
        "grand_total": flt(order.grand_total),
        "prescription_required": cint(order.prescription_required),
        "prescription_attachment": order.prescription_attachment or "",
        "prescription_review_status": order.prescription_review_status,
        "prescription_review_notes": order.prescription_review_notes or "",
        "prescription_reviewed_by": order.prescription_reviewed_by or "",
        "prescription_reviewed_at": order.prescription_reviewed_at,
        "delivery_fee": flt(order.delivery_fee),
        "delivery_fee_rule": order.delivery_fee_rule or "",
        "estimated_delivery_time_mins": cint(order.estimated_delivery_time_mins),
        "final_confirmation_readiness_status": getattr(
            order, "custom_final_confirmation_readiness_status", "Pending"
        ) or "Pending",
        "final_confirmation_checked_by": getattr(
            order, "custom_final_confirmation_checked_by", ""
        ) or "",
        "final_confirmation_checked_at": getattr(
            order, "custom_final_confirmation_checked_at", None
        ),
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
        ) or "Pending",
        "order_confirmation_readiness_status": getattr(
            order, "custom_order_confirmation_readiness_status", "Pending"
        ) or "Pending",
        "conversion_readiness_status": getattr(
            order, "custom_conversion_readiness_status", "Pending"
        ) or "Pending",
        "conversion_execution_status": getattr(
            order, "custom_conversion_execution_status", "Pending"
        ) or "Pending",
        "post_conversion_integrity_status": getattr(
            order, "custom_post_conversion_integrity_status", "Pending"
        ) or "Pending",
        "submit_readiness_status": getattr(
            order, "custom_submit_readiness_status", "Pending"
        ) or "Pending",
        "submit_execution_status": getattr(
            order, "custom_submit_execution_status", "Pending"
        ) or "Pending",
        "confirmed_at": order.confirmed_at,
        "sales_order": order.sales_order or "",
        "sales_invoice": order.sales_invoice or "",
        "items": rows,
        "review_blockers": blockers["review"],
        "confirmation_blockers": blockers["confirmation"],
        "review_ready": cint(not blockers["review"]),
        "confirmation_ready": cint(not blockers["review"] and not blockers["confirmation"]),
        "creates_quotation": 0,
        "creates_sales_order": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
    }


def _audit_comment(order, title: str, details: dict[str, Any]) -> None:
    safe_details = json.dumps(details, ensure_ascii=False, sort_keys=True, default=str)
    order.add_comment(
        "Info",
        "<b>{0}</b><br><code>{1}</code>".format(
            html.escape(title),
            html.escape(safe_details),
        ),
    )


@frappe.whitelist()
def get_review_queue(
    status: str | None = None,
    search: str | None = None,
    page_length: int | str = 50,
) -> dict[str, Any]:
    _require_authenticated_user()
    if not frappe.has_permission("Online Order", "read"):
        frappe.throw(_("You do not have permission to read Online Orders."), frappe.PermissionError)

    selected_status = _clean_text(status, 60)
    if selected_status and selected_status not in REVIEW_QUEUE_STATUSES:
        frappe.throw(_("Invalid review status filter."))

    filters: dict[str, Any] = {"docstatus": ["<", 2]}
    if selected_status:
        filters["status"] = selected_status
    else:
        filters["status"] = ["in", REVIEW_QUEUE_STATUSES]

    search_text = _clean_text(search, 140)
    or_filters = None
    if search_text:
        pattern = f"%{search_text}%"
        or_filters = {
            "name": ["like", pattern],
            "customer_name": ["like", pattern],
            "mobile_no": ["like", pattern],
            "external_reference": ["like", pattern],
        }

    rows = frappe.get_list(
        "Online Order",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "status",
            "source_channel",
            "external_reference",
            "customer",
            "customer_name",
            "mobile_no",
            "customer_resolution_status",
            "delivery_zone",
            "warehouse",
            "fulfilment_method",
            "grand_total",
            "currency",
            "prescription_required",
            "prescription_review_status",
            "payment_timing",
            "payment_method",
            "payment_status",
            "custom_final_confirmation_readiness_status",
            "custom_payment_selection_status",
            "custom_order_confirmation_readiness_status",
            "custom_conversion_readiness_status",
            "custom_conversion_execution_status",
            "custom_post_conversion_integrity_status",
            "custom_submit_readiness_status",
            "custom_submit_execution_status",
            "custom_submitted_at",
            "confirmed_at",
            "sales_order",
            "sales_invoice",
            "creation",
            "modified",
        ],
        order_by="creation desc",
        limit_page_length=max(1, min(200, cint(page_length) or 50)),
    )

    counts = Counter(str(row.get("status") or "") for row in rows)
    return {
        "orders": rows,
        "counts": dict(counts),
        "total": len(rows),
        "statuses": list(REVIEW_QUEUE_STATUSES),
        "controlled_review": 1,
        "controlled_submit_sync": 1,
        "financial_stock_documents_created": cint(
            any(
                str(row.get("custom_submit_execution_status") or "") == "Submitted"
                for row in rows
            )
        ),
    }


@frappe.whitelist()
def get_review_snapshot(online_order: str | None = None) -> dict[str, Any]:
    return _snapshot(_get_order(online_order, "read"))


@frappe.whitelist(methods=["POST"])
def start_review(online_order: str | None = None) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    original_status = order.status
    if order.status == "Placed":
        _save_status(order, "Under Review")
    elif order.status not in REVIEW_QUEUE_STATUSES:
        frappe.throw(_("The current order status cannot enter controlled review."))

    _audit_comment(
        order,
        _("Controlled Review Started"),
        {
            "from_status": original_status,
            "to_status": order.status,
            "reviewed_by": frappe.session.user,
            "source": "Step 3B.4",
        },
    )
    return _snapshot(order)


@frappe.whitelist(methods=["POST"])
def apply_prescription_review(
    online_order: str | None = None,
    decision: str | None = None,
    notes: str | None = None,
    item_decisions: str | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    _prepare_review_stage(order, "Prescription Review")

    if not cint(order.prescription_required):
        order.prescription_review_status = "Not Required"
        order.prescription_review_notes = _clean_text(notes, 1000)
        order.prescription_reviewed_by = frappe.session.user
        order.prescription_reviewed_at = now_datetime()
        for row in order.items:
            row.prescription_item_status = "Not Required"
            row.prescription_item_notes = ""
        if order.status == "Prescription Review":
            order.status = "Stock Review"
        order.save(ignore_permissions=True)
        _audit_comment(
            order,
            _("Prescription Review Completed"),
            {"decision": "Not Required", "reviewed_by": frappe.session.user},
        )
        return _snapshot(order)

    header_decision = _clean_text(decision, 60)
    if header_decision not in PRESCRIPTION_HEADER_DECISIONS:
        frappe.throw(_("Select a valid prescription review decision."))
    if header_decision in {"Approved", "Partially Approved"} and not order.prescription_attachment:
        frappe.throw(_("Attach the prescription before approving it."))

    supplied = _json_list(item_decisions)
    supplied_by_name = {
        _clean_text(row.get("child_name") or row.get("name"), 140): row
        for row in supplied
        if _clean_text(row.get("child_name") or row.get("name"), 140)
    }

    reviewed_rows: list[dict[str, Any]] = []
    prescription_rows = [row for row in order.items if cint(row.requires_prescription_snapshot)]
    if not prescription_rows:
        frappe.throw(_("The order no longer contains prescription-required rows."))

    for row in prescription_rows:
        supplied_row = supplied_by_name.get(row.name, {})
        row_decision = _clean_text(supplied_row.get("decision"), 60)
        if not row_decision:
            if header_decision == "Approved":
                row_decision = "Approved"
            elif header_decision == "Rejected":
                row_decision = "Rejected"
            elif header_decision == "Replacement Requested":
                row_decision = "Alternative Suggested"
        if row_decision not in PRESCRIPTION_ITEM_DECISIONS:
            frappe.throw(
                _("Select a prescription decision for item {0}.").format(
                    frappe.bold(row.item_code)
                )
            )

        row_notes = _clean_text(supplied_row.get("notes"), 500)
        alternative_item = _clean_text(supplied_row.get("alternative_item"), 140)

        if row_decision == "Approved":
            row.prescription_item_status = "Approved"
            row.prescription_item_notes = row_notes
            if row.availability_status in {"Unavailable", "Removed"} and not row.alternative_item:
                row.availability_status = "Pending Review"
            if flt(row.approved_qty) <= 0:
                row.approved_qty = flt(row.requested_qty)
        elif row_decision == "Rejected":
            row.prescription_item_status = "Rejected"
            row.prescription_item_notes = row_notes
            row.approved_qty = 0
            row.availability_status = "Removed"
            row.stock_review_status = "Rejected"
            row.alternative_item = ""
            row.alternative_accepted = 0
        else:
            if not alternative_item:
                frappe.throw(
                    _("Select an alternative item for prescription item {0}.").format(
                        frappe.bold(row.item_code)
                    )
                )
            if alternative_item == row.item_code:
                frappe.throw(_("Alternative Item must be different from the original item."))
            _item_stock(alternative_item, None)
            row.prescription_item_status = "Alternative Suggested"
            row.prescription_item_notes = row_notes
            row.alternative_item = alternative_item
            row.alternative_accepted = 0
            row.approved_qty = 0
            # Store as unavailable so the existing Online Order calculation does not
            # restore approved_qty before the customer accepts the alternative.
            row.availability_status = "Unavailable"
            row.stock_review_status = "Reviewed"

        reviewed_rows.append(
            {
                "item_code": row.item_code,
                "decision": row_decision,
                "alternative_item": row.alternative_item or "",
            }
        )

    approved_count = sum(
        1 for row in prescription_rows if row.prescription_item_status == "Approved"
    )
    if header_decision == "Partially Approved" and not (0 < approved_count < len(prescription_rows)):
        frappe.throw(_("Partially Approved requires a mix of approved and non-approved rows."))

    order.prescription_review_status = header_decision
    order.prescription_review_notes = _clean_text(notes, 1000)
    order.prescription_reviewed_by = frappe.session.user
    order.prescription_reviewed_at = now_datetime()

    if header_decision in {"Approved", "Partially Approved"}:
        if order.status == "Prescription Review":
            order.status = "Stock Review"
    else:
        order.status = "Prescription Review"

    order.save(ignore_permissions=True)
    _audit_comment(
        order,
        _("Controlled Prescription Review"),
        {
            "decision": header_decision,
            "rows": reviewed_rows,
            "notes": order.prescription_review_notes,
            "reviewed_by": frappe.session.user,
            "reviewed_at": order.prescription_reviewed_at,
        },
    )
    return _snapshot(order)


@frappe.whitelist(methods=["POST"])
def apply_stock_review(
    online_order: str | None = None,
    rows: str | list[dict[str, Any]] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    _prepare_review_stage(order, "Stock Review")

    supplied = _json_list(rows)
    if not supplied:
        frappe.throw(_("Add stock review rows."))
    supplied_by_name = {
        _clean_text(row.get("child_name") or row.get("name"), 140): row
        for row in supplied
        if _clean_text(row.get("child_name") or row.get("name"), 140)
    }
    if len(supplied_by_name) != len(order.items):
        frappe.throw(_("Stock review must include every Online Order row exactly once."))

    audit_rows: list[dict[str, Any]] = []
    has_partial = False
    has_unavailable = False
    has_alternative = False
    active_warehouses: set[str] = set()

    for order_row in order.items:
        input_row = supplied_by_name.get(order_row.name)
        if not input_row:
            frappe.throw(
                _("Stock review row is missing for item {0}.").format(
                    frappe.bold(order_row.item_code)
                )
            )

        decision = _clean_text(input_row.get("availability_status"), 60)
        if decision not in STOCK_DECISIONS:
            frappe.throw(
                _("Select a valid stock decision for item {0}.").format(
                    frappe.bold(order_row.item_code)
                )
            )

        approved_qty = flt(input_row.get("approved_qty"))
        requested_qty = flt(order_row.requested_qty)
        if abs(approved_qty - round(approved_qty)) > 0.000001:
            frappe.throw(_("Approved online quantities must be whole numbers."))
        if approved_qty < 0 or approved_qty > requested_qty:
            frappe.throw(
                _("Approved Qty for item {0} must be between 0 and {1}.").format(
                    frappe.bold(order_row.item_code), requested_qty
                )
            )

        warehouse = _clean_text(input_row.get("warehouse"), 140)
        alternative_item = _clean_text(input_row.get("alternative_item"), 140)
        checked_item_code = order_row.item_code

        if decision == "Available":
            if approved_qty != requested_qty:
                frappe.throw(
                    _("Available item {0} must approve the full requested quantity.").format(
                        frappe.bold(order_row.item_code)
                    )
                )
            stored_availability = "Available"
        elif decision == "Partially Available":
            if not (0 < approved_qty < requested_qty):
                frappe.throw(
                    _("Partially Available item {0} requires a reduced positive quantity.").format(
                        frappe.bold(order_row.item_code)
                    )
                )
            stored_availability = "Partially Available"
            has_partial = True
        elif decision in {"Unavailable", "Removed"}:
            if approved_qty != 0:
                frappe.throw(
                    _("Unavailable or removed item {0} must have Approved Qty 0.").format(
                        frappe.bold(order_row.item_code)
                    )
                )
            stored_availability = decision
            has_unavailable = True
            alternative_item = ""
        else:
            if approved_qty != 0:
                frappe.throw(
                    _("Alternative Suggested item {0} must have Approved Qty 0 until customer decision.").format(
                        frappe.bold(order_row.item_code)
                    )
                )
            if not alternative_item:
                frappe.throw(
                    _("Select an alternative item for {0}.").format(
                        frappe.bold(order_row.item_code)
                    )
                )
            if alternative_item == order_row.item_code:
                frappe.throw(_("Alternative Item must be different from the original item."))
            _item_stock(alternative_item, None)
            stored_availability = "Unavailable"
            has_alternative = True

        stock = _item_stock(checked_item_code, warehouse or None)
        if approved_qty > 0 and stock["is_stock_item"]:
            if not warehouse:
                frappe.throw(
                    _("Select a Warehouse for stock item {0}.").format(
                        frappe.bold(order_row.item_code)
                    )
                )
            _warehouse_state(warehouse, order.company)
            stock = _item_stock(checked_item_code, warehouse)
            if approved_qty > stock["actual_qty"] + 0.000001:
                frappe.throw(
                    _(
                        "Approved Qty {0} exceeds Actual Qty {1} for item {2} in warehouse {3}."
                    ).format(
                        approved_qty,
                        stock["actual_qty"],
                        frappe.bold(order_row.item_code),
                        frappe.bold(warehouse),
                    )
                )
            active_warehouses.add(warehouse)
        elif warehouse:
            _warehouse_state(warehouse, order.company)

        order_row.approved_qty = approved_qty
        order_row.warehouse = warehouse
        order_row.availability_status = stored_availability
        order_row.alternative_item = alternative_item
        order_row.alternative_accepted = 0
        order_row.stock_review_status = (
            "Approved"
            if approved_qty > 0
            else ("Reviewed" if decision == "Alternative Suggested" else "Rejected")
        )

        audit_rows.append(
            {
                "item_code": order_row.item_code,
                "decision": decision,
                "approved_qty": approved_qty,
                "warehouse": warehouse,
                "actual_qty": stock["actual_qty"],
                "alternative_item": alternative_item,
            }
        )

    if len(active_warehouses) == 1:
        only_warehouse = next(iter(active_warehouses))
        if not order.delivery_zone:
            order.warehouse = only_warehouse
        else:
            zone_warehouse = frappe.db.get_value("Delivery Zone", order.delivery_zone, "warehouse")
            if zone_warehouse and zone_warehouse != only_warehouse:
                frappe.throw(_("Reviewed Warehouse must match the Delivery Zone warehouse."))
            order.warehouse = only_warehouse

    prescription_complete = (
        not cint(order.prescription_required)
        or order.prescription_review_status in {"Approved", "Partially Approved"}
    )

    if has_alternative:
        target_status = "Awaiting Customer Decision"
    elif has_partial or has_unavailable:
        target_status = "Partially Available"
    elif prescription_complete:
        target_status = "Ready for Payment"
    else:
        # Stock can be reviewed before the pharmacist decision. Keep the order
        # in Stock Review and surface the prescription blocker in the snapshot.
        target_status = "Stock Review"

    if order.status != target_status:
        allowed = DIRECT_TRANSITIONS.get(order.status, set())
        if target_status not in allowed:
            frappe.throw(
                _("Cannot move reviewed order from {0} to {1}.").format(
                    frappe.bold(order.status), frappe.bold(target_status)
                )
            )
        order.status = target_status

    order.save(ignore_permissions=True)
    _audit_comment(
        order,
        _("Controlled Stock Review"),
        {
            "target_status": target_status,
            "rows": audit_rows,
            "notes": _clean_text(notes, 1000),
            "reviewed_by": frappe.session.user,
            "reviewed_at": now_datetime(),
        },
    )
    return _snapshot(order)

CUSTOMER_RESOLUTION_METHODS = {
    "Website User",
    "Mobile",
    "Email",
    "Manual Confirmation",
}


def _normalise_match_mobile(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalise_match_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _customer_identity(customer: str) -> dict[str, Any]:
    values = frappe.db.get_value(
        "Customer",
        customer,
        ["name", "customer_name", "mobile_no", "email_id", "disabled"],
        as_dict=True,
    )
    if not values or cint(values.get("disabled")):
        frappe.throw(_("Customer {0} was not found or is disabled.").format(frappe.bold(customer)))
    customer_code = customer
    if frappe.get_meta("Customer").has_field("custom_customer_code"):
        customer_code = frappe.db.get_value("Customer", customer, "custom_customer_code") or customer
    return {
        "name": values.get("name"),
        "customer_code": customer_code,
        "customer_name": values.get("customer_name") or customer,
        "mobile_no": values.get("mobile_no") or "",
        "email_id": values.get("email_id") or "",
    }


def _customer_addresses(customer: str) -> list[dict[str, Any]]:
    address_names = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Address",
            "link_doctype": "Customer",
            "link_name": customer,
        },
        pluck="parent",
    )
    if not address_names:
        return []
    rows = frappe.get_all(
        "Address",
        filters={"name": ["in", list(dict.fromkeys(address_names))], "disabled": 0},
        fields=[
            "name",
            "address_title",
            "address_type",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "country",
            "phone",
            "is_shipping_address",
            "is_primary_address",
            "custom_delivery_zone",
        ],
        order_by="is_shipping_address desc, is_primary_address desc, modified desc",
    )
    for row in rows:
        row["label"] = " — ".join(
            part
            for part in (
                row.get("address_title") or row.get("name"),
                row.get("address_line1"),
                row.get("city"),
            )
            if part
        )
    return rows


def _customer_contacts(customer: str) -> list[dict[str, Any]]:
    contact_names = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "link_doctype": "Customer",
            "link_name": customer,
        },
        pluck="parent",
    )
    if not contact_names:
        return []
    return frappe.get_all(
        "Contact",
        filters={"name": ["in", list(dict.fromkeys(contact_names))]},
        fields=["name", "full_name", "email_id", "mobile_no", "phone", "user", "is_primary_contact"],
        order_by="is_primary_contact desc, modified desc",
    )


def _website_user_customers(website_user: str) -> set[str]:
    user = str(website_user or "").strip()
    if not user or user == "Guest":
        return set()
    customers: set[str] = set()
    if frappe.db.exists("DocType", "Portal User"):
        for customer in frappe.get_all(
            "Portal User",
            filters={"parenttype": "Customer", "user": user},
            pluck="parent",
        ):
            customers.add(str(customer))
    contact_names = frappe.get_all("Contact", filters={"user": user}, pluck="name")
    if contact_names:
        for customer in frappe.get_all(
            "Dynamic Link",
            filters={
                "parenttype": "Contact",
                "parent": ["in", contact_names],
                "link_doctype": "Customer",
            },
            pluck="link_name",
        ):
            customers.add(str(customer))
    return {
        customer
        for customer in customers
        if frappe.db.exists("Customer", {"name": customer, "disabled": 0})
    }


def _customer_resolution_candidates(order) -> list[dict[str, Any]]:
    matched: dict[str, set[str]] = {}

    def add(customer: str, method: str) -> None:
        if customer and frappe.db.exists("Customer", {"name": customer, "disabled": 0}):
            matched.setdefault(str(customer), set()).add(method)

    website_user = getattr(order, "custom_website_user", "") or ""
    for customer in _website_user_customers(website_user):
        add(customer, "Website User")

    mobile = _normalise_match_mobile(order.mobile_no)
    email = _normalise_match_email(order.email_id)

    direct_customers = frappe.get_all(
        "Customer",
        filters={"disabled": 0},
        fields=["name", "mobile_no", "email_id"],
        limit_page_length=1000,
    )
    for row in direct_customers:
        if mobile and _normalise_match_mobile(row.get("mobile_no")) == mobile:
            add(row.get("name"), "Mobile")
        if email and _normalise_match_email(row.get("email_id")) == email:
            add(row.get("name"), "Email")

    contact_filters: dict[str, Any] = {}
    contacts = frappe.get_all(
        "Contact",
        filters=contact_filters,
        fields=["name", "mobile_no", "phone", "email_id", "user"],
        limit_page_length=2000,
    )
    contact_methods: dict[str, set[str]] = {}
    for contact in contacts:
        methods: set[str] = set()
        if mobile and mobile in {
            _normalise_match_mobile(contact.get("mobile_no")),
            _normalise_match_mobile(contact.get("phone")),
        }:
            methods.add("Mobile")
        if email and _normalise_match_email(contact.get("email_id")) == email:
            methods.add("Email")
        if website_user and contact.get("user") == website_user:
            methods.add("Website User")
        if methods:
            contact_methods[str(contact.get("name"))] = methods

    if contact_methods:
        links = frappe.get_all(
            "Dynamic Link",
            filters={
                "parenttype": "Contact",
                "parent": ["in", list(contact_methods)],
                "link_doctype": "Customer",
            },
            fields=["parent", "link_name"],
        )
        for link in links:
            for method in contact_methods.get(str(link.get("parent")), set()):
                add(link.get("link_name"), method)

    candidates: list[dict[str, Any]] = []
    for customer, methods in matched.items():
        identity = _customer_identity(customer)
        identity["match_methods"] = sorted(methods)
        identity["address_count"] = len(_customer_addresses(customer))
        identity["website_user_match"] = cint("Website User" in methods)
        candidates.append(identity)
    candidates.sort(
        key=lambda row: (
            -cint(row.get("website_user_match")),
            row.get("customer_name") or "",
            row.get("name") or "",
        )
    )
    return candidates


def _validate_customer_address(customer: str, address_name: str) -> dict[str, Any]:
    if not address_name:
        return {}
    if not frappe.db.exists("Address", address_name):
        frappe.throw(_("Address {0} was not found.").format(frappe.bold(address_name)))
    linked = frappe.db.exists(
        "Dynamic Link",
        {
            "parenttype": "Address",
            "parent": address_name,
            "link_doctype": "Customer",
            "link_name": customer,
        },
    )
    if not linked:
        frappe.throw(_("The selected address is not linked to Customer {0}.").format(frappe.bold(customer)))
    values = frappe.db.get_value(
        "Address",
        address_name,
        [
            "address_title",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "country",
            "phone",
            "disabled",
            "custom_delivery_zone",
        ],
        as_dict=True,
    ) or {}
    if cint(values.get("disabled")):
        frappe.throw(_("The selected address is disabled."))
    return values


def _apply_address_to_order(order, address_name: str, values: dict[str, Any]) -> None:
    if not address_name:
        return
    order.customer_address = address_name
    order.address_title = values.get("address_title") or address_name
    order.address_line1 = values.get("address_line1") or ""
    order.address_line2 = values.get("address_line2") or ""
    order.city = values.get("city") or ""
    order.state = values.get("state") or ""
    order.country = values.get("country") or "Egypt"
    order.address_phone = values.get("phone") or order.mobile_no or ""
    order.formatted_address = ", ".join(
        part
        for part in (
            order.address_line1,
            order.address_line2,
            order.city,
            order.state,
            order.country,
        )
        if part
    )


def _zone_options(order) -> list[dict[str, Any]]:
    zones = frappe.get_all(
        "Delivery Zone",
        filters={"is_active": 1},
        fields=[
            "name",
            "zone_name",
            "zone_name_ar",
            "warehouse",
            "priority",
            "delivery_fee",
            "minimum_order_amount",
            "small_order_threshold",
            "small_order_delivery_fee",
            "free_delivery_above",
            "estimated_time_mins",
        ],
        order_by="priority asc, zone_name asc",
    )
    result: list[dict[str, Any]] = []
    for zone in zones:
        if order.warehouse and zone.get("warehouse") and zone.get("warehouse") != order.warehouse:
            continue
        zone["label"] = zone.get("zone_name_ar") or zone.get("zone_name") or zone.get("name")
        result.append(zone)
    return result


def _zone_delivery_fee(zone: dict[str, Any], products_subtotal: float) -> tuple[float, str]:
    subtotal = flt(products_subtotal)
    minimum = flt(zone.get("minimum_order_amount"))
    if minimum and subtotal + 0.000001 < minimum:
        frappe.throw(
            _("Order subtotal {0} is below the minimum {1} for Delivery Zone {2}.").format(
                subtotal, minimum, frappe.bold(zone.get("name"))
            )
        )
    free_above = flt(zone.get("free_delivery_above"))
    if free_above and subtotal + 0.000001 >= free_above:
        return 0.0, f"Free Delivery Above {free_above:g}"
    small_threshold = flt(zone.get("small_order_threshold"))
    small_fee = flt(zone.get("small_order_delivery_fee"))
    if small_threshold and subtotal < small_threshold and small_fee > 0:
        return small_fee, f"Small Order Delivery Fee Below {small_threshold:g}"
    return flt(zone.get("delivery_fee")), "Delivery Zone Standard Fee"


@frappe.whitelist()
def get_customer_resolution_context(online_order: str | None = None) -> dict[str, Any]:
    order = _get_order(online_order, "read")
    selected_customer = order.customer or ""
    return {
        "online_order": order.name,
        "website_user": getattr(order, "custom_website_user", "") or "",
        "customer": selected_customer,
        "customer_address": order.customer_address or "",
        "customer_resolution_status": order.customer_resolution_status or "Unresolved",
        "customer_resolution_method": getattr(order, "custom_customer_resolution_method", "") or "",
        "candidates": _customer_resolution_candidates(order),
        "selected_customer": _customer_identity(selected_customer) if selected_customer else {},
        "addresses": _customer_addresses(selected_customer) if selected_customer else [],
        "contacts": _customer_contacts(selected_customer) if selected_customer else [],
        "controlled_resolution": 1,
    }


@frappe.whitelist()
def get_customer_profile(customer: str | None = None) -> dict[str, Any]:
    _require_authenticated_user()
    name = _clean_text(customer, 140)
    if not name:
        frappe.throw(_("Customer is required."))
    if not frappe.has_permission("Customer", "read"):
        frappe.throw(_("You do not have permission to read Customers."), frappe.PermissionError)
    return {
        "customer": _customer_identity(name),
        "addresses": _customer_addresses(name),
        "contacts": _customer_contacts(name),
    }


@frappe.whitelist(methods=["POST"])
def apply_customer_resolution(
    online_order: str | None = None,
    customer: str | None = None,
    resolution_method: str | None = None,
    address_name: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    customer_name = _clean_text(customer, 140)
    method = _clean_text(resolution_method, 60)
    address = _clean_text(address_name, 140)
    if method not in CUSTOMER_RESOLUTION_METHODS:
        frappe.throw(_("Select a valid customer resolution method."))
    identity = _customer_identity(customer_name)
    candidates = {row["name"]: row for row in _customer_resolution_candidates(order)}
    if method != "Manual Confirmation":
        candidate = candidates.get(customer_name)
        if not candidate or method not in set(candidate.get("match_methods") or []):
            frappe.throw(_("The selected Customer does not match the selected resolution method."))
    address_values = _validate_customer_address(customer_name, address) if address else {}

    order.customer = customer_name
    order.customer_resolution_status = "Matched" if method == "Website User" else "Confirmed"
    if order.meta.has_field("custom_customer_resolution_method"):
        order.custom_customer_resolution_method = method
    if order.meta.has_field("custom_customer_resolution_notes"):
        order.custom_customer_resolution_notes = _clean_text(notes, 1000)
    if order.meta.has_field("custom_customer_resolved_by"):
        order.custom_customer_resolved_by = frappe.session.user
    if order.meta.has_field("custom_customer_resolved_at"):
        order.custom_customer_resolved_at = now_datetime()
    _apply_address_to_order(order, address, address_values)
    order.save(ignore_permissions=True)
    _audit_comment(
        order,
        _("Controlled Customer Resolution"),
        {
            "customer": customer_name,
            "customer_code": identity.get("customer_code"),
            "resolution_method": method,
            "resolution_status": order.customer_resolution_status,
            "custom_website_user": getattr(order, "custom_website_user", "") or "",
            "address": address,
            "notes": _clean_text(notes, 1000),
            "resolved_by": frappe.session.user,
            "resolved_at": now_datetime(),
        },
    )
    return _snapshot(order)


@frappe.whitelist()
def get_delivery_zone_context(online_order: str | None = None) -> dict[str, Any]:
    order = _get_order(online_order, "read")
    return {
        "online_order": order.name,
        "fulfilment_method": order.fulfilment_method,
        "warehouse": order.warehouse or "",
        "delivery_zone": order.delivery_zone or "",
        "products_subtotal": flt(order.products_subtotal),
        "current_delivery_fee": flt(order.delivery_fee),
        "zones": _zone_options(order),
        "controlled_delivery_zone": 1,
    }


@frappe.whitelist(methods=["POST"])
def apply_delivery_zone(
    online_order: str | None = None,
    delivery_zone: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    if order.fulfilment_method != "Home Delivery":
        frappe.throw(_("Delivery Zone is only used for Home Delivery orders."))
    zone_name = _clean_text(delivery_zone, 140)
    zone = frappe.db.get_value(
        "Delivery Zone",
        zone_name,
        [
            "name",
            "is_active",
            "warehouse",
            "delivery_fee",
            "minimum_order_amount",
            "small_order_threshold",
            "small_order_delivery_fee",
            "free_delivery_above",
            "estimated_time_mins",
        ],
        as_dict=True,
    )
    if not zone or not cint(zone.get("is_active")):
        frappe.throw(_("Select an active Delivery Zone."))
    zone_warehouse = zone.get("warehouse") or ""
    if order.warehouse and zone_warehouse and order.warehouse != zone_warehouse:
        frappe.throw(
            _("Delivery Zone warehouse {0} does not match reviewed warehouse {1}.").format(
                frappe.bold(zone_warehouse), frappe.bold(order.warehouse)
            )
        )
    if zone_warehouse:
        _warehouse_state(zone_warehouse, order.company)
    fee, rule = _zone_delivery_fee(zone, flt(order.products_subtotal))
    order.delivery_zone = zone_name
    order.warehouse = order.warehouse or zone_warehouse
    order.delivery_fee = fee
    order.delivery_fee_rule = rule
    order.estimated_delivery_time_mins = cint(zone.get("estimated_time_mins"))
    order.save(ignore_permissions=True)
    _audit_comment(
        order,
        _("Controlled Delivery Zone Resolution"),
        {
            "delivery_zone": zone_name,
            "warehouse": order.warehouse,
            "products_subtotal": flt(order.products_subtotal),
            "delivery_fee": flt(order.delivery_fee),
            "delivery_fee_rule": order.delivery_fee_rule,
            "grand_total": flt(order.grand_total),
            "notes": _clean_text(notes, 1000),
            "resolved_by": frappe.session.user,
            "resolved_at": now_datetime(),
        },
    )
    return _snapshot(order)


@frappe.whitelist(methods=["POST"])
def verify_final_confirmation_readiness(
    online_order: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    order = _get_order(online_order, "write")
    current = _snapshot(order)
    blockers = list(current.get("review_blockers") or []) + list(
        current.get("confirmation_blockers") or []
    )
    if blockers:
        frappe.throw(
            _("Final confirmation readiness is blocked: {0}").format(" | ".join(blockers))
        )
    if order.meta.has_field("custom_final_confirmation_readiness_status"):
        order.custom_final_confirmation_readiness_status = "Ready"
    if order.meta.has_field("custom_final_confirmation_checked_by"):
        order.custom_final_confirmation_checked_by = frappe.session.user
    if order.meta.has_field("custom_final_confirmation_checked_at"):
        order.custom_final_confirmation_checked_at = now_datetime()
    if order.meta.has_field("custom_final_confirmation_notes"):
        order.custom_final_confirmation_notes = _clean_text(notes, 1000)
    order.save(ignore_permissions=True)
    _audit_comment(
        order,
        _("Final Confirmation Readiness Verified"),
        {
            "status": order.status,
            "customer": order.customer,
            "customer_resolution_status": order.customer_resolution_status,
            "customer_address": order.customer_address,
            "delivery_zone": order.delivery_zone,
            "warehouse": order.warehouse,
            "grand_total": flt(order.grand_total),
            "checked_by": frappe.session.user,
            "checked_at": now_datetime(),
            "notes": _clean_text(notes, 1000),
            "creates_financial_or_stock_documents": 0,
        },
    )
    return _snapshot(order)
