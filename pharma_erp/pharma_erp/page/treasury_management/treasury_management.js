frappe.pages["treasury-management"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("إدارة الخزائن والبنوك ووسائل الدفع"),
        single_column: true,
    });

    new TreasuryManagementPageV8(page, wrapper);
};


class TreasuryManagementPageV8 {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$main = page.main
            ? $(page.main)
            : $(wrapper).find(".layout-main-section");
        this.canCreateCashDrawer = false;
        this.canManageCashDrawer = false;
        this.canCreateBank = false;
        this.canManageCardTerminal = false;
        this.canManagePaymentSetup = false;
        this.autoAccountName = "";
        this.autoBankNames = {};
        this.autoTerminalNames = {};
        this.autoPaymentNames = {};

        this.addStyles();
        this.page.set_primary_action(
            __("إنشاء خزنة جديدة"),
            () => this.openCreateCashDrawerDialog(),
            "add",
        );
        this.$bankButton = this.page.add_inner_button(
            __("إضافة بنك وحساب"),
            () => this.openCreateBankDialog(),
            __("البنوك"),
        );
        this.$terminalButton = this.page.add_inner_button(
            __("إضافة ماكينة فيزا"),
            () => this.openCardTerminalDialog(),
            __("ماكينات الفيزا"),
        );
        this.$paymentSetupButton = this.page.add_inner_button(
            __("إضافة وسيلة دفع إلكترونية"),
            () => this.openPaymentSetupDialog(),
            __("وسائل الدفع"),
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
                .tmv3-actions { display: flex; gap: 6px; flex-wrap: wrap; }
                .tmv3-action-btn {
                    border: 1px solid var(--border-color);
                    background: var(--control-bg);
                    color: var(--text-color);
                    border-radius: 8px;
                    padding: 5px 9px;
                    cursor: pointer;
                    font-size: 11px;
                    font-weight: 700;
                }
                .tmv3-action-btn:hover { background: var(--subtle-fg); }
                .tmv3-action-danger { color: var(--red-600); border-color: var(--red-200); }
                .tmv3-action-success { color: var(--green-700); border-color: var(--green-200); }
                .tmv3-balance-positive { color: var(--green-700); font-weight: 800; }
                .tmv3-balance-negative { color: var(--red-600); font-weight: 800; }
                .tmv3-activity-table { width: 100%; border-collapse: collapse; min-width: 760px; }
                .tmv3-activity-table th, .tmv3-activity-table td {
                    padding: 8px; border-bottom: 1px solid var(--border-color); text-align: right;
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
            this.canManageCashDrawer = Boolean(data.can_manage_cash_drawer);
            this.canCreateBank = Boolean(data.can_create_bank);
            this.canManageCardTerminal = Boolean(data.can_manage_card_terminal);
            this.canManagePaymentSetup = Boolean(data.can_manage_payment_setup);
            this.page.btn_primary.toggle(this.canCreateCashDrawer);
            if (this.$bankButton) this.$bankButton.toggle(this.canCreateBank);
            if (this.$terminalButton) this.$terminalButton.toggle(this.canManageCardTerminal);
            if (this.$paymentSetupButton) this.$paymentSetupButton.toggle(this.canManagePaymentSetup);
            this.render(data);
            this.bindDrawerActions();
            this.bindBankActions();
            this.bindTerminalActions();
            this.bindPaymentSetupActions();
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


    async openCreateBankDialog() {
        if (!this.canCreateBank) {
            frappe.msgprint(__("ليس لديك صلاحية إنشاء أو ربط حساب بنكي."));
            return;
        }

        const options = await this.getBankCreationOptions();
        let dialog;
        dialog = new frappe.ui.Dialog({
            title: __("إضافة بنك وحساب بنكي"),
            size: "extra-large",
            fields: [
                { fieldtype: "Section Break", label: __("بيانات البنك") },
                {
                    fieldname: "bank_name",
                    label: __("اسم البنك"),
                    fieldtype: "Data",
                    reqd: 1,
                    onchange: () => this.syncBankNames(dialog),
                },
                {
                    fieldname: "swift_number",
                    label: __("SWIFT Code"),
                    fieldtype: "Data",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "company",
                    label: __("الشركة"),
                    fieldtype: "Link",
                    options: "Company",
                    reqd: 1,
                    default: options.company,
                    onchange: () => this.reloadBankCompanyDefaults(dialog),
                },
                {
                    fieldname: "website",
                    label: __("موقع البنك"),
                    fieldtype: "Data",
                },
                { fieldtype: "Section Break", label: __("الحساب داخل Chart of Accounts") },
                {
                    fieldname: "ledger_mode",
                    label: __("طريقة ربط الحساب"),
                    fieldtype: "Select",
                    options: "Use Existing Account\nCreate New Account",
                    default: (options.unlinked_bank_accounts || []).length
                        ? "Use Existing Account"
                        : "Create New Account",
                    reqd: 1,
                },
                {
                    fieldname: "existing_ledger_account",
                    label: __("حساب بنكي موجود"),
                    fieldtype: "Link",
                    options: "Account",
                    depends_on: "eval:doc.ledger_mode=='Use Existing Account'",
                    mandatory_depends_on: "eval:doc.ledger_mode=='Use Existing Account'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            account_type: "Bank",
                            root_type: "Asset",
                            is_group: 0,
                            disabled: 0,
                        },
                    }),
                },
                {
                    fieldname: "ledger_account_name",
                    label: __("اسم الحساب البنكي الجديد"),
                    fieldtype: "Data",
                    depends_on: "eval:doc.ledger_mode=='Create New Account'",
                    mandatory_depends_on: "eval:doc.ledger_mode=='Create New Account'",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "bank_parent_account",
                    label: __("الحساب الأب للبنك"),
                    fieldtype: "Link",
                    options: "Account",
                    default: options.default_bank_parent_account,
                    depends_on: "eval:doc.ledger_mode=='Create New Account'",
                    mandatory_depends_on: "eval:doc.ledger_mode=='Create New Account'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Asset",
                            is_group: 1,
                            disabled: 0,
                        },
                    }),
                },
                {
                    fieldname: "account_currency",
                    label: __("العملة"),
                    fieldtype: "Data",
                    read_only: 1,
                    default: options.account_currency,
                },
                { fieldtype: "Section Break", label: __("Bank Account داخل ERPNext") },
                {
                    fieldname: "bank_account_name",
                    label: __("اسم Bank Account"),
                    fieldtype: "Data",
                    reqd: 1,
                },
                {
                    fieldname: "bank_account_no",
                    label: __("رقم الحساب"),
                    fieldtype: "Data",
                },
                {
                    fieldname: "iban",
                    label: __("IBAN"),
                    fieldtype: "Data",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "branch_code",
                    label: __("كود فرع البنك"),
                    fieldtype: "Data",
                },
                { fieldtype: "Section Break", label: __("الحسابات الوسيطة المقترحة") },
                {
                    fieldname: "create_card_clearing",
                    label: __("إنشاء أو استخدام Card Clearing"),
                    fieldtype: "Check",
                    default: 1,
                },
                {
                    fieldname: "card_clearing_name",
                    label: __("اسم حساب Card Clearing"),
                    fieldtype: "Data",
                    depends_on: "create_card_clearing",
                    mandatory_depends_on: "create_card_clearing",
                },
                {
                    fieldname: "create_instapay_clearing",
                    label: __("إنشاء أو استخدام InstaPay Clearing"),
                    fieldtype: "Check",
                    default: 0,
                },
                {
                    fieldname: "instapay_clearing_name",
                    label: __("اسم حساب InstaPay Clearing"),
                    fieldtype: "Data",
                    depends_on: "create_instapay_clearing",
                    mandatory_depends_on: "create_instapay_clearing",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "clearing_parent_account",
                    label: __("الحساب الأب للحسابات الوسيطة"),
                    fieldtype: "Link",
                    options: "Account",
                    default: options.default_clearing_parent_account,
                    depends_on: "eval:doc.create_card_clearing || doc.create_instapay_clearing",
                    mandatory_depends_on: "eval:doc.create_card_clearing || doc.create_instapay_clearing",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Asset",
                            is_group: 1,
                            disabled: 0,
                        },
                    }),
                },
                {
                    fieldname: "create_fee_account",
                    label: __("إنشاء أو استخدام حساب رسوم البنك"),
                    fieldtype: "Check",
                    default: 1,
                },
                {
                    fieldname: "fee_account_name",
                    label: __("اسم حساب رسوم البنك"),
                    fieldtype: "Data",
                    depends_on: "create_fee_account",
                    mandatory_depends_on: "create_fee_account",
                },
                {
                    fieldname: "fee_parent_account",
                    label: __("الحساب الأب للرسوم"),
                    fieldtype: "Link",
                    options: "Account",
                    default: options.default_fee_parent_account,
                    depends_on: "create_fee_account",
                    mandatory_depends_on: "create_fee_account",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Expense",
                            is_group: 1,
                            disabled: 0,
                        },
                    }),
                },
            ],
            primary_action_label: __("معاينة الإنشاء"),
            primary_action: async (values) => this.previewBankSetup(dialog, values),
        });
        dialog.show();
    }

    async getBankCreationOptions(company = null) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_bank_creation_options",
            args: { company },
            freeze: true,
            freeze_message: __("جاري تجهيز بيانات البنك..."),
        });
        return response.message || {};
    }

    async reloadBankCompanyDefaults(dialog) {
        const company = dialog.get_value("company");
        if (!company) return;
        const options = await this.getBankCreationOptions(company);
        dialog.set_value("account_currency", options.account_currency || "");
        dialog.set_value("bank_parent_account", options.default_bank_parent_account || "");
        dialog.set_value("clearing_parent_account", options.default_clearing_parent_account || "");
        dialog.set_value("fee_parent_account", options.default_fee_parent_account || "");
        dialog.set_value("existing_ledger_account", "");
    }

    syncBankNames(dialog) {
        const bankName = String(dialog.get_value("bank_name") || "").trim();
        const suggestions = {
            ledger_account_name: `${bankName} Current Account`,
            bank_account_name: `${bankName} Current Account`,
            card_clearing_name: `${bankName} Card Clearing`,
            instapay_clearing_name: `${bankName} InstaPay Clearing`,
            fee_account_name: `${bankName} Bank Charges`,
        };
        Object.entries(suggestions).forEach(([fieldname, value]) => {
            const current = String(dialog.get_value(fieldname) || "").trim();
            if (!current || current === this.autoBankNames[fieldname]) {
                this.autoBankNames[fieldname] = value;
                dialog.set_value(fieldname, value);
            }
        });
    }

    async previewBankSetup(sourceDialog, values) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.preview_bank_setup",
            args: values,
            freeze: true,
            freeze_message: __("جاري مراجعة بيانات البنك والحسابات..."),
        });
        this.showBankConfirmation(sourceDialog, values, response.message || {});
    }

    showBankConfirmation(sourceDialog, sourceValues, preview) {
        const confirmDialog = new frappe.ui.Dialog({
            title: __("تأكيد إنشاء البنك والحسابات"),
            size: "extra-large",
            fields: [{ fieldtype: "HTML", options: this.renderBankPreview(preview) }],
            primary_action_label: __("إنشاء البنك والحسابات"),
            primary_action: async () => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.create_bank_setup",
                    args: sourceValues,
                    freeze: true,
                    freeze_message: __("جاري إنشاء وربط البنك والحسابات..."),
                });
                confirmDialog.hide();
                sourceDialog.hide();
                const result = response.message || {};
                frappe.msgprint({
                    title: __("تم إنشاء إعداد البنك"),
                    indicator: "green",
                    message: `
                        <div style="direction: rtl; text-align: right;">
                            <div>${this.esc(result.message || __("تم الإنشاء بنجاح"))}</div>
                            <div><strong>${__("البنك")}:</strong> ${this.esc(result.bank || "-")}</div>
                            <div><strong>${__("Bank Account")}:</strong> ${this.esc(result.bank_account || "-")}</div>
                            <div><strong>${__("حساب الأستاذ")}:</strong> ${this.esc(result.ledger_account || "-")}</div>
                        </div>
                    `,
                });
                await this.refresh();
            },
        });
        confirmDialog.show();
    }

    renderBankPreview(preview) {
        const accountRows = [
            [__("الحساب البنكي"), preview.ledger_account],
            [__("Card Clearing"), preview.card_clearing_account],
            [__("InstaPay Clearing"), preview.instapay_clearing_account],
            [__("رسوم البنك"), preview.fee_account],
        ].filter(([, plan]) => plan);
        const actionLabel = (plan) => plan?.action === "reuse" ? __("استخدام الموجود") : __("إنشاء جديد");
        return `
            <div class="tmv3-preview">
                <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("البنك")}</div><div class="tmv3-preview-value">${this.esc(preview.bank_name || "-")} — ${preview.bank_master_action === "reuse" ? __("موجود") : __("سيتم إنشاؤه")}</div></div>
                <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الشركة")}</div><div class="tmv3-preview-value">${this.esc(preview.company || "-")}</div></div>
                <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("Bank Account")}</div><div class="tmv3-preview-value">${this.esc(preview.bank_account_name || "-")}</div></div>
                <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("رقم الحساب / IBAN")}</div><div class="tmv3-preview-value">${this.esc(preview.bank_account_no || "-")} / ${this.esc(preview.iban || "-")}</div></div>
                ${accountRows.map(([label, plan]) => `
                    <div class="tmv3-preview-row">
                        <div class="tmv3-preview-label">${this.esc(label)}</div>
                        <div class="tmv3-preview-value">
                            ${this.esc(plan.document_name || plan.account_name || "-")}
                            — ${this.esc(actionLabel(plan))}
                            <br><small>${this.esc(plan.parent_account || "-")}</small>
                        </div>
                    </div>
                `).join("")}
            </div>
            <div class="tmv3-preview-note">
                <strong>${__("مهم")}:</strong>
                ${__("لن يتم إنشاء أي قيد محاسبي. سيتم فقط إنشاء أو ربط سجلات البنك والحسابات، مع إعادة استخدام الحسابات الموجودة المطابقة بدل تكرارها.")}
            </div>
        `;
    }


    async openCardTerminalDialog(existingTerminal = null) {
        if (!this.canManageCardTerminal) {
            frappe.msgprint(__("ليس لديك صلاحية إدارة ماكينات الفيزا."));
            return;
        }

        const options = await this.getCardTerminalOptions(null, existingTerminal);
        const current = options.terminal || {};
        const editing = Boolean(current.name);
        let dialog;

        dialog = new frappe.ui.Dialog({
            title: editing ? __("تعديل ماكينة الفيزا") : __("إضافة ماكينة فيزا"),
            size: "extra-large",
            fields: [
                {
                    fieldname: "existing_terminal",
                    fieldtype: "Data",
                    hidden: 1,
                    default: current.name || "",
                },
                { fieldtype: "Section Break", label: __("بيانات الماكينة") },
                {
                    fieldname: "terminal_name",
                    label: __("اسم الماكينة"),
                    fieldtype: "Data",
                    reqd: 1,
                    default: current.terminal_name || "",
                },
                {
                    fieldname: "terminal_code",
                    label: __("كود الماكينة"),
                    fieldtype: "Data",
                    reqd: 1,
                    read_only: editing ? 1 : 0,
                    default: current.terminal_code || options.suggested_terminal_code,
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "company",
                    label: __("الشركة"),
                    fieldtype: "Link",
                    options: "Company",
                    reqd: 1,
                    default: current.company || options.company,
                    onchange: () => this.reloadTerminalCompanyDefaults(dialog),
                },
                {
                    fieldname: "mode_of_payment",
                    label: __("طريقة الدفع"),
                    fieldtype: "Link",
                    options: "Mode of Payment",
                    reqd: 1,
                    default: current.mode_of_payment || options.default_mode_of_payment,
                },
                { fieldtype: "Section Break", label: __("البنك والحساب النهائي") },
                {
                    fieldname: "bank_account",
                    label: __("Bank Account"),
                    fieldtype: "Link",
                    options: "Bank Account",
                    reqd: 1,
                    default: current.bank_account || "",
                    onchange: () => this.syncTerminalBankDefaults(dialog),
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            disabled: 0,
                            is_company_account: 1,
                        },
                    }),
                },
                {
                    fieldname: "merchant_id",
                    label: __("Merchant ID"),
                    fieldtype: "Data",
                    default: current.merchant_id || "",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "terminal_id",
                    label: __("Terminal ID"),
                    fieldtype: "Data",
                    default: current.terminal_id || "",
                },
                { fieldtype: "Section Break", label: __("حساب Card Clearing") },
                {
                    fieldname: "clearing_mode",
                    label: __("طريقة ربط حساب Clearing"),
                    fieldtype: "Select",
                    options: "Use Existing Account\nCreate New Account",
                    reqd: 1,
                    default: "Use Existing Account",
                },
                {
                    fieldname: "existing_clearing_account",
                    label: __("حساب Clearing موجود"),
                    fieldtype: "Link",
                    options: "Account",
                    default: current.clearing_account || "",
                    depends_on: "eval:doc.clearing_mode=='Use Existing Account'",
                    mandatory_depends_on: "eval:doc.clearing_mode=='Use Existing Account'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Asset",
                            is_group: 0,
                            disabled: 0,
                        },
                    }),
                },
                {
                    fieldname: "clearing_account_name",
                    label: __("اسم حساب Clearing الجديد"),
                    fieldtype: "Data",
                    depends_on: "eval:doc.clearing_mode=='Create New Account'",
                    mandatory_depends_on: "eval:doc.clearing_mode=='Create New Account'",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "clearing_parent_account",
                    label: __("الحساب الأب لـ Clearing"),
                    fieldtype: "Link",
                    options: "Account",
                    default: options.default_clearing_parent_account || "",
                    depends_on: "eval:doc.clearing_mode=='Create New Account'",
                    mandatory_depends_on: "eval:doc.clearing_mode=='Create New Account'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Asset",
                            is_group: 1,
                            disabled: 0,
                        },
                    }),
                },
                {
                    fieldname: "fee_account",
                    label: __("حساب رسوم البنك"),
                    fieldtype: "Link",
                    options: "Account",
                    default: current.fee_account || options.default_fee_account || "",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Expense",
                            is_group: 0,
                            disabled: 0,
                        },
                    }),
                },
                { fieldtype: "Section Break", label: __("ملاحظات") },
                {
                    fieldname: "notes",
                    label: __("ملاحظات"),
                    fieldtype: "Small Text",
                    default: current.notes || "",
                },
            ],
            primary_action_label: editing ? __("معاينة التعديل") : __("معاينة الإنشاء"),
            primary_action: async (values) => this.previewCardTerminal(dialog, values),
        });

        dialog.show();
        if (!editing && current.bank_label) this.syncTerminalBankDefaults(dialog);
    }

    async getCardTerminalOptions(company = null, terminalName = null) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_card_terminal_creation_options",
            args: { company, terminal_name: terminalName },
            freeze: true,
            freeze_message: __("جاري تجهيز بيانات ماكينة الفيزا..."),
        });
        return response.message || {};
    }

    async reloadTerminalCompanyDefaults(dialog) {
        const company = dialog.get_value("company");
        if (!company) return;
        const options = await this.getCardTerminalOptions(company);
        dialog.set_value("mode_of_payment", options.default_mode_of_payment || "");
        dialog.set_value("clearing_parent_account", options.default_clearing_parent_account || "");
        dialog.set_value("fee_account", options.default_fee_account || "");
        dialog.set_value("bank_account", "");
        dialog.set_value("existing_clearing_account", "");
    }

    async syncTerminalBankDefaults(dialog) {
        const bankAccount = dialog.get_value("bank_account");
        if (!bankAccount) return;
        const response = await frappe.db.get_value(
            "Bank Account",
            bankAccount,
            ["bank", "account_name", "account"],
        );
        const data = response.message || {};
        const bank = String(data.bank || "").trim();
        if (!bank) return;

        const suggestions = {
            terminal_name: `${bank} Terminal`,
            clearing_account_name: `${bank} Card Clearing`,
        };
        Object.entries(suggestions).forEach(([fieldname, value]) => {
            const current = String(dialog.get_value(fieldname) || "").trim();
            if (!current || current === this.autoTerminalNames[fieldname]) {
                this.autoTerminalNames[fieldname] = value;
                dialog.set_value(fieldname, value);
            }
        });
    }

    async previewCardTerminal(sourceDialog, values) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.preview_card_terminal",
            args: values,
            freeze: true,
            freeze_message: __("جاري مراجعة بيانات ماكينة الفيزا..."),
        });
        this.showCardTerminalConfirmation(sourceDialog, values, response.message || {});
    }

    showCardTerminalConfirmation(sourceDialog, sourceValues, preview) {
        const updating = preview.action === "update";
        const confirmDialog = new frappe.ui.Dialog({
            title: updating ? __("تأكيد تعديل ماكينة الفيزا") : __("تأكيد إنشاء ماكينة الفيزا"),
            size: "extra-large",
            fields: [{ fieldtype: "HTML", options: this.renderCardTerminalPreview(preview) }],
            primary_action_label: updating ? __("حفظ التعديلات") : __("إنشاء الماكينة"),
            primary_action: async () => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.save_card_terminal",
                    args: sourceValues,
                    freeze: true,
                    freeze_message: updating
                        ? __("جاري حفظ تعديلات الماكينة...")
                        : __("جاري إنشاء ماكينة الفيزا..."),
                });
                confirmDialog.hide();
                sourceDialog.hide();
                const result = response.message || {};
                frappe.msgprint({
                    title: updating ? __("تم تعديل الماكينة") : __("تم إنشاء الماكينة"),
                    indicator: "green",
                    message: `
                        <div style="direction: rtl; text-align: right;">
                            <div>${this.esc(result.message || __("تم الحفظ بنجاح"))}</div>
                            <div><strong>${__("الماكينة")}:</strong> ${this.esc(result.terminal || "-")}</div>
                            <div><strong>${__("Clearing")}:</strong> ${this.esc(result.clearing_account || "-")}</div>
                            <div><strong>${__("الحساب البنكي")}:</strong> ${this.esc(result.destination_bank_account || "-")}</div>
                        </div>
                    `,
                });
                await this.refresh();
            },
        });
        confirmDialog.show();
    }

    renderCardTerminalPreview(preview) {
        const clearing = preview.clearing_account || {};
        const clearingAction = clearing.action === "reuse" ? __("استخدام الموجود") : __("إنشاء جديد");
        const rows = [
            [__("العملية"), preview.action === "update" ? __("تعديل ماكينة موجودة") : __("إنشاء ماكينة جديدة")],
            [__("اسم الماكينة"), preview.terminal_name],
            [__("كود الماكينة"), preview.terminal_code],
            [__("الشركة"), preview.company],
            [__("طريقة الدفع"), preview.mode_of_payment],
            [__("البنك"), preview.bank_label],
            [__("Bank Account"), preview.bank_account],
            [__("الحساب البنكي النهائي"), preview.destination_bank_account],
            [__("حساب Clearing"), `${clearing.document_name || clearing.account_name || "-"} — ${clearingAction}`],
            [__("حساب الرسوم"), preview.fee_account || "-"],
            [__("Merchant ID"), preview.merchant_id || "-"],
            [__("Terminal ID"), preview.terminal_id || "-"],
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
                ${__("لن يتم إنشاء قيد محاسبي. عند تعديل ماكينة عليها Batches مفتوحة، يمنع النظام تغيير البنك أو حساب Clearing أو طريقة الدفع حتى تتم التسوية.")}
            </div>
        `;
    }


    async openPaymentSetupDialog(existingSetup = null) {
        if (!this.canManagePaymentSetup) {
            frappe.msgprint(__("ليس لديك صلاحية إدارة وسائل الدفع الإلكترونية."));
            return;
        }

        const options = await this.getPaymentSetupOptions(null, existingSetup);
        const current = options.setup || {};
        const editing = Boolean(current.name);
        let dialog;

        dialog = new frappe.ui.Dialog({
            title: editing ? __("تعديل إعداد وسيلة الدفع") : __("إضافة وسيلة دفع إلكترونية"),
            size: "extra-large",
            fields: [
                {
                    fieldname: "existing_setup",
                    fieldtype: "Data",
                    hidden: 1,
                    default: current.name || "",
                },
                { fieldtype: "Section Break", label: __("بيانات وسيلة الدفع") },
                {
                    fieldname: "company",
                    label: __("الشركة"),
                    fieldtype: "Link",
                    options: "Company",
                    reqd: 1,
                    read_only: editing ? 1 : 0,
                    default: current.company || options.company,
                    onchange: () => this.reloadPaymentSetupCompanyDefaults(dialog),
                },
                {
                    fieldname: "mode_of_payment",
                    label: __("طريقة الدفع"),
                    fieldtype: "Link",
                    options: "Mode of Payment",
                    reqd: 1,
                    read_only: editing ? 1 : 0,
                    default: current.mode_of_payment || options.default_mode_of_payment,
                    onchange: () => this.syncPaymentSetupNames(dialog),
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "settlement_policy",
                    label: __("سياسة التسوية"),
                    fieldtype: "Select",
                    options: "At Shift Closing\nOn Actual Bank Settlement",
                    reqd: 1,
                    default: current.settlement_policy || options.default_settlement_policy,
                },
                {
                    fieldname: "enabled",
                    label: __("مفعّل"),
                    fieldtype: "Check",
                    default: editing ? Number(current.enabled || 0) : 1,
                },
                { fieldtype: "Section Break", label: __("الحساب النهائي") },
                {
                    fieldname: "destination_mode",
                    label: __("طريقة ربط الحساب النهائي"),
                    fieldtype: "Select",
                    options: "Use Bank Account\nUse Existing Account\nCreate New Account",
                    reqd: 1,
                    default: current.destination_mode || "Use Bank Account",
                },
                {
                    fieldname: "bank_account",
                    label: __("Bank Account"),
                    fieldtype: "Link",
                    options: "Bank Account",
                    default: current.bank_account || "",
                    depends_on: "eval:doc.destination_mode=='Use Bank Account'",
                    mandatory_depends_on: "eval:doc.destination_mode=='Use Bank Account'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            disabled: 0,
                            is_company_account: 1,
                        },
                    }),
                },
                {
                    fieldname: "existing_destination_account",
                    label: __("حساب نهائي موجود"),
                    fieldtype: "Link",
                    options: "Account",
                    default: current.destination_account || "",
                    depends_on: "eval:doc.destination_mode=='Use Existing Account'",
                    mandatory_depends_on: "eval:doc.destination_mode=='Use Existing Account'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Asset",
                            is_group: 0,
                            disabled: 0,
                        },
                    }),
                },
                {
                    fieldname: "destination_account_name",
                    label: __("اسم الحساب النهائي الجديد"),
                    fieldtype: "Data",
                    depends_on: "eval:doc.destination_mode=='Create New Account'",
                    mandatory_depends_on: "eval:doc.destination_mode=='Create New Account'",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "destination_parent_account",
                    label: __("الحساب الأب للحساب النهائي"),
                    fieldtype: "Link",
                    options: "Account",
                    default: options.default_destination_parent_account || "",
                    depends_on: "eval:doc.destination_mode=='Create New Account'",
                    mandatory_depends_on: "eval:doc.destination_mode=='Create New Account'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Asset",
                            is_group: 1,
                            disabled: 0,
                        },
                    }),
                },
                { fieldtype: "Section Break", label: __("حساب Clearing") },
                {
                    fieldname: "clearing_mode",
                    label: __("طريقة ربط حساب Clearing"),
                    fieldtype: "Select",
                    options: "Use Existing Account\nCreate New Account",
                    reqd: 1,
                    default: "Use Existing Account",
                },
                {
                    fieldname: "existing_clearing_account",
                    label: __("حساب Clearing موجود"),
                    fieldtype: "Link",
                    options: "Account",
                    default: current.clearing_account || "",
                    depends_on: "eval:doc.clearing_mode=='Use Existing Account'",
                    mandatory_depends_on: "eval:doc.clearing_mode=='Use Existing Account'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Asset",
                            is_group: 0,
                            disabled: 0,
                        },
                    }),
                },
                {
                    fieldname: "clearing_account_name",
                    label: __("اسم حساب Clearing الجديد"),
                    fieldtype: "Data",
                    depends_on: "eval:doc.clearing_mode=='Create New Account'",
                    mandatory_depends_on: "eval:doc.clearing_mode=='Create New Account'",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "clearing_parent_account",
                    label: __("الحساب الأب لـ Clearing"),
                    fieldtype: "Link",
                    options: "Account",
                    default: options.default_clearing_parent_account || "",
                    depends_on: "eval:doc.clearing_mode=='Create New Account'",
                    mandatory_depends_on: "eval:doc.clearing_mode=='Create New Account'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Asset",
                            is_group: 1,
                            disabled: 0,
                        },
                    }),
                },
                {
                    fieldname: "fee_account",
                    label: __("حساب الرسوم"),
                    fieldtype: "Link",
                    options: "Account",
                    default: current.fee_account || options.default_fee_account || "",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            root_type: "Expense",
                            is_group: 0,
                            disabled: 0,
                        },
                    }),
                },
                { fieldtype: "Section Break", label: __("ملاحظات") },
                {
                    fieldname: "notes",
                    label: __("ملاحظات"),
                    fieldtype: "Small Text",
                    default: current.notes || "",
                },
            ],
            primary_action_label: editing ? __("معاينة التعديل") : __("معاينة الإنشاء"),
            primary_action: async (values) => this.previewPaymentSetup(dialog, values),
        });

        dialog.show();
        if (!editing) this.syncPaymentSetupNames(dialog);
    }

    async getPaymentSetupOptions(company = null, setupName = null) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_payment_method_setup_options",
            args: { company, setup_name: setupName },
            freeze: true,
            freeze_message: __("جاري تجهيز إعداد وسيلة الدفع..."),
        });
        return response.message || {};
    }

    async reloadPaymentSetupCompanyDefaults(dialog) {
        const company = dialog.get_value("company");
        if (!company) return;
        const options = await this.getPaymentSetupOptions(company);
        dialog.set_value("clearing_parent_account", options.default_clearing_parent_account || "");
        dialog.set_value("destination_parent_account", options.default_destination_parent_account || "");
        dialog.set_value("fee_account", options.default_fee_account || "");
        dialog.set_value("bank_account", "");
        dialog.set_value("existing_destination_account", "");
        dialog.set_value("existing_clearing_account", "");
    }

    syncPaymentSetupNames(dialog) {
        const mode = String(dialog.get_value("mode_of_payment") || "").trim();
        if (!mode) return;
        const base = mode.replace(/\s+/g, " ");
        const suggestions = {
            clearing_account_name: `${base} Clearing`,
            destination_account_name: `${base} Account`,
        };
        Object.entries(suggestions).forEach(([fieldname, value]) => {
            const current = String(dialog.get_value(fieldname) || "").trim();
            if (!current || current === this.autoPaymentNames[fieldname]) {
                this.autoPaymentNames[fieldname] = value;
                dialog.set_value(fieldname, value);
            }
        });
    }

    async previewPaymentSetup(sourceDialog, values) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.preview_payment_method_setup",
            args: values,
            freeze: true,
            freeze_message: __("جاري مراجعة إعداد وسيلة الدفع..."),
        });
        this.showPaymentSetupConfirmation(sourceDialog, values, response.message || {});
    }

    showPaymentSetupConfirmation(sourceDialog, sourceValues, preview) {
        const updating = preview.action === "update";
        const confirmDialog = new frappe.ui.Dialog({
            title: updating ? __("تأكيد تعديل وسيلة الدفع") : __("تأكيد إنشاء وسيلة الدفع"),
            size: "extra-large",
            fields: [{ fieldtype: "HTML", options: this.renderPaymentSetupPreview(preview) }],
            primary_action_label: updating ? __("حفظ التعديلات") : __("إنشاء الإعداد"),
            primary_action: async () => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.save_payment_method_setup",
                    args: sourceValues,
                    freeze: true,
                    freeze_message: updating
                        ? __("جاري حفظ تعديلات وسيلة الدفع...")
                        : __("جاري إنشاء إعداد وسيلة الدفع..."),
                });
                confirmDialog.hide();
                sourceDialog.hide();
                const result = response.message || {};
                frappe.msgprint({
                    title: updating ? __("تم تعديل وسيلة الدفع") : __("تم إنشاء وسيلة الدفع"),
                    indicator: "green",
                    message: `
                        <div style="direction:rtl;text-align:right;">
                            <div>${this.esc(result.message || __("تم الحفظ بنجاح"))}</div>
                            <div><strong>${__("الإعداد")}:</strong> ${this.esc(result.setup || "-")}</div>
                            <div><strong>${__("Clearing")}:</strong> ${this.esc(result.clearing_account || "-")}</div>
                            <div><strong>${__("الحساب النهائي")}:</strong> ${this.esc(result.destination_account || "-")}</div>
                        </div>
                    `,
                });
                await this.refresh();
            },
        });
        confirmDialog.show();
    }

    renderPaymentSetupPreview(preview) {
        const accountLabel = (plan) => {
            if (!plan) return "-";
            const action = plan.action === "reuse" ? __("استخدام الموجود") : __("إنشاء جديد");
            return `${plan.document_name || plan.account_name || "-"} — ${action}`;
        };
        const rows = [
            [__("العملية"), preview.action === "update" ? __("تعديل إعداد موجود") : __("إنشاء إعداد جديد")],
            [__("الشركة"), preview.company],
            [__("طريقة الدفع"), preview.mode_of_payment],
            [__("سياسة التسوية"), preview.settlement_policy],
            [__("الحالة"), preview.enabled ? __("Active") : __("Disabled")],
            [__("حساب Clearing"), accountLabel(preview.clearing_account)],
            [__("الحساب النهائي"), accountLabel(preview.destination_account)],
            [__("Bank Account"), preview.bank_account || "-"],
            [__("حساب الرسوم"), preview.fee_account || "-"],
        ];
        const terminalWarning = Number(preview.card_terminal_count || 0) > 0
            ? `<div class="tmv3-preview-note"><strong>${__("تنبيه")}:</strong> ${__("طريقة الدفع هذه مرتبطة بماكينات فيزا. إعداد الماكينة المخصص يظل هو المرجع لعمليات Card POS Terminal.")}</div>`
            : "";
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
                ${__("لن يتم إنشاء قيد محاسبي. الحساب الوسيط يستقبل التحصيل مؤقتًا، والحساب النهائي يمثل البنك أو المحفظة التي تصل إليها التسوية.")}
            </div>
            ${terminalWarning}
        `;
    }

    render(data) {
        this.$main.html(`
            <div class="tmv3">
                <div class="tmv3-hero">
                    <h2>${__("إدارة الخزائن والبنوك ووسائل الدفع")}</h2>
                    <p>
                        ${__("يمكن إدارة الخزائن والبنوك وحساباتها، ومراجعة الأرصدة والحركات، وإنشاء الحسابات بعد المعاينة والتأكيد.")}
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
                    ${this.card(__("البنوك المسجلة"), data.bank_institutions, __("Bank"))}
                    ${this.card(__("حسابات البنوك"), data.bank_ledger_accounts, __("Bank Ledger Accounts"))}
                    ${this.card(__("Bank Accounts"), data.bank_accounts, __("ERPNext Bank Account"))}
                    ${this.card(__("ماكينات الفيزا"), data.card_terminals, __("Card POS Terminal"))}
                    ${this.card(__("دفعات فيزا مفتوحة"), data.open_card_batches, __("Unsettled Batches"))}
                    ${this.card(__("إعدادات التسوية"), data.clearing_setups, __("Clearing Setup"))}
                    ${this.card(__("تسويات دفع مفتوحة"), data.open_payment_reconciliations, __("Shift Reconciliation"))}
                </div>

                ${this.renderDrawers(data.drawers || [])}
                ${this.renderBanks(data.banks || [])}
                ${this.renderTerminals(data.terminals || [])}
                ${this.renderPaymentSetups(data.payment_setups || [])}
                ${this.renderUnlinkedBankLedgers(data.unlinked_bank_ledgers || [])}
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

        const body = rows.map((row) => {
            const balanceClass = Number(row.current_balance || 0) < 0
                ? "tmv3-balance-negative"
                : "tmv3-balance-positive";
            const lastMovement = row.last_movement || {};
            const toggleButton = this.canManageCashDrawer
                ? `
                    <button
                        class="tmv3-action-btn tmv3-drawer-toggle ${row.enabled ? "tmv3-action-danger" : "tmv3-action-success"}"
                        data-drawer="${this.esc(row.name)}"
                        data-enabled="${row.enabled ? 1 : 0}"
                    >
                        ${row.enabled ? __("تعطيل") : __("تفعيل")}
                    </button>
                `
                : "";

            return `
                <tr>
                    <td>
                        <a href="/app/cash-drawer/${encodeURIComponent(row.name)}">
                            ${this.esc(row.drawer_name || row.name)}
                        </a>
                    </td>
                    <td>${this.esc(row.drawer_code || "-")}</td>
                    <td>${this.esc(row.company || "-")}</td>
                    <td>${this.esc(row.cash_account || "-")}</td>
                    <td class="${balanceClass}">
                        ${this.formatMoney(row.current_balance, row.account_currency)}
                    </td>
                    <td>${this.esc(lastMovement.posting_date || "-")}</td>
                    <td>${this.esc(row.current_responsible_user || "-")}</td>
                    <td>${this.esc(row.current_active_shift || "-")}</td>
                    <td>
                        <span class="tmv3-badge ${row.enabled ? "tmv3-badge-on" : "tmv3-badge-off"}">
                            ${row.enabled ? __("Active") : __("Disabled")}
                        </span>
                    </td>
                    <td>
                        <div class="tmv3-actions">
                            <button
                                class="tmv3-action-btn tmv3-drawer-activity"
                                data-drawer="${this.esc(row.name)}"
                            >${__("الرصيد والحركات")}</button>
                            ${toggleButton}
                        </div>
                    </td>
                </tr>
            `;
        }).join("");

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
                                <th>${__("الحساب")}</th>
                                <th>${__("الرصيد الحالي")}</th>
                                <th>${__("آخر حركة")}</th>
                                <th>${__("المسؤول الحالي")}</th>
                                <th>${__("الوردية الحالية")}</th>
                                <th>${__("الحالة")}</th>
                                <th>${__("إجراءات")}</th>
                            </tr>
                        </thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            </div>
        `;
    }


    renderBanks(rows) {
        if (!rows.length) {
            return `
                <div class="tmv3-section">
                    <h4>${__("البنوك والحسابات البنكية")}</h4>
                    <div class="tmv3-empty">${__("لا توجد Bank Accounts مسجلة حتى الآن. استخدم زر إضافة بنك وحساب لربط الحسابات الحالية أو إنشاء حساب جديد.")}</div>
                </div>
            `;
        }
        const body = rows.map((row) => {
            const balanceClass = Number(row.current_balance || 0) < 0
                ? "tmv3-balance-negative"
                : "tmv3-balance-positive";
            const lastMovement = row.last_movement || {};
            return `
                <tr>
                    <td><a href="/app/bank/${encodeURIComponent(row.bank || "")}">${this.esc(row.bank || "-")}</a></td>
                    <td><a href="/app/bank-account/${encodeURIComponent(row.name)}">${this.esc(row.account_name || row.name)}</a></td>
                    <td>${this.esc(row.company || "-")}</td>
                    <td>${this.esc(row.account || "-")}</td>
                    <td class="${balanceClass}">${this.formatMoney(row.current_balance, row.account_currency)}</td>
                    <td>${this.esc(row.bank_account_no || "-")}</td>
                    <td>${this.esc(row.iban || "-")}</td>
                    <td>${this.esc(lastMovement.posting_date || "-")}</td>
                    <td><span class="tmv3-badge ${row.disabled ? "tmv3-badge-off" : "tmv3-badge-on"}">${row.disabled ? __("Disabled") : __("Active")}</span></td>
                    <td><button class="tmv3-action-btn tmv3-bank-activity" data-bank-account="${this.esc(row.name)}">${__("الرصيد والحركات")}</button></td>
                </tr>
            `;
        }).join("");
        return `
            <div class="tmv3-section">
                <h4>${__("البنوك والحسابات البنكية")}</h4>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table">
                        <thead><tr>
                            <th>${__("البنك")}</th><th>${__("Bank Account")}</th><th>${__("الشركة")}</th>
                            <th>${__("حساب الأستاذ")}</th><th>${__("الرصيد")}</th><th>${__("رقم الحساب")}</th>
                            <th>${__("IBAN")}</th><th>${__("آخر حركة")}</th><th>${__("الحالة")}</th><th>${__("إجراءات")}</th>
                        </tr></thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            </div>
        `;
    }


    renderTerminals(rows) {
        if (!rows.length) {
            return `
                <div class="tmv3-section">
                    <h4>${__("ماكينات الفيزا والـ Card Clearing")}</h4>
                    <div class="tmv3-empty">${__("لا توجد ماكينات فيزا مسجلة حتى الآن.")}</div>
                </div>
            `;
        }

        const body = rows.map((row) => {
            const balanceClass = Number(row.current_balance || 0) < 0
                ? "tmv3-balance-negative"
                : "tmv3-balance-positive";
            const openBadge = Number(row.open_batch_count || 0) > 0
                ? `<span class="tmv3-badge tmv3-badge-off">${this.esc(row.open_batch_count)} ${__("مفتوحة")}</span>`
                : `<span class="tmv3-badge tmv3-badge-on">${__("لا توجد دفعات مفتوحة")}</span>`;
            const lateBadge = Number(row.late_batch_count || 0) > 0
                ? `<br><span class="text-danger">${this.esc(row.late_batch_count)} ${__("من يوم سابق")}</span>`
                : "";
            const toggle = this.canManageCardTerminal
                ? `<button class="tmv3-action-btn tmv3-terminal-toggle ${row.enabled ? "tmv3-action-danger" : "tmv3-action-success"}" data-terminal="${this.esc(row.name)}" data-enabled="${row.enabled ? 1 : 0}">${row.enabled ? __("تعطيل") : __("تفعيل")}</button>`
                : "";
            const edit = this.canManageCardTerminal
                ? `<button class="tmv3-action-btn tmv3-terminal-edit" data-terminal="${this.esc(row.name)}">${__("تعديل")}</button>`
                : "";

            return `
                <tr>
                    <td><a href="/app/card-pos-terminal/${encodeURIComponent(row.name)}">${this.esc(row.terminal_name || row.name)}</a></td>
                    <td>${this.esc(row.terminal_code || "-")}</td>
                    <td>${this.esc(row.bank_label || "-")}</td>
                    <td>${this.esc(row.bank_account_name || row.bank_account || "-")}</td>
                    <td>${this.esc(row.mode_of_payment || "-")}</td>
                    <td>${this.esc(row.clearing_account || "-")}</td>
                    <td class="${balanceClass}">${this.formatMoney(row.current_balance, row.account_currency)}</td>
                    <td>${openBadge}${lateBadge}<br><small>${this.formatMoney(row.open_outstanding_amount, row.account_currency)}</small></td>
                    <td><span class="tmv3-badge ${row.enabled ? "tmv3-badge-on" : "tmv3-badge-off"}">${row.enabled ? __("Active") : __("Disabled")}</span></td>
                    <td><div class="tmv3-actions">
                        <button class="tmv3-action-btn tmv3-terminal-activity" data-terminal="${this.esc(row.name)}">${__("الرصيد والدفعات")}</button>
                        ${edit}${toggle}
                    </div></td>
                </tr>
            `;
        }).join("");

        return `
            <div class="tmv3-section">
                <h4>${__("ماكينات الفيزا والـ Card Clearing")}</h4>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table" style="min-width:1180px;">
                        <thead><tr>
                            <th>${__("الماكينة")}</th><th>${__("الكود")}</th><th>${__("البنك")}</th>
                            <th>${__("Bank Account")}</th><th>${__("طريقة الدفع")}</th><th>${__("Clearing")}</th>
                            <th>${__("رصيد Clearing")}</th><th>${__("الدفعات المفتوحة")}</th><th>${__("الحالة")}</th><th>${__("إجراءات")}</th>
                        </tr></thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
                <div class="tmv3-preview-note">${__("الدفعة تُعرض كـ «من يوم سابق» عندما تظل غير مسوّاة بعد تاريخ الإغلاق. تعطيل الماكينة ممنوع طالما توجد دفعات مفتوحة.")}</div>
            </div>
        `;
    }


    renderPaymentSetups(rows) {
        if (!rows.length) {
            return `
                <div class="tmv3-section">
                    <h4>${__("InstaPay والمحافظ والتحويلات")}</h4>
                    <div class="tmv3-empty">${__("لا توجد إعدادات Payment Clearing مسجلة حتى الآن.")}</div>
                </div>
            `;
        }

        const body = rows.map((row) => {
            const clearingClass = Number(row.clearing_balance || 0) < 0
                ? "tmv3-balance-negative" : "tmv3-balance-positive";
            const openBadge = Number(row.open_reconciliation_count || 0) > 0
                ? `<span class="tmv3-badge tmv3-badge-off">${this.esc(row.open_reconciliation_count)} ${__("مفتوحة")}</span>`
                : `<span class="tmv3-badge tmv3-badge-on">${__("لا توجد تسويات مفتوحة")}</span>`;
            const cardNote = Number(row.card_terminal_count || 0) > 0
                ? `<br><small>${this.esc(row.card_terminal_count)} ${__("ماكينة مرتبطة")}</small>` : "";
            const edit = this.canManagePaymentSetup
                ? `<button class="tmv3-action-btn tmv3-payment-edit" data-setup="${this.esc(row.name)}">${__("تعديل")}</button>` : "";
            const toggle = this.canManagePaymentSetup
                ? `<button class="tmv3-action-btn tmv3-payment-toggle ${row.enabled ? "tmv3-action-danger" : "tmv3-action-success"}" data-setup="${this.esc(row.name)}" data-enabled="${row.enabled ? 1 : 0}">${row.enabled ? __("تعطيل") : __("تفعيل")}</button>` : "";
            return `
                <tr>
                    <td><a href="/app/payment-method-clearing-setup/${encodeURIComponent(row.name)}">${this.esc(row.mode_of_payment || row.name)}</a>${cardNote}</td>
                    <td>${this.esc(row.settlement_policy || "-")}</td>
                    <td>${this.esc(row.clearing_account || "-")}</td>
                    <td class="${clearingClass}">${this.formatMoney(row.clearing_balance, row.account_currency)}</td>
                    <td>${this.esc(row.destination_account || "-")}</td>
                    <td>${this.formatMoney(row.destination_balance, row.account_currency)}</td>
                    <td>${this.esc(row.fee_account || "-")}</td>
                    <td>${openBadge}<br><small>${this.formatMoney(row.open_expected_amount, row.account_currency)}</small></td>
                    <td><span class="tmv3-badge ${row.enabled ? "tmv3-badge-on" : "tmv3-badge-off"}">${row.enabled ? __("Active") : __("Disabled")}</span></td>
                    <td><div class="tmv3-actions">
                        <button class="tmv3-action-btn tmv3-payment-activity" data-setup="${this.esc(row.name)}">${__("الأرصدة والتسويات")}</button>
                        ${edit}${toggle}
                    </div></td>
                </tr>
            `;
        }).join("");

        return `
            <div class="tmv3-section">
                <h4>${__("InstaPay والمحافظ والتحويلات وPayment Clearing")}</h4>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table" style="min-width:1250px;">
                        <thead><tr>
                            <th>${__("طريقة الدفع")}</th><th>${__("سياسة التسوية")}</th>
                            <th>${__("Clearing")}</th><th>${__("رصيد Clearing")}</th>
                            <th>${__("الحساب النهائي")}</th><th>${__("رصيد الحساب النهائي")}</th>
                            <th>${__("حساب الرسوم")}</th><th>${__("التسويات المفتوحة")}</th>
                            <th>${__("الحالة")}</th><th>${__("إجراءات")}</th>
                        </tr></thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
                <div class="tmv3-preview-note">${__("مثال: تحصيل InstaPay يدخل أولًا إلى InstaPay Clearing، ثم ينتقل إلى الحساب البنكي النهائي عند المراجعة أو التسوية حسب السياسة المحددة.")}</div>
            </div>
        `;
    }

    bindPaymentSetupActions() {
        this.$main.find(".tmv3-payment-activity").off("click").on("click", (event) => {
            this.openPaymentSetupActivity($(event.currentTarget).attr("data-setup"));
        });
        this.$main.find(".tmv3-payment-edit").off("click").on("click", (event) => {
            this.openPaymentSetupDialog($(event.currentTarget).attr("data-setup"));
        });
        this.$main.find(".tmv3-payment-toggle").off("click").on("click", (event) => {
            const $button = $(event.currentTarget);
            this.confirmPaymentSetupToggle(
                $button.attr("data-setup"),
                Number($button.attr("data-enabled") || 0) === 1,
            );
        });
    }

    async openPaymentSetupActivity(setup) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_payment_method_setup_activity",
            args: { setup_name: setup, limit: 20 },
            freeze: true,
            freeze_message: __("جاري تحميل أرصدة وسيلة الدفع..."),
        });
        const data = response.message || {};
        const reconciliations = (data.open_reconciliations || []).length
            ? data.open_reconciliations.map((row) => `
                <tr>
                    <td><a href="/app/shift-payment-reconciliation/${encodeURIComponent(row.name)}">${this.esc(row.name)}</a></td>
                    <td>${this.esc(row.shift_reference || "-")}</td>
                    <td>${this.esc(row.status || "-")}</td>
                    <td>${this.formatMoney(row.expected_amount, data.account_currency)}</td>
                    <td>${this.formatMoney(row.reviewed_amount, data.account_currency)}</td>
                    <td>${this.formatMoney(row.difference, data.account_currency)}</td>
                </tr>
            `).join("")
            : `<tr><td colspan="6" class="tmv3-empty">${__("لا توجد تسويات وردية مفتوحة لهذه الوسيلة.")}</td></tr>`;
        const movementRows = (rows) => (rows || []).length
            ? rows.map((row) => `
                <tr><td>${this.esc(row.posting_date || "-")}</td><td>${this.esc(row.voucher_type || "-")}</td>
                <td>${this.esc(row.voucher_no || "-")}</td><td>${this.formatMoney(row.debit, data.account_currency)}</td>
                <td>${this.formatMoney(row.credit, data.account_currency)}</td><td>${this.esc(row.against || "-")}</td></tr>
            `).join("")
            : `<tr><td colspan="6" class="tmv3-empty">${__("لا توجد حركات دفتر أستاذ حتى الآن.")}</td></tr>`;

        const dialog = new frappe.ui.Dialog({
            title: `${__("أرصدة وتسويات وسيلة الدفع")}: ${this.esc(data.mode_of_payment || "")}`,
            size: "extra-large",
            fields: [{
                fieldtype: "HTML",
                options: `
                    <div style="direction:rtl;text-align:right;">
                        <div class="tmv3-preview" style="margin-bottom:14px;">
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("حساب Clearing")}</div><div class="tmv3-preview-value">${this.esc(data.clearing_account || "-")} — ${this.formatMoney(data.clearing_balance, data.account_currency)}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الحساب النهائي")}</div><div class="tmv3-preview-value">${this.esc(data.destination_account || "-")} — ${this.formatMoney(data.destination_balance, data.account_currency)}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("سياسة التسوية")}</div><div class="tmv3-preview-value">${this.esc(data.settlement_policy || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("التسويات المفتوحة")}</div><div class="tmv3-preview-value">${this.esc(data.open_reconciliation_count || 0)} — ${this.formatMoney(data.open_expected_amount, data.account_currency)}</div></div>
                        </div>
                        <h5>${__("تسويات الوردية المفتوحة")}</h5>
                        <div class="tmv3-table-wrap"><table class="tmv3-activity-table">
                            <thead><tr><th>${__("التسوية")}</th><th>${__("الوردية")}</th><th>${__("الحالة")}</th><th>${__("المتوقع")}</th><th>${__("المراجع")}</th><th>${__("الفرق")}</th></tr></thead>
                            <tbody>${reconciliations}</tbody>
                        </table></div>
                        <h5 style="margin-top:18px;">${__("آخر حركات حساب Clearing")}</h5>
                        <div class="tmv3-table-wrap"><table class="tmv3-activity-table"><thead><tr><th>${__("التاريخ")}</th><th>${__("النوع")}</th><th>${__("المستند")}</th><th>${__("مدين")}</th><th>${__("دائن")}</th><th>${__("المقابل")}</th></tr></thead><tbody>${movementRows(data.clearing_movements)}</tbody></table></div>
                        <h5 style="margin-top:18px;">${__("آخر حركات الحساب النهائي")}</h5>
                        <div class="tmv3-table-wrap"><table class="tmv3-activity-table"><thead><tr><th>${__("التاريخ")}</th><th>${__("النوع")}</th><th>${__("المستند")}</th><th>${__("مدين")}</th><th>${__("دائن")}</th><th>${__("المقابل")}</th></tr></thead><tbody>${movementRows(data.destination_movements)}</tbody></table></div>
                    </div>
                `,
            }],
        });
        dialog.show();
    }

    confirmPaymentSetupToggle(setup, isEnabled) {
        const message = isEnabled
            ? __("لن يمكن تعطيل الإعداد إذا كانت هناك Shift Payment Reconciliation مفتوحة. هل تريد المتابعة؟")
            : __("سيتم التحقق من الحسابات وطريقة الدفع ثم تفعيل الإعداد. هل تريد المتابعة؟");
        frappe.confirm(`${message}<br><br><strong>${this.esc(setup)}</strong>`, async () => {
            await frappe.call({
                method:
                    "pharma_erp.pharma_erp.page.treasury_management.treasury_management.set_payment_method_setup_enabled",
                args: { setup_name: setup, enabled: isEnabled ? 0 : 1 },
                freeze: true,
                freeze_message: __("جاري تحديث حالة إعداد وسيلة الدفع..."),
            });
            frappe.show_alert({ message: __("تم تحديث حالة وسيلة الدفع"), indicator: "green" });
            await this.refresh();
        });
    }

    bindTerminalActions() {
        this.$main.find(".tmv3-terminal-activity").off("click").on("click", (event) => {
            this.openTerminalActivity($(event.currentTarget).attr("data-terminal"));
        });
        this.$main.find(".tmv3-terminal-edit").off("click").on("click", (event) => {
            this.openCardTerminalDialog($(event.currentTarget).attr("data-terminal"));
        });
        this.$main.find(".tmv3-terminal-toggle").off("click").on("click", (event) => {
            const $button = $(event.currentTarget);
            this.confirmTerminalToggle(
                $button.attr("data-terminal"),
                Number($button.attr("data-enabled") || 0) === 1,
            );
        });
    }

    async openTerminalActivity(terminal) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_card_terminal_activity",
            args: { terminal_name: terminal, limit: 20 },
            freeze: true,
            freeze_message: __("جاري تحميل رصيد Clearing والدفعات..."),
        });
        const data = response.message || {};
        const batchRows = (data.open_batches || []).length
            ? data.open_batches.map((row) => `
                <tr>
                    <td><a href="/app/card-settlement-batch/${encodeURIComponent(row.name)}">${this.esc(row.name)}</a></td>
                    <td>${this.esc(row.shift_reference || "-")}</td>
                    <td>${this.esc(row.close_time || "-")}</td>
                    <td>${this.esc(row.status || "-")}</td>
                    <td>${this.formatMoney(row.machine_total, data.account_currency)}</td>
                    <td>${this.formatMoney(row.outstanding_amount, data.account_currency)}</td>
                    <td>${row.is_late ? `<span class="text-danger">${this.esc(row.age_days)} ${__("يوم")}</span>` : this.esc(row.age_days || 0)}</td>
                </tr>
            `).join("")
            : `<tr><td colspan="7" class="tmv3-empty">${__("لا توجد دفعات مفتوحة لهذه الماكينة.")}</td></tr>`;
        const movementRows = (data.movements || []).length
            ? data.movements.map((row) => `
                <tr><td>${this.esc(row.posting_date || "-")}</td><td>${this.esc(row.voucher_type || "-")}</td>
                <td>${this.esc(row.voucher_no || "-")}</td><td>${this.formatMoney(row.debit, data.account_currency)}</td>
                <td>${this.formatMoney(row.credit, data.account_currency)}</td><td>${this.esc(row.against || "-")}</td></tr>
            `).join("")
            : `<tr><td colspan="6" class="tmv3-empty">${__("لا توجد حركات دفتر أستاذ حتى الآن.")}</td></tr>`;

        const dialog = new frappe.ui.Dialog({
            title: `${__("رصيد Clearing ودفعات الماكينة")}: ${this.esc(data.terminal_name || data.terminal || "")}`,
            size: "extra-large",
            fields: [{
                fieldtype: "HTML",
                options: `
                    <div style="direction:rtl;text-align:right;">
                        <div class="tmv3-preview" style="margin-bottom:14px;">
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("حساب Clearing")}</div><div class="tmv3-preview-value">${this.esc(data.clearing_account || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الرصيد الحالي")}</div><div class="tmv3-preview-value">${this.formatMoney(data.current_balance, data.account_currency)}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الدفعات المفتوحة")}</div><div class="tmv3-preview-value">${this.esc(data.open_batch_count || 0)} — ${this.formatMoney(data.open_outstanding_amount, data.account_currency)}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("دفعات من يوم سابق")}</div><div class="tmv3-preview-value">${this.esc(data.late_batch_count || 0)}</div></div>
                        </div>
                        <h5>${__("الدفعات المفتوحة")}</h5>
                        <div class="tmv3-table-wrap"><table class="tmv3-activity-table">
                            <thead><tr><th>${__("الدفعة")}</th><th>${__("الوردية")}</th><th>${__("الإغلاق")}</th><th>${__("الحالة")}</th><th>${__("إجمالي الماكينة")}</th><th>${__("المتبقي")}</th><th>${__("العمر")}</th></tr></thead>
                            <tbody>${batchRows}</tbody>
                        </table></div>
                        <h5 style="margin-top:18px;">${__("آخر حركات حساب Clearing")}</h5>
                        <div class="tmv3-table-wrap"><table class="tmv3-activity-table">
                            <thead><tr><th>${__("التاريخ")}</th><th>${__("نوع المستند")}</th><th>${__("المستند")}</th><th>${__("مدين")}</th><th>${__("دائن")}</th><th>${__("الحساب المقابل")}</th></tr></thead>
                            <tbody>${movementRows}</tbody>
                        </table></div>
                    </div>
                `,
            }],
        });
        dialog.show();
    }

    confirmTerminalToggle(terminal, isEnabled) {
        const action = isEnabled ? __("تعطيل") : __("تفعيل");
        const message = isEnabled
            ? __("لن يمكن تعطيل الماكينة إذا كانت مرتبطة بدفعات Card Settlement غير مسوّاة. هل تريد المتابعة؟")
            : __("سيتم التحقق من الحسابات المرتبطة ثم تفعيل الماكينة. هل تريد المتابعة؟");
        frappe.confirm(`${message}<br><br><strong>${this.esc(terminal)}</strong>`, async () => {
            const response = await frappe.call({
                method:
                    "pharma_erp.pharma_erp.page.treasury_management.treasury_management.set_card_terminal_enabled",
                args: { terminal_name: terminal, enabled: isEnabled ? 0 : 1 },
                freeze: true,
                freeze_message: `${action} ${__("الماكينة...")}`,
            });
            frappe.show_alert({
                message: response.message?.message || __("تم تحديث حالة الماكينة"),
                indicator: "green",
            });
            await this.refresh();
        });
    }

    renderUnlinkedBankLedgers(rows) {
        if (!rows.length) return "";
        return `
            <div class="tmv3-section tmv3-warning">
                <h4>${__("حسابات Bank غير مربوطة بـ Bank Account")}</h4>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table">
                        <thead><tr><th>${__("الحساب")}</th><th>${__("الشركة")}</th><th>${__("الحساب الأب")}</th><th>${__("الرصيد")}</th></tr></thead>
                        <tbody>${rows.map((row) => `
                            <tr>
                                <td><a href="/app/account/${encodeURIComponent(row.name)}">${this.esc(row.name)}</a></td>
                                <td>${this.esc(row.company || "-")}</td>
                                <td>${this.esc(row.parent_account || "-")}</td>
                                <td>${this.formatMoney(row.current_balance, row.account_currency)}</td>
                            </tr>
                        `).join("")}</tbody>
                    </table>
                </div>
                <div class="tmv3-preview-note">${__("هذه الحسابات موجودة في Chart of Accounts لكنها غير مربوطة بسجل Bank وBank Account. يمكن ربطها بدون إنشاء حساب محاسبي مكرر.")}</div>
            </div>
        `;
    }

    bindBankActions() {
        this.$main.find(".tmv3-bank-activity")
            .off("click")
            .on("click", (event) => {
                this.openBankActivity($(event.currentTarget).attr("data-bank-account"));
            });
    }

    async openBankActivity(bankAccount) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_bank_account_activity",
            args: { bank_account_name: bankAccount, limit: 20 },
            freeze: true,
            freeze_message: __("جاري تحميل رصيد وحركات الحساب البنكي..."),
        });
        const data = response.message || {};
        const rows = (data.movements || []).length
            ? data.movements.map((row) => `
                <tr><td>${this.esc(row.posting_date || "-")}</td><td>${this.esc(row.voucher_type || "-")}</td>
                <td>${this.esc(row.voucher_no || "-")}</td><td>${this.formatMoney(row.debit, data.account_currency)}</td>
                <td>${this.formatMoney(row.credit, data.account_currency)}</td><td>${this.esc(row.against || "-")}</td></tr>
            `).join("")
            : `<tr><td colspan="6" class="tmv3-empty">${__("لا توجد حركات دفتر أستاذ حتى الآن.")}</td></tr>`;
        const dialog = new frappe.ui.Dialog({
            title: `${__("رصيد وحركات الحساب البنكي")}: ${this.esc(data.account_name || data.bank_account || "")}`,
            size: "extra-large",
            fields: [{
                fieldtype: "HTML",
                options: `
                    <div style="direction: rtl; text-align: right;">
                        <div class="tmv3-preview" style="margin-bottom:14px;">
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("البنك")}</div><div class="tmv3-preview-value">${this.esc(data.bank || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("حساب الأستاذ")}</div><div class="tmv3-preview-value">${this.esc(data.ledger_account || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الرصيد الحالي")}</div><div class="tmv3-preview-value">${this.formatMoney(data.current_balance, data.account_currency)}</div></div>
                        </div>
                        <div class="tmv3-table-wrap"><table class="tmv3-activity-table">
                            <thead><tr><th>${__("التاريخ")}</th><th>${__("نوع المستند")}</th><th>${__("المستند")}</th><th>${__("مدين")}</th><th>${__("دائن")}</th><th>${__("الحساب المقابل")}</th></tr></thead>
                            <tbody>${rows}</tbody>
                        </table></div>
                    </div>
                `,
            }],
        });
        dialog.show();
    }

    bindDrawerActions() {
        this.$main.find(".tmv3-drawer-activity")
            .off("click")
            .on("click", (event) => {
                this.openDrawerActivity($(event.currentTarget).attr("data-drawer"));
            });

        this.$main.find(".tmv3-drawer-toggle")
            .off("click")
            .on("click", (event) => {
                const $button = $(event.currentTarget);
                const drawer = $button.attr("data-drawer");
                const isEnabled = Number($button.attr("data-enabled") || 0) === 1;
                this.confirmDrawerToggle(drawer, isEnabled);
            });
    }

    async openDrawerActivity(drawer) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_cash_drawer_activity",
            args: { drawer_name: drawer, limit: 20 },
            freeze: true,
            freeze_message: __("جاري تحميل رصيد وحركات الخزنة..."),
        });

        const data = response.message || {};
        const movements = data.movements || [];
        const rows = movements.length
            ? movements.map((row) => `
                <tr>
                    <td>${this.esc(row.posting_date || "-")}</td>
                    <td>${this.esc(row.voucher_type || "-")}</td>
                    <td>${this.esc(row.voucher_no || "-")}</td>
                    <td>${this.formatMoney(row.debit, data.account_currency)}</td>
                    <td>${this.formatMoney(row.credit, data.account_currency)}</td>
                    <td>${this.esc(row.against || "-")}</td>
                </tr>
            `).join("")
            : `<tr><td colspan="6" class="tmv3-empty">${__("لا توجد حركات دفتر أستاذ حتى الآن.")}</td></tr>`;

        const dialog = new frappe.ui.Dialog({
            title: `${__("رصيد وحركات الخزنة")}: ${this.esc(data.drawer_name || data.drawer || "")}`,
            size: "extra-large",
            fields: [{
                fieldtype: "HTML",
                options: `
                    <div style="direction: rtl; text-align: right;">
                        <div class="tmv3-preview" style="margin-bottom: 14px;">
                            <div class="tmv3-preview-row">
                                <div class="tmv3-preview-label">${__("الحساب")}</div>
                                <div class="tmv3-preview-value">${this.esc(data.cash_account || "-")}</div>
                            </div>
                            <div class="tmv3-preview-row">
                                <div class="tmv3-preview-label">${__("الرصيد الحالي")}</div>
                                <div class="tmv3-preview-value">${this.formatMoney(data.current_balance, data.account_currency)}</div>
                            </div>
                            <div class="tmv3-preview-row">
                                <div class="tmv3-preview-label">${__("الوردية الحالية")}</div>
                                <div class="tmv3-preview-value">${this.esc(data.current_active_shift || "-")}</div>
                            </div>
                        </div>
                        <div class="tmv3-table-wrap">
                            <table class="tmv3-activity-table">
                                <thead>
                                    <tr>
                                        <th>${__("التاريخ")}</th>
                                        <th>${__("نوع المستند")}</th>
                                        <th>${__("المستند")}</th>
                                        <th>${__("مدين")}</th>
                                        <th>${__("دائن")}</th>
                                        <th>${__("الحساب المقابل")}</th>
                                    </tr>
                                </thead>
                                <tbody>${rows}</tbody>
                            </table>
                        </div>
                    </div>
                `,
            }],
        });
        dialog.show();
    }

    confirmDrawerToggle(drawer, isEnabled) {
        const action = isEnabled ? __("تعطيل") : __("تفعيل");
        const message = isEnabled
            ? __("سيتم تعطيل الخزنة فقط، ولن يتم تعطيل الحساب المحاسبي أو حذف الحركات السابقة. لا يمكن تعطيل خزنة عليها وردية مفتوحة. هل تريد المتابعة؟")
            : __("سيتم التحقق من سلامة الحساب المحاسبي ثم تفعيل الخزنة. هل تريد المتابعة؟");

        frappe.confirm(
            `${message}<br><br><strong>${this.esc(drawer)}</strong>`,
            async () => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.set_cash_drawer_enabled",
                    args: {
                        drawer_name: drawer,
                        enabled: isEnabled ? 0 : 1,
                    },
                    freeze: true,
                    freeze_message: `${action} ${__("الخزنة...")}`,
                });
                frappe.show_alert({
                    message: response.message?.message || __("تم تحديث حالة الخزنة"),
                    indicator: "green",
                });
                await this.refresh();
            },
        );
    }

    formatMoney(value, currency) {
        const number = Number(value || 0);
        if (typeof format_currency === "function") {
            return format_currency(number, currency || undefined);
        }
        return `${number.toFixed(2)} ${this.esc(currency || "")}`.trim();
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
