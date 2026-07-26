from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc
from frappe.utils import cint, cstr


DOCTYPE = "Online Category"
ITEM_DOCTYPE = "Item"
ITEM_LINK_FIELD = "custom_online_category"
DATA_FILE = Path(__file__).resolve().parent / "data" / "online_category_master_v0_7_65.json"
STEP = "v0.7.65 Step 7 — Online Category Master Tree"


def _clean(value: Any) -> str:
    return cstr(value).strip()


def _load_plan() -> dict[str, Any]:
    if not DATA_FILE.exists():
        frappe.throw(_("Online Category master data file is missing: {0}").format(DATA_FILE))

    with DATA_FILE.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)

    if plan.get("doctype") != DOCTYPE:
        frappe.throw(_("Unexpected DocType in Online Category master data."))

    categories = plan.get("categories") or []
    if not categories:
        frappe.throw(_("Online Category master tree is empty."))

    names = [_clean(row.get("name")) for row in categories]
    if any(not name for name in names):
        frappe.throw(_("Online Category master contains an empty name."))
    if len(names) != len(set(names)):
        frappe.throw(_("Online Category master contains duplicate names."))

    planned = set(names)
    child_count: dict[str, int] = {name: 0 for name in names}

    for row in categories:
        name = _clean(row.get("name"))
        parent = _clean(row.get("parent"))
        if parent and parent not in planned:
            frappe.throw(
                _("Parent {0} for Online Category {1} is not in the master plan.").format(
                    parent, name
                )
            )
        if parent == name:
            frappe.throw(_("Online Category {0} cannot be its own parent.").format(name))
        if parent:
            child_count[parent] += 1

    for row in categories:
        name = _clean(row.get("name"))
        expected_group = cint(row.get("is_group"))
        has_planned_children = child_count[name] > 0
        if expected_group != cint(has_planned_children):
            frappe.throw(
                _("Online Category group flag does not match its children: {0}").format(name)
            )

    _sort_categories(categories)

    renames = plan.get("legacy_renames") or []
    old_names: set[str] = set()
    new_names: set[str] = set()
    for row in renames:
        old = _clean(row.get("from"))
        new = _clean(row.get("to"))
        if not old or not new or old == new:
            frappe.throw(_("Online Category legacy rename entry is invalid."))
        if new not in planned:
            frappe.throw(
                _("Legacy rename target {0} is not in the master plan.").format(new)
            )
        if old in planned:
            frappe.throw(
                _("Legacy Online Category name {0} must not remain in the master plan.").format(
                    old
                )
            )
        if old in old_names or new in new_names:
            frappe.throw(_("Online Category legacy rename entries contain duplicates."))
        old_names.add(old)
        new_names.add(new)

    return plan


def _sort_categories(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = [dict(row) for row in categories]
    ordered: list[dict[str, Any]] = []
    available = {""}

    while pending:
        progressed = False
        remaining: list[dict[str, Any]] = []

        for row in sorted(
            pending,
            key=lambda value: (
                _clean(value.get("parent")),
                cint(value.get("sort_order")),
                _clean(value.get("name")),
            ),
        ):
            if _clean(row.get("parent")) in available:
                ordered.append(row)
                available.add(_clean(row.get("name")))
                progressed = True
            else:
                remaining.append(row)

        if not progressed:
            frappe.throw(
                _("Online Category master contains a parent cycle or missing parent.")
            )

        pending = remaining

    return ordered


def _existing_state(name: str) -> dict[str, Any] | None:
    return frappe.db.get_value(
        DOCTYPE,
        name,
        [
            "name",
            "category_name",
            "category_name_ar",
            "parent_online_category",
            "is_group",
            "enabled",
            "sort_order",
            "lft",
            "rgt",
        ],
        as_dict=True,
    )


def _item_links(category: str) -> list[str]:
    if not category:
        return []
    return frappe.get_all(
        ITEM_DOCTYPE,
        filters={ITEM_LINK_FIELD: category},
        pluck="name",
        order_by="name asc",
    )


def _children(category: str) -> list[str]:
    return frappe.get_all(
        DOCTYPE,
        filters={"parent_online_category": category},
        pluck="name",
        order_by="name asc",
    )


def _is_descendant(node: dict[str, Any], possible_parent: dict[str, Any] | None) -> bool:
    if not possible_parent:
        return False
    node_lft = cint(node.get("lft"))
    node_rgt = cint(node.get("rgt"))
    parent_lft = cint(possible_parent.get("lft"))
    parent_rgt = cint(possible_parent.get("rgt"))
    if not all((node_lft, node_rgt, parent_lft, parent_rgt)):
        return False
    return node_lft < parent_lft < parent_rgt < node_rgt


def _differences(spec: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "category_name": _clean(spec.get("name")),
        "category_name_ar": _clean(spec.get("name_ar")),
        "parent_online_category": _clean(spec.get("parent")),
        "is_group": cint(spec.get("is_group")),
        "enabled": cint(spec.get("enabled")),
        "sort_order": cint(spec.get("sort_order")),
    }
    actual = {
        "category_name": _clean(existing.get("category_name")),
        "category_name_ar": _clean(existing.get("category_name_ar")),
        "parent_online_category": _clean(existing.get("parent_online_category")),
        "is_group": cint(existing.get("is_group")),
        "enabled": cint(existing.get("enabled")),
        "sort_order": cint(existing.get("sort_order")),
    }

    return {
        field: {"current": actual[field], "expected": expected[field]}
        for field in expected
        if actual[field] != expected[field]
    }


def _classify(plan: dict[str, Any]) -> dict[str, Any]:
    categories = plan["categories"]
    planned_names = {_clean(row.get("name")) for row in categories}
    spec_by_name = {_clean(row.get("name")): row for row in categories}
    legacy_by_target = {
        _clean(row.get("to")): _clean(row.get("from"))
        for row in (plan.get("legacy_renames") or [])
    }
    legacy_names = set(legacy_by_target.values())

    result: dict[str, Any] = {
        "matched": [],
        "missing": [],
        "updates": [],
        "renames": [],
        "already_renamed": [],
        "conflicts": [],
        "legacy_item_links": [],
        "extras": [],
    }

    for target, old in legacy_by_target.items():
        old_state = _existing_state(old)
        target_state = _existing_state(target)
        linked_items = _item_links(old)

        if old_state and target_state:
            result["conflicts"].append(
                {
                    "type": "legacy_rename_target_exists",
                    "from": old,
                    "to": target,
                    "message": "Both legacy and target Online Categories exist.",
                }
            )
        elif old_state:
            result["renames"].append({"from": old, "to": target})
        elif target_state:
            result["already_renamed"].append({"from": old, "to": target})

        if linked_items:
            result["legacy_item_links"].append(
                {"from": old, "to": target, "items": linked_items}
            )

    for spec in _sort_categories(categories):
        name = _clean(spec.get("name"))
        old = legacy_by_target.get(name)
        existing = _existing_state(name)
        effective = existing or (_existing_state(old) if old else None)

        if not effective:
            result["missing"].append(name)
            continue

        expected_group = cint(spec.get("is_group"))
        children = _children(effective.name)
        item_links = _item_links(effective.name)

        if expected_group and item_links:
            result["conflicts"].append(
                {
                    "type": "group_has_item_links",
                    "category": effective.name,
                    "planned_name": name,
                    "items": item_links,
                }
            )
            continue

        if not expected_group and children:
            result["conflicts"].append(
                {
                    "type": "leaf_has_children",
                    "category": effective.name,
                    "planned_name": name,
                    "children": children,
                }
            )
            continue

        expected_parent = _clean(spec.get("parent"))
        if expected_parent and expected_parent != _clean(effective.parent_online_category):
            parent_state = _existing_state(expected_parent)
            if _is_descendant(effective, parent_state):
                result["conflicts"].append(
                    {
                        "type": "parent_cycle",
                        "category": effective.name,
                        "planned_parent": expected_parent,
                    }
                )
                continue

        if old and not existing and _existing_state(old):
            # The rename itself accounts for category_name/name differences.
            virtual = dict(effective)
            virtual["category_name"] = name
            differences = _differences(spec, virtual)
        else:
            differences = _differences(spec, effective)

        if differences:
            result["updates"].append(
                {
                    "name": name,
                    "current_name": effective.name,
                    "differences": differences,
                }
            )
        else:
            result["matched"].append(name)

    existing_names = set(frappe.get_all(DOCTYPE, pluck="name"))
    result["extras"] = sorted(existing_names - planned_names - legacy_names)

    for group_name in sorted(
        _clean(row.get("name")) for row in categories if cint(row.get("is_group"))
    ):
        links = _item_links(group_name)
        if links and not any(
            row.get("type") == "group_has_item_links"
            and row.get("category") == group_name
            for row in result["conflicts"]
        ):
            result["conflicts"].append(
                {
                    "type": "group_has_item_links",
                    "category": group_name,
                    "planned_name": group_name,
                    "items": links,
                }
            )

    return result


def _tree_verification(plan: dict[str, Any]) -> dict[str, Any]:
    categories = plan["categories"]
    planned_names = {_clean(row.get("name")) for row in categories}
    rows = {
        row.name: row
        for row in frappe.get_all(
            DOCTYPE,
            fields=[
                "name",
                "parent_online_category",
                "is_group",
                "enabled",
                "sort_order",
                "lft",
                "rgt",
            ],
        )
    }

    errors: list[dict[str, Any]] = []
    boundaries: list[int] = []

    for name, row in rows.items():
        lft = cint(row.lft)
        rgt = cint(row.rgt)
        if lft <= 0 or rgt <= lft:
            errors.append({"type": "invalid_nested_set_bounds", "category": name})
        else:
            boundaries.extend([lft, rgt])

    if len(boundaries) != len(set(boundaries)):
        errors.append({"type": "duplicate_nested_set_boundaries"})

    for spec in categories:
        name = _clean(spec.get("name"))
        row = rows.get(name)
        if not row:
            errors.append({"type": "missing_category", "category": name})
            continue

        parent = _clean(spec.get("parent"))
        if _clean(row.parent_online_category) != parent:
            errors.append(
                {
                    "type": "wrong_parent",
                    "category": name,
                    "current": _clean(row.parent_online_category),
                    "expected": parent,
                }
            )

        if parent:
            parent_row = rows.get(parent)
            if not parent_row or not (
                cint(parent_row.lft)
                < cint(row.lft)
                < cint(row.rgt)
                < cint(parent_row.rgt)
            ):
                errors.append(
                    {"type": "nested_set_parent_mismatch", "category": name}
                )

        if cint(spec.get("is_group")):
            links = _item_links(name)
            if links:
                errors.append(
                    {"type": "group_has_item_links", "category": name, "items": links}
                )
        elif _children(name):
            errors.append({"type": "leaf_has_children", "category": name})

    legacy_remaining = [
        _clean(row.get("from"))
        for row in (plan.get("legacy_renames") or [])
        if frappe.db.exists(DOCTYPE, _clean(row.get("from")))
    ]
    if legacy_remaining:
        errors.append(
            {"type": "legacy_categories_remaining", "categories": legacy_remaining}
        )

    return {
        "status": "ok" if not errors else "error",
        "planned_nodes_checked": len(planned_names),
        "all_nodes_checked": len(rows),
        "errors": errors,
    }


def preview() -> dict[str, Any]:
    plan = _load_plan()
    classification = _classify(plan)
    categories = plan["categories"]

    return {
        "status": "ok" if not classification["conflicts"] else "conflict",
        "step": STEP,
        "planned_count": len(categories),
        "root_count": sum(1 for row in categories if not _clean(row.get("parent"))),
        "group_count": sum(cint(row.get("is_group")) for row in categories),
        "leaf_count": sum(1 for row in categories if not cint(row.get("is_group"))),
        "current_category_count": len(frappe.get_all(DOCTYPE, pluck="name")),
        "matched_count": len(classification["matched"]),
        "missing_count": len(classification["missing"]),
        "update_count": len(classification["updates"]),
        "rename_count": len(classification["renames"]),
        "already_renamed_count": len(classification["already_renamed"]),
        "conflict_count": len(classification["conflicts"]),
        "extra_existing_count": len(classification["extras"]),
        "matched": classification["matched"],
        "missing": classification["missing"],
        "updates": classification["updates"],
        "renames": classification["renames"],
        "already_renamed": classification["already_renamed"],
        "legacy_item_links": classification["legacy_item_links"],
        "conflicts": classification["conflicts"],
        "extra_existing_categories": classification["extras"],
        "item_group_changes": False,
        "show_online_changes": False,
        "requires_prescription_changes": False,
        "extra_existing_categories_allowed": True,
        "legacy_category_conversion_only": True,
    }


def _apply_legacy_renames(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    renamed: list[dict[str, Any]] = []
    migrated_items: list[str] = []

    for row in plan.get("legacy_renames") or []:
        old = _clean(row.get("from"))
        new = _clean(row.get("to"))
        old_exists = bool(frappe.db.exists(DOCTYPE, old))
        new_exists = bool(frappe.db.exists(DOCTYPE, new))

        if old_exists and new_exists:
            frappe.throw(
                _("Cannot rename Online Category {0}: target {1} already exists.").format(
                    old, new
                )
            )
        if not old_exists:
            continue

        linked_items = _item_links(old)
        rename_doc(DOCTYPE, old, new, force=True)

        if frappe.db.exists(DOCTYPE, old) or not frappe.db.exists(DOCTYPE, new):
            frappe.throw(
                _("Online Category rename failed: {0} to {1}.").format(old, new)
            )

        doc = frappe.get_doc(DOCTYPE, new)
        doc.category_name = new
        doc.save(ignore_permissions=True)

        for item_name in linked_items:
            current = _clean(
                frappe.db.get_value(ITEM_DOCTYPE, item_name, ITEM_LINK_FIELD)
            )
            if current == old:
                frappe.db.set_value(
                    ITEM_DOCTYPE,
                    item_name,
                    ITEM_LINK_FIELD,
                    new,
                    update_modified=False,
                )
            final = _clean(
                frappe.db.get_value(ITEM_DOCTYPE, item_name, ITEM_LINK_FIELD)
            )
            if final != new:
                frappe.throw(
                    _("Item {0} was not migrated to Online Category {1}.").format(
                        item_name, new
                    )
                )
            migrated_items.append(item_name)

        renamed.append({"from": old, "to": new, "items": linked_items})

    return renamed, sorted(set(migrated_items))


def _upsert_categories(plan: dict[str, Any]) -> tuple[list[str], list[str]]:
    created: list[str] = []
    updated: list[str] = []

    for spec in _sort_categories(plan["categories"]):
        name = _clean(spec.get("name"))
        values = {
            "category_name": name,
            "category_name_ar": _clean(spec.get("name_ar")),
            "parent_online_category": _clean(spec.get("parent")) or None,
            "is_group": cint(spec.get("is_group")),
            "enabled": cint(spec.get("enabled")),
            "sort_order": cint(spec.get("sort_order")),
        }

        if not frappe.db.exists(DOCTYPE, name):
            doc = frappe.get_doc({"doctype": DOCTYPE, **values})
            doc.insert(ignore_permissions=True)
            created.append(name)
            continue

        doc = frappe.get_doc(DOCTYPE, name)
        existing = _existing_state(name)
        differences = _differences(spec, existing)
        if not differences:
            continue

        for field, value in values.items():
            doc.set(field, value)
        doc.save(ignore_permissions=True)
        updated.append(name)

    return created, updated


@frappe.whitelist()
def install() -> dict[str, Any]:
    frappe.set_user("Administrator")
    plan = _load_plan()
    before = _classify(plan)

    if before["conflicts"]:
        frappe.throw(
            _("Online Category conflicts must be reviewed before installation: {0}").format(
                frappe.as_json(before["conflicts"])
            )
        )

    try:
        renamed, migrated_items = _apply_legacy_renames(plan)
        created, updated = _upsert_categories(plan)

        frappe.clear_cache(doctype=DOCTYPE)

        final = _classify(plan)
        tree = _tree_verification(plan)

        if (
            final["missing"]
            or final["updates"]
            or final["renames"]
            or final["conflicts"]
            or tree["status"] != "ok"
        ):
            frappe.throw(
                _("Online Category verification failed after installation: {0}").format(
                    frappe.as_json({"classification": final, "tree": tree})
                )
            )

        frappe.db.commit()

        return {
            "status": "ok",
            "step": STEP,
            "planned_count": len(plan["categories"]),
            "created_count": len(created),
            "updated_count": len(updated),
            "renamed_count": len(renamed),
            "migrated_item_count": len(migrated_items),
            "created": created,
            "updated": updated,
            "renamed": renamed,
            "migrated_items": migrated_items,
            "matched_count": len(final["matched"]),
            "extra_existing_categories": final["extras"],
            "tree_verification": tree,
            "item_group_changes": False,
            "show_online_changes": False,
            "requires_prescription_changes": False,
            "automatic_item_classification": False,
        }
    except Exception:
        frappe.db.rollback()
        raise
