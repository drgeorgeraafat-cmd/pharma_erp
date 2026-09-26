from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from pharma_erp.pharma_erp.inventory_count_service import (
    COUNT_DOCTYPE,
    SETTINGS_DOCTYPE,
    _available_batches_for_adjustment,
    get_official_warehouse_qty,
)

REQUIRED_DOCTYPES = [
    "Pharmacy Inventory Count Settings",
    "Pharmacy Inventory Count",
    "Pharmacy Inventory Count Item",
    "Pharmacy Inventory Count Event",
]
REQUIRED_ROLES = [
    "Inventory Counter",
    "Inventory Reviewer",
    "Inventory Approver",
    "Inventory High Variance Approver",
    "Inventory Stock Poster",
]


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _candidate():
    rows = frappe.db.sql(
        """
        SELECT b.warehouse, b.item_code, b.actual_qty, COALESCE(b.reserved_qty,0) AS reserved_qty,
               i.has_batch_no, i.has_serial_no, i.disabled AS item_disabled,
               w.company, p.branch
        FROM `tabBin` b
        INNER JOIN `tabItem` i ON i.name=b.item_code
        INNER JOIN `tabWarehouse` w ON w.name=b.warehouse
        INNER JOIN `tabPharmacy Warehouse Profile` p ON p.warehouse=b.warehouse
        WHERE b.actual_qty >= 3
          AND COALESCE(b.reserved_qty,0) <= 0.000000001
          AND i.disabled=0
          AND i.is_stock_item=1
          AND i.has_serial_no=0
          AND w.disabled=0
          AND w.is_group=0
          AND p.disabled=0
          AND p.physicality='Physical'
        ORDER BY i.has_batch_no ASC, b.actual_qty DESC
        LIMIT 100
        """,
        as_dict=True,
    )
    for row in rows:
        if not cint(row.has_batch_no):
            return row
        available = _available_batches_for_adjustment(row.item_code, row.warehouse)
        if sum(flt(batch.qty) for batch in available) >= 2:
            return row
    return None


def run():
    original_user = frappe.session.user or "Administrator"
    frappe.set_user("Administrator")
    try:
        for dt in REQUIRED_DOCTYPES:
            _assert(frappe.db.exists("DocType", dt), f"Missing DocType: {dt}")
        for role in REQUIRED_ROLES:
            _assert(frappe.db.exists("Role", role), f"Missing Role: {role}")

        final_feature_state = int(frappe.db.get_single_value(SETTINGS_DOCTYPE, "enable_inventory_count") or 0)
        _assert(final_feature_state == 0, "Inventory Count feature flag must be OFF before controlled verification")

        candidate = _candidate()
        _assert(candidate, "No safe stock candidate (qty >= 3, no reservation, non-serialized) for transactional verification")

        frappe.db.savepoint("inventory_count_verify")
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "enable_inventory_count", 1)
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "require_recount_for_full_shortage", 0)
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "high_variance_value_threshold", 0)
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "high_variance_percentage_threshold", 0)
        frappe.clear_cache(doctype=SETTINGS_DOCTYPE)

        initial_qty = flt(get_official_warehouse_qty(candidate.item_code, candidate.warehouse), 6)
        count = frappe.get_doc(
            {
                "doctype": COUNT_DOCTYPE,
                "company": candidate.company,
                "branch": candidate.branch,
                "scope_type": "Item",
                "warehouse": candidate.warehouse,
                "item_code": candidate.item_code,
                "blind_count": 1,
            }
        )
        count.flags.ignore_permissions = True
        count.insert(ignore_permissions=True)
        start = count.start_count()
        _assert(start["row_count"] == 1, "Item Count must create exactly one expected row")

        missing = count.complete_count()
        _assert(not missing["completed"] and missing["missing_count"] == 1, "Missing expected item guard failed")

        count.reload()
        row = count.items[0]
        row.actual_qty = flt(initial_qty - 1, 6)
        row.count_entered = 1
        row.resolution_status = "Counted"
        row.reason_code = "Data Entry Error"
        count.save(ignore_permissions=True)

        completed = count.complete_count()
        _assert(completed["completed"], "Count completion failed after explicit physical count")
        count.begin_review()
        count.reload()
        count.items[0].reason_code = "Data Entry Error"
        count.save(ignore_permissions=True)
        approved = count.approve_count()
        _assert(approved["status"] == "Approved", "Approval failed")

        posted = count.post_count()
        _assert(posted["status"] == "Posted", "Posting failed")
        _assert(posted["stock_reconciliation"], "Warehouse variance must create Stock Reconciliation")
        reco_status = frappe.db.get_value("Stock Reconciliation", posted["stock_reconciliation"], "docstatus")
        _assert(cint(reco_status) == 1, "Stock Reconciliation was not submitted")

        after_post = flt(get_official_warehouse_qty(candidate.item_code, candidate.warehouse), 6)
        _assert(abs(after_post - flt(initial_qty - 1, 6)) < 0.000001, "Posted warehouse quantity mismatch")

        duplicate = count.post_count()
        _assert(duplicate.get("idempotent") is True, "Post idempotency failed")
        _assert(duplicate.get("stock_reconciliation") == posted["stock_reconciliation"], "Idempotent post changed reconciliation")

        cancelled = count.cancel_count("Automated v0.9.3 Inventory Count verification rollback")
        _assert(cancelled["status"] == "Cancelled", "Controlled cancellation failed")
        restored = flt(get_official_warehouse_qty(candidate.item_code, candidate.warehouse), 6)
        _assert(abs(restored - initial_qty) < 0.000001, "Cancellation did not restore warehouse stock")

        event_count = frappe.db.count("Pharmacy Inventory Count Event", {"inventory_count": count.name})
        _assert(event_count >= 5, "Expected Inventory Count audit events were not written")

        result = {
            "status": "PASS",
            "candidate": {
                "warehouse": candidate.warehouse,
                "item_code": candidate.item_code,
                "has_batch_no": cint(candidate.has_batch_no),
                "initial_qty": initial_qty,
            },
            "inventory_count": count.name,
            "stock_reconciliation": posted["stock_reconciliation"],
            "missing_guard": "PASS",
            "posting": "PASS",
            "idempotency": "PASS",
            "cancellation": "PASS",
            "audit_events": event_count,
            "transaction_rolled_back": True,
            "feature_flag_final_expected": "OFF",
        }
        frappe.db.rollback(save_point="inventory_count_verify")
        frappe.db.set_single_value(SETTINGS_DOCTYPE, "enable_inventory_count", 0)
        frappe.db.rollback()
        return result
    except Exception:
        try:
            frappe.db.rollback(save_point="inventory_count_verify")
        except Exception:
            frappe.db.rollback()
        raise
    finally:
        frappe.set_user(original_user)
