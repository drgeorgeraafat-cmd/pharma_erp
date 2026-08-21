frappe.ui.form.on("Customer Product Request Item", {
    requested_qty(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (flt(row.requested_qty) <= 0) {
            frappe.model.set_value(cdt, cdn, "requested_qty", 1);
        }
    }
});

frappe.ui.form.on("Customer Product Request", {
    refresh(frm) {
        if (!frm.is_new() && ["Waiting for Stock", "Partially Available", "Available for Contact", "Contact Attempted", "Still Interested"].includes(frm.doc.status)) {
            frm.add_custom_button(__("Evaluate Availability"), async () => {
                await frappe.call({method: "pharma_erp.pharma_erp.customer_product_request_service.evaluate_customer_product_requests", args: {item_codes: JSON.stringify((frm.doc.items || []).map(row => row.item_code))}, freeze: true});
                frm.reload_doc();
            });
        }
    }
});
