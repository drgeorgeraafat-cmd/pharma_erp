"""Shared Treasury authorization and Payment Entry audit controls.

The page uses role-aware server methods, while these document hooks protect
Internal Transfer Payment Entries even when users open the standard form or call
ERPNext APIs directly.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime


TREASURY_VIEW_ROLES = {
    "Treasury Viewer",
    "Treasury Operator",
    "Treasury Manager",
    "Accounts Manager",
    "System Manager",
}
TREASURY_OPERATOR_ROLES = {
    "Treasury Operator",
    "Treasury Manager",
    "Accounts Manager",
    "System Manager",
}
TREASURY_MANAGER_ROLES = {
    "Treasury Manager",
    "Accounts Manager",
    "System Manager",
}
SYSTEM_MANAGER_ROLE = "System Manager"

AUDIT_FIELDS = (
    "custom_treasury_internal_transfer",
    "custom_treasury_request_status",
    "custom_treasury_requested_by",
    "custom_treasury_requested_at",
    "custom_treasury_approved_by",
    "custom_treasury_approved_at",
    "custom_treasury_approval_note",
)


def get_user_roles(user=None):
    return set(frappe.get_roles(user or frappe.session.user))


def has_any_role(roles, user=None):
    return bool(get_user_roles(user).intersection(set(roles)))


def can_view_treasury(user=None):
    return has_any_role(TREASURY_VIEW_ROLES, user)


def can_operate_treasury(user=None):
    return has_any_role(TREASURY_OPERATOR_ROLES, user)


def can_manage_treasury(user=None):
    return has_any_role(TREASURY_MANAGER_ROLES, user)


def can_emergency_submit_treasury(user=None):
    return SYSTEM_MANAGER_ROLE in get_user_roles(user)


def get_treasury_access_profile(user=None):
    user = user or frappe.session.user
    roles = get_user_roles(user)
    if SYSTEM_MANAGER_ROLE in roles:
        label = "System Manager"
    elif "Treasury Manager" in roles:
        label = "Treasury Manager"
    elif "Accounts Manager" in roles:
        label = "Accounts Manager"
    elif "Treasury Operator" in roles:
        label = "Treasury Operator"
    elif "Treasury Viewer" in roles:
        label = "Treasury Viewer"
    else:
        label = "No Treasury Access"

    return {
        "user": user,
        "role_label": label,
        "can_view": can_view_treasury(user),
        "can_operate": can_operate_treasury(user),
        "can_manage": can_manage_treasury(user),
        "can_emergency_submit": can_emergency_submit_treasury(user),
    }


def validate_payment_entry(doc, method=None):
    """Stamp and protect Treasury audit data on every Internal Transfer."""
    if not _is_internal_transfer(doc):
        return

    if not can_operate_treasury():
        frappe.throw(
            _("Only Treasury Operator, Treasury Manager, Accounts Manager, or System Manager can create Internal Transfers."),
            frappe.PermissionError,
        )

    existing = _existing_audit_values(doc)
    if doc.is_new():
        _set_if_available(doc, "custom_treasury_internal_transfer", 1)
        _set_if_available(doc, "custom_treasury_request_status", "Pending Approval")
        _set_if_available(doc, "custom_treasury_requested_by", frappe.session.user)
        _set_if_available(doc, "custom_treasury_requested_at", now_datetime())
        _set_if_available(doc, "custom_treasury_approved_by", None)
        _set_if_available(doc, "custom_treasury_approved_at", None)
        _set_if_available(doc, "custom_treasury_approval_note", None)
        return

    # Existing audit values are server-owned and cannot be changed from the form/API.
    for fieldname in AUDIT_FIELDS:
        if fieldname in existing and _has_field(doc, fieldname):
            setattr(doc, fieldname, existing.get(fieldname))

    _set_if_available(doc, "custom_treasury_internal_transfer", 1)
    if not _get_field_value(doc, "custom_treasury_request_status"):
        _set_if_available(doc, "custom_treasury_request_status", "Pending Approval")
    if not _get_field_value(doc, "custom_treasury_requested_by"):
        _set_if_available(doc, "custom_treasury_requested_by", doc.owner or frappe.session.user)
    if not _get_field_value(doc, "custom_treasury_requested_at"):
        _set_if_available(doc, "custom_treasury_requested_at", doc.creation or now_datetime())


def before_submit_payment_entry(doc, method=None):
    """Require a separate Treasury approver before an Internal Transfer posts."""
    if not _is_internal_transfer(doc):
        return

    if not can_manage_treasury():
        frappe.throw(
            _("Only Treasury Manager, Accounts Manager, or System Manager can approve an Internal Transfer."),
            frappe.PermissionError,
        )

    existing = _existing_audit_values(doc)
    requested_by = (
        existing.get("custom_treasury_requested_by")
        or _get_field_value(doc, "custom_treasury_requested_by")
        or doc.owner
    )
    requested_at = (
        existing.get("custom_treasury_requested_at")
        or _get_field_value(doc, "custom_treasury_requested_at")
        or doc.creation
        or now_datetime()
    )

    self_approval = requested_by == frappe.session.user
    if self_approval and not can_emergency_submit_treasury():
        frappe.throw(
            _("The user who requested this Internal Transfer cannot approve the same request. A different Treasury Manager must approve it."),
            frappe.PermissionError,
        )

    approval_note = (
        _("Emergency self-approval by System Manager.")
        if self_approval
        else _("Approved by a separate Treasury approver.")
    )

    _set_if_available(doc, "custom_treasury_internal_transfer", 1)
    _set_if_available(doc, "custom_treasury_request_status", "Approved")
    _set_if_available(doc, "custom_treasury_requested_by", requested_by)
    _set_if_available(doc, "custom_treasury_requested_at", requested_at)
    _set_if_available(doc, "custom_treasury_approved_by", frappe.session.user)
    _set_if_available(doc, "custom_treasury_approved_at", now_datetime())
    _set_if_available(doc, "custom_treasury_approval_note", approval_note)


def before_cancel_payment_entry(doc, method=None):
    if not _is_internal_transfer(doc):
        return
    if not can_manage_treasury():
        frappe.throw(
            _("Only Treasury Manager, Accounts Manager, or System Manager can cancel an Internal Transfer."),
            frappe.PermissionError,
        )
    _set_if_available(doc, "custom_treasury_request_status", "Cancelled")


def validate_internal_transfer_approver(doc):
    """Run the same approval separation check before page-driven submit."""
    if not can_manage_treasury():
        frappe.throw(
            _("Only Treasury Manager, Accounts Manager, or System Manager can approve an Internal Transfer."),
            frappe.PermissionError,
        )

    requested_by = frappe.db.get_value(
        "Payment Entry", doc.name, "custom_treasury_requested_by"
    ) if frappe.db.has_column("Payment Entry", "custom_treasury_requested_by") else None
    requested_by = requested_by or doc.owner
    if requested_by == frappe.session.user and not can_emergency_submit_treasury():
        frappe.throw(
            _("The user who requested this Internal Transfer cannot approve the same request. A different Treasury Manager must approve it."),
            frappe.PermissionError,
        )


def _is_internal_transfer(doc):
    return str(getattr(doc, "payment_type", "") or "").strip() == "Internal Transfer"


def _has_field(doc, fieldname):
    try:
        return bool(doc.meta.has_field(fieldname))
    except Exception:
        return False


def _set_if_available(doc, fieldname, value):
    if _has_field(doc, fieldname):
        setattr(doc, fieldname, value)


def _get_field_value(doc, fieldname):
    return getattr(doc, fieldname, None) if _has_field(doc, fieldname) else None


def _existing_audit_values(doc):
    if doc.is_new() or not getattr(doc, "name", None):
        return {}
    available = [fieldname for fieldname in AUDIT_FIELDS if frappe.db.has_column("Payment Entry", fieldname)]
    if not available:
        return {}
    return frappe.db.get_value("Payment Entry", doc.name, available, as_dict=True) or {}
