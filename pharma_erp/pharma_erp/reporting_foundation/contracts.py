from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Sequence


class ReportingError(Exception):
    """Base reporting foundation error."""


class PermissionDenied(ReportingError):
    """Raised when the requested reporting scope is not authorized."""


class ValidationError(ReportingError):
    """Raised when filters or execution parameters violate a report contract."""


class ValueClass(str, Enum):
    ACCOUNTING = "Accounting"
    OPERATIONAL = "Operational"
    CONTROL = "Control / Expected"
    PENDING = "Pending Posting"


class ExecutionMode(str, Enum):
    SCREEN = "screen"
    EXPORT = "export"
    PRINT = "print"


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str
    data_type: str = "Data"
    sensitive: bool = False
    width: int | None = None


@dataclass(frozen=True)
class ReportDefinition:
    report_id: str
    name: str
    required_capability: str
    columns: tuple[ColumnSpec, ...]
    require_date_range: bool = True
    max_date_range_days: int = 366
    default_page_size: int = 50
    max_page_size: int = 200
    export_row_limit: int = 10000
    print_row_limit: int = 5000
    allow_drilldown: bool = True


@dataclass(frozen=True)
class PermissionContext:
    user: str
    allowed_companies: tuple[str, ...]
    allowed_branches: tuple[str, ...]
    allowed_warehouses: tuple[str, ...]
    capabilities: frozenset[str]


@dataclass(frozen=True)
class ExecutionRequest:
    report_id: str
    filters: Mapping[str, Any]
    page: int = 1
    page_size: int | None = None
    mode: ExecutionMode = ExecutionMode.SCREEN
    requested_row_limit: int | None = None


@dataclass(frozen=True)
class ResolvedScope:
    company: str
    branches: tuple[str, ...]
    warehouses: tuple[str, ...]
    normalized_filters: Mapping[str, Any]


@dataclass(frozen=True)
class ResolvedExecutionContext:
    definition: ReportDefinition
    permission: PermissionContext
    scope: ResolvedScope
    mode: ExecutionMode
    offset: int
    limit: int


@dataclass(frozen=True)
class RunnerResult:
    rows: Sequence[Mapping[str, Any]]
    total_rows: int
    summary: Mapping[str, Any] = field(default_factory=dict)
    totals: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionMetadata:
    report_id: str
    user: str
    generated_at: str
    duration_ms: int
    row_count: int
    total_rows: int
    filter_hash: str
    mode: str
    page: int
    page_size: int


@dataclass(frozen=True)
class ReportResult:
    definition: ReportDefinition
    rows: Sequence[Mapping[str, Any]]
    summary: Mapping[str, Any]
    totals: Mapping[str, Any]
    metadata: ExecutionMetadata
    applied_filters: Mapping[str, Any]
