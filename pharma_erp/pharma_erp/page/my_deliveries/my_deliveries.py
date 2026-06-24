import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, nowdate

from pharma_erp.pharma_erp.delivery_collection import (
    COLLECTION_PROOF_FIELD,
    create_collection_payment_entry,
    validate_collection_proof,
)

from pharma_erp.pharma_erp.delivery_partial_return import (
    INVOICE_ACTIVE_REQUEST,
    INVOICE_LAST_REQUEST,
    INVOICE_RETURN_TYPE,
    RETURN_TYPE_PARTIAL,
    adjusted_expected_collection,
    annotate_orders as annotate_partial_return_orders,
    create_partial_return_request,
    get_active_request,
    get_partial_return_items,
)

from pharma_erp.pharma_erp.delivery_return_workflow import (
    DRIVER_RETURNED,
    DRIVER_RETURN_STATUS_FIELD,
    DRIVER_RETURNED_AT_FIELD,
    RETURN_STATUS_FIELD,
    RETURN_REASON_FIELD,
    RETURN_NOTES_FIELD,
    RETURN_CREDIT_NOTE_FIELD,
    mark_invoice_departed,
    mark_invoice_returned,
    mark_trip_departed,
    mark_trip_returned,
    request_customer_return,
)

from pharma_erp.pharma_erp.delivery_attempt import (
    ADD_ON_NOTES_FIELD,
    ADD_ON_STATUS_FIELD,
    ATTEMPT_COUNT_FIELD,
    CURRENT_ATTEMPT_FIELD,
    complete_delivery_attempt,
    finish_return_to_pharmacy,
    get_current_attempt,
    request_add_on_return,
    sales_invoice_has,
    start_delivery_attempt,
    sync_delivery_group,
)
from pharma_erp.pharma_erp.delivery_trip import (
    TRIP_FIELD,
    TRIP_STOP_ROW_FIELD,
    TRIP_STOP_SEQUENCE_FIELD,
    annotate_orders_with_trips,
    clear_invoice_trip_link,
    complete_trip_stop,
    get_active_trip_for_invoice,
    get_employee_trip_summaries,
    mark_trip_stop_returning,
    return_trip_to_pharmacy,
    start_trip,
)


ALLOWED_ROLES = {"Delivery", "System Manager"}
ADD_ON_CHECK_FIELD = "custom_add_on_delivery_invoice"
ADD_ON_PARENT_FIELD = "custom_parent_delivery_invoice"


def _has_field(fieldname):
    return sales_invoice_has(fieldname)


def _order_fields():
    fields = [
        "name",
        "customer",
        "customer_name",
        "contact_mobile",
        "contact_person",
        "customer_address",
        "address_display",
        "shipping_address_name",
        "shipping_address",
        "posting_date",
        "posting_time",
        "creation",
        "grand_total",
        "outstanding_amount",
        "currency",
        "company",
        "custom_delivery_boy",
        "custom_delivery_status",
        "custom_departure_time",
        "custom_delivery_time",
        "custom_duration_in_mins",
    ]
    if _has_field(ADD_ON_CHECK_FIELD):
        fields.append(ADD_ON_CHECK_FIELD)
    if _has_field(ADD_ON_PARENT_FIELD):
        fields.append(ADD_ON_PARENT_FIELD)
    for optional_field in (
        ADD_ON_STATUS_FIELD,
        ADD_ON_NOTES_FIELD,
        CURRENT_ATTEMPT_FIELD,
        ATTEMPT_COUNT_FIELD,
        "custom_add_on_requested",
        TRIP_FIELD,
        TRIP_STOP_ROW_FIELD,
        TRIP_STOP_SEQUENCE_FIELD,
        "custom_delivery_payment_timing",
        "custom_prepaid_amount",
        "custom_prepaid_method",
        "custom_prepaid_transaction_reference",
        "custom_prepaid_verification_status",
        "custom_prepaid_payment_entry",
        "custom_driver_reported_customer_payment_method",
        "custom_driver_reported_collected_amount",
        "custom_driver_collection_notes",
        "custom_driver_collection_reference",
        COLLECTION_PROOF_FIELD,
        "custom_delivery_card_pos_terminal",
        "custom_collection_declared_by",
        "custom_collection_declared_at",
        "custom_collection_verification_status",
        "custom_collection_received_by",
        "custom_confirmed_customer_payment_method",
        "custom_confirmed_collected_amount",
        "custom_collection_confirmed_at",
        "custom_collection_payment_entry",
        DRIVER_RETURN_STATUS_FIELD,
        DRIVER_RETURNED_AT_FIELD,
        RETURN_STATUS_FIELD,
        RETURN_REASON_FIELD,
        RETURN_NOTES_FIELD,
        RETURN_CREDIT_NOTE_FIELD,
        INVOICE_ACTIVE_REQUEST,
        INVOICE_LAST_REQUEST,
        INVOICE_RETURN_TYPE,
    ):
        if _has_field(optional_field):
            fields.append(optional_field)
    return fields


def _validate_page_access():
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not user_roles.intersection(ALLOWED_ROLES):
        frappe.throw(
            _("غير مسموح لك باستخدام صفحة أوردرات الدليفري."),
            frappe.PermissionError,
        )


def _get_current_employee():
    return frappe.db.get_value(
        "Employee",
        {"user_id": frappe.session.user, "status": "Active"},
        ["name", "employee_name", "user_id"],
        as_dict=True,
    )


def _enabled_card_terminals(company):
    return frappe.get_all(
        "Card POS Terminal",
        filters={
            "company": company,
            "enabled": 1,
        },
        fields=[
            "name",
            "terminal_name",
            "terminal_code",
            "bank_label",
        ],
        order_by=(
            "bank_label asc, "
            "terminal_name asc"
        ),
        limit_page_length=100,
    )


def _validate_delivery_card_terminal(
    company,
    terminal,
):
    terminal = str(terminal or "").strip()

    if not terminal:
        frappe.throw(
            _(
                "اختر ماكينة الفيزا التي استقبلت عملية الدفع."
            )
        )

    data = frappe.db.get_value(
        "Card POS Terminal",
        terminal,
        [
            "name",
            "company",
            "enabled",
        ],
        as_dict=True,
    )

    if (
        not data
        or data.company != company
        or not cint(data.enabled)
    ):
        frappe.throw(
            _(
                "ماكينة الفيزا المحددة غير صحيحة أو غير مفعلة."
            )
        )

    return terminal


@frappe.whitelist()
def get_my_delivery_card_terminals(
    invoice_name,
):
    _validate_page_access()
    employee = _get_current_employee()

    invoice = frappe.db.get_value(
        "Sales Invoice",
        invoice_name,
        [
            "company",
            "custom_delivery_boy",
        ],
        as_dict=True,
    )

    if not invoice:
        frappe.throw(_("الفاتورة غير موجودة."))

    if (
        "System Manager"
        not in frappe.get_roles(
            frappe.session.user
        )
        and (
            not employee
            or invoice.custom_delivery_boy
            != employee.name
        )
    ):
        frappe.throw(
            _("هذا الأوردر غير مخصص لك."),
            frappe.PermissionError,
        )

    return _enabled_card_terminals(
        invoice.company
    )


def _is_delivered_today(order):
    delivery_date = None
    if order.custom_delivery_time:
        delivery_date = getdate(order.custom_delivery_time)
    elif order.posting_date:
        delivery_date = getdate(order.posting_date)
    return delivery_date == getdate(nowdate())


def _remove_add_on_rows(rows):
    if not _has_field(ADD_ON_CHECK_FIELD):
        return rows
    return [row for row in rows if not cint(row.get(ADD_ON_CHECK_FIELD))]


def _delivery_group_invoices(parent_invoice):
    invoices = [parent_invoice]
    if not _has_field(ADD_ON_PARENT_FIELD):
        return invoices

    add_on_names = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            ADD_ON_PARENT_FIELD: parent_invoice.name,
        },
        pluck="name",
        order_by="creation asc",
        limit_page_length=500,
    )
    for name in add_on_names:
        invoices.append(frappe.get_doc("Sales Invoice", name))
    return invoices


def _delivery_group_outstanding(parent_invoice):
    return flt(
        sum(flt(invoice.outstanding_amount) for invoice in _delivery_group_invoices(parent_invoice)),
        6,
    )


def _require_collection_fields():
    required = (
        "custom_driver_reported_customer_payment_method",
        "custom_driver_reported_collected_amount",
        "custom_driver_collection_notes",
        "custom_driver_collection_reference",
        COLLECTION_PROOF_FIELD,
        "custom_delivery_card_pos_terminal",
        "custom_collection_declared_by",
        "custom_collection_declared_at",
        "custom_collection_verification_status",
        "custom_collection_received_by",
        "custom_confirmed_customer_payment_method",
        "custom_confirmed_collected_amount",
        "custom_collection_confirmed_by",
        "custom_collection_confirmed_at",
        "custom_collection_payment_entry",
    )
    missing = [fieldname for fieldname in required if not _has_field(fieldname)]
    if missing:
        frappe.throw(_("حقول تحصيل الدليفري غير مكتملة: {0}").format(", ".join(missing)))


def _attach_add_on_totals(orders):
    parent_names = [row.name for row in orders]
    add_ons_by_parent = {name: [] for name in parent_names}

    if parent_names and _has_field(ADD_ON_PARENT_FIELD):
        add_ons = frappe.get_all(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "is_return": 0,
                ADD_ON_PARENT_FIELD: ["in", parent_names],
            },
            fields=[
                "name",
                ADD_ON_PARENT_FIELD,
                "grand_total",
                "outstanding_amount",
            ],
            order_by="creation asc",
            limit_page_length=500,
        )
        for row in add_ons:
            add_ons_by_parent.setdefault(row.get(ADD_ON_PARENT_FIELD), []).append(row)

    for order in orders:
        add_ons = add_ons_by_parent.get(order.name, [])
        order["add_on_count"] = len(add_ons)
        order["add_on_invoices"] = [row.name for row in add_ons]
        order["group_grand_total"] = flt(
            flt(order.grand_total) + sum(flt(row.grand_total) for row in add_ons),
            6,
        )
        order["group_outstanding_amount"] = flt(
            flt(order.outstanding_amount)
            + sum(flt(row.outstanding_amount) for row in add_ons),
            6,
        )


@frappe.whitelist()
def get_my_deliveries():
    _validate_page_access()
    employee = _get_current_employee()

    if not employee:
        return {
            "employee": None,
            "orders": [],
            "trips": [],
            "message": _(
                "المستخدم الحالي غير مربوط بموظف نشط. "
                "اربط User داخل كارت Employee ثم أعد فتح الصفحة."
            ),
        }

    active_orders = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            "custom_order_type": "Home Delivery",
            "custom_delivery_boy": employee.name,
            "custom_delivery_status": [
                "in",
                [
                    "Ready for Delivery",
                    "Out for Delivery",
                    "Returning to Pharmacy",
                    "Returned to Pharmacy",
                ],
            ],
        },
        fields=_order_fields(),
        order_by="creation desc",
        limit_page_length=300,
    )
    active_orders = _remove_add_on_rows(active_orders)

    recent_delivered = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            "custom_order_type": "Home Delivery",
            "custom_delivery_boy": employee.name,
            "custom_delivery_status": "Delivered",
        },
        fields=_order_fields(),
        order_by="custom_delivery_time desc, creation desc",
        limit_page_length=200,
    )
    recent_delivered = _remove_add_on_rows(recent_delivered)
    delivered_today = [row for row in recent_delivered if _is_delivered_today(row)]

    orders = active_orders + delivered_today
    _attach_add_on_totals(orders)
    annotate_partial_return_orders(orders)
    order_trips = annotate_orders_with_trips(orders)
    employee_trips = get_employee_trip_summaries(employee.name, include_completed_today=True)
    trips_by_name = {trip.name: trip for trip in order_trips}
    for trip in employee_trips:
        trips_by_name[trip.name] = trip
    trips = sorted(
        trips_by_name.values(),
        key=lambda trip: str(trip.get("creation") or ""),
        reverse=True,
    )

    orders.sort(
        key=lambda order: str(
            order.custom_delivery_time
            or order.custom_departure_time
            or order.creation
            or ""
        ),
        reverse=True,
    )

    return {
        "employee": employee,
        "orders": orders,
        "trips": trips,
        "message": "",
    }


@frappe.whitelist()
def start_my_delivery_trip(trip_name):
    _validate_page_access()
    employee = _get_current_employee()
    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))
    result = start_trip(
        trip_name,
        employee=employee.name,
        delivery_user=frappe.session.user,
    )
    mark_trip_departed(trip_name)
    return result


@frappe.whitelist()
def return_my_delivery_trip(trip_name):
    _validate_page_access()
    employee = _get_current_employee()
    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))
    result = return_trip_to_pharmacy(trip_name, employee=employee.name)
    mark_trip_returned(trip_name)
    return result


@frappe.whitelist()
def update_my_delivery_status(invoice_name, new_status):
    _validate_page_access()
    employee = _get_current_employee()

    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))
    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))
    if not new_status:
        frappe.throw(_("الحالة الجديدة مطلوبة."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.docstatus != 1:
        frappe.throw(_("لا يمكن تحديث أوردر غير معتمد."))
    if invoice.custom_order_type != "Home Delivery":
        frappe.throw(_("الفاتورة المحددة ليست Home Delivery."))
    if _has_field(ADD_ON_CHECK_FIELD) and cint(invoice.get(ADD_ON_CHECK_FIELD)):
        frappe.throw(_("حدّث الأوردر من الفاتورة الأصلية."))
    if invoice.custom_delivery_boy != employee.name:
        frappe.throw(_("هذا الأوردر غير مخصص لك."), frappe.PermissionError)

    current_status = invoice.custom_delivery_status or ""
    allowed_transitions = {
        "Ready for Delivery": "Out for Delivery",
        "Out for Delivery": "Delivered",
    }
    expected_status = allowed_transitions.get(current_status)
    if expected_status != new_status:
        frappe.throw(
            _("لا يمكن نقل الأوردر من الحالة {0} إلى الحالة {1}.").format(
                current_status or "بدون حالة",
                new_status,
            )
        )

    active_trip = get_active_trip_for_invoice(invoice)

    if new_status == "Out for Delivery":
        if active_trip:
            frappe.throw(
                _("الأوردر ضمن الرحلة {0}. ابدأ الرحلة كاملة من بطاقة الرحلة.").format(
                    active_trip.name
                )
            )
        clear_invoice_trip_link(invoice)
        attempt = start_delivery_attempt(invoice, delivery_user=frappe.session.user)
        mark_invoice_departed(invoice)
        invoice.save(ignore_permissions=True)
        sync_delivery_group(
            invoice,
            "Out for Delivery",
            departure_time=invoice.get("custom_departure_time"),
        )
        return {
            "invoice_name": invoice.name,
            "delivery_status": invoice.custom_delivery_status,
            "departure_time": invoice.get("custom_departure_time"),
            "delivery_time": invoice.get("custom_delivery_time"),
            "duration_in_mins": invoice.get("custom_duration_in_mins"),
            "delivery_attempt": attempt.name if attempt else "",
        }

    group_outstanding = adjusted_expected_collection(invoice, _delivery_group_outstanding(invoice))
    if group_outstanding > 0.01:
        frappe.throw(
            _("يجب تسجيل طريقة الدفع والمبلغ المحصل قبل تأكيد تسليم الأوردر.")
        )

    if _has_field("custom_collection_verification_status"):
        invoice.set("custom_collection_verification_status", "Not Required")
    if _has_field("custom_collection_received_by"):
        invoice.set("custom_collection_received_by", "No Collection")
    if _has_field("custom_driver_reported_customer_payment_method"):
        invoice.set("custom_driver_reported_customer_payment_method", "No Collection")
    if _has_field("custom_driver_reported_collected_amount"):
        invoice.set("custom_driver_reported_collected_amount", 0)

    current_attempt = get_current_attempt(invoice)
    current_attempt_name = current_attempt.name if current_attempt else ""
    duration = complete_delivery_attempt(invoice)
    invoice.save(ignore_permissions=True)
    sync_delivery_group(
        invoice,
        "Delivered",
        delivery_time=invoice.get("custom_delivery_time"),
        duration=duration,
    )
    trip_result = complete_trip_stop(invoice, attempt_name=current_attempt_name)

    return {
        "invoice_name": invoice.name,
        "delivery_status": invoice.custom_delivery_status,
        "departure_time": invoice.get("custom_departure_time"),
        "delivery_time": invoice.get("custom_delivery_time"),
        "duration_in_mins": duration,
        "delivery_attempt": current_attempt_name,
        "delivery_trip": trip_result.name if trip_result else "",
    }


@frappe.whitelist()
def declare_my_delivery_collection(
    invoice_name,
    payment_method,
    collected_amount,
    reference=None,
    notes=None,
    card_pos_terminal=None,
    collection_proof=None,
):
    _validate_page_access()
    _require_collection_fields()
    employee = _get_current_employee()

    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.docstatus != 1 or invoice.custom_order_type != "Home Delivery":
        frappe.throw(_("الأوردر المحدد غير صالح للدليفري."))
    if invoice.custom_delivery_boy != employee.name:
        frappe.throw(_("هذا الأوردر غير مخصص لك."), frappe.PermissionError)
    if invoice.custom_delivery_status not in {"Out for Delivery", "Delivered"}:
        frappe.throw(_("لا يمكن تسجيل التحصيل في حالة الأوردر الحالية."))

    current_verification = invoice.get("custom_collection_verification_status") or ""
    if current_verification == "Confirmed":
        frappe.throw(_("تحصيل هذا الأوردر مؤكد بالفعل."))

    allowed_methods = {"Cash", "InstaPay", "Mobile Wallet", "Card", "Bank Transfer"}
    payment_method = str(payment_method or "").strip()
    if payment_method not in allowed_methods:
        frappe.throw(_("طريقة دفع العميل غير صحيحة."))

    group_invoices = _delivery_group_invoices(invoice)
    expected_amount = flt(
        sum(flt(group_invoice.outstanding_amount) for group_invoice in group_invoices),
        6,
    )
    expected_amount = adjusted_expected_collection(invoice, expected_amount)
    amount = flt(collected_amount, 6)

    if expected_amount <= 0:
        frappe.throw(_("لا يوجد مبلغ مطلوب تحصيله من العميل."))
    if amount <= 0:
        frappe.throw(_("المبلغ المحصل يجب أن يكون أكبر من صفر."))
    if amount > expected_amount + 0.01:
        frappe.throw(
            _("المبلغ المحصل لا يمكن أن يتجاوز المطلوب من العميل: {0}").format(
                frappe.format_value(expected_amount, {"fieldtype": "Currency"})
            )
        )

    reference = str(reference or "").strip()
    notes = str(notes or "").strip()
    if payment_method != "Cash" and not reference:
        frappe.throw(_("رقم العملية مطلوب في التحصيلات غير النقدية."))

    proof_url = validate_collection_proof(
        payment_method,
        collection_proof,
        invoice_name=invoice.name,
    )

    difference = flt(amount - expected_amount, 6)
    if payment_method == "Cash" and abs(difference) > 0.01 and not notes:
        frappe.throw(_("اكتب سبب فرق التحصيل النقدي في الملاحظات."))

    selected_terminal = ""
    if payment_method == "Card":
        selected_terminal = (
            _validate_delivery_card_terminal(
                invoice.company,
                card_pos_terminal,
            )
        )

    declared_at = now_datetime()
    invoice.set("custom_driver_reported_customer_payment_method", payment_method)
    invoice.set("custom_driver_reported_collected_amount", amount)
    invoice.set("custom_driver_collection_reference", reference)
    invoice.set(COLLECTION_PROOF_FIELD, proof_url)
    invoice.set("custom_driver_collection_notes", notes)
    if _has_field(
        "custom_delivery_card_pos_terminal"
    ):
        invoice.set(
            "custom_delivery_card_pos_terminal",
            selected_terminal,
        )
    invoice.set("custom_collection_declared_by", frappe.session.user)
    invoice.set("custom_collection_declared_at", declared_at)

    duration = flt(invoice.get("custom_duration_in_mins"), 6)
    attempt_name = invoice.get("custom_current_delivery_attempt") or ""
    trip_name = invoice.get(TRIP_FIELD) if _has_field(TRIP_FIELD) else ""

    if invoice.custom_delivery_status == "Out for Delivery":
        current_attempt = get_current_attempt(invoice)
        attempt_name = current_attempt.name if current_attempt else attempt_name
        duration = complete_delivery_attempt(invoice)
        invoice.save(ignore_permissions=True)
        sync_delivery_group(
            invoice,
            "Delivered",
            delivery_time=invoice.get("custom_delivery_time"),
            duration=duration,
        )
        trip_result = complete_trip_stop(invoice, attempt_name=attempt_name)
        trip_name = trip_result.name if trip_result else trip_name
    else:
        invoice.save(ignore_permissions=True)

    if payment_method == "Cash":
        payment_entry = create_collection_payment_entry(
            invoice,
            group_invoices,
            amount,
            payment_method,
            "Delivery Boy",
            reference_no=reference,
        )

        confirmed_at = now_datetime()
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {
                "custom_collection_verification_status": "Confirmed",
                "custom_collection_received_by": "Delivery Boy",
                "custom_confirmed_customer_payment_method": payment_method,
                "custom_confirmed_collected_amount": amount,
                "custom_collection_review_notes": notes,
                "custom_collection_difference": difference,
                "custom_collection_difference_reason": notes,
                "custom_collection_confirmed_by": frappe.session.user,
                "custom_collection_confirmed_at": confirmed_at,
                "custom_collection_payment_entry": payment_entry.name,
            },
            update_modified=False,
        )
        invoice.add_comment(
            "Comment",
            _(
                "تم تأكيد التحصيل النقدي تلقائيًا بقيمة {0} وإنشاء Payment Entry {1}. المبلغ أصبح عهدة على الطيار."
            ).format(
                frappe.format_value(amount, {"fieldtype": "Currency"}),
                payment_entry.name,
            ),
        )
        verification_status = "Confirmed"
        payment_entry_name = payment_entry.name
    else:
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            {
                "custom_collection_verification_status": "Awaiting Confirmation",
                "custom_collection_received_by": "Pharmacy Direct",
                "custom_confirmed_customer_payment_method": "",
                "custom_confirmed_collected_amount": 0,
                "custom_collection_review_notes": "",
                "custom_collection_difference": 0,
                "custom_collection_difference_reason": "",
                "custom_collection_confirmed_by": "",
                "custom_collection_confirmed_at": None,
                "custom_collection_payment_entry": "",
            },
            update_modified=False,
        )
        invoice.add_comment(
            "Comment",
            _(
                "أعلن الطيار دفع العميل {0} عن طريق {1}. "
                "تم إرفاق إثبات التحصيل، والحالة في انتظار تأكيد المدير."
            ).format(
                frappe.format_value(amount, {"fieldtype": "Currency"}),
                payment_method,
            ),
        )
        verification_status = "Awaiting Confirmation"
        payment_entry_name = ""

    return {
        "invoice_name": invoice.name,
        "delivery_status": "Delivered",
        "reported_method": payment_method,
        "reported_amount": amount,
        "expected_amount": expected_amount,
        "verification_status": verification_status,
        "payment_entry": payment_entry_name,
        "card_pos_terminal": selected_terminal,
        "collection_proof": proof_url,
        "duration_in_mins": duration,
        "delivery_attempt": attempt_name,
        "delivery_trip": trip_name or "",
    }


@frappe.whitelist()
def get_my_partial_return_items(invoice_name):
    _validate_page_access()
    employee = _get_current_employee()
    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.custom_delivery_boy != employee.name:
        frappe.throw(_("هذا الأوردر غير مخصص لك."), frappe.PermissionError)
    return get_partial_return_items(invoice_name)


@frappe.whitelist()
def request_my_partial_return(invoice_name, items, reason, notes=None):
    _validate_page_access()
    employee = _get_current_employee()
    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.custom_delivery_boy != employee.name:
        frappe.throw(_("هذا الأوردر غير مخصص لك."), frappe.PermissionError)
    return create_partial_return_request(
        invoice_name,
        items=items,
        reason=reason,
        notes=notes,
        actor=frappe.session.user,
    )


@frappe.whitelist()
def request_my_customer_return(invoice_name, reason, notes=None):
    _validate_page_access()
    employee = _get_current_employee()
    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.custom_delivery_boy != employee.name:
        frappe.throw(_("هذا الأوردر غير مخصص لك."), frappe.PermissionError)

    return request_customer_return(
        invoice,
        reason=reason,
        notes=notes,
        actor=frappe.session.user,
    )


@frappe.whitelist()
def mark_my_driver_returned(invoice_name):
    _validate_page_access()
    employee = _get_current_employee()
    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.docstatus != 1 or invoice.custom_order_type != "Home Delivery":
        frappe.throw(_("الأوردر المحدد غير صالح للدليفري."))
    if invoice.custom_delivery_boy != employee.name:
        frappe.throw(_("هذا الأوردر غير مخصص لك."), frappe.PermissionError)

    active_trip = get_active_trip_for_invoice(invoice)
    if active_trip:
        frappe.throw(
            _("الأوردر ضمن الرحلة {0}. سجّل رجوع الرحلة كاملة من بطاقة الرحلة.").format(
                active_trip.name
            )
        )

    mark_invoice_returned(invoice, save=True)
    return {
        "invoice_name": invoice.name,
        "delivery_status": invoice.custom_delivery_status,
        "driver_return_status": invoice.get(DRIVER_RETURN_STATUS_FIELD) or DRIVER_RETURNED,
        "driver_returned_at": invoice.get(DRIVER_RETURNED_AT_FIELD),
        "return_status": invoice.get(RETURN_STATUS_FIELD) or "",
    }


@frappe.whitelist()
def request_my_add_on_return(invoice_name, notes):
    _validate_page_access()
    employee = _get_current_employee()
    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.docstatus != 1 or invoice.custom_order_type != "Home Delivery":
        frappe.throw(_("الأوردر المحدد غير صالح للدليفري."))
    if invoice.custom_delivery_boy != employee.name:
        frappe.throw(_("هذا الأوردر غير مخصص لك."), frappe.PermissionError)

    attempt = request_add_on_return(
        invoice,
        notes,
        delivery_user=frappe.session.user,
    )
    invoice.save(ignore_permissions=True)
    trip_result = mark_trip_stop_returning(invoice, notes)

    return {
        "invoice_name": invoice.name,
        "delivery_status": invoice.custom_delivery_status,
        "add_on_status": invoice.get(ADD_ON_STATUS_FIELD) if _has_field(ADD_ON_STATUS_FIELD) else "",
        "delivery_attempt": attempt.name if attempt else "",
        "delivery_trip": trip_result.name if trip_result else "",
    }


@frappe.whitelist()
def mark_my_returned_to_pharmacy(invoice_name):
    _validate_page_access()
    employee = _get_current_employee()
    if not employee:
        frappe.throw(_("المستخدم الحالي غير مربوط بموظف نشط."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    if invoice.docstatus != 1 or invoice.custom_order_type != "Home Delivery":
        frappe.throw(_("الأوردر المحدد غير صالح للدليفري."))
    if invoice.custom_delivery_boy != employee.name:
        frappe.throw(_("هذا الأوردر غير مخصص لك."), frappe.PermissionError)

    active_trip = get_active_trip_for_invoice(invoice)
    if active_trip:
        frappe.throw(
            _("الأوردر ضمن الرحلة {0}. سجّل رجوع الرحلة كاملة من بطاقة الرحلة.").format(
                active_trip.name
            )
        )

    partial_request = get_active_request(invoice.name)
    if partial_request and partial_request.return_type == RETURN_TYPE_PARTIAL:
        # The sale itself is already delivered and the net collection may have
        # been recorded. This action only confirms that the driver physically
        # brought the rejected item back to the pharmacy.
        mark_invoice_returned(invoice, save=True)
        invoice.reload()
        return {
            "invoice_name": invoice.name,
            "delivery_status": invoice.custom_delivery_status,
            "delivery_return_status": invoice.get(RETURN_STATUS_FIELD) or "",
            "driver_return_status": invoice.get(DRIVER_RETURN_STATUS_FIELD) or "",
            "partial_return_request": partial_request.name,
            "add_on_status": invoice.get(ADD_ON_STATUS_FIELD) if _has_field(ADD_ON_STATUS_FIELD) else "",
            "delivery_attempt": "",
            "return_duration_mins": 0,
            "total_attempt_duration_mins": 0,
        }

    result = finish_return_to_pharmacy(invoice)
    invoice.save(ignore_permissions=True)

    return {
        "invoice_name": invoice.name,
        "delivery_status": invoice.custom_delivery_status,
        "add_on_status": invoice.get(ADD_ON_STATUS_FIELD) if _has_field(ADD_ON_STATUS_FIELD) else "",
        "delivery_attempt": result.attempt,
        "return_duration_mins": result.return_duration_mins,
        "total_attempt_duration_mins": result.total_attempt_duration_mins,
    }
