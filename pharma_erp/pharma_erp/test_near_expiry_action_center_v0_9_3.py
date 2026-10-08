from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import frappe

from pharma_erp.pharma_erp import near_expiry_service as service

from pharma_erp.pharma_erp.near_expiry_service import (
    _normalize_thresholds,
    _physical_batch_qty,
    _summarize,
    classify_expiry,
)


class TestNearExpiryActionCenterV093(unittest.TestCase):
    AS_OF = "2026-10-07"

    def classify(self, expiry, horizon=180, critical=30, urgent=60):
        return classify_expiry(
            expiry,
            as_of_date=self.AS_OF,
            horizon_days=horizon,
            critical_days=critical,
            urgent_days=urgent,
        )

    def test_expired(self):
        result = self.classify("2026-10-06")
        self.assertEqual(result["status"], "Expired")
        self.assertEqual(result["days_remaining"], -1)

    def test_zero_and_critical_boundary(self):
        self.assertEqual(self.classify("2026-10-07")["status"], "Critical")
        self.assertEqual(self.classify("2026-11-06")["status"], "Critical")

    def test_urgent_boundary(self):
        self.assertEqual(self.classify("2026-11-07")["status"], "Urgent")
        self.assertEqual(self.classify("2026-12-06")["status"], "Urgent")

    def test_near_expiry_boundary(self):
        self.assertEqual(self.classify("2026-12-07")["status"], "Near Expiry")
        self.assertEqual(self.classify("2027-04-05")["status"], "Near Expiry")

    def test_outside_horizon_is_safe(self):
        self.assertEqual(self.classify("2027-04-06")["status"], "Safe")

    def test_missing_expiry(self):
        result = self.classify(None)
        self.assertEqual(result["status"], "No Expiry")
        self.assertIsNone(result["days_remaining"])

    def test_thresholds_are_clamped_to_horizon(self):
        horizon, critical, urgent = _normalize_thresholds(
            horizon_days=20,
            critical_days=30,
            urgent_days=60,
        )
        self.assertEqual((horizon, critical, urgent), (20, 20, 20))

    @patch("erpnext.stock.doctype.batch.batch.get_batch_qty")
    def test_physical_batch_qty_includes_expired_and_ignores_reservations(self, get_batch_qty):
        get_batch_qty.return_value = 9

        qty = _physical_batch_qty("10003", "Stores - C", "12312")

        self.assertEqual(qty, 9)
        get_batch_qty.assert_called_once_with(
            batch_no="12312",
            warehouse="Stores - C",
            item_code="10003",
            for_stock_levels=True,
            ignore_reserved_stock=True,
        )

    def test_action_center_surfaces_expired_physical_stock_without_shared_snapshot_row(self):
        branch = "R5F1 Branch"
        warehouse = "R5F1 Stores"
        item_code = "10003"
        batch_no = "R5F1-EXP"
        candidate = frappe._dict(
            name=batch_no,
            item=item_code,
            expiry_date="2026-10-06",
            disabled=0,
        )
        item = frappe._dict(
            name=item_code,
            item_name="Panadol Advance",
            item_group="Analgesics",
            stock_uom="Nos",
            disabled=0,
            is_stock_item=1,
            has_batch_no=1,
        )
        profile = frappe._dict(
            warehouse=warehouse,
            branch=branch,
            operational_class="General",
            is_sellable=1,
        )
        price = frappe._dict(
            customer_price=100,
            price_integrity_error=0,
            price_source="Printed Batch Price",
        )

        with (
            patch.object(service, "_require_read_access", lambda: None),
            patch.object(service, "_default_company", lambda: "Cure"),
            patch.object(service, "_visible_branch_names", lambda company: [branch]),
            patch.object(service, "_normalize_thresholds", lambda **kwargs: (182, 30, 60)),
            patch.object(service, "_visible_warehouse_profiles", lambda *args, **kwargs: [profile]),
            patch.object(service, "_paged_candidate_batches", lambda **kwargs: [candidate]),
            patch.object(service, "_item_meta_map", lambda codes: {item_code: item}),
            patch.object(service, "_allowed_item_groups", lambda value: None),
            patch.object(service, "_sellable_role_map", lambda company, branches: {(branch, warehouse): "Sales"}),
            patch.object(service, "get_batch_system_snapshot", lambda *args, **kwargs: []),
            patch.object(service, "_physical_batch_qty", lambda *args, **kwargs: 9),
            patch.object(service, "_item_customer_price", lambda code: 0),
            patch.object(service, "_valuation_context", lambda *args, **kwargs: (90.196078, "ERPNext Bin Valuation Rate")),
            patch.object(service, "_availability_context", lambda **kwargs: (0, ["batch_expired"], None)),
            patch.object(service, "_batch_price_context", lambda *args, **kwargs: price),
            patch.object(service.frappe.db, "get_value", lambda *args, **kwargs: "EGP"),
        ):
            result = service.get_near_expiry_action_center(
                branch=branch,
                horizon_days=182,
                critical_days=30,
                urgent_days=60,
                as_of_date=self.AS_OF,
            )

        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual(row["batch_no"], batch_no)
        self.assertEqual(row["expiry_status"], "Expired")
        self.assertEqual(row["days_remaining"], -1)
        self.assertEqual(row["physical_qty"], 9)
        self.assertEqual(row["sellable_qty"], 0)
        self.assertIn("batch_expired", row["availability_blockers"])
        self.assertEqual(row["retail_exposure"], 900)

    def test_summary_counts_unique_batches_but_sums_locations(self):
        rows = [
            {
                "expiry_status": "Expired",
                "batch_no": "B-001",
                "physical_qty": 2,
                "retail_exposure": 20,
                "at_risk_cost": 12,
            },
            {
                "expiry_status": "Expired",
                "batch_no": "B-001",
                "physical_qty": 3,
                "retail_exposure": 30,
                "at_risk_cost": 18,
            },
        ]
        summary = _summarize(rows)
        self.assertEqual(summary["rows"], 2)
        self.assertEqual(summary["expired_batches"], 1)
        self.assertEqual(summary["physical_qty_at_risk"], 5)
        self.assertEqual(summary["retail_exposure"], 50)
        self.assertEqual(summary["at_risk_cost"], 30)


def run():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestNearExpiryActionCenterV093)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("Near Expiry R5-F1 unit regression failure:\n" + stream.getvalue())
    return {
        "status": "PASS",
        "tests_run": result.testsRun,
        "expired_physical_stock_semantics": "PASS",
    }


if __name__ == "__main__":
    unittest.main()
