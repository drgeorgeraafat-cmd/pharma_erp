import frappe


VERSION = "2.27"
DOCTYPE = "Sales Invoice"
FIELDNAME = "custom_driver_collection_proof"


def _upsert_custom_field():
    values = {
        "dt": DOCTYPE,
        "label": "Driver Collection Proof",
        "fieldname": FIELDNAME,
        "fieldtype": "Attach Image",
        "insert_after": "custom_driver_collection_reference",
        "read_only": 1,
        "allow_on_submit": 1,
        "no_copy": 1,
        "description": (
            "Photo of the customer transfer or payment receipt captured by the delivery driver."
        ),
    }

    name = frappe.db.get_value(
        "Custom Field",
        {"dt": DOCTYPE, "fieldname": FIELDNAME},
        "name",
    )
    if name:
        doc = frappe.get_doc("Custom Field", name)
        for key, value in values.items():
            doc.set(key, value)
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        return "updated"

    doc = frappe.get_doc({"doctype": "Custom Field", **values})
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return "created"


@frappe.whitelist()
def install():
    frappe.only_for("System Manager")
    field_result = _upsert_custom_field()
    frappe.db.commit()
    frappe.clear_cache(doctype=DOCTYPE)

    result = verify()
    result["field_result"] = field_result
    print("Delivery collection proof V2.27 installed successfully.")
    return result


@frappe.whitelist()
def verify():
    meta = frappe.get_meta(DOCTYPE)
    return {
        "version": VERSION,
        "ready": bool(meta.has_field(FIELDNAME)),
        "fieldname": FIELDNAME,
    }
