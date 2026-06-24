import frappe


FIELDS = [
    {
        "label": "Cash Account",
        "fieldname": "cash_account",
        "fieldtype": "Link",
        "options": "Account",
        "insert_after": "company",
        "default": "Cashier Till - C",
        "read_only": 1,
    },
    {
        "label": "Difference Reason",
        "fieldname": "difference_reason",
        "fieldtype": "Small Text",
        "insert_after": "difference",
    },
    {
        "label": "Closed By",
        "fieldname": "closed_by",
        "fieldtype": "Link",
        "options": "User",
        "insert_after": "end_time",
        "read_only": 1,
    },
    {
        "label": "Closed At",
        "fieldname": "closed_at",
        "fieldtype": "Datetime",
        "insert_after": "closed_by",
        "read_only": 1,
    },
]


def _ensure_field(doctype_name, spec):
    doc = frappe.get_doc("DocType", doctype_name)

    existing = None

    for row in doc.fields:
        if row.fieldname == spec["fieldname"]:
            existing = row
            break

    if existing:
        for key, value in spec.items():
            existing.set(key, value)
    else:
        doc.append("fields", spec)

    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def _fix_shift_doctype():
    doc = frappe.get_doc("DocType", "Pharmacy Shift Closing")

    for row in doc.fields:
        if row.fieldname == "company":
            row.default = "Cure"
            row.reqd = 1

        elif row.fieldname == "cashier":
            row.reqd = 1

        elif row.fieldname == "total_home_delivery_sales":
            row.read_only = 1

        elif row.fieldname == "actual_cash":
            row.reqd = 0

    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def _fix_expense_child():
    doc = frappe.get_doc("DocType", "Pharmacy Shift Expense")

    for row in doc.fields:
        if row.fieldname == "employee":
            row.depends_on = 'eval:doc.transaction_type=="سلفة موظف"'

    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)


def _ensure_page_roles():
    page = frappe.get_doc("Page", "pharmacy-shift-management")
    roles = {row.role for row in page.roles}

    for role in ["System Manager"]:
        if role not in roles:
            page.append("roles", {"role": role})

    page.flags.ignore_permissions = True
    page.save(ignore_permissions=True)


def install():
    _fix_shift_doctype()

    for field in FIELDS:
        _ensure_field("Pharmacy Shift Closing", field)

    _fix_expense_child()

    frappe.db.commit()

    frappe.db.updatedb("Pharmacy Shift Closing")
    frappe.db.updatedb("Pharmacy Shift Expense")

    frappe.db.commit()
    frappe.clear_cache()

    if frappe.db.exists("Page", "pharmacy-shift-management"):
        _ensure_page_roles()
        frappe.db.commit()

    print("Pharmacy Shift Management page setup completed.")
    return verify()


def verify():
    result = {
        "page_exists": bool(
            frappe.db.exists("Page", "pharmacy-shift-management")
        ),
        "cash_account_field": bool(
            frappe.get_meta("Pharmacy Shift Closing").has_field(
                "cash_account"
            )
        ),
        "difference_reason_field": bool(
            frappe.get_meta("Pharmacy Shift Closing").has_field(
                "difference_reason"
            )
        ),
        "closed_by_field": bool(
            frappe.get_meta("Pharmacy Shift Closing").has_field(
                "closed_by"
            )
        ),
        "closed_at_field": bool(
            frappe.get_meta("Pharmacy Shift Closing").has_field(
                "closed_at"
            )
        ),
        "old_after_submit_disabled": frappe.db.get_value(
            "Server Script",
            "Pharmacy Shift ClosinG",
            "disabled",
        ),
    }

    print(result)
    return result
