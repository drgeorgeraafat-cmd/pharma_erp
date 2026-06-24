import frappe

SERVER_SCRIPTS = [{'name': 'Driver Shortage - Before Submit',
  'reference_doctype': 'Driver Shortage',
  'doctype_event': 'Before Submit',
  'script': '# Server Script\n'
            '# Script Type: DocType Event\n'
            '# Reference DocType: Driver Shortage\n'
            '# Event: Before Submit\n'
            '\n'
            'expected = frappe.utils.flt(doc.expected_amount)\n'
            'handed = frappe.utils.flt(doc.handed_over_amount)\n'
            'recovered = frappe.utils.flt(doc.recovered_amount)\n'
            'installments = frappe.utils.cint(doc.number_of_installments or 1)\n'
            '\n'
            'if not doc.company:\n'
            '    frappe.throw("Company is required.")\n'
            'if not doc.employee:\n'
            '    frappe.throw("Employee is required.")\n'
            'if not doc.shift_reference:\n'
            '    frappe.throw("Shift Reference is required.")\n'
            'if not doc.delivery_settlement:\n'
            '    frappe.throw("Delivery Settlement is required.")\n'
            '\n'
            'settlement = frappe.get_doc("Delivery Settlement", doc.delivery_settlement)\n'
            'if settlement.docstatus == 2:\n'
            '    frappe.throw("The selected Delivery Settlement is cancelled.")\n'
            'if settlement.delivery_boy and settlement.delivery_boy != doc.employee:\n'
            '    frappe.throw("Employee does not match the delivery boy on the selected settlement.")\n'
            'if settlement.shift_reference and settlement.shift_reference != doc.shift_reference:\n'
            '    frappe.throw("Shift Reference does not match the selected Delivery Settlement.")\n'
            '\n'
            'duplicate = frappe.db.exists(\n'
            '    "Driver Shortage",\n'
            '    {\n'
            '        "delivery_settlement": doc.delivery_settlement,\n'
            '        "docstatus": 1,\n'
            '        "name": ["!=", doc.name],\n'
            '    },\n'
            ')\n'
            'if duplicate:\n'
            '    frappe.throw("A submitted Driver Shortage already exists for this Delivery Settlement: " + '
            'duplicate)\n'
            '\n'
            'settlement_expected = frappe.utils.flt(settlement.total_expected or '
            'settlement.total_collected_by_driver)\n'
            'settlement_handed = frappe.utils.flt(settlement.total_handed_over)\n'
            'if settlement_expected > 0:\n'
            '    expected = settlement_expected\n'
            'handed = settlement_handed\n'
            '\n'
            'shortage = frappe.utils.flt(expected - handed)\n'
            'if shortage <= 0:\n'
            '    frappe.throw("There is no shortage to record. The handed-over amount already covers the '
            'expected amount.")\n'
            'if recovered < 0:\n'
            '    frappe.throw("Recovered Amount cannot be negative.")\n'
            'if recovered > shortage:\n'
            '    frappe.throw("Recovered Amount cannot exceed Shortage Amount.")\n'
            '\n'
            'outstanding = frappe.utils.flt(shortage - recovered)\n'
            'if doc.recovery_method == "Waived":\n'
            '    frappe.throw("Waived shortages are not enabled yet because a shortage write-off expense '
            'account has not been configured.")\n'
            '\n'
            'if doc.recovery_method == "Multiple Installments":\n'
            '    if installments <= 0:\n'
            '        frappe.throw("Number of Installments must be greater than zero.")\n'
            '    installment_amount = frappe.utils.flt(outstanding / installments)\n'
            '    payroll_status = "Scheduled"\n'
            'elif doc.recovery_method == "Salary Deduction":\n'
            '    installments = 1\n'
            '    installment_amount = outstanding\n'
            '    payroll_status = "Scheduled"\n'
            'else:\n'
            '    installments = 1\n'
            '    installment_amount = 0\n'
            '    payroll_status = "Not Applicable"\n'
            '\n'
            'doc.expected_amount = expected\n'
            'doc.handed_over_amount = handed\n'
            'doc.shortage_amount = shortage\n'
            'doc.recovered_amount = recovered\n'
            'doc.outstanding_amount = outstanding\n'
            'doc.number_of_installments = installments\n'
            'doc.installment_amount = installment_amount\n'
            'doc.payroll_status = payroll_status\n'
            'doc.status = "Open"\n'
            'doc.approved_by = frappe.session.user\n'
            'doc.approved_at = frappe.utils.now()\n'
            '\n'
            'if not doc.delivery_transit_account:\n'
            '    doc.delivery_transit_account = "Delivery Cash In Transit - C"\n'
            'if not doc.employee_shortage_account:\n'
            '    doc.employee_shortage_account = "Employee Shortage - C"\n'
            '\n'
            'for account in [doc.delivery_transit_account, doc.employee_shortage_account]:\n'
            '    account_row = frappe.db.get_value(\n'
            '        "Account", account, ["company", "is_group", "disabled"], as_dict=True\n'
            '    )\n'
            '    if not account_row:\n'
            '        frappe.throw("Account not found: " + account)\n'
            '    if account_row.company != doc.company:\n'
            '        frappe.throw("Account belongs to another company: " + account)\n'
            '    if account_row.is_group:\n'
            '        frappe.throw("A group account cannot be used: " + account)\n'
            '    if account_row.disabled:\n'
            '        frappe.throw("Account is disabled: " + account)\n'},
 {'name': 'Driver Shortage - After Submit',
  'reference_doctype': 'Driver Shortage',
  'doctype_event': 'After Submit',
  'script': '# Server Script\n'
            '# Script Type: DocType Event\n'
            '# Reference DocType: Driver Shortage\n'
            '# Event: After Submit\n'
            '\n'
            'if doc.journal_entry:\n'
            '    existing_status = frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus")\n'
            '    if existing_status == 1:\n'
            '        frappe.throw("A submitted Journal Entry is already linked: " + doc.journal_entry)\n'
            '\n'
            'amount = frappe.utils.flt(doc.shortage_amount)\n'
            'if amount <= 0:\n'
            '    frappe.throw("Shortage Amount must be greater than zero.")\n'
            '\n'
            'journal = frappe.new_doc("Journal Entry")\n'
            'journal.voucher_type = "Journal Entry"\n'
            'journal.company = doc.company\n'
            'journal.posting_date = doc.shortage_date or frappe.utils.today()\n'
            'journal.user_remark = (\n'
            '    "Driver shortage " + doc.name + " for employee " + doc.employee\n'
            '    + ", settlement " + doc.delivery_settlement\n'
            ')\n'
            '\n'
            'journal.append("accounts", {\n'
            '    "account": doc.employee_shortage_account,\n'
            '    "party_type": "Employee",\n'
            '    "party": doc.employee,\n'
            '    "debit_in_account_currency": amount,\n'
            '    "credit_in_account_currency": 0,\n'
            '})\n'
            'journal.append("accounts", {\n'
            '    "account": doc.delivery_transit_account,\n'
            '    "debit_in_account_currency": 0,\n'
            '    "credit_in_account_currency": amount,\n'
            '})\n'
            '\n'
            'journal.flags.ignore_permissions = True\n'
            'journal.insert(ignore_permissions=True)\n'
            'journal.flags.ignore_permissions = True\n'
            'journal.submit()\n'
            '\n'
            'frappe.db.set_value(\n'
            '    "Driver Shortage", doc.name, "journal_entry", journal.name, update_modified=False\n'
            ')\n'
            '\n'
            'frappe.db.set_value(\n'
            '    "Delivery Settlement",\n'
            '    doc.delivery_settlement,\n'
            '    {\n'
            '        "remaining_with_driver": 0,\n'
            '        "final_difference": -abs(amount),\n'
            '        "difference_reason": doc.reason,\n'
            '        "settlement_status": "Settled",\n'
            '        "settled_at": frappe.utils.now(),\n'
            '        "settled_by": frappe.session.user,\n'
            '    },\n'
            '    update_modified=False,\n'
            ')\n'},
 {'name': 'Driver Shortage - Before Cancel',
  'reference_doctype': 'Driver Shortage',
  'doctype_event': 'Before Cancel',
  'script': '# Server Script\n'
            '# Script Type: DocType Event\n'
            '# Reference DocType: Driver Shortage\n'
            '# Event: Before Cancel\n'
            '\n'
            'if frappe.utils.flt(doc.recovered_amount) > 0:\n'
            '    frappe.throw("This Driver Shortage cannot be cancelled because recovery has already '
            'started.")\n'
            'if doc.payroll_status in ["Partially Deducted", "Fully Deducted"]:\n'
            '    frappe.throw("This Driver Shortage cannot be cancelled because payroll deductions exist.")\n'
            '\n'
            'if doc.journal_entry:\n'
            '    journal = frappe.get_doc("Journal Entry", doc.journal_entry)\n'
            '    if journal.docstatus == 1:\n'
            '        journal.flags.ignore_permissions = True\n'
            '        journal.cancel()\n'
            '\n'
            'if doc.delivery_settlement:\n'
            '    settlement = frappe.get_doc("Delivery Settlement", doc.delivery_settlement)\n'
            '    remaining = max(\n'
            '        frappe.utils.flt(settlement.total_expected)\n'
            '        - frappe.utils.flt(settlement.total_handed_over),\n'
            '        0,\n'
            '    )\n'
            '    frappe.db.set_value(\n'
            '        "Delivery Settlement",\n'
            '        settlement.name,\n'
            '        {\n'
            '            "remaining_with_driver": remaining,\n'
            '            "final_difference": 0,\n'
            '            "difference_reason": "",\n'
            '            "settlement_status": "Awaiting Final Settlement",\n'
            '            "settled_at": None,\n'
            '            "settled_by": None,\n'
            '        },\n'
            '        update_modified=False,\n'
            '    )\n'},
 {'name': 'Employee Cash Advance - Before Submit',
  'reference_doctype': 'Employee Cash Advance',
  'doctype_event': 'Before Submit',
  'script': '# Server Script\n'
            '# Script Type: DocType Event\n'
            '# Reference DocType: Employee Cash Advance\n'
            '# Event: Before Submit\n'
            '\n'
            'amount = frappe.utils.flt(doc.advance_amount)\n'
            'recovered = frappe.utils.flt(doc.recovered_amount)\n'
            'installments = frappe.utils.cint(doc.number_of_installments or 1)\n'
            '\n'
            'if not doc.company:\n'
            '    frappe.throw("Company is required.")\n'
            'if not doc.employee:\n'
            '    frappe.throw("Employee is required.")\n'
            'if not doc.shift_reference:\n'
            '    frappe.throw("Shift Reference is required.")\n'
            'if amount <= 0:\n'
            '    frappe.throw("Advance Amount must be greater than zero.")\n'
            'if recovered < 0:\n'
            '    frappe.throw("Recovered Amount cannot be negative.")\n'
            'if recovered > amount:\n'
            '    frappe.throw("Recovered Amount cannot exceed Advance Amount.")\n'
            '\n'
            'employee_company = frappe.db.get_value("Employee", doc.employee, "company")\n'
            'if employee_company and employee_company != doc.company:\n'
            '    frappe.throw("Employee belongs to another company.")\n'
            '\n'
            'outstanding = frappe.utils.flt(amount - recovered)\n'
            'if doc.recovery_method == "Multiple Installments":\n'
            '    if installments <= 0:\n'
            '        frappe.throw("Number of Installments must be greater than zero.")\n'
            '    installment_amount = frappe.utils.flt(outstanding / installments)\n'
            '    payroll_status = "Scheduled"\n'
            'elif doc.recovery_method == "Salary Deduction":\n'
            '    installments = 1\n'
            '    installment_amount = outstanding\n'
            '    payroll_status = "Scheduled"\n'
            'else:\n'
            '    installments = 1\n'
            '    installment_amount = 0\n'
            '    payroll_status = "Not Applicable"\n'
            '\n'
            'doc.recovered_amount = recovered\n'
            'doc.outstanding_amount = outstanding\n'
            'doc.number_of_installments = installments\n'
            'doc.installment_amount = installment_amount\n'
            'doc.payroll_status = payroll_status\n'
            'doc.status = "Pending Disbursement"\n'
            'doc.approved_by = frappe.session.user\n'
            'doc.approved_at = frappe.utils.now()\n'
            '\n'
            'if not doc.cash_account:\n'
            '    doc.cash_account = "Cashier Till - C"\n'
            'if not doc.employee_advance_account:\n'
            '    doc.employee_advance_account = "Employee Advances - C"\n'
            '\n'
            'for account in [doc.cash_account, doc.employee_advance_account]:\n'
            '    account_row = frappe.db.get_value(\n'
            '        "Account", account, ["company", "is_group", "disabled"], as_dict=True\n'
            '    )\n'
            '    if not account_row:\n'
            '        frappe.throw("Account not found: " + account)\n'
            '    if account_row.company != doc.company:\n'
            '        frappe.throw("Account belongs to another company: " + account)\n'
            '    if account_row.is_group:\n'
            '        frappe.throw("A group account cannot be used: " + account)\n'
            '    if account_row.disabled:\n'
            '        frappe.throw("Account is disabled: " + account)\n'},
 {'name': 'Employee Cash Advance - After Submit',
  'reference_doctype': 'Employee Cash Advance',
  'doctype_event': 'After Submit',
  'script': '# Server Script\n'
            '# Script Type: DocType Event\n'
            '# Reference DocType: Employee Cash Advance\n'
            '# Event: After Submit\n'
            '\n'
            'if doc.journal_entry:\n'
            '    existing_status = frappe.db.get_value("Journal Entry", doc.journal_entry, "docstatus")\n'
            '    if existing_status == 1:\n'
            '        frappe.throw("A submitted Journal Entry is already linked: " + doc.journal_entry)\n'
            '\n'
            'amount = frappe.utils.flt(doc.advance_amount)\n'
            'if amount <= 0:\n'
            '    frappe.throw("Advance Amount must be greater than zero.")\n'
            '\n'
            'journal = frappe.new_doc("Journal Entry")\n'
            'journal.voucher_type = "Journal Entry"\n'
            'journal.company = doc.company\n'
            'journal.posting_date = doc.advance_date or frappe.utils.today()\n'
            'journal.user_remark = (\n'
            '    "Employee cash advance " + doc.name + " for employee " + doc.employee\n'
            '    + ", shift " + doc.shift_reference\n'
            ')\n'
            '\n'
            'journal.append("accounts", {\n'
            '    "account": doc.employee_advance_account,\n'
            '    "party_type": "Employee",\n'
            '    "party": doc.employee,\n'
            '    "debit_in_account_currency": amount,\n'
            '    "credit_in_account_currency": 0,\n'
            '})\n'
            'journal.append("accounts", {\n'
            '    "account": doc.cash_account,\n'
            '    "debit_in_account_currency": 0,\n'
            '    "credit_in_account_currency": amount,\n'
            '})\n'
            '\n'
            'journal.flags.ignore_permissions = True\n'
            'journal.insert(ignore_permissions=True)\n'
            'journal.flags.ignore_permissions = True\n'
            'journal.submit()\n'
            '\n'
            'frappe.db.set_value(\n'
            '    "Employee Cash Advance",\n'
            '    doc.name,\n'
            '    {\n'
            '        "journal_entry": journal.name,\n'
            '        "status": "Disbursed",\n'
            '        "disbursed_by": frappe.session.user,\n'
            '        "disbursed_at": frappe.utils.now(),\n'
            '    },\n'
            '    update_modified=False,\n'
            ')\n'},
 {'name': 'Employee Cash Advance - Before Cancel',
  'reference_doctype': 'Employee Cash Advance',
  'doctype_event': 'Before Cancel',
  'script': '# Server Script\n'
            '# Script Type: DocType Event\n'
            '# Reference DocType: Employee Cash Advance\n'
            '# Event: Before Cancel\n'
            '\n'
            'if frappe.utils.flt(doc.recovered_amount) > 0:\n'
            '    frappe.throw("This Employee Cash Advance cannot be cancelled because recovery has already '
            'started.")\n'
            'if doc.payroll_status in ["Partially Deducted", "Fully Deducted"]:\n'
            '    frappe.throw("This Employee Cash Advance cannot be cancelled because payroll deductions '
            'exist.")\n'
            '\n'
            'if doc.journal_entry:\n'
            '    journal = frappe.get_doc("Journal Entry", doc.journal_entry)\n'
            '    if journal.docstatus == 1:\n'
            '        journal.flags.ignore_permissions = True\n'
            '        journal.cancel()\n'}]

CLIENT_SCRIPTS = [{'name': 'Driver Shortage - Client Script',
  'dt': 'Driver Shortage',
  'view': 'Form',
  'script': 'frappe.ui.form.on("Driver Shortage", {\n'
            '    refresh(frm) {\n'
            '        frm.set_query("employee", () => ({\n'
            '            filters: {\n'
            '                company: frm.doc.company || "Cure",\n'
            '                status: "Active",\n'
            '            },\n'
            '        }));\n'
            '\n'
            '        for (const fieldname of [\n'
            '            "delivery_transit_account",\n'
            '            "employee_shortage_account",\n'
            '        ]) {\n'
            '            frm.set_query(fieldname, () => ({\n'
            '                filters: {\n'
            '                    company: frm.doc.company || "Cure",\n'
            '                    is_group: 0,\n'
            '                    disabled: 0,\n'
            '                },\n'
            '            }));\n'
            '        }\n'
            '\n'
            '        calculate_driver_shortage(frm);\n'
            '    },\n'
            '\n'
            '    delivery_settlement(frm) {\n'
            '        if (!frm.doc.delivery_settlement) return;\n'
            '\n'
            '        frappe.db.get_value(\n'
            '            "Delivery Settlement",\n'
            '            frm.doc.delivery_settlement,\n'
            '            [\n'
            '                "delivery_boy",\n'
            '                "shift_reference",\n'
            '                "total_expected",\n'
            '                "total_collected_by_driver",\n'
            '                "total_handed_over",\n'
            '            ],\n'
            '        ).then(({ message }) => {\n'
            '            if (!message) return;\n'
            '\n'
            '            const expected =\n'
            '                flt(message.total_expected)\n'
            '                || flt(message.total_collected_by_driver);\n'
            '\n'
            '            frm.set_value("employee", message.delivery_boy || "");\n'
            '            frm.set_value("shift_reference", message.shift_reference || "");\n'
            '            frm.set_value("expected_amount", expected);\n'
            '            frm.set_value("handed_over_amount", flt(message.total_handed_over));\n'
            '\n'
            '            calculate_driver_shortage(frm);\n'
            '        });\n'
            '    },\n'
            '\n'
            '    expected_amount: calculate_driver_shortage,\n'
            '    handed_over_amount: calculate_driver_shortage,\n'
            '    recovered_amount: calculate_driver_shortage,\n'
            '    recovery_method: calculate_driver_shortage,\n'
            '    number_of_installments: calculate_driver_shortage,\n'
            '});\n'
            '\n'
            'function calculate_driver_shortage(frm) {\n'
            '    const shortage = Math.max(\n'
            '        flt(frm.doc.expected_amount) - flt(frm.doc.handed_over_amount),\n'
            '        0,\n'
            '    );\n'
            '\n'
            '    const outstanding = Math.max(\n'
            '        shortage - flt(frm.doc.recovered_amount),\n'
            '        0,\n'
            '    );\n'
            '\n'
            '    let installments = cint(frm.doc.number_of_installments || 1);\n'
            '    if (installments < 1) installments = 1;\n'
            '\n'
            '    let installmentAmount = 0;\n'
            '\n'
            '    if (frm.doc.recovery_method === "Salary Deduction") {\n'
            '        installmentAmount = outstanding;\n'
            '    } else if (frm.doc.recovery_method === "Multiple Installments") {\n'
            '        installmentAmount = outstanding / installments;\n'
            '    }\n'
            '\n'
            '    frm.set_value("shortage_amount", shortage);\n'
            '    frm.set_value("outstanding_amount", outstanding);\n'
            '    frm.set_value("installment_amount", installmentAmount);\n'
            '}\n'},
 {'name': 'Employee Cash Advance - Client Script',
  'dt': 'Employee Cash Advance',
  'view': 'Form',
  'script': 'frappe.ui.form.on("Employee Cash Advance", {\n'
            '    refresh(frm) {\n'
            '        frm.set_query("employee", () => ({\n'
            '            filters: {\n'
            '                company: frm.doc.company || "Cure",\n'
            '                status: "Active",\n'
            '            },\n'
            '        }));\n'
            '\n'
            '        for (const fieldname of ["cash_account", "employee_advance_account"]) {\n'
            '            frm.set_query(fieldname, () => ({\n'
            '                filters: {\n'
            '                    company: frm.doc.company || "Cure",\n'
            '                    is_group: 0,\n'
            '                    disabled: 0,\n'
            '                },\n'
            '            }));\n'
            '        }\n'
            '\n'
            '        calculate_employee_advance(frm);\n'
            '    },\n'
            '\n'
            '    advance_amount: calculate_employee_advance,\n'
            '    recovered_amount: calculate_employee_advance,\n'
            '    recovery_method: calculate_employee_advance,\n'
            '    number_of_installments: calculate_employee_advance,\n'
            '});\n'
            '\n'
            'function calculate_employee_advance(frm) {\n'
            '    const outstanding = Math.max(\n'
            '        flt(frm.doc.advance_amount) - flt(frm.doc.recovered_amount),\n'
            '        0,\n'
            '    );\n'
            '\n'
            '    let installments = cint(frm.doc.number_of_installments || 1);\n'
            '    if (installments < 1) installments = 1;\n'
            '\n'
            '    let installmentAmount = 0;\n'
            '\n'
            '    if (frm.doc.recovery_method === "Salary Deduction") {\n'
            '        installmentAmount = outstanding;\n'
            '    } else if (frm.doc.recovery_method === "Multiple Installments") {\n'
            '        installmentAmount = outstanding / installments;\n'
            '    }\n'
            '\n'
            '    frm.set_value("outstanding_amount", outstanding);\n'
            '    frm.set_value("installment_amount", installmentAmount);\n'
            '}\n'}]


def _upsert_server_script(spec):
    existing = frappe.db.exists("Server Script", spec["name"])

    if existing:
        doc = frappe.get_doc("Server Script", existing)
        action = "Updated"
    else:
        doc = frappe.new_doc("Server Script")
        doc.name = spec["name"]
        action = "Created"

    doc.script_type = "DocType Event"
    doc.reference_doctype = spec["reference_doctype"]
    doc.doctype_event = spec["doctype_event"]
    doc.script = spec["script"]
    doc.disabled = 0
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)

    return action, doc.name


def _upsert_client_script(spec):
    existing = frappe.db.exists("Client Script", spec["name"])

    if existing:
        doc = frappe.get_doc("Client Script", existing)
        action = "Updated"
    else:
        doc = frappe.new_doc("Client Script")
        doc.name = spec["name"]
        action = "Created"

    doc.dt = spec["dt"]
    doc.view = spec["view"]
    doc.script = spec["script"]
    doc.enabled = 1
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)

    return action, doc.name


def install():
    """Create or update all Driver Shortage and Employee Cash Advance scripts."""
    results = {"server_scripts": [], "client_scripts": []}

    for spec in SERVER_SCRIPTS:
        action, name = _upsert_server_script(spec)
        results["server_scripts"].append({"name": name, "action": action})

    for spec in CLIENT_SCRIPTS:
        action, name = _upsert_client_script(spec)
        results["client_scripts"].append({"name": name, "action": action})

    frappe.db.commit()
    frappe.clear_cache()

    print("\nEmployee financial scripts installed successfully.\n")

    for row in results["server_scripts"]:
        print(f'{row["action"]} Server Script: {row["name"]}')

    for row in results["client_scripts"]:
        print(f'{row["action"]} Client Script: {row["name"]}')

    return results


def verify():
    """Return the current status of the eight installed scripts."""
    rows = []

    for spec in SERVER_SCRIPTS:
        name = frappe.db.exists("Server Script", spec["name"])
        rows.append(
            {
                "type": "Server Script",
                "name": spec["name"],
                "exists": bool(name),
                "disabled": frappe.db.get_value("Server Script", name, "disabled") if name else None,
                "event": frappe.db.get_value("Server Script", name, "doctype_event") if name else None,
            }
        )

    for spec in CLIENT_SCRIPTS:
        name = frappe.db.exists("Client Script", spec["name"])
        rows.append(
            {
                "type": "Client Script",
                "name": spec["name"],
                "exists": bool(name),
                "enabled": frappe.db.get_value("Client Script", name, "enabled") if name else None,
                "doctype": frappe.db.get_value("Client Script", name, "dt") if name else None,
            }
        )

    for row in rows:
        print(row)

    return rows
