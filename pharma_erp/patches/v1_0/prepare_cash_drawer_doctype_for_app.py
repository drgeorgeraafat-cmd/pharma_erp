"""Prepare the legacy database-created Cash Drawer for app ownership.

This patch must run in [pre_model_sync] before the exported DocType JSON is
synchronised. It changes metadata ownership only and does not alter drawer or
account transactions.
"""

import frappe


DOCTYPE_NAME = "Cash Drawer"


def execute():
    if not frappe.db.exists("DocType", DOCTYPE_NAME):
        frappe.throw("Required DocType is missing: " + DOCTYPE_NAME)

    frappe.db.set_value(
        "DocType",
        DOCTYPE_NAME,
        {
            "custom": 0,
            "module": "Pharma Erp",
        },
        update_modified=False,
    )
    frappe.clear_cache()
