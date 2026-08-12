from __future__ import annotations

import frappe


DOCTYPES = (
    ("pharmacy_shift_closing", "Pharmacy Shift Closing"),
    ("delivery_settlement", "Delivery Settlement"),
    ("delivery_handover", "Delivery Handover"),
)


def execute():
    """Install canonical Branch fields without attributing historical rows."""
    for document_name, doctype in DOCTYPES:
        frappe.reload_doc(
            "pharma_erp",
            "doctype",
            document_name,
            force=True,
        )
        frappe.db.updatedb(doctype)
        frappe.clear_cache(doctype=doctype)

    # Deliberately no backfill: historical blank values are Not Attributable.
