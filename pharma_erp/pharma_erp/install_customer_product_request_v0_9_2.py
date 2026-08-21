"""Controlled Step2D metadata and action-center installer."""

from __future__ import annotations

import json
from pathlib import Path

import frappe

from pharma_erp.pharma_erp.customer_product_request_contract import CONTRACT_VERSION


DOCTYPES = (
    "Customer Product Request Item",
    "Customer Product Request",
    "Customer Product Request Match",
)
PAGE_NAME = "customer-product-request-operations"
MATCH_SOURCE_FIELD = "source_type"
R3_MATCH_SOURCE_OPTIONS = "Purchase Receipt\nManual Review"
R4_MATCH_SOURCE_OPTIONS = "Purchase Receipt\nPurchase Invoice\nManual Review"


def _state_path(output_path: str) -> Path:
    path = Path(output_path).resolve()
    if path.parent != Path("/tmp") or not path.name.startswith("Pharma_ERP_v0.9.2_Step2D_"):
        frappe.throw("Step2D state file must be a named file directly under /tmp.")
    return path


def capture_state(output_path: str) -> dict:
    path = _state_path(output_path)
    state = {
        "contract_version": CONTRACT_VERSION,
        "doctypes_present": {name: bool(frappe.db.exists("DocType", name)) for name in DOCTYPES},
        "page_present": bool(frappe.db.exists("Page", PAGE_NAME)),
    }
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    return {"contract_version": CONTRACT_VERSION, "state_file": str(path)}


def apply() -> dict:
    frappe.reload_doc("pharma_erp", "doctype", "customer_product_request_item")
    frappe.reload_doc("pharma_erp", "doctype", "customer_product_request")
    frappe.reload_doc("pharma_erp", "doctype", "customer_product_request_match")
    frappe.reload_doc("pharma_erp", "page", "customer_product_request_operations")
    for name in DOCTYPES:
        frappe.clear_cache(doctype=name)
    return {"contract_version": CONTRACT_VERSION, "status": "APPLIED", "doctypes": list(DOCTYPES), "page": PAGE_NAME}


def _match_source_field_name() -> str:
    name = frappe.db.get_value(
        "DocField",
        {
            "parent": "Customer Product Request Match",
            "parenttype": "DocType",
            "fieldname": MATCH_SOURCE_FIELD,
        },
        "name",
    )
    if not name:
        frappe.throw("Customer Product Request Match.source_type metadata was not found.")
    return name


def apply_direct_purchase_invoice_hotfix_metadata() -> dict:
    """Synchronize only the R4 source-type option from the approved JSON."""
    frappe.reload_doc(
        "pharma_erp",
        "doctype",
        "customer_product_request_match",
        force=True,
    )
    frappe.clear_cache(doctype="Customer Product Request Match")
    options = frappe.db.get_value("DocField", _match_source_field_name(), "options") or ""
    if options != R4_MATCH_SOURCE_OPTIONS:
        frappe.throw("R4 Purchase Invoice match-source metadata did not synchronize exactly.")
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS",
        "field": "Customer Product Request Match.source_type",
        "options": options.splitlines(),
    }


def rollback_direct_purchase_invoice_hotfix_metadata() -> dict:
    """Restore the exact R3 Select options after a failed hotfix gate."""
    frappe.db.set_value(
        "DocField",
        _match_source_field_name(),
        "options",
        R3_MATCH_SOURCE_OPTIONS,
        update_modified=False,
    )
    frappe.clear_cache(doctype="Customer Product Request Match")
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS",
        "field": "Customer Product Request Match.source_type",
        "options": R3_MATCH_SOURCE_OPTIONS.splitlines(),
    }


def verify_installation() -> dict:
    failures = []
    for name in DOCTYPES:
        if not frappe.db.exists("DocType", name):
            failures.append(f"Missing DocType {name}")
        elif not frappe.db.table_exists(name):
            failures.append(f"Missing table for {name}")
    if not frappe.db.exists("Page", PAGE_NAME):
        failures.append(f"Missing Page {PAGE_NAME}")
    parent_meta = frappe.get_meta("Customer Product Request") if frappe.db.exists("DocType", "Customer Product Request") else None
    for fieldname in ("status", "company", "branch", "customer", "requested_at", "external_request_key", "items", "terminal_reason"):
        if parent_meta and not parent_meta.has_field(fieldname):
            failures.append(f"Missing Customer Product Request.{fieldname}")
    match_meta = frappe.get_meta("Customer Product Request Match") if frappe.db.exists("DocType", "Customer Product Request Match") else None
    source_field = match_meta.get_field(MATCH_SOURCE_FIELD) if match_meta else None
    if not source_field:
        failures.append("Missing Customer Product Request Match.source_type")
    elif (source_field.options or "") != R4_MATCH_SOURCE_OPTIONS:
        failures.append("Customer Product Request Match.source_type does not include the exact R4 Purchase Invoice option")
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "doctypes": list(DOCTYPES),
        "page": PAGE_NAME,
    }


def rollback_from_file(output_path: str) -> dict:
    state = json.loads(_state_path(output_path).read_text(encoding="utf-8"))
    if state.get("contract_version") != CONTRACT_VERSION:
        frappe.throw("Rollback state belongs to another contract version.")
    if frappe.db.exists("DocType", "Customer Product Request") and frappe.db.count("Customer Product Request"):
        frappe.throw("Step2D rollback is blocked because Customer Product Request records exist. Restore the full backup or review them first.")
    removed = []
    if not state.get("page_present") and frappe.db.exists("Page", PAGE_NAME):
        frappe.db.delete("Has Role", {"parent": PAGE_NAME, "parenttype": "Page"})
        frappe.db.delete("Page", {"name": PAGE_NAME})
        removed.append(PAGE_NAME)
    # Frappe owns standard DocType table cleanup. Only newly installed, empty
    # Step2D metadata is eligible; existing baseline metadata is never touched.
    for name in reversed(DOCTYPES):
        if state.get("doctypes_present", {}).get(name) or not frappe.db.exists("DocType", name):
            continue
        if frappe.db.table_exists(name) and frappe.db.count(name):
            frappe.throw(f"Rollback blocked because {name} contains records.")
        frappe.delete_doc("DocType", name, force=True, ignore_permissions=True)
        removed.append(name)
    return {"contract_version": CONTRACT_VERSION, "status": "ROLLED_BACK", "removed": removed}
