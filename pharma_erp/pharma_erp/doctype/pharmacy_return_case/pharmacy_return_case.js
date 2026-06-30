frappe.ui.form.on("Pharmacy Return Case", {
    refresh(frm) {
        if (frm.doc.original_purchase_invoice) {
            frm.add_custom_button(__("Original Purchase Invoice"), () => {
                frappe.set_route("Form", "Purchase Invoice", frm.doc.original_purchase_invoice);
            }, __("View"));
        }
        if (frm.doc.purchase_return) {
            frm.add_custom_button(__("Official Purchase Return"), () => {
                frappe.set_route("Form", "Purchase Invoice", frm.doc.purchase_return);
            }, __("View"));
        }
        if (frm.doc.quarantine_stock_entry) {
            frm.add_custom_button(__("Quarantine Stock Entry"), () => {
                frappe.set_route("Form", "Stock Entry", frm.doc.quarantine_stock_entry);
            }, __("View"));
        }
        if (frm.doc.handover_stock_entry) {
            frm.add_custom_button(__("Supplier Handover Stock Entry"), () => {
                frappe.set_route("Form", "Stock Entry", frm.doc.handover_stock_entry);
            }, __("View"));
        }
        frm.add_custom_button(__("Returns Management"), () => frappe.set_route("purchase-returns-management"));
    },
    approved_return_value: calculate_settlement,
    claim_deduction_amount: calculate_settlement,
    refund_amount: calculate_settlement,
});

function calculate_settlement(frm) {
    const approved = flt(frm.doc.approved_return_value);
    const rejected = Math.max(0, flt(frm.doc.requested_return_value) - approved);
    const remaining = Math.max(0, approved - flt(frm.doc.claim_deduction_amount) - flt(frm.doc.refund_amount));
    frm.set_value("rejected_return_value", rejected);
    frm.set_value("remaining_settlement_amount", remaining);
}
