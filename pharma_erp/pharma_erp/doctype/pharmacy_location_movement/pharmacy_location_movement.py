import frappe
from frappe import _
from frappe.model.document import Document

class PharmacyLocationMovement(Document):
    def validate(self):
        if not self.is_new():
            frappe.throw(_("Location Movement is an immutable audit ledger and cannot be edited."))
    def on_trash(self):
        if not getattr(frappe.flags, "in_location_foundation_cleanup", False):
            frappe.throw(_("Location Movement is an immutable audit ledger and cannot be deleted."))
