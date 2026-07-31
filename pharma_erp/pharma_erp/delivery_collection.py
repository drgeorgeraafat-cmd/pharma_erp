from pathlib import Path

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
    get_accounting_dimensions,
)
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry
from erpnext.accounts.party import complete_contact_details


DELIVERY_TRANSIT_ACCOUNT = "Delivery Cash In Transit - C"

COLLECTION_METHOD_MODE_CANDIDATES = {
    "Cash": ("Cash",),
    "InstaPay": ("Insta Pay", "InstaPay"),
    "Mobile Wallet": ("Wallet", "Mobile Wallet"),
    "Card": ("Credit Card", "Card"),
    "Bank Transfer": ("Bank Transfer",),
}

COLLECTION_PROOF_FIELD = "custom_driver_collection_proof"
COLLECTION_PROOF_REQUIRED_METHODS = {"InstaPay", "Mobile Wallet", "Bank Transfer"}
COLLECTION_PROOF_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".heic",
    ".heif",
}


class ControlledDeliveryPaymentEntry(PaymentEntry):
    """Payment Entry variant for the controlled delivery collection path.

    ERPNext's interactive Payment Entry helpers enforce the current Desk user's
    Account / Payment Entry read permissions while they populate balances and
    reference details. Delivery users intentionally do not have those accounting
    master permissions. This subclass keeps the normal Payment Entry validation
    and submit hooks, but replaces only those interactive lookups with validated
    server-side DB reads for the already-authorized delivery transaction.
    """

    def set_missing_values(self):
        if self.payment_type != "Receive":
            frappe.throw(_("Controlled delivery collection only supports Receive payments."))
        if self.party_type != "Customer":
            frappe.throw(_("Controlled delivery collection requires Customer as Party Type."))
        if not self.party:
            frappe.throw(_("Customer is mandatory for controlled delivery collection."))

        party_name_field = (
            "title"
            if self.party_type == "Shareholder"
            else self.party_type.lower() + "_name"
        )
        if frappe.db.has_column(self.party_type, party_name_field):
            self.party_name = frappe.db.get_value(
                self.party_type, self.party, party_name_field
            )
        else:
            self.party_name = frappe.db.get_value(
                self.party_type, self.party, "name"
            )

        if self.contact_person:
            complete_contact_details(self)

        self.setup_party_account_field()
        if not self.party_account:
            frappe.throw(_("Receivable account is mandatory for controlled collection."))

        company_currency = (
            self.get("company_currency")
            or frappe.get_cached_value("Company", self.company, "default_currency")
        )
        paid_from = _validated_payment_account(
            self.paid_from, self.company, _("Receivable account")
        )
        paid_to = _validated_payment_account(
            self.paid_to, self.company, _("Collection destination account")
        )

        self.paid_from_account_currency = (
            paid_from.account_currency or company_currency
        )
        self.paid_to_account_currency = paid_to.account_currency or company_currency
        self.paid_from_account_type = paid_from.account_type
        self.paid_to_account_type = paid_to.account_type

        # These are informational form balances only; they do not affect GL.
        # Leaving them as zero avoids the permission-gated interactive lookup.
        self.paid_from_account_balance = 0
        self.paid_to_account_balance = 0
        self.party_balance = 0
        self.party_account_currency = self.paid_from_account_currency

    def set_missing_ref_details(
        self,
        force=False,
        update_ref_details_only_for=None,
        reference_exchange_details=None,
    ):
        for row in self.get("references") or []:
            if not flt(row.allocated_amount, 6):
                continue
            if update_ref_details_only_for and (
                row.reference_doctype, row.reference_name
            ) not in update_ref_details_only_for:
                continue
            if row.reference_doctype != "Sales Invoice":
                frappe.throw(
                    _("Controlled delivery collection only supports Sales Invoice references.")
                )

            invoice = frappe.db.get_value(
                "Sales Invoice",
                row.reference_name,
                [
                    "name",
                    "docstatus",
                    "company",
                    "customer",
                    "debit_to",
                    "due_date",
                    "currency",
                    "conversion_rate",
                    "base_rounded_total",
                    "base_grand_total",
                    "rounded_total",
                    "grand_total",
                    "outstanding_amount",
                ],
                as_dict=True,
            )
            if not invoice or cint(invoice.docstatus) != 1:
                frappe.throw(
                    _("Sales Invoice must be submitted: {0}").format(
                        row.reference_name
                    )
                )
            if invoice.company != self.company or invoice.customer != self.party:
                frappe.throw(
                    _("Sales Invoice company or customer does not match the collection.")
                )
            if invoice.debit_to != self.paid_from:
                frappe.throw(
                    _("Sales Invoice receivable account does not match the Payment Entry.")
                )

            company_currency = frappe.get_cached_value(
                "Company", invoice.company, "default_currency"
            )
            if self.party_account_currency == company_currency:
                total_amount = (
                    invoice.base_rounded_total or invoice.base_grand_total
                )
                exchange_rate = 1
            else:
                total_amount = invoice.rounded_total or invoice.grand_total
                exchange_rate = invoice.conversion_rate or 1

            row.total_amount = flt(total_amount, 6)
            row.outstanding_amount = flt(invoice.outstanding_amount, 6)
            row.exchange_rate = flt(exchange_rate, 9)
            row.due_date = invoice.due_date

    def validate_allocated_amount_with_latest_data(self):
        for row in self.get("references") or []:
            if not flt(row.allocated_amount, 6):
                continue
            if row.reference_doctype != "Sales Invoice":
                frappe.throw(
                    _("Controlled delivery collection only supports Sales Invoice references.")
                )

            latest = frappe.db.get_value(
                "Sales Invoice",
                row.reference_name,
                ["docstatus", "company", "customer", "outstanding_amount"],
                as_dict=True,
            )
            if not latest or cint(latest.docstatus) != 1:
                frappe.throw(
                    _("Sales Invoice must be submitted: {0}").format(
                        row.reference_name
                    )
                )
            if latest.company != self.company or latest.customer != self.party:
                frappe.throw(
                    _("Sales Invoice company or customer does not match the collection.")
                )

            outstanding = flt(latest.outstanding_amount, 6)
            allocated = flt(row.allocated_amount, 6)
            if outstanding <= 0.000001:
                frappe.throw(
                    _("Sales Invoice {0} has already been fully paid.").format(
                        row.reference_name
                    )
                )
            if allocated > outstanding + 0.01:
                frappe.throw(
                    _("Allocated amount cannot exceed current outstanding amount for {0}.").format(
                        row.reference_name
                    )
                )


def validate_collection_proof(payment_method, proof_url, invoice_name=None):
    """Validate and link a driver's transfer/receipt image.

    A proof image is mandatory for direct transfers (InstaPay, mobile wallet,
    and bank transfer).  Card receipts are allowed but remain optional because
    the configured POS terminal is already captured separately.
    """
    payment_method = str(payment_method or "").strip()
    proof_url = str(proof_url or "").strip()

    if payment_method in COLLECTION_PROOF_REQUIRED_METHODS and not proof_url:
        frappe.throw(_("صورة التحويل مطلوبة لطريقة الدفع المحددة."))

    if not proof_url:
        return ""

    file_row = frappe.db.get_value(
        "File",
        {"file_url": proof_url},
        [
            "name",
            "file_name",
            "attached_to_doctype",
            "attached_to_name",
        ],
        as_dict=True,
    )
    if not file_row:
        frappe.throw(_("صورة التحويل المرفوعة غير موجودة. أعد تصويرها ورفعها."))

    suffix = Path(str(file_row.file_name or proof_url)).suffix.lower()
    if suffix not in COLLECTION_PROOF_IMAGE_EXTENSIONS:
        frappe.throw(_("إثبات التحصيل يجب أن يكون صورة."))

    if invoice_name:
        attached_doctype = str(file_row.attached_to_doctype or "").strip()
        attached_name = str(file_row.attached_to_name or "").strip()
        if attached_doctype and (
            attached_doctype != "Sales Invoice" or attached_name != invoice_name
        ):
            frappe.throw(_("صورة التحويل مرتبطة بمستند آخر. ارفع صورة جديدة."))

        if not attached_doctype:
            frappe.db.set_value(
                "File",
                file_row.name,
                {
                    "attached_to_doctype": "Sales Invoice",
                    "attached_to_name": invoice_name,
                    "attached_to_field": COLLECTION_PROOF_FIELD,
                },
                update_modified=False,
            )

    return proof_url


def resolve_collection_mode_of_payment(customer_method):
    for candidate in COLLECTION_METHOD_MODE_CANDIDATES.get(
        customer_method, (customer_method,)
    ):
        if candidate and frappe.db.exists("Mode of Payment", candidate):
            return candidate

    frappe.throw(
        _("No Mode of Payment matches customer payment method: {0}").format(
            customer_method or _("Not specified")
        )
    )


def mode_default_account(mode_of_payment, company):
    account = frappe.db.get_value(
        "Mode of Payment Account",
        {
            "parent": mode_of_payment,
            "parenttype": "Mode of Payment",
            "company": company,
        },
        "default_account",
    )
    if not account:
        frappe.throw(
            _("Set a Default Account for company {0} in Mode of Payment {1}.").format(
                company, mode_of_payment
            )
        )
    return account


def _validated_payment_account(account, company, label):
    account = str(account or "").strip()
    row = frappe.db.get_value(
        "Account",
        account,
        [
            "name",
            "company",
            "is_group",
            "disabled",
            "account_type",
            "account_currency",
        ],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("{0} was not found: {1}").format(label, account or _("Not set")))
    if row.company != company:
        frappe.throw(_("{0} belongs to another company: {1}").format(label, account))
    if cint(row.is_group):
        frappe.throw(_("{0} cannot be a group account: {1}").format(label, account))
    if cint(row.disabled):
        frappe.throw(_("{0} is disabled: {1}").format(label, account))
    return row


def _submitted_linked_payment(invoice):
    payment_name = invoice.get("custom_collection_payment_entry") or ""
    if not payment_name or not frappe.db.exists("Payment Entry", payment_name):
        return None

    if int(frappe.db.get_value("Payment Entry", payment_name, "docstatus") or 0) != 1:
        return None

    return frappe.get_doc("Payment Entry", payment_name)


def create_collection_payment_entry(
    parent_invoice,
    group_invoices,
    amount,
    customer_method,
    received_by,
    reference_no=None,
):
    """Create one submitted Payment Entry allocated across the delivery group.

    Cash received by the delivery boy is posted to Delivery Cash In Transit.
    Confirmed non-cash payments are posted to the Mode of Payment default account.

    The calling page validates the current delivery user and the assigned order
    before reaching this helper. Account and Payment Entry writes use explicit
    ignore_permissions so the Delivery role does not need direct access to
    accounting masters, without changing the live request user.
    """
    existing = _submitted_linked_payment(parent_invoice)
    if existing:
        return existing

    amount = flt(amount, 6)
    if amount <= 0:
        frappe.throw(_("Collection amount must be greater than zero."))

    submitted_invoices = [
        invoice
        for invoice in group_invoices
        if invoice.docstatus == 1 and flt(invoice.outstanding_amount, 6) > 0
    ]
    if not submitted_invoices:
        frappe.throw(_("There is no outstanding amount to allocate."))

    company = parent_invoice.company
    customer = parent_invoice.customer
    company_currency = frappe.get_cached_value(
        "Company", company, "default_currency"
    )
    if not company_currency:
        frappe.throw(_("Default currency is missing for company: {0}").format(company))
    receivable_account = parent_invoice.debit_to
    receivable_details = _validated_payment_account(
        receivable_account,
        company,
        _("Receivable account"),
    )
    if receivable_details.account_type != "Receivable":
        frappe.throw(
            _("Sales Invoice receivable account must have account type Receivable: {0}").format(
                receivable_account
            )
        )

    for invoice in submitted_invoices:
        if invoice.company != company or invoice.customer != customer:
            frappe.throw(
                _("All delivery-group invoices must have the same company and customer.")
            )
        if invoice.debit_to != receivable_account:
            frappe.throw(
                _("All delivery-group invoices must use the same receivable account.")
            )

    total_outstanding = flt(
        sum(flt(invoice.outstanding_amount, 6) for invoice in submitted_invoices),
        6,
    )
    if amount > total_outstanding + 0.01:
        frappe.throw(
            _("Collection amount cannot exceed current outstanding amount: {0}").format(
                frappe.format_value(total_outstanding, {"fieldtype": "Currency"})
            )
        )

    original_user = frappe.session.user or "Guest"

    try:
        # Keep the authenticated delivery user's request session intact.
        # Accounting writes below already use explicit ignore_permissions.

        mode_of_payment = resolve_collection_mode_of_payment(customer_method)

        if received_by == "Delivery Boy":
            paid_to = DELIVERY_TRANSIT_ACCOUNT
        else:
            paid_to = mode_default_account(mode_of_payment, company)

        paid_to_details = _validated_payment_account(
            paid_to,
            company,
            _("Collection destination account"),
        )

        posting_date = nowdate()
        payment_entry = ControlledDeliveryPaymentEntry(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "company": company,
                "company_currency": company_currency,
                "cost_center": parent_invoice.get("cost_center"),
                "posting_date": posting_date,
                "reference_date": posting_date,
                "mode_of_payment": mode_of_payment,
                "party_type": "Customer",
                "party": customer,
                "contact_person": parent_invoice.get("contact_person"),
                "paid_from": receivable_account,
                "paid_to": paid_to,
                "paid_from_account_currency": (
                    receivable_details.account_currency
                    or parent_invoice.get("party_account_currency")
                    or company_currency
                ),
                "paid_to_account_currency": (
                    paid_to_details.account_currency
                    or company_currency
                ),
                "paid_from_account_type": receivable_details.account_type,
                "paid_to_account_type": paid_to_details.account_type,
                "paid_amount": amount,
                "received_amount": amount,
                "letter_head": parent_invoice.get("letter_head"),
            }
        )

        payment_entry.project = parent_invoice.get("project") or next(
            (row.get("project") for row in parent_invoice.get("items") or [] if row.get("project")),
            None,
        )
        for dimension in get_accounting_dimensions():
            payment_entry.set(dimension, parent_invoice.get(dimension))

        payment_entry.posting_date = posting_date
        payment_entry.reference_no = (
            str(reference_no or "").strip()
            or "DELIVERY-{0}".format(parent_invoice.name)
        )
        payment_entry.reference_date = posting_date
        payment_entry.remarks = _(
            "Delivery collection for {0}; method {1}; received by {2}; declared by {3}."
        ).format(
            parent_invoice.name,
            customer_method,
            received_by,
            original_user,
        )

        payment_entry.set("references", [])
        remaining = amount
        allocated_invoice_names = []

        for invoice in submitted_invoices:
            if remaining <= 0.000001:
                break

            allocated_amount = min(flt(invoice.outstanding_amount, 6), remaining)
            if allocated_amount <= 0:
                continue

            payment_entry.append(
                "references",
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "allocated_amount": allocated_amount,
                },
            )
            allocated_invoice_names.append(invoice.name)
            remaining = flt(remaining - allocated_amount, 6)

        if remaining > 0.01:
            frappe.throw(_("Could not allocate the complete collection amount."))

        payment_entry.paid_amount = amount
        payment_entry.received_amount = amount

        previous_ignore_account_permission = bool(
            getattr(frappe.flags, "ignore_account_permission", False)
        )
        frappe.flags.ignore_account_permission = True
        try:
            payment_entry.flags.ignore_permissions = True
            payment_entry.insert(ignore_permissions=True)
            payment_entry.flags.ignore_permissions = True
            payment_entry.submit()
        finally:
            frappe.flags.ignore_account_permission = (
                previous_ignore_account_permission
            )

        for invoice_name in allocated_invoice_names:
            if frappe.get_meta("Sales Invoice").has_field(
                "custom_collection_payment_entry"
            ):
                frappe.db.set_value(
                    "Sales Invoice",
                    invoice_name,
                    "custom_collection_payment_entry",
                    payment_entry.name,
                    update_modified=False,
                )

        return payment_entry

    finally:
        # Never mutate frappe.session.user inside a live delivery web request.
        # frappe.set_user() can replace the request session object and break
        # the client reload after an otherwise successful collection.
        pass
