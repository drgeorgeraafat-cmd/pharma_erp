from __future__ import annotations

from typing import Optional

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

EPSILON = 1e-9


def normalize_batch_key(batch_no: Optional[str]) -> str:
    return (batch_no or "").strip()


def validate_location(location: str, warehouse: str, allow_disabled: bool = False):
    row = frappe.db.get_value(
        "Pharmacy Storage Location",
        location,
        ["name", "warehouse", "disabled", "purpose"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Storage Location {0} does not exist.").format(frappe.bold(location)))
    if row.warehouse != warehouse:
        frappe.throw(_("Location {0} belongs to another Warehouse.").format(frappe.bold(location)))
    if row.disabled and not allow_disabled:
        frappe.throw(_("Location {0} is disabled.").format(frappe.bold(location)))
    return row


def get_item_flags(item_code: str):
    return frappe.db.get_value("Item", item_code, ["has_batch_no", "disabled"], as_dict=True) or frappe._dict()


def get_official_warehouse_qty(item_code: str, warehouse: str) -> float:
    return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0)


def get_official_batch_qty(item_code: str, warehouse: str, batch_no: str) -> float:
    batch_key = normalize_batch_key(batch_no)
    if not batch_key:
        return get_official_warehouse_qty(item_code, warehouse)
    value = frappe.db.sql(
        """
        SELECT COALESCE(SUM(actual_qty), 0)
        FROM `tabStock Ledger Entry`
        WHERE item_code=%s AND warehouse=%s AND IFNULL(batch_no, '')=%s
        """,
        (item_code, warehouse, batch_key),
    )
    return flt(value[0][0] if value else 0)


def get_allocated_qty(item_code: str, warehouse: str, batch_no: Optional[str] = None, location: Optional[str] = None) -> float:
    filters = {"item_code": item_code, "warehouse": warehouse}
    if batch_no is not None:
        filters["batch_key"] = normalize_batch_key(batch_no)
    if location:
        filters["location"] = location
    rows = frappe.get_all("Pharmacy Location Balance", filters=filters, pluck="qty")
    return sum(flt(x) for x in rows)


def get_unallocated_qty(item_code: str, warehouse: str, batch_no: Optional[str] = None) -> float:
    flags = get_item_flags(item_code)
    batch_key = normalize_batch_key(batch_no)
    if flags.get("has_batch_no"):
        if not batch_key:
            frappe.throw(_("Batch is required for batched item {0}.").format(frappe.bold(item_code)))
        official = get_official_batch_qty(item_code, warehouse, batch_key)
        allocated = get_allocated_qty(item_code, warehouse, batch_key)
    else:
        official = get_official_warehouse_qty(item_code, warehouse)
        allocated = get_allocated_qty(item_code, warehouse)
    return flt(official - allocated, 6)


def _balance_row_for_update(warehouse: str, location: str, item_code: str, batch_key: str):
    rows = frappe.db.sql(
        """
        SELECT name, qty
        FROM `tabPharmacy Location Balance`
        WHERE warehouse=%s AND location=%s AND item_code=%s AND batch_key=%s
        LIMIT 1 FOR UPDATE
        """,
        (warehouse, location, item_code, batch_key),
        as_dict=True,
    )
    return rows[0] if rows else None


def adjust_balance(*, warehouse: str, location: str, item_code: str, batch_no: Optional[str], delta: float):
    validate_location(location, warehouse)
    delta = flt(delta, 6)
    if abs(delta) <= EPSILON:
        return
    flags = get_item_flags(item_code)
    batch_key = normalize_batch_key(batch_no)
    if flags.get("has_batch_no") and not batch_key:
        frappe.throw(_("Batch is required for batched item {0}.").format(frappe.bold(item_code)))

    row = _balance_row_for_update(warehouse, location, item_code, batch_key)
    current = flt(row.qty if row else 0, 6)
    new_qty = flt(current + delta, 6)
    if new_qty < -EPSILON:
        frappe.throw(_("Location stock cannot become negative for {0} at {1}.").format(frappe.bold(item_code), frappe.bold(location)))

    if row:
        frappe.db.set_value("Pharmacy Location Balance", row.name, {"qty": max(new_qty, 0), "last_updated": now_datetime()})
    else:
        if delta < 0:
            frappe.throw(_("No location balance exists for {0} at {1}.").format(item_code, location))
        frappe.get_doc({
            "doctype": "Pharmacy Location Balance",
            "warehouse": warehouse,
            "location": location,
            "item_code": item_code,
            "batch_no": batch_key or None,
            "batch_key": batch_key,
            "qty": max(new_qty, 0),
            "last_updated": now_datetime(),
        }).insert(ignore_permissions=True)


def post_movement(*, movement_type: str, warehouse: str, item_code: str, qty: float,
                  batch_no: Optional[str] = None, from_location: Optional[str] = None,
                  to_location: Optional[str] = None, reference_doctype: str,
                  reference_name: str, reference_row: str, dedupe_key: str,
                  remarks: Optional[str] = None):
    qty = flt(qty, 6)
    if qty <= 0:
        frappe.throw(_("Movement quantity must be greater than zero."))
    if frappe.db.exists("Pharmacy Location Movement", {"dedupe_key": dedupe_key}):
        return {"skipped": True, "dedupe_key": dedupe_key}
    if from_location:
        validate_location(from_location, warehouse)
    if to_location:
        validate_location(to_location, warehouse)
    if from_location and to_location and from_location == to_location:
        frappe.throw(_("Source and target locations must be different."))

    if from_location:
        adjust_balance(warehouse=warehouse, location=from_location, item_code=item_code, batch_no=batch_no, delta=-qty)
    if to_location:
        adjust_balance(warehouse=warehouse, location=to_location, item_code=item_code, batch_no=batch_no, delta=qty)

    frappe.get_doc({
        "doctype": "Pharmacy Location Movement",
        "posting_datetime": now_datetime(),
        "movement_type": movement_type,
        "warehouse": warehouse,
        "item_code": item_code,
        "batch_no": normalize_batch_key(batch_no) or None,
        "qty": qty,
        "from_location": from_location,
        "to_location": to_location,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
        "reference_row": reference_row,
        "dedupe_key": dedupe_key,
        "remarks": remarks,
    }).insert(ignore_permissions=True)
    return {"skipped": False, "dedupe_key": dedupe_key}


@frappe.whitelist()
def get_location_qty(warehouse: str, location: str, item_code: str, batch_no: Optional[str] = None):
    validate_location(location, warehouse)
    return {"qty": flt(get_allocated_qty(item_code, warehouse, batch_no, location), 6)}


@frappe.whitelist()
def get_location_snapshot(item_code: str, warehouse: str):
    official = get_official_warehouse_qty(item_code, warehouse)
    rows = frappe.get_all("Pharmacy Location Balance", filters={"item_code": item_code, "warehouse": warehouse}, fields=["location", "batch_no", "qty"], order_by="location asc, batch_no asc")
    allocated = sum(flt(row.qty) for row in rows)
    return {"item_code": item_code, "warehouse": warehouse, "warehouse_qty": flt(official, 6), "allocated_qty": flt(allocated, 6), "unallocated_qty": flt(official-allocated, 6), "locations": rows}
