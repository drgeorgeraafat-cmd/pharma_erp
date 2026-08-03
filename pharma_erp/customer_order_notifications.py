
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime, strip_html

PREFERENCE_DOCTYPE = "Online Order Notification Preference"
NOTIFICATION_DOCTYPE = "Online Order Customer Notification"
STATUS_EVENT_DOCTYPE = "Online Order Customer Status Event"
STATUS_EVENT_FIELD = "custom_customer_status_events"

OUTBOUND_DELIVERY_ENABLED = False
NOTIFICATION_RATE_LIMIT_PER_MINUTE = 30

ELIGIBLE_SOURCE_STATUSES = {
    "Placed": "order_received",
    "Awaiting Customer Decision": "customer_action_required",
    "Payment Failed": "payment_action_required",
    "Confirmed": "order_confirmed",
    "Preparing": "order_preparing",
    "Ready for Delivery": "order_ready_delivery",
    "Ready for Pickup": "order_ready_pickup",
    "Out for Delivery": "order_out_for_delivery",
    "Delivered": "order_delivered",
    "Completed": "order_completed",
    "Returned": "order_returned",
    "On Hold": "order_on_hold",
    "Rejected": "order_rejected",
    "Cancelled": "order_cancelled",
}

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

_RESPONSE_HEADERS = {
    "Cache-Control": "private, no-store, no-cache, max-age=0, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
    "Referrer-Policy": "no-referrer",
    "Vary": "Cookie",
}


def _clean_text(value: Any, limit: int = 240) -> str:
    return " ".join(strip_html(str(value or "")).split())[:limit]


def _parse_payload(payload: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        frappe.throw(_("Invalid notification preference request."))
    if not isinstance(parsed, dict):
        frappe.throw(_("Invalid notification preference request."))
    return parsed


def _require_website_user() -> str:
    user = str(frappe.session.user or "Guest").strip()
    if not user or user == "Guest":
        frappe.throw(
            _("Please sign in to manage notification preferences."),
            frappe.PermissionError,
        )
    values = frappe.db.get_value(
        "User", user, ["enabled", "user_type"], as_dict=True
    ) or {}
    if not cint(values.get("enabled")) or values.get("user_type") != "Website User":
        frappe.throw(
            _("Notification preferences are available only for website customer accounts."),
            frappe.PermissionError,
        )
    return user


def _request_ip_hash() -> str:
    request = getattr(frappe.local, "request", None)
    remote = ""
    if request:
        forwarded = str(request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        remote = forwarded or str(getattr(request, "remote_addr", "") or "")
    key = str((getattr(frappe.local, "conf", None) or {}).get("encryption_key") or "")
    return hashlib.sha256(f"{key}|{remote}".encode("utf-8")).hexdigest()[:20]


def _enforce_rate_limit(action: str) -> None:
    user = str(frappe.session.user or "Guest")
    bucket = now_datetime().strftime("%Y%m%d%H%M")
    cache_key = (
        f"pharma_customer_notifications:{action}:{user}:{_request_ip_hash()}:{bucket}"
    )
    try:
        cache = getattr(frappe, "cache", None)
        if callable(cache):
            cache = cache()
        if not cache:
            return
        current = cint(cache.incr(cache_key))
        if current == 1:
            cache.expire(cache_key, 75)
        if current > NOTIFICATION_RATE_LIMIT_PER_MINUTE:
            if getattr(frappe.local, "response", None) is not None:
                frappe.local.response["http_status_code"] = 429
            frappe.throw(
                _("Too many notification preference requests. Please try again shortly."),
                frappe.ValidationError,
            )
    except frappe.ValidationError:
        raise
    except Exception:
        return


def _set_no_store_headers() -> None:
    frappe.flags.customer_notification_no_store = True


def apply_customer_notification_response_headers(response=None, request=None) -> None:
    if response is None or request is None:
        return
    path = str(getattr(request, "path", "") or "")
    api_prefix = "/api/method/pharma_erp.customer_order_notifications."
    marked = bool(getattr(frappe.flags, "customer_notification_no_store", False))
    if not path.startswith(api_prefix) and not marked:
        return
    for key, value in _RESPONSE_HEADERS.items():
        response.headers[key] = value


def _foundation_available() -> bool:
    return bool(
        frappe.db.exists("DocType", "Online Order")
        and frappe.db.exists("DocType", STATUS_EVENT_DOCTYPE)
        and frappe.db.exists("DocType", PREFERENCE_DOCTYPE)
        and frappe.db.exists("DocType", NOTIFICATION_DOCTYPE)
    )


def _site_secret() -> str:
    conf = getattr(frappe.local, "conf", None) or getattr(frappe, "conf", None) or {}
    return str(conf.get("encryption_key") or conf.get("secret_key") or frappe.local.site)


def _recipient_hash(value: str) -> str:
    normalised = str(value or "").strip().lower()
    return hashlib.sha256(
        f"{_site_secret()}|{normalised}".encode("utf-8")
    ).hexdigest()


def _mask_email(value: str) -> str:
    email = str(value or "").strip()
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    prefix = local[:2] if len(local) > 1 else local[:1]
    return f"{prefix}***@{domain}"


def _email_for_user(user: str) -> str:
    values = frappe.db.get_value("User", user, ["email", "name"], as_dict=True) or {}
    email = str(values.get("email") or values.get("name") or user).strip().lower()
    return email if _EMAIL_PATTERN.fullmatch(email) else ""


def _valid_website_user(user: str) -> bool:
    if not user or user == "Guest":
        return False
    values = frappe.db.get_value(
        "User", user, ["enabled", "user_type"], as_dict=True
    ) or {}
    return bool(cint(values.get("enabled")) and values.get("user_type") == "Website User")


def ensure_notification_preference(user: str):
    if not _valid_website_user(user):
        return None
    if frappe.db.exists(PREFERENCE_DOCTYPE, user):
        return frappe.get_doc(PREFERENCE_DOCTYPE, user)
    return frappe.get_doc(
        {
            "doctype": PREFERENCE_DOCTYPE,
            "website_user": user,
            "order_updates_enabled": 1,
            "email_enabled": 1,
            "whatsapp_enabled": 0,
            "sms_enabled": 0,
            "marketing_enabled": 0,
            "consent_source": "Account Default",
            "consent_updated_at": now_datetime(),
            "last_updated_by": "Administrator",
        }
    ).insert(ignore_permissions=True)


def _preference_payload(preference) -> dict[str, Any]:
    return {
        "website_user": preference.website_user,
        "order_updates_enabled": cint(preference.order_updates_enabled),
        "email_enabled": cint(preference.email_enabled),
        "whatsapp_enabled": 0,
        "sms_enabled": 0,
        "marketing_enabled": 0,
        "outbound_delivery_enabled": cint(OUTBOUND_DELIVERY_ENABLED),
        "email_recipient_masked": _mask_email(
            _email_for_user(preference.website_user)
        ),
        "consent_source": preference.consent_source,
        "consent_updated_at": preference.consent_updated_at,
    }


def _idempotency_key(order_name: str, event_hash: str, user: str, channel: str) -> str:
    raw = f"{order_name}|{event_hash}|{user}|{channel}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_hash(order_name: str, event) -> str:
    existing = str(event.get("event_hash") or "").strip()
    if existing:
        return existing
    raw = (
        f"{order_name}|{event.get('source_status')}|"
        f"{event.get('event_key')}|{event.get('event_at')}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _build_message(order_name: str, event) -> tuple[str, str]:
    label = _clean_text(event.get("label_ar") or "تحديث الطلب", 120)
    message = _clean_text(event.get("message_ar") or "", 240)
    subject = f"تحديث طلبك {order_name}: {label}"
    preview = f"طلبك {order_name}: {message or label}"
    return subject[:240], preview[:500]


def _insert_email_intent(order, event, preference, email: str) -> bool:
    event_hash = _event_hash(order.name, event)
    idempotency_key = _idempotency_key(
        order.name, event_hash, preference.website_user, "Email"
    )
    if frappe.db.exists(
        NOTIFICATION_DOCTYPE, {"idempotency_key": idempotency_key}
    ):
        return False

    source_status = str(event.get("source_status") or "")
    template_key = ELIGIBLE_SOURCE_STATUSES.get(source_status)
    if not template_key:
        return False

    subject, preview = _build_message(order.name, event)
    frappe.get_doc(
        {
            "doctype": NOTIFICATION_DOCTYPE,
            "online_order": order.name,
            "website_user": preference.website_user,
            "status_event_hash": event_hash,
            "event_key": event.get("event_key"),
            "source_status": source_status,
            "event_at": event.get("event_at"),
            "channel": "Email",
            "notification_status": (
                "Pending" if OUTBOUND_DELIVERY_ENABLED else "Deferred"
            ),
            "idempotency_key": idempotency_key,
            "recipient_masked": _mask_email(email),
            "recipient_hash": _recipient_hash(email),
            "template_key": template_key,
            "subject": subject,
            "message_preview": preview,
            "defer_reason": (
                ""
                if OUTBOUND_DELIVERY_ENABLED
                else "Outbound delivery is disabled in Step 4C foundation."
            ),
            "attempt_count": 0,
            "created_at": now_datetime(),
            "is_transactional": 1,
        }
    ).insert(ignore_permissions=True)
    return True


def _capture_order_notification_intents(order) -> int:
    if not _foundation_available():
        return 0
    user = str(order.get("custom_website_user") or "").strip()
    if not _valid_website_user(user):
        return 0

    preference = ensure_notification_preference(user)
    if (
        not preference
        or not cint(preference.order_updates_enabled)
        or not cint(preference.email_enabled)
    ):
        return 0

    email = _email_for_user(user)
    if not email:
        return 0

    created = 0
    for event in list(order.get(STATUS_EVENT_FIELD) or []):
        if str(event.get("source_status") or "") not in ELIGIBLE_SOURCE_STATUSES:
            continue
        created += cint(_insert_email_intent(order, event, preference, email))
    return created


def capture_order_notification_intents(doc, method=None) -> None:
    """Capture idempotent notification intents without sending externally.

    This hook is deliberately fail-open: an unavailable notification foundation
    must never block order confirmation, delivery, collection, or completion.
    """
    if getattr(doc, "doctype", "") != "Online Order":
        return
    if not _foundation_available():
        return

    savepoint = f"step4c_notification_{hashlib.sha1(str(doc.name).encode()).hexdigest()[:10]}"
    try:
        frappe.db.savepoint(savepoint)
        _capture_order_notification_intents(doc)
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        frappe.log_error(
            title="Step 4C Notification Intent Capture",
            message=frappe.get_traceback(),
        )


def bootstrap_notification_preferences() -> dict[str, int]:
    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "Website User"},
        pluck="name",
    )
    created = 0
    for user in users:
        if not frappe.db.exists(PREFERENCE_DOCTYPE, user):
            ensure_notification_preference(str(user))
            created += 1
    return {"website_users_seen": len(users), "preferences_created": created}


def bootstrap_existing_notification_intents() -> dict[str, int]:
    orders = frappe.get_all(
        "Online Order",
        filters={"custom_website_user": ["!=", ""]},
        pluck="name",
        order_by="creation asc",
    )
    created = 0
    eligible_orders = 0
    for order_name in orders:
        order = frappe.get_doc("Online Order", order_name)
        if not _valid_website_user(str(order.get("custom_website_user") or "")):
            continue
        eligible_orders += 1
        created += _capture_order_notification_intents(order)
    return {
        "orders_seen": len(orders),
        "eligible_orders": eligible_orders,
        "notification_intents_created": created,
    }


@frappe.whitelist()
def get_notification_preferences() -> dict[str, Any]:
    _set_no_store_headers()
    _enforce_rate_limit("get")
    user = _require_website_user()
    preference = ensure_notification_preference(user)
    return _preference_payload(preference)


@frappe.whitelist()
def update_notification_preferences(
    payload: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    _set_no_store_headers()
    _enforce_rate_limit("update")
    user = _require_website_user()
    values = _parse_payload(payload)

    if cint(values.get("whatsapp_enabled")) or cint(values.get("sms_enabled")):
        frappe.throw(
            _("WhatsApp and SMS delivery are not enabled in this foundation step.")
        )

    preference = ensure_notification_preference(user)
    preference.order_updates_enabled = cint(values.get("order_updates_enabled"))
    preference.email_enabled = cint(values.get("email_enabled"))
    preference.whatsapp_enabled = 0
    preference.sms_enabled = 0
    preference.marketing_enabled = 0
    preference.consent_source = "Customer Account"
    preference.consent_updated_at = now_datetime()
    preference.last_updated_by = user
    preference.save(ignore_permissions=True)
    return _preference_payload(preference)
