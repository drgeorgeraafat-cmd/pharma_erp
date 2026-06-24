frappe.pages["treasury-management"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("إدارة الخزائن والبنوك ووسائل الدفع"),
        single_column: true,
    });

    new TreasuryManagementPageV1(page, wrapper);
};


class TreasuryManagementPageV1 {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$main = page.main
            ? $(page.main)
            : $(wrapper).find(".layout-main-section");

        this.addStyles();
        this.page.set_primary_action(
            __("اختبار الصفحة"),
            () => this.refresh(),
            "refresh",
        );
        this.renderLoading();
        this.refresh();
    }

    addStyles() {
        if ($("#treasury-management-v1-style").length) return;

        $("head").append(`
            <style id="treasury-management-v1-style">
                .tmv1 { direction: rtl; text-align: right; padding-bottom: 34px; }
                .tmv1-hero {
                    border: 1px solid var(--border-color);
                    background: linear-gradient(135deg, var(--card-bg), var(--control-bg));
                    border-radius: 16px;
                    padding: 22px;
                    margin-bottom: 16px;
                }
                .tmv1-hero h2 { margin: 0 0 8px; font-weight: 800; }
                .tmv1-hero p { margin: 0; color: var(--text-muted); }
                .tmv1-status {
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
                .tmv1-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 12px;
                    margin-bottom: 16px;
                }
                .tmv1-card {
                    border: 1px solid var(--border-color);
                    background: var(--card-bg);
                    border-radius: 14px;
                    padding: 16px;
                    min-height: 112px;
                }
                .tmv1-card-title { color: var(--text-muted); font-size: 12px; }
                .tmv1-card-value { font-size: 25px; font-weight: 800; margin-top: 10px; }
                .tmv1-card-note { color: var(--text-muted); font-size: 11px; margin-top: 5px; }
                .tmv1-section {
                    border: 1px solid var(--border-color);
                    background: var(--card-bg);
                    border-radius: 14px;
                    padding: 16px;
                    margin-bottom: 16px;
                }
                .tmv1-section h4 { margin: 0 0 12px; font-weight: 800; }
                .tmv1-roadmap {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
                    gap: 10px;
                }
                .tmv1-roadmap-item {
                    border: 1px solid var(--border-color);
                    background: var(--control-bg);
                    border-radius: 12px;
                    padding: 13px;
                }
                .tmv1-roadmap-item strong { display: block; margin-bottom: 5px; }
                .tmv1-roadmap-item span { color: var(--text-muted); font-size: 12px; }
                .tmv1-loading, .tmv1-error { padding: 32px; text-align: center; }
            </style>
        `);
    }

    renderLoading() {
        this.$main.html(`
            <div class="tmv1">
                <div class="tmv1-section tmv1-loading">
                    ${__("جاري تحميل الصفحة...")}
                </div>
            </div>
        `);
    }

    async refresh() {
        frappe.dom.freeze(__("جاري اختبار صفحة الخزائن والبنوك..."));

        try {
            const response = await frappe.call({
                method:
                    "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_overview",
            });

            this.render(response.message || {});
            frappe.show_alert({
                message: __("Treasury Management Working Successfully ✅"),
                indicator: "green",
            });
        } catch (error) {
            console.error(error);
            this.$main.html(`
                <div class="tmv1">
                    <div class="tmv1-section tmv1-error">
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
            <div class="tmv1">
                <div class="tmv1-hero">
                    <h2>${__("إدارة الخزائن والبنوك ووسائل الدفع")}</h2>
                    <p>
                        ${__("المرحلة الأولى: تأسيس الصفحة وربطها بالـ Backend بدون إنشاء قيود أو حسابات جديدة.")}
                    </p>
                    <div class="tmv1-status">
                        <span>●</span>
                        ${frappe.utils.escape_html(
                            data.message || __("Page is ready"),
                        )}
                    </div>
                </div>

                <div class="tmv1-grid">
                    ${this.card(__("الشركات"), data.companies, __("Company"))}
                    ${this.card(__("الخزائن الحالية"), data.cash_accounts, __("Cash Accounts"))}
                    ${this.card(__("حسابات البنوك"), data.bank_ledger_accounts, __("Bank Ledger Accounts"))}
                    ${this.card(__("Bank Accounts"), data.bank_accounts, __("ERPNext Bank Account"))}
                    ${this.card(__("ماكينات الفيزا"), data.card_terminals, __("Card POS Terminal"))}
                    ${this.card(__("إعدادات التسوية"), data.clearing_setups, __("Clearing Setup"))}
                </div>

                <div class="tmv1-section">
                    <h4>${__("ترتيب بناء الصفحة")}</h4>
                    <div class="tmv1-roadmap">
                        ${this.roadmapItem("1", __("إدارة الخزائن"), __("إنشاء الخزنة والحساب وربط الاستخدامات."))}
                        ${this.roadmapItem("2", __("إدارة البنوك"), __("Bank Account والحساب البنكي والرسوم."))}
                        ${this.roadmapItem("3", __("ماكينات الفيزا"), __("الربط بالبنك والحساب الوسيط والنهائي."))}
                        ${this.roadmapItem("4", __("InstaPay والمحافظ"), __("وسائل الدفع والتسوية والمراجعة."))}
                        ${this.roadmapItem("5", __("الأرصدة الوسيطة"), __("عرض الحركات والأرصدة والتنبيهات."))}
                        ${this.roadmapItem("6", __("صلاحيات الإدارة"), __("الفصل بين العرض والإنشاء والاعتماد."))}
                    </div>
                </div>
            </div>
        `);
    }

    card(title, value, note) {
        return `
            <div class="tmv1-card">
                <div class="tmv1-card-title">${frappe.utils.escape_html(title)}</div>
                <div class="tmv1-card-value">${frappe.utils.escape_html(String(value ?? 0))}</div>
                <div class="tmv1-card-note">${frappe.utils.escape_html(note)}</div>
            </div>
        `;
    }

    roadmapItem(number, title, note) {
        return `
            <div class="tmv1-roadmap-item">
                <strong>${number}. ${frappe.utils.escape_html(title)}</strong>
                <span>${frappe.utils.escape_html(note)}</span>
            </div>
        `;
    }
}
