import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from erpnext.accounts.utils import get_balance_on

from pharma_erp.treasury_access import (
    can_emergency_submit_treasury,
    can_manage_treasury,
    can_operate_treasury,
)


VOUCHER_RULES = {
    "General Expense": {
        "direction": "Out",
        "counter_root_type": "Expense",
        "categories": (
            "Rent",
            "Utilities",
            "Maintenance",
            "Office Supplies",
            "Transportation",
            "Administrative Expense",
            "Marketing Expense",
            "Miscellaneous Expense",
            "Other Expense",
        ),
    },
    "General Receipt": {
        "direction": "In",
        "counter_root_type": "Income",
        "categories": (
            "Other Income",
            "Cashback / Rebate",
            "Insurance Reimbursement",
            "Refund / Compensation",
            "Miscellaneous Receipt",
            "Other Receipt",
        ),
    },
}

AUDIT_FIELDS = (
    "request_status",
    "requested_by",
    "requested_at",
    "approved_by",
    "approved_at",
    "approval_note",
)


class TreasuryVoucher(Document):
    def before_insert(self):
        self._validate_operator_access()
        self.status = "Draft"
        self.request_status = "Pending Approval"
        self.requested_by = frappe.session.user
        self.requested_at = now_datetime()
        self.approved_by = None
        self.approved_at = None
        self.approval_note = None
        self.journal_entry = None
        self.posted_by = None
        self.posted_at = None

    def validate(self):
        self._validate_operator_access()
        self._protect_audit_fields()
        self._validate_and_normalize(check_live_balance=True)

    def before_submit(self):
        if not can_manage_treasury():
            frappe.throw(
                _("Only Treasury Manager, Accounts Manager, or System Manager can approve a Treasury Voucher."),
                frappe.PermissionError,
            )

        requested_by = self.requested_by or self.owner
        self_approval = requested_by == frappe.session.user
        if self_approval and not can_emergency_submit_treasury():
            frappe.throw(
                _("The user who requested this Treasury Voucher cannot approve the same request. A different Treasury Manager must approve it."),
                frappe.PermissionError,
            )

        self._lock_cash_bank_account()
        self._validate_and_normalize(check_live_balance=True)
        self.request_status = "Approved"
        self.approved_by = frappe.session.user
        self.approved_at = now_datetime()
        self.approval_note = (
            _("Emergency self-approval by System Manager.")
            if self_approval
            else _("Approved by a separate Treasury approver.")
        )

    def on_submit(self):
        journal_name = self._ensure_journal_entry()
        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "journal_entry": journal_name,
                "status": "Posted",
                "request_status": "Approved",
                "posted_by": frappe.session.user,
                "posted_at": now_datetime(),
                "approved_by": self.approved_by or frappe.session.user,
                "approved_at": self.approved_at or now_datetime(),
            },
            update_modified=False,
        )

    def before_cancel(self):
        if not can_manage_treasury():
            frappe.throw(
                _("Only Treasury Manager, Accounts Manager, or System Manager can cancel a Treasury Voucher."),
                frappe.PermissionError,
            )

        if not self.journal_entry:
            return
        journal = frappe.get_doc("Journal Entry", self.journal_entry)
        if journal.docstatus == 1:
            journal.flags.ignore_permissions = True
            journal.cancel()

    def on_cancel(self):
        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "status": "Cancelled",
                "request_status": "Cancelled",
                "approval_note": _("Cancelled by {0}.").format(frappe.session.user),
            },
            update_modified=False,
        )

    def _validate_operator_access(self):
        if not can_operate_treasury():
            frappe.throw(
                _("Only Treasury Operator, Treasury Manager, Accounts Manager, or System Manager can create or edit Treasury Vouchers."),
                frappe.PermissionError,
            )

        if not self.is_new() and self.docstatus == 0 and not can_manage_treasury():
            owner = frappe.db.get_value(self.doctype, self.name, "owner") or self.owner
            if owner and owner != frappe.session.user:
                frappe.throw(
                    _("Treasury Operator can edit only Treasury Vouchers created by the same user."),
                    frappe.PermissionError,
                )

    def _protect_audit_fields(self):
        if self.is_new() or not self.name:
            return
        existing = frappe.db.get_value(
            self.doctype,
            self.name,
            list(AUDIT_FIELDS),
            as_dict=True,
        ) or {}
        for fieldname in AUDIT_FIELDS:
            if fieldname in existing:
                setattr(self, fieldname, existing.get(fieldname))

        if not self.request_status:
            self.request_status = "Pending Approval"
        if not self.requested_by:
            self.requested_by = self.owner or frappe.session.user
        if not self.requested_at:
            self.requested_at = self.creation or now_datetime()

    def _validate_and_normalize(self, check_live_balance=True):
        self.company = str(self.company or "").strip()
        self.voucher_type = str(self.voucher_type or "").strip()
        self.category = str(self.category or "").strip()
        self.cash_bank_account = str(self.cash_bank_account or "").strip()
        self.counter_account = str(self.counter_account or "").strip()
        self.reference_no = str(self.reference_no or "").strip()
        self.beneficiary_or_payer = str(self.beneficiary_or_payer or "").strip()
        self.description = str(self.description or "").strip()
        self.amount = flt(self.amount)
        self.posting_date = getdate(self.posting_date or nowdate())
        self.reference_date = getdate(self.reference_date) if self.reference_date else None

        if not self.company or not frappe.db.exists("Company", self.company):
            frappe.throw(_("Select a valid Company."))
        if self.voucher_type not in VOUCHER_RULES:
            frappe.throw(_("Select a valid Voucher Type."))
        if self.posting_date > getdate(nowdate()):
            frappe.throw(_("Posting Date cannot be in the future."))
        if self.amount <= 0:
            frappe.throw(_("Amount must be greater than zero."))
        if not self.description:
            frappe.throw(_("Description is required."))
        if not self.cash_bank_account:
            frappe.throw(_("Cash / Bank Account is required."))
        if not self.counter_account:
            frappe.throw(_("Expense / Income Account is required."))
        if self.cash_bank_account == self.counter_account:
            frappe.throw(_("Cash / Bank Account and Counter Account cannot be the same."))

        rule = VOUCHER_RULES[self.voucher_type]
        allowed_categories = rule.get("categories") or ()
        if not self.category:
            self.category = allowed_categories[-1] if allowed_categories else "Other"
        elif allowed_categories and self.category not in allowed_categories:
            frappe.throw(_("Category is not valid for the selected Voucher Type."))

        cash_account = self._validate_account(
            self.cash_bank_account,
            _("Cash / Bank Account"),
        )
        if cash_account.root_type != "Asset" or cash_account.account_type not in ("Cash", "Bank"):
            frappe.throw(_("Cash / Bank Account must be an active Asset account of type Cash or Bank."))
        self._validate_not_active_shift_drawer(cash_account)

        counter_account = self._validate_account(
            self.counter_account,
            _("Expense / Income Account"),
        )
        if counter_account.root_type != rule["counter_root_type"]:
            frappe.throw(
                _("For {0}, the counter account must have Root Type {1}.").format(
                    self.voucher_type,
                    rule["counter_root_type"],
                )
            )

        company_currency = frappe.db.get_value("Company", self.company, "default_currency")
        if cash_account.account_currency != counter_account.account_currency:
            frappe.throw(_("Cash / Bank Account and Counter Account must use the same currency."))
        if company_currency and cash_account.account_currency != company_currency:
            frappe.throw(_("Foreign-currency Treasury Vouchers are not supported in this version."))
        self.currency = cash_account.account_currency or company_currency

        self.cost_center = str(self.cost_center or "").strip() or (
            frappe.db.get_value("Company", self.company, "cost_center") or ""
        )
        if not self.cost_center:
            frappe.throw(_("Cost Center is required."))
        cost_center = frappe.db.get_value(
            "Cost Center",
            self.cost_center,
            ["company", "is_group", "disabled"],
            as_dict=True,
        )
        if not cost_center or cost_center.company != self.company or cint(cost_center.is_group) or cint(cost_center.disabled):
            frappe.throw(_("Select an active leaf Cost Center for the same company."))

        if self.voucher_type == "General Expense":
            self.source_account = self.cash_bank_account
            self.target_account = self.counter_account
        else:
            self.source_account = self.counter_account
            self.target_account = self.cash_bank_account

        self._validate_duplicate_reference()
        if check_live_balance and self.voucher_type == "General Expense":
            balance = flt(
                get_balance_on(
                    account=self.cash_bank_account,
                    date=self.posting_date,
                    company=self.company,
                    in_account_currency=True,
                )
            )
            if balance + 0.005 < self.amount:
                frappe.throw(
                    _("Available balance in {0} is {1}, which is lower than the expense amount {2}.").format(
                        self.cash_bank_account,
                        balance,
                        self.amount,
                    )
                )

    def _validate_account(self, account_name, label):
        account = frappe.db.get_value(
            "Account",
            account_name,
            [
                "name",
                "company",
                "root_type",
                "account_type",
                "account_currency",
                "is_group",
                "disabled",
                "account_name",
            ],
            as_dict=True,
        )
        if not account:
            frappe.throw(_("{0} was not found.").format(label))
        if account.company != self.company:
            frappe.throw(_("{0} belongs to another company.").format(label))
        if cint(account.is_group):
            frappe.throw(_("{0} cannot be a group account.").format(label))
        if cint(account.disabled):
            frappe.throw(_("{0} is disabled.").format(label))
        return account

    def _validate_not_active_shift_drawer(self, cash_account):
        if not frappe.db.exists("DocType", "Cash Drawer"):
            return
        drawer = frappe.db.get_value(
            "Cash Drawer",
            {"cash_account": cash_account.name, "enabled": 1},
            ["name", "drawer_name", "current_active_shift"],
            as_dict=True,
        )
        if drawer and drawer.current_active_shift:
            frappe.throw(
                _("Account {0} belongs to active drawer {1} in shift {2}. Use Shift Cash Movement instead.").format(
                    cash_account.name,
                    drawer.drawer_name or drawer.name,
                    drawer.current_active_shift,
                )
            )

    def _validate_duplicate_reference(self):
        if not self.reference_no:
            return
        filters = {
            "company": self.company,
            "reference_no": self.reference_no,
            "docstatus": ["!=", 2],
        }
        if self.name:
            filters["name"] = ["!=", self.name]
        duplicate = frappe.db.get_value(self.doctype, filters, "name")
        if duplicate:
            frappe.throw(
                _("Reference No {0} is already used by Treasury Voucher {1}.").format(
                    self.reference_no,
                    duplicate,
                )
            )

    def _lock_cash_bank_account(self):
        frappe.db.sql(
            "select name from `tabAccount` where name=%s for update",
            self.cash_bank_account,
        )

    def _ensure_journal_entry(self):
        if self.journal_entry:
            journal = frappe.get_doc("Journal Entry", self.journal_entry)
            if journal.docstatus != 1:
                frappe.throw(_("Linked Journal Entry is not submitted."))
            return journal.name

        journal = frappe.new_doc("Journal Entry")
        journal.voucher_type = "Journal Entry"
        journal.company = self.company
        journal.posting_date = self.posting_date
        reference_text = self.reference_no or "-"
        party_text = self.beneficiary_or_payer or "-"
        journal.user_remark = (
            f"Treasury Voucher {self.name} / {self.voucher_type} / "
            f"{self.category} / reference {reference_text} / party {party_text} / {self.description}"
        )

        if self.voucher_type == "General Expense":
            journal.append(
                "accounts",
                {
                    "account": self.counter_account,
                    "debit_in_account_currency": self.amount,
                    "credit_in_account_currency": 0,
                    "cost_center": self.cost_center,
                },
            )
            journal.append(
                "accounts",
                {
                    "account": self.cash_bank_account,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": self.amount,
                },
            )
        else:
            journal.append(
                "accounts",
                {
                    "account": self.cash_bank_account,
                    "debit_in_account_currency": self.amount,
                    "credit_in_account_currency": 0,
                },
            )
            journal.append(
                "accounts",
                {
                    "account": self.counter_account,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": self.amount,
                    "cost_center": self.cost_center,
                },
            )

        journal.flags.ignore_permissions = True
        journal.insert(ignore_permissions=True)
        journal.flags.ignore_permissions = True
        journal.submit()
        return journal.name
