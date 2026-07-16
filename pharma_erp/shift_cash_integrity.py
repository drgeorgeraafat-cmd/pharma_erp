"""Shift cash integrity controls for v0.7.64.

All cash-drawer outflows are validated server-side before accounting submit.
The same module also enforces one canonical Pharmacy Shift link on Payment
Entry and Journal Entry documents that touch a configured Cash Drawer account.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

TOLERANCE = 0.000001
SHIFT_FIELD = "custom_pharmacy_shift"
JE_SHIFT_FIELD = "custom_pharmacy_shift"
SCM_LINK_FIELD = "custom_shift_cash_movement"


def _has_field(doctype: str, fieldname: str) -> bool:
    try:
        return bool(frappe.get_meta(doctype).has_field(fieldname))
    except Exception:
        return False


def _money(value) -> float:
    return flt(value or 0, 6)


def _format_currency(value, account=None, company=None):
    currency = None
    if account:
        currency = frappe.db.get_value("Account", account, "account_currency")
    if not currency and company:
        currency = frappe.db.get_value("Company", company, "default_currency")
    return frappe.format_value(
        _money(value),
        {"fieldtype": "Currency", "options": currency or "EGP"},
    )


def cash_drawer_for_account(account: str, company: str | None = None):
    account = str(account or "").strip()
    if not account or not frappe.db.exists("DocType", "Cash Drawer"):
        return None
    filters = {"cash_account": account, "enabled": 1}
    if company:
        filters["company"] = company
    rows = frappe.get_all(
        "Cash Drawer",
        filters=filters,
        fields=["name", "company", "cash_account", "current_active_shift"],
        order_by="creation asc",
        limit_page_length=2,
    )
    if len(rows) > 1:
        frappe.throw(
            _("Cash account {0} is linked to more than one enabled Cash Drawer.").format(account)
        )
    return rows[0] if rows else None


def _shift_row(shift_name: str):
    if not shift_name or not frappe.db.exists("Pharmacy Shift Closing", shift_name):
        return None
    meta = frappe.get_meta("Pharmacy Shift Closing")
    fields = ["name", "docstatus", "company", "status", "start_time", "end_time", "cash_account"]
    for fieldname in ("custom_shift_operational_status", "custom_cash_drawer"):
        if meta.has_field(fieldname):
            fields.append(fieldname)
    return frappe.db.get_value("Pharmacy Shift Closing", shift_name, fields, as_dict=True)


def _shift_is_active(row) -> bool:
    if not row or cint(row.docstatus) != 0 or row.status == "Closed" or row.end_time:
        return False
    state = str(row.get("custom_shift_operational_status") or "Active").strip()
    return state in ("", "Active")


def _shift_is_under_review(row) -> bool:
    if not row or cint(row.docstatus) != 0:
        return False
    state = str(row.get("custom_shift_operational_status") or "").strip()
    return state == "Under Review"


def resolve_active_shift(company: str, account: str, preferred_shift: str | None = None):
    drawer = cash_drawer_for_account(account, company)
    if not drawer:
        return None

    candidates = []
    for value in (preferred_shift, drawer.get("current_active_shift")):
        value = str(value or "").strip()
        if value and value not in candidates:
            candidates.append(value)

    rows = frappe.get_all(
        "Pharmacy Shift Closing",
        filters={"company": company, "docstatus": 0, "cash_account": account},
        fields=["name", "creation"],
        order_by="creation desc",
        limit_page_length=50,
    )
    candidates.extend(row.name for row in rows if row.name not in candidates)

    for shift_name in candidates:
        row = _shift_row(shift_name)
        if _shift_is_active(row):
            return row
    return None


def validate_shift_for_drawer(
    shift_name: str,
    company: str,
    account: str,
    *,
    allow_under_review: bool = False,
):
    row = _shift_row(shift_name)
    if not row:
        frappe.throw(_("Pharmacy Shift {0} was not found.").format(shift_name or ""))
    if row.company != company:
        frappe.throw(_("Pharmacy Shift belongs to another company."))
    if row.cash_account and row.cash_account != account:
        frappe.throw(
            _("Pharmacy Shift {0} is linked to cash account {1}, not {2}.").format(
                row.name, row.cash_account, account
            )
        )
    if _shift_is_active(row):
        return row
    if allow_under_review and _shift_is_under_review(row):
        return row
    frappe.throw(
        _("Cash Drawer transactions can only be posted to the active Pharmacy Shift. Shift {0} is not active.").format(
            row.name
        )
    )


def get_gl_balance(account: str, company: str, posting_date=None) -> float:
    posting_date = getdate(posting_date or now_datetime())
    value = frappe.db.sql(
        """
        select coalesce(sum(debit - credit), 0)
        from `tabGL Entry`
        where company = %s
          and account = %s
          and is_cancelled = 0
          and posting_date <= %s
        """,
        (company, account, posting_date),
    )[0][0]
    return _money(value)


def guard_outgoing_cash(
    *,
    account: str,
    amount,
    company: str,
    posting_date=None,
    document_label: str | None = None,
):
    amount = _money(amount)
    if amount <= TOLERANCE or not cash_drawer_for_account(account, company):
        return

    frappe.db.sql("select name from `tabAccount` where name=%s for update", (account,))
    available = get_gl_balance(account, company, posting_date)
    shortage = _money(amount - available)
    if shortage > TOLERANCE:
        frappe.throw(
            _(
                "Cash Drawer balance is insufficient.<br>"
                "Account: <b>{0}</b><br>"
                "Available balance: <b>{1}</b><br>"
                "Requested outgoing amount: <b>{2}</b><br>"
                "Shortage: <b>{3}</b><br>"
                "Document: <b>{4}</b>"
            ).format(
                account,
                _format_currency(available, account, company),
                _format_currency(amount, account, company),
                _format_currency(shortage, account, company),
                document_label or _("New transaction"),
            ),
            title=_("Negative Cash Drawer Blocked"),
        )


def _legacy_payment_shift(doc):
    for fieldname in (
        "custom_collection_shift",
        "custom_sales_shift",
        "custom_delivery_shift",
    ):
        if _has_field("Payment Entry", fieldname):
            value = str(doc.get(fieldname) or "").strip()
            if value:
                return value
    return ""


def validate_payment_entry_shift(doc, method=None):
    touched = []
    for account in (doc.get("paid_from"), doc.get("paid_to")):
        drawer = cash_drawer_for_account(account, doc.company)
        if drawer:
            touched.append((account, drawer))
    if not touched:
        return
    if len({row[0] for row in touched}) > 1:
        frappe.throw(_("One Payment Entry cannot use two different Cash Drawer accounts."))

    account = touched[0][0]
    preferred = str(doc.get(SHIFT_FIELD) or "").strip() if _has_field("Payment Entry", SHIFT_FIELD) else ""
    preferred = preferred or _legacy_payment_shift(doc)
    shift = resolve_active_shift(doc.company, account, preferred)
    if not shift:
        frappe.throw(
            _("No active Pharmacy Shift is linked to Cash Drawer account {0}.").format(account)
        )
    validate_shift_for_drawer(shift.name, doc.company, account)
    if _has_field("Payment Entry", SHIFT_FIELD):
        doc.set(SHIFT_FIELD, shift.name)


def before_submit_payment_entry_cash_guard(doc, method=None):
    validate_payment_entry_shift(doc, method)
    account = str(doc.get("paid_from") or "").strip()
    if not cash_drawer_for_account(account, doc.company):
        return
    amount = _money(doc.get("paid_amount") or doc.get("base_paid_amount"))
    guard_outgoing_cash(
        account=account,
        amount=amount,
        company=doc.company,
        posting_date=doc.posting_date,
        document_label=f"Payment Entry {doc.name or '[New]'}",
    )


def validate_journal_entry_shift(doc, method=None):
    drawer_accounts = []
    for row in doc.get("accounts") or []:
        if cash_drawer_for_account(row.account, doc.company):
            drawer_accounts.append(row.account)
    drawer_accounts = list(dict.fromkeys(drawer_accounts))
    if not drawer_accounts:
        return
    if len(drawer_accounts) > 1:
        frappe.throw(_("One Journal Entry cannot use two different Cash Drawer accounts."))

    account = drawer_accounts[0]
    preferred = str(doc.get(JE_SHIFT_FIELD) or "").strip() if _has_field("Journal Entry", JE_SHIFT_FIELD) else ""
    allow_review = bool(getattr(doc.flags, "allow_under_review_shift_posting", False))
    if preferred:
        shift = validate_shift_for_drawer(
            preferred, doc.company, account, allow_under_review=allow_review
        )
    else:
        shift = resolve_active_shift(doc.company, account)
        if not shift:
            frappe.throw(
                _("No active Pharmacy Shift is linked to Cash Drawer account {0}.").format(account)
            )
    if _has_field("Journal Entry", JE_SHIFT_FIELD):
        doc.set(JE_SHIFT_FIELD, shift.name)


def before_submit_journal_entry_cash_guard(doc, method=None):
    validate_journal_entry_shift(doc, method)
    by_account = {}
    for row in doc.get("accounts") or []:
        if not cash_drawer_for_account(row.account, doc.company):
            continue
        debit = _money(row.get("debit_in_account_currency"))
        credit = _money(row.get("credit_in_account_currency"))
        by_account[row.account] = _money(by_account.get(row.account, 0) + credit - debit)
    for account, outgoing in by_account.items():
        if outgoing > TOLERANCE:
            guard_outgoing_cash(
                account=account,
                amount=outgoing,
                company=doc.company,
                posting_date=doc.posting_date,
                document_label=f"Journal Entry {doc.name or '[New]'}",
            )


def validate_shift_cash_movement_guard(doc):
    if str(doc.get("direction") or "") != "Out":
        return
    guard_outgoing_cash(
        account=doc.source_account,
        amount=doc.amount,
        company=doc.company,
        posting_date=get_datetime(doc.movement_date or now_datetime()).date(),
        document_label=f"Shift Cash Movement {doc.name or '[New]'}",
    )


def validate_employee_advance_guard(doc):
    guard_outgoing_cash(
        account=doc.cash_account,
        amount=doc.advance_amount,
        company=doc.company,
        posting_date=doc.advance_date,
        document_label=f"Employee Cash Advance {doc.name or '[New]'}",
    )


def before_cancel_payment_entry_link_guard(doc, method=None):
    if not _has_field("Payment Entry", SCM_LINK_FIELD):
        return
    movement = str(doc.get(SCM_LINK_FIELD) or "").strip()
    if not movement:
        return
    if getattr(doc.flags, "from_shift_cash_movement_cancel", False):
        return
    status = frappe.db.get_value("Shift Cash Movement", movement, "docstatus")
    if status == 1:
        frappe.throw(
            _("Cancel Shift Cash Movement {0}; its linked Payment Entry will be reversed automatically.").format(movement),
            title=_("Linked Shift Cash Movement"),
        )
