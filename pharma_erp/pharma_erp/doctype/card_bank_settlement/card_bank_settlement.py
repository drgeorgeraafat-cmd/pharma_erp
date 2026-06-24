import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class CardBankSettlement(Document):
    def before_submit(self):
        if not self.allocations:
            frappe.throw(_("Add at least one Card Settlement Batch."))

        gross = 0

        for row in self.allocations:
            batch = frappe.get_doc("Card Settlement Batch", row.card_settlement_batch)

            if batch.docstatus != 1:
                frappe.throw(_("Card batch must be submitted: {0}").format(batch.name))

            if (
                batch.clearing_account != self.clearing_account
                or batch.destination_bank_account != self.destination_bank_account
            ):
                frappe.throw(_("All batches must use the selected clearing and bank accounts."))

            available = flt(batch.outstanding_amount)
            allocated = flt(row.allocated_amount)

            if allocated <= 0 or allocated - available > 0.01:
                frappe.throw(_("Invalid allocated amount for {0}").format(batch.name))

            row.pos_terminal = batch.pos_terminal
            row.batch_number = batch.batch_number
            row.available_amount = available
            gross += allocated

        self.gross_amount = flt(gross)
        self.net_amount = flt(self.gross_amount) - flt(self.fee_amount)

        if self.net_amount < 0:
            frappe.throw(_("Fee Amount cannot exceed Gross Amount."))

        if flt(self.fee_amount) > 0 and not self.fee_account:
            frappe.throw(_("Fee Account is required."))

        self.status = "Submitted"

    def on_submit(self):
        journal_name = self._ensure_journal_entry()

        frappe.db.set_value(
            self.doctype,
            self.name,
            {
                "journal_entry": journal_name,
                "status": "Submitted",
            },
            update_modified=False,
        )

        for row in self.allocations:
            batch = frappe.get_doc("Card Settlement Batch", row.card_settlement_batch)
            settled = flt(batch.settled_amount) + flt(row.allocated_amount)
            outstanding = flt(batch.system_total) - settled
            status = "Settled" if outstanding <= 0.01 else "Partially Settled"

            frappe.db.set_value(
                "Card Settlement Batch",
                batch.name,
                {
                    "settled_amount": settled,
                    "outstanding_amount": max(outstanding, 0),
                    "status": status,
                    "bank_settlement": self.name if status == "Settled" else "",
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

    def on_cancel(self):
        for row in self.allocations:
            batch = frappe.get_doc("Card Settlement Batch", row.card_settlement_batch)
            settled = max(
                flt(batch.settled_amount) - flt(row.allocated_amount),
                0,
            )
            outstanding = flt(batch.system_total) - settled
            status = (
                "Awaiting Bank Settlement"
                if settled <= 0.01
                else "Partially Settled"
            )

            frappe.db.set_value(
                "Card Settlement Batch",
                batch.name,
                {
                    "settled_amount": settled,
                    "outstanding_amount": max(outstanding, 0),
                    "status": status,
                    "bank_settlement": "",
                },
                update_modified=False,
            )

    def _ensure_journal_entry(self):
        linked = self.journal_entry or frappe.db.get_value(
            self.doctype,
            self.name,
            "journal_entry",
        )

        if linked and frappe.db.get_value("Journal Entry", linked, "docstatus") == 1:
            return linked

        journal = frappe.new_doc("Journal Entry")
        journal.voucher_type = "Journal Entry"
        journal.company = self.company
        journal.posting_date = self.settlement_date
        journal.user_remark = (
            "Card bank settlement "
            + self.name
            + " / "
            + (self.bank_reference or "")
        )

        if flt(self.net_amount) > 0:
            journal.append(
                "accounts",
                {
                    "account": self.destination_bank_account,
                    "debit_in_account_currency": flt(self.net_amount),
                    "credit_in_account_currency": 0,
                },
            )

        if flt(self.fee_amount) > 0:
            journal.append(
                "accounts",
                {
                    "account": self.fee_account,
                    "debit_in_account_currency": flt(self.fee_amount),
                    "credit_in_account_currency": 0,
                },
            )

        journal.append(
            "accounts",
            {
                "account": self.clearing_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": flt(self.gross_amount),
            },
        )

        journal.flags.ignore_permissions = True
        journal.insert(ignore_permissions=True)
        journal.flags.ignore_permissions = True
        journal.submit()

        return journal.name
