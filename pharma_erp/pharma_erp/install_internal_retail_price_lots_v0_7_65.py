"""Install v0.7.65 Step 6C v2 optional Internal Retail Price Lots."""
from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt

LOT_DOCTYPE = "Internal Retail Price Lot"
STEP = "v0.7.65 Step 6C v2 — Optional Printed-Price Lots & Automatic Stock Sources"


def _has_field(doctype, fieldname):
    return bool(frappe.get_meta(doctype).has_field(fieldname))


def _custom_fields():
    return {
        "Batch": [
            {"fieldname": "custom_pharmacy_barcode", "label": "Pharmacy Barcode", "fieldtype": "Data", "insert_after": "batch_id", "unique": 1},
            {"fieldname": "custom_pharmacy_qr_value", "label": "Pharmacy QR Value", "fieldtype": "Data", "insert_after": "custom_pharmacy_barcode", "unique": 1},
        ],
        "Purchase Invoice": [
            {
                "fieldname": "custom_retail_price_stock_scope",
                "label": "Retail Price Stock Scope",
                "fieldtype": "Select",
                "options": "\nAll Stock\nSeparate Printed Prices\nKeep Current",
                "insert_after": "custom_retail_price_review_status",
                "read_only": 1,
                "allow_on_submit": 1,
            }
        ],
        "Sales Invoice": [
            {"fieldname": "custom_retail_lot_posted", "label": "Retail Lot Ledger Posted", "fieldtype": "Check", "insert_after": "update_stock", "hidden": 1, "read_only": 1, "allow_on_submit": 1}
        ],
        "Sales Invoice Item": [
            {"fieldname": "custom_retail_price_lot", "label": "Internal Retail Price Lot", "fieldtype": "Link", "options": LOT_DOCTYPE, "insert_after": "batch_no", "read_only": 1, "allow_on_submit": 1},
            {"fieldname": "custom_stock_source_mode", "label": "Stock Source Mode", "fieldtype": "Select", "options": "Auto\nManual", "insert_after": "custom_retail_price_lot", "read_only": 1, "allow_on_submit": 1},
            {"fieldname": "custom_pos_row_key", "label": "POS Row Key", "fieldtype": "Data", "insert_after": "custom_stock_source_mode", "hidden": 1, "read_only": 1, "allow_on_submit": 1},
            {"fieldname": "custom_box_qty", "label": "POS Boxes", "fieldtype": "Float", "insert_after": "custom_pos_row_key", "read_only": 1, "allow_on_submit": 1},
            {"fieldname": "custom_unit_qty", "label": "POS Units", "fieldtype": "Float", "insert_after": "custom_box_qty", "read_only": 1, "allow_on_submit": 1},
            {"fieldname": "custom_pack_size", "label": "POS Pack Size", "fieldtype": "Float", "insert_after": "custom_unit_qty", "read_only": 1, "allow_on_submit": 1},
        ],
        "Purchase Invoice Item": [
            {"fieldname": "custom_retail_price_lot", "label": "Internal Retail Price Lot", "fieldtype": "Link", "options": LOT_DOCTYPE, "insert_after": "batch_no", "read_only": 1, "allow_on_submit": 1}
        ],
        "Purchase Receipt Item": [
            {"fieldname": "custom_retail_price_lot", "label": "Internal Retail Price Lot", "fieldtype": "Link", "options": LOT_DOCTYPE, "insert_after": "batch_no", "read_only": 1, "allow_on_submit": 1}
        ],
    }


def _sync_batch_codes():
    if not _has_field("Batch", "custom_pharmacy_barcode"):
        return {"updated": 0}
    rows = frappe.get_all("Batch", filters={"disabled": 0}, fields=["name", "custom_pharmacy_barcode", "custom_pharmacy_qr_value"], limit_page_length=0)
    updated = 0
    for row in rows:
        values = {}
        if not row.custom_pharmacy_barcode:
            values["custom_pharmacy_barcode"] = row.name
        if not row.custom_pharmacy_qr_value:
            values["custom_pharmacy_qr_value"] = f"BATCH:{row.name}"
        if values:
            frappe.db.set_value("Batch", row.name, values, update_modified=False)
            updated += 1
    return {"updated": updated}


def _integrity_counts():
    if not frappe.db.exists("DocType", LOT_DOCTYPE):
        return {"tracked_pairs": 0, "lots": 0, "mismatches": 0, "mismatch_sample": []}
    rows = frappe.db.sql(
        f"""
        SELECT l.item_code, l.warehouse, COALESCE(b.actual_qty, 0) AS actual_qty,
               SUM(l.available_qty) AS lot_qty
        FROM `tab{LOT_DOCTYPE}` l
        LEFT JOIN `tabBin` b ON b.item_code = l.item_code AND b.warehouse = l.warehouse
        WHERE IFNULL(l.disabled, 0) = 0
        GROUP BY l.item_code, l.warehouse, b.actual_qty
        """,
        as_dict=True,
    )
    mismatches = [row for row in rows if abs(flt(row.actual_qty) - flt(row.lot_qty)) > 0.0001]
    return {"tracked_pairs": len(rows), "lots": frappe.db.count(LOT_DOCTYPE), "mismatches": len(mismatches), "mismatch_sample": mismatches[:10]}


def preview():
    non_batch_stock_pairs = cint(frappe.db.sql(
        """
        SELECT COUNT(*)
        FROM `tabBin` b
        INNER JOIN `tabItem` i ON i.name = b.item_code
        WHERE IFNULL(i.has_batch_no, 0) = 0
          AND IFNULL(i.is_stock_item, 1) = 1
          AND b.actual_qty > 0.000001
        """
    )[0][0])
    return {
        "status": "ok",
        "step": STEP,
        "doctype_exists": bool(frappe.db.exists("DocType", LOT_DOCTYPE)),
        "historical_backfill": {"planned_lots": 0, "planned_items": 0, "reason": "Existing test stock keeps the current Item Customer Price; no historical price inference."},
        "non_batch_stock_pairs_left_untracked": non_batch_stock_pairs,
        "policy": {
            "default_non_batch_scope": "Apply New Price to All Stock",
            "optional_scope": "Keep Separate Printed Prices",
            "one_visible_pos_row": True,
            "automatic_batch_allocation": "FEFO",
            "automatic_price_lot_allocation": "Oldest Lot First",
            "whole_box_not_split_between_sources": True,
            "loose_units_may_span_sources": True,
            "manual_new_line_supported": True,
            "batch_lot_barcode_qr_search": True,
            "stock_ledger_impact": False,
            "gl_impact": False,
        },
    }


def verify_installed():
    required_fields = _custom_fields()
    missing_fields = {}
    for doctype, definitions in required_fields.items():
        missing = [definition["fieldname"] for definition in definitions if not _has_field(doctype, definition["fieldname"])]
        if missing:
            missing_fields[doctype] = missing
    doctype_exists = bool(frappe.db.exists("DocType", LOT_DOCTYPE))
    integrity = _integrity_counts() if doctype_exists else {"tracked_pairs": 0, "lots": 0, "mismatches": 0, "mismatch_sample": []}
    missing_batch_codes = 0
    if _has_field("Batch", "custom_pharmacy_barcode"):
        missing_batch_codes = cint(frappe.db.sql("SELECT COUNT(*) FROM `tabBatch` WHERE IFNULL(disabled, 0) = 0 AND IFNULL(custom_pharmacy_barcode, '') = ''")[0][0])
    try:
        import qrcode  # noqa: F401
        qr_image_support = True
    except Exception:
        qr_image_support = False
    return {
        "status": "ok" if doctype_exists and not missing_fields and not integrity.get("mismatches") else "blocked",
        "step": STEP,
        "doctype_exists": doctype_exists,
        "missing_fields": missing_fields,
        "integrity": integrity,
        "missing_batch_codes": missing_batch_codes,
        "qr_image_support": qr_image_support,
        "historical_lots_created": 0,
    }


def install():
    if not frappe.db.exists("DocType", LOT_DOCTYPE):
        frappe.throw(f"{LOT_DOCTYPE} is missing. Run bench migrate after copying Step 6C files.")
    create_custom_fields(_custom_fields(), update=True)
    frappe.clear_cache()
    batch_result = _sync_batch_codes()
    integrity = _integrity_counts()
    if integrity["mismatches"]:
        frappe.throw("Existing Internal Retail Price Lot mismatch detected: " + frappe.as_json(integrity["mismatch_sample"]))
    frappe.db.commit()
    return {
        "status": "ok",
        "step": STEP,
        "batch_codes": batch_result,
        "historical_backfill": {"created": 0, "policy": "No historical price inference"},
        "integrity": integrity,
        "stock_ledger_impact": False,
        "gl_impact": False,
    }
