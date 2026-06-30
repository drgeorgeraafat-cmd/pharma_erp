frappe.ui.form.on("Supplier Claim", {
    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Fetch Eligible Invoices"), async () => {
                if (!frm.doc.supplier || !frm.doc.company || !frm.doc.period_from || !frm.doc.period_to) {
                    frappe.msgprint(__("Select Company, Supplier and Claim Period first."));
                    return;
                }
                const r = await frappe.call({
                    method: "pharma_erp.pharma_erp.doctype.supplier_claim.supplier_claim.get_eligible_invoices",
                    args: { supplier: frm.doc.supplier, company: frm.doc.company, period_from: frm.doc.period_from, period_to: frm.doc.period_to },
                    freeze: true,
                    freeze_message: __("Fetching eligible invoices...")
                });
                frm.clear_table("invoices");
                (r.message || []).forEach((row) => frm.add_child("invoices", row));
                frm.refresh_field("invoices");
                frm.trigger("recalculate");
            });
        }
    },
    supplier_printed_claim_total(frm) { frm.trigger("recalculate"); },
    net_amount_to_pay(frm) { frm.trigger("recalculate"); },
    recalculate(frm) {
        const rows = frm.doc.invoices || [];
        const gross = rows.filter(r => flt(r.included_amount) >= 0).reduce((s,r)=>s+flt(r.included_amount),0);
        const returns = Math.abs(rows.filter(r => flt(r.included_amount) < 0).reduce((s,r)=>s+flt(r.included_amount),0));
        const system = gross - returns;
        frm.set_value("gross_claim_total", gross);
        frm.set_value("purchase_returns_total", returns);
        frm.set_value("system_claim_total", system);
        const printed = flt(frm.doc.supplier_printed_claim_total);
        frm.set_value("match_status", printed ? (Math.abs(printed-system)<0.005 ? "Matched" : "Mismatch") : "Not Checked");
        const net = flt(frm.doc.net_amount_to_pay);
        const discount = net ? system-net : 0;
        frm.set_value("settlement_discount_amount", discount);
        frm.set_value("settlement_discount_percentage", system ? discount/system*100 : 0);
    }
});
frappe.ui.form.on("Supplier Claim Invoice", {
    invoices_add(frm) { frm.trigger("recalculate"); },
    invoices_remove(frm) { frm.trigger("recalculate"); },
    included_amount(frm) { frm.trigger("recalculate"); }
});
