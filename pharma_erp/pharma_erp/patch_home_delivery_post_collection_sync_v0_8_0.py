from __future__ import annotations

from pathlib import Path

import frappe
from frappe import _


PATCH_MARKER = "STEP2E4_POST_COLLECTION_RESYNC"
SYNC_BLOCK = '''    # STEP2E4_POST_COLLECTION_RESYNC
    frappe.get_attr(
        "pharma_erp.pharma_erp.doctype.online_order.online_order."
        "sync_home_delivery_after_collection"
    )(invoice.name)

'''


def _app_root() -> Path:
    return Path(frappe.get_app_path("pharma_erp")) / "pharma_erp"


def _function_region(content: str, function_name: str):
    start_token = f"def {function_name}("
    start = content.find(start_token)
    if start < 0:
        frappe.throw(
            _("Function {0} was not found.").format(function_name)
        )

    next_whitelist = content.find(
        "\n@frappe.whitelist()",
        start + len(start_token),
    )
    next_def = content.find(
        "\ndef ",
        start + len(start_token),
    )

    candidates = [
        position
        for position in (next_whitelist, next_def)
        if position >= 0
    ]
    end = min(candidates) if candidates else len(content)
    return start, end


def _prepare_patch(
    path: Path,
    function_name: str,
    return_anchor: str,
    label: str,
) -> dict:
    if not path.exists():
        frappe.throw(
            _("Target backend file was not found: {0}").format(path)
        )

    content = path.read_text(encoding="utf-8")
    start, end = _function_region(content, function_name)
    region = content[start:end]

    if PATCH_MARKER in region:
        if "sync_home_delivery_after_collection" not in region:
            frappe.throw(
                _(
                    "Step 2E.4 marker exists without the trusted sync "
                    "call in {0}.{1}."
                ).format(path, function_name)
            )
        return {
            "label": label,
            "path": str(path),
            "function": function_name,
            "changed": False,
            "marker_present": True,
            "trusted_sync_call_present": True,
            "content": content,
        }

    relative_position = region.rfind(return_anchor)
    if relative_position < 0:
        frappe.throw(
            _(
                "Could not locate the exact final return anchor in "
                "{0}.{1}: {2}"
            ).format(path, function_name, return_anchor.strip())
        )

    absolute_position = start + relative_position + 1
    patched = (
        content[:absolute_position]
        + SYNC_BLOCK
        + content[absolute_position:]
    )

    check_start, check_end = _function_region(
        patched,
        function_name,
    )
    patched_region = patched[check_start:check_end]

    marker_present = PATCH_MARKER in patched_region
    trusted_sync_call_present = (
        "sync_home_delivery_after_collection"
        in patched_region
    )

    if not marker_present or not trusted_sync_call_present:
        frappe.throw(
            _(
                "Step 2E.4 validation failed for {0}.{1}."
            ).format(path, function_name)
        )

    return {
        "label": label,
        "path": str(path),
        "function": function_name,
        "changed": True,
        "marker_present": marker_present,
        "trusted_sync_call_present": (
            trusted_sync_call_present
        ),
        "content": patched.rstrip("\r\n") + "\n",
    }


def _targets():
    return (
        {
            "label": "My Deliveries",
            "path": (
                _app_root()
                / "page"
                / "my_deliveries"
                / "my_deliveries.py"
            ),
            "function": "declare_my_delivery_collection",
            "return_anchor": "\n    return {",
        },
        {
            "label": "Delivery Management",
            "path": (
                _app_root()
                / "page"
                / "delivery_management"
                / "delivery_management.py"
            ),
            "function": "confirm_delivery_collection",
            "return_anchor": (
                "\n    return _collection_result(invoice.name)"
            ),
        },
    )


@frappe.whitelist()
def apply():
    # Prepare and validate both files before writing either one.
    prepared = [
        _prepare_patch(
            target["path"],
            target["function"],
            target["return_anchor"],
            target["label"],
        )
        for target in _targets()
    ]

    for row in prepared:
        if row["changed"]:
            Path(row["path"]).write_text(
                row["content"],
                encoding="utf-8",
            )

    files = [
        {
            key: value
            for key, value in row.items()
            if key != "content"
        }
        for row in prepared
    ]

    output = {
        "step2e4_2_exact_backend_patch_applied": True,
        "files": files,
        "ok": len(files) == 2
        and all(
            row["marker_present"]
            and row["trusted_sync_call_present"]
            for row in files
        ),
    }

    print(output)
    print(frappe.as_json(output))
    return output


@frappe.whitelist()
def verify():
    results = []

    for target in _targets():
        path = target["path"]
        content = (
            path.read_text(encoding="utf-8")
            if path.exists()
            else ""
        )

        if content:
            start, end = _function_region(
                content,
                target["function"],
            )
            region = content[start:end]
        else:
            region = ""

        row = {
            "label": target["label"],
            "path": str(path),
            "function": target["function"],
            "exists": path.exists(),
            "marker_present": PATCH_MARKER in region,
            "trusted_sync_call_present": (
                "sync_home_delivery_after_collection"
                in region
            ),
            "exact_return_anchor_present": (
                target["return_anchor"].strip()
                in region
            ),
        }
        row["ok"] = all(
            row[key]
            for key in (
                "exists",
                "marker_present",
                "trusted_sync_call_present",
                "exact_return_anchor_present",
            )
        )
        results.append(row)

    output = {
        "step2e4_2_exact_backend_patch_verified": True,
        "files": results,
        "ok": len(results) == 2
        and all(row["ok"] for row in results),
    }

    print(output)
    print(frappe.as_json(output))
    return output
