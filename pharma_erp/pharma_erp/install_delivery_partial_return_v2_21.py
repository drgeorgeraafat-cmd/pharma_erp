import frappe

VERSION = "2.21"


def F(label, fieldname, fieldtype, **kwargs):
    row = {"label": label, "fieldname": fieldname, "fieldtype": fieldtype}
    row.update(kwargs)
    return row


DOCTYPE_SPECS = {
    "Delivery Return Item": {
        "module": "Pharma Erp",
        "custom": 1,
        "istable": 1,
        "is_submittable": 0,
        "fields": [
            F("Source Invoice Item", "source_item", "Link", options="Sales Invoice Item", reqd=1, read_only=1),
            F("Item Code", "item_code", "Link", options="Item", reqd=1, read_only=1, in_list_view=1),
            F("Item Name", "item_name", "Data", read_only=1, in_list_view=1),
            F("Batch No", "batch_no", "Link", options="Batch", read_only=1),
            F("Warehouse", "warehouse", "Link", options="Warehouse", read_only=1),
            F("Sold Qty", "sold_qty", "Float", read_only=1),
            F("Previously Returned Qty", "previously_returned_qty", "Float", read_only=1),
            F("Return Qty", "return_qty", "Float", reqd=1, in_list_view=1),
            F("Pack Size", "pack_size", "Float", read_only=1),
            F("Return Boxes", "return_box_qty", "Float", read_only=1),
            F("Return Units", "return_unit_qty", "Float", read_only=1),
            F("Rate", "rate", "Currency", read_only=1),
            F("Amount", "amount", "Currency", read_only=1, in_list_view=1),
            F("Reason", "reason", "Data"),
            F("Credit Note Item", "credit_note_item", "Link", options="Sales Invoice Item", read_only=1),
            F("Completed", "completed", "Check", default="0", read_only=1),
        ],
    },
    "Delivery Return Request": {
        "module": "Pharma Erp",
        "custom": 1,
        "istable": 0,
        "is_submittable": 0,
        "autoname": "naming_series:",
        "title_field": "sales_invoice",
        "search_fields": "sales_invoice,return_type,status,delivery_boy,credit_note",
        "fields": [
            F("Series", "naming_series", "Select", options="DRR-.YYYY.-.#####", default="DRR-.YYYY.-.#####", reqd=1, hidden=1),
            F("Request", "request_section", "Section Break"),
            F("Sales Invoice", "sales_invoice", "Link", options="Sales Invoice", reqd=1, read_only=1, in_list_view=1),
            F("Return Type", "return_type", "Select", options="Full Order Cancellation\nPartial Item Return", reqd=1, read_only=1, in_list_view=1),
            F("Status", "status", "Select", options="Requested\nReturning to Pharmacy\nReturned to Pharmacy\nAwaiting Manager Review\nCredit Note Draft\nPartial Return Completed\nFull Return Completed\nCancelled", reqd=1, default="Requested", read_only=1, in_list_view=1),
            F("", "column_break_1", "Column Break"),
            F("Company", "company", "Link", options="Company", reqd=1, read_only=1),
            F("Customer", "customer", "Link", options="Customer", reqd=1, read_only=1),
            F("Delivery Boy", "delivery_boy", "Link", options="Employee", read_only=1, in_list_view=1),
            F("Delivery Trip", "delivery_trip", "Link", options="Delivery Trip", read_only=1),
            F("Shifts", "shift_section", "Section Break"),
            F("Sales Shift", "sales_shift", "Link", options="Pharmacy Shift Closing", read_only=1),
            F("Delivery Shift", "delivery_shift", "Link", options="Pharmacy Shift Closing", read_only=1),
            F("Collection Shift", "collection_shift", "Link", options="Pharmacy Shift Closing", read_only=1),
            F("Reason", "reason_section", "Section Break"),
            F("Reason", "reason", "Select", options="Customer Cancelled Order\nCustomer Refused Order\nItem Rejected by Customer\nWrong Item\nDamaged Item\nPayment Problem\nOther", reqd=1, read_only=1),
            F("Notes", "notes", "Small Text", read_only=1),
            F("Items", "items_section", "Section Break"),
            F("Returned Items", "items", "Table", options="Delivery Return Item", reqd=1, read_only=1),
            F("Amounts", "amounts_section", "Section Break"),
            F("Source Grand Total", "source_grand_total", "Currency", read_only=1),
            F("Estimated Return Amount", "estimated_return_amount", "Currency", read_only=1),
            F("Remaining Collectible", "remaining_collectible", "Currency", read_only=1),
            F("Reported Collected Amount", "reported_collected_amount", "Currency", read_only=1),
            F("", "column_break_2", "Column Break"),
            F("Credit Note", "credit_note", "Link", options="Sales Invoice", read_only=1, in_list_view=1),
            F("Reconciled Amount", "reconciled_amount", "Currency", read_only=1),
            F("Remaining Invoice Outstanding", "remaining_invoice_outstanding", "Currency", read_only=1),
            F("Audit", "audit_section", "Section Break"),
            F("Requested By", "requested_by", "Link", options="User", read_only=1),
            F("Requested At", "requested_at", "Datetime", read_only=1),
            F("Driver Returned At", "driver_returned_at", "Datetime", read_only=1),
            F("Received By", "received_by", "Link", options="User", read_only=1),
            F("Received At", "received_at", "Datetime", read_only=1),
            F("Completed By", "completed_by", "Link", options="User", read_only=1),
            F("Completed At", "completed_at", "Datetime", read_only=1),
        ],
    },
}


SALES_INVOICE_FIELDS = {
    "custom_active_delivery_return_request": {
        "label": "Active Delivery Return Request",
        "fieldtype": "Link",
        "options": "Delivery Return Request",
        "insert_after": "custom_delivery_return_credit_note",
        "read_only": 1,
        "allow_on_submit": 1,
        "hidden": 1,
    },
    "custom_last_delivery_return_request": {
        "label": "Last Delivery Return Request",
        "fieldtype": "Link",
        "options": "Delivery Return Request",
        "insert_after": "custom_active_delivery_return_request",
        "read_only": 1,
        "allow_on_submit": 1,
        "hidden": 1,
    },
    "custom_delivery_return_type": {
        "label": "Delivery Return Type",
        "fieldtype": "Select",
        "options": "Not Required\nFull Order Cancellation\nPartial Item Return",
        "default": "Not Required",
        "insert_after": "custom_last_delivery_return_request",
        "read_only": 1,
        "allow_on_submit": 1,
        "hidden": 1,
    },
}

RETURN_STATUS_OPTIONS = [
    "Partial Return Requested",
    "Partial Return Returning",
    "Partial Return Awaiting Review",
    "Partial Credit Note Draft",
    "Partial Return Completed",
]


def _ensure_permission(doc):
    for row in doc.permissions:
        if row.role == "System Manager":
            row.read = row.write = row.create = 1
            return
    doc.append("permissions", {"role": "System Manager", "read": 1, "write": 1, "create": 1})


def _upsert_doctype(name, spec):
    doc = frappe.get_doc("DocType", name) if frappe.db.exists("DocType", name) else frappe.new_doc("DocType")
    if doc.is_new():
        doc.name = name
    for key in ("module", "custom", "istable", "is_submittable", "autoname", "title_field", "search_fields"):
        if key in spec:
            doc.set(key, spec[key])

    seen = set()
    for row in list(doc.fields):
        if row.fieldname and row.fieldname in seen:
            doc.remove(row)
        elif row.fieldname:
            seen.add(row.fieldname)
    existing = {row.fieldname: row for row in doc.fields if row.fieldname}
    for values in spec["fields"]:
        fieldname = values.get("fieldname")
        if fieldname and fieldname in existing:
            row = existing[fieldname]
            for key, value in values.items():
                row.set(key, value)
        else:
            doc.append("fields", values)
    if not spec.get("istable"):
        _ensure_permission(doc)
    doc.flags.ignore_permissions = True
    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.db.updatedb(name)
    frappe.db.commit()
    frappe.clear_cache(doctype=name)


def _custom_field(dt, fieldname, values):
    name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
    if name:
        doc = frappe.get_doc("Custom Field", name)
        for key, value in values.items():
            doc.set(key, value)
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        return "updated"
    if frappe.get_meta(dt).has_field(fieldname):
        return "existing"
    doc = frappe.new_doc("Custom Field")
    doc.dt = dt
    doc.fieldname = fieldname
    for key, value in values.items():
        doc.set(key, value)
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return "created"


def _append_return_status_options():
    fieldname = frappe.db.get_value(
        "Custom Field", {"dt": "Sales Invoice", "fieldname": "custom_delivery_return_status"}, "name"
    )
    if not fieldname:
        return []
    doc = frappe.get_doc("Custom Field", fieldname)
    options = [line.strip() for line in str(doc.options or "").splitlines() if line.strip()]
    added = []
    for option in RETURN_STATUS_OPTIONS:
        if option not in options:
            options.append(option)
            added.append(option)
    if added:
        doc.options = "\n".join(options)
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
    return added


@frappe.whitelist()
def install():
    frappe.only_for("System Manager")
    _upsert_doctype("Delivery Return Item", DOCTYPE_SPECS["Delivery Return Item"])
    _upsert_doctype("Delivery Return Request", DOCTYPE_SPECS["Delivery Return Request"])
    field_results = {}
    for fieldname, values in SALES_INVOICE_FIELDS.items():
        field_results[fieldname] = _custom_field("Sales Invoice", fieldname, values)
    added_options = _append_return_status_options()
    frappe.db.commit()
    frappe.clear_cache(doctype="Sales Invoice")
    result = verify()
    result.update({"field_results": field_results, "added_status_options": added_options})
    print("Delivery partial return workflow V2.21 installed successfully.")
    return result


@frappe.whitelist()
def verify():
    invoice_meta = frappe.get_meta("Sales Invoice")
    missing_fields = [fieldname for fieldname in SALES_INVOICE_FIELDS if not invoice_meta.has_field(fieldname)]
    status_field = invoice_meta.get_field("custom_delivery_return_status")
    status_options = [line.strip() for line in str(status_field.options or "").splitlines() if line.strip()] if status_field else []
    missing_options = [option for option in RETURN_STATUS_OPTIONS if option not in status_options]
    missing_doctypes = [name for name in DOCTYPE_SPECS if not frappe.db.exists("DocType", name)]
    return {
        "version": VERSION,
        "missing_doctypes": missing_doctypes,
        "missing_fields": missing_fields,
        "missing_return_status_options": missing_options,
        "ready": not missing_doctypes and not missing_fields and not missing_options,
    }


@frappe.whitelist()
def repair_existing(invoice_name, credit_note_name):
    frappe.only_for("System Manager")
    from pharma_erp.pharma_erp.delivery_partial_return import repair_existing_partial_return
    result = repair_existing_partial_return(invoice_name, credit_note_name)
    frappe.db.commit()
    return result


@frappe.whitelist()
def verify_invoice(invoice_name):
    source = frappe.get_doc("Sales Invoice", invoice_name)
    request_name = source.get("custom_last_delivery_return_request") or source.get("custom_active_delivery_return_request") or ""
    request = frappe.get_doc("Delivery Return Request", request_name) if request_name and frappe.db.exists("Delivery Return Request", request_name) else None
    return {
        "invoice_name": source.name,
        "delivery_status": source.get("custom_delivery_status") or "",
        "return_type": source.get("custom_delivery_return_type") or "",
        "return_status": source.get("custom_delivery_return_status") or "",
        "outstanding_amount": source.outstanding_amount,
        "request": request.name if request else "",
        "request_status": request.status if request else "",
        "credit_note": request.credit_note if request else "",
        "ready": bool(request and request.status in {"Partial Return Completed", "Full Return Completed"}),
    }
