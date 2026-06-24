import frappe


@frappe.whitelist()
def get_current_open_shift():
    fields = ["name", "owner", "creation"]

    meta = frappe.get_meta("Pharmacy Shift Closing")

    for fieldname in ["cashier", "status", "start_time", "end_time"]:
        if meta.has_field(fieldname):
            fields.append(fieldname)

    rows = frappe.get_all(
        "Pharmacy Shift Closing",
        filters={"docstatus": 0},
        fields=fields,
        order_by="creation desc",
        limit_page_length=50,
    )

    open_rows = []

    for row in rows:
        if row.get("status") == "Closed":
            continue

        if row.get("end_time"):
            continue

        open_rows.append(row)

    if not open_rows:
        return None

    current_user = frappe.session.user

    for row in open_rows:
        if row.get("cashier") == current_user or row.get("owner") == current_user:
            return row

    return open_rows[0]


def _update_doctype_autoname(doctype_name, autoname):
    doc = frappe.get_doc("DocType", doctype_name)
    doc.autoname = autoname
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def _update_server_script(name, script):
    doc = frappe.get_doc("Server Script", name)
    doc.script = script
    doc.disabled = 0
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def _update_client_script(name, script):
    doc = frappe.get_doc("Client Script", name)
    doc.script = script
    doc.enabled = 1
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def install():
    _update_doctype_autoname(
        "Driver Shortage",
        "format:DSH-{YYYY}-{#####}",
    )

    _update_doctype_autoname(
        "Employee Cash Advance",
        "format:ECA-{YYYY}-{#####}",
    )

    _update_server_script(
        "Driver Shortage - Before Submit",
        '# Server Script\n# Script Type: DocType Event\n# Reference DocType: Driver Shortage\n# Event: Before Submit\n\nexpected = frappe.utils.flt(doc.expected_amount)\nhanded = frappe.utils.flt(doc.handed_over_amount)\nrecovered = frappe.utils.flt(doc.recovered_amount)\ninstallments = frappe.utils.cint(doc.number_of_installments or 1)\n\nif not doc.company:\n    frappe.throw("Company is required.")\n\nif not doc.employee:\n    frappe.throw("Employee is required.")\n\nif not doc.shift_reference:\n    frappe.throw("Shift Reference is required.")\n\nshift_row = frappe.db.get_value(\n    "Pharmacy Shift Closing",\n    doc.shift_reference,\n    ["docstatus", "status", "end_time"],\n    as_dict=True,\n)\n\nif not shift_row:\n    frappe.throw("Shift Reference was not found.")\n\nif shift_row.docstatus != 0:\n    frappe.throw("Shift Reference must be the currently open shift.")\n\nif shift_row.status == "Closed" or shift_row.end_time:\n    frappe.throw("The selected shift is already closed.")\n\nif not doc.delivery_settlement:\n    frappe.throw("Delivery Settlement is required.")\n\nsettlement = frappe.get_doc("Delivery Settlement", doc.delivery_settlement)\n\nif settlement.docstatus == 2:\n    frappe.throw("The selected Delivery Settlement is cancelled.")\n\nif settlement.delivery_boy and settlement.delivery_boy != doc.employee:\n    frappe.throw(\n        "Employee does not match the delivery boy on the selected settlement."\n    )\n\nif settlement.shift_reference and settlement.shift_reference != doc.shift_reference:\n    frappe.throw(\n        "Shift Reference does not match the selected Delivery Settlement."\n    )\n\nduplicate = frappe.db.exists(\n    "Driver Shortage",\n    {\n        "delivery_settlement": doc.delivery_settlement,\n        "docstatus": 1,\n        "name": ["!=", doc.name],\n    },\n)\n\nif duplicate:\n    frappe.throw(\n        "A submitted Driver Shortage already exists for this Delivery Settlement: "\n        + duplicate\n    )\n\nsettlement_expected = frappe.utils.flt(\n    settlement.total_expected\n    or settlement.total_collected_by_driver\n)\n\nsettlement_handed = frappe.utils.flt(settlement.total_handed_over)\n\nif settlement_expected > 0:\n    expected = settlement_expected\n\nhanded = settlement_handed\n\nshortage = frappe.utils.flt(expected - handed)\n\nif shortage <= 0:\n    frappe.throw(\n        "There is no shortage to record. The handed-over amount already covers "\n        "the expected amount."\n    )\n\nif recovered < 0:\n    frappe.throw("Recovered Amount cannot be negative.")\n\nif recovered > shortage:\n    frappe.throw("Recovered Amount cannot exceed Shortage Amount.")\n\noutstanding = frappe.utils.flt(shortage - recovered)\n\nif doc.recovery_method == "Waived":\n    frappe.throw(\n        "Waived shortages are not enabled yet because a shortage write-off "\n        "expense account has not been configured."\n    )\n\nif doc.recovery_method == "Multiple Installments":\n    if installments <= 0:\n        frappe.throw("Number of Installments must be greater than zero.")\n\n    installment_amount = frappe.utils.flt(outstanding / installments)\n    payroll_status = "Scheduled"\n\nelif doc.recovery_method == "Salary Deduction":\n    installments = 1\n    installment_amount = outstanding\n    payroll_status = "Scheduled"\n\nelse:\n    installments = 1\n    installment_amount = 0\n    payroll_status = "Not Applicable"\n\ndoc.expected_amount = expected\ndoc.handed_over_amount = handed\ndoc.shortage_amount = shortage\ndoc.recovered_amount = recovered\ndoc.outstanding_amount = outstanding\ndoc.number_of_installments = installments\ndoc.installment_amount = installment_amount\ndoc.payroll_status = payroll_status\ndoc.status = "Open"\ndoc.approved_by = frappe.session.user\ndoc.approved_at = frappe.utils.now()\n\nif not doc.delivery_transit_account:\n    doc.delivery_transit_account = "Delivery Cash In Transit - C"\n\nif not doc.employee_shortage_account:\n    doc.employee_shortage_account = "Employee Shortage - C"\n\nfor account in [\n    doc.delivery_transit_account,\n    doc.employee_shortage_account,\n]:\n    account_row = frappe.db.get_value(\n        "Account",\n        account,\n        ["company", "is_group", "disabled"],\n        as_dict=True,\n    )\n\n    if not account_row:\n        frappe.throw("Account not found: " + account)\n\n    if account_row.company != doc.company:\n        frappe.throw("Account belongs to another company: " + account)\n\n    if account_row.is_group:\n        frappe.throw("A group account cannot be used: " + account)\n\n    if account_row.disabled:\n        frappe.throw("Account is disabled: " + account)',
    )

    _update_server_script(
        "Employee Cash Advance - Before Submit",
        '# Server Script\n# Script Type: DocType Event\n# Reference DocType: Employee Cash Advance\n# Event: Before Submit\n\namount = frappe.utils.flt(doc.advance_amount)\nrecovered = frappe.utils.flt(doc.recovered_amount)\ninstallments = frappe.utils.cint(doc.number_of_installments or 1)\n\nif not doc.company:\n    frappe.throw("Company is required.")\n\nif not doc.employee:\n    frappe.throw("Employee is required.")\n\nif not doc.shift_reference:\n    frappe.throw("Shift Reference is required.")\n\nshift_row = frappe.db.get_value(\n    "Pharmacy Shift Closing",\n    doc.shift_reference,\n    ["docstatus", "status", "end_time"],\n    as_dict=True,\n)\n\nif not shift_row:\n    frappe.throw("Shift Reference was not found.")\n\nif shift_row.docstatus != 0:\n    frappe.throw("Shift Reference must be the currently open shift.")\n\nif shift_row.status == "Closed" or shift_row.end_time:\n    frappe.throw("The selected shift is already closed.")\n\nif amount <= 0:\n    frappe.throw("Advance Amount must be greater than zero.")\n\nif recovered < 0:\n    frappe.throw("Recovered Amount cannot be negative.")\n\nif recovered > amount:\n    frappe.throw("Recovered Amount cannot exceed Advance Amount.")\n\nemployee_company = frappe.db.get_value(\n    "Employee",\n    doc.employee,\n    "company",\n)\n\nif employee_company and employee_company != doc.company:\n    frappe.throw("Employee belongs to another company.")\n\noutstanding = frappe.utils.flt(amount - recovered)\n\nif doc.recovery_method == "Multiple Installments":\n    if installments <= 0:\n        frappe.throw("Number of Installments must be greater than zero.")\n\n    installment_amount = frappe.utils.flt(outstanding / installments)\n    payroll_status = "Scheduled"\n\nelif doc.recovery_method == "Salary Deduction":\n    installments = 1\n    installment_amount = outstanding\n    payroll_status = "Scheduled"\n\nelse:\n    installments = 1\n    installment_amount = 0\n    payroll_status = "Not Applicable"\n\ndoc.recovered_amount = recovered\ndoc.outstanding_amount = outstanding\ndoc.number_of_installments = installments\ndoc.installment_amount = installment_amount\ndoc.payroll_status = payroll_status\ndoc.status = "Pending Disbursement"\ndoc.approved_by = frappe.session.user\ndoc.approved_at = frappe.utils.now()\n\nif not doc.cash_account:\n    doc.cash_account = "Cashier Till - C"\n\nif not doc.employee_advance_account:\n    doc.employee_advance_account = "Employee Advances - C"\n\nfor account in [\n    doc.cash_account,\n    doc.employee_advance_account,\n]:\n    account_row = frappe.db.get_value(\n        "Account",\n        account,\n        ["company", "is_group", "disabled"],\n        as_dict=True,\n    )\n\n    if not account_row:\n        frappe.throw("Account not found: " + account)\n\n    if account_row.company != doc.company:\n        frappe.throw("Account belongs to another company: " + account)\n\n    if account_row.is_group:\n        frappe.throw("A group account cannot be used: " + account)\n\n    if account_row.disabled:\n        frappe.throw("Account is disabled: " + account)',
    )

    _update_client_script(
        "Driver Shortage - Client Script",
        'frappe.ui.form.on("Driver Shortage", {\n    async onload(frm) {\n        await set_current_open_shift(frm);\n        apply_open_shift_query(frm);\n    },\n\n    async refresh(frm) {\n        await set_current_open_shift(frm);\n        apply_open_shift_query(frm);\n\n        frm.set_query("employee", () => ({\n            filters: {\n                company: frm.doc.company || "Cure",\n                status: "Active",\n            },\n        }));\n\n        for (const fieldname of [\n            "delivery_transit_account",\n            "employee_shortage_account",\n        ]) {\n            frm.set_query(fieldname, () => ({\n                filters: {\n                    company: frm.doc.company || "Cure",\n                    is_group: 0,\n                    disabled: 0,\n                },\n            }));\n        }\n\n        calculate_driver_shortage(frm);\n    },\n\n    delivery_settlement(frm) {\n        if (!frm.doc.delivery_settlement) return;\n\n        frappe.db.get_value(\n            "Delivery Settlement",\n            frm.doc.delivery_settlement,\n            [\n                "delivery_boy",\n                "shift_reference",\n                "total_expected",\n                "total_collected_by_driver",\n                "total_handed_over",\n            ],\n        ).then(async ({ message }) => {\n            if (!message) return;\n\n            if (\n                message.shift_reference\n                && frm.doc.shift_reference\n                && message.shift_reference !== frm.doc.shift_reference\n            ) {\n                frappe.throw(\n                    __("The Delivery Settlement does not belong to the current open shift.")\n                );\n            }\n\n            const expected =\n                flt(message.total_expected)\n                || flt(message.total_collected_by_driver);\n\n            await frm.set_value("employee", message.delivery_boy || "");\n            await frm.set_value("expected_amount", expected);\n            await frm.set_value(\n                "handed_over_amount",\n                flt(message.total_handed_over),\n            );\n\n            calculate_driver_shortage(frm);\n        });\n    },\n\n    expected_amount: calculate_driver_shortage,\n    handed_over_amount: calculate_driver_shortage,\n    recovered_amount: calculate_driver_shortage,\n    recovery_method: calculate_driver_shortage,\n    number_of_installments: calculate_driver_shortage,\n});\n\nfunction calculate_driver_shortage(frm) {\n    const shortage = Math.max(\n        flt(frm.doc.expected_amount) - flt(frm.doc.handed_over_amount),\n        0,\n    );\n\n    const outstanding = Math.max(\n        shortage - flt(frm.doc.recovered_amount),\n        0,\n    );\n\n    let installments = cint(frm.doc.number_of_installments || 1);\n    if (installments < 1) installments = 1;\n\n    let installmentAmount = 0;\n\n    if (frm.doc.recovery_method === "Salary Deduction") {\n        installmentAmount = outstanding;\n    } else if (frm.doc.recovery_method === "Multiple Installments") {\n        installmentAmount = outstanding / installments;\n    }\n\n    frm.set_value("shortage_amount", shortage);\n    frm.set_value("outstanding_amount", outstanding);\n    frm.set_value("installment_amount", installmentAmount);\n}\n\nasync function set_current_open_shift(frm) {\n    if (!frm.is_new()) return;\n\n    const response = await frappe.call({\n        method: "pharma_erp.pharma_erp.fix_employee_financial_shift_naming.get_current_open_shift",\n    });\n\n    const shift = response.message;\n\n    if (!shift || !shift.name) {\n        await frm.set_value("shift_reference", "");\n        frappe.msgprint({\n            title: __("No Open Shift"),\n            message: __("There is no open Pharmacy Shift Closing document."),\n            indicator: "orange",\n        });\n        return;\n    }\n\n    await frm.set_value("shift_reference", shift.name);\n}\n\nfunction apply_open_shift_query(frm) {\n    const shiftName = frm.doc.shift_reference;\n\n    frm.set_query("shift_reference", () => {\n        if (shiftName) {\n            return {\n                filters: {\n                    name: shiftName,\n                    docstatus: 0,\n                },\n            };\n        }\n\n        return {\n            filters: {\n                docstatus: 0,\n                status: ["!=", "Closed"],\n            },\n        };\n    });\n\n    frm.set_df_property("shift_reference", "read_only", 1);\n}\n',
    )

    _update_client_script(
        "Employee Cash Advance - Client Script",
        'frappe.ui.form.on("Employee Cash Advance", {\n    async onload(frm) {\n        await set_current_open_shift(frm);\n        apply_open_shift_query(frm);\n    },\n\n    async refresh(frm) {\n        await set_current_open_shift(frm);\n        apply_open_shift_query(frm);\n\n        frm.set_query("employee", () => ({\n            filters: {\n                company: frm.doc.company || "Cure",\n                status: "Active",\n            },\n        }));\n\n        for (const fieldname of [\n            "cash_account",\n            "employee_advance_account",\n        ]) {\n            frm.set_query(fieldname, () => ({\n                filters: {\n                    company: frm.doc.company || "Cure",\n                    is_group: 0,\n                    disabled: 0,\n                },\n            }));\n        }\n\n        calculate_employee_advance(frm);\n    },\n\n    advance_amount: calculate_employee_advance,\n    recovered_amount: calculate_employee_advance,\n    recovery_method: calculate_employee_advance,\n    number_of_installments: calculate_employee_advance,\n});\n\nfunction calculate_employee_advance(frm) {\n    const outstanding = Math.max(\n        flt(frm.doc.advance_amount) - flt(frm.doc.recovered_amount),\n        0,\n    );\n\n    let installments = cint(frm.doc.number_of_installments || 1);\n    if (installments < 1) installments = 1;\n\n    let installmentAmount = 0;\n\n    if (frm.doc.recovery_method === "Salary Deduction") {\n        installmentAmount = outstanding;\n    } else if (frm.doc.recovery_method === "Multiple Installments") {\n        installmentAmount = outstanding / installments;\n    }\n\n    frm.set_value("outstanding_amount", outstanding);\n    frm.set_value("installment_amount", installmentAmount);\n}\n\nasync function set_current_open_shift(frm) {\n    if (!frm.is_new()) return;\n\n    const response = await frappe.call({\n        method: "pharma_erp.pharma_erp.fix_employee_financial_shift_naming.get_current_open_shift",\n    });\n\n    const shift = response.message;\n\n    if (!shift || !shift.name) {\n        await frm.set_value("shift_reference", "");\n        frappe.msgprint({\n            title: __("No Open Shift"),\n            message: __("There is no open Pharmacy Shift Closing document."),\n            indicator: "orange",\n        });\n        return;\n    }\n\n    await frm.set_value("shift_reference", shift.name);\n}\n\nfunction apply_open_shift_query(frm) {\n    const shiftName = frm.doc.shift_reference;\n\n    frm.set_query("shift_reference", () => {\n        if (shiftName) {\n            return {\n                filters: {\n                    name: shiftName,\n                    docstatus: 0,\n                },\n            };\n        }\n\n        return {\n            filters: {\n                docstatus: 0,\n                status: ["!=", "Closed"],\n            },\n        };\n    });\n\n    frm.set_df_property("shift_reference", "read_only", 1);\n}\n',
    )

    frappe.db.commit()
    frappe.clear_cache()

    print("Employee financial naming and current-shift fix installed.")
    return verify()


def verify():
    result = {
        "Driver Shortage autoname": frappe.db.get_value(
            "DocType",
            "Driver Shortage",
            "autoname",
        ),
        "Employee Cash Advance autoname": frappe.db.get_value(
            "DocType",
            "Employee Cash Advance",
            "autoname",
        ),
        "Current Open Shift": get_current_open_shift(),
    }

    print(result)
    return result
