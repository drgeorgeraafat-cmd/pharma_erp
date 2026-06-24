import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, time_diff_in_seconds


ATTEMPT_DOCTYPE = "Delivery Attempt"
ADD_ON_PARENT_FIELD = "custom_parent_delivery_invoice"
ADD_ON_CHECK_FIELD = "custom_add_on_delivery_invoice"
CURRENT_ATTEMPT_FIELD = "custom_current_delivery_attempt"
ATTEMPT_COUNT_FIELD = "custom_delivery_attempt_count"
ADD_ON_STATUS_FIELD = "custom_add_on_order_status"
ADD_ON_REQUESTED_FIELD = "custom_add_on_requested"
ADD_ON_REQUESTED_AT_FIELD = "custom_add_on_requested_at"
ADD_ON_NOTES_FIELD = "custom_add_on_request_notes"
DELIVERY_ISSUE_FIELD = "custom_delivery_issue"
DELIVERY_ISSUE_REASON_FIELD = "custom_delivery_issue_reason"


BLOCKED_DEPARTURE_ADD_ON_STATUSES = {
    "Requested",
    "Driver Returning",
    "Returned to Pharmacy",
    "Add-on Invoice Created",
}


def sales_invoice_has(fieldname):
    return bool(frappe.get_meta("Sales Invoice").has_field(fieldname))


def attempt_doctype_exists():
    return bool(frappe.db.exists("DocType", ATTEMPT_DOCTYPE))


def attempt_has(fieldname):
    return attempt_doctype_exists() and bool(
        frappe.get_meta(ATTEMPT_DOCTYPE).has_field(fieldname)
    )


def set_invoice_value(doc, fieldname, value):
    if sales_invoice_has(fieldname):
        doc.set(fieldname, value)


def set_attempt_value(doc, fieldname, value):
    if attempt_has(fieldname):
        doc.set(fieldname, value)


def _add_on_invoice_names(parent_name, submitted_only=True):
    if not parent_name or not sales_invoice_has(ADD_ON_PARENT_FIELD):
        return []

    filters = {
        ADD_ON_PARENT_FIELD: parent_name,
        "is_return": 0,
    }
    if submitted_only:
        filters["docstatus"] = 1
    else:
        filters["docstatus"] = ["in", [0, 1]]

    return frappe.get_all(
        "Sales Invoice",
        filters=filters,
        pluck="name",
        order_by="creation asc",
        limit_page_length=500,
    )


def delivery_group_invoice_names(parent_name):
    return [parent_name] + _add_on_invoice_names(parent_name, submitted_only=True)


def delivery_group_snapshot(parent_invoice):
    names = delivery_group_invoice_names(parent_invoice.name)
    rows = frappe.get_all(
        "Sales Invoice",
        filters={"name": ["in", names], "docstatus": 1},
        fields=["name", "grand_total", "outstanding_amount"],
        limit_page_length=500,
    )

    grand_total = flt(sum(flt(row.grand_total) for row in rows), 6)
    outstanding = flt(sum(flt(row.outstanding_amount) for row in rows), 6)

    item_count = 0
    if names:
        item_count = cint(
            frappe.db.sql(
                """
                SELECT COUNT(*)
                FROM `tabSales Invoice Item`
                WHERE parenttype = 'Sales Invoice'
                  AND parent IN %(parents)s
                  AND IFNULL(qty, 0) != 0
                """,
                {"parents": tuple(names)},
            )[0][0]
        )

    prepaid_amount = 0
    if sales_invoice_has("custom_prepaid_amount"):
        for name in names:
            status = (
                frappe.db.get_value(
                    "Sales Invoice",
                    name,
                    "custom_prepaid_verification_status",
                )
                if sales_invoice_has("custom_prepaid_verification_status")
                else ""
            )
            if not status or status == "Confirmed":
                prepaid_amount += flt(
                    frappe.db.get_value(
                        "Sales Invoice",
                        name,
                        "custom_prepaid_amount",
                    )
                    or 0
                )

    return frappe._dict(
        {
            "invoice_names": names,
            "grand_total": grand_total,
            "outstanding_amount": outstanding,
            "prepaid_amount": flt(prepaid_amount, 6),
            "item_count": item_count,
        }
    )


def _employee_data(employee_name):
    if not employee_name:
        return frappe._dict()
    return frappe.db.get_value(
        "Employee",
        employee_name,
        ["name", "employee_name", "user_id"],
        as_dict=True,
    ) or frappe._dict()


def _attempt_number(parent_invoice):
    stored = cint(parent_invoice.get(ATTEMPT_COUNT_FIELD)) if sales_invoice_has(ATTEMPT_COUNT_FIELD) else 0
    latest = 0
    if attempt_doctype_exists() and attempt_has("parent_delivery_invoice"):
        rows = frappe.get_all(
            ATTEMPT_DOCTYPE,
            filters={"parent_delivery_invoice": parent_invoice.name},
            fields=["attempt_number"],
            order_by="attempt_number desc, creation desc",
            limit_page_length=1,
        )
        latest = cint(rows[0].attempt_number) if rows else 0
    return max(stored, latest) + 1


def _latest_attempt_name(parent_name):
    if not attempt_doctype_exists() or not attempt_has("parent_delivery_invoice"):
        return ""

    rows = frappe.get_all(
        ATTEMPT_DOCTYPE,
        filters={"parent_delivery_invoice": parent_name},
        fields=["name", "attempt_number", "creation"],
        order_by="attempt_number desc, creation desc",
        limit_page_length=1,
    )
    return rows[0].name if rows else ""


def get_current_attempt(parent_invoice):
    if not attempt_doctype_exists():
        return None

    attempt_name = ""
    if sales_invoice_has(CURRENT_ATTEMPT_FIELD):
        attempt_name = parent_invoice.get(CURRENT_ATTEMPT_FIELD) or ""
        if attempt_name and frappe.db.exists(ATTEMPT_DOCTYPE, attempt_name):
            return frappe.get_doc(ATTEMPT_DOCTYPE, attempt_name)

    if attempt_has("parent_delivery_invoice") and attempt_has("is_current_attempt"):
        rows = frappe.get_all(
            ATTEMPT_DOCTYPE,
            filters={
                "parent_delivery_invoice": parent_invoice.name,
                "is_current_attempt": 1,
            },
            fields=["name"],
            order_by="attempt_number desc, creation desc",
            limit_page_length=1,
        )
        attempt_name = rows[0].name if rows else ""
        if attempt_name:
            return frappe.get_doc(ATTEMPT_DOCTYPE, attempt_name)

    return None


def can_depart(parent_invoice):
    add_on_status = (
        parent_invoice.get(ADD_ON_STATUS_FIELD)
        if sales_invoice_has(ADD_ON_STATUS_FIELD)
        else ""
    ) or ""
    if add_on_status in BLOCKED_DEPARTURE_ADD_ON_STATUSES:
        return False

    prepaid_status = (
        parent_invoice.get("custom_prepaid_verification_status")
        if sales_invoice_has("custom_prepaid_verification_status")
        else ""
    ) or ""
    return prepaid_status != "Awaiting Confirmation"


def _attempt_type(parent_invoice, attempt_number):
    if attempt_number <= 1:
        return "Initial Delivery"

    add_on_status = (
        parent_invoice.get(ADD_ON_STATUS_FIELD)
        if sales_invoice_has(ADD_ON_STATUS_FIELD)
        else ""
    ) or ""

    # An order may continue to have submitted Add-on invoices for its whole
    # lifetime.  Their mere existence must not classify every later retry as
    # "Redelivery After Add-on".  Only the attempt immediately following the
    # physical return-for-add-on cycle gets that type; later customer-return
    # retries are Manager Retry.
    latest_attempt_name = _latest_attempt_name(parent_invoice.name)
    latest_outcome = ""
    if latest_attempt_name and frappe.db.exists(ATTEMPT_DOCTYPE, latest_attempt_name):
        latest_outcome = str(
            frappe.db.get_value(
                ATTEMPT_DOCTYPE,
                latest_attempt_name,
                "attempt_outcome",
            )
            or ""
        ).strip()

    if (
        add_on_status
        in {
            "Ready for Redelivery",
            "Add-on Invoice Created",
            "Returned to Pharmacy",
        }
        and latest_outcome == "Returned for Add-on"
    ):
        return "Redelivery After Add-on"

    return "Manager Retry"


def start_delivery_attempt(
    parent_invoice,
    delivery_user=None,
    delivery_trip=None,
    delivery_trip_stop_row=None,
    trip_stop_sequence=None,
):
    if not can_depart(parent_invoice):
        frappe.throw(
            _(
                "لا يمكن خروج الأوردر الآن. راجع حالة الإضافة أو الدفع المسبق المعلّق أولًا."
            )
        )

    current = get_current_attempt(parent_invoice)
    if current:
        frappe.throw(
            _("توجد بالفعل محاولة توصيل مفتوحة لهذا الأوردر: {0}").format(
                current.name
            )
        )

    now = now_datetime()
    employee = _employee_data(parent_invoice.get("custom_delivery_boy"))
    snapshot = delivery_group_snapshot(parent_invoice)
    attempt_number = _attempt_number(parent_invoice)
    previous_attempt = _latest_attempt_name(parent_invoice.name)

    attempt = None
    if attempt_doctype_exists():
        attempt = frappe.new_doc(ATTEMPT_DOCTYPE)
        set_attempt_value(attempt, "parent_delivery_invoice", parent_invoice.name)
        set_attempt_value(attempt, "company", parent_invoice.company)
        set_attempt_value(attempt, "customer", parent_invoice.customer)
        set_attempt_value(
            attempt,
            "customer_address",
            parent_invoice.customer_address
            or parent_invoice.shipping_address_name
            or "",
        )
        set_attempt_value(
            attempt,
            "delivery_zone",
            parent_invoice.get("custom_delivery_zone") or "",
        )
        set_attempt_value(attempt, "attempt_number", attempt_number)
        set_attempt_value(
            attempt,
            "attempt_type",
            _attempt_type(parent_invoice, attempt_number),
        )
        set_attempt_value(
            attempt,
            "delivery_boy",
            parent_invoice.get("custom_delivery_boy") or "",
        )
        set_attempt_value(
            attempt,
            "delivery_user",
            employee.get("user_id") or delivery_user or frappe.session.user,
        )
        set_attempt_value(attempt, "attempt_status", "Out for Delivery")
        set_attempt_value(attempt, "is_current_attempt", 1)
        set_attempt_value(attempt, "previous_attempt", previous_attempt)
        set_attempt_value(attempt, "departure_time", now)
        set_attempt_value(attempt, "attempt_outcome", "Pending")
        set_attempt_value(
            attempt,
            "order_amount_at_departure",
            snapshot.grand_total,
        )
        set_attempt_value(
            attempt,
            "prepaid_amount_at_departure",
            snapshot.prepaid_amount,
        )
        set_attempt_value(
            attempt,
            "expected_collection_at_departure",
            snapshot.outstanding_amount,
        )
        set_attempt_value(
            attempt,
            "item_count_at_departure",
            snapshot.item_count,
        )
        set_attempt_value(attempt, "delivery_trip", delivery_trip or "")
        set_attempt_value(
            attempt,
            "delivery_trip_stop_row",
            delivery_trip_stop_row or "",
        )
        set_attempt_value(
            attempt,
            "trip_stop_sequence",
            trip_stop_sequence or 0,
        )
        attempt.insert(ignore_permissions=True)

    set_invoice_value(parent_invoice, CURRENT_ATTEMPT_FIELD, attempt.name if attempt else "")
    set_invoice_value(parent_invoice, ATTEMPT_COUNT_FIELD, attempt_number)
    set_invoice_value(parent_invoice, "custom_departure_time", now)
    set_invoice_value(parent_invoice, "custom_delivery_time", None)
    set_invoice_value(parent_invoice, "custom_duration_in_mins", 0)
    parent_invoice.custom_delivery_status = "Out for Delivery"

    return attempt


def _duration_minutes(start, end):
    if not start or not end:
        return 0
    return round(max(0, time_diff_in_seconds(get_datetime(end), get_datetime(start))) / 60, 2)


def complete_delivery_attempt(parent_invoice):
    now = now_datetime()
    attempt = get_current_attempt(parent_invoice)

    if not attempt and attempt_doctype_exists():
        # Compatibility for an order that was already outside before this feature was installed.
        attempt = start_delivery_attempt(parent_invoice)

    duration = _duration_minutes(
        attempt.get("departure_time") if attempt else parent_invoice.get("custom_departure_time"),
        now,
    )

    if attempt:
        set_attempt_value(attempt, "attempt_status", "Delivered")
        set_attempt_value(attempt, "attempt_outcome", "Delivered")
        set_attempt_value(attempt, "delivered_at", now)
        set_attempt_value(attempt, "closed_at", now)
        set_attempt_value(attempt, "delivery_duration_mins", duration)
        set_attempt_value(attempt, "total_attempt_duration_mins", duration)
        set_attempt_value(attempt, "is_current_attempt", 0)
        attempt.save(ignore_permissions=True)

    set_invoice_value(parent_invoice, CURRENT_ATTEMPT_FIELD, "")
    set_invoice_value(parent_invoice, "custom_delivery_time", now)
    set_invoice_value(parent_invoice, "custom_duration_in_mins", duration)
    if sales_invoice_has(ADD_ON_STATUS_FIELD):
        current_status = parent_invoice.get(ADD_ON_STATUS_FIELD) or ""
        if current_status and current_status != "Not Required":
            parent_invoice.set(ADD_ON_STATUS_FIELD, "Completed")
    parent_invoice.custom_delivery_status = "Delivered"

    return duration


def request_add_on_return(parent_invoice, notes, delivery_user=None):
    notes = (notes or "").strip()
    if not notes:
        frappe.throw(_("اكتب الأصناف الإضافية التي طلبها العميل."))

    if (parent_invoice.custom_delivery_status or "") != "Out for Delivery":
        frappe.throw(_("يمكن طلب الإضافة فقط أثناء خروج الأوردر للتوصيل."))

    attempt = get_current_attempt(parent_invoice)
    if not attempt:
        # Compatibility for old outside orders.
        attempt = start_delivery_attempt(parent_invoice, delivery_user=delivery_user)

    now = now_datetime()
    set_attempt_value(attempt, "attempt_status", "Returning to Pharmacy")
    set_attempt_value(attempt, "attempt_outcome", "Pending")
    set_attempt_value(
        attempt,
        "delivery_issue",
        "Customer Requested Additional Items",
    )
    set_attempt_value(attempt, "issue_reason", notes)
    set_attempt_value(attempt, "add_on_requested", 1)
    set_attempt_value(attempt, "add_on_request_notes", notes)
    set_attempt_value(attempt, "return_started_at", now)
    attempt.save(ignore_permissions=True)

    set_invoice_value(parent_invoice, ADD_ON_REQUESTED_FIELD, 1)
    set_invoice_value(parent_invoice, ADD_ON_REQUESTED_AT_FIELD, now)
    set_invoice_value(parent_invoice, ADD_ON_NOTES_FIELD, notes)
    set_invoice_value(parent_invoice, ADD_ON_STATUS_FIELD, "Driver Returning")
    set_invoice_value(
        parent_invoice,
        DELIVERY_ISSUE_FIELD,
        "Customer Requested Additional Items",
    )
    set_invoice_value(parent_invoice, DELIVERY_ISSUE_REASON_FIELD, notes)

    return attempt


def cancel_add_on_request(parent_invoice, reason=None, actor=None):
    """Cancel an active add-on return flow without creating an add-on invoice.

    If the driver is still on the road, the current attempt resumes as Out for
    Delivery. If the driver already reached the pharmacy, the closed attempt is
    preserved and the order becomes Ready for Delivery for a new Manager Retry.
    """
    if isinstance(parent_invoice, str):
        parent_invoice = frappe.get_doc("Sales Invoice", parent_invoice)

    add_on_status = (
        parent_invoice.get(ADD_ON_STATUS_FIELD)
        if sales_invoice_has(ADD_ON_STATUS_FIELD)
        else ""
    ) or ""
    if add_on_status not in {"Driver Returning", "Returned to Pharmacy"}:
        frappe.throw(_("لا يوجد طلب إضافة جارٍ يمكن إلغاؤه لهذا الأوردر."))

    reason = str(reason or "").strip()
    actor = str(actor or frappe.session.user or "").strip()
    previous_notes = (
        parent_invoice.get(ADD_ON_NOTES_FIELD)
        if sales_invoice_has(ADD_ON_NOTES_FIELD)
        else ""
    ) or ""

    attempt_name = ""
    mode = "ready_for_redelivery"
    if add_on_status == "Driver Returning":
        attempt = get_current_attempt(parent_invoice)
        if not attempt:
            frappe.throw(_("لم يتم العثور على محاولة التوصيل الحالية لاستكمال الأوردر."))

        attempt_name = attempt.name
        mode = "continue_current_attempt"
        set_attempt_value(attempt, "attempt_status", "Out for Delivery")
        set_attempt_value(attempt, "attempt_outcome", "Pending")
        set_attempt_value(attempt, "delivery_issue", "None")
        set_attempt_value(attempt, "issue_reason", "")
        set_attempt_value(attempt, "add_on_requested", 0)
        set_attempt_value(attempt, "add_on_request_notes", "")
        set_attempt_value(attempt, "return_started_at", None)
        audit_note = _("تم إلغاء طلب الإضافة واستكمال نفس محاولة التوصيل بواسطة {0}.").format(
            actor or _("مدير الشيفت")
        )
        if reason:
            audit_note += " " + _("السبب: {0}").format(reason)
        if previous_notes:
            audit_note += " " + _("طلب الإضافة الملغى: {0}").format(previous_notes)
        existing_notes = str(attempt.get("notes") or "").strip()
        set_attempt_value(
            attempt,
            "notes",
            "\n".join(value for value in (existing_notes, audit_note) if value),
        )
        attempt.save(ignore_permissions=True)
        parent_invoice.custom_delivery_status = "Out for Delivery"
    else:
        parent_invoice.custom_delivery_status = (
            "Ready for Delivery"
            if parent_invoice.get("custom_delivery_boy")
            else "Draft"
        )

    set_invoice_value(parent_invoice, ADD_ON_REQUESTED_FIELD, 0)
    set_invoice_value(parent_invoice, ADD_ON_REQUESTED_AT_FIELD, None)
    set_invoice_value(parent_invoice, ADD_ON_NOTES_FIELD, "")
    set_invoice_value(parent_invoice, ADD_ON_STATUS_FIELD, "Not Required")
    set_invoice_value(parent_invoice, DELIVERY_ISSUE_FIELD, "None")
    set_invoice_value(parent_invoice, DELIVERY_ISSUE_REASON_FIELD, "")

    comment = _("تم إلغاء طلب إضافة الأصناف.")
    if reason:
        comment += " " + _("السبب: {0}.").format(reason)
    if previous_notes:
        comment += " " + _("الطلب الملغى: {0}.").format(previous_notes)
    if mode == "continue_current_attempt":
        comment += " " + _("استمر الطيار في نفس محاولة التوصيل.")
    else:
        comment += " " + _("أصبح الأوردر جاهزًا للخروج مرة أخرى بدون فاتورة إضافة.")
    parent_invoice.add_comment("Comment", comment)

    return frappe._dict(
        {
            "mode": mode,
            "delivery_status": parent_invoice.get("custom_delivery_status") or "",
            "add_on_status": parent_invoice.get(ADD_ON_STATUS_FIELD) or "",
            "delivery_attempt": attempt_name,
        }
    )


def finish_return_to_pharmacy(parent_invoice):
    add_on_status = (
        parent_invoice.get(ADD_ON_STATUS_FIELD)
        if sales_invoice_has(ADD_ON_STATUS_FIELD)
        else ""
    ) or ""
    if add_on_status != "Driver Returning":
        frappe.throw(_("الأوردر غير مسجل حاليًا كراجع للصيدلية."))

    attempt = get_current_attempt(parent_invoice)
    if not attempt:
        frappe.throw(_("لم يتم العثور على محاولة التوصيل الحالية."))

    now = now_datetime()
    return_duration = _duration_minutes(attempt.get("return_started_at"), now)
    total_duration = _duration_minutes(attempt.get("departure_time"), now)

    set_attempt_value(attempt, "attempt_status", "Returned to Pharmacy")
    set_attempt_value(attempt, "attempt_outcome", "Returned for Add-on")
    set_attempt_value(attempt, "returned_to_pharmacy_at", now)
    set_attempt_value(attempt, "closed_at", now)
    set_attempt_value(attempt, "return_duration_mins", return_duration)
    set_attempt_value(attempt, "total_attempt_duration_mins", total_duration)
    set_attempt_value(attempt, "is_current_attempt", 0)
    attempt.save(ignore_permissions=True)

    set_invoice_value(parent_invoice, CURRENT_ATTEMPT_FIELD, "")
    set_invoice_value(parent_invoice, ADD_ON_STATUS_FIELD, "Returned to Pharmacy")
    parent_invoice.custom_delivery_status = "Ready for Delivery"

    return frappe._dict(
        {
            "attempt": attempt.name,
            "return_duration_mins": return_duration,
            "total_attempt_duration_mins": total_duration,
        }
    )


def mark_add_on_invoice_created(parent_invoice, add_on_invoice_name):
    if isinstance(parent_invoice, str):
        parent_invoice = frappe.get_doc("Sales Invoice", parent_invoice)

    set_invoice_value(parent_invoice, ADD_ON_REQUESTED_FIELD, 0)
    set_invoice_value(parent_invoice, ADD_ON_STATUS_FIELD, "Ready for Redelivery")
    parent_invoice.custom_delivery_status = (
        "Ready for Delivery"
        if parent_invoice.get("custom_delivery_boy")
        else "Draft"
    )
    parent_invoice.save(ignore_permissions=True)

    if attempt_doctype_exists() and attempt_has("parent_delivery_invoice"):
        filters = {
            "parent_delivery_invoice": parent_invoice.name,
        }
        rows = frappe.get_all(
            ATTEMPT_DOCTYPE,
            filters=filters,
            fields=["name", "attempt_number", "creation", "attempt_outcome", "add_on_invoice"],
            order_by="attempt_number desc, creation desc",
            limit_page_length=20,
        )
        for row in rows:
            if row.get("attempt_outcome") == "Returned for Add-on" and not row.get("add_on_invoice"):
                attempt = frappe.get_doc(ATTEMPT_DOCTYPE, row.name)
                set_attempt_value(attempt, "add_on_invoice", add_on_invoice_name)
                attempt.save(ignore_permissions=True)
                break


def sync_delivery_group(parent_invoice, status, departure_time=None, delivery_time=None, duration=None):
    add_on_names = _add_on_invoice_names(parent_invoice.name, submitted_only=True)
    if not add_on_names:
        return

    for name in add_on_names:
        values = {}
        if sales_invoice_has("custom_delivery_status"):
            values["custom_delivery_status"] = status
        if sales_invoice_has("custom_delivery_boy"):
            values["custom_delivery_boy"] = parent_invoice.get("custom_delivery_boy") or ""
        if departure_time is not None and sales_invoice_has("custom_departure_time"):
            values["custom_departure_time"] = departure_time
        if delivery_time is not None and sales_invoice_has("custom_delivery_time"):
            values["custom_delivery_time"] = delivery_time
        if duration is not None and sales_invoice_has("custom_duration_in_mins"):
            values["custom_duration_in_mins"] = duration
        if values:
            frappe.db.set_value(
                "Sales Invoice",
                name,
                values,
                update_modified=False,
            )
