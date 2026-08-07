from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import ColumnSpec, PermissionContext, PermissionDenied


def require_capability(permission: PermissionContext, capability: str) -> None:
    if capability not in permission.capabilities:
        raise PermissionDenied(f"missing reporting capability: {capability}")


def require_drilldown(permission: PermissionContext) -> None:
    require_capability(permission, "SOURCE_DOCUMENT_DRILLDOWN")


def filter_visible_columns(
    columns: Sequence[ColumnSpec],
    permission: PermissionContext,
) -> tuple[ColumnSpec, ...]:
    allow_sensitive = "SENSITIVE_FINANCIAL_DETAIL" in permission.capabilities
    return tuple(c for c in columns if allow_sensitive or not c.sensitive)


def project_visible_rows(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[ColumnSpec],
    permission: PermissionContext,
) -> list[dict[str, Any]]:
    visible = filter_visible_columns(columns, permission)
    keys = {c.key for c in visible}
    return [{k: row.get(k) for k in keys} for row in rows]
