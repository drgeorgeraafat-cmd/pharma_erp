"""Transactional savepoint acceptance for v0.9.2 Step2D R3."""

from __future__ import annotations

import frappe
from frappe.utils import flt

from pharma_erp.pharma_erp.customer_product_request_contract import CONTRACT_VERSION
from pharma_erp.pharma_erp.customer_product_request_service import (
    _match_direct_purchase_invoice,
    confirm_and_convert,
    create_customer_product_request,
    get_customer_product_request,
)
from pharma_erp.pharma_erp.install_customer_product_request_v0_9_2 import verify_installation
from pharma_erp.pharma_erp.unified_stock_availability import get_unified_stock_availability
from pharma_erp.pharma_erp.verify_customer_reservation_operations_v0_9_2 import (
    _candidate,
    _canonical_target,
    _customer,
)


COUNTERS = (
    "Comment", "Customer Product Request", "Customer Product Request Match",
    "Sales Order", "Stock Reservation Entry",
)


def _counts():
    return {name: frappe.db.count(name) for name in COUNTERS}


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def run():
    report = {
        "contract_version": CONTRACT_VERSION,
        "mode": "transactional_savepoint_rollback",
        "status": "FAIL", "failures": [], "checks": [], "temporary_documents": [],
    }
    installation = verify_installation()
    if installation["status"] != "PASS":
        report["failures"].extend(installation["failures"])
        return report
    report["checks"].append("installation_metadata_page_and_tables")
    before = _counts()
    report["counts_before"] = before
    savepoint = "pharma_step2d_acceptance"
    frappe.db.savepoint(savepoint)
    try:
        target = _canonical_target()
        candidate = _candidate(target)
        customer = _customer(target.company)
        availability = get_unified_stock_availability(
            item_code=candidate.item_code, branch=target.branch,
            operational_role="Sales", warehouse=target.warehouse,
            source_type="stock", enforce_permissions=False,
        )
        atp_before = flt(availability["quantities"]["available_to_promise"], 6)
        _assert(atp_before >= 2, "Step2D acceptance requires at least two ATP units.")
        sre_before = frappe.db.count("Stock Reservation Entry")
        request = create_customer_product_request({
            "customer": customer, "company": target.company, "branch": target.branch,
            "contact_mobile": "01000000000", "source": "Phone",
            "items": [{"item_code": candidate.item_code, "requested_qty": atp_before + 1}],
            "notes": "Step2D transactional rollback acceptance",
            "request_token": "step2d-transactional-savepoint",
        })
        report["temporary_documents"].append(request["request"])
        _assert(request["status"] == "Waiting for Stock", "New request is not waiting for stock.")
        _assert(frappe.db.count("Stock Reservation Entry") == sre_before, "Creating a product request created an SRE.")
        atp_after_request = flt(get_unified_stock_availability(
            item_code=candidate.item_code, branch=target.branch,
            operational_role="Sales", warehouse=target.warehouse,
            source_type="stock", enforce_permissions=False,
        )["quantities"]["available_to_promise"], 6)
        _assert(atp_after_request == atp_before, "Creating a product request changed ATP.")
        report["checks"].append("request_does_not_reserve_or_reduce_atp")

        direct_invoice = frappe._dict({
            "doctype": "Purchase Invoice",
            "name": "STEP2D-R4-DIRECT-PI-TEST",
            "docstatus": 1,
            "update_stock": 1,
            "is_return": 0,
            "items": [frappe._dict({
                "item_code": candidate.item_code,
                "purchase_receipt": "",
                "pr_detail": "",
            })],
        })
        match = _match_direct_purchase_invoice(direct_invoice, notify=False)
        request = get_customer_product_request(request["request"])
        _assert(not match["ignored"], "Eligible direct Purchase Invoice was ignored.")
        _assert(match["matched_lines"] >= 1, "Direct Purchase Invoice matching did not find available quantity.")
        _assert(request["items"][0]["matched_qty"] == atp_before, "Persistent match does not equal the FIFO ATP pool.")
        _assert(frappe.db.count("Customer Product Request Match", {"request": request["request"]}) == 1, "Persistent match was not created exactly once.")
        match_row = frappe.db.get_value(
            "Customer Product Request Match",
            {"request": request["request"]},
            ["source_type", "source_name"],
            as_dict=True,
        )
        _assert(match_row.source_type == "Purchase Invoice", "Direct PI match source type was not preserved.")
        _assert(match_row.source_name == direct_invoice.name, "Direct PI match source name was not preserved.")
        _assert(frappe.db.count("Stock Reservation Entry") == sre_before, "Matching created an SRE before confirmation.")

        # Retrying the same direct source updates the stable match row.  A PI
        # backed by Purchase Receipt, a non-stock PI, and a return are ignored.
        _match_direct_purchase_invoice(direct_invoice, notify=False)
        _assert(frappe.db.count("Customer Product Request Match", {"request": request["request"]}) == 1, "Direct PI retry duplicated the match row.")
        for ignored_invoice in (
            frappe._dict({
                "name": "STEP2D-R4-LINKED-PI-TEST", "docstatus": 1,
                "update_stock": 1, "is_return": 0,
                "items": [frappe._dict({
                    "item_code": candidate.item_code,
                    "purchase_receipt": "MAT-PRE-TEST",
                    "pr_detail": "MAT-PRE-DETAIL-TEST",
                })],
            }),
            frappe._dict({
                "name": "STEP2D-R4-NONSTOCK-PI-TEST", "docstatus": 1,
                "update_stock": 0, "is_return": 0,
                "items": [frappe._dict({"item_code": candidate.item_code})],
            }),
            frappe._dict({
                "name": "STEP2D-R4-RETURN-PI-TEST", "docstatus": 1,
                "update_stock": 1, "is_return": 1,
                "items": [frappe._dict({"item_code": candidate.item_code})],
            }),
        ):
            ignored = _match_direct_purchase_invoice(ignored_invoice, notify=False)
            _assert(ignored["ignored"], f"Ineligible Purchase Invoice {ignored_invoice.name} was not ignored.")
        _assert(frappe.db.count("Customer Product Request Match", {"request": request["request"]}) == 1, "Ignored PI path changed the stable match count.")
        report["checks"].append("direct_purchase_invoice_match_is_fifo_non_reserving_idempotent_and_receipt_safe")

        conversion = confirm_and_convert(request["request"], "Pickup", allow_partial=1, notes="Confirmed in Step2D transactional acceptance")
        _assert(conversion["partial"], "Expected explicit partial conversion for ATP+1 request.")
        _assert(len(conversion["reservations"]) == 1, "Expected exactly one Step2C reservation.")
        report["temporary_documents"].extend(conversion["reservations"])
        _assert(frappe.db.count("Stock Reservation Entry") == sre_before + 1, "Confirmed conversion did not create exactly one standard SRE.")
        order = frappe.get_doc("Sales Order", conversion["reservations"][0])
        _assert(order.custom_customer_reservation == 1, "Conversion did not use the closed Step2C contract.")
        _assert(not order.get("custom_online_order"), "Step2D conversion was incorrectly linked to Online Order.")
        report["checks"].append("confirmed_contact_converts_idempotently_to_step2c")
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
        report["failures"].append(f"Transactional verification leaked rows: before={before}, after={after}")
        report["status"] = "FAIL"
    report["temporary_documents_rolled_back"] = after == before
    return report
