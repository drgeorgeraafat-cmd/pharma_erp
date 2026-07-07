from __future__ import annotations

import frappe
from frappe import _

SUPPLIER_SETTLEMENT_POLICY_OPTIONS = """
Cash Per Invoice
Claim Only
Mixed Cash + Claim
Credit Outside Claim"""
PAYMENT_CLASSIFICATION_OPTIONS = """
Cash Invoice
Claim Invoice
Credit Invoice Outside Claim"""

POLICY_TO_CLASSIFICATION = {
    "Cash Per Invoice": "Cash Invoice",
    "Claim Only": "Claim Invoice",
    "Mixed Cash + Claim": "Claim Invoice",
    "Credit Outside Claim": "Credit Invoice Outside Claim",
}


def default_classification_for_policy(policy: str | None) -> str:
    return POLICY_TO_CLASSIFICATION.get((policy or "").strip(), "")


def legacy_policy_from_supplier(payment_model: str | None = None, supplier_type: str | None = None) -> str:
    payment_model = (payment_model or "").strip()
    supplier_type = (supplier_type or "").strip()
    if payment_model == "Cash":
        return "Cash Per Invoice"
    if payment_model == "Mixed":
        return "Mixed Cash + Claim"
    if payment_model == "Credit Claim" or (supplier_type == "Distribution Company" and payment_model != "Mixed"):
        return "Claim Only"
    return ""


def ensure_supplier_settlement_policy_fields() -> dict:
    """Create/update the lightweight custom fields used by Purchase/Supplier running account.

    This is intentionally safe to run repeatedly. It does not create GL, Payment Entry,
    Journal Entry, Purchase Invoice, or any accounting document.
    """
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    custom_fields = {
        "Supplier": [
            {
                "fieldname": "custom_supplier_settlement_policy",
                "label": "Supplier Settlement Policy",
                "fieldtype": "Select",
                "insert_after": "supplier_type",
                "options": SUPPLIER_SETTLEMENT_POLICY_OPTIONS,
                "description": "Default settlement classification for new purchase invoices. Mixed defaults to Claim Invoice and can be changed manually per invoice.",
            }
        ],
        "Purchase Invoice": [
            {
                "fieldname": "custom_payment_classification",
                "label": "Settlement Classification",
                "fieldtype": "Select",
                "insert_after": "supplier",
                "options": PAYMENT_CLASSIFICATION_OPTIONS,
                "description": "Operational settlement tag only. It does not split supplier accounting; Supplier Running Account remains the unified ledger.",
            }
        ],
    }
    create_custom_fields(custom_fields, update=True)

    # Keep legacy field label aligned if it already existed from earlier versions.
    cf_name = "Purchase Invoice-custom_payment_classification"
    if frappe.db.exists("Custom Field", cf_name):
        frappe.db.set_value("Custom Field", cf_name, {
            "label": "Settlement Classification",
            "options": PAYMENT_CLASSIFICATION_OPTIONS,
            "description": "Operational settlement tag only. It does not split supplier accounting; Supplier Running Account remains the unified ledger.",
        })

    frappe.clear_cache(doctype="Supplier")
    frappe.clear_cache(doctype="Purchase Invoice")
    frappe.db.commit()
    return {"ok": 1, "message": _("Supplier settlement policy fields are ready.")}
