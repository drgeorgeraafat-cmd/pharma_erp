import frappe

VERSION = "2.23"
ITEM_DOCTYPE = "Delivery Return Item"
REQUEST_DOCTYPE = "Delivery Return Request"


def _insert_field(doc, values, before=None, after=None):
    existing = next((row for row in doc.fields if row.fieldname == values["fieldname"]), None)
    if existing:
        for key, value in values.items():
            existing.set(key, value)
        return "updated"

    index = len(doc.fields)
    if before:
        for i, row in enumerate(doc.fields):
            if row.fieldname == before:
                index = i
                break
    elif after:
        for i, row in enumerate(doc.fields):
            if row.fieldname == after:
                index = i + 1
                break

    row = doc.append("fields", values)
    doc.fields.remove(row)
    doc.fields.insert(index, row)
    return "created"


def _backfill_existing_rows():
    if not frappe.db.table_exists(f"tab{ITEM_DOCTYPE}"):
        return {"source_invoice": 0, "credit_note": 0}

    source_count = frappe.db.sql(
        f"""
        UPDATE `tab{ITEM_DOCTYPE}` item
        INNER JOIN `tab{REQUEST_DOCTYPE}` request
            ON request.name = item.parent
           AND item.parenttype = %(request_doctype)s
        SET item.source_invoice = request.sales_invoice
        WHERE IFNULL(item.source_invoice, '') = ''
        """,
        {"request_doctype": REQUEST_DOCTYPE},
    )

    credit_count = frappe.db.sql(
        f"""
        UPDATE `tab{ITEM_DOCTYPE}` item
        INNER JOIN `tab{REQUEST_DOCTYPE}` request
            ON request.name = item.parent
           AND item.parenttype = %(request_doctype)s
        SET item.credit_note = request.credit_note
        WHERE IFNULL(item.credit_note, '') = ''
          AND IFNULL(request.credit_note, '') != ''
        """,
        {"request_doctype": REQUEST_DOCTYPE},
    )
    return {
        "source_invoice": getattr(source_count, "rowcount", 0) if source_count is not None else 0,
        "credit_note": getattr(credit_count, "rowcount", 0) if credit_count is not None else 0,
    }


@frappe.whitelist()
def install():
    frappe.only_for("System Manager")
    missing = [name for name in (ITEM_DOCTYPE, REQUEST_DOCTYPE) if not frappe.db.exists("DocType", name)]
    if missing:
        frappe.throw("Run Delivery Partial Return V2.22 first. Missing: " + ", ".join(missing))

    doc = frappe.get_doc("DocType", ITEM_DOCTYPE)
    results = {
        "source_invoice": _insert_field(
            doc,
            {
                "label": "Source Invoice",
                "fieldname": "source_invoice",
                "fieldtype": "Link",
                "options": "Sales Invoice",
                "reqd": 1,
                "read_only": 1,
                "in_list_view": 1,
            },
            before="source_item",
        ),
        "credit_note": _insert_field(
            doc,
            {
                "label": "Credit Note",
                "fieldname": "credit_note",
                "fieldtype": "Link",
                "options": "Sales Invoice",
                "read_only": 1,
            },
            before="credit_note_item",
        ),
    }
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.db.updatedb(ITEM_DOCTYPE)
    frappe.db.commit()
    frappe.clear_cache(doctype=ITEM_DOCTYPE)

    backfilled = _backfill_existing_rows()
    frappe.db.commit()
    result = verify()
    result.update({"field_results": results, "backfilled": backfilled})
    print("Delivery partial return workflow V2.23 installed successfully.")
    return result


@frappe.whitelist()
def verify():
    if not frappe.db.exists("DocType", ITEM_DOCTYPE):
        return {"version": VERSION, "ready": False, "missing_doctype": ITEM_DOCTYPE}
    meta = frappe.get_meta(ITEM_DOCTYPE)
    missing_fields = [fieldname for fieldname in ("source_invoice", "credit_note") if not meta.has_field(fieldname)]
    return {
        "version": VERSION,
        "missing_fields": missing_fields,
        "ready": not missing_fields,
    }
