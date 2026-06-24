import frappe
from frappe import _
from frappe.model.naming import make_autoname


def set_customer_code(doc, method=None):
    """Generate a unique numeric Customer Code before inserting Customer."""

    # لا نغيّر الكود لو موجود بالفعل
    if doc.get("custom_customer_code"):
        return

    # نستخدم Prefix داخلي فقط لفصل عداد العملاء عن عداد الأصناف
    # لكن الذي يُحفظ في Customer يكون أرقامًا فقط
    for _ in range(100):
        generated_code = make_autoname(
            "CUST-.######",
            doc=doc
        )

        customer_code = generated_code.replace(
            "CUST-",
            "",
            1
        )

        if not frappe.db.exists(
            "Customer",
            {"custom_customer_code": customer_code}
        ):
            doc.custom_customer_code = customer_code
            return

    frappe.throw(
        _("Unable to generate a unique Customer Code.")
    )
