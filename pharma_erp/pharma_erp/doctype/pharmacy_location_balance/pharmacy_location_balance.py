import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

class PharmacyLocationBalance(Document):
    def validate(self):
        if flt(self.qty) < 0:
            frappe.throw(_("Location Qty cannot be negative."))
    def on_trash(self):
        if not getattr(frappe.flags, "in_location_foundation_cleanup", False):
            frappe.throw(_("Location Balance rows are system-managed and cannot be deleted manually."))
