import re

import frappe
from frappe import _
from frappe.utils import cint, flt


CREATE_ROLES = {"System Manager", "Accounts Manager"}


@frappe.whitelist()
def get_overview():
    """Return the treasury summary and current cash drawer setup."""
    _validate_access()

    drawers = _get_cash_drawers()
    cash_accounts = _get_operational_cash_accounts()
    account_warnings = _get_cash_account_warnings()

    return {
        "ok": True,
        "message": _("Treasury Management is working successfully."),
        "user": frappe.session.user,
        "companies": frappe.db.count("Company"),
        "cash_drawers": len(drawers),
        "cash_ledger_accounts": len(cash_accounts),
        "bank_accounts": frappe.db.count("Bank Account"),
        "bank_ledger_accounts": _count_leaf_accounts("Bank"),
        "card_terminals": _safe_count("Card POS Terminal"),
        "clearing_setups": _safe_count("Payment Method Clearing Setup"),
        "drawers": drawers,
        "cash_accounts": cash_accounts,
        "account_warnings": account_warnings,
        "can_create_cash_drawer": _can_create_cash_drawer(),
    }


@frappe.whitelist()
def get_cash_drawer_creation_options(company=None):
    """Return safe defaults for the create-cash-drawer dialog."""
    _validate_create_access()

    company = _resolve_company(company)
    currency = frappe.db.get_value("Company", company, "default_currency") or ""
    parent_accounts = _cash_parent_accounts(company)

    return {
        "company": company,
        "account_currency": currency,
        "suggested_drawer_code": _next_drawer_code(),
        "default_parent_account": parent_accounts[0]["name"] if parent_accounts else "",
        "parent_accounts": parent_accounts,
    }


@frappe.whitelist()
def preview_cash_drawer(
    drawer_name,
    drawer_code,
    company,
    account_name,
    parent_account,
    branch=None,
    physical_location=None,
    default_opening_float=0,
    **kwargs,
):
    """Validate and return exactly what will be created, without writing data."""
    _validate_create_access()
    return _prepare_cash_drawer_payload(
        drawer_name=drawer_name,
        drawer_code=drawer_code,
        company=company,
        account_name=account_name,
        parent_account=parent_account,
        branch=branch,
        physical_location=physical_location,
        default_opening_float=default_opening_float,
    )


@frappe.whitelist()
def create_cash_drawer(
    drawer_name,
    drawer_code,
    company,
    account_name,
    parent_account,
    branch=None,
    physical_location=None,
    default_opening_float=0,
    **kwargs,
):
    """Create a Cash account and its Cash Drawer after final server validation."""
    _validate_create_access()

    payload = _prepare_cash_drawer_payload(
        drawer_name=drawer_name,
        drawer_code=drawer_code,
        company=company,
        account_name=account_name,
        parent_account=parent_account,
        branch=branch,
        physical_location=physical_location,
        default_opening_float=default_opening_float,
    )

    account = frappe.new_doc("Account")
    account.account_name = payload["account_name"]
    account.company = payload["company"]
    account.parent_account = payload["parent_account"]
    account.is_group = 0
    account.account_type = "Cash"
    account.account_currency = payload["account_currency"]
    account.flags.ignore_permissions = True
    account.insert(ignore_permissions=True)

    drawer = frappe.new_doc("Cash Drawer")
    drawer.drawer_name = payload["drawer_name"]
    drawer.drawer_code = payload["drawer_code"]
    drawer.company = payload["company"]
    drawer.branch = payload["branch"] or None
    drawer.physical_location = payload["physical_location"] or None
    drawer.enabled = 1
    drawer.cash_account = account.name
    drawer.default_opening_float = payload["default_opening_float"]
    drawer.flags.ignore_permissions = True
    drawer.insert(ignore_permissions=True)

    drawer.add_comment(
        "Comment",
        _("Created from Treasury Management with cash account {0}.").format(account.name),
    )

    return {
        "ok": True,
        "drawer": drawer.name,
        "drawer_name": drawer.drawer_name,
        "cash_account": account.name,
        "message": _("Cash drawer and cash account were created successfully."),
    }


def _prepare_cash_drawer_payload(
    drawer_name,
    drawer_code,
    company,
    account_name,
    parent_account,
    branch=None,
    physical_location=None,
    default_opening_float=0,
):
    drawer_name = str(drawer_name or "").strip()
    drawer_code = _normalize_drawer_code(drawer_code)
    company = _resolve_company(company)
    account_name = str(account_name or "").strip()
    parent_account = str(parent_account or "").strip()
    branch = str(branch or "").strip()
    physical_location = str(physical_location or "").strip()
    default_opening_float = flt(default_opening_float)

    if not drawer_name:
        frappe.throw(_("Drawer Name is required."))
    if not drawer_code:
        frappe.throw(_("Drawer Code is required."))
    if not account_name:
        frappe.throw(_("Cash Account Name is required."))
    if not parent_account:
        frappe.throw(_("Parent Account is required."))
    if default_opening_float < 0:
        frappe.throw(_("Default Opening Float cannot be negative."))

    if frappe.db.exists("Cash Drawer", drawer_code):
        frappe.throw(_("Cash Drawer {0} already exists.").format(drawer_code))

    duplicate_drawer_name = frappe.db.get_value(
        "Cash Drawer",
        {"drawer_name": drawer_name, "company": company},
        "name",
    )
    if duplicate_drawer_name:
        frappe.throw(
            _("A cash drawer with this name already exists: {0}.").format(
                duplicate_drawer_name
            )
        )

    existing_account = frappe.db.get_value(
        "Account",
        {"company": company, "account_name": account_name},
        "name",
    )
    if existing_account:
        frappe.throw(
            _("An account with this name already exists: {0}.").format(existing_account)
        )

    parent = frappe.db.get_value(
        "Account",
        parent_account,
        [
            "name",
            "company",
            "is_group",
            "disabled",
            "root_type",
            "account_currency",
        ],
        as_dict=True,
    )
    if not parent:
        frappe.throw(_("Parent Account was not found."))
    if parent.company != company:
        frappe.throw(_("Parent Account belongs to another company."))
    if not cint(parent.is_group):
        frappe.throw(_("Parent Account must be a group account."))
    if cint(parent.disabled):
        frappe.throw(_("Parent Account is disabled."))
    if parent.root_type != "Asset":
        frappe.throw(_("Parent Account must be under the Asset root."))

    if branch and frappe.db.exists("DocType", "Branch"):
        branch_row = frappe.db.get_value(
            "Branch",
            branch,
            ["name", "company"],
            as_dict=True,
        )
        if not branch_row:
            frappe.throw(_("Branch was not found."))
        if branch_row.get("company") and branch_row.company != company:
            frappe.throw(_("Branch belongs to another company."))

    account_currency = (
        frappe.db.get_value("Company", company, "default_currency")
        or parent.account_currency
        or ""
    )

    return {
        "drawer_name": drawer_name,
        "drawer_code": drawer_code,
        "company": company,
        "branch": branch,
        "physical_location": physical_location,
        "default_opening_float": default_opening_float,
        "account_name": account_name,
        "parent_account": parent_account,
        "account_currency": account_currency,
        "account_type": "Cash",
        "enabled": 1,
        "creates_opening_entry": False,
    }


def _normalize_drawer_code(value):
    value = str(value or "").strip().upper()
    value = re.sub(r"[^A-Z0-9_-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-_")
    return value[:140]


def _resolve_company(company=None):
    company = str(company or "").strip()
    if not company:
        company = frappe.defaults.get_user_default("Company") or ""
    if not company:
        company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    if not company:
        companies = frappe.get_all("Company", pluck="name", limit_page_length=2)
        if len(companies) == 1:
            company = companies[0]
    if not company or not frappe.db.exists("Company", company):
        frappe.throw(_("Select a valid Company."))
    return company


def _next_drawer_code():
    rows = frappe.get_all(
        "Cash Drawer",
        fields=["drawer_code"],
        limit_page_length=1000,
    )
    highest = 0
    for row in rows:
        match = re.search(r"(\d+)$", str(row.get("drawer_code") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"DRAWER-{highest + 1:02d}"


def _cash_parent_accounts(company):
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Asset",
            "is_group": 1,
            "disabled": 0,
        },
        fields=[
            "name",
            "account_name",
            "parent_account",
            "account_currency",
            "account_type",
        ],
        order_by="lft asc",
        limit_page_length=500,
    )

    def priority(row):
        account_name = str(row.get("account_name") or "").strip().lower()
        account_type = str(row.get("account_type") or "").strip().lower()
        if account_name == "cash in hand":
            return (0, row.get("name") or "")
        if account_type == "cash":
            return (1, row.get("name") or "")
        if "cash" in account_name:
            return (2, row.get("name") or "")
        return (3, row.get("name") or "")

    rows.sort(key=priority)
    return rows


def _get_cash_drawers():
    if not frappe.db.exists("DocType", "Cash Drawer"):
        return []

    fields = [
        "name",
        "drawer_name",
        "drawer_code",
        "company",
        "branch",
        "physical_location",
        "enabled",
        "cash_account",
        "default_opening_float",
        "current_responsible_user",
        "current_active_shift",
    ]
    rows = frappe.get_all(
        "Cash Drawer",
        fields=fields,
        order_by="company asc, drawer_name asc",
        limit_page_length=500,
    )

    for row in rows:
        row["enabled"] = cint(row.get("enabled"))
        row["default_opening_float"] = flt(row.get("default_opening_float"))
        if row.get("cash_account"):
            account = frappe.db.get_value(
                "Account",
                row.cash_account,
                ["account_currency", "disabled", "root_type"],
                as_dict=True,
            ) or {}
            row["account_currency"] = account.get("account_currency") or ""
            row["account_disabled"] = cint(account.get("disabled"))
            row["account_root_type"] = account.get("root_type") or ""
        else:
            row["account_currency"] = ""
            row["account_disabled"] = 0
            row["account_root_type"] = ""

    return rows


def _get_operational_cash_accounts():
    fields = [
        "name",
        "account_name",
        "company",
        "parent_account",
        "account_currency",
        "disabled",
        "root_type",
    ]
    return frappe.get_all(
        "Account",
        filters={
            "account_type": "Cash",
            "root_type": "Asset",
            "is_group": 0,
            "disabled": 0,
        },
        fields=fields,
        order_by="company asc, account_name asc",
        limit_page_length=500,
    )


def _get_cash_account_warnings():
    return frappe.get_all(
        "Account",
        filters={
            "account_type": "Cash",
            "root_type": ["!=", "Asset"],
            "is_group": 0,
        },
        fields=[
            "name",
            "account_name",
            "company",
            "parent_account",
            "root_type",
            "disabled",
        ],
        order_by="company asc, account_name asc",
        limit_page_length=100,
    )


def _count_leaf_accounts(account_type):
    return frappe.db.count(
        "Account",
        filters={
            "account_type": account_type,
            "is_group": 0,
            "disabled": 0,
        },
    )


def _safe_count(doctype):
    if not frappe.db.exists("DocType", doctype):
        return 0
    return frappe.db.count(doctype)


def _can_create_cash_drawer():
    return bool(CREATE_ROLES.intersection(set(frappe.get_roles(frappe.session.user))))


def _validate_create_access():
    if _can_create_cash_drawer():
        return
    frappe.throw(
        _("Only System Manager or Accounts Manager can create cash drawers."),
        frappe.PermissionError,
    )


def _validate_access():
    roles = set(frappe.get_roles(frappe.session.user))
    if roles.intersection(CREATE_ROLES):
        return

    if not frappe.has_permission("Account", ptype="read"):
        frappe.throw(
            _("You are not permitted to view Treasury Management."),
            frappe.PermissionError,
        )
