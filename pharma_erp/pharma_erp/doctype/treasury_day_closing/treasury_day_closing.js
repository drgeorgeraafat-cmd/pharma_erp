frappe.ui.form.on("Treasury Day Closing", {
    refresh(frm) {
        frm.set_query("company", () => ({ filters: { is_group: 0 } }));

        frm.add_custom_button(__("تقرير الخزينة اليومي"), () => {
            frappe.set_route("query-report", "Treasury Daily Review", {
                company: frm.doc.company,
                from_date: frm.doc.closing_date,
                to_date: frm.doc.closing_date,
            });
        }, __("التقارير"));

        if (frm.doc.docstatus === 0 && !frm.is_new()) {
            frm.add_custom_button(__("تحديث لقطة الإقفال"), async () => {
                await frappe.call({
                    method: "pharma_erp.pharma_erp.doctype.treasury_day_closing.treasury_day_closing.refresh_day_closing_snapshot",
                    args: { name: frm.doc.name },
                    freeze: true,
                    freeze_message: __("جاري تحديث بيانات الإقفال..."),
                });
                await frm.reload_doc();
            });
        }
    },
});

frappe.ui.form.on("Treasury Day Closing Account", {
    actual_closing(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        row.difference = flt(row.actual_closing) - flt(row.expected_closing);
        row.review_status = Math.abs(row.difference) <= 0.005
            ? "Matched"
            : (row.difference_reason ? "Explained" : "Unresolved");
        frm.refresh_field("accounts");
    },
    difference_reason(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        row.review_status = Math.abs(flt(row.difference)) <= 0.005
            ? "Matched"
            : (row.difference_reason ? "Explained" : "Unresolved");
        frm.refresh_field("accounts");
    },
});
