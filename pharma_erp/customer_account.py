from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, strip_html

from pharma_erp.controlled_cart_checkout import (
    _customer_checkout_identity,
    _website_user_customers,
)
from pharma_erp.customer_order_tracking import (
    _FULFILMENT_LABELS,
    _PAYMENT_STATUS_LABELS,
    _parse_tracking_token,
    _public_status,
    _tracking_order_by_token_id,
    tracking_url_for_order_name,
)
from pharma_erp.controlled_product_listing import _catalog_brand, _format_public_price

ACCOUNT_ROUTE = "/pharmacy-account/"
ACCOUNT_PAGE_SIZE = 20
ACCOUNT_MAX_PAGE_SIZE = 50
ACCOUNT_RATE_LIMIT_PER_MINUTE = 120
ACCOUNT_MUTATION_RATE_LIMIT_PER_MINUTE = 30
GUEST_ORDER_CLAIM_RATE_LIMIT_PER_MINUTE = 8

_ALLOWED_ADDRESS_TYPES = {"Shipping", "Office", "Personal", "Other"}
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_MOBILE_SUFFIX_PATTERN = re.compile(r"^[0-9]{4}$")

_ACCOUNT_RESPONSE_HEADERS = {
    "Cache-Control": "private, no-store, no-cache, max-age=0, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
    "Referrer-Policy": "no-referrer",
    "Vary": "Cookie",
}


def _clean_text(value: Any, limit: int = 180) -> str:
    return " ".join(strip_html(str(value or "")).split())[:limit]


def _normalise_mobile(value: Any) -> str:
    raw = str(value or "").strip()
    prefix = "+" if raw.startswith("+") else ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 8 or len(digits) > 16:
        frappe.throw(_("Enter a valid mobile number."))
    return prefix + digits


def _parse_payload(payload: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        frappe.throw(_("Invalid account request."))
    if not isinstance(parsed, dict):
        frappe.throw(_("Invalid account request."))
    return parsed


def _guest_claim_error() -> None:
    frappe.throw(
        _("Unable to link this order. Check the order number, tracking link, and the last four mobile digits."),
        frappe.ValidationError,
    )


def _extract_tracking_token(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 1200:
        _guest_claim_error()

    token = raw
    if not raw.startswith("TRK"):
        try:
            query = parse_qs(urlparse(raw).query, keep_blank_values=False)
            token = str((query.get("token") or [""])[0] or "")
        except (TypeError, ValueError):
            _guest_claim_error()
    token = unquote(token).strip()
    if not token:
        _guest_claim_error()
    return token


def _normalise_mobile_suffix(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not _MOBILE_SUFFIX_PATTERN.fullmatch(digits):
        _guest_claim_error()
    return digits


def _require_website_user() -> str:
    user = str(frappe.session.user or "Guest").strip()
    if not user or user == "Guest":
        frappe.throw(_("Please sign in to access your customer account."), frappe.PermissionError)

    values = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True) or {}
    if not cint(values.get("enabled")) or values.get("user_type") != "Website User":
        frappe.throw(_("This page is available only for customer website accounts."), frappe.PermissionError)
    return user


def _request_ip_hash() -> str:
    request = getattr(frappe.local, "request", None)
    remote = ""
    if request:
        forwarded = str(request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        remote = forwarded or str(getattr(request, "remote_addr", "") or "")
    key = str((getattr(frappe.local, "conf", None) or {}).get("encryption_key") or "")
    return hashlib.sha256(f"{key}|{remote}".encode("utf-8")).hexdigest()[:20]


def _enforce_account_rate_limit(action: str, limit: int) -> None:
    user = str(frappe.session.user or "Guest")
    bucket = now_datetime().strftime("%Y%m%d%H%M")
    cache_key = f"pharma_customer_account:{action}:{user}:{_request_ip_hash()}:{bucket}"
    try:
        cache = getattr(frappe, "cache", None)
        if callable(cache):
            cache = cache()
        if not cache:
            return
        current = cint(cache.incr(cache_key))
        if current == 1:
            cache.expire(cache_key, 75)
        if current > limit:
            if getattr(frappe.local, "response", None) is not None:
                frappe.local.response["http_status_code"] = 429
            frappe.throw(
                _("Too many requests. Please wait a minute and try again."),
                frappe.ValidationError,
            )
    except frappe.ValidationError:
        raise
    except Exception:
        return


def _set_no_store_headers() -> None:
    """Mark the current request for the real after_request response hook."""
    frappe.flags.customer_account_no_store = True


def apply_customer_account_response_headers(response=None, request=None) -> None:
    if response is None or request is None:
        return
    path = str(getattr(request, "path", "") or "").rstrip("/")
    account_page = ACCOUNT_ROUTE.rstrip("/")
    api_prefix = "/api/method/pharma_erp.customer_account."
    marked = bool(getattr(frappe.flags, "customer_account_no_store", False))
    if path != account_page and not path.startswith(api_prefix) and not marked:
        return
    for key, value in _ACCOUNT_RESPONSE_HEADERS.items():
        response.headers[key] = value


def _website_users_for_customer(customer: str) -> list[str]:
    users: set[str] = set()
    if frappe.db.exists("DocType", "Portal User"):
        users.update(
            str(user)
            for user in frappe.get_all(
                "Portal User",
                filters={"parenttype": "Customer", "parent": customer},
                pluck="user",
            )
            if user
        )

    contact_names = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "link_doctype": "Customer",
            "link_name": customer,
        },
        pluck="parent",
    )
    if contact_names:
        users.update(
            str(user)
            for user in frappe.get_all(
                "Contact",
                filters={"name": ["in", list(dict.fromkeys(contact_names))]},
                pluck="user",
            )
            if user
        )

    if not users:
        return []
    return sorted(
        str(name)
        for name in frappe.get_all(
            "User",
            filters={
                "name": ["in", sorted(users)],
                "enabled": 1,
                "user_type": "Website User",
            },
            pluck="name",
        )
    )


def _assert_exclusive_customer_user(customer: str, user: str) -> None:
    linked_users = _website_users_for_customer(customer)
    other_users = [linked for linked in linked_users if linked != user]
    if other_users:
        frappe.throw(
            _("This Customer record is shared with another website account. Please contact the pharmacy."),
            frappe.PermissionError,
        )


def _customer_for_user(user: str, *, allow_unlinked: bool = False) -> str:
    customers = _website_user_customers(user)
    if len(customers) > 1:
        frappe.throw(
            _("Your website account is linked to more than one Customer record. Please contact the pharmacy."),
            frappe.ValidationError,
        )
    if not customers:
        if allow_unlinked:
            return ""
        frappe.throw(_("Complete your customer profile first."), frappe.DoesNotExistError)
    customer = customers[0]
    _assert_exclusive_customer_user(customer, user)
    return customer


def _selling_defaults() -> tuple[str, str]:
    customer_group = frappe.db.get_single_value("Selling Settings", "customer_group")
    territory = frappe.db.get_single_value("Selling Settings", "territory")

    if not customer_group:
        customer_group = frappe.db.get_value(
            "Customer Group", {"is_group": 0}, "name", order_by="lft asc"
        )
    if not territory:
        territory = frappe.db.get_value(
            "Territory", {"is_group": 0}, "name", order_by="lft asc"
        ) or frappe.db.get_value("Territory", {}, "name", order_by="lft asc")

    if not customer_group or not territory:
        frappe.throw(
            _("Customer account setup requires a default Customer Group and Territory in Selling Settings."),
            frappe.ValidationError,
        )
    return str(customer_group), str(territory)


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in full_name.split() if part]
    first_name = parts[0] if parts else full_name
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    return first_name, last_name


def _contact_for_user(user: str) -> str:
    contact = frappe.db.get_value("Contact", {"user": user}, "name")
    return str(contact or "")


def _ensure_contact_link(user: str, customer: str, full_name: str, mobile_no: str) -> str:
    first_name, last_name = _split_name(full_name)
    contact_name = _contact_for_user(user)

    if contact_name:
        contact = frappe.get_doc("Contact", contact_name)
    else:
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": first_name,
                "last_name": last_name,
                "user": user,
                "is_primary_contact": 1,
            }
        )

    contact.first_name = first_name
    contact.last_name = last_name
    contact.user = user
    contact.is_primary_contact = 1

    if not any(str(row.email_id or "").lower() == user.lower() for row in contact.get("email_ids") or []):
        contact.append("email_ids", {"email_id": user, "is_primary": 1})
    for row in contact.get("email_ids") or []:
        row.is_primary = cint(str(row.email_id or "").lower() == user.lower())

    if mobile_no:
        matched_phone = False
        for row in contact.get("phone_nos") or []:
            if str(row.phone or "") == mobile_no:
                row.is_primary_mobile_no = 1
                matched_phone = True
            elif row.is_primary_mobile_no:
                row.is_primary_mobile_no = 0
        if not matched_phone:
            contact.append("phone_nos", {"phone": mobile_no, "is_primary_mobile_no": 1})

    if not any(
        row.link_doctype == "Customer" and row.link_name == customer
        for row in contact.get("links") or []
    ):
        contact.append("links", {"link_doctype": "Customer", "link_name": customer})

    if contact.is_new():
        contact.insert(ignore_permissions=True)
    else:
        contact.save(ignore_permissions=True)

    frappe.db.set_value(
        "Customer",
        customer,
        {
            "customer_primary_contact": contact.name,
            "mobile_no": mobile_no,
            "email_id": user,
        },
        update_modified=False,
    )
    return contact.name


def _ensure_portal_user(customer: str, user: str) -> None:
    if frappe.db.exists(
        "Portal User",
        {"parenttype": "Customer", "parent": customer, "user": user},
    ):
        return
    customer_doc = frappe.get_doc("Customer", customer)
    customer_doc.append("portal_users", {"user": user})
    customer_doc.save(ignore_permissions=True)


def _address_names(customer: str, *, include_disabled: bool = False) -> list[str]:
    linked = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Address",
            "link_doctype": "Customer",
            "link_name": customer,
        },
        pluck="parent",
    )
    names = list(dict.fromkeys(str(name) for name in linked if name))
    if not names or include_disabled:
        return names
    return frappe.get_all(
        "Address",
        filters={"name": ["in", names], "disabled": 0},
        pluck="name",
        order_by="is_shipping_address desc, modified desc",
    )


def _address_customer_links(address_name: str) -> list[str]:
    return list(
        dict.fromkeys(
            str(name)
            for name in frappe.get_all(
                "Dynamic Link",
                filters={
                    "parenttype": "Address",
                    "parent": address_name,
                    "link_doctype": "Customer",
                },
                pluck="link_name",
            )
            if name
        )
    )


def _owned_address(customer: str, address_name: str, *, allow_disabled: bool = False):
    address_name = _clean_text(address_name, 140)
    if not address_name:
        frappe.throw(_("Select a saved address."))
    links = _address_customer_links(address_name)
    if customer not in links or any(link != customer for link in links):
        frappe.throw(_("This address does not belong exclusively to your customer account."), frappe.PermissionError)
    address = frappe.get_doc("Address", address_name)
    if cint(address.disabled) and not allow_disabled:
        frappe.throw(_("This address is archived."))
    return address


def _default_country() -> str:
    country = frappe.defaults.get_global_default("country") or "Egypt"
    if country and frappe.db.exists("Country", country):
        return str(country)
    return str(frappe.db.get_value("Country", {}, "name", order_by="name asc") or "")


def _address_payload(address) -> dict[str, Any]:
    return {
        "name": address.name,
        "address_title": address.address_title or address.name,
        "address_type": address.address_type or "Shipping",
        "address_line1": address.address_line1 or "",
        "address_line2": address.address_line2 or "",
        "city": address.city or "",
        "state": address.state or "",
        "pincode": address.pincode or "",
        "country": address.country or "",
        "phone": address.phone or "",
        "is_default": cint(address.is_shipping_address),
        "label": " — ".join(
            part
            for part in (
                address.address_title or address.name,
                address.address_line1,
                address.city,
            )
            if part
        ),
    }


def _list_addresses(customer: str) -> list[dict[str, Any]]:
    names = _address_names(customer)
    if not names:
        return []
    docs = [frappe.get_doc("Address", name) for name in names]
    return [_address_payload(doc) for doc in docs]


def _set_default_address(customer: str, address_name: str) -> None:
    selected = _owned_address(customer, address_name)
    names = _address_names(customer)
    for name in names:
        frappe.db.set_value(
            "Address", name, "is_shipping_address", cint(name == selected.name), update_modified=False
        )


def _my_orders(user: str, customer: str, start: int, page_length: int) -> dict[str, Any]:
    start = max(0, cint(start))
    page_length = max(1, min(cint(page_length) or ACCOUNT_PAGE_SIZE, ACCOUNT_MAX_PAGE_SIZE))
    meta = frappe.get_meta("Online Order")
    has_website_user = meta.has_field("custom_website_user")

    ownership_parts = []
    ownership_values: list[Any] = []
    if has_website_user:
        ownership_parts.append("oo.custom_website_user = %s")
        ownership_values.append(user)
    if customer:
        ownership_parts.append("oo.customer = %s")
        ownership_values.append(customer)
    if not ownership_parts:
        return {"orders": [], "has_more": 0, "next_start": start}

    rows = frappe.db.sql(
        f"""
        SELECT
            oo.name,
            oo.status,
            oo.fulfilment_method,
            oo.grand_total,
            oo.currency,
            oo.payment_status,
            oo.placed_at,
            oo.creation
        FROM `tabOnline Order` oo
        WHERE oo.docstatus < 2
          AND oo.source_channel = 'Website'
          AND ({' OR '.join(ownership_parts)})
        ORDER BY COALESCE(oo.placed_at, oo.creation) DESC, oo.creation DESC
        LIMIT %s OFFSET %s
        """,
        tuple(ownership_values + [page_length + 1, start]),
        as_dict=True,
    )
    has_more = cint(len(rows) > page_length)
    rows = rows[:page_length]
    names = [row.name for row in rows]
    item_counts: dict[str, int] = {}
    if names:
        count_rows = frappe.get_all(
            "Online Order Item",
            filters={"parenttype": "Online Order", "parent": ["in", names]},
            fields=["parent", "count(name) as item_count"],
            group_by="parent",
        )
        item_counts = {str(row.parent): cint(row.item_count) for row in count_rows}

    brand = _catalog_brand()
    orders = []
    for row in rows:
        status = _public_status(row.status or "")
        currency = row.currency or brand.get("currency") or "EGP"
        orders.append(
            {
                "online_order": row.name,
                "placed_at": row.placed_at or row.creation,
                "status_label_ar": status.get("label_ar") or "قيد المراجعة",
                "status_key": status.get("key") or "review",
                "fulfilment_method": row.fulfilment_method or "",
                "fulfilment_label_ar": _FULFILMENT_LABELS.get(
                    row.fulfilment_method, "طريقة الاستلام"
                ),
                "payment_status_label_ar": _PAYMENT_STATUS_LABELS.get(
                    row.payment_status, "حالة الدفع قيد المراجعة"
                ),
                "grand_total": flt(row.grand_total),
                "grand_total_formatted": _format_public_price(flt(row.grand_total), currency),
                "currency": currency,
                "item_count": item_counts.get(row.name, 0),
                "tracking_url": tracking_url_for_order_name(row.name),
            }
        )
    return {
        "orders": orders,
        "has_more": has_more,
        "next_start": start + len(orders),
    }


@frappe.whitelist()
def get_customer_account(start: int = 0, page_length: int = ACCOUNT_PAGE_SIZE) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_website_user()
    _enforce_account_rate_limit("read", ACCOUNT_RATE_LIMIT_PER_MINUTE)
    customer = _customer_for_user(user, allow_unlinked=True)
    user_values = frappe.db.get_value(
        "User", user, ["name", "full_name", "first_name", "last_name", "mobile_no"], as_dict=True
    ) or {}
    orders = _my_orders(user, customer, start, page_length)

    if not customer:
        return {
            "authenticated": 1,
            "website_user": user,
            "customer_linked": 0,
            "profile": {
                "email": user,
                "full_name": user_values.get("full_name") or user_values.get("first_name") or "",
                "mobile_no": user_values.get("mobile_no") or "",
            },
            "addresses": [],
            **orders,
        }

    identity = _customer_checkout_identity(customer)
    return {
        "authenticated": 1,
        "website_user": user,
        "customer_linked": 1,
        "customer": customer,
        "customer_code": identity.get("customer_code") or customer,
        "profile": {
            "email": user,
            "full_name": user_values.get("full_name") or identity.get("customer_name") or customer,
            "mobile_no": identity.get("mobile_no") or user_values.get("mobile_no") or "",
        },
        "addresses": _list_addresses(customer),
        **orders,
    }


@frappe.whitelist(methods=["POST"])
def activate_customer_account(payload: str | dict[str, Any] | None = None) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_website_user()
    _enforce_account_rate_limit("activate", ACCOUNT_MUTATION_RATE_LIMIT_PER_MINUTE)
    data = _parse_payload(payload)
    full_name = _clean_text(data.get("full_name"), 140)
    mobile_no = _normalise_mobile(data.get("mobile_no"))
    if len(full_name) < 2:
        frappe.throw(_("Enter your full name."))
    if not _EMAIL_PATTERN.fullmatch(user):
        frappe.throw(_("The website account email is invalid."))

    existing = _customer_for_user(user, allow_unlinked=True)
    if existing:
        _ensure_portal_user(existing, user)
        _ensure_contact_link(user, existing, full_name, mobile_no)
        return get_customer_account()

    customer_group, territory = _selling_defaults()
    customer_doc = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": full_name,
            "customer_type": "Individual",
            "customer_group": customer_group,
            "territory": territory,
            "portal_users": [{"user": user}],
        }
    )
    customer_doc.insert(ignore_permissions=True)
    _ensure_contact_link(user, customer_doc.name, full_name, mobile_no)

    first_name, last_name = _split_name(full_name)
    frappe.db.set_value(
        "User",
        user,
        {"first_name": first_name, "last_name": last_name, "mobile_no": mobile_no},
        update_modified=True,
    )
    return get_customer_account()


@frappe.whitelist(methods=["POST"])
def claim_guest_order(payload: str | dict[str, Any] | None = None) -> dict[str, Any]:
    """Link one guest website order after secure ownership proof.

    Proof requires all three values: exact order number, the valid HMAC tracking
    token (or full tracking URL), and the last four digits of the order mobile.
    The endpoint never auto-matches by email/mobile and never changes Customer,
    invoices, payments, ledger entries, or stock.
    """
    _set_no_store_headers()
    user = _require_website_user()
    _enforce_account_rate_limit(
        "guest-order-claim", GUEST_ORDER_CLAIM_RATE_LIMIT_PER_MINUTE
    )
    customer = _customer_for_user(user)
    data = _parse_payload(payload)

    order_name = _clean_text(data.get("online_order"), 140)
    mobile_suffix = _normalise_mobile_suffix(data.get("mobile_last4"))
    tracking_token = _extract_tracking_token(data.get("tracking_token"))
    if not order_name:
        _guest_claim_error()

    try:
        version, token_id = _parse_tracking_token(tracking_token)
    except Exception:
        _guest_claim_error()
        return {}

    tracked_order = _tracking_order_by_token_id(token_id)
    if (
        not tracked_order
        or str(tracked_order.get("name") or "") != order_name
        or cint(tracked_order.get("docstatus")) >= 2
        or not cint(tracked_order.get("custom_tracking_enabled"))
        or tracked_order.get("custom_tracking_revoked_at")
        or cint(tracked_order.get("custom_tracking_token_version")) != version
    ):
        _guest_claim_error()

    fields = [
        "name",
        "docstatus",
        "source_channel",
        "customer",
        "mobile_no",
        "custom_website_user",
        "custom_guest_claimed_at",
        "custom_guest_claimed_by",
        "custom_guest_claim_method",
    ]
    order = frappe.db.get_value("Online Order", order_name, fields, as_dict=True) or {}
    order_mobile = re.sub(r"\D", "", str(order.get("mobile_no") or ""))
    if (
        not order
        or cint(order.get("docstatus")) >= 2
        or order.get("source_channel") != "Website"
        or len(order_mobile) < 4
        or order_mobile[-4:] != mobile_suffix
    ):
        _guest_claim_error()

    existing_user = str(order.get("custom_website_user") or "").strip()
    if existing_user and existing_user != user:
        _guest_claim_error()

    order_customer = str(order.get("customer") or "").strip()
    if order_customer:
        linked_users = _website_users_for_customer(order_customer)
        if any(linked_user != user for linked_user in linked_users):
            _guest_claim_error()

    status = "already_linked"
    if not existing_user:
        frappe.db.set_value(
            "Online Order",
            order_name,
            {
                "custom_website_user": user,
                "custom_guest_claimed_at": now_datetime(),
                "custom_guest_claimed_by": user,
                "custom_guest_claim_method": "HMAC Tracking Token + Mobile Suffix",
            },
            update_modified=True,
        )
        status = "linked"
        try:
            frappe.logger("customer_account", allow_site=True).info(
                json.dumps(
                    {
                        "event": "guest_order_claimed",
                        "online_order": order_name,
                        "website_user": user,
                        "customer_account": customer,
                        "tracking_token_hint": token_id[-6:],
                        "at": str(now_datetime()),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        except Exception:
            pass

    result = get_customer_account()
    result["guest_order_claim"] = {
        "status": status,
        "online_order": order_name,
        "verification": "tracking_token_and_mobile_suffix",
    }
    return result


@frappe.whitelist(methods=["POST"])
def update_customer_profile(payload: str | dict[str, Any] | None = None) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_website_user()
    _enforce_account_rate_limit("profile", ACCOUNT_MUTATION_RATE_LIMIT_PER_MINUTE)
    customer = _customer_for_user(user)
    data = _parse_payload(payload)
    full_name = _clean_text(data.get("full_name"), 140)
    mobile_no = _normalise_mobile(data.get("mobile_no"))
    if len(full_name) < 2:
        frappe.throw(_("Enter your full name."))

    first_name, last_name = _split_name(full_name)
    frappe.db.set_value(
        "User",
        user,
        {"first_name": first_name, "last_name": last_name, "mobile_no": mobile_no},
        update_modified=True,
    )
    _ensure_portal_user(customer, user)
    _ensure_contact_link(user, customer, full_name, mobile_no)
    return get_customer_account()


@frappe.whitelist(methods=["POST"])
def save_customer_address(payload: str | dict[str, Any] | None = None) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_website_user()
    _enforce_account_rate_limit("address-save", ACCOUNT_MUTATION_RATE_LIMIT_PER_MINUTE)
    customer = _customer_for_user(user)
    data = _parse_payload(payload)

    address_name = _clean_text(data.get("name"), 140)
    address_title = _clean_text(data.get("address_title"), 80)
    address_type = _clean_text(data.get("address_type") or "Shipping", 40)
    address_line1 = _clean_text(data.get("address_line1"), 180)
    address_line2 = _clean_text(data.get("address_line2"), 180)
    city = _clean_text(data.get("city"), 120)
    state = _clean_text(data.get("state"), 120)
    pincode = _clean_text(data.get("pincode"), 20)
    country = _clean_text(data.get("country") or _default_country(), 120)
    phone = _normalise_mobile(data.get("phone")) if data.get("phone") else ""
    make_default = cint(data.get("make_default"))

    if not address_title:
        address_title = f"{frappe.db.get_value('Customer', customer, 'customer_name') or customer} - Address"
    if address_type not in _ALLOWED_ADDRESS_TYPES:
        frappe.throw(_("Select a valid address type."))
    if not address_line1 or not city or not country:
        frappe.throw(_("Address line, city, and country are required."))
    if not frappe.db.exists("Country", country):
        frappe.throw(_("Select a valid country."))

    if address_name:
        address = _owned_address(customer, address_name)
    else:
        address = frappe.get_doc(
            {
                "doctype": "Address",
                "links": [{"link_doctype": "Customer", "link_name": customer}],
            }
        )

    address.address_title = address_title
    address.address_type = address_type
    address.address_line1 = address_line1
    address.address_line2 = address_line2
    address.city = city
    address.state = state
    address.pincode = pincode
    address.country = country
    address.phone = phone
    address.disabled = 0

    existing_active = _address_names(customer)
    if address.is_new():
        address.is_shipping_address = cint(make_default or not existing_active)
        address.insert(ignore_permissions=True)
    else:
        address.save(ignore_permissions=True)

    if make_default or not existing_active:
        _set_default_address(customer, address.name)

    return get_customer_account()


@frappe.whitelist(methods=["POST"])
def set_default_customer_address(address_name: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_website_user()
    _enforce_account_rate_limit("address-default", ACCOUNT_MUTATION_RATE_LIMIT_PER_MINUTE)
    customer = _customer_for_user(user)
    _set_default_address(customer, address_name)
    return get_customer_account()


@frappe.whitelist(methods=["POST"])
def archive_customer_address(address_name: str) -> dict[str, Any]:
    _set_no_store_headers()
    user = _require_website_user()
    _enforce_account_rate_limit("address-archive", ACCOUNT_MUTATION_RATE_LIMIT_PER_MINUTE)
    customer = _customer_for_user(user)
    address = _owned_address(customer, address_name)
    was_default = cint(address.is_shipping_address)
    address.disabled = 1
    address.is_shipping_address = 0
    address.save(ignore_permissions=True)

    if was_default:
        remaining = _address_names(customer)
        if remaining:
            _set_default_address(customer, remaining[0])
    return get_customer_account()


def _outgoing_email_account() -> str:
    filters: dict[str, Any] = {"default_outgoing": 1}
    if frappe.get_meta("Email Account").has_field("awaiting_password"):
        filters["awaiting_password"] = 0
    return str(frappe.db.get_value("Email Account", filters, "name") or "")


def account_readiness() -> dict[str, Any]:
    """Read-only readiness summary used by the installer and verifier."""
    required = (
        "Customer",
        "Contact",
        "Address",
        "Online Order",
        "Online Order Item",
        "Portal User",
    )
    missing = [doctype for doctype in required if not frappe.db.exists("DocType", doctype)]
    online_meta = frappe.get_meta("Online Order") if not missing else None
    defaults = {
        "customer_group": frappe.db.get_single_value("Selling Settings", "customer_group"),
        "territory": frappe.db.get_single_value("Selling Settings", "territory"),
    }
    return {
        "status": "ok" if not missing else "missing_requirements",
        "step": "4A.2",
        "account_route": ACCOUNT_ROUTE,
        "missing_doctypes": missing,
        "online_order_website_user_field": cint(
            bool(online_meta and online_meta.has_field("custom_website_user"))
        ),
        "website_users": frappe.db.count("User", {"enabled": 1, "user_type": "Website User"}),
        "active_saved_addresses": frappe.db.count("Address", {"disabled": 0}),
        "signup_disabled": cint(frappe.get_website_settings("disable_signup")),
        "outgoing_email_configured": cint(bool(_outgoing_email_account())),
        "selling_defaults": defaults,
        "uses_standard_frappe_login": 1,
        "uses_standard_frappe_signup": 1,
        "uses_standard_frappe_password_reset": 1,
        "guest_account_data_access": 0,
        "exclusive_customer_account_guard": 1,
        "address_owner_validation": 1,
        "my_orders_owner_filter": 1,
        "guest_order_secure_claim": 1,
        "guest_order_auto_claim": 0,
        "guest_order_claim_requires_tracking_token": 1,
        "guest_order_claim_requires_mobile_suffix": 1,
        "guest_order_claim_changes_customer": 0,
        "creates_sales_invoice": 0,
        "creates_payment_entry": 0,
        "creates_gl_entries": 0,
        "creates_stock_entries": 0,
        "core_changes": 0,
    }
