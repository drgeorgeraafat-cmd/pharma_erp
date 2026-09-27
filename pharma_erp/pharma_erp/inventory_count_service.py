from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Iterable

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate, nowtime

from pharma_erp.pharma_erp.branch_warehouse_foundation import get_branch_profile, get_warehouse_profile
from pharma_erp.pharma_erp.location_service import (
    get_allocated_qty,
    get_official_warehouse_qty,
    post_movement,
    validate_location,
)

SETTINGS_DOCTYPE = "Pharmacy Inventory Count Settings"
COUNT_DOCTYPE = "Pharmacy Inventory Count"
ITEM_DOCTYPE = "Pharmacy Inventory Count Item"
EVENT_DOCTYPE = "Pharmacy Inventory Count Event"
EPSILON = 1e-9

COUNTER_ROLES = {"Inventory Counter", "Stock Manager", "System Manager"}
REVIEWER_ROLES = {"Inventory Reviewer", "Stock Manager", "System Manager"}
APPROVER_ROLES = {"Inventory Approver", "Stock Manager", "System Manager"}
POSTER_ROLES = {"Inventory Stock Poster", "Stock Manager", "System Manager"}

LOCATION_SCOPE_TYPES = {"Zone", "Aisle", "Shelf", "Bin"}
WAREHOUSE_SCOPE_TYPES = {"Warehouse", "Item", "Item Group", "Batch"}
RESOLVED_STATES = {
    "Counted",
    "Confirmed Zero",
    "Found Elsewhere",
    "Resolved by Movement",
    "Authorized Exclusion",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def json_dumps(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)


def get_settings() -> frappe._dict:
    if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
        return frappe._dict(
            enable_inventory_count=0,
            blind_count_default=1,
            high_variance_value_threshold=0,
            high_variance_percentage_threshold=0,
            require_recount_for_full_shortage=1,
            maximum_recounts=2,
            high_variance_approval_role="Inventory High Variance Approver",
        )
    doc = frappe.get_single(SETTINGS_DOCTYPE)
    return frappe._dict(doc.as_dict())


def inventory_count_enabled() -> bool:
    if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
        return False
    return bool(cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, "enable_inventory_count") or 0))


def require_feature_enabled() -> None:
    if not inventory_count_enabled():
        frappe.throw(
            _("Inventory Count is disabled. Enable it explicitly in Pharmacy Inventory Count Settings before operation.")
        )


def _roles(user: str | None = None) -> set[str]:
    user = user or frappe.session.user
    if user == "Administrator":
        return {"System Manager"}
    return set(frappe.get_roles(user))


def require_any_role(allowed: set[str], label: str) -> None:
    if not (_roles() & allowed):
        frappe.throw(
            _("{0} permission is required for this action.").format(label),
            frappe.PermissionError,
        )


def require_high_variance_role() -> None:
    settings = get_settings()
    configured = clean(settings.get("high_variance_approval_role")) or "Inventory High Variance Approver"
    allowed = {configured, "Stock Manager", "System Manager"}
    require_any_role(allowed, _("High Variance Approval"))


def _item_meta(item_code: str) -> frappe._dict:
    fields = ["name", "item_name", "stock_uom", "item_group", "is_stock_item", "disabled", "has_batch_no", "has_serial_no"]
    item_meta = frappe.get_meta("Item")
    if item_meta.has_field("custom_pack_size"):
        fields.append("custom_pack_size")
    if item_meta.has_field("custom_box_only"):
        fields.append("custom_box_only")
    row = frappe.db.get_value(
        "Item",
        item_code,
        fields,
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Item {0} does not exist.").format(frappe.bold(item_code)))
    if cint(row.disabled):
        frappe.throw(_("Item {0} is disabled.").format(frappe.bold(item_code)))
    if not cint(row.is_stock_item):
        frappe.throw(_("Item {0} is not a stock item.").format(frappe.bold(item_code)))
    if cint(row.has_serial_no):
        frappe.throw(
            _("Serialized item {0} is not supported by Inventory Count R1.2.").format(frappe.bold(item_code))
        )
    return frappe._dict(row)


def _warehouse_company(warehouse: str) -> str:
    row = frappe.db.get_value("Warehouse", warehouse, ["company", "is_group", "disabled"], as_dict=True)
    if not row:
        frappe.throw(_("Warehouse {0} does not exist.").format(frappe.bold(warehouse)))
    if cint(row.is_group):
        frappe.throw(_("Group Warehouse {0} cannot be counted.").format(frappe.bold(warehouse)))
    if cint(row.disabled):
        frappe.throw(_("Warehouse {0} is disabled.").format(frappe.bold(warehouse)))
    return row.company


def validate_scope(doc) -> None:
    scope_type = clean(doc.scope_type)
    if scope_type not in {"Branch", "Warehouse", "Zone", "Aisle", "Shelf", "Bin", "Item", "Item Group", "Batch"}:
        frappe.throw(_("Select a valid Inventory Count Scope Type."))

    if not doc.company:
        frappe.throw(_("Company is required."))

    if scope_type == "Branch":
        if not doc.branch:
            frappe.throw(_("Branch is required for Branch Count."))
        profile = get_branch_profile(doc.branch, company=doc.company)
        if cint(profile.disabled):
            frappe.throw(_("Branch {0} is disabled.").format(frappe.bold(doc.branch)))
        return

    if not doc.warehouse:
        frappe.throw(_("Warehouse is required for {0} Count.").format(scope_type))

    company = _warehouse_company(doc.warehouse)
    if company != doc.company:
        frappe.throw(
            _("Warehouse {0} belongs to company {1}, not {2}.").format(
                frappe.bold(doc.warehouse), frappe.bold(company), frappe.bold(doc.company)
            )
        )

    warehouse_profile = get_warehouse_profile(doc.warehouse, company=doc.company)
    if doc.branch and warehouse_profile.branch != doc.branch:
        frappe.throw(
            _("Warehouse {0} belongs canonically to Branch {1}, not {2}.").format(
                frappe.bold(doc.warehouse), frappe.bold(warehouse_profile.branch), frappe.bold(doc.branch)
            )
        )
    if not doc.branch:
        doc.branch = warehouse_profile.branch

    if scope_type in LOCATION_SCOPE_TYPES:
        if not doc.scope_location:
            frappe.throw(_("Storage Location is required for {0} Count.").format(scope_type))
        location = validate_location(doc.scope_location, doc.warehouse)
        location_type = frappe.db.get_value("Pharmacy Storage Location", location.name, "location_type")
        if location_type != scope_type:
            frappe.throw(
                _("Selected Storage Location type is {0}, but Scope Type is {1}.").format(
                    frappe.bold(location_type), frappe.bold(scope_type)
                )
            )

    if scope_type == "Item":
        if not doc.item_code:
            frappe.throw(_("Item is required for Item Count."))
        _item_meta(doc.item_code)

    if scope_type == "Item Group":
        if not doc.item_group:
            frappe.throw(_("Item Group is required for Item Group Count."))
        if not frappe.db.exists("Item Group", doc.item_group):
            frappe.throw(_("Item Group {0} does not exist.").format(frappe.bold(doc.item_group)))

    if scope_type == "Batch":
        if not doc.batch_no:
            frappe.throw(_("Batch is required for Batch Count."))
        batch_item = frappe.db.get_value("Batch", doc.batch_no, "item")
        if not batch_item:
            frappe.throw(_("Batch {0} does not exist.").format(frappe.bold(doc.batch_no)))
        _item_meta(batch_item)
        if doc.item_code and doc.item_code != batch_item:
            frappe.throw(_("Batch {0} belongs to Item {1}.").format(frappe.bold(doc.batch_no), frappe.bold(batch_item)))
        doc.item_code = batch_item


def _physical_branch_warehouses(branch: str, company: str) -> list[str]:
    rows = frappe.get_all(
        "Pharmacy Warehouse Profile",
        filters={"branch": branch, "company": company, "disabled": 0, "physicality": "Physical"},
        pluck="warehouse",
        order_by="warehouse asc",
    )
    result = []
    for warehouse in rows:
        try:
            _warehouse_company(warehouse)
        except Exception:
            continue
        result.append(warehouse)
    if not result:
        frappe.throw(_("No active physical Warehouses are configured for Branch {0}.").format(frappe.bold(branch)))
    return result


def _descendant_locations(root: str, warehouse: str) -> list[str]:
    validate_location(root, warehouse)
    result = []
    queue = [root]
    seen = set()
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
        children = frappe.get_all(
            "Pharmacy Storage Location",
            filters={"parent_location": name, "warehouse": warehouse, "disabled": 0},
            pluck="name",
            order_by="replenishment_priority asc, location_code asc, name asc",
        )
        queue.extend(children)
    return result


def _item_groups(root: str) -> list[str]:
    groups = [root]
    try:
        from frappe.utils.nestedset import get_descendants_of

        groups.extend(get_descendants_of("Item Group", root) or [])
    except Exception:
        pass
    return list(dict.fromkeys(groups))


def _bin_valuation_rate(item_code: str, warehouse: str) -> float:
    rate = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate")
    if rate in (None, ""):
        rate = frappe.db.get_value("Item", item_code, "valuation_rate")
    return flt(rate or 0, 6)


def _batch_qty(batch_no: str, warehouse: str, item_code: str) -> float:
    from erpnext.stock.doctype.batch.batch import get_batch_qty

    rows = get_batch_qty(batch_no=batch_no, warehouse=warehouse, item_code=item_code) or []
    if isinstance(rows, (int, float)):
        return flt(rows, 6)
    if isinstance(rows, dict):
        return flt(rows.get("qty") or rows.get(batch_no) or 0, 6)
    total = 0.0
    for raw in rows:
        row = frappe._dict(raw)
        candidate = clean(row.get("batch_no") or row.get("name"))
        if candidate and candidate != batch_no:
            continue
        total += flt(row.get("qty") or row.get("actual_qty") or 0, 6)
    return flt(total, 6)


def _available_batches_for_adjustment(item_code: str, warehouse: str, *, location: str | None = None) -> list[frappe._dict]:
    today = getdate(nowdate())
    rows = frappe.get_all(
        "Batch",
        filters={"item": item_code, "disabled": 0},
        fields=["name", "expiry_date"],
        order_by="expiry_date asc, name asc",
        limit_page_length=1000,
    )
    result = []
    for raw in rows:
        batch = frappe._dict(raw)
        if batch.expiry_date and getdate(batch.expiry_date) < today:
            continue
        if location:
            qty = flt(get_allocated_qty(item_code, warehouse, batch.name, location), 6)
        else:
            qty = _batch_qty(batch.name, warehouse, item_code)
        if qty <= EPSILON:
            continue
        result.append(frappe._dict(batch_no=batch.name, expiry_date=batch.expiry_date, qty=qty))
    result.sort(key=lambda d: (getdate(d.expiry_date) if d.expiry_date else getdate("9999-12-31"), d.batch_no))
    return result


def allocate_batch_shortage(item_code: str, warehouse: str, qty: float, *, location: str | None = None) -> list[frappe._dict]:
    """Allocate a shortage by the same FEFO principle used by Pharmacy POS.

    Expired/disabled batches are not guessed automatically. If non-expired FEFO
    stock cannot cover the shortage, the count must be resolved explicitly by
    Batch Count / review instead of silently changing the wrong batch.
    """

    remaining = flt(qty, 6)
    if remaining <= EPSILON:
        return []
    allocations = []
    for batch in _available_batches_for_adjustment(item_code, warehouse, location=location):
        if remaining <= EPSILON:
            break
        take = min(flt(batch.qty, 6), remaining)
        if take <= EPSILON:
            continue
        allocations.append(frappe._dict(batch_no=batch.batch_no, qty=flt(take, 6), current_qty=flt(batch.qty, 6)))
        remaining = flt(remaining - take, 6)
    if remaining > EPSILON:
        frappe.throw(
            _(
                "Automatic FEFO batch resolution cannot cover shortage {0} for Item {1}. "
                "Run a Batch Count or resolve the Batch explicitly."
            ).format(qty, frappe.bold(item_code))
        )
    return allocations


def validate_posting_batch(item_code: str, batch_no: str) -> None:
    batch_no = clean(batch_no)
    if not batch_no:
        frappe.throw(_("Physical Batch is required before posting excess stock for Item {0}.").format(frappe.bold(item_code)))
    batch_item = frappe.db.get_value("Batch", batch_no, "item")
    if not batch_item:
        frappe.throw(_("Batch {0} does not exist. Verify/create the real physical Batch before posting.").format(frappe.bold(batch_no)))
    if batch_item != item_code:
        frappe.throw(_("Batch {0} belongs to Item {1}, not {2}.").format(frappe.bold(batch_no), frappe.bold(batch_item), frappe.bold(item_code)))


def get_location_batch_snapshot(item_code: str, warehouse: str, location: str) -> list[dict[str, Any]]:
    """Return the live operational Batch composition for one Item at one Location."""
    rows = frappe.get_all(
        "Pharmacy Location Balance",
        filters={"item_code": item_code, "warehouse": warehouse, "location": location},
        fields=["batch_no", "qty"],
        order_by="batch_no asc",
        limit_page_length=5000,
    )
    totals = defaultdict(float)
    for raw in rows:
        row = frappe._dict(raw or {})
        qty = flt(row.get("qty"), 6)
        if abs(qty) <= EPSILON:
            continue
        batch_no = clean(row.get("batch_no"))
        if not batch_no:
            frappe.throw(
                _("Batch-controlled Item {0} has Location stock without a Batch at {1}. Repair Location stock before counting.").format(
                    frappe.bold(item_code), frappe.bold(location)
                )
            )
        totals[batch_no] = flt(totals[batch_no] + qty, 6)
    return [
        {"batch_no": batch_no, "qty": flt(qty, 6)}
        for batch_no, qty in sorted(totals.items())
        if abs(flt(qty, 6)) > EPSILON
    ]


def location_batch_snapshot_fingerprint(snapshot: list[dict[str, Any]]) -> str:
    normalized = [
        {"batch_no": clean(frappe._dict(raw or {}).get("batch_no")), "qty": flt(frappe._dict(raw or {}).get("qty"), 6)}
        for raw in (snapshot or [])
    ]
    normalized.sort(key=lambda row: (row["batch_no"], row["qty"]))
    return hashlib.sha256(json_dumps(normalized).encode("utf-8")).hexdigest()


def _warehouse_expected_rows(warehouse: str, *, item_codes: Iterable[str] | None = None) -> list[frappe._dict]:
    params: list[Any] = [warehouse]
    item_filter = ""
    item_codes = list(item_codes or [])
    if item_codes:
        placeholders = ",".join(["%s"] * len(item_codes))
        item_filter = f" AND i.name IN ({placeholders})"
        params.extend(item_codes)

    rows = frappe.db.sql(
        f"""
        SELECT i.name AS item_code, i.item_name, i.stock_uom, i.has_batch_no, i.has_serial_no,
               COALESCE(b.actual_qty, 0) AS snapshot_qty
        FROM `tabItem` i
        LEFT JOIN `tabBin` b ON b.item_code=i.name AND b.warehouse=%s
        WHERE i.disabled=0 AND i.is_stock_item=1
          AND ABS(COALESCE(b.actual_qty, 0)) > 0.000000001
          {item_filter}
        ORDER BY i.name
        """,
        tuple(params),
        as_dict=True,
    )

    # Surface operational-location-only inconsistencies too, even if Bin is zero.
    loc_params: list[Any] = [warehouse]
    loc_filter = ""
    if item_codes:
        placeholders = ",".join(["%s"] * len(item_codes))
        loc_filter = f" AND lb.item_code IN ({placeholders})"
        loc_params.extend(item_codes)
    location_only = frappe.db.sql(
        f"""
        SELECT lb.item_code
        FROM `tabPharmacy Location Balance` lb
        WHERE lb.warehouse=%s {loc_filter}
        GROUP BY lb.item_code
        HAVING ABS(SUM(COALESCE(lb.qty,0))) > 0.000000001
        """,
        tuple(loc_params),
        as_dict=True,
    )
    known = {row.item_code for row in rows}
    for raw in location_only:
        if raw.item_code in known:
            continue
        item = _item_meta(raw.item_code)
        rows.append(
            frappe._dict(
                item_code=item.name,
                item_name=item.item_name,
                stock_uom=item.stock_uom,
                has_batch_no=item.has_batch_no,
                has_serial_no=item.has_serial_no,
                snapshot_qty=get_official_warehouse_qty(item.name, warehouse),
            )
        )
    return rows


def _line_dict(*, warehouse: str, item_code: str, snapshot_qty: float, count_basis: str,
               location: str | None = None, batch_no: str | None = None,
               snapshot_datetime=None, unexpected: int = 0) -> dict[str, Any]:
    item = _item_meta(item_code)
    if batch_no:
        validate_posting_batch(item_code, batch_no)
    return {
        "warehouse": warehouse,
        "location": location,
        "item_code": item_code,
        "item_name": item.item_name,
        "stock_uom": item.stock_uom,
        "pack_size": flt(item.get("custom_pack_size") or 1, 6) or 1,
        "box_only": cint(item.get("custom_box_only") or 0),
        "entry_mode": "Stock Qty",
        "has_batch_no": cint(item.has_batch_no),
        "batch_no": batch_no,
        "count_basis": count_basis,
        "snapshot_qty": flt(snapshot_qty, 6),
        "warehouse_snapshot_qty": flt(get_official_warehouse_qty(item_code, warehouse), 6),
        "valuation_rate_snapshot": _bin_valuation_rate(item_code, warehouse),
        "resolution_status": "Pending",
        "count_entered": 0,
        "count_round": 1,
        "unexpected_item": cint(unexpected),
        "line_key": "|".join([warehouse, location or "", item_code, batch_no or ""]),
        "snapshot_datetime": snapshot_datetime,
    }


def build_snapshot_rows(doc) -> list[dict[str, Any]]:
    validate_scope(doc)
    scope_type = clean(doc.scope_type)
    snapshot_datetime = now_datetime()
    rows: list[dict[str, Any]] = []

    if scope_type == "Branch":
        for warehouse in _physical_branch_warehouses(doc.branch, doc.company):
            for raw in _warehouse_expected_rows(warehouse):
                rows.append(
                    _line_dict(
                        warehouse=warehouse,
                        item_code=raw.item_code,
                        snapshot_qty=raw.snapshot_qty,
                        count_basis="Warehouse",
                        snapshot_datetime=snapshot_datetime,
                    )
                )

    elif scope_type == "Warehouse":
        for raw in _warehouse_expected_rows(doc.warehouse):
            rows.append(
                _line_dict(
                    warehouse=doc.warehouse,
                    item_code=raw.item_code,
                    snapshot_qty=raw.snapshot_qty,
                    count_basis="Warehouse",
                    snapshot_datetime=snapshot_datetime,
                )
            )

    elif scope_type == "Item":
        _item_meta(doc.item_code)
        rows.append(
            _line_dict(
                warehouse=doc.warehouse,
                item_code=doc.item_code,
                snapshot_qty=get_official_warehouse_qty(doc.item_code, doc.warehouse),
                count_basis="Warehouse",
                snapshot_datetime=snapshot_datetime,
            )
        )

    elif scope_type == "Item Group":
        groups = _item_groups(doc.item_group)
        item_codes = frappe.get_all(
            "Item",
            filters={"item_group": ["in", groups], "disabled": 0, "is_stock_item": 1},
            pluck="name",
            limit_page_length=10000,
        )
        for raw in _warehouse_expected_rows(doc.warehouse, item_codes=item_codes):
            rows.append(
                _line_dict(
                    warehouse=doc.warehouse,
                    item_code=raw.item_code,
                    snapshot_qty=raw.snapshot_qty,
                    count_basis="Warehouse",
                    snapshot_datetime=snapshot_datetime,
                )
            )

    elif scope_type in LOCATION_SCOPE_TYPES:
        locations = _descendant_locations(doc.scope_location, doc.warehouse)
        placeholders = ",".join(["%s"] * len(locations))
        location_rows = frappe.db.sql(
            f"""
            SELECT lb.location, lb.item_code, SUM(COALESCE(lb.qty,0)) AS qty
            FROM `tabPharmacy Location Balance` lb
            INNER JOIN `tabPharmacy Storage Location` loc ON loc.name=lb.location
            WHERE lb.warehouse=%s
              AND lb.location IN ({placeholders})
              AND loc.disabled=0
            GROUP BY lb.location, lb.item_code
            HAVING ABS(SUM(COALESCE(lb.qty,0))) > 0.000000001
            ORDER BY MIN(loc.replenishment_priority), MIN(loc.location_code), lb.item_code
            """,
            tuple([doc.warehouse] + locations),
            as_dict=True,
        )
        for raw in location_rows:
            rows.append(
                _line_dict(
                    warehouse=doc.warehouse,
                    location=raw.location,
                    item_code=raw.item_code,
                    snapshot_qty=raw.qty,
                    count_basis="Location",
                    snapshot_datetime=snapshot_datetime,
                )
            )

    elif scope_type == "Batch":
        item_code = doc.item_code or frappe.db.get_value("Batch", doc.batch_no, "item")
        rows.append(
            _line_dict(
                warehouse=doc.warehouse,
                item_code=item_code,
                batch_no=doc.batch_no,
                snapshot_qty=_batch_qty(doc.batch_no, doc.warehouse, item_code),
                count_basis="Warehouse",
                snapshot_datetime=snapshot_datetime,
            )
        )

    rows.sort(key=lambda d: (d["warehouse"], d.get("location") or "", d["item_code"], d.get("batch_no") or ""))
    return rows



def assert_no_overlap(count_name: str, rows: Iterable[Any]) -> None:
    """Prevent two active counts from owning the same Warehouse+Item concurrently.

    R1.2 intentionally uses a conservative key. A Warehouse-total count and a
    Location count for the same Item overlap because either can later change the
    operational/official interpretation of that stock. Explicit Batch Counts may
    coexist only with other different-batch counts when no item-total count exists.
    """
    active_statuses = ("Counting", "Count Completed", "Under Review", "Approved")
    for raw in rows:
        row = frappe._dict(raw if isinstance(raw, dict) else raw.as_dict())
        warehouse = clean(row.get("warehouse"))
        item_code = clean(row.get("item_code"))
        batch_no = clean(row.get("batch_no"))
        if not warehouse or not item_code:
            continue
        placeholders = ",".join(["%s"] * len(active_statuses))
        existing = frappe.db.sql(
            f"""
            SELECT ci.parent, ci.batch_no, c.status
            FROM `tabPharmacy Inventory Count Item` ci
            INNER JOIN `tabPharmacy Inventory Count` c ON c.name=ci.parent
            WHERE ci.parenttype='Pharmacy Inventory Count'
              AND ci.parentfield='items'
              AND ci.warehouse=%s
              AND ci.item_code=%s
              AND c.status IN ({placeholders})
              AND ci.parent<>%s
            LIMIT 20
            """,
            tuple([warehouse, item_code] + list(active_statuses) + [count_name or ""]),
            as_dict=True,
        )
        for other in existing:
            other_batch = clean(other.batch_no)
            # Item-total lines overlap every batch. Two explicit different Batch
            # counts do not overlap each other.
            if not batch_no or not other_batch or batch_no == other_batch:
                frappe.throw(
                    _(
                        "Item {0} in Warehouse {1} is already covered by active Inventory Count {2} ({3})."
                    ).format(
                        frappe.bold(item_code),
                        frappe.bold(warehouse),
                        frappe.bold(other.parent),
                        other.status,
                    )
                )

def current_expected_qty(row) -> float:
    if clean(row.count_basis) == "Location":
        return flt(get_allocated_qty(row.item_code, row.warehouse, row.batch_no or None, row.location), 6)
    if row.batch_no:
        return flt(_batch_qty(row.batch_no, row.warehouse, row.item_code), 6)
    return flt(get_official_warehouse_qty(row.item_code, row.warehouse), 6)


def _variance_percent(expected: float, actual: float, variance: float) -> float:
    expected = abs(flt(expected, 6))
    if expected > EPSILON:
        return flt(abs(variance) / expected * 100, 6)
    return 100.0 if abs(actual) > EPSILON else 0.0


def evaluate_high_variance(row) -> bool:
    settings = get_settings()
    value_threshold = flt(settings.get("high_variance_value_threshold") or 0)
    percent_threshold = flt(settings.get("high_variance_percentage_threshold") or 0)
    variance_value = abs(flt(row.variance_value, 6))
    percent = _variance_percent(row.expected_qty_at_count, row.actual_qty, row.variance_qty)
    return bool(
        (value_threshold > EPSILON and variance_value + EPSILON >= value_threshold)
        or (percent_threshold > EPSILON and percent + EPSILON >= percent_threshold)
    )


def refresh_line_variance(row, *, capture_now: bool = False) -> None:
    if capture_now:
        row.expected_qty_at_count = current_expected_qty(row)
        row.counted_at = now_datetime()
        row.counted_by = frappe.session.user
        row.valuation_rate_snapshot = _bin_valuation_rate(row.item_code, row.warehouse)
    expected = flt(row.expected_qty_at_count, 6)
    actual = flt(row.actual_qty, 6)
    row.variance_qty = flt(actual - expected, 6)
    row.variance_value = flt(row.variance_qty * flt(row.valuation_rate_snapshot, 6), 6)
    row.high_variance = cint(evaluate_high_variance(row))


def _old_item_values(count_name: str) -> dict[str, frappe._dict]:
    if not count_name or not frappe.db.exists(COUNT_DOCTYPE, count_name):
        return {}
    rows = frappe.get_all(
        ITEM_DOCTYPE,
        filters={"parent": count_name, "parenttype": COUNT_DOCTYPE, "parentfield": "items"},
        fields=[
            "name", "actual_qty", "count_entered", "resolution_status", "found_location",
            "found_elsewhere_qty", "posting_batch_no", "reason_code", "reason_note", "count_round",
        ],
        limit_page_length=10000,
    )
    return {row.name: frappe._dict(row) for row in rows}


def sync_counted_rows(doc) -> None:
    old = _old_item_values(doc.name)
    settings = get_settings()
    max_recounts = max(0, cint(settings.get("maximum_recounts") or 0))

    for row in doc.items or []:
        if clean(row.resolution_status) == "Authorized Exclusion":
            continue
        if not cint(row.count_entered):
            continue

        if clean(row.entry_mode) == "Box / Unit":
            pack_size = flt(row.pack_size or 1, 6) or 1
            boxes = flt(row.actual_boxes, 6)
            loose_units = flt(row.actual_loose_units, 6)
            if boxes < -EPSILON or loose_units < -EPSILON:
                frappe.throw(_("Box / Unit quantities cannot be negative on row {0}.").format(row.idx))
            if abs(boxes - round(boxes)) > 0.000001 or abs(loose_units - round(loose_units)) > 0.000001:
                frappe.throw(_("Boxes and loose units must be whole numbers on row {0}.").format(row.idx))
            if cint(row.box_only) and loose_units > EPSILON:
                frappe.throw(_("Item {0} is Box Only; loose units are not allowed.").format(frappe.bold(row.item_code)))
            row.actual_qty = flt(round(boxes) + (round(loose_units) / pack_size), 6)

        if flt(row.actual_qty, 6) < -EPSILON:
            frappe.throw(_("Actual Qty cannot be negative on row {0}.").format(row.idx))

        previous = old.get(row.name)
        changed = previous is None
        if previous:
            changed = any(
                [
                    flt(previous.actual_qty, 6) != flt(row.actual_qty, 6),
                    clean(previous.resolution_status) != clean(row.resolution_status),
                    clean(previous.found_location) != clean(row.found_location),
                    flt(previous.found_elsewhere_qty, 6) != flt(row.found_elsewhere_qty, 6),
                    clean(previous.posting_batch_no) != clean(row.posting_batch_no),
                    cint(previous.count_round) != cint(row.count_round),
                ]
            )
        if changed or not row.counted_at:
            refresh_line_variance(row, capture_now=True)

        if flt(row.actual_qty, 6) <= EPSILON and clean(row.resolution_status) in {"", "Pending", "Counted"}:
            row.resolution_status = "Confirmed Zero"
        elif flt(row.actual_qty, 6) > EPSILON and clean(row.resolution_status) in {"", "Pending", "Confirmed Zero"}:
            row.resolution_status = "Counted"

        if clean(row.resolution_status) == "Found Elsewhere":
            if clean(row.count_basis) != "Location":
                frappe.throw(_("Found Elsewhere is only valid for Location-based Count rows."))
            if not row.found_location:
                frappe.throw(_("Found Location is required on row {0}.").format(row.idx))
            validate_location(row.found_location, row.warehouse)
            if row.found_location == row.location:
                frappe.throw(_("Found Location must differ from the counted Location on row {0}.").format(row.idx))
            shortage = max(0.0, -flt(row.variance_qty, 6))
            if flt(row.found_elsewhere_qty, 6) <= EPSILON or flt(row.found_elsewhere_qty, 6) > shortage + EPSILON:
                frappe.throw(
                    _("Found Elsewhere Qty on row {0} must be greater than zero and cannot exceed the location shortage.").format(row.idx)
                )

        if max_recounts and cint(row.count_round) > max_recounts + 1:
            row.high_variance = 1


def update_totals(doc) -> None:
    rows = [row for row in (doc.items or []) if cint(row.count_entered)]
    doc.total_snapshot_qty = flt(sum(flt(row.snapshot_qty, 6) for row in rows), 6)
    doc.total_actual_qty = flt(sum(flt(row.actual_qty, 6) for row in rows), 6)
    doc.net_variance_qty = flt(sum(flt(row.variance_qty, 6) for row in rows), 6)
    doc.absolute_variance_qty = flt(sum(abs(flt(row.variance_qty, 6)) for row in rows), 6)
    doc.total_variance_value = flt(sum(abs(flt(row.variance_value, 6)) for row in rows), 6)
    doc.high_variance = cint(any(cint(row.high_variance) for row in rows))


def auto_resolve_movements(doc) -> list[str]:
    resolved = []
    for row in doc.items or []:
        if cint(row.count_entered):
            continue
        current = current_expected_qty(row)
        if abs(current) <= EPSILON and abs(flt(row.snapshot_qty, 6)) > EPSILON:
            row.count_entered = 1
            row.actual_qty = 0
            row.expected_qty_at_count = 0
            row.variance_qty = 0
            row.variance_value = 0
            row.counted_at = now_datetime()
            row.counted_by = frappe.session.user
            row.resolution_status = "Resolved by Movement"
            row.high_variance = 0
            resolved.append(row.name)
    return resolved


def unresolved_rows(doc) -> list[dict[str, Any]]:
    missing = []
    for row in doc.items or []:
        if cint(row.count_entered) and clean(row.resolution_status) in RESOLVED_STATES:
            continue
        missing.append(
            {
                "row_name": row.name,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "warehouse": row.warehouse,
                "location": row.location,
                "snapshot_qty": flt(row.snapshot_qty, 6),
            }
        )
    return missing


def log_event(count_name: str, event_type: str, *, row=None, details: str = "", payload: Any = None, count_round: int | None = None) -> str:
    doc = frappe.get_doc(
        {
            "doctype": EVENT_DOCTYPE,
            "inventory_count": count_name,
            "event_type": event_type,
            "event_datetime": now_datetime(),
            "user": frappe.session.user,
            "count_round": count_round or (cint(getattr(row, "count_round", 0)) if row else None),
            "item_code": getattr(row, "item_code", None) if row else None,
            "row_reference": getattr(row, "name", None) if row else None,
            "details": details,
            "payload_json": json_dumps(payload) if payload is not None else None,
        }
    )
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name


def _full_shortage_requires_recount(row) -> bool:
    settings = get_settings()
    if not cint(settings.get("require_recount_for_full_shortage")):
        return False
    expected = flt(row.expected_qty_at_count, 6)
    actual = flt(row.actual_qty, 6)
    return expected > EPSILON and actual <= EPSILON and cint(row.count_round) < 2


def _latest_batch_breakdown_payload(count_name: str, row) -> dict[str, Any]:
    events = frappe.get_all(
        EVENT_DOCTYPE,
        filters={
            "inventory_count": count_name,
            "row_reference": row.name,
            "count_round": cint(row.count_round or 1),
            "event_type": ["in", ["Batch Breakdown Saved", "Batch Breakdown Cleared"]],
        },
        fields=["event_type", "payload_json", "event_datetime", "creation"],
        order_by="event_datetime desc, creation desc",
        limit_page_length=1,
    )
    if not events or events[0].event_type == "Batch Breakdown Cleared":
        return {
            "segments": [],
            "price_groups": [],
            "location_batch_snapshot_captured": 0,
            "location_batch_snapshot": [],
            "location_batch_snapshot_fingerprint": "",
        }
    try:
        payload = json.loads(events[0].payload_json or "{}")
    except Exception:
        payload = {}
    return {
        "segments": payload.get("segments") or [],
        "price_groups": payload.get("price_groups") or [],
        "location_batch_snapshot_captured": cint(payload.get("location_batch_snapshot_captured")),
        "location_batch_snapshot": payload.get("location_batch_snapshot") or [],
        "location_batch_snapshot_fingerprint": clean(payload.get("location_batch_snapshot_fingerprint")),
    }


def _latest_batch_breakdown_for_row(count_name: str, row) -> list[dict[str, Any]]:
    return _latest_batch_breakdown_payload(count_name, row).get("segments") or []


def _batch_breakdown_fingerprint(segments: list[dict[str, Any]]) -> str:
    normalized = []
    for raw in segments or []:
        row = frappe._dict(raw or {})
        normalized.append(
            {
                "batch_no": clean(row.get("batch_no")),
                "expiry_date": clean(row.get("expiry_date")),
                "customer_price": flt(row.get("customer_price") or row.get("observed_price"), 6),
                "qty": flt(row.get("qty"), 6),
                "source_kind": clean(row.get("source_kind")),
                "expiry_mismatch": cint(row.get("expiry_mismatch")),
                "price_mismatch": cint(row.get("price_mismatch")),
                "auto_batch_requested": cint(row.get("auto_batch_requested")),
            }
        )
    normalized.sort(key=lambda r: (r["customer_price"], r["batch_no"], r["expiry_date"], r["qty"]))
    return hashlib.sha256(json_dumps(normalized).encode("utf-8")).hexdigest()


def get_batch_system_snapshot(item_code: str, warehouse: str) -> list[dict[str, Any]]:
    """Return the live official Batch composition used to arm an execution plan.

    The snapshot intentionally includes expired/disabled Batch masters when they still
    carry positive official stock. Retail price is metadata only; Stock Ledger remains
    the valuation source.

    R1.13: retail-price metadata follows the same effective-price contract used by
    Pharmacy POS and Inventory Count: Batch printed/POSA price first, then Item
    Customer Price fallback when the Batch itself has no retail price.
    """
    from pharma_erp.pharma_erp.page.pharmacy_pos.api import (
        _batch_price_context,
        _item_customer_price,
    )

    fallback_price = flt(_item_customer_price(item_code), 6)
    meta = frappe.get_meta("Batch")
    fields = ["name", "expiry_date", "disabled"]
    for fieldname in ("custom_printed_retail_price", "posa_batch_price"):
        if meta.has_field(fieldname):
            fields.append(fieldname)
    rows = frappe.get_all(
        "Batch",
        filters={"item": item_code},
        fields=fields,
        order_by="expiry_date asc, name asc",
        limit_page_length=5000,
    )
    result = []
    for raw in rows:
        row = frappe._dict(raw)
        qty = flt(_batch_qty(row.name, warehouse, item_code), 6)
        if qty <= EPSILON:
            continue
        price_context = _batch_price_context(
            row.name,
            item_code,
            fallback_price,
        )
        price = flt(price_context.get("customer_price") or 0, 6)
        expiry = clean(row.get("expiry_date"))
        result.append({
            "batch_no": row.name,
            "expiry_date": expiry,
            "customer_price": price,
            "qty": qty,
            "disabled": cint(row.get("disabled")),
        })
    result.sort(key=lambda r: (r["customer_price"], r["expiry_date"] or "9999-12-31", r["batch_no"]))
    return result


def batch_system_snapshot_fingerprint(snapshot: list[dict[str, Any]]) -> str:
    normalized = []
    for raw in snapshot or []:
        row = frappe._dict(raw or {})
        normalized.append({
            "batch_no": clean(row.get("batch_no")),
            "expiry_date": clean(row.get("expiry_date")),
            "customer_price": flt(row.get("customer_price"), 6),
            "qty": flt(row.get("qty"), 6),
            "disabled": cint(row.get("disabled")),
        })
    normalized.sort(key=lambda r: (r["batch_no"], r["expiry_date"], r["customer_price"], r["qty"]))
    return hashlib.sha256(json_dumps(normalized).encode("utf-8")).hexdigest()


def _latest_batch_reconciliation_execution_for_row(count_name: str, row) -> dict[str, Any]:
    events = frappe.get_all(
        EVENT_DOCTYPE,
        filters={
            "inventory_count": count_name,
            "row_reference": row.name,
            "count_round": cint(row.count_round or 1),
            "event_type": "Batch Reconciliation Executed",
        },
        fields=["payload_json", "event_datetime", "creation"],
        order_by="event_datetime desc, creation desc",
        limit_page_length=1,
    )
    if not events:
        return {}
    try:
        return json.loads(events[0].payload_json or "{}") or {}
    except Exception:
        return {}


def _latest_batch_reconciliation_plan_for_row(count_name: str, row) -> dict[str, Any]:
    events = frappe.get_all(
        EVENT_DOCTYPE,
        filters={
            "inventory_count": count_name,
            "row_reference": row.name,
            "count_round": cint(row.count_round or 1),
            "event_type": "Batch Reconciliation Plan Saved",
        },
        fields=["payload_json", "event_datetime", "creation"],
        order_by="event_datetime desc, creation desc",
        limit_page_length=1,
    )
    if not events:
        return {}
    try:
        return json.loads(events[0].payload_json or "{}") or {}
    except Exception:
        return {}


def batch_reconciliation_row_status(doc, row) -> dict[str, Any]:
    # R1.12: Location counts reconcile operational Location balances, not the
    # Warehouse Batch composition.  Physical Batch evidence is handled by the
    # Location Batch matrix during approval/posting instead.
    if clean(row.count_basis) == "Location":
        return {
            "row_name": row.name,
            "item_code": row.item_code,
            "required": 0,
            "planned": 0,
            "plan_stale": 0,
            "execution_ready": 0,
            "execution_stale": 0,
            "executed": 0,
            "auto_batch_requests": 0,
            "expiry_mismatches": 0,
            "price_mismatches": 0,
            "composition_differences": 0,
            "breakdown_fingerprint": "",
            "system_snapshot_fingerprint": "",
        }
    if not cint(row.count_entered) or not cint(row.has_batch_no) or clean(row.batch_no):
        return {
            "row_name": row.name,
            "item_code": row.item_code,
            "required": 0,
            "planned": 0,
            "plan_stale": 0,
            "execution_ready": 0,
            "execution_stale": 0,
            "executed": 0,
            "auto_batch_requests": 0,
            "expiry_mismatches": 0,
            "price_mismatches": 0,
            "composition_differences": 0,
            "breakdown_fingerprint": "",
            "system_snapshot_fingerprint": "",
        }

    payload = _latest_batch_breakdown_payload(doc.name, row)
    segments = payload.get("segments") or []
    if not segments:
        return {
            "row_name": row.name,
            "item_code": row.item_code,
            "required": 0,
            "planned": 0,
            "plan_stale": 0,
            "execution_ready": 0,
            "execution_stale": 0,
            "executed": 0,
            "auto_batch_requests": 0,
            "expiry_mismatches": 0,
            "price_mismatches": 0,
            "composition_differences": 0,
            "breakdown_fingerprint": "",
            "system_snapshot_fingerprint": "",
        }

    observed = defaultdict(float)
    auto_batch_requests = 0
    expiry_mismatches = 0
    price_mismatches = 0
    metadata_issue = False
    for raw in segments:
        segment = frappe._dict(raw or {})
        batch_no = clean(segment.get("batch_no"))
        qty = flt(segment.get("qty"), 6)
        auto_batch_requests += cint(segment.get("auto_batch_requested") or not batch_no)
        expiry_mismatches += cint(segment.get("expiry_mismatch"))
        price_mismatches += cint(segment.get("price_mismatch"))
        if (
            not batch_no
            or clean(segment.get("source_kind")) != "Existing Batch"
            or cint(segment.get("expiry_mismatch"))
            or cint(segment.get("price_mismatch"))
        ):
            metadata_issue = True
        if batch_no and clean(segment.get("source_kind")) == "Existing Batch":
            observed[batch_no] += qty

    system_snapshot = get_batch_system_snapshot(row.item_code, row.warehouse)
    system = {clean(source.get("batch_no")): flt(source.get("qty"), 6) for source in system_snapshot}
    composition_differences = 0
    for key in set(system) | set(observed):
        if abs(flt(system.get(key), 6) - flt(observed.get(key), 6)) > 0.000001:
            composition_differences += 1

    required = cint(bool(metadata_issue or composition_differences))
    fingerprint = _batch_breakdown_fingerprint(segments)
    system_fingerprint = batch_system_snapshot_fingerprint(system_snapshot)
    plan = _latest_batch_reconciliation_plan_for_row(doc.name, row)
    planned = cint(bool(required and plan and clean(plan.get("breakdown_fingerprint")) == fingerprint))
    plan_stale = cint(bool(plan and clean(plan.get("breakdown_fingerprint")) != fingerprint))
    r2_plan = bool(clean(plan.get("version")) == "R1.10-R2" and cint(plan.get("execution_ready")))
    plan_system_fingerprint = clean(plan.get("system_snapshot_fingerprint"))
    execution_stale = cint(bool(r2_plan and plan_system_fingerprint and plan_system_fingerprint != system_fingerprint))
    execution_ready = cint(bool(planned and r2_plan and not execution_stale and plan_system_fingerprint == system_fingerprint))
    executed_payload = _latest_batch_reconciliation_execution_for_row(doc.name, row)
    executed = cint(bool(executed_payload and clean(executed_payload.get("breakdown_fingerprint")) == fingerprint))
    if executed and clean(doc.status) == "Posted":
        planned = 1
        plan_stale = 0
        execution_stale = 0
        execution_ready = 1

    return {
        "row_name": row.name,
        "item_code": row.item_code,
        "item_name": row.item_name,
        "warehouse": row.warehouse,
        "required": required,
        "planned": planned,
        "plan_stale": plan_stale,
        "execution_ready": execution_ready,
        "execution_stale": execution_stale,
        "executed": executed,
        "auto_batch_requests": auto_batch_requests,
        "expiry_mismatches": expiry_mismatches,
        "price_mismatches": price_mismatches,
        "composition_differences": composition_differences,
        "physical_lots": len(segments),
        "system_batches": len(system),
        "breakdown_fingerprint": fingerprint,
        "system_snapshot_fingerprint": system_fingerprint,
    }


def get_batch_reconciliation_status(doc) -> dict[str, Any]:
    rows = []
    for row in doc.items or []:
        status = batch_reconciliation_row_status(doc, row)
        if status.get("required") or status.get("plan_stale") or status.get("execution_stale") or status.get("executed"):
            rows.append(status)
    required_rows = [row for row in rows if cint(row.get("required"))]
    return {
        "required": cint(bool(required_rows)),
        "planned": cint(bool(required_rows) and all(cint(row.get("planned")) for row in required_rows)),
        "rows_required": sum(cint(row.get("required")) for row in rows),
        "rows_planned": sum(cint(row.get("planned")) for row in rows),
        "auto_batch_requests": sum(cint(row.get("auto_batch_requests")) for row in rows),
        "expiry_mismatches": sum(cint(row.get("expiry_mismatches")) for row in rows),
        "price_mismatches": sum(cint(row.get("price_mismatches")) for row in rows),
        "composition_differences": sum(cint(row.get("composition_differences")) for row in rows),
        "plan_stale": cint(any(cint(row.get("plan_stale")) for row in rows)),
        "execution_stale": cint(any(cint(row.get("execution_stale")) for row in rows)),
        "execution_ready": cint(bool(required_rows) and all(cint(row.get("execution_ready")) for row in required_rows)),
        "executed": cint(bool(required_rows) and all(cint(row.get("executed")) for row in required_rows)),
        "rows": rows,
    }


def validate_batch_reconciliation_plan(doc) -> None:
    status = get_batch_reconciliation_status(doc)
    if status.get("required") and not status.get("planned"):
        frappe.throw(
            _(
                "Batch/Expiry/Price composition reconciliation is required before approval. "
                "Open Review Batch Reconciliation and save a reviewer plan first."
            )
        )
    if status.get("plan_stale"):
        frappe.throw(_("The saved Batch Reconciliation plan is stale. Review and save it again before approval."))


def validate_batch_breakdown_posting(doc) -> None:
    """Require an R1.10 R2 execution-armed plan and reject any stock drift."""
    status = get_batch_reconciliation_status(doc)
    if not status.get("required"):
        return
    if not status.get("planned"):
        frappe.throw(
            _(
                "Batch/Expiry/Price composition reconciliation is required before posting. "
                "Save the controlled reconciliation plan first."
            )
        )
    if status.get("execution_stale"):
        frappe.throw(
            _(
                "Batch stock or metadata changed after the R1.10 R2 execution plan was armed. "
                "Do not overwrite live movements; request a recount for the affected Item."
            )
        )
    if not status.get("execution_ready"):
        frappe.throw(
            _(
                "The reviewer plan is saved but is not armed for R1.10 R2 execution. "
                "Open Review Batch Plan and save it again after verifying the current System Batch snapshot."
            )
        )


def _location_batch_matrix(doc, row) -> dict[str, Any]:
    """Build the exact operational Batch delta matrix for a Location Count row.

    The physical Batch breakdown is compared with the Batch composition captured
    at count-entry time for this Location only.  Warehouse Batch composition is
    never rewritten by this path.
    """
    payload = _latest_batch_breakdown_payload(doc.name, row)
    if not cint(payload.get("location_batch_snapshot_captured")):
        frappe.throw(
            _(
                "Location Batch snapshot is missing for Item {0}. Request a recount for this Item so the Batch/Location baseline can be captured safely."
            ).format(frappe.bold(row.item_code))
        )

    segments = payload.get("segments") or []
    snapshot = payload.get("location_batch_snapshot") or []
    expected_fingerprint = clean(payload.get("location_batch_snapshot_fingerprint"))
    if expected_fingerprint and location_batch_snapshot_fingerprint(snapshot) != expected_fingerprint:
        frappe.throw(_("Stored Location Batch snapshot is invalid for Item {0}; request a recount.").format(frappe.bold(row.item_code)))

    snapshot_by_batch = defaultdict(float)
    for raw in snapshot:
        source = frappe._dict(raw or {})
        batch_no = clean(source.get("batch_no"))
        qty = flt(source.get("qty"), 6)
        if abs(qty) <= EPSILON:
            continue
        if not batch_no:
            frappe.throw(_("Location Batch snapshot contains stock without a Batch for Item {0}; request a recount after repairing Location stock.").format(frappe.bold(row.item_code)))
        snapshot_by_batch[batch_no] = flt(snapshot_by_batch[batch_no] + qty, 6)

    snapshot_total = flt(sum(snapshot_by_batch.values()), 6)
    if abs(snapshot_total - flt(row.expected_qty_at_count, 6)) > 0.000001:
        frappe.throw(
            _(
                "Location Batch snapshot for Item {0} does not match the counted expected quantity. Request a recount before approval."
            ).format(frappe.bold(row.item_code))
        )

    target_by_batch = defaultdict(float)
    for raw in segments:
        segment = frappe._dict(raw or {})
        qty = flt(segment.get("qty"), 6)
        if qty <= EPSILON:
            continue
        batch_no = clean(segment.get("batch_no"))
        if (
            not batch_no
            or clean(segment.get("source_kind")) != "Existing Batch"
            or cint(segment.get("auto_batch_requested"))
        ):
            frappe.throw(
                _(
                    "Location Count cannot create or infer a new Batch for Item {0}. Run a Warehouse/Batch Count to create or reclassify the physical Batch first."
                ).format(frappe.bold(row.item_code))
            )
        if cint(segment.get("expiry_mismatch")) or cint(segment.get("price_mismatch")):
            frappe.throw(
                _(
                    "Location Count cannot change Batch Expiry/Price metadata for Item {0} / Batch {1}. Run a Warehouse/Batch Count to reconcile Batch metadata first."
                ).format(frappe.bold(row.item_code), frappe.bold(batch_no))
            )
        validate_posting_batch(row.item_code, batch_no)
        target_by_batch[batch_no] = flt(target_by_batch[batch_no] + qty, 6)

    physical_total = flt(sum(target_by_batch.values()), 6)
    if abs(physical_total - flt(row.actual_qty, 6)) > 0.000001:
        frappe.throw(_("Physical Batch total does not equal Actual Qty for Location Item {0}; request a recount.").format(frappe.bold(row.item_code)))

    deltas = []
    for batch_no in sorted(set(snapshot_by_batch) | set(target_by_batch)):
        before = flt(snapshot_by_batch.get(batch_no), 6)
        target = flt(target_by_batch.get(batch_no), 6)
        delta = flt(target - before, 6)
        if abs(delta) <= EPSILON:
            continue
        deltas.append({
            "batch_no": batch_no,
            "snapshot_qty": before,
            "target_qty": target,
            "delta": delta,
        })

    return {
        "snapshot": [{"batch_no": key, "qty": flt(value, 6)} for key, value in sorted(snapshot_by_batch.items())],
        "targets": [{"batch_no": key, "qty": flt(value, 6)} for key, value in sorted(target_by_batch.items())],
        "deltas": deltas,
        "snapshot_total": snapshot_total,
        "physical_total": physical_total,
    }


def validate_for_approval(doc) -> None:
    missing = unresolved_rows(doc)
    if missing:
        frappe.throw(_("All expected items must be resolved before approval."))

    validate_batch_reconciliation_plan(doc)

    for row in doc.items or []:
        if not cint(row.count_entered):
            continue
        variance = flt(row.variance_qty, 6)
        if abs(variance) > EPSILON and not clean(row.reason_code):
            frappe.throw(_("Reason Code is required for variance on row {0} ({1}).").format(row.idx, frappe.bold(row.item_code)))
        if clean(row.reason_code) == "Other" and not clean(row.reason_note):
            frappe.throw(_("Reason Note is required when Reason Code is Other on row {0}.").format(row.idx))
        if _full_shortage_requires_recount(row):
            frappe.throw(
                _("Full shortage for Item {0} requires a second count before approval.").format(frappe.bold(row.item_code))
            )
        item = _item_meta(row.item_code)
        if cint(item.has_batch_no) and clean(row.count_basis) == "Location":
            _location_batch_matrix(doc, row)
        elif cint(item.has_batch_no) and variance > EPSILON:
            # R1.13.2: Warehouse Batch rows whose physical Batch composition is
            # handled by the controlled reconciliation plan must not fall through
            # to the legacy single-posting_batch_no guard. The plan owns the exact
            # per-Batch target matrix and is later excluded from the legacy target
            # builder through handled_rows.
            reconciliation_status = batch_reconciliation_row_status(doc, row)
            if not cint(reconciliation_status.get("required")):
                validate_posting_batch(row.item_code, row.posting_batch_no)


def _lock_bins(rows) -> None:
    keys = sorted({(row.item_code, row.warehouse) for row in rows if clean(row.count_basis) == "Warehouse"})
    for item_code, warehouse in keys:
        frappe.db.sql(
            "SELECT name FROM `tabBin` WHERE item_code=%s AND warehouse=%s FOR UPDATE",
            (item_code, warehouse),
        )


def _current_batch_valuation(item_code: str, warehouse: str) -> float:
    return _bin_valuation_rate(item_code, warehouse)


def _append_reconciliation_row(reco, *, item_code: str, warehouse: str, target_qty: float, batch_no: str | None = None):
    target_qty = flt(target_qty, 6)
    if target_qty < -EPSILON:
        frappe.throw(_("Inventory Count would create negative stock for Item {0}.").format(frappe.bold(item_code)))
    rate = _current_batch_valuation(item_code, warehouse)
    if target_qty > EPSILON and rate <= EPSILON:
        frappe.throw(
            _("Valuation Rate is missing for Item {0} in Warehouse {1}; cannot post positive stock adjustment safely.").format(
                frappe.bold(item_code), frappe.bold(warehouse)
            )
        )
    child = reco.append(
        "items",
        {
            "item_code": item_code,
            "warehouse": warehouse,
            "qty": max(0.0, target_qty),
            "valuation_rate": rate or None,
        },
    )
    if batch_no:
        meta = frappe.get_meta("Stock Reconciliation Item")
        if not meta.has_field("batch_no"):
            frappe.throw(_("This ERPNext Stock Reconciliation schema does not expose Batch No."))
        child.batch_no = batch_no
        if meta.has_field("use_serial_batch_fields"):
            child.use_serial_batch_fields = 1
    return child


def build_reconciliation_targets(doc, skip_row_names: Iterable[str] | None = None) -> list[dict[str, Any]]:
    skip = set(skip_row_names or [])
    targets: list[dict[str, Any]] = []
    for row in doc.items or []:
        if row.name in skip:
            continue
        if not cint(row.count_entered) or clean(row.count_basis) != "Warehouse":
            continue
        variance = flt(row.variance_qty, 6)
        if abs(variance) <= EPSILON:
            continue
        item = _item_meta(row.item_code)
        if row.batch_no:
            current = _batch_qty(row.batch_no, row.warehouse, row.item_code)
            target = flt(current + variance, 6)
            if target < -EPSILON:
                frappe.throw(_("Stock changed after count; Batch {0} cannot absorb the approved shortage. Recount is required.").format(frappe.bold(row.batch_no)))
            targets.append(
                {
                    "item_code": row.item_code,
                    "warehouse": row.warehouse,
                    "batch_no": row.batch_no,
                    "target_qty": max(0.0, target),
                    "variance": variance,
                    "row_name": row.name,
                }
            )
            continue

        current = flt(get_official_warehouse_qty(row.item_code, row.warehouse), 6)
        target_total = flt(current + variance, 6)
        if target_total < -EPSILON:
            frappe.throw(
                _("Stock changed after count; Item {0} now has {1} and cannot absorb approved variance {2}. Recount is required.").format(
                    frappe.bold(row.item_code), current, variance
                )
            )

        if not cint(item.has_batch_no):
            targets.append(
                {
                    "item_code": row.item_code,
                    "warehouse": row.warehouse,
                    "batch_no": None,
                    "target_qty": max(0.0, target_total),
                    "variance": variance,
                    "row_name": row.name,
                }
            )
            continue

        if variance < -EPSILON:
            for allocation in allocate_batch_shortage(row.item_code, row.warehouse, abs(variance)):
                current_batch = _batch_qty(allocation.batch_no, row.warehouse, row.item_code)
                target_batch = flt(current_batch - flt(allocation.qty, 6), 6)
                if target_batch < -EPSILON:
                    frappe.throw(_("Batch stock changed while posting; recount is required."))
                targets.append(
                    {
                        "item_code": row.item_code,
                        "warehouse": row.warehouse,
                        "batch_no": allocation.batch_no,
                        "target_qty": max(0.0, target_batch),
                        "variance": -flt(allocation.qty, 6),
                        "row_name": row.name,
                    }
                )
        else:
            validate_posting_batch(row.item_code, row.posting_batch_no)
            current_batch = _batch_qty(row.posting_batch_no, row.warehouse, row.item_code)
            targets.append(
                {
                    "item_code": row.item_code,
                    "warehouse": row.warehouse,
                    "batch_no": row.posting_batch_no,
                    "target_qty": flt(current_batch + variance, 6),
                    "variance": variance,
                    "row_name": row.name,
                }
            )
    return targets


def create_stock_reconciliation(doc, targets: list[dict[str, Any]]) -> str | None:
    if not targets:
        return None
    if doc.stock_reconciliation:
        existing = frappe.db.get_value("Stock Reconciliation", doc.stock_reconciliation, "docstatus")
        if existing is not None:
            return doc.stock_reconciliation

    reco = frappe.new_doc("Stock Reconciliation")
    reco.company = doc.company
    reco.purpose = "Stock Reconciliation"
    reco.set_posting_time = 1
    reco.posting_date = nowdate()
    reco.posting_time = nowtime()
    for target in targets:
        _append_reconciliation_row(
            reco,
            item_code=target["item_code"],
            warehouse=target["warehouse"],
            target_qty=target["target_qty"],
            batch_no=target.get("batch_no"),
        )
    reco.flags.ignore_permissions = True
    reco.insert(ignore_permissions=True)
    reco.submit()
    return reco.name


def _batch_set_if_field(batch, fieldname: str, value: Any) -> None:
    if batch.meta.has_field(fieldname):
        batch.set(fieldname, value)


def _batch_customer_price(batch_no: str) -> float:
    meta = frappe.get_meta("Batch")
    fields = [fieldname for fieldname in ("custom_printed_retail_price", "posa_batch_price") if meta.has_field(fieldname)]
    if not fields:
        return 0.0
    values = frappe.db.get_value("Batch", batch_no, fields, as_dict=True) or frappe._dict()
    return flt(values.get("custom_printed_retail_price") or values.get("posa_batch_price") or 0, 6)


def _create_inventory_count_batch(doc, row, segment, *, batch_no: str | None = None, auto_generated: bool = False) -> str:
    segment = frappe._dict(segment or {})
    expiry = clean(segment.get("expiry_date"))
    price = flt(segment.get("customer_price") or segment.get("observed_price"), 6)
    if not expiry:
        frappe.throw(_("Expiry Date is required before creating a Batch for Item {0}.").format(frappe.bold(row.item_code)))
    if price <= EPSILON:
        frappe.throw(_("Observed retail price is required before creating a Batch for Item {0}.").format(frappe.bold(row.item_code)))

    if auto_generated:
        from pharma_erp.purchase_management import _generate_batch_number, get_purchase_settings

        settings = get_purchase_settings()
        batch_no = _generate_batch_number(row.item_code, getdate(expiry), settings.get("auto_batch_prefix") or "AUTO")
    else:
        batch_no = clean(batch_no or segment.get("batch_no"))
        if not batch_no:
            frappe.throw(_("Physical Batch No is required for Create Observed Batch."))

    existing = frappe.db.get_value("Batch", batch_no, ["name", "item", "expiry_date"], as_dict=True)
    if existing:
        if clean(existing.item) != clean(row.item_code):
            frappe.throw(_("Batch {0} belongs to another Item.").format(frappe.bold(batch_no)))
        if existing.expiry_date and getdate(existing.expiry_date) != getdate(expiry):
            frappe.throw(_("Batch {0} now has a different Expiry Date; execution plan is stale.").format(frappe.bold(batch_no)))
        current_price = _batch_customer_price(batch_no)
        if current_price > EPSILON and abs(current_price - price) > 0.000001:
            frappe.throw(_("Batch {0} now has a different retail price; execution plan is stale.").format(frappe.bold(batch_no)))
        return batch_no

    batch = frappe.new_doc("Batch")
    batch.batch_id = batch_no
    batch.item = row.item_code
    batch.expiry_date = getdate(expiry)
    _batch_set_if_field(batch, "custom_printed_retail_price", price)
    _batch_set_if_field(batch, "posa_batch_price", price)
    _batch_set_if_field(batch, "custom_price_effective_date", nowdate())
    _batch_set_if_field(batch, "custom_price_updated_from_invoice", 0)
    _batch_set_if_field(batch, "custom_auto_generated", cint(auto_generated))
    _batch_set_if_field(batch, "custom_auto_generation_reason", _("Inventory Count {0} Batch reconciliation").format(doc.name))
    batch.flags.ignore_permissions = True
    batch.insert(ignore_permissions=True)
    return batch.name


def batch_reconciliation_segment_action(segment):
    """Return the canonical controlled action for one physical Batch segment.

    R1.13.1: the pre-arm Final Target Matrix must use the same action semantics
    as the reviewer plan. This prevents an unarmed preview from incorrectly
    rendering Existing Batches as AUTO-on-post targets.
    """
    segment = frappe._dict(segment or {})
    batch_no = clean(segment.get("batch_no"))

    if cint(segment.get("price_mismatch")):
        return "Reclassify to AUTO Batch", ["Reclassify to AUTO Batch"]

    if batch_no and frappe.db.exists("Batch", batch_no):
        if cint(segment.get("expiry_mismatch")):
            return "Correct Existing Expiry", [
                "Correct Existing Expiry",
                "Reclassify to AUTO Batch",
            ]
        return "Use Existing Batch", ["Use Existing Batch"]

    if batch_no:
        return "Create Observed Batch", ["Create Observed Batch"]

    return "Create AUTO Batch", ["Create AUTO Batch"]


def build_batch_reconciliation_execution_preview(doc, row) -> dict[str, Any]:
    status = batch_reconciliation_row_status(doc, row)
    breakdown = _latest_batch_breakdown_payload(doc.name, row)
    segments = breakdown.get("segments") or []
    plan = _latest_batch_reconciliation_plan_for_row(doc.name, row)
    decisions = {cint(raw.get("segment_index")): clean(raw.get("action")) for raw in (plan.get("decisions") or [])}
    system_snapshot = get_batch_system_snapshot(row.item_code, row.warehouse)
    current_total = flt(sum(flt(source.get("qty"), 6) for source in system_snapshot), 6)
    expected = flt(row.expected_qty_at_count, 6)

    targets = {clean(source.get("batch_no")): {"batch_no": clean(source.get("batch_no")), "current_qty": flt(source.get("qty"), 6), "target_qty": 0.0, "kind": "Existing Batch"} for source in system_snapshot}
    physical_total = 0.0
    for index, raw in enumerate(segments):
        segment = frappe._dict(raw or {})
        qty = flt(segment.get("qty"), 6)
        physical_total = flt(physical_total + qty, 6)
        action = decisions.get(index) or ""
        if not action:
            action, _allowed = batch_reconciliation_segment_action(segment)

        batch_no = clean(segment.get("batch_no"))
        if action in {"Use Existing Batch", "Correct Existing Expiry", "Create Observed Batch"}:
            key = batch_no or _("Observed Batch")
            kind = action
        else:
            key = "AUTO on Post #{0}".format(index + 1)
            kind = action or "AUTO on Post"
        target = targets.setdefault(key, {"batch_no": key, "current_qty": 0.0, "target_qty": 0.0, "kind": kind})
        target["target_qty"] = flt(target.get("target_qty") + qty, 6)
        target["customer_price"] = flt(segment.get("customer_price") or segment.get("observed_price"), 6)
        target["expiry_date"] = clean(segment.get("expiry_date"))

    return {
        "row_name": row.name,
        "item_code": row.item_code,
        "warehouse": row.warehouse,
        "expected_qty_at_count": expected,
        "current_system_total": current_total,
        "physical_total": physical_total,
        "movement_safe": cint(abs(current_total - expected) <= 0.000001),
        "breakdown_fingerprint": status.get("breakdown_fingerprint"),
        "system_snapshot": system_snapshot,
        "system_snapshot_fingerprint": batch_system_snapshot_fingerprint(system_snapshot),
        "targets": sorted(targets.values(), key=lambda r: (clean(r.get("batch_no")), flt(r.get("target_qty"), 6))),
    }


def execute_batch_reconciliation_plans(doc) -> dict[str, Any]:
    """Apply reviewed Batch metadata decisions and build exact Batch target matrices.

    No general FEFO shortage allocation is used for rows handled here. Before any
    metadata write, the live Batch composition must exactly match the R1.10 R2
    snapshot that the reviewer armed. If stock moved, the Item is recounted rather
    than overwriting a live pharmacy movement.
    """
    summary = get_batch_reconciliation_status(doc)
    if not summary.get("required"):
        return {"handled_rows": [], "targets": [], "created_batches": [], "metadata_changes": [], "expired_targets": []}
    validate_batch_breakdown_posting(doc)

    handled_rows = []
    targets = []
    created_batches = []
    metadata_changes = []
    expired_targets = []
    today = getdate(nowdate())

    for row in doc.items or []:
        row_status = batch_reconciliation_row_status(doc, row)
        if not cint(row_status.get("required")):
            continue
        plan = _latest_batch_reconciliation_plan_for_row(doc.name, row)
        if clean(plan.get("version")) != "R1.10-R2" or not cint(plan.get("execution_ready")):
            frappe.throw(_("Item {0} does not have an armed R1.10 R2 execution plan.").format(frappe.bold(row.item_code)))

        current_snapshot = get_batch_system_snapshot(row.item_code, row.warehouse)
        current_fingerprint = batch_system_snapshot_fingerprint(current_snapshot)
        if current_fingerprint != clean(plan.get("system_snapshot_fingerprint")):
            frappe.throw(_("Batch stock changed after execution confirmation for Item {0}; recount is required.").format(frappe.bold(row.item_code)))
        current_total = flt(sum(flt(source.get("qty"), 6) for source in current_snapshot), 6)
        if abs(current_total - flt(row.expected_qty_at_count, 6)) > 0.000001:
            frappe.throw(_("Warehouse stock moved after the physical count for Item {0}; recount is required before Batch reconciliation.").format(frappe.bold(row.item_code)))

        breakdown = _latest_batch_breakdown_payload(doc.name, row)
        segments = breakdown.get("segments") or []
        decisions = {cint(raw.get("segment_index")): clean(raw.get("action")) for raw in (plan.get("decisions") or [])}
        if len(decisions) != len(segments):
            frappe.throw(_("Batch Reconciliation plan is incomplete for Item {0}.").format(frappe.bold(row.item_code)))

        target_qty_by_batch = defaultdict(float)
        target_meta = {}
        row_created = []
        row_changes = []
        row_expired = []
        for index, raw in enumerate(segments):
            segment = frappe._dict(raw or {})
            qty = flt(segment.get("qty"), 6)
            action = decisions.get(index)
            batch_no = clean(segment.get("batch_no"))
            expiry = clean(segment.get("expiry_date"))
            price = flt(segment.get("customer_price") or segment.get("observed_price"), 6)

            if action == "Use Existing Batch":
                validate_posting_batch(row.item_code, batch_no)
                resolved_batch = batch_no
            elif action == "Correct Existing Expiry":
                validate_posting_batch(row.item_code, batch_no)
                old_expiry = frappe.db.get_value("Batch", batch_no, "expiry_date")
                expected_old = clean(segment.get("system_expiry_date"))
                if expected_old and old_expiry and getdate(old_expiry) != getdate(expected_old):
                    frappe.throw(_("Batch {0} Expiry changed after review; execution plan is stale.").format(frappe.bold(batch_no)))
                if not expiry:
                    frappe.throw(_("Observed Expiry Date is required for Batch {0}.").format(frappe.bold(batch_no)))
                if not old_expiry or getdate(old_expiry) != getdate(expiry):
                    frappe.db.set_value("Batch", batch_no, "expiry_date", getdate(expiry), update_modified=True)
                    change = {"batch_no": batch_no, "field": "expiry_date", "old_value": clean(old_expiry), "new_value": expiry}
                    metadata_changes.append(change)
                    row_changes.append(change)
                resolved_batch = batch_no
            elif action == "Create Observed Batch":
                existed = bool(frappe.db.exists("Batch", batch_no))
                resolved_batch = _create_inventory_count_batch(doc, row, segment, batch_no=batch_no, auto_generated=False)
                if not existed:
                    created_batches.append(resolved_batch)
                    row_created.append(resolved_batch)
            elif action in {"Create AUTO Batch", "Reclassify to AUTO Batch"}:
                resolved_batch = _create_inventory_count_batch(doc, row, segment, auto_generated=True)
                created_batches.append(resolved_batch)
                row_created.append(resolved_batch)
            else:
                frappe.throw(_("Unsupported Batch Reconciliation action {0}.").format(frappe.bold(action)))

            target_qty_by_batch[resolved_batch] = flt(target_qty_by_batch[resolved_batch] + qty, 6)
            target_meta[resolved_batch] = {"expiry_date": expiry, "customer_price": price}
            if expiry and getdate(expiry) < today and qty > EPSILON:
                expired = {"item_code": row.item_code, "warehouse": row.warehouse, "batch_no": resolved_batch, "qty": qty, "expiry_date": expiry}
                expired_targets.append(expired)
                row_expired.append(expired)

        physical_total = flt(sum(target_qty_by_batch.values()), 6)
        if abs(physical_total - flt(row.actual_qty, 6)) > 0.000001:
            frappe.throw(_("Physical Batch target total does not equal Actual Qty for Item {0}.").format(frappe.bold(row.item_code)))

        current_by_batch = {clean(source.get("batch_no")): flt(source.get("qty"), 6) for source in current_snapshot}
        for batch_no in sorted(set(current_by_batch) | set(target_qty_by_batch)):
            current_qty = flt(current_by_batch.get(batch_no), 6)
            target_qty = flt(target_qty_by_batch.get(batch_no), 6)
            targets.append({
                "item_code": row.item_code,
                "warehouse": row.warehouse,
                "batch_no": batch_no,
                "target_qty": target_qty,
                "variance": flt(target_qty - current_qty, 6),
                "row_name": row.name,
                "controlled_batch_matrix": 1,
            })

        execution_payload = {
            "version": "R1.10-R2",
            "breakdown_fingerprint": row_status.get("breakdown_fingerprint"),
            "system_snapshot_fingerprint": current_fingerprint,
            "created_batches": row_created,
            "metadata_changes": row_changes,
            "expired_targets": row_expired,
            "targets": [target for target in targets if target.get("row_name") == row.name],
        }
        log_event(
            doc.name,
            "Batch Reconciliation Executed",
            row=row,
            details=_("Controlled Batch/Expiry/Price target matrix prepared for posting."),
            payload=execution_payload,
            count_round=row.count_round,
        )
        handled_rows.append(row.name)

    return {
        "handled_rows": handled_rows,
        "targets": targets,
        "created_batches": list(dict.fromkeys(created_batches)),
        "metadata_changes": metadata_changes,
        "expired_targets": expired_targets,
    }


def _expired_drugs_warehouse(company: str) -> str | None:
    return frappe.db.get_value(
        "Warehouse",
        {"company": company, "warehouse_name": "Expired Drugs", "is_group": 0, "disabled": 0},
        "name",
    )


def create_expired_stock_transfer(doc, expired_targets: list[dict[str, Any]]) -> str | None:
    if not expired_targets:
        return None
    destination = _expired_drugs_warehouse(doc.company)
    if not destination:
        frappe.throw(_("Expired Drugs Warehouse is required before posting expired physical stock."))

    entry = frappe.new_doc("Stock Entry")
    entry.company = doc.company
    entry.purpose = "Material Transfer"
    entry.posting_date = nowdate()
    entry.set_posting_time = 0
    entry.to_warehouse = destination
    entry.remarks = _("Inventory Count {0} automatic expired-stock segregation").format(doc.name)
    for raw in expired_targets:
        row = frappe._dict(raw or {})
        qty = flt(row.get("qty"), 6)
        if qty <= EPSILON:
            continue
        stock_uom = frappe.db.get_value("Item", row.item_code, "stock_uom")
        entry.append("items", {
            "item_code": row.item_code,
            "qty": qty,
            "uom": stock_uom,
            "stock_uom": stock_uom,
            "conversion_factor": 1,
            "s_warehouse": row.warehouse,
            "t_warehouse": destination,
            "batch_no": row.batch_no,
            "use_serial_batch_fields": 1,
        })
    if not entry.items:
        return None
    if hasattr(entry, "set_stock_entry_type"):
        entry.set_stock_entry_type()
    entry.flags.ignore_permissions = True
    entry.insert(ignore_permissions=True)
    entry.submit()
    return entry.name


def _batch_execution_events(count_name: str) -> list[dict[str, Any]]:
    events = frappe.get_all(
        EVENT_DOCTYPE,
        filters={"inventory_count": count_name, "event_type": "Batch Reconciliation Executed"},
        fields=["row_reference", "payload_json", "event_datetime", "creation"],
        order_by="event_datetime desc, creation desc",
        limit_page_length=1000,
    )
    latest = {}
    for event in events:
        key = clean(event.row_reference)
        if key in latest:
            continue
        try:
            latest[key] = json.loads(event.payload_json or "{}") or {}
        except Exception:
            latest[key] = {}
    return list(latest.values())


def reverse_batch_reconciliation_execution(doc) -> dict[str, Any]:
    """Reverse R1.10 R2 stock documents and metadata when a Posted Count is cancelled."""
    payloads = _batch_execution_events(doc.name)
    if not payloads:
        return {"handled": 0, "cancelled_stock_reconciliation": None, "cancelled_expired_entries": [], "restored_metadata": []}

    posted_event = frappe.get_all(
        EVENT_DOCTYPE,
        filters={"inventory_count": doc.name, "event_type": "Posted"},
        fields=["payload_json"],
        order_by="event_datetime desc, creation desc",
        limit_page_length=1,
    )
    expired_entries = []
    if posted_event:
        try:
            p = json.loads(posted_event[0].payload_json or "{}") or {}
            name = clean(p.get("expired_stock_entry"))
            if name:
                expired_entries.append(name)
        except Exception:
            pass

    cancelled_entries = []
    for name in dict.fromkeys(expired_entries):
        if frappe.db.exists("Stock Entry", name):
            entry = frappe.get_doc("Stock Entry", name)
            if entry.docstatus == 1:
                entry.flags.ignore_permissions = True
                entry.cancel()
                cancelled_entries.append(name)

    cancelled_reco = None
    if doc.stock_reconciliation and frappe.db.exists("Stock Reconciliation", doc.stock_reconciliation):
        reco = frappe.get_doc("Stock Reconciliation", doc.stock_reconciliation)
        if reco.docstatus == 1:
            reco.flags.ignore_permissions = True
            reco.cancel()
            cancelled_reco = reco.name

    restored = []
    changes = []
    created_batches = []
    for payload in payloads:
        changes.extend(payload.get("metadata_changes") or [])
        created_batches.extend(payload.get("created_batches") or [])
    for raw in reversed(changes):
        change = frappe._dict(raw or {})
        if clean(change.get("field")) != "expiry_date":
            continue
        batch_no = clean(change.get("batch_no"))
        if not batch_no or not frappe.db.exists("Batch", batch_no):
            continue
        current = frappe.db.get_value("Batch", batch_no, "expiry_date")
        new_value = clean(change.get("new_value"))
        old_value = clean(change.get("old_value"))
        if new_value and current and getdate(current) != getdate(new_value):
            frappe.throw(_("Batch {0} changed after Inventory Count posting; cancellation cannot safely restore Expiry.").format(frappe.bold(batch_no)))
        frappe.db.set_value("Batch", batch_no, "expiry_date", getdate(old_value) if old_value else None, update_modified=True)
        restored.append({"batch_no": batch_no, "field": "expiry_date", "restored_value": old_value})

    disabled_created_batches = []
    warehouses = frappe.get_all(
        "Warehouse",
        filters={"company": doc.company, "is_group": 0},
        pluck="name",
        limit_page_length=5000,
    )
    for batch_no in dict.fromkeys(clean(name) for name in created_batches if clean(name)):
        if not frappe.db.exists("Batch", batch_no):
            continue
        item_code = frappe.db.get_value("Batch", batch_no, "item")
        total_qty = flt(sum(_batch_qty(batch_no, warehouse, item_code) for warehouse in warehouses), 6)
        if abs(total_qty) <= EPSILON:
            frappe.db.set_value("Batch", batch_no, "disabled", 1, update_modified=True)
            disabled_created_batches.append(batch_no)

    return {
        "handled": 1,
        "cancelled_stock_reconciliation": cancelled_reco,
        "cancelled_expired_entries": cancelled_entries,
        "restored_metadata": restored,
        "disabled_created_batches": disabled_created_batches,
    }


def _batch_location_shortage_allocations(item_code: str, warehouse: str, location: str, qty: float) -> list[frappe._dict]:
    return allocate_batch_shortage(item_code, warehouse, qty, location=location)


def _post_location_decrease(doc, row, qty: float, *, to_location: str | None = None, key_suffix: str) -> list[dict[str, Any]]:
    item = _item_meta(row.item_code)
    qty = flt(qty, 6)
    if qty <= EPSILON:
        return []
    allocations = []
    if cint(item.has_batch_no):
        allocations = _batch_location_shortage_allocations(row.item_code, row.warehouse, row.location, qty)
    else:
        allocations = [frappe._dict(batch_no=None, qty=qty)]

    moved = []
    for index, allocation in enumerate(allocations, start=1):
        dedupe = f"INVCOUNT|{doc.name}|{row.name}|{key_suffix}|{index}|{clean(allocation.batch_no)}"
        result = post_movement(
            movement_type="Adjustment",
            warehouse=row.warehouse,
            item_code=row.item_code,
            batch_no=allocation.batch_no or None,
            qty=allocation.qty,
            from_location=row.location,
            to_location=to_location,
            reference_doctype=COUNT_DOCTYPE,
            reference_name=doc.name,
            reference_row=row.name,
            dedupe_key=dedupe,
            remarks=_("Inventory Count location reconciliation"),
        )
        moved.append({"dedupe_key": dedupe, "batch_no": allocation.batch_no, "qty": allocation.qty, "skipped": result.get("skipped")})
    return moved


def _post_location_increase(doc, row, qty: float, *, key_suffix: str) -> list[dict[str, Any]]:
    item = _item_meta(row.item_code)
    qty = flt(qty, 6)
    if qty <= EPSILON:
        return []

    if cint(item.has_batch_no):
        validate_posting_batch(row.item_code, row.posting_batch_no)
        official = _batch_qty(row.posting_batch_no, row.warehouse, row.item_code)
        allocated = flt(get_allocated_qty(row.item_code, row.warehouse, row.posting_batch_no), 6)
        available = flt(official - allocated, 6)
        if available + EPSILON < qty:
            frappe.throw(
                _(
                    "Location excess for Item {0} / Batch {1} exceeds unallocated Warehouse stock. "
                    "Run a Warehouse/Item Count before changing official stock."
                ).format(frappe.bold(row.item_code), frappe.bold(row.posting_batch_no))
            )
        batch_no = row.posting_batch_no
    else:
        official = flt(get_official_warehouse_qty(row.item_code, row.warehouse), 6)
        allocated = flt(get_allocated_qty(row.item_code, row.warehouse), 6)
        available = flt(official - allocated, 6)
        if available + EPSILON < qty:
            frappe.throw(
                _(
                    "Location excess for Item {0} exceeds unallocated Warehouse stock. "
                    "Run a Warehouse/Item Count before changing official stock."
                ).format(frappe.bold(row.item_code))
            )
        batch_no = None

    dedupe = f"INVCOUNT|{doc.name}|{row.name}|{key_suffix}|{clean(batch_no)}"
    result = post_movement(
        movement_type="Adjustment",
        warehouse=row.warehouse,
        item_code=row.item_code,
        batch_no=batch_no,
        qty=qty,
        from_location=None,
        to_location=row.location,
        reference_doctype=COUNT_DOCTYPE,
        reference_name=doc.name,
        reference_row=row.name,
        dedupe_key=dedupe,
        remarks=_("Inventory Count location reconciliation from unallocated stock"),
    )
    return [{"dedupe_key": dedupe, "batch_no": batch_no, "qty": qty, "skipped": result.get("skipped")}]


def _post_location_batch_matrix(doc, row) -> list[dict[str, Any]]:
    matrix = _location_batch_matrix(doc, row)
    deltas = [frappe._dict(raw or {}) for raw in (matrix.get("deltas") or [])]
    if not deltas:
        return []

    # Validate the complete matrix before the first operational movement.
    for delta_row in deltas:
        batch_no = clean(delta_row.batch_no)
        delta = flt(delta_row.delta, 6)
        current = flt(get_allocated_qty(row.item_code, row.warehouse, batch_no, row.location), 6)
        if current + delta < -EPSILON:
            frappe.throw(
                _(
                    "Location Batch stock changed after count for Item {0} / Batch {1}; the approved Batch delta can no longer be applied. Recount is required."
                ).format(frappe.bold(row.item_code), frappe.bold(batch_no))
            )
        if delta > EPSILON:
            validate_posting_batch(row.item_code, batch_no)
            meta = frappe.db.get_value("Batch", batch_no, ["disabled", "expiry_date"], as_dict=True) or frappe._dict()
            if cint(meta.get("disabled")):
                frappe.throw(_("Batch {0} is disabled and cannot be allocated to Location {1}.").format(frappe.bold(batch_no), frappe.bold(row.location)))
            if meta.get("expiry_date") and getdate(meta.get("expiry_date")) < getdate(nowdate()):
                frappe.throw(
                    _(
                        "Expired Batch {0} cannot be newly allocated to Location {1}. Run a Warehouse/Batch Count and expired-stock segregation instead."
                    ).format(frappe.bold(batch_no), frappe.bold(row.location))
                )
            official = flt(_batch_qty(batch_no, row.warehouse, row.item_code), 6)
            allocated = flt(get_allocated_qty(row.item_code, row.warehouse, batch_no), 6)
            available = flt(official - allocated, 6)
            if available + EPSILON < delta:
                frappe.throw(
                    _(
                        "Location excess for Item {0} / Batch {1} exceeds unallocated Warehouse stock. Run a Warehouse/Batch Count before changing official stock."
                    ).format(frappe.bold(row.item_code), frappe.bold(batch_no))
                )

    moved: list[dict[str, Any]] = []
    found_remaining = max(0.0, flt(row.found_elsewhere_qty, 6))

    # Negative Batch deltas leave the counted Location first.  Wrong-Location
    # quantity is routed to the selected Location; the remaining shortage becomes
    # unallocated.  Batch identity is preserved in every movement.
    for index, delta_row in enumerate((row for row in deltas if flt(row.delta, 6) < -EPSILON), start=1):
        batch_no = clean(delta_row.batch_no)
        qty = abs(flt(delta_row.delta, 6))
        found_qty = min(found_remaining, qty)
        if found_qty > EPSILON:
            validate_location(row.found_location, row.warehouse)
            dedupe = f"INVCOUNT|{doc.name}|{row.name}|MATRIX-FOUND|{index}|{batch_no}"
            result = post_movement(
                movement_type="Adjustment",
                warehouse=row.warehouse,
                item_code=row.item_code,
                batch_no=batch_no,
                qty=found_qty,
                from_location=row.location,
                to_location=row.found_location,
                reference_doctype=COUNT_DOCTYPE,
                reference_name=doc.name,
                reference_row=row.name,
                dedupe_key=dedupe,
                remarks=_("Inventory Count exact Location Batch reconciliation - found elsewhere"),
            )
            moved.append({"dedupe_key": dedupe, "batch_no": batch_no, "qty": found_qty, "skipped": result.get("skipped")})
            found_remaining = flt(found_remaining - found_qty, 6)
            qty = flt(qty - found_qty, 6)
        if qty > EPSILON:
            dedupe = f"INVCOUNT|{doc.name}|{row.name}|MATRIX-UNALLOC|{index}|{batch_no}"
            result = post_movement(
                movement_type="Adjustment",
                warehouse=row.warehouse,
                item_code=row.item_code,
                batch_no=batch_no,
                qty=qty,
                from_location=row.location,
                to_location=None,
                reference_doctype=COUNT_DOCTYPE,
                reference_name=doc.name,
                reference_row=row.name,
                dedupe_key=dedupe,
                remarks=_("Inventory Count exact Location Batch reconciliation - unallocated"),
            )
            moved.append({"dedupe_key": dedupe, "batch_no": batch_no, "qty": qty, "skipped": result.get("skipped")})

    for index, delta_row in enumerate((row for row in deltas if flt(row.delta, 6) > EPSILON), start=1):
        batch_no = clean(delta_row.batch_no)
        qty = flt(delta_row.delta, 6)
        dedupe = f"INVCOUNT|{doc.name}|{row.name}|MATRIX-INCREASE|{index}|{batch_no}"
        result = post_movement(
            movement_type="Adjustment",
            warehouse=row.warehouse,
            item_code=row.item_code,
            batch_no=batch_no,
            qty=qty,
            from_location=None,
            to_location=row.location,
            reference_doctype=COUNT_DOCTYPE,
            reference_name=doc.name,
            reference_row=row.name,
            dedupe_key=dedupe,
            remarks=_("Inventory Count exact Location Batch reconciliation from unallocated stock"),
        )
        moved.append({"dedupe_key": dedupe, "batch_no": batch_no, "qty": qty, "skipped": result.get("skipped")})

    log_event(
        doc.name,
        "Location Batch Matrix Posted",
        row=row,
        details=_("Exact physical Batch matrix applied to operational Location balances without changing Warehouse stock."),
        payload={"matrix": matrix, "movements": moved},
        count_round=row.count_round,
    )
    return moved


def post_location_variances(doc) -> list[dict[str, Any]]:
    moved: list[dict[str, Any]] = []
    for row in doc.items or []:
        if not cint(row.count_entered) or clean(row.count_basis) != "Location":
            continue
        item = _item_meta(row.item_code)
        if cint(item.has_batch_no):
            moved.extend(_post_location_batch_matrix(doc, row))
            continue
        variance = flt(row.variance_qty, 6)
        if abs(variance) <= EPSILON:
            continue
        current = current_expected_qty(row)
        if current + variance < -EPSILON:
            frappe.throw(
                _("Location stock changed after count for Item {0}; approved shortage can no longer be applied. Recount is required.").format(
                    frappe.bold(row.item_code)
                )
            )
        if variance < -EPSILON:
            shortage = abs(variance)
            found_qty = min(flt(row.found_elsewhere_qty, 6), shortage)
            if found_qty > EPSILON:
                validate_location(row.found_location, row.warehouse)
                moved.extend(_post_location_decrease(doc, row, found_qty, to_location=row.found_location, key_suffix="FOUND"))
            remaining = flt(shortage - found_qty, 6)
            if remaining > EPSILON:
                moved.extend(_post_location_decrease(doc, row, remaining, to_location=None, key_suffix="UNALLOC"))
        else:
            moved.extend(_post_location_increase(doc, row, variance, key_suffix="INCREASE"))
    return moved


def reverse_location_movements(doc) -> list[str]:
    rows = frappe.get_all(
        "Pharmacy Location Movement",
        filters={"reference_doctype": COUNT_DOCTYPE, "reference_name": doc.name},
        fields=["name", "warehouse", "item_code", "batch_no", "qty", "from_location", "to_location", "dedupe_key"],
        order_by="creation desc, name desc",
        limit_page_length=10000,
    )
    reversed_keys = []
    for raw in rows:
        row = frappe._dict(raw)
        if clean(row.dedupe_key).startswith("INVCOUNT-CANCEL|"):
            continue
        dedupe = f"INVCOUNT-CANCEL|{doc.name}|{row.name}"
        post_movement(
            movement_type="Adjustment",
            warehouse=row.warehouse,
            item_code=row.item_code,
            batch_no=row.batch_no or None,
            qty=row.qty,
            from_location=row.to_location or None,
            to_location=row.from_location or None,
            reference_doctype=COUNT_DOCTYPE,
            reference_name=doc.name,
            reference_row=row.name,
            dedupe_key=dedupe,
            remarks=_("Inventory Count cancellation reversal"),
        )
        reversed_keys.append(dedupe)
    return reversed_keys


def location_followup_required(row) -> bool:
    if clean(row.count_basis) != "Warehouse":
        return False
    allocated = flt(get_allocated_qty(row.item_code, row.warehouse), 6)
    official = flt(get_official_warehouse_qty(row.item_code, row.warehouse), 6)
    return allocated > official + EPSILON
