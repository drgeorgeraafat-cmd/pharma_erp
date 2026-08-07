from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .contracts import PermissionContext, ReportDefinition, ResolvedScope, ValidationError, PermissionDenied


ALL_BRANCHES = "__ALL_PERMITTED_BRANCHES__"


def _iso_date(value: Any, fieldname: str) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValidationError(f"{fieldname} must be YYYY-MM-DD") from exc


def normalize_filters(definition: ReportDefinition, filters: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(filters or {})
    from_date = _iso_date(out.get("from_date"), "from_date")
    to_date = _iso_date(out.get("to_date"), "to_date")

    if definition.require_date_range and (not from_date or not to_date):
        raise ValidationError("from_date and to_date are required by this report contract")

    if from_date and to_date:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
        if start > end:
            raise ValidationError("from_date must be <= to_date")
        if (end - start).days > definition.max_date_range_days:
            raise ValidationError(
                f"date range exceeds report maximum of {definition.max_date_range_days} days"
            )
        out["from_date"] = from_date
        out["to_date"] = to_date

    return out


def resolve_scope(
    *,
    definition: ReportDefinition,
    filters: Mapping[str, Any],
    permission: PermissionContext,
    warehouse_branch_map: Mapping[str, str] | None = None,
    branch_company_map: Mapping[str, str] | None = None,
) -> ResolvedScope:
    normalized = normalize_filters(definition, filters)

    allowed_companies = tuple(dict.fromkeys(permission.allowed_companies))
    allowed_branches = tuple(dict.fromkeys(permission.allowed_branches))
    allowed_warehouses = tuple(dict.fromkeys(permission.allowed_warehouses))

    requested_company = normalized.get("company")
    if requested_company:
        if requested_company not in allowed_companies:
            raise PermissionDenied("requested Company is outside permitted scope")
        company = requested_company
    elif len(allowed_companies) == 1:
        company = allowed_companies[0]
    else:
        raise ValidationError("company must be selected when more than one Company is permitted")

    requested_branch = normalized.get("branch")
    if requested_branch in (ALL_BRANCHES, "All Branches"):
        if "CROSS_BRANCH_REPORTING" not in permission.capabilities:
            raise PermissionDenied("All Branches requires CROSS_BRANCH_REPORTING")
        branches = allowed_branches
        if not branches:
            raise PermissionDenied("no permitted Branches are available")
    elif requested_branch:
        if requested_branch not in allowed_branches:
            raise PermissionDenied("requested Branch is outside permitted scope")
        branches = (requested_branch,)
    elif len(allowed_branches) == 1:
        branches = (allowed_branches[0],)
    else:
        raise ValidationError("branch must be selected when more than one Branch is permitted")

    if branch_company_map:
        for branch in branches:
            mapped_company = branch_company_map.get(branch)
            if mapped_company is None:
                raise ValidationError(f"canonical Company mapping missing for Branch {branch}")
            if mapped_company != company:
                raise ValidationError(f"Branch {branch} does not belong to selected Company")

    requested_warehouse = normalized.get("warehouse")
    if requested_warehouse:
        if requested_warehouse not in allowed_warehouses:
            raise PermissionDenied("requested Warehouse is outside permitted scope")
        if warehouse_branch_map:
            mapped_branch = warehouse_branch_map.get(requested_warehouse)
            if mapped_branch is None:
                raise ValidationError(
                    f"canonical Branch mapping missing for Warehouse {requested_warehouse}"
                )
            if mapped_branch not in branches:
                raise ValidationError("Warehouse conflicts with selected Branch scope")
        warehouses = (requested_warehouse,)
    else:
        if warehouse_branch_map:
            warehouses = tuple(
                w for w in allowed_warehouses if warehouse_branch_map.get(w) in branches
            )
        else:
            warehouses = allowed_warehouses

    normalized["company"] = company
    normalized["branch"] = list(branches)
    if requested_warehouse or warehouses:
        normalized["warehouse"] = list(warehouses)

    return ResolvedScope(
        company=company,
        branches=branches,
        warehouses=warehouses,
        normalized_filters=normalized,
    )
