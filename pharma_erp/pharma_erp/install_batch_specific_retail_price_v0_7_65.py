from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt


STEP = "v0.7.65 Step 6A — Batch-Specific Retail Price Integrity"
CANONICAL_FIELD = "custom_printed_retail_price"
COMPATIBILITY_FIELD = "posa_batch_price"
INVOICE_FLAG_FIELD = "custom_price_updated_from_invoice"
TOLERANCE = 0.000001


def _has_batch_field(fieldname: str) -> bool:
    return frappe.get_meta("Batch").has_field(fieldname)


def _assert_required_fields() -> None:
    missing = [
        fieldname
        for fieldname in (CANONICAL_FIELD, COMPATIBILITY_FIELD)
        if not _has_batch_field(fieldname)
    ]
    if missing:
        frappe.throw(
            _("Required Batch price fields are missing: {0}").format(
                ", ".join(missing)
            )
        )


def _counts() -> dict[str, int]:
    _assert_required_fields()

    canonical_to_compatibility = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabBatch`
        WHERE IFNULL(`{CANONICAL_FIELD}`, 0) > 0
          AND ABS(
                IFNULL(`{COMPATIBILITY_FIELD}`, 0)
                - IFNULL(`{CANONICAL_FIELD}`, 0)
              ) > %(tolerance)s
        """,
        {"tolerance": TOLERANCE},
    )[0][0]

    legacy_to_canonical = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabBatch`
        WHERE IFNULL(`{CANONICAL_FIELD}`, 0) <= 0
          AND IFNULL(`{COMPATIBILITY_FIELD}`, 0) > 0
        """
    )[0][0]

    missing_marked_invoice_price = 0
    if _has_batch_field(INVOICE_FLAG_FIELD):
        missing_marked_invoice_price = frappe.db.sql(
            f"""
            SELECT COUNT(*)
            FROM `tabBatch`
            WHERE IFNULL(`{INVOICE_FLAG_FIELD}`, 0) = 1
              AND IFNULL(`{CANONICAL_FIELD}`, 0) <= 0
              AND IFNULL(`{COMPATIBILITY_FIELD}`, 0) <= 0
            """
        )[0][0]

    return {
        "canonical_to_compatibility": cint(canonical_to_compatibility),
        "legacy_to_canonical": cint(legacy_to_canonical),
        "missing_marked_invoice_price": cint(missing_marked_invoice_price),
    }


def _batch_snapshot(batch_no: str) -> dict[str, Any] | None:
    if not batch_no or not frappe.db.exists("Batch", batch_no):
        return None

    fields = [
        "name",
        "item",
        "expiry_date",
        CANONICAL_FIELD,
        COMPATIBILITY_FIELD,
    ]
    if _has_batch_field(INVOICE_FLAG_FIELD):
        fields.append(INVOICE_FLAG_FIELD)

    row = frappe.db.get_value("Batch", batch_no, fields, as_dict=True)
    if not row:
        return None

    return {
        "name": row.name,
        "item": row.item,
        "expiry_date": row.expiry_date,
        "canonical_price": flt(row.get(CANONICAL_FIELD) or 0),
        "compatibility_price": flt(row.get(COMPATIBILITY_FIELD) or 0),
        "updated_from_invoice": cint(row.get(INVOICE_FLAG_FIELD) or 0),
    }


@frappe.whitelist()
def preview(batch_no: str = "asdasdasd") -> dict[str, Any]:
    return {
        "status": "ok",
        "step": STEP,
        "canonical_field": CANONICAL_FIELD,
        "compatibility_field": COMPATIBILITY_FIELD,
        "counts": _counts(),
        "sample_batch": _batch_snapshot(batch_no),
        "policy": {
            "canonical_price_priority": [
                CANONICAL_FIELD,
                COMPATIBILITY_FIELD,
                "Item.custom_customer_price",
            ],
            "destructive_cleanup": False,
            "stock_ledger_impact": False,
            "gl_impact": False,
            "historical_invoice_update": False,
        },
    }


@frappe.whitelist()
def install() -> dict[str, Any]:
    frappe.set_user("Administrator")
    before = _counts()

    frappe.db.sql(
        f"""
        UPDATE `tabBatch`
        SET `{COMPATIBILITY_FIELD}` = `{CANONICAL_FIELD}`
        WHERE IFNULL(`{CANONICAL_FIELD}`, 0) > 0
          AND ABS(
                IFNULL(`{COMPATIBILITY_FIELD}`, 0)
                - IFNULL(`{CANONICAL_FIELD}`, 0)
              ) > %(tolerance)s
        """,
        {"tolerance": TOLERANCE},
    )

    frappe.db.sql(
        f"""
        UPDATE `tabBatch`
        SET `{CANONICAL_FIELD}` = `{COMPATIBILITY_FIELD}`
        WHERE IFNULL(`{CANONICAL_FIELD}`, 0) <= 0
          AND IFNULL(`{COMPATIBILITY_FIELD}`, 0) > 0
        """
    )

    frappe.clear_cache(doctype="Batch")
    frappe.db.commit()

    after = _counts()
    if (
        after["canonical_to_compatibility"]
        or after["legacy_to_canonical"]
    ):
        frappe.throw(
            _("Batch price synchronization verification failed: {0}").format(
                frappe.as_json(after)
            )
        )

    return {
        "status": "ok",
        "step": STEP,
        "before": before,
        "after": after,
        "sample_batch": _batch_snapshot("asdasdasd"),
        "destructive_cleanup": False,
        "stock_ledger_impact": False,
        "gl_impact": False,
        "historical_invoice_update": False,
    }
