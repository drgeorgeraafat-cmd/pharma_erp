
from __future__ import annotations

import hashlib
import html
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from pharma_erp.customer_order_notifications import (
    NOTIFICATION_DOCTYPE,
    PREFERENCE_DOCTYPE,
    _email_for_user,
    _recipient_hash,
)

SETTINGS_DOCTYPE = "Online Order Notification Delivery Settings"
ATTEMPT_DOCTYPE = "Online Order Notification Delivery Attempt"

DELIVERY_MODE_DISABLED = "Disabled"
DELIVERY_MODE_PREVIEW = "Preview Only"

_RESPONSE_HEADERS = {
    "Cache-Control": "private, no-store, no-cache, max-age=0, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
    "Referrer-Policy": "no-referrer",
    "Vary": "Cookie",
}


def _set_no_store_headers() -> None:
    frappe.flags.customer_notification_delivery_no_store = True


def apply_notification_delivery_response_headers(response=None, request=None) -> None:
    if response is None or request is None:
        return
    path = str(getattr(request, "path", "") or "")
    api_prefix = "/api/method/pharma_erp.customer_notification_delivery."
    marked = bool(
        getattr(frappe.flags, "customer_notification_delivery_no_store", False)
    )
    if not path.startswith(api_prefix) and not marked:
        return
    for key, value in _RESPONSE_HEADERS.items():
        response.headers[key] = value


def _require_system_manager() -> str:
    user = str(frappe.session.user or "Guest").strip()
    if not user or user == "Guest":
        frappe.throw(
            _("Please sign in as a System Manager."),
            frappe.PermissionError,
        )
    roles = set(frappe.get_roles(user))
    if "System Manager" not in roles:
        frappe.throw(
            _("Only a System Manager can review notification delivery."),
            frappe.PermissionError,
        )
    return user


def _foundation_available() -> bool:
    required = (
        NOTIFICATION_DOCTYPE,
        PREFERENCE_DOCTYPE,
        SETTINGS_DOCTYPE,
        ATTEMPT_DOCTYPE,
    )
    return all(frappe.db.exists("DocType", doctype) for doctype in required)


def get_settings():
    return frappe.get_single(SETTINGS_DOCTYPE)


def bootstrap_delivery_settings() -> dict[str, Any]:
    settings = get_settings()
    changed = False

    defaults = {
        "delivery_mode": DELIVERY_MODE_PREVIEW,
        "outbound_email_enabled": 0,
        "sender_display_name": "Cure Pharmacy",
        "portal_path": "/pharmacy-orders/",
        "max_batch_size": 20,
        "max_attempts": 3,
        "retry_delay_minutes": 15,
        "require_recipient_hash_match": 1,
        "last_readiness_status": "Not Checked",
        "activation_note": (
            "Step 4D supports readiness checks, secure template previews, "
            "and a hard delivery guard. External email activation is reserved "
            "for Step 4E."
        ),
    }
    for fieldname, value in defaults.items():
        current = settings.get(fieldname)
        if current in (None, ""):
            settings.set(fieldname, value)
            changed = True

    # Step 4D must remain non-sending even after repeated installation.
    if cint(settings.outbound_email_enabled):
        settings.outbound_email_enabled = 0
        changed = True
    if settings.delivery_mode not in (DELIVERY_MODE_DISABLED, DELIVERY_MODE_PREVIEW):
        settings.delivery_mode = DELIVERY_MODE_PREVIEW
        changed = True

    if changed:
        settings.flags.ignore_permissions = True
        settings.save()

    return {
        "delivery_mode": settings.delivery_mode,
        "outbound_email_enabled": cint(settings.outbound_email_enabled),
        "max_batch_size": cint(settings.max_batch_size),
        "max_attempts": cint(settings.max_attempts),
        "retry_delay_minutes": cint(settings.retry_delay_minutes),
        "require_recipient_hash_match": cint(
            settings.require_recipient_hash_match
        ),
    }


def _notification_counts() -> dict[str, int]:
    statuses = ("Deferred", "Pending", "Sent", "Failed", "Skipped")
    result = {
        status.lower(): frappe.db.count(
            NOTIFICATION_DOCTYPE, {"notification_status": status}
        )
        for status in statuses
    }
    result["total"] = frappe.db.count(NOTIFICATION_DOCTYPE)
    return result


def _outgoing_account_state(settings) -> dict[str, Any]:
    account_name = str(settings.outgoing_email_account or "").strip()
    if not account_name:
        return {
            "configured": 0,
            "enabled": 0,
            "account": "",
            "reason": "No outgoing Email Account has been selected.",
        }

    values = frappe.db.get_value(
        "Email Account",
        account_name,
        ["name", "enable_outgoing", "default_outgoing"],
        as_dict=True,
    ) or {}
    if not values:
        return {
            "configured": 0,
            "enabled": 0,
            "account": account_name,
            "reason": "The selected Email Account does not exist.",
        }

    enabled = cint(values.get("enable_outgoing"))
    return {
        "configured": 1,
        "enabled": enabled,
        "account": values.get("name"),
        "default_outgoing": cint(values.get("default_outgoing")),
        "reason": (
            ""
            if enabled
            else "The selected Email Account is not enabled for outgoing mail."
        ),
    }


def _readiness_payload() -> dict[str, Any]:
    settings = get_settings()
    counts = _notification_counts()
    account = _outgoing_account_state(settings)

    preview_ready = int(
        _foundation_available()
        and settings.delivery_mode in (
            DELIVERY_MODE_DISABLED,
            DELIVERY_MODE_PREVIEW,
        )
        and not cint(settings.outbound_email_enabled)
    )
    external_delivery_ready = int(
        bool(account.get("configured"))
        and bool(account.get("enabled"))
        and cint(settings.require_recipient_hash_match)
        and not cint(settings.outbound_email_enabled)
    )

    blockers: list[str] = []
    if cint(settings.outbound_email_enabled):
        blockers.append(
            "Outbound email must remain disabled during Step 4D."
        )
    if not account.get("configured"):
        blockers.append("Select an outgoing Email Account before Step 4E.")
    elif not account.get("enabled"):
        blockers.append("Enable outgoing mail on the selected Email Account.")
    if not cint(settings.require_recipient_hash_match):
        blockers.append("Recipient hash matching must remain enabled.")

    readiness_status = (
        "Ready for Controlled Activation"
        if external_delivery_ready
        else "Preview Ready"
        if preview_ready
        else "Configuration Required"
    )

    return {
        "status": "ok",
        "step": "4D",
        "delivery_mode": settings.delivery_mode,
        "outbound_email_enabled": cint(settings.outbound_email_enabled),
        "preview_ready": preview_ready,
        "external_delivery_ready": external_delivery_ready,
        "readiness_status": readiness_status,
        "blockers": blockers,
        "outgoing_email_account": account,
        "notification_counts": counts,
        "delivery_attempts": frappe.db.count(ATTEMPT_DOCTYPE),
        "max_batch_size": cint(settings.max_batch_size),
        "max_attempts": cint(settings.max_attempts),
        "retry_delay_minutes": cint(settings.retry_delay_minutes),
        "require_recipient_hash_match": cint(
            settings.require_recipient_hash_match
        ),
        "creates_email_queue": 0,
        "creates_communication": 0,
        "sends_external_email": 0,
    }


def _record_attempt(
    *,
    notification,
    attempt_type: str,
    result_status: str,
    attempted_by: str,
    message_digest: str = "",
    error_summary: str = "",
) -> str:
    doc = frappe.get_doc(
        {
            "doctype": ATTEMPT_DOCTYPE,
            "notification": notification.name,
            "online_order": notification.online_order,
            "website_user": notification.website_user,
            "attempt_type": attempt_type,
            "result_status": result_status,
            "recipient_masked": notification.recipient_masked,
            "recipient_hash": notification.recipient_hash,
            "template_key": notification.template_key,
            "subject": notification.subject,
            "provider_mode": DELIVERY_MODE_PREVIEW,
            "message_digest": message_digest,
            "error_summary": error_summary,
            "attempted_at": now_datetime(),
            "attempted_by": attempted_by,
        }
    ).insert(ignore_permissions=True)
    return doc.name


def _build_preview(notification_name: str) -> dict[str, Any]:
    notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)
    settings = get_settings()

    email = _email_for_user(str(notification.website_user or ""))
    current_hash = _recipient_hash(email) if email else ""
    stored_hash = str(notification.recipient_hash or "")
    hash_matches = int(bool(email) and current_hash == stored_hash)

    if cint(settings.require_recipient_hash_match) and not hash_matches:
        frappe.throw(
            _(
                "The current Website User email does not match the recipient "
                "hash stored with this notification intent."
            )
        )

    portal_path = str(settings.portal_path or "/pharmacy-orders/").strip()
    if not portal_path.startswith("/"):
        portal_path = "/pharmacy-orders/"

    subject = str(notification.subject or "").strip()
    message = str(notification.message_preview or "").strip()
    order_name = str(notification.online_order or "").strip()

    escaped_subject = html.escape(subject)
    escaped_message = html.escape(message)
    escaped_order = html.escape(order_name)
    escaped_path = html.escape(portal_path, quote=True)

    body_html = (
        '<div dir="rtl" style="font-family:Arial,sans-serif;line-height:1.8">'
        f"<h2>{escaped_subject}</h2>"
        f"<p>{escaped_message}</p>"
        f"<p><strong>رقم الطلب:</strong> {escaped_order}</p>"
        f'<p><a href="{escaped_path}">فتح حسابي ومتابعة الطلب</a></p>'
        "<p style=\"color:#64748b;font-size:13px\">"
        "هذه معاينة آمنة فقط. لم يتم إرسال بريد إلكتروني."
        "</p></div>"
    )
    body_text = (
        f"{subject}\n\n{message}\n"
        f"رقم الطلب: {order_name}\n"
        f"متابعة الطلب: {portal_path}\n\n"
        "معاينة آمنة فقط — لم يتم إرسال بريد إلكتروني."
    )
    digest = hashlib.sha256(
        f"{subject}|{body_text}|{stored_hash}".encode("utf-8")
    ).hexdigest()

    return {
        "notification": notification.name,
        "online_order": order_name,
        "website_user": notification.website_user,
        "source_status": notification.source_status,
        "event_key": notification.event_key,
        "recipient_masked": notification.recipient_masked,
        "recipient_hash_matches": hash_matches,
        "template_key": notification.template_key,
        "subject": subject,
        "body_html": body_html,
        "body_text": body_text,
        "message_digest": digest,
        "notification_status": notification.notification_status,
        "delivery_mode": settings.delivery_mode,
        "outbound_email_enabled": cint(settings.outbound_email_enabled),
        "external_send_performed": 0,
    }


@frappe.whitelist()
def get_delivery_readiness(record_check: int = 0) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    payload = _readiness_payload()

    if cint(record_check):
        settings = get_settings()
        settings.last_readiness_status = payload["readiness_status"]
        settings.last_readiness_checked_at = now_datetime()
        settings.last_readiness_checked_by = user
        settings.readiness_details = "\n".join(payload["blockers"]) or (
            "Preview controls are ready. External activation remains guarded."
        )
        settings.flags.ignore_permissions = True
        settings.save()

    return payload


@frappe.whitelist()
def preview_notification(notification_name: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    preview = _build_preview(notification_name)
    notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)
    attempt_name = _record_attempt(
        notification=notification,
        attempt_type="Template Preview",
        result_status="Previewed",
        attempted_by=user,
        message_digest=preview["message_digest"],
    )
    preview["delivery_attempt"] = attempt_name
    return preview


@frappe.whitelist()
def request_controlled_delivery(notification_name: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)

    reason = (
        "External email delivery is intentionally blocked in Step 4D. "
        "Complete provider readiness and activate controlled dispatch in Step 4E."
    )
    attempt_name = _record_attempt(
        notification=notification,
        attempt_type="Delivery Guard",
        result_status="Blocked",
        attempted_by=user,
        error_summary=reason,
    )
    return {
        "status": "blocked",
        "step": "4D",
        "notification": notification.name,
        "delivery_attempt": attempt_name,
        "reason": reason,
        "external_send_performed": 0,
        "email_queue_created": 0,
        "communication_created": 0,
    }
