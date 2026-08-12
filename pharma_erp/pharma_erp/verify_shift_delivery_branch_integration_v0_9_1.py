from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, now_datetime


BRANCH_DOCTYPES = (
    "Pharmacy Shift Closing",
    "Delivery Settlement",
    "Delivery Handover",
)


def _clean(value) -> str:
    return str(value or "").strip()


def _assert_schema() -> dict:
    result = {}
    for doctype in BRANCH_DOCTYPES:
        field = frappe.get_meta(doctype).get_field("branch")
        expected_read_only = 0 if doctype == "Pharmacy Shift Closing" else 1
        valid = bool(
            field
            and field.fieldtype == "Link"
            and field.options == "Branch"
            and not field.reqd
            and int(field.read_only or 0) == expected_read_only
            and field.in_standard_filter
            and field.search_index
        )
        result[doctype] = {
            "exists": bool(field),
            "fieldtype": field.fieldtype if field else "",
            "options": field.options if field else "",
            "required": int(field.reqd or 0) if field else None,
            "read_only": int(field.read_only or 0) if field else None,
            "valid": valid,
        }
    return result


def _profile_pairs() -> set[tuple[str, str]]:
    return {
        (_clean(row.company), _clean(row.branch))
        for row in frappe.get_all(
            "Pharmacy Branch Profile",
            filters={"disabled": 0},
            fields=["company", "branch"],
            limit_page_length=10000,
        )
        if _clean(row.company) and _clean(row.branch)
    }


def _audit_attribution() -> dict:
    profile_pairs = _profile_pairs()
    shift_rows = frappe.get_all(
        "Pharmacy Shift Closing",
        fields=["name", "company", "branch"],
        limit_page_length=100000,
    )
    shifts = {row.name: row for row in shift_rows}

    invalid_shift_profiles = []
    legacy_shifts = []
    for shift in shift_rows:
        branch = _clean(shift.branch)
        if not branch:
            legacy_shifts.append(shift.name)
        elif (_clean(shift.company), branch) not in profile_pairs:
            invalid_shift_profiles.append(shift.name)

    settlement_rows = frappe.get_all(
        "Delivery Settlement",
        fields=["name", "shift_reference", "branch"],
        limit_page_length=100000,
    )
    settlements = {row.name: row for row in settlement_rows}
    orphan_settlements = []
    settlement_shift_mismatches = []
    legacy_settlements = []
    for settlement in settlement_rows:
        branch = _clean(settlement.branch)
        if not branch:
            legacy_settlements.append(settlement.name)
        shift = shifts.get(settlement.shift_reference)
        if not shift:
            orphan_settlements.append(settlement.name)
        elif branch != _clean(shift.branch):
            settlement_shift_mismatches.append(settlement.name)

    handover_rows = frappe.get_all(
        "Delivery Handover",
        fields=[
            "name",
            "delivery_settlement",
            "shift_reference",
            "branch",
        ],
        limit_page_length=100000,
    )
    orphan_handovers = []
    handover_settlement_mismatches = []
    handover_shift_mismatches = []
    legacy_handovers = []
    for handover in handover_rows:
        branch = _clean(handover.branch)
        if not branch:
            legacy_handovers.append(handover.name)
        settlement = settlements.get(handover.delivery_settlement)
        shift = shifts.get(handover.shift_reference)
        if not settlement:
            orphan_handovers.append(handover.name)
            continue
        if (
            handover.shift_reference != settlement.shift_reference
            or branch != _clean(settlement.branch)
        ):
            handover_settlement_mismatches.append(handover.name)
        if not shift or branch != _clean(shift.branch):
            handover_shift_mismatches.append(handover.name)

    return {
        "counts": {
            "shifts": len(shift_rows),
            "legacy_not_attributable_shifts": len(legacy_shifts),
            "settlements": len(settlement_rows),
            "legacy_not_attributable_settlements": len(legacy_settlements),
            "handovers": len(handover_rows),
            "legacy_not_attributable_handovers": len(legacy_handovers),
        },
        "violations": {
            "invalid_shift_profiles": invalid_shift_profiles,
            "orphan_settlements": orphan_settlements,
            "settlement_shift_mismatches": settlement_shift_mismatches,
            "orphan_handovers": orphan_handovers,
            "handover_settlement_mismatches": handover_settlement_mismatches,
            "handover_shift_mismatches": handover_shift_mismatches,
        },
    }


def _notification_baseline() -> dict:
    rows = frappe.db.sql(
        """
        SELECT notification_status, COUNT(*)
        FROM `tabOnline Order Customer Notification`
        GROUP BY notification_status
        """
    )
    statuses = {str(status or ""): int(count or 0) for status, count in rows}
    return {
        "total": sum(statuses.values()),
        "deferred": statuses.get("Deferred", 0),
        "pending": statuses.get("Pending", 0),
        "sent": statuses.get("Sent", 0),
        "failed": statuses.get("Failed", 0),
    }


def run():
    """Read-only acceptance check for Step 4C R2."""
    schema = _assert_schema()
    attribution = _audit_attribution()
    schema_errors = [
        doctype for doctype, row in schema.items() if not row["valid"]
    ]
    data_errors = {
        key: values
        for key, values in attribution["violations"].items()
        if values
    }

    if schema_errors or data_errors:
        frappe.throw(
            _("Step 4C R2 verification failed: {0}").format(
                frappe.as_json(
                    {
                        "schema_errors": schema_errors,
                        "data_errors": data_errors,
                    }
                )
            )
        )

    return {
        "ok": True,
        "schema": schema,
        "attribution": attribution,
        "notification_baseline": _notification_baseline(),
    }


def verify_settlement_invoice_link_sync(invoice_name=None):
    """Transactionally verify settlement link add, remove, and delete hooks."""
    filters = {
        "docstatus": 1,
        "custom_order_type": "Home Delivery",
        "custom_delivery_status": "Delivered",
        "custom_collection_verification_status": "Confirmed",
        "custom_collection_received_by": "Delivery Boy",
        "custom_delivery_settlement": ["is", "not set"],
    }
    if invoice_name:
        filters["name"] = invoice_name

    invoice = frappe.db.get_value(
        "Sales Invoice",
        filters,
        [
            "name",
            "customer_name",
            "company",
            "custom_pharmacy_branch",
            "custom_delivery_boy",
            "custom_delivery_trip",
            "custom_confirmed_collected_amount",
            "custom_collection_payment_entry",
            "custom_collection_confirmed_at",
        ],
        as_dict=True,
    )
    if not invoice:
        frappe.throw(
            _(
                "No delivered, confirmed, driver-collected Sales Invoice "
                "without a Delivery Settlement link was found."
            )
        )

    shift_reference = frappe.db.get_value(
        "Delivery Trip",
        invoice.custom_delivery_trip,
        "custom_shift_reference",
    )
    if not shift_reference:
        frappe.throw(
            _("Sales Invoice {0} has no attributed Delivery Trip Shift.").format(
                frappe.bold(invoice.name)
            )
        )

    amount = flt(invoice.custom_confirmed_collected_amount)
    if amount <= 0:
        frappe.throw(
            _("Sales Invoice {0} has no confirmed collection amount.").format(
                frappe.bold(invoice.name)
            )
        )

    probe_name = ""
    checks = {}
    try:
        settlement = frappe.new_doc("Delivery Settlement")
        settlement.delivery_boy = invoice.custom_delivery_boy
        settlement.shift_reference = shift_reference
        settlement.branch = invoice.custom_pharmacy_branch
        settlement.date = now_datetime()
        settlement.pilot_float = 0
        settlement.settlement_status = "Open"
        settlement.total_expected = amount
        settlement.total_collected_by_driver = amount
        settlement.remaining_with_driver = amount
        if settlement.meta.has_field("custom_collection_shift"):
            settlement.custom_collection_shift = shift_reference

        child = settlement.append("invoices", {})
        child.invoice_number = invoice.name
        child.customer_name = invoice.customer_name
        child.amount = amount
        child.mode_of_payment = "Cash"
        child.collection_received_by = "Delivery Boy"
        child.payment_entry = invoice.custom_collection_payment_entry
        child.confirmed_collection_amount = amount
        child.collection_status = "Confirmed"
        child.delivery_trip = invoice.custom_delivery_trip
        child.collected_at = invoice.custom_collection_confirmed_at

        settlement.insert(ignore_permissions=True)
        probe_name = settlement.name
        link_after_insert = frappe.db.get_value(
            "Sales Invoice",
            invoice.name,
            "custom_delivery_settlement",
        ) or ""
        checks["insert_sets_link"] = link_after_insert == probe_name

        settlement.set("invoices", [])
        settlement.save(ignore_permissions=True)
        link_after_remove = frappe.db.get_value(
            "Sales Invoice",
            invoice.name,
            "custom_delivery_settlement",
        ) or ""
        checks["removing_row_clears_link"] = not link_after_remove

        settlement.append(
            "invoices",
            {
                "invoice_number": invoice.name,
                "customer_name": invoice.customer_name,
                "amount": amount,
                "mode_of_payment": "Cash",
                "collection_received_by": "Delivery Boy",
                "payment_entry": invoice.custom_collection_payment_entry,
                "confirmed_collection_amount": amount,
                "collection_status": "Confirmed",
                "delivery_trip": invoice.custom_delivery_trip,
                "collected_at": invoice.custom_collection_confirmed_at,
            },
        )
        settlement.save(ignore_permissions=True)
        link_after_restore = frappe.db.get_value(
            "Sales Invoice",
            invoice.name,
            "custom_delivery_settlement",
        ) or ""
        checks["restoring_row_sets_link"] = link_after_restore == probe_name

        frappe.delete_doc(
            "Delivery Settlement",
            probe_name,
            ignore_permissions=True,
        )
        link_after_delete = frappe.db.get_value(
            "Sales Invoice",
            invoice.name,
            "custom_delivery_settlement",
        ) or ""
        checks["deleting_draft_clears_link"] = not link_after_delete

        failures = [key for key, passed in checks.items() if not passed]
        if failures:
            frappe.throw(
                _("Delivery Settlement link synchronization failed: {0}").format(
                    ", ".join(failures)
                )
            )

        return {
            "ok": True,
            "invoice": invoice.name,
            "branch": invoice.custom_pharmacy_branch,
            "shift": shift_reference,
            "probe_settlement": probe_name,
            "checks": checks,
            "rolled_back": True,
        }
    finally:
        frappe.db.rollback()
