from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr


DOCTYPE = "Item Group"
ROOT = "All Item Groups"
DATA_FILE = Path(__file__).resolve().parent / "data" / "item_group_master_v0_7_65.json"


def _load_plan() -> dict[str, Any]:
    if not DATA_FILE.exists():
        frappe.throw(_("Item Group master data file is missing: {0}").format(DATA_FILE))

    with DATA_FILE.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)

    if plan.get("root") != ROOT:
        frappe.throw(_("Unexpected Item Group root in master data."))

    groups = plan.get("groups") or []
    if not groups:
        frappe.throw(_("Item Group master structure is empty."))

    names = [cstr(row.get("name")).strip() for row in groups]
    if any(not name for name in names):
        frappe.throw(_("Item Group master contains an empty name."))
    if len(names) != len(set(names)):
        frappe.throw(_("Item Group master contains duplicate names."))

    planned = set(names)
    for row in groups:
        parent = cstr(row.get("parent")).strip()
        if parent != ROOT and parent not in planned:
            frappe.throw(
                _("Parent {0} for Item Group {1} is not in the master plan.").format(
                    parent, row.get("name")
                )
            )

    return plan


def _existing_state(name: str) -> dict[str, Any] | None:
    row = frappe.db.get_value(
        DOCTYPE,
        name,
        ["name", "item_group_name", "parent_item_group", "is_group"],
        as_dict=True,
    )
    return row


def _check_root() -> None:
    root = _existing_state(ROOT)
    if not root:
        frappe.throw(_("ERPNext root Item Group {0} does not exist.").format(ROOT))
    if cint(root.is_group) != 1:
        frappe.throw(_("ERPNext root Item Group must be a group."))


def _sort_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = [dict(row) for row in groups]
    ordered: list[dict[str, Any]] = []
    available = {ROOT}

    while pending:
        progressed = False
        remaining: list[dict[str, Any]] = []

        for row in sorted(
            pending,
            key=lambda value: (
                cint(value.get("sort_order")),
                cstr(value.get("name")),
            ),
        ):
            if row.get("parent") in available:
                ordered.append(row)
                available.add(row["name"])
                progressed = True
            else:
                remaining.append(row)

        if not progressed:
            frappe.throw(_("Item Group master contains a parent cycle or missing parent."))

        pending = remaining

    return ordered


def _classify(plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "matched": [],
        "missing": [],
        "conflicts": [],
    }

    for spec in _sort_groups(plan["groups"]):
        existing = _existing_state(spec["name"])
        if not existing:
            result["missing"].append(spec)
            continue

        expected_parent = cstr(spec["parent"])
        expected_is_group = cint(spec["is_group"])
        actual_parent = cstr(existing.parent_item_group)
        actual_is_group = cint(existing.is_group)

        if actual_parent == expected_parent and actual_is_group == expected_is_group:
            result["matched"].append(spec)
        else:
            result["conflicts"].append(
                {
                    **spec,
                    "actual_parent": actual_parent,
                    "actual_is_group": actual_is_group,
                }
            )

    return result


def preview() -> dict[str, Any]:
    _check_root()
    plan = _load_plan()
    classification = _classify(plan)

    return {
        "status": "ok" if not classification["conflicts"] else "conflict",
        "step": "v0.7.65 Step 5 — Item Group Master Structure",
        "root": ROOT,
        "planned_count": len(plan["groups"]),
        "matched_count": len(classification["matched"]),
        "missing_count": len(classification["missing"]),
        "conflict_count": len(classification["conflicts"]),
        "matched": [row["name"] for row in classification["matched"]],
        "missing": [row["name"] for row in classification["missing"]],
        "conflicts": classification["conflicts"],
        "destructive_cleanup": False,
        "extra_existing_groups_allowed": True,
        "data_migration": False,
    }


@frappe.whitelist()
def install() -> dict[str, Any]:
    frappe.set_user("Administrator")
    _check_root()
    plan = _load_plan()
    classification = _classify(plan)

    if classification["conflicts"]:
        frappe.throw(
            _("Item Group conflicts must be reviewed before installation: {0}").format(
                frappe.as_json(classification["conflicts"])
            )
        )

    created: list[str] = []

    for spec in _sort_groups(plan["groups"]):
        if _existing_state(spec["name"]):
            continue

        doc = frappe.get_doc(
            {
                "doctype": DOCTYPE,
                "item_group_name": spec["name"],
                "parent_item_group": spec["parent"],
                "is_group": cint(spec["is_group"]),
            }
        )
        doc.insert()
        created.append(spec["name"])

    frappe.clear_cache(doctype=DOCTYPE)
    frappe.db.commit()

    final = _classify(plan)
    if final["missing"] or final["conflicts"]:
        frappe.throw(
            _("Item Group master verification failed after installation: {0}").format(
                frappe.as_json(final)
            )
        )

    return {
        "status": "ok",
        "step": "v0.7.65 Step 5 — Item Group Master Structure",
        "planned_count": len(plan["groups"]),
        "created_count": len(created),
        "created": created,
        "matched_count": len(final["matched"]),
        "destructive_cleanup": False,
        "extra_existing_groups_allowed": True,
        "data_migration": False,
        "production_catalog_import": False,
    }
