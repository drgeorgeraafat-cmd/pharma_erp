"""Server API for the Purchase & Invoice Management desk page.

The page is an operational interface only. Purchase Invoice remains the official
stock and accounting document in ERPNext.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

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
    elif payment_model in ("Credit Claim", "Mixed") or supplier_type == "Distribution Company":
        classification = "Claim Invoice"
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
            {"pii.custom_additional_discount" if "custom_additional_discount" in _meta_fieldnames("Purchase Invoice Item") else "0"} AS additional_discount
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


def _calculate_row(row: frappe._dict) -> tuple[float, float, float]:
    printed_price = flt(row.get("printed_retail_price"))
    supplier_discount = max(0.0, min(100.0, flt(row.get("supplier_discount"))))
    additional_discount = max(0.0, min(100.0, flt(row.get("additional_discount"))))
    if cint(row.get("is_bonus")):
        return 100.0, 0.0, printed_price
    if printed_price <= 0:
        frappe.throw(
            _("Printed Retail Price is required for item {0}.").format(
                frappe.bold(row.get("item_code") or "")
            )
        )
    effective = 100.0 * (
        1.0
        - (1.0 - supplier_discount / 100.0)
        * (1.0 - additional_discount / 100.0)
    )
    rate = printed_price * (1.0 - effective / 100.0)
    return effective, rate, printed_price - rate


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


def _build_item_row(doc, row: frappe._dict, default_warehouse: str) -> dict:
    item_code = row.get("item_code")
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Invalid item in purchase rows."))
    item = frappe.db.get_value(
        "Item",
        item_code,
        ["item_name", "description", "stock_uom", "purchase_uom", "disabled", "is_purchase_item"],
        as_dict=True,
    )
    if cint(item.disabled) or not cint(item.is_purchase_item):
        frappe.throw(_("Item {0} cannot be purchased.").format(frappe.bold(item_code)))

    qty = flt(row.get("qty"))
    if qty <= 0:
        frappe.throw(_("Quantity must be greater than zero for item {0}.").format(item_code))
    uom = row.get("uom") or item.purchase_uom or item.stock_uom
    conversion_factor = flt(row.get("conversion_factor")) or _uom_conversion_factor(
        item_code, uom, item.stock_uom
    )
    effective, rate, discount_amount = _calculate_row(row)
    printed_price = flt(row.get("printed_retail_price"))
    is_bonus = cint(row.get("is_bonus"))

    values = {
        "item_code": item_code,
        "item_name": item.item_name,
        "description": item.description or item.item_name,
        "qty": qty,
        "uom": uom,
        "stock_uom": item.stock_uom,
        "conversion_factor": conversion_factor,
        "warehouse": row.get("warehouse") or default_warehouse,
        "price_list_rate": printed_price,
        "rate": rate,
        "discount_percentage": effective,
        "discount_amount": discount_amount,
        "is_free_item": is_bonus,
        "allow_zero_valuation_rate": is_bonus,
        "custom_selling_price": printed_price,
        "custom_supplier_discount_percentage": 0 if is_bonus else flt(row.get("supplier_discount")),
        "custom_additional_discount": 0 if is_bonus else flt(row.get("additional_discount")),
        "custom_effective_discount_percentage": effective,
        "custom_is_bonus_item": is_bonus,
        "custom_batch_number": (row.get("batch_no") or "").strip(),
        "custom_expiry_date": _parse_flexible_date(row.get("expiry_date"), _("Expiry Date")),
        "custom_auto_batch_reason": row.get("auto_batch_reason"),
    }
    if row.get("item_tax_template"):
        values["item_tax_template"] = row.get("item_tax_template")
    return values


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
        "route": f"/app/purchase-invoice/{doc.name}",
    }


@frappe.whitelist()
def save_draft(payload):
    _require_create_access()
    payload = _parse_payload(payload)
    _validate_header(payload)

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
        doc.append("items", _build_item_row(doc, row, payload.get("warehouse")))

    if hasattr(doc, "set_missing_values"):
        doc.set_missing_values()

    _copy_tax_template(
        doc,
        payload.get("taxes_and_charges"),
        cint(payload.get("tax_included_in_print_rate")),
    )
    _append_additional_charge(
        doc,
        payload.get("additional_charge_account"),
        flt(payload.get("additional_charge_amount")),
        payload.get("additional_charge_description"),
    )

    invoice_discount = max(0.0, min(100.0, flt(payload.get("invoice_discount_percentage"))))
    doc.apply_discount_on = "Net Total"
    doc.additional_discount_percentage = invoice_discount

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
