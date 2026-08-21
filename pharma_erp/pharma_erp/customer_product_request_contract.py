"""Pure contract helpers for v0.9.2 Step2D Customer Product Requests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal


CONTRACT_VERSION = "v0.9.2-step2d-r3"
ACTIVE_PARENT_STATUSES = (
    "Waiting for Stock",
    "Partially Available",
    "Available for Contact",
    "Contact Attempted",
    "Still Interested",
)
TERMINAL_PARENT_STATUSES = ("Converted to Reservation", "Declined", "Closed", "Cancelled")
FULFILMENT_MODES = ("Undecided", "Pickup", "Home Delivery")
CONTACT_OUTCOMES = (
    "No Answer",
    "Still Interested",
    "Confirmed Pickup",
    "Confirmed Delivery",
    "Declined",
)


def positive_qty(value) -> float:
    qty = Decimal(str(value or 0))
    if qty <= 0:
        raise ValueError("Quantity must be greater than zero.")
    return float(qty)


def stable_request_key(customer: str, branch: str, request_token: str) -> str:
    raw = f"{CONTRACT_VERSION}|{customer}|{branch}|{request_token}".encode()
    return hashlib.sha256(raw).hexdigest()


def stable_match_key(request: str, request_item: str) -> str:
    raw = f"{CONTRACT_VERSION}|{request}|{request_item}".encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class Allocation:
    request_item: str
    requested_qty: float
    matched_qty: float


def fifo_allocate(rows: list[dict], available_qty: float) -> list[Allocation]:
    """Allocate an informational availability pool in caller-provided FIFO order."""
    pool = max(float(available_qty or 0), 0.0)
    result = []
    for row in rows:
        requested = positive_qty(row.get("remaining_qty") or row.get("requested_qty"))
        matched = min(requested, pool)
        pool = max(pool - matched, 0.0)
        result.append(Allocation(str(row["request_item"]), requested, matched))
    return result


def aggregate_status(items: list[dict], current_status: str = "") -> str:
    if not items:
        return current_status or "Draft"
    states = {str(item.get("match_status") or "Waiting") for item in items}
    if states <= {"Converted", "Closed", "Declined"} and "Converted" in states:
        return "Converted to Reservation"
    matched = sum(float(item.get("matched_qty") or 0) for item in items)
    remaining = sum(float(item.get("remaining_qty") or 0) for item in items)
    if current_status in {"Contact Attempted", "Still Interested"} and matched > 0:
        return current_status
    if matched <= 0:
        return "Waiting for Stock"
    if remaining > matched:
        return "Partially Available"
    return "Available for Contact"
