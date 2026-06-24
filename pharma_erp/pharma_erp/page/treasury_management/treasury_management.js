frappe.pages["treasury-management"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("إدارة الخزائن والبنوك ووسائل الدفع"),
        single_column: true,
    });

    new TreasuryManagementPageV2(page, wrapper);
};


class TreasuryManagementPageV2 {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$main = page.main
            ? $(page.main)
            : $(wrapper).find(".layout-main-section");

        this.addStyles();
        this.page.set_primary_action(
            __("تحديث البيانات"),
            () => this.refresh(),
            "refresh",
        );
        this.renderLoading();
        this.refresh();
    }

    addStyles() {
        if ($("#treasury-management-v2-style").length) return;

        $("head").append(`
            <style id="treasury-management-v2-style">
                .tmv2 { direction: rtl; text-align: right; padding-bottom: 34px; }
                .tmv2-hero {
                    border: 1px solid var(--border-color);
                    background: linear-gradient(135deg, var(--card-bg), var(--control-bg));
                    border-radius: 16px;
                    padding: 22px;
                    margin-bottom: 16px;
                }
                .tmv2-hero h2 { margin: 0 0 8px; font-weight: 800; }
                .tmv2-hero p { margin: 0; color: var(--text-muted); }
                .tmv2-status {
                    display: inline-flex;
                    align-items: center;
                    gap: 7px;
                    margin-top: 14px;
                    border-radius: 999px;
                    padding: 6px 12px;
                    background: var(--green-100);
                    color: var(--green-700);
                    font-weight: 700;
                }
                .tmv2-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 12px;
                    margin-bottom: 16px;
                }
                .tmv2-card, .tmv2-section {
                    border: 1px solid var(--border-color);
                    background: var(--card-bg);
                    border-radius: 14px;
                }
                .tmv2-card { padding: 16px; min-height: 112px; }
                .tmv2-card-title { color: var(--text-muted); font-size: 12px; }
                .tmv2-card-value { font-size: 25px; font-weight: 800; margin-top: 10px; }
                .tmv2-card-note { color: var(--text-muted); font-size: 11px; margin-top: 5px; }
                .tmv2-section { padding: 16px; margin-bottom: 16px; }
                .tmv2-section h4 { margin: 0 0 12px; font-weight: 800; }
                .tmv2-table-wrap { overflow-x: auto; }
                .tmv2-table { width: 100%; border-collapse: collapse; min-width: 840px; }
                .tmv2-table th, .tmv2-table td {
                    padding: 10px 9px;
                    border-bottom: 1px solid var(--border-color);
                    vertical-align: middle;
                    text-align: right;
                    white-space: nowrap;
                }
                .tmv2-table th { color: var(--text-muted); font-size: 12px; }
                .tmv2-badge {
                    display: inline-flex;
                    align-items: center;
                    padding: 4px 9px;
                    border-radius: 999px;
                    font-weight: 700;
                    font-size: 11px;
                }
                .tmv2-badge-on { background: var(--green-100); color: var(--green-700); }
                .tmv2-badge-off { background: var(--gray-100); color: var(--text-muted); }
                .tmv2-warning {
                    border-color: var(--orange-300);
                    background: var(--orange-50);
                }
                .tmv2-warning-list { margin: 0; padding-right: 20px; }
                .tmv2-warning-list li { margin-bottom: 6px; }
                .tmv2-empty { color: var(--text-muted); padding: 16px 0; }
                .tmv2-loading, .tmv2-error { padding: 32px; text-align: center; }
            </style>
        `);
    }

    renderLoading() {
        this.$main.html(`
            <div class="tmv2">
                <div class="tmv2-section tmv2-loading">
                    ${__("جاري تحميل بيانات الخزائن...")}
                </div>
            </div>
        `);
    }

    async refresh() {
        frappe.dom.freeze(__("جاري تحديث بيانات الخزائن..."));

        try {
            const response = await frappe.call({
                method:
                    "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_overview",
            });

            this.render(response.message || {});
            frappe.show_alert({
                message: __("تم تحديث بيانات الخزائن والبنوك"),
                indicator: "green",
            });
        } catch (error) {
            console.error(error);
            this.$main.html(`
                <div class="tmv2">
                    <div class="tmv2-section tmv2-error">
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

    render(data) {
        this.$main.html(`
            <div class="tmv2">
                <div class="tmv2-hero">
                    <h2>${__("إدارة الخزائن والبنوك ووسائل الدفع")}</h2>
                    <p>
                        ${__("تم اعتماد Cash Drawer الحالي ليكون سجل الخزنة التشغيلية، بدون إنشاء Doctype مكرر.")}
                    </p>
                    <div class="tmv2-status">
                        <span>●</span>
                        ${frappe.utils.escape_html(
                            data.message || __("Page is ready"),
                        )}
                    </div>
                </div>

                <div class="tmv2-grid">
                    ${this.card(__("الشركات"), data.companies, __("Company"))}
                    ${this.card(__("الخزائن التشغيلية"), data.cash_drawers, __("Cash Drawer"))}
                    ${this.card(__("حسابات النقدية"), data.cash_ledger_accounts, __("Asset Cash Accounts"))}
                    ${this.card(__("حسابات البنوك"), data.bank_ledger_accounts, __("Bank Ledger Accounts"))}
                    ${this.card(__("Bank Accounts"), data.bank_accounts, __("ERPNext Bank Account"))}
                    ${this.card(__("ماكينات الفيزا"), data.card_terminals, __("Card POS Terminal"))}
                    ${this.card(__("إعدادات التسوية"), data.clearing_setups, __("Clearing Setup"))}
                </div>

                ${this.renderDrawers(data.drawers || [])}
                ${this.renderWarnings(data.account_warnings || [])}
            </div>
        `);
    }

    renderDrawers(rows) {
        if (!rows.length) {
            return `
                <div class="tmv2-section">
                    <h4>${__("الخزائن التشغيلية")}</h4>
                    <div class="tmv2-empty">
                        ${__("لا توجد خزائن مسجلة حتى الآن.")}
                    </div>
                </div>
            `;
        }

        const body = rows.map((row) => `
            <tr>
                <td>
                    <a href="/app/cash-drawer/${encodeURIComponent(row.name)}">
                        ${this.esc(row.drawer_name || row.name)}
                    </a>
                </td>
                <td>${this.esc(row.drawer_code || "-")}</td>
                <td>${this.esc(row.company || "-")}</td>
                <td>${this.esc(row.branch || "-")}</td>
                <td>${this.esc(row.cash_account || "-")}</td>
                <td>${this.esc(row.account_currency || "-")}</td>
                <td>${this.esc(row.current_responsible_user || "-")}</td>
                <td>${this.esc(row.current_active_shift || "-")}</td>
                <td>
                    <span class="tmv2-badge ${row.enabled ? "tmv2-badge-on" : "tmv2-badge-off"}">
                        ${row.enabled ? __("Active") : __("Disabled")}
                    </span>
                </td>
            </tr>
        `).join("");

        return `
            <div class="tmv2-section">
                <h4>${__("الخزائن التشغيلية")}</h4>
                <div class="tmv2-table-wrap">
                    <table class="tmv2-table">
                        <thead>
                            <tr>
                                <th>${__("الخزنة")}</th>
                                <th>${__("الكود")}</th>
                                <th>${__("الشركة")}</th>
                                <th>${__("الفرع")}</th>
                                <th>${__("الحساب")}</th>
                                <th>${__("العملة")}</th>
                                <th>${__("المسؤول الحالي")}</th>
                                <th>${__("الوردية الحالية")}</th>
                                <th>${__("الحالة")}</th>
                            </tr>
                        </thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            </div>
        `;
    }

    renderWarnings(rows) {
        if (!rows.length) return "";

        return `
            <div class="tmv2-section tmv2-warning">
                <h4>${__("ملاحظات على تصنيف الحسابات")}</h4>
                <ul class="tmv2-warning-list">
                    ${rows.map((row) => `
                        <li>
                            <strong>${this.esc(row.name)}</strong>:
                            ${__("محدد كحساب Cash لكنه تابع لجذر")}
                            <strong>${this.esc(row.root_type || "-")}</strong>
                            ${__("تحت")}
                            <strong>${this.esc(row.parent_account || "-")}</strong>.
                            ${__("لن يتم احتسابه كخزنة تشغيلية.")}
                        </li>
                    `).join("")}
                </ul>
            </div>
        `;
    }

    card(title, value, note) {
        return `
            <div class="tmv2-card">
                <div class="tmv2-card-title">${this.esc(title)}</div>
                <div class="tmv2-card-value">${this.esc(String(value ?? 0))}</div>
                <div class="tmv2-card-note">${this.esc(note)}</div>
            </div>
        `;
    }

    esc(value) {
        return frappe.utils.escape_html(String(value ?? ""));
    }
}
