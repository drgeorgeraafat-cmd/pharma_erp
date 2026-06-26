"""Foundation logic for pharmacy purchase invoices, batches and retail prices."""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now, nowdate


DEFAULT_SETTINGS = frappe._dict(
    {
        "default_entry_mode": "Quick Invoice & Receipt",
        "require_supplier_invoice_number": 1,
        "prevent_duplicate_supplier_invoice_number": 1,
        "require_supplier_invoice_attachment": 0,
        "default_cash_invoice_excluded_from_claim": 1,
        "enable_automatic_batch_generation": 1,
        "require_batch_number": 1,
        "require_expiry_date": 1,
        "require_manager_approval_for_auto_batch": 0,
        "auto_batch_prefix": "AUTO",
        "retail_price_update_policy": "Ask Before Update",
        "selling_price_list": "Standard Selling",
        "retail_price_difference_tolerance": 0.01,
        "block_batch_price_conflict": 1,
    }
)


def _has_field(doctype: str, fieldname: str) -> bool:
    return bool(frappe.get_meta(doctype).has_field(fieldname))


def _set_if_field(doc, fieldname: str, value) -> None:
    if doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


def _set_row_if_field(row, fieldname: str, value) -> None:
    if row.meta.has_field(fieldname):
        row.set(fieldname, value)


def get_purchase_settings():
    if not frappe.db.exists("DocType", "Pharmacy Purchase Settings"):
        return DEFAULT_SETTINGS.copy()

    settings = DEFAULT_SETTINGS.copy()
    try:
        doc = frappe.get_single("Pharmacy Purchase Settings")
    except Exception:
        return settings

    for key in DEFAULT_SETTINGS:
        value = doc.get(key)
        if value not in (None, ""):
            settings[key] = value
    return settings


def validate_purchase_invoice(doc, method=None):
    if cint(doc.get("is_return")):
        return

    settings = get_purchase_settings()
    _set_purchase_defaults(doc, settings)

    bonus_count = 0
    auto_batch_count = 0
    price_change_count = 0
    needs_recalculation = False
    item_flags = {}

    for row in doc.get("items") or []:
        if not row.item_code:
            continue

        if cint(row.get("custom_is_bonus_item")):
            bonus_count += 1

        needs_recalculation = (
            _calculate_pharmacy_purchase_rate(row) or needs_recalculation
        )

        if _detect_retail_price_change(row, settings):
            price_change_count += 1

        if not cint(doc.get("update_stock")):
            continue

        flags = item_flags.get(row.item_code)
        if flags is None:
            flags = frappe.db.get_value(
                "Item",
                row.item_code,
                ["has_batch_no", "has_expiry_date"],
                as_dict=True,
            ) or frappe._dict()
            item_flags[row.item_code] = flags

        if cint(flags.get("has_batch_no")) and _prepare_batch_for_row(
            doc, row, flags, settings
        ):
            auto_batch_count += 1

    _set_if_field(doc, "custom_bonus_line_count", bonus_count)
    _set_if_field(doc, "custom_auto_batch_count", auto_batch_count)
    _set_if_field(doc, "custom_price_change_count", price_change_count)
    _set_if_field(
        doc,
        "custom_retail_price_review_status",
        "Pending Review" if price_change_count else "Not Required",
    )

    if needs_recalculation and hasattr(doc, "calculate_taxes_and_totals"):
        doc.calculate_taxes_and_totals()


def before_submit_purchase_invoice(doc, method=None):
    if cint(doc.get("is_return")):
        return

    settings = get_purchase_settings()
    _validate_batch_conflict_approvals(doc, settings)
    bill_no = (doc.get("bill_no") or "").strip()

    if cint(settings.require_supplier_invoice_number) and not bill_no:
        frappe.throw(_("Supplier Invoice Number is required before submitting."))

    if cint(settings.prevent_duplicate_supplier_invoice_number) and doc.supplier and bill_no:
        duplicate = frappe.db.exists(
            "Purchase Invoice",
            {
                "supplier": doc.supplier,
                "bill_no": bill_no,
                "docstatus": ["<", 2],
                "name": ["!=", doc.name],
            },
        )
        if duplicate:
            frappe.throw(
                _("Supplier Invoice Number {0} already exists for this supplier in {1}.").format(
                    frappe.bold(bill_no),
                    frappe.get_desk_link("Purchase Invoice", duplicate),
                )
            )

    if cint(settings.require_supplier_invoice_attachment):
        attachment = doc.get("custom_supplier_invoice_attachment") or frappe.db.exists(
            "File",
            {
                "attached_to_doctype": "Purchase Invoice",
                "attached_to_name": doc.name,
                "is_folder": 0,
            },
        )
        if not attachment:
            frappe.throw(_("Attach the supplier invoice before submitting."))


def on_submit_purchase_invoice(doc, method=None):
    if cint(doc.get("is_return")):
        return

    _update_batch_purchase_metadata(doc)
    settings = get_purchase_settings()
    policy = settings.retail_price_update_policy or "Ask Before Update"
    change_count = cint(doc.get("custom_price_change_count"))

    if not change_count:
        _set_invoice_review_status(doc.name, "Not Required")
    elif policy == "Update Automatically":
        _apply_retail_price_updates(doc, settings)
    elif policy == "Do Not Update":
        _set_invoice_review_status(doc.name, "Skipped")
    else:
        _set_invoice_review_status(doc.name, "Pending Review")


def _set_purchase_defaults(doc, settings):
    if doc.meta.has_field("custom_purchase_entry_mode") and not doc.get(
        "custom_purchase_entry_mode"
    ):
        doc.custom_purchase_entry_mode = settings.default_entry_mode

    if doc.get("custom_purchase_entry_mode") == "Quick Invoice & Receipt":
        doc.update_stock = 1

    if doc.supplier and doc.meta.has_field("custom_payment_classification"):
        if not doc.get("custom_payment_classification") and _has_field(
            "Supplier", "custom_purchase_payment_model"
        ):
            payment_model = frappe.db.get_value(
                "Supplier", doc.supplier, "custom_purchase_payment_model"
            )
            if payment_model == "Cash":
                doc.custom_payment_classification = "Cash Invoice"
            elif payment_model in ("Credit Claim", "Mixed"):
                doc.custom_payment_classification = "Claim Invoice"

    if doc.get("custom_payment_classification") == "Cash Invoice":
        _set_if_field(doc, "custom_exclude_from_supplier_claim", 1)


def _normalize_bonus_row(row) -> bool:
    changed = False
    printed_price = flt(row.get("custom_selling_price"))
    values = {
        "is_free_item": 1,
        "custom_supplier_discount_percentage": 0,
        "custom_additional_discount": 0,
        "custom_effective_discount_percentage": 100,
        "discount_percentage": 100,
        "discount_amount": printed_price,
        "rate": 0,
        "amount": 0,
        "net_rate": 0,
        "net_amount": 0,
        "allow_zero_valuation_rate": 1,
    }
    for fieldname, value in values.items():
        if row.meta.has_field(fieldname) and row.get(fieldname) != value:
            row.set(fieldname, value)
            changed = True
    return changed


def _calculate_pharmacy_purchase_rate(row) -> bool:
    """Calculate rate while preserving basic, additional and effective discounts.

    ``custom_supplier_discount_percentage`` is the supplier/company discount entered
    by the user. ``custom_additional_discount`` is applied sequentially. ERPNext's
    standard ``discount_percentage`` stores only the resulting effective discount so
    its native totals and accounting remain consistent.
    """
    if cint(row.get("custom_is_bonus_item")):
        return _normalize_bonus_row(row)

    printed_price = flt(row.get("custom_selling_price"))
    if not printed_price and row.item_code and _has_field("Item", "custom_customer_price"):
        printed_price = flt(
            frappe.db.get_value("Item", row.item_code, "custom_customer_price")
        )
        if printed_price:
            _set_row_if_field(row, "custom_selling_price", printed_price)

    if not printed_price:
        return False

    base_discount = max(
        0.0,
        min(100.0, flt(row.get("custom_supplier_discount_percentage"))),
    )
    additional_discount = max(
        0.0, min(100.0, flt(row.get("custom_additional_discount")))
    )
    effective_discount = 100.0 * (
        1.0
        - (1.0 - base_discount / 100.0)
        * (1.0 - additional_discount / 100.0)
    )
    final_rate = printed_price * (1.0 - effective_discount / 100.0)
    total_discount_amount = printed_price - final_rate

    changed = False
    values = {
        "price_list_rate": printed_price,
        "custom_effective_discount_percentage": effective_discount,
        "discount_percentage": effective_discount,
        "discount_amount": total_discount_amount,
        "rate": final_rate,
    }
    for fieldname, value in values.items():
        if row.meta.has_field(fieldname) and abs(flt(row.get(fieldname)) - flt(value)) > 0.000001:
            row.set(fieldname, value)
            changed = True
    return changed


def _detect_retail_price_change(row, settings) -> bool:
    printed_price = flt(row.get("custom_selling_price"))
    if not printed_price or not row.item_code:
        _set_row_if_field(row, "custom_price_change_detected", 0)
        return False

    current_price = flt(
        frappe.db.get_value("Item", row.item_code, "custom_customer_price")
        if _has_field("Item", "custom_customer_price")
        else 0
    )
    changed = abs(printed_price - current_price) > flt(
        settings.retail_price_difference_tolerance
    )
    _set_row_if_field(row, "custom_previous_retail_price", current_price)
    _set_row_if_field(row, "custom_price_change_detected", cint(changed))
    return changed


def _prepare_batch_for_row(doc, row, item_flags, settings) -> bool:
    batch_no = (row.get("custom_batch_number") or row.get("batch_no") or "").strip()
    expiry_date = row.get("custom_expiry_date")
    auto_generated = False

    if batch_no and not expiry_date and frappe.db.exists("Batch", batch_no):
        expiry_date = frappe.db.get_value("Batch", batch_no, "expiry_date")
        _set_row_if_field(row, "custom_expiry_date", expiry_date)

    if (
        cint(item_flags.get("has_expiry_date"))
        and cint(settings.require_expiry_date)
        and not expiry_date
    ):
        frappe.throw(
            _("Expiry Date is required for item {0} on row {1}.").format(
                frappe.bold(row.item_code), row.idx
            )
        )

    if not batch_no:
        if cint(settings.enable_automatic_batch_generation):
            if not expiry_date:
                frappe.throw(
                    _("Expiry Date is required before generating a batch for item {0}.").format(
                        frappe.bold(row.item_code)
                    )
                )
            _validate_auto_batch_authorization(row, settings)
            batch_no = _generate_batch_number(
                row.item_code, expiry_date, settings.auto_batch_prefix
            )
            auto_generated = True
            _set_row_if_field(row, "custom_batch_number", batch_no)
            _set_row_if_field(row, "custom_auto_batch_generated", 1)
        elif cint(settings.require_batch_number):
            frappe.throw(
                _("Batch Number is required for item {0} on row {1}.").format(
                    frappe.bold(row.item_code), row.idx
                )
            )
        else:
            return False

    fields = ["name", "item", "expiry_date"]
    if _has_field("Batch", "custom_printed_retail_price"):
        fields.append("custom_printed_retail_price")
    existing = frappe.db.get_value("Batch", batch_no, fields, as_dict=True)

    if existing:
        if existing.item != row.item_code:
            frappe.throw(
                _("Batch {0} belongs to item {1}, not {2}.").format(
                    frappe.bold(batch_no),
                    frappe.bold(existing.item),
                    frappe.bold(row.item_code),
                )
            )
        if expiry_date and existing.expiry_date and getdate(expiry_date) != getdate(
            existing.expiry_date
        ):
            frappe.throw(
                _("Batch {0} has a different expiry date.").format(
                    frappe.bold(batch_no)
                )
            )
        _validate_existing_batch_price(row, existing, settings)
    else:
        _create_batch(doc, row, batch_no, expiry_date, auto_generated)

    row.batch_no = batch_no
    _set_row_if_field(row, "custom_batch_number", batch_no)
    return bool(auto_generated or cint(row.get("custom_auto_batch_generated")))


def _validate_auto_batch_authorization(row, settings):
    if not cint(settings.require_manager_approval_for_auto_batch):
        return

    allowed_roles = {"Purchase Manager", "Accounts Manager", "System Manager"}
    if not allowed_roles.intersection(set(frappe.get_roles())):
        frappe.throw(_("A Purchase Manager must approve automatic batch generation."))
    if not (row.get("custom_auto_batch_reason") or "").strip():
        frappe.throw(_("Enter an Auto Batch Reason on row {0}.").format(row.idx))


def _generate_batch_number(item_code, expiry_date, prefix):
    clean_prefix = re.sub(r"[^A-Za-z0-9_-]+", "", (prefix or "AUTO").strip()) or "AUTO"
    clean_item = re.sub(r"[^A-Za-z0-9_-]+", "-", item_code).strip("-") or "ITEM"
    base = f"{clean_prefix}-{clean_item}-{getdate(expiry_date).strftime('%Y%m%d')}"
    sequence = 1
    while True:
        candidate = f"{base}-{sequence:05d}"
        if not frappe.db.exists("Batch", candidate):
            return candidate
        sequence += 1


def _create_batch(doc, row, batch_no, expiry_date, auto_generated):
    batch = frappe.new_doc("Batch")
    batch.batch_id = batch_no
    batch.item = row.item_code
    if expiry_date:
        batch.expiry_date = getdate(expiry_date)
    if batch.meta.has_field("supplier") and doc.supplier:
        batch.supplier = doc.supplier
    printed_price = flt(row.get("custom_selling_price"))
    _set_if_field(batch, "custom_printed_retail_price", printed_price)
    _set_if_field(batch, "custom_price_effective_date", doc.posting_date or nowdate())
    _set_if_field(batch, "custom_supplier", doc.supplier)
    _set_if_field(batch, "custom_price_updated_from_invoice", cint(bool(row.get("custom_selling_price"))))
    _set_if_field(batch, "custom_auto_generated", cint(auto_generated))
    _set_if_field(batch, "custom_auto_generation_reason", row.get("custom_auto_batch_reason"))
    batch.flags.ignore_permissions = True
    batch.insert(ignore_permissions=True)


def _validate_existing_batch_price(row, batch, settings):
    entered_price = flt(row.get("custom_selling_price"))
    saved_price = flt(batch.get("custom_printed_retail_price"))
    conflict = bool(
        entered_price
        and saved_price
        and abs(entered_price - saved_price)
        > flt(settings.retail_price_difference_tolerance)
    )
    _set_row_if_field(row, "custom_existing_batch_retail_price", saved_price)
    _set_row_if_field(row, "custom_batch_price_conflict", cint(conflict))

    # The conflict is stored on the draft. Approval is enforced only on submit so
    # the manager can see the saved prices, tick approval, and enter a reason.


def _validate_batch_conflict_approvals(doc, settings):
    if not cint(settings.block_batch_price_conflict):
        return

    allowed_roles = {"Purchase Manager", "Accounts Manager", "System Manager"}
    manager = bool(allowed_roles.intersection(set(frappe.get_roles())))
    for row in doc.get("items") or []:
        if not cint(row.get("custom_batch_price_conflict")):
            continue
        approved = cint(row.get("custom_approve_batch_price_conflict"))
        reason = (row.get("custom_price_conflict_reason") or "").strip()
        if approved and manager and reason:
            continue
        frappe.throw(
            _(
                "Batch price conflict on row {0}. A Purchase Manager must approve it "
                "and enter a reason before submit."
            ).format(row.idx)
        )


def _update_batch_purchase_metadata(doc):
    batch_meta = frappe.get_meta("Batch")
    for row in doc.get("items") or []:
        batch_no = row.get("batch_no") or row.get("custom_batch_number")
        if not batch_no or not frappe.db.exists("Batch", batch_no):
            continue

        values = {}
        mapping = {
            "custom_purchase_invoice": doc.name,
            "custom_supplier": doc.supplier,
            "custom_price_effective_date": doc.posting_date,
            "custom_price_updated_from_invoice": cint(bool(row.get("custom_selling_price"))),
            "custom_auto_generated": cint(row.get("custom_auto_batch_generated")),
            "custom_auto_generation_reason": row.get("custom_auto_batch_reason"),
        }
        for fieldname, value in mapping.items():
            if batch_meta.has_field(fieldname) and value not in (None, ""):
                values[fieldname] = value

        saved_price = 0.0
        printed_price = flt(row.get("custom_selling_price"))
        if batch_meta.has_field("custom_printed_retail_price"):
            saved_price = flt(
                frappe.db.get_value("Batch", batch_no, "custom_printed_retail_price")
            )
            if printed_price and not saved_price:
                values["custom_printed_retail_price"] = printed_price
                saved_price = printed_price

        if values:
            frappe.db.set_value("Batch", batch_no, values, update_modified=False)


@frappe.whitelist()
def apply_retail_price_updates(invoice_name: str):
    doc = frappe.get_doc("Purchase Invoice", invoice_name)
    if doc.docstatus != 1:
        frappe.throw(_("Submit the Purchase Invoice before updating retail prices."))

    allowed_roles = {"Purchase Manager", "Accounts Manager", "System Manager"}
    if not allowed_roles.intersection(set(frappe.get_roles())):
        frappe.throw(_("You are not permitted to approve retail price updates."), frappe.PermissionError)

    return _apply_retail_price_updates(doc, get_purchase_settings())


def _apply_retail_price_updates(doc, settings):
    if not _has_field("Item", "custom_customer_price"):
        frappe.throw(_("Item field custom_customer_price is missing."))

    updated = 0
    price_list = settings.selling_price_list or "Standard Selling"

    for row in doc.get("items") or []:
        if not cint(row.get("custom_price_change_detected")) or cint(
            row.get("custom_price_change_applied")
        ):
            continue

        new_price = flt(row.get("custom_selling_price"))
        if not row.item_code or not new_price:
            continue

        old_price = flt(
            frappe.db.get_value("Item", row.item_code, "custom_customer_price")
        )
        if abs(new_price - old_price) <= flt(
            settings.retail_price_difference_tolerance
        ):
            _mark_price_change_applied(row.name)
            continue

        frappe.db.set_value(
            "Item", row.item_code, "custom_customer_price", new_price, update_modified=True
        )
        _upsert_item_price(row.item_code, price_list, new_price)
        _create_price_change_log(doc, row, old_price, new_price)
        _mark_price_change_applied(row.name)
        updated += 1

    _set_invoice_review_status(doc.name, "Applied", reviewer=frappe.session.user)
    return updated


def _upsert_item_price(item_code, price_list, new_price):
    existing = frappe.db.get_value(
        "Item Price",
        {
            "item_code": item_code,
            "price_list": price_list,
            "batch_no": ["is", "not set"],
        },
        "name",
        order_by="valid_from desc, creation desc",
    )
    if existing:
        frappe.db.set_value(
            "Item Price", existing, "price_list_rate", new_price, update_modified=True
        )
        return

    price = frappe.new_doc("Item Price")
    price.item_code = item_code
    price.price_list = price_list
    price.price_list_rate = new_price
    price.flags.ignore_permissions = True
    price.insert(ignore_permissions=True)


def _create_price_change_log(doc, row, old_price, new_price):
    if not frappe.db.exists("DocType", "Item Retail Price Change"):
        return

    log = frappe.new_doc("Item Retail Price Change")
    log.item = row.item_code
    log.batch_no = row.get("batch_no") or row.get("custom_batch_number")
    log.supplier = doc.supplier
    log.purchase_invoice = doc.name
    log.old_price = old_price
    log.new_price = new_price
    log.price_difference = new_price - old_price
    log.effective_date = doc.posting_date
    log.change_source = "Purchase Invoice"
    log.changed_by = frappe.session.user
    log.changed_at = now()
    log.notes = _("Current Item price updated from Purchase Invoice.")
    log.flags.ignore_permissions = True
    log.insert(ignore_permissions=True)


def _mark_price_change_applied(row_name):
    if _has_field("Purchase Invoice Item", "custom_price_change_applied"):
        frappe.db.set_value(
            "Purchase Invoice Item",
            row_name,
            "custom_price_change_applied",
            1,
            update_modified=False,
        )


def _set_invoice_review_status(invoice_name, status, reviewer=None):
    meta = frappe.get_meta("Purchase Invoice")
    values = {}
    if meta.has_field("custom_retail_price_review_status"):
        values["custom_retail_price_review_status"] = status
    if reviewer and meta.has_field("custom_price_reviewed_by"):
        values["custom_price_reviewed_by"] = reviewer
    if reviewer and meta.has_field("custom_price_reviewed_at"):
        values["custom_price_reviewed_at"] = now()
    if values:
        frappe.db.set_value("Purchase Invoice", invoice_name, values, update_modified=False)
