"""Dynamic pharmacy/company print identity helpers for Pharma ERP.

v0.7.47: Centralizes the data used by short operational print summaries so
pages do not hardcode pharmacy/company names, logo, phone, or address.
"""
from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint, cstr

SETTINGS_DOCTYPE = "Pharmacy Purchase Settings"

PRINT_SETTING_FIELDS = (
    "show_company_name",
    "show_pharmacy_name",
    "pharmacy_english_name",
    "pharmacy_arabic_name",
    "pharmacy_logo",
    "pharmacy_phone",
    "pharmacy_address",
    "print_footer_note",
)

COMPANY_FIELDS = (
    "company_name",
    "abbr",
    "company_logo",
    "phone_no",
    "email",
    "website",
)


def _doctype_exists(doctype: str) -> bool:
    try:
        return bool(frappe.db.exists("DocType", doctype))
    except Exception:
        return False


def _meta_fields(doctype: str) -> set[str]:
    try:
        return {df.fieldname for df in frappe.get_meta(doctype).fields if df.fieldname}
    except Exception:
        return set()


def _safe_single_values(doctype: str, fields: tuple[str, ...]) -> dict[str, Any]:
    if not _doctype_exists(doctype):
        return {}
    available = _meta_fields(doctype)
    values: dict[str, Any] = {}
    for fieldname in fields:
        if fieldname not in available:
            continue
        try:
            values[fieldname] = frappe.db.get_single_value(doctype, fieldname)
        except Exception:
            values[fieldname] = None
    return values


def _safe_doc_values(doctype: str, name: str | None, fields: tuple[str, ...]) -> dict[str, Any]:
    if not name or not _doctype_exists(doctype) or not frappe.db.exists(doctype, name):
        return {}
    available = _meta_fields(doctype)
    selected = [fieldname for fieldname in fields if fieldname in available]
    if not selected:
        return {}
    try:
        return frappe.db.get_value(doctype, name, selected, as_dict=True) or {}
    except Exception:
        return {}


def _default_company() -> str | None:
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.defaults.get_global_default("company")
        or frappe.db.get_value("Company", {}, "name", order_by="is_group asc, creation asc")
    )


def _bool_setting(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return bool(cint(value))


def _dedupe_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        text = cstr(line).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _company_display_name(company: str | None, company_values: dict[str, Any]) -> str:
    return cstr(company_values.get("company_name") or company or "").strip()


@frappe.whitelist()
def get_print_identity(company: str | None = None) -> dict[str, Any]:
    """Return dynamic print identity for short operational summaries.

    Data priority:
    1. Pharmacy Purchase Settings print section.
    2. Company master fields where available.
    3. Current/default company name only.

    The function intentionally returns empty strings instead of hardcoded
    pharmacy data when settings are missing.
    """
    company = cstr(company or _default_company() or "").strip()
    settings = _safe_single_values(SETTINGS_DOCTYPE, PRINT_SETTING_FIELDS)
    company_values = _safe_doc_values("Company", company, COMPANY_FIELDS)

    show_company_name = _bool_setting(settings.get("show_company_name"), True)
    show_pharmacy_name = _bool_setting(settings.get("show_pharmacy_name"), True)

    pharmacy_english_name = cstr(settings.get("pharmacy_english_name") or "").strip()
    pharmacy_arabic_name = cstr(settings.get("pharmacy_arabic_name") or "").strip()
    company_name = _company_display_name(company, company_values)

    logo = cstr(settings.get("pharmacy_logo") or company_values.get("company_logo") or "").strip()
    phone = cstr(settings.get("pharmacy_phone") or company_values.get("phone_no") or "").strip()
    address = cstr(settings.get("pharmacy_address") or "").strip()
    footer_note = cstr(settings.get("print_footer_note") or "").strip()

    name_lines: list[str] = []
    if show_pharmacy_name:
        name_lines.extend([pharmacy_arabic_name, pharmacy_english_name])
    if show_company_name:
        name_lines.append(company_name)
    name_lines = _dedupe_lines(name_lines)
    if not name_lines and company_name:
        name_lines = [company_name]

    return {
        "company": company,
        "company_name": company_name,
        "show_company_name": 1 if show_company_name else 0,
        "show_pharmacy_name": 1 if show_pharmacy_name else 0,
        "pharmacy_english_name": pharmacy_english_name,
        "pharmacy_arabic_name": pharmacy_arabic_name,
        "name_lines": name_lines,
        "display_title": " | ".join(name_lines),
        "logo": logo,
        "phone": phone,
        "address": address,
        "footer_note": footer_note,
    }
