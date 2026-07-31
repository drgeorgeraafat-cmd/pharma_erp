from __future__ import annotations

import hashlib
import json

import frappe

from pharma_erp.pharma_erp.install_pharmacy_shift_final_architecture_v2_16 import (
    PAYMENT_ENTRY_SHIFT_SCRIPT,
)

SERVER_SCRIPT_NAME = "Payment Entry - Pharmacy Shift Reference"
EXPECTED_LEGACY_SHA256 = "cc89df84629eef8cd4ff5862168ee27298a874e20310af8457bbffe045b20a98"
EXPECTED_TARGET_SHA256 = "1ec440a93db915b792fbb35bf934bfe53fb48ab72951b2436f35b9e80d0027c6"


def _script_sha(value: str | None) -> str:
    return hashlib.sha256(str(value or "").strip().encode("utf-8")).hexdigest()


def install():
    if not frappe.db.exists("Server Script", SERVER_SCRIPT_NAME):
        frappe.throw(f"Required Server Script {SERVER_SCRIPT_NAME} was not found.")

    doc = frappe.get_doc("Server Script", SERVER_SCRIPT_NAME)
    current_sha = _script_sha(doc.script)

    if current_sha not in {EXPECTED_LEGACY_SHA256, EXPECTED_TARGET_SHA256}:
        frappe.throw(
            "Payment Entry shift Server Script differs from the reviewed legacy or R4 source. "
            "Review it manually before applying this repair."
        )

    doc.script_type = "DocType Event"
    doc.reference_doctype = "Payment Entry"
    doc.doctype_event = "Before Save"
    doc.script = PAYMENT_ENTRY_SHIFT_SCRIPT.strip()
    doc.disabled = 0
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)

    frappe.db.commit()
    frappe.clear_cache()

    result = verify()
    result["previous_sha256"] = current_sha
    result["updated"] = int(current_sha != EXPECTED_TARGET_SHA256)

    print(json.dumps(result, indent=2, default=str))
    return result


def verify():
    if not frappe.db.exists("Server Script", SERVER_SCRIPT_NAME):
        return {
            "server_script": SERVER_SCRIPT_NAME,
            "ready": False,
            "reason": "missing",
        }

    doc = frappe.get_doc("Server Script", SERVER_SCRIPT_NAME)
    script = str(doc.script or "").strip()
    script_sha = _script_sha(script)

    required_tokens = (
        'referenced_invoice_count = 0',
        'if order_type == "Home Delivery":',
        'if has_home_delivery or not doc.get("custom_pharmacy_shift"):',
        'elif referenced_invoice_count and not has_home_delivery:',
        'doc.custom_delivery_shift = None',
    )

    token_checks = {token: token in script for token in required_tokens}
    ready = bool(
        doc.script_type == "DocType Event"
        and doc.reference_doctype == "Payment Entry"
        and doc.doctype_event == "Before Save"
        and not int(doc.disabled or 0)
        and script_sha == EXPECTED_TARGET_SHA256
        and all(token_checks.values())
    )

    result = {
        "server_script": SERVER_SCRIPT_NAME,
        "script_type": doc.script_type,
        "reference_doctype": doc.reference_doctype,
        "doctype_event": doc.doctype_event,
        "disabled": int(doc.disabled or 0),
        "script_sha256": script_sha,
        "expected_sha256": EXPECTED_TARGET_SHA256,
        "token_checks": token_checks,
        "ready": ready,
    }

    print(json.dumps(result, indent=2, default=str))
    return result
