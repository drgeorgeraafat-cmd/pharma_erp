from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CUSTOM_FIELDS = {
    "Sales Order": [
        {
            "fieldname": "custom_online_order",
            "label": "Online Order",
            "fieldtype": "Link",
            "options": "Online Order",
            "insert_after": "customer",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        }
    ],
    "Sales Invoice": [
        {
            "fieldname": "custom_online_order",
            "label": "Online Order",
            "fieldtype": "Link",
            "options": "Online Order",
            "insert_after": "custom_order_type",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        }
    ],
}


def install():
    if not frappe.db.exists("DocType", "Online Order"):
        frappe.throw("Online Order DocType is not installed. Run bench migrate first.")
    if not frappe.db.exists("DocType", "Online Order Item"):
        frappe.throw("Online Order Item DocType is not installed. Run bench migrate first.")

    create_custom_fields(CUSTOM_FIELDS, update=True)
    _add_indexes()
    frappe.clear_cache(doctype="Online Order")
    frappe.clear_cache(doctype="Sales Order")
    frappe.clear_cache(doctype="Sales Invoice")
    frappe.db.commit()
    return verify()


def _add_indexes():
    index_specs = [
        ("Online Order", ["status"]),
        ("Online Order", ["mobile_no"]),
        ("Online Order", ["customer"]),
        ("Online Order", ["sales_invoice"]),
        ("Online Order", ["sales_order"]),
    ]
    for doctype, fields in index_specs:
        try:
            frappe.db.add_index(doctype, fields)
        except Exception:
            # Index may already exist or the database engine may generate an equivalent name.
            pass


def verify():
    required_online_order_fields = {
        "status",
        "source_channel",
        "fulfilment_method",
        "customer",
        "mobile_no",
        "delivery_zone",
        "items",
        "prescription_review_status",
        "payment_status",
        "sales_order",
        "sales_invoice",
    }
    online_meta = frappe.get_meta("Online Order")
    present = {df.fieldname for df in online_meta.fields}
    missing = sorted(required_online_order_fields - present)

    result = {
        "online_order_exists": bool(frappe.db.exists("DocType", "Online Order")),
        "online_order_item_exists": bool(frappe.db.exists("DocType", "Online Order Item")),
        "missing_online_order_fields": missing,
        "sales_order_link": frappe.get_meta("Sales Order").has_field("custom_online_order"),
        "sales_invoice_link": frappe.get_meta("Sales Invoice").has_field("custom_online_order"),
    }
    result["ok"] = all(
        [
            result["online_order_exists"],
            result["online_order_item_exists"],
            not result["missing_online_order_fields"],
            result["sales_order_link"],
            result["sales_invoice_link"],
        ]
    )
    print(result)
    return result
