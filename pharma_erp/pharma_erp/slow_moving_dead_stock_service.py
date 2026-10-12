from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, date_diff, flt, getdate, nowdate

from erpnext.stock.report.stock_ageing.stock_ageing import FIFOSlots, get_average_age, get_report_fifo_queue
from pharma_erp.purchase_management import get_purchase_settings
from pharma_erp.pharma_erp.branch_warehouse_foundation import get_branch_profile
from pharma_erp.pharma_erp.inventory_count_service import _bin_valuation_rate
from pharma_erp.pharma_erp.page.pharmacy_pos.api import _item_customer_price
from pharma_erp.pharma_erp.unified_stock_availability import SELLABLE_ROLES, get_unified_stock_availability

CONTRACT_VERSION = "v0.9.3-slow-moving-dead-stock-r2"
MODE = "read_only_action_center"
EPSILON = 1e-9
READ_ROLES = {
    "Purchase User", "Purchase Manager", "Sales User", "Sales Manager",
    "Accounts User", "Accounts Manager", "Stock User", "Stock Manager", "System Manager",
}
ROLE_PRIORITY = ("Sales", "POS", "Online Fulfilment", "Pickup")
STATUS_ORDER = {"No Movement": 0, "Low Movement": 1, "Recent Stock": 2, "Not Sellable": 3, "Normal": 4, "Unresolved": 5}


def _clean(value: Any) -> str:
    return cstr(value or "").strip()


def _default_company() -> str:
    return _clean(frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company") or "")


def _roles() -> set[str]:
    if frappe.session.user == "Administrator":
        return {"System Manager"}
    return set(frappe.get_roles())


def _require_read_access() -> None:
    if not (_roles() & READ_ROLES):
        frappe.throw(_("You are not permitted to access Slow Moving & Dead Stock Action Center."), frappe.PermissionError)
    for doctype in ("Item", "Warehouse", "Stock Ledger Entry", "Sales Invoice"):
        if frappe.db.exists("DocType", doctype) and not frappe.has_permission(doctype, "read"):
            frappe.throw(_("Read permission for {0} is required to use Slow Moving & Dead Stock Action Center.").format(doctype), frappe.PermissionError)


def _can_read_named_doc(doctype: str, name: str) -> bool:
    name = _clean(name)
    if not name or not frappe.db.exists("DocType", doctype):
        return False
    try:
        return bool(frappe.get_list(doctype, filters={"name": name}, pluck="name", limit_page_length=1))
    except frappe.PermissionError:
        return False


def _visible_branch_names(company: str) -> list[str]:
    rows = frappe.get_all("Pharmacy Branch Profile", filters={"company": company, "disabled": 0}, fields=["branch"], order_by="branch asc", limit_page_length=1000)
    result = []
    for row in rows:
        branch = _clean(row.branch)
        if branch and branch not in result and _can_read_named_doc("Branch", branch):
            result.append(branch)
    return result


def _visible_warehouse_profiles(company: str, *, branch: str, warehouse: str = "") -> list[frappe._dict]:
    filters = {"company": company, "branch": branch, "disabled": 0, "physicality": "Physical"}
    if warehouse:
        filters["warehouse"] = warehouse
    rows = frappe.get_all(
        "Pharmacy Warehouse Profile", filters=filters,
        fields=["name", "warehouse", "branch", "company", "operational_class", "is_sellable", "allow_online"],
        order_by="warehouse asc", limit_page_length=5000,
    )
    result = []
    for raw in rows:
        row = frappe._dict(raw)
        if not _can_read_named_doc("Warehouse", row.warehouse):
            continue
        wh = frappe.db.get_value("Warehouse", row.warehouse, ["company", "is_group", "disabled"], as_dict=True)
        if not wh or cint(wh.is_group) or cint(wh.disabled) or _clean(wh.company) != company:
            continue
        result.append(row)
    return result


def _sellable_role_map(company: str, branch: str) -> dict[str, str]:
    result = {}
    priority = {role: i for i, role in enumerate(ROLE_PRIORITY)}
    profile = get_branch_profile(branch, company=company, require_enabled=True)
    candidates = defaultdict(list)
    for row in profile.warehouse_roles or []:
        role = _clean(row.operational_role)
        warehouse = _clean(row.warehouse)
        if role in SELLABLE_ROLES and warehouse:
            candidates[warehouse].append(role)
    for warehouse, roles in candidates.items():
        roles.sort(key=lambda role: priority.get(role, 999))
        result[warehouse] = roles[0]
    return result


def movement_metrics(gross_qty: float, returned_qty: float, physical_qty: float) -> dict[str, float]:
    gross = flt(gross_qty or 0, 6)
    returned = flt(returned_qty or 0, 6)
    net = flt(gross - returned, 6)
    ratio = flt((net / physical_qty) * 100, 2) if flt(physical_qty) > EPSILON else 0.0
    return {"gross_movement_qty": gross, "returned_movement_qty": returned, "net_movement_qty": net, "movement_ratio_percent": ratio}


def classify_movement(*, net_movement_qty: float, average_stock_age_days: float | None, minimum_stock_age_days: int,
                      maximum_movement_qty: float, warehouse_is_sellable: bool, sellable_qty: float) -> str:
    if not warehouse_is_sellable or flt(sellable_qty, 6) <= EPSILON:
        return "Not Sellable"
    if average_stock_age_days is None:
        return "Unresolved"
    if flt(average_stock_age_days, 6) < flt(minimum_stock_age_days, 6):
        return "Recent Stock"
    net = flt(net_movement_qty, 6)
    if abs(net) <= EPSILON:
        return "No Movement"
    if net < -EPSILON:
        return "Unresolved"
    if net <= flt(maximum_movement_qty, 6) + EPSILON:
        return "Low Movement"
    return "Normal"


def _purchase_defaults() -> tuple[int, int]:
    settings = get_purchase_settings()
    return max(1, cint(settings.get("slow_movement_analysis_days") or 30)), max(1, cint(settings.get("dormant_item_days") or 90))


def get_bootstrap(branch: str | None = None) -> dict[str, Any]:
    _require_read_access()
    company = _default_company()
    if not company:
        frappe.throw(_("Set a default Company before using Slow Moving & Dead Stock Action Center."))
    branches = _visible_branch_names(company)
    requested = _clean(branch)
    if requested and requested not in branches:
        frappe.throw(_("Branch {0} is unavailable or outside your permissions.").format(frappe.bold(requested)))
    selected = requested or (branches[0] if len(branches) == 1 else "")
    profiles = _visible_warehouse_profiles(company, branch=selected) if selected else []
    lookback, min_age = _purchase_defaults()
    return {
        "contract_version": CONTRACT_VERSION, "mode": MODE, "company": company,
        "currency": _clean(frappe.db.get_value("Company", company, "default_currency")),
        "branches": branches, "selected_branch": selected,
        "warehouses": [{"warehouse": r.warehouse, "operational_class": _clean(r.operational_class), "is_sellable": cint(r.is_sellable)} for r in profiles],
        "default_lookback_days": lookback, "default_minimum_stock_age_days": min_age,
        "default_maximum_movement_qty": 0,
        "status_options": ["", "No Movement", "Low Movement", "Recent Stock", "Not Sellable", "Normal"],
        "persistent_writes_performed": False,
    }


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


def _candidate_bins(*, company: str, profiles: list[frappe._dict], item_group: str = "", item_code: str = "") -> list[frappe._dict]:
    warehouses = [_clean(r.warehouse) for r in profiles if _clean(r.warehouse)]
    if not warehouses:
        return []
    wh_marks = ", ".join(["%s"] * len(warehouses))
    params = [company, *warehouses]
    conditions = ["w.company=%s", f"b.warehouse in ({wh_marks})", "b.actual_qty > 0.000001", "i.disabled=0", "i.is_stock_item=1"]
    if item_code:
        conditions.append("b.item_code=%s")
        params.append(item_code)
    rows = frappe.db.sql(
        f"""select b.item_code,i.item_name,i.item_group,i.stock_uom,i.has_batch_no,i.has_serial_no,
                   b.warehouse,b.actual_qty,b.projected_qty,b.valuation_rate
              from `tabBin` b
              join `tabItem` i on i.name=b.item_code
              join `tabWarehouse` w on w.name=b.warehouse
             where {' and '.join(conditions)}
             order by b.warehouse,b.item_code""",
        params, as_dict=True,
    )
    allowed = _allowed_item_groups(item_group)
    if allowed is not None:
        rows = [r for r in rows if _clean(r.item_group) in allowed]
    meta = frappe.get_meta("Item")
    extra_fields = [f for f in ("custom_pack_size", "custom_uom_options", "custom_box_only") if meta.has_field(f)]
    if extra_fields and rows:
        codes = sorted({_clean(r.item_code) for r in rows})
        extras = {r.name: frappe._dict(r) for r in frappe.get_all("Item", filters={"name": ("in", codes)}, fields=["name", *extra_fields], limit_page_length=len(codes))}
        for row in rows:
            extra = extras.get(row.item_code, frappe._dict())
            for field in extra_fields:
                row[field] = extra.get(field)
    return [frappe._dict(r) for r in rows]


def _sales_movement_map(*, company: str, keys: list[tuple[str, str]], start_date, end_date) -> dict[tuple[str, str], frappe._dict]:
    if not keys:
        return {}
    items = sorted({x[0] for x in keys}); warehouses = sorted({x[1] for x in keys})
    im = ", ".join(["%s"] * len(items)); wm = ", ".join(["%s"] * len(warehouses))
    rows = frappe.db.sql(
        f"""select sii.item_code,sii.warehouse,
                   sum(case when ifnull(si.is_return,0)=0 then abs(ifnull(sii.stock_qty,0)) else 0 end) gross_qty,
                   sum(case when ifnull(si.is_return,0)=1 then abs(ifnull(sii.stock_qty,0)) else 0 end) returned_qty,
                   max(case when ifnull(si.is_return,0)=0 and abs(ifnull(sii.stock_qty,0))>0.000001 then si.posting_date else null end) last_sale_date
              from `tabSales Invoice` si
              join `tabSales Invoice Item` sii on sii.parent=si.name
             where si.docstatus=1 and si.company=%s and si.posting_date>=%s and si.posting_date<=%s
               and sii.item_code in ({im}) and sii.warehouse in ({wm})
             group by sii.item_code,sii.warehouse""",
        [company, start_date, end_date, *items, *warehouses], as_dict=True,
    )
    return {(_clean(r.item_code), _clean(r.warehouse)): frappe._dict(r) for r in rows}


def _last_sale_map(company: str, keys: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    if not keys:
        return {}
    items = sorted({x[0] for x in keys}); warehouses = sorted({x[1] for x in keys})
    im = ", ".join(["%s"] * len(items)); wm = ", ".join(["%s"] * len(warehouses))
    rows = frappe.db.sql(
        f"""select sii.item_code,sii.warehouse,max(si.posting_date) last_sale_date
              from `tabSales Invoice` si join `tabSales Invoice Item` sii on sii.parent=si.name
             where si.docstatus=1 and si.company=%s and ifnull(si.is_return,0)=0
               and abs(ifnull(sii.stock_qty,0))>0.000001 and sii.item_code in ({im}) and sii.warehouse in ({wm})
             group by sii.item_code,sii.warehouse""",
        [company, *items, *warehouses], as_dict=True,
    )
    return {(_clean(r.item_code), _clean(r.warehouse)): _clean(r.last_sale_date) for r in rows}


def _inward_map(company: str, keys: list[tuple[str, str]]) -> dict[tuple[str, str], frappe._dict]:
    if not keys:
        return {}
    items = sorted({x[0] for x in keys}); warehouses = sorted({x[1] for x in keys})
    im = ", ".join(["%s"] * len(items)); wm = ", ".join(["%s"] * len(warehouses))
    rows = frappe.db.sql(
        f"""select sle.item_code,sle.warehouse,
                   max(case when sle.actual_qty>0 then sle.posting_date else null end) last_inward_date,
                   max(case when sle.actual_qty>0 and sle.voucher_type='Purchase Receipt' then sle.posting_date else null end) last_purchase_receipt_date
              from `tabStock Ledger Entry` sle
             where sle.company=%s and sle.is_cancelled=0 and sle.item_code in ({im}) and sle.warehouse in ({wm})
             group by sle.item_code,sle.warehouse""",
        [company, *items, *warehouses], as_dict=True,
    )
    return {(_clean(r.item_code), _clean(r.warehouse)): frappe._dict(r) for r in rows}


def _fifo_age_map(company: str, warehouses: list[str], as_of_date) -> dict[tuple[str, str], frappe._dict]:
    result = {}
    for warehouse in sorted(set(warehouses)):
        filters = frappe._dict(company=company, to_date=cstr(as_of_date), range="30,60,90,180", show_warehouse_wise_stock=1, warehouse=warehouse)
        for key, item_dict in FIFOSlots(filters).generate().items():
            if not isinstance(key, tuple) or len(key) != 2 or _clean(key[1]) != warehouse:
                continue
            total_qty = flt(item_dict.get("total_qty"), 6)
            if total_qty <= EPSILON:
                continue
            queue = get_report_fifo_queue(item_dict.get("fifo_queue") or [], bool(item_dict.get("has_batch_no")))
            if not queue:
                continue
            ages = [max(0, date_diff(as_of_date, slot[-2])) for slot in queue if slot[-2]]
            result[(key[0], warehouse)] = frappe._dict(
                fifo_total_qty=total_qty, average_age_days=flt(get_average_age(queue, cstr(as_of_date)), 2),
                oldest_remaining_age_days=max(ages) if ages else None,
                youngest_remaining_age_days=min(ages) if ages else None,
                fifo_slots=len(queue),
            )
    return result


def _availability_context(*, item_code: str, branch: str, warehouse: str, role: str | None, as_of_date):
    if not role:
        return 0.0, ["warehouse_not_mapped_to_sellable_role"], None
    try:
        data = get_unified_stock_availability(
            item_code=item_code, branch=branch, operational_role=role, warehouse=warehouse,
            source_type="stock", as_of_date=as_of_date, enforce_permissions=True,
        )
    except frappe.PermissionError:
        raise
    except Exception as exc:
        return 0.0, ["availability_unresolved"], _clean(exc)
    q = frappe._dict(data.get("quantities") or {})
    qty = flt(q.get("available_to_promise") if q.get("available_to_promise") is not None else q.get("source_sellable_qty"), 6)
    return max(0.0, qty), sorted(set(data.get("blockers") or [])), None


def _package_definition(row: frappe._dict) -> str:
    stock_uom = _clean(row.stock_uom)
    pack_size = cint(row.get("custom_pack_size") or 0)
    subunit = _clean(row.get("custom_uom_options"))
    if stock_uom.lower() == "box" and pack_size > 1 and subunit:
        return _("1 Box = {0} {1}").format(pack_size, subunit)
    if stock_uom.lower() == "box":
        return _("Box")
    return _("{0} (non-Box legacy/test item)").format(stock_uom or _("Stock UOM"))


def _summarize(rows):
    counts = defaultdict(int); retail = cost = box_physical = box_net = 0.0
    unresolved_retail = unresolved_cost = non_box = 0
    for raw in rows:
        r = frappe._dict(raw); counts[_clean(r.movement_status)] += 1
        if _clean(r.stock_uom).lower() == "box":
            box_physical += flt(r.physical_qty, 6); box_net += flt(r.net_movement_qty, 6)
        else:
            non_box += 1
        if r.get("retail_exposure") is None: unresolved_retail += 1
        else: retail += flt(r.retail_exposure, 6)
        if r.get("cost_exposure") is None: unresolved_cost += 1
        else: cost += flt(r.cost_exposure, 6)
    return {
        "rows": len(rows), "no_movement_rows": counts["No Movement"], "low_movement_rows": counts["Low Movement"],
        "recent_stock_rows": counts["Recent Stock"], "not_sellable_rows": counts["Not Sellable"], "normal_rows": counts["Normal"],
        "unresolved_rows": counts["Unresolved"], "box_physical_qty": flt(box_physical, 6),
        "box_net_movement_qty": flt(box_net, 6), "non_box_rows": non_box,
        "retail_exposure": flt(retail, 6), "cost_exposure": flt(cost, 6),
        "unresolved_retail_rows": unresolved_retail, "unresolved_cost_rows": unresolved_cost,
    }


def get_action_center(*, branch: str, warehouse: str = "", item_group: str = "", item_code: str = "",
                      lookback_days=None, maximum_movement_qty=None, minimum_stock_age_days=None,
                      status: str = "", as_of_date=None) -> dict[str, Any]:
    _require_read_access()
    company = _default_company()
    if not company:
        frappe.throw(_("Set a default Company before using Slow Moving & Dead Stock Action Center."))
    branch = _clean(branch); warehouse = _clean(warehouse); item_group = _clean(item_group); item_code = _clean(item_code); status = _clean(status)
    if not branch:
        frappe.throw(_("Select a Branch before loading Slow Moving stock."))
    if branch not in _visible_branch_names(company):
        frappe.throw(_("Branch {0} is unavailable or outside your permissions.").format(frappe.bold(branch)))

    default_lookback, default_min_age = _purchase_defaults()
    lookback = max(1, cint(lookback_days) or default_lookback)
    min_age = max(1, cint(minimum_stock_age_days) or default_min_age)
    max_move = max(0.0, flt(maximum_movement_qty or 0, 6))
    today = getdate(as_of_date or nowdate())
    start_date = getdate(add_days(today, -lookback))

    all_profiles = _visible_warehouse_profiles(company, branch=branch, warehouse=warehouse)
    if warehouse and not all_profiles:
        frappe.throw(_("Warehouse {0} is unavailable, inactive, non-physical, or outside your permissions.").format(frappe.bold(warehouse)))
    profiles = all_profiles if warehouse else [r for r in all_profiles if cint(r.is_sellable)]

    if not profiles:
        return {
            "contract_version": CONTRACT_VERSION, "mode": MODE, "company": company,
            "currency": _clean(frappe.db.get_value("Company", company, "default_currency")),
            "as_of_date": cstr(today), "summary": _summarize([]), "rows": [],
            "warnings": [_("No readable physical Warehouses match the current scope.")],
            "filters": {"branch": branch, "warehouse": warehouse, "lookback_days": lookback,
                        "maximum_movement_qty": max_move, "minimum_stock_age_days": min_age, "status": status},
            "persistent_writes_performed": False,
        }

    bins = _candidate_bins(company=company, profiles=profiles, item_group=item_group, item_code=item_code)
    keys = [(_clean(r.item_code), _clean(r.warehouse)) for r in bins]
    movement_map = _sales_movement_map(company=company, keys=keys, start_date=start_date, end_date=today)
    last_sales = _last_sale_map(company, keys)
    inwards = _inward_map(company, keys)
    ages = _fifo_age_map(company, [_clean(r.warehouse) for r in profiles], today)
    role_map = _sellable_role_map(company, branch)
    profile_map = {_clean(r.warehouse): frappe._dict(r) for r in profiles}

    warnings = set(); rows = []
    for b in bins:
        key = (_clean(b.item_code), _clean(b.warehouse))
        p = profile_map.get(key[1], frappe._dict())
        movement = movement_map.get(key, frappe._dict())
        age = ages.get(key); inward = inwards.get(key, frappe._dict())
        physical = flt(b.actual_qty, 6)
        metrics = movement_metrics(movement.get("gross_qty"), movement.get("returned_qty"), physical)
        role = role_map.get(key[1]) if cint(p.get("is_sellable")) else None
        sellable, blockers, availability_error = _availability_context(item_code=key[0], branch=branch, warehouse=key[1], role=role, as_of_date=today)
        if availability_error:
            warnings.add(_("Availability could not be resolved for Item {0}, Warehouse {1}.").format(key[0], key[1]))

        average_age = age.get("average_age_days") if age else None
        movement_status = classify_movement(
            net_movement_qty=metrics["net_movement_qty"], average_stock_age_days=average_age,
            minimum_stock_age_days=min_age, maximum_movement_qty=max_move,
            warehouse_is_sellable=bool(cint(p.get("is_sellable"))), sellable_qty=sellable,
        )
        if status and movement_status != status:
            continue

        price = flt(_item_customer_price(key[0]), 6)
        retail_exposure = flt(physical * price, 6) if price > 0 else None
        if price <= 0:
            warnings.add(_("Retail price is unresolved for Item {0}.").format(key[0]))

        valuation = flt(b.valuation_rate, 6) or flt(_bin_valuation_rate(key[0], key[1]), 6)
        cost_exposure = flt(physical * valuation, 6) if valuation > 0 else None
        if valuation <= 0:
            warnings.add(_("Valuation is unresolved for Item {0}, Warehouse {1}.").format(key[0], key[1]))

        last_sale = last_sales.get(key, "")
        if _clean(b.stock_uom).lower() != "box":
            warnings.add(_("Item {0} uses Stock UOM {1}; current production catalog contract expects Box.").format(key[0], _clean(b.stock_uom)))

        rows.append({
            "branch": branch, "warehouse": key[1], "warehouse_operational_class": _clean(p.get("operational_class")),
            "warehouse_is_sellable": cint(p.get("is_sellable")), "sellable_role": role or "",
            "item_code": key[0], "item_name": _clean(b.item_name), "item_group": _clean(b.item_group),
            "stock_uom": _clean(b.stock_uom), "pack_size": cint(b.get("custom_pack_size") or 0),
            "subunit_uom": _clean(b.get("custom_uom_options")), "package_definition": _package_definition(b),
            "physical_qty": physical, "sellable_qty": flt(sellable, 6), "availability_blockers": blockers,
            **metrics,
            "last_sale_date": last_sale or None,
            "days_since_last_sale": date_diff(today, getdate(last_sale)) if last_sale else None,
            "last_sale_in_window": _clean(movement.get("last_sale_date")) or None,
            "average_stock_age_days": average_age,
            "oldest_remaining_stock_age_days": age.get("oldest_remaining_age_days") if age else None,
            "youngest_remaining_stock_age_days": age.get("youngest_remaining_age_days") if age else None,
            "last_inward_date": _clean(inward.get("last_inward_date")) or None,
            "last_purchase_receipt_date": _clean(inward.get("last_purchase_receipt_date")) or None,
            "retail_price": price if price > 0 else None,
            "retail_price_source": "Item Current Customer Price" if price > 0 else "Unresolved",
            "retail_exposure": retail_exposure,
            "valuation_rate": valuation if valuation > 0 else None,
            "valuation_source": "ERPNext Bin / Item Valuation",
            "cost_exposure": cost_exposure, "movement_status": movement_status,
        })

    rows.sort(key=lambda r: (
        STATUS_ORDER.get(r["movement_status"], 99),
        -flt(r.get("average_stock_age_days") or 0),
        flt(r.get("net_movement_qty") or 0),
        -flt(r.get("physical_qty") or 0),
        r["item_code"], r["warehouse"],
    ))
    return {
        "contract_version": CONTRACT_VERSION, "mode": MODE, "company": company,
        "currency": _clean(frappe.db.get_value("Company", company, "default_currency")),
        "as_of_date": cstr(today), "summary": _summarize(rows), "rows": rows, "warnings": sorted(warnings),
        "filters": {
            "branch": branch, "warehouse": warehouse, "item_group": item_group, "item_code": item_code,
            "lookback_days": lookback, "maximum_movement_qty": max_move, "minimum_stock_age_days": min_age,
            "status": status, "default_scope": "explicit_warehouse" if warehouse else "sellable_warehouses_only",
            "movement_unit": "Stock UOM; production catalog contract = Box",
            "movement_metric": "Net Stock Qty = Gross Sales Stock Qty - Returned Stock Qty",
            "stock_age_metric": "ERPNext FIFO Average Remaining Stock Age",
        },
        "persistent_writes_performed": False,
    }


def get_history(*, item_code: str, warehouse: str, history_type: str, limit=50) -> dict[str, Any]:
    _require_read_access()
    item_code = _clean(item_code); warehouse = _clean(warehouse); history_type = _clean(history_type).lower()
    limit = max(1, min(cint(limit) or 50, 100))
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Select a valid Item."))
    if not warehouse or not frappe.db.exists("Warehouse", warehouse):
        frappe.throw(_("Select a valid Warehouse."))
    if not _can_read_named_doc("Item", item_code):
        frappe.throw(
            _("You are not permitted to read Item {0}.").format(frappe.bold(item_code)),
            frappe.PermissionError,
        )
    if not _can_read_named_doc("Warehouse", warehouse):
        frappe.throw(
            _("You are not permitted to read Warehouse {0}.").format(frappe.bold(warehouse)),
            frappe.PermissionError,
        )

    if history_type == "sales":
        rows = frappe.db.sql(
            """select si.name voucher_no,si.posting_date,si.customer,si.customer_name,si.is_return,
                      sii.qty,sii.uom,sii.stock_qty,sii.stock_uom,sii.conversion_factor
                 from `tabSales Invoice` si join `tabSales Invoice Item` sii on sii.parent=si.name
                where si.docstatus=1 and sii.item_code=%s and sii.warehouse=%s
                order by si.posting_date desc,si.posting_time desc,si.creation desc limit %s""",
            [item_code, warehouse, limit], as_dict=True,
        )
        return {"history_type": "sales", "item_code": item_code, "warehouse": warehouse, "rows": [dict(r) for r in rows], "persistent_writes_performed": False}

    if history_type in {"purchase", "inward", "receipt"}:
        rows = frappe.db.sql(
            """select sle.posting_date,sle.posting_time,sle.voucher_type,sle.voucher_no,sle.actual_qty,
                      sle.qty_after_transaction,sle.valuation_rate,sle.batch_no
                 from `tabStock Ledger Entry` sle
                where sle.is_cancelled=0 and sle.item_code=%s and sle.warehouse=%s and sle.actual_qty>0
                order by sle.posting_date desc,sle.posting_time desc,sle.creation desc limit %s""",
            [item_code, warehouse, limit], as_dict=True,
        )
        return {"history_type": "inward", "item_code": item_code, "warehouse": warehouse, "rows": [dict(r) for r in rows], "persistent_writes_performed": False}

    frappe.throw(_("History Type must be Sales or Purchase / Inward."))
