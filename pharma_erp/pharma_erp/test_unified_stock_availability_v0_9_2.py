from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
