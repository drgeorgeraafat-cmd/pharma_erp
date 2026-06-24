from pathlib import Path

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry


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
    before reaching this helper. Account and Payment Entry operations are then
    executed with system permissions so the Delivery role does not need direct
    access to accounting masters.
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
    receivable_account = parent_invoice.debit_to

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

    original_user = frappe.session.user

    try:
        # Do not grant Account/Payment Entry permissions to the Delivery role.
        # The endpoint already validated the assigned driver and invoice.
        frappe.set_user("Administrator")

        mode_of_payment = resolve_collection_mode_of_payment(customer_method)

        if received_by == "Delivery Boy":
            paid_to = DELIVERY_TRANSIT_ACCOUNT
            if not frappe.db.exists("Account", paid_to):
                frappe.throw(_("Account not found: {0}").format(paid_to))
            if frappe.db.get_value("Account", paid_to, "company") != company:
                frappe.throw(_("Delivery transit account belongs to another company."))
        else:
            paid_to = mode_default_account(mode_of_payment, company)

        posting_date = nowdate()
        payment_entry = get_payment_entry(
            "Sales Invoice",
            parent_invoice.name,
            party_amount=amount,
            bank_account=paid_to,
            reference_date=posting_date,
            ignore_permissions=True,
        )

        payment_entry.mode_of_payment = mode_of_payment
        payment_entry.paid_to = paid_to
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
        payment_entry.flags.ignore_permissions = True
        payment_entry.insert(ignore_permissions=True)
        payment_entry.submit()

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
        frappe.set_user(original_user)
