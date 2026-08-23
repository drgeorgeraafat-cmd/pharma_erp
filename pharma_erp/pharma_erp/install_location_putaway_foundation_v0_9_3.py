import frappe

UNIQUE_SPECS = [
    ("Pharmacy Storage Location", ["warehouse", "location_code"], "uniq_pharmacy_storage_location"),
    ("Pharmacy Location Balance", ["warehouse", "location", "item_code", "batch_key"], "uniq_pharmacy_location_balance"),
    ("Pharmacy Location Movement", ["dedupe_key"], "uniq_pharmacy_location_movement_dedupe"),
]

def _index_exists(doctype, index_name):
    row = frappe.db.sql("""
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema=DATABASE() AND table_name=%s AND index_name=%s LIMIT 1
    """, (f"tab{doctype}", index_name))
    return bool(row)

def install():
    results=[]
    for doctype, fields, index_name in UNIQUE_SPECS:
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType missing after migrate: {doctype}")
        if _index_exists(doctype, index_name):
            results.append(f"{index_name}:EXISTS")
            continue
        frappe.db.add_unique(doctype, fields, constraint_name=index_name)
        results.append(f"{index_name}:CREATED")
    frappe.db.commit()
    return {"status":"PASS","indexes":results}
