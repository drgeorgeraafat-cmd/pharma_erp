from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


ITEM_FIELD_UPDATES = {
    "custom_customer_price": {
        "description": (
            "Official customer price for one full Box. This is the primary retail "
            "price source and is synchronized with the configured selling price list."
        ),
    },
    "custom_pack_size": {
        "description": "Number of sellable Units inside one Box.",
    },
    "custom_pharmacy_group": {
        "label": "Primary Use",
        "description": "Main therapeutic or customer use for this item.",
    },
    "custom_controlled_drug": {
        "insert_after": "custom_additional_uses",
    },
    "custom_box_only": {
        "description": "When enabled, the item can only be sold as a full Box.",
    },
    "custom_uom_options": {
        "label": "Unit Type",
        "description": (
            "Meaning of Unit for this item, for example Strip, Tablet, Ampoule, "
            "Film, or Sachet. Accounting sale units remain Box and Unit."
        ),
    },
}


def _custom_field_name(fieldname: str) -> str | None:
    return frappe.db.get_value(
        "Custom Field", {"dt": "Item", "fieldname": fieldname}, "name"
    )


def _update_existing_item_fields() -> None:
    missing: list[str] = []
    for fieldname, values in ITEM_FIELD_UPDATES.items():
        name = _custom_field_name(fieldname)
        if not name:
            missing.append(fieldname)
            continue
        frappe.db.set_value(
            "Custom Field", name, values, update_modified=False
        )

    if missing:
        frappe.throw(
            "Required existing Item custom fields are missing: "
            + ", ".join(sorted(missing))
        )


def _ensure_additional_uses_field() -> None:
    create_custom_fields(
        {
            "Item": [
                {
                    "fieldname": "custom_additional_uses",
                    "label": "Additional Uses",
                    "fieldtype": "Table MultiSelect",
                    "options": "Item Pharmacy Use",
                    "insert_after": "custom_pharmacy_group",
                    "description": (
                        "Optional additional therapeutic or customer uses. "
                        "Primary Use remains the main classification."
                    ),
                }
            ]
        },
        update=True,
    )


def _validate_result() -> None:
    expected = {
        "custom_pharmacy_group": ("Primary Use", "Link", "Pharmacy Group"),
        "custom_additional_uses": (
            "Additional Uses",
            "Table MultiSelect",
            "Item Pharmacy Use",
        ),
        "custom_uom_options": ("Unit Type", "Select", None),
    }

    for fieldname, (label, fieldtype, options) in expected.items():
        row = frappe.db.get_value(
            "Custom Field",
            {"dt": "Item", "fieldname": fieldname},
            ["label", "fieldtype", "options"],
            as_dict=True,
        )
        if not row:
            frappe.throw(f"Custom field was not created or found: {fieldname}")
        if row.label != label or row.fieldtype != fieldtype:
            frappe.throw(
                f"Unexpected metadata for {fieldname}: "
                f"label={row.label!r}, fieldtype={row.fieldtype!r}"
            )
        if options is not None and row.options != options:
            frappe.throw(
                f"Unexpected options for {fieldname}: {row.options!r}"
            )

    if not frappe.db.exists("DocType", "Item Pharmacy Use"):
        frappe.throw("Item Pharmacy Use DocType was not synchronized.")

    child = frappe.get_meta("Item Pharmacy Use")
    if not child.istable:
        frappe.throw("Item Pharmacy Use must be a child table DocType.")
    use_field = child.get_field("pharmacy_group")
    if not use_field or use_field.fieldtype != "Link" or use_field.options != "Pharmacy Group":
        frappe.throw("Item Pharmacy Use.pharmacy_group metadata is invalid.")


def install() -> dict[str, object]:
    """Install Step 3: Item Uses and Item form label structure.

    This installer is intentionally idempotent. It does not migrate or alter
    existing item values, prices, stock, invoices, or test transactions.
    """
    _ensure_additional_uses_field()
    _update_existing_item_fields()
    _validate_result()

    frappe.clear_cache(doctype="Item")
    frappe.clear_cache(doctype="Item Pharmacy Use")
    frappe.db.commit()

    return {
        "status": "ok",
        "step": "v0.7.65 Step 3 — Uses & Item Form Structure",
        "created": ["Item Pharmacy Use", "Item.custom_additional_uses"],
        "renamed_labels": {
            "custom_pharmacy_group": "Primary Use",
            "custom_uom_options": "Unit Type",
        },
        "data_migration": False,
        "online_catalog_fields_added": False,
    }
