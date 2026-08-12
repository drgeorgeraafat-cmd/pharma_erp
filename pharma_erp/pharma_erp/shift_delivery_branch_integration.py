from __future__ import annotations

import frappe
from frappe import _

from pharma_erp.pharma_erp.branch_operational_integration import (
    resolve_operational_branch,
)


BRANCH_FIELD = "branch"
SALES_INVOICE_BRANCH_FIELD = "custom_pharmacy_branch"
COLLECTION_SHIFT_FIELD = "custom_collection_shift"


def _clean(value) -> str:
    return str(value or "").strip()


def _document_is_new(doc) -> bool:
    return bool(doc.is_new())


def _validate_immutable_links(doc, fieldnames: tuple[str, ...]) -> None:
    if _document_is_new(doc):
        return

    stored = frappe.db.get_value(
        doc.doctype,
        doc.name,
        list(fieldnames),
        as_dict=True,
    )
    if not stored:
        return

    for fieldname in fieldnames:
        if _clean(doc.get(fieldname)) != _clean(stored.get(fieldname)):
            field = doc.meta.get_field(fieldname)
            frappe.throw(
                _("{0} cannot be changed after {1} is created.").format(
                    frappe.bold(field.label if field else fieldname),
                    frappe.bold(doc.doctype),
                )
            )


def validate_pharmacy_shift_branch(doc, method=None) -> str:
    """Validate new/attributed shifts without guessing legacy attribution."""
    _validate_immutable_links(doc, ("company", BRANCH_FIELD))
    branch = _clean(doc.get(BRANCH_FIELD))

    # Historical blank rows remain intentionally Not Attributable. They can
    # still be reviewed and closed, but cannot receive new branch operations.
    if not _document_is_new(doc) and not branch:
        return ""

    branch = resolve_operational_branch(
        company=doc.company,
        requested_branch=branch,
    )
    doc.set(BRANCH_FIELD, branch)
    return branch


def require_attributed_shift(shift_reference: str, *, label: str | None = None):
    shift_reference = _clean(shift_reference)
    if not shift_reference:
        frappe.throw(_("Shift Reference is required."))

    shift = frappe.get_doc("Pharmacy Shift Closing", shift_reference)
    branch = _clean(shift.get(BRANCH_FIELD))
    if not branch:
        frappe.throw(
            _(
                "Pharmacy Shift Closing {0} has no canonical Branch attribution. "
                "Legacy unattributed shifts must be reviewed explicitly and cannot receive new delivery operations."
            ).format(frappe.bold(shift_reference))
        )

    branch = resolve_operational_branch(
        company=shift.company,
        requested_branch=branch,
    )
    return shift, branch


def _validate_collection_shift(doc, expected_branch: str) -> None:
    if not doc.meta.has_field(COLLECTION_SHIFT_FIELD):
        return

    collection_shift = _clean(doc.get(COLLECTION_SHIFT_FIELD))
    if not collection_shift and _document_is_new(doc):
        collection_shift = _clean(doc.get("shift_reference"))
        doc.set(COLLECTION_SHIFT_FIELD, collection_shift)

    if not collection_shift:
        return

    _shift, collection_branch = require_attributed_shift(
        collection_shift,
        label=_("Collection Shift"),
    )
    if collection_branch != expected_branch:
        frappe.throw(
            _(
                "Collection Shift {0} belongs to Branch {1}, not {2}."
            ).format(
                frappe.bold(collection_shift),
                frappe.bold(collection_branch),
                frappe.bold(expected_branch),
            )
        )


def _validate_settlement_invoices(doc, expected_branch: str, company: str) -> None:
    invoice_names = sorted(
        {
            _clean(row.get("invoice_number"))
            for row in (doc.get("invoices") or [])
            if _clean(row.get("invoice_number"))
        }
    )
    if not invoice_names:
        return

    invoice_meta = frappe.get_meta("Sales Invoice")
    if not invoice_meta.has_field(SALES_INVOICE_BRANCH_FIELD):
        frappe.throw(_("Sales Invoice canonical Branch field is not installed."))

    rows = frappe.get_all(
        "Sales Invoice",
        filters={"name": ["in", invoice_names]},
        fields=[
            "name",
            "company",
            "custom_delivery_boy",
            SALES_INVOICE_BRANCH_FIELD,
        ],
        limit_page_length=max(100, len(invoice_names) + 10),
    )
    by_name = {row.name: row for row in rows}

    for invoice_name in invoice_names:
        invoice = by_name.get(invoice_name)
        if not invoice:
            frappe.throw(
                _("Sales Invoice {0} was not found.").format(
                    frappe.bold(invoice_name)
                )
            )
        invoice_branch = _clean(invoice.get(SALES_INVOICE_BRANCH_FIELD))
        if not invoice_branch:
            frappe.throw(
                _(
                    "Sales Invoice {0} has no canonical Branch attribution and cannot be included in an attributed Delivery Settlement."
                ).format(frappe.bold(invoice_name))
            )
        if invoice.company != company or invoice_branch != expected_branch:
            frappe.throw(
                _(
                    "Sales Invoice {0} belongs to Branch {1}; Delivery Settlement Branch is {2}."
                ).format(
                    frappe.bold(invoice_name),
                    frappe.bold(invoice_branch),
                    frappe.bold(expected_branch),
                )
            )
        if (
            _clean(invoice.get("custom_delivery_boy"))
            and _clean(invoice.get("custom_delivery_boy"))
            != _clean(doc.get("delivery_boy"))
        ):
            frappe.throw(
                _("Sales Invoice {0} belongs to another Delivery Boy.").format(
                    frappe.bold(invoice_name)
                )
            )


def validate_delivery_settlement_branch(doc, method=None) -> str:
    _validate_immutable_links(
        doc,
        ("shift_reference", "delivery_boy", BRANCH_FIELD),
    )
    if not _clean(doc.get("shift_reference")):
        return ""

    current_branch = _clean(doc.get(BRANCH_FIELD))
    shift = frappe.get_doc("Pharmacy Shift Closing", doc.shift_reference)
    shift_branch = _clean(shift.get(BRANCH_FIELD))

    if not shift_branch:
        if _document_is_new(doc) or current_branch:
            frappe.throw(
                _(
                    "Pharmacy Shift Closing {0} is Not Attributable and cannot create an attributed Delivery Settlement."
                ).format(frappe.bold(shift.name))
            )
        return ""

    _shift, shift_branch = require_attributed_shift(shift.name)
    if current_branch and current_branch != shift_branch:
        frappe.throw(
            _(
                "Delivery Settlement Branch {0} conflicts with Shift Branch {1}."
            ).format(
                frappe.bold(current_branch),
                frappe.bold(shift_branch),
            )
        )

    doc.set(BRANCH_FIELD, shift_branch)
    _validate_collection_shift(doc, shift_branch)
    _validate_settlement_invoices(doc, shift_branch, shift.company)
    return shift_branch


def validate_delivery_handover_branch(doc, method=None) -> str:
    _validate_immutable_links(doc, ("delivery_settlement", BRANCH_FIELD))
    settlement_name = _clean(doc.get("delivery_settlement"))
    if not settlement_name:
        return ""

    fields = [
        "name",
        "docstatus",
        "delivery_boy",
        "shift_reference",
        "settlement_status",
        BRANCH_FIELD,
    ]
    if frappe.get_meta("Delivery Settlement").has_field(COLLECTION_SHIFT_FIELD):
        fields.append(COLLECTION_SHIFT_FIELD)

    settlement = frappe.db.get_value(
        "Delivery Settlement",
        settlement_name,
        fields,
        as_dict=True,
    )
    if not settlement:
        frappe.throw(
            _("Delivery Settlement {0} was not found.").format(
                frappe.bold(settlement_name)
            )
        )

    settlement_branch = _clean(settlement.get(BRANCH_FIELD))
    current_branch = _clean(doc.get(BRANCH_FIELD))
    if not settlement_branch:
        if _document_is_new(doc) or current_branch:
            frappe.throw(
                _(
                    "Delivery Settlement {0} is Not Attributable and cannot receive a new Delivery Handover."
                ).format(frappe.bold(settlement_name))
            )
        return ""

    _shift, shift_branch = require_attributed_shift(settlement.shift_reference)
    if settlement_branch != shift_branch:
        frappe.throw(
            _(
                "Delivery Settlement Branch {0} conflicts with Shift Branch {1}."
            ).format(
                frappe.bold(settlement_branch),
                frappe.bold(shift_branch),
            )
        )

    if _clean(doc.get("shift_reference")) not in ("", settlement.shift_reference):
        frappe.throw(_("Delivery Handover Shift must match its Delivery Settlement."))
    if _clean(doc.get("delivery_boy")) not in ("", settlement.delivery_boy):
        frappe.throw(_("Delivery Handover Delivery Boy must match its Delivery Settlement."))
    if current_branch and current_branch != settlement_branch:
        frappe.throw(_("Delivery Handover Branch must match its Delivery Settlement."))

    if _document_is_new(doc) and (
        settlement.docstatus == 2
        or settlement.settlement_status in ("Settled", "Cancelled")
    ):
        frappe.throw(_("A completed or cancelled Delivery Settlement cannot receive a new handover."))

    doc.shift_reference = settlement.shift_reference
    doc.delivery_boy = settlement.delivery_boy
    doc.set(BRANCH_FIELD, settlement_branch)
    if doc.meta.has_field(COLLECTION_SHIFT_FIELD):
        doc.set(
            COLLECTION_SHIFT_FIELD,
            _clean(settlement.get(COLLECTION_SHIFT_FIELD))
            or settlement.shift_reference,
        )
        _validate_collection_shift(doc, settlement_branch)

    return settlement_branch
