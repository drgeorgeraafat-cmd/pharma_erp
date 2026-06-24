frappe.ui.form.on("Card Bank Settlement", {
    async refresh(frm) {
        if (frm.doc.docstatus !== 0) return;

        await set_card_bank_defaults(frm);

        frm.add_custom_button(__("Load Awaiting Batches"), async () => {
            await set_card_bank_defaults(frm);

            if (!frm.doc.clearing_account || !frm.doc.destination_bank_account) {
                frappe.msgprint(__("Select Destination Bank Account first."));
                return;
            }

            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.payment_card_management.get_awaiting_card_batches",
                args: {
                    clearing_account: frm.doc.clearing_account,
                    destination_bank_account: frm.doc.destination_bank_account,
                },
                freeze: true,
            });

            frm.clear_table("allocations");

            (response.message || []).forEach((batch) => {
                const row = frm.add_child("allocations");
                row.card_settlement_batch = batch.name;
                row.pos_terminal = batch.pos_terminal;
                row.batch_number = batch.batch_number;
                row.available_amount = batch.outstanding_amount;
                row.allocated_amount = batch.outstanding_amount;

                if (!frm.doc.fee_account && batch.fee_account) {
                    frm.set_value("fee_account", batch.fee_account);
                }
            });

            frm.refresh_field("allocations");
            calculate_card_bank_totals(frm);
        });
    },

    destination_bank_account(frm) {
        set_card_bank_defaults(frm);
    },

    clearing_account(frm) {
        set_card_bank_defaults(frm);
    },

    fee_amount(frm) {
        calculate_card_bank_totals(frm);
    },
});

frappe.ui.form.on("Card Bank Settlement Allocation", {
    allocated_amount(frm) {
        calculate_card_bank_totals(frm);
    },

    allocations_remove(frm) {
        calculate_card_bank_totals(frm);
    },
});

async function set_card_bank_defaults(frm) {
    const response = await frappe.call({
        method: "pharma_erp.pharma_erp.payment_card_management.get_card_bank_defaults",
        args: {
            destination_bank_account: frm.doc.destination_bank_account || "",
            clearing_account: frm.doc.clearing_account || "",
        },
    });

    const values = response.message || {};

    if (!frm.doc.destination_bank_account && values.destination_bank_account) {
        await frm.set_value("destination_bank_account", values.destination_bank_account);
    }

    if (!frm.doc.clearing_account && values.clearing_account) {
        await frm.set_value("clearing_account", values.clearing_account);
    }

    if (!frm.doc.fee_account && values.fee_account) {
        await frm.set_value("fee_account", values.fee_account);
    }
}

function calculate_card_bank_totals(frm) {
    let gross = 0;

    (frm.doc.allocations || []).forEach((row) => {
        gross += flt(row.allocated_amount);
    });

    frm.set_value("gross_amount", gross);
    frm.set_value("net_amount", gross - flt(frm.doc.fee_amount));
}
