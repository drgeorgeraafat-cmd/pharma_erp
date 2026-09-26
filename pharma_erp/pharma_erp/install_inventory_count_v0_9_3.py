from __future__ import annotations

import frappe

SETTINGS = "Pharmacy Inventory Count Settings"
ROLES = [
    "Inventory Counter",
    "Inventory Reviewer",
    "Inventory Approver",
    "Inventory High Variance Approver",
    "Inventory Stock Poster",
]

DEFAULTS = {
    "enable_inventory_count": 0,
    "blind_count_default": 1,
    "high_variance_value_threshold": 0,
    "high_variance_percentage_threshold": 0,
    "require_recount_for_full_shortage": 1,
    "maximum_recounts": 2,
    "high_variance_approval_role": "Inventory High Variance Approver",
}


def prepare_roles():
    results = []
    for role_name in ROLES:
        if frappe.db.exists("Role", role_name):
            results.append(f"{role_name}:EXISTS")
            continue
        role = frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1})
        role.flags.ignore_permissions = True
        role.insert(ignore_permissions=True)
        results.append(f"{role_name}:CREATED")
    frappe.db.commit()
    return {"status": "PASS", "roles": results}


def _single_value_exists(fieldname: str) -> bool:
    rows = frappe.db.sql(
        "SELECT 1 FROM `tabSingles` WHERE doctype=%s AND field=%s LIMIT 1",
        (SETTINGS, fieldname),
    )
    return bool(rows)


def install():
    missing = [
        dt
        for dt in [
            "Pharmacy Inventory Count Settings",
            "Pharmacy Inventory Count",
            "Pharmacy Inventory Count Item",
            "Pharmacy Inventory Count Event",
        ]
        if not frappe.db.exists("DocType", dt)
    ]
    if missing:
        frappe.throw("Inventory Count DocTypes are missing after migrate: " + ", ".join(missing))

    role_result = prepare_roles()
    initialized = []
    for fieldname, value in DEFAULTS.items():
        if _single_value_exists(fieldname):
            continue
        frappe.db.set_single_value(SETTINGS, fieldname, value)
        initialized.append(fieldname)

    # Safety invariant: a fresh installation is never silently activated.
    if not _single_value_exists("enable_inventory_count"):
        frappe.db.set_single_value(SETTINGS, "enable_inventory_count", 0)
        initialized.append("enable_inventory_count")

    frappe.clear_cache(doctype=SETTINGS)
    frappe.db.commit()
    return {
        "status": "PASS",
        "roles": role_result["roles"],
        "initialized_settings": initialized,
        "enable_inventory_count": int(frappe.db.get_single_value(SETTINGS, "enable_inventory_count") or 0),
    }
