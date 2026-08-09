from __future__ import annotations

from collections import OrderedDict

import frappe
from frappe import _
from frappe.utils import cint


WAREHOUSE_ROLES = (
    "Sales",
    "POS",
    "Online Fulfilment",
    "Pickup",
    "Purchase Receipt",
    "Customer Return",
    "Expired",
    "Supplier Return",
    "Recall / Quarantine",
    "Damaged / Rejected",
    "Transfer Source",
    "Transfer Target",
)


def _clean(value):
    return (value or "").strip()


def _assert_role(role: str) -> str:
    role = _clean(role)
    if role not in WAREHOUSE_ROLES:
        frappe.throw(
            _("Warehouse operational role {0} is not supported.").format(
                frappe.bold(role or _("(blank)"))
            )
        )
    return role


def _require_existing(doctype: str, name: str, label: str | None = None) -> None:
    if name and not frappe.db.exists(doctype, name):
        frappe.throw(
            _("{0} {1} does not exist.").format(
                label or doctype,
                frappe.bold(name),
            )
        )


def _validate_link_company(
    doctype: str,
    name: str | None,
    company: str,
    *,
    company_field: str = "company",
    label: str | None = None,
) -> None:
    if not name:
        return

    _require_existing(doctype, name, label)

    linked_company = frappe.db.get_value(doctype, name, company_field)
    if linked_company and linked_company != company:
        frappe.throw(
            _("{0} {1} belongs to company {2}, not {3}.").format(
                label or doctype,
                frappe.bold(name),
                frappe.bold(linked_company),
                frappe.bold(company),
            )
        )


def _get_branch_profile_name(branch: str) -> str | None:
    return frappe.db.get_value(
        "Pharmacy Branch Profile",
        {"branch": branch},
        "name",
    )


def _get_warehouse_profile_name(warehouse: str) -> str | None:
    return frappe.db.get_value(
        "Pharmacy Warehouse Profile",
        {"warehouse": warehouse},
        "name",
    )


def get_branch_profile(
    branch: str,
    *,
    company: str | None = None,
    require_enabled: bool = True,
):
    branch = _clean(branch)
    _require_existing("Branch", branch)

    profile_name = _get_branch_profile_name(branch)
    if not profile_name:
        frappe.throw(
            _("Branch {0} has no canonical Pharmacy Branch Profile.").format(
                frappe.bold(branch)
            )
        )

    profile = frappe.get_doc("Pharmacy Branch Profile", profile_name)

    if require_enabled and cint(profile.disabled):
        frappe.throw(
            _("Branch {0} is disabled in its Pharmacy Branch Profile.").format(
                frappe.bold(branch)
            )
        )

    if company and profile.company != company:
        frappe.throw(
            _("Branch {0} belongs to company {1}, not {2}.").format(
                frappe.bold(branch),
                frappe.bold(profile.company),
                frappe.bold(company),
            )
        )

    return profile


def get_warehouse_profile(
    warehouse: str,
    *,
    company: str | None = None,
    require_enabled: bool = True,
):
    warehouse = _clean(warehouse)
    _require_existing("Warehouse", warehouse)

    profile_name = _get_warehouse_profile_name(warehouse)
    if not profile_name:
        frappe.throw(
            _("Warehouse {0} has no canonical Pharmacy Warehouse Profile.").format(
                frappe.bold(warehouse)
            )
        )

    profile = frappe.get_doc("Pharmacy Warehouse Profile", profile_name)

    if require_enabled and cint(profile.disabled):
        frappe.throw(
            _("Warehouse {0} is disabled in its Pharmacy Warehouse Profile.").format(
                frappe.bold(warehouse)
            )
        )

    standard = frappe.db.get_value(
        "Warehouse",
        warehouse,
        ["company", "is_group", "disabled"],
        as_dict=True,
    ) or {}

    if cint(standard.get("is_group")):
        frappe.throw(
            _("Warehouse {0} is a group and cannot be used operationally.").format(
                frappe.bold(warehouse)
            )
        )

    if require_enabled and cint(standard.get("disabled")):
        frappe.throw(
            _("Warehouse {0} is disabled in ERPNext.").format(
                frappe.bold(warehouse)
            )
        )

    if company and standard.get("company") != company:
        frappe.throw(
            _("Warehouse {0} belongs to company {1}, not {2}.").format(
                frappe.bold(warehouse),
                frappe.bold(standard.get("company") or _("(none)")),
                frappe.bold(company),
            )
        )

    return profile


def _allowed_operations(warehouse_profile) -> set[str]:
    return {
        _clean(row.operation)
        for row in (warehouse_profile.allowed_operations or [])
        if _clean(row.operation)
    }


def validate_warehouse_profile(doc) -> None:
    _require_existing("Warehouse", doc.warehouse)
    _require_existing("Branch", doc.branch)
    _require_existing("Company", doc.company)

    standard = frappe.db.get_value(
        "Warehouse",
        doc.warehouse,
        ["company", "is_group", "disabled"],
        as_dict=True,
    ) or {}

    if cint(standard.get("is_group")):
        frappe.throw(
            _("Group warehouse {0} cannot have an operational Pharmacy Warehouse Profile.").format(
                frappe.bold(doc.warehouse)
            )
        )

    if standard.get("company") != doc.company:
        frappe.throw(
            _("Warehouse {0} belongs to company {1}, not {2}.").format(
                frappe.bold(doc.warehouse),
                frappe.bold(standard.get("company") or _("(none)")),
                frappe.bold(doc.company),
            )
        )

    if not cint(doc.disabled) and cint(standard.get("disabled")):
        frappe.throw(
            _("ERPNext Warehouse {0} is disabled; its operational profile must also be disabled.").format(
                frappe.bold(doc.warehouse)
            )
        )

    branch_profile = get_branch_profile(
        doc.branch,
        company=doc.company,
        require_enabled=not cint(doc.disabled),
    )

    _validate_link_company(
        "Cost Center",
        doc.cost_center,
        doc.company,
        label=_("Cost Center"),
    )

    if doc.manager:
        _require_existing("User", doc.manager, _("Manager"))
        enabled = frappe.db.get_value("User", doc.manager, "enabled")
        if not cint(doc.disabled) and enabled is not None and not cint(enabled):
            frappe.throw(
                _("Warehouse manager {0} is disabled.").format(
                    frappe.bold(doc.manager)
                )
            )

    seen = set()
    for row in doc.allowed_operations or []:
        role = _assert_role(row.operation)
        if role in seen:
            frappe.throw(
                _("Allowed operation {0} is duplicated for warehouse {1}.").format(
                    frappe.bold(role),
                    frappe.bold(doc.warehouse),
                )
            )
        seen.add(role)

    if cint(doc.allow_online) and "Online Fulfilment" not in seen:
        frappe.throw(_("Allow Online requires the Online Fulfilment operation."))

    if cint(doc.is_sellable) and not seen.intersection(
        {"Sales", "POS", "Online Fulfilment", "Pickup"}
    ):
        frappe.throw(
            _("A sellable warehouse must allow at least one selling operation.")
        )

    if branch_profile.branch != doc.branch:
        frappe.throw(_("Canonical branch profile mismatch."))


def _normalize_operating_hours(doc) -> None:
    """Neutralize Frappe v15 Time-field auto-now defaults without guessing.

    New Pharmacy Branch Profiles must be saved once before operating hours can
    be configured. This prevents Frappe's new-document default machinery from
    turning unset Time fields into the current time.

    Existing profiles use an explicit persisted flag:
    - flag off  -> both Time fields are cleared
    - flag on   -> both Time fields are required

    This also preserves midnight (00:00:00) as a valid explicit time because
    readiness checks None-ness, not truthiness.
    """

    if doc.is_new():
        doc.operating_hours_configured = 0
        doc.opening_time = None
        doc.closing_time = None
        return

    if not cint(doc.operating_hours_configured):
        doc.opening_time = None
        doc.closing_time = None
        return

    if doc.opening_time is None or doc.closing_time is None:
        frappe.throw(
            _("Opening Time and Closing Time are both required when Operating Hours Configured is enabled.")
        )


def validate_branch_profile(doc) -> None:
    _require_existing("Branch", doc.branch)
    _require_existing("Company", doc.company)

    _normalize_operating_hours(doc)

    _validate_link_company(
        "Cost Center",
        doc.cost_center,
        doc.company,
        label=_("Cost Center"),
    )
    _validate_link_company(
        "POS Profile",
        doc.pos_profile,
        doc.company,
        label=_("POS Profile"),
    )
    _validate_link_company(
        "Account",
        doc.default_cash_account,
        doc.company,
        label=_("Default Cash Account"),
    )
    _validate_link_company(
        "Account",
        doc.default_till_account,
        doc.company,
        label=_("Default Till Account"),
    )

    if doc.selling_price_list:
        _require_existing("Price List", doc.selling_price_list, _("Selling Price List"))
    if doc.letter_head:
        _require_existing("Letter Head", doc.letter_head)
    if doc.default_print_format:
        _require_existing("Print Format", doc.default_print_format)
    if doc.branch_manager:
        _require_existing("User", doc.branch_manager, _("Branch Manager"))
        enabled = frappe.db.get_value("User", doc.branch_manager, "enabled")
        if not cint(doc.disabled) and enabled is not None and not cint(enabled):
            frappe.throw(
                _("Branch manager {0} is disabled.").format(
                    frappe.bold(doc.branch_manager)
                )
            )

    seen_roles = set()
    role_to_warehouse = OrderedDict()

    for row in doc.warehouse_roles or []:
        role = _assert_role(row.operational_role)
        warehouse = _clean(row.warehouse)

        if not warehouse:
            frappe.throw(
                _("Warehouse is required for operational role {0}.").format(
                    frappe.bold(role)
                )
            )

        if role in seen_roles:
            frappe.throw(
                _("Operational role {0} is duplicated for branch {1}.").format(
                    frappe.bold(role),
                    frappe.bold(doc.branch),
                )
            )

        seen_roles.add(role)
        role_to_warehouse[role] = warehouse

        warehouse_profile = get_warehouse_profile(
            warehouse,
            company=doc.company,
            require_enabled=not cint(doc.disabled),
        )

        if warehouse_profile.branch != doc.branch:
            frappe.throw(
                _("Warehouse {0} belongs canonically to branch {1}, not {2}.").format(
                    frappe.bold(warehouse),
                    frappe.bold(warehouse_profile.branch),
                    frappe.bold(doc.branch),
                )
            )

        allowed = _allowed_operations(warehouse_profile)
        if role not in allowed:
            frappe.throw(
                _("Warehouse {0} is not allowed for operational role {1}.").format(
                    frappe.bold(warehouse),
                    frappe.bold(role),
                )
            )

    if doc.pos_profile and role_to_warehouse.get("POS"):
        pos_warehouse = frappe.db.get_value("POS Profile", doc.pos_profile, "warehouse")
        if pos_warehouse and pos_warehouse != role_to_warehouse["POS"]:
            frappe.throw(
                _("POS Profile {0} uses warehouse {1}, but branch POS mapping uses {2}.").format(
                    frappe.bold(doc.pos_profile),
                    frappe.bold(pos_warehouse),
                    frappe.bold(role_to_warehouse["POS"]),
                )
            )


def resolve_branch_for_warehouse(
    warehouse: str,
    *,
    company: str | None = None,
    require_enabled: bool = True,
) -> str:
    """Return the canonical branch explicitly configured for a Warehouse.

    Never falls back to warehouse names, suffixes, company abbreviations,
    users, cashiers, accounts, or other inferred signals.
    """

    profile = get_warehouse_profile(
        warehouse,
        company=company,
        require_enabled=require_enabled,
    )

    branch_profile = get_branch_profile(
        profile.branch,
        company=company or profile.company,
        require_enabled=require_enabled,
    )

    return branch_profile.branch


def resolve_warehouse_for_role(
    branch: str,
    role: str,
    *,
    company: str | None = None,
    require_enabled: bool = True,
) -> str:
    role = _assert_role(role)
    profile = get_branch_profile(
        branch,
        company=company,
        require_enabled=require_enabled,
    )

    matches = [
        row
        for row in (profile.warehouse_roles or [])
        if _clean(row.operational_role) == role
    ]

    if not matches:
        frappe.throw(
            _("Branch {0} has no canonical warehouse mapping for role {1}.").format(
                frappe.bold(branch),
                frappe.bold(role),
            )
        )

    if len(matches) != 1:
        frappe.throw(
            _("Branch {0} has multiple warehouse mappings for role {1}.").format(
                frappe.bold(branch),
                frappe.bold(role),
            )
        )

    warehouse = _clean(matches[0].warehouse)
    warehouse_profile = get_warehouse_profile(
        warehouse,
        company=profile.company,
        require_enabled=require_enabled,
    )

    if warehouse_profile.branch != branch:
        frappe.throw(
            _("Warehouse {0} is not canonically assigned to branch {1}.").format(
                frappe.bold(warehouse),
                frappe.bold(branch),
            )
        )

    if role not in _allowed_operations(warehouse_profile):
        frappe.throw(
            _("Warehouse {0} is not allowed for operational role {1}.").format(
                frappe.bold(warehouse),
                frappe.bold(role),
            )
        )

    return warehouse


def get_branch_readiness(branch: str) -> dict:
    profile = get_branch_profile(branch, require_enabled=False)

    mapped = OrderedDict()
    duplicates = []
    for row in profile.warehouse_roles or []:
        role = _clean(row.operational_role)
        if role in mapped:
            duplicates.append(role)
        else:
            mapped[role] = _clean(row.warehouse)

    missing_roles = [role for role in WAREHOUSE_ROLES if role not in mapped]

    capability_checks = OrderedDict(
        (
            ("Company", bool(profile.company)),
            ("Cost Center", bool(profile.cost_center)),
            ("Selling Price List", bool(profile.selling_price_list)),
            ("POS Profile", bool(profile.pos_profile)),
            ("Default Cash Account", bool(profile.default_cash_account)),
            ("Default Till Account", bool(profile.default_till_account)),
            (
                "Operating Hours",
                bool(
                    cint(profile.operating_hours_configured)
                    and profile.opening_time is not None
                    and profile.closing_time is not None
                ),
            ),
            ("Branch Manager", bool(profile.branch_manager)),
        )
    )

    configured_capabilities = sum(1 for value in capability_checks.values() if value)
    total_capabilities = len(capability_checks)
    mapped_roles = len([role for role in WAREHOUSE_ROLES if role in mapped])

    total_points = total_capabilities + len(WAREHOUSE_ROLES)
    earned_points = configured_capabilities + mapped_roles
    score = round((earned_points / total_points) * 100, 1) if total_points else 0.0

    return {
        "branch": profile.branch,
        "company": profile.company,
        "disabled": bool(cint(profile.disabled)),
        "score": score,
        "capabilities": capability_checks,
        "mapped_roles": mapped,
        "missing_roles": missing_roles,
        "duplicate_roles": sorted(set(duplicates)),
        "canonical_attribution": "Configured" if not duplicates else "Invalid",
        "inference_policy": "Explicit mapping only; no name/suffix inference",
    }
