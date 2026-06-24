"""Prepare legacy database-created financial DocTypes for app ownership.

This patch must run in [pre_model_sync], before the exported JSON schemas are
synchronised. It changes metadata ownership only and does not alter transactions.
"""

import frappe


DOCTYPE_NAMES = (
    "Card POS Terminal",
    "Card Settlement Batch Item",
    "Card Settlement Batch",
    "Card Bank Settlement Allocation",
    "Card Bank Settlement",
    "Payment Method Clearing Setup",
    "Shift Payment Reconciliation Item",
    "Shift Payment Reconciliation",
    "Shift Cash Movement",
)


def execute():
    for doctype_name in DOCTYPE_NAMES:
        if not frappe.db.exists("DocType", doctype_name):
            frappe.throw(
                "Required financial DocType is missing: " + doctype_name
            )

        frappe.db.set_value(
            "DocType",
            doctype_name,
            {
                "custom": 0,
                "module": "Pharma Erp",
            },
            update_modified=False,
        )

    frappe.clear_cache()
