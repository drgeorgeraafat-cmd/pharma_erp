import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

REQUEST_DOCTYPE = "Delivery Return Request"
ITEM_DOCTYPE = "Delivery Return Item"
RETURN_TYPE_PARTIAL = "Partial Item Return"
RETURN_TYPE_FULL = "Full Order Cancellation"

STATUS_REQUESTED = "Requested"
STATUS_RETURNING = "Returning to Pharmacy"
STATUS_RETURNED = "Returned to Pharmacy"
STATUS_AWAITING_REVIEW = "Awaiting Manager Review"
STATUS_CREDIT_NOTE_DRAFT = "Credit Note Draft"
STATUS_PARTIAL_COMPLETED = "Partial Return Completed"
STATUS_FULL_COMPLETED = "Full Return Completed"
STATUS_CANCELLED = "Cancelled"

INVOICE_ACTIVE_REQUEST = "custom_active_delivery_return_request"
INVOICE_LAST_REQUEST = "custom_last_delivery_return_request"
INVOICE_RETURN_TYPE = "custom_delivery_return_type"
INVOICE_RETURN_STATUS = "custom_delivery_return_status"
INVOICE_RETURN_REASON = "custom_delivery_return_reason"
INVOICE_RETURN_NOTES = "custom_delivery_return_notes"
INVOICE_RETURN_CREDIT_NOTE = "custom_delivery_return_credit_note"
INVOICE_DRIVER_RETURN_STATUS = "custom_driver_return_status"
INVOICE_DRIVER_RETURNED_AT = "custom_driver_returned_at"

ADD_ON_CHECK_FIELD = "custom_add_on_delivery_invoice"
ADD_ON_PARENT_FIELD = "custom_parent_delivery_invoice"
RETURN_ITEM_SOURCE_INVOICE_FIELD = "source_invoice"
RETURN_ITEM_CREDIT_NOTE_FIELD = "credit_note"

PARTIAL_RETURN_REQUESTED = "Partial Return Requested"
PARTIAL_RETURN_RETURNING = "Partial Return Returning"
PARTIAL_RETURN_AWAITING = "Partial Return Awaiting Review"
PARTIAL_CREDIT_NOTE_DRAFT = "Partial Credit Note Draft"
PARTIAL_RETURN_COMPLETED = "Partial Return Completed"

PARTIAL_REASONS = {
    "Item Rejected by Customer",
    "Wrong Item",
    "Damaged Item",
    "Payment Problem",
    "Other",
}

# Sales Invoice and Delivery Return Request share the same operational reason.
# Keep the two Select fields aligned with the union of full-order and partial-item
# return reasons. Older installers could overwrite Delivery Return Request.reason
# with only the partial-return list, which made values such as
# "Customer Not Answering" fail validation during a full return.
FULL_REASON_OPTION_ORDER = (
    "Customer Cancelled Order",
    "Customer Refused Order",
    "Customer Not Answering",
    "Wrong Address",
    "Payment Problem",
    "Other",
)

PARTIAL_REASON_OPTION_ORDER = (
    "Item Rejected by Customer",
    "Wrong Item",
    "Damaged Item",
    "Payment Problem",
    "Other",
)

RETURN_REASON_OPTION_ORDER = tuple(
    dict.fromkeys(FULL_REASON_OPTION_ORDER + PARTIAL_REASON_OPTION_ORDER)
)

REQUEST_STATUS_OPTION_ORDER = (
    STATUS_REQUESTED,
    STATUS_RETURNING,
    STATUS_RETURNED,
    STATUS_AWAITING_REVIEW,
    STATUS_CREDIT_NOTE_DRAFT,
    STATUS_PARTIAL_COMPLETED,
    STATUS_FULL_COMPLETED,
    STATUS_CANCELLED,
)

INVOICE_RETURN_STATUS_OPTION_ORDER = (
    "Not Required",
    "Returning to Pharmacy",
    "Awaiting Manager Review",
    "Credit Note Draft",
    "Return Completed",
    PARTIAL_RETURN_REQUESTED,
    PARTIAL_RETURN_RETURNING,
    PARTIAL_RETURN_AWAITING,
    PARTIAL_CREDIT_NOTE_DRAFT,
    PARTIAL_RETURN_COMPLETED,
)



PACK_SIZE_FIELD_CANDIDATES = (
    "custom_pack_size",
    "pack_size",
    "custom_units_per_box",
    "custom_strips_per_box",
    "custom_units_in_box",
)


def _has_field(doctype, fieldname):
    return bool(frappe.get_meta(doctype).has_field(fieldname))


def _set_if_field(doc, fieldname, value):
    if _has_field(doc.doctype, fieldname):
        doc.set(fieldname, value)


def _split_select_options(value):
    return [
        str(option or "").strip()
        for option in str(value or "").replace("\r", "").split("\n")
        if str(option or "").strip()
    ]


@frappe.whitelist()
def ensure_partial_return_reason_options():
    """Keep full and partial return reasons aligned on both Select fields.

    The function name is retained for backward compatibility with existing
    callers. It is safe to call repeatedly and upgrades both:
    - Sales Invoice.custom_delivery_return_reason
    - Delivery Return Request.reason
    """
    results = []

    results.append(
        _ensure_select_options(
            "Sales Invoice",
            INVOICE_RETURN_REASON,
            RETURN_REASON_OPTION_ORDER,
        )
    )

    if frappe.db.exists("DocType", REQUEST_DOCTYPE):
        results.append(
            _ensure_select_options(
                REQUEST_DOCTYPE,
                "reason",
                RETURN_REASON_OPTION_ORDER,
            )
        )

    return {
        "updated": any(result.get("updated") for result in results),
        "results": results,
        "options": list(RETURN_REASON_OPTION_ORDER),
    }


def _ensure_select_options(doctype, fieldname, required_options):
    """Ensure a Select field contains all workflow values used by this module."""
    if not _has_field(doctype, fieldname):
        return {
            "updated": False,
            "doctype": doctype,
            "field": fieldname,
            "reason": "field_missing",
        }

    field = frappe.get_meta(doctype).get_field(fieldname)
    current_options = _split_select_options(getattr(field, "options", ""))
    missing = [option for option in required_options if option not in current_options]
    if not missing:
        return {
            "updated": False,
            "doctype": doctype,
            "field": fieldname,
            "options": current_options,
        }

    combined = current_options + missing

    custom_field_name = frappe.db.get_value(
        "Custom Field",
        {"dt": doctype, "fieldname": fieldname},
        "name",
    )
    if custom_field_name:
        frappe.db.set_value(
            "Custom Field",
            custom_field_name,
            "options",
            "\n".join(combined),
            update_modified=False,
        )
    else:
        docfield_name = frappe.db.get_value(
            "DocField",
            {
                "parent": doctype,
                "parenttype": "DocType",
                "fieldname": fieldname,
            },
            "name",
        )
        if not docfield_name:
            frappe.throw(
                _(
                    "تعذر تحديث اختيارات الحقل {0}.{1}. أضف الاختيارات التالية يدويًا: {2}"
                ).format(doctype, fieldname, ", ".join(missing))
            )
        frappe.db.set_value(
            "DocField",
            docfield_name,
            "options",
            "\n".join(combined),
            update_modified=False,
        )

    frappe.clear_cache(doctype=doctype)
    return {
        "updated": True,
        "doctype": doctype,
        "field": fieldname,
        "added": missing,
        "options": combined,
    }


@frappe.whitelist()
def ensure_partial_return_status_options():
    """Keep request and invoice workflow statuses aligned across old installs."""
    results = []
    if frappe.db.exists("DocType", REQUEST_DOCTYPE):
        results.append(
            _ensure_select_options(
                REQUEST_DOCTYPE,
                "status",
                REQUEST_STATUS_OPTION_ORDER,
            )
        )
    results.append(
        _ensure_select_options(
            "Sales Invoice",
            INVOICE_RETURN_STATUS,
            INVOICE_RETURN_STATUS_OPTION_ORDER,
        )
    )
    return results


def _clean_pack_size(value):
    value = flt(value or 0, 6)
    if value <= 0:
        return 0.0
    rounded = round(value)
    return float(rounded) if abs(value - rounded) <= 1e-6 else value


def _field_looks_like_pack_size(field):
    fieldname = str(getattr(field, "fieldname", "") or "").strip().lower()
    label = str(getattr(field, "label", "") or "").strip().lower()
    searchable = f"{fieldname} {label}".replace("_", " ")
    if fieldname in PACK_SIZE_FIELD_CANDIDATES:
        return True
    english_match = (
        ("pack" in searchable and ("size" in searchable or "qty" in searchable))
        or ("unit" in searchable and "box" in searchable)
        or ("strip" in searchable and "box" in searchable)
    )
    arabic_match = any(
        phrase in searchable
        for phrase in (
            "حجم العبوة",
            "عدد الوحدات في العلبة",
            "عدد الوحدات بالعلبة",
            "عدد الشرائط في العلبة",
            "عدد الشرائط بالعلبة",
        )
    )
    return english_match or arabic_match


def _pack_size_from_uoms(item_doc):
    rows = item_doc.get("uoms") or []
    if not rows:
        return 0.0

    stock_uom = str(item_doc.get("stock_uom") or "").strip().lower()
    box_words = ("box", "pack", "علبة", "عبوة")
    unit_words = ("strip", "unit", "piece", "شريط", "وحدة", "قطعة")
    stock_is_box = any(word in stock_uom for word in box_words)

    if stock_is_box:
        smaller = []
        preferred = []
        for row in rows:
            factor = _clean_pack_size(row.get("conversion_factor"))
            uom = str(row.get("uom") or "").strip().lower()
            if 0 < factor < 1:
                smaller.append(factor)
                if any(word in uom for word in unit_words):
                    preferred.append(factor)
        factors = preferred or smaller
        if factors:
            # أقرب وحدة أصغر من العلبة هي الأنسب لحقل «وحدات/شرائط».
            return _clean_pack_size(1.0 / max(factors))

    larger_boxes = []
    for row in rows:
        factor = _clean_pack_size(row.get("conversion_factor"))
        uom = str(row.get("uom") or "").strip().lower()
        if factor > 1 and any(word in uom for word in box_words):
            larger_boxes.append(factor)
    if larger_boxes:
        return _clean_pack_size(min(larger_boxes))
    return 0.0


def _resolve_pack_size(source_item):
    """Return the authoritative units/strips count in one sold box.

    The browser value is never trusted.  The value is resolved from the
    Sales Invoice Item, then Item custom fields, then Item UOM conversions.
    A default value of 1 on the invoice row must not hide a real Item value.
    """
    row_fallback = 0.0
    for fieldname in PACK_SIZE_FIELD_CANDIDATES:
        value = _clean_pack_size(source_item.get(fieldname))
        if value > 1:
            return value
        row_fallback = row_fallback or value

    item_code = str(source_item.get("item_code") or "").strip()
    if not item_code or not frappe.db.exists("Item", item_code):
        return row_fallback or 1.0

    item_doc = frappe.get_cached_doc("Item", item_code)
    item_fallback = 0.0
    for fieldname in PACK_SIZE_FIELD_CANDIDATES:
        value = _clean_pack_size(item_doc.get(fieldname))
        if value > 1:
            return value
        item_fallback = item_fallback or value

    for field in frappe.get_meta("Item").fields:
        if field.fieldtype not in {"Int", "Float", "Currency"}:
            continue
        if not _field_looks_like_pack_size(field):
            continue
        value = _clean_pack_size(item_doc.get(field.fieldname))
        if value > 1:
            return value
        item_fallback = item_fallback or value

    uom_pack_size = _pack_size_from_uoms(item_doc)
    if uom_pack_size > 1:
        return uom_pack_size
    return item_fallback or row_fallback or 1.0


def _whole_non_negative(value, label, item_code):
    number = max(0.0, flt(value or 0, 6))
    rounded = round(number)
    if abs(number - rounded) > 1e-6:
        frappe.throw(
            _("{0} للصنف {1} يجب أن تكون رقمًا صحيحًا.").format(label, item_code)
        )
    return float(rounded)


def _returned_qty(invoice_name, source_item):
    return abs(
        flt(
            frappe.db.sql(
                """
                SELECT COALESCE(SUM(ABS(rii.qty)), 0)
                FROM `tabSales Invoice Item` rii
                INNER JOIN `tabSales Invoice` ri ON ri.name = rii.parent
                WHERE ri.docstatus = 1
                  AND ri.is_return = 1
                  AND ri.return_against = %(invoice)s
                  AND rii.sales_invoice_item = %(source_item)s
                """,
                {"invoice": invoice_name, "source_item": source_item},
            )[0][0]
        )
    )


def _delivery_fee_item():
    if not frappe.db.exists("DocType", "Pharmacy POS Settings"):
        return ""
    try:
        return frappe.db.get_single_value("Pharmacy POS Settings", "delivery_fee_item") or ""
    except Exception:
        return ""


def _root_delivery_invoice(invoice):
    """Return the operational parent invoice for a delivery group."""
    if isinstance(invoice, str):
        invoice = frappe.get_doc("Sales Invoice", invoice)
    if (
        _has_field("Sales Invoice", ADD_ON_PARENT_FIELD)
        and str(invoice.get(ADD_ON_PARENT_FIELD) or "").strip()
    ):
        parent_name = str(invoice.get(ADD_ON_PARENT_FIELD) or "").strip()
        if frappe.db.exists("Sales Invoice", parent_name):
            return frappe.get_doc("Sales Invoice", parent_name)
    return invoice


def _delivery_group_invoices(invoice):
    """Return the parent invoice followed by every submitted add-on invoice."""
    parent = _root_delivery_invoice(invoice)
    invoices = [parent]
    if not _has_field("Sales Invoice", ADD_ON_PARENT_FIELD):
        return invoices

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
    return invoices


def _request_item_source_invoice(request, row):
    return str(row.get(RETURN_ITEM_SOURCE_INVOICE_FIELD) or request.sales_invoice or "").strip()


def _request_item_credit_note(row):
    return str(row.get(RETURN_ITEM_CREDIT_NOTE_FIELD) or "").strip()


def _request_credit_notes(request):
    notes = []
    for row in request.items or []:
        name = _request_item_credit_note(row)
        if name and name not in notes:
            notes.append(name)
    if request.get("credit_note") and request.credit_note not in notes:
        notes.insert(0, request.credit_note)
    return notes


def _request_all_credit_notes_submitted(request):
    if not request.items:
        return False
    for row in request.items:
        note = _request_item_credit_note(row)
        if not note or not frappe.db.exists("Sales Invoice", note):
            return False
        if cint(frappe.db.get_value("Sales Invoice", note, "docstatus")) != 1:
            return False
    return True

def get_active_request(invoice_name):
    if not frappe.db.exists("DocType", REQUEST_DOCTYPE):
        return None
    linked = ""
    if _has_field("Sales Invoice", INVOICE_ACTIVE_REQUEST):
        linked = frappe.db.get_value("Sales Invoice", invoice_name, INVOICE_ACTIVE_REQUEST) or ""
    if linked and frappe.db.exists(REQUEST_DOCTYPE, linked):
        doc = frappe.get_doc(REQUEST_DOCTYPE, linked)
        if doc.status not in {STATUS_PARTIAL_COMPLETED, STATUS_FULL_COMPLETED, STATUS_CANCELLED}:
            return doc
    rows = frappe.get_all(
        REQUEST_DOCTYPE,
        filters={
            "sales_invoice": invoice_name,
            "status": ["not in", [STATUS_PARTIAL_COMPLETED, STATUS_FULL_COMPLETED, STATUS_CANCELLED]],
        },
        pluck="name",
        order_by="creation desc",
        limit_page_length=1,
    )
    return frappe.get_doc(REQUEST_DOCTYPE, rows[0]) if rows else None


def get_partial_return_items(invoice_name):
    parent = _root_delivery_invoice(invoice_name)
    if parent.docstatus != 1 or cint(parent.get("is_return")):
        frappe.throw(_("اختر فاتورة مبيعات معتمدة."))
    if parent.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("المرتجع الجزئي من صفحة الطيار متاح لأوردرات Home Delivery فقط."))

    fee_item = _delivery_fee_item()
    rows = []
    group_invoices = _delivery_group_invoices(parent)
    supports_group_rows = _has_field(ITEM_DOCTYPE, RETURN_ITEM_SOURCE_INVOICE_FIELD)

    for source in group_invoices:
        is_add_on = source.name != parent.name
        for item in source.items:
            if fee_item and item.item_code == fee_item:
                continue
            sold_qty = abs(flt(item.qty))
            already_returned = _returned_qty(source.name, item.name)
            available = max(0.0, sold_qty - already_returned)
            if available <= 1e-9:
                continue
            if is_add_on and not supports_group_rows:
                frappe.throw(
                    _("شغّل مثبت V2.23 أولًا لتمكين مرتجع أصناف فواتير الإضافة.")
                )
            pack_size = _resolve_pack_size(item)
            rows.append(
                {
                    "source_invoice": source.name,
                    "source_invoice_type": "Add-on" if is_add_on else "Original",
                    "source_item": item.name,
                    "item_code": item.item_code,
                    "item_name": item.item_name or item.item_code,
                    "batch_no": item.batch_no or "",
                    "warehouse": item.warehouse or "",
                    "sold_qty": sold_qty,
                    "previously_returned_qty": already_returned,
                    "returnable_qty": available,
                    "pack_size": pack_size,
                    "returnable_boxes": int(available),
                    "returnable_units": flt((available - int(available)) * pack_size, 6),
                    "rate": abs(flt(item.rate)),
                }
            )

    return {
        "invoice_name": parent.name,
        "customer": parent.customer,
        "customer_name": parent.customer_name,
        "grand_total": flt(sum(flt(doc.grand_total) for doc in group_invoices), 2),
        "outstanding_amount": flt(sum(flt(doc.outstanding_amount) for doc in group_invoices), 2),
        "group_invoices": [doc.name for doc in group_invoices],
        "items": rows,
    }

def _normalize_items(invoice, selections):
    if isinstance(selections, str):
        selections = json.loads(selections)
    selections = selections or []

    parent = _root_delivery_invoice(invoice)
    group_invoices = _delivery_group_invoices(parent)
    source_map = {}
    for source_invoice in group_invoices:
        for row in source_invoice.items:
            source_map[row.name] = (source_invoice, row)

    fee_item = _delivery_fee_item()
    normalized = []
    total = 0.0
    supports_group_rows = _has_field(ITEM_DOCTYPE, RETURN_ITEM_SOURCE_INVOICE_FIELD)

    for raw in selections:
        raw = frappe._dict(raw or {})
        source_item = str(raw.get("source_item") or "").strip()
        if not source_item or source_item not in source_map:
            continue
        source_invoice, source = source_map[source_item]
        sent_source_invoice = str(raw.get("source_invoice") or "").strip()
        if sent_source_invoice and sent_source_invoice != source_invoice.name:
            frappe.throw(_("مصدر الصنف المحدد لا يطابق فاتورة البيع الأصلية."))
        if source_invoice.name != parent.name and not supports_group_rows:
            frappe.throw(_("شغّل مثبت V2.23 أولًا لتمكين مرتجع أصناف فواتير الإضافة."))
        if fee_item and source.item_code == fee_item:
            frappe.throw(_("خدمة التوصيل لا تدخل في المرتجع الجزئي تلقائيًا."))

        pack_size = _resolve_pack_size(source)
        has_split_quantity = raw.get("box_qty") is not None or raw.get("unit_qty") is not None
        if has_split_quantity:
            box_qty = _whole_non_negative(raw.get("box_qty"), _("عدد العلب"), source.item_code)
            unit_qty = _whole_non_negative(raw.get("unit_qty"), _("عدد الوحدات"), source.item_code)
            if pack_size > 1 and unit_qty >= pack_size:
                frappe.throw(
                    _("عدد الوحدات للصنف {0} يجب أن يكون أقل من حجم العبوة ({1}).").format(
                        source.item_code,
                        int(pack_size) if abs(pack_size - round(pack_size)) <= 1e-6 else pack_size,
                    )
                )
            if pack_size <= 1 and unit_qty > 0:
                frappe.throw(
                    _("الصنف {0} لا يحتوي حجم عبوة يسمح بإدخال وحدات منفصلة. استخدم خانة العلب.").format(
                        source.item_code
                    )
                )
            qty = flt(box_qty + unit_qty / pack_size, 6)
        else:
            qty = max(0.0, flt(raw.get("qty"), 6))
            box_qty = float(int(qty))
            unit_qty = flt((qty - int(qty)) * pack_size, 6)
        if qty <= 0:
            continue

        returned = _returned_qty(source_invoice.name, source.name)
        available = max(0.0, abs(flt(source.qty)) - returned)
        if qty - available > 1e-9:
            frappe.throw(
                _("كمية المرتجع للصنف {0} أكبر من الكمية المتاحة ({1}).").format(
                    source.item_code, available
                )
            )
        amount = flt(qty * abs(flt(source.rate)), 2)
        total += amount
        row = {
            "source_item": source.name,
            "item_code": source.item_code,
            "item_name": source.item_name or source.item_code,
            "batch_no": source.batch_no or "",
            "warehouse": source.warehouse or "",
            "sold_qty": abs(flt(source.qty)),
            "previously_returned_qty": returned,
            "return_qty": qty,
            "pack_size": pack_size,
            "return_box_qty": box_qty,
            "return_unit_qty": unit_qty,
            "rate": abs(flt(source.rate)),
            "amount": amount,
            "reason": str(raw.get("reason") or "").strip(),
        }
        if supports_group_rows:
            row[RETURN_ITEM_SOURCE_INVOICE_FIELD] = source_invoice.name
        normalized.append(row)

    if not normalized:
        frappe.throw(_("حدد صنفًا واحدًا على الأقل وكمية مرتجع أكبر من صفر."))
    return normalized, flt(total, 2)

def create_partial_return_request(
    invoice_name,
    items,
    reason,
    notes=None,
    actor=None,
    request_source="Driver Report",
    approved_by=None,
):
    if not frappe.db.exists("DocType", REQUEST_DOCTYPE):
        frappe.throw(_("شغّل مثبت V2.22 لإنشاء Delivery Return Request أولًا."))

    ensure_partial_return_reason_options()
    ensure_partial_return_status_options()
    source = _root_delivery_invoice(invoice_name)
    if source.docstatus != 1 or cint(source.get("is_return")):
        frappe.throw(_("الفاتورة المحددة غير صالحة للمرتجع الجزئي."))
    if source.get("custom_order_type") != "Home Delivery":
        frappe.throw(_("الفاتورة المحددة ليست Home Delivery."))
    if str(source.get("custom_delivery_status") or "") != "Out for Delivery":
        frappe.throw(_("يمكن تسجيل المرتجع الجزئي أثناء خروج الأوردر للتوصيل فقط."))
    if get_active_request(source.name):
        frappe.throw(_("يوجد طلب مرتجع مفتوح بالفعل لهذا الأوردر."))

    reason = str(reason or "").strip()
    notes = str(notes or "").strip()
    if reason not in PARTIAL_REASONS:
        frappe.throw(_("اختر سببًا صحيحًا للمرتجع الجزئي."))
    if reason == "Other" and not notes:
        frappe.throw(_("اكتب سبب المرتجع الجزئي في الملاحظات."))

    normalized, estimated_amount = _normalize_items(source, items)
    group_invoices = _delivery_group_invoices(source)
    group_grand_total = flt(sum(flt(doc.grand_total) for doc in group_invoices), 2)
    group_outstanding = flt(sum(flt(doc.outstanding_amount) for doc in group_invoices), 2)

    request = frappe.new_doc(REQUEST_DOCTYPE)
    request.return_type = RETURN_TYPE_PARTIAL
    request.status = STATUS_RETURNING
    request.sales_invoice = source.name
    request.company = source.company
    request.customer = source.customer
    request.delivery_boy = source.get("custom_delivery_boy") or ""
    request.delivery_trip = source.get("custom_delivery_trip") or ""
    request.sales_shift = source.get("custom_pharmacy_shift") or ""
    request.delivery_shift = source.get("custom_delivery_shift") or source.get("custom_pharmacy_shift") or ""
    request.reason = reason
    request.notes = notes
    request.source_grand_total = group_grand_total
    request.estimated_return_amount = estimated_amount
    request.remaining_collectible = max(0.0, group_outstanding - estimated_amount)
    request.requested_by = actor or frappe.session.user
    request.requested_at = now_datetime()
    _set_if_field(request, "request_source", request_source or "Driver Report")
    if approved_by:
        _set_if_field(request, "approved_by", approved_by)
        _set_if_field(request, "approved_at", now_datetime())
    for row in normalized:
        request.append("items", row)
    request.flags.ignore_permissions = True
    request.insert(ignore_permissions=True)

    _set_if_field(source, INVOICE_ACTIVE_REQUEST, request.name)
    _set_if_field(source, INVOICE_LAST_REQUEST, request.name)
    _set_if_field(source, INVOICE_RETURN_TYPE, RETURN_TYPE_PARTIAL)
    _set_if_field(source, INVOICE_RETURN_STATUS, PARTIAL_RETURN_RETURNING)
    _set_if_field(source, INVOICE_RETURN_REASON, reason)
    _set_if_field(source, INVOICE_RETURN_NOTES, notes)
    _set_if_field(source, INVOICE_DRIVER_RETURN_STATUS, "Returning to Pharmacy")
    source.flags.ignore_validate_update_after_submit = True
    source.save(ignore_permissions=True)
    source.add_comment(
        "Comment",
        _("تم تسجيل مرتجع جزئي بقيمة تقديرية {0} من مجموعة فواتير الأوردر. الطلب: {1}. المصدر: {2}.").format(
            frappe.format_value(estimated_amount, {"fieldtype": "Currency", "options": source.currency}),
            request.name,
            request_source or "Driver Report",
        ),
    )
    return request_summary(request)

def adjusted_expected_collection(invoice, base_expected):
    request = get_active_request(invoice.name if hasattr(invoice, "name") else str(invoice))
    if not request or request.return_type != RETURN_TYPE_PARTIAL:
        return flt(base_expected, 6)
    return max(0.0, flt(base_expected, 6) - flt(request.estimated_return_amount, 6))


def mark_request_driver_returned(invoice):
    """Move an active return request to manager review and persist both records.

    Older workflow versions could save the physical driver-return flag while
    leaving the partial-return status at "Returning". This function writes the
    two linked documents explicitly so the manager receives the review action.
    """
    ensure_partial_return_status_options()

    request = get_active_request(invoice.name)
    if not request:
        return None
    if request.status in {STATUS_PARTIAL_COMPLETED, STATUS_FULL_COMPLETED, STATUS_CANCELLED}:
        return request

    now = now_datetime()

    frappe.db.set_value(
        REQUEST_DOCTYPE,
        request.name,
        {
            "status": STATUS_AWAITING_REVIEW,
            "driver_returned_at": request.get("driver_returned_at") or now,
        },
        update_modified=False,
    )

    invoice_values = {}
    if _has_field("Sales Invoice", INVOICE_DRIVER_RETURN_STATUS):
        invoice_values[INVOICE_DRIVER_RETURN_STATUS] = "Returned to Pharmacy"
    if _has_field("Sales Invoice", INVOICE_DRIVER_RETURNED_AT):
        invoice_values[INVOICE_DRIVER_RETURNED_AT] = invoice.get(INVOICE_DRIVER_RETURNED_AT) or now
    if request.return_type == RETURN_TYPE_PARTIAL:
        if _has_field("Sales Invoice", INVOICE_RETURN_TYPE):
            invoice_values[INVOICE_RETURN_TYPE] = RETURN_TYPE_PARTIAL
        if _has_field("Sales Invoice", INVOICE_RETURN_STATUS):
            invoice_values[INVOICE_RETURN_STATUS] = PARTIAL_RETURN_AWAITING

    if invoice_values:
        frappe.db.set_value(
            "Sales Invoice",
            invoice.name,
            invoice_values,
            update_modified=False,
        )
        for fieldname, value in invoice_values.items():
            invoice.set(fieldname, value)

    request.reload()
    return request


def confirm_partial_return_received(invoice_name):
    source = frappe.get_doc("Sales Invoice", invoice_name)
    request = get_active_request(source.name)
    if not request or request.return_type != RETURN_TYPE_PARTIAL:
        frappe.throw(_("لا يوجد طلب مرتجع جزئي مفتوح لهذا الأوردر."))
    if str(source.get(INVOICE_DRIVER_RETURN_STATUS) or "") != "Returned to Pharmacy":
        frappe.throw(_("يجب أن يسجل الطيار الرجوع إلى الصيدلية أولًا."))
    if request.status in {STATUS_PARTIAL_COMPLETED, STATUS_FULL_COMPLETED, STATUS_CANCELLED}:
        frappe.throw(_("طلب المرتجع الجزئي مغلق بالفعل."))

    ensure_partial_return_status_options()
    now = now_datetime()
    frappe.db.set_value(
        REQUEST_DOCTYPE,
        request.name,
        {
            "status": STATUS_AWAITING_REVIEW,
            "driver_returned_at": request.get("driver_returned_at")
            or source.get(INVOICE_DRIVER_RETURNED_AT)
            or now,
            "received_by": frappe.session.user,
            "received_at": now,
        },
        update_modified=False,
    )
    if _has_field("Sales Invoice", INVOICE_RETURN_STATUS):
        frappe.db.set_value(
            "Sales Invoice",
            source.name,
            INVOICE_RETURN_STATUS,
            PARTIAL_RETURN_AWAITING,
            update_modified=False,
        )

    request.reload()
    return request_summary(request)


def _request_returned_qty(request, source_item):
    return sum(flt(row.return_qty) for row in request.items if row.source_item == source_item)


def _validate_credit_note_matches_request(source, request, return_doc):
    expected_rows = {
        row.source_item: row
        for row in request.items
        if _request_item_source_invoice(request, row) == source.name
    }
    if not expected_rows:
        frappe.throw(_("لا توجد أصناف في طلب المرتجع تخص الفاتورة {0}.").format(source.name))

    returned = {}
    for row in return_doc.items:
        if row.sales_invoice_item:
            returned[row.sales_invoice_item] = returned.get(row.sales_invoice_item, 0.0) + abs(flt(row.qty))

    unexpected = [item_name for item_name in returned if item_name not in expected_rows]
    if unexpected:
        frappe.throw(_("مرتجع المبيعات يحتوي أصنافًا غير موجودة في طلب المرتجع الجزئي."))

    for source_item, item in expected_rows.items():
        actual = flt(returned.get(source_item), 6)
        expected = flt(item.return_qty, 6)
        if abs(actual - expected) > 1e-6:
            frappe.throw(
                _("مرتجع المبيعات لا يطابق طلب المرتجع {0} للصنف {1}: المطلوب {2} والمنفذ {3}.").format(
                    request.name, item.item_code, expected, actual
                )
            )

def sync_partial_return_credit_note(source, return_doc, request_name=None):
    request = None
    if request_name and frappe.db.exists(REQUEST_DOCTYPE, request_name):
        request = frappe.get_doc(REQUEST_DOCTYPE, request_name)
    if not request:
        parent = _root_delivery_invoice(source)
        request = get_active_request(parent.name)
    if not request or request.return_type != RETURN_TYPE_PARTIAL:
        return frappe._dict({"linked": False, "complete": False})

    valid_source_invoices = {
        _request_item_source_invoice(request, row)
        for row in request.items
    }
    if source.name not in valid_source_invoices:
        frappe.throw(_("طلب المرتجع لا يحتوي أصنافًا من الفاتورة المحددة."))

    _validate_credit_note_matches_request(source, request, return_doc)
    returned_item_map = {
        row.sales_invoice_item: row.name
        for row in return_doc.items
        if row.sales_invoice_item
    }
    for row in request.items:
        if _request_item_source_invoice(request, row) != source.name:
            continue
        if _has_field(ITEM_DOCTYPE, RETURN_ITEM_CREDIT_NOTE_FIELD):
            row.set(RETURN_ITEM_CREDIT_NOTE_FIELD, return_doc.name)
        if _has_field(ITEM_DOCTYPE, "credit_note_item"):
            row.credit_note_item = returned_item_map.get(row.source_item) or ""
        if _has_field(ITEM_DOCTYPE, "completed"):
            row.completed = 1 if return_doc.docstatus == 1 else 0

    if not request.get("credit_note"):
        request.credit_note = return_doc.name
    request.status = STATUS_CREDIT_NOTE_DRAFT if return_doc.docstatus != 1 else STATUS_AWAITING_REVIEW
    request.flags.ignore_permissions = True
    request.save(ignore_permissions=True)

    _set_if_field(source, INVOICE_RETURN_CREDIT_NOTE, return_doc.name)
    _set_if_field(source, INVOICE_RETURN_STATUS, PARTIAL_CREDIT_NOTE_DRAFT if return_doc.docstatus != 1 else PARTIAL_RETURN_AWAITING)
    source.flags.ignore_validate_update_after_submit = True
    source.save(ignore_permissions=True)

    parent = frappe.get_doc("Sales Invoice", request.sales_invoice)
    _set_if_field(parent, INVOICE_RETURN_CREDIT_NOTE, request.credit_note or return_doc.name)
    _set_if_field(parent, INVOICE_RETURN_STATUS, PARTIAL_CREDIT_NOTE_DRAFT if return_doc.docstatus != 1 else PARTIAL_RETURN_AWAITING)
    parent.flags.ignore_validate_update_after_submit = True
    parent.save(ignore_permissions=True)

    if return_doc.docstatus == 1 and _request_all_credit_notes_submitted(request):
        return complete_partial_return_request(parent.name, request.name)
    return frappe._dict({
        "linked": True,
        "complete": False,
        "request": request.name,
        "credit_note": return_doc.name,
        "credit_notes": _request_credit_notes(request),
    })

def complete_partial_return_request(invoice_name, request_name=None):
    source = _root_delivery_invoice(invoice_name)
    request = frappe.get_doc(REQUEST_DOCTYPE, request_name) if request_name else get_active_request(source.name)
    if not request or request.return_type != RETURN_TYPE_PARTIAL:
        frappe.throw(_("لا يوجد طلب مرتجع جزئي مفتوح لهذا الأوردر."))
    if not _request_all_credit_notes_submitted(request):
        frappe.throw(_("لم يتم إنشاء واعتماد كل مرتجعات المبيعات الخاصة بطلب المرتجع الجزئي."))

    from pharma_erp.pharma_erp.delivery_return_workflow import _reconcile_credit_note_against_invoice

    grouped = {}
    for row in request.items:
        source_invoice = _request_item_source_invoice(request, row)
        credit_note = _request_item_credit_note(row)
        grouped.setdefault((source_invoice, credit_note), []).append(row)

    reconciled_total = 0.0
    credit_notes = []
    for (source_invoice_name, credit_note_name), rows in grouped.items():
        if not source_invoice_name or not credit_note_name:
            frappe.throw(_("بيانات مصدر المرتجع أو مرتجع المبيعات غير مكتملة."))
        source_invoice = frappe.get_doc("Sales Invoice", source_invoice_name)
        credit_note = frappe.get_doc("Sales Invoice", credit_note_name)
        if credit_note.docstatus != 1:
            frappe.throw(_("اعتمد مرتجع المبيعات {0} أولًا.").format(credit_note.name))
        if credit_note.get("return_against") != source_invoice.name:
            frappe.throw(_("مرتجع المبيعات {0} لا يخص الفاتورة {1}.").format(credit_note.name, source_invoice.name))
        _validate_credit_note_matches_request(source_invoice, request, credit_note)
        reconciled_total += flt(_reconcile_credit_note_against_invoice(source_invoice.name, credit_note.name), 2)
        if credit_note.name not in credit_notes:
            credit_notes.append(credit_note.name)

    group_invoices = _delivery_group_invoices(source)
    remaining_group_outstanding = flt(
        sum(flt(frappe.db.get_value("Sales Invoice", doc.name, "outstanding_amount") or 0) for doc in group_invoices),
        2,
    )

    request.status = STATUS_PARTIAL_COMPLETED
    request.reconciled_amount = flt(reconciled_total, 2)
    request.remaining_invoice_outstanding = remaining_group_outstanding
    request.completed_by = frappe.session.user
    request.completed_at = now_datetime()
    if credit_notes and not request.get("credit_note"):
        request.credit_note = credit_notes[0]
    request.flags.ignore_permissions = True
    request.save(ignore_permissions=True)

    source = frappe.get_doc("Sales Invoice", source.name)
    _set_if_field(source, INVOICE_ACTIVE_REQUEST, "")
    _set_if_field(source, INVOICE_LAST_REQUEST, request.name)
    _set_if_field(source, INVOICE_RETURN_TYPE, RETURN_TYPE_PARTIAL)
    _set_if_field(source, INVOICE_RETURN_STATUS, PARTIAL_RETURN_COMPLETED)
    _set_if_field(source, INVOICE_RETURN_CREDIT_NOTE, credit_notes[0] if credit_notes else request.get("credit_note") or "")
    source.custom_delivery_status = "Delivered"
    source.flags.ignore_validate_update_after_submit = True
    source.save(ignore_permissions=True)
    source.add_comment(
        "Comment",
        _("اكتمل المرتجع الجزئي {0}. مرتجعات المبيعات: {1}. المتبقي على مجموعة الأوردر: {2}.").format(
            request.name,
            ", ".join(credit_notes),
            frappe.format_value(remaining_group_outstanding, {"fieldtype": "Currency", "options": source.currency}),
        ),
    )
    result = request_summary(request)
    result.update({
        "linked": True,
        "complete": True,
        "reconciled_amount": flt(reconciled_total, 2),
        "credit_notes": credit_notes,
    })
    return frappe._dict(result)

def request_summary(request):
    if isinstance(request, str):
        request = frappe.get_doc(REQUEST_DOCTYPE, request)
    credit_notes = _request_credit_notes(request)
    return {
        "name": request.name,
        "sales_invoice": request.sales_invoice,
        "return_type": request.return_type,
        "status": request.status,
        "estimated_return_amount": flt(request.estimated_return_amount, 2),
        "remaining_collectible": flt(request.remaining_collectible, 2),
        "credit_note": request.credit_note or "",
        "credit_notes": credit_notes,
        "request_source": request.get("request_source") or "Driver Report",
        "approved_by": request.get("approved_by") or "",
        "approved_at": request.get("approved_at"),
        "items": [
            {
                "source_invoice": _request_item_source_invoice(request, row),
                "source_item": row.source_item,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "return_qty": flt(row.return_qty, 6),
                "rate": flt(row.rate, 2),
                "amount": flt(row.amount, 2),
                "credit_note": _request_item_credit_note(row),
            }
            for row in request.items
        ],
    }

def annotate_orders(orders):
    """Attach request details and repair stale linked workflow states."""
    for order in orders or []:
        request_name = order.get(INVOICE_ACTIVE_REQUEST) or ""
        if not request_name or not frappe.db.exists(REQUEST_DOCTYPE, request_name):
            order["partial_return_request"] = None
            continue

        request = frappe.get_doc(REQUEST_DOCTYPE, request_name)
        driver_status = str(order.get(INVOICE_DRIVER_RETURN_STATUS) or "").strip()
        invoice_return_status = str(order.get(INVOICE_RETURN_STATUS) or "").strip()

        if (
            request.return_type == RETURN_TYPE_PARTIAL
            and driver_status == "Returned to Pharmacy"
            and request.status not in {
                STATUS_AWAITING_REVIEW,
                STATUS_CREDIT_NOTE_DRAFT,
                STATUS_PARTIAL_COMPLETED,
                STATUS_CANCELLED,
            }
        ):
            ensure_partial_return_status_options()
            returned_at = order.get(INVOICE_DRIVER_RETURNED_AT) or now_datetime()
            frappe.db.set_value(
                REQUEST_DOCTYPE,
                request.name,
                {
                    "status": STATUS_AWAITING_REVIEW,
                    "driver_returned_at": request.get("driver_returned_at") or returned_at,
                },
                update_modified=False,
            )
            if invoice_return_status != PARTIAL_RETURN_AWAITING:
                frappe.db.set_value(
                    "Sales Invoice",
                    order.name,
                    INVOICE_RETURN_STATUS,
                    PARTIAL_RETURN_AWAITING,
                    update_modified=False,
                )
                order[INVOICE_RETURN_STATUS] = PARTIAL_RETURN_AWAITING
            request.reload()

        elif (
            request.return_type == RETURN_TYPE_PARTIAL
            and request.status == STATUS_AWAITING_REVIEW
            and invoice_return_status != PARTIAL_RETURN_AWAITING
        ):
            ensure_partial_return_status_options()
            frappe.db.set_value(
                "Sales Invoice",
                order.name,
                INVOICE_RETURN_STATUS,
                PARTIAL_RETURN_AWAITING,
                update_modified=False,
            )
            order[INVOICE_RETURN_STATUS] = PARTIAL_RETURN_AWAITING

        order["partial_return_request"] = request_summary(request)
    return orders



@frappe.whitelist()
def repair_existing_partial_return(invoice_name, credit_note_name):
    source = frappe.get_doc("Sales Invoice", invoice_name)
    credit = frappe.get_doc("Sales Invoice", credit_note_name)
    if credit.docstatus != 1 or not cint(credit.get("is_return")) or credit.get("return_against") != source.name:
        frappe.throw(_("مرتجع المبيعات المحدد غير صالح لهذه الفاتورة."))
    active = get_active_request(source.name)
    if active:
        request = active
    else:
        request = frappe.new_doc(REQUEST_DOCTYPE)
        request.return_type = RETURN_TYPE_PARTIAL
        request.status = STATUS_AWAITING_REVIEW
        request.sales_invoice = source.name
        request.company = source.company
        request.customer = source.customer
        request.delivery_boy = source.get("custom_delivery_boy") or ""
        request.delivery_trip = source.get("custom_delivery_trip") or ""
        request.sales_shift = source.get("custom_pharmacy_shift") or ""
        request.delivery_shift = source.get("custom_delivery_shift") or source.get("custom_pharmacy_shift") or ""
        request.reason = "Item Rejected by Customer"
        request.notes = "Converted from an existing partial Credit Note."
        request.source_grand_total = flt(source.grand_total, 2)
        request.requested_by = frappe.session.user
        request.requested_at = now_datetime()
        total = 0.0
        source_map = {row.name: row for row in source.items}
        for row in credit.items:
            if not row.sales_invoice_item or row.sales_invoice_item not in source_map:
                continue
            original = source_map[row.sales_invoice_item]
            qty = abs(flt(row.qty))
            amount = abs(flt(row.amount))
            total += amount
            request.append(
                "items",
                {
                    "source_item": original.name,
                    **({RETURN_ITEM_SOURCE_INVOICE_FIELD: source.name} if _has_field(ITEM_DOCTYPE, RETURN_ITEM_SOURCE_INVOICE_FIELD) else {}),
                    "item_code": original.item_code,
                    "item_name": original.item_name or original.item_code,
                    "batch_no": original.batch_no or "",
                    "warehouse": original.warehouse or "",
                    "sold_qty": abs(flt(original.qty)),
                    "previously_returned_qty": max(0.0, _returned_qty(source.name, original.name) - qty),
                    "return_qty": qty,
                    "pack_size": _resolve_pack_size(original),
                    "rate": abs(flt(original.rate)),
                    "amount": amount,
                },
            )
        if not request.items:
            frappe.throw(_("لم يتم العثور على بنود مرتبطة بالفاتورة الأصلية داخل مرتجع المبيعات."))
        request.estimated_return_amount = flt(total, 2)
        request.remaining_collectible = max(0.0, flt(source.grand_total, 2) - total)
        request.credit_note = credit.name
        request.flags.ignore_permissions = True
        request.insert(ignore_permissions=True)
    _set_if_field(source, INVOICE_ACTIVE_REQUEST, request.name)
    _set_if_field(source, INVOICE_LAST_REQUEST, request.name)
    _set_if_field(source, INVOICE_RETURN_TYPE, RETURN_TYPE_PARTIAL)
    _set_if_field(source, INVOICE_RETURN_STATUS, PARTIAL_RETURN_AWAITING)
    source.flags.ignore_validate_update_after_submit = True
    source.save(ignore_permissions=True)
    return complete_partial_return_request(source.name, request.name)


def ensure_full_return_request(invoice, reason, notes=None, actor=None):
    if isinstance(invoice, str):
        invoice = frappe.get_doc("Sales Invoice", invoice)

    # A full return may use reasons that were missing after an older partial-
    # return installer replaced the request Select options. Repair metadata
    # before creating/saving either the request or the submitted invoice.
    ensure_partial_return_reason_options()

    if not frappe.db.exists("DocType", REQUEST_DOCTYPE):
        return None
    existing = get_active_request(invoice.name)
    if existing:
        return existing
    request = frappe.new_doc(REQUEST_DOCTYPE)
    request.return_type = RETURN_TYPE_FULL
    request.status = STATUS_RETURNING
    request.sales_invoice = invoice.name
    request.company = invoice.company
    request.customer = invoice.customer
    request.delivery_boy = invoice.get("custom_delivery_boy") or ""
    request.delivery_trip = invoice.get("custom_delivery_trip") or ""
    request.sales_shift = invoice.get("custom_pharmacy_shift") or ""
    request.delivery_shift = invoice.get("custom_delivery_shift") or invoice.get("custom_pharmacy_shift") or ""
    request.reason = reason
    request.notes = notes or ""
    request.source_grand_total = flt(invoice.grand_total, 2)
    request.estimated_return_amount = flt(invoice.grand_total, 2)
    request.remaining_collectible = 0
    request.requested_by = actor or frappe.session.user
    request.requested_at = now_datetime()
    for item in invoice.items:
        available = max(0.0, abs(flt(item.qty)) - _returned_qty(invoice.name, item.name))
        if available <= 1e-9:
            continue
        request.append("items", {
            "source_item": item.name,
            **({RETURN_ITEM_SOURCE_INVOICE_FIELD: invoice.name} if _has_field(ITEM_DOCTYPE, RETURN_ITEM_SOURCE_INVOICE_FIELD) else {}),
            "item_code": item.item_code,
            "item_name": item.item_name or item.item_code,
            "batch_no": item.batch_no or "",
            "warehouse": item.warehouse or "",
            "sold_qty": abs(flt(item.qty)),
            "previously_returned_qty": _returned_qty(invoice.name, item.name),
            "return_qty": available,
            "pack_size": _resolve_pack_size(item),
            "rate": abs(flt(item.rate)),
            "amount": flt(available * abs(flt(item.rate)), 2),
        })
    request.flags.ignore_permissions = True
    request.insert(ignore_permissions=True)
    _set_if_field(invoice, INVOICE_ACTIVE_REQUEST, request.name)
    _set_if_field(invoice, INVOICE_LAST_REQUEST, request.name)
    _set_if_field(invoice, INVOICE_RETURN_TYPE, RETURN_TYPE_FULL)
    return request


def mark_full_request_completed(invoice_name, credit_note_name):
    request = get_active_request(invoice_name)
    if not request or request.return_type != RETURN_TYPE_FULL:
        return None
    request.status = STATUS_FULL_COMPLETED
    request.credit_note = credit_note_name
    request.completed_by = frappe.session.user
    request.completed_at = now_datetime()
    request.remaining_invoice_outstanding = 0
    request.flags.ignore_permissions = True
    request.save(ignore_permissions=True)
    return request
