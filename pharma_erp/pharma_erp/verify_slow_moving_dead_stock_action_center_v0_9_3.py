from __future__ import annotations

from frappe.utils import cint, flt

from pharma_erp.pharma_erp.slow_moving_dead_stock_service import get_action_center, get_bootstrap


def execute() -> dict:
    bootstrap = get_bootstrap()
    branch = bootstrap.get("selected_branch")
    if not branch:
        branches = bootstrap.get("branches") or []
        branch = branches[0] if branches else None
    if not branch:
        raise AssertionError("No readable Branch is available.")

    result = get_action_center(
        branch=branch,
        warehouse="",
        lookback_days=30,
        maximum_movement_qty=2,
        minimum_stock_age_days=60,
    )
    if result.get("persistent_writes_performed") is not False:
        raise AssertionError("Action Center must report persistent_writes_performed=False.")

    for row in result.get("rows") or []:
        if not cint(row.get("warehouse_is_sellable")):
            raise AssertionError("Default blank-Warehouse scope returned a non-sellable warehouse.")
        if flt(row.get("physical_qty")) <= 0:
            raise AssertionError("Action Center returned non-positive physical stock.")
        expected_net = flt(row.get("gross_movement_qty")) - flt(row.get("returned_movement_qty"))
        if abs(expected_net - flt(row.get("net_movement_qty"))) > 0.000001:
            raise AssertionError("Net movement does not equal Gross - Returns.")

    return {
        "status": "PASS",
        "branch": branch,
        "rows": len(result.get("rows") or []),
        "default_scope": (result.get("filters") or {}).get("default_scope"),
        "persistent_writes_performed": False,
    }
