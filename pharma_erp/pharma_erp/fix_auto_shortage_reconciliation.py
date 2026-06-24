import frappe

DRIVER_SHORTAGE_BEFORE_SUBMIT = '# Server Script\n# Script Type: DocType Event\n# Reference DocType: Driver Shortage\n# Event: Before Submit\n\nexpected = 0.0\nhanded = 0.0\nrecovered = frappe.utils.flt(doc.recovered_amount)\ninstallments = frappe.utils.cint(doc.number_of_installments or 1)\n\nif not doc.company:\n    frappe.throw("Company is required.")\n\nif not doc.employee:\n    frappe.throw("Employee is required.")\n\nif not doc.shift_reference:\n    frappe.throw("Shift Reference is required.")\n\nif not doc.delivery_settlement:\n    frappe.throw("Delivery Settlement is required.")\n\nsettlement = frappe.get_doc(\n    "Delivery Settlement",\n    doc.delivery_settlement,\n)\n\nif settlement.docstatus == 2:\n    frappe.throw("The selected Delivery Settlement is cancelled.")\n\nif settlement.delivery_boy and settlement.delivery_boy != doc.employee:\n    frappe.throw(\n        "Employee does not match the delivery boy on the selected settlement."\n    )\n\nif settlement.shift_reference and settlement.shift_reference != doc.shift_reference:\n    frappe.throw(\n        "Shift Reference does not match the selected Delivery Settlement."\n    )\n\nif doc.get("delivery_handover"):\n    handover = frappe.get_doc(\n        "Delivery Handover",\n        doc.delivery_handover,\n    )\n\n    if handover.docstatus != 1:\n        frappe.throw("Final Delivery Handover must be submitted.")\n\n    if handover.delivery_settlement != doc.delivery_settlement:\n        frappe.throw(\n            "Final Delivery Handover does not belong to the selected settlement."\n        )\n\n    if handover.handover_type != "Final Settlement":\n        frappe.throw(\n            "Driver Shortage can only be linked to a Final Settlement handover."\n        )\n\n    duplicate = frappe.db.exists(\n        "Driver Shortage",\n        {\n            "delivery_handover": doc.delivery_handover,\n            "docstatus": 1,\n            "name": ["!=", doc.name],\n        },\n    )\nelse:\n    duplicate = frappe.db.exists(\n        "Driver Shortage",\n        {\n            "delivery_settlement": doc.delivery_settlement,\n            "docstatus": 1,\n            "name": ["!=", doc.name],\n        },\n    )\n\nif duplicate:\n    frappe.throw(\n        "A submitted Driver Shortage already exists: " + duplicate\n    )\n\n# Use the settlement total as the source of truth.\nexpected = frappe.utils.flt(settlement.total_expected)\n\n# Fallback for old settlements where total_expected was not populated.\nif expected <= 0.01:\n    expected = frappe.utils.flt(settlement.pilot_float)\n\n    for row in settlement.invoices:\n        if (\n            row.collection_status == "Confirmed"\n            and row.collection_received_by == "Delivery Boy"\n        ):\n            expected += frappe.utils.flt(\n                row.confirmed_collection_amount\n                or row.amount\n            )\n\nsubmitted_handovers = frappe.get_all(\n    "Delivery Handover",\n    filters={\n        "delivery_settlement": settlement.name,\n        "docstatus": 1,\n    },\n    fields=["amount"],\n    limit_page_length=1000,\n)\n\nfor handover_row in submitted_handovers:\n    handed += frappe.utils.flt(handover_row.amount)\n\nshortage = frappe.utils.flt(expected - handed)\n\nif shortage <= 0.01:\n    frappe.throw(\n        "There is no shortage to record. Submitted handovers cover the expected amount."\n    )\n\nif recovered < 0:\n    frappe.throw("Recovered Amount cannot be negative.")\n\nif recovered > shortage:\n    frappe.throw("Recovered Amount cannot exceed Shortage Amount.")\n\noutstanding = frappe.utils.flt(shortage - recovered)\n\nif doc.recovery_method == "Waived":\n    frappe.throw(\n        "Waived shortages are not enabled yet because a shortage write-off "\n        "expense account has not been configured."\n    )\n\nif doc.recovery_method == "Multiple Installments":\n    if installments <= 0:\n        frappe.throw("Number of Installments must be greater than zero.")\n\n    installment_amount = frappe.utils.flt(outstanding / installments)\n    payroll_status = "Scheduled"\n\nelif doc.recovery_method == "Salary Deduction":\n    installments = 1\n    installment_amount = outstanding\n    payroll_status = "Scheduled"\n\nelse:\n    installments = 1\n    installment_amount = 0\n    payroll_status = "Not Applicable"\n\ndoc.expected_amount = expected\ndoc.handed_over_amount = handed\ndoc.shortage_amount = shortage\ndoc.recovered_amount = recovered\ndoc.outstanding_amount = outstanding\ndoc.number_of_installments = installments\ndoc.installment_amount = installment_amount\ndoc.payroll_status = payroll_status\ndoc.status = "Open"\ndoc.approved_by = frappe.session.user\ndoc.approved_at = frappe.utils.now()\n\nif not doc.delivery_transit_account:\n    doc.delivery_transit_account = "Delivery Cash In Transit - C"\n\nif not doc.employee_shortage_account:\n    doc.employee_shortage_account = "Employee Shortage - C"\n\nfor account in [\n    doc.delivery_transit_account,\n    doc.employee_shortage_account,\n]:\n    account_row = frappe.db.get_value(\n        "Account",\n        account,\n        ["company", "is_group", "disabled"],\n        as_dict=True,\n    )\n\n    if not account_row:\n        frappe.throw("Account not found: " + account)\n\n    if account_row.company != doc.company:\n        frappe.throw("Account belongs to another company: " + account)\n\n    if account_row.is_group:\n        frappe.throw("A group account cannot be used: " + account)\n\n    if account_row.disabled:\n        frappe.throw("Account is disabled: " + account)'
AUTO_CREATE_SCRIPT = '# Server Script\n# Script Type: DocType Event\n# Reference DocType: Delivery Handover\n# Event: After Submit\n\nif doc.handover_type == "Final Settlement":\n    settlement = frappe.get_doc(\n        "Delivery Settlement",\n        doc.delivery_settlement,\n    )\n\n    # total_expected is the accounting source of truth.\n    expected = frappe.utils.flt(settlement.total_expected)\n\n    # Fallback for old settlements.\n    if expected <= 0.01:\n        expected = frappe.utils.flt(settlement.pilot_float)\n\n        for row in settlement.invoices:\n            if (\n                row.collection_status == "Confirmed"\n                and row.collection_received_by == "Delivery Boy"\n            ):\n                expected += frappe.utils.flt(\n                    row.confirmed_collection_amount\n                    or row.amount\n                )\n\n    submitted_handovers = frappe.get_all(\n        "Delivery Handover",\n        filters={\n            "delivery_settlement": settlement.name,\n            "docstatus": 1,\n        },\n        fields=["amount"],\n        limit_page_length=1000,\n    )\n\n    handed = 0.0\n\n    for handover_row in submitted_handovers:\n        handed += frappe.utils.flt(handover_row.amount)\n\n    shortage_amount = frappe.utils.flt(expected - handed)\n\n    if shortage_amount > 0.01:\n        shortage_name = doc.get("driver_shortage")\n\n        if not shortage_name:\n            shortage_name = frappe.db.exists(\n                "Driver Shortage",\n                {\n                    "delivery_handover": doc.name,\n                    "docstatus": ["!=", 2],\n                },\n            )\n\n        company = settlement.get("company")\n\n        if not company and doc.shift_reference:\n            shift_meta = frappe.get_meta("Pharmacy Shift Closing")\n\n            if shift_meta.has_field("company"):\n                company = frappe.db.get_value(\n                    "Pharmacy Shift Closing",\n                    doc.shift_reference,\n                    "company",\n                )\n\n        if not company:\n            company = frappe.db.get_single_value(\n                "Global Defaults",\n                "default_company",\n            )\n\n        if not company:\n            company = "Cure"\n\n        shortage_date = frappe.utils.today()\n\n        if doc.received_at:\n            shortage_date = frappe.utils.getdate(doc.received_at)\n\n        if shortage_name:\n            shortage_doc = frappe.get_doc(\n                "Driver Shortage",\n                shortage_name,\n            )\n        else:\n            shortage_doc = frappe.new_doc("Driver Shortage")\n\n        if shortage_doc.docstatus == 0:\n            shortage_doc.company = company\n            shortage_doc.employee = (\n                doc.delivery_boy\n                or settlement.delivery_boy\n            )\n            shortage_doc.shift_reference = doc.shift_reference\n            shortage_doc.delivery_settlement = settlement.name\n            shortage_doc.delivery_handover = doc.name\n            shortage_doc.shortage_date = shortage_date\n            shortage_doc.expected_amount = expected\n            shortage_doc.handed_over_amount = handed\n            shortage_doc.shortage_amount = shortage_amount\n            shortage_doc.recovered_amount = 0\n            shortage_doc.outstanding_amount = shortage_amount\n            shortage_doc.recovery_method = "Salary Deduction"\n            shortage_doc.payroll_date = frappe.utils.get_last_day(\n                shortage_date\n            )\n            shortage_doc.number_of_installments = 1\n            shortage_doc.reason = (\n                doc.notes\n                or "Automatic shortage from final delivery settlement."\n            )\n            shortage_doc.delivery_transit_account = (\n                "Delivery Cash In Transit - C"\n            )\n            shortage_doc.employee_shortage_account = (\n                "Employee Shortage - C"\n            )\n\n            if shortage_doc.is_new():\n                shortage_doc.flags.ignore_permissions = True\n                shortage_doc.insert(ignore_permissions=True)\n            else:\n                shortage_doc.flags.ignore_permissions = True\n                shortage_doc.save(ignore_permissions=True)\n\n            shortage_doc.flags.ignore_permissions = True\n            shortage_doc.submit()\n\n        frappe.db.set_value(\n            "Delivery Handover",\n            doc.name,\n            "driver_shortage",\n            shortage_doc.name,\n            update_modified=False,\n        )\n\n        # Force the settlement to the final correct state.\n        frappe.db.set_value(\n            "Delivery Settlement",\n            settlement.name,\n            {\n                "remaining_with_driver": 0,\n                "final_difference": shortage_amount,\n                "difference_reason": (\n                    "Converted to Driver Shortage "\n                    + shortage_doc.name\n                ),\n                "settlement_status": "Settled",\n                "settled_at": frappe.utils.now(),\n                "settled_by": frappe.session.user,\n            },\n            update_modified=False,\n        )\n\n        frappe.msgprint(\n            "تم تسجيل عجز على الطيار بقيمة "\n            + str(shortage_amount)\n            + " في المستند "\n            + shortage_doc.name\n        )'
RECONCILE_BLOCK = '# AUTO_SHORTAGE_RECONCILIATION_V2\nif doc.handover_type == "Final Settlement":\n    shortage_name = doc.get("driver_shortage")\n\n    if not shortage_name:\n        shortage_name = frappe.db.exists(\n            "Driver Shortage",\n            {\n                "delivery_handover": doc.name,\n                "docstatus": 1,\n            },\n        )\n\n    if shortage_name:\n        shortage_amount = frappe.utils.flt(\n            frappe.db.get_value(\n                "Driver Shortage",\n                shortage_name,\n                "shortage_amount",\n            )\n        )\n\n        frappe.db.set_value(\n            "Delivery Settlement",\n            doc.delivery_settlement,\n            {\n                "remaining_with_driver": 0,\n                "final_difference": shortage_amount,\n                "difference_reason": (\n                    "Converted to Driver Shortage "\n                    + shortage_name\n                ),\n                "settlement_status": "Settled",\n                "settled_at": frappe.utils.now(),\n                "settled_by": frappe.session.user,\n            },\n            update_modified=False,\n        )'


def _upsert_server_script(name, reference_doctype, event, script):
    existing = frappe.db.exists("Server Script", name)

    if existing:
        doc = frappe.get_doc("Server Script", existing)
        action = "Updated"
    else:
        doc = frappe.new_doc("Server Script")
        doc.name = name
        action = "Created"

    doc.script_type = "DocType Event"
    doc.reference_doctype = reference_doctype
    doc.doctype_event = event
    doc.script = script
    doc.disabled = 0
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)

    return action, doc.name


def install():
    results = []

    results.append(
        _upsert_server_script(
            "Driver Shortage - Before Submit",
            "Driver Shortage",
            "Before Submit",
            DRIVER_SHORTAGE_BEFORE_SUBMIT,
        )
    )

    results.append(
        _upsert_server_script(
            "Auto Create Driver Shortage After Final Handover",
            "Delivery Handover",
            "After Submit",
            AUTO_CREATE_SCRIPT,
        )
    )

    settlement_script_name = frappe.db.exists(
        "Server Script",
        "Settlement After Handover",
    )

    if settlement_script_name:
        settlement_script = frappe.get_doc(
            "Server Script",
            settlement_script_name,
        )

        if "AUTO_SHORTAGE_RECONCILIATION_V2" not in (
            settlement_script.script or ""
        ):
            settlement_script.script = (
                (settlement_script.script or "").rstrip()
                + "\n\n"
                + RECONCILE_BLOCK
                + "\n"
            )

        settlement_script.disabled = 0
        settlement_script.flags.ignore_permissions = True
        settlement_script.save(ignore_permissions=True)
        results.append(("Updated", settlement_script.name))

    frappe.db.commit()
    frappe.clear_cache()

    print("Automatic shortage reconciliation fix installed.")

    for action, name in results:
        print(action + ": " + name)

    return verify()


def _get_expected(settlement):
    expected = frappe.utils.flt(settlement.total_expected)

    if expected <= 0.01:
        expected = frappe.utils.flt(settlement.pilot_float)

        for row in settlement.invoices:
            if (
                row.collection_status == "Confirmed"
                and row.collection_received_by == "Delivery Boy"
            ):
                expected += frappe.utils.flt(
                    row.confirmed_collection_amount
                    or row.amount
                )

    return expected


def _get_handed(settlement_name):
    rows = frappe.get_all(
        "Delivery Handover",
        filters={
            "delivery_settlement": settlement_name,
            "docstatus": 1,
        },
        fields=["amount"],
        limit_page_length=1000,
    )

    total = 0.0

    for row in rows:
        total += frappe.utils.flt(row.amount)

    return total


def repair(settlement_name):
    settlement = frappe.get_doc(
        "Delivery Settlement",
        settlement_name,
    )

    final_handover_name = frappe.db.get_value(
        "Delivery Handover",
        {
            "delivery_settlement": settlement.name,
            "handover_type": "Final Settlement",
            "docstatus": 1,
        },
        "name",
        order_by="creation desc",
    )

    if not final_handover_name:
        frappe.throw("No submitted Final Settlement handover was found.")

    handover = frappe.get_doc(
        "Delivery Handover",
        final_handover_name,
    )

    expected = _get_expected(settlement)
    handed = _get_handed(settlement.name)
    shortage_amount = frappe.utils.flt(expected - handed)

    if shortage_amount <= 0.01:
        frappe.throw("There is no shortage to repair.")

    shortage_name = handover.get("driver_shortage")

    if not shortage_name:
        shortage_name = frappe.db.exists(
            "Driver Shortage",
            {
                "delivery_handover": handover.name,
                "docstatus": ["!=", 2],
            },
        )

    if not shortage_name:
        shortage = frappe.new_doc("Driver Shortage")
        shortage.company = settlement.get("company") or "Cure"
        shortage.employee = (
            handover.delivery_boy
            or settlement.delivery_boy
        )
        shortage.shift_reference = handover.shift_reference
        shortage.delivery_settlement = settlement.name
        shortage.delivery_handover = handover.name
        shortage.shortage_date = frappe.utils.getdate(
            handover.received_at or frappe.utils.today()
        )
        shortage.expected_amount = expected
        shortage.handed_over_amount = handed
        shortage.shortage_amount = shortage_amount
        shortage.recovered_amount = 0
        shortage.outstanding_amount = shortage_amount
        shortage.recovery_method = "Salary Deduction"
        shortage.payroll_date = frappe.utils.get_last_day(
            shortage.shortage_date
        )
        shortage.number_of_installments = 1
        shortage.reason = (
            handover.notes
            or "Automatic shortage repair from final settlement."
        )
        shortage.delivery_transit_account = (
            "Delivery Cash In Transit - C"
        )
        shortage.employee_shortage_account = (
            "Employee Shortage - C"
        )
        shortage.flags.ignore_permissions = True
        shortage.insert(ignore_permissions=True)
        shortage.flags.ignore_permissions = True
        shortage.submit()
        shortage_name = shortage.name

        frappe.db.set_value(
            "Delivery Handover",
            handover.name,
            "driver_shortage",
            shortage_name,
            update_modified=False,
        )

    frappe.db.set_value(
        "Delivery Settlement",
        settlement.name,
        {
            "remaining_with_driver": 0,
            "final_difference": shortage_amount,
            "difference_reason": (
                "Converted to Driver Shortage "
                + shortage_name
            ),
            "settlement_status": "Settled",
            "settled_at": frappe.utils.now(),
            "settled_by": frappe.session.user,
        },
        update_modified=False,
    )

    frappe.db.commit()
    frappe.clear_cache()

    result = {
        "settlement": settlement.name,
        "final_handover": handover.name,
        "expected": expected,
        "handed_over": handed,
        "shortage": shortage_amount,
        "driver_shortage": shortage_name,
    }

    print(result)
    return result


def verify():
    result = {
        "Driver Shortage Before Submit": frappe.db.get_value(
            "Server Script",
            "Driver Shortage - Before Submit",
            ["disabled", "doctype_event"],
            as_dict=True,
        ),
        "Auto Create Driver Shortage": frappe.db.get_value(
            "Server Script",
            "Auto Create Driver Shortage After Final Handover",
            ["disabled", "doctype_event"],
            as_dict=True,
        ),
        "Settlement After Handover patched": (
            "AUTO_SHORTAGE_RECONCILIATION_V2"
            in (
                frappe.db.get_value(
                    "Server Script",
                    "Settlement After Handover",
                    "script",
                )
                or ""
            )
        ),
    }

    print(result)
    return result
