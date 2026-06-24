import frappe
from frappe import _
from frappe.model.document import Document


class CardPOSTerminal(Document):
    def validate(self):
        if self.mode_of_payment != "Credit Card":
            frappe.throw(_("Card POS Terminal must use Credit Card Mode of Payment."))

        for account in (self.clearing_account, self.destination_bank_account):
            self._validate_account(account)

        if self.fee_account:
            self._validate_account(self.fee_account)

    def _validate_account(self, account):
        row = frappe.db.get_value(
            "Account",
            account,
            ["company", "is_group", "disabled"],
            as_dict=True,
        )

        if (
            not row
            or row.company != self.company
            or row.is_group
            or row.disabled
        ):
            frappe.throw(_("Invalid account: {0}").format(account or _("Not set")))
