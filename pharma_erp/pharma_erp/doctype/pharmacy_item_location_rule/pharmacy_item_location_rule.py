import frappe
from frappe import _
from frappe.model.document import Document
from pharma_erp.pharma_erp.location_service import validate_location

class PharmacyItemLocationRule(Document):
    def validate(self):
        if bool(self.item_code) == bool(self.item_group):
            frappe.throw(_("Set exactly one of Item or Item Group."))
        validate_location(self.primary_location, self.warehouse)
        if self.overflow_location:
            validate_location(self.overflow_location, self.warehouse)
            if self.overflow_location == self.primary_location:
                frappe.throw(_("Overflow Location must differ from Primary Location."))
