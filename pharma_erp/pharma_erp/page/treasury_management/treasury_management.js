frappe.pages["treasury-management"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("إدارة الخزائن والبنوك ووسائل الدفع"),
        single_column: true,
    });

    new TreasuryManagementPageV3(page, wrapper);
};


class TreasuryManagementPageV3 {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$main = page.main
            ? $(page.main)
            : $(wrapper).find(".layout-main-section");
        this.canCreateCashDrawer = false;
        this.autoAccountName = "";

        this.addStyles();
        this.page.set_primary_action(
            __("إنشاء خزنة جديدة"),
            () => this.openCreateCashDrawerDialog(),
            "add",
        );
        this.page.add_inner_button(
            __("تحديث البيانات"),
            () => this.refresh(),
            "إجراءات",
        );
        this.renderLoading();
        this.refresh();
    }

    addStyles() {
        if ($("#treasury-management-v3-style").length) return;

        $("head").append(`
            <style id="treasury-management-v3-style">
                .tmv3 { direction: rtl; text-align: right; padding-bottom: 34px; }
                .tmv3-hero {
                    border: 1px solid var(--border-color);
                    background: linear-gradient(135deg, var(--card-bg), var(--control-bg));
                    border-radius: 16px;
                    padding: 22px;
                    margin-bottom: 16px;
                }
                .tmv3-hero h2 { margin: 0 0 8px; font-weight: 800; }
                .tmv3-hero p { margin: 0; color: var(--text-muted); }
                .tmv3-status {
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
                .tmv3-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 12px;
                    margin-bottom: 16px;
                }
                .tmv3-card, .tmv3-section {
                    border: 1px solid var(--border-color);
                    background: var(--card-bg);
                    border-radius: 14px;
                }
                .tmv3-card { padding: 16px; min-height: 112px; }
                .tmv3-card-title { color: var(--text-muted); font-size: 12px; }
                .tmv3-card-value { font-size: 25px; font-weight: 800; margin-top: 10px; }
                .tmv3-card-note { color: var(--text-muted); font-size: 11px; margin-top: 5px; }
                .tmv3-section { padding: 16px; margin-bottom: 16px; }
                .tmv3-section h4 { margin: 0 0 12px; font-weight: 800; }
                .tmv3-table-wrap { overflow-x: auto; }
                .tmv3-table { width: 100%; border-collapse: collapse; min-width: 840px; }
                .tmv3-table th, .tmv3-table td {
                    padding: 10px 9px;
                    border-bottom: 1px solid var(--border-color);
                    vertical-align: middle;
                    text-align: right;
                    white-space: nowrap;
                }
                .tmv3-table th { color: var(--text-muted); font-size: 12px; }
                .tmv3-badge {
                    display: inline-flex;
                    align-items: center;
                    padding: 4px 9px;
                    border-radius: 999px;
                    font-weight: 700;
                    font-size: 11px;
                }
                .tmv3-badge-on { background: var(--green-100); color: var(--green-700); }
                .tmv3-badge-off { background: var(--gray-100); color: var(--text-muted); }
                .tmv3-warning {
                    border-color: var(--orange-300);
                    background: var(--orange-50);
                }
                .tmv3-warning-list { margin: 0; padding-right: 20px; }
                .tmv3-warning-list li { margin-bottom: 6px; }
                .tmv3-empty { color: var(--text-muted); padding: 16px 0; }
                .tmv3-loading, .tmv3-error { padding: 32px; text-align: center; }
                .tmv3-preview {
                    direction: rtl;
                    border: 1px solid var(--border-color);
                    border-radius: 12px;
                    overflow: hidden;
                }
                .tmv3-preview-row {
                    display: grid;
                    grid-template-columns: minmax(130px, 0.75fr) minmax(220px, 1.4fr);
                    gap: 12px;
                    padding: 10px 12px;
                    border-bottom: 1px solid var(--border-color);
                }
                .tmv3-preview-row:last-child { border-bottom: 0; }
                .tmv3-preview-label { color: var(--text-muted); }
                .tmv3-preview-value { font-weight: 700; word-break: break-word; }
                .tmv3-preview-note {
                    margin-top: 12px;
                    padding: 10px 12px;
                    border-radius: 10px;
                    background: var(--yellow-50);
                    border: 1px solid var(--yellow-200);
                }
            </style>
        `);
    }

    renderLoading() {
        this.$main.html(`
            <div class="tmv3">
                <div class="tmv3-section tmv3-loading">
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

            const data = response.message || {};
            this.canCreateCashDrawer = Boolean(data.can_create_cash_drawer);
            this.page.btn_primary.toggle(this.canCreateCashDrawer);
            this.render(data);
            frappe.show_alert({
                message: __("تم تحديث بيانات الخزائن والبنوك"),
                indicator: "green",
            });
        } catch (error) {
            console.error(error);
            this.$main.html(`
                <div class="tmv3">
                    <div class="tmv3-section tmv3-error">
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

    async openCreateCashDrawerDialog() {
        if (!this.canCreateCashDrawer) {
            frappe.msgprint(__("ليس لديك صلاحية إنشاء خزنة جديدة."));
            return;
        }

        const options = await this.getCreationOptions();
        let dialog;

        dialog = new frappe.ui.Dialog({
            title: __("إنشاء خزنة جديدة"),
            size: "large",
            fields: [
                {
                    fieldname: "drawer_name",
                    label: __("اسم الخزنة"),
                    fieldtype: "Data",
                    reqd: 1,
                    onchange: () => this.syncAccountName(dialog),
                },
                {
                    fieldname: "drawer_code",
                    label: __("كود الخزنة"),
                    fieldtype: "Data",
                    reqd: 1,
                    default: options.suggested_drawer_code,
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "company",
                    label: __("الشركة"),
                    fieldtype: "Link",
                    options: "Company",
                    reqd: 1,
                    default: options.company,
                    onchange: () => this.reloadCompanyDefaults(dialog),
                },
                {
                    fieldname: "branch",
                    label: __("الفرع"),
                    fieldtype: "Link",
                    options: "Branch",
                    get_query: () => ({
                        filters: dialog.get_value("company")
                            ? { company: dialog.get_value("company") }
                            : {},
                    }),
                },
                { fieldtype: "Section Break", label: __("الموقع والعهدة") },
                {
                    fieldname: "physical_location",
                    label: __("الموقع الفعلي"),
                    fieldtype: "Data",
                },
                {
                    fieldname: "default_opening_float",
                    label: __("عهدة البداية الافتراضية"),
                    fieldtype: "Currency",
                    default: 0,
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "account_currency",
                    label: __("العملة"),
                    fieldtype: "Data",
                    read_only: 1,
                    default: options.account_currency,
                },
                { fieldtype: "Section Break", label: __("الحساب المحاسبي الذي سيتم إنشاؤه") },
                {
                    fieldname: "account_name",
                    label: __("اسم حساب الخزنة"),
                    fieldtype: "Data",
                    reqd: 1,
                },
                {
                    fieldname: "parent_account",
                    label: __("الحساب الأب"),
                    fieldtype: "Link",
                    options: "Account",
                    reqd: 1,
                    default: options.default_parent_account,
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Asset",
                            is_group: 1,
                            disabled: 0,
                        },
                    }),
                },
            ],
            primary_action_label: __("معاينة الإنشاء"),
            primary_action: async (values) => {
                await this.previewCashDrawer(dialog, values);
            },
        });

        dialog.show();
    }

    async getCreationOptions(company = null) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_cash_drawer_creation_options",
            args: { company },
            freeze: true,
            freeze_message: __("جاري تجهيز بيانات الخزنة..."),
        });
        return response.message || {};
    }

    async reloadCompanyDefaults(dialog) {
        const company = dialog.get_value("company");
        if (!company) return;

        const options = await this.getCreationOptions(company);
        dialog.set_value("account_currency", options.account_currency || "");
        dialog.set_value("parent_account", options.default_parent_account || "");
        dialog.set_value("branch", "");
    }

    syncAccountName(dialog) {
        const drawerName = String(dialog.get_value("drawer_name") || "").trim();
        const current = String(dialog.get_value("account_name") || "").trim();
        if (!current || current === this.autoAccountName) {
            this.autoAccountName = drawerName;
            dialog.set_value("account_name", drawerName);
        }
    }

    async previewCashDrawer(sourceDialog, values) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.preview_cash_drawer",
            args: values,
            freeze: true,
            freeze_message: __("جاري مراجعة بيانات الخزنة..."),
        });

        const preview = response.message || {};
        this.showCreateConfirmation(sourceDialog, preview);
    }

    showCreateConfirmation(sourceDialog, preview) {
        const confirmDialog = new frappe.ui.Dialog({
            title: __("تأكيد إنشاء الخزنة والحساب"),
            size: "large",
            fields: [
                {
                    fieldtype: "HTML",
                    options: this.renderCreationPreview(preview),
                },
            ],
            primary_action_label: __("إنشاء الخزنة والحساب"),
            primary_action: async () => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.create_cash_drawer",
                    args: preview,
                    freeze: true,
                    freeze_message: __("جاري إنشاء الخزنة والحساب المحاسبي..."),
                });

                confirmDialog.hide();
                sourceDialog.hide();
                const result = response.message || {};
                frappe.msgprint({
                    title: __("تم إنشاء الخزنة"),
                    indicator: "green",
                    message: `
                        <div style="direction: rtl; text-align: right;">
                            <div>${this.esc(result.message || __("تم الإنشاء بنجاح"))}</div>
                            <div style="margin-top: 8px;">
                                <strong>${__("الخزنة")}:</strong>
                                ${this.esc(result.drawer || "-")}
                            </div>
                            <div>
                                <strong>${__("الحساب")}:</strong>
                                ${this.esc(result.cash_account || "-")}
                            </div>
                        </div>
                    `,
                });
                await this.refresh();
            },
        });

        confirmDialog.show();
    }

    renderCreationPreview(preview) {
        const rows = [
            [__("اسم الخزنة"), preview.drawer_name],
            [__("كود الخزنة"), preview.drawer_code],
            [__("الشركة"), preview.company],
            [__("الفرع"), preview.branch || "-"],
            [__("الموقع"), preview.physical_location || "-"],
            [__("عهدة البداية الافتراضية"), format_currency(preview.default_opening_float || 0, preview.account_currency)],
            [__("اسم الحساب الجديد"), preview.account_name],
            [__("الحساب الأب"), preview.parent_account],
            [__("نوع الحساب"), preview.account_type],
            [__("العملة"), preview.account_currency],
        ];

        return `
            <div class="tmv3-preview">
                ${rows.map(([label, value]) => `
                    <div class="tmv3-preview-row">
                        <div class="tmv3-preview-label">${this.esc(label)}</div>
                        <div class="tmv3-preview-value">${this.esc(value || "-")}</div>
                    </div>
                `).join("")}
            </div>
            <div class="tmv3-preview-note">
                <strong>${__("مهم")}:</strong>
                ${__("سيتم إنشاء حساب Cash جديد ثم ربطه بالخزنة. عهدة البداية الافتراضية إعداد تشغيلي فقط ولن تنشئ قيدًا افتتاحيًا في هذه الخطوة.")}
            </div>
        `;
    }

    render(data) {
        this.$main.html(`
            <div class="tmv3">
                <div class="tmv3-hero">
                    <h2>${__("إدارة الخزائن والبنوك ووسائل الدفع")}</h2>
                    <p>
                        ${__("تم اعتماد Cash Drawer الحالي ليكون سجل الخزنة التشغيلية، ويمكن الآن إنشاء خزنة وحسابها المحاسبي بعد المعاينة والتأكيد.")}
                    </p>
                    <div class="tmv3-status">
                        <span>●</span>
                        ${frappe.utils.escape_html(
                            data.message || __("Page is ready"),
                        )}
                    </div>
                </div>

                <div class="tmv3-grid">
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
                <div class="tmv3-section">
                    <h4>${__("الخزائن التشغيلية")}</h4>
                    <div class="tmv3-empty">
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
                    <span class="tmv3-badge ${row.enabled ? "tmv3-badge-on" : "tmv3-badge-off"}">
                        ${row.enabled ? __("Active") : __("Disabled")}
                    </span>
                </td>
            </tr>
        `).join("");

        return `
            <div class="tmv3-section">
                <h4>${__("الخزائن التشغيلية")}</h4>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table">
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
            <div class="tmv3-section tmv3-warning">
                <h4>${__("ملاحظات على تصنيف الحسابات")}</h4>
                <ul class="tmv3-warning-list">
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
            <div class="tmv3-card">
                <div class="tmv3-card-title">${this.esc(title)}</div>
                <div class="tmv3-card-value">${this.esc(String(value ?? 0))}</div>
                <div class="tmv3-card-note">${this.esc(note)}</div>
            </div>
        `;
    }

    esc(value) {
        return frappe.utils.escape_html(String(value ?? ""));
    }
}
