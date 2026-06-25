"""Backfill audit and Cash Drawer links for legacy Shift Cash Movement records."""

import frappe
from frappe.utils import cint


def execute():
    if not frappe.db.exists("DocType", "Shift Cash Movement"):
        return

    meta = frappe.get_meta("Shift Cash Movement")
    required = {
        "cash_drawer",
        "request_status",
        "requested_by",
        "requested_at",
        "approved_by",
        "approved_at",
        "approval_note",
    }
    if not all(meta.has_field(fieldname) for fieldname in required):
        return

    rows = frappe.get_all(
        "Shift Cash Movement",
        fields=[
            "name",
            "docstatus",
            "owner",
            "creation",
            "modified_by",
            "modified",
            "shift_reference",
            "source_account",
            "target_account",
            "cash_drawer",
            "request_status",
        ],
        limit_page_length=0,
    )
    for row in rows:
        cash_drawer = row.cash_drawer or _resolve_cash_drawer(row)
        if cint(row.docstatus) == 1:
            request_status = "Approved"
            approved_by = row.modified_by or row.owner
            approved_at = row.modified
            approval_note = "Legacy posted cash movement backfilled during Treasury setup."
            status = "Posted"
        elif cint(row.docstatus) == 2:
            request_status = "Cancelled"
            approved_by = row.modified_by or row.owner
            approved_at = row.modified
            approval_note = "Legacy cancelled cash movement backfilled during Treasury setup."
            status = "Cancelled"
        else:
            request_status = "Pending Approval"
            approved_by = None
            approved_at = None
            approval_note = None
            status = "Draft"

        frappe.db.set_value(
            "Shift Cash Movement",
            row.name,
            {
                "cash_drawer": cash_drawer,
                "status": status,
                "request_status": row.request_status or request_status,
                "requested_by": row.owner,
                "requested_at": row.creation,
                "approved_by": approved_by,
                "approved_at": approved_at,
                "approval_note": approval_note,
            },
            update_modified=False,
        )

    frappe.clear_cache(doctype="Shift Cash Movement")


def _resolve_cash_drawer(row):
    if row.shift_reference and frappe.db.exists("Pharmacy Shift Closing", row.shift_reference):
        shift_meta = frappe.get_meta("Pharmacy Shift Closing")
        if shift_meta.has_field("custom_cash_drawer"):
            drawer = frappe.db.get_value(
                "Pharmacy Shift Closing", row.shift_reference, "custom_cash_drawer"
            )
            if drawer:
                return drawer

    for account in (row.source_account, row.target_account):
        if not account:
            continue
        drawer = frappe.db.get_value("Cash Drawer", {"cash_account": account}, "name")
        if drawer:
            return drawer
    return None
