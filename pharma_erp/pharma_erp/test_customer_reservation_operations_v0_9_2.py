from __future__ import annotations

import unittest

from pharma_erp.pharma_erp.customer_reservation_contract import (
    build_request_key,
    derive_operational_status,
    locked_reservation_pricing,
    validate_contact_outcome,
    validate_locked_reservation_price,
    validate_reserved_fulfilment_qty,
    weighted_source_price,
)


class TestCustomerReservationOperationsContract(unittest.TestCase):
    def test_review_due_does_not_release_stock(self):
        self.assertEqual(
            derive_operational_status(
                reserved_qty=1,
                delivered_qty=0,
                reservation_docstatus=1,
                reservation_contract_state="Active",
                review_due=True,
                fulfilment_mode="Pickup",
            ),
            "Review Required",
        )

    def test_partial_and_complete_fulfilment_mapping(self):
        self.assertEqual(
            derive_operational_status(
                reserved_qty=2,
                delivered_qty=1,
                reservation_docstatus=1,
            ),
            "Partially Fulfilled",
        )
        self.assertEqual(
            derive_operational_status(
                reserved_qty=2,
                delivered_qty=2,
                reservation_docstatus=1,
                fulfilment_mode="Pickup",
            ),
            "Picked Up",
        )
        self.assertEqual(
            derive_operational_status(
                reserved_qty=2,
                delivered_qty=2,
                reservation_docstatus=1,
                fulfilment_mode="Home Delivery",
            ),
            "Sent for Delivery",
        )

    def test_terminal_standard_state_is_preserved(self):
        self.assertEqual(
            derive_operational_status(
                reserved_qty=1,
                delivered_qty=0,
                reservation_docstatus=2,
                reservation_contract_state="Released",
            ),
            "Released",
        )

    def test_fulfilment_cannot_exceed_remaining_reservation(self):
        self.assertEqual(
            validate_reserved_fulfilment_qty(requested_qty=1, remaining_reserved_qty=2),
            1,
        )
        with self.assertRaises(ValueError):
            validate_reserved_fulfilment_qty(requested_qty=3, remaining_reserved_qty=2)

    def test_contact_outcomes_are_bounded(self):
        self.assertEqual(validate_contact_outcome("Still Needed"), "Still Needed")
        with self.assertRaises(ValueError):
            validate_contact_outcome("Auto Release")

    def test_reservation_price_is_locked_to_sales_order_item(self):
        locked = locked_reservation_pricing(
            price_list_rate=220,
            rate=220,
            discount_percentage=0,
        )
        self.assertEqual(locked["rate"], 220)
        self.assertEqual(
            validate_locked_reservation_price(
                locked_price_list_rate=220,
                locked_rate=220,
                locked_discount_percentage=0,
                invoice_price_list_rate=220,
                invoice_rate=220,
                invoice_discount_percentage=0,
            ),
            locked,
        )
        with self.assertRaises(ValueError):
            validate_locked_reservation_price(
                locked_price_list_rate=220,
                locked_rate=220,
                locked_discount_percentage=0,
                invoice_price_list_rate=300,
                invoice_rate=300,
                invoice_discount_percentage=0,
            )

    def test_weighted_pos_source_price(self):
        self.assertEqual(
            weighted_source_price(
                [
                    {"qty": 1, "customer_price": 300},
                    {"qty": 2, "customer_price": 380},
                ]
            ),
            round(1060 / 3, 6),
        )
        with self.assertRaises(ValueError):
            weighted_source_price([])

    def test_request_key_is_idempotent_and_scoped(self):
        first = build_request_key(
            customer="CUST-1",
            item_code="ITEM-1",
            branch="Main Branch",
            request_token="abc",
        )
        second = build_request_key(
            customer="CUST-1",
            item_code="ITEM-1",
            branch="Main Branch",
            request_token="abc",
        )
        other = build_request_key(
            customer="CUST-1",
            item_code="ITEM-1",
            branch="Main Branch",
            request_token="xyz",
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)


if __name__ == "__main__":
    unittest.main()
