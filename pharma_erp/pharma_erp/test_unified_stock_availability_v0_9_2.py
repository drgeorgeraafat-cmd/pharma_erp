from __future__ import annotations

import io
import json
import sys
import unittest
from datetime import date
from unittest.mock import patch

import frappe

from pharma_erp.pharma_erp import unified_stock_availability as availability
from pharma_erp.pharma_erp.availability_math import (
    compute_availability_metrics,
    normalized_qty,
)


class UnifiedAvailabilityMathTest(unittest.TestCase):
    def test_item_reservation_and_safety_floor_are_subtracted_once(self):
        metrics = compute_availability_metrics(
            item_sellable_qty=100,
            source_sellable_qty=100,
            item_reserved_qty=25,
            source_reserved_qty=25,
            safety_floor=10,
        )
        self.assertEqual(metrics["item_after_reservation_qty"], 75)
        self.assertEqual(metrics["available_to_promise"], 65)

    def test_source_limit_is_stricter_than_item_total(self):
        metrics = compute_availability_metrics(
            item_sellable_qty=100,
            source_sellable_qty=12,
            item_reserved_qty=5,
            source_reserved_qty=2,
            safety_floor=10,
        )
        self.assertEqual(metrics["item_available_to_promise"], 85)
        self.assertEqual(metrics["source_after_reservation_qty"], 10)
        self.assertEqual(metrics["available_to_promise"], 10)

    def test_transfer_commitment_reduces_surplus_not_atp(self):
        metrics = compute_availability_metrics(
            item_sellable_qty=30,
            source_sellable_qty=30,
            approved_unissued_transfer_qty=7,
        )
        self.assertEqual(metrics["available_to_promise"], 30)
        self.assertEqual(metrics["transferable_surplus"], 23)

    def test_quantities_never_become_negative(self):
        metrics = compute_availability_metrics(
            item_sellable_qty=4,
            source_sellable_qty=2,
            item_reserved_qty=10,
            source_reserved_qty=8,
            safety_floor=3,
            approved_unissued_transfer_qty=99,
        )
        self.assertTrue(all(value >= 0 for value in metrics.values()))
        self.assertEqual(metrics["available_to_promise"], 0)
        self.assertEqual(metrics["transferable_surplus"], 0)

    def test_projected_and_transit_cannot_enter_contract_math(self):
        parameters = compute_availability_metrics.__annotations__
        self.assertNotIn("projected_qty", parameters)
        self.assertNotIn("in_transit_qty", parameters)

    def test_normalization_is_stable(self):
        self.assertEqual(normalized_qty(None), 0)
        self.assertEqual(normalized_qty(-1), 0)
        self.assertEqual(normalized_qty("1.23456789"), 1.234568)


class UnifiedAvailabilityExpiredBatchRegressionTest(unittest.TestCase):
    def test_expired_physical_batch_is_supplemented_without_changing_valid_rows(self):
        default_rows = [frappe._dict(batch_no="VALID", qty=5)]
        stock_level_rows = [
            frappe._dict(batch_no="VALID", qty=7),
            frappe._dict(batch_no="EXPIRED", qty=3),
            frappe._dict(batch_no="FUTURE-ONLY", qty=4),
            frappe._dict(batch_no="DISABLED-EXPIRED", qty=2),
        ]
        metadata = [
            frappe._dict(name="VALID", item="ITEM-1", disabled=0, expiry_date=date(2026, 12, 1)),
            frappe._dict(name="EXPIRED", item="ITEM-1", disabled=0, expiry_date=date(2026, 10, 6)),
            frappe._dict(name="FUTURE-ONLY", item="ITEM-1", disabled=0, expiry_date=date(2026, 12, 15)),
            frappe._dict(name="DISABLED-EXPIRED", item="ITEM-1", disabled=1, expiry_date=date(2026, 10, 5)),
        ]

        with (
            patch.object(availability, "get_batch_qty", side_effect=[default_rows, stock_level_rows]) as get_qty,
            patch.object(availability.frappe, "get_all", return_value=metadata),
        ):
            rows = availability._batch_rows(
                "ITEM-1",
                "Stores - TEST",
                sre_rows=[frappe._dict(name="SRE-1")],
                as_of_date=date(2026, 10, 7),
            )

        by_batch = {row.batch_no: row for row in rows}
        self.assertEqual(set(by_batch), {"VALID", "EXPIRED"})
        self.assertEqual(by_batch["VALID"].physical_qty, 5)
        self.assertFalse(by_batch["VALID"].expired)
        self.assertTrue(by_batch["VALID"].sellable)
        self.assertEqual(by_batch["EXPIRED"].physical_qty, 3)
        self.assertTrue(by_batch["EXPIRED"].expired)
        self.assertFalse(by_batch["EXPIRED"].sellable)

        self.assertEqual(get_qty.call_count, 2)
        first_kwargs = get_qty.call_args_list[0].kwargs
        second_kwargs = get_qty.call_args_list[1].kwargs
        self.assertNotIn("for_stock_levels", first_kwargs)
        self.assertEqual(first_kwargs["ignore_voucher_nos"], ["SRE-1"])
        self.assertTrue(second_kwargs["for_stock_levels"])
        self.assertTrue(second_kwargs["ignore_reserved_stock"])
        self.assertEqual(second_kwargs["ignore_voucher_nos"], ["SRE-1"])


def run():
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(UnifiedAvailabilityMathTest))
    suite.addTests(loader.loadTestsFromTestCase(UnifiedAvailabilityExpiredBatchRegressionTest))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("Unified Availability R5-F2B unit regression failure:\n" + stream.getvalue())
    payload = {
        "status": "PASS",
        "tests_run": result.testsRun,
        "expired_batch_semantics": "PASS",
        "non_expired_semantics_preserved": "PASS",
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return payload


if __name__ == "__main__":
    unittest.main()
