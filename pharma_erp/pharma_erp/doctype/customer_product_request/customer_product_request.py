from uuid import uuid4

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from pharma_erp.pharma_erp.customer_product_request_contract import stable_request_key


class CustomerProductRequest(Document):
    def before_insert(self):
        self.requested_at = self.requested_at or now_datetime()
        self.status = "Waiting for Stock"
        if not self.external_request_key:
            self.external_request_key = stable_request_key(
                self.customer, self.branch, uuid4().hex
            )

    def validate(self):
        if not self.items:
            frappe.throw("Customer Product Request requires at least one item.")
        for row in self.items:
            if flt(row.requested_qty) <= 0:
                frappe.throw(f"Requested quantity must be positive for {row.item_code}.")
            row.operational_role = "Sales"
            row.converted_qty = max(flt(row.converted_qty), 0)
            row.remaining_qty = max(flt(row.requested_qty) - flt(row.converted_qty), 0)
