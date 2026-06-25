import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, nowdate

from pharma_erp.pharma_erp.report.treasury_daily_review.treasury_daily_review import (
    _get_accounts,
    _get_opening_balances,
)
from pharma_erp.treasury_access import (
    can_emergency_submit_treasury,
    can_manage_treasury,
    can_operate_treasury,
    can_view_treasury,
)


TOLERANCE = 0.005
OPEN_CARD_STATUSES = [
    "Draft",
    "Awaiting Bank Settlement",
    "Partially Settled",
    "Disputed",
]
OPEN_RECONCILIATION_STATUSES = ["Draft", "Reviewed"]


class TreasuryDayClosing(Document):
    def before_insert(self):
        self._validate_operator_access()
        self.status = "Draft"
        self.prepared_by = frappe.session.user
        self.prepared_at = now_datetime()
        self.reviewed_by = None
        self.reviewed_at = None
        self.approval_note = None
        self._set_closing_key()

    def validate(self):
        self._validate_operator_access()
        self._normalize()
        self._set_closing_key()
        self._validate_unique_day()
        self.refresh_snapshot()

    def before_submit(self):
        if not can_manage_treasury():
            frappe.throw(
                _("Only Treasury Manager, Accounts Manager, or System Manager can close a Treasury day."),
                frappe.PermissionError,
            )

        prepared_by = self.prepared_by or self.owner
        self_approval = prepared_by == frappe.session.user
        if self_approval and not can_emergency_submit_treasury():
            frappe.throw(
                _("The user who prepared this closing cannot approve the same closing. A different Treasury Manager must approve it."),
                frappe.PermissionError,
            )

        self.refresh_snapshot()
        self._validate_blockers()
        self._validate_account_review()

        self.status = "Closed"
        self.reviewed_by = frappe.session.user
        self.reviewed_at = now_datetime()
        self.approval_note = (
            _("Emergency self-approval by System Manager.")
            if self_approval
            else _("Approved by a separate Treasury approver.")
        )

    def on_submit(self):
        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "status": "Closed",
                "reviewed_by": self.reviewed_by or frappe.session.user,
                "reviewed_at": self.reviewed_at or now_datetime(),
            },
            update_modified=False,
        )

    def before_cancel(self):
        if not can_manage_treasury():
            frappe.throw(
                _("Only Treasury Manager, Accounts Manager, or System Manager can cancel a Treasury day closing."),
                frappe.PermissionError,
            )

    def on_cancel(self):
        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "status": "Cancelled",
                "closing_key": None,
                "approval_note": _("Cancelled by {0}.").format(frappe.session.user),
            },
            update_modified=False,
        )

    def _validate_operator_access(self):
        if not can_operate_treasury():
            frappe.throw(
                _("Only Treasury Operator, Treasury Manager, Accounts Manager, or System Manager can create or edit a Treasury day closing."),
                frappe.PermissionError,
            )
        if not self.is_new() and self.docstatus == 0 and not can_manage_treasury():
            owner = frappe.db.get_value(self.doctype, self.name, "owner") or self.owner
            if owner and owner != frappe.session.user:
                frappe.throw(
                    _("Treasury Operator can edit only closings created by the same user."),
                    frappe.PermissionError,
                )

    def _normalize(self):
        self.company = str(self.company or "").strip()
        if not self.company or not frappe.db.exists("Company", self.company):
            frappe.throw(_("Select a valid Company."))
        self.closing_date = getdate(self.closing_date or nowdate())
        if self.closing_date > getdate(nowdate()):
            frappe.throw(_("Treasury closing date cannot be in the future."))
        self.currency = frappe.db.get_value("Company", self.company, "default_currency") or ""

    def _set_closing_key(self):
        if self.company and self.closing_date and self.docstatus != 2:
            self.closing_key = f"{self.company}::{getdate(self.closing_date)}"

    def _validate_unique_day(self):
        filters = {
            "company": self.company,
            "closing_date": self.closing_date,
            "docstatus": ["!=", 2],
            "name": ["!=", self.name or ""],
        }
        existing = frappe.db.get_value(self.doctype, filters, "name")
        if existing:
            frappe.throw(
                _("Treasury day {0} already has closing document {1}.").format(
                    self.closing_date, frappe.bold(existing)
                )
            )

    def refresh_snapshot(self):
        existing = {
            row.account: {
                "actual_closing": row.actual_closing,
                "difference_reason": row.difference_reason,
                "notes": row.notes,
            }
            for row in self.accounts or []
            if row.account
        }
        snapshot = build_day_closing_snapshot(
            company=self.company,
            closing_date=self.closing_date,
            actual_rows=existing,
            exclude_closing=self.name,
        )

        self.set("accounts", [])
        for row in snapshot["accounts"]:
            self.append("accounts", row)

        summary = snapshot["summary"]
        self.opening_total = summary["opening_total"]
        self.total_in = summary["total_in"]
        self.total_out = summary["total_out"]
        self.expected_closing_total = summary["expected_closing_total"]
        self.actual_closing_total = summary["actual_closing_total"]
        self.difference_total = summary["difference_total"]
        self.open_shift_count = summary["open_shift_count"]
        self.draft_document_count = summary["draft_document_count"]
        self.pending_card_count = summary["pending_card_count"]
        self.pending_card_amount = summary["pending_card_amount"]
        self.pending_reconciliation_count = summary["pending_reconciliation_count"]
        self.pending_reconciliation_amount = summary["pending_reconciliation_amount"]
        self.clearing_balance = summary["clearing_balance"]
        self.documented_pending = summary["documented_pending"]
        self.unmatched_clearing_balance = summary["unmatched_clearing_balance"]
        self.blocker_count = len(snapshot["blockers"])
        self.blocker_details = json.dumps(snapshot["blockers"], ensure_ascii=False, default=str)
        self.snapshot_generated_at = now_datetime()

    def _validate_blockers(self):
        blockers = json.loads(self.blocker_details or "[]")
        if blockers:
            lines = "<br>".join(
                f"• {frappe.utils.escape_html(str(row.get('message') or row))}"
                for row in blockers
            )
            frappe.throw(
                _("Treasury day cannot be closed until these blockers are resolved:")
                + "<br>"
                + lines,
                title=_("Treasury Closing Blocked"),
            )

    def _validate_account_review(self):
        if not self.accounts:
            frappe.throw(_("Treasury closing has no Cash or Bank accounts to review."))

        unresolved = []
        for row in self.accounts:
            row.actual_closing = flt(row.actual_closing)
            row.difference = flt(row.actual_closing) - flt(row.expected_closing)
            if abs(row.difference) <= TOLERANCE:
                row.difference = 0
                row.review_status = "Matched"
            elif str(row.difference_reason or "").strip():
                row.review_status = "Explained"
            else:
                row.review_status = "Unresolved"
                unresolved.append(row.account)

        self.actual_closing_total = sum(flt(row.actual_closing) for row in self.accounts)
        self.difference_total = sum(flt(row.difference) for row in self.accounts)
        if unresolved:
            frappe.throw(
                _("Enter a difference reason for these accounts before closing: {0}").format(
                    ", ".join(unresolved)
                )
            )


def build_day_closing_snapshot(company, closing_date, actual_rows=None, exclude_closing=None):
    if not can_view_treasury():
        frappe.throw(_("You do not have access to Treasury day closing."), frappe.PermissionError)

    company = str(company or "").strip()
    if not company or not frappe.db.exists("Company", company):
        frappe.throw(_("Select a valid Company."))
    closing_date = getdate(closing_date or nowdate())
    if closing_date > getdate(nowdate()):
        frappe.throw(_("Treasury closing date cannot be in the future."))

    actual_rows = actual_rows or {}
    if isinstance(actual_rows, str):
        actual_rows = frappe.parse_json(actual_rows) or {}
    if isinstance(actual_rows, list):
        actual_rows = {
            str(row.get("account") or ""): row
            for row in actual_rows
            if row.get("account")
        }

    accounts = _get_accounts(company)
    account_names = [row.name for row in accounts]
    opening_by_account = _get_opening_balances(company, account_names, closing_date)
    period_totals, gl_row_count = _get_period_totals(company, account_names, closing_date)

    account_rows = []
    for account in accounts:
        opening = flt(opening_by_account.get(account.name))
        debit = flt(period_totals[account.name]["debit"])
        credit = flt(period_totals[account.name]["credit"])
        expected = opening + debit - credit
        supplied = actual_rows.get(account.name) or {}
        supplied_actual = supplied.get("actual_closing")
        actual = expected if supplied_actual in (None, "") else flt(supplied_actual)
        difference = actual - expected
        reason = str(supplied.get("difference_reason") or "").strip()
        review_status = (
            "Matched"
            if abs(difference) <= TOLERANCE
            else "Explained"
            if reason
            else "Unresolved"
        )
        account_rows.append(
            {
                "account": account.name,
                "account_type": account.account_type,
                "currency": account.account_currency
                or frappe.db.get_value("Company", company, "default_currency"),
                "opening_balance": opening,
                "total_in": debit,
                "total_out": credit,
                "expected_closing": expected,
                "actual_closing": actual,
                "difference": 0 if abs(difference) <= TOLERANCE else difference,
                "review_status": review_status,
                "difference_reason": reason,
                "notes": supplied.get("notes") or "",
            }
        )

    blockers = _get_day_blockers(company, closing_date, exclude_closing)
    pending = _get_pending_snapshot(company, closing_date)
    summary = {
        "opening_total": sum(flt(row["opening_balance"]) for row in account_rows),
        "total_in": sum(flt(row["total_in"]) for row in account_rows),
        "total_out": sum(flt(row["total_out"]) for row in account_rows),
        "expected_closing_total": sum(flt(row["expected_closing"]) for row in account_rows),
        "actual_closing_total": sum(flt(row["actual_closing"]) for row in account_rows),
        "difference_total": sum(flt(row["difference"]) for row in account_rows),
        "open_shift_count": pending["open_shift_count"],
        "draft_document_count": pending["draft_document_count"],
        "pending_card_count": pending["pending_card_count"],
        "pending_card_amount": pending["pending_card_amount"],
        "pending_reconciliation_count": pending["pending_reconciliation_count"],
        "pending_reconciliation_amount": pending["pending_reconciliation_amount"],
        "clearing_balance": pending["clearing_balance"],
        "documented_pending": pending["documented_pending"],
        "unmatched_clearing_balance": pending["unmatched_clearing_balance"],
        "gl_row_count": gl_row_count,
        "gl_truncated": 0,
    }
    return {
        "company": company,
        "closing_date": str(closing_date),
        "currency": frappe.db.get_value("Company", company, "default_currency") or "",
        "accounts": account_rows,
        "summary": summary,
        "blockers": blockers,
        "pending": pending,
    }



def _get_period_totals(company, account_names, closing_date):
    totals = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})
    if not account_names:
        return totals, 0
    placeholders = ", ".join(["%s"] * len(account_names))
    rows = frappe.db.sql(
        f"""
        select account, sum(debit) as debit, sum(credit) as credit, count(*) as row_count
        from `tabGL Entry`
        where company = %s
          and posting_date = %s
          and is_cancelled = 0
          and account in ({placeholders})
        group by account
        """,
        [company, closing_date, *account_names],
        as_dict=True,
    )
    row_count = 0
    for row in rows:
        totals[row.account]["debit"] = flt(row.debit)
        totals[row.account]["credit"] = flt(row.credit)
        row_count += cint(row.row_count)
    return totals, row_count

def get_recent_day_closings(company=None, limit=20):
    if not frappe.db.exists("DocType", "Treasury Day Closing"):
        return []
    filters = {}
    if company:
        filters["company"] = company
    rows = frappe.get_all(
        "Treasury Day Closing",
        filters=filters,
        fields=[
            "name",
            "company",
            "closing_date",
            "status",
            "docstatus",
            "expected_closing_total",
            "actual_closing_total",
            "difference_total",
            "blocker_count",
            "pending_card_amount",
            "pending_reconciliation_amount",
            "unmatched_clearing_balance",
            "prepared_by",
            "reviewed_by",
            "reviewed_at",
            "override_count",
            "modified",
        ],
        order_by="closing_date desc, creation desc",
        limit_page_length=max(1, min(cint(limit) or 20, 100)),
    )
    for row in rows:
        for fieldname in (
            "expected_closing_total",
            "actual_closing_total",
            "difference_total",
            "pending_card_amount",
            "pending_reconciliation_amount",
            "unmatched_clearing_balance",
        ):
            row[fieldname] = flt(row.get(fieldname))
    return rows


def _get_day_blockers(company, closing_date, exclude_closing=None):
    blockers = []
    day_start = f"{closing_date} 00:00:00"
    day_end = f"{closing_date} 23:59:59"

    if frappe.db.exists("DocType", "Pharmacy Shift Closing"):
        open_shifts = frappe.get_all(
            "Pharmacy Shift Closing",
            filters={
                "docstatus": 0,
                "start_time": ["<=", day_end],
            },
            fields=["name", "status", "start_time", "cash_account", "custom_cash_drawer"],
            limit_page_length=1000,
        )
        for row in open_shifts:
            status = str(row.get("status") or "").strip().lower()
            if status in {"closed", "cancelled"}:
                continue
            blockers.append(
                {
                    "type": "open_shift",
                    "doctype": "Pharmacy Shift Closing",
                    "document": row.name,
                    "message": _("Open shift {0} must be closed first.").format(row.name),
                }
            )

    _append_draft_blockers(
        blockers,
        "Shift Cash Movement",
        {"docstatus": 0, "movement_date": ["between", [day_start, day_end]]},
        closing_date,
    )
    _append_draft_blockers(
        blockers,
        "Treasury Voucher",
        {"docstatus": 0, "posting_date": closing_date},
        closing_date,
    )
    _append_draft_blockers(
        blockers,
        "Payment Entry",
        {
            "docstatus": 0,
            "payment_type": "Internal Transfer",
            "posting_date": closing_date,
        },
        closing_date,
    )

    if frappe.db.exists("DocType", "Treasury Day Closing"):
        filters = {
            "company": company,
            "closing_date": closing_date,
            "docstatus": ["!=", 2],
        }
        if exclude_closing:
            filters["name"] = ["!=", exclude_closing]
        duplicate = frappe.db.get_value("Treasury Day Closing", filters, "name")
        if duplicate:
            blockers.append(
                {
                    "type": "duplicate_closing",
                    "doctype": "Treasury Day Closing",
                    "document": duplicate,
                    "message": _("Another Treasury day closing exists: {0}.").format(duplicate),
                }
            )
    return blockers


def _append_draft_blockers(blockers, doctype, filters, closing_date):
    if not frappe.db.exists("DocType", doctype):
        return
    rows = frappe.get_all(
        doctype,
        filters=filters,
        fields=["name"],
        order_by="creation asc",
        limit_page_length=1000,
    )
    for row in rows:
        blockers.append(
            {
                "type": "draft_document",
                "doctype": doctype,
                "document": row.name,
                "message": _("Draft {0} {1} must be submitted or cancelled before closing {2}.").format(
                    doctype, row.name, closing_date
                ),
            }
        )


def _get_pending_snapshot(company, closing_date):
    day_end = f"{closing_date} 23:59:59"
    open_shift_count = 0
    if frappe.db.exists("DocType", "Pharmacy Shift Closing"):
        open_shift_count = frappe.db.count(
            "Pharmacy Shift Closing",
            filters={"docstatus": 0, "start_time": ["<=", day_end]},
        )

    draft_document_count = 0
    if frappe.db.exists("DocType", "Shift Cash Movement"):
        draft_document_count += frappe.db.count(
            "Shift Cash Movement",
            filters={
                "docstatus": 0,
                "movement_date": ["between", [f"{closing_date} 00:00:00", day_end]],
            },
        )
    if frappe.db.exists("DocType", "Treasury Voucher"):
        draft_document_count += frappe.db.count(
            "Treasury Voucher", {"docstatus": 0, "posting_date": closing_date}
        )
    if frappe.db.exists("DocType", "Payment Entry"):
        draft_document_count += frappe.db.count(
            "Payment Entry",
            {
                "docstatus": 0,
                "payment_type": "Internal Transfer",
                "posting_date": closing_date,
            },
        )

    card_count = 0
    card_amount = 0.0
    if frappe.db.exists("DocType", "Card Settlement Batch"):
        card_rows = frappe.get_all(
            "Card Settlement Batch",
            filters={
                "company": company,
                "docstatus": ["!=", 2],
                "status": ["in", OPEN_CARD_STATUSES],
            },
            fields=["name", "outstanding_amount", "close_time", "creation", "status"],
            limit_page_length=1000,
        )
        for row in card_rows:
            basis = row.get("close_time") or row.get("creation")
            if basis and get_datetime(basis) > get_datetime(day_end):
                continue
            outstanding = flt(row.get("outstanding_amount"))
            if outstanding <= TOLERANCE and row.get("status") not in ("Draft", "Disputed"):
                continue
            card_count += 1
            card_amount += outstanding

    reconciliation_count = 0
    reconciliation_amount = 0.0
    if frappe.db.exists("DocType", "Shift Payment Reconciliation"):
        rec_rows = frappe.get_all(
            "Shift Payment Reconciliation",
            filters={
                "company": company,
                "docstatus": ["!=", 2],
                "status": ["in", OPEN_RECONCILIATION_STATUSES],
            },
            fields=["name", "expected_amount", "to_time", "creation"],
            limit_page_length=1000,
        )
        for row in rec_rows:
            basis = row.get("to_time") or row.get("creation")
            if basis and get_datetime(basis) > get_datetime(day_end):
                continue
            reconciliation_count += 1
            reconciliation_amount += flt(row.get("expected_amount"))

    clearing_accounts = set()
    if frappe.db.exists("DocType", "Card POS Terminal"):
        terminal_rows = frappe.get_all(
            "Card POS Terminal",
            filters={"company": company, "enabled": 1},
            fields=["clearing_account"],
            limit_page_length=0,
        )
        clearing_accounts.update(row.clearing_account for row in terminal_rows if row.clearing_account)
    if frappe.db.exists("DocType", "Payment Method Clearing Setup"):
        setup_rows = frappe.get_all(
            "Payment Method Clearing Setup",
            filters={"company": company, "enabled": 1},
            fields=["clearing_account"],
            limit_page_length=0,
        )
        clearing_accounts.update(row.clearing_account for row in setup_rows if row.clearing_account)

    clearing_balance = 0.0
    if clearing_accounts:
        placeholders = ", ".join(["%s"] * len(clearing_accounts))
        result = frappe.db.sql(
            f"""
            select coalesce(sum(debit - credit), 0)
            from `tabGL Entry`
            where company = %s
              and posting_date <= %s
              and is_cancelled = 0
              and account in ({placeholders})
            """,
            [company, closing_date, *sorted(clearing_accounts)],
        )
        clearing_balance = flt(result[0][0] if result else 0)

    documented_pending = card_amount + reconciliation_amount
    return {
        "open_shift_count": cint(open_shift_count),
        "draft_document_count": cint(draft_document_count),
        "pending_card_count": cint(card_count),
        "pending_card_amount": card_amount,
        "pending_reconciliation_count": cint(reconciliation_count),
        "pending_reconciliation_amount": reconciliation_amount,
        "clearing_balance": clearing_balance,
        "documented_pending": documented_pending,
        "unmatched_clearing_balance": clearing_balance - documented_pending,
    }


@frappe.whitelist()
def refresh_day_closing_snapshot(name):
    if not can_operate_treasury():
        frappe.throw(_("You do not have permission to refresh Treasury closing."), frappe.PermissionError)
    doc = frappe.get_doc("Treasury Day Closing", name)
    if doc.docstatus != 0:
        frappe.throw(_("Only Draft closing can be refreshed."))
    doc.refresh_snapshot()
    doc.save(ignore_permissions=True)
    return {"name": doc.name, "message": _("Treasury closing snapshot refreshed.")}
