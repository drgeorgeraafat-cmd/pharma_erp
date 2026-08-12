import frappe
from frappe import _

from pharma_erp.pharma_erp.branch_operational_integration import (
    resolve_operational_branch,
)
from pharma_erp.pharma_erp.payment_card_management import (
    begin_shift_review,
    cancel_cashflow_document,
    cancel_shift_review,
    close_and_open_shift,
    close_shift,
    create_card_batch,
    create_cash_action,
    create_payment_reconciliation,
    direct_close_shift,
    create_shift as _create_shift,
    get_awaiting_card_batches,
    get_card_bank_defaults,
    get_dashboard as _get_dashboard,
    get_delivery_handover_summary,
    get_invoice_items,
    get_payment_details,
    get_transferable_delivery_orders,
    refresh_card_batch,
    rollover_shift,
    submit_delivery_handover,
)


def _default_company():
    return (
        frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or "Cure"
    )


def _shift_is_active(shift_name):
    if not shift_name or not frappe.db.exists("Pharmacy Shift Closing", shift_name):
        return False

    fields = ["docstatus", "status"]
    meta = frappe.get_meta("Pharmacy Shift Closing")
    operational_field = "custom_shift_operational_status"
    if meta.has_field(operational_field):
        fields.append(operational_field)

    row = frappe.db.get_value(
        "Pharmacy Shift Closing",
        shift_name,
        fields,
        as_dict=True,
    )
    if not row or row.docstatus != 0 or row.status == "Closed":
        return False

    if operational_field in row and row.get(operational_field):
        return row.get(operational_field) == "Active"

    return True


def _cash_drawer_rows(company=None):
    company = company or _default_company()
    meta = frappe.get_meta("Cash Drawer")

    fields = ["name", "drawer_code", "drawer_name", "company", "cash_account"]
    for fieldname in [
        "physical_location",
        "current_responsible_user",
        "current_active_shift",
    ]:
        if meta.has_field(fieldname):
            fields.append(fieldname)

    rows = frappe.get_all(
        "Cash Drawer",
        filters={"company": company, "enabled": 1},
        fields=fields,
        order_by="drawer_name asc, drawer_code asc, name asc",
        limit_page_length=200,
    )

    result = []
    for row in rows:
        active_shift = row.get("current_active_shift") or ""
        busy = _shift_is_active(active_shift)
        label = row.get("drawer_name") or row.get("drawer_code") or row.name
        if row.get("drawer_code") and row.get("drawer_code") != label:
            label = f"{label} ({row.get('drawer_code')})"
        if row.get("cash_account"):
            label = f"{label} — {row.get('cash_account')}"

        result.append(
            {
                "name": row.name,
                "drawer_code": row.get("drawer_code") or "",
                "drawer_name": row.get("drawer_name") or row.name,
                "company": row.company,
                "cash_account": row.get("cash_account") or "",
                "physical_location": row.get("physical_location") or "",
                "current_responsible_user": row.get("current_responsible_user") or "",
                "current_active_shift": active_shift,
                "is_busy": 1 if busy else 0,
                "label": label,
            }
        )

    return result


def _branch_rows(company=None):
    company = company or _default_company()
    return frappe.get_all(
        "Pharmacy Branch Profile",
        filters={"company": company, "disabled": 0},
        fields=["branch", "company"],
        order_by="branch asc",
        limit_page_length=200,
    )


@frappe.whitelist()
def get_dashboard(shift_name=None, branch=None):
    company = _default_company()
    branches = _branch_rows(company)
    branch = str(branch or "").strip()
    data = None

    if shift_name:
        shift_branch = frappe.db.get_value(
            "Pharmacy Shift Closing",
            shift_name,
            "branch",
        ) or ""
        if branch and shift_branch and branch != shift_branch:
            frappe.throw(_("Selected Shift belongs to another Branch."))
        branch = shift_branch or branch
    elif branch:
        branch = resolve_operational_branch(
            company=company,
            requested_branch=branch,
        )
    else:
        legacy_active = _get_dashboard()
        legacy_shift = legacy_active.get("shift") or {}
        if legacy_active.get("has_open_shift") and not legacy_shift.get("branch"):
            data = legacy_active
        elif len(branches) == 1:
            branch = branches[0].branch
            data = _get_dashboard(branch=branch)
        else:
            data = {
                "has_open_shift": False,
                "has_active_shift": False,
                "active_shift": "",
                "under_review_shifts": [],
            }

    if data is None:
        data = _get_dashboard(
            shift_name=shift_name,
            branch=branch,
        )

    data["branches"] = branches
    data["selected_branch"] = branch
    if not data.get("has_open_shift"):
        data["cash_drawers"] = _cash_drawer_rows(company)
    return data


@frappe.whitelist()
def create_shift(opening_balance=0, company=None, cash_drawer=None, branch=None):
    company = company or _default_company()
    cash_drawer = (cash_drawer or "").strip()
    branch = resolve_operational_branch(
        company=company,
        requested_branch=branch,
    )

    if not cash_drawer:
        frappe.throw(_("Cash Drawer is required."))

    if not frappe.db.exists("Cash Drawer", cash_drawer):
        frappe.throw(_("Cash Drawer {0} was not found.").format(cash_drawer))

    drawer = frappe.db.get_value(
        "Cash Drawer",
        cash_drawer,
        ["company", "enabled", "cash_account", "current_active_shift"],
        as_dict=True,
    )
    if not drawer or not drawer.enabled:
        frappe.throw(_("The selected Cash Drawer is disabled."))
    if drawer.company != company:
        frappe.throw(_("The selected Cash Drawer belongs to another company."))
    if not drawer.cash_account:
        frappe.throw(_("The selected Cash Drawer has no Cash Account."))
    if _shift_is_active(drawer.current_active_shift):
        frappe.throw(
            _("Cash Drawer {0} is already linked to active shift {1}.").format(
                cash_drawer,
                drawer.current_active_shift,
            )
        )

    return _create_shift(
        opening_balance=opening_balance,
        company=company,
        cash_drawer=cash_drawer,
        branch=branch,
    )
