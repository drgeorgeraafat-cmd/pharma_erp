import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, time_diff_in_seconds

from pharma_erp.pharma_erp.delivery_collection import COLLECTION_PROOF_FIELD


DRIVER_RETURN_STATUS_FIELD = "custom_driver_return_status"
DRIVER_RETURNED_AT_FIELD = "custom_driver_returned_at"
RETURN_STATUS_FIELD = "custom_delivery_return_status"
RETURN_REASON_FIELD = "custom_delivery_return_reason"
RETURN_NOTES_FIELD = "custom_delivery_return_notes"
RETURN_REVIEWED_BY_FIELD = "custom_delivery_return_reviewed_by"
RETURN_REVIEWED_AT_FIELD = "custom_delivery_return_reviewed_at"
RETURN_CREDIT_NOTE_FIELD = "custom_delivery_return_credit_note"
CURRENT_ATTEMPT_FIELD = "custom_current_delivery_attempt"
RETURN_TYPE_FIELD = "custom_delivery_return_type"
ACTIVE_RETURN_REQUEST_FIELD = "custom_active_delivery_return_request"
LAST_RETURN_REQUEST_FIELD = "custom_last_delivery_return_request"
ADD_ON_PARENT_FIELD = "custom_parent_delivery_invoice"


DRIVER_OUT = "Out With Driver"
DRIVER_RETURNING = "Returning to Pharmacy"
DRIVER_RETURNED = "Returned to Pharmacy"
DRIVER_NOT_REQUIRED = "Not Required"

RETURN_NOT_REQUIRED = "Not Required"
RETURN_RETURNING = "Returning to Pharmacy"
RETURN_AWAITING_REVIEW = "Awaiting Manager Review"
RETURN_CREDIT_NOTE_DRAFT = "Credit Note Draft"
RETURN_COMPLETED = "Return Completed"

DELIVERY_RETURNING = "Returning to Pharmacy"
DELIVERY_RETURNED = "Returned to Pharmacy"
DELIVERY_CANCELLED = "Cancelled"

RETURN_REASONS = {
    "Customer Cancelled Order": "Customer Cancelled Order",
    "Customer Refused Order": "Customer Refused Order",
    "Customer Not Answering": "Customer Not Answering",
    "Wrong Address": "Wrong Address",
    "Payment Problem": "Payment Problem",
    "Other": "Other",
}


def _has_field(doctype, fieldname):
    return bool(frappe.get_meta(doctype).has_field(fieldname))


def _set_if_field(doc, fieldname, value):
    if _has_field(doc.doctype, fieldname):
        doc.set(fieldname, value)


def _delivery_group_invoices(invoice_name):
    """Return the operational parent and all submitted Add-on invoices."""
    source = frappe.get_doc("Sales Invoice", invoice_name)
    parent = source
    if (
        _has_field("Sales Invoice", ADD_ON_PARENT_FIELD)
        and str(source.get(ADD_ON_PARENT_FIELD) or "").strip()
    ):
        parent_name = str(source.get(ADD_ON_PARENT_FIELD) or "").strip()
        if frappe.db.exists("Sales Invoice", parent_name):
            parent = frappe.get_doc("Sales Invoice", parent_name)

    invoices = [parent]
    if not _has_field("Sales Invoice", ADD_ON_PARENT_FIELD):
        return parent, invoices

    names = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            ADD_ON_PARENT_FIELD: parent.name,
        },
        pluck="name",
        order_by="creation asc",
        limit_page_length=500,
    )
    invoices.extend(frappe.get_doc("Sales Invoice", name) for name in names)
    return parent, invoices


def _open_group_credit_notes(invoices):
    """Return draft/submitted credit notes linked to any invoice in the group."""
    invoice_names = [row.name for row in invoices]
    if not invoice_names:
        return []
    return frappe.get_all(
        "Sales Invoice",
        filters={
            "is_return": 1,
            "return_against": ["in", invoice_names],
            "docstatus": ["!=", 2],
        },
        fields=["name", "return_against", "docstatus"],
        order_by="creation asc",
        limit_page_length=500,
    )


def _reset_collection_cycle_for_redelivery(parent, invoices):
    """Prepare a new collection round without touching old accounting entries.

    A partial delivery may already have produced a valid Payment Entry while the
    returned item is still physically with the driver.  When that item is sent
    again, the next attempt must be able to collect only the current outstanding
    balance.  We clear the single-value UI fields, but the old submitted Payment
    Entry remains untouched and continues to be the accounting source of truth.
    """
    outstanding = flt(
        sum(max(0, flt(row.outstanding_amount)) for row in invoices),
        6,
    )
    if outstanding <= 0.01:
        return {
            "outstanding_amount": outstanding,
            "collection_reset": False,
            "previous_payment_entries": [],
        }

    current_status = str(
        parent.get("custom_collection_verification_status") or ""
    ).strip()
    if current_status in {"Awaiting Confirmation", "Disputed"}:
        frappe.throw(
            _(
                "لا يمكن إعادة إرسال الأوردر قبل حسم التحصيل الحالي. "
                "أكد أو ارفض التحصيل المعلق أولًا."
            )
        )

    previous_payment_entries = []
    for invoice in invoices:
        payment_name = str(invoice.get("custom_collection_payment_entry") or "").strip()
        if payment_name and payment_name not in previous_payment_entries:
            previous_payment_entries.append(payment_name)

    collection_fields = {
        "custom_driver_reported_customer_payment_method": "",
        "custom_driver_reported_collected_amount": 0,
        "custom_driver_collection_notes": "",
        "custom_driver_collection_reference": "",
        COLLECTION_PROOF_FIELD: "",
        "custom_delivery_card_pos_terminal": "",
        "custom_collection_declared_by": "",
        "custom_collection_declared_at": None,
        "custom_collection_verification_status": "Pending Driver Declaration",
        "custom_collection_received_by": "No Collection",
        "custom_confirmed_customer_payment_method": "",
        "custom_confirmed_collected_amount": 0,
        "custom_collection_review_notes": "",
        "custom_collection_difference": 0,
        "custom_collection_difference_reason": "",
        "custom_collection_confirmed_by": "",
        "custom_collection_confirmed_at": None,
        "custom_collection_payment_entry": "",
    }

    for invoice in invoices:
        for fieldname, value in collection_fields.items():
            if _has_field("Sales Invoice", fieldname):
                if fieldname == "custom_collection_verification_status":
                    _set_select_if_allowed(
                        invoice,
                        fieldname,
                        value,
                        fallback="Not Required",
                    )
                elif fieldname == "custom_collection_received_by":
                    _set_select_if_allowed(
                        invoice,
                        fieldname,
                        value,
                        fallback="No Collection",
                    )
                else:
                    invoice.set(fieldname, value)

    return {
        "outstanding_amount": outstanding,
        "collection_reset": True,
        "previous_payment_entries": previous_payment_entries,
    }


def _select_options(doctype, fieldname):
    field = frappe.get_meta(doctype).get_field(fieldname)
    if not field:
        return []
    return [line.strip() for line in str(field.options or "").splitlines() if line.strip()]


def _set_select_if_allowed(doc, fieldname, value, fallback=None):
    if not _has_field(doc.doctype, fieldname):
        return
    options = _select_options(doc.doctype, fieldname)
    if not options or value in options:
        doc.set(fieldname, value)
    elif fallback and fallback in options:
        doc.set(fieldname, fallback)


def _duration_minutes(start, end):
    if not start or not end:
        return 0
    return round(max(0, time_diff_in_seconds(get_datetime(end), get_datetime(start))) / 60, 2)


def _delivery_stop_invoice_field():
    if not frappe.db.exists("DocType", "Delivery Stop"):
        return ""
    meta = frappe.get_meta("Delivery Stop")
    for candidate in ("custom_parent_delivery_invoice", "sales_invoice"):
        if meta.has_field(candidate):
            return candidate
    return ""


def trip_invoice_names(trip_name):
    invoice_field = _delivery_stop_invoice_field()
    if not invoice_field or not trip_name:
        return []
    return frappe.get_all(
        "Delivery Stop",
        filters={"parent": trip_name},
        pluck=invoice_field,
        order_by="idx asc",
        limit_page_length=1000,
    )


def mark_invoice_departed(invoice, save=False):
    if isinstance(invoice, str):
        invoice = frappe.get_doc("Sales Invoice", invoice)
    _set_if_field(invoice, DRIVER_RETURN_STATUS_FIELD, DRIVER_OUT)
    _set_if_field(invoice, DRIVER_RETURNED_AT_FIELD, None)
    if (invoice.get(RETURN_STATUS_FIELD) or RETURN_NOT_REQUIRED) == RETURN_COMPLETED:
        _set_if_field(invoice, RETURN_STATUS_FIELD, RETURN_NOT_REQUIRED)
    if save:
        invoice.flags.ignore_validate_update_after_submit = True
        invoice.save(ignore_permissions=True)
    return invoice


def mark_trip_departed(trip_name):
    updated = []
    for invoice_name in trip_invoice_names(trip_name):
        if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
            continue
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        if invoice.docstatus != 1 or cint(invoice.get("is_return")):
            continue
        mark_invoice_departed(invoice, save=True)
        updated.append(invoice.name)
    return updated


def _close_attempt_for_return(invoice, reason, notes):
    if not frappe.db.exists("DocType", "Delivery Attempt"):
        return ""
    attempt_name = invoice.get(CURRENT_ATTEMPT_FIELD) if _has_field("Sales Invoice", CURRENT_ATTEMPT_FIELD) else ""
    if not attempt_name or not frappe.db.exists("Delivery Attempt", attempt_name):
        return ""

    attempt = frappe.get_doc("Delivery Attempt", attempt_name)
    now = now_datetime()
    departure = attempt.get("departure_time") or invoice.get("custom_departure_time")
    return_started = attempt.get("return_started_at") or now

    _set_select_if_allowed(attempt, "attempt_status", "Returned to Pharmacy", fallback="Failed")
    _set_select_if_allowed(attempt, "attempt_outcome", "Failed", fallback="Pending")
    _set_select_if_allowed(attempt, "delivery_issue", reason, fallback="Other")
    _set_if_field(attempt, "issue_reason", notes or reason)
    _set_if_field(attempt, "returned_to_pharmacy_at", now)
    _set_if_field(attempt, "closed_at", now)
    _set_if_field(attempt, "return_duration_mins", _duration_minutes(return_started, now))
    _set_if_field(attempt, "total_attempt_duration_mins", _duration_minutes(departure, now))
    _set_if_field(attempt, "is_current_attempt", 0)
    attempt.save(ignore_permissions=True)
    _set_if_field(invoice, CURRENT_ATTEMPT_FIELD, "")
    return attempt.name


def _mark_trip_stop_failed(invoice, reason, notes):
    try:
        from pharma_erp.pharma_erp.delivery_trip import get_active_trip_for_invoice, recalculate_trip
    except Exception:
        return ""

    trip = get_active_trip_for_invoice(invoice)
    if not trip:
        return ""

    invoice_field = _delivery_stop_invoice_field()
    if not invoice_field:
        return trip.name

    stop_names = frappe.get_all(
        "Delivery Stop",
        filters={"parent": trip.name, invoice_field: invoice.name},
        pluck="name",
        limit_page_length=50,
    )
    stop_meta = frappe.get_meta("Delivery Stop")
    for stop_name in stop_names:
        values = {}
        if stop_meta.has_field("custom_stop_status"):
            values["custom_stop_status"] = "Failed"
        if stop_meta.has_field("custom_stop_issue"):
            issue_options = _select_options("Delivery Stop", "custom_stop_issue")
            mapped_issue = ""
            if not issue_options or reason in issue_options:
                mapped_issue = reason
            elif "Customer Refused Order" in issue_options:
                mapped_issue = "Customer Refused Order"
            elif "Other" in issue_options:
                mapped_issue = "Other"
            if mapped_issue:
                values["custom_stop_issue"] = mapped_issue
        if stop_meta.has_field("custom_issue_reason"):
            values["custom_issue_reason"] = notes or reason
        if values:
            frappe.db.set_value("Delivery Stop", stop_name, values, update_modified=False)

    try:
        recalculate_trip(trip, update_operational_status=True)
        if trip.docstatus == 1:
            trip.flags.ignore_validate_update_after_submit = True
        trip.save(ignore_permissions=True)
    except TypeError:
        recalculate_trip(trip)
        if trip.docstatus == 1:
            trip.flags.ignore_validate_update_after_submit = True
        trip.save(ignore_permissions=True)
    return trip.name


def request_customer_return(invoice, reason, notes=None, actor=None):
    if isinstance(invoice, str):
        invoice = frappe.get_doc("Sales Invoice", invoice)
    reason = str(reason or "").strip()
    notes = str(notes or "").strip()

    if reason not in RETURN_REASONS:
        frappe.throw(_("اختر سببًا صحيحًا لرجوع الأوردر."))
    if reason == "Other" and not notes:
        frappe.throw(_("اكتب سبب رجوع الأوردر في الملاحظات."))
    if invoice.docstatus != 1 or invoice.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("الأوردر المحدد غير صالح للدليفري."))
    if cint(invoice.get("is_return")):
        frappe.throw(_("لا يمكن تنفيذ الإجراء على فاتورة مرتجع."))
    if (invoice.get("custom_delivery_status") or "") != "Out for Delivery":
        frappe.throw(_("يمكن تسجيل رجوع الأوردر فقط أثناء خروجه للتوصيل."))

    now = now_datetime()
    invoice.custom_delivery_status = DELIVERY_RETURNING
    _set_if_field(invoice, DRIVER_RETURN_STATUS_FIELD, DRIVER_RETURNING)
    _set_if_field(invoice, RETURN_STATUS_FIELD, RETURN_RETURNING)
    _set_if_field(invoice, RETURN_TYPE_FIELD, "Full Order Cancellation")
    _set_if_field(invoice, RETURN_REASON_FIELD, reason)
    _set_if_field(invoice, RETURN_NOTES_FIELD, notes)
    if _has_field("Sales Invoice", "custom_delivery_issue"):
        issue_options = _select_options("Sales Invoice", "custom_delivery_issue")
        issue = reason if reason in issue_options else ("Other" if "Other" in issue_options else "")
        if issue:
            invoice.set("custom_delivery_issue", issue)
    if _has_field("Sales Invoice", "custom_delivery_issue_reason"):
        invoice.set("custom_delivery_issue_reason", notes or reason)

    attempt_name = invoice.get(CURRENT_ATTEMPT_FIELD) if _has_field("Sales Invoice", CURRENT_ATTEMPT_FIELD) else ""
    if attempt_name and frappe.db.exists("Delivery Attempt", attempt_name):
        attempt = frappe.get_doc("Delivery Attempt", attempt_name)
        _set_select_if_allowed(attempt, "attempt_status", "Returning to Pharmacy", fallback="Out for Delivery")
        _set_select_if_allowed(attempt, "delivery_issue", reason, fallback="Other")
        _set_if_field(attempt, "issue_reason", notes or reason)
        _set_if_field(attempt, "return_started_at", now)
        attempt.save(ignore_permissions=True)

    try:
        from pharma_erp.pharma_erp.delivery_partial_return import ensure_full_return_request
        request = ensure_full_return_request(invoice, reason, notes, actor=actor or frappe.session.user)
        if request:
            _set_if_field(invoice, ACTIVE_RETURN_REQUEST_FIELD, request.name)
            _set_if_field(invoice, LAST_RETURN_REQUEST_FIELD, request.name)
    except Exception:
        raise

    invoice.flags.ignore_validate_update_after_submit = True
    invoice.save(ignore_permissions=True)
    trip_name = _mark_trip_stop_failed(invoice, reason, notes)
    invoice.add_comment(
        "Comment",
        _("سجل الطيار رجوع الأوردر للصيدلية. السبب: {0}. {1}").format(reason, notes),
    )
    return {
        "invoice_name": invoice.name,
        "delivery_status": invoice.custom_delivery_status,
        "return_status": invoice.get(RETURN_STATUS_FIELD) or RETURN_RETURNING,
        "delivery_trip": trip_name,
    }


def mark_invoice_returned(invoice, save=True):
    if isinstance(invoice, str):
        invoice = frappe.get_doc("Sales Invoice", invoice)
    now = now_datetime()
    delivery_status = str(invoice.get("custom_delivery_status") or "").strip()
    return_status = str(invoice.get(RETURN_STATUS_FIELD) or "").strip()

    _set_if_field(invoice, DRIVER_RETURN_STATUS_FIELD, DRIVER_RETURNED)
    _set_if_field(invoice, DRIVER_RETURNED_AT_FIELD, now)

    if delivery_status == DELIVERY_RETURNING or return_status == RETURN_RETURNING:
        reason = invoice.get(RETURN_REASON_FIELD) or "Other"
        notes = invoice.get(RETURN_NOTES_FIELD) or ""
        _close_attempt_for_return(invoice, reason, notes)
        invoice.custom_delivery_status = DELIVERY_RETURNED
        _set_if_field(invoice, RETURN_STATUS_FIELD, RETURN_AWAITING_REVIEW)
    elif delivery_status == "Delivered":
        # The remaining items are delivered, but the driver may still be
        # carrying a partial return. Move that request to manager review when
        # the driver physically reaches the pharmacy.
        if frappe.db.exists("DocType", "Delivery Return Request"):
            from pharma_erp.pharma_erp.delivery_partial_return import (
                RETURN_TYPE_PARTIAL,
                get_active_request,
                mark_request_driver_returned,
            )

            partial_request = get_active_request(invoice.name)
            if partial_request and partial_request.return_type == RETURN_TYPE_PARTIAL:
                mark_request_driver_returned(invoice)
    else:
        frappe.throw(_("لا يمكن تسجيل الرجوع للصيدلية في حالة الأوردر الحالية."))

    if save:
        invoice.flags.ignore_validate_update_after_submit = True
        invoice.save(ignore_permissions=True)
    return invoice


def mark_trip_returned(trip_name):
    updated = []
    for invoice_name in trip_invoice_names(trip_name):
        if not invoice_name or not frappe.db.exists("Sales Invoice", invoice_name):
            continue
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        if invoice.docstatus != 1 or cint(invoice.get("is_return")):
            continue
        status = str(invoice.get("custom_delivery_status") or "").strip()
        if status in {"Delivered", DELIVERY_RETURNING, DELIVERY_RETURNED}:
            if status != DELIVERY_RETURNED:
                mark_invoice_returned(invoice, save=True)
            else:
                _set_if_field(invoice, DRIVER_RETURN_STATUS_FIELD, DRIVER_RETURNED)
                _set_if_field(invoice, DRIVER_RETURNED_AT_FIELD, now_datetime())
                invoice.flags.ignore_validate_update_after_submit = True
                invoice.save(ignore_permissions=True)
            updated.append(invoice.name)
    return updated


def reopen_returned_order_for_redelivery(invoice_name, notes=None, actor=None):
    """Cancel an unposted return request and make the same order deliverable again.

    This action is intentionally allowed only after the driver has physically
    returned to the pharmacy and before any draft/submitted Credit Note exists.
    The old Delivery Return Request and Delivery Attempt remain as audit history;
    the next departure creates a new attempt automatically (normally Manager
    Retry, or Redelivery After Add-on when the immediately previous attempt was
    the add-on return cycle).
    """
    from pharma_erp.pharma_erp.delivery_partial_return import (
        INVOICE_ACTIVE_REQUEST,
        INVOICE_LAST_REQUEST,
        RETURN_TYPE_FULL,
        RETURN_TYPE_PARTIAL,
        STATUS_CANCELLED,
        STATUS_CREDIT_NOTE_DRAFT,
        STATUS_FULL_COMPLETED,
        STATUS_PARTIAL_COMPLETED,
        get_active_request,
    )
    from pharma_erp.pharma_erp.delivery_attempt import sync_delivery_group
    from pharma_erp.pharma_erp.delivery_trip import (
        clear_invoice_trip_link,
        get_active_trip_for_invoice,
    )

    parent, invoices = _delivery_group_invoices(invoice_name)
    parent.check_permission("write")

    if parent.docstatus != 1 or cint(parent.get("is_return")):
        frappe.throw(_("الفاتورة الأصلية غير صالحة لإعادة التوصيل."))
    if parent.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("الإجراء متاح لأوردرات Home Delivery فقط."))

    request = get_active_request(parent.name)
    if not request:
        frappe.throw(_("لا يوجد طلب مرتجع مفتوح يمكن إلغاؤه لهذا الأوردر."))
    if request.return_type not in {RETURN_TYPE_FULL, RETURN_TYPE_PARTIAL}:
        frappe.throw(_("نوع طلب المرتجع الحالي غير مدعوم لإعادة التوصيل."))
    if request.status in {
        STATUS_CREDIT_NOTE_DRAFT,
        STATUS_PARTIAL_COMPLETED,
        STATUS_FULL_COMPLETED,
        STATUS_CANCELLED,
    }:
        frappe.throw(
            _("لا يمكن إعادة تشغيل الأوردر بعد إنشاء مرتجع المبيعات أو إغلاق الطلب.")
        )

    driver_return_status = str(parent.get(DRIVER_RETURN_STATUS_FIELD) or "").strip()
    if driver_return_status != DRIVER_RETURNED:
        frappe.throw(_("يجب أن يكون الطيار قد سجل الرجوع إلى الصيدلية أولًا."))

    request_credit_notes = [
        str(request.get("credit_note") or "").strip(),
        *[
            str(row.get("credit_note") or "").strip()
            for row in (request.get("items") or [])
        ],
    ]
    request_credit_notes = [name for name in request_credit_notes if name]
    group_credit_notes = _open_group_credit_notes(invoices)
    if request_credit_notes or group_credit_notes:
        names = request_credit_notes + [row.name for row in group_credit_notes]
        frappe.throw(
            _(
                "يوجد Credit Note مرتبط بالأوردر ({0}). "
                "ألغِ/احذف المسودة أولًا، أو أنشئ أوردرًا جديدًا بعد اعتماد المرتجع."
            ).format(", ".join(dict.fromkeys(names)))
        )

    active_trip = get_active_trip_for_invoice(parent)
    if active_trip:
        frappe.throw(
            _(
                "الأوردر ما زال مرتبطًا بالرحلة النشطة {0}. "
                "سجل رجوع الرحلة أولًا ثم أعد المحاولة."
            ).format(active_trip.name)
        )

    notes = str(notes or "").strip()
    actor = actor or frappe.session.user
    now = now_datetime()

    collection_result = _reset_collection_cycle_for_redelivery(parent, invoices)

    request.status = STATUS_CANCELLED
    request.completed_by = actor
    request.completed_at = now
    audit_note = _("أُلغي طلب المرتجع لإعادة إرسال الأوردر بناءً على طلب العميل.")
    if notes:
        audit_note = "{0} {1}".format(audit_note, notes)
    request.notes = "\n".join(
        part for part in [str(request.get("notes") or "").strip(), audit_note] if part
    )
    request.flags.ignore_permissions = True
    request.save(ignore_permissions=True)

    for invoice in invoices:
        invoice.custom_delivery_status = "Ready for Delivery"
        _set_if_field(invoice, DRIVER_RETURN_STATUS_FIELD, DRIVER_NOT_REQUIRED)
        _set_if_field(invoice, DRIVER_RETURNED_AT_FIELD, None)
        _set_if_field(invoice, RETURN_STATUS_FIELD, RETURN_NOT_REQUIRED)
        _set_if_field(invoice, RETURN_TYPE_FIELD, "Not Required")
        _set_if_field(invoice, RETURN_REASON_FIELD, "")
        _set_if_field(invoice, RETURN_NOTES_FIELD, "")
        _set_if_field(invoice, RETURN_CREDIT_NOTE_FIELD, "")
        _set_if_field(invoice, RETURN_REVIEWED_BY_FIELD, "")
        _set_if_field(invoice, RETURN_REVIEWED_AT_FIELD, None)
        _set_if_field(invoice, ACTIVE_RETURN_REQUEST_FIELD, "")
        _set_if_field(invoice, LAST_RETURN_REQUEST_FIELD, request.name)
        _set_if_field(invoice, CURRENT_ATTEMPT_FIELD, "")
        _set_if_field(invoice, "custom_departure_time", None)
        _set_if_field(invoice, "custom_delivery_time", None)
        _set_if_field(invoice, "custom_duration_in_mins", 0)
        _set_if_field(invoice, "custom_delivery_issue", "")
        _set_if_field(invoice, "custom_delivery_issue_reason", "")
        clear_invoice_trip_link(invoice)
        invoice.flags.ignore_validate_update_after_submit = True
        invoice.save(ignore_permissions=True)

    parent = frappe.get_doc("Sales Invoice", parent.name)
    sync_delivery_group(parent, "Ready for Delivery")
    parent.add_comment(
        "Comment",
        _(
            "أعاد مدير الشيفت فتح الأوردر للتوصيل. تم إلغاء طلب المرتجع {0}. "
            "المطلوب الحالي من العميل: {1}.{2}"
        ).format(
            request.name,
            frappe.format_value(
                collection_result["outstanding_amount"],
                {"fieldtype": "Currency", "options": parent.currency},
            ),
            " " + notes if notes else "",
        ),
    )

    return {
        "invoice_name": parent.name,
        "delivery_status": parent.custom_delivery_status,
        "cancelled_return_request": request.name,
        "return_type": request.return_type,
        "outstanding_amount": collection_result["outstanding_amount"],
        "collection_reset": collection_result["collection_reset"],
        "previous_payment_entries": collection_result["previous_payment_entries"],
        "delivery_boy": parent.get("custom_delivery_boy") or "",
    }


def driver_outside_orders(delivery_boy):
    if not delivery_boy or not _has_field("Sales Invoice", "custom_delivery_boy"):
        return []
    meta = frappe.get_meta("Sales Invoice")
    fields = ["name", "customer", "customer_name", "grand_total", "custom_delivery_status"]
    for fieldname in (DRIVER_RETURN_STATUS_FIELD, DRIVER_RETURNED_AT_FIELD, RETURN_STATUS_FIELD):
        if meta.has_field(fieldname):
            fields.append(fieldname)
    rows = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            "custom_order_type": "Home Delivery",
            "custom_delivery_boy": delivery_boy,
        },
        fields=fields,
        order_by="creation asc",
        limit_page_length=2000,
    )
    output = []
    for row in rows:
        delivery_status = str(row.get("custom_delivery_status") or "").strip()
        physical_status = str(row.get(DRIVER_RETURN_STATUS_FIELD) or "").strip()
        # Operational delivery status is the source of truth. Older test orders
        # may carry a stale physical-return flag while still being Out for Delivery.
        # They must remain outside so shift closing and cash handover stay consistent.
        outside = (
            delivery_status in {"Out for Delivery", DELIVERY_RETURNING}
            or physical_status in {DRIVER_OUT, DRIVER_RETURNING}
        )
        if outside:
            output.append(
                frappe._dict(
                    {
                        "name": row.name,
                        "customer_name": row.customer_name or row.customer,
                        "grand_total": row.grand_total,
                        "status": delivery_status,
                        "driver_return_status": physical_status or DRIVER_OUT,
                    }
                )
            )
    return output


def _delivery_return_reversal_summary(invoice_name):
    """Return an item-level reversal summary for a Sales Invoice.

    The source invoice outstanding amount is not reliable until the database
    transaction that submits the Credit Note has committed.  Delivery return
    completion is therefore based on submitted return quantities against every
    original invoice row, including non-stock delivery-fee lines.
    """
    source_rows = frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": invoice_name, "parenttype": "Sales Invoice"},
        fields=["name", "item_code", "item_name", "qty", "rate", "amount"],
        order_by="idx asc",
        limit_page_length=2000,
    )

    returned_rows = frappe.db.sql(
        """
        select
            sii.sales_invoice_item as source_item,
            sum(abs(sii.qty)) as returned_qty
        from `tabSales Invoice Item` sii
        inner join `tabSales Invoice` si on si.name = sii.parent
        where si.docstatus = 1
          and si.is_return = 1
          and si.return_against = %s
          and ifnull(sii.sales_invoice_item, '') != ''
        group by sii.sales_invoice_item
        """,
        (invoice_name,),
        as_dict=True,
    )
    returned_by_source = {row.source_item: flt(row.returned_qty) for row in returned_rows}

    pending = []
    pending_amount = 0.0
    for row in source_rows:
        sold_qty = abs(flt(row.qty))
        returned_qty = min(sold_qty, flt(returned_by_source.get(row.name)))
        remaining_qty = max(0.0, sold_qty - returned_qty)
        if remaining_qty <= 1e-9:
            continue
        amount_per_unit = abs(flt(row.rate))
        remaining_amount = remaining_qty * amount_per_unit
        pending_amount += remaining_amount
        pending.append(
            frappe._dict(
                {
                    "source_item": row.name,
                    "item_code": row.item_code,
                    "item_name": row.item_name or row.item_code,
                    "sold_qty": sold_qty,
                    "returned_qty": returned_qty,
                    "remaining_qty": remaining_qty,
                    "remaining_amount": remaining_amount,
                }
            )
        )

    return frappe._dict(
        {
            "complete": not pending,
            "pending": pending,
            "pending_amount": flt(pending_amount, 2),
        }
    )


def _delivery_return_group_reversal_summary(invoice_name):
    """Aggregate reversal completion across the parent and all Add-on invoices."""
    parent, invoices = _delivery_group_invoices(invoice_name)
    pending = []
    pending_amount = 0.0
    summaries = {}
    for invoice in invoices:
        summary = _delivery_return_reversal_summary(invoice.name)
        summaries[invoice.name] = summary
        pending_amount += flt(summary.pending_amount)
        for row in summary.pending:
            item = frappe._dict(row)
            item.source_invoice = invoice.name
            pending.append(item)

    return frappe._dict(
        {
            "parent_invoice": parent.name,
            "invoices": [invoice.name for invoice in invoices],
            "complete": not pending,
            "pending": pending,
            "pending_amount": flt(pending_amount, 2),
            "summaries": summaries,
        }
    )


def _existing_credit_note(invoice_name):
    linked = ""
    if _has_field("Sales Invoice", RETURN_CREDIT_NOTE_FIELD):
        linked = frappe.db.get_value("Sales Invoice", invoice_name, RETURN_CREDIT_NOTE_FIELD) or ""
    if linked and frappe.db.exists("Sales Invoice", linked):
        return frappe.get_doc("Sales Invoice", linked)
    rows = frappe.get_all(
        "Sales Invoice",
        filters={
            "is_return": 1,
            "return_against": invoice_name,
            "docstatus": ["!=", 2],
        },
        fields=["name"],
        order_by="creation desc",
        limit_page_length=1,
    )
    return frappe.get_doc("Sales Invoice", rows[0].name) if rows else None


def create_return_credit_note(invoice_name):
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.docstatus != 1 or cint(invoice.get("is_return")):
        frappe.throw(_("الفاتورة الأصلية غير صالحة لإنشاء مرتجع."))
    if (invoice.get("custom_delivery_status") or "") != DELIVERY_RETURNED:
        frappe.throw(_("يجب أن يسجل الطيار الرجوع للصيدلية أولًا."))
    if (invoice.get(RETURN_STATUS_FIELD) or "") not in {RETURN_AWAITING_REVIEW, RETURN_CREDIT_NOTE_DRAFT}:
        frappe.throw(_("الأوردر ليس بانتظار مراجعة المرتجع."))

    existing = _existing_credit_note(invoice.name)
    if existing:
        # Keep the original delivery order in manager-review state until the
        # manager explicitly completes the return.  A submitted Credit Note is
        # therefore still linked here, but the final delivery status changes
        # only in complete_return_review().
        _set_if_field(invoice, RETURN_CREDIT_NOTE_FIELD, existing.name)
        _set_if_field(invoice, RETURN_STATUS_FIELD, RETURN_CREDIT_NOTE_DRAFT)
        _set_if_field(invoice, RETURN_REVIEWED_BY_FIELD, frappe.session.user)
        _set_if_field(invoice, RETURN_REVIEWED_AT_FIELD, now_datetime())
        invoice.flags.ignore_validate_update_after_submit = True
        invoice.save(ignore_permissions=True)
        return existing

    from erpnext.controllers.sales_and_purchase_return import make_return_doc

    return_doc = make_return_doc("Sales Invoice", invoice.name)
    if isinstance(return_doc, dict):
        return_doc = frappe.get_doc(return_doc)
    if _has_field("Sales Invoice", "custom_delivery_status"):
        return_doc.custom_delivery_status = DELIVERY_CANCELLED
    if _has_field("Sales Invoice", "custom_delivery_boy"):
        return_doc.custom_delivery_boy = ""
    if _has_field("Sales Invoice", DRIVER_RETURN_STATUS_FIELD):
        return_doc.set(DRIVER_RETURN_STATUS_FIELD, DRIVER_NOT_REQUIRED)
    if _has_field("Sales Invoice", RETURN_STATUS_FIELD):
        return_doc.set(RETURN_STATUS_FIELD, RETURN_COMPLETED)
    return_doc.flags.ignore_permissions = True
    return_doc.insert(ignore_permissions=True)

    _set_if_field(invoice, RETURN_CREDIT_NOTE_FIELD, return_doc.name)
    _set_if_field(invoice, RETURN_STATUS_FIELD, RETURN_CREDIT_NOTE_DRAFT)
    _set_if_field(invoice, RETURN_REVIEWED_BY_FIELD, frappe.session.user)
    _set_if_field(invoice, RETURN_REVIEWED_AT_FIELD, now_datetime())
    invoice.flags.ignore_validate_update_after_submit = True
    invoice.save(ignore_permissions=True)
    invoice.add_comment("Comment", _("تم إنشاء مسودة مرتجع المبيعات: {0}").format(return_doc.name))
    return return_doc



RECONCILIATION_TOLERANCE = 0.009


def _submitted_delivery_credit_notes(invoice_name):
    return frappe.get_all(
        "Sales Invoice",
        filters={
            "is_return": 1,
            "return_against": invoice_name,
            "docstatus": 1,
        },
        fields=["name", "posting_date", "grand_total", "outstanding_amount", "creation"],
        order_by="creation asc",
        limit_page_length=2000,
    )


def _submitted_delivery_group_credit_notes(invoice_name):
    parent, invoices = _delivery_group_invoices(invoice_name)
    rows = []
    for invoice in invoices:
        for row in _submitted_delivery_credit_notes(invoice.name):
            item = frappe._dict(row)
            item.source_invoice = invoice.name
            rows.append(item)
    rows.sort(key=lambda row: str(row.get("creation") or ""))
    return parent, invoices, rows


def _reconcile_credit_note_against_invoice(invoice_name, credit_note_name):
    """Allocate one submitted Credit Note against its original Sales Invoice.

    The implementation intentionally uses ERPNext's native Payment Reconciliation
    controller rather than editing outstanding amounts directly.  That preserves
    GL references and keeps the process safe to re-run.
    """
    target = frappe.get_doc("Sales Invoice", invoice_name)
    credit_note = frappe.get_doc("Sales Invoice", credit_note_name)

    if target.docstatus != 1 or cint(target.get("is_return")):
        frappe.throw(_("الفاتورة الأصلية غير صالحة للتسوية."))
    if credit_note.docstatus != 1 or not cint(credit_note.get("is_return")):
        frappe.throw(_("مرتجع المبيعات {0} يجب أن يكون معتمدًا أولًا.").format(credit_note_name))
    if credit_note.get("return_against") != target.name:
        frappe.throw(_("مرتجع المبيعات {0} غير مرتبط بالفاتورة الأصلية.").format(credit_note_name))

    target_outstanding = max(0.0, flt(target.outstanding_amount))
    credit_available = abs(min(0.0, flt(credit_note.outstanding_amount)))
    if target_outstanding <= RECONCILIATION_TOLERANCE or credit_available <= RECONCILIATION_TOLERANCE:
        return 0.0

    from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
        PaymentReconciliation,
    )

    reconciliation = PaymentReconciliation(
        {
            "doctype": "Payment Reconciliation",
            "company": target.company,
            "party_type": "Customer",
            "party": target.customer,
            "receivable_payable_account": target.debit_to,
            "invoice_name": target.name,
            "payment_name": credit_note.name,
            "invoice_limit": 50,
            "payment_limit": 50,
        }
    )
    reconciliation.get_unreconciled_entries()

    payment = next(
        (
            row
            for row in reconciliation.payments
            if row.reference_type == "Sales Invoice"
            and row.reference_name == credit_note.name
        ),
        None,
    )
    invoice = next(
        (
            row
            for row in reconciliation.invoices
            if row.invoice_type == "Sales Invoice"
            and row.invoice_number == target.name
        ),
        None,
    )

    # Another process may have already completed the allocation.  Treat that
    # as idempotent success instead of creating a duplicate reconciliation.
    if not payment or not invoice:
        target.reload()
        credit_note.reload()
        if (
            max(0.0, flt(target.outstanding_amount)) <= RECONCILIATION_TOLERANCE
            or abs(min(0.0, flt(credit_note.outstanding_amount))) <= RECONCILIATION_TOLERANCE
        ):
            return 0.0
        frappe.throw(
            _("تعذر العثور على أرصدة قابلة للتسوية بين {0} و{1}.").format(
                target.name, credit_note.name
            )
        )

    available = abs(flt(payment.get("unreconciled_amount") or payment.get("amount")))
    outstanding = abs(flt(invoice.outstanding_amount))
    amount = min(available, outstanding)
    if amount <= RECONCILIATION_TOLERANCE:
        return 0.0

    payment_data = payment.as_dict() if hasattr(payment, "as_dict") else dict(payment)
    invoice_data = invoice.as_dict() if hasattr(invoice, "as_dict") else dict(invoice)
    payment_data["amount"] = available
    payment_data["unreconciled_amount"] = available
    invoice_data["outstanding_amount"] = outstanding

    reconciliation.allocate_entries(
        {"payments": [payment_data], "invoices": [invoice_data]}
    )
    if not reconciliation.allocation:
        frappe.throw(
            _("تعذر تجهيز تسوية مرتجع المبيعات {0}.").format(credit_note.name)
        )

    allocation = reconciliation.allocation[0]
    allocation.amount = available
    allocation.unreconciled_amount = available
    allocation.allocated_amount = amount
    allocation.difference_amount = 0
    allocation.exchange_rate = allocation.exchange_rate or 1
    allocation.gain_loss_posting_date = payment.get("posting_date") or now_datetime().date()
    allocation.debit_or_credit_note_posting_date = payment.get("posting_date") or now_datetime().date()
    reconciliation.reconcile_allocations()
    return flt(amount, 2)


def _finalize_delivery_return(invoice_name, credit_note_name):
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.custom_delivery_status = DELIVERY_CANCELLED
    _set_if_field(invoice, RETURN_STATUS_FIELD, RETURN_COMPLETED)
    _set_if_field(invoice, RETURN_TYPE_FIELD, "Full Order Cancellation")
    _set_if_field(invoice, ACTIVE_RETURN_REQUEST_FIELD, "")
    _set_if_field(invoice, RETURN_CREDIT_NOTE_FIELD, credit_note_name)
    _set_if_field(invoice, RETURN_REVIEWED_BY_FIELD, frappe.session.user)
    _set_if_field(invoice, RETURN_REVIEWED_AT_FIELD, now_datetime())
    _set_if_field(invoice, DRIVER_RETURN_STATUS_FIELD, DRIVER_RETURNED)
    invoice.flags.ignore_validate_update_after_submit = True
    invoice.save(ignore_permissions=True)
    invoice.add_comment(
        "Comment",
        _("اكتملت مراجعة المرتجع والتسوية المالية. آخر مستند مرتجع: {0}.").format(
            credit_note_name
        ),
    )
    try:
        from pharma_erp.pharma_erp.delivery_partial_return import mark_full_request_completed
        mark_full_request_completed(invoice.name, credit_note_name)
    except Exception:
        raise
    return invoice


def _finalize_delivery_return_group(invoice_name, credit_note_name):
    """Finalize the parent and every Add-on invoice as one delivery order."""
    parent, invoices = _delivery_group_invoices(invoice_name)
    parent_notes = _submitted_delivery_credit_notes(parent.name)
    request_credit_note = parent_notes[-1].name if parent_notes else credit_note_name
    latest_group_note = credit_note_name

    for invoice in invoices:
        notes = _submitted_delivery_credit_notes(invoice.name)
        own_note = notes[-1].name if notes else ""
        if own_note:
            latest_group_note = own_note

        invoice = frappe.get_doc("Sales Invoice", invoice.name)
        invoice.custom_delivery_status = DELIVERY_CANCELLED
        _set_if_field(invoice, RETURN_STATUS_FIELD, RETURN_COMPLETED)
        _set_if_field(invoice, RETURN_TYPE_FIELD, "Full Order Cancellation")
        _set_if_field(invoice, ACTIVE_RETURN_REQUEST_FIELD, "")
        _set_if_field(invoice, RETURN_CREDIT_NOTE_FIELD, own_note or credit_note_name)
        _set_if_field(invoice, RETURN_REVIEWED_BY_FIELD, frappe.session.user)
        _set_if_field(invoice, RETURN_REVIEWED_AT_FIELD, now_datetime())
        _set_if_field(invoice, DRIVER_RETURN_STATUS_FIELD, DRIVER_RETURNED)
        invoice.flags.ignore_validate_update_after_submit = True
        invoice.save(ignore_permissions=True)

    parent = frappe.get_doc("Sales Invoice", parent.name)
    parent.add_comment(
        "Comment",
        _("اكتمل مرتجع مجموعة الدليفري بالكامل. آخر مستند مرتجع: {0}.").format(
            latest_group_note or credit_note_name
        ),
    )
    from pharma_erp.pharma_erp.delivery_partial_return import mark_full_request_completed
    mark_full_request_completed(parent.name, request_credit_note or latest_group_note or credit_note_name)
    return parent


@frappe.whitelist()
def reconcile_delivery_return(invoice_name, finalize=True):
    """Reconcile every submitted Credit Note in one delivery order group.

    Each Add-on invoice is a separate accounting document, so its Credit Note
    must be reconciled against that exact source invoice.  Operationally, the
    parent and Add-ons are finalized together only after all items in the group
    have been reversed and every positive outstanding balance is cleared.
    """
    source = frappe.get_doc("Sales Invoice", invoice_name)
    if source.docstatus != 1 or cint(source.get("is_return")):
        frappe.throw(_("الفاتورة الأصلية غير صالحة لتسوية مرتجع الدليفري."))

    parent, invoices, credit_notes = _submitted_delivery_group_credit_notes(source.name)
    reversal = _delivery_return_group_reversal_summary(parent.name)
    allocated_total = 0.0

    notes_by_source = {}
    for row in credit_notes:
        notes_by_source.setdefault(row.source_invoice, []).append(row)

    for invoice in invoices:
        for row in notes_by_source.get(invoice.name, []):
            current = frappe.get_doc("Sales Invoice", invoice.name)
            if max(0.0, flt(current.outstanding_amount)) <= RECONCILIATION_TOLERANCE:
                break
            allocated_total += _reconcile_credit_note_against_invoice(current.name, row.name)

    parent, invoices, credit_notes = _submitted_delivery_group_credit_notes(parent.name)
    positive_outstanding = sum(
        max(0.0, flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount") or 0))
        for invoice in invoices
    )
    unallocated_credit = sum(
        abs(min(0.0, flt(row.outstanding_amount))) for row in credit_notes
    )

    completed = False
    if cint(finalize) and reversal.complete and positive_outstanding <= RECONCILIATION_TOLERANCE:
        latest_credit_note = credit_notes[-1].name if credit_notes else ""
        if latest_credit_note:
            _finalize_delivery_return_group(parent.name, latest_credit_note)
            completed = True

    return {
        "invoice_name": parent.name,
        "group_invoices": [invoice.name for invoice in invoices],
        "allocated_amount": flt(allocated_total, 2),
        "original_outstanding": flt(positive_outstanding, 2),
        "unallocated_credit": flt(unallocated_credit, 2),
        "reversal_complete": bool(reversal.complete),
        "pending_return_amount": flt(reversal.pending_amount, 2),
        "completed": completed,
        "credit_notes": [row.name for row in credit_notes],
    }


def complete_return_review(invoice_name):
    parent, invoices, credit_notes = _submitted_delivery_group_credit_notes(invoice_name)
    if not credit_notes:
        frappe.throw(_("لم يتم العثور على مرتجع مبيعات معتمد مرتبط بالأوردر."))

    reversal = _delivery_return_group_reversal_summary(parent.name)
    if not reversal.complete:
        pending_labels = ", ".join(
            f"{row.item_code} [{row.source_invoice}] ({row.remaining_qty:g})"
            for row in reversal.pending[:8]
        )
        frappe.throw(
            _("لا يمكن إكمال المرتجع؛ ما زالت بنود من الفاتورة الأصلية أو الإضافات لم تُعكس بالكامل: {0}. القيمة المتبقية التقريبية: {1}.").format(
                pending_labels or _("بنود غير مكتملة"),
                frappe.utils.fmt_money(reversal.pending_amount, currency=parent.currency),
            )
        )

    reconciliation = reconcile_delivery_return(parent.name, finalize=False)
    parent, invoices = _delivery_group_invoices(parent.name)
    remaining = sum(
        max(0.0, flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount") or 0))
        for invoice in invoices
    )
    if remaining > RECONCILIATION_TOLERANCE:
        frappe.throw(
            _("المرتجع اكتمل من ناحية الأصناف، لكن ما زال على مجموعة الفواتير مبلغ {0}. لا تنشئ مرتجعًا جديدًا؛ راجع أرصدة الـCredit Notes المرتبطة.").format(
                frappe.utils.fmt_money(remaining, currency=parent.currency)
            )
        )

    _, _, credit_notes = _submitted_delivery_group_credit_notes(parent.name)
    latest_credit_note = credit_notes[-1].name
    parent = _finalize_delivery_return_group(parent.name, latest_credit_note)
    return {
        "invoice_name": parent.name,
        "group_invoices": [invoice.name for invoice in invoices],
        "credit_note": latest_credit_note,
        "credit_notes": [row.name for row in credit_notes],
        "delivery_status": DELIVERY_CANCELLED,
        "return_status": RETURN_COMPLETED,
        "reversal_complete": True,
        "reconciled_amount": flt(reconciliation.get("allocated_amount"), 2),
        "original_outstanding": flt(reconciliation.get("original_outstanding"), 2),
        "unallocated_credit": flt(reconciliation.get("unallocated_credit"), 2),
    }
