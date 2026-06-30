"""Operational API for Purchase Returns Management."""
from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

READ_ROLES = {
    "Purchase User", "Purchase Manager", "Accounts User", "Accounts Manager",
    "Stock User", "Stock Manager", "System Manager",
}
SPECIAL_WAREHOUSE_NAMES = {
    "recall": "Recall Quarantine",
    "expired": "Expired Drugs",
    "supplier": "Returns With Supplier",
}


def _require_read() -> None:
    if not READ_ROLES.intersection(set(frappe.get_roles())):
        frappe.throw(_("You are not permitted to access Purchase Returns Management."), frappe.PermissionError)
    if not frappe.has_permission("Purchase Invoice", "read"):
        frappe.throw(_("You are not permitted to read Purchase Invoices."), frappe.PermissionError)


def _require_create() -> None:
    _require_read()
    if not frappe.has_permission("Pharmacy Return Case", "create"):
        frappe.throw(_("You are not permitted to create Pharmacy Return Cases."), frappe.PermissionError)


def _parse(payload: Any) -> dict:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            frappe.throw(_("Invalid return payload."))
    if not isinstance(payload, dict):
        frappe.throw(_("Invalid return payload."))
    return dict(payload)


def _default_company() -> str | None:
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.defaults.get_global_default("company")
        or frappe.db.get_value("Company", {}, "name", order_by="is_group asc, creation asc")
    )


def _default_warehouse(company: str | None) -> str | None:
    warehouse = frappe.defaults.get_user_default("Warehouse")
    if not warehouse and frappe.db.exists("DocType", "Pharmacy POS Settings"):
        warehouse = frappe.db.get_single_value("Pharmacy POS Settings", "default_warehouse")
    if warehouse and frappe.db.exists("Warehouse", warehouse):
        row = frappe.db.get_value("Warehouse", warehouse, ["company", "is_group", "disabled"], as_dict=True)
        if row and not row.is_group and not row.disabled and (not company or row.company == company):
            return warehouse
    if not company:
        return None
    special = set(filter(None, _special_warehouses(company).values()))
    rows = frappe.get_all(
        "Warehouse",
        filters={"company": company, "is_group": 0, "disabled": 0},
        fields=["name"],
        order_by="creation asc",
        limit_page_length=200,
    )
    for row in rows:
        if row.name not in special:
            return row.name
    return None


def _special_warehouses(company: str | None) -> dict[str, str | None]:
    if not company:
        return {key: None for key in SPECIAL_WAREHOUSE_NAMES}
    result = {}
    for key, warehouse_name in SPECIAL_WAREHOUSE_NAMES.items():
        result[key] = frappe.db.get_value(
            "Warehouse",
            {"company": company, "warehouse_name": warehouse_name, "is_group": 0},
            "name",
        )
    return result


def _sync_case_operational_status(doc) -> None:
    if doc.return_type != "Regulatory Batch Recall" or not doc.quarantine_stock_entry:
        return
    docstatus = frappe.db.get_value("Stock Entry", doc.quarantine_stock_entry, "docstatus")
    desired = None
    if docstatus == 1:
        desired = "Quarantined"
    elif docstatus == 0:
        desired = "Quarantine Transfer Draft Created"
    elif docstatus == 2:
        desired = "Under Review"
    if desired and doc.operational_status != desired:
        doc.db_set("operational_status", desired, update_modified=False)
        doc.operational_status = desired


def _recent_cases(company: str | None, limit: int = 20) -> list[dict]:
    filters = {"company": company} if company else {}
    rows = frappe.get_list(
        "Pharmacy Return Case",
        filters=filters,
        fields=[
            "name", "posting_date", "return_type", "supplier", "original_purchase_invoice",
            "purchase_return", "quarantine_stock_entry", "operational_status",
            "requested_return_value", "approved_return_value", "settlement_method", "modified",
        ],
        order_by="modified desc",
        limit_page_length=max(1, min(cint(limit) or 20, 100)),
    )
    for row in rows:
        if row.return_type == "Regulatory Batch Recall" and row.quarantine_stock_entry:
            docstatus = frappe.db.get_value("Stock Entry", row.quarantine_stock_entry, "docstatus")
            row.operational_status = (
                "Quarantined" if docstatus == 1
                else "Quarantine Transfer Draft Created" if docstatus == 0
                else "Under Review" if docstatus == 2
                else row.operational_status
            )
    return rows


@frappe.whitelist()
def get_bootstrap(company: str | None = None, purchase_invoice: str | None = None):
    _require_read()
    company = company or _default_company()
    result = {
        "company": company,
        "posting_date": nowdate(),
        "default_warehouse": _default_warehouse(company),
        "recent_cases": _recent_cases(company),
        "special_warehouses": _special_warehouses(company),
        "can_create_case": bool(frappe.has_permission("Pharmacy Return Case", "create")),
        "can_create_purchase_invoice": bool(frappe.has_permission("Purchase Invoice", "create")),
        "can_create_stock_entry": bool(frappe.has_permission("Stock Entry", "create")),
    }
    if purchase_invoice:
        result["invoice"] = get_invoice_for_return(purchase_invoice)
    return result


def _returned_qty_by_original_item(invoice_name: str) -> dict[str, float]:
    rows = frappe.db.sql(
        """
        select pii.purchase_invoice_item, sum(abs(pii.qty)) as returned_qty
        from `tabPurchase Invoice Item` pii
        inner join `tabPurchase Invoice` pi on pi.name = pii.parent
        where pi.return_against = %s
          and pi.is_return = 1
          and pi.docstatus < 2
          and ifnull(pii.purchase_invoice_item, '') != ''
        group by pii.purchase_invoice_item
        """,
        invoice_name,
        as_dict=True,
    )
    return {row.purchase_invoice_item: flt(row.returned_qty) for row in rows}


@frappe.whitelist()
def get_invoice_for_return(name: str):
    _require_read()
    if not name or not frappe.db.exists("Purchase Invoice", name):
        frappe.throw(_("Purchase Invoice does not exist."))
    doc = frappe.get_doc("Purchase Invoice", name)
    if doc.docstatus != 1:
        frappe.throw(_("Only submitted Purchase Invoices can be returned."))
    if cint(doc.is_return):
        frappe.throw(_("A return document cannot be used as the original invoice."))

    returned = _returned_qty_by_original_item(doc.name)
    item_meta = frappe.get_meta("Purchase Invoice Item")
    item_fields = {df.fieldname for df in item_meta.fields if df.fieldname}
    result_items = []
    for row in doc.items:
        original_qty = abs(flt(row.qty))
        already = flt(returned.get(row.name))
        available = max(0.0, original_qty - already)
        batch_no = ""
        if "batch_no" in item_fields:
            batch_no = row.get("batch_no") or ""
        if not batch_no and "custom_batch_number" in item_fields:
            batch_no = row.get("custom_batch_number") or ""
        expiry_date = row.get("custom_expiry_date") if "custom_expiry_date" in item_fields else None
        result_items.append({
            "original_purchase_invoice_item": row.name,
            "item_code": row.item_code,
            "item_name": row.item_name,
            "description": row.description,
            "warehouse": row.warehouse,
            "batch_no": batch_no,
            "expiry_date": expiry_date,
            "stock_uom": row.stock_uom or row.uom,
            "original_qty": original_qty,
            "already_returned_qty": already,
            "available_to_return_qty": available,
            "return_qty": 0,
            "rate": abs(flt(row.rate)),
            "tax_amount": abs(flt(row.get("item_tax_amount"))),
            "return_amount": 0,
            "return_reason": "Normal Return",
            "notes": "",
        })

    return {
        "name": doc.name,
        "company": doc.company,
        "supplier": doc.supplier,
        "supplier_name": doc.supplier_name,
        "posting_date": doc.posting_date,
        "bill_no": doc.bill_no,
        "currency": doc.currency,
        "grand_total": doc.grand_total,
        "update_stock": cint(doc.update_stock),
        "items": result_items,
    }


def _latest_purchase_rate(item_code: str, batch_no: str, company: str) -> float:
    meta = frappe.get_meta("Purchase Invoice Item")
    fields = {df.fieldname for df in meta.fields if df.fieldname}
    batch_field = "batch_no" if "batch_no" in fields else "custom_batch_number" if "custom_batch_number" in fields else None
    batch_condition = ""
    values: list[Any] = [company, item_code]
    if batch_field and batch_no:
        batch_condition = f" and pii.`{batch_field}` = %s"
        values.append(batch_no)
    row = frappe.db.sql(
        f"""
        select abs(ifnull(pii.net_rate, pii.rate)) as rate
        from `tabPurchase Invoice Item` pii
        inner join `tabPurchase Invoice` pi on pi.name = pii.parent
        where pi.docstatus = 1 and ifnull(pi.is_return, 0) = 0
          and pi.company = %s and pii.item_code = %s
          {batch_condition}
        order by pi.posting_date desc, pi.posting_time desc, pi.creation desc
        limit 1
        """,
        values,
        as_dict=True,
    )
    return flt(row[0].rate) if row else 0.0


def _stock_valuation_rate(item_code: str, warehouse: str, batch_no: str | None = None) -> float:
    filters = {
        "item_code": item_code,
        "warehouse": warehouse,
        "is_cancelled": 0,
    }
    if batch_no:
        filters["batch_no"] = batch_no
    rows = frappe.get_all(
        "Stock Ledger Entry",
        filters=filters,
        fields=["valuation_rate"],
        order_by="posting_date desc, posting_time desc, creation desc",
        limit_page_length=1,
    )
    rate = rows[0].valuation_rate if rows else None
    if rate is None:
        rate = frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            "valuation_rate",
        )
    return flt(rate)



def _recall_search_pattern(txt: str | None) -> tuple[str, str, str]:
    """Use the tolerant Pharmacy POS / Sales search behaviour."""
    raw = (txt or "").strip()
    tokens = [token for token in re.split(r"[\s*%]+", raw) if token]
    like_pattern = "%" + "%".join(tokens) + "%" if tokens else "%"
    compact = re.sub(r"[\s*%_-]+", "", raw).lower()
    return raw, like_pattern, compact


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_recall_items(doctype, txt, searchfield, start, page_len, filters):
    """Search recalled items using the pharmacy-wide item search behaviour.

    Supports item code, English/Arabic name, aliases, keywords, barcode,
    spaces, percent signs and asterisks. Only batch-controlled items with
    positive stock in the selected source warehouse are returned.
    """
    _require_read()
    raw, like_txt, compact_txt = _recall_search_pattern(txt)
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    warehouse = (filters.get("warehouse") or "").strip()
    company = (filters.get("company") or "").strip()
    if not warehouse or not frappe.db.exists("Warehouse", warehouse):
        return []

    wh = frappe.db.get_value(
        "Warehouse", warehouse, ["company", "is_group", "disabled"], as_dict=True
    )
    if not wh or wh.is_group or wh.disabled or (company and wh.company != company):
        return []

    item_meta = frappe.get_meta("Item")
    arabic_field = (
        "custom_item_name_ar"
        if item_meta.has_field("custom_item_name_ar")
        else None
    )
    keywords_field = None
    for candidate in ("custom_search_keywords", "custom_search_keywords__aliases"):
        if item_meta.has_field(candidate):
            keywords_field = candidate
            break

    arabic_sql = f"i.`{arabic_field}`" if arabic_field else "''"
    keywords_sql = f"i.`{keywords_field}`" if keywords_field else "''"
    start = max(cint(start), 0)
    page_len = max(1, min(cint(page_len) or 20, 100))

    return frappe.db.sql(
        f"""
        SELECT
            i.name,
            i.item_name,
            {arabic_sql} AS item_name_ar,
            SUM(bin.actual_qty) AS actual_qty,
            i.stock_uom
        FROM `tabItem` i
        INNER JOIN `tabBin` bin
            ON bin.item_code = i.name
           AND bin.warehouse = %(warehouse)s
           AND bin.actual_qty > 0
        LEFT JOIN `tabItem Barcode` ib ON ib.parent = i.name
        WHERE IFNULL(i.disabled, 0) = 0
          AND IFNULL(i.has_batch_no, 0) = 1
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
        GROUP BY i.name, i.item_name, {arabic_sql}, i.stock_uom
        HAVING SUM(bin.actual_qty) > 0
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


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def search_recall_batches(doctype, txt, searchfield, start, page_len, filters):
    """Return only batches with positive stock for the selected item/warehouse."""
    _require_read()
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    item_code = (filters.get("item_code") or "").strip()
    warehouse = (filters.get("warehouse") or "").strip()
    company = (filters.get("company") or "").strip()
    if not item_code or not warehouse:
        return []
    if not frappe.db.exists("Item", item_code):
        return []

    wh = frappe.db.get_value(
        "Warehouse", warehouse, ["company", "is_group", "disabled"], as_dict=True
    )
    if not wh or wh.is_group or wh.disabled or (company and wh.company != company):
        return []

    raw = (txt or "").strip()
    like_txt = f"%{raw}%"
    candidates = frappe.db.sql(
        """
        SELECT name, expiry_date
        FROM `tabBatch`
        WHERE item = %(item_code)s
          AND IFNULL(disabled, 0) = 0
          AND (
              name LIKE %(like_txt)s
              OR IFNULL(CAST(expiry_date AS CHAR), '') LIKE %(like_txt)s
          )
        ORDER BY
            CASE WHEN name = %(raw)s THEN 0 ELSE 1 END,
            CASE WHEN name LIKE %(starts)s THEN 0 ELSE 1 END,
            expiry_date ASC,
            name ASC
        LIMIT 300
        """,
        {
            "item_code": item_code,
            "raw": raw,
            "starts": f"{raw}%",
            "like_txt": like_txt,
        },
        as_dict=True,
    )

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    positive = []
    for batch in candidates:
        qty = flt(
            get_batch_qty(
                batch_no=batch.name,
                warehouse=warehouse,
                item_code=item_code,
                for_stock_levels=True,
                consider_negative_batches=True,
                ignore_reserved_stock=True,
            )
        )
        if qty <= 0:
            continue
        positive.append([
            batch.name,
            batch.expiry_date or "",
            qty,
        ])

    start = max(cint(start), 0)
    page_len = max(1, min(cint(page_len) or 20, 100))
    return positive[start:start + page_len]


@frappe.whitelist()
def get_batch_stock_for_recall(
    batch_no: str,
    company: str | None = None,
    item_code: str | None = None,
    source_warehouse: str | None = None,
):
    _require_read()
    company = company or _default_company()
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Select a valid recalled Item first."))
    item = frappe.db.get_value(
        "Item", item_code,
        ["item_name", "stock_uom", "disabled", "has_batch_no"],
        as_dict=True,
    )
    if not item or item.disabled or not item.has_batch_no:
        frappe.throw(_("The selected item is disabled or is not batch controlled."))
    if not batch_no or not frappe.db.exists("Batch", {"name": batch_no, "item": item_code}):
        frappe.throw(_("Select a valid Batch No belonging to item {0}.").format(frappe.bold(item_code)))
    batch = frappe.db.get_value(
        "Batch", batch_no,
        ["name", "item", "item_name", "expiry_date", "disabled", "stock_uom"],
        as_dict=True,
    )
    if source_warehouse:
        warehouse = frappe.db.get_value(
            "Warehouse", source_warehouse,
            ["company", "is_group", "disabled"],
            as_dict=True,
        )
        if not warehouse or warehouse.company != company or warehouse.is_group or warehouse.disabled:
            frappe.throw(_("Select an active Source Warehouse for the same company."))
        if source_warehouse in set(filter(None, _special_warehouses(company).values())):
            frappe.throw(_("The Source Warehouse must be a normal sellable warehouse, not a quarantine or returns warehouse."))

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    special = set(filter(None, _special_warehouses(company).values()))
    balances = get_batch_qty(
        batch_no=batch_no,
        item_code=batch.item,
        for_stock_levels=True,
        consider_negative_batches=True,
        ignore_reserved_stock=True,
    ) or []
    expected_rate = _latest_purchase_rate(batch.item, batch_no, company)
    rows = []
    for balance in balances:
        warehouse_name = balance.get("warehouse")
        qty = flt(balance.get("qty"))
        if not warehouse_name or qty <= 0 or warehouse_name in special:
            continue
        if source_warehouse and warehouse_name != source_warehouse:
            continue
        warehouse_company = frappe.db.get_value("Warehouse", warehouse_name, "company")
        if warehouse_company != company:
            continue
        valuation_rate = _stock_valuation_rate(batch.item, warehouse_name, batch_no)
        rows.append({
            "item_code": batch.item,
            "item_name": item.item_name or batch.item_name or batch.item,
            "warehouse": warehouse_name,
            "batch_no": batch_no,
            "expiry_date": batch.expiry_date,
            "stock_uom": item.stock_uom or batch.stock_uom,
            "original_qty": qty,
            "already_returned_qty": 0,
            "available_to_return_qty": qty,
            "return_qty": qty,
            "stock_valuation_rate": valuation_rate,
            "stock_value": qty * valuation_rate,
            "rate": expected_rate,
            "tax_amount": 0,
            "return_amount": qty * expected_rate,
            "return_reason": "Health Authority Recall",
            "notes": "",
        })
    if not rows:
        frappe.throw(_("No positive stock was found for batch {0} in normal warehouses.").format(frappe.bold(batch_no)))
    return {
        "batch_no": batch_no,
        "item_code": batch.item,
        "item_name": item.item_name or batch.item_name,
        "expiry_date": batch.expiry_date,
        "disabled": cint(batch.disabled),
        "estimated_rate": expected_rate,
        "rows": rows,
    }


def _validate_invoice_case_payload(payload: dict) -> None:
    if payload.get("return_type") != "Return Against Invoice":
        return
    if not payload.get("original_purchase_invoice"):
        frappe.throw(_("Select the original Purchase Invoice."))
    invoice = frappe.get_doc("Purchase Invoice", payload.get("original_purchase_invoice"))
    if invoice.docstatus != 1 or cint(invoice.is_return):
        frappe.throw(_("Select a submitted original Purchase Invoice."))
    if payload.get("supplier") and payload.get("supplier") != invoice.supplier:
        frappe.throw(_("The receiving supplier must match the original invoice supplier for an invoice-linked return."))
    selected = [frappe._dict(row) for row in (payload.get("items") or []) if flt(row.get("return_qty")) > 0]
    if not selected:
        frappe.throw(_("Enter a return quantity for at least one item."))
    source = {row.name: row for row in invoice.items}
    already = _returned_qty_by_original_item(invoice.name)
    for row in selected:
        original = source.get(row.original_purchase_invoice_item)
        if not original:
            frappe.throw(_("Invalid original invoice item in return rows."))
        available = max(0.0, abs(flt(original.qty)) - flt(already.get(original.name)))
        if flt(row.return_qty) > available + 0.000001:
            frappe.throw(_("Return quantity for {0} cannot exceed the available quantity {1}.").format(frappe.bold(original.item_code), available))
        if not row.get("return_reason"):
            frappe.throw(_("Select a return reason for item {0}.").format(frappe.bold(original.item_code)))


def _validate_regulatory_case_payload(payload: dict) -> None:
    if payload.get("return_type") != "Regulatory Batch Recall":
        return
    if not payload.get("authority_notification_no"):
        frappe.throw(_("Enter the Authority Notification Number."))
    if not payload.get("authority_notification_date"):
        frappe.throw(_("Enter the Authority Notification Date."))
    if not payload.get("recall_source_warehouse"):
        frappe.throw(_("Select the Source Warehouse."))
    quarantine = payload.get("recall_quarantine_warehouse")
    if not quarantine:
        frappe.throw(_("Select the Recall Quarantine Warehouse."))
    warehouse = frappe.db.get_value("Warehouse", quarantine, ["company", "is_group", "disabled"], as_dict=True)
    if not warehouse or warehouse.company != payload.get("company") or warehouse.is_group or warehouse.disabled:
        frappe.throw(_("Select an active quarantine warehouse for the same company."))
    selected = [frappe._dict(row) for row in (payload.get("items") or []) if flt(row.get("return_qty")) > 0]
    if not selected:
        frappe.throw(_("Enter a recall quantity for at least one warehouse row."))

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    for row in selected:
        if row.warehouse != payload.get("recall_source_warehouse"):
            frappe.throw(_("Recall row warehouse must match the selected Source Warehouse."))
        if not row.batch_no or not frappe.db.exists("Batch", row.batch_no):
            frappe.throw(_("Select a valid Batch No for item {0}.").format(frappe.bold(row.item_code)))
        batch_item = frappe.db.get_value("Batch", row.batch_no, "item")
        if batch_item != row.item_code:
            frappe.throw(_("Batch {0} does not belong to item {1}.").format(frappe.bold(row.batch_no), frappe.bold(row.item_code)))
        current = flt(get_batch_qty(
            batch_no=row.batch_no,
            warehouse=row.warehouse,
            item_code=row.item_code,
            for_stock_levels=True,
            consider_negative_batches=True,
            ignore_reserved_stock=True,
        ))
        if flt(row.return_qty) > current + 0.000001:
            frappe.throw(_("Recall quantity for batch {0} in {1} cannot exceed current stock {2}.").format(frappe.bold(row.batch_no), frappe.bold(row.warehouse), current))


def _set_case_values(doc, payload: dict) -> None:
    return_type = payload.get("return_type") or "Return Against Invoice"
    doc.return_type = return_type
    doc.company = payload.get("company")
    doc.posting_date = payload.get("posting_date") or nowdate()
    doc.supplier = payload.get("supplier")
    doc.original_purchase_invoice = payload.get("original_purchase_invoice") or None
    doc.settlement_method = payload.get("settlement_method") or "Pending Settlement"
    doc.remarks = payload.get("remarks") or ""
    doc.operational_status = doc.operational_status or "Draft"
    doc.authority_notification_no = payload.get("authority_notification_no") or None
    doc.authority_notification_date = payload.get("authority_notification_date") or None
    doc.authority_notification_attachment = payload.get("authority_notification_attachment") or None
    doc.recall_source_warehouse = payload.get("recall_source_warehouse") or None
    doc.recall_item_code = None
    doc.recall_quarantine_warehouse = payload.get("recall_quarantine_warehouse") or None
    doc.set("items", [])
    for source in payload.get("items") or []:
        row = frappe._dict(source)
        if flt(row.return_qty) <= 0:
            continue
        doc.append("items", {
            "original_purchase_invoice_item": row.get("original_purchase_invoice_item"),
            "item_code": row.item_code,
            "item_name": row.item_name,
            "warehouse": row.warehouse,
            "batch_no": row.batch_no,
            "expiry_date": row.expiry_date,
            "stock_uom": row.stock_uom,
            "original_qty": flt(row.original_qty),
            "already_returned_qty": flt(row.already_returned_qty),
            "available_to_return_qty": flt(row.available_to_return_qty),
            "quarantine_warehouse": payload.get("recall_quarantine_warehouse") if return_type == "Regulatory Batch Recall" else row.get("quarantine_warehouse"),
            "return_qty": flt(row.return_qty),
            "stock_valuation_rate": flt(row.get("stock_valuation_rate")),
            "stock_value": flt(row.return_qty) * flt(row.get("stock_valuation_rate")),
            "rate": flt(row.rate),
            "tax_amount": flt(row.tax_amount),
            "return_amount": flt(row.return_qty) * flt(row.rate),
            "return_reason": "Health Authority Recall" if return_type == "Regulatory Batch Recall" else (row.return_reason or "Normal Return"),
            "notes": row.notes or "",
        })

    if return_type == "Regulatory Batch Recall":
        unique_items = sorted({row.item_code for row in doc.items if row.item_code})
        doc.recall_item_code = unique_items[0] if len(unique_items) == 1 else None


@frappe.whitelist()
def save_case(payload):
    _require_create()
    payload = _parse(payload)
    if not payload.get("company") or not frappe.db.exists("Company", payload.get("company")):
        frappe.throw(_("Select a valid company."))
    if not payload.get("supplier") or not frappe.db.exists("Supplier", payload.get("supplier")):
        frappe.throw(_("Select the company or distributor receiving the return."))
    _validate_invoice_case_payload(payload)
    _validate_regulatory_case_payload(payload)

    if payload.get("name"):
        doc = frappe.get_doc("Pharmacy Return Case", payload.get("name"))
        if doc.docstatus != 0:
            frappe.throw(_("Only a draft Return Case can be edited."))
    else:
        doc = frappe.new_doc("Pharmacy Return Case")
    _set_case_values(doc, payload)
    doc.save()
    return get_case(doc.name)


@frappe.whitelist()
def get_case(name: str):
    _require_read()
    doc = frappe.get_doc("Pharmacy Return Case", name)
    _sync_case_operational_status(doc)
    if doc.return_type == "Regulatory Batch Recall" and doc.quarantine_stock_entry:
        status = frappe.db.get_value("Stock Entry", doc.quarantine_stock_entry, "docstatus")
        if status == 1:
            total = sum(flt(row.return_qty) for row in doc.items)
            if flt(doc.quarantined_quantity) != total:
                doc.db_set("quarantined_quantity", total, update_modified=False)
                for row in doc.items:
                    if flt(row.quarantined_qty) != flt(row.return_qty):
                        row.db_set("quarantined_qty", flt(row.return_qty), update_modified=False)
                        row.quarantined_qty = flt(row.return_qty)
                doc.quarantined_quantity = total
    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "return_type": doc.return_type,
        "company": doc.company,
        "posting_date": doc.posting_date,
        "supplier": doc.supplier,
        "original_purchase_invoice": doc.original_purchase_invoice,
        "purchase_return": doc.purchase_return,
        "quarantine_stock_entry": doc.quarantine_stock_entry,
        "recall_source_warehouse": doc.recall_source_warehouse,
        "recall_item_code": doc.recall_item_code,
        "recall_quarantine_warehouse": doc.recall_quarantine_warehouse,
        "authority_notification_no": doc.authority_notification_no,
        "authority_notification_date": doc.authority_notification_date,
        "authority_notification_attachment": doc.authority_notification_attachment,
        "settlement_method": doc.settlement_method,
        "operational_status": doc.operational_status,
        "requested_return_value": doc.requested_return_value,
        "approved_return_value": doc.approved_return_value,
        "quarantined_quantity": doc.quarantined_quantity,
        "remarks": doc.remarks,
        "items": [row.as_dict() for row in doc.items],
    }


def _make_standard_debit_note(original_invoice: str):
    from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note
    return make_debit_note(original_invoice)


def _match_mapped_item(mapped, case_row):
    original_name = case_row.original_purchase_invoice_item
    for row in mapped.items:
        if row.get("purchase_invoice_item") == original_name:
            return row
    candidates = [row for row in mapped.items if row.item_code == case_row.item_code and (not case_row.warehouse or row.warehouse == case_row.warehouse)]
    return candidates[0] if len(candidates) == 1 else None


@frappe.whitelist()
def create_purchase_return_draft(case_name: str):
    _require_create()
    if not frappe.has_permission("Purchase Invoice", "create"):
        frappe.throw(_("You are not permitted to create Purchase Returns."), frappe.PermissionError)
    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if case.return_type != "Return Against Invoice":
        frappe.throw(_("This action is only for invoice-linked returns."))
    if case.purchase_return:
        if frappe.db.exists("Purchase Invoice", case.purchase_return):
            return {"case": case.name, "purchase_return": case.purchase_return, "already_exists": 1}
        case.purchase_return = None
    if not case.original_purchase_invoice:
        frappe.throw(_("Original Purchase Invoice is required."))

    payload = {
        "return_type": case.return_type,
        "original_purchase_invoice": case.original_purchase_invoice,
        "supplier": case.supplier,
        "items": [row.as_dict() for row in case.items],
    }
    _validate_invoice_case_payload(payload)

    mapped = _make_standard_debit_note(case.original_purchase_invoice)
    mapped.posting_date = case.posting_date or nowdate()
    mapped.set_posting_time = 0
    mapped.update_stock = 1
    mapped.remarks = _("Created from Pharmacy Return Case {0}").format(case.name)

    new_items = []
    for case_row in case.items:
        if flt(case_row.return_qty) <= 0:
            continue
        mapped_row = _match_mapped_item(mapped, case_row)
        if not mapped_row:
            frappe.throw(_("Could not match original row for item {0}.").format(frappe.bold(case_row.item_code)))
        mapped_row.qty = -abs(flt(case_row.return_qty))
        if mapped_row.meta.has_field("rejected_qty"):
            mapped_row.rejected_qty = 0
        if mapped_row.meta.has_field("received_qty"):
            mapped_row.received_qty = mapped_row.qty
        mapped_row.stock_qty = mapped_row.qty * (flt(mapped_row.conversion_factor) or 1)
        mapped_row.warehouse = case_row.warehouse or mapped_row.warehouse
        if mapped_row.meta.has_field("rejected_warehouse"):
            mapped_row.rejected_warehouse = None
        if mapped_row.meta.has_field("rejected_serial_and_batch_bundle"):
            mapped_row.rejected_serial_and_batch_bundle = None
        if mapped_row.meta.has_field("rejected_serial_no"):
            mapped_row.rejected_serial_no = None
        if mapped_row.meta.has_field("batch_no") and case_row.batch_no:
            mapped_row.batch_no = case_row.batch_no
        if mapped_row.meta.has_field("serial_and_batch_bundle"):
            mapped_row.serial_and_batch_bundle = None
        if mapped_row.meta.has_field("use_serial_batch_fields") and case_row.batch_no:
            mapped_row.use_serial_batch_fields = 1
        new_items.append(mapped_row)
    mapped.set("items", new_items)

    if mapped.meta.has_field("custom_pharmacy_return_case"):
        mapped.custom_pharmacy_return_case = case.name
    mapped.insert()

    case.purchase_return = mapped.name
    case.operational_status = "Purchase Return Draft Created"
    case.save(ignore_permissions=True)
    return {"case": case.name, "purchase_return": mapped.name, "already_exists": 0}


@frappe.whitelist()
def create_quarantine_transfer_draft(case_name: str):
    _require_create()
    if not frappe.has_permission("Stock Entry", "create"):
        frappe.throw(_("You are not permitted to create Stock Entries."), frappe.PermissionError)
    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if case.return_type != "Regulatory Batch Recall":
        frappe.throw(_("This action is only for Regulatory Batch Recall cases."))
    _sync_case_operational_status(case)
    if case.quarantine_stock_entry:
        if frappe.db.exists("Stock Entry", case.quarantine_stock_entry):
            return {"case": case.name, "stock_entry": case.quarantine_stock_entry, "already_exists": 1}
        case.quarantine_stock_entry = None

    payload = {
        "return_type": case.return_type,
        "company": case.company,
        "supplier": case.supplier,
        "authority_notification_no": case.authority_notification_no,
        "authority_notification_date": case.authority_notification_date,
        "recall_source_warehouse": case.recall_source_warehouse,
        "recall_item_code": case.recall_item_code,
        "recall_quarantine_warehouse": case.recall_quarantine_warehouse,
        "items": [row.as_dict() for row in case.items],
    }
    _validate_regulatory_case_payload(payload)

    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.company = case.company
    stock_entry.purpose = "Material Transfer"
    stock_entry.posting_date = case.posting_date or nowdate()
    stock_entry.set_posting_time = 0
    stock_entry.to_warehouse = case.recall_quarantine_warehouse
    stock_entry.remarks = _("Regulatory batch recall quarantine transfer for Pharmacy Return Case {0}. Authority notice: {1}").format(case.name, case.authority_notification_no)

    for row in case.items:
        qty = flt(row.return_qty)
        if qty <= 0:
            continue
        stock_entry.append("items", {
            "item_code": row.item_code,
            "qty": qty,
            "uom": row.stock_uom,
            "stock_uom": row.stock_uom,
            "conversion_factor": 1,
            "s_warehouse": row.warehouse,
            "t_warehouse": case.recall_quarantine_warehouse,
            "batch_no": row.batch_no,
            "use_serial_batch_fields": 1 if row.batch_no else 0,
        })
    if hasattr(stock_entry, "set_stock_entry_type"):
        stock_entry.set_stock_entry_type()
    stock_entry.insert()

    case.quarantine_stock_entry = stock_entry.name
    case.operational_status = "Quarantine Transfer Draft Created"
    for row in case.items:
        row.quarantine_warehouse = case.recall_quarantine_warehouse
    case.save(ignore_permissions=True)
    return {"case": case.name, "stock_entry": stock_entry.name, "already_exists": 0}


@frappe.whitelist()
def list_recent_cases(company: str | None = None, limit: int = 30):
    _require_read()
    return _recent_cases(company or _default_company(), limit)
