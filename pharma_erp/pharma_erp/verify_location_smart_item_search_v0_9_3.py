from __future__ import annotations

import re

import frappe

from pharma_erp.pharma_erp.location_item_search import search_items


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _contains(rows, item_code):
    return any(row and row[0] == item_code for row in (rows or []))


def _make_spaced_probe(item_name):
    compact = "".join(ch for ch in (item_name or "") if ch.isalnum())
    if len(compact) < 3:
        return None
    # Use ordered characters with a small gap to prove subsequence matching.
    positions = [0, min(2, len(compact) - 1), min(3, len(compact) - 1)]
    chars = [compact[pos] for pos in positions]
    return " ".join(chars)


def run():
    candidate = frappe.db.sql(
        """
        SELECT name, item_name
        FROM `tabItem`
        WHERE disabled=0
          AND is_stock_item=1
          AND CHAR_LENGTH(REGEXP_REPLACE(IFNULL(item_name, ''), '[^[:alnum:]]', '')) >= 4
        ORDER BY
            CASE WHEN LOWER(item_name) LIKE 'augmentin%%' THEN 0 ELSE 1 END,
            modified DESC,
            name
        LIMIT 1
        """,
        as_dict=True,
    )
    _assert(candidate, "No enabled stock Item is available for search verification.")
    item = candidate[0]

    by_code = search_items("Item", item.name, "name", 0, 20, {})
    _assert(_contains(by_code, item.name), f"Item Code search failed for {item.name}")

    by_name = search_items("Item", item.item_name, "name", 0, 20, {})
    _assert(_contains(by_name, item.name), f"Item Name search failed for {item.item_name}")

    spaced_probe = _make_spaced_probe(item.item_name)
    _assert(spaced_probe, f"Could not build spaced-letter probe for {item.item_name}")
    by_spaced = search_items("Item", spaced_probe, "name", 0, 20, {})
    _assert(
        _contains(by_spaced, item.name),
        f"Spaced-letter search failed for {spaced_probe} -> {item.name}",
    )

    barcode_row = frappe.db.sql(
        """
        SELECT ib.parent AS item_code, ib.barcode
        FROM `tabItem Barcode` ib
        INNER JOIN `tabItem` i ON i.name=ib.parent
        WHERE ib.parenttype='Item'
          AND i.disabled=0
          AND i.is_stock_item=1
          AND IFNULL(ib.barcode, '') != ''
        ORDER BY ib.modified DESC
        LIMIT 1
        """,
        as_dict=True,
    )

    barcode_result = "SKIP_NO_BARCODE"
    if barcode_row:
        row = barcode_row[0]
        by_barcode = search_items("Item", row.barcode, "name", 0, 20, {})
        _assert(
            _contains(by_barcode, row.item_code),
            f"Barcode search failed for {row.barcode} -> {row.item_code}",
        )
        barcode_result = "PASS"

    return {
        "status": "PASS",
        "item_code_search": "PASS",
        "item_name_search": "PASS",
        "spaced_letter_search": "PASS",
        "spaced_probe": spaced_probe,
        "barcode_search": barcode_result,
        "verified_item": item.name,
        "verified_item_name": item.item_name,
    }
