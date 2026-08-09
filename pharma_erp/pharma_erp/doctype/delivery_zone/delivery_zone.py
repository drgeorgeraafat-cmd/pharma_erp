# Copyright (c) 2026, ZeePharaoh and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from pharma_erp.pharma_erp.branch_operational_integration import resolve_role_context
from pharma_erp.pharma_erp.branch_warehouse_foundation import get_branch_profile


class DeliveryZone(Document):
    def validate(self):
        profile = get_branch_profile(self.branch, require_enabled=True)
        context = resolve_role_context(
            company=profile.company,
            role="Online Fulfilment",
            requested_branch=self.branch,
            submitted_warehouse=self.warehouse,
        )
        self.branch = context["branch"]
        self.warehouse = context["warehouse"]
