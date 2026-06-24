# Copyright (c) 2026, ZeePharaoh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DeliveryHandover(Document):
    def before_cancel(self):
        if not self.journal_entry:
            return

        journal = frappe.get_doc("Journal Entry", self.journal_entry)
        if journal.docstatus == 1:
            journal.flags.ignore_permissions = True
            journal.cancel()
