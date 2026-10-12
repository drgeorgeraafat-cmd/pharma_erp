from __future__ import annotations

import frappe

from pharma_erp.pharma_erp.slow_moving_dead_stock_service import (
    get_action_center as _get_action_center,
    get_bootstrap as _get_bootstrap,
    get_history as _get_history,
)


@frappe.whitelist()
def get_bootstrap(branch=None):
    return _get_bootstrap(branch=branch)


@frappe.whitelist()
def get_action_center(
    branch,
    warehouse=None,
    item_group=None,
    item_code=None,
    lookback_days=None,
    maximum_movement_qty=None,
    minimum_stock_age_days=None,
    status=None,
):
    return _get_action_center(
        branch=branch,
        warehouse=warehouse or "",
        item_group=item_group or "",
        item_code=item_code or "",
        lookback_days=lookback_days,
        maximum_movement_qty=maximum_movement_qty,
        minimum_stock_age_days=minimum_stock_age_days,
        status=status or "",
    )


@frappe.whitelist()
def get_history(item_code, warehouse, history_type, limit=50):
    return _get_history(
        item_code=item_code,
        warehouse=warehouse,
        history_type=history_type,
        limit=limit,
    )
