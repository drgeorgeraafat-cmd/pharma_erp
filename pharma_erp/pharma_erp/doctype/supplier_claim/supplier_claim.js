frappe.ui.form.on("Supplier Claim", {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.status === "Approved") {
            frm.dashboard.set_headline_alert(
                __("Claim deduction is confirmed. Final financial settlement occurs after claim payment and reconciliation."),
                "blue"
            );
        }
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Fetch Eligible Invoices"), async () => {
                if (!frm.doc.supplier || !frm.doc.company || !frm.doc.period_from || !frm.doc.period_to) {
                    frappe.msgprint(__("Select Company, Supplier and Claim Period first."));
                    return;
                }
                const existingRows = (frm.doc.invoices || []).map((row) => ({
                    purchase_invoice: row.purchase_invoice,
                    supplier_invoice_no: row.supplier_invoice_no,
                    supplier_invoice_date: row.supplier_invoice_date,
                    posting_date: row.posting_date,
                    grand_total: flt(row.grand_total),
                    outstanding_amount: flt(row.outstanding_amount),
                    included_amount: flt(row.included_amount),
                    is_return: cint(row.is_return),
                    invoice_status: row.invoice_status
                }));

                const preservedReturns = existingRows.filter(
                    (row) => row.purchase_invoice
                        && (cint(row.is_return) || flt(row.included_amount) < 0)
                );

                const r = await frappe.call({
                    method: "pharma_erp.pharma_erp.doctype.supplier_claim.supplier_claim.get_eligible_invoices",
                    args: {
                        supplier: frm.doc.supplier,
                        company: frm.doc.company,
                        period_from: frm.doc.period_from,
                        period_to: frm.doc.period_to,
                        claim_basis: frm.doc.claim_basis || "Supplier Invoice Date"
                    },
                    freeze: true,
                    freeze_message: __("Fetching eligible invoices...")
                });

                const merged = new Map();
                preservedReturns.forEach((row) => {
                    merged.set(row.purchase_invoice, row);
                });
                (r.message || []).forEach((row) => {
                    if (!merged.has(row.purchase_invoice)) {
                        merged.set(row.purchase_invoice, row);
                    }
                });

                frm.clear_table("invoices");
                Array.from(merged.values()).forEach(
                    (row) => frm.add_child("invoices", row)
                );
                frm.refresh_field("invoices");
                frm.trigger("recalculate");

                const fetchedPositiveCount = Array.from(merged.values()).filter(
                    (row) => !cint(row.is_return) && flt(row.included_amount) >= 0
                ).length;
                if (!fetchedPositiveCount) {
                    frappe.show_alert({
                        message: __("No eligible positive supplier invoices were found for this period. Existing Debit Notes were preserved."),
                        indicator: "orange"
                    }, 8);
                }
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
