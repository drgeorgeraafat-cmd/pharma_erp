import frappe
from frappe import _
from frappe.model.document import Document

class PharmacyStorageLocation(Document):
    def validate(self):
        self.location_code=(self.location_code or '').strip()
        if not self.location_code:
            frappe.throw(_("Location Code is required."))
        if self.parent_location:
            parent=frappe.db.get_value("Pharmacy Storage Location", self.parent_location, ["warehouse","parent_location"], as_dict=True)
            if not parent:
                frappe.throw(_("Parent Location does not exist."))
            if parent.warehouse != self.warehouse:
                frappe.throw(_("Parent Location must belong to the same Warehouse."))
            if self.parent_location == self.name:
                frappe.throw(_("A location cannot be its own parent."))
            seen={self.name}; current=self.parent_location
            while current:
                if current in seen:
                    frappe.throw(_("Location hierarchy cannot contain a cycle."))
                seen.add(current)
                current=frappe.db.get_value("Pharmacy Storage Location", current, "parent_location")
        elif self.location_type != "Zone":
            frappe.throw(_("Only a Zone may exist without a Parent Location."))
