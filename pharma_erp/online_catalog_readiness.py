from __future__ import annotations

import json
from collections import Counter
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, strip_html


VALID_AVAILABILITY_STATUSES = {
    "Available",
    "Temporarily Unavailable",
    "Coming Soon",
    "Hidden",
}

STATUS_ORDER = {
    "Not Ready": 0,
    "Warning": 1,
    "Ready": 2,
    "Not Selected": 3,
}

CHECK_WEIGHTS = {
    "category": 20,
    "availability": 10,
    "price": 20,
    "image": 15,
    "description_ar": 15,
    "description_en": 10,
    "keywords": 5,
    "sort_order": 5,
}


def _as_dict(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _plain_text(value: Any) -> str:
    text = strip_html(str(value or ""))
    return (
        text.replace("&nbsp;", " ")
        .replace("\u00a0", " ")
        .strip()
    )


def _get_online_category_map() -> dict[str, dict[str, Any]]:
    rows = frappe.get_all(
        "Online Category",
        fields=["name", "category_name", "is_group", "enabled"],
    )
    return {row.name: row for row in rows}


def _get_standard_selling_prices(item_codes: list[str]) -> dict[str, float]:
    if not item_codes:
        return {}

    rows = frappe.get_all(
        "Item Price",
        filters={
            "price_list": "Standard Selling",
            "item_code": ["in", item_codes],
        },
        fields=[
            "item_code",
            "price_list_rate",
            "valid_from",
            "modified",
        ],
        order_by="item_code asc, valid_from desc, modified desc",
        limit_page_length=0,
    )

    result: dict[str, float] = {}
    for row in rows:
        result.setdefault(row.item_code, flt(row.price_list_rate))
    return result


def _get_item_fields() -> list[str]:
    fields = [
        "name",
        "item_name",
        "item_group",
        "disabled",
        "image",
        "custom_show_online",
        "custom_online_category",
        "custom_requires_prescription",
        "custom_featured_product",
        "custom_online_availability_status",
        "custom_online_sort_order",
        "custom_online_description_ar",
        "custom_online_description_en",
        "custom_search_keywords__aliases",
    ]
    meta = frappe.get_meta("Item")
    if meta.has_field("custom_customer_price"):
        fields.append("custom_customer_price")
    return fields


def _issue(code: str, message: str, level: str) -> dict[str, str]:
    return {
        "code": code,
        "message": message,
        "level": level,
    }


def evaluate_item_readiness(
    item: dict[str, Any],
    category_map: dict[str, dict[str, Any]],
    standard_selling_price: float = 0,
) -> dict[str, Any]:
    show_online = cint(item.get("custom_show_online"))
    disabled = cint(item.get("disabled"))
    category_name = item.get("custom_online_category") or ""
    availability = item.get("custom_online_availability_status") or ""
    featured = cint(item.get("custom_featured_product"))
    requires_prescription = cint(item.get("custom_requires_prescription"))
    sort_order = cint(item.get("custom_online_sort_order"))

    category = category_map.get(category_name)
    category_ok = bool(
        category_name
        and category
        and not cint(category.get("is_group"))
        and cint(category.get("enabled"))
    )

    customer_price = flt(item.get("custom_customer_price"))
    standard_selling_price = flt(standard_selling_price)
    effective_price = customer_price or standard_selling_price
    price_source = (
        "Item Customer Price"
        if customer_price > 0
        else "Standard Selling"
        if standard_selling_price > 0
        else ""
    )

    image_ok = bool(str(item.get("image") or "").strip())
    description_ar_ok = bool(
        _plain_text(item.get("custom_online_description_ar"))
    )
    description_en_ok = bool(
        _plain_text(item.get("custom_online_description_en"))
    )
    keywords_ok = bool(
        str(item.get("custom_search_keywords__aliases") or "").strip()
    )
    availability_ok = (
        availability in VALID_AVAILABILITY_STATUSES
        and availability != "Hidden"
    )
    price_ok = effective_price > 0
    sort_order_ok = sort_order > 0

    checks = {
        "category": category_ok,
        "availability": availability_ok,
        "price": price_ok,
        "image": image_ok,
        "description_ar": description_ar_ok,
        "description_en": description_en_ok,
        "keywords": keywords_ok,
        "sort_order": sort_order_ok,
    }
    score = sum(
        CHECK_WEIGHTS[key]
        for key, passed in checks.items()
        if passed
    )

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if disabled:
        blockers.append(
            _issue(
                "disabled_item",
                _("Item is disabled."),
                "Not Ready",
            )
        )

    if not category_name:
        blockers.append(
            _issue(
                "missing_category",
                _("Online Category is required."),
                "Not Ready",
            )
        )
    elif not category:
        blockers.append(
            _issue(
                "unknown_category",
                _("The selected Online Category does not exist."),
                "Not Ready",
            )
        )
    elif cint(category.get("is_group")):
        blockers.append(
            _issue(
                "group_category",
                _("Select a leaf Online Category, not a group."),
                "Not Ready",
            )
        )
    elif not cint(category.get("enabled")):
        blockers.append(
            _issue(
                "disabled_category",
                _("The selected Online Category is disabled."),
                "Not Ready",
            )
        )

    if not availability:
        blockers.append(
            _issue(
                "missing_availability",
                _("Online Availability Status is required."),
                "Not Ready",
            )
        )
    elif availability not in VALID_AVAILABILITY_STATUSES:
        blockers.append(
            _issue(
                "invalid_availability",
                _("Online Availability Status is invalid."),
                "Not Ready",
            )
        )
    elif availability == "Hidden":
        blockers.append(
            _issue(
                "hidden_availability",
                _("Show Online conflicts with availability status Hidden."),
                "Not Ready",
            )
        )

    if not price_ok:
        blockers.append(
            _issue(
                "missing_price",
                _(
                    "A positive Customer Price or Standard Selling price "
                    "is required."
                ),
                "Not Ready",
            )
        )

    if not image_ok:
        blockers.append(
            _issue(
                "missing_image",
                _("A product image is required."),
                "Not Ready",
            )
        )

    if not description_ar_ok:
        blockers.append(
            _issue(
                "missing_description_ar",
                _("Arabic online description is required."),
                "Not Ready",
            )
        )

    if not description_en_ok:
        warnings.append(
            _issue(
                "missing_description_en",
                _("English online description is missing."),
                "Warning",
            )
        )

    if not keywords_ok:
        warnings.append(
            _issue(
                "missing_keywords",
                _(
                    "Search Keywords / Aliases are missing. "
                    "This existing field is also used for online search."
                ),
                "Warning",
            )
        )

    if not sort_order_ok:
        warnings.append(
            _issue(
                "missing_sort_order",
                _("Online Sort Order should be greater than zero."),
                "Warning",
            )
        )

    if featured and availability != "Available":
        warnings.append(
            _issue(
                "featured_not_available",
                _(
                    "Featured Product is selected while the item is not "
                    "Available."
                ),
                "Warning",
            )
        )

    if not show_online:
        status = "Not Selected"
    elif blockers:
        status = "Not Ready"
    elif warnings:
        status = "Warning"
    else:
        status = "Ready"

    issues = blockers + warnings

    return {
        "item_code": item.get("name"),
        "item_name": item.get("item_name"),
        "item_group": item.get("item_group"),
        "disabled": disabled,
        "show_online": show_online,
        "online_category": category_name,
        "availability_status": availability,
        "effective_price": effective_price,
        "price_source": price_source,
        "has_image": cint(image_ok),
        "has_description_ar": cint(description_ar_ok),
        "has_description_en": cint(description_en_ok),
        "has_keywords": cint(keywords_ok),
        "online_sort_order": sort_order,
        "requires_prescription": requires_prescription,
        "featured_product": featured,
        "readiness_status": status,
        "readiness_score": score,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "issues": issues,
        "issues_text": "\n".join(issue["message"] for issue in issues),
    }


def get_readiness_rows(filters: dict[str, Any] | str | None = None) -> list[dict]:
    filters = _as_dict(filters)
    item_filters: dict[str, Any] = {}

    item_group = filters.get("item_group")
    if item_group:
        item_filters["item_group"] = item_group

    online_category = filters.get("online_category")
    if online_category:
        item_filters["custom_online_category"] = online_category

    if not cint(filters.get("include_disabled")):
        item_filters["disabled"] = 0

    scope = filters.get("show_online_scope") or "Show Online Only"
    if scope == "Show Online Only":
        item_filters["custom_show_online"] = 1
    elif scope == "Not Selected Only":
        item_filters["custom_show_online"] = 0

    items = frappe.get_all(
        "Item",
        filters=item_filters,
        fields=_get_item_fields(),
        order_by="item_name asc, name asc",
        limit_page_length=0,
    )

    category_map = _get_online_category_map()
    prices = _get_standard_selling_prices(
        [item.name for item in items]
    )

    rows = [
        evaluate_item_readiness(
            item,
            category_map,
            prices.get(item.name, 0),
        )
        for item in items
    ]

    status_filter = filters.get("readiness_status")
    if status_filter:
        rows = [
            row
            for row in rows
            if row["readiness_status"] == status_filter
        ]

    rows.sort(
        key=lambda row: (
            STATUS_ORDER.get(row["readiness_status"], 99),
            row["online_sort_order"] or 999999,
            row["item_name"] or "",
            row["item_code"] or "",
        )
    )
    return rows


@frappe.whitelist()
def get_item_readiness(item_name: str) -> dict[str, Any]:
    item = frappe.db.get_value(
        "Item",
        item_name,
        _get_item_fields(),
        as_dict=True,
    )
    if not item:
        frappe.throw(_("Item {0} was not found.").format(item_name))

    category_map = _get_online_category_map()
    prices = _get_standard_selling_prices([item_name])
    return evaluate_item_readiness(
        item,
        category_map,
        prices.get(item_name, 0),
    )


@frappe.whitelist()
def preview() -> dict[str, Any]:
    rows = get_readiness_rows(
        {
            "show_online_scope": "All Items",
            "include_disabled": 1,
        }
    )
    counts = Counter(row["readiness_status"] for row in rows)
    show_online_count = sum(row["show_online"] for row in rows)

    return {
        "status": "ok",
        "step": (
            "v0.7.65 Step 8 — Online Catalog Publishing Framework"
        ),
        "total_items": len(rows),
        "show_online_count": show_online_count,
        "readiness_counts": {
            "Ready": counts.get("Ready", 0),
            "Warning": counts.get("Warning", 0),
            "Not Ready": counts.get("Not Ready", 0),
            "Not Selected": counts.get("Not Selected", 0),
        },
        "sample_issues": [
            {
                "item_code": row["item_code"],
                "item_name": row["item_name"],
                "readiness_status": row["readiness_status"],
                "readiness_score": row["readiness_score"],
                "issues": row["issues_text"],
            }
            for row in rows
            if row["readiness_status"] in {"Not Ready", "Warning"}
        ][:20],
        "policy": {
            "current_items_are_test_data": True,
            "item_records_changed": False,
            "dynamic_report_only": True,
            "online_keywords_field": (
                "custom_search_keywords__aliases"
            ),
            "category_must_be_enabled_leaf": True,
            "stock_is_not_a_publish_blocker": True,
            "prescription_flag_is_not_a_publish_blocker": True,
            "arabic_description_is_required": True,
            "english_description_is_warning": True,
            "image_is_required": True,
            "positive_selling_price_is_required": True,
        },
    }


def validate_item_online_catalog_selection(doc, method=None) -> None:
    if not cint(doc.get("custom_show_online")):
        return

    category_name = doc.get("custom_online_category")
    if not category_name:
        frappe.throw(
            _("Online Category is required when Show Online is selected.")
        )

    category = frappe.db.get_value(
        "Online Category",
        category_name,
        ["is_group", "enabled"],
        as_dict=True,
    )
    if not category:
        frappe.throw(
            _("Online Category {0} does not exist.").format(
                frappe.bold(category_name)
            )
        )
    if cint(category.is_group):
        frappe.throw(
            _(
                "Select a leaf Online Category for item {0}; "
                "group categories cannot contain products directly."
            ).format(frappe.bold(doc.name or doc.item_code))
        )
    if not cint(category.enabled):
        frappe.throw(
            _("Online Category {0} is disabled.").format(
                frappe.bold(category_name)
            )
        )
