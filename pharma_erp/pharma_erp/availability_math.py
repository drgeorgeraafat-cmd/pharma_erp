"""Pure quantity math for the v0.9.2 unified availability contract.

This module deliberately has no Frappe or ERPNext imports so the contract math
can be tested without a site or database.  Data collection and canonical
validation live in ``unified_stock_availability``.
"""

from __future__ import annotations

from typing import Any


QTY_PRECISION = 6


def normalized_qty(value: Any) -> float:
    """Return a non-negative, deterministically rounded stock quantity."""

    try:
        quantity = float(value or 0)
    except (TypeError, ValueError):
        quantity = 0.0
    return round(max(0.0, quantity), QTY_PRECISION)


def compute_availability_metrics(
    *,
    item_sellable_qty: Any,
    source_sellable_qty: Any,
    item_reserved_qty: Any = 0,
    source_reserved_qty: Any = 0,
    safety_floor: Any = 0,
    approved_unissued_transfer_qty: Any = 0,
) -> dict[str, float]:
    """Apply the approved Step 1 quantity contract.

    ``source_*`` may describe the whole item/warehouse, one batch, or one
    Internal Retail Price Lot.  The final promise is constrained by both the
    source and the item/warehouse totals.  Projected and transit quantities are
    intentionally absent from this function and therefore cannot increase ATP.
    """

    item_sellable = normalized_qty(item_sellable_qty)
    source_sellable = normalized_qty(source_sellable_qty)
    item_reserved = normalized_qty(item_reserved_qty)
    source_reserved = normalized_qty(source_reserved_qty)
    floor = normalized_qty(safety_floor)
    transfer_commitment = normalized_qty(approved_unissued_transfer_qty)

    item_after_reservation = normalized_qty(item_sellable - item_reserved)
    item_available_to_promise = normalized_qty(item_after_reservation - floor)
    source_after_reservation = normalized_qty(source_sellable - source_reserved)
    available_to_promise = normalized_qty(
        min(item_available_to_promise, source_after_reservation)
    )
    transferable_surplus = normalized_qty(
        available_to_promise - transfer_commitment
    )

    return {
        "item_after_reservation_qty": item_after_reservation,
        "item_available_to_promise": item_available_to_promise,
        "source_after_reservation_qty": source_after_reservation,
        "available_to_promise": available_to_promise,
        "transferable_surplus": transferable_surplus,
    }
