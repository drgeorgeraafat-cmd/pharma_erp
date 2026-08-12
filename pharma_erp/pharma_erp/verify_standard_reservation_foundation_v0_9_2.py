"""Transactional acceptance for v0.9.2 Step2B R1.

All temporary Sales Orders, Stock Reservation Entries and Comments are created
after a savepoint and rolled back before this function returns.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import add_days, add_to_date, cint, flt, now_datetime, today

from pharma_erp.pharma_erp.install_standard_reservation_foundation_v0_9_2 import (
    _canonical_sales_targets,
    verify_installation,
)
from pharma_erp.pharma_erp.standard_reservation_service import (
    _release_reservation,
    expire_due_reservations,
    reserve_sales_order_item,
    sync_standard_reservation_contract,
)
from pharma_erp.pharma_erp.unified_stock_availability import (
    get_unified_stock_availability,
)


CONTRACT_VERSION = "v0.9.2-step2b-r1"
COUNTER_DOCTYPES = (
    "Comment",
    "GL Entry",
    "Sales Invoice",
    "Sales Order",
    "Stock Entry",
    "Stock Ledger Entry",
    "Stock Reservation Entry",
)


def _counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in COUNTER_DOCTYPES}


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _candidate() -> frappe._dict:
    for target in _canonical_sales_targets():
        rows = frappe.db.sql(
            """
            SELECT b.item_code, b.actual_qty, i.stock_uom
              FROM `tabBin` b
              JOIN `tabItem` i ON i.name = b.item_code
             WHERE b.warehouse = %(warehouse)s
               AND b.actual_qty >= 2
               AND i.disabled = 0
               AND i.is_stock_item = 1
               AND i.has_serial_no = 0
               AND i.has_batch_no = 0
             ORDER BY b.actual_qty DESC, b.item_code ASC
            """,
            {"warehouse": target["warehouse"]},
            as_dict=True,
        )
        for row in rows:
            availability = get_unified_stock_availability(
                item_code=row.item_code,
                branch=target["branch"],
                operational_role="Sales",
                warehouse=target["warehouse"],
                enforce_permissions=False,
            )
            if flt(availability["quantities"]["available_to_promise"]) >= 2:
                return frappe._dict(target=frappe._dict(target), item=row, availability=availability)
    raise AssertionError("No non-batch, non-serial canonical Sales item has at least two ATP units.")


def _customer(company: str) -> str:
    customer = frappe.db.get_value(
        "Sales Invoice",
        {"company": company, "docstatus": 1},
        "customer",
        order_by="posting_date desc, posting_time desc, creation desc",
    )
    if not customer:
        customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
    if not customer:
        raise AssertionError("No enabled Customer is available for transactional rollback acceptance.")
    return customer


def _new_sales_order(candidate: frappe._dict, qty: float = 2):
    target = candidate.target
    item = candidate.item
    order = frappe.get_doc(
        {
            "doctype": "Sales Order",
            "company": target.company,
            "customer": _customer(target.company),
            "order_type": "Sales",
            "transaction_date": today(),
            "delivery_date": add_days(today(), 1),
            "set_warehouse": target.warehouse,
            "custom_pharmacy_branch": target.branch,
            "reserve_stock": 1,
            "ignore_pricing_rule": 1,
            "items": [
                {
                    "item_code": item.item_code,
                    "qty": qty,
                    "rate": 1,
                    "delivery_date": add_days(today(), 1),
                    "warehouse": target.warehouse,
                    "reserve_stock": 1,
                }
            ],
        }
    )
    order.flags.ignore_permissions = True
    order.insert(ignore_permissions=True)
    order.submit()
    return order


def _reservation_for(order):
    row = order.items[0]
    names = frappe.get_all(
        "Stock Reservation Entry",
        filters={
            "voucher_type": "Sales Order",
            "voucher_no": order.name,
            "voucher_detail_no": row.name,
        },
        pluck="name",
        order_by="creation asc, name asc",
    )
    if not names:
        reserve_sales_order_item(order.name, row.name, qty_in_stock_uom=row.stock_qty)
        names = frappe.get_all(
            "Stock Reservation Entry",
            filters={
                "voucher_type": "Sales Order",
                "voucher_no": order.name,
                "voucher_detail_no": row.name,
            },
            pluck="name",
            order_by="creation asc, name asc",
        )
    _assert(len(names) == 1, f"Expected one reservation for owner line; found {len(names)}.")
    return frappe.get_doc("Stock Reservation Entry", names[0])


def _atp(candidate: frappe._dict) -> float:
    result = get_unified_stock_availability(
        item_code=candidate.item.item_code,
        branch=candidate.target.branch,
        operational_role="Sales",
        warehouse=candidate.target.warehouse,
        enforce_permissions=False,
    )
    return flt(result["quantities"]["available_to_promise"])


def run() -> dict[str, Any]:
    report: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "mode": "transactional_savepoint_rollback",
        "status": "FAIL",
        "failures": [],
        "checks": [],
        "temporary_documents": [],
    }
    installation = verify_installation()
    if installation["status"] != "PASS":
        report["failures"].extend(installation["failures"])
        return report
    report["checks"].append("installation_metadata_and_configuration")

    before = _counts()
    report["counts_before"] = before
    savepoint = "pharma_step2b_acceptance"
    frappe.db.savepoint(savepoint)
    try:
        candidate = _candidate()
        report["candidate"] = {
            "branch": candidate.target.branch,
            "warehouse": candidate.target.warehouse,
            "item_code": candidate.item.item_code,
        }
        atp_before = _atp(candidate)

        release_order = _new_sales_order(candidate, qty=2)
        report["temporary_documents"].append(release_order.name)
        release_sre = _reservation_for(release_order)
        report["temporary_documents"].append(release_sre.name)
        _assert(cint(release_sre.docstatus) == 1, "Standard SRE was not submitted.")
        _assert(release_sre.custom_contract_state == "Active", "New SRE is not Active.")
        _assert(
            release_sre.custom_pharmacy_branch == candidate.target.branch,
            "SRE canonical Branch mismatch.",
        )
        _assert(
            release_sre.warehouse == candidate.target.warehouse,
            "SRE canonical Warehouse mismatch.",
        )
        _assert(len(release_sre.custom_idempotency_key or "") == 64, "Missing idempotency key.")
        report["checks"].append("standard_sre_active_canonical_owner")

        atp_reserved = _atp(candidate)
        _assert(
            round(atp_before - atp_reserved, 6) == round(flt(release_sre.reserved_qty), 6),
            "Unified ATP did not decrease by the active reservation quantity.",
        )
        report["checks"].append("unified_atp_reduced_once")

        repeated = reserve_sales_order_item(
            release_order.name,
            release_order.items[0].name,
            qty_in_stock_uom=release_order.items[0].stock_qty,
        )
        _assert(repeated["reservation"] == release_sre.name, "Retry returned another SRE.")
        _assert(repeated["idempotent"] is True, "Retry was not reported as idempotent.")
        active_count = frappe.db.count(
            "Stock Reservation Entry",
            {
                "voucher_no": release_order.name,
                "voucher_detail_no": release_order.items[0].name,
                "docstatus": 1,
            },
        )
        _assert(active_count == 1, "Retry created a duplicate active reservation.")
        report["checks"].append("idempotent_retry_no_double_reservation")

        frappe.db.set_value(
            "Stock Reservation Entry",
            release_sre.name,
            "delivered_qty",
            flt(release_sre.reserved_qty) / 2,
            update_modified=False,
        )
        release_sre.reload()
        sync_standard_reservation_contract(release_sre)
        _assert(
            release_sre.custom_contract_state == "Partially Used",
            "Partial-use lifecycle mapping failed.",
        )
        frappe.db.set_value(
            "Stock Reservation Entry",
            release_sre.name,
            "delivered_qty",
            0,
            update_modified=False,
        )
        release_sre.reload()
        sync_standard_reservation_contract(release_sre)
        report["checks"].append("partial_use_state_mapping")

        released = _release_reservation(
            release_sre.name,
            reason="Step2B transactional rollback acceptance release",
            terminal_state="Released",
            ignore_permissions=True,
        )
        _assert(released["contract_state"] == "Released", "Controlled release failed.")
        released_doc = frappe.get_doc("Stock Reservation Entry", release_sre.name)
        _assert(cint(released_doc.docstatus) == 2, "Released SRE was not cancelled.")
        _assert(released_doc.custom_terminal_reason, "Release reason was not audited.")
        _assert(round(_atp(candidate), 6) == round(atp_before, 6), "Release did not restore ATP.")
        repeated_release = _release_reservation(
            release_sre.name,
            reason="Step2B repeated release must be idempotent",
            terminal_state="Released",
            ignore_permissions=True,
        )
        _assert(repeated_release["idempotent"] is True, "Repeated release was not idempotent.")
        _assert(
            round(_atp(candidate), 6) == round(atp_before, 6),
            "Repeated release changed ATP twice.",
        )
        report["checks"].append("controlled_release_restores_atp")

        expiry_order = _new_sales_order(candidate, qty=1)
        report["temporary_documents"].append(expiry_order.name)
        expiry_sre = _reservation_for(expiry_order)
        report["temporary_documents"].append(expiry_sre.name)
        frappe.db.set_value(
            "Stock Reservation Entry",
            expiry_sre.name,
            "custom_expires_at",
            add_to_date(now_datetime(), minutes=-1),
            update_modified=False,
        )
        expiry_result = expire_due_reservations(limit=10)
        _assert(not expiry_result["failures"], "Scheduled expiry reported failures.")
        expiry_sre.reload()
        _assert(cint(expiry_sre.docstatus) == 2, "Expired SRE was not cancelled.")
        _assert(expiry_sre.custom_contract_state == "Expired", "Expiry state was not audited.")
        _assert(expiry_sre.custom_terminal_reason, "Expiry reason was not audited.")
        repeated_expiry = expire_due_reservations(limit=10)
        _assert(not repeated_expiry["failures"], "Repeated expiry reported failures.")
        _assert(
            repeated_expiry["expired"] == 0,
            "Repeated expiry changed the terminal reservation twice.",
        )
        report["checks"].append("idempotent_scheduled_expiry")

        report["status"] = "PASS"
    except Exception as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        report["traceback"] = frappe.get_traceback()
    finally:
        frappe.db.rollback(save_point=savepoint)
        frappe.clear_cache()

    after = _counts()
    report["counts_after"] = after
    if after != before:
        report["failures"].append(
            f"Transactional verification leaked persistent rows: before={before}, after={after}"
        )
        report["status"] = "FAIL"
    report["temporary_documents_rolled_back"] = after == before
    return report
