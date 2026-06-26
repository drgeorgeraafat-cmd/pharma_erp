// Copyright (c) 2026, ZeePharaoh and contributors
// For license information, please see license.txt

frappe.ui.form.on("Pharmacy Purchase Settings", {
    refresh(frm) {
        frm.set_intro(
            __("Controls pharmacy purchase invoices, supplier bills, batches, and retail-price updates."),
            "blue"
        );
    },
});
