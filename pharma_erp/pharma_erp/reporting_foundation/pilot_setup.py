from __future__ import annotations

import frappe


REPORTS = (
    {"name": "Daily Branch Operations Summary", "ref_doctype": "Sales Invoice"},
    {"name": "Shift Cash Integrity Summary", "ref_doctype": "Pharmacy Shift Closing"},
    {"name": "Online Order Operations Funnel", "ref_doctype": "Online Order"},
)


def _report_names() -> tuple[str, ...]:
    return tuple(row["name"] for row in REPORTS)


def _record(name: str):
    return frappe.db.get_value(
        "Report",
        name,
        [
            "name",
            "report_name",
            "ref_doctype",
            "report_type",
            "is_standard",
            "module",
            "disabled",
            "prepared_report",
        ],
        as_dict=True,
    )


def preflight_report_metadata():
    existing = [name for name in _report_names() if frappe.db.exists("Report", name)]
    result = {
        "existing_reports": existing,
        "expected_count": len(REPORTS),
        "module_exists": bool(frappe.db.exists("Module Def", "Pharma Erp")),
        "source_doctypes": {
            row["ref_doctype"]: bool(frappe.db.exists("DocType", row["ref_doctype"]))
            for row in REPORTS
        },
    }
    if existing:
        raise RuntimeError(f"A.5 pilot Report metadata already exists: {existing}")
    if not result["module_exists"]:
        raise RuntimeError("Module Def 'Pharma Erp' does not exist")
    missing = [dt for dt, exists in result["source_doctypes"].items() if not exists]
    if missing:
        raise RuntimeError(f"Required source DocTypes are missing: {missing}")
    return result


def install_report_metadata():
    """Create exactly three metadata rows without Standard Report export hooks."""
    preflight_report_metadata()
    created = []
    try:
        for spec in REPORTS:
            doc = frappe.get_doc(
                {
                    "doctype": "Report",
                    "name": spec["name"],
                    "report_name": spec["name"],
                    "ref_doctype": spec["ref_doctype"],
                    "report_type": "Script Report",
                    "is_standard": "Yes",
                    "module": "Pharma Erp",
                    "disabled": 0,
                    "prepared_report": 0,
                    "add_total_row": 0,
                }
            )
            # Intentional metadata-only insert: normal Report.insert() can
            # export/boilerplate standard report source in developer mode.
            doc.db_insert()
            created.append(spec["name"])

        verified = verify_report_metadata()
        frappe.db.commit()
        frappe.clear_cache()
        return {
            "created": created,
            "verified": verified,
            "db_write_scope": "Report metadata only",
        }
    except Exception:
        frappe.db.rollback()
        raise


def verify_report_metadata():
    verified = []
    for spec in REPORTS:
        row = _record(spec["name"])
        if not row:
            raise RuntimeError(f"Missing Report metadata: {spec['name']}")
        expected = {
            "name": spec["name"],
            "report_name": spec["name"],
            "ref_doctype": spec["ref_doctype"],
            "report_type": "Script Report",
            "is_standard": "Yes",
            "module": "Pharma Erp",
        }
        for fieldname, expected_value in expected.items():
            actual = row.get(fieldname)
            if actual != expected_value:
                raise RuntimeError(
                    f"{spec['name']}: {fieldname} expected {expected_value!r}, got {actual!r}"
                )
        if int(row.get("disabled") or 0) != 0:
            raise RuntimeError(f"{spec['name']}: Report is disabled")
        verified.append(dict(row))
    return verified


def rollback_report_metadata():
    names = _report_names()
    try:
        frappe.db.delete("Report", {"name": ["in", list(names)]})
        frappe.db.commit()
        frappe.clear_cache()
    except Exception:
        frappe.db.rollback()
        raise

    remaining = [name for name in names if frappe.db.exists("Report", name)]
    if remaining:
        raise RuntimeError(f"A.5 Report metadata rollback incomplete: {remaining}")
    return {"rolled_back": list(names)}
