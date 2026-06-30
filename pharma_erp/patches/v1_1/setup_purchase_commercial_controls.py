"""Add commercial purchase controls, exact supplier totals and claim linkage."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "Purchase Invoice": [
            {"fieldname":"custom_supplier_invoice_total","label":"Supplier Invoice Total","fieldtype":"Currency","insert_after":"custom_supplier_invoice_attachment","in_standard_filter":1},
            {"fieldname":"custom_fraction_adjustment","label":"Fraction Adjustment","fieldtype":"Currency","read_only":1,"allow_on_submit":1,"insert_after":"custom_supplier_invoice_total"},
            {"fieldname":"custom_fraction_adjustment_account","label":"Fraction Adjustment Account","fieldtype":"Link","options":"Account","read_only":1,"allow_on_submit":1,"insert_after":"custom_fraction_adjustment"},
            {"fieldname":"custom_claim_basis_date","label":"Claim Basis Date","fieldtype":"Date","read_only":1,"allow_on_submit":1,"insert_after":"custom_fraction_adjustment_account"},
            {"fieldname":"custom_expected_claim_period_from","label":"Expected Claim Period From","fieldtype":"Date","read_only":1,"allow_on_submit":1,"insert_after":"custom_claim_basis_date"},
            {"fieldname":"custom_expected_claim_period_to","label":"Expected Claim Period To","fieldtype":"Date","read_only":1,"allow_on_submit":1,"insert_after":"custom_expected_claim_period_from"},
            {"fieldname":"custom_claim_match_status","label":"Supplier Total Match","fieldtype":"Select","options":"Not Checked\nMatched\nMismatch","default":"Not Checked","read_only":1,"allow_on_submit":1,"insert_after":"custom_expected_claim_period_to","in_standard_filter":1},
            {"fieldname":"custom_supplier_claim","label":"Supplier Claim","fieldtype":"Link","options":"Supplier Claim","read_only":1,"allow_on_submit":1,"insert_after":"custom_claim_match_status","in_standard_filter":1},
        ],
        "Purchase Invoice Item": [
            {"fieldname":"custom_supplier_base_price","label":"Supplier Invoice Base Price","fieldtype":"Currency","insert_after":"custom_selling_price","in_list_view":1},
            {"fieldname":"custom_purchase_pricing_method","label":"Purchase Pricing Method","fieldtype":"Select","options":"Discount From Supplier Base Price\nDirect Net Purchase Rate","default":"Discount From Supplier Base Price","insert_after":"custom_supplier_base_price"},
            {"fieldname":"custom_manual_net_rate","label":"Entered Net Rate","fieldtype":"Currency","insert_after":"custom_purchase_pricing_method"},
        ],
    }, update=True)
    label_updates = [
        ("Item", "custom_customer_price", "Current Customer Price"),
        ("Purchase Invoice Item", "custom_selling_price", "Customer Price"),
        ("Batch", "custom_printed_retail_price", "Customer Price"),
    ]
    for dt, fieldname, label in label_updates:
        name = frappe.db.get_value("Custom Field", {"dt":dt,"fieldname":fieldname}, "name")
        if name:
            frappe.db.set_value("Custom Field", name, "label", label, update_modified=False)
    defaults = {
        "default_pricing_method":"Discount From Supplier Base Price",
        "require_exact_supplier_invoice_total":1,
        "max_fraction_adjustment":1.0,
        "near_expiry_warning_months":6,
        "auto_merge_same_item_batch":1,
        "enable_local_draft_recovery":1,
        "claim_cycle_basis":"Supplier Invoice Date",
    }
    for fieldname, value in defaults.items():
        if frappe.get_meta("Pharmacy Purchase Settings").has_field(fieldname):
            current = frappe.db.get_single_value("Pharmacy Purchase Settings", fieldname)
            if current in (None, ""):
                frappe.db.set_single_value("Pharmacy Purchase Settings", fieldname, value)
    frappe.clear_cache()
