from __future__ import annotations

import re
from pathlib import Path

import frappe
from frappe import _


PATCH_MARKER = "step2e3CollectionRequiredAtDelivery"

TARGETS = (
    (
        "Delivery Management",
        "pharma_erp/page/delivery_management/delivery_management.js",
    ),
    (
        "My Deliveries",
        "pharma_erp/page/my_deliveries/my_deliveries.js",
    ),
)

DISPLAY_OUTSTANDING_PATTERN = re.compile(
    r"""(?P<block>
^[ \t]*const[ \t]+displayOutstanding[ \t]*=[ \t]*partialReturnRequest[ \t]*\n
^[ \t]*\?[ \t]*Number\(partialReturnRequest\.remaining_collectible[ \t]*\|\|[ \t]*0\)[ \t]*\n
^[ \t]*:[ \t]*Number\(order\.group_outstanding_amount[ \t]*\?\?[ \t]*order\.outstanding_amount[ \t]*\?\?[ \t]*0\);
)""",
    re.MULTILINE | re.VERBOSE,
)

DISPLAY_INSERTION = """
        const step2e3CollectionRequiredAtDelivery = (
            ["Collect on Delivery", "Partially Prepaid"].includes(prepaidTiming)
            && displayOutstanding > 0.01
            && !["Confirmed", "Awaiting Confirmation"].includes(collectionStatus)
        );
        const step2e3CollectionStatusDisplay = step2e3CollectionRequiredAtDelivery
            ? `${__("مطلوب عند التسليم")} — ${this.format_money(displayOutstanding)}`
            : this.get_collection_status_label(collectionStatus);
        const step2e3ShowDeliveryReturnReason = (
            deliveryReturnStatus !== "Not Required"
            && Boolean(deliveryReturnReason)
        );
"""

OLD_COLLECTION_ROW = '${this.info_row("حالة التحصيل", this.get_collection_status_label(collectionStatus))}'
NEW_COLLECTION_ROW = '${this.info_row("حالة التحصيل", step2e3CollectionStatusDisplay)}'

OLD_RETURN_REASON_ROW = '${deliveryReturnReason ? this.info_row("سبب الرجوع", deliveryReturnReason) : ""}'
NEW_RETURN_REASON_ROW = '${step2e3ShowDeliveryReturnReason ? this.info_row("سبب الرجوع", deliveryReturnReason) : ""}'


def _app_root() -> Path:
    return Path(frappe.get_app_path("pharma_erp"))


def _target_path(relative_path: str) -> Path:
    return _app_root() / relative_path


def _build_patched_content(path: Path) -> tuple[str, dict]:
    if not path.exists():
        frappe.throw(
            _("Target JavaScript file was not found: {0}").format(path)
        )

    original = path.read_text(encoding="utf-8")
    content = original

    if PATCH_MARKER not in content:
        match = DISPLAY_OUTSTANDING_PATTERN.search(content)
        if not match:
            frappe.throw(
                _(
                    "Could not locate the outstanding display block in {0}. "
                    "No source file was changed."
                ).format(path)
            )

        block = match.group("block")
        first_line = block.splitlines()[0]
        indent = first_line[: len(first_line) - len(first_line.lstrip())]

        insertion = "\n".join(
            indent + line.lstrip()
            if line.strip()
            else ""
            for line in DISPLAY_INSERTION.strip("\n").splitlines()
        )

        content = (
            content[: match.end("block")]
            + "\n"
            + insertion
            + "\n"
            + content[match.end("block") :]
        )

    content = content.replace(
        OLD_COLLECTION_ROW,
        NEW_COLLECTION_ROW,
        1,
    )
    content = content.replace(
        OLD_RETURN_REASON_ROW,
        NEW_RETURN_REASON_ROW,
        1,
    )

    required_tokens = (
        PATCH_MARKER,
        NEW_COLLECTION_ROW,
        NEW_RETURN_REASON_ROW,
        '["Collect on Delivery", "Partially Prepaid"]',
        'deliveryReturnStatus !== "Not Required"',
    )
    missing = [
        token
        for token in required_tokens
        if token not in content
    ]
    if missing:
        frappe.throw(
            _(
                "Step 2E.3 patch validation failed for {0}: {1}. "
                "No source file was changed."
            ).format(path, ", ".join(missing))
        )

    if OLD_COLLECTION_ROW in content:
        frappe.throw(
            _(
                "Old collection display expression remains in {0}."
            ).format(path)
        )

    if OLD_RETURN_REASON_ROW in content:
        frappe.throw(
            _(
                "Old return-reason display expression remains in {0}."
            ).format(path)
        )

    return (
        content.rstrip("\r\n") + "\n",
        {
            "path": str(path),
            "changed": content != original,
            "patch_marker_present": PATCH_MARKER in content,
            "collection_display_fixed": NEW_COLLECTION_ROW in content,
            "return_reason_guard_fixed": NEW_RETURN_REASON_ROW in content,
        },
    )


@frappe.whitelist()
def apply():
    prepared = []

    # Validate all target files before writing either file.
    for label, relative_path in TARGETS:
        path = _target_path(relative_path)
        content, result = _build_patched_content(path)
        result["label"] = label
        prepared.append((path, content, result))

    for path, content, result in prepared:
        if result["changed"]:
            path.write_text(content, encoding="utf-8")

    results = [result for _, _, result in prepared]
    output = {
        "step2e3_display_patch_applied": True,
        "files": results,
        "ok": all(
            row["patch_marker_present"]
            and row["collection_display_fixed"]
            and row["return_reason_guard_fixed"]
            for row in results
        ),
    }

    print(output)
    print(frappe.as_json(output))
    return output


@frappe.whitelist()
def verify():
    results = []

    for label, relative_path in TARGETS:
        path = _target_path(relative_path)

        if not path.exists():
            results.append(
                {
                    "label": label,
                    "path": str(path),
                    "exists": False,
                    "ok": False,
                }
            )
            continue

        content = path.read_text(encoding="utf-8")

        row = {
            "label": label,
            "path": str(path),
            "exists": True,
            "patch_marker_present": PATCH_MARKER in content,
            "collection_display_fixed": NEW_COLLECTION_ROW in content,
            "return_reason_guard_fixed": NEW_RETURN_REASON_ROW in content,
            "old_collection_expression_absent": OLD_COLLECTION_ROW not in content,
            "old_return_reason_expression_absent": OLD_RETURN_REASON_ROW not in content,
        }
        row["ok"] = all(
            value
            for key, value in row.items()
            if key not in {"label", "path"}
        )
        results.append(row)

    output = {
        "step2e3_display_patch_verified": True,
        "files": results,
        "expected_collection_display": (
            "Collect on Delivery + outstanding > 0 "
            "shows Required on Delivery with amount"
        ),
        "expected_return_display": (
            "Return reason is hidden while return status is Not Required"
        ),
        "ok": len(results) == len(TARGETS)
        and all(row.get("ok") for row in results),
    }

    print(output)
    print(frappe.as_json(output))
    return output
