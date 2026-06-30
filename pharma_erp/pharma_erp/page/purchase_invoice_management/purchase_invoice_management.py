"""Server API for the Purchase & Invoice Management desk page.

The page is an operational interface only. Purchase Invoice remains the official
stock and accounting document in ERPNext.
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date, datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from pharma_erp.purchase_management import get_purchase_settings


READ_ROLES = {
    "Purchase User",
    "Purchase Manager",
    "Accounts User",
    "Accounts Manager",
    "Stock User",
    "Stock Manager",
    "System Manager",
}


def _has_role_access() -> bool:
    return bool(READ_ROLES.intersection(set(frappe.get_roles())))


def _require_read_access() -> None:
    if not _has_role_access() or not frappe.has_permission("Purchase Invoice", "read"):
        frappe.throw(_("You are not permitted to access Purchase Management."), frappe.PermissionError)


def _require_create_access() -> None:
    _require_read_access()
    if not frappe.has_permission("Purchase Invoice", "create"):
        frappe.throw(_("You are not permitted to create Purchase Invoices."), frappe.PermissionError)


def _parse_payload(payload: Any) -> frappe._dict:
    if isinstance(payload, str):
        payload = frappe.parse_json(payload)
    if not isinstance(payload, dict):
        frappe.throw(_("Invalid purchase invoice payload."))
    return frappe._dict(payload)


def _meta_fieldnames(doctype: str) -> set[str]:
    return {field.fieldname for field in frappe.get_meta(doctype).fields if field.fieldname}


def _safe_fields(doctype: str, desired: list[str]) -> list[str]:
    available = _meta_fieldnames(doctype)
    return [fieldname for fieldname in desired if fieldname in available or fieldname == "name"]


def _first_existing_field(doctype: str, candidates: list[str]) -> str | None:
    available = _meta_fieldnames(doctype)
    return next((fieldname for fieldname in candidates if fieldname in available), None)


def _search_pattern(txt: str | None) -> tuple[str, str, str]:
    """Build the same tolerant search pattern used by Pharmacy POS.

    Spaces, percent signs and asterisks are treated as wildcards. The compact
    value also permits matching names typed without spaces or hyphens.
    """
    raw = (txt or "").strip()
    tokens = [token for token in re.split(r"[\s*%]+", raw) if token]
    like_pattern = "%" + "%".join(tokens) + "%" if tokens else "%"
    compact = re.sub(r"[\s*%_-]+", "", raw).lower()
    return raw, like_pattern, compact


def _default_company() -> str | None:
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.defaults.get_global_default("company")
        or frappe.db.get_value("Company", {}, "name", order_by="is_group asc, creation asc")
    )


def _default_warehouse(company: str | None) -> str | None:
    warehouse = frappe.defaults.get_user_default("Warehouse")
    if warehouse and frappe.db.exists("Warehouse", warehouse):
        return warehouse
    if not company:
        return None
    return frappe.db.get_value(
        "Warehouse",
        {"company": company, "is_group": 0, "disabled": 0},
        "name",
        order_by="creation asc",
    )


def _default_buying_price_list() -> str | None:
    if frappe.db.exists("DocType", "Buying Settings"):
        return frappe.db.get_single_value("Buying Settings", "buying_price_list")
    return None


def _purchase_invoice_fields() -> list[str]:
    return _safe_fields(
        "Purchase Invoice",
        [
            "name",
            "supplier",
            "supplier_name",
            "bill_no",
            "posting_date",
            "status",
            "docstatus",
            "grand_total",
            "outstanding_amount",
            "currency",
            "custom_payment_classification",
        ],
    )


def _filtered_purchase_invoices(
    company: str | None,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    supplier: str | None = None,
    item_code: str | None = None,
    limit: int = 30,
) -> list[dict]:
    filters: dict[str, Any] = {}
    if company:
        filters["company"] = company
    if from_date:
        filters["posting_date"] = [">=", getdate(from_date)]
    if to_date:
        if "posting_date" in filters:
            filters["posting_date"] = ["between", [getdate(from_date), getdate(to_date)]]
        else:
            filters["posting_date"] = ["<=", getdate(to_date)]
    if supplier:
        filters["supplier"] = supplier
    if item_code:
        parents = frappe.get_all(
            "Purchase Invoice Item",
            filters={"item_code": item_code, "parenttype": "Purchase Invoice"},
            pluck="parent",
            limit_page_length=5000,
        )
        if not parents:
            return []
        filters["name"] = ["in", parents]

    return frappe.get_list(
        "Purchase Invoice",
        filters=filters,
        fields=_purchase_invoice_fields(),
        order_by="posting_date desc, modified desc",
        limit_page_length=max(1, min(cint(limit) or 30, 100)),
    )


def _recent_invoices(company: str | None, limit: int = 12) -> list[dict]:
    return _filtered_purchase_invoices(company, limit=max(1, min(cint(limit), 30)))


@frappe.whitelist()
def get_bootstrap(company: str | None = None):
    _require_read_access()
    company = company or _default_company()
    company_currency = (
        frappe.db.get_value("Company", company, "default_currency") if company else None
    )
    settings = get_purchase_settings()
    item_tax_template_names = frappe.get_all(
        "Item Tax Template",
        filters={"company": company, "disabled": 0} if company else {"disabled": 0},
        pluck="name",
        order_by="name asc",
        limit_page_length=500,
    ) if frappe.db.exists("DocType", "Item Tax Template") else []
    item_tax_templates = [
        {"name": name, "rate": _item_tax_template_rate(name)}
        for name in item_tax_template_names
    ]
    return {
        "company": company,
        "currency": company_currency,
        "default_warehouse": _default_warehouse(company),
        "buying_price_list": _default_buying_price_list(),
        "posting_date": nowdate(),
        "purchase_settings": dict(settings),
        "item_tax_templates": item_tax_templates,
        "recent_invoices": _recent_invoices(company),
        "can_create": bool(frappe.has_permission("Purchase Invoice", "create")),
        "can_submit": bool(frappe.has_permission("Purchase Invoice", "submit")),
    }


@frappe.whitelist()
def search_purchase_invoices(
    company: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    supplier: str | None = None,
    item_code: str | None = None,
    limit: int = 50,
):
    _require_read_access()
    company = company or _default_company()
    if from_date and to_date and getdate(from_date) > getdate(to_date):
        frappe.throw(_("From Date cannot be after To Date."))
    if supplier and not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Supplier does not exist."))
    if item_code and not frappe.db.exists("Item", item_code):
        frappe.throw(_("Item does not exist."))
    return _filtered_purchase_invoices(
        company,
        from_date=from_date or None,
        to_date=to_date or None,
        supplier=supplier or None,
        item_code=item_code or None,
        limit=limit,
    )


def _supplier_balance(supplier: str, company: str | None) -> float:
    if not supplier or not company:
        return 0.0
    try:
        from erpnext.accounts.utils import get_balance_on

        return flt(
            get_balance_on(
                party_type="Supplier",
                party=supplier,
                company=company,
                date=nowdate(),
            )
        )
    except Exception:
        outstanding = frappe.db.sql(
            """
            SELECT COALESCE(SUM(outstanding_amount), 0)
            FROM `tabPurchase Invoice`
            WHERE docstatus = 1
              AND company = %(company)s
              AND supplier = %(supplier)s
            """,
            {"company": company, "supplier": supplier},
        )
        return flt(outstanding[0][0] if outstanding else 0)


def _safe_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(max(1, cint(day)), calendar.monthrange(year, month)[1]))


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + offset
    return absolute // 12, absolute % 12 + 1


def _claim_period_for_date(supplier: str, bill_date) -> dict:
    if not supplier or not bill_date:
        return {}
    fields = _safe_fields("Supplier", ["custom_claim_cycle_start_day", "custom_claim_cycle_end_day"])
    values = frappe.db.get_value("Supplier", supplier, fields, as_dict=True) or frappe._dict()
    start_day = cint(values.get("custom_claim_cycle_start_day"))
    end_day = cint(values.get("custom_claim_cycle_end_day"))
    if not start_day or not end_day:
        return {}
    basis = getdate(bill_date)
    if basis.day >= start_day:
        start_year, start_month = basis.year, basis.month
    else:
        start_year, start_month = _shift_month(basis.year, basis.month, -1)
    end_year, end_month = _shift_month(start_year, start_month, 1)
    return {
        "basis_date": basis,
        "period_from": _safe_day(start_year, start_month, start_day),
        "period_to": _safe_day(end_year, end_month, end_day),
    }


@frappe.whitelist()
def get_claim_period(supplier: str, bill_date: str | None = None):
    _require_read_access()
    if not supplier or not frappe.db.exists("Supplier", supplier):
        return {}
    return _claim_period_for_date(supplier, bill_date or nowdate())


@frappe.whitelist()
def get_supplier_context(supplier: str, company: str | None = None):
    _require_read_access()
    if not supplier or not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Select a valid supplier."))
    if not frappe.has_permission("Supplier", "read", supplier):
        frappe.throw(_("You are not permitted to read this supplier."), frappe.PermissionError)

    fields = _safe_fields(
        "Supplier",
        [
            "name",
            "supplier_name",
            "supplier_group",
            "supplier_type",
            "default_currency",
            "custom_purchase_supplier_type",
            "custom_purchase_payment_model",
            "custom_claim_cycle_start_day",
            "custom_claim_cycle_end_day",
            "custom_exclude_cash_invoices_from_claim",
            "custom_purchase_notes",
        ],
    )
    data = frappe.db.get_value("Supplier", supplier, fields, as_dict=True) or frappe._dict()
    payment_model = data.get("custom_purchase_payment_model")
    supplier_type = data.get("custom_purchase_supplier_type")
    if payment_model == "Cash":
        classification = "Cash Invoice"
    elif payment_model == "Credit Claim" or (supplier_type == "Distribution Company" and payment_model != "Mixed"):
        classification = "Claim Invoice"
    elif payment_model == "Mixed":
        classification = ""
    else:
        classification = ""

    company = company or _default_company()
    outstanding = frappe.db.sql(
        """
        SELECT COALESCE(SUM(outstanding_amount), 0)
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND supplier = %(supplier)s
          AND (%(company)s = '' OR company = %(company)s)
        """,
        {"supplier": supplier, "company": company or ""},
    )
    return {
        **dict(data),
        "balance": _supplier_balance(supplier, company),
        "outstanding_invoices": flt(outstanding[0][0] if outstanding else 0),
        "default_payment_classification": classification,
        "exclude_from_claim": cint(
            classification == "Cash Invoice"
            and data.get("custom_exclude_cash_invoices_from_claim")
        ),
    }


def _item_fields() -> list[str]:
    return _safe_fields(
        "Item",
        [
            "name",
            "item_name",
            "description",
            "stock_uom",
            "purchase_uom",
            "disabled",
            "is_purchase_item",
            "has_batch_no",
            "has_expiry_date",
            "item_group",
            "brand",
            "custom_customer_price",
            "custom_pack_size",
            "custom_box_only",
            "custom_item_origin",
            "custom_manufacturer",
            "custom_item_name_ar",
        ],
    )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_purchase_items(doctype, txt, searchfield, start, page_len, filters):
    """Purchase-item Link query with the Pharmacy POS search behaviour.

    Supports English/Arabic names, aliases/keywords, barcode, item code and
    wildcard separators using spaces, ``%`` or ``*``.
    """
    _require_read_access()
    raw, like_txt, compact_txt = _search_pattern(txt)
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    warehouse = filters.get("warehouse") or ""
    start = max(cint(start), 0)
    page_len = max(1, min(cint(page_len) or 20, 100))

    item_fields = _meta_fieldnames("Item")
    arabic_field = _first_existing_field("Item", ["custom_item_name_ar"])
    keywords_field = _first_existing_field(
        "Item", ["custom_search_keywords", "custom_search_keywords__aliases"]
    )
    price_field = _first_existing_field("Item", ["custom_customer_price"])
    arabic_sql = f"i.`{arabic_field}`" if arabic_field else "''"
    keywords_sql = f"i.`{keywords_field}`" if keywords_field else "''"
    price_sql = f"i.`{price_field}`" if price_field else "0"
    purchase_filter = "AND IFNULL(i.is_purchase_item, 1) = 1" if "is_purchase_item" in item_fields else ""

    return frappe.db.sql(
        f"""
        SELECT
            i.name,
            i.item_name,
            {arabic_sql} AS item_name_ar,
            COALESCE((
                SELECT SUM(bin.actual_qty)
                FROM `tabBin` bin
                WHERE bin.item_code = i.name
                  AND (%(warehouse)s = '' OR bin.warehouse = %(warehouse)s)
            ), 0) AS actual_qty,
            i.stock_uom,
            {price_sql} AS printed_retail_price
        FROM `tabItem` i
        LEFT JOIN `tabItem Barcode` ib ON ib.parent = i.name
        WHERE IFNULL(i.disabled, 0) = 0
          {purchase_filter}
          AND (
              i.name LIKE %(like_txt)s
              OR IFNULL(i.item_name, '') LIKE %(like_txt)s
              OR IFNULL({arabic_sql}, '') LIKE %(like_txt)s
              OR IFNULL({keywords_sql}, '') LIKE %(like_txt)s
              OR IFNULL(ib.barcode, '') LIKE %(like_txt)s
              OR REPLACE(REPLACE(LOWER(IFNULL(i.item_name, '')), ' ', ''), '-', '') LIKE %(compact_like)s
              OR REPLACE(REPLACE(LOWER(IFNULL({arabic_sql}, '')), ' ', ''), '-', '') LIKE %(compact_like)s
              OR REPLACE(REPLACE(LOWER(IFNULL({keywords_sql}, '')), ' ', ''), '-', '') LIKE %(compact_like)s
          )
        GROUP BY i.name
        ORDER BY
            MAX(CASE WHEN ib.barcode = %(raw)s THEN 0 ELSE 1 END),
            CASE WHEN i.name = %(raw)s THEN 0 ELSE 1 END,
            CASE WHEN LOWER(i.item_name) = LOWER(%(raw)s) THEN 0 ELSE 1 END,
            CASE WHEN LOWER(IFNULL({arabic_sql}, '')) = LOWER(%(raw)s) THEN 0 ELSE 1 END,
            CASE WHEN i.name LIKE %(starts)s THEN 0 ELSE 1 END,
            CASE WHEN i.item_name LIKE %(starts)s THEN 0 ELSE 1 END,
            i.item_name ASC, i.name ASC
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "raw": raw,
            "like_txt": like_txt,
            "compact_like": f"%{compact_txt}%",
            "starts": f"{raw}%",
            "warehouse": warehouse,
            "start": start,
            "page_len": page_len,
        },
    )


def _resolve_item_code(search_value: str) -> str | None:
    value = (search_value or "").strip()
    if not value:
        return None
    if frappe.db.exists("Item", value):
        return value
    if frappe.db.exists("DocType", "Item Barcode"):
        item_code = frappe.db.get_value("Item Barcode", {"barcode": value}, "parent")
        if item_code:
            return item_code
    candidates = frappe.get_all(
        "Item",
        filters={"disabled": 0, "is_purchase_item": 1},
        or_filters={
            "item_name": ["like", f"%{value}%"],
            "name": ["like", f"%{value}%"],
        },
        pluck="name",
        limit_page_length=1,
    )
    return candidates[0] if candidates else None


def _uom_conversion_factor(item_code: str, uom: str | None, stock_uom: str | None) -> float:
    if not uom or not stock_uom or uom == stock_uom:
        return 1.0
    factor = frappe.db.get_value(
        "UOM Conversion Detail", {"parent": item_code, "uom": uom}, "conversion_factor"
    )
    return flt(factor) or 1.0


def _default_item_tax_template(item_code: str, company: str | None = None) -> str | None:
    if not frappe.db.exists("DocType", "Item Tax"):
        return None
    filters: dict[str, Any] = {"parent": item_code, "parenttype": "Item"}
    rows = frappe.get_all(
        "Item Tax",
        filters=filters,
        fields=["item_tax_template", "valid_from", "tax_category"],
        order_by="valid_from desc, idx asc",
        limit_page_length=20,
    )
    today = getdate(nowdate())
    for row in rows:
        if row.valid_from and getdate(row.valid_from) > today:
            continue
        if row.item_tax_template and frappe.db.exists("Item Tax Template", row.item_tax_template):
            if company:
                template_company = frappe.db.get_value(
                    "Item Tax Template", row.item_tax_template, "company"
                )
                if template_company and template_company != company:
                    continue
            return row.item_tax_template
    return None


def _item_tax_template_rate(template_name: str | None) -> float:
    """Return a simple preview rate for an Item Tax Template.

    ERPNext remains the source of truth and recalculates the actual tax on save.
    The returned value is only used for the live page estimate.
    """
    if not template_name or not frappe.db.exists("Item Tax Template", template_name):
        return 0.0
    template = frappe.get_doc("Item Tax Template", template_name)
    rates = []
    for row in template.get("taxes") or []:
        rate = flt(row.get("tax_rate") if hasattr(row, "get") else getattr(row, "tax_rate", 0))
        if rate:
            rates.append(rate)
    return sum(rates)


def _latest_purchase_rows(item_code: str, supplier: str | None = None) -> list[dict]:
    supplier_condition = "AND pi.supplier = %(supplier)s" if supplier else ""
    rows = frappe.db.sql(
        f"""
        SELECT
            pi.name AS purchase_invoice,
            pi.posting_date,
            pi.supplier,
            pi.supplier_name,
            pii.qty,
            pii.uom,
            pii.rate,
            pii.net_rate,
            pii.net_amount,
            pii.item_tax_amount,
            pii.discount_percentage AS effective_discount,
            pii.discount_percentage,
            pii.batch_no,
            {"pii.custom_selling_price" if "custom_selling_price" in _meta_fieldnames("Purchase Invoice Item") else "0"} AS printed_retail_price,
            {"pii.custom_supplier_discount_percentage" if "custom_supplier_discount_percentage" in _meta_fieldnames("Purchase Invoice Item") else "0"} AS supplier_discount,
            {"pii.custom_additional_discount" if "custom_additional_discount" in _meta_fieldnames("Purchase Invoice Item") else "0"} AS additional_discount,
            {"pii.custom_supplier_base_price" if "custom_supplier_base_price" in _meta_fieldnames("Purchase Invoice Item") else "pii.price_list_rate"} AS supplier_base_price,
            {"pii.custom_purchase_pricing_method" if "custom_purchase_pricing_method" in _meta_fieldnames("Purchase Invoice Item") else "''"} AS pricing_method
        FROM `tabPurchase Invoice Item` pii
        INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pi.docstatus = 1
          AND pii.item_code = %(item_code)s
          {supplier_condition}
        ORDER BY pi.posting_date DESC, pi.creation DESC
        LIMIT 5
        """,
        {"item_code": item_code, "supplier": supplier},
        as_dict=True,
    )

    # The history needs the final commercial result, not the individual discount
    # components. ERPNext's net_amount is after line/invoice discounts and
    # item_tax_amount is the tax allocated to this row. Their sum therefore
    # represents the final row cost whether tax is included in the entered rate
    # or added above it.
    for row in rows:
        qty = abs(flt(row.get("qty"))) or 1.0
        final_net_rate = (flt(row.get("net_amount")) + flt(row.get("item_tax_amount"))) / qty
        printed_price = flt(row.get("printed_retail_price"))
        row["final_net_rate"] = flt(final_net_rate, 6)
        row["net_discount_after_tax"] = (
            flt((1.0 - final_net_rate / printed_price) * 100.0, 6)
            if printed_price
            else 0.0
        )

    return rows



def _days_since(value) -> int | None:
    if not value:
        return None
    return max(0, (getdate(nowdate()) - getdate(value)).days)



def _add_months(value, months: int):
    source = getdate(value)
    month_index = source.month - 1 + int(months)
    year = source.year + month_index // 12
    month = month_index % 12 + 1
    day = min(source.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _expiry_risk(expiry_date, posting_date=None) -> dict:
    if not expiry_date:
        return {"level":"None", "flags":[], "messages":[]}
    settings = get_purchase_settings()
    expiry = getdate(expiry_date)
    posting = getdate(posting_date or nowdate())
    days_remaining = (expiry - posting).days
    if days_remaining < 0:
        return {
            "level":"Critical",
            "flags":["EXPIRED_ITEM"],
            "messages":[_("Expired item: expiry date {0} is before the receipt date.").format(expiry.strftime("%d/%m/%Y"))],
            "days_remaining":days_remaining,
        }
    warning_months = max(1, cint(settings.get("near_expiry_warning_months") or 6))
    if expiry <= _add_months(posting, warning_months):
        return {
            "level":"Warning",
            "flags":["NEAR_EXPIRY"],
            "messages":[_("Near expiry: {0} — {1} days remaining.").format(expiry.strftime("%d/%m/%Y"), days_remaining)],
            "days_remaining":days_remaining,
        }
    return {"level":"None", "flags":[], "messages":[], "days_remaining":days_remaining}


def _merge_risks(*risks) -> dict:
    rank={"None":0,"Warning":1,"Critical":2}
    level="None"; flags=[]; messages=[]
    for risk in risks:
        if not risk: continue
        for flag in risk.get("flags") or []:
            if flag not in flags: flags.append(flag)
        for message in risk.get("messages") or []:
            if message not in messages: messages.append(message)
        if rank.get(risk.get("level") or "None",0) > rank.get(level,0):
            level=risk.get("level") or "None"
    if len(flags)>=2 and level=="Warning": level="Critical"
    return {"level":level,"flags":flags,"messages":messages}

def _purchase_risk_metrics(item_code: str, warehouse: str | None, incoming_stock_qty: float = 0.0) -> dict:
    settings = get_purchase_settings()
    if not cint(settings.get("enable_purchase_risk_alerts")):
        return {"level":"None", "flags":[], "messages":[]}

    analysis_days = max(1, cint(settings.get("slow_movement_analysis_days") or 30))
    recent_days = max(1, cint(settings.get("recent_purchase_warning_days") or 3))
    dormant_days = max(1, cint(settings.get("dormant_item_days") or 90))
    coverage_limit = max(1, cint(settings.get("high_stock_coverage_days") or 90))
    minimum_qty = max(0.0, flt(settings.get("minimum_stock_qty_for_warning") or 0))

    current_qty = flt(frappe.db.get_value("Bin", {"item_code":item_code, "warehouse":warehouse}, "actual_qty")) if warehouse else flt(frappe.db.sql("SELECT COALESCE(SUM(actual_qty),0) FROM `tabBin` WHERE item_code=%s", item_code)[0][0])
    wh_sales = "AND sii.warehouse = %(warehouse)s" if warehouse else ""
    sales = frappe.db.sql(f"""
        SELECT
            COALESCE(SUM(CASE WHEN si.posting_date >= DATE_SUB(CURDATE(), INTERVAL %(analysis_days)s DAY)
                THEN CASE WHEN IFNULL(si.is_return,0)=1 THEN -ABS(sii.stock_qty) ELSE ABS(sii.stock_qty) END ELSE 0 END),0) sales_qty,
            MAX(CASE WHEN IFNULL(si.is_return,0)=0 THEN si.posting_date END) last_sale_date
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name=sii.parent
        WHERE si.docstatus=1 AND sii.item_code=%(item_code)s {wh_sales}
    """, {"item_code":item_code,"warehouse":warehouse,"analysis_days":analysis_days}, as_dict=True)[0]
    wh_purchase = "AND pii.warehouse = %(warehouse)s" if warehouse else ""
    purchases = frappe.db.sql(f"""
        SELECT
            MAX(CASE WHEN IFNULL(pi.is_return,0)=0 THEN pi.posting_date END) last_purchase_date,
            COALESCE(SUM(CASE WHEN pi.posting_date >= DATE_SUB(CURDATE(), INTERVAL %(recent_days)s DAY)
                THEN CASE WHEN IFNULL(pi.is_return,0)=1 THEN -ABS(pii.stock_qty) ELSE ABS(pii.stock_qty) END ELSE 0 END),0) recent_purchase_qty
        FROM `tabPurchase Invoice Item` pii
        INNER JOIN `tabPurchase Invoice` pi ON pi.name=pii.parent
        WHERE pi.docstatus=1 AND pii.item_code=%(item_code)s {wh_purchase}
    """, {"item_code":item_code,"warehouse":warehouse,"recent_days":recent_days}, as_dict=True)[0]

    sales_qty = max(0.0, flt(sales.sales_qty))
    projected = current_qty + flt(incoming_stock_qty)
    avg_daily = sales_qty / analysis_days if analysis_days else 0.0
    coverage_days = projected / avg_daily if avg_daily > 0 else None
    last_sale_days = _days_since(sales.last_sale_date)
    last_purchase_days = _days_since(purchases.last_purchase_date)
    flags=[]; messages=[]

    if last_purchase_days is not None and last_purchase_days <= recent_days and (not sales.last_sale_date or getdate(sales.last_sale_date) < getdate(purchases.last_purchase_date)):
        flags.append("RECENT_PURCHASE_NO_SALE")
        messages.append(_("Purchased within the last {0} days with no sale after the latest purchase.").format(recent_days))
    if projected >= minimum_qty and (last_sale_days is None or last_sale_days >= dormant_days):
        flags.append("DORMANT_ITEM")
        messages.append(_("Dormant item: no sale for {0} days or no recorded sale.").format(last_sale_days if last_sale_days is not None else dormant_days))
    if projected >= minimum_qty and (avg_daily <= 0 or (coverage_days is not None and coverage_days >= coverage_limit)):
        flags.append("HIGH_STOCK_SLOW_MOVEMENT")
        messages.append(_("High projected stock with slow movement ({0} days coverage).").format(round(coverage_days,1) if coverage_days is not None else _("no sales")))

    level = "Critical" if "DORMANT_ITEM" in flags or len(flags) >= 2 else ("Warning" if flags else "None")
    return {
        "level":level, "flags":flags, "messages":messages,
        "current_qty":current_qty, "incoming_stock_qty":flt(incoming_stock_qty), "projected_qty":projected,
        "sales_analysis_days":analysis_days, "sales_qty":sales_qty, "avg_daily_sales":avg_daily,
        "coverage_days":coverage_days, "last_sale_date":sales.last_sale_date, "last_sale_days":last_sale_days,
        "last_purchase_date":purchases.last_purchase_date, "last_purchase_days":last_purchase_days,
        "recent_purchase_qty":flt(purchases.recent_purchase_qty),
    }


@frappe.whitelist()
def search_purchase_item_cards(search_text: str, warehouse: str | None = None, supplier: str | None = None, limit: int = 10):
    _require_read_access()
    limit = max(1, min(cint(limit) or 10, 30))
    raw_rows = search_purchase_items("Item", search_text or "", "name", 0, limit, {"warehouse":warehouse or ""})
    results=[]
    for raw in raw_rows:
        item_code, item_name, item_name_ar, actual_qty, stock_uom, customer_price = raw
        history = _latest_purchase_rows(item_code, supplier) if supplier else _latest_purchase_rows(item_code)
        latest = history[0] if history else None
        risk = _purchase_risk_metrics(item_code, warehouse, 0)
        results.append({
            "item_code":item_code,"item_name":item_name,"item_name_ar":item_name_ar,
            "actual_qty":flt(actual_qty),"stock_uom":stock_uom,"customer_price":flt(customer_price),
            "last_purchase_rate":flt((latest or {}).get("final_net_rate") or (latest or {}).get("rate")),
            "last_purchase_date":(latest or {}).get("posting_date"),"risk":risk,
        })
    return results


@frappe.whitelist()
def get_purchase_risk(item_code: str, warehouse: str | None = None, qty: float = 0, conversion_factor: float = 1):
    _require_read_access()
    return _purchase_risk_metrics(item_code, warehouse, flt(qty) * (flt(conversion_factor) or 1.0))

@frappe.whitelist()
def get_item_context(
    item_code: str | None = None,
    search_value: str | None = None,
    company: str | None = None,
    warehouse: str | None = None,
    supplier: str | None = None,
):
    _require_read_access()
    item_code = item_code or _resolve_item_code(search_value or "")
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Item not found."))
    if not frappe.has_permission("Item", "read", item_code):
        frappe.throw(_("You are not permitted to read this item."), frappe.PermissionError)

    item = frappe.db.get_value("Item", item_code, _item_fields(), as_dict=True) or frappe._dict()
    if cint(item.get("disabled")) or not cint(item.get("is_purchase_item", 1)):
        frappe.throw(_("Item {0} is disabled for purchasing.").format(frappe.bold(item_code)))

    purchase_uom = item.get("purchase_uom") or item.get("stock_uom")
    conversion_factor = _uom_conversion_factor(
        item_code, purchase_uom, item.get("stock_uom")
    )
    stock_qty = 0.0
    if warehouse:
        stock_qty = flt(
            frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
        )

    latest_all = _latest_purchase_rows(item_code)
    latest_supplier = _latest_purchase_rows(item_code, supplier) if supplier else []
    default_item_tax_template = _default_item_tax_template(item_code, company)
    return {
        **dict(item),
        "item_code": item_code,
        "purchase_uom": purchase_uom,
        "conversion_factor": conversion_factor,
        "actual_qty": stock_qty,
        "default_item_tax_template": default_item_tax_template,
        "default_item_tax_rate": _item_tax_template_rate(default_item_tax_template),
        "latest_purchase": latest_all[0] if latest_all else None,
        "latest_supplier_purchase": latest_supplier[0] if latest_supplier else None,
        "purchase_history": latest_all,
        "risk": _purchase_risk_metrics(item_code, warehouse, 0),
    }


def _movement_operation(voucher_type: str | None, actual_qty: float) -> str:
    voucher_type = voucher_type or ""
    if voucher_type == "Sales Invoice":
        return "Sales Return" if actual_qty > 0 else "Sale"
    if voucher_type == "Purchase Invoice":
        return "Purchase" if actual_qty > 0 else "Purchase Return"
    if voucher_type == "Purchase Receipt":
        return "Purchase Receipt" if actual_qty > 0 else "Purchase Receipt Return"
    if voucher_type == "Delivery Note":
        return "Delivery Return" if actual_qty > 0 else "Delivery"
    if voucher_type == "Stock Entry":
        return "Stock In" if actual_qty > 0 else "Stock Out"
    return "Stock In" if actual_qty > 0 else "Stock Out"


@frappe.whitelist()
def get_item_movement(
    item_code: str, warehouse: str | None = None, limit: int = 100
):
    _require_read_access()
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Select a valid item."))
    if not frappe.has_permission("Item", "read", item_code):
        frappe.throw(_("You are not permitted to read this item."), frappe.PermissionError)
    if not frappe.has_permission("Stock Ledger Entry", "read"):
        frappe.throw(_("You are not permitted to read stock movement."), frappe.PermissionError)

    item = frappe.db.get_value(
        "Item", item_code, ["item_name", "stock_uom"], as_dict=True
    ) or frappe._dict()
    filters: dict[str, Any] = {"item_code": item_code}
    if warehouse:
        filters["warehouse"] = warehouse
    sle_fields = _safe_fields(
        "Stock Ledger Entry",
        [
            "name", "posting_date", "posting_time", "creation",
            "voucher_type", "voucher_no", "warehouse", "actual_qty",
            "qty_after_transaction", "valuation_rate", "stock_value_difference",
            "batch_no", "serial_and_batch_bundle", "is_cancelled",
        ],
    )
    if "is_cancelled" in _meta_fieldnames("Stock Ledger Entry"):
        filters["is_cancelled"] = 0
    movements = frappe.get_list(
        "Stock Ledger Entry",
        filters=filters,
        fields=sle_fields,
        order_by="posting_date desc, posting_time desc, creation desc",
        limit_page_length=max(1, min(cint(limit) or 100, 300)),
    )
    rows = []
    for movement in movements:
        actual_qty = flt(movement.get("actual_qty"))
        rows.append(
            {
                **dict(movement),
                "operation": _movement_operation(movement.get("voucher_type"), actual_qty),
                "qty_in": actual_qty if actual_qty > 0 else 0,
                "qty_out": abs(actual_qty) if actual_qty < 0 else 0,
            }
        )

    if warehouse:
        current_qty = flt(
            frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
        )
    else:
        current_qty = flt(
            frappe.db.sql(
                "SELECT COALESCE(SUM(actual_qty), 0) FROM `tabBin` WHERE item_code=%s",
                item_code,
            )[0][0]
        )
    return {
        "item_code": item_code,
        "item_name": item.get("item_name") or item_code,
        "stock_uom": item.get("stock_uom") or "",
        "warehouse": warehouse or "",
        "current_qty": current_qty,
        "movements": rows,
    }


def _copy_tax_template(doc, template_name: str | None, included_in_print_rate: int = 0) -> None:
    doc.set("taxes", [])
    doc.taxes_and_charges = ""
    if not template_name:
        return
    if not frappe.db.exists("Purchase Taxes and Charges Template", template_name):
        frappe.throw(_("Purchase tax template {0} does not exist.").format(template_name))
    template = frappe.get_doc("Purchase Taxes and Charges Template", template_name)
    if template.company and template.company != doc.company:
        frappe.throw(_("The selected tax template belongs to another company."))
    doc.taxes_and_charges = template.name
    child_meta = frappe.get_meta("Purchase Taxes and Charges")
    valid_fields = {field.fieldname for field in child_meta.fields if field.fieldname}
    for source in template.get("taxes") or []:
        values = {
            key: value
            for key, value in source.as_dict().items()
            if key in valid_fields and key not in {"name", "parent", "parenttype", "parentfield", "idx"}
        }
        if "included_in_print_rate" in valid_fields and values.get("charge_type") != "Actual":
            values["included_in_print_rate"] = cint(included_in_print_rate)
        doc.append("taxes", values)



def _item_tax_accounts(template_name: str | None) -> list[dict]:
    if not template_name or not frappe.db.exists("Item Tax Template", template_name):
        return []
    template=frappe.get_doc("Item Tax Template",template_name)
    return [{"account":row.tax_type,"rate":flt(row.tax_rate)} for row in (template.get("taxes") or []) if row.tax_type]


def _ensure_item_tax_rows(doc, payload: frappe._dict) -> None:
    existing={row.account_head for row in (doc.get("taxes") or []) if row.account_head}
    for source in payload.get("items") or []:
        row=frappe._dict(source)
        if cint(row.get("is_bonus")):
            continue
        if (row.get("tax_entry_mode") or "No VAT") == "No VAT":
            continue
        accounts=_item_tax_accounts(row.get("item_tax_template"))
        if not accounts:
            frappe.throw(_("Select an Item Tax Template for taxable item {0}.").format(frappe.bold(row.get("item_code") or "")))
        for tax in accounts:
            if tax["account"] in existing: continue
            doc.append("taxes", {"charge_type":"On Net Total","account_head":tax["account"],"description":_("Item VAT"),"rate":0,"included_in_print_rate":1,"category":"Total","add_deduct_tax":"Add"})
            existing.add(tax["account"])
    for tax in doc.get("taxes") or []:
        if tax.charge_type != "Actual": tax.included_in_print_rate=1


def _apply_item_tax_overrides(doc, payload: frappe._dict) -> None:
    tax_accounts = [
        tax.account_head for tax in (doc.get("taxes") or [])
        if tax.account_head and tax.charge_type != "Actual"
    ]
    for item, source in zip(doc.get("items") or [], payload.get("items") or []):
        row=frappe._dict(source)
        calc=_calculate_row(row,1)
        rates = {account: 0.0 for account in tax_accounts}
        if cint(row.get("is_bonus")):
            item.item_tax_rate=json.dumps(rates)
            continue
        if (row.get("tax_entry_mode") or "No VAT") != "No VAT" and calc.vat_per_unit > 0:
            accounts=_item_tax_accounts(row.get("item_tax_template"))
            if len(accounts) != 1:
                frappe.throw(_("Manual or item-level VAT requires an Item Tax Template with one tax account for item {0}.").format(frappe.bold(row.get("item_code") or "")))
            effective_rate=100.0*calc.vat_per_unit/calc.net_before_vat if calc.net_before_vat else 0
            rates[accounts[0]["account"]] = effective_rate
        item.item_tax_rate=json.dumps(rates)

def _append_additional_charge(doc, account: str | None, amount: float, description: str | None) -> None:
    amount = flt(amount)
    if not amount:
        return
    if not account or not frappe.db.exists("Account", account):
        frappe.throw(_("Select a valid account for additional purchase charges."))
    account_row = frappe.db.get_value(
        "Account", account, ["company", "is_group", "root_type"], as_dict=True
    )
    if not account_row or account_row.company != doc.company or cint(account_row.is_group):
        frappe.throw(_("The additional charge account is not valid for this company."))
    doc.append(
        "taxes",
        {
            "charge_type": "Actual",
            "account_head": account,
            "description": description or _("Additional Purchase Charges"),
            "tax_amount": amount,
            "add_deduct_tax": "Add",
            "category": "Valuation and Total",
        },
    )


def _validate_header(payload: frappe._dict) -> None:
    if not payload.get("company") or not frappe.db.exists("Company", payload.get("company")):
        frappe.throw(_("Select a valid company."))
    if not payload.get("supplier") or not frappe.db.exists("Supplier", payload.get("supplier")):
        frappe.throw(_("Select a valid supplier."))
    if not payload.get("warehouse") or not frappe.db.exists("Warehouse", payload.get("warehouse")):
        frappe.throw(_("Select a valid receiving warehouse."))
    warehouse_company = frappe.db.get_value("Warehouse", payload.get("warehouse"), "company")
    if warehouse_company and warehouse_company != payload.get("company"):
        frappe.throw(_("The selected warehouse belongs to another company."))
    if not (payload.get("items") or []):
        frappe.throw(_("Add at least one purchase item."))


def _calculate_row(row: frappe._dict, tax_included: int = 1) -> dict:
    customer_price = flt(row.get("customer_price") or row.get("printed_retail_price"))
    qty = flt(row.get("qty")) or 1.0
    mode = row.get("tax_entry_mode") or "No VAT"
    vat_inclusive = cint(row.get("vat_inclusive"))
    template_rate = _item_tax_template_rate(row.get("item_tax_template"))
    vat_rate = max(0.0, flt(row.get("vat_rate")) or (template_rate if mode != "No VAT" else 0))

    if cint(row.get("is_bonus")):
        customer_base = customer_price / (1.0 + vat_rate / 100.0) if mode != "No VAT" and vat_rate else customer_price
        taxable_base = max(0.0, flt(row.get("supplier_base_price")) or customer_base)
        if mode == "VAT Per Unit":
            vat_per_unit = max(0.0, flt(row.get("vat_per_unit")))
        elif mode == "Total VAT for Line":
            vat_per_unit = max(0.0, flt(row.get("total_vat"))) / qty
        elif mode == "Auto by VAT %":
            vat_per_unit = taxable_base * vat_rate / 100.0
        else:
            vat_per_unit = 0.0
        total_vat = max(0.0, flt(row.get("total_vat"))) if mode == "Total VAT for Line" else vat_per_unit * qty
        final_rate = vat_per_unit
        effective = 100.0 * (1.0 - final_rate / customer_price) if customer_price else 100.0
        return frappe._dict(
            customer_price=customer_price,
            customer_base_before_vat=customer_base,
            supplier_base=taxable_base,
            supplier_discount=100,
            additional_discount=0,
            net_before_vat=0,
            vat_rate=vat_rate,
            vat_per_unit=vat_per_unit,
            total_vat=total_vat,
            final_rate=final_rate,
            effective_discount=effective,
            amount=qty * final_rate,
        )

    if customer_price <= 0:
        frappe.throw(_("Customer Price is required for item {0}.").format(frappe.bold(row.get("item_code") or "")))

    method = row.get("pricing_method") or "Discount From Customer Price"
    supplier_invoice_price = (
        customer_price
        if method == "Discount From Customer Price"
        else (flt(row.get("supplier_base_price")) or customer_price)
    )
    supplier_invoice_price = max(0.0, supplier_invoice_price)
    if supplier_invoice_price <= 0:
        frappe.throw(_("Supplier Invoice Price is required for item {0}.").format(frappe.bold(row.get("item_code") or "")))

    additional = max(0.0, min(100.0, flt(row.get("additional_discount"))))
    supplier_discount = max(0.0, min(100.0, flt(row.get("supplier_discount"))))
    entered_net_before_vat = 0.0
    net_before_vat = 0.0
    vat_per_unit = 0.0
    final_rate = 0.0

    if method == "Direct Final Net Rate":
        final_rate = max(0.0, flt(row.get("net_rate")))
        if final_rate <= 0:
            frappe.throw(_("Final Net Rate is required for item {0}.").format(frappe.bold(row.get("item_code") or "")))
        if mode == "VAT Per Unit":
            vat_per_unit = max(0.0, flt(row.get("vat_per_unit")))
        elif mode == "Total VAT for Line":
            vat_per_unit = max(0.0, flt(row.get("total_vat"))) / qty
        elif mode == "Auto by VAT %" and vat_rate:
            vat_per_unit = final_rate - final_rate / (1.0 + vat_rate / 100.0)
        net_before_vat = max(0.0, final_rate - vat_per_unit)

        discount_comparable = final_rate if vat_inclusive else net_before_vat
        denominator = supplier_invoice_price * max(0.000001, 1.0 - additional / 100.0)
        supplier_discount = (
            max(0.0, min(100.0, 100.0 * (1.0 - discount_comparable / denominator)))
            if denominator
            else 0.0
        )

    elif method == "Direct Net Before VAT":
        entered_net_before_vat = max(
            0.0,
            flt(row.get("entered_net_before_vat") or row.get("net_before_vat")),
        )
        if entered_net_before_vat <= 0:
            frappe.throw(_("Net Before VAT is required for item {0}.").format(frappe.bold(row.get("item_code") or "")))

        # The entered supplier net already includes the base supplier discount.
        # Apply the Additional Discount afterwards without changing the base discount.
        net_before_vat = entered_net_before_vat * (1.0 - additional / 100.0)
        if mode == "VAT Per Unit":
            vat_per_unit = max(0.0, flt(row.get("vat_per_unit")))
        elif mode == "Total VAT for Line":
            vat_per_unit = max(0.0, flt(row.get("total_vat"))) / qty
        elif mode == "Auto by VAT %":
            vat_per_unit = net_before_vat * vat_rate / 100.0
        final_rate = net_before_vat + vat_per_unit

        supplier_discount = (
            max(0.0, min(100.0, 100.0 * (1.0 - entered_net_before_vat / supplier_invoice_price)))
            if supplier_invoice_price
            else 0.0
        )

    else:
        discounted_invoice_price = (
            supplier_invoice_price
            * (1.0 - supplier_discount / 100.0)
            * (1.0 - additional / 100.0)
        )

        if mode == "No VAT":
            net_before_vat = discounted_invoice_price
            vat_per_unit = 0.0
            final_rate = discounted_invoice_price

        elif mode == "Auto by VAT %":
            if vat_inclusive:
                final_rate = discounted_invoice_price
                net_before_vat = final_rate / (1.0 + vat_rate / 100.0) if vat_rate else final_rate
                vat_per_unit = final_rate - net_before_vat
            else:
                net_before_vat = discounted_invoice_price
                vat_per_unit = net_before_vat * vat_rate / 100.0
                final_rate = net_before_vat + vat_per_unit

        else:
            if mode == "VAT Per Unit":
                vat_per_unit = max(0.0, flt(row.get("vat_per_unit")))
            elif mode == "Total VAT for Line":
                vat_per_unit = max(0.0, flt(row.get("total_vat"))) / qty

            if vat_inclusive:
                final_rate = discounted_invoice_price
                net_before_vat = max(0.0, final_rate - vat_per_unit)
            else:
                net_before_vat = discounted_invoice_price
                final_rate = net_before_vat + vat_per_unit

    total_vat = max(0.0, flt(row.get("total_vat"))) if mode == "Total VAT for Line" else vat_per_unit * qty
    effective = 100.0 * (1.0 - final_rate / customer_price) if customer_price else 0.0
    customer_base = (
        supplier_invoice_price / (1.0 + vat_rate / 100.0)
        if mode != "No VAT" and vat_rate and vat_inclusive
        else supplier_invoice_price
    )

    return frappe._dict(
        customer_price=customer_price,
        customer_base_before_vat=customer_base,
        supplier_base=supplier_invoice_price,
        supplier_discount=supplier_discount,
        additional_discount=additional,
        entered_net_before_vat=entered_net_before_vat,
        net_before_vat=net_before_vat,
        vat_rate=vat_rate,
        vat_per_unit=vat_per_unit,
        total_vat=total_vat,
        final_rate=final_rate,
        effective_discount=effective,
        amount=qty * final_rate,
    )

def _parse_flexible_date(value: Any, label: str = "Date"):
    """Accept ISO or pharmacy-friendly DD/MM/YYYY dates, including two-digit years."""
    if value in (None, ""):
        return None
    if isinstance(value, (date, datetime)):
        return getdate(value)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return getdate(raw)
    except Exception:
        pass
    normalized = raw.replace(".", "/").replace("-", "/")
    parts = normalized.split("/")
    if len(parts) == 3 and all(part.strip().isdigit() for part in parts):
        day, month, year = (int(part.strip()) for part in parts)
        if year < 100:
            year += 2000
        try:
            return getdate(f"{year:04d}-{month:02d}-{day:02d}")
        except Exception:
            pass
    frappe.throw(_("{0} must be entered as DD/MM/YYYY, for example 31/1/29.").format(label))


def _build_item_row(doc, row: frappe._dict, default_warehouse: str, tax_included: int = 1) -> dict:
    item_code = row.get("item_code")
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Invalid item in purchase rows."))
    item = frappe.db.get_value("Item", item_code, ["item_name","description","stock_uom","purchase_uom","disabled","is_purchase_item"], as_dict=True)
    if cint(item.disabled) or not cint(item.is_purchase_item):
        frappe.throw(_("Item {0} cannot be purchased.").format(frappe.bold(item_code)))
    qty=flt(row.get("qty"))
    if qty<=0: frappe.throw(_("Quantity must be greater than zero for item {0}.").format(item_code))
    uom=row.get("uom") or item.purchase_uom or item.stock_uom
    conversion_factor=flt(row.get("conversion_factor")) or _uom_conversion_factor(item_code,uom,item.stock_uom)
    calc=_calculate_row(row,1)
    is_bonus=cint(row.get("is_bonus"))
    taxable_bonus = bool(is_bonus and flt(calc.final_rate) > 0)
    standard_rate = flt(calc.final_rate)
    parsed_expiry=_parse_flexible_date(row.get("expiry_date"),_("Expiry Date"))
    movement_risk=_purchase_risk_metrics(item_code,row.get("warehouse") or default_warehouse,qty*conversion_factor)
    expiry_risk=_expiry_risk(parsed_expiry, doc.posting_date)
    if "EXPIRED_ITEM" in (expiry_risk.get("flags") or []):
        frappe.throw(_("Expired item {0} cannot be received: {1}").format(frappe.bold(item_code), " • ".join(expiry_risk.get("messages") or [])))
    risk=_merge_risks(movement_risk, expiry_risk)
    confirmed=cint(row.get("risk_confirmed"))
    values={
        "item_code":item_code,"item_name":item.item_name,"description":item.description or item.item_name,
        "qty":qty,"uom":uom,"stock_uom":item.stock_uom,"conversion_factor":conversion_factor,
        "warehouse":row.get("warehouse") or default_warehouse,
        "price_list_rate":standard_rate,"rate":standard_rate,"discount_percentage":0,"discount_amount":0,
        "is_free_item":bool(is_bonus and not taxable_bonus),"allow_zero_valuation_rate":bool(is_bonus and not taxable_bonus),
        "custom_selling_price":calc.customer_price,"custom_customer_base_before_vat":calc.customer_base_before_vat,
        "custom_supplier_base_price":calc.supplier_base,"custom_purchase_pricing_method":row.get("pricing_method") or "Discount From Customer Price",
        "custom_manual_net_rate":calc.final_rate,"custom_supplier_discount_percentage":100 if is_bonus else calc.supplier_discount,
        "custom_additional_discount":0 if is_bonus else calc.additional_discount,"custom_effective_discount_percentage":calc.effective_discount,
        "custom_tax_entry_mode":row.get("tax_entry_mode") or "No VAT","custom_vat_inclusive_in_final_rate":cint(row.get("vat_inclusive")),"custom_vat_rate":calc.vat_rate,
        "custom_entered_net_before_vat":calc.entered_net_before_vat,"custom_net_before_vat":calc.net_before_vat,"custom_vat_per_unit":calc.vat_per_unit,
        "custom_total_vat_amount":calc.total_vat,
        "custom_purchase_risk_level":risk.get("level") or "None","custom_purchase_risk_flags":"\n".join(risk.get("messages") or []),
        "custom_purchase_risk_confirmed":confirmed,"custom_purchase_risk_confirmation_reason":row.get("risk_confirmation_reason") or "",
        "custom_purchase_risk_confirmed_by":frappe.session.user if confirmed else "","custom_purchase_risk_confirmed_at":now_datetime() if confirmed else None,
        "custom_is_bonus_item":is_bonus,"custom_batch_number":(row.get("batch_no") or "").strip(),
        "custom_expiry_date":parsed_expiry,"custom_auto_batch_reason":row.get("auto_batch_reason"),
    }
    if row.get("item_tax_template") and not is_bonus:
        values["item_tax_template"]=row.get("item_tax_template")
    return values

def _currency_precision(doc) -> int:
    return cint(frappe.db.get_default("currency_precision") or 2)


def _fraction_account(company: str, settings) -> str | None:
    account = settings.get("fraction_adjustment_account")
    if account:
        return account
    return frappe.db.get_value("Company", company, "round_off_account")


def _apply_exact_supplier_total(doc, payload: frappe._dict, settings) -> float:
    if hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()

    precision = _currency_precision(doc)
    current_total = round(flt(doc.grand_total), precision)
    supplier_total = flt(payload.get("supplier_invoice_total"))

    # Supplier Invoice Total is automatic by default. This server fallback protects
    # Save Draft from a temporary client rendering race or an old browser draft.
    if not supplier_total:
        supplier_total = current_total

    if not supplier_total:
        if cint(settings.get("require_exact_supplier_invoice_total")):
            frappe.throw(_("Supplier Invoice Total is required."))
        return 0.0
    target_total = round(supplier_total, precision)
    difference = round(target_total - current_total, precision)
    max_adjustment = abs(flt(settings.get("max_fraction_adjustment") or 0))
    if abs(difference) > max_adjustment:
        frappe.throw(
            _("Supplier invoice differs from the calculated ERP total by {0}. The maximum permitted fraction adjustment is {1}.").format(
                frappe.bold(difference), frappe.bold(max_adjustment)
            )
        )
    if difference:
        account = _fraction_account(doc.company, settings)
        if not account or not frappe.db.exists("Account", account):
            frappe.throw(_("Set Purchase Fraction Adjustment Account in Pharmacy Purchase Settings or configure the company Round Off Account."))
        doc.append("taxes", {
            "charge_type": "Actual",
            "account_head": account,
            "description": _("Supplier Invoice Fraction Adjustment"),
            "tax_amount": abs(difference),
            "add_deduct_tax": "Add" if difference > 0 else "Deduct",
            "category": "Total",
        })
        if hasattr(doc, "calculate_taxes_and_totals"):
            doc.calculate_taxes_and_totals()
    final_total = round(flt(doc.grand_total), precision)
    if final_total != target_total:
        frappe.throw(_("Unable to match the supplier invoice total exactly. ERP total is {0}, supplier total is {1}.").format(final_total, target_total))
    if doc.meta.has_field("custom_supplier_invoice_total"):
        doc.custom_supplier_invoice_total = target_total
    if doc.meta.has_field("custom_fraction_adjustment"):
        doc.custom_fraction_adjustment = difference
    if doc.meta.has_field("custom_fraction_adjustment_account"):
        doc.custom_fraction_adjustment_account = _fraction_account(doc.company, settings) if difference else ""
    if doc.meta.has_field("custom_claim_match_status"):
        doc.custom_claim_match_status = "Matched"
    return difference


def _attach_file(file_url: str | None, invoice_name: str) -> None:
    if not file_url:
        return
    file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        return
    file_doc = frappe.get_doc("File", file_name)
    if not file_doc.attached_to_doctype and not file_doc.attached_to_name:
        file_doc.db_set(
            {
                "attached_to_doctype": "Purchase Invoice",
                "attached_to_name": invoice_name,
                "attached_to_field": "custom_supplier_invoice_attachment",
            },
            update_modified=False,
        )


def _invoice_response(doc) -> dict:
    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "status": doc.status,
        "supplier": doc.supplier,
        "supplier_name": doc.supplier_name,
        "bill_no": doc.bill_no,
        "posting_date": doc.posting_date,
        "net_total": flt(doc.net_total),
        "total_taxes_and_charges": flt(doc.total_taxes_and_charges),
        "taxes": [
            {
                "description": row.description,
                "account_head": row.account_head,
                "rate": flt(row.rate),
                "tax_amount": flt(row.tax_amount),
                "included_in_print_rate": cint(row.included_in_print_rate),
                "total": flt(row.total),
            }
            for row in (doc.get("taxes") or [])
        ],
        "discount_amount": flt(doc.discount_amount),
        "grand_total": flt(doc.grand_total),
        "outstanding_amount": flt(doc.outstanding_amount),
        "currency": doc.currency,
        "items_count": len(doc.items or []),
        "items": [
            {
                "idx": row.idx,
                "item_code": row.item_code,
                "batch_no": row.get("batch_no") or row.get("custom_batch_number") or "",
                "serial_and_batch_bundle": row.get("serial_and_batch_bundle") or "",
                "expiry_date": row.get("custom_expiry_date"),
                "auto_batch_generated": cint(row.get("custom_auto_batch_generated")),
            }
            for row in (doc.get("items") or [])
        ],
        "supplier_invoice_total": flt(doc.get("custom_supplier_invoice_total")),
        "fraction_adjustment": flt(doc.get("custom_fraction_adjustment")),
        "claim_match_status": doc.get("custom_claim_match_status") or "",
        "expected_claim_period_from": doc.get("custom_expected_claim_period_from"),
        "expected_claim_period_to": doc.get("custom_expected_claim_period_to"),
        "route": f"/app/purchase-invoice/{doc.name}",
    }



def _purchase_page_additional_charge(doc) -> dict:
    for tax in doc.get("taxes") or []:
        if tax.charge_type != "Actual":
            continue
        if (tax.description or "") == _("Supplier Invoice Fraction Adjustment"):
            continue
        if (tax.description or "") == "Supplier Invoice Fraction Adjustment":
            continue
        return {
            "account": tax.account_head or "",
            "amount": flt(tax.tax_amount),
            "description": tax.description or "",
        }
    return {"account": "", "amount": 0.0, "description": ""}


def _purchase_page_item_row(doc, row) -> dict:
    item = frappe.db.get_value(
        "Item",
        row.item_code,
        _safe_fields(
            "Item",
            [
                "item_name", "stock_uom", "has_batch_no", "has_expiry_date",
                "custom_customer_price",
            ],
        ),
        as_dict=True,
    ) or frappe._dict()
    conversion_factor = flt(row.conversion_factor) or 1.0
    warehouse = row.warehouse or doc.set_warehouse
    movement_risk = _purchase_risk_metrics(
        row.item_code,
        warehouse,
        flt(row.qty) * conversion_factor,
    )
    expiry_risk = _expiry_risk(row.get("custom_expiry_date"), doc.posting_date)
    merged_risk = _merge_risks(movement_risk, expiry_risk)
    customer_price = flt(row.get("custom_selling_price"))
    supplier_price = flt(row.get("custom_supplier_base_price")) or flt(row.price_list_rate) or customer_price
    net_rate = flt(row.get("custom_manual_net_rate")) or flt(row.rate)
    net_before_vat = flt(row.get("custom_net_before_vat"))
    entered_net_before_vat = flt(row.get("custom_entered_net_before_vat"))
    vat_per_unit = flt(row.get("custom_vat_per_unit"))
    total_vat = flt(row.get("custom_total_vat_amount"))

    return {
        "row_id": row.name or f"loaded-{row.idx}",
        "item_code": row.item_code,
        "item_name": row.item_name or item.get("item_name") or row.item_code,
        "qty": flt(row.qty),
        "uom": row.uom or item.get("stock_uom"),
        "conversion_factor": conversion_factor,
        "customer_price": customer_price,
        "printed_retail_price": customer_price,
        "customer_base_before_vat": flt(row.get("custom_customer_base_before_vat")),
        "supplier_base_price": supplier_price,
        "pricing_method": row.get("custom_purchase_pricing_method") or "Discount From Customer Price",
        "entered_net_before_vat": entered_net_before_vat,
        "supplier_discount": flt(row.get("custom_supplier_discount_percentage")),
        "additional_discount": flt(row.get("custom_additional_discount")),
        "effective_discount": flt(row.get("custom_effective_discount_percentage")),
        "tax_entry_mode": row.get("custom_tax_entry_mode") or "No VAT",
        "vat_inclusive": cint(row.get("custom_vat_inclusive_in_final_rate")),
        "vat_rate": flt(row.get("custom_vat_rate")),
        "net_before_vat": net_before_vat,
        "vat_per_unit": vat_per_unit,
        "total_vat": total_vat,
        "net_rate": net_rate,
        "amount": flt(row.amount),
        "batch_no": row.get("custom_batch_number") or row.get("batch_no") or "",
        "expiry_date": row.get("custom_expiry_date"),
        "item_tax_template": row.item_tax_template or "",
        "item_tax_rate": flt(row.get("custom_vat_rate")),
        "is_bonus": cint(row.get("custom_is_bonus_item")),
        "auto_batch_reason": row.get("custom_auto_batch_reason") or "",
        "has_batch_no": cint(item.get("has_batch_no")),
        "has_expiry_date": cint(item.get("has_expiry_date")),
        "current_customer_price": flt(item.get("custom_customer_price")),
        "risk_level": merged_risk.get("level") or "None",
        "risk_flags": merged_risk.get("flags") or [],
        "risk_messages": merged_risk.get("messages") or [],
        "risk_confirmed": cint(row.get("custom_purchase_risk_confirmed")),
        "risk_confirmation_reason": row.get("custom_purchase_risk_confirmation_reason") or "",
        "risk_metrics": movement_risk,
    }


def _purchase_invoice_page_payload(doc) -> dict:
    charge = _purchase_page_additional_charge(doc)
    supplier_total = flt(doc.get("custom_supplier_invoice_total")) or flt(doc.grand_total)
    fraction_adjustment = flt(doc.get("custom_fraction_adjustment"))
    tax_included = 1
    non_actual_taxes = [tax for tax in (doc.get("taxes") or []) if tax.charge_type != "Actual"]
    if non_actual_taxes:
        tax_included = 1 if any(cint(tax.included_in_print_rate) for tax in non_actual_taxes) else 0

    return {
        "name": doc.name,
        "company": doc.company,
        "supplier": doc.supplier,
        "warehouse": doc.set_warehouse or next((row.warehouse for row in (doc.items or []) if row.warehouse), ""),
        "payment_classification": doc.get("custom_payment_classification") or "",
        "posting_date": doc.posting_date,
        "bill_no": doc.bill_no or "",
        "bill_date": doc.bill_date or doc.posting_date,
        "due_date": doc.due_date or doc.posting_date,
        "taxes_and_charges": doc.taxes_and_charges or "",
        "tax_included_in_print_rate": tax_included,
        "invoice_discount_percentage": flt(doc.additional_discount_percentage),
        "additional_charge_account": charge.get("account") or "",
        "additional_charge_amount": flt(charge.get("amount")),
        "additional_charge_description": charge.get("description") or "",
        "supplier_invoice_total": supplier_total,
        "supplier_invoice_total_manual": 1 if abs(fraction_adjustment) > 0.000001 else 0,
        "fraction_adjustment": fraction_adjustment,
        "attachment": doc.get("custom_supplier_invoice_attachment") or "",
        "remarks": doc.remarks or "",
        "buying_price_list": doc.buying_price_list or _default_buying_price_list(),
        "items": [_purchase_page_item_row(doc, row) for row in (doc.items or [])],
    }


@frappe.whitelist()
def load_invoice(name: str):
    _require_read_access()
    if not name or not frappe.db.exists("Purchase Invoice", name):
        frappe.throw(_("Purchase Invoice was not found."))
    doc = frappe.get_doc("Purchase Invoice", name)
    doc.check_permission("read")
    if doc.docstatus != 0:
        frappe.throw(_("Only Draft Purchase Invoices can be opened for editing on this page."))
    return {
        "invoice": _invoice_response(doc),
        "payload": _purchase_invoice_page_payload(doc),
    }


def _validate_near_expiry_confirmation_before_save(payload: frappe._dict, settings) -> None:
    if not cint(settings.get("enable_purchase_risk_alerts")) or not cint(settings.get("require_risk_confirmation")):
        return

    posting_date = payload.get("posting_date") or nowdate()
    for index, source in enumerate(payload.get("items") or [], start=1):
        row = frappe._dict(source)
        expiry_risk = _expiry_risk(row.get("expiry_date"), posting_date)
        flags = expiry_risk.get("flags") or []

        if "EXPIRED_ITEM" in flags:
            frappe.throw(
                _("Expired item on row {0} cannot be saved: {1}").format(
                    index,
                    " • ".join(expiry_risk.get("messages") or []),
                )
            )

        if "NEAR_EXPIRY" not in flags:
            continue

        confirmed = cint(row.get("risk_confirmed"))
        reason = (row.get("risk_confirmation_reason") or "").strip()
        if not confirmed or not reason:
            frappe.throw(
                _("Confirm the near-expiry item and select a reason on row {0}: {1}").format(
                    index,
                    " • ".join(expiry_risk.get("messages") or []),
                )
            )


@frappe.whitelist()
def save_draft(payload):
    _require_create_access()
    payload = _parse_payload(payload)
    _validate_header(payload)
    settings = get_purchase_settings()
    _validate_near_expiry_confirmation_before_save(payload, settings)

    invoice_name = (payload.get("name") or "").strip()
    bill_no = (payload.get("bill_no") or "").strip()
    if bill_no:
        duplicate_filters = {
            "supplier": payload.get("supplier"),
            "bill_no": bill_no,
            "docstatus": ["<", 2],
        }
        if invoice_name:
            duplicate_filters["name"] = ["!=", invoice_name]
        duplicate = frappe.db.exists("Purchase Invoice", duplicate_filters)
        if duplicate:
            frappe.throw(
                _("Supplier Invoice Number {0} already exists in {1}.").format(
                    frappe.bold(bill_no),
                    frappe.get_desk_link("Purchase Invoice", duplicate),
                )
            )

    if invoice_name:
        doc = frappe.get_doc("Purchase Invoice", invoice_name)
        doc.check_permission("write")
        if doc.docstatus != 0:
            frappe.throw(_("Only Draft Purchase Invoices can be edited from this page."))
    else:
        doc = frappe.new_doc("Purchase Invoice")

    doc.company = payload.get("company")
    doc.supplier = payload.get("supplier")
    doc.posting_date = payload.get("posting_date") or nowdate()
    doc.set_posting_time = 1
    doc.bill_no = bill_no
    doc.bill_date = payload.get("bill_date") or doc.posting_date
    claim_period = _claim_period_for_date(doc.supplier, doc.bill_date)
    if doc.meta.has_field("custom_claim_basis_date"):
        doc.custom_claim_basis_date = claim_period.get("basis_date") or doc.bill_date
    if doc.meta.has_field("custom_expected_claim_period_from"):
        doc.custom_expected_claim_period_from = claim_period.get("period_from")
    if doc.meta.has_field("custom_expected_claim_period_to"):
        doc.custom_expected_claim_period_to = claim_period.get("period_to")
    doc.due_date = payload.get("due_date") or doc.posting_date
    doc.update_stock = 1
    doc.set_warehouse = payload.get("warehouse")
    doc.buying_price_list = payload.get("buying_price_list") or _default_buying_price_list()

    if doc.meta.has_field("custom_purchase_entry_mode"):
        doc.custom_purchase_entry_mode = "Quick Invoice & Receipt"
    if doc.meta.has_field("custom_payment_classification"):
        doc.custom_payment_classification = payload.get("payment_classification") or ""
    if doc.meta.has_field("custom_exclude_from_supplier_claim"):
        doc.custom_exclude_from_supplier_claim = cint(payload.get("exclude_from_claim"))
    if doc.meta.has_field("custom_supplier_invoice_attachment"):
        doc.custom_supplier_invoice_attachment = payload.get("attachment") or ""

    doc.remarks = payload.get("remarks") or ""
    doc.set("items", [])
    for source in payload.get("items") or []:
        row = frappe._dict(source)
        doc.append("items", _build_item_row(doc, row, payload.get("warehouse"), 1))

    if hasattr(doc, "set_missing_values"):
        doc.set_missing_values()

    _copy_tax_template(doc, payload.get("taxes_and_charges"), 1)
    _ensure_item_tax_rows(doc, payload)
    _apply_item_tax_overrides(doc, payload)
    _append_additional_charge(
        doc,
        payload.get("additional_charge_account"),
        flt(payload.get("additional_charge_amount")),
        payload.get("additional_charge_description"),
    )

    invoice_discount = max(0.0, min(100.0, flt(payload.get("invoice_discount_percentage"))))
    doc.apply_discount_on = "Net Total"
    doc.additional_discount_percentage = invoice_discount
    _apply_exact_supplier_total(doc, payload, settings)

    if invoice_name:
        doc.save()
    else:
        doc.insert()

    _attach_file(payload.get("attachment"), doc.name)
    doc.reload()
    return {
        "invoice": _invoice_response(doc),
        "recent_invoices": _recent_invoices(doc.company),
    }



def _validate_purchase_risk_before_submit(doc) -> None:
    settings=get_purchase_settings()
    if not cint(settings.get("enable_purchase_risk_alerts")) or not cint(settings.get("require_risk_confirmation")):
        return
    role=(settings.get("critical_risk_approval_role") or "").strip()
    for row in doc.get("items") or []:
        expiry_risk=_expiry_risk(row.get("custom_expiry_date"), doc.posting_date)
        if "EXPIRED_ITEM" in (expiry_risk.get("flags") or []):
            frappe.throw(_("Expired item {0} cannot be submitted: {1}").format(frappe.bold(row.item_code), " • ".join(expiry_risk.get("messages") or [])))
        stored={"level":row.get("custom_purchase_risk_level") or "None","flags":[],"messages":(row.get("custom_purchase_risk_flags") or "").splitlines()}
        merged=_merge_risks(stored, expiry_risk)
        level=merged.get("level") or "None"
        if level not in ("Warning","Critical"): continue
        if not cint(row.get("custom_purchase_risk_confirmed")) or not (row.get("custom_purchase_risk_confirmation_reason") or "").strip():
            frappe.throw(_("Confirm the purchase risk and reason for item {0} before submitting.").format(frappe.bold(row.item_code)))
        if level=="Critical" and role:
            confirmer=row.get("custom_purchase_risk_confirmed_by") or frappe.session.user
            if role not in frappe.get_roles(confirmer):
                frappe.throw(_("Critical-risk item {0} must be confirmed by a user with role {1}.").format(frappe.bold(row.item_code),frappe.bold(role)))

def validate_purchase_invoice_risk_before_submit(doc, method=None):
    """Enforce purchase-risk confirmation even from the standard ERPNext form."""
    _validate_purchase_risk_before_submit(doc)


@frappe.whitelist()
def submit_invoice(name: str):
    _require_create_access()
    doc = frappe.get_doc("Purchase Invoice", name)
    doc.check_permission("submit")
    if doc.docstatus != 0:
        frappe.throw(_("Only a Draft Purchase Invoice can be submitted."))
    _validate_purchase_risk_before_submit(doc)
    doc.submit()
    doc.reload()
    return {"invoice": _invoice_response(doc), "recent_invoices": _recent_invoices(doc.company)}


@frappe.whitelist()
def cancel_invoice(name: str):
    _require_create_access()
    doc = frappe.get_doc("Purchase Invoice", name)
    doc.check_permission("cancel")
    if doc.docstatus != 1:
        frappe.throw(_("Only a Submitted Purchase Invoice can be cancelled."))
    doc.cancel()
    doc.reload()
    return {"invoice": _invoice_response(doc), "recent_invoices": _recent_invoices(doc.company)}
