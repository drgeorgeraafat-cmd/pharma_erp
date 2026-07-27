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
    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Online Order")
    frappe.clear_cache(doctype="Sales Order")
    frappe.clear_cache(doctype="Sales Invoice")
    frappe.db.commit()
    return verify()


def verify():
    online_meta = frappe.get_meta("Online Order")
    status_field = online_meta.get_field("status")
    status_options = [
        value.strip()
        for value in str(status_field.options or "").splitlines()
        if value.strip()
    ]

    result = {
        "online_order_exists": bool(frappe.db.exists("DocType", "Online Order")),
        "ready_for_pickup_status": "Ready for Pickup" in status_options,
        "sales_order_link": frappe.get_meta("Sales Order").has_field("custom_online_order"),
        "sales_invoice_link": frappe.get_meta("Sales Invoice").has_field("custom_online_order"),
        "conversion_method": False,
    }

    try:
        from pharma_erp.pharma_erp.doctype.online_order.online_order import (
            create_sales_invoice_draft,
        )

        result["conversion_method"] = callable(create_sales_invoice_draft)
    except Exception:
        result["conversion_method"] = False

    result["ok"] = all(result.values())
    print(result)
    return result
