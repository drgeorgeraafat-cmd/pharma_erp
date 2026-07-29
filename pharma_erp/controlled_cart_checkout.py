from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, now_datetime, strip_html

from pharma_erp.controlled_product_listing import _catalog_brand, _format_public_price

MAX_CART_LINES = 25
MAX_LINE_QTY = 99
MAX_TOTAL_QTY = 200
ALLOWED_FULFILMENT_METHODS = {"Home Delivery", "Pharmacy Pickup"}
CHECKOUT_TOKEN_PATTERN = re.compile(r"^WEB-[A-Za-z0-9_-]{16,96}$")


@dataclass(frozen=True)
class RequestedLine:
    item_code: str
    qty: float


def _clean_text(value: Any, limit: int) -> str:
    text = " ".join(strip_html(str(value or "")).split())
    return text[:limit]


def _payload_dict(payload: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError):
        frappe.throw(_("Invalid checkout payload."))
    if not isinstance(parsed, dict):
        frappe.throw(_("Invalid checkout payload."))
    return parsed


def _items_value(items: str | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if isinstance(items, list):
        return items
    if not items:
        return []
    try:
        parsed = json.loads(items)
    except (TypeError, ValueError):
        frappe.throw(_("Invalid cart data."))
    if not isinstance(parsed, list):
        frappe.throw(_("Invalid cart data."))
    return parsed


def _normalise_requested_lines(items: str | list[dict[str, Any]] | None) -> list[RequestedLine]:
    raw_items = _items_value(items)
    if not raw_items:
        frappe.throw(_("Your cart is empty."))
    if len(raw_items) > MAX_CART_LINES:
        frappe.throw(_("The cart cannot contain more than {0} products.").format(MAX_CART_LINES))

    merged: dict[str, float] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            frappe.throw(_("Invalid cart row."))
        item_code = _clean_text(raw.get("item_code"), 140)
        qty = flt(raw.get("qty"))
        if not item_code:
            frappe.throw(_("Every cart row must include an item code."))
        if qty <= 0 or qty > MAX_LINE_QTY:
            frappe.throw(
                _("Quantity for item {0} must be between 1 and {1}.").format(
                    frappe.bold(item_code), MAX_LINE_QTY
                )
            )
        if abs(qty - round(qty)) > 0.000001:
            frappe.throw(_("Online cart quantities must be whole numbers."))
        merged[item_code] = merged.get(item_code, 0) + round(qty)
        if merged[item_code] > MAX_LINE_QTY:
            frappe.throw(
                _("Quantity for item {0} cannot exceed {1}.").format(
                    frappe.bold(item_code), MAX_LINE_QTY
                )
            )

    if sum(merged.values()) > MAX_TOTAL_QTY:
        frappe.throw(_("The total cart quantity cannot exceed {0}.").format(MAX_TOTAL_QTY))

    return [RequestedLine(item_code=code, qty=qty) for code, qty in merged.items()]


def _orderable_rows(item_codes: list[str]) -> dict[str, dict[str, Any]]:
    placeholders = ", ".join(["%s"] * len(item_codes))
    rows = frappe.db.sql(
        f"""
        SELECT
            wi.name AS website_item,
            wi.item_code,
            wi.web_item_name,
            wi.website_image,
            wi.custom_online_category,
            COALESCE(wi.custom_requires_prescription, 0) AS requires_prescription,
            wi.custom_online_availability_status,
            wi.custom_online_description_ar,
            wi.custom_online_description_en,
            i.item_name,
            i.stock_uom,
            COALESCE(i.custom_customer_price, 0) AS customer_price
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON i.name = wi.item_code
        WHERE wi.item_code IN ({placeholders})
          AND wi.published = 1
          AND COALESCE(wi.custom_pharma_managed, 0) = 1
          AND COALESCE(i.custom_show_online, 0) = 1
          AND COALESCE(i.published_in_website, 0) = 1
          AND COALESCE(i.disabled, 0) = 0
          AND wi.custom_online_availability_status = 'Available'
          AND wi.custom_pharma_readiness_status IN ('Ready', 'Warning')
          AND COALESCE(i.custom_customer_price, 0) > 0
        """,
        tuple(item_codes),
        as_dict=True,
    )
    return {str(row.get("item_code")): row for row in rows}


def _validated_cart(items: str | list[dict[str, Any]] | None) -> dict[str, Any]:
    requested = _normalise_requested_lines(items)
    rows = _orderable_rows([line.item_code for line in requested])
    brand = _catalog_brand()
    currency = brand["currency"]
    validated_items: list[dict[str, Any]] = []
    products_subtotal = 0.0
    prescription_required = False

    for line in requested:
        row = rows.get(line.item_code)
        if not row:
            frappe.throw(
                _("Item {0} is no longer published, available, or orderable online.").format(
                    frappe.bold(line.item_code)
                )
            )

        rate = flt(row.get("customer_price"))
        amount = rate * line.qty
        products_subtotal += amount
        requires_prescription = cint(row.get("requires_prescription"))
        prescription_required = prescription_required or bool(requires_prescription)
        description = (
            row.get("custom_online_description_ar")
            or row.get("custom_online_description_en")
            or ""
        )

        validated_items.append(
            {
                "website_item": row.get("website_item"),
                "item_code": line.item_code,
                "item_name": row.get("web_item_name") or row.get("item_name") or line.item_code,
                "image": row.get("website_image") or "",
                "category": row.get("custom_online_category") or "",
                "description": " ".join(strip_html(description).split())[:220],
                "uom": row.get("stock_uom") or "",
                "qty": line.qty,
                "rate": rate,
                "rate_formatted": _format_public_price(rate, currency),
                "amount": amount,
                "amount_formatted": _format_public_price(amount, currency),
                "requires_prescription": requires_prescription,
                "availability": "Available",
                "availability_label_ar": "متاح",
            }
        )

    return {
        "items": validated_items,
        "line_count": len(validated_items),
        "total_qty": sum(line.qty for line in requested),
        "products_subtotal": products_subtotal,
        "products_subtotal_formatted": _format_public_price(products_subtotal, currency),
        "delivery_fee": 0.0,
        "delivery_fee_formatted": _format_public_price(0, currency),
        "grand_total": products_subtotal,
        "grand_total_formatted": _format_public_price(products_subtotal, currency),
        "currency": currency,
        "brand": brand,
        "prescription_required": cint(prescription_required),
        "delivery_fee_pending_review": 1,
        "controlled_cart": 1,
        "creates_quotation": 0,
        "creates_sales_order": 0,
        "creates_financial_entries": 0,
        "creates_stock_entries": 0,
    }


def _normalise_mobile(value: Any) -> str:
    raw = str(value or "").strip()
    prefix = "+" if raw.startswith("+") else ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 8 or len(digits) > 16:
        frappe.throw(_("Enter a valid mobile number."))
    return prefix + digits


def _checkout_token(value: Any) -> str:
    token = _clean_text(value, 100)
    if not token:
        token = "WEB-" + uuid.uuid4().hex
    if not CHECKOUT_TOKEN_PATTERN.fullmatch(token):
        frappe.throw(_("Invalid checkout token."))
    return token


def _safe_order_receipt(order_name: str, checkout_token: str) -> dict[str, Any]:
    row = frappe.db.get_value(
        "Online Order",
        {
            "name": order_name,
            "source_channel": "Website",
            "external_reference": checkout_token,
            "docstatus": ["<", 2],
        },
        [
            "name",
            "status",
            "customer_name",
            "mobile_no",
            "fulfilment_method",
            "products_subtotal",
            "delivery_fee",
            "grand_total",
            "currency",
            "prescription_required",
            "prescription_review_status",
            "payment_timing",
            "payment_method",
            "payment_status",
            "placed_at",
        ],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Online order receipt was not found."), frappe.DoesNotExistError)

    items = frappe.get_all(
        "Online Order Item",
        filters={"parent": order_name, "parenttype": "Online Order"},
        fields=[
            "item_code",
            "item_name_snapshot",
            "requested_qty",
            "listed_rate",
            "net_amount",
            "requires_prescription_snapshot",
        ],
        order_by="idx asc",
    )
    currency = row.get("currency") or "EGP"
    return {
        "online_order": row.get("name"),
        "status": row.get("status"),
        "customer_name": row.get("customer_name"),
        "mobile_no_masked": _mask_mobile(row.get("mobile_no")),
        "fulfilment_method": row.get("fulfilment_method"),
        "products_subtotal": flt(row.get("products_subtotal")),
        "products_subtotal_formatted": _format_public_price(
            flt(row.get("products_subtotal")), currency
        ),
        "delivery_fee": flt(row.get("delivery_fee")),
        "delivery_fee_formatted": _format_public_price(flt(row.get("delivery_fee")), currency),
        "grand_total": flt(row.get("grand_total")),
        "grand_total_formatted": _format_public_price(flt(row.get("grand_total")), currency),
        "currency": currency,
        "prescription_required": cint(row.get("prescription_required")),
        "prescription_review_status": row.get("prescription_review_status"),
        "payment_timing": row.get("payment_timing"),
        "payment_method": row.get("payment_method"),
        "payment_status": row.get("payment_status"),
        "placed_at": row.get("placed_at"),
        "items": [
            {
                "item_code": item.get("item_code"),
                "item_name": item.get("item_name_snapshot") or item.get("item_code"),
                "qty": flt(item.get("requested_qty")),
                "rate": flt(item.get("listed_rate")),
                "rate_formatted": _format_public_price(flt(item.get("listed_rate")), currency),
                "amount": flt(item.get("net_amount")),
                "amount_formatted": _format_public_price(flt(item.get("net_amount")), currency),
                "requires_prescription": cint(item.get("requires_prescription_snapshot")),
            }
            for item in items
        ],
        "delivery_fee_pending_review": cint(row.get("fulfilment_method") == "Home Delivery"),
        "review_required": 1,
        "sales_invoice_created": 0,
        "sales_order_created": 0,
        "quotation_created": 0,
    }


def _mask_mobile(value: Any) -> str:
    mobile = str(value or "")
    if len(mobile) <= 4:
        return mobile
    return "*" * max(0, len(mobile) - 4) + mobile[-4:]




def _website_user_customers(website_user: str) -> list[str]:
    user = str(website_user or "").strip()
    if not user or user == "Guest":
        return []
    customers: set[str] = set()
    if frappe.db.exists("DocType", "Portal User"):
        for customer in frappe.get_all(
            "Portal User",
            filters={"parenttype": "Customer", "user": user},
            pluck="parent",
        ):
            customers.add(str(customer))
    contact_names = frappe.get_all("Contact", filters={"user": user}, pluck="name")
    if contact_names:
        for customer in frappe.get_all(
            "Dynamic Link",
            filters={
                "parenttype": "Contact",
                "parent": ["in", contact_names],
                "link_doctype": "Customer",
            },
            pluck="link_name",
        ):
            customers.add(str(customer))
    return sorted(
        customer
        for customer in customers
        if frappe.db.exists("Customer", {"name": customer, "disabled": 0})
    )


def _customer_checkout_identity(customer: str) -> dict[str, Any]:
    values = frappe.db.get_value(
        "Customer",
        customer,
        ["name", "customer_name", "mobile_no", "email_id"],
        as_dict=True,
    ) or {}
    customer_code = customer
    if frappe.get_meta("Customer").has_field("custom_customer_code"):
        customer_code = frappe.db.get_value("Customer", customer, "custom_customer_code") or customer

    contacts = []
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
        contacts = frappe.get_all(
            "Contact",
            filters={"name": ["in", list(dict.fromkeys(contact_names))]},
            fields=["name", "full_name", "email_id", "mobile_no", "phone", "is_primary_contact"],
            order_by="is_primary_contact desc, modified desc",
        )
    primary = contacts[0] if contacts else {}

    address_names = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Address",
            "link_doctype": "Customer",
            "link_name": customer,
        },
        pluck="parent",
    )
    addresses = []
    if address_names:
        addresses = frappe.get_all(
            "Address",
            filters={"name": ["in", list(dict.fromkeys(address_names))], "disabled": 0},
            fields=[
                "name",
                "address_title",
                "address_type",
                "address_line1",
                "address_line2",
                "city",
                "state",
                "country",
                "phone",
                "is_shipping_address",
                "is_primary_address",
                "custom_delivery_zone",
            ],
            order_by="is_shipping_address desc, is_primary_address desc, modified desc",
        )
    for address in addresses:
        address["label"] = " — ".join(
            part
            for part in (
                address.get("address_title") or address.get("name"),
                address.get("address_line1"),
                address.get("city"),
            )
            if part
        )

    return {
        "customer": values.get("name"),
        "customer_code": customer_code,
        "customer_name": values.get("customer_name") or customer,
        "mobile_no": values.get("mobile_no") or primary.get("mobile_no") or primary.get("phone") or "",
        "email_id": values.get("email_id") or primary.get("email_id") or "",
        "addresses": addresses,
    }


def _validate_checkout_address(customer: str, address_name: str) -> dict[str, Any]:
    if not address_name:
        return {}
    linked = frappe.db.exists(
        "Dynamic Link",
        {
            "parenttype": "Address",
            "parent": address_name,
            "link_doctype": "Customer",
            "link_name": customer,
        },
    )
    if not linked:
        frappe.throw(_("The selected saved address is not linked to your Customer account."))
    values = frappe.db.get_value(
        "Address",
        address_name,
        [
            "address_title",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "country",
            "phone",
            "disabled",
        ],
        as_dict=True,
    ) or {}
    if cint(values.get("disabled")):
        frappe.throw(_("The selected saved address is disabled."))
    return values


@frappe.whitelist(allow_guest=True)
def get_checkout_identity() -> dict[str, Any]:
    website_user = frappe.session.user or "Guest"
    if website_user == "Guest":
        return {
            "authenticated": 0,
            "website_user": "",
            "customer_linked": 0,
            "ambiguous_customer_links": 0,
            "customer": {},
            "addresses": [],
        }
    customers = _website_user_customers(website_user)
    if len(customers) != 1:
        return {
            "authenticated": 1,
            "website_user": website_user,
            "customer_linked": 0,
            "ambiguous_customer_links": cint(len(customers) > 1),
            "customer_link_count": len(customers),
            "customer": {},
            "addresses": [],
        }
    identity = _customer_checkout_identity(customers[0])
    return {
        "authenticated": 1,
        "website_user": website_user,
        "customer_linked": 1,
        "ambiguous_customer_links": 0,
        "customer_link_count": 1,
        "customer": {key: value for key, value in identity.items() if key != "addresses"},
        "addresses": identity.get("addresses") or [],
    }


@frappe.whitelist(allow_guest=True)
def validate_cart(items: str | list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Revalidate a browser cart against the controlled published catalog."""
    return _validated_cart(items)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def create_online_order(payload: str | dict[str, Any] | None = None) -> dict[str, Any]:
    """Create one controlled Online Order only.

    This method never creates a Quotation, Sales Order, Sales Invoice, Payment Entry,
    GL Entry, or Stock Ledger Entry. Internal review and the existing Online Order
    workflow remain responsible for customer resolution, stock review, prescription
    review, delivery fee resolution, confirmation, invoicing, and collection.
    """
    data = _payload_dict(payload)
    cart = _validated_cart(data.get("items"))
    checkout_token = _checkout_token(data.get("checkout_token"))
    fulfilment_method = _clean_text(data.get("fulfilment_method"), 40)
    if fulfilment_method not in ALLOWED_FULFILMENT_METHODS:
        frappe.throw(_("Select a valid fulfilment method."))

    customer_name = _clean_text(data.get("customer_name"), 140)
    mobile_no = _normalise_mobile(data.get("mobile_no"))
    email_id = _clean_text(data.get("email_id"), 140)
    if not customer_name:
        frappe.throw(_("Customer name is required."))
    if email_id and ("@" not in email_id or "." not in email_id.split("@")[-1]):
        frappe.throw(_("Enter a valid email address."))

    website_user = frappe.session.user if frappe.session.user != "Guest" else ""
    linked_customers = _website_user_customers(website_user) if website_user else []
    linked_customer = linked_customers[0] if len(linked_customers) == 1 else ""
    selected_address = _clean_text(data.get("customer_address"), 140)
    if selected_address and not linked_customer:
        frappe.throw(_("A saved address requires one linked Customer account."))
    selected_address_values = (
        _validate_checkout_address(linked_customer, selected_address)
        if linked_customer and selected_address
        else {}
    )

    existing_orders = frappe.get_all(
        "Online Order",
        filters={
            "source_channel": "Website",
            "external_reference": checkout_token,
            "docstatus": ["<", 2],
        },
        pluck="name",
        order_by="creation desc",
        limit=1,
    )
    existing_name = existing_orders[0] if existing_orders else None
    if existing_name:
        existing_mobile = frappe.db.get_value("Online Order", existing_name, "mobile_no")
        if str(existing_mobile or "") != mobile_no:
            frappe.throw(_("This checkout token is already in use."))
        receipt = _safe_order_receipt(existing_name, checkout_token)
        receipt["created"] = 0
        receipt["idempotent_replay"] = 1
        receipt["checkout_token"] = checkout_token
        return receipt

    recent_cutoff = add_to_date(now_datetime(), minutes=-15)
    recent_orders = frappe.db.count(
        "Online Order",
        filters={
            "source_channel": "Website",
            "mobile_no": mobile_no,
            "creation": [">=", recent_cutoff],
            "docstatus": ["<", 2],
        },
    )
    if recent_orders >= 5:
        frappe.throw(
            _("Too many recent checkout attempts for this mobile number. Try again later.")
        )

    address_line1 = _clean_text(
        selected_address_values.get("address_line1") or data.get("address_line1"), 180
    )
    address_line2 = _clean_text(
        selected_address_values.get("address_line2") or data.get("address_line2"), 180
    )
    city = _clean_text(selected_address_values.get("city") or data.get("city"), 120)
    state = _clean_text(selected_address_values.get("state") or data.get("state"), 120)
    country = _clean_text(
        selected_address_values.get("country") or data.get("country"), 120
    ) or "Egypt"
    delivery_instructions = _clean_text(data.get("delivery_instructions"), 500)

    if fulfilment_method == "Home Delivery":
        if not address_line1 or not city:
            frappe.throw(_("Address Line 1 and City are required for Home Delivery."))
        if country and not frappe.db.exists("Country", country):
            frappe.throw(_("Country {0} was not found.").format(frappe.bold(country)))

    company = frappe.defaults.get_global_default("company") or frappe.db.get_single_value(
        "Global Defaults", "default_company"
    )
    if not company:
        frappe.throw(_("Default Company is not configured."))

    payment_method = (
        "Cash on Delivery" if fulfilment_method == "Home Delivery" else "Cash at Pharmacy"
    )
    formatted_address = ", ".join(
        value for value in (address_line1, address_line2, city, state, country) if value
    )

    order_data = {
            "doctype": "Online Order",
            "status": "Placed",
            "source_channel": "Website",
            "external_reference": checkout_token,
            "external_created_at": now_datetime(),
            "company": company,
            "order_type": "Retail",
            "fulfilment_method": fulfilment_method,
            "customer_name": customer_name,
            "mobile_no": mobile_no,
            "email_id": email_id,
            "customer_resolution_status": "Unresolved",
            "address_line1": address_line1 if fulfilment_method == "Home Delivery" else "",
            "address_line2": address_line2 if fulfilment_method == "Home Delivery" else "",
            "city": city if fulfilment_method == "Home Delivery" else "",
            "state": state if fulfilment_method == "Home Delivery" else "",
            "country": country if fulfilment_method == "Home Delivery" else "",
            "address_phone": mobile_no if fulfilment_method == "Home Delivery" else "",
            "formatted_address": formatted_address if fulfilment_method == "Home Delivery" else "",
            "delivery_fee": 0,
            "delivery_fee_rule": (
                "Pending Controlled Delivery Review"
                if fulfilment_method == "Home Delivery"
                else "Pharmacy Pickup"
            ),
            "delivery_instructions": delivery_instructions,
            "currency": cart["currency"],
            "discount_amount": 0,
            "payment_timing": "Collect on Delivery",
            "payment_method": payment_method,
            "payment_status": "Not Declared",
            "customer": linked_customer or None,
            "customer_address": selected_address or None,
            "customer_resolution_status": "Matched" if linked_customer else "Unresolved",
        }
    online_meta = frappe.get_meta("Online Order")
    if website_user and online_meta.has_field("custom_website_user"):
        order_data["custom_website_user"] = website_user
    if linked_customer and online_meta.has_field("custom_customer_resolution_method"):
        order_data["custom_customer_resolution_method"] = "Website User"
    if linked_customer and online_meta.has_field("custom_customer_resolved_at"):
        order_data["custom_customer_resolved_at"] = now_datetime()
    if linked_customer and online_meta.has_field("custom_customer_resolution_notes"):
        order_data["custom_customer_resolution_notes"] = "Matched from authenticated Website User."

    order = frappe.get_doc(order_data)

    for item in cart["items"]:
        order.append(
            "items",
            {
                "item_code": item["item_code"],
                "requested_qty": item["qty"],
                "uom": item["uom"],
                "listed_rate": item["rate"],
                "approved_rate": item["rate"],
                "availability_status": "Available",
                "stock_review_status": "Pending",
                "prescription_item_status": (
                    "Pending" if item["requires_prescription"] else "Not Required"
                ),
            },
        )

    order.flags.ignore_permissions = True
    order.insert(ignore_permissions=True)

    receipt = _safe_order_receipt(order.name, checkout_token)
    receipt["created"] = 1
    receipt["idempotent_replay"] = 0
    receipt["checkout_token"] = checkout_token
    return receipt


@frappe.whitelist(allow_guest=True)
def get_public_order_receipt(
    online_order: str | None = None,
    checkout_token: str | None = None,
) -> dict[str, Any]:
    clean_order = _clean_text(online_order, 140)
    clean_token = _clean_text(checkout_token, 100)
    if not clean_order:
        frappe.throw(_("Online Order is required."))
    if not clean_token or not CHECKOUT_TOKEN_PATTERN.fullmatch(clean_token):
        frappe.throw(_("Invalid checkout token."))
    return _safe_order_receipt(clean_order, clean_token)
