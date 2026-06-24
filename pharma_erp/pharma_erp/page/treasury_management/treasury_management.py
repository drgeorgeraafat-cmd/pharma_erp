import re

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from erpnext.accounts.utils import get_balance_on


CREATE_ROLES = {"System Manager", "Accounts Manager"}


@frappe.whitelist()
def get_overview():
    """Return the treasury summary and current cash drawer setup."""
    _validate_access()

    drawers = _get_cash_drawers()
    cash_accounts = _get_operational_cash_accounts()
    account_warnings = _get_cash_account_warnings()
    banks = _get_bank_accounts()
    bank_ledger_accounts = _get_bank_ledger_accounts()
    unlinked_bank_ledgers = _get_unlinked_bank_ledgers(bank_ledger_accounts, banks)

    return {
        "ok": True,
        "message": _("Treasury Management is working successfully."),
        "user": frappe.session.user,
        "companies": frappe.db.count("Company"),
        "cash_drawers": len(drawers),
        "cash_ledger_accounts": len(cash_accounts),
        "bank_institutions": frappe.db.count("Bank"),
        "bank_accounts": len(banks),
        "bank_ledger_accounts": len(bank_ledger_accounts),
        "card_terminals": _safe_count("Card POS Terminal"),
        "clearing_setups": _safe_count("Payment Method Clearing Setup"),
        "drawers": drawers,
        "cash_accounts": cash_accounts,
        "account_warnings": account_warnings,
        "banks": banks,
        "bank_ledger_accounts_list": bank_ledger_accounts,
        "unlinked_bank_ledgers": unlinked_bank_ledgers,
        "can_create_cash_drawer": _can_create_cash_drawer(),
        "can_manage_cash_drawer": _can_create_cash_drawer(),
        "can_create_bank": _can_create_cash_drawer(),
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


@frappe.whitelist()
def get_cash_drawer_activity(drawer_name, limit=20):
    """Return the live balance and latest posted ledger movements for a drawer."""
    _validate_access()

    drawer_name = str(drawer_name or "").strip()
    if not drawer_name or not frappe.db.exists("Cash Drawer", drawer_name):
        frappe.throw(_("Cash Drawer was not found."))

    drawer = frappe.get_doc("Cash Drawer", drawer_name)
    if not drawer.cash_account:
        frappe.throw(_("The Cash Drawer has no Cash Account."))

    limit = max(1, min(cint(limit) or 20, 100))
    account = _validate_drawer_account(drawer)
    balance = _account_balance(drawer.cash_account, drawer.company)

    rows = frappe.get_all(
        "GL Entry",
        filters={
            "account": drawer.cash_account,
            "is_cancelled": 0,
        },
        fields=[
            "name",
            "posting_date",
            "creation",
            "voucher_type",
            "voucher_no",
            "debit",
            "credit",
            "against",
            "remarks",
        ],
        order_by="posting_date desc, creation desc",
        limit_page_length=limit,
    )

    for row in rows:
        row["debit"] = flt(row.get("debit"))
        row["credit"] = flt(row.get("credit"))
        row["net_movement"] = flt(row["debit"] - row["credit"])

    return {
        "drawer": drawer.name,
        "drawer_name": drawer.drawer_name,
        "company": drawer.company,
        "cash_account": drawer.cash_account,
        "account_currency": account.get("account_currency") or "",
        "enabled": cint(drawer.enabled),
        "current_active_shift": drawer.current_active_shift or "",
        "current_responsible_user": drawer.current_responsible_user or "",
        "current_balance": balance,
        "movements": rows,
    }


@frappe.whitelist()
def set_cash_drawer_enabled(drawer_name, enabled):
    """Enable or disable a drawer without disabling its ledger account."""
    _validate_create_access()

    drawer_name = str(drawer_name or "").strip()
    if not drawer_name or not frappe.db.exists("Cash Drawer", drawer_name):
        frappe.throw(_("Cash Drawer was not found."))

    drawer = frappe.get_doc("Cash Drawer", drawer_name)
    enabled = cint(enabled)

    if enabled:
        _validate_drawer_account(drawer)
    else:
        open_shift = _find_open_shift_for_drawer(drawer)
        if open_shift:
            frappe.throw(
                _("Cannot disable this drawer while shift {0} is still open.").format(
                    open_shift
                )
            )

        # Clear stale operational links only after proving that no open shift exists.
        drawer.current_active_shift = None
        drawer.current_responsible_user = None

    if cint(drawer.enabled) != enabled:
        drawer.enabled = enabled
        drawer.flags.ignore_permissions = True
        drawer.save(ignore_permissions=True)
        drawer.add_comment(
            "Comment",
            _("Cash Drawer {0} from Treasury Management.").format(
                _("enabled") if enabled else _("disabled")
            ),
        )

    return {
        "drawer": drawer.name,
        "enabled": cint(drawer.enabled),
        "message": _("Cash Drawer status was updated successfully."),
    }



@frappe.whitelist()
def get_bank_creation_options(company=None):
    """Return safe defaults for registering a bank and its accounting records."""
    _validate_create_access()

    company = _resolve_company(company)
    currency = frappe.db.get_value("Company", company, "default_currency") or ""
    bank_parents = _bank_parent_accounts(company)
    clearing_parents = _clearing_parent_accounts(company)
    fee_parents = _fee_parent_accounts(company)

    return {
        "company": company,
        "account_currency": currency,
        "default_bank_parent_account": bank_parents[0]["name"] if bank_parents else "",
        "default_clearing_parent_account": clearing_parents[0]["name"] if clearing_parents else "",
        "default_fee_parent_account": fee_parents[0]["name"] if fee_parents else "",
        "unlinked_bank_accounts": _get_unlinked_bank_ledgers(),
    }


@frappe.whitelist()
def preview_bank_setup(
    bank_name,
    company,
    bank_account_name,
    ledger_mode="Create New Account",
    existing_ledger_account=None,
    ledger_account_name=None,
    bank_parent_account=None,
    swift_number=None,
    website=None,
    bank_account_no=None,
    iban=None,
    branch_code=None,
    create_card_clearing=1,
    card_clearing_name=None,
    create_instapay_clearing=0,
    instapay_clearing_name=None,
    clearing_parent_account=None,
    create_fee_account=1,
    fee_account_name=None,
    fee_parent_account=None,
    **kwargs,
):
    """Validate and preview a bank setup without writing any records."""
    _validate_create_access()
    return _prepare_bank_setup_payload(
        bank_name=bank_name,
        company=company,
        bank_account_name=bank_account_name,
        ledger_mode=ledger_mode,
        existing_ledger_account=existing_ledger_account,
        ledger_account_name=ledger_account_name,
        bank_parent_account=bank_parent_account,
        swift_number=swift_number,
        website=website,
        bank_account_no=bank_account_no,
        iban=iban,
        branch_code=branch_code,
        create_card_clearing=create_card_clearing,
        card_clearing_name=card_clearing_name,
        create_instapay_clearing=create_instapay_clearing,
        instapay_clearing_name=instapay_clearing_name,
        clearing_parent_account=clearing_parent_account,
        create_fee_account=create_fee_account,
        fee_account_name=fee_account_name,
        fee_parent_account=fee_parent_account,
    )


@frappe.whitelist()
def create_bank_setup(
    bank_name,
    company,
    bank_account_name,
    ledger_mode="Create New Account",
    existing_ledger_account=None,
    ledger_account_name=None,
    bank_parent_account=None,
    swift_number=None,
    website=None,
    bank_account_no=None,
    iban=None,
    branch_code=None,
    create_card_clearing=1,
    card_clearing_name=None,
    create_instapay_clearing=0,
    instapay_clearing_name=None,
    clearing_parent_account=None,
    create_fee_account=1,
    fee_account_name=None,
    fee_parent_account=None,
    **kwargs,
):
    """Create or reuse the bank master, then create its linked company Bank Account."""
    _validate_create_access()
    payload = _prepare_bank_setup_payload(
        bank_name=bank_name,
        company=company,
        bank_account_name=bank_account_name,
        ledger_mode=ledger_mode,
        existing_ledger_account=existing_ledger_account,
        ledger_account_name=ledger_account_name,
        bank_parent_account=bank_parent_account,
        swift_number=swift_number,
        website=website,
        bank_account_no=bank_account_no,
        iban=iban,
        branch_code=branch_code,
        create_card_clearing=create_card_clearing,
        card_clearing_name=card_clearing_name,
        create_instapay_clearing=create_instapay_clearing,
        instapay_clearing_name=instapay_clearing_name,
        clearing_parent_account=clearing_parent_account,
        create_fee_account=create_fee_account,
        fee_account_name=fee_account_name,
        fee_parent_account=fee_parent_account,
    )

    if payload["bank_master_action"] == "create":
        bank = frappe.new_doc("Bank")
        bank.bank_name = payload["bank_name"]
        bank.swift_number = payload["swift_number"] or None
        bank.website = payload["website"] or None
        bank.flags.ignore_permissions = True
        bank.insert(ignore_permissions=True)
        bank_name_value = bank.name
    else:
        bank_name_value = payload["bank_name"]

    if payload["ledger_account"]["action"] == "create":
        ledger_account = _create_account_from_plan(payload["ledger_account"])
    else:
        ledger_account = payload["ledger_account"]["document_name"]

    bank_account = frappe.new_doc("Bank Account")
    bank_account.account_name = payload["bank_account_name"]
    bank_account.bank = bank_name_value
    bank_account.account = ledger_account
    bank_account.company = payload["company"]
    bank_account.is_company_account = 1
    bank_account.disabled = 0
    bank_account.bank_account_no = payload["bank_account_no"] or None
    bank_account.iban = payload["iban"] or None
    bank_account.branch_code = payload["branch_code"] or None
    bank_account.flags.ignore_permissions = True
    bank_account.insert(ignore_permissions=True)

    created_accounts = {"bank_ledger_account": ledger_account}
    for key in ("card_clearing_account", "instapay_clearing_account", "fee_account"):
        plan = payload.get(key)
        if not plan:
            continue
        created_accounts[key] = (
            _create_account_from_plan(plan)
            if plan["action"] == "create"
            else plan["document_name"]
        )

    bank_account.add_comment(
        "Comment",
        _("Created from Treasury Management and linked to ledger account {0}.").format(
            ledger_account
        ),
    )

    return {
        "ok": True,
        "bank": bank_name_value,
        "bank_account": bank_account.name,
        "ledger_account": ledger_account,
        "accounts": created_accounts,
        "message": _("Bank setup was created successfully."),
    }


@frappe.whitelist()
def get_bank_account_activity(bank_account_name, limit=20):
    """Return balance and latest ledger movements for an ERPNext Bank Account."""
    _validate_access()

    bank_account_name = str(bank_account_name or "").strip()
    if not bank_account_name or not frappe.db.exists("Bank Account", bank_account_name):
        frappe.throw(_("Bank Account was not found."))

    bank_account = frappe.get_doc("Bank Account", bank_account_name)
    if not bank_account.account:
        frappe.throw(_("The Bank Account is not linked to a company ledger account."))

    account = _validate_company_account(
        bank_account.account,
        bank_account.company,
        expected_root="Asset",
        expected_type="Bank",
        label=_("Bank Ledger Account"),
    )
    limit = max(1, min(cint(limit) or 20, 100))
    movements = frappe.get_all(
        "GL Entry",
        filters={"account": bank_account.account, "is_cancelled": 0},
        fields=[
            "name",
            "posting_date",
            "creation",
            "voucher_type",
            "voucher_no",
            "debit",
            "credit",
            "against",
            "remarks",
        ],
        order_by="posting_date desc, creation desc",
        limit_page_length=limit,
    )
    for row in movements:
        row["debit"] = flt(row.get("debit"))
        row["credit"] = flt(row.get("credit"))
        row["net_movement"] = flt(row["debit"] - row["credit"])

    return {
        "bank_account": bank_account.name,
        "account_name": bank_account.account_name,
        "bank": bank_account.bank,
        "company": bank_account.company,
        "ledger_account": bank_account.account,
        "account_currency": account.get("account_currency") or "",
        "current_balance": _account_balance(bank_account.account, bank_account.company),
        "disabled": cint(bank_account.disabled),
        "bank_account_no": bank_account.bank_account_no or "",
        "iban": bank_account.iban or "",
        "movements": movements,
    }


def _prepare_bank_setup_payload(
    bank_name,
    company,
    bank_account_name,
    ledger_mode="Create New Account",
    existing_ledger_account=None,
    ledger_account_name=None,
    bank_parent_account=None,
    swift_number=None,
    website=None,
    bank_account_no=None,
    iban=None,
    branch_code=None,
    create_card_clearing=1,
    card_clearing_name=None,
    create_instapay_clearing=0,
    instapay_clearing_name=None,
    clearing_parent_account=None,
    create_fee_account=1,
    fee_account_name=None,
    fee_parent_account=None,
):
    bank_name = str(bank_name or "").strip()
    company = _resolve_company(company)
    bank_account_name = str(bank_account_name or "").strip()
    ledger_mode = str(ledger_mode or "Create New Account").strip()
    swift_number = str(swift_number or "").strip()
    website = str(website or "").strip()
    bank_account_no = str(bank_account_no or "").strip()
    iban = str(iban or "").strip().replace(" ", "").upper()
    branch_code = str(branch_code or "").strip()
    account_currency = frappe.db.get_value("Company", company, "default_currency") or ""

    if not bank_name:
        frappe.throw(_("Bank Name is required."))
    if not bank_account_name:
        frappe.throw(_("Bank Account Name is required."))

    if frappe.db.exists("Bank Account", {"company": company, "account_name": bank_account_name}):
        frappe.throw(_("A Bank Account with this name already exists for the company."))
    if bank_account_no and frappe.db.exists(
        "Bank Account", {"bank": bank_name, "bank_account_no": bank_account_no}
    ):
        frappe.throw(_("This bank account number is already registered."))
    if iban and frappe.db.exists("Bank Account", {"iban": iban}):
        frappe.throw(_("This IBAN is already registered."))

    bank_master_action = "reuse" if frappe.db.exists("Bank", bank_name) else "create"

    use_existing = ledger_mode.lower().startswith("use") or ledger_mode.lower() == "existing"
    if use_existing:
        existing_ledger_account = str(existing_ledger_account or "").strip()
        if not existing_ledger_account:
            frappe.throw(_("Select an existing Bank ledger account."))
        account = _validate_company_account(
            existing_ledger_account,
            company,
            expected_root="Asset",
            expected_type="Bank",
            label=_("Bank Ledger Account"),
        )
        linked = frappe.db.get_value("Bank Account", {"account": existing_ledger_account}, "name")
        if linked:
            frappe.throw(
                _("This ledger account is already linked to Bank Account {0}.").format(linked)
            )
        ledger_plan = {
            "action": "reuse",
            "document_name": account.name,
            "account_name": account.account_name,
            "company": company,
            "parent_account": account.parent_account,
            "account_currency": account.account_currency or account_currency,
            "root_type": account.root_type,
            "account_type": account.account_type,
        }
    else:
        ledger_account_name = str(ledger_account_name or "").strip()
        bank_parent_account = str(bank_parent_account or "").strip()
        if not ledger_account_name:
            frappe.throw(_("Bank Ledger Account Name is required."))
        if not bank_parent_account:
            frappe.throw(_("Bank Parent Account is required."))
        duplicate = frappe.db.get_value(
            "Account", {"company": company, "account_name": ledger_account_name}, "name"
        )
        if duplicate:
            frappe.throw(
                _("Account {0} already exists. Choose Use Existing Account instead.").format(
                    duplicate
                )
            )
        _validate_parent_account(bank_parent_account, company, "Asset")
        ledger_plan = {
            "action": "create",
            "document_name": "",
            "account_name": ledger_account_name,
            "company": company,
            "parent_account": bank_parent_account,
            "account_currency": account_currency,
            "root_type": "Asset",
            "account_type": "Bank",
        }

    payload = {
        "bank_name": bank_name,
        "bank_master_action": bank_master_action,
        "swift_number": swift_number,
        "website": website,
        "company": company,
        "account_currency": account_currency,
        "bank_account_name": bank_account_name,
        "bank_account_no": bank_account_no,
        "iban": iban,
        "branch_code": branch_code,
        "ledger_mode": "existing" if use_existing else "create",
        "ledger_account": ledger_plan,
    }

    create_card_clearing = cint(create_card_clearing)
    create_instapay_clearing = cint(create_instapay_clearing)
    create_fee_account = cint(create_fee_account)

    if create_card_clearing or create_instapay_clearing:
        clearing_parent_account = str(clearing_parent_account or "").strip()
        if not clearing_parent_account:
            frappe.throw(_("Clearing Parent Account is required."))
        _validate_parent_account(clearing_parent_account, company, "Asset")

    if create_card_clearing:
        payload["card_clearing_account"] = _plan_reusable_account(
            card_clearing_name or f"{bank_name} Card Clearing",
            company,
            clearing_parent_account,
            account_currency,
            root_type="Asset",
            account_type="",
        )

    if create_instapay_clearing:
        payload["instapay_clearing_account"] = _plan_reusable_account(
            instapay_clearing_name or f"{bank_name} InstaPay Clearing",
            company,
            clearing_parent_account,
            account_currency,
            root_type="Asset",
            account_type="",
        )

    if create_fee_account:
        fee_parent_account = str(fee_parent_account or "").strip()
        if not fee_parent_account:
            frappe.throw(_("Fee Parent Account is required."))
        _validate_parent_account(fee_parent_account, company, "Expense")
        payload["fee_account"] = _plan_reusable_account(
            fee_account_name or f"{bank_name} Bank Charges",
            company,
            fee_parent_account,
            account_currency,
            root_type="Expense",
            account_type="",
        )

    return payload


def _plan_reusable_account(
    account_name,
    company,
    parent_account,
    account_currency,
    root_type,
    account_type="",
):
    account_name = str(account_name or "").strip()
    if not account_name:
        frappe.throw(_("Account Name is required."))

    existing = frappe.db.get_value(
        "Account", {"company": company, "account_name": account_name}, "name"
    )
    if existing:
        account = _validate_company_account(
            existing,
            company,
            expected_root=root_type,
            expected_type=None,
            label=_("Account"),
        )
        return {
            "action": "reuse",
            "document_name": account.name,
            "account_name": account.account_name,
            "company": company,
            "parent_account": account.parent_account,
            "account_currency": account.account_currency or account_currency,
            "root_type": account.root_type,
            "account_type": account.account_type or "",
        }

    return {
        "action": "create",
        "document_name": "",
        "account_name": account_name,
        "company": company,
        "parent_account": parent_account,
        "account_currency": account_currency,
        "root_type": root_type,
        "account_type": account_type,
    }


def _create_account_from_plan(plan):
    account = frappe.new_doc("Account")
    account.account_name = plan["account_name"]
    account.company = plan["company"]
    account.parent_account = plan["parent_account"]
    account.is_group = 0
    account.account_type = plan.get("account_type") or ""
    account.account_currency = plan.get("account_currency") or ""
    account.flags.ignore_permissions = True
    account.insert(ignore_permissions=True)
    return account.name


def _validate_parent_account(account_name, company, root_type):
    account = frappe.db.get_value(
        "Account",
        account_name,
        ["name", "company", "is_group", "disabled", "root_type"],
        as_dict=True,
    )
    if not account:
        frappe.throw(_("Parent Account was not found."))
    if account.company != company:
        frappe.throw(_("Parent Account belongs to another company."))
    if not cint(account.is_group):
        frappe.throw(_("Parent Account must be a group account."))
    if cint(account.disabled):
        frappe.throw(_("Parent Account is disabled."))
    if account.root_type != root_type:
        frappe.throw(
            _("Parent Account must be under the {0} root.").format(root_type)
        )
    return account


def _validate_company_account(
    account_name,
    company,
    expected_root=None,
    expected_type=None,
    label=None,
):
    account = frappe.db.get_value(
        "Account",
        account_name,
        [
            "name",
            "account_name",
            "company",
            "parent_account",
            "is_group",
            "disabled",
            "root_type",
            "account_type",
            "account_currency",
        ],
        as_dict=True,
    )
    label = label or _("Account")
    if not account:
        frappe.throw(_("{0} was not found.").format(label))
    if account.company != company:
        frappe.throw(_("{0} belongs to another company.").format(label))
    if cint(account.is_group):
        frappe.throw(_("{0} cannot be a group account.").format(label))
    if cint(account.disabled):
        frappe.throw(_("{0} is disabled.").format(label))
    if expected_root and account.root_type != expected_root:
        frappe.throw(
            _("{0} must be under the {1} root.").format(label, expected_root)
        )
    if expected_type and account.account_type != expected_type:
        frappe.throw(
            _("{0} must have Account Type {1}.").format(label, expected_type)
        )
    return account

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
            row["current_balance"] = _account_balance(
                row.cash_account, row.company
            )
            last_movement = frappe.get_all(
                "GL Entry",
                filters={
                    "account": row.cash_account,
                    "is_cancelled": 0,
                },
                fields=["posting_date", "creation", "voucher_type", "voucher_no"],
                order_by="posting_date desc, creation desc",
                limit_page_length=1,
            )
            row["last_movement"] = last_movement[0] if last_movement else {}
        else:
            row["account_currency"] = ""
            row["account_disabled"] = 0
            row["account_root_type"] = ""
            row["current_balance"] = 0
            row["last_movement"] = {}

    return rows


def _account_balance(account, company):
    if not account:
        return 0
    try:
        return flt(
            get_balance_on(
                account=account,
                date=nowdate(),
                company=company,
                in_account_currency=True,
            )
        )
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Treasury Management Cash Drawer Balance",
        )
        return 0


def _validate_drawer_account(drawer):
    account = frappe.db.get_value(
        "Account",
        drawer.cash_account,
        [
            "name",
            "company",
            "is_group",
            "disabled",
            "root_type",
            "account_type",
            "account_currency",
        ],
        as_dict=True,
    )
    if not account:
        frappe.throw(_("Cash Account was not found."))
    if account.company != drawer.company:
        frappe.throw(_("Cash Account belongs to another company."))
    if cint(account.is_group):
        frappe.throw(_("Cash Account cannot be a group account."))
    if cint(account.disabled):
        frappe.throw(_("Cash Account is disabled."))
    if account.root_type != "Asset" or account.account_type != "Cash":
        frappe.throw(_("Linked account must be an active Asset Cash account."))
    return account


def _find_open_shift_for_drawer(drawer):
    if not frappe.db.exists("DocType", "Pharmacy Shift Closing"):
        return None

    meta = frappe.get_meta("Pharmacy Shift Closing")
    fields = ["name", "docstatus"]
    for fieldname in (
        "status",
        "end_time",
        "custom_shift_operational_status",
        "custom_cash_drawer",
    ):
        if meta.has_field(fieldname):
            fields.append(fieldname)

    names = []
    if drawer.current_active_shift and frappe.db.exists(
        "Pharmacy Shift Closing", drawer.current_active_shift
    ):
        names.append(drawer.current_active_shift)

    if meta.has_field("custom_cash_drawer"):
        linked = frappe.get_all(
            "Pharmacy Shift Closing",
            filters={"custom_cash_drawer": drawer.name},
            pluck="name",
            order_by="modified desc",
            limit_page_length=20,
        )
        for name in linked:
            if name not in names:
                names.append(name)

    for name in names:
        row = frappe.db.get_value(
            "Pharmacy Shift Closing", name, fields, as_dict=True
        )
        if row and not _shift_is_clearly_closed(row):
            return row.name

    return None


def _shift_is_clearly_closed(row):
    if cint(row.get("docstatus")) == 2:
        return True
    if row.get("end_time"):
        return True

    statuses = {
        str(row.get("status") or "").strip().lower(),
        str(row.get("custom_shift_operational_status") or "").strip().lower(),
    }
    return bool(statuses.intersection({"closed", "completed", "cancelled"}))


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




def _get_bank_accounts():
    if not frappe.db.exists("DocType", "Bank Account"):
        return []

    rows = frappe.get_all(
        "Bank Account",
        fields=[
            "name",
            "account_name",
            "account",
            "bank",
            "company",
            "disabled",
            "is_default",
            "bank_account_no",
            "iban",
            "branch_code",
        ],
        order_by="company asc, bank asc, account_name asc",
        limit_page_length=500,
    )
    for row in rows:
        row["disabled"] = cint(row.get("disabled"))
        row["is_default"] = cint(row.get("is_default"))
        row["current_balance"] = 0
        row["account_currency"] = ""
        row["last_movement"] = {}
        if row.get("account"):
            account = frappe.db.get_value(
                "Account",
                row.account,
                ["account_currency", "disabled", "account_type", "root_type"],
                as_dict=True,
            ) or {}
            row["account_currency"] = account.get("account_currency") or ""
            row["ledger_disabled"] = cint(account.get("disabled"))
            row["account_type"] = account.get("account_type") or ""
            row["root_type"] = account.get("root_type") or ""
            row["current_balance"] = _account_balance(row.account, row.company)
            movement = frappe.get_all(
                "GL Entry",
                filters={"account": row.account, "is_cancelled": 0},
                fields=["posting_date", "creation", "voucher_type", "voucher_no"],
                order_by="posting_date desc, creation desc",
                limit_page_length=1,
            )
            row["last_movement"] = movement[0] if movement else {}
        if row.get("bank"):
            bank = frappe.db.get_value(
                "Bank", row.bank, ["swift_number", "website"], as_dict=True
            ) or {}
            row["swift_number"] = bank.get("swift_number") or ""
            row["website"] = bank.get("website") or ""
    return rows


def _get_bank_ledger_accounts():
    return frappe.get_all(
        "Account",
        filters={"account_type": "Bank", "is_group": 0, "disabled": 0},
        fields=[
            "name",
            "account_name",
            "company",
            "parent_account",
            "account_currency",
            "root_type",
            "disabled",
        ],
        order_by="company asc, account_name asc",
        limit_page_length=500,
    )


def _get_unlinked_bank_ledgers(bank_ledgers=None, bank_accounts=None):
    bank_ledgers = bank_ledgers if bank_ledgers is not None else _get_bank_ledger_accounts()
    bank_accounts = bank_accounts if bank_accounts is not None else _get_bank_accounts()
    linked = {str(row.get("account") or "") for row in bank_accounts}
    rows = []
    for row in bank_ledgers:
        if row.name in linked:
            continue
        item = dict(row)
        item["current_balance"] = _account_balance(row.name, row.company)
        rows.append(item)
    return rows


def _bank_parent_accounts(company):
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Asset",
            "is_group": 1,
            "disabled": 0,
        },
        fields=["name", "account_name", "account_type", "parent_account"],
        order_by="lft asc",
        limit_page_length=500,
    )
    rows.sort(
        key=lambda row: (
            0 if str(row.get("account_name") or "").lower() == "bank accounts" else
            1 if str(row.get("account_type") or "").lower() == "bank" else
            2 if "bank" in str(row.get("account_name") or "").lower() else 3,
            row.get("name") or "",
        )
    )
    return rows


def _clearing_parent_accounts(company):
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Asset",
            "is_group": 1,
            "disabled": 0,
        },
        fields=["name", "account_name", "parent_account"],
        order_by="lft asc",
        limit_page_length=500,
    )
    rows.sort(
        key=lambda row: (
            0 if "payment clearing" in str(row.get("account_name") or "").lower() else
            1 if str(row.get("account_name") or "").lower() == "current assets" else 2,
            row.get("name") or "",
        )
    )
    return rows


def _fee_parent_accounts(company):
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Expense",
            "is_group": 1,
            "disabled": 0,
        },
        fields=["name", "account_name", "parent_account"],
        order_by="lft asc",
        limit_page_length=500,
    )
    rows.sort(
        key=lambda row: (
            0 if "indirect expense" in str(row.get("account_name") or "").lower() else
            1 if str(row.get("account_name") or "").lower() == "expenses" else 2,
            row.get("name") or "",
        )
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
