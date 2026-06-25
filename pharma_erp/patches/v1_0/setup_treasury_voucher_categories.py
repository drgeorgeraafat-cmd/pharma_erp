import frappe


CATEGORY_SEEDS = (
    ("Rent", "General Expense", ("Office Rent",)),
    ("Utilities", "General Expense", ("Utility Expenses", "Telephone Expenses", "كهرباء ومياة")),
    ("Maintenance", "General Expense", ("Office Maintenance Expenses",)),
    ("Office Supplies", "General Expense", ("Print and Stationery", "Postal Expenses")),
    ("Transportation", "General Expense", ("Travel Expenses", "Freight and Forwarding Charges")),
    ("Administrative Expense", "General Expense", ("Administrative Expenses", "Legal Expenses")),
    ("Marketing Expense", "General Expense", ("Marketing Expenses", "Marketing & Loyalty Expenses", "Commission on Sales")),
    ("Miscellaneous Expense", "General Expense", ("Miscellaneous Expenses", "Entertainment Expenses")),
    ("Other Expense", "General Expense", ("Miscellaneous Expenses", "Write Off")),
    ("Other Income", "General Receipt", ("Other Income",)),
    ("Cashback / Rebate", "General Receipt", ("Other Income",)),
    ("Insurance Reimbursement", "General Receipt", ("Other Income",)),
    ("Refund / Compensation", "General Receipt", ("Other Income",)),
    ("Miscellaneous Receipt", "General Receipt", ("Other Income",)),
    ("Other Receipt", "General Receipt", ("Other Income",)),
)


def execute():
    if not frappe.db.exists("DocType", "Treasury Voucher Category"):
        return

    companies = frappe.get_all("Company", pluck="name", order_by="creation asc")
    for company in companies:
        expense_accounts = _account_map(company, "Expense")
        income_accounts = _account_map(company, "Income")
        order = 10
        for category_name, voucher_type, candidate_names in CATEGORY_SEEDS:
            account_map = expense_accounts if voucher_type == "General Expense" else income_accounts
            accounts = [account_map[name] for name in candidate_names if name in account_map]
            if not accounts:
                fallback = _fallback_account(account_map, voucher_type)
                if fallback:
                    accounts = [fallback]
            if not accounts:
                continue

            name = _category_docname(category_name, company)
            if frappe.db.exists("Treasury Voucher Category", name):
                order += 10
                continue

            doc = frappe.new_doc("Treasury Voucher Category")
            doc.category_name = name
            doc.company = company
            doc.voucher_type = voucher_type
            doc.enabled = 1
            doc.display_order = order
            doc.default_account = accounts[0]
            doc.notes = "Default category created by Pharma ERP migration."
            for account in accounts:
                doc.append("allowed_accounts", {"account": account})
            doc.flags.ignore_permissions = True
            doc.insert(ignore_permissions=True)
            order += 10


def _account_map(company, root_type):
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": root_type,
            "is_group": 0,
            "disabled": 0,
        },
        fields=["name", "account_name"],
        order_by="name asc",
    )
    return {row.account_name: row.name for row in rows if row.account_name}


def _fallback_account(account_map, voucher_type):
    preferred = (
        ("Miscellaneous Expenses", "Administrative Expenses")
        if voucher_type == "General Expense"
        else ("Other Income",)
    )
    for account_name in preferred:
        if account_name in account_map:
            return account_map[account_name]
    return next(iter(account_map.values()), None)


def _category_docname(category_name, company):
    existing = frappe.db.get_value(
        "Treasury Voucher Category", category_name, ["name", "company"], as_dict=True
    )
    if not existing or existing.company == company:
        return category_name
    abbr = frappe.db.get_value("Company", company, "abbr") or company
    return f"{category_name} - {abbr}"
