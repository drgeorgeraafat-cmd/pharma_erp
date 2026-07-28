from __future__ import annotations

from typing import Any

import frappe
from frappe import _


DOCTYPE = "Website Item"

CUSTOM_FIELDS: list[dict[str, Any]] = [
    {
        "fieldname": "custom_pharma_catalog_control_section",
        "label": "Pharma Online Catalog Control",
        "fieldtype": "Section Break",
        "insert_after": "website_content",
    },
    {
        "fieldname": "custom_pharma_managed",
        "label": "Managed by Pharma Publishing Bridge",
        "fieldtype": "Check",
        "insert_after": "custom_pharma_catalog_control_section",
        "read_only": 1,
        "default": "0",
    },
    {
        "fieldname": "custom_online_category",
        "label": "Online Category",
        "fieldtype": "Link",
        "options": "Online Category",
        "insert_after": "custom_pharma_managed",
        "read_only": 1,
    },
    {
        "fieldname": "custom_requires_prescription",
        "label": "Requires Prescription",
        "fieldtype": "Check",
        "insert_after": "custom_online_category",
        "read_only": 1,
        "default": "0",
    },
    {
        "fieldname": "custom_featured_product",
        "label": "Featured Product",
        "fieldtype": "Check",
        "insert_after": "custom_requires_prescription",
        "read_only": 1,
        "default": "0",
    },
    {
        "fieldname": "custom_online_availability_status",
        "label": "Online Availability Status",
        "fieldtype": "Select",
        "options": (
            "Available\n"
            "Temporarily Unavailable\n"
            "Coming Soon\n"
            "Hidden"
        ),
        "insert_after": "custom_featured_product",
        "read_only": 1,
    },
    {
        "fieldname": "custom_online_sort_order",
        "label": "Online Sort Order",
        "fieldtype": "Int",
        "insert_after": "custom_online_availability_status",
        "read_only": 1,
        "default": "0",
    },
    {
        "fieldname": "custom_pharma_readiness_status",
        "label": "Online Readiness Status",
        "fieldtype": "Select",
        "options": "Not Selected\nNot Ready\nWarning\nReady",
        "insert_after": "custom_online_sort_order",
        "read_only": 1,
    },
    {
        "fieldname": "custom_pharma_readiness_score",
        "label": "Online Readiness Score",
        "fieldtype": "Int",
        "insert_after": "custom_pharma_readiness_status",
        "read_only": 1,
        "default": "0",
    },
    {
        "fieldname": "custom_pharma_last_synced_at",
        "label": "Last Synced At",
        "fieldtype": "Datetime",
        "insert_after": "custom_pharma_readiness_score",
        "read_only": 1,
    },
    {
        "fieldname": "custom_online_description_ar",
        "label": "Online Description Arabic",
        "fieldtype": "Text Editor",
        "insert_after": "custom_pharma_last_synced_at",
        "read_only": 1,
    },
    {
        "fieldname": "custom_online_description_en",
        "label": "Online Description English",
        "fieldtype": "Text Editor",
        "insert_after": "custom_online_description_ar",
        "read_only": 1,
    },
]


def _set_if_changed(doc, fieldname: str, value: Any) -> bool:
    if doc.get(fieldname) == value:
        return False
    doc.set(fieldname, value)
    return True


def _upsert_custom_field(spec: dict[str, Any]) -> str:
    fieldname = spec["fieldname"]
    existing_name = frappe.db.get_value(
        "Custom Field",
        {
            "dt": DOCTYPE,
            "fieldname": fieldname,
        },
        "name",
    )

    if existing_name:
        custom_field = frappe.get_doc(
            "Custom Field",
            existing_name,
        )
    else:
        custom_field = frappe.new_doc("Custom Field")
        custom_field.dt = DOCTYPE
        custom_field.fieldname = fieldname

    changed = not existing_name
    for key, value in spec.items():
        changed = _set_if_changed(
            custom_field,
            key,
            value,
        ) or changed

    if changed:
        custom_field.save(ignore_permissions=True)

    return "updated" if existing_name else "created"


@frappe.whitelist()
def install() -> dict[str, Any]:
    if not frappe.db.exists("DocType", DOCTYPE):
        frappe.throw(
            _("Install Frappe Webshop before installing this bridge."),
            title=_("Webshop Required"),
        )

    results: dict[str, str] = {}
    for spec in CUSTOM_FIELDS:
        results[spec["fieldname"]] = _upsert_custom_field(spec)

    frappe.clear_cache(doctype=DOCTYPE)
    frappe.clear_document_cache(DOCTYPE)

    return {
        "doctype": DOCTYPE,
        "field_count": len(CUSTOM_FIELDS),
        "fields": results,
    }
