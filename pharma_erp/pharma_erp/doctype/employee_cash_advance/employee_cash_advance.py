# Copyright (c) 2026, ZeePharaoh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now, today


DEFAULT_CASH_ACCOUNT = "Cashier Till - C"
DEFAULT_EMPLOYEE_ADVANCE_ACCOUNT = "Employee Advances - C"


class EmployeeCashAdvance(Document):
    def before_submit(self):
        amount = flt(self.advance_amount)
        recovered = flt(self.recovered_amount)
        installments = cint(self.number_of_installments or 1)

        if not self.company:
            frappe.throw("Company is required.")
        if not self.employee:
            frappe.throw("Employee is required.")
        if not self.shift_reference:
            frappe.throw("Shift Reference is required.")

        shift_row = frappe.db.get_value(
            "Pharmacy Shift Closing",
            self.shift_reference,
            ["docstatus", "status", "end_time"],
            as_dict=True,
        )
        if not shift_row:
            frappe.throw("Shift Reference was not found.")
        if shift_row.docstatus != 0:
            frappe.throw("Shift Reference must be the currently open shift.")
        if shift_row.status == "Closed" or shift_row.end_time:
            frappe.throw("The selected shift is already closed.")
        if amount <= 0:
            frappe.throw("Advance Amount must be greater than zero.")
        if recovered < 0:
            frappe.throw("Recovered Amount cannot be negative.")
        if recovered > amount:
            frappe.throw("Recovered Amount cannot exceed Advance Amount.")

        employee_company = frappe.db.get_value("Employee", self.employee, "company")
        if employee_company and employee_company != self.company:
            frappe.throw("Employee belongs to another company.")

        outstanding = flt(amount - recovered)

        if self.recovery_method == "Multiple Installments":
            if installments <= 0:
                frappe.throw("Number of Installments must be greater than zero.")
            installment_amount = flt(outstanding / installments)
            payroll_status = "Scheduled"
        elif self.recovery_method == "Salary Deduction":
            installments = 1
            installment_amount = outstanding
            payroll_status = "Scheduled"
        else:
            installments = 1
            installment_amount = 0
            payroll_status = "Not Applicable"

        self.recovered_amount = recovered
        self.outstanding_amount = outstanding
        self.number_of_installments = installments
        self.installment_amount = installment_amount
        self.payroll_status = payroll_status
        self.status = "Pending Disbursement"
        self.approved_by = frappe.session.user
        self.approved_at = now()

        if not self.cash_account:
            self.cash_account = DEFAULT_CASH_ACCOUNT
        if not self.employee_advance_account:
            self.employee_advance_account = DEFAULT_EMPLOYEE_ADVANCE_ACCOUNT

        for account in (self.cash_account, self.employee_advance_account):
            _validate_account(account, self.company)

    def on_submit(self):
        if self.journal_entry:
            existing_status = frappe.db.get_value(
                "Journal Entry", self.journal_entry, "docstatus"
            )
            if existing_status == 1:
                frappe.throw(
                    "A submitted Journal Entry is already linked: " + self.journal_entry
                )

        amount = flt(self.advance_amount)
        if amount <= 0:
            frappe.throw("Advance Amount must be greater than zero.")

        journal = frappe.new_doc("Journal Entry")
        journal.voucher_type = "Journal Entry"
        journal.company = self.company
        journal.posting_date = self.advance_date or today()
        journal.user_remark = (
            "Employee cash advance "
            + self.name
            + " for employee "
            + self.employee
            + ", shift "
            + self.shift_reference
        )
        journal.append(
            "accounts",
            {
                "account": self.employee_advance_account,
                "party_type": "Employee",
                "party": self.employee,
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
            },
        )
        journal.append(
            "accounts",
            {
                "account": self.cash_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
            },
        )
        journal.flags.ignore_permissions = True
        journal.insert(ignore_permissions=True)
        journal.flags.ignore_permissions = True
        journal.submit()

        frappe.db.set_value(
            "Employee Cash Advance",
            self.name,
            {
                "journal_entry": journal.name,
                "status": "Disbursed",
                "disbursed_by": frappe.session.user,
                "disbursed_at": now(),
            },
            update_modified=False,
        )

    def before_cancel(self):
        if flt(self.recovered_amount) > 0:
            frappe.throw(
                "This Employee Cash Advance cannot be cancelled because recovery has already started."
            )
        if self.payroll_status in ("Partially Deducted", "Fully Deducted"):
            frappe.throw(
                "This Employee Cash Advance cannot be cancelled because payroll deductions exist."
            )

        if self.journal_entry:
            journal = frappe.get_doc("Journal Entry", self.journal_entry)
            if journal.docstatus == 1:
                journal.flags.ignore_permissions = True
                journal.cancel()


def _validate_account(account, company):
    account_row = frappe.db.get_value(
        "Account",
        account,
        ["company", "is_group", "disabled"],
        as_dict=True,
    )
    if not account_row:
        frappe.throw("Account not found: " + account)
    if account_row.company != company:
        frappe.throw("Account belongs to another company: " + account)
    if account_row.is_group:
        frappe.throw("A group account cannot be used: " + account)
    if account_row.disabled:
        frappe.throw("Account is disabled: " + account)
