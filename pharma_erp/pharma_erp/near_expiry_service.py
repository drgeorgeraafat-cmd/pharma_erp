from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, cstr, date_diff, flt, getdate, nowdate

from pharma_erp.purchase_management import get_purchase_settings
from pharma_erp.pharma_erp.branch_warehouse_foundation import get_branch_profile
from pharma_erp.pharma_erp.inventory_count_service import (
    _bin_valuation_rate,
    get_batch_system_snapshot,
)
from pharma_erp.pharma_erp.page.pharmacy_pos.api import (
    _batch_price_context,
    _item_customer_price,
)
from pharma_erp.pharma_erp.unified_stock_availability import (
    SELLABLE_ROLES,
    get_unified_stock_availability,
)


CONTRACT_VERSION = "v0.9.3-near-expiry-r5f1"
MODE = "read_only_action_center"
EPSILON = 1e-9
READ_ROLES = {
    "Purchase User",
    "Purchase Manager",
    "Accounts User",
    "Accounts Manager",
    "Stock User",
    "Stock Manager",
    "System Manager",
}
ROLE_PRIORITY = ("Sales", "POS", "Online Fulfilment", "Pickup")
STATUS_ORDER = {"Expired": 0, "Critical": 1, "Urgent": 2, "Near Expiry": 3, "Safe": 4}


def _clean(value: Any) -> str:
    return cstr(value or "").strip()


def _default_company() -> str:
    return _clean(
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or ""
    )


def _roles() -> set[str]:
    if frappe.session.user == "Administrator":
        return {"System Manager"}
    return set(frappe.get_roles())


def _require_read_access() -> None:
    if not (_roles() & READ_ROLES):
        frappe.throw(_("You are not permitted to access Near Expiry Action Center."), frappe.PermissionError)

    for doctype in ("Item", "Batch", "Warehouse", "Stock Ledger Entry"):
        if frappe.db.exists("DocType", doctype) and not frappe.has_permission(doctype, "read"):
            frappe.throw(
                _("Read permission for {0} is required to use Near Expiry Action Center.").format(doctype),
                frappe.PermissionError,
            )


def _can_read_named_doc(doctype: str, name: str) -> bool:
    name = _clean(name)
    if not name or not frappe.db.exists("DocType", doctype):
        return False
    try:
        rows = frappe.get_list(
            doctype,
            filters={"name": name},
            pluck="name",
            limit_page_length=1,
        )
    except frappe.PermissionError:
        return False
    return bool(rows)


def _purchase_warning_horizon() -> tuple[int, int]:
    settings = get_purchase_settings()
    months = max(1, cint(settings.get("near_expiry_warning_months") or 6))
    today = getdate(nowdate())
    end_date = getdate(add_months(today, months))
    days = max(1, date_diff(end_date, today))
    return months, days


def _normalize_thresholds(
    *, horizon_days: int | str | None, critical_days: int | str | None, urgent_days: int | str | None
) -> tuple[int, int, int]:
    _, default_horizon = _purchase_warning_horizon()
    horizon = max(1, cint(horizon_days) or default_horizon)
    critical = max(0, cint(critical_days) if critical_days not in (None, "") else 30)
    urgent = max(0, cint(urgent_days) if urgent_days not in (None, "") else 60)
    critical = min(critical, horizon)
    urgent = max(critical, min(urgent, horizon))
    return horizon, critical, urgent


def classify_expiry(
    expiry_date,
    *,
    as_of_date=None,
    horizon_days: int | str | None = None,
    critical_days: int | str | None = None,
    urgent_days: int | str | None = None,
) -> dict[str, Any]:
    """Pure expiry classification used by UI and tests.

    Expired is always surfaced. Non-expired rows are classified only within the
    selected horizon. Thresholds are request-visible and are never hidden stock
    mutation rules.
    """

    if not expiry_date:
        return {"status": "No Expiry", "days_remaining": None}

    horizon, critical, urgent = _normalize_thresholds(
        horizon_days=horizon_days,
        critical_days=critical_days,
        urgent_days=urgent_days,
    )
    today = getdate(as_of_date or nowdate())
    expiry = getdate(expiry_date)
    days_remaining = date_diff(expiry, today)

    if days_remaining < 0:
        status = "Expired"
    elif days_remaining <= critical:
        status = "Critical"
    elif days_remaining <= urgent:
        status = "Urgent"
    elif days_remaining <= horizon:
        status = "Near Expiry"
    else:
        status = "Safe"

    return {"status": status, "days_remaining": days_remaining}


def _visible_branch_names(company: str) -> list[str]:
    rows = frappe.get_all(
        "Pharmacy Branch Profile",
        filters={"company": company, "disabled": 0},
        fields=["branch"],
        order_by="branch asc",
        limit_page_length=1000,
    )
    result = []
    for row in rows:
        branch = _clean(row.branch)
        if not branch or branch in result:
            continue
        if _can_read_named_doc("Branch", branch):
            result.append(branch)
    return result


def _visible_warehouse_profiles(company: str, *, branch: str = "", warehouse: str = "") -> list[frappe._dict]:
    filters: dict[str, Any] = {
        "company": company,
        "disabled": 0,
        "physicality": "Physical",
    }
    if branch:
        filters["branch"] = branch
    if warehouse:
        filters["warehouse"] = warehouse

    rows = frappe.get_all(
        "Pharmacy Warehouse Profile",
        filters=filters,
        fields=[
            "name",
            "warehouse",
            "branch",
            "company",
            "operational_class",
            "is_sellable",
            "allow_online",
        ],
        order_by="branch asc, warehouse asc",
        limit_page_length=5000,
    )

    result = []
    for raw in rows:
        row = frappe._dict(raw)
        if not _can_read_named_doc("Branch", row.branch):
            continue
        if not _can_read_named_doc("Warehouse", row.warehouse):
            continue
        warehouse_row = frappe.db.get_value(
            "Warehouse",
            row.warehouse,
            ["company", "is_group", "disabled"],
            as_dict=True,
        )
        if not warehouse_row:
            continue
        if cint(warehouse_row.is_group) or cint(warehouse_row.disabled):
            continue
        if _clean(warehouse_row.company) != company:
            continue
        result.append(row)
    return result


def _sellable_role_map(company: str, branches: set[str]) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    priority = {role: index for index, role in enumerate(ROLE_PRIORITY)}
    for branch in sorted(branches):
        profile = get_branch_profile(branch, company=company, require_enabled=True)
        candidates: dict[str, list[str]] = defaultdict(list)
        for row in profile.warehouse_roles or []:
            role = _clean(row.operational_role)
            warehouse = _clean(row.warehouse)
            if role in SELLABLE_ROLES and warehouse:
                candidates[warehouse].append(role)
        for warehouse, roles in candidates.items():
            roles.sort(key=lambda role: priority.get(role, 999))
            result[(branch, warehouse)] = roles[0]
    return result


def get_bootstrap(branch: str | None = None) -> dict[str, Any]:
    _require_read_access()
    company = _default_company()
    if not company:
        frappe.throw(_("Set a default Company before using Near Expiry Action Center."))

    branches = _visible_branch_names(company)
    requested_branch = _clean(branch)
    if requested_branch and requested_branch not in branches:
        frappe.throw(_("Branch {0} is unavailable or outside your permissions.").format(frappe.bold(requested_branch)))

    selected_branch = requested_branch
    if not selected_branch and len(branches) == 1:
        selected_branch = branches[0]

    warehouse_profiles = (
        _visible_warehouse_profiles(company, branch=selected_branch)
        if selected_branch
        else []
    )
    months, horizon_days = _purchase_warning_horizon()
    currency = _clean(frappe.db.get_value("Company", company, "default_currency"))

    return {
        "contract_version": CONTRACT_VERSION,
        "mode": MODE,
        "company": company,
        "currency": currency,
        "branches": branches,
        "selected_branch": selected_branch,
        "warehouses": [
            {
                "warehouse": row.warehouse,
                "operational_class": _clean(row.operational_class),
                "is_sellable": cint(row.is_sellable),
            }
            for row in warehouse_profiles
        ],
        "default_warning_months": months,
        "default_horizon_days": horizon_days,
        "default_critical_days": min(30, horizon_days),
        "default_urgent_days": min(max(30, 60), horizon_days),
        "status_options": ["", "Expired", "Critical", "Urgent", "Near Expiry"],
        "persistent_writes_performed": False,
    }


def _paged_candidate_batches(*, horizon_end, item_code: str = "", batch_no: str = "") -> list[frappe._dict]:
    filters: list[list[Any]] = [["Batch", "expiry_date", "<=", horizon_end]]
    if item_code:
        filters.append(["Batch", "item", "=", item_code])
    if batch_no:
        filters.append(["Batch", "name", "=", batch_no])

    result: list[frappe._dict] = []
    start = 0
    page_length = 1000
    while True:
        rows = frappe.get_list(
            "Batch",
            filters=filters,
            fields=["name", "item", "expiry_date", "disabled"],
            order_by="expiry_date asc, name asc",
            limit_start=start,
            limit_page_length=page_length,
        )
        result.extend(frappe._dict(row) for row in rows)
        if len(rows) < page_length:
            break
        start += page_length
    return result


def _item_meta_map(item_codes: list[str]) -> dict[str, frappe._dict]:
    result: dict[str, frappe._dict] = {}
    for start in range(0, len(item_codes), 500):
        chunk = item_codes[start : start + 500]
        rows = frappe.get_list(
            "Item",
            filters={"name": ("in", chunk)},
            fields=["name", "item_name", "item_group", "stock_uom", "disabled", "is_stock_item", "has_batch_no"],
            limit_page_length=len(chunk),
        )
        for row in rows:
            result[row.name] = frappe._dict(row)
    return result


def _allowed_item_groups(item_group: str) -> set[str] | None:
    item_group = _clean(item_group)
    if not item_group:
        return None
    if not frappe.db.exists("Item Group", item_group):
        frappe.throw(_("Item Group {0} does not exist.").format(frappe.bold(item_group)))
    groups = {item_group}
    try:
        from frappe.utils.nestedset import get_descendants_of

        groups.update(get_descendants_of("Item Group", item_group) or [])
    except Exception:
        pass
    return groups


def _physical_batch_qty(item_code: str, warehouse: str, batch_no: str) -> float:
    """Return official physical Batch stock, including expired stock.

    Near Expiry must not use saleable Batch selection as physical stock truth.
    ERPNext's ``for_stock_levels=True`` includes expired Batches, while
    ``ignore_reserved_stock=True`` prevents reservations from reducing the
    physical quantity shown by the Action Center.
    """

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    qty = get_batch_qty(
        batch_no=batch_no,
        warehouse=warehouse,
        item_code=item_code,
        for_stock_levels=True,
        ignore_reserved_stock=True,
    )
    return flt(qty or 0, 6)


def _valuation_context(item_code: str, warehouse: str) -> tuple[float, str]:
    bin_rate = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate")
    effective = flt(_bin_valuation_rate(item_code, warehouse), 6)
    if flt(bin_rate or 0, 6) > 0:
        return effective, "ERPNext Bin Valuation Rate"
    if effective > 0:
        return effective, "ERPNext Item Valuation Rate Fallback"
    return 0.0, "Unresolved"


def _availability_context(
    *, item_code: str, branch: str, warehouse: str, batch_no: str, role: str | None, as_of_date
) -> tuple[float, list[str], str | None]:
    if not role:
        return 0.0, ["warehouse_not_mapped_to_sellable_role"], None

    try:
        availability = get_unified_stock_availability(
            item_code=item_code,
            branch=branch,
            operational_role=role,
            warehouse=warehouse,
            source_type="batch",
            source_name=batch_no,
            as_of_date=as_of_date,
            enforce_permissions=True,
        )
    except frappe.PermissionError:
        raise
    except Exception as exc:
        return 0.0, ["availability_unresolved"], _clean(exc)

    quantities = frappe._dict(availability.get("quantities") or {})
    blockers = sorted(set(availability.get("blockers") or []))
    sellable_qty = flt(
        quantities.get("available_to_promise")
        if quantities.get("available_to_promise") is not None
        else quantities.get("source_sellable_qty"),
        6,
    )
    return max(0.0, sellable_qty), blockers, None


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    unique_by_status: dict[str, set[str]] = defaultdict(set)
    physical_qty = 0.0
    retail_exposure = 0.0
    at_risk_cost = 0.0
    unresolved_retail_rows = 0
    unresolved_cost_rows = 0

    for raw in rows:
        row = frappe._dict(raw)
        unique_by_status[_clean(row.expiry_status)].add(_clean(row.batch_no))
        physical_qty += flt(row.physical_qty, 6)
        if row.get("retail_exposure") is None:
            unresolved_retail_rows += 1
        else:
            retail_exposure += flt(row.retail_exposure, 6)
        if row.get("at_risk_cost") is None:
            unresolved_cost_rows += 1
        else:
            at_risk_cost += flt(row.at_risk_cost, 6)

    return {
        "rows": len(rows),
        "expired_batches": len(unique_by_status["Expired"]),
        "critical_batches": len(unique_by_status["Critical"]),
        "urgent_batches": len(unique_by_status["Urgent"]),
        "near_expiry_batches": len(unique_by_status["Near Expiry"]),
        "physical_qty_at_risk": flt(physical_qty, 6),
        "retail_exposure": flt(retail_exposure, 6),
        "at_risk_cost": flt(at_risk_cost, 6),
        "unresolved_retail_rows": unresolved_retail_rows,
        "unresolved_cost_rows": unresolved_cost_rows,
    }


def get_near_expiry_action_center(
    *,
    branch: str,
    warehouse: str = "",
    item_group: str = "",
    item_code: str = "",
    batch_no: str = "",
    horizon_days: int | str | None = None,
    critical_days: int | str | None = None,
    urgent_days: int | str | None = None,
    status: str = "",
    as_of_date=None,
) -> dict[str, Any]:
    """Return read-only Near Expiry operational rows.

    Warehouse/Stock Ledger semantics remain authoritative. No Location Balance is
    consulted for stock truth and this function never mutates stock/accounting data.
    """

    _require_read_access()
    company = _default_company()
    if not company:
        frappe.throw(_("Set a default Company before using Near Expiry Action Center."))

    branch = _clean(branch)
    warehouse = _clean(warehouse)
    item_group = _clean(item_group)
    item_code = _clean(item_code)
    batch_no = _clean(batch_no)
    status = _clean(status)
    if not branch:
        frappe.throw(_("Select a Branch before loading Near Expiry stock."))

    visible_branches = _visible_branch_names(company)
    if branch not in visible_branches:
        frappe.throw(_("Branch {0} is unavailable or outside your permissions.").format(frappe.bold(branch)))

    horizon, critical, urgent = _normalize_thresholds(
        horizon_days=horizon_days,
        critical_days=critical_days,
        urgent_days=urgent_days,
    )
    today = getdate(as_of_date or nowdate())
    horizon_end = getdate(add_days(today, horizon))

    profiles = _visible_warehouse_profiles(company, branch=branch, warehouse=warehouse)
    if warehouse and not profiles:
        frappe.throw(
            _("Warehouse {0} is unavailable, inactive, non-physical, or outside your permissions.").format(
                frappe.bold(warehouse)
            )
        )
    if not profiles:
        return {
            "contract_version": CONTRACT_VERSION,
            "mode": MODE,
            "company": company,
            "currency": _clean(frappe.db.get_value("Company", company, "default_currency")),
            "as_of_date": cstr(today),
            "summary": _summarize([]),
            "rows": [],
            "warnings": [_("No readable active physical Warehouses are configured for this Branch.")],
            "filters": {
                "branch": branch,
                "warehouse": warehouse,
                "horizon_days": horizon,
                "critical_days": critical,
                "urgent_days": urgent,
                "status": status,
            },
            "persistent_writes_performed": False,
        }

    candidate_batches = _paged_candidate_batches(
        horizon_end=horizon_end,
        item_code=item_code,
        batch_no=batch_no,
    )
    candidate_items = sorted({_clean(row.item) for row in candidate_batches if _clean(row.item)})
    item_meta = _item_meta_map(candidate_items)
    allowed_groups = _allowed_item_groups(item_group)

    candidates_by_item: dict[str, dict[str, frappe._dict]] = defaultdict(dict)
    for batch in candidate_batches:
        item = item_meta.get(_clean(batch.item))
        if not item:
            continue
        if allowed_groups is not None and _clean(item.item_group) not in allowed_groups:
            continue
        if not cint(item.is_stock_item) or not cint(item.has_batch_no):
            continue
        candidates_by_item[item.name][batch.name] = batch

    role_map = _sellable_role_map(company, {branch})
    warnings: set[str] = set()
    rows: list[dict[str, Any]] = []

    for profile in profiles:
        profile = frappe._dict(profile)
        mapped_role = role_map.get((branch, profile.warehouse))
        for candidate_item in sorted(candidates_by_item):
            # Keep Inventory Count's shared snapshot only as a retail-price parity
            # reference. Physical stock is resolved independently below so an
            # expired Batch cannot disappear merely because a saleable-stock
            # helper excludes it.
            snapshots = {
                _clean(row.get("batch_no")): frappe._dict(row)
                for row in get_batch_system_snapshot(candidate_item, profile.warehouse)
                if _clean(row.get("batch_no"))
            }
            item = item_meta[candidate_item]
            fallback_price = flt(_item_customer_price(candidate_item), 6)
            valuation_rate, valuation_source = _valuation_context(candidate_item, profile.warehouse)

            for candidate_name in sorted(candidates_by_item[candidate_item]):
                candidate = candidates_by_item[candidate_item][candidate_name]
                physical_qty = _physical_batch_qty(candidate_item, profile.warehouse, candidate.name)
                if physical_qty <= EPSILON:
                    continue
                snapshot = snapshots.get(candidate.name)

                classification = classify_expiry(
                    candidate.expiry_date,
                    as_of_date=today,
                    horizon_days=horizon,
                    critical_days=critical,
                    urgent_days=urgent,
                )
                expiry_status = classification["status"]
                if expiry_status == "Safe":
                    continue
                if status and status != expiry_status:
                    continue

                sellable_qty, blockers, availability_error = _availability_context(
                    item_code=candidate_item,
                    branch=branch,
                    warehouse=profile.warehouse,
                    batch_no=candidate.name,
                    role=mapped_role,
                    as_of_date=today,
                )
                if availability_error:
                    warnings.add(
                        _("Availability could not be resolved for Item {0}, Batch {1}, Warehouse {2}.").format(
                            candidate_item, candidate.name, profile.warehouse
                        )
                    )

                price_context = _batch_price_context(candidate.name, candidate_item, fallback_price)
                retail_price = flt(price_context.get("customer_price") or 0, 6)
                price_integrity_error = cint(price_context.get("price_integrity_error"))
                snapshot_price = flt(snapshot.get("customer_price") or 0, 6) if snapshot else retail_price
                price_parity = snapshot is None or abs(snapshot_price - retail_price) <= 0.000001
                if not price_parity:
                    warnings.add(
                        _("Retail price parity mismatch for Item {0}, Batch {1}.").format(candidate_item, candidate.name)
                    )
                retail_resolved = bool(retail_price > 0 and not price_integrity_error and price_parity)
                retail_exposure = flt(physical_qty * retail_price, 6) if retail_resolved else None
                if not retail_resolved:
                    warnings.add(
                        _("Retail exposure is unresolved for Item {0}, Batch {1}.").format(candidate_item, candidate.name)
                    )

                cost_resolved = valuation_rate > 0
                at_risk_cost = flt(physical_qty * valuation_rate, 6) if cost_resolved else None
                if not cost_resolved:
                    warnings.add(
                        _("At-risk cost is unresolved for Item {0}, Warehouse {1}.").format(candidate_item, profile.warehouse)
                    )

                if expiry_status == "Expired":
                    action_status = "Review Required"
                elif expiry_status in {"Critical", "Urgent"}:
                    action_status = "Action Review"
                else:
                    action_status = "Monitor"

                rows.append(
                    {
                        "branch": branch,
                        "warehouse": profile.warehouse,
                        "warehouse_operational_class": _clean(profile.operational_class),
                        "warehouse_is_sellable": cint(profile.is_sellable),
                        "sellable_role": mapped_role or "",
                        "item_code": candidate_item,
                        "item_name": _clean(item.item_name),
                        "item_group": _clean(item.item_group),
                        "stock_uom": _clean(item.stock_uom),
                        "item_disabled": cint(item.disabled),
                        "batch_no": candidate.name,
                        "batch_disabled": cint(candidate.disabled),
                        "expiry_date": cstr(candidate.expiry_date),
                        "days_remaining": classification["days_remaining"],
                        "expiry_status": expiry_status,
                        "physical_qty": physical_qty,
                        "sellable_qty": flt(sellable_qty, 6),
                        "availability_blockers": blockers,
                        "retail_price": retail_price if retail_resolved else None,
                        "retail_price_source": _clean(price_context.get("price_source")),
                        "retail_price_integrity_error": price_integrity_error,
                        "retail_exposure": retail_exposure,
                        "valuation_rate": valuation_rate if cost_resolved else None,
                        "valuation_source": valuation_source,
                        "at_risk_cost": at_risk_cost,
                        "action_status": action_status,
                    }
                )

    rows.sort(
        key=lambda row: (
            STATUS_ORDER.get(row["expiry_status"], 99),
            row["days_remaining"] if row["days_remaining"] is not None else 999999,
            row["item_code"],
            row["batch_no"],
            row["warehouse"],
        )
    )

    currency = _clean(frappe.db.get_value("Company", company, "default_currency"))
    return {
        "contract_version": CONTRACT_VERSION,
        "mode": MODE,
        "company": company,
        "currency": currency,
        "as_of_date": cstr(today),
        "summary": _summarize(rows),
        "rows": rows,
        "warnings": sorted(warnings),
        "filters": {
            "branch": branch,
            "warehouse": warehouse,
            "item_group": item_group,
            "item_code": item_code,
            "batch_no": batch_no,
            "horizon_days": horizon,
            "critical_days": critical,
            "urgent_days": urgent,
            "status": status,
        },
        "persistent_writes_performed": False,
    }
