import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, nowdate

from erpnext.accounts.utils import get_balance_on

from pharma_erp.treasury_access import (
    can_emergency_submit_treasury,
    can_manage_treasury,
    can_operate_treasury,
)


MOVEMENT_RULES = {
    "Opening Float": {"direction": "In", "counter_kind": "cash_bank"},
    "Till Refill": {"direction": "In", "counter_kind": "cash_bank"},
    "Return Opening Float": {"direction": "Out", "counter_kind": "cash_bank"},
    "Cash Sales Deposit": {"direction": "Out", "counter_kind": "cash_bank"},
    "Unused Till Refill Return": {"direction": "Out", "counter_kind": "cash_bank"},
    "Other Cash Return": {"direction": "Out", "counter_kind": "cash_bank"},
    "Under Review Driver Cash Deposit": {"direction": "In", "counter_kind": "cash_bank"},
    "Transfer to Main Safe": {"direction": "Out", "counter_kind": "cash_bank"},
    "Supplier Payment": {
        "direction": "Out",
        "counter_kind": "payable",
        "requires_supplier": True,
    },
    "Operating Expense": {"direction": "Out", "counter_kind": "expense"},
    "Employee Advance": {
        "direction": "Out",
        "counter_kind": "employee_advance",
        "requires_employee": True,
    },
    "Other Cash Receipt": {"direction": "In", "counter_kind": "receipt"},
    "Other Cash Payment": {"direction": "Out", "counter_kind": "payment"},
    "Other": {"direction": None, "counter_kind": "other"},
}

AUDIT_FIELDS = (
    "request_status",
    "requested_by",
    "requested_at",
    "approved_by",
    "approved_at",
    "approval_note",
)


class ShiftCashMovement(Document):
    def before_insert(self):
        self._resolve_cash_drawer_from_shift()
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
        self._resolve_cash_drawer_from_shift()
        self._validate_operator_access()
        self._protect_audit_fields()
        self._validate_and_normalize()

    def before_submit(self):
        if not can_manage_treasury():
            frappe.throw(
                _("Only Treasury Manager, Accounts Manager, or System Manager can approve a cash movement."),
                frappe.PermissionError,
            )

        requested_by = self.requested_by or self.owner
        self_approval = requested_by == frappe.session.user
        if self_approval and not can_emergency_submit_treasury():
            frappe.throw(
                _("The user who requested this cash movement cannot approve the same request. A different Treasury Manager must approve it."),
                frappe.PermissionError,
            )

        self._lock_source_account()
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
                _("Only Treasury Manager, Accounts Manager, or System Manager can cancel a cash movement."),
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

    def _resolve_cash_drawer_from_shift(self):
        """Bridge legacy shift cash actions to the required Cash Drawer field.

        Older shift-management helpers create Shift Cash Movement documents from
        a Pharmacy Shift Closing and rely on the shift to carry the drawer link.
        V14 made cash_drawer mandatory, so resolve it from the linked shift before
        validation when the caller did not pass it explicitly.
        """
        if self.cash_drawer or not self.shift_reference:
            return

        if not frappe.db.exists("Pharmacy Shift Closing", self.shift_reference):
            return

        shift_meta = frappe.get_meta("Pharmacy Shift Closing")
        if not shift_meta.has_field("custom_cash_drawer"):
            return

        self.cash_drawer = (
            frappe.db.get_value(
                "Pharmacy Shift Closing",
                self.shift_reference,
                "custom_cash_drawer",
            )
            or ""
        )

    def _validate_operator_access(self):
        if not can_operate_treasury():
            frappe.throw(
                _("Only Treasury Operator, Treasury Manager, Accounts Manager, or System Manager can create or edit cash movements."),
                frappe.PermissionError,
            )

        if not self.is_new() and self.docstatus == 0 and not can_manage_treasury():
            owner = frappe.db.get_value(self.doctype, self.name, "owner") or self.owner
            if owner and owner != frappe.session.user:
                frappe.throw(
                    _("Treasury Operator can edit only cash movements created by the same user."),
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
        self.shift_reference = str(self.shift_reference or "").strip()
        self.cash_drawer = str(self.cash_drawer or "").strip()
        self.movement_type = str(self.movement_type or "").strip()
        self.source_account = str(self.source_account or "").strip()
        self.target_account = str(self.target_account or "").strip()
        self.reference_no = str(self.reference_no or "").strip()
        self.description = str(self.description or "").strip()
        self.amount = flt(self.amount)

        if not self.company or not frappe.db.exists("Company", self.company):
            frappe.throw(_("Select a valid Company."))
        if not self.shift_reference:
            frappe.throw(_("Shift Reference is required."))
        if not self.cash_drawer:
            frappe.throw(_("Cash Drawer is required."))
        if not self.movement_type or self.movement_type not in MOVEMENT_RULES:
            frappe.throw(_("Select a valid Movement Type."))
        if self.amount <= 0:
            frappe.throw(_("Amount must be greater than zero."))
        if not self.description:
            frappe.throw(_("Description is required."))
        if not self.source_account or not self.target_account:
            frappe.throw(_("Source Account and Target Account are required."))
        if self.source_account == self.target_account:
            frappe.throw(_("Source and Target accounts cannot be the same."))

        drawer = self._validate_drawer()
        self._validate_shift(drawer)

        rule = MOVEMENT_RULES[self.movement_type]
        expected_direction = rule.get("direction")
        if expected_direction:
            self.direction = expected_direction
        elif self.direction not in ("In", "Out"):
            if self.target_account == drawer.cash_account:
                self.direction = "In"
            elif self.source_account == drawer.cash_account:
                self.direction = "Out"
            else:
                frappe.throw(_("Direction must be In or Out for Other movements."))

        if self.direction == "In":
            if self.target_account != drawer.cash_account:
                frappe.throw(
                    _("For an incoming cash movement, Target Account must be the selected Cash Drawer account {0}.").format(
                        drawer.cash_account
                    )
                )
            counter_account_name = self.source_account
        else:
            if self.source_account != drawer.cash_account:
                frappe.throw(
                    _("For an outgoing cash movement, Source Account must be the selected Cash Drawer account {0}.").format(
                        drawer.cash_account
                    )
                )
            counter_account_name = self.target_account

        source = self._validate_account(self.source_account, _("Source Account"))
        target = self._validate_account(self.target_account, _("Target Account"))
        if source.account_currency != target.account_currency:
            frappe.throw(_("Source and Target accounts must use the same currency."))

        company_currency = frappe.db.get_value("Company", self.company, "default_currency")
        if company_currency and source.account_currency != company_currency:
            frappe.throw(
                _("Shift cash movements currently require accounts in company currency {0}.").format(
                    company_currency
                )
            )

        counter = source if counter_account_name == source.name else target
        self._validate_counter_account(counter, rule)
        self._validate_party_fields(rule)
        self._validate_reference_uniqueness()

        if self.movement_type == "Operating Expense":
            self.expense_account = counter.name
        elif self.expense_account:
            self.expense_account = None

        if check_live_balance:
            self._validate_source_balance(source)

    def _validate_drawer(self):
        if not frappe.db.exists("DocType", "Cash Drawer"):
            frappe.throw(_("Cash Drawer DocType is not available."))

        drawer = frappe.db.get_value(
            "Cash Drawer",
            self.cash_drawer,
            [
                "name",
                "company",
                "enabled",
                "cash_account",
                "current_active_shift",
            ],
            as_dict=True,
        )
        if not drawer:
            frappe.throw(_("Cash Drawer was not found."))
        if drawer.company != self.company:
            frappe.throw(_("Cash Drawer belongs to another company."))
        if not cint(drawer.enabled):
            frappe.throw(_("Cash Drawer is disabled."))
        if not drawer.cash_account:
            frappe.throw(_("Cash Drawer does not have a linked Cash Account."))
        return drawer

    def _validate_shift(self, drawer):
        if not frappe.db.exists("Pharmacy Shift Closing", self.shift_reference):
            frappe.throw(_("Shift Reference was not found."))

        meta = frappe.get_meta("Pharmacy Shift Closing")
        fields = ["name", "docstatus"]
        for fieldname in (
            "company",
            "status",
            "end_time",
            "custom_shift_operational_status",
            "custom_cash_drawer",
        ):
            if meta.has_field(fieldname):
                fields.append(fieldname)
        shift = frappe.db.get_value(
            "Pharmacy Shift Closing", self.shift_reference, fields, as_dict=True
        ) or {}

        if shift.get("company") and shift.company != self.company:
            frappe.throw(_("Shift Reference belongs to another company."))
        if shift.get("custom_cash_drawer") and shift.custom_cash_drawer != self.cash_drawer:
            frappe.throw(_("Shift Reference is linked to another Cash Drawer."))
        if drawer.get("current_active_shift") and drawer.current_active_shift != self.shift_reference:
            frappe.throw(
                _("The selected Cash Drawer is currently linked to shift {0}.").format(
                    drawer.current_active_shift
                )
            )
        if self._shift_is_closed(shift):
            frappe.throw(_("Cash movements cannot be posted to a closed shift."))

    @staticmethod
    def _shift_is_closed(shift):
        if cint(shift.get("docstatus")) == 2 or shift.get("end_time"):
            return True
        statuses = {
            str(shift.get("status") or "").strip().lower(),
            str(shift.get("custom_shift_operational_status") or "").strip().lower(),
        }
        return bool(statuses.intersection({"closed", "completed", "cancelled"}))

    def _validate_account(self, account_name, label):
        account = frappe.db.get_value(
            "Account",
            account_name,
            [
                "name",
                "company",
                "is_group",
                "disabled",
                "root_type",
                "account_type",
                "account_currency",
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

    def _validate_counter_account(self, account, rule):
        kind = rule.get("counter_kind")
        if kind == "cash_bank":
            if account.root_type != "Asset" or account.account_type not in ("Cash", "Bank"):
                frappe.throw(_("Counter Account must be an active Asset Cash or Bank account."))
        elif kind == "expense":
            if account.root_type != "Expense":
                frappe.throw(_("Operating Expense requires an Expense account."))
        elif kind == "payable":
            if account.root_type != "Liability" or account.account_type != "Payable":
                frappe.throw(_("Supplier Payment requires a Liability account with Account Type Payable."))
        elif kind == "employee_advance":
            if account.root_type != "Asset" or account.account_type != "Receivable":
                frappe.throw(_("Employee Advance requires an Asset account with Account Type Receivable."))
        elif kind == "receipt":
            if account.root_type not in ("Income", "Liability", "Equity", "Asset"):
                frappe.throw(_("Other Cash Receipt requires an Income, Liability, Equity, or Asset counter account."))
            if account.account_type in ("Receivable", "Payable"):
                frappe.throw(_("Use a dedicated customer or supplier transaction for Receivable or Payable accounts."))
            if account.root_type == "Asset" and account.account_type not in ("Cash", "Bank"):
                frappe.throw(_("Asset counter account for a cash receipt must be Cash or Bank."))
        elif kind == "payment":
            if account.root_type not in ("Expense", "Asset", "Liability"):
                frappe.throw(_("Other Cash Payment requires an Expense, Asset, or Liability counter account."))
            if account.account_type in ("Receivable", "Payable"):
                frappe.throw(_("Use Employee Advance or Supplier Payment for party accounts."))

    def _validate_party_fields(self, rule):
        if rule.get("requires_supplier") and not self.supplier:
            frappe.throw(_("Supplier is required for Supplier Payment."))
        if self.movement_type != "Supplier Payment":
            self.supplier = None
            self.purchase_invoice = None
        elif self.purchase_invoice:
            invoice = frappe.db.get_value(
                "Purchase Invoice",
                self.purchase_invoice,
                ["name", "company", "supplier", "docstatus", "outstanding_amount"],
                as_dict=True,
            )
            if not invoice or cint(invoice.docstatus) != 1:
                frappe.throw(_("Select a submitted Purchase Invoice."))
            if invoice.company != self.company:
                frappe.throw(_("Purchase Invoice belongs to another company."))
            if invoice.supplier != self.supplier:
                frappe.throw(_("Purchase Invoice belongs to another Supplier."))
            if flt(invoice.outstanding_amount) <= 0:
                frappe.throw(_("Purchase Invoice has no outstanding amount."))
            if self.amount > flt(invoice.outstanding_amount) + 0.000001:
                frappe.throw(_("Payment amount cannot exceed Purchase Invoice outstanding amount."))

        if rule.get("requires_employee") and not self.employee:
            frappe.throw(_("Employee is required for Employee Advance."))
        if self.movement_type != "Employee Advance":
            self.employee = None

    def _validate_reference_uniqueness(self):
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
                _("Reference No is already used by cash movement {0}.").format(duplicate)
            )

    def _validate_source_balance(self, source):
        if source.root_type != "Asset" or source.account_type not in ("Cash", "Bank"):
            return
        balance = flt(
            get_balance_on(
                account=source.name,
                date=get_datetime(self.movement_date or now_datetime()).date(),
                company=self.company,
                in_account_currency=True,
            )
        )
        if self.amount > balance + 0.000001:
            frappe.throw(
                _("Insufficient balance in {0}. Available balance is {1}.").format(
                    source.name,
                    frappe.format_value(balance, {"fieldtype": "Currency", "options": source.account_currency}),
                )
            )

    def _lock_source_account(self):
        if self.source_account:
            frappe.db.sql(
                "select name from `tabAccount` where name=%s for update",
                (self.source_account,),
            )

    def _ensure_journal_entry(self):
        linked = self.journal_entry or frappe.db.get_value(
            self.doctype, self.name, "journal_entry"
        )
        if linked:
            linked_status = frappe.db.get_value("Journal Entry", linked, "docstatus")
            if linked_status == 1:
                return linked
            if linked_status == 2:
                frappe.throw(_("Linked Journal Entry is cancelled."))

        amount = flt(self.amount)
        journal = frappe.new_doc("Journal Entry")
        journal.voucher_type = "Journal Entry"
        journal.company = self.company
        journal.posting_date = get_datetime(self.movement_date or now_datetime()).date()
        reference_text = f" / reference {self.reference_no}" if self.reference_no else ""
        journal.user_remark = (
            f"Shift cash movement {self.name} / {self.movement_type} / "
            f"{self.shift_reference}{reference_text} / {self.description}"
        )

        debit_row = {
            "account": self.target_account,
            "debit_in_account_currency": amount,
            "credit_in_account_currency": 0,
        }
        credit_row = {
            "account": self.source_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": amount,
        }

        if self.movement_type == "Employee Advance" and self.employee:
            debit_row["party_type"] = "Employee"
            debit_row["party"] = self.employee

        if self.movement_type == "Supplier Payment" and self.supplier:
            debit_row["party_type"] = "Supplier"
            debit_row["party"] = self.supplier
            if self.purchase_invoice:
                debit_row["reference_type"] = "Purchase Invoice"
                debit_row["reference_name"] = self.purchase_invoice

        journal.append("accounts", debit_row)
        journal.append("accounts", credit_row)
        journal.flags.ignore_permissions = True
        journal.insert(ignore_permissions=True)
        journal.flags.ignore_permissions = True
        journal.submit()
        return journal.name
