import frappe
from frappe import _


VERSION = "2.18"

SALES_INVOICE_FIELDS = {
    "custom_driver_return_status": {
        "label": "Driver Return Status",
        "fieldtype": "Select",
        "options": "Not Required\nOut With Driver\nReturning to Pharmacy\nReturned to Pharmacy",
        "default": "Not Required",
        "allow_on_submit": 1,
        "read_only": 1,
        "hidden": 1,
        "insert_after": "custom_delivery_status",
    },
    "custom_driver_returned_at": {
        "label": "Driver Returned At",
        "fieldtype": "Datetime",
        "allow_on_submit": 1,
        "read_only": 1,
        "hidden": 1,
        "insert_after": "custom_driver_return_status",
    },
    "custom_delivery_return_status": {
        "label": "Delivery Return Status",
        "fieldtype": "Select",
        "options": "Not Required\nReturning to Pharmacy\nAwaiting Manager Review\nCredit Note Draft\nReturn Completed",
        "default": "Not Required",
        "allow_on_submit": 1,
        "read_only": 1,
        "hidden": 1,
        "insert_after": "custom_driver_returned_at",
    },
    "custom_delivery_return_reason": {
        "label": "Delivery Return Reason",
        "fieldtype": "Select",
        "options": "Customer Cancelled Order\nCustomer Refused Order\nCustomer Not Answering\nWrong Address\nPayment Problem\nOther",
        "allow_on_submit": 1,
        "read_only": 1,
        "hidden": 1,
        "insert_after": "custom_delivery_return_status",
    },
    "custom_delivery_return_notes": {
        "label": "Delivery Return Notes",
        "fieldtype": "Small Text",
        "allow_on_submit": 1,
        "read_only": 1,
        "hidden": 1,
        "insert_after": "custom_delivery_return_reason",
    },
    "custom_delivery_return_reviewed_by": {
        "label": "Delivery Return Reviewed By",
        "fieldtype": "Link",
        "options": "User",
        "allow_on_submit": 1,
        "read_only": 1,
        "hidden": 1,
        "insert_after": "custom_delivery_return_notes",
    },
    "custom_delivery_return_reviewed_at": {
        "label": "Delivery Return Reviewed At",
        "fieldtype": "Datetime",
        "allow_on_submit": 1,
        "read_only": 1,
        "hidden": 1,
        "insert_after": "custom_delivery_return_reviewed_by",
    },
    "custom_delivery_return_credit_note": {
        "label": "Delivery Return Credit Note",
        "fieldtype": "Link",
        "options": "Sales Invoice",
        "allow_on_submit": 1,
        "read_only": 1,
        "hidden": 1,
        "insert_after": "custom_delivery_return_reviewed_at",
    },
}

DELIVERY_STATUS_OPTIONS = [
    "Returning to Pharmacy",
    "Returned to Pharmacy",
    "Cancelled",
]


def _custom_field(dt, fieldname, values):
    name = frappe.db.get_value(
        "Custom Field",
        {"dt": dt, "fieldname": fieldname},
        "name",
    )
    if name:
        doc = frappe.get_doc("Custom Field", name)
        for key, value in values.items():
            doc.set(key, value)
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        return {"action": "updated", "name": doc.name}

    if frappe.get_meta(dt).has_field(fieldname):
        return {"action": "existing", "name": f"{dt}.{fieldname}"}

    doc = frappe.new_doc("Custom Field")
    doc.dt = dt
    doc.fieldname = fieldname
    for key, value in values.items():
        doc.set(key, value)
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return {"action": "created", "name": doc.name}


def _append_select_options(dt, fieldname, options):
    custom_field_name = frappe.db.get_value(
        "Custom Field",
        {"dt": dt, "fieldname": fieldname},
        "name",
    )
    if not custom_field_name:
        if not frappe.get_meta(dt).has_field(fieldname):
            frappe.throw(_("الحقل {0}.{1} غير موجود.").format(dt, fieldname))
        # Standard fields are not expected here, but keep the installer safe.
        return {"action": "existing_doctype_field", "name": f"{dt}.{fieldname}"}

    doc = frappe.get_doc("Custom Field", custom_field_name)
    current = [line.strip() for line in str(doc.options or "").splitlines() if line.strip()]
    changed = False
    for option in options:
        if option not in current:
            current.append(option)
            changed = True
    if changed:
        doc.options = "\n".join(current)
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
    return {"action": "updated_options" if changed else "options_ok", "name": doc.name}


def _backfill_active_orders():
    meta = frappe.get_meta("Sales Invoice")
    if not meta.has_field("custom_driver_return_status"):
        return {"updated": 0}

    rows = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            "custom_order_type": "Home Delivery",
            "custom_delivery_status": ["in", ["Out for Delivery", "Returning to Pharmacy", "Returned to Pharmacy"]],
        },
        fields=["name", "custom_delivery_status", "custom_driver_return_status"],
        limit_page_length=5000,
    )
    updated = 0
    mapping = {
        "Out for Delivery": "Out With Driver",
        "Returning to Pharmacy": "Returning to Pharmacy",
        "Returned to Pharmacy": "Returned to Pharmacy",
    }
    for row in rows:
        target = mapping.get(row.custom_delivery_status)
        if target and row.custom_driver_return_status != target:
            frappe.db.set_value(
                "Sales Invoice",
                row.name,
                "custom_driver_return_status",
                target,
                update_modified=False,
            )
            updated += 1
    return {"updated": updated}


@frappe.whitelist()
def install():
    frappe.only_for("System Manager")
    result = {
        "version": VERSION,
        "fields": [],
        "delivery_status_options": None,
        "backfill": None,
    }
    result["delivery_status_options"] = _append_select_options(
        "Sales Invoice",
        "custom_delivery_status",
        DELIVERY_STATUS_OPTIONS,
    )
    for fieldname, values in SALES_INVOICE_FIELDS.items():
        result["fields"].append(_custom_field("Sales Invoice", fieldname, values))
    frappe.clear_cache(doctype="Sales Invoice")
    result["backfill"] = _backfill_active_orders()
    frappe.db.commit()
    result["verify"] = verify()
    print("Delivery return and driver return workflow V2.18 installed successfully.")
    return result


@frappe.whitelist()
def verify():
    meta = frappe.get_meta("Sales Invoice")
    missing = [fieldname for fieldname in SALES_INVOICE_FIELDS if not meta.has_field(fieldname)]
    status_field = meta.get_field("custom_delivery_status")
    status_options = [line.strip() for line in str(status_field.options or "").splitlines() if line.strip()] if status_field else []
    missing_status_options = [option for option in DELIVERY_STATUS_OPTIONS if option not in status_options]
    return {
        "version": VERSION,
        "missing_fields": missing,
        "missing_delivery_status_options": missing_status_options,
        "ready": not missing and not missing_status_options,
    }
