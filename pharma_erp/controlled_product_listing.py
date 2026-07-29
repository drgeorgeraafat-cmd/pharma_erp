from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, flt, strip_html

DEFAULT_PAGE_LENGTH = 24
MAX_PAGE_LENGTH = 48
VISIBLE_AVAILABILITY_STATUSES = (
    "Available",
    "Temporarily Unavailable",
    "Coming Soon",
)


@dataclass(frozen=True)
class CatalogQuery:
    search: str
    category: str
    availability: str
    featured_only: bool
    start: int
    page_length: int


def _clean_text(value: Any, limit: int = 180) -> str:
    text = (value or "").strip()
    return text[:limit]


def _normalise_query(
    search: str | None = None,
    category: str | None = None,
    availability: str | None = None,
    featured: int | str | bool | None = None,
    start: int | str | None = 0,
    page_length: int | str | None = DEFAULT_PAGE_LENGTH,
) -> CatalogQuery:
    clean_availability = _clean_text(availability, 80)
    if clean_availability and clean_availability not in VISIBLE_AVAILABILITY_STATUSES:
        clean_availability = ""

    safe_start = max(cint(start), 0)
    safe_page_length = min(max(cint(page_length) or DEFAULT_PAGE_LENGTH, 1), MAX_PAGE_LENGTH)

    return CatalogQuery(
        search=_clean_text(search, 120),
        category=_clean_text(category, 140),
        availability=clean_availability,
        featured_only=bool(cint(featured)),
        start=safe_start,
        page_length=safe_page_length,
    )


def _default_company() -> str:
    return (
        frappe.defaults.get_global_default("company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or ""
    )


def _catalog_brand() -> dict[str, str]:
    company = _default_company()
    company_name = company
    company_logo = ""
    currency = frappe.defaults.get_global_default("currency") or "EGP"

    if company and frappe.db.exists("Company", company):
        company_row = frappe.db.get_value(
            "Company",
            company,
            ["company_name", "company_logo", "default_currency"],
            as_dict=True,
        ) or {}
        company_name = company_row.get("company_name") or company
        company_logo = company_row.get("company_logo") or ""
        currency = company_row.get("default_currency") or currency

    return {
        "company": company,
        "company_name": company_name or _("Online Pharmacy"),
        "company_logo": company_logo,
        "currency": currency,
    }




def _format_public_price(price: float, currency: str) -> str:
    """Return a stable public price using the ISO currency code.

    ERPNext currency symbols can contain locale alternatives (for example
    multiple EGP symbols joined with "or"). The controlled catalog should
    show one predictable customer-facing value instead.
    """
    clean_currency = (currency or "EGP").strip().upper() or "EGP"
    return f"{price:,.2f} {clean_currency}"

def _catalog_where(query: CatalogQuery, include_search: bool = True) -> tuple[str, dict[str, Any]]:
    conditions = [
        "wi.published = 1",
        "COALESCE(wi.custom_pharma_managed, 0) = 1",
        "COALESCE(i.disabled, 0) = 0",
        "COALESCE(wi.custom_online_availability_status, '') != 'Hidden'",
    ]
    values: dict[str, Any] = {}

    if query.category:
        conditions.append("wi.custom_online_category = %(category)s")
        values["category"] = query.category

    if query.availability:
        conditions.append("wi.custom_online_availability_status = %(availability)s")
        values["availability"] = query.availability

    if query.featured_only:
        conditions.append("COALESCE(wi.custom_featured_product, 0) = 1")

    if include_search and query.search:
        values["search"] = f"%{query.search}%"
        conditions.append(
            "("
            "wi.item_code LIKE %(search)s OR "
            "wi.web_item_name LIKE %(search)s OR "
            "i.item_name LIKE %(search)s OR "
            "COALESCE(i.custom_search_keywords__aliases, '') LIKE %(search)s OR "
            "COALESCE(wi.custom_online_description_ar, '') LIKE %(search)s OR "
            "COALESCE(wi.custom_online_description_en, '') LIKE %(search)s"
            ")"
        )

    return " AND ".join(conditions), values


def _catalog_select_sql(where_sql: str) -> str:
    return f"""
        SELECT
            wi.name AS website_item,
            wi.item_code,
            wi.web_item_name,
            wi.website_image,
            wi.route AS webshop_route,
            wi.custom_online_category,
            COALESCE(wi.custom_requires_prescription, 0) AS requires_prescription,
            COALESCE(wi.custom_featured_product, 0) AS featured_product,
            wi.custom_online_availability_status,
            COALESCE(wi.custom_online_sort_order, 999999) AS online_sort_order,
            wi.custom_online_description_ar,
            wi.custom_online_description_en,
            i.item_name,
            COALESCE(i.custom_customer_price, 0) AS customer_price,
            COALESCE(i.custom_search_keywords__aliases, '') AS search_keywords
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON i.name = wi.item_code
        WHERE {where_sql}
    """


def _serialise_product(row: dict[str, Any], currency: str) -> dict[str, Any]:
    item_code = row.get("item_code") or ""
    price = flt(row.get("customer_price"))
    description_ar = row.get("custom_online_description_ar") or ""
    description_en = row.get("custom_online_description_en") or ""
    summary_source = description_ar or description_en or row.get("item_name") or ""
    summary = " ".join(strip_html(summary_source).split())[:220]
    webshop_route = (row.get("webshop_route") or "").lstrip("/")

    return {
        "website_item": row.get("website_item"),
        "item_code": item_code,
        "item_name": row.get("web_item_name") or row.get("item_name") or item_code,
        "image": row.get("website_image") or "",
        "category": row.get("custom_online_category") or "",
        "availability": row.get("custom_online_availability_status") or "Available",
        "requires_prescription": cint(row.get("requires_prescription")),
        "featured": cint(row.get("featured_product")),
        "online_sort_order": cint(row.get("online_sort_order")),
        "description_ar": strip_html(description_ar),
        "description_en": strip_html(description_en),
        "summary": summary,
        "keywords": row.get("search_keywords") or "",
        "price": price,
        "currency": currency,
        "price_formatted": _format_public_price(price, currency),
        "availability_label_ar": {
            "Available": "متاح",
            "Temporarily Unavailable": "غير متاح مؤقتًا",
            "Coming Soon": "قريبًا",
        }.get(row.get("custom_online_availability_status") or "Available", row.get("custom_online_availability_status") or "Available"),
        "product_url": f"/pharmacy-product/?item={quote(item_code)}",
        "webshop_url": f"/{webshop_route}" if webshop_route else "",
    }


def _published_categories() -> list[str]:
    rows = frappe.db.sql(
        """
        SELECT DISTINCT wi.custom_online_category
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON i.name = wi.item_code
        WHERE wi.published = 1
          AND COALESCE(wi.custom_pharma_managed, 0) = 1
          AND COALESCE(i.disabled, 0) = 0
          AND COALESCE(wi.custom_online_availability_status, '') != 'Hidden'
          AND COALESCE(wi.custom_online_category, '') != ''
        ORDER BY wi.custom_online_category ASC
        """,
        as_list=True,
    )
    return [row[0] for row in rows if row and row[0]]


@frappe.whitelist(allow_guest=True)
def get_public_products(
    search: str | None = None,
    category: str | None = None,
    availability: str | None = None,
    featured: int | str | bool | None = None,
    start: int | str | None = 0,
    page_length: int | str | None = DEFAULT_PAGE_LENGTH,
) -> dict[str, Any]:
    """Return only published, bridge-managed, visible Website Items.

    This endpoint is read-only. It does not create carts, Quotations, Sales Orders,
    Online Orders, stock movements, invoices, payments, or ledger entries.
    """
    query = _normalise_query(
        search=search,
        category=category,
        availability=availability,
        featured=featured,
        start=start,
        page_length=page_length,
    )
    where_sql, values = _catalog_where(query)
    brand = _catalog_brand()

    count_row = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON i.name = wi.item_code
        WHERE {where_sql}
        """,
        values,
        as_list=True,
    )
    total_count = cint(count_row[0][0] if count_row else 0)

    values.update({"start": query.start, "page_length": query.page_length})
    rows = frappe.db.sql(
        _catalog_select_sql(where_sql)
        + """
        ORDER BY
            COALESCE(wi.custom_featured_product, 0) DESC,
            COALESCE(wi.custom_online_sort_order, 999999) ASC,
            wi.web_item_name ASC,
            wi.item_code ASC
        LIMIT %(start)s, %(page_length)s
        """,
        values,
        as_dict=True,
    )

    items = [_serialise_product(row, brand["currency"]) for row in rows]
    return {
        "items": items,
        "total_count": total_count,
        "start": query.start,
        "page_length": query.page_length,
        "has_more": query.start + len(items) < total_count,
        "categories": _published_categories(),
        "availability_options": list(VISIBLE_AVAILABILITY_STATUSES),
        "brand": brand,
        "read_only_catalog": 1,
    }


def get_public_product(item_code: str | None) -> dict[str, Any] | None:
    clean_item_code = _clean_text(item_code, 140)
    if not clean_item_code:
        return None

    query = _normalise_query(page_length=1)
    where_sql, values = _catalog_where(query, include_search=False)
    where_sql += " AND wi.item_code = %(item_code)s"
    values["item_code"] = clean_item_code
    brand = _catalog_brand()

    rows = frappe.db.sql(
        _catalog_select_sql(where_sql) + " LIMIT 1",
        values,
        as_dict=True,
    )
    if not rows:
        return None

    product = _serialise_product(rows[0], brand["currency"])
    product["brand"] = brand
    return product


@frappe.whitelist(allow_guest=True)
def get_public_product_detail(item_code: str | None = None) -> dict[str, Any]:
    product = get_public_product(item_code)
    if not product:
        frappe.throw(_("This product is not published or is not available online."), frappe.DoesNotExistError)
    return product
