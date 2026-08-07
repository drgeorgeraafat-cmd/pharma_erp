from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Mapping

from .contracts import (
    ExecutionMetadata,
    ExecutionMode,
    ExecutionRequest,
    PermissionContext,
    ReportDefinition,
    ReportResult,
    ResolvedExecutionContext,
    RunnerResult,
    ValidationError,
)
from .filters import resolve_scope
from .permissions import project_visible_rows, require_capability


Runner = Callable[[ResolvedExecutionContext], RunnerResult]


class ReportRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ReportDefinition] = {}
        self._runners: dict[str, Runner] = {}

    def register(self, definition: ReportDefinition, runner: Runner) -> None:
        if definition.report_id in self._definitions:
            raise ValidationError(f"duplicate report_id: {definition.report_id}")
        self._definitions[definition.report_id] = definition
        self._runners[definition.report_id] = runner

    def get(self, report_id: str) -> tuple[ReportDefinition, Runner]:
        try:
            return self._definitions[report_id], self._runners[report_id]
        except KeyError as exc:
            raise ValidationError(f"unknown report_id: {report_id}") from exc

    def report_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))


def _filter_hash(filters: Mapping[str, object]) -> str:
    raw = json.dumps(filters, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _limit_for(definition: ReportDefinition, request: ExecutionRequest) -> int:
    if request.page < 1:
        raise ValidationError("page must be >= 1")

    if request.mode == ExecutionMode.SCREEN:
        page_size = request.page_size or definition.default_page_size
        if page_size < 1 or page_size > definition.max_page_size:
            raise ValidationError(
                f"screen page_size must be between 1 and {definition.max_page_size}"
            )
        return page_size

    hard_limit = (
        definition.export_row_limit
        if request.mode == ExecutionMode.EXPORT
        else definition.print_row_limit
    )
    requested = request.requested_row_limit or hard_limit
    if requested < 1 or requested > hard_limit:
        raise ValidationError(f"requested row limit exceeds hard limit of {hard_limit}")
    return requested


def execute(
    *,
    registry: ReportRegistry,
    request: ExecutionRequest,
    permission: PermissionContext,
    warehouse_branch_map: Mapping[str, str] | None = None,
    branch_company_map: Mapping[str, str] | None = None,
) -> ReportResult:
    definition, runner = registry.get(request.report_id)
    require_capability(permission, definition.required_capability)

    limit = _limit_for(definition, request)
    offset = 0 if request.mode != ExecutionMode.SCREEN else (request.page - 1) * limit

    scope = resolve_scope(
        definition=definition,
        filters=request.filters,
        permission=permission,
        warehouse_branch_map=warehouse_branch_map,
        branch_company_map=branch_company_map,
    )

    context = ResolvedExecutionContext(
        definition=definition,
        permission=permission,
        scope=scope,
        mode=request.mode,
        offset=offset,
        limit=limit,
    )

    started = time.perf_counter()
    runner_result = runner(context)
    duration_ms = int(round((time.perf_counter() - started) * 1000))

    rows = list(runner_result.rows)
    if len(rows) > limit:
        raise ValidationError(
            "report runner returned more rows than the execution engine limit; "
            "runner must paginate/query with context.offset/context.limit"
        )

    visible_rows = project_visible_rows(rows, definition.columns, permission)
    metadata = ExecutionMetadata(
        report_id=definition.report_id,
        user=permission.user,
        generated_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=duration_ms,
        row_count=len(visible_rows),
        total_rows=int(runner_result.total_rows),
        filter_hash=_filter_hash(scope.normalized_filters),
        mode=request.mode.value,
        page=request.page,
        page_size=limit,
    )

    return ReportResult(
        definition=definition,
        rows=visible_rows,
        summary=dict(runner_result.summary),
        totals=dict(runner_result.totals),
        metadata=metadata,
        applied_filters=dict(scope.normalized_filters),
    )
