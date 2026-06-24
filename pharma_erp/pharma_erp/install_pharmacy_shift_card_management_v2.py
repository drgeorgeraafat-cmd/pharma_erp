import copy
import json
import shutil
from pathlib import Path

import frappe

from pharma_erp.pharma_erp import install_shift_payment_clearing_foundation as foundation

COMPANY = "Cure"
APP = "pharma_erp"


def F(label, fieldname, fieldtype, **kwargs):
    row = {"label": label, "fieldname": fieldname, "fieldtype": fieldtype}
    row.update(kwargs)
    return row


DOCTYPE_SPECS = {
    "Card POS Terminal": {
        "module": "Pharma Erp", "custom": 1, "istable": 0, "is_submittable": 0,
        "autoname": "field:terminal_code", "title_field": "terminal_name",
        "search_fields": "terminal_code,terminal_name,bank_label,terminal_id,merchant_id",
        "fields": [
            F("Terminal", "terminal_section", "Section Break"),
            F("Terminal Name", "terminal_name", "Data", reqd=1, in_list_view=1),
            F("Terminal Code", "terminal_code", "Data", reqd=1, unique=1, in_list_view=1),
            F("Company", "company", "Link", options="Company", reqd=1, default="Cure"),
            F("Mode of Payment", "mode_of_payment", "Link", options="Mode of Payment", reqd=1, default="Credit Card"),
            F("", "column_break_1", "Column Break"),
            F("Bank", "bank_label", "Data", reqd=1, in_list_view=1),
            F("Merchant ID", "merchant_id", "Data"),
            F("Terminal ID", "terminal_id", "Data"),
            F("Enabled", "enabled", "Check", default="1", in_list_view=1),
            F("Accounts", "accounts_section", "Section Break"),
            F("Card Clearing Account", "clearing_account", "Link", options="Account", reqd=1, in_list_view=1),
            F("Destination Bank Account", "destination_bank_account", "Link", options="Account", reqd=1, in_list_view=1),
            F("", "column_break_2", "Column Break"),
            F("Fee Account", "fee_account", "Link", options="Account"),
            F("Notes", "notes", "Small Text"),
        ],
    },
    "Card Settlement Batch Item": {
        "module": "Pharma Erp", "custom": 1, "istable": 1, "is_submittable": 0,
        "fields": [
            F("Payment Row", "payment_row_name", "Data", read_only=1),
            F("Sales Invoice", "sales_invoice", "Link", options="Sales Invoice", read_only=1, in_list_view=1),
            F("Customer", "customer", "Link", options="Customer", read_only=1),
            F("Customer Name", "customer_name", "Data", read_only=1),
            F("Transaction Time", "transaction_time", "Datetime", read_only=1),
            F("Transaction Type", "transaction_type", "Select", options="Sale\nRefund", read_only=1),
            F("Reference Number", "reference_no", "Data", read_only=1),
            F("Amount", "amount", "Currency", read_only=1, in_list_view=1),
            F("POS Terminal", "pos_terminal", "Link", options="Card POS Terminal", read_only=1),
        ],
    },
    "Card Settlement Batch": {
        "module": "Pharma Erp", "custom": 1, "istable": 0, "is_submittable": 1,
        "autoname": "naming_series:", "title_field": "batch_number",
        "search_fields": "shift_reference,pos_terminal,batch_number,status,bank_settlement",
        "fields": [
            F("Series", "naming_series", "Select", options="CSB-.YYYY.-.#####", default="CSB-.YYYY.-.#####", reqd=1, hidden=1),
            F("General", "general_section", "Section Break"),
            F("Shift Reference", "shift_reference", "Link", options="Pharmacy Shift Closing", reqd=1, in_list_view=1),
            F("Company", "company", "Link", options="Company", reqd=1, default="Cure"),
            F("POS Terminal", "pos_terminal", "Link", options="Card POS Terminal", reqd=1, in_list_view=1),
            F("Bank", "bank_label", "Data", read_only=1, in_list_view=1),
            F("", "column_break_1", "Column Break"),
            F("Batch Number", "batch_number", "Data", in_list_view=1),
            F("From Time", "from_time", "Datetime", read_only=1),
            F("To Time", "to_time", "Datetime", read_only=1),
            F("Close Time", "close_time", "Datetime", reqd=1, default="Now"),
            F("Close Report", "closing_report", "Attach"),
            F("Accounts", "accounts_section", "Section Break"),
            F("Clearing Account", "clearing_account", "Link", options="Account", read_only=1),
            F("Destination Bank Account", "destination_bank_account", "Link", options="Account", read_only=1),
            F("Fee Account", "fee_account", "Link", options="Account", read_only=1),
            F("Totals", "totals_section", "Section Break"),
            F("Transaction Count", "transaction_count", "Int", read_only=1),
            F("System Total", "system_total", "Currency", read_only=1, in_list_view=1),
            F("Machine Total", "machine_total", "Currency", reqd=1, in_list_view=1),
            F("Difference", "difference", "Currency", read_only=1, in_list_view=1),
            F("", "column_break_2", "Column Break"),
            F("Settled Amount", "settled_amount", "Currency", read_only=1, default="0"),
            F("Outstanding Amount", "outstanding_amount", "Currency", read_only=1),
            F("Status", "status", "Select", options="Draft\nAwaiting Bank Settlement\nPartially Settled\nSettled\nDisputed\nCancelled", default="Draft", read_only=1, in_list_view=1),
            F("Difference Reason", "difference_reason", "Small Text"),
            F("Review", "review_section", "Section Break"),
            F("Reviewed By", "reviewed_by", "Link", options="User", read_only=1),
            F("Reviewed At", "reviewed_at", "Datetime", read_only=1),
            F("Bank Settlement", "bank_settlement", "Link", options="Card Bank Settlement", read_only=1, allow_on_submit=1),
            F("Items", "items_section", "Section Break"),
            F("Items", "items", "Table", options="Card Settlement Batch Item"),
            F("Amended From", "amended_from", "Link", options="Card Settlement Batch", read_only=1, hidden=1, no_copy=1),
        ],
    },
    "Card Bank Settlement Allocation": {
        "module": "Pharma Erp", "custom": 1, "istable": 1, "is_submittable": 0,
        "fields": [
            F("Card Settlement Batch", "card_settlement_batch", "Link", options="Card Settlement Batch", reqd=1, in_list_view=1),
            F("POS Terminal", "pos_terminal", "Link", options="Card POS Terminal", read_only=1),
            F("Batch Number", "batch_number", "Data", read_only=1),
            F("Available Amount", "available_amount", "Currency", read_only=1),
            F("Allocated Amount", "allocated_amount", "Currency", reqd=1, in_list_view=1),
        ],
    },
    "Card Bank Settlement": {
        "module": "Pharma Erp", "custom": 1, "istable": 0, "is_submittable": 1,
        "autoname": "naming_series:", "title_field": "bank_reference",
        "search_fields": "destination_bank_account,clearing_account,bank_reference,status,journal_entry",
        "fields": [
            F("Series", "naming_series", "Select", options="CBS-.YYYY.-.#####", default="CBS-.YYYY.-.#####", reqd=1, hidden=1),
            F("General", "general_section", "Section Break"),
            F("Company", "company", "Link", options="Company", reqd=1, default="Cure"),
            F("Settlement Date", "settlement_date", "Date", reqd=1, default="Today"),
            F("Bank Reference", "bank_reference", "Data", reqd=1, in_list_view=1),
            F("Statement Attachment", "statement_attachment", "Attach"),
            F("", "column_break_1", "Column Break"),
            F("Status", "status", "Select", options="Draft\nSubmitted\nCancelled", default="Draft", read_only=1, in_list_view=1),
            F("Destination Bank Account", "destination_bank_account", "Link", options="Account", reqd=1, in_list_view=1),
            F("Clearing Account", "clearing_account", "Link", options="Account", reqd=1, in_list_view=1),
            F("Fee Account", "fee_account", "Link", options="Account"),
            F("Amounts", "amounts_section", "Section Break"),
            F("Gross Amount", "gross_amount", "Currency", read_only=1, in_list_view=1),
            F("Fee Amount", "fee_amount", "Currency", default="0"),
            F("Net Amount", "net_amount", "Currency", read_only=1, in_list_view=1),
            F("Journal Entry", "journal_entry", "Link", options="Journal Entry", read_only=1, allow_on_submit=1),
            F("Allocations", "allocations_section", "Section Break"),
            F("Allocations", "allocations", "Table", options="Card Bank Settlement Allocation"),
            F("Notes", "notes", "Small Text"),
            F("Amended From", "amended_from", "Link", options="Card Bank Settlement", read_only=1, hidden=1, no_copy=1),
        ],
    },
}


SERVER_SCRIPTS = {
    "Card POS Terminal - Validate": ("Card POS Terminal", "Before Save", '''
if doc.mode_of_payment != "Credit Card":
    frappe.throw("Card POS Terminal must use Credit Card Mode of Payment.")
for account in [doc.clearing_account, doc.destination_bank_account]:
    row = frappe.db.get_value("Account", account, ["company", "is_group", "disabled"], as_dict=True)
    if not row or row.company != doc.company or row.is_group or row.disabled:
        frappe.throw("Invalid account: " + account)
'''),
    "Card Settlement Batch - Before Submit": ("Card Settlement Batch", "Before Submit", '''
if not doc.items:
    frappe.throw("The card batch has no transactions.")
system_total = 0
for row in doc.items:
    system_total += frappe.utils.flt(row.amount)
doc.transaction_count = len(doc.items)
doc.system_total = frappe.utils.flt(system_total)
doc.difference = frappe.utils.flt(doc.machine_total) - frappe.utils.flt(doc.system_total)
doc.outstanding_amount = frappe.utils.flt(doc.system_total) - frappe.utils.flt(doc.settled_amount)
if abs(frappe.utils.flt(doc.difference)) > 0.01:
    frappe.throw("Machine Total must equal System Total before submission.")
duplicates = frappe.db.sql("""
    SELECT item.payment_row_name
    FROM `tabCard Settlement Batch Item` item
    INNER JOIN `tabCard Settlement Batch` batch ON batch.name = item.parent
    WHERE item.payment_row_name IN %(row_names)s
      AND batch.name != %(batch_name)s
      AND batch.docstatus != 2
    LIMIT 1
""", {"row_names": tuple([row.payment_row_name for row in doc.items]), "batch_name": doc.name})
if duplicates:
    frappe.throw("A card transaction is already included in another batch.")
doc.status = "Awaiting Bank Settlement"
doc.reviewed_by = frappe.session.user
doc.reviewed_at = frappe.utils.now()
'''),
    "Card Settlement Batch - Before Cancel": ("Card Settlement Batch", "Before Cancel", '''
if frappe.utils.flt(doc.settled_amount) > 0:
    frappe.throw("A settled or partially settled card batch cannot be cancelled.")
'''),
    "Card Bank Settlement - Before Submit": ("Card Bank Settlement", "Before Submit", '''
if not doc.allocations:
    frappe.throw("Add at least one Card Settlement Batch.")
gross = 0
for row in doc.allocations:
    batch = frappe.get_doc("Card Settlement Batch", row.card_settlement_batch)
    if batch.docstatus != 1:
        frappe.throw("Card batch must be submitted: " + batch.name)
    if batch.clearing_account != doc.clearing_account or batch.destination_bank_account != doc.destination_bank_account:
        frappe.throw("All batches must use the selected clearing and bank accounts.")
    available = frappe.utils.flt(batch.outstanding_amount)
    allocated = frappe.utils.flt(row.allocated_amount)
    if allocated <= 0 or allocated - available > 0.01:
        frappe.throw("Invalid allocated amount for " + batch.name)
    row.pos_terminal = batch.pos_terminal
    row.batch_number = batch.batch_number
    row.available_amount = available
    gross += allocated
doc.gross_amount = frappe.utils.flt(gross)
doc.net_amount = frappe.utils.flt(doc.gross_amount) - frappe.utils.flt(doc.fee_amount)
if doc.net_amount < 0:
    frappe.throw("Fee Amount cannot exceed Gross Amount.")
if frappe.utils.flt(doc.fee_amount) > 0 and not doc.fee_account:
    frappe.throw("Fee Account is required.")
doc.status = "Submitted"
'''),
    "Card Bank Settlement - After Submit": ("Card Bank Settlement", "After Submit", '''
journal = frappe.new_doc("Journal Entry")
journal.voucher_type = "Journal Entry"
journal.company = doc.company
journal.posting_date = doc.settlement_date
journal.user_remark = "Card bank settlement " + doc.name + " / " + doc.bank_reference
if frappe.utils.flt(doc.net_amount) > 0:
    journal.append("accounts", {"account": doc.destination_bank_account, "debit_in_account_currency": frappe.utils.flt(doc.net_amount), "credit_in_account_currency": 0})
if frappe.utils.flt(doc.fee_amount) > 0:
    journal.append("accounts", {"account": doc.fee_account, "debit_in_account_currency": frappe.utils.flt(doc.fee_amount), "credit_in_account_currency": 0})
journal.append("accounts", {"account": doc.clearing_account, "debit_in_account_currency": 0, "credit_in_account_currency": frappe.utils.flt(doc.gross_amount)})
journal.flags.ignore_permissions = True
journal.insert(ignore_permissions=True)
journal.flags.ignore_permissions = True
journal.submit()
frappe.db.set_value("Card Bank Settlement", doc.name, {"journal_entry": journal.name, "status": "Submitted"}, update_modified=False)
for row in doc.allocations:
    batch = frappe.get_doc("Card Settlement Batch", row.card_settlement_batch)
    settled = frappe.utils.flt(batch.settled_amount) + frappe.utils.flt(row.allocated_amount)
    outstanding = frappe.utils.flt(batch.system_total) - settled
    status = "Settled" if outstanding <= 0.01 else "Partially Settled"
    frappe.db.set_value("Card Settlement Batch", batch.name, {"settled_amount": settled, "outstanding_amount": max(outstanding, 0), "status": status, "bank_settlement": doc.name if status == "Settled" else ""}, update_modified=False)
'''),
    "Card Bank Settlement - Before Cancel": ("Card Bank Settlement", "Before Cancel", '''
if doc.journal_entry:
    journal = frappe.get_doc("Journal Entry", doc.journal_entry)
    if journal.docstatus == 1:
        journal.flags.ignore_permissions = True
        journal.cancel()
'''),
    "Card Bank Settlement - After Cancel": ("Card Bank Settlement", "After Cancel", '''
for row in doc.allocations:
    batch = frappe.get_doc("Card Settlement Batch", row.card_settlement_batch)
    settled = max(frappe.utils.flt(batch.settled_amount) - frappe.utils.flt(row.allocated_amount), 0)
    outstanding = frappe.utils.flt(batch.system_total) - settled
    status = "Awaiting Bank Settlement" if settled <= 0.01 else "Partially Settled"
    frappe.db.set_value("Card Settlement Batch", batch.name, {"settled_amount": settled, "outstanding_amount": max(outstanding, 0), "status": status, "bank_settlement": ""}, update_modified=False)
'''),
    "Sales Invoice - Card Terminal Account": ("Sales Invoice", "Before Save", '''
if doc.get("payments"):
    enabled = frappe.get_all("Card POS Terminal", filters={"company": doc.company, "enabled": 1}, pluck="name")
    for row in doc.payments:
        if row.mode_of_payment != "Credit Card":
            continue
        terminal = row.get("custom_card_pos_terminal")
        if not terminal and len(enabled) == 1:
            terminal = enabled[0]
            row.custom_card_pos_terminal = terminal
        if not terminal:
            frappe.throw("Select Card POS Terminal for each Credit Card payment.")
        terminal_doc = frappe.get_doc("Card POS Terminal", terminal)
        if terminal_doc.company != doc.company or not terminal_doc.enabled:
            frappe.throw("Invalid or disabled Card POS Terminal.")
        row.account = terminal_doc.clearing_account
'''),
    "Shift Cash Movement - After Submit": ("Shift Cash Movement", "After Submit", '''
amount = frappe.utils.flt(doc.amount)

journal = frappe.new_doc("Journal Entry")
journal.voucher_type = "Journal Entry"
journal.company = doc.company
journal.posting_date = frappe.utils.getdate(doc.movement_date)
journal.user_remark = "Shift cash movement " + doc.name + " - " + doc.description

debit_row = {
    "account": doc.target_account,
    "debit_in_account_currency": amount,
    "credit_in_account_currency": 0,
}
credit_row = {
    "account": doc.source_account,
    "debit_in_account_currency": 0,
    "credit_in_account_currency": amount,
}

if doc.movement_type == "Employee Advance" and doc.employee:
    debit_row["party_type"] = "Employee"
    debit_row["party"] = doc.employee

if doc.movement_type == "Supplier Payment" and doc.supplier:
    debit_row["party_type"] = "Supplier"
    debit_row["party"] = doc.supplier

    if doc.get("purchase_invoice"):
        debit_row["reference_type"] = "Purchase Invoice"
        debit_row["reference_name"] = doc.purchase_invoice

journal.append("accounts", debit_row)
journal.append("accounts", credit_row)
journal.flags.ignore_permissions = True
journal.insert(ignore_permissions=True)
journal.flags.ignore_permissions = True
journal.submit()

frappe.db.set_value(
    "Shift Cash Movement",
    doc.name,
    {
        "journal_entry": journal.name,
        "status": "Posted",
        "posted_by": frappe.session.user,
        "posted_at": frappe.utils.now(),
    },
    update_modified=False,
)
'''),
    "Cancel Delivery Handover Journal": ("Delivery Handover", "Before Cancel", '''
if doc.journal_entry:
    journal = frappe.get_doc("Journal Entry", doc.journal_entry)
    if journal.docstatus == 1:
        journal.flags.ignore_permissions = True
        journal.cancel()
'''),
    "Payment Entry - Card Terminal Account": ("Payment Entry", "Before Save", '''
if doc.mode_of_payment == "Credit Card":
    enabled = frappe.get_all(
        "Card POS Terminal",
        filters={
            "company": doc.company,
            "enabled": 1,
        },
        pluck="name",
    )

    terminal = doc.get(
        "custom_card_pos_terminal"
    )

    if (
        not terminal
        and frappe.get_meta(
            "Sales Invoice"
        ).has_field(
            "custom_delivery_card_pos_terminal"
        )
    ):
        referenced_terminals = []

        for reference in doc.get(
            "references"
        ) or []:
            if (
                reference.reference_doctype
                != "Sales Invoice"
            ):
                continue

            invoice_terminal = (
                frappe.db.get_value(
                    "Sales Invoice",
                    reference.reference_name,
                    "custom_delivery_card_pos_terminal",
                )
            )

            if (
                invoice_terminal
                and invoice_terminal
                not in referenced_terminals
            ):
                referenced_terminals.append(
                    invoice_terminal
                )

        if len(referenced_terminals) > 1:
            frappe.throw(
                "The referenced delivery invoices use different card terminals."
            )

        if referenced_terminals:
            terminal = referenced_terminals[0]
            doc.custom_card_pos_terminal = (
                terminal
            )

    if not terminal and len(enabled) == 1:
        terminal = enabled[0]
        doc.custom_card_pos_terminal = (
            terminal
        )

    if not terminal:
        frappe.throw(
            "Select Card POS Terminal."
        )

    terminal_doc = frappe.get_doc(
        "Card POS Terminal",
        terminal,
    )

    if (
        terminal_doc.company != doc.company
        or not terminal_doc.enabled
    ):
        frappe.throw(
            "Invalid or disabled Card POS Terminal."
        )

    if doc.payment_type == "Receive":
        doc.paid_to = (
            terminal_doc.clearing_account
        )
    elif doc.payment_type == "Pay":
        doc.paid_from = (
            terminal_doc.clearing_account
        )
'''),
}


SERVER_SCRIPTS.update(
    {
        "Shift Payment Reconciliation - Before Submit": (
            "Shift Payment Reconciliation",
            "Before Submit",
            """
setup = frappe.get_doc(
    "Payment Method Clearing Setup",
    doc.setup_reference,
)

if not setup.enabled:
    frappe.throw(
        "The selected clearing setup is disabled."
    )

doc.clearing_account = setup.clearing_account
doc.destination_account = (
    setup.destination_account
)
doc.settlement_policy = (
    setup.settlement_policy
)
doc.fee_account = setup.fee_account

doc.difference = (
    frappe.utils.flt(doc.reviewed_amount)
    - frappe.utils.flt(doc.expected_amount)
)
doc.net_transfer_amount = (
    frappe.utils.flt(doc.reviewed_amount)
    - frappe.utils.flt(doc.fee_amount)
)

if frappe.utils.flt(doc.reviewed_amount) <= 0:
    frappe.throw(
        "Reviewed Amount must be greater than zero."
    )

if abs(frappe.utils.flt(doc.difference)) > 0.01:
    frappe.throw(
        "Reviewed Amount must equal Expected Amount."
    )

if frappe.utils.flt(doc.net_transfer_amount) < 0:
    frappe.throw(
        "Fee Amount cannot exceed Reviewed Amount."
    )

if (
    frappe.utils.flt(doc.fee_amount) > 0
    and not doc.fee_account
):
    frappe.throw(
        "Fee Account is required."
    )

doc.status = "Reviewed"
doc.reviewed_by = frappe.session.user
doc.reviewed_at = frappe.utils.now()
""",
        ),
        "Shift Payment Reconciliation - After Submit": (
            "Shift Payment Reconciliation",
            "After Submit",
            """
# Review confirmation only. The Journal Entry is created when the
# Pharmacy Shift is finally approved and closed.
frappe.db.set_value(
    "Shift Payment Reconciliation",
    doc.name,
    {
        "status": "Reviewed",
        "journal_entry": "",
    },
    update_modified=False,
)
""",
        ),
        "Shift Payment Reconciliation - Before Cancel": (
            "Shift Payment Reconciliation",
            "Before Cancel",
            """
if doc.journal_entry:
    journal = frappe.get_doc(
        "Journal Entry",
        doc.journal_entry,
    )

    if journal.docstatus == 1:
        journal.flags.ignore_permissions = True
        journal.cancel()
""",
        ),
        "Shift Cash Movement - Before Submit": (
            "Shift Cash Movement",
            "Before Submit",
            """
amount = frappe.utils.flt(doc.amount)

if amount <= 0:
    frappe.throw(
        "Amount must be greater than zero."
    )

if not doc.source_account or not doc.target_account:
    frappe.throw(
        "Source Account and Target Account are required."
    )

if doc.source_account == doc.target_account:
    frappe.throw(
        "Source and Target accounts cannot be the same."
    )
""",
        ),
        "Shift Cash Movement - Before Cancel": (
            "Shift Cash Movement",
            "Before Cancel",
            """
if doc.journal_entry:
    journal = frappe.get_doc(
        "Journal Entry",
        doc.journal_entry,
    )

    if journal.docstatus == 1:
        journal.flags.ignore_permissions = True
        journal.cancel()
""",
        ),
    }
)



SERVER_SCRIPTS.update(
    {
        "Payment Entry - Pharmacy Shift Reference": (
            "Payment Entry",
            "Before Save",
            """
if (
    frappe.get_meta("Payment Entry").has_field("custom_pharmacy_shift")
    and not doc.get("custom_pharmacy_shift")
):
    referenced_shifts = []

    if frappe.get_meta("Sales Invoice").has_field("custom_pharmacy_shift"):
        for reference in doc.get("references") or []:
            if reference.reference_doctype != "Sales Invoice":
                continue

            shift_reference = frappe.db.get_value(
                "Sales Invoice",
                reference.reference_name,
                "custom_pharmacy_shift",
            )

            if (
                shift_reference
                and shift_reference not in referenced_shifts
            ):
                referenced_shifts.append(shift_reference)

    if len(referenced_shifts) > 1:
        frappe.throw(
            "The referenced invoices belong to different pharmacy shifts."
        )

    if referenced_shifts:
        doc.custom_pharmacy_shift = referenced_shifts[0]
""",
        ),
    }
)


CLIENT_SCRIPTS = {
    "Card Settlement Batch - Client": ("Card Settlement Batch", '''
frappe.ui.form.on("Card Settlement Batch", {
    refresh(frm) {
        if (frm.doc.docstatus === 0 && !frm.is_new()) {
            frm.add_custom_button(__("Refresh Transactions"), async () => {
                await frappe.call({method: "pharma_erp.pharma_erp.payment_card_management.refresh_card_batch", args: {batch_name: frm.doc.name}, freeze: true});
                await frm.reload_doc();
            });
        }
    },
    machine_total(frm) {
        frm.set_value("difference", flt(frm.doc.machine_total) - flt(frm.doc.system_total));
    },
});
'''),
    "Card Bank Settlement - Client": ("Card Bank Settlement", '''
frappe.ui.form.on("Card Bank Settlement", {
    async refresh(frm) {
        if (frm.doc.docstatus !== 0) return;

        await set_card_bank_defaults(frm);

        frm.add_custom_button(__("Load Awaiting Batches"), async () => {
            await set_card_bank_defaults(frm);

            if (!frm.doc.clearing_account || !frm.doc.destination_bank_account) {
                frappe.msgprint(__("Select Destination Bank Account first."));
                return;
            }

            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.payment_card_management.get_awaiting_card_batches",
                args: {
                    clearing_account: frm.doc.clearing_account,
                    destination_bank_account: frm.doc.destination_bank_account,
                },
                freeze: true,
            });

            frm.clear_table("allocations");

            (response.message || []).forEach((batch) => {
                const row = frm.add_child("allocations");
                row.card_settlement_batch = batch.name;
                row.pos_terminal = batch.pos_terminal;
                row.batch_number = batch.batch_number;
                row.available_amount = batch.outstanding_amount;
                row.allocated_amount = batch.outstanding_amount;

                if (!frm.doc.fee_account && batch.fee_account) {
                    frm.set_value("fee_account", batch.fee_account);
                }
            });

            frm.refresh_field("allocations");
            calculate_card_bank_totals(frm);
        });
    },

    destination_bank_account(frm) {
        set_card_bank_defaults(frm);
    },

    clearing_account(frm) {
        set_card_bank_defaults(frm);
    },

    fee_amount(frm) {
        calculate_card_bank_totals(frm);
    },
});

frappe.ui.form.on("Card Bank Settlement Allocation", {
    allocated_amount(frm) { calculate_card_bank_totals(frm); },
    allocations_remove(frm) { calculate_card_bank_totals(frm); },
});

async function set_card_bank_defaults(frm) {
    const response = await frappe.call({
        method: "pharma_erp.pharma_erp.payment_card_management.get_card_bank_defaults",
        args: {
            destination_bank_account: frm.doc.destination_bank_account || "",
            clearing_account: frm.doc.clearing_account || "",
        },
    });

    const values = response.message || {};

    if (!frm.doc.destination_bank_account && values.destination_bank_account) {
        await frm.set_value("destination_bank_account", values.destination_bank_account);
    }

    if (!frm.doc.clearing_account && values.clearing_account) {
        await frm.set_value("clearing_account", values.clearing_account);
    }

    if (!frm.doc.fee_account && values.fee_account) {
        await frm.set_value("fee_account", values.fee_account);
    }
}

function calculate_card_bank_totals(frm) {
    let gross = 0;
    (frm.doc.allocations || []).forEach((row) => {
        gross += flt(row.allocated_amount);
    });
    frm.set_value("gross_amount", gross);
    frm.set_value("net_amount", gross - flt(frm.doc.fee_amount));
}
'''),
    "Sales Invoice - Card Terminal Client": ("Sales Invoice", '''
frappe.ui.form.on("Sales Invoice Payment", {
    custom_card_pos_terminal(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.custom_card_pos_terminal) return;
        frappe.db.get_value("Card POS Terminal", row.custom_card_pos_terminal, "clearing_account").then(r => {
            frappe.model.set_value(cdt, cdn, "account", r.message.clearing_account);
        });
    },
});
'''),
    "Payment Entry - Card Terminal Client": ("Payment Entry", '''
frappe.ui.form.on("Payment Entry", {
    custom_card_pos_terminal(frm) {
        if (!frm.doc.custom_card_pos_terminal) return;
        frappe.db.get_value("Card POS Terminal", frm.doc.custom_card_pos_terminal, "clearing_account").then(r => {
            if (frm.doc.payment_type === "Receive") frm.set_value("paid_to", r.message.clearing_account);
            if (frm.doc.payment_type === "Pay") frm.set_value("paid_from", r.message.clearing_account);
        });
    },
});
'''),
}


def _ensure_permission(doc):
    for row in doc.permissions:
        if row.role == "System Manager":
            row.read = row.write = row.create = 1
            if doc.is_submittable:
                row.submit = row.cancel = row.amend = 1
            return
    values = {"role": "System Manager", "read": 1, "write": 1, "create": 1}
    if doc.is_submittable:
        values.update({"submit": 1, "cancel": 1, "amend": 1})
    doc.append("permissions", values)


def _upsert_doctype(name, spec, remove_fields=None):
    doc = frappe.get_doc("DocType", name) if frappe.db.exists("DocType", name) else frappe.new_doc("DocType")
    if doc.is_new():
        doc.name = name
    for key in ["module", "custom", "istable", "is_submittable", "autoname", "title_field", "search_fields"]:
        if key in spec:
            doc.set(key, spec[key])
    remove_fields = set(remove_fields or [])
    seen = set()

    for row in list(doc.fields):
        if row.fieldname in remove_fields:
            doc.remove(row)
            continue

        if row.fieldname and row.fieldname in seen:
            doc.remove(row)
        elif row.fieldname:
            seen.add(row.fieldname)
    existing = {row.fieldname: row for row in doc.fields if row.fieldname}
    for values in spec["fields"]:
        fieldname = values.get("fieldname")
        if fieldname and fieldname in existing:
            row = existing[fieldname]
            for key, value in values.items():
                row.set(key, value)
        else:
            doc.append("fields", values)
    if not spec.get("istable"):
        _ensure_permission(doc)
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True) if doc.is_new() else doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.db.updatedb(name)
    frappe.db.commit()



def _install_card_doctypes():
    """
    Install the card DocTypes in dependency order.

    Card Settlement Batch links to Card Bank Settlement, while
    Card Bank Settlement uses an allocation child table that links
    back to Card Settlement Batch. The first pass creates the batch
    without the circular bank_settlement Link. After the bank
    settlement DocType exists, the full batch schema is applied.
    """
    _upsert_doctype(
        "Card POS Terminal",
        DOCTYPE_SPECS["Card POS Terminal"],
    )

    _upsert_doctype(
        "Card Settlement Batch Item",
        DOCTYPE_SPECS["Card Settlement Batch Item"],
    )

    batch_base = copy.deepcopy(
        DOCTYPE_SPECS["Card Settlement Batch"]
    )
    batch_base["fields"] = [
        row
        for row in batch_base["fields"]
        if row.get("fieldname") != "bank_settlement"
    ]
    batch_base["search_fields"] = (
        "shift_reference,pos_terminal,batch_number,status"
    )

    _upsert_doctype(
        "Card Settlement Batch",
        batch_base,
        remove_fields={"bank_settlement"},
    )

    _upsert_doctype(
        "Card Bank Settlement Allocation",
        DOCTYPE_SPECS["Card Bank Settlement Allocation"],
    )

    _upsert_doctype(
        "Card Bank Settlement",
        DOCTYPE_SPECS["Card Bank Settlement"],
    )

    # Second pass: both sides of the circular relationship now exist.
    _upsert_doctype(
        "Card Settlement Batch",
        DOCTYPE_SPECS["Card Settlement Batch"],
    )


def _custom_field(dt, fieldname, values):
    """
    Create or update a Custom Field safely.

    Some fields, such as cash_account on Pharmacy Shift Closing, may
    already exist directly inside the custom DocType rather than as a
    separate Custom Field record. In that case the installer must not
    try to create a duplicate Custom Field.
    """
    custom_field_name = frappe.db.get_value(
        "Custom Field",
        {
            "dt": dt,
            "fieldname": fieldname,
        },
        "name",
    )

    if custom_field_name:
        doc = frappe.get_doc(
            "Custom Field",
            custom_field_name,
        )

        for key, value in values.items():
            doc.set(key, value)

        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        return {
            "action": "updated_custom_field",
            "name": doc.name,
        }

    # The field may already be part of the DocType itself. This is the
    # case for fields previously installed directly on custom DocTypes.
    if frappe.get_meta(dt).has_field(fieldname):
        return {
            "action": "existing_doctype_field",
            "name": dt + "." + fieldname,
        }

    doc = frappe.new_doc("Custom Field")
    doc.dt = dt
    doc.fieldname = fieldname

    for key, value in values.items():
        doc.set(key, value)

    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)

    return {
        "action": "created_custom_field",
        "name": doc.name,
    }


def _account(account_name, parent, root_type="Asset", report_type="Balance Sheet", is_group=0):
    existing = frappe.db.get_value("Account", {"account_name": account_name, "company": COMPANY}, "name")
    if existing:
        return existing
    doc = frappe.new_doc("Account")
    doc.account_name = account_name
    doc.company = COMPANY
    doc.parent_account = parent
    doc.root_type = root_type
    doc.report_type = report_type
    doc.is_group = is_group
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name


def _ensure_card_accounts():
    parent = next((name for name in ["Current Assets - C", "Bank Accounts - C", "Cash In Hand - C"] if frappe.db.exists("Account", name)), None)
    if not parent:
        frappe.throw("No Asset parent account was found.")
    group = _account("Payment Clearing Accounts", parent, is_group=1)
    generic = _account("Card Clearing", group)
    qnb = _account("QNB Card Clearing", group)

    expense_parent = next((name for name in ["Indirect Expenses - C", "Expenses - C", "Direct Expenses - C"] if frappe.db.exists("Account", name)), None)
    income_parent = next((name for name in ["Indirect Income - C", "Income - C", "Direct Income - C"] if frappe.db.exists("Account", name)), None)

    if not expense_parent:
        rows = frappe.get_all(
            "Account",
            filters={
                "company": COMPANY,
                "root_type": "Expense",
                "is_group": 1,
                "disabled": 0,
            },
            fields=["name"],
            order_by="lft asc",
            limit_page_length=1,
        )
        expense_parent = rows[0].name if rows else None

    if not income_parent:
        rows = frappe.get_all(
            "Account",
            filters={
                "company": COMPANY,
                "root_type": "Income",
                "is_group": 1,
                "disabled": 0,
            },
            fields=["name"],
            order_by="lft asc",
            limit_page_length=1,
        )
        income_parent = rows[0].name if rows else None

    if not expense_parent or not income_parent:
        frappe.throw("Expense and Income parent accounts are required for shift difference accounts.")

    fee = _account("Payment Processing Fees", expense_parent, "Expense", "Profit and Loss")
    shortage_expense = _account("Cash Shortage Expense", expense_parent, "Expense", "Profit and Loss")
    overage_income = _account("Cash Overage Income", income_parent, "Income", "Profit and Loss")

    frappe.db.commit()
    return {
        "group": group,
        "generic": generic,
        "qnb": qnb,
        "fee": fee,
        "cash_shortage_expense": shortage_expense,
        "cash_overage_income": overage_income,
    }


def _default_terminal(accounts):
    if frappe.db.exists("Card POS Terminal", "QNB-01"):
        return "QNB-01"
    doc = frappe.new_doc("Card POS Terminal")
    doc.terminal_name = "QNB Terminal 01"
    doc.terminal_code = "QNB-01"
    doc.company = COMPANY
    doc.mode_of_payment = "Credit Card"
    doc.bank_label = "QNB"
    doc.clearing_account = accounts["qnb"]
    doc.destination_bank_account = "QNB - C"
    doc.fee_account = accounts["fee"]
    doc.enabled = 1
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    return doc.name


def _server_script(name, values):
    dt, event, script = values
    doc = frappe.get_doc("Server Script", name) if frappe.db.exists("Server Script", name) else frappe.new_doc("Server Script")
    if doc.is_new():
        doc.name = name
    doc.script_type = "DocType Event"
    doc.reference_doctype = dt
    doc.doctype_event = event
    doc.script = script.strip()
    doc.disabled = 0
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True) if doc.is_new() else doc.save(ignore_permissions=True)


def _client_script(name, values):
    dt, script = values
    doc = frappe.get_doc("Client Script", name) if frappe.db.exists("Client Script", name) else frappe.new_doc("Client Script")
    if doc.is_new():
        doc.name = name
    doc.dt = dt
    doc.view = "Form"
    doc.script = script.strip()
    doc.enabled = 1
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True) if doc.is_new() else doc.save(ignore_permissions=True)


def _replace_once(text, old, new, label):
    if new in text:
        return text, False
    if old not in text:
        frappe.throw("POS patch marker not found: " + label)
    return text.replace(old, new, 1), True


def _patch_pos_api():
    bench = Path(frappe.get_app_path(APP)).parents[2]
    path = bench / "apps/pharma_erp/pharma_erp/pharma_erp/page/pharmacy_pos/api.py"
    text = path.read_text(encoding="utf-8")
    changed = False

    marker = "def _get_loyalty_context(customer, company):"
    helper = '''def _resolve_card_terminal(terminal, company):
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


'''
    if "def _resolve_card_terminal" not in text:
        if marker not in text:
            frappe.throw("POS API helper marker was not found.")
        text = text.replace(marker, helper + marker, 1)
        changed = True

    old = '''        result.append(
            {
                "name": row.name,
                "type": row.type,
                "account": account or "",
                "configured": 1 if account else 0,
            }
        )'''
    new = '''        terminals = []
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
        )'''
    text, did = _replace_once(text, old, new, "get_payment_modes")
    changed |= did

    old = '''        account = _mode_of_payment_account(mode, company)
        if not account:
            frappe.throw(
                _("No default account is configured for Mode of Payment {0} in company {1}.").format(
                    mode, company
                )
            )

        row = doc.append("payments", {})
        row.mode_of_payment = mode
        row.amount = amount
        row.account = account'''
    new = '''        card_terminal = None
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
            row.custom_card_pos_terminal = card_terminal.name'''
    text, did = _replace_once(text, old, new, "append payments")
    changed |= did

    old = '''    paid_to = _mode_of_payment_account(mode, company)
    if not paid_to:
        frappe.throw(
            _("No default account is configured for Mode of Payment {0} in company {1}.").format(
                mode, company
            )
        )'''
    new = '''    card_terminal = None
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
        )'''
    text, did = _replace_once(text, old, new, "customer advance account")
    changed |= did

    old = '''    if cost_center and _has_field("Payment Entry", "cost_center"):
        pe.cost_center = cost_center

    pe.insert(ignore_permissions=True)'''
    new = '''    if cost_center and _has_field("Payment Entry", "cost_center"):
        pe.cost_center = cost_center
    if card_terminal and _has_field("Payment Entry", "custom_card_pos_terminal"):
        pe.custom_card_pos_terminal = card_terminal.name

    pe.insert(ignore_permissions=True)'''
    text, did = _replace_once(text, old, new, "payment entry terminal")
    changed |= did

    old = '''            "reference_no": data.get("reference_no") or "",
            "remarks": data.get("remarks") or "",'''
    new = '''            "reference_no": data.get("reference_no") or "",
            "card_pos_terminal": data.get("card_pos_terminal") or "",
            "remarks": data.get("remarks") or "",'''
    text, did = _replace_once(text, old, new, "balance terminal payload")
    changed |= did

    if changed:
        backup = path.with_suffix(path.suffix + ".pre_card_v2.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(text, encoding="utf-8")
    return str(path), changed


def _patch_pos_js():
    bench = Path(frappe.get_app_path(APP)).parents[2]
    path = bench / "apps/pharma_erp/pharma_erp/public/js/pharmacy_pos/payment.js"
    text = path.read_text(encoding="utf-8")
    changed = False

    marker = '''    defaultCashMode() {'''
    helper = '''    cardTerminals() {
        const mode = (this.modes || []).find(row => row.name === "Credit Card");
        return mode?.terminals || [];
    },

    terminalOptions(selected = "") {
        return [
            `<option value="">${__("Select Terminal")}</option>`,
            ...this.cardTerminals().map(terminal => {
                const label = `${terminal.terminal_name} - ${terminal.bank_label || ""}`;
                return `<option value="${frappe.utils.escape_html(terminal.name)}" ${terminal.name === selected ? "selected" : ""}>${frappe.utils.escape_html(label)}</option>`;
            }),
        ].join("");
    },

'''
    if "terminalOptions(selected" not in text:
        if marker not in text:
            frappe.throw("POS payment helper marker not found.")
        text = text.replace(marker, helper + marker, 1)
        changed = True

    text, did = _replace_once(text, '<thead><tr><th>Mode</th><th>Amount</th><th>Reference</th><th></th></tr></thead>', '<thead><tr><th>Mode</th><th>Terminal</th><th>Amount</th><th>Reference</th><th></th></tr></thead>', "payment header")
    changed |= did

    old = '''    paymentRowHtml(row = {}) {
        return `<tr class="payment-row"><td><select class="payment-mode form-control">${this.modeOptions(row.mode_of_payment || "")}</select></td><td><input class="payment-amount form-control" type="number" min="0" step="0.01" value="${flt(row.amount || 0) || ""}"></td><td><input class="payment-reference form-control" type="text" value="${frappe.utils.escape_html(row.reference_no || "")}" placeholder="Optional reference"></td><td><button type="button" class="remove-payment-row btn btn-sm btn-danger">×</button></td></tr>`;
    },'''
    new = '''    paymentRowHtml(row = {}) {
        const cardSelected = (row.mode_of_payment || "") === "Credit Card";
        return `<tr class="payment-row"><td><select class="payment-mode form-control">${this.modeOptions(row.mode_of_payment || "")}</select></td><td><select class="payment-terminal form-control" ${cardSelected ? "" : "disabled"}>${this.terminalOptions(row.card_pos_terminal || "")}</select></td><td><input class="payment-amount form-control" type="number" min="0" step="0.01" value="${flt(row.amount || 0) || ""}"></td><td><input class="payment-reference form-control" type="text" value="${frappe.utils.escape_html(row.reference_no || "")}" placeholder="Optional reference"></td><td><button type="button" class="remove-payment-row btn btn-sm btn-danger">×</button></td></tr>`;
    },'''
    text, did = _replace_once(text, old, new, "payment row")
    changed |= did

    old = '''        const bindRow = row => {
            row.querySelectorAll("input, select").forEach(element => {'''
    new = '''        const bindRow = row => {
            const syncTerminal = () => {
                const mode = row.querySelector(".payment-mode")?.value || "";
                const terminal = row.querySelector(".payment-terminal");
                if (!terminal) return;
                terminal.disabled = mode !== "Credit Card";
                if (mode !== "Credit Card") terminal.value = "";
            };
            row.querySelector(".payment-mode")?.addEventListener("change", syncTerminal);
            syncTerminal();
            row.querySelectorAll("input, select").forEach(element => {'''
    text, did = _replace_once(text, old, new, "payment bind")
    changed |= did

    old = '''            mode_of_payment: row.querySelector(".payment-mode")?.value || "",
            amount: flt(row.querySelector(".payment-amount")?.value || 0),
            reference_no: row.querySelector(".payment-reference")?.value?.trim() || ""'''
    new = '''            mode_of_payment: row.querySelector(".payment-mode")?.value || "",
            card_pos_terminal: row.querySelector(".payment-terminal")?.value || "",
            amount: flt(row.querySelector(".payment-amount")?.value || 0),
            reference_no: row.querySelector(".payment-reference")?.value?.trim() || ""'''
    text, did = _replace_once(text, old, new, "payment collect")
    changed |= did

    old = ''')).filter(row => row.mode_of_payment && row.amount > 0);
        const points ='''
    new = ''')).filter(row => row.mode_of_payment && row.amount > 0);
        payments.forEach(row => {
            if (row.mode_of_payment === "Credit Card" && !row.card_pos_terminal) frappe.throw(__("Select Card POS Terminal for each Credit Card payment."));
        });
        const points ='''
    text, did = _replace_once(text, old, new, "terminal validation")
    changed |= did

    add_marker = '''                {
                    fieldtype: "Data",
                    fieldname: "reference_no",'''
    add_field = '''                {
                    fieldtype: "Select",
                    fieldname: "card_pos_terminal",
                    label: __("Card POS Terminal"),
                    options: this.cardTerminals().map(row => row.name).join("\\n"),
                    depends_on: 'eval:doc.mode_of_payment=="Credit Card"',
                    mandatory_depends_on: 'eval:doc.mode_of_payment=="Credit Card"'
                },
'''
    if 'fieldname: "card_pos_terminal"' not in text:
        if add_marker not in text:
            frappe.throw("Add Balance terminal marker not found.")
        text = text.replace(add_marker, add_field + add_marker, 1)
        changed = True

    old = '''                        mode_of_payment: values.mode_of_payment,
                        reference_no: values.reference_no || "",'''
    new = '''                        mode_of_payment: values.mode_of_payment,
                        card_pos_terminal: values.card_pos_terminal || "",
                        reference_no: values.reference_no || "",'''
    text, did = _replace_once(text, old, new, "balance terminal data")
    changed |= did

    if changed:
        backup = path.with_suffix(path.suffix + ".pre_card_v2.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(text, encoding="utf-8")
    return str(path), changed


def _update_shift_cash_movement_options():
    doc = frappe.get_doc(
        "DocType",
        "Shift Cash Movement",
    )

    options = "\n".join(
        [
            "Opening Float",
            "Till Refill",
            "Return Opening Float",
            "Cash Sales Deposit",
            "Unused Till Refill Return",
            "Other Cash Return",
            "Under Review Driver Cash Deposit",
            "Transfer to Main Safe",
            "Supplier Payment",
            "Operating Expense",
            "Employee Advance",
            "Other",
        ]
    )

    for row in doc.fields:
        if row.fieldname == "movement_type":
            row.options = options
            break
    else:
        frappe.throw(
            "movement_type field was not found in Shift Cash Movement."
        )

    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.db.updatedb(
        "Shift Cash Movement"
    )
    frappe.db.commit()


def install():
    foundation.install()
    _update_shift_cash_movement_options()
    _install_card_doctypes()

    _custom_field("Sales Invoice Payment", "custom_card_pos_terminal", {"label": "Card POS Terminal", "fieldtype": "Link", "options": "Card POS Terminal", "insert_after": "mode_of_payment", "in_list_view": 1, "depends_on": 'eval:doc.mode_of_payment=="Credit Card"'})
    _custom_field("Payment Entry", "custom_card_pos_terminal", {"label": "Card POS Terminal", "fieldtype": "Link", "options": "Card POS Terminal", "insert_after": "mode_of_payment", "depends_on": 'eval:doc.mode_of_payment=="Credit Card"'})
    _custom_field("Sales Invoice", "custom_delivery_card_pos_terminal", {"label": "Delivery Card POS Terminal", "fieldtype": "Link", "options": "Card POS Terminal", "insert_after": "custom_driver_collection_reference", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Sales Invoice", "custom_pharmacy_shift", {"label": "Pharmacy Shift", "fieldtype": "Link", "options": "Pharmacy Shift Closing", "insert_after": "custom_order_type", "read_only": 1, "allow_on_submit": 1, "in_standard_filter": 1})
    _custom_field("Payment Entry", "custom_pharmacy_shift", {"label": "Pharmacy Shift", "fieldtype": "Link", "options": "Pharmacy Shift Closing", "insert_after": "custom_card_pos_terminal", "read_only": 1, "allow_on_submit": 1, "in_standard_filter": 1})
    _custom_field("Pharmacy Shift Closing", "cash_account", {"label": "Cash Account", "fieldtype": "Link", "options": "Account", "insert_after": "company", "default": "Cashier Till - C", "read_only": 1})
    _custom_field("Pharmacy Shift Closing", "custom_shift_operational_status", {"label": "Operational Status", "fieldtype": "Select", "options": "Active\nUnder Review\nClosed", "insert_after": "status", "default": "Active", "read_only": 1, "allow_on_submit": 1, "in_standard_filter": 1})
    _custom_field("Pharmacy Shift Closing", "custom_sales_cutoff_at", {"label": "Sales Cutoff At", "fieldtype": "Datetime", "insert_after": "custom_shift_operational_status", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_review_started_at", {"label": "Review Started At", "fieldtype": "Datetime", "insert_after": "custom_sales_cutoff_at", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_review_started_by", {"label": "Review Started By", "fieldtype": "Link", "options": "User", "insert_after": "custom_review_started_at", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_review_expected_cash", {"label": "Review Expected Cash", "fieldtype": "Currency", "insert_after": "custom_review_started_by", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_review_actual_cash", {"label": "Review Counted Cash", "fieldtype": "Currency", "insert_after": "custom_review_expected_cash", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_review_difference", {"label": "Review Cash Difference", "fieldtype": "Currency", "insert_after": "custom_review_actual_cash", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_review_cash_reference", {"label": "Review Cash Envelope Reference", "fieldtype": "Data", "insert_after": "custom_review_difference", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_review_notes", {"label": "Review Notes", "fieldtype": "Small Text", "insert_after": "custom_review_cash_reference", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_cash_difference_resolution", {"label": "Cash Difference Resolution", "fieldtype": "Select", "options": "No Difference\nEmployee Liability\nCompany Expense\nOverage Income", "insert_after": "custom_review_notes", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_cash_difference_employee", {"label": "Cash Difference Employee", "fieldtype": "Link", "options": "Employee", "insert_after": "custom_cash_difference_resolution", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_cash_difference_account", {"label": "Cash Difference Account", "fieldtype": "Link", "options": "Account", "insert_after": "custom_cash_difference_employee", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_cash_difference_journal", {"label": "Cash Difference Journal", "fieldtype": "Link", "options": "Journal Entry", "insert_after": "custom_cash_difference_account", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_final_posted_at", {"label": "Final Posted At", "fieldtype": "Datetime", "insert_after": "custom_cash_difference_journal", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_final_posted_by", {"label": "Final Posted By", "fieldtype": "Link", "options": "User", "insert_after": "custom_final_posted_at", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_rollover_new_shift", {"label": "Rollover New Shift", "fieldtype": "Link", "options": "Pharmacy Shift Closing", "insert_after": "custom_final_posted_by", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_rollover_new_opening_balance", {"label": "New Shift Opening Float", "fieldtype": "Currency", "insert_after": "custom_rollover_new_shift", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "custom_rollover_net_safe_cash", {"label": "Legacy Net Safe Cash (Unused)", "fieldtype": "Currency", "insert_after": "custom_rollover_new_opening_balance", "read_only": 1, "allow_on_submit": 1, "hidden": 1})
    _custom_field("Pharmacy Shift Closing", "closed_by", {"label": "Closed By", "fieldtype": "Link", "options": "User", "insert_after": "end_time", "read_only": 1})
    _custom_field("Pharmacy Shift Closing", "closed_at", {"label": "Closed At", "fieldtype": "Datetime", "insert_after": "closed_by", "read_only": 1})
    _custom_field("Pharmacy Shift Closing", "opening_cash_movement", {"label": "Opening Cash Movement", "fieldtype": "Link", "options": "Shift Cash Movement", "insert_after": "opening_balance", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "closing_cash_movement", {"label": "Closing Cash Movement", "fieldtype": "Link", "options": "Shift Cash Movement", "insert_after": "actual_cash", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "opening_float_return_movement", {"label": "Opening Float Return", "fieldtype": "Link", "options": "Shift Cash Movement", "insert_after": "closing_cash_movement", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "cash_sales_deposit_movement", {"label": "Cash Sales Deposit", "fieldtype": "Link", "options": "Shift Cash Movement", "insert_after": "opening_float_return_movement", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "till_refill_return_movement", {"label": "Till Refill Return", "fieldtype": "Link", "options": "Shift Cash Movement", "insert_after": "cash_sales_deposit_movement", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Pharmacy Shift Closing", "other_cash_return_movement", {"label": "Other Cash Return", "fieldtype": "Link", "options": "Shift Cash Movement", "insert_after": "till_refill_return_movement", "read_only": 1, "allow_on_submit": 1})
    _custom_field("Shift Cash Movement", "purchase_invoice", {"label": "Purchase Invoice", "fieldtype": "Link", "options": "Purchase Invoice", "insert_after": "supplier", "depends_on": 'eval:doc.movement_type=="Supplier Payment"'})
    frappe.db.commit()
    frappe.clear_cache()

    accounts = _ensure_card_accounts()
    terminal = _default_terminal(accounts)

    for name, values in SERVER_SCRIPTS.items():
        _server_script(name, values)
    for name, values in CLIENT_SCRIPTS.items():
        _client_script(name, values)

    if frappe.db.exists("Client Script", "Pharmacy Shift Closing"):
        frappe.db.set_value("Client Script", "Pharmacy Shift Closing", "enabled", 0)
    if frappe.db.exists("Server Script", "Pharmacy Shift ClosinG"):
        frappe.db.set_value("Server Script", "Pharmacy Shift ClosinG", "disabled", 1)

    # Driver handovers and shortages are now posted only during final
    # shift approval. Disable the old automatic script to avoid early or
    # duplicate accounting entries.
    if frappe.db.exists(
        "Server Script",
        "Auto Create Driver Shortage After Final Handover",
    ):
        frappe.db.set_value(
            "Server Script",
            "Auto Create Driver Shortage After Final Handover",
            "disabled",
            1,
        )

    from pharma_erp.pharma_erp.fix_delivery_settlement_multi_cycle import install as install_delivery_settlement_multi_cycle
    multi_cycle_fix = install_delivery_settlement_multi_cycle()

    patches = [_patch_pos_api(), _patch_pos_js()]
    frappe.db.commit()
    frappe.clear_cache()
    result = {"doctypes": list(DOCTYPE_SPECS), "accounts": accounts, "terminal": terminal, "multi_cycle_fix": multi_cycle_fix, "patches": patches}
    print("Pharmacy Shift base components installed successfully.")
    print(json.dumps(result, default=str, indent=2))
    return result


def verify():
    result = {
        "doctypes": {name: bool(frappe.db.exists("DocType", name)) for name in DOCTYPE_SPECS},
        "terminals": frappe.get_all("Card POS Terminal", fields=["name", "terminal_name", "bank_label", "clearing_account", "destination_bank_account", "enabled"]),
        "page_exists": bool(frappe.db.exists("Page", "pharmacy-shift-management")),
        "mode_accounts": {},
        "review_accounts": {
            "employee_shortage": bool(frappe.db.exists("Account", "Employee Shortage - C")),
            "cash_shortage_expense": bool(frappe.db.exists("Account", "Cash Shortage Expense - C")),
            "cash_overage_income": bool(frappe.db.exists("Account", "Cash Overage Income - C")),
        },
        "script_status": {
            "old_shift_client_enabled": frappe.db.get_value("Client Script", "Pharmacy Shift Closing", "enabled") if frappe.db.exists("Client Script", "Pharmacy Shift Closing") else None,
            "old_shift_server_disabled": frappe.db.get_value("Server Script", "Pharmacy Shift ClosinG", "disabled") if frappe.db.exists("Server Script", "Pharmacy Shift ClosinG") else None,
            "old_driver_auto_disabled": frappe.db.get_value("Server Script", "Auto Create Driver Shortage After Final Handover", "disabled") if frappe.db.exists("Server Script", "Auto Create Driver Shortage After Final Handover") else None,
            "deferred_reconciliation_script": bool(frappe.db.exists("Server Script", "Shift Payment Reconciliation - After Submit")),
        },
    }
    for mode in ["Cash", "Insta Pay", "Wallet", "Credit Card"]:
        result["mode_accounts"][mode] = frappe.db.get_value("Mode of Payment Account", {"parent": mode, "company": COMPANY}, "default_account")
    print(json.dumps(result, default=str, indent=2))
    return result


def restore_pos_backups():
    bench = Path(frappe.get_app_path(APP)).parents[2]
    paths = [
        bench / "apps/pharma_erp/pharma_erp/pharma_erp/page/pharmacy_pos/api.py",
        bench / "apps/pharma_erp/pharma_erp/public/js/pharmacy_pos/payment.js",
    ]
    restored = []
    for path in paths:
        backup = path.with_suffix(path.suffix + ".pre_card_v2.bak")
        if backup.exists():
            shutil.copy2(backup, path)
            restored.append(str(path))
    frappe.clear_cache()
    print(restored)
    return restored
