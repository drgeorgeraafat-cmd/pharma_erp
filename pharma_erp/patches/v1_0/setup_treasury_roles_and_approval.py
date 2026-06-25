"""Create Treasury roles, audit fields, page access and role permissions."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.permissions import setup_custom_perms


ROLES = (
    "Treasury Viewer",
    "Treasury Operator",
    "Treasury Manager",
)
PAGE_ROLES = (
    "Treasury Viewer",
    "Treasury Operator",
    "Treasury Manager",
    "Accounts Manager",
    "System Manager",
)

VIEWER_READ_DOCTYPES = (
    "Account",
    "Company",
    "Bank",
    "Bank Account",
    "Cash Drawer",
    "Card POS Terminal",
    "Payment Method Clearing Setup",
    "Shift Payment Reconciliation",
    "Card Settlement Batch",
    "Card Bank Settlement",
)

OPERATOR_READ_DOCTYPES = VIEWER_READ_DOCTYPES + (
    "Journal Entry",
)


MANAGED_DOCTYPES = (
    "Cash Drawer",
    "Card POS Terminal",
    "Payment Method Clearing Setup",
    "Shift Payment Reconciliation",
    "Card Settlement Batch",
    "Card Bank Settlement",
)


def execute():
    _ensure_roles()
    _ensure_payment_entry_fields()
    _ensure_page_roles()
    _ensure_permissions()
    _backfill_internal_transfers()
    frappe.clear_cache()


def _ensure_roles():
    for role_name in ROLES:
        if frappe.db.exists("Role", role_name):
            frappe.db.set_value(
                "Role",
                role_name,
                {"disabled": 0, "desk_access": 1},
                update_modified=False,
            )
            continue
        role = frappe.new_doc("Role")
        role.role_name = role_name
        role.desk_access = 1
        role.insert(ignore_permissions=True)


def _ensure_payment_entry_fields():
    create_custom_fields(
        {
            "Payment Entry": [
                {
                    "fieldname": "custom_treasury_approval_section",
                    "label": "Treasury Approval",
                    "fieldtype": "Section Break",
                    "insert_after": "remarks",
                    "depends_on": "eval:doc.payment_type=='Internal Transfer'",
                    "collapsible": 1,
                },
                {
                    "fieldname": "custom_treasury_internal_transfer",
                    "label": "Treasury Internal Transfer",
                    "fieldtype": "Check",
                    "insert_after": "custom_treasury_approval_section",
                    "read_only": 1,
                    "hidden": 1,
                    "no_copy": 1,
                },
                {
                    "fieldname": "custom_treasury_request_status",
                    "label": "Treasury Request Status",
                    "fieldtype": "Select",
                    "options": "\nPending Approval\nApproved\nCancelled",
                    "insert_after": "custom_treasury_internal_transfer",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "no_copy": 1,
                },
                {
                    "fieldname": "custom_treasury_requested_by",
                    "label": "Requested By",
                    "fieldtype": "Link",
                    "options": "User",
                    "insert_after": "custom_treasury_request_status",
                    "read_only": 1,
                    "no_copy": 1,
                },
                {
                    "fieldname": "custom_treasury_requested_at",
                    "label": "Requested At",
                    "fieldtype": "Datetime",
                    "insert_after": "custom_treasury_requested_by",
                    "read_only": 1,
                    "no_copy": 1,
                },
                {
                    "fieldname": "custom_treasury_approval_column",
                    "fieldtype": "Column Break",
                    "insert_after": "custom_treasury_requested_at",
                },
                {
                    "fieldname": "custom_treasury_approved_by",
                    "label": "Approved By",
                    "fieldtype": "Link",
                    "options": "User",
                    "insert_after": "custom_treasury_approval_column",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "no_copy": 1,
                },
                {
                    "fieldname": "custom_treasury_approved_at",
                    "label": "Approved At",
                    "fieldtype": "Datetime",
                    "insert_after": "custom_treasury_approved_by",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "no_copy": 1,
                },
                {
                    "fieldname": "custom_treasury_approval_note",
                    "label": "Approval Audit Note",
                    "fieldtype": "Small Text",
                    "insert_after": "custom_treasury_approved_at",
                    "read_only": 1,
                    "allow_on_submit": 1,
                    "no_copy": 1,
                },
            ]
        },
        update=True,
    )


def _ensure_page_roles():
    if not frappe.db.exists("Page", "treasury-management"):
        return
    page = frappe.get_doc("Page", "treasury-management")
    page.set("roles", [])
    for role_name in PAGE_ROLES:
        page.append("roles", {"role": role_name})
    page.flags.ignore_permissions = True
    page.save(ignore_permissions=True)


def _ensure_permissions():
    # Viewer can read Treasury masters and settlement records without posting entries.
    for doctype in VIEWER_READ_DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            _upsert_custom_permission(
                doctype,
                "Treasury Viewer",
                read=1,
                report=1,
                export=1,
                print_perm=1,
            )

    # Operator can additionally inspect Journal Entries while preparing reconciliation previews.
    for doctype in OPERATOR_READ_DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            _upsert_custom_permission(
                doctype,
                "Treasury Operator",
                read=1,
                report=1,
                export=1,
                print_perm=1,
            )

    # Operator owns and edits only the Payment Entry drafts they create.
    _upsert_custom_permission(
        "Payment Entry",
        "Treasury Operator",
        read=1,
        write=1,
        create=1,
        delete=1,
        report=1,
        export=1,
        print_perm=1,
        if_owner=1,
    )

    # Manager can review all Treasury documents and submit/cancel transfers.
    for doctype in OPERATOR_READ_DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            _upsert_custom_permission(
                doctype,
                "Treasury Manager",
                read=1,
                report=1,
                export=1,
                print_perm=1,
            )

    _upsert_custom_permission(
        "Payment Entry",
        "Treasury Manager",
        read=1,
        write=1,
        create=1,
        submit=1,
        cancel=1,
        amend=1,
        report=1,
        export=1,
        print_perm=1,
    )

    for doctype in MANAGED_DOCTYPES:
        if not frappe.db.exists("DocType", doctype):
            continue
        is_submittable = bool(frappe.db.get_value("DocType", doctype, "is_submittable"))
        _upsert_custom_permission(
            doctype,
            "Treasury Manager",
            read=1,
            write=1,
            create=1,
            submit=1 if is_submittable else 0,
            cancel=1 if is_submittable else 0,
            amend=1 if is_submittable else 0,
            delete=1,
            report=1,
            export=1,
            print_perm=1,
        )


def _upsert_custom_permission(
    doctype,
    role,
    *,
    read=0,
    write=0,
    create=0,
    submit=0,
    cancel=0,
    delete=0,
    amend=0,
    report=0,
    export=0,
    print_perm=0,
    if_owner=0,
):
    setup_custom_perms(doctype)
    values = {
        "read": read,
        "write": write,
        "create": create,
        "submit": submit,
        "cancel": cancel,
        "delete": delete,
        "amend": amend,
        "report": report,
        "export": export,
        "print": print_perm,
        "if_owner": if_owner,
    }
    existing = frappe.get_all(
        "Custom DocPerm",
        filters={
            "parent": doctype,
            "parenttype": "DocType",
            "parentfield": "permissions",
            "role": role,
            "permlevel": 0,
            "if_owner": if_owner,
        },
        pluck="name",
        order_by="creation asc",
        limit_page_length=20,
    )
    if existing:
        frappe.db.set_value("Custom DocPerm", existing[0], values, update_modified=False)
        for duplicate in existing[1:]:
            frappe.delete_doc("Custom DocPerm", duplicate, ignore_permissions=True, force=True)
        return

    doc = frappe.get_doc(
        {
            "doctype": "Custom DocPerm",
            "parent": doctype,
            "parenttype": "DocType",
            "parentfield": "permissions",
            "role": role,
            "permlevel": 0,
            **values,
        }
    )
    doc.insert(ignore_permissions=True)


def _backfill_internal_transfers():
    required_columns = (
        "custom_treasury_internal_transfer",
        "custom_treasury_request_status",
        "custom_treasury_requested_by",
        "custom_treasury_requested_at",
        "custom_treasury_approved_by",
        "custom_treasury_approved_at",
        "custom_treasury_approval_note",
    )
    if not all(frappe.db.has_column("Payment Entry", fieldname) for fieldname in required_columns):
        return

    rows = frappe.get_all(
        "Payment Entry",
        filters={"payment_type": "Internal Transfer"},
        fields=[
            "name",
            "docstatus",
            "owner",
            "creation",
            "modified_by",
            "modified",
        ],
        limit_page_length=0,
    )
    for row in rows:
        if row.docstatus == 1:
            status = "Approved"
            approved_by = row.modified_by or row.owner
            approved_at = row.modified
            note = "Legacy Internal Transfer backfilled during Treasury permission setup."
        elif row.docstatus == 2:
            status = "Cancelled"
            approved_by = row.modified_by or row.owner
            approved_at = row.modified
            note = "Legacy cancelled Internal Transfer backfilled during Treasury permission setup."
        else:
            status = "Pending Approval"
            approved_by = None
            approved_at = None
            note = None

        frappe.db.set_value(
            "Payment Entry",
            row.name,
            {
                "custom_treasury_internal_transfer": 1,
                "custom_treasury_request_status": status,
                "custom_treasury_requested_by": row.owner,
                "custom_treasury_requested_at": row.creation,
                "custom_treasury_approved_by": approved_by,
                "custom_treasury_approved_at": approved_at,
                "custom_treasury_approval_note": note,
            },
            update_modified=False,
        )
