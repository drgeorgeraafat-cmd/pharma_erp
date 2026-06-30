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
        for row in self.invoices:
            linked = frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim")
            if linked and linked != self.name:
                frappe.throw(_("Purchase Invoice {0} already belongs to Supplier Claim {1}.").format(row.purchase_invoice, linked))
        self.status = "Approved"

    def on_submit(self):
        for row in self.invoices:
            if frappe.get_meta("Purchase Invoice").has_field("custom_supplier_claim"):
                frappe.db.set_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim", self.name, update_modified=False)

    def on_cancel(self):
        for row in self.invoices:
            if frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim") == self.name:
                frappe.db.set_value("Purchase Invoice", row.purchase_invoice, "custom_supplier_claim", None, update_modified=False)
        self.db_set("status", "Cancelled", update_modified=False)

    def _calculate_totals(self):
        positives = sum(flt(row.included_amount) for row in self.invoices if flt(row.included_amount) >= 0)
        returns = abs(sum(flt(row.included_amount) for row in self.invoices if flt(row.included_amount) < 0))
        system_total = positives - returns
        self.gross_claim_total = positives
        self.purchase_returns_total = returns
        self.system_claim_total = system_total
        printed = flt(self.supplier_printed_claim_total)
        self.match_status = "Matched" if printed and round(printed, 2) == round(system_total, 2) else ("Mismatch" if printed else "Not Checked")
        net = flt(self.net_amount_to_pay)
        if net < 0 or net > system_total:
            frappe.throw(_("Net Amount To Pay must be between zero and the System Claim Total."))
        self.settlement_discount_amount = system_total - net if net else 0
        self.settlement_discount_percentage = (self.settlement_discount_amount / system_total * 100) if system_total else 0


@frappe.whitelist()
def get_eligible_invoices(supplier, company, period_from, period_to):
    if not frappe.has_permission("Purchase Invoice", "read"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)
    fields = ["name","bill_no","bill_date","posting_date","grand_total","outstanding_amount","is_return","status"]
    filters = {"supplier":supplier,"company":company,"docstatus":1,"bill_date":["between",[getdate(period_from),getdate(period_to)]]}
    rows = frappe.get_list("Purchase Invoice", filters=filters, fields=fields, order_by="bill_date asc, posting_date asc", limit_page_length=5000)
    result=[]
    for row in rows:
        classification = frappe.db.get_value("Purchase Invoice", row.name, "custom_payment_classification") if frappe.get_meta("Purchase Invoice").has_field("custom_payment_classification") else ""
        excluded = frappe.db.get_value("Purchase Invoice", row.name, "custom_exclude_from_supplier_claim") if frappe.get_meta("Purchase Invoice").has_field("custom_exclude_from_supplier_claim") else 0
        linked = frappe.db.get_value("Purchase Invoice", row.name, "custom_supplier_claim") if frappe.get_meta("Purchase Invoice").has_field("custom_supplier_claim") else ""
        if linked or excluded or (classification and classification != "Claim Invoice" and not row.is_return):
            continue
        amount = -abs(flt(row.grand_total)) if row.is_return else flt(row.grand_total)
        result.append({
            "purchase_invoice":row.name,"supplier_invoice_no":row.bill_no,"supplier_invoice_date":row.bill_date or row.posting_date,
            "posting_date":row.posting_date,"grand_total":flt(row.grand_total),"outstanding_amount":flt(row.outstanding_amount),
            "included_amount":amount,"is_return":row.is_return,"invoice_status":row.status,
        })
    return result
