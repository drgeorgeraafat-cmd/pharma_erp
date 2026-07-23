from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr
from frappe.utils.nestedset import rebuild_tree


DOCTYPE = "Item Group"

EXPECTED = {
    "Drops": {"parent": "Medicines", "is_group": 0, "linked_items": 0},
    "Injections": {"parent": "Medicines", "is_group": 0, "linked_items": 0},
    "Baby Care": {"parent": "All Item Groups", "is_group": 1, "linked_items": 0},
    "Eye Drops": {"parent": "Medicines", "is_group": 0, "linked_items": 0},
    "Ear Drops": {"parent": "Medicines", "is_group": 0, "linked_items": 0},
}

TARGETS = {
    "Drops": {"parent": "Medicines", "is_group": 1},
    "Injections": {"parent": "Medicines", "is_group": 1},
    "Baby Care": {"parent": "Mother & Baby", "is_group": 1},
    "Eye Drops": {"parent": "Drops", "is_group": 0},
    "Ear Drops": {"parent": "Drops", "is_group": 0},
}


def _state(name: str) -> dict[str, Any]:
    row = frappe.db.get_value(
        DOCTYPE,
        name,
        ["name", "parent_item_group", "is_group"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Required Item Group {0} does not exist.").format(name))

    return {
        "name": name,
        "parent": cstr(row.parent_item_group),
        "is_group": cint(row.is_group),
        "linked_items": frappe.db.count("Item", {"item_group": name}),
    }


def preview() -> dict[str, Any]:
    current = {name: _state(name) for name in EXPECTED}
    mismatches = []

    for name, expected in EXPECTED.items():
        for field, expected_value in expected.items():
            actual = current[name][field]
            if actual != expected_value:
                mismatches.append(
                    {
                        "name": name,
                        "field": field,
                        "expected": expected_value,
                        "actual": actual,
                    }
                )

    return {
        "status": "ok" if not mismatches else "unexpected_state",
        "step": "v0.7.65 Step 5A — Item Group Conflict Resolution",
        "current": current,
        "targets": TARGETS,
        "mismatches": mismatches,
        "linked_item_moves_required": False,
        "destructive_cleanup": False,
    }


def _save_group(name: str, parent: str | None = None, is_group: int | None = None) -> None:
    doc = frappe.get_doc(DOCTYPE, name)
    changed = False

    if parent is not None and cstr(doc.parent_item_group) != parent:
        doc.parent_item_group = parent
        changed = True

    if is_group is not None and cint(doc.is_group) != cint(is_group):
        doc.is_group = cint(is_group)
        changed = True

    if changed:
        doc.flags.ignore_permissions = True
        doc.save()


@frappe.whitelist()
def install() -> dict[str, Any]:
    frappe.set_user("Administrator")

    before = preview()
    if before["mismatches"]:
        frappe.throw(
            _("Item Group conflict baseline changed: {0}").format(
                frappe.as_json(before["mismatches"])
            )
        )

    _save_group("Drops", is_group=1)
    _save_group("Injections", is_group=1)
    _save_group("Baby Care", parent="Mother & Baby")
    _save_group("Eye Drops", parent="Drops")
    _save_group("Ear Drops", parent="Drops")

    rebuild_tree(DOCTYPE, "parent_item_group")
    frappe.clear_cache(doctype=DOCTYPE)
    frappe.db.commit()

    final = {name: _state(name) for name in TARGETS}
    mismatches = []

    for name, target in TARGETS.items():
        for field, expected_value in target.items():
            actual = final[name][field]
            if actual != expected_value:
                mismatches.append(
                    {
                        "name": name,
                        "field": field,
                        "expected": expected_value,
                        "actual": actual,
                    }
                )

    if mismatches:
        frappe.throw(
            _("Item Group repair verification failed: {0}").format(
                frappe.as_json(mismatches)
            )
        )

    return {
        "status": "ok",
        "step": "v0.7.65 Step 5A — Item Group Conflict Resolution",
        "updated": final,
        "linked_item_moves_required": False,
        "destructive_cleanup": False,
    }
