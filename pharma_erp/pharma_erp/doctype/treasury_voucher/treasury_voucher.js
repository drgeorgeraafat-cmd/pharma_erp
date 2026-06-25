frappe.ui.form.on("Treasury Voucher", {
    setup(frm) {
        frm.set_query("cash_bank_account", () => ({
            filters: {
                company: frm.doc.company,
                root_type: "Asset",
                account_type: ["in", ["Cash", "Bank"]],
                is_group: 0,
                disabled: 0,
            },
        }));
        frm.set_query("counter_account", () => ({
            filters: {
                company: frm.doc.company,
                root_type: frm.doc.voucher_type === "General Receipt" ? "Income" : "Expense",
                is_group: 0,
                disabled: 0,
            },
        }));
        frm.set_query("cost_center", () => ({
            filters: {
                company: frm.doc.company,
                is_group: 0,
                disabled: 0,
            },
        }));
    },

    refresh(frm) {
        update_category_options(frm);
        if (frm.doc.docstatus === 0) {
            frm.set_intro(
                __("Saving creates a pending Treasury request only. A different Treasury Manager must submit it before any accounting entry is posted."),
                "blue",
            );
        } else if (frm.doc.docstatus === 1 && frm.doc.journal_entry) {
            frm.set_intro(
                __("Posted through Journal Entry {0}.", [frm.doc.journal_entry]),
                "green",
            );
        }
    },

    voucher_type(frm) {
        update_category_options(frm);
        frm.set_value("counter_account", "");
    },
});


function update_category_options(frm) {
    const expense = [
        "Rent",
        "Utilities",
        "Maintenance",
        "Office Supplies",
        "Transportation",
        "Administrative Expense",
        "Marketing Expense",
        "Miscellaneous Expense",
        "Other Expense",
    ];
    const receipt = [
        "Other Income",
        "Cashback / Rebate",
        "Insurance Reimbursement",
        "Refund / Compensation",
        "Miscellaneous Receipt",
        "Other Receipt",
    ];
    const options = frm.doc.voucher_type === "General Receipt" ? receipt : expense;
    frm.set_df_property("category", "options", options.join("\n"));
    if (!options.includes(frm.doc.category)) {
        frm.set_value("category", options[0]);
    }
}
