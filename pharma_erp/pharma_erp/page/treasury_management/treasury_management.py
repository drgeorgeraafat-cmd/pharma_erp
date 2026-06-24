import frappe
from frappe import _
from frappe.utils import cint, flt


@frappe.whitelist()
def get_overview():
    """Return the treasury foundation summary and current cash drawer setup."""
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
    }


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
    rows = frappe.get_all(
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
    return rows


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


def _validate_access():
    roles = set(frappe.get_roles(frappe.session.user))
    if roles.intersection({"System Manager", "Accounts Manager"}):
        return

    if not frappe.has_permission("Account", ptype="read"):
        frappe.throw(
            _("You are not permitted to view Treasury Management."),
            frappe.PermissionError,
        )
