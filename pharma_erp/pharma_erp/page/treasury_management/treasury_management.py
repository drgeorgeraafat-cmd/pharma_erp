import re
import unicodedata

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, get_datetime, getdate, now_datetime, nowdate

from erpnext.accounts.utils import get_balance_on

from pharma_erp.pharma_erp.doctype.shift_cash_movement.shift_cash_movement import (
    MOVEMENT_RULES as SHIFT_CASH_MOVEMENT_RULES,
)

from pharma_erp.treasury_access import (
    can_emergency_submit_treasury,
    can_manage_treasury,
    can_operate_treasury,
    can_view_treasury,
    get_treasury_access_profile,
    validate_internal_transfer_approver,
)


@frappe.whitelist()
def get_overview():
    """Return the treasury summary and current cash drawer setup."""
    _validate_access()
    access_profile = get_treasury_access_profile()

    drawers = _get_cash_drawers()
    cash_accounts = _get_operational_cash_accounts()
    account_warnings = _get_cash_account_warnings()
    banks = _get_bank_accounts()
    bank_ledger_accounts = _get_bank_ledger_accounts()
    unlinked_bank_ledgers = _get_unlinked_bank_ledgers(bank_ledger_accounts, banks)
    terminals = _get_card_terminals()
    payment_setups = _get_payment_method_setups()
    internal_transfers = _get_internal_transfers()
    shift_cash_movements = _get_shift_cash_movements()
    pending_dashboard = _get_pending_settlement_dashboard(
        terminals=terminals, payment_setups=payment_setups
    )

    return {
        "ok": True,
        "message": _("Treasury Management is working successfully."),
        "user": frappe.session.user,
        "companies": frappe.db.count("Company"),
        "cash_drawers": len(drawers),
        "cash_ledger_accounts": len(cash_accounts),
        "bank_institutions": frappe.db.count("Bank"),
        "bank_accounts": len(banks),
        "bank_ledger_accounts": len(bank_ledger_accounts),
        "card_terminals": len(terminals),
        "open_card_batches": sum(cint(row.get("open_batch_count")) for row in terminals),
        "clearing_setups": _safe_count("Payment Method Clearing Setup"),
        "open_payment_reconciliations": sum(cint(row.get("open_reconciliation_count")) for row in payment_setups),
        "internal_transfers": len(internal_transfers),
        "draft_internal_transfers": sum(1 for row in internal_transfers if cint(row.get("docstatus")) == 0),
        "shift_cash_movements": len(shift_cash_movements),
        "draft_shift_cash_movements": sum(1 for row in shift_cash_movements if cint(row.get("docstatus")) == 0),
        "drawers": drawers,
        "cash_accounts": cash_accounts,
        "account_warnings": account_warnings,
        "banks": banks,
        "bank_ledger_accounts_list": bank_ledger_accounts,
        "unlinked_bank_ledgers": unlinked_bank_ledgers,
        "terminals": terminals,
        "payment_setups": payment_setups,
        "internal_transfer_rows": internal_transfers,
        "shift_cash_movement_rows": shift_cash_movements,
        "pending_dashboard": pending_dashboard,
        "access_profile": access_profile,
        "can_create_cash_drawer": access_profile["can_manage"],
        "can_manage_cash_drawer": access_profile["can_manage"],
        "can_create_bank": access_profile["can_manage"],
        "can_manage_card_terminal": access_profile["can_manage"],
        "can_manage_payment_setup": access_profile["can_manage"],
        "can_prepare_settlement": access_profile["can_operate"],
        "can_execute_settlement": access_profile["can_manage"],
        "can_manage_internal_transfer": access_profile["can_operate"],
        "can_approve_internal_transfer": access_profile["can_manage"],
        "can_emergency_submit_internal_transfer": access_profile["can_emergency_submit"],
        "can_manage_shift_cash_movement": access_profile["can_operate"],
        "can_approve_shift_cash_movement": access_profile["can_manage"],
        "can_cancel_shift_cash_movement": access_profile["can_manage"],
        "can_emergency_submit_shift_cash_movement": access_profile["can_emergency_submit"],
    }


@frappe.whitelist()
def get_pending_settlement_dashboard():
    """Return pending clearing balances, overdue settlements and review alerts."""
    _validate_access()
    return _get_pending_settlement_dashboard()


@frappe.whitelist()
def get_payment_reconciliation_settlement_details(reconciliation_name):
    """Return validated details for settling one electronic reconciliation."""
    _validate_operator_access()
    doc = _get_open_payment_reconciliation(reconciliation_name)
    return _reconciliation_settlement_details(doc)


@frappe.whitelist()
def preview_payment_reconciliation_settlement(
    reconciliation_name,
    settlement_action,
    fee_amount=0,
    posting_date=None,
    bank_reference=None,
    existing_journal_entry=None,
    notes=None,
):
    """Validate and preview a settlement without changing accounting data."""
    _validate_operator_access()
    return _prepare_payment_reconciliation_settlement(
        reconciliation_name=reconciliation_name,
        settlement_action=settlement_action,
        fee_amount=fee_amount,
        posting_date=posting_date,
        bank_reference=bank_reference,
        existing_journal_entry=existing_journal_entry,
        notes=notes,
    )


@frappe.whitelist()
def execute_payment_reconciliation_settlement(
    reconciliation_name,
    settlement_action,
    fee_amount=0,
    posting_date=None,
    bank_reference=None,
    existing_journal_entry=None,
    notes=None,
):
    """Create or link the Journal Entry and close one reconciliation."""
    _validate_manager_access()
    plan = _prepare_payment_reconciliation_settlement(
        reconciliation_name=reconciliation_name,
        settlement_action=settlement_action,
        fee_amount=fee_amount,
        posting_date=posting_date,
        bank_reference=bank_reference,
        existing_journal_entry=existing_journal_entry,
        notes=notes,
    )
    doc = frappe.get_doc("Shift Payment Reconciliation", plan["reconciliation"])

    if plan["settlement_action"] == "Create New Journal Entry":
        journal = frappe.new_doc("Journal Entry")
        journal.voucher_type = "Journal Entry"
        journal.company = plan["company"]
        journal.posting_date = plan["posting_date"]
        reference_text = plan.get("bank_reference") or "-"
        journal.user_remark = (
            f"Treasury settlement {doc.name} / {doc.mode_of_payment} / "
            f"{doc.shift_reference} / reference {reference_text}"
        )
        if flt(plan["net_transfer_amount"]) > 0:
            journal.append(
                "accounts",
                {
                    "account": plan["destination_account"],
                    "debit_in_account_currency": flt(plan["net_transfer_amount"]),
                    "credit_in_account_currency": 0,
                },
            )
        if flt(plan["fee_amount"]) > 0:
            journal.append(
                "accounts",
                {
                    "account": plan["fee_account"],
                    "debit_in_account_currency": flt(plan["fee_amount"]),
                    "credit_in_account_currency": 0,
                },
            )
        journal.append(
            "accounts",
            {
                "account": plan["clearing_account"],
                "debit_in_account_currency": 0,
                "credit_in_account_currency": flt(plan["reviewed_amount"]),
            },
        )
        journal.flags.ignore_permissions = True
        journal.insert(ignore_permissions=True)
        journal.flags.ignore_permissions = True
        journal.submit()
        journal_name = journal.name
    else:
        journal_name = plan["existing_journal_entry"]

    note_parts = []
    if plan.get("bank_reference"):
        note_parts.append(_("Bank Reference: {0}").format(plan["bank_reference"]))
    if plan.get("notes"):
        note_parts.append(plan["notes"])
    stored_notes = "\n".join(note_parts) or (doc.notes or "")

    frappe.db.set_value(
        "Shift Payment Reconciliation",
        doc.name,
        {
            "reviewed_amount": flt(plan["reviewed_amount"]),
            "difference": flt(plan["difference"]),
            "fee_amount": flt(plan["fee_amount"]),
            "net_transfer_amount": flt(plan["net_transfer_amount"]),
            "reviewed_by": frappe.session.user,
            "reviewed_at": now_datetime(),
            "journal_entry": journal_name,
            "status": "Submitted",
            "notes": stored_notes,
        },
        update_modified=False,
    )
    frappe.db.commit()

    return {
        "ok": True,
        "message": _("Payment reconciliation was settled successfully."),
        "reconciliation": doc.name,
        "journal_entry": journal_name,
        "status": "Submitted",
        "settlement_action": plan["settlement_action"],
        "reviewed_amount": plan["reviewed_amount"],
        "fee_amount": plan["fee_amount"],
        "net_transfer_amount": plan["net_transfer_amount"],
    }


@frappe.whitelist()
def get_card_bank_settlement_options(batch_name):
    """Return compatible open card batches and bank-settlement defaults."""
    _validate_operator_access()
    return _card_bank_settlement_options(batch_name)


@frappe.whitelist()
def preview_card_bank_settlement(
    batch_name,
    allocations,
    settlement_date=None,
    bank_reference=None,
    fee_amount=0,
    statement_attachment=None,
    notes=None,
):
    """Validate a card bank settlement without creating accounting documents."""
    _validate_operator_access()
    return _prepare_card_bank_settlement(
        batch_name=batch_name,
        allocations=allocations,
        settlement_date=settlement_date,
        bank_reference=bank_reference,
        fee_amount=fee_amount,
        statement_attachment=statement_attachment,
        notes=notes,
    )


@frappe.whitelist()
def execute_card_bank_settlement(
    batch_name,
    allocations,
    settlement_date=None,
    bank_reference=None,
    fee_amount=0,
    statement_attachment=None,
    notes=None,
):
    """Create and submit Card Bank Settlement for selected open batches."""
    _validate_manager_access()
    plan = _prepare_card_bank_settlement(
        batch_name=batch_name,
        allocations=allocations,
        settlement_date=settlement_date,
        bank_reference=bank_reference,
        fee_amount=fee_amount,
        statement_attachment=statement_attachment,
        notes=notes,
    )

    batch_names = tuple(row["card_settlement_batch"] for row in plan["allocations"])
    if batch_names:
        frappe.db.sql(
            """
            SELECT name
            FROM `tabCard Settlement Batch`
            WHERE name IN %(batch_names)s
            FOR UPDATE
            """,
            {"batch_names": batch_names},
        )

    # Revalidate after locking to prevent two users settling the same amount.
    plan = _prepare_card_bank_settlement(
        batch_name=batch_name,
        allocations=allocations,
        settlement_date=settlement_date,
        bank_reference=bank_reference,
        fee_amount=fee_amount,
        statement_attachment=statement_attachment,
        notes=notes,
    )

    settlement = frappe.new_doc("Card Bank Settlement")
    settlement.company = plan["company"]
    settlement.settlement_date = plan["settlement_date"]
    settlement.bank_reference = plan["bank_reference"]
    settlement.statement_attachment = plan.get("statement_attachment") or ""
    settlement.destination_bank_account = plan["destination_bank_account"]
    settlement.clearing_account = plan["clearing_account"]
    settlement.fee_account = plan.get("fee_account") or ""
    settlement.fee_amount = flt(plan["fee_amount"])
    settlement.notes = plan.get("notes") or ""

    for row in plan["allocations"]:
        settlement.append(
            "allocations",
            {
                "card_settlement_batch": row["card_settlement_batch"],
                "pos_terminal": row.get("pos_terminal") or "",
                "batch_number": row.get("batch_number") or "",
                "available_amount": flt(row["available_amount"]),
                "allocated_amount": flt(row["allocated_amount"]),
            },
        )

    settlement.flags.ignore_permissions = True
    settlement.insert(ignore_permissions=True)
    settlement.flags.ignore_permissions = True
    settlement.submit()

    journal_entry = frappe.db.get_value(
        "Card Bank Settlement", settlement.name, "journal_entry"
    ) or ""
    updated_batches = frappe.get_all(
        "Card Settlement Batch",
        filters={"name": ["in", list(batch_names)]},
        fields=[
            "name",
            "status",
            "settled_amount",
            "outstanding_amount",
            "bank_settlement",
        ],
        order_by="name asc",
        limit_page_length=500,
    )
    frappe.db.commit()

    return {
        "ok": True,
        "message": _("Card bank settlement was submitted successfully."),
        "card_bank_settlement": settlement.name,
        "journal_entry": journal_entry,
        "gross_amount": flt(plan["gross_amount"]),
        "fee_amount": flt(plan["fee_amount"]),
        "net_amount": flt(plan["net_amount"]),
        "batches": updated_batches,
    }


@frappe.whitelist()
def get_internal_transfer_options(company=None):
    """Return eligible Asset Cash/Bank accounts and live balances."""
    _validate_operator_access()
    company = _resolve_company(company)
    return {
        "company": company,
        "company_currency": frappe.db.get_value("Company", company, "default_currency") or "",
        "posting_date": nowdate(),
        "reference_date": nowdate(),
        "accounts": _get_internal_transfer_accounts(company),
    }


@frappe.whitelist()
def preview_internal_transfer(
    company,
    paid_from,
    paid_to,
    amount,
    posting_date=None,
    reference_no=None,
    reference_date=None,
    remarks=None,
    transfer_action="Create Draft",
):
    """Validate and preview a Cash/Bank internal transfer without writing data."""
    _validate_operator_access()
    _validate_internal_transfer_action_access(transfer_action)
    return _prepare_internal_transfer(
        company=company,
        paid_from=paid_from,
        paid_to=paid_to,
        amount=amount,
        posting_date=posting_date,
        reference_no=reference_no,
        reference_date=reference_date,
        remarks=remarks,
        transfer_action=transfer_action,
    )


@frappe.whitelist()
def execute_internal_transfer(
    company,
    paid_from,
    paid_to,
    amount,
    posting_date=None,
    reference_no=None,
    reference_date=None,
    remarks=None,
    transfer_action="Create Draft",
):
    """Create a Treasury Internal Transfer request or emergency submission."""
    _validate_operator_access()
    _validate_internal_transfer_action_access(transfer_action)
    plan = _prepare_internal_transfer(
        company=company,
        paid_from=paid_from,
        paid_to=paid_to,
        amount=amount,
        posting_date=posting_date,
        reference_no=reference_no,
        reference_date=reference_date,
        remarks=remarks,
        transfer_action=transfer_action,
    )

    payment = frappe.new_doc("Payment Entry")
    payment.payment_type = "Internal Transfer"
    payment.company = plan["company"]
    payment.posting_date = plan["posting_date"]
    payment.paid_from = plan["paid_from"]
    payment.paid_to = plan["paid_to"]
    payment.paid_from_account_currency = plan["account_currency"]
    payment.paid_to_account_currency = plan["account_currency"]
    payment.paid_amount = flt(plan["amount"])
    payment.received_amount = flt(plan["amount"])
    payment.source_exchange_rate = 1
    payment.target_exchange_rate = 1
    payment.reference_no = plan["reference_no"]
    payment.reference_date = plan["reference_date"]
    payment.remarks = plan["remarks"] or (
        f"Treasury internal transfer from {plan['paid_from']} to {plan['paid_to']}"
    )
    if payment.meta.has_field("custom_treasury_internal_transfer"):
        payment.custom_treasury_internal_transfer = 1
    if payment.meta.has_field("custom_treasury_request_status"):
        payment.custom_treasury_request_status = "Pending Approval"
    if payment.meta.has_field("custom_treasury_requested_by"):
        payment.custom_treasury_requested_by = frappe.session.user
    if payment.meta.has_field("custom_treasury_requested_at"):
        payment.custom_treasury_requested_at = now_datetime()
    payment.flags.ignore_permissions = True
    payment.insert(ignore_permissions=True)

    if plan["transfer_action"] == "Submit Now":
        payment.flags.ignore_permissions = True
        payment.submit()

    frappe.db.commit()
    return {
        "ok": True,
        "message": _("Internal transfer was created successfully."),
        "payment_entry": payment.name,
        "docstatus": payment.docstatus,
        "status": "Submitted" if payment.docstatus == 1 else "Pending Approval",
        "requested_by": getattr(payment, "custom_treasury_requested_by", None) or payment.owner,
        "approved_by": getattr(payment, "custom_treasury_approved_by", None),
        "paid_from": plan["paid_from"],
        "paid_to": plan["paid_to"],
        "amount": plan["amount"],
        "account_currency": plan["account_currency"],
    }


@frappe.whitelist()
def submit_internal_transfer(payment_entry_name):
    """Approve and submit an existing Draft Internal Transfer."""
    _validate_manager_access()
    payment_entry_name = str(payment_entry_name or "").strip()
    if not payment_entry_name or not frappe.db.exists("Payment Entry", payment_entry_name):
        frappe.throw(_("Payment Entry was not found."))

    payment = frappe.get_doc("Payment Entry", payment_entry_name)
    if payment.payment_type != "Internal Transfer":
        frappe.throw(_("Only Internal Transfer Payment Entries can be submitted here."))
    if payment.docstatus != 0:
        frappe.throw(_("Only a Draft Internal Transfer can be submitted."))

    _prepare_internal_transfer(
        company=payment.company,
        paid_from=payment.paid_from,
        paid_to=payment.paid_to,
        amount=payment.paid_amount,
        posting_date=payment.posting_date,
        reference_no=payment.reference_no,
        reference_date=payment.reference_date,
        remarks=payment.remarks,
        transfer_action="Create Draft",
        exclude_payment_entry=payment.name,
    )
    validate_internal_transfer_approver(payment)

    payment.flags.ignore_permissions = True
    payment.submit()
    frappe.db.commit()
    return {
        "ok": True,
        "message": _("Internal transfer was submitted successfully."),
        "payment_entry": payment.name,
        "status": "Submitted",
        "requested_by": getattr(payment, "custom_treasury_requested_by", None) or payment.owner,
        "approved_by": getattr(payment, "custom_treasury_approved_by", None) or frappe.session.user,
    }


@frappe.whitelist()
def get_shift_cash_movement_options(company=None):
    """Return open drawers, movement rules and defaults for a shift cash request."""
    _validate_operator_access()
    company = _resolve_company(company)
    drawers = _get_shift_cash_movement_drawers(company)
    return {
        "company": company,
        "company_currency": frappe.db.get_value("Company", company, "default_currency") or "",
        "movement_date": now_datetime().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S"),
        "reference_date": nowdate(),
        "drawers": drawers,
        "movement_types": _get_shift_cash_movement_type_options(),
        "default_cash_drawer": drawers[0]["name"] if len(drawers) == 1 else "",
    }


@frappe.whitelist()
def preview_shift_cash_movement(
    company,
    cash_drawer,
    shift_reference,
    movement_type,
    amount,
    counter_account,
    movement_date=None,
    direction=None,
    reference_no=None,
    reference_date=None,
    description=None,
    supplier=None,
    purchase_invoice=None,
    employee=None,
    receipt_attachment=None,
    movement_action="Create Draft",
):
    """Validate and preview one shift cash movement without writing data."""
    _validate_operator_access()
    _validate_shift_cash_movement_action_access(movement_action)
    return _prepare_shift_cash_movement(
        company=company,
        cash_drawer=cash_drawer,
        shift_reference=shift_reference,
        movement_type=movement_type,
        amount=amount,
        counter_account=counter_account,
        movement_date=movement_date,
        direction=direction,
        reference_no=reference_no,
        reference_date=reference_date,
        description=description,
        supplier=supplier,
        purchase_invoice=purchase_invoice,
        employee=employee,
        receipt_attachment=receipt_attachment,
        movement_action=movement_action,
    )


@frappe.whitelist()
def execute_shift_cash_movement(
    company,
    cash_drawer,
    shift_reference,
    movement_type,
    amount,
    counter_account,
    movement_date=None,
    direction=None,
    reference_no=None,
    reference_date=None,
    description=None,
    supplier=None,
    purchase_invoice=None,
    employee=None,
    receipt_attachment=None,
    movement_action="Create Draft",
):
    """Create a draft cash movement request or emergency-submit it."""
    _validate_operator_access()
    _validate_shift_cash_movement_action_access(movement_action)
    plan = _prepare_shift_cash_movement(
        company=company,
        cash_drawer=cash_drawer,
        shift_reference=shift_reference,
        movement_type=movement_type,
        amount=amount,
        counter_account=counter_account,
        movement_date=movement_date,
        direction=direction,
        reference_no=reference_no,
        reference_date=reference_date,
        description=description,
        supplier=supplier,
        purchase_invoice=purchase_invoice,
        employee=employee,
        receipt_attachment=receipt_attachment,
        movement_action=movement_action,
    )

    movement = frappe.new_doc("Shift Cash Movement")
    for fieldname in (
        "company",
        "cash_drawer",
        "shift_reference",
        "movement_type",
        "direction",
        "amount",
        "movement_date",
        "source_account",
        "target_account",
        "expense_account",
        "supplier",
        "purchase_invoice",
        "employee",
        "reference_no",
        "reference_date",
        "description",
        "receipt_attachment",
    ):
        if fieldname in plan:
            setattr(movement, fieldname, plan.get(fieldname))

    movement.flags.ignore_permissions = True
    movement.insert(ignore_permissions=True)
    if plan["movement_action"] == "Submit Now":
        movement.flags.ignore_permissions = True
        movement.submit()

    frappe.db.commit()
    return {
        "ok": True,
        "message": _("Shift cash movement was created successfully."),
        "shift_cash_movement": movement.name,
        "docstatus": movement.docstatus,
        "status": "Posted" if movement.docstatus == 1 else "Pending Approval",
        "journal_entry": frappe.db.get_value("Shift Cash Movement", movement.name, "journal_entry"),
        "amount": flt(movement.amount),
        "currency": plan["currency"],
        "requested_by": movement.requested_by or movement.owner,
        "approved_by": movement.approved_by,
    }


@frappe.whitelist()
def submit_shift_cash_movement(movement_name):
    """Approve and submit an existing draft shift cash movement."""
    _validate_manager_access()
    movement_name = str(movement_name or "").strip()
    if not movement_name or not frappe.db.exists("Shift Cash Movement", movement_name):
        frappe.throw(_("Shift Cash Movement was not found."))

    movement = frappe.get_doc("Shift Cash Movement", movement_name)
    if movement.docstatus != 0:
        frappe.throw(_("Only a Draft Shift Cash Movement can be submitted."))
    movement.flags.ignore_permissions = True
    movement.submit()
    frappe.db.commit()
    return {
        "ok": True,
        "message": _("Shift cash movement was approved and posted successfully."),
        "shift_cash_movement": movement.name,
        "journal_entry": movement.journal_entry,
        "status": "Posted",
    }


@frappe.whitelist()
def cancel_shift_cash_movement(movement_name):
    """Cancel a posted shift cash movement and its generated Journal Entry."""
    _validate_manager_access()
    movement_name = str(movement_name or "").strip()
    if not movement_name or not frappe.db.exists("Shift Cash Movement", movement_name):
        frappe.throw(_("Shift Cash Movement was not found."))

    movement = frappe.get_doc("Shift Cash Movement", movement_name)
    if movement.docstatus != 1:
        frappe.throw(_("Only a submitted Shift Cash Movement can be cancelled."))
    movement.flags.ignore_permissions = True
    movement.cancel()
    frappe.db.commit()
    return {
        "ok": True,
        "message": _("Shift cash movement and its Journal Entry were cancelled."),
        "shift_cash_movement": movement.name,
        "status": "Cancelled",
    }


@frappe.whitelist()
def get_cash_drawer_creation_options(company=None):
    """Return safe defaults for the create-cash-drawer dialog."""
    _validate_create_access()

    company = _resolve_company(company)
    currency = frappe.db.get_value("Company", company, "default_currency") or ""
    parent_accounts = _cash_parent_accounts(company)

    return {
        "company": company,
        "account_currency": currency,
        "suggested_drawer_code": _next_drawer_code(),
        "default_parent_account": parent_accounts[0]["name"] if parent_accounts else "",
        "parent_accounts": parent_accounts,
    }


@frappe.whitelist()
def preview_cash_drawer(
    drawer_name,
    drawer_code,
    company,
    account_name,
    parent_account,
    branch=None,
    physical_location=None,
    default_opening_float=0,
    **kwargs,
):
    """Validate and return exactly what will be created, without writing data."""
    _validate_create_access()
    return _prepare_cash_drawer_payload(
        drawer_name=drawer_name,
        drawer_code=drawer_code,
        company=company,
        account_name=account_name,
        parent_account=parent_account,
        branch=branch,
        physical_location=physical_location,
        default_opening_float=default_opening_float,
    )


@frappe.whitelist()
def create_cash_drawer(
    drawer_name,
    drawer_code,
    company,
    account_name,
    parent_account,
    branch=None,
    physical_location=None,
    default_opening_float=0,
    **kwargs,
):
    """Create a Cash account and its Cash Drawer after final server validation."""
    _validate_create_access()

    payload = _prepare_cash_drawer_payload(
        drawer_name=drawer_name,
        drawer_code=drawer_code,
        company=company,
        account_name=account_name,
        parent_account=parent_account,
        branch=branch,
        physical_location=physical_location,
        default_opening_float=default_opening_float,
    )

    account = frappe.new_doc("Account")
    account.account_name = payload["account_name"]
    account.company = payload["company"]
    account.parent_account = payload["parent_account"]
    account.is_group = 0
    account.account_type = "Cash"
    account.account_currency = payload["account_currency"]
    account.flags.ignore_permissions = True
    account.insert(ignore_permissions=True)

    drawer = frappe.new_doc("Cash Drawer")
    drawer.drawer_name = payload["drawer_name"]
    drawer.drawer_code = payload["drawer_code"]
    drawer.company = payload["company"]
    drawer.branch = payload["branch"] or None
    drawer.physical_location = payload["physical_location"] or None
    drawer.enabled = 1
    drawer.cash_account = account.name
    drawer.default_opening_float = payload["default_opening_float"]
    drawer.flags.ignore_permissions = True
    drawer.insert(ignore_permissions=True)

    drawer.add_comment(
        "Comment",
        _("Created from Treasury Management with cash account {0}.").format(account.name),
    )

    return {
        "ok": True,
        "drawer": drawer.name,
        "drawer_name": drawer.drawer_name,
        "cash_account": account.name,
        "message": _("Cash drawer and cash account were created successfully."),
    }


@frappe.whitelist()
def get_cash_drawer_activity(drawer_name, limit=20):
    """Return the live balance and latest posted ledger movements for a drawer."""
    _validate_access()

    drawer_name = str(drawer_name or "").strip()
    if not drawer_name or not frappe.db.exists("Cash Drawer", drawer_name):
        frappe.throw(_("Cash Drawer was not found."))

    drawer = frappe.get_doc("Cash Drawer", drawer_name)
    if not drawer.cash_account:
        frappe.throw(_("The Cash Drawer has no Cash Account."))

    limit = max(1, min(cint(limit) or 20, 100))
    account = _validate_drawer_account(drawer)
    balance = _account_balance(drawer.cash_account, drawer.company)

    rows = frappe.get_all(
        "GL Entry",
        filters={
            "account": drawer.cash_account,
            "is_cancelled": 0,
        },
        fields=[
            "name",
            "posting_date",
            "creation",
            "voucher_type",
            "voucher_no",
            "debit",
            "credit",
            "against",
            "remarks",
        ],
        order_by="posting_date desc, creation desc",
        limit_page_length=limit,
    )

    for row in rows:
        row["debit"] = flt(row.get("debit"))
        row["credit"] = flt(row.get("credit"))
        row["net_movement"] = flt(row["debit"] - row["credit"])

    return {
        "drawer": drawer.name,
        "drawer_name": drawer.drawer_name,
        "company": drawer.company,
        "cash_account": drawer.cash_account,
        "account_currency": account.get("account_currency") or "",
        "enabled": cint(drawer.enabled),
        "current_active_shift": drawer.current_active_shift or "",
        "current_responsible_user": drawer.current_responsible_user or "",
        "current_balance": balance,
        "movements": rows,
    }


@frappe.whitelist()
def set_cash_drawer_enabled(drawer_name, enabled):
    """Enable or disable a drawer without disabling its ledger account."""
    _validate_create_access()

    drawer_name = str(drawer_name or "").strip()
    if not drawer_name or not frappe.db.exists("Cash Drawer", drawer_name):
        frappe.throw(_("Cash Drawer was not found."))

    drawer = frappe.get_doc("Cash Drawer", drawer_name)
    enabled = cint(enabled)

    if enabled:
        _validate_drawer_account(drawer)
    else:
        open_shift = _find_open_shift_for_drawer(drawer)
        if open_shift:
            frappe.throw(
                _("Cannot disable this drawer while shift {0} is still open.").format(
                    open_shift
                )
            )

        # Clear stale operational links only after proving that no open shift exists.
        drawer.current_active_shift = None
        drawer.current_responsible_user = None

    if cint(drawer.enabled) != enabled:
        drawer.enabled = enabled
        drawer.flags.ignore_permissions = True
        drawer.save(ignore_permissions=True)
        drawer.add_comment(
            "Comment",
            _("Cash Drawer {0} from Treasury Management.").format(
                _("enabled") if enabled else _("disabled")
            ),
        )

    return {
        "drawer": drawer.name,
        "enabled": cint(drawer.enabled),
        "message": _("Cash Drawer status was updated successfully."),
    }



@frappe.whitelist()
def get_bank_creation_options(company=None):
    """Return safe defaults for registering a bank and its accounting records."""
    _validate_create_access()

    company = _resolve_company(company)
    currency = frappe.db.get_value("Company", company, "default_currency") or ""
    bank_parents = _bank_parent_accounts(company)
    clearing_parents = _clearing_parent_accounts(company)
    fee_parents = _fee_parent_accounts(company)

    return {
        "company": company,
        "account_currency": currency,
        "default_bank_parent_account": bank_parents[0]["name"] if bank_parents else "",
        "default_clearing_parent_account": clearing_parents[0]["name"] if clearing_parents else "",
        "default_fee_parent_account": fee_parents[0]["name"] if fee_parents else "",
        "unlinked_bank_accounts": _get_unlinked_bank_ledgers(),
    }


@frappe.whitelist()
def preview_bank_setup(
    bank_name,
    company,
    bank_account_name,
    ledger_mode="Create New Account",
    existing_ledger_account=None,
    ledger_account_name=None,
    bank_parent_account=None,
    swift_number=None,
    website=None,
    bank_account_no=None,
    iban=None,
    branch_code=None,
    create_card_clearing=1,
    card_clearing_name=None,
    create_instapay_clearing=0,
    instapay_clearing_name=None,
    clearing_parent_account=None,
    create_fee_account=1,
    fee_account_name=None,
    fee_parent_account=None,
    **kwargs,
):
    """Validate and preview a bank setup without writing any records."""
    _validate_create_access()
    return _prepare_bank_setup_payload(
        bank_name=bank_name,
        company=company,
        bank_account_name=bank_account_name,
        ledger_mode=ledger_mode,
        existing_ledger_account=existing_ledger_account,
        ledger_account_name=ledger_account_name,
        bank_parent_account=bank_parent_account,
        swift_number=swift_number,
        website=website,
        bank_account_no=bank_account_no,
        iban=iban,
        branch_code=branch_code,
        create_card_clearing=create_card_clearing,
        card_clearing_name=card_clearing_name,
        create_instapay_clearing=create_instapay_clearing,
        instapay_clearing_name=instapay_clearing_name,
        clearing_parent_account=clearing_parent_account,
        create_fee_account=create_fee_account,
        fee_account_name=fee_account_name,
        fee_parent_account=fee_parent_account,
    )


@frappe.whitelist()
def create_bank_setup(
    bank_name,
    company,
    bank_account_name,
    ledger_mode="Create New Account",
    existing_ledger_account=None,
    ledger_account_name=None,
    bank_parent_account=None,
    swift_number=None,
    website=None,
    bank_account_no=None,
    iban=None,
    branch_code=None,
    create_card_clearing=1,
    card_clearing_name=None,
    create_instapay_clearing=0,
    instapay_clearing_name=None,
    clearing_parent_account=None,
    create_fee_account=1,
    fee_account_name=None,
    fee_parent_account=None,
    **kwargs,
):
    """Create or reuse the bank master, then create its linked company Bank Account."""
    _validate_create_access()
    payload = _prepare_bank_setup_payload(
        bank_name=bank_name,
        company=company,
        bank_account_name=bank_account_name,
        ledger_mode=ledger_mode,
        existing_ledger_account=existing_ledger_account,
        ledger_account_name=ledger_account_name,
        bank_parent_account=bank_parent_account,
        swift_number=swift_number,
        website=website,
        bank_account_no=bank_account_no,
        iban=iban,
        branch_code=branch_code,
        create_card_clearing=create_card_clearing,
        card_clearing_name=card_clearing_name,
        create_instapay_clearing=create_instapay_clearing,
        instapay_clearing_name=instapay_clearing_name,
        clearing_parent_account=clearing_parent_account,
        create_fee_account=create_fee_account,
        fee_account_name=fee_account_name,
        fee_parent_account=fee_parent_account,
    )

    if payload["bank_master_action"] == "create":
        bank = frappe.new_doc("Bank")
        bank.bank_name = payload["bank_name"]
        bank.swift_number = payload["swift_number"] or None
        bank.website = payload["website"] or None
        bank.flags.ignore_permissions = True
        bank.insert(ignore_permissions=True)
        bank_name_value = bank.name
    else:
        bank_name_value = payload["bank_name"]

    if payload["ledger_account"]["action"] == "create":
        ledger_account = _create_account_from_plan(payload["ledger_account"])
    else:
        ledger_account = payload["ledger_account"]["document_name"]

    bank_account = frappe.new_doc("Bank Account")
    bank_account.account_name = payload["bank_account_name"]
    bank_account.bank = bank_name_value
    bank_account.account = ledger_account
    bank_account.company = payload["company"]
    bank_account.is_company_account = 1
    bank_account.disabled = 0
    bank_account.bank_account_no = payload["bank_account_no"] or None
    bank_account.iban = payload["iban"] or None
    bank_account.branch_code = payload["branch_code"] or None
    bank_account.flags.ignore_permissions = True
    bank_account.insert(ignore_permissions=True)

    created_accounts = {"bank_ledger_account": ledger_account}
    for key in ("card_clearing_account", "instapay_clearing_account", "fee_account"):
        plan = payload.get(key)
        if not plan:
            continue
        created_accounts[key] = (
            _create_account_from_plan(plan)
            if plan["action"] == "create"
            else plan["document_name"]
        )

    bank_account.add_comment(
        "Comment",
        _("Created from Treasury Management and linked to ledger account {0}.").format(
            ledger_account
        ),
    )

    return {
        "ok": True,
        "bank": bank_name_value,
        "bank_account": bank_account.name,
        "ledger_account": ledger_account,
        "accounts": created_accounts,
        "message": _("Bank setup was created successfully."),
    }


@frappe.whitelist()
def get_bank_account_activity(bank_account_name, limit=20):
    """Return balance and latest ledger movements for an ERPNext Bank Account."""
    _validate_access()

    bank_account_name = _clean_master_text(bank_account_name)
    if not bank_account_name or not frappe.db.exists("Bank Account", bank_account_name):
        frappe.throw(_("Bank Account was not found."))

    bank_account = frappe.get_doc("Bank Account", bank_account_name)
    if not bank_account.account:
        frappe.throw(_("The Bank Account is not linked to a company ledger account."))

    account = _validate_company_account(
        bank_account.account,
        bank_account.company,
        expected_root="Asset",
        expected_type="Bank",
        label=_("Bank Ledger Account"),
    )
    limit = max(1, min(cint(limit) or 20, 100))
    movements = frappe.get_all(
        "GL Entry",
        filters={"account": bank_account.account, "is_cancelled": 0},
        fields=[
            "name",
            "posting_date",
            "creation",
            "voucher_type",
            "voucher_no",
            "debit",
            "credit",
            "against",
            "remarks",
        ],
        order_by="posting_date desc, creation desc",
        limit_page_length=limit,
    )
    for row in movements:
        row["debit"] = flt(row.get("debit"))
        row["credit"] = flt(row.get("credit"))
        row["net_movement"] = flt(row["debit"] - row["credit"])

    return {
        "bank_account": bank_account.name,
        "account_name": bank_account.account_name,
        "bank": bank_account.bank,
        "company": bank_account.company,
        "ledger_account": bank_account.account,
        "account_currency": account.get("account_currency") or "",
        "current_balance": _account_balance(bank_account.account, bank_account.company),
        "disabled": cint(bank_account.disabled),
        "bank_account_no": bank_account.bank_account_no or "",
        "iban": bank_account.iban or "",
        "movements": movements,
    }



@frappe.whitelist()
def get_payment_method_setup_options(company=None, setup_name=None):
    """Return defaults for creating or editing a Payment Method Clearing Setup."""
    _validate_create_access()
    if not frappe.db.exists("DocType", "Payment Method Clearing Setup"):
        frappe.throw(_("Payment Method Clearing Setup is not installed."))

    company = _resolve_company(company)
    setup = None
    if setup_name:
        setup_name = _clean_master_text(setup_name)
        if not frappe.db.exists("Payment Method Clearing Setup", setup_name):
            frappe.throw(_("Payment Method Clearing Setup was not found."))
        setup = frappe.get_doc("Payment Method Clearing Setup", setup_name)
        company = setup.company

    clearing_parents = _clearing_parent_accounts(company)
    destination_parents = _bank_parent_accounts(company)
    default_mode = _default_non_card_mode_of_payment()
    default_fee = setup.fee_account if setup else _default_fee_account(company)

    bank_account = ""
    if setup:
        bank_account = frappe.db.get_value(
            "Bank Account",
            {
                "company": company,
                "account": setup.destination_account,
                "disabled": 0,
                "is_company_account": 1,
            },
            "name",
        ) or ""

    return {
        "company": company,
        "default_mode_of_payment": setup.mode_of_payment if setup else default_mode,
        "default_settlement_policy": setup.settlement_policy if setup else "At Shift Closing",
        "default_clearing_parent_account": clearing_parents[0]["name"] if clearing_parents else "",
        "default_destination_parent_account": destination_parents[0]["name"] if destination_parents else "",
        "default_fee_account": default_fee or "",
        "setup": _serialize_payment_setup_for_edit(setup, bank_account) if setup else None,
    }


@frappe.whitelist()
def preview_payment_method_setup(
    company,
    mode_of_payment,
    settlement_policy,
    destination_mode="Use Bank Account",
    bank_account=None,
    existing_destination_account=None,
    destination_account_name=None,
    destination_parent_account=None,
    clearing_mode="Use Existing Account",
    existing_clearing_account=None,
    clearing_account_name=None,
    clearing_parent_account=None,
    fee_account=None,
    notes=None,
    enabled=1,
    existing_setup=None,
    **kwargs,
):
    """Validate and preview a clearing setup without writing data."""
    _validate_create_access()
    return _prepare_payment_method_setup_payload(
        company=company,
        mode_of_payment=mode_of_payment,
        settlement_policy=settlement_policy,
        destination_mode=destination_mode,
        bank_account=bank_account,
        existing_destination_account=existing_destination_account,
        destination_account_name=destination_account_name,
        destination_parent_account=destination_parent_account,
        clearing_mode=clearing_mode,
        existing_clearing_account=existing_clearing_account,
        clearing_account_name=clearing_account_name,
        clearing_parent_account=clearing_parent_account,
        fee_account=fee_account,
        notes=notes,
        enabled=enabled,
        existing_setup=existing_setup,
    )


@frappe.whitelist()
def save_payment_method_setup(
    company,
    mode_of_payment,
    settlement_policy,
    destination_mode="Use Bank Account",
    bank_account=None,
    existing_destination_account=None,
    destination_account_name=None,
    destination_parent_account=None,
    clearing_mode="Use Existing Account",
    existing_clearing_account=None,
    clearing_account_name=None,
    clearing_parent_account=None,
    fee_account=None,
    notes=None,
    enabled=1,
    existing_setup=None,
    **kwargs,
):
    """Create or update a Payment Method Clearing Setup after final validation."""
    _validate_create_access()
    payload = _prepare_payment_method_setup_payload(
        company=company,
        mode_of_payment=mode_of_payment,
        settlement_policy=settlement_policy,
        destination_mode=destination_mode,
        bank_account=bank_account,
        existing_destination_account=existing_destination_account,
        destination_account_name=destination_account_name,
        destination_parent_account=destination_parent_account,
        clearing_mode=clearing_mode,
        existing_clearing_account=existing_clearing_account,
        clearing_account_name=clearing_account_name,
        clearing_parent_account=clearing_parent_account,
        fee_account=fee_account,
        notes=notes,
        enabled=enabled,
        existing_setup=existing_setup,
    )

    clearing_plan = payload["clearing_account"]
    clearing_account = (
        _create_account_from_plan(clearing_plan)
        if clearing_plan["action"] == "create"
        else clearing_plan["document_name"]
    )
    destination_plan = payload["destination_account"]
    destination_account = (
        _create_account_from_plan(destination_plan)
        if destination_plan["action"] == "create"
        else destination_plan["document_name"]
    )

    if payload["action"] == "update":
        doc = frappe.get_doc("Payment Method Clearing Setup", payload["existing_setup"])
    else:
        doc = frappe.new_doc("Payment Method Clearing Setup")

    doc.company = payload["company"]
    doc.mode_of_payment = payload["mode_of_payment"]
    doc.enabled = payload["enabled"]
    doc.settlement_policy = payload["settlement_policy"]
    doc.clearing_account = clearing_account
    doc.destination_account = destination_account
    doc.fee_account = payload["fee_account"] or None
    doc.notes = payload["notes"] or None
    doc.flags.ignore_permissions = True
    if payload["action"] == "create":
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    if payload["enabled"]:
        _sync_mode_of_payment_account(
            payload["mode_of_payment"], payload["company"], clearing_account
        )

    doc.add_comment(
        "Comment",
        _("{0} from Treasury Management.").format(
            _("Created") if payload["action"] == "create" else _("Updated")
        ),
    )

    return {
        "ok": True,
        "setup": doc.name,
        "mode_of_payment": doc.mode_of_payment,
        "clearing_account": doc.clearing_account,
        "destination_account": doc.destination_account,
        "action": payload["action"],
        "message": _("Payment Method Clearing Setup was saved successfully."),
    }


@frappe.whitelist()
def get_payment_method_setup_activity(setup_name, limit=20):
    """Return balances, movements and open shift reconciliations for a setup."""
    _validate_access()
    setup_name = _clean_master_text(setup_name)
    if not setup_name or not frappe.db.exists("Payment Method Clearing Setup", setup_name):
        frappe.throw(_("Payment Method Clearing Setup was not found."))

    setup = frappe.get_doc("Payment Method Clearing Setup", setup_name)
    clearing = _validate_company_account(
        setup.clearing_account,
        setup.company,
        expected_root="Asset",
        expected_type=None,
        label=_("Clearing Account"),
    )
    destination = _validate_company_account(
        setup.destination_account,
        setup.company,
        expected_root="Asset",
        expected_type=None,
        label=_("Destination Account"),
    )
    limit = max(1, min(cint(limit) or 20, 100))

    def movements(account):
        rows = frappe.get_all(
            "GL Entry",
            filters={"account": account, "is_cancelled": 0},
            fields=[
                "name", "posting_date", "creation", "voucher_type", "voucher_no",
                "debit", "credit", "against", "remarks",
            ],
            order_by="posting_date desc, creation desc",
            limit_page_length=limit,
        )
        for row in rows:
            row["debit"] = flt(row.get("debit"))
            row["credit"] = flt(row.get("credit"))
            row["net_movement"] = flt(row["debit"] - row["credit"])
        return rows

    reconciliations = _get_open_payment_reconciliations(setup.name, limit=100)
    return {
        "setup": setup.name,
        "company": setup.company,
        "mode_of_payment": setup.mode_of_payment,
        "settlement_policy": setup.settlement_policy,
        "enabled": cint(setup.enabled),
        "clearing_account": setup.clearing_account,
        "destination_account": setup.destination_account,
        "fee_account": setup.fee_account or "",
        "account_currency": clearing.get("account_currency") or destination.get("account_currency") or "",
        "clearing_balance": _account_balance(setup.clearing_account, setup.company),
        "destination_balance": _account_balance(setup.destination_account, setup.company),
        "open_reconciliation_count": len(reconciliations),
        "open_expected_amount": sum(flt(row.get("expected_amount")) for row in reconciliations),
        "open_reconciliations": reconciliations,
        "clearing_movements": movements(setup.clearing_account),
        "destination_movements": movements(setup.destination_account),
    }


@frappe.whitelist()
def set_payment_method_setup_enabled(setup_name, enabled):
    """Enable or disable a setup, blocking disable while open reconciliations exist."""
    _validate_create_access()
    setup_name = _clean_master_text(setup_name)
    if not setup_name or not frappe.db.exists("Payment Method Clearing Setup", setup_name):
        frappe.throw(_("Payment Method Clearing Setup was not found."))

    setup = frappe.get_doc("Payment Method Clearing Setup", setup_name)
    enabled = cint(enabled)
    if enabled:
        if not frappe.db.exists("Mode of Payment", setup.mode_of_payment):
            frappe.throw(_("Mode of Payment was not found."))
        _validate_company_account(setup.clearing_account, setup.company, "Asset", None, _("Clearing Account"))
        _validate_company_account(setup.destination_account, setup.company, "Asset", None, _("Destination Account"))
        if setup.fee_account:
            _validate_company_account(setup.fee_account, setup.company, "Expense", None, _("Fee Account"))
    else:
        open_rows = _get_open_payment_reconciliations(setup.name, limit=5)
        if open_rows:
            names = ", ".join(row.name for row in open_rows)
            frappe.throw(
                _("Cannot disable this setup while open reconciliations exist: {0}.").format(names)
            )

    if cint(setup.enabled) != enabled:
        setup.enabled = enabled
        setup.flags.ignore_permissions = True
        setup.save(ignore_permissions=True)
        if enabled:
            _sync_mode_of_payment_account(
                setup.mode_of_payment, setup.company, setup.clearing_account
            )
        setup.add_comment(
            "Comment",
            _("Payment Method Clearing Setup {0} from Treasury Management.").format(
                _("enabled") if enabled else _("disabled")
            ),
        )

    return {
        "setup": setup.name,
        "enabled": cint(setup.enabled),
        "message": _("Payment Method Clearing Setup status was updated successfully."),
    }


def _prepare_payment_method_setup_payload(
    company,
    mode_of_payment,
    settlement_policy,
    destination_mode="Use Bank Account",
    bank_account=None,
    existing_destination_account=None,
    destination_account_name=None,
    destination_parent_account=None,
    clearing_mode="Use Existing Account",
    existing_clearing_account=None,
    clearing_account_name=None,
    clearing_parent_account=None,
    fee_account=None,
    notes=None,
    enabled=1,
    existing_setup=None,
):
    if not frappe.db.exists("DocType", "Payment Method Clearing Setup"):
        frappe.throw(_("Payment Method Clearing Setup is not installed."))

    company = _resolve_company(company)
    mode_of_payment = _clean_master_text(mode_of_payment)
    settlement_policy = str(settlement_policy or "").strip()
    destination_mode = str(destination_mode or "Use Bank Account").strip()
    clearing_mode = str(clearing_mode or "Use Existing Account").strip()
    fee_account = str(fee_account or "").strip()
    notes = str(notes or "").strip()
    existing_setup = _clean_master_text(existing_setup)
    enabled = cint(enabled)

    if not mode_of_payment or not frappe.db.exists("Mode of Payment", mode_of_payment):
        frappe.throw(_("Select a valid Mode of Payment."))
    if settlement_policy not in {"At Shift Closing", "On Actual Bank Settlement"}:
        frappe.throw(_("Select a valid Settlement Policy."))

    action = "update" if existing_setup else "create"
    current = None
    if action == "update":
        if not frappe.db.exists("Payment Method Clearing Setup", existing_setup):
            frappe.throw(_("Payment Method Clearing Setup was not found."))
        current = frappe.get_doc("Payment Method Clearing Setup", existing_setup)
        if company != current.company:
            frappe.throw(_("Company cannot be changed after setup creation."))
        if mode_of_payment != current.mode_of_payment:
            frappe.throw(_("Mode of Payment cannot be changed after setup creation."))
    duplicate = frappe.db.get_value(
        "Payment Method Clearing Setup",
        {"company": company, "mode_of_payment": mode_of_payment},
        "name",
    )
    if duplicate and duplicate != existing_setup:
        frappe.throw(
            _("A clearing setup already exists for {0} and {1}: {2}.").format(
                company, mode_of_payment, duplicate
            )
        )

    destination_mode_lower = destination_mode.lower()
    selected_bank_account = ""
    if destination_mode_lower.startswith("use bank"):
        bank_account = _clean_master_text(bank_account)
        if not bank_account or not frappe.db.exists("Bank Account", bank_account):
            frappe.throw(_("Select a valid Bank Account."))
        bank_doc = frappe.get_doc("Bank Account", bank_account)
        if cint(bank_doc.disabled) or not cint(bank_doc.is_company_account):
            frappe.throw(_("The selected Bank Account is disabled or is not a Company Account."))
        if bank_doc.company != company or not bank_doc.account:
            frappe.throw(_("The selected Bank Account is not valid for this company."))
        account = _validate_company_account(
            bank_doc.account, company, "Asset", "Bank", _("Destination Account")
        )
        destination_plan = {
            "action": "reuse",
            "document_name": account.name,
            "account_name": account.account_name,
            "company": company,
            "parent_account": account.parent_account,
            "account_currency": account.account_currency or "",
            "root_type": account.root_type,
            "account_type": account.account_type or "",
        }
        selected_bank_account = bank_doc.name
    elif destination_mode_lower.startswith("use existing"):
        existing_destination_account = str(existing_destination_account or "").strip()
        if not existing_destination_account:
            frappe.throw(_("Select an existing Destination Account."))
        account = _validate_company_account(
            existing_destination_account, company, "Asset", None, _("Destination Account")
        )
        destination_plan = {
            "action": "reuse",
            "document_name": account.name,
            "account_name": account.account_name,
            "company": company,
            "parent_account": account.parent_account,
            "account_currency": account.account_currency or "",
            "root_type": account.root_type,
            "account_type": account.account_type or "",
        }
    else:
        destination_account_name = _clean_master_text(destination_account_name)
        destination_parent_account = str(destination_parent_account or "").strip()
        if not destination_account_name:
            frappe.throw(_("Destination Account Name is required."))
        if not destination_parent_account:
            frappe.throw(_("Destination Parent Account is required."))
        _validate_parent_account(destination_parent_account, company, "Asset")
        currency = frappe.db.get_value("Company", company, "default_currency") or ""
        destination_plan = _plan_reusable_account(
            destination_account_name,
            company,
            destination_parent_account,
            currency,
            root_type="Asset",
            account_type="Bank",
        )

    clearing_existing = clearing_mode.lower().startswith("use")
    if clearing_existing:
        existing_clearing_account = str(existing_clearing_account or "").strip()
        if not existing_clearing_account:
            frappe.throw(_("Select an existing Clearing Account."))
        account = _validate_company_account(
            existing_clearing_account, company, "Asset", None, _("Clearing Account")
        )
        clearing_plan = {
            "action": "reuse",
            "document_name": account.name,
            "account_name": account.account_name,
            "company": company,
            "parent_account": account.parent_account,
            "account_currency": account.account_currency or "",
            "root_type": account.root_type,
            "account_type": account.account_type or "",
        }
    else:
        clearing_account_name = _clean_master_text(clearing_account_name)
        clearing_parent_account = str(clearing_parent_account or "").strip()
        if not clearing_account_name:
            frappe.throw(_("Clearing Account Name is required."))
        if not clearing_parent_account:
            frappe.throw(_("Clearing Parent Account is required."))
        _validate_parent_account(clearing_parent_account, company, "Asset")
        currency = frappe.db.get_value("Company", company, "default_currency") or ""
        clearing_plan = _plan_reusable_account(
            clearing_account_name,
            company,
            clearing_parent_account,
            currency,
            root_type="Asset",
            account_type="",
        )

    if clearing_plan.get("action") == "reuse" and destination_plan.get("action") == "reuse":
        if clearing_plan["document_name"] == destination_plan["document_name"]:
            frappe.throw(_("Clearing Account and Destination Account must be different."))

    if fee_account:
        _validate_company_account(fee_account, company, "Expense", None, _("Fee Account"))
        if fee_account in {
            clearing_plan.get("document_name"), destination_plan.get("document_name")
        }:
            frappe.throw(_("Fee Account must be different from clearing and destination accounts."))

    if current:
        open_rows = _get_open_payment_reconciliations(current.name, limit=5)
        clearing_name = clearing_plan.get("document_name") if clearing_plan["action"] == "reuse" else ""
        destination_name = destination_plan.get("document_name") if destination_plan["action"] == "reuse" else ""
        protected_changed = any((
            company != current.company,
            mode_of_payment != current.mode_of_payment,
            clearing_name != current.clearing_account,
            destination_name != current.destination_account,
        ))
        if open_rows and protected_changed:
            names = ", ".join(row.name for row in open_rows)
            frappe.throw(
                _("Accounting links cannot be changed while open reconciliations exist: {0}.").format(names)
            )
        if open_rows and not enabled:
            names = ", ".join(row.name for row in open_rows)
            frappe.throw(
                _("Cannot disable this setup while open reconciliations exist: {0}.").format(names)
            )

    card_terminal_count = frappe.db.count(
        "Card POS Terminal",
        filters={"company": company, "mode_of_payment": mode_of_payment},
    ) if frappe.db.exists("DocType", "Card POS Terminal") else 0

    return {
        "action": action,
        "existing_setup": existing_setup,
        "company": company,
        "mode_of_payment": mode_of_payment,
        "settlement_policy": settlement_policy,
        "enabled": enabled,
        "destination_mode": destination_mode,
        "bank_account": selected_bank_account,
        "destination_account": destination_plan,
        "clearing_mode": clearing_mode,
        "clearing_account": clearing_plan,
        "fee_account": fee_account,
        "notes": notes,
        "card_terminal_count": card_terminal_count,
    }


@frappe.whitelist()
def get_card_terminal_creation_options(company=None, terminal_name=None):
    """Return defaults for creating or editing a Card POS Terminal."""
    _validate_create_access()

    company = _resolve_company(company)
    terminal = None
    if terminal_name:
        terminal_name = _clean_master_text(terminal_name)
        if not frappe.db.exists("Card POS Terminal", terminal_name):
            frappe.throw(_("Card POS Terminal was not found."))
        terminal = frappe.get_doc("Card POS Terminal", terminal_name)
        company = terminal.company

    clearing_parents = _clearing_parent_accounts(company)
    default_bank_account = ""
    default_fee_account = _default_fee_account(company)
    default_mode = _default_card_mode_of_payment()
    if terminal:
        default_bank_account = frappe.db.get_value(
            "Bank Account",
            {"company": company, "account": terminal.destination_bank_account, "disabled": 0},
            "name",
        ) or ""

    return {
        "company": company,
        "suggested_terminal_code": terminal.terminal_code if terminal else _next_terminal_code(),
        "default_mode_of_payment": terminal.mode_of_payment if terminal else default_mode,
        "default_clearing_parent_account": clearing_parents[0]["name"] if clearing_parents else "",
        "default_fee_account": terminal.fee_account if terminal else default_fee_account,
        "terminal": _serialize_terminal_for_edit(terminal, default_bank_account) if terminal else None,
    }


@frappe.whitelist()
def preview_card_terminal(
    terminal_name,
    terminal_code,
    company,
    mode_of_payment,
    bank_account,
    merchant_id=None,
    terminal_id=None,
    clearing_mode="Use Existing Account",
    existing_clearing_account=None,
    clearing_account_name=None,
    clearing_parent_account=None,
    fee_account=None,
    notes=None,
    existing_terminal=None,
    **kwargs,
):
    """Validate and preview a Card POS Terminal without writing data."""
    _validate_create_access()
    return _prepare_card_terminal_payload(
        terminal_name=terminal_name,
        terminal_code=terminal_code,
        company=company,
        mode_of_payment=mode_of_payment,
        bank_account=bank_account,
        merchant_id=merchant_id,
        terminal_id=terminal_id,
        clearing_mode=clearing_mode,
        existing_clearing_account=existing_clearing_account,
        clearing_account_name=clearing_account_name,
        clearing_parent_account=clearing_parent_account,
        fee_account=fee_account,
        notes=notes,
        existing_terminal=existing_terminal,
    )


@frappe.whitelist()
def save_card_terminal(
    terminal_name,
    terminal_code,
    company,
    mode_of_payment,
    bank_account,
    merchant_id=None,
    terminal_id=None,
    clearing_mode="Use Existing Account",
    existing_clearing_account=None,
    clearing_account_name=None,
    clearing_parent_account=None,
    fee_account=None,
    notes=None,
    existing_terminal=None,
    **kwargs,
):
    """Create or update a Card POS Terminal after final server validation."""
    _validate_create_access()
    payload = _prepare_card_terminal_payload(
        terminal_name=terminal_name,
        terminal_code=terminal_code,
        company=company,
        mode_of_payment=mode_of_payment,
        bank_account=bank_account,
        merchant_id=merchant_id,
        terminal_id=terminal_id,
        clearing_mode=clearing_mode,
        existing_clearing_account=existing_clearing_account,
        clearing_account_name=clearing_account_name,
        clearing_parent_account=clearing_parent_account,
        fee_account=fee_account,
        notes=notes,
        existing_terminal=existing_terminal,
    )

    clearing_plan = payload["clearing_account"]
    clearing_account = (
        _create_account_from_plan(clearing_plan)
        if clearing_plan["action"] == "create"
        else clearing_plan["document_name"]
    )

    if payload["action"] == "update":
        terminal = frappe.get_doc("Card POS Terminal", payload["existing_terminal"])
    else:
        terminal = frappe.new_doc("Card POS Terminal")
        terminal.terminal_code = payload["terminal_code"]

    terminal.terminal_name = payload["terminal_name"]
    terminal.company = payload["company"]
    terminal.mode_of_payment = payload["mode_of_payment"]
    terminal.bank_label = payload["bank_label"]
    terminal.merchant_id = payload["merchant_id"] or None
    terminal.terminal_id = payload["terminal_id"] or None
    terminal.clearing_account = clearing_account
    terminal.destination_bank_account = payload["destination_bank_account"]
    terminal.fee_account = payload["fee_account"] or None
    terminal.notes = payload["notes"] or None
    if payload["action"] == "create":
        terminal.enabled = 1
        terminal.flags.ignore_permissions = True
        terminal.insert(ignore_permissions=True)
    else:
        terminal.flags.ignore_permissions = True
        terminal.save(ignore_permissions=True)

    terminal.add_comment(
        "Comment",
        _("{0} from Treasury Management.").format(
            _("Created") if payload["action"] == "create" else _("Updated")
        ),
    )

    return {
        "ok": True,
        "terminal": terminal.name,
        "terminal_name": terminal.terminal_name,
        "clearing_account": clearing_account,
        "destination_bank_account": terminal.destination_bank_account,
        "action": payload["action"],
        "message": _("Card POS Terminal was saved successfully."),
    }


@frappe.whitelist()
def get_card_terminal_activity(terminal_name, limit=20):
    """Return clearing balance, GL movements and open batches for a terminal."""
    _validate_access()
    terminal_name = _clean_master_text(terminal_name)
    if not terminal_name or not frappe.db.exists("Card POS Terminal", terminal_name):
        frappe.throw(_("Card POS Terminal was not found."))

    terminal = frappe.get_doc("Card POS Terminal", terminal_name)
    clearing = _validate_company_account(
        terminal.clearing_account,
        terminal.company,
        expected_root="Asset",
        expected_type=None,
        label=_("Clearing Account"),
    )
    limit = max(1, min(cint(limit) or 20, 100))
    movements = frappe.get_all(
        "GL Entry",
        filters={"account": terminal.clearing_account, "is_cancelled": 0},
        fields=[
            "name", "posting_date", "creation", "voucher_type", "voucher_no",
            "debit", "credit", "against", "remarks",
        ],
        order_by="posting_date desc, creation desc",
        limit_page_length=limit,
    )
    for row in movements:
        row["debit"] = flt(row.get("debit"))
        row["credit"] = flt(row.get("credit"))
        row["net_movement"] = flt(row["debit"] - row["credit"])

    open_batches = _get_open_card_batches(terminal.name, limit=100)
    return {
        "terminal": terminal.name,
        "terminal_name": terminal.terminal_name,
        "company": terminal.company,
        "bank_label": terminal.bank_label,
        "mode_of_payment": terminal.mode_of_payment,
        "clearing_account": terminal.clearing_account,
        "destination_bank_account": terminal.destination_bank_account,
        "fee_account": terminal.fee_account or "",
        "account_currency": clearing.get("account_currency") or "",
        "current_balance": _account_balance(terminal.clearing_account, terminal.company),
        "enabled": cint(terminal.enabled),
        "open_batch_count": len(open_batches),
        "open_outstanding_amount": sum(flt(row.get("outstanding_amount")) for row in open_batches),
        "late_batch_count": sum(cint(row.get("is_late")) for row in open_batches),
        "open_batches": open_batches,
        "movements": movements,
    }


@frappe.whitelist()
def set_card_terminal_enabled(terminal_name, enabled):
    """Enable or disable a terminal, blocking disable while open batches exist."""
    _validate_create_access()
    terminal_name = _clean_master_text(terminal_name)
    if not terminal_name or not frappe.db.exists("Card POS Terminal", terminal_name):
        frappe.throw(_("Card POS Terminal was not found."))

    terminal = frappe.get_doc("Card POS Terminal", terminal_name)
    enabled = cint(enabled)
    if enabled:
        _validate_terminal_accounts(terminal)
        if not frappe.db.exists("Mode of Payment", terminal.mode_of_payment):
            frappe.throw(_("Mode of Payment was not found."))
    else:
        open_batches = _get_open_card_batches(terminal.name, limit=5)
        if open_batches:
            names = ", ".join(row.name for row in open_batches)
            frappe.throw(
                _("Cannot disable this terminal while open settlement batches exist: {0}.").format(names)
            )

    if cint(terminal.enabled) != enabled:
        terminal.enabled = enabled
        terminal.flags.ignore_permissions = True
        terminal.save(ignore_permissions=True)
        terminal.add_comment(
            "Comment",
            _("Card POS Terminal {0} from Treasury Management.").format(
                _("enabled") if enabled else _("disabled")
            ),
        )

    return {
        "terminal": terminal.name,
        "enabled": cint(terminal.enabled),
        "message": _("Card POS Terminal status was updated successfully."),
    }


def _prepare_card_terminal_payload(
    terminal_name,
    terminal_code,
    company,
    mode_of_payment,
    bank_account,
    merchant_id=None,
    terminal_id=None,
    clearing_mode="Use Existing Account",
    existing_clearing_account=None,
    clearing_account_name=None,
    clearing_parent_account=None,
    fee_account=None,
    notes=None,
    existing_terminal=None,
):
    terminal_name = _clean_master_text(terminal_name)
    terminal_code = _normalize_terminal_code(terminal_code)
    company = _resolve_company(company)
    mode_of_payment = _clean_master_text(mode_of_payment)
    bank_account = _clean_master_text(bank_account)
    merchant_id = _clean_master_text(merchant_id)
    terminal_id = _clean_master_text(terminal_id)
    clearing_mode = str(clearing_mode or "Use Existing Account").strip()
    fee_account = str(fee_account or "").strip()
    notes = str(notes or "").strip()
    existing_terminal = _clean_master_text(existing_terminal)

    if not terminal_name:
        frappe.throw(_("Terminal Name is required."))
    if not terminal_code:
        frappe.throw(_("Terminal Code is required."))
    if not mode_of_payment or not frappe.db.exists("Mode of Payment", mode_of_payment):
        frappe.throw(_("Select a valid Mode of Payment."))
    if not bank_account or not frappe.db.exists("Bank Account", bank_account):
        frappe.throw(_("Select a valid Bank Account."))

    bank_account_doc = frappe.get_doc("Bank Account", bank_account)
    if cint(bank_account_doc.disabled):
        frappe.throw(_("The selected Bank Account is disabled."))
    if not cint(bank_account_doc.is_company_account):
        frappe.throw(_("The selected Bank Account is not marked as a Company Account."))
    if bank_account_doc.company != company:
        frappe.throw(_("The selected Bank Account belongs to another company."))
    if not bank_account_doc.account:
        frappe.throw(_("The selected Bank Account has no company ledger account."))
    destination = _validate_company_account(
        bank_account_doc.account,
        company,
        expected_root="Asset",
        expected_type="Bank",
        label=_("Destination Bank Account"),
    )

    action = "update" if existing_terminal else "create"
    current = None
    if action == "update":
        if not frappe.db.exists("Card POS Terminal", existing_terminal):
            frappe.throw(_("Card POS Terminal was not found."))
        current = frappe.get_doc("Card POS Terminal", existing_terminal)
        if terminal_code != current.terminal_code:
            frappe.throw(_("Terminal Code cannot be changed after creation."))
    elif frappe.db.exists("Card POS Terminal", terminal_code):
        frappe.throw(_("Card POS Terminal {0} already exists.").format(terminal_code))

    duplicate_name = frappe.db.get_value(
        "Card POS Terminal",
        {"company": company, "terminal_name": terminal_name},
        "name",
    )
    if duplicate_name and duplicate_name != existing_terminal:
        frappe.throw(_("A terminal with this name already exists: {0}.").format(duplicate_name))

    for fieldname, value, label in (
        ("merchant_id", merchant_id, _("Merchant ID")),
        ("terminal_id", terminal_id, _("Terminal ID")),
    ):
        if not value:
            continue
        duplicate = frappe.db.get_value(
            "Card POS Terminal",
            {"company": company, fieldname: value},
            "name",
        )
        if duplicate and duplicate != existing_terminal:
            frappe.throw(_("{0} is already used by terminal {1}.").format(label, duplicate))

    use_existing = clearing_mode.lower().startswith("use") or clearing_mode.lower() == "existing"
    if use_existing:
        existing_clearing_account = str(existing_clearing_account or "").strip()
        if not existing_clearing_account:
            frappe.throw(_("Select an existing Clearing Account."))
        clearing = _validate_company_account(
            existing_clearing_account,
            company,
            expected_root="Asset",
            expected_type=None,
            label=_("Clearing Account"),
        )
        clearing_plan = {
            "action": "reuse",
            "document_name": clearing.name,
            "account_name": clearing.account_name,
            "company": company,
            "parent_account": clearing.parent_account,
            "account_currency": clearing.account_currency or "",
            "root_type": clearing.root_type,
            "account_type": clearing.account_type or "",
        }
    else:
        clearing_account_name = _clean_master_text(clearing_account_name)
        clearing_parent_account = str(clearing_parent_account or "").strip()
        if not clearing_account_name:
            frappe.throw(_("Clearing Account Name is required."))
        if not clearing_parent_account:
            frappe.throw(_("Clearing Parent Account is required."))
        _validate_parent_account(clearing_parent_account, company, "Asset")
        currency = frappe.db.get_value("Company", company, "default_currency") or ""
        clearing_plan = _plan_reusable_account(
            clearing_account_name,
            company,
            clearing_parent_account,
            currency,
            root_type="Asset",
            account_type="",
        )

    if fee_account:
        _validate_company_account(
            fee_account,
            company,
            expected_root="Expense",
            expected_type=None,
            label=_("Fee Account"),
        )

    if current:
        open_batches = _get_open_card_batches(current.name, limit=5)
        protected_changed = any((
            company != current.company,
            mode_of_payment != current.mode_of_payment,
            bank_account_doc.bank != current.bank_label,
            destination.name != current.destination_bank_account,
            (clearing_plan.get("document_name") or "") != current.clearing_account
                if clearing_plan["action"] == "reuse" else True,
        ))
        if open_batches and protected_changed:
            names = ", ".join(row.name for row in open_batches)
            frappe.throw(
                _("Accounting links cannot be changed while open batches exist: {0}.").format(names)
            )

    return {
        "action": action,
        "existing_terminal": existing_terminal,
        "terminal_name": terminal_name,
        "terminal_code": terminal_code,
        "company": company,
        "mode_of_payment": mode_of_payment,
        "bank_account": bank_account,
        "bank_label": bank_account_doc.bank,
        "destination_bank_account": destination.name,
        "merchant_id": merchant_id,
        "terminal_id": terminal_id,
        "clearing_mode": "existing" if use_existing else "create",
        "clearing_account": clearing_plan,
        "fee_account": fee_account,
        "notes": notes,
    }


def _prepare_bank_setup_payload(
    bank_name,
    company,
    bank_account_name,
    ledger_mode="Create New Account",
    existing_ledger_account=None,
    ledger_account_name=None,
    bank_parent_account=None,
    swift_number=None,
    website=None,
    bank_account_no=None,
    iban=None,
    branch_code=None,
    create_card_clearing=1,
    card_clearing_name=None,
    create_instapay_clearing=0,
    instapay_clearing_name=None,
    clearing_parent_account=None,
    create_fee_account=1,
    fee_account_name=None,
    fee_parent_account=None,
):
    bank_name = _clean_master_text(bank_name)
    company = _resolve_company(company)
    bank_account_name = str(bank_account_name or "").strip()
    ledger_mode = str(ledger_mode or "Create New Account").strip()
    swift_number = str(swift_number or "").strip()
    website = str(website or "").strip()
    bank_account_no = str(bank_account_no or "").strip()
    iban = str(iban or "").strip().replace(" ", "").upper()
    branch_code = str(branch_code or "").strip()
    account_currency = frappe.db.get_value("Company", company, "default_currency") or ""

    if not bank_name:
        frappe.throw(_("Bank Name is required."))
    if not bank_account_name:
        frappe.throw(_("Bank Account Name is required."))

    if frappe.db.exists("Bank Account", {"company": company, "account_name": bank_account_name}):
        frappe.throw(_("A Bank Account with this name already exists for the company."))
    if bank_account_no and frappe.db.exists(
        "Bank Account", {"bank": bank_name, "bank_account_no": bank_account_no}
    ):
        frappe.throw(_("This bank account number is already registered."))
    if iban and frappe.db.exists("Bank Account", {"iban": iban}):
        frappe.throw(_("This IBAN is already registered."))

    bank_master_action = "reuse" if frappe.db.exists("Bank", bank_name) else "create"

    use_existing = ledger_mode.lower().startswith("use") or ledger_mode.lower() == "existing"
    if use_existing:
        existing_ledger_account = str(existing_ledger_account or "").strip()
        if not existing_ledger_account:
            frappe.throw(_("Select an existing Bank ledger account."))
        account = _validate_company_account(
            existing_ledger_account,
            company,
            expected_root="Asset",
            expected_type="Bank",
            label=_("Bank Ledger Account"),
        )
        linked = frappe.db.get_value("Bank Account", {"account": existing_ledger_account}, "name")
        if linked:
            frappe.throw(
                _("This ledger account is already linked to Bank Account {0}.").format(linked)
            )
        ledger_plan = {
            "action": "reuse",
            "document_name": account.name,
            "account_name": account.account_name,
            "company": company,
            "parent_account": account.parent_account,
            "account_currency": account.account_currency or account_currency,
            "root_type": account.root_type,
            "account_type": account.account_type,
        }
    else:
        ledger_account_name = _clean_master_text(ledger_account_name)
        bank_parent_account = str(bank_parent_account or "").strip()
        if not ledger_account_name:
            frappe.throw(_("Bank Ledger Account Name is required."))
        if not bank_parent_account:
            frappe.throw(_("Bank Parent Account is required."))
        duplicate = frappe.db.get_value(
            "Account", {"company": company, "account_name": ledger_account_name}, "name"
        )
        if duplicate:
            frappe.throw(
                _("Account {0} already exists. Choose Use Existing Account instead.").format(
                    duplicate
                )
            )
        _validate_parent_account(bank_parent_account, company, "Asset")
        ledger_plan = {
            "action": "create",
            "document_name": "",
            "account_name": ledger_account_name,
            "company": company,
            "parent_account": bank_parent_account,
            "account_currency": account_currency,
            "root_type": "Asset",
            "account_type": "Bank",
        }

    payload = {
        "bank_name": bank_name,
        "bank_master_action": bank_master_action,
        "swift_number": swift_number,
        "website": website,
        "company": company,
        "account_currency": account_currency,
        "bank_account_name": bank_account_name,
        "bank_account_no": bank_account_no,
        "iban": iban,
        "branch_code": branch_code,
        "ledger_mode": "existing" if use_existing else "create",
        "ledger_account": ledger_plan,
    }

    create_card_clearing = cint(create_card_clearing)
    create_instapay_clearing = cint(create_instapay_clearing)
    create_fee_account = cint(create_fee_account)

    if create_card_clearing or create_instapay_clearing:
        clearing_parent_account = str(clearing_parent_account or "").strip()
        if not clearing_parent_account:
            frappe.throw(_("Clearing Parent Account is required."))
        _validate_parent_account(clearing_parent_account, company, "Asset")

    if create_card_clearing:
        payload["card_clearing_account"] = _plan_reusable_account(
            card_clearing_name or f"{bank_name} Card Clearing",
            company,
            clearing_parent_account,
            account_currency,
            root_type="Asset",
            account_type="",
        )

    if create_instapay_clearing:
        payload["instapay_clearing_account"] = _plan_reusable_account(
            instapay_clearing_name or f"{bank_name} InstaPay Clearing",
            company,
            clearing_parent_account,
            account_currency,
            root_type="Asset",
            account_type="",
        )

    if create_fee_account:
        fee_parent_account = str(fee_parent_account or "").strip()
        if not fee_parent_account:
            frappe.throw(_("Fee Parent Account is required."))
        _validate_parent_account(fee_parent_account, company, "Expense")
        payload["fee_account"] = _plan_reusable_account(
            fee_account_name or f"{bank_name} Bank Charges",
            company,
            fee_parent_account,
            account_currency,
            root_type="Expense",
            account_type="",
        )

    return payload



def _clean_master_text(value):
    """Normalize master-data names and remove hidden/combining Unicode marks."""
    value = unicodedata.normalize("NFKC", str(value or ""))
    cleaned = []
    for char in value:
        category = unicodedata.category(char)
        if unicodedata.combining(char) or category in {"Cf", "Cc"}:
            continue
        cleaned.append(char)
    return " ".join("".join(cleaned).split())

def _plan_reusable_account(
    account_name,
    company,
    parent_account,
    account_currency,
    root_type,
    account_type="",
):
    account_name = _clean_master_text(account_name)
    if not account_name:
        frappe.throw(_("Account Name is required."))

    existing = frappe.db.get_value(
        "Account", {"company": company, "account_name": account_name}, "name"
    )
    if existing:
        account = _validate_company_account(
            existing,
            company,
            expected_root=root_type,
            expected_type=None,
            label=_("Account"),
        )
        return {
            "action": "reuse",
            "document_name": account.name,
            "account_name": account.account_name,
            "company": company,
            "parent_account": account.parent_account,
            "account_currency": account.account_currency or account_currency,
            "root_type": account.root_type,
            "account_type": account.account_type or "",
        }

    return {
        "action": "create",
        "document_name": "",
        "account_name": account_name,
        "company": company,
        "parent_account": parent_account,
        "account_currency": account_currency,
        "root_type": root_type,
        "account_type": account_type,
    }


def _create_account_from_plan(plan):
    account = frappe.new_doc("Account")
    account.account_name = plan["account_name"]
    account.company = plan["company"]
    account.parent_account = plan["parent_account"]
    account.is_group = 0
    account.account_type = plan.get("account_type") or ""
    account.account_currency = plan.get("account_currency") or ""
    account.flags.ignore_permissions = True
    account.insert(ignore_permissions=True)
    return account.name


def _validate_parent_account(account_name, company, root_type):
    account = frappe.db.get_value(
        "Account",
        account_name,
        ["name", "company", "is_group", "disabled", "root_type"],
        as_dict=True,
    )
    if not account:
        frappe.throw(_("Parent Account was not found."))
    if account.company != company:
        frappe.throw(_("Parent Account belongs to another company."))
    if not cint(account.is_group):
        frappe.throw(_("Parent Account must be a group account."))
    if cint(account.disabled):
        frappe.throw(_("Parent Account is disabled."))
    if account.root_type != root_type:
        frappe.throw(
            _("Parent Account must be under the {0} root.").format(root_type)
        )
    return account


def _validate_company_account(
    account_name,
    company,
    expected_root=None,
    expected_type=None,
    label=None,
):
    account = frappe.db.get_value(
        "Account",
        account_name,
        [
            "name",
            "account_name",
            "company",
            "parent_account",
            "is_group",
            "disabled",
            "root_type",
            "account_type",
            "account_currency",
        ],
        as_dict=True,
    )
    label = label or _("Account")
    if not account:
        frappe.throw(_("{0} was not found.").format(label))
    if account.company != company:
        frappe.throw(_("{0} belongs to another company.").format(label))
    if cint(account.is_group):
        frappe.throw(_("{0} cannot be a group account.").format(label))
    if cint(account.disabled):
        frappe.throw(_("{0} is disabled.").format(label))
    if expected_root and account.root_type != expected_root:
        frappe.throw(
            _("{0} must be under the {1} root.").format(label, expected_root)
        )
    if expected_type and account.account_type != expected_type:
        frappe.throw(
            _("{0} must have Account Type {1}.").format(label, expected_type)
        )
    return account

def _prepare_cash_drawer_payload(
    drawer_name,
    drawer_code,
    company,
    account_name,
    parent_account,
    branch=None,
    physical_location=None,
    default_opening_float=0,
):
    drawer_name = str(drawer_name or "").strip()
    drawer_code = _normalize_drawer_code(drawer_code)
    company = _resolve_company(company)
    account_name = str(account_name or "").strip()
    parent_account = str(parent_account or "").strip()
    branch = str(branch or "").strip()
    physical_location = str(physical_location or "").strip()
    default_opening_float = flt(default_opening_float)

    if not drawer_name:
        frappe.throw(_("Drawer Name is required."))
    if not drawer_code:
        frappe.throw(_("Drawer Code is required."))
    if not account_name:
        frappe.throw(_("Cash Account Name is required."))
    if not parent_account:
        frappe.throw(_("Parent Account is required."))
    if default_opening_float < 0:
        frappe.throw(_("Default Opening Float cannot be negative."))

    if frappe.db.exists("Cash Drawer", drawer_code):
        frappe.throw(_("Cash Drawer {0} already exists.").format(drawer_code))

    duplicate_drawer_name = frappe.db.get_value(
        "Cash Drawer",
        {"drawer_name": drawer_name, "company": company},
        "name",
    )
    if duplicate_drawer_name:
        frappe.throw(
            _("A cash drawer with this name already exists: {0}.").format(
                duplicate_drawer_name
            )
        )

    existing_account = frappe.db.get_value(
        "Account",
        {"company": company, "account_name": account_name},
        "name",
    )
    if existing_account:
        frappe.throw(
            _("An account with this name already exists: {0}.").format(existing_account)
        )

    parent = frappe.db.get_value(
        "Account",
        parent_account,
        [
            "name",
            "company",
            "is_group",
            "disabled",
            "root_type",
            "account_currency",
        ],
        as_dict=True,
    )
    if not parent:
        frappe.throw(_("Parent Account was not found."))
    if parent.company != company:
        frappe.throw(_("Parent Account belongs to another company."))
    if not cint(parent.is_group):
        frappe.throw(_("Parent Account must be a group account."))
    if cint(parent.disabled):
        frappe.throw(_("Parent Account is disabled."))
    if parent.root_type != "Asset":
        frappe.throw(_("Parent Account must be under the Asset root."))

    if branch and frappe.db.exists("DocType", "Branch"):
        branch_row = frappe.db.get_value(
            "Branch",
            branch,
            ["name", "company"],
            as_dict=True,
        )
        if not branch_row:
            frappe.throw(_("Branch was not found."))
        if branch_row.get("company") and branch_row.company != company:
            frappe.throw(_("Branch belongs to another company."))

    account_currency = (
        frappe.db.get_value("Company", company, "default_currency")
        or parent.account_currency
        or ""
    )

    return {
        "drawer_name": drawer_name,
        "drawer_code": drawer_code,
        "company": company,
        "branch": branch,
        "physical_location": physical_location,
        "default_opening_float": default_opening_float,
        "account_name": account_name,
        "parent_account": parent_account,
        "account_currency": account_currency,
        "account_type": "Cash",
        "enabled": 1,
        "creates_opening_entry": False,
    }


def _normalize_drawer_code(value):
    value = str(value or "").strip().upper()
    value = re.sub(r"[^A-Z0-9_-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-_")
    return value[:140]


def _resolve_company(company=None):
    company = str(company or "").strip()
    if not company:
        company = frappe.defaults.get_user_default("Company") or ""
    if not company:
        company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    if not company:
        companies = frappe.get_all("Company", pluck="name", limit_page_length=2)
        if len(companies) == 1:
            company = companies[0]
    if not company or not frappe.db.exists("Company", company):
        frappe.throw(_("Select a valid Company."))
    return company


def _next_drawer_code():
    rows = frappe.get_all(
        "Cash Drawer",
        fields=["drawer_code"],
        limit_page_length=1000,
    )
    highest = 0
    for row in rows:
        match = re.search(r"(\d+)$", str(row.get("drawer_code") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"DRAWER-{highest + 1:02d}"


def _cash_parent_accounts(company):
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Asset",
            "is_group": 1,
            "disabled": 0,
        },
        fields=[
            "name",
            "account_name",
            "parent_account",
            "account_currency",
            "account_type",
        ],
        order_by="lft asc",
        limit_page_length=500,
    )

    def priority(row):
        account_name = str(row.get("account_name") or "").strip().lower()
        account_type = str(row.get("account_type") or "").strip().lower()
        if account_name == "cash in hand":
            return (0, row.get("name") or "")
        if account_type == "cash":
            return (1, row.get("name") or "")
        if "cash" in account_name:
            return (2, row.get("name") or "")
        return (3, row.get("name") or "")

    rows.sort(key=priority)
    return rows



def _get_internal_transfer_accounts(company):
    """Return enabled Asset Cash/Bank leaf accounts with operational labels."""
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Asset",
            "is_group": 0,
            "disabled": 0,
            "account_type": ["in", ["Cash", "Bank"]],
        },
        fields=[
            "name",
            "account_name",
            "account_type",
            "account_currency",
            "parent_account",
            "company",
        ],
        order_by="account_type asc, account_name asc",
        limit_page_length=1000,
    )

    drawer_map = {}
    if frappe.db.exists("DocType", "Cash Drawer"):
        for drawer in frappe.get_all(
            "Cash Drawer",
            filters={"company": company, "enabled": 1},
            fields=["name", "drawer_name", "cash_account"],
            limit_page_length=500,
        ):
            if drawer.cash_account:
                drawer_map[drawer.cash_account] = drawer.drawer_name or drawer.name

    bank_map = {}
    if frappe.db.exists("DocType", "Bank Account"):
        for bank_account in frappe.get_all(
            "Bank Account",
            filters={"company": company, "disabled": 0},
            fields=["name", "account_name", "bank", "account"],
            limit_page_length=500,
        ):
            if bank_account.account:
                bank_map[bank_account.account] = (
                    bank_account.account_name or bank_account.bank or bank_account.name
                )

    company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
    for row in rows:
        row["account_currency"] = row.get("account_currency") or company_currency
        row["current_balance"] = _account_balance(row.name, company)
        if row.account_type == "Cash":
            row["master_type"] = "Cash Drawer" if row.name in drawer_map else "Cash Account"
            row["master_label"] = drawer_map.get(row.name) or row.account_name or row.name
        else:
            row["master_type"] = "Bank Account" if row.name in bank_map else "Bank Ledger"
            row["master_label"] = bank_map.get(row.name) or row.account_name or row.name
    return rows


def _get_internal_transfers(limit=50):
    if not frappe.db.exists("DocType", "Payment Entry"):
        return []

    fields = [
        "name",
        "docstatus",
        "status",
        "posting_date",
        "company",
        "paid_from",
        "paid_to",
        "paid_amount",
        "received_amount",
        "paid_from_account_currency",
        "paid_to_account_currency",
        "reference_no",
        "reference_date",
        "remarks",
        "owner",
        "creation",
        "modified",
    ]
    meta = frappe.get_meta("Payment Entry")
    audit_fields = [
        "custom_treasury_request_status",
        "custom_treasury_requested_by",
        "custom_treasury_requested_at",
        "custom_treasury_approved_by",
        "custom_treasury_approved_at",
        "custom_treasury_approval_note",
    ]
    fields.extend(fieldname for fieldname in audit_fields if meta.has_field(fieldname))

    rows = frappe.get_all(
        "Payment Entry",
        filters={"payment_type": "Internal Transfer"},
        fields=fields,
        order_by="creation desc",
        limit_page_length=cint(limit) or 50,
    )
    status_by_docstatus = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
    for row in rows:
        row["paid_amount"] = flt(row.get("paid_amount"))
        row["received_amount"] = flt(row.get("received_amount"))
        row["requested_by"] = row.get("custom_treasury_requested_by") or row.get("owner")
        row["requested_at"] = row.get("custom_treasury_requested_at") or row.get("creation")
        row["approved_by"] = row.get("custom_treasury_approved_by") or ""
        row["approved_at"] = row.get("custom_treasury_approved_at") or ""
        row["approval_note"] = row.get("custom_treasury_approval_note") or ""
        row["request_status"] = (
            row.get("custom_treasury_request_status")
            or status_by_docstatus.get(cint(row.get("docstatus")), row.get("status") or "")
        )
        row["display_status"] = row["request_status"]
        row["account_currency"] = (
            row.get("paid_from_account_currency")
            or row.get("paid_to_account_currency")
            or frappe.db.get_value("Company", row.company, "default_currency")
            or ""
        )
        row["can_current_user_approve"] = bool(
            can_manage_treasury()
            and cint(row.get("docstatus")) == 0
            and (
                can_emergency_submit_treasury()
                or row.get("requested_by") != frappe.session.user
            )
        )
    return rows


def _validate_internal_transfer_account(account_name, company, label):
    account_name = str(account_name or "").strip()
    account = frappe.db.get_value(
        "Account",
        account_name,
        [
            "name",
            "account_name",
            "company",
            "root_type",
            "account_type",
            "account_currency",
            "is_group",
            "disabled",
        ],
        as_dict=True,
    )
    if not account:
        frappe.throw(_("{0} was not found.").format(label))
    if account.company != company:
        frappe.throw(_("{0} belongs to another company.").format(label))
    if account.root_type != "Asset":
        frappe.throw(_("{0} must be an Asset account.").format(label))
    if account.account_type not in ("Cash", "Bank"):
        frappe.throw(_("{0} must be a Cash or Bank account.").format(label))
    if cint(account.is_group):
        frappe.throw(_("{0} cannot be a group account.").format(label))
    if cint(account.disabled):
        frappe.throw(_("{0} is disabled.").format(label))
    return account


def _prepare_internal_transfer(
    company,
    paid_from,
    paid_to,
    amount,
    posting_date=None,
    reference_no=None,
    reference_date=None,
    remarks=None,
    transfer_action="Create Draft",
    exclude_payment_entry=None,
):
    company = _resolve_company(company)
    paid_from = str(paid_from or "").strip()
    paid_to = str(paid_to or "").strip()
    if not paid_from or not paid_to:
        frappe.throw(_("Select both source and destination accounts."))
    if paid_from == paid_to:
        frappe.throw(_("Source and destination accounts must be different."))

    source = _validate_internal_transfer_account(paid_from, company, _("Source Account"))
    destination = _validate_internal_transfer_account(paid_to, company, _("Destination Account"))
    company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
    source_currency = source.account_currency or company_currency
    destination_currency = destination.account_currency or company_currency
    if source_currency != destination_currency:
        frappe.throw(
            _("Cross-currency transfers are not supported from Treasury Management. "
              "Source currency is {0} and destination currency is {1}.").format(
                source_currency, destination_currency
            )
        )

    amount = flt(amount)
    if amount <= 0:
        frappe.throw(_("Transfer Amount must be greater than zero."))

    posting_date = str(getdate(posting_date or nowdate()))
    if getdate(posting_date) > getdate(nowdate()):
        frappe.throw(_("Posting Date cannot be in the future."))
    reference_date = str(getdate(reference_date or posting_date))
    reference_no = _clean_master_text(reference_no)
    if not reference_no:
        frappe.throw(_("Reference Number is required for audit tracking."))
    remarks = str(remarks or "").strip()[:1000]

    transfer_action = str(transfer_action or "").strip()
    if transfer_action not in ("Create Draft", "Submit Now"):
        frappe.throw(_("Select a valid transfer action."))

    duplicate_filters = {
        "company": company,
        "payment_type": "Internal Transfer",
        "reference_no": reference_no,
        "docstatus": ["!=", 2],
    }
    duplicate = frappe.db.get_value("Payment Entry", duplicate_filters, "name")
    if duplicate and duplicate != exclude_payment_entry:
        frappe.throw(
            _("Reference Number is already used by Internal Transfer {0}.").format(duplicate)
        )

    source_balance = flt(_account_balance(paid_from, company))
    destination_balance = flt(_account_balance(paid_to, company))
    if source_balance + 0.01 < amount:
        frappe.throw(
            _("Source balance {0} is lower than transfer amount {1}.").format(
                source_balance, amount
            )
        )

    return {
        "company": company,
        "posting_date": posting_date,
        "reference_no": reference_no,
        "reference_date": reference_date,
        "remarks": remarks,
        "transfer_action": transfer_action,
        "paid_from": source.name,
        "paid_from_name": source.account_name or source.name,
        "paid_from_type": source.account_type,
        "paid_to": destination.name,
        "paid_to_name": destination.account_name or destination.name,
        "paid_to_type": destination.account_type,
        "amount": amount,
        "account_currency": source_currency,
        "source_balance_before": source_balance,
        "source_balance_after": flt(source_balance - amount),
        "destination_balance_before": destination_balance,
        "destination_balance_after": flt(destination_balance + amount),
        "journal_preview": [
            {"account": destination.name, "debit": amount, "credit": 0},
            {"account": source.name, "debit": 0, "credit": amount},
        ],
    }

def _get_shift_cash_movement_type_options():
    labels = {
        "Opening Float": _("Opening Float"),
        "Till Refill": _("Till Refill"),
        "Return Opening Float": _("Return Opening Float"),
        "Cash Sales Deposit": _("Cash Sales Deposit"),
        "Unused Till Refill Return": _("Unused Till Refill Return"),
        "Other Cash Return": _("Other Cash Return"),
        "Under Review Driver Cash Deposit": _("Under Review Driver Cash Deposit"),
        "Transfer to Main Safe": _("Transfer to Main Safe"),
        "Supplier Payment": _("Supplier Payment"),
        "Operating Expense": _("Operating Expense"),
        "Employee Advance": _("Employee Advance"),
        "Other Cash Receipt": _("Other Cash Receipt"),
        "Other Cash Payment": _("Other Cash Payment"),
        "Other": _("Other"),
    }
    rows = []
    for value, rule in SHIFT_CASH_MOVEMENT_RULES.items():
        rows.append(
            {
                "value": value,
                "label": labels.get(value, value),
                "direction": rule.get("direction") or "",
                "counter_kind": rule.get("counter_kind") or "other",
                "requires_supplier": cint(rule.get("requires_supplier")),
                "requires_employee": cint(rule.get("requires_employee")),
            }
        )
    return rows


def _get_shift_cash_movement_drawers(company):
    rows = []
    for drawer in _get_cash_drawers():
        if drawer.get("company") != company or not cint(drawer.get("enabled")):
            continue
        open_shift = _find_open_shift_for_drawer(frappe._dict(drawer))
        rows.append(
            {
                "name": drawer.get("name"),
                "drawer_name": drawer.get("drawer_name") or drawer.get("name"),
                "cash_account": drawer.get("cash_account"),
                "current_balance": flt(drawer.get("current_balance")),
                "currency": drawer.get("account_currency") or "",
                "open_shift": open_shift or "",
                "available": bool(open_shift),
            }
        )
    rows.sort(key=lambda row: (not row["available"], row["drawer_name"]))
    return rows


def _prepare_shift_cash_movement(
    *,
    company,
    cash_drawer,
    shift_reference,
    movement_type,
    amount,
    counter_account,
    movement_date=None,
    direction=None,
    reference_no=None,
    reference_date=None,
    description=None,
    supplier=None,
    purchase_invoice=None,
    employee=None,
    receipt_attachment=None,
    movement_action="Create Draft",
):
    company = _resolve_company(company)
    cash_drawer = str(cash_drawer or "").strip()
    shift_reference = str(shift_reference or "").strip()
    movement_type = str(movement_type or "").strip()
    counter_account = str(counter_account or "").strip()
    movement_action = str(movement_action or "Create Draft").strip()

    if movement_type not in SHIFT_CASH_MOVEMENT_RULES:
        frappe.throw(_("Select a valid Movement Type."))
    if not cash_drawer:
        frappe.throw(_("Cash Drawer is required."))
    if not shift_reference:
        frappe.throw(_("An open Shift Reference is required."))
    if not counter_account:
        frappe.throw(_("Counter Account is required."))

    drawer = frappe.db.get_value(
        "Cash Drawer",
        cash_drawer,
        ["name", "company", "enabled", "cash_account", "current_active_shift"],
        as_dict=True,
    )
    if not drawer:
        frappe.throw(_("Cash Drawer was not found."))
    if drawer.company != company:
        frappe.throw(_("Cash Drawer belongs to another company."))
    if not cint(drawer.enabled):
        frappe.throw(_("Cash Drawer is disabled."))
    if not drawer.cash_account:
        frappe.throw(_("Cash Drawer does not have a linked Cash Account."))

    rule = SHIFT_CASH_MOVEMENT_RULES[movement_type]
    resolved_direction = rule.get("direction") or str(direction or "").strip()
    if resolved_direction not in ("In", "Out"):
        frappe.throw(_("Direction is required for Other cash movements."))

    if resolved_direction == "In":
        source_account = counter_account
        target_account = drawer.cash_account
    else:
        source_account = drawer.cash_account
        target_account = counter_account

    movement_datetime = get_datetime(movement_date or now_datetime()).replace(microsecond=0)
    movement_date_value = movement_datetime.strftime("%Y-%m-%d %H:%M:%S")
    reference_date_value = str(getdate(reference_date)) if reference_date else None

    movement = frappe.new_doc("Shift Cash Movement")
    movement.company = company
    movement.cash_drawer = cash_drawer
    movement.shift_reference = shift_reference
    movement.movement_type = movement_type
    movement.direction = resolved_direction
    movement.amount = flt(amount)
    movement.movement_date = movement_date_value
    movement.source_account = source_account
    movement.target_account = target_account
    movement.expense_account = counter_account if movement_type == "Operating Expense" else None
    movement.supplier = str(supplier or "").strip() or None
    movement.purchase_invoice = str(purchase_invoice or "").strip() or None
    movement.employee = str(employee or "").strip() or None
    movement.reference_no = str(reference_no or "").strip()
    movement.reference_date = reference_date_value
    movement.description = str(description or "").strip()
    movement.receipt_attachment = str(receipt_attachment or "").strip() or None
    movement._validate_and_normalize(check_live_balance=True)

    source = frappe.db.get_value(
        "Account",
        movement.source_account,
        ["name", "account_currency", "root_type", "account_type"],
        as_dict=True,
    ) or {}
    target = frappe.db.get_value(
        "Account",
        movement.target_account,
        ["name", "account_currency", "root_type", "account_type"],
        as_dict=True,
    ) or {}
    source_balance = _account_balance_on_date(
        movement.source_account, company, movement_datetime.date()
    )
    target_balance = _account_balance_on_date(
        movement.target_account, company, movement_datetime.date()
    )
    currency = source.get("account_currency") or target.get("account_currency") or ""

    return {
        "company": company,
        "cash_drawer": cash_drawer,
        "cash_drawer_account": drawer.cash_account,
        "shift_reference": shift_reference,
        "movement_type": movement_type,
        "direction": resolved_direction,
        "amount": flt(movement.amount),
        "movement_date": movement_date_value,
        "source_account": movement.source_account,
        "source_account_type": source.get("account_type") or source.get("root_type") or "",
        "target_account": movement.target_account,
        "target_account_type": target.get("account_type") or target.get("root_type") or "",
        "counter_account": counter_account,
        "expense_account": movement.expense_account,
        "supplier": movement.supplier,
        "purchase_invoice": movement.purchase_invoice,
        "employee": movement.employee,
        "reference_no": movement.reference_no,
        "reference_date": movement.reference_date,
        "description": movement.description,
        "receipt_attachment": movement.receipt_attachment,
        "movement_action": movement_action,
        "currency": currency,
        "source_balance_before": source_balance,
        "source_balance_after": flt(source_balance - movement.amount),
        "target_balance_before": target_balance,
        "target_balance_after": flt(target_balance + movement.amount),
        "journal_preview": [
            {"account": movement.target_account, "debit": flt(movement.amount), "credit": 0},
            {"account": movement.source_account, "debit": 0, "credit": flt(movement.amount)},
        ],
    }


def _account_balance_on_date(account, company, posting_date):
    try:
        return flt(
            get_balance_on(
                account=account,
                date=posting_date,
                company=company,
                in_account_currency=True,
            )
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Treasury Shift Cash Movement Balance")
        return 0


def _get_shift_cash_movements(limit=50):
    if not frappe.db.exists("DocType", "Shift Cash Movement"):
        return []
    meta = frappe.get_meta("Shift Cash Movement")
    fields = [
        "name",
        "docstatus",
        "company",
        "shift_reference",
        "movement_date",
        "movement_type",
        "direction",
        "amount",
        "status",
        "source_account",
        "target_account",
        "journal_entry",
        "owner",
        "creation",
    ]
    for fieldname in (
        "cash_drawer",
        "reference_no",
        "receipt_attachment",
        "request_status",
        "requested_by",
        "requested_at",
        "approved_by",
        "approved_at",
        "approval_note",
    ):
        if meta.has_field(fieldname):
            fields.append(fieldname)

    rows = frappe.get_all(
        "Shift Cash Movement",
        fields=fields,
        order_by="movement_date desc, creation desc",
        limit_page_length=cint(limit) or 50,
    )
    for row in rows:
        row["amount"] = flt(row.get("amount"))
        row["request_status"] = row.get("request_status") or (
            "Approved" if cint(row.get("docstatus")) == 1 else "Cancelled" if cint(row.get("docstatus")) == 2 else "Pending Approval"
        )
        row["requested_by"] = row.get("requested_by") or row.get("owner")
        row["can_self_approve"] = bool(
            can_emergency_submit_treasury()
            or row.get("requested_by") != frappe.session.user
        )
    return rows


def _validate_shift_cash_movement_action_access(movement_action):
    movement_action = str(movement_action or "Create Draft").strip()
    if movement_action not in ("Create Draft", "Submit Now"):
        frappe.throw(_("Invalid cash movement action."))
    if movement_action == "Submit Now" and not can_emergency_submit_treasury():
        frappe.throw(
            _("Submit Now is reserved for emergency System Manager use. Save the request as Draft for manager approval."),
            frappe.PermissionError,
        )


def _get_cash_drawers():
    if not frappe.db.exists("DocType", "Cash Drawer"):
        return []

    fields = [
        "name",
        "drawer_name",
        "drawer_code",
        "company",
        "branch",
        "physical_location",
        "enabled",
        "cash_account",
        "default_opening_float",
        "current_responsible_user",
        "current_active_shift",
    ]
    rows = frappe.get_all(
        "Cash Drawer",
        fields=fields,
        order_by="company asc, drawer_name asc",
        limit_page_length=500,
    )

    for row in rows:
        row["enabled"] = cint(row.get("enabled"))
        row["default_opening_float"] = flt(row.get("default_opening_float"))
        if row.get("cash_account"):
            account = frappe.db.get_value(
                "Account",
                row.cash_account,
                ["account_currency", "disabled", "root_type"],
                as_dict=True,
            ) or {}
            row["account_currency"] = account.get("account_currency") or ""
            row["account_disabled"] = cint(account.get("disabled"))
            row["account_root_type"] = account.get("root_type") or ""
            row["current_balance"] = _account_balance(
                row.cash_account, row.company
            )
            last_movement = frappe.get_all(
                "GL Entry",
                filters={
                    "account": row.cash_account,
                    "is_cancelled": 0,
                },
                fields=["posting_date", "creation", "voucher_type", "voucher_no"],
                order_by="posting_date desc, creation desc",
                limit_page_length=1,
            )
            row["last_movement"] = last_movement[0] if last_movement else {}
        else:
            row["account_currency"] = ""
            row["account_disabled"] = 0
            row["account_root_type"] = ""
            row["current_balance"] = 0
            row["last_movement"] = {}

    return rows


def _account_balance(account, company):
    if not account:
        return 0
    try:
        return flt(
            get_balance_on(
                account=account,
                date=nowdate(),
                company=company,
                in_account_currency=True,
            )
        )
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Treasury Management Cash Drawer Balance",
        )
        return 0


def _validate_drawer_account(drawer):
    account = frappe.db.get_value(
        "Account",
        drawer.cash_account,
        [
            "name",
            "company",
            "is_group",
            "disabled",
            "root_type",
            "account_type",
            "account_currency",
        ],
        as_dict=True,
    )
    if not account:
        frappe.throw(_("Cash Account was not found."))
    if account.company != drawer.company:
        frappe.throw(_("Cash Account belongs to another company."))
    if cint(account.is_group):
        frappe.throw(_("Cash Account cannot be a group account."))
    if cint(account.disabled):
        frappe.throw(_("Cash Account is disabled."))
    if account.root_type != "Asset" or account.account_type != "Cash":
        frappe.throw(_("Linked account must be an active Asset Cash account."))
    return account


def _find_open_shift_for_drawer(drawer):
    if not frappe.db.exists("DocType", "Pharmacy Shift Closing"):
        return None

    meta = frappe.get_meta("Pharmacy Shift Closing")
    fields = ["name", "docstatus"]
    for fieldname in (
        "status",
        "end_time",
        "custom_shift_operational_status",
        "custom_cash_drawer",
    ):
        if meta.has_field(fieldname):
            fields.append(fieldname)

    names = []
    if drawer.current_active_shift and frappe.db.exists(
        "Pharmacy Shift Closing", drawer.current_active_shift
    ):
        names.append(drawer.current_active_shift)

    if meta.has_field("custom_cash_drawer"):
        linked = frappe.get_all(
            "Pharmacy Shift Closing",
            filters={"custom_cash_drawer": drawer.name},
            pluck="name",
            order_by="modified desc",
            limit_page_length=20,
        )
        for name in linked:
            if name not in names:
                names.append(name)

    for name in names:
        row = frappe.db.get_value(
            "Pharmacy Shift Closing", name, fields, as_dict=True
        )
        if row and not _shift_is_clearly_closed(row):
            return row.name

    return None


def _shift_is_clearly_closed(row):
    if cint(row.get("docstatus")) == 2:
        return True
    if row.get("end_time"):
        return True

    statuses = {
        str(row.get("status") or "").strip().lower(),
        str(row.get("custom_shift_operational_status") or "").strip().lower(),
    }
    return bool(statuses.intersection({"closed", "completed", "cancelled"}))


def _get_operational_cash_accounts():
    fields = [
        "name",
        "account_name",
        "company",
        "parent_account",
        "account_currency",
        "disabled",
        "root_type",
    ]
    return frappe.get_all(
        "Account",
        filters={
            "account_type": "Cash",
            "root_type": "Asset",
            "is_group": 0,
            "disabled": 0,
        },
        fields=fields,
        order_by="company asc, account_name asc",
        limit_page_length=500,
    )


def _get_cash_account_warnings():
    return frappe.get_all(
        "Account",
        filters={
            "account_type": "Cash",
            "root_type": ["!=", "Asset"],
            "is_group": 0,
        },
        fields=[
            "name",
            "account_name",
            "company",
            "parent_account",
            "root_type",
            "disabled",
        ],
        order_by="company asc, account_name asc",
        limit_page_length=100,
    )




def _get_bank_accounts():
    if not frappe.db.exists("DocType", "Bank Account"):
        return []

    rows = frappe.get_all(
        "Bank Account",
        fields=[
            "name",
            "account_name",
            "account",
            "bank",
            "company",
            "disabled",
            "is_default",
            "bank_account_no",
            "iban",
            "branch_code",
        ],
        order_by="company asc, bank asc, account_name asc",
        limit_page_length=500,
    )
    for row in rows:
        row["disabled"] = cint(row.get("disabled"))
        row["is_default"] = cint(row.get("is_default"))
        row["current_balance"] = 0
        row["account_currency"] = ""
        row["last_movement"] = {}
        if row.get("account"):
            account = frappe.db.get_value(
                "Account",
                row.account,
                ["account_currency", "disabled", "account_type", "root_type"],
                as_dict=True,
            ) or {}
            row["account_currency"] = account.get("account_currency") or ""
            row["ledger_disabled"] = cint(account.get("disabled"))
            row["account_type"] = account.get("account_type") or ""
            row["root_type"] = account.get("root_type") or ""
            row["current_balance"] = _account_balance(row.account, row.company)
            movement = frappe.get_all(
                "GL Entry",
                filters={"account": row.account, "is_cancelled": 0},
                fields=["posting_date", "creation", "voucher_type", "voucher_no"],
                order_by="posting_date desc, creation desc",
                limit_page_length=1,
            )
            row["last_movement"] = movement[0] if movement else {}
        if row.get("bank"):
            bank = frappe.db.get_value(
                "Bank", row.bank, ["swift_number", "website"], as_dict=True
            ) or {}
            row["swift_number"] = bank.get("swift_number") or ""
            row["website"] = bank.get("website") or ""
    return rows


def _get_bank_ledger_accounts():
    return frappe.get_all(
        "Account",
        filters={"account_type": "Bank", "is_group": 0, "disabled": 0},
        fields=[
            "name",
            "account_name",
            "company",
            "parent_account",
            "account_currency",
            "root_type",
            "disabled",
        ],
        order_by="company asc, account_name asc",
        limit_page_length=500,
    )


def _get_unlinked_bank_ledgers(bank_ledgers=None, bank_accounts=None):
    bank_ledgers = bank_ledgers if bank_ledgers is not None else _get_bank_ledger_accounts()
    bank_accounts = bank_accounts if bank_accounts is not None else _get_bank_accounts()
    linked = {str(row.get("account") or "") for row in bank_accounts}
    rows = []
    for row in bank_ledgers:
        if row.name in linked:
            continue
        item = dict(row)
        item["current_balance"] = _account_balance(row.name, row.company)
        rows.append(item)
    return rows


def _bank_parent_accounts(company):
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Asset",
            "is_group": 1,
            "disabled": 0,
        },
        fields=["name", "account_name", "account_type", "parent_account"],
        order_by="lft asc",
        limit_page_length=500,
    )
    rows.sort(
        key=lambda row: (
            0 if str(row.get("account_name") or "").lower() == "bank accounts" else
            1 if str(row.get("account_type") or "").lower() == "bank" else
            2 if "bank" in str(row.get("account_name") or "").lower() else 3,
            row.get("name") or "",
        )
    )
    return rows


def _clearing_parent_accounts(company):
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Asset",
            "is_group": 1,
            "disabled": 0,
        },
        fields=["name", "account_name", "parent_account"],
        order_by="lft asc",
        limit_page_length=500,
    )
    rows.sort(
        key=lambda row: (
            0 if "payment clearing" in str(row.get("account_name") or "").lower() else
            1 if str(row.get("account_name") or "").lower() == "current assets" else 2,
            row.get("name") or "",
        )
    )
    return rows


def _fee_parent_accounts(company):
    rows = frappe.get_all(
        "Account",
        filters={
            "company": company,
            "root_type": "Expense",
            "is_group": 1,
            "disabled": 0,
        },
        fields=["name", "account_name", "parent_account"],
        order_by="lft asc",
        limit_page_length=500,
    )
    rows.sort(
        key=lambda row: (
            0 if "indirect expense" in str(row.get("account_name") or "").lower() else
            1 if str(row.get("account_name") or "").lower() == "expenses" else 2,
            row.get("name") or "",
        )
    )
    return rows




CARD_BATCH_SETTLEABLE_STATUSES = {
    "Awaiting Bank Settlement",
    "Partially Settled",
    "Disputed",
}


def _card_bank_settlement_options(batch_name):
    batch_name = str(batch_name or "").strip()
    if not batch_name or not frappe.db.exists("Card Settlement Batch", batch_name):
        frappe.throw(_("Select an existing Card Settlement Batch."))

    seed = frappe.get_doc("Card Settlement Batch", batch_name)
    _validate_settleable_card_batch(seed)

    batches = frappe.get_all(
        "Card Settlement Batch",
        filters={
            "docstatus": 1,
            "company": seed.company,
            "clearing_account": seed.clearing_account,
            "destination_bank_account": seed.destination_bank_account,
            "status": ["in", sorted(CARD_BATCH_SETTLEABLE_STATUSES)],
            "outstanding_amount": [">", 0.005],
        },
        fields=[
            "name",
            "shift_reference",
            "pos_terminal",
            "bank_label",
            "batch_number",
            "close_time",
            "status",
            "system_total",
            "machine_total",
            "settled_amount",
            "outstanding_amount",
            "clearing_account",
            "destination_bank_account",
            "fee_account",
        ],
        order_by="close_time asc, creation asc",
        limit_page_length=500,
    )
    for row in batches:
        for fieldname in (
            "system_total",
            "machine_total",
            "settled_amount",
            "outstanding_amount",
        ):
            row[fieldname] = flt(row.get(fieldname))
        row["selected"] = cint(row.name == seed.name)

    currency = frappe.db.get_value(
        "Account", seed.clearing_account, "account_currency"
    ) or frappe.db.get_value("Company", seed.company, "default_currency") or ""
    bank_account = frappe.db.get_value(
        "Bank Account",
        {
            "company": seed.company,
            "account": seed.destination_bank_account,
            "disabled": 0,
        },
        ["name", "account_name", "bank"],
        as_dict=True,
    ) or {}
    fee_account = seed.fee_account or frappe.db.get_value(
        "Card POS Terminal", seed.pos_terminal, "fee_account"
    ) or ""

    return {
        "seed_batch": seed.name,
        "company": seed.company,
        "currency": currency,
        "clearing_account": seed.clearing_account,
        "destination_bank_account": seed.destination_bank_account,
        "bank_account": bank_account.get("name") or "",
        "bank_account_name": bank_account.get("account_name") or "",
        "bank": bank_account.get("bank") or seed.bank_label or "",
        "fee_account": fee_account,
        "settlement_date": nowdate(),
        "clearing_balance": flt(_account_balance(seed.clearing_account, seed.company)),
        "batches": batches,
    }


def _parse_card_allocations(allocations):
    if isinstance(allocations, str):
        allocations = frappe.parse_json(allocations)
    if not isinstance(allocations, (list, tuple)):
        frappe.throw(_("Card batch allocations must be a list."))

    normalized = []
    seen = set()
    for row in allocations:
        if not isinstance(row, dict):
            frappe.throw(_("Invalid card batch allocation row."))
        batch_name = str(row.get("card_settlement_batch") or row.get("name") or "").strip()
        amount = flt(row.get("allocated_amount"))
        if not batch_name:
            frappe.throw(_("Every allocation must include a Card Settlement Batch."))
        if batch_name in seen:
            frappe.throw(_("Card batch {0} was selected more than once.").format(batch_name))
        if amount <= 0:
            frappe.throw(_("Allocated amount for {0} must be greater than zero.").format(batch_name))
        seen.add(batch_name)
        normalized.append(
            {
                "card_settlement_batch": batch_name,
                "allocated_amount": amount,
            }
        )
    if not normalized:
        frappe.throw(_("Select at least one Card Settlement Batch."))
    return normalized


def _prepare_card_bank_settlement(
    batch_name,
    allocations,
    settlement_date=None,
    bank_reference=None,
    fee_amount=0,
    statement_attachment=None,
    notes=None,
):
    options = _card_bank_settlement_options(batch_name)
    allocation_rows = _parse_card_allocations(allocations)
    compatible = {row.name: row for row in options["batches"]}

    prepared = []
    gross = 0.0
    latest_close_date = None
    for allocation in allocation_rows:
        batch_id = allocation["card_settlement_batch"]
        if batch_id not in compatible:
            frappe.throw(
                _(
                    "Card batch {0} does not use the same company, clearing account, "
                    "and destination bank account as {1}."
                ).format(batch_id, options["seed_batch"])
            )
        batch = frappe.get_doc("Card Settlement Batch", batch_id)
        _validate_settleable_card_batch(batch)
        available = flt(batch.outstanding_amount)
        allocated = flt(allocation["allocated_amount"])
        if allocated - available > 0.01:
            frappe.throw(
                _("Allocated amount for {0} exceeds the available amount {1}.").format(
                    batch.name, available
                )
            )
        if batch.close_time:
            close_date = getdate(batch.close_time)
            latest_close_date = max(latest_close_date, close_date) if latest_close_date else close_date
        gross += allocated
        prepared.append(
            {
                "card_settlement_batch": batch.name,
                "shift_reference": batch.shift_reference,
                "pos_terminal": batch.pos_terminal,
                "batch_number": batch.batch_number or "",
                "status": batch.status,
                "close_time": batch.close_time,
                "available_amount": available,
                "allocated_amount": allocated,
            }
        )

    settlement_date = getdate(settlement_date or nowdate())
    if settlement_date > getdate(nowdate()):
        frappe.throw(_("Settlement Date cannot be in the future."))
    if latest_close_date and settlement_date < latest_close_date:
        frappe.throw(
            _("Settlement Date cannot be earlier than the latest selected batch close date {0}.").format(
                latest_close_date
            )
        )

    bank_reference = _clean_master_text(bank_reference)
    if not bank_reference:
        frappe.throw(_("Bank Reference is required."))
    duplicate_reference = frappe.db.get_value(
        "Card Bank Settlement",
        {
            "company": options["company"],
            "bank_reference": bank_reference,
            "docstatus": ["!=", 2],
        },
        "name",
    )
    if duplicate_reference:
        frappe.throw(
            _("Bank Reference is already used by Card Bank Settlement {0}.").format(
                duplicate_reference
            )
        )

    fee_amount = flt(fee_amount)
    if fee_amount < 0:
        frappe.throw(_("Fee Amount cannot be negative."))
    if fee_amount - gross > 0.01:
        frappe.throw(_("Fee Amount cannot exceed Gross Amount."))
    fee_account = options.get("fee_account") or ""
    if fee_amount > 0 and not fee_account:
        frappe.throw(_("Fee Account is required when bank fees are entered."))

    _validate_company_account(
        options["clearing_account"],
        options["company"],
        expected_root="Asset",
        label=_("Clearing Account"),
    )
    _validate_company_account(
        options["destination_bank_account"],
        options["company"],
        expected_root="Asset",
        expected_type="Bank",
        label=_("Destination Bank Account"),
    )
    if fee_account:
        _validate_company_account(
            fee_account,
            options["company"],
            expected_root="Expense",
            label=_("Fee Account"),
        )

    clearing_balance = flt(_account_balance(options["clearing_account"], options["company"]))
    if clearing_balance + 0.01 < gross:
        frappe.throw(
            _(
                "Clearing balance {0} is lower than the selected gross settlement {1}."
            ).format(clearing_balance, gross)
        )

    return {
        "seed_batch": options["seed_batch"],
        "company": options["company"],
        "currency": options["currency"],
        "settlement_date": str(settlement_date),
        "bank_reference": bank_reference,
        "statement_attachment": str(statement_attachment or "").strip(),
        "clearing_account": options["clearing_account"],
        "destination_bank_account": options["destination_bank_account"],
        "bank_account": options.get("bank_account") or "",
        "bank_account_name": options.get("bank_account_name") or "",
        "bank": options.get("bank") or "",
        "fee_account": fee_account,
        "gross_amount": flt(gross),
        "fee_amount": fee_amount,
        "net_amount": flt(gross - fee_amount),
        "clearing_balance_before": clearing_balance,
        "clearing_balance_after": flt(clearing_balance - gross),
        "notes": str(notes or "").strip(),
        "allocations": prepared,
    }


def _validate_settleable_card_batch(batch):
    if batch.docstatus != 1:
        frappe.throw(_("Card batch must be submitted: {0}").format(batch.name))
    if batch.status not in CARD_BATCH_SETTLEABLE_STATUSES:
        frappe.throw(
            _("Card batch {0} is not open for bank settlement (status: {1}).").format(
                batch.name, batch.status
            )
        )
    if flt(batch.outstanding_amount) <= 0.005:
        frappe.throw(_("Card batch {0} has no outstanding amount.").format(batch.name))
    if not batch.clearing_account or not batch.destination_bank_account:
        frappe.throw(_("Card batch {0} has incomplete account configuration.").format(batch.name))


def _get_pending_settlement_dashboard(terminals=None, payment_setups=None):
    """Build a read-only dashboard for clearing balances and overdue settlements."""
    terminals = terminals if terminals is not None else _get_card_terminals()
    payment_setups = (
        payment_setups if payment_setups is not None else _get_payment_method_setups()
    )
    today = getdate(nowdate())

    accounts = {}

    def register_account(account_name, company, source_type, source_name, destination=None):
        account_name = str(account_name or "").strip()
        company = str(company or "").strip()
        if not account_name or not company:
            return

        row = accounts.setdefault(
            account_name,
            {
                "account": account_name,
                "company": company,
                "currency": "",
                "disabled": 0,
                "sources": [],
                "destination_accounts": [],
                "current_balance": 0.0,
                "documented_pending": 0.0,
                "card_pending": 0.0,
                "payment_pending": 0.0,
                "open_document_count": 0,
                "overdue_document_count": 0,
                "oldest_pending_days": 0,
                "last_movement": {},
            },
        )
        source = {
            "type": source_type,
            "name": source_name,
        }
        if source not in row["sources"]:
            row["sources"].append(source)
        destination = str(destination or "").strip()
        if destination and destination not in row["destination_accounts"]:
            row["destination_accounts"].append(destination)

    for terminal in terminals or []:
        register_account(
            terminal.get("clearing_account"),
            terminal.get("company"),
            "Card POS Terminal",
            terminal.get("terminal_name") or terminal.get("name"),
            terminal.get("destination_bank_account"),
        )

    for setup in payment_setups or []:
        register_account(
            setup.get("clearing_account"),
            setup.get("company"),
            "Payment Method",
            setup.get("mode_of_payment") or setup.get("name"),
            setup.get("destination_account"),
        )

    for row in accounts.values():
        meta = frappe.db.get_value(
            "Account",
            row["account"],
            ["account_currency", "disabled", "root_type", "is_group"],
            as_dict=True,
        ) or {}
        row["currency"] = meta.get("account_currency") or ""
        row["disabled"] = cint(meta.get("disabled"))
        row["current_balance"] = _account_balance(row["account"], row["company"])
        movement = frappe.get_all(
            "GL Entry",
            filters={"account": row["account"], "is_cancelled": 0},
            fields=["posting_date", "creation", "voucher_type", "voucher_no"],
            order_by="posting_date desc, creation desc",
            limit_page_length=1,
        )
        row["last_movement"] = movement[0] if movement else {}

    open_card_batches = []
    if frappe.db.exists("DocType", "Card Settlement Batch"):
        card_rows = frappe.get_all(
            "Card Settlement Batch",
            filters={
                "docstatus": ["!=", 2],
                "status": [
                    "in",
                    [
                        "Draft",
                        "Awaiting Bank Settlement",
                        "Partially Settled",
                        "Disputed",
                    ],
                ],
            },
            fields=[
                "name",
                "company",
                "pos_terminal",
                "bank_label",
                "status",
                "close_time",
                "creation",
                "system_total",
                "machine_total",
                "settled_amount",
                "outstanding_amount",
                "clearing_account",
                "destination_bank_account",
                "bank_settlement",
            ],
            order_by="close_time asc, creation asc",
            limit_page_length=1000,
        )
        for batch in card_rows:
            outstanding = flt(batch.get("outstanding_amount"))
            if outstanding <= 0.005 and batch.get("status") not in ("Draft", "Disputed"):
                continue
            basis = batch.get("close_time") or batch.get("creation")
            age_days = max(date_diff(today, getdate(basis)), 0) if basis else 0
            overdue = bool(basis and getdate(basis) < today)
            batch["system_total"] = flt(batch.get("system_total"))
            batch["machine_total"] = flt(batch.get("machine_total"))
            batch["settled_amount"] = flt(batch.get("settled_amount"))
            batch["outstanding_amount"] = outstanding
            batch["age_days"] = age_days
            batch["overdue"] = overdue
            batch["severity"] = (
                "critical"
                if batch.get("status") == "Disputed" or age_days >= 3
                else "warning"
                if overdue
                else "info"
            )
            register_account(
                batch.get("clearing_account"),
                batch.get("company"),
                "Card Settlement Batch",
                batch.get("pos_terminal") or batch.get("name"),
                batch.get("destination_bank_account"),
            )
            open_card_batches.append(batch)

            account_row = accounts.get(batch.get("clearing_account"))
            if account_row:
                account_row["card_pending"] += outstanding
                account_row["documented_pending"] += outstanding
                account_row["open_document_count"] += 1
                account_row["overdue_document_count"] += cint(overdue)
                account_row["oldest_pending_days"] = max(
                    cint(account_row.get("oldest_pending_days")), age_days
                )

    setup_by_name = {row.get("name"): row for row in payment_setups or []}
    open_reconciliations = []
    if frappe.db.exists("DocType", "Shift Payment Reconciliation"):
        reconciliation_rows = frappe.get_all(
            "Shift Payment Reconciliation",
            filters={
                "docstatus": ["!=", 2],
                "status": ["in", ["Draft", "Reviewed"]],
            },
            fields=[
                "name",
                "setup_reference",
                "shift_reference",
                "company",
                "mode_of_payment",
                "status",
                "from_time",
                "to_time",
                "expected_amount",
                "reviewed_amount",
                "difference",
                "fee_amount",
                "net_transfer_amount",
                "clearing_account",
                "destination_account",
                "settlement_policy",
                "journal_entry",
                "creation",
                "modified",
            ],
            order_by="to_time asc, creation asc",
            limit_page_length=1000,
        )
        for reconciliation in reconciliation_rows:
            setup = setup_by_name.get(reconciliation.get("setup_reference")) or {}
            clearing_account = reconciliation.get("clearing_account") or setup.get("clearing_account") or ""
            destination_account = reconciliation.get("destination_account") or setup.get("destination_account") or ""
            expected = flt(reconciliation.get("expected_amount"))
            reviewed = flt(reconciliation.get("reviewed_amount"))
            difference = flt(reconciliation.get("difference"))
            fee_amount = flt(reconciliation.get("fee_amount"))
            net_transfer = flt(reconciliation.get("net_transfer_amount"))
            pending_amount = reviewed if reviewed > 0 else expected
            if net_transfer > 0 and reconciliation.get("status") == "Reviewed":
                pending_amount = net_transfer + fee_amount

            basis = reconciliation.get("to_time") or reconciliation.get("creation")
            age_days = max(date_diff(today, getdate(basis)), 0) if basis else 0
            overdue = bool(basis and getdate(basis) < today)
            register_account(
                clearing_account,
                reconciliation.get("company"),
                "Shift Payment Reconciliation",
                reconciliation.get("mode_of_payment") or reconciliation.get("name"),
                destination_account,
            )
            reconciliation.update(
                {
                    "clearing_account": clearing_account,
                    "destination_account": destination_account,
                    "expected_amount": expected,
                    "reviewed_amount": reviewed,
                    "difference": difference,
                    "fee_amount": fee_amount,
                    "net_transfer_amount": net_transfer,
                    "pending_amount": pending_amount,
                    "age_days": age_days,
                    "overdue": overdue,
                    "severity": "critical" if age_days >= 3 else "warning" if overdue else "info",
                }
            )
            open_reconciliations.append(reconciliation)

            account_row = accounts.get(clearing_account)
            if account_row:
                account_row["payment_pending"] += pending_amount
                account_row["documented_pending"] += pending_amount
                account_row["open_document_count"] += 1
                account_row["overdue_document_count"] += cint(overdue)
                account_row["oldest_pending_days"] = max(
                    cint(account_row.get("oldest_pending_days")), age_days
                )

    # Open documents can reference an account not currently present in an active setup.
    # Enrich any such account before building totals and alerts.
    for row in accounts.values():
        if row.get("currency") or row.get("last_movement"):
            continue
        meta = frappe.db.get_value(
            "Account",
            row["account"],
            ["account_currency", "disabled", "root_type", "is_group"],
            as_dict=True,
        ) or {}
        row["currency"] = meta.get("account_currency") or ""
        row["disabled"] = cint(meta.get("disabled"))
        row["current_balance"] = _account_balance(row["account"], row["company"])
        movement = frappe.get_all(
            "GL Entry",
            filters={"account": row["account"], "is_cancelled": 0},
            fields=["posting_date", "creation", "voucher_type", "voucher_no"],
            order_by="posting_date desc, creation desc",
            limit_page_length=1,
        )
        row["last_movement"] = movement[0] if movement else {}

    alerts = []
    account_rows = []
    for row in accounts.values():
        row["current_balance"] = flt(row.get("current_balance"))
        row["documented_pending"] = flt(row.get("documented_pending"))
        row["card_pending"] = flt(row.get("card_pending"))
        row["payment_pending"] = flt(row.get("payment_pending"))
        row["unmatched_balance"] = flt(
            row["current_balance"] - row["documented_pending"]
        )
        row["source_label"] = "، ".join(
            source.get("name") or source.get("type") or ""
            for source in row.get("sources") or []
        )
        row["destination_label"] = "، ".join(row.get("destination_accounts") or [])

        if row.get("disabled"):
            alerts.append(
                {
                    "severity": "critical",
                    "type": "disabled_account",
                    "title": _("Referenced clearing account is disabled"),
                    "message": _("Account {0} is disabled but still linked to treasury settings.").format(row["account"]),
                    "account": row["account"],
                }
            )
        if row["current_balance"] < -0.005:
            alerts.append(
                {
                    "severity": "critical",
                    "type": "negative_balance",
                    "title": _("Negative clearing balance"),
                    "message": _("Account {0} has a negative balance of {1}.").format(
                        row["account"], row["current_balance"]
                    ),
                    "account": row["account"],
                }
            )
        if abs(row["unmatched_balance"]) > 0.01:
            alerts.append(
                {
                    "severity": "warning",
                    "type": "unmatched_balance",
                    "title": _("Clearing balance needs review"),
                    "message": _("Account {0} differs from documented open settlements by {1}.").format(
                        row["account"], row["unmatched_balance"]
                    ),
                    "account": row["account"],
                }
            )
        account_rows.append(row)

    for batch in open_card_batches:
        if batch.get("overdue") or batch.get("status") == "Disputed":
            alerts.append(
                {
                    "severity": batch.get("severity"),
                    "type": "card_batch",
                    "title": _("Card settlement batch needs attention"),
                    "message": _("Batch {0} is {1} with {2} still outstanding.").format(
                        batch.get("name"), batch.get("status"), batch.get("outstanding_amount")
                    ),
                    "doctype": "Card Settlement Batch",
                    "document": batch.get("name"),
                }
            )

    for reconciliation in open_reconciliations:
        if reconciliation.get("overdue"):
            alerts.append(
                {
                    "severity": reconciliation.get("severity"),
                    "type": "payment_reconciliation",
                    "title": _("Payment reconciliation is overdue"),
                    "message": _("Reconciliation {0} for {1} has been open for {2} day(s).").format(
                        reconciliation.get("name"),
                        reconciliation.get("mode_of_payment") or "-",
                        reconciliation.get("age_days") or 0,
                    ),
                    "doctype": "Shift Payment Reconciliation",
                    "document": reconciliation.get("name"),
                }
            )

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda row: (severity_order.get(row.get("severity"), 9), row.get("title") or ""))
    open_card_batches.sort(key=lambda row: (-cint(row.get("overdue")), -cint(row.get("age_days")), row.get("name") or ""))
    open_reconciliations.sort(key=lambda row: (-cint(row.get("overdue")), -cint(row.get("age_days")), row.get("name") or ""))
    account_rows.sort(key=lambda row: (-cint(row.get("overdue_document_count")), -abs(flt(row.get("unmatched_balance"))), row.get("account") or ""))

    currencies = {row.get("currency") for row in account_rows if row.get("currency")}
    summary_currency = next(iter(currencies)) if len(currencies) == 1 else ""
    total_clearing_balance = sum(flt(row.get("current_balance")) for row in account_rows)
    total_documented_pending = sum(flt(row.get("documented_pending")) for row in account_rows)
    total_unmatched_balance = flt(total_clearing_balance - total_documented_pending)

    return {
        "generated_on": nowdate(),
        "currency": summary_currency,
        "summary": {
            "clearing_account_count": len(account_rows),
            "total_clearing_balance": total_clearing_balance,
            "total_documented_pending": total_documented_pending,
            "total_unmatched_balance": total_unmatched_balance,
            "accounts_needing_review": sum(
                1 for row in account_rows if abs(flt(row.get("unmatched_balance"))) > 0.01
            ),
            "open_card_batch_count": len(open_card_batches),
            "open_card_batch_amount": sum(
                flt(row.get("outstanding_amount")) for row in open_card_batches
            ),
            "overdue_card_batch_count": sum(cint(row.get("overdue")) for row in open_card_batches),
            "overdue_card_batch_amount": sum(
                flt(row.get("outstanding_amount"))
                for row in open_card_batches
                if row.get("overdue")
            ),
            "open_reconciliation_count": len(open_reconciliations),
            "open_reconciliation_amount": sum(
                flt(row.get("pending_amount")) for row in open_reconciliations
            ),
            "overdue_reconciliation_count": sum(
                cint(row.get("overdue")) for row in open_reconciliations
            ),
            "overdue_reconciliation_amount": sum(
                flt(row.get("pending_amount"))
                for row in open_reconciliations
                if row.get("overdue")
            ),
            "critical_alert_count": sum(1 for row in alerts if row.get("severity") == "critical"),
            "warning_alert_count": sum(1 for row in alerts if row.get("severity") == "warning"),
        },
        "accounts": account_rows,
        "open_card_batches": open_card_batches,
        "open_reconciliations": open_reconciliations,
        "alerts": alerts,
    }


def _get_payment_method_setups():
    if not frappe.db.exists("DocType", "Payment Method Clearing Setup"):
        return []
    rows = frappe.get_all(
        "Payment Method Clearing Setup",
        fields=[
            "name", "company", "mode_of_payment", "enabled", "settlement_policy",
            "clearing_account", "destination_account", "fee_account", "notes",
        ],
        order_by="company asc, mode_of_payment asc",
        limit_page_length=500,
    )
    for row in rows:
        row["enabled"] = cint(row.get("enabled"))
        row["clearing_balance"] = _account_balance(row.clearing_account, row.company) if row.get("clearing_account") else 0
        row["destination_balance"] = _account_balance(row.destination_account, row.company) if row.get("destination_account") else 0
        account = frappe.db.get_value(
            "Account",
            row.clearing_account,
            ["account_currency", "disabled"],
            as_dict=True,
        ) if row.get("clearing_account") else {}
        row["account_currency"] = (account or {}).get("account_currency") or ""
        row["clearing_disabled"] = cint((account or {}).get("disabled"))
        destination = frappe.db.get_value(
            "Account",
            row.destination_account,
            ["account_currency", "disabled", "account_type"],
            as_dict=True,
        ) if row.get("destination_account") else {}
        row["destination_disabled"] = cint((destination or {}).get("disabled"))
        bank_account = frappe.db.get_value(
            "Bank Account",
            {
                "company": row.company,
                "account": row.destination_account,
                "disabled": 0,
                "is_company_account": 1,
            },
            ["name", "account_name", "bank"],
            as_dict=True,
        ) or {}
        row["bank_account"] = bank_account.get("name") or ""
        row["bank_account_name"] = bank_account.get("account_name") or ""
        row["bank"] = bank_account.get("bank") or ""
        recs = _get_open_payment_reconciliations(row.name, limit=100)
        row["open_reconciliation_count"] = len(recs)
        row["open_expected_amount"] = sum(flt(item.get("expected_amount")) for item in recs)
        row["card_terminal_count"] = frappe.db.count(
            "Card POS Terminal",
            filters={"company": row.company, "mode_of_payment": row.mode_of_payment},
        ) if frappe.db.exists("DocType", "Card POS Terminal") else 0
        movement = frappe.get_all(
            "GL Entry",
            filters={"account": row.clearing_account, "is_cancelled": 0},
            fields=["posting_date", "creation", "voucher_type", "voucher_no"],
            order_by="posting_date desc, creation desc",
            limit_page_length=1,
        ) if row.get("clearing_account") else []
        row["last_movement"] = movement[0] if movement else {}
    return rows


def _get_open_payment_reconciliations(setup_name, limit=100):
    if not frappe.db.exists("DocType", "Shift Payment Reconciliation"):
        return []
    rows = frappe.get_all(
        "Shift Payment Reconciliation",
        filters={
            "setup_reference": setup_name,
            "docstatus": ["!=", 2],
            "status": ["in", ["Draft", "Reviewed"]],
        },
        fields=[
            "name", "shift_reference", "company", "mode_of_payment", "status",
            "from_time", "to_time", "expected_amount", "reviewed_amount",
            "difference", "fee_amount", "net_transfer_amount", "journal_entry",
            "creation", "modified",
        ],
        order_by="creation asc",
        limit_page_length=max(1, min(cint(limit) or 100, 500)),
    )
    for row in rows:
        for fieldname in (
            "expected_amount", "reviewed_amount", "difference", "fee_amount", "net_transfer_amount"
        ):
            row[fieldname] = flt(row.get(fieldname))
    return rows


def _serialize_payment_setup_for_edit(setup, bank_account):
    if not setup:
        return None
    destination_mode = "Use Bank Account" if bank_account else "Use Existing Account"
    return {
        "name": setup.name,
        "company": setup.company,
        "mode_of_payment": setup.mode_of_payment,
        "enabled": cint(setup.enabled),
        "settlement_policy": setup.settlement_policy,
        "destination_mode": destination_mode,
        "bank_account": bank_account or "",
        "destination_account": setup.destination_account,
        "clearing_account": setup.clearing_account,
        "fee_account": setup.fee_account or "",
        "notes": setup.notes or "",
    }



def _sync_mode_of_payment_account(mode_of_payment, company, clearing_account):
    """Keep ERPNext Mode of Payment company default aligned with the setup."""
    doc = frappe.get_doc("Mode of Payment", mode_of_payment)
    row = None
    for account_row in doc.get("accounts") or []:
        if account_row.company == company:
            row = account_row
            break
    if not row:
        row = doc.append("accounts", {"company": company})
    row.default_account = clearing_account
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)

def _default_non_card_mode_of_payment():
    for name in ("Insta Pay", "Wallet", "Bank Transfer", "Transfer"):
        if frappe.db.exists("Mode of Payment", name):
            return name
    rows = frappe.get_all(
        "Mode of Payment",
        pluck="name",
        order_by="name asc",
        limit_page_length=1,
    )
    return rows[0] if rows else ""

def _get_card_terminals():
    if not frappe.db.exists("DocType", "Card POS Terminal"):
        return []

    rows = frappe.get_all(
        "Card POS Terminal",
        fields=[
            "name", "terminal_name", "terminal_code", "company", "mode_of_payment",
            "bank_label", "merchant_id", "terminal_id", "enabled", "clearing_account",
            "destination_bank_account", "fee_account", "notes",
        ],
        order_by="company asc, bank_label asc, terminal_name asc",
        limit_page_length=500,
    )
    for row in rows:
        row["enabled"] = cint(row.get("enabled"))
        row["current_balance"] = _account_balance(row.clearing_account, row.company) if row.get("clearing_account") else 0
        row["account_currency"] = ""
        row["last_movement"] = {}
        if row.get("clearing_account"):
            account = frappe.db.get_value(
                "Account", row.clearing_account,
                ["account_currency", "disabled", "root_type", "is_group"],
                as_dict=True,
            ) or {}
            row["account_currency"] = account.get("account_currency") or ""
            row["clearing_disabled"] = cint(account.get("disabled"))
            movement = frappe.get_all(
                "GL Entry",
                filters={"account": row.clearing_account, "is_cancelled": 0},
                fields=["posting_date", "creation", "voucher_type", "voucher_no"],
                order_by="posting_date desc, creation desc",
                limit_page_length=1,
            )
            row["last_movement"] = movement[0] if movement else {}

        bank_account = frappe.db.get_value(
            "Bank Account",
            {"company": row.company, "account": row.destination_bank_account, "disabled": 0},
            ["name", "account_name", "bank"],
            as_dict=True,
        ) or {}
        row["bank_account"] = bank_account.get("name") or ""
        row["bank_account_name"] = bank_account.get("account_name") or ""
        if bank_account.get("bank"):
            row["bank_label"] = bank_account.bank

        batches = _get_open_card_batches(row.name, limit=100)
        row["open_batch_count"] = len(batches)
        row["open_outstanding_amount"] = sum(flt(item.get("outstanding_amount")) for item in batches)
        row["late_batch_count"] = sum(cint(item.get("is_late")) for item in batches)
        row["oldest_open_batch_date"] = min(
            (str(item.get("close_time") or "") for item in batches if item.get("close_time")),
            default="",
        )
    return rows


def _get_open_card_batches(terminal_name, limit=100):
    if not frappe.db.exists("DocType", "Card Settlement Batch"):
        return []
    rows = frappe.get_all(
        "Card Settlement Batch",
        filters={
            "pos_terminal": terminal_name,
            "docstatus": ["!=", 2],
            "status": ["not in", ["Settled", "Cancelled"]],
        },
        fields=[
            "name", "shift_reference", "batch_number", "close_time", "system_total",
            "machine_total", "settled_amount", "outstanding_amount", "status", "docstatus",
            "bank_settlement", "clearing_account", "destination_bank_account",
        ],
        order_by="close_time asc, creation asc",
        limit_page_length=max(1, min(cint(limit) or 100, 500)),
    )
    today = getdate(nowdate())
    for row in rows:
        for fieldname in ("system_total", "machine_total", "settled_amount", "outstanding_amount"):
            row[fieldname] = flt(row.get(fieldname))
        close_date = getdate(row.close_time) if row.get("close_time") else None
        row["age_days"] = max(0, date_diff(today, close_date)) if close_date else 0
        row["is_late"] = cint(bool(close_date and close_date < today))
    return rows


def _serialize_terminal_for_edit(terminal, bank_account):
    if not terminal:
        return None
    return {
        "name": terminal.name,
        "terminal_name": terminal.terminal_name,
        "terminal_code": terminal.terminal_code,
        "company": terminal.company,
        "mode_of_payment": terminal.mode_of_payment,
        "bank_account": bank_account or "",
        "bank_label": terminal.bank_label,
        "merchant_id": terminal.merchant_id or "",
        "terminal_id": terminal.terminal_id or "",
        "enabled": cint(terminal.enabled),
        "clearing_account": terminal.clearing_account,
        "destination_bank_account": terminal.destination_bank_account,
        "fee_account": terminal.fee_account or "",
        "notes": terminal.notes or "",
    }


def _validate_terminal_accounts(terminal):
    _validate_company_account(
        terminal.clearing_account,
        terminal.company,
        expected_root="Asset",
        expected_type=None,
        label=_("Clearing Account"),
    )
    _validate_company_account(
        terminal.destination_bank_account,
        terminal.company,
        expected_root="Asset",
        expected_type="Bank",
        label=_("Destination Bank Account"),
    )
    if terminal.fee_account:
        _validate_company_account(
            terminal.fee_account,
            terminal.company,
            expected_root="Expense",
            expected_type=None,
            label=_("Fee Account"),
        )


def _normalize_terminal_code(value):
    value = _clean_master_text(value).upper()
    value = re.sub(r"[^A-Z0-9_-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-_")
    return value[:140]


def _next_terminal_code():
    rows = frappe.get_all("Card POS Terminal", fields=["terminal_code"], limit_page_length=1000)
    highest = 0
    for row in rows:
        match = re.search(r"(\d+)$", str(row.get("terminal_code") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"CARD-{highest + 1:02d}"


def _default_card_mode_of_payment():
    for name in ("Credit Card", "Card", "Visa"):
        if frappe.db.exists("Mode of Payment", name):
            return name
    rows = frappe.get_all(
        "Mode of Payment",
        filters={"enabled": 1} if frappe.get_meta("Mode of Payment").has_field("enabled") else {},
        pluck="name",
        order_by="name asc",
        limit_page_length=1,
    )
    return rows[0] if rows else ""


def _default_fee_account(company):
    if frappe.db.exists("DocType", "Payment Method Clearing Setup"):
        row = frappe.db.get_value(
            "Payment Method Clearing Setup",
            {"company": company, "mode_of_payment": _default_card_mode_of_payment(), "enabled": 1},
            "fee_account",
        )
        if row:
            return row
    for account_name in ("Payment Processing Fees", "Bank Charges"):
        row = frappe.db.get_value(
            "Account",
            {"company": company, "account_name": account_name, "root_type": "Expense", "is_group": 0, "disabled": 0},
            "name",
        )
        if row:
            return row
    return ""


def _count_leaf_accounts(account_type):
    return frappe.db.count(
        "Account",
        filters={
            "account_type": account_type,
            "is_group": 0,
            "disabled": 0,
        },
    )


def _get_open_payment_reconciliation(reconciliation_name):
    reconciliation_name = str(reconciliation_name or "").strip()
    if not reconciliation_name or not frappe.db.exists(
        "Shift Payment Reconciliation", reconciliation_name
    ):
        frappe.throw(_("Payment Reconciliation was not found."))

    doc = frappe.get_doc("Shift Payment Reconciliation", reconciliation_name)
    if doc.docstatus != 1:
        frappe.throw(_("Only a submitted reconciliation can be settled."))
    if doc.status not in ("Draft", "Reviewed"):
        frappe.throw(
            _("Reconciliation {0} is not open for settlement.").format(doc.name)
        )

    linked = str(doc.journal_entry or "").strip()
    if linked:
        journal_status = frappe.db.get_value("Journal Entry", linked, "docstatus")
        if cint(journal_status) == 1:
            frappe.throw(
                _("Reconciliation is already linked to submitted Journal Entry {0}.").format(linked)
            )
        frappe.throw(
            _("Reconciliation has a non-submitted Journal Entry link {0}. Review it first.").format(linked)
        )
    return doc


def _reconciliation_settlement_details(doc):
    expected = flt(doc.expected_amount)
    reviewed = flt(doc.reviewed_amount) or expected
    fee_amount = flt(doc.fee_amount)
    net_amount = flt(reviewed - fee_amount)
    balance = _account_balance(doc.clearing_account, doc.company)
    return {
        "reconciliation": doc.name,
        "shift_reference": doc.shift_reference,
        "company": doc.company,
        "mode_of_payment": doc.mode_of_payment,
        "status": doc.status,
        "expected_amount": expected,
        "reviewed_amount": reviewed,
        "difference": flt(reviewed - expected),
        "fee_amount": fee_amount,
        "net_transfer_amount": net_amount,
        "clearing_account": doc.clearing_account,
        "destination_account": doc.destination_account,
        "fee_account": doc.fee_account or "",
        "settlement_policy": doc.settlement_policy,
        "to_time": doc.to_time,
        "posting_date": str(getdate(doc.to_time or nowdate())),
        "clearing_balance": flt(balance),
        "notes": doc.notes or "",
        "currency": frappe.db.get_value("Company", doc.company, "default_currency") or "",
    }


def _prepare_payment_reconciliation_settlement(
    reconciliation_name,
    settlement_action,
    fee_amount=0,
    posting_date=None,
    bank_reference=None,
    existing_journal_entry=None,
    notes=None,
):
    doc = _get_open_payment_reconciliation(reconciliation_name)
    settlement_action = str(settlement_action or "").strip()
    if settlement_action not in (
        "Create New Journal Entry",
        "Link Existing Journal Entry",
    ):
        frappe.throw(_("Select a valid settlement action."))

    expected = flt(doc.expected_amount)
    reviewed = flt(doc.reviewed_amount) or expected
    if reviewed <= 0:
        frappe.throw(_("Reviewed Amount must be greater than zero."))
    difference = flt(reviewed - expected)
    if abs(difference) > 0.01:
        frappe.throw(_("Reviewed Amount must equal Expected Amount."))

    fee_amount = flt(fee_amount)
    if fee_amount < 0:
        frappe.throw(_("Fee Amount cannot be negative."))
    if fee_amount > reviewed:
        frappe.throw(_("Fee Amount cannot exceed Reviewed Amount."))
    net_amount = flt(reviewed - fee_amount)

    _validate_company_account(
        doc.clearing_account,
        doc.company,
        expected_root="Asset",
        label=_("Clearing Account"),
    )
    _validate_company_account(
        doc.destination_account,
        doc.company,
        expected_root="Asset",
        label=_("Destination Account"),
    )
    if fee_amount > 0:
        if not doc.fee_account:
            frappe.throw(_("Fee Account is required when a fee is entered."))
        _validate_company_account(
            doc.fee_account,
            doc.company,
            expected_root="Expense",
            label=_("Fee Account"),
        )

    posting_date = str(getdate(posting_date or doc.to_time or nowdate()))
    bank_reference = _clean_master_text(bank_reference)
    notes = str(notes or "").strip()
    clearing_balance = flt(_account_balance(doc.clearing_account, doc.company))
    after_balance = flt(clearing_balance - reviewed)

    existing_journal_entry = str(existing_journal_entry or "").strip()
    if settlement_action == "Create New Journal Entry":
        if existing_journal_entry:
            frappe.throw(_("Do not select an existing Journal Entry when creating a new one."))
        if not bank_reference:
            frappe.throw(_("Bank Reference is required for a new settlement Journal Entry."))
        if clearing_balance + 0.01 < reviewed:
            frappe.throw(
                _(
                    "Clearing balance {0} is lower than the settlement amount {1}. "
                    "Link the existing Journal Entry or review previous postings."
                ).format(clearing_balance, reviewed)
            )
    else:
        if not existing_journal_entry:
            frappe.throw(_("Select the existing Journal Entry to link."))
        _validate_existing_reconciliation_journal(
            doc,
            existing_journal_entry,
            reviewed,
            fee_amount,
            net_amount,
        )

    return {
        "reconciliation": doc.name,
        "shift_reference": doc.shift_reference,
        "company": doc.company,
        "mode_of_payment": doc.mode_of_payment,
        "settlement_action": settlement_action,
        "posting_date": posting_date,
        "bank_reference": bank_reference,
        "existing_journal_entry": existing_journal_entry,
        "expected_amount": expected,
        "reviewed_amount": reviewed,
        "difference": difference,
        "fee_amount": fee_amount,
        "net_transfer_amount": net_amount,
        "clearing_account": doc.clearing_account,
        "destination_account": doc.destination_account,
        "fee_account": doc.fee_account or "",
        "clearing_balance_before": clearing_balance,
        "clearing_balance_after": after_balance,
        "notes": notes,
    }


def _validate_existing_reconciliation_journal(
    reconciliation,
    journal_name,
    reviewed_amount,
    fee_amount,
    net_amount,
):
    if not frappe.db.exists("Journal Entry", journal_name):
        frappe.throw(_("Existing Journal Entry was not found."))
    journal = frappe.get_doc("Journal Entry", journal_name)
    if journal.docstatus != 1:
        frappe.throw(_("Existing Journal Entry must be submitted."))
    if journal.company != reconciliation.company:
        frappe.throw(_("Existing Journal Entry belongs to another company."))

    other_link = frappe.db.get_value(
        "Shift Payment Reconciliation",
        {
            "journal_entry": journal_name,
            "name": ["!=", reconciliation.name],
            "docstatus": ["!=", 2],
        },
        "name",
    )
    if other_link:
        frappe.throw(
            _("Journal Entry is already linked to reconciliation {0}.").format(other_link)
        )

    expected_net = {
        reconciliation.destination_account: flt(net_amount),
        reconciliation.clearing_account: flt(-reviewed_amount),
    }
    if fee_amount > 0:
        expected_net[reconciliation.fee_account] = flt(
            expected_net.get(reconciliation.fee_account, 0) + fee_amount
        )

    actual_net = {}
    for row in journal.accounts:
        amount = flt(row.debit) - flt(row.credit)
        if abs(amount) <= 0.005:
            continue
        actual_net[row.account] = flt(actual_net.get(row.account, 0) + amount)

    unexpected = {
        account: amount
        for account, amount in actual_net.items()
        if account not in expected_net and abs(amount) > 0.01
    }
    if unexpected:
        frappe.throw(
            _("Existing Journal Entry contains unrelated account movements: {0}.").format(
                ", ".join(sorted(unexpected))
            )
        )

    for account, expected_amount in expected_net.items():
        actual_amount = flt(actual_net.get(account))
        if abs(actual_amount - expected_amount) > 0.01:
            frappe.throw(
                _(
                    "Journal Entry amount for {0} is {1}, expected {2}."
                ).format(account, actual_amount, expected_amount)
            )
    return journal


def _safe_count(doctype):
    if not frappe.db.exists("DocType", doctype):
        return 0
    return frappe.db.count(doctype)


def _can_create_cash_drawer():
    return can_manage_treasury()


def _validate_create_access():
    _validate_manager_access()


def _validate_operator_access():
    if can_operate_treasury():
        return
    frappe.throw(
        _("Only Treasury Operator, Treasury Manager, Accounts Manager, or System Manager can prepare Treasury operations."),
        frappe.PermissionError,
    )


def _validate_manager_access():
    if can_manage_treasury():
        return
    frappe.throw(
        _("Only Treasury Manager, Accounts Manager, or System Manager can execute or manage Treasury operations."),
        frappe.PermissionError,
    )


def _validate_internal_transfer_action_access(transfer_action):
    action = str(transfer_action or "Create Draft").strip()
    if action == "Submit Now" and not can_emergency_submit_treasury():
        frappe.throw(
            _("Immediate submission is reserved for System Manager emergency override. Save the transfer as a Draft for separate approval."),
            frappe.PermissionError,
        )


def _validate_access():
    if can_view_treasury():
        return
    frappe.throw(
        _("You are not permitted to view Treasury Management."),
        frappe.PermissionError,
    )
