from __future__ import annotations
import uuid
import frappe
from pharma_erp.pharma_erp.location_service import get_allocated_qty

REQUIRED=["Pharmacy Storage Location","Pharmacy Item Location Rule","Pharmacy Location Balance","Pharmacy Location Movement","Pharmacy Putaway","Pharmacy Putaway Item","Pharmacy Location Transfer","Pharmacy Location Transfer Item"]

def _assert(cond,msg):
    if not cond: raise AssertionError(msg)

def _candidate():
    rows=frappe.db.sql("""
        SELECT b.warehouse,b.item_code,b.actual_qty,i.has_batch_no
        FROM `tabBin` b INNER JOIN `tabWarehouse` w ON w.name=b.warehouse INNER JOIN `tabItem` i ON i.name=b.item_code
        WHERE b.actual_qty>=3 AND w.disabled=0 AND w.is_group=0 AND i.disabled=0
        ORDER BY i.has_batch_no ASC,b.actual_qty DESC LIMIT 50
    """,as_dict=True)
    for row in rows:
        if not row.has_batch_no:
            row.batch_no=None; return row
        batch=frappe.db.sql("""
            SELECT batch_no,SUM(actual_qty) qty FROM `tabStock Ledger Entry`
            WHERE item_code=%s AND warehouse=%s AND IFNULL(batch_no,'')!=''
            GROUP BY batch_no HAVING SUM(actual_qty)>=3 ORDER BY qty DESC LIMIT 1
        """,(row.item_code,row.warehouse),as_dict=True)
        if batch:
            row.batch_no=batch[0].batch_no; return row
    return None

def run():
    for dt in REQUIRED: _assert(frappe.db.exists("DocType",dt),f"Missing DocType: {dt}")
    _assert(frappe.db.exists("Report","Stock by Location"),"Missing report: Stock by Location")
    c=_candidate(); _assert(c,"No stock candidate with qty >= 3 for transactional verification")
    token=uuid.uuid4().hex[:8].upper()
    try:
        a=frappe.get_doc({"doctype":"Pharmacy Storage Location","location_code":f"TST-A-{token}","location_name":f"Test Selling {token}","warehouse":c.warehouse,"location_type":"Zone","purpose":"Selling","replenishment_priority":10}).insert(ignore_permissions=True)
        s=frappe.get_doc({"doctype":"Pharmacy Storage Location","location_code":f"TST-S-{token}","location_name":f"Test Reserve {token}","warehouse":c.warehouse,"location_type":"Zone","purpose":"Reserve","replenishment_priority":20}).insert(ignore_permissions=True)
        p=frappe.get_doc({"doctype":"Pharmacy Putaway","warehouse":c.warehouse,"remarks":"Automated v0.9.3 Step2A verification","items":[{"item_code":c.item_code,"batch_no":c.batch_no,"qty":2,"to_location":a.name}]})
        p.insert(ignore_permissions=True); p.submit()
        _assert(abs(get_allocated_qty(c.item_code,c.warehouse,c.batch_no,a.name)-2)<1e-9,"Putaway mismatch")
        t=frappe.get_doc({"doctype":"Pharmacy Location Transfer","warehouse":c.warehouse,"reason":"Automated v0.9.3 Step2A verification","items":[{"item_code":c.item_code,"batch_no":c.batch_no,"qty":1,"from_location":a.name,"to_location":s.name}]})
        t.insert(ignore_permissions=True); t.submit()
        _assert(abs(get_allocated_qty(c.item_code,c.warehouse,c.batch_no,a.name)-1)<1e-9,"Transfer source mismatch")
        _assert(abs(get_allocated_qty(c.item_code,c.warehouse,c.batch_no,s.name)-1)<1e-9,"Transfer target mismatch")
        t.cancel()
        _assert(abs(get_allocated_qty(c.item_code,c.warehouse,c.batch_no,a.name)-2)<1e-9,"Transfer cancel mismatch")
        p.cancel()
        _assert(abs(get_allocated_qty(c.item_code,c.warehouse,c.batch_no,a.name))<1e-9,"Putaway cancel mismatch")
        movements=frappe.db.count("Pharmacy Location Movement",filters={"reference_name":["in",[p.name,t.name]]})
        _assert(movements==4,f"Expected 4 movement rows, found {movements}")
        result={"status":"PASS","warehouse":c.warehouse,"item_code":c.item_code,"batch_no":c.batch_no,"putaway":p.name,"transfer":t.name,"movement_rows":movements,"transaction_rolled_back":True}
        frappe.db.rollback(); return result
    except Exception:
        frappe.db.rollback(); raise
