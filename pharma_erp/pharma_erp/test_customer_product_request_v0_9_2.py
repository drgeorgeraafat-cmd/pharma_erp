from __future__ import annotations

import unittest
from pathlib import Path

from pharma_erp.pharma_erp.customer_product_request_contract import (
    CONTRACT_VERSION,
    aggregate_status,
    fifo_allocate,
    positive_qty,
    stable_match_key,
    stable_request_key,
)


class TestCustomerProductRequestContract(unittest.TestCase):
    def test_r4_hotfix_preserves_r3_stable_key_contract(self):
        self.assertEqual(CONTRACT_VERSION, "v0.9.2-step2d-r3")

    def test_availability_adapter_uses_step2a_canonical_context(self):
        service_source = Path(__file__).with_name("customer_product_request_service.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('result.get("canonical_context")', service_source)
        self.assertIn('canonical_context.get("warehouse")', service_source)
        self.assertNotIn('result["context"]', service_source)

    def test_items_payload_uses_explicit_mapping_key(self):
        service_source = Path(__file__).with_name("customer_product_request_service.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('raw_items = data.get("items")', service_source)
        self.assertNotIn("raw_items = data.items", service_source)

    def test_direct_purchase_invoice_matching_is_bounded_and_deduplicated(self):
        service_source = Path(__file__).with_name("customer_product_request_service.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def on_submit_purchase_invoice_match_requests", service_source)
        self.assertIn('not cint(doc.get("update_stock"))', service_source)
        self.assertIn('cint(doc.get("is_return"))', service_source)
        self.assertIn('row.get("purchase_receipt")', service_source)
        self.assertIn('row.get("pr_detail")', service_source)
        self.assertIn("DIRECT_PURCHASE_INVOICE_SOURCE", service_source)

        hooks_source = (Path(__file__).resolve().parents[1] / "hooks.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '"on_submit_purchase_invoice_match_requests"',
            hooks_source,
        )

        match_json = (
            Path(__file__).with_name("doctype")
            / "customer_product_request_match"
            / "customer_product_request_match.json"
        ).read_text(encoding="utf-8")
        self.assertIn("Purchase Receipt\\nPurchase Invoice\\nManual Review", match_json)

    def test_positive_qty(self):
        self.assertEqual(positive_qty("1.5"), 1.5)
        with self.assertRaises(ValueError):
            positive_qty(0)

    def test_request_and_match_keys_are_stable_and_scoped(self):
        self.assertEqual(
            stable_request_key("CUST-1", "Main", "token"),
            stable_request_key("CUST-1", "Main", "token"),
        )
        self.assertNotEqual(
            stable_request_key("CUST-1", "Main", "token"),
            stable_request_key("CUST-1", "Other", "token"),
        )
        self.assertNotEqual(stable_match_key("REQ-1", "ROW-1"), stable_match_key("REQ-1", "ROW-2"))

    def test_fifo_allocation_never_overcommits_pool(self):
        result = fifo_allocate(
            [
                {"request_item": "older", "remaining_qty": 2},
                {"request_item": "newer", "remaining_qty": 2},
            ],
            3,
        )
        self.assertEqual([row.matched_qty for row in result], [2, 1])
        self.assertEqual(sum(row.matched_qty for row in result), 3)

    def test_parent_status_is_derived_without_creating_reservation(self):
        self.assertEqual(
            aggregate_status([{"match_status": "Waiting", "matched_qty": 0, "remaining_qty": 1}]),
            "Waiting for Stock",
        )
        self.assertEqual(
            aggregate_status([{"match_status": "Available", "matched_qty": 1, "remaining_qty": 1}]),
            "Available for Contact",
        )
        self.assertEqual(
            aggregate_status([{"match_status": "Partially Available", "matched_qty": 1, "remaining_qty": 2}]),
            "Partially Available",
        )


if __name__ == "__main__":
    unittest.main()
