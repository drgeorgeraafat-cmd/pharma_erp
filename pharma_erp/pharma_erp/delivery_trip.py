import json

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, nowdate, time_diff_in_seconds

from pharma_erp.pharma_erp.delivery_attempt import (
    ADD_ON_NOTES_FIELD,
    ADD_ON_STATUS_FIELD,
    ATTEMPT_COUNT_FIELD,
    CURRENT_ATTEMPT_FIELD,
    can_depart,
    delivery_group_invoice_names,
    delivery_group_snapshot,
    finish_return_to_pharmacy,
    get_current_attempt,
    sales_invoice_has,
    start_delivery_attempt,
    sync_delivery_group,
)


TRIP_DOCTYPE = "Delivery Trip"
STOP_DOCTYPE = "Delivery Stop"
SHIFT_DOCTYPE = "Pharmacy Shift Closing"

TRIP_FIELD = "custom_delivery_trip"
TRIP_STOP_ROW_FIELD = "custom_delivery_trip_stop_row"
TRIP_STOP_SEQUENCE_FIELD = "custom_delivery_trip_stop_sequence"

ACTIVE_TRIP_STATUSES = {
    "Ready",
    "Out for Delivery",
    "Partially Delivered",
    "Returning to Pharmacy",
}
FINAL_STOP_STATUSES = {
    "Delivered",
    "Returned to Pharmacy",
    "Failed",
    "Cancelled",
}
RETURNABLE_STOP_STATUSES = FINAL_STOP_STATUSES | {"Returning for Add-on"}


def _trip_has(fieldname):
    return bool(frappe.get_meta(TRIP_DOCTYPE).has_field(fieldname))


def _stop_has(fieldname):
    return bool(frappe.get_meta(STOP_DOCTYPE).has_field(fieldname))


def _set_if_has(doc, fieldname, value):
    if doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


def _duration_minutes(start, end):
    if not start or not end:
        return 0
    seconds = max(0, time_diff_in_seconds(get_datetime(end), get_datetime(start)))
    return round(seconds / 60, 2)


def _parse_invoice_names(invoice_names):
    if isinstance(invoice_names, str):
        try:
            invoice_names = json.loads(invoice_names)
        except Exception:
            invoice_names = [name.strip() for name in invoice_names.split(",") if name.strip()]

    names = []
    for name in invoice_names or []:
        name = str(name or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _get_default_value(doctype, fieldname, fallback=None):
    field = frappe.get_meta(doctype).get_field(fieldname)
    value = field.default if field else None
    return value or fallback


def _normalise_status(value):
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ")


def get_current_open_shift(company=None):
    """Return the current open Pharmacy Shift Closing record.

    The custom DocType can differ between installations, so the lookup uses
    common status, company, date, user and closing-time field names. Draft
    records are treated as open. Submitted records are accepted only when
    their status explicitly means open/active/in progress.
    """
    if not frappe.db.exists("DocType", SHIFT_DOCTYPE):
        return ""

    meta = frappe.get_meta(SHIFT_DOCTYPE)
    status_fields = [
        name for name in (
            "status",
            "shift_status",
            "custom_status",
            "closing_status",
            "workflow_state",
        )
        if meta.has_field(name)
    ]
    company_fields = [
        name for name in ("company", "custom_company") if meta.has_field(name)
    ]
    date_fields = [
        name for name in (
            "posting_date",
            "shift_date",
            "date",
            "opening_date",
            "start_date",
        )
        if meta.has_field(name)
    ]
    user_fields = [
        name for name in (
            "user",
            "cashier",
            "opened_by",
            "opening_user",
            "shift_user",
        )
        if meta.has_field(name)
    ]
    close_fields = [
        name for name in (
            "closed_at",
            "closing_time",
            "closing_datetime",
            "end_time",
            "shift_end",
            "shift_end_time",
        )
        if meta.has_field(name)
    ]

    fields = ["name", "docstatus", "creation", "modified", "owner"]
    for fieldname in status_fields + company_fields + date_fields + user_fields + close_fields:
        if fieldname not in fields:
            fields.append(fieldname)

    rows = frappe.get_all(
        SHIFT_DOCTYPE,
        filters={"docstatus": ["<", 2]},
        fields=fields,
        order_by="creation desc",
        limit_page_length=100,
    )

    open_values = {
        "open",
        "opened",
        "active",
        "in progress",
        "ongoing",
        "running",
        "draft",
        "shift open",
        "مفتوح",
        "نشط",
        "جاري",
    }
    closed_values = {
        "closed",
        "completed",
        "cancelled",
        "canceled",
        "submitted",
        "shift closed",
        "مغلق",
        "مكتمل",
        "ملغي",
        "منتهي",
        "تم الاغلاق",
        "تم الإغلاق",
    }

    best = None
    best_score = None
    current_user = frappe.session.user
    today_value = getdate(nowdate())

    for row in rows:
        status = ""
        for fieldname in status_fields:
            if row.get(fieldname):
                status = _normalise_status(row.get(fieldname))
                break

        if status in closed_values:
            continue

        is_explicitly_open = status in open_values
        if cint(row.docstatus) == 1 and not is_explicitly_open:
            continue

        if any(row.get(fieldname) for fieldname in close_fields):
            continue

        if company:
            shift_company = next(
                (row.get(fieldname) for fieldname in company_fields if row.get(fieldname)),
                None,
            )
            if shift_company and shift_company != company:
                continue

        score = 100 if is_explicitly_open else 50
        if cint(row.docstatus) == 0:
            score += 30

        shift_user = next(
            (row.get(fieldname) for fieldname in user_fields if row.get(fieldname)),
            None,
        )
        if shift_user and shift_user == current_user:
            score += 20
        elif row.get("owner") == current_user:
            score += 10

        shift_date = next(
            (row.get(fieldname) for fieldname in date_fields if row.get(fieldname)),
            None,
        )
        if shift_date:
            try:
                if getdate(shift_date) == today_value:
                    score += 15
                else:
                    score -= 5
            except Exception:
                pass

        marker = (score, str(row.creation or row.modified or ""))
        if best_score is None or marker > best_score:
            best = row.name
            best_score = marker

    return best or ""


def get_trip_defaults(company=None):
    return frappe._dict(
        {
            "vehicle": _get_default_value(TRIP_DOCTYPE, "vehicle", ""),
            "delivery_method": _get_default_value(
                TRIP_DOCTYPE,
                "custom_delivery_method",
                "Motorcycle",
            ),
            "shift_reference": get_current_open_shift(company=company),
        }
    )


def _driver_for_employee(employee):
    if not employee:
        frappe.throw(_("يجب تعيين الطيار قبل إنشاء الرحلة."))

    driver = frappe.db.get_value(
        "Driver",
        {"employee": employee, "status": "Active"},
        "name",
    )
    if not driver:
        employee_name = frappe.db.get_value("Employee", employee, "employee_name") or employee
        frappe.throw(
            _("لا يوجد Driver نشط مربوط بالموظف {0}.").format(employee_name)
        )
    return driver


def _employee_data(employee):
    if not employee:
        return frappe._dict()
    return frappe.db.get_value(
        "Employee",
        employee,
        ["name", "employee_name", "user_id", "status"],
        as_dict=True,
    ) or frappe._dict()


def _invoice_address(invoice):
    return (
        invoice.get("shipping_address_name")
        or invoice.get("customer_address")
        or ""
    )


def _active_trip_name_from_invoice(invoice):
    if not sales_invoice_has(TRIP_FIELD):
        return ""

    trip_name = invoice.get(TRIP_FIELD) or ""
    if not trip_name or not frappe.db.exists(TRIP_DOCTYPE, trip_name):
        return ""

    trip = frappe.db.get_value(
        TRIP_DOCTYPE,
        trip_name,
        ["docstatus", "custom_operational_status"],
        as_dict=True,
    ) or frappe._dict()
    operational_status = trip.get("custom_operational_status") or ""
    if cint(trip.get("docstatus")) != 2 and operational_status in ACTIVE_TRIP_STATUSES:
        return trip_name
    return ""


def get_active_trip_for_invoice(invoice):
    trip_name = _active_trip_name_from_invoice(invoice)
    return frappe.get_doc(TRIP_DOCTYPE, trip_name) if trip_name else None


def clear_invoice_trip_link(invoice):
    for fieldname in (TRIP_FIELD, TRIP_STOP_ROW_FIELD, TRIP_STOP_SEQUENCE_FIELD):
        if sales_invoice_has(fieldname):
            invoice.set(fieldname, "" if fieldname != TRIP_STOP_SEQUENCE_FIELD else 0)


def _latest_add_on_name(parent_name):
    if not sales_invoice_has("custom_parent_delivery_invoice"):
        return ""
    rows = frappe.get_all(
        "Sales Invoice",
        filters={
            "custom_parent_delivery_invoice": parent_name,
            "docstatus": 1,
            "is_return": 0,
        },
        pluck="name",
        order_by="creation desc",
        limit_page_length=1,
    )
    return rows[0] if rows else ""


def _set_invoice_trip_values(invoice_name, trip_name, stop_row, sequence):
    values = {}
    if sales_invoice_has(TRIP_FIELD):
        values[TRIP_FIELD] = trip_name
    if sales_invoice_has(TRIP_STOP_ROW_FIELD):
        values[TRIP_STOP_ROW_FIELD] = stop_row
    if sales_invoice_has(TRIP_STOP_SEQUENCE_FIELD):
        values[TRIP_STOP_SEQUENCE_FIELD] = sequence

    if not values:
        return

    for name in delivery_group_invoice_names(invoice_name):
        if frappe.db.exists("Sales Invoice", name):
            frappe.db.set_value(
                "Sales Invoice",
                name,
                values,
                update_modified=False,
            )


def _trip_stop_for_invoice(trip, invoice):
    stop_row_name = invoice.get(TRIP_STOP_ROW_FIELD) if sales_invoice_has(TRIP_STOP_ROW_FIELD) else ""
    if stop_row_name:
        for stop in trip.delivery_stops:
            if stop.name == stop_row_name:
                return stop

    for stop in trip.delivery_stops:
        if stop.get("custom_parent_delivery_invoice") == invoice.name:
            return stop
    return None


def _refresh_stop_snapshot(stop, invoice):
    snapshot = delivery_group_snapshot(invoice)
    parent_total = flt(invoice.grand_total)

    stop.customer = invoice.customer
    stop.address = _invoice_address(invoice)
    stop.customer_address = invoice.get("shipping_address") or invoice.get("address_display") or ""
    stop.contact = invoice.get("contact_person") or ""
    stop.customer_contact = invoice.get("contact_mobile") or ""
    stop.grand_total = snapshot.grand_total
    stop.details = _("Sales Invoice {0}").format(invoice.name)

    _set_if_has(stop, "custom_parent_delivery_invoice", invoice.name)
    _set_if_has(stop, "custom_expected_collection", snapshot.outstanding_amount)
    _set_if_has(
        stop,
        "custom_driver_reported_collection",
        flt(invoice.get("custom_driver_reported_collected_amount") or 0),
    )
    _set_if_has(stop, "custom_attempt_count", cint(invoice.get(ATTEMPT_COUNT_FIELD) or 0))
    _set_if_has(stop, "custom_current_delivery_attempt", invoice.get(CURRENT_ATTEMPT_FIELD) or "")
    _set_if_has(stop, "custom_add_on_requested", cint(invoice.get("custom_add_on_requested") or 0))
    _set_if_has(stop, "custom_add_on_invoice", _latest_add_on_name(invoice.name))

    return frappe._dict(
        {
            "original_total": parent_total,
            "add_on_total": max(0, flt(snapshot.grand_total) - parent_total),
            "trip_total": snapshot.grand_total,
            "prepaid_total": snapshot.prepaid_amount,
            "expected_collection": snapshot.outstanding_amount,
            "driver_reported_collection": flt(
                invoice.get("custom_driver_reported_collected_amount") or 0
            ),
            "confirmed_collection": flt(
                invoice.get("custom_confirmed_collected_amount") or 0
            ),
        }
    )


def recalculate_trip(trip, update_operational_status=True):
    total_stops = len(trip.delivery_stops)
    delivered = 0
    returned = 0
    failed = 0
    pending = 0

    original_total = 0
    add_on_total = 0
    trip_total = 0
    prepaid_total = 0
    expected_collection = 0
    driver_reported = 0
    confirmed_collection = 0

    statuses = []
    for stop in trip.delivery_stops:
        invoice_name = stop.get("custom_parent_delivery_invoice")
        if invoice_name and frappe.db.exists("Sales Invoice", invoice_name):
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            amounts = _refresh_stop_snapshot(stop, invoice)
            original_total += amounts.original_total
            add_on_total += amounts.add_on_total
            trip_total += amounts.trip_total
            prepaid_total += amounts.prepaid_total
            expected_collection += amounts.expected_collection
            driver_reported += amounts.driver_reported_collection
            confirmed_collection += amounts.confirmed_collection

        status = stop.get("custom_stop_status") or "Ready"
        statuses.append(status)
        if status == "Delivered":
            delivered += 1
        elif status == "Returned to Pharmacy":
            returned += 1
        elif status in {"Failed", "Cancelled"}:
            failed += 1
        else:
            pending += 1

    _set_if_has(trip, "custom_total_stops", total_stops)
    _set_if_has(trip, "custom_delivered_stops", delivered)
    _set_if_has(trip, "custom_returned_stops", returned)
    _set_if_has(trip, "custom_failed_stops", failed)
    _set_if_has(trip, "custom_pending_stops", pending)

    _set_if_has(trip, "custom_original_orders_total", flt(original_total, 6))
    _set_if_has(trip, "custom_add_on_total", flt(add_on_total, 6))
    _set_if_has(trip, "custom_trip_total", flt(trip_total, 6))
    _set_if_has(trip, "custom_prepaid_total", flt(prepaid_total, 6))
    _set_if_has(trip, "custom_expected_collection", flt(expected_collection, 6))
    _set_if_has(trip, "custom_driver_reported_collection", flt(driver_reported, 6))
    _set_if_has(trip, "custom_confirmed_collection", flt(confirmed_collection, 6))
    _set_if_has(
        trip,
        "custom_collection_difference",
        flt(confirmed_collection - expected_collection, 6),
    )

    if update_operational_status and trip.get("custom_operational_status") not in {"Completed", "Cancelled"}:
        if cint(trip.docstatus) == 0:
            operational_status = "Ready"
        else:
            active_statuses = {"Ready", "Out for Delivery"}
            any_active = any(status in active_statuses for status in statuses)
            any_progress = any(
                status in {"Delivered", "Returned to Pharmacy", "Failed", "Cancelled", "Returning for Add-on"}
                for status in statuses
            )
            if any_active:
                operational_status = "Partially Delivered" if any_progress else "Out for Delivery"
            elif statuses and all(status in RETURNABLE_STOP_STATUSES for status in statuses):
                operational_status = "Returning to Pharmacy"
                if not trip.get("custom_returning_at"):
                    _set_if_has(trip, "custom_returning_at", now_datetime())
            else:
                operational_status = "Out for Delivery"
        _set_if_has(trip, "custom_operational_status", operational_status)

    return trip


@frappe.whitelist()
def create_trip(invoice_names, vehicle=None, shift_reference=None, delivery_method=None):
    names = _parse_invoice_names(invoice_names)
    if not names:
        frappe.throw(_("حدد أوردرًا واحدًا على الأقل لإنشاء الرحلة."))

    invoices = []
    company = None
    employee = None

    for name in names:
        invoice = frappe.get_doc("Sales Invoice", name)
        invoice.check_permission("write")

        if invoice.docstatus != 1:
            frappe.throw(_("الفاتورة {0} غير معتمدة.").format(name))
        if invoice.get("custom_order_type") != "Home Delivery":
            frappe.throw(_("الفاتورة {0} ليست Home Delivery.").format(name))
        if invoice.get("custom_delivery_status") != "Ready for Delivery":
            frappe.throw(_("الفاتورة {0} ليست جاهزة للتوصيل.").format(name))
        if not invoice.get("custom_delivery_boy"):
            frappe.throw(_("الفاتورة {0} ليس لها طيار معين.").format(name))
        if not can_depart(invoice):
            frappe.throw(
                _("الفاتورة {0} لديها Add-on غير مكتمل أو دفع مسبق بانتظار التأكيد.").format(name)
            )

        active_trip = _active_trip_name_from_invoice(invoice)
        if active_trip:
            frappe.throw(
                _("الفاتورة {0} موجودة بالفعل في الرحلة {1}.").format(name, active_trip)
            )

        company = company or invoice.company
        employee = employee or invoice.get("custom_delivery_boy")
        if invoice.company != company:
            frappe.throw(_("كل الأوردرات يجب أن تكون لنفس الشركة."))
        if invoice.get("custom_delivery_boy") != employee:
            frappe.throw(_("كل الأوردرات المحددة يجب أن تكون لنفس الطيار."))
        if not _invoice_address(invoice):
            frappe.throw(_("الفاتورة {0} لا تحتوي على عنوان مرتبط.").format(name))

        invoices.append(invoice)

    employee_data = _employee_data(employee)
    if employee_data.get("status") != "Active":
        frappe.throw(_("الطيار المحدد غير نشط."))

    driver = _driver_for_employee(employee)
    defaults = get_trip_defaults(company=company)
    vehicle = vehicle or defaults.vehicle
    if not vehicle:
        frappe.throw(_("حدد Vehicle للرحلة أو ضع قيمة افتراضية في Delivery Trip."))
    if not frappe.db.exists("Vehicle", vehicle):
        frappe.throw(_("Vehicle غير موجود: {0}").format(vehicle))

    current_shift = defaults.shift_reference or get_current_open_shift(company=company)
    if not current_shift:
        frappe.throw(
            _("لا يوجد Pharmacy Shift Closing مفتوح حاليًا. افتح الشيفت أولًا ثم أعد إنشاء الرحلة.")
        )
    shift_reference = current_shift

    trip = frappe.new_doc(TRIP_DOCTYPE)
    if trip.meta.has_field("naming_series") and not trip.get("naming_series"):
        naming_field = trip.meta.get_field("naming_series")
        naming_options = [
            option.strip()
            for option in (naming_field.options or "").splitlines()
            if option.strip()
        ]
        if naming_options:
            trip.naming_series = naming_options[0]
    trip.company = company
    trip.driver = driver
    trip.employee = employee
    trip.driver_name = frappe.db.get_value("Driver", driver, "full_name") or employee_data.get("employee_name") or employee
    trip.vehicle = vehicle
    trip.departure_time = now_datetime()

    _set_if_has(trip, "custom_shift_reference", shift_reference or "")
    _set_if_has(trip, "custom_delivery_user", employee_data.get("user_id") or "")
    _set_if_has(trip, "custom_operational_status", "Ready")
    _set_if_has(
        trip,
        "custom_delivery_method",
        delivery_method or defaults.delivery_method or "Motorcycle",
    )

    for invoice in invoices:
        stop = trip.append("delivery_stops", {})
        stop.customer = invoice.customer
        stop.address = _invoice_address(invoice)
        stop.customer_address = invoice.get("shipping_address") or invoice.get("address_display") or ""
        stop.contact = invoice.get("contact_person") or ""
        stop.customer_contact = invoice.get("contact_mobile") or ""
        stop.details = _("Sales Invoice {0}").format(invoice.name)
        stop.locked = 0
        stop.visited = 0
        _set_if_has(stop, "custom_parent_delivery_invoice", invoice.name)
        _set_if_has(stop, "custom_stop_status", "Ready")
        _refresh_stop_snapshot(stop, invoice)

    recalculate_trip(trip, update_operational_status=False)
    trip.insert(ignore_permissions=True)

    for stop in trip.delivery_stops:
        invoice_name = stop.get("custom_parent_delivery_invoice")
        if invoice_name:
            _set_invoice_trip_values(invoice_name, trip.name, stop.name, stop.idx)

    return get_trip_summary(trip.name)


def _validate_trip_owner(trip, employee=None):
    if employee and trip.get("employee") != employee:
        frappe.throw(_("هذه الرحلة غير مخصصة لك."), frappe.PermissionError)


def start_trip(trip_name, employee=None, delivery_user=None):
    if not trip_name:
        frappe.throw(_("رقم الرحلة مطلوب."))

    trip = frappe.get_doc(TRIP_DOCTYPE, trip_name)
    _validate_trip_owner(trip, employee)

    if trip.docstatus != 0:
        frappe.throw(_("لا يمكن بدء رحلة بدأت أو أُلغيت بالفعل."))
    if not trip.delivery_stops:
        frappe.throw(_("لا توجد أوردرات داخل الرحلة."))

    departure_time = now_datetime()
    trip.departure_time = departure_time
    _set_if_has(trip, "custom_operational_status", "Out for Delivery")
    _set_if_has(trip, "custom_returning_at", None)
    _set_if_has(trip, "custom_returned_at", None)
    _set_if_has(trip, "custom_trip_duration_mins", 0)

    for stop in trip.delivery_stops:
        invoice_name = stop.get("custom_parent_delivery_invoice")
        if not invoice_name:
            frappe.throw(_("يوجد صف داخل الرحلة بدون Sales Invoice."))

        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        if invoice.docstatus != 1 or invoice.get("custom_delivery_status") != "Ready for Delivery":
            frappe.throw(_("الأوردر {0} لم يعد جاهزًا للخروج.").format(invoice_name))
        if invoice.get("custom_delivery_boy") != trip.get("employee"):
            frappe.throw(_("الطيار في الأوردر {0} لا يطابق طيار الرحلة.").format(invoice_name))
        if not can_depart(invoice):
            frappe.throw(_("الأوردر {0} لديه Add-on غير مكتمل أو دفع مسبق بانتظار التأكيد.").format(invoice_name))

        attempt = start_delivery_attempt(
            invoice,
            delivery_user=delivery_user or trip.get("custom_delivery_user") or frappe.session.user,
            delivery_trip=trip.name,
            delivery_trip_stop_row=stop.name,
            trip_stop_sequence=stop.idx,
        )
        invoice.save(ignore_permissions=True)
        sync_delivery_group(
            invoice,
            "Out for Delivery",
            departure_time=invoice.get("custom_departure_time"),
        )

        stop.visited = 0
        _set_if_has(stop, "custom_stop_status", "Out for Delivery")
        _set_if_has(stop, "custom_current_delivery_attempt", attempt.name if attempt else "")
        _set_if_has(stop, "custom_attempt_count", cint(invoice.get(ATTEMPT_COUNT_FIELD) or 0))
        _set_if_has(stop, "custom_delivered_at", None)
        _set_if_has(stop, "custom_delivery_duration_mins", 0)
        _set_if_has(stop, "custom_previous_stop_delivered_at", None)
        _set_if_has(stop, "custom_leg_duration_mins", 0)
        _set_invoice_trip_values(invoice.name, trip.name, stop.name, stop.idx)

    recalculate_trip(trip, update_operational_status=False)
    trip.save(ignore_permissions=True)

    old_mute = getattr(frappe.flags, "mute_messages", False)
    frappe.flags.mute_messages = True
    try:
        trip.flags.ignore_permissions = True
        trip.submit()
    finally:
        frappe.flags.mute_messages = old_mute

    return get_trip_summary(trip.name)


def complete_trip_stop(invoice, attempt_name=None):
    trip = get_active_trip_for_invoice(invoice)
    if not trip or trip.docstatus != 1:
        return None

    stop = _trip_stop_for_invoice(trip, invoice)
    if not stop:
        return None

    now = invoice.get("custom_delivery_time") or now_datetime()
    previous_times = []
    for other in trip.delivery_stops:
        if other.name == stop.name:
            continue
        delivered_at = other.get("custom_delivered_at")
        if delivered_at and get_datetime(delivered_at) <= get_datetime(now):
            previous_times.append(get_datetime(delivered_at))
    previous_delivery = max(previous_times) if previous_times else None
    leg_start = previous_delivery or trip.departure_time

    stop.visited = 1
    _set_if_has(stop, "custom_stop_status", "Delivered")
    _set_if_has(stop, "custom_current_delivery_attempt", attempt_name or "")
    _set_if_has(stop, "custom_attempt_count", cint(invoice.get(ATTEMPT_COUNT_FIELD) or 0))
    _set_if_has(stop, "custom_delivered_at", now)
    _set_if_has(
        stop,
        "custom_delivery_duration_mins",
        _duration_minutes(trip.departure_time, now),
    )
    _set_if_has(stop, "custom_previous_stop_delivered_at", previous_delivery)
    _set_if_has(stop, "custom_leg_duration_mins", _duration_minutes(leg_start, now))
    _set_if_has(stop, "custom_add_on_requested", 0)
    _set_if_has(stop, "custom_add_on_invoice", "")
    _set_if_has(stop, "custom_stop_issue", "None")
    _set_if_has(stop, "custom_issue_reason", "")

    # The trip may have been marked Returning to Pharmacy when all its stops
    # were returnable. Cancelling the add-on request makes this stop active
    # again, so stale trip return timestamps must not remain.
    _set_if_has(trip, "custom_returning_at", None)
    _set_if_has(trip, "custom_returned_at", None)
    recalculate_trip(trip, update_operational_status=True)
    trip.flags.ignore_validate_update_after_submit = True
    trip.save(ignore_permissions=True)
    return get_trip_summary(trip.name)


def mark_trip_stop_returning(invoice, notes):
    trip = get_active_trip_for_invoice(invoice)
    if not trip or trip.docstatus != 1:
        return None

    stop = _trip_stop_for_invoice(trip, invoice)
    if not stop:
        return None

    current_attempt = get_current_attempt(invoice)
    _set_if_has(stop, "custom_stop_status", "Returning for Add-on")
    _set_if_has(stop, "custom_current_delivery_attempt", current_attempt.name if current_attempt else "")
    _set_if_has(stop, "custom_attempt_count", cint(invoice.get(ATTEMPT_COUNT_FIELD) or 0))
    _set_if_has(stop, "custom_add_on_requested", 1)
    _set_if_has(stop, "custom_stop_issue", "Customer Requested Additional Items")
    _set_if_has(stop, "custom_issue_reason", notes or "")

    recalculate_trip(trip, update_operational_status=True)
    trip.flags.ignore_validate_update_after_submit = True
    trip.save(ignore_permissions=True)
    return get_trip_summary(trip.name)


def cancel_trip_stop_add_on_return(invoice):
    """Return an active trip stop from Returning for Add-on to Out for Delivery."""
    trip = get_active_trip_for_invoice(invoice)
    if not trip or trip.docstatus != 1:
        return None

    stop = _trip_stop_for_invoice(trip, invoice)
    if not stop:
        return None

    if (stop.get("custom_stop_status") or "") != "Returning for Add-on":
        return get_trip_summary(trip.name)

    current_attempt = get_current_attempt(invoice)
    stop.visited = 0
    _set_if_has(stop, "custom_stop_status", "Out for Delivery")
    _set_if_has(
        stop,
        "custom_current_delivery_attempt",
        current_attempt.name if current_attempt else "",
    )
    _set_if_has(stop, "custom_attempt_count", cint(invoice.get(ATTEMPT_COUNT_FIELD) or 0))
    _set_if_has(stop, "custom_add_on_requested", 0)
    _set_if_has(stop, "custom_add_on_invoice", "")
    _set_if_has(stop, "custom_stop_issue", "None")
    _set_if_has(stop, "custom_issue_reason", "")

    # The trip may have been marked Returning to Pharmacy when all its stops
    # were returnable. Cancelling the add-on request makes this stop active
    # again, so stale trip return timestamps must not remain.
    _set_if_has(trip, "custom_returning_at", None)
    _set_if_has(trip, "custom_returned_at", None)
    recalculate_trip(trip, update_operational_status=True)
    trip.flags.ignore_validate_update_after_submit = True
    trip.save(ignore_permissions=True)
    return get_trip_summary(trip.name)


def can_return_trip(trip):
    if not trip.delivery_stops:
        return False
    statuses = [stop.get("custom_stop_status") or "Ready" for stop in trip.delivery_stops]
    return all(status in RETURNABLE_STOP_STATUSES for status in statuses)


def return_trip_to_pharmacy(trip_name, employee=None):
    if not trip_name:
        frappe.throw(_("رقم الرحلة مطلوب."))

    trip = frappe.get_doc(TRIP_DOCTYPE, trip_name)
    _validate_trip_owner(trip, employee)

    if trip.docstatus != 1:
        frappe.throw(_("الرحلة ليست في حالة تسمح بتسجيل الرجوع."))
    if trip.get("custom_operational_status") == "Completed":
        return get_trip_summary(trip.name)
    if not can_return_trip(trip):
        frappe.throw(_("لا يمكن إنهاء الرحلة قبل إنهاء كل الأوردرات داخلها."))

    for stop in trip.delivery_stops:
        status = stop.get("custom_stop_status") or "Ready"
        invoice_name = stop.get("custom_parent_delivery_invoice")

        if status == "Returning for Add-on":
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            result = finish_return_to_pharmacy(invoice)
            invoice.save(ignore_permissions=True)
            stop.visited = 1
            _set_if_has(stop, "custom_stop_status", "Returned to Pharmacy")
            _set_if_has(stop, "custom_current_delivery_attempt", result.attempt)
            _set_if_has(stop, "custom_add_on_requested", 1)
            _set_if_has(stop, "custom_stop_issue", "Customer Requested Additional Items")
            _set_if_has(stop, "custom_issue_reason", invoice.get(ADD_ON_NOTES_FIELD) or "")
        elif status in FINAL_STOP_STATUSES:
            stop.visited = 1

    returned_at = now_datetime()
    if not trip.get("custom_returning_at"):
        _set_if_has(trip, "custom_returning_at", returned_at)
    _set_if_has(trip, "custom_returned_at", returned_at)
    _set_if_has(
        trip,
        "custom_trip_duration_mins",
        _duration_minutes(trip.departure_time, returned_at),
    )
    _set_if_has(trip, "custom_operational_status", "Completed")

    recalculate_trip(trip, update_operational_status=False)
    trip.flags.ignore_validate_update_after_submit = True
    trip.save(ignore_permissions=True)
    return get_trip_summary(trip.name)


def _trip_fields():
    fields = [
        "name",
        "docstatus",
        "company",
        "driver",
        "driver_name",
        "employee",
        "vehicle",
        "departure_time",
        "status",
        "creation",
        "modified",
    ]
    for fieldname in (
        "custom_shift_reference",
        "custom_delivery_user",
        "custom_operational_status",
        "custom_returning_at",
        "custom_returned_at",
        "custom_trip_duration_mins",
        "custom_total_stops",
        "custom_delivered_stops",
        "custom_pending_stops",
        "custom_returned_stops",
        "custom_failed_stops",
        "custom_original_orders_total",
        "custom_add_on_total",
        "custom_trip_total",
        "custom_prepaid_total",
        "custom_expected_collection",
        "custom_driver_reported_collection",
        "custom_confirmed_collection",
        "custom_collection_difference",
        "custom_delivery_method",
    ):
        if _trip_has(fieldname):
            fields.append(fieldname)
    return fields


def get_trip_summary(trip_name):
    row = frappe.db.get_value(TRIP_DOCTYPE, trip_name, _trip_fields(), as_dict=True)
    if not row:
        return frappe._dict()

    trip = frappe.get_doc(TRIP_DOCTYPE, trip_name)
    row["can_start"] = cint(trip.docstatus) == 0 and (trip.get("custom_operational_status") or "Ready") == "Ready"
    row["can_return"] = cint(trip.docstatus) == 1 and can_return_trip(trip) and (trip.get("custom_operational_status") or "") != "Completed"
    row["invoice_names"] = [
        stop.get("custom_parent_delivery_invoice")
        for stop in trip.delivery_stops
        if stop.get("custom_parent_delivery_invoice")
    ]
    row["stops"] = [
        {
            "row_name": stop.name,
            "idx": stop.idx,
            "invoice": stop.get("custom_parent_delivery_invoice") or "",
            "customer": stop.customer or "",
            "status": stop.get("custom_stop_status") or "Ready",
            "delivered_at": stop.get("custom_delivered_at"),
        }
        for stop in trip.delivery_stops
    ]
    return row


def get_trip_summaries(trip_names):
    names = []
    for name in trip_names or []:
        if name and name not in names and frappe.db.exists(TRIP_DOCTYPE, name):
            names.append(name)
    return [get_trip_summary(name) for name in names]


def get_employee_trip_summaries(employee, include_completed_today=True):
    if not employee:
        return []

    trip_names = frappe.get_all(
        TRIP_DOCTYPE,
        filters={
            "employee": employee,
            "docstatus": ["<", 2],
        },
        pluck="name",
        order_by="creation desc",
        limit_page_length=100,
    )

    results = []
    today_value = getdate(nowdate())
    for trip_name in trip_names:
        summary = get_trip_summary(trip_name)
        operational = summary.get("custom_operational_status") or "Ready"
        if operational in ACTIVE_TRIP_STATUSES:
            results.append(summary)
            continue
        if include_completed_today and operational == "Completed":
            completed_at = summary.get("custom_returned_at") or summary.get("modified")
            if completed_at and getdate(completed_at) == today_value:
                results.append(summary)

    return results


def annotate_orders_with_trips(orders):
    trip_names = []
    for order in orders:
        trip_name = order.get(TRIP_FIELD) if sales_invoice_has(TRIP_FIELD) else ""
        if trip_name and trip_name not in trip_names:
            trip_names.append(trip_name)

    summaries = get_trip_summaries(trip_names)
    by_name = {row.name: row for row in summaries}

    for order in orders:
        trip_name = order.get(TRIP_FIELD) if sales_invoice_has(TRIP_FIELD) else ""
        trip = by_name.get(trip_name)
        operational = trip.get("custom_operational_status") if trip else ""
        order["delivery_trip_active"] = bool(
            trip
            and cint(trip.get("docstatus")) != 2
            and operational in ACTIVE_TRIP_STATUSES
        )
        order["trip_operational_status"] = operational or ""
        order["trip_docstatus"] = cint(trip.get("docstatus")) if trip else 0
        order["trip_can_start"] = bool(trip.get("can_start")) if trip else False
        order["trip_can_return"] = bool(trip.get("can_return")) if trip else False

    return summaries
