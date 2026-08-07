from __future__ import annotations

import os

from .contracts import (
    ColumnSpec,
    ExecutionMode,
    ExecutionRequest,
    PermissionContext,
    PermissionDenied,
    ReportDefinition,
    RunnerResult,
    ValidationError,
)
from .execution import ReportRegistry, execute
from .exporting import to_csv_bytes, to_xlsx_bytes
from .printing import render_a4_html


PILOT_IDS = {
    "daily_branch_operations_summary",
    "shift_cash_integrity_summary",
    "online_order_operations_funnel",
}


def _definition() -> ReportDefinition:
    return ReportDefinition(
        report_id="foundation_selftest",
        name="Foundation Self Test",
        required_capability="OPERATIONAL_REPORTING",
        columns=(
            ColumnSpec("item", "Item"),
            ColumnSpec("amount", "Amount", data_type="Currency"),
            ColumnSpec("secret", "Sensitive", sensitive=True),
        ),
        max_date_range_days=31,
        default_page_size=10,
        max_page_size=50,
        export_row_limit=100,
        print_row_limit=80,
    )


def _runner(context):
    total = 60
    start = context.offset
    end = min(start + context.limit, total)
    rows = [
        {"item": f"ROW-{i+1}", "amount": i + 0.5, "secret": "hidden"}
        for i in range(start, end)
    ]
    if rows:
        rows[0]["item"] = "=2+2"
    return RunnerResult(
        rows=rows,
        total_rows=total,
        summary={"classification": "Operational"},
        totals={"amount": 1770.0},
    )


def run() -> dict[str, str]:
    registry = ReportRegistry()
    registry.register(_definition(), _runner)

    assert not (set(registry.report_ids()) & PILOT_IDS), "Pilot report registered in A.4"

    permission = PermissionContext(
        user="foundation-test@example.invalid",
        allowed_companies=("Test Company",),
        allowed_branches=("BR-TEST",),
        allowed_warehouses=("WH-TEST",),
        capabilities=frozenset({"REPORT_ACCESS", "OPERATIONAL_REPORTING"}),
    )

    maps = {"WH-TEST": "BR-TEST"}
    bmap = {"BR-TEST": "Test Company"}

    request = ExecutionRequest(
        report_id="foundation_selftest",
        filters={
            "from_date": "2026-08-01",
            "to_date": "2026-08-07",
            "company": "Test Company",
            "branch": "BR-TEST",
            "warehouse": "WH-TEST",
        },
        page=1,
        page_size=10,
    )
    result = execute(
        registry=registry,
        request=request,
        permission=permission,
        warehouse_branch_map=maps,
        branch_company_map=bmap,
    )
    assert len(result.rows) == 10
    assert "secret" not in result.rows[0], "sensitive field leaked without capability"
    assert result.metadata.total_rows == 60
    assert len(result.metadata.filter_hash) == 64

    csv_bytes = to_csv_bytes(result)
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    assert b"'=2+2" in csv_bytes, "CSV formula injection guard failed"

    xlsx_bytes = to_xlsx_bytes(result)
    assert xlsx_bytes.startswith(b"PK"), "XLSX payload is not a ZIP container"

    html = render_a4_html(
        result,
        branding={
            "company_name": "Dynamic Test Pharmacy",
            "logo_url": "",
            "contact": "Dynamic Contact",
        },
        title_ar="اختبار أساس التقارير",
        title_en="Reporting Foundation Test",
    )
    assert "Dynamic Test Pharmacy" in html
    assert "Cure Pharmacy" not in html
    assert "WH-TEST" in html

    try:
        execute(
            registry=registry,
            request=ExecutionRequest(
                report_id="foundation_selftest",
                filters={
                    "from_date": "2026-08-01",
                    "to_date": "2026-08-07",
                    "company": "Test Company",
                    "branch": "BR-OTHER",
                },
            ),
            permission=permission,
            warehouse_branch_map=maps,
            branch_company_map=bmap,
        )
        raise AssertionError("permission isolation selftest did not fail")
    except PermissionDenied:
        pass

    try:
        execute(
            registry=registry,
            request=ExecutionRequest(
                report_id="foundation_selftest",
                filters={
                    "from_date": "2026-01-01",
                    "to_date": "2026-08-07",
                    "company": "Test Company",
                    "branch": "BR-TEST",
                },
            ),
            permission=permission,
            warehouse_branch_map=maps,
            branch_company_map=bmap,
        )
        raise AssertionError("date range guard selftest did not fail")
    except ValidationError:
        pass

    pdf_adapter = "NOT_CHECKED"
    if os.environ.get("A4_REQUIRE_FRAPPE_PDF_IMPORT") == "1":
        from frappe.utils.pdf import get_pdf  # noqa: F401
        pdf_adapter = "PASS"

    return {
        "EXECUTION_ENGINE_SELFTEST": "PASS",
        "PAGINATION_LIMIT_GUARD": "PASS",
        "DATE_RANGE_GUARD": "PASS",
        "PERMISSION_SCOPE_GUARD": "PASS",
        "SENSITIVE_COLUMN_GUARD": "PASS",
        "CSV_EXPORT_SELFTEST": "PASS",
        "XLSX_EXPORT_SELFTEST": "PASS",
        "CSV_FORMULA_INJECTION_GUARD": "PASS",
        "A4_PRINT_HTML_SELFTEST": "PASS",
        "DYNAMIC_BRANDING_GUARD": "PASS",
        "PILOT_REPORTS_IMPLEMENTED": "NO",
        "PDF_ADAPTER_IMPORT": pdf_adapter,
    }


if __name__ == "__main__":
    for key, value in run().items():
        print(f"{key}={value}")
