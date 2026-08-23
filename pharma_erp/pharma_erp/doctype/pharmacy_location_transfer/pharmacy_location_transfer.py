import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from pharma_erp.pharma_erp.location_service import get_allocated_qty, post_movement, validate_location

class PharmacyLocationTransfer(Document):
    def validate(self):
        if not self.items:
            frappe.throw(_("Add at least one Transfer Item."))
        grouped={}
        for row in self.items:
            if flt(row.qty) <= 0:
                frappe.throw(_("Transfer quantity must be greater than zero on row {0}.").format(row.idx))
            validate_location(row.from_location,self.warehouse)
            validate_location(row.to_location,self.warehouse)
            if row.from_location == row.to_location:
                frappe.throw(_("Source and Target Location must differ on row {0}.").format(row.idx))
            key=(row.item_code,row.batch_no or "",row.from_location)
            grouped[key]=flt(grouped.get(key,0)+flt(row.qty),6)
        for (item_code,batch_no,from_location),requested in grouped.items():
            available=get_allocated_qty(item_code,self.warehouse,batch_no or None,from_location)
            if requested > available + 1e-9:
                frappe.throw(_("Transfer exceeds location stock for {0} at {1}. Requested {2}, available {3}.").format(frappe.bold(item_code),frappe.bold(from_location),requested,available))
    def on_submit(self):
        for row in self.items:
            post_movement(movement_type="Internal Transfer",warehouse=self.warehouse,item_code=row.item_code,batch_no=row.batch_no,qty=row.qty,from_location=row.from_location,to_location=row.to_location,reference_doctype=self.doctype,reference_name=self.name,reference_row=row.name,dedupe_key=f"TRANSFER|{self.name}|{row.name}",remarks=self.reason)
    def on_cancel(self):
        for row in self.items:
            post_movement(movement_type="Internal Transfer Cancel",warehouse=self.warehouse,item_code=row.item_code,batch_no=row.batch_no,qty=row.qty,from_location=row.to_location,to_location=row.from_location,reference_doctype=self.doctype,reference_name=self.name,reference_row=row.name,dedupe_key=f"TRANSFER-CANCEL|{self.name}|{row.name}",remarks=self.reason)
