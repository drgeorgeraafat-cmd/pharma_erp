"""Controlled installer and rollback metadata for v0.9.2 Step2B R1."""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint


CONTRACT_VERSION = "v0.9.2-step2b-r1"
STOCK_SETTING_FIELDS = ("enable_stock_reservation",)
CUSTOM_FIELDS = {
    "Sales Order": [
        {
            "fieldname": "custom_pharmacy_branch",
            "label": "Pharmacy Branch",
            "fieldtype": "Link",
            "options": "Branch",
            "insert_after": "company",
            "in_standard_filter": 1,
            "description": "Canonical Branch required by the controlled Step2B reservation contract.",
        }
    ],
    "Stock Reservation Entry": [
        {
            "fieldname": "custom_pharmacy_branch",
            "label": "Pharmacy Branch",
            "fieldtype": "Link",
            "options": "Branch",
            "insert_after": "project",
            "read_only": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_operational_role",
            "label": "Operational Role",
            "fieldtype": "Data",
            "insert_after": "custom_pharmacy_branch",
            "read_only": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_contract_state",
            "label": "Reservation Contract State",
            "fieldtype": "Select",
            "options": "Active\nPartially Used\nConsumed\nReleased\nExpired\nCancelled",
            "insert_after": "custom_operational_role",
            "read_only": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_idempotency_key",
            "label": "Reservation Idempotency Key",
            "fieldtype": "Data",
            "insert_after": "custom_contract_state",
            "read_only": 1,
            "hidden": 1,
            "unique": 1,
        },
        {
            "fieldname": "custom_original_reserved_qty",
            "label": "Original Reserved Qty",
            "fieldtype": "Float",
            "insert_after": "custom_idempotency_key",
            "read_only": 1,
        },
        {
            "fieldname": "custom_expires_at",
            "label": "Reservation Expires At",
            "fieldtype": "Datetime",
            "insert_after": "custom_original_reserved_qty",
        },
        {
            "fieldname": "custom_terminal_reason",
            "label": "Terminal Reason",
            "fieldtype": "Small Text",
            "insert_after": "custom_expires_at",
            "read_only": 1,
        },
        {
            "fieldname": "custom_terminal_at",
            "label": "Terminal At",
            "fieldtype": "Datetime",
            "insert_after": "custom_terminal_reason",
            "read_only": 1,
        },
        {
            "fieldname": "custom_terminal_by",
            "label": "Terminal By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_terminal_at",
            "read_only": 1,
        },
    ],
}


def _assert_state_path(output_path: str) -> Path:
    path = Path(output_path).resolve()
    if path.parent != Path("/tmp") or not path.name.startswith("Pharma_ERP_v0.9.2_Step2B_"):
        frappe.throw("Step2B state file must be a named file directly under /tmp.")
    return path


def _custom_field_name(doctype: str, fieldname: str) -> str | None:
    return frappe.db.get_value(
        "Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
    )


def _canonical_sales_targets() -> list[dict]:
    targets = []
    profiles = frappe.get_all(
        "Pharmacy Branch Profile",
        filters={"disabled": 0},
        fields=["name", "branch", "company", "allow_reservation"],
        order_by="company asc, branch asc, name asc",
        limit_page_length=10000,
    )
    for profile in profiles:
        mappings = frappe.get_all(
            "Pharmacy Branch Warehouse Role",
            filters={
                "parent": profile.name,
                "parenttype": "Pharmacy Branch Profile",
                "operational_role": "Sales",
            },
            fields=["warehouse"],
            order_by="idx asc, name asc",
        )
        if len(mappings) != 1:
            frappe.throw(
                f"Branch {profile.branch} must have exactly one canonical Sales warehouse; found {len(mappings)}."
            )
        warehouse = mappings[0].warehouse
        warehouse_profile = frappe.db.get_value(
            "Pharmacy Warehouse Profile",
            {
                "warehouse": warehouse,
                "branch": profile.branch,
                "company": profile.company,
                "disabled": 0,
            },
            ["name", "is_sellable", "allow_reservation"],
            as_dict=True,
        )
        if not warehouse_profile or not cint(warehouse_profile.is_sellable):
            frappe.throw(
                f"Canonical Sales warehouse {warehouse} for Branch {profile.branch} has no enabled sellable profile."
            )
        targets.append(
            {
                "branch_profile": profile.name,
                "branch": profile.branch,
                "company": profile.company,
                "warehouse_profile": warehouse_profile.name,
                "warehouse": warehouse,
            }
        )
    if not targets:
        frappe.throw("No enabled canonical Sales reservation target is configured.")
    return targets


def capture_state(output_path: str) -> dict:
    path = _assert_state_path(output_path)
    state = {
        "contract_version": CONTRACT_VERSION,
        "stock_settings": {
            fieldname: frappe.db.get_single_value("Stock Settings", fieldname)
            for fieldname in STOCK_SETTING_FIELDS
        },
        "branch_profiles": {
            row.name: cint(row.allow_reservation)
            for row in frappe.get_all(
                "Pharmacy Branch Profile",
                fields=["name", "allow_reservation"],
                limit_page_length=10000,
            )
        },
        "warehouse_profiles": {
            row.name: cint(row.allow_reservation)
            for row in frappe.get_all(
                "Pharmacy Warehouse Profile",
                fields=["name", "allow_reservation"],
                limit_page_length=10000,
            )
        },
        "custom_fields_present": {
            f"{doctype}::{field['fieldname']}": bool(
                _custom_field_name(doctype, field["fieldname"])
            )
            for doctype, fields in CUSTOM_FIELDS.items()
            for field in fields
        },
    }
    path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {"state_file": str(path), "contract_version": CONTRACT_VERSION}


def apply() -> dict:
    if frappe.db.count("Stock Reservation Entry"):
        frappe.throw(
            "Step2B R1 requires zero existing Stock Reservation Entry rows before installing the unique owner contract."
        )
    targets = _canonical_sales_targets()
    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Sales Order")
    frappe.clear_cache(doctype="Stock Reservation Entry")

    frappe.db.set_single_value("Stock Settings", "enable_stock_reservation", 1)
    for target in targets:
        frappe.db.set_value(
            "Pharmacy Branch Profile",
            target["branch_profile"],
            "allow_reservation",
            1,
            update_modified=False,
        )
        frappe.db.set_value(
            "Pharmacy Warehouse Profile",
            target["warehouse_profile"],
            "allow_reservation",
            1,
            update_modified=False,
        )

    return {
        "contract_version": CONTRACT_VERSION,
        "status": "APPLIED",
        "custom_fields": sum(len(fields) for fields in CUSTOM_FIELDS.values()),
        "canonical_sales_targets": len(targets),
        "stock_reservation_enabled": True,
    }


def verify_installation() -> dict:
    failures = []
    for doctype, fields in CUSTOM_FIELDS.items():
        meta = frappe.get_meta(doctype)
        for field in fields:
            if not meta.has_field(field["fieldname"]):
                failures.append(f"Missing {doctype}.{field['fieldname']}")
    if not cint(frappe.db.get_single_value("Stock Settings", "enable_stock_reservation")):
        failures.append("Stock Settings.enable_stock_reservation is not enabled")

    targets = _canonical_sales_targets()
    for target in targets:
        if not cint(
            frappe.db.get_value(
                "Pharmacy Branch Profile", target["branch_profile"], "allow_reservation"
            )
        ):
            failures.append(f"Branch profile {target['branch_profile']} is not reservation-enabled")
        if not cint(
            frappe.db.get_value(
                "Pharmacy Warehouse Profile",
                target["warehouse_profile"],
                "allow_reservation",
            )
        ):
            failures.append(
                f"Warehouse profile {target['warehouse_profile']} is not reservation-enabled"
            )
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "canonical_sales_targets": len(targets),
    }


def rollback_from_file(output_path: str) -> dict:
    path = _assert_state_path(output_path)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("contract_version") != CONTRACT_VERSION:
        frappe.throw("Rollback state belongs to another contract version.")
    if frappe.db.count("Stock Reservation Entry"):
        frappe.throw(
            "Step2B rollback is blocked because Stock Reservation Entry rows now exist. "
            "Review or restore the full backup instead of removing active reservation metadata."
        )

    for fieldname, value in state.get("stock_settings", {}).items():
        frappe.db.set_single_value("Stock Settings", fieldname, value)
    for name, value in state.get("branch_profiles", {}).items():
        if frappe.db.exists("Pharmacy Branch Profile", name):
            frappe.db.set_value(
                "Pharmacy Branch Profile",
                name,
                "allow_reservation",
                value,
                update_modified=False,
            )
    for name, value in state.get("warehouse_profiles", {}).items():
        if frappe.db.exists("Pharmacy Warehouse Profile", name):
            frappe.db.set_value(
                "Pharmacy Warehouse Profile",
                name,
                "allow_reservation",
                value,
                update_modified=False,
            )

    removed = []
    present_before = state.get("custom_fields_present", {})
    for doctype, fields in reversed(list(CUSTOM_FIELDS.items())):
        for field in reversed(fields):
            key = f"{doctype}::{field['fieldname']}"
            if present_before.get(key):
                continue
            custom_field = _custom_field_name(doctype, field["fieldname"])
            if custom_field:
                frappe.delete_doc(
                    "Custom Field",
                    custom_field,
                    force=1,
                    ignore_permissions=True,
                )
                removed.append(key)

    frappe.clear_cache(doctype="Sales Order")
    frappe.clear_cache(doctype="Stock Reservation Entry")
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "ROLLED_BACK",
        "removed_custom_fields": removed,
    }
