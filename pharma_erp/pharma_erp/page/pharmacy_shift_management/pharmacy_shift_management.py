import frappe
from frappe import _

from pharma_erp.pharma_erp.payment_card_management import (
    close_shift,
    create_card_batch,
    create_cash_action,
    create_payment_reconciliation,
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


@frappe.whitelist()
def get_dashboard(shift_name=None):
    data = _get_dashboard(shift_name=shift_name)
    if not data.get("has_open_shift"):
        data["cash_drawers"] = _cash_drawer_rows()
    return data


@frappe.whitelist()
def create_shift(opening_balance=0, company=None, cash_drawer=None):
    company = company or _default_company()
    cash_drawer = (cash_drawer or "").strip()

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
    )
