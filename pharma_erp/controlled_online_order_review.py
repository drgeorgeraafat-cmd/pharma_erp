from __future__ import annotations

import html
import json
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
        "customer_name": order.customer_name,
        "mobile_no": order.mobile_no,
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
            "customer_name",
            "mobile_no",
            "fulfilment_method",
            "grand_total",
            "currency",
            "prescription_required",
            "prescription_review_status",
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
        "financial_stock_documents_created": 0,
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
