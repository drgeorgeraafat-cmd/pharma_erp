frappe.pages["pharmacy-shift-management"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("إدارة الوردية وطرق الدفع"),
        single_column: true,
    });

    new PharmacyShiftManagementV24(page, wrapper);
};


class PharmacyShiftManagementV24 {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$main = page.main
            ? $(page.main)
            : $(wrapper).find(".layout-main-section");
        this.data = null;
        this.selectedShift = "";

        this.addStyles();
        this.page.set_primary_action(
            __("تحديث"),
            () => this.refresh(),
            "refresh",
        );
        this.refresh();
    }

    addStyles() {
        if ($("#psm-v24-style").length) return;

        $("head").append(`
            <style id="psm-v24-style">
                .psm24 { direction: rtl; text-align: right; padding-bottom: 32px; }
                .psm24-actions { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; margin-bottom:16px; }
                .psm24-action { border:1px solid var(--border-color); background:var(--card-bg); border-radius:12px; min-height:74px; font-weight:700; }
                .psm24-section { border:1px solid var(--border-color); background:var(--card-bg); border-radius:14px; padding:16px; margin-bottom:16px; }
                .psm24-section h4 { margin:0 0 14px; }
                .psm24-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }
                .psm24-card { border:1px solid var(--border-color); background:var(--control-bg); border-radius:12px; padding:14px; min-height:94px; }
                .psm24-title { color:var(--text-muted); font-size:12px; }
                .psm24-value { font-size:18px; font-weight:800; margin-top:8px; }
                .psm24-amount { font-size:22px; font-weight:800; margin-top:8px; }
                .psm24-alert { border:1px solid var(--orange-300); background:var(--alert-bg); border-radius:10px; padding:10px 12px; margin-bottom:8px; }
                .psm24-terminal { border:1px solid var(--border-color); border-radius:12px; padding:14px; margin-bottom:10px; }
                .psm24-terminal-head { display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
                .psm24-table { overflow-x:auto; }
                .psm24-table table { min-width:760px; }
                .psm24-good { color:var(--green-600); font-weight:700; }
                .psm24-empty { color:var(--text-muted); text-align:center; padding:24px; }
                .psm24-invoice-link { font-weight:700; cursor:pointer; }
                .psm24-report-tabs { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:14px; }
                .psm24-report-tab { border:1px solid var(--border-color); background:var(--control-bg); border-radius:999px; padding:7px 14px; font-weight:700; }
                .psm24-report-tab.active { background:var(--primary); color:#fff; border-color:var(--primary); }
                .psm24-report-summary { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; margin-bottom:16px; }
                .psm24-report-stat { border:1px solid var(--border-color); background:var(--control-bg); border-radius:10px; padding:10px; }
                .psm24-report-stat strong { display:block; font-size:18px; margin-top:4px; }
                .psm24-source-note { font-size:11px; color:var(--text-muted); margin-top:3px; }
                .psm29-review-banner { border:1px solid #f0ad4e; background:#fff8e8; border-radius:12px; padding:14px; margin-bottom:16px; }
                .psm29-review-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:10px; }
                .psm29-review-item { border:1px solid var(--border-color); background:var(--control-bg); border-radius:12px; padding:12px; }
                .psm29-review-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
            </style>
        `);
    }

    async refresh() {
        frappe.dom.freeze(__("جاري تحميل الوردية..."));

        try {
            const response = await frappe.call({
                method:
                    "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.get_dashboard",
                args: {
                    shift_name: this.selectedShift || "",
                },
            });

            this.data = response.message || {};
            this.render();
        } catch (error) {
            console.error(error);
            this.$main.html(`
                <div class="psm24">
                    <div class="psm24-section">
                        <h4>${__("تعذر تحميل الصفحة")}</h4>
                        <div class="text-danger">
                            ${frappe.utils.escape_html(
                                error?.message || __("Server Error"),
                            )}
                        </div>
                    </div>
                </div>
            `);
        } finally {
            frappe.dom.unfreeze();
        }
    }

    render() {
        if (!this.data.has_open_shift) {
            this.renderNoShift();
            return;
        }

        const shift = this.data.shift;
        const cash = this.data.cash;

        this.$main.html(`
            <div class="psm24">
                ${shift.is_under_review ? `
                    <div class="psm29-review-banner">
                        <strong>هذه الوردية مجمدة وتحت المراجعة.</strong>
                        لا تستقبل مبيعات جديدة. تم عدّ النقدية وعزلها فعليًا فقط،
                        ولم يتم ترحيل أرصدة الوردية محاسبيًا بعد. أكمل مراجعة
                        الطيارين ووسائل الدفع والفيزا ثم اعتمد الترحيل النهائي.
                        ${this.data.active_shift ? `
                            <div class="psm29-review-actions">
                                <button class="btn btn-default psm29-show-active-shift">
                                    العودة للوردية النشطة ${frappe.utils.escape_html(this.data.active_shift)}
                                </button>
                            </div>
                        ` : ""}
                    </div>
                ` : ""}

                <div class="psm24-actions">
                    ${this.action("📊", __("مراجعة المبيعات"), "review-sales")}
                    ${!shift.is_under_review ? this.action("💵", __("دخول نقدية"), "cash-in") : ""}
                    ${!shift.is_under_review ? this.action("💸", __("خروج نقدية"), "cash-out") : ""}
                    ${!shift.is_under_review ? this.action("👤", __("صرف سلفة موظف"), "employee-advance") : ""}
                    ${this.action("💳", __("تقفيل ماكينة فيزا"), "close-terminal")}
                    ${this.action("🏦", __("تسوية بنك الفيزا"), "bank-settlement")}
                    ${this.action("🛵", __("تسوية عهدة طيار"), "delivery-settlement")}
                    ${!shift.is_under_review ? this.action("⏸️", __("تجميد الوردية وفتح وردية جديدة"), "rollover-shift") : ""}
                    ${this.action("✅", __("مراجعة وإغلاق الوردية"), "close-shift")}
                </div>

                <div class="psm24-section">
                    <div class="psm24-grid">
                        ${this.infoCard(__("رقم الوردية"), shift.name)}
                        ${this.infoCard(__("الكاشير"), shift.cashier || "-")}
                        ${this.infoCard(
                            __("وقت البداية"),
                            shift.start_time
                                ? frappe.datetime.str_to_user(shift.start_time)
                                : "-",
                        )}
                        ${this.moneyCard(__("عهدة بداية الوردية"), shift.opening_balance)}
                        ${this.infoCard(__("حركة العهدة"), shift.opening_cash_movement || "-")}
                        ${this.moneyCard(
                            shift.is_under_review
                                ? __("النقدية المعدودة والمعزولة")
                                : __("النقدية المتوقعة"),
                            shift.is_under_review
                                ? shift.review_actual_cash
                                : cash.expected_cash,
                        )}
                    </div>
                </div>

                ${shift.is_under_review ? `
                    <div class="psm24-section">
                        <h4>بيانات تجميد ومراجعة الوردية</h4>
                        <div class="psm24-grid">
                            ${this.moneyCard("النقدية المتوقعة وقت التجميد", shift.review_expected_cash || 0)}
                            ${this.infoCard("العد الفعلي", "يتم عند الاعتماد النهائي")}
                            ${this.infoCard("قرار العجز أو الزيادة", "لم يُحدد بعد")}
                            ${this.moneyCard("عهدة الوردية الجديدة", shift.rollover_new_opening_balance || 0)}
                            ${this.infoCard("الوردية الجديدة", shift.rollover_new_shift || this.data.active_shift || "-")}
                            ${this.infoCard("وقت توقف المبيعات", shift.cutoff_time ? frappe.datetime.str_to_user(shift.cutoff_time) : "-")}
                        </div>
                        <div class="alert alert-info mt-3 mb-0">
                            لم يتم تحويل نقدية هذه الوردية إلى Main Safe ولم يتم ترحيل
                            Insta Pay أو Wallet أو متحصلات الطيارين. كل القيود النهائية
                            تُنشأ معًا عند الضغط على اعتماد وترحيل وإغلاق.
                        </div>
                    </div>
                ` : ""}

                ${this.renderUnderReviewShifts(this.data.under_review_shifts || [], shift.name)}
                ${this.renderPaymentSummary(this.data.payment_summary || [])}
                ${this.renderElectronicReview()}
                ${this.renderDeliveryDrivers(this.data.delivery_drivers || [])}
                ${this.renderTerminals(this.data.terminals || [])}
                ${this.renderPendingBank(this.data.pending_bank_batches || [])}
                ${this.renderBlockers(this.data.blockers || [])}
            </div>
        `);

        this.bindEvents();
    }

    renderNoShift() {
        this.$main.html(`
            <div class="psm24">
                <div class="psm24-section">
                    <h4>${__("فتح وردية جديدة")}</h4>
                    <div class="form-group" style="max-width:320px">
                        <label>${__("رصيد أول الوردية")}</label>
                        <input
                            class="form-control psm24-opening"
                            type="number"
                            min="0"
                            step="0.01"
                            value="0"
                        >
                    </div>
                    <button class="btn btn-primary psm24-create-shift">
                        ${__("فتح الوردية")}
                    </button>
                </div>
                ${this.renderUnderReviewShifts(this.data.under_review_shifts || [], "")}
            </div>
        `);

        this.$main
            .off(".psm24")
            .on("click.psm24", ".psm24-create-shift", () => {
                this.createShift();
            })
            .on("click.psm24", ".psm29-open-review-shift", (event) => {
                this.selectedShift = $(event.currentTarget).attr("data-shift") || "";
                this.refresh();
            });
    }

    action(icon, label, action) {
        return `
            <button class="psm24-action" data-action="${action}">
                <div style="font-size:24px">${icon}</div>
                <div>${label}</div>
            </button>
        `;
    }

    infoCard(label, value) {
        return `
            <div class="psm24-card">
                <div class="psm24-title">${label}</div>
                <div class="psm24-value">
                    ${frappe.utils.escape_html(String(value || "-"))}
                </div>
            </div>
        `;
    }

    moneyCard(label, amount, count = null) {
        return `
            <div class="psm24-card">
                <div class="psm24-title">${label}</div>
                <div class="psm24-amount">
                    ${format_currency(flt(amount), "EGP")}
                </div>
                ${
                    count === null
                        ? ""
                        : `<div class="small text-muted">${count} ${__("عملية")}</div>`
                }
            </div>
        `;
    }

    renderUnderReviewShifts(rows, currentShift = "") {
        const visible = (rows || []).filter(
            (row) => row.name !== currentShift,
        );

        if (!visible.length) return "";

        return `
            <div class="psm24-section">
                <h4>ورديات تحت المراجعة</h4>
                <div class="psm29-review-list">
                    ${visible.map((row) => `
                        <div class="psm29-review-item">
                            <strong>${frappe.utils.escape_html(row.name)}</strong>
                            <div class="small text-muted mt-1">
                                الكاشير: ${frappe.utils.escape_html(row.cashier || "-")}
                            </div>
                            <div class="small text-muted">
                                توقف المبيعات: ${row.cutoff_time ? frappe.datetime.str_to_user(row.cutoff_time) : "-"}
                            </div>
                            <div class="small text-muted">
                                المتوقع: ${format_currency(flt(row.expected_cash), "EGP")}
                            </div>
                            <div class="small text-muted">
                                المعدود والمعزول: ${format_currency(flt(row.actual_cash), "EGP")}
                            </div>
                            <div class="small ${Math.abs(flt(row.difference)) > 0.01 ? "text-danger" : "text-muted"}">
                                الفرق: ${format_currency(flt(row.difference), "EGP")}
                            </div>
                            <div class="small text-muted">
                                مرجع الحفظ: ${frappe.utils.escape_html(row.cash_reference || "-")}
                            </div>
                            <div class="psm29-review-actions">
                                <button class="btn btn-sm btn-primary psm29-open-review-shift" data-shift="${row.name}">
                                    فتح المراجعة
                                </button>
                            </div>
                        </div>
                    `).join("")}
                </div>
            </div>
        `;
    }

    renderPaymentSummary(rows) {
        const cards = rows.map((row) =>
            this.moneyCard(
                row.mode_of_payment,
                row.amount,
                row.transaction_count,
            ),
        );

        return `
            <div class="psm24-section">
                <h4>${__("مبيعات الوردية حسب طريقة الدفع")}</h4>
                <div class="psm24-grid">
                    ${
                        cards.length
                            ? cards.join("")
                            : `<div class="psm24-empty">${__("لا توجد مبيعات")}</div>`
                    }
                </div>
            </div>
        `;
    }

    paymentAmount(mode) {
        return flt(
            (this.data.payment_summary || []).find(
                (row) => row.mode_of_payment === mode,
            )?.amount || 0,
        );
    }

    reconciliation(mode) {
        return (this.data.reconciliations || []).find(
            (row) =>
                row.mode_of_payment === mode &&
                row.docstatus === 1,
        );
    }

    renderElectronicReview() {
        const modes = ["Insta Pay", "Wallet"];

        return `
            <div class="psm24-section">
                <h4>${__("مراجعة وسائل الدفع الإلكترونية")}</h4>
                <div class="psm24-grid">
                    ${modes
                        .map((mode) => {
                            const amount = this.paymentAmount(mode);
                            const reconciliation = this.reconciliation(mode);

                            return `
                                <div class="psm24-card">
                                    <div class="psm24-title">${mode}</div>
                                    <div class="psm24-amount">
                                        ${format_currency(amount, "EGP")}
                                    </div>
                                    <div class="mt-2">
                                        ${
                                            reconciliation
                                                ? `<span class="psm24-good">${__("تمت المراجعة — الترحيل عند الاعتماد النهائي")}</span>`
                                                : amount
                                                  ? `<button class="btn btn-sm btn-primary psm24-reconcile-mode" data-mode="${mode}" data-amount="${amount}">${__("تم التسليم")}</button>`
                                                  : `<span class="text-muted">${__("لا توجد عمليات")}</span>`
                                        }
                                    </div>
                                </div>
                            `;
                        })
                        .join("")}
                </div>
            </div>
        `;
    }

    renderDeliveryDrivers(rows) {
        const activeRows = (rows || []).filter((row) => {
            const outsideOrders = row.outside_orders || [];
            const activeOrders = row.active_orders || [];
            return (
                flt(row.expected_amount) > 0
                || flt(row.remaining_amount) > 0
                || outsideOrders.length > 0
                || activeOrders.length > 0
            );
        });

        return `
            <div class="psm24-section">
                <h4>${__("متحصلات وعهد الطيارين")}</h4>
                ${
                    activeRows.length
                        ? `<div class="psm24-table">
                            <table class="table table-bordered">
                                <thead>
                                    <tr>
                                        <th>${__("الطيار")}</th>
                                        <th>${__("المطلوب")}</th>
                                        <th>${__("تم استلامه")}</th>
                                        <th>${__("المتبقي")}</th>
                                        <th>${__("الحالة")}</th>
                                        <th>${__("الإجراء")}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${activeRows
                                        .map(
                                            (row) => `
                                                <tr>
                                                    <td>
                                                        <strong>${frappe.utils.escape_html(
                                                            row.employee_name || row.delivery_boy,
                                                        )}</strong>
                                                        <div class="small text-muted">
                                                            ${frappe.utils.escape_html(row.delivery_boy)}
                                                        </div>
                                                    </td>
                                                    <td>${format_currency(flt(row.expected_amount), "EGP")}</td>
                                                    <td>${format_currency(flt(row.handed_over_amount), "EGP")}</td>
                                                    <td>${format_currency(flt(row.remaining_amount), "EGP")}</td>
                                                    <td>
                                                        ${
                                                            row.final_submitted
                                                                ? row.shortage_amount > 0
                                                                    ? `<span class="text-danger">${__("تقفيل نهائي بعجز")}</span>`
                                                                    : `<span class="psm24-good">${__("تم التقفيل النهائي")}</span>`
                                                                : !cint(row.can_receive_handover)
                                                                    ? `
                                                                        <span class="text-warning">${__("الطيار خارج الصيدلية")}</span>
                                                                        ${(row.outside_orders || []).length ? `
                                                                            <div class="small text-muted mt-1">
                                                                                ${(row.outside_orders || []).map((order) => `${frappe.utils.escape_html(order.name || "")} — ${frappe.utils.escape_html(order.status || "")}`).join("<br>")}
                                                                            </div>
                                                                        ` : ""}
                                                                    `
                                                                    : (row.active_orders || []).length
                                                                        ? `<span class="text-warning">${__("لديه أوردرات نشطة")}</span>`
                                                                        : row.handed_over_amount > 0
                                                                            ? __("تسليم جزئي")
                                                                            : __("لم يتم الاستلام")
                                                        }
                                                    </td>
                                                    <td>
                                                        ${
                                                            row.final_submitted
                                                                ? row.shortage
                                                                    ? `<a href="#" class="psm24-open-doc" data-doctype="Driver Shortage" data-name="${row.shortage}">${row.shortage}</a>`
                                                                    : "—"
                                                                : !cint(row.can_receive_handover)
                                                                    ? `<button class="btn btn-sm btn-warning psm22-open-delivery-orders" data-driver="${row.delivery_boy}">${__("عرض الأوردرات النشطة")}</button>`
                                                                    : flt(row.remaining_amount) > 0.01
                                                                        ? `<button class="btn btn-sm btn-primary psm28-driver-handover" data-driver="${row.delivery_boy}">${__("استلام من الطيار")}</button>`
                                                                        : (row.active_orders || []).length
                                                                            ? `<button class="btn btn-sm btn-warning psm22-open-delivery-orders" data-driver="${row.delivery_boy}">${__("عرض الأوردرات النشطة")}</button>`
                                                                            : `<button class="btn btn-sm btn-default" disabled>${__("لا توجد نقدية معلقة")}</button>`
                                                        }
                                                    </td>
                                                </tr>
                                            `,
                                        )
                                        .join("")}
                                </tbody>
                            </table>
                        </div>`
                        : `<div class="psm24-empty">${__("لا توجد متحصلات نقدية مع الطيارين في هذه الوردية")}</div>`
                }
            </div>
        `;
    }

    async showDeliveryHandoverDialog(selectedDriver = "") {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.get_delivery_handover_summary",
            args: {
                shift_name: this.data.shift.name,
            },
            freeze: true,
        });

        const allRows = response.message || [];
        const selectedOutside = selectedDriver
            ? allRows.find((row) => row.delivery_boy === selectedDriver && !cint(row.can_receive_handover))
            : null;
        if (selectedOutside) {
            const outsideOrders = selectedOutside.outside_orders || [];
            frappe.msgprint({
                title: __("لا يمكن استلام العهدة الآن"),
                indicator: "orange",
                message: `
                    ${__("الطيار لم يسجل الرجوع للصيدلية بعد.")}
                    ${outsideOrders.length ? `<ul class="mt-2">${outsideOrders.map((row) => `<li><strong>${frappe.utils.escape_html(row.name || "")}</strong> — ${frappe.utils.escape_html(row.status || "")}</li>`).join("")}</ul>` : ""}
                `,
            });
            return;
        }

        const rows = allRows.filter((row) => {
            if (cint(row.final_submitted)) return false;
            if (!cint(row.can_receive_handover)) return false;
            const remaining = flt(row.remaining_amount);
            const activeOrders = row.active_orders || [];
            return (
                remaining > 0.01 ||
                (flt(row.expected_amount) > 0.01 && activeOrders.length === 0)
            );
        });

        if (!rows.length) {
            const operationalRows = allRows.filter((row) =>
                (row.outside_orders || []).length || (row.active_orders || []).length
            );
            if (operationalRows.length) {
                const details = operationalRows.map((row) => {
                    const orders = (row.outside_orders || row.active_orders || [])
                        .map((order) => `<li><strong>${frappe.utils.escape_html(order.name || "")}</strong> — ${frappe.utils.escape_html(order.status || "")}</li>`)
                        .join("");
                    return `<div class="mb-3"><strong>${frappe.utils.escape_html(row.employee_name || row.delivery_boy || "")}</strong><ul class="mt-1">${orders}</ul></div>`;
                }).join("");
                frappe.msgprint({
                    title: __("لا توجد نقدية معلقة — توجد أوردرات تشغيلية"),
                    indicator: "orange",
                    message: `${__("لا يوجد مبلغ جديد لاستلامه من الطيارين، لكن توجد أوردرات ما زالت تمنع الإغلاق حتى يتم تسليمها أو إرجاعها وتسجيل رجوع الطيار.")}<div class="mt-3">${details}</div>`
                });
            } else {
                frappe.msgprint(__("لا توجد متحصلات نقدية معلقة مع الطيارين."));
            }
            return;
        }

        const options = rows.map((row) => row.delivery_boy).join("\n");
        const defaultDriver =
            selectedDriver && rows.some((row) => row.delivery_boy === selectedDriver)
                ? selectedDriver
                : rows[0].delivery_boy;

        let dialog;
        const getDriver = () =>
            rows.find(
                (row) => row.delivery_boy === dialog.get_value("delivery_boy"),
            ) || rows[0];

        const syncDriver = () => {
            const row = getDriver();
            const activeOrders = row.active_orders || [];
            const hasActiveOrders = activeOrders.length > 0;

            dialog.set_value(
                "employee_name",
                row.employee_name || row.delivery_boy,
            );
            dialog.set_value(
                "expected_amount",
                flt(row.expected_amount),
            );
            dialog.set_value(
                "already_handed_over",
                flt(row.handed_over_amount),
            );
            dialog.set_value(
                "remaining_amount",
                flt(row.remaining_amount),
            );
            dialog.set_value(
                "amount",
                flt(row.remaining_amount),
            );

            const handoverField = dialog.get_field(
                "handover_type",
            );
            if (hasActiveOrders) {
                dialog.set_value(
                    "handover_type",
                    "Partial Handover",
                );
                handoverField.df.read_only = 1;
            } else {
                handoverField.df.read_only = 0;
                dialog.set_value(
                    "handover_type",
                    "Final Settlement",
                );
            }
            handoverField.refresh();

            const orderRows = activeOrders
                .map(
                    (order) => `
                        <li>
                            <strong>${frappe.utils.escape_html(order.name)}</strong>
                            — ${frappe.utils.escape_html(order.status || "")}
                            — ${format_currency(flt(order.grand_total), "EGP")}
                        </li>
                    `,
                )
                .join("");

            dialog
                .get_field("active_orders")
                .$wrapper.html(
                    hasActiveOrders
                        ? `
                            <div class="alert alert-warning">
                                <strong>${__("لا يمكن عمل تقفيل نهائي الآن.")}</strong>
                                <br>${__("الطيار لديه أوردرات دليفري نشطة، لذلك سيتم تسجيل الاستلام كتسليم جزئي:")}
                                <ul class="mt-2 mb-0">${orderRows}</ul>
                            </div>
                        `
                        : `
                            <div class="alert alert-success">
                                ${__("لا توجد أوردرات نشطة مع الطيار، ويمكن تنفيذ التقفيل النهائي.")}
                            </div>
                        `,
                );
        };

        dialog = new frappe.ui.Dialog({
            title: __("استلام متحصلات من الطيار"),
            fields: [
                {
                    label: __("الطيار"),
                    fieldname: "delivery_boy",
                    fieldtype: "Select",
                    options,
                    default: defaultDriver,
                    reqd: 1,
                    onchange: syncDriver,
                },
                {
                    label: __("اسم الطيار"),
                    fieldname: "employee_name",
                    fieldtype: "Data",
                    read_only: 1,
                },
                {
                    label: __("المبلغ المطلوب"),
                    fieldname: "expected_amount",
                    fieldtype: "Currency",
                    read_only: 1,
                },
                {
                    label: __("تم استلامه سابقًا"),
                    fieldname: "already_handed_over",
                    fieldtype: "Currency",
                    read_only: 1,
                },
                {
                    label: __("المتبقي مع الطيار"),
                    fieldname: "remaining_amount",
                    fieldtype: "Currency",
                    read_only: 1,
                },
                {
                    label: __("المبلغ المحصل الآن"),
                    fieldname: "amount",
                    fieldtype: "Currency",
                    reqd: 1,
                },
                {
                    fieldname: "active_orders",
                    fieldtype: "HTML",
                },
                {
                    label: __("نوع الاستلام"),
                    fieldname: "handover_type",
                    fieldtype: "Select",
                    options: "Partial Handover\nFinal Settlement",
                    default: "Final Settlement",
                    reqd: 1,
                },
                {
                    label: __("سبب الفرق / الملاحظات"),
                    fieldname: "notes",
                    fieldtype: "Small Text",
                },
                {
                    fieldname: "help",
                    fieldtype: "HTML",
                    options: `
                        <div class="alert alert-info">
                            • التسليم الجزئي يترك الباقي مع الطيار ويمكنه مواصلة العمل.<br>
                            • التقفيل النهائي يحول أي فرق ناقص إلى Driver Shortage تلقائيًا.<br>
                            • لا يمكن إغلاق الوردية قبل التقفيل النهائي لكل طيار لديه متحصلات.
                        </div>
                    `,
                },
            ],
            primary_action_label: __("تأكيد الاستلام"),
            primary_action: async (values) => {
                const remaining = flt(dialog.get_value("remaining_amount"));
                const amount = flt(values.amount);

                if (amount < 0 || amount > remaining + 0.01) {
                    frappe.throw(__("المبلغ المحصل غير صحيح."));
                }

                if (
                    values.handover_type === "Final Settlement" &&
                    amount < remaining - 0.01 &&
                    !String(values.notes || "").trim()
                ) {
                    frappe.throw(__("اكتب سبب الفرق قبل التقفيل النهائي."));
                }

                const result = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.submit_delivery_handover",
                    args: {
                        shift_name: this.data.shift.name,
                        delivery_boy: values.delivery_boy,
                        handover_type: values.handover_type,
                        amount: values.amount,
                        notes: values.notes || "",
                    },
                    freeze: true,
                    freeze_message: __("جاري تسجيل الاستلام وإنشاء القيود..."),
                });

                dialog.hide();
                const data = result.message || {};

                frappe.msgprint({
                    title: __("تم استلام متحصلات الطيار"),
                    indicator: data.shortage ? "orange" : "green",
                    message: `
                        ${__("Delivery Settlement")}: ${frappe.utils.escape_html(data.settlement || "-")}<br>
                        ${__("Delivery Handover")}: ${frappe.utils.escape_html(data.handover || "-")}<br>
                        ${__("المبلغ المسلم")}: ${format_currency(flt(values.amount), "EGP")}
                        ${
                            cint(data.forced_partial)
                                ? `<br><span class="text-warning">${__("تم تحويل العملية تلقائيًا إلى تسليم جزئي لأن الطيار لديه أوردرات نشطة.")}</span>`
                                : ""
                        }
                        ${
                            data.shortage
                                ? `<br>${__("تم تسجيل عجز")}: ${format_currency(flt(data.shortage_amount), "EGP")} — ${frappe.utils.escape_html(data.shortage)}`
                                : ""
                        }
                    `,
                });

                await this.refresh();
            },
        });

        dialog.show();
        syncDriver();
    }

    renderTerminals(terminals) {
        const content = terminals
            .map((terminal) => {
                return `
                    <div class="psm24-terminal">
                        <div class="psm24-terminal-head">
                            <div>
                                <strong>${frappe.utils.escape_html(
                                    terminal.terminal_name,
                                )}</strong>
                                — ${frappe.utils.escape_html(
                                    terminal.bank_label || "",
                                )}
                            </div>
                            <button
                                class="btn btn-sm btn-primary psm24-close-terminal"
                                data-terminal="${terminal.name}"
                                data-total="${flt(terminal.unbatched_total)}"
                            >
                                ${__("تقفيل الماكينة")}
                            </button>
                        </div>

                        <div class="psm24-grid">
                            ${this.moneyCard(
                                __("عمليات غير مقفلة"),
                                terminal.unbatched_total,
                                terminal.unbatched_count,
                            )}
                            ${this.infoCard(
                                __("الحساب الوسيط"),
                                terminal.clearing_account,
                            )}
                            ${this.infoCard(
                                __("الحساب البنكي"),
                                terminal.destination_bank_account,
                            )}
                        </div>

                        ${
                            terminal.batches?.length
                                ? this.batchTable(terminal.batches)
                                : `<div class="text-muted mt-3">${__("لا توجد تقفيلات لهذه الماكينة في الوردية")}</div>`
                        }
                    </div>
                `;
            })
            .join("");

        return `
            <div class="psm24-section">
                <h4>${__("ماكينات الفيزا وتقفيلاتها")}</h4>
                ${
                    content ||
                    `<div class="psm24-empty">${__("لا توجد ماكينات مفعلة")}</div>`
                }
            </div>
        `;
    }

    batchTable(rows) {
        return `
            <div class="psm24-table mt-3">
                <table class="table table-bordered">
                    <thead>
                        <tr>
                            <th>${__("المستند")}</th>
                            <th>${__("رقم التقفيلة")}</th>
                            <th>${__("النظام")}</th>
                            <th>${__("الماكينة")}</th>
                            <th>${__("الفرق")}</th>
                            <th>${__("الحالة")}</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows
                            .map(
                                (row) => `
                                    <tr>
                                        <td>
                                            <a href="#" class="psm24-open-doc" data-doctype="Card Settlement Batch" data-name="${row.name}">
                                                ${row.name}
                                            </a>
                                        </td>
                                        <td>${frappe.utils.escape_html(
                                            row.batch_number || "-",
                                        )}</td>
                                        <td>${format_currency(
                                            flt(row.system_total),
                                            "EGP",
                                        )}</td>
                                        <td>${format_currency(
                                            flt(row.machine_total),
                                            "EGP",
                                        )}</td>
                                        <td>${format_currency(
                                            flt(row.difference),
                                            "EGP",
                                        )}</td>
                                        <td>${frappe.utils.escape_html(
                                            row.status || "-",
                                        )}</td>
                                    </tr>
                                `,
                            )
                            .join("")}
                    </tbody>
                </table>
            </div>
        `;
    }

    renderPendingBank(rows) {
        if (!rows.length) {
            return `
                <div class="psm24-section">
                    <h4>${__("تقفيلات تنتظر وصول البنك")}</h4>
                    <div class="psm24-good">${__("لا توجد تقفيلات معلقة")}</div>
                </div>
            `;
        }

        return `
            <div class="psm24-section">
                <h4>${__("تقفيلات تنتظر وصول البنك")}</h4>
                <div class="psm24-table">
                    <table class="table table-bordered">
                        <thead>
                            <tr>
                                <th>${__("المستند")}</th>
                                <th>${__("الماكينة")}</th>
                                <th>${__("رقم التقفيلة")}</th>
                                <th>${__("المتبقي")}</th>
                                <th>${__("الوردية")}</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${rows
                                .map(
                                    (row) => `
                                        <tr>
                                            <td>
                                                <a href="#" class="psm24-open-doc" data-doctype="Card Settlement Batch" data-name="${row.name}">
                                                    ${row.name}
                                                </a>
                                            </td>
                                            <td>${frappe.utils.escape_html(
                                                row.pos_terminal || "",
                                            )}</td>
                                            <td>${frappe.utils.escape_html(
                                                row.batch_number || "-",
                                            )}</td>
                                            <td>${format_currency(
                                                flt(row.outstanding_amount),
                                                "EGP",
                                            )}</td>
                                            <td>${frappe.utils.escape_html(
                                                row.shift_reference || "",
                                            )}</td>
                                        </tr>
                                    `,
                                )
                                .join("")}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    renderBlockers(rows) {
        if (!rows.length) {
            return `
                <div class="psm24-section">
                    <h4>${__("مراجعة إغلاق الوردية")}</h4>
                    <div class="psm24-good">${__("الوردية جاهزة للإغلاق")}</div>
                </div>
            `;
        }

        return `
            <div class="psm24-section">
                <h4>${__("موانع إغلاق الوردية")}</h4>
                ${rows
                    .map(
                        (row) => `
                            <div class="psm24-alert">
                                <strong>${frappe.utils.escape_html(
                                    row.message || "",
                                )}</strong>
                                <div class="small text-muted mt-2">
                                    ${frappe.utils.escape_html(
                                        JSON.stringify(row.rows || []),
                                    )}
                                </div>
                            </div>
                        `,
                    )
                    .join("")}
            </div>
        `;
    }

    bindEvents() {
        this.$main
            .off(".psm24")
            .on("click.psm24", "[data-action='review-sales']", () =>
                this.reviewSales(),
            )
            .on("click.psm24", "[data-action='cash-in']", () =>
                this.showCashInDialog(),
            )
            .on("click.psm24", "[data-action='cash-out']", () =>
                this.showCashOutDialog(),
            )
            .on(
                "click.psm24",
                "[data-action='employee-advance']",
                () => this.showCashOutDialog("Employee Advance"),
            )
            .on("click.psm24", "[data-action='close-terminal']", () =>
                this.chooseTerminal(),
            )
            .on("click.psm24", "[data-action='bank-settlement']", () =>
                this.newBankSettlement(),
            )
            .on(
                "click.psm24",
                "[data-action='delivery-settlement']",
                () => this.showDeliveryHandoverDialog(),
            )
            .on(
                "click.psm24",
                ".psm28-driver-handover",
                (event) => {
                    this.showDeliveryHandoverDialog(
                        $(event.currentTarget).attr("data-driver"),
                    );
                },
            )
            .on("click.psm24", ".psm22-open-delivery-orders", () => {
                frappe.set_route("delivery-management");
            })
            .on("click.psm24", "[data-action='rollover-shift']", () =>
                this.showRolloverDialog(),
            )
            .on("click.psm24", "[data-action='close-shift']", () =>
                this.closeShift(),
            )
            .on("click.psm24", ".psm29-open-review-shift", (event) => {
                this.selectedShift = $(event.currentTarget).attr("data-shift") || "";
                this.refresh();
            })
            .on("click.psm24", ".psm29-show-active-shift", () => {
                this.selectedShift = "";
                this.refresh();
            })
            .on("click.psm24", ".psm24-close-terminal", (event) => {
                const $button = $(event.currentTarget);
                this.closeTerminalDialog(
                    $button.attr("data-terminal"),
                    flt($button.attr("data-total")),
                );
            })
            .on("click.psm24", ".psm24-reconcile-mode", (event) => {
                const $button = $(event.currentTarget);
                this.reconcileMode(
                    $button.attr("data-mode"),
                    flt($button.attr("data-amount")),
                );
            })
            .on("click.psm24", ".psm24-open-doc", (event) => {
                event.preventDefault();
                const $link = $(event.currentTarget);
                frappe.set_route(
                    "Form",
                    $link.attr("data-doctype"),
                    $link.attr("data-name"),
                );
            });
    }

    async showRolloverDialog() {
        const expected = flt(this.data.cash?.expected_cash || 0);
        const transferResponse = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.get_transferable_delivery_orders",
            args: {
                shift_name: this.data.shift.name,
            },
            freeze: true,
            freeze_message: __("جاري فحص أوردرات الدليفري القابلة للترحيل..."),
        });
        const transferable = transferResponse.message || [];

        const transferTableData = transferable.map((row) => ({
            selected: 1,
            invoice: row.invoice,
            customer: row.customer,
            status: row.status || "Draft",
            amount: flt(row.amount),
        }));

        const dialog = new frappe.ui.Dialog({
            title: __("تجميد الوردية وفتح وردية جديدة"),
            size: "extra-large",
            fields: [
                {
                    fieldname: "notice",
                    fieldtype: "HTML",
                    options: `
                        <div class="alert alert-warning">
                            سيتم إيقاف تسجيل المبيعات على الوردية الحالية وفتح وردية جديدة.
                            <br><strong>لن يُطلب عدّ النقدية، ولن يتم إنشاء أي قيد أو قرار فرق للوردية القديمة الآن.</strong>
                            <br>عدّ النقدية ومعالجة العجز أو الزيادة وإنشاء كل قيود الترحيل يتم مرة واحدة عند اعتماد وإغلاق الوردية المعلقة.
                            <br><strong>Sales Shift للفاتورة لا يتغير. الذي ينتقل فقط هو Delivery Shift للأوردرات غير المعيّنة لطيار.</strong>
                        </div>
                    `,
                },
                {
                    label: __("النقدية المتوقعة وقت التجميد"),
                    fieldname: "expected_cash",
                    fieldtype: "Currency",
                    default: expected,
                    read_only: 1,
                    description: __("لقطة مرجعية فقط، وليست عدًا فعليًا أو قيدًا محاسبيًا."),
                },
                {
                    label: __("عهدة بداية الوردية الجديدة"),
                    fieldname: "new_opening_balance",
                    fieldtype: "Currency",
                    default: flt(this.data.shift?.opening_balance || 0),
                    reqd: 1,
                },
                {
                    label: __("الأوردرات غير المعيّنة القابلة للترحيل"),
                    fieldname: "transfer_orders",
                    fieldtype: "Table",
                    cannot_add_rows: true,
                    cannot_delete_rows: true,
                    in_place_edit: true,
                    data: transferTableData,
                    fields: [
                        {
                            label: __("ترحيل"),
                            fieldname: "selected",
                            fieldtype: "Check",
                            in_list_view: 1,
                            columns: 1,
                        },
                        {
                            label: __("الفاتورة"),
                            fieldname: "invoice",
                            fieldtype: "Data",
                            read_only: 1,
                            in_list_view: 1,
                            columns: 2,
                        },
                        {
                            label: __("العميل"),
                            fieldname: "customer",
                            fieldtype: "Data",
                            read_only: 1,
                            in_list_view: 1,
                            columns: 3,
                        },
                        {
                            label: __("الحالة"),
                            fieldname: "status",
                            fieldtype: "Data",
                            read_only: 1,
                            in_list_view: 1,
                            columns: 2,
                        },
                        {
                            label: __("القيمة"),
                            fieldname: "amount",
                            fieldtype: "Currency",
                            read_only: 1,
                            in_list_view: 1,
                            columns: 2,
                        },
                    ],
                    description: transferable.length
                        ? __("المحدد سيتم ربط Delivery Shift الخاص به بالوردية الجديدة. الأوردر المعيّن لطيار أو الموجود في رحلة لا يظهر هنا.")
                        : __("لا توجد أوردرات غير معيّنة قابلة للترحيل."),
                },
                {
                    label: __("سبب الترحيل"),
                    fieldname: "transfer_reason",
                    fieldtype: "Small Text",
                    default: __("Shift rollover - unassigned delivery order"),
                    depends_on: "eval:(doc.transfer_orders || []).some(row => row.selected)",
                },
            ],
            primary_action_label: __("تجميد وفتح وردية جديدة"),
            primary_action: async (values) => {
                const selectedInvoices = (values.transfer_orders || [])
                    .filter((row) => cint(row.selected))
                    .map((row) => row.invoice);

                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.rollover_shift",
                    args: {
                        shift_name: this.data.shift.name,
                        new_opening_balance: values.new_opening_balance,
                        transfer_invoices: JSON.stringify(selectedInvoices),
                        transfer_reason: values.transfer_reason || "",
                    },
                    freeze: true,
                    freeze_message: __("جاري تجميد الوردية وفتح الوردية الجديدة وترحيل الأوردرات..."),
                });

                dialog.hide();
                this.selectedShift = "";
                const transferred =
                    response.message?.delivery_transfers?.transferred || [];
                const skipped = response.message?.delivery_transfers?.skipped || [];

                frappe.msgprint({
                    title: __("تم فتح وردية جديدة"),
                    indicator: skipped.length ? "orange" : "green",
                    message: `
                        الوردية القديمة تحت المراجعة: ${frappe.utils.escape_html(response.message?.under_review_shift || "-")}
                        <br>الوردية الجديدة: ${frappe.utils.escape_html(response.message?.new_shift || "-")}
                        <br>Cash Drawer: ${frappe.utils.escape_html(response.message?.cash_drawer || "-")}
                        <br>النقدية المتوقعة وقت التجميد: ${format_currency(flt(response.message?.expected_cash_snapshot), "EGP")}
                        <br>تم ترحيل ${transferred.length} أوردر إلى Delivery Shift الجديد.
                        ${skipped.length ? `<br><span class="text-warning">تعذر ترحيل ${skipped.length} أوردر لأن حالته تغيّرت أثناء التنفيذ.</span>` : ""}
                        <br><strong>العد الفعلي وكل قيود الوردية القديمة مؤجلة للاعتماد النهائي.</strong>
                    `,
                });

                await this.refresh();
            },
        });

        dialog.show();
        if (transferable.length) {
            dialog.get_field("transfer_orders").grid.refresh();
        }
    }

    async createShift() {
        await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.create_shift",
            args: {
                opening_balance: flt(
                    this.$main.find(".psm24-opening").val(),
                ),
            },
            freeze: true,
        });
        await this.refresh();
    }

    async reviewSales() {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.get_payment_details",
            args: {
                shift_name: this.data.shift.name,
                include_monthly_claims: 1,
            },
            freeze: true,
        });

        const rows = response.message || [];
        const dialog = new frappe.ui.Dialog({
            title: __("تفاصيل مبيعات وتحصيلات الوردية"),
            size: "extra-large",
            fields: [
                {
                    fieldtype: "HTML",
                    fieldname: "report",
                },
            ],
        });

        dialog.show();
        const $wrapper = dialog.get_field("report").$wrapper;

        const tabs = [
            {
                key: "all",
                label: __("الكل"),
                filter: () => true,
            },
            {
                key: "walk_in",
                label: __("الصالة"),
                filter: (row) => row.channel === "Walk In",
            },
            {
                key: "delivery",
                label: __("الدليفري"),
                filter: (row) => row.channel === "Delivery",
            },
            {
                key: "corporate",
                label: __("التعاقدات"),
                filter: (row) => row.channel === "Corporate",
            },
        ];

        const renderTab = (tabKey) => {
            const activeTab =
                tabs.find((tab) => tab.key === tabKey) || tabs[0];
            const filteredRows = rows.filter(activeTab.filter);

            $wrapper.html(
                this.buildShiftPaymentReport(
                    rows,
                    filteredRows,
                    tabs,
                    activeTab.key,
                ),
            );

            $wrapper
                .off("click.psm24report")
                .on(
                    "click.psm24report",
                    ".psm24-report-tab",
                    (event) => {
                        event.preventDefault();
                        renderTab(
                            $(event.currentTarget).attr("data-tab"),
                        );
                    },
                )
                .on(
                    "click.psm24report",
                    ".psm24-invoice-link",
                    (event) => {
                        event.preventDefault();
                        this.showInvoiceItems(
                            $(event.currentTarget).attr("data-invoice"),
                        );
                    },
                );
        };

        renderTab("all");
    }

    buildShiftPaymentReport(
        allRows,
        rows,
        tabs,
        activeTab,
    ) {
        const uniqueInvoices = new Map();
        const collectionSources = new Set();
        let collectedTotal = 0;

        rows.forEach((row) => {
            collectedTotal += flt(row.amount);

            if (
                row.payment_source_key &&
                row.payment_source_type !== "Contract Monthly Claim" &&
                Math.abs(flt(row.amount)) > 0.000001
            ) {
                collectionSources.add(row.payment_source_key);
            }

            if (
                row.sales_invoice &&
                !uniqueInvoices.has(row.sales_invoice)
            ) {
                uniqueInvoices.set(row.sales_invoice, row);
            }
        });

        let invoiceTotal = 0;
        let outstandingTotal = 0;

        uniqueInvoices.forEach((row) => {
            invoiceTotal += flt(row.invoice_total);
            outstandingTotal += flt(row.outstanding_amount);
        });

        const tabHtml = tabs
            .map((tab) => {
                const tabRows = allRows.filter(tab.filter);
                const invoiceCount = new Set(
                    tabRows
                        .map((row) => row.sales_invoice)
                        .filter(Boolean),
                ).size;
                return `
                    <button
                        type="button"
                        class="psm24-report-tab ${
                            tab.key === activeTab ? "active" : ""
                        }"
                        data-tab="${tab.key}"
                    >
                        ${tab.label}
                        <span class="small">(${invoiceCount})</span>
                    </button>
                `;
            })
            .join("");

        const grouped = {};
        rows.forEach((row) => {
            const mode = row.mode_of_payment || __("غير محدد");
            grouped[mode] ||= [];
            grouped[mode].push(row);
        });

        let tables = "";

        Object.keys(grouped)
            .sort()
            .forEach((mode) => {
                const modeRows = grouped[mode];
                const modeTotal = modeRows.reduce(
                    (sum, row) => sum + flt(row.amount),
                    0,
                );

                tables += `
                    <h4 class="mt-4">${frappe.utils.escape_html(mode)}</h4>
                    <div class="psm24-table">
                        <table class="table table-bordered">
                            <thead>
                                <tr>
                                    <th>${__("الفاتورة")}</th>
                                    <th>${__("العميل")}</th>
                                    <th>${__("القناة")}</th>
                                    <th>${__("مصدر التحصيل")}</th>
                                    <th>${__("الطيار / نوع التعاقد")}</th>
                                    <th>${__("الماكينة")}</th>
                                    <th>${__("قيمة الفاتورة")}</th>
                                    <th>${__("المحصل")}</th>
                                    <th>${__("المتبقي")}</th>
                                    <th>${__("المرجع")}</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${modeRows
                                    .map((row) =>
                                        this.shiftPaymentReportRow(row),
                                    )
                                    .join("")}
                                <tr>
                                    <td colspan="7">
                                        <strong>${__("إجمالي المحصل بطريقة الدفع")}</strong>
                                    </td>
                                    <td>
                                        <strong>${format_currency(
                                            modeTotal,
                                            "EGP",
                                        )}</strong>
                                    </td>
                                    <td colspan="2"></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                `;
            });

        return `
            <div class="psm24-report-tabs">
                ${tabHtml}
            </div>

            <div class="psm24-report-summary">
                <div class="psm24-report-stat">
                    ${__("عدد الفواتير")}
                    <strong>${uniqueInvoices.size}</strong>
                </div>
                <div class="psm24-report-stat">
                    ${__("عدد عمليات التحصيل")}
                    <strong>${collectionSources.size}</strong>
                </div>
                <div class="psm24-report-stat">
                    ${__("إجمالي قيمة الفواتير")}
                    <strong>${format_currency(invoiceTotal, "EGP")}</strong>
                </div>
                <div class="psm24-report-stat">
                    ${__("إجمالي المحصل")}
                    <strong>${format_currency(collectedTotal, "EGP")}</strong>
                </div>
                <div class="psm24-report-stat">
                    ${__("إجمالي المتبقي")}
                    <strong>${format_currency(outstandingTotal, "EGP")}</strong>
                </div>
            </div>

            ${
                tables ||
                `<div class="psm24-empty">${__("لا توجد عمليات في هذا التبويب")}</div>`
            }
        `;
    }

    shiftPaymentReportRow(row) {
        const channelLabels = {
            "Walk In": __("الصالة"),
            Delivery: __("الدليفري"),
            Corporate: __("التعاقدات"),
        };

        let sourceLabel = row.payment_source_type || "—";
        if (row.payment_source_type === "Sales Invoice Payment") {
            sourceLabel = __("دفع مباشر POS");
        } else if (row.payment_source_type === "Payment Entry") {
            sourceLabel = __("Payment Entry");
        } else if (
            row.payment_source_type === "Contract Monthly Claim"
        ) {
            sourceLabel = __("مطالبة شهرية آجلة");
        }

        let operationalInfo = "—";
        if (row.channel === "Delivery") {
            operationalInfo = [
                row.delivery_boy || "",
                row.collection_received_by || "",
            ]
                .filter(Boolean)
                .join(" / ") || "—";
        } else if (row.channel === "Corporate") {
            operationalInfo = row.contract_billing_type || "—";
        }

        const sourceReference = [
            row.payment_entry || "",
            row.reference_no || "",
        ]
            .filter(Boolean)
            .join(" / ") || "—";

        return `
            <tr>
                <td>
                    <a
                        href="#"
                        class="psm24-invoice-link"
                        data-invoice="${frappe.utils.escape_html(
                            row.sales_invoice || "",
                        )}"
                    >
                        ${frappe.utils.escape_html(
                            row.sales_invoice || "—",
                        )}
                    </a>
                    <div class="psm24-source-note">
                        ${frappe.utils.escape_html(
                            row.payment_status || "",
                        )}
                    </div>
                </td>
                <td>${frappe.utils.escape_html(
                    row.customer_name || row.customer || "",
                )}</td>
                <td>${frappe.utils.escape_html(
                    channelLabels[row.channel] || row.channel || "—",
                )}</td>
                <td>
                    ${frappe.utils.escape_html(sourceLabel)}
                    <div class="psm24-source-note">
                        ${frappe.utils.escape_html(
                            row.transaction_type || "",
                        )}
                    </div>
                </td>
                <td>${frappe.utils.escape_html(operationalInfo)}</td>
                <td>${frappe.utils.escape_html(
                    row.card_pos_terminal || "—",
                )}</td>
                <td>${format_currency(
                    flt(row.invoice_total),
                    "EGP",
                )}</td>
                <td>${format_currency(flt(row.amount), "EGP")}</td>
                <td>${format_currency(
                    flt(row.outstanding_amount),
                    "EGP",
                )}</td>
                <td>${frappe.utils.escape_html(sourceReference)}</td>
            </tr>
        `;
    }

    async showInvoiceItems(invoiceName) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.get_invoice_items",
            args: { invoice_name: invoiceName },
            freeze: true,
        });

        const data = response.message || {};
        const rows = data.items || [];
        const html = `
            <div class="mb-3">
                <strong>${frappe.utils.escape_html(
                    data.invoice || invoiceName,
                )}</strong>
                — ${frappe.utils.escape_html(
                    data.customer_name || data.customer || "",
                )}
            </div>
            <div class="psm24-table">
                <table class="table table-bordered">
                    <thead>
                        <tr>
                            <th>${__("الصنف")}</th>
                            <th>${__("الكمية")}</th>
                            <th>${__("الوحدة")}</th>
                            <th>${__("الباتش")}</th>
                            <th>${__("السعر")}</th>
                            <th>${__("الإجمالي")}</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows
                            .map(
                                (row) => `
                                    <tr>
                                        <td>
                                            <strong>${frappe.utils.escape_html(
                                                row.item_name ||
                                                    row.item_code ||
                                                    "",
                                            )}</strong>
                                            <div class="small text-muted">
                                                ${frappe.utils.escape_html(
                                                    row.item_code || "",
                                                )}
                                            </div>
                                        </td>
                                        <td>${row.qty}</td>
                                        <td>${frappe.utils.escape_html(
                                            row.uom || "",
                                        )}</td>
                                        <td>${frappe.utils.escape_html(
                                            row.batch_no ||
                                                row.serial_and_batch_bundle ||
                                                "-",
                                        )}</td>
                                        <td>${format_currency(
                                            flt(row.rate),
                                            "EGP",
                                        )}</td>
                                        <td>${format_currency(
                                            flt(row.amount),
                                            "EGP",
                                        )}</td>
                                    </tr>
                                `,
                            )
                            .join("")}
                    </tbody>
                </table>
            </div>
            <div class="text-left">
                <strong>${__("إجمالي الفاتورة")}: ${format_currency(
                    flt(data.grand_total),
                    "EGP",
                )}</strong>
            </div>
        `;

        const dialog = new frappe.ui.Dialog({
            title: __("أصناف الفاتورة"),
            size: "large",
            fields: [{ fieldtype: "HTML", fieldname: "items" }],
        });

        dialog.show();
        dialog.get_field("items").$wrapper.html(html);
    }

    showCashInDialog() {
        const dialog = new frappe.ui.Dialog({
            title: __("دخول نقدية للدرج"),
            fields: [
                {
                    label: __("نوع الحركة"),
                    fieldname: "movement_type",
                    fieldtype: "Select",
                    options: "Opening Float\nTill Refill",
                    default: "Till Refill",
                    reqd: 1,
                },
                {
                    label: __("الحساب المصدر"),
                    fieldname: "source_account",
                    fieldtype: "Link",
                    options: "Account",
                    default: "Main Safe - C",
                    reqd: 1,
                },
                {
                    label: __("المبلغ"),
                    fieldname: "amount",
                    fieldtype: "Currency",
                    reqd: 1,
                },
                {
                    label: __("البيان"),
                    fieldname: "description",
                    fieldtype: "Small Text",
                    reqd: 1,
                },
            ],
            primary_action_label: __("تأكيد وإنشاء القيد"),
            primary_action: async (values) => {
                const result = await this.createCashAction({
                    action_type: "Cash In",
                    ...values,
                });
                dialog.hide();
                this.showCreatedResult(result);
            },
        });

        dialog.show();
    }

    showCashOutDialog(defaultType = "") {
        let dialog;

        dialog = new frappe.ui.Dialog({
            title: __("خروج نقدية من الدرج"),
            fields: [
                {
                    label: __("نوع العملية"),
                    fieldname: "action_type",
                    fieldtype: "Select",
                    options:
                        "Employee Advance\nOperating Expense\nSupplier Payment",
                    default: defaultType,
                    reqd: 1,
                },
                {
                    label: __("الموظف"),
                    fieldname: "employee",
                    fieldtype: "Link",
                    options: "Employee",
                    depends_on:
                        'eval:doc.action_type=="Employee Advance"',
                    mandatory_depends_on:
                        'eval:doc.action_type=="Employee Advance"',
                },
                {
                    label: __("غرض السلفة"),
                    fieldname: "purpose",
                    fieldtype: "Small Text",
                    depends_on:
                        'eval:doc.action_type=="Employee Advance"',
                    mandatory_depends_on:
                        'eval:doc.action_type=="Employee Advance"',
                },
                {
                    label: __("طريقة الاسترداد"),
                    fieldname: "recovery_method",
                    fieldtype: "Select",
                    options:
                        "Cash Repayment\nSalary Deduction\nMultiple Installments",
                    default: "Cash Repayment",
                    depends_on:
                        'eval:doc.action_type=="Employee Advance"',
                },
                {
                    label: __("حساب المصروف"),
                    fieldname: "expense_account",
                    fieldtype: "Link",
                    options: "Account",
                    depends_on:
                        'eval:doc.action_type=="Operating Expense"',
                    mandatory_depends_on:
                        'eval:doc.action_type=="Operating Expense"',
                    get_query: () => ({
                        filters: {
                            root_type: "Expense",
                            is_group: 0,
                            company: this.data.shift.company,
                        },
                    }),
                },
                {
                    label: __("المورد / الشركة"),
                    fieldname: "supplier",
                    fieldtype: "Link",
                    options: "Supplier",
                    depends_on:
                        'eval:doc.action_type=="Supplier Payment"',
                    mandatory_depends_on:
                        'eval:doc.action_type=="Supplier Payment"',
                },
                {
                    label: __("فاتورة مشتريات"),
                    fieldname: "purchase_invoice",
                    fieldtype: "Link",
                    options: "Purchase Invoice",
                    depends_on:
                        'eval:doc.action_type=="Supplier Payment"',
                    get_query: () => ({
                        filters: {
                            supplier: dialog.get_value("supplier") || "",
                            docstatus: 1,
                            outstanding_amount: [">", 0],
                        },
                    }),
                },
                {
                    label: __("المبلغ"),
                    fieldname: "amount",
                    fieldtype: "Currency",
                    reqd: 1,
                },
                {
                    label: __("البيان / الملاحظات"),
                    fieldname: "description",
                    fieldtype: "Small Text",
                    reqd: 1,
                },
            ],
            primary_action_label: __("تأكيد وإنشاء القيد"),
            primary_action: async (values) => {
                const result = await this.createCashAction(values);
                dialog.hide();
                this.showCreatedResult(result);
            },
        });

        dialog.show();
    }

    async createCashAction(values) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.create_cash_action",
            args: {
                shift_name: this.data.shift.name,
                ...values,
            },
            freeze: true,
            freeze_message: __("جاري إنشاء المستند والقيد..."),
        });

        await this.refresh();
        return response.message || {};
    }

    showCreatedResult(result) {
        frappe.msgprint({
            title: __("تمت العملية بنجاح"),
            indicator: "green",
            message: `${__("المستند")}: ${frappe.utils.escape_html(
                result.name || "-",
            )}<br>${__("القيد")}: ${frappe.utils.escape_html(
                result.journal_entry || "-",
            )}`,
        });
    }

    chooseTerminal() {
        const active = (this.data.terminals || []).filter(
            (row) => row.unbatched_count > 0,
        );

        if (!active.length) {
            frappe.msgprint(__("لا توجد عمليات فيزا غير مقفلة."));
            return;
        }

        if (active.length === 1) {
            this.closeTerminalDialog(
                active[0].name,
                active[0].unbatched_total,
            );
            return;
        }

        const optionMap = {};
        active.forEach((row) => {
            const label = `${row.name} — ${row.terminal_name || row.name} — ${format_currency(flt(row.unbatched_total), "EGP")}`;
            optionMap[label] = row;
        });

        const dialog = new frappe.ui.Dialog({
            title: __("اختيار ماكينة الفيزا التي سيتم تقفيلها"),
            fields: [
                {
                    label: __("الماكينة"),
                    fieldname: "terminal_label",
                    fieldtype: "Select",
                    options: Object.keys(optionMap).join("\n"),
                    reqd: 1,
                },
            ],
            primary_action_label: __("متابعة"),
            primary_action: (values) => {
                const terminal = optionMap[values.terminal_label];
                dialog.hide();
                this.closeTerminalDialog(
                    terminal.name,
                    terminal.unbatched_total,
                );
            },
        });

        dialog.show();
    }

    closeTerminalDialog(terminal, systemTotal) {
        const dialog = new frappe.ui.Dialog({
            title: __("تقفيل ماكينة فيزا"),
            fields: [
                {
                    label: __("الماكينة"),
                    fieldname: "terminal",
                    fieldtype: "Link",
                    options: "Card POS Terminal",
                    default: terminal,
                    read_only: 1,
                },
                {
                    label: __("إجمالي النظام"),
                    fieldname: "system_total",
                    fieldtype: "Currency",
                    default: systemTotal,
                    read_only: 1,
                },
                {
                    label: __("إجمالي تقرير الماكينة"),
                    fieldname: "machine_total",
                    fieldtype: "Currency",
                    default: systemTotal,
                    reqd: 1,
                },
                {
                    label: __("رقم تقفيلة الماكينة"),
                    fieldname: "batch_number",
                    fieldtype: "Data",
                },
            ],
            primary_action_label: __("إنشاء التقفيلة"),
            primary_action: async (values) => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.create_card_batch",
                    args: {
                        shift_name: this.data.shift.name,
                        pos_terminal: values.terminal,
                        machine_total: values.machine_total,
                        batch_number: values.batch_number || "",
                    },
                    freeze: true,
                });

                dialog.hide();

                const data = response.message || {};

                if (cint(data.submitted)) {
                    frappe.msgprint({
                        title: __("تم تقفيل ماكينة الفيزا"),
                        indicator: "green",
                        message: `
                            ${__("المستند")}: ${frappe.utils.escape_html(data.name || "-")}
                            <br>${__("عدد العمليات")}: ${cint(data.transaction_count)}
                            <br>${__("الإجمالي")}: ${format_currency(flt(data.system_total), "EGP")}
                            <br>${__("تم إنشاء واعتماد التقفيلة في الخلفية.")}
                        `,
                    });
                    await this.refresh();
                    return;
                }

                frappe.msgprint({
                    title: __("تقفيلة تحتاج مراجعة"),
                    indicator: "orange",
                    message: `
                        ${__("يوجد فرق بين إجمالي النظام وتقرير الماكينة.")}
                        <br>${__("المستند")}: ${frappe.utils.escape_html(data.name || "-")}
                        <br>${__("الفرق")}: ${format_currency(flt(data.difference), "EGP")}
                        <br>${__("سيتم فتح المستند لمراجعة الفرق قبل الاعتماد.")}
                    `,
                });

                if (data.name) {
                    frappe.set_route(
                        "Form",
                        "Card Settlement Batch",
                        data.name,
                    );
                }
            },
        });

        dialog.show();
    }

    reconcileMode(mode, amount) {
        const dialog = new frappe.ui.Dialog({
            title: __("تأكيد مراجعة وتسليم {0}", [mode]),
            fields: [
                {
                    fieldname: "notice",
                    fieldtype: "HTML",
                    options: `
                        <div class="alert alert-info">
                            هذا الإجراء يسجل تأكيد المراجعة فقط. لن يتم تحويل الرصيد
                            من الحساب الوسيط إلى الحساب المستلم إلا عند الاعتماد النهائي للوردية.
                        </div>
                    `,
                },
                {
                    label: __("إجمالي النظام"),
                    fieldname: "expected",
                    fieldtype: "Currency",
                    default: amount,
                    read_only: 1,
                },
                {
                    label: __("الإجمالي بعد المراجعة"),
                    fieldname: "reviewed",
                    fieldtype: "Currency",
                    default: amount,
                    reqd: 1,
                },
                {
                    label: __("العمولة"),
                    fieldname: "fee",
                    fieldtype: "Currency",
                    default: 0,
                },
            ],
            primary_action_label: __("حفظ تأكيد المراجعة"),
            primary_action: async (values) => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.create_payment_reconciliation",
                    args: {
                        shift_name: this.data.shift.name,
                        mode_of_payment: mode,
                        reviewed_amount: values.reviewed,
                        fee_amount: values.fee,
                    },
                    freeze: true,
                });

                dialog.hide();

                if (response.message?.name) {
                    frappe.msgprint({
                        title: __("تم حفظ المراجعة"),
                        indicator: "green",
                        message: `
                            ${frappe.utils.escape_html(response.message.name)}
                            <br>سيتم إنشاء القيد عند اعتماد وإغلاق الوردية نهائيًا.
                        `,
                    });
                }

                await this.refresh();
            },
        });

        dialog.show();
    }

    newBankSettlement() {
        const unique = new Map();

        (this.data.terminals || []).forEach((row) => {
            unique.set(
                `${row.clearing_account}|${row.destination_bank_account}`,
                row,
            );
        });

        const only = unique.size === 1 ? [...unique.values()][0] : null;

        frappe.route_options = {
            company: this.data.shift.company,
            settlement_date: frappe.datetime.get_today(),
            destination_bank_account:
                only?.destination_bank_account || "",
            clearing_account: only?.clearing_account || "",
        };
        frappe.new_doc("Card Bank Settlement");
    }

    showCardCloseRequiredDialog(terminals, draftBatches = []) {
        const terminalRows = terminals
            .map(
                (terminal) => `
                    <div class="psm24-terminal" style="margin-bottom:10px">
                        <div class="psm24-terminal-head">
                            <div>
                                <strong>${frappe.utils.escape_html(
                                    terminal.terminal_name,
                                )}</strong>
                                <div class="small text-muted">
                                    ${terminal.unbatched_count} ${__("عملية")}
                                    — ${format_currency(
                                        flt(terminal.unbatched_total),
                                        "EGP",
                                    )}
                                </div>
                            </div>
                            <button
                                class="btn btn-primary btn-sm psm26-close-terminal-now"
                                data-terminal="${terminal.name}"
                                data-total="${flt(terminal.unbatched_total)}"
                            >
                                ${__("تقفيل الماكينة الآن")}
                            </button>
                        </div>
                    </div>
                `,
            )
            .join("");

        const draftRows = draftBatches.length
            ? `
                <div class="alert alert-warning mt-3">
                    <strong>${__("تقفيلات تحتاج Submit")}</strong>
                    <div class="mt-2">
                        ${draftBatches
                            .map(
                                (batch) => `
                                    <a
                                        href="#"
                                        class="psm26-open-draft-batch"
                                        data-name="${batch.name}"
                                        style="display:block"
                                    >
                                        ${batch.name}
                                    </a>
                                `,
                            )
                            .join("")}
                    </div>
                </div>
            `
            : "";

        const dialog = new frappe.ui.Dialog({
            title: __("استكمال تقفيلات الفيزا أولًا"),
            size: "large",
            fields: [
                {
                    fieldname: "message",
                    fieldtype: "HTML",
                },
            ],
        });

        dialog.show();

        const $wrapper = dialog.get_field("message").$wrapper;
        $wrapper.html(`
            <div class="alert alert-info">
                لا يمكن إغلاق الوردية قبل تقفيل كل ماكينة فيزا ومراجعة
                إجمالي النظام مع تقرير الماكينة ثم عمل Submit للـBatch.
                الفلوس ستظل بعد ذلك في الحساب الوسيط حتى وصول البنك.
            </div>
            ${terminalRows}
            ${draftRows}
        `);

        $wrapper
            .off(".psm26")
            .on(
                "click.psm26",
                ".psm26-close-terminal-now",
                (event) => {
                    const $button = $(event.currentTarget);
                    dialog.hide();
                    this.closeTerminalDialog(
                        $button.attr("data-terminal"),
                        flt($button.attr("data-total")),
                    );
                },
            )
            .on(
                "click.psm26",
                ".psm26-open-draft-batch",
                (event) => {
                    event.preventDefault();
                    dialog.hide();
                    frappe.set_route(
                        "Form",
                        "Card Settlement Batch",
                        $(event.currentTarget).attr("data-name"),
                    );
                },
            );
    }

    closeShift() {
        const unbatchedTerminals = (this.data.terminals || []).filter(
            (terminal) => flt(terminal.unbatched_count) > 0,
        );
        const draftBatches = (this.data.terminals || []).flatMap(
            (terminal) =>
                (terminal.batches || []).filter(
                    (batch) => batch.docstatus === 0,
                ),
        );

        if (unbatchedTerminals.length || draftBatches.length) {
            this.showCardCloseRequiredDialog(
                unbatchedTerminals,
                draftBatches,
            );
            return;
        }

        const driverReturnBlocker = (this.data.blockers || []).find(
            (row) => row.code === "DRIVER_NOT_RETURNED",
        );
        if (driverReturnBlocker) {
            const rows = driverReturnBlocker.rows || [];
            frappe.msgprint({
                title: __("الطيار لم يرجع للصيدلية"),
                indicator: "orange",
                message: `
                    ${frappe.utils.escape_html(driverReturnBlocker.message || "")}
                    ${rows.length ? `<div class="mt-3">${rows.map((row) => `
                        <div class="mb-3">
                            <strong>${frappe.utils.escape_html(row.employee_name || row.delivery_boy || "")}</strong>
                            — ${format_currency(flt(row.remaining_amount), "EGP")}
                            ${(row.outside_orders || []).length ? `<ul>${(row.outside_orders || []).map((order) => `<li>${frappe.utils.escape_html(order.name || "")} — ${frappe.utils.escape_html(order.status || "")}</li>`).join("")}</ul>` : ""}
                        </div>
                    `).join("")}</div>` : ""}
                    <div class="alert alert-info mt-2 mb-0">${__("افتح صفحة My Deliveries واضغط رجعت الصيدلية، ثم ارجع لاستلام العهدة.")}</div>
                `,
            });
            return;
        }

        const deliveryOrderBlocker = (this.data.blockers || []).find(
            (row) => row.code === "ACTIVE_DELIVERY_ORDERS",
        );
        if (deliveryOrderBlocker) {
            const rows = deliveryOrderBlocker.rows || [];
            frappe.msgprint({
                title: __("لا يمكن إغلاق الوردية"),
                indicator: "orange",
                message: `
                    ${frappe.utils.escape_html(deliveryOrderBlocker.message || "")}
                    ${
                        rows.length
                            ? `<div class="mt-3"><ul>${rows
                                  .map(
                                      (row) =>
                                          `<li><strong>${frappe.utils.escape_html(row.invoice || "")}</strong> — ${frappe.utils.escape_html(row.status || "Draft")} — ${frappe.utils.escape_html(row.delivery_boy || __("غير معيّن"))}</li>`,
                                  )
                                  .join("")}</ul></div>`
                            : ""
                    }
                `,
            });
            return;
        }

        const driverBlocker = (this.data.blockers || []).find(
            (row) => row.code === "DELIVERY_NOT_SETTLED",
        );
        const pendingDriverCashRows = (driverBlocker?.rows || []).filter(
            (row) => flt(row.remaining_amount) > 0.01,
        );
        if (pendingDriverCashRows.length) {
            this.showDeliveryHandoverDialog();
            return;
        }
        // A driver may have completed all cash handovers through partial
        // receipts while the delivery cycle was still active. In that valid
        // case there is no cash left to receive. Continue to final approval;
        // the server will auto-finalize the fully covered draft settlement.

        const electronicBlocker = (this.data.blockers || []).find(
            (row) => row.code === "MOP_NOT_RECONCILED",
        );
        if (electronicBlocker) {
            frappe.msgprint({
                title: __("تأكيد وسائل الدفع الإلكترونية مطلوب"),
                indicator: "orange",
                message: __("راجع وأكد Insta Pay وWallet قبل الاعتماد النهائي."),
            });
            return;
        }

        const isUnderReview = Boolean(this.data.shift?.is_under_review);
        const expected = isUnderReview
            ? flt(this.data.shift.review_expected_cash)
            : flt(this.data.cash.expected_cash);
        const counted = expected;
        const difference = 0;

        let dialog;
        const fields = [
            {
                fieldname: "approval_note",
                fieldtype: "HTML",
                options: `
                    <div class="alert alert-info">
                        عند الاعتماد النهائي فقط سيتم إنشاء القيود التالية:
                        <br>• توريد نقدية الوردية المعزولة إلى Main Safe.
                        <br>• ترحيل متحصلات الطيارين أو تسجيل عجزهم.
                        <br>• تحويل Insta Pay وWallet من الحسابات الوسيطة.
                        <br>• تسجيل عجز أو زيادة الدرج حسب قرار المراجعة.
                        <br>• الفيزا تظل في Card Clearing حتى وصول تسوية البنك.
                    </div>
                `,
            },
            {
                label: __("النقدية المتوقعة وقت المراجعة"),
                fieldname: "expected_cash",
                fieldtype: "Currency",
                default: expected,
                read_only: 1,
            },
            {
                label: __("النقدية المعدودة والمعزولة"),
                fieldname: "actual_cash",
                fieldtype: "Currency",
                default: counted,
                read_only: 0,
                reqd: 1,
                description: isUnderReview
                    ? __("أدخل العد النهائي الآن؛ لم يتم تسجيل عد عند تجميد الوردية.")
                    : "",
            },
            {
                label: __("فرق النقدية"),
                fieldname: "cash_difference",
                fieldtype: "Currency",
                default: difference,
                read_only: 1,
            },
            {
                label: __("معالجة العجز"),
                fieldname: "difference_resolution",
                fieldtype: "Select",
                options: "Employee Liability\nCompany Expense",
                depends_on: "eval:doc.cash_difference < -0.01",
                mandatory_depends_on: "eval:doc.cash_difference < -0.01",
            },
            {
                label: __("الموظف المسؤول عن العجز"),
                fieldname: "responsible_employee",
                fieldtype: "Link",
                options: "Employee",
                depends_on: 'eval:doc.cash_difference < -0.01 && doc.difference_resolution=="Employee Liability"',
                mandatory_depends_on: 'eval:doc.cash_difference < -0.01 && doc.difference_resolution=="Employee Liability"',
            },
            {
                label: __("سبب الفرق / قرار المراجعة"),
                fieldname: "difference_reason",
                fieldtype: "Small Text",
                depends_on: "eval:Math.abs(doc.cash_difference) > 0.01",
                mandatory_depends_on: "eval:Math.abs(doc.cash_difference) > 0.01",
            },
        ];

        dialog = new frappe.ui.Dialog({
            title: __("اعتماد وترحيل وإغلاق الوردية"),
            size: "large",
            fields,
            primary_action_label: __("اعتماد وترحيل وإغلاق"),
            primary_action: async (values) => {
                const actualCash = flt(values.actual_cash);
                const finalDifference = actualCash - expected;

                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.pharmacy_shift_management.pharmacy_shift_management.close_shift",
                    args: {
                        shift_name: this.data.shift.name,
                        actual_cash: actualCash,
                        difference_resolution:
                            finalDifference < -0.01
                                ? values.difference_resolution
                                : finalDifference > 0.01
                                  ? "Overage Income"
                                  : "No Difference",
                        responsible_employee: values.responsible_employee || "",
                        difference_reason: values.difference_reason || "",
                    },
                    freeze: true,
                    freeze_message: __("جاري اعتماد المراجعة وإنشاء القيود النهائية..."),
                });

                dialog.hide();

                const movements =
                    response.message?.closing_cash_movements || [];
                const differenceEntry =
                    response.message?.difference_entry || {};

                frappe.msgprint({
                    title: __("تم اعتماد وإغلاق الوردية"),
                    indicator: "green",
                    message: `
                        ${frappe.utils.escape_html(response.message?.name || "-")}
                        <br>النقدية الموردة: ${format_currency(flt(response.message?.actual_cash), "EGP")}
                        <br>فرق النقدية: ${format_currency(flt(response.message?.difference), "EGP")}
                        ${differenceEntry.journal_entry ? `<br>قيد الفرق: ${frappe.utils.escape_html(differenceEntry.journal_entry)}` : ""}
                        ${movements.length ? `<br>عدد حركات توريد النقدية: ${movements.length}` : ""}
                    `,
                });

                this.selectedShift = "";
                await this.refresh();
            },
        });

        dialog.show();

        const actualField = dialog.get_field("actual_cash");
        actualField.df.onchange = () => {
            const actualValue = flt(dialog.get_value("actual_cash"));
            dialog.set_value("cash_difference", actualValue - expected);
        };
        actualField.refresh();
    }

}
