from __future__ import annotations

import frappe

from pharma_erp.pharma_erp.near_expiry_service import (
    get_bootstrap as _get_bootstrap,
    get_near_expiry_action_center,
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
    batch_no=None,
    horizon_days=None,
    critical_days=None,
    urgent_days=None,
    status=None,
):
    return get_near_expiry_action_center(
        branch=branch,
        warehouse=warehouse or "",
        item_group=item_group or "",
        item_code=item_code or "",
        batch_no=batch_no or "",
        horizon_days=horizon_days,
        critical_days=critical_days,
        urgent_days=urgent_days,
        status=status or "",
    )
