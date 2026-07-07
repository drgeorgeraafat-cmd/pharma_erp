"""Read-only Supplier Running Account page API.

Phase 1 intentionally does not create, submit, cancel, reconcile, or mutate any
ERPNext accounting/stock document. It reads the official supplier ledger from
GL Entry and enriches each row with Purchase Invoice, Payment Entry, Journal
Entry, Supplier Claim, and Pharmacy Return Case links where available.
"""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, get_first_day, getdate, nowdate

READ_ROLES = {
    "Purchase User",
    "Purchase Manager",
    "Accounts User",
    "Accounts Manager",
    "System Manager",
}
MONEY_TOLERANCE = 0.01


def _has_role_access() -> bool:
    return bool(READ_ROLES.intersection(set(frappe.get_roles())))


def _require_read_access() -> None:
    if not _has_role_access():
        frappe.throw(_("You are not permitted to access Supplier Running Account."), frappe.PermissionError)
    if not frappe.has_permission("Supplier", "read"):
        frappe.throw(_("You are not permitted to read Suppliers."), frappe.PermissionError)
    if not frappe.has_permission("GL Entry", "read"):
        frappe.throw(_("You are not permitted to read General Ledger entries."), frappe.PermissionError)


def _default_company() -> str | None:
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.defaults.get_global_default("company")
        or frappe.db.get_value("Company", {}, "name", order_by="is_group asc, creation asc")
    )


def _meta_has_field(doctype: str, fieldname: str) -> bool:
    try:
        return frappe.get_meta(doctype).has_field(fieldname)
    except Exception:
        return False


def _db_has_column(doctype: str, fieldname: str) -> bool:
    try:
        return bool(frappe.db.has_column(doctype, fieldname))
    except Exception:
        return _meta_has_field(doctype, fieldname)


def _safe_fields(doctype: str, desired: list[str]) -> list[str]:
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return [fieldname for fieldname in desired if fieldname == "name"]
    allowed = {field.fieldname for field in meta.fields if field.fieldname}
    allowed.add("name")
    return [fieldname for fieldname in desired if fieldname in allowed]


def _doc_exists(doctype: str, name: str | None) -> bool:
    return bool(name and frappe.db.exists(doctype, name))


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(cint(value))


def _docstatus_label(docstatus: int | None, status: str | None = None) -> str:
    if cint(docstatus) == 2:
        return "Cancelled"
    if status:
        return status
    if cint(docstatus) == 1:
        return "Submitted"
    return "Draft"


def _posting_total(row: dict | frappe._dict) -> float:
    """Use rounded_total when ERPNext rounding is active, otherwise grand_total.

    This mirrors the rule already stabilized in Purchase Returns: do not rely on
    grand_total alone when rounded_total/outstanding_amount is the accounting
    amount shown by ERPNext.
    """
    rounded_total = flt(row.get("rounded_total"))
    grand_total = flt(row.get("grand_total"))
    if not cint(row.get("disable_rounded_total")) and abs(rounded_total) > MONEY_TOLERANCE:
        return rounded_total
    return grand_total


def _condition_date_range(alias: str, params: dict, from_date: str | None, to_date: str | None) -> list[str]:
    conditions = []
    if from_date:
        params["from_date"] = getdate(from_date)
        conditions.append(f"{alias}.posting_date >= %(from_date)s")
    if to_date:
        params["to_date"] = getdate(to_date)
        conditions.append(f"{alias}.posting_date <= %(to_date)s")
    return conditions


def _opening_balance(company: str, supplier: str, from_date: str | None, include_cancelled: bool) -> float:
    if not from_date:
        return 0.0

    conditions = [
        "company = %(company)s",
        "party_type = 'Supplier'",
        "party = %(supplier)s",
        "posting_date < %(from_date)s",
    ]
    params = {"company": company, "supplier": supplier, "from_date": getdate(from_date)}
    if not include_cancelled and _db_has_column("GL Entry", "is_cancelled"):
        conditions.append("ifnull(is_cancelled, 0) = 0")

    rows = frappe.db.sql(
        f"""
        SELECT COALESCE(SUM(credit), 0) - COALESCE(SUM(debit), 0) AS balance
        FROM `tabGL Entry`
        WHERE {' AND '.join(conditions)}
        """,
        params,
        as_dict=True,
    )
    return flt(rows[0].balance if rows else 0)


def _gl_rows(
    company: str,
    supplier: str,
    from_date: str | None,
    to_date: str | None,
    include_cancelled: bool,
) -> list[frappe._dict]:
    params = {"company": company, "supplier": supplier}
    conditions = [
        "gle.company = %(company)s",
        "gle.party_type = 'Supplier'",
        "gle.party = %(supplier)s",
    ]
    conditions.extend(_condition_date_range("gle", params, from_date, to_date))
    if not include_cancelled and _db_has_column("GL Entry", "is_cancelled"):
        conditions.append("ifnull(gle.is_cancelled, 0) = 0")

    cancelled_select = "MAX(ifnull(gle.is_cancelled, 0)) AS is_cancelled" if _db_has_column("GL Entry", "is_cancelled") else "0 AS is_cancelled"
    against_select = "GROUP_CONCAT(DISTINCT NULLIF(gle.against_voucher, '') SEPARATOR ', ') AS against_voucher" if _db_has_column("GL Entry", "against_voucher") else "NULL AS against_voucher"
    against_type_select = "GROUP_CONCAT(DISTINCT NULLIF(gle.against_voucher_type, '') SEPARATOR ', ') AS against_voucher_type" if _db_has_column("GL Entry", "against_voucher_type") else "NULL AS against_voucher_type"

    return frappe.db.sql(
        f"""
        SELECT
            gle.posting_date,
            gle.voucher_type,
            gle.voucher_no,
            MIN(gle.creation) AS creation,
            GROUP_CONCAT(DISTINCT gle.account ORDER BY gle.account SEPARATOR ', ') AS accounts,
            {against_type_select},
            {against_select},
            COALESCE(SUM(gle.debit), 0) AS debit,
            COALESCE(SUM(gle.credit), 0) AS credit,
            {cancelled_select},
            GROUP_CONCAT(DISTINCT NULLIF(gle.remarks, '') SEPARATOR ' | ') AS gl_remarks
        FROM `tabGL Entry` gle
        WHERE {' AND '.join(conditions)}
        GROUP BY gle.posting_date, gle.voucher_type, gle.voucher_no
        ORDER BY gle.posting_date ASC, creation ASC, gle.voucher_type ASC, gle.voucher_no ASC
        """,
        params,
        as_dict=True,
    )


def _purchase_invoice_context(name: str) -> dict:
    if not _doc_exists("Purchase Invoice", name):
        return {}
    fields = _safe_fields(
        "Purchase Invoice",
        [
            "name",
            "company",
            "supplier",
            "bill_no",
            "posting_date",
            "status",
            "docstatus",
            "is_return",
            "return_against",
            "grand_total",
            "rounded_total",
            "disable_rounded_total",
            "outstanding_amount",
            "custom_payment_classification",
            "custom_supplier_claim",
            "custom_pharmacy_return_case",
        ],
    )
    invoice = frappe.db.get_value("Purchase Invoice", name, fields, as_dict=True) or frappe._dict()
    claim = invoice.get("custom_supplier_claim") if "custom_supplier_claim" in invoice else None
    if not claim and frappe.db.exists("DocType", "Supplier Claim Invoice"):
        claim = frappe.db.get_value(
            "Supplier Claim Invoice",
            {"purchase_invoice": name, "parenttype": "Supplier Claim"},
            "parent",
        )

    return_case = invoice.get("custom_pharmacy_return_case") if "custom_pharmacy_return_case" in invoice else None
    if not return_case and frappe.db.exists("DocType", "Pharmacy Return Case"):
        return_case = frappe.db.get_value(
            "Pharmacy Return Case",
            [["purchase_return", "=", name]],
            "name",
        ) or frappe.db.get_value(
            "Pharmacy Return Case",
            [["approved_debit_note", "=", name]],
            "name",
        )

    return {
        "type": "Purchase Return / Debit Note" if cint(invoice.get("is_return")) else "Purchase Invoice",
        "supplier_invoice_no": invoice.get("bill_no"),
        "status": _docstatus_label(invoice.get("docstatus"), invoice.get("status")),
        "related_return_case": return_case,
        "related_supplier_claim": claim,
        "settlement_classification": invoice.get("custom_payment_classification") or "",
        "outstanding_amount": flt(invoice.get("outstanding_amount")),
        "document_total": _posting_total(invoice),
        "is_purchase_return": cint(invoice.get("is_return")),
        "notes": (
            _("Return Against {0}").format(invoice.get("return_against"))
            if invoice.get("return_against")
            else ""
        ),
    }


def _payment_entry_reference_context(name: str) -> dict:
    if not frappe.db.exists("DocType", "Payment Entry Reference"):
        return {}
    refs = frappe.get_all(
        "Payment Entry Reference",
        filters={"parent": name, "parenttype": "Payment Entry"},
        fields=["reference_doctype", "reference_name", "allocated_amount"],
        limit_page_length=100,
    )
    return_cases: list[str] = []
    claims: list[str] = []
    classifications: list[str] = []
    return_refs = []
    invoice_refs = []
    for ref in refs:
        if ref.reference_doctype != "Purchase Invoice" or not ref.reference_name:
            continue
        ctx = _purchase_invoice_context(ref.reference_name)
        if ctx.get("related_return_case") and ctx["related_return_case"] not in return_cases:
            return_cases.append(ctx["related_return_case"])
        if ctx.get("related_supplier_claim") and ctx["related_supplier_claim"] not in claims:
            claims.append(ctx["related_supplier_claim"])
        if ctx.get("settlement_classification") and ctx["settlement_classification"] not in classifications:
            classifications.append(ctx["settlement_classification"])
        if ctx.get("is_purchase_return"):
            return_refs.append(ref.reference_name)
        else:
            invoice_refs.append(ref.reference_name)
    return {
        "related_return_case": ", ".join(return_cases),
        "related_supplier_claim": ", ".join(claims),
        "settlement_classification": ", ".join(classifications),
        "has_return_reference": bool(return_refs),
        "references_note": ", ".join(return_refs or invoice_refs),
    }


def _payment_entry_context(name: str) -> dict:
    if not _doc_exists("Payment Entry", name):
        return {}
    fields = _safe_fields(
        "Payment Entry",
        [
            "name",
            "posting_date",
            "payment_type",
            "party_type",
            "party",
            "mode_of_payment",
            "paid_amount",
            "received_amount",
            "unallocated_amount",
            "reference_no",
            "reference_date",
            "status",
            "docstatus",
            "custom_supplier_claim",
            "custom_pharmacy_return_case",
            "custom_supplier_refund_method",
        ],
    )
    payment = frappe.db.get_value("Payment Entry", name, fields, as_dict=True) or frappe._dict()
    ref_ctx = _payment_entry_reference_context(name)
    claim = payment.get("custom_supplier_claim") if "custom_supplier_claim" in payment else None
    if not claim and frappe.db.exists("DocType", "Supplier Claim"):
        claim = frappe.db.get_value("Supplier Claim", {"payment_entry": name}, "name") or ref_ctx.get("related_supplier_claim")
    return_case = payment.get("custom_pharmacy_return_case") if "custom_pharmacy_return_case" in payment else None
    return_case = return_case or ref_ctx.get("related_return_case")
    is_refund = (
        payment.get("payment_type") == "Receive"
        or bool(payment.get("custom_supplier_refund_method"))
        or bool(ref_ctx.get("has_return_reference"))
    )
    notes = []
    if payment.get("mode_of_payment"):
        notes.append(_("Mode: {0}").format(payment.get("mode_of_payment")))
    if payment.get("reference_no"):
        notes.append(_("Ref: {0}").format(payment.get("reference_no")))
    if abs(flt(payment.get("unallocated_amount"))) > MONEY_TOLERANCE:
        notes.append(_("Unallocated: {0}").format(flt(payment.get("unallocated_amount"), 2)))
    if ref_ctx.get("references_note"):
        notes.append(_("Refs: {0}").format(ref_ctx.get("references_note")))
    return {
        "type": "Supplier Refund" if is_refund else "Payment Entry",
        "supplier_invoice_no": None,
        "status": _docstatus_label(payment.get("docstatus"), payment.get("status")),
        "related_return_case": return_case,
        "related_supplier_claim": claim,
        "settlement_classification": ref_ctx.get("settlement_classification"),
        "outstanding_amount": flt(payment.get("unallocated_amount")),
        "payment_type": payment.get("payment_type"),
        "notes": " | ".join(notes),
    }


def _journal_reference_context(name: str) -> dict:
    if not frappe.db.exists("DocType", "Journal Entry Account"):
        return {}
    refs = frappe.get_all(
        "Journal Entry Account",
        filters={"parent": name, "parenttype": "Journal Entry", "party_type": "Supplier"},
        fields=["reference_type", "reference_name", "party", "debit_in_account_currency", "credit_in_account_currency"],
        limit_page_length=100,
    )
    return_cases: list[str] = []
    claims: list[str] = []
    journal_classifications: list[str] = []
    referenced = []
    for ref in refs:
        if ref.reference_type == "Purchase Invoice" and ref.reference_name:
            ctx = _purchase_invoice_context(ref.reference_name)
            if ctx.get("related_return_case") and ctx["related_return_case"] not in return_cases:
                return_cases.append(ctx["related_return_case"])
            if ctx.get("related_supplier_claim") and ctx["related_supplier_claim"] not in claims:
                claims.append(ctx["related_supplier_claim"])
            if ctx.get("settlement_classification") and ctx["settlement_classification"] not in journal_classifications:
                journal_classifications.append(ctx["settlement_classification"])
            referenced.append(ref.reference_name)
    return {
        "related_return_case": ", ".join(return_cases),
        "related_supplier_claim": ", ".join(claims),
        "settlement_classification": ", ".join(journal_classifications),
        "references_note": ", ".join(referenced),
    }


def _journal_entry_context(name: str) -> dict:
    if not _doc_exists("Journal Entry", name):
        return {}
    fields = _safe_fields(
        "Journal Entry",
        [
            "name",
            "posting_date",
            "voucher_type",
            "user_remark",
            "remark",
            "cheque_no",
            "docstatus",
            "custom_supplier_claim",
            "custom_pharmacy_return_case",
        ],
    )
    journal = frappe.db.get_value("Journal Entry", name, fields, as_dict=True) or frappe._dict()
    ref_ctx = _journal_reference_context(name)
    claim = journal.get("custom_supplier_claim") if "custom_supplier_claim" in journal else None
    if not claim and frappe.db.exists("DocType", "Supplier Claim"):
        claim = frappe.db.get_value("Supplier Claim", {"settlement_discount_journal_entry": name}, "name")
        if not claim:
            claim = frappe.db.sql(
                """
                SELECT name
                FROM `tabSupplier Claim`
                WHERE accounting_reconciliation_journal_entries LIKE %(journal)s
                ORDER BY modified DESC
                LIMIT 1
                """,
                {"journal": f"%{name}%"},
                as_dict=True,
            )
            claim = claim[0].name if claim else None
    claim = claim or ref_ctx.get("related_supplier_claim")
    return_case = journal.get("custom_pharmacy_return_case") if "custom_pharmacy_return_case" in journal else None
    return_case = return_case or ref_ctx.get("related_return_case")
    notes = journal.get("user_remark") or journal.get("remark") or ""
    if ref_ctx.get("references_note"):
        notes = (notes + " | " if notes else "") + _("Refs: {0}").format(ref_ctx.get("references_note"))
    return {
        "type": "Journal Entry",
        "supplier_invoice_no": None,
        "status": _docstatus_label(journal.get("docstatus")),
        "related_return_case": return_case,
        "related_supplier_claim": claim,
        "settlement_classification": ref_ctx.get("settlement_classification"),
        "outstanding_amount": 0,
        "notes": notes,
    }


def _voucher_context(voucher_type: str | None, voucher_no: str | None) -> dict:
    if voucher_type == "Purchase Invoice":
        return _purchase_invoice_context(voucher_no)
    if voucher_type == "Payment Entry":
        return _payment_entry_context(voucher_no)
    if voucher_type == "Journal Entry":
        return _journal_entry_context(voucher_no)
    return {"type": voucher_type or "GL Entry", "status": "Submitted", "notes": ""}


def _claim_context_rows(
    company: str,
    supplier: str,
    from_date: str | None,
    to_date: str | None,
    include_cancelled: bool,
    include_drafts: bool,
) -> list[dict]:
    if not frappe.db.exists("DocType", "Supplier Claim") or not frappe.has_permission("Supplier Claim", "read"):
        return []

    filters: dict[str, Any] = {"company": company, "supplier": supplier}
    allowed_docstatus = [1]
    if include_drafts:
        allowed_docstatus.append(0)
    if include_cancelled:
        allowed_docstatus.append(2)
    filters["docstatus"] = ["in", sorted(set(allowed_docstatus))]
    if from_date and to_date:
        filters["period_to"] = ["between", [getdate(from_date), getdate(to_date)]]
    elif from_date:
        filters["period_to"] = [">=", getdate(from_date)]
    elif to_date:
        filters["period_from"] = ["<=", getdate(to_date)]

    fields = _safe_fields(
        "Supplier Claim",
        [
            "name",
            "company",
            "supplier",
            "period_from",
            "period_to",
            "status",
            "docstatus",
            "gross_claim_total",
            "purchase_returns_total",
            "system_claim_total",
            "supplier_printed_claim_total",
            "settlement_discount_amount",
            "net_amount_to_pay",
            "payment_entry",
            "settlement_discount_journal_entry",
            "accounting_reconciliation_journal_entries",
            "accounting_settlement_status",
            "accounting_settlement_date",
            "notes",
        ],
    )
    claims = frappe.get_all(
        "Supplier Claim",
        filters=filters,
        fields=fields,
        order_by="period_to asc, modified asc",
        limit_page_length=500,
    )
    rows: list[dict] = []
    for claim in claims:
        posting_date = claim.get("accounting_settlement_date") or claim.get("period_to") or claim.get("period_from")
        linked_docs = []
        if claim.get("payment_entry"):
            linked_docs.append(_("Payment: {0}").format(claim.get("payment_entry")))
        if claim.get("settlement_discount_journal_entry"):
            linked_docs.append(_("Discount JE: {0}").format(claim.get("settlement_discount_journal_entry")))
        if claim.get("accounting_reconciliation_journal_entries"):
            linked_docs.append(_("Reconciliation JE(s): {0}").format(
                re.sub(r"\s+", ", ", claim.get("accounting_reconciliation_journal_entries") or "").strip(", ")
            ))
        notes = []
        notes.append(_("Gross {0}; Returns {1}; Net {2}").format(
            flt(claim.get("gross_claim_total"), 2),
            flt(claim.get("purchase_returns_total"), 2),
            flt(claim.get("net_amount_to_pay"), 2),
        ))
        if claim.get("accounting_settlement_status"):
            notes.append(_("Accounting: {0}").format(claim.get("accounting_settlement_status")))
        notes.extend(linked_docs)
        if claim.get("notes"):
            notes.append(claim.get("notes"))
        rows.append(
            {
                "posting_date": posting_date,
                "type": "Supplier Claim",
                "document_type": "Supplier Claim",
                "document": claim.name,
                "voucher_type": "Supplier Claim",
                "voucher_no": claim.name,
                "supplier_invoice_no": None,
                "debit": 0,
                "credit": 0,
                "running_balance": None,
                "status": _docstatus_label(claim.get("docstatus"), claim.get("status")),
                "related_return_case": None,
                "related_supplier_claim": claim.name,
                "notes": " | ".join([note for note in notes if note]),
                "is_cancelled": cint(claim.get("docstatus")) == 2,
                "affects_balance": 0,
                "source": "Supplier Claim",
                "claim_purchase_returns_total": flt(claim.get("purchase_returns_total")),
                "claim_settlement_discount_amount": flt(claim.get("settlement_discount_amount")),
            }
        )
    return rows


def _draft_purchase_invoice_rows(
    company: str,
    supplier: str,
    from_date: str | None,
    to_date: str | None,
) -> list[dict]:
    if not frappe.has_permission("Purchase Invoice", "read"):
        return []
    filters: dict[str, Any] = {"company": company, "supplier": supplier, "docstatus": 0}
    if from_date and to_date:
        filters["posting_date"] = ["between", [getdate(from_date), getdate(to_date)]]
    elif from_date:
        filters["posting_date"] = [">=", getdate(from_date)]
    elif to_date:
        filters["posting_date"] = ["<=", getdate(to_date)]
    fields = _safe_fields(
        "Purchase Invoice",
        [
            "name",
            "posting_date",
            "bill_no",
            "is_return",
            "grand_total",
            "rounded_total",
            "disable_rounded_total",
            "outstanding_amount",
            "status",
            "docstatus",
            "custom_supplier_claim",
            "custom_pharmacy_return_case",
        ],
    )
    rows = []
    for invoice in frappe.get_all("Purchase Invoice", filters=filters, fields=fields, limit_page_length=500):
        amount = abs(_posting_total(invoice))
        is_return = cint(invoice.get("is_return"))
        rows.append(
            {
                "posting_date": invoice.get("posting_date"),
                "type": "Draft Purchase Return" if is_return else "Draft Purchase Invoice",
                "document_type": "Purchase Invoice",
                "document": invoice.name,
                "voucher_type": "Purchase Invoice",
                "voucher_no": invoice.name,
                "supplier_invoice_no": invoice.get("bill_no"),
                "debit": amount if is_return else 0,
                "credit": 0 if is_return else amount,
                "running_balance": None,
                "status": _docstatus_label(invoice.get("docstatus"), invoice.get("status")),
                "related_return_case": invoice.get("custom_pharmacy_return_case"),
                "related_supplier_claim": invoice.get("custom_supplier_claim"),
                "notes": _("Draft only — does not affect official GL balance."),
                "is_cancelled": 0,
                "affects_balance": 0,
                "source": "Draft Purchase Invoice",
                "outstanding_amount": flt(invoice.get("outstanding_amount")),
            }
        )
    return rows


def _draft_payment_entry_rows(
    company: str,
    supplier: str,
    from_date: str | None,
    to_date: str | None,
) -> list[dict]:
    if not frappe.has_permission("Payment Entry", "read"):
        return []
    filters: dict[str, Any] = {"company": company, "party_type": "Supplier", "party": supplier, "docstatus": 0}
    if from_date and to_date:
        filters["posting_date"] = ["between", [getdate(from_date), getdate(to_date)]]
    elif from_date:
        filters["posting_date"] = [">=", getdate(from_date)]
    elif to_date:
        filters["posting_date"] = ["<=", getdate(to_date)]
    fields = _safe_fields(
        "Payment Entry",
        [
            "name",
            "posting_date",
            "payment_type",
            "mode_of_payment",
            "paid_amount",
            "received_amount",
            "unallocated_amount",
            "reference_no",
            "status",
            "docstatus",
            "custom_supplier_claim",
            "custom_pharmacy_return_case",
            "custom_supplier_refund_method",
        ],
    )
    rows = []
    for payment in frappe.get_all("Payment Entry", filters=filters, fields=fields, limit_page_length=500):
        is_refund = payment.get("payment_type") == "Receive" or bool(payment.get("custom_supplier_refund_method"))
        amount = abs(flt(payment.get("received_amount") if is_refund else payment.get("paid_amount")))
        rows.append(
            {
                "posting_date": payment.get("posting_date"),
                "type": "Draft Supplier Refund" if is_refund else "Draft Payment Entry",
                "document_type": "Payment Entry",
                "document": payment.name,
                "voucher_type": "Payment Entry",
                "voucher_no": payment.name,
                "supplier_invoice_no": None,
                "debit": 0 if is_refund else amount,
                "credit": amount if is_refund else 0,
                "running_balance": None,
                "status": _docstatus_label(payment.get("docstatus"), payment.get("status")),
                "related_return_case": payment.get("custom_pharmacy_return_case"),
                "related_supplier_claim": payment.get("custom_supplier_claim"),
                "notes": _("Draft only — does not affect official GL balance."),
                "is_cancelled": 0,
                "affects_balance": 0,
                "source": "Draft Payment Entry",
                "outstanding_amount": flt(payment.get("unallocated_amount")),
            }
        )
    return rows


def _sort_rows(rows: list[dict]) -> list[dict]:
    def key(row: dict):
        return (
            str(row.get("posting_date") or ""),
            1 if not cint(row.get("affects_balance")) else 0,
            str(row.get("document_type") or row.get("voucher_type") or ""),
            str(row.get("document") or row.get("voucher_no") or ""),
        )

    return sorted(rows, key=key)


def _build_statement(
    company: str,
    supplier: str,
    from_date: str | None,
    to_date: str | None,
    include_cancelled: bool,
    include_drafts: bool,
    only_outstanding: bool,
) -> dict:
    opening = _opening_balance(company, supplier, from_date, include_cancelled)
    balance = opening
    official_rows: list[dict] = []

    for gl in _gl_rows(company, supplier, from_date, to_date, include_cancelled):
        ctx = _voucher_context(gl.get("voucher_type"), gl.get("voucher_no"))
        debit = flt(gl.get("debit"))
        credit = flt(gl.get("credit"))
        balance = flt(balance + credit - debit, 6)
        row = {
            "posting_date": gl.get("posting_date"),
            "type": ctx.get("type") or gl.get("voucher_type"),
            "document_type": gl.get("voucher_type"),
            "document": gl.get("voucher_no"),
            "voucher_type": gl.get("voucher_type"),
            "voucher_no": gl.get("voucher_no"),
            "supplier_invoice_no": ctx.get("supplier_invoice_no"),
            "debit": debit,
            "credit": credit,
            "running_balance": balance,
            "status": "Cancelled" if cint(gl.get("is_cancelled")) else (ctx.get("status") or "Submitted"),
            "related_return_case": ctx.get("related_return_case"),
            "related_supplier_claim": ctx.get("related_supplier_claim"),
            "settlement_classification": ctx.get("settlement_classification") or "",
            "notes": ctx.get("notes") or gl.get("gl_remarks") or "",
            "is_cancelled": cint(gl.get("is_cancelled")),
            "affects_balance": 1,
            "source": "GL Entry",
            "accounts": gl.get("accounts"),
            "against_voucher_type": gl.get("against_voucher_type"),
            "against_voucher": gl.get("against_voucher"),
            "outstanding_amount": flt(ctx.get("outstanding_amount")),
            "is_purchase_return": cint(ctx.get("is_purchase_return")),
            "payment_type": ctx.get("payment_type"),
        }
        official_rows.append(row)

    closing = balance
    rows = list(official_rows)
    rows.extend(_claim_context_rows(company, supplier, from_date, to_date, include_cancelled, include_drafts))
    if include_drafts:
        rows.extend(_draft_purchase_invoice_rows(company, supplier, from_date, to_date))
        rows.extend(_draft_payment_entry_rows(company, supplier, from_date, to_date))

    if only_outstanding:
        filtered = []
        for row in rows:
            if row.get("document_type") == "Purchase Invoice" and abs(flt(row.get("outstanding_amount"))) > MONEY_TOLERANCE:
                filtered.append(row)
            elif row.get("document_type") == "Supplier Claim" and row.get("status") not in {"Paid", "Cancelled"}:
                filtered.append(row)
            elif not cint(row.get("affects_balance")) and abs(flt(row.get("outstanding_amount"))) > MONEY_TOLERANCE:
                filtered.append(row)
        rows = filtered

    rows = _sort_rows(rows)

    summary = {
        "opening_balance": opening,
        "total_invoices": 0,
        "total_payments": 0,
        "total_returns_credits": 0,
        "total_claim_deductions": 0,
        "total_refunds": 0,
        "adjustments_rounding": 0,
        "closing_balance": closing,
        "official_rows": len(official_rows),
        "displayed_rows": len(rows),
    }

    for row in official_rows:
        if row.get("document_type") == "Purchase Invoice" and not cint(row.get("is_purchase_return")):
            summary["total_invoices"] += flt(row.get("credit"))
        elif row.get("document_type") == "Purchase Invoice" and cint(row.get("is_purchase_return")):
            summary["total_returns_credits"] += flt(row.get("debit"))
        elif row.get("document_type") == "Payment Entry" and row.get("type") == "Supplier Refund":
            summary["total_refunds"] += max(abs(flt(row.get("debit"))), abs(flt(row.get("credit"))))
        elif row.get("document_type") == "Payment Entry":
            summary["total_payments"] += max(abs(flt(row.get("debit"))), abs(flt(row.get("credit"))))
        elif row.get("document_type") == "Journal Entry":
            summary["adjustments_rounding"] += max(abs(flt(row.get("debit"))), abs(flt(row.get("credit"))))

    claim_rows = [row for row in rows if row.get("document_type") == "Supplier Claim"]
    summary["total_claim_deductions"] = sum(abs(flt(row.get("claim_purchase_returns_total"))) for row in claim_rows)
    summary["adjustments_rounding"] += sum(abs(flt(row.get("claim_settlement_discount_amount"))) for row in claim_rows)

    for key, value in list(summary.items()):
        if isinstance(value, float):
            summary[key] = flt(value, 2)

    return {"summary": summary, "rows": rows}


@frappe.whitelist()
def get_bootstrap(company: str | None = None) -> dict:
    _require_read_access()
    company = company or _default_company()
    today = nowdate()
    return {
        "company": company,
        "from_date": get_first_day(add_months(today, -1)),
        "to_date": today,
        "currency": frappe.db.get_value("Company", company, "default_currency") if company else None,
    }


@frappe.whitelist()
def get_statement(
    company: str | None = None,
    supplier: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    include_cancelled: int | str | bool = 0,
    include_drafts: int | str | bool = 0,
    only_outstanding: int | str | bool = 0,
) -> dict:
    _require_read_access()
    company = company or _default_company()
    if not company or not frappe.db.exists("Company", company):
        frappe.throw(_("Select a valid Company."))
    if not supplier or not frappe.db.exists("Supplier", supplier):
        frappe.throw(_("Select a valid Supplier."))
    if not frappe.has_permission("Supplier", "read", supplier):
        frappe.throw(_("You are not permitted to read Supplier {0}.").format(frappe.bold(supplier)), frappe.PermissionError)
    if from_date and to_date and getdate(from_date) > getdate(to_date):
        frappe.throw(_("From Date cannot be after To Date."))

    supplier_label = frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier
    company_currency = frappe.db.get_value("Company", company, "default_currency")
    statement = _build_statement(
        company,
        supplier,
        from_date,
        to_date,
        _bool(include_cancelled),
        _bool(include_drafts),
        _bool(only_outstanding),
    )
    return {
        "company": company,
        "supplier": supplier,
        "supplier_name": supplier_label,
        "from_date": from_date,
        "to_date": to_date,
        "currency": company_currency,
        "balance_note": _("Net Supplier Balance = previous balance + Credit - Debit. Invoices increase supplier balance, while payments / purchase returns / refunds reduce it. Positive balance means amount payable to supplier; negative balance means supplier credit / refund due to pharmacy."),
        **statement,
    }
