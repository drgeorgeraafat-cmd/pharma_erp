from collections import defaultdict
from html import escape

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, nowdate

from pharma_erp.treasury_access import can_view_treasury


MAX_REPORT_DAYS = 366
MAX_GL_ROWS = 5000


def execute(filters=None):
    filters = frappe._dict(filters or {})
    _validate_access()

    company = filters.get("company") or frappe.defaults.get_user_default("Company")
    if not company or not frappe.db.exists("Company", company):
        frappe.throw(_("Please select a valid Company."))

    from_date = getdate(filters.get("from_date") or nowdate())
    to_date = getdate(filters.get("to_date") or from_date)
    if from_date > to_date:
        frappe.throw(_("From Date cannot be after To Date."))
    if date_diff(to_date, from_date) > MAX_REPORT_DAYS:
        frappe.throw(_("The report period cannot exceed {0} days.").format(MAX_REPORT_DAYS))

    accounts = _get_accounts(
        company=company,
        account_type=filters.get("account_type"),
        account=filters.get("account"),
    )
    if not accounts:
        return _get_columns(), [], _("No active Cash or Bank accounts match the selected filters."), None, []

    account_names = [row.name for row in accounts]
    company_currency = frappe.db.get_value("Company", company, "default_currency") or ""
    opening_by_account = _get_opening_balances(company, account_names, from_date)
    gl_rows, truncated = _get_gl_rows(company, account_names, from_date, to_date)
    source_context = _get_source_context(gl_rows)

    running_by_account = defaultdict(float)
    for account_name in account_names:
        running_by_account[account_name] = flt(opening_by_account.get(account_name))

    period_totals = {
        account_name: {"debit": 0.0, "credit": 0.0}
        for account_name in account_names
    }
    all_rows = []
    for row in gl_rows:
        account_name = row.get("account")
        debit = flt(row.get("debit"))
        credit = flt(row.get("credit"))
        period_totals[account_name]["debit"] += debit
        period_totals[account_name]["credit"] += credit
        running_by_account[account_name] += debit - credit

        source = _resolve_source(row, source_context)
        direction = "In" if debit >= credit else "Out"
        report_row = {
            "posting_date": row.get("posting_date"),
            "account": account_name,
            "account_type": row.get("account_type"),
            "movement_family": source.get("movement_family"),
            "category": source.get("category"),
            "direction": direction,
            "debit": debit,
            "credit": credit,
            "running_balance": running_by_account[account_name],
            "currency": company_currency,
            "source_doctype": source.get("source_doctype"),
            "source_document": source.get("source_document"),
            "accounting_voucher_type": row.get("voucher_type"),
            "accounting_voucher_no": row.get("voucher_no"),
            "shift_reference": source.get("shift_reference"),
            "cash_drawer": source.get("cash_drawer"),
            "reference_no": source.get("reference_no"),
            "party": source.get("party") or row.get("party"),
            "requested_by": source.get("requested_by"),
            "approved_by": source.get("approved_by"),
            "against": row.get("against"),
            "cost_center": row.get("cost_center"),
            "remarks": source.get("remarks") or row.get("remarks"),
            "creation": row.get("creation"),
        }
        all_rows.append(report_row)

    filtered_rows = _apply_row_filters(all_rows, filters)
    account_summary = _build_account_summary(
        accounts=accounts,
        opening_by_account=opening_by_account,
        period_totals=period_totals,
    )
    report_summary = _build_report_summary(filtered_rows, account_summary, company_currency)
    chart = _build_chart(account_summary)
    message = _build_message(
        account_summary=account_summary,
        currency=company_currency,
        filters=filters,
        truncated=truncated,
        total_rows=len(all_rows),
        filtered_rows=len(filtered_rows),
    )

    return _get_columns(), filtered_rows, message, chart, report_summary


def _validate_access():
    if not can_view_treasury():
        frappe.throw(_("You do not have permission to view Treasury reports."), frappe.PermissionError)


def _get_accounts(company, account_type=None, account=None):
    filters = {
        "company": company,
        "root_type": "Asset",
        "is_group": 0,
        "disabled": 0,
        "account_type": ["in", ["Cash", "Bank"]],
    }
    if account_type in {"Cash", "Bank"}:
        filters["account_type"] = account_type
    if account:
        filters["name"] = account

    return frappe.get_all(
        "Account",
        filters=filters,
        fields=["name", "account_name", "account_type", "account_currency"],
        order_by="account_type asc, account_name asc",
        limit_page_length=1000,
    )


def _get_opening_balances(company, account_names, from_date):
    if not account_names:
        return {}
    placeholders = ", ".join(["%s"] * len(account_names))
    rows = frappe.db.sql(
        f"""
        select account, sum(debit - credit) as balance
        from `tabGL Entry`
        where company = %s
          and posting_date < %s
          and is_cancelled = 0
          and account in ({placeholders})
        group by account
        """,
        [company, from_date, *account_names],
        as_dict=True,
    )
    return {row.account: flt(row.balance) for row in rows}


def _get_gl_rows(company, account_names, from_date, to_date):
    placeholders = ", ".join(["%s"] * len(account_names))
    rows = frappe.db.sql(
        f"""
        select
            gle.name,
            gle.posting_date,
            gle.account,
            acc.account_type,
            gle.debit,
            gle.credit,
            gle.voucher_type,
            gle.voucher_no,
            gle.against,
            gle.party_type,
            gle.party,
            gle.cost_center,
            gle.remarks,
            gle.creation
        from `tabGL Entry` gle
        inner join `tabAccount` acc on acc.name = gle.account
        where gle.company = %s
          and gle.posting_date between %s and %s
          and gle.is_cancelled = 0
          and gle.account in ({placeholders})
        order by gle.posting_date asc, gle.creation asc, gle.name asc
        limit %s
        """,
        [company, from_date, to_date, *account_names, MAX_GL_ROWS + 1],
        as_dict=True,
    )
    truncated = len(rows) > MAX_GL_ROWS
    return rows[:MAX_GL_ROWS], truncated


def _get_source_context(gl_rows):
    voucher_groups = defaultdict(set)
    for row in gl_rows:
        voucher_groups[row.get("voucher_type")].add(row.get("voucher_no"))

    journal_entries = sorted(voucher_groups.get("Journal Entry") or [])
    payment_entries = sorted(voucher_groups.get("Payment Entry") or [])
    sales_invoices = sorted(voucher_groups.get("Sales Invoice") or [])
    purchase_invoices = sorted(voucher_groups.get("Purchase Invoice") or [])

    return {
        "shift_movements": _map_by_linked_journal(
            "Shift Cash Movement",
            journal_entries,
            [
                "name", "journal_entry", "movement_type", "direction", "shift_reference",
                "cash_drawer", "reference_no", "description", "requested_by", "approved_by",
            ],
        ),
        "treasury_vouchers": _map_by_linked_journal(
            "Treasury Voucher",
            journal_entries,
            [
                "name", "journal_entry", "voucher_type", "category", "reference_no",
                "beneficiary_or_payer", "description", "requested_by", "approved_by",
            ],
        ),
        "card_settlements": _map_by_linked_journal(
            "Card Bank Settlement",
            journal_entries,
            [
                "name", "journal_entry", "bank_reference", "settlement_date", "status",
                "gross_amount", "fee_amount", "net_amount",
            ],
        ),
        "payment_reconciliations": _map_by_linked_journal(
            "Shift Payment Reconciliation",
            journal_entries,
            [
                "name", "journal_entry", "mode_of_payment", "shift_reference", "status",
                "reviewed_amount", "fee_amount", "net_transfer_amount", "reviewed_by",
            ],
        ),
        "journal_entries": _map_by_name(
            "Journal Entry",
            journal_entries,
            ["name", "user_remark", "cheque_no", "cheque_date"],
        ),
        "payment_entries": _map_by_name(
            "Payment Entry",
            payment_entries,
            [
                "name", "payment_type", "party_type", "party", "paid_from", "paid_to",
                "reference_no", "remarks", "custom_treasury_request_status",
                "custom_treasury_requested_by", "custom_treasury_approved_by",
            ],
        ),
        "sales_invoices": _map_by_name(
            "Sales Invoice",
            sales_invoices,
            ["name", "customer", "is_return", "custom_order_type", "remarks"],
        ),
        "purchase_invoices": _map_by_name(
            "Purchase Invoice",
            purchase_invoices,
            ["name", "supplier", "is_return", "remarks"],
        ),
    }


def _existing_fields(doctype, candidates):
    if not frappe.db.exists("DocType", doctype):
        return []
    meta = frappe.get_meta(doctype)
    fields = []
    for fieldname in candidates:
        if fieldname == "name" or meta.has_field(fieldname):
            fields.append(fieldname)
    return fields


def _map_by_name(doctype, names, candidates):
    if not names or not frappe.db.exists("DocType", doctype):
        return {}
    fields = _existing_fields(doctype, candidates)
    if "name" not in fields:
        fields.insert(0, "name")
    rows = frappe.get_all(
        doctype,
        filters={"name": ["in", names]},
        fields=fields,
        limit_page_length=0,
    )
    return {row.name: row for row in rows}


def _map_by_linked_journal(doctype, journal_entries, candidates):
    if not journal_entries or not frappe.db.exists("DocType", doctype):
        return {}
    fields = _existing_fields(doctype, candidates)
    if "journal_entry" not in fields:
        return {}
    rows = frappe.get_all(
        doctype,
        filters={"journal_entry": ["in", journal_entries]},
        fields=fields,
        limit_page_length=0,
    )
    return {row.journal_entry: row for row in rows if row.get("journal_entry")}


def _resolve_source(gl_row, context):
    voucher_type = gl_row.get("voucher_type") or ""
    voucher_no = gl_row.get("voucher_no") or ""
    base = {
        "movement_family": "Other",
        "category": voucher_type or "Other",
        "source_doctype": voucher_type or "Journal Entry",
        "source_document": voucher_no,
        "shift_reference": "",
        "cash_drawer": "",
        "reference_no": "",
        "party": "",
        "requested_by": "",
        "approved_by": "",
        "remarks": gl_row.get("remarks") or "",
    }

    if voucher_type == "Journal Entry":
        movement = context["shift_movements"].get(voucher_no)
        if movement:
            base.update({
                "movement_family": "Shift Cash Movement",
                "category": movement.get("movement_type") or "Shift Cash Movement",
                "source_doctype": "Shift Cash Movement",
                "source_document": movement.get("name"),
                "shift_reference": movement.get("shift_reference"),
                "cash_drawer": movement.get("cash_drawer"),
                "reference_no": movement.get("reference_no"),
                "requested_by": movement.get("requested_by"),
                "approved_by": movement.get("approved_by"),
                "remarks": movement.get("description") or base["remarks"],
            })
            return base

        voucher = context["treasury_vouchers"].get(voucher_no)
        if voucher:
            base.update({
                "movement_family": voucher.get("voucher_type") or "Other",
                "category": voucher.get("category") or voucher.get("voucher_type") or "Other",
                "source_doctype": "Treasury Voucher",
                "source_document": voucher.get("name"),
                "reference_no": voucher.get("reference_no"),
                "party": voucher.get("beneficiary_or_payer"),
                "requested_by": voucher.get("requested_by"),
                "approved_by": voucher.get("approved_by"),
                "remarks": voucher.get("description") or base["remarks"],
            })
            return base

        settlement = context["card_settlements"].get(voucher_no)
        if settlement:
            base.update({
                "movement_family": "Card Settlement",
                "category": "Card Bank Settlement",
                "source_doctype": "Card Bank Settlement",
                "source_document": settlement.get("name"),
                "reference_no": settlement.get("bank_reference"),
            })
            return base

        reconciliation = context["payment_reconciliations"].get(voucher_no)
        if reconciliation:
            base.update({
                "movement_family": "Electronic Settlement",
                "category": reconciliation.get("mode_of_payment") or "Electronic Settlement",
                "source_doctype": "Shift Payment Reconciliation",
                "source_document": reconciliation.get("name"),
                "shift_reference": reconciliation.get("shift_reference"),
                "approved_by": reconciliation.get("reviewed_by"),
            })
            return base

        journal = context["journal_entries"].get(voucher_no) or {}
        base.update({
            "movement_family": "Other Journal Entry",
            "category": "Journal Entry",
            "source_doctype": "Journal Entry",
            "source_document": voucher_no,
            "reference_no": journal.get("cheque_no"),
            "remarks": journal.get("user_remark") or base["remarks"],
        })
        return base

    if voucher_type == "Payment Entry":
        payment = context["payment_entries"].get(voucher_no) or {}
        payment_type = payment.get("payment_type") or ""
        party_type = payment.get("party_type") or ""
        if payment_type == "Internal Transfer":
            family = "Internal Transfer"
        elif payment_type == "Receive":
            family = "Customer Receipt" if party_type == "Customer" else "General Receipt"
        elif payment_type == "Pay":
            family = "Supplier Payment" if party_type == "Supplier" else "Other"
        else:
            family = "Other"
        base.update({
            "movement_family": family,
            "category": payment_type or "Payment Entry",
            "source_doctype": "Payment Entry",
            "source_document": voucher_no,
            "reference_no": payment.get("reference_no"),
            "party": payment.get("party"),
            "requested_by": payment.get("custom_treasury_requested_by"),
            "approved_by": payment.get("custom_treasury_approved_by"),
            "remarks": payment.get("remarks") or base["remarks"],
        })
        return base

    if voucher_type == "Sales Invoice":
        invoice = context["sales_invoices"].get(voucher_no) or {}
        base.update({
            "movement_family": "Sales Return" if invoice.get("is_return") else "POS / Sales",
            "category": invoice.get("custom_order_type") or "Sales Invoice",
            "source_doctype": "Sales Invoice",
            "source_document": voucher_no,
            "party": invoice.get("customer"),
            "remarks": invoice.get("remarks") or base["remarks"],
        })
        return base

    if voucher_type == "Purchase Invoice":
        invoice = context["purchase_invoices"].get(voucher_no) or {}
        base.update({
            "movement_family": "Supplier Payment",
            "category": "Purchase Return" if invoice.get("is_return") else "Purchase Invoice",
            "source_doctype": "Purchase Invoice",
            "source_document": voucher_no,
            "party": invoice.get("supplier"),
            "remarks": invoice.get("remarks") or base["remarks"],
        })
        return base

    base["movement_family"] = voucher_type or "Other"
    return base


def _apply_row_filters(rows, filters):
    movement_family = str(filters.get("movement_family") or "").strip()
    direction = str(filters.get("direction") or "").strip()
    reference_no = str(filters.get("reference_no") or "").strip().lower()

    result = []
    for row in rows:
        if movement_family and row.get("movement_family") != movement_family:
            continue
        if direction and row.get("direction") != direction:
            continue
        if reference_no:
            haystack = " ".join([
                str(row.get("reference_no") or ""),
                str(row.get("source_document") or ""),
                str(row.get("accounting_voucher_no") or ""),
                str(row.get("party") or ""),
                str(row.get("remarks") or ""),
            ]).lower()
            if reference_no not in haystack:
                continue
        result.append(row)
    return result


def _build_account_summary(accounts, opening_by_account, period_totals):
    rows = []
    for account in accounts:
        opening = flt(opening_by_account.get(account.name))
        debit = flt(period_totals.get(account.name, {}).get("debit"))
        credit = flt(period_totals.get(account.name, {}).get("credit"))
        rows.append({
            "account": account.name,
            "account_type": account.account_type,
            "opening": opening,
            "debit": debit,
            "credit": credit,
            "net": debit - credit,
            "closing": opening + debit - credit,
        })
    return rows


def _build_report_summary(filtered_rows, account_summary, currency):
    opening = sum(flt(row.get("opening")) for row in account_summary)
    closing = sum(flt(row.get("closing")) for row in account_summary)
    total_in = sum(flt(row.get("debit")) for row in filtered_rows)
    total_out = sum(flt(row.get("credit")) for row in filtered_rows)
    return [
        {"value": opening, "label": _("Opening Balance"), "datatype": "Currency", "currency": currency, "indicator": "Blue"},
        {"value": total_in, "label": _("Filtered In"), "datatype": "Currency", "currency": currency, "indicator": "Green"},
        {"value": total_out, "label": _("Filtered Out"), "datatype": "Currency", "currency": currency, "indicator": "Red"},
        {"value": total_in - total_out, "label": _("Filtered Net"), "datatype": "Currency", "currency": currency, "indicator": "Orange"},
        {"value": closing, "label": _("Closing Balance"), "datatype": "Currency", "currency": currency, "indicator": "Blue"},
        {"value": len(filtered_rows), "label": _("Movement Count"), "datatype": "Int", "indicator": "Gray"},
    ]


def _build_chart(account_summary):
    return {
        "data": {
            "labels": [row.get("account") for row in account_summary],
            "datasets": [
                {
                    "name": _("Closing Balance"),
                    "values": [flt(row.get("closing")) for row in account_summary],
                }
            ],
        },
        "type": "bar",
    }


def _money(value, currency):
    return f"{flt(value):,.2f} {escape(currency or '')}".strip()


def _build_message(account_summary, currency, filters, truncated, total_rows, filtered_rows):
    table_rows = "".join(
        f"""
        <tr>
            <td>{escape(row.get('account') or '')}</td>
            <td>{escape(row.get('account_type') or '')}</td>
            <td>{_money(row.get('opening'), currency)}</td>
            <td>{_money(row.get('debit'), currency)}</td>
            <td>{_money(row.get('credit'), currency)}</td>
            <td>{_money(row.get('closing'), currency)}</td>
        </tr>
        """
        for row in account_summary
    )
    filtered_note = ""
    if filters.get("movement_family") or filters.get("direction") or filters.get("reference_no"):
        filtered_note = _(
            "Opening and closing balances include all posted movements in the period, while In/Out summary cards follow the transaction filters."
        )
    truncation_note = ""
    if truncated:
        truncation_note = _(
            "The transaction list was limited to the first {0} GL rows. Narrow the period or select one account for a complete list."
        ).format(MAX_GL_ROWS)

    return f"""
    <div dir="rtl" style="margin-bottom:12px;">
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px;">
            <span><strong>{escape(str(_("All period rows")))}:</strong> {total_rows}</span>
            <span><strong>{escape(str(_("Displayed rows")))}:</strong> {filtered_rows}</span>
            <span><strong>{escape(str(_("Currency")))}:</strong> {escape(currency or '-')}</span>
        </div>
        <div style="overflow-x:auto;">
            <table class="table table-bordered" style="min-width:760px;margin-bottom:8px;">
                <thead><tr>
                    <th>{escape(str(_("Account")))}</th>
                    <th>{escape(str(_("Type")))}</th>
                    <th>{escape(str(_("Opening")))}</th>
                    <th>{escape(str(_("In")))}</th>
                    <th>{escape(str(_("Out")))}</th>
                    <th>{escape(str(_("Closing")))}</th>
                </tr></thead>
                <tbody>{table_rows}</tbody>
            </table>
        </div>
        {f'<div class="text-muted">{escape(str(filtered_note))}</div>' if filtered_note else ''}
        {f'<div class="text-danger">{escape(str(truncation_note))}</div>' if truncation_note else ''}
    </div>
    """


def _get_columns():
    return [
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
        {"label": _("Account"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 190},
        {"label": _("Account Type"), "fieldname": "account_type", "fieldtype": "Data", "width": 90},
        {"label": _("Movement Type"), "fieldname": "movement_family", "fieldtype": "Data", "width": 145},
        {"label": _("Category"), "fieldname": "category", "fieldtype": "Data", "width": 145},
        {"label": _("Direction"), "fieldname": "direction", "fieldtype": "Data", "width": 70},
        {"label": _("In"), "fieldname": "debit", "fieldtype": "Currency", "options": "currency", "width": 110},
        {"label": _("Out"), "fieldname": "credit", "fieldtype": "Currency", "options": "currency", "width": 110},
        {"label": _("Running Balance"), "fieldname": "running_balance", "fieldtype": "Currency", "options": "currency", "width": 125},
        {"label": _("Source Type"), "fieldname": "source_doctype", "fieldtype": "Link", "options": "DocType", "width": 145},
        {"label": _("Source Document"), "fieldname": "source_document", "fieldtype": "Dynamic Link", "options": "source_doctype", "width": 150},
        {"label": _("Accounting Voucher Type"), "fieldname": "accounting_voucher_type", "fieldtype": "Link", "options": "DocType", "width": 150},
        {"label": _("Accounting Voucher"), "fieldname": "accounting_voucher_no", "fieldtype": "Dynamic Link", "options": "accounting_voucher_type", "width": 150},
        {"label": _("Shift"), "fieldname": "shift_reference", "fieldtype": "Link", "options": "Pharmacy Shift Closing", "width": 145},
        {"label": _("Cash Drawer"), "fieldname": "cash_drawer", "fieldtype": "Link", "options": "Cash Drawer", "width": 120},
        {"label": _("Reference No"), "fieldname": "reference_no", "fieldtype": "Data", "width": 120},
        {"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 150},
        {"label": _("Requested By"), "fieldname": "requested_by", "fieldtype": "Link", "options": "User", "width": 145},
        {"label": _("Approved By"), "fieldname": "approved_by", "fieldtype": "Link", "options": "User", "width": 145},
        {"label": _("Against"), "fieldname": "against", "fieldtype": "Data", "width": 180},
        {"label": _("Cost Center"), "fieldname": "cost_center", "fieldtype": "Link", "options": "Cost Center", "width": 130},
        {"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 260},
        {"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "hidden": 1},
    ]
