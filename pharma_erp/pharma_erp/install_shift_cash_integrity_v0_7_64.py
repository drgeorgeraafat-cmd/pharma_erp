"""Install and repair database metadata for Pharma ERP v0.7.64.

Repair 2 is safe to run after Repair 1 stopped because Frappe's in-process
Meta cache still advertised two Custom Fields that had been rolled back in the
database.  Field discovery and verification in this revision use database
metadata and physical columns directly, not the same-process Meta cache.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


MOVEMENT_OPTIONS = """Opening Float
Till Refill
Return Opening Float
Cash Sales Deposit
Unused Till Refill Return
Other Cash Return
Under Review Driver Cash Deposit
Transfer to Main Safe
Supplier Payment
Operating Expense
Employee Advance
Other
Other Cash Receipt
Other Cash Payment"""

FIELD_DEFINITIONS = {
    "Journal Entry": [
        {
            "fieldname": "custom_pharmacy_shift",
            "label": "Pharmacy Shift",
            "fieldtype": "Link",
            "options": "Pharmacy Shift Closing",
            "read_only": 1,
            "allow_on_submit": 1,
            "insert_after": "user_remark",
        },
    ],
    "Payment Entry": [
        {
            "fieldname": "custom_shift_cash_movement",
            "label": "Shift Cash Movement",
            "fieldtype": "Link",
            "options": "Shift Cash Movement",
            "read_only": 1,
            "allow_on_submit": 1,
            "insert_after": "custom_pharmacy_shift",
        },
    ],
    "Shift Cash Movement": [
        {
            "fieldname": "payment_entry",
            "label": "Payment Entry",
            "fieldtype": "Link",
            "options": "Payment Entry",
            "read_only": 1,
            "allow_on_submit": 1,
            "insert_after": "journal_entry",
        },
    ],
    "Pharmacy Shift Closing": [
        {
            "fieldname": "custom_review_cashflow_snapshot",
            "label": "Review Cashflow Snapshot",
            "fieldtype": "Long Text",
            "read_only": 1,
            "allow_on_submit": 1,
            "hidden": 1,
            "insert_after": "custom_review_expected_cash",
        },
        {
            "fieldname": "custom_review_gl_balance",
            "label": "Review GL Balance",
            "fieldtype": "Currency",
            "read_only": 1,
            "allow_on_submit": 1,
            "insert_after": "custom_review_cashflow_snapshot",
        },
    ],
}


def _custom_field_exists(doctype: str, fieldname: str) -> bool:
    return bool(
        frappe.db.exists(
            "Custom Field", {"dt": doctype, "fieldname": fieldname}
        )
    )


def _column_exists(doctype: str, fieldname: str) -> bool:
    value = frappe.db.sql(
        """
        select count(*)
        from information_schema.columns
        where table_schema = database()
          and table_name = %s
          and column_name = %s
        """,
        (f"tab{doctype}", fieldname),
    )[0][0]
    return bool(value)


def _clear_meta_caches() -> None:
    frappe.clear_cache()
    for doctype in FIELD_DEFINITIONS:
        frappe.clear_cache(doctype=doctype)


def _repair_duplicate_purchase_invoice_metadata() -> list[str]:
    """Remove obsolete duplicate metadata without dropping its DB column."""

    standard = frappe.db.get_value(
        "DocField",
        {"parent": "Shift Cash Movement", "fieldname": "purchase_invoice"},
        ["name", "fieldtype", "options"],
        as_dict=True,
    )
    custom_rows = frappe.get_all(
        "Custom Field",
        filters={"dt": "Shift Cash Movement", "fieldname": "purchase_invoice"},
        fields=["name", "fieldtype", "options"],
        order_by="creation asc",
    )

    if not custom_rows:
        return []
    if not standard:
        frappe.throw(
            _(
                "Cannot repair Shift Cash Movement.purchase_invoice because the standard DocField is missing."
            )
        )

    removed: list[str] = []
    for row in custom_rows:
        if (row.fieldtype or "") != (standard.fieldtype or ""):
            frappe.throw(
                _(
                    "Refusing to remove duplicate Custom Field {0}: field type differs from the standard DocField."
                ).format(row.name)
            )
        if (row.options or "") != (standard.options or ""):
            frappe.throw(
                _(
                    "Refusing to remove duplicate Custom Field {0}: options differ from the standard DocField."
                ).format(row.name)
            )

        # Direct metadata deletion is deliberate.  The existing physical
        # purchase_invoice column and all values remain untouched.
        frappe.db.delete("Custom Field", {"name": row.name})
        removed.append(row.name)

    frappe.db.commit()
    _clear_meta_caches()

    remaining = frappe.db.count(
        "Custom Field",
        filters={"dt": "Shift Cash Movement", "fieldname": "purchase_invoice"},
    )
    if remaining:
        frappe.throw(_("Duplicate purchase_invoice Custom Field metadata still exists."))
    return removed


def _ensure_fields() -> dict[str, list[str]]:
    # A failed create_custom_fields transaction can leave stale Meta objects in
    # local/Redis caches even though the Custom Field rows and columns rolled
    # back.  Clear all relevant caches first, then inspect the database itself.
    _clear_meta_caches()

    missing: dict[str, list[dict]] = {}
    for doctype, fields in FIELD_DEFINITIONS.items():
        rows = [
            row
            for row in fields
            if not _custom_field_exists(doctype, row["fieldname"])
        ]
        if rows:
            missing[doctype] = rows

    if missing:
        create_custom_fields(missing, update=True)
        frappe.db.commit()

    _clear_meta_caches()

    metadata_absent: list[str] = []
    columns_absent: list[str] = []
    for doctype, fields in FIELD_DEFINITIONS.items():
        for row in fields:
            fieldname = row["fieldname"]
            if not _custom_field_exists(doctype, fieldname):
                metadata_absent.append(f"{doctype}.{fieldname}")
            if not _column_exists(doctype, fieldname):
                columns_absent.append(f"{doctype}.{fieldname}")

    if metadata_absent:
        frappe.throw(
            _("Required v0.7.64 Custom Field metadata is missing: {0}").format(
                ", ".join(metadata_absent)
            )
        )
    if columns_absent:
        frappe.throw(
            _("Required v0.7.64 database columns are missing: {0}").format(
                ", ".join(columns_absent)
            )
        )

    return {
        doctype: [row["fieldname"] for row in fields]
        for doctype, fields in missing.items()
    }


def _update_movement_options() -> None:
    if frappe.db.exists(
        "DocField", {"parent": "Shift Cash Movement", "fieldname": "movement_type"}
    ):
        frappe.db.set_value(
            "DocField",
            {"parent": "Shift Cash Movement", "fieldname": "movement_type"},
            "options",
            MOVEMENT_OPTIONS,
            update_modified=False,
        )
    if frappe.db.exists(
        "Custom Field", {"dt": "Shift Cash Movement", "fieldname": "movement_type"}
    ):
        frappe.db.set_value(
            "Custom Field",
            {"dt": "Shift Cash Movement", "fieldname": "movement_type"},
            "options",
            MOVEMENT_OPTIONS,
            update_modified=False,
        )
    frappe.db.commit()
    frappe.clear_cache(doctype="Shift Cash Movement")


def _backfill_payment_entry_shifts() -> int:
    if not _column_exists("Payment Entry", "custom_pharmacy_shift"):
        return 0
    frappe.db.sql(
        """
        update `tabPayment Entry` pe
        inner join `tabCash Drawer` drawer
            on drawer.enabled=1
           and drawer.company=pe.company
           and (drawer.cash_account=pe.paid_from or drawer.cash_account=pe.paid_to)
        set pe.custom_pharmacy_shift = coalesce(
            nullif(pe.custom_collection_shift, ''),
            nullif(pe.custom_sales_shift, ''),
            nullif(pe.custom_delivery_shift, '')
        )
        where coalesce(pe.custom_pharmacy_shift, '')=''
          and coalesce(
            nullif(pe.custom_collection_shift, ''),
            nullif(pe.custom_sales_shift, ''),
            nullif(pe.custom_delivery_shift, '')
          ) is not null
        """
    )
    return int(getattr(frappe.db._cursor, "rowcount", 0) or 0)


def _backfill_journal_entry_shifts() -> int:
    if not _column_exists("Journal Entry", "custom_pharmacy_shift"):
        return 0

    total = 0
    frappe.db.sql(
        """
        update `tabJournal Entry` je
        inner join `tabShift Cash Movement` scm on scm.journal_entry=je.name
        set je.custom_pharmacy_shift=scm.shift_reference
        where coalesce(je.custom_pharmacy_shift, '')=''
          and coalesce(scm.shift_reference, '')!=''
          and scm.docstatus != 2
        """
    )
    total += int(getattr(frappe.db._cursor, "rowcount", 0) or 0)

    frappe.db.sql(
        """
        update `tabJournal Entry` je
        inner join `tabEmployee Cash Advance` eca on eca.journal_entry=je.name
        set je.custom_pharmacy_shift=eca.shift_reference
        where coalesce(je.custom_pharmacy_shift, '')=''
          and coalesce(eca.shift_reference, '')!=''
          and eca.docstatus != 2
        """
    )
    total += int(getattr(frappe.db._cursor, "rowcount", 0) or 0)
    return total


def _verification_state() -> dict:
    duplicate_count = frappe.db.count(
        "Custom Field",
        filters={"dt": "Shift Cash Movement", "fieldname": "purchase_invoice"},
    )
    if duplicate_count:
        frappe.throw(_("Duplicate purchase_invoice metadata remains after repair."))

    missing_metadata: list[str] = []
    missing_columns: list[str] = []
    for doctype, fields in FIELD_DEFINITIONS.items():
        for row in fields:
            fieldname = row["fieldname"]
            if not _custom_field_exists(doctype, fieldname):
                missing_metadata.append(f"{doctype}.{fieldname}")
            if not _column_exists(doctype, fieldname):
                missing_columns.append(f"{doctype}.{fieldname}")

    if missing_metadata or missing_columns:
        frappe.throw(
            _(
                "v0.7.64 metadata verification failed. Missing metadata: {0}; missing columns: {1}"
            ).format(
                ", ".join(missing_metadata) or "None",
                ", ".join(missing_columns) or "None",
            )
        )

    payment_count = frappe.db.sql(
        """
        select count(*)
        from `tabPayment Entry`
        where coalesce(custom_pharmacy_shift, '') != ''
        """
    )[0][0]
    journal_count = frappe.db.sql(
        """
        select count(*)
        from `tabJournal Entry`
        where coalesce(custom_pharmacy_shift, '') != ''
        """
    )[0][0]

    return {
        "duplicate_purchase_invoice_custom_fields": int(duplicate_count or 0),
        "required_custom_fields": "present",
        "required_database_columns": "present",
        "payment_entries_with_canonical_shift": int(payment_count or 0),
        "journal_entries_with_canonical_shift": int(journal_count or 0),
    }


def verify_installation():
    result = _verification_state()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


def execute():
    removed_duplicates = _repair_duplicate_purchase_invoice_metadata()
    created = _ensure_fields()
    _update_movement_options()
    pe_backfill = _backfill_payment_entry_shifts()
    je_backfill = _backfill_journal_entry_shifts()
    frappe.db.commit()
    _clear_meta_caches()

    result = {
        "version": "v0.7.64-repair-2",
        "removed_duplicate_metadata": removed_duplicates,
        "created_custom_fields": created,
        "payment_entry_shift_backfill_count": pe_backfill,
        "journal_entry_shift_backfill_count": je_backfill,
        "movement_options_updated": True,
        "verification": _verification_state(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return result


if __name__ == "__main__":
    execute()
