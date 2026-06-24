# Copyright (c) 2026, ZeePharaoh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now, today


DEFAULT_DELIVERY_TRANSIT_ACCOUNT = "Delivery Cash In Transit - C"
DEFAULT_EMPLOYEE_SHORTAGE_ACCOUNT = "Employee Shortage - C"


class DriverShortage(Document):
    def before_submit(self):
        expected = 0.0
        handed = 0.0
        recovered = flt(self.recovered_amount)
        installments = cint(self.number_of_installments or 1)

        if not self.company:
            frappe.throw("Company is required.")
        if not self.employee:
            frappe.throw("Employee is required.")
        if not self.shift_reference:
            frappe.throw("Shift Reference is required.")
        if not self.delivery_settlement:
            frappe.throw("Delivery Settlement is required.")

        settlement = frappe.get_doc("Delivery Settlement", self.delivery_settlement)
        if settlement.docstatus == 2:
            frappe.throw("The selected Delivery Settlement is cancelled.")

        if settlement.delivery_boy and settlement.delivery_boy != self.employee:
            frappe.throw(
                "Employee does not match the delivery boy on the selected settlement."
            )

        if settlement.shift_reference and settlement.shift_reference != self.shift_reference:
            frappe.throw(
                "Shift Reference does not match the selected Delivery Settlement."
            )

        if self.get("delivery_handover"):
            handover = frappe.get_doc("Delivery Handover", self.delivery_handover)

            if handover.docstatus != 1:
                frappe.throw("Final Delivery Handover must be submitted.")
            if handover.delivery_settlement != self.delivery_settlement:
                frappe.throw(
                    "Final Delivery Handover does not belong to the selected settlement."
                )
            if handover.handover_type != "Final Settlement":
                frappe.throw(
                    "Driver Shortage can only be linked to a Final Settlement handover."
                )

            duplicate = frappe.db.exists(
                "Driver Shortage",
                {
                    "delivery_handover": self.delivery_handover,
                    "docstatus": 1,
                    "name": ["!=", self.name],
                },
            )
        else:
            duplicate = frappe.db.exists(
                "Driver Shortage",
                {
                    "delivery_settlement": self.delivery_settlement,
                    "docstatus": 1,
                    "name": ["!=", self.name],
                },
            )

        if duplicate:
            frappe.throw("A submitted Driver Shortage already exists: " + duplicate)

        expected = flt(settlement.total_expected)
        if expected <= 0.01:
            expected = flt(settlement.pilot_float)
            for row in settlement.invoices:
                if (
                    row.collection_status == "Confirmed"
                    and row.collection_received_by == "Delivery Boy"
                ):
                    expected += flt(row.confirmed_collection_amount or row.amount)

        submitted_handovers = frappe.get_all(
            "Delivery Handover",
            filters={
                "delivery_settlement": settlement.name,
                "docstatus": 1,
            },
            fields=["amount"],
            limit_page_length=1000,
        )
        for handover_row in submitted_handovers:
            handed += flt(handover_row.amount)

        shortage = flt(expected - handed)
        if shortage <= 0.01:
            frappe.throw(
                "There is no shortage to record. Submitted handovers cover the expected amount."
            )
        if recovered < 0:
            frappe.throw("Recovered Amount cannot be negative.")
        if recovered > shortage:
            frappe.throw("Recovered Amount cannot exceed Shortage Amount.")

        outstanding = flt(shortage - recovered)

        if self.recovery_method == "Waived":
            frappe.throw(
                "Waived shortages are not enabled yet because a shortage write-off "
                "expense account has not been configured."
            )

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

        self.expected_amount = expected
        self.handed_over_amount = handed
        self.shortage_amount = shortage
        self.recovered_amount = recovered
        self.outstanding_amount = outstanding
        self.number_of_installments = installments
        self.installment_amount = installment_amount
        self.payroll_status = payroll_status
        self.status = "Open"
        self.approved_by = frappe.session.user
        self.approved_at = now()

        if not self.delivery_transit_account:
            self.delivery_transit_account = DEFAULT_DELIVERY_TRANSIT_ACCOUNT
        if not self.employee_shortage_account:
            self.employee_shortage_account = DEFAULT_EMPLOYEE_SHORTAGE_ACCOUNT

        for account in (self.delivery_transit_account, self.employee_shortage_account):
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

        amount = flt(self.shortage_amount)
        if amount <= 0:
            frappe.throw("Shortage Amount must be greater than zero.")

        journal = frappe.new_doc("Journal Entry")
        journal.voucher_type = "Journal Entry"
        journal.company = self.company
        journal.posting_date = self.shortage_date or today()
        journal.user_remark = (
            "Driver shortage "
            + self.name
            + " for employee "
            + self.employee
            + ", settlement "
            + self.delivery_settlement
        )
        journal.append(
            "accounts",
            {
                "account": self.employee_shortage_account,
                "party_type": "Employee",
                "party": self.employee,
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
            },
        )
        journal.append(
            "accounts",
            {
                "account": self.delivery_transit_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
            },
        )
        journal.flags.ignore_permissions = True
        journal.insert(ignore_permissions=True)
        journal.flags.ignore_permissions = True
        journal.submit()

        frappe.db.set_value(
            "Driver Shortage",
            self.name,
            "journal_entry",
            journal.name,
            update_modified=False,
        )
        frappe.db.set_value(
            "Delivery Settlement",
            self.delivery_settlement,
            {
                "remaining_with_driver": 0,
                "final_difference": -abs(amount),
                "difference_reason": self.reason,
                "settlement_status": "Settled",
                "settled_at": now(),
                "settled_by": frappe.session.user,
            },
            update_modified=False,
        )

    def before_cancel(self):
        if flt(self.recovered_amount) > 0:
            frappe.throw(
                "This Driver Shortage cannot be cancelled because recovery has already started."
            )
        if self.payroll_status in ("Partially Deducted", "Fully Deducted"):
            frappe.throw(
                "This Driver Shortage cannot be cancelled because payroll deductions exist."
            )

        if self.journal_entry:
            journal = frappe.get_doc("Journal Entry", self.journal_entry)
            if journal.docstatus == 1:
                journal.flags.ignore_permissions = True
                journal.cancel()

        if self.delivery_settlement:
            settlement = frappe.get_doc("Delivery Settlement", self.delivery_settlement)
            remaining = max(
                flt(settlement.total_expected) - flt(settlement.total_handed_over),
                0,
            )
            frappe.db.set_value(
                "Delivery Settlement",
                settlement.name,
                {
                    "remaining_with_driver": remaining,
                    "final_difference": 0,
                    "difference_reason": "",
                    "settlement_status": "Awaiting Final Settlement",
                    "settled_at": None,
                    "settled_by": None,
                },
                update_modified=False,
            )


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
