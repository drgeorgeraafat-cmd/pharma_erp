from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from pharma_erp.online_catalog_readiness import get_item_readiness


READY_STATUSES = {"Ready", "Warning"}


def _ensure_webshop_available() -> None:
    if not frappe.db.exists("DocType", "Website Item"):
        frappe.throw(
            _("Frappe Webshop is not installed on this site."),
            title=_("Webshop Required"),
        )


def _plain_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _slug(value: Any) -> str:
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "item"


def _get_readiness(item_name: str) -> frappe._dict:
    return frappe._dict(
        get_item_readiness(item_name=item_name) or {}
    )


def _is_publishable(readiness: frappe._dict) -> bool:
    return bool(
        cint(readiness.get("show_online"))
        and cint(readiness.get("blocker_count")) == 0
        and readiness.get("readiness_status") in READY_STATUSES
    )


def _issue_messages(readiness: frappe._dict) -> list[str]:
    return [
        str(issue.get("message") or "").strip()
        for issue in readiness.get("issues") or []
        if str(issue.get("message") or "").strip()
    ]


def _throw_not_publishable(readiness: frappe._dict) -> None:
    issues = _issue_messages(readiness)
    message = _(
        "This item cannot be published until all blocking readiness issues are resolved."
    )
    if issues:
        message += "<br><br><ul>{0}</ul>".format(
            "".join(f"<li>{frappe.utils.escape_html(issue)}</li>" for issue in issues)
        )
    frappe.throw(message, title=_("Online Publishing Blocked"))


def _require_permission(
    website_item: frappe.model.document.Document | None = None,
) -> None:
    if frappe.session.user == "Guest":
        frappe.throw(_("Please sign in."), frappe.PermissionError)

    if website_item:
        allowed = frappe.has_permission(
            "Website Item",
            ptype="write",
            doc=website_item,
        )
    else:
        allowed = frappe.has_permission(
            "Website Item",
            ptype="create",
        )

    if not allowed:
        frappe.throw(
            _("You are not permitted to manage Website Items."),
            frappe.PermissionError,
        )


def _set_if_changed(
    doc: frappe.model.document.Document,
    fieldname: str,
    value: Any,
) -> bool:
    if not doc.meta.has_field(fieldname):
        return False
    if doc.get(fieldname) == value:
        return False
    doc.set(fieldname, value)
    return True


def _build_route(item) -> str:
    return "products/{0}-{1}".format(
        _slug(item.get("item_name")),
        _slug(item.get("name")),
    )


def _is_usable_public_image(image: Any) -> bool:
    image = str(image or "").strip()
    if not image:
        return False

    file_row = frappe.db.get_value(
        "File",
        {"file_url": image},
        ["name", "is_private"],
        as_dict=True,
    )
    return bool(file_row and not cint(file_row.get("is_private")))


def _apply_item_snapshot(
    website_item,
    item,
    readiness: frappe._dict,
    *,
    mark_managed: bool = True,
    refresh_sync_timestamp: bool = True,
) -> bool:
    description_ar = item.get("custom_online_description_ar") or ""
    description_en = item.get("custom_online_description_en") or ""
    short_description = _plain_text(description_ar or description_en)
    short_description = short_description[:500]

    values = {
        "web_item_name": item.get("item_name") or item.get("name"),
        "item_code": item.get("name"),
        "item_name": item.get("item_name"),
        "item_group": item.get("item_group"),
        "stock_uom": item.get("stock_uom"),
        "brand": item.get("brand"),
        "has_variants": cint(item.get("has_variants")),
        "variant_of": item.get("variant_of"),
        "description": item.get("description"),
        "website_image": item.get("image"),
        "website_image_alt": item.get("item_name") or item.get("name"),
        "short_description": short_description,
        "web_long_description": description_ar or description_en,
        "ranking": cint(item.get("custom_online_sort_order")),
        "custom_online_category": item.get("custom_online_category"),
        "custom_requires_prescription": cint(
            item.get("custom_requires_prescription")
        ),
        "custom_featured_product": cint(
            item.get("custom_featured_product")
        ),
        "custom_online_availability_status": (
            item.get("custom_online_availability_status")
        ),
        "custom_online_sort_order": cint(
            item.get("custom_online_sort_order")
        ),
        "custom_online_description_ar": description_ar,
        "custom_online_description_en": description_en,
        "custom_pharma_readiness_status": (
            readiness.get("readiness_status")
        ),
        "custom_pharma_readiness_score": cint(
            readiness.get("readiness_score")
        ),
    }

    if mark_managed:
        values["custom_pharma_managed"] = 1

    changed = False
    for fieldname, value in values.items():
        changed = _set_if_changed(
            website_item,
            fieldname,
            value,
        ) or changed

    if not website_item.get("route"):
        changed = _set_if_changed(
            website_item,
            "route",
            _build_route(item),
        ) or changed

    if refresh_sync_timestamp and website_item.meta.has_field(
        "custom_pharma_last_synced_at"
    ):
        website_item.custom_pharma_last_synced_at = now_datetime()
        changed = True

    return changed


def _sync_item_published_flag(
    item_code: str,
    published: int,
) -> None:
    if not item_code:
        return

    current = cint(
        frappe.db.get_value(
            "Item",
            item_code,
            "published_in_website",
        )
    )
    published = cint(published)
    if current == published:
        return

    frappe.db.set_value(
        "Item",
        item_code,
        "published_in_website",
        published,
        update_modified=False,
    )


def _publishing_response(
    website_item,
    readiness: frappe._dict,
    action: str,
) -> dict[str, Any]:
    route = str(website_item.get("route") or "").lstrip("/")
    return {
        "action": action,
        "website_item": website_item.name,
        "item_code": website_item.item_code,
        "published": cint(website_item.published),
        "route": route,
        "website_url": frappe.utils.get_url(f"/{route}") if route else "",
        "readiness_status": readiness.get("readiness_status"),
        "readiness_score": cint(readiness.get("readiness_score")),
        "blocker_count": cint(readiness.get("blocker_count")),
        "warning_count": cint(readiness.get("warning_count")),
        "issues": readiness.get("issues") or [],
    }


def _save_controlled(
    item_name: str,
    *,
    operation: str,
) -> dict[str, Any]:
    _ensure_webshop_available()

    item = frappe.get_doc("Item", item_name)
    readiness = _get_readiness(item.name)

    existing_name = frappe.db.get_value(
        "Website Item",
        {"item_code": item.name},
        "name",
    )
    if operation == "unpublish" and not existing_name:
        frappe.throw(
            _("No Website Item exists for this Item."),
            title=_("Website Item Not Found"),
        )

    website_item = (
        frappe.get_doc("Website Item", existing_name)
        if existing_name
        else frappe.new_doc("Website Item")
    )
    _require_permission(website_item if existing_name else None)

    if operation in {"sync", "publish"} and not cint(
        item.get("custom_show_online")
    ):
        frappe.throw(
            _("Enable Show Online on the Item first."),
            title=_("Online Catalog Not Selected"),
        )

    _apply_item_snapshot(
        website_item,
        item,
        readiness,
        mark_managed=True,
        refresh_sync_timestamp=True,
    )

    action = "Synced" if existing_name else "Created"

    if not existing_name:
        website_item.published = 0

    if operation == "publish":
        if not _is_publishable(readiness):
            _throw_not_publishable(readiness)

        if not _is_usable_public_image(website_item.get("website_image")):
            frappe.throw(
                _("A usable public Website Image is required before publishing."),
                title=_("Online Publishing Blocked"),
            )

        website_item.flags.pharma_controlled_publish = True
        website_item.published = 1
        action = "Published"

    elif operation == "unpublish":
        website_item.flags.pharma_controlled_unpublish = True
        website_item.published = 0
        action = "Unpublished"

    elif cint(website_item.published) and not _is_publishable(readiness):
        website_item.flags.pharma_controlled_unpublish = True
        website_item.published = 0
        action = "Synced and Unpublished"

    website_item.flags.pharma_controlled_sync = True
    website_item.save()

    _sync_item_published_flag(
        website_item.item_code,
        website_item.published,
    )

    return _publishing_response(
        website_item,
        readiness,
        action,
    )


@frappe.whitelist()
def get_website_item_publishing_status(
    item_name: str,
) -> dict[str, Any]:
    _ensure_webshop_available()

    item = frappe.get_doc("Item", item_name)
    if not item.has_permission("read"):
        frappe.throw(_("Not permitted."), frappe.PermissionError)

    readiness = _get_readiness(item.name)
    website_item_name = frappe.db.get_value(
        "Website Item",
        {"item_code": item.name},
        "name",
    )

    result = {
        "item_code": item.name,
        "exists": cint(bool(website_item_name)),
        "website_item": website_item_name or "",
        "published": 0,
        "route": "",
        "website_url": "",
        "managed": 0,
        "publishable": cint(_is_publishable(readiness)),
        "readiness_status": readiness.get("readiness_status"),
        "readiness_score": cint(readiness.get("readiness_score")),
        "blocker_count": cint(readiness.get("blocker_count")),
        "warning_count": cint(readiness.get("warning_count")),
        "issues": readiness.get("issues") or [],
    }

    if website_item_name:
        website_item = frappe.get_doc(
            "Website Item",
            website_item_name,
        )
        route = str(website_item.get("route") or "").lstrip("/")
        result.update(
            {
                "published": cint(website_item.published),
                "route": route,
                "website_url": (
                    frappe.utils.get_url(f"/{route}")
                    if route
                    else ""
                ),
                "managed": cint(
                    website_item.get("custom_pharma_managed")
                ),
            }
        )

    return result


@frappe.whitelist()
def create_or_sync_website_item(
    item_name: str,
) -> dict[str, Any]:
    return _save_controlled(
        item_name,
        operation="sync",
    )


@frappe.whitelist()
def publish_website_item(
    item_name: str,
) -> dict[str, Any]:
    return _save_controlled(
        item_name,
        operation="publish",
    )


@frappe.whitelist()
def unpublish_website_item(
    item_name: str,
) -> dict[str, Any]:
    return _save_controlled(
        item_name,
        operation="unpublish",
    )


def validate_controlled_website_item(
    doc,
    method: str | None = None,
) -> None:
    if not doc.get("item_code"):
        return

    readiness = _get_readiness(doc.item_code)
    was_published = 0
    if not doc.is_new():
        was_published = cint(
            frappe.db.get_value(
                "Website Item",
                doc.name,
                "published",
            )
        )

    if not cint(doc.published):
        return

    controlled_publish = cint(
        getattr(doc.flags, "pharma_controlled_publish", False)
    )

    if not _is_publishable(readiness):
        if controlled_publish:
            _throw_not_publishable(readiness)

        doc.published = 0
        frappe.msgprint(
            _(
                "Website Item was kept unpublished because the linked Item "
                "does not pass Online Publishing Readiness."
            ),
            indicator="orange",
            alert=True,
        )
        return

    if not was_published and not controlled_publish:
        doc.published = 0
        frappe.msgprint(
            _(
                "Direct Website Item publishing is disabled. "
                "Use Publish Online from the Item form."
            ),
            indicator="orange",
            alert=True,
        )


def sync_website_item_publication_flag(
    doc,
    method: str | None = None,
) -> None:
    _sync_item_published_flag(
        doc.get("item_code"),
        cint(doc.get("published")),
    )


def sync_managed_website_item_from_item(
    doc,
    method: str | None = None,
) -> None:
    if not frappe.db.exists("DocType", "Website Item"):
        return

    website_item_name = frappe.db.get_value(
        "Website Item",
        {"item_code": doc.name},
        "name",
    )
    if not website_item_name:
        return

    website_item = frappe.get_doc(
        "Website Item",
        website_item_name,
    )
    if not cint(website_item.get("custom_pharma_managed")):
        return

    readiness = _get_readiness(doc.name)
    changed = _apply_item_snapshot(
        website_item,
        doc,
        readiness,
        mark_managed=True,
        refresh_sync_timestamp=False,
    )

    if cint(website_item.published) and not _is_publishable(readiness):
        website_item.flags.pharma_controlled_unpublish = True
        website_item.published = 0
        changed = True

    if not changed:
        return

    if website_item.meta.has_field("custom_pharma_last_synced_at"):
        website_item.custom_pharma_last_synced_at = now_datetime()

    website_item.flags.pharma_controlled_sync = True
    website_item.save(ignore_permissions=True)
