import frappe
from frappe.utils import now_datetime

@frappe.whitelist()
def get_shift_details(cashier):
    # 1. نجيب وقت آخر وردية اتقفلت للكاشير ده عشان منكررش الفواتير
    last_shift = frappe.db.get_all("Pharmacy Shift Closing",
        filters={"cashier": cashier, "docstatus": 1},
        fields=["end_time"],
        order_by="end_time desc",
        limit=1
    )
    last_closed_time = last_shift[0].end_time if last_shift else '2000-01-01'

    # 2. نجيب وقت "أول فاتورة" اتعملت بعد التقفيل اللي فات (عشان تكون دي البداية الحقيقية)
    first_invoice = frappe.db.get_all("Sales Invoice",
        filters={"owner": cashier, "docstatus": 1, "creation": (">", last_closed_time)},
        fields=["creation"],
        order_by="creation asc",
        limit=1
    )

    if not first_invoice:
        return {"status": "no_data"}

    start_time = first_invoice[0].creation
    end_time = now_datetime()

    # 3. نجيب مجاميع طرق الدفع (عشان نملا الجدول الفرعي الجديد)
    sales_data = frappe.db.sql("""
        SELECT 
            sip.mode_of_payment,
            SUM(sip.amount) as total_amount
        FROM `tabSales Invoice Payment` sip
        JOIN `tabSales Invoice` si ON si.name = sip.parent
        WHERE si.docstatus = 1 
          AND si.owner = %s
          AND si.creation BETWEEN %s AND %s
        GROUP BY sip.mode_of_payment
    """, (cashier, start_time, end_time), as_dict=True)

    payment_summary = []
    cash_sales = 0.0

    for data in sales_data:
        payment_summary.append({
            "mode_of_payment": data.mode_of_payment,
            "amount": data.total_amount
        })
        # نعرف الكاش بس عشان ده اللي هيدخل في معادلة الدرج
        mop_type = frappe.db.get_value("Mode of Payment", data.mode_of_payment, "type")
        if mop_type == "Cash":
            cash_sales += data.total_amount

    # 4. التقرير السحري (نجيب كل الفواتير بالتفصيل)
    invoices = frappe.db.sql("""
        SELECT 
            si.name,
            si.creation,
            si.customer_name,
            si.grand_total,
            GROUP_CONCAT(sip.mode_of_payment SEPARATOR ', ') as payment_modes
        FROM `tabSales Invoice` si
        LEFT JOIN `tabSales Invoice Payment` sip ON si.name = sip.parent
        WHERE si.docstatus = 1 
          AND si.owner = %s
          AND si.creation BETWEEN %s AND %s
        GROUP BY si.name
        ORDER BY si.creation ASC
    """, (cashier, start_time, end_time), as_dict=True)

    # بناء كود الـ HTML بتاع التقرير بشكل احترافي وممرر (Scrollable)
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
        time_formatted = inv.creation.strftime("%Y-%m-%d %H:%M") if inv.creation else ""
        html += f"""
                <tr>
                    <td><a href="/app/sales-invoice/{inv.name}" target="_blank"><b>{inv.name}</b></a></td>
                    <td>{time_formatted}</td>
                    <td>{inv.customer_name or 'نقدي'}</td>
                    <td><span class="badge badge-info">{inv.payment_modes or 'غير محدد'}</span></td>
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
        "html_report": html
    }
