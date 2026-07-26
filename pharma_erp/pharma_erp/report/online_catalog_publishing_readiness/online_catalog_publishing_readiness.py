from __future__ import annotations

from frappe import _

from pharma_erp.online_catalog_readiness import get_readiness_rows


def execute(filters=None):
    rows = get_readiness_rows(filters)
    columns = get_columns()

    counts = {
        "Ready": 0,
        "Warning": 0,
        "Not Ready": 0,
        "Not Selected": 0,
    }
    for row in rows:
        status = row.get("readiness_status")
        if status in counts:
            counts[status] += 1

    report_summary = [
        {
            "label": _("Ready"),
            "value": counts["Ready"],
            "indicator": "Green",
            "datatype": "Int",
        },
        {
            "label": _("Warning"),
            "value": counts["Warning"],
            "indicator": "Orange",
            "datatype": "Int",
        },
        {
            "label": _("Not Ready"),
            "value": counts["Not Ready"],
            "indicator": "Red",
            "datatype": "Int",
        },
        {
            "label": _("Not Selected"),
            "value": counts["Not Selected"],
            "indicator": "Blue",
            "datatype": "Int",
        },
    ]

    return columns, rows, None, None, report_summary


def get_columns():
    return [
        {
            "label": _("Item Code"),
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 130,
        },
        {
            "label": _("Item Name"),
            "fieldname": "item_name",
            "fieldtype": "Data",
            "width": 220,
        },
        {
            "label": _("Item Group"),
            "fieldname": "item_group",
            "fieldtype": "Link",
            "options": "Item Group",
            "width": 150,
        },
        {
            "label": _("Show Online"),
            "fieldname": "show_online",
            "fieldtype": "Check",
            "width": 95,
        },
        {
            "label": _("Online Category"),
            "fieldname": "online_category",
            "fieldtype": "Link",
            "options": "Online Category",
            "width": 180,
        },
        {
            "label": _("Availability"),
            "fieldname": "availability_status",
            "fieldtype": "Data",
            "width": 150,
        },
        {
            "label": _("Effective Price"),
            "fieldname": "effective_price",
            "fieldtype": "Currency",
            "width": 120,
        },
        {
            "label": _("Price Source"),
            "fieldname": "price_source",
            "fieldtype": "Data",
            "width": 135,
        },
        {
            "label": _("Image"),
            "fieldname": "has_image",
            "fieldtype": "Check",
            "width": 70,
        },
        {
            "label": _("Arabic Description"),
            "fieldname": "has_description_ar",
            "fieldtype": "Check",
            "width": 130,
        },
        {
            "label": _("English Description"),
            "fieldname": "has_description_en",
            "fieldtype": "Check",
            "width": 135,
        },
        {
            "label": _("Keywords"),
            "fieldname": "has_keywords",
            "fieldtype": "Check",
            "width": 85,
        },
        {
            "label": _("Sort Order"),
            "fieldname": "online_sort_order",
            "fieldtype": "Int",
            "width": 90,
        },
        {
            "label": _("Prescription"),
            "fieldname": "requires_prescription",
            "fieldtype": "Check",
            "width": 100,
        },
        {
            "label": _("Featured"),
            "fieldname": "featured_product",
            "fieldtype": "Check",
            "width": 80,
        },
        {
            "label": _("Status"),
            "fieldname": "readiness_status",
            "fieldtype": "Data",
            "width": 105,
        },
        {
            "label": _("Score"),
            "fieldname": "readiness_score",
            "fieldtype": "Percent",
            "width": 80,
        },
        {
            "label": _("Blockers"),
            "fieldname": "blocker_count",
            "fieldtype": "Int",
            "width": 75,
        },
        {
            "label": _("Warnings"),
            "fieldname": "warning_count",
            "fieldtype": "Int",
            "width": 80,
        },
        {
            "label": _("Issues"),
            "fieldname": "issues_text",
            "fieldtype": "Small Text",
            "width": 320,
        },
    ]
