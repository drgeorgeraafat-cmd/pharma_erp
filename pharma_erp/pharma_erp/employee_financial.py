import frappe


@frappe.whitelist()
def get_current_open_shift():
    """Return the most relevant currently open pharmacy shift."""
    fields = ["name", "owner", "creation"]
    meta = frappe.get_meta("Pharmacy Shift Closing")

    for fieldname in ("cashier", "status", "start_time", "end_time"):
        if meta.has_field(fieldname):
            fields.append(fieldname)

    rows = frappe.get_all(
        "Pharmacy Shift Closing",
        filters={"docstatus": 0},
        fields=fields,
        order_by="creation desc",
        limit_page_length=50,
    )

    open_rows = [
        row
        for row in rows
        if row.get("status") != "Closed" and not row.get("end_time")
    ]

    if not open_rows:
        return None

    current_user = frappe.session.user
    for row in open_rows:
        if row.get("cashier") == current_user or row.get("owner") == current_user:
            return row

    return open_rows[0]
