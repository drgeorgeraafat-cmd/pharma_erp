"""Server API for the Purchase & Invoice Management desk page.

The page is an operational interface only. Purchase Invoice remains the official
stock and accounting document in ERPNext.
"""

from __future__ import annotations

import calendar
import html
import json
import re
from datetime import date, datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, now_datetime, nowdate, escape_html

from pharma_erp.purchase_management import (
    get_purchase_settings,
    get_retail_price_change_preview,
    set_retail_price_submission_decision,
)


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
            "is_return",
            "return_against",
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


_OPEN_PROCUREMENT_DRAFT_CONFIG = {
    "purchase_request": {
        "doctype": "Material Request",
        "label": "Request",
        "date_fields": ["transaction_date", "schedule_date"],
        "supplier_fields": ["custom_source_supplier"],
        "filters": {"material_request_type": "Purchase"},
        "next_action": "Continue to Order",
    },
    "purchase_order": {
        "doctype": "Purchase Order",
        "label": "Order",
        "date_fields": ["transaction_date", "schedule_date"],
        "supplier_fields": ["supplier"],
        "filters": {},
        "next_action": "Continue to Receipt",
    },
    "purchase_receipt": {
        "doctype": "Purchase Receipt",
        "label": "Receipt",
        "date_fields": ["posting_date"],
        "supplier_fields": ["supplier"],
        "filters": {},
        "next_action": "Continue to Invoice",
    },
    "purchase_invoice": {
        "doctype": "Purchase Invoice",
        "label": "Invoice",
        "date_fields": ["posting_date"],
        "supplier_fields": ["supplier"],
        "filters": {"is_return": 0},
        "next_action": "Review / Submit",
    },
}


def _open_draft_item_stats(doctype: str, names: list[str]) -> dict[str, dict[str, float]]:
    if not names:
        return {}
    items_field = frappe.get_meta(doctype).get_field("items")
    child_doctype = items_field.options if items_field else None
    if not child_doctype or not frappe.db.exists("DocType", child_doctype):
        return {}

    placeholders = ", ".join(["%s"] * len(names))
    values = [*names, doctype]
    rows = frappe.db.sql(
        f"""
        select parent, count(name) as items_count, coalesce(sum(qty), 0) as total_qty
        from `tab{child_doctype}`
        where parent in ({placeholders}) and parenttype = %s
        group by parent
        """,
        tuple(values),
        as_dict=True,
    )
    return {
        row.parent: {
            "items_count": cint(row.items_count),
            "total_qty": flt(row.total_qty),
        }
        for row in rows
    }



def _open_draft_downstream_progress(stage_key: str, source_names: list[str]) -> dict[str, dict[str, Any]]:
    """Return downstream quantity usage and linked document names for procurement drafts.

    The source documents intentionally remain ERPNext Drafts.  Operational progress is
    therefore calculated from linked downstream child rows instead of docstatus.
    """
    if not source_names:
        return {}

    configs = {
        "purchase_request": {
            "parent_doctype": "Purchase Order",
            "child_doctype": "Purchase Order Item",
            "link_fields": ["material_request"],
            "qty_fields": ["qty", "stock_qty"],
            "target_stage": "purchase_order",
        },
        "purchase_order": {
            "parent_doctype": "Purchase Receipt",
            "child_doctype": "Purchase Receipt Item",
            "link_fields": ["purchase_order"],
            "qty_fields": ["qty", "received_qty", "accepted_qty", "stock_qty"],
            "target_stage": "purchase_receipt",
        },
        "purchase_receipt": {
            "parent_doctype": "Purchase Invoice",
            "child_doctype": "Purchase Invoice Item",
            "link_fields": ["purchase_receipt"],
            "qty_fields": ["qty", "stock_qty"],
            "target_stage": "purchase_invoice",
        },
    }
    config = configs.get(stage_key)
    if not config:
        return {}

    child_meta = frappe.get_meta(config["child_doctype"])
    child_fields = {field.fieldname for field in child_meta.fields if field.fieldname}
    link_field = next((field for field in config["link_fields"] if field in child_fields), None)
    qty_field = next((field for field in config["qty_fields"] if field in child_fields), None)
    if not link_field or not qty_field:
        return {}

    placeholders = ", ".join(["%s"] * len(source_names))
    rows = frappe.db.sql(
        f"""
        select
            c.`{link_field}` as source_name,
            coalesce(sum(c.`{qty_field}`), 0) as used_qty,
            group_concat(distinct p.name order by p.modified desc separator '\\n') as downstream_names
        from `tab{config['child_doctype']}` c
        join `tab{config['parent_doctype']}` p on p.name = c.parent
        where c.`{link_field}` in ({placeholders})
          and p.docstatus < 2
        group by c.`{link_field}`
        """,
        tuple(source_names),
        as_dict=True,
    )

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        names = [name for name in str(row.get("downstream_names") or "").split("\n") if name]
        result[row.get("source_name")] = {
            "used_qty": flt(row.get("used_qty")),
            "downstream_names": names,
            "target_stage": config["target_stage"],
            "target_doctype": _OPEN_PROCUREMENT_DRAFT_CONFIG[config["target_stage"]]["doctype"],
        }
    return result


def _open_draft_progress_label(stage_key: str, progress_status: str) -> str:
    labels = {
        "purchase_request": {
            "open": _("Open / Not Ordered"),
            "partial": _("Partially Ordered"),
            "done": _("Done / Fully Ordered"),
        },
        "purchase_order": {
            "open": _("Open / Not Received"),
            "partial": _("Partially Received"),
            "done": _("Done / Fully Received"),
        },
        "purchase_receipt": {
            "open": _("Open / Not Invoiced"),
            "partial": _("Partially Invoiced"),
            "done": _("Done / Fully Invoiced"),
        },
        "purchase_invoice": {
            "open": _("Open / Review & Submit"),
            "partial": _("Open / Review & Submit"),
            "done": _("Submitted"),
        },
    }
    return labels.get(stage_key, {}).get(progress_status) or _(progress_status.title())


def _open_draft_next_action(stage_key: str, progress_status: str, has_next_document: bool) -> str:
    next_labels = {
        "purchase_request": _("Order"),
        "purchase_order": _("Receipt"),
        "purchase_receipt": _("Invoice"),
    }
    if stage_key == "purchase_invoice":
        return _("Review / Submit")
    target = next_labels.get(stage_key) or _("Next Stage")
    if progress_status == "done" and has_next_document:
        return _("Open linked {0}").format(target)
    if progress_status == "partial":
        return _("Continue remaining to {0}").format(target)
    return _("Continue to {0}").format(target)


def _linked_item_rows(parent_doctype: str, parent_name: str, desired_fields: list[str]) -> list[dict[str, Any]]:
    items_field = frappe.get_meta(parent_doctype).get_field("items")
    child_doctype = items_field.options if items_field else None
    if not child_doctype or not frappe.db.exists("DocType", child_doctype):
        return []
    available = set(frappe.get_meta(child_doctype).get_valid_columns())
    fields = [field for field in desired_fields if field in available]
    if not fields:
        return []
    return frappe.get_all(
        child_doctype,
        filters={"parent": parent_name, "parenttype": parent_doctype},
        fields=fields,
        order_by="idx asc",
        limit_page_length=1000,
    )


def _procurement_linked_documents(source_type: str, source_name: str) -> dict[str, Any]:
    """Resolve the full Request -> Order -> Receipt -> Invoice chain from official rows.

    The page stores links in browser localStorage for convenience, but official child-row
    links are the source of truth after the page is closed and reopened.
    """
    stage_doctypes = {
        "purchase_request": "Material Request",
        "purchase_order": "Purchase Order",
        "purchase_receipt": "Purchase Receipt",
        "purchase_invoice": "Purchase Invoice",
    }
    if source_type not in stage_doctypes or not source_name:
        return {}

    names: dict[str, list[str]] = {key: [] for key in stage_doctypes}

    def add(stage: str, value: Any) -> None:
        value = str(value or "").strip()
        if value and value not in names[stage] and frappe.db.exists(stage_doctypes[stage], value):
            names[stage].append(value)

    add(source_type, source_name)

    if source_type == "purchase_order":
        for row in _linked_item_rows("Purchase Order", source_name, ["material_request"]):
            add("purchase_request", row.get("material_request"))

    elif source_type == "purchase_receipt":
        for row in _linked_item_rows("Purchase Receipt", source_name, ["purchase_order", "material_request"]):
            add("purchase_order", row.get("purchase_order"))
            add("purchase_request", row.get("material_request"))
        for order_name in list(names["purchase_order"]):
            for row in _linked_item_rows("Purchase Order", order_name, ["material_request"]):
                add("purchase_request", row.get("material_request"))

    elif source_type == "purchase_invoice":
        for row in _linked_item_rows(
            "Purchase Invoice",
            source_name,
            ["purchase_receipt", "purchase_order", "material_request"],
        ):
            add("purchase_receipt", row.get("purchase_receipt"))
            add("purchase_order", row.get("purchase_order"))
            add("purchase_request", row.get("material_request"))
        for receipt_name in list(names["purchase_receipt"]):
            for row in _linked_item_rows("Purchase Receipt", receipt_name, ["purchase_order", "material_request"]):
                add("purchase_order", row.get("purchase_order"))
                add("purchase_request", row.get("material_request"))
        for order_name in list(names["purchase_order"]):
            for row in _linked_item_rows("Purchase Order", order_name, ["material_request"]):
                add("purchase_request", row.get("material_request"))

    linked: dict[str, Any] = {}
    all_links: dict[str, list[str]] = {}
    for stage, doctype in stage_doctypes.items():
        if names[stage]:
            linked[stage] = {"doctype": doctype, "name": names[stage][0]}
            all_links[stage] = names[stage]
    if all_links:
        linked["all"] = all_links
        linked["has_multiple"] = any(len(values) > 1 for values in all_links.values())
    return linked


def _open_procurement_drafts(
    company: str | None,
    *,
    supplier: str | None = None,
    stage: str | None = None,
    search_text: str | None = None,
    progress_status: str | None = "active",
    limit: int = 60,
) -> dict[str, Any]:
    selected_stage = (stage or "").strip().lower()
    if selected_stage in {"all", "all_stages"}:
        selected_stage = ""
    selected_progress = (progress_status or "active").strip().lower()
    if selected_progress not in {"active", "open", "partial", "done", "all"}:
        selected_progress = "active"

    stage_keys = [selected_stage] if selected_stage in _OPEN_PROCUREMENT_DRAFT_CONFIG else list(_OPEN_PROCUREMENT_DRAFT_CONFIG)
    per_stage_limit = max(20, min(cint(limit) or 60, 120))
    search_text = (search_text or "").strip()
    all_drafts: list[dict[str, Any]] = []

    for stage_key in stage_keys:
        config = _OPEN_PROCUREMENT_DRAFT_CONFIG[stage_key]
        doctype = config["doctype"]
        if not frappe.db.exists("DocType", doctype) or not frappe.has_permission(doctype, "read"):
            continue

        available = set(frappe.get_meta(doctype).get_valid_columns())
        supplier_field = next((field for field in config["supplier_fields"] if field in available), None)
        if supplier and not supplier_field:
            continue

        filters: dict[str, Any] = {"docstatus": 0, **config["filters"]}
        if company and "company" in available:
            filters["company"] = company
        if supplier and supplier_field:
            filters[supplier_field] = supplier
        if search_text:
            filters["name"] = ["like", f"%{search_text}%"]

        desired_fields = [
            "name", "company", "status", "creation", "modified", "owner",
            "grand_total", "rounded_total", "net_total", "total_qty",
            *config["date_fields"], *config["supplier_fields"], "supplier_name",
        ]
        rows = frappe.get_list(
            doctype,
            filters=filters,
            fields=[field for field in desired_fields if field in available],
            order_by="modified desc",
            limit_page_length=per_stage_limit,
        )
        row_names = [row.get("name") for row in rows if row.get("name")]
        item_stats = _open_draft_item_stats(doctype, row_names)
        downstream = _open_draft_downstream_progress(stage_key, row_names)

        for row in rows:
            row = frappe._dict(row)
            supplier_name = row.get("supplier_name") or ""
            supplier_value = row.get(supplier_field) if supplier_field else ""
            document_date = next((row.get(field) for field in config["date_fields"] if row.get(field)), None)
            created_on = row.get("creation") or row.get("modified") or now_datetime()
            days_open = max(0, cint(date_diff(nowdate(), getdate(created_on))))
            stats = item_stats.get(row.get("name"), {})
            total_qty = flt(row.get("total_qty")) or flt(stats.get("total_qty"))
            grand_total = flt(row.get("grand_total") or row.get("rounded_total") or row.get("net_total"))
            progress = downstream.get(row.get("name"), {})
            used_qty = flt(progress.get("used_qty"))
            remaining_qty = max(total_qty - used_qty, 0)

            if stage_key == "purchase_invoice":
                operational_status = "open"
            elif total_qty > 0 and used_qty >= total_qty - 0.0001:
                operational_status = "done"
            elif used_qty > 0.0001:
                operational_status = "partial"
            else:
                operational_status = "open"

            downstream_names = progress.get("downstream_names") or []
            next_document_name = downstream_names[0] if downstream_names else ""
            next_document_stage = progress.get("target_stage") or ""
            next_document_doctype = progress.get("target_doctype") or ""
            next_action = _open_draft_next_action(stage_key, operational_status, bool(next_document_name))

            all_drafts.append({
                "stage": stage_key,
                "stage_label": _(config["label"]),
                "doctype": doctype,
                "name": row.get("name"),
                "company": row.get("company") or company or "",
                "supplier": supplier_value or "",
                "supplier_name": supplier_name,
                "date": document_date,
                "status": row.get("status") or _("Draft"),
                "modified": row.get("modified"),
                "owner": row.get("owner") or "",
                "days_open": days_open,
                "items_count": cint(stats.get("items_count")),
                "total_qty": total_qty,
                "used_qty": used_qty,
                "remaining_qty": remaining_qty,
                "grand_total": grand_total,
                "operational_status": operational_status,
                "operational_status_label": _open_draft_progress_label(stage_key, operational_status),
                "next_action": next_action,
                "next_document_name": next_document_name,
                "next_document_stage": next_document_stage,
                "next_document_doctype": next_document_doctype,
                "next_documents_count": len(downstream_names),
                "route": f"/app/{doctype.lower().replace(' ', '-')}/{row.get('name')}",
            })

    supplier_ids = sorted({row["supplier"] for row in all_drafts if row.get("supplier") and not row.get("supplier_name")})
    supplier_names = {}
    if supplier_ids:
        supplier_names = {
            row.get("name"): row.get("supplier_name")
            for row in frappe.get_all(
                "Supplier",
                filters={"name": ["in", supplier_ids]},
                fields=["name", "supplier_name"],
                limit_page_length=len(supplier_ids),
            )
        }
    for row in all_drafts:
        if not row.get("supplier_name") and row.get("supplier"):
            row["supplier_name"] = supplier_names.get(row["supplier"]) or row["supplier"]

    progress_counts = {"open": 0, "partial": 0, "done": 0}
    for row in all_drafts:
        status_key = row.get("operational_status") or "open"
        progress_counts[status_key] = progress_counts.get(status_key, 0) + 1

    if selected_progress == "active":
        drafts = [row for row in all_drafts if row.get("operational_status") in {"open", "partial"}]
    elif selected_progress == "all":
        drafts = list(all_drafts)
    else:
        drafts = [row for row in all_drafts if row.get("operational_status") == selected_progress]

    drafts.sort(key=lambda row: str(row.get("modified") or ""), reverse=True)
    max_results = max(1, min(cint(limit) or 60, 120))
    drafts = drafts[:max_results]
    counts = {key: 0 for key in _OPEN_PROCUREMENT_DRAFT_CONFIG}
    for row in drafts:
        counts[row["stage"]] = counts.get(row["stage"], 0) + 1

    return {
        "drafts": drafts,
        "counts": counts,
        "progress_counts": progress_counts,
        "total": len(drafts),
        "all_status_total": len(all_drafts),
        "filters": {
            "company": company or "",
            "supplier": supplier or "",
            "stage": selected_stage,
            "search_text": search_text,
            "progress_status": selected_progress,
        },
    }


@frappe.whitelist()
def get_open_procurement_drafts(
    company: str | None = None,
    supplier: str | None = None,
    stage: str | None = None,
    search_text: str | None = None,
    progress_status: str | None = "active",
    limit: int = 60,
):
    _require_read_access()
    company = company or _default_company()
    if supplier and not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Supplier does not exist."))
    return _open_procurement_drafts(
        company,
        supplier=supplier or None,
        stage=stage or None,
        search_text=search_text or None,
        progress_status=progress_status or "active",
        limit=limit,
    )


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
        {
            "name": name,
            "rate": _item_tax_template_rate(name),
            "tax_accounts": [row.get("account") for row in _item_tax_accounts(name) if row.get("account")],
        }
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
        "open_procurement_drafts": _open_procurement_drafts(company, limit=60),
        "recent_invoices": _recent_invoices(company),
        "can_create": bool(frappe.has_permission("Purchase Invoice", "create")),
        "can_submit": bool(frappe.has_permission("Purchase Invoice", "submit")),
    }


def _purchase_invoice_linked_supplier_claim(invoice_name: str) -> str:
    if not invoice_name:
        return ""
    if "custom_supplier_claim" in _safe_fields("Purchase Invoice", ["custom_supplier_claim"]):
        claim = frappe.db.get_value("Purchase Invoice", invoice_name, "custom_supplier_claim")
        if claim:
            return claim
    if frappe.db.exists("DocType", "Supplier Claim Invoice"):
        return frappe.db.get_value(
            "Supplier Claim Invoice",
            {"purchase_invoice": invoice_name, "parenttype": "Supplier Claim"},
            "parent",
        ) or ""
    return ""


@frappe.whitelist()
def get_invoice_settlement_context(name: str):
    """Read-only settlement snapshot for one Purchase Invoice.

    Financial actions continue to use the established Supplier Running Account
    APIs so payment, claim and advance rules remain centralized.
    """
    _require_read_access()
    invoice_name = (name or "").strip()
    if not invoice_name or not frappe.db.exists("Purchase Invoice", invoice_name):
        frappe.throw(_("Select a valid Purchase Invoice."))
    if not frappe.has_permission("Purchase Invoice", "read", invoice_name):
        frappe.throw(_("You are not permitted to read Purchase Invoice {0}.").format(frappe.bold(invoice_name)), frappe.PermissionError)

    requested_fields = [
        "name", "company", "supplier", "supplier_name", "docstatus", "status",
        "posting_date", "due_date", "currency", "grand_total", "rounded_total",
        "outstanding_amount", "custom_payment_classification",
        "custom_expected_claim_period_from", "custom_expected_claim_period_to",
    ]
    fields = _safe_fields("Purchase Invoice", requested_fields)
    # docstatus is a standard Frappe column, not a DocField returned by meta.
    # Include it explicitly so Submitted/Cancelled invoices do not appear as Draft.
    if "docstatus" not in fields:
        fields.append("docstatus")
    invoice = frappe.db.get_value("Purchase Invoice", invoice_name, fields, as_dict=True) or frappe._dict()
    classification = invoice.get("custom_payment_classification") or ""
    outstanding = flt(invoice.get("outstanding_amount"), 2)
    grand_total = flt(invoice.get("rounded_total") or invoice.get("grand_total"), 2)
    paid_amount = max(0.0, flt(grand_total - outstanding, 2))

    linked_claim = _purchase_invoice_linked_supplier_claim(invoice_name)
    linked_claim_status = ""
    linked_claim_docstatus = None
    if linked_claim and frappe.db.exists("Supplier Claim", linked_claim):
        claim_values = frappe.db.get_value("Supplier Claim", linked_claim, ["status", "docstatus"], as_dict=True) or frappe._dict()
        linked_claim_status = claim_values.get("status") or ""
        linked_claim_docstatus = cint(claim_values.get("docstatus"))

    advances = []
    can_read_advances = bool(frappe.has_permission("Payment Entry", "read"))
    if can_read_advances and invoice.get("company") and invoice.get("supplier"):
        rows = frappe.get_all(
            "Payment Entry",
            filters={
                "company": invoice.company,
                "party_type": "Supplier",
                "party": invoice.supplier,
                "docstatus": 1,
                "payment_type": "Pay",
                "unallocated_amount": [">", 0.005],
            },
            fields=[
                "name", "posting_date", "mode_of_payment", "paid_from",
                "paid_amount", "unallocated_amount", "reference_no",
            ],
            order_by="posting_date asc, creation asc",
            limit_page_length=100,
        )
        advances = [
            {
                "payment_entry": row.name,
                "posting_date": row.posting_date,
                "mode_of_payment": row.mode_of_payment or "",
                "paid_from": row.paid_from or "",
                "paid_amount": flt(row.paid_amount, 2),
                "unallocated_amount": flt(row.unallocated_amount, 2),
                "reference_no": row.reference_no or "",
            }
            for row in rows
        ]

    if cint(invoice.get("docstatus")) == 0:
        settlement_status = "Draft"
    elif cint(invoice.get("docstatus")) == 2:
        settlement_status = "Cancelled"
    elif outstanding <= 0.005:
        settlement_status = "Paid"
    elif linked_claim:
        settlement_status = "Allocated to Claim"
    elif paid_amount > 0.005:
        settlement_status = "Partly Paid"
    else:
        settlement_status = "Unpaid"

    submitted_open = cint(invoice.get("docstatus")) == 1 and outstanding > 0.005
    claim_invoice = classification == "Claim Invoice"
    can_create_payment = bool(
        submitted_open
        and not claim_invoice
        and frappe.has_permission("Payment Entry", "create")
    )
    can_create_claim = bool(
        submitted_open
        and claim_invoice
        and not linked_claim
        and frappe.db.exists("DocType", "Supplier Claim")
        and frappe.has_permission("Supplier Claim", "create")
    )
    can_use_advance = bool(
        submitted_open
        and advances
        and frappe.has_permission("Payment Entry", "write")
    )

    return {
        "invoice": invoice_name,
        "company": invoice.get("company") or "",
        "supplier": invoice.get("supplier") or "",
        "supplier_name": invoice.get("supplier_name") or invoice.get("supplier") or "",
        "docstatus": cint(invoice.get("docstatus")),
        "invoice_status": invoice.get("status") or "",
        "settlement_status": settlement_status,
        "classification": classification,
        "posting_date": invoice.get("posting_date"),
        "due_date": invoice.get("due_date"),
        "currency": invoice.get("currency") or frappe.db.get_value("Company", invoice.get("company"), "default_currency") or "",
        "grand_total": grand_total,
        "outstanding_amount": outstanding,
        "paid_amount": paid_amount,
        "supplier_balance": flt(_supplier_balance(invoice.get("supplier"), invoice.get("company")), 2),
        "linked_supplier_claim": linked_claim,
        "linked_supplier_claim_status": linked_claim_status,
        "linked_supplier_claim_docstatus": linked_claim_docstatus,
        "expected_claim_period_from": invoice.get("custom_expected_claim_period_from"),
        "expected_claim_period_to": invoice.get("custom_expected_claim_period_to"),
        "unallocated_advances": advances,
        "unallocated_advance_total": flt(sum(flt(row.get("unallocated_amount")) for row in advances), 2),
        "actions": {
            "create_payment_draft": can_create_payment,
            "create_claim_draft": can_create_claim,
            "use_existing_advance": can_use_advance,
            "open_supplier_account": bool(invoice.get("supplier") and frappe.has_permission("Supplier", "read", invoice.get("supplier"))),
        },
        "draft_only_actions": 1,
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
            "custom_supplier_settlement_policy",
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
    settlement_policy = (data.get("custom_supplier_settlement_policy") or "").strip()
    if not settlement_policy:
        if payment_model == "Cash":
            settlement_policy = "Cash Per Invoice"
        elif payment_model == "Mixed":
            settlement_policy = "Mixed Cash + Claim"
        elif payment_model == "Credit Claim" or (supplier_type == "Distribution Company" and payment_model != "Mixed"):
            settlement_policy = "Claim Only"
        else:
            settlement_policy = ""
    classification = {
        "Cash Per Invoice": "Cash Invoice",
        "Claim Only": "Claim Invoice",
        "Mixed Cash + Claim": "Claim Invoice",
        "Credit Outside Claim": "Credit Invoice Outside Claim",
    }.get(settlement_policy, "")

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
        "supplier_settlement_policy": settlement_policy,
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


def _template_has_one_tax_account(template_name: str | None, company: str | None = None) -> bool:
    if not template_name or not frappe.db.exists("Item Tax Template", template_name):
        return False
    template_company = frappe.db.get_value("Item Tax Template", template_name, "company")
    if company and template_company and template_company != company:
        return False
    return len(_item_tax_accounts(template_name)) == 1


def _is_vat_labelled_item_tax_template(template_name: str) -> bool:
    accounts = [row.get("account") or "" for row in _item_tax_accounts(template_name)]
    label = " ".join([template_name or "", *accounts])
    return bool(re.search(r"(^|[^a-z])vat([^a-z]|$)|value\s*added|ضريبة\s*القيمة", label, re.IGNORECASE))


def _resolve_tax_template_for_row(row: frappe._dict, company: str | None = None) -> str | None:
    current = (row.get("item_tax_template") or "").strip()
    if current and _template_has_one_tax_account(current, company):
        return current
    mode = row.get("tax_entry_mode") or "No VAT"
    if mode == "No VAT" or cint(row.get("is_bonus")):
        return current or None

    item_default = _default_item_tax_template(row.get("item_code"), company)
    if _template_has_one_tax_account(item_default, company):
        return item_default

    filters = {"disabled": 0}
    if company:
        filters["company"] = company
    names = frappe.get_all(
        "Item Tax Template",
        filters=filters,
        pluck="name",
        order_by="name asc",
        limit_page_length=500,
    )
    candidates = [name for name in names if _template_has_one_tax_account(name, company)]
    target_rate = max(0.0, flt(row.get("vat_rate")))
    if target_rate:
        matching = [name for name in candidates if abs(_item_tax_template_rate(name) - target_rate) < 0.0001]
        if len(matching) == 1:
            return matching[0]

    # Manual VAT is allowed to differ from the configured percentage. In that
    # case the template identifies only the VAT accounting account. Prefer the
    # single template explicitly labelled as VAT, without changing the entered
    # VAT Per Unit or Total VAT for Line.
    has_manual_amount = flt(row.get("vat_per_unit")) > 0 or flt(row.get("total_vat")) > 0
    if mode in ("VAT Per Unit", "Total VAT for Line") and has_manual_amount:
        labelled = [name for name in candidates if _is_vat_labelled_item_tax_template(name)]
        if len(labelled) == 1:
            return labelled[0]

    return candidates[0] if len(candidates) == 1 else None


def _normalize_tax_templates(payload: frappe._dict) -> None:
    company = payload.get("company")
    for source in payload.get("items") or []:
        row = frappe._dict(source)
        if (row.get("tax_entry_mode") or "No VAT") == "No VAT" or cint(row.get("is_bonus")):
            continue
        if row.get("item_tax_template"):
            continue
        resolved = _resolve_tax_template_for_row(row, company)
        if not resolved:
            frappe.throw(
                _("Select an Item Tax Template to identify the VAT account for item {0}. The manually entered VAT amount will not be recalculated.").format(
                    frappe.bold(row.get("item_code") or "")
                )
            )
        source["item_tax_template"] = resolved


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

def _append_bonus_vat_charges(doc, payload: frappe._dict) -> float:
    """Post VAT payable on free bonus quantities as an explicit tax charge.

    The bonus item itself must stay free in ERPNext (rate/amount = 0). Its
    operational VAT Per Unit and Total VAT are retained in the custom item
    fields, while this tax row carries the payable amount to the configured VAT
    account and therefore into the official invoice total / GL on submit.
    """
    company = payload.get("company") or doc.get("company")
    source_rows = [frappe._dict(source) for source in (payload.get("items") or [])]
    item_templates: dict[str, str] = {}
    for row in source_rows:
        if cint(row.get("is_bonus")):
            continue
        template = (row.get("item_tax_template") or "").strip()
        if row.get("item_code") and template:
            item_templates[row.get("item_code")] = template

    amounts_by_account: dict[str, float] = {}
    for row in source_rows:
        if not cint(row.get("is_bonus")):
            continue
        if (row.get("tax_entry_mode") or "No VAT") == "No VAT":
            continue

        calc = _calculate_row(row, 1)
        bonus_vat = max(0.0, flt(calc.total_vat))
        if not bonus_vat:
            continue

        template = (row.get("item_tax_template") or "").strip()
        if not template:
            template = item_templates.get(row.get("item_code")) or ""
        if not template:
            lookup_row = frappe._dict(dict(row))
            lookup_row.is_bonus = 0
            template = _resolve_tax_template_for_row(lookup_row, company) or ""

        accounts = _item_tax_accounts(template)
        if len(accounts) != 1:
            frappe.throw(
                _("Bonus VAT requires one Item Tax Template account for item {0}.").format(
                    frappe.bold(row.get("item_code") or "")
                )
            )
        account = accounts[0].get("account")
        amounts_by_account[account] = flt(amounts_by_account.get(account)) + bonus_vat

    precision = _currency_precision(doc)
    total = 0.0
    for account, raw_amount in amounts_by_account.items():
        amount = flt(raw_amount, precision)
        if not amount:
            continue
        doc.append(
            "taxes",
            {
                "charge_type": "Actual",
                "account_head": account,
                "description": _("Bonus Item VAT"),
                "rate": 0,
                "tax_amount": amount,
                "included_in_print_rate": 0,
                "add_deduct_tax": "Add",
                "category": "Total",
            },
        )
        total += amount
    return flt(total, precision)


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
        # v0.7.61.2: bonus VAT uses the inherited VAT Per Unit.
        # Total VAT for Line belongs to the purchased row; for a bonus row the
        # unit cost is the already-calculated VAT Per Unit copied from that row.
        if mode in ("VAT Per Unit", "Total VAT for Line"):
            vat_per_unit = max(0.0, flt(row.get("vat_per_unit")))
        elif mode == "Auto by VAT %":
            vat_per_unit = taxable_base * vat_rate / 100.0
        else:
            vat_per_unit = 0.0
        total_vat = vat_per_unit * qty
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
    # Bonus goods remain zero-value ERP item rows. Any VAT payable on those
    # free units is posted separately to the VAT account by
    # _append_bonus_vat_charges(), while the custom fields retain the
    # operational VAT-per-unit display used by Purchase Management.
    standard_rate = 0.0 if is_bonus else flt(calc.final_rate)
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
        "is_free_item":bool(is_bonus),"allow_zero_valuation_rate":bool(is_bonus),
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
    invoice_item_fields = _doc_fieldnames("Purchase Invoice Item")
    source_links = {
        "purchase_order": row.get("purchase_order") or None,
        "po_detail": row.get("purchase_order_item") or row.get("po_detail") or None,
        "purchase_receipt": row.get("purchase_receipt") or None,
        "pr_detail": row.get("purchase_receipt_item") or row.get("pr_detail") or None,
        "material_request": row.get("material_request") or None,
        "material_request_item": row.get("material_request_item") or None,
    }
    for key, value in source_links.items():
        if value and key in invoice_item_fields:
            values[key] = value
    return values

def _disable_purchase_invoice_rounded_total(doc) -> None:
    """Keep the supplier payable/outstanding equal to the exact invoice total.

    ERPNext can round the payable to the nearest whole currency unit through
    ``rounded_total``. Supplier invoices entered from this page must instead
    preserve the exact supplier document amount (for example 1,469.71), while
    any permitted supplier fraction difference remains an explicit tax row.
    """
    if doc.meta.has_field("disable_rounded_total"):
        doc.disable_rounded_total = 1


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
        "retail_price_review_status": doc.get("custom_retail_price_review_status") or "",
        "retail_price_change_count": cint(doc.get("custom_price_change_count")),
        "price_reviewed_by": doc.get("custom_price_reviewed_by") or "",
        "price_reviewed_at": doc.get("custom_price_reviewed_at"),
        "route": f"/app/purchase-invoice/{doc.name}",
    }



def _purchase_page_additional_charge(doc) -> dict:
    # v0.7.61.2: system-generated Actual tax rows are not shipping charges.
    # Bonus Item VAT is posted as an official Actual tax row for accounting,
    # but must never be loaded back into the page's Shipping / Additional
    # Charges controls; otherwise it is appended a second time on re-save or
    # submit and creates an artificial difference equal to the bonus VAT.
    ignored_descriptions = {
        _("Supplier Invoice Fraction Adjustment"),
        "Supplier Invoice Fraction Adjustment",
        _("Bonus Item VAT"),
        "Bonus Item VAT",
    }
    ignored_normalized = {
        str(description or "").strip().casefold()
        for description in ignored_descriptions
        if description
    }

    for tax in doc.get("taxes") or []:
        if tax.charge_type != "Actual":
            continue
        description = (tax.description or "").strip()
        if description.casefold() in ignored_normalized:
            continue
        return {
            "account": tax.account_head or "",
            "amount": flt(tax.tax_amount),
            "description": description,
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
        "purchase_order": row.get("purchase_order") or "",
        "purchase_order_item": row.get("po_detail") or row.get("purchase_order_item") or "",
        "purchase_receipt": row.get("purchase_receipt") or "",
        "purchase_receipt_item": row.get("pr_detail") or row.get("purchase_receipt_item") or "",
        "material_request": row.get("material_request") or "",
        "material_request_item": row.get("material_request_item") or "",
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
    return {
        "invoice": _invoice_response(doc),
        "payload": _purchase_invoice_page_payload(doc),
        "procurement_links": _procurement_linked_documents("purchase_invoice", doc.name),
        "read_only": cint(doc.docstatus) != 0,
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
    _enrich_procurement_items_from_latest_link(payload)
    _normalize_tax_templates(payload)
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

    _disable_purchase_invoice_rounded_total(doc)
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
    is_receipt_backed = _purchase_invoice_has_linked_receipt(payload=payload, doc=doc)
    doc.update_stock = 0 if is_receipt_backed else 1
    doc.set_warehouse = payload.get("warehouse")
    doc.buying_price_list = payload.get("buying_price_list") or _default_buying_price_list()

    if doc.meta.has_field("custom_purchase_entry_mode"):
        doc.custom_purchase_entry_mode = (
            "Against Purchase Order" if is_receipt_backed else "Quick Invoice & Receipt"
        )
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
    _append_bonus_vat_charges(doc, payload)
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

    # Re-evaluate after all invoice rows and official receipt links are populated.
    is_receipt_backed = _purchase_invoice_has_linked_receipt(payload=payload, doc=doc)
    doc.update_stock = 0 if is_receipt_backed else 1
    if doc.meta.has_field("custom_purchase_entry_mode"):
        doc.custom_purchase_entry_mode = (
            "Against Purchase Order" if is_receipt_backed else "Quick Invoice & Receipt"
        )

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
    # Purchase-risk confirmation applies only when receiving/purchasing stock.
    # A Purchase Return / Debit Note removes stock and must not be blocked by
    # expiry or purchase-risk confirmation rules from the original purchase.
    if cint(doc.get("is_return")):
        return

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



def _require_document_create_access(doctype: str, label: str | None = None) -> None:
    _require_read_access()
    if not frappe.db.exists("DocType", doctype):
        frappe.throw(_("{0} is not available on this site.").format(label or doctype))
    if not frappe.has_permission(doctype, "create"):
        frappe.throw(
            _("You are not permitted to create {0}.").format(label or doctype),
            frappe.PermissionError,
        )


def _doc_fieldnames(doctype: str) -> set[str]:
    return _meta_fieldnames(doctype)


def _child_values(doctype: str, values: dict[str, Any]) -> dict[str, Any]:
    available = _doc_fieldnames(doctype)
    return {key: value for key, value in values.items() if key in available}


def _payload_procurement_links(payload: frappe._dict) -> frappe._dict:
    links = payload.get("procurement_links") or {}
    if isinstance(links, str):
        try:
            links = frappe.parse_json(links)
        except Exception:
            links = {}
    return frappe._dict(links if isinstance(links, dict) else {})


def _linked_source_name(payload: frappe._dict, source_type: str) -> str:
    key_by_type = {
        "purchase_request": "purchase_request",
        "purchase_order": "purchase_order",
        "purchase_receipt": "purchase_receipt",
    }
    key = key_by_type.get(source_type)
    if not key:
        return ""
    links = _payload_procurement_links(payload)
    return str(links.get(key) or payload.get(key) or "").strip()


def _source_row_quantity(row) -> float:
    for fieldname in ("qty", "received_qty", "accepted_qty", "stock_qty"):
        value = row.get(fieldname)
        if value not in (None, ""):
            return abs(flt(value))
    return 0.0


def _enrich_procurement_items_from_linked_source(payload: frappe._dict, source_type: str) -> bool:
    """Attach official ERPNext parent/child references before creating the next draft.

    Operators may create Request -> Order -> Receipt -> Invoice directly from the same
    page without reloading each document. In that flow the visible rows originally come
    from the page, so they do not yet contain the child-row names assigned by ERPNext.
    This helper resolves the latest linked draft and safely maps matching item rows back
    to its official children before building the downstream document.
    """
    source_name = _linked_source_name(payload, source_type)
    source_doctype_by_type = {
        "purchase_request": "Material Request",
        "purchase_order": "Purchase Order",
        "purchase_receipt": "Purchase Receipt",
    }
    source_doctype = source_doctype_by_type.get(source_type)
    if not source_doctype or not source_name or not frappe.db.exists(source_doctype, source_name):
        return False

    source_doc = frappe.get_doc(source_doctype, source_name)
    source_rows = [row for row in (source_doc.get("items") or []) if row.get("item_code")]
    if not source_rows:
        return False

    rows_by_item: dict[str, list[Any]] = {}
    rows_by_name: dict[str, Any] = {}
    for source_row in source_rows:
        rows_by_item.setdefault(source_row.get("item_code"), []).append(source_row)
        if source_row.get("name"):
            rows_by_name[source_row.get("name")] = source_row

    assigned_qty: dict[str, float] = {}
    enriched_items = []
    changed = False

    for raw in payload.get("items") or []:
        row = frappe._dict(dict(raw))
        item_code = row.get("item_code")
        row_qty = abs(flt(row.get("qty")))

        if source_type == "purchase_request":
            parent_field = "material_request"
            detail_field = "material_request_item"
        elif source_type == "purchase_order":
            parent_field = "purchase_order"
            detail_field = "purchase_order_item"
        else:
            parent_field = "purchase_receipt"
            detail_field = "purchase_receipt_item"

        candidate = None
        existing_detail = row.get(detail_field) or row.get("source_detail")
        if existing_detail and existing_detail in rows_by_name:
            possible = rows_by_name[existing_detail]
            if not item_code or possible.get("item_code") == item_code:
                candidate = possible

        if candidate is None and item_code:
            candidates = rows_by_item.get(item_code) or []
            if candidates:
                candidate = next(
                    (
                        source_row
                        for source_row in candidates
                        if _source_row_quantity(source_row)
                        - assigned_qty.get(source_row.get("name") or "", 0.0)
                        + 0.000001
                        >= row_qty
                    ),
                    candidates[0],
                )

        if candidate is not None:
            candidate_name = candidate.get("name") or ""
            row[parent_field] = source_name
            row[detail_field] = candidate_name
            row["source_doctype"] = source_doctype
            row["source_name"] = source_name
            row["source_detail"] = candidate_name

            if source_type == "purchase_order":
                row["material_request"] = candidate.get("material_request") or row.get("material_request") or ""
                row["material_request_item"] = candidate.get("material_request_item") or row.get("material_request_item") or ""
            elif source_type == "purchase_receipt":
                row["purchase_order"] = candidate.get("purchase_order") or row.get("purchase_order") or ""
                row["purchase_order_item"] = (
                    candidate.get("purchase_order_item")
                    or candidate.get("po_detail")
                    or row.get("purchase_order_item")
                    or row.get("po_detail")
                    or ""
                )
                row["material_request"] = candidate.get("material_request") or row.get("material_request") or ""
                row["material_request_item"] = candidate.get("material_request_item") or row.get("material_request_item") or ""

            assigned_qty[candidate_name] = assigned_qty.get(candidate_name, 0.0) + row_qty
            changed = True

        enriched_items.append(row)

    payload["items"] = enriched_items
    return changed


def _enrich_procurement_items_from_latest_link(payload: frappe._dict) -> bool:
    for source_type in ("purchase_receipt", "purchase_order", "purchase_request"):
        if _linked_source_name(payload, source_type):
            return _enrich_procurement_items_from_linked_source(payload, source_type)
    return False



def _purchase_invoice_has_linked_receipt(payload: frappe._dict | None = None, doc=None) -> bool:
    # Return True when a Purchase Invoice is backed by an official Purchase Receipt.
    # A Purchase Receipt already posts the stock ledger. Any Purchase Invoice linked
    # to it must keep update_stock disabled, including drafts re-opened and saved here.
    if payload is not None:
        payload = frappe._dict(payload)
        if _linked_source_name(payload, "purchase_receipt"):
            return True

        for raw in payload.get("items") or []:
            row = frappe._dict(raw)
            if (
                row.get("purchase_receipt")
                or row.get("purchase_receipt_item")
                or row.get("pr_detail")
            ):
                return True

    if doc is not None:
        for row in doc.get("items") or []:
            if (
                row.get("purchase_receipt")
                or row.get("purchase_receipt_item")
                or row.get("pr_detail")
            ):
                return True

        if getattr(doc, "name", None) and not getattr(doc, "is_new", lambda: False)():
            try:
                linked = _procurement_linked_documents("purchase_invoice", doc.name)
                if linked.get("purchase_receipt"):
                    return True
            except Exception:
                # Official child-row references above remain the primary check.
                pass

    return False


def _procurement_schedule_date(payload: frappe._dict):
    return (
        _parse_flexible_date(payload.get("required_by_date") or payload.get("due_date"), _("Required By"))
        or _parse_flexible_date(payload.get("posting_date"), _("Posting Date"))
        or getdate(nowdate())
    )


def _validate_procurement_payload(payload: frappe._dict, *, require_supplier: bool = True) -> None:
    if not payload.get("company") or not frappe.db.exists("Company", payload.get("company")):
        frappe.throw(_("Select a valid company."))
    if require_supplier and (not payload.get("supplier") or not frappe.db.exists("Supplier", payload.get("supplier"))):
        frappe.throw(_("Select a valid supplier."))
    if not payload.get("warehouse") or not frappe.db.exists("Warehouse", payload.get("warehouse")):
        frappe.throw(_("Select a valid receiving warehouse."))
    warehouse_company = frappe.db.get_value("Warehouse", payload.get("warehouse"), "company")
    if warehouse_company and warehouse_company != payload.get("company"):
        frappe.throw(_("The selected warehouse belongs to another company."))
    if not (payload.get("items") or []):
        frappe.throw(_("Add at least one purchase item."))


def _procurement_item_base(row: frappe._dict, default_warehouse: str) -> frappe._dict:
    item_code = row.get("item_code")
    if not item_code or not frappe.db.exists("Item", item_code):
        frappe.throw(_("Invalid item in purchase rows."))
    item = frappe.db.get_value(
        "Item",
        item_code,
        ["item_name", "description", "stock_uom", "purchase_uom", "disabled", "is_purchase_item"],
        as_dict=True,
    ) or frappe._dict()
    if cint(item.get("disabled")) or not cint(item.get("is_purchase_item", 1)):
        frappe.throw(_("Item {0} cannot be purchased.").format(frappe.bold(item_code)))
    qty = flt(row.get("qty"))
    if qty <= 0:
        frappe.throw(_("Quantity must be greater than zero for item {0}.").format(item_code))
    uom = row.get("uom") or item.get("purchase_uom") or item.get("stock_uom")
    conversion_factor = flt(row.get("conversion_factor")) or _uom_conversion_factor(item_code, uom, item.get("stock_uom"))
    return frappe._dict(
        item_code=item_code,
        item_name=item.get("item_name") or item_code,
        description=item.get("description") or item.get("item_name") or item_code,
        stock_uom=item.get("stock_uom"),
        uom=uom,
        qty=qty,
        conversion_factor=conversion_factor,
        warehouse=row.get("warehouse") or default_warehouse,
    )


def _build_material_request_item(row: frappe._dict, default_warehouse: str, schedule_date) -> dict[str, Any]:
    base = _procurement_item_base(row, default_warehouse)
    values = {
        "item_code": base.item_code,
        "item_name": base.item_name,
        "description": base.description,
        "qty": base.qty,
        "stock_qty": base.qty * base.conversion_factor,
        "uom": base.uom,
        "stock_uom": base.stock_uom,
        "conversion_factor": base.conversion_factor,
        "warehouse": base.warehouse,
        "schedule_date": schedule_date,
    }
    return _child_values("Material Request Item", values)


def _build_purchase_order_item(row: frappe._dict, default_warehouse: str, schedule_date) -> dict[str, Any]:
    base = _procurement_item_base(row, default_warehouse)
    calc = _calculate_row(row, 1)
    rate = flt(calc.final_rate)
    values = {
        "item_code": base.item_code,
        "item_name": base.item_name,
        "description": base.description,
        "qty": base.qty,
        "stock_qty": base.qty * base.conversion_factor,
        "uom": base.uom,
        "stock_uom": base.stock_uom,
        "conversion_factor": base.conversion_factor,
        "warehouse": base.warehouse,
        "schedule_date": schedule_date,
        "price_list_rate": rate,
        "rate": rate,
        "base_rate": rate,
        "amount": base.qty * rate,
        "base_amount": base.qty * rate,
        "discount_percentage": 0,
        "discount_amount": 0,
        "item_tax_template": row.get("item_tax_template") or None,
        "material_request": row.get("material_request") or None,
        "material_request_item": row.get("material_request_item") or None,
    }
    return _child_values("Purchase Order Item", values)



def _build_purchase_receipt_item(row: frappe._dict, default_warehouse: str) -> dict[str, Any]:
    base = _procurement_item_base(row, default_warehouse)
    calc = _calculate_row(row, 1)
    rate = flt(calc.final_rate)
    is_bonus = cint(row.get("is_bonus"))
    taxable_bonus = bool(is_bonus and rate > 0)
    parsed_expiry = _parse_flexible_date(row.get("expiry_date"), _("Expiry Date")) if row.get("expiry_date") else None
    values = {
        "item_code": base.item_code,
        "item_name": base.item_name,
        "description": base.description,
        "qty": base.qty,
        "received_qty": base.qty,
        "stock_qty": base.qty * base.conversion_factor,
        "uom": base.uom,
        "stock_uom": base.stock_uom,
        "conversion_factor": base.conversion_factor,
        "warehouse": base.warehouse,
        "price_list_rate": rate,
        "rate": rate,
        "base_rate": rate,
        "amount": base.qty * rate,
        "base_amount": base.qty * rate,
        "discount_percentage": 0,
        "discount_amount": 0,
        "item_tax_template": row.get("item_tax_template") or None,
        "batch_no": (row.get("batch_no") or "").strip(),
        "expiry_date": parsed_expiry,
        "is_free_item": bool(is_bonus and not taxable_bonus),
        "allow_zero_valuation_rate": bool(is_bonus and not taxable_bonus),
        "custom_selling_price": calc.customer_price,
        "custom_customer_base_before_vat": calc.customer_base_before_vat,
        "custom_supplier_base_price": calc.supplier_base,
        "custom_purchase_pricing_method": row.get("pricing_method") or "Discount From Customer Price",
        "custom_manual_net_rate": calc.final_rate,
        "custom_supplier_discount_percentage": 100 if is_bonus else calc.supplier_discount,
        "custom_additional_discount": 0 if is_bonus else calc.additional_discount,
        "custom_effective_discount_percentage": calc.effective_discount,
        "custom_tax_entry_mode": row.get("tax_entry_mode") or "No VAT",
        "custom_vat_inclusive_in_final_rate": cint(row.get("vat_inclusive")),
        "custom_vat_rate": calc.vat_rate,
        "custom_entered_net_before_vat": calc.entered_net_before_vat,
        "custom_net_before_vat": calc.net_before_vat,
        "custom_vat_per_unit": calc.vat_per_unit,
        "custom_total_vat_amount": calc.total_vat,
        "custom_is_bonus_item": is_bonus,
        "custom_batch_number": (row.get("batch_no") or "").strip(),
        "custom_expiry_date": parsed_expiry,
        "custom_auto_batch_reason": row.get("auto_batch_reason"),
        "purchase_order": row.get("purchase_order") or None,
        "purchase_order_item": row.get("purchase_order_item") or row.get("po_detail") or None,
        "material_request": row.get("material_request") or None,
        "material_request_item": row.get("material_request_item") or None,
    }
    return _child_values("Purchase Receipt Item", values)


def _procurement_response(doc) -> dict[str, Any]:
    route_doctype = doc.doctype.lower().replace(" ", "-")
    return {
        "doctype": doc.doctype,
        "name": doc.name,
        "docstatus": doc.docstatus,
        "status": doc.get("status") or "Draft",
        "supplier": doc.get("supplier") or "",
        "transaction_date": doc.get("transaction_date") or doc.get("posting_date"),
        "grand_total": flt(doc.get("grand_total")),
        "items_count": len(doc.get("items") or []),
        "route": f"/app/{route_doctype}/{doc.name}",
    }


def _match_first_number(row, candidates: list[str]) -> float:
    for fieldname in candidates:
        value = row.get(fieldname)
        if value is not None:
            return flt(value)
    return 0.0


def _match_item_bucket(item_map: dict[str, dict[str, Any]], item_code: str, item_name: str | None = None) -> dict[str, Any]:
    if not item_code:
        item_code = "__missing_item__"
    if item_code not in item_map:
        item_map[item_code] = {
            "item_code": item_code,
            "item_name": item_name or item_code,
            "requested_qty": 0.0,
            "ordered_qty": 0.0,
            "received_qty": 0.0,
            "invoiced_qty": 0.0,
            "requested_amount": 0.0,
            "ordered_amount": 0.0,
            "received_amount": 0.0,
            "invoiced_amount": 0.0,
        }
    elif item_name and not item_map[item_code].get("item_name"):
        item_map[item_code]["item_name"] = item_name
    return item_map[item_code]


def _match_add_doc_items(item_map: dict[str, dict[str, Any]], doc, kind: str) -> None:
    qty_fields = {
        "purchase_request": ["qty", "stock_qty"],
        "purchase_order": ["qty", "stock_qty"],
        "purchase_receipt": ["qty", "received_qty", "accepted_qty", "stock_qty"],
        "purchase_invoice": ["qty", "stock_qty"],
    }
    qty_key = {
        "purchase_request": "requested_qty",
        "purchase_order": "ordered_qty",
        "purchase_receipt": "received_qty",
        "purchase_invoice": "invoiced_qty",
    }[kind]
    amount_key = {
        "purchase_request": "requested_amount",
        "purchase_order": "ordered_amount",
        "purchase_receipt": "received_amount",
        "purchase_invoice": "invoiced_amount",
    }[kind]

    for row in doc.get("items") or []:
        item_code = row.get("item_code") or row.get("item") or ""
        bucket = _match_item_bucket(item_map, item_code, row.get("item_name"))
        qty = _match_first_number(row, qty_fields[kind])
        amount = flt(row.get("amount") or row.get("base_amount"))
        if not amount:
            amount = qty * flt(row.get("rate") or row.get("base_rate"))
        bucket[qty_key] += qty
        bucket[amount_key] += amount


def _match_doc_summary(doc) -> dict[str, Any]:
    return {
        "doctype": doc.doctype,
        "name": doc.name,
        "docstatus": cint(doc.docstatus),
        "status": doc.get("status") or ("Draft" if cint(doc.docstatus) == 0 else "Submitted"),
        "supplier": doc.get("supplier") or "",
        "posting_date": doc.get("posting_date") or doc.get("transaction_date") or doc.get("schedule_date"),
        "total_qty": flt(doc.get("total_qty") or sum(flt(row.get("qty")) for row in (doc.get("items") or []))),
        "grand_total": flt(doc.get("grand_total") or doc.get("rounded_total") or doc.get("net_total") or 0),
        "items_count": len(doc.get("items") or []),
        "route": f"/app/{doc.doctype.lower().replace(' ', '-')}/{doc.name}",
    }


@frappe.whitelist()
def get_procurement_match_preview(links):
    """Return a lightweight procurement match preview for linked PR/PO/Receipt/Invoice drafts.

    This is a read-only foundation for Three-Way Match. It does not submit or modify any
    official ERPNext document.
    """
    _require_read_access()
    links = _parse_payload(links or {})

    requested = {
        "purchase_request": ("Material Request", links.get("purchase_request") or links.get("material_request")),
        "purchase_order": ("Purchase Order", links.get("purchase_order")),
        "purchase_receipt": ("Purchase Receipt", links.get("purchase_receipt")),
        "purchase_invoice": ("Purchase Invoice", links.get("purchase_invoice")),
    }

    docs = {}
    missing = []
    for kind, (doctype, name) in requested.items():
        if not name:
            continue
        if not frappe.has_permission(doctype, "read"):
            missing.append({"kind": kind, "doctype": doctype, "name": name, "reason": "no_permission"})
            continue
        if not frappe.db.exists(doctype, name):
            missing.append({"kind": kind, "doctype": doctype, "name": name, "reason": "not_found"})
            continue
        docs[kind] = frappe.get_doc(doctype, name)

    item_map: dict[str, dict[str, Any]] = {}
    for kind, doc in docs.items():
        _match_add_doc_items(item_map, doc, kind)

    rows = []
    all_issues = []
    qty_tolerance = 0.0001
    amount_tolerance = 0.01
    rate_tolerance = 0.01

    def add_issue(issues, code: str, severity: str, message: str) -> None:
        issues.append({"code": code, "severity": severity, "message": message})

    for item_code, bucket in sorted(item_map.items(), key=lambda item: item[0]):
        ordered_qty = flt(bucket.get("ordered_qty"))
        received_qty = flt(bucket.get("received_qty"))
        invoiced_qty = flt(bucket.get("invoiced_qty"))
        ordered_amount = flt(bucket.get("ordered_amount"))
        received_amount = flt(bucket.get("received_amount"))
        invoiced_amount = flt(bucket.get("invoiced_amount"))
        ordered_rate = ordered_amount / ordered_qty if ordered_qty else 0.0
        received_rate = received_amount / received_qty if received_qty else 0.0
        invoiced_rate = invoiced_amount / invoiced_qty if invoiced_qty else 0.0
        issues = []

        if ordered_qty <= qty_tolerance and received_qty > qty_tolerance:
            add_issue(issues, "received_without_po", "warning", "Received item is not present in the Purchase Order. If this is an actual supplier line, receive/invoice it as-is, then handle return/credit note if needed.")
        if ordered_qty <= qty_tolerance and invoiced_qty > qty_tolerance:
            add_issue(issues, "invoice_item_not_in_po", "warning", "Invoice item is not present in the Purchase Order. Enter supplier invoice as received; use Supplier Return/Credit Note if the item was sent by mistake.")
        if ordered_qty > qty_tolerance and received_qty <= qty_tolerance:
            add_issue(issues, "ordered_not_received", "warning", "Ordered item has not been received yet.")
        if ordered_qty > qty_tolerance and received_qty > qty_tolerance and received_qty < ordered_qty - qty_tolerance:
            add_issue(issues, "received_less_than_ordered", "warning", "Received quantity is less than ordered quantity.")
        if received_qty > qty_tolerance and invoiced_qty > received_qty + qty_tolerance:
            add_issue(issues, "invoice_quantity_higher_than_received", "mismatch", "Invoice quantity is higher than received quantity.")
        if received_qty > qty_tolerance and invoiced_qty < received_qty - qty_tolerance:
            add_issue(issues, "invoice_quantity_lower_than_received", "warning", "Invoice quantity is lower than received quantity.")
        if ordered_qty > qty_tolerance and invoiced_qty > qty_tolerance and abs(invoiced_rate - ordered_rate) > rate_tolerance:
            add_issue(issues, "invoice_rate_differs_from_po", "warning", "Invoice rate differs from Purchase Order rate.")
        if ordered_qty > qty_tolerance and invoiced_qty > qty_tolerance and abs(invoiced_amount - ordered_amount) > amount_tolerance:
            add_issue(issues, "invoice_amount_differs_from_po", "warning", "Invoice amount differs from Purchase Order amount.")

        if any(issue.get("severity") == "mismatch" for issue in issues):
            status = "mismatch"
        elif issues:
            status = "warning"
        else:
            status = "matched"

        bucket["ordered_rate"] = ordered_rate
        bucket["received_rate"] = received_rate
        bucket["invoiced_rate"] = invoiced_rate
        bucket["ordered_vs_received_qty"] = ordered_qty - received_qty
        bucket["received_vs_invoiced_qty"] = received_qty - invoiced_qty
        bucket["ordered_vs_invoiced_amount"] = ordered_amount - invoiced_amount
        bucket["status"] = status
        bucket["issues"] = issues
        bucket["issues_text"] = "; ".join(issue.get("message") for issue in issues)
        rows.append(bucket)
        for issue in issues:
            enriched_issue = dict(issue)
            enriched_issue["item_code"] = bucket.get("item_code")
            enriched_issue["item_name"] = bucket.get("item_name")
            all_issues.append(enriched_issue)

    summary = {
        "requested_qty": sum(flt(row.get("requested_qty")) for row in rows),
        "ordered_qty": sum(flt(row.get("ordered_qty")) for row in rows),
        "received_qty": sum(flt(row.get("received_qty")) for row in rows),
        "invoiced_qty": sum(flt(row.get("invoiced_qty")) for row in rows),
        "ordered_amount": sum(flt(row.get("ordered_amount")) for row in rows),
        "received_amount": sum(flt(row.get("received_amount")) for row in rows),
        "invoiced_amount": sum(flt(row.get("invoiced_amount")) for row in rows),
        "rows_count": len(rows),
    }
    summary["ordered_vs_received_qty"] = summary["ordered_qty"] - summary["received_qty"]
    summary["received_vs_invoiced_qty"] = summary["received_qty"] - summary["invoiced_qty"]
    summary["ordered_vs_invoiced_amount"] = summary["ordered_amount"] - summary["invoiced_amount"]
    summary["issues_count"] = len(all_issues)
    summary["issues"] = all_issues
    if any(issue.get("severity") == "mismatch" for issue in all_issues):
        summary["match_status"] = "mismatch"
        summary["status_label"] = "Mismatch"
    elif all_issues or missing:
        summary["match_status"] = "warning"
        summary["status_label"] = "Warning"
    else:
        summary["match_status"] = "matched"
        summary["status_label"] = "Matched"

    return {
        "documents": {kind: _match_doc_summary(doc) for kind, doc in docs.items()},
        "missing": missing,
        "summary": summary,
        "rows": rows,
    }


_PROCUREMENT_SUMMARY_STAGE_CONFIG = {
    "purchase_request": {"doctype": "Material Request", "label": _("Request")},
    "purchase_order": {"doctype": "Purchase Order", "label": _("Order")},
    "purchase_receipt": {"doctype": "Purchase Receipt", "label": _("Receipt")},
    "purchase_invoice": {"doctype": "Purchase Invoice", "label": _("Invoice")},
}


def _procurement_document_warehouse(doc) -> str:
    warehouse = (
        doc.get("set_warehouse")
        or doc.get("warehouse")
        or doc.get("target_warehouse")
        or doc.get("from_warehouse")
    )
    if warehouse:
        return warehouse
    for row in doc.get("items") or []:
        warehouse = row.get("warehouse") or row.get("target_warehouse") or row.get("from_warehouse")
        if warehouse:
            return warehouse
    return ""


def _procurement_stage_document_summary(stage_key: str, doc) -> dict[str, Any]:
    total_qty = flt(doc.get("total_qty")) or sum(flt(row.get("qty")) for row in (doc.get("items") or []))
    used_qty = 0.0
    remaining_qty = total_qty

    if cint(doc.docstatus) == 2:
        operational_status = "cancelled"
        operational_status_label = _("Cancelled")
    elif stage_key == "purchase_invoice":
        operational_status = "done" if cint(doc.docstatus) == 1 else "open"
        operational_status_label = _("Submitted") if cint(doc.docstatus) == 1 else _("Open / Review & Submit")
    else:
        progress = _open_draft_downstream_progress(stage_key, [doc.name]).get(doc.name, {})
        used_qty = flt(progress.get("used_qty"))
        remaining_qty = max(total_qty - used_qty, 0.0)
        if total_qty > 0 and used_qty >= total_qty - 0.0001:
            operational_status = "done"
        elif used_qty > 0.0001:
            operational_status = "partial"
        else:
            operational_status = "open"
        operational_status_label = _open_draft_progress_label(stage_key, operational_status)

    supplier = doc.get("supplier") or ""
    supplier_name = doc.get("supplier_name") or supplier
    document_date = doc.get("posting_date") or doc.get("transaction_date") or doc.get("schedule_date")
    return {
        "stage": stage_key,
        "stage_label": _PROCUREMENT_SUMMARY_STAGE_CONFIG[stage_key]["label"],
        "doctype": doc.doctype,
        "name": doc.name,
        "docstatus": cint(doc.docstatus),
        "status": doc.get("status") or ("Draft" if cint(doc.docstatus) == 0 else "Submitted"),
        "operational_status": operational_status,
        "operational_status_label": operational_status_label,
        "supplier": supplier,
        "supplier_name": supplier_name,
        "date": document_date,
        "warehouse": _procurement_document_warehouse(doc),
        "items_count": len(doc.get("items") or []),
        "total_qty": total_qty,
        "used_qty": used_qty,
        "remaining_qty": remaining_qty,
        "grand_total": flt(doc.get("grand_total") or doc.get("rounded_total") or doc.get("net_total")),
        "route": f"/app/{doc.doctype.lower().replace(' ', '-')}/{doc.name}",
    }


def _plain_comment_value(content: str, label: str) -> str:
    pattern = rf"<b>\s*{re.escape(label)}\s*:\s*</b>\s*(.*?)</div>"
    match = re.search(pattern, content or "", flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    value = re.sub(r"<[^>]+>", " ", match.group(1))
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _latest_procurement_match_decision(invoice_name: str) -> dict[str, Any]:
    if not frappe.db.exists("DocType", "Comment"):
        return {}
    rows = frappe.get_all(
        "Comment",
        filters={
            "reference_doctype": "Purchase Invoice",
            "reference_name": invoice_name,
            "comment_type": "Comment",
        },
        fields=["content", "creation", "comment_by", "comment_email"],
        order_by="creation desc",
        limit_page_length=30,
    )
    for row in rows:
        content = row.get("content") or ""
        if "Procurement Match Decision" not in content:
            continue
        return {
            "status": _plain_comment_value(content, "Status"),
            "decision": _plain_comment_value(content, "Decision"),
            "reason": _plain_comment_value(content, "Reason"),
            "creation": row.get("creation"),
            "user": row.get("comment_by") or row.get("comment_email") or "",
        }
    return {}


def _purchase_invoice_operational_totals(doc) -> dict[str, Any]:
    normal_rows = [row for row in (doc.get("items") or []) if not cint(row.get("custom_is_bonus_item"))]
    bonus_rows = [row for row in (doc.get("items") or []) if cint(row.get("custom_is_bonus_item"))]

    supplier_invoice_gross = sum(
        flt(row.qty) * flt(row.get("custom_supplier_base_price") or row.get("price_list_rate"))
        for row in normal_rows
    )
    supplier_discount = sum(
        flt(row.qty)
        * flt(row.get("custom_supplier_base_price") or row.get("price_list_rate"))
        * max(0.0, min(100.0, flt(row.get("custom_supplier_discount_percentage"))))
        / 100.0
        for row in normal_rows
    )
    additional_line_discount = 0.0
    for row in normal_rows:
        supplier_price = flt(row.get("custom_supplier_base_price") or row.get("price_list_rate"))
        supplier_discount_pct = max(0.0, min(100.0, flt(row.get("custom_supplier_discount_percentage"))))
        additional_discount_pct = max(0.0, min(100.0, flt(row.get("custom_additional_discount"))))
        additional_line_discount += (
            flt(row.qty)
            * supplier_price
            * (1.0 - supplier_discount_pct / 100.0)
            * additional_discount_pct
            / 100.0
        )

    net_before_vat = sum(flt(row.qty) * flt(row.get("custom_net_before_vat")) for row in normal_rows)
    item_vat = sum(flt(row.get("custom_total_vat_amount")) for row in normal_rows)
    bonus_vat = sum(flt(row.get("custom_total_vat_amount")) for row in bonus_rows)
    bonus_retail_value = sum(flt(row.qty) * flt(row.get("custom_selling_price")) for row in bonus_rows)

    fraction_labels = {
        _("Supplier Invoice Fraction Adjustment").strip().casefold(),
        "supplier invoice fraction adjustment",
    }
    bonus_labels = {_("Bonus Item VAT").strip().casefold(), "bonus item vat"}
    shipping = 0.0
    official_fraction_adjustment = 0.0
    official_bonus_vat = 0.0
    for tax in doc.get("taxes") or []:
        description = str(tax.get("description") or "").strip().casefold()
        amount = flt(tax.get("tax_amount"))
        signed_amount = -amount if tax.get("add_deduct_tax") == "Deduct" else amount
        if description in fraction_labels:
            official_fraction_adjustment += signed_amount
        elif description in bonus_labels:
            official_bonus_vat += signed_amount
        elif tax.get("charge_type") == "Actual":
            shipping += signed_amount

    supplier_invoice_total = flt(doc.get("custom_supplier_invoice_total")) or flt(doc.grand_total)
    return {
        "currency": doc.currency or "",
        "supplier_invoice_gross": supplier_invoice_gross,
        "supplier_discount": supplier_discount,
        "additional_line_discount": additional_line_discount,
        "invoice_discount": flt(doc.get("discount_amount")),
        "net_before_vat": net_before_vat or flt(doc.net_total),
        "item_vat": item_vat,
        "bonus_vat": official_bonus_vat or bonus_vat,
        "total_vat": item_vat + (official_bonus_vat or bonus_vat),
        "shipping": shipping,
        "fraction_adjustment": flt(doc.get("custom_fraction_adjustment")) or official_fraction_adjustment,
        "total_taxes_and_charges": flt(doc.total_taxes_and_charges),
        "grand_total": flt(doc.grand_total),
        "supplier_invoice_total": supplier_invoice_total,
        "outstanding_amount": flt(doc.outstanding_amount),
        "bonus_retail_value": bonus_retail_value,
    }


@frappe.whitelist()
def get_procurement_operational_summary(invoice_name: str):
    """Return an A4-ready, read-only operational summary for one purchase cycle."""
    _require_read_access()
    invoice_name = (invoice_name or "").strip()
    if not invoice_name or not frappe.db.exists("Purchase Invoice", invoice_name):
        frappe.throw(_("Purchase Invoice was not found."))

    invoice = frappe.get_doc("Purchase Invoice", invoice_name)
    invoice.check_permission("read")

    linked = _procurement_linked_documents("purchase_invoice", invoice.name)
    all_links = dict(linked.get("all") or {})
    all_links.setdefault("purchase_invoice", [])
    if invoice.name not in all_links["purchase_invoice"]:
        all_links["purchase_invoice"].append(invoice.name)

    stages = []
    primary_links: dict[str, str] = {}
    missing = []
    for stage_key, config in _PROCUREMENT_SUMMARY_STAGE_CONFIG.items():
        documents = []
        for name in all_links.get(stage_key, []):
            if not name or not frappe.db.exists(config["doctype"], name):
                missing.append({"stage": stage_key, "doctype": config["doctype"], "name": name or "", "reason": "not_found"})
                continue
            document = frappe.get_doc(config["doctype"], name)
            try:
                document.check_permission("read")
            except frappe.PermissionError:
                missing.append({"stage": stage_key, "doctype": config["doctype"], "name": name, "reason": "no_permission"})
                continue
            documents.append(_procurement_stage_document_summary(stage_key, document))
        if documents:
            primary_links[stage_key] = documents[0]["name"]
        stages.append({
            "stage": stage_key,
            "stage_label": config["label"],
            "documents": documents,
        })

    has_upstream = any(primary_links.get(key) for key in ("purchase_request", "purchase_order", "purchase_receipt"))
    match = get_procurement_match_preview(primary_links)
    if not has_upstream:
        for row in match.get("rows") or []:
            row["status"] = "direct"
            row["issues"] = []
            row["issues_text"] = ""
        match["summary"]["issues"] = []
        match["summary"]["issues_count"] = 0
        match["summary"]["match_status"] = "direct"
        match["summary"]["status_label"] = _("Direct Invoice")

    return {
        "invoice": {
            "name": invoice.name,
            "docstatus": cint(invoice.docstatus),
            "status": invoice.status or ("Draft" if cint(invoice.docstatus) == 0 else "Submitted"),
            "company": invoice.company,
            "supplier": invoice.supplier,
            "supplier_name": invoice.supplier_name or invoice.supplier,
            "warehouse": _procurement_document_warehouse(invoice),
            "posting_date": invoice.posting_date,
            "bill_no": invoice.bill_no or "",
            "bill_date": invoice.bill_date,
            "due_date": invoice.due_date,
            "payment_classification": invoice.get("custom_payment_classification") or "",
            "remarks": invoice.remarks or "",
            "route": f"/app/purchase-invoice/{invoice.name}",
        },
        "is_direct_invoice": 0 if has_upstream else 1,
        "stages": stages,
        "match": match,
        "decision": _latest_procurement_match_decision(invoice.name),
        "totals": _purchase_invoice_operational_totals(invoice),
        "missing": missing,
        "generated": {
            "at": now_datetime(),
            "by": frappe.utils.get_fullname(frappe.session.user) or frappe.session.user,
        },
    }


def _source_doc_config(source_type: str) -> dict[str, Any]:
    source_type = (source_type or "").strip()
    configs = {
        "purchase_request": {
            "doctype": "Material Request",
            "label": _("Purchase Request"),
            "link_key": "purchase_request",
            "target": "purchase_order",
        },
        "purchase_order": {
            "doctype": "Purchase Order",
            "label": _("Purchase Order"),
            "link_key": "purchase_order",
            "target": "purchase_receipt",
        },
        "purchase_receipt": {
            "doctype": "Purchase Receipt",
            "label": _("Purchase Receipt"),
            "link_key": "purchase_receipt",
            "target": "purchase_invoice",
        },
    }
    if source_type not in configs:
        frappe.throw(_("Unsupported procurement source type."))
    return configs[source_type]


def _source_row_qty(source_type: str, row) -> float:
    if source_type == "purchase_receipt":
        return flt(row.get("received_qty") or row.get("accepted_qty") or row.get("qty") or row.get("stock_qty"))
    return flt(row.get("qty") or row.get("stock_qty"))


def _source_row_rate(row, qty: float) -> float:
    rate = flt(row.get("rate") or row.get("base_rate") or row.get("price_list_rate"))
    if not rate and qty:
        rate = flt(row.get("amount") or row.get("base_amount")) / qty
    return rate





def _child_table_has_field(doctype: str, fieldname: str) -> bool:
    try:
        return bool(frappe.get_meta(doctype).get_field(fieldname))
    except Exception:
        return False


def _sum_linked_child_qty(parent_doctype: str, child_doctype: str, qty_fields: list[str], filters: dict[str, Any]) -> float:
    """Sum linked child quantities for draft/submitted downstream procurement docs.

    Draft documents are intentionally counted so the picker cannot accidentally
    over-order, over-receive, or over-invoice from already-created draft documents.
    """
    qty_field = next((field for field in qty_fields if _child_table_has_field(child_doctype, field)), None)
    if not qty_field:
        return 0.0

    conditions = ["p.docstatus < 2"]
    params = []
    for fieldname, value in (filters or {}).items():
        if value in (None, ""):
            continue
        if not _child_table_has_field(child_doctype, fieldname):
            continue
        conditions.append(f"c.`{fieldname}` = %s")
        params.append(value)

    if len(conditions) <= 1:
        return 0.0

    result = frappe.db.sql(
        f"""
        select coalesce(sum(c.`{qty_field}`), 0)
        from `tab{child_doctype}` c
        join `tab{parent_doctype}` p on p.name = c.parent
        where {' and '.join(conditions)}
        """,
        tuple(params),
    )
    return flt(result[0][0] if result else 0)


def _source_row_consumed_qty(source_type: str, source_docname: str, source_rowname: str, item_code: str) -> float:
    """Return quantity already carried forward from a source row.

    purchase_request -> Purchase Order Item
    purchase_order   -> Purchase Receipt Item
    purchase_receipt -> Purchase Invoice Item
    """
    source_type = (source_type or "").strip()

    if source_type == "purchase_request":
        filters = {
            "material_request": source_docname,
            "material_request_item": source_rowname,
        }
        # item_code fallback keeps the function useful if a custom ERPNext field is missing.
        if not _child_table_has_field("Purchase Order Item", "material_request_item"):
            filters = {"material_request": source_docname, "item_code": item_code}
        return _sum_linked_child_qty("Purchase Order", "Purchase Order Item", ["qty", "stock_qty"], filters)

    if source_type == "purchase_order":
        detail_field = "purchase_order_item" if _child_table_has_field("Purchase Receipt Item", "purchase_order_item") else "po_detail"
        filters = {
            "purchase_order": source_docname,
            detail_field: source_rowname,
        }
        if not _child_table_has_field("Purchase Receipt Item", detail_field):
            filters = {"purchase_order": source_docname, "item_code": item_code}
        return _sum_linked_child_qty("Purchase Receipt", "Purchase Receipt Item", ["qty", "received_qty", "accepted_qty", "stock_qty"], filters)

    if source_type == "purchase_receipt":
        detail_field = "pr_detail" if _child_table_has_field("Purchase Invoice Item", "pr_detail") else "purchase_receipt_item"
        filters = {
            "purchase_receipt": source_docname,
            detail_field: source_rowname,
        }
        if not _child_table_has_field("Purchase Invoice Item", detail_field):
            filters = {"purchase_receipt": source_docname, "item_code": item_code}
        return _sum_linked_child_qty("Purchase Invoice", "Purchase Invoice Item", ["qty", "stock_qty"], filters)

    return 0.0


def _purchase_page_row_from_source(source_type: str, doc, row) -> dict[str, Any]:
    item_code = row.get("item_code")
    item = frappe.db.get_value(
        "Item",
        item_code,
        _safe_fields(
            "Item",
            [
                "item_name",
                "stock_uom",
                "purchase_uom",
                "has_batch_no",
                "has_expiry_date",
                "custom_customer_price",
            ],
        ),
        as_dict=True,
    ) or frappe._dict()
    qty = _source_row_qty(source_type, row)
    rate = _source_row_rate(row, qty)
    warehouse = row.get("warehouse") or row.get("target_warehouse") or row.get("accepted_warehouse") or doc.get("set_warehouse") or ""
    customer_price = flt(row.get("custom_selling_price")) or flt(item.get("custom_customer_price")) or rate
    supplier_base = flt(row.get("custom_supplier_base_price")) or flt(row.get("price_list_rate")) or rate or customer_price
    net_rate = flt(row.get("custom_manual_net_rate")) or rate
    conversion_factor = flt(row.get("conversion_factor")) or _uom_conversion_factor(item_code, row.get("uom") or item.get("purchase_uom") or item.get("stock_uom"), item.get("stock_uom"))

    source_links = {
        "source_doctype": doc.doctype,
        "source_name": doc.name,
        "source_detail": row.get("name") or "",
    }
    if source_type == "purchase_request":
        source_links.update({
            "material_request": doc.name,
            "material_request_item": row.get("name") or "",
        })
    elif source_type == "purchase_order":
        source_links.update({
            "purchase_order": doc.name,
            "purchase_order_item": row.get("name") or "",
            "material_request": row.get("material_request") or "",
            "material_request_item": row.get("material_request_item") or "",
        })
    elif source_type == "purchase_receipt":
        source_links.update({
            "purchase_receipt": doc.name,
            "purchase_receipt_item": row.get("name") or "",
            "purchase_order": row.get("purchase_order") or "",
            "purchase_order_item": row.get("purchase_order_item") or row.get("po_detail") or "",
            "material_request": row.get("material_request") or "",
            "material_request_item": row.get("material_request_item") or "",
        })

    return {
        "row_id": f"source-{doc.doctype}-{doc.name}-{row.get('name') or row.get('idx')}",
        "item_code": item_code,
        "item_name": row.get("item_name") or item.get("item_name") or item_code,
        "qty": qty,
        "source_qty": qty,
        "uom": row.get("uom") or item.get("purchase_uom") or item.get("stock_uom"),
        "conversion_factor": conversion_factor,
        "warehouse": warehouse,
        "customer_price": customer_price,
        "printed_retail_price": customer_price,
        "customer_base_before_vat": flt(row.get("custom_customer_base_before_vat")),
        "supplier_base_price": supplier_base,
        "pricing_method": row.get("custom_purchase_pricing_method") or ("Direct Final Net Rate" if net_rate else "Discount From Customer Price"),
        "entered_net_before_vat": flt(row.get("custom_entered_net_before_vat")),
        "supplier_discount": flt(row.get("custom_supplier_discount_percentage")),
        "additional_discount": flt(row.get("custom_additional_discount")),
        "effective_discount": flt(row.get("custom_effective_discount_percentage")),
        "tax_entry_mode": row.get("custom_tax_entry_mode") or ("Auto by VAT %" if row.get("item_tax_template") else "No VAT"),
        "vat_inclusive": cint(row.get("custom_vat_inclusive_in_final_rate") if row.get("custom_vat_inclusive_in_final_rate") is not None else 1),
        "vat_rate": flt(row.get("custom_vat_rate")),
        "net_before_vat": flt(row.get("custom_net_before_vat")),
        "vat_per_unit": flt(row.get("custom_vat_per_unit")),
        "total_vat": flt(row.get("custom_total_vat_amount")),
        "net_rate": net_rate,
        "amount": qty * net_rate,
        "batch_no": row.get("custom_batch_number") or row.get("batch_no") or "",
        "expiry_date": row.get("custom_expiry_date") or row.get("expiry_date") or "",
        "item_tax_template": row.get("item_tax_template") or "",
        "item_tax_rate": flt(row.get("custom_vat_rate")),
        "is_bonus": cint(row.get("custom_is_bonus_item") or row.get("is_free_item")),
        "auto_batch_reason": row.get("custom_auto_batch_reason") or "",
        "has_batch_no": cint(item.get("has_batch_no")),
        "has_expiry_date": cint(item.get("has_expiry_date")),
        "current_customer_price": flt(item.get("custom_customer_price")),
        "risk_level": "None",
        "risk_flags": [],
        "risk_messages": [],
        "risk_confirmed": 0,
        "risk_confirmation_reason": "",
        "risk_metrics": _purchase_risk_metrics(item_code, warehouse, qty * conversion_factor),
        **source_links,
    }


def _source_current_stock_qty(item_code: str, warehouse: str | None = None) -> float:
    """Return current actual stock for advisory procurement recheck."""
    if not item_code:
        return 0.0
    if warehouse:
        return flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0)
    row = frappe.db.sql(
        """select sum(actual_qty) from `tabBin` where item_code=%s""",
        (item_code,),
    )
    return flt(row[0][0] if row and row[0] else 0)


def _apply_source_stock_recheck(source_type: str, source_row: dict[str, Any]) -> None:
    """Add advisory current-stock fields to source picker rows.

    This does not change stock, status, or linked documents. It only warns the user
    when a requested shortage may already have been covered by another purchase.
    """
    item_code = source_row.get("item_code")
    warehouse = source_row.get("warehouse")
    remaining_qty = flt(source_row.get("remaining_qty") or source_row.get("qty") or 0)
    current_stock_qty = _source_current_stock_qty(item_code, warehouse)
    source_row["current_stock_qty"] = current_stock_qty
    source_row["suggested_qty_to_load"] = remaining_qty
    source_row["stock_recheck_level"] = "none"
    source_row["stock_recheck_message"] = ""

    if source_type != "purchase_request" or remaining_qty <= 0:
        return

    if current_stock_qty >= remaining_qty:
        source_row["stock_recheck_level"] = "covered"
        source_row["suggested_qty_to_load"] = 0
        source_row["stock_recheck_message"] = _("Current stock may already cover this requested quantity.")
    elif current_stock_qty > 0:
        source_row["stock_recheck_level"] = "partial"
        source_row["suggested_qty_to_load"] = max(remaining_qty - current_stock_qty, 0)
        source_row["stock_recheck_message"] = _("Current stock has increased; review the quantity before ordering.")


@frappe.whitelist()
def get_procurement_source_items(source_type: str, source_name: str):
    """Load selectable source items for continuing a procurement flow.

    This is a read-only picker foundation. The user chooses which rows and quantities
    to carry forward into the current Purchase & Invoice Management page.
    """
    _require_read_access()
    config = _source_doc_config(source_type)
    doctype = config["doctype"]
    source_name = (source_name or "").strip()
    if not source_name or not frappe.db.exists(doctype, source_name):
        frappe.throw(_("{0} was not found.").format(config["label"]))
    doc = frappe.get_doc(doctype, source_name)
    doc.check_permission("read")

    items = []
    for row in doc.get("items") or []:
        item_code = row.get("item_code")
        if not item_code:
            continue
        source_row = _purchase_page_row_from_source(source_type, doc, row)
        source_qty = flt(source_row.get("qty"))
        if source_qty <= 0:
            continue
        already_used_qty = _source_row_consumed_qty(source_type, doc.name, row.get("name") or "", item_code)
        remaining_qty = max(source_qty - already_used_qty, 0)
        source_row["source_qty"] = source_qty
        source_row["already_used_qty"] = already_used_qty
        source_row["remaining_qty"] = remaining_qty
        source_row["qty"] = remaining_qty
        source_row["is_fully_consumed"] = 1 if remaining_qty <= 0 else 0
        _apply_source_stock_recheck(source_type, source_row)
        items.append(source_row)

    return {
        "source_type": source_type,
        "target_kind": config["target"],
        "link_key": config["link_key"],
        "document": _procurement_response(doc),
        "linked_documents": _procurement_linked_documents(source_type, doc.name),
        "company": doc.get("company") or "",
        "supplier": doc.get("supplier") or "",
        "warehouse": doc.get("set_warehouse") or (items[0].get("warehouse") if items else ""),
        "items": items,
    }


@frappe.whitelist()
def create_purchase_request_draft(payload):
    """Create an ERPNext Material Request with type Purchase as a Draft only."""
    _require_document_create_access("Material Request", _("Purchase Request"))
    payload = _parse_payload(payload)
    _validate_procurement_payload(payload, require_supplier=False)
    schedule_date = _procurement_schedule_date(payload)

    doc = frappe.new_doc("Material Request")
    doc.material_request_type = "Purchase"
    doc.company = payload.get("company")
    doc.transaction_date = payload.get("posting_date") or nowdate()
    if doc.meta.has_field("schedule_date"):
        doc.schedule_date = schedule_date
    if doc.meta.has_field("set_warehouse"):
        doc.set_warehouse = payload.get("warehouse")
    if doc.meta.has_field("title"):
        doc.title = _("Purchase Request from Purchase Management")
    if doc.meta.has_field("custom_source_supplier"):
        doc.custom_source_supplier = payload.get("supplier") or ""
    if doc.meta.has_field("custom_source_purchase_invoice_draft"):
        doc.custom_source_purchase_invoice_draft = payload.get("name") or ""
    doc.set("items", [])
    for source in payload.get("items") or []:
        doc.append("items", _build_material_request_item(frappe._dict(source), payload.get("warehouse"), schedule_date))
    doc.flags.ignore_mandatory = False
    doc.insert()
    doc.reload()
    return {"document": _procurement_response(doc)}


@frappe.whitelist()
def create_purchase_order_draft(payload):
    """Create an ERPNext Purchase Order Draft from the current Purchase Management rows."""
    _require_document_create_access("Purchase Order")
    payload = _parse_payload(payload)
    _validate_procurement_payload(payload, require_supplier=True)
    _enrich_procurement_items_from_linked_source(payload, "purchase_request")
    _normalize_tax_templates(payload)
    schedule_date = _procurement_schedule_date(payload)

    doc = frappe.new_doc("Purchase Order")
    doc.company = payload.get("company")
    doc.supplier = payload.get("supplier")
    doc.transaction_date = payload.get("posting_date") or nowdate()
    doc.schedule_date = schedule_date
    if doc.meta.has_field("set_warehouse"):
        doc.set_warehouse = payload.get("warehouse")
    if doc.meta.has_field("buying_price_list"):
        doc.buying_price_list = payload.get("buying_price_list") or _default_buying_price_list()
    if doc.meta.has_field("custom_source_purchase_invoice_draft"):
        doc.custom_source_purchase_invoice_draft = payload.get("name") or ""
    if doc.meta.has_field("custom_purchase_management_source"):
        doc.custom_purchase_management_source = "Purchase & Invoice Management"
    if doc.meta.has_field("remarks"):
        doc.remarks = payload.get("remarks") or _("Draft created from Purchase & Invoice Management.")

    doc.set("items", [])
    for source in payload.get("items") or []:
        doc.append("items", _build_purchase_order_item(frappe._dict(source), payload.get("warehouse"), schedule_date))

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
    if invoice_discount:
        doc.apply_discount_on = "Net Total"
        doc.additional_discount_percentage = invoice_discount
    if hasattr(doc, "set_missing_values"):
        doc.set_missing_values()
    if hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()
    doc.insert()
    doc.reload()
    return {"document": _procurement_response(doc)}



@frappe.whitelist()
def create_purchase_receipt_draft(payload):
    """Create an ERPNext Purchase Receipt Draft from the current Purchase Management rows."""
    _require_document_create_access("Purchase Receipt")
    payload = _parse_payload(payload)
    _validate_procurement_payload(payload, require_supplier=True)
    _enrich_procurement_items_from_linked_source(payload, "purchase_order")
    _normalize_tax_templates(payload)

    doc = frappe.new_doc("Purchase Receipt")
    doc.company = payload.get("company")
    doc.supplier = payload.get("supplier")
    doc.posting_date = payload.get("posting_date") or nowdate()
    if doc.meta.has_field("set_posting_time"):
        doc.set_posting_time = 1
    if doc.meta.has_field("set_warehouse"):
        doc.set_warehouse = payload.get("warehouse")
    if doc.meta.has_field("custom_source_purchase_invoice_draft"):
        doc.custom_source_purchase_invoice_draft = payload.get("name") or ""
    if doc.meta.has_field("custom_purchase_management_source"):
        doc.custom_purchase_management_source = "Purchase & Invoice Management"
    if doc.meta.has_field("remarks"):
        doc.remarks = payload.get("remarks") or _("Draft created from Purchase & Invoice Management.")

    doc.set("items", [])
    for source in payload.get("items") or []:
        doc.append("items", _build_purchase_receipt_item(frappe._dict(source), payload.get("warehouse")))

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
    if invoice_discount:
        doc.apply_discount_on = "Net Total"
        doc.additional_discount_percentage = invoice_discount
    if hasattr(doc, "set_missing_values"):
        doc.set_missing_values()
    if hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()
    doc.insert()
    doc.reload()
    return {"document": _procurement_response(doc)}


@frappe.whitelist()
def create_purchase_invoice_draft(payload):
    """Create an ERPNext Purchase Invoice Draft from the current Purchase Management rows.

    This draft is intended for invoicing after a Purchase Receipt / Purchase Order review.
    It does not submit, does not create GL Entries, and keeps update_stock disabled so stock
    is not received twice when a Purchase Receipt is used.
    """
    _require_document_create_access("Purchase Invoice")
    payload = _parse_payload(payload)
    _validate_procurement_payload(payload, require_supplier=True)
    _enrich_procurement_items_from_latest_link(payload)
    _normalize_tax_templates(payload)
    settings = get_purchase_settings()
    _validate_near_expiry_confirmation_before_save(payload, settings)

    bill_no = (payload.get("bill_no") or "").strip()
    if bill_no:
        duplicate = frappe.db.exists(
            "Purchase Invoice",
            {
                "supplier": payload.get("supplier"),
                "bill_no": bill_no,
                "docstatus": ["<", 2],
            },
        )
        if duplicate:
            frappe.throw(
                _("Supplier Invoice Number {0} already exists in {1}.").format(
                    frappe.bold(bill_no),
                    frappe.get_desk_link("Purchase Invoice", duplicate),
                )
            )

    doc = frappe.new_doc("Purchase Invoice")
    _disable_purchase_invoice_rounded_total(doc)
    doc.company = payload.get("company")
    doc.supplier = payload.get("supplier")
    doc.posting_date = payload.get("posting_date") or nowdate()
    doc.set_posting_time = 1
    doc.bill_no = bill_no
    doc.bill_date = payload.get("bill_date") or doc.posting_date
    doc.due_date = payload.get("due_date") or doc.posting_date
    doc.update_stock = 0
    doc.set_warehouse = payload.get("warehouse")
    doc.buying_price_list = payload.get("buying_price_list") or _default_buying_price_list()

    claim_period = _claim_period_for_date(doc.supplier, doc.bill_date)
    if doc.meta.has_field("custom_claim_basis_date"):
        doc.custom_claim_basis_date = claim_period.get("basis_date") or doc.bill_date
    if doc.meta.has_field("custom_expected_claim_period_from"):
        doc.custom_expected_claim_period_from = claim_period.get("period_from")
    if doc.meta.has_field("custom_expected_claim_period_to"):
        doc.custom_expected_claim_period_to = claim_period.get("period_to")
    if doc.meta.has_field("custom_purchase_entry_mode"):
        doc.custom_purchase_entry_mode = "Against Purchase Order"
    if doc.meta.has_field("custom_payment_classification"):
        doc.custom_payment_classification = payload.get("payment_classification") or ""
    if doc.meta.has_field("custom_exclude_from_supplier_claim"):
        doc.custom_exclude_from_supplier_claim = cint(payload.get("exclude_from_claim"))
    if doc.meta.has_field("custom_supplier_invoice_attachment"):
        doc.custom_supplier_invoice_attachment = payload.get("attachment") or ""
    if doc.meta.has_field("custom_source_purchase_invoice_draft"):
        doc.custom_source_purchase_invoice_draft = payload.get("name") or ""
    if doc.meta.has_field("custom_purchase_management_source"):
        doc.custom_purchase_management_source = "Purchase & Invoice Management"

    doc.remarks = payload.get("remarks") or _("Draft created from Purchase & Invoice Management.")
    doc.set("items", [])
    for source in payload.get("items") or []:
        row = frappe._dict(source)
        doc.append("items", _build_item_row(doc, row, payload.get("warehouse"), 1))

    if hasattr(doc, "set_missing_values"):
        doc.set_missing_values()

    _copy_tax_template(doc, payload.get("taxes_and_charges"), 1)
    _ensure_item_tax_rows(doc, payload)
    _apply_item_tax_overrides(doc, payload)
    _append_bonus_vat_charges(doc, payload)
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

    doc.insert()
    _attach_file(payload.get("attachment"), doc.name)
    doc.reload()
    return {"document": _procurement_response(doc), "invoice": _invoice_response(doc)}


@frappe.whitelist()
def log_procurement_match_decision(payload):
    """Record a user's decision to continue despite procurement match warnings.

    This is intentionally audit-only: it does not submit, cancel, or change stock/GL.
    The actual submit still goes through submit_invoice after this comment is written.
    """
    _require_create_access()
    data = _parse_payload(payload or {})
    invoice_name = (data.get("purchase_invoice") or data.get("invoice") or "").strip()
    if not invoice_name or not frappe.db.exists("Purchase Invoice", invoice_name):
        frappe.throw(_("A valid Purchase Invoice is required to log the match decision."))

    doc = frappe.get_doc("Purchase Invoice", invoice_name)
    doc.check_permission("write")

    status = (data.get("match_status") or "").strip().lower()
    decision = (data.get("decision") or "").strip()
    reason = (data.get("reason") or "").strip()
    if status in {"warning", "mismatch"} and not reason:
        frappe.throw(_("A reason is required when accepting procurement match differences."))

    links = data.get("links") or {}
    summary = data.get("summary") or {}
    issues = data.get("issues") or summary.get("issues") or []

    def link_line(label: str, value: Any) -> str:
        if not value:
            return ""
        return f"<li><b>{escape_html(label)}:</b> {escape_html(str(value))}</li>"

    issue_lines = []
    for issue in issues[:30]:
        if not isinstance(issue, dict):
            continue
        item = issue.get("item_name") or issue.get("item_code") or ""
        severity = issue.get("severity") or "warning"
        message = issue.get("message") or issue.get("code") or ""
        issue_lines.append(
            f"<li><b>{escape_html(str(severity).upper())}</b> — {escape_html(str(item))}: {escape_html(str(message))}</li>"
        )

    links_html = "".join([
        link_line("Purchase Request", links.get("purchase_request") or links.get("material_request")),
        link_line("Purchase Order", links.get("purchase_order")),
        link_line("Purchase Receipt", links.get("purchase_receipt")),
        link_line("Purchase Invoice", links.get("purchase_invoice") or invoice_name),
    ])

    summary_json = escape_html(frappe.as_json(summary, indent=2) if summary else "{}")
    comment = f"""
        <div><b>Procurement Match Decision</b></div>
        <div><b>Status:</b> {escape_html(status or 'unknown')}</div>
        <div><b>Decision:</b> {escape_html(decision or 'accepted')}</div>
        <div><b>Reason:</b> {escape_html(reason)}</div>
        <ul>{links_html}</ul>
        <div><b>Issues:</b></div>
        <ul>{''.join(issue_lines) or '<li>No issue details provided.</li>'}</ul>
        <details><summary>Match Summary JSON</summary><pre>{summary_json}</pre></details>
    """
    doc.add_comment("Comment", comment)
    return {"ok": True, "invoice": doc.name}



def _submit_linked_procurement_chain(invoice_doc) -> list[dict]:
    # Submit Request -> Order -> Receipt drafts before their linked invoice.
    # Purchase Receipt is the only stage that posts stock; the linked
    # Purchase Invoice remains update_stock = 0.
    linked = _procurement_linked_documents("purchase_invoice", invoice_doc.name)
    all_links = linked.get("all") or {}

    stage_specs = (
        ("purchase_request", "Material Request", _("Purchase Request")),
        ("purchase_order", "Purchase Order", _("Purchase Order")),
        ("purchase_receipt", "Purchase Receipt", _("Purchase Receipt")),
    )

    planned = []
    seen = set()

    for stage_key, doctype, label in stage_specs:
        names = list(all_links.get(stage_key) or [])
        if not names and linked.get(stage_key):
            name = (linked.get(stage_key) or {}).get("name")
            if name:
                names = [name]

        for name in names:
            key = (doctype, name)
            if not name or key in seen:
                continue
            seen.add(key)

            if not frappe.db.exists(doctype, name):
                frappe.throw(
                    _("Linked {0} {1} no longer exists.").format(
                        label, frappe.bold(name)
                    )
                )

            stage_doc = frappe.get_doc(doctype, name)

            if stage_doc.docstatus == 2:
                frappe.throw(
                    _("Linked {0} {1} is cancelled and the procurement chain cannot be submitted.").format(
                        label, frappe.bold(name)
                    )
                )

            if (
                stage_doc.get("company")
                and invoice_doc.get("company")
                and stage_doc.company != invoice_doc.company
            ):
                frappe.throw(
                    _("Linked {0} {1} belongs to a different company.").format(
                        label, frappe.bold(name)
                    )
                )

            if (
                doctype in {"Purchase Order", "Purchase Receipt"}
                and stage_doc.get("supplier")
                and invoice_doc.get("supplier")
                and stage_doc.supplier != invoice_doc.supplier
            ):
                frappe.throw(
                    _("Linked {0} {1} belongs to a different supplier.").format(
                        label, frappe.bold(name)
                    )
                )

            if stage_doc.docstatus == 0:
                stage_doc.check_permission("submit")
                planned.append((stage_key, doctype, label, stage_doc))

    submitted = []
    for stage_key, doctype, label, stage_doc in planned:
        try:
            stage_doc.submit()
            stage_doc.reload()
        except Exception as exc:
            frappe.throw(
                _("Unable to submit {0} {1}. ERPNext message: {2}").format(
                    label,
                    frappe.bold(stage_doc.name),
                    frappe.utils.escape_html(str(exc)),
                )
            )

        submitted.append(
            {
                "stage": stage_key,
                "doctype": doctype,
                "name": stage_doc.name,
                "docstatus": stage_doc.docstatus,
            }
        )

    return submitted


@frappe.whitelist()
def submit_invoice(name: str, retail_price_decision: str | None = None):
    _require_create_access()
    doc = frappe.get_doc("Purchase Invoice", name)
    doc.check_permission("submit")
    if doc.docstatus != 0:
        frappe.throw(_("Only a Draft Purchase Invoice can be submitted."))

    price_preview = get_retail_price_change_preview(doc.name)
    if price_preview.get("conflicts"):
        details = "<br>".join(
            _("{0}: {1}").format(
                frappe.bold(conflict.get("item_name") or conflict.get("item_code")),
                ", ".join(str(flt(price)) for price in (conflict.get("prices") or [])),
            )
            for conflict in price_preview.get("conflicts") or []
        )
        frappe.throw(
            _(
                "More than one new Customer Price was entered for the same "
                "non-batch item. Keep one final price before Submit:<br>{0}"
            ).format(details)
        )

    if price_preview.get("requires_decision") and not retail_price_decision:
        frappe.throw(
            _(
                "Review the Customer Price changes and choose either Approve New "
                "Price or Keep Current Price before submitting."
            )
        )

    normalized_price_decision = set_retail_price_submission_decision(
        doc,
        retail_price_decision,
    )

    # Also normalize drafts created before this fix. Saving once with rounded
    # total disabled removes ERPNext's extra whole-unit rounding while keeping
    # the explicit supplier fraction-adjustment row and Bonus VAT row intact.
    rounded_total_was_enabled = bool(
        doc.meta.has_field("disable_rounded_total")
        and not cint(doc.get("disable_rounded_total"))
    )
    # Normalize the stock flag before any recalculation or intermediate save.
    # Purchase Receipt has already posted stock, so its linked invoice must never update stock again.
    if _purchase_invoice_has_linked_receipt(doc=doc) and cint(doc.get("update_stock")):
        doc.update_stock = 0

    # Official upstream drafts must be submitted before any intermediate
    # invoice save, otherwise ERPNext rejects links to Draft documents.
    if _purchase_invoice_has_linked_receipt(doc=doc):
        doc.update_stock = 0
    submitted_procurement = _submit_linked_procurement_chain(doc)

    _disable_purchase_invoice_rounded_total(doc)
    if rounded_total_was_enabled:
        if hasattr(doc, "calculate_taxes_and_totals"):
            doc.calculate_taxes_and_totals()
        doc.save()
        doc.reload()

    # Final persisted invariant after upstream chain submission and any intermediate save.
    if _purchase_invoice_has_linked_receipt(doc=doc):
        doc.update_stock = 0
        if (
            doc.meta.has_field("custom_purchase_entry_mode")
            and doc.get("custom_purchase_entry_mode") == "Quick Invoice & Receipt"
        ):
            doc.custom_purchase_entry_mode = "Against Purchase Order"
        doc.save()
        doc.reload()

        persisted_update_stock = cint(
            frappe.db.get_value("Purchase Invoice", doc.name, "update_stock")
        )
        if persisted_update_stock:
            frappe.throw(
                _(
                    "Safety guard stopped submission because Purchase Invoice {0} "
                    "is linked to a Purchase Receipt but Update Stock is still enabled."
                ).format(frappe.bold(doc.name))
            )

    _validate_purchase_risk_before_submit(doc)
    doc.submit()
    doc.reload()
    return {
        "invoice": _invoice_response(doc),
        "recent_invoices": _recent_invoices(doc.company),
        "submitted_procurement": submitted_procurement,
        "retail_price_review": {
            "decision": normalized_price_decision or "not_required",
            "status": doc.get("custom_retail_price_review_status") or "",
            "change_count": cint(doc.get("custom_price_change_count")),
            "reviewed_by": doc.get("custom_price_reviewed_by") or "",
            "reviewed_at": doc.get("custom_price_reviewed_at"),
            "stock_scope": doc.get("custom_retail_price_stock_scope") or "",
        },
    }


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
