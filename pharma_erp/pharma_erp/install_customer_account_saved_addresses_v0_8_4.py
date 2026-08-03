from __future__ import annotations

from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from pharma_erp.customer_account import ACCOUNT_ROUTE, account_readiness

CUSTOM_FIELDS = {
    "Online Order": [
        {
            "fieldname": "custom_website_user",
            "label": "Website User",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "source_channel",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_guest_claimed_at",
            "label": "Guest Order Claimed At",
            "fieldtype": "Datetime",
            "insert_after": "custom_website_user",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_guest_claimed_by",
            "label": "Guest Order Claimed By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_guest_claimed_at",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_guest_claim_method",
            "label": "Guest Order Claim Method",
            "fieldtype": "Data",
            "insert_after": "custom_guest_claimed_by",
            "read_only": 1,
            "no_copy": 1,
        },
    ]
}

REQUIRED_ONLINE_ORDER_FIELDS = (
    "custom_website_user",
    "custom_guest_claimed_at",
    "custom_guest_claimed_by",
    "custom_guest_claim_method",
)

REQUIRED_FILES = (
    "customer_account.py",
    "public/css/customer_account.css",
    "public/js/customer_account.js",
    "www/pharmacy-account/index.py",
    "www/pharmacy-account/index.html",
)


def _missing_files() -> list[str]:
    app_path = Path(frappe.get_app_path("pharma_erp"))
    return [
        str(app_path / relative)
        for relative in REQUIRED_FILES
        if not (app_path / relative).exists()
    ]


def verify() -> dict:
    missing_files = _missing_files()
    if missing_files:
        frappe.throw("Customer account source files are missing: " + ", ".join(missing_files))

    if not frappe.db.exists("DocType", "Online Order"):
        frappe.throw("Online Order DocType is missing.")
    online_meta = frappe.get_meta("Online Order")
    missing_fields = [
        fieldname
        for fieldname in REQUIRED_ONLINE_ORDER_FIELDS
        if not online_meta.has_field(fieldname)
    ]
    if missing_fields:
        frappe.throw(
            "Online Order customer-account fields are missing: "
            + ", ".join(missing_fields)
        )

    readiness = account_readiness()
    if readiness.get("missing_doctypes"):
        frappe.throw(
            "Customer account required DocTypes are missing: "
            + ", ".join(readiness["missing_doctypes"])
        )

    return {
        **readiness,
        "status": "ok",
        "step": "4A.2",
        "account_route": ACCOUNT_ROUTE,
        "required_files": len(REQUIRED_FILES),
        "customer_account_installed": 1,
        "guest_order_claim_fields": len(REQUIRED_ONLINE_ORDER_FIELDS) - 1,
        "secure_guest_order_claim_installed": 1,
    }


def install() -> dict:
    required_apps = {"pharma_erp", "erpnext"}
    missing_apps = sorted(required_apps - set(frappe.get_installed_apps()))
    if missing_apps:
        frappe.throw("Missing required apps: " + ", ".join(missing_apps))

    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Online Order")
    frappe.clear_cache()
    frappe.db.commit()
    return verify()


def run() -> dict:
    return install()


def execute() -> dict:
    return install()
