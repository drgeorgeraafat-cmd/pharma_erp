"""Customer Reservation Operations for Pharma ERP v0.9.2 Step2C.

Operational metadata lives on Sales Order.  The durable stock hold remains
ERPNext's submitted Stock Reservation Entry and is consumed through the
standard Sales Invoice Item ``sales_order`` / ``so_detail`` references.
"""

from __future__ import annotations

import json
from math import floor
from typing import Any
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import (
    cint,
    cstr,
    flt,
    get_datetime,
    getdate,
    now_datetime,
    nowdate,
)

from pharma_erp.pharma_erp.branch_operational_integration import resolve_role_context
from pharma_erp.pharma_erp.customer_reservation_contract import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    build_request_key,
    derive_operational_status,
    normalized_qty,
    remaining_qty,
    validate_contact_outcome,
    validate_fulfilment_mode,
    validate_locked_reservation_price,
    validate_reserved_fulfilment_qty,
)
from pharma_erp.pharma_erp.standard_reservation_service import (
    _release_reservation,
    reserve_sales_order_item,
)
from pharma_erp.pharma_erp.unified_stock_availability import (
    get_unified_stock_availability,
)


ROLE = "Sales"
SRE_DOCTYPE = "Stock Reservation Entry"
REQUIRED_SO_FIELDS = (
    "custom_customer_reservation",
    "custom_reservation_request_key",
    "custom_reservation_review_at",
    "custom_reservation_fulfilment_mode",
    "custom_reservation_operational_status",
    "custom_reservation_last_contact_outcome",
    "custom_reservation_fulfilment_invoice",
)


def _clean(value: Any) -> str:
    return cstr(value or "").strip()


def _as_data(value: Any) -> frappe._dict:
    if isinstance(value, str):
        value = json.loads(value)
    return frappe._dict(value or {})


def _default_company() -> str:
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or ""
    )


def _assert_installation() -> None:
    so_meta = frappe.get_meta("Sales Order")
    missing = [f"Sales Order.{field}" for field in REQUIRED_SO_FIELDS if not so_meta.has_field(field)]
    invoice_item_meta = frappe.get_meta("Sales Invoice Item")
    missing += [
        f"Sales Invoice Item.{field}"
        for field in ("sales_order", "so_detail")
        if not invoice_item_meta.has_field(field)
    ]
    if missing:
        frappe.throw(_("Step2C metadata is incomplete: {0}").format(", ".join(missing)))


def _check_permission(doctype: str, ptype: str) -> None:
    if not frappe.has_permission(doctype, ptype):
        frappe.throw(
            _("You do not have {0} permission for {1}.").format(ptype, doctype),
            frappe.PermissionError,
        )


def _review_due(review_at: Any) -> bool:
    return bool(review_at and get_datetime(review_at) <= now_datetime())


def _reservation_entries(sales_order: str, *, for_update: bool = False) -> list[frappe._dict]:
    sql = """
        SELECT
            sre.name, sre.docstatus, sre.status, sre.voucher_detail_no,
            sre.item_code, sre.warehouse, sre.reserved_qty, sre.delivered_qty,
            sre.custom_contract_state, sre.custom_pharmacy_branch,
            soi.qty, soi.stock_qty, soi.conversion_factor, soi.rate,
            soi.price_list_rate, soi.discount_percentage, soi.uom,
            soi.stock_uom, soi.item_name
        FROM `tabStock Reservation Entry` sre
        INNER JOIN `tabSales Order Item` soi ON soi.name=sre.voucher_detail_no
        WHERE sre.voucher_type='Sales Order' AND sre.voucher_no=%s
        ORDER BY soi.idx ASC, sre.creation ASC, sre.name ASC
    """
    if for_update:
        sql += " FOR UPDATE"
    return frappe.db.sql(sql, (sales_order,), as_dict=True)


def _operational_status(order, entries: list[frappe._dict]) -> str:
    reserved = sum(flt(row.reserved_qty) for row in entries)
    delivered = sum(flt(row.delivered_qty) for row in entries)
    all_terminal = bool(entries) and all(cint(row.docstatus) == 2 for row in entries)
    terminal_state = ""
    if all_terminal:
        states = {_clean(row.custom_contract_state) for row in entries}
        terminal_state = "Released" if states.intersection({"Released", "Expired"}) else "Cancelled"
    return derive_operational_status(
        reserved_qty=reserved,
        delivered_qty=delivered,
        reservation_docstatus=2 if all_terminal else 1,
        reservation_contract_state=terminal_state,
        review_due=_review_due(order.get("custom_reservation_review_at")),
        fulfilment_mode=order.get("custom_reservation_fulfilment_mode") or "Undecided",
        stored_status=order.get("custom_reservation_operational_status") or "",
    )


def _sync_operational_status(order, entries: list[frappe._dict] | None = None) -> str:
    entries = entries if entries is not None else _reservation_entries(order.name)
    status = _operational_status(order, entries)
    if _clean(order.get("custom_reservation_operational_status")) != status:
        frappe.db.set_value(
            "Sales Order",
            order.name,
            "custom_reservation_operational_status",
            status,
            update_modified=False,
        )
        order.custom_reservation_operational_status = status
    return status


def _customer_result(customer: str) -> frappe._dict:
    fields = ["name", "customer_name", "mobile_no"]
    if frappe.get_meta("Customer").has_field("custom_customer_code"):
        fields.append("custom_customer_code")
    return frappe.db.get_value("Customer", customer, fields, as_dict=True) or frappe._dict()


def _reservation_detail(order) -> dict[str, Any]:
    entries = _reservation_entries(order.name)
    status = _sync_operational_status(order, entries)
    items = []
    for row in entries:
        remaining = remaining_qty(row.reserved_qty, row.delivered_qty) if cint(row.docstatus) == 1 else 0
        items.append(
            {
                "reservation": row.name,
                "reservation_docstatus": cint(row.docstatus),
                "reservation_status": row.status,
                "reservation_contract_state": row.custom_contract_state,
                "sales_order_item": row.voucher_detail_no,
                "item_code": row.item_code,
                "item_name": row.item_name or row.item_code,
                "warehouse": row.warehouse,
                "reserved_qty": normalized_qty(row.reserved_qty),
                "delivered_qty": normalized_qty(row.delivered_qty),
                "remaining_qty": remaining,
                "stock_uom": row.stock_uom,
                "price_list_rate": flt(row.price_list_rate or row.rate),
                "discount_percentage": flt(row.discount_percentage),
                "rate": flt(row.rate),
            }
        )
    return {
        "sales_order": order.name,
        "customer": order.customer,
        "customer_name": order.customer_name,
        "contact_mobile": order.contact_mobile or "",
        "company": order.company,
        "branch": order.custom_pharmacy_branch,
        "warehouse": order.set_warehouse,
        "review_at": order.custom_reservation_review_at,
        "fulfilment_mode": order.custom_reservation_fulfilment_mode or "Undecided",
        "operational_status": status,
        "last_contact_outcome": order.custom_reservation_last_contact_outcome or "",
        "last_contact_at": order.custom_reservation_last_contact_at,
        "last_contact_by": order.custom_reservation_last_contact_by,
        "last_contact_notes": order.custom_reservation_last_contact_notes or "",
        "notes": order.custom_reservation_notes or "",
        "fulfilment_invoice": order.custom_reservation_fulfilment_invoice or "",
        "items": items,
        "remaining_qty": normalized_qty(sum(row["remaining_qty"] for row in items)),
    }


def validate_customer_reservation_sales_order(doc, method=None):
    if not cint(doc.get("custom_customer_reservation")) or cint(doc.docstatus) == 2:
        return
    _assert_installation()
    if doc.get("custom_online_order"):
        frappe.throw(_("Online Order cannot be converted into a Step2C Customer Reservation."))
    if not doc.get("custom_reservation_review_at"):
        frappe.throw(_("Reservation Review At is required."))
    validate_fulfilment_mode(doc.get("custom_reservation_fulfilment_mode"))
    if not cint(doc.get("reserve_stock")):
        frappe.throw(_("Customer Reservation must reserve stock."))
    if not doc.get("items"):
        frappe.throw(_("Customer Reservation requires at least one item."))
    if method == "before_submit" and get_datetime(doc.custom_reservation_review_at) <= now_datetime():
        frappe.throw(_("Reservation Review At must be in the future when the reservation is submitted."))


def _selling_rate(
    item_code: str,
    price_list: str,
    warehouse: str,
    requested_qty: float,
) -> float:
    del price_list  # Pharmacy POS stock-source pricing is authoritative here.
    from pharma_erp.pharma_erp.page.pharmacy_pos.api import (
        _canonical_pos_source_pricing,
    )

    pricing = _canonical_pos_source_pricing(
        item_code,
        warehouse,
        requested_qty,
    )
    return flt(pricing.rate, 6)


@frappe.whitelist()
def create_customer_reservation(data):
    _assert_installation()
    _check_permission("Sales Order", "create")
    _check_permission("Sales Order", "submit")
    _check_permission(SRE_DOCTYPE, "create")
    data = _as_data(data)

    customer = _clean(data.customer)
    item_code = _clean(data.item_code)
    company = _clean(data.company) or _default_company()
    requested_branch = _clean(data.branch)
    requested_qty = normalized_qty(data.qty)
    review_at = get_datetime(data.review_at) if data.review_at else None
    fulfilment_mode = validate_fulfilment_mode(data.fulfilment_mode or "Undecided")
    if not customer or not frappe.db.exists("Customer", customer):
        frappe.throw(_("Select a valid customer."))
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Select a valid item."))
    if requested_qty <= 0:
        frappe.throw(_("Reservation quantity must be greater than zero."))
    if not review_at or review_at <= now_datetime():
        frappe.throw(_("Reservation review time must be in the future."))

    item = frappe.db.get_value(
        "Item",
        item_code,
        ["name", "item_name", "stock_uom", "is_stock_item", "disabled"],
        as_dict=True,
    )
    if not item or cint(item.disabled) or not cint(item.is_stock_item):
        frappe.throw(_("Customer Reservation requires an enabled stock item."))

    context = frappe._dict(
        resolve_role_context(
            company=company,
            role=ROLE,
            requested_branch=requested_branch,
            submitted_warehouse=_clean(data.warehouse),
        )
    )
    availability = get_unified_stock_availability(
        item_code=item_code,
        branch=context.branch,
        operational_role=ROLE,
        warehouse=context.warehouse,
        source_type="stock",
        enforce_permissions=False,
    )
    if not availability["states"]["reservation_enabled"]:
        frappe.throw(_("The canonical Sales source is not enabled for reservation."))
    available = normalized_qty(availability["quantities"]["available_to_promise"])
    if requested_qty > available:
        frappe.throw(
            _("Cannot reserve {0}; unified available-to-promise is {1}.").format(
                requested_qty, available
            )
        )

    request_token = _clean(data.request_token) or uuid4().hex
    request_key = build_request_key(
        customer=customer,
        item_code=item_code,
        branch=context.branch,
        request_token=request_token,
    )
    existing = frappe.db.get_value(
        "Sales Order",
        {"custom_reservation_request_key": request_key},
        "name",
    )
    if existing:
        return {**get_customer_reservation(existing), "idempotent": True}

    price_list = (
        _clean(data.price_list)
        or frappe.db.get_single_value("Selling Settings", "selling_price_list")
        or ""
    )
    order = frappe.new_doc("Sales Order")
    order.customer = customer
    order.company = company
    order.order_type = "Sales"
    order.transaction_date = nowdate()
    order.delivery_date = max(getdate(nowdate()), getdate(review_at))
    order.set_warehouse = context.warehouse
    order.reserve_stock = 1
    order.custom_pharmacy_branch = context.branch
    order.custom_customer_reservation = 1
    order.custom_reservation_request_key = request_key
    order.custom_reservation_review_at = review_at
    order.custom_reservation_fulfilment_mode = fulfilment_mode
    order.custom_reservation_operational_status = "Active"
    order.custom_reservation_notes = _clean(data.notes)
    order.contact_mobile = _clean(data.contact_mobile) or _clean(
        frappe.db.get_value("Customer", customer, "mobile_no")
    )
    if price_list:
        order.selling_price_list = price_list
    rate = _selling_rate(
        item_code,
        price_list,
        context.warehouse,
        requested_qty,
    )
    row = order.append(
        "items",
        {
            "item_code": item_code,
            "item_name": item.item_name,
            "qty": requested_qty,
            "uom": item.stock_uom,
            "stock_uom": item.stock_uom,
            "conversion_factor": 1,
            "warehouse": context.warehouse,
            "delivery_date": order.delivery_date,
            "reserve_stock": 1,
            "rate": rate,
            "price_list_rate": rate,
        },
    )

    create_savepoint = "pharma_step2c_create_reservation"
    frappe.db.savepoint(create_savepoint)
    try:
        order.set_missing_values()
        order.insert()
        order.submit()
        entries = _reservation_entries(order.name)
        if not entries:
            reserve_sales_order_item(
                order.name,
                row.name,
                qty_in_stock_uom=requested_qty,
            )
            entries = _reservation_entries(order.name)
        if not entries or normalized_qty(sum(flt(entry.reserved_qty) for entry in entries)) < requested_qty:
            frappe.throw(_("Standard Stock Reservation Entry was not created for the full requested quantity."))
        order.add_comment(
            "Info",
            _("Customer Reservation created. Review at {0}. Fulfilment: {1}.").format(
                review_at, fulfilment_mode
            ),
        )
    except Exception:
        # Keep caller-owned savepoints intact.  Frappe rolls back the request
        # on an uncaught exception; this bounded rollback only removes the
        # partial reservation when the service is called inside a larger test
        # or workflow transaction.
        frappe.db.rollback(save_point=create_savepoint)
        raise

    return {**_reservation_detail(order), "idempotent": False}


@frappe.whitelist()
def get_customer_reservation(sales_order: str):
    _assert_installation()
    order = frappe.get_doc("Sales Order", _clean(sales_order))
    if not order.has_permission("read"):
        frappe.throw(_("You do not have permission to read this reservation."), frappe.PermissionError)
    if not cint(order.get("custom_customer_reservation")):
        frappe.throw(_("Sales Order is not a Step2C Customer Reservation."))
    return _reservation_detail(order)


@frappe.whitelist()
def list_customer_reservations(
    status: str = "",
    branch: str = "",
    customer: str = "",
    limit: int = 100,
):
    _assert_installation()
    filters: dict[str, Any] = {"custom_customer_reservation": 1, "docstatus": ("<", 2)}
    if branch:
        filters["custom_pharmacy_branch"] = _clean(branch)
    if customer:
        filters["customer"] = _clean(customer)
    rows = frappe.get_list(
        "Sales Order",
        filters=filters,
        fields=["name"],
        order_by="custom_reservation_review_at asc, creation asc",
        limit_page_length=max(1, min(cint(limit) or 100, 500)),
    )
    requested_status = _clean(status)
    result = []
    for row in rows:
        order = frappe.get_doc("Sales Order", row.name)
        detail = _reservation_detail(order)
        if requested_status and detail["operational_status"] != requested_status:
            continue
        result.append(detail)
    return result


def _write_contact(order, *, outcome: str, notes: str, review_at=None, mode: str | None = None):
    values: dict[str, Any] = {
        "custom_reservation_last_contact_outcome": outcome,
        "custom_reservation_last_contact_at": now_datetime(),
        "custom_reservation_last_contact_by": frappe.session.user,
        "custom_reservation_last_contact_notes": notes,
    }
    if review_at:
        values["custom_reservation_review_at"] = review_at
        values["custom_reservation_operational_status"] = "Active"
    if mode:
        values["custom_reservation_fulfilment_mode"] = mode
    frappe.db.set_value("Sales Order", order.name, values, update_modified=False)
    order.update(values)
    order.add_comment(
        "Info",
        _("Customer contact outcome: {0}. {1}").format(outcome, notes or ""),
    )


@frappe.whitelist()
def record_customer_contact(
    sales_order: str,
    outcome: str,
    notes: str = "",
    next_review_at: str | None = None,
):
    order = frappe.get_doc("Sales Order", _clean(sales_order))
    if not order.has_permission("write"):
        frappe.throw(_("You do not have permission to update this reservation."), frappe.PermissionError)
    if not cint(order.get("custom_customer_reservation")):
        frappe.throw(_("Sales Order is not a Step2C Customer Reservation."))
    outcome = validate_contact_outcome(outcome)
    notes = _clean(notes)
    if outcome == "Declined":
        return release_customer_reservation(order.name, notes or _("Customer declined the reservation."))

    review_at = None
    if outcome in ("Still Needed", "No Answer"):
        if not next_review_at:
            frappe.throw(_("Next review time is required for Still Needed or No Answer."))
        review_at = get_datetime(next_review_at)
        if review_at <= now_datetime():
            frappe.throw(_("Next review time must be in the future."))
    mode = None
    if outcome == "Confirmed Pickup":
        mode = "Pickup"
    elif outcome == "Confirmed Delivery":
        mode = "Home Delivery"
    _write_contact(order, outcome=outcome, notes=notes, review_at=review_at, mode=mode)
    return _reservation_detail(order)


@frappe.whitelist()
def set_customer_reservation_mode(sales_order: str, fulfilment_mode: str):
    order = frappe.get_doc("Sales Order", _clean(sales_order))
    if not order.has_permission("write"):
        frappe.throw(_("You do not have permission to update this reservation."), frappe.PermissionError)
    mode = validate_fulfilment_mode(fulfilment_mode)
    if mode == "Undecided":
        frappe.throw(_("Choose Pickup or Home Delivery before opening Pharmacy POS."))
    frappe.db.set_value(
        "Sales Order",
        order.name,
        "custom_reservation_fulfilment_mode",
        mode,
        update_modified=False,
    )
    order.custom_reservation_fulfilment_mode = mode
    order.add_comment("Info", _("Reservation fulfilment mode changed to {0}.").format(mode))
    return _reservation_detail(order)


@frappe.whitelist()
def release_customer_reservation(sales_order: str, reason: str):
    order = frappe.get_doc("Sales Order", _clean(sales_order))
    if not order.has_permission("write"):
        frappe.throw(_("You do not have permission to release this reservation."), frappe.PermissionError)
    reason = _clean(reason)
    if not reason:
        frappe.throw(_("A release reason is required."))
    entries = _reservation_entries(order.name, for_update=True)
    if not entries:
        frappe.throw(_("No standard Stock Reservation Entry belongs to this reservation."))
    released = []
    for row in entries:
        if cint(row.docstatus) == 1:
            released.append(
                _release_reservation(
                    row.name,
                    reason=reason,
                    terminal_state="Released",
                    ignore_permissions=False,
                )
            )
    values = {
        "custom_reservation_operational_status": "Released",
        "custom_reservation_last_contact_at": now_datetime(),
        "custom_reservation_last_contact_by": frappe.session.user,
        "custom_reservation_last_contact_notes": reason,
    }
    frappe.db.set_value("Sales Order", order.name, values, update_modified=False)
    order.update(values)
    order.add_comment("Info", _("Customer Reservation released. Reason: {0}").format(reason))
    return {**_reservation_detail(order), "released_entries": released}


@frappe.whitelist()
def get_customer_reservation_pos_context(sales_order: str, fulfilment_mode: str = ""):
    detail = get_customer_reservation(sales_order)
    if detail["operational_status"] not in ACTIVE_STATUSES:
        frappe.throw(
            _("Reservation {0} is not active; current status is {1}.").format(
                sales_order, detail["operational_status"]
            )
        )
    mode = validate_fulfilment_mode(fulfilment_mode or detail["fulfilment_mode"])
    if mode == "Undecided":
        frappe.throw(_("Choose Pickup or Home Delivery before opening Pharmacy POS."))
    items = []
    for row in detail["items"]:
        if row["reservation_docstatus"] != 1 or row["remaining_qty"] <= 0:
            continue
        pack_size = 1.0
        if frappe.get_meta("Item").has_field("custom_pack_size"):
            pack_size = flt(frappe.db.get_value("Item", row["item_code"], "custom_pack_size")) or 1
        boxes = floor(row["remaining_qty"] + 1e-9)
        units = round((row["remaining_qty"] - boxes) * pack_size, 6)
        items.append(
            {
                **row,
                "box_qty": boxes,
                "unit_qty": units,
                "pack_size": pack_size,
            }
        )
    if not items:
        frappe.throw(_("Reservation has no remaining stock quantity to fulfil."))
    return {
        **detail,
        "fulfilment_mode": mode,
        "order_type": "Home Delivery" if mode == "Home Delivery" else "Walk In",
        "customer_data": _customer_result(detail["customer"]),
        "items": items,
    }


def _reservation_sales_order_from_invoice(doc) -> str:
    """Derive the single Step2C owner from standard invoice-item links."""
    linked_orders = {
        _clean(row.get("sales_order"))
        for row in (doc.items or [])
        if _clean(row.get("sales_order"))
    }
    reservation_orders = {
        sales_order
        for sales_order in linked_orders
        if cint(
            frappe.db.get_value(
                "Sales Order", sales_order, "custom_customer_reservation"
            )
        )
    }
    if len(reservation_orders) > 1:
        frappe.throw(
            _("A Sales Invoice cannot fulfil more than one Customer Reservation.")
        )
    return next(iter(reservation_orders), "")


def _invoice_fulfilment_mode(doc) -> str:
    order_type = _clean(doc.get("custom_order_type")) or "Walk In"
    if order_type not in ("Walk In", "Home Delivery"):
        frappe.throw(
            _("Customer Reservation can only be fulfilled by Pickup or Home Delivery.")
        )
    return "Home Delivery" if order_type == "Home Delivery" else "Pickup"


def validate_customer_reservation_invoice(doc, method=None):
    sales_order = _reservation_sales_order_from_invoice(doc)
    if not sales_order or cint(doc.docstatus) == 2:
        return
    _assert_installation()
    order = frappe.get_doc("Sales Order", sales_order)
    if not cint(order.get("custom_customer_reservation")) or cint(order.docstatus) != 1:
        frappe.throw(_("Reservation owner must be a submitted Step2C Sales Order."))
    if doc.customer != order.customer or doc.company != order.company:
        frappe.throw(_("Reservation invoice customer/company must match its Sales Order."))
    mode = _invoice_fulfilment_mode(doc)
    stored_mode = validate_fulfilment_mode(order.get("custom_reservation_fulfilment_mode"))
    if stored_mode != "Undecided" and stored_mode != mode:
        frappe.throw(
            _("Invoice mode {0} conflicts with reservation mode {1}.").format(mode, stored_mode)
        )
    if doc.get("custom_pharmacy_branch") != order.custom_pharmacy_branch:
        frappe.throw(_("Reservation invoice Branch must match its Sales Order."))
    if _clean(doc.set_warehouse) != _clean(order.set_warehouse):
        frappe.throw(_("Reservation invoice warehouse must match its Sales Order."))

    entries = _reservation_entries(order.name, for_update=method == "before_submit")
    remaining_by_row: dict[str, float] = {}
    owner_by_row: dict[str, frappe._dict] = {}
    for entry in entries:
        if cint(entry.docstatus) == 1:
            owner_by_row[entry.voucher_detail_no] = entry
            remaining_by_row[entry.voucher_detail_no] = normalized_qty(
                remaining_by_row.get(entry.voucher_detail_no, 0)
                + remaining_qty(entry.reserved_qty, entry.delivered_qty)
            )
    consumed_by_row: dict[str, float] = {}
    sales_qty_by_row: dict[str, float] = {}
    gross_amount_by_row: dict[str, float] = {}
    net_amount_by_row: dict[str, float] = {}
    for row in doc.items or []:
        row_sales_order = _clean(row.get("sales_order"))
        if row_sales_order and row_sales_order != order.name:
            frappe.throw(
                _("Reservation invoice cannot include an item owned by another Sales Order.")
            )
        if row_sales_order != order.name:
            continue
        detail_no = _clean(row.get("so_detail"))
        if detail_no not in remaining_by_row:
            frappe.throw(_("Invoice row references an inactive or foreign reservation owner line."))
        owner = owner_by_row[detail_no]
        if _clean(row.get("item_code")) != _clean(owner.item_code):
            frappe.throw(_("Invoice item does not match its reserved Sales Order Item."))
        if abs(flt(row.get("discount_percentage")) - flt(owner.discount_percentage)) > 0.005:
            frappe.throw(_("Reserved item discount is locked by its Sales Order Item."))
        stock_qty = flt(row.get("stock_qty")) or flt(row.qty) * (flt(row.get("conversion_factor")) or 1)
        consumed_by_row[detail_no] = normalized_qty(consumed_by_row.get(detail_no, 0) + stock_qty)
        sales_qty_by_row[detail_no] = flt(
            sales_qty_by_row.get(detail_no, 0) + flt(row.qty),
            6,
        )
        gross_amount_by_row[detail_no] = flt(
            gross_amount_by_row.get(detail_no, 0)
            + flt(row.qty) * flt(row.get("price_list_rate") or row.get("rate")),
            6,
        )
        net_amount_by_row[detail_no] = flt(
            net_amount_by_row.get(detail_no, 0)
            + flt(row.qty) * flt(row.get("rate")),
            6,
        )
    if not consumed_by_row:
        frappe.throw(_("Reservation invoice must include at least one linked reserved item row."))
    for detail_no, quantity in consumed_by_row.items():
        try:
            validate_reserved_fulfilment_qty(
                requested_qty=quantity,
                remaining_reserved_qty=remaining_by_row.get(detail_no, 0),
            )
            sales_qty = sales_qty_by_row.get(detail_no, 0)
            if sales_qty <= 0:
                raise ValueError("Reserved invoice quantity must be positive.")
            owner = owner_by_row[detail_no]
            validate_locked_reservation_price(
                locked_price_list_rate=owner.price_list_rate,
                locked_rate=owner.rate,
                locked_discount_percentage=owner.discount_percentage,
                invoice_price_list_rate=flt(
                    gross_amount_by_row[detail_no] / sales_qty,
                    6,
                ),
                invoice_rate=flt(
                    net_amount_by_row[detail_no] / sales_qty,
                    6,
                ),
                invoice_discount_percentage=owner.discount_percentage,
            )
        except ValueError as exc:
            frappe.throw(_(str(exc)))


def on_submit_customer_reservation_invoice(doc, method=None):
    sales_order = _reservation_sales_order_from_invoice(doc)
    if not sales_order:
        return
    order = frappe.get_doc("Sales Order", sales_order)
    mode = _invoice_fulfilment_mode(doc)
    entries = _reservation_entries(order.name)
    status = _operational_status(order, entries)
    if status not in ("Partially Fulfilled", "Picked Up", "Sent for Delivery"):
        remaining = normalized_qty(
            sum(
                remaining_qty(row.reserved_qty, row.delivered_qty)
                for row in entries
                if cint(row.docstatus) == 1
            )
        )
        status = "Partially Fulfilled" if remaining > 0 else (
            "Sent for Delivery"
            if mode == "Home Delivery"
            else "Picked Up"
        )
    values = {
        "custom_reservation_operational_status": status,
        "custom_reservation_fulfilment_mode": mode,
        "custom_reservation_fulfilment_invoice": doc.name,
        "custom_reservation_fulfilment_at": now_datetime(),
        "custom_reservation_fulfilment_by": frappe.session.user,
    }
    frappe.db.set_value("Sales Order", order.name, values, update_modified=False)
    order.update(values)
    order.add_comment(
        "Info",
        _("Reservation fulfilled through Pharmacy POS invoice {0}. Status: {1}.").format(
            doc.name, status
        ),
    )


def on_cancel_customer_reservation_invoice(doc, method=None):
    sales_order = _reservation_sales_order_from_invoice(doc)
    if not sales_order or not frappe.db.exists("Sales Order", sales_order):
        return
    order = frappe.get_doc("Sales Order", sales_order)
    entries = _reservation_entries(order.name)
    status = _operational_status(order, entries)
    values: dict[str, Any] = {"custom_reservation_operational_status": status}
    if order.custom_reservation_fulfilment_invoice == doc.name:
        values.update(
            {
                "custom_reservation_fulfilment_invoice": None,
                "custom_reservation_fulfilment_at": None,
                "custom_reservation_fulfilment_by": None,
            }
        )
    frappe.db.set_value("Sales Order", order.name, values, update_modified=False)
    order.add_comment(
        "Info",
        _("Reservation fulfilment invoice {0} was cancelled. Current status: {1}.").format(
            doc.name, status
        ),
    )


def on_update_after_submit_customer_reservation_invoice(doc, method=None):
    sales_order = _reservation_sales_order_from_invoice(doc)
    if (
        not sales_order
        or cint(doc.docstatus) != 1
        or _invoice_fulfilment_mode(doc) != "Home Delivery"
        or _clean(doc.get("custom_delivery_status")) != "Delivered"
        or not frappe.db.exists("Sales Order", sales_order)
    ):
        return
    entries = _reservation_entries(sales_order)
    remaining = normalized_qty(
        sum(
            remaining_qty(row.reserved_qty, row.delivered_qty)
            for row in entries
            if cint(row.docstatus) == 1
        )
    )
    if remaining > 0:
        frappe.db.set_value(
            "Sales Order",
            sales_order,
            "custom_reservation_operational_status",
            "Partially Fulfilled",
            update_modified=False,
        )
        return
    current = _clean(
        frappe.db.get_value(
            "Sales Order", sales_order, "custom_reservation_operational_status"
        )
    )
    if current == "Fulfilled":
        return
    frappe.db.set_value(
        "Sales Order",
        sales_order,
        {
            "custom_reservation_operational_status": "Fulfilled",
            "custom_reservation_fulfilment_invoice": doc.name,
            "custom_reservation_fulfilment_at": now_datetime(),
            "custom_reservation_fulfilment_by": frappe.session.user,
        },
        update_modified=False,
    )
    frappe.get_doc("Sales Order", sales_order).add_comment(
        "Info",
        _("Customer Reservation delivery completed through invoice {0}.").format(
            doc.name
        ),
    )
