frappe.ui.form.on("Driver Shortage", {
    async onload(frm) {
        await set_current_open_shift(frm);
        apply_open_shift_query(frm);
    },

    async refresh(frm) {
        await set_current_open_shift(frm);
        apply_open_shift_query(frm);

        frm.set_query("employee", () => ({
            filters: {
                company: frm.doc.company || "Cure",
                status: "Active",
            },
        }));

        for (const fieldname of [
            "delivery_transit_account",
            "employee_shortage_account",
        ]) {
            frm.set_query(fieldname, () => ({
                filters: {
                    company: frm.doc.company || "Cure",
                    is_group: 0,
                    disabled: 0,
                },
            }));
        }

        calculate_driver_shortage(frm);
    },

    delivery_settlement(frm) {
        if (!frm.doc.delivery_settlement) return;

        frappe.db.get_value(
            "Delivery Settlement",
            frm.doc.delivery_settlement,
            [
                "delivery_boy",
                "shift_reference",
                "total_expected",
                "total_collected_by_driver",
                "total_handed_over",
            ],
        ).then(async ({ message }) => {
            if (!message) return;

            if (
                message.shift_reference
                && frm.doc.shift_reference
                && message.shift_reference !== frm.doc.shift_reference
            ) {
                frappe.throw(
                    __("The Delivery Settlement does not belong to the current open shift.")
                );
            }

            const expected =
                flt(message.total_expected)
                || flt(message.total_collected_by_driver);

            await frm.set_value("employee", message.delivery_boy || "");
            await frm.set_value("expected_amount", expected);
            await frm.set_value(
                "handed_over_amount",
                flt(message.total_handed_over),
            );

            calculate_driver_shortage(frm);
        });
    },

    expected_amount: calculate_driver_shortage,
    handed_over_amount: calculate_driver_shortage,
    recovered_amount: calculate_driver_shortage,
    recovery_method: calculate_driver_shortage,
    number_of_installments: calculate_driver_shortage,
});

function calculate_driver_shortage(frm) {
    const shortage = Math.max(
        flt(frm.doc.expected_amount) - flt(frm.doc.handed_over_amount),
        0,
    );

    const outstanding = Math.max(
        shortage - flt(frm.doc.recovered_amount),
        0,
    );

    let installments = cint(frm.doc.number_of_installments || 1);
    if (installments < 1) installments = 1;

    let installmentAmount = 0;

    if (frm.doc.recovery_method === "Salary Deduction") {
        installmentAmount = outstanding;
    } else if (frm.doc.recovery_method === "Multiple Installments") {
        installmentAmount = outstanding / installments;
    }

    frm.set_value("shortage_amount", shortage);
    frm.set_value("outstanding_amount", outstanding);
    frm.set_value("installment_amount", installmentAmount);
}

async function set_current_open_shift(frm) {
    if (!frm.is_new()) return;

    const response = await frappe.call({
        method: "pharma_erp.pharma_erp.employee_financial.get_current_open_shift",
    });

    const shift = response.message;

    if (!shift || !shift.name) {
        await frm.set_value("shift_reference", "");
        frappe.msgprint({
            title: __("No Open Shift"),
            message: __("There is no open Pharmacy Shift Closing document."),
            indicator: "orange",
        });
        return;
    }

    await frm.set_value("shift_reference", shift.name);
}

function apply_open_shift_query(frm) {
    const shiftName = frm.doc.shift_reference;

    frm.set_query("shift_reference", () => {
        if (shiftName) {
            return {
                filters: {
                    name: shiftName,
                    docstatus: 0,
                },
            };
        }

        return {
            filters: {
                docstatus: 0,
                status: ["!=", "Closed"],
            },
        };
    });

    frm.set_df_property("shift_reference", "read_only", 1);
}
