from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cstr


ITEM_DOCTYPE = "Item"
ONLINE_CATEGORY_DOCTYPE = "Online Category"


FIELDS: list[dict[str, Any]] = [
    {
        "fieldname": "custom_online_catalog_section",
        "label": "Online Catalog",
        "fieldtype": "Section Break",
        "insert_after": "custom_uom_options",
        "description": (
            "Customer-facing catalog settings. Current Customer Price remains the "
            "single retail price source; no separate online price is stored."
        ),
    },
    {
        "fieldname": "custom_show_online",
        "label": "Show Online",
        "fieldtype": "Check",
        "insert_after": "custom_online_catalog_section",
        "default": "0",
        "description": "Main publishing gate for the online customer catalog.",
    },
    {
        "fieldname": "custom_online_category",
        "label": "Online Category",
        "fieldtype": "Link",
        "options": ONLINE_CATEGORY_DOCTYPE,
        "insert_after": "custom_show_online",
        "depends_on": "eval:doc.custom_show_online==1",
        "mandatory_depends_on": "eval:doc.custom_show_online==1",
        "description": (
            "Customer-facing category. This is separate from Item Group and Primary Use."
        ),
    },
    {
        "fieldname": "custom_requires_prescription",
        "label": "Requires Prescription",
        "fieldtype": "Check",
        "insert_after": "custom_online_category",
        "default": "0",
        "description": "Marks products that require prescription review before fulfillment.",
    },
    {
        "fieldname": "custom_online_catalog_column_break",
        "label": "",
        "fieldtype": "Column Break",
        "insert_after": "custom_requires_prescription",
    },
    {
        "fieldname": "custom_featured_product",
        "label": "Featured Product",
        "fieldtype": "Check",
        "insert_after": "custom_online_catalog_column_break",
        "default": "0",
        "description": "Allows storefronts to prioritize this product in featured sections.",
    },
    {
        "fieldname": "custom_online_availability_status",
        "label": "Online Availability Status",
        "fieldtype": "Select",
        "options": "Available\nTemporarily Unavailable\nComing Soon\nHidden",
        "insert_after": "custom_featured_product",
        "default": "Available",
        "depends_on": "eval:doc.custom_show_online==1",
        "mandatory_depends_on": "eval:doc.custom_show_online==1",
        "description": (
            "Manual catalog status. Dynamic stock checks will be handled in the "
            "online stock and prescription review stage."
        ),
    },
    {
        "fieldname": "custom_online_sort_order",
        "label": "Online Sort Order",
        "fieldtype": "Int",
        "insert_after": "custom_online_availability_status",
        "default": "0",
        "description": "Lower numbers appear first when the storefront uses manual ordering.",
    },
    {
        "fieldname": "custom_online_descriptions_section",
        "label": "Online Descriptions",
        "fieldtype": "Section Break",
        "insert_after": "custom_online_sort_order",
        "depends_on": "eval:doc.custom_show_online==1",
    },
    {
        "fieldname": "custom_online_description_ar",
        "label": "Online Description Arabic",
        "fieldtype": "Text Editor",
        "insert_after": "custom_online_descriptions_section",
        "description": "Customer-facing Arabic product description.",
    },
    {
        "fieldname": "custom_online_description_en",
        "label": "Online Description English",
        "fieldtype": "Text Editor",
        "insert_after": "custom_online_description_ar",
        "description": "Customer-facing English product description.",
    },
]


def _set_if_changed(doc: frappe.model.document.Document, key: str, value: Any) -> bool:
    current = doc.get(key)
    if cstr(current) == cstr(value):
        return False
    doc.set(key, value)
    return True


def _upsert_custom_field(spec: dict[str, Any]) -> str:
    fieldname = spec["fieldname"]
    existing_name = frappe.db.get_value(
        "Custom Field",
        {"dt": ITEM_DOCTYPE, "fieldname": fieldname},
        "name",
    )

    if existing_name:
        doc = frappe.get_doc("Custom Field", existing_name)
        changed = False
        for key, value in spec.items():
            changed = _set_if_changed(doc, key, value) or changed
        if changed:
            doc.save()
            return "updated"
        return "unchanged"

    values = {
        "doctype": "Custom Field",
        "dt": ITEM_DOCTYPE,
        **spec,
    }
    frappe.get_doc(values).insert()
    return "created"


def _upsert_image_visibility_property() -> str:
    meta = frappe.get_meta(ITEM_DOCTYPE)
    if not meta.get_field("image"):
        frappe.throw(_("Standard Item.image field was not found."))

    filters = {
        "doc_type": ITEM_DOCTYPE,
        "doctype_or_field": "DocField",
        "field_name": "image",
        "property": "hidden",
    }
    existing_name = frappe.db.get_value("Property Setter", filters, "name")

    if existing_name:
        doc = frappe.get_doc("Property Setter", existing_name)
        changed = False
        changed = _set_if_changed(doc, "value", "0") or changed
        changed = _set_if_changed(doc, "property_type", "Check") or changed
        if changed:
            doc.save()
            return "updated"
        return "unchanged"

    frappe.get_doc(
        {
            "doctype": "Property Setter",
            **filters,
            "value": "0",
            "property_type": "Check",
        }
    ).insert()
    return "created"


def _assert_online_category_metadata() -> None:
    row = frappe.db.get_value(
        "DocType",
        ONLINE_CATEGORY_DOCTYPE,
        [
            "autoname",
            "title_field",
            "search_fields",
            "show_title_field_in_link",
            "is_tree",
            "nsm_parent_field",
        ],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("{0} was not synchronized by migrate.").format(ONLINE_CATEGORY_DOCTYPE))

    expected = {
        "autoname": "field:category_name",
        "title_field": "category_name",
        "search_fields": "category_name,category_name_ar",
        "show_title_field_in_link": 1,
        "is_tree": 1,
        "nsm_parent_field": "parent_online_category",
    }
    mismatches = {
        key: {"expected": value, "actual": row.get(key)}
        for key, value in expected.items()
        if cstr(row.get(key)) != cstr(value)
    }
    if mismatches:
        frappe.throw(
            _("Online Category metadata mismatch: {0}").format(
                frappe.as_json(mismatches)
            )
        )


@frappe.whitelist()
def install() -> dict[str, Any]:
    frappe.set_user("Administrator")
    _assert_online_category_metadata()

    results: dict[str, str] = {}
    for spec in FIELDS:
        results[spec["fieldname"]] = _upsert_custom_field(spec)

    image_property = _upsert_image_visibility_property()

    frappe.clear_cache(doctype=ITEM_DOCTYPE)
    frappe.clear_cache(doctype=ONLINE_CATEGORY_DOCTYPE)
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "v0.7.65 Step 4 — Online Catalog Fields",
        "fields": results,
        "standard_item_image_visibility": image_property,
        "online_price_added": False,
        "units_inside_box_added": False,
        "data_migration": False,
    }
