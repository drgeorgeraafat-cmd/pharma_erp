from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from pharma_erp.pharma_erp.inventory_count_service import (
    APPROVER_ROLES,
    COUNT_DOCTYPE,
    EVENT_DOCTYPE,
    LOCATION_SCOPE_TYPES,
    REVIEWER_ROLES,
    _batch_qty,
    _warehouse_company,
    _latest_batch_reconciliation_plan_for_row,
    batch_system_snapshot_fingerprint,
    build_batch_reconciliation_execution_preview,
    get_batch_system_snapshot,
    get_location_batch_snapshot,
    location_batch_snapshot_fingerprint,
    batch_reconciliation_row_status,
    get_batch_reconciliation_status,
    log_event,
    get_settings,
    inventory_count_enabled,
    require_any_role,
    require_feature_enabled,
)
from pharma_erp.pharma_erp.page.pharmacy_pos.api import _batch_price_context, search_items_for_warehouse


ALLOWED_ACTIONS = {
    "start_count",
    "complete_count",
    "begin_review",
    "approve_count",
    "post_count",
}


def _clean(value):
    return str(value or "").strip()


def _default_company():
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or ""
    )


def _validate_inventory_warehouse(warehouse: str, company: str | None = None) -> str:
    warehouse = _clean(warehouse)
    if not warehouse:
        frappe.throw(_("Warehouse is required."))
    actual_company = _warehouse_company(warehouse)
    if company and actual_company != company:
        frappe.throw(
            _("Warehouse {0} belongs to company {1}, not {2}.").format(
                frappe.bold(warehouse), frappe.bold(actual_company), frappe.bold(company)
            )
        )
    return warehouse


@frappe.whitelist()
def get_context(branch=None):
    company = _default_company()
    branches = frappe.get_all(
        "Pharmacy Branch Profile",
        filters={"company": company, "disabled": 0},
        fields=["branch"],
        order_by="branch asc",
        limit_page_length=200,
    )
    branch_names = [row.branch for row in branches if row.branch]
    selected_branch = _clean(branch)
    if not selected_branch and len(branch_names) == 1:
        selected_branch = branch_names[0]

    warehouses = []
    if selected_branch:
        warehouses = frappe.get_all(
            "Pharmacy Warehouse Profile",
            filters={"company": company, "branch": selected_branch, "disabled": 0, "physicality": "Physical"},
            fields=["warehouse", "operational_class", "is_sellable"],
            order_by="warehouse asc",
            limit_page_length=200,
        )

    settings = get_settings()
    return {
        "company": company,
        "branches": branch_names,
        "branch": selected_branch,
        "warehouses": warehouses,
        "feature_enabled": cint(inventory_count_enabled()),
        "blind_count_default": cint(settings.get("blind_count_default") or 1),
        "search_limit": 20,
    }


@frappe.whitelist()
def get_scope_options(scope_type, warehouse=None, item_code=None):
    """Return safe operational choices for the selected Inventory Count scope."""

    scope_type = _clean(scope_type)
    company = _default_company()

    if scope_type in LOCATION_SCOPE_TYPES:
        warehouse = _validate_inventory_warehouse(warehouse, company)
        rows = frappe.get_all(
            "Pharmacy Storage Location",
            filters={
                "warehouse": warehouse,
                "location_type": scope_type,
                "disabled": 0,
            },
            fields=["name", "location_code", "location_name", "parent_location"],
            order_by="location_code asc, name asc",
            limit_page_length=2000,
        )
        return [
            {
                "value": row.name,
                "label": " — ".join(
                    [part for part in [row.location_code or row.name, row.location_name] if part]
                ),
                "parent": row.parent_location or "",
            }
            for row in rows
        ]

    if scope_type == "Item Group":
        rows = frappe.get_all(
            "Item Group",
            fields=["name", "parent_item_group", "is_group"],
            order_by="lft asc, name asc",
            limit_page_length=2000,
        )
        return [
            {
                "value": row.name,
                "label": row.name,
                "parent": row.parent_item_group or "",
                "is_group": cint(row.is_group),
            }
            for row in rows
            if row.name
        ]

    if scope_type == "Batch":
        warehouse = _validate_inventory_warehouse(warehouse, company)
        item_code = _clean(item_code)
        if not item_code:
            return []
        rows = frappe.get_all(
            "Batch",
            filters={"item": item_code},
            fields=["name", "expiry_date", "disabled"],
            order_by="expiry_date asc, name asc",
            limit_page_length=2000,
        )
        result = []
        for row in rows:
            qty = flt(_batch_qty(row.name, warehouse, item_code), 6)
            # A Batch Count is an audit tool; show any batch that currently has
            # warehouse stock even when expired/disabled, plus active batches.
            if abs(qty) <= 0.000000001 and cint(row.disabled):
                continue
            result.append(
                {
                    "value": row.name,
                    "label": row.name,
                    "expiry_date": str(row.expiry_date or ""),
                    "qty": qty,
                    "disabled": cint(row.disabled),
                }
            )
        return result

    return []


@frappe.whitelist()
def get_item_group_hierarchy():
    """Return top-level Item Groups and descendants for the two-stage workstation selector."""
    rows = frappe.get_all(
        "Item Group",
        fields=["name", "parent_item_group", "is_group", "lft", "rgt"],
        order_by="lft asc, name asc",
        limit_page_length=5000,
    )
    by_name = {row.name: row for row in rows if row.name}
    root_name = "All Item Groups" if "All Item Groups" in by_name else None

    main_groups = []
    for row in rows:
        if not row.name:
            continue
        if root_name:
            if row.parent_item_group != root_name:
                continue
        elif row.parent_item_group:
            continue
        main_groups.append({"value": row.name, "label": row.name, "is_group": cint(row.is_group)})

    descendants = {}
    for main in main_groups:
        main_row = by_name.get(main["value"])
        scoped = []
        if main_row:
            for row in rows:
                if not row.name or row.name == main_row.name:
                    continue
                if flt(row.lft) > flt(main_row.lft) and flt(row.rgt) < flt(main_row.rgt):
                    depth = 1
                    parent = row.parent_item_group
                    seen = set()
                    while parent and parent != main_row.name and parent in by_name and parent not in seen:
                        seen.add(parent)
                        depth += 1
                        parent = by_name[parent].parent_item_group
                    scoped.append({
                        "value": row.name,
                        "label": row.name,
                        "parent": row.parent_item_group or "",
                        "depth": depth,
                        "is_group": cint(row.is_group),
                    })
        descendants[main["value"]] = scoped

    return {"main_groups": main_groups, "descendants": descendants}


@frappe.whitelist()
def get_item_group_scope_summary(warehouse, item_group):
    """Read-only preview for Item Group Count before Draft creation."""
    company = _default_company()
    warehouse = _validate_inventory_warehouse(warehouse, company)
    item_group = _clean(item_group)
    root = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
    if not root:
        frappe.throw(_("Select a valid Item Group."))

    rows = frappe.db.sql(
        """
        SELECT COUNT(DISTINCT b.item_code) AS item_count,
               COALESCE(SUM(b.actual_qty), 0) AS total_qty
        FROM `tabBin` b
        INNER JOIN `tabItem` i ON i.name = b.item_code
        INNER JOIN `tabItem Group` ig ON ig.name = i.item_group
        WHERE b.warehouse = %(warehouse)s
          AND b.actual_qty > 0
          AND i.disabled = 0
          AND ig.lft >= %(lft)s
          AND ig.rgt <= %(rgt)s
        """,
        {"warehouse": warehouse, "lft": root.lft, "rgt": root.rgt},
        as_dict=True,
    )
    row = rows[0] if rows else frappe._dict()
    return {
        "warehouse": warehouse,
        "item_group": item_group,
        "expected_items_with_stock": cint(row.get("item_count") or 0),
        "total_qty": flt(row.get("total_qty") or 0, 6),
    }


@frappe.whitelist()
def search_items(txt="", warehouse=None, blind_count=1):
    """Return each Item once while preserving Pharmacy POS matching/ranking.

    POS may return one row per stock source. Inventory Count deliberately collapses
    those rows to the Item identity, then opens an Inventory-specific Batch/Price
    picker after selection.
    """
    company = _default_company()
    warehouse = _validate_inventory_warehouse(warehouse, company)
    rows = search_items_for_warehouse(txt, warehouse, stock_only=True) or []
    blind = cint(blind_count)
    result = []
    seen = set()
    for row in rows:
        row = frappe._dict(row)
        item_code = row.get("item_code") or row.get("name")
        if not item_code or item_code in seen:
            continue
        seen.add(item_code)
        payload = {
            "name": item_code,
            "item_code": item_code,
            "item_name": row.get("item_name") or item_code,
            "item_name_ar": row.get("item_name_ar") or "",
            "ingredient_summary": row.get("ingredient_summary") or "",
            "image": row.get("image") or "",
            "stock_uom": row.get("stock_uom") or "",
            "has_batch_no": cint(row.get("has_batch_no")),
            "pack_size": flt(row.get("pack_size") or 1) or 1,
            "box_only": cint(row.get("box_only")),
            "barcode": row.get("barcode") or "",
            "matched_batch_no": row.get("matched_batch_no") or "",
        }
        if not blind:
            payload["actual_qty"] = flt(row.get("actual_qty"), 6)
        result.append(payload)
    return result


def _item_count_meta(item_code):
    fields = ["name", "item_name", "stock_uom", "has_batch_no"]
    for fieldname in ("custom_pack_size", "custom_box_only", "custom_customer_price"):
        if frappe.get_meta("Item").has_field(fieldname):
            fields.append(fieldname)
    item = frappe.db.get_value("Item", item_code, fields, as_dict=True)
    if not item:
        frappe.throw(_("Item {0} was not found.").format(frappe.bold(item_code)))
    return frappe._dict(item)


def _price_group_key(value) -> str:
    return f"{flt(value or 0, 6):.6f}"


def _batch_price_sources(item_code: str, warehouse: str) -> list[dict]:
    """Return positive Batch stock with POS-compatible retail-price context.

    This is an internal inventory helper. It deliberately includes expired or
    disabled Batches because physical counting must be able to discover them.
    """
    item = _item_count_meta(item_code)
    fallback_price = flt(item.get("custom_customer_price") or 0, 6)
    today = getdate(nowdate())
    rows = frappe.get_all(
        "Batch",
        filters={"item": item_code},
        fields=["name", "expiry_date", "disabled"],
        order_by="expiry_date asc, name asc",
        limit_page_length=5000,
    )
    sources = []
    for raw in rows:
        batch = frappe._dict(raw)
        qty = flt(_batch_qty(batch.name, warehouse, item_code), 6)
        if qty <= 0.000000001:
            continue
        price = _batch_price_context(batch.name, item_code, fallback_price)
        expired = cint(bool(batch.expiry_date and getdate(batch.expiry_date) < today))
        disabled = cint(batch.disabled)
        sources.append(
            {
                "batch_no": batch.name,
                "expiry_date": str(batch.expiry_date or ""),
                "customer_price": flt(price.get("customer_price") or 0, 6),
                "batch_price": flt(price.get("batch_price") or 0, 6),
                "price_source": price.get("price_source") or "",
                "price_integrity_error": cint(price.get("price_integrity_error")),
                "status": "Expired" if expired else ("Disabled" if disabled else "Saleable"),
                "expired": expired,
                "disabled": disabled,
                "available_qty": qty,
            }
        )
    sources.sort(
        key=lambda row: (
            flt(row.get("customer_price"), 6),
            getdate(row.get("expiry_date")) if row.get("expiry_date") else getdate("9999-12-31"),
            row.get("batch_no"),
        )
    )
    return sources


def _expected_price_groups(item_code: str, warehouse: str) -> list[dict]:
    grouped = {}
    for source in _batch_price_sources(item_code, warehouse):
        key = _price_group_key(source.get("customer_price"))
        group = grouped.setdefault(
            key,
            {
                "key": key,
                "customer_price": flt(source.get("customer_price") or 0, 6),
                "source_count": 0,
                "has_expired": 0,
                "has_disabled": 0,
                "price_integrity_error": 0,
            },
        )
        group["source_count"] += 1
        group["has_expired"] = cint(bool(group["has_expired"] or source.get("expired")))
        group["has_disabled"] = cint(bool(group["has_disabled"] or source.get("disabled")))
        group["price_integrity_error"] = cint(
            bool(group["price_integrity_error"] or source.get("price_integrity_error"))
        )
    return [grouped[key] for key in sorted(grouped, key=lambda value: flt(value, 6))]


@frappe.whitelist()
def get_count_stock_sources(item_code, warehouse, blind_count=1):
    """Return compact price groups for physical Batch counting.

    R1.9.1 intentionally does not expose the system Batch list during Counting.
    The counter sees only the available retail-price groups, then records the
    physical Batch/Expiry lots actually found on the shelf. This keeps Blind
    Count operationally useful without flooding the screen with historical lots.
    """
    company = _default_company()
    warehouse = _validate_inventory_warehouse(warehouse, company)
    item_code = _clean(item_code)
    item = _item_count_meta(item_code)
    pack_size = flt(item.get("custom_pack_size") or 1, 6) or 1
    box_only = cint(item.get("custom_box_only") or 0)
    blind = cint(blind_count)

    result = {
        "item_code": item_code,
        "item_name": item.get("item_name") or item_code,
        "stock_uom": item.get("stock_uom") or "",
        "has_batch_no": cint(item.get("has_batch_no")),
        "pack_size": pack_size,
        "box_only": box_only,
        "price_groups": [],
        "sources": [],
    }
    if not cint(item.get("has_batch_no")):
        return result

    groups = _expected_price_groups(item_code, warehouse)
    result["price_groups"] = groups

    # Detailed source data is intentionally withheld during Blind Count.  It is
    # retained for non-blind/review diagnostics only.
    if not blind:
        result["sources"] = _batch_price_sources(item_code, warehouse)
    return result


def _latest_breakdowns(count_name):
    rows = frappe.get_all(
        EVENT_DOCTYPE,
        filters={
            "inventory_count": count_name,
            "event_type": ["in", ["Batch Breakdown Saved", "Batch Breakdown Cleared"]],
        },
        fields=["event_type", "row_reference", "count_round", "payload_json", "event_datetime", "creation"],
        order_by="event_datetime asc, creation asc",
        limit_page_length=10000,
    )
    latest = {}
    for event in rows:
        key = (_clean(event.row_reference), cint(event.count_round or 1))
        if not key[0]:
            continue
        if event.event_type == "Batch Breakdown Cleared":
            latest[key] = {"segments": [], "price_groups": []}
            continue
        try:
            payload = json.loads(event.payload_json or "{}")
        except Exception:
            payload = {}
        latest[key] = {
            "segments": payload.get("segments") or [],
            "price_groups": payload.get("price_groups") or [],
        }
    return latest

def _validated_breakdown_segment(row, raw):
    raw = frappe._dict(raw or {})
    pack_size = flt(row.pack_size or 1, 6) or 1
    boxes = flt(raw.get("boxes") or 0, 6)
    units = flt(raw.get("units") or 0, 6)
    if boxes < 0 or units < 0 or abs(boxes - round(boxes)) > 0.000001 or abs(units - round(units)) > 0.000001:
        frappe.throw(_("Batch count Boxes and Units must be non-negative whole numbers."))
    boxes = int(round(boxes))
    units = int(round(units))
    if cint(row.box_only) and units:
        frappe.throw(_("Item {0} is Box Only; loose units are not allowed.").format(frappe.bold(row.item_code)))
    if pack_size > 1 and units >= pack_size:
        frappe.throw(_("Loose Units must be less than Pack Size {0} for Item {1}.").format(pack_size, frappe.bold(row.item_code)))
    qty = flt(boxes + (units / pack_size), 6)
    if qty <= 0:
        return None

    batch_no = _clean(raw.get("batch_no"))
    observed_expiry = _clean(raw.get("expiry_date"))
    if not observed_expiry:
        frappe.throw(_("Expiry Date is required for every physical Batch lot counted."))
    # Round-trip safety: a saved Batch Breakdown event stores the normalized
    # physical price as customer_price.  On a later edit, the browser sends that
    # persisted segment back without necessarily re-adding observed_price.  Treat
    # customer_price as the persisted observed value instead of silently falling
    # back to zero.  This is especially important for blank/AUTO Batch requests,
    # where there is no Batch master price to recover from.
    raw_observed_price = raw.get("observed_price")
    if raw_observed_price is None:
        raw_observed_price = raw.get("customer_price")
    has_observed_price = raw_observed_price is not None
    observed_price = flt(raw_observed_price or 0, 6)
    segment = {
        "batch_no": batch_no,
        "expiry_date": observed_expiry,
        "boxes": boxes,
        "units": units,
        "qty": qty,
        "source_kind": "Observed New / Unverified",
        "system_expiry_date": "",
        "expiry_mismatch": 0,
        "observed_price": observed_price,
        "customer_price": observed_price,
        "system_customer_price": 0.0,
        "price_mismatch": 0,
        "auto_batch_requested": cint(not bool(batch_no)),
    }

    if batch_no and frappe.db.exists("Batch", batch_no):
        batch = frappe.db.get_value("Batch", batch_no, ["item", "expiry_date", "disabled"], as_dict=True)
        if batch.item != row.item_code:
            frappe.throw(_("Batch {0} belongs to Item {1}, not {2}.").format(frappe.bold(batch_no), frappe.bold(batch.item), frappe.bold(row.item_code)))
        system_expiry = str(batch.expiry_date or "")
        mismatch = cint(bool(system_expiry and getdate(system_expiry) != getdate(observed_expiry)))
        price = _batch_price_context(batch_no, row.item_code, 0)
        system_price = flt(price.get("customer_price") or 0, 6)
        effective_observed_price = flt(observed_price if has_observed_price else system_price, 6)
        price_mismatch = cint(abs(effective_observed_price - system_price) > 0.000001)
        segment.update({
            "expiry_date": observed_expiry,
            "source_kind": "Existing Batch",
            "system_expiry_date": system_expiry,
            "expiry_mismatch": mismatch,
            "observed_price": effective_observed_price,
            "customer_price": effective_observed_price,
            "system_customer_price": system_price,
            "price_mismatch": price_mismatch,
            "price_source": price.get("price_source") or "",
            "auto_batch_requested": 0,
        })
    else:
        if batch_no:
            segment["source_kind"] = "Observed New Batch"
        else:
            segment["source_kind"] = "AUTO Batch Requested"

    return segment


def _normalize_price_groups(raw_groups) -> list[dict]:
    if isinstance(raw_groups, str):
        raw_groups = json.loads(raw_groups or "[]")
    if raw_groups is None:
        raw_groups = []
    if not isinstance(raw_groups, list):
        frappe.throw(_("Price Group resolution must be a list."))

    allowed = {"Counted", "Confirmed Zero"}
    result = []
    seen = set()
    for raw in raw_groups:
        row = frappe._dict(raw or {})
        price = flt(row.get("customer_price") or row.get("price") or 0, 6)
        key = _price_group_key(price)
        status = _clean(row.get("status"))
        if status not in allowed:
            frappe.throw(_("Every Price Group must be explicitly Counted or Confirmed Zero."))
        if key in seen:
            frappe.throw(_("Duplicate Price Group {0} in physical count.").format(price))
        seen.add(key)
        result.append(
            {
                "key": key,
                "customer_price": price,
                "status": status,
                "expected": cint(row.get("expected", 0)),
            }
        )
    return result


@frappe.whitelist()
def save_batch_breakdown(name, row_name, segments, price_groups=None):
    """Save a price-group-first physical Batch/Expiry count.

    The counter resolves each system retail-price group without seeing the old
    Batch list, then records only the physical Batch/Expiry lots actually found.
    Batch creation/reclassification remains deferred to the controlled
    Batch/Expiry Reconciliation phase.
    """
    require_feature_enabled()
    doc = frappe.get_doc(COUNT_DOCTYPE, _clean(name))
    if doc.status != "Counting":
        frappe.throw(_("Batch breakdown can only be entered while Counting."))
    row = next((r for r in (doc.items or []) if r.name == _clean(row_name)), None)
    if not row:
        frappe.throw(_("Inventory Count row was not found."))
    if not cint(row.has_batch_no):
        frappe.throw(_("Batch breakdown is only valid for Batch-controlled Items."))

    if isinstance(segments, str):
        segments = json.loads(segments or "[]")
    if not isinstance(segments, list):
        frappe.throw(_("Batch breakdown must be a list."))

    clean_segments = []
    for raw in segments:
        segment = _validated_breakdown_segment(row, raw)
        if segment:
            clean_segments.append(segment)

    # A physical Batch number cannot mean two different prices/expiries in the
    # same count.  Blank Batch numbers are allowed and become AUTO requests later.
    seen_batches = {}
    for segment in clean_segments:
        batch_no = _clean(segment.get("batch_no"))
        if not batch_no:
            continue
        identity = (_price_group_key(segment.get("customer_price")), _clean(segment.get("expiry_date")))
        previous = seen_batches.get(batch_no)
        if previous and previous != identity:
            frappe.throw(
                _("Physical Batch {0} was entered with conflicting Price/Expiry values.").format(
                    frappe.bold(batch_no)
                )
            )
        seen_batches[batch_no] = identity

    submitted_groups = _normalize_price_groups(price_groups)
    if not submitted_groups and clean_segments:
        # Compatibility fallback still enforces complete price-group resolution.
        distinct_prices = {}
        for segment in clean_segments:
            price = flt(segment.get("customer_price") or 0, 6)
            distinct_prices[_price_group_key(price)] = price
        submitted_groups = _normalize_price_groups(
            [{"customer_price": price, "status": "Counted"} for price in distinct_prices.values()]
        )

    expected_groups = _expected_price_groups(row.item_code, row.warehouse)
    expected_by_key = {group["key"]: group for group in expected_groups}
    submitted_by_key = {group["key"]: group for group in submitted_groups}

    missing = [group for key, group in expected_by_key.items() if key not in submitted_by_key]
    if missing:
        labels = ", ".join(str(flt(group.get("customer_price"), 2)) for group in missing)
        frappe.throw(
            _(
                "Resolve every available Price Group before saving this Item Count. Pending price(s): {0}."
            ).format(labels)
        )

    qty_by_price = {}
    for segment in clean_segments:
        key = _price_group_key(segment.get("customer_price"))
        qty_by_price[key] = flt(qty_by_price.get(key, 0) + flt(segment.get("qty"), 6), 6)

    for group in submitted_groups:
        key = group["key"]
        qty = flt(qty_by_price.get(key), 6)
        if group["status"] == "Counted" and qty <= 0.000000001:
            frappe.throw(
                _("Price Group {0} is marked Counted but has no physical quantity.").format(
                    flt(group["customer_price"], 2)
                )
            )
        if group["status"] == "Confirmed Zero" and qty > 0.000000001:
            frappe.throw(
                _("Price Group {0} cannot be Confirmed Zero while physical quantity was entered.").format(
                    flt(group["customer_price"], 2)
                )
            )
        group["expected"] = cint(key in expected_by_key)

    # Every physical segment must belong to a resolved group. Unexpected physical
    # prices are allowed, but must be explicitly added/resolved by the counter.
    unresolved_observed = [key for key in qty_by_price if key not in submitted_by_key]
    if unresolved_observed:
        frappe.throw(_("A physical Price Group was entered without being resolved in the count dialog."))

    if not clean_segments and any(group["status"] == "Counted" for group in submitted_groups):
        frappe.throw(_("Enter physical Batch/Expiry quantity for each Counted Price Group."))
    if not clean_segments and not submitted_groups:
        frappe.throw(_("Enter physical quantity or explicitly resolve the available Price Groups."))

    total_qty = flt(sum(flt(segment["qty"], 6) for segment in clean_segments), 6)
    pack_size = flt(row.pack_size or 1, 6) or 1
    total_boxes = int(total_qty + 0.000000001)
    total_units = int(round((total_qty - total_boxes) * pack_size))
    if total_units >= pack_size and pack_size > 1:
        total_boxes += total_units // int(pack_size)
        total_units = total_units % int(pack_size)

    location_batch_snapshot = []
    location_batch_snapshot_captured = 0
    if _clean(row.count_basis) == "Location":
        location_batch_snapshot = get_location_batch_snapshot(row.item_code, row.warehouse, row.location)
        location_batch_snapshot_captured = 1

    row.entry_mode = "Box / Unit"
    row.actual_boxes = total_boxes
    row.actual_loose_units = total_units
    row.actual_qty = total_qty
    row.count_entered = 1
    row.resolution_status = "Confirmed Zero" if total_qty <= 0.000000001 else "Counted"
    row.observed_batch_no = (
        clean_segments[0]["batch_no"]
        if len(clean_segments) == 1 and clean_segments[0]["batch_no"]
        else None
    )
    doc.save(ignore_permissions=True)

    refreshed = next(r for r in doc.items if r.name == row.name)
    if location_batch_snapshot_captured:
        snapshot_total = flt(sum(flt(raw.get("qty"), 6) for raw in location_batch_snapshot), 6)
        if abs(snapshot_total - flt(refreshed.expected_qty_at_count, 6)) > 0.000001:
            frappe.throw(
                _(
                    "Location Batch stock changed while Item {0} was being saved. Request a recount for this Item before continuing."
                ).format(frappe.bold(refreshed.item_code))
            )

    payload = {
        "segments": clean_segments,
        "price_groups": submitted_groups,
        "actual_qty": total_qty,
        "pack_size": pack_size,
        "mode": "Price Group First",
        "location_batch_snapshot_captured": location_batch_snapshot_captured,
        "location_batch_snapshot": location_batch_snapshot,
        "location_batch_snapshot_fingerprint": location_batch_snapshot_fingerprint(location_batch_snapshot) if location_batch_snapshot_captured else "",
    }
    log_event(
        doc.name,
        "Batch Breakdown Saved",
        row=refreshed,
        details=_("Price-group-first physical Batch / Expiry count captured."),
        payload=payload,
        count_round=refreshed.count_round,
    )
    return {
        "count": get_count(doc.name),
        "segments": clean_segments,
        "price_groups": submitted_groups,
    }


def _reconciliation_segment_action(segment):
    segment = frappe._dict(segment or {})
    batch_no = _clean(segment.get("batch_no"))
    if cint(segment.get("price_mismatch")):
        return "Reclassify to AUTO Batch", ["Reclassify to AUTO Batch"]
    if batch_no and frappe.db.exists("Batch", batch_no):
        if cint(segment.get("expiry_mismatch")):
            return "Correct Existing Expiry", ["Correct Existing Expiry", "Reclassify to AUTO Batch"]
        return "Use Existing Batch", ["Use Existing Batch"]
    if batch_no:
        return "Create Observed Batch", ["Create Observed Batch"]
    return "Create AUTO Batch", ["Create AUTO Batch"]


def _reconciliation_preview_row(doc, row, breakdown, status):
    today = getdate(nowdate())
    segments = breakdown.get("segments") or []
    saved_plan = _latest_batch_reconciliation_plan_for_row(doc.name, row)
    saved_decisions = {
        cint(raw.get("segment_index")): _clean(raw.get("action"))
        for raw in (saved_plan.get("decisions") or [])
    }
    physical = []
    for index, raw in enumerate(segments):
        segment = frappe._dict(raw or {})
        suggested, allowed = _reconciliation_segment_action(segment)
        selected = saved_decisions.get(index) if saved_decisions.get(index) in allowed else suggested
        expiry = _clean(segment.get("expiry_date"))
        physical.append({
            "segment_index": index,
            "batch_no": _clean(segment.get("batch_no")),
            "expiry_date": expiry,
            "customer_price": flt(segment.get("customer_price") or segment.get("observed_price"), 6),
            "qty": flt(segment.get("qty"), 6),
            "boxes": cint(segment.get("boxes")),
            "units": cint(segment.get("units")),
            "source_kind": _clean(segment.get("source_kind")),
            "expiry_mismatch": cint(segment.get("expiry_mismatch")),
            "price_mismatch": cint(segment.get("price_mismatch")),
            "auto_batch_requested": cint(segment.get("auto_batch_requested")),
            "system_expiry_date": _clean(segment.get("system_expiry_date")),
            "system_customer_price": flt(segment.get("system_customer_price"), 6),
            "expired": cint(bool(expiry and getdate(expiry) < today)),
            "suggested_action": suggested,
            "selected_action": selected,
            "allowed_actions": allowed,
        })

    system_sources = []
    for source in _batch_price_sources(row.item_code, row.warehouse):
        system_sources.append({
            "batch_no": source.get("batch_no"),
            "expiry_date": source.get("expiry_date"),
            "customer_price": flt(source.get("customer_price"), 6),
            "available_qty": flt(source.get("available_qty"), 6),
            "status": source.get("status"),
        })

    execution_preview = build_batch_reconciliation_execution_preview(doc, row)
    return {
        "row_name": row.name,
        "item_code": row.item_code,
        "item_name": row.item_name,
        "warehouse": row.warehouse,
        "pack_size": flt(row.pack_size or 1, 6),
        "actual_qty": flt(row.actual_qty, 6),
        "expected_qty": flt(row.expected_qty_at_count or row.snapshot_qty, 6),
        "variance_qty": flt(row.variance_qty, 6),
        "breakdown_fingerprint": status.get("breakdown_fingerprint") or "",
        "auto_batch_requests": cint(status.get("auto_batch_requests")),
        "expiry_mismatches": cint(status.get("expiry_mismatches")),
        "price_mismatches": cint(status.get("price_mismatches")),
        "composition_differences": cint(status.get("composition_differences")),
        "planned": cint(status.get("planned")),
        "execution_ready": cint(status.get("execution_ready")),
        "execution_stale": cint(status.get("execution_stale")),
        "physical_segments": physical,
        "system_sources": system_sources,
        "execution_targets": execution_preview.get("targets") or [],
        "movement_safe": cint(execution_preview.get("movement_safe")),
        "current_system_total": flt(execution_preview.get("current_system_total"), 6),
    }


@frappe.whitelist()
def get_batch_reconciliation_preview(name):
    require_feature_enabled()
    doc = frappe.get_doc(COUNT_DOCTYPE, _clean(name))
    if doc.status in {"Draft", "Counting", "Cancelled", "Posted"}:
        frappe.throw(_("Batch Reconciliation Review is available after Count Completed and before posting."))
    status = get_batch_reconciliation_status(doc)
    breakdowns = _latest_breakdowns(doc.name)
    rows = []
    for row in doc.items or []:
        row_status = batch_reconciliation_row_status(doc, row)
        if not cint(row_status.get("required")) and not cint(row_status.get("plan_stale")):
            continue
        breakdown = breakdowns.get((row.name, cint(row.count_round or 1)), {"segments": [], "price_groups": []})
        rows.append(_reconciliation_preview_row(doc, row, breakdown, row_status))
    return {"count": doc.name, "status": doc.status, "summary": status, "rows": rows}


@frappe.whitelist()
def save_batch_reconciliation_plan(name, plans):
    require_feature_enabled()
    require_any_role(REVIEWER_ROLES | APPROVER_ROLES, _("Inventory Reviewer / Approver"))
    doc = frappe.get_doc(COUNT_DOCTYPE, _clean(name))
    if doc.status not in {"Count Completed", "Under Review", "Approved"}:
        frappe.throw(_("Batch Reconciliation Plan can only be saved during Review or after Approval before posting."))
    if isinstance(plans, str):
        plans = json.loads(plans or "[]")
    if not isinstance(plans, list):
        frappe.throw(_("Batch Reconciliation Plan must be a list."))

    by_row = {_clean(plan.get("row_name")): frappe._dict(plan or {}) for plan in plans if isinstance(plan, dict)}
    breakdowns = _latest_breakdowns(doc.name)
    saved = []
    for row in doc.items or []:
        status = batch_reconciliation_row_status(doc, row)
        if not cint(status.get("required")):
            continue
        plan = by_row.get(row.name)
        if not plan:
            frappe.throw(_("A reconciliation decision is required for Item {0}.").format(frappe.bold(row.item_code)))
        if _clean(plan.get("breakdown_fingerprint")) != _clean(status.get("breakdown_fingerprint")):
            frappe.throw(_("Physical Batch evidence changed for Item {0}. Reload the reconciliation review.").format(frappe.bold(row.item_code)))

        breakdown = breakdowns.get((row.name, cint(row.count_round or 1)), {"segments": []})
        segments = breakdown.get("segments") or []
        decisions = plan.get("decisions") or []
        if not isinstance(decisions, list) or len(decisions) != len(segments):
            frappe.throw(_("Every physical Batch/Expiry lot needs a reconciliation action for Item {0}.").format(frappe.bold(row.item_code)))

        normalized = []
        seen = set()
        for decision in decisions:
            decision = frappe._dict(decision or {})
            index = cint(decision.get("segment_index"))
            if index < 0 or index >= len(segments) or index in seen:
                frappe.throw(_("Invalid or duplicate Batch Reconciliation segment selection."))
            seen.add(index)
            suggested, allowed = _reconciliation_segment_action(segments[index])
            action = _clean(decision.get("action")) or suggested
            if action not in allowed:
                frappe.throw(_("Reconciliation action {0} is not allowed for this physical lot.").format(frappe.bold(action)))
            normalized.append({"segment_index": index, "action": action})
        if len(seen) != len(segments):
            frappe.throw(_("Every physical Batch/Expiry lot must be reviewed."))

        system_snapshot = get_batch_system_snapshot(row.item_code, row.warehouse)
        current_total = flt(sum(flt(source.get("qty"), 6) for source in system_snapshot), 6)
        expected_at_count = flt(row.expected_qty_at_count, 6)
        if abs(current_total - expected_at_count) > 0.000001:
            frappe.throw(
                _(
                    "Warehouse stock moved after the physical count for Item {0}. "
                    "R1.10 R2 will not overwrite live pharmacy movement; request a recount for this Item."
                ).format(frappe.bold(row.item_code))
            )
        payload = {
            "version": "R1.10-R2",
            "breakdown_fingerprint": status.get("breakdown_fingerprint"),
            "system_snapshot": system_snapshot,
            "system_snapshot_fingerprint": batch_system_snapshot_fingerprint(system_snapshot),
            "expected_qty_at_count": expected_at_count,
            "execution_ready": 1,
            "decisions": sorted(normalized, key=lambda d: d["segment_index"]),
            "issue_summary": {
                "auto_batch_requests": cint(status.get("auto_batch_requests")),
                "expiry_mismatches": cint(status.get("expiry_mismatches")),
                "price_mismatches": cint(status.get("price_mismatches")),
                "composition_differences": cint(status.get("composition_differences")),
            },
        }
        log_event(
            doc.name,
            "Batch Reconciliation Plan Saved",
            row=row,
            details=_("Reviewer armed the R1.10 R2 Batch/Expiry/Price execution plan."),
            payload=payload,
            count_round=row.count_round,
        )
        saved.append(row.name)

    if not saved:
        frappe.throw(_("This Inventory Count has no Batch composition differences requiring a plan."))
    return {"saved_rows": saved, "count": get_count(doc.name)}


@frappe.whitelist()
def create_count(company, branch, warehouse=None, scope_type="Item", item_code=None, blind_count=1,
                 scope_location=None, item_group=None, batch_no=None):
    require_feature_enabled()
    company = _clean(company) or _default_company()
    scope_type = _clean(scope_type) or "Item"
    allowed_scopes = {"Branch", "Warehouse", "Zone", "Aisle", "Shelf", "Bin", "Item", "Item Group", "Batch"}
    if scope_type not in allowed_scopes:
        frappe.throw(_("Select a valid Inventory Count Scope Type."))
    warehouse = None if scope_type == "Branch" else _validate_inventory_warehouse(warehouse, company)
    doc = frappe.new_doc(COUNT_DOCTYPE)
    doc.company = company
    doc.branch = _clean(branch)
    doc.scope_type = scope_type
    doc.warehouse = warehouse
    doc.item_code = _clean(item_code) or None
    doc.scope_location = _clean(scope_location) or None
    doc.item_group = _clean(item_group) or None
    doc.batch_no = _clean(batch_no) or None
    doc.blind_count = cint(blind_count)
    doc.status = "Draft"
    doc.insert()
    return {"name": doc.name, "status": doc.status}


def _count_line_payload(row, *, blind=False):
    payload = {
        "name": row.name,
        "idx": row.idx,
        "warehouse": row.warehouse,
        "location": row.location,
        "item_code": row.item_code,
        "item_name": row.item_name,
        "stock_uom": row.stock_uom,
        "has_batch_no": cint(row.has_batch_no),
        "batch_no": row.batch_no,
        "entry_mode": row.entry_mode or "Stock Qty",
        "pack_size": flt(row.pack_size or 1, 6),
        "box_only": cint(row.box_only),
        "actual_boxes": cint(row.actual_boxes),
        "actual_loose_units": cint(row.actual_loose_units),
        "actual_qty": flt(row.actual_qty, 6) if cint(row.count_entered) else None,
        "count_entered": cint(row.count_entered),
        "resolution_status": row.resolution_status or "Pending",
        "found_location": row.found_location,
        "found_elsewhere_qty": flt(row.found_elsewhere_qty, 6),
        "posting_batch_no": row.posting_batch_no,
        "observed_batch_no": row.observed_batch_no,
        "reason_code": row.reason_code,
        "reason_note": row.reason_note,
        "count_round": cint(row.count_round or 1),
        "high_variance": cint(row.high_variance),
        "unexpected_item": cint(row.unexpected_item),
        "location_followup_required": cint(row.location_followup_required),
    }
    if not blind:
        payload.update(
            snapshot_qty=flt(row.snapshot_qty, 6),
            warehouse_snapshot_qty=flt(row.warehouse_snapshot_qty, 6),
            expected_qty_at_count=flt(row.expected_qty_at_count, 6),
            variance_qty=flt(row.variance_qty, 6),
            variance_value=flt(row.variance_value, 6),
        )
    return payload


def _batch_reconciliation_execution_summary(count_name: str) -> dict:
    """Return latest per-row execution evidence for terminal Posted UI.

    This is read-only presentation data. The authoritative audit remains
    Pharmacy Inventory Count Event / Stock Reconciliation / Batch master.
    """
    events = frappe.get_all(
        EVENT_DOCTYPE,
        filters={
            "inventory_count": count_name,
            "event_type": "Batch Reconciliation Executed",
        },
        fields=["row_reference", "payload_json", "event_datetime", "creation"],
        order_by="event_datetime desc, creation desc",
        limit_page_length=500,
    )
    latest_by_row = {}
    for event in events:
        row_reference = _clean(event.row_reference) or "__count__"
        if row_reference in latest_by_row:
            continue
        try:
            latest_by_row[row_reference] = json.loads(event.payload_json or "{}") or {}
        except Exception:
            latest_by_row[row_reference] = {}

    created_batches = []
    metadata_changes = []
    expired_targets = []
    for payload in latest_by_row.values():
        for batch_no in payload.get("created_batches") or []:
            batch_no = _clean(batch_no)
            if batch_no and batch_no not in created_batches:
                created_batches.append(batch_no)
        metadata_changes.extend(payload.get("metadata_changes") or [])
        expired_targets.extend(payload.get("expired_targets") or [])

    return {
        "executed_rows": len(latest_by_row),
        "created_batches": created_batches,
        "metadata_changes": metadata_changes,
        "expired_targets": expired_targets,
    }


@frappe.whitelist()
def get_count(name):
    name = _clean(name)
    if not name or not frappe.db.exists(COUNT_DOCTYPE, name):
        frappe.throw(_("Inventory Count was not found."))
    doc = frappe.get_doc(COUNT_DOCTYPE, name)
    blind = bool(cint(doc.blind_count) and doc.status == "Counting")
    breakdowns = _latest_breakdowns(doc.name)
    items = []
    for row in (doc.items or []):
        payload = _count_line_payload(row, blind=blind)
        breakdown = breakdowns.get((row.name, cint(row.count_round or 1)), {"segments": [], "price_groups": []})
        payload["batch_breakdown"] = breakdown.get("segments") or []
        payload["batch_price_groups"] = breakdown.get("price_groups") or []
        items.append(payload)
    reconciliation = (
        get_batch_reconciliation_status(doc)
        if doc.status not in {"Draft", "Counting"}
        else {
            "required": 0, "planned": 0, "rows_required": 0, "rows_planned": 0,
            "auto_batch_requests": 0, "expiry_mismatches": 0, "price_mismatches": 0,
            "composition_differences": 0, "plan_stale": 0, "execution_stale": 0, "execution_ready": 0, "executed": 0, "rows": [],
        }
    )
    if doc.status == "Posted" and cint(reconciliation.get("executed")):
        reconciliation["execution_summary"] = _batch_reconciliation_execution_summary(doc.name)
    return {
        "name": doc.name,
        "company": doc.company,
        "branch": doc.branch,
        "status": doc.status,
        "count_round": cint(doc.count_round or 1),
        "scope_type": doc.scope_type,
        "warehouse": doc.warehouse,
        "scope_location": doc.scope_location,
        "item_code": doc.item_code,
        "item_group": doc.item_group,
        "batch_no": doc.batch_no,
        "blind_count": cint(doc.blind_count),
        "snapshot_datetime": doc.snapshot_datetime,
        "stock_reconciliation": doc.stock_reconciliation,
        "total_actual_qty": flt(doc.total_actual_qty, 6),
        "net_variance_qty": None if blind else flt(doc.net_variance_qty, 6),
        "absolute_variance_qty": None if blind else flt(doc.absolute_variance_qty, 6),
        "total_variance_value": None if blind else flt(doc.total_variance_value, 6),
        "high_variance": cint(doc.high_variance),
        "batch_reconciliation": reconciliation,
        "items": items,
    }


@frappe.whitelist()
def save_line(name, row_name, entry_mode="Stock Qty", actual_qty=None, actual_boxes=None,
              actual_loose_units=None, resolution_status=None, found_location=None,
              found_elsewhere_qty=None, posting_batch_no=None, observed_batch_no=None,
              reason_code=None, reason_note=None):
    require_feature_enabled()
    doc = frappe.get_doc(COUNT_DOCTYPE, _clean(name))
    if doc.status != "Counting":
        frappe.throw(_("Physical quantities can only be entered while Counting."))
    row = next((r for r in (doc.items or []) if r.name == row_name), None)
    if not row:
        frappe.throw(_("Inventory Count row was not found."))

    row.entry_mode = _clean(entry_mode) or "Stock Qty"
    if row.entry_mode == "Box / Unit":
        row.actual_boxes = cint(actual_boxes or 0)
        row.actual_loose_units = cint(actual_loose_units or 0)
    else:
        if actual_qty is None or str(actual_qty).strip() == "":
            frappe.throw(_("Actual Qty is required."))
        row.actual_qty = flt(actual_qty, 6)
    row.count_entered = 1
    if resolution_status:
        row.resolution_status = _clean(resolution_status)
    if found_location is not None:
        row.found_location = _clean(found_location) or None
    if found_elsewhere_qty is not None:
        row.found_elsewhere_qty = flt(found_elsewhere_qty, 6)
    if posting_batch_no is not None:
        row.posting_batch_no = _clean(posting_batch_no) or None
    if observed_batch_no is not None:
        row.observed_batch_no = _clean(observed_batch_no) or None
    if reason_code is not None:
        row.reason_code = _clean(reason_code) or None
    if reason_note is not None:
        row.reason_note = _clean(reason_note) or None

    doc.save()
    refreshed = next(r for r in doc.items if r.name == row_name)
    if cint(refreshed.has_batch_no):
        log_event(
            doc.name,
            "Batch Breakdown Cleared",
            row=refreshed,
            details=_("Batch breakdown cleared by direct Item-total count entry."),
            payload={"entry_mode": refreshed.entry_mode, "actual_qty": refreshed.actual_qty},
            count_round=refreshed.count_round,
        )
    blind = bool(cint(doc.blind_count) and doc.status == "Counting")
    return _count_line_payload(refreshed, blind=blind)


@frappe.whitelist()
def run_action(name, action, args=None):
    require_feature_enabled()
    action = _clean(action)
    if action not in ALLOWED_ACTIONS:
        frappe.throw(_("Unsupported Inventory Count action."))
    doc = frappe.get_doc(COUNT_DOCTYPE, _clean(name))
    method = getattr(doc, action)
    parsed = json.loads(args) if isinstance(args, str) and args else (args or {})
    result = method(**parsed) if parsed else method()
    return {"result": result, "count": get_count(doc.name)}


@frappe.whitelist()
def confirm_zero(name, row_name):
    return save_line(
        name=name,
        row_name=row_name,
        entry_mode="Stock Qty",
        actual_qty=0,
        resolution_status="Confirmed Zero",
    )


@frappe.whitelist()
def add_found_item(name, item_code, warehouse=None, location=None, batch_no=None):
    require_feature_enabled()
    doc = frappe.get_doc(COUNT_DOCTYPE, _clean(name))
    result = doc.add_found_item(
        item_code=_clean(item_code),
        warehouse=_clean(warehouse) or None,
        location=_clean(location) or None,
        batch_no=_clean(batch_no) or None,
    )
    return {"result": result, "count": get_count(doc.name)}


@frappe.whitelist()
def request_recount(name, row_names):
    require_feature_enabled()
    doc = frappe.get_doc(COUNT_DOCTYPE, _clean(name))
    result = doc.request_recount(row_names=row_names)
    return {"result": result, "count": get_count(doc.name)}

@frappe.whitelist()
def save_review_line(name, row_name, reason_code=None, reason_note=None,
                     posting_batch_no=None, observed_batch_no=None,
                     found_location=None, found_elsewhere_qty=None):
    require_feature_enabled()
    doc = frappe.get_doc(COUNT_DOCTYPE, _clean(name))
    if doc.status not in {"Count Completed", "Under Review"}:
        frappe.throw(_("Review fields can only be edited after Count Completed and before Approval."))
    row = next((r for r in (doc.items or []) if r.name == row_name), None)
    if not row:
        frappe.throw(_("Inventory Count row was not found."))
    if reason_code is not None:
        row.reason_code = _clean(reason_code) or None
    if reason_note is not None:
        row.reason_note = _clean(reason_note) or None
    if posting_batch_no is not None:
        row.posting_batch_no = _clean(posting_batch_no) or None
    if observed_batch_no is not None:
        row.observed_batch_no = _clean(observed_batch_no) or None

    selected_reason = _clean(row.reason_code)
    if selected_reason == "Wrong Location":
        if _clean(row.count_basis) != "Location":
            frappe.throw(_("Wrong Location can only be used for a Location-based Inventory Count line."))
        variance = flt(row.variance_qty, 6)
        if variance >= -0.000001:
            frappe.throw(_("Wrong Location requires a shortage on the counted Location."))
        destination = _clean(found_location if found_location is not None else row.found_location)
        found_qty = flt(found_elsewhere_qty if found_elsewhere_qty is not None else row.found_elsewhere_qty, 6)
        shortage = abs(variance)
        if not destination:
            frappe.throw(_("Found Location is required when Reason is Wrong Location."))
        if destination == _clean(row.location):
            frappe.throw(_("Found Location must be different from the counted Location."))
        location_meta = frappe.db.get_value(
            "Pharmacy Storage Location", destination, ["warehouse", "disabled"], as_dict=True
        )
        if not location_meta or cint(location_meta.disabled):
            frappe.throw(_("Found Location must be an active Pharmacy Storage Location."))
        if _clean(location_meta.warehouse) != _clean(row.warehouse):
            frappe.throw(_("Found Location must belong to the same Warehouse as the counted Location."))
        if found_qty <= 0.000001:
            frappe.throw(_("Found Elsewhere Qty must be greater than zero."))
        if found_qty > shortage + 0.000001:
            frappe.throw(_("Found Elsewhere Qty {0} cannot exceed the counted shortage {1}.").format(found_qty, shortage))
        row.found_location = destination
        row.found_elsewhere_qty = found_qty
    else:
        row.found_location = None
        row.found_elsewhere_qty = 0

    doc.save()
    refreshed = next(r for r in doc.items if r.name == row_name)
    return _count_line_payload(refreshed, blind=False)
