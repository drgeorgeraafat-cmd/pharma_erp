
import frappe

COMPANY = "Cure"

CLEARING_CONFIGS = [
    {
        "mode_of_payment": "Insta Pay",
        "account_name": "InstaPay Clearing",
        "destination_account": "CIB - C",
        "settlement_policy": "At Shift Closing",
    },
    {
        "mode_of_payment": "Wallet",
        "account_name": "Wallet Clearing",
        "destination_account": "Smart Wallet - C",
        "settlement_policy": "At Shift Closing",
    },
    {
        "mode_of_payment": "Credit Card",
        "account_name": "Card Clearing",
        "destination_account": "QNB - C",
        "settlement_policy": "On Actual Bank Settlement",
    },
]


def _field(label, fieldname, fieldtype, **kwargs):
    row = {"label": label, "fieldname": fieldname, "fieldtype": fieldtype}
    row.update(kwargs)
    return row


DOCTYPE_SPECS = {
    "Payment Method Clearing Setup": {
        "custom": 1,
        "module": "Pharma Erp",
        "istable": 0,
        "issingle": 0,
        "is_submittable": 0,
        "track_changes": 1,
        "allow_rename": 0,
        "autoname": "format:PMCS-{#####}",
        "title_field": "mode_of_payment",
        "search_fields": "mode_of_payment,company,clearing_account,destination_account",
        "fields": [
            _field("Setup", "setup_section", "Section Break"),
            _field("Company", "company", "Link", options="Company", reqd=1, default="Cure"),
            _field("Mode of Payment", "mode_of_payment", "Link", options="Mode of Payment", reqd=1, in_list_view=1),
            _field("", "column_break_1", "Column Break"),
            _field("Enabled", "enabled", "Check", default="1", in_list_view=1),
            _field("Settlement Policy", "settlement_policy", "Select", options="At Shift Closing\nOn Actual Bank Settlement", reqd=1, default="At Shift Closing", in_list_view=1),
            _field("Accounts", "accounts_section", "Section Break"),
            _field("Clearing Account", "clearing_account", "Link", options="Account", reqd=1, in_list_view=1),
            _field("Destination Account", "destination_account", "Link", options="Account", reqd=1, in_list_view=1),
            _field("", "column_break_2", "Column Break"),
            _field("Fee Account", "fee_account", "Link", options="Account"),
            _field("Notes", "notes", "Small Text"),
        ],
    },
    "Shift Payment Reconciliation Item": {
        "custom": 1,
        "module": "Pharma Erp",
        "istable": 1,
        "issingle": 0,
        "is_submittable": 0,
        "track_changes": 0,
        "allow_rename": 0,
        "fields": [
            _field("Payment Entry", "payment_entry", "Link", options="Payment Entry", read_only=1, in_list_view=1),
            _field("Sales Invoice", "sales_invoice", "Link", options="Sales Invoice", read_only=1, in_list_view=1),
            _field("Customer", "customer", "Link", options="Customer", read_only=1),
            _field("Order Type", "order_type", "Data", read_only=1),
            _field("Transaction Date", "transaction_date", "Datetime", read_only=1),
            _field("Reference Number", "reference_number", "Data", read_only=1),
            _field("Amount", "amount", "Currency", read_only=1, in_list_view=1),
            _field("Verified", "verified", "Check", default="0", in_list_view=1),
            _field("Notes", "notes", "Small Text"),
        ],
    },
    "Shift Payment Reconciliation": {
        "custom": 1,
        "module": "Pharma Erp",
        "istable": 0,
        "issingle": 0,
        "is_submittable": 1,
        "track_changes": 1,
        "allow_rename": 0,
        "autoname": "naming_series:",
        "title_field": "mode_of_payment",
        "search_fields": "shift_reference,mode_of_payment,status,journal_entry",
        "fields": [
            _field("Series", "naming_series", "Select", options="SPR-.YYYY.-.#####", default="SPR-.YYYY.-.#####", reqd=1, hidden=1),
            _field("General", "general_section", "Section Break"),
            _field("Shift Reference", "shift_reference", "Link", options="Pharmacy Shift Closing", reqd=1, in_list_view=1),
            _field("Company", "company", "Link", options="Company", reqd=1, default="Cure"),
            _field("Mode of Payment", "mode_of_payment", "Link", options="Mode of Payment", reqd=1, in_list_view=1),
            _field("Setup Reference", "setup_reference", "Link", options="Payment Method Clearing Setup", reqd=1),
            _field("", "column_break_1", "Column Break"),
            _field("Status", "status", "Select", options="Draft\nReviewed\nSubmitted\nCancelled", default="Draft", read_only=1, in_list_view=1),
            _field("From Time", "from_time", "Datetime", read_only=1),
            _field("To Time", "to_time", "Datetime", read_only=1),
            _field("Accounts", "accounts_section", "Section Break"),
            _field("Clearing Account", "clearing_account", "Link", options="Account", read_only=1),
            _field("Destination Account", "destination_account", "Link", options="Account", read_only=1),
            _field("Settlement Policy", "settlement_policy", "Select", options="At Shift Closing\nOn Actual Bank Settlement", read_only=1),
            _field("Fee Account", "fee_account", "Link", options="Account", read_only=1),
            _field("Amounts", "amounts_section", "Section Break"),
            _field("Expected Amount", "expected_amount", "Currency", read_only=1),
            _field("Reviewed Amount", "reviewed_amount", "Currency", reqd=1, in_list_view=1),
            _field("Difference", "difference", "Currency", read_only=1, in_list_view=1),
            _field("", "column_break_2", "Column Break"),
            _field("Fee Amount", "fee_amount", "Currency", default="0"),
            _field("Net Transfer Amount", "net_transfer_amount", "Currency", read_only=1),
            _field("Review", "review_section", "Section Break"),
            _field("Reviewed By", "reviewed_by", "Link", options="User", read_only=1),
            _field("Reviewed At", "reviewed_at", "Datetime", read_only=1),
            _field("Journal Entry", "journal_entry", "Link", options="Journal Entry", read_only=1, allow_on_submit=1, no_copy=1),
            _field("Notes", "notes", "Small Text"),
            _field("Transactions", "transactions_section", "Section Break"),
            _field("Transactions", "transactions", "Table", options="Shift Payment Reconciliation Item"),
            _field("Amended From", "amended_from", "Link", options="Shift Payment Reconciliation", read_only=1, hidden=1, no_copy=1),
        ],
    },
    "Shift Cash Movement": {
        "custom": 1,
        "module": "Pharma Erp",
        "istable": 0,
        "issingle": 0,
        "is_submittable": 1,
        "track_changes": 1,
        "allow_rename": 0,
        "autoname": "naming_series:",
        "title_field": "movement_type",
        "search_fields": "shift_reference,movement_type,employee,supplier,journal_entry",
        "fields": [
            _field("Series", "naming_series", "Select", options="SCM-.YYYY.-.#####", default="SCM-.YYYY.-.#####", reqd=1, hidden=1),
            _field("General", "general_section", "Section Break"),
            _field("Shift Reference", "shift_reference", "Link", options="Pharmacy Shift Closing", reqd=1, in_list_view=1),
            _field("Company", "company", "Link", options="Company", reqd=1, default="Cure"),
            _field("Movement Date", "movement_date", "Datetime", reqd=1, default="Now"),
            _field("Movement Type", "movement_type", "Select", options="Opening Float\nTill Refill\nTransfer to Main Safe\nSupplier Payment\nOperating Expense\nEmployee Advance\nOther", reqd=1, in_list_view=1),
            _field("Direction", "direction", "Select", options="In\nOut", reqd=1, in_list_view=1),
            _field("", "column_break_1", "Column Break"),
            _field("Amount", "amount", "Currency", reqd=1, in_list_view=1),
            _field("Status", "status", "Select", options="Draft\nPosted\nCancelled", default="Draft", read_only=1, in_list_view=1),
            _field("Accounts", "accounts_section", "Section Break"),
            _field("Source Account", "source_account", "Link", options="Account", reqd=1),
            _field("Target Account", "target_account", "Link", options="Account", reqd=1),
            _field("", "column_break_2", "Column Break"),
            _field("Expense Account", "expense_account", "Link", options="Account"),
            _field("Supplier", "supplier", "Link", options="Supplier"),
            _field("Employee", "employee", "Link", options="Employee"),
            _field("References", "reference_section", "Section Break"),
            _field("Description", "description", "Small Text", reqd=1),
            _field("Journal Entry", "journal_entry", "Link", options="Journal Entry", read_only=1, allow_on_submit=1, no_copy=1),
            _field("Posted By", "posted_by", "Link", options="User", read_only=1),
            _field("Posted At", "posted_at", "Datetime", read_only=1),
            _field("Amended From", "amended_from", "Link", options="Shift Cash Movement", read_only=1, hidden=1, no_copy=1),
        ],
    },
}


def _dedupe_fields(doc):
    seen = set()
    for row in list(doc.fields):
        if not row.fieldname:
            continue
        if row.fieldname in seen:
            doc.remove(row)
        else:
            seen.add(row.fieldname)


def _ensure_permission(doc, role="System Manager"):
    for row in doc.permissions:
        if row.role == role:
            row.read = row.write = row.create = 1
            if doc.is_submittable:
                row.submit = row.cancel = row.amend = 1
            return
    values = {"role": role, "read": 1, "write": 1, "create": 1}
    if doc.is_submittable:
        values.update({"submit": 1, "cancel": 1, "amend": 1})
    doc.append("permissions", values)


def _upsert_doctype(name, spec):
    if frappe.db.exists("DocType", name):
        doc = frappe.get_doc("DocType", name)
        action = "Updated"
    else:
        doc = frappe.new_doc("DocType")
        doc.name = name
        action = "Created"

    for key in ["module", "custom", "istable", "issingle", "is_submittable", "track_changes", "allow_rename", "autoname", "title_field", "search_fields"]:
        if key in spec:
            doc.set(key, spec[key])

    _dedupe_fields(doc)
    existing = {row.fieldname: row for row in doc.fields if row.fieldname}

    for field_spec in spec.get("fields", []):
        fieldname = field_spec.get("fieldname")
        if fieldname and fieldname in existing:
            row = existing[fieldname]
            for key, value in field_spec.items():
                row.set(key, value)
        else:
            doc.append("fields", field_spec)

    if not spec.get("istable"):
        _ensure_permission(doc)

    doc.flags.ignore_permissions = True
    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    frappe.db.updatedb(name)
    frappe.db.commit()
    return action, name


def _find_parent_asset_account():
    for name in ["Current Assets - C", "Bank Accounts - C", "Cash In Hand - C"]:
        if frappe.db.exists("Account", name):
            return name
    frappe.throw("No suitable parent asset account was found.")


def _ensure_account(account_name, parent_account, is_group=0):
    existing = frappe.db.get_value("Account", {"account_name": account_name, "company": COMPANY}, "name")
    if existing:
        return existing

    doc = frappe.new_doc("Account")
    doc.account_name = account_name
    doc.company = COMPANY
    doc.parent_account = parent_account
    doc.is_group = is_group
    doc.root_type = "Asset"
    doc.report_type = "Balance Sheet"
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name


def _ensure_clearing_accounts():
    parent = _find_parent_asset_account()
    group_name = _ensure_account("Payment Clearing Accounts", parent, is_group=1)
    accounts = {}
    for config in CLEARING_CONFIGS:
        accounts[config["mode_of_payment"]] = _ensure_account(config["account_name"], group_name, is_group=0)
    frappe.db.commit()
    return accounts


def _find_fee_parent():
    for name in ["Indirect Expenses - C", "Expenses - C"]:
        if frappe.db.exists("Account", name):
            return name
    return None


def _ensure_fee_account():
    parent = _find_fee_parent()
    if not parent:
        return None

    existing = frappe.db.get_value("Account", {"account_name": "Payment Processing Fees", "company": COMPANY}, "name")
    if existing:
        return existing

    doc = frappe.new_doc("Account")
    doc.account_name = "Payment Processing Fees"
    doc.company = COMPANY
    doc.parent_account = parent
    doc.is_group = 0
    doc.root_type = "Expense"
    doc.report_type = "Profit and Loss"
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


def _upsert_setup(config, clearing_account, fee_account):
    existing = frappe.db.get_value("Payment Method Clearing Setup", {"company": COMPANY, "mode_of_payment": config["mode_of_payment"]}, "name")
    if existing:
        doc = frappe.get_doc("Payment Method Clearing Setup", existing)
        action = "Updated"
    else:
        doc = frappe.new_doc("Payment Method Clearing Setup")
        action = "Created"

    doc.company = COMPANY
    doc.mode_of_payment = config["mode_of_payment"]
    doc.clearing_account = clearing_account
    doc.destination_account = config["destination_account"]
    doc.settlement_policy = config["settlement_policy"]
    doc.fee_account = fee_account
    doc.enabled = 1
    doc.flags.ignore_permissions = True
    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    return action, doc.name


def _update_mode_of_payment_account(mode_of_payment, account):
    doc = frappe.get_doc("Mode of Payment", mode_of_payment)
    row = None
    for account_row in doc.accounts:
        if account_row.company == COMPANY:
            row = account_row
            break
    if not row:
        row = doc.append("accounts", {"company": COMPANY})
    row.default_account = account
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def install():
    results = {"doctypes": [], "accounts": {}, "setups": [], "mode_of_payment_updates": []}

    # Child first, then parents.
    for name in ["Shift Payment Reconciliation Item", "Payment Method Clearing Setup", "Shift Payment Reconciliation", "Shift Cash Movement"]:
        results["doctypes"].append(_upsert_doctype(name, DOCTYPE_SPECS[name]))

    clearing_accounts = _ensure_clearing_accounts()
    fee_account = _ensure_fee_account()
    results["accounts"] = {"clearing_accounts": clearing_accounts, "fee_account": fee_account}

    for config in CLEARING_CONFIGS:
        mode = config["mode_of_payment"]
        if not frappe.db.exists("Mode of Payment", mode):
            frappe.throw("Mode of Payment not found: " + mode)
        if not frappe.db.exists("Account", config["destination_account"]):
            frappe.throw("Destination account not found: " + config["destination_account"])

        clearing_account = clearing_accounts[mode]
        results["setups"].append(_upsert_setup(config, clearing_account, fee_account))
        _update_mode_of_payment_account(mode, clearing_account)
        results["mode_of_payment_updates"].append({"mode_of_payment": mode, "default_account": clearing_account})

    frappe.db.commit()
    frappe.clear_cache()
    print("Shift payment clearing foundation installed successfully.")
    print(results)
    return results


def verify():
    result = {"doctypes": {}, "accounts": {}, "setups": [], "mode_of_payment_accounts": []}

    for name in DOCTYPE_SPECS:
        result["doctypes"][name] = bool(frappe.db.exists("DocType", name))

    for config in CLEARING_CONFIGS:
        mode = config["mode_of_payment"]
        result["accounts"][mode] = frappe.db.get_value("Account", {"account_name": config["account_name"], "company": COMPANY}, "name")
        result["setups"].append(
            frappe.db.get_value(
                "Payment Method Clearing Setup",
                {"company": COMPANY, "mode_of_payment": mode},
                ["name", "clearing_account", "destination_account", "settlement_policy", "enabled"],
                as_dict=True,
            )
        )

        mode_doc = frappe.get_doc("Mode of Payment", mode)
        default_account = None
        for row in mode_doc.accounts:
            if row.company == COMPANY:
                default_account = row.default_account
                break
        result["mode_of_payment_accounts"].append({"mode_of_payment": mode, "default_account": default_account})

    print(result)
    return result


def restore_original_mode_of_payment_accounts():
    original = {
        "Insta Pay": "CIB - C",
        "Wallet": "Smart Wallet - C",
        "Credit Card": "QNB - C",
    }
    for mode, account in original.items():
        _update_mode_of_payment_account(mode, account)
    frappe.db.commit()
    frappe.clear_cache()
    print("Original Mode of Payment accounts restored.")
    return original
