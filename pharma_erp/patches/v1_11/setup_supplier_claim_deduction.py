from __future__ import annotations
import json, os
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.modules.import_file import import_file_by_path
CASE_FIELDS=("supplier_claim","settlement_status","planned_claim_deduction_amount","settled_amount")
def execute():
    path=frappe.get_app_path("pharma_erp","pharma_erp","doctype","pharmacy_return_case","pharmacy_return_case.json")
    if not os.path.exists(path): frappe.throw(f"Missing DocType JSON file: {path}")
    data=json.load(open(path,encoding="utf-8")); names={f.get("fieldname") for f in data.get("fields",[]) if f.get("fieldname")}
    missing=[f for f in CASE_FIELDS if f not in names]
    if missing: frappe.throw(f"Outdated Pharmacy Return Case JSON. Missing fields: {', '.join(missing)}")
    import_file_by_path(path,force=True); frappe.clear_cache(); frappe.db.updatedb("Pharmacy Return Case")
    absent=[f for f in CASE_FIELDS if not frappe.db.has_column("Pharmacy Return Case",f)]
    if absent: frappe.throw("Supplier Claim deduction schema sync failed: "+frappe.as_json(absent))
    create_custom_fields({"Purchase Invoice":[
        {"fieldname":"custom_supplier_claim","label":"Supplier Claim","fieldtype":"Link","options":"Supplier Claim","insert_after":"custom_pharmacy_return_case","read_only":1,"no_copy":1,"allow_on_submit":1},
        {"fieldname":"custom_payment_classification","label":"Payment Classification","fieldtype":"Select","options":"\nCash Invoice\nClaim Invoice\nCredit Invoice Outside Claim","insert_after":"custom_supplier_claim","allow_on_submit":1},
        {"fieldname":"custom_exclude_from_supplier_claim","label":"Exclude from Supplier Claim","fieldtype":"Check","insert_after":"custom_payment_classification","allow_on_submit":1,"default":"0"}
    ]},update=True)
    frappe.clear_cache()
