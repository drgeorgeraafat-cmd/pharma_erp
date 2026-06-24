import frappe
from frappe.desk.reportview import get_match_cond
from frappe.utils import now_datetime


@frappe.whitelist()
def get_shift_details(cashier):
    # 1. Get the end time of the last submitted shift for this cashier.
    last_shift = frappe.db.get_all(
        "Pharmacy Shift Closing",
        filters={"cashier": cashier, "docstatus": 1},
        fields=["end_time"],
        order_by="end_time desc",
        limit=1,
    )

    last_closed_time = last_shift[0].end_time if last_shift else "2000-01-01"

    # 2. Find the first submitted Sales Invoice after the previous closing.
    first_invoice = frappe.db.get_all(
        "Sales Invoice",
        filters={
            "owner": cashier,
            "docstatus": 1,
            "creation": (">", last_closed_time),
        },
        fields=["creation"],
        order_by="creation asc",
        limit=1,
    )

    if not first_invoice:
        return {"status": "no_data"}

    start_time = first_invoice[0].creation
    end_time = now_datetime()

    # 3. Payment totals for the shift.
    sales_data = frappe.db.sql(
        """
        SELECT
            sip.mode_of_payment,
            SUM(sip.amount) AS total_amount
        FROM `tabSales Invoice Payment` sip
        INNER JOIN `tabSales Invoice` si
            ON si.name = sip.parent
        WHERE
            si.docstatus = 1
            AND si.owner = %s
            AND si.creation BETWEEN %s AND %s
        GROUP BY sip.mode_of_payment
        """,
        (cashier, start_time, end_time),
        as_dict=True,
    )

    payment_summary = []
    cash_sales = 0.0

    for data in sales_data:
        amount = float(data.total_amount or 0)

        payment_summary.append(
            {
                "mode_of_payment": data.mode_of_payment,
                "amount": amount,
            }
        )

        mop_type = frappe.db.get_value(
            "Mode of Payment",
            data.mode_of_payment,
            "type",
        )

        if mop_type == "Cash":
            cash_sales += amount

    # 4. Detailed invoice report.
    invoices = frappe.db.sql(
        """
        SELECT
            si.name,
            si.creation,
            si.customer_name,
            si.grand_total,
            GROUP_CONCAT(
                sip.mode_of_payment
                SEPARATOR ', '
            ) AS payment_modes
        FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Invoice Payment` sip
            ON si.name = sip.parent
        WHERE
            si.docstatus = 1
            AND si.owner = %s
            AND si.creation BETWEEN %s AND %s
        GROUP BY
            si.name,
            si.creation,
            si.customer_name,
            si.grand_total
        ORDER BY si.creation ASC
        """,
        (cashier, start_time, end_time),
        as_dict=True,
    )

    html = """
    <div style="max-height: 350px; overflow-y: auto; border: 1px solid #d1d8dd; border-radius: 4px;">
        <table class="table table-bordered table-hover" style="margin-bottom: 0;">
            <thead style="position: sticky; top: 0; background-color: #f4f5f6; z-index: 1;">
                <tr>
                    <th>رقم الفاتورة</th>
                    <th>الوقت</th>
                    <th>العميل</th>
                    <th>طريقة الدفع</th>
                    <th>المبلغ</th>
                </tr>
            </thead>
            <tbody>
    """

    for inv in invoices:
        time_formatted = (
            inv.creation.strftime("%Y-%m-%d %H:%M") if inv.creation else ""
        )

        html += f"""
            <tr>
                <td>
                    <a href="/app/sales-invoice/{inv.name}" target="_blank">
                        <b>{inv.name}</b>
                    </a>
                </td>
                <td>{time_formatted}</td>
                <td>{inv.customer_name or 'نقدي'}</td>
                <td>
                    <span class="badge badge-info">
                        {inv.payment_modes or 'غير محدد'}
                    </span>
                </td>
                <td><b>{inv.grand_total}</b> ج.م</td>
            </tr>
        """

    html += """
            </tbody>
        </table>
    </div>
    """

    return {
        "status": "success",
        "start_time": start_time,
        "end_time": end_time,
        "payment_summary": payment_summary,
        "cash_sales": cash_sales,
        "html_report": html,
    }


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def non_contract_customer_query(
    doctype,
    txt,
    searchfield,
    start,
    page_len,
    filters=None,
):
    """Return customers not linked to active contract records."""

    txt = (txt or "").strip()

    return frappe.db.sql(
        """
        SELECT
            `tabCustomer`.name,
            `tabCustomer`.customer_name,
            `tabCustomer`.mobile_no
        FROM `tabCustomer`
        WHERE
            IFNULL(`tabCustomer`.disabled, 0) = 0

            AND (
                `tabCustomer`.name LIKE %(txt)s
                OR IFNULL(`tabCustomer`.customer_name, '') LIKE %(txt)s
                OR IFNULL(`tabCustomer`.mobile_no, '') LIKE %(txt)s
            )

            AND NOT EXISTS (
                SELECT 1
                FROM `tabPharmacy Contract`
                WHERE
                    `tabPharmacy Contract`.customer = `tabCustomer`.name
                    AND IFNULL(`tabPharmacy Contract`.is_active, 0) = 1
            )

            AND NOT EXISTS (
                SELECT 1
                FROM `tabContract Beneficiary`
                WHERE
                    `tabContract Beneficiary`.customer = `tabCustomer`.name
                    AND IFNULL(`tabContract Beneficiary`.is_active, 0) = 1
            )

            {match_conditions}

        ORDER BY
            `tabCustomer`.customer_name,
            `tabCustomer`.name

        LIMIT %(start)s, %(page_len)s
        """.format(match_conditions=get_match_cond(doctype)),
        {
            "txt": f"%{txt}%",
            "start": int(start),
            "page_len": int(page_len),
        },
    )


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def contract_beneficiary_query(
    doctype,
    txt,
    searchfield,
    start,
    page_len,
    filters=None,
):
    """Search active contract beneficiaries by name, customer, or employee code."""

    if isinstance(filters, str):
        filters = frappe.parse_json(filters)

    filters = filters or {}
    pharmacy_contract = filters.get("pharmacy_contract") or ""
    txt = (txt or "").strip()

    return frappe.db.sql(
        """
        SELECT
            `tabContract Beneficiary`.name,
            COALESCE(
                NULLIF(`tabCustomer`.customer_name, ''),
                `tabContract Beneficiary`.customer
            ) AS customer_name,
            `tabContract Beneficiary`.employee_code
        FROM `tabContract Beneficiary`
        LEFT JOIN `tabCustomer`
            ON `tabCustomer`.name = `tabContract Beneficiary`.customer
        WHERE
            IFNULL(`tabContract Beneficiary`.is_active, 0) = 1

            AND (
                %(pharmacy_contract)s = ''
                OR `tabContract Beneficiary`.pharmacy_contract = %(pharmacy_contract)s
            )

            AND (
                `tabContract Beneficiary`.name LIKE %(txt)s
                OR IFNULL(`tabCustomer`.customer_name, '') LIKE %(txt)s
                OR IFNULL(`tabContract Beneficiary`.employee_code, '') LIKE %(txt)s
                OR IFNULL(`tabContract Beneficiary`.customer, '') LIKE %(txt)s
            )

            AND (
                `tabContract Beneficiary`.expiry_date IS NULL
                OR `tabContract Beneficiary`.expiry_date >= CURDATE()
            )

            {match_conditions}

        ORDER BY
            `tabCustomer`.customer_name,
            `tabContract Beneficiary`.employee_code,
            `tabContract Beneficiary`.name

        LIMIT %(start)s, %(page_len)s
        """.format(match_conditions=get_match_cond(doctype)),
        {
            "txt": f"%{txt}%",
            "pharmacy_contract": pharmacy_contract,
            "start": int(start),
            "page_len": int(page_len),
        },
    )
