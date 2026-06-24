import frappe
from frappe import _
from frappe.utils import cint


@frappe.whitelist()
def get_overview():
    """Return a small read-only summary for the first treasury page milestone."""
    _validate_access()

    return {
        "ok": True,
        "message": _("Treasury Management is working successfully."),
        "user": frappe.session.user,
        "companies": frappe.db.count("Company"),
        "bank_accounts": frappe.db.count("Bank Account"),
        "cash_accounts": _count_leaf_accounts("Cash"),
        "bank_ledger_accounts": _count_leaf_accounts("Bank"),
        "card_terminals": _safe_count("Card POS Terminal"),
        "clearing_setups": _safe_count("Payment Method Clearing Setup"),
    }


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
