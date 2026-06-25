"""Treasury day-closing controls shared by Treasury documents and page APIs."""

import json

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

from pharma_erp.treasury_access import can_emergency_submit_treasury


PROTECTED_TREASURY_DOCTYPES = {
    "Shift Cash Movement": ("company", "movement_date"),
    "Treasury Voucher": ("company", "posting_date"),
    "Card Bank Settlement": ("company", "settlement_date"),
    "Pharmacy Shift Closing": ("company", "start_time"),
}


def get_closed_day(company, posting_date):
    company = str(company or "").strip()
    if not company or not posting_date or not frappe.db.exists("DocType", "Treasury Day Closing"):
        return None

    closing_date = getdate(posting_date)
    rows = frappe.get_all(
        "Treasury Day Closing",
        filters={
            "company": company,
            "closing_date": closing_date,
            "docstatus": 1,
            "status": "Closed",
        },
        fields=["name", "closing_date", "reviewed_by", "reviewed_at"],
        order_by="creation desc",
        limit_page_length=1,
    )
    return rows[0] if rows else None


def ensure_treasury_date_open(company, posting_date, operation=None, document=None):
    """Block treasury activity on a submitted closing date.

    System Manager remains an emergency path. Every bypass is recorded on the
    Treasury Day Closing itself so it is visible during audit.
    """
    closed = get_closed_day(company, posting_date)
    if not closed:
        return

    if can_emergency_submit_treasury():
        _record_emergency_override(closed.name, operation, document)
        return

    frappe.throw(
        _(
            "Treasury day {0} is closed by {1}. Cancel the closing or ask a System Manager to perform a recorded emergency override."
        ).format(getdate(posting_date), closed.name),
        title=_("Treasury Day Closed"),
    )


def validate_treasury_document_date(doc, method=None):
    if getattr(doc.flags, "ignore_treasury_day_closing", False):
        return

    company, posting_date = _resolve_document_company_date(doc)
    if not company or not posting_date:
        return

    ensure_treasury_date_open(
        company,
        posting_date,
        operation=method or "validate",
        document=doc,
    )


def before_cancel_treasury_document(doc, method=None):
    if getattr(doc.flags, "ignore_treasury_day_closing", False):
        return

    company, posting_date = _resolve_document_company_date(doc)
    if not company or not posting_date:
        return

    ensure_treasury_date_open(
        company,
        posting_date,
        operation=method or "cancel",
        document=doc,
    )


def _resolve_document_company_date(doc):
    if doc.doctype == "Payment Entry":
        company = getattr(doc, "company", None)
        accounts = [getattr(doc, "paid_from", None), getattr(doc, "paid_to", None)]
        if not any(_is_treasury_account(account, company) for account in accounts if account):
            return None, None
        return company, getattr(doc, "posting_date", None)

    if doc.doctype == "Journal Entry":
        company = getattr(doc, "company", None)
        accounts = [getattr(row, "account", None) for row in getattr(doc, "accounts", [])]
        if not any(_is_treasury_account(account, company) for account in accounts if account):
            return None, None
        return company, getattr(doc, "posting_date", None)

    fields = PROTECTED_TREASURY_DOCTYPES.get(doc.doctype)
    if not fields:
        return None, None
    company_field, date_field = fields
    company = getattr(doc, company_field, None)
    if not company and doc.doctype == "Pharmacy Shift Closing":
        cash_account = getattr(doc, "cash_account", None)
        if cash_account:
            company = frappe.db.get_value("Account", cash_account, "company")
    return company, getattr(doc, date_field, None)


def _is_treasury_account(account, company=None):
    account = str(account or "").strip()
    if not account:
        return False
    meta = frappe.db.get_value(
        "Account",
        account,
        ["company", "account_type", "root_type", "is_group", "disabled"],
        as_dict=True,
    ) or {}
    if not meta or meta.get("is_group") or meta.get("disabled"):
        return False
    if company and meta.get("company") and meta.get("company") != company:
        return False
    if meta.get("account_type") in {"Cash", "Bank"}:
        return True

    if frappe.db.exists("DocType", "Card POS Terminal"):
        if frappe.db.exists("Card POS Terminal", {"clearing_account": account}):
            return True
    if frappe.db.exists("DocType", "Payment Method Clearing Setup"):
        if frappe.db.exists("Payment Method Clearing Setup", {"clearing_account": account}):
            return True
    return False


def _record_emergency_override(closing_name, operation, document):
    # frappe.flags is a frappe._dict: a missing key can resolve to None rather
    # than honoring getattr's default. Always normalize the request cache to a
    # set before checking membership so emergency overrides cannot fail during
    # validation of a new document.
    cache = getattr(frappe.flags, "treasury_day_override_log", None)
    if not isinstance(cache, set):
        cache = set()

    key = (
        closing_name,
        getattr(document, "doctype", ""),
        getattr(document, "name", ""),
        str(operation or ""),
    )
    if key in cache:
        return
    cache.add(key)
    frappe.flags.treasury_day_override_log = cache

    doctype = getattr(document, "doctype", "Treasury operation") or "Treasury operation"
    name = getattr(document, "name", None) or "New document"
    payload = {
        "user": frappe.session.user,
        "timestamp": str(now_datetime()),
        "operation": str(operation or "Treasury operation"),
        "document_type": doctype,
        "document_name": name,
    }
    message = _(
        "Emergency closed-day override by {0}: {1} on {2} {3}."
    ).format(
        frappe.bold(frappe.session.user),
        frappe.bold(payload["operation"]),
        frappe.bold(doctype),
        frappe.bold(name),
    )

    if frappe.db.exists("Treasury Day Closing", closing_name):
        closing = frappe.get_doc("Treasury Day Closing", closing_name)
        closing.add_comment("Info", message)
        if closing.meta.has_field("override_count"):
            frappe.db.sql(
                """
                update `tabTreasury Day Closing`
                set override_count = coalesce(override_count, 0) + 1,
                    last_override_by = %s,
                    last_override_at = %s,
                    last_override_note = %s
                where name = %s
                """,
                (
                    frappe.session.user,
                    now_datetime(),
                    json.dumps(payload, ensure_ascii=False),
                    closing_name,
                ),
            )
