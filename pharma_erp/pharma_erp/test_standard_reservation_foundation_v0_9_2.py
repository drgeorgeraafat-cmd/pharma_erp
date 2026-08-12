from __future__ import annotations

import unittest

from pharma_erp.pharma_erp.reservation_contract import (
    build_idempotency_key,
    contract_state,
    remaining_qty,
    reservation_ceiling,
    validate_terminal_state,
)


class TestStandardReservationContract(unittest.TestCase):
    def test_lifecycle_mapping(self):
        self.assertEqual(
            contract_state(docstatus=1, reserved_qty=5, delivered_qty=0),
            "Active",
        )
        self.assertEqual(
            contract_state(docstatus=1, reserved_qty=5, delivered_qty=2),
            "Partially Used",
        )
        self.assertEqual(
            contract_state(docstatus=1, reserved_qty=5, delivered_qty=5),
            "Consumed",
        )
        self.assertEqual(
            contract_state(
                docstatus=2,
                reserved_qty=5,
                delivered_qty=0,
                terminal_state="Expired",
            ),
            "Expired",
        )
        self.assertEqual(
            contract_state(docstatus=2, reserved_qty=5, delivered_qty=0),
            "Cancelled",
        )

    def test_remaining_never_negative(self):
        self.assertEqual(remaining_qty(2, 3), 0)
        self.assertEqual(remaining_qty("5.12345678", "1"), 4.123457)

    def test_ceiling_uses_strictest_bound(self):
        self.assertEqual(
            reservation_ceiling(
                owner_remaining_qty=10,
                unified_available_to_promise=4,
                standard_available_qty=7,
            ),
            4,
        )
        self.assertEqual(
            reservation_ceiling(
                owner_remaining_qty=-1,
                unified_available_to_promise=4,
                standard_available_qty=7,
            ),
            0,
        )

    def test_idempotency_key_is_deterministic_and_scoped(self):
        values = {
            "voucher_type": "Sales Order",
            "voucher_no": "SO-TEST",
            "voucher_detail_no": "SOI-TEST",
            "item_code": "ITEM-1",
            "warehouse": "WAREHOUSE-1",
            "operational_role": "Sales",
        }
        key = build_idempotency_key(**values)
        self.assertEqual(key, build_idempotency_key(**values))
        self.assertEqual(len(key), 64)
        changed = dict(values, warehouse="WAREHOUSE-2")
        self.assertNotEqual(key, build_idempotency_key(**changed))

    def test_terminal_action_is_bounded(self):
        self.assertEqual(validate_terminal_state("Released"), "Released")
        with self.assertRaises(ValueError):
            validate_terminal_state("Consumed")


if __name__ == "__main__":
    unittest.main()
