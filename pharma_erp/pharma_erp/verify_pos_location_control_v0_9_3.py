from __future__ import annotations

import json

import frappe
from frappe.utils import flt

from pharma_erp.pharma_erp.location_service import get_allocated_qty
from pharma_erp.pharma_erp.pos_location_control import (
    ENABLE_FIELD,
    SETTINGS_DOCTYPE,
    _consume_controlled_item,
    build_pos_location_plan,
    replenish_pos_locations,
    reverse_pos_consumption_before_cancel,
)


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _location_for_code(code):
    return frappe.db.get_value(
        "Pharmacy Storage Location",
        {"warehouse": "Stores - C", "location_code": code, "disabled": 0},
        "name",
    )


def run():
    savepoint = "step2b_pos_location_verify"
    frappe.db.savepoint(savepoint)
    report = {"status": "FAIL", "checks": []}

    try:
        frappe.db.set_single_value(
            SETTINGS_DOCTYPE,
            ENABLE_FIELD,
            0,
            update_modified=False,
        )
        off_plan = build_pos_location_plan(
            {"warehouse": "Stores - C", "items": [{"item_code": "000001", "qty": 2}]}
        )
        _assert(not off_plan["enabled"], "Feature OFF must use legacy mode.")
        report["checks"].append("feature_off_legacy_all_items")

        selling = _location_for_code("A-01")
        reserve = _location_for_code("S")
        _assert(selling and reserve, "Expected Step2A A-01 and S locations.")

        selling_before = flt(get_allocated_qty("000001", "Stores - C", None, selling), 6)
        reserve_before = flt(get_allocated_qty("000001", "Stores - C", None, reserve), 6)
        _assert(abs(selling_before - 1.0) < 1e-9, f"Expected Selling qty 1, got {selling_before}")
        _assert(abs(reserve_before - 1.0) < 1e-9, f"Expected Reserve qty 1, got {reserve_before}")

        frappe.db.set_single_value(
            SETTINGS_DOCTYPE,
            ENABLE_FIELD,
            1,
            update_modified=False,
        )

        legacy_rows = frappe.db.sql(
            """
            SELECT i.name
            FROM `tabItem` i
            WHERE i.disabled=0
              AND i.is_stock_item=1
              AND i.name <> '000001'
              AND NOT EXISTS (
                  SELECT 1
                  FROM `tabPharmacy Item Location Rule` r
                  WHERE r.disabled=0
                    AND r.warehouse='Stores - C'
                    AND r.item_code=i.name
              )
            ORDER BY i.name
            LIMIT 20
            """,
            as_dict=True,
        )
        legacy_code = None
        for candidate in legacy_rows:
            plan = build_pos_location_plan(
                {
                    "warehouse": "Stores - C",
                    "items": [{"item_code": candidate.name, "qty": 0.001}],
                }
            )
            if candidate.name in plan.get("legacy_items", []):
                legacy_code = candidate.name
                _assert(not plan["blocking"], "No-rule legacy item must not be location-blocked.")
                break
        _assert(legacy_code, "No stock Item without Location Rule is available for legacy test.")
        report["checks"].append("no_rule_item_legacy_behavior")

        qty1 = build_pos_location_plan(
            {"warehouse": "Stores - C", "items": [{"item_code": "000001", "qty": 1}]}
        )
        _assert(qty1["rows"], "Controlled item produced no plan row.")
        row1 = qty1["rows"][0]
        _assert(row1["status"] == "ready", f"Qty1 expected ready, got {row1['status']}")
        report["checks"].append("selling_location_ready")

        payload = {
            "warehouse": "Stores - C",
            "location_request_key": "STEP2B-AUTO-VERIFY",
            "items": [{"item_code": "000001", "qty": 2}],
        }
        qty2 = build_pos_location_plan(payload)
        _assert(qty2["rows"], "Qty2 produced no controlled plan row.")
        row2 = qty2["rows"][0]
        _assert(
            row2["status"] == "replenish_required",
            f"Qty2 expected replenishment, got {row2['status']}",
        )
        _assert(abs(flt(row2["shortage_qty"]) - 1.0) < 1e-9, "Expected replenish shortage = 1.")
        report["checks"].append("reserve_replenishment_plan")

        replenished = replenish_pos_locations(json.dumps(payload))
        _assert(not replenished["requires_replenishment"], "Replenishment did not make cart ready.")
        selling_after_replenish = flt(get_allocated_qty("000001", "Stores - C", None, selling), 6)
        reserve_after_replenish = flt(get_allocated_qty("000001", "Stores - C", None, reserve), 6)
        _assert(abs(selling_after_replenish - 2.0) < 1e-9, "Selling qty did not become 2.")
        _assert(abs(reserve_after_replenish - 0.0) < 1e-9, "Reserve qty did not become 0.")
        report["checks"].append("internal_replenishment_movement")

        repeated = replenish_pos_locations(json.dumps(payload))
        _assert(not repeated.get("movements"), "Repeated ready request unexpectedly moved stock.")
        report["checks"].append("replenishment_retry_safe")

        reference_invoice = frappe.db.get_value(
            "Sales Invoice",
            {"docstatus": 1, "is_pos": 1},
            "name",
            order_by="modified desc",
        )
        _assert(reference_invoice, "No submitted POS invoice exists for transactional reference.")

        consumed = _consume_controlled_item(
            invoice_name=reference_invoice,
            reference_row="STEP2B-VERIFY-ROW",
            warehouse="Stores - C",
            item_code="000001",
            qty=2,
            batch_no="",
        )
        _assert(consumed.get("controlled"), "Expected controlled POS consumption.")
        selling_after_consume = flt(get_allocated_qty("000001", "Stores - C", None, selling), 6)
        _assert(abs(selling_after_consume) < 1e-9, "Selling qty did not decrease to 0.")
        report["checks"].append("pos_consumption")

        _consume_controlled_item(
            invoice_name=reference_invoice,
            reference_row="STEP2B-VERIFY-ROW",
            warehouse="Stores - C",
            item_code="000001",
            qty=2,
            batch_no="",
        )
        selling_after_repeat = flt(get_allocated_qty("000001", "Stores - C", None, selling), 6)
        _assert(abs(selling_after_repeat) < 1e-9, "Duplicate consumption changed balance.")
        report["checks"].append("pos_consumption_dedupe")

        reverse_pos_consumption_before_cancel(frappe._dict(name=reference_invoice))
        selling_after_reverse = flt(get_allocated_qty("000001", "Stores - C", None, selling), 6)
        _assert(abs(selling_after_reverse - 2.0) < 1e-9, "Cancellation reversal did not restore Selling qty.")
        report["checks"].append("cancel_reversal")

        report["status"] = "PASS"
        report["legacy_item"] = legacy_code
        report["selling_location"] = selling
        report["reserve_location"] = reserve
        report["location_batch_mode"] = row2.get("location_batch_mode")
        report["transaction_rolled_back"] = True
        return report
    finally:
        frappe.db.rollback(save_point=savepoint)
