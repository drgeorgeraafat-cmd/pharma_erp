"""Internal retail-price lots for non-batch pharmacy stock.

ERPNext Batch remains the source of truth for real batch-controlled items.
This module adds a lightweight price-lot ledger only for items that do not use
ERPNext Batch, so old and new printed retail prices can coexist safely.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha1

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate


LOT_DOCTYPE = "Internal Retail Price Lot"
LOT_FIELD = "custom_retail_price_lot"
LOT_POSTED_FIELD = "custom_retail_lot_posted"
TOLERANCE = 0.000001


def _has_doctype(doctype: str) -> bool:
    return bool(frappe.db.exists("DocType", doctype))


def _has_field(doctype: str, fieldname: str) -> bool:
    return bool(frappe.get_meta(doctype).has_field(fieldname))


def _item_flags(item_code: str):
    return frappe.db.get_value(
        "Item",
        item_code,
        ["item_name", "has_batch_no", "is_stock_item", "custom_customer_price", "custom_pack_size"],
        as_dict=True,
    ) or frappe._dict()


def _row_stock_qty(row) -> float:
    return flt(row.get("stock_qty") or row.get("qty") or 0, 6)


def _lot_balance(values) -> float:
    values = frappe._dict(values or {})
    return flt(
        flt(values.get("opening_qty"))
        + flt(values.get("received_qty"))
        + flt(values.get("returned_qty"))
        + flt(values.get("adjustment_qty"))
        - flt(values.get("sold_qty")),
        6,
    )


def _refresh_lot(name: str, *, update_modified: bool = False):
    fields = [
        "opening_qty",
        "received_qty",
        "returned_qty",
        "adjustment_qty",
        "sold_qty",
        "disabled",
    ]
    values = frappe.db.get_value(LOT_DOCTYPE, name, fields, as_dict=True)
    if not values:
        return None

    available = _lot_balance(values)
    if abs(available) <= TOLERANCE:
        available = 0.0
    if available < -TOLERANCE:
        frappe.throw(_("Retail Price Lot {0} has a negative balance.").format(name))

    if cint(values.get("disabled")):
        status = "Disabled"
    elif available <= TOLERANCE:
        status = "Depleted"
    else:
        status = "Open"

    frappe.db.set_value(
        LOT_DOCTYPE,
        name,
        {"available_qty": available, "status": status},
        update_modified=update_modified,
    )
    return frappe._dict({"available_qty": available, "status": status})


def _source_filters(source_doctype: str, source_name: str, source_row: str):
    return {
        "source_doctype": source_doctype,
        "source_name": source_name,
        "source_row": source_row,
    }


def _create_or_update_source_lot(
    *,
    item_code: str,
    warehouse: str,
    retail_price: float,
    pack_size: float,
    qty: float,
    source_doctype: str,
    source_name: str,
    source_row: str,
    lot_kind: str,
    source_date=None,
    supplier: str | None = None,
    purchase_invoice: str | None = None,
    purchase_receipt: str | None = None,
):
    if not _has_doctype(LOT_DOCTYPE):
        return None

    item = _item_flags(item_code)
    if not item or cint(item.get("has_batch_no")) or not cint(item.get("is_stock_item", 1)):
        return None

    qty = flt(qty, 6)
    if qty <= TOLERANCE:
        return None

    existing = frappe.db.get_value(
        LOT_DOCTYPE,
        _source_filters(source_doctype, source_name, source_row),
        "name",
    )
    values = {
        "item_code": item_code,
        "item_name": item.get("item_name"),
        "warehouse": warehouse,
        "retail_price": flt(retail_price),
        "pack_size": flt(pack_size or item.get("custom_pack_size") or 1) or 1,
        "source_date": getdate(source_date or nowdate()),
        "lot_kind": lot_kind,
        "source_doctype": source_doctype,
        "source_name": source_name,
        "source_row": source_row,
        "supplier": supplier,
        "purchase_invoice": purchase_invoice,
        "purchase_receipt": purchase_receipt,
    }

    if existing:
        current = frappe.db.get_value(
            LOT_DOCTYPE,
            existing,
            ["sold_qty", "returned_qty", "adjustment_qty", "opening_qty"],
            as_dict=True,
        ) or frappe._dict()
        values["received_qty"] = qty
        if flt(current.get("sold_qty")) > TOLERANCE and abs(
            flt(frappe.db.get_value(LOT_DOCTYPE, existing, "retail_price"))
            - flt(retail_price)
        ) > TOLERANCE:
            frappe.throw(
                _(
                    "Cannot change Retail Price Lot {0} after stock from it has been sold."
                ).format(existing)
            )
        frappe.db.set_value(LOT_DOCTYPE, existing, values, update_modified=False)
        _refresh_lot(existing)
        return existing

    doc = frappe.new_doc(LOT_DOCTYPE)
    doc.update(values)
    doc.received_qty = qty
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name




def _purchase_invoice_review_status(doc) -> str:
    status = str(doc.get("custom_retail_price_review_status") or "").strip()
    if doc.get("name"):
        status = str(
            frappe.db.get_value(
                "Purchase Invoice",
                doc.name,
                "custom_retail_price_review_status",
            )
            or status
            or ""
        ).strip()
    return status


def _purchase_invoice_scope(doc) -> str:
    scope = str(doc.get("custom_retail_price_stock_scope") or "").strip()
    if scope:
        return scope
    decision = str(doc.flags.get("pharmacy_retail_price_decision") or "").strip().lower()
    if decision == "separate_printed_prices":
        return "Separate Printed Prices"
    if decision == "keep_current":
        return "Keep Current"
    if decision == "approve":
        return "All Stock"
    status = _purchase_invoice_review_status(doc).lower()
    if status == "skipped":
        return "Keep Current"
    if status == "applied":
        return "All Stock"
    return ""


def _effective_purchase_lot_price(doc, row, item, scope: str | None = None) -> float:
    entered = flt(row.get("custom_selling_price"))
    current = flt(item.get("custom_customer_price"))
    resolved_scope = str(scope or _purchase_invoice_scope(doc)).strip()
    if resolved_scope == "Keep Current":
        return current or entered
    return entered or current


def _purchase_row_source(doc, row):
    if row.get("purchase_receipt") and row.get("pr_detail"):
        return frappe._dict(
            {
                "source_doctype": "Purchase Receipt",
                "source_name": row.purchase_receipt,
                "source_row": row.pr_detail,
                "lot_kind": "Purchase Receipt",
                "purchase_receipt": row.purchase_receipt,
            }
        )
    if cint(doc.get("update_stock")):
        return frappe._dict(
            {
                "source_doctype": "Purchase Invoice",
                "source_name": doc.name,
                "source_row": row.name,
                "lot_kind": "Purchase Invoice",
                "purchase_invoice": doc.name,
            }
        )
    return None


def _open_lot_qty(item_code: str, warehouse: str) -> float:
    if not _has_doctype(LOT_DOCTYPE):
        return 0.0
    return flt(
        frappe.db.sql(
            f"""
            SELECT COALESCE(SUM(available_qty), 0)
            FROM `tab{LOT_DOCTYPE}`
            WHERE item_code = %s
              AND warehouse = %s
              AND IFNULL(disabled, 0) = 0
              AND available_qty > 0.000001
            """,
            (item_code, warehouse),
        )[0][0],
        6,
    )


def item_has_open_retail_lots(item_code: str, warehouse: str | None = None) -> bool:
    if not _has_doctype(LOT_DOCTYPE):
        return False
    filters = {"item_code": item_code, "disabled": 0, "available_qty": [">", TOLERANCE]}
    if warehouse:
        filters["warehouse"] = warehouse
    return bool(frappe.db.exists(LOT_DOCTYPE, filters))


def _create_baseline_lot(item_code: str, warehouse: str, price: float, qty: float, source_date=None):
    qty = flt(qty, 6)
    if qty <= TOLERANCE:
        return None
    item = _item_flags(item_code)
    raw_key = f"{item_code}|{warehouse}|printed-baseline"
    backfill_key = "RPLBASE-" + sha1(raw_key.encode()).hexdigest()[:20]
    existing = frappe.db.get_value(LOT_DOCTYPE, {"backfill_key": backfill_key}, "name")
    if existing:
        values = frappe.db.get_value(
            LOT_DOCTYPE,
            existing,
            ["sold_qty", "returned_qty", "adjustment_qty"],
            as_dict=True,
        ) or frappe._dict()
        if flt(values.get("sold_qty")) > TOLERANCE:
            frappe.throw(
                _("Existing printed-price baseline Lot {0} already has sales.").format(existing)
            )
        frappe.db.set_value(
            LOT_DOCTYPE,
            existing,
            {
                "retail_price": flt(price),
                "opening_qty": qty,
                "disabled": 0,
                "notes": _("Existing stock separated when a newly printed company price was received."),
            },
            update_modified=False,
        )
        _refresh_lot(existing)
        return existing

    doc = frappe.new_doc(LOT_DOCTYPE)
    doc.item_code = item_code
    doc.item_name = item.get("item_name")
    doc.warehouse = warehouse
    doc.retail_price = flt(price)
    doc.pack_size = flt(item.get("custom_pack_size") or 1) or 1
    doc.source_date = getdate(source_date or nowdate())
    doc.opening_qty = qty
    doc.lot_kind = "Opening Printed Price"
    doc.backfill_key = backfill_key
    doc.notes = _("Existing stock separated when a newly printed company price was received.")
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name


def reprice_open_lots(item_code: str, new_price: float) -> int:
    if not _has_doctype(LOT_DOCTYPE) or flt(new_price) <= 0:
        return 0
    names = frappe.get_all(
        LOT_DOCTYPE,
        filters={"item_code": item_code, "disabled": 0, "available_qty": [">", TOLERANCE]},
        pluck="name",
        limit_page_length=0,
    )
    for name in names:
        frappe.db.set_value(
            LOT_DOCTYPE,
            name,
            "retail_price",
            flt(new_price),
            update_modified=False,
        )
    return len(names)


def _create_purchase_lot(doc, row, item, retail_price: float):
    source = _purchase_row_source(doc, row)
    if not source:
        return None
    warehouse = row.get("warehouse") or doc.get("set_warehouse")
    if not warehouse:
        return None
    lot = _create_or_update_source_lot(
        item_code=row.item_code,
        warehouse=warehouse,
        retail_price=retail_price,
        pack_size=flt(item.get("custom_pack_size") or 1) or 1,
        qty=_row_stock_qty(row),
        source_doctype=source.source_doctype,
        source_name=source.source_name,
        source_row=source.source_row,
        lot_kind=source.lot_kind,
        source_date=doc.posting_date,
        supplier=doc.get("supplier"),
        purchase_invoice=doc.name,
        purchase_receipt=source.get("purchase_receipt"),
    )
    if lot and _has_field("Purchase Invoice Item", LOT_FIELD):
        frappe.db.set_value(
            "Purchase Invoice Item",
            row.name,
            LOT_FIELD,
            lot,
            update_modified=False,
        )
    if lot and source.source_doctype == "Purchase Receipt" and _has_field("Purchase Receipt Item", LOT_FIELD):
        frappe.db.set_value(
            "Purchase Receipt Item",
            source.source_row,
            LOT_FIELD,
            lot,
            update_modified=False,
        )
    return lot


def _initialize_separate_printed_prices(doc, rows, item, old_price: float, new_price: float):
    grouped = defaultdict(list)
    for row in rows:
        source = _purchase_row_source(doc, row)
        warehouse = row.get("warehouse") or doc.get("set_warehouse")
        if source and warehouse:
            grouped[warehouse].append(row)
    if not grouped:
        frappe.throw(
            _("Separate Printed Prices requires stock received by this Purchase Invoice or its linked Purchase Receipt.")
        )

    for warehouse, warehouse_rows in grouped.items():
        purchase_qty = flt(sum(_row_stock_qty(row) for row in warehouse_rows), 6)
        actual_qty = flt(
            frappe.db.get_value(
                "Bin", {"item_code": item.name, "warehouse": warehouse}, "actual_qty"
            ) or 0,
            6,
        )
        tracked_qty = _open_lot_qty(item.name, warehouse)
        if actual_qty + TOLERANCE < tracked_qty + purchase_qty:
            frappe.throw(
                _(
                    "Cannot separate printed prices for {0} in {1}: some received stock appears to have been consumed before price separation. Choose Apply New Price to All Stock or reconcile the stock first."
                ).format(item.get("item_name") or item.name, warehouse)
            )
        baseline_qty = flt(actual_qty - tracked_qty - purchase_qty, 6)
        if baseline_qty > TOLERANCE:
            _create_baseline_lot(
                item.name,
                warehouse,
                old_price or new_price,
                baseline_qty,
                source_date=doc.posting_date,
            )
        for row in warehouse_rows:
            _create_purchase_lot(doc, row, item, new_price)


def sync_purchase_invoice_lot_prices(doc, decision: str | None = None):
    """Apply a post-submit review decision to existing tracked stock.

    Submitted historical invoices cannot be safely split after stock may have moved,
    so post-submit approval always applies the new price to all open lots.
    """
    if not _has_doctype(LOT_DOCTYPE) or cint(doc.get("is_return")):
        return 0
    updated = 0
    for row in doc.get("items") or []:
        item = _item_flags(row.item_code)
        if not item or cint(item.get("has_batch_no")):
            continue
        price = _effective_purchase_lot_price(doc, row, item, "All Stock")
        updated += reprice_open_lots(row.item_code, price)
    return updated


def on_submit_purchase_receipt_lots(doc, method=None):
    # Price scope is decided on the Purchase Invoice confirmation dialog.
    # A Purchase Receipt alone does not create an Internal Retail Price Lot.
    return


def before_cancel_purchase_receipt_lots(doc, method=None):
    if not _has_doctype(LOT_DOCTYPE):
        return
    for row in doc.get("items") or []:
        lot = row.get(LOT_FIELD) or frappe.db.get_value(
            LOT_DOCTYPE,
            _source_filters("Purchase Receipt", doc.name, row.name),
            "name",
        )
        if not lot:
            continue
        sold = flt(frappe.db.get_value(LOT_DOCTYPE, lot, "sold_qty"))
        if sold > TOLERANCE:
            frappe.throw(
                _("Cannot cancel Purchase Receipt {0}: Retail Price Lot {1} has sold quantity {2}.").format(
                    doc.name, lot, sold
                )
            )


def on_cancel_purchase_receipt_lots(doc, method=None):
    if not _has_doctype(LOT_DOCTYPE):
        return
    for row in doc.get("items") or []:
        lot = row.get(LOT_FIELD) or frappe.db.get_value(
            LOT_DOCTYPE,
            _source_filters("Purchase Receipt", doc.name, row.name),
            "name",
        )
        if lot:
            frappe.db.set_value(
                LOT_DOCTYPE,
                lot,
                {"received_qty": 0, "disabled": 1},
                update_modified=False,
            )
            _refresh_lot(lot)


def on_submit_purchase_invoice_lots(doc, method=None):
    if cint(doc.get("is_return")) or not _has_doctype(LOT_DOCTYPE):
        return

    scope = _purchase_invoice_scope(doc) or "All Stock"
    rows_by_item = defaultdict(list)
    for row in doc.get("items") or []:
        item = _item_flags(row.item_code)
        if not item or cint(item.get("has_batch_no")) or not cint(item.get("is_stock_item", 1)):
            continue
        rows_by_item[row.item_code].append(row)

    for item_code, rows in rows_by_item.items():
        item = _item_flags(item_code)
        item.name = item_code
        old_price = flt(next((row.get("custom_previous_retail_price") for row in rows if flt(row.get("custom_previous_retail_price")) > 0), 0))
        entered_price = flt(next((row.get("custom_selling_price") for row in rows if flt(row.get("custom_selling_price")) > 0), 0))
        current_price = flt(item.get("custom_customer_price"))

        if scope == "Separate Printed Prices":
            _initialize_separate_printed_prices(
                doc,
                rows,
                item,
                old_price or current_price,
                entered_price or current_price,
            )
            continue

        tracked = any(
            item_has_open_retail_lots(
                item_code,
                row.get("warehouse") or doc.get("set_warehouse"),
            )
            for row in rows
            if (row.get("warehouse") or doc.get("set_warehouse"))
        )
        if tracked:
            effective_price = current_price if scope in {"All Stock", "Keep Current"} else (entered_price or current_price)
            for row in rows:
                _create_purchase_lot(doc, row, item, effective_price)
            if scope == "All Stock":
                reprice_open_lots(item_code, current_price or entered_price)


def before_cancel_purchase_invoice_lots(doc, method=None):
    if not _has_doctype(LOT_DOCTYPE) or not cint(doc.get("update_stock")):
        return
    for row in doc.get("items") or []:
        lot = row.get(LOT_FIELD) or frappe.db.get_value(
            LOT_DOCTYPE,
            _source_filters("Purchase Invoice", doc.name, row.name),
            "name",
        )
        if not lot:
            continue
        sold = flt(frappe.db.get_value(LOT_DOCTYPE, lot, "sold_qty"))
        if sold > TOLERANCE:
            frappe.throw(
                _("Cannot cancel Purchase Invoice {0}: Retail Price Lot {1} has sold quantity {2}.").format(
                    doc.name, lot, sold
                )
            )


def on_cancel_purchase_invoice_lots(doc, method=None):
    if not _has_doctype(LOT_DOCTYPE) or not cint(doc.get("update_stock")):
        return
    for row in doc.get("items") or []:
        lot = row.get(LOT_FIELD) or frappe.db.get_value(
            LOT_DOCTYPE,
            _source_filters("Purchase Invoice", doc.name, row.name),
            "name",
        )
        if lot:
            frappe.db.set_value(
                LOT_DOCTYPE,
                lot,
                {"received_qty": 0, "disabled": 1},
                update_modified=False,
            )
            _refresh_lot(lot)


def get_available_retail_lots(item_code: str, warehouse: str, *, for_update=False):
    if not _has_doctype(LOT_DOCTYPE) or not item_code or not warehouse:
        return []

    suffix = " FOR UPDATE" if for_update else ""
    rows = frappe.db.sql(
        f"""
        SELECT
            name,
            item_code,
            item_name,
            warehouse,
            retail_price,
            pack_size,
            source_date,
            expiry_date,
            available_qty,
            barcode_value,
            qr_value,
            lot_kind,
            purchase_invoice,
            purchase_receipt
        FROM `tab{LOT_DOCTYPE}`
        WHERE item_code = %(item_code)s
          AND warehouse = %(warehouse)s
          AND IFNULL(disabled, 0) = 0
          AND available_qty > 0.000001
        ORDER BY
            COALESCE(expiry_date, '9999-12-31') ASC,
            source_date ASC,
            creation ASC,
            name ASC
        {suffix}
        """,
        {"item_code": item_code, "warehouse": warehouse},
        as_dict=True,
    )
    for row in rows:
        row.source_type = "retail_lot"
        row.customer_price = flt(row.retail_price)
        row.qty = flt(row.available_qty, 6)
        row.label = row.name
    return rows


def allocate_retail_lots(
    item_code: str,
    warehouse: str,
    required_qty: float,
    preferred_lot: str | None = None,
    *,
    strict_preferred: bool = False,
    for_update: bool = False,
):
    required_qty = flt(required_qty, 6)
    if required_qty <= 0:
        return []

    lots = get_available_retail_lots(item_code, warehouse, for_update=for_update)
    if not lots:
        frappe.throw(
            _(
                "No Internal Retail Price Lot is available for item {0} in warehouse {1}."
            ).format(item_code, warehouse)
        )

    preferred = None
    if preferred_lot:
        preferred = next((lot for lot in lots if lot.name == preferred_lot), None)
        if not preferred:
            frappe.throw(
                _("Retail Price Lot {0} is not available for item {1}.").format(
                    preferred_lot, item_code
                )
            )

    ordered = [preferred] if preferred else []
    if not strict_preferred:
        ordered.extend(lot for lot in lots if not preferred or lot.name != preferred.name)

    total_available = flt(sum(flt(lot.available_qty) for lot in ordered), 6)
    if total_available + TOLERANCE < required_qty:
        label = preferred_lot if strict_preferred and preferred_lot else item_code
        frappe.throw(
            _(
                "Insufficient Retail Price Lot stock for {0}. Required: {1}, available: {2}."
            ).format(label, required_qty, total_available)
        )

    remaining = required_qty
    allocations = []
    for lot in ordered:
        if remaining <= TOLERANCE:
            break
        allocated = min(flt(lot.available_qty), remaining)
        if allocated <= 0:
            continue
        allocations.append(
            frappe._dict(
                {
                    "retail_price_lot": lot.name,
                    "qty": flt(allocated, 6),
                    "customer_price": flt(lot.retail_price),
                    "price_source": "Internal Retail Price Lot",
                    "source_date": lot.source_date,
                    "expiry_date": lot.expiry_date,
                }
            )
        )
        remaining = flt(remaining - allocated, 6)

    if remaining > TOLERANCE:
        frappe.throw(_("Unable to allocate Retail Price Lot stock for item {0}.").format(item_code))
    return allocations


def _is_pharmacy_pos_invoice(doc) -> bool:
    remarks = str(doc.get("remarks") or "")
    return "Pharmacy POS" in remarks or "PHARMACY_POS_HOLD" in remarks



def _ensure_sales_return_lot(doc, row, item, warehouse):
    price = flt(row.get("price_list_rate") or row.get("rate") or item.get("custom_customer_price"))
    candidates = frappe.get_all(
        LOT_DOCTYPE,
        filters={
            "item_code": row.item_code,
            "warehouse": warehouse,
            "disabled": 0,
            "retail_price": price,
        },
        fields=["name"],
        order_by="source_date asc, creation asc",
        limit_page_length=1,
    )
    if candidates:
        return candidates[0].name

    lot = frappe.new_doc(LOT_DOCTYPE)
    lot.item_code = row.item_code
    lot.item_name = item.get("item_name")
    lot.warehouse = warehouse
    lot.retail_price = price
    lot.pack_size = flt(item.get("custom_pack_size") or 1) or 1
    lot.source_date = doc.posting_date or nowdate()
    lot.lot_kind = "Sales Return"
    lot.source_doctype = "Sales Invoice"
    lot.source_name = doc.name
    lot.source_row = row.name
    lot.notes = _("Created automatically for a sales return without a tracked original lot.")
    lot.flags.ignore_permissions = True
    lot.insert(ignore_permissions=True)
    return lot.name


def before_submit_sales_invoice_lots(doc, method=None):
    if (
        not cint(doc.get("update_stock"))
        or not _has_doctype(LOT_DOCTYPE)
        or not _has_field("Sales Invoice Item", LOT_FIELD)
    ):
        return

    # ERPNext copies custom parent fields when it creates a Credit Note from a
    # submitted Sales Invoice.  The source invoice is already marked as posted,
    # but a new return must always start unposted so its lot movement runs once.
    if _has_field("Sales Invoice", LOT_POSTED_FIELD) and cint(doc.get(LOT_POSTED_FIELD)):
        doc.set(LOT_POSTED_FIELD, 0)

    for row in doc.get("items") or []:
        item = _item_flags(row.item_code)
        if not item or cint(item.get("has_batch_no")) or not cint(item.get("is_stock_item", 1)):
            continue

        lot_name = row.get(LOT_FIELD)
        if cint(doc.get("is_return")) and not lot_name:
            original_row = row.get("sales_invoice_item") or row.get("si_detail")
            if original_row:
                original_values = frappe.db.get_value(
                    "Sales Invoice Item",
                    original_row,
                    [LOT_FIELD, "custom_stock_source_mode", "custom_pack_size"],
                    as_dict=True,
                ) or frappe._dict()
                lot_name = original_values.get(LOT_FIELD)
                if lot_name:
                    row.set(LOT_FIELD, lot_name)
                if (
                    _has_field("Sales Invoice Item", "custom_stock_source_mode")
                    and not row.get("custom_stock_source_mode")
                    and original_values.get("custom_stock_source_mode")
                ):
                    row.set(
                        "custom_stock_source_mode",
                        original_values.get("custom_stock_source_mode"),
                    )
                if (
                    _has_field("Sales Invoice Item", "custom_pack_size")
                    and not flt(row.get("custom_pack_size"))
                    and flt(original_values.get("custom_pack_size"))
                ):
                    row.set("custom_pack_size", flt(original_values.get("custom_pack_size")))

        row_warehouse = row.get("warehouse") or doc.get("set_warehouse")
        tracked = bool(row_warehouse and item_has_open_retail_lots(row.item_code, row_warehouse))

        if not lot_name and cint(doc.get("is_return")) and tracked:
            lot_name = _ensure_sales_return_lot(doc, row, item, row_warehouse)
            row.set(LOT_FIELD, lot_name)

        if not lot_name and not tracked:
            # Default mode: the Item Customer Price applies to all old and new stock.
            continue

        if not lot_name:
            frappe.throw(
                _(
                    "Retail Price Lot is required for stock-updating Sales Invoice item {0}. "
                    "Use Pharmacy POS so the oldest eligible lot is allocated automatically."
                ).format(row.item_code)
            )

        lot = frappe.db.get_value(
            LOT_DOCTYPE,
            lot_name,
            ["item_code", "warehouse", "retail_price", "disabled"],
            as_dict=True,
        )
        if not lot or cint(lot.get("disabled")):
            frappe.throw(_("Retail Price Lot {0} is unavailable.").format(lot_name))
        if lot.item_code != row.item_code:
            frappe.throw(
                _("Retail Price Lot {0} does not belong to item {1}.").format(
                    lot_name, row.item_code
                )
            )
        row_warehouse = row.get("warehouse") or doc.get("set_warehouse")
        if row_warehouse and lot.warehouse != row_warehouse:
            frappe.throw(
                _("Retail Price Lot {0} belongs to warehouse {1}, not {2}.").format(
                    lot_name, lot.warehouse, row_warehouse
                )
            )

        submitted_price = flt(row.get("price_list_rate") or row.get("rate"))
        if submitted_price and abs(submitted_price - flt(lot.retail_price)) > 0.0001:
            frappe.throw(
                _(
                    "Retail Price Lot {0} price is {1}, but Sales Invoice row price is {2}."
                ).format(lot_name, lot.retail_price, submitted_price)
            )


def _update_sales_lots(doc, direction: int):
    if not _has_doctype(LOT_DOCTYPE) or not _has_field("Sales Invoice Item", LOT_FIELD):
        return

    grouped = defaultdict(float)
    for row in doc.get("items") or []:
        lot_name = row.get(LOT_FIELD)
        if not lot_name:
            continue
        grouped[lot_name] += _row_stock_qty(row)

    for lot_name, row_qty in grouped.items():
        rows = frappe.db.sql(
            f"""
            SELECT opening_qty, received_qty, returned_qty, adjustment_qty,
                   sold_qty, available_qty, disabled
            FROM `tab{LOT_DOCTYPE}`
            WHERE name = %s
            FOR UPDATE
            """,
            lot_name,
            as_dict=True,
        )
        if not rows:
            frappe.throw(_("Retail Price Lot {0} was not found.").format(lot_name))
        lot = frappe._dict(rows[0])
        sold = flt(lot.sold_qty, 6)
        returned = flt(lot.returned_qty, 6)
        qty = flt(row_qty, 6)

        if direction == 1:
            if qty >= 0:
                sold = flt(sold + qty, 6)
            else:
                return_qty = abs(qty)
                reverse_sold = min(sold, return_qty)
                sold = flt(sold - reverse_sold, 6)
                returned = flt(returned + (return_qty - reverse_sold), 6)
        else:
            if qty >= 0:
                sold = flt(sold - qty, 6)
            else:
                return_qty = abs(qty)
                reverse_returned = min(returned, return_qty)
                returned = flt(returned - reverse_returned, 6)
                sold = flt(sold + (return_qty - reverse_returned), 6)

        if sold < -TOLERANCE or returned < -TOLERANCE:
            frappe.throw(_("Retail Price Lot {0} ledger would become negative.").format(lot_name))

        new_available = flt(
            flt(lot.opening_qty)
            + flt(lot.received_qty)
            + returned
            + flt(lot.adjustment_qty)
            - sold,
            6,
        )
        if new_available < -TOLERANCE:
            frappe.throw(
                _(
                    "Insufficient Retail Price Lot stock in {0}. Available: {1}, requested: {2}."
                ).format(lot_name, lot.available_qty, abs(qty))
            )
        frappe.db.set_value(
            LOT_DOCTYPE,
            lot_name,
            {"sold_qty": max(0, sold), "returned_qty": max(0, returned)},
            update_modified=False,
        )
        _refresh_lot(lot_name)


def on_submit_sales_invoice_lots(doc, method=None):
    if not cint(doc.get("update_stock")) or not _has_field("Sales Invoice", LOT_POSTED_FIELD):
        return
    if cint(doc.get(LOT_POSTED_FIELD)):
        return
    _update_sales_lots(doc, 1)
    frappe.db.set_value("Sales Invoice", doc.name, LOT_POSTED_FIELD, 1, update_modified=False)


def on_cancel_sales_invoice_lots(doc, method=None):
    if not cint(doc.get("update_stock")) or not _has_field("Sales Invoice", LOT_POSTED_FIELD):
        return
    posted = cint(doc.get(LOT_POSTED_FIELD)) or cint(
        frappe.db.get_value("Sales Invoice", doc.name, LOT_POSTED_FIELD)
    )
    if not posted:
        return
    _update_sales_lots(doc, -1)
    frappe.db.set_value("Sales Invoice", doc.name, LOT_POSTED_FIELD, 0, update_modified=False)



def rebuild_sales_lot_balances(*, apply: bool = False):
    """Rebuild lot sales/return counters from active stock-updating invoices.

    Sales Invoice and Credit Note rows are the authoritative source.  This also
    repairs returns created before v0.7.65 Step 6C v2.2 where ERPNext copied the
    parent's posted marker and the return movement was skipped.
    """
    if not _has_doctype(LOT_DOCTYPE) or not _has_field("Sales Invoice Item", LOT_FIELD):
        return frappe._dict(
            {
                "status": "ok",
                "apply": cint(apply),
                "lots_checked": 0,
                "lots_changed": 0,
                "changes": [],
            }
        )

    aggregates = frappe.db.sql(
        f"""
        SELECT
            sii.{LOT_FIELD} AS lot_name,
            COALESCE(SUM(CASE
                WHEN sii.stock_qty > 0 THEN sii.stock_qty ELSE 0 END), 0) AS sale_qty,
            COALESCE(SUM(CASE
                WHEN sii.stock_qty < 0 THEN ABS(sii.stock_qty) ELSE 0 END), 0) AS return_qty
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1
          AND IFNULL(si.update_stock, 0) = 1
          AND IFNULL(sii.{LOT_FIELD}, '') != ''
        GROUP BY sii.{LOT_FIELD}
        """,
        as_dict=True,
    )
    by_lot = {row.lot_name: frappe._dict(row) for row in aggregates}
    lot_rows = frappe.get_all(
        LOT_DOCTYPE,
        fields=[
            "name",
            "item_code",
            "warehouse",
            "opening_qty",
            "received_qty",
            "adjustment_qty",
            "sold_qty",
            "returned_qty",
            "available_qty",
        ],
        limit_page_length=0,
        order_by="creation asc, name asc",
    )

    changes = []
    for raw_lot in lot_rows:
        lot = frappe._dict(raw_lot)
        totals = by_lot.get(lot.name, frappe._dict())
        sale_qty = flt(totals.get("sale_qty"), 6)
        return_qty = flt(totals.get("return_qty"), 6)
        expected_sold = flt(max(sale_qty - return_qty, 0), 6)
        expected_returned = flt(max(return_qty - sale_qty, 0), 6)
        expected_available = flt(
            flt(lot.opening_qty)
            + flt(lot.received_qty)
            + expected_returned
            + flt(lot.adjustment_qty)
            - expected_sold,
            6,
        )
        changed = any(
            abs(flt(current) - flt(expected)) > TOLERANCE
            for current, expected in (
                (lot.sold_qty, expected_sold),
                (lot.returned_qty, expected_returned),
                (lot.available_qty, expected_available),
            )
        )
        if not changed:
            continue
        change = frappe._dict(
            {
                "lot": lot.name,
                "item_code": lot.item_code,
                "warehouse": lot.warehouse,
                "current_sold_qty": flt(lot.sold_qty, 6),
                "expected_sold_qty": expected_sold,
                "current_returned_qty": flt(lot.returned_qty, 6),
                "expected_returned_qty": expected_returned,
                "current_available_qty": flt(lot.available_qty, 6),
                "expected_available_qty": expected_available,
            }
        )
        changes.append(change)
        if apply:
            frappe.db.set_value(
                LOT_DOCTYPE,
                lot.name,
                {
                    "sold_qty": expected_sold,
                    "returned_qty": expected_returned,
                },
                update_modified=False,
            )
            _refresh_lot(lot.name)

    return frappe._dict(
        {
            "status": "ok",
            "apply": cint(apply),
            "lots_checked": len(lot_rows),
            "lots_changed": len(changes),
            "changes": changes,
        }
    )

def find_source_matches(text: str, warehouse: str | None = None, limit: int = 20):
    """Search exact/partial Batch and Internal Retail Price Lot identifiers."""
    raw = (text or "").strip()
    if not raw:
        return []
    like = f"%{raw}%"
    results = []

    batch_fields = ["name", "batch_id", "item", "expiry_date"]
    batch_meta = frappe.get_meta("Batch")
    for fieldname in ("custom_pharmacy_barcode", "custom_pharmacy_qr_value"):
        if batch_meta.has_field(fieldname):
            batch_fields.append(fieldname)
    filters_sql = ["b.name LIKE %(like)s", "IFNULL(b.batch_id, '') LIKE %(like)s"]
    if batch_meta.has_field("custom_pharmacy_barcode"):
        filters_sql.append("IFNULL(b.custom_pharmacy_barcode, '') LIKE %(like)s")
    if batch_meta.has_field("custom_pharmacy_qr_value"):
        filters_sql.append("IFNULL(b.custom_pharmacy_qr_value, '') LIKE %(like)s")

    batch_rows = frappe.db.sql(
        f"""
        SELECT b.name, b.batch_id, b.item, b.expiry_date,
               {('b.custom_pharmacy_barcode' if batch_meta.has_field('custom_pharmacy_barcode') else "''")} AS barcode_value,
               {('b.custom_pharmacy_qr_value' if batch_meta.has_field('custom_pharmacy_qr_value') else "''")} AS qr_value
        FROM `tabBatch` b
        WHERE IFNULL(b.disabled, 0) = 0
          AND ({' OR '.join(filters_sql)})
        ORDER BY
          CASE WHEN b.name = %(raw)s OR b.batch_id = %(raw)s THEN 0 ELSE 1 END,
          b.name ASC
        LIMIT %(limit)s
        """,
        {"raw": raw, "like": like, "limit": limit},
        as_dict=True,
    )
    for batch in batch_rows:
        qty = 0
        if warehouse:
            try:
                from erpnext.stock.doctype.batch.batch import get_batch_qty

                rows = get_batch_qty(batch_no=batch.name, warehouse=warehouse) or []
                if isinstance(rows, (int, float)):
                    qty = flt(rows)
                elif rows:
                    qty = flt(frappe._dict(rows[0]).get("qty"))
            except Exception:
                qty = 0
        results.append(
            frappe._dict(
                {
                    "source_type": "batch",
                    "source_name": batch.name,
                    "item_code": batch.item,
                    "expiry_date": batch.expiry_date,
                    "qty": qty,
                    "barcode_value": batch.barcode_value,
                    "qr_value": batch.qr_value,
                    "exact": cint(
                        raw
                        in {
                            batch.name,
                            batch.batch_id,
                            batch.barcode_value,
                            batch.qr_value,
                            f"BATCH:{batch.name}",
                        }
                    ),
                }
            )
        )

    if _has_doctype(LOT_DOCTYPE):
        lot_rows = frappe.db.sql(
            f"""
            SELECT name, item_code, warehouse, retail_price, available_qty,
                   source_date, expiry_date, barcode_value, qr_value
            FROM `tab{LOT_DOCTYPE}`
            WHERE IFNULL(disabled, 0) = 0
              AND available_qty > 0.000001
              AND (%(warehouse)s = '' OR warehouse = %(warehouse)s)
              AND (
                  name LIKE %(like)s
                  OR IFNULL(barcode_value, '') LIKE %(like)s
                  OR IFNULL(qr_value, '') LIKE %(like)s
              )
            ORDER BY
              CASE WHEN name = %(raw)s OR barcode_value = %(raw)s OR qr_value = %(raw)s THEN 0 ELSE 1 END,
              source_date ASC,
              name ASC
            LIMIT %(limit)s
            """,
            {"raw": raw, "like": like, "warehouse": warehouse or "", "limit": limit},
            as_dict=True,
        )
        for lot in lot_rows:
            results.append(
                frappe._dict(
                    {
                        "source_type": "retail_lot",
                        "source_name": lot.name,
                        "item_code": lot.item_code,
                        "expiry_date": lot.expiry_date,
                        "qty": flt(lot.available_qty),
                        "customer_price": flt(lot.retail_price),
                        "barcode_value": lot.barcode_value,
                        "qr_value": lot.qr_value,
                        "exact": cint(
                            raw
                            in {
                                lot.name,
                                lot.barcode_value,
                                lot.qr_value,
                                f"RPL:{lot.name}",
                            }
                        ),
                    }
                )
            )

    results.sort(key=lambda row: (0 if row.exact else 1, row.source_type, row.source_name))
    return results[:limit]
