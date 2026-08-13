"""Controlled metadata installer for v0.9.2 Step2C R7."""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


CONTRACT_VERSION = "v0.9.2-step2c-r7"
PAGE_NAME = "customer-reservation-operations"
LEGACY_R1_SALES_INVOICE_FIELDS = (
    "custom_customer_reservation_sales_order",
    "custom_customer_reservation_mode",
)
CUSTOM_FIELDS = {
    "Sales Order": [
        {
            "fieldname": "custom_customer_reservation",
            "label": "Customer Reservation",
            "fieldtype": "Check",
            "insert_after": "custom_pharmacy_branch",
            "read_only": 1,
            "in_standard_filter": 1,
            "description": "Operational Step2C reservation backed by standard Sales Order and SRE stock truth.",
        },
        {
            "fieldname": "custom_reservation_request_key",
            "label": "Reservation Request Key",
            "fieldtype": "Data",
            "insert_after": "custom_customer_reservation",
            "read_only": 1,
            "hidden": 1,
            "unique": 1,
        },
        {
            "fieldname": "custom_reservation_review_at",
            "label": "Reservation Review At",
            "fieldtype": "Datetime",
            "insert_after": "custom_reservation_request_key",
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_reservation_fulfilment_mode",
            "label": "Reservation Fulfilment Mode",
            "fieldtype": "Select",
            "options": "Undecided\nPickup\nHome Delivery",
            "insert_after": "custom_reservation_review_at",
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_reservation_operational_status",
            "label": "Reservation Operational Status",
            "fieldtype": "Select",
            "options": "Active\nReview Required\nPartially Fulfilled\nPicked Up\nSent for Delivery\nFulfilled\nReleased\nCancelled",
            "insert_after": "custom_reservation_fulfilment_mode",
            "read_only": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_reservation_notes",
            "label": "Reservation Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_reservation_operational_status",
        },
        {
            "fieldname": "custom_reservation_last_contact_outcome",
            "label": "Last Contact Outcome",
            "fieldtype": "Select",
            "options": "\nStill Needed\nConfirmed Pickup\nConfirmed Delivery\nNo Answer\nDeclined\nOther",
            "insert_after": "custom_reservation_notes",
            "read_only": 1,
        },
        {
            "fieldname": "custom_reservation_last_contact_at",
            "label": "Last Contact At",
            "fieldtype": "Datetime",
            "insert_after": "custom_reservation_last_contact_outcome",
            "read_only": 1,
        },
        {
            "fieldname": "custom_reservation_last_contact_by",
            "label": "Last Contact By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_reservation_last_contact_at",
            "read_only": 1,
        },
        {
            "fieldname": "custom_reservation_last_contact_notes",
            "label": "Last Contact Notes",
            "fieldtype": "Small Text",
            "insert_after": "custom_reservation_last_contact_by",
            "read_only": 1,
        },
        {
            "fieldname": "custom_reservation_fulfilment_invoice",
            "label": "Reservation Fulfilment Invoice",
            "fieldtype": "Link",
            "options": "Sales Invoice",
            "insert_after": "custom_reservation_last_contact_notes",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_reservation_fulfilment_at",
            "label": "Reservation Fulfilment At",
            "fieldtype": "Datetime",
            "insert_after": "custom_reservation_fulfilment_invoice",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_reservation_fulfilment_by",
            "label": "Reservation Fulfilment By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_reservation_fulfilment_at",
            "read_only": 1,
            "no_copy": 1,
        },
    ],
}


def _assert_state_path(output_path: str) -> Path:
    path = Path(output_path).resolve()
    if path.parent != Path("/tmp") or not path.name.startswith("Pharma_ERP_v0.9.2_Step2C_"):
        frappe.throw("Step2C state file must be a named file directly under /tmp.")
    return path


def _custom_field_name(doctype: str, fieldname: str) -> str | None:
    return frappe.db.get_value(
        "Custom Field", {"dt": doctype, "fieldname": fieldname}, "name"
    )


def capture_state(output_path: str) -> dict:
    path = _assert_state_path(output_path)
    state = {
        "contract_version": CONTRACT_VERSION,
        "page_present": bool(frappe.db.exists("Page", PAGE_NAME)),
        "custom_fields_present": {
            f"{doctype}::{field['fieldname']}": bool(
                _custom_field_name(doctype, field["fieldname"])
            )
            for doctype, fields in CUSTOM_FIELDS.items()
            for field in fields
        },
        "legacy_r1_sales_invoice_fields_present": {
            fieldname: bool(_custom_field_name("Sales Invoice", fieldname))
            for fieldname in LEGACY_R1_SALES_INVOICE_FIELDS
        },
    }
    state["known_failed_r1_residue"] = (
        not state["page_present"]
        and all(state["custom_fields_present"].values())
        and all(state["legacy_r1_sales_invoice_fields_present"].values())
    )
    path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {"state_file": str(path), "contract_version": CONTRACT_VERSION}


def apply() -> dict:
    # R1 inserted these Custom Field rows before MariaDB rejected their
    # physical VARCHAR columns with error 1118.  They are redundant because
    # Sales Invoice Item already carries the standard sales_order/so_detail
    # ownership link.  Direct metadata cleanup avoids another Sales Invoice
    # table rebuild at the row-size limit.
    removed_legacy_fields = []
    for fieldname in LEGACY_R1_SALES_INVOICE_FIELDS:
        custom_field = _custom_field_name("Sales Invoice", fieldname)
        if custom_field:
            frappe.db.delete("Custom Field", {"name": custom_field})
            removed_legacy_fields.append(fieldname)
    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Sales Order")
    frappe.clear_cache(doctype="Sales Invoice")
    frappe.reload_doc("pharma_erp", "page", "customer_reservation_operations")
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "APPLIED",
        "custom_fields": sum(len(fields) for fields in CUSTOM_FIELDS.values()),
        "removed_legacy_r1_sales_invoice_fields": removed_legacy_fields,
        "page": PAGE_NAME,
    }


def verify_installation() -> dict:
    failures = []
    for doctype, fields in CUSTOM_FIELDS.items():
        meta = frappe.get_meta(doctype)
        for field in fields:
            if not meta.has_field(field["fieldname"]):
                failures.append(f"Missing {doctype}.{field['fieldname']}")
    if not frappe.db.exists("Page", PAGE_NAME):
        failures.append(f"Missing Page {PAGE_NAME}")
    for fieldname in LEGACY_R1_SALES_INVOICE_FIELDS:
        if _custom_field_name("Sales Invoice", fieldname):
            failures.append(f"Legacy R1 Sales Invoice metadata remains: {fieldname}")
        if frappe.db.has_column("Sales Invoice", fieldname):
            failures.append(f"Unexpected legacy R1 Sales Invoice column: {fieldname}")
    invoice_item_meta = frappe.get_meta("Sales Invoice Item")
    for fieldname in ("sales_order", "so_detail"):
        if not invoice_item_meta.has_field(fieldname):
            failures.append(f"Missing standard Sales Invoice Item.{fieldname}")
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "custom_fields": sum(len(fields) for fields in CUSTOM_FIELDS.values()),
        "page": PAGE_NAME,
    }


def rollback_from_file(output_path: str) -> dict:
    path = _assert_state_path(output_path)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("contract_version") != CONTRACT_VERSION:
        frappe.throw("Rollback state belongs to another contract version.")
    if (
        frappe.db.has_column("Sales Order", "custom_customer_reservation")
        and frappe.db.count("Sales Order", {"custom_customer_reservation": 1})
    ):
        frappe.throw(
            "Step2C rollback is blocked because operational Customer Reservations exist. "
            "Restore the full backup or review those records first."
        )
    removed = []
    present_before = state.get("custom_fields_present", {})
    if state.get("known_failed_r1_residue"):
        # The R1 residue was not an accepted baseline.  A failed recovery attempt
        # must return to the Step2B metadata state, not recreate that residue.
        present_before = {}
    for doctype, fields in reversed(list(CUSTOM_FIELDS.items())):
        for field in reversed(fields):
            key = f"{doctype}::{field['fieldname']}"
            if present_before.get(key):
                continue
            custom_field = _custom_field_name(doctype, field["fieldname"])
            if custom_field:
                # Controlled failure recovery removes metadata directly.  This
                # avoids creating one Comment audit row per temporary field;
                # the physical columns are intentionally left reusable.
                frappe.db.delete("Custom Field", {"name": custom_field})
                removed.append(key)

    for fieldname in LEGACY_R1_SALES_INVOICE_FIELDS:
        custom_field = _custom_field_name("Sales Invoice", fieldname)
        if custom_field:
            frappe.db.delete("Custom Field", {"name": custom_field})
            removed.append(f"Sales Invoice::{fieldname}")

    if not state.get("page_present") and frappe.db.exists("Page", PAGE_NAME):
        frappe.db.delete(
            "Has Role",
            {"parent": PAGE_NAME, "parenttype": "Page"},
        )
        frappe.db.delete("Page", {"name": PAGE_NAME})
    frappe.clear_cache(doctype="Sales Order")
    frappe.clear_cache(doctype="Sales Invoice")
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "ROLLED_BACK",
        "removed_custom_fields": removed,
        "removed_page": not state.get("page_present"),
    }
