import json

import frappe


DUPLICATE_PHRASES = (
    "يوجد بالفعل delivery settlement",
    "داخل نفس الشيفت",
    "already exists",
    "same shift",
    "duplicate delivery settlement",
)


def _looks_like_old_duplicate_guard(name, script):
    text = str(script or "")
    lowered = text.lower()
    name_lowered = str(name or "").lower()

    exact_message = any(
        phrase in lowered
        for phrase in DUPLICATE_PHRASES
    )

    has_settlement_context = (
        "delivery settlement" in lowered
        and "delivery_boy" in lowered
        and "shift_reference" in lowered
    )

    has_duplicate_query = any(
        token in lowered
        for token in (
            "frappe.db.exists",
            "frappe.db.count",
            "frappe.db.get_value",
            "frappe.get_all",
            "frappe.get_list",
        )
    )

    has_duplicate_intent = any(
        token in lowered or token in name_lowered
        for token in (
            "duplicate",
            "unique",
            "already",
            "existing",
            "prevent multiple",
            "منع التكرار",
        )
    )

    return exact_message or (
        has_settlement_context
        and has_duplicate_query
        and has_duplicate_intent
    )


def _disable_server_guards():
    disabled = []

    rows = frappe.get_all(
        "Server Script",
        filters={
            "reference_doctype": "Delivery Settlement",
            "disabled": 0,
        },
        fields=[
            "name",
            "doctype_event",
            "script",
        ],
        limit_page_length=1000,
    )

    for row in rows:
        if not _looks_like_old_duplicate_guard(
            row.name,
            row.script,
        ):
            continue

        frappe.db.set_value(
            "Server Script",
            row.name,
            "disabled",
            1,
            update_modified=False,
        )
        disabled.append(
            {
                "doctype": "Server Script",
                "name": row.name,
                "event": row.doctype_event,
            }
        )

    return disabled


def _disable_client_guards():
    disabled = []

    rows = frappe.get_all(
        "Client Script",
        filters={
            "dt": "Delivery Settlement",
            "enabled": 1,
        },
        fields=[
            "name",
            "script",
            "view",
        ],
        limit_page_length=1000,
    )

    for row in rows:
        if not _looks_like_old_duplicate_guard(
            row.name,
            row.script,
        ):
            continue

        frappe.db.set_value(
            "Client Script",
            row.name,
            "enabled",
            0,
            update_modified=False,
        )
        disabled.append(
            {
                "doctype": "Client Script",
                "name": row.name,
                "view": row.view,
            }
        )

    return disabled


def install():
    """Allow multiple Delivery Settlement cycles per driver and shift."""
    disabled = []
    disabled.extend(_disable_server_guards())
    disabled.extend(_disable_client_guards())

    frappe.db.commit()
    frappe.clear_cache()

    result = {
        "disabled_duplicate_guards": disabled,
        "multi_cycle_enabled": True,
    }

    print(
        "Delivery Settlement multi-cycle fix V2.14 installed successfully."
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def verify():
    active_suspects = []

    server_rows = frappe.get_all(
        "Server Script",
        filters={
            "reference_doctype": "Delivery Settlement",
            "disabled": 0,
        },
        fields=["name", "doctype_event", "script"],
        limit_page_length=1000,
    )

    for row in server_rows:
        if _looks_like_old_duplicate_guard(row.name, row.script):
            active_suspects.append(
                {
                    "doctype": "Server Script",
                    "name": row.name,
                    "event": row.doctype_event,
                }
            )

    client_rows = frappe.get_all(
        "Client Script",
        filters={
            "dt": "Delivery Settlement",
            "enabled": 1,
        },
        fields=["name", "view", "script"],
        limit_page_length=1000,
    )

    for row in client_rows:
        if _looks_like_old_duplicate_guard(row.name, row.script):
            active_suspects.append(
                {
                    "doctype": "Client Script",
                    "name": row.name,
                    "view": row.view,
                }
            )

    result = {
        "active_duplicate_guards": active_suspects,
        "ready": not bool(active_suspects),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result
