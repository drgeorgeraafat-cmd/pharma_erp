"""Operational API for Purchase Returns Management.

Purchase Invoice remains the official accounting and stock document for returns
against an invoice. Pharmacy Return Case is the operational wrapper that also
supports regulatory recalls and expired-drug returns in later stages.
"""
from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

READ_ROLES = {
    "Purchase User", "Purchase Manager", "Accounts User", "Accounts Manager",
    "Stock User", "Stock Manager", "System Manager",
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
    """Return a plain Python dict.

    frappe._dict exposes dict methods as attributes. A payload key named
    ``items`` can therefore collide with ``dict.items`` in some request paths.
    Using json.loads and ordinary dictionary access avoids that ambiguity.
    """
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


def _recent_cases(company: str | None, limit: int = 20) -> list[dict]:
    filters = {"company": company} if company else {}
    return frappe.get_list(
        "Pharmacy Return Case",
        filters=filters,
        fields=[
            "name", "posting_date", "return_type", "supplier", "original_purchase_invoice",
            "purchase_return", "operational_status", "requested_return_value",
            "approved_return_value", "settlement_method", "modified",
        ],
        order_by="modified desc",
        limit_page_length=max(1, min(cint(limit) or 20, 100)),
    )


@frappe.whitelist()
def get_bootstrap(company: str | None = None, purchase_invoice: str | None = None):
    _require_read()
    company = company or _default_company()
    result = {
        "company": company,
        "posting_date": nowdate(),
        "recent_cases": _recent_cases(company),
        "can_create_case": bool(frappe.has_permission("Pharmacy Return Case", "create")),
        "can_create_purchase_invoice": bool(frappe.has_permission("Purchase Invoice", "create")),
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
            frappe.throw(
                _("Return quantity for {0} cannot exceed the available quantity {1}.").format(
                    frappe.bold(original.item_code), available
                )
            )
        if not row.get("return_reason"):
            frappe.throw(_("Select a return reason for item {0}.").format(frappe.bold(original.item_code)))


def _set_case_values(doc, payload: dict) -> None:
    doc.return_type = payload.get("return_type") or "Return Against Invoice"
    doc.company = payload.get("company")
    doc.posting_date = payload.get("posting_date") or nowdate()
    doc.supplier = payload.get("supplier")
    doc.original_purchase_invoice = payload.get("original_purchase_invoice") or None
    doc.settlement_method = payload.get("settlement_method") or "Pending Settlement"
    doc.remarks = payload.get("remarks") or ""
    doc.operational_status = doc.operational_status or "Draft"
    doc.set("items", [])
    for source in payload.get("items") or []:
        row = frappe._dict(source)
        if flt(row.return_qty) <= 0:
            continue
        doc.append("items", {
            "original_purchase_invoice_item": row.original_purchase_invoice_item,
            "item_code": row.item_code,
            "item_name": row.item_name,
            "warehouse": row.warehouse,
            "batch_no": row.batch_no,
            "expiry_date": row.expiry_date,
            "stock_uom": row.stock_uom,
            "original_qty": flt(row.original_qty),
            "already_returned_qty": flt(row.already_returned_qty),
            "available_to_return_qty": flt(row.available_to_return_qty),
            "return_qty": flt(row.return_qty),
            "rate": flt(row.rate),
            "tax_amount": flt(row.tax_amount),
            "return_amount": flt(row.return_qty) * flt(row.rate),
            "return_reason": row.return_reason or "Normal Return",
            "notes": row.notes or "",
        })


@frappe.whitelist()
def save_case(payload):
    _require_create()
    payload = _parse(payload)
    if not payload.get("company") or not frappe.db.exists("Company", payload.get("company")):
        frappe.throw(_("Select a valid company."))
    if not payload.get("supplier") or not frappe.db.exists("Supplier", payload.get("supplier")):
        frappe.throw(_("Select the company or distributor receiving the return."))
    _validate_invoice_case_payload(payload)

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
    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "return_type": doc.return_type,
        "company": doc.company,
        "posting_date": doc.posting_date,
        "supplier": doc.supplier,
        "original_purchase_invoice": doc.original_purchase_invoice,
        "purchase_return": doc.purchase_return,
        "settlement_method": doc.settlement_method,
        "operational_status": doc.operational_status,
        "requested_return_value": doc.requested_return_value,
        "approved_return_value": doc.approved_return_value,
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
    candidates = [
        row for row in mapped.items
        if row.item_code == case_row.item_code and (not case_row.warehouse or row.warehouse == case_row.warehouse)
    ]
    return candidates[0] if len(candidates) == 1 else None


@frappe.whitelist()
def create_purchase_return_draft(case_name: str):
    _require_create()
    if not frappe.has_permission("Purchase Invoice", "create"):
        frappe.throw(_("You are not permitted to create Purchase Returns."), frappe.PermissionError)
    case = frappe.get_doc("Pharmacy Return Case", case_name)
    if case.return_type != "Return Against Invoice":
        frappe.throw(_("This version creates official Purchase Returns only for invoice-linked cases."))
    if case.purchase_return:
        if frappe.db.exists("Purchase Invoice", case.purchase_return):
            return {"case": case.name, "purchase_return": case.purchase_return, "already_exists": 1}
        case.purchase_return = None
    if not case.original_purchase_invoice:
        frappe.throw(_("Original Purchase Invoice is required."))

    payload = frappe._dict({
        "return_type": case.return_type,
        "original_purchase_invoice": case.original_purchase_invoice,
        "supplier": case.supplier,
        "items": [row.as_dict() for row in case.items],
    })
    _validate_invoice_case_payload(payload)

    mapped = _make_standard_debit_note(case.original_purchase_invoice)
    mapped.posting_date = case.posting_date or nowdate()
    mapped.set_posting_time = 0
    mapped.update_stock = 1
    mapped.remarks = _("Created from Pharmacy Return Case {0}").format(case.name)

    selected_names = {row.original_purchase_invoice_item for row in case.items if flt(row.return_qty) > 0}
    new_items = []
    for case_row in case.items:
        if flt(case_row.return_qty) <= 0:
            continue
        mapped_row = _match_mapped_item(mapped, case_row)
        if not mapped_row:
            frappe.throw(_("Could not match original row for item {0}.").format(frappe.bold(case_row.item_code)))
        mapped_row.qty = -abs(flt(case_row.return_qty))

        # In Purchase Invoice Item, qty is the Accepted Qty. ERPNext validates:
        # Received Qty = Accepted Qty + Rejected Qty.
        # make_debit_note can retain received/rejected values from the source row,
        # so they must be aligned after changing a partial-return quantity.
        if mapped_row.meta.has_field("rejected_qty"):
            mapped_row.rejected_qty = 0
        if mapped_row.meta.has_field("received_qty"):
            mapped_row.received_qty = mapped_row.qty

        mapped_row.stock_qty = mapped_row.qty * (flt(mapped_row.conversion_factor) or 1)
        mapped_row.warehouse = case_row.warehouse or mapped_row.warehouse

        # This flow returns accepted stock from the normal warehouse, not stock
        # held in a rejected warehouse.
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
    mapped.flags.ignore_permissions = False
    mapped.insert()

    case.purchase_return = mapped.name
    case.operational_status = "Purchase Return Draft Created"
    case.save(ignore_permissions=True)
    return {"case": case.name, "purchase_return": mapped.name, "already_exists": 0}


@frappe.whitelist()
def list_recent_cases(company: str | None = None, limit: int = 30):
    _require_read()
    return _recent_cases(company or _default_company(), limit)
