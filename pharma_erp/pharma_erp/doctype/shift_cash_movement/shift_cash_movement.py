import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, now, nowdate


class ShiftCashMovement(Document):
    def before_submit(self):
        amount = flt(self.amount)

        if amount <= 0:
            frappe.throw(_("Amount must be greater than zero."))

        if not self.source_account or not self.target_account:
            frappe.throw(_("Source Account and Target Account are required."))

        if self.source_account == self.target_account:
            frappe.throw(_("Source and Target accounts cannot be the same."))

    def on_submit(self):
        journal_name = self._ensure_journal_entry()

        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "journal_entry": journal_name,
                "status": "Posted",
                "posted_by": frappe.session.user,
                "posted_at": now(),
            },
            update_modified=False,
        )

    def before_cancel(self):
        if not self.journal_entry:
            return

        journal = frappe.get_doc("Journal Entry", self.journal_entry)
        if journal.docstatus == 1:
            journal.flags.ignore_permissions = True
            journal.cancel()

    def _ensure_journal_entry(self):
        linked = self.journal_entry or frappe.db.get_value(
            self.doctype,
            self.name,
            "journal_entry",
        )

        if linked and frappe.db.get_value("Journal Entry", linked, "docstatus") == 1:
            return linked

        amount = flt(self.amount)
        journal = frappe.new_doc("Journal Entry")
        journal.voucher_type = "Journal Entry"
        journal.company = self.company
        journal.posting_date = getdate(self.movement_date or nowdate())
        journal.user_remark = (
            "Shift cash movement "
            + self.name
            + " - "
            + (self.description or self.movement_type or "")
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

            if self.get("purchase_invoice"):
                debit_row["reference_type"] = "Purchase Invoice"
                debit_row["reference_name"] = self.purchase_invoice

        journal.append("accounts", debit_row)
        journal.append("accounts", credit_row)
        journal.flags.ignore_permissions = True
        journal.insert(ignore_permissions=True)
        journal.flags.ignore_permissions = True
        journal.submit()

        return journal.name
