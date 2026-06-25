frappe.ui.form.on("Treasury Voucher Category", {
    setup(frm) {
        frm.set_query("default_account", () => category_account_query(frm));
        frm.set_query("account", "allowed_accounts", () => category_account_query(frm));
    },

    company(frm) {
        clear_category_accounts(frm);
    },

    voucher_type(frm) {
        clear_category_accounts(frm);
    },

    default_account(frm) {
        const account = frm.doc.default_account;
        if (!account) return;
        const exists = (frm.doc.allowed_accounts || []).some((row) => row.account === account);
        if (!exists) {
            const row = frm.add_child("allowed_accounts");
            row.account = account;
            frm.refresh_field("allowed_accounts");
        }
    },
});


function category_account_query(frm) {
    return {
        filters: {
            company: frm.doc.company,
            root_type: frm.doc.voucher_type === "General Receipt" ? "Income" : "Expense",
            is_group: 0,
            disabled: 0,
        },
    };
}


function clear_category_accounts(frm) {
    frm.set_value("default_account", "");
    frm.clear_table("allowed_accounts");
    frm.refresh_field("allowed_accounts");
}
