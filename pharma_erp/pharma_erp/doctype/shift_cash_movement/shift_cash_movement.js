frappe.ui.form.on("Shift Cash Movement", {
    setup(frm) {
        frm.set_query("cash_drawer", () => ({
            filters: {
                company: frm.doc.company,
                enabled: 1,
            },
        }));
        frm.set_query("source_account", () => cash_movement_account_query(frm, "source"));
        frm.set_query("target_account", () => cash_movement_account_query(frm, "target"));
        frm.set_query("expense_account", () => ({
            filters: {
                company: frm.doc.company,
                root_type: "Expense",
                is_group: 0,
                disabled: 0,
            },
        }));
        frm.set_query("purchase_invoice", () => ({
            filters: {
                company: frm.doc.company,
                supplier: frm.doc.supplier,
                docstatus: 1,
                outstanding_amount: [">", 0],
            },
        }));
    },

    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.set_intro(
                __("Saving creates a pending request only. A different Treasury Manager must submit it before any accounting entry is posted."),
                "blue",
            );
        } else if (frm.doc.docstatus === 1 && frm.doc.journal_entry) {
            frm.set_intro(
                __("Posted through Journal Entry {0}.", [frm.doc.journal_entry]),
                "green",
            );
        }
    },

    movement_type(frm) {
        const direction = movement_direction(frm.doc.movement_type);
        if (direction) frm.set_value("direction", direction);
        sync_drawer_accounts(frm);
        if (frm.doc.movement_type !== "Supplier Payment") {
            frm.set_value("supplier", "");
            frm.set_value("purchase_invoice", "");
        }
        if (frm.doc.movement_type !== "Employee Advance") {
            frm.set_value("employee", "");
        }
    },

    cash_drawer(frm) {
        sync_drawer_accounts(frm);
    },

    supplier(frm) {
        frm.set_value("purchase_invoice", "");
    },
});


function movement_direction(movementType) {
    const incoming = [
        "Opening Float",
        "Till Refill",
        "Under Review Driver Cash Deposit",
        "Other Cash Receipt",
    ];
    const outgoing = [
        "Return Opening Float",
        "Cash Sales Deposit",
        "Unused Till Refill Return",
        "Other Cash Return",
        "Transfer to Main Safe",
        "Supplier Payment",
        "Operating Expense",
        "Employee Advance",
        "Other Cash Payment",
    ];
    if (incoming.includes(movementType)) return "In";
    if (outgoing.includes(movementType)) return "Out";
    return "";
}


async function sync_drawer_accounts(frm) {
    if (!frm.doc.cash_drawer) return;
    const response = await frappe.db.get_value(
        "Cash Drawer",
        frm.doc.cash_drawer,
        ["company", "cash_account", "current_active_shift"],
    );
    const drawer = response.message || {};
    if (drawer.company && !frm.doc.company) await frm.set_value("company", drawer.company);
    if (drawer.current_active_shift) await frm.set_value("shift_reference", drawer.current_active_shift);
    if (!drawer.cash_account) return;
    if (frm.doc.direction === "In") await frm.set_value("target_account", drawer.cash_account);
    if (frm.doc.direction === "Out") await frm.set_value("source_account", drawer.cash_account);
}


function cash_movement_account_query(frm, side) {
    const filters = {
        company: frm.doc.company,
        is_group: 0,
        disabled: 0,
    };
    const drawerSide = frm.doc.direction === "In" ? "target" : "source";
    if (side === drawerSide) {
        filters.root_type = "Asset";
        filters.account_type = "Cash";
        return { filters };
    }

    if ([
        "Opening Float",
        "Till Refill",
        "Return Opening Float",
        "Cash Sales Deposit",
        "Unused Till Refill Return",
        "Other Cash Return",
        "Under Review Driver Cash Deposit",
        "Transfer to Main Safe",
    ].includes(frm.doc.movement_type)) {
        filters.root_type = "Asset";
        filters.account_type = ["in", ["Cash", "Bank"]];
    } else if (frm.doc.movement_type === "Operating Expense") {
        filters.root_type = "Expense";
    } else if (frm.doc.movement_type === "Supplier Payment") {
        filters.root_type = "Liability";
        filters.account_type = "Payable";
    } else if (frm.doc.movement_type === "Employee Advance") {
        filters.root_type = "Asset";
        filters.account_type = ["not in", ["Cash", "Bank"]];
    }
    return { filters };
}
