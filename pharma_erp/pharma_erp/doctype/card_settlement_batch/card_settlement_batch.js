frappe.ui.form.on("Card Settlement Batch", {
    refresh(frm) {
        if (frm.doc.docstatus === 0 && !frm.is_new()) {
            frm.add_custom_button(__("Refresh Transactions"), async () => {
                await frappe.call({
                    method: "pharma_erp.pharma_erp.payment_card_management.refresh_card_batch",
                    args: { batch_name: frm.doc.name },
                    freeze: true,
                });
                await frm.reload_doc();
            });
        }
    },

    machine_total(frm) {
        frm.set_value(
            "difference",
            flt(frm.doc.machine_total) - flt(frm.doc.system_total)
        );
    },
});
