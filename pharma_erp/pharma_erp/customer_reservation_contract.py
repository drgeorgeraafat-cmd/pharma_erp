"""Pure operational invariants for Pharma ERP v0.9.2 Step2C.

The stock hold remains the submitted ERPNext Stock Reservation Entry owned by
a Sales Order item.  This module only maps that stock truth to the pharmacist's
customer-reservation workflow.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any


CONTRACT_VERSION = "v0.9.2-step2c-r7"
PRICE_TOLERANCE = 0.005
FULFILMENT_MODES = ("Undecided", "Pickup", "Home Delivery")
ACTIVE_STATUSES = ("Active", "Review Required", "Partially Fulfilled")
TERMINAL_STATUSES = (
    "Picked Up",
    "Sent for Delivery",
    "Fulfilled",
    "Released",
    "Cancelled",
)
CONTACT_OUTCOMES = (
    "Still Needed",
    "Confirmed Pickup",
    "Confirmed Delivery",
    "No Answer",
    "Declined",
    "Other",
)


def normalized_qty(value: Any) -> float:
    try:
        quantity = float(value or 0)
    except (TypeError, ValueError):
        quantity = 0.0
    return round(max(0.0, quantity), 6)


def remaining_qty(reserved_qty: Any, delivered_qty: Any) -> float:
    return normalized_qty(normalized_qty(reserved_qty) - normalized_qty(delivered_qty))


def validate_fulfilment_mode(mode: str | None) -> str:
    mode = str(mode or "Undecided").strip() or "Undecided"
    if mode not in FULFILMENT_MODES:
        raise ValueError("Fulfilment mode must be Undecided, Pickup or Home Delivery.")
    return mode


def validate_contact_outcome(outcome: str | None) -> str:
    outcome = str(outcome or "").strip()
    if outcome not in CONTACT_OUTCOMES:
        raise ValueError("Unsupported customer contact outcome.")
    return outcome


def derive_operational_status(
    *,
    reserved_qty: Any,
    delivered_qty: Any,
    reservation_docstatus: int,
    reservation_contract_state: str = "",
    review_due: bool = False,
    fulfilment_mode: str = "Undecided",
    stored_status: str = "",
) -> str:
    """Map standard reservation evidence to the Step2C action-center status."""

    stored_status = str(stored_status or "").strip()
    if stored_status in ("Released", "Cancelled", "Fulfilled"):
        return stored_status

    contract_state = str(reservation_contract_state or "").strip()
    if int(reservation_docstatus or 0) == 2:
        return "Released" if contract_state in ("Released", "Expired") else "Cancelled"

    reserved = normalized_qty(reserved_qty)
    delivered = normalized_qty(delivered_qty)
    remaining = remaining_qty(reserved, delivered)
    if reserved and not remaining:
        return "Sent for Delivery" if validate_fulfilment_mode(fulfilment_mode) == "Home Delivery" else "Picked Up"
    if delivered > 0 and remaining > 0:
        return "Partially Fulfilled"
    if review_due:
        return "Review Required"
    return "Active"


def validate_reserved_fulfilment_qty(*, requested_qty: Any, remaining_reserved_qty: Any) -> float:
    requested = normalized_qty(requested_qty)
    remaining = normalized_qty(remaining_reserved_qty)
    if requested <= 0:
        raise ValueError("A fulfilment must consume a positive reserved quantity.")
    if requested > remaining:
        raise ValueError("Fulfilment quantity cannot exceed the remaining reserved quantity.")
    return requested


def locked_reservation_pricing(
    *,
    price_list_rate: Any,
    rate: Any,
    discount_percentage: Any = 0,
) -> dict[str, float]:
    """Return the immutable Sales Order price contract for a reserved line."""

    try:
        effective_rate = round(float(rate or 0), 6)
        list_rate = round(float(price_list_rate or 0), 6)
        discount = round(float(discount_percentage or 0), 6)
    except (TypeError, ValueError) as exc:
        raise ValueError("Reservation price values must be numeric.") from exc

    if effective_rate <= 0:
        raise ValueError("Reserved Sales Order Item rate must be positive.")
    if list_rate <= 0:
        list_rate = effective_rate
    if discount < 0 or discount > 100:
        raise ValueError("Reservation discount must be between 0 and 100.")

    return {
        "price_list_rate": list_rate,
        "rate": effective_rate,
        "discount_percentage": discount,
    }


def weighted_source_price(allocations: list[dict[str, Any]]) -> float:
    """Return the quantity-weighted price of POS stock-source allocations."""

    total_qty = 0.0
    total_amount = 0.0
    for allocation in allocations or []:
        quantity = normalized_qty(allocation.get("qty"))
        try:
            price = round(float(allocation.get("customer_price") or 0), 6)
        except (TypeError, ValueError) as exc:
            raise ValueError("Stock-source price must be numeric.") from exc
        if quantity <= 0:
            continue
        if price <= 0:
            raise ValueError("Stock-source price must be positive.")
        total_qty += quantity
        total_amount += quantity * price
    if total_qty <= 0:
        raise ValueError("At least one positive stock-source allocation is required.")
    return round(total_amount / total_qty, 6)


def validate_locked_reservation_price(
    *,
    locked_price_list_rate: Any,
    locked_rate: Any,
    locked_discount_percentage: Any = 0,
    invoice_price_list_rate: Any,
    invoice_rate: Any,
    invoice_discount_percentage: Any = 0,
) -> dict[str, float]:
    """Reject POS repricing of a line owned by a customer reservation."""

    locked = locked_reservation_pricing(
        price_list_rate=locked_price_list_rate,
        rate=locked_rate,
        discount_percentage=locked_discount_percentage,
    )
    submitted = locked_reservation_pricing(
        price_list_rate=invoice_price_list_rate,
        rate=invoice_rate,
        discount_percentage=invoice_discount_percentage,
    )
    for fieldname in ("price_list_rate", "rate", "discount_percentage"):
        if abs(locked[fieldname] - submitted[fieldname]) > PRICE_TOLERANCE:
            raise ValueError(
                "Reserved item price is locked by its Sales Order Item."
            )
    return locked


def build_request_key(*, customer: str, item_code: str, branch: str, request_token: str) -> str:
    values = (
        CONTRACT_VERSION,
        str(customer or "").strip(),
        str(item_code or "").strip(),
        str(branch or "").strip(),
        str(request_token or "").strip(),
    )
    if any(not value for value in values[1:]):
        raise ValueError("Customer, item, branch and request token are required.")
    return sha256("|".join(values).encode("utf-8")).hexdigest()
