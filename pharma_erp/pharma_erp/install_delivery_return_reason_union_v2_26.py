import frappe

from pharma_erp.pharma_erp.delivery_partial_return import (
    ensure_partial_return_reason_options,
)


VERSION = "2.26"


def install():
    """Align full-order and partial-item return reason Select options."""
    result = ensure_partial_return_reason_options()
    frappe.db.commit()
    return {
        "version": VERSION,
        "ready": True,
        "reason_options": result,
    }
