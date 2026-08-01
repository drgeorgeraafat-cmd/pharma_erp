from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from typing import Any
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint, flt, get_url, now_datetime, strip_html

from pharma_erp.controlled_product_listing import _catalog_brand, _format_public_price

TRACKING_VERSION = 1
TRACKING_ROUTE = "/pharmacy-order-tracking/"
TRACKING_TOKEN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32}$")
TRACKING_TOKEN_PATTERN = re.compile(
    r"^TRK(?P<version>[1-9][0-9]*)\."
    r"(?P<token_id>[A-Za-z0-9_-]{32})\."
    r"(?P<signature>[A-Za-z0-9_-]{43})$"
)
TRACKING_RATE_LIMIT_PER_MINUTE = 60

TRACKING_FIELDS = (
    "custom_tracking_enabled",
    "custom_tracking_token_id",
    "custom_tracking_token_version",
    "custom_tracking_token_hint",
    "custom_tracking_issued_at",
    "custom_tracking_revoked_at",
    "custom_tracking_last_rotated_by",
)

_STATUS_VIEW = {
    "Draft": ("received", "تم استلام الطلب", "تم تسجيل الطلب وسيبدأ فريق الصيدلية مراجعته."),
    "Placed": ("received", "تم استلام الطلب", "تم استلام طلبك بنجاح وهو بانتظار المراجعة."),
    "Under Review": ("review", "قيد المراجعة", "يتم الآن مراجعة بيانات الطلب والأصناف."),
    "Prescription Review": ("review", "مراجعة الروشتة", "تتم مراجعة الروشتة والأصناف التي تحتاجها."),
    "Stock Review": ("review", "مراجعة التوافر", "يتحقق الفريق من توافر الأصناف المطلوبة."),
    "Partially Available": ("review", "مراجعة التوافر", "بعض الأصناف تحتاج مراجعة أو تأكيدًا إضافيًا."),
    "Awaiting Customer Decision": (
        "review",
        "بانتظار تأكيد العميل",
        "سيتم التواصل معك لتأكيد أحد تفاصيل الطلب.",
    ),
    "Ready for Payment": ("review", "مراجعة الطلب", "اكتملت المراجعة الأساسية ويجري استكمال التجهيز."),
    "Payment Verification": ("review", "مراجعة الدفع", "يتم الآن التحقق من بيانات الدفع."),
    "Payment Failed": ("attention", "مطلوب استكمال الدفع", "يوجد إجراء مطلوب بخصوص الدفع وسيتم التواصل معك."),
    "Confirmed": ("preparing", "تم تأكيد الطلب", "تم تأكيد الطلب وسيبدأ التجهيز."),
    "Preparing": ("preparing", "جاري التجهيز", "يقوم فريق الصيدلية بتجهيز طلبك الآن."),
    "Ready for Delivery": ("ready_delivery", "جاهز للتوصيل", "تم تجهيز الطلب وأصبح جاهزًا للتوصيل."),
    "Ready for Pickup": ("ready_pickup", "جاهز للاستلام", "طلبك جاهز للاستلام من الصيدلية."),
    "Out for Delivery": ("out_delivery", "خرج للتوصيل", "الطلب خرج للتوصيل وهو في الطريق إليك."),
    "Delivered": ("delivered", "تم التسليم", "تم تسليم الطلب بنجاح."),
    "Completed": ("completed", "مكتمل", "اكتمل الطلب بنجاح."),
    "Returned": ("returned", "تمت إعادة الطلب", "تمت إعادة الطلب إلى الصيدلية."),
    "On Hold": ("attention", "متوقف مؤقتًا", "الطلب متوقف مؤقتًا وسيتم التواصل معك عند الحاجة."),
    "Rejected": ("rejected", "تعذر تنفيذ الطلب", "تعذر تنفيذ الطلب بهذه الحالة."),
    "Cancelled": ("cancelled", "تم إلغاء الطلب", "تم إلغاء الطلب."),
}

_PAYMENT_STATUS_LABELS = {
    "Not Declared": "لم يتم تحديد الدفع",
    "Pending Collection": "الدفع عند الاستلام",
    "Collection Draft Created": "الدفع عند الاستلام",
    "Awaiting Verification": "جاري مراجعة الدفع",
    "Verified": "تم الدفع",
    "Partially Verified": "مدفوع جزئيًا",
    "Rejected": "مشكلة في الدفع",
    "Failed": "تعذر تأكيد الدفع",
    "No Collection Required": "لا يوجد تحصيل مطلوب",
}

_PAYMENT_METHOD_LABELS = {
    "Cash on Delivery": "نقدًا عند التوصيل",
    "Cash at Pharmacy": "نقدًا عند الاستلام من الصيدلية",
    "InstaPay": "InstaPay",
    "Mobile Wallet": "محفظة إلكترونية",
    "Card Payment Link": "رابط دفع بالبطاقة",
    "Bank Transfer": "تحويل بنكي",
    "Other": "طريقة دفع أخرى",
}

_FULFILMENT_LABELS = {
    "Home Delivery": "توصيل للمنزل",
    "Pharmacy Pickup": "استلام من الصيدلية",
}


def _clean_text(value: Any, limit: int = 180) -> str:
    return " ".join(strip_html(str(value or "")).split())[:limit]


def _tracking_fields_available() -> bool:
    if not frappe.db.exists("DocType", "Online Order"):
        return False
    meta = frappe.get_meta("Online Order")
    return all(meta.has_field(fieldname) for fieldname in TRACKING_FIELDS)


def _tracking_signing_key() -> bytes:
    conf = getattr(frappe.local, "conf", None) or getattr(frappe, "conf", None) or {}
    key = conf.get("encryption_key") or conf.get("secret_key")
    if not key:
        frappe.throw(_("Customer tracking signing key is not configured."))
    return str(key).encode("utf-8")


def _site_name() -> str:
    return str(getattr(frappe.local, "site", "") or "default-site")


def _new_tracking_token_id() -> str:
    for _ in range(20):
        token_id = secrets.token_urlsafe(24)
        if not TRACKING_TOKEN_ID_PATTERN.fullmatch(token_id):
            continue
        if not frappe.db.exists(
            "Online Order", {"custom_tracking_token_id": token_id}
        ):
            return token_id
    frappe.throw(_("Unable to generate a unique customer tracking identifier."))
    return ""


def _tracking_signature(version: int, token_id: str) -> str:
    message = f"{_site_name()}|{version}|{token_id}".encode("utf-8")
    digest = hmac.new(_tracking_signing_key(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _build_tracking_token(version: int, token_id: str) -> str:
    return f"TRK{version}.{token_id}.{_tracking_signature(version, token_id)}"


def _tracking_relative_url(version: int, token_id: str) -> str:
    token = _build_tracking_token(version, token_id)
    return f"{TRACKING_ROUTE}?token={quote(token, safe='')}"


def prepare_online_order_tracking_identity(doc, method=None) -> None:
    """Assign a regenerable public tracking identity before Online Order insert.

    Only a random identifier is stored. The public token signature is generated from
    the site encryption key when a tracking link is requested.
    """
    if getattr(doc, "doctype", "") != "Online Order":
        return
    if not _tracking_fields_available():
        return
    if doc.get("custom_tracking_token_id"):
        return

    token_id = _new_tracking_token_id()
    doc.custom_tracking_enabled = 1
    doc.custom_tracking_token_id = token_id
    doc.custom_tracking_token_version = TRACKING_VERSION
    doc.custom_tracking_token_hint = token_id[-6:]
    doc.custom_tracking_issued_at = now_datetime()
    doc.custom_tracking_revoked_at = None
    doc.custom_tracking_last_rotated_by = frappe.session.user if frappe.session else None


def _tracking_values(order_name: str) -> dict[str, Any]:
    if not _tracking_fields_available():
        return {}
    return frappe.db.get_value(
        "Online Order",
        order_name,
        [
            "name",
            "custom_tracking_enabled",
            "custom_tracking_token_id",
            "custom_tracking_token_version",
            "custom_tracking_token_hint",
            "custom_tracking_issued_at",
            "custom_tracking_revoked_at",
        ],
        as_dict=True,
    ) or {}


def tracking_url_for_order_name(order_name: str, absolute: bool = False) -> str:
    values = _tracking_values(_clean_text(order_name, 140))
    token_id = str(values.get("custom_tracking_token_id") or "").strip()
    version = cint(values.get("custom_tracking_token_version") or TRACKING_VERSION)
    if not values or not cint(values.get("custom_tracking_enabled")):
        return ""
    if values.get("custom_tracking_revoked_at"):
        return ""
    if not TRACKING_TOKEN_ID_PATTERN.fullmatch(token_id):
        return ""
    relative = _tracking_relative_url(version, token_id)
    return get_url(relative) if absolute else relative


_TRACKING_RESPONSE_HEADERS = {
    "Cache-Control": "private, no-store, no-cache, max-age=0, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
    "Referrer-Policy": "no-referrer",
}

_TRACKING_HTTP_PATHS = {
    TRACKING_ROUTE.rstrip("/"),
    "/api/method/pharma_erp.customer_order_tracking.get_public_order_tracking",
}


def _set_no_store_headers() -> None:
    """Mark the request for the after_request response-header hook."""
    frappe.flags.customer_tracking_no_store = True


def apply_customer_tracking_response_headers(response=None, request=None) -> None:
    """Apply customer-tracking security headers to the real HTTP response."""
    if response is None or request is None:
        return

    path = str(getattr(request, "path", "") or "").rstrip("/")
    marked = bool(getattr(frappe.flags, "customer_tracking_no_store", False))

    if path not in _TRACKING_HTTP_PATHS and not marked:
        return

    for header, value in _TRACKING_RESPONSE_HEADERS.items():
        response.headers[header] = value


def _request_ip_hash() -> str:
    request = getattr(frappe.local, "request", None)
    ip = str(getattr(request, "remote_addr", "") or "unknown")
    return hashlib.sha256(_tracking_signing_key() + ip.encode("utf-8")).hexdigest()[:16]


def _enforce_tracking_rate_limit(token_id: str) -> None:
    """Best-effort cache rate limit without writing to business documents."""
    try:
        cache = getattr(frappe, "cache", None)
        if callable(cache):
            cache = cache()
        if not cache:
            return
        minute_bucket = now_datetime().strftime("%Y%m%d%H%M")
        key = (
            "pharma:customer-tracking:"
            f"{minute_bucket}:{_request_ip_hash()}:{token_id[-8:]}"
        )
        count = cint(cache.incr(key))
        if count == 1:
            cache.expire(key, 120)
        if count > TRACKING_RATE_LIMIT_PER_MINUTE:
            if getattr(frappe.local, "response", None) is not None:
                frappe.local.response["http_status_code"] = 429
            frappe.throw(
                _("Too many tracking requests. Please wait and try again."),
                frappe.ValidationError,
            )
    except frappe.ValidationError:
        raise
    except Exception:
        return


def _parse_tracking_token(token: str) -> tuple[int, str]:
    clean_token = _clean_text(token, 180)
    match = TRACKING_TOKEN_PATTERN.fullmatch(clean_token)
    if not match:
        frappe.throw(
            _("This tracking link is invalid or no longer available."),
            frappe.DoesNotExistError,
        )
    version = cint(match.group("version"))
    token_id = match.group("token_id")
    expected = _tracking_signature(version, token_id)
    if version != TRACKING_VERSION or not hmac.compare_digest(
        expected, match.group("signature")
    ):
        frappe.throw(
            _("This tracking link is invalid or no longer available."),
            frappe.DoesNotExistError,
        )
    return version, token_id


def _public_status(status: str) -> dict[str, str]:
    key, label, message = _STATUS_VIEW.get(
        status,
        ("review", "قيد المراجعة", "يتم الآن مراجعة حالة الطلب."),
    )
    return {"key": key, "label_ar": label, "message_ar": message}


def _timeline_definition(fulfilment_method: str) -> list[dict[str, str]]:
    if fulfilment_method == "Pharmacy Pickup":
        return [
            {"key": "received", "label_ar": "تم استلام الطلب"},
            {"key": "review", "label_ar": "قيد المراجعة"},
            {"key": "preparing", "label_ar": "جاري التجهيز"},
            {"key": "ready_pickup", "label_ar": "جاهز للاستلام"},
            {"key": "completed", "label_ar": "مكتمل"},
        ]
    return [
        {"key": "received", "label_ar": "تم استلام الطلب"},
        {"key": "review", "label_ar": "قيد المراجعة"},
        {"key": "preparing", "label_ar": "جاري التجهيز"},
        {"key": "ready_delivery", "label_ar": "جاهز للتوصيل"},
        {"key": "out_delivery", "label_ar": "خرج للتوصيل"},
        {"key": "delivered", "label_ar": "تم التسليم"},
        {"key": "completed", "label_ar": "مكتمل"},
    ]


def _timeline(order: dict[str, Any], status_view: dict[str, str]) -> list[dict[str, Any]]:
    steps = _timeline_definition(order.get("fulfilment_method") or "")
    step_keys = [step["key"] for step in steps]
    current_key = status_view["key"]
    exceptional = current_key in {
        "attention",
        "returned",
        "rejected",
        "cancelled",
    }
    if exceptional:
        current_index = min(1, len(steps) - 1)
    else:
        current_index = step_keys.index(current_key) if current_key in step_keys else 1

    timestamp_by_key = {
        "received": order.get("placed_at") or order.get("creation"),
        "preparing": order.get("confirmed_at"),
        "out_delivery": order.get("delivery_departure_at"),
        "delivered": order.get("delivery_delivered_at"),
        "completed": (
            order.get("pickup_completed_at")
            if order.get("fulfilment_method") == "Pharmacy Pickup"
            else order.get("delivery_completed_at")
        ),
    }

    timeline = []
    for index, step in enumerate(steps):
        state = "done" if index < current_index else "upcoming"
        if index == current_index:
            state = "current"
        timeline.append(
            {
                **step,
                "state": state,
                "at": timestamp_by_key.get(step["key"]),
            }
        )

    if exceptional:
        timeline = timeline[: current_index + 1]
        for step in timeline:
            step["state"] = "done"
        timeline.append(
            {
                "key": current_key,
                "label_ar": status_view["label_ar"],
                "state": "current",
                "at": order.get("modified"),
            }
        )
    return timeline


def _driver_public_name(order: dict[str, Any]) -> str:
    if order.get("fulfilment_method") != "Home Delivery":
        return ""
    if order.get("status") not in {"Out for Delivery", "Delivered", "Completed"}:
        return ""
    employee = str(order.get("delivery_boy") or "").strip()
    if not employee:
        return ""
    return str(
        frappe.db.get_value("Employee", employee, "employee_name") or ""
    ).strip()


def _public_items(order_name: str) -> list[dict[str, Any]]:
    rows = frappe.get_all(
        "Online Order Item",
        filters={"parent": order_name, "parenttype": "Online Order"},
        fields=[
            "item_name_snapshot",
            "requested_qty",
            "approved_qty",
            "requires_prescription_snapshot",
        ],
        order_by="idx asc",
    )
    result = []
    for row in rows:
        approved = flt(row.get("approved_qty"))
        requested = flt(row.get("requested_qty"))
        result.append(
            {
                "item_name": row.get("item_name_snapshot") or _("Product"),
                "qty": approved if approved > 0 else requested,
                "requires_prescription": cint(
                    row.get("requires_prescription_snapshot")
                ),
            }
        )
    return result


def _audit_tracking_open(order_name: str, token_id: str, status: str) -> None:
    payload = {
        "event": "customer_order_tracking_open",
        "online_order": order_name,
        "status": status,
        "token_hint": token_id[-6:],
        "ip_hash": _request_ip_hash(),
        "at": str(now_datetime()),
    }
    try:
        frappe.logger("customer_order_tracking", allow_site=True).info(
            json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
    except Exception:
        pass


def _tracking_order_by_token_id(token_id: str) -> dict[str, Any]:
    fields = [
        "name",
        "docstatus",
        "status",
        "fulfilment_method",
        "products_subtotal",
        "delivery_fee",
        "grand_total",
        "currency",
        "payment_status",
        "payment_method",
        "placed_at",
        "confirmed_at",
        "pickup_completed_at",
        "delivery_departure_at",
        "delivery_delivered_at",
        "delivery_completed_at",
        "delivery_boy",
        "estimated_delivery_time_mins",
        "creation",
        "modified",
        "custom_tracking_enabled",
        "custom_tracking_token_id",
        "custom_tracking_token_version",
        "custom_tracking_issued_at",
        "custom_tracking_revoked_at",
    ]
    return frappe.db.get_value(
        "Online Order",
        {"custom_tracking_token_id": token_id},
        fields,
        as_dict=True,
    ) or {}


@frappe.whitelist(allow_guest=True)
def get_public_order_tracking(token: str | None = None) -> dict[str, Any]:
    """Return a strict, read-only customer-safe view for one Online Order."""
    _set_no_store_headers()
    if not _tracking_fields_available():
        frappe.throw(_("Customer order tracking is not installed."))

    version, token_id = _parse_tracking_token(token or "")
    _enforce_tracking_rate_limit(token_id)
    order = _tracking_order_by_token_id(token_id)

    if (
        not order
        or cint(order.get("docstatus")) >= 2
        or not cint(order.get("custom_tracking_enabled"))
        or order.get("custom_tracking_revoked_at")
        or cint(order.get("custom_tracking_token_version")) != version
    ):
        frappe.throw(
            _("This tracking link is invalid or no longer available."),
            frappe.DoesNotExistError,
        )

    status_view = _public_status(order.get("status") or "")
    currency = order.get("currency") or _catalog_brand().get("currency") or "EGP"
    payload = {
        "online_order": order.get("name"),
        "placed_at": order.get("placed_at") or order.get("creation"),
        "customer_status": status_view,
        "fulfilment_method": order.get("fulfilment_method"),
        "fulfilment_label_ar": _FULFILMENT_LABELS.get(
            order.get("fulfilment_method"), "طريقة استلام الطلب"
        ),
        "grand_total": flt(order.get("grand_total")),
        "grand_total_formatted": _format_public_price(
            flt(order.get("grand_total")), currency
        ),
        "currency": currency,
        "payment_status_label_ar": _PAYMENT_STATUS_LABELS.get(
            order.get("payment_status"), "حالة الدفع قيد المراجعة"
        ),
        "payment_method_label_ar": _PAYMENT_METHOD_LABELS.get(
            order.get("payment_method"), ""
        ),
        "driver_name": _driver_public_name(order),
        "estimated_delivery_time_mins": cint(
            order.get("estimated_delivery_time_mins")
        ),
        "timeline": _timeline(order, status_view),
        "items": _public_items(order.get("name")),
        "read_only": 1,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
    }
    _audit_tracking_open(
        str(order.get("name") or ""), token_id, str(order.get("status") or "")
    )
    return payload


def _staff_order(online_order: str, permission: str):
    name = _clean_text(online_order, 140)
    if not name or not frappe.db.exists("Online Order", name):
        frappe.throw(_("Online Order was not found."), frappe.DoesNotExistError)
    doc = frappe.get_doc("Online Order", name)
    if not frappe.has_permission("Online Order", permission, doc=doc):
        frappe.throw(
            _("You do not have permission for this Online Order."),
            frappe.PermissionError,
        )
    return doc


def _staff_tracking_result(order_name: str) -> dict[str, Any]:
    values = _tracking_values(order_name)
    return {
        "online_order": order_name,
        "enabled": cint(values.get("custom_tracking_enabled")),
        "issued_at": values.get("custom_tracking_issued_at"),
        "revoked_at": values.get("custom_tracking_revoked_at"),
        "token_hint": values.get("custom_tracking_token_hint") or "",
        "tracking_url": tracking_url_for_order_name(order_name, absolute=True),
        "tracking_route": TRACKING_ROUTE,
    }


@frappe.whitelist()
def get_staff_tracking_link(online_order: str | None = None) -> dict[str, Any]:
    order = _staff_order(online_order or "", "read")
    values = _tracking_values(order.name)
    if not values.get("custom_tracking_token_id"):
        if not frappe.has_permission("Online Order", "write", doc=order):
            frappe.throw(
                _("The tracking link has not been issued yet."),
                frappe.PermissionError,
            )
        return rotate_staff_tracking_link(order.name)
    return _staff_tracking_result(order.name)


@frappe.whitelist(methods=["POST"])
def rotate_staff_tracking_link(online_order: str | None = None) -> dict[str, Any]:
    order = _staff_order(online_order or "", "write")
    token_id = _new_tracking_token_id()
    now = now_datetime()
    frappe.db.set_value(
        "Online Order",
        order.name,
        {
            "custom_tracking_enabled": 1,
            "custom_tracking_token_id": token_id,
            "custom_tracking_token_version": TRACKING_VERSION,
            "custom_tracking_token_hint": token_id[-6:],
            "custom_tracking_issued_at": now,
            "custom_tracking_revoked_at": None,
            "custom_tracking_last_rotated_by": frappe.session.user,
        },
        update_modified=True,
    )
    order.add_comment(
        "Info",
        _("Customer tracking link was issued or rotated by {0}.").format(
            frappe.session.user
        ),
    )
    return _staff_tracking_result(order.name)


@frappe.whitelist(methods=["POST"])
def revoke_staff_tracking_link(online_order: str | None = None) -> dict[str, Any]:
    order = _staff_order(online_order or "", "write")
    frappe.db.set_value(
        "Online Order",
        order.name,
        {
            "custom_tracking_enabled": 0,
            "custom_tracking_revoked_at": now_datetime(),
            "custom_tracking_last_rotated_by": frappe.session.user,
        },
        update_modified=True,
    )
    order.add_comment(
        "Info",
        _("Customer tracking link was revoked by {0}.").format(
            frappe.session.user
        ),
    )
    return _staff_tracking_result(order.name)
