
from __future__ import annotations

import hashlib
import html
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, get_url, now_datetime, nowdate

from pharma_erp.customer_order_notifications import (
    NOTIFICATION_DOCTYPE,
    PREFERENCE_DOCTYPE,
    _email_for_user,
    _mask_email,
    _recipient_hash,
)

SETTINGS_DOCTYPE = "Online Order Notification Delivery Settings"
ATTEMPT_DOCTYPE = "Online Order Notification Delivery Attempt"

DELIVERY_MODE_DISABLED = "Disabled"
DELIVERY_MODE_PREVIEW = "Preview Only"
DELIVERY_MODE_PILOT = "Controlled Pilot"
DELIVERY_MODE_CUSTOMER = "Controlled Customer"

ACTIVATION_PHRASE = "ACTIVATE STEP 4E PILOT"
DEACTIVATION_PHRASE = "DEACTIVATE STEP 4E PILOT"
DISPATCH_PHRASE = "QUEUE STEP 4E PILOT"
CUSTOMER_ACTIVATION_PHRASE = "ACTIVATE STEP 4F CUSTOMER"
CUSTOMER_DEACTIVATION_PHRASE = "DEACTIVATE STEP 4F CUSTOMER"
CUSTOMER_DISPATCH_PHRASE = "QUEUE STEP 4F CUSTOMER"
AUTO_ENABLE_PHRASE = "ENABLE STEP 4F AUTO"
AUTO_DISABLE_PHRASE = "DISABLE STEP 4F AUTO"

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_QUEUE_ACTIVE_STATUSES = {"Not Sent", "Sending"}
_QUEUE_SUCCESS_STATUSES = {"Sent", "Partially Sent"}
_QUEUE_FAILURE_STATUSES = {"Error"}

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
    if "System Manager" not in set(frappe.get_roles(user)):
        frappe.throw(
            _("Only a System Manager can control transactional email dispatch."),
            frappe.PermissionError,
        )
    return user


def _foundation_available() -> bool:
    required = (
        NOTIFICATION_DOCTYPE,
        PREFERENCE_DOCTYPE,
        SETTINGS_DOCTYPE,
        ATTEMPT_DOCTYPE,
        "Email Queue",
        "Email Account",
    )
    return all(frappe.db.exists("DocType", doctype) for doctype in required)


def get_settings():
    return frappe.get_single(SETTINGS_DOCTYPE)


def _save_settings_controlled(settings) -> None:
    settings.flags.ignore_permissions = True
    settings.flags.step4e_controlled_update = True
    settings.flags.step4f_controlled_update = True
    settings.save()


def _valid_email(value: str) -> bool:
    return bool(_EMAIL_PATTERN.fullmatch(str(value or "").strip().lower()))


def _pilot_email(settings) -> str:
    try:
        return str(
            settings.get_password(
                "pilot_recipient_email", raise_exception=False
            ) or ""
        ).strip().lower()
    except Exception:
        return ""


def _emails_are_muted() -> bool:
    try:
        return bool(frappe.are_emails_muted())
    except Exception:
        return True


def _email_queue_is_suspended() -> bool:
    return cint(frappe.db.get_default("suspend_email_queue")) == 1


def _outgoing_account_state(settings) -> dict[str, Any]:
    """Read the installed Email Account schema without assuming custom columns.

    Frappe v15 uses ``email_id`` (and, on some installations, ``login_id``)
    as the sender address. ``default_sender`` is not a standard database
    column, so the query must be assembled from fields that actually exist.
    """
    account_name = str(settings.outgoing_email_account or "").strip()
    if not account_name:
        return {
            "configured": 0,
            "enabled": 0,
            "account": "",
            "sender_address": "",
            "default_sender": "",
            "default_outgoing": 0,
            "reason": "No outgoing Email Account has been selected.",
        }

    account_meta = frappe.get_meta("Email Account")
    fields = ["name", "enable_outgoing", "default_outgoing"]
    for fieldname in ("email_id", "login_id"):
        if account_meta.has_field(fieldname):
            fields.append(fieldname)

    values = frappe.db.get_value(
        "Email Account",
        account_name,
        fields,
        as_dict=True,
    ) or {}
    if not values:
        return {
            "configured": 0,
            "enabled": 0,
            "account": account_name,
            "sender_address": "",
            "default_sender": "",
            "default_outgoing": 0,
            "reason": "The selected Email Account does not exist.",
        }

    sender_address = str(
        values.get("email_id") or values.get("login_id") or ""
    ).strip().lower()
    sender_name = str(settings.sender_display_name or "").strip()
    sender = (
        f"{sender_name} <{sender_address}>"
        if sender_name and sender_address
        else sender_address
    )
    enabled = cint(values.get("enable_outgoing"))
    sender_ready = _valid_email(sender_address)

    return {
        "configured": 1,
        "enabled": enabled,
        "account": values.get("name"),
        "sender_address": sender_address,
        # Preserve the existing key used by readiness and dispatch code.
        "default_sender": sender,
        "default_outgoing": cint(values.get("default_outgoing")),
        "reason": (
            ""
            if enabled and sender_ready
            else "The selected Email Account is not ready for outgoing mail."
        ),
    }


def bootstrap_delivery_settings() -> dict[str, Any]:
    settings = get_settings()
    changed = False

    defaults = {
        "delivery_mode": DELIVERY_MODE_PREVIEW,
        "outbound_email_enabled": 0,
        "activation_status": "Inactive",
        "pilot_mode_enabled": 0,
        "pilot_recipient_masked": "",
        "customer_mode_enabled": 0,
        "automatic_customer_dispatch_enabled": 0,
        "customer_dispatch_scope": "Post-Cutover Events Only",
        "allow_actual_customer_recipient": 0,
        "sender_display_name": "Cure Pharmacy",
        "portal_path": "/pharmacy-orders/",
        "daily_dispatch_limit": 5,
        "daily_customer_dispatch_limit": 20,
        "max_batch_size": 20,
        "max_attempts": 3,
        "retry_delay_minutes": 15,
        "require_recipient_hash_match": 1,
        "last_readiness_status": "Not Checked",
        "activation_note": (
            "Step 4F is installed in safe Preview Only mode. Legacy Deferred "
            "intents remain protected until explicit customer activation."
        ),
    }
    for fieldname, value in defaults.items():
        if settings.get(fieldname) in (None, ""):
            settings.set(fieldname, value)
            changed = True

    pilot_consistent = bool(
        settings.delivery_mode == DELIVERY_MODE_PILOT
        and cint(settings.outbound_email_enabled)
        and cint(settings.pilot_mode_enabled)
        and not cint(settings.customer_mode_enabled)
        and not cint(settings.allow_actual_customer_recipient)
        and settings.activation_status == "Active"
    )
    customer_consistent = bool(
        settings.delivery_mode == DELIVERY_MODE_CUSTOMER
        and cint(settings.outbound_email_enabled)
        and cint(settings.customer_mode_enabled)
        and cint(settings.allow_actual_customer_recipient)
        and not cint(settings.pilot_mode_enabled)
        and settings.activation_status == "Active"
    )
    active_consistent = pilot_consistent or customer_consistent

    if not active_consistent:
        if settings.delivery_mode not in (
            DELIVERY_MODE_DISABLED,
            DELIVERY_MODE_PREVIEW,
        ):
            settings.delivery_mode = DELIVERY_MODE_PREVIEW
            changed = True
        for fieldname in (
            "outbound_email_enabled",
            "pilot_mode_enabled",
            "customer_mode_enabled",
            "automatic_customer_dispatch_enabled",
            "allow_actual_customer_recipient",
        ):
            if cint(settings.get(fieldname)):
                settings.set(fieldname, 0)
                changed = True
        if settings.activation_status == "Active":
            settings.activation_status = "Inactive"
            changed = True
    elif pilot_consistent:
        for fieldname in (
            "customer_mode_enabled",
            "automatic_customer_dispatch_enabled",
            "allow_actual_customer_recipient",
        ):
            if cint(settings.get(fieldname)):
                settings.set(fieldname, 0)
                changed = True
    elif customer_consistent and cint(settings.pilot_mode_enabled):
        settings.pilot_mode_enabled = 0
        changed = True

    if not customer_consistent and cint(settings.allow_actual_customer_recipient):
        settings.allow_actual_customer_recipient = 0
        changed = True
    if not customer_consistent and cint(settings.automatic_customer_dispatch_enabled):
        settings.automatic_customer_dispatch_enabled = 0
        changed = True
    if not cint(settings.require_recipient_hash_match):
        settings.require_recipient_hash_match = 1
        changed = True
    if settings.customer_dispatch_scope != "Post-Cutover Events Only":
        settings.customer_dispatch_scope = "Post-Cutover Events Only"
        changed = True

    if changed:
        _save_settings_controlled(settings)

    return {
        "delivery_mode": settings.delivery_mode,
        "outbound_email_enabled": cint(settings.outbound_email_enabled),
        "activation_status": settings.activation_status,
        "pilot_mode_enabled": cint(settings.pilot_mode_enabled),
        "pilot_recipient_masked": settings.pilot_recipient_masked,
        "customer_mode_enabled": cint(settings.customer_mode_enabled),
        "automatic_customer_dispatch_enabled": cint(
            settings.automatic_customer_dispatch_enabled
        ),
        "customer_dispatch_cutover_at": settings.customer_dispatch_cutover_at,
        "allow_actual_customer_recipient": cint(
            settings.allow_actual_customer_recipient
        ),
        "daily_dispatch_limit": cint(settings.daily_dispatch_limit),
        "daily_customer_dispatch_limit": cint(
            settings.daily_customer_dispatch_limit
        ),
        "max_attempts": cint(settings.max_attempts),
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


def _dispatches_today(provider_mode: str | None = None) -> int:
    where_mode = ""
    values: list[Any] = [nowdate()]
    if provider_mode:
        where_mode = " AND provider_mode=%s"
        values.append(provider_mode)
    rows = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tab{ATTEMPT_DOCTYPE}`
        WHERE attempt_type='Queue Dispatch'
          AND result_status='Queued'
          AND DATE(attempted_at)=%s
          {where_mode}
        """,
        tuple(values),
        as_list=True,
    )
    return int(rows[0][0] or 0) if rows else 0


def _customer_cutover(settings):
    value = settings.customer_dispatch_cutover_at
    return get_datetime(value) if value else None


def _notification_timestamp(notification):
    value = notification.get("created_at") or notification.get("event_at")
    return get_datetime(value) if value else None


def _protected_legacy_deferred_count(settings) -> int:
    cutover = _customer_cutover(settings)
    filters: dict[str, Any] = {
        "notification_status": ["in", ["Deferred", "Failed"]],
        "channel": "Email",
        "is_transactional": 1,
    }
    if cutover:
        filters["created_at"] = ["<", cutover]
    return frappe.db.count(NOTIFICATION_DOCTYPE, filters)


def _eligible_post_cutover_count(settings) -> int:
    cutover = _customer_cutover(settings)
    if not cutover:
        return 0
    return frappe.db.count(
        NOTIFICATION_DOCTYPE,
        {
            "notification_status": ["in", ["Deferred", "Failed"]],
            "channel": "Email",
            "is_transactional": 1,
            "created_at": [">=", cutover],
        },
    )


def _readiness_payload() -> dict[str, Any]:
    settings = get_settings()
    account = _outgoing_account_state(settings)
    pilot_email = _pilot_email(settings)
    muted = int(_emails_are_muted())
    queue_suspended = int(_email_queue_is_suspended())

    preview_ready = int(
        _foundation_available()
        and cint(settings.require_recipient_hash_match)
    )
    activation_ready = int(
        preview_ready
        and bool(account.get("configured"))
        and bool(account.get("enabled"))
        and bool(account.get("default_sender"))
        and not muted
        and not queue_suspended
    )
    pilot_active = int(
        settings.delivery_mode == DELIVERY_MODE_PILOT
        and cint(settings.outbound_email_enabled)
        and cint(settings.pilot_mode_enabled)
        and not cint(settings.customer_mode_enabled)
        and settings.activation_status == "Active"
        and _valid_email(pilot_email)
        and activation_ready
    )
    customer_active = int(
        settings.delivery_mode == DELIVERY_MODE_CUSTOMER
        and cint(settings.outbound_email_enabled)
        and cint(settings.customer_mode_enabled)
        and cint(settings.allow_actual_customer_recipient)
        and not cint(settings.pilot_mode_enabled)
        and settings.activation_status == "Active"
        and bool(_customer_cutover(settings))
        and activation_ready
    )
    auto_active = int(
        customer_active
        and cint(settings.automatic_customer_dispatch_enabled)
    )

    blockers: list[str] = []
    if not account.get("configured"):
        blockers.append("Select an outgoing Email Account.")
    elif not account.get("enabled"):
        blockers.append("Enable outgoing mail on the selected Email Account.")
    elif not account.get("default_sender"):
        blockers.append("Configure a sender address on the Email Account.")
    if muted:
        blockers.append("Email sending is muted in site configuration.")
    if queue_suspended:
        blockers.append("The Frappe Email Queue is suspended.")
    if not cint(settings.require_recipient_hash_match):
        blockers.append("Recipient hash matching must remain enabled.")
    if (
        cint(settings.allow_actual_customer_recipient)
        and not customer_active
    ):
        blockers.append(
            "Actual customer recipients require active Step 4F customer mode."
        )

    readiness_status = (
        "Customer Auto Dispatch Active"
        if auto_active
        else "Controlled Customer Active"
        if customer_active
        else "Controlled Pilot Active"
        if pilot_active
        else "Ready for Customer Activation"
        if activation_ready
        else "Preview Ready"
        if preview_ready
        else "Configuration Required"
    )

    return {
        "status": "ok",
        "step": "4F",
        "delivery_mode": settings.delivery_mode,
        "outbound_email_enabled": cint(settings.outbound_email_enabled),
        "activation_status": settings.activation_status,
        "pilot_mode_enabled": cint(settings.pilot_mode_enabled),
        "pilot_recipient_masked": settings.pilot_recipient_masked,
        "customer_mode_enabled": cint(settings.customer_mode_enabled),
        "automatic_customer_dispatch_enabled": cint(
            settings.automatic_customer_dispatch_enabled
        ),
        "customer_dispatch_cutover_at": settings.customer_dispatch_cutover_at,
        "preview_ready": preview_ready,
        "activation_ready": activation_ready,
        "pilot_active": pilot_active,
        "customer_active": customer_active,
        "auto_dispatch_active": auto_active,
        "readiness_status": readiness_status,
        "blockers": blockers,
        "outgoing_email_account": account,
        "emails_muted": muted,
        "email_queue_suspended": queue_suspended,
        "pilot_dispatches_today": _dispatches_today(DELIVERY_MODE_PILOT),
        "customer_dispatches_today": _dispatches_today(DELIVERY_MODE_CUSTOMER),
        "daily_pilot_dispatch_limit": cint(settings.daily_dispatch_limit),
        "daily_customer_dispatch_limit": cint(
            settings.daily_customer_dispatch_limit
        ),
        "protected_legacy_deferred": _protected_legacy_deferred_count(settings),
        "eligible_post_cutover": _eligible_post_cutover_count(settings),
        "notification_counts": _notification_counts(),
        "delivery_attempts": frappe.db.count(ATTEMPT_DOCTYPE),
        "actual_customer_recipient_enabled": cint(
            settings.allow_actual_customer_recipient
        ),
    }


def _record_attempt(
    *,
    notification,
    attempt_type: str,
    result_status: str,
    attempted_by: str,
    recipient_masked: str | None = None,
    recipient_hash: str | None = None,
    provider_mode: str | None = None,
    dispatch_source: str = "",
    provider_reference: str = "",
    queue_status: str = "",
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
            "recipient_masked": (
                recipient_masked
                if recipient_masked is not None
                else notification.recipient_masked
            ),
            "recipient_hash": (
                recipient_hash
                if recipient_hash is not None
                else notification.recipient_hash
            ),
            "template_key": notification.template_key,
            "subject": notification.subject,
            "provider_mode": provider_mode or get_settings().delivery_mode,
            "dispatch_source": dispatch_source,
            "provider_reference": provider_reference,
            "queue_status": queue_status,
            "message_digest": message_digest,
            "error_summary": error_summary[:1000],
            "attempted_at": now_datetime(),
            "attempted_by": attempted_by,
        }
    ).insert(ignore_permissions=True)
    return doc.name


def _build_message(notification, *, pilot: bool) -> dict[str, Any]:
    settings = get_settings()
    actual_email = _email_for_user(str(notification.website_user or ""))
    current_hash = _recipient_hash(actual_email) if actual_email else ""
    stored_hash = str(notification.recipient_hash or "")
    hash_matches = int(bool(actual_email) and current_hash == stored_hash)

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
    portal_url = get_url(portal_path)

    base_subject = str(notification.subject or "").strip()
    subject = f"[STEP 4E PILOT] {base_subject}" if pilot else base_subject
    message = str(notification.message_preview or "").strip()
    order_name = str(notification.online_order or "").strip()

    pilot_banner = (
        '<div style="padding:10px 12px;border:1px solid #f59e0b;'
        'background:#fffbeb;color:#92400e;margin-bottom:16px">'
        "<strong>Controlled Pilot:</strong> "
        "هذه الرسالة موجهة إلى بريد الاختبار فقط، وليس إلى بريد العميل."
        "</div>"
        if pilot
        else ""
    )

    body_html = (
        '<div dir="rtl" style="font-family:Arial,sans-serif;line-height:1.8">'
        f"{pilot_banner}"
        f"<h2>{html.escape(base_subject)}</h2>"
        f"<p>{html.escape(message)}</p>"
        f"<p><strong>رقم الطلب:</strong> {html.escape(order_name)}</p>"
        f'<p><a href="{html.escape(portal_url, quote=True)}">'
        "فتح حسابي ومتابعة الطلب</a></p>"
        '<p style="color:#64748b;font-size:13px">'
        "رسالة آلية خاصة بتحديث حالة الطلب.</p></div>"
    )
    body_text = (
        f"{subject}\n\n{message}\n"
        f"رقم الطلب: {order_name}\n"
        f"متابعة الطلب: {portal_url}\n"
    )
    digest = hashlib.sha256(
        f"{subject}|{body_text}|{stored_hash}".encode("utf-8")
    ).hexdigest()

    return {
        "subject": subject,
        "body_html": body_html,
        "body_text": body_text,
        "message_digest": digest,
        "actual_recipient_hash_matches": hash_matches,
    }


def _preference_allows_dispatch(notification) -> bool:
    preference = frappe.db.get_value(
        PREFERENCE_DOCTYPE,
        notification.website_user,
        ["order_updates_enabled", "email_enabled"],
        as_dict=True,
    ) or {}
    return bool(
        cint(preference.get("order_updates_enabled"))
        and cint(preference.get("email_enabled"))
    )


def _assert_pilot_active(settings) -> str:
    readiness = _readiness_payload()
    if not readiness["pilot_active"]:
        frappe.throw(
            _("Controlled Pilot dispatch is not active or no longer ready.")
        )
    pilot_email = _pilot_email(settings)
    if not _valid_email(pilot_email):
        frappe.throw(_("A valid encrypted pilot recipient is required."))
    return pilot_email


def _website_customer_emails() -> set[str]:
    rows = frappe.db.sql(
        """
        SELECT DISTINCT LOWER(user_doc.email)
        FROM `tabOnline Order` order_doc
        INNER JOIN `tabUser` user_doc
            ON user_doc.name=order_doc.custom_website_user
        WHERE IFNULL(order_doc.custom_website_user,'')!=''
          AND user_doc.enabled=1
          AND IFNULL(user_doc.email,'')!=''
        """,
        as_list=True,
    )
    return {str(row[0] or "").strip().lower() for row in rows if row[0]}



def _website_user_state(user: str) -> dict[str, Any]:
    values = frappe.db.get_value(
        "User",
        user,
        ["name", "email", "enabled", "user_type"],
        as_dict=True,
    ) or {}
    email = str(values.get("email") or values.get("name") or "").strip().lower()
    return {
        "exists": int(bool(values)),
        "enabled": cint(values.get("enabled")),
        "user_type": str(values.get("user_type") or ""),
        "email": email if _valid_email(email) else "",
    }


def _order_website_user(order_name: str) -> str:
    return str(
        frappe.db.get_value(
            "Online Order", order_name, "custom_website_user"
        ) or ""
    ).strip()


def _queue_state(queue_name: str) -> dict[str, Any]:
    if not queue_name or not frappe.db.exists("Email Queue", queue_name):
        return {"exists": 0, "status": "", "error": ""}
    values = frappe.db.get_value(
        "Email Queue", queue_name, ["status", "error"], as_dict=True
    ) or {}
    return {
        "exists": 1,
        "status": str(values.get("status") or ""),
        "error": str(values.get("error") or ""),
    }


def _retry_delay_satisfied(notification, settings) -> bool:
    if notification.notification_status != "Failed":
        return True
    if not notification.last_attempt_at:
        return True
    retry_at = add_to_date(
        get_datetime(notification.last_attempt_at),
        minutes=max(1, cint(settings.retry_delay_minutes or 15)),
        as_datetime=True,
    )
    return now_datetime() >= retry_at


def _customer_dispatch_eligibility(notification, settings=None) -> dict[str, Any]:
    settings = settings or get_settings()
    readiness = _readiness_payload()
    reasons: list[str] = []

    if not readiness["customer_active"]:
        reasons.append("Controlled Customer dispatch is not active or ready.")
    if notification.notification_status not in ("Deferred", "Failed"):
        reasons.append("Only Deferred or Failed notification intents can be queued.")
    if str(notification.channel or "") != "Email":
        reasons.append("Only Email notification intents are supported.")
    if not cint(notification.is_transactional):
        reasons.append("Only transactional notifications can be delivered.")

    cutover = _customer_cutover(settings)
    notification_time = _notification_timestamp(notification)
    post_cutover = int(bool(cutover and notification_time and notification_time >= cutover))
    if not cutover:
        reasons.append("Customer dispatch cutover has not been established.")
    elif not post_cutover:
        reasons.append("This legacy intent is protected by the Step 4F cutover.")

    website_user = str(notification.website_user or "").strip()
    user_state = _website_user_state(website_user)
    if not user_state["exists"] or not user_state["enabled"]:
        reasons.append("The Website User is missing or disabled.")
    elif user_state["user_type"] != "Website User":
        reasons.append("The notification recipient is not a Website User.")

    order_user = _order_website_user(str(notification.online_order or ""))
    ownership_matches = int(bool(website_user and order_user == website_user))
    if not ownership_matches:
        reasons.append("The Website User does not own the Online Order.")

    actual_email = user_state["email"]
    current_hash = _recipient_hash(actual_email) if actual_email else ""
    stored_hash = str(notification.recipient_hash or "")
    hash_matches = int(bool(actual_email) and current_hash == stored_hash)
    if not actual_email:
        reasons.append("The Website User does not have a valid email address.")
    elif cint(settings.require_recipient_hash_match) and not hash_matches:
        reasons.append("The current email does not match the stored recipient hash.")

    preference_allows = int(_preference_allows_dispatch(notification))
    if not preference_allows:
        reasons.append("The customer has disabled email order updates.")

    attempts_remaining = max(
        0, cint(settings.max_attempts) - cint(notification.attempt_count)
    )
    if attempts_remaining <= 0:
        reasons.append("The maximum dispatch attempts have been reached.")
    if not _retry_delay_satisfied(notification, settings):
        reasons.append("The retry delay has not elapsed yet.")

    queue = _queue_state(str(notification.provider_reference or "").strip())
    if queue["status"] in (_QUEUE_ACTIVE_STATUSES | _QUEUE_SUCCESS_STATUSES):
        reasons.append(
            f"The linked Email Queue is already {queue['status']}."
        )

    today = _dispatches_today(DELIVERY_MODE_CUSTOMER)
    daily_limit = cint(settings.daily_customer_dispatch_limit)
    if today >= daily_limit:
        reasons.append("The daily customer dispatch limit has been reached.")

    return {
        "eligible": int(not reasons),
        "reasons": reasons,
        "notification": notification.name,
        "notification_status": notification.notification_status,
        "post_cutover": post_cutover,
        "cutover_at": settings.customer_dispatch_cutover_at,
        "recipient_masked": _mask_email(actual_email) if actual_email else "",
        "recipient_hash_matches": hash_matches,
        "order_ownership_matches": ownership_matches,
        "preference_allows": preference_allows,
        "attempts_remaining": attempts_remaining,
        "existing_queue_status": queue["status"],
        "customer_dispatches_today": today,
        "daily_customer_dispatch_limit": daily_limit,
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
            "Controlled customer activation requirements are satisfied."
        )
        _save_settings_controlled(settings)

    return payload


@frappe.whitelist()
def preview_notification(notification_name: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)
    preview = _build_message(notification, pilot=False)
    attempt_name = _record_attempt(
        notification=notification,
        attempt_type="Template Preview",
        result_status="Previewed",
        attempted_by=user,
        provider_mode=DELIVERY_MODE_PREVIEW,
        dispatch_source="Preview",
        message_digest=preview["message_digest"],
    )
    return {
        "notification": notification.name,
        "online_order": notification.online_order,
        "website_user": notification.website_user,
        "source_status": notification.source_status,
        "event_key": notification.event_key,
        "recipient_masked": notification.recipient_masked,
        "recipient_hash_matches": preview["actual_recipient_hash_matches"],
        "template_key": notification.template_key,
        "subject": notification.subject,
        "body_html": preview["body_html"],
        "body_text": preview["body_text"],
        "message_digest": preview["message_digest"],
        "notification_status": notification.notification_status,
        "delivery_mode": get_settings().delivery_mode,
        "outbound_email_enabled": cint(
            get_settings().outbound_email_enabled
        ),
        "delivery_attempt": attempt_name,
        "external_send_performed": 0,
    }


@frappe.whitelist()
def request_controlled_delivery(notification_name: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)
    reason = (
        "Direct customer delivery is blocked unless Step 4F Controlled "
        "Customer mode and all eligibility safeguards pass. Use the "
        "controlled customer queue action for eligible post-cutover events."
    )
    attempt_name = _record_attempt(
        notification=notification,
        attempt_type="Delivery Guard",
        result_status="Blocked",
        attempted_by=user,
        provider_mode=get_settings().delivery_mode,
        dispatch_source="Guard",
        error_summary=reason,
    )
    return {
        "status": "blocked",
        "step": "4F",
        "notification": notification.name,
        "delivery_attempt": attempt_name,
        "reason": reason,
        "external_send_performed": 0,
        "email_queue_created": 0,
        "communication_created": 0,
    }


@frappe.whitelist()
def activate_pilot_dispatch(
    pilot_recipient: str,
    confirmation_text: str,
) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    if str(confirmation_text or "").strip() != ACTIVATION_PHRASE:
        frappe.throw(_("The Step 4E activation confirmation text is incorrect."))

    email = str(pilot_recipient or "").strip().lower()
    if not _valid_email(email):
        frappe.throw(_("Enter a valid pilot recipient email address."))
    if email in _website_customer_emails():
        frappe.throw(
            _(
                "The pilot recipient must not match an active website customer "
                "email address."
            )
        )

    settings = get_settings()
    readiness = _readiness_payload()
    if not readiness["activation_ready"]:
        frappe.throw(
            _("Email delivery is not ready for controlled pilot activation.")
        )

    settings.pilot_recipient_email = email
    settings.pilot_recipient_masked = _mask_email(email)
    settings.delivery_mode = DELIVERY_MODE_PILOT
    settings.outbound_email_enabled = 1
    settings.pilot_mode_enabled = 1
    settings.customer_mode_enabled = 0
    settings.automatic_customer_dispatch_enabled = 0
    settings.allow_actual_customer_recipient = 0
    settings.activation_status = "Active"
    settings.last_activation_at = now_datetime()
    settings.last_activation_by = user
    settings.activation_note = (
        "Controlled Pilot is active. Only the encrypted pilot recipient can "
        "receive explicitly queued Step 4E messages."
    )
    _save_settings_controlled(settings)

    return {
        "status": "active",
        "step": "4E",
        "delivery_mode": settings.delivery_mode,
        "pilot_recipient_masked": settings.pilot_recipient_masked,
        "actual_customer_recipient_enabled": 0,
        "automatic_bulk_dispatch_enabled": 0,
        "external_email_queued": 0,
    }


@frappe.whitelist()
def deactivate_pilot_dispatch(
    confirmation_text: str,
) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    if str(confirmation_text or "").strip() != DEACTIVATION_PHRASE:
        frappe.throw(_("The Step 4E deactivation confirmation text is incorrect."))

    settings = get_settings()
    settings.delivery_mode = DELIVERY_MODE_PREVIEW
    settings.outbound_email_enabled = 0
    settings.pilot_mode_enabled = 0
    settings.customer_mode_enabled = 0
    settings.automatic_customer_dispatch_enabled = 0
    settings.allow_actual_customer_recipient = 0
    settings.activation_status = "Inactive"
    settings.last_deactivation_at = now_datetime()
    settings.last_deactivation_by = user
    settings.activation_note = (
        "Controlled Pilot is inactive. No new pilot dispatch can be queued."
    )
    _save_settings_controlled(settings)

    return {
        "status": "inactive",
        "step": "4E",
        "pending_queues_are_not_cancelled": 1,
        "external_email_queued": 0,
    }



@frappe.whitelist()
def get_customer_dispatch_eligibility(notification_name: str) -> dict[str, Any]:
    _set_no_store_headers()
    _require_system_manager()
    notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)
    result = _customer_dispatch_eligibility(notification)
    return {"status": "ok", "step": "4F", **result}


@frappe.whitelist()
def activate_customer_dispatch(confirmation_text: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    if str(confirmation_text or "").strip() != CUSTOMER_ACTIVATION_PHRASE:
        frappe.throw(_("The Step 4F customer activation confirmation text is incorrect."))

    settings = get_settings()
    readiness = _readiness_payload()
    if not readiness["activation_ready"]:
        frappe.throw(_("Email delivery is not ready for customer activation."))

    if not settings.customer_dispatch_cutover_at:
        settings.customer_dispatch_cutover_at = now_datetime()
        settings.customer_dispatch_cutover_by = user

    settings.delivery_mode = DELIVERY_MODE_CUSTOMER
    settings.outbound_email_enabled = 1
    settings.pilot_mode_enabled = 0
    settings.customer_mode_enabled = 1
    settings.automatic_customer_dispatch_enabled = 0
    settings.allow_actual_customer_recipient = 1
    settings.activation_status = "Active"
    settings.last_activation_at = now_datetime()
    settings.last_activation_by = user
    settings.activation_note = (
        "Controlled Customer mode is active for post-cutover transactional "
        "events only. Automatic dispatch remains disabled until separately enabled."
    )
    _save_settings_controlled(settings)

    return {
        "status": "active",
        "step": "4F",
        "delivery_mode": settings.delivery_mode,
        "customer_dispatch_cutover_at": settings.customer_dispatch_cutover_at,
        "automatic_customer_dispatch_enabled": 0,
        "actual_customer_recipient_enabled": 1,
        "protected_legacy_deferred": _protected_legacy_deferred_count(settings),
        "external_email_queued": 0,
    }


@frappe.whitelist()
def deactivate_customer_dispatch(confirmation_text: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    if str(confirmation_text or "").strip() != CUSTOMER_DEACTIVATION_PHRASE:
        frappe.throw(_("The Step 4F customer deactivation confirmation text is incorrect."))

    settings = get_settings()
    settings.delivery_mode = DELIVERY_MODE_PREVIEW
    settings.outbound_email_enabled = 0
    settings.pilot_mode_enabled = 0
    settings.customer_mode_enabled = 0
    settings.automatic_customer_dispatch_enabled = 0
    settings.allow_actual_customer_recipient = 0
    settings.activation_status = "Inactive"
    settings.last_deactivation_at = now_datetime()
    settings.last_deactivation_by = user
    settings.activation_note = (
        "Controlled Customer mode is inactive. Existing Email Queue rows are not cancelled."
    )
    _save_settings_controlled(settings)

    return {
        "status": "inactive",
        "step": "4F",
        "customer_dispatch_cutover_at": settings.customer_dispatch_cutover_at,
        "pending_queues_are_not_cancelled": 1,
        "external_email_queued": 0,
    }


@frappe.whitelist()
def enable_automatic_customer_dispatch(confirmation_text: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    if str(confirmation_text or "").strip() != AUTO_ENABLE_PHRASE:
        frappe.throw(_("The Step 4F automatic-dispatch confirmation text is incorrect."))

    settings = get_settings()
    readiness = _readiness_payload()
    if not readiness["customer_active"]:
        frappe.throw(_("Activate Controlled Customer mode first."))

    settings.automatic_customer_dispatch_enabled = 1
    settings.activation_note = (
        "Automatic Step 4F dispatch is active for eligible post-cutover "
        "transactional email intents within configured limits."
    )
    _save_settings_controlled(settings)
    return {
        "status": "active",
        "step": "4F",
        "automatic_customer_dispatch_enabled": 1,
        "enabled_by": user,
        "external_email_queued": 0,
    }


@frappe.whitelist()
def disable_automatic_customer_dispatch(confirmation_text: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    if str(confirmation_text or "").strip() != AUTO_DISABLE_PHRASE:
        frappe.throw(_("The Step 4F automatic-dispatch disable text is incorrect."))

    settings = get_settings()
    settings.automatic_customer_dispatch_enabled = 0
    settings.activation_note = (
        "Automatic Step 4F dispatch is disabled. Controlled Customer mode may remain active."
    )
    _save_settings_controlled(settings)
    return {
        "status": "inactive",
        "step": "4F",
        "automatic_customer_dispatch_enabled": 0,
        "disabled_by": user,
        "external_email_queued": 0,
    }



def _lock_notification_for_dispatch(notification_name: str) -> None:
    rows = frappe.db.sql(
        f"SELECT name FROM `tab{NOTIFICATION_DOCTYPE}` WHERE name=%s FOR UPDATE",
        (notification_name,),
        as_list=True,
    )
    if not rows:
        frappe.throw(_("The notification intent does not exist."))


def _queue_customer_notification_internal(
    notification_name: str,
    *,
    actor: str,
    dispatch_source: str,
) -> dict[str, Any]:
    settings = get_settings()
    _lock_notification_for_dispatch(notification_name)
    notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)
    eligibility = _customer_dispatch_eligibility(notification, settings)
    if not eligibility["eligible"]:
        frappe.throw(
            _("Customer dispatch is blocked: {0}").format(
                " ".join(eligibility["reasons"])
            )
        )

    actual_email = _email_for_user(str(notification.website_user or ""))
    message = _build_message(notification, pilot=False)
    account = _outgoing_account_state(settings)
    if not account.get("enabled") or not account.get("default_sender"):
        frappe.throw(_("The selected outgoing Email Account is not ready."))

    savepoint = (
        "step4f_queue_"
        + hashlib.sha1(notification.name.encode("utf-8")).hexdigest()[:10]
    )
    frappe.db.savepoint(savepoint)
    try:
        queue_doc = frappe.sendmail(
            recipients=[actual_email],
            sender=account["default_sender"],
            subject=message["subject"],
            message=message["body_html"],
            delayed=True,
            now=False,
            add_unsubscribe_link=0,
            queue_separately=False,
            is_notification=True,
            with_container=True,
            expose_recipients=None,
            email_headers={
                "Pharma-Notification-ID": notification.name,
                "Pharma-Step4F-Customer": "1",
                "Pharma-Dispatch-Source": dispatch_source,
            },
        )
        if not queue_doc or not getattr(queue_doc, "name", None):
            frappe.throw(_("Frappe did not create an Email Queue record."))

        if queue_doc.email_account != settings.outgoing_email_account:
            queue_doc.db_set(
                "email_account",
                settings.outgoing_email_account,
                update_modified=False,
            )

        frappe.db.set_value(
            NOTIFICATION_DOCTYPE,
            notification.name,
            {
                "notification_status": "Pending",
                "provider_reference": queue_doc.name,
                "attempt_count": cint(notification.attempt_count) + 1,
                "last_attempt_at": now_datetime(),
                "defer_reason": "",
            },
            update_modified=True,
        )
        attempt_name = _record_attempt(
            notification=notification,
            attempt_type="Queue Dispatch",
            result_status="Queued",
            attempted_by=actor,
            recipient_masked=_mask_email(actual_email),
            recipient_hash=_recipient_hash(actual_email),
            provider_mode=DELIVERY_MODE_CUSTOMER,
            dispatch_source=dispatch_source,
            provider_reference=queue_doc.name,
            queue_status=queue_doc.status,
            message_digest=message["message_digest"],
        )
        settings.last_customer_dispatch_at = now_datetime()
        if dispatch_source == "Customer Automatic":
            settings.last_auto_dispatch_at = now_datetime()
        _save_settings_controlled(settings)
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise

    return {
        "status": "queued",
        "step": "4F",
        "notification": notification.name,
        "email_queue": queue_doc.name,
        "email_queue_status": queue_doc.status,
        "email_account": settings.outgoing_email_account,
        "customer_recipient_masked": _mask_email(actual_email),
        "delivery_attempt": attempt_name,
        "dispatch_source": dispatch_source,
        "actual_customer_recipient_used": 1,
        "communication_created": 0,
    }


@frappe.whitelist()
def queue_customer_notification(
    notification_name: str,
    confirmation_text: str,
) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    if str(confirmation_text or "").strip() != CUSTOMER_DISPATCH_PHRASE:
        frappe.throw(_("The Step 4F customer dispatch confirmation text is incorrect."))
    return _queue_customer_notification_internal(
        notification_name,
        actor=user,
        dispatch_source="Customer Manual",
    )


@frappe.whitelist()
def queue_pilot_notification(
    notification_name: str,
    confirmation_text: str,
) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    if str(confirmation_text or "").strip() != DISPATCH_PHRASE:
        frappe.throw(_("The Step 4E pilot dispatch confirmation text is incorrect."))

    settings = get_settings()
    pilot_email = _assert_pilot_active(settings)
    notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)

    if notification.notification_status not in ("Deferred", "Failed"):
        frappe.throw(
            _(
                "Only Deferred or Failed notification intents can be queued."
            )
        )
    if not _preference_allows_dispatch(notification):
        frappe.throw(_("The customer has disabled email order updates."))
    if cint(notification.attempt_count) >= cint(settings.max_attempts):
        frappe.throw(_("The maximum dispatch attempts have been reached."))
    if _dispatches_today(DELIVERY_MODE_PILOT) >= cint(settings.daily_dispatch_limit):
        frappe.throw(_("The daily Step 4E pilot dispatch limit has been reached."))

    message = _build_message(notification, pilot=True)
    account = _outgoing_account_state(settings)
    if not account.get("enabled") or not account.get("default_sender"):
        frappe.throw(_("The selected outgoing Email Account is not ready."))

    savepoint = (
        "step4e_queue_"
        + hashlib.sha1(notification.name.encode("utf-8")).hexdigest()[:10]
    )
    frappe.db.savepoint(savepoint)
    try:
        queue_doc = frappe.sendmail(
            recipients=[pilot_email],
            sender=account["default_sender"],
            subject=message["subject"],
            message=message["body_html"],
            delayed=True,
            now=False,
            add_unsubscribe_link=0,
            queue_separately=False,
            is_notification=True,
            with_container=True,
            expose_recipients=None,
            email_headers={
                "Pharma-Notification-ID": notification.name,
                "Pharma-Step4E-Pilot": "1",
            },
        )
        if not queue_doc or not getattr(queue_doc, "name", None):
            frappe.throw(_("Frappe did not create an Email Queue record."))

        if queue_doc.email_account != settings.outgoing_email_account:
            queue_doc.db_set(
                "email_account",
                settings.outgoing_email_account,
                update_modified=False,
            )

        frappe.db.set_value(
            NOTIFICATION_DOCTYPE,
            notification.name,
            {
                "notification_status": "Pending",
                "provider_reference": queue_doc.name,
                "attempt_count": cint(notification.attempt_count) + 1,
                "last_attempt_at": now_datetime(),
                "defer_reason": "",
            },
            update_modified=True,
        )
        attempt_name = _record_attempt(
            notification=notification,
            attempt_type="Queue Dispatch",
            result_status="Queued",
            attempted_by=user,
            recipient_masked=_mask_email(pilot_email),
            recipient_hash=_recipient_hash(pilot_email),
            provider_mode=DELIVERY_MODE_PILOT,
            dispatch_source="Pilot Manual",
            provider_reference=queue_doc.name,
            queue_status=queue_doc.status,
            message_digest=message["message_digest"],
        )
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise

    return {
        "status": "queued",
        "step": "4E",
        "notification": notification.name,
        "email_queue": queue_doc.name,
        "email_queue_status": queue_doc.status,
        "email_account": settings.outgoing_email_account,
        "pilot_recipient_masked": _mask_email(pilot_email),
        "delivery_attempt": attempt_name,
        "actual_customer_recipient_used": 0,
        "communication_created": 0,
    }


def _reconciliation_attempt_exists(
    notification_name: str,
    queue_name: str,
    result_status: str,
) -> bool:
    return bool(
        frappe.db.exists(
            ATTEMPT_DOCTYPE,
            {
                "notification": notification_name,
                "attempt_type": "Dispatch Reconciliation",
                "provider_reference": queue_name,
                "result_status": result_status,
            },
        )
    )


def _reconcile_one(notification, *, actor: str) -> dict[str, Any]:
    queue_name = str(notification.provider_reference or "").strip()
    if not queue_name or not frappe.db.exists("Email Queue", queue_name):
        return {
            "notification": notification.name,
            "status": "missing_queue",
            "changed": 0,
        }

    queue_values = frappe.db.get_value(
        "Email Queue",
        queue_name,
        ["status", "error", "email_account"],
        as_dict=True,
    ) or {}
    queue_status = str(queue_values.get("status") or "")

    if queue_status in _QUEUE_SUCCESS_STATUSES:
        target_status = "Sent"
        result_status = "Sent"
    elif queue_status in _QUEUE_FAILURE_STATUSES:
        target_status = "Failed"
        result_status = "Failed"
    else:
        target_status = "Pending"
        result_status = "Pending"

    changed = int(notification.notification_status != target_status)
    values: dict[str, Any] = {"notification_status": target_status}
    if target_status == "Sent":
        values["sent_at"] = now_datetime()
    elif target_status == "Failed":
        values["defer_reason"] = "Frappe Email Queue reported an error."
        values["last_attempt_at"] = now_datetime()

    if changed:
        frappe.db.set_value(
            NOTIFICATION_DOCTYPE,
            notification.name,
            values,
            update_modified=True,
        )

    provider_mode = str(
        frappe.db.get_value(
            ATTEMPT_DOCTYPE,
            {
                "notification": notification.name,
                "attempt_type": "Queue Dispatch",
                "provider_reference": queue_name,
            },
            "provider_mode",
            order_by="attempted_at desc",
        )
        or get_settings().delivery_mode
        or DELIVERY_MODE_PREVIEW
    )
    if not _reconciliation_attempt_exists(
        notification.name, queue_name, result_status
    ):
        _record_attempt(
            notification=notification,
            attempt_type="Dispatch Reconciliation",
            result_status=result_status,
            attempted_by=actor,
            recipient_masked="",
            recipient_hash="",
            provider_mode=provider_mode,
            dispatch_source="Reconciliation",
            provider_reference=queue_name,
            queue_status=queue_status,
            error_summary=str(queue_values.get("error") or "")[:1000],
        )

    return {
        "notification": notification.name,
        "status": target_status,
        "queue_status": queue_status,
        "changed": changed,
    }


@frappe.whitelist()
def refresh_dispatch_status(notification_name: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_system_manager()
    notification = frappe.get_doc(NOTIFICATION_DOCTYPE, notification_name)
    result = _reconcile_one(notification, actor=user)
    settings = get_settings()
    settings.last_reconciliation_at = now_datetime()
    _save_settings_controlled(settings)
    return {"status": "ok", "step": "4F", "result": result}


def reconcile_pending_dispatches(limit: int = 50) -> dict[str, Any]:
    """Reconcile existing Email Queue statuses only.

    This scheduled method never creates a new Email Queue and never dispatches
    a Deferred or Failed notification intent.
    """
    if not _foundation_available():
        return {"status": "skipped", "reason": "foundation_unavailable"}

    names = frappe.get_all(
        NOTIFICATION_DOCTYPE,
        filters={
            "notification_status": "Pending",
            "provider_reference": ["!=", ""],
        },
        pluck="name",
        order_by="last_attempt_at asc",
        limit_page_length=max(1, min(cint(limit or 50), 200)),
    )
    results = []
    for name in names:
        notification = frappe.get_doc(NOTIFICATION_DOCTYPE, name)
        results.append(_reconcile_one(notification, actor="Administrator"))

    if names:
        settings = get_settings()
        settings.last_reconciliation_at = now_datetime()
        _save_settings_controlled(settings)
        frappe.db.commit()

    return {
        "status": "ok",
        "step": "4F",
        "pending_seen": len(names),
        "results": results,
        "email_queues_created": 0,
    }



def dispatch_eligible_customer_notifications(limit: int = 0) -> dict[str, Any]:
    """Queue only eligible post-cutover customer intents when explicitly enabled.

    Safe properties:
    - Does nothing unless Controlled Customer and automatic dispatch are active.
    - Never touches protected pre-cutover Deferred/Failed intents.
    - Respects preferences, order ownership, recipient hash, attempt, retry,
      batch, and daily limits.
    - Creates no Sales Invoice, Payment Entry, GL Entry, or Stock Ledger Entry.
    """
    if not _foundation_available():
        return {"status": "skipped", "reason": "foundation_unavailable"}

    settings = get_settings()
    readiness = _readiness_payload()
    if not readiness["auto_dispatch_active"]:
        return {
            "status": "skipped",
            "step": "4F",
            "reason": "automatic_customer_dispatch_inactive",
            "email_queues_created": 0,
        }

    remaining_daily = max(
        0,
        cint(settings.daily_customer_dispatch_limit)
        - _dispatches_today(DELIVERY_MODE_CUSTOMER),
    )
    requested = cint(limit or settings.max_batch_size or 20)
    batch_limit = max(
        0,
        min(requested, cint(settings.max_batch_size), remaining_daily, 100),
    )
    if batch_limit <= 0:
        return {
            "status": "ok",
            "step": "4F",
            "eligible_seen": 0,
            "queued": 0,
            "skipped": 0,
            "email_queues_created": 0,
            "reason": "daily_or_batch_limit_reached",
        }

    cutover = _customer_cutover(settings)
    names = frappe.get_all(
        NOTIFICATION_DOCTYPE,
        filters={
            "notification_status": ["in", ["Deferred", "Failed"]],
            "channel": "Email",
            "is_transactional": 1,
            "created_at": [">=", cutover],
        },
        pluck="name",
        order_by="event_at asc, creation asc",
        limit_page_length=min(max(batch_limit * 5, batch_limit), 500),
    )

    results: list[dict[str, Any]] = []
    queued = 0
    skipped = 0
    for name in names:
        if queued >= batch_limit:
            break
        notification = frappe.get_doc(NOTIFICATION_DOCTYPE, name)
        eligibility = _customer_dispatch_eligibility(notification, settings)
        if not eligibility["eligible"]:
            skipped += 1
            results.append(
                {
                    "notification": name,
                    "status": "skipped",
                    "reasons": eligibility["reasons"],
                }
            )
            continue
        try:
            result = _queue_customer_notification_internal(
                name,
                actor="Administrator",
                dispatch_source="Customer Automatic",
            )
            results.append(result)
            queued += 1
        except Exception:
            skipped += 1
            frappe.log_error(
                title="Step 4F Automatic Customer Dispatch",
                message=frappe.get_traceback(),
            )
            results.append(
                {
                    "notification": name,
                    "status": "error",
                }
            )

    if queued:
        frappe.db.commit()

    return {
        "status": "ok",
        "step": "4F",
        "eligible_seen": len(names),
        "queued": queued,
        "skipped": skipped,
        "email_queues_created": queued,
        "results": results,
    }
