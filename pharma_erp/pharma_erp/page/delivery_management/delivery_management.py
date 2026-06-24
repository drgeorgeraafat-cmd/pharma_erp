import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate, today

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

from pharma_erp.pharma_erp.delivery_collection import (
    COLLECTION_PROOF_FIELD,
    create_collection_payment_entry,
    validate_collection_proof,
)

from pharma_erp.pharma_erp import payment_card_management as shift_finance

from pharma_erp.pharma_erp.delivery_partial_return import (
    INVOICE_ACTIVE_REQUEST,
    INVOICE_LAST_REQUEST,
    INVOICE_RETURN_TYPE,
    PARTIAL_RETURN_AWAITING,
    PARTIAL_CREDIT_NOTE_DRAFT,
    PARTIAL_RETURN_COMPLETED,
    RETURN_TYPE_PARTIAL,
    adjusted_expected_collection,
    annotate_orders as annotate_partial_return_orders,
    complete_partial_return_request,
    confirm_partial_return_received,
    create_partial_return_request,
    get_active_request,
    get_partial_return_items,
)

from pharma_erp.pharma_erp.delivery_return_workflow import (
    DRIVER_RETURN_STATUS_FIELD,
    DRIVER_RETURNED_AT_FIELD,
    RETURN_STATUS_FIELD,
    RETURN_REASON_FIELD,
    RETURN_NOTES_FIELD,
    RETURN_CREDIT_NOTE_FIELD,
    create_return_credit_note,
    complete_return_review,
    mark_invoice_departed,
    mark_trip_departed,
    mark_trip_returned,
    reopen_returned_order_for_redelivery,
)

from pharma_erp.pharma_erp.delivery_attempt import (
    ADD_ON_NOTES_FIELD,
    ADD_ON_STATUS_FIELD,
    ATTEMPT_COUNT_FIELD,
    CURRENT_ATTEMPT_FIELD,
    can_depart,
    cancel_add_on_request,
    complete_delivery_attempt,
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
    cancel_trip_stop_add_on_return,
    clear_invoice_trip_link,
    complete_trip_stop,
    create_trip,
    get_active_trip_for_invoice,
    get_trip_defaults,
    mark_trip_stop_returning,
    return_trip_to_pharmacy,
    recalculate_trip,
    start_trip,
)


ADD_ON_CHECK_FIELD = "custom_add_on_delivery_invoice"
ADD_ON_PARENT_FIELD = "custom_parent_delivery_invoice"


def _has_field(fieldname):
    return sales_invoice_has(fieldname)


PREPAID_METHOD_MODE_CANDIDATES = {
    "InstaPay": ("Insta Pay", "InstaPay"),
    "Mobile Wallet": ("Wallet", "Mobile Wallet"),
    "Card Payment Link": ("Credit Card", "Card"),
    "Bank Transfer": ("Bank Transfer",),
    "Cash at Pharmacy": ("Cash",),
    "Other": ("Other",),
}


COLLECTION_METHOD_MODE_CANDIDATES = {
    "Cash": ("Cash",),
    "InstaPay": ("Insta Pay", "InstaPay"),
    "Mobile Wallet": ("Wallet", "Mobile Wallet"),
    "Card": ("Credit Card", "Card"),
    "Bank Transfer": ("Bank Transfer",),
}


def _require_prepaid_fields():
    required = (
        "custom_delivery_payment_timing",
        "custom_prepaid_amount",
        "custom_prepaid_method",
        "custom_prepaid_transaction_reference",
        "custom_prepaid_payment_proof",
        "custom_prepaid_verification_status",
        "custom_prepaid_confirmed_by",
        "custom_prepaid_confirmed_at",
        "custom_prepaid_payment_entry",
    )
    missing = [fieldname for fieldname in required if not _has_field(fieldname)]
    if missing:
        frappe.throw(
            _("حقول الدفع المسبق غير مكتملة: {0}").format(", ".join(missing))
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
        "custom_collection_review_notes",
        "custom_collection_difference",
        "custom_collection_difference_reason",
        "custom_collection_confirmed_by",
        "custom_collection_confirmed_at",
        "custom_collection_payment_entry",
    )
    missing = [fieldname for fieldname in required if not _has_field(fieldname)]
    if missing:
        frappe.throw(_("حقول تحصيل الدليفري غير مكتملة: {0}").format(", ".join(missing)))


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


def _resolve_collection_mode_of_payment(customer_method):
    for candidate in COLLECTION_METHOD_MODE_CANDIDATES.get(
        customer_method, (customer_method,)
    ):
        if candidate and frappe.db.exists("Mode of Payment", candidate):
            return candidate
    frappe.throw(
        _("لا يوجد Mode of Payment مناسب لطريقة دفع العميل {0}.").format(
            customer_method or _("غير محددة")
        )
    )


def _collection_result(invoice_name):
    fields = [
        "name",
        "outstanding_amount",
        "custom_driver_reported_customer_payment_method",
        "custom_driver_reported_collected_amount",
        "custom_driver_collection_reference",
        "custom_driver_collection_notes",
        COLLECTION_PROOF_FIELD,
        "custom_delivery_card_pos_terminal",
        "custom_collection_verification_status",
        "custom_collection_received_by",
        "custom_confirmed_customer_payment_method",
        "custom_confirmed_collected_amount",
        "custom_collection_difference",
        "custom_collection_difference_reason",
        "custom_collection_confirmed_by",
        "custom_collection_confirmed_at",
        "custom_collection_payment_entry",
    ]
    return frappe.db.get_value("Sales Invoice", invoice_name, fields, as_dict=True)


def _validate_prepaid_invoice(invoice):
    if invoice.docstatus != 1:
        frappe.throw(_("يجب اعتماد الفاتورة أولًا."))
    if invoice.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("الدفع المسبق من صفحة الدليفري متاح لفواتير Home Delivery فقط."))
    if _has_field(ADD_ON_CHECK_FIELD) and cint(invoice.get(ADD_ON_CHECK_FIELD)):
        frappe.throw(_("سجّل الدفع المسبق من الفاتورة الأصلية."))
    if invoice.get("custom_delivery_status") in {"Out for Delivery", "Delivered"}:
        frappe.throw(_("لا يمكن تعديل الدفع المسبق بعد خروج الأوردر للتوصيل."))


def _resolve_mode_of_payment(prepaid_method):
    for candidate in PREPAID_METHOD_MODE_CANDIDATES.get(prepaid_method, (prepaid_method,)):
        if candidate and frappe.db.exists("Mode of Payment", candidate):
            return candidate
    frappe.throw(
        _("لا يوجد Mode of Payment مناسب لطريقة الدفع {0}. أنشئه أولًا.").format(
            prepaid_method or _("غير محددة")
        )
    )


def _mode_default_account(mode_of_payment, company):
    account = frappe.db.get_value(
        "Mode of Payment Account",
        {
            "parent": mode_of_payment,
            "parenttype": "Mode of Payment",
            "company": company,
        },
        "default_account",
    )
    if not account:
        frappe.throw(
            _("حدد Default Account للشركة {0} داخل Mode of Payment: {1}.").format(
                company, mode_of_payment
            )
        )
    return account


def _refresh_invoice_trip(invoice):
    trip = get_active_trip_for_invoice(invoice)
    if not trip:
        return
    recalculate_trip(trip, update_operational_status=False)
    if trip.docstatus == 1:
        trip.flags.ignore_validate_update_after_submit = True
    trip.save(ignore_permissions=True)


def _prepaid_result(invoice_name):
    fields = [
        "name",
        "outstanding_amount",
        "custom_delivery_payment_timing",
        "custom_prepaid_amount",
        "custom_prepaid_method",
        "custom_prepaid_transaction_reference",
        "custom_prepaid_payment_proof",
        "custom_prepaid_verification_status",
        "custom_prepaid_confirmed_by",
        "custom_prepaid_confirmed_at",
        "custom_prepaid_payment_entry",
    ]
    return frappe.db.get_value("Sales Invoice", invoice_name, fields, as_dict=True)


def _validate_management_access():
    if "System Manager" in frappe.get_roles(frappe.session.user):
        return
    if not frappe.has_permission("Sales Invoice", ptype="write"):
        frappe.throw(
            _("غير مسموح لك بإدارة رحلات التوصيل."),
            frappe.PermissionError,
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
            "clearing_account",
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
def get_delivery_card_terminals(invoice_name):
    _validate_management_access()

    company = frappe.db.get_value(
        "Sales Invoice",
        invoice_name,
        "company",
    )

    if not company:
        frappe.throw(_("الفاتورة غير موجودة."))

    return _enabled_card_terminals(company)


def _delivery_order_fields():
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
        "custom_prepaid_payment_proof",
        "custom_prepaid_verification_status",
        "custom_prepaid_confirmed_by",
        "custom_prepaid_confirmed_at",
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
        "custom_collection_review_notes",
        "custom_collection_difference",
        "custom_collection_difference_reason",
        "custom_collection_confirmed_by",
        "custom_collection_confirmed_at",
        "custom_collection_payment_entry",
        "custom_pharmacy_shift",
        "custom_delivery_shift",
        "custom_original_delivery_shift",
        "custom_last_delivery_transfer",
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


def _attach_add_on_totals(orders):
    parent_names = [row.name for row in orders]
    add_ons_by_parent = {name: [] for name in parent_names}

    if parent_names and _has_field(ADD_ON_PARENT_FIELD):
        fields = [
            "name",
            ADD_ON_PARENT_FIELD,
            "grand_total",
            "outstanding_amount",
            "docstatus",
        ]
        add_ons = frappe.get_all(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "is_return": 0,
                ADD_ON_PARENT_FIELD: ["in", parent_names],
            },
            fields=fields,
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
        order["can_depart"] = can_depart(order)


def _delivery_order_needs_operational_action(row):
    """Return True when an order must stay visible on the operational board.

    The shift-closing blockers intentionally inspect orders across dates.  The
    delivery board must use the same operational idea; otherwise an older order
    can block closing while being invisible to the manager.
    """
    delivery_status = str(row.get("custom_delivery_status") or "").strip()
    return_status = str(row.get(RETURN_STATUS_FIELD) or "").strip()

    if delivery_status not in shift_finance.FINAL_DELIVERY_STATUSES:
        return True

    if return_status and return_status not in {"Not Required", "Return Completed"}:
        return True

    return bool(str(row.get(INVOICE_ACTIVE_REQUEST) or "").strip())


@frappe.whitelist()
def get_delivery_orders():
    fields = _delivery_order_fields()

    # The live board is scoped to the currently active delivery shift, not to
    # posting date and not to every historical invoice with a stale status.
    # This also works when a shift crosses midnight.
    candidates = frappe.get_list(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            "custom_order_type": "Home Delivery",
        },
        fields=fields,
        order_by="creation desc",
        limit_page_length=5000,
    )

    by_name = {}
    active_shift_by_company = {}

    for row in candidates:
        # Add-on invoices are represented under the parent invoice and must
        # never appear as independent operational cards.
        if _has_field(ADD_ON_CHECK_FIELD) and cint(row.get(ADD_ON_CHECK_FIELD)):
            continue

        company = row.get("company") or ""
        if company not in active_shift_by_company:
            active_shift_by_company[company] = shift_finance._current_open_shift(company)

        active_shift = active_shift_by_company.get(company)
        current_delivery_shift = (
            row.get("custom_delivery_shift")
            or row.get("custom_pharmacy_shift")
            or ""
        )

        if not active_shift or current_delivery_shift != active_shift.name:
            continue

        by_name[row.name] = row

    orders = sorted(
        by_name.values(),
        key=lambda row: str(row.get("creation") or ""),
        reverse=True,
    )

    if _has_field(ADD_ON_CHECK_FIELD):
        orders = [row for row in orders if not cint(row.get(ADD_ON_CHECK_FIELD))]

    # The delivery board is an operational board. Fully completed returns and
    # cancelled delivery orders remain available in Sales Invoice/history
    # reports, but must not stay mixed with orders that still require action.
    orders = [
        row for row in orders
        if not (
            (
                str(row.get("custom_delivery_status") or "").strip() == "Cancelled"
                or str(row.get(RETURN_STATUS_FIELD) or "").strip() == "Return Completed"
            )
            and abs(flt(row.get("outstanding_amount") or 0)) <= 0.01
        )
    ]

    _attach_add_on_totals(orders)
    annotate_partial_return_orders(orders)

    # Keep the operational board consistent for legacy/test records whose
    # physical driver-return flag was left stale during earlier workflow versions.
    for order in orders:
        delivery_status = str(order.get("custom_delivery_status") or "").strip()
        physical_status = str(order.get(DRIVER_RETURN_STATUS_FIELD) or "").strip()
        if delivery_status == "Out for Delivery" and physical_status not in {
            "Driver Out",
            "Returning to Pharmacy",
        }:
            order[DRIVER_RETURN_STATUS_FIELD] = "Driver Out"
        elif delivery_status == "Returning to Pharmacy":
            order[DRIVER_RETURN_STATUS_FIELD] = "Returning to Pharmacy"

    employee_ids = list(
        {
            row.custom_delivery_boy
            for row in orders
            if row.custom_delivery_boy
        }
    )

    employee_names = {}
    if employee_ids:
        employees = frappe.get_all(
            "Employee",
            filters={"name": ["in", employee_ids]},
            fields=["name", "employee_name"],
        )
        employee_names = {
            employee.name: employee.employee_name
            for employee in employees
        }

    for order in orders:
        order["delivery_boy_name"] = employee_names.get(
            order.custom_delivery_boy,
            order.custom_delivery_boy or "",
        )

    trips = annotate_orders_with_trips(orders)

    active_shift_by_company = {}
    transferable_statuses = set(shift_finance.TRANSFERABLE_DELIVERY_STATUSES)
    for order in orders:
        company = order.get("company") or ""
        if company not in active_shift_by_company:
            active_shift_by_company[company] = shift_finance._current_open_shift(company)

        active_shift = active_shift_by_company.get(company)
        current_delivery_shift = (
            order.get("custom_delivery_shift")
            or order.get("custom_pharmacy_shift")
            or ""
        )
        status = str(order.get("custom_delivery_status") or "").strip()
        has_active_trip = bool(order.get("delivery_trip_active"))
        has_driver = bool(str(order.get("custom_delivery_boy") or "").strip())

        order["sales_shift"] = order.get("custom_pharmacy_shift") or ""
        order["current_delivery_shift"] = current_delivery_shift
        order["active_delivery_shift"] = active_shift.name if active_shift else ""
        order["can_transfer_to_active_shift"] = bool(
            active_shift
            and current_delivery_shift
            and active_shift.name != current_delivery_shift
            and status in transferable_statuses
            and not has_driver
            and not has_active_trip
        )

    return {
        "orders": orders,
        "trips": trips,
        "trip_defaults": get_trip_defaults(),
    }


@frappe.whitelist()
def transfer_order_to_active_shift(invoice_name, reason=None):
    _validate_management_access()

    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))

    required_fields = (
        "custom_pharmacy_shift",
        "custom_delivery_shift",
        "custom_original_delivery_shift",
        "custom_last_delivery_transfer",
    )
    missing_fields = [fieldname for fieldname in required_fields if not _has_field(fieldname)]
    if missing_fields:
        frappe.throw(
            _("حقول ربط الورديات غير مكتملة: {0}").format(", ".join(missing_fields))
        )

    if not frappe.db.exists("DocType", "Delivery Shift Transfer"):
        frappe.throw(_("Doctype باسم Delivery Shift Transfer غير موجود. شغّل تحديث V2.16 أولًا."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")

    if invoice.docstatus != 1:
        frappe.throw(_("لا يمكن نقل إلا فاتورة معتمدة."))
    if invoice.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("الفاتورة المحددة ليست Home Delivery."))
    if _has_field(ADD_ON_CHECK_FIELD) and cint(invoice.get(ADD_ON_CHECK_FIELD)):
        frappe.throw(_("انقل الأوردر من الفاتورة الأصلية، وسيتم نقل فواتير الإضافة معها تلقائيًا."))

    status = str(invoice.get("custom_delivery_status") or "").strip()
    if status not in set(shift_finance.TRANSFERABLE_DELIVERY_STATUSES):
        frappe.throw(
            _("لا يمكن نقل الأوردر في حالته الحالية: {0}").format(status or _("غير محددة"))
        )

    if str(invoice.get("custom_delivery_boy") or "").strip():
        frappe.throw(_("لا يمكن نقل الأوردر بعد تعيين طيار. ألغِ التعيين أولًا."))

    active_trip = get_active_trip_for_invoice(invoice)
    if active_trip:
        frappe.throw(
            _("لا يمكن نقل الأوردر لأنه موجود في الرحلة {0}.").format(active_trip.name)
        )

    current_delivery_shift = (
        invoice.get("custom_delivery_shift")
        or invoice.get("custom_pharmacy_shift")
        or ""
    )
    if not current_delivery_shift:
        frappe.throw(_("الأوردر غير مرتبط بوردية توصيل حالية."))

    active_shift = shift_finance._current_open_shift(invoice.company)
    if not active_shift:
        frappe.throw(_("لا توجد وردية Active حاليًا لنقل الأوردر إليها."))
    if active_shift.name == current_delivery_shift:
        frappe.throw(_("الأوردر مرتبط بالفعل بالوردية النشطة {0}.").format(active_shift.name))

    old_shift = frappe.get_doc("Pharmacy Shift Closing", current_delivery_shift)
    new_shift = frappe.get_doc("Pharmacy Shift Closing", active_shift.name)

    result = shift_finance._transfer_delivery_orders(
        old_shift=old_shift,
        new_shift=new_shift,
        invoice_names=[invoice.name],
        reason=reason or _("نقل أوردر غير معيّن لطيار إلى الوردية النشطة"),
    )

    if not result.get("transferred"):
        skipped = result.get("skipped") or []
        message = skipped[0].get("reason") if skipped else _("الأوردر لم يعد مؤهلًا للنقل.")
        frappe.throw(message)

    frappe.db.commit()
    return {
        "invoice": invoice.name,
        "from_shift": current_delivery_shift,
        "to_shift": active_shift.name,
        "sales_shift": invoice.get("custom_pharmacy_shift") or "",
        "transfers": result.get("transferred") or [],
    }


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def delivery_driver_query(
    doctype,
    txt,
    searchfield,
    start,
    page_len,
    filters,
):
    return frappe.db.sql(
        """
        SELECT DISTINCT
            employee.name,
            employee.employee_name
        FROM `tabEmployee` employee

        INNER JOIN `tabHas Role` user_role
            ON user_role.parent = employee.user_id
            AND user_role.parenttype = 'User'

        WHERE
            employee.status = 'Active'
            AND IFNULL(employee.user_id, '') != ''
            AND user_role.role = 'Delivery'
            AND (
                employee.name LIKE %(txt)s
                OR employee.employee_name LIKE %(txt)s
            )

        ORDER BY
            employee.employee_name ASC,
            employee.name ASC

        LIMIT %(start)s, %(page_len)s
        """,
        {
            "txt": f"%{txt}%",
            "start": int(start),
            "page_len": int(page_len),
        },
    )


def _sync_add_on_driver(parent_invoice, employee):
    if not _has_field(ADD_ON_PARENT_FIELD):
        return

    add_on_names = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            ADD_ON_PARENT_FIELD: parent_invoice,
        },
        pluck="name",
        limit_page_length=500,
    )

    parent_delivery_shift = ""
    if frappe.get_meta("Sales Invoice").has_field("custom_delivery_shift"):
        parent_delivery_shift = frappe.db.get_value(
            "Sales Invoice", parent_invoice, "custom_delivery_shift"
        ) or ""

    for name in add_on_names:
        add_on = frappe.get_doc("Sales Invoice", name)
        if _has_field("custom_delivery_boy"):
            add_on.custom_delivery_boy = employee
        if frappe.get_meta("Sales Invoice").has_field("delivery_boy"):
            add_on.delivery_boy = employee
        if parent_delivery_shift and frappe.get_meta("Sales Invoice").has_field("custom_delivery_shift"):
            add_on.custom_delivery_shift = parent_delivery_shift
            if (
                frappe.get_meta("Sales Invoice").has_field("custom_original_delivery_shift")
                and not add_on.get("custom_original_delivery_shift")
            ):
                add_on.custom_original_delivery_shift = parent_delivery_shift
        add_on.save(ignore_permissions=True)


@frappe.whitelist()
def assign_delivery_driver(invoice_name, employee):
    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))
    if not employee:
        frappe.throw(_("برجاء اختيار الطيار."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")

    if invoice.docstatus != 1:
        frappe.throw(_("لا يمكن تعيين طيار إلا لفاتورة معتمدة."))
    if invoice.custom_order_type != "Home Delivery":
        frappe.throw(_("الفاتورة المحددة ليست Home Delivery."))
    if _has_field(ADD_ON_CHECK_FIELD) and cint(invoice.get(ADD_ON_CHECK_FIELD)):
        frappe.throw(_("عيّن الطيار من الفاتورة الأصلية، وليس فاتورة الإضافة."))
    if invoice.custom_delivery_status in {"Delivered", "Returning to Pharmacy", "Returned to Pharmacy", "Cancelled"}:
        frappe.throw(_("لا يمكن تغيير الطيار بعد بدء دورة التوصيل أو المرتجع."))
    if invoice.custom_delivery_status == "Out for Delivery":
        frappe.throw(_("لا يمكن تغيير الطيار بعد خروج الأوردر للتوصيل."))
    active_trip = get_active_trip_for_invoice(invoice)
    if active_trip:
        frappe.throw(
            _("لا يمكن تغيير الطيار لأن الأوردر موجود في الرحلة {0}.").format(
                active_trip.name
            )
        )

    employee_doc = frappe.get_doc("Employee", employee)
    if employee_doc.status != "Active":
        frappe.throw(_("الطيار المحدد غير نشط."))
    if not employee_doc.user_id:
        frappe.throw(_("الموظف المحدد غير مربوط بمستخدم User."))

    has_delivery_role = frappe.db.exists(
        "Has Role",
        {
            "parent": employee_doc.user_id,
            "parenttype": "User",
            "role": "Delivery",
        },
    )
    if not has_delivery_role:
        frappe.throw(_("الموظف المحدد لا يمتلك Role باسم Delivery."))

    invoice.custom_delivery_boy = employee
    invoice.custom_delivery_status = "Ready for Delivery"
    if frappe.get_meta("Sales Invoice").has_field("custom_delivery_shift"):
        invoice.custom_delivery_shift = (
            invoice.get("custom_delivery_shift")
            or invoice.get("custom_pharmacy_shift")
        )
    if (
        frappe.get_meta("Sales Invoice").has_field("custom_original_delivery_shift")
        and not invoice.get("custom_original_delivery_shift")
    ):
        invoice.custom_original_delivery_shift = (
            invoice.get("custom_delivery_shift")
            or invoice.get("custom_pharmacy_shift")
        )
    invoice.save()
    _sync_add_on_driver(invoice.name, employee)

    return {
        "invoice_name": invoice.name,
        "employee": employee_doc.name,
        "employee_name": employee_doc.employee_name,
        "delivery_status": invoice.custom_delivery_status,
    }


@frappe.whitelist()
def request_manager_add_on_return(invoice_name, notes):
    """Register an add-on request received by the pharmacy while the order is outside.

    The manager records the requested items, and the existing delivery attempt is
    moved to the return-for-add-on flow. The add-on invoice itself is created only
    after the driver reaches the pharmacy.
    """
    _validate_management_access()

    invoice_name = str(invoice_name or "").strip()
    notes = str(notes or "").strip()
    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))
    if not notes:
        frappe.throw(_("اكتب الأصناف والكميات التي طلب العميل إضافتها."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")

    if invoice.docstatus != 1:
        frappe.throw(_("لا يمكن تسجيل طلب إضافة على فاتورة غير معتمدة."))
    if invoice.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("الفاتورة المحددة ليست أوردر دليفري."))
    if _has_field(ADD_ON_CHECK_FIELD) and cint(invoice.get(ADD_ON_CHECK_FIELD)):
        frappe.throw(_("سجّل طلب الإضافة من الفاتورة الأصلية، وليس فاتورة الإضافة."))
    if invoice.get("custom_delivery_status") != "Out for Delivery":
        frappe.throw(_("يمكن تسجيل طلب الإضافة من المدير فقط أثناء خروج الأوردر للتوصيل."))
    if not invoice.get("custom_delivery_boy"):
        frappe.throw(_("الأوردر غير معيّن لطيار."))

    active_return = get_active_request(invoice.name)
    if active_return:
        frappe.throw(
            _("يوجد طلب مرتجع نشط على الأوردر: {0}. أكمله أو ألغِه أولًا.").format(
                active_return.name
            )
        )

    current_add_on_status = (
        invoice.get(ADD_ON_STATUS_FIELD) if _has_field(ADD_ON_STATUS_FIELD) else ""
    ) or ""
    if current_add_on_status in {"Driver Returning", "Returned to Pharmacy"}:
        frappe.throw(_("يوجد بالفعل طلب إضافة جارٍ لهذا الأوردر."))

    attempt = request_add_on_return(
        invoice,
        notes,
        delivery_user=frappe.session.user,
    )
    invoice.flags.ignore_validate_update_after_submit = True
    invoice.save(ignore_permissions=True)
    trip_result = mark_trip_stop_returning(invoice, notes)

    invoice.add_comment(
        "Comment",
        _("سجّل مدير الشيفت طلب إضافة أصناف أثناء خروج الأوردر: {0}").format(notes),
    )

    return {
        "invoice_name": invoice.name,
        "delivery_status": invoice.get("custom_delivery_status"),
        "add_on_status": invoice.get(ADD_ON_STATUS_FIELD) if _has_field(ADD_ON_STATUS_FIELD) else "",
        "delivery_attempt": attempt.name if attempt else "",
        "delivery_trip": trip_result.name if trip_result else "",
    }


@frappe.whitelist()
def cancel_manager_add_on_request(invoice_name, reason=None):
    """Cancel a mistaken or customer-cancelled add-on request.

    The same delivery attempt resumes when the driver is still outside. After a
    physical return, the order becomes Ready for Delivery and the next departure
    creates a Manager Retry attempt.
    """
    _validate_management_access()

    invoice_name = str(invoice_name or "").strip()
    reason = str(reason or "").strip()
    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))
    if not reason:
        frappe.throw(_("سبب إلغاء طلب الإضافة مطلوب."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")

    if invoice.docstatus != 1:
        frappe.throw(_("لا يمكن تعديل طلب الإضافة على فاتورة غير معتمدة."))
    if invoice.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("الفاتورة المحددة ليست أوردر دليفري."))
    if _has_field(ADD_ON_CHECK_FIELD) and cint(invoice.get(ADD_ON_CHECK_FIELD)):
        frappe.throw(_("ألغِ طلب الإضافة من الفاتورة الأصلية."))

    add_on_status = (
        invoice.get(ADD_ON_STATUS_FIELD) if _has_field(ADD_ON_STATUS_FIELD) else ""
    ) or ""
    if add_on_status not in {"Driver Returning", "Returned to Pharmacy"}:
        frappe.throw(_("لا يوجد طلب إضافة جارٍ يمكن إلغاؤه."))

    active_return = get_active_request(invoice.name)
    if active_return:
        frappe.throw(
            _("يوجد طلب مرتجع نشط على الأوردر: {0}. أكمله أو ألغِه أولًا.").format(
                active_return.name
            )
        )

    draft_filters = {
        "docstatus": 0,
        "is_return": 0,
        ADD_ON_PARENT_FIELD: invoice.name,
    }
    if _has_field(ADD_ON_CHECK_FIELD):
        draft_filters[ADD_ON_CHECK_FIELD] = 1
    draft_add_on = frappe.db.get_value("Sales Invoice", draft_filters, "name")
    if draft_add_on:
        frappe.throw(
            _("توجد مسودة فاتورة إضافة {0}. احذفها أو اعتمدها قبل إلغاء الطلب.").format(
                draft_add_on
            )
        )

    original_status = add_on_status
    result = cancel_add_on_request(
        invoice,
        reason=reason,
        actor=frappe.session.user,
    )
    invoice.flags.ignore_validate_update_after_submit = True
    invoice.save(ignore_permissions=True)

    trip_result = None
    if original_status == "Driver Returning":
        trip_result = cancel_trip_stop_add_on_return(invoice)

    return {
        "invoice_name": invoice.name,
        "delivery_status": invoice.get("custom_delivery_status") or "",
        "add_on_status": invoice.get(ADD_ON_STATUS_FIELD) if _has_field(ADD_ON_STATUS_FIELD) else "",
        "mode": result.mode,
        "delivery_attempt": result.delivery_attempt,
        "delivery_trip": trip_result.name if trip_result else "",
    }


@frappe.whitelist()
def register_prepaid_payment(
    invoice_name,
    amount,
    prepaid_method,
    transaction_reference=None,
    payment_proof=None,
):
    _validate_management_access()
    _require_prepaid_fields()

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")
    _validate_prepaid_invoice(invoice)

    linked_payment = invoice.get("custom_prepaid_payment_entry")
    if linked_payment and frappe.db.exists("Payment Entry", linked_payment):
        linked_status = cint(frappe.db.get_value("Payment Entry", linked_payment, "docstatus"))
        if linked_status == 1:
            frappe.throw(_("الدفع المسبق مؤكد بالفعل في Payment Entry {0}.").format(linked_payment))

    amount = flt(amount, 6)
    outstanding = flt(invoice.outstanding_amount, 6)
    if amount <= 0:
        frappe.throw(_("مبلغ الدفع المسبق يجب أن يكون أكبر من صفر."))
    if amount > outstanding:
        frappe.throw(
            _("مبلغ الدفع المسبق لا يمكن أن يتجاوز المتبقي على الفاتورة: {0}").format(
                frappe.format_value(outstanding, {"fieldtype": "Currency"})
            )
        )

    prepaid_method = str(prepaid_method or "").strip()
    allowed_methods = set(PREPAID_METHOD_MODE_CANDIDATES)
    if prepaid_method not in allowed_methods:
        frappe.throw(_("طريقة الدفع المسبق غير صحيحة."))

    transaction_reference = str(transaction_reference or "").strip()
    if prepaid_method != "Cash at Pharmacy" and not transaction_reference:
        frappe.throw(_("رقم العملية مطلوب لهذه الطريقة."))

    timing = "Prepaid" if amount >= outstanding else "Partially Prepaid"
    values = {
        "custom_delivery_payment_timing": timing,
        "custom_prepaid_amount": amount,
        "custom_prepaid_method": prepaid_method,
        "custom_prepaid_transaction_reference": transaction_reference,
        "custom_prepaid_payment_proof": payment_proof or "",
        "custom_prepaid_verification_status": "Awaiting Confirmation",
        "custom_prepaid_confirmed_by": "",
        "custom_prepaid_confirmed_at": None,
        "custom_prepaid_payment_entry": "",
    }
    frappe.db.set_value("Sales Invoice", invoice.name, values)
    invoice.add_comment(
        "Comment",
        _("تم تسجيل دفع مسبق بقيمة {0} عن طريق {1} وينتظر التأكيد.").format(
            amount, prepaid_method
        ),
    )
    invoice.reload()
    _refresh_invoice_trip(invoice)
    return _prepaid_result(invoice.name)


@frappe.whitelist()
def confirm_prepaid_payment(invoice_name):
    _validate_management_access()
    _require_prepaid_fields()

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")
    _validate_prepaid_invoice(invoice)

    if invoice.get("custom_prepaid_verification_status") != "Awaiting Confirmation":
        frappe.throw(_("لا يوجد دفع مسبق في انتظار التأكيد."))

    amount = flt(invoice.get("custom_prepaid_amount"), 6)
    outstanding_before = flt(invoice.outstanding_amount, 6)
    if amount <= 0 or amount > outstanding_before:
        frappe.throw(_("مبلغ الدفع المسبق غير صالح مقارنة بالمتبقي الحالي على الفاتورة."))

    prepaid_method = invoice.get("custom_prepaid_method") or ""
    mode_of_payment = _resolve_mode_of_payment(prepaid_method)
    paid_to = _mode_default_account(mode_of_payment, invoice.company)

    payment_entry = get_payment_entry(
        "Sales Invoice",
        invoice.name,
        party_amount=amount,
        bank_account=paid_to,
        reference_date=nowdate(),
        ignore_permissions=True,
    )
    payment_entry.mode_of_payment = mode_of_payment
    payment_entry.paid_to = paid_to
    payment_entry.posting_date = nowdate()
    payment_entry.reference_no = (
        invoice.get("custom_prepaid_transaction_reference")
        or "PREPAID-{0}".format(invoice.name)
    )
    payment_entry.reference_date = nowdate()
    payment_entry.remarks = _("دفع مسبق لأوردر الدليفري {0} عن طريق {1}").format(
        invoice.name, prepaid_method
    )
    for reference in payment_entry.get("references") or []:
        if reference.reference_doctype == "Sales Invoice" and reference.reference_name == invoice.name:
            reference.allocated_amount = amount

    payment_entry.flags.ignore_permissions = True
    payment_entry.insert(ignore_permissions=True)
    payment_entry.submit()

    timing = "Prepaid" if amount >= outstanding_before else "Partially Prepaid"
    frappe.db.set_value(
        "Sales Invoice",
        invoice.name,
        {
            "custom_delivery_payment_timing": timing,
            "custom_prepaid_verification_status": "Confirmed",
            "custom_prepaid_confirmed_by": frappe.session.user,
            "custom_prepaid_confirmed_at": now_datetime(),
            "custom_prepaid_payment_entry": payment_entry.name,
        },
    )
    invoice.add_comment(
        "Comment",
        _("تم تأكيد الدفع المسبق وإنشاء Payment Entry {0}.").format(payment_entry.name),
    )
    invoice.reload()
    _refresh_invoice_trip(invoice)
    return _prepaid_result(invoice.name)


@frappe.whitelist()
def reject_prepaid_payment(invoice_name, reason=None):
    _validate_management_access()
    _require_prepaid_fields()

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")
    _validate_prepaid_invoice(invoice)

    if invoice.get("custom_prepaid_verification_status") != "Awaiting Confirmation":
        frappe.throw(_("لا يوجد دفع مسبق في انتظار الرفض."))

    frappe.db.set_value(
        "Sales Invoice",
        invoice.name,
        {
            "custom_prepaid_verification_status": "Rejected",
            "custom_prepaid_confirmed_by": "",
            "custom_prepaid_confirmed_at": None,
        },
    )
    invoice.add_comment(
        "Comment",
        _("تم رفض الدفع المسبق.{0}").format(
            " " + str(reason).strip() if reason else ""
        ),
    )
    invoice.reload()
    _refresh_invoice_trip(invoice)
    return _prepaid_result(invoice.name)


@frappe.whitelist()
def confirm_delivery_collection(
    invoice_name,
    confirmed_amount=None,
    reason=None,
    card_pos_terminal=None,
):
    _validate_management_access()
    _require_collection_fields()

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")
    if invoice.docstatus != 1 or invoice.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("الفاتورة المحددة ليست أوردر دليفري معتمد."))
    if _has_field(ADD_ON_CHECK_FIELD) and cint(invoice.get(ADD_ON_CHECK_FIELD)):
        frappe.throw(_("أكد التحصيل من الفاتورة الأصلية."))
    if invoice.get("custom_delivery_status") != "Delivered":
        frappe.throw(_("لا يمكن تأكيد التحصيل قبل تسليم الأوردر."))
    if invoice.get("custom_collection_verification_status") != "Awaiting Confirmation":
        frappe.throw(_("لا يوجد تحصيل في انتظار التأكيد."))

    reported_amount = flt(invoice.get("custom_driver_reported_collected_amount"), 6)
    amount = flt(confirmed_amount if confirmed_amount is not None else reported_amount, 6)
    if amount <= 0:
        frappe.throw(_("المبلغ المؤكد يجب أن يكون أكبر من صفر."))

    group_invoices = _delivery_group_invoices(invoice)
    expected_amount = flt(
        sum(flt(group_invoice.outstanding_amount) for group_invoice in group_invoices),
        6,
    )
    expected_amount = adjusted_expected_collection(invoice, expected_amount)
    if amount > expected_amount + 0.01:
        frappe.throw(
            _("المبلغ المؤكد لا يمكن أن يتجاوز المطلوب الحالي: {0}").format(
                frappe.format_value(expected_amount, {"fieldtype": "Currency"})
            )
        )

    difference = flt(amount - expected_amount, 6)
    reason = str(reason or "").strip()
    if abs(difference) > 0.01 and not reason:
        frappe.throw(_("يوجد فرق عن المطلوب. برجاء كتابة سبب الفرق."))

    customer_method = invoice.get("custom_driver_reported_customer_payment_method") or ""
    if customer_method not in COLLECTION_METHOD_MODE_CANDIDATES:
        frappe.throw(_("طريقة دفع العميل غير صحيحة."))

    validate_collection_proof(
        customer_method,
        invoice.get(COLLECTION_PROOF_FIELD),
        invoice_name=invoice.name,
    )

    reference_no = str(invoice.get("custom_driver_collection_reference") or "").strip()
    if customer_method != "Cash" and not reference_no:
        frappe.throw(_("رقم العملية مطلوب للتحصيل غير النقدي."))

    selected_terminal = ""
    if customer_method == "Card":
        selected_terminal = (
            _validate_delivery_card_terminal(
                invoice.company,
                card_pos_terminal
                or invoice.get(
                    "custom_delivery_card_pos_terminal"
                ),
            )
        )

    if _has_field(
        "custom_delivery_card_pos_terminal"
    ):
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            "custom_delivery_card_pos_terminal",
            selected_terminal,
            update_modified=False,
        )
        invoice.set(
            "custom_delivery_card_pos_terminal",
            selected_terminal,
        )

    received_by = "Delivery Boy" if customer_method == "Cash" else "Pharmacy Direct"
    payment_entry = create_collection_payment_entry(
        invoice,
        group_invoices,
        amount,
        customer_method,
        received_by,
        reference_no=reference_no,
    )

    confirmed_at = now_datetime()
    values = {
        "custom_collection_verification_status": "Confirmed",
        "custom_collection_received_by": received_by,
        "custom_confirmed_customer_payment_method": customer_method,
        "custom_confirmed_collected_amount": amount,
        "custom_collection_review_notes": reason,
        "custom_collection_difference": difference,
        "custom_collection_difference_reason": reason,
        "custom_collection_confirmed_by": frappe.session.user,
        "custom_collection_confirmed_at": confirmed_at,
        "custom_collection_payment_entry": payment_entry.name,
    }
    if _has_field(
        "custom_delivery_card_pos_terminal"
    ):
        values[
            "custom_delivery_card_pos_terminal"
        ] = selected_terminal
    frappe.db.set_value("Sales Invoice", invoice.name, values, update_modified=False)
    invoice.add_comment(
        "Comment",
        _("تم تأكيد التحصيل بقيمة {0} وإنشاء Payment Entry {1}.").format(
            frappe.format_value(amount, {"fieldtype": "Currency"}),
            payment_entry.name,
        ),
    )
    invoice.reload()
    _refresh_invoice_trip(invoice)
    return _collection_result(invoice.name)


@frappe.whitelist()
def reject_delivery_collection(invoice_name, reason):
    _validate_management_access()
    _require_collection_fields()

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")
    if invoice.get("custom_collection_verification_status") != "Awaiting Confirmation":
        frappe.throw(_("لا يوجد تحصيل في انتظار الاعتراض."))

    reason = str(reason or "").strip()
    if not reason:
        frappe.throw(_("سبب الاعتراض مطلوب."))

    frappe.db.set_value(
        "Sales Invoice",
        invoice.name,
        {
            "custom_collection_verification_status": "Disputed",
            "custom_collection_review_notes": reason,
            "custom_collection_difference_reason": reason,
            "custom_collection_confirmed_by": "",
            "custom_collection_confirmed_at": None,
        },
    )
    invoice.add_comment("Comment", _("تم الاعتراض على تحصيل الطيار: {0}").format(reason))
    return _collection_result(invoice.name)


@frappe.whitelist()
def get_manager_partial_return_items(invoice_name):
    """Return the invoice rows available for a manager-created partial return."""
    _validate_management_access()
    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))
    return get_partial_return_items(invoice_name)


@frappe.whitelist()
def create_manager_partial_return_request(invoice_name, items, reason, notes=None):
    """Register and approve a partial return while the driver is at the customer."""
    _validate_management_access()
    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))
    result = create_partial_return_request(
        invoice_name=invoice_name,
        items=items,
        reason=reason,
        notes=notes,
        actor=frappe.session.user,
        request_source="Shift Manager",
        approved_by=frappe.session.user,
    )
    frappe.db.commit()
    return result


@frappe.whitelist()
def confirm_delivery_return_received(invoice_name):
    """Persist the manager's physical receipt confirmation before POS return."""
    _validate_management_access()
    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")
    if invoice.docstatus != 1 or cint(invoice.get("is_return")):
        frappe.throw(_("الفاتورة الأصلية غير صالحة لإنشاء مرتجع."))
    if invoice.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("الفاتورة المحددة ليست أوردر دليفري."))

    partial_request = get_active_request(invoice.name)
    if partial_request and partial_request.return_type == RETURN_TYPE_PARTIAL:
        return confirm_partial_return_received(invoice.name)

    if str(invoice.get("custom_delivery_status") or "").strip() != "Returned to Pharmacy":
        frappe.throw(_("يجب أن يسجل الطيار الرجوع إلى الصيدلية أولًا."))
    if str(invoice.get(RETURN_STATUS_FIELD) or "").strip() != "Awaiting Manager Review":
        frappe.throw(_("الأوردر ليس بانتظار مراجعة المرتجع."))

    if _has_field("custom_delivery_return_reviewed_by"):
        invoice.set("custom_delivery_return_reviewed_by", frappe.session.user)
    if _has_field("custom_delivery_return_reviewed_at"):
        invoice.set("custom_delivery_return_reviewed_at", now_datetime())
    invoice.flags.ignore_validate_update_after_submit = True
    invoice.save(ignore_permissions=True)
    invoice.add_comment(
        "Comment",
        _("أكد مدير الشيفت استلام البضاعة المرتجعة، وتم تحويل إنشاء المرتجع إلى Pharmacy POS."),
    )
    return {
        "invoice_name": invoice.name,
        "delivery_status": invoice.get("custom_delivery_status"),
        "return_status": invoice.get(RETURN_STATUS_FIELD),
    }


@frappe.whitelist()
def create_delivery_return_credit_note(invoice_name):
    _validate_management_access()
    return_doc = create_return_credit_note(invoice_name)
    return {
        "invoice_name": invoice_name,
        "credit_note": return_doc.name,
        "credit_note_docstatus": return_doc.docstatus,
    }


@frappe.whitelist()
def complete_delivery_return(invoice_name):
    _validate_management_access()
    partial_request = get_active_request(invoice_name)
    if partial_request and partial_request.return_type == RETURN_TYPE_PARTIAL:
        return complete_partial_return_request(invoice_name, partial_request.name)
    return complete_return_review(invoice_name)


@frappe.whitelist()
def redeliver_returned_order(invoice_name, notes=None):
    """Cancel an unposted return request and prepare the same order for retry."""
    _validate_management_access()
    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))
    result = reopen_returned_order_for_redelivery(
        invoice_name=invoice_name,
        notes=notes,
        actor=frappe.session.user,
    )
    frappe.db.commit()
    return result


@frappe.whitelist()
def create_delivery_trip(
    invoice_names,
    vehicle=None,
    shift_reference=None,
    delivery_method=None,
):
    _validate_management_access()
    return create_trip(
        invoice_names,
        vehicle=vehicle,
        shift_reference=shift_reference,
        delivery_method=delivery_method,
    )


@frappe.whitelist()
def start_delivery_trip(trip_name):
    _validate_management_access()
    result = start_trip(trip_name)
    mark_trip_departed(trip_name)
    return result


@frappe.whitelist()
def return_delivery_trip(trip_name):
    _validate_management_access()
    result = return_trip_to_pharmacy(trip_name)
    mark_trip_returned(trip_name)
    return result


@frappe.whitelist()
def update_delivery_status(invoice_name, new_status):
    if not invoice_name:
        frappe.throw(_("رقم الفاتورة مطلوب."))
    if not new_status:
        frappe.throw(_("الحالة الجديدة مطلوبة."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    invoice.check_permission("write")

    if invoice.docstatus != 1:
        frappe.throw(_("لا يمكن تحديث حالة فاتورة غير معتمدة."))
    if invoice.custom_order_type != "Home Delivery":
        frappe.throw(_("الفاتورة المحددة ليست Home Delivery."))
    if _has_field(ADD_ON_CHECK_FIELD) and cint(invoice.get(ADD_ON_CHECK_FIELD)):
        frappe.throw(_("حدّث حالة الدليفري من الفاتورة الأصلية."))

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
                _("الأوردر ضمن الرحلة {0}. ابدأ الرحلة كاملة بدلًا من الأوردر منفردًا.").format(
                    active_trip.name
                )
            )
        if not invoice.custom_delivery_boy:
            frappe.throw(_("يجب تعيين الطيار قبل خروج الأوردر."))
        if not can_depart(invoice):
            frappe.throw(
                _("يجب إنشاء واعتماد فاتورة الإضافة قبل خروج الطيار مرة أخرى.")
            )
        clear_invoice_trip_link(invoice)
        attempt = start_delivery_attempt(invoice)
        mark_invoice_departed(invoice)
        invoice.save()
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

    group_outstanding = flt(
        sum(flt(group_invoice.outstanding_amount) for group_invoice in _delivery_group_invoices(invoice)),
        6,
    )
    group_outstanding = adjusted_expected_collection(invoice, group_outstanding)
    if group_outstanding > 0.01:
        frappe.throw(
            _("يجب أن يسجل الطيار طريقة الدفع والمبلغ المحصل قبل تأكيد التسليم.")
        )

    if _has_field("custom_collection_verification_status"):
        invoice.set("custom_collection_verification_status", "Not Required")
    if _has_field("custom_collection_received_by"):
        invoice.set("custom_collection_received_by", "No Collection")

    current_attempt = get_current_attempt(invoice)
    current_attempt_name = current_attempt.name if current_attempt else ""
    duration = complete_delivery_attempt(invoice)
    invoice.save()
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
