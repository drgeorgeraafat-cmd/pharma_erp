from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class PharmacyReturnCase(Document):
    def validate(self):
        self._validate_party_responsibility()
        self._validate_invoice_link()
        self._calculate_totals()
        self._validate_settlement()

    def _validate_party_responsibility(self):
        if not self.supplier:
            frappe.throw(_("Receiving Company / Distributor is required."))

    def _validate_invoice_link(self):
        if self.return_type != "Return Against Invoice":
            return
        if not self.original_purchase_invoice:
            frappe.throw(_("Original Purchase Invoice is required."))
        invoice = frappe.db.get_value(
            "Purchase Invoice", self.original_purchase_invoice,
            ["supplier", "company", "docstatus", "is_return"], as_dict=True,
        )
        if not invoice or invoice.docstatus != 1 or invoice.is_return:
            frappe.throw(_("Original Purchase Invoice must be submitted and must not be a return."))
        if invoice.supplier != self.supplier:
            frappe.throw(_("For an invoice-linked return, the receiving supplier must match the original invoice supplier."))
        if invoice.company != self.company:
            frappe.throw(_("Original Purchase Invoice belongs to another company."))

    def _calculate_totals(self):
        requested = 0.0
        for row in self.items:
            if flt(row.return_qty) < 0:
                frappe.throw(_("Return quantity cannot be negative."))
            if flt(row.return_qty) > flt(row.available_to_return_qty) + 0.000001:
                frappe.throw(_("Row {0}: Return quantity exceeds available quantity.").format(row.idx))
            row.return_amount = flt(row.return_qty) * flt(row.rate)
            requested += flt(row.return_amount)
        self.requested_return_value = requested
        self.rejected_return_value = max(0.0, requested - flt(self.approved_return_value))
        self.remaining_settlement_amount = max(
            0.0,
            flt(self.approved_return_value) - flt(self.claim_deduction_amount) - flt(self.refund_amount),
        )

    def _validate_settlement(self):
        if flt(self.claim_deduction_amount) + flt(self.refund_amount) > flt(self.approved_return_value) + 0.000001:
            frappe.throw(_("Claim deduction plus refund cannot exceed the approved return value."))
