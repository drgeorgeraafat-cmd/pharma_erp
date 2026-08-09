from __future__ import annotations

from frappe.model.document import Document

from pharma_erp.pharma_erp.branch_warehouse_foundation import validate_branch_profile


class PharmacyBranchProfile(Document):
    def validate(self):
        validate_branch_profile(self)
