"""Install v0.7.47 Pharmacy / Company Print Settings."""
from __future__ import annotations

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

SETTINGS_DOCTYPE = "Pharmacy Purchase Settings"


def _doctype_exists(doctype: str) -> bool:
    try:
        return bool(frappe.db.exists("DocType", doctype))
    except Exception:
        return False


def _field_exists(doctype: str, fieldname: str) -> bool:
    try:
        return bool(frappe.get_meta(doctype).has_field(fieldname))
    except Exception:
        return False


def _ensure_print_fields() -> list[str]:
    if not _doctype_exists(SETTINGS_DOCTYPE):
        frappe.throw(f"{SETTINGS_DOCTYPE} DocType is required before installing print settings.")

    fields = [
        {
            "fieldname": "print_identity_section",
            "label": "Pharmacy / Company Print Settings",
            "fieldtype": "Section Break",
            "insert_after": "claim_settlement_discount_account",
        },
        {
            "fieldname": "show_company_name",
            "label": "Show Company Name",
            "fieldtype": "Check",
            "default": "1",
            "insert_after": "print_identity_section",
        },
        {
            "fieldname": "show_pharmacy_name",
            "label": "Show Pharmacy Name",
            "fieldtype": "Check",
            "default": "1",
            "insert_after": "show_company_name",
        },
        {
            "fieldname": "print_identity_column_break",
            "fieldtype": "Column Break",
            "insert_after": "show_pharmacy_name",
        },
        {
            "fieldname": "pharmacy_english_name",
            "label": "Pharmacy English Name",
            "fieldtype": "Data",
            "insert_after": "print_identity_column_break",
        },
        {
            "fieldname": "pharmacy_arabic_name",
            "label": "Pharmacy Arabic Name",
            "fieldtype": "Data",
            "insert_after": "pharmacy_english_name",
        },
        {
            "fieldname": "pharmacy_logo",
            "label": "Pharmacy Logo",
            "fieldtype": "Attach Image",
            "insert_after": "pharmacy_arabic_name",
        },
        {
            "fieldname": "pharmacy_phone",
            "label": "Phone Number",
            "fieldtype": "Data",
            "insert_after": "pharmacy_logo",
        },
        {
            "fieldname": "pharmacy_address",
            "label": "Address",
            "fieldtype": "Small Text",
            "insert_after": "pharmacy_phone",
        },
        {
            "fieldname": "print_footer_note",
            "label": "Print Footer Note",
            "fieldtype": "Small Text",
            "insert_after": "pharmacy_address",
        },
    ]

    missing = [field for field in fields if not _field_exists(SETTINGS_DOCTYPE, field["fieldname"])]
    if missing:
        create_custom_fields({SETTINGS_DOCTYPE: missing}, update=True)
    frappe.clear_cache(doctype=SETTINGS_DOCTYPE)
    return [field["fieldname"] for field in missing]


def _set_default_single_values() -> dict[str, str]:
    updated: dict[str, str] = {}
    for fieldname in ("show_company_name", "show_pharmacy_name"):
        if _field_exists(SETTINGS_DOCTYPE, fieldname):
            current = frappe.db.get_single_value(SETTINGS_DOCTYPE, fieldname)
            if current in (None, ""):
                frappe.db.set_single_value(SETTINGS_DOCTYPE, fieldname, 1)
                updated[fieldname] = "1"
    return updated


def execute() -> dict:
    try:
        frappe.reload_doc("pharma_erp", "doctype", "pharmacy_purchase_settings")
    except Exception:
        # The custom fields below are enough for this update; reload failures are
        # reported in the result only if the actual field creation fails.
        pass

    missing = _ensure_print_fields()
    defaults = _set_default_single_values()
    frappe.db.commit()

    result = {
        "version": "v0.7.47",
        "doctype": SETTINGS_DOCTYPE,
        "created_or_confirmed_fields": [
            "show_company_name",
            "show_pharmacy_name",
            "pharmacy_english_name",
            "pharmacy_arabic_name",
            "pharmacy_logo",
            "pharmacy_phone",
            "pharmacy_address",
            "print_footer_note",
        ],
        "new_custom_fields": missing,
        "defaults_updated": defaults,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    execute()
