from __future__ import annotations

import hashlib
import json

import frappe
from frappe.utils import flt, getdate, nowdate

from pharma_erp.pharma_erp.near_expiry_service import (
    EPSILON,
    _physical_batch_qty,
    get_bootstrap,
    get_near_expiry_action_center,
)


def _fingerprint() -> str:
    rows = []
    checks = [
        ("Batch", "SELECT COUNT(*), COALESCE(MAX(modified), '') FROM `tabBatch`"),
        (
            "Stock Ledger Entry",
            "SELECT COUNT(*), COALESCE(MAX(creation), ''), COALESCE(SUM(actual_qty), 0), COALESCE(SUM(stock_value_difference), 0) FROM `tabStock Ledger Entry`",
        ),
        ("Bin", "SELECT COUNT(*), COALESCE(MAX(modified), ''), COALESCE(SUM(actual_qty), 0) FROM `tabBin`"),
        (
            "Stock Reconciliation",
            "SELECT COUNT(*), COALESCE(MAX(modified), '') FROM `tabStock Reconciliation`",
        ),
    ]
    for label, sql in checks:
        value = frappe.db.sql(sql)[0]
        rows.append([label, *value])
    raw = json.dumps(rows, default=str, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _expired_physical_candidates(bootstrap: dict) -> list[tuple[str, str, str]]:
    """Find readable active expired Batches that still have physical stock."""

    warehouses = [row.get("warehouse") for row in (bootstrap.get("warehouses") or []) if row.get("warehouse")]
    if not warehouses:
        return []

    expired = frappe.get_list(
        "Batch",
        filters={"disabled": 0, "expiry_date": ("<", getdate(nowdate()))},
        fields=["name", "item"],
        order_by="expiry_date asc, name asc",
        limit_page_length=5000,
    )
    candidates = []
    for raw in expired:
        for warehouse in warehouses:
            if flt(_physical_batch_qty(raw.item, warehouse, raw.name), 6) > EPSILON:
                candidates.append((warehouse, raw.item, raw.name))
    return candidates



def run():
    before = _fingerprint()
    bootstrap = get_bootstrap()
    branches = bootstrap.get("branches") or []
    if not branches:
        raise AssertionError("No readable Branch is available for Near Expiry verification.")

    branch = bootstrap.get("selected_branch") or branches[0]
    branch_bootstrap = get_bootstrap(branch=branch)
    expired_physical = _expired_physical_candidates(branch_bootstrap)

    result = get_near_expiry_action_center(
        branch=branch,
        horizon_days=bootstrap.get("default_horizon_days") or 180,
        critical_days=bootstrap.get("default_critical_days") or 30,
        urgent_days=bootstrap.get("default_urgent_days") or 60,
    )

    if result.get("persistent_writes_performed") is not False:
        raise AssertionError("Near Expiry service must declare persistent_writes_performed=False.")

    seen = set()
    for row in result.get("rows") or []:
        key = (row.get("branch"), row.get("warehouse"), row.get("item_code"), row.get("batch_no"))
        if key in seen:
            raise AssertionError(f"Duplicate Near Expiry row: {key}")
        seen.add(key)

        if flt(row.get("physical_qty"), 6) <= EPSILON:
            raise AssertionError(f"Non-positive physical quantity surfaced: {key}")
        if not row.get("expiry_date"):
            raise AssertionError(f"Missing expiry date surfaced: {key}")
        if row.get("expiry_status") == "Safe":
            raise AssertionError(f"Safe row leaked into Near Expiry result: {key}")
        if row.get("expiry_status") == "Expired" and flt(row.get("sellable_qty"), 6) > EPSILON:
            raise AssertionError(f"Expired Batch is sellable: {key}")

        if row.get("retail_exposure") is not None:
            expected = flt(flt(row.get("physical_qty"), 6) * flt(row.get("retail_price"), 6), 6)
            if abs(expected - flt(row.get("retail_exposure"), 6)) > 0.000001:
                raise AssertionError(f"Retail exposure mismatch: {key}")

        if row.get("at_risk_cost") is not None:
            expected = flt(flt(row.get("physical_qty"), 6) * flt(row.get("valuation_rate"), 6), 6)
            if abs(expected - flt(row.get("at_risk_cost"), 6)) > 0.000001:
                raise AssertionError(f"At-risk cost mismatch: {key}")

    row_keys = {
        (row.get("warehouse"), row.get("item_code"), row.get("batch_no"))
        for row in (result.get("rows") or [])
    }
    missing_expired = [key for key in expired_physical if key not in row_keys]
    if missing_expired:
        raise AssertionError(
            "Expired Batches with positive physical stock are missing from Near Expiry: "
            + repr(missing_expired[:20])
        )

    after = _fingerprint()
    if before != after:
        raise AssertionError("DB stock fingerprint changed during read-only Near Expiry verification.")

    return {
        "result": "PASS",
        "contract_version": result.get("contract_version"),
        "branch": branch,
        "rows": len(result.get("rows") or []),
        "expired_physical_candidates": len(expired_physical),
        "expired_rows_verified": len(expired_physical),
        "warnings": result.get("warnings") or [],
        "db_non_mutation": "PASS",
        "db_fingerprint": before,
    }
