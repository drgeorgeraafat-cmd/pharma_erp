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
        self._validate_supplier_handover()
        self._validate_supplier_response()
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

    def _validate_supplier_handover(self):
        if self.return_type != "Regulatory Batch Recall":
            return

        delivered_rows = [row for row in self.items if flt(row.delivered_qty) > 0]
        if self.get("handover_stock_entry") or delivered_rows:
            if not self.get("returns_with_supplier_warehouse"):
                frappe.throw(_("Returns With Supplier Warehouse is required for supplier handover."))
            warehouse = frappe.db.get_value(
                "Warehouse", self.get("returns_with_supplier_warehouse"),
                ["company", "is_group", "disabled"], as_dict=True,
            )
            if not warehouse or warehouse.company != self.company or warehouse.is_group or warehouse.disabled:
                frappe.throw(_("Select an active non-group Returns With Supplier Warehouse for the same company."))

        for row in self.items:
            delivered = flt(row.delivered_qty)
            quarantined = flt(row.quarantined_qty) or flt(row.return_qty)
            if delivered < 0:
                frappe.throw(_("Row {0}: Handover quantity cannot be negative.").format(row.idx))
            if delivered > quarantined + 0.000001:
                frappe.throw(
                    _("Row {0}: Handover quantity cannot exceed quarantined quantity {1}.").format(
                        row.idx, quarantined
                    )
                )
            accepted = flt(row.accepted_qty)
            rejected = flt(row.rejected_qty)
            if accepted + rejected > delivered + 0.000001:
                frappe.throw(
                    _("Row {0}: Accepted plus rejected quantity cannot exceed handed-over quantity.").format(
                        row.idx
                    )
                )

    def _validate_supplier_response(self):
        if self.return_type != "Regulatory Batch Recall":
            return

        response_rows = [
            row for row in self.items
            if flt(row.accepted_qty) > 0
            or flt(row.rejected_qty) > 0
            or flt(row.approved_rate) > 0
            or (row.rejection_reason or "").strip()
        ]
        if not response_rows:
            return

        if not self.get("handover_stock_entry"):
            frappe.throw(_("Supplier response cannot be recorded before supplier handover."))

        handover_status = frappe.db.get_value(
            "Stock Entry",
            self.get("handover_stock_entry"),
            "docstatus",
        )
        if handover_status != 1:
            frappe.throw(_("Submit the Supplier Handover Stock Entry before recording the supplier response."))

        if not self.get("supplier_response_date"):
            frappe.throw(_("Supplier Response Date is required."))
        if not self.get("supplier_response_reference"):
            frappe.throw(_("Supplier Response Reference is required."))

        for row in self.items:
            delivered = flt(row.delivered_qty)
            accepted = flt(row.accepted_qty)
            rejected = flt(row.rejected_qty)
            approved_rate = flt(row.approved_rate)

            if accepted < 0 or rejected < 0 or approved_rate < 0:
                frappe.throw(_("Row {0}: Supplier response quantities and rate cannot be negative.").format(row.idx))
            if accepted + rejected > delivered + 0.000001:
                frappe.throw(
                    _("Row {0}: Accepted plus rejected quantity cannot exceed handed-over quantity {1}.").format(
                        row.idx, delivered
                    )
                )
            if accepted > 0 and approved_rate <= 0:
                frappe.throw(_("Row {0}: Approved Settlement Rate is required for accepted quantity.").format(row.idx))
            if rejected > 0 and not (row.rejection_reason or "").strip():
                frappe.throw(_("Row {0}: Supplier Rejection Reason is required.").format(row.idx))

    def _calculate_totals(self):
        requested = 0.0
        quarantined = 0.0
        handed_over = 0.0
        accepted = 0.0
        rejected = 0.0
        rejected_returned = 0.0
        approved = 0.0
        for row in self.items:
            if flt(row.return_qty) < 0:
                frappe.throw(_("Return quantity cannot be negative."))
            if flt(row.return_qty) > flt(row.available_to_return_qty) + 0.000001:
                frappe.throw(_("Row {0}: Return quantity exceeds available quantity.").format(row.idx))
            row.return_amount = flt(row.return_qty) * flt(row.rate)
            requested += flt(row.return_amount)
            quarantined += flt(row.quarantined_qty)
            handed_over += flt(row.delivered_qty)
            accepted += flt(row.accepted_qty)
            rejected += flt(row.rejected_qty)
            rejected_returned += flt(row.rejected_returned_qty)
            row.accepted_amount = flt(row.accepted_qty) * flt(row.approved_rate)
            approved += flt(row.accepted_amount)
        self.requested_return_value = requested
        self.quarantined_quantity = quarantined
        self.handed_over_quantity = handed_over
        self.accepted_quantity = accepted
        self.rejected_quantity = rejected
        self.pending_response_quantity = max(0.0, handed_over - accepted - rejected)
        self.rejected_return_quantity = rejected_returned
        self.approved_return_value = approved
        self.rejected_return_value = max(0.0, requested - approved)
        self.remaining_settlement_amount = max(
            0.0,
            flt(self.approved_return_value) - flt(self.claim_deduction_amount) - flt(self.refund_amount),
        )

    def _validate_settlement(self):
        if flt(self.claim_deduction_amount) + flt(self.refund_amount) > flt(self.approved_return_value) + 0.000001:
            frappe.throw(_("Claim deduction plus refund cannot exceed the approved return value."))
