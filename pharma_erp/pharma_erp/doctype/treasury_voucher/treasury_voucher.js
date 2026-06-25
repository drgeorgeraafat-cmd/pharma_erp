frappe.ui.form.on("Treasury Voucher", {
    setup(frm) {
        frm.set_query("category", () => ({
            filters: {
                company: frm.doc.company,
                voucher_type: frm.doc.voucher_type,
                enabled: 1,
            },
        }));
        frm.set_query("cash_bank_account", () => ({
            filters: {
                company: frm.doc.company,
                root_type: "Asset",
                account_type: ["in", ["Cash", "Bank"]],
                is_group: 0,
                disabled: 0,
            },
        }));
        frm.set_query("counter_account", () => counter_account_query(frm));
        frm.set_query("cost_center", () => ({
            filters: {
                company: frm.doc.company,
                is_group: 0,
                disabled: 0,
            },
        }));
    },

    refresh(frm) {
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
        load_category_configuration(frm, false);
    },

    company(frm) {
        frm.set_value("category", "");
        frm.set_value("counter_account", "");
        frm._treasury_category_configuration = null;
    },

    voucher_type(frm) {
        frm.set_value("category", "");
        frm.set_value("counter_account", "");
        frm._treasury_category_configuration = null;
    },

    category(frm) {
        load_category_configuration(frm, true);
    },
});


function counter_account_query(frm) {
    const configuration = frm._treasury_category_configuration || {};
    const allowed = configuration.allowed_accounts || [];
    const filters = {
        company: frm.doc.company,
        root_type: frm.doc.voucher_type === "General Receipt" ? "Income" : "Expense",
        is_group: 0,
        disabled: 0,
    };
    if (allowed.length) {
        filters.name = ["in", allowed];
    } else if (frm.doc.category) {
        filters.name = ["in", ["__NO_ALLOWED_ACCOUNT__"]];
    }
    return { filters };
}


async function load_category_configuration(frm, set_default) {
    if (!frm.doc.category || !frm.doc.company || !frm.doc.voucher_type) {
        frm._treasury_category_configuration = null;
        return;
    }
    const response = await frappe.call({
        method: "pharma_erp.pharma_erp.doctype.treasury_voucher.treasury_voucher.get_category_configuration_for_form",
        args: {
            category: frm.doc.category,
            company: frm.doc.company,
            voucher_type: frm.doc.voucher_type,
        },
    });
    const configuration = response.message || {};
    frm._treasury_category_configuration = configuration;
    const allowed = configuration.allowed_accounts || [];
    if (set_default && configuration.default_account && !allowed.includes(frm.doc.counter_account)) {
        await frm.set_value("counter_account", configuration.default_account);
    } else if (frm.doc.counter_account && !allowed.includes(frm.doc.counter_account)) {
        await frm.set_value("counter_account", "");
    }
}
