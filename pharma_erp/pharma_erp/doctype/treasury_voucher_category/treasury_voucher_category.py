import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from pharma_erp.treasury_access import can_manage_treasury


ROOT_TYPE_BY_VOUCHER = {
    "General Expense": "Expense",
    "General Receipt": "Income",
}


class TreasuryVoucherCategory(Document):
    def before_insert(self):
        self._validate_manager_access()

    def validate(self):
        self._validate_manager_access()
        self.category_name = str(self.category_name or "").strip()
        self.company = str(self.company or "").strip()
        self.voucher_type = str(self.voucher_type or "").strip()
        self.default_account = str(self.default_account or "").strip()
        self.enabled = cint(self.enabled)
        self.display_order = cint(self.display_order)

        if not self.category_name:
            frappe.throw(_("Category Name is required."))
        if not self.company or not frappe.db.exists("Company", self.company):
            frappe.throw(_("Select a valid Company."))
        if self.voucher_type not in ROOT_TYPE_BY_VOUCHER:
            frappe.throw(_("Select a valid Voucher Type."))
        if not self.default_account:
            frappe.throw(_("Default Account is required."))

        allowed = []
        seen = set()
        for row in self.allowed_accounts or []:
            account = str(row.account or "").strip()
            if not account or account in seen:
                continue
            seen.add(account)
            allowed.append(account)

        if self.default_account not in seen:
            allowed.insert(0, self.default_account)

        self.set("allowed_accounts", [])
        for account in allowed:
            self._validate_account(account)
            self.append("allowed_accounts", {"account": account})

        if not self.allowed_accounts:
            frappe.throw(_("At least one Allowed Account is required."))

    def _validate_manager_access(self):
        if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
            return
        if not can_manage_treasury():
            frappe.throw(
                _("Only Treasury Manager, Accounts Manager, or System Manager can manage Treasury Voucher Categories."),
                frappe.PermissionError,
            )

    def _validate_account(self, account_name):
        account = frappe.db.get_value(
            "Account",
            account_name,
            ["company", "root_type", "is_group", "disabled"],
            as_dict=True,
        )
        if not account:
            frappe.throw(_("Account {0} was not found.").format(account_name))
        if account.company != self.company:
            frappe.throw(_("Account {0} belongs to another company.").format(account_name))
        if cint(account.is_group):
            frappe.throw(_("Account {0} cannot be a group account.").format(account_name))
        if cint(account.disabled):
            frappe.throw(_("Account {0} is disabled.").format(account_name))

        required_root = ROOT_TYPE_BY_VOUCHER[self.voucher_type]
        if account.root_type != required_root:
            frappe.throw(
                _("Account {0} must have Root Type {1} for {2}.").format(
                    account_name, required_root, self.voucher_type
                )
            )
