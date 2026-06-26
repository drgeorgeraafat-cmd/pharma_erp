"""Install the Purchase & Invoice Management foundation."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    _create_or_update_custom_fields()
    _set_default_settings()
    _disable_migrated_legacy_scripts()
    frappe.clear_cache()


def _create_or_update_custom_fields():
    create_custom_fields(
        {
            "Supplier": [
                {
                    "fieldname": "custom_purchase_profile_section",
                    "label": "Pharmacy Purchase Profile",
                    "fieldtype": "Section Break",
                    "insert_after": "supplier_group",
                    "collapsible": 1,
                },
                {
                    "fieldname": "custom_purchase_supplier_type",
                    "label": "Purchase Supplier Type",
                    "fieldtype": "Select",
                    "options": "\nDistribution Company\nWarehouse\nOther",
                    "insert_after": "custom_purchase_profile_section",
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "custom_purchase_payment_model",
                    "label": "Purchase Payment Model",
                    "fieldtype": "Select",
                    "options": "\nCash\nCredit Claim\nMixed",
                    "insert_after": "custom_purchase_supplier_type",
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "custom_claim_cycle_start_day",
                    "label": "Claim Cycle Start Day",
                    "fieldtype": "Int",
                    "insert_after": "custom_purchase_payment_model",
                },
                {
                    "fieldname": "custom_claim_cycle_end_day",
                    "label": "Claim Cycle End Day",
                    "fieldtype": "Int",
                    "insert_after": "custom_claim_cycle_start_day",
                },
                {
                    "fieldname": "custom_exclude_cash_invoices_from_claim",
                    "label": "Exclude Cash Invoices From Claims",
                    "fieldtype": "Check",
                    "default": "1",
                    "insert_after": "custom_claim_cycle_end_day",
                },
                {
                    "fieldname": "custom_purchase_notes",
                    "label": "Purchase Notes",
                    "fieldtype": "Small Text",
                    "insert_after": "custom_exclude_cash_invoices_from_claim",
                },
            ],
            "Item": [
                {
                    "fieldname": "custom_customer_price",
                    "label": "Current Printed Retail Price",
                    "fieldtype": "Currency",
                    "insert_after": "custom_item_origin",
                    "in_standard_filter": 1,
                },
            ],
            "Purchase Invoice": [
                {
                    "fieldname": "custom_purchase_management_section",
                    "label": "Pharmacy Purchase Management",
                    "fieldtype": "Section Break",
                    "insert_after": "bill_date",
                    "collapsible": 1,
                },
                {
                    "fieldname": "custom_purchase_entry_mode",
                    "label": "Purchase Entry Mode",
                    "fieldtype": "Select",
                    "options": "Quick Invoice & Receipt\nAgainst Purchase Order",
                    "default": "Quick Invoice & Receipt",
                    "insert_after": "custom_purchase_management_section",
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "custom_payment_classification",
                    "label": "Supplier Payment Classification",
                    "fieldtype": "Select",
                    "options": "\nCash Invoice\nClaim Invoice\nCredit Invoice Outside Claim",
                    "insert_after": "custom_purchase_entry_mode",
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "custom_exclude_from_supplier_claim",
                    "label": "Exclude From Supplier Claim",
                    "fieldtype": "Check",
                    "insert_after": "custom_payment_classification",
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "custom_supplier_invoice_attachment",
                    "label": "Supplier Invoice Attachment",
                    "fieldtype": "Attach",
                    "insert_after": "custom_exclude_from_supplier_claim",
                },
                {
                    "fieldname": "custom_purchase_review_column",
                    "fieldtype": "Column Break",
                    "insert_after": "custom_supplier_invoice_attachment",
                },
                {
                    "fieldname": "custom_retail_price_review_status",
                    "label": "Retail Price Review Status",
                    "fieldtype": "Select",
                    "options": "Not Required\nPending Review\nApplied\nSkipped",
                    "default": "Not Required",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "no_copy": 1,
                    "insert_after": "custom_purchase_review_column",
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "custom_price_change_count",
                    "label": "Retail Price Changes",
                    "fieldtype": "Int",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "no_copy": 1,
                    "insert_after": "custom_retail_price_review_status",
                },
                {
                    "fieldname": "custom_bonus_line_count",
                    "label": "Bonus Lines",
                    "fieldtype": "Int",
                    "read_only": 1,
                    "no_copy": 1,
                    "insert_after": "custom_price_change_count",
                },
                {
                    "fieldname": "custom_auto_batch_count",
                    "label": "Auto-generated Batches",
                    "fieldtype": "Int",
                    "read_only": 1,
                    "no_copy": 1,
                    "insert_after": "custom_bonus_line_count",
                },
                {
                    "fieldname": "custom_price_reviewed_by",
                    "label": "Price Reviewed By",
                    "fieldtype": "Link",
                    "options": "User",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "no_copy": 1,
                    "insert_after": "custom_auto_batch_count",
                },
                {
                    "fieldname": "custom_price_reviewed_at",
                    "label": "Price Reviewed At",
                    "fieldtype": "Datetime",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "no_copy": 1,
                    "insert_after": "custom_price_reviewed_by",
                },
            ],
            "Purchase Invoice Item": [
                {
                    "fieldname": "custom_batch_number",
                    "label": "Supplier Batch Number",
                    "fieldtype": "Data",
                    "insert_after": "rejected_qty",
                    "in_list_view": 1,
                },
                {
                    "fieldname": "custom_expiry_date",
                    "label": "Expiry Date",
                    "fieldtype": "Date",
                    "insert_after": "custom_batch_number",
                    "in_list_view": 1,
                },
                {
                    "fieldname": "custom_is_bonus_item",
                    "label": "Bonus Item",
                    "fieldtype": "Check",
                    "insert_after": "custom_expiry_date",
                    "in_list_view": 1,
                },
                {
                    "fieldname": "custom_auto_batch_generated",
                    "label": "Auto Batch Generated",
                    "fieldtype": "Check",
                    "read_only": 1,
                    "no_copy": 1,
                    "insert_after": "custom_is_bonus_item",
                },
                {
                    "fieldname": "custom_auto_batch_reason",
                    "label": "Auto Batch Reason",
                    "fieldtype": "Small Text",
                    "insert_after": "custom_auto_batch_generated",
                },
                {
                    "fieldname": "custom_selling_price",
                    "label": "Printed Retail Price",
                    "fieldtype": "Currency",
                    "fetch_from": "item_code.custom_customer_price",
                    "fetch_if_empty": 1,
                    "insert_after": "price_list_rate",
                    "in_list_view": 1,
                },
                {
                    "fieldname": "custom_additional_discount",
                    "label": "Additional Line Discount %",
                    "fieldtype": "Percent",
                    "insert_after": "discount_percentage",
                    "in_list_view": 1,
                },
                {
                    "fieldname": "custom_previous_retail_price",
                    "label": "Previous Current Retail Price",
                    "fieldtype": "Currency",
                    "read_only": 1,
                    "no_copy": 1,
                    "insert_after": "custom_selling_price",
                },
                {
                    "fieldname": "custom_price_change_detected",
                    "label": "Retail Price Change Detected",
                    "fieldtype": "Check",
                    "read_only": 1,
                    "no_copy": 1,
                    "insert_after": "custom_previous_retail_price",
                },
                {
                    "fieldname": "custom_price_change_applied",
                    "label": "Retail Price Change Applied",
                    "fieldtype": "Check",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "no_copy": 1,
                    "insert_after": "custom_price_change_detected",
                },
                {
                    "fieldname": "custom_existing_batch_retail_price",
                    "label": "Existing Batch Retail Price",
                    "fieldtype": "Currency",
                    "read_only": 1,
                    "no_copy": 1,
                    "insert_after": "custom_price_change_applied",
                },
                {
                    "fieldname": "custom_batch_price_conflict",
                    "label": "Batch Price Conflict",
                    "fieldtype": "Check",
                    "read_only": 1,
                    "no_copy": 1,
                    "insert_after": "custom_existing_batch_retail_price",
                },
                {
                    "fieldname": "custom_approve_batch_price_conflict",
                    "label": "Approve Batch Price Conflict",
                    "fieldtype": "Check",
                    "insert_after": "custom_batch_price_conflict",
                    "depends_on": "eval:doc.custom_batch_price_conflict",
                },
                {
                    "fieldname": "custom_price_conflict_reason",
                    "label": "Batch Price Conflict Reason",
                    "fieldtype": "Small Text",
                    "insert_after": "custom_approve_batch_price_conflict",
                    "depends_on": "eval:doc.custom_batch_price_conflict",
                },
            ],
            "Batch": [
                {
                    "fieldname": "custom_purchase_pricing_section",
                    "label": "Pharmacy Purchase Pricing",
                    "fieldtype": "Section Break",
                    "insert_after": "expiry_date",
                    "collapsible": 1,
                },
                {
                    "fieldname": "custom_printed_retail_price",
                    "label": "Printed Retail Price",
                    "fieldtype": "Currency",
                    "insert_after": "custom_purchase_pricing_section",
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "custom_price_effective_date",
                    "label": "Price Effective Date",
                    "fieldtype": "Date",
                    "insert_after": "custom_printed_retail_price",
                },
                {
                    "fieldname": "custom_purchase_invoice",
                    "label": "Source Purchase Invoice",
                    "fieldtype": "Link",
                    "options": "Purchase Invoice",
                    "read_only": 1,
                    "insert_after": "custom_price_effective_date",
                },
                {
                    "fieldname": "custom_supplier",
                    "label": "Source Supplier",
                    "fieldtype": "Link",
                    "options": "Supplier",
                    "read_only": 1,
                    "insert_after": "custom_purchase_invoice",
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "custom_price_updated_from_invoice",
                    "label": "Price Updated From Purchase Invoice",
                    "fieldtype": "Check",
                    "read_only": 1,
                    "insert_after": "custom_supplier",
                },
                {
                    "fieldname": "custom_auto_generated",
                    "label": "Automatically Generated Batch",
                    "fieldtype": "Check",
                    "read_only": 1,
                    "insert_after": "custom_price_updated_from_invoice",
                    "in_standard_filter": 1,
                },
                {
                    "fieldname": "custom_auto_generation_reason",
                    "label": "Automatic Generation Reason",
                    "fieldtype": "Small Text",
                    "read_only": 1,
                    "insert_after": "custom_auto_generated",
                },
            ],
        },
        update=True,
    )


def _set_default_settings():
    if not frappe.db.exists("DocType", "Pharmacy Purchase Settings"):
        return

    defaults = {
        "default_entry_mode": "Quick Invoice & Receipt",
        "require_supplier_invoice_number": 1,
        "prevent_duplicate_supplier_invoice_number": 1,
        "require_supplier_invoice_attachment": 0,
        "default_cash_invoice_excluded_from_claim": 1,
        "enable_automatic_batch_generation": 1,
        "require_batch_number": 1,
        "require_expiry_date": 1,
        "require_manager_approval_for_auto_batch": 0,
        "auto_batch_prefix": "AUTO",
        "retail_price_update_policy": "Ask Before Update",
        "retail_price_difference_tolerance": 0.01,
        "block_batch_price_conflict": 1,
    }
    for fieldname, value in defaults.items():
        current = frappe.db.get_single_value("Pharmacy Purchase Settings", fieldname)
        if current in (None, ""):
            frappe.db.set_single_value("Pharmacy Purchase Settings", fieldname, value)

    if frappe.db.exists("Price List", "Standard Selling"):
        current = frappe.db.get_single_value(
            "Pharmacy Purchase Settings", "selling_price_list"
        )
        if not current:
            frappe.db.set_single_value(
                "Pharmacy Purchase Settings", "selling_price_list", "Standard Selling"
            )


def _disable_migrated_legacy_scripts():
    if frappe.db.exists("Server Script", "Auto Batch Number"):
        frappe.db.set_value(
            "Server Script", "Auto Batch Number", "disabled", 1, update_modified=False
        )
