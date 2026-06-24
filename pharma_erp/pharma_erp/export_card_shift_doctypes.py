"""Export the live card/shift financial DocTypes into the app tree.

Run explicitly from the bench before migrate:
    bench --site <site> execute \
      pharma_erp.pharma_erp.export_card_shift_doctypes.execute

This is a development utility. It does not change database records.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import frappe


DOCTYPE_NAMES = (
    "Card POS Terminal",
    "Card Settlement Batch Item",
    "Card Settlement Batch",
    "Card Bank Settlement Allocation",
    "Card Bank Settlement",
    "Payment Method Clearing Setup",
    "Shift Payment Reconciliation Item",
    "Shift Payment Reconciliation",
    "Shift Cash Movement",
)

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
    # .../apps/pharma_erp/pharma_erp/pharma_erp/export_card_shift_doctypes.py
    # app root is the first parent that contains pyproject/setup config and
    # the package directory named pharma_erp.
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


def _doctype_payload(doctype_name: str) -> dict:
    doc = frappe.get_doc("DocType", doctype_name)
    payload = _clean_row(doc.as_dict(no_nulls=False))

    # Convert the database-created Custom DocType into an app-owned DocType.
    payload["custom"] = 0
    payload["module"] = "Pharma Erp"
    payload["doctype"] = "DocType"
    payload["name"] = doctype_name

    return payload


def _controller_source(doctype_name: str) -> str:
    class_name = _class_name(doctype_name)
    return (
        "from frappe.model.document import Document\n\n\n"
        f"class {class_name}(Document):\n"
        "    pass\n"
    )


def execute():
    missing = [
        name for name in DOCTYPE_NAMES
        if not frappe.db.exists("DocType", name)
    ]
    if missing:
        frappe.throw(
            "Missing required DocTypes: " + ", ".join(missing)
        )

    app_root = _app_root()
    doctype_root = app_root / "pharma_erp" / "pharma_erp" / "doctype"
    exported = []

    for doctype_name in DOCTYPE_NAMES:
        folder_name = _scrub(doctype_name)
        folder = doctype_root / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        init_path = folder / "__init__.py"
        init_path.touch(exist_ok=True)

        json_path = folder / f"{folder_name}.json"
        json_path.write_text(
            json.dumps(
                _doctype_payload(doctype_name),
                ensure_ascii=False,
                indent=1,
                sort_keys=True,
                default=str,
            ) + "\n",
            encoding="utf-8",
        )

        controller_path = folder / f"{folder_name}.py"
        if not controller_path.exists():
            controller_path.write_text(
                _controller_source(doctype_name),
                encoding="utf-8",
            )

        exported.append(
            {
                "doctype": doctype_name,
                "json": str(json_path),
                "controller": str(controller_path),
            }
        )

    print(json.dumps(exported, ensure_ascii=False, indent=2))
    return exported
