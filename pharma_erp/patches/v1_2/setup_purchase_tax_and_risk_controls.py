"""Add pharmacy VAT-entry audit fields and purchase-risk controls."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Purchase Invoice Item": [
            {"fieldname":"custom_customer_base_before_vat","label":"Customer Base Before VAT","fieldtype":"Currency","insert_after":"custom_supplier_base_price","read_only":1},
            {"fieldname":"custom_tax_entry_mode","label":"VAT Entry Mode","fieldtype":"Select","options":"No VAT\nAuto by VAT %\nVAT Per Unit\nTotal VAT for Line","default":"Auto by VAT %","insert_after":"custom_manual_net_rate"},
            {"fieldname":"custom_vat_rate","label":"VAT Rate %","fieldtype":"Percent","insert_after":"custom_tax_entry_mode"},
            {"fieldname":"custom_net_before_vat","label":"Net Before VAT","fieldtype":"Currency","insert_after":"custom_vat_rate"},
            {"fieldname":"custom_vat_per_unit","label":"VAT Per Unit","fieldtype":"Currency","insert_after":"custom_net_before_vat"},
            {"fieldname":"custom_total_vat_amount","label":"Total VAT for Line","fieldtype":"Currency","insert_after":"custom_vat_per_unit"},
            {"fieldname":"custom_purchase_risk_level","label":"Purchase Risk Level","fieldtype":"Select","options":"None\nWarning\nCritical","default":"None","read_only":1,"allow_on_submit":1,"insert_after":"custom_total_vat_amount"},
            {"fieldname":"custom_purchase_risk_flags","label":"Purchase Risk Flags","fieldtype":"Small Text","read_only":1,"allow_on_submit":1,"insert_after":"custom_purchase_risk_level"},
            {"fieldname":"custom_purchase_risk_confirmed","label":"Purchase Risk Confirmed","fieldtype":"Check","allow_on_submit":1,"insert_after":"custom_purchase_risk_flags"},
            {"fieldname":"custom_purchase_risk_confirmed_by","label":"Risk Confirmed By","fieldtype":"Link","options":"User","read_only":1,"allow_on_submit":1,"insert_after":"custom_purchase_risk_confirmed"},
            {"fieldname":"custom_purchase_risk_confirmed_at","label":"Risk Confirmed At","fieldtype":"Datetime","read_only":1,"allow_on_submit":1,"insert_after":"custom_purchase_risk_confirmed_by"},
            {"fieldname":"custom_purchase_risk_confirmation_reason","label":"Risk Confirmation Reason","fieldtype":"Small Text","allow_on_submit":1,"insert_after":"custom_purchase_risk_confirmed_at"},
        ]
    }, update=True)

    field_name = frappe.db.get_value("Custom Field", {"dt":"Purchase Invoice Item","fieldname":"custom_purchase_pricing_method"}, "name")
    if field_name:
        frappe.db.set_value("Custom Field", field_name, {
            "options":"Discount From Customer Price\nDiscount From Supplier Base Price\nDirect Net Before VAT\nDirect Final Net Rate",
            "default":"Discount From Customer Price",
        }, update_modified=False)
    net_field = frappe.db.get_value("Custom Field", {"dt":"Purchase Invoice Item","fieldname":"custom_manual_net_rate"}, "name")
    if net_field:
        frappe.db.set_value("Custom Field", net_field, "label", "Final Net Rate", update_modified=False)

    defaults = {
        "default_pricing_method":"Discount From Customer Price",
        "default_tax_entry_mode":"Auto by VAT %",
        "manual_vat_difference_tolerance":0.10,
        "enable_purchase_risk_alerts":1,
        "item_search_result_limit":10,
        "recent_purchase_warning_days":3,
        "slow_movement_analysis_days":30,
        "dormant_item_days":90,
        "high_stock_coverage_days":90,
        "minimum_stock_qty_for_warning":5,
        "require_risk_confirmation":1,
    }
    for fieldname, value in defaults.items():
        if frappe.get_meta("Pharmacy Purchase Settings").has_field(fieldname):
            current = frappe.db.get_single_value("Pharmacy Purchase Settings", fieldname)
            if current in (None, ""):
                frappe.db.set_single_value("Pharmacy Purchase Settings", fieldname, value)
    frappe.clear_cache()
