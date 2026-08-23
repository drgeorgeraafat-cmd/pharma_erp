import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from pharma_erp.pharma_erp.location_service import get_unallocated_qty, post_movement, validate_location

class PharmacyPutaway(Document):
    def validate(self):
        if not self.items:
            frappe.throw(_("Add at least one Putaway Item."))
        grouped={}
        for row in self.items:
            if flt(row.qty) <= 0:
                frappe.throw(_("Putaway quantity must be greater than zero on row {0}.").format(row.idx))
            validate_location(row.to_location, self.warehouse)
            key=(row.item_code,row.batch_no or "")
            grouped[key]=flt(grouped.get(key,0)+flt(row.qty),6)
        for (item_code,batch_no),requested in grouped.items():
            available=get_unallocated_qty(item_code,self.warehouse,batch_no or None)
            if requested > available + 1e-9:
                frappe.throw(_("Putaway exceeds unallocated warehouse stock for {0}. Requested {1}, available {2}.").format(frappe.bold(item_code),requested,available))
    def on_submit(self):
        for row in self.items:
            post_movement(movement_type="Putaway",warehouse=self.warehouse,item_code=row.item_code,batch_no=row.batch_no,qty=row.qty,to_location=row.to_location,reference_doctype=self.doctype,reference_name=self.name,reference_row=row.name,dedupe_key=f"PUTAWAY|{self.name}|{row.name}",remarks=self.remarks)
    def on_cancel(self):
        for row in self.items:
            post_movement(movement_type="Putaway Cancel",warehouse=self.warehouse,item_code=row.item_code,batch_no=row.batch_no,qty=row.qty,from_location=row.to_location,reference_doctype=self.doctype,reference_name=self.name,reference_row=row.name,dedupe_key=f"PUTAWAY-CANCEL|{self.name}|{row.name}",remarks=self.remarks)
