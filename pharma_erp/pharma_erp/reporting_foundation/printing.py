from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

from .contracts import ColumnSpec, ReportResult, ValidationError


def _display(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value))


def render_a4_html(
    result: ReportResult,
    *,
    branding: Mapping[str, Any],
    title_ar: str | None = None,
    title_en: str | None = None,
    columns: Sequence[ColumnSpec] | None = None,
) -> str:
    company_name = str(branding.get("company_name") or "").strip()
    if not company_name:
        raise ValidationError("dynamic branding requires company_name")

    logo_url = str(branding.get("logo_url") or "").strip()
    contact = str(branding.get("contact") or "").strip()

    cols = tuple(columns or result.definition.columns)
    visible_keys = set(result.rows[0].keys()) if result.rows else {c.key for c in cols}
    cols = tuple(c for c in cols if c.key in visible_keys)

    filters = "".join(
        f"<li><strong>{escape(str(k))}:</strong> {_display(v)}</li>"
        for k, v in sorted(result.applied_filters.items())
    )
    headers = "".join(f"<th>{escape(c.label)}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{_display(row.get(c.key))}</td>" for c in cols) + "</tr>"
        for row in result.rows
    )
    logo = f'<img class="logo" src="{escape(logo_url)}" alt="Company logo">' if logo_url else ""
    title = escape(title_ar or title_en or result.definition.name)

    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <style>
    @page {{ size: A4; margin: 12mm; }}
    body {{ font-family: sans-serif; font-size: 10pt; }}
    .header {{ display:flex; justify-content:space-between; align-items:center; gap:12px; }}
    .logo {{ max-height:55px; max-width:150px; }}
    .meta {{ font-size:8.5pt; color:#444; }}
    table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
    th,td {{ border:1px solid #bbb; padding:5px; vertical-align:top; }}
    th {{ font-weight:700; }}
    ul.filters {{ columns:2; padding-right:18px; }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h2>{title}</h2>
      <div>{escape(company_name)}</div>
      <div>{escape(contact)}</div>
    </div>
    {logo}
  </div>
  <div class="meta">
    <div>Generated: {escape(result.metadata.generated_at)}</div>
    <div>User: {escape(result.metadata.user)}</div>
    <div>Rows: {result.metadata.row_count} / {result.metadata.total_rows}</div>
    <div>Duration: {result.metadata.duration_ms} ms</div>
  </div>
  <ul class="filters">{filters}</ul>
  <table>
    <thead><tr>{headers}</tr></thead>
    <tbody>{body}</tbody>
  </table>
</body>
</html>"""


def get_pdf_bytes(html: str, *, pdf_options: Mapping[str, Any] | None = None) -> bytes:
    try:
        from frappe.utils.pdf import get_pdf
    except ImportError as exc:
        raise ValidationError("Frappe PDF adapter is unavailable") from exc
    return get_pdf(html, options=dict(pdf_options or {}))
