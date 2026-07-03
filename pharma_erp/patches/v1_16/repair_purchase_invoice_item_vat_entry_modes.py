from __future__ import annotations

import re

import frappe


VALID_MODES = {
    "No VAT",
    "Auto by VAT %",
    "VAT Per Unit",
    "Total VAT for Line",
}


def _normalize(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text or text in VALID_MODES:
        return text or None

    lowered = text.lower()
    if "no vat" in lowered or "exempt" in lowered:
        return "No VAT"
    if "total" in lowered and "vat" in lowered:
        return "Total VAT for Line"
    if "per unit" in lowered and "vat" in lowered:
        return "VAT Per Unit"
    if "auto" in lowered and "vat" in lowered:
        return "Auto by VAT %"
    return None


def execute():
    if not frappe.db.has_column(
        "Purchase Invoice Item", "custom_tax_entry_mode"
    ):
        return

    rows = frappe.get_all(
        "Purchase Invoice Item",
        filters={"custom_tax_entry_mode": ["not in", list(VALID_MODES) + [""]]},
        fields=["name", "custom_tax_entry_mode"],
        limit_page_length=0,
    )

    repaired = 0
    for row in rows:
        normalized = _normalize(row.custom_tax_entry_mode)
        if not normalized or normalized == row.custom_tax_entry_mode:
            continue
        frappe.db.set_value(
            "Purchase Invoice Item",
            row.name,
            "custom_tax_entry_mode",
            normalized,
            update_modified=False,
        )
        repaired += 1

    if repaired:
        frappe.clear_cache(doctype="Purchase Invoice")
