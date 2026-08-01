from __future__ import annotations

from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, now_datetime

from pharma_erp.customer_order_tracking import (
    TRACKING_FIELDS,
    TRACKING_ROUTE,
    TRACKING_VERSION,
    _new_tracking_token_id,
)

CUSTOM_FIELDS = {
    "Online Order": [
        {
            "fieldname": "custom_customer_tracking_section",
            "label": "Customer Tracking",
            "fieldtype": "Section Break",
            "insert_after": "delivery_completion_notes",
            "collapsible": 1,
        },
        {
            "fieldname": "custom_tracking_enabled",
            "label": "Customer Tracking Enabled",
            "fieldtype": "Check",
            "default": "1",
            "insert_after": "custom_customer_tracking_section",
            "read_only": 1,
            "no_copy": 1,
            "in_standard_filter": 1,
        },
        {
            "fieldname": "custom_tracking_issued_at",
            "label": "Tracking Issued At",
            "fieldtype": "Datetime",
            "insert_after": "custom_tracking_enabled",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_tracking_revoked_at",
            "label": "Tracking Revoked At",
            "fieldtype": "Datetime",
            "insert_after": "custom_tracking_issued_at",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_tracking_token_hint",
            "label": "Tracking Token Hint",
            "fieldtype": "Data",
            "insert_after": "custom_tracking_revoked_at",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_tracking_last_rotated_by",
            "label": "Tracking Last Rotated By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_tracking_token_hint",
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_tracking_token_id",
            "label": "Tracking Token Identifier",
            "fieldtype": "Data",
            "insert_after": "custom_tracking_last_rotated_by",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
            "unique": 1,
        },
        {
            "fieldname": "custom_tracking_token_version",
            "label": "Tracking Token Version",
            "fieldtype": "Int",
            "default": str(TRACKING_VERSION),
            "insert_after": "custom_tracking_token_id",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
        },
    ]
}

REQUIRED_FILES = (
    "customer_order_tracking.py",
    "controlled_cart_checkout.py",
    "public/css/customer_order_tracking.css",
    "public/js/customer_order_tracking.js",
    "public/js/controlled_cart_checkout.js",
    "www/pharmacy-order-tracking/index.py",
    "www/pharmacy-order-tracking/index.html",
    "www/pharmacy-order-success/index.html",
    "pharma_erp/doctype/online_order/online_order.js",
)


def _missing_tracking_fields() -> list[str]:
    meta = frappe.get_meta("Online Order")
    return [fieldname for fieldname in TRACKING_FIELDS if not meta.has_field(fieldname)]


def _backfill_tracking_identities() -> dict[str, int]:
    rows = frappe.get_all(
        "Online Order",
        filters={"docstatus": ["<", 2]},
        fields=[
            "name",
            "creation",
            "custom_tracking_enabled",
            "custom_tracking_token_id",
            "custom_tracking_token_version",
            "custom_tracking_token_hint",
            "custom_tracking_issued_at",
        ],
        order_by="creation asc",
        limit_page_length=100000,
    )
    created = 0
    repaired = 0
    for row in rows:
        token_id = str(row.get("custom_tracking_token_id") or "").strip()
        if not token_id:
            token_id = _new_tracking_token_id()
            frappe.db.set_value(
                "Online Order",
                row.name,
                {
                    "custom_tracking_enabled": 1,
                    "custom_tracking_token_id": token_id,
                    "custom_tracking_token_version": TRACKING_VERSION,
                    "custom_tracking_token_hint": token_id[-6:],
                    "custom_tracking_issued_at": row.get("creation") or now_datetime(),
                    "custom_tracking_revoked_at": None,
                    "custom_tracking_last_rotated_by": frappe.session.user,
                },
                update_modified=False,
            )
            created += 1
            continue

        updates = {}
        if not row.get("custom_tracking_token_version"):
            updates["custom_tracking_token_version"] = TRACKING_VERSION
        if not row.get("custom_tracking_token_hint"):
            updates["custom_tracking_token_hint"] = token_id[-6:]
        if not row.get("custom_tracking_issued_at"):
            updates["custom_tracking_issued_at"] = row.get("creation") or now_datetime()
        if row.get("custom_tracking_enabled") is None:
            updates["custom_tracking_enabled"] = 1
        if updates:
            frappe.db.set_value(
                "Online Order", row.name, updates, update_modified=False
            )
            repaired += 1
    return {"created": created, "repaired": repaired, "total": len(rows)}


def verify() -> dict:
    if not frappe.db.exists("DocType", "Online Order"):
        frappe.throw("Online Order DocType is missing.")
    missing_fields = _missing_tracking_fields()
    if missing_fields:
        frappe.throw(
            "Customer tracking custom fields are missing: " + ", ".join(missing_fields)
        )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    missing_files = [
        str(app_path / relative)
        for relative in REQUIRED_FILES
        if not (app_path / relative).exists()
    ]
    if missing_files:
        frappe.throw("Customer tracking source files are missing: " + ", ".join(missing_files))

    total_orders = frappe.db.count("Online Order", {"docstatus": ["<", 2]})
    identified_orders = cint(
        frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tabOnline Order`
            WHERE docstatus < 2
              AND COALESCE(custom_tracking_token_id, '') != ''
            """
        )[0][0]
    )
    duplicate_rows = frappe.db.sql(
        """
        SELECT custom_tracking_token_id, COUNT(*) AS row_count
        FROM `tabOnline Order`
        WHERE COALESCE(custom_tracking_token_id, '') != ''
        GROUP BY custom_tracking_token_id
        HAVING COUNT(*) > 1
        """,
        as_dict=True,
    )
    if identified_orders != total_orders:
        frappe.throw(
            f"Tracking identities are incomplete: {identified_orders}/{total_orders}."
        )
    if duplicate_rows:
        frappe.throw("Duplicate customer tracking identifiers were found.")

    return {
        "status": "ok",
        "step": "4A.1",
        "tracking_route": TRACKING_ROUTE,
        "public_api": "pharma_erp.customer_order_tracking.get_public_order_tracking",
        "staff_link_api": "pharma_erp.customer_order_tracking.get_staff_tracking_link",
        "rotate_api": "pharma_erp.customer_order_tracking.rotate_staff_tracking_link",
        "revoke_api": "pharma_erp.customer_order_tracking.revoke_staff_tracking_link",
        "tracking_fields": len(TRACKING_FIELDS),
        "online_orders": total_orders,
        "identified_orders": identified_orders,
        "duplicate_identifiers": len(duplicate_rows),
        "read_only_public_api": 1,
        "stores_raw_public_token": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }


def install() -> dict:
    installed_apps = set(frappe.get_installed_apps())
    missing_apps = sorted({"pharma_erp", "webshop"} - installed_apps)
    if missing_apps:
        frappe.throw("Missing required apps: " + ", ".join(missing_apps))

    for doctype in ("Online Order", "Online Order Item"):
        if not frappe.db.exists("DocType", doctype):
            frappe.throw(f"Required DocType is missing: {doctype}")

    create_custom_fields(CUSTOM_FIELDS, update=True)
    frappe.clear_cache(doctype="Online Order")

    missing_fields = _missing_tracking_fields()
    if missing_fields:
        frappe.throw(
            "Step 4A.1 custom fields were not installed: " + ", ".join(missing_fields)
        )

    backfill = _backfill_tracking_identities()
    try:
        frappe.db.add_index("Online Order", ["custom_tracking_token_id"])
    except Exception:
        pass

    frappe.clear_cache()
    frappe.db.commit()

    result = verify()
    result.update(
        {
            "backfilled_tracking_identities": backfill["created"],
            "repaired_tracking_identities": backfill["repaired"],
        }
    )
    return result


def execute() -> dict:
    return install()
