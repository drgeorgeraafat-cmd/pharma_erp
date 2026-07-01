import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class SupplierClaim(Document):
    def validate(self):
        if self.period_from and self.period_to and getdate(self.period_from) > getdate(self.period_to):
            frappe.throw(_("Period From cannot be after Period To."))
        self._calculate_totals()

    def before_submit(self):
        self._calculate_totals()
        if not self.invoices:
            frappe.throw(_("Fetch at least one eligible supplier invoice."))
        if self.match_status != "Matched":
            frappe.throw(_("Supplier Printed Claim Total must match the System Claim Total exactly."))
        meta = frappe.get_meta("Purchase Invoice")
        for row in self.invoices:
            linked = frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim") if meta.has_field("custom_supplier_claim") else None
            if linked and linked != self.name:
                frappe.throw(_("Purchase Invoice {0} already belongs to Supplier Claim {1}.").format(row.purchase_invoice, linked))
        self.status = "Approved"

    def on_submit(self):
        meta = frappe.get_meta("Purchase Invoice")
        for row in self.invoices:
            if meta.has_field("custom_supplier_claim"):
                frappe.db.set_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim", self.name, update_modified=False)
        self._sync_return_cases(cancel=False)

    def on_update_after_submit(self):
        self._sync_return_cases(cancel=False)

    def on_cancel(self):
        meta = frappe.get_meta("Purchase Invoice")
        for row in self.invoices:
            if meta.has_field("custom_supplier_claim") and frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim") == self.name:
                frappe.db.set_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim", None, update_modified=False)
        self._sync_return_cases(cancel=True)
        self.db_set("status", "Cancelled", update_modified=False)

    def _calculate_totals(self):
        positives = sum(flt(row.included_amount) for row in self.invoices if flt(row.included_amount) >= 0)
        returns = abs(sum(flt(row.included_amount) for row in self.invoices if flt(row.included_amount) < 0))
        system_total = positives - returns
        self.gross_claim_total = positives
        self.purchase_returns_total = returns
        self.system_claim_total = system_total
        printed = flt(self.supplier_printed_claim_total)
        self.match_status = "Matched" if self.supplier_printed_claim_total not in (None, "") and round(printed,2)==round(system_total,2) else ("Mismatch" if self.supplier_printed_claim_total not in (None, "") else "Not Checked")
        net = flt(self.net_amount_to_pay)
        if system_total <= 0:
            # A new claim may temporarily contain only the approved Debit Note.
            # Until positive supplier invoices are fetched, nothing is payable.
            if abs(net) > 0.005:
                frappe.throw(
                    _(
                        "Net Amount To Pay must be zero while the claim contains "
                        "only purchase returns / debit notes."
                    )
                )
            self.settlement_discount_amount = 0
            self.settlement_discount_percentage = 0
        else:
            if net < 0 or net > system_total:
                frappe.throw(
                    _("Net Amount To Pay must be between zero and the System Claim Total.")
                )
            self.settlement_discount_amount = system_total - net
            self.settlement_discount_percentage = (
                self.settlement_discount_amount / system_total * 100
            )

    def _return_case_settlement_base(self, case, row):
        note_total = abs(
            flt(
                frappe.db.get_value(
                    "Purchase Invoice",
                    row.purchase_invoice,
                    "grand_total",
                )
            )
        )
        if note_total:
            return note_total

        if case.return_type == "Regulatory Batch Recall":
            return flt(case.approved_return_value)

        return (
            flt(case.approved_return_value)
            or flt(case.requested_return_value)
            or abs(flt(row.included_amount))
        )

    def _status_before_claim(self, case):
        if case.return_type == "Return Against Invoice":
            if case.purchase_return:
                docstatus = frappe.db.get_value(
                    "Purchase Invoice",
                    case.purchase_return,
                    "docstatus",
                )
                if docstatus == 1:
                    return "Purchase Return Submitted"
                if docstatus == 0:
                    return "Purchase Return Draft Created"
            return "Under Review"

        if case.get("approved_debit_note"):
            docstatus = frappe.db.get_value(
                "Purchase Invoice",
                case.get("approved_debit_note"),
                "docstatus",
            )
            if docstatus == 1:
                return "Approved Debit Note Submitted"
            if docstatus == 0:
                return "Approved Debit Note Draft Created"

        return case.operational_status or "Under Review"

    def _sync_return_cases(self, cancel=False):
        meta = frappe.get_meta("Purchase Invoice")
        if not meta.has_field("custom_pharmacy_return_case"):
            return

        for row in self.invoices:
            if not row.is_return:
                continue

            case_name = frappe.db.get_value(
                "Purchase Invoice",
                row.purchase_invoice,
                "custom_pharmacy_return_case",
            )
            if not case_name or not frappe.db.exists(
                "Pharmacy Return Case",
                case_name,
            ):
                continue

            case = frappe.get_doc("Pharmacy Return Case", case_name)
            settlement_base = self._return_case_settlement_base(case, row)
            deduction = min(
                settlement_base,
                abs(flt(row.included_amount)),
            )
            refund = flt(case.refund_amount)

            case.approved_return_value = settlement_base
            case.rejected_return_value = max(
                0.0,
                flt(case.requested_return_value) - settlement_base,
            )

            if cancel:
                case.supplier_claim = None
                case.planned_claim_deduction_amount = 0
                case.claim_deduction_amount = 0
                case.settled_amount = refund
                case.remaining_settlement_amount = max(
                    0.0,
                    settlement_base - refund,
                )
                case.settlement_status = (
                    "Partially Settled"
                    if refund > 0
                    else "Pending Settlement"
                )
                case.operational_status = self._status_before_claim(case)
                case.save(ignore_permissions=True)
                continue

            case.supplier_claim = self.name
            case.settlement_method = (
                "Mixed Settlement"
                if refund > 0
                else "Deduct from Supplier Claim"
            )
            case.planned_claim_deduction_amount = deduction
            case.claim_deduction_amount = deduction
            case.settled_amount = deduction + refund
            case.remaining_settlement_amount = max(
                0.0,
                settlement_base - deduction - refund,
            )

            if (
                self.status == "Paid"
                and case.remaining_settlement_amount <= 0.01
            ):
                case.settlement_status = "Settled"
                case.operational_status = "Financially Settled"
            else:
                case.settlement_status = (
                    "Claim Deduction Confirmed"
                    if case.remaining_settlement_amount <= 0.01
                    else "Partially Settled"
                )
                case.operational_status = "Claim Deduction Confirmed"

            case.save(ignore_permissions=True)


@frappe.whitelist()
def get_eligible_invoices(
    supplier,
    company,
    period_from,
    period_to,
    claim_basis="Supplier Invoice Date",
):
    if not frappe.has_permission("Purchase Invoice", "read"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)

    period_from = getdate(period_from)
    period_to = getdate(period_to)
    claim_basis = claim_basis or "Supplier Invoice Date"

    if claim_basis == "Posting Date":
        date_condition = "`posting_date` between %(period_from)s and %(period_to)s"
    else:
        # Supplier Invoice Date is preferred. For invoices/debit notes where
        # Bill Date is empty, Posting Date is the operational fallback.
        date_condition = (
            "coalesce(`bill_date`, `posting_date`) "
            "between %(period_from)s and %(period_to)s"
        )

    rows = frappe.db.sql(
        f"""
        select
            name,
            bill_no,
            bill_date,
            posting_date,
            grand_total,
            outstanding_amount,
            is_return,
            status
        from `tabPurchase Invoice`
        where supplier = %(supplier)s
          and company = %(company)s
          and docstatus = 1
          and {date_condition}
        order by
            coalesce(bill_date, posting_date) asc,
            posting_date asc,
            name asc
        """,
        {
            "supplier": supplier,
            "company": company,
            "period_from": period_from,
            "period_to": period_to,
        },
        as_dict=True,
    )

    result = []
    meta = frappe.get_meta("Purchase Invoice")
    for row in rows:
        classification = (
            frappe.db.get_value(
                "Purchase Invoice",
                row.name,
                "custom_payment_classification",
            )
            if meta.has_field("custom_payment_classification")
            else ""
        )
        excluded = (
            frappe.db.get_value(
                "Purchase Invoice",
                row.name,
                "custom_exclude_from_supplier_claim",
            )
            if meta.has_field("custom_exclude_from_supplier_claim")
            else 0
        )
        linked = (
            frappe.db.get_value(
                "Purchase Invoice",
                row.name,
                "custom_supplier_claim",
            )
            if meta.has_field("custom_supplier_claim")
            else ""
        )

        if linked or excluded:
            continue
        if classification and classification != "Claim Invoice" and not row.is_return:
            continue

        amount = (
            -abs(flt(row.grand_total))
            if row.is_return
            else flt(row.grand_total)
        )
        result.append(
            {
                "purchase_invoice": row.name,
                "supplier_invoice_no": row.bill_no,
                "supplier_invoice_date": row.bill_date or row.posting_date,
                "posting_date": row.posting_date,
                "grand_total": flt(row.grand_total),
                "outstanding_amount": flt(row.outstanding_amount),
                "included_amount": amount,
                "is_return": row.is_return,
                "invoice_status": row.status,
            }
        )

    return result
