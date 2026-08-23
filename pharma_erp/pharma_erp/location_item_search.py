from __future__ import annotations

import re

import frappe
from frappe.desk.search import validate_and_sanitize_search_inputs


def _spaced_letter_pattern(txt: str) -> str | None:
    """Return a LIKE subsequence pattern for deliberate spaced-letter input.

    Example:
        "a g m" -> "%a%g%m%"

    This mode is enabled only when there are at least two whitespace-separated
    tokens and every token is exactly one alphanumeric character. Normal
    multi-word names continue to use the regular phrase search.
    """
    tokens = [part for part in re.split(r"\s+", (txt or "").strip()) if part]
    if len(tokens) < 2:
        return None
    if not all(len(token) == 1 and token.isalnum() for token in tokens):
        return None
    return "%" + "%".join(tokens) + "%"


@frappe.whitelist()
@validate_and_sanitize_search_inputs
def search_items(doctype, txt, searchfield, start, page_len, filters):
    """Smart Item Link search for Pharmacy Location operations.

    Searches enabled stock items by:
    - Item Code
    - Item Name
    - Barcode
    - Deliberate spaced letters, e.g. "a g m" -> Augmentin

    The selected Link value remains the standard Item Code.
    """
    txt = (txt or "").strip()
    like_txt = f"%{txt}%"
    prefix_txt = f"{txt}%"
    spaced_pattern = _spaced_letter_pattern(txt)
    spaced_enabled = 1 if spaced_pattern else 0
    spaced_like = spaced_pattern or "__NO_SPACED_SEARCH__"

    rows = frappe.db.sql(
        """
        SELECT
            i.name,
            i.item_name,
            (
                SELECT ib.barcode
                FROM `tabItem Barcode` ib
                WHERE ib.parent = i.name
                  AND ib.parenttype = 'Item'
                  AND (
                        ib.barcode LIKE %(like_txt)s
                     OR (%(spaced_enabled)s = 1 AND ib.barcode LIKE %(spaced_like)s)
                  )
                ORDER BY
                    CASE WHEN ib.barcode = %(txt)s THEN 0 ELSE 1 END,
                    ib.idx
                LIMIT 1
            ) AS matched_barcode
        FROM `tabItem` i
        WHERE i.disabled = 0
          AND i.is_stock_item = 1
          AND (
                i.name LIKE %(like_txt)s
             OR i.item_name LIKE %(like_txt)s
             OR EXISTS (
                    SELECT 1
                    FROM `tabItem Barcode` ib2
                    WHERE ib2.parent = i.name
                      AND ib2.parenttype = 'Item'
                      AND ib2.barcode LIKE %(like_txt)s
                )
             OR (
                    %(spaced_enabled)s = 1
                AND (
                       i.name LIKE %(spaced_like)s
                    OR i.item_name LIKE %(spaced_like)s
                    OR EXISTS (
                        SELECT 1
                        FROM `tabItem Barcode` ib4
                        WHERE ib4.parent = i.name
                          AND ib4.parenttype = 'Item'
                          AND ib4.barcode LIKE %(spaced_like)s
                    )
                )
             )
          )
        ORDER BY
            CASE
                WHEN i.name = %(txt)s THEN 0
                WHEN i.item_name = %(txt)s THEN 1
                WHEN EXISTS (
                    SELECT 1
                    FROM `tabItem Barcode` ib3
                    WHERE ib3.parent = i.name
                      AND ib3.parenttype = 'Item'
                      AND ib3.barcode = %(txt)s
                ) THEN 2
                WHEN i.name LIKE %(prefix_txt)s THEN 3
                WHEN i.item_name LIKE %(prefix_txt)s THEN 4
                WHEN %(spaced_enabled)s = 1
                     AND i.name LIKE %(spaced_like)s THEN 5
                WHEN %(spaced_enabled)s = 1
                     AND i.item_name LIKE %(spaced_like)s THEN 6
                ELSE 7
            END,
            i.name
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "txt": txt,
            "like_txt": like_txt,
            "prefix_txt": prefix_txt,
            "spaced_enabled": spaced_enabled,
            "spaced_like": spaced_like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
        },
        as_list=True,
    )

    return rows
