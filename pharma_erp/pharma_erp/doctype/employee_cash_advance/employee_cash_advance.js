frappe.ui.form.on("Employee Cash Advance", {
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
            "cash_account",
            "employee_advance_account",
        ]) {
            frm.set_query(fieldname, () => ({
                filters: {
                    company: frm.doc.company || "Cure",
                    is_group: 0,
                    disabled: 0,
                },
            }));
        }

        calculate_employee_advance(frm);
    },

    advance_amount: calculate_employee_advance,
    recovered_amount: calculate_employee_advance,
    recovery_method: calculate_employee_advance,
    number_of_installments: calculate_employee_advance,
});

function calculate_employee_advance(frm) {
    const outstanding = Math.max(
        flt(frm.doc.advance_amount) - flt(frm.doc.recovered_amount),
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
