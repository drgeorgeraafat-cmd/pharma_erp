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
                "settlement_classification": "Supplier Claim",
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
            "custom_payment_classification",
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
                "settlement_classification": invoice.get("custom_payment_classification") or "",
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
        "total_unallocated_advances": 0,
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
            if flt(row.get("outstanding_amount")) > MONEY_TOLERANCE:
                summary["total_unallocated_advances"] += flt(row.get("outstanding_amount"))
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


# -----------------------------------------------------------------------------
# Supplier Running Account v0.7.42 — Draft Supplier Payment creation
# -----------------------------------------------------------------------------

@frappe.whitelist()
def get_supplier_payment_defaults(company: str, supplier: str | None = None) -> dict:
    """Return lightweight defaults for the Create Supplier Payment Draft dialog."""
    company = _sra_payment_required(company, "Company")
    default_currency = frappe.get_cached_value("Company", company, "default_currency")
    paid_from = (
        frappe.get_cached_value("Company", company, "default_bank_account")
        or frappe.get_cached_value("Company", company, "default_cash_account")
        or ""
    )
    mode_of_payment = ""
    if paid_from and frappe.db.exists("DocType", "Mode of Payment Account"):
        mode_of_payment = frappe.db.get_value(
            "Mode of Payment Account",
            {"company": company, "default_account": paid_from, "parenttype": "Mode of Payment"},
            "parent",
        ) or ""
    return {
        "company": company,
        "supplier": supplier,
        "currency": default_currency,
        "paid_from": paid_from,
        "mode_of_payment": mode_of_payment,
    }


@frappe.whitelist()
def get_supplier_payment_candidates(
    company: str,
    supplier: str,
    include_claim_linked: int = 0,
    limit: int = 200,
    from_date: str | None = None,
    to_date: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """Outstanding submitted Purchase Invoices that can be used for payment allocation.

    Read-only. Supports date range and invoice-number search so the user can add
    invoices intentionally to a payment list instead of scrolling a long table.
    """
    from frappe.utils import getdate

    company = _sra_payment_required(company, "Company")
    supplier = _sra_payment_required(supplier, "Supplier")

    filters = [
        ["company", "=", company],
        ["supplier", "=", supplier],
        ["docstatus", "=", 1],
        ["is_return", "=", 0],
    ]
    if from_date:
        filters.append(["posting_date", ">=", getdate(from_date)])
    if to_date:
        filters.append(["posting_date", "<=", getdate(to_date)])

    query = (search or "").strip()
    or_filters = []
    if query:
        like = f"%{query}%"
        or_filters = [["name", "like", like], ["bill_no", "like", like]]

    rows = frappe.get_all(
        "Purchase Invoice",
        filters=filters,
        or_filters=or_filters or None,
        fields=[
            "name",
            "posting_date",
            "bill_no",
            "outstanding_amount",
            "grand_total",
            "rounded_total",
            "status",
            "custom_payment_classification",
            "custom_supplier_claim" if _sra_has_field("Purchase Invoice", "custom_supplier_claim") else "name",
        ],
        order_by="posting_date asc, creation asc",
        limit_page_length=int(limit or 200),
    )
    out = []
    for row in rows:
        outstanding = _sra_flt(row.get("outstanding_amount"))
        if outstanding <= 0.005:
            continue
        linked_claim = row.get("custom_supplier_claim") if _sra_has_field("Purchase Invoice", "custom_supplier_claim") else None
        if not linked_claim:
            linked_claim = _sra_find_claim_for_invoice(row.name)
        if linked_claim and not int(include_claim_linked or 0):
            continue
        out.append({
            "name": row.name,
            "posting_date": row.posting_date,
            "supplier_invoice_no": row.get("bill_no") or "",
            "outstanding_amount": outstanding,
            "settlement_classification": row.get("custom_payment_classification") or "",
            "status": row.get("status") or "",
            "related_supplier_claim": linked_claim or "",
        })
    return out


@frappe.whitelist()
def create_supplier_payment_draft(args: dict | None = None) -> dict:
    """Create a Draft Payment Entry for a supplier.

    Safety rule: this method only saves Draft. It never submits and never reconciles
    automatically. The user must review and submit Payment Entry manually.
    """
    if isinstance(args, str):
        args = frappe.parse_json(args) or {}
    args = frappe._dict(args or {})
    company = _sra_payment_required(args.get("company"), "Company")
    supplier = _sra_payment_required(args.get("supplier"), "Supplier")
    posting_date = args.get("posting_date") or _sra_nowdate()
    paid_from = _sra_payment_required(args.get("paid_from"), "Paid From Account")
    amount = _sra_flt(args.get("amount"))
    if amount <= 0:
        frappe.throw(_("Payment amount must be greater than zero."))

    allocation_mode = args.get("allocation_mode") or "Oldest Outstanding First"
    include_claim_linked = int(args.get("include_claim_linked") or 0)
    allocations = []

    if allocation_mode == "Oldest Outstanding First":
        remaining = amount
        for inv in get_supplier_payment_candidates(company, supplier, include_claim_linked=include_claim_linked, limit=500):
            if remaining <= 0.005:
                break
            alloc = min(_sra_flt(inv.get("outstanding_amount")), remaining)
            if alloc > 0:
                allocations.append({"invoice": inv["name"], "allocated_amount": alloc, "outstanding_amount": inv.get("outstanding_amount")})
                remaining -= alloc
    elif allocation_mode == "Selected Invoices":
        for row in args.get("invoices") or []:
            row = frappe._dict(row)
            inv = row.get("invoice")
            alloc = _sra_flt(row.get("allocated_amount"))
            if inv and alloc > 0:
                _sra_validate_invoice_candidate(company, supplier, inv, alloc, include_claim_linked)
                allocations.append({"invoice": inv, "allocated_amount": alloc})
        if not allocations:
            frappe.throw(_("Select at least one invoice and enter allocation amount."))
    elif allocation_mode == "Unallocated Advance":
        allocations = []
    else:
        frappe.throw(_("Unsupported Allocation Mode: {0}").format(allocation_mode))

    total_allocated = sum(_sra_flt(row.get("allocated_amount")) for row in allocations)
    if total_allocated - amount > 0.005:
        frappe.throw(_("Allocated amount cannot exceed payment amount."))

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Pay"
    pe.company = company
    pe.posting_date = posting_date
    pe.party_type = "Supplier"
    pe.party = supplier
    pe.mode_of_payment = args.get("mode_of_payment") or None
    pe.paid_from = paid_from
    pe.paid_to = _sra_get_supplier_party_account(company, supplier)
    pe.paid_amount = amount
    pe.received_amount = amount
    pe.reference_no = args.get("reference_no") or None
    pe.reference_date = posting_date if pe.reference_no else None
    pe.remarks = args.get("remarks") or _("Draft supplier payment created from Supplier Running Account.")

    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    if pe.paid_from:
        pe.paid_from_account_currency = frappe.get_cached_value("Account", pe.paid_from, "account_currency") or company_currency
    if pe.paid_to:
        pe.paid_to_account_currency = frappe.get_cached_value("Account", pe.paid_to, "account_currency") or company_currency
    pe.source_exchange_rate = 1
    pe.target_exchange_rate = 1

    for allocation in allocations:
        inv_name = allocation["invoice"]
        inv = frappe.db.get_value(
            "Purchase Invoice",
            inv_name,
            ["grand_total", "rounded_total", "outstanding_amount"],
            as_dict=True,
        ) or {}
        pe.append("references", {
            "reference_doctype": "Purchase Invoice",
            "reference_name": inv_name,
            "total_amount": _sra_payment_invoice_total(inv),
            "outstanding_amount": _sra_flt(inv.get("outstanding_amount")),
            "allocated_amount": _sra_flt(allocation.get("allocated_amount")),
        })

    try:
        pe.set_missing_values()
    except Exception:
        pass
    try:
        pe.set_amounts()
    except Exception:
        pass
    pe.flags.ignore_permissions = False
    pe.insert()
    return {"name": pe.name, "doctype": pe.doctype, "allocated_amount": total_allocated, "unallocated_amount": amount - total_allocated}


def _sra_payment_required(value, label: str) -> str:
    value = (value or "").strip() if isinstance(value, str) else value
    if not value:
        frappe.throw(_("{0} is required.").format(_(label)))
    return value


def _sra_has_field(doctype: str, fieldname: str) -> bool:
    try:
        return frappe.get_meta(doctype).has_field(fieldname)
    except Exception:
        return False


def _sra_flt(value) -> float:
    from frappe.utils import flt
    return flt(value)


def _sra_nowdate() -> str:
    from frappe.utils import nowdate
    return nowdate()


def _sra_find_claim_for_invoice(invoice: str) -> str:
    if frappe.db.exists("DocType", "Supplier Claim Invoice"):
        return frappe.db.get_value(
            "Supplier Claim Invoice",
            {"purchase_invoice": invoice, "parenttype": "Supplier Claim"},
            "parent",
        ) or ""
    return ""


def _sra_validate_invoice_candidate(company: str, supplier: str, invoice: str, allocated_amount: float, include_claim_linked: int = 0) -> None:
    inv = frappe.db.get_value(
        "Purchase Invoice",
        invoice,
        ["company", "supplier", "docstatus", "is_return", "outstanding_amount"],
        as_dict=True,
    )
    if not inv:
        frappe.throw(_("Purchase Invoice {0} not found.").format(invoice))
    if inv.company != company or inv.supplier != supplier or int(inv.docstatus or 0) != 1 or int(inv.is_return or 0):
        frappe.throw(_("Purchase Invoice {0} is not eligible for this supplier payment.").format(invoice))
    outstanding = _sra_flt(inv.outstanding_amount)
    if outstanding <= 0.005:
        frappe.throw(_("Purchase Invoice {0} has no outstanding amount.").format(invoice))
    if allocated_amount - outstanding > 0.005:
        frappe.throw(_("Allocated amount for {0} exceeds outstanding amount.").format(invoice))
    linked_claim = _sra_find_claim_for_invoice(invoice)
    if linked_claim and not int(include_claim_linked or 0):
        frappe.throw(_("Purchase Invoice {0} is linked to Supplier Claim {1}. Enable include linked claims if intentional.").format(invoice, linked_claim))


def _sra_get_supplier_party_account(company: str, supplier: str) -> str:
    try:
        from erpnext.accounts.party import get_party_account
        return get_party_account("Supplier", supplier, company)
    except Exception:
        account = frappe.db.get_value("Party Account", {"parenttype": "Supplier", "parent": supplier, "company": company}, "account")
        if account:
            return account
        default_payable = frappe.get_cached_value("Company", company, "default_payable_account")
        if default_payable:
            return default_payable
        frappe.throw(_("Could not determine supplier payable account for {0}.").format(supplier))


def _sra_payment_invoice_total(inv: dict) -> float:
    rounded = _sra_flt(inv.get("rounded_total"))
    grand = _sra_flt(inv.get("grand_total"))
    return rounded if abs(rounded) > 0.005 else grand



# -----------------------------------------------------------------------------
# Supplier Running Account v0.7.43 — Draft Supplier Claim creation
# -----------------------------------------------------------------------------

def _sra_claim_period_date_expr() -> str:
    return "COALESCE(pi.bill_date, pi.posting_date)"


def _sra_claim_existing_link(purchase_invoice: str, exclude_claim: str | None = None) -> dict | None:
    """Return a non-cancelled Supplier Claim that already contains this PI/credit.

    This deliberately checks Draft claims as well as Submitted claims so a return
    credit / debit note cannot be placed in two draft claims from the running
    account flow.
    """
    if not purchase_invoice:
        return None

    pi_meta = frappe.get_meta("Purchase Invoice")
    if pi_meta.has_field("custom_supplier_claim"):
        linked = frappe.db.get_value("Purchase Invoice", purchase_invoice, "custom_supplier_claim")
        if linked and linked != exclude_claim and frappe.db.exists("Supplier Claim", linked):
            docstatus = cint(frappe.db.get_value("Supplier Claim", linked, "docstatus"))
            if docstatus < 2:
                return {"supplier_claim": linked, "docstatus": docstatus, "source": "Purchase Invoice link"}

    if not (frappe.db.exists("DocType", "Supplier Claim") and frappe.db.exists("DocType", "Supplier Claim Invoice")):
        return None

    params = {"purchase_invoice": purchase_invoice, "exclude_claim": exclude_claim or ""}
    exclude_clause = "AND sc.name != %(exclude_claim)s" if exclude_claim else ""
    rows = frappe.db.sql(
        f"""
        SELECT sc.name AS supplier_claim, sc.docstatus, sc.status
        FROM `tabSupplier Claim Invoice` sci
        INNER JOIN `tabSupplier Claim` sc
            ON sc.name = sci.parent
           AND sci.parenttype = 'Supplier Claim'
        WHERE sci.purchase_invoice = %(purchase_invoice)s
          AND IFNULL(sc.docstatus, 0) < 2
          {exclude_clause}
        ORDER BY sc.modified DESC
        LIMIT 1
        """,
        params,
        as_dict=True,
    )
    if rows:
        return dict(rows[0])
    return None


def _sra_claim_purchase_invoice_fields() -> list[str]:
    fields = [
        "name",
        "company",
        "supplier",
        "docstatus",
        "is_return",
        "bill_no",
        "bill_date",
        "posting_date",
        "grand_total",
        "rounded_total",
        "disable_rounded_total",
        "outstanding_amount",
        "status",
    ]
    for fieldname in [
        "custom_payment_classification",
        "custom_supplier_claim",
        "custom_pharmacy_return_case",
        "custom_exclude_from_supplier_claim",
    ]:
        if _sra_has_field("Purchase Invoice", fieldname):
            fields.append(fieldname)
    return fields


def _sra_claim_invoice_snapshot(purchase_invoice: str) -> frappe._dict:
    invoice = frappe.db.get_value(
        "Purchase Invoice",
        purchase_invoice,
        _sra_claim_purchase_invoice_fields(),
        as_dict=True,
    )
    if not invoice:
        frappe.throw(_("Purchase Invoice {0} was not found.").format(frappe.bold(purchase_invoice)))
    return frappe._dict(invoice)


def _sra_validate_claim_invoice_candidate(
    company: str,
    supplier: str,
    purchase_invoice: str,
    included_amount: float,
    exclude_claim: str | None = None,
) -> frappe._dict:
    invoice = _sra_claim_invoice_snapshot(purchase_invoice)
    if invoice.company != company or invoice.supplier != supplier:
        frappe.throw(_("Purchase Invoice {0} belongs to another company or supplier.").format(frappe.bold(purchase_invoice)))
    if cint(invoice.docstatus) != 1:
        frappe.throw(_("Purchase Invoice {0} must be submitted before it can be included in a Supplier Claim.").format(frappe.bold(purchase_invoice)))

    if cint(invoice.get("custom_exclude_from_supplier_claim")):
        frappe.throw(_("Purchase Invoice {0} is excluded from Supplier Claims.").format(frappe.bold(purchase_invoice)))

    existing_link = _sra_claim_existing_link(purchase_invoice, exclude_claim=exclude_claim)
    if existing_link:
        frappe.throw(_("Purchase Invoice / Debit Note {0} is already used in Supplier Claim {1}.").format(
            frappe.bold(purchase_invoice), frappe.bold(existing_link.get("supplier_claim"))
        ))

    outstanding = flt(invoice.outstanding_amount)
    included = flt(included_amount)
    tolerance = 0.01
    is_return = cint(invoice.is_return)

    if is_return:
        if included >= -tolerance:
            frappe.throw(_("Return Credit / Debit Note {0} must be included as a negative amount.").format(frappe.bold(purchase_invoice)))
        if outstanding >= -tolerance:
            frappe.throw(_("Return Credit / Debit Note {0} has no open supplier credit outstanding.").format(frappe.bold(purchase_invoice)))
        if abs(included) - abs(outstanding) > tolerance:
            frappe.throw(_("Included credit amount for {0} exceeds its open supplier credit outstanding {1}.").format(
                frappe.bold(purchase_invoice), abs(outstanding)
            ))
    else:
        if included <= tolerance:
            frappe.throw(_("Supplier Invoice {0} must be included as a positive amount.").format(frappe.bold(purchase_invoice)))
        if outstanding <= tolerance:
            frappe.throw(_("Supplier Invoice {0} has no payable outstanding.").format(frappe.bold(purchase_invoice)))
        if included - outstanding > tolerance:
            frappe.throw(_("Included amount for {0} exceeds its payable outstanding {1}.").format(
                frappe.bold(purchase_invoice), outstanding
            ))
        classification = invoice.get("custom_payment_classification") or ""
        if _sra_has_field("Purchase Invoice", "custom_payment_classification") and classification != "Claim Invoice":
            frappe.throw(_("Supplier Invoice {0} is classified as {1}, not Claim Invoice.").format(
                frappe.bold(purchase_invoice), frappe.bold(classification or _("Not Set"))
            ))

    return invoice


@frappe.whitelist()
def get_supplier_claim_draft_candidates(
    company: str,
    supplier: str,
    from_date: str | None = None,
    to_date: str | None = None,
    search: str | None = None,
    limit: int = 300,
) -> list[dict]:
    """Return open Claim Invoice candidates plus open return credits.

    The result is read-only and excludes invoices / debit notes already present in
    any non-cancelled Supplier Claim, including Draft claims.
    """
    _require_read_access()
    if not frappe.has_permission("Purchase Invoice", "read"):
        frappe.throw(_("You are not permitted to read Purchase Invoices."), frappe.PermissionError)

    company = _sra_payment_required(company, "Company")
    supplier = _sra_payment_required(supplier, "Supplier")
    if from_date and to_date and getdate(from_date) > getdate(to_date):
        frappe.throw(_("From Date cannot be after To Date."))

    params: dict[str, Any] = {"company": company, "supplier": supplier, "limit": cint(limit or 300)}
    date_expr = _sra_claim_period_date_expr()
    conditions = [
        "pi.company = %(company)s",
        "pi.supplier = %(supplier)s",
        "pi.docstatus = 1",
        "ABS(IFNULL(pi.outstanding_amount, 0)) > 0.005",
    ]

    if from_date:
        params["from_date"] = getdate(from_date)
        conditions.append(f"{date_expr} >= %(from_date)s")
    if to_date:
        params["to_date"] = getdate(to_date)
        conditions.append(f"{date_expr} <= %(to_date)s")

    has_classification = _db_has_column("Purchase Invoice", "custom_payment_classification")
    if has_classification:
        classification_select = "pi.custom_payment_classification AS settlement_classification"
        claim_candidate_condition = "IFNULL(pi.custom_payment_classification, '') = 'Claim Invoice'"
    else:
        classification_select = "'' AS settlement_classification"
        claim_candidate_condition = "1 = 1"

    if _db_has_column("Purchase Invoice", "custom_supplier_claim"):
        conditions.append("IFNULL(pi.custom_supplier_claim, '') = ''")
    if _db_has_column("Purchase Invoice", "custom_exclude_from_supplier_claim"):
        conditions.append("IFNULL(pi.custom_exclude_from_supplier_claim, 0) = 0")

    return_case_select = (
        "pi.custom_pharmacy_return_case AS related_return_case"
        if _db_has_column("Purchase Invoice", "custom_pharmacy_return_case")
        else "'' AS related_return_case"
    )

    search_text = (search or "").strip()
    if search_text:
        params["search"] = f"%{search_text}%"
        search_parts = ["pi.name LIKE %(search)s", "IFNULL(pi.bill_no, '') LIKE %(search)s"]
        if _db_has_column("Purchase Invoice", "custom_pharmacy_return_case"):
            search_parts.append("IFNULL(pi.custom_pharmacy_return_case, '') LIKE %(search)s")
        conditions.append("(" + " OR ".join(search_parts) + ")")

    if frappe.db.exists("DocType", "Supplier Claim Invoice") and frappe.db.exists("DocType", "Supplier Claim"):
        conditions.append(
            """
            NOT EXISTS (
                SELECT 1
                FROM `tabSupplier Claim Invoice` sci
                INNER JOIN `tabSupplier Claim` sc
                    ON sc.name = sci.parent
                   AND sci.parenttype = 'Supplier Claim'
                WHERE sci.purchase_invoice = pi.name
                  AND IFNULL(sc.docstatus, 0) < 2
            )
            """
        )

    conditions.append(
        f"""
        (
            (IFNULL(pi.is_return, 0) = 1 AND IFNULL(pi.outstanding_amount, 0) < -0.005)
            OR
            (IFNULL(pi.is_return, 0) = 0 AND IFNULL(pi.outstanding_amount, 0) > 0.005 AND {claim_candidate_condition})
        )
        """
    )

    rows = frappe.db.sql(
        f"""
        SELECT
            pi.name,
            pi.posting_date,
            pi.bill_no,
            pi.bill_date,
            pi.grand_total,
            pi.rounded_total,
            pi.disable_rounded_total,
            pi.outstanding_amount,
            pi.is_return,
            pi.status,
            {classification_select},
            {return_case_select}
        FROM `tabPurchase Invoice` pi
        WHERE {' AND '.join(conditions)}
        ORDER BY {date_expr} ASC, pi.posting_date ASC, pi.creation ASC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )

    out: list[dict] = []
    for row in rows:
        outstanding = flt(row.get("outstanding_amount"))
        is_return = cint(row.get("is_return"))
        included_amount = -abs(outstanding) if is_return else outstanding
        out.append({
            "purchase_invoice": row.name,
            "posting_date": row.posting_date,
            "supplier_invoice_no": row.bill_no or "",
            "supplier_invoice_date": row.bill_date or row.posting_date,
            "grand_total": _posting_total(row),
            "outstanding_amount": outstanding,
            "included_amount": included_amount,
            "is_return": is_return,
            "candidate_type": "Return Credit / Debit Note" if is_return else "Claim Invoice",
            "invoice_status": row.status or "",
            "settlement_classification": row.get("settlement_classification") or "",
            "related_return_case": row.get("related_return_case") or "",
        })
    return out


@frappe.whitelist()
def create_supplier_claim_draft(args: dict | None = None) -> dict:
    """Create a Draft Supplier Claim from selected running-account candidates.

    Safety rule: this method only inserts Draft. It never submits, never creates
    GL, and never marks Purchase Invoices / Debit Notes as linked. Submission and
    accounting reconciliation remain manual review steps.
    """
    if isinstance(args, str):
        args = frappe.parse_json(args) or {}
    args = frappe._dict(args or {})

    company = _sra_payment_required(args.get("company"), "Company")
    supplier = _sra_payment_required(args.get("supplier"), "Supplier")
    period_from = args.get("period_from") or args.get("from_date") or nowdate()
    period_to = args.get("period_to") or args.get("to_date") or nowdate()
    if getdate(period_from) > getdate(period_to):
        frappe.throw(_("Period From cannot be after Period To."))
    if not frappe.has_permission("Supplier Claim", "create"):
        frappe.throw(_("You are not permitted to create Supplier Claims."), frappe.PermissionError)

    selected_rows = []
    seen = set()
    for raw in args.get("invoices") or []:
        row = frappe._dict(raw)
        purchase_invoice = (row.get("purchase_invoice") or row.get("invoice") or "").strip()
        included_amount = flt(row.get("included_amount"))
        if not purchase_invoice or abs(included_amount) <= 0.005:
            continue
        if purchase_invoice in seen:
            frappe.throw(_("Purchase Invoice / Debit Note {0} is duplicated in the selected rows.").format(frappe.bold(purchase_invoice)))
        seen.add(purchase_invoice)
        invoice = _sra_validate_claim_invoice_candidate(company, supplier, purchase_invoice, included_amount)
        selected_rows.append((invoice, included_amount))

    if not selected_rows:
        frappe.throw(_("Select at least one Claim Invoice or Return Credit / Debit Note."))

    gross = sum(amount for invoice, amount in selected_rows if amount > 0)
    returns_total = abs(sum(amount for invoice, amount in selected_rows if amount < 0))
    system_total = gross - returns_total
    if system_total < -0.005:
        frappe.throw(_("Selected Return Credits exceed selected Claim Invoices. Add payable invoices first or reduce selected credit amounts."))

    if args.get("net_amount_to_pay") in (None, ""):
        net_amount_to_pay = max(0, system_total)
    else:
        net_amount_to_pay = flt(args.get("net_amount_to_pay"))
    if net_amount_to_pay < -0.005 or net_amount_to_pay - system_total > 0.005:
        frappe.throw(_("Net Amount To Pay must be between zero and the System Claim Total."))

    supplier_printed_claim_total = (
        flt(args.get("supplier_printed_claim_total"))
        if args.get("supplier_printed_claim_total") not in (None, "")
        else system_total
    )

    claim = frappe.new_doc("Supplier Claim")
    claim.company = company
    claim.supplier = supplier
    claim.period_from = period_from
    claim.period_to = period_to
    claim.claim_basis = "Supplier Invoice Date"
    claim.supplier_printed_claim_total = supplier_printed_claim_total
    claim.net_amount_to_pay = net_amount_to_pay
    claim.payment_due_date = args.get("payment_due_date") or None
    claim.notes = args.get("notes") or _("Draft Supplier Claim created from Supplier Running Account. Review before Submit.")

    for invoice, included_amount in selected_rows:
        claim.append("invoices", {
            "purchase_invoice": invoice.name,
            "supplier_invoice_no": invoice.bill_no,
            "supplier_invoice_date": invoice.bill_date or invoice.posting_date,
            "posting_date": invoice.posting_date,
            "grand_total": _posting_total(invoice),
            "outstanding_amount": flt(invoice.outstanding_amount),
            "included_amount": included_amount,
            "is_return": cint(invoice.is_return),
            "invoice_status": invoice.status,
        })

    claim.insert()
    claim.reload()
    return {
        "name": claim.name,
        "doctype": claim.doctype,
        "docstatus": claim.docstatus,
        "gross_claim_total": flt(claim.gross_claim_total, 2),
        "purchase_returns_total": flt(claim.purchase_returns_total, 2),
        "system_claim_total": flt(claim.system_claim_total, 2),
        "settlement_discount_amount": flt(claim.settlement_discount_amount, 2),
        "net_amount_to_pay": flt(claim.net_amount_to_pay, 2),
    }

# -----------------------------------------------------------------------------
# Supplier Running Account v0.7.44 — Existing supplier advance allocation helper
# -----------------------------------------------------------------------------

@frappe.whitelist()
def get_supplier_unallocated_advances(
    company: str,
    supplier: str,
    from_date: str | None = None,
    to_date: str | None = None,
    search: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return submitted supplier Payment Entries with unallocated amount.

    Read-only helper for the SRA advance allocation dialog. It only lists
    official submitted Payment Entries; it does not mutate accounting.
    """
    _require_read_access()
    if not frappe.has_permission("Payment Entry", "read"):
        frappe.throw(_("You are not permitted to read Payment Entries."), frappe.PermissionError)

    company = _sra_payment_required(company, "Company")
    supplier = _sra_payment_required(supplier, "Supplier")
    params: dict[str, Any] = {"company": company, "supplier": supplier, "limit": cint(limit or 100)}
    conditions = [
        "pe.company = %(company)s",
        "pe.party_type = 'Supplier'",
        "pe.party = %(supplier)s",
        "pe.docstatus = 1",
        "pe.payment_type = 'Pay'",
        "IFNULL(pe.unallocated_amount, 0) > 0.005",
    ]
    if from_date:
        params["from_date"] = getdate(from_date)
        conditions.append("pe.posting_date >= %(from_date)s")
    if to_date:
        params["to_date"] = getdate(to_date)
        conditions.append("pe.posting_date <= %(to_date)s")
    search_text = (search or "").strip()
    if search_text:
        params["search"] = f"%{search_text}%"
        conditions.append("(pe.name LIKE %(search)s OR IFNULL(pe.reference_no, '') LIKE %(search)s OR IFNULL(pe.remarks, '') LIKE %(search)s)")

    rows = frappe.db.sql(
        f"""
        SELECT
            pe.name,
            pe.posting_date,
            pe.mode_of_payment,
            pe.paid_from,
            pe.paid_amount,
            pe.unallocated_amount,
            pe.reference_no,
            pe.reference_date,
            pe.remarks
        FROM `tabPayment Entry` pe
        WHERE {' AND '.join(conditions)}
        ORDER BY pe.posting_date ASC, pe.creation ASC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    return [
        {
            "payment_entry": row.name,
            "posting_date": row.posting_date,
            "mode_of_payment": row.mode_of_payment or "",
            "paid_from": row.paid_from or "",
            "paid_amount": flt(row.paid_amount, 2),
            "unallocated_amount": flt(row.unallocated_amount, 2),
            "reference_no": row.reference_no or "",
            "reference_date": row.reference_date,
            "remarks": row.remarks or "",
        }
        for row in rows
    ]


def _sra_validate_supplier_advance(company: str, supplier: str, payment_entry: str) -> frappe._dict:
    pe = frappe.db.get_value(
        "Payment Entry",
        payment_entry,
        ["name", "company", "party_type", "party", "docstatus", "payment_type", "unallocated_amount", "paid_amount", "posting_date"],
        as_dict=True,
    )
    if not pe:
        frappe.throw(_("Payment Entry {0} was not found.").format(frappe.bold(payment_entry)))
    if pe.company != company or pe.party_type != "Supplier" or pe.party != supplier:
        frappe.throw(_("Payment Entry {0} belongs to another company or supplier.").format(frappe.bold(payment_entry)))
    if cint(pe.docstatus) != 1 or pe.payment_type != "Pay":
        frappe.throw(_("Payment Entry {0} must be a submitted supplier payment.").format(frappe.bold(payment_entry)))
    if flt(pe.unallocated_amount) <= MONEY_TOLERANCE:
        frappe.throw(_("Payment Entry {0} has no unallocated advance amount.").format(frappe.bold(payment_entry)))
    return frappe._dict(pe)


def _sra_get_payment_reconciliation_doc(company: str, supplier: str, payment_entry: str | None = None):
    from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import PaymentReconciliation  # noqa: F401

    pr = frappe.new_doc("Payment Reconciliation")
    pr.company = company
    pr.party_type = "Supplier"
    pr.party = supplier
    pr.receivable_payable_account = _sra_get_supplier_party_account(company, supplier)
    pr.payment_limit = 1000
    pr.invoice_limit = 1000
    if payment_entry:
        pr.payment_name = payment_entry
    pr.get_unreconciled_entries()
    return pr


def _sra_find_reconciliation_payment(pr, payment_entry: str) -> frappe._dict | None:
    for payment in pr.get("payments") or []:
        if payment.get("reference_type") == "Payment Entry" and payment.get("reference_name") == payment_entry:
            return frappe._dict(payment.as_dict() if hasattr(payment, "as_dict") else payment)
    return None


def _sra_find_reconciliation_invoice(pr, purchase_invoice: str) -> frappe._dict | None:
    for invoice in pr.get("invoices") or []:
        if invoice.get("invoice_type") == "Purchase Invoice" and invoice.get("invoice_number") == purchase_invoice:
            return frappe._dict(invoice.as_dict() if hasattr(invoice, "as_dict") else invoice)
    return None


@frappe.whitelist()
def preview_supplier_advance_allocation(args: dict | None = None) -> dict:
    """Validate and preview applying an existing supplier advance to invoices.

    This method is read-only. It does not call Payment Reconciliation.reconcile().
    """
    if isinstance(args, str):
        args = frappe.parse_json(args) or {}
    args = frappe._dict(args or {})

    company = _sra_payment_required(args.get("company"), "Company")
    supplier = _sra_payment_required(args.get("supplier"), "Supplier")
    payment_entry = _sra_payment_required(args.get("payment_entry"), "Payment Entry")
    include_claim_linked = cint(args.get("include_claim_linked") or 0)
    pe = _sra_validate_supplier_advance(company, supplier, payment_entry)

    allocations = []
    total_allocated = 0.0
    seen = set()
    for raw in args.get("invoices") or []:
        row = frappe._dict(raw)
        invoice = (row.get("invoice") or row.get("purchase_invoice") or "").strip()
        amount = flt(row.get("allocated_amount"))
        if not invoice or amount <= MONEY_TOLERANCE:
            continue
        if invoice in seen:
            frappe.throw(_("Purchase Invoice {0} is duplicated in the allocation rows.").format(frappe.bold(invoice)))
        seen.add(invoice)
        _sra_validate_invoice_candidate(company, supplier, invoice, amount, include_claim_linked=include_claim_linked)
        inv = frappe.db.get_value("Purchase Invoice", invoice, ["name", "bill_no", "posting_date", "outstanding_amount"], as_dict=True) or {}
        allocations.append({
            "payment_entry": payment_entry,
            "purchase_invoice": invoice,
            "supplier_invoice_no": inv.get("bill_no") or "",
            "posting_date": inv.get("posting_date"),
            "invoice_outstanding": flt(inv.get("outstanding_amount"), 2),
            "allocated_amount": flt(amount, 2),
        })
        total_allocated += flt(amount)

    if not allocations:
        frappe.throw(_("Select at least one invoice and enter allocation amount."))
    if total_allocated - flt(pe.unallocated_amount) > MONEY_TOLERANCE:
        frappe.throw(_("Allocated amount {0} exceeds unallocated advance {1} for Payment Entry {2}.").format(
            flt(total_allocated, 2), flt(pe.unallocated_amount, 2), frappe.bold(payment_entry)
        ))

    return {
        "payment_entry": payment_entry,
        "available_advance": flt(pe.unallocated_amount, 2),
        "allocated_total": flt(total_allocated, 2),
        "remaining_advance": flt(flt(pe.unallocated_amount) - total_allocated, 2),
        "allocations": allocations,
        "read_only": 1,
    }


@frappe.whitelist()
def reconcile_supplier_advance_against_invoices(args: dict | None = None) -> dict:
    """Apply an existing supplier advance against selected Purchase Invoices.

    This is an explicit accounting action using ERPNext Payment Reconciliation.
    It does not create new GL on its own for normal Payment Entry vs Purchase
    Invoice reconciliation, but it mutates allocation/payment-ledger state.
    """
    if isinstance(args, str):
        args = frappe.parse_json(args) or {}
    args = frappe._dict(args or {})

    if not ({"Accounts Manager", "System Manager"}.intersection(set(frappe.get_roles())) or frappe.has_permission("Payment Entry", "write")):
        frappe.throw(_("You are not permitted to reconcile supplier advances."), frappe.PermissionError)

    preview = preview_supplier_advance_allocation(args)
    company = _sra_payment_required(args.get("company"), "Company")
    supplier = _sra_payment_required(args.get("supplier"), "Supplier")
    payment_entry = _sra_payment_required(args.get("payment_entry"), "Payment Entry")

    pr = _sra_get_payment_reconciliation_doc(company, supplier, payment_entry=payment_entry)
    payment_row = _sra_find_reconciliation_payment(pr, payment_entry)
    if not payment_row:
        frappe.throw(_("Payment Entry {0} is not available in ERPNext Payment Reconciliation. Refresh and try again.").format(frappe.bold(payment_entry)))

    invoice_rows = []
    for alloc in preview.get("allocations") or []:
        invoice_row = _sra_find_reconciliation_invoice(pr, alloc.get("purchase_invoice"))
        if not invoice_row:
            frappe.throw(_("Purchase Invoice {0} is not available in ERPNext Payment Reconciliation. Refresh and try again.").format(
                frappe.bold(alloc.get("purchase_invoice"))
            ))
        invoice_row = frappe._dict(invoice_row)
        # Limit each invoice copy to the amount explicitly selected in SRA.
        invoice_row.outstanding_amount = flt(alloc.get("allocated_amount"))
        invoice_rows.append(invoice_row)

    # Let ERPNext build the exact allocation rows for this Payment Entry and the
    # selected invoice portions, then reconcile explicitly.
    payment_copy = frappe._dict(payment_row)
    payment_copy.amount = flt(payment_row.get("amount") or payment_row.get("unreconciled_amount") or preview.get("available_advance"))
    pr.allocate_entries({"payments": [payment_copy], "invoices": invoice_rows})
    if not pr.get("allocation"):
        frappe.throw(_("ERPNext did not create any allocation rows. No reconciliation was applied."))
    pr.reconcile()

    return {
        "payment_entry": payment_entry,
        "allocated_total": preview.get("allocated_total"),
        "remaining_advance_before_refresh": preview.get("remaining_advance"),
        "reconciled": 1,
        "allocations": preview.get("allocations"),
    }

