"""Export the live Cash Drawer DocType into the app tree.

Run explicitly from the bench before migrate:
    bench --site <site> execute \
      pharma_erp.pharma_erp.export_cash_drawer_doctype.execute

This development utility writes the live DocType schema to the app and does not
change transactional data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import frappe


DOCTYPE_NAME = "Cash Drawer"
SYSTEM_KEYS_TO_DROP = {
    "_comments",
    "_liked_by",
    "_seen",
    "_user_tags",
}


def _scrub(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _class_name(value: str) -> str:
    return "".join(part for part in re.split(r"[^A-Za-z0-9]+", value) if part)


def _app_root() -> Path:
    current = Path(__file__).resolve()
    return current.parents[2]


def _clean_row(row):
    if isinstance(row, list):
        return [_clean_row(item) for item in row]
    if not isinstance(row, dict):
        return row

    cleaned = {}
    for key, value in row.items():
        if key in SYSTEM_KEYS_TO_DROP:
            continue
        cleaned[key] = _clean_row(value)
    return cleaned


def _doctype_payload() -> dict:
    doc = frappe.get_doc("DocType", DOCTYPE_NAME)
    payload = _clean_row(doc.as_dict(no_nulls=False))
    payload["custom"] = 0
    payload["module"] = "Pharma Erp"
    payload["doctype"] = "DocType"
    payload["name"] = DOCTYPE_NAME
    return payload


def _controller_source() -> str:
    class_name = _class_name(DOCTYPE_NAME)
    return (
        "from frappe.model.document import Document\n\n\n"
        f"class {class_name}(Document):\n"
        "    pass\n"
    )


def execute():
    if not frappe.db.exists("DocType", DOCTYPE_NAME):
        frappe.throw("Required DocType is missing: " + DOCTYPE_NAME)

    app_root = _app_root()
    folder_name = _scrub(DOCTYPE_NAME)
    folder = app_root / "pharma_erp" / "pharma_erp" / "doctype" / folder_name
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "__init__.py").touch(exist_ok=True)

    json_path = folder / f"{folder_name}.json"
    json_path.write_text(
        json.dumps(
            _doctype_payload(),
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
            default=str,
        ) + "\n",
        encoding="utf-8",
    )

    controller_path = folder / f"{folder_name}.py"
    if not controller_path.exists():
        controller_path.write_text(_controller_source(), encoding="utf-8")

    result = {
        "doctype": DOCTYPE_NAME,
        "json": str(json_path),
        "controller": str(controller_path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result
