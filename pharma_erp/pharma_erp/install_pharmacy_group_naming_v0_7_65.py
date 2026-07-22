from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cstr


DOCTYPE = "Pharmacy Group"


def _clean_group_name(value: str | None) -> str:
    cleaned = cstr(value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*&\s*", " & ", cleaned)
    return cleaned.strip()


def _assert_metadata() -> None:
    row = frappe.db.get_value(
        "DocType",
        DOCTYPE,
        [
            "autoname",
            "title_field",
            "search_fields",
            "show_title_field_in_link",
            "allow_rename",
        ],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("{0} DocType was not found.").format(DOCTYPE))

    expected = {
        "autoname": "field:group_name",
        "title_field": "group_name",
        "search_fields": "group_name",
        "show_title_field_in_link": 1,
        "allow_rename": 1,
    }
    mismatches = {
        key: {"expected": expected_value, "actual": row.get(key)}
        for key, expected_value in expected.items()
        if cstr(row.get(key)) != cstr(expected_value)
    }
    if mismatches:
        frappe.throw(
            _("Pharmacy Group metadata is not ready: {0}").format(
                frappe.as_json(mismatches)
            )
        )


def _planned_renames() -> list[tuple[str, str]]:
    rows = frappe.get_all(
        DOCTYPE,
        fields=["name", "group_name"],
        order_by="creation asc, name asc",
    )

    planned: list[tuple[str, str]] = []
    seen_targets: dict[str, str] = {}

    for row in rows:
        old_name = cstr(row.name)
        target = _clean_group_name(row.group_name or old_name)

        if not target:
            frappe.throw(_("Pharmacy Group {0} has no Group Name.").format(old_name))

        key = target.casefold()
        prior = seen_targets.get(key)
        if prior and prior != old_name:
            frappe.throw(
                _("Duplicate normalized Pharmacy Group target {0}: {1}, {2}").format(
                    target, prior, old_name
                )
            )

        seen_targets[key] = old_name

        if old_name != target:
            planned.append((old_name, target))

    return planned


def _rename_existing_groups() -> list[dict[str, str]]:
    planned = _planned_renames()
    renamed: list[dict[str, str]] = []

    frappe.set_user("Administrator")

    for old_name, target in planned:
        if not frappe.db.exists(DOCTYPE, old_name):
            continue

        if frappe.db.exists(DOCTYPE, target):
            frappe.throw(
                _("Cannot rename {0} to {1}: target already exists.").format(
                    old_name, target
                )
            )

        frappe.rename_doc(
            DOCTYPE,
            old_name,
            target,
            force=True,
            merge=False,
            show_alert=False,
        )

        frappe.db.set_value(
            DOCTYPE,
            target,
            "group_name",
            target,
            update_modified=False,
        )

        renamed.append({"from": old_name, "to": target})

    return renamed


@frappe.whitelist()
def install() -> dict:
    _assert_metadata()
    renamed = _rename_existing_groups()

    frappe.clear_cache(doctype=DOCTYPE)
    frappe.clear_cache(doctype="Item")
    frappe.db.commit()

    records = frappe.get_all(
        DOCTYPE,
        fields=["name", "group_name"],
        order_by="name asc",
    )

    return {
        "status": "ok",
        "step": "v0.7.65 Step 3 Repair 2D — Metadata Call Fix",
        "renamed": renamed,
        "records": records,
    }
