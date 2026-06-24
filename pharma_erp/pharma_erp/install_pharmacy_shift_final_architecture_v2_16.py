import json

import frappe

from pharma_erp.pharma_erp import install_pharmacy_shift_card_management_v2 as base

COMPANY = "Cure"
DEFAULT_DRAWER = "DRAWER-01"
DEFAULT_CASH_ACCOUNT = "Cashier Till - C"


REPAIR_DOCTYPES = [
    "Delivery Handover",
    "Delivery Settlement",
    "Pharmacy Shift Closing",
]


def repair_duplicate_fields():
    """Repair invalid duplicate field definitions left by older installers.

    A submittable custom DocType already owns its standard ``amended_from``
    DocField. Older customizations can also leave a Custom Field with the same
    fieldname, or duplicate DocField child rows. Any later Custom Field save
    then fails validation for the whole DocType. This repair keeps one native
    DocField and removes only duplicate definitions.
    """
    result = {
        "removed_duplicate_docfields": [],
        "removed_conflicting_custom_fields": [],
    }

    existing_doctypes = [
        name for name in REPAIR_DOCTYPES if frappe.db.exists("DocType", name)
    ]
    if not existing_doctypes:
        return result

    placeholders = ", ".join(["%s"] * len(existing_doctypes))

    duplicate_groups = frappe.db.sql(
        f"""
        SELECT parent, fieldname, COUNT(*) AS row_count
        FROM `tabDocField`
        WHERE parent IN ({placeholders})
          AND parentfield = 'fields'
          AND IFNULL(fieldname, '') != ''
        GROUP BY parent, fieldname
        HAVING COUNT(*) > 1
        """,
        tuple(existing_doctypes),
        as_dict=True,
    )

    for group in duplicate_groups:
        rows = frappe.db.sql(
            """
            SELECT name, parent, fieldname, fieldtype, options, label, idx,
                   creation, modified
            FROM `tabDocField`
            WHERE parent = %s
              AND parentfield = 'fields'
              AND fieldname = %s
            ORDER BY idx ASC, creation ASC, name ASC
            """,
            (group.parent, group.fieldname),
            as_dict=True,
        )
        if len(rows) < 2:
            continue

        def row_score(row):
            score = 0
            if row.fieldtype:
                score += 2
            if row.label:
                score += 1
            if row.options:
                score += 1
            if row.fieldname == "amended_from":
                if row.fieldtype == "Link":
                    score += 10
                if row.options == row.parent:
                    score += 10
            # Prefer the earlier row only when definitions are otherwise equal.
            score -= float(row.idx or 0) / 100000.0
            return score

        keeper = max(rows, key=row_score)
        min_idx = min(int(row.idx or 0) for row in rows)
        if int(keeper.idx or 0) != min_idx:
            frappe.db.set_value(
                "DocField", keeper.name, "idx", min_idx, update_modified=False
            )

        for row in rows:
            if row.name == keeper.name:
                continue
            frappe.db.sql("DELETE FROM `tabDocField` WHERE name = %s", row.name)
            result["removed_duplicate_docfields"].append(
                {
                    "doctype": row.parent,
                    "fieldname": row.fieldname,
                    "removed": row.name,
                    "kept": keeper.name,
                }
            )

    # A Custom Field must never reuse the fieldname of a native DocField.
    # The known failure is amended_from on submittable custom DocTypes.
    conflicting_custom_fields = frappe.db.sql(
        f"""
        SELECT cf.name, cf.dt, cf.fieldname
        FROM `tabCustom Field` cf
        INNER JOIN `tabDocField` df
            ON df.parent = cf.dt
           AND df.parentfield = 'fields'
           AND df.fieldname = cf.fieldname
        WHERE cf.dt IN ({placeholders})
          AND cf.fieldname = 'amended_from'
        """,
        tuple(existing_doctypes),
        as_dict=True,
    )

    for row in conflicting_custom_fields:
        frappe.db.sql("DELETE FROM `tabCustom Field` WHERE name = %s", row.name)
        result["removed_conflicting_custom_fields"].append(
            {
                "doctype": row.dt,
                "fieldname": row.fieldname,
                "removed": row.name,
            }
        )

    frappe.db.commit()
    for doctype in existing_doctypes:
        frappe.clear_cache(doctype=doctype)

    return result


def F(label, fieldname, fieldtype, **kwargs):
    row = {"label": label, "fieldname": fieldname, "fieldtype": fieldtype}
    row.update(kwargs)
    return row


DOCTYPE_SPECS = {
    "Cash Drawer": {
        "module": "Pharma Erp",
        "custom": 1,
        "istable": 0,
        "is_submittable": 0,
        "autoname": "field:drawer_code",
        "title_field": "drawer_name",
        "search_fields": "drawer_code,drawer_name,company,branch,cash_account,physical_location",
        "fields": [
            F("Drawer", "drawer_section", "Section Break"),
            F("Drawer Name", "drawer_name", "Data", reqd=1, in_list_view=1),
            F("Drawer Code", "drawer_code", "Data", reqd=1, unique=1, in_list_view=1),
            F("Company", "company", "Link", options="Company", reqd=1, default=COMPANY, in_list_view=1),
            F("", "column_break_1", "Column Break"),
            F("Branch", "branch", "Link", options="Branch"),
            F("Physical Location", "physical_location", "Data"),
            F("Enabled", "enabled", "Check", default="1", in_list_view=1),
            F("Accounting", "accounting_section", "Section Break"),
            F("Cash Account", "cash_account", "Link", options="Account", reqd=1, in_list_view=1),
            F("Default Opening Float", "default_opening_float", "Currency", default="0"),
            F("", "column_break_2", "Column Break"),
            F("Current Responsible User", "current_responsible_user", "Link", options="User", read_only=1),
            F("Current Active Shift", "current_active_shift", "Link", options="Pharmacy Shift Closing", read_only=1),
            F("Notes", "notes_section", "Section Break"),
            F("Notes", "notes", "Small Text"),
        ],
    },
    "Delivery Handover Allocation": {
        "module": "Pharma Erp",
        "custom": 1,
        "istable": 1,
        "is_submittable": 0,
        "fields": [
            F("Source Key", "payment_source_key", "Data", read_only=1),
            F("Payment Entry", "payment_entry", "Link", options="Payment Entry", read_only=1, in_list_view=1),
            F("Sales Invoice", "sales_invoice", "Link", options="Sales Invoice", read_only=1, in_list_view=1),
            F("Allocation Type", "allocation_type", "Select", options="Cash Handover\nShortage", read_only=1, in_list_view=1),
            F("Amount", "amount", "Currency", read_only=1, in_list_view=1),
            F("Sales Shift", "sales_shift", "Link", options="Pharmacy Shift Closing", read_only=1),
            F("Delivery Shift", "delivery_shift", "Link", options="Pharmacy Shift Closing", read_only=1),
            F("Collection Shift", "collection_shift", "Link", options="Pharmacy Shift Closing", read_only=1),
            F("Transaction Time", "transaction_time", "Datetime", read_only=1),
        ],
    },
    "Delivery Shift Transfer": {
        "module": "Pharma Erp",
        "custom": 1,
        "istable": 0,
        "is_submittable": 1,
        "autoname": "naming_series:",
        "title_field": "sales_invoice",
        "search_fields": "sales_invoice,from_delivery_shift,to_delivery_shift,transferred_by",
        "fields": [
            F("Series", "naming_series", "Select", options="DST-.YYYY.-.#####", default="DST-.YYYY.-.#####", reqd=1, hidden=1),
            F("Order", "order_section", "Section Break"),
            F("Sales Invoice", "sales_invoice", "Link", options="Sales Invoice", reqd=1, in_list_view=1),
            F("Original Sales Shift", "original_sales_shift", "Link", options="Pharmacy Shift Closing", read_only=1),
            F("Original Delivery Shift", "original_delivery_shift", "Link", options="Pharmacy Shift Closing", read_only=1),
            F("", "column_break_1", "Column Break"),
            F("From Delivery Shift", "from_delivery_shift", "Link", options="Pharmacy Shift Closing", reqd=1, read_only=1, in_list_view=1),
            F("To Delivery Shift", "to_delivery_shift", "Link", options="Pharmacy Shift Closing", reqd=1, read_only=1, in_list_view=1),
            F("Delivery Status", "delivery_status", "Data", read_only=1),
            F("Transfer Audit", "audit_section", "Section Break"),
            F("Transferred By", "transferred_by", "Link", options="User", read_only=1, in_list_view=1),
            F("Transferred At", "transferred_at", "Datetime", read_only=1, in_list_view=1),
            F("Reason", "reason", "Small Text", reqd=1),
            F("Amended From", "amended_from", "Link", options="Delivery Shift Transfer", read_only=1, hidden=1, no_copy=1),
        ],
    },
}


PAYMENT_ENTRY_SHIFT_SCRIPT = r'''
sales_shifts = []
delivery_shifts = []
received_by_values = []
order_types = []

invoice_meta = frappe.get_meta("Sales Invoice")

for reference in doc.get("references") or []:
    if reference.reference_doctype != "Sales Invoice":
        continue

    fields = ["name"]
    for fieldname in [
        "custom_pharmacy_shift",
        "custom_delivery_shift",
        "custom_collection_received_by",
        "custom_order_type",
    ]:
        if invoice_meta.has_field(fieldname):
            fields.append(fieldname)

    invoice = frappe.db.get_value(
        "Sales Invoice",
        reference.reference_name,
        fields,
        as_dict=True,
    )

    if not invoice:
        continue

    sales_shift = invoice.get("custom_pharmacy_shift") or ""
    delivery_shift = invoice.get("custom_delivery_shift") or sales_shift
    received_by = invoice.get("custom_collection_received_by") or ""
    order_type = invoice.get("custom_order_type") or ""

    if sales_shift and sales_shift not in sales_shifts:
        sales_shifts.append(sales_shift)
    if delivery_shift and delivery_shift not in delivery_shifts:
        delivery_shifts.append(delivery_shift)
    if received_by and received_by not in received_by_values:
        received_by_values.append(received_by)
    if order_type and order_type not in order_types:
        order_types.append(order_type)

if len(sales_shifts) > 1:
    frappe.throw("The referenced invoices belong to different sales shifts.")

if len(delivery_shifts) > 1:
    frappe.throw("The referenced invoices belong to different delivery shifts.")

sales_shift = sales_shifts[0] if sales_shifts else ""
delivery_shift = delivery_shifts[0] if delivery_shifts else sales_shift

if frappe.get_meta("Payment Entry").has_field("custom_pharmacy_shift") and sales_shift:
    doc.custom_pharmacy_shift = sales_shift

if frappe.get_meta("Payment Entry").has_field("custom_sales_shift") and sales_shift:
    doc.custom_sales_shift = sales_shift

if frappe.get_meta("Payment Entry").has_field("custom_delivery_shift") and delivery_shift:
    doc.custom_delivery_shift = delivery_shift

is_driver_cash = (
    doc.mode_of_payment == "Cash"
    and "Home Delivery" in order_types
    and "Delivery Boy" in received_by_values
)

if (
    frappe.get_meta("Payment Entry").has_field("custom_collection_shift")
    and not doc.get("custom_collection_shift")
    and not is_driver_cash
):
    shift_rows = frappe.get_all(
        "Pharmacy Shift Closing",
        filters={
            "company": doc.company,
            "docstatus": 0,
            "custom_shift_operational_status": "Active",
        },
        fields=["name", "cashier", "owner", "creation"],
        order_by="creation desc",
        limit_page_length=100,
    )

    selected = None
    for row in shift_rows:
        if row.cashier == frappe.session.user or row.owner == frappe.session.user:
            selected = row
            break

    if not selected and shift_rows:
        selected = shift_rows[0]

    if selected:
        doc.custom_collection_shift = selected.name
'''


SALES_INVOICE_DELIVERY_SHIFT_SCRIPT = r'''
if doc.get("custom_order_type") == "Home Delivery":
    sales_shift = doc.get("custom_pharmacy_shift") or ""
    current_delivery_shift = doc.get("custom_delivery_shift") or ""

    if not current_delivery_shift and sales_shift:
        doc.custom_delivery_shift = sales_shift
        current_delivery_shift = sales_shift

    if not doc.get("custom_original_delivery_shift") and current_delivery_shift:
        doc.custom_original_delivery_shift = current_delivery_shift
'''


def _upsert_server_script(name, reference_doctype, event, script):
    if frappe.db.exists("Server Script", name):
        doc = frappe.get_doc("Server Script", name)
    else:
        doc = frappe.new_doc("Server Script")
        doc.name = name

    doc.script_type = "DocType Event"
    doc.reference_doctype = reference_doctype
    doc.doctype_event = event
    doc.script = script.strip()
    doc.disabled = 0
    doc.flags.ignore_permissions = True
    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)


def _default_drawer():
    if frappe.db.exists("Cash Drawer", DEFAULT_DRAWER):
        doc = frappe.get_doc("Cash Drawer", DEFAULT_DRAWER)
        doc.drawer_name = doc.drawer_name or "Cashier Drawer 01"
        doc.company = doc.company or COMPANY
        doc.cash_account = doc.cash_account or DEFAULT_CASH_ACCOUNT
        doc.enabled = 1
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        return doc.name

    doc = frappe.new_doc("Cash Drawer")
    doc.drawer_code = DEFAULT_DRAWER
    doc.drawer_name = "Cashier Drawer 01"
    doc.company = COMPANY
    doc.cash_account = DEFAULT_CASH_ACCOUNT
    doc.physical_location = "Main Pharmacy Counter"
    doc.default_opening_float = 0
    doc.enabled = 1
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name


def _add_fields():
    base._custom_field(
        "Pharmacy Shift Closing",
        "custom_cash_drawer",
        {
            "label": "Cash Drawer",
            "fieldtype": "Link",
            "options": "Cash Drawer",
            "insert_after": "cash_account",
            "default": DEFAULT_DRAWER,
            "read_only": 1,
            "allow_on_submit": 1,
            "in_standard_filter": 1,
        },
    )

    base._custom_field(
        "Sales Invoice",
        "custom_delivery_shift",
        {
            "label": "Delivery Shift",
            "fieldtype": "Link",
            "options": "Pharmacy Shift Closing",
            "insert_after": "custom_pharmacy_shift",
            "read_only": 1,
            "allow_on_submit": 1,
            "in_standard_filter": 1,
        },
    )
    base._custom_field(
        "Sales Invoice",
        "custom_original_delivery_shift",
        {
            "label": "Original Delivery Shift",
            "fieldtype": "Link",
            "options": "Pharmacy Shift Closing",
            "insert_after": "custom_delivery_shift",
            "read_only": 1,
            "allow_on_submit": 1,
        },
    )
    base._custom_field(
        "Sales Invoice",
        "custom_last_delivery_transfer",
        {
            "label": "Last Delivery Shift Transfer",
            "fieldtype": "Link",
            "options": "Delivery Shift Transfer",
            "insert_after": "custom_original_delivery_shift",
            "read_only": 1,
            "allow_on_submit": 1,
        },
    )

    for doctype in ["Payment Entry"]:
        base._custom_field(
            doctype,
            "custom_sales_shift",
            {
                "label": "Sales Shift",
                "fieldtype": "Link",
                "options": "Pharmacy Shift Closing",
                "insert_after": "custom_pharmacy_shift",
                "read_only": 1,
                "allow_on_submit": 1,
                "in_standard_filter": 1,
            },
        )
        base._custom_field(
            doctype,
            "custom_delivery_shift",
            {
                "label": "Delivery Shift",
                "fieldtype": "Link",
                "options": "Pharmacy Shift Closing",
                "insert_after": "custom_sales_shift",
                "read_only": 1,
                "allow_on_submit": 1,
                "in_standard_filter": 1,
            },
        )
        base._custom_field(
            doctype,
            "custom_collection_shift",
            {
                "label": "Collection Shift",
                "fieldtype": "Link",
                "options": "Pharmacy Shift Closing",
                "insert_after": "custom_delivery_shift",
                "read_only": 1,
                "allow_on_submit": 1,
                "in_standard_filter": 1,
            },
        )

    base._custom_field(
        "Delivery Handover",
        "custom_collection_shift",
        {
            "label": "Collection Shift",
            "fieldtype": "Link",
            "options": "Pharmacy Shift Closing",
            "insert_after": "shift_reference",
            "read_only": 1,
            "allow_on_submit": 1,
            "in_standard_filter": 1,
        },
    )
    base._custom_field(
        "Delivery Handover",
        "custom_allocations",
        {
            "label": "Collection Allocations",
            "fieldtype": "Table",
            "options": "Delivery Handover Allocation",
            "insert_after": "amount",
            "read_only": 1,
            "allow_on_submit": 1,
        },
    )
    base._custom_field(
        "Delivery Settlement",
        "custom_collection_shift",
        {
            "label": "Collection Shift",
            "fieldtype": "Link",
            "options": "Pharmacy Shift Closing",
            "insert_after": "shift_reference",
            "read_only": 1,
            "allow_on_submit": 1,
            "in_standard_filter": 1,
        },
    )


def _disable_legacy_handover_scripts():
    names = [
        "Validate Delivery Handover",
        "Settlement After Handover",
        "Recalculate Settlement After Handover Cancel",
        "Auto Create Driver Shortage After Final Handover",
    ]
    for name in names:
        if frappe.db.exists("Server Script", name):
            frappe.db.set_value("Server Script", name, "disabled", 1)


def _backfill_cash_drawer(drawer_name):
    if not frappe.get_meta("Pharmacy Shift Closing").has_field("custom_cash_drawer"):
        return 0

    rows = frappe.get_all(
        "Pharmacy Shift Closing",
        fields=["name", "docstatus", "custom_shift_operational_status", "custom_cash_drawer", "cashier", "owner"],
        limit_page_length=100000,
    )
    rows = [row for row in rows if not row.custom_cash_drawer]
    updated = 0
    active_shift = ""
    for row in rows:
        frappe.db.set_value(
            "Pharmacy Shift Closing",
            row.name,
            {
                "custom_cash_drawer": drawer_name,
                "cash_account": DEFAULT_CASH_ACCOUNT,
            },
            update_modified=False,
        )
        updated += 1
        if row.docstatus == 0 and row.custom_shift_operational_status == "Active" and not active_shift:
            active_shift = row.name

    if active_shift:
        frappe.db.set_value(
            "Cash Drawer",
            drawer_name,
            {
                "current_active_shift": active_shift,
                "current_responsible_user": frappe.db.get_value(
                    "Pharmacy Shift Closing", active_shift, "cashier"
                ) or frappe.db.get_value(
                    "Pharmacy Shift Closing", active_shift, "owner"
                ) or "",
            },
            update_modified=False,
        )
    return updated


def _backfill_delivery_shift_fields():
    meta = frappe.get_meta("Sales Invoice")
    if not (
        meta.has_field("custom_delivery_shift")
        and meta.has_field("custom_pharmacy_shift")
    ):
        return 0

    rows = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "custom_order_type": "Home Delivery",
        },
        fields=[
            "name",
            "custom_pharmacy_shift",
            "custom_delivery_shift",
            "custom_original_delivery_shift",
        ],
        limit_page_length=100000,
    )

    updated = 0
    for row in rows:
        delivery_shift = row.custom_delivery_shift or row.custom_pharmacy_shift
        original_shift = row.custom_original_delivery_shift or delivery_shift
        values = {}
        if delivery_shift and not row.custom_delivery_shift:
            values["custom_delivery_shift"] = delivery_shift
        if original_shift and not row.custom_original_delivery_shift:
            values["custom_original_delivery_shift"] = original_shift
        if values:
            frappe.db.set_value("Sales Invoice", row.name, values, update_modified=False)
            updated += 1
    return updated


def install():
    field_repair = repair_duplicate_fields()
    base_result = base.install()

    for name, spec in DOCTYPE_SPECS.items():
        base._upsert_doctype(name, spec)

    _add_fields()
    frappe.db.commit()
    frappe.clear_cache()
    drawer = _default_drawer()

    _upsert_server_script(
        "Payment Entry - Pharmacy Shift Reference",
        "Payment Entry",
        "Before Save",
        PAYMENT_ENTRY_SHIFT_SCRIPT,
    )
    _upsert_server_script(
        "Sales Invoice - Delivery Shift Initialization",
        "Sales Invoice",
        "Before Save",
        SALES_INVOICE_DELIVERY_SHIFT_SCRIPT,
    )

    _disable_legacy_handover_scripts()
    backfilled_drawers = _backfill_cash_drawer(drawer)
    backfilled = _backfill_delivery_shift_fields()

    frappe.db.commit()
    frappe.clear_cache()

    result = {
        "version": "2.16.1",
        "field_repair": field_repair,
        "base": base_result,
        "doctypes": list(DOCTYPE_SPECS),
        "default_cash_drawer": drawer,
        "backfilled_delivery_orders": backfilled,
        "backfilled_shifts_with_cash_drawer": backfilled_drawers,
    }
    print("Pharmacy Shift Final Architecture V2.16.1 installed successfully.")
    print(json.dumps(result, default=str, indent=2))
    return result


def inspect_duplicate_fields():
    """Return duplicate-field diagnostics without modifying metadata."""
    existing_doctypes = [
        name for name in REPAIR_DOCTYPES if frappe.db.exists("DocType", name)
    ]
    duplicate_docfields = []
    conflicting_custom_fields = []

    if existing_doctypes:
        placeholders = ", ".join(["%s"] * len(existing_doctypes))
        duplicate_docfields = frappe.db.sql(
            f"""
            SELECT parent AS doctype, fieldname, COUNT(*) AS row_count
            FROM `tabDocField`
            WHERE parent IN ({placeholders})
              AND parentfield = 'fields'
              AND IFNULL(fieldname, '') != ''
            GROUP BY parent, fieldname
            HAVING COUNT(*) > 1
            ORDER BY parent, fieldname
            """,
            tuple(existing_doctypes),
            as_dict=True,
        )
        conflicting_custom_fields = frappe.db.sql(
            f"""
            SELECT cf.name, cf.dt AS doctype, cf.fieldname
            FROM `tabCustom Field` cf
            INNER JOIN `tabDocField` df
                ON df.parent = cf.dt
               AND df.parentfield = 'fields'
               AND df.fieldname = cf.fieldname
            WHERE cf.dt IN ({placeholders})
              AND cf.fieldname = 'amended_from'
            ORDER BY cf.dt, cf.name
            """,
            tuple(existing_doctypes),
            as_dict=True,
        )

    return {
        "duplicate_docfields": duplicate_docfields,
        "conflicting_custom_fields": conflicting_custom_fields,
        "clean": not duplicate_docfields and not conflicting_custom_fields,
    }


def verify():
    field_repair = inspect_duplicate_fields()
    field_checks = {
        "Pharmacy Shift Closing.custom_cash_drawer": frappe.get_meta("Pharmacy Shift Closing").has_field("custom_cash_drawer"),
        "Sales Invoice.custom_delivery_shift": frappe.get_meta("Sales Invoice").has_field("custom_delivery_shift"),
        "Sales Invoice.custom_original_delivery_shift": frappe.get_meta("Sales Invoice").has_field("custom_original_delivery_shift"),
        "Payment Entry.custom_collection_shift": frappe.get_meta("Payment Entry").has_field("custom_collection_shift"),
        "Delivery Handover.custom_collection_shift": frappe.get_meta("Delivery Handover").has_field("custom_collection_shift"),
        "Delivery Handover.custom_allocations": frappe.get_meta("Delivery Handover").has_field("custom_allocations"),
    }

    result = {
        "version": "2.16.2",
        "field_repair": field_repair,
        "doctypes": {name: bool(frappe.db.exists("DocType", name)) for name in DOCTYPE_SPECS},
        "fields": field_checks,
        "default_cash_drawer": bool(frappe.db.exists("Cash Drawer", DEFAULT_DRAWER)),
        "drawer_account": frappe.db.get_value("Cash Drawer", DEFAULT_DRAWER, "cash_account") if frappe.db.exists("Cash Drawer", DEFAULT_DRAWER) else None,
        "legacy_handover_scripts_disabled": {
            name: frappe.db.get_value("Server Script", name, "disabled")
            for name in [
                "Validate Delivery Handover",
                "Settlement After Handover",
                "Recalculate Settlement After Handover Cancel",
                "Auto Create Driver Shortage After Final Handover",
            ]
            if frappe.db.exists("Server Script", name)
        },
    }
    result["ready"] = (
        all(result["doctypes"].values())
        and all(field_checks.values())
        and result["default_cash_drawer"]
        and result["drawer_account"] == DEFAULT_CASH_ACCOUNT
        and field_repair["clean"]
    )
    print(json.dumps(result, default=str, indent=2))
    return result
