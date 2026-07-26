"""Repair Credit Note movements for Internal Retail Price Lots (v0.7.65 Step 6C v2.2)."""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

from pharma_erp.retail_price_lots import rebuild_sales_lot_balances


STEP = "v0.7.65 Step 6C v2.2 — Sales Return Retail Lot Reversal"
SAMPLE_RETURN = "ACC-SINV-2026-00314"
SAMPLE_LOT = "RPL-2026-00092"


def _sample_state():
    invoice = None
    items = []
    lot = None

    if frappe.db.exists("Sales Invoice", SAMPLE_RETURN):
        invoice = frappe.db.get_value(
            "Sales Invoice",
            SAMPLE_RETURN,
            [
                "name",
                "docstatus",
                "status",
                "is_return",
                "return_against",
                "update_stock",
                "custom_retail_lot_posted",
            ],
            as_dict=True,
        )
        items = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": SAMPLE_RETURN},
            fields=[
                "name",
                "item_code",
                "stock_qty",
                "sales_invoice_item",
                "custom_retail_price_lot",
                "custom_stock_source_mode",
            ],
            order_by="idx asc",
            limit_page_length=0,
        )
    if frappe.db.exists("Internal Retail Price Lot", SAMPLE_LOT):
        lot = frappe.db.get_value(
            "Internal Retail Price Lot",
            SAMPLE_LOT,
            [
                "name",
                "item_code",
                "warehouse",
                "retail_price",
                "received_qty",
                "sold_qty",
                "returned_qty",
                "available_qty",
                "status",
            ],
            as_dict=True,
        )
    return {"invoice": invoice, "items": items, "lot": lot}


def preview():
    reconciliation = rebuild_sales_lot_balances(apply=False)
    return {
        "status": "ok",
        "step": STEP,
        "reconciliation": reconciliation,
        "sample": _sample_state(),
        "policy": {
            "new_returns_start_unposted": True,
            "server_recovers_lot_from_sales_invoice_item": True,
            "existing_return_repair_is_lot_metadata_only": True,
            "stock_ledger_impact": False,
            "gl_impact": False,
            "sales_invoice_update": False,
        },
    }


def install():
    before = rebuild_sales_lot_balances(apply=False)
    applied = rebuild_sales_lot_balances(apply=True)
    after = rebuild_sales_lot_balances(apply=False)
    frappe.db.commit()
    return {
        "status": "ok",
        "step": STEP,
        "before": before,
        "applied": applied,
        "after": after,
        "sample": _sample_state(),
        "stock_ledger_impact": False,
        "gl_impact": False,
        "sales_invoice_update": False,
    }
