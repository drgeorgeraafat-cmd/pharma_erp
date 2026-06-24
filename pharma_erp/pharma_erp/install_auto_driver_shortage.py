import frappe

SERVER_SCRIPTS = [{'name': 'Driver Shortage - Before Submit',
  'reference_doctype': 'Driver Shortage',
  'event': 'Before Submit',
  'script': '# Server Script\n'
            '# Script Type: DocType Event\n'
            '# Reference DocType: Driver Shortage\n'
            '# Event: Before Submit\n'
            '\n'
            'expected = 0.0\n'
            'handed = 0.0\n'
            'recovered = frappe.utils.flt(doc.recovered_amount)\n'
            'installments = frappe.utils.cint(doc.number_of_installments or 1)\n'
            '\n'
            'if not doc.company:\n'
            '    frappe.throw("Company is required.")\n'
            '\n'
            'if not doc.employee:\n'
            '    frappe.throw("Employee is required.")\n'
            '\n'
            'if not doc.shift_reference:\n'
            '    frappe.throw("Shift Reference is required.")\n'
            '\n'
            'if not doc.delivery_settlement:\n'
            '    frappe.throw("Delivery Settlement is required.")\n'
            '\n'
            'settlement = frappe.get_doc(\n'
            '    "Delivery Settlement",\n'
            '    doc.delivery_settlement,\n'
            ')\n'
            '\n'
            'if settlement.docstatus == 2:\n'
            '    frappe.throw("The selected Delivery Settlement is cancelled.")\n'
            '\n'
            'if settlement.delivery_boy and settlement.delivery_boy != doc.employee:\n'
            '    frappe.throw(\n'
            '        "Employee does not match the delivery boy on the selected settlement."\n'
            '    )\n'
            '\n'
            'if settlement.shift_reference and settlement.shift_reference != doc.shift_reference:\n'
            '    frappe.throw(\n'
            '        "Shift Reference does not match the selected Delivery Settlement."\n'
            '    )\n'
            '\n'
            'if doc.get("delivery_handover"):\n'
            '    handover = frappe.get_doc(\n'
            '        "Delivery Handover",\n'
            '        doc.delivery_handover,\n'
            '    )\n'
            '\n'
            '    if handover.docstatus != 1:\n'
            '        frappe.throw("Final Delivery Handover must be submitted.")\n'
            '\n'
            '    if handover.delivery_settlement != doc.delivery_settlement:\n'
            '        frappe.throw(\n'
            '            "Final Delivery Handover does not belong to the selected settlement."\n'
            '        )\n'
            '\n'
            '    if handover.handover_type != "Final Settlement":\n'
            '        frappe.throw(\n'
            '            "Driver Shortage can only be linked to a Final Settlement handover."\n'
            '        )\n'
            '\n'
            '    duplicate = frappe.db.exists(\n'
            '        "Driver Shortage",\n'
            '        {\n'
            '            "delivery_handover": doc.delivery_handover,\n'
            '            "docstatus": 1,\n'
            '            "name": ["!=", doc.name],\n'
            '        },\n'
            '    )\n'
            'else:\n'
            '    duplicate = frappe.db.exists(\n'
            '        "Driver Shortage",\n'
            '        {\n'
            '            "delivery_settlement": doc.delivery_settlement,\n'
            '            "docstatus": 1,\n'
            '            "name": ["!=", doc.name],\n'
            '        },\n'
            '    )\n'
            '\n'
            'if duplicate:\n'
            '    frappe.throw(\n'
            '        "A submitted Driver Shortage already exists: " + duplicate\n'
            '    )\n'
            '\n'
            'expected = frappe.utils.flt(settlement.pilot_float)\n'
            '\n'
            'for row in settlement.invoices:\n'
            '    if (\n'
            '        row.collection_status == "Confirmed"\n'
            '        and row.collection_received_by == "Delivery Boy"\n'
            '    ):\n'
            '        expected += frappe.utils.flt(\n'
            '            row.confirmed_collection_amount\n'
            '            or row.amount\n'
            '        )\n'
            '\n'
            'submitted_handovers = frappe.get_all(\n'
            '    "Delivery Handover",\n'
            '    filters={\n'
            '        "delivery_settlement": settlement.name,\n'
            '        "docstatus": 1,\n'
            '    },\n'
            '    fields=["amount"],\n'
            '    limit_page_length=1000,\n'
            ')\n'
            '\n'
            'for handover_row in submitted_handovers:\n'
            '    handed += frappe.utils.flt(handover_row.amount)\n'
            '\n'
            'shortage = frappe.utils.flt(expected - handed)\n'
            '\n'
            'if shortage <= 0.01:\n'
            '    frappe.throw(\n'
            '        "There is no shortage to record. Submitted handovers cover the expected amount."\n'
            '    )\n'
            '\n'
            'if recovered < 0:\n'
            '    frappe.throw("Recovered Amount cannot be negative.")\n'
            '\n'
            'if recovered > shortage:\n'
            '    frappe.throw("Recovered Amount cannot exceed Shortage Amount.")\n'
            '\n'
            'outstanding = frappe.utils.flt(shortage - recovered)\n'
            '\n'
            'if doc.recovery_method == "Waived":\n'
            '    frappe.throw(\n'
            '        "Waived shortages are not enabled yet because a shortage write-off "\n'
            '        "expense account has not been configured."\n'
            '    )\n'
            '\n'
            'if doc.recovery_method == "Multiple Installments":\n'
            '    if installments <= 0:\n'
            '        frappe.throw("Number of Installments must be greater than zero.")\n'
            '\n'
            '    installment_amount = frappe.utils.flt(outstanding / installments)\n'
            '    payroll_status = "Scheduled"\n'
            '\n'
            'elif doc.recovery_method == "Salary Deduction":\n'
            '    installments = 1\n'
            '    installment_amount = outstanding\n'
            '    payroll_status = "Scheduled"\n'
            '\n'
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
            '\n'
            'if not doc.employee_shortage_account:\n'
            '    doc.employee_shortage_account = "Employee Shortage - C"\n'
            '\n'
            'for account in [\n'
            '    doc.delivery_transit_account,\n'
            '    doc.employee_shortage_account,\n'
            ']:\n'
            '    account_row = frappe.db.get_value(\n'
            '        "Account",\n'
            '        account,\n'
            '        ["company", "is_group", "disabled"],\n'
            '        as_dict=True,\n'
            '    )\n'
            '\n'
            '    if not account_row:\n'
            '        frappe.throw("Account not found: " + account)\n'
            '\n'
            '    if account_row.company != doc.company:\n'
            '        frappe.throw("Account belongs to another company: " + account)\n'
            '\n'
            '    if account_row.is_group:\n'
            '        frappe.throw("A group account cannot be used: " + account)\n'
            '\n'
            '    if account_row.disabled:\n'
            '        frappe.throw("Account is disabled: " + account)'},
 {'name': 'Auto Create Driver Shortage After Final Handover',
  'reference_doctype': 'Delivery Handover',
  'event': 'After Submit',
  'script': '# Server Script\n'
            '# Script Type: DocType Event\n'
            '# Reference DocType: Delivery Handover\n'
            '# Event: After Submit\n'
            '\n'
            'if doc.handover_type == "Final Settlement":\n'
            '    settlement = frappe.get_doc(\n'
            '        "Delivery Settlement",\n'
            '        doc.delivery_settlement,\n'
            '    )\n'
            '\n'
            '    expected = frappe.utils.flt(settlement.pilot_float)\n'
            '\n'
            '    for row in settlement.invoices:\n'
            '        if (\n'
            '            row.collection_status == "Confirmed"\n'
            '            and row.collection_received_by == "Delivery Boy"\n'
            '        ):\n'
            '            expected += frappe.utils.flt(\n'
            '                row.confirmed_collection_amount\n'
            '                or row.amount\n'
            '            )\n'
            '\n'
            '    submitted_handovers = frappe.get_all(\n'
            '        "Delivery Handover",\n'
            '        filters={\n'
            '            "delivery_settlement": settlement.name,\n'
            '            "docstatus": 1,\n'
            '        },\n'
            '        fields=["amount"],\n'
            '        limit_page_length=1000,\n'
            '    )\n'
            '\n'
            '    handed = 0.0\n'
            '\n'
            '    for handover_row in submitted_handovers:\n'
            '        handed += frappe.utils.flt(handover_row.amount)\n'
            '\n'
            '    shortage_amount = frappe.utils.flt(expected - handed)\n'
            '\n'
            '    if shortage_amount > 0.01:\n'
            '        shortage_name = ""\n'
            '\n'
            '        if doc.get("driver_shortage"):\n'
            '            shortage_name = doc.driver_shortage\n'
            '        else:\n'
            '            shortage_name = frappe.db.exists(\n'
            '                "Driver Shortage",\n'
            '                {\n'
            '                    "delivery_handover": doc.name,\n'
            '                    "docstatus": ["!=", 2],\n'
            '                },\n'
            '            )\n'
            '\n'
            '        company = settlement.get("company")\n'
            '\n'
            '        if not company and doc.shift_reference:\n'
            '            shift_meta = frappe.get_meta("Pharmacy Shift Closing")\n'
            '\n'
            '            if shift_meta.has_field("company"):\n'
            '                company = frappe.db.get_value(\n'
            '                    "Pharmacy Shift Closing",\n'
            '                    doc.shift_reference,\n'
            '                    "company",\n'
            '                )\n'
            '\n'
            '        if not company:\n'
            '            company = frappe.db.get_single_value(\n'
            '                "Global Defaults",\n'
            '                "default_company",\n'
            '            )\n'
            '\n'
            '        if not company:\n'
            '            company = "Cure"\n'
            '\n'
            '        shortage_date = frappe.utils.today()\n'
            '\n'
            '        if doc.received_at:\n'
            '            shortage_date = frappe.utils.getdate(doc.received_at)\n'
            '\n'
            '        if shortage_name:\n'
            '            shortage_doc = frappe.get_doc(\n'
            '                "Driver Shortage",\n'
            '                shortage_name,\n'
            '            )\n'
            '\n'
            '            if shortage_doc.docstatus == 1:\n'
            '                frappe.db.set_value(\n'
            '                    "Delivery Handover",\n'
            '                    doc.name,\n'
            '                    "driver_shortage",\n'
            '                    shortage_doc.name,\n'
            '                    update_modified=False,\n'
            '                )\n'
            '            elif shortage_doc.docstatus == 0:\n'
            '                shortage_doc.company = company\n'
            '                shortage_doc.employee = (\n'
            '                    doc.delivery_boy\n'
            '                    or settlement.delivery_boy\n'
            '                )\n'
            '                shortage_doc.shift_reference = doc.shift_reference\n'
            '                shortage_doc.delivery_settlement = settlement.name\n'
            '                shortage_doc.delivery_handover = doc.name\n'
            '                shortage_doc.shortage_date = shortage_date\n'
            '                shortage_doc.expected_amount = expected\n'
            '                shortage_doc.handed_over_amount = handed\n'
            '                shortage_doc.shortage_amount = shortage_amount\n'
            '                shortage_doc.recovered_amount = 0\n'
            '                shortage_doc.outstanding_amount = shortage_amount\n'
            '                shortage_doc.recovery_method = "Salary Deduction"\n'
            '                shortage_doc.payroll_date = frappe.utils.get_last_day(\n'
            '                    shortage_date\n'
            '                )\n'
            '                shortage_doc.number_of_installments = 1\n'
            '                shortage_doc.reason = (\n'
            '                    doc.notes\n'
            '                    or "Automatic shortage from final delivery settlement."\n'
            '                )\n'
            '                shortage_doc.delivery_transit_account = (\n'
            '                    "Delivery Cash In Transit - C"\n'
            '                )\n'
            '                shortage_doc.employee_shortage_account = (\n'
            '                    "Employee Shortage - C"\n'
            '                )\n'
            '                shortage_doc.flags.ignore_permissions = True\n'
            '                shortage_doc.save(ignore_permissions=True)\n'
            '                shortage_doc.flags.ignore_permissions = True\n'
            '                shortage_doc.submit()\n'
            '\n'
            '                frappe.db.set_value(\n'
            '                    "Delivery Handover",\n'
            '                    doc.name,\n'
            '                    "driver_shortage",\n'
            '                    shortage_doc.name,\n'
            '                    update_modified=False,\n'
            '                )\n'
            '        else:\n'
            '            shortage_doc = frappe.new_doc("Driver Shortage")\n'
            '            shortage_doc.company = company\n'
            '            shortage_doc.employee = (\n'
            '                doc.delivery_boy\n'
            '                or settlement.delivery_boy\n'
            '            )\n'
            '            shortage_doc.shift_reference = doc.shift_reference\n'
            '            shortage_doc.delivery_settlement = settlement.name\n'
            '            shortage_doc.delivery_handover = doc.name\n'
            '            shortage_doc.shortage_date = shortage_date\n'
            '            shortage_doc.expected_amount = expected\n'
            '            shortage_doc.handed_over_amount = handed\n'
            '            shortage_doc.shortage_amount = shortage_amount\n'
            '            shortage_doc.recovered_amount = 0\n'
            '            shortage_doc.outstanding_amount = shortage_amount\n'
            '            shortage_doc.recovery_method = "Salary Deduction"\n'
            '            shortage_doc.payroll_date = frappe.utils.get_last_day(\n'
            '                shortage_date\n'
            '            )\n'
            '            shortage_doc.number_of_installments = 1\n'
            '            shortage_doc.reason = (\n'
            '                doc.notes\n'
            '                or "Automatic shortage from final delivery settlement."\n'
            '            )\n'
            '            shortage_doc.delivery_transit_account = (\n'
            '                "Delivery Cash In Transit - C"\n'
            '            )\n'
            '            shortage_doc.employee_shortage_account = (\n'
            '                "Employee Shortage - C"\n'
            '            )\n'
            '            shortage_doc.flags.ignore_permissions = True\n'
            '            shortage_doc.insert(ignore_permissions=True)\n'
            '            shortage_doc.flags.ignore_permissions = True\n'
            '            shortage_doc.submit()\n'
            '\n'
            '            frappe.db.set_value(\n'
            '                "Delivery Handover",\n'
            '                doc.name,\n'
            '                "driver_shortage",\n'
            '                shortage_doc.name,\n'
            '                update_modified=False,\n'
            '            )\n'
            '\n'
            '        frappe.msgprint(\n'
            '            "تم تسجيل عجز على الطيار بقيمة "\n'
            '            + str(shortage_amount)\n'
            '            + " وربطه بالتسوية النهائية."\n'
            '        )'},
 {'name': 'Cancel Auto Driver Shortage Before Handover Cancel',
  'reference_doctype': 'Delivery Handover',
  'event': 'Before Cancel',
  'script': '# Server Script\n'
            '# Script Type: DocType Event\n'
            '# Reference DocType: Delivery Handover\n'
            '# Event: Before Cancel\n'
            '\n'
            'if doc.handover_type == "Final Settlement":\n'
            '    shortage_name = doc.get("driver_shortage")\n'
            '\n'
            '    if not shortage_name:\n'
            '        shortage_name = frappe.db.exists(\n'
            '            "Driver Shortage",\n'
            '            {\n'
            '                "delivery_handover": doc.name,\n'
            '                "docstatus": ["!=", 2],\n'
            '            },\n'
            '        )\n'
            '\n'
            '    if shortage_name:\n'
            '        shortage_doc = frappe.get_doc(\n'
            '            "Driver Shortage",\n'
            '            shortage_name,\n'
            '        )\n'
            '\n'
            '        if shortage_doc.docstatus == 1:\n'
            '            shortage_doc.flags.ignore_permissions = True\n'
            '            shortage_doc.cancel()\n'
            '        elif shortage_doc.docstatus == 0:\n'
            '            frappe.delete_doc(\n'
            '                "Driver Shortage",\n'
            '                shortage_doc.name,\n'
            '                ignore_permissions=True,\n'
            '            )'}]


def _ensure_link_field(
    doctype_name,
    fieldname,
    label,
    options,
    insert_after=None,
    allow_on_submit=0,
):
    doctype = frappe.get_doc("DocType", doctype_name)

    existing = None

    for row in doctype.fields:
        if row.fieldname == fieldname:
            existing = row
            break

    if existing:
        existing.label = label
        existing.fieldtype = "Link"
        existing.options = options
        existing.read_only = 1
        existing.no_copy = 1
        existing.allow_on_submit = allow_on_submit
    else:
        doctype.append(
            "fields",
            {
                "label": label,
                "fieldname": fieldname,
                "fieldtype": "Link",
                "options": options,
                "insert_after": insert_after,
                "read_only": 1,
                "no_copy": 1,
                "allow_on_submit": allow_on_submit,
            },
        )

    doctype.flags.ignore_permissions = True
    doctype.save(ignore_permissions=True)


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
    doc.doctype_event = spec["event"]
    doc.script = spec["script"]
    doc.disabled = 0
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)

    return action, doc.name


def install():
    _ensure_link_field(
        "Driver Shortage",
        "delivery_handover",
        "Final Delivery Handover",
        "Delivery Handover",
        insert_after="delivery_settlement",
        allow_on_submit=0,
    )

    _ensure_link_field(
        "Delivery Handover",
        "driver_shortage",
        "Driver Shortage",
        "Driver Shortage",
        insert_after="journal_entry",
        allow_on_submit=1,
    )

    results = []

    for spec in SERVER_SCRIPTS:
        results.append(_upsert_server_script(spec))

    frappe.db.commit()
    frappe.clear_cache()

    print("Automatic Driver Shortage integration installed.")

    for action, name in results:
        print(action + " Server Script: " + name)

    return verify()


def verify():
    result = {
        "Driver Shortage.delivery_handover": bool(
            frappe.get_meta("Driver Shortage").has_field("delivery_handover")
        ),
        "Delivery Handover.driver_shortage": bool(
            frappe.get_meta("Delivery Handover").has_field("driver_shortage")
        ),
        "scripts": [],
    }

    for spec in SERVER_SCRIPTS:
        name = frappe.db.exists("Server Script", spec["name"])

        result["scripts"].append(
            {
                "name": spec["name"],
                "exists": bool(name),
                "disabled": (
                    frappe.db.get_value("Server Script", name, "disabled")
                    if name else None
                ),
                "event": (
                    frappe.db.get_value("Server Script", name, "doctype_event")
                    if name else None
                ),
            }
        )

    print(result)
    return result
