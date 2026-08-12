"""Pure reservation invariants for Pharma ERP v0.9.2 Step2B.

This module has no Frappe imports. Database collection, canonical validation
and standard ERPNext Stock Reservation Entry integration live in
``standard_reservation_service``.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any


CONTRACT_VERSION = "v0.9.2-step2b-r1"
QTY_PRECISION = 6
ACTIVE_STATES = ("Active", "Partially Used")
TERMINAL_STATES = ("Consumed", "Released", "Expired", "Cancelled")
ALL_STATES = ACTIVE_STATES + TERMINAL_STATES


def normalized_qty(value: Any) -> float:
    try:
        quantity = float(value or 0)
    except (TypeError, ValueError):
        quantity = 0.0
    return round(max(0.0, quantity), QTY_PRECISION)


def remaining_qty(reserved_qty: Any, delivered_qty: Any) -> float:
    return normalized_qty(normalized_qty(reserved_qty) - normalized_qty(delivered_qty))


def contract_state(
    *,
    docstatus: int,
    reserved_qty: Any,
    delivered_qty: Any,
    terminal_state: str = "",
) -> str:
    """Map standard SRE evidence to the approved Step2B lifecycle."""

    terminal_state = str(terminal_state or "").strip()
    if int(docstatus or 0) == 2:
        return terminal_state if terminal_state in TERMINAL_STATES else "Cancelled"

    reserved = normalized_qty(reserved_qty)
    delivered = normalized_qty(delivered_qty)
    remaining = remaining_qty(reserved, delivered)
    if reserved and not remaining:
        return "Consumed"
    if delivered > 0 and remaining > 0:
        return "Partially Used"
    return "Active"


def reservation_ceiling(
    *,
    owner_remaining_qty: Any,
    unified_available_to_promise: Any,
    standard_available_qty: Any,
) -> float:
    """Return the maximum stock-UOM quantity allowed in the final transaction."""

    return normalized_qty(
        min(
            normalized_qty(owner_remaining_qty),
            normalized_qty(unified_available_to_promise),
            normalized_qty(standard_available_qty),
        )
    )


def build_idempotency_key(
    *,
    voucher_type: str,
    voucher_no: str,
    voucher_detail_no: str,
    item_code: str,
    warehouse: str,
    operational_role: str,
) -> str:
    components = (
        CONTRACT_VERSION,
        str(voucher_type or "").strip(),
        str(voucher_no or "").strip(),
        str(voucher_detail_no or "").strip(),
        str(item_code or "").strip(),
        str(warehouse or "").strip(),
        str(operational_role or "").strip(),
    )
    if any(not value for value in components[1:]):
        raise ValueError("Complete reservation owner and canonical stock context are required.")
    return sha256("|".join(components).encode("utf-8")).hexdigest()


def validate_terminal_state(state: str) -> str:
    state = str(state or "").strip()
    if state not in ("Released", "Expired", "Cancelled"):
        raise ValueError("Terminal action must be Released, Expired or Cancelled.")
    return state
