from __future__ import annotations

from frappe.model.document import Document

from pharma_erp.pharma_erp.branch_warehouse_foundation import validate_warehouse_profile


class PharmacyWarehouseProfile(Document):
    def validate(self):
        validate_warehouse_profile(self)
