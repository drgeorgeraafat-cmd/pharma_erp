"""Read-only automated acceptance for v0.9.2 Step2A."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import cint

from pharma_erp.pharma_erp.unified_stock_availability import (
    CONTRACT_VERSION,
    MODE,
    SELLABLE_ROLES,
    get_unified_stock_availability,
)


COUNT_DOCTYPES = (
    "Branch",
    "Pharmacy Branch Profile",
    "Pharmacy Warehouse Profile",
    "Pharmacy Branch Warehouse Role",
    "Item",
    "Bin",
    "Batch",
    "Stock Reservation Entry",
    "Material Request",
    "Stock Entry",
    "Online Order",
    "Sales Invoice",
)

NON_NEGATIVE_KEYS = (
    "physical_qty",
    "item_sellable_qty",
    "source_physical_qty",
    "source_sellable_qty",
    "blocked_qty",
    "item_reserved_qty",
    "source_reserved_qty",
    "safety_floor",
    "approved_unissued_transfer_qty",
    "item_after_reservation_qty",
    "item_available_to_promise",
    "source_after_reservation_qty",
    "available_to_promise",
    "transferable_surplus",
)


def _exists(doctype: str) -> bool:
    return bool(frappe.db.exists("DocType", doctype))


def _snapshot_counts() -> dict[str, int]:
    return {
        doctype: frappe.db.count(doctype)
        for doctype in COUNT_DOCTYPES
        if _exists(doctype)
    }


def _check_result(result: dict[str, Any], label: str, failures: list[str]) -> None:
    if result.get("contract_version") != CONTRACT_VERSION:
        failures.append(f"{label}: contract version mismatch")
    if result.get("mode") != MODE:
        failures.append(f"{label}: mode is not shadow_read_only")
    quantities = result.get("quantities") or {}
    for key in NON_NEGATIVE_KEYS:
        value = quantities.get(key)
        if value is None or value < 0:
            failures.append(f"{label}: {key} is missing or negative")
    if quantities.get("item_sellable_qty", 0) > quantities.get("physical_qty", 0):
        failures.append(f"{label}: item sellable quantity exceeds physical quantity")
    if quantities.get("available_to_promise", 0) > quantities.get("item_sellable_qty", 0):
        failures.append(f"{label}: ATP exceeds item sellable quantity")
    if quantities.get("available_to_promise", 0) > quantities.get("source_sellable_qty", 0):
        failures.append(f"{label}: ATP exceeds source sellable quantity")
    if quantities.get("transferable_surplus", 0) > quantities.get("available_to_promise", 0):
        failures.append(f"{label}: transferable surplus exceeds ATP")
    states = result.get("states") or {}
    if states.get("projected_included_in_atp") is not False:
        failures.append(f"{label}: projected quantity entered ATP")
    if states.get("transit_included_in_atp") is not False:
        failures.append(f"{label}: transit quantity entered ATP")
    if states.get("persistent_writes_performed") is not False:
        failures.append(f"{label}: service reported a persistent write")


def _sellable_mappings() -> list[frappe._dict]:
    profiles = frappe.get_all(
        "Pharmacy Branch Profile",
        filters={"disabled": 0},
        fields=["name", "branch"],
        order_by="name asc",
    )
    rows = []
    for profile in profiles:
        for mapping in frappe.get_all(
            "Pharmacy Branch Warehouse Role",
            filters={
                "parent": profile.name,
                "parenttype": "Pharmacy Branch Profile",
                "operational_role": ("in", sorted(SELLABLE_ROLES)),
            },
            fields=["operational_role", "warehouse"],
            order_by="idx asc, name asc",
        ):
            rows.append(
                frappe._dict(
                    branch=profile.branch,
                    branch_profile=profile.name,
                    operational_role=mapping.operational_role,
                    warehouse=mapping.warehouse,
                )
            )
    return rows


def run(limit: int = 100) -> dict[str, Any]:
    """Execute a bounded shadow comparison without changing persistent state."""

    limit = max(1, min(cint(limit) or 100, 500))
    counts_before = _snapshot_counts()
    failures: list[str] = []
    comparison_rows = []
    mapping_rows = _sellable_mappings()

    if not mapping_rows:
        failures.append("No canonical sellable Branch/Warehouse mappings were found")

    evaluated = 0
    for mapping in mapping_rows:
        bin_rows = frappe.get_all(
            "Bin",
            filters={"warehouse": mapping.warehouse},
            fields=["item_code", "actual_qty", "projected_qty"],
            order_by="item_code asc",
            limit_page_length=limit,
        )
        for bin_row in bin_rows:
            label = f"{mapping.branch}/{mapping.operational_role}/{bin_row.item_code}"
            try:
                result = get_unified_stock_availability(
                    item_code=bin_row.item_code,
                    branch=mapping.branch,
                    operational_role=mapping.operational_role,
                    warehouse=mapping.warehouse,
                    enforce_permissions=True,
                )
                _check_result(result, label, failures)
                comparison_rows.append(
                    {
                        "branch": mapping.branch,
                        "role": mapping.operational_role,
                        "warehouse": mapping.warehouse,
                        "item_code": bin_row.item_code,
                        "source_type": "stock",
                        "legacy_actual_qty": result["shadow_comparison"]["legacy_bin_actual_qty"],
                        "unified_atp": result["quantities"]["available_to_promise"],
                        "delta": result["shadow_comparison"]["delta_vs_legacy_actual"],
                        "blocked_qty": result["quantities"]["blocked_qty"],
                        "reserved_qty": result["quantities"]["item_reserved_qty"],
                        "safety_floor": result["quantities"]["safety_floor"],
                        "projected_qty": result["quantities"]["projected_qty"],
                        "transit_state": result["states"]["transit_attribution"],
                    }
                )
                evaluated += 1
            except Exception as exc:
                failures.append(f"{label}: {type(exc).__name__}: {exc}")

    if _exists("Internal Retail Price Lot"):
        lots = frappe.get_all(
            "Internal Retail Price Lot",
            filters={"disabled": 0, "available_qty": (">", 0)},
            fields=["name", "item_code", "warehouse"],
            order_by="name asc",
            limit_page_length=limit,
        )
        for lot in lots:
            warehouse_profile = frappe.db.get_value(
                "Pharmacy Warehouse Profile",
                {"warehouse": lot.warehouse, "disabled": 0},
                ["branch", "is_sellable"],
                as_dict=True,
            )
            if not warehouse_profile or not cint(warehouse_profile.is_sellable):
                continue
            role = next(
                (
                    row.operational_role
                    for row in mapping_rows
                    if row.branch == warehouse_profile.branch and row.warehouse == lot.warehouse
                ),
                None,
            )
            if not role:
                continue
            label = f"retail_lot/{lot.name}"
            try:
                result = get_unified_stock_availability(
                    item_code=lot.item_code,
                    branch=warehouse_profile.branch,
                    operational_role=role,
                    warehouse=lot.warehouse,
                    source_type="retail_lot",
                    source_name=lot.name,
                    enforce_permissions=True,
                )
                _check_result(result, label, failures)
                comparison_rows.append(
                    {
                        "branch": warehouse_profile.branch,
                        "role": role,
                        "warehouse": lot.warehouse,
                        "item_code": lot.item_code,
                        "source_type": "retail_lot",
                        "source_name": lot.name,
                        "legacy_actual_qty": result["shadow_comparison"]["legacy_bin_actual_qty"],
                        "unified_atp": result["quantities"]["available_to_promise"],
                        "delta": result["shadow_comparison"]["delta_vs_legacy_actual"],
                    }
                )
                evaluated += 1
            except Exception as exc:
                failures.append(f"{label}: {type(exc).__name__}: {exc}")

    counts_after = _snapshot_counts()
    if counts_before != counts_after:
        failures.append("Business/configuration counters changed during shadow verification")

    report = {
        "contract_version": CONTRACT_VERSION,
        "mode": MODE,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "warnings": [],
        "canonical_mappings_evaluated": len(mapping_rows),
        "availability_rows_evaluated": evaluated,
        "divergent_from_legacy_actual": sum(
            1 for row in comparison_rows if row.get("delta") not in (None, 0, 0.0)
        ),
        "counts_before": counts_before,
        "counts_after": counts_after,
        "comparison_rows": comparison_rows,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))
    return report
