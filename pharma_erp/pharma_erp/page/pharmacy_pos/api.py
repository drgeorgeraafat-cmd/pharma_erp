import json
import re

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import cint, flt, getdate, nowdate

from pharma_erp.pharma_erp.delivery_attempt import mark_add_on_invoice_created


# =====================================================
# Helpers
# =====================================================


def _get_settings():
    try:
        return frappe.get_cached_doc("Pharmacy POS Settings")
    except Exception:
        return frappe._dict(
            {
                "default_warehouse": "",
                "default_price_list": "",
                "default_customer": "",
                "search_limit": 20,
                "enable_fuzzy_search": 0,
                "auto_batch_selection": 1,
                "auto_focus_search": 1,
                "default_mode_of_payment": "Cash",
            }
        )


def _has_field(doctype, fieldname):
    return bool(frappe.get_meta(doctype).has_field(fieldname))


def _set_if_field(doc, fieldname, value):
    if value is not None and _has_field(doc.doctype, fieldname):
        doc.set(fieldname, value)


def _safe_limit(value, default=20, maximum=100):
    value = cint(value) or default
    return max(1, min(value, maximum))


def _company(value=None):
    return (
        value
        or frappe.defaults.get_user_default("Company")
        or frappe.db.get_single_value("Global Defaults", "default_company")
        or ""
    )


def _company_cost_center(company):
    if not company:
        return ""

    return frappe.db.get_value(
        "Company",
        company,
        "cost_center",
    ) or ""



def _search_pattern(txt):
    """Build a tolerant LIKE pattern: spaces and * act as wildcards."""
    raw = (txt or "").strip()
    tokens = [token for token in re.split(r"[\s*%]+", raw) if token]
    like_pattern = "%" + "%".join(tokens) + "%" if tokens else "%"
    compact = re.sub(r"[\s*%_-]+", "", raw).lower()
    return raw, like_pattern, compact


def _user_is_manager():
    roles = set(frappe.get_roles(frappe.session.user))
    return bool(roles.intersection({"System Manager", "Sales Manager", "Accounts Manager"}))


def _get_all_item_batches(item_code):
    if not item_code:
        return []
    rows = frappe.get_all(
        "Batch",
        filters={"item": item_code},
        fields=["name", "expiry_date", "disabled"],
        order_by="expiry_date asc, name asc",
        limit=500,
    )
    today = getdate(nowdate())
    result = []
    for row in rows:
        if cint(row.get("disabled")):
            continue
        if row.get("expiry_date") and getdate(row.expiry_date) < today:
            continue
        result.append(row)
    return result


def _reconcile_selected_allocations(invoice_name, allocations):
    """Reconcile selected Credit Notes against a submitted invoice.

    Payment Entry advances are attached to the Sales Invoice before submit.
    This helper is therefore primarily for credit notes.  It keeps the source
    document's full unreconciled balance while applying only the requested
    amount, which prevents ERPNext's "modified after you pulled it" check from
    comparing a partial requested amount with the source's full balance.
    """
    allocations = [
        frappe._dict(row)
        for row in (allocations or [])
        if flt(row.get("allocated_amount")) > 0
    ]
    if not allocations:
        return

    from erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation import (
        PaymentReconciliation,
    )

    for requested in allocations:
        target = frappe.get_doc("Sales Invoice", invoice_name)
        if target.docstatus != 1:
            frappe.throw(
                _("Invoice {0} must be submitted before allocation.").format(invoice_name)
            )
        if flt(target.outstanding_amount) <= 0.009:
            break

        reconciliation = PaymentReconciliation(
            {
                "doctype": "Payment Reconciliation",
                "company": target.company,
                "party_type": "Customer",
                "party": target.customer,
                "receivable_payable_account": target.debit_to,
                "invoice_name": target.name,
                "payment_name": requested.reference_name,
                "invoice_limit": 50,
                "payment_limit": 50,
            }
        )
        reconciliation.get_unreconciled_entries()

        payment = next(
            (
                row
                for row in reconciliation.payments
                if row.reference_type == requested.reference_type
                and row.reference_name == requested.reference_name
            ),
            None,
        )
        invoice = next(
            (
                row
                for row in reconciliation.invoices
                if row.invoice_type == "Sales Invoice"
                and row.invoice_number == target.name
            ),
            None,
        )

        if not payment:
            frappe.throw(
                _("The selected customer balance {0} is no longer available.").format(
                    requested.reference_name
                )
            )
        if not invoice:
            frappe.throw(
                _("Invoice {0} has no outstanding amount to reconcile.").format(
                    target.name
                )
            )

        available = abs(
            flt(payment.get("unreconciled_amount") or payment.get("amount"))
        )
        outstanding = abs(flt(invoice.outstanding_amount))
        amount = min(flt(requested.allocated_amount), available, outstanding)
        if amount <= 0:
            continue

        payment_data = payment.as_dict() if hasattr(payment, "as_dict") else dict(payment)
        invoice_data = invoice.as_dict() if hasattr(invoice, "as_dict") else dict(invoice)
        payment_data["amount"] = available
        payment_data["unreconciled_amount"] = available
        invoice_data["outstanding_amount"] = outstanding

        reconciliation.allocate_entries(
            {"payments": [payment_data], "invoices": [invoice_data]}
        )
        if not reconciliation.allocation:
            frappe.throw(
                _("Unable to allocate customer balance {0}.").format(
                    requested.reference_name
                )
            )

        allocation = reconciliation.allocation[0]
        allocation.amount = available
        allocation.unreconciled_amount = available
        allocation.allocated_amount = amount
        allocation.difference_amount = 0
        allocation.exchange_rate = allocation.exchange_rate or 1
        allocation.gain_loss_posting_date = (
            payment.get("posting_date") or nowdate()
        )
        allocation.debit_or_credit_note_posting_date = (
            payment.get("posting_date") or nowdate()
        )

        reconciliation.reconcile_allocations()


def _item_ingredient_summary(item_code):
    if not item_code or not frappe.db.exists("DocType", "Item Active Ingredient"):
        return ""

    if not _has_field("Item", "custom_active_ingredients"):
        return ""

    ingredient_name_sql = (
        "COALESCE(NULLIF(ai.ingredient_name, ''), iai.active_ingredient)"
        if frappe.db.exists("DocType", "Active Ingredient")
        and _has_field("Active Ingredient", "ingredient_name")
        else "iai.active_ingredient"
    )
    strength_sql = "iai.strength" if _has_field("Item Active Ingredient", "strength") else "0"
    uom_sql = "iai.strength_uom" if _has_field("Item Active Ingredient", "strength_uom") else "''"
    active_link_sql = (
        "LEFT JOIN `tabActive Ingredient` ai ON ai.name = iai.active_ingredient"
        if frappe.db.exists("DocType", "Active Ingredient")
        else ""
    )

    return frappe.db.sql(
        f"""
        SELECT GROUP_CONCAT(
            DISTINCT CONCAT(
                {ingredient_name_sql},
                CASE WHEN IFNULL({strength_sql}, 0) > 0
                    THEN CONCAT(' ', CAST({strength_sql} AS CHAR),
                        CASE WHEN IFNULL({uom_sql}, '') != '' THEN CONCAT(' ', {uom_sql}) ELSE '' END)
                    ELSE ''
                END
            )
            ORDER BY iai.idx
            SEPARATOR ' + '
        )
        FROM `tabItem Active Ingredient` iai
        {active_link_sql}
        WHERE iai.parent = %(item_code)s
          AND iai.parenttype = 'Item'
          AND iai.parentfield = 'custom_active_ingredients'
        """,
        {"item_code": item_code},
    )[0][0] or ""



def _ingredient_signature(item_code):
    if not item_code or not frappe.db.exists("DocType", "Item Active Ingredient"):
        return tuple()
    rows = frappe.get_all(
        "Item Active Ingredient",
        filters={
            "parent": item_code,
            "parenttype": "Item",
            "parentfield": "custom_active_ingredients",
        },
        fields=["active_ingredient", "strength", "strength_uom"],
        order_by="idx asc",
        limit=100,
    )
    return tuple(
        sorted(
            (
                (row.get("active_ingredient") or "").strip().lower(),
                round(flt(row.get("strength")), 6),
                (row.get("strength_uom") or "").strip().lower(),
            )
            for row in rows
            if row.get("active_ingredient")
        )
    )


def _get_item_alternatives(item_code, warehouse="", limit=20):
    signature = _ingredient_signature(item_code)
    if not signature:
        return []

    active_names = sorted({row[0] for row in signature if row[0]})
    if not active_names:
        return []

    # Link values preserve the original case; get them again for the IN filter.
    link_values = frappe.get_all(
        "Item Active Ingredient",
        filters={
            "parent": item_code,
            "parenttype": "Item",
            "parentfield": "custom_active_ingredients",
        },
        pluck="active_ingredient",
        limit=100,
    )
    candidates = frappe.get_all(
        "Item Active Ingredient",
        filters={
            "active_ingredient": ("in", list(set(link_values))),
            "parent": ("!=", item_code),
            "parenttype": "Item",
            "parentfield": "custom_active_ingredients",
        },
        pluck="parent",
        distinct=True,
        limit=500,
    )

    dosage_field = next(
        (field for field in ["custom_dosage_form", "dosage_form"] if _has_field("Item", field)),
        None,
    )
    source_dosage = frappe.db.get_value("Item", item_code, dosage_field) if dosage_field else ""
    fee_item = _get_settings().get("delivery_fee_item") or ""
    result = []

    for candidate in candidates:
        if candidate == fee_item or _ingredient_signature(candidate) != signature:
            continue
        if dosage_field and source_dosage:
            candidate_dosage = frappe.db.get_value("Item", candidate, dosage_field)
            if candidate_dosage and candidate_dosage != source_dosage:
                continue
        item = frappe.db.get_value(
            "Item",
            candidate,
            ["disabled", "is_sales_item"],
            as_dict=True,
        )
        if not item or cint(item.disabled) or not cint(item.is_sales_item):
            continue
        context = _item_context(candidate, warehouse)
        result.append(
            {
                "item_code": context.item_code,
                "item_name": context.item_name,
                "item_name_ar": context.get("custom_item_name_ar") or "",
                "ingredient_summary": context.get("ingredient_summary") or "",
                "image": context.get("image") or "",
                "actual_qty": flt(context.get("actual_qty")),
                "customer_price": flt(context.get("custom_customer_price")),
                "dosage_form": context.get(dosage_field) if dosage_field else "",
            }
        )
        if len(result) >= _safe_limit(limit, 20, 50):
            break

    result.sort(key=lambda row: (-flt(row.get("actual_qty")), row.get("item_name") or row.get("item_code")))
    return result


def _delivery_zone_data(zone_name):
    if not zone_name or not frappe.db.exists("DocType", "Delivery Zone"):
        return None

    fields = ["name"]
    for fieldname in [
        "zone_name",
        "zone_name_ar",
        "is_active",
        "warehouse",
        "priority",
        "delivery_fee",
        "small_order_threshold",
        "small_order_delivery_fee",
        "minimum_order_amount",
        "free_delivery_above",
        "estimated_time_mins",
        "notes",
    ]:
        if _has_field("Delivery Zone", fieldname):
            fields.append(fieldname)

    data = frappe.db.get_value("Delivery Zone", zone_name, fields, as_dict=True)
    if not data:
        frappe.throw(_("Delivery Zone {0} was not found.").format(zone_name))
    return frappe._dict(data)


def _calculate_delivery_fee(zone, products_subtotal):
    zone = frappe._dict(zone or {})
    products_subtotal = flt(products_subtotal, 6)
    minimum_order = flt(zone.get("minimum_order_amount"))
    free_above = flt(zone.get("free_delivery_above"))
    small_threshold = flt(zone.get("small_order_threshold"))
    standard_fee = flt(zone.get("delivery_fee"))
    small_fee = flt(zone.get("small_order_delivery_fee"))

    if minimum_order > 0 and products_subtotal + 1e-9 < minimum_order:
        frappe.throw(
            _("Minimum order for delivery zone {0} is {1}. Current products total is {2}.").format(
                zone.get("zone_name_ar") or zone.get("zone_name") or zone.get("name"),
                minimum_order,
                products_subtotal,
            )
        )

    if free_above > 0 and products_subtotal + 1e-9 >= free_above:
        return frappe._dict({"fee": 0, "rule": "Free Delivery"})

    if small_threshold > 0 and products_subtotal + 1e-9 < small_threshold:
        return frappe._dict(
            {
                "fee": small_fee if small_fee > 0 else standard_fee,
                "rule": "Small Order",
            }
        )

    return frappe._dict({"fee": standard_fee, "rule": "Standard Delivery"})


def _validate_delivery_address(customer, address_name, warehouse):
    if not address_name:
        frappe.throw(_("Select a delivery address."))
    if not frappe.db.exists("Address", address_name):
        frappe.throw(_("Address {0} was not found.").format(address_name))

    linked = frappe.db.exists(
        "Dynamic Link",
        {
            "parent": address_name,
            "parenttype": "Address",
            "link_doctype": "Customer",
            "link_name": customer,
        },
    )
    if not linked:
        frappe.throw(_("The selected address does not belong to customer {0}.").format(customer))

    if not _has_field("Address", "custom_delivery_zone"):
        frappe.throw(_("Add custom_delivery_zone to Address before using Home Delivery."))

    zone_name = frappe.db.get_value("Address", address_name, "custom_delivery_zone")
    if not zone_name:
        frappe.throw(_("The selected address has no Delivery Zone."))

    zone = _delivery_zone_data(zone_name)
    if not cint(zone.get("is_active", 1)):
        frappe.throw(_("The selected Delivery Zone is inactive."))

    zone_warehouse = zone.get("warehouse") or ""
    if zone_warehouse and warehouse and zone_warehouse != warehouse:
        frappe.throw(
            _("Delivery Zone {0} belongs to warehouse {1}, not {2}.").format(
                zone.get("zone_name_ar") or zone.get("zone_name") or zone.name,
                zone_warehouse,
                warehouse,
            )
        )
    return zone


def _append_delivery_fee_item(doc, context, products_subtotal):
    if context.order_type != "Home Delivery":
        return frappe._dict({"fee": 0, "rule": "", "zone": None})

    zone = context.delivery_zone
    calculation = _calculate_delivery_fee(zone, products_subtotal)
    fee = flt(calculation.fee, 6)
    settings = context.settings
    fee_item = settings.get("delivery_fee_item") or ""

    if fee > 0:
        if not fee_item:
            frappe.throw(_("Set Delivery Fee Item in Pharmacy POS Settings."))
        item = frappe.db.get_value(
            "Item",
            fee_item,
            ["name", "disabled", "is_sales_item", "is_stock_item"],
            as_dict=True,
        )
        if not item or cint(item.disabled) or not cint(item.is_sales_item):
            frappe.throw(_("The configured Delivery Fee Item is invalid or disabled."))
        if cint(item.is_stock_item):
            frappe.throw(_("Delivery Fee Item must be a non-stock service item."))

        row = doc.append("items", {})
        row.item_code = fee_item
        row.qty = 1
        row.rate = fee
        row.price_list_rate = fee
        row.discount_percentage = 0
        row.warehouse = ""
        if context.cost_center and _has_field("Sales Invoice Item", "cost_center"):
            row.cost_center = context.cost_center

    _set_if_field(doc, "custom_delivery_zone", zone.name)
    _set_if_field(doc, "custom_delivery_fee", fee)
    _set_if_field(doc, "custom_estimated_delivery_time", cint(zone.get("estimated_time_mins")))
    _set_if_field(doc, "custom_delivery_fee_rule", calculation.rule)

    return frappe._dict({"fee": fee, "rule": calculation.rule, "zone": zone})



def _normalize_customer_code(value):
    value = (value or "").strip()
    if not value:
        return ""
    if value.isdigit():
        return value.zfill(6)
    return value


def _is_default_pos_customer(customer):
    settings = _get_settings()
    return bool(customer and customer == (settings.get("default_customer") or ""))


def _split_payment_rows_for_customer_credit(payments, amount_due):
    """Split tendered payments into invoice payments and unallocated customer credit."""
    invoice_rows = []
    advance_rows = []
    remaining_due = max(0, flt(amount_due, 6))

    for payment in payments or []:
        payment = frappe._dict(payment or {})
        amount = max(0, flt(payment.get("amount"), 6))
        if amount <= 0:
            continue

        applied = min(amount, remaining_due)
        if applied > 0:
            row = dict(payment)
            row["amount"] = flt(applied, 6)
            invoice_rows.append(row)
            remaining_due = flt(remaining_due - applied, 6)

        excess = flt(amount - applied, 6)
        if excess > 0:
            row = dict(payment)
            row["amount"] = excess
            advance_rows.append(row)

    return invoice_rows, advance_rows


def _create_customer_advance_payment(customer, company, payment, source_reference="", cost_center=""):
    payment = frappe._dict(payment or {})
    amount = flt(payment.get("amount"), 6)
    mode = payment.get("mode_of_payment")
    if amount <= 0:
        return None
    if not mode:
        frappe.throw(_("Mode of Payment is required for customer credit."))

    card_terminal = None
    if mode == "Credit Card":
        card_terminal = _resolve_card_terminal(payment.get("card_pos_terminal"), company)
        paid_to = card_terminal.clearing_account
    else:
        paid_to = _mode_of_payment_account(mode, company)
    if not paid_to:
        frappe.throw(
            _("No default account is configured for Mode of Payment {0} in company {1}.").format(
                mode, company
            )
        )

    from erpnext.accounts.party import get_party_account

    paid_from = get_party_account("Customer", customer, company)
    if not paid_from:
        frappe.throw(_("No receivable account was found for customer {0}.").format(customer))

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Receive"
    pe.company = company
    pe.posting_date = nowdate()
    pe.mode_of_payment = mode
    pe.party_type = "Customer"
    pe.party = customer
    pe.paid_from = paid_from
    pe.paid_to = paid_to
    pe.paid_amount = amount
    pe.received_amount = amount
    source_reference = (source_reference or "").strip()
    pe.reference_no = payment.get("reference_no") or source_reference or "Pharmacy POS Balance"
    pe.reference_date = nowdate()
    if source_reference:
        pe.remarks = _("Customer credit deposited from Pharmacy POS against {0}").format(
            source_reference
        )
    else:
        pe.remarks = payment.get("remarks") or _("Direct customer balance deposit from Pharmacy POS")
    if cost_center and _has_field("Payment Entry", "cost_center"):
        pe.cost_center = cost_center
    if card_terminal and _has_field("Payment Entry", "custom_card_pos_terminal"):
        pe.custom_card_pos_terminal = card_terminal.name

    pe.insert(ignore_permissions=True)
    pe.submit()
    return pe.name


def _generate_customer_code():
    if not _has_field("Customer", "custom_customer_code"):
        return ""

    for _ in range(100):
        generated = make_autoname("CUST-.######")
        code = generated.replace("CUST-", "", 1)
        if not frappe.db.exists("Customer", {"custom_customer_code": code}):
            return code

    frappe.throw(_("Unable to generate a unique Customer Code."))


def _ensure_customer_code(customer):
    if not customer or not _has_field("Customer", "custom_customer_code"):
        return ""

    code = frappe.db.get_value("Customer", customer, "custom_customer_code") or ""
    if code:
        return code

    code = _generate_customer_code()
    frappe.db.set_value("Customer", customer, "custom_customer_code", code, update_modified=False)
    return code


def _assert_pos_customer_create_permission():
    allowed_roles = {
        "System Manager", "Sales Manager", "Sales User",
        "Accounts Manager", "Accounts User", "POS User"
    }
    if not allowed_roles.intersection(set(frappe.get_roles(frappe.session.user))):
        frappe.throw(_("You are not allowed to create customers from Pharmacy POS."))


def _customer_result(customer):
    if not customer:
        return None
    fields = ["name", "customer_name", "mobile_no", "customer_type"]
    if _has_field("Customer", "custom_customer_code"):
        fields.append("custom_customer_code")
    data = frappe.db.get_value("Customer", customer, fields, as_dict=True)
    if data and _has_field("Customer", "custom_customer_code") and not data.get("custom_customer_code"):
        data.custom_customer_code = _ensure_customer_code(customer)
    return data


def _create_customer_address(customer, values):
    values = frappe._dict(values or {})
    address_line1 = (values.get("address_line1") or "").strip()
    city = (values.get("city") or "").strip()
    if not address_line1:
        return None
    if not city:
        frappe.throw(_("City is required when adding an address."))

    delivery_zone = (values.get("delivery_zone") or "").strip()
    if cint(values.get("require_delivery_zone")) and not delivery_zone:
        frappe.throw(_("Delivery Zone is required for Home Delivery."))
    if delivery_zone and not frappe.db.exists("Delivery Zone", delivery_zone):
        frappe.throw(_("Delivery Zone {0} was not found.").format(delivery_zone))

    customer_name = frappe.db.get_value("Customer", customer, "customer_name") or customer
    address = frappe.new_doc("Address")
    address.address_title = (values.get("address_title") or customer_name or customer).strip()
    address.address_type = values.get("address_type") or "Shipping"
    address.address_line1 = address_line1
    address.address_line2 = (values.get("address_line2") or "").strip()
    address.city = city
    address.state = (values.get("state") or "").strip()
    address.pincode = (values.get("pincode") or "").strip()
    address.phone = (values.get("phone") or "").strip()
    address.country = (
        values.get("country")
        or frappe.db.get_single_value("Global Defaults", "country")
        or "Egypt"
    )
    address.is_shipping_address = 1
    address.is_primary_address = 0 if frappe.db.exists("Dynamic Link", {
        "parenttype": "Address", "link_doctype": "Customer", "link_name": customer
    }) else 1
    if delivery_zone and _has_field("Address", "custom_delivery_zone"):
        address.custom_delivery_zone = delivery_zone
    address.append("links", {"link_doctype": "Customer", "link_name": customer})
    address.insert(ignore_permissions=True)
    return address.name

def _contract_discount_map(contract_doc):
    discounts = {}

    for _, value in contract_doc.as_dict().items():
        if not isinstance(value, list):
            continue

        for row in value:
            if not isinstance(row, dict):
                continue

            origin = (row.get("origin") or "").strip().lower()
            if not origin:
                continue

            discount = (
                row.get("discount")
                or row.get("discount_percentage")
                or row.get("discount_percent")
                or row.get("percentage")
                or 0
            )
            discounts[origin] = flt(discount)

    return discounts


def _get_available_batches(item_code, warehouse):
    """Return non-expired batches with positive stock in the warehouse (FEFO)."""
    if not item_code or not warehouse:
        return []

    from erpnext.stock.doctype.batch.batch import get_batch_qty

    rows = get_batch_qty(item_code=item_code, warehouse=warehouse) or []
    today = getdate(nowdate())
    batches = []

    for row in rows:
        row = frappe._dict(row)
        batch_no = row.get("batch_no") or row.get("name")
        qty = flt(row.get("qty"))

        if not batch_no or qty <= 0:
            continue

        expiry_date = row.get("expiry_date") or frappe.db.get_value(
            "Batch", batch_no, "expiry_date"
        )

        if expiry_date and getdate(expiry_date) < today:
            continue

        batches.append(
            frappe._dict(
                {
                    "name": batch_no,
                    "batch_no": batch_no,
                    "expiry_date": expiry_date,
                    "qty": qty,
                }
            )
        )

    batches.sort(
        key=lambda batch: (
            getdate(batch.expiry_date)
            if batch.expiry_date
            else getdate("9999-12-31"),
            batch.name,
        )
    )
    return batches


def _allocate_batches(item_code, warehouse, required_qty, preferred_batch=None):
    required_qty = flt(required_qty, 6)
    if required_qty <= 0:
        return []

    batches = _get_available_batches(item_code, warehouse)
    total_available = flt(sum(flt(batch.qty) for batch in batches), 6)

    if total_available + 1e-9 < required_qty:
        frappe.throw(
            _(
                "Insufficient batch stock for item {0} in warehouse {1}. "
                "Required: {2}, available: {3}."
            ).format(item_code, warehouse, required_qty, total_available)
        )

    ordered = []
    if preferred_batch:
        preferred = next(
            (batch for batch in batches if batch.name == preferred_batch), None
        )
        if preferred:
            ordered.append(preferred)

    ordered.extend(batch for batch in batches if batch.name != preferred_batch)

    remaining = required_qty
    allocations = []

    for batch in ordered:
        if remaining <= 1e-9:
            break

        allocated_qty = min(flt(batch.qty), remaining)
        if allocated_qty <= 0:
            continue

        allocations.append(
            frappe._dict({"batch_no": batch.name, "qty": flt(allocated_qty, 6)})
        )
        remaining = flt(remaining - allocated_qty, 6)

    if remaining > 1e-9:
        frappe.throw(_("Unable to allocate batch stock for item {0}.").format(item_code))

    return allocations


def _item_context(item_code, warehouse=None):
    fields = ["name", "item_code", "item_name", "stock_uom", "has_batch_no", "image"]

    for fieldname in [
        "custom_customer_price",
        "custom_item_origin",
        "custom_pack_size",
        "custom_box_only",
        "custom_item_name_ar",
        "custom_search_keywords",
        "custom_dosage_form",
        "dosage_form",
    ]:
        if _has_field("Item", fieldname):
            fields.append(fieldname)

    item = frappe.db.get_value("Item", item_code, fields, as_dict=True)
    if not item:
        frappe.throw(_("Item {0} was not found.").format(item_code))

    item.batches = []

    if cint(item.has_batch_no) and warehouse:
        item.batches = _get_available_batches(item_code, warehouse)
        item.actual_qty = flt(sum(flt(batch.qty) for batch in item.batches), 6)
    elif warehouse:
        item.actual_qty = flt(
            frappe.db.get_value(
                "Bin",
                {"item_code": item_code, "warehouse": warehouse},
                "actual_qty",
            )
            or 0
        )
    else:
        item.actual_qty = flt(
            frappe.db.sql(
                """
                SELECT COALESCE(SUM(actual_qty), 0)
                FROM `tabBin`
                WHERE item_code = %s
                """,
                item_code,
            )[0][0]
        )

    item.ingredient_summary = _item_ingredient_summary(item_code)
    return item


def _mode_of_payment_account(mode_of_payment, company):
    if not mode_of_payment or not company:
        return None

    return frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account",
    )


def _resolve_card_terminal(terminal, company):
    filters = {"company": company, "enabled": 1}
    if terminal:
        filters["name"] = terminal
    rows = frappe.get_all("Card POS Terminal", filters=filters, fields=["name", "terminal_name", "bank_label", "clearing_account", "destination_bank_account"], order_by="terminal_name asc", limit_page_length=100)
    if terminal and not rows:
        frappe.throw(_("Invalid or disabled Card POS Terminal: {0}").format(terminal))
    if not terminal:
        if len(rows) == 1:
            return frappe._dict(rows[0])
        if not rows:
            frappe.throw(_("No enabled Card POS Terminal is configured."))
        frappe.throw(_("Select the Card POS Terminal for Credit Card payment."))
    return frappe._dict(rows[0])


def _get_loyalty_context(customer, company):
    result = frappe._dict(
        {
            "program": "",
            "available_points": 0,
            "conversion_factor": 0,
            "available_amount": 0,
            "expense_account": "",
            "cost_center": "",
        }
    )

    if not customer or not frappe.db.exists("DocType", "Loyalty Point Entry"):
        return result

    # The configured default POS customer represents anonymous walk-in sales.
    # Loyalty belongs to identified customers only.
    if _is_default_pos_customer(customer):
        return result

    loyalty_program = ""
    if _has_field("Customer", "loyalty_program"):
        loyalty_program = frappe.db.get_value("Customer", customer, "loyalty_program") or ""

    if not loyalty_program:
        return result

    points = flt(
        frappe.db.sql(
            """
            SELECT COALESCE(SUM(loyalty_points), 0)
            FROM `tabLoyalty Point Entry`
            WHERE customer = %(customer)s
              AND (%(company)s = '' OR company = %(company)s)
              AND (expiry_date IS NULL OR expiry_date >= CURDATE())
            """,
            {"customer": customer, "company": company or ""},
        )[0][0]
    )

    factor = 0
    try:
        from erpnext.accounts.doctype.loyalty_program.loyalty_program import (
            get_redeemption_factor,
        )

        factor = flt(
            get_redeemption_factor(
                loyalty_program=loyalty_program,
                customer=customer,
            )
        )
    except Exception:
        for fieldname in ["conversion_factor", "redemption_factor"]:
            if _has_field("Loyalty Program", fieldname):
                factor = flt(
                    frappe.db.get_value("Loyalty Program", loyalty_program, fieldname)
                    or 0
                )
                if factor:
                    break

    expense_account = ""
    cost_center = ""
    if _has_field("Loyalty Program", "expense_account"):
        expense_account = (
            frappe.db.get_value("Loyalty Program", loyalty_program, "expense_account")
            or ""
        )
    if _has_field("Loyalty Program", "cost_center"):
        cost_center = (
            frappe.db.get_value("Loyalty Program", loyalty_program, "cost_center")
            or ""
        )

    # Use the Company's Default Cost Center when the Loyalty Program
    # does not have a dedicated Redemption Cost Center.
    if not cost_center:
        cost_center = _company_cost_center(company)

    result.update(
        {
            "program": loyalty_program,
            "available_points": points,
            "conversion_factor": factor,
            "available_amount": flt(points * factor, 6),
            "expense_account": expense_account,
            "cost_center": cost_center,
        }
    )
    return result


def _get_customer_advances(customer, company, limit=50):
    if not customer:
        return []

    return frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.posting_date,
            pe.unallocated_amount AS available_amount,
            pe.paid_amount,
            pe.mode_of_payment,
            pe.remarks
        FROM `tabPayment Entry` pe
        WHERE pe.docstatus = 1
          AND pe.party_type = 'Customer'
          AND pe.party = %(customer)s
          AND pe.payment_type = 'Receive'
          AND pe.company = %(company)s
          AND pe.unallocated_amount > 0
        ORDER BY pe.posting_date ASC, pe.creation ASC
        LIMIT %(limit)s
        """,
        {"customer": customer, "company": company, "limit": _safe_limit(limit, 50, 200)},
        as_dict=True,
    )


def _get_customer_credits(customer, company, limit=50):
    if not customer:
        return []

    return frappe.db.sql(
        """
        SELECT
            si.name,
            si.posting_date,
            ABS(si.outstanding_amount) AS available_amount,
            si.grand_total,
            si.remarks
        FROM `tabSales Invoice` si
        WHERE si.docstatus = 1
          AND si.is_return = 1
          AND si.customer = %(customer)s
          AND si.company = %(company)s
          AND si.outstanding_amount < 0
        ORDER BY si.posting_date ASC, si.creation ASC
        LIMIT %(limit)s
        """,
        {"customer": customer, "company": company, "limit": _safe_limit(limit, 50, 200)},
        as_dict=True,
    )


def _append_advance(doc, allocation):
    allocation = frappe._dict(allocation or {})
    reference_type = allocation.get("reference_type")
    reference_name = allocation.get("reference_name")
    allocated_amount = flt(allocation.get("allocated_amount"))

    if not reference_type or not reference_name or allocated_amount <= 0:
        return

    if reference_type == "Payment Entry":
        source = frappe.db.get_value(
            "Payment Entry",
            reference_name,
            ["unallocated_amount", "paid_amount", "remarks", "docstatus", "party"],
            as_dict=True,
        )
        if not source or source.docstatus != 1 or source.party != doc.customer:
            frappe.throw(_("Invalid Payment Entry advance {0}.").format(reference_name))
        available_amount = flt(source.unallocated_amount)
        remarks = source.remarks or ""

        # IMPORTANT:
        # ERPNext validates the value pulled into Sales Invoice Advance against
        # the Payment Entry's CURRENT unallocated_amount.  Using paid_amount
        # here fails as soon as the same Payment Entry was partially consumed
        # before (for example: paid 1000, remaining unallocated 800).
        # The advance row must therefore carry the current available balance.
        advance_amount = available_amount
    elif reference_type == "Sales Invoice":
        source = frappe.db.get_value(
            "Sales Invoice",
            reference_name,
            ["outstanding_amount", "grand_total", "remarks", "docstatus", "customer", "is_return"],
            as_dict=True,
        )
        if (
            not source
            or source.docstatus != 1
            or source.customer != doc.customer
            or not cint(source.is_return)
        ):
            frappe.throw(_("Invalid Customer Credit {0}.").format(reference_name))
        available_amount = abs(flt(source.outstanding_amount))
        remarks = source.remarks or ""
        advance_amount = abs(flt(source.grand_total or available_amount))
    else:
        frappe.throw(_("Unsupported advance reference type {0}.").format(reference_type))

    if allocated_amount - available_amount > 1e-9:
        frappe.throw(
            _("Allocated amount exceeds the available amount for {0}.").format(reference_name)
        )

    row = doc.append("advances", {})
    row.reference_type = reference_type
    row.reference_name = reference_name
    row.remarks = remarks
    row.advance_amount = advance_amount
    row.allocated_amount = allocated_amount
    row.ref_exchange_rate = 1


def _apply_native_payment_entry_advances(doc, allocations):
    """Attach selected Payment Entry advances using ERPNext's own fetch logic.

    This intentionally avoids constructing Sales Invoice Advance rows by hand.
    ERPNext fills reference_row, account, exchange rate and the exact fresh
    advance_amount that its submit-time validation expects.
    """
    allocations = [frappe._dict(row or {}) for row in (allocations or [])]
    allocations = [
        row for row in allocations
        if row.get("reference_type") == "Payment Entry"
        and row.get("reference_name")
        and flt(row.get("allocated_amount")) > 0
    ]

    if not allocations:
        doc.set("advances", [])
        return

    # Fetch the same rows ERPNext itself shows through "Get Advances Received".
    doc.set("advances", [])
    doc.set_advances()
    fetched_rows = list(doc.get("advances") or [])

    selected_rows = []
    used_row_names = set()

    for requested in allocations:
        reference_name = requested.get("reference_name")
        requested_amount = flt(requested.get("allocated_amount"), 6)
        requested_reference_row = requested.get("reference_row") or ""

        candidates = [
            row for row in fetched_rows
            if row.reference_type == "Payment Entry"
            and row.reference_name == reference_name
            and row.name not in used_row_names
        ]

        # Prefer an exact Payment Entry Reference row when the client supplied it.
        if requested_reference_row:
            exact = [row for row in candidates if (row.reference_row or "") == requested_reference_row]
            if exact:
                candidates = exact
        else:
            # Add Balance entries are normally unallocated Payment Entries, so
            # prefer the native row with an empty reference_row.
            unallocated = [row for row in candidates if not row.reference_row]
            if unallocated:
                candidates = unallocated

        if not candidates:
            frappe.throw(
                _("Advance {0} is no longer available for this customer. Reopen Payment and select it again.").format(
                    reference_name
                )
            )

        row = candidates[0]
        available_amount = flt(row.advance_amount, 6)
        if requested_amount - available_amount > 1e-9:
            frappe.throw(
                _("Advance {0} changed. Available now: {1}, requested: {2}. Reopen Payment and try again.").format(
                    reference_name,
                    available_amount,
                    requested_amount,
                )
            )

        row.allocated_amount = requested_amount
        selected_rows.append(row)
        used_row_names.add(row.name)

    doc.set("advances", selected_rows)
    doc.set_advance_gain_or_loss()


# =====================================================
# Settings / searches
# =====================================================


def _open_shift_for_pos(company=None):
    company = company or _company()
    state_field = "custom_shift_operational_status"
    fields = [
        "name",
        "status",
        "end_time",
        "cashier",
        "owner",
        "start_time",
        "creation",
    ]

    if frappe.get_meta(
        "Pharmacy Shift Closing"
    ).has_field(state_field):
        fields.append(state_field)

    rows = frappe.get_all(
        "Pharmacy Shift Closing",
        filters={
            "company": company,
            "docstatus": 0,
        },
        fields=fields,
        order_by="creation desc",
        limit_page_length=100,
    )

    active = []

    for row in rows:
        state = str(
            row.get(state_field) or ""
        ).strip()

        if state in ("Under Review", "Closed"):
            continue
        if row.status == "Closed" or row.end_time:
            continue

        active.append(row)

    for row in active:
        if (
            row.cashier == frappe.session.user
            or row.owner == frappe.session.user
        ):
            return row

    return active[0] if active else None


def _require_open_shift_for_pos(company=None):
    shift = _open_shift_for_pos(company)
    if not shift:
        frappe.throw(
            _(
                "لا يمكن تسجيل أو اعتماد فاتورة من Pharmacy POS بدون وردية مفتوحة. افتح وردية من صفحة إدارة الوردية أولًا."
            ),
            title=_("لا توجد وردية مفتوحة"),
        )
    return shift


@frappe.whitelist()
def get_settings():
    settings = _get_settings()
    company = _company()
    open_shift = _open_shift_for_pos(company)

    return {
        "default_warehouse": settings.get("default_warehouse") or "",
        "default_price_list": settings.get("default_price_list") or "",
        "default_customer": settings.get("default_customer") or "",
        "search_limit": _safe_limit(settings.get("search_limit"), 20, 100),
        "enable_fuzzy_search": cint(settings.get("enable_fuzzy_search")),
        "auto_batch_selection": cint(settings.get("auto_batch_selection", 1)),
        "auto_focus_search": cint(settings.get("auto_focus_search", 1)),
        "default_mode_of_payment": settings.get("default_mode_of_payment") or "Cash",
        "company": company,
        "has_open_shift": 1 if open_shift else 0,
        "open_shift": open_shift.name if open_shift else "",
        "open_shift_cashier": open_shift.cashier if open_shift else "",
        "default_cost_center": _company_cost_center(company),
        "quick_cash_default": cint(settings.get("quick_cash_default", 1)) if settings.get("quick_cash_default") is not None else 1,
        "delivery_fee_item": settings.get("delivery_fee_item") or "",
        "default_print_format": settings.get("default_print_format") or "",
        "auto_print_after_submit": cint(settings.get("auto_print_after_submit")),
        "default_print_copies": max(1, cint(settings.get("default_print_copies")) or 1),
        "enable_reprint": cint(settings.get("enable_reprint", 1)) if settings.get("enable_reprint") is not None else 1,
        "receipt_paper_width": settings.get("receipt_paper_width") or "80 mm",
    }

@frappe.whitelist()
def search_items(txt="", warehouse=None):
    raw, like_txt, compact_txt = _search_pattern(txt)
    if not raw:
        return []

    settings = _get_settings()
    warehouse = warehouse or settings.get("default_warehouse") or ""
    limit = _safe_limit(settings.get("search_limit"), 20, 100)

    customer_price_sql = "i.custom_customer_price" if _has_field("Item", "custom_customer_price") else "0"
    origin_sql = "i.custom_item_origin" if _has_field("Item", "custom_item_origin") else "''"
    pack_size_sql = "i.custom_pack_size" if _has_field("Item", "custom_pack_size") else "1"
    box_only_sql = "i.custom_box_only" if _has_field("Item", "custom_box_only") else "0"
    arabic_sql = "i.custom_item_name_ar" if _has_field("Item", "custom_item_name_ar") else "''"
    keywords_sql = "i.custom_search_keywords" if _has_field("Item", "custom_search_keywords") else "''"

    child_enabled = (
        frappe.db.exists("DocType", "Item Active Ingredient")
        and _has_field("Item", "custom_active_ingredients")
        and _has_field("Item Active Ingredient", "active_ingredient")
    )
    if child_enabled:
        child_join = """
        LEFT JOIN `tabItem Active Ingredient` iai
            ON iai.parent = i.name
            AND iai.parenttype = 'Item'
            AND iai.parentfield = 'custom_active_ingredients'
        """
        if frappe.db.exists("DocType", "Active Ingredient"):
            master_join = "LEFT JOIN `tabActive Ingredient` ai ON ai.name = iai.active_ingredient"
            ingredient_name_sql = (
                "COALESCE(NULLIF(ai.ingredient_name, ''), iai.active_ingredient)"
                if _has_field("Active Ingredient", "ingredient_name")
                else "iai.active_ingredient"
            )
        else:
            master_join = ""
            ingredient_name_sql = "iai.active_ingredient"
        strength_sql = "iai.strength" if _has_field("Item Active Ingredient", "strength") else "0"
        uom_sql = "iai.strength_uom" if _has_field("Item Active Ingredient", "strength_uom") else "''"
        ingredient_search_sql = f"""
            OR IFNULL(iai.active_ingredient, '') LIKE %(like_txt)s
            OR IFNULL({ingredient_name_sql}, '') LIKE %(like_txt)s
            OR REPLACE(REPLACE(LOWER(IFNULL({ingredient_name_sql}, '')), ' ', ''), '-', '') LIKE %(compact_like)s
        """
        ingredient_summary_sql = f"""
            GROUP_CONCAT(
                DISTINCT CONCAT(
                    {ingredient_name_sql},
                    CASE WHEN IFNULL({strength_sql}, 0) > 0
                        THEN CONCAT(' ', CAST({strength_sql} AS CHAR),
                            CASE WHEN IFNULL({uom_sql}, '') != '' THEN CONCAT(' ', {uom_sql}) ELSE '' END)
                        ELSE ''
                    END
                )
                ORDER BY iai.idx SEPARATOR ' + '
            )
        """
    else:
        child_join = master_join = ingredient_search_sql = ""
        ingredient_summary_sql = "''"

    return frappe.db.sql(
        f"""
        SELECT
            i.name,
            i.item_code,
            i.item_name,
            {arabic_sql} AS item_name_ar,
            {keywords_sql} AS search_keywords,
            i.image,
            i.stock_uom,
            i.has_batch_no,
            {customer_price_sql} AS customer_price,
            {origin_sql} AS item_origin,
            {pack_size_sql} AS pack_size,
            {box_only_sql} AS box_only,
            COALESCE((
                SELECT SUM(bin.actual_qty)
                FROM `tabBin` bin
                WHERE bin.item_code = i.name
                  AND (%(warehouse)s = '' OR bin.warehouse = %(warehouse)s)
            ), 0) AS actual_qty,
            MAX(ib.barcode) AS barcode,
            {ingredient_summary_sql} AS ingredient_summary
        FROM `tabItem` i
        LEFT JOIN `tabItem Barcode` ib ON ib.parent = i.name
        {child_join}
        {master_join}
        WHERE IFNULL(i.disabled, 0) = 0
          AND IFNULL(i.is_sales_item, 1) = 1
          AND (
              i.name LIKE %(like_txt)s
              OR i.item_code LIKE %(like_txt)s
              OR IFNULL(i.item_name, '') LIKE %(like_txt)s
              OR IFNULL({arabic_sql}, '') LIKE %(like_txt)s
              OR IFNULL({keywords_sql}, '') LIKE %(like_txt)s
              OR IFNULL(ib.barcode, '') LIKE %(like_txt)s
              OR REPLACE(REPLACE(LOWER(IFNULL(i.item_name, '')), ' ', ''), '-', '') LIKE %(compact_like)s
              OR REPLACE(REPLACE(LOWER(IFNULL({arabic_sql}, '')), ' ', ''), '-', '') LIKE %(compact_like)s
              {ingredient_search_sql}
          )
        GROUP BY i.name
        ORDER BY
            MAX(CASE WHEN ib.barcode = %(raw)s THEN 0 ELSE 1 END),
            CASE WHEN i.item_code = %(raw)s THEN 0 ELSE 1 END,
            CASE WHEN LOWER(i.item_name) = LOWER(%(raw)s) THEN 0 ELSE 1 END,
            CASE WHEN LOWER(IFNULL({arabic_sql}, '')) = LOWER(%(raw)s) THEN 0 ELSE 1 END,
            CASE WHEN i.item_code LIKE %(starts)s THEN 0 ELSE 1 END,
            CASE WHEN i.item_name LIKE %(starts)s THEN 0 ELSE 1 END,
            i.item_name ASC,
            i.name ASC
        LIMIT %(limit)s
        """,
        {
            "raw": raw,
            "like_txt": like_txt,
            "compact_like": f"%{compact_txt}%",
            "starts": f"{raw}%",
            "warehouse": warehouse,
            "limit": limit,
        },
        as_dict=True,
    )

@frappe.whitelist()
def get_item(item_code, warehouse=None):
    if not item_code:
        return None

    settings = _get_settings()
    warehouse = warehouse or settings.get("default_warehouse") or ""
    return _item_context(item_code, warehouse)


@frappe.whitelist()
def search_customer(txt=""):
    """Normal customers only. Search by code, name, mobile, or ERPNext ID."""
    txt = (txt or "").strip()
    settings = _get_settings()
    limit = _safe_limit(settings.get("search_limit"), 20, 100)
    code_select = "c.custom_customer_code" if _has_field("Customer", "custom_customer_code") else "''"
    code_search = "OR IFNULL(c.custom_customer_code, '') LIKE %(like_txt)s" if _has_field("Customer", "custom_customer_code") else ""

    return frappe.db.sql(
        f"""
        SELECT
            c.name,
            c.customer_name,
            c.mobile_no,
            c.customer_type,
            {code_select} AS custom_customer_code
        FROM `tabCustomer` c
        WHERE IFNULL(c.disabled, 0) = 0
          AND (
              %(txt)s = ''
              OR c.name LIKE %(like_txt)s
              OR IFNULL(c.customer_name, '') LIKE %(like_txt)s
              OR IFNULL(c.mobile_no, '') LIKE %(like_txt)s
              {code_search}
          )
          AND NOT EXISTS (
              SELECT 1 FROM `tabPharmacy Contract` pc WHERE pc.customer = c.name
          )
          AND NOT EXISTS (
              SELECT 1 FROM `tabContract Beneficiary` cb WHERE cb.customer = c.name
          )
        ORDER BY
            CASE WHEN {code_select} = %(txt)s THEN 0 ELSE 1 END,
            CASE WHEN c.mobile_no = %(txt)s THEN 0 ELSE 1 END,
            CASE WHEN c.name = %(txt)s THEN 0 ELSE 1 END,
            CASE WHEN %(txt)s = '' THEN c.modified END DESC,
            c.customer_name ASC,
            c.name ASC
        LIMIT %(limit)s
        """,
        {"txt": txt, "like_txt": f"%{txt}%", "limit": limit},
        as_dict=True,
    )


@frappe.whitelist()
def get_customer_by_code(customer_code):
    raw_code = (customer_code or "").strip()
    normalized_code = _normalize_customer_code(raw_code)
    if not raw_code or not _has_field("Customer", "custom_customer_code"):
        return None

    customer = frappe.db.get_value(
        "Customer",
        {
            "custom_customer_code": ["in", list(dict.fromkeys([raw_code, normalized_code]))],
            "disabled": 0,
        },
        "name",
    )
    return _customer_result(customer)


@frappe.whitelist()
def ensure_customer_code(customer):
    if not customer:
        return None
    return {"customer": customer, "customer_code": _ensure_customer_code(customer)}


@frappe.whitelist()
def create_pos_customer(data):
    _assert_pos_customer_create_permission()
    if isinstance(data, str):
        data = json.loads(data)
    data = frappe._dict(data or {})

    customer_name = (data.get("customer_name") or "").strip()
    mobile_no = (data.get("mobile_no") or "").strip()
    if not customer_name:
        frappe.throw(_("Customer Name is required."))
    if not mobile_no:
        frappe.throw(_("Mobile Number is required to prevent duplicate customers."))

    existing = frappe.db.get_value("Customer", {"mobile_no": mobile_no, "disabled": 0}, "name")
    created = 0
    if existing:
        customer_name_id = existing
    else:
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Individual"
        customer.mobile_no = mobile_no

        selling_settings = frappe.get_cached_doc("Selling Settings")
        if _has_field("Customer", "customer_group") and selling_settings.get("customer_group"):
            customer.customer_group = selling_settings.get("customer_group")
        if _has_field("Customer", "territory") and selling_settings.get("territory"):
            customer.territory = selling_settings.get("territory")

        customer.insert(ignore_permissions=True)
        customer_name_id = customer.name
        created = 1

    customer_code = _ensure_customer_code(customer_name_id)
    address_name = None
    if data.get("address_line1"):
        address_name = _create_customer_address(customer_name_id, data)

    return {
        "success": True,
        "created": created,
        "customer": _customer_result(customer_name_id),
        "customer_code": customer_code,
        "address": address_name,
        "addresses": get_customer_addresses(customer_name_id),
    }


@frappe.whitelist()
def add_pos_customer_address(data):
    _assert_pos_customer_create_permission()
    if isinstance(data, str):
        data = json.loads(data)
    data = frappe._dict(data or {})
    customer = data.get("customer")
    if not customer or not frappe.db.exists("Customer", customer):
        frappe.throw(_("Select a valid Customer."))
    address_name = _create_customer_address(customer, data)
    if not address_name:
        frappe.throw(_("Address Line 1 is required."))
    return {
        "success": True,
        "address": address_name,
        "addresses": get_customer_addresses(customer),
    }

@frappe.whitelist()
def search_delivery_employees(txt=""):
    txt = (txt or "").strip()
    limit = _safe_limit(_get_settings().get("search_limit"), 20, 100)

    return frappe.db.sql(
        """
        SELECT
            e.name,
            e.employee_name,
            e.cell_number,
            e.user_id
        FROM `tabEmployee` e
        WHERE e.status = 'Active'
          AND (
              %(txt)s = ''
              OR e.name LIKE %(like_txt)s
              OR IFNULL(e.employee_name, '') LIKE %(like_txt)s
              OR IFNULL(e.cell_number, '') LIKE %(like_txt)s
          )
        ORDER BY e.employee_name ASC, e.name ASC
        LIMIT %(limit)s
        """,
        {"txt": txt, "like_txt": f"%{txt}%", "limit": limit},
        as_dict=True,
    )


@frappe.whitelist()
def search_contracts(txt=""):
    txt = (txt or "").strip()
    limit = _safe_limit(_get_settings().get("search_limit"), 20, 100)
    contract_name_sql = (
        "pc.`contract_name`" if _has_field("Pharmacy Contract", "contract_name") else "''"
    )

    return frappe.db.sql(
        f"""
        SELECT
            pc.name,
            {contract_name_sql} AS contract_name,
            pc.customer,
            c.customer_name,
            pc.billing_type
        FROM `tabPharmacy Contract` pc
        LEFT JOIN `tabCustomer` c ON c.name = pc.customer
        WHERE IFNULL(pc.is_active, 0) = 1
          AND (
              %(txt)s = ''
              OR pc.name LIKE %(like_txt)s
              OR IFNULL({contract_name_sql}, '') LIKE %(like_txt)s
              OR IFNULL(pc.customer, '') LIKE %(like_txt)s
              OR IFNULL(c.customer_name, '') LIKE %(like_txt)s
          )
        ORDER BY COALESCE(NULLIF({contract_name_sql}, ''), c.customer_name, pc.name)
        LIMIT %(limit)s
        """,
        {"txt": txt, "like_txt": f"%{txt}%", "limit": limit},
        as_dict=True,
    )


@frappe.whitelist()
def search_beneficiaries(txt="", pharmacy_contract=None):
    txt = (txt or "").strip()
    pharmacy_contract = pharmacy_contract or ""
    limit = _safe_limit(_get_settings().get("search_limit"), 20, 100)
    card_sql = (
        "cb.`card_number`" if _has_field("Contract Beneficiary", "card_number") else "''"
    )
    external_sql = (
        "cb.`external_id`" if _has_field("Contract Beneficiary", "external_id") else "''"
    )

    return frappe.db.sql(
        f"""
        SELECT
            cb.name,
            cb.customer,
            c.customer_name,
            cb.employee_code,
            cb.pharmacy_contract,
            {card_sql} AS card_number,
            {external_sql} AS external_id,
            cb.expiry_date
        FROM `tabContract Beneficiary` cb
        LEFT JOIN `tabCustomer` c ON c.name = cb.customer
        WHERE IFNULL(cb.is_active, 0) = 1
          AND (%(pharmacy_contract)s = '' OR cb.pharmacy_contract = %(pharmacy_contract)s)
          AND (cb.expiry_date IS NULL OR cb.expiry_date >= CURDATE())
          AND (
              %(txt)s = ''
              OR cb.name LIKE %(like_txt)s
              OR IFNULL(c.customer_name, '') LIKE %(like_txt)s
              OR IFNULL(cb.customer, '') LIKE %(like_txt)s
              OR IFNULL(cb.employee_code, '') LIKE %(like_txt)s
              OR IFNULL({card_sql}, '') LIKE %(like_txt)s
              OR IFNULL({external_sql}, '') LIKE %(like_txt)s
          )
        ORDER BY c.customer_name ASC, cb.employee_code ASC, cb.name ASC
        LIMIT %(limit)s
        """,
        {
            "txt": txt,
            "like_txt": f"%{txt}%",
            "pharmacy_contract": pharmacy_contract,
            "limit": limit,
        },
        as_dict=True,
    )


@frappe.whitelist()
def get_contract_details(pharmacy_contract):
    if not pharmacy_contract:
        return None

    doc = frappe.get_doc("Pharmacy Contract", pharmacy_contract)
    customer_name = (
        frappe.db.get_value("Customer", doc.get("customer"), "customer_name")
        if doc.get("customer")
        else ""
    )
    return {
        "name": doc.name,
        "contract_name": doc.get("contract_name") or doc.name,
        "customer": doc.get("customer"),
        "customer_name": customer_name,
        "billing_type": doc.get("billing_type"),
        "need_prescription": cint(doc.get("need_prescription")),
        "require_employee_code": cint(doc.get("require_employee_code")),
        "is_active": cint(doc.get("is_active")),
        "discounts": _contract_discount_map(doc),
    }


@frappe.whitelist()
def get_beneficiary_details(beneficiary):
    if not beneficiary:
        return None

    fields = [
        "name",
        "customer",
        "pharmacy_contract",
        "employee_code",
        "is_active",
        "expiry_date",
    ]
    for fieldname in ["card_number", "external_id"]:
        if _has_field("Contract Beneficiary", fieldname):
            fields.append(fieldname)

    data = frappe.db.get_value("Contract Beneficiary", beneficiary, fields, as_dict=True)
    if not data:
        return None

    data.customer_name = (
        frappe.db.get_value("Customer", data.customer, "customer_name") if data.customer else ""
    )
    data.mobile_no = (
        frappe.db.get_value("Customer", data.customer, "mobile_no") if data.customer else ""
    )
    return data


@frappe.whitelist()
def get_customer_addresses(customer):
    if not customer:
        return []

    zone_field = _has_field("Address", "custom_delivery_zone")
    zone_exists = frappe.db.exists("DocType", "Delivery Zone")
    zone_select = "a.custom_delivery_zone AS delivery_zone" if zone_field else "'' AS delivery_zone"
    zone_join = "LEFT JOIN `tabDelivery Zone` dz ON dz.name = a.custom_delivery_zone" if zone_field and zone_exists else ""

    def zone_col(fieldname, alias, default="NULL"):
        if zone_field and zone_exists and _has_field("Delivery Zone", fieldname):
            return f"dz.{fieldname} AS {alias}"
        return f"{default} AS {alias}"

    return frappe.db.sql(
        f"""
        SELECT
            a.name,
            a.address_title,
            a.address_type,
            a.address_line1,
            a.address_line2,
            a.city,
            a.state,
            a.pincode,
            a.phone,
            a.is_primary_address,
            a.is_shipping_address,
            {zone_select},
            {zone_col('zone_name', 'zone_name', "''")},
            {zone_col('zone_name_ar', 'zone_name_ar', "''")},
            {zone_col('is_active', 'zone_is_active', '1')},
            {zone_col('warehouse', 'zone_warehouse', "''")},
            {zone_col('delivery_fee', 'delivery_fee', '0')},
            {zone_col('small_order_threshold', 'small_order_threshold', '0')},
            {zone_col('small_order_delivery_fee', 'small_order_delivery_fee', '0')},
            {zone_col('minimum_order_amount', 'minimum_order_amount', '0')},
            {zone_col('free_delivery_above', 'free_delivery_above', '0')},
            {zone_col('estimated_time_mins', 'estimated_time_mins', '0')}
        FROM `tabAddress` a
        INNER JOIN `tabDynamic Link` dl
            ON dl.parent = a.name
            AND dl.parenttype = 'Address'
            AND dl.link_doctype = 'Customer'
            AND dl.link_name = %(customer)s
        {zone_join}
        WHERE IFNULL(a.disabled, 0) = 0
        ORDER BY a.is_shipping_address DESC, a.is_primary_address DESC, a.address_title ASC
        """,
        {"customer": customer},
        as_dict=True,
    )


@frappe.whitelist()
def get_delivery_zone_details(delivery_zone):
    return _delivery_zone_data(delivery_zone)

@frappe.whitelist()
def get_customer_history(customer, limit=10):
    if not customer:
        return []

    fields = ["name", "posting_date", "posting_time", "grand_total", "outstanding_amount", "status", "is_return"]
    if _has_field("Sales Invoice", "custom_order_type"):
        fields.append("custom_order_type")

    return frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer, "docstatus": 1},
        fields=fields,
        order_by="posting_date desc, posting_time desc, creation desc",
        limit=_safe_limit(limit, 20, 100),
    )


@frappe.whitelist()
def get_invoice_history_details(invoice):
    if not invoice:
        return None
    doc = frappe.get_doc("Sales Invoice", invoice)
    if doc.docstatus != 1:
        frappe.throw(_("Select a submitted Sales Invoice."))

    rows = []
    delivery_fee_item = _get_settings().get("delivery_fee_item") or ""
    for item in doc.items:
        if delivery_fee_item and item.item_code == delivery_fee_item:
            continue
        pack_size = flt(item.get("custom_pack_size") or 0)
        if not pack_size:
            pack_size = flt(
                frappe.db.get_value("Item", item.item_code, "custom_pack_size")
                if _has_field("Item", "custom_pack_size")
                else 1
            ) or 1
        box_qty = flt(item.get("custom_box_qty") or 0)
        unit_qty = flt(item.get("custom_unit_qty") or 0)
        if not box_qty and not unit_qty:
            absolute_qty = abs(flt(item.qty))
            box_qty = int(absolute_qty)
            unit_qty = flt((absolute_qty - box_qty) * pack_size, 6)

        returned_qty = abs(
            flt(
                frappe.db.sql(
                    """
                    SELECT COALESCE(SUM(ABS(rii.qty)), 0)
                    FROM `tabSales Invoice Item` rii
                    INNER JOIN `tabSales Invoice` ri ON ri.name = rii.parent
                    WHERE ri.docstatus = 1
                      AND ri.is_return = 1
                      AND ri.return_against = %(invoice)s
                      AND rii.sales_invoice_item = %(source_item)s
                    """,
                    {"invoice": doc.name, "source_item": item.name},
                )[0][0]
            )
        )
        rows.append(
            {
                "source_item": item.name,
                "item_code": item.item_code,
                "item_name": item.item_name,
                "batch_no": item.batch_no or "",
                "qty": flt(item.qty),
                "box_qty": box_qty,
                "unit_qty": unit_qty,
                "pack_size": pack_size,
                "rate": flt(item.rate),
                "discount_percentage": flt(item.discount_percentage),
                "amount": flt(item.amount),
                "returned_qty": returned_qty,
            }
        )

    return {
        "name": doc.name,
        "posting_date": doc.posting_date,
        "customer": doc.customer,
        "customer_name": doc.customer_name,
        "grand_total": doc.grand_total,
        "outstanding_amount": doc.outstanding_amount,
        "status": doc.status,
        "is_return": cint(doc.is_return),
        "delivery_zone": doc.get("custom_delivery_zone") or "",
        "delivery_fee": flt(doc.get("custom_delivery_fee") or 0),
        "delivery_fee_rule": doc.get("custom_delivery_fee_rule") or "",
        "items": rows,
    }


@frappe.whitelist()
def get_customer_purchased_items(customer, days=0, limit=200):
    if not customer:
        return []
    days = cint(days)
    date_condition = ""
    values = {
        "customer": customer,
        "limit": _safe_limit(limit, 100, 500),
        "delivery_fee_item": _get_settings().get("delivery_fee_item") or "",
    }
    if days > 0:
        date_condition = "AND si.posting_date >= DATE_SUB(CURDATE(), INTERVAL %(days)s DAY)"
        values["days"] = days

    pack_sql = (
        "COALESCE(NULLIF(sii.custom_pack_size, 0), NULLIF(i.custom_pack_size, 0), 1)"
        if _has_field("Sales Invoice Item", "custom_pack_size") and _has_field("Item", "custom_pack_size")
        else ("COALESCE(NULLIF(i.custom_pack_size, 0), 1)" if _has_field("Item", "custom_pack_size") else "1")
    )

    rows = frappe.db.sql(
        f"""
        SELECT
            sii.item_code,
            MAX(sii.item_name) AS item_name,
            SUM(sii.qty) AS net_qty,
            MAX({pack_sql}) AS pack_size,
            COUNT(DISTINCT CASE WHEN si.is_return = 0 THEN si.name END) AS purchase_count,
            MAX(CASE WHEN si.is_return = 0 THEN si.posting_date END) AS last_purchase_date,
            CAST(SUBSTRING_INDEX(
                GROUP_CONCAT(
                    CASE WHEN si.is_return = 0 THEN sii.rate END
                    ORDER BY si.posting_date DESC, si.posting_time DESC, si.creation DESC
                    SEPARATOR ','
                ),
                ',',
                1
            ) AS DECIMAL(18, 6)) AS last_rate
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        LEFT JOIN `tabItem` i ON i.name = sii.item_code
        WHERE si.docstatus = 1
          AND si.customer = %(customer)s
          AND (%(delivery_fee_item)s = '' OR sii.item_code != %(delivery_fee_item)s)
          {date_condition}
        GROUP BY sii.item_code
        HAVING SUM(sii.qty) > 0.000001
        ORDER BY last_purchase_date DESC, item_name ASC
        LIMIT %(limit)s
        """,
        values,
        as_dict=True,
    )
    return rows


@frappe.whitelist()
def get_item_movement(item_code, warehouse="", limit=20, offset=0):
    if not item_code:
        return None
    limit = _safe_limit(limit, 20, 100)
    offset = max(0, cint(offset))
    item = _item_context(item_code, warehouse or None)

    warehouses = frappe.get_all(
        "Bin",
        filters={"item_code": item_code, "actual_qty": ("!=", 0)},
        fields=["warehouse", "actual_qty", "reserved_qty", "projected_qty"],
        order_by="actual_qty desc",
        limit=200,
    )
    batches = _get_available_batches(item_code, warehouse) if warehouse else []

    movements = frappe.db.sql(
        """
        SELECT
            name, posting_date, posting_time, voucher_type, voucher_no,
            warehouse, batch_no, actual_qty, qty_after_transaction,
            valuation_rate, stock_value_difference
        FROM `tabStock Ledger Entry`
        WHERE item_code = %(item_code)s
          AND is_cancelled = 0
          AND (%(warehouse)s = '' OR warehouse = %(warehouse)s)
        ORDER BY posting_date DESC, posting_time DESC, creation DESC
        LIMIT %(offset)s, %(limit)s
        """,
        {"item_code": item_code, "warehouse": warehouse or "", "offset": offset, "limit": limit},
        as_dict=True,
    )

    for row in movements:
        row.party_type = ""
        row.party = ""
        row.party_name = ""
        row.description = row.voucher_type
        if row.voucher_type in ("Sales Invoice", "Delivery Note"):
            party = frappe.db.get_value(row.voucher_type, row.voucher_no, ["customer", "customer_name"], as_dict=True)
            if party:
                row.party_type = "Customer"
                row.party = party.get("customer")
                row.party_name = party.get("customer_name") or party.get("customer")
        elif row.voucher_type in ("Purchase Receipt", "Purchase Invoice"):
            party = frappe.db.get_value(row.voucher_type, row.voucher_no, ["supplier", "supplier_name"], as_dict=True)
            if party:
                row.party_type = "Supplier"
                row.party = party.get("supplier")
                row.party_name = party.get("supplier_name") or party.get("supplier")
        elif row.voucher_type == "Stock Entry":
            purpose = frappe.db.get_value("Stock Entry", row.voucher_no, "stock_entry_type")
            row.description = purpose or "Stock Entry"

    last_purchase_rate = frappe.db.sql(
        """
        SELECT pri.rate
        FROM `tabPurchase Receipt Item` pri
        INNER JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
        WHERE pr.docstatus = 1 AND pri.item_code = %s
        ORDER BY pr.posting_date DESC, pr.posting_time DESC, pr.creation DESC
        LIMIT 1
        """,
        item_code,
    )
    last_sales_rate = frappe.db.sql(
        """
        SELECT sii.rate
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1 AND si.is_return = 0 AND sii.item_code = %s
        ORDER BY si.posting_date DESC, si.posting_time DESC, si.creation DESC
        LIMIT 1
        """,
        item_code,
    )

    return {
        "item": item,
        "warehouses": warehouses,
        "batches": batches,
        "movements": movements,
        "offset": offset,
        "has_more": 1 if len(movements) == limit else 0,
        "last_purchase_rate": flt(last_purchase_rate[0][0]) if last_purchase_rate else 0,
        "last_sales_rate": flt(last_sales_rate[0][0]) if last_sales_rate else 0,
        "alternatives": _get_item_alternatives(item_code, warehouse, 20),
    }

@frappe.whitelist()
def get_payment_modes(company=None):
    company = _company(company)
    rows = frappe.get_all(
        "Mode of Payment",
        fields=["name", "type"],
        order_by="name asc",
        limit=200,
    )

    result = []
    for row in rows:
        account = _mode_of_payment_account(row.name, company)
        terminals = []
        if row.name == "Credit Card" and frappe.db.exists("DocType", "Card POS Terminal"):
            terminals = frappe.get_all("Card POS Terminal", filters={"company": company, "enabled": 1}, fields=["name", "terminal_name", "bank_label", "clearing_account"], order_by="bank_label asc, terminal_name asc", limit_page_length=100)
        result.append(
            {
                "name": row.name,
                "type": row.type,
                "account": account or "",
                "configured": 1 if account else 0,
                "terminals": terminals,
            }
        )
    return result


@frappe.whitelist()
def create_customer_balance(data):
    """Create an unallocated customer advance without creating an invoice."""
    if isinstance(data, str):
        data = json.loads(data)

    data = frappe._dict(data or {})
    customer = data.get("customer") or ""
    company = _company(data.get("company"))
    amount = flt(data.get("amount"), 6)
    mode = data.get("mode_of_payment") or ""

    if not customer or not frappe.db.exists("Customer", customer):
        frappe.throw(_("Select a valid customer."))
    if _is_default_pos_customer(customer):
        frappe.throw(
            _("Balance cannot be stored against the anonymous Cash Customer.")
        )
    if amount <= 0:
        frappe.throw(_("Balance amount must be greater than zero."))
    if not mode:
        frappe.throw(_("Mode of Payment is required."))

    allowed_roles = {
        "System Manager",
        "Sales Manager",
        "Accounts Manager",
        "Accounts User",
        "POS User",
        "Sales User",
    }
    if not allowed_roles.intersection(set(frappe.get_roles(frappe.session.user))):
        frappe.throw(_("You are not allowed to add customer balance from Pharmacy POS."))

    payment = frappe._dict(
        {
            "mode_of_payment": mode,
            "amount": amount,
            "reference_no": data.get("reference_no") or "",
            "card_pos_terminal": data.get("card_pos_terminal") or "",
            "remarks": data.get("remarks") or "",
        }
    )
    payment_entry = _create_customer_advance_payment(
        customer,
        company,
        payment,
        source_reference="",
        cost_center=_company_cost_center(company),
    )

    return {
        "success": True,
        "payment_entry": payment_entry,
        "customer": customer,
        "amount": amount,
    }


@frappe.whitelist()
def get_customer_payment_context(customer, company=None):
    company = _company(company)
    loyalty = _get_loyalty_context(customer, company)
    advances = _get_customer_advances(customer, company)
    credits = _get_customer_credits(customer, company)

    return {
        "loyalty": loyalty,
        "advances": advances,
        "credits": credits,
        "advance_total": flt(sum(flt(row.available_amount) for row in advances), 6),
        "credit_total": flt(sum(flt(row.available_amount) for row in credits), 6),
    }


@frappe.whitelist()
def search_held_invoices(limit=50):
    fields = ["name", "modified", "customer", "customer_name", "grand_total", "remarks"]
    if _has_field("Sales Invoice", "custom_order_type"):
        fields.append("custom_order_type")
    return frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 0,
            "owner": frappe.session.user,
            "remarks": ("like", "[PHARMACY_POS_HOLD]%"),
        },
        fields=fields,
        order_by="modified desc",
        limit=_safe_limit(limit, 50, 200),
    )


@frappe.whitelist()
def get_held_invoice(invoice):
    doc = frappe.get_doc("Sales Invoice", invoice)
    if doc.docstatus != 0 or doc.owner != frappe.session.user:
        frappe.throw(_("You cannot recall this invoice."))

    customer = frappe.db.get_value("Customer", doc.customer, ["name", "customer_name", "mobile_no"], as_dict=True)
    items = []
    delivery_fee_item = _get_settings().get("delivery_fee_item") or ""
    for row in doc.items:
        if delivery_fee_item and row.item_code == delivery_fee_item:
            continue
        pack_size = flt(row.get("custom_pack_size") or 1) or 1
        box_qty = flt(row.get("custom_box_qty") or 0)
        unit_qty = flt(row.get("custom_unit_qty") or 0)
        if not box_qty and not unit_qty:
            box_qty = int(flt(row.qty))
            unit_qty = flt((flt(row.qty) - box_qty) * pack_size, 6)
        context = _item_context(row.item_code, row.warehouse or doc.set_warehouse)
        items.append(
            {
                "item_code": row.item_code,
                "item_name": row.item_name,
                "item_name_ar": context.get("custom_item_name_ar") or "",
                "ingredient_summary": context.get("ingredient_summary") or "",
                "image": context.get("image") or "",
                "stock_uom": row.stock_uom,
                "actual_qty": context.actual_qty,
                "has_batch_no": context.has_batch_no,
                "batches": context.batches,
                "batch_no": row.batch_no or "",
                "pack_size": pack_size,
                "box_only": cint(context.get("custom_box_only")),
                "item_origin": context.get("custom_item_origin") or "",
                "customer_price": flt(row.price_list_rate or row.rate),
                "price_list_rate": flt(row.price_list_rate or row.rate),
                "discount_percentage": flt(row.discount_percentage),
                "rate": flt(row.rate),
                "box_qty": box_qty,
                "unit_qty": unit_qty,
                "qty": flt(row.qty),
                "total": flt(row.amount),
            }
        )

    return {
        "name": doc.name,
        "order_type": doc.get("custom_order_type") or "Walk In",
        "customer": customer,
        "customer_address": doc.customer_address or "",
        "delivery_zone": doc.get("custom_delivery_zone") or "",
        "pharmacy_contract": doc.get("custom_pharmacy_contract") or "",
        "contract_beneficiary": doc.get("custom_contract_beneficiary") or "",
        "delivery_boy": doc.get("custom_delivery_boy") or doc.get("delivery_boy") or "",
        "payments": [
            {"mode_of_payment": row.mode_of_payment, "amount": flt(row.amount)} for row in doc.payments
        ],
        "loyalty_redemption": {
            "points": flt(doc.loyalty_points),
            "amount": flt(doc.loyalty_amount),
        },
        "items": items,
    }

# =====================================================
# Add-on Delivery Orders
# =====================================================


ADD_ON_CHECK_FIELD = "custom_add_on_delivery_invoice"
ADD_ON_PARENT_FIELD = "custom_parent_delivery_invoice"


def _require_add_on_fields():
    missing = [
        fieldname
        for fieldname in (ADD_ON_CHECK_FIELD, ADD_ON_PARENT_FIELD)
        if not _has_field("Sales Invoice", fieldname)
    ]
    if missing:
        frappe.throw(
            _("Create the following Sales Invoice custom fields before using Add-on mode: {0}").format(
                ", ".join(missing)
            )
        )


def _get_root_delivery_invoice(invoice_name):
    if not invoice_name:
        frappe.throw(_("Parent Delivery Invoice is required."))

    _require_add_on_fields()
    doc = frappe.get_doc("Sales Invoice", invoice_name)

    if cint(doc.get(ADD_ON_CHECK_FIELD)) and doc.get(ADD_ON_PARENT_FIELD):
        doc = frappe.get_doc("Sales Invoice", doc.get(ADD_ON_PARENT_FIELD))

    if doc.docstatus != 1:
        frappe.throw(
            _("Parent Delivery Invoice {0} must be submitted.").format(doc.name)
        )
    if cint(doc.get("is_return")):
        frappe.throw(_("A return invoice cannot be used as a Delivery Add-on parent."))
    if (doc.get("custom_order_type") or "") != "Home Delivery":
        frappe.throw(_("Parent invoice must be a Home Delivery invoice."))
    delivery_status = doc.get("custom_delivery_status") or ""
    add_on_status = doc.get("custom_add_on_order_status") or ""
    if delivery_status == "Delivered":
        frappe.throw(_("You cannot add items after the delivery has been completed."))
    if delivery_status == "Out for Delivery" or add_on_status == "Driver Returning":
        frappe.throw(
            _("The delivery boy must return to the pharmacy before creating the Add-on invoice.")
        )

    return doc


def _get_delivery_group_rows(parent_invoice, include_drafts=True):
    rows = [
        frappe._dict(
            {
                "name": parent_invoice.name,
                "docstatus": parent_invoice.docstatus,
                "grand_total": flt(parent_invoice.grand_total),
                "outstanding_amount": flt(parent_invoice.outstanding_amount),
            }
        )
    ]

    if not _has_field("Sales Invoice", ADD_ON_PARENT_FIELD):
        return rows

    filters = {
        ADD_ON_PARENT_FIELD: parent_invoice.name,
        "is_return": 0,
    }
    filters["docstatus"] = ["in", [0, 1]] if include_drafts else 1

    rows.extend(
        frappe.get_all(
            "Sales Invoice",
            filters=filters,
            fields=["name", "docstatus", "grand_total", "outstanding_amount"],
            order_by="creation asc",
            limit_page_length=200,
        )
    )
    return rows


def _get_submitted_delivery_group_docs(source):
    """Return the operational parent followed by submitted Add-on invoices.

    Unlike ``_get_root_delivery_invoice`` this helper is intentionally safe for
    delivered / returning orders and does not apply Add-on creation rules.  It
    is used by Sales Return so the whole customer order is treated as one
    operational group while ERPNext still receives one Credit Note per source
    Sales Invoice.
    """
    if isinstance(source, str):
        source = frappe.get_doc("Sales Invoice", source)

    parent = source
    if (
        _has_field("Sales Invoice", ADD_ON_PARENT_FIELD)
        and str(source.get(ADD_ON_PARENT_FIELD) or "").strip()
    ):
        parent_name = str(source.get(ADD_ON_PARENT_FIELD) or "").strip()
        if frappe.db.exists("Sales Invoice", parent_name):
            parent = frappe.get_doc("Sales Invoice", parent_name)

    docs = [parent]
    if not _has_field("Sales Invoice", ADD_ON_PARENT_FIELD):
        return parent, docs

    names = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "is_return": 0,
            ADD_ON_PARENT_FIELD: parent.name,
        },
        pluck="name",
        order_by="creation asc",
        limit_page_length=500,
    )
    for name in names:
        doc = frappe.get_doc("Sales Invoice", name)
        if doc.company != parent.company or doc.customer != parent.customer:
            frappe.throw(
                _("Add-on invoice {0} does not belong to the same company and customer.").format(name)
            )
        docs.append(doc)
    return parent, docs


@frappe.whitelist()
def get_add_on_context(parent_invoice):
    parent = _get_root_delivery_invoice(parent_invoice)

    customer_fields = ["name", "customer_name", "mobile_no"]
    if _has_field("Customer", "custom_customer_code"):
        customer_fields.append("custom_customer_code")
    customer = frappe.db.get_value(
        "Customer",
        parent.customer,
        customer_fields,
        as_dict=True,
    )

    delivery_boy_name = parent.get("custom_delivery_boy") or parent.get("delivery_boy") or ""
    delivery_boy = None
    if delivery_boy_name and frappe.db.exists("Employee", delivery_boy_name):
        delivery_boy = frappe.db.get_value(
            "Employee",
            delivery_boy_name,
            ["name", "employee_name", "cell_number", "user_id"],
            as_dict=True,
        )

    group_rows = _get_delivery_group_rows(parent, include_drafts=False)
    add_on_rows = [row for row in group_rows if row.name != parent.name]

    return {
        "parent_invoice": parent.name,
        "parent_status": parent.get("custom_delivery_status") or "",
        "parent_grand_total": flt(parent.grand_total),
        "parent_outstanding_amount": flt(parent.outstanding_amount),
        "group_grand_total": flt(sum(flt(row.grand_total) for row in group_rows), 6),
        "group_outstanding_amount": flt(
            sum(flt(row.outstanding_amount) for row in group_rows), 6
        ),
        "existing_add_on_count": len(add_on_rows),
        "existing_add_on_invoices": [row.name for row in add_on_rows],
        "company": parent.company,
        "warehouse": parent.set_warehouse or "",
        "price_list": parent.selling_price_list or "",
        "customer": customer,
        "customer_address": parent.customer_address or parent.shipping_address_name or "",
        "delivery_zone": parent.get("custom_delivery_zone") or "",
        "delivery_boy": delivery_boy,
    }


# =====================================================
# Invoice creation
# =====================================================


def _prepare_invoice_context(data):
    settings = _get_settings()
    is_add_on = cint(data.get("is_add_on_delivery_invoice"))
    parent_invoice = None
    inherited_delivery_boy = ""

    if is_add_on:
        parent_invoice = _get_root_delivery_invoice(
            data.get("parent_delivery_invoice")
        )
        company = parent_invoice.company
        order_type = "Home Delivery"
        warehouse = (
            parent_invoice.set_warehouse
            or data.get("warehouse")
            or settings.get("default_warehouse")
            or ""
        )
        price_list = (
            parent_invoice.selling_price_list
            or data.get("price_list")
            or settings.get("default_price_list")
            or ""
        )
        customer = parent_invoice.customer
        customer_address = (
            parent_invoice.customer_address
            or parent_invoice.shipping_address_name
            or ""
        )
        inherited_delivery_boy = (
            parent_invoice.get("custom_delivery_boy")
            or parent_invoice.get("delivery_boy")
            or ""
        )

        submitted_customer = data.get("customer") or ""
        submitted_address = data.get("customer_address") or ""
        if submitted_customer and submitted_customer != customer:
            frappe.throw(_("Add-on customer must match the parent invoice."))
        if submitted_address and submitted_address != customer_address:
            frappe.throw(_("Add-on address must match the parent invoice."))
    else:
        company = _company(data.get("company"))
        order_type = data.get("order_type") or "Walk In"
        warehouse = data.get("warehouse") or settings.get("default_warehouse") or ""
        price_list = data.get("price_list") or settings.get("default_price_list") or ""
        customer = data.get("customer") or settings.get("default_customer") or ""
        customer_address = data.get("customer_address") or ""

    if not company:
        frappe.throw(_("Default Company is not configured."))

    if order_type not in ("Walk In", "Home Delivery", "Corporate"):
        frappe.throw(_("Invalid order type."))

    contract = None
    beneficiary = None
    delivery_zone = None
    claim_status = "Not Applicable"
    billing_type = ""

    if order_type == "Corporate":
        contract_name = data.get("pharmacy_contract")
        beneficiary_name = data.get("contract_beneficiary")
        if not contract_name:
            frappe.throw(_("Select Pharmacy Contract."))
        if not beneficiary_name:
            frappe.throw(_("Select Contract Beneficiary."))

        contract = frappe.get_doc("Pharmacy Contract", contract_name)
        beneficiary = frappe.get_doc("Contract Beneficiary", beneficiary_name)
        if not cint(contract.get("is_active")):
            frappe.throw(_("The selected contract is inactive."))
        if not cint(beneficiary.get("is_active")):
            frappe.throw(_("The selected beneficiary is inactive."))
        if beneficiary.get("pharmacy_contract") != contract.name:
            frappe.throw(_("The beneficiary does not belong to the selected contract."))
        if beneficiary.get("expiry_date") and getdate(beneficiary.expiry_date) < getdate(nowdate()):
            frappe.throw(_("The beneficiary card is expired."))

        billing_type = contract.get("billing_type") or ""
        if billing_type == "Cash Discount":
            customer = beneficiary.get("customer")
        elif billing_type == "Monthly Claim":
            customer = contract.get("customer")
            claim_status = "Pending"
        else:
            frappe.throw(_("Invalid Billing Type in Pharmacy Contract."))
        if cint(contract.get("require_employee_code")) and not beneficiary.get("employee_code"):
            frappe.throw(_("Employee Code is required for this contract."))

    if not customer:
        frappe.throw(_("Select Customer."))

    if order_type == "Home Delivery":
        delivery_zone = _validate_delivery_address(customer, customer_address, warehouse)

    return frappe._dict(
        {
            "settings": settings,
            "company": company,
            "cost_center": _company_cost_center(company),
            "order_type": order_type,
            "warehouse": warehouse,
            "price_list": price_list,
            "customer": customer,
            "customer_address": customer_address,
            "contract": contract,
            "beneficiary": beneficiary,
            "billing_type": billing_type,
            "claim_status": claim_status,
            "delivery_zone": delivery_zone,
            "is_add_on": is_add_on,
            "parent_invoice": parent_invoice,
            "skip_delivery_fee": 1 if is_add_on else cint(data.get("skip_delivery_fee")),
            "delivery_boy": inherited_delivery_boy or data.get("delivery_boy") or "",
        }
    )


def _append_invoice_items(doc, data, context):
    items = data.get("items") or []
    if not items:
        frappe.throw(_("Add at least one item."))

    discount_map = _contract_discount_map(context.contract) if context.contract else {}

    for item_data in items:
        item_data = frappe._dict(item_data)
        item_code = item_data.get("item_code")
        if not item_code:
            continue

        item = _item_context(item_code, context.warehouse)
        pack_size = flt(item.get("custom_pack_size") or item_data.get("pack_size") or 1) or 1
        box_qty = max(0, flt(item_data.get("box_qty")))
        unit_qty = max(0, flt(item_data.get("unit_qty")))

        if cint(item.get("custom_box_only")):
            unit_qty = 0

        qty = flt(item_data.get("qty")) or flt(box_qty + (unit_qty / pack_size), 6)
        if qty <= 0:
            frappe.throw(_("Quantity must be greater than zero for item {0}.").format(item_code))

        customer_price = flt(
            item.get("custom_customer_price")
            or item_data.get("price_list_rate")
            or item_data.get("rate")
        )

        submitted_discount = item_data.get("discount_percentage")
        if submitted_discount is None and context.contract:
            origin = (item.get("custom_item_origin") or "").strip().lower()
            discount_percentage = flt(discount_map.get(origin, 0))
        else:
            discount_percentage = flt(submitted_discount or 0)

        if discount_percentage < 0 or discount_percentage > 100:
            frappe.throw(_("Discount must be between 0 and 100 for item {0}.").format(item_code))

        rate = flt(customer_price * (1 - discount_percentage / 100), 6)

        if cint(item.get("has_batch_no")):
            if not context.warehouse:
                frappe.throw(_("Warehouse is required for batch item {0}.").format(item_code))
            allocations = _allocate_batches(
                item_code,
                context.warehouse,
                qty,
                item_data.get("batch_no"),
            )
        else:
            allocations = [frappe._dict({"batch_no": "", "qty": qty})]

        for allocation in allocations:
            allocation_qty = flt(allocation.qty, 6)
            row = doc.append("items", {})
            row.item_code = item_code
            row.qty = allocation_qty
            row.rate = rate
            row.discount_percentage = discount_percentage
            row.price_list_rate = customer_price or rate

            if context.warehouse:
                row.warehouse = context.warehouse
            if context.cost_center and _has_field("Sales Invoice Item", "cost_center"):
                row.cost_center = context.cost_center
            if allocation.batch_no:
                row.batch_no = allocation.batch_no

            if len(allocations) == 1:
                allocated_boxes = box_qty
                allocated_units = unit_qty
            else:
                allocated_boxes = int(allocation_qty)
                allocated_units = flt((allocation_qty - allocated_boxes) * pack_size, 6)

            if _has_field("Sales Invoice Item", "custom_box_qty"):
                row.custom_box_qty = allocated_boxes
            if _has_field("Sales Invoice Item", "custom_unit_qty"):
                row.custom_unit_qty = allocated_units
            if _has_field("Sales Invoice Item", "custom_pack_size"):
                row.custom_pack_size = pack_size

    if not doc.items:
        frappe.throw(_("No valid items were added."))


def _apply_loyalty(doc, loyalty_data, company):
    loyalty_data = frappe._dict(loyalty_data or {})
    points = flt(loyalty_data.get("points"))
    if points <= 0:
        return 0

    context = _get_loyalty_context(doc.customer, company)
    if not context.program or context.available_points <= 0:
        frappe.throw(_("The customer has no available loyalty points."))
    if points - context.available_points > 1e-9:
        frappe.throw(_("Requested loyalty points exceed the available balance."))
    if context.conversion_factor <= 0:
        frappe.throw(_("Loyalty conversion factor is not configured."))

    amount = flt(points * context.conversion_factor, 6)
    doc.redeem_loyalty_points = 1
    doc.loyalty_points = points
    doc.loyalty_amount = amount
    doc.loyalty_program = context.program

    if _has_field("Sales Invoice", "loyalty_redemption_account"):
        doc.loyalty_redemption_account = context.expense_account

    loyalty_cost_center = context.cost_center or _company_cost_center(company)
    if not loyalty_cost_center:
        frappe.throw(
            _(
                "Set Redemption Cost Center in Loyalty Program "
                "or Default Cost Center in Company {0}."
            ).format(company)
        )

    if _has_field("Sales Invoice", "loyalty_redemption_cost_center"):
        doc.loyalty_redemption_cost_center = loyalty_cost_center

    if _has_field("Sales Invoice", "cost_center"):
        doc.cost_center = loyalty_cost_center

    return amount


def _append_payments(doc, payments, company):
    total = 0
    cash_account = None

    for payment in payments or []:
        payment = frappe._dict(payment or {})
        amount = flt(payment.get("amount"))
        mode = payment.get("mode_of_payment")
        if amount <= 0:
            continue
        if not mode:
            frappe.throw(_("Mode of Payment is required."))

        card_terminal = None
        if mode == "Credit Card":
            card_terminal = _resolve_card_terminal(payment.get("card_pos_terminal"), company)
            account = card_terminal.clearing_account
        else:
            account = _mode_of_payment_account(mode, company)
        if not account:
            frappe.throw(
                _("No default account is configured for Mode of Payment {0} in company {1}.").format(
                    mode, company
                )
            )

        row = doc.append("payments", {})
        row.mode_of_payment = mode
        row.amount = amount
        row.account = account
        if card_terminal and _has_field("Sales Invoice Payment", "custom_card_pos_terminal"):
            row.custom_card_pos_terminal = card_terminal.name
        if payment.get("reference_no"):
            if _has_field("Sales Invoice Payment", "reference_no"):
                row.reference_no = payment.get("reference_no")
            elif _has_field("Sales Invoice Payment", "reference"):
                row.reference = payment.get("reference_no")
        total += amount

        mode_type = frappe.db.get_value("Mode of Payment", mode, "type")
        if mode_type == "Cash" and not cash_account:
            cash_account = account

    return flt(total, 6), cash_account


@frappe.whitelist()
def save_invoice(data):
    if isinstance(data, str):
        data = json.loads(data)

    data = frappe._dict(data or {})
    active_shift = _require_open_shift_for_pos(
        data.get("company") or _company()
    )
    context = _prepare_invoice_context(data)
    submitted_payments = data.get("payments") or []
    selected_allocations = [frappe._dict(row) for row in (data.get("advance_allocations") or [])]
    payment_entry_allocations = [
        row for row in selected_allocations if row.get("reference_type") == "Payment Entry"
    ]
    credit_note_allocations = [
        row for row in selected_allocations if row.get("reference_type") == "Sales Invoice"
    ]
    draft_name = data.get("draft_name") or ""
    hold = cint(data.get("hold"))
    keep_excess_as_credit = cint(data.get("keep_excess_as_credit"))

    if keep_excess_as_credit and _is_default_pos_customer(context.customer):
        frappe.throw(_("Customer credit cannot be stored against the anonymous Cash Customer. Select or create the actual customer first."))

    is_monthly_claim = context.billing_type == "Monthly Claim"

    if draft_name:
        doc = frappe.get_doc("Sales Invoice", draft_name)
        if doc.docstatus != 0:
            frappe.throw(_("Only a draft invoice can be updated."))
        if not doc.has_permission("write"):
            frappe.throw(_("You do not have permission to update this draft."))
        if context.is_add_on:
            existing_parent = doc.get(ADD_ON_PARENT_FIELD) or ""
            if existing_parent and existing_parent != context.parent_invoice.name:
                frappe.throw(_("This draft belongs to a different Add-on parent invoice."))
        doc.set("items", [])
        doc.set("payments", [])
        doc.set("advances", [])
    else:
        doc = frappe.new_doc("Sales Invoice")

    doc.company = context.company
    doc.customer = context.customer

    shift_field = "custom_pharmacy_shift"
    if _has_field("Sales Invoice", shift_field):
        existing_shift = doc.get(shift_field)

        if (
            existing_shift
            and existing_shift != active_shift.name
        ):
            frappe.throw(
                _(
                    "This draft belongs to shift {0}. Reopen that shift for review or create a new invoice in the active shift {1}."
                ).format(
                    existing_shift,
                    active_shift.name,
                )
            )

        doc.set(shift_field, active_shift.name)

    doc.update_stock = cint(data.get("update_stock", 1))
    doc.ignore_pricing_rule = 1
    if context.is_add_on:
        add_on_note = "Add-on for {0}".format(context.parent_invoice.name)
        doc.remarks = (
            "[PHARMACY_POS_HOLD] " + add_on_note
            if hold
            else "Pharmacy POS - " + add_on_note
        )
    else:
        doc.remarks = "[PHARMACY_POS_HOLD] Held from Pharmacy POS" if hold else "Pharmacy POS"

    if context.cost_center and _has_field("Sales Invoice", "cost_center"):
        doc.cost_center = context.cost_center
    if context.warehouse:
        doc.set_warehouse = context.warehouse
    if context.price_list:
        doc.selling_price_list = context.price_list
    if context.customer_address:
        doc.customer_address = context.customer_address
        doc.shipping_address_name = context.customer_address

    _set_if_field(doc, "custom_order_type", context.order_type)
    _set_if_field(doc, "delivery_boy", context.delivery_boy)
    _set_if_field(doc, "custom_delivery_boy", context.delivery_boy)

    if context.order_type == "Home Delivery":
        delivery_shift = active_shift.name
        if context.is_add_on and context.parent_invoice:
            delivery_shift = (
                context.parent_invoice.get("custom_delivery_shift")
                or context.parent_invoice.get("custom_pharmacy_shift")
                or active_shift.name
            )
        _set_if_field(doc, "custom_delivery_shift", delivery_shift)
        if not doc.get("custom_original_delivery_shift"):
            _set_if_field(doc, "custom_original_delivery_shift", delivery_shift)

    if context.is_add_on:
        _set_if_field(doc, ADD_ON_CHECK_FIELD, 1)
        _set_if_field(doc, ADD_ON_PARENT_FIELD, context.parent_invoice.name)
        _set_if_field(doc, "custom_delivery_fee", 0)
        _set_if_field(doc, "custom_delivery_fee_rule", "Add-on – No Additional Delivery Fee")
        _set_if_field(
            doc,
            "custom_delivery_status",
            "Ready for Delivery" if context.delivery_boy else "Draft",
        )

    if context.order_type == "Corporate":
        _set_if_field(doc, "custom_pharmacy_contract", context.contract.name)
        _set_if_field(doc, "custom_contract_beneficiary", context.beneficiary.name)
        _set_if_field(doc, "custom_beneficiary_customer", context.beneficiary.get("customer"))
        _set_if_field(doc, "custom_employee_code", context.beneficiary.get("employee_code") or context.beneficiary.name)
        _set_if_field(doc, "custom_contract_billing_type", context.billing_type)
        _set_if_field(doc, "custom_claim_status", context.claim_status)

    _append_invoice_items(doc, data, context)
    products_subtotal = flt(sum(flt(row.qty) * flt(row.rate) for row in doc.items), 6)

    if context.is_add_on or context.skip_delivery_fee:
        _set_if_field(doc, "custom_delivery_zone", context.delivery_zone.name if context.delivery_zone else "")
        _set_if_field(doc, "custom_delivery_fee", 0)
        _set_if_field(doc, "custom_estimated_delivery_time", cint(context.delivery_zone.get("estimated_time_mins")) if context.delivery_zone else 0)
        _set_if_field(doc, "custom_delivery_fee_rule", "Add-on – No Additional Delivery Fee")
        delivery_result = frappe._dict(
            {
                "fee": 0,
                "rule": "Add-on – No Additional Delivery Fee",
                "zone": context.delivery_zone,
            }
        )
    else:
        delivery_result = _append_delivery_fee_item(doc, context, products_subtotal)

    loyalty_payload = data.get("loyalty_redemption") or {}
    if _is_default_pos_customer(context.customer):
        loyalty_payload = {}
    loyalty_amount = _apply_loyalty(doc, loyalty_payload, context.company)

    allocation_total = flt(sum(flt(row.get("allocated_amount")) for row in selected_allocations), 6)
    expected_total = flt(sum(flt(row.qty) * flt(row.rate) for row in doc.items), 6)
    amount_due = max(0, flt(expected_total - loyalty_amount - allocation_total, 6))

    invoice_payments = submitted_payments
    advance_payment_rows = []
    if keep_excess_as_credit:
        invoice_payments, advance_payment_rows = _split_payment_rows_for_customer_credit(
            submitted_payments, amount_due
        )

    has_direct_payment = any(flt(row.get("amount")) > 0 for row in invoice_payments)
    is_pos = not is_monthly_claim and has_direct_payment
    doc.is_pos = cint(is_pos)

    payment_total = 0
    cash_account = None
    if cint(is_pos):
        payment_total, cash_account = _append_payments(doc, invoice_payments, context.company)

    requires_full_payment = context.order_type == "Walk In" or (
        context.order_type == "Corporate" and context.billing_type == "Cash Discount"
    )

    if cint(data.get("submit")) and requires_full_payment and payment_total + 1e-9 < amount_due:
        frappe.throw(_("Payment is incomplete. Required: {0}, entered: {1}.").format(amount_due, payment_total))

    if not keep_excess_as_credit and payment_total > amount_due + 1e-9:
        doc.change_amount = flt(payment_total - amount_due, 6)
        if cash_account and _has_field("Sales Invoice", "account_for_change_amount"):
            doc.account_for_change_amount = cash_account

    created_advance_entries = []
    customer_credit_added = flt(sum(flt(row.get("amount")) for row in advance_payment_rows), 6)

    try:
        if doc.is_new():
            doc.insert()
        else:
            doc.save()

        # Fetch and attach Payment Entry advances only after the invoice draft
        # has all native accounting fields (debit_to, currency, exchange rate).
        # This is the same path ERPNext uses from the standard Sales Invoice form.
        if payment_entry_allocations:
            _apply_native_payment_entry_advances(doc, payment_entry_allocations)
            doc.save()

        if cint(data.get("submit")):
            doc.submit()
            if credit_note_allocations:
                _reconcile_selected_allocations(doc.name, credit_note_allocations)

            for advance_payment in advance_payment_rows:
                payment_entry = _create_customer_advance_payment(
                    context.customer,
                    context.company,
                    advance_payment,
                    doc.name,
                    context.cost_center,
                )
                if payment_entry:
                    created_advance_entries.append(payment_entry)

            doc.reload()

            if context.is_add_on:
                mark_add_on_invoice_created(
                    context.parent_invoice.name,
                    doc.name,
                )

            if requires_full_payment and flt(doc.outstanding_amount) > 0.009:
                frappe.throw(
                    _("Customer balance allocation was not completed. Outstanding amount: {0}.").format(doc.outstanding_amount)
                )
    except Exception:
        frappe.db.rollback()
        raise

    return {
        "success": True,
        "name": doc.name,
        "docstatus": doc.docstatus,
        "status": doc.status,
        "grand_total": doc.grand_total,
        "paid_amount": doc.paid_amount,
        "outstanding_amount": doc.outstanding_amount,
        "customer": doc.customer,
        "held": hold,
        "delivery_zone": delivery_result.zone.name if delivery_result.zone else "",
        "delivery_fee": delivery_result.fee,
        "delivery_fee_rule": delivery_result.rule,
        "customer_credit_added": customer_credit_added,
        "customer_credit_entries": created_advance_entries,
        "is_add_on": 1 if context.is_add_on else 0,
        "parent_delivery_invoice": context.parent_invoice.name if context.parent_invoice else "",
    }

# =====================================================
# Returns
# =====================================================


@frappe.whitelist()
def search_sales_invoices(txt="", customer="", limit=20):
    raw, like_txt, compact_txt = _search_pattern(txt)
    customer = customer or ""
    return frappe.db.sql(
        """
        SELECT
            si.name,
            si.posting_date,
            si.customer,
            si.customer_name,
            si.grand_total,
            si.outstanding_amount
        FROM `tabSales Invoice` si
        LEFT JOIN `tabCustomer` c ON c.name = si.customer
        WHERE si.docstatus = 1
          AND IFNULL(si.is_return, 0) = 0
          AND (%(customer)s = '' OR si.customer = %(customer)s)
          AND (
              %(raw)s = ''
              OR si.name LIKE %(like_txt)s
              OR IFNULL(si.customer_name, '') LIKE %(like_txt)s
              OR IFNULL(c.mobile_no, '') LIKE %(like_txt)s
              OR CAST(si.grand_total AS CHAR) LIKE %(like_txt)s
              OR CAST(si.posting_date AS CHAR) LIKE %(like_txt)s
              OR REPLACE(REPLACE(LOWER(si.name), '-', ''), ' ', '') LIKE %(compact_like)s
          )
        ORDER BY
            CASE WHEN si.name = %(raw)s THEN 0 ELSE 1 END,
            CASE WHEN si.name LIKE %(starts)s THEN 0 ELSE 1 END,
            si.posting_date DESC,
            si.creation DESC
        LIMIT %(limit)s
        """,
        {
            "raw": raw,
            "like_txt": like_txt,
            "compact_like": f"%{compact_txt}%",
            "starts": f"{raw}%",
            "customer": customer,
            "limit": _safe_limit(limit, 20, 100),
        },
        as_dict=True,
    )

@frappe.whitelist()
def get_returnable_invoice(invoice, return_request=None):
    if not invoice:
        return None

    source = frappe.get_doc("Sales Invoice", invoice)
    if source.docstatus != 1 or cint(source.is_return):
        frappe.throw(_("Select a submitted sales invoice."))

    rows = []
    delivery_fee_item = _get_settings().get("delivery_fee_item") or ""
    delivery_return_context = _is_pending_delivery_return(source)
    partial_request = None
    request_items = {}
    source_docs = [source]

    if return_request:
        from pharma_erp.pharma_erp.delivery_partial_return import (
            REQUEST_DOCTYPE,
            RETURN_TYPE_PARTIAL,
            _request_item_source_invoice,
            _resolve_pack_size,
        )
        if not frappe.db.exists(REQUEST_DOCTYPE, return_request):
            frappe.throw(_("طلب المرتجع غير موجود."))
        partial_request = frappe.get_doc(REQUEST_DOCTYPE, return_request)
        if partial_request.sales_invoice != source.name or partial_request.return_type != RETURN_TYPE_PARTIAL:
            frappe.throw(_("طلب المرتجع الجزئي لا يخص الفاتورة المحددة."))

        source_names = []
        for request_row in partial_request.items:
            source_invoice = _request_item_source_invoice(partial_request, request_row)
            if source_invoice and source_invoice not in source_names:
                source_names.append(source_invoice)
            request_items[request_row.source_item] = frappe._dict({
                "qty": flt(request_row.return_qty, 6),
                "source_invoice": source_invoice,
                "box_qty": flt(request_row.get("return_box_qty"), 6),
                "unit_qty": flt(request_row.get("return_unit_qty"), 6),
            })
        source_docs = [frappe.get_doc("Sales Invoice", name) for name in source_names]
        delivery_return_context = False
    else:
        _resolve_pack_size = None
        # A full delivery cancellation belongs to the whole operational order,
        # not only to the first Sales Invoice.  Include every submitted Add-on
        # invoice so the manager can return its items from the same dialog.
        group_parent, group_docs = _get_submitted_delivery_group_docs(source)
        if _is_pending_delivery_return(group_parent):
            source = group_parent
            source_docs = group_docs
            delivery_return_context = True

    for source_doc in source_docs:
        for item in source_doc.items:
            requested = request_items.get(item.name) if partial_request else None
            if partial_request and not requested:
                continue
            if delivery_fee_item and item.item_code == delivery_fee_item and not delivery_return_context:
                continue

            returned_qty = abs(
                flt(
                    frappe.db.sql(
                        """
                        SELECT COALESCE(SUM(ABS(rii.qty)), 0)
                        FROM `tabSales Invoice Item` rii
                        INNER JOIN `tabSales Invoice` ri ON ri.name = rii.parent
                        WHERE ri.docstatus = 1
                          AND ri.is_return = 1
                          AND ri.return_against = %(invoice)s
                          AND rii.sales_invoice_item = %(source_item)s
                        """,
                        {"invoice": source_doc.name, "source_item": item.name},
                    )[0][0]
                )
            )
            returnable_qty = max(0, abs(flt(item.qty)) - returned_qty)
            if partial_request:
                returnable_qty = min(returnable_qty, flt(requested.qty, 6))
            if returnable_qty <= 0:
                continue

            if partial_request:
                pack_size = flt(_resolve_pack_size(item) or 1)
            else:
                pack_size = flt(item.get("custom_pack_size") or 0)
                if not pack_size and _has_field("Item", "custom_pack_size"):
                    pack_size = flt(frappe.db.get_value("Item", item.item_code, "custom_pack_size") or 1)
                pack_size = pack_size or 1

            rows.append(
                {
                    "source_invoice": source_doc.name,
                    "source_invoice_type": "Original" if source_doc.name == source.name else "Add-on",
                    "source_item": item.name,
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "batch_no": item.batch_no or "",
                    "sold_qty": abs(flt(item.qty)),
                    "returned_qty": returned_qty,
                    "returnable_qty": returnable_qty,
                    "requested_box_qty": flt(requested.box_qty, 6) if requested else 0,
                    "requested_unit_qty": flt(requested.unit_qty, 6) if requested else 0,
                    "pack_size": pack_size,
                    "returnable_boxes": int(returnable_qty),
                    "returnable_units": flt((returnable_qty - int(returnable_qty)) * pack_size, 6),
                    "rate": abs(flt(item.rate)),
                    "amount": abs(flt(item.amount)),
                    "warehouse": item.warehouse,
                    "is_delivery_fee": bool(delivery_fee_item and item.item_code == delivery_fee_item),
                }
            )

    return {
        "name": source.name,
        "customer": source.customer,
        "customer_name": source.customer_name,
        "posting_date": source.posting_date,
        "grand_total": flt(sum(flt(doc.grand_total) for doc in source_docs), 2),
        "group_invoices": [doc.name for doc in source_docs],
        "delivery_return_request": partial_request.name if partial_request else "",
        "return_type": partial_request.return_type if partial_request else "",
        "items": rows,
    }

@frappe.whitelist()
def get_return_item(item_code, warehouse=None):
    settings = _get_settings()
    warehouse = warehouse or settings.get("default_warehouse") or ""
    item = _item_context(item_code, warehouse)
    item.return_batches = _get_all_item_batches(item_code) if cint(item.has_batch_no) else []
    return item

def _is_pending_delivery_return(source):
    """Return True while the invoice belongs to the delivery-cancellation flow.

    Older patch versions could mark the order as Cancelled / Return Completed
    after only part of the invoice had been reversed.  In that recovery state
    the strict operational status is no longer ``Returned to Pharmacy``, but
    the delivery-return fields still prove that this is not a normal customer
    return.  Keep the context active until every source invoice row (including
    the delivery-fee service row) has a submitted reversal.
    """
    if not (
        source
        and source.docstatus == 1
        and not cint(source.get("is_return"))
        and source.get("custom_order_type") == "Home Delivery"
    ):
        return False

    delivery_status = str(source.get("custom_delivery_status") or "").strip()
    return_status = str(source.get("custom_delivery_return_status") or "").strip()
    return_type = str(source.get("custom_delivery_return_type") or "").strip()
    if return_type == "Partial Item Return":
        return False
    return_reason = str(source.get("custom_delivery_return_reason") or "").strip()
    linked_credit_note = str(source.get("custom_delivery_return_credit_note") or "").strip()

    strict_pending = (
        delivery_status == "Returned to Pharmacy"
        and return_status in {"Awaiting Manager Review", "Credit Note Draft"}
    )

    # Recovery / continuation mode: a delivery return was already initiated,
    # even if a previous version moved the order to a terminal status too soon.
    workflow_marked = bool(
        (return_status and return_status != "Not Required")
        or return_reason
        or linked_credit_note
        or delivery_status in {"Returning to Pharmacy", "Returned to Pharmacy", "Cancelled"}
    )

    return bool(strict_pending or workflow_marked)


def _sync_delivery_return_workflow(source, return_doc, request_name=None):
    # Submitting the Credit Note updates the source invoice and its modified
    # timestamp. Reload it before writing delivery-return workflow fields.
    source_name = source.name if source else ""
    if not source_name:
        return frappe._dict({"linked": False, "complete": False})
    source = frappe.get_doc("Sales Invoice", source_name)
    if request_name or str(source.get("custom_delivery_return_type") or "") == "Partial Item Return":
        from pharma_erp.pharma_erp.delivery_partial_return import sync_partial_return_credit_note
        return sync_partial_return_credit_note(source, return_doc, request_name=request_name)
    if not _is_pending_delivery_return(source):
        return frappe._dict({"linked": False, "complete": False})

    from pharma_erp.pharma_erp.delivery_return_workflow import (
        RETURN_CREDIT_NOTE_DRAFT,
        RETURN_CREDIT_NOTE_FIELD,
        RETURN_REVIEWED_AT_FIELD,
        RETURN_REVIEWED_BY_FIELD,
        RETURN_STATUS_FIELD,
        _delivery_return_group_reversal_summary,
        complete_return_review,
    )

    _set_if_field(source, RETURN_CREDIT_NOTE_FIELD, return_doc.name)
    _set_if_field(source, RETURN_STATUS_FIELD, RETURN_CREDIT_NOTE_DRAFT)
    _set_if_field(source, RETURN_REVIEWED_BY_FIELD, frappe.session.user)
    _set_if_field(source, RETURN_REVIEWED_AT_FIELD, frappe.utils.now_datetime())
    source.flags.ignore_validate_update_after_submit = True
    source.save(ignore_permissions=True)

    reversal = _delivery_return_group_reversal_summary(source.name)
    completed = False
    if return_doc.docstatus == 1 and reversal.complete:
        complete_return_review(source.name)
        completed = True

    return frappe._dict(
        {
            "linked": True,
            "complete": completed,
            "pending_amount": reversal.pending_amount,
            "pending_items": [row.item_code for row in reversal.pending],
        }
    )


def _create_partial_delivery_group_returns(data, selections, request_name):
    """Create one Credit Note per source invoice for a grouped delivery return."""
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
    from pharma_erp.pharma_erp.delivery_partial_return import (
        REQUEST_DOCTYPE,
        RETURN_TYPE_PARTIAL,
        _request_item_credit_note,
        _request_item_source_invoice,
    )

    if not frappe.db.exists(REQUEST_DOCTYPE, request_name):
        frappe.throw(_("طلب المرتجع غير موجود."))
    request = frappe.get_doc(REQUEST_DOCTYPE, request_name)
    if request.return_type != RETURN_TYPE_PARTIAL:
        frappe.throw(_("طلب المرتجع المحدد ليس مرتجعًا جزئيًا."))

    parent_name = str(data.get("invoice") or "").strip()
    if not parent_name or request.sales_invoice != parent_name:
        frappe.throw(_("طلب المرتجع الجزئي لا يخص الفاتورة المحددة."))
    parent = frappe.get_doc("Sales Invoice", parent_name)

    existing_notes = {
        _request_item_credit_note(row)
        for row in request.items
        if _request_item_credit_note(row)
    }
    if existing_notes:
        frappe.throw(
            _("تم ربط طلب المرتجع بالفعل بمرتجع مبيعات: {0}.").format(", ".join(sorted(existing_notes)))
        )

    request_map = {}
    for row in request.items:
        request_map[row.source_item] = frappe._dict({
            "source_invoice": _request_item_source_invoice(request, row),
            "qty": flt(row.return_qty, 6),
            "box_qty": flt(row.get("return_box_qty"), 6),
            "unit_qty": flt(row.get("return_unit_qty"), 6),
        })

    selected_map = {}
    for raw in selections:
        raw = frappe._dict(raw or {})
        source_item = str(raw.get("source_item") or "").strip()
        if source_item not in request_map:
            frappe.throw(_("تم اختيار صنف غير موجود في طلب المرتجع الجزئي."))
        expected = request_map[source_item]
        source_invoice = str(raw.get("source_invoice") or expected.source_invoice or "").strip()
        if source_invoice != expected.source_invoice:
            frappe.throw(_("فاتورة مصدر الصنف لا تطابق طلب المرتجع."))
        qty = flt(raw.get("qty"), 6)
        if abs(qty - flt(expected.qty, 6)) > 1e-6:
            frappe.throw(_("يجب تنفيذ كمية المرتجع المعتمدة بالكامل لكل صنف."))
        selected_map[source_item] = frappe._dict({
            "source_invoice": source_invoice,
            "qty": qty,
            "box_qty": flt(raw.get("box_qty"), 6),
            "unit_qty": flt(raw.get("unit_qty"), 6),
        })

    missing = [row.item_code for row in request.items if row.source_item not in selected_map]
    if missing:
        frappe.throw(_("نفّذ كل أصناف طلب المرتجع قبل الحفظ: {0}").format(", ".join(missing)))

    grouped = {}
    for source_item, selected in selected_map.items():
        grouped.setdefault(selected.source_invoice, {})[source_item] = selected

    created_docs = []
    workflow_result = frappe._dict({"linked": False, "complete": False})
    try:
        for source_invoice_name, group_selection in grouped.items():
            source_doc = frappe.get_doc("Sales Invoice", source_invoice_name)
            if source_doc.docstatus != 1 or cint(source_doc.get("is_return")):
                frappe.throw(_("فاتورة المصدر {0} غير صالحة للمرتجع.").format(source_invoice_name))
            if source_doc.company != parent.company or source_doc.customer != parent.customer:
                frappe.throw(_("فاتورة الإضافة لا تتبع نفس الشركة والعميل للأوردر الأصلي."))

            return_doc = make_sales_return(source_invoice_name)
            kept_rows = []
            for row in return_doc.items:
                selected = group_selection.get(row.sales_invoice_item)
                if not selected:
                    continue
                maximum_qty = abs(flt(row.qty))
                if selected.qty - maximum_qty > 1e-9:
                    frappe.throw(_("Return quantity exceeds the available quantity for {0}.").format(row.item_code))
                row.qty = -selected.qty
                if _has_field("Sales Invoice Item", "custom_box_qty"):
                    row.custom_box_qty = -abs(selected.box_qty)
                if _has_field("Sales Invoice Item", "custom_unit_qty"):
                    row.custom_unit_qty = -abs(selected.unit_qty)
                kept_rows.append(row)
            return_doc.set("items", kept_rows)
            if not return_doc.items:
                frappe.throw(_("No valid return items were selected for {0}.").format(source_invoice_name))
            return_doc.update_stock = 1
            return_doc.is_pos = 0
            return_doc.set("payments", [])
            if _has_field("Sales Invoice", "update_outstanding_for_self"):
                return_doc.update_outstanding_for_self = 0
            return_doc.remarks = _("Delivery partial return request {0} for order {1}").format(request.name, parent.name)
            return_doc.insert()
            return_doc.submit()
            created_docs.append(return_doc)
            workflow_result = _sync_delivery_return_workflow(source_doc, return_doc, request_name=request.name)
    except Exception:
        frappe.db.rollback()
        raise

    return {
        "success": True,
        "name": created_docs[0].name if created_docs else "",
        "names": [doc.name for doc in created_docs],
        "credit_notes": [doc.name for doc in created_docs],
        "docstatus": 1,
        "grand_total": flt(sum(flt(doc.grand_total) for doc in created_docs), 2),
        "outstanding_amount": flt(sum(flt(doc.outstanding_amount) for doc in created_docs), 2),
        "customer": parent.customer,
        "keep_as_credit": 0,
        "credit_amount": 0,
        "delivery_return_linked": bool(workflow_result.get("linked")),
        "delivery_return_complete": bool(workflow_result.get("complete")),
        "delivery_return_pending_amount": flt(workflow_result.get("pending_amount")),
        "delivery_return_pending_items": workflow_result.get("pending_items") or [],
    }


def _create_full_delivery_group_returns(data, selections):
    """Create submitted Credit Notes for a full delivery order group.

    ERPNext requires every Credit Note to point to exactly one ``return_against``
    Sales Invoice.  A customer delivery order can, however, consist of the
    original invoice plus one or more Add-on invoices.  This function validates
    one combined selection and splits it into one Credit Note per source invoice.
    """
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

    source_name = str(data.get("invoice") or "").strip()
    if not source_name:
        frappe.throw(_("Select the original invoice."))

    selected_doc = frappe.get_doc("Sales Invoice", source_name)
    parent, group_docs = _get_submitted_delivery_group_docs(selected_doc)
    if not _is_pending_delivery_return(parent):
        frappe.throw(_("The selected order is not awaiting a full delivery return."))

    docs_by_name = {doc.name: doc for doc in group_docs}
    item_source = {
        item.name: doc.name
        for doc in group_docs
        for item in (doc.items or [])
    }

    grouped = {}
    for raw in selections:
        raw = frappe._dict(raw or {})
        source_item = str(raw.get("source_item") or "").strip()
        qty = flt(raw.get("qty"), 6)
        if not source_item or qty <= 0:
            continue

        expected_invoice = item_source.get(source_item)
        if not expected_invoice:
            frappe.throw(_("A selected item does not belong to this delivery order."))
        source_invoice = str(raw.get("source_invoice") or expected_invoice).strip()
        if source_invoice != expected_invoice or source_invoice not in docs_by_name:
            frappe.throw(_("The item source invoice does not match the delivery order."))

        grouped.setdefault(source_invoice, {})[source_item] = frappe._dict(
            {
                "source_invoice": source_invoice,
                "source_item": source_item,
                "qty": qty,
                "box_qty": flt(raw.get("box_qty"), 6),
                "unit_qty": flt(raw.get("unit_qty"), 6),
            }
        )

    if not grouped:
        frappe.throw(_("Select at least one item to return."))

    delivery_fee_item = _get_settings().get("delivery_fee_item") or ""
    created_docs = []
    workflow_result = frappe._dict({"linked": False, "complete": False})

    try:
        for source_doc in group_docs:
            group_selection = grouped.get(source_doc.name, {})
            return_doc = make_sales_return(source_doc.name)

            # Full delivery cancellation also reverses the service fee.  It is
            # added automatically on the source invoice that contains it, even
            # when the manager did not type a quantity for that row.
            if delivery_fee_item:
                for fee_row in return_doc.items:
                    if (
                        fee_row.item_code == delivery_fee_item
                        and fee_row.sales_invoice_item not in group_selection
                    ):
                        group_selection[fee_row.sales_invoice_item] = frappe._dict(
                            {
                                "source_invoice": source_doc.name,
                                "source_item": fee_row.sales_invoice_item,
                                "qty": abs(flt(fee_row.qty)),
                                "box_qty": abs(flt(fee_row.qty)),
                                "unit_qty": 0,
                            }
                        )

            if not group_selection:
                continue

            kept_rows = []
            for row in return_doc.items:
                selected = group_selection.get(row.sales_invoice_item)
                if not selected:
                    continue
                requested_qty = flt(selected.get("qty"), 6)
                maximum_qty = abs(flt(row.qty))
                if requested_qty - maximum_qty > 1e-9:
                    frappe.throw(
                        _("Return quantity exceeds the available quantity for {0}.").format(
                            row.item_code
                        )
                    )
                row.qty = -requested_qty
                if _has_field("Sales Invoice Item", "custom_box_qty"):
                    row.custom_box_qty = -abs(flt(selected.get("box_qty")))
                if _has_field("Sales Invoice Item", "custom_unit_qty"):
                    row.custom_unit_qty = -abs(flt(selected.get("unit_qty")))
                kept_rows.append(row)

            return_doc.set("items", kept_rows)
            if not return_doc.items:
                continue

            return_doc.update_stock = 1
            return_doc.is_pos = 0
            return_doc.set("payments", [])
            if _has_field("Sales Invoice", "update_outstanding_for_self"):
                return_doc.update_outstanding_for_self = 0
            return_doc.remarks = _(
                "Full delivery return for order {0}; source invoice {1}"
            ).format(parent.name, source_doc.name)
            return_doc.insert()
            return_doc.submit()
            created_docs.append(return_doc)

        if not created_docs:
            frappe.throw(_("No valid return items were selected."))

        # Link and finish the operational workflow only after all source Credit
        # Notes exist.  The workflow layer verifies the complete group before it
        # closes the order and reconciles each source invoice separately.
        workflow_result = _sync_delivery_return_workflow(parent, created_docs[-1])
    except Exception:
        frappe.db.rollback()
        raise

    return {
        "success": True,
        "name": created_docs[0].name,
        "names": [doc.name for doc in created_docs],
        "credit_notes": [doc.name for doc in created_docs],
        "docstatus": 1,
        "grand_total": flt(sum(flt(doc.grand_total) for doc in created_docs), 2),
        "outstanding_amount": flt(sum(flt(doc.outstanding_amount) for doc in created_docs), 2),
        "customer": parent.customer,
        "keep_as_credit": 0,
        "credit_amount": 0,
        "delivery_return_linked": bool(workflow_result.get("linked")),
        "delivery_return_complete": bool(workflow_result.get("complete")),
        "delivery_return_pending_amount": flt(workflow_result.get("pending_amount")),
        "delivery_return_pending_items": workflow_result.get("pending_items") or [],
    }


@frappe.whitelist()
def create_sales_return(data):
    if isinstance(data, str):
        data = json.loads(data)
    data = frappe._dict(data or {})

    mode = data.get("mode") or "against_invoice"
    selections = data.get("items") or []
    if not selections:
        frappe.throw(_("Select at least one item to return."))

    delivery_return_request = str(data.get("delivery_return_request") or "").strip()
    if mode == "against_invoice" and delivery_return_request:
        return _create_partial_delivery_group_returns(data, selections, delivery_return_request)

    if mode == "against_invoice" and not delivery_return_request:
        selected_name = str(data.get("invoice") or "").strip()
        if selected_name:
            selected_doc = frappe.get_doc("Sales Invoice", selected_name)
            group_parent, group_docs = _get_submitted_delivery_group_docs(selected_doc)
            if len(group_docs) > 1 and _is_pending_delivery_return(group_parent):
                data.invoice = group_parent.name
                return _create_full_delivery_group_returns(data, selections)

    source_doc = None
    delivery_return_context = False
    partial_return_context = False
    if mode == "against_invoice":
        source_name = data.get("invoice")
        if not source_name:
            frappe.throw(_("Select the original invoice."))
        source_doc = frappe.get_doc("Sales Invoice", source_name)
        delivery_return_context = _is_pending_delivery_return(source_doc)
        if delivery_return_request:
            from pharma_erp.pharma_erp.delivery_partial_return import REQUEST_DOCTYPE, RETURN_TYPE_PARTIAL
            if not frappe.db.exists(REQUEST_DOCTYPE, delivery_return_request):
                frappe.throw(_("طلب المرتجع غير موجود."))
            request_doc = frappe.get_doc(REQUEST_DOCTYPE, delivery_return_request)
            if request_doc.sales_invoice != source_doc.name or request_doc.return_type != RETURN_TYPE_PARTIAL:
                frappe.throw(_("طلب المرتجع الجزئي لا يخص الفاتورة المحددة."))
            partial_return_context = True
            delivery_return_context = False
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

        return_doc = make_sales_return(source_name)
        selected_map = {
            row.get("source_item"): frappe._dict(row)
            for row in selections
            if row.get("source_item") and flt(row.get("qty")) > 0
        }

        # Delivery cancellation/return is a full operational reversal. Include
        # the configured delivery-fee line automatically so the original
        # invoice cannot be left Partly Paid by an unreturned service charge.
        if delivery_return_context:
            delivery_fee_item = _get_settings().get("delivery_fee_item") or ""
            if delivery_fee_item:
                for fee_row in return_doc.items:
                    if fee_row.item_code == delivery_fee_item and fee_row.sales_invoice_item not in selected_map:
                        selected_map[fee_row.sales_invoice_item] = frappe._dict({
                            "source_item": fee_row.sales_invoice_item,
                            "qty": abs(flt(fee_row.qty)),
                            "box_qty": abs(flt(fee_row.qty)),
                            "unit_qty": 0,
                        })

        kept_rows = []
        for row in return_doc.items:
            selected = selected_map.get(row.sales_invoice_item)
            if not selected:
                continue
            requested_qty = flt(selected.get("qty"))
            maximum_qty = abs(flt(row.qty))
            if requested_qty - maximum_qty > 1e-9:
                frappe.throw(_("Return quantity exceeds the available quantity for {0}.").format(row.item_code))
            row.qty = -requested_qty
            if _has_field("Sales Invoice Item", "custom_box_qty"):
                row.custom_box_qty = -abs(flt(selected.get("box_qty")))
            if _has_field("Sales Invoice Item", "custom_unit_qty"):
                row.custom_unit_qty = -abs(flt(selected.get("unit_qty")))
            kept_rows.append(row)
        return_doc.set("items", kept_rows)
        if not return_doc.items:
            frappe.throw(_("No valid return items were selected."))
        return_doc.update_stock = 1
    elif mode == "without_invoice":
        reason = (data.get("reason") or "").strip()
        if not reason:
            frappe.throw(_("Return reason is required."))
        settings = _get_settings()
        company = _company(data.get("company"))
        warehouse = data.get("warehouse") or settings.get("default_warehouse") or ""
        customer = data.get("customer") or settings.get("default_customer") or ""
        if not customer:
            frappe.throw(_("Select Customer."))

        return_doc = frappe.new_doc("Sales Invoice")
        return_doc.company = company
        return_doc.customer = customer
        return_doc.is_return = 1
        return_doc.update_stock = 1
        return_doc.is_pos = 0
        return_doc.remarks = f"Return Without Original Invoice: {reason}"
        if warehouse:
            return_doc.set_warehouse = warehouse
        cost_center = _company_cost_center(company)
        if cost_center and _has_field("Sales Invoice", "cost_center"):
            return_doc.cost_center = cost_center
        _set_if_field(return_doc, "custom_order_type", "Walk In")

        for selected in selections:
            selected = frappe._dict(selected)
            item_code = selected.get("item_code")
            if not item_code:
                continue
            item = _item_context(item_code, warehouse)
            pack_size = flt(selected.get("pack_size") or item.get("custom_pack_size") or 1) or 1
            box_qty = max(0, flt(selected.get("box_qty")))
            unit_qty = max(0, flt(selected.get("unit_qty")))
            if cint(item.get("custom_box_only")):
                unit_qty = 0
            qty = flt(box_qty + unit_qty / pack_size, 6)
            if qty <= 0:
                continue
            default_rate = flt(item.get("custom_customer_price") or 0)
            rate = flt(selected.get("rate") or default_rate)
            if abs(rate - default_rate) > 0.009 and not _user_is_manager():
                frappe.throw(_("Manager permission is required to change the rate for a return without invoice."))
            batch_no = selected.get("batch_no") or ""
            if cint(item.has_batch_no):
                if not batch_no or not frappe.db.exists("Batch", {"name": batch_no, "item": item_code}):
                    frappe.throw(_("Select a valid Batch for item {0}.").format(item_code))

            row = return_doc.append("items", {})
            row.item_code = item_code
            row.qty = -qty
            row.rate = rate
            row.price_list_rate = default_rate or rate
            row.warehouse = warehouse
            row.batch_no = batch_no
            if cost_center and _has_field("Sales Invoice Item", "cost_center"):
                row.cost_center = cost_center
            if _has_field("Sales Invoice Item", "custom_box_qty"):
                row.custom_box_qty = -box_qty
            if _has_field("Sales Invoice Item", "custom_unit_qty"):
                row.custom_unit_qty = -unit_qty
            if _has_field("Sales Invoice Item", "custom_pack_size"):
                row.custom_pack_size = pack_size
        if not return_doc.items:
            frappe.throw(_("No valid return items were selected."))
    else:
        frappe.throw(_("Invalid return mode."))

    refund_payments = data.get("payments") or []
    keep_as_credit = cint(data.get("keep_as_credit", 1))

    # A delivery order returned before collecting from the customer is a
    # reversal of an unpaid invoice, not a new customer credit.  Preserve the
    # normal POS refund choices only when the original invoice was already paid.
    if (delivery_return_context or partial_return_context) and flt(source_doc.outstanding_amount) > 0.01:
        keep_as_credit = 0
        refund_payments = []

    # When the refund is kept as customer credit, the Credit Note must
    # maintain its own negative outstanding balance. Otherwise ERPNext
    # updates the original invoice and no reusable Customer Credit appears.
    if _has_field("Sales Invoice", "update_outstanding_for_self"):
        return_doc.update_outstanding_for_self = 1 if keep_as_credit else 0

    return_doc.set("payments", [])
    if refund_payments and not keep_as_credit:
        if mode == "without_invoice" and not _user_is_manager():
            frappe.throw(_("Manager permission is required for a direct refund without the original invoice."))
        return_doc.is_pos = 1
        for payment in refund_payments:
            payment = frappe._dict(payment or {})
            amount = abs(flt(payment.get("amount")))
            payment_mode = payment.get("mode_of_payment")
            if amount <= 0:
                continue
            account = _mode_of_payment_account(payment_mode, return_doc.company)
            if not account:
                frappe.throw(_("No default account is configured for {0}.").format(payment_mode))
            row = return_doc.append("payments", {})
            row.mode_of_payment = payment_mode
            row.amount = -amount
            row.account = account
    else:
        return_doc.is_pos = 0

    try:
        return_doc.insert()
        if cint(data.get("submit", 1)):
            return_doc.submit()

        workflow_result = frappe._dict({"linked": False, "complete": False})
        if source_doc:
            # Do not validate the source outstanding before commit. ERPNext can
            # still expose the pre-return outstanding inside this transaction,
            # which would roll back a valid final Credit Note. The workflow is
            # finalized from submitted item quantities instead.
            workflow_result = _sync_delivery_return_workflow(source_doc, return_doc, request_name=delivery_return_request)
    except Exception:
        frappe.db.rollback()
        raise

    return {
        "success": True,
        "name": return_doc.name,
        "docstatus": return_doc.docstatus,
        "grand_total": return_doc.grand_total,
        "outstanding_amount": return_doc.outstanding_amount,
        "customer": return_doc.customer,
        "keep_as_credit": keep_as_credit,
        "credit_amount": abs(flt(return_doc.outstanding_amount)) if keep_as_credit else 0,
        "delivery_return_linked": bool(workflow_result.get("linked")) if source_doc else False,
        "delivery_return_complete": bool(workflow_result.get("complete")) if source_doc else False,
        "delivery_return_pending_amount": flt(workflow_result.get("pending_amount")) if source_doc else 0,
        "delivery_return_pending_items": workflow_result.get("pending_items") if source_doc else [],
    }
