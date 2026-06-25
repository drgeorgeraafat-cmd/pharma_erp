"""Create Treasury roles before Page JSON role links are synchronised."""

import frappe


ROLE_NAMES = (
    "Treasury Viewer",
    "Treasury Operator",
    "Treasury Manager",
)


def execute():
    for role_name in ROLE_NAMES:
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

    frappe.clear_cache()
