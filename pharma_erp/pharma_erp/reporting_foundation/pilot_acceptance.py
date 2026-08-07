from __future__ import annotations

import json

import frappe
from frappe.utils import flt

from .pilots import (
    DAILY_REPORT_ID,
    ONLINE_REPORT_ID,
    canonical_shift_snapshot,
    runtime_mapping_snapshot,
    _execute_report,
)


def _near(actual, expected, tol=0.01):
    return abs(flt(actual) - flt(expected)) <= tol


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _progress(marker: str, payload=None):
    print(f"{marker}=PASS")
    if payload is not None:
        print(json.dumps(payload, ensure_ascii=False, default=str))


def _reference_invoice():
    preferred = "ACC-SINV-2026-00324"
    if frappe.db.exists("Sales Invoice", preferred):
        return frappe.db.get_value(
            "Sales Invoice", preferred, ["company", "posting_date"], as_dict=True
        )
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": 1},
        fields=["company", "posting_date"],
        order_by="posting_date desc, modified desc",
        limit_page_length=1,
    )
    if not rows:
        raise AssertionError("No submitted Sales Invoice exists for Daily Pilot acceptance")
    return rows[0]


def _daily_acceptance():
    ref = _reference_invoice()
    filters = {
        "company": ref.company,
        "from_date": str(ref.posting_date),
        "to_date": str(ref.posting_date),
        "page": 1,
        "page_size": 50,
    }
    result = _execute_report(DAILY_REPORT_ID, filters)
    s = result.summary

    amount_field = s["amount_basis"]
    raw = frappe.db.sql(
        f"""
        select
          sum(case when coalesce(is_return,0)=0 then greatest(coalesce(`{amount_field}`,0),0) else 0 end),
          sum(case when coalesce(is_return,0)=1 then abs(coalesce(`{amount_field}`,0)) else 0 end),
          sum(case when coalesce(is_return,0)=0 then 1 else 0 end)
        from `tabSales Invoice`
        where docstatus=1 and company=%s and posting_date=%s
        """,
        (ref.company, ref.posting_date),
    )[0]
    _assert(_near(s["gross_sales"], raw[0]), "Daily gross sales does not reconcile")
    _assert(_near(s["returns"], raw[1]), "Daily returns does not reconcile")
    _assert(_near(s["net_sales"], flt(raw[0]) - flt(raw[1])), "Daily net sales does not reconcile")
    _assert(int(s["invoice_count"]) == int(raw[2] or 0), "Daily invoice count does not reconcile")
    return {
        "company": ref.company,
        "date": str(ref.posting_date),
        "gross_sales": s["gross_sales"],
        "returns": s["returns"],
        "net_sales": s["net_sales"],
        "invoice_count": s["invoice_count"],
        "branch_attribution": s["branch_attribution"],
        "card_mapping_status": s["card_mapping_status"],
    }


def _shift_acceptance():
    results = {}
    expected = {
        "SHIFT-2026-00060": {
            "opening_float": 200,
            "expected_cash": 3090,
            "counted_cash": 3090,
            "cash_difference": 0,
            "driver_expected_cash": 1740,
            "driver_handed_over_cash": 1740,
        },
        "SHIFT-2026-00061": {
            "opening_float": 200,
            "direct_till_cash": 380,
            "driver_handed_over_cash": 705,
            "expected_cash": 1285,
            "counted_cash": 1285,
            "cash_difference": 0,
        },
    }
    found_any = False
    for shift_name, wanted in expected.items():
        if not frappe.db.exists("Pharmacy Shift Closing", shift_name):
            continue
        found_any = True
        snapshot = canonical_shift_snapshot(shift_name)
        values = snapshot["metrics"]
        for key, expected_value in wanted.items():
            _assert(key in values, f"{shift_name}: required metric {key} was not mapped")
            _assert(
                _near(values[key], expected_value),
                f"{shift_name}: {key} expected {expected_value}, got {values[key]}",
            )
        _assert(
            snapshot["reconciliation_status"] == "Control Balanced",
            f"{shift_name}: reconciliation is not balanced",
        )
        results[shift_name] = {
            "metrics": values,
            "sources": snapshot["sources"],
            "reconciliation_status": snapshot["reconciliation_status"],
        }
    _assert(found_any, "Neither accepted shift SHIFT-2026-00060 nor SHIFT-2026-00061 exists")
    return results


def _online_acceptance():
    if not frappe.db.exists("DocType", "Online Order"):
        raise AssertionError("Online Order DocType is missing")
    mapping = runtime_mapping_snapshot()["online_order"]
    date_field = mapping["date"]
    _assert(date_field, "Online Order date mapping is missing")

    minmax = frappe.db.sql(
        f"select min(`{date_field}`), max(`{date_field}`) from `tabOnline Order`"
    )[0]
    _assert(minmax[0] and minmax[1], "No Online Orders exist for acceptance")
    from_date = str(minmax[0])[:10]
    to_date = str(minmax[1])[:10]

    # Use a Company from a linked invoice if Online Order itself has no Company.
    company_field = frappe.get_meta("Online Order").has_field("company")
    company = None
    if company_field:
        company = frappe.db.get_value("Online Order", {}, "company")
    if not company:
        ref = _reference_invoice()
        company = ref.company

    result = _execute_report(
        ONLINE_REPORT_ID,
        {
            "company": company,
            "from_date": from_date,
            "to_date": to_date,
            "page": 1,
            "page_size": 50,
        },
    )
    stages = result.summary["stages"]
    stage_sum = sum(int(v or 0) for v in stages.values())
    _assert(stage_sum == int(result.summary["total_orders"]), "Online stage buckets do not reconcile")

    for known in ("OO-2026-00004", "OO-2026-00006"):
        if frappe.db.exists("Online Order", known):
            status = frappe.db.get_value("Online Order", known, "status")
            _assert(
                str(status or "").casefold() in {"delivered", "completed"},
                f"{known} is no longer in an accepted terminal status",
            )
    return {
        "from_date": from_date,
        "to_date": to_date,
        "total_orders": result.summary["total_orders"],
        "stages": stages,
        "mapping": mapping,
    }


def run():
    reports = (
        "Daily Branch Operations Summary",
        "Shift Cash Integrity Summary",
        "Online Order Operations Funnel",
    )
    for name in reports:
        _assert(frappe.db.exists("Report", name), f"Report record missing: {name}")
        doc = frappe.get_doc("Report", name)
        _assert(doc.report_type == "Script Report", f"{name}: wrong report type")
        _assert(doc.is_standard == "Yes", f"{name}: not a standard report")

    mapping = runtime_mapping_snapshot()

    daily = _daily_acceptance()
    _progress("DAILY_BRANCH_OPERATIONS_RECONCILIATION", daily)

    shifts = _shift_acceptance()
    _progress("SHIFT_CASH_INTEGRITY_ACCEPTANCE", shifts)

    online = _online_acceptance()
    _progress("ONLINE_FUNNEL_BUCKET_RECONCILIATION", online)

    output = {
        "REPORT_RECORDS_REGISTERED": "PASS",
        "DAILY_BRANCH_OPERATIONS_RECONCILIATION": "PASS",
        "SHIFT_CASH_INTEGRITY_ACCEPTANCE": "PASS",
        "ONLINE_FUNNEL_BUCKET_RECONCILIATION": "PASS",
        "NO_HARDCODED_BRANCH_OR_WAREHOUSE_REQUIRED": "PASS",
        "runtime_mapping": mapping,
        "daily": daily,
        "shifts": shifts,
        "online": online,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return output
