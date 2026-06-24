import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, nowdate

from erpnext.accounts.party import get_party_account

from pharma_erp.pharma_erp.delivery_return_workflow import (
    DRIVER_OUT,
    DRIVER_RETURNING,
    DRIVER_RETURN_STATUS_FIELD,
    driver_outside_orders,
)

COMPANY = "Cure"
CASH_ACCOUNT = "Cashier Till - C"
TOLERANCE = 0.01
SHIFT_STATE_FIELD = "custom_shift_operational_status"
SHIFT_CUTOFF_FIELD = "custom_sales_cutoff_at"
SHIFT_LINK_FIELD = "custom_pharmacy_shift"
SALES_SHIFT_FIELD = "custom_pharmacy_shift"
DELIVERY_SHIFT_FIELD = "custom_delivery_shift"
COLLECTION_SHIFT_FIELD = "custom_collection_shift"
CASH_DRAWER_FIELD = "custom_cash_drawer"
ACTIVE_SHIFT = "Active"
UNDER_REVIEW_SHIFT = "Under Review"
CLOSED_SHIFT = "Closed"
EMPLOYEE_SHORTAGE_ACCOUNT = "Employee Shortage - C"
CASH_SHORTAGE_EXPENSE_ACCOUNT = "Cash Shortage Expense - C"
CASH_OVERAGE_INCOME_ACCOUNT = "Cash Overage Income - C"
DELIVERY_TRANSIT_ACCOUNT = "Delivery Cash In Transit - C"
MAIN_SAFE_ACCOUNT = "Main Safe - C"
FINAL_CASH_MOVEMENT_TYPES = {
    "Transfer to Main Safe",
    "Return Opening Float",
    "Cash Sales Deposit",
    "Unused Till Refill Return",
    "Other Cash Return",
    "Approved Shift Cash Deposit",
}


# A delivery order blocks final shift approval until it reaches a final
# state or is transferred to another shift. Draft/blank statuses are active
# too because they represent orders that are still waiting for assignment.
FINAL_DELIVERY_STATUSES = {
    "Delivered",
    "Cancelled",
}

TRANSFERABLE_DELIVERY_STATUSES = {
    "",
    "Draft",
    "Waiting",
    "Pending",
    "Ready for Delivery",
}


def _money(value):
    return flt(value or 0, 6)


def _has_field(doctype, fieldname):
    return bool(frappe.get_meta(doctype).has_field(fieldname))


def _shift_operational_state(shift):
    state = ""

    if _has_field(
        "Pharmacy Shift Closing",
        SHIFT_STATE_FIELD,
    ):
        state = str(
            shift.get(SHIFT_STATE_FIELD) or ""
        ).strip()

    if (
        shift.get("docstatus") == 1
        or shift.get("status") == "Closed"
        or state == CLOSED_SHIFT
    ):
        return CLOSED_SHIFT

    if state == UNDER_REVIEW_SHIFT:
        return UNDER_REVIEW_SHIFT

    cutoff = (
        shift.get(SHIFT_CUTOFF_FIELD)
        if _has_field(
            "Pharmacy Shift Closing",
            SHIFT_CUTOFF_FIELD,
        )
        else None
    )

    if cutoff or shift.get("end_time"):
        return UNDER_REVIEW_SHIFT

    return ACTIVE_SHIFT


def _shift_list_fields():
    fields = [
        "name",
        "docstatus",
        "owner",
        "cashier",
        "company",
        "status",
        "start_time",
        "end_time",
        "opening_balance",
        "actual_cash",
        "creation",
    ]

    for fieldname in [
        SHIFT_STATE_FIELD,
        SHIFT_CUTOFF_FIELD,
        "custom_review_started_at",
        "custom_review_started_by",
        "custom_review_expected_cash",
        "custom_review_actual_cash",
        "custom_rollover_new_shift",
        "custom_rollover_new_opening_balance",
        "custom_rollover_net_safe_cash",
        "custom_review_cash_reference",
        "custom_cash_difference_resolution",
        "custom_cash_difference_employee",
        "custom_cash_difference_account",
        "custom_cash_difference_journal",
        "custom_final_posted_at",
        "custom_final_posted_by",
        CASH_DRAWER_FIELD,
    ]:
        if _has_field(
            "Pharmacy Shift Closing",
            fieldname,
        ):
            fields.append(fieldname)

    return fields


def _current_open_shift(company=None):
    filters = {"docstatus": 0}
    if company:
        filters["company"] = company

    rows = frappe.get_all(
        "Pharmacy Shift Closing",
        filters=filters,
        fields=_shift_list_fields(),
        order_by="creation desc",
        limit_page_length=200,
    )

    active_rows = [
        row
        for row in rows
        if _shift_operational_state(row)
        == ACTIVE_SHIFT
    ]

    for row in active_rows:
        if (
            row.cashier == frappe.session.user
            or row.owner == frappe.session.user
        ):
            return row

    return active_rows[0] if active_rows else None


def _under_review_shift_rows(company=None):
    filters = {"docstatus": 0}
    if company:
        filters["company"] = company

    rows = frappe.get_all(
        "Pharmacy Shift Closing",
        filters=filters,
        fields=_shift_list_fields(),
        order_by="modified desc",
        limit_page_length=200,
    )

    return [
        row
        for row in rows
        if _shift_operational_state(row)
        == UNDER_REVIEW_SHIFT
    ]


def _get_shift(
    shift_name=None,
    require_active=False,
):
    if shift_name:
        doc = frappe.get_doc(
            "Pharmacy Shift Closing",
            shift_name,
        )
    else:
        row = _current_open_shift()
        if not row:
            return None
        doc = frappe.get_doc(
            "Pharmacy Shift Closing",
            row.name,
        )

    state = _shift_operational_state(doc)

    if (
        doc.docstatus != 0
        or state == CLOSED_SHIFT
        or doc.status == "Closed"
    ):
        frappe.throw(_("This shift is closed."))

    if require_active and state != ACTIVE_SHIFT:
        frappe.throw(
            _(
                "This shift is under review and cannot receive new sales."
            )
        )

    return doc


def _shift_window(shift):
    start_time = get_datetime(
        shift.start_time or shift.creation
    )

    cutoff = None
    if _has_field(
        "Pharmacy Shift Closing",
        SHIFT_CUTOFF_FIELD,
    ):
        cutoff = shift.get(SHIFT_CUTOFF_FIELD)

    end_time = get_datetime(
        cutoff or shift.end_time
    ) if (cutoff or shift.end_time) else now_datetime()

    return start_time, end_time


def _find_shift_cash_movement(
    shift_name,
    movement_type,
):
    return frappe.db.get_value(
        "Shift Cash Movement",
        {
            "shift_reference": shift_name,
            "movement_type": movement_type,
            "docstatus": 1,
        },
        "name",
    )


def _opening_movement_name(shift):
    linked = (
        shift.get("opening_cash_movement")
        if _has_field(
            "Pharmacy Shift Closing",
            "opening_cash_movement",
        )
        else None
    )

    return linked or _find_shift_cash_movement(
        shift.name,
        "Opening Float",
    )


CLOSING_MOVEMENT_FIELDS = {
    "Return Opening Float": "opening_float_return_movement",
    "Cash Sales Deposit": "cash_sales_deposit_movement",
    "Unused Till Refill Return": "till_refill_return_movement",
    "Other Cash Return": "other_cash_return_movement",
}


def _closing_movement_names(shift):
    result = {}

    for movement_type, fieldname in CLOSING_MOVEMENT_FIELDS.items():
        linked = (
            shift.get(fieldname)
            if _has_field(
                "Pharmacy Shift Closing",
                fieldname,
            )
            else None
        )

        name = linked or frappe.db.get_value(
            "Shift Cash Movement",
            {
                "shift_reference": shift.name,
                "movement_type": movement_type,
                "docstatus": 1,
            },
            "name",
        )

        if name:
            result[movement_type] = name

    legacy = (
        shift.get("closing_cash_movement")
        if _has_field(
            "Pharmacy Shift Closing",
            "closing_cash_movement",
        )
        else None
    )

    legacy = legacy or frappe.db.get_value(
        "Shift Cash Movement",
        {
            "shift_reference": shift.name,
            "movement_type": "Transfer to Main Safe",
            "docstatus": 1,
        },
        "name",
    )

    if legacy and not result:
        result["Transfer to Main Safe"] = legacy

    return result


def _closing_movement_name(shift):
    movements = _closing_movement_names(shift)
    return next(iter(movements.values()), None)


MODE_OF_PAYMENT_ALIASES = {
    "InstaPay": "Insta Pay",
    "Insta Pay": "Insta Pay",
    "Mobile Wallet": "Wallet",
    "Wallet": "Wallet",
    "Card": "Credit Card",
    "Card Payment Link": "Credit Card",
    "Credit Card": "Credit Card",
    "Cash at Pharmacy": "Cash",
    "Cash": "Cash",
}


def _normalize_mode_of_payment(value):
    value = str(value or "").strip()
    return MODE_OF_PAYMENT_ALIASES.get(
        value,
        value or "Unknown",
    )


def _payment_channel(order_type):
    order_type = str(order_type or "").strip()

    if order_type == "Home Delivery":
        return "Delivery"

    if order_type == "Corporate":
        return "Corporate"

    return "Walk In"


def _normalize_payment_row(row):
    row = frappe._dict(row or {})
    row.mode_of_payment = _normalize_mode_of_payment(
        row.get("mode_of_payment")
    )
    row.channel = _payment_channel(
        row.get("order_type")
    )
    row.payment_source_type = (
        row.get("payment_source_type")
        or "Unknown"
    )
    row.payment_source_name = (
        row.get("payment_source_name")
        or row.get("payment_row_name")
        or ""
    )
    row.payment_source_key = (
        row.get("payment_row_name")
        or row.get("payment_source_name")
        or ""
    )
    row.invoice_total = _money(
        row.get("invoice_total")
    )
    row.outstanding_amount = _money(
        row.get("outstanding_amount")
    )
    row.amount = _money(row.get("amount"))
    row.card_pos_terminal = str(
        row.get("card_pos_terminal") or ""
    )
    row.reference_no = str(
        row.get("reference_no") or ""
    )
    row.destination_account = str(
        row.get("destination_account") or ""
    )
    return row



def _effective_delivery_shift(row):
    row = frappe._dict(row or {})
    return str(
        row.get(DELIVERY_SHIFT_FIELD)
        or row.get(SALES_SHIFT_FIELD)
        or ""
    ).strip()


def _all_delivery_cash_rows(delivery_boy=None):
    """Return all confirmed driver cash collections, regardless of shift.

    The shift that finally receives the money is determined by Delivery
    Handover allocations, not by the sales shift of the invoice.
    """
    invoice_meta = frappe.get_meta("Sales Invoice")

    order_type_expr = (
        "COALESCE(si.custom_order_type, '')"
        if invoice_meta.has_field("custom_order_type")
        else "''"
    )
    delivery_boy_expr = (
        "COALESCE(si.custom_delivery_boy, '')"
        if invoice_meta.has_field("custom_delivery_boy")
        else "''"
    )
    # A Sales Invoice contains only the latest collection-state fields, while
    # the same delivery order can legitimately have more than one collection
    # attempt after a returned order is sent again.  The destination account on
    # each posted payment is the durable source of truth for driver cash.
    sales_shift_expr = (
        f"COALESCE(si.{SALES_SHIFT_FIELD}, '')"
        if invoice_meta.has_field(SALES_SHIFT_FIELD)
        else "''"
    )
    delivery_shift_expr = (
        f"COALESCE(NULLIF(si.{DELIVERY_SHIFT_FIELD}, ''), NULLIF(si.{SALES_SHIFT_FIELD}, ''), '')"
        if invoice_meta.has_field(DELIVERY_SHIFT_FIELD)
        and invoice_meta.has_field(SALES_SHIFT_FIELD)
        else sales_shift_expr
    )

    if _has_field("Sales Invoice Payment", "reference_no"):
        sip_reference_expr = "COALESCE(sip.reference_no, '')"
    elif _has_field("Sales Invoice Payment", "reference"):
        sip_reference_expr = "COALESCE(sip.reference, '')"
    else:
        sip_reference_expr = "''"

    sip_rows = frappe.db.sql(
        f"""
        SELECT
            sip.name AS payment_row_name,
            'Sales Invoice Payment' AS payment_source_type,
            sip.name AS payment_source_name,
            '' AS payment_entry,
            sip.parent AS sales_invoice,
            si.customer,
            si.customer_name,
            si.creation AS transaction_time,
            {order_type_expr} AS order_type,
            {delivery_boy_expr} AS delivery_boy,
            'Delivery Boy' AS collection_received_by,
            'Cash' AS mode_of_payment,
            {sip_reference_expr} AS reference_no,
            COALESCE(sip.account, '') AS destination_account,
            {sales_shift_expr} AS sales_shift,
            {delivery_shift_expr} AS delivery_shift,
            ABS(sip.amount) AS amount,
            si.grand_total AS invoice_total,
            si.outstanding_amount,
            'Collection' AS transaction_type
        FROM `tabSales Invoice Payment` sip
        INNER JOIN `tabSales Invoice` si ON si.name = sip.parent
        WHERE si.docstatus = 1
          AND sip.mode_of_payment = 'Cash'
          AND {order_type_expr} = 'Home Delivery'
          AND COALESCE(sip.account, '') = %(delivery_transit_account)s
        ORDER BY si.creation ASC, sip.idx ASC
        """,
        {"delivery_transit_account": DELIVERY_TRANSIT_ACCOUNT},
        as_dict=True,
    )

    pe_rows = frappe.db.sql(
        f"""
        SELECT
            CONCAT('PE::', per.name) AS payment_row_name,
            'Payment Entry' AS payment_source_type,
            pe.name AS payment_source_name,
            pe.name AS payment_entry,
            per.reference_name AS sales_invoice,
            si.customer,
            si.customer_name,
            pe.creation AS transaction_time,
            {order_type_expr} AS order_type,
            {delivery_boy_expr} AS delivery_boy,
            'Delivery Boy' AS collection_received_by,
            pe.mode_of_payment,
            COALESCE(pe.reference_no, '') AS reference_no,
            COALESCE(pe.paid_to, '') AS destination_account,
            {sales_shift_expr} AS sales_shift,
            {delivery_shift_expr} AS delivery_shift,
            ABS(per.allocated_amount) AS amount,
            si.grand_total AS invoice_total,
            si.outstanding_amount,
            'Collection' AS transaction_type
        FROM `tabPayment Entry Reference` per
        INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent
        INNER JOIN `tabSales Invoice` si ON si.name = per.reference_name
        WHERE pe.docstatus = 1
          AND per.reference_doctype = 'Sales Invoice'
          AND si.docstatus = 1
          AND pe.mode_of_payment = 'Cash'
          AND {order_type_expr} = 'Home Delivery'
          AND COALESCE(pe.paid_to, '') = %(delivery_transit_account)s
        ORDER BY pe.creation ASC, pe.name ASC, per.idx ASC
        """,
        {"delivery_transit_account": DELIVERY_TRANSIT_ACCOUNT},
        as_dict=True,
    )

    rows = []
    seen = set()
    for raw in list(sip_rows) + list(pe_rows):
        row = _normalize_payment_row(raw)
        if delivery_boy and row.delivery_boy != delivery_boy:
            continue
        if not row.delivery_boy or _money(row.amount) <= TOLERANCE:
            continue
        if row.destination_account and row.destination_account != DELIVERY_TRANSIT_ACCOUNT:
            continue
        if row.payment_source_key in seen:
            continue
        seen.add(row.payment_source_key)
        row.sales_shift = str(row.get("sales_shift") or "")
        row.delivery_shift = str(row.get("delivery_shift") or row.sales_shift or "")
        row.original_amount = _money(row.amount)
        rows.append(row)

    rows.sort(
        key=lambda row: (
            get_datetime(row.transaction_time),
            row.payment_source_key,
        )
    )
    return rows


def _submitted_handover_allocations(shift_name=None, delivery_boy=None):
    if not frappe.db.exists("DocType", "Delivery Handover Allocation"):
        return []
    if not _has_field("Delivery Handover", "custom_allocations"):
        return []

    conditions = ["handover.docstatus = 1"]
    values = {}
    if shift_name:
        conditions.append(
            "COALESCE(NULLIF(handover.custom_collection_shift, ''), handover.shift_reference) = %(shift_name)s"
        )
        values["shift_name"] = shift_name
    if delivery_boy:
        conditions.append("handover.delivery_boy = %(delivery_boy)s")
        values["delivery_boy"] = delivery_boy

    return frappe.db.sql(
        f"""
        SELECT
            allocation.name,
            allocation.parent AS handover,
            handover.delivery_boy,
            COALESCE(NULLIF(handover.custom_collection_shift, ''), handover.shift_reference) AS collection_shift,
            allocation.payment_source_key,
            allocation.payment_entry,
            allocation.sales_invoice,
            allocation.allocation_type,
            allocation.amount,
            allocation.sales_shift,
            allocation.delivery_shift,
            allocation.transaction_time
        FROM `tabDelivery Handover Allocation` allocation
        INNER JOIN `tabDelivery Handover` handover
            ON handover.name = allocation.parent
        WHERE {' AND '.join(conditions)}
        ORDER BY handover.creation ASC, allocation.idx ASC
        """,
        values,
        as_dict=True,
    )


def _legacy_handover_events(delivery_boy=None):
    filters = {
        "handover_method": "Cash",
        "docstatus": 1,
    }
    if delivery_boy:
        filters["delivery_boy"] = delivery_boy

    handovers = frappe.get_all(
        "Delivery Handover",
        filters=filters,
        fields=[
            "name",
            "delivery_boy",
            "amount",
            "received_at",
            "shift_reference",
            "driver_shortage",
        ],
        order_by="received_at asc, creation asc",
        limit_page_length=100000,
    )

    allocated_parents = {
        row.handover for row in _submitted_handover_allocations()
    }
    events = []
    for handover in handovers:
        if handover.name in allocated_parents:
            continue
        shortage_amount = 0
        if handover.driver_shortage and frappe.db.exists("Driver Shortage", handover.driver_shortage):
            shortage_amount = _money(
                frappe.db.get_value(
                    "Driver Shortage",
                    handover.driver_shortage,
                    "shortage_amount",
                )
            )
        events.append(
            frappe._dict(
                {
                    "name": handover.name,
                    "delivery_boy": handover.delivery_boy,
                    "amount": _money(handover.amount) + shortage_amount,
                    "received_at": handover.received_at,
                    "shift_reference": handover.shift_reference,
                }
            )
        )
    return events


def _delivery_outstanding_rows(delivery_boy=None):
    rows = _all_delivery_cash_rows(delivery_boy)
    allocation_totals = {}
    for allocation in _submitted_handover_allocations(delivery_boy=delivery_boy):
        key = allocation.payment_source_key
        allocation_totals[key] = _money(
            allocation_totals.get(key, 0) + _money(allocation.amount)
        )

    for row in rows:
        row.allocated_amount = min(
            row.original_amount,
            _money(allocation_totals.get(row.payment_source_key, 0)),
        )
        row.remaining_amount = max(
            0,
            _money(row.original_amount - row.allocated_amount),
        )

    # Old handovers created before V2.16 have no allocation rows. Apply
    # their covered amount FIFO so they do not reappear as outstanding.
    by_driver = {}
    for row in rows:
        by_driver.setdefault(row.delivery_boy, []).append(row)

    for event in _legacy_handover_events(delivery_boy):
        credit = _money(event.amount)
        if credit <= TOLERANCE:
            continue
        driver_rows = by_driver.get(event.delivery_boy, [])
        event_time = get_datetime(event.received_at) if event.received_at else None
        eligible = [
            row
            for row in driver_rows
            if row.remaining_amount > TOLERANCE
            and (
                not event_time
                or get_datetime(row.transaction_time) <= event_time
            )
        ]
        if not eligible:
            eligible = [row for row in driver_rows if row.remaining_amount > TOLERANCE]
        for row in eligible:
            if credit <= TOLERANCE:
                break
            amount = min(credit, row.remaining_amount)
            row.allocated_amount = _money(row.allocated_amount + amount)
            row.remaining_amount = _money(row.remaining_amount - amount)
            credit = _money(credit - amount)

    return [row for row in rows if row.remaining_amount > TOLERANCE]


def _allocation_payload(row, amount, allocation_type, collection_shift):
    return {
        "payment_source_key": row.payment_source_key,
        "payment_entry": row.payment_entry or "",
        "sales_invoice": row.sales_invoice,
        "allocation_type": allocation_type,
        "amount": _money(amount),
        "sales_shift": row.get("sales_shift") or "",
        "delivery_shift": row.get("delivery_shift") or row.get("sales_shift") or "",
        "collection_shift": collection_shift,
        "transaction_time": row.transaction_time,
    }


def _build_delivery_allocations(delivery_boy, cash_amount, shortage_amount, collection_shift):
    outstanding = _delivery_outstanding_rows(delivery_boy)
    allocations = []

    for allocation_type, requested in (
        ("Cash Handover", _money(cash_amount)),
        ("Shortage", _money(shortage_amount)),
    ):
        remaining = requested
        for row in outstanding:
            if remaining <= TOLERANCE:
                break
            available = _money(row.remaining_amount)
            if available <= TOLERANCE:
                continue
            amount = min(available, remaining)
            allocations.append(
                _allocation_payload(
                    row,
                    amount,
                    allocation_type,
                    collection_shift,
                )
            )
            row.remaining_amount = _money(available - amount)
            remaining = _money(remaining - amount)

        if remaining > TOLERANCE:
            frappe.throw(
                _("The handover allocation exceeds the driver's outstanding collections.")
            )

    return allocations


def _refresh_payment_entry_collection_shifts(payment_entries):
    if not _has_field("Payment Entry", COLLECTION_SHIFT_FIELD):
        return

    all_rows = _all_delivery_cash_rows()
    totals = {}
    for row in all_rows:
        if row.payment_entry:
            totals[row.payment_entry] = _money(
                totals.get(row.payment_entry, 0) + row.original_amount
            )

    allocation_rows = _submitted_handover_allocations()
    by_payment = {}
    for row in allocation_rows:
        if row.payment_entry:
            by_payment.setdefault(row.payment_entry, []).append(row)

    for payment_entry in set(payment_entries or []):
        if not payment_entry or not frappe.db.exists("Payment Entry", payment_entry):
            continue
        rows = by_payment.get(payment_entry, [])
        allocated = _money(sum(_money(row.amount) for row in rows))
        total = _money(totals.get(payment_entry, 0))
        shifts = {row.collection_shift for row in rows if row.collection_shift}
        value = ""
        if total > TOLERANCE and allocated >= total - TOLERANCE and len(shifts) == 1:
            value = next(iter(shifts))
        frappe.db.set_value(
            "Payment Entry",
            payment_entry,
            COLLECTION_SHIFT_FIELD,
            value,
            update_modified=False,
        )


def _sales_invoice_payment_rows(shift):
    start_time, end_time = _shift_window(shift)

    order_type = (
        "COALESCE(si.custom_order_type, '')"
        if _has_field(
            "Sales Invoice",
            "custom_order_type",
        )
        else "''"
    )
    billing_type = (
        "COALESCE(si.custom_contract_billing_type, '')"
        if _has_field(
            "Sales Invoice",
            "custom_contract_billing_type",
        )
        else "''"
    )
    delivery_boy = (
        "COALESCE(si.custom_delivery_boy, '')"
        if _has_field(
            "Sales Invoice",
            "custom_delivery_boy",
        )
        else "''"
    )
    received_by = (
        "COALESCE(si.custom_collection_received_by, '')"
        if _has_field(
            "Sales Invoice",
            "custom_collection_received_by",
        )
        else "''"
    )
    terminal_expr = (
        "COALESCE(sip.custom_card_pos_terminal, '')"
        if _has_field(
            "Sales Invoice Payment",
            "custom_card_pos_terminal",
        )
        else "''"
    )
    invoice_shift_expr = (
        f"COALESCE(si.{SHIFT_LINK_FIELD}, '')"
        if _has_field(
            "Sales Invoice",
            SHIFT_LINK_FIELD,
        )
        else "''"
    )

    if _has_field(
        "Sales Invoice Payment",
        "reference_no",
    ):
        reference_expr = (
            "COALESCE(sip.reference_no, '')"
        )
    elif _has_field(
        "Sales Invoice Payment",
        "reference",
    ):
        reference_expr = (
            "COALESCE(sip.reference, '')"
        )
    else:
        reference_expr = "''"

    rows = frappe.db.sql(
        f"""
        SELECT
            sip.name AS payment_row_name,
            'Sales Invoice Payment' AS payment_source_type,
            sip.name AS payment_source_name,
            '' AS payment_entry,
            sip.parent AS sales_invoice,
            si.customer,
            si.customer_name,
            si.creation AS transaction_time,
            {order_type} AS order_type,
            {billing_type} AS contract_billing_type,
            {delivery_boy} AS delivery_boy,
            {received_by} AS collection_received_by,
            sip.mode_of_payment,
            {terminal_expr} AS card_pos_terminal,
            {reference_expr} AS reference_no,
            COALESCE(sip.account, '') AS destination_account,
            si.grand_total AS invoice_total,
            si.outstanding_amount,
            si.status AS payment_status,
            CASE
                WHEN si.is_return = 1
                    THEN -ABS(sip.amount)
                ELSE ABS(sip.amount)
            END AS amount,
            CASE
                WHEN si.is_return = 1
                    THEN 'Refund'
                ELSE 'Sale'
            END AS transaction_type
        FROM `tabSales Invoice Payment` sip
        INNER JOIN `tabSales Invoice` si
            ON si.name = sip.parent
        WHERE si.docstatus = 1
          AND (
                {invoice_shift_expr} = %(shift_name)s
                OR (
                    {invoice_shift_expr} = ''
                    AND si.creation >= %(start_time)s
                    AND si.creation <= %(end_time)s
                )
          )
        ORDER BY
            si.creation ASC,
            sip.idx ASC
        """,
        {
            "shift_name": shift.name,
            "start_time": start_time,
            "end_time": end_time,
        },
        as_dict=True,
    )

    return [
        _normalize_payment_row(row)
        for row in rows
    ]


def _payment_entry_rows(shift):
    start_time, end_time = _shift_window(shift)

    order_type = (
        "COALESCE(si.custom_order_type, '')"
        if _has_field("Sales Invoice", "custom_order_type")
        else "''"
    )
    billing_type = (
        "COALESCE(si.custom_contract_billing_type, '')"
        if _has_field("Sales Invoice", "custom_contract_billing_type")
        else "''"
    )
    delivery_boy = (
        "COALESCE(si.custom_delivery_boy, '')"
        if _has_field("Sales Invoice", "custom_delivery_boy")
        else "''"
    )
    received_by = (
        "COALESCE(si.custom_collection_received_by, '')"
        if _has_field("Sales Invoice", "custom_collection_received_by")
        else "''"
    )
    pe_terminal = (
        "COALESCE(pe.custom_card_pos_terminal, '')"
        if _has_field("Payment Entry", "custom_card_pos_terminal")
        else "''"
    )
    invoice_terminal = (
        "COALESCE(si.custom_delivery_card_pos_terminal, '')"
        if _has_field("Sales Invoice", "custom_delivery_card_pos_terminal")
        else "''"
    )
    terminal_expr = f"COALESCE(NULLIF({pe_terminal}, ''), NULLIF({invoice_terminal}, ''), '')"
    payment_shift_expr = (
        f"COALESCE(pe.{SHIFT_LINK_FIELD}, '')"
        if _has_field("Payment Entry", SHIFT_LINK_FIELD)
        else "''"
    )
    collection_shift_expr = (
        f"COALESCE(pe.{COLLECTION_SHIFT_FIELD}, '')"
        if _has_field("Payment Entry", COLLECTION_SHIFT_FIELD)
        else "''"
    )
    invoice_shift_expr = (
        f"COALESCE(si.{SHIFT_LINK_FIELD}, '')"
        if _has_field("Sales Invoice", SHIFT_LINK_FIELD)
        else "''"
    )
    delivery_shift_expr = (
        f"COALESCE(NULLIF(si.{DELIVERY_SHIFT_FIELD}, ''), NULLIF(si.{SHIFT_LINK_FIELD}, ''), '')"
        if _has_field("Sales Invoice", DELIVERY_SHIFT_FIELD)
        else invoice_shift_expr
    )

    rows = frappe.db.sql(
        f"""
        SELECT
            CONCAT('PE::', per.name) AS payment_row_name,
            'Payment Entry' AS payment_source_type,
            pe.name AS payment_source_name,
            pe.name AS payment_entry,
            per.reference_name AS sales_invoice,
            si.customer,
            si.customer_name,
            pe.creation AS transaction_time,
            {order_type} AS order_type,
            {billing_type} AS contract_billing_type,
            {delivery_boy} AS delivery_boy,
            {received_by} AS collection_received_by,
            pe.mode_of_payment,
            {terminal_expr} AS card_pos_terminal,
            COALESCE(pe.reference_no, '') AS reference_no,
            COALESCE(pe.paid_to, '') AS destination_account,
            {invoice_shift_expr} AS sales_shift,
            {delivery_shift_expr} AS delivery_shift,
            {collection_shift_expr} AS collection_shift,
            si.grand_total AS invoice_total,
            si.outstanding_amount,
            si.status AS payment_status,
            CASE
                WHEN pe.payment_type = 'Pay' OR si.is_return = 1
                    THEN -ABS(per.allocated_amount)
                ELSE ABS(per.allocated_amount)
            END AS amount,
            CASE
                WHEN pe.payment_type = 'Pay' OR si.is_return = 1
                    THEN 'Refund'
                ELSE 'Collection'
            END AS transaction_type
        FROM `tabPayment Entry Reference` per
        INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent
        INNER JOIN `tabSales Invoice` si ON si.name = per.reference_name
        WHERE pe.docstatus = 1
          AND per.reference_doctype = 'Sales Invoice'
          AND si.docstatus = 1
          AND (
                {collection_shift_expr} = %(shift_name)s
                OR (
                    {collection_shift_expr} = ''
                    AND (
                        {payment_shift_expr} = %(shift_name)s
                        OR {invoice_shift_expr} = %(shift_name)s
                        OR (
                            {payment_shift_expr} = ''
                            AND {invoice_shift_expr} = ''
                            AND pe.creation >= %(start_time)s
                            AND pe.creation <= %(end_time)s
                        )
                    )
                )
          )
        ORDER BY pe.creation ASC, pe.name ASC, per.idx ASC
        """,
        {
            "shift_name": shift.name,
            "start_time": start_time,
            "end_time": end_time,
        },
        as_dict=True,
    )
    return [_normalize_payment_row(row) for row in rows]


def _payment_rows(
    shift,
    mode_of_payment=None,
    terminal=None,
):
    rows = []
    rows.extend(
        _sales_invoice_payment_rows(shift)
    )
    rows.extend(
        _payment_entry_rows(shift)
    )

    if mode_of_payment:
        normalized_mode = (
            _normalize_mode_of_payment(
                mode_of_payment
            )
        )
        rows = [
            row
            for row in rows
            if row.mode_of_payment
            == normalized_mode
        ]

    if terminal:
        rows = [
            row
            for row in rows
            if row.card_pos_terminal
            == terminal
        ]

    rows.sort(
        key=lambda row: (
            get_datetime(row.transaction_time),
            row.payment_source_name,
            row.payment_row_name,
        )
    )

    return rows


def _monthly_claim_rows(shift):
    if not _has_field(
        "Sales Invoice",
        "custom_order_type",
    ):
        return []

    if not _has_field(
        "Sales Invoice",
        "custom_contract_billing_type",
    ):
        return []

    start_time, end_time = _shift_window(shift)
    invoice_shift_expr = (
        f"COALESCE(si.{SHIFT_LINK_FIELD}, '')"
        if _has_field(
            "Sales Invoice",
            SHIFT_LINK_FIELD,
        )
        else "''"
    )

    rows = frappe.db.sql(
        f"""
        SELECT
            CONCAT('CLAIM::', si.name)
                AS payment_row_name,
            'Contract Monthly Claim'
                AS payment_source_type,
            si.name
                AS payment_source_name,
            '' AS payment_entry,
            si.name AS sales_invoice,
            si.customer,
            si.customer_name,
            si.creation AS transaction_time,
            COALESCE(si.custom_order_type, '')
                AS order_type,
            COALESCE(
                si.custom_contract_billing_type,
                ''
            ) AS contract_billing_type,
            '' AS delivery_boy,
            '' AS collection_received_by,
            'Monthly Claim'
                AS mode_of_payment,
            '' AS card_pos_terminal,
            '' AS reference_no,
            '' AS destination_account,
            si.grand_total AS invoice_total,
            si.outstanding_amount,
            si.status AS payment_status,
            0 AS amount,
            'Claim' AS transaction_type
        FROM `tabSales Invoice` si
        WHERE si.docstatus = 1
          AND si.custom_order_type = 'Corporate'
          AND si.custom_contract_billing_type
              = 'Monthly Claim'
          AND (
                {invoice_shift_expr} = %(shift_name)s
                OR (
                    {invoice_shift_expr} = ''
                    AND si.creation >= %(start_time)s
                    AND si.creation <= %(end_time)s
                )
          )
        ORDER BY si.creation ASC
        """,
        {
            "shift_name": shift.name,
            "start_time": start_time,
            "end_time": end_time,
        },
        as_dict=True,
    )

    return [
        _normalize_payment_row(row)
        for row in rows
    ]


def _unbatched_card_rows(shift, terminal=None):
    rows = _payment_rows(shift, "Credit Card", terminal)
    if not rows:
        return []
    names = [row.payment_row_name for row in rows]
    used = set(
        row[0]
        for row in frappe.db.sql(
            """
            SELECT item.payment_row_name
            FROM `tabCard Settlement Batch Item` item
            INNER JOIN `tabCard Settlement Batch` batch
                ON batch.name = item.parent
            WHERE item.payment_row_name IN %(names)s
              AND batch.docstatus != 2
            """,
            {"names": tuple(names)},
        )
    )
    return [row for row in rows if row.payment_row_name not in used]


def _cash_ledger(shift):
    """
    Calculate drawer cash from shift-linked documents instead of GL
    creation time. This keeps an old Under Review shift isolated from
    a newer Active shift even though both use Cashier Till - C.
    """
    account = shift.get("cash_account") or CASH_ACCOUNT

    cash_sales_rows = [
        row
        for row in _payment_rows(shift, "Cash")
        if str(row.destination_account or "") == account
    ]
    cash_sales = _money(
        sum(_money(row.amount) for row in cash_sales_rows)
    )

    movement_rows = frappe.get_all(
        "Shift Cash Movement",
        filters={
            "shift_reference": shift.name,
            "docstatus": 1,
        },
        fields=[
            "name",
            "movement_type",
            "direction",
            "amount",
            "source_account",
            "target_account",
        ],
        limit_page_length=5000,
    )

    movement_in = 0.0
    movement_out = 0.0

    for row in movement_rows:
        if row.movement_type in FINAL_CASH_MOVEMENT_TYPES:
            continue

        amount = _money(row.amount)

        if (
            row.direction == "In"
            and row.target_account == account
        ):
            movement_in += amount

        if (
            row.direction == "Out"
            and row.source_account == account
        ):
            movement_out += amount

    employee_advances = _money(
        sum(
            _money(row.advance_amount)
            for row in frappe.get_all(
                "Employee Cash Advance",
                filters={
                    "shift_reference": shift.name,
                    "docstatus": 1,
                },
                fields=["advance_amount"],
                limit_page_length=5000,
            )
        )
    )

    opening_movement = _opening_movement_name(shift)
    legacy_opening = (
        0.0
        if opening_movement
        else _money(shift.opening_balance)
    )

    handover_filters = {
        "shift_reference": shift.name,
        "handover_method": "Cash",
        "docstatus": 1,
    }
    delivery_handover_cash = _money(
        sum(
            _money(row.amount)
            for row in frappe.get_all(
                "Delivery Handover",
                filters=handover_filters,
                fields=["amount"],
                limit_page_length=5000,
            )
        )
    )

    cash_in = _money(
        legacy_opening
        + movement_in
        + cash_sales
        + delivery_handover_cash
    )
    cash_out = _money(
        movement_out + employee_advances
    )
    expected_cash = _money(cash_in - cash_out)

    return {
        "account": account,
        "cash_in": cash_in,
        "cash_out": cash_out,
        "cash_sales": cash_sales,
        "movement_in": _money(movement_in),
        "movement_out": _money(movement_out),
        "employee_advances": employee_advances,
        "delivery_handover_cash": delivery_handover_cash,
        "net_movement": expected_cash,
        "expected_cash": expected_cash,
        "opening_cash_movement": opening_movement,
        "closing_cash_movement": _closing_movement_name(shift),
    }


def _payment_summary(shift):
    grouped = {}

    for row in _payment_rows(shift):
        mode = (
            row.mode_of_payment
            or "Unknown"
        )
        data = grouped.setdefault(
            mode,
            {
                "mode_of_payment": mode,
                "amount": 0,
                "source_keys": set(),
            },
        )
        data["amount"] += _money(
            row.amount
        )
        data["source_keys"].add(
            row.payment_source_key
            or row.payment_row_name
        )

    output = []

    for row in grouped.values():
        output.append(
            frappe._dict(
                {
                    "mode_of_payment": (
                        row["mode_of_payment"]
                    ),
                    "amount": _money(
                        row["amount"]
                    ),
                    "transaction_count": len(
                        row["source_keys"]
                    ),
                }
            )
        )

    return sorted(
        output,
        key=lambda value: (
            value.mode_of_payment
        ),
    )


def _terminal_summary(shift):
    terminals = frappe.get_all(
        "Card POS Terminal",
        filters={"company": shift.company or COMPANY, "enabled": 1},
        fields=[
            "name", "terminal_name", "terminal_code", "bank_label",
            "clearing_account", "destination_bank_account",
        ],
        order_by="bank_label asc, terminal_name asc",
        limit_page_length=500,
    )
    batches = frappe.get_all(
        "Card Settlement Batch",
        filters={"shift_reference": shift.name, "docstatus": ["!=", 2]},
        fields=[
            "name", "pos_terminal", "batch_number", "system_total", "machine_total",
            "difference", "status", "outstanding_amount", "docstatus", "close_time",
        ],
        order_by="creation desc",
        limit_page_length=1000,
    )
    by_terminal = {}
    for row in batches:
        by_terminal.setdefault(row.pos_terminal, []).append(row)
    output = []
    for terminal in terminals:
        rows = _unbatched_card_rows(shift, terminal.name)
        output.append(
            frappe._dict(
                {
                    **terminal,
                    "unbatched_count": len(rows),
                    "unbatched_total": _money(
                        sum(_money(row.amount) for row in rows)
                    ),
                    "batches": by_terminal.get(
                        terminal.name,
                        [],
                    ),
                }
            )
        )
    return output



def _outside_delivery_orders_for_shift(shift):
    """Orders whose driver has not physically returned for this delivery shift.

    Delivered orders are intentionally included until the driver presses
    "Returned to Pharmacy".  This keeps the operational trip open even when
    there is no cash to hand over (for example, prepaid deliveries).
    """
    if not shift:
        return []
    meta = frappe.get_meta("Sales Invoice")
    if not meta.has_field("custom_delivery_status") or not meta.has_field("custom_delivery_boy"):
        return []

    fields = [
        "name",
        "customer",
        "customer_name",
        "grand_total",
        "custom_delivery_status",
        "custom_delivery_boy",
        "creation",
    ]
    for fieldname in (DRIVER_RETURN_STATUS_FIELD, SALES_SHIFT_FIELD, DELIVERY_SHIFT_FIELD):
        if meta.has_field(fieldname):
            fields.append(fieldname)

    rows = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            "custom_order_type": "Home Delivery",
            "custom_delivery_boy": ["!=", ""],
        },
        fields=fields,
        order_by="creation asc",
        limit_page_length=5000,
    )

    output = []
    for row in rows:
        if _effective_delivery_shift(row) != shift.name:
            continue
        delivery_status = str(row.get("custom_delivery_status") or "").strip()
        physical_status = str(row.get(DRIVER_RETURN_STATUS_FIELD) or "").strip()
        is_outside = physical_status in {DRIVER_OUT, DRIVER_RETURNING}
        if not physical_status and delivery_status in {"Out for Delivery", "Returning to Pharmacy"}:
            is_outside = True
        if is_outside:
            output.append(row)
    return output


def _active_delivery_orders(shift=None, delivery_boy=None):
    meta = frappe.get_meta("Sales Invoice")
    if not meta.has_field("custom_delivery_status"):
        return []

    filters = {"docstatus": 1, "is_return": 0}
    if meta.has_field("custom_order_type"):
        filters["custom_order_type"] = "Home Delivery"
    if delivery_boy and meta.has_field("custom_delivery_boy"):
        filters["custom_delivery_boy"] = delivery_boy

    fields = [
        "name",
        "customer",
        "customer_name",
        "grand_total",
        "outstanding_amount",
        "custom_delivery_status",
        "creation",
        "posting_date",
        "posting_time",
    ]
    for fieldname in [
        "custom_delivery_boy",
        SALES_SHIFT_FIELD,
        DELIVERY_SHIFT_FIELD,
        "custom_original_delivery_shift",
    ]:
        if meta.has_field(fieldname):
            fields.append(fieldname)

    rows = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=fields,
        order_by="posting_date asc, posting_time asc, creation asc",
        limit_page_length=5000,
    )

    active = []
    for row in rows:
        status = str(row.custom_delivery_status or "").strip()
        if status in FINAL_DELIVERY_STATUSES:
            continue
        if shift and _effective_delivery_shift(row) != shift.name:
            continue
        active.append(row)
    return active


def _has_active_delivery_trip(invoice_name):
    if not frappe.db.exists("DocType", "Delivery Stop"):
        return False
    stop_meta = frappe.get_meta("Delivery Stop")
    invoice_field = None
    for candidate in ["custom_parent_delivery_invoice", "sales_invoice"]:
        if stop_meta.has_field(candidate):
            invoice_field = candidate
            break
    if not invoice_field:
        return False

    rows = frappe.get_all(
        "Delivery Stop",
        filters={invoice_field: invoice_name},
        fields=["parent"],
        limit_page_length=100,
    )
    parents = list({row.parent for row in rows if row.parent})
    if not parents:
        return False

    trips = frappe.get_all(
        "Delivery Trip",
        filters={
            "name": ["in", parents],
            "docstatus": ["!=", 2],
            "status": ["not in", ["Completed", "Cancelled"]],
        },
        pluck="name",
        limit_page_length=100,
    )
    return bool(trips)


def _transferable_delivery_orders(shift):
    rows = _active_delivery_orders(shift)
    output = []
    for row in rows:
        status = str(row.custom_delivery_status or "").strip()
        if status not in TRANSFERABLE_DELIVERY_STATUSES:
            continue
        if str(row.get("custom_delivery_boy") or "").strip():
            continue
        if _has_active_delivery_trip(row.name):
            continue
        output.append(row)
    return output


@frappe.whitelist()
def get_transferable_delivery_orders(shift_name):
    frappe.only_for("System Manager")
    shift = _get_shift(shift_name)
    rows = _transferable_delivery_orders(shift)
    return [
        {
            "invoice": row.name,
            "customer": row.customer_name or row.customer,
            "status": row.custom_delivery_status or "Draft",
            "amount": _money(row.grand_total),
            "sales_shift": row.get(SALES_SHIFT_FIELD) or "",
            "delivery_shift": _effective_delivery_shift(row),
        }
        for row in rows
    ]


def _expand_add_on_invoices(invoice_names):
    names = set(invoice_names or [])
    meta = frappe.get_meta("Sales Invoice")
    if not meta.has_field("custom_parent_delivery_invoice"):
        return list(names)

    queue = list(names)
    while queue:
        parent = queue.pop(0)
        children = frappe.get_all(
            "Sales Invoice",
            filters={
                "custom_parent_delivery_invoice": parent,
                "docstatus": 1,
            },
            pluck="name",
            limit_page_length=1000,
        )
        for child in children:
            if child not in names:
                names.add(child)
                queue.append(child)
    return list(names)


def _transfer_delivery_orders(old_shift, new_shift, invoice_names, reason=None):
    invoice_names = _expand_add_on_invoices(invoice_names)
    allowed = {row.name: row for row in _transferable_delivery_orders(old_shift)}
    transferred = []
    skipped = []
    reason = str(reason or "Shift rollover - unassigned delivery order").strip()

    for invoice_name in invoice_names:
        row = allowed.get(invoice_name)
        if not row:
            skipped.append({"invoice": invoice_name, "reason": "Order is no longer transferable."})
            continue

        original_delivery_shift = (
            row.get("custom_original_delivery_shift")
            or _effective_delivery_shift(row)
            or old_shift.name
        )
        transfer = frappe.new_doc("Delivery Shift Transfer")
        transfer.sales_invoice = invoice_name
        transfer.original_sales_shift = row.get(SALES_SHIFT_FIELD) or ""
        transfer.original_delivery_shift = original_delivery_shift
        transfer.from_delivery_shift = old_shift.name
        transfer.to_delivery_shift = new_shift.name
        transfer.delivery_status = row.custom_delivery_status or "Draft"
        transfer.transferred_by = frappe.session.user
        transfer.transferred_at = now_datetime()
        transfer.reason = reason
        transfer.flags.ignore_permissions = True
        transfer.insert(ignore_permissions=True)
        transfer.flags.ignore_permissions = True
        transfer.submit()

        values = {DELIVERY_SHIFT_FIELD: new_shift.name}
        if _has_field("Sales Invoice", "custom_original_delivery_shift"):
            values["custom_original_delivery_shift"] = original_delivery_shift
        if _has_field("Sales Invoice", "custom_last_delivery_transfer"):
            values["custom_last_delivery_transfer"] = transfer.name
        frappe.db.set_value("Sales Invoice", invoice_name, values, update_modified=False)
        transferred.append({"invoice": invoice_name, "transfer": transfer.name})

    return {"transferred": transferred, "skipped": skipped}


@frappe.whitelist()
def diagnose_pending_delivery_orders(shift_name):
    frappe.only_for("System Manager")

    shift = frappe.get_doc(
        "Pharmacy Shift Closing",
        shift_name,
    )
    rows = _active_delivery_orders(shift)

    return {
        "shift": shift.name,
        "active_count": len(rows),
        "orders": [
            {
                "invoice": row.name,
                "status": row.custom_delivery_status or "",
                "delivery_boy": row.custom_delivery_boy or "",
                "amount": _money(row.grand_total),
                "pharmacy_shift": row.get(SHIFT_LINK_FIELD) or "",
                "delivery_shift": _effective_delivery_shift(row),
            }
            for row in rows
        ],
        "ready": not bool(rows),
    }


def _driver_shortages_for_shift(
    shift,
    delivery_boy,
):
    if not frappe.db.exists(
        "DocType",
        "Driver Shortage",
    ):
        return []

    return frappe.get_all(
        "Driver Shortage",
        filters={
            "shift_reference": shift.name,
            "employee": delivery_boy,
            "docstatus": ["!=", 2],
        },
        fields=[
            "name",
            "shortage_amount",
            "docstatus",
            "creation",
        ],
        order_by="creation desc",
        limit_page_length=5000,
    )


def _delivery_cash_rows(shift, delivery_boy=None):
    rows = []

    for row in _payment_rows(shift, "Cash"):
        if row.channel != "Delivery":
            continue
        if not row.delivery_boy:
            continue
        if delivery_boy and row.delivery_boy != delivery_boy:
            continue
        if row.collection_received_by != "Delivery Boy":
            continue
        if _money(row.amount) <= TOLERANCE:
            continue
        if (
            row.destination_account
            and row.destination_account
            != "Delivery Cash In Transit - C"
        ):
            continue

        rows.append(row)

    return rows


def _delivery_settlement_for_driver(
    shift_name,
    delivery_boy,
):
    rows = frappe.get_all(
        "Delivery Settlement",
        filters={
            "shift_reference": shift_name,
            "delivery_boy": delivery_boy,
            "docstatus": ["!=", 2],
        },
        fields=[
            "name",
            "docstatus",
            "settlement_status",
            "total_expected",
            "total_handed_over",
            "remaining_with_driver",
            "pilot_float",
        ],
        order_by="docstatus asc, creation desc",
        limit_page_length=20,
    )

    return rows[0] if rows else None


def _delivery_driver_summaries(shift):
    outstanding_rows = _delivery_outstanding_rows()
    outstanding_by_driver = {}
    for row in outstanding_rows:
        outstanding_by_driver.setdefault(row.delivery_boy, []).append(row)

    handovers = frappe.get_all(
        "Delivery Handover",
        filters={
            "shift_reference": shift.name,
            "handover_method": "Cash",
            "docstatus": 1,
        },
        fields=[
            "name",
            "delivery_boy",
            "delivery_settlement",
            "handover_type",
            "amount",
            "driver_shortage",
            "received_at",
        ],
        order_by="creation asc",
        limit_page_length=5000,
    )
    handovers_by_driver = {}
    for row in handovers:
        handovers_by_driver.setdefault(row.delivery_boy, []).append(row)

    shortages = frappe.get_all(
        "Driver Shortage",
        filters={
            "shift_reference": shift.name,
            "docstatus": ["!=", 2],
        },
        fields=["name", "employee", "shortage_amount", "delivery_settlement"],
        limit_page_length=5000,
    ) if frappe.db.exists("DocType", "Driver Shortage") else []
    shortages_by_driver = {}
    for row in shortages:
        shortages_by_driver.setdefault(row.employee, []).append(row)

    settlements = frappe.get_all(
        "Delivery Settlement",
        filters={
            "shift_reference": shift.name,
            "docstatus": ["!=", 2],
        },
        fields=[
            "name",
            "delivery_boy",
            "docstatus",
            "settlement_status",
            "total_expected",
            "total_handed_over",
            "remaining_with_driver",
            "creation",
        ],
        order_by="creation desc",
        limit_page_length=5000,
    )
    settlement_by_driver = {}
    for row in settlements:
        settlement_by_driver.setdefault(row.delivery_boy, row)

    outside_shift_orders = _outside_delivery_orders_for_shift(shift)
    outside_by_driver = {}
    for row in outside_shift_orders:
        if row.custom_delivery_boy:
            outside_by_driver.setdefault(row.custom_delivery_boy, []).append(row)

    drivers = (
        set(outstanding_by_driver)
        | set(handovers_by_driver)
        | set(shortages_by_driver)
        | set(outside_by_driver)
    )
    employee_names = {
        row.name: row.employee_name
        for row in frappe.get_all(
            "Employee",
            filters={"name": ["in", list(drivers)]} if drivers else {"name": ""},
            fields=["name", "employee_name"],
            limit_page_length=5000,
        )
    } if drivers else {}

    output = []
    for delivery_boy in drivers:
        driver_outstanding = outstanding_by_driver.get(delivery_boy, [])
        driver_handovers = handovers_by_driver.get(delivery_boy, [])
        driver_shortages = shortages_by_driver.get(delivery_boy, [])
        settlement = settlement_by_driver.get(delivery_boy)

        outstanding_amount = _money(sum(_money(row.remaining_amount) for row in driver_outstanding))
        handed_over = _money(sum(_money(row.amount) for row in driver_handovers))
        shortage_amount = _money(sum(_money(row.shortage_amount) for row in driver_shortages))
        expected_amount = _money(outstanding_amount + handed_over + shortage_amount)
        remaining = max(0, _money(expected_amount - handed_over - shortage_amount))

        final_handover = next(
            (row for row in reversed(driver_handovers) if row.handover_type == "Final Settlement"),
            None,
        )
        settlement_finalized = bool(
            settlement
            and settlement.docstatus == 1
            and settlement.settlement_status in ("Settled", "Disputed")
        )
        active_orders = _active_delivery_orders(None, delivery_boy)
        # Global outside state prevents receiving this driver's cash in any
        # collection shift.  Shift-local outside rows also ensure prepaid or
        # zero-cash trips still appear and block their delivery shift.
        outside_orders = driver_outside_orders(delivery_boy)
        if not outside_orders and outside_by_driver.get(delivery_boy):
            outside_orders = [
                frappe._dict(
                    {
                        "name": row.name,
                        "customer_name": row.customer_name or row.customer,
                        "grand_total": row.grand_total,
                        "status": row.custom_delivery_status,
                        "driver_return_status": row.get(DRIVER_RETURN_STATUS_FIELD) or DRIVER_OUT,
                    }
                )
                for row in outside_by_driver.get(delivery_boy, [])
            ]
        can_receive_handover = not bool(outside_orders)
        final_submitted = bool(
            remaining <= TOLERANCE
            and not active_orders
            and can_receive_handover
            and (
                final_handover
                or settlement_finalized
                or outstanding_amount <= TOLERANCE
            )
        )

        output.append(
            frappe._dict(
                {
                    "delivery_boy": delivery_boy,
                    "employee_name": employee_names.get(delivery_boy, delivery_boy),
                    "expected_amount": expected_amount,
                    "handed_over_amount": handed_over,
                    "remaining_amount": remaining,
                    "final_submitted": 1 if final_submitted else 0,
                    "shortage_amount": shortage_amount,
                    "shortage": driver_shortages[0].name if driver_shortages else "",
                    "settlement": settlement.name if settlement else "",
                    "settlement_status": settlement.settlement_status if settlement else "Not Started",
                    "payment_count": len(driver_outstanding),
                    "active_order_count": len(active_orders),
                    "can_receive_handover": 1 if can_receive_handover else 0,
                    "driver_return_state": "At Pharmacy" if can_receive_handover else "Outside Pharmacy",
                    "outside_order_count": len(outside_orders),
                    "outside_orders": [
                        {
                            "name": row.name,
                            "customer_name": row.customer_name,
                            "grand_total": _money(row.grand_total),
                            "status": row.status,
                            "driver_return_status": row.driver_return_status,
                        }
                        for row in outside_orders
                    ],
                    "active_orders": [
                        {
                            "name": row.name,
                            "customer_name": row.customer_name or row.customer,
                            "grand_total": _money(row.grand_total),
                            "status": row.custom_delivery_status,
                            "delivery_shift": _effective_delivery_shift(row),
                        }
                        for row in active_orders
                    ],
                }
            )
        )

    output.sort(key=lambda row: (row.employee_name, row.delivery_boy))
    return output


def _ensure_delivery_settlement(shift, delivery_boy):
    outstanding_rows = _delivery_outstanding_rows(delivery_boy)
    outstanding_amount = _money(
        sum(_money(row.remaining_amount) for row in outstanding_rows)
    )

    current = _delivery_settlement_for_driver(shift.name, delivery_boy)
    if current and current.docstatus == 1:
        if outstanding_amount <= TOLERANCE:
            frappe.throw(
                _("Delivery Settlement {0} is already fully completed.").format(current.name)
            )
        current = None

    if current:
        doc = frappe.get_doc("Delivery Settlement", current.name)
    else:
        doc = frappe.new_doc("Delivery Settlement")
        doc.delivery_boy = delivery_boy
        doc.shift_reference = shift.name
        doc.pilot_float = 0
        doc.date = now_datetime()
        doc.settlement_status = "Open"
        if _has_field("Delivery Settlement", COLLECTION_SHIFT_FIELD):
            doc.set(COLLECTION_SHIFT_FIELD, shift.name)

    linked_handovers = frappe.get_all(
        "Delivery Handover",
        filters={
            "delivery_settlement": doc.name if not doc.is_new() else "__new__",
            "handover_method": "Cash",
            "docstatus": 1,
        },
        fields=["amount"],
        limit_page_length=5000,
    ) if not doc.is_new() else []
    handed_over = _money(sum(_money(row.amount) for row in linked_handovers))

    linked_shortage = _money(
        sum(
            _money(row.shortage_amount)
            for row in frappe.get_all(
                "Driver Shortage",
                filters={
                    "delivery_settlement": doc.name if not doc.is_new() else "__new__",
                    "docstatus": ["!=", 2],
                },
                fields=["shortage_amount"],
                limit_page_length=5000,
            )
        )
    ) if (not doc.is_new() and frappe.db.exists("DocType", "Driver Shortage")) else 0

    expected = _money(outstanding_amount + handed_over + linked_shortage)
    doc.set("invoices", [])
    for row in outstanding_rows:
        child = doc.append("invoices", {})
        child.invoice_number = row.sales_invoice
        child.customer_name = row.customer_name
        child.amount = row.remaining_amount
        child.mode_of_payment = "Cash"
        child.collection_received_by = "Delivery Boy"
        child.payment_entry = row.payment_entry
        child.confirmed_collection_amount = row.remaining_amount
        child.collection_status = "Confirmed"
        child.collected_at = row.transaction_time

    doc.total_expected = expected
    doc.total_collected_by_driver = expected
    doc.total_handed_over = handed_over
    doc.remaining_with_driver = max(0, _money(expected - handed_over - linked_shortage))
    doc.handover_count = len(linked_handovers)
    if handed_over > TOLERANCE:
        doc.settlement_status = "Partial Handover"

    doc.flags.ignore_permissions = True
    if doc.is_new():
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    return doc


def _ensure_driver_shortage(
    settlement,
    final_handover,
    expected_amount,
    handed_over_amount,
    reason,
):
    shortage_amount = max(
        0,
        _money(
            expected_amount - handed_over_amount
        ),
    )

    if shortage_amount <= TOLERANCE:
        return None

    existing = frappe.db.get_value(
        "Driver Shortage",
        {
            "delivery_settlement": settlement.name,
            "docstatus": ["!=", 2],
        },
        "name",
    )
    if existing:
        return frappe.get_doc(
            "Driver Shortage",
            existing,
        )

    shortage = frappe.new_doc(
        "Driver Shortage"
    )
    shortage.company = COMPANY
    shortage.employee = settlement.delivery_boy
    shortage.shift_reference = settlement.shift_reference
    shortage.delivery_settlement = settlement.name
    shortage.shortage_date = nowdate()
    shortage.currency = frappe.db.get_value(
        "Company",
        COMPANY,
        "default_currency",
    ) or "EGP"
    shortage.delivery_transit_account = (
        "Delivery Cash In Transit - C"
    )
    shortage.employee_shortage_account = (
        "Employee Shortage - C"
    )
    shortage.expected_amount = expected_amount
    shortage.handed_over_amount = handed_over_amount
    shortage.shortage_amount = shortage_amount
    shortage.recovered_amount = 0
    shortage.outstanding_amount = shortage_amount
    shortage.recovery_method = "Salary Deduction"
    shortage.reason = (
        reason
        or _(
            "Shortage recorded during final driver settlement."
        )
    )
    shortage.status = "Open"
    shortage.payroll_status = "Not Scheduled"
    shortage.delivery_handover = (
        final_handover.name
        if final_handover
        else ""
    )
    shortage.flags.ignore_permissions = True
    shortage.insert(ignore_permissions=True)

    # The shortage is approved and posted only when the shift review
    # is finally approved. Keeping it in Draft avoids posting balances
    # while the shift is still Under Review.

    if final_handover and _has_field(
        "Delivery Handover",
        "driver_shortage",
    ):
        frappe.db.set_value(
            "Delivery Handover",
            final_handover.name,
            "driver_shortage",
            shortage.name,
            update_modified=False,
        )

    return shortage


@frappe.whitelist()
def get_delivery_handover_summary(shift_name):
    frappe.only_for("System Manager")
    shift = _get_shift(shift_name)
    return _delivery_driver_summaries(shift)


@frappe.whitelist()
def submit_delivery_handover(shift_name, delivery_boy, handover_type, amount, notes=None):
    frappe.only_for("System Manager")
    shift = _get_shift(shift_name)

    if handover_type not in ("Partial Handover", "Final Settlement"):
        frappe.throw(_("Invalid handover type."))

    amount = _money(amount)
    notes = str(notes or "").strip()
    requested_handover_type = handover_type
    outside_orders = driver_outside_orders(delivery_boy)
    if outside_orders:
        order_list = ", ".join(row.name for row in outside_orders[:10])
        frappe.throw(
            _("لا يمكن استلام متحصلات الطيار قبل تسجيل رجوعه للصيدلية. الأوردرات المرتبطة بخروجه الحالي: {0}").format(
                order_list
            )
        )
    active_orders = _active_delivery_orders(None, delivery_boy)
    forced_partial = bool(handover_type == "Final Settlement" and active_orders)
    if forced_partial:
        handover_type = "Partial Handover"

    summary = next(
        (
            row
            for row in _delivery_driver_summaries(shift)
            if row.delivery_boy == delivery_boy
        ),
        None,
    )
    if not summary or summary.expected_amount <= TOLERANCE:
        frappe.throw(_("There are no confirmed cash collections for this driver."))

    outstanding_rows = _delivery_outstanding_rows(delivery_boy)
    remaining_before = _money(summary.remaining_amount)
    if handover_type == "Partial Handover" and remaining_before <= TOLERANCE:
        frappe.throw(_("There is no remaining cash to receive as a partial handover."))
    if amount < 0:
        frappe.throw(_("Amount cannot be negative."))
    if amount - remaining_before > TOLERANCE:
        frappe.throw(_("Collected amount cannot exceed the amount remaining with the driver."))
    if handover_type == "Partial Handover" and amount <= TOLERANCE:
        frappe.throw(_("Partial handover amount must be greater than zero."))
    if handover_type == "Final Settlement" and amount < remaining_before - TOLERANCE and not notes:
        frappe.throw(_("Enter the reason for the shortage before final settlement."))

    settlement = _ensure_delivery_settlement(shift, delivery_boy)
    shortage_to_allocate = (
        max(0, _money(remaining_before - amount))
        if handover_type == "Final Settlement"
        else 0
    )
    allocations = _build_delivery_allocations(
        delivery_boy,
        amount,
        shortage_to_allocate,
        shift.name,
    )

    handover = frappe.new_doc("Delivery Handover")
    handover.delivery_settlement = settlement.name
    handover.delivery_boy = delivery_boy
    handover.shift_reference = shift.name
    if _has_field("Delivery Handover", COLLECTION_SHIFT_FIELD):
        handover.set(COLLECTION_SHIFT_FIELD, shift.name)
    handover.handover_type = handover_type
    handover.handover_method = "Cash"
    handover.amount = amount
    handover.received_by = frappe.session.user
    handover.received_at = now_datetime()
    handover.notes = notes
    if _has_field("Delivery Handover", "custom_allocations"):
        for values in allocations:
            handover.append("custom_allocations", values)
    handover.flags.ignore_permissions = True
    handover.insert(ignore_permissions=True)
    handover.flags.ignore_permissions = True
    handover.submit()

    linked_handovers = frappe.get_all(
        "Delivery Handover",
        filters={
            "delivery_settlement": settlement.name,
            "handover_method": "Cash",
            "docstatus": 1,
        },
        fields=["amount", "handover_type"],
        limit_page_length=5000,
    )
    total_handed_over = _money(sum(_money(row.amount) for row in linked_handovers))

    settlement.reload()
    settlement.total_handed_over = total_handed_over
    settlement.handover_count = len(linked_handovers)
    settlement.last_handover_at = now_datetime()

    shortage = None
    if handover_type == "Final Settlement":
        shortage = _ensure_driver_shortage(
            settlement=settlement,
            final_handover=handover,
            expected_amount=_money(settlement.total_expected),
            handed_over_amount=total_handed_over,
            reason=notes,
        )
        shortage_amount = _money(shortage.shortage_amount) if shortage else 0
        settlement.remaining_with_driver = 0
        settlement.final_difference = _money(total_handed_over - _money(settlement.total_expected))
        settlement.difference_reason = notes if shortage_amount > TOLERANCE else ""
        settlement.settlement_status = "Disputed" if shortage_amount > TOLERANCE else "Settled"
        settlement.settled_at = now_datetime()
        settlement.settled_by = frappe.session.user
    else:
        settlement.remaining_with_driver = max(
            0,
            _money(_money(settlement.total_expected) - total_handed_over),
        )
        settlement.settlement_status = "Partial Handover"

    settlement.flags.ignore_permissions = True
    settlement.save(ignore_permissions=True)
    if handover_type == "Final Settlement" and settlement.docstatus == 0:
        settlement.flags.ignore_permissions = True
        settlement.submit()

    _refresh_payment_entry_collection_shifts(
        [row.get("payment_entry") for row in allocations if row.get("payment_entry")]
    )
    frappe.db.commit()

    return {
        "settlement": settlement.name,
        "handover": handover.name,
        "handover_type": handover_type,
        "requested_handover_type": requested_handover_type,
        "forced_partial": 1 if forced_partial else 0,
        "active_orders": [
            {
                "name": row.name,
                "customer_name": row.customer_name or row.customer,
                "grand_total": _money(row.grand_total),
                "status": row.custom_delivery_status,
                "delivery_shift": _effective_delivery_shift(row),
            }
            for row in active_orders
        ],
        "expected_amount": _money(settlement.total_expected),
        "handed_over_amount": total_handed_over,
        "shortage_amount": _money(shortage.shortage_amount) if shortage else 0,
        "shortage": shortage.name if shortage else "",
        "settlement_status": settlement.settlement_status,
        "collection_shift": shift.name,
        "allocation_count": len(allocations),
    }



def _finalize_covered_delivery_settlements(shift):
    """Submit draft settlements that are fully covered and have no active orders.

    This handles the valid case where the driver handed over all currently
    collected cash as a Partial Handover while still outside, then completed
    the remaining delivery without collecting more cash.
    """
    rows = frappe.get_all(
        "Delivery Settlement",
        filters={
            "shift_reference": shift.name,
            "docstatus": 0,
        },
        fields=["name", "delivery_boy"],
        limit_page_length=5000,
    )
    finalized = []
    for row in rows:
        outstanding = _money(
            sum(
                _money(item.remaining_amount)
                for item in _delivery_outstanding_rows(row.delivery_boy)
            )
        )
        if outstanding > TOLERANCE:
            continue
        if _active_delivery_orders(None, row.delivery_boy):
            continue
        if driver_outside_orders(row.delivery_boy):
            continue

        doc = frappe.get_doc("Delivery Settlement", row.name)
        handovers = frappe.get_all(
            "Delivery Handover",
            filters={
                "delivery_settlement": doc.name,
                "handover_method": "Cash",
                "docstatus": 1,
            },
            fields=["amount"],
            limit_page_length=5000,
        )
        handed_over = _money(sum(_money(item.amount) for item in handovers))
        doc.total_handed_over = handed_over
        doc.remaining_with_driver = 0
        doc.final_difference = _money(handed_over - _money(doc.total_expected))
        if abs(doc.final_difference) > TOLERANCE:
            # The remaining collection was completed in another Collection
            # Shift. Close this shift-local settlement only for the amount
            # actually received here; no shortage is created because the
            # global driver balance is already fully covered.
            doc.total_expected = handed_over
            doc.total_collected_by_driver = handed_over
            doc.final_difference = 0
            doc.difference_reason = "Remaining collection completed in another Collection Shift."
        doc.settlement_status = "Settled"
        doc.settled_at = now_datetime()
        doc.settled_by = frappe.session.user
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        doc.flags.ignore_permissions = True
        doc.submit()
        finalized.append(doc.name)
    return finalized

def _blockers(shift, terminals, include_electronic=True):
    blockers = []
    for terminal in terminals:
        if terminal.unbatched_count:
            blockers.append(
                {
                    "code": "UNBATCHED_CARD",
                    "message": _("توجد عمليات فيزا لم تدخل في تقفيلة ماكينة بعد. اعمل تقفيل للماكينة ثم اعتمد الـBatch قبل إغلاق الوردية."),
                    "rows": [{"terminal": terminal.terminal_name, "count": terminal.unbatched_count, "amount": terminal.unbatched_total}],
                }
            )
        draft = [row for row in terminal.batches if row.docstatus == 0]
        if draft:
            blockers.append({"code": "DRAFT_CARD_BATCH", "message": _("توجد تقفيلات ماكينة فيزا ما زالت Draft. افتحها وراجعها ثم اعمل Submit."), "rows": draft})

    if include_electronic:
        summary = {row.mode_of_payment: _money(row.amount) for row in _payment_summary(shift)}
        for mode in ("Insta Pay", "Wallet"):
            if abs(summary.get(mode, 0)) <= TOLERANCE:
                continue
            reconciliations = frappe.get_all(
                "Shift Payment Reconciliation",
                filters={
                    "shift_reference": shift.name,
                    "mode_of_payment": mode,
                    "docstatus": 1,
                },
                fields=[
                    "name",
                    "reviewed_amount",
                    "journal_entry",
                ],
                limit_page_length=1000,
            )

            reconciled_amount = _money(
                sum(
                    _money(row.reviewed_amount)
                    for row in reconciliations
                )
            )

            difference = _money(
                summary[mode] - reconciled_amount
            )

            if abs(difference) > TOLERANCE:
                blockers.append(
                    {
                        "code": "MOP_NOT_RECONCILED",
                        "message": _(
                            "{0} has not been fully reviewed and confirmed."
                        ).format(mode),
                        "rows": [
                            {
                                "sales_total": summary[mode],
                                "reconciled_total": reconciled_amount,
                                "difference": difference,
                            }
                        ],
                    }
                )

    driver_summaries = _delivery_driver_summaries(shift)
    drivers_not_returned = [
        row
        for row in driver_summaries
        if not row.final_submitted
        and not cint(row.can_receive_handover)
    ]
    if drivers_not_returned:
        blockers.append(
            {
                "code": "DRIVER_NOT_RETURNED",
                "message": _(
                    "يوجد طيارون لم يسجلوا الرجوع للصيدلية بعد. يجب تسجيل الرجوع أولًا، ثم استلام أي عهدة نقدية إن وجدت."
                ),
                "rows": drivers_not_returned,
            }
        )

    active_delivery_orders = (
        _active_delivery_orders(shift)
    )
    if active_delivery_orders:
        blockers.append(
            {
                "code": "ACTIVE_DELIVERY_ORDERS",
                "message": _(
                    "توجد أوردرات دليفري ما زالت نشطة. يجب تسليمها أو إلغاؤها أو ترحيلها رسميًا قبل إغلاق الوردية."
                ),
                "rows": [
                    {
                        "invoice": row.name,
                        "customer": (
                            row.customer_name
                            or row.customer
                        ),
                        "delivery_boy": (
                            row.custom_delivery_boy
                        ),
                        "status": (
                            row.custom_delivery_status
                        ),
                        "grand_total": _money(
                            row.grand_total
                        ),
                    }
                    for row in active_delivery_orders
                ],
            }
        )

    if frappe.db.exists("DocType", "Delivery Return Request"):
        return_requests = frappe.get_all(
            "Delivery Return Request",
            filters={
                "delivery_shift": shift.name,
                "status": ["not in", ["Partial Return Completed", "Full Return Completed", "Cancelled"]],
            },
            fields=["name", "sales_invoice", "return_type", "status", "delivery_boy", "estimated_return_amount"],
            order_by="creation asc",
            limit_page_length=1000,
        )
        if return_requests:
            blockers.append(
                {
                    "code": "OPEN_DELIVERY_RETURN_REQUESTS",
                    "message": _(
                        "توجد طلبات مرتجع دليفري لم تكتمل. استلم البضاعة وأنشئ أو اعتمد Credit Note قبل إغلاق الوردية."
                    ),
                    "rows": return_requests,
                }
            )

    unsettled = [
        row
        for row in driver_summaries
        if row.remaining_amount > TOLERANCE
        and not row.final_submitted
    ]
    if unsettled:
        blockers.append(
            {
                "code": "DELIVERY_NOT_SETTLED",
                "message": _(
                    "توجد متحصلات نقدية ما زالت مع الطيارين. استلمها جزئيًا أو نفّذ التقفيل النهائي قبل إغلاق الوردية."
                ),
                "rows": unsettled,
            }
        )

    for doctype, code, message in [
        ("Shift Cash Movement", "DRAFT_CASH_MOVEMENT", _("توجد حركات نقدية ما زالت Draft.")),
        ("Employee Cash Advance", "DRAFT_ADVANCE", _("توجد سلف موظفين ما زالت Draft.")),
    ]:
        rows = frappe.get_all(doctype, filters={"shift_reference": shift.name, "docstatus": 0}, pluck="name", limit_page_length=1000)
        if rows:
            blockers.append({"code": code, "message": message, "rows": rows})
    return blockers



def _rollover_summary(shift):
    state = _shift_operational_state(shift)
    current_due = _money(
        _cash_ledger(shift)["expected_cash"]
    )

    if state != UNDER_REVIEW_SHIFT:
        return {
            "new_shift": "",
            "new_opening_balance": 0.0,
            "net_safe_cash": 0.0,
            "remaining_cash_due": current_due,
        }

    new_shift_name = (
        shift.get("custom_rollover_new_shift")
        if _has_field(
            "Pharmacy Shift Closing",
            "custom_rollover_new_shift",
        )
        else ""
    )
    new_opening_balance = _money(
        shift.get("custom_rollover_new_opening_balance")
    )
    counted_cash = _money(
        shift.get("custom_review_actual_cash")
    )

    return {
        "new_shift": new_shift_name or "",
        "new_opening_balance": new_opening_balance,
        # No old-shift cash is posted to Main Safe at freeze time.
        "net_safe_cash": 0.0,
        "remaining_cash_due": counted_cash,
    }


@frappe.whitelist()
def get_dashboard(shift_name=None):
    frappe.only_for("System Manager")

    active = _current_open_shift()
    review_rows = _under_review_shift_rows()
    shift = _get_shift(shift_name) if shift_name else (
        frappe.get_doc(
            "Pharmacy Shift Closing",
            active.name,
        )
        if active
        else None
    )

    under_review = [
        {
            "name": row.name,
            "cashier": row.cashier,
            "company": row.company,
            "start_time": row.start_time or row.creation,
            "cutoff_time": row.get(SHIFT_CUTOFF_FIELD) or row.end_time,
            "expected_cash": _money(row.get("custom_review_expected_cash")),
            "actual_cash": _money(row.get("custom_review_actual_cash")),
            "difference": _money(row.get("custom_review_difference")),
            "cash_reference": row.get("custom_review_cash_reference") or "",
            "review_started_at": row.get("custom_review_started_at"),
            "review_started_by": row.get("custom_review_started_by"),
        }
        for row in review_rows
    ]

    if not shift:
        return {
            "has_open_shift": False,
            "has_active_shift": False,
            "active_shift": "",
            "under_review_shifts": under_review,
        }

    state = _shift_operational_state(shift)
    terminals = _terminal_summary(shift)
    rollover = _rollover_summary(shift)

    return {
        "has_open_shift": True,
        "has_active_shift": bool(active),
        "active_shift": active.name if active else "",
        "under_review_shifts": under_review,
        "shift": {
            "name": shift.name,
            "cashier": shift.cashier,
            "company": shift.company,
            "status": shift.status,
            "operational_status": state,
            "is_under_review": state == UNDER_REVIEW_SHIFT,
            "start_time": shift.start_time or shift.creation,
            "cutoff_time": shift.get(SHIFT_CUTOFF_FIELD) or shift.end_time,
            "opening_balance": _money(shift.opening_balance),
            "actual_cash": _money(shift.actual_cash),
            "cash_drawer": shift.get(CASH_DRAWER_FIELD) or "",
            "cash_account": shift.get("cash_account") or CASH_ACCOUNT,
            "opening_cash_movement": _opening_movement_name(shift),
            "closing_cash_movement": _closing_movement_name(shift),
            "review_expected_cash": _money(shift.get("custom_review_expected_cash")),
            "review_actual_cash": _money(shift.get("custom_review_actual_cash")),
            "review_difference": _money(shift.get("custom_review_difference")),
            "review_cash_reference": shift.get("custom_review_cash_reference") or "",
            "review_notes": shift.get("custom_review_notes") or "",
            "cash_difference_resolution": shift.get("custom_cash_difference_resolution") or "",
            "cash_difference_employee": shift.get("custom_cash_difference_employee") or "",
            "cash_difference_account": shift.get("custom_cash_difference_account") or "",
            "cash_difference_journal": shift.get("custom_cash_difference_journal") or "",
            "rollover_new_shift": rollover["new_shift"],
            "rollover_new_opening_balance": rollover["new_opening_balance"],
            "rollover_net_safe_cash": rollover["net_safe_cash"],
            "remaining_cash_due": rollover["remaining_cash_due"],
        },
        "cash": _cash_ledger(shift),
        "payment_summary": _payment_summary(shift),
        "delivery_drivers": _delivery_driver_summaries(shift),
        "terminals": terminals,
        "reconciliations": frappe.get_all(
            "Shift Payment Reconciliation",
            filters={"shift_reference": shift.name, "docstatus": ["!=", 2]},
            fields=["name", "mode_of_payment", "expected_amount", "reviewed_amount", "difference", "status", "journal_entry", "docstatus"],
            order_by="creation desc",
            limit_page_length=1000,
        ),
        "pending_bank_batches": frappe.get_all(
            "Card Settlement Batch",
            filters={"docstatus": 1, "status": ["in", ["Awaiting Bank Settlement", "Partially Settled"]]},
            fields=["name", "pos_terminal", "batch_number", "system_total", "settled_amount", "outstanding_amount", "status", "shift_reference"],
            order_by="close_time asc",
            limit_page_length=1000,
        ),
        "blockers": _blockers(shift, terminals),
    }


@frappe.whitelist()
def get_payment_details(
    shift_name,
    mode_of_payment=None,
    include_monthly_claims=1,
):
    frappe.only_for("System Manager")
    shift = _get_shift(shift_name)
    rows = _payment_rows(
        shift,
        mode_of_payment,
    )

    if (
        cint(include_monthly_claims)
        and not mode_of_payment
    ):
        rows.extend(
            _monthly_claim_rows(shift)
        )

    rows.sort(
        key=lambda row: (
            get_datetime(row.transaction_time),
            row.payment_source_name,
            row.payment_row_name,
        )
    )

    return rows


@frappe.whitelist()
def diagnose_shift_payments(shift_name=None):
    frappe.only_for("System Manager")
    shift = _get_shift(shift_name)
    rows = _payment_rows(shift)
    breakdown = {}

    for row in rows:
        key = (
            row.channel,
            row.mode_of_payment,
        )
        data = breakdown.setdefault(
            key,
            {
                "channel": row.channel,
                "mode_of_payment": (
                    row.mode_of_payment
                ),
                "amount": 0,
                "sources": set(),
            },
        )
        data["amount"] += _money(
            row.amount
        )
        data["sources"].add(
            row.payment_source_key
            or row.payment_row_name
        )

    summary = []

    for data in breakdown.values():
        summary.append(
            {
                "channel": data["channel"],
                "mode_of_payment": (
                    data["mode_of_payment"]
                ),
                "amount": _money(
                    data["amount"]
                ),
                "transaction_count": len(
                    data["sources"]
                ),
            }
        )

    summary.sort(
        key=lambda row: (
            row["channel"],
            row["mode_of_payment"],
        )
    )

    return {
        "shift": shift.name,
        "summary": summary,
        "rows": rows,
        "monthly_claims": (
            _monthly_claim_rows(shift)
        ),
    }


@frappe.whitelist()
def get_invoice_items(invoice_name):
    """Return invoice items for an in-page details dialog."""
    frappe.only_for("System Manager")

    if not frappe.db.exists("Sales Invoice", invoice_name):
        frappe.throw(_("Sales Invoice not found."))

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    item_meta = frappe.get_meta("Sales Invoice Item")

    rows = []
    for item in invoice.items:
        row = {
            "item_code": item.item_code,
            "item_name": item.item_name,
            "qty": _money(item.qty),
            "uom": item.uom,
            "rate": _money(item.rate),
            "amount": _money(item.amount),
            "discount_percentage": _money(item.discount_percentage),
            "warehouse": item.warehouse,
            "batch_no": "",
            "serial_and_batch_bundle": "",
        }

        if item_meta.has_field("batch_no"):
            row["batch_no"] = item.get("batch_no") or ""

        if item_meta.has_field("serial_and_batch_bundle"):
            row["serial_and_batch_bundle"] = item.get("serial_and_batch_bundle") or ""

        rows.append(row)

    return {
        "invoice": invoice.name,
        "customer": invoice.customer,
        "customer_name": invoice.customer_name,
        "posting_date": invoice.posting_date,
        "grand_total": _money(invoice.grand_total),
        "items": rows,
    }


def _create_shift_cash_movement(
    shift,
    movement_type,
    direction,
    amount,
    description,
    source_account,
    target_account,
    employee=None,
    supplier=None,
    expense_account=None,
    purchase_invoice=None,
    movement_date=None,
):
    doc = frappe.new_doc("Shift Cash Movement")
    doc.shift_reference = shift.name
    doc.company = shift.company
    doc.movement_date = (
        movement_date or now_datetime()
    )
    doc.movement_type = movement_type
    doc.direction = direction
    doc.amount = _money(amount)
    doc.source_account = source_account
    doc.target_account = target_account
    doc.employee = employee
    doc.supplier = supplier
    doc.expense_account = expense_account
    doc.description = description

    if _has_field("Shift Cash Movement", "purchase_invoice"):
        doc.purchase_invoice = purchase_invoice

    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    doc.flags.ignore_permissions = True
    doc.submit()

    _ensure_cash_movement_journal(doc)

    return {
        "doctype": doc.doctype,
        "name": doc.name,
        "journal_entry": frappe.db.get_value(
            doc.doctype,
            doc.name,
            "journal_entry",
        ),
    }



def _submitted_journal_exists(journal_entry):
    if not journal_entry:
        return False

    return (
        frappe.db.get_value(
            "Journal Entry",
            journal_entry,
            "docstatus",
        )
        == 1
    )


def _ensure_cash_movement_journal(doc):
    linked = frappe.db.get_value(
        "Shift Cash Movement",
        doc.name,
        "journal_entry",
    )

    if _submitted_journal_exists(linked):
        return linked

    amount = _money(doc.amount)

    journal = frappe.new_doc("Journal Entry")
    journal.voucher_type = "Journal Entry"
    journal.company = doc.company
    journal.posting_date = frappe.utils.getdate(
        doc.movement_date or nowdate()
    )
    journal.user_remark = (
        "Shift cash movement "
        + doc.name
        + " - "
        + (doc.description or doc.movement_type)
    )

    debit_row = {
        "account": doc.target_account,
        "debit_in_account_currency": amount,
        "credit_in_account_currency": 0,
    }
    credit_row = {
        "account": doc.source_account,
        "debit_in_account_currency": 0,
        "credit_in_account_currency": amount,
    }

    if (
        doc.movement_type == "Supplier Payment"
        and doc.supplier
    ):
        debit_row["party_type"] = "Supplier"
        debit_row["party"] = doc.supplier

        if doc.get("purchase_invoice"):
            debit_row["reference_type"] = (
                "Purchase Invoice"
            )
            debit_row["reference_name"] = (
                doc.purchase_invoice
            )

    journal.append("accounts", debit_row)
    journal.append("accounts", credit_row)
    journal.flags.ignore_permissions = True
    journal.insert(ignore_permissions=True)
    journal.flags.ignore_permissions = True
    journal.submit()

    frappe.db.set_value(
        "Shift Cash Movement",
        doc.name,
        {
            "journal_entry": journal.name,
            "status": "Posted",
            "posted_by": frappe.session.user,
            "posted_at": frappe.utils.now(),
        },
        update_modified=False,
    )

    return journal.name


def _shift_movement_total(
    shift_name,
    movement_type,
    direction=None,
):
    filters = {
        "shift_reference": shift_name,
        "movement_type": movement_type,
        "docstatus": 1,
    }

    if direction:
        filters["direction"] = direction

    rows = frappe.get_all(
        "Shift Cash Movement",
        filters=filters,
        fields=["amount"],
        limit_page_length=1000,
    )

    return _money(
        sum(_money(row.amount) for row in rows)
    )


def _closing_cash_breakdown(
    shift,
    actual_cash,
):
    """
    Split the physical drawer transfer into clear operational sources.

    Priority:
    1. Return the opening float.
    2. Deposit cash sales.
    3. Return unused till refills.
    4. Put any remaining amount in Other Cash Return.

    Cash expenses and advances already reduce the drawer through their
    own Journal Entries, so the allocation never exceeds actual cash.
    """
    remaining = _money(actual_cash)

    opening_total = _shift_movement_total(
        shift.name,
        "Opening Float",
        "In",
    )

    if opening_total <= TOLERANCE:
        opening_total = _money(
            shift.opening_balance
        )

    cash_account = shift.get("cash_account") or CASH_ACCOUNT
    cash_sales_total = _money(
        sum(
            _money(row.amount)
            for row in _payment_rows(
                shift,
                "Cash",
            )
            if str(row.destination_account or "") == cash_account
        )
    )

    refill_total = _shift_movement_total(
        shift.name,
        "Till Refill",
        "In",
    )

    desired = [
        (
            "Return Opening Float",
            opening_total,
            "Return opening float for shift ",
        ),
        (
            "Cash Sales Deposit",
            cash_sales_total,
            "Deposit cash sales for shift ",
        ),
        (
            "Unused Till Refill Return",
            refill_total,
            "Return unused till refill for shift ",
        ),
    ]

    allocations = []

    for movement_type, source_amount, description in desired:
        amount = min(
            max(_money(source_amount), 0),
            max(remaining, 0),
        )

        if amount > TOLERANCE:
            allocations.append(
                {
                    "movement_type": movement_type,
                    "amount": _money(amount),
                    "description": (
                        description + shift.name
                    ),
                }
            )
            remaining = _money(
                remaining - amount
            )

    if remaining > TOLERANCE:
        allocations.append(
            {
                "movement_type": "Other Cash Return",
                "amount": _money(remaining),
                "description": (
                    "Return other drawer cash for shift "
                    + shift.name
                ),
            }
        )

    return allocations


def _create_closing_cash_movements(
    shift,
    actual_cash,
):
    legacy = frappe.db.get_value(
        "Shift Cash Movement",
        {
            "shift_reference": shift.name,
            "movement_type": "Transfer to Main Safe",
            "docstatus": 1,
        },
        "name",
    )

    if legacy:
        return [
            {
                "movement_type": "Transfer to Main Safe",
                "name": legacy,
                "amount": _money(
                    frappe.db.get_value(
                        "Shift Cash Movement",
                        legacy,
                        "amount",
                    )
                ),
                "journal_entry": frappe.db.get_value(
                    "Shift Cash Movement",
                    legacy,
                    "journal_entry",
                ),
            }
        ]

    results = []
    cash_account = (
        shift.get("cash_account")
        or CASH_ACCOUNT
    )

    for row in _closing_cash_breakdown(
        shift,
        actual_cash,
    ):
        existing = frappe.db.get_value(
            "Shift Cash Movement",
            {
                "shift_reference": shift.name,
                "movement_type": row[
                    "movement_type"
                ],
                "docstatus": 1,
            },
            "name",
        )

        if existing:
            result = {
                "movement_type": row[
                    "movement_type"
                ],
                "name": existing,
                "amount": _money(
                    frappe.db.get_value(
                        "Shift Cash Movement",
                        existing,
                        "amount",
                    )
                ),
                "journal_entry": frappe.db.get_value(
                    "Shift Cash Movement",
                    existing,
                    "journal_entry",
                ),
            }
        else:
            created = _create_shift_cash_movement(
                shift=shift,
                movement_type=row[
                    "movement_type"
                ],
                direction="Out",
                amount=row["amount"],
                description=row[
                    "description"
                ],
                source_account=cash_account,
                target_account="Main Safe - C",
                movement_date=now_datetime(),
            )

            result = {
                "movement_type": row[
                    "movement_type"
                ],
                "amount": row["amount"],
                **created,
            }

        results.append(result)

        fieldname = CLOSING_MOVEMENT_FIELDS.get(
            row["movement_type"]
        )

        if (
            fieldname
            and _has_field(
                "Pharmacy Shift Closing",
                fieldname,
            )
        ):
            frappe.db.set_value(
                "Pharmacy Shift Closing",
                shift.name,
                fieldname,
                result["name"],
                update_modified=False,
            )

    if (
        results
        and _has_field(
            "Pharmacy Shift Closing",
            "closing_cash_movement",
        )
    ):
        frappe.db.set_value(
            "Pharmacy Shift Closing",
            shift.name,
            "closing_cash_movement",
            results[0]["name"],
            update_modified=False,
        )

    return results


def _ensure_reconciliation_journal(doc):
    linked = frappe.db.get_value(
        "Shift Payment Reconciliation",
        doc.name,
        "journal_entry",
    )

    if _submitted_journal_exists(linked):
        return linked

    gross_amount = _money(doc.reviewed_amount)
    fee_amount = _money(doc.fee_amount)
    net_amount = _money(
        gross_amount - fee_amount
    )

    if gross_amount <= 0:
        frappe.throw(
            _(
                "Reviewed amount must be greater than zero."
            )
        )

    journal = frappe.new_doc("Journal Entry")
    journal.voucher_type = "Journal Entry"
    journal.company = doc.company
    journal.posting_date = frappe.utils.getdate(
        doc.to_time or nowdate()
    )
    journal.user_remark = (
        "Shift payment reconciliation "
        + doc.name
        + " / "
        + doc.mode_of_payment
        + " / "
        + doc.shift_reference
    )

    if net_amount > 0:
        journal.append(
            "accounts",
            {
                "account": doc.destination_account,
                "debit_in_account_currency": net_amount,
                "credit_in_account_currency": 0,
            },
        )

    if fee_amount > 0:
        if not doc.fee_account:
            frappe.throw(
                _(
                    "Fee Account is required when a fee is entered."
                )
            )

        journal.append(
            "accounts",
            {
                "account": doc.fee_account,
                "debit_in_account_currency": fee_amount,
                "credit_in_account_currency": 0,
            },
        )

    journal.append(
        "accounts",
        {
            "account": doc.clearing_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": gross_amount,
        },
    )

    journal.flags.ignore_permissions = True
    journal.insert(ignore_permissions=True)
    journal.flags.ignore_permissions = True
    journal.submit()

    frappe.db.set_value(
        "Shift Payment Reconciliation",
        doc.name,
        {
            "journal_entry": journal.name,
            "status": "Submitted",
        },
        update_modified=False,
    )

    return journal.name


def _new_payment_reconciliation(
    shift,
    mode_of_payment,
    expected_amount,
    rows,
    from_time=None,
    to_time=None,
    fee_amount=0,
):
    setup_name = frappe.db.get_value(
        "Payment Method Clearing Setup",
        {
            "company": shift.company,
            "mode_of_payment": mode_of_payment,
            "enabled": 1,
        },
        "name",
    )

    if not setup_name:
        frappe.throw(
            _(
                "No enabled clearing setup was found for {0}."
            ).format(mode_of_payment)
        )

    setup = frappe.get_doc(
        "Payment Method Clearing Setup",
        setup_name,
    )

    doc = frappe.new_doc(
        "Shift Payment Reconciliation"
    )
    doc.shift_reference = shift.name
    doc.company = shift.company
    doc.mode_of_payment = mode_of_payment
    doc.setup_reference = setup.name
    doc.from_time = (
        from_time
        or shift.start_time
        or shift.creation
    )
    doc.to_time = to_time or now_datetime()
    doc.clearing_account = setup.clearing_account
    doc.destination_account = (
        setup.destination_account
    )
    doc.settlement_policy = (
        setup.settlement_policy
    )
    doc.fee_account = setup.fee_account
    doc.expected_amount = _money(
        expected_amount
    )
    doc.reviewed_amount = _money(
        expected_amount
    )
    doc.fee_amount = _money(fee_amount)
    doc.difference = 0
    doc.net_transfer_amount = _money(
        expected_amount - fee_amount
    )

    for row in rows or []:
        doc.append(
            "transactions",
            {
                "sales_invoice": row.sales_invoice,
                "customer": row.customer,
                "order_type": row.order_type,
                "transaction_date": row.transaction_time,
                "reference_number": row.reference_no,
                "amount": row.amount,
                "verified": 1,
            },
        )

    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    doc.flags.ignore_permissions = True
    doc.submit()

    _ensure_reconciliation_journal(doc)

    return doc


def _auto_reconcile_shift_modes(shift):
    created = []

    for mode in ("Insta Pay", "Wallet"):
        payment_rows = _payment_rows(
            shift,
            mode,
        )
        sales_total = _money(
            sum(
                _money(row.amount)
                for row in payment_rows
            )
        )

        reconciliations = frappe.get_all(
            "Shift Payment Reconciliation",
            filters={
                "shift_reference": shift.name,
                "mode_of_payment": mode,
                "docstatus": 1,
            },
            fields=[
                "name",
                "reviewed_amount",
                "to_time",
                "journal_entry",
            ],
            order_by="creation asc",
            limit_page_length=1000,
        )

        reconciled_total = 0
        latest_to_time = None

        for row in reconciliations:
            reconciled_total += _money(
                row.reviewed_amount
            )
            latest_to_time = (
                row.to_time or latest_to_time
            )

            doc = frappe.get_doc(
                "Shift Payment Reconciliation",
                row.name,
            )
            _ensure_reconciliation_journal(doc)

        difference = _money(
            sales_total - reconciled_total
        )

        if abs(difference) <= TOLERANCE:
            continue

        if difference < 0:
            frappe.throw(
                _(
                    "{0} reconciliations exceed the shift sales total. Review the existing reconciliation documents."
                ).format(mode)
            )

        delta_rows = payment_rows

        if latest_to_time:
            latest_dt = get_datetime(
                latest_to_time
            )
            delta_rows = [
                row
                for row in payment_rows
                if get_datetime(
                    row.transaction_time
                )
                > latest_dt
            ]

        doc = _new_payment_reconciliation(
            shift=shift,
            mode_of_payment=mode,
            expected_amount=difference,
            rows=delta_rows,
            from_time=(
                latest_to_time
                or shift.start_time
                or shift.creation
            ),
            to_time=(
                shift.end_time
                or now_datetime()
            ),
            fee_amount=0,
        )

        created.append(
            {
                "name": doc.name,
                "mode_of_payment": mode,
                "amount": difference,
                "journal_entry": frappe.db.get_value(
                    doc.doctype,
                    doc.name,
                    "journal_entry",
                ),
            }
        )

    return created


@frappe.whitelist()
def create_cash_action(
    shift_name,
    action_type,
    amount,
    description=None,
    movement_type=None,
    source_account=None,
    employee=None,
    purpose=None,
    recovery_method=None,
    expense_account=None,
    supplier=None,
    purchase_invoice=None,
):
    """Create and submit a cash-in, expense, supplier payment, or advance."""
    frappe.only_for("System Manager")

    shift = _get_shift(shift_name)
    amount = _money(amount)
    description = (description or purpose or "").strip()

    if amount <= 0:
        frappe.throw(_("Amount must be greater than zero."))

    cash_account = shift.get("cash_account") or CASH_ACCOUNT

    if action_type == "Cash In":
        source_account = source_account or "Main Safe - C"
        movement_type = movement_type or "Till Refill"
        result = _create_shift_cash_movement(
            shift=shift,
            movement_type=movement_type,
            direction="In",
            amount=amount,
            description=description or movement_type,
            source_account=source_account,
            target_account=cash_account,
        )

    elif action_type == "Employee Advance":
        if not employee:
            frappe.throw(_("Employee is required."))
        if not purpose:
            frappe.throw(_("Purpose is required."))

        doc = frappe.new_doc("Employee Cash Advance")
        doc.company = shift.company
        doc.employee = employee
        doc.shift_reference = shift.name
        doc.advance_date = nowdate()
        doc.cash_account = cash_account
        doc.employee_advance_account = "Employee Advances - C"
        doc.advance_amount = amount
        doc.purpose = purpose
        doc.recovery_method = recovery_method or "Cash Repayment"
        doc.notes = description or purpose
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
        doc.flags.ignore_permissions = True
        doc.submit()

        result = {
            "doctype": doc.doctype,
            "name": doc.name,
            "journal_entry": frappe.db.get_value(doc.doctype, doc.name, "journal_entry"),
        }

    elif action_type == "Operating Expense":
        if not expense_account:
            frappe.throw(_("Expense Account is required."))
        result = _create_shift_cash_movement(
            shift=shift,
            movement_type="Operating Expense",
            direction="Out",
            amount=amount,
            description=description or "Operating Expense",
            source_account=cash_account,
            target_account=expense_account,
            expense_account=expense_account,
        )

    elif action_type == "Supplier Payment":
        if not supplier:
            frappe.throw(_("Supplier is required."))

        payable_account = get_party_account("Supplier", supplier, shift.company)
        result = _create_shift_cash_movement(
            shift=shift,
            movement_type="Supplier Payment",
            direction="Out",
            amount=amount,
            description=description or "Supplier Payment",
            source_account=cash_account,
            target_account=payable_account,
            supplier=supplier,
            purchase_invoice=purchase_invoice,
        )

    else:
        frappe.throw(_("Unsupported cash action type."))

    frappe.db.commit()
    return result


@frappe.whitelist()
def get_card_bank_defaults(destination_bank_account=None, clearing_account=None):
    """Resolve clearing and fee accounts from active card terminals."""
    frappe.only_for("System Manager")

    filters = {"company": COMPANY, "enabled": 1}
    if destination_bank_account:
        filters["destination_bank_account"] = destination_bank_account
    if clearing_account:
        filters["clearing_account"] = clearing_account

    rows = frappe.get_all(
        "Card POS Terminal",
        filters=filters,
        fields=["clearing_account", "destination_bank_account", "fee_account"],
        order_by="creation asc",
        limit_page_length=100,
    )
    if not rows:
        return {}

    unique = {
        (row.clearing_account, row.destination_bank_account, row.fee_account or "")
        for row in rows
    }
    if len(unique) != 1:
        return {}

    clearing, destination, fee = next(iter(unique))
    return {
        "clearing_account": clearing,
        "destination_bank_account": destination,
        "fee_account": fee,
    }


def _drawer_for_shift(cash_drawer=None, company=None):
    company = company or COMPANY
    name = cash_drawer
    if not name:
        name = frappe.db.get_value(
            "Cash Drawer",
            {"company": company, "enabled": 1},
            "name",
            order_by="creation asc",
        )
    if not name:
        frappe.throw(_("No enabled Cash Drawer is configured for this company."))
    drawer = frappe.get_doc("Cash Drawer", name)
    if not drawer.enabled or drawer.company != company:
        frappe.throw(_("Invalid or disabled Cash Drawer."))
    if not drawer.cash_account:
        frappe.throw(_("The Cash Drawer has no Cash Account."))
    return drawer


def _create_shift_document(opening_balance=0, company=None, cash_drawer=None):
    opening_balance = _money(opening_balance)
    company = company or COMPANY
    drawer = _drawer_for_shift(cash_drawer, company)

    doc = frappe.new_doc("Pharmacy Shift Closing")
    doc.company = company
    doc.cashier = frappe.session.user
    doc.status = "Open"
    doc.start_time = now_datetime()
    doc.opening_balance = opening_balance
    if _has_field("Pharmacy Shift Closing", "cash_account"):
        doc.cash_account = drawer.cash_account
    if _has_field("Pharmacy Shift Closing", CASH_DRAWER_FIELD):
        doc.set(CASH_DRAWER_FIELD, drawer.name)
    if _has_field("Pharmacy Shift Closing", SHIFT_STATE_FIELD):
        doc.set(SHIFT_STATE_FIELD, ACTIVE_SHIFT)

    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)

    frappe.db.set_value(
        "Cash Drawer",
        drawer.name,
        {
            "current_responsible_user": frappe.session.user,
            "current_active_shift": doc.name,
        },
        update_modified=False,
    )

    opening_result = None
    if opening_balance > 0:
        opening_result = _create_shift_cash_movement(
            shift=doc,
            movement_type="Opening Float",
            direction="In",
            amount=opening_balance,
            description="Opening float for shift " + doc.name,
            source_account=MAIN_SAFE_ACCOUNT,
            target_account=drawer.cash_account,
            movement_date=doc.start_time,
        )
        if _has_field("Pharmacy Shift Closing", "opening_cash_movement"):
            frappe.db.set_value(
                "Pharmacy Shift Closing",
                doc.name,
                "opening_cash_movement",
                opening_result["name"],
                update_modified=False,
            )
    return doc, opening_result


@frappe.whitelist()
def create_shift(opening_balance=0, company=None, cash_drawer=None):
    frappe.only_for("System Manager")
    company = company or COMPANY
    if _current_open_shift(company):
        frappe.throw(_("There is already an active shift. Move it to Under Review or close it first."))

    doc, opening_result = _create_shift_document(opening_balance, company, cash_drawer)
    frappe.db.commit()
    return {
        "name": doc.name,
        "cash_drawer": doc.get(CASH_DRAWER_FIELD) or "",
        "cash_account": doc.get("cash_account") or "",
        "opening_cash_movement": opening_result["name"] if opening_result else None,
        "opening_journal_entry": opening_result["journal_entry"] if opening_result else None,
    }


@frappe.whitelist()
def rollover_shift(
    shift_name,
    new_opening_balance=0,
    transfer_invoices=None,
    transfer_reason=None,
    counted_cash=None,
    review_notes=None,
    cash_reference=None,
    secured_cash=None,
):
    """Freeze old shift, open a new shift, and optionally move unassigned
    delivery orders to the new Delivery Shift. Sales Shift never changes.
    """
    frappe.only_for("System Manager")
    shift = _get_shift(shift_name, require_active=True)

    draft_documents = []
    for doctype in ("Shift Cash Movement", "Employee Cash Advance"):
        names = frappe.get_all(
            doctype,
            filters={"shift_reference": shift.name, "docstatus": 0},
            pluck="name",
            limit_page_length=1000,
        )
        draft_documents.extend([doctype + ": " + name for name in names])

    if _has_field("Sales Invoice", SHIFT_LINK_FIELD):
        draft_invoices = frappe.get_all(
            "Sales Invoice",
            filters={SHIFT_LINK_FIELD: shift.name, "docstatus": 0},
            pluck="name",
            limit_page_length=1000,
        )
        draft_documents.extend(["Sales Invoice: " + name for name in draft_invoices])

    if draft_documents:
        frappe.throw(
            _("Resolve or cancel the following draft documents before moving the shift to review: {0}").format(
                ", ".join(draft_documents)
            )
        )

    cash = _cash_ledger(shift)
    expected_cash = _money(cash["expected_cash"])
    cutoff = now_datetime()
    shift.reload()
    shift.end_time = cutoff
    shift.actual_cash = 0
    shift.expected_cash = expected_cash
    shift.difference = 0
    shift.total_cash_sales = _money(cash.get("cash_sales"))
    shift.total_expenses = _money(cash.get("cash_out"))
    if _has_field("Pharmacy Shift Closing", SHIFT_STATE_FIELD):
        shift.set(SHIFT_STATE_FIELD, UNDER_REVIEW_SHIFT)
    if _has_field("Pharmacy Shift Closing", SHIFT_CUTOFF_FIELD):
        shift.set(SHIFT_CUTOFF_FIELD, cutoff)

    review_values = {
        "custom_review_started_at": cutoff,
        "custom_review_started_by": frappe.session.user,
        "custom_review_expected_cash": expected_cash,
        "custom_review_actual_cash": None,
        "custom_review_difference": None,
        "custom_review_notes": "",
        "custom_review_cash_reference": "",
    }
    for fieldname, value in review_values.items():
        if _has_field("Pharmacy Shift Closing", fieldname):
            shift.set(fieldname, value)
    shift.flags.ignore_permissions = True
    shift.save(ignore_permissions=True)

    drawer_name = shift.get(CASH_DRAWER_FIELD) if _has_field("Pharmacy Shift Closing", CASH_DRAWER_FIELD) else None
    new_shift, opening_result = _create_shift_document(
        new_opening_balance,
        shift.company,
        drawer_name,
    )

    if isinstance(transfer_invoices, str):
        transfer_invoices = frappe.parse_json(transfer_invoices) if transfer_invoices else []
    transfer_result = _transfer_delivery_orders(
        shift,
        new_shift,
        transfer_invoices or [],
        transfer_reason,
    )

    rollover_values = {}
    if _has_field("Pharmacy Shift Closing", "custom_rollover_new_shift"):
        rollover_values["custom_rollover_new_shift"] = new_shift.name
    if _has_field("Pharmacy Shift Closing", "custom_rollover_new_opening_balance"):
        rollover_values["custom_rollover_new_opening_balance"] = _money(new_opening_balance)
    if _has_field("Pharmacy Shift Closing", "custom_rollover_net_safe_cash"):
        rollover_values["custom_rollover_net_safe_cash"] = 0
    if rollover_values:
        frappe.db.set_value("Pharmacy Shift Closing", shift.name, rollover_values, update_modified=False)

    frappe.db.commit()
    return {
        "under_review_shift": shift.name,
        "new_shift": new_shift.name,
        "cash_drawer": new_shift.get(CASH_DRAWER_FIELD) or "",
        "expected_cash_snapshot": expected_cash,
        "final_cash_count_pending": True,
        "new_opening_balance": _money(new_opening_balance),
        "closing_cash_movements": [],
        "new_opening_cash_movement": opening_result["name"] if opening_result else None,
        "delivery_transfers": transfer_result,
    }


def _fill_batch(doc, rows):
    doc.set("items", [])
    for row in rows:
        doc.append(
            "items",
            {
                "payment_row_name": row.payment_row_name,
                "sales_invoice": row.sales_invoice,
                "customer": row.customer,
                "customer_name": row.customer_name,
                "transaction_time": row.transaction_time,
                "transaction_type": row.transaction_type,
                "reference_no": row.reference_no,
                "amount": row.amount,
                "pos_terminal": row.card_pos_terminal,
            },
        )
    doc.transaction_count = len(rows)
    doc.system_total = _money(sum(_money(row.amount) for row in rows))
    doc.difference = _money(_money(doc.machine_total) - doc.system_total)
    doc.outstanding_amount = _money(doc.system_total - _money(doc.settled_amount))


@frappe.whitelist()
def create_card_batch(shift_name, pos_terminal, machine_total, batch_number=None, close_time=None):
    frappe.only_for("System Manager")
    shift = _get_shift(shift_name)
    terminal = frappe.get_doc("Card POS Terminal", pos_terminal)
    if not terminal.enabled or terminal.company != shift.company:
        frappe.throw(_("Invalid or disabled terminal."))
    rows = _unbatched_card_rows(shift, terminal.name)
    if not rows:
        frappe.throw(_("There are no unbatched card transactions for this terminal."))
    doc = frappe.new_doc("Card Settlement Batch")
    doc.company = shift.company
    doc.shift_reference = shift.name
    doc.pos_terminal = terminal.name
    doc.bank_label = terminal.bank_label
    doc.batch_number = batch_number or ""
    doc.from_time = rows[0].transaction_time
    doc.to_time = rows[-1].transaction_time
    doc.close_time = close_time or now_datetime()
    doc.machine_total = _money(machine_total)
    doc.clearing_account = terminal.clearing_account
    doc.destination_bank_account = terminal.destination_bank_account
    doc.fee_account = terminal.fee_account
    doc.status = "Draft"
    _fill_batch(doc, rows)
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)

    submitted = 0
    if abs(_money(doc.difference)) <= TOLERANCE:
        doc.flags.ignore_permissions = True
        doc.submit()
        submitted = 1

    frappe.db.commit()

    return {
        "name": doc.name,
        "system_total": doc.system_total,
        "machine_total": doc.machine_total,
        "difference": doc.difference,
        "transaction_count": doc.transaction_count,
        "submitted": submitted,
        "docstatus": doc.docstatus,
        "status": doc.status,
    }


@frappe.whitelist()
def refresh_card_batch(batch_name):
    frappe.only_for("System Manager")
    doc = frappe.get_doc("Card Settlement Batch", batch_name)
    if doc.docstatus != 0:
        frappe.throw(_("Only a Draft batch can be refreshed."))
    shift = _get_shift(doc.shift_reference)
    all_rows = _payment_rows(shift, "Credit Card", doc.pos_terminal)
    current = {row.payment_row_name for row in doc.items}
    available = {row.payment_row_name: row for row in _unbatched_card_rows(shift, doc.pos_terminal)}
    all_by_name = {row.payment_row_name: row for row in all_rows}
    names = list(current)
    names.extend(name for name in available if name not in current)
    _fill_batch(doc, [all_by_name[name] for name in names if name in all_by_name])
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"name": doc.name, "system_total": doc.system_total, "difference": doc.difference, "transaction_count": doc.transaction_count}


@frappe.whitelist()
def create_payment_reconciliation(shift_name, mode_of_payment, reviewed_amount, fee_amount=0):
    frappe.only_for("System Manager")
    if mode_of_payment not in ("Insta Pay", "Wallet"):
        frappe.throw(_("This action is only for Insta Pay and Wallet."))
    shift = _get_shift(shift_name)
    existing = frappe.db.get_value(
        "Shift Payment Reconciliation",
        {"shift_reference": shift.name, "mode_of_payment": mode_of_payment, "docstatus": ["!=", 2]},
        "name",
    )
    if existing:
        frappe.throw(_("A reconciliation already exists: {0}").format(existing))
    setup_name = frappe.db.get_value(
        "Payment Method Clearing Setup",
        {"company": shift.company, "mode_of_payment": mode_of_payment, "enabled": 1},
        "name",
    )
    if not setup_name:
        frappe.throw(_("No enabled clearing setup was found."))
    setup = frappe.get_doc("Payment Method Clearing Setup", setup_name)
    rows = _payment_rows(shift, mode_of_payment)
    expected = _money(sum(_money(row.amount) for row in rows))
    doc = frappe.new_doc("Shift Payment Reconciliation")
    doc.shift_reference = shift.name
    doc.company = shift.company
    doc.mode_of_payment = mode_of_payment
    doc.setup_reference = setup.name
    doc.from_time = shift.start_time or shift.creation
    doc.to_time = now_datetime()
    doc.clearing_account = setup.clearing_account
    doc.destination_account = setup.destination_account
    doc.settlement_policy = setup.settlement_policy
    doc.fee_account = setup.fee_account
    doc.expected_amount = expected
    doc.reviewed_amount = _money(reviewed_amount)
    doc.fee_amount = _money(fee_amount)
    doc.difference = _money(doc.reviewed_amount - expected)
    doc.net_transfer_amount = _money(doc.reviewed_amount - doc.fee_amount)
    for row in rows:
        doc.append(
            "transactions",
            {
                "sales_invoice": row.sales_invoice,
                "customer": row.customer,
                "order_type": row.order_type,
                "transaction_date": row.transaction_time,
                "reference_number": row.reference_no,
                "amount": row.amount,
                "verified": 1,
            },
        )
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    doc.flags.ignore_permissions = True
    doc.submit()

    frappe.db.commit()

    return {
        "name": doc.name,
        "expected_amount": doc.expected_amount,
        "reviewed_amount": doc.reviewed_amount,
        "journal_entry": "",
        "posting_status": "Pending Final Shift Approval",
    }


@frappe.whitelist()
def get_awaiting_card_batches(clearing_account=None, destination_bank_account=None):
    frappe.only_for("System Manager")
    filters = {
        "docstatus": 1,
        "status": ["in", ["Awaiting Bank Settlement", "Partially Settled"]],
        "outstanding_amount": [">", 0],
    }
    if clearing_account:
        filters["clearing_account"] = clearing_account
    if destination_bank_account:
        filters["destination_bank_account"] = destination_bank_account
    return frappe.get_all(
        "Card Settlement Batch",
        filters=filters,
        fields=["name", "pos_terminal", "batch_number", "close_time", "system_total", "settled_amount", "outstanding_amount", "clearing_account", "destination_bank_account", "fee_account"],
        order_by="close_time asc",
        limit_page_length=5000,
    )


def _ensure_delivery_handover_journal(handover, shift):
    linked = handover.get("journal_entry") or ""
    if _submitted_journal_exists(linked):
        return linked

    amount = _money(handover.amount)
    if amount <= TOLERANCE:
        return ""

    journal = frappe.new_doc("Journal Entry")
    journal.voucher_type = "Journal Entry"
    journal.company = shift.company
    journal.posting_date = frappe.utils.getdate(
        shift.get(SHIFT_CUTOFF_FIELD)
        or shift.end_time
        or nowdate()
    )
    journal.user_remark = (
        "Driver cash handover / "
        + handover.name
        + " / shift "
        + shift.name
    )
    journal.append(
        "accounts",
        {
            "account": shift.get("cash_account") or CASH_ACCOUNT,
            "debit_in_account_currency": amount,
            "credit_in_account_currency": 0,
        },
    )
    journal.append(
        "accounts",
        {
            "account": DELIVERY_TRANSIT_ACCOUNT,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": amount,
        },
    )
    journal.flags.ignore_permissions = True
    journal.insert(ignore_permissions=True)
    journal.flags.ignore_permissions = True
    journal.submit()

    if _has_field("Delivery Handover", "journal_entry"):
        frappe.db.set_value(
            "Delivery Handover",
            handover.name,
            "journal_entry",
            journal.name,
            update_modified=False,
        )

    return journal.name


def _ensure_driver_shortage_journal(shortage, shift):
    linked = shortage.get("journal_entry") or ""
    if _submitted_journal_exists(linked):
        return linked

    amount = _money(shortage.shortage_amount)
    if amount <= TOLERANCE:
        return ""

    journal = frappe.new_doc("Journal Entry")
    journal.voucher_type = "Journal Entry"
    journal.company = shift.company
    journal.posting_date = frappe.utils.getdate(
        shift.get(SHIFT_CUTOFF_FIELD)
        or shift.end_time
        or nowdate()
    )
    journal.user_remark = (
        "Driver shortage / "
        + shortage.name
        + " / shift "
        + shift.name
    )

    debit_row = {
        "account": shortage.employee_shortage_account
        or EMPLOYEE_SHORTAGE_ACCOUNT,
        "debit_in_account_currency": amount,
        "credit_in_account_currency": 0,
    }
    if shortage.employee:
        debit_row["party_type"] = "Employee"
        debit_row["party"] = shortage.employee

    journal.append("accounts", debit_row)
    journal.append(
        "accounts",
        {
            "account": shortage.delivery_transit_account
            or DELIVERY_TRANSIT_ACCOUNT,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": amount,
        },
    )
    journal.flags.ignore_permissions = True
    journal.insert(ignore_permissions=True)
    journal.flags.ignore_permissions = True
    journal.submit()

    frappe.db.set_value(
        "Driver Shortage",
        shortage.name,
        {
            "journal_entry": journal.name,
            "status": shortage.status or "Open",
        },
        update_modified=False,
    )

    return journal.name


def _post_delivery_review_entries(shift):
    results = {"handovers": [], "shortages": []}

    handovers = frappe.get_all(
        "Delivery Handover",
        filters={
            "shift_reference": shift.name,
            "handover_method": "Cash",
            "docstatus": 1,
        },
        fields=["name"],
        order_by="creation asc",
        limit_page_length=5000,
    )

    for row in handovers:
        handover = frappe.get_doc("Delivery Handover", row.name)
        journal = _ensure_delivery_handover_journal(handover, shift)
        results["handovers"].append(
            {"name": handover.name, "journal_entry": journal}
        )

    shortages = frappe.get_all(
        "Driver Shortage",
        filters={
            "shift_reference": shift.name,
            "docstatus": ["!=", 2],
        },
        fields=["name", "docstatus"],
        order_by="creation asc",
        limit_page_length=5000,
    )

    for row in shortages:
        shortage = frappe.get_doc("Driver Shortage", row.name)
        if shortage.docstatus == 0:
            shortage.flags.ignore_permissions = True
            shortage.submit()
            shortage.reload()
        journal = _ensure_driver_shortage_journal(shortage, shift)
        results["shortages"].append(
            {"name": shortage.name, "journal_entry": journal}
        )

    return results


def _post_electronic_review_entries(shift):
    results = []
    rows = frappe.get_all(
        "Shift Payment Reconciliation",
        filters={
            "shift_reference": shift.name,
            "docstatus": 1,
        },
        fields=["name"],
        order_by="creation asc",
        limit_page_length=1000,
    )

    for row in rows:
        doc = frappe.get_doc("Shift Payment Reconciliation", row.name)
        journal = _ensure_reconciliation_journal(doc)
        results.append(
            {
                "name": doc.name,
                "mode_of_payment": doc.mode_of_payment,
                "journal_entry": journal,
            }
        )

    return results


def _create_cash_difference_journal(
    shift,
    difference,
    resolution=None,
    responsible_employee=None,
    reason=None,
):
    difference = _money(difference)
    reason = str(reason or "").strip()

    if abs(difference) <= TOLERANCE:
        return {
            "journal_entry": "",
            "account": "",
            "resolution": "No Difference",
        }

    existing = shift.get("custom_cash_difference_journal") or ""
    if _submitted_journal_exists(existing):
        return {
            "journal_entry": existing,
            "account": shift.get("custom_cash_difference_account") or "",
            "resolution": shift.get("custom_cash_difference_resolution") or "",
        }

    cash_account = shift.get("cash_account") or CASH_ACCOUNT
    journal = frappe.new_doc("Journal Entry")
    journal.voucher_type = "Journal Entry"
    journal.company = shift.company
    journal.posting_date = frappe.utils.getdate(
        shift.get(SHIFT_CUTOFF_FIELD)
        or shift.end_time
        or nowdate()
    )

    if difference < -TOLERANCE:
        if resolution not in ("Employee Liability", "Company Expense"):
            frappe.throw(
                _("Select how the cash shortage will be resolved.")
            )
        if not reason:
            frappe.throw(_("Enter the reason for the cash shortage."))

        shortage_amount = abs(difference)
        if resolution == "Employee Liability":
            if not responsible_employee:
                frappe.throw(
                    _("Select the employee responsible for the shortage.")
                )
            difference_account = EMPLOYEE_SHORTAGE_ACCOUNT
            debit_row = {
                "account": difference_account,
                "debit_in_account_currency": shortage_amount,
                "credit_in_account_currency": 0,
                "party_type": "Employee",
                "party": responsible_employee,
            }
        else:
            difference_account = CASH_SHORTAGE_EXPENSE_ACCOUNT
            debit_row = {
                "account": difference_account,
                "debit_in_account_currency": shortage_amount,
                "credit_in_account_currency": 0,
            }

        journal.user_remark = (
            "Shift cash shortage / " + shift.name + " / " + reason
        )
        journal.append("accounts", debit_row)
        journal.append(
            "accounts",
            {
                "account": cash_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": shortage_amount,
            },
        )

    else:
        resolution = "Overage Income"
        if not reason:
            frappe.throw(_("Enter the reason or note for the cash overage."))
        difference_account = CASH_OVERAGE_INCOME_ACCOUNT
        journal.user_remark = (
            "Shift cash overage / " + shift.name + " / " + reason
        )
        journal.append(
            "accounts",
            {
                "account": cash_account,
                "debit_in_account_currency": difference,
                "credit_in_account_currency": 0,
            },
        )
        journal.append(
            "accounts",
            {
                "account": difference_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": difference,
            },
        )

    journal.flags.ignore_permissions = True
    journal.insert(ignore_permissions=True)
    journal.flags.ignore_permissions = True
    journal.submit()

    return {
        "journal_entry": journal.name,
        "account": difference_account,
        "resolution": resolution,
    }


@frappe.whitelist()
def close_shift(
    shift_name,
    actual_cash=None,
    difference_resolution=None,
    responsible_employee=None,
    difference_reason=None,
):
    frappe.only_for("System Manager")

    shift = _get_shift(shift_name)
    shift_state = _shift_operational_state(shift)
    terminals = _terminal_summary(shift)
    auto_finalized_settlements = _finalize_covered_delivery_settlements(shift)

    blockers = _blockers(
        shift,
        terminals,
        include_electronic=True,
    )
    if blockers:
        frappe.throw(
            "<br>".join(row["message"] for row in blockers)
        )

    cash = _cash_ledger(shift)

    # The freeze snapshot is informational only. Final expected cash must
    # include any driver handovers or approved movements received while
    # the shift was Under Review.
    expected_cash = _money(cash["expected_cash"])

    if actual_cash in (None, ""):
        frappe.throw(
            _("Enter the final counted cash before approving the shift.")
        )

    counted_cash = _money(actual_cash)
    difference = _money(counted_cash - expected_cash)

    if counted_cash < -TOLERANCE:
        frappe.throw(_("Actual cash cannot be negative."))

    # Review confirmations are stored first; their accounting entries are
    # posted only in this final approval transaction.
    electronic_entries = _post_electronic_review_entries(shift)
    delivery_entries = _post_delivery_review_entries(shift)
    difference_entry = _create_cash_difference_journal(
        shift=shift,
        difference=difference,
        resolution=difference_resolution,
        responsible_employee=responsible_employee,
        reason=difference_reason,
    )

    closing_movements = (
        _create_closing_cash_movements(shift, counted_cash)
        if counted_cash > TOLERANCE
        else []
    )

    cash_sales_total = _money(cash.get("cash_sales"))

    shift.reload()
    shift.actual_cash = counted_cash
    shift.expected_cash = expected_cash
    shift.difference = difference
    shift.total_cash_sales = cash_sales_total
    shift.total_expenses = _money(cash.get("cash_out"))
    shift.status = "Closed"

    if shift_state == UNDER_REVIEW_SHIFT:
        shift.end_time = (
            shift.get(SHIFT_CUTOFF_FIELD)
            or shift.end_time
            or now_datetime()
        )
    else:
        shift.end_time = now_datetime()

    if _has_field("Pharmacy Shift Closing", SHIFT_STATE_FIELD):
        shift.set(SHIFT_STATE_FIELD, CLOSED_SHIFT)

    final_values = {
        "custom_review_actual_cash": counted_cash,
        "custom_review_difference": difference,
        "custom_review_notes": difference_reason or "",
        "custom_cash_difference_resolution": difference_entry["resolution"],
        "custom_cash_difference_employee": responsible_employee or "",
        "custom_cash_difference_account": difference_entry["account"],
        "custom_cash_difference_journal": difference_entry["journal_entry"],
        "custom_final_posted_at": now_datetime(),
        "custom_final_posted_by": frappe.session.user,
    }
    for fieldname, value in final_values.items():
        if _has_field("Pharmacy Shift Closing", fieldname):
            shift.set(fieldname, value)

    if _has_field("Pharmacy Shift Closing", "closed_by"):
        shift.closed_by = frappe.session.user
    if _has_field("Pharmacy Shift Closing", "closed_at"):
        shift.closed_at = now_datetime()

    shift.flags.ignore_permissions = True
    shift.save(ignore_permissions=True)
    shift.flags.ignore_permissions = True
    shift.submit()

    frappe.db.commit()

    return {
        "name": shift.name,
        "expected_cash": expected_cash,
        "actual_cash": counted_cash,
        "difference": difference,
        "difference_entry": difference_entry,
        "closing_cash_movements": closing_movements,
        "electronic_entries": electronic_entries,
        "delivery_entries": delivery_entries,
        "auto_finalized_delivery_settlements": auto_finalized_settlements,
    }


@frappe.whitelist()
def repair_shift_financial_flow(shift_name):
    """
    Backfill opening float, electronic reconciliations, and split closing
    cash movements for an existing test shift.

    Existing submitted movements are reused.
    """
    frappe.only_for("System Manager")

    shift = frappe.get_doc(
        "Pharmacy Shift Closing",
        shift_name,
    )
    results = {
        "shift": shift.name,
        "opening": None,
        "electronic_reconciliations": [],
        "closing_cash_movements": [],
    }

    opening_balance = _money(
        shift.opening_balance
    )
    opening_name = _opening_movement_name(
        shift
    )

    if opening_balance > 0 and not opening_name:
        opening = _create_shift_cash_movement(
            shift=shift,
            movement_type="Opening Float",
            direction="In",
            amount=opening_balance,
            description=(
                "Opening float repair for shift "
                + shift.name
            ),
            source_account="Main Safe - C",
            target_account=(
                shift.get("cash_account")
                or CASH_ACCOUNT
            ),
            movement_date=(
                shift.start_time
                or shift.creation
            ),
        )
        opening_name = opening["name"]
        results["opening"] = opening

    elif opening_name:
        results["opening"] = {
            "name": opening_name,
            "journal_entry": frappe.db.get_value(
                "Shift Cash Movement",
                opening_name,
                "journal_entry",
            ),
        }

    if (
        opening_name
        and _has_field(
            "Pharmacy Shift Closing",
            "opening_cash_movement",
        )
    ):
        frappe.db.set_value(
            "Pharmacy Shift Closing",
            shift.name,
            "opening_cash_movement",
            opening_name,
            update_modified=False,
        )

    results[
        "electronic_reconciliations"
    ] = _auto_reconcile_shift_modes(shift)

    is_closed = (
        shift.docstatus == 1
        or shift.status == "Closed"
        or bool(shift.end_time)
    )
    actual_cash = _money(
        shift.actual_cash
    )

    if is_closed and actual_cash > TOLERANCE:
        results[
            "closing_cash_movements"
        ] = _create_closing_cash_movements(
            shift,
            actual_cash,
        )

    frappe.db.commit()
    frappe.clear_cache()

    return results
