from __future__ import annotations

import unittest

from pharma_erp.pharma_erp.slow_moving_dead_stock_service import classify_movement, movement_metrics


class TestSlowMovingDeadStockActionCenter(unittest.TestCase):
    def test_package_movement_math(self):
        metrics = movement_metrics(3, 1, 50)
        self.assertEqual(metrics["gross_movement_qty"], 3)
        self.assertEqual(metrics["returned_movement_qty"], 1)
        self.assertEqual(metrics["net_movement_qty"], 2)
        self.assertEqual(metrics["movement_ratio_percent"], 4)

    def test_no_movement(self):
        self.assertEqual(classify_movement(
            net_movement_qty=0, average_stock_age_days=90,
            minimum_stock_age_days=60, maximum_movement_qty=2,
            warehouse_is_sellable=True, sellable_qty=10,
        ), "No Movement")

    def test_negative_net_movement_is_unresolved(self):
        self.assertEqual(classify_movement(
            net_movement_qty=-1, average_stock_age_days=90,
            minimum_stock_age_days=60, maximum_movement_qty=2,
            warehouse_is_sellable=True, sellable_qty=10,
        ), "Unresolved")

    def test_low_movement(self):
        self.assertEqual(classify_movement(
            net_movement_qty=2, average_stock_age_days=90,
            minimum_stock_age_days=60, maximum_movement_qty=2,
            warehouse_is_sellable=True, sellable_qty=10,
        ), "Low Movement")

    def test_normal(self):
        self.assertEqual(classify_movement(
            net_movement_qty=3, average_stock_age_days=90,
            minimum_stock_age_days=60, maximum_movement_qty=2,
            warehouse_is_sellable=True, sellable_qty=10,
        ), "Normal")

    def test_recent_stock(self):
        self.assertEqual(classify_movement(
            net_movement_qty=0, average_stock_age_days=20,
            minimum_stock_age_days=60, maximum_movement_qty=2,
            warehouse_is_sellable=True, sellable_qty=10,
        ), "Recent Stock")

    def test_not_sellable(self):
        self.assertEqual(classify_movement(
            net_movement_qty=0, average_stock_age_days=120,
            minimum_stock_age_days=60, maximum_movement_qty=2,
            warehouse_is_sellable=False, sellable_qty=0,
        ), "Not Sellable")

    def test_unresolved_age(self):
        self.assertEqual(classify_movement(
            net_movement_qty=0, average_stock_age_days=None,
            minimum_stock_age_days=60, maximum_movement_qty=2,
            warehouse_is_sellable=True, sellable_qty=10,
        ), "Unresolved")
