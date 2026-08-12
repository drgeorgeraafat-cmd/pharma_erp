# Copyright (c) 2026, ZeePharaoh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from pharma_erp.pharma_erp.shift_delivery_branch_integration import (
    validate_delivery_handover_branch,
)


class DeliveryHandover(Document):
    def validate(self):
        validate_delivery_handover_branch(self)

    def before_cancel(self):
        if not self.journal_entry:
            return

        journal = frappe.get_doc("Journal Entry", self.journal_entry)
        if journal.docstatus == 1:
            journal.flags.ignore_permissions = True
            journal.cancel()
