from __future__ import annotations

import json
import os

import frappe
from frappe.modules.import_file import import_file_by_path


ITEM_FIELDS = (
    "base_rate",
    "discount_percentage",
    "pricing_input_mode",
    "is_vat_taxable",
    "vat_rate",
    "vat_source",
    "vat_account",
    "item_tax_template",
    "net_return_amount",
    "approved_discount_percentage",
    "approved_pricing_input_mode",
    "approved_net_amount",
    "approved_tax_amount",
    "approved_total_credit",
)


def execute():
    path = frappe.get_app_path(
        "pharma_erp",
        "pharma_erp",
        "doctype",
        "pharmacy_return_item",
        "pharmacy_return_item.json",
    )
    if not os.path.exists(path):
        frappe.throw(f"Missing DocType JSON file: {path}")

    with open(path, encoding="utf-8") as source:
        data = json.load(source)

    fieldnames = {
        field.get("fieldname")
        for field in (data.get("fields") or [])
        if field.get("fieldname")
    }
    missing = [field for field in ITEM_FIELDS if field not in fieldnames]
    if missing:
        frappe.throw(
            "Outdated Pharmacy Return Item JSON. Missing fields: "
            + ", ".join(missing)
        )

    import_file_by_path(path, force=True)
    frappe.clear_cache()
    frappe.db.updatedb("Pharmacy Return Item")

    absent = [
        field
        for field in ITEM_FIELDS
        if not frappe.db.has_column("Pharmacy Return Item", field)
    ]
    if absent:
        frappe.throw(
            "Return pricing/VAT schema sync failed: " + frappe.as_json(absent)
        )

    # Safe historical backfill only. Existing rows are not marked taxable here,
    # because VAT must come from the original Purchase Invoice or Item Tax setup.
    # Opening/saving a case refreshes the authoritative VAT data server-side.
    frappe.db.sql(
        """
        update `tabPharmacy Return Item`
        set
            base_rate = case
                when ifnull(base_rate, 0) <= 0 then abs(ifnull(rate, 0))
                else abs(base_rate)
            end,
            discount_percentage = greatest(0, least(100, ifnull(discount_percentage, 0))),
            pricing_input_mode = case
                when ifnull(pricing_input_mode, '') = '' then 'Net Unit Value'
                else pricing_input_mode
            end,
            is_vat_taxable = ifnull(is_vat_taxable, 0),
            vat_rate = case
                when ifnull(is_vat_taxable, 0) = 1 then greatest(0, ifnull(vat_rate, 0))
                else 0
            end,
            net_return_amount = abs(ifnull(return_qty, 0)) * abs(ifnull(rate, 0)),
            tax_amount = case
                when ifnull(is_vat_taxable, 0) = 1
                then abs(ifnull(return_qty, 0)) * abs(ifnull(rate, 0)) * greatest(0, ifnull(vat_rate, 0)) / 100
                else 0
            end,
            return_amount = (
                abs(ifnull(return_qty, 0)) * abs(ifnull(rate, 0))
                + case
                    when ifnull(is_vat_taxable, 0) = 1
                    then abs(ifnull(return_qty, 0)) * abs(ifnull(rate, 0)) * greatest(0, ifnull(vat_rate, 0)) / 100
                    else 0
                end
            ),
            approved_discount_percentage = greatest(0, least(100, ifnull(approved_discount_percentage, 0))),
            approved_pricing_input_mode = case
                when ifnull(approved_pricing_input_mode, '') = '' then 'Net Unit Value'
                else approved_pricing_input_mode
            end,
            approved_net_amount = abs(ifnull(accepted_qty, 0)) * abs(ifnull(approved_rate, 0)),
            approved_tax_amount = case
                when ifnull(is_vat_taxable, 0) = 1
                then abs(ifnull(accepted_qty, 0)) * abs(ifnull(approved_rate, 0)) * greatest(0, ifnull(vat_rate, 0)) / 100
                else 0
            end,
            approved_total_credit = (
                abs(ifnull(accepted_qty, 0)) * abs(ifnull(approved_rate, 0))
                + case
                    when ifnull(is_vat_taxable, 0) = 1
                    then abs(ifnull(accepted_qty, 0)) * abs(ifnull(approved_rate, 0)) * greatest(0, ifnull(vat_rate, 0)) / 100
                    else 0
                end
            ),
            accepted_amount = (
                abs(ifnull(accepted_qty, 0)) * abs(ifnull(approved_rate, 0))
                + case
                    when ifnull(is_vat_taxable, 0) = 1
                    then abs(ifnull(accepted_qty, 0)) * abs(ifnull(approved_rate, 0)) * greatest(0, ifnull(vat_rate, 0)) / 100
                    else 0
                end
            )
        """
    )
    frappe.clear_cache()
