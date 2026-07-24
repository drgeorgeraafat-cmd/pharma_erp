"""Install/verify v0.7.65 Step 6B non-batch retail price confirmation.

This installer only normalizes retail-price review metadata. It does not alter
stock quantities, GL entries, historical invoice amounts, or Item prices.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt


STEP = "v0.7.65 Step 6B — Non-Batch Customer Price Confirmation"
REQUIRED_FIELDS = {
    "Item": ["has_batch_no", "custom_customer_price", "stock_uom"],
    "Purchase Invoice": [
        "custom_price_change_count",
        "custom_retail_price_review_status",
        "custom_price_reviewed_by",
        "custom_price_reviewed_at",
    ],
    "Purchase Invoice Item": [
        "custom_selling_price",
        "custom_previous_retail_price",
        "custom_price_change_detected",
        "custom_price_change_applied",
    ],
}


def _missing_fields() -> dict[str, list[str]]:
    missing = {}
    for doctype, fields in REQUIRED_FIELDS.items():
        meta = frappe.get_meta(doctype)
        absent = [fieldname for fieldname in fields if not meta.has_field(fieldname)]
        if absent:
            missing[doctype] = absent
    return missing


def _count_batch_rows_marked_for_general_price() -> int:
    return cint(
        frappe.db.sql(
            """
            select count(*)
            from `tabPurchase Invoice Item` pii
            inner join `tabItem` i on i.name = pii.item_code
            where ifnull(i.has_batch_no, 0) = 1
              and ifnull(pii.custom_price_change_detected, 0) = 1
            """
        )[0][0]
    )


def _count_pending_non_batch_rows() -> int:
    return cint(
        frappe.db.sql(
            """
            select count(*)
            from `tabPurchase Invoice Item` pii
            inner join `tabPurchase Invoice` pi on pi.name = pii.parent
            inner join `tabItem` i on i.name = pii.item_code
            where pi.docstatus = 1
              and ifnull(pi.is_return, 0) = 0
              and ifnull(i.has_batch_no, 0) = 0
              and ifnull(pii.custom_price_change_detected, 0) = 1
              and ifnull(pii.custom_price_change_applied, 0) = 0
            """
        )[0][0]
    )


def _pending_invoice_count() -> int:
    return cint(
        frappe.db.count(
            "Purchase Invoice",
            {
                "docstatus": 1,
                "is_return": 0,
                "custom_retail_price_review_status": "Pending Review",
            },
        )
    )


def _sample_invoice() -> dict:
    name = "ACC-PINV-2026-00128"
    if not frappe.db.exists("Purchase Invoice", name):
        return {}

    invoice = frappe.db.get_value(
        "Purchase Invoice",
        name,
        [
            "name",
            "docstatus",
            "custom_price_change_count",
            "custom_retail_price_review_status",
        ],
        as_dict=True,
    ) or frappe._dict()
    rows = frappe.db.sql(
        """
        select
            pii.name as row_name,
            pii.item_code,
            i.item_name,
            ifnull(i.has_batch_no, 0) as has_batch_no,
            ifnull(i.custom_customer_price, 0) as current_price,
            ifnull(pii.custom_selling_price, 0) as new_price,
            ifnull(pii.custom_price_change_detected, 0) as detected,
            ifnull(pii.custom_price_change_applied, 0) as applied
        from `tabPurchase Invoice Item` pii
        inner join `tabItem` i on i.name = pii.item_code
        where pii.parent = %s
        order by pii.idx
        """,
        name,
        as_dict=True,
    )
    invoice["rows"] = rows
    return invoice


def _settings() -> dict:
    if not frappe.db.exists("DocType", "Pharmacy Purchase Settings"):
        return {}
    return {
        "retail_price_update_policy": frappe.db.get_single_value(
            "Pharmacy Purchase Settings", "retail_price_update_policy"
        ),
        "selling_price_list": frappe.db.get_single_value(
            "Pharmacy Purchase Settings", "selling_price_list"
        ),
        "retail_price_difference_tolerance": flt(
            frappe.db.get_single_value(
                "Pharmacy Purchase Settings", "retail_price_difference_tolerance"
            )
        ),
    }


def preview():
    missing = _missing_fields()
    return {
        "status": "ok" if not missing else "blocked",
        "step": STEP,
        "missing_fields": missing,
        "settings": _settings(),
        "counts": {
            "batch_rows_marked_for_general_price": _count_batch_rows_marked_for_general_price(),
            "pending_non_batch_rows": _count_pending_non_batch_rows(),
            "pending_invoices": _pending_invoice_count(),
        },
        "sample_invoice": _sample_invoice(),
        "policy": {
            "non_batch_confirmation_required": True,
            "item_customer_price_updated_after_submit_only": True,
            "selling_price_list_synced": True,
            "batch_items_excluded_from_general_item_price": True,
            "stock_ledger_impact": False,
            "gl_impact": False,
            "historical_invoice_amount_update": False,
        },
    }


def _normalize_batch_rows() -> int:
    rows = frappe.db.sql(
        """
        select pii.name
        from `tabPurchase Invoice Item` pii
        inner join `tabItem` i on i.name = pii.item_code
        where ifnull(i.has_batch_no, 0) = 1
          and ifnull(pii.custom_price_change_detected, 0) = 1
        """,
        as_dict=True,
    )
    for row in rows:
        frappe.db.set_value(
            "Purchase Invoice Item",
            row.name,
            "custom_price_change_detected",
            0,
            update_modified=False,
        )
    return len(rows)


def _recalculate_review_headers() -> int:
    invoice_names = frappe.db.sql_list(
        """
        select distinct pi.name
        from `tabPurchase Invoice` pi
        inner join `tabPurchase Invoice Item` pii on pii.parent = pi.name
        where pi.docstatus < 2
          and ifnull(pi.is_return, 0) = 0
          and (
              ifnull(pi.custom_retail_price_review_status, '') = 'Pending Review'
              or ifnull(pi.custom_price_change_count, 0) > 0
          )
        """
    )
    updated = 0
    for invoice_name in invoice_names:
        count = cint(
            frappe.db.sql(
                """
                select count(*)
                from `tabPurchase Invoice Item` pii
                inner join `tabItem` i on i.name = pii.item_code
                where pii.parent = %s
                  and ifnull(i.has_batch_no, 0) = 0
                  and ifnull(pii.custom_price_change_detected, 0) = 1
                  and ifnull(pii.custom_price_change_applied, 0) = 0
                """,
                invoice_name,
            )[0][0]
        )
        values = {"custom_price_change_count": count}
        current_status = frappe.db.get_value(
            "Purchase Invoice", invoice_name, "custom_retail_price_review_status"
        )
        if count == 0 and current_status == "Pending Review":
            values["custom_retail_price_review_status"] = "Not Required"
        elif count > 0 and current_status in (None, "", "Not Required"):
            values["custom_retail_price_review_status"] = "Pending Review"
        frappe.db.set_value(
            "Purchase Invoice",
            invoice_name,
            values,
            update_modified=False,
        )
        updated += 1
    return updated


def install():
    before = preview()
    if before["missing_fields"]:
        frappe.throw(f"Missing required fields: {before['missing_fields']}")

    normalized_batch_rows = _normalize_batch_rows()
    recalculated_invoices = _recalculate_review_headers()
    frappe.db.commit()

    after = preview()
    if after["counts"]["batch_rows_marked_for_general_price"]:
        frappe.throw("Batch rows are still marked for general Item price updates.")

    return {
        "status": "ok",
        "step": STEP,
        "before": before["counts"],
        "after": after["counts"],
        "normalized_batch_rows": normalized_batch_rows,
        "recalculated_invoices": recalculated_invoices,
        "sample_invoice": after["sample_invoice"],
        "stock_ledger_impact": False,
        "gl_impact": False,
        "historical_invoice_amount_update": False,
    }
