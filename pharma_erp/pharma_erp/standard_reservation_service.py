"""Controlled standard reservation foundation for Pharma ERP v0.9.2 Step2B.

The durable stock hold remains ERPNext's submitted Stock Reservation Entry
owned by a Sales Order item. This layer adds canonical Branch/Warehouse
validation, Step2A ATP re-checks, idempotency and an auditable contract-state
mapping without overriding ERPNext Core.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_datetime, now_datetime

from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
    create_stock_reservation_entries_for_so_items,
    get_available_qty_to_reserve,
)

from pharma_erp.pharma_erp.branch_operational_integration import resolve_role_context
from pharma_erp.pharma_erp.reservation_contract import (
    ACTIVE_STATES,
    build_idempotency_key,
    contract_state,
    normalized_qty,
    reservation_ceiling,
    validate_terminal_state,
)
from pharma_erp.pharma_erp.unified_stock_availability import (
    get_unified_stock_availability,
)


ROLE = "Sales"
SRE_DOCTYPE = "Stock Reservation Entry"
REQUIRED_SRE_FIELDS = (
    "custom_pharmacy_branch",
    "custom_operational_role",
    "custom_contract_state",
    "custom_idempotency_key",
    "custom_original_reserved_qty",
    "custom_expires_at",
    "custom_terminal_reason",
    "custom_terminal_at",
    "custom_terminal_by",
)


def _clean(value: Any) -> str:
    return cstr(value or "").strip()


def _assert_installation() -> None:
    if not frappe.get_meta("Sales Order").has_field("custom_pharmacy_branch"):
        frappe.throw(_("Step2B Sales Order Branch metadata is not installed."))
    meta = frappe.get_meta(SRE_DOCTYPE)
    missing = [fieldname for fieldname in REQUIRED_SRE_FIELDS if not meta.has_field(fieldname)]
    if missing:
        frappe.throw(
            _("Step2B Stock Reservation Entry metadata is incomplete: {0}").format(
                ", ".join(missing)
            )
        )


def _reservation_requested(doc) -> bool:
    if cint(doc.get("reserve_stock")):
        return True
    return any(cint(row.get("reserve_stock")) for row in (doc.get("items") or []))


def _stock_item_codes(doc) -> set[str]:
    item_codes = sorted({_clean(row.item_code) for row in (doc.items or []) if _clean(row.item_code)})
    if not item_codes:
        return set()
    rows = frappe.get_all(
        "Item",
        filters={"name": ("in", item_codes)},
        fields=["name", "is_stock_item"],
        limit_page_length=max(100, len(item_codes) + 10),
    )
    return {row.name for row in rows if cint(row.is_stock_item)}


def _require_reservation_configuration(
    *, branch: str, warehouse: str, company: str, **_ignored
) -> None:
    if not cint(frappe.db.get_single_value("Stock Settings", "enable_stock_reservation")):
        frappe.throw(_("Stock Reservation is not enabled in Stock Settings."))

    branch_profile = frappe.db.get_value(
        "Pharmacy Branch Profile",
        {"branch": branch, "company": company, "disabled": 0},
        ["name", "allow_reservation"],
        as_dict=True,
    )
    if not branch_profile or not cint(branch_profile.allow_reservation):
        frappe.throw(
            _("Branch {0} is not enabled for controlled reservations.").format(
                frappe.bold(branch)
            )
        )

    warehouse_profile = frappe.db.get_value(
        "Pharmacy Warehouse Profile",
        {"warehouse": warehouse, "branch": branch, "company": company, "disabled": 0},
        ["name", "is_sellable", "allow_reservation"],
        as_dict=True,
    )
    if (
        not warehouse_profile
        or not cint(warehouse_profile.is_sellable)
        or not cint(warehouse_profile.allow_reservation)
    ):
        frappe.throw(
            _("Warehouse {0} is not enabled as a sellable reservation source.").format(
                frappe.bold(warehouse)
            )
        )


def validate_sales_order_reservation_context(doc, method=None):
    """Canonical guard for Sales Orders that explicitly request stock reservation."""

    if cint(doc.docstatus) == 2 or not _reservation_requested(doc):
        return
    _assert_installation()

    requested_branch = _clean(doc.get("custom_pharmacy_branch"))
    context = resolve_role_context(
        company=_clean(doc.company),
        role=ROLE,
        requested_branch=requested_branch,
        submitted_warehouse=_clean(doc.get("set_warehouse")),
    )
    _require_reservation_configuration(**context)

    doc.custom_pharmacy_branch = context["branch"]
    doc.set_warehouse = context["warehouse"]

    stock_items = _stock_item_codes(doc)
    for row in doc.items or []:
        if row.item_code not in stock_items:
            continue
        if _clean(row.get("warehouse")) and _clean(row.warehouse) != context["warehouse"]:
            frappe.throw(
                _(
                    "Sales Order row {0} warehouse {1} conflicts with canonical Sales warehouse {2} for Branch {3}."
                ).format(
                    row.idx,
                    frappe.bold(row.warehouse),
                    frappe.bold(context["warehouse"]),
                    frappe.bold(context["branch"]),
                )
            )
        row.warehouse = context["warehouse"]
        if cint(doc.get("reserve_stock")) and row.meta.has_field("reserve_stock"):
            row.reserve_stock = 1


def _owner_context(doc) -> frappe._dict:
    if _clean(doc.voucher_type) != "Sales Order":
        frappe.throw(_("Step2B supports Sales Order owned reservations only."))

    order = frappe.db.get_value(
        "Sales Order",
        doc.voucher_no,
        ["name", "docstatus", "company", "custom_pharmacy_branch", "set_warehouse"],
        as_dict=True,
    )
    if not order or cint(order.docstatus) != 1:
        frappe.throw(_("Reservation owner must be a submitted Sales Order."))

    row = frappe.db.get_value(
        "Sales Order Item",
        doc.voucher_detail_no,
        [
            "name",
            "parent",
            "item_code",
            "warehouse",
            "stock_qty",
            "delivered_qty",
            "conversion_factor",
            "stock_reserved_qty",
        ],
        as_dict=True,
    )
    if not row or row.parent != order.name:
        frappe.throw(_("Reservation owner line does not belong to the submitted Sales Order."))

    context = resolve_role_context(
        company=_clean(order.company),
        role=ROLE,
        requested_branch=_clean(order.custom_pharmacy_branch),
        submitted_warehouse=_clean(doc.warehouse or row.warehouse or order.set_warehouse),
    )
    _require_reservation_configuration(**context)

    if _clean(doc.item_code) != _clean(row.item_code):
        frappe.throw(_("Reservation item conflicts with its Sales Order owner line."))
    if _clean(doc.company) != context["company"]:
        frappe.throw(_("Reservation company conflicts with its canonical owner context."))

    return frappe._dict(order=order, row=row, **context)


def _key_for(doc, context: frappe._dict) -> str:
    return build_idempotency_key(
        voucher_type="Sales Order",
        voucher_no=doc.voucher_no,
        voucher_detail_no=doc.voucher_detail_no,
        item_code=doc.item_code,
        warehouse=context.warehouse,
        operational_role=ROLE,
    )


def _existing_for_key(key: str, *, exclude_name: str = "", for_update: bool = False):
    conditions = ["custom_idempotency_key=%s"]
    values: list[Any] = [key]
    if exclude_name:
        conditions.append("name<>%s")
        values.append(exclude_name)
    sql = "SELECT name, docstatus, custom_contract_state FROM `tabStock Reservation Entry` WHERE "
    sql += " AND ".join(conditions) + " ORDER BY creation ASC LIMIT 1"
    if for_update:
        sql += " FOR UPDATE"
    rows = frappe.db.sql(sql, tuple(values), as_dict=True)
    return rows[0] if rows else None


def prepare_standard_reservation_entry(doc, method=None):
    """Populate immutable owner/canonical metadata before a standard SRE is saved."""

    _assert_installation()
    context = _owner_context(doc)
    key = _key_for(doc, context)
    existing = _existing_for_key(key, exclude_name=_clean(doc.name))
    if existing:
        frappe.throw(
            _("Owner line already has reservation {0}; duplicate reservation is not allowed.").format(
                frappe.bold(existing.name)
            )
        )

    doc.custom_pharmacy_branch = context.branch
    doc.custom_operational_role = ROLE
    doc.custom_idempotency_key = key
    if not flt(doc.get("custom_original_reserved_qty")):
        doc.custom_original_reserved_qty = normalized_qty(doc.reserved_qty)
    doc.custom_contract_state = contract_state(
        docstatus=doc.docstatus,
        reserved_qty=doc.reserved_qty,
        delivered_qty=doc.delivered_qty,
        terminal_state=doc.get("custom_contract_state"),
    )

    if doc.get("custom_expires_at") and get_datetime(doc.custom_expires_at) <= now_datetime():
        frappe.throw(_("Reservation expiry must be in the future when the reservation is created."))


def _lock_final_scope(doc, context: frappe._dict) -> None:
    frappe.db.sql(
        "SELECT name FROM `tabSales Order Item` WHERE name=%s FOR UPDATE",
        doc.voucher_detail_no,
    )
    frappe.db.sql(
        "SELECT name FROM `tabBin` WHERE item_code=%s AND warehouse=%s FOR UPDATE",
        (doc.item_code, context.warehouse),
    )
    existing = _existing_for_key(
        doc.custom_idempotency_key,
        exclude_name=_clean(doc.name),
        for_update=True,
    )
    if existing:
        frappe.throw(
            _("Concurrent duplicate reservation was rejected; owner line already has {0}.").format(
                frappe.bold(existing.name)
            )
        )


def validate_before_submit_standard_reservation(doc, method=None):
    """Final transactional ATP and owner ceiling guard before standard submit."""

    prepare_standard_reservation_entry(doc)
    context = _owner_context(doc)
    _lock_final_scope(doc, context)

    availability = get_unified_stock_availability(
        item_code=doc.item_code,
        branch=context.branch,
        operational_role=ROLE,
        warehouse=context.warehouse,
        source_type="stock",
        enforce_permissions=False,
    )
    if not availability["states"]["reservation_enabled"]:
        frappe.throw(_("Step2A canonical context is not enabled for reservation."))

    row = frappe.db.get_value(
        "Sales Order Item",
        doc.voucher_detail_no,
        ["stock_qty", "delivered_qty", "conversion_factor", "stock_reserved_qty"],
        as_dict=True,
    )
    delivered_stock_qty = flt(row.delivered_qty) * (flt(row.conversion_factor) or 1)
    owner_remaining = normalized_qty(
        flt(row.stock_qty) - delivered_stock_qty - flt(row.stock_reserved_qty)
    )
    standard_available = normalized_qty(
        get_available_qty_to_reserve(
            doc.item_code,
            context.warehouse,
            ignore_sre=doc.name,
        )
    )
    unified_atp = normalized_qty(
        availability["quantities"]["available_to_promise"]
    )
    ceiling = reservation_ceiling(
        owner_remaining_qty=owner_remaining,
        unified_available_to_promise=unified_atp,
        standard_available_qty=standard_available,
    )
    requested = normalized_qty(doc.reserved_qty)
    if requested <= 0 or requested > ceiling:
        frappe.throw(
            _(
                "Cannot reserve {0}. Final controlled ceiling is {1} stock units "
                "(owner remaining {2}, unified ATP {3}, standard available {4})."
            ).format(requested, ceiling, owner_remaining, unified_atp, standard_available)
        )


def _write_contract_state(doc, state: str) -> None:
    values: dict[str, Any] = {"custom_contract_state": state}
    if not flt(doc.get("custom_original_reserved_qty")):
        values["custom_original_reserved_qty"] = normalized_qty(doc.reserved_qty)
    frappe.db.set_value(SRE_DOCTYPE, doc.name, values, update_modified=False)
    doc.update(values)


def sync_standard_reservation_contract(doc, method=None):
    if not doc.name or not frappe.get_meta(SRE_DOCTYPE).has_field("custom_contract_state"):
        return
    state = contract_state(
        docstatus=doc.docstatus,
        reserved_qty=doc.reserved_qty,
        delivered_qty=doc.delivered_qty,
        terminal_state=doc.get("custom_contract_state"),
    )
    _write_contract_state(doc, state)


def before_cancel_standard_reservation(doc, method=None):
    desired = _clean(getattr(doc.flags, "pharmacy_terminal_state", ""))
    if desired not in ("Released", "Expired", "Cancelled"):
        current = _clean(doc.get("custom_contract_state"))
        desired = current if current in ("Released", "Expired", "Cancelled") else "Cancelled"
    reason = _clean(getattr(doc.flags, "pharmacy_terminal_reason", "")) or _clean(
        doc.get("custom_terminal_reason")
    )
    values = {
        "custom_contract_state": desired,
        "custom_terminal_reason": reason or _("Owner reservation cancelled."),
        "custom_terminal_at": now_datetime(),
        "custom_terminal_by": frappe.session.user,
    }
    frappe.db.set_value(SRE_DOCTYPE, doc.name, values, update_modified=False)
    doc.update(values)


def on_cancel_standard_reservation(doc, method=None):
    sync_standard_reservation_contract(doc)


def _release_reservation(
    name: str,
    *,
    reason: str,
    terminal_state: str,
    ignore_permissions: bool,
) -> dict[str, Any]:
    terminal_state = validate_terminal_state(terminal_state)
    reason = _clean(reason)
    if not reason:
        frappe.throw(_("A release, expiry or cancellation reason is required."))

    frappe.db.sql(
        "SELECT name FROM `tabStock Reservation Entry` WHERE name=%s FOR UPDATE",
        name,
    )
    doc = frappe.get_doc(SRE_DOCTYPE, name)
    if not ignore_permissions and not doc.has_permission("cancel"):
        frappe.throw(_("You do not have permission to release this reservation."), frappe.PermissionError)

    current = _clean(doc.get("custom_contract_state"))
    if cint(doc.docstatus) == 2:
        if current == terminal_state:
            return {
                "reservation": doc.name,
                "contract_state": current,
                "idempotent": True,
            }
        frappe.throw(
            _("Reservation is already terminal in state {0}; it cannot become {1}.").format(
                current or "Cancelled", terminal_state
            )
        )
    if current == "Consumed":
        frappe.throw(_("A consumed reservation cannot be released or expired."))

    terminal_values = {
        "custom_contract_state": terminal_state,
        "custom_terminal_reason": reason,
        "custom_terminal_at": now_datetime(),
        "custom_terminal_by": frappe.session.user,
    }
    frappe.db.set_value(SRE_DOCTYPE, doc.name, terminal_values, update_modified=False)
    doc.update(terminal_values)
    doc.flags.pharmacy_terminal_state = terminal_state
    doc.flags.pharmacy_terminal_reason = reason
    doc.flags.ignore_permissions = ignore_permissions
    doc.cancel()
    doc.add_comment(
        "Info",
        _("Reservation moved to {0}. Reason: {1}").format(terminal_state, reason),
    )
    return {
        "reservation": doc.name,
        "contract_state": terminal_state,
        "idempotent": False,
    }


@frappe.whitelist()
def release_reservation(name: str, reason: str, terminal_state: str = "Released"):
    return _release_reservation(
        _clean(name),
        reason=reason,
        terminal_state=terminal_state,
        ignore_permissions=False,
    )


def expire_due_reservations(limit: int = 100):
    """Scheduled idempotent expiry for Step2B reservations only."""

    if not frappe.get_meta(SRE_DOCTYPE).has_field("custom_expires_at"):
        return {"evaluated": 0, "expired": 0, "failures": []}
    rows = frappe.get_all(
        SRE_DOCTYPE,
        filters={
            "docstatus": 1,
            "custom_operational_role": ROLE,
            "custom_contract_state": ("in", ACTIVE_STATES),
            "custom_expires_at": ("<=", now_datetime()),
        },
        fields=["name"],
        order_by="custom_expires_at asc, name asc",
        limit_page_length=max(1, min(cint(limit) or 100, 1000)),
    )
    failures = []
    expired = 0
    for index, row in enumerate(rows, start=1):
        savepoint = f"step2b_expiry_{index}"
        frappe.db.savepoint(savepoint)
        try:
            _release_reservation(
                row.name,
                reason=_("Reservation expiry policy reached."),
                terminal_state="Expired",
                ignore_permissions=True,
            )
            expired += 1
        except Exception:
            frappe.db.rollback(save_point=savepoint)
            failures.append(row.name)
            frappe.log_error(frappe.get_traceback(), "Step2B reservation expiry failed")
    return {"evaluated": len(rows), "expired": expired, "failures": failures}


@frappe.whitelist()
def reserve_sales_order_item(
    sales_order: str,
    sales_order_item: str,
    qty_in_stock_uom: float | None = None,
):
    """Idempotently create the standard SRE for one submitted owner line."""

    order = frappe.get_doc("Sales Order", _clean(sales_order))
    if not order.has_permission("read") or not frappe.has_permission(SRE_DOCTYPE, "create"):
        frappe.throw(_("You do not have permission to create this reservation."), frappe.PermissionError)
    if cint(order.docstatus) != 1:
        frappe.throw(_("Sales Order must be submitted before reservation."))
    validate_sales_order_reservation_context(order)

    row = next((item for item in order.items if item.name == sales_order_item), None)
    if not row:
        frappe.throw(_("Sales Order item row was not found."))
    key = build_idempotency_key(
        voucher_type="Sales Order",
        voucher_no=order.name,
        voucher_detail_no=row.name,
        item_code=row.item_code,
        warehouse=row.warehouse,
        operational_role=ROLE,
    )
    existing = _existing_for_key(key, for_update=True)
    if existing:
        if cint(existing.docstatus) < 2:
            return {
                "reservation": existing.name,
                "contract_state": existing.custom_contract_state,
                "idempotent": True,
            }
        frappe.throw(_("Owner line already completed a reservation lifecycle."))

    conversion_factor = flt(row.conversion_factor) or 1
    owner_remaining = normalized_qty(
        flt(row.stock_qty)
        - (flt(row.delivered_qty) * conversion_factor)
        - flt(row.stock_reserved_qty)
    )
    requested_stock_qty = normalized_qty(qty_in_stock_uom or owner_remaining)
    if requested_stock_qty <= 0:
        frappe.throw(_("Reservation quantity must be greater than zero."))

    create_stock_reservation_entries_for_so_items(
        order,
        items_details=[
            {
                "sales_order_item": row.name,
                "warehouse": row.warehouse,
                "qty_to_reserve": requested_stock_qty / conversion_factor,
                "conversion_factor": conversion_factor,
            }
        ],
        notify=False,
    )
    created = _existing_for_key(key, for_update=True)
    if not created or cint(created.docstatus) != 1:
        frappe.throw(_("Standard reservation was not created for the owner line."))
    return {
        "reservation": created.name,
        "contract_state": created.custom_contract_state,
        "idempotent": False,
    }
