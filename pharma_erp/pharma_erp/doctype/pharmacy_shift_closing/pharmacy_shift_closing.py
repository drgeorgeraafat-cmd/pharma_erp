# Copyright (c) 2026, ZeePharaoh and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from pharma_erp.pharma_erp.shift_delivery_branch_integration import (
    validate_pharmacy_shift_branch,
)


class PharmacyShiftClosing(Document):
    def validate(self):
        validate_pharmacy_shift_branch(self)
