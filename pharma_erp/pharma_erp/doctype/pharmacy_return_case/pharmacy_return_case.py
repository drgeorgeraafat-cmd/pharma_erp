from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class PharmacyReturnCase(Document):
    def validate(self):
        self._validate_party_responsibility()
        self._validate_invoice_link()
        self._validate_regulatory_recall()
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

    def _validate_regulatory_recall(self):
        if self.return_type != "Regulatory Batch Recall":
            return
        if not self.authority_notification_no:
            frappe.throw(_("Authority Notification Number is required."))
        if not self.authority_notification_date:
            frappe.throw(_("Authority Notification Date is required."))
        if not self.recall_quarantine_warehouse:
            frappe.throw(_("Recall Quarantine Warehouse is required."))
        warehouse = frappe.db.get_value(
            "Warehouse", self.recall_quarantine_warehouse,
            ["company", "is_group", "disabled"], as_dict=True,
        )
        if not warehouse or warehouse.company != self.company or warehouse.is_group or warehouse.disabled:
            frappe.throw(_("Select an active non-group quarantine warehouse for the same company."))
        selected = [row for row in self.items if flt(row.return_qty) > 0]
        if not selected:
            frappe.throw(_("Add at least one recalled batch quantity."))
        for row in selected:
            if not row.batch_no:
                frappe.throw(_("Row {0}: Batch No is required for a regulatory recall.").format(row.idx))
            row.return_reason = "Health Authority Recall"
            row.quarantine_warehouse = self.recall_quarantine_warehouse

    def _calculate_totals(self):
        requested = 0.0
        quarantined = 0.0
        for row in self.items:
            if flt(row.return_qty) < 0:
                frappe.throw(_("Return quantity cannot be negative."))
            if flt(row.return_qty) > flt(row.available_to_return_qty) + 0.000001:
                frappe.throw(_("Row {0}: Return quantity exceeds available quantity.").format(row.idx))
            row.return_amount = flt(row.return_qty) * flt(row.rate)
            requested += flt(row.return_amount)
            quarantined += flt(row.quarantined_qty)
        self.requested_return_value = requested
        self.quarantined_quantity = quarantined
        self.rejected_return_value = max(0.0, requested - flt(self.approved_return_value))
        self.remaining_settlement_amount = max(
            0.0,
            flt(self.approved_return_value) - flt(self.claim_deduction_amount) - flt(self.refund_amount),
        )

    def _validate_settlement(self):
        if flt(self.claim_deduction_amount) + flt(self.refund_amount) > flt(self.approved_return_value) + 0.000001:
            frappe.throw(_("Claim deduction plus refund cannot exceed the approved return value."))
