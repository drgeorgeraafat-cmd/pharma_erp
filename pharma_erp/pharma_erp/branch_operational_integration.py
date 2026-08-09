from __future__ import annotations

import frappe
from frappe import _

from pharma_erp.pharma_erp.branch_warehouse_foundation import (
    get_branch_profile,
    resolve_branch_for_warehouse,
    resolve_warehouse_for_role,
)


def _clean(value) -> str:
    return str(value or "").strip()


def resolve_operational_branch(
    *,
    company: str,
    requested_branch: str | None = None,
) -> str:
    """Resolve an explicit canonical operational Branch.

    A client-supplied branch is only a request; the server validates it against
    Pharmacy Branch Profile.  When the caller does not provide a branch, the
    server may default only when exactly one enabled canonical branch exists for
    the company.  It never infers from names, suffixes, users, cashiers,
    accounts, or warehouse naming conventions.
    """

    company = _clean(company)
    requested_branch = _clean(requested_branch)
    if not company:
        frappe.throw(_("Company is required to resolve the operational Branch."))

    if requested_branch:
        profile = get_branch_profile(
            requested_branch,
            company=company,
            require_enabled=True,
        )
        return profile.branch

    rows = frappe.get_all(
        "Pharmacy Branch Profile",
        filters={"company": company, "disabled": 0},
        fields=["branch"],
        order_by="branch asc",
        limit_page_length=3,
    )
    branches = [_clean(row.branch) for row in rows if _clean(row.branch)]

    if len(branches) == 1:
        return branches[0]
    if not branches:
        frappe.throw(
            _("Company {0} has no enabled canonical Pharmacy Branch Profile.").format(
                frappe.bold(company)
            )
        )

    frappe.throw(
        _(
            "Company {0} has multiple enabled branches. Select an explicit Branch before continuing."
        ).format(frappe.bold(company))
    )


def resolve_role_context(
    *,
    company: str,
    role: str,
    requested_branch: str | None = None,
    submitted_warehouse: str | None = None,
) -> dict:
    branch = resolve_operational_branch(
        company=company,
        requested_branch=requested_branch,
    )
    warehouse = resolve_warehouse_for_role(
        branch,
        role,
        company=company,
        require_enabled=True,
    )

    submitted_warehouse = _clean(submitted_warehouse)
    if submitted_warehouse and submitted_warehouse != warehouse:
        frappe.throw(
            _(
                "Submitted warehouse {0} conflicts with canonical {1} warehouse {2} for branch {3}."
            ).format(
                frappe.bold(submitted_warehouse),
                frappe.bold(role),
                frappe.bold(warehouse),
                frappe.bold(branch),
            )
        )

    return {
        "branch": branch,
        "warehouse": warehouse,
        "role": role,
        "company": company,
    }


def resolve_pos_context(
    *,
    company: str,
    requested_branch: str | None = None,
    submitted_warehouse: str | None = None,
) -> dict:
    return resolve_role_context(
        company=company,
        role="POS",
        requested_branch=requested_branch,
        submitted_warehouse=submitted_warehouse,
    )


def online_role(fulfilment_method: str | None) -> str:
    return "Pickup" if _clean(fulfilment_method) == "Pharmacy Pickup" else "Online Fulfilment"


def resolve_online_context(
    *,
    company: str,
    fulfilment_method: str | None,
    requested_branch: str | None = None,
    submitted_warehouse: str | None = None,
) -> dict:
    return resolve_role_context(
        company=company,
        role=online_role(fulfilment_method),
        requested_branch=requested_branch,
        submitted_warehouse=submitted_warehouse,
    )


def require_online_order_context(order) -> dict:
    branch = _clean(order.get("branch"))
    if not branch:
        frappe.throw(
            _(
                "Online Order {0} has no canonical Branch attribution. Legacy unattributed orders must be reviewed explicitly before operational processing."
            ).format(frappe.bold(order.name or _("(new)")))
        )

    return resolve_online_context(
        company=order.company,
        fulfilment_method=order.fulfilment_method,
        requested_branch=branch,
        submitted_warehouse=order.warehouse,
    )


def branch_from_canonical_warehouse(
    *,
    warehouse: str,
    company: str,
) -> str:
    """Resolve only through the explicit Pharmacy Warehouse Profile mapping."""
    return resolve_branch_for_warehouse(
        warehouse,
        company=company,
        require_enabled=True,
    )
