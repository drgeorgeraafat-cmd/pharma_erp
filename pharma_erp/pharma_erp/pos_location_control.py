from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt

from pharma_erp.pharma_erp.location_service import (
    get_allocated_qty,
    get_official_batch_qty,
    get_official_warehouse_qty,
    post_movement,
)

CONTRACT_VERSION = "v0.9.3-step2b-r1"
SETTINGS_DOCTYPE = "Pharmacy POS Settings"
ENABLE_FIELD = "enable_location_stock_control"
EPSILON = 1e-9


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _payload(data: Any) -> frappe._dict:
    if isinstance(data, str):
        try:
            data = json.loads(data or "{}")
        except Exception:
            frappe.throw(_("Invalid POS location payload."))
    return frappe._dict(data or {})


def location_control_enabled() -> bool:
    meta = frappe.get_meta(SETTINGS_DOCTYPE)
    if not meta.has_field(ENABLE_FIELD):
        return False
    return bool(cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, ENABLE_FIELD) or 0))


def _require_authenticated_user() -> None:
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw(
            _("Authentication is required for POS location operations."),
            frappe.PermissionError,
        )


def _rule_priority_field() -> str | None:
    meta = frappe.get_meta("Pharmacy Item Location Rule")
    for name in ("rule_priority", "priority"):
        if meta.has_field(name):
            return name
    return None


def _active_item_rule(item_code: str, warehouse: str) -> frappe._dict | None:
    item_code = _clean(item_code)
    warehouse = _clean(warehouse)
    if not item_code or not warehouse:
        return None

    priority = _rule_priority_field()
    order_by = f"{priority} asc, modified desc, name asc" if priority else "modified desc, name asc"
    fields = [
        "name",
        "warehouse",
        "item_code",
        "item_group",
        "primary_location",
        "overflow_location",
        "disabled",
    ]
    if priority:
        fields.append(priority)

    exact = frappe.get_all(
        "Pharmacy Item Location Rule",
        filters={"warehouse": warehouse, "disabled": 0, "item_code": item_code},
        fields=fields,
        order_by=order_by,
        limit_page_length=1,
    )
    if exact:
        row = frappe._dict(exact[0])
        row.match_type = "Item"
        return row

    item_group = _clean(frappe.db.get_value("Item", item_code, "item_group"))
    if not item_group:
        return None

    group_rows = frappe.get_all(
        "Pharmacy Item Location Rule",
        filters={"warehouse": warehouse, "disabled": 0, "item_group": item_group},
        fields=fields,
        order_by=order_by,
        limit_page_length=50,
    )
    for candidate in group_rows:
        row = frappe._dict(candidate)
        if not _clean(row.item_code):
            row.match_type = "Item Group"
            return row
    return None


def _location_meta(location: str, warehouse: str) -> frappe._dict:
    row = frappe.db.get_value(
        "Pharmacy Storage Location",
        location,
        ["name", "location_code", "location_name", "warehouse", "purpose", "disabled"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Storage Location {0} does not exist.").format(frappe.bold(location)))
    if _clean(row.warehouse) != _clean(warehouse):
        frappe.throw(_("Storage Location {0} belongs to another Warehouse.").format(frappe.bold(location)))
    if cint(row.disabled):
        frappe.throw(_("Storage Location {0} is disabled.").format(frappe.bold(location)))
    return frappe._dict(row)


def _validate_rule_locations(rule: frappe._dict, warehouse: str) -> tuple[frappe._dict, frappe._dict | None]:
    primary = _location_meta(rule.primary_location, warehouse)
    if _clean(primary.purpose) != "Selling":
        frappe.throw(
            _("Primary Location {0} must have Purpose = Selling.").format(
                frappe.bold(primary.location_name or primary.name)
            )
        )

    reserve = None
    if _clean(rule.overflow_location):
        reserve = _location_meta(rule.overflow_location, warehouse)
        if _clean(reserve.purpose) != "Reserve":
            frappe.throw(
                _("Overflow / Reserve Location {0} must have Purpose = Reserve.").format(
                    frappe.bold(reserve.location_name or reserve.name)
                )
            )
    return primary, reserve


def _item_flags(item_code: str) -> frappe._dict:
    row = frappe.db.get_value(
        "Item",
        item_code,
        ["name", "item_name", "disabled", "is_stock_item", "has_batch_no"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Item {0} was not found.").format(frappe.bold(item_code)))
    return frappe._dict(row)


def _batch_location_mode(item_code: str, warehouse: str) -> str:
    """Choose batch-specific only when Step2A actually has batch-specific location rows."""
    specific = frappe.db.sql(
        """
        SELECT 1
        FROM `tabPharmacy Location Balance`
        WHERE item_code=%s
          AND warehouse=%s
          AND IFNULL(batch_no, '') <> ''
          AND ABS(IFNULL(qty, 0)) > 0.000000001
        LIMIT 1
        """,
        (item_code, warehouse),
    )
    return "batch_specific" if specific else "pooled"


def _source_requirements(item_code: str, warehouse: str, requested_qty: float, preferred_batch: str = "") -> list[frappe._dict]:
    requested_qty = flt(requested_qty, 6)
    if requested_qty <= 0:
        return []

    item = _item_flags(item_code)
    if cint(item.disabled) or not cint(item.is_stock_item):
        return []

    if not cint(item.has_batch_no):
        return [frappe._dict(batch_no="", qty=requested_qty)]

    # Reuse current Pharmacy POS FEFO / preferred-batch allocator.
    from pharma_erp.pharma_erp.page.pharmacy_pos.api import _allocate_batches

    allocations = _allocate_batches(
        item_code,
        warehouse,
        requested_qty,
        preferred_batch=_clean(preferred_batch) or None,
        strict_preferred=False,
    )
    return [
        frappe._dict(batch_no=_clean(row.get("batch_no")), qty=flt(row.get("qty"), 6))
        for row in allocations
        if flt(row.get("qty"), 6) > 0
    ]


def _official_qty(item_code: str, warehouse: str, batch_no: str, location_mode: str) -> float:
    item = _item_flags(item_code)
    if cint(item.has_batch_no) and batch_no and location_mode == "batch_specific":
        return flt(get_official_batch_qty(item_code, warehouse, batch_no), 6)
    return flt(get_official_warehouse_qty(item_code, warehouse), 6)


def _location_qty(item_code: str, warehouse: str, location: str, batch_no: str, location_mode: str) -> float:
    effective_batch = batch_no if location_mode == "batch_specific" else None
    return flt(get_allocated_qty(item_code, warehouse, effective_batch, location), 6)


def _allocated_qty(item_code: str, warehouse: str, batch_no: str, location_mode: str) -> float:
    effective_batch = batch_no if location_mode == "batch_specific" else None
    return flt(get_allocated_qty(item_code, warehouse, effective_batch), 6)


def _plan_requirements(data: frappe._dict) -> tuple[list[frappe._dict], list[str]]:
    warehouse = _clean(data.get("warehouse"))
    if not warehouse:
        frappe.throw(_("Warehouse is required for POS location planning."))

    grouped: dict[tuple[str, str], float] = defaultdict(float)
    selected_batches: dict[str, list[str]] = defaultdict(list)
    legacy_items: set[str] = set()

    for raw in data.get("items") or []:
        row = frappe._dict(raw or {})
        item_code = _clean(row.get("item_code"))
        qty = flt(row.get("qty"), 6)
        if not item_code or qty <= 0:
            continue

        item = _item_flags(item_code)
        if cint(item.disabled) or not cint(item.is_stock_item):
            legacy_items.add(item_code)
            continue

        rule = _active_item_rule(item_code, warehouse)
        if not rule:
            legacy_items.add(item_code)
            continue

        mode = _batch_location_mode(item_code, warehouse) if cint(item.has_batch_no) else "pooled"
        allocations = _source_requirements(
            item_code,
            warehouse,
            qty,
            preferred_batch=_clean(row.get("batch_no")),
        )

        if mode == "batch_specific":
            for source in allocations:
                grouped[(item_code, _clean(source.batch_no))] += flt(source.qty, 6)
        else:
            grouped[(item_code, "")] += qty
            for source in allocations:
                selected = _clean(source.batch_no)
                if selected and selected not in selected_batches[item_code]:
                    selected_batches[item_code].append(selected)

    rows = []
    for (item_code, grouped_batch_no), requested_qty in sorted(grouped.items()):
        rule = _active_item_rule(item_code, warehouse)
        if not rule:
            legacy_items.add(item_code)
            continue

        item = _item_flags(item_code)
        mode = _batch_location_mode(item_code, warehouse) if cint(item.has_batch_no) else "pooled"
        batch_no = grouped_batch_no if mode == "batch_specific" else ""
        primary, reserve = _validate_rule_locations(rule, warehouse)

        selling_qty = _location_qty(item_code, warehouse, primary.name, batch_no, mode)
        reserve_qty = _location_qty(item_code, warehouse, reserve.name, batch_no, mode) if reserve else 0.0
        allocated_qty = _allocated_qty(item_code, warehouse, batch_no, mode)
        official_qty = _official_qty(item_code, warehouse, batch_no, mode)
        unallocated_qty = flt(official_qty - allocated_qty, 6)
        shortage = flt(max(0.0, requested_qty - selling_qty), 6)

        if selling_qty + EPSILON >= requested_qty:
            status = "ready"
        elif reserve and reserve_qty + EPSILON >= shortage:
            status = "replenish_required"
        elif official_qty + EPSILON >= requested_qty and unallocated_qty > EPSILON:
            status = "putaway_required"
        else:
            status = "location_shortage"

        item_name = _clean(frappe.db.get_value("Item", item_code, "item_name")) or item_code
        rows.append(
            frappe._dict(
                item_code=item_code,
                item_name=item_name,
                batch_no=batch_no or None,
                selected_batches=selected_batches.get(item_code, []),
                location_batch_mode=mode,
                rule=rule.name,
                rule_match_type=rule.match_type,
                primary_location=primary.name,
                primary_location_label=primary.location_name or primary.name,
                reserve_location=reserve.name if reserve else None,
                reserve_location_label=(reserve.location_name or reserve.name) if reserve else None,
                requested_qty=flt(requested_qty, 6),
                selling_qty=selling_qty,
                reserve_qty=reserve_qty,
                shortage_qty=shortage,
                allocated_qty=allocated_qty,
                official_warehouse_qty=official_qty,
                unallocated_qty=unallocated_qty,
                status=status,
            )
        )

    return rows, sorted(legacy_items)


def build_pos_location_plan(data: Any) -> dict[str, Any]:
    payload = _payload(data)
    enabled = location_control_enabled()

    if not enabled:
        return {
            "contract_version": CONTRACT_VERSION,
            "enabled": False,
            "mode": "legacy_all_items",
            "warehouse": _clean(payload.get("warehouse")),
            "rows": [],
            "legacy_items": [
                _clean(row.get("item_code"))
                for row in (payload.get("items") or [])
                if _clean(row.get("item_code"))
            ],
            "requires_replenishment": False,
            "blocking": False,
            "blocking_rows": [],
        }

    rows, legacy_items = _plan_requirements(payload)
    replenish = any(row.status == "replenish_required" for row in rows)
    blockers = [row for row in rows if row.status in {"putaway_required", "location_shortage"}]

    return {
        "contract_version": CONTRACT_VERSION,
        "enabled": True,
        "mode": "location_control_opt_in",
        "warehouse": _clean(payload.get("warehouse")),
        "rows": [dict(row) for row in rows],
        "legacy_items": legacy_items,
        "controlled_item_count": len({row.item_code for row in rows}),
        "legacy_item_count": len(set(legacy_items)),
        "requires_replenishment": replenish,
        "blocking": bool(blockers),
        "blocking_rows": [dict(row) for row in blockers],
    }


@frappe.whitelist()
def get_pos_location_plan(data):
    _require_authenticated_user()
    return build_pos_location_plan(data)


def _blocking_message(plan: dict[str, Any]) -> str:
    parts = []
    for raw in plan.get("blocking_rows") or []:
        row = frappe._dict(raw)
        if row.status == "putaway_required":
            parts.append(
                _(
                    "{0}: Warehouse stock exists, but configured Selling / Reserve stock is insufficient. "
                    "Putaway is required before sale."
                ).format(frappe.bold(row.item_name or row.item_code))
            )
        else:
            parts.append(
                _("{0}: configured Selling / Reserve location stock is insufficient for the requested quantity.").format(
                    frappe.bold(row.item_name or row.item_code)
                )
            )
    return "<br>".join(parts)


def assert_payload_ready_for_submit(data: Any) -> dict[str, Any]:
    plan = build_pos_location_plan(data)
    if not plan.get("enabled"):
        return plan
    if plan.get("blocking"):
        frappe.throw(_blocking_message(plan))

    replenish_rows = [
        frappe._dict(row)
        for row in plan.get("rows") or []
        if row.get("status") == "replenish_required"
    ]
    if replenish_rows:
        names = ", ".join(sorted({row.item_name or row.item_code for row in replenish_rows}))
        frappe.throw(
            _("Selling Location replenishment is required before POS submit for: {0}.").format(
                frappe.bold(names)
            )
        )
    return plan


@frappe.whitelist()
def replenish_pos_locations(data):
    _require_authenticated_user()
    payload = _payload(data)
    if not location_control_enabled():
        return build_pos_location_plan(payload)

    request_key = _clean(payload.get("location_request_key"))
    if not request_key:
        frappe.throw(_("Location Request Key is required for controlled replenishment."))

    plan = build_pos_location_plan(payload)
    if plan.get("blocking"):
        frappe.throw(_blocking_message(plan))

    moved = []
    for raw in plan.get("rows") or []:
        row = frappe._dict(raw)
        if row.status != "replenish_required":
            continue
        if not row.reserve_location:
            frappe.throw(_("Reserve Location is required for replenishment."))

        movement_batch = row.batch_no if row.location_batch_mode == "batch_specific" else None
        dedupe_key = "|".join(
            [
                "POS-REPLENISH",
                request_key,
                row.item_code,
                _clean(movement_batch),
                row.reserve_location,
                row.primary_location,
            ]
        )
        result = post_movement(
            movement_type="POS Replenishment",
            warehouse=plan["warehouse"],
            item_code=row.item_code,
            qty=row.shortage_qty,
            batch_no=movement_batch,
            from_location=row.reserve_location,
            to_location=row.primary_location,
            reference_doctype=SETTINGS_DOCTYPE,
            reference_name=SETTINGS_DOCTYPE,
            reference_row=request_key,
            dedupe_key=dedupe_key,
            remarks=_("Pharmacy POS Replenish & Continue"),
        )
        moved.append(
            {
                "item_code": row.item_code,
                "batch_no": movement_batch,
                "source_batches": row.selected_batches or ([row.batch_no] if row.batch_no else []),
                "qty": row.shortage_qty,
                "from_location": row.reserve_location,
                "to_location": row.primary_location,
                "dedupe_key": dedupe_key,
                "skipped": bool(result.get("skipped")),
            }
        )

    refreshed = build_pos_location_plan(payload)
    if refreshed.get("blocking") or refreshed.get("requires_replenishment"):
        frappe.throw(_("POS location state changed during replenishment. Please review the cart again."))
    refreshed["movements"] = moved
    return refreshed


def _consume_controlled_item(
    *,
    invoice_name: str,
    reference_row: str,
    warehouse: str,
    item_code: str,
    qty: float,
    batch_no: str = "",
) -> dict[str, Any]:
    rule = _active_item_rule(item_code, warehouse)
    if not rule:
        return {"controlled": False, "item_code": item_code}

    primary, _reserve = _validate_rule_locations(rule, warehouse)
    item = _item_flags(item_code)
    mode = _batch_location_mode(item_code, warehouse) if cint(item.has_batch_no) else "pooled"
    movement_batch = batch_no if mode == "batch_specific" else None

    qty = flt(qty, 6)
    if qty <= 0:
        return {"controlled": True, "skipped": True, "reason": "non_positive_qty"}

    dedupe_key = f"POS-CONSUME|{invoice_name}|{reference_row}"

    # Idempotency must be resolved before current-balance validation. After the
    # first successful consumption, Selling stock may legitimately be zero; a
    # retry of the same invoice row must therefore be skipped, not blocked.
    if frappe.db.exists(
        "Pharmacy Location Movement",
        {"dedupe_key": dedupe_key},
    ):
        return {
            "controlled": True,
            "item_code": item_code,
            "invoice_batch_no": batch_no or None,
            "location_batch_no": movement_batch,
            "location_batch_mode": mode,
            "qty": qty,
            "selling_location": primary.name,
            "dedupe_key": dedupe_key,
            "skipped": True,
        }

    available = _location_qty(item_code, warehouse, primary.name, _clean(movement_batch), mode)
    if available + EPSILON < qty:
        frappe.throw(
            _(
                "Selling Location stock changed before invoice completion for {0}. "
                "Required: {1}, available at {2}: {3}."
            ).format(item_code, qty, primary.location_name or primary.name, available)
        )

    result = post_movement(
        movement_type="POS Sale Consumption",
        warehouse=warehouse,
        item_code=item_code,
        qty=qty,
        batch_no=movement_batch,
        from_location=primary.name,
        to_location=None,
        reference_doctype="Sales Invoice",
        reference_name=invoice_name,
        reference_row=reference_row,
        dedupe_key=dedupe_key,
        remarks=(
            _("Pharmacy POS Selling Location consumption")
            + (f" | Sales Invoice Batch: {batch_no}" if batch_no and not movement_batch else "")
        ),
    )
    return {
        "controlled": True,
        "item_code": item_code,
        "invoice_batch_no": batch_no or None,
        "location_batch_no": movement_batch,
        "location_batch_mode": mode,
        "qty": qty,
        "selling_location": primary.name,
        "dedupe_key": dedupe_key,
        "skipped": bool(result.get("skipped")),
    }


def apply_submitted_pos_invoice(invoice_name: str) -> dict[str, Any]:
    if not location_control_enabled():
        return {"enabled": False, "movements": []}

    doc = frappe.get_doc("Sales Invoice", invoice_name)
    if doc.docstatus != 1 or not cint(doc.get("is_pos")) or cint(doc.get("is_return")):
        return {"enabled": True, "movements": [], "skipped": True}

    movements = []
    for row in doc.items or []:
        item_code = _clean(row.item_code)
        if not item_code:
            continue
        item = _item_flags(item_code)
        if not cint(item.is_stock_item):
            continue

        qty = flt(row.get("stock_qty"), 6)
        if not qty:
            qty = flt(row.get("qty"), 6) * flt(row.get("conversion_factor") or 1, 6)
        if qty <= 0:
            continue

        warehouse = _clean(row.get("warehouse") or doc.get("set_warehouse"))
        if not warehouse:
            continue

        result = _consume_controlled_item(
            invoice_name=doc.name,
            reference_row=row.name,
            warehouse=warehouse,
            item_code=item_code,
            qty=qty,
            batch_no=_clean(row.get("batch_no")),
        )
        if result.get("controlled"):
            movements.append(result)

    return {"enabled": True, "movements": movements}


def reverse_pos_consumption_before_cancel(doc, method=None):
    # Reversal ignores current feature flag: previously controlled sales must restore their location balance.
    if not doc or not doc.name:
        return

    rows = frappe.get_all(
        "Pharmacy Location Movement",
        filters={
            "movement_type": "POS Sale Consumption",
            "reference_doctype": "Sales Invoice",
            "reference_name": doc.name,
        },
        fields=[
            "name",
            "warehouse",
            "item_code",
            "batch_no",
            "qty",
            "from_location",
            "reference_row",
        ],
        order_by="posting_datetime asc, name asc",
    )

    for raw in rows:
        row = frappe._dict(raw)
        if not row.from_location or flt(row.qty, 6) <= 0:
            continue
        post_movement(
            movement_type="Adjustment",
            warehouse=row.warehouse,
            item_code=row.item_code,
            qty=row.qty,
            batch_no=row.batch_no,
            from_location=None,
            to_location=row.from_location,
            reference_doctype="Sales Invoice",
            reference_name=doc.name,
            reference_row=row.reference_row or row.name,
            dedupe_key=f"POS-CONSUME-REVERSAL|{row.name}",
            remarks=_("POS Sale Cancellation — restore Selling Location"),
        )
