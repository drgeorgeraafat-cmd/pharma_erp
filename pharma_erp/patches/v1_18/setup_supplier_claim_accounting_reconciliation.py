from __future__ import annotations

import json
import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.modules.import_file import import_file_by_path
from frappe.utils import flt

from pharma_erp.pharma_erp.supplier_claim_accounting import (
    ensure_supplier_settlement_discount_account,
)


def _import_doctype(doctype_folder, doctype_name):
    path = frappe.get_app_path(
        "pharma_erp", "pharma_erp", "doctype", doctype_folder, f"{doctype_folder}.json"
    )
    if not os.path.exists(path):
        frappe.throw(f"Missing DocType JSON file: {path}")
    import_file_by_path(path, force=True)
    frappe.clear_cache(doctype=doctype_name)
    frappe.db.updatedb(doctype_name)


def execute():
    _import_doctype("supplier_claim", "Supplier Claim")
    _import_doctype("supplier_claim_invoice", "Supplier Claim Invoice")

    create_custom_fields(
        {
            "Payment Entry": [
                {
                    "fieldname": "custom_supplier_claim",
                    "label": "Supplier Claim",
                    "fieldtype": "Link",
                    "options": "Supplier Claim",
                    "insert_after": "reference_date",
                    "read_only": 1,
                    "no_copy": 1,
                    "allow_on_submit": 1,
                }
            ],
            "Journal Entry": [
                {
                    "fieldname": "custom_supplier_claim",
                    "label": "Supplier Claim",
                    "fieldtype": "Link",
                    "options": "Supplier Claim",
                    "insert_after": "user_remark",
                    "read_only": 1,
                    "no_copy": 1,
                    "allow_on_submit": 1,
                }
            ],
        },
        update=True,
    )

    for company in frappe.get_all("Company", pluck="name"):
        ensure_supplier_settlement_discount_account(company)

    for name in frappe.get_all("Supplier Claim", filters={"docstatus": 1}, pluck="name"):
        claim = frappe.get_doc("Supplier Claim", name)
        updates = {}
        if flt(claim.settlement_discount_amount) > 0 and not claim.settlement_discount_account:
            updates["settlement_discount_account"] = ensure_supplier_settlement_discount_account(
                claim.company
            )

        all_zero = True
        for row in claim.invoices:
            outstanding = flt(
                frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "outstanding_amount")
            )
            if abs(outstanding) > 0.01:
                all_zero = False
                break

        if claim.status == "Paid":
            updates["accounting_settlement_status"] = (
                "Reconciled" if all_zero else "Needs Reconciliation"
            )
        elif not claim.accounting_settlement_status:
            updates["accounting_settlement_status"] = "Pending"

        if updates:
            frappe.db.set_value(
                "Supplier Claim", claim.name, updates, update_modified=False
            )

        # Re-open operational settlement labels for legacy claims that were marked
        # Paid without an accounting reconciliation. No GL/Payment Ledger entries
        # are changed by this synchronization.
        refreshed = frappe.get_doc("Supplier Claim", claim.name)
        if refreshed.status == "Paid" and refreshed.accounting_settlement_status != "Reconciled":
            refreshed._sync_return_cases(cancel=False)

    frappe.clear_cache()
