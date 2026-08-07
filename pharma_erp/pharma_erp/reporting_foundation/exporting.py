from __future__ import annotations

import csv
import io
from typing import Any, Mapping, Sequence

from .contracts import ColumnSpec, ReportResult, ValidationError


_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _safe_excel_text(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def to_csv_bytes(result: ReportResult, columns: Sequence[ColumnSpec] | None = None) -> bytes:
    cols = tuple(columns or result.definition.columns)
    visible_keys = set(result.rows[0].keys()) if result.rows else {c.key for c in cols}
    cols = tuple(c for c in cols if c.key in visible_keys)

    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow([c.label for c in cols])
    for row in result.rows:
        writer.writerow([_safe_excel_text(row.get(c.key, "")) for c in cols])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def to_xlsx_bytes(
    result: ReportResult,
    columns: Sequence[ColumnSpec] | None = None,
    sheet_name: str = "Report",
) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise ValidationError("openpyxl is required for XLSX export") from exc

    cols = tuple(columns or result.definition.columns)
    visible_keys = set(result.rows[0].keys()) if result.rows else {c.key for c in cols}
    cols = tuple(c for c in cols if c.key in visible_keys)

    wb = Workbook(write_only=False)
    ws = wb.active
    ws.title = (sheet_name or "Report")[:31]
    ws.append([c.label for c in cols])
    for row in result.rows:
        ws.append([_safe_excel_text(row.get(c.key, "")) for c in cols])

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()
