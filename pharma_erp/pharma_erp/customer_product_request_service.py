"""Step2D Customer Product Request operations.

Requests and matches are informational.  Stock is held only when a confirmed
customer decision is converted through the closed Step2C reservation service.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta
from typing import Any
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, now_datetime

from pharma_erp.pharma_erp.branch_operational_integration import resolve_role_context
from pharma_erp.pharma_erp.customer_product_request_contract import (
    ACTIVE_PARENT_STATUSES,
    CONTACT_OUTCOMES,
    CONTRACT_VERSION,
    FULFILMENT_MODES,
    TERMINAL_PARENT_STATUSES,
    aggregate_status,
    fifo_allocate,
    positive_qty,
    stable_match_key,
    stable_request_key,
)
from pharma_erp.pharma_erp.customer_reservation_service import create_customer_reservation
from pharma_erp.pharma_erp.unified_stock_availability import get_unified_stock_availability


REQUEST_DOCTYPE = "Customer Product Request"
ITEM_DOCTYPE = "Customer Product Request Item"
MATCH_DOCTYPE = "Customer Product Request Match"
ROLE = "Sales"
DIRECT_PURCHASE_INVOICE_SOURCE = "Purchase Invoice"


def _clean(value: Any) -> str:
    return cstr(value or "").strip()


def _data(value: Any) -> frappe._dict:
    if isinstance(value, str):
        value = json.loads(value)
    return frappe._dict(value or {})


def _assert_installation() -> None:
    missing = [name for name in (REQUEST_DOCTYPE, ITEM_DOCTYPE, MATCH_DOCTYPE) if not frappe.db.exists("DocType", name)]
    if missing:
        frappe.throw(_("Step2D metadata is not installed: {0}").format(", ".join(missing)))


def _permitted_request(name: str, permission: str = "read"):
    doc = frappe.get_doc(REQUEST_DOCTYPE, name)
    if not frappe.has_permission(REQUEST_DOCTYPE, permission, doc=doc):
        frappe.throw(
            _("You do not have {0} permission for Customer Product Request {1}.").format(
                permission, frappe.bold(name)
            ),
            frappe.PermissionError,
        )
    return doc


def _default_company() -> str:
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or ""
    )


def _availability(item_code: str, branch: str, warehouse: str = "") -> frappe._dict:
    result = get_unified_stock_availability(
        item_code=item_code,
        branch=branch,
        operational_role=ROLE,
        warehouse=warehouse,
        source_type="stock",
        enforce_permissions=False,
    )
    quantities = frappe._dict(result.get("quantities") or {})
    canonical_context = frappe._dict(result.get("canonical_context") or {})
    states = frappe._dict(result.get("states") or {})
    missing = []
    if "available_to_promise" not in quantities:
        missing.append("quantities.available_to_promise")
    if not _clean(canonical_context.get("warehouse")):
        missing.append("canonical_context.warehouse")
    if "reservation_enabled" not in states:
        missing.append("states.reservation_enabled")
    if missing:
        frappe.throw(
            _("Unified availability response is missing required Step2D fields: {0}").format(
                ", ".join(missing)
            )
        )
    return frappe._dict(
        atp=flt(quantities.available_to_promise, 6),
        warehouse=_clean(canonical_context.warehouse),
        reservation_enabled=bool(states.reservation_enabled),
    )


def _item_row(item_code: str) -> frappe._dict:
    row = frappe.db.get_value(
        "Item", item_code,
        ["name", "item_name", "stock_uom", "is_stock_item", "disabled"],
        as_dict=True,
    )
    if not row or cint(row.disabled) or not cint(row.is_stock_item):
        frappe.throw(_("Select an enabled stock item: {0}").format(item_code))
    return row


@frappe.whitelist()
def create_customer_product_request(data):
    _assert_installation()
    frappe.has_permission(REQUEST_DOCTYPE, "create", throw=True)
    data = _data(data)
    customer = _clean(data.customer)
    branch = _clean(data.branch)
    company = _clean(data.company) or _default_company()
    if not customer or not frappe.db.exists("Customer", customer):
        frappe.throw(_("Select a valid customer."))
    if not branch or not frappe.db.exists("Branch", branch):
        frappe.throw(_("Select a valid branch."))
    # frappe._dict inherits dict, so attribute access to ``items`` resolves to
    # dict.items (a method), not to the payload key named "items".
    raw_items = data.get("items")
    if isinstance(raw_items, str):
        raw_items = json.loads(raw_items)
    if not raw_items:
        frappe.throw(_("Add at least one requested item."))

    token = _clean(data.request_token) or uuid4().hex
    request_key = stable_request_key(customer, branch, token)
    existing = frappe.db.get_value(REQUEST_DOCTYPE, {"external_request_key": request_key}, "name")
    if existing:
        return {**get_customer_product_request(existing), "idempotent": True}

    prepared = []
    fully_available = []
    for raw in raw_items:
        row = _data(raw)
        item = _item_row(_clean(row.item_code))
        qty = positive_qty(row.requested_qty or row.qty)
        availability = _availability(item.name, branch)
        if availability.atp >= qty:
            fully_available.append(item.item_name or item.name)
        prepared.append((item, qty, availability))
    if fully_available and len(fully_available) == len(prepared):
        frappe.throw(
            _("All requested items are currently available. Use Customer Reservation instead: {0}").format(
                ", ".join(fully_available)
            )
        )

    doc = frappe.new_doc(REQUEST_DOCTYPE)
    doc.company = company
    doc.branch = branch
    doc.customer = customer
    doc.contact_mobile = _clean(data.contact_mobile) or _clean(
        frappe.db.get_value("Customer", customer, "mobile_no")
    )
    doc.source = _clean(data.source) or "Phone"
    doc.priority = _clean(data.priority) or "Normal"
    doc.status = "Waiting for Stock"
    doc.requested_at = now_datetime()
    doc.external_request_key = request_key
    doc.notes = _clean(data.notes)
    for sequence, (item, qty, availability) in enumerate(prepared, 1):
        doc.append("items", {
            "item_code": item.name,
            "item_name": item.item_name,
            "stock_uom": item.stock_uom,
            "requested_qty": qty,
            "matched_qty": 0,
            "converted_qty": 0,
            "remaining_qty": qty,
            "operational_role": ROLE,
            "warehouse": availability.warehouse,
            "match_status": "Waiting",
            "fulfilment_mode": "Undecided",
            "fifo_sequence": sequence,
        })
    doc.insert(ignore_permissions=True)
    doc.add_comment("Info", _("Customer Product Request created without reserving stock."))
    return get_customer_product_request(doc.name)


def _active_rows(item_codes: list[str] | None = None, lock: bool = False) -> list[frappe._dict]:
    values: dict[str, Any] = {"statuses": tuple(ACTIVE_PARENT_STATUSES)}
    item_filter = ""
    if item_codes:
        values["item_codes"] = tuple(sorted(set(item_codes)))
        item_filter = " AND i.item_code IN %(item_codes)s"
    lock_clause = " FOR UPDATE" if lock else ""
    return frappe.db.sql(
        f"""
        SELECT p.name AS request, p.branch, p.company, p.customer,
               p.requested_at, p.creation, p.status AS parent_status,
               i.name AS request_item, i.item_code, i.warehouse,
               i.requested_qty, i.converted_qty,
               GREATEST(i.requested_qty - i.converted_qty, 0) AS remaining_qty,
               i.idx
          FROM `tabCustomer Product Request` p
          JOIN `tabCustomer Product Request Item` i ON i.parent = p.name
         WHERE p.status IN %(statuses)s
           AND i.match_status NOT IN ('Converted', 'Declined', 'Closed')
           {item_filter}
         ORDER BY p.branch, i.item_code, p.requested_at, p.creation, i.idx, i.name
         {lock_clause}
        """,
        values,
        as_dict=True,
    )


def _write_match(row: frappe._dict, allocation, availability, source_type: str, source_name: str) -> None:
    key = stable_match_key(row.request, row.request_item)
    existing = frappe.db.get_value(MATCH_DOCTYPE, {"match_key": key}, "name")
    status = "Unavailable"
    if allocation.matched_qty > 0:
        status = "Available" if allocation.matched_qty >= allocation.requested_qty else "Partially Available"
    values = {
        "match_key": key,
        "request": row.request,
        "request_item": row.request_item,
        "item_code": row.item_code,
        "branch": row.branch,
        "warehouse": availability.warehouse,
        "source_type": source_type,
        "source_name": source_name,
        "available_to_promise": availability.atp,
        "matched_qty": allocation.matched_qty,
        "status": status,
        "matched_at": now_datetime(),
        "superseded_at": None,
    }
    if existing:
        match = frappe.get_doc(MATCH_DOCTYPE, existing)
        match.update(values)
        match.save(ignore_permissions=True)
    else:
        match = frappe.get_doc({"doctype": MATCH_DOCTYPE, **values})
        match.insert(ignore_permissions=True)
    frappe.db.set_value(ITEM_DOCTYPE, row.request_item, {
        "warehouse": availability.warehouse,
        "matched_qty": allocation.matched_qty,
        "remaining_qty": allocation.requested_qty,
        "match_status": status if status != "Unavailable" else "Waiting",
        "match_reference": match.name,
    }, update_modified=False)


def _refresh_parent_status(request: str) -> str:
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    status = aggregate_status([row.as_dict() for row in doc.items], doc.status)
    if status != doc.status and doc.status not in TERMINAL_PARENT_STATUSES:
        frappe.db.set_value(REQUEST_DOCTYPE, request, "status", status)
    return status


def match_waiting_requests(item_codes=None, source_type="Manual Review", source_name="") -> dict:
    _assert_installation()
    if source_type not in {"Purchase Receipt", DIRECT_PURCHASE_INVOICE_SOURCE, "Manual Review"}:
        frappe.throw(_("Unsupported Step2D match source."))
    if isinstance(item_codes, str):
        item_codes = json.loads(item_codes) if item_codes.startswith("[") else [item_codes]
    # Matching writes a persistent FIFO allocation. Lock the participating
    # parent/child rows so concurrent receipt hooks cannot allocate the same
    # availability pool independently.
    rows = _active_rows(item_codes, lock=True)
    grouped: dict[tuple[str, str], list[frappe._dict]] = defaultdict(list)
    for row in rows:
        grouped[(row.branch, row.item_code)].append(row)
    changed_requests = set()
    matched_lines = 0
    for (branch, item_code), group in grouped.items():
        availability = _availability(item_code, branch, group[0].warehouse)
        allocations = fifo_allocate(group, availability.atp)
        by_item = {allocation.request_item: allocation for allocation in allocations}
        for row in group:
            allocation = by_item[row.request_item]
            _write_match(row, allocation, availability, source_type, _clean(source_name))
            changed_requests.add(row.request)
            matched_lines += int(allocation.matched_qty > 0)
    statuses = {request: _refresh_parent_status(request) for request in sorted(changed_requests)}
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS",
        "evaluated_lines": len(rows),
        "matched_lines": matched_lines,
        "requests": statuses,
    }


@frappe.whitelist()
def evaluate_customer_product_requests(item_codes=None):
    frappe.has_permission(REQUEST_DOCTYPE, "write", throw=True)
    return match_waiting_requests(item_codes, "Manual Review", f"user:{frappe.session.user}")


def on_submit_purchase_receipt_match_requests(doc, method=None):
    item_codes = sorted({_clean(row.item_code) for row in doc.get("items") or [] if _clean(row.item_code)})
    if not item_codes or not frappe.db.exists("DocType", REQUEST_DOCTYPE):
        return
    return match_waiting_requests(item_codes, "Purchase Receipt", doc.name)


def _direct_purchase_invoice_item_codes(doc) -> list[str]:
    """Return stock-producing PI lines that are not backed by a Receipt.

    A Purchase Invoice linked to a Purchase Receipt must not run Step2D again;
    the Receipt hook is the single source for that path.  Direct Quick Invoice
    & Receipt documents, however, are the stock-entry document and therefore
    must trigger matching after submit.
    """
    if cint(doc.get("docstatus")) != 1:
        return []
    if not cint(doc.get("update_stock")) or cint(doc.get("is_return")):
        return []
    return sorted({
        _clean(row.get("item_code"))
        for row in doc.get("items") or []
        if _clean(row.get("item_code"))
        and not _clean(row.get("purchase_receipt"))
        and not _clean(row.get("pr_detail"))
    })


def _notify_direct_purchase_invoice_matches(result: dict) -> None:
    available = [
        name
        for name, status in (result.get("requests") or {}).items()
        if status in {"Available for Contact", "Partially Available", "Still Interested", "Contact Attempted"}
    ]
    if not available or not cint(result.get("matched_lines")):
        return
    requests = ", ".join(frappe.bold(name) for name in sorted(available))
    frappe.msgprint(
        _(
            "Stock received for customer-requested item(s). Request(s) {0} are ready for pharmacist contact. "
            '<a href="/app/customer-product-request-operations">Open Customer Product Request Operations</a>.'
        ).format(requests),
        title=_("Customer Product Request Available"),
        indicator="green",
    )


def _match_direct_purchase_invoice(doc, notify: bool = True) -> dict:
    item_codes = _direct_purchase_invoice_item_codes(doc)
    if not frappe.db.exists("DocType", REQUEST_DOCTYPE):
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "PASS",
            "ignored": True,
            "reason": "Step2D metadata is not installed.",
            "item_codes": item_codes,
        }
    if not item_codes:
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "PASS",
            "ignored": True,
            "reason": "Purchase Invoice is not a direct submitted stock receipt.",
            "item_codes": [],
        }
    result = match_waiting_requests(
        item_codes,
        DIRECT_PURCHASE_INVOICE_SOURCE,
        _clean(doc.get("name")),
    )
    result.update({
        "ignored": False,
        "source_type": DIRECT_PURCHASE_INVOICE_SOURCE,
        "source_name": _clean(doc.get("name")),
        "item_codes": item_codes,
    })
    if notify:
        _notify_direct_purchase_invoice_matches(result)
    return result


def on_submit_purchase_invoice_match_requests(doc, method=None):
    """Match only direct Purchase Invoices that actually posted stock."""
    return _match_direct_purchase_invoice(doc, notify=True)


@frappe.whitelist()
def reconcile_submitted_purchase_invoice(purchase_invoice: str, notify: int = 0) -> dict:
    """Idempotently backfill one already-submitted direct Purchase Invoice."""
    frappe.has_permission("Purchase Invoice", "read", throw=True)
    doc = frappe.get_doc("Purchase Invoice", _clean(purchase_invoice))
    if doc.docstatus != 1:
        frappe.throw(_("Purchase Invoice {0} must be submitted.").format(frappe.bold(doc.name)))
    result = _match_direct_purchase_invoice(doc, notify=bool(cint(notify)))
    if result.get("ignored"):
        frappe.throw(_("Purchase Invoice {0} is not an eligible direct stock receipt.").format(frappe.bold(doc.name)))
    return result


@frappe.whitelist()
def reconcile_submitted_purchase_invoice_acceptance(
    purchase_invoice: str,
    request: str,
) -> dict:
    """Atomically reconcile and verify one known manual-acceptance pair.

    This is intentionally stricter than the normal idempotent reconciliation
    endpoint.  Any failed assertion raises inside the same request so Frappe
    rolls the reconciliation back instead of leaving partial acceptance data.
    """
    _assert_installation()
    frappe.has_permission("Purchase Invoice", "read", throw=True)
    request_doc = _permitted_request(_clean(request), "read")
    invoice = frappe.get_doc("Purchase Invoice", _clean(purchase_invoice))
    item_codes = _direct_purchase_invoice_item_codes(invoice)
    if not item_codes:
        frappe.throw(_("Purchase Invoice {0} is not an eligible direct stock receipt.").format(frappe.bold(invoice.name)))

    target_rows = [row for row in request_doc.items if _clean(row.item_code) in item_codes]
    if not target_rows:
        frappe.throw(
            _("Purchase Invoice {0} has no direct stock line requested by {1}.").format(
                frappe.bold(invoice.name), frappe.bold(request_doc.name)
            )
        )
    if request_doc.status not in ACTIVE_PARENT_STATUSES:
        frappe.throw(_("Customer Product Request {0} is not active.").format(frappe.bold(request_doc.name)))

    before = {
        "request_status": request_doc.status,
        "matched_qty": {row.name: flt(row.matched_qty, 6) for row in target_rows},
        "match_count": frappe.db.count(MATCH_DOCTYPE, {"request": request_doc.name}),
        "sre_count": frappe.db.count(
            "Stock Reservation Entry",
            {"item_code": ["in", sorted({_clean(row.item_code) for row in target_rows})]},
        ),
    }

    result = reconcile_submitted_purchase_invoice(invoice.name, notify=0)
    request_doc.reload()
    target_rows = [row for row in request_doc.items if _clean(row.item_code) in item_codes]
    if not target_rows or any(flt(row.matched_qty, 6) <= 0 for row in target_rows):
        frappe.throw(_("Direct Purchase Invoice reconciliation did not persist a positive FIFO match."))
    if request_doc.status not in {
        "Available for Contact",
        "Partially Available",
        "Still Interested",
        "Contact Attempted",
    }:
        frappe.throw(_("Direct Purchase Invoice reconciliation did not make the request contactable."))

    source_matches = frappe.get_all(
        MATCH_DOCTYPE,
        filters={
            "request": request_doc.name,
            "source_type": DIRECT_PURCHASE_INVOICE_SOURCE,
            "source_name": invoice.name,
        },
        fields=["name", "request_item", "item_code", "matched_qty", "status"],
        order_by="creation asc, name asc",
    )
    if len(source_matches) != len(target_rows):
        frappe.throw(_("Direct Purchase Invoice reconciliation did not create the exact stable match set."))

    after_sre_count = frappe.db.count(
        "Stock Reservation Entry",
        {"item_code": ["in", sorted({_clean(row.item_code) for row in target_rows})]},
    )
    if after_sre_count != before["sre_count"]:
        frappe.throw(_("Direct Purchase Invoice matching created or changed a stock reservation."))

    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS",
        "purchase_invoice": invoice.name,
        "request": request_doc.name,
        "item_codes": item_codes,
        "before": before,
        "after": {
            "request_status": request_doc.status,
            "matched_qty": {row.name: flt(row.matched_qty, 6) for row in target_rows},
            "match_count": frappe.db.count(MATCH_DOCTYPE, {"request": request_doc.name}),
            "sre_count": after_sre_count,
            "source_matches": source_matches,
        },
        "match_result": result,
    }


@frappe.whitelist()
def rollback_submitted_purchase_invoice_acceptance(
    purchase_invoice: str,
    request: str,
) -> dict:
    """Undo only the exact, unconverted R4 manual-acceptance match set."""
    _assert_installation()
    request_doc = _permitted_request(_clean(request), "write")
    invoice_name = _clean(purchase_invoice)
    source_matches = frappe.get_all(
        MATCH_DOCTYPE,
        filters={
            "request": request_doc.name,
            "source_type": DIRECT_PURCHASE_INVOICE_SOURCE,
            "source_name": invoice_name,
        },
        fields=["name", "request_item", "item_code"],
        order_by="creation asc, name asc",
    )
    if not source_matches:
        frappe.throw(_("No exact R4 Purchase Invoice acceptance match exists to roll back."))

    request_items = {row.name: row for row in request_doc.items}
    for match in source_matches:
        row = request_items.get(match.request_item)
        if not row or flt(row.converted_qty, 6) > 0 or _clean(row.customer_reservation):
            frappe.throw(_("The matched request was converted; automatic R4 acceptance rollback is blocked."))
        if frappe.db.count("Stock Reservation Entry", {"item_code": match.item_code}):
            frappe.throw(_("A stock reservation now exists for the matched item; automatic rollback is blocked."))

    for match in source_matches:
        row = request_items[match.request_item]
        frappe.delete_doc(MATCH_DOCTYPE, match.name, ignore_permissions=True)
        frappe.db.set_value(
            ITEM_DOCTYPE,
            row.name,
            {
                "matched_qty": 0,
                "remaining_qty": max(flt(row.requested_qty) - flt(row.converted_qty), 0),
                "match_status": "Waiting",
                "match_reference": "",
            },
            update_modified=False,
        )
    status = _refresh_parent_status(request_doc.name)
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS",
        "purchase_invoice": invoice_name,
        "request": request_doc.name,
        "removed_matches": [match.name for match in source_matches],
        "request_status": status,
    }


def _lock_request(name: str):
    rows = frappe.db.sql(
        "SELECT name FROM `tabCustomer Product Request` WHERE name=%s FOR UPDATE", name
    )
    if not rows:
        frappe.throw(_("Customer Product Request {0} was not found.").format(name))
    frappe.db.sql(
        "SELECT name FROM `tabCustomer Product Request Item` WHERE parent=%s ORDER BY idx FOR UPDATE", name
    )


@frappe.whitelist()
def confirm_and_convert(request: str, fulfilment_mode: str, allow_partial: int = 0, notes: str = ""):
    _assert_installation()
    _permitted_request(request, "write")
    fulfilment_mode = _clean(fulfilment_mode)
    if fulfilment_mode not in {"Pickup", "Home Delivery"}:
        frappe.throw(_("Choose Pickup or Home Delivery."))
    _lock_request(request)
    match_waiting_requests(source_type="Manual Review", source_name=f"conversion:{request}")
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    if doc.status in TERMINAL_PARENT_STATUSES:
        existing = [row.customer_reservation for row in doc.items if row.customer_reservation]
        return {"request": request, "reservations": existing, "idempotent": True}
    convertible = []
    insufficient = []
    for row in doc.items:
        remaining = max(flt(row.requested_qty) - flt(row.converted_qty), 0)
        if remaining <= 0:
            continue
        available = _availability(row.item_code, doc.branch, row.warehouse)
        qty = min(remaining, available.atp)
        if qty + 1e-9 < remaining:
            insufficient.append(row.item_code)
        if qty > 0:
            convertible.append((row, qty, available))
    if insufficient and not cint(allow_partial):
        frappe.throw(_("Full requested quantities are not available. Explicitly allow partial conversion: {0}").format(", ".join(insufficient)))
    if not convertible:
        frappe.throw(_("No requested quantity is currently available to reserve."))

    reservations = []
    review_at = now_datetime() + timedelta(days=1)
    for row, qty, available in convertible:
        converted_before = flt(row.converted_qty)
        converted_target = converted_before + qty
        result = create_customer_reservation({
            "customer": doc.customer,
            "contact_mobile": doc.contact_mobile,
            "company": doc.company,
            "branch": doc.branch,
            "warehouse": available.warehouse,
            "item_code": row.item_code,
            "qty": qty,
            "review_at": review_at,
            "fulfilment_mode": fulfilment_mode,
            "notes": _clean(notes) or f"Converted from Customer Product Request {doc.name}",
            # Each partial tranche gets a deterministic cumulative key. A
            # retry of the same transaction is idempotent, while a later
            # tranche can create its own controlled Step2C reservation.
            "request_token": f"step2d:{doc.name}:{row.name}:to:{converted_target:.6f}",
        })
        reservations.append(result["sales_order"])
        converted = converted_target
        remaining = max(flt(row.requested_qty) - converted, 0)
        frappe.db.set_value(ITEM_DOCTYPE, row.name, {
            "converted_qty": converted,
            "remaining_qty": remaining,
            "matched_qty": 0,
            "match_status": "Converted" if remaining <= 1e-9 else "Waiting",
            "fulfilment_mode": fulfilment_mode,
            "customer_reservation": result["sales_order"],
        }, update_modified=False)
        if row.match_reference:
            frappe.db.set_value(MATCH_DOCTYPE, row.match_reference, "status", "Consumed")
    doc.reload()
    terminal = all(flt(row.remaining_qty) <= 1e-9 for row in doc.items)
    values = {
        "status": "Converted to Reservation" if terminal else "Partially Available",
        "last_contact_outcome": "Confirmed Pickup" if fulfilment_mode == "Pickup" else "Confirmed Delivery",
        "last_contact_at": now_datetime(),
        "last_contact_by": frappe.session.user,
        "last_contact_notes": _clean(notes),
    }
    if terminal:
        values.update({"terminal_at": now_datetime(), "terminal_by": frappe.session.user, "terminal_reason": "Converted to controlled Step2C reservation."})
    frappe.db.set_value(REQUEST_DOCTYPE, request, values)
    doc.add_comment("Info", _("Customer Product Request converted to Step2C reservation(s): {0}").format(", ".join(reservations)))
    return {"request": request, "reservations": reservations, "partial": not terminal}


@frappe.whitelist()
def record_customer_product_request_contact(request: str, outcome: str, notes: str = "", next_review_at=None, allow_partial: int = 0):
    _permitted_request(request, "write")
    outcome = _clean(outcome)
    if outcome not in CONTACT_OUTCOMES:
        frappe.throw(_("Unsupported contact outcome."))
    if outcome in {"Confirmed Pickup", "Confirmed Delivery"}:
        mode = "Pickup" if outcome == "Confirmed Pickup" else "Home Delivery"
        return confirm_and_convert(request, mode, allow_partial, notes)
    status = {"No Answer": "Contact Attempted", "Still Interested": "Still Interested", "Declined": "Declined"}[outcome]
    values = {
        "status": status,
        "last_contact_outcome": outcome,
        "last_contact_at": now_datetime(),
        "last_contact_by": frappe.session.user,
        "last_contact_notes": _clean(notes),
    }
    if outcome == "Declined":
        values.update({"terminal_at": now_datetime(), "terminal_by": frappe.session.user, "terminal_reason": _clean(notes) or "Customer declined."})
        for row in frappe.get_doc(REQUEST_DOCTYPE, request).items:
            frappe.db.set_value(ITEM_DOCTYPE, row.name, {"match_status": "Declined", "matched_qty": 0}, update_modified=False)
    frappe.db.set_value(REQUEST_DOCTYPE, request, values)
    frappe.get_doc(REQUEST_DOCTYPE, request).add_comment("Info", _("Customer contact recorded: {0}. {1}").format(outcome, _clean(notes)))
    return get_customer_product_request(request)


@frappe.whitelist()
def close_customer_product_request(request: str, reason: str):
    _permitted_request(request, "write")
    reason = _clean(reason)
    if not reason:
        frappe.throw(_("A close reason is required."))
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    if doc.status == "Converted to Reservation":
        frappe.throw(_("A converted request cannot be closed as unfulfilled."))
    for row in doc.items:
        frappe.db.set_value(ITEM_DOCTYPE, row.name, {"match_status": "Closed", "matched_qty": 0}, update_modified=False)
    frappe.db.set_value(REQUEST_DOCTYPE, request, {
        "status": "Closed", "terminal_at": now_datetime(), "terminal_by": frappe.session.user, "terminal_reason": reason,
    })
    doc.add_comment("Info", _("Customer Product Request closed. Reason: {0}").format(reason))
    return get_customer_product_request(request)


@frappe.whitelist()
def get_customer_product_request(request: str) -> dict:
    doc = _permitted_request(request, "read")
    customer_name = frappe.db.get_value("Customer", doc.customer, "customer_name") or doc.customer
    return {
        "request": doc.name, "status": doc.status, "priority": doc.priority,
        "company": doc.company, "branch": doc.branch, "customer": doc.customer,
        "customer_name": customer_name, "contact_mobile": doc.contact_mobile,
        "requested_at": doc.requested_at, "last_contact_outcome": doc.last_contact_outcome,
        "last_contact_at": doc.last_contact_at, "last_contact_notes": doc.last_contact_notes,
        "terminal_reason": doc.terminal_reason, "notes": doc.notes,
        "items": [{
            "name": row.name, "item_code": row.item_code, "item_name": row.item_name,
            "stock_uom": row.stock_uom, "requested_qty": flt(row.requested_qty),
            "matched_qty": flt(row.matched_qty), "converted_qty": flt(row.converted_qty),
            "remaining_qty": flt(row.remaining_qty), "match_status": row.match_status,
            "warehouse": row.warehouse, "fulfilment_mode": row.fulfilment_mode,
            "customer_reservation": row.customer_reservation,
        } for row in doc.items],
    }


@frappe.whitelist()
def list_customer_product_requests(status="", branch="", customer="", limit=300):
    frappe.has_permission(REQUEST_DOCTYPE, "read", throw=True)
    filters = {}
    if _clean(status): filters["status"] = _clean(status)
    if _clean(branch): filters["branch"] = _clean(branch)
    if _clean(customer): filters["customer"] = _clean(customer)
    names = frappe.get_all(REQUEST_DOCTYPE, filters=filters, pluck="name", order_by="requested_at desc, creation desc", limit=min(cint(limit) or 300, 500))
    return [get_customer_product_request(name) for name in names]
