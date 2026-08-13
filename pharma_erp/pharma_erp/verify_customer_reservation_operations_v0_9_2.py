"""Transactional savepoint/rollback acceptance for v0.9.2 Step2C R7."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import add_to_date, cint, flt, now_datetime

from pharma_erp.pharma_erp.customer_reservation_service import (
    create_customer_reservation,
    get_customer_reservation_pos_context,
)
from pharma_erp.pharma_erp.install_customer_reservation_operations_v0_9_2 import (
    verify_installation,
)
from pharma_erp.pharma_erp.page.pharmacy_pos.api import (
    _append_invoice_items,
)
from pharma_erp.pharma_erp.unified_stock_availability import (
    get_unified_stock_availability,
)
from pharma_erp.retail_price_lots import (
    LOT_DOCTYPE,
    LOT_FIELD,
    get_available_retail_lots,
)


CONTRACT_VERSION = "v0.9.2-step2c-r7"
COUNTER_DOCTYPES = (
    "Comment",
    "GL Entry",
    "Sales Invoice",
    "Sales Order",
    "Stock Ledger Entry",
    "Stock Reservation Entry",
)


def _counts() -> dict[str, int]:
    return {doctype: frappe.db.count(doctype) for doctype in COUNTER_DOCTYPES}


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _canonical_target() -> frappe._dict:
    rows = frappe.db.sql(
        """
        SELECT
            bp.branch, r.warehouse, bp.company
        FROM `tabPharmacy Branch Warehouse Role` r
        INNER JOIN `tabPharmacy Branch Profile` bp
            ON bp.name=r.parent
            AND r.parenttype='Pharmacy Branch Profile'
            AND bp.disabled=0
        INNER JOIN `tabPharmacy Warehouse Profile` wp
            ON wp.warehouse=r.warehouse AND wp.branch=bp.branch
            AND wp.company=bp.company AND wp.disabled=0
        WHERE r.operational_role='Sales'
          AND bp.allow_reservation=1
          AND wp.is_sellable=1
          AND wp.allow_reservation=1
        ORDER BY bp.branch ASC, r.warehouse ASC
        """,
        as_dict=True,
    )
    if not rows:
        raise AssertionError("No canonical Sales target is enabled for reservation.")
    return frappe._dict(rows[0])


def _candidate(target: frappe._dict) -> frappe._dict:
    rows = frappe.db.sql(
        """
        SELECT b.item_code, b.actual_qty, i.item_name, i.stock_uom
        FROM `tabBin` b
        INNER JOIN `tabItem` i ON i.name=b.item_code
        WHERE b.warehouse=%s
          AND b.actual_qty>=2
          AND i.disabled=0
          AND i.is_stock_item=1
          AND i.has_serial_no=0
          AND i.has_batch_no=0
        ORDER BY b.actual_qty DESC, b.item_code ASC
        """,
        (target.warehouse,),
        as_dict=True,
    )
    for row in rows:
        lots = get_available_retail_lots(row.item_code, target.warehouse) or []
        if lots and not any(flt(lot.available_qty) >= 1 for lot in lots):
            continue
        availability = get_unified_stock_availability(
            item_code=row.item_code,
            branch=target.branch,
            operational_role="Sales",
            warehouse=target.warehouse,
            source_type="stock",
            enforce_permissions=False,
        )
        if flt(availability["quantities"]["available_to_promise"]) >= 2:
            return frappe._dict(row)
    raise AssertionError(
        "No non-batch, non-serial canonical Sales item has at least two ATP units."
    )


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
        raise AssertionError("No enabled Customer is available for Step2C acceptance.")
    return customer


def _pos_payment_account(company: str) -> frappe._dict:
    preferred = ""
    if (
        frappe.db.exists("DocType", "Pharmacy POS Settings")
        and frappe.get_meta("Pharmacy POS Settings").has_field(
            "default_mode_of_payment"
        )
    ):
        preferred = (
            frappe.db.get_single_value(
                "Pharmacy POS Settings", "default_mode_of_payment"
            )
            or ""
        )

    rows = frappe.db.sql(
        """
        SELECT
            mpa.parent AS mode_of_payment,
            mpa.default_account AS account,
            mop.type AS payment_type
        FROM `tabMode of Payment Account` mpa
        INNER JOIN `tabMode of Payment` mop ON mop.name=mpa.parent
        WHERE mpa.company=%s
          AND mop.enabled=1
          AND COALESCE(mpa.default_account, '')<>''
        ORDER BY
            CASE WHEN mpa.parent=%s THEN 0 ELSE 1 END,
            CASE WHEN mop.type='Cash' THEN 0 ELSE 1 END,
            mpa.parent ASC
        """,
        (company, preferred),
        as_dict=True,
    )
    if not rows:
        raise AssertionError(
            f"No enabled Mode of Payment has a default account for company {company}."
        )
    return frappe._dict(rows[0])


def _fulfil_by_sales_invoice(
    reservation: dict[str, Any], target: frappe._dict, candidate: frappe._dict
):
    owner = reservation["items"][0]
    rate = flt(owner.get("rate"))
    price_list_rate = flt(owner.get("price_list_rate") or rate)
    discount_percentage = flt(owner.get("discount_percentage"))
    _assert(rate > 0, "Reserved Sales Order Item rate is not positive.")
    invoice = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "company": target.company,
            "customer": reservation["customer"],
            "is_pos": 1,
            "update_stock": 1,
            "set_warehouse": target.warehouse,
            "custom_pharmacy_branch": target.branch,
            "custom_order_type": "Walk In",
        }
    )
    _append_invoice_items(
        invoice,
        frappe._dict(
            {
                "items": [
                    {
                        "item_code": candidate.item_code,
                        "box_qty": 1,
                        "unit_qty": 0,
                        "qty": 1,
                        "price_list_rate": price_list_rate,
                        "discount_percentage": discount_percentage,
                        "rate": rate,
                        "reservation_sales_order": reservation["sales_order"],
                        "reservation_so_detail": owner["sales_order_item"],
                        "reservation_sre": owner["reservation"],
                    }
                ]
            }
        ),
        frappe._dict(
            {
                "warehouse": target.warehouse,
                "cost_center": frappe.db.get_value(
                    "Company", target.company, "cost_center"
                ),
                "contract": None,
            }
        ),
    )
    invoice.flags.ignore_permissions = True
    invoice.ignore_pricing_rule = 1
    invoice.set_missing_values()
    invoice.insert(ignore_permissions=True)

    payment_amount = flt(invoice.rounded_total or invoice.grand_total, 6)
    _assert(payment_amount > 0, "Temporary POS invoice total is not positive.")
    current_payment_total = flt(
        sum(flt(row.amount) for row in (invoice.payments or [])), 6
    )
    if current_payment_total + 1e-9 < payment_amount:
        payment = _pos_payment_account(target.company)
        invoice.set("payments", [])
        invoice.append(
            "payments",
            {
                "mode_of_payment": payment.mode_of_payment,
                "amount": payment_amount,
                "account": payment.account,
            },
        )
        invoice.save(ignore_permissions=True)

    invoice.submit()
    return invoice


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
    report["checks"].append("installation_metadata_and_page")

    before = _counts()
    report["counts_before"] = before
    savepoint = "pharma_step2c_acceptance"
    frappe.db.savepoint(savepoint)
    try:
        target = _canonical_target()
        candidate = _candidate(target)
        customer = _customer(target.company)
        report["candidate"] = {
            "branch": target.branch,
            "warehouse": target.warehouse,
            "item_code": candidate.item_code,
            "customer": customer,
        }

        reservation = create_customer_reservation(
            {
                "customer": customer,
                "company": target.company,
                "branch": target.branch,
                "warehouse": target.warehouse,
                "item_code": candidate.item_code,
                "qty": 1,
                "review_at": add_to_date(now_datetime(), hours=4),
                "fulfilment_mode": "Pickup",
                "notes": "Step2C transactional rollback acceptance",
                "request_token": "step2c-transactional-savepoint",
            }
        )
        report["temporary_documents"].append(reservation["sales_order"])
        _assert(reservation["operational_status"] == "Active", "New reservation is not Active.")
        _assert(len(reservation["items"]) == 1, "Expected exactly one reserved owner line.")
        owner = reservation["items"][0]
        report["temporary_documents"].append(owner["reservation"])
        _assert(owner["reservation_docstatus"] == 1, "Standard SRE was not submitted.")
        _assert(owner["remaining_qty"] == 1, "Reserved quantity does not equal one stock unit.")
        report["checks"].append("customer_reservation_creates_standard_sre")

        pos_context = get_customer_reservation_pos_context(
            reservation["sales_order"], "Pickup"
        )
        _assert(pos_context["order_type"] == "Walk In", "Pickup did not map to Walk In POS.")
        _assert(pos_context["customer"] == customer, "POS customer ownership mismatch.")
        _assert(pos_context["items"][0]["sales_order_item"] == owner["sales_order_item"], "POS owner line mismatch.")
        report["checks"].append("pharmacy_pos_context_preserves_reservation_owner")

        invoice = _fulfil_by_sales_invoice(reservation, target, candidate)
        report["temporary_documents"].append(invoice.name)
        _assert(cint(invoice.docstatus) == 1, "Fulfilment Sales Invoice was not submitted.")
        linked_rows = [
            row
            for row in invoice.items
            if row.sales_order == reservation["sales_order"]
            and row.so_detail == owner["sales_order_item"]
        ]
        _assert(linked_rows, "Invoice lost Sales Order Item ownership.")
        linked_qty = flt(sum(flt(row.qty) for row in linked_rows), 6)
        linked_net_rate = flt(
            sum(flt(row.qty) * flt(row.rate) for row in linked_rows)
            / linked_qty,
            6,
        )
        linked_list_rate = flt(
            sum(
                flt(row.qty) * flt(row.price_list_rate or row.rate)
                for row in linked_rows
            )
            / linked_qty,
            6,
        )
        _assert(
            abs(linked_net_rate - flt(owner["rate"])) <= 0.005,
            "Fulfilment invoice changed the weighted reservation rate.",
        )
        _assert(
            abs(linked_list_rate - flt(owner["price_list_rate"])) <= 0.005,
            "Fulfilment invoice changed the weighted reservation list rate.",
        )
        report["reservation_source_price"] = {
            "sales_order_rate": flt(owner["rate"]),
            "invoice_weighted_rate": linked_net_rate,
            "source_rows": len(linked_rows),
        }
        report["checks"].append("canonical_source_price_matches_pos_fulfilment")

        sre = frappe.get_doc("Stock Reservation Entry", owner["reservation"])
        _assert(flt(sre.delivered_qty) >= 1, "Standard SRE delivered quantity was not consumed.")
        order = frappe.get_doc("Sales Order", reservation["sales_order"])
        _assert(order.custom_reservation_fulfilment_invoice == invoice.name, "Sales Order did not record the POS fulfilment invoice.")
        _assert(order.custom_reservation_operational_status == "Picked Up", "Pickup did not reach Picked Up status.")
        report["checks"].append("standard_sre_consumed_by_linked_sales_invoice")
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
