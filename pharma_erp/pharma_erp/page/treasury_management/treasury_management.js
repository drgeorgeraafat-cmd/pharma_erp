frappe.pages["treasury-management"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("إدارة الخزائن والبنوك ووسائل الدفع"),
        single_column: true,
    });

    new TreasuryManagementPageV15(page, wrapper);
};


class TreasuryManagementPageV15 {
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
        this.canPrepareSettlement = false;
        this.canExecuteSettlement = false;
        this.canManageInternalTransfer = false;
        this.canApproveInternalTransfer = false;
        this.canEmergencySubmitInternalTransfer = false;
        this.canManageShiftCashMovement = false;
        this.canApproveShiftCashMovement = false;
        this.canCancelShiftCashMovement = false;
        this.canEmergencySubmitShiftCashMovement = false;
        this.canManageTreasuryVoucher = false;
        this.canApproveTreasuryVoucher = false;
        this.canCancelTreasuryVoucher = false;
        this.canEmergencySubmitTreasuryVoucher = false;
        this.accessProfile = {};
        this.transferAccounts = {};
        this.cashMovementDrawers = {};
        this.cashMovementTypes = {};
        this.treasuryVoucherAccounts = {};
        this.treasuryVoucherCategories = {};
        this.treasuryVoucherCategoryMap = {};
        this.shiftCashMovementData = null;
        this.shiftCashMovementSectionOpen = false;
        this.shiftCashMovementLoading = false;
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
        this.$cardSettlementButton = this.page.add_inner_button(
            __("تسوية دفعات الفيزا"),
            () => this.openCardSettlementPicker(),
            __("ماكينات الفيزا"),
        );
        this.$internalTransferButton = this.page.add_inner_button(
            __("تحويل مالي جديد"),
            () => this.openInternalTransferDialog(),
            __("التحويلات"),
        );
        this.$cashMovementButton = this.page.add_inner_button(
            __("حركة نقدية جديدة"),
            () => this.openShiftCashMovementDialog(),
            __("حركات الوردية"),
        );
        this.$treasuryVoucherButton = this.page.add_inner_button(
            __("مصروف أو مقبوض عام جديد"),
            () => this.openTreasuryVoucherDialog(),
            __("المصروفات العامة"),
        );
        this.$treasuryCategoryButton = this.page.add_inner_button(
            __("إدارة التصنيفات"),
            () => frappe.set_route("List", "Treasury Voucher Category"),
            __("المصروفات العامة"),
        );
        this.$dailyTreasuryReportButton = this.page.add_inner_button(
            __("تقرير الخزينة اليومي"),
            () => frappe.set_route("query-report", "Treasury Daily Review"),
            __("التقارير"),
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
                .tmv3-balance-review { color: var(--orange-700); font-weight: 800; }
                .tmv3-alerts { display: grid; gap: 8px; margin-bottom: 14px; }
                .tmv3-alert {
                    border: 1px solid var(--border-color);
                    border-radius: 10px;
                    padding: 10px 12px;
                    display: grid;
                    grid-template-columns: auto 1fr auto;
                    gap: 10px;
                    align-items: center;
                }
                .tmv3-alert-critical { border-color: var(--red-300); background: var(--red-50); }
                .tmv3-alert-warning { border-color: var(--orange-300); background: var(--orange-50); }
                .tmv3-alert-info { border-color: var(--blue-200); background: var(--blue-50); }
                .tmv3-alert-title { font-weight: 800; }
                .tmv3-alert-message { color: var(--text-muted); font-size: 12px; margin-top: 2px; }
                .tmv3-alert-icon { font-size: 16px; }
                .tmv3-dashboard-note {
                    display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
                    color: var(--text-muted); font-size: 12px; margin-bottom: 12px;
                }
                .tmv3-dashboard-ok {
                    border: 1px solid var(--green-200); background: var(--green-50);
                    color: var(--green-700); border-radius: 10px; padding: 11px 12px;
                    margin-bottom: 12px; font-weight: 700;
                }
                .tmv3-activity-table { width: 100%; border-collapse: collapse; min-width: 760px; }
                .tmv3-activity-table th, .tmv3-activity-table td {
                    padding: 8px; border-bottom: 1px solid var(--border-color); text-align: right;
                }
                .tmv3-section-toggle {
                    width: 100%; border: 0; background: transparent; color: var(--text-color);
                    display: flex; align-items: center; justify-content: space-between; gap: 12px;
                    padding: 0; cursor: pointer; text-align: right;
                }
                .tmv3-section-toggle h4 { margin: 0; }
                .tmv3-section-toggle-meta {
                    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
                }
                .tmv3-collapse-icon { font-size: 14px; color: var(--text-muted); }
                .tmv3-filter-grid {
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 10px; margin: 14px 0 10px;
                }
                .tmv3-filter-field label {
                    display: block; color: var(--text-muted); font-size: 11px; margin-bottom: 5px;
                }
                .tmv3-filter-field input, .tmv3-filter-field select {
                    width: 100%; min-height: 34px; border: 1px solid var(--border-color);
                    border-radius: 8px; background: var(--control-bg); color: var(--text-color);
                    padding: 6px 9px;
                }
                .tmv3-filter-actions { display: flex; gap: 8px; align-items: end; flex-wrap: wrap; }
                .tmv3-summary-strip {
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(135px, 1fr));
                    gap: 8px; margin: 10px 0 12px;
                }
                .tmv3-summary-chip {
                    border: 1px solid var(--border-color); border-radius: 10px; padding: 9px 10px;
                    background: var(--control-bg);
                }
                .tmv3-summary-chip small { display: block; color: var(--text-muted); margin-bottom: 3px; }
                .tmv3-summary-chip strong { font-size: 14px; }
                .tmv3-pagination {
                    display: flex; justify-content: space-between; align-items: center;
                    gap: 10px; flex-wrap: wrap; margin-top: 12px;
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
            this.shiftCashMovementData = data.shift_cash_movement_data || {
                rows: data.shift_cash_movement_rows || [],
                summary: {},
                filters: {},
                pagination: {},
                options: {},
            };
            this.canCreateCashDrawer = Boolean(data.can_create_cash_drawer);
            this.canManageCashDrawer = Boolean(data.can_manage_cash_drawer);
            this.canCreateBank = Boolean(data.can_create_bank);
            this.canManageCardTerminal = Boolean(data.can_manage_card_terminal);
            this.canManagePaymentSetup = Boolean(data.can_manage_payment_setup);
            this.canPrepareSettlement = Boolean(data.can_prepare_settlement);
            this.canExecuteSettlement = Boolean(data.can_execute_settlement);
            this.canManageInternalTransfer = Boolean(data.can_manage_internal_transfer);
            this.canApproveInternalTransfer = Boolean(data.can_approve_internal_transfer);
            this.canEmergencySubmitInternalTransfer = Boolean(data.can_emergency_submit_internal_transfer);
            this.canManageShiftCashMovement = Boolean(data.can_manage_shift_cash_movement);
            this.canApproveShiftCashMovement = Boolean(data.can_approve_shift_cash_movement);
            this.canCancelShiftCashMovement = Boolean(data.can_cancel_shift_cash_movement);
            this.canEmergencySubmitShiftCashMovement = Boolean(data.can_emergency_submit_shift_cash_movement);
            this.canManageTreasuryVoucher = Boolean(data.can_manage_treasury_voucher);
            this.canApproveTreasuryVoucher = Boolean(data.can_approve_treasury_voucher);
            this.canCancelTreasuryVoucher = Boolean(data.can_cancel_treasury_voucher);
            this.canEmergencySubmitTreasuryVoucher = Boolean(data.can_emergency_submit_treasury_voucher);
            this.accessProfile = data.access_profile || {};
            this.page.btn_primary.toggle(this.canCreateCashDrawer);
            if (this.$bankButton) this.$bankButton.toggle(this.canCreateBank);
            if (this.$terminalButton) this.$terminalButton.toggle(this.canManageCardTerminal);
            if (this.$paymentSetupButton) this.$paymentSetupButton.toggle(this.canManagePaymentSetup);
            if (this.$cardSettlementButton) this.$cardSettlementButton.toggle(this.canPrepareSettlement);
            if (this.$internalTransferButton) this.$internalTransferButton.toggle(this.canManageInternalTransfer);
            if (this.$cashMovementButton) this.$cashMovementButton.toggle(this.canManageShiftCashMovement);
            if (this.$treasuryVoucherButton) this.$treasuryVoucherButton.toggle(this.canManageTreasuryVoucher);
            if (this.$treasuryCategoryButton) this.$treasuryCategoryButton.toggle(this.canApproveTreasuryVoucher);
            this.render(data);
            this.bindDrawerActions();
            this.bindBankActions();
            this.bindTerminalActions();
            this.bindPaymentSetupActions();
            this.bindSettlementActions();
            this.bindInternalTransferActions();
            this.bindShiftCashMovementActions();
            this.bindTreasuryVoucherActions();
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


    async getTreasuryVoucherOptions(company = null) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_treasury_voucher_options",
            args: { company },
            freeze: true,
            freeze_message: __("جاري تحميل حسابات الخزينة والبنوك..."),
        });
        return response.message || {};
    }

    setTreasuryVoucherMaps(options) {
        this.treasuryVoucherAccounts = {};
        (options.cash_bank_accounts || []).forEach((row) => {
            this.treasuryVoucherAccounts[row.name] = row;
        });
        this.treasuryVoucherCategories = options.categories || {};
        this.treasuryVoucherCategoryMap = {};
        Object.values(this.treasuryVoucherCategories).forEach((rows) => {
            (rows || []).forEach((row) => {
                this.treasuryVoucherCategoryMap[row.name] = row;
            });
        });
    }

    async openTreasuryVoucherDialog() {
        if (!this.canManageTreasuryVoucher) {
            frappe.msgprint(__("ليس لديك صلاحية إنشاء مصروفات أو مقبوضات عامة."));
            return;
        }

        const options = await this.getTreasuryVoucherOptions();
        this.setTreasuryVoucherMaps(options);
        const accounts = options.cash_bank_accounts || [];
        if (!accounts.length) {
            frappe.msgprint({
                title: __("لا توجد حسابات خزينة متاحة"),
                indicator: "orange",
                message: __("لا يوجد حساب Cash أو Bank تشغيلي متاح خارج وردية نشطة."),
            });
            return;
        }

        let dialog;
        dialog = new frappe.ui.Dialog({
            title: __("مصروف أو مقبوض عام خارج الوردية"),
            size: "extra-large",
            fields: [
                {
                    fieldname: "company",
                    fieldtype: "Link",
                    options: "Company",
                    label: __("الشركة"),
                    reqd: 1,
                    default: options.company,
                    onchange: async () => this.reloadTreasuryVoucherCompany(dialog),
                },
                {
                    fieldname: "voucher_action",
                    fieldtype: "Select",
                    label: __("إجراء المستند"),
                    options: this.canEmergencySubmitTreasuryVoucher
                        ? "Create Draft\nSubmit Now"
                        : "Create Draft",
                    default: "Create Draft",
                    reqd: 1,
                    read_only: !this.canEmergencySubmitTreasuryVoucher,
                    description: this.canEmergencySubmitTreasuryVoucher
                        ? __("المسار الطبيعي هو حفظ طلب للمراجعة. Submit Now مخصص لطوارئ System Manager ويُسجل في التدقيق.")
                        : __("سيُحفظ الطلب كمسودة ويعتمده مدير خزينة مختلف عن طالب المستند."),
                },
                { fieldtype: "Section Break", label: __("نوع العملية والحساب النقدي") },
                {
                    fieldname: "voucher_type",
                    fieldtype: "Select",
                    label: __("نوع المستند"),
                    options: "General Expense\nGeneral Receipt",
                    default: "General Expense",
                    reqd: 1,
                    onchange: () => this.updateTreasuryVoucherType(dialog),
                },
                {
                    fieldname: "category",
                    fieldtype: "Select",
                    label: __("التصنيف"),
                    reqd: 1,
                    onchange: () => this.updateTreasuryVoucherCategory(dialog),
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "cash_bank_account",
                    fieldtype: "Select",
                    label: __("الخزنة أو البنك"),
                    options: accounts.map((row) => row.name).join("\n"),
                    default: options.default_cash_bank_account || accounts[0].name,
                    reqd: 1,
                    onchange: () => this.updateTreasuryVoucherAccountInfo(dialog),
                },
                {
                    fieldname: "cash_bank_balance",
                    fieldtype: "Currency",
                    label: __("الرصيد الحالي"),
                    options: "currency",
                    read_only: 1,
                },
                {
                    fieldname: "currency",
                    fieldtype: "Data",
                    label: __("العملة"),
                    read_only: 1,
                    default: options.company_currency || "",
                },
                { fieldtype: "Section Break", label: __("الحساب والمبلغ") },
                {
                    fieldname: "counter_account",
                    fieldtype: "Link",
                    options: "Account",
                    label: __("حساب المصروف أو الإيراد"),
                    reqd: 1,
                    get_query: () => this.treasuryVoucherCounterAccountQuery(dialog),
                },
                {
                    fieldname: "amount",
                    fieldtype: "Currency",
                    label: __("المبلغ"),
                    options: "currency",
                    reqd: 1,
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "posting_date",
                    fieldtype: "Date",
                    label: __("تاريخ العملية"),
                    default: options.posting_date || frappe.datetime.get_today(),
                    reqd: 1,
                },
                {
                    fieldname: "cost_center",
                    fieldtype: "Link",
                    options: "Cost Center",
                    label: __("مركز التكلفة"),
                    default: options.default_cost_center || "",
                    reqd: 1,
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            is_group: 0,
                            disabled: 0,
                        },
                    }),
                },
                { fieldtype: "Section Break", label: __("المرجع والمستند الداعم") },
                {
                    fieldname: "reference_no",
                    fieldtype: "Data",
                    label: __("رقم المرجع"),
                    description: __("عند إدخال مرجع يجب ألا يتكرر في مستند Treasury Voucher آخر."),
                },
                {
                    fieldname: "reference_date",
                    fieldtype: "Date",
                    label: __("تاريخ المرجع"),
                    default: options.reference_date || frappe.datetime.get_today(),
                },
                {
                    fieldname: "beneficiary_or_payer",
                    fieldtype: "Data",
                    label: __("المستفيد أو الدافع"),
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "attachment",
                    fieldtype: "Attach",
                    label: __("صورة الإيصال أو المستند"),
                },
                { fieldtype: "Section Break", label: __("البيان") },
                {
                    fieldname: "description",
                    fieldtype: "Small Text",
                    label: __("وصف العملية وسببها"),
                    reqd: 1,
                },
            ],
            primary_action_label: __("معاينة المستند"),
            primary_action: async (values) => this.previewTreasuryVoucher(dialog, values),
        });
        dialog.show();
        this.updateTreasuryVoucherType(dialog);
        this.updateTreasuryVoucherAccountInfo(dialog);
    }

    async reloadTreasuryVoucherCompany(dialog) {
        const company = dialog.get_value("company");
        if (!company) return;
        const options = await this.getTreasuryVoucherOptions(company);
        this.setTreasuryVoucherMaps(options);
        const accounts = options.cash_bank_accounts || [];
        dialog.set_df_property("cash_bank_account", "options", accounts.map((row) => row.name).join("\n"));
        dialog.set_value("cash_bank_account", options.default_cash_bank_account || accounts[0]?.name || "");
        dialog.set_value("currency", options.company_currency || "");
        dialog.set_value("cost_center", options.default_cost_center || "");
        dialog.set_value("counter_account", "");
        this.updateTreasuryVoucherType(dialog);
        this.updateTreasuryVoucherAccountInfo(dialog);
    }

    updateTreasuryVoucherType(dialog) {
        const voucherType = dialog.get_value("voucher_type") || "General Expense";
        const categories = this.treasuryVoucherCategories[voucherType] || [];
        const categoryNames = categories.map((row) => row.name);
        dialog.set_df_property("category", "options", categoryNames.join("\n"));
        if (!categoryNames.includes(dialog.get_value("category"))) {
            dialog.set_value("category", categoryNames[0] || "");
        }
        this.updateTreasuryVoucherCategory(dialog);
    }

    updateTreasuryVoucherCategory(dialog) {
        const configuration = this.treasuryVoucherCategoryMap[dialog.get_value("category")] || {};
        const allowed = configuration.allowed_accounts || [];
        const current = dialog.get_value("counter_account");
        if (!allowed.includes(current)) {
            dialog.set_value("counter_account", configuration.default_account || allowed[0] || "");
        }
    }

    updateTreasuryVoucherAccountInfo(dialog) {
        const account = this.treasuryVoucherAccounts[dialog.get_value("cash_bank_account")] || {};
        dialog.set_value("cash_bank_balance", Number(account.current_balance || 0));
        dialog.set_value("currency", account.currency || dialog.get_value("currency") || "");
    }

    treasuryVoucherCounterAccountQuery(dialog) {
        const configuration = this.treasuryVoucherCategoryMap[dialog.get_value("category")] || {};
        const allowed = configuration.allowed_accounts || [];
        return {
            filters: {
                company: dialog.get_value("company"),
                root_type: dialog.get_value("voucher_type") === "General Receipt" ? "Income" : "Expense",
                is_group: 0,
                disabled: 0,
                name: ["in", allowed.length ? allowed : ["__NO_ALLOWED_ACCOUNT__"]],
            },
        };
    }

    async previewTreasuryVoucher(sourceDialog, values) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.preview_treasury_voucher",
            args: values,
            freeze: true,
            freeze_message: __("جاري مراجعة الحسابات والرصيد..."),
        });
        this.showTreasuryVoucherConfirmation(sourceDialog, values, response.message || {});
    }

    showTreasuryVoucherConfirmation(sourceDialog, sourceValues, preview) {
        const submitNow = preview.voucher_action === "Submit Now";
        const confirmDialog = new frappe.ui.Dialog({
            title: submitNow ? __("تأكيد التنفيذ الفوري") : __("تأكيد حفظ طلب المستند"),
            size: "large",
            fields: [{ fieldtype: "HTML", options: this.renderTreasuryVoucherPreview(preview) }],
            primary_action_label: submitNow ? __("تنفيذ واعتماد") : __("حفظ كمسودة"),
            primary_action: async () => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.execute_treasury_voucher",
                    args: sourceValues,
                    freeze: true,
                    freeze_message: submitNow
                        ? __("جاري إنشاء واعتماد المستند المحاسبي...")
                        : __("جاري حفظ طلب المستند..."),
                });
                const result = response.message || {};
                confirmDialog.hide();
                sourceDialog.hide();
                frappe.msgprint({
                    title: submitNow ? __("تم تنفيذ المستند") : __("تم حفظ طلب المستند"),
                    indicator: "green",
                    message: `
                        <div style="direction:rtl;text-align:right;">
                            <div>${this.esc(result.message || __("تم الحفظ بنجاح"))}</div>
                            <div><strong>${__("Treasury Voucher")}:</strong> <a href="/app/treasury-voucher/${encodeURIComponent(result.treasury_voucher || "")}">${this.esc(result.treasury_voucher || "-")}</a></div>
                            <div><strong>${__("الحالة")}:</strong> ${this.esc(result.status || "-")}</div>
                            <div><strong>${__("المبلغ")}:</strong> ${this.formatMoney(result.amount, result.currency)}</div>
                        </div>
                    `,
                });
                await this.refresh();
            },
        });
        confirmDialog.show();
    }

    renderTreasuryVoucherPreview(preview) {
        const rows = [
            [__("الإجراء"), preview.voucher_action === "Submit Now" ? __("تنفيذ واعتماد فورًا") : __("حفظ كمسودة للمراجعة")],
            [__("الشركة"), preview.company],
            [__("نوع المستند"), preview.voucher_type],
            [__("التصنيف"), preview.category],
            [__("الخزنة أو البنك"), preview.cash_bank_account],
            [__("حساب المصروف أو الإيراد"), preview.counter_account],
            [__("المبلغ"), this.formatMoney(preview.amount, preview.currency)],
            [__("الحساب المصدر"), preview.source_account],
            [__("رصيد المصدر قبل"), this.formatMoney(preview.source_balance_before, preview.currency)],
            [__("رصيد المصدر بعد"), this.formatMoney(preview.source_balance_after, preview.currency)],
            [__("الحساب المستهدف"), preview.target_account],
            [__("رصيد المستهدف قبل"), this.formatMoney(preview.target_balance_before, preview.currency)],
            [__("رصيد المستهدف بعد"), this.formatMoney(preview.target_balance_after, preview.currency)],
            [__("مركز التكلفة"), preview.cost_center],
            [__("المرجع"), preview.reference_no || "-"],
            [__("المستفيد أو الدافع"), preview.beneficiary_or_payer || "-"],
            [__("الوصف"), preview.description || "-"],
        ];
        const journalRows = (preview.journal_preview || []).map((row) => `
            <tr>
                <td>${this.esc(row.account || "-")}</td>
                <td>${this.formatMoney(row.debit || 0, preview.currency)}</td>
                <td>${this.formatMoney(row.credit || 0, preview.currency)}</td>
            </tr>
        `).join("");
        return `
            <div class="tmv3-preview">
                ${rows.map(([label, value]) => `
                    <div class="tmv3-preview-row">
                        <div class="tmv3-preview-label">${this.esc(label)}</div>
                        <div class="tmv3-preview-value">${this.esc(value || "-")}</div>
                    </div>
                `).join("")}
            </div>
            <div class="tmv3-table-wrap" style="margin-top:12px;">
                <table class="tmv3-table">
                    <thead><tr><th>${__("الحساب")}</th><th>${__("مدين")}</th><th>${__("دائن")}</th></tr></thead>
                    <tbody>${journalRows}</tbody>
                </table>
            </div>
            <div class="tmv3-preview-note">
                <strong>${__("مهم")}:</strong>
                ${__("هذا المسار للمصروفات والمقبوضات العامة غير المرتبطة بوردية أو فاتورة مورد أو فاتورة عميل.")}
            </div>
        `;
    }

    renderTreasuryVouchers(rows) {
        const body = (rows || []).length
            ? rows.map((row) => {
                const docstatus = Number(row.docstatus || 0);
                const badgeClass = docstatus === 1 ? "tmv3-badge-on" : docstatus === 2 ? "tmv3-badge-off" : "tmv3-badge-warn";
                const canApprove = this.canApproveTreasuryVoucher && docstatus === 0 && row.can_self_approve;
                const canCancel = this.canCancelTreasuryVoucher && docstatus === 1;
                const approvalNote = docstatus === 0 && !row.can_self_approve
                    ? `<small class="text-muted">${__("ينتظر مديرًا مختلفًا عن طالب المستند")}</small>`
                    : "";
                return `
                    <tr>
                        <td><a href="/app/treasury-voucher/${encodeURIComponent(row.name || "")}">${this.esc(row.name || "-")}</a></td>
                        <td>${this.esc(row.posting_date || "-")}</td>
                        <td>${this.esc(row.voucher_type || "-")}</td>
                        <td>${this.esc(row.category || "-")}</td>
                        <td>${this.esc(row.cash_bank_account || "-")}</td>
                        <td>${this.esc(row.counter_account || "-")}</td>
                        <td>${this.formatMoney(row.amount, row.currency || "")}</td>
                        <td><span class="tmv3-badge ${badgeClass}">${this.esc(row.request_status || row.status || "-")}</span></td>
                        <td>${this.esc(row.requested_by || "-")}<br>${approvalNote}</td>
                        <td>${row.journal_entry ? `<a href="/app/journal-entry/${encodeURIComponent(row.journal_entry)}">${this.esc(row.journal_entry)}</a>` : "-"}</td>
                        <td>
                            ${canApprove ? `<button class="btn btn-xs btn-primary tmv3-treasury-voucher-submit" data-voucher="${this.esc(row.name)}">${__("اعتماد وتنفيذ")}</button>` : ""}
                            ${canCancel ? `<button class="btn btn-xs btn-danger tmv3-treasury-voucher-cancel" data-voucher="${this.esc(row.name)}">${__("إلغاء")}</button>` : ""}
                        </td>
                    </tr>
                `;
            }).join("")
            : `<tr><td colspan="11" class="tmv3-empty">${__("لا توجد مصروفات أو مقبوضات عامة مسجلة حتى الآن.")}</td></tr>`;

        return `
            <div class="tmv3-section">
                <h4>${__("المصروفات والمقبوضات العامة خارج الوردية")}</h4>
                <div class="tmv3-preview-note" style="margin-bottom:12px;">
                    ${__("لا تستخدم هذا القسم لسداد Purchase Invoice أو تحصيل Sales Invoice أو لحركة مرتبطة بورديّة مفتوحة.")}
                </div>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table">
                        <thead>
                            <tr>
                                <th>${__("المستند")}</th><th>${__("التاريخ")}</th><th>${__("النوع")}</th>
                                <th>${__("التصنيف")}</th><th>${__("الخزنة أو البنك")}</th><th>${__("الحساب المقابل")}</th>
                                <th>${__("المبلغ")}</th><th>${__("الحالة")}</th><th>${__("طالب المستند")}</th>
                                <th>${__("Journal Entry")}</th><th>${__("إجراءات")}</th>
                            </tr>
                        </thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            </div>
        `;
    }

    bindTreasuryVoucherActions() {
        this.$main.find(".tmv3-treasury-voucher-submit")
            .off("click.tmv3-treasury-voucher")
            .on("click.tmv3-treasury-voucher", (event) => {
                const voucher = $(event.currentTarget).attr("data-voucher");
                frappe.confirm(
                    `${__("سيتم اعتماد المستند وإنشاء Journal Entry. هل تريد المتابعة؟")}<br><br><strong>${this.esc(voucher)}</strong>`,
                    async () => {
                        const response = await frappe.call({
                            method:
                                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.submit_treasury_voucher",
                            args: { voucher_name: voucher },
                            freeze: true,
                            freeze_message: __("جاري اعتماد مستند الخزينة..."),
                        });
                        frappe.show_alert({ message: response.message?.message || __("تم اعتماد المستند"), indicator: "green" });
                        await this.refresh();
                    },
                );
            });

        this.$main.find(".tmv3-treasury-voucher-cancel")
            .off("click.tmv3-treasury-voucher-cancel")
            .on("click.tmv3-treasury-voucher-cancel", (event) => {
                const voucher = $(event.currentTarget).attr("data-voucher");
                frappe.confirm(
                    `${__("سيتم إلغاء المستند والقيد المحاسبي المرتبط به. هل تريد المتابعة؟")}<br><br><strong>${this.esc(voucher)}</strong>`,
                    async () => {
                        const response = await frappe.call({
                            method:
                                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.cancel_treasury_voucher",
                            args: { voucher_name: voucher },
                            freeze: true,
                            freeze_message: __("جاري إلغاء مستند الخزينة..."),
                        });
                        frappe.show_alert({ message: response.message?.message || __("تم إلغاء المستند"), indicator: "green" });
                        await this.refresh();
                    },
                );
            });
    }

    async getShiftCashMovementOptions(company = null) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_shift_cash_movement_options",
            args: { company },
            freeze: true,
            freeze_message: __("جاري تحميل الخزائن والورديات المفتوحة..."),
        });
        return response.message || {};
    }

    setShiftCashMovementMaps(options) {
        this.cashMovementDrawers = {};
        (options.drawers || []).forEach((row) => {
            this.cashMovementDrawers[row.name] = row;
        });
        this.cashMovementTypes = {};
        (options.movement_types || []).forEach((row) => {
            this.cashMovementTypes[row.value] = row;
        });
    }

    async openShiftCashMovementDialog() {
        if (!this.canManageShiftCashMovement) {
            frappe.msgprint(__("ليس لديك صلاحية إنشاء حركات نقدية للوردية."));
            return;
        }

        const options = await this.getShiftCashMovementOptions();
        this.setShiftCashMovementMaps(options);
        const openDrawers = (options.drawers || []).filter((row) => row.available);
        if (!openDrawers.length) {
            frappe.msgprint({
                title: __("لا توجد وردية مفتوحة"),
                indicator: "orange",
                message: __("يجب فتح وردية وربطها بخزنة مفعلة قبل تسجيل حركة نقدية."),
            });
            return;
        }

        let dialog;
        dialog = new frappe.ui.Dialog({
            title: __("حركة نقدية مرتبطة بالوردية"),
            size: "extra-large",
            fields: [
                {
                    fieldname: "company",
                    fieldtype: "Link",
                    options: "Company",
                    label: __("الشركة"),
                    reqd: 1,
                    default: options.company,
                    onchange: async () => this.reloadShiftCashMovementCompany(dialog),
                },
                {
                    fieldname: "movement_action",
                    fieldtype: "Select",
                    label: __("إجراء الحركة"),
                    options: this.canEmergencySubmitShiftCashMovement
                        ? "Create Draft\nSubmit Now"
                        : "Create Draft",
                    default: "Create Draft",
                    reqd: 1,
                    read_only: !this.canEmergencySubmitShiftCashMovement,
                    description: this.canEmergencySubmitShiftCashMovement
                        ? __("المسار الطبيعي هو حفظ طلب للمراجعة. Submit Now مخصص لطوارئ System Manager ويُسجل في التدقيق.")
                        : __("سيُحفظ الطلب كمسودة ويعتمده مدير خزينة مختلف عن طالب الحركة."),
                },
                { fieldtype: "Section Break", label: __("الوردية والخزنة") },
                {
                    fieldname: "cash_drawer",
                    fieldtype: "Select",
                    label: __("الخزنة"),
                    options: openDrawers.map((row) => row.name).join("\n"),
                    reqd: 1,
                    default: options.default_cash_drawer || openDrawers[0].name,
                    onchange: () => this.updateShiftCashDrawerInfo(dialog),
                },
                {
                    fieldname: "shift_reference",
                    fieldtype: "Link",
                    options: "Pharmacy Shift Closing",
                    label: __("الوردية المفتوحة"),
                    reqd: 1,
                    read_only: 1,
                },
                {
                    fieldname: "drawer_balance",
                    fieldtype: "Currency",
                    label: __("رصيد الخزنة الحالي"),
                    options: "currency",
                    read_only: 1,
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "movement_type",
                    fieldtype: "Select",
                    label: __("نوع الحركة"),
                    options: (options.movement_types || []).map((row) => row.value).join("\n"),
                    reqd: 1,
                    default: "Operating Expense",
                    onchange: () => this.updateShiftCashMovementType(dialog),
                },
                {
                    fieldname: "direction",
                    fieldtype: "Select",
                    label: __("الاتجاه بالنسبة للخزنة"),
                    options: "In\nOut",
                    reqd: 1,
                    read_only: 1,
                },
                {
                    fieldname: "currency",
                    fieldtype: "Data",
                    label: __("العملة"),
                    read_only: 1,
                    default: options.company_currency || "",
                },
                { fieldtype: "Section Break", label: __("الحساب والمبلغ") },
                {
                    fieldname: "counter_account",
                    fieldtype: "Link",
                    options: "Account",
                    label: __("الحساب المقابل"),
                    reqd: 1,
                    get_query: () => this.shiftCashCounterAccountQuery(dialog),
                },
                {
                    fieldname: "amount",
                    fieldtype: "Currency",
                    label: __("المبلغ"),
                    options: "currency",
                    reqd: 1,
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "movement_date",
                    fieldtype: "Datetime",
                    label: __("تاريخ ووقت الحركة"),
                    reqd: 1,
                    default: frappe.datetime.now_datetime(),
                },
                {
                    fieldname: "reference_no",
                    fieldtype: "Data",
                    label: __("رقم المرجع"),
                    description: __("رقم إيصال أو فاتورة أو مرجع داخلي. عند إدخاله يجب ألا يتكرر."),
                },
                {
                    fieldname: "reference_date",
                    fieldtype: "Date",
                    label: __("تاريخ المرجع"),
                    default: options.reference_date || frappe.datetime.get_today(),
                },
                { fieldtype: "Section Break", label: __("بيانات مرتبطة") },
                {
                    fieldname: "supplier",
                    fieldtype: "Link",
                    options: "Supplier",
                    label: __("المورد"),
                    depends_on: "eval:doc.movement_type=='Supplier Payment'",
                    mandatory_depends_on: "eval:doc.movement_type=='Supplier Payment'",
                    onchange: () => dialog.set_value("purchase_invoice", ""),
                },
                {
                    fieldname: "purchase_invoice",
                    fieldtype: "Link",
                    options: "Purchase Invoice",
                    label: __("فاتورة المشتريات"),
                    depends_on: "eval:doc.movement_type=='Supplier Payment'",
                    get_query: () => ({
                        filters: {
                            company: dialog.get_value("company"),
                            supplier: dialog.get_value("supplier"),
                            docstatus: 1,
                            outstanding_amount: [">", 0],
                        },
                    }),
                },
                {
                    fieldname: "employee",
                    fieldtype: "Link",
                    options: "Employee",
                    label: __("الموظف"),
                    depends_on: "eval:doc.movement_type=='Employee Advance'",
                    mandatory_depends_on: "eval:doc.movement_type=='Employee Advance'",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "receipt_attachment",
                    fieldtype: "Attach",
                    label: __("صورة الإيصال أو الإثبات"),
                },
                { fieldtype: "Section Break", label: __("البيان") },
                {
                    fieldname: "description",
                    fieldtype: "Small Text",
                    label: __("سبب الحركة ووصفها"),
                    reqd: 1,
                },
            ],
            primary_action_label: __("معاينة الحركة"),
            primary_action: async (values) => this.previewShiftCashMovement(dialog, values),
        });
        dialog.show();
        this.updateShiftCashDrawerInfo(dialog);
        this.updateShiftCashMovementType(dialog);
    }

    async reloadShiftCashMovementCompany(dialog) {
        const company = dialog.get_value("company");
        if (!company) return;
        const options = await this.getShiftCashMovementOptions(company);
        this.setShiftCashMovementMaps(options);
        const openDrawers = (options.drawers || []).filter((row) => row.available);
        dialog.set_df_property("cash_drawer", "options", openDrawers.map((row) => row.name).join("\n"));
        dialog.set_value("cash_drawer", openDrawers[0]?.name || "");
        dialog.set_value("currency", options.company_currency || "");
        dialog.set_value("counter_account", "");
        this.updateShiftCashDrawerInfo(dialog);
    }

    updateShiftCashDrawerInfo(dialog) {
        const drawer = this.cashMovementDrawers[dialog.get_value("cash_drawer")] || {};
        dialog.set_value("shift_reference", drawer.open_shift || "");
        dialog.set_value("drawer_balance", Number(drawer.current_balance || 0));
        dialog.set_value("currency", drawer.currency || dialog.get_value("currency") || "");
    }

    updateShiftCashMovementType(dialog) {
        const rule = this.cashMovementTypes[dialog.get_value("movement_type")] || {};
        const fixedDirection = rule.direction || "";
        dialog.set_df_property("direction", "read_only", fixedDirection ? 1 : 0);
        if (fixedDirection) dialog.set_value("direction", fixedDirection);
        dialog.set_value("counter_account", "");
        if (dialog.layout?.refresh_dependencies) dialog.layout.refresh_dependencies();
    }

    shiftCashCounterAccountQuery(dialog) {
        const company = dialog.get_value("company");
        const drawer = this.cashMovementDrawers[dialog.get_value("cash_drawer")] || {};
        const rule = this.cashMovementTypes[dialog.get_value("movement_type")] || {};
        const filters = {
            company,
            is_group: 0,
            disabled: 0,
        };
        if (drawer.cash_account) filters.name = ["!=", drawer.cash_account];

        if (rule.counter_kind === "cash_bank") {
            filters.root_type = "Asset";
            filters.account_type = ["in", ["Cash", "Bank"]];
        } else if (rule.counter_kind === "expense") {
            filters.root_type = "Expense";
        } else if (rule.counter_kind === "payable") {
            filters.root_type = "Liability";
            filters.account_type = "Payable";
        } else if (rule.counter_kind === "employee_advance") {
            filters.root_type = "Asset";
            filters.account_type = ["not in", ["Cash", "Bank"]];
        } else if (rule.counter_kind === "receipt") {
            filters.root_type = ["in", ["Income", "Liability", "Equity", "Asset"]];
        } else if (rule.counter_kind === "payment") {
            filters.root_type = ["in", ["Expense", "Asset", "Liability"]];
        }
        return { filters };
    }

    async previewShiftCashMovement(sourceDialog, values) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.preview_shift_cash_movement",
            args: values,
            freeze: true,
            freeze_message: __("جاري مراجعة الحركة والرصيد والوردية..."),
        });
        this.showShiftCashMovementConfirmation(sourceDialog, values, response.message || {});
    }

    showShiftCashMovementConfirmation(sourceDialog, sourceValues, preview) {
        const submitNow = preview.movement_action === "Submit Now";
        const confirmDialog = new frappe.ui.Dialog({
            title: submitNow ? __("تأكيد التنفيذ الفوري") : __("تأكيد حفظ طلب الحركة"),
            size: "large",
            fields: [{ fieldtype: "HTML", options: this.renderShiftCashMovementPreview(preview) }],
            primary_action_label: submitNow ? __("تنفيذ واعتماد") : __("حفظ كمسودة"),
            primary_action: async () => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.execute_shift_cash_movement",
                    args: sourceValues,
                    freeze: true,
                    freeze_message: submitNow
                        ? __("جاري إنشاء واعتماد الحركة المحاسبية...")
                        : __("جاري حفظ طلب الحركة..."),
                });
                const result = response.message || {};
                confirmDialog.hide();
                sourceDialog.hide();
                frappe.msgprint({
                    title: submitNow ? __("تم تنفيذ الحركة") : __("تم حفظ طلب الحركة"),
                    indicator: "green",
                    message: `
                        <div style="direction:rtl;text-align:right;">
                            <div>${this.esc(result.message || __("تم الحفظ بنجاح"))}</div>
                            <div><strong>${__("Shift Cash Movement")}:</strong> <a href="/app/shift-cash-movement/${encodeURIComponent(result.shift_cash_movement || "")}">${this.esc(result.shift_cash_movement || "-")}</a></div>
                            <div><strong>${__("الحالة")}:</strong> ${this.esc(result.status || "-")}</div>
                            <div><strong>${__("المبلغ")}:</strong> ${this.formatMoney(result.amount, result.currency)}</div>
                        </div>
                    `,
                });
                await this.refresh();
            },
        });
        confirmDialog.show();
    }

    renderShiftCashMovementPreview(preview) {
        const rows = [
            [__("الإجراء"), preview.movement_action === "Submit Now" ? __("تنفيذ واعتماد فورًا") : __("حفظ كمسودة للمراجعة")],
            [__("الشركة"), preview.company],
            [__("الخزنة"), preview.cash_drawer],
            [__("الوردية"), preview.shift_reference],
            [__("نوع الحركة"), preview.movement_type],
            [__("الاتجاه"), preview.direction],
            [__("المبلغ"), this.formatMoney(preview.amount, preview.currency)],
            [__("الحساب المصدر"), preview.source_account],
            [__("رصيد المصدر قبل"), this.formatMoney(preview.source_balance_before, preview.currency)],
            [__("رصيد المصدر بعد"), this.formatMoney(preview.source_balance_after, preview.currency)],
            [__("الحساب المستهدف"), preview.target_account],
            [__("رصيد المستهدف قبل"), this.formatMoney(preview.target_balance_before, preview.currency)],
            [__("رصيد المستهدف بعد"), this.formatMoney(preview.target_balance_after, preview.currency)],
            [__("المرجع"), preview.reference_no || "-"],
            [__("الوصف"), preview.description || "-"],
        ];
        const journalRows = (preview.journal_preview || []).map((row) => `
            <tr>
                <td>${this.esc(row.account || "-")}</td>
                <td>${this.formatMoney(row.debit || 0, preview.currency)}</td>
                <td>${this.formatMoney(row.credit || 0, preview.currency)}</td>
            </tr>
        `).join("");
        return `
            <div class="tmv3-preview">
                ${rows.map(([label, value]) => `
                    <div class="tmv3-preview-row">
                        <div class="tmv3-preview-label">${this.esc(label)}</div>
                        <div class="tmv3-preview-value">${this.esc(value || "-")}</div>
                    </div>
                `).join("")}
            </div>
            <div class="tmv3-table-wrap" style="margin-top:12px;">
                <table class="tmv3-table">
                    <thead><tr><th>${__("الحساب")}</th><th>${__("مدين")}</th><th>${__("دائن")}</th></tr></thead>
                    <tbody>${journalRows}</tbody>
                </table>
            </div>
        `;
    }

    renderShiftCashMovements(dataset) {
        const data = dataset || {};
        const rows = data.rows || [];
        const summary = data.summary || {};
        const filters = data.filters || {};
        const pagination = data.pagination || {};
        const options = data.options || {};
        const isOpen = Boolean(this.shiftCashMovementSectionOpen);

        const optionList = (items, selectedValue, emptyLabel) => [
            `<option value="">${this.esc(emptyLabel)}</option>`,
            ...(items || []).map((item) => {
                const value = item.value || "";
                const selected = String(value) === String(selectedValue || "") ? " selected" : "";
                return `<option value="${this.esc(value)}"${selected}>${this.esc(item.label || value)}</option>`;
            }),
        ].join("");

        const body = rows.length
            ? rows.map((row) => {
                const docstatus = Number(row.docstatus || 0);
                const badgeClass = docstatus === 1 ? "tmv3-badge-on" : docstatus === 2 ? "tmv3-badge-off" : "tmv3-badge-warn";
                const canApprove = this.canApproveShiftCashMovement && docstatus === 0 && row.can_self_approve;
                const canCancel = this.canCancelShiftCashMovement && docstatus === 1;
                const approvalNote = docstatus === 0 && !row.can_self_approve
                    ? `<small class="text-muted">${__("ينتظر مديرًا مختلفًا عن طالب الحركة")}</small>`
                    : "";
                return `
                    <tr>
                        <td><a href="/app/shift-cash-movement/${encodeURIComponent(row.name || "")}">${this.esc(row.name || "-")}</a></td>
                        <td>${this.esc(this.formatDateTime(row.movement_date))}</td>
                        <td>${this.esc(row.movement_type || "-")}</td>
                        <td>${this.esc(row.direction || "-")}</td>
                        <td>${this.esc(row.cash_drawer || "-")}</td>
                        <td><a href="/app/pharmacy-shift-closing/${encodeURIComponent(row.shift_reference || "")}">${this.esc(row.shift_reference || "-")}</a></td>
                        <td>${this.formatMoney(row.amount, "")}</td>
                        <td><span class="tmv3-badge ${badgeClass}">${this.esc(row.request_status || row.status || "-")}</span></td>
                        <td>${this.esc(row.requested_by || "-")}<br>${approvalNote}</td>
                        <td>${row.journal_entry ? `<a href="/app/journal-entry/${encodeURIComponent(row.journal_entry)}">${this.esc(row.journal_entry)}</a>` : "-"}</td>
                        <td>
                            ${canApprove ? `<button class="btn btn-xs btn-primary tmv3-cash-movement-submit" data-movement="${this.esc(row.name)}">${__("اعتماد وتنفيذ")}</button>` : ""}
                            ${canCancel ? `<button class="btn btn-xs btn-danger tmv3-cash-movement-cancel" data-movement="${this.esc(row.name)}">${__("إلغاء")}</button>` : ""}
                        </td>
                    </tr>
                `;
            }).join("")
            : `<tr><td colspan="11" class="tmv3-empty">${__("لا توجد حركات مطابقة للفلاتر المحددة.")}</td></tr>`;

        const loadedCount = rows.length;
        const totalCount = Number(summary.total_count || 0);
        return `
            <div class="tmv3-section tmv3-shift-movements-section">
                <button type="button" class="tmv3-section-toggle tmv3-shift-movement-toggle" aria-expanded="${isOpen ? "true" : "false"}">
                    <div class="tmv3-section-toggle-meta">
                        <h4>${__("حركات النقدية المرتبطة بالورديات")}</h4>
                        <span class="tmv3-badge tmv3-badge-on">${this.esc(String(totalCount))} ${__("حركة")}</span>
                        <span class="text-muted">${this.esc(filters.from_date || "-")} → ${this.esc(filters.to_date || "-")}</span>
                    </div>
                    <span class="tmv3-collapse-icon">${isOpen ? "▲" : "▼"}</span>
                </button>

                <div class="tmv3-collapsible-body"${isOpen ? "" : ' style="display:none;"'}>
                    <div class="tmv3-filter-grid">
                        <div class="tmv3-filter-field">
                            <label>${__("من تاريخ")}</label>
                            <input type="date" class="tmv3-shift-filter-from" value="${this.esc(filters.from_date || "")}">
                        </div>
                        <div class="tmv3-filter-field">
                            <label>${__("إلى تاريخ")}</label>
                            <input type="date" class="tmv3-shift-filter-to" value="${this.esc(filters.to_date || "")}">
                        </div>
                        <div class="tmv3-filter-field">
                            <label>${__("الحالة")}</label>
                            <select class="tmv3-shift-filter-status">${optionList(options.statuses, filters.request_status, __("كل الحالات"))}</select>
                        </div>
                        <div class="tmv3-filter-field">
                            <label>${__("نوع الحركة")}</label>
                            <select class="tmv3-shift-filter-type">${optionList(options.movement_types, filters.movement_type, __("كل الأنواع"))}</select>
                        </div>
                        <div class="tmv3-filter-field">
                            <label>${__("الخزنة")}</label>
                            <select class="tmv3-shift-filter-drawer">${optionList(options.drawers, filters.cash_drawer, __("كل الخزائن"))}</select>
                        </div>
                        <div class="tmv3-filter-field">
                            <label>${__("رقم الوردية")}</label>
                            <input type="text" class="tmv3-shift-filter-shift" value="${this.esc(filters.shift_reference || "")}" placeholder="SHIFT-YYYY-00000">
                        </div>
                        <div class="tmv3-filter-actions">
                            <button type="button" class="btn btn-primary btn-sm tmv3-shift-filter-apply">${__("تطبيق")}</button>
                            <button type="button" class="btn btn-default btn-sm tmv3-shift-filter-reset">${__("إعادة ضبط")}</button>
                        </div>
                    </div>

                    <div class="tmv3-summary-strip">
                        <div class="tmv3-summary-chip"><small>${__("عدد الحركات")}</small><strong>${this.esc(String(totalCount))}</strong></div>
                        <div class="tmv3-summary-chip"><small>${__("إجمالي الداخل")}</small><strong>${this.formatMoney(summary.total_in || 0, "")}</strong></div>
                        <div class="tmv3-summary-chip"><small>${__("إجمالي الخارج")}</small><strong>${this.formatMoney(summary.total_out || 0, "")}</strong></div>
                        <div class="tmv3-summary-chip"><small>${__("صافي الحركة")}</small><strong>${this.formatMoney(summary.net_movement || 0, "")}</strong></div>
                        <div class="tmv3-summary-chip"><small>${__("تنتظر الاعتماد")}</small><strong>${this.esc(String(summary.pending_count || 0))}</strong></div>
                    </div>

                    <div class="tmv3-table-wrap">
                        <table class="tmv3-table">
                            <thead>
                                <tr>
                                    <th>${__("المستند")}</th><th>${__("التاريخ")}</th><th>${__("النوع")}</th>
                                    <th>${__("الاتجاه")}</th><th>${__("الخزنة")}</th><th>${__("الوردية")}</th>
                                    <th>${__("المبلغ")}</th><th>${__("الحالة")}</th><th>${__("طالب الحركة")}</th>
                                    <th>${__("Journal Entry")}</th><th>${__("إجراءات")}</th>
                                </tr>
                            </thead>
                            <tbody>${body}</tbody>
                        </table>
                    </div>
                    <div class="tmv3-pagination">
                        <span class="text-muted">${__("المعروض")}: ${this.esc(String(loadedCount))} / ${this.esc(String(totalCount))}</span>
                        ${pagination.has_more ? `<button type="button" class="btn btn-default btn-sm tmv3-shift-load-more">${__("تحميل المزيد")}</button>` : ""}
                    </div>
                </div>
            </div>
        `;
    }

    getShiftCashMovementFilters() {
        const $section = this.$main.find(".tmv3-shift-movements-section");
        return {
            from_date: $section.find(".tmv3-shift-filter-from").val() || frappe.datetime.get_today(),
            to_date: $section.find(".tmv3-shift-filter-to").val() || frappe.datetime.get_today(),
            request_status: $section.find(".tmv3-shift-filter-status").val() || "",
            movement_type: $section.find(".tmv3-shift-filter-type").val() || "",
            cash_drawer: $section.find(".tmv3-shift-filter-drawer").val() || "",
            shift_reference: ($section.find(".tmv3-shift-filter-shift").val() || "").trim(),
        };
    }

    async loadShiftCashMovements({ append = false, reset = false } = {}) {
        if (this.shiftCashMovementLoading) return;
        this.shiftCashMovementLoading = true;
        this.shiftCashMovementSectionOpen = true;
        try {
            let filters = this.getShiftCashMovementFilters();
            if (reset) {
                const today = frappe.datetime.get_today();
                filters = {
                    from_date: today,
                    to_date: today,
                    request_status: "",
                    movement_type: "",
                    cash_drawer: "",
                    shift_reference: "",
                };
            }
            const existingRows = append ? ((this.shiftCashMovementData || {}).rows || []) : [];
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_shift_cash_movements",
                args: {
                    ...filters,
                    start: append ? existingRows.length : 0,
                    page_length: 50,
                },
                freeze: true,
                freeze_message: __("جاري تحميل حركات الوردية..."),
            });
            const nextData = response.message || {};
            if (append) {
                nextData.rows = existingRows.concat(nextData.rows || []);
            }
            this.shiftCashMovementData = nextData;
            const $current = this.$main.find(".tmv3-shift-movements-section");
            $current.replaceWith(this.renderShiftCashMovements(this.shiftCashMovementData));
            this.bindShiftCashMovementActions();
        } catch (error) {
            console.error(error);
            frappe.msgprint(error?.message || __("تعذر تحميل حركات الوردية."));
        } finally {
            this.shiftCashMovementLoading = false;
        }
    }

    bindShiftCashMovementActions() {
        const $section = this.$main.find(".tmv3-shift-movements-section");
        $section.find(".tmv3-shift-movement-toggle")
            .off("click.tmv3-shift-toggle")
            .on("click.tmv3-shift-toggle", () => {
                this.shiftCashMovementSectionOpen = !this.shiftCashMovementSectionOpen;
                $section.find(".tmv3-collapsible-body").stop(true, true).slideToggle(160);
                $section.find(".tmv3-collapse-icon").text(this.shiftCashMovementSectionOpen ? "▲" : "▼");
                $section.find(".tmv3-shift-movement-toggle").attr("aria-expanded", this.shiftCashMovementSectionOpen ? "true" : "false");
            });
        $section.find(".tmv3-shift-filter-apply")
            .off("click.tmv3-shift-apply")
            .on("click.tmv3-shift-apply", () => this.loadShiftCashMovements({ append: false }));
        $section.find(".tmv3-shift-filter-reset")
            .off("click.tmv3-shift-reset")
            .on("click.tmv3-shift-reset", () => this.loadShiftCashMovements({ append: false, reset: true }));
        $section.find(".tmv3-shift-load-more")
            .off("click.tmv3-shift-more")
            .on("click.tmv3-shift-more", () => this.loadShiftCashMovements({ append: true }));

        this.$main.find(".tmv3-cash-movement-submit")
            .off("click.tmv3-cash-movement")
            .on("click.tmv3-cash-movement", (event) => {
                const movement = $(event.currentTarget).attr("data-movement");
                frappe.confirm(
                    `${__("سيتم اعتماد الحركة وإنشاء Journal Entry. هل تريد المتابعة؟")}<br><br><strong>${this.esc(movement)}</strong>`,
                    async () => {
                        const response = await frappe.call({
                            method:
                                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.submit_shift_cash_movement",
                            args: { movement_name: movement },
                            freeze: true,
                            freeze_message: __("جاري اعتماد الحركة النقدية..."),
                        });
                        frappe.show_alert({ message: response.message?.message || __("تم اعتماد الحركة"), indicator: "green" });
                        await this.refresh();
                    },
                );
            });

        this.$main.find(".tmv3-cash-movement-cancel")
            .off("click.tmv3-cash-movement-cancel")
            .on("click.tmv3-cash-movement-cancel", (event) => {
                const movement = $(event.currentTarget).attr("data-movement");
                frappe.confirm(
                    `${__("سيتم إلغاء الحركة والقيد المحاسبي المرتبط بها. هل تريد المتابعة؟")}<br><br><strong>${this.esc(movement)}</strong>`,
                    async () => {
                        const response = await frappe.call({
                            method:
                                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.cancel_shift_cash_movement",
                            args: { movement_name: movement },
                            freeze: true,
                            freeze_message: __("جاري إلغاء الحركة النقدية..."),
                        });
                        frappe.show_alert({ message: response.message?.message || __("تم إلغاء الحركة"), indicator: "green" });
                        await this.refresh();
                    },
                );
            });
    }

    async getInternalTransferOptions(company = null) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_internal_transfer_options",
            args: { company },
            freeze: true,
            freeze_message: __("جاري تحميل حسابات التحويل..."),
        });
        return response.message || {};
    }

    async openInternalTransferDialog() {
        if (!this.canManageInternalTransfer) {
            frappe.msgprint(__("ليس لديك صلاحية تنفيذ التحويلات المالية."));
            return;
        }

        const options = await this.getInternalTransferOptions();
        this.setTransferAccountMap(options.accounts || []);
        let dialog;
        dialog = new frappe.ui.Dialog({
            title: __("تحويل مالي بين الخزائن والبنوك"),
            size: "large",
            fields: [
                {
                    fieldname: "company",
                    fieldtype: "Link",
                    options: "Company",
                    label: __("الشركة"),
                    reqd: 1,
                    default: options.company,
                    onchange: async () => this.reloadInternalTransferCompany(dialog),
                },
                {
                    fieldname: "transfer_action",
                    fieldtype: "Select",
                    label: __("إجراء التحويل"),
                    options: this.canEmergencySubmitInternalTransfer
                        ? "Create Draft\nSubmit Now"
                        : "Create Draft",
                    default: "Create Draft",
                    reqd: 1,
                    read_only: !this.canEmergencySubmitInternalTransfer,
                    description: this.canEmergencySubmitInternalTransfer
                        ? __("الحفظ كمسودة هو المسار الطبيعي. Submit Now مخصص لتجاوز الطوارئ بواسطة System Manager ويُسجل في التدقيق.")
                        : __("سيُحفظ الطلب كمسودة، ويجب أن يعتمده مدير خزينة مختلف عن طالب التحويل."),
                },
                { fieldtype: "Section Break", label: __("الحساب المصدر والوجهة") },
                {
                    fieldname: "paid_from",
                    fieldtype: "Link",
                    options: "Account",
                    label: __("من حساب"),
                    reqd: 1,
                    get_query: () => this.internalTransferAccountQuery(dialog),
                    onchange: () => this.updateInternalTransferAccountInfo(dialog),
                },
                {
                    fieldname: "source_balance",
                    fieldtype: "Currency",
                    label: __("الرصيد المتاح في المصدر"),
                    read_only: 1,
                    options: "account_currency",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "paid_to",
                    fieldtype: "Link",
                    options: "Account",
                    label: __("إلى حساب"),
                    reqd: 1,
                    get_query: () => this.internalTransferAccountQuery(dialog),
                    onchange: () => this.updateInternalTransferAccountInfo(dialog),
                },
                {
                    fieldname: "destination_balance",
                    fieldtype: "Currency",
                    label: __("الرصيد الحالي في الوجهة"),
                    read_only: 1,
                    options: "account_currency",
                },
                { fieldtype: "Section Break", label: __("بيانات التحويل") },
                {
                    fieldname: "amount",
                    fieldtype: "Currency",
                    label: __("مبلغ التحويل"),
                    reqd: 1,
                    options: "account_currency",
                },
                {
                    fieldname: "posting_date",
                    fieldtype: "Date",
                    label: __("تاريخ القيد"),
                    reqd: 1,
                    default: options.posting_date || frappe.datetime.get_today(),
                },
                {
                    fieldname: "account_currency",
                    fieldtype: "Data",
                    label: __("العملة"),
                    read_only: 1,
                    default: options.company_currency || "",
                },
                { fieldtype: "Column Break" },
                {
                    fieldname: "reference_no",
                    fieldtype: "Data",
                    label: __("رقم المرجع"),
                    reqd: 1,
                    description: __("رقم إيصال الإيداع أو التحويل أو رقم داخلي فريد."),
                },
                {
                    fieldname: "reference_date",
                    fieldtype: "Date",
                    label: __("تاريخ المرجع"),
                    reqd: 1,
                    default: options.reference_date || frappe.datetime.get_today(),
                },
                { fieldtype: "Section Break", label: __("ملاحظات") },
                {
                    fieldname: "remarks",
                    fieldtype: "Small Text",
                    label: __("سبب أو ملاحظات التحويل"),
                },
            ],
            primary_action_label: __("معاينة التحويل"),
            primary_action: async (values) => this.previewInternalTransfer(dialog, values),
        });
        dialog.show();
    }

    setTransferAccountMap(accounts) {
        this.transferAccounts = {};
        (accounts || []).forEach((row) => {
            this.transferAccounts[row.name] = row;
        });
    }

    internalTransferAccountQuery(dialog) {
        return {
            filters: {
                company: dialog.get_value("company"),
                root_type: "Asset",
                is_group: 0,
                disabled: 0,
                account_type: ["in", ["Cash", "Bank"]],
            },
        };
    }

    async reloadInternalTransferCompany(dialog) {
        const company = dialog.get_value("company");
        if (!company) return;
        const options = await this.getInternalTransferOptions(company);
        this.setTransferAccountMap(options.accounts || []);
        dialog.set_value("paid_from", "");
        dialog.set_value("paid_to", "");
        dialog.set_value("source_balance", 0);
        dialog.set_value("destination_balance", 0);
        dialog.set_value("account_currency", options.company_currency || "");
    }

    updateInternalTransferAccountInfo(dialog) {
        const source = this.transferAccounts[dialog.get_value("paid_from")] || {};
        const destination = this.transferAccounts[dialog.get_value("paid_to")] || {};
        dialog.set_value("source_balance", Number(source.current_balance || 0));
        dialog.set_value("destination_balance", Number(destination.current_balance || 0));
        dialog.set_value(
            "account_currency",
            source.account_currency || destination.account_currency || dialog.get_value("account_currency") || "",
        );
    }

    async previewInternalTransfer(sourceDialog, values) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.preview_internal_transfer",
            args: values,
            freeze: true,
            freeze_message: __("جاري مراجعة التحويل والرصيد المتاح..."),
        });
        this.showInternalTransferConfirmation(sourceDialog, values, response.message || {});
    }

    showInternalTransferConfirmation(sourceDialog, sourceValues, preview) {
        const submitNow = preview.transfer_action === "Submit Now";
        const confirmDialog = new frappe.ui.Dialog({
            title: submitNow ? __("تأكيد تنفيذ واعتماد التحويل") : __("تأكيد حفظ طلب التحويل"),
            size: "large",
            fields: [{ fieldtype: "HTML", options: this.renderInternalTransferPreview(preview) }],
            primary_action_label: submitNow ? __("تنفيذ واعتماد التحويل") : __("حفظ كمسودة"),
            primary_action: async () => {
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.execute_internal_transfer",
                    args: sourceValues,
                    freeze: true,
                    freeze_message: submitNow
                        ? __("جاري إنشاء واعتماد التحويل المالي...")
                        : __("جاري حفظ طلب التحويل..."),
                });
                const result = response.message || {};
                confirmDialog.hide();
                sourceDialog.hide();
                frappe.msgprint({
                    title: submitNow ? __("تم تنفيذ التحويل") : __("تم حفظ طلب التحويل"),
                    indicator: "green",
                    message: `
                        <div style="direction:rtl;text-align:right;">
                            <div>${this.esc(result.message || __("تم الحفظ بنجاح"))}</div>
                            <div><strong>${__("Payment Entry")}:</strong> <a href="/app/payment-entry/${encodeURIComponent(result.payment_entry || "")}">${this.esc(result.payment_entry || "-")}</a></div>
                            <div><strong>${__("الحالة")}:</strong> ${this.esc(result.status || "-")}</div>
                            <div><strong>${__("المبلغ")}:</strong> ${this.formatMoney(result.amount, result.account_currency)}</div>
                        </div>
                    `,
                });
                await this.refresh();
            },
        });
        confirmDialog.show();
    }

    renderInternalTransferPreview(preview) {
        const rows = [
            [__("الإجراء"), preview.transfer_action === "Submit Now" ? __("إنشاء واعتماد فورًا") : __("حفظ كمسودة للمراجعة")],
            [__("الشركة"), preview.company],
            [__("من حساب"), `${preview.paid_from} — ${preview.paid_from_type}`],
            [__("الرصيد قبل التحويل"), this.formatMoney(preview.source_balance_before, preview.account_currency)],
            [__("الرصيد بعد التحويل"), this.formatMoney(preview.source_balance_after, preview.account_currency)],
            [__("إلى حساب"), `${preview.paid_to} — ${preview.paid_to_type}`],
            [__("رصيد الوجهة قبل التحويل"), this.formatMoney(preview.destination_balance_before, preview.account_currency)],
            [__("رصيد الوجهة بعد التحويل"), this.formatMoney(preview.destination_balance_after, preview.account_currency)],
            [__("المبلغ"), this.formatMoney(preview.amount, preview.account_currency)],
            [__("تاريخ القيد"), preview.posting_date],
            [__("المرجع"), preview.reference_no],
            [__("تاريخ المرجع"), preview.reference_date],
            [__("الملاحظات"), preview.remarks || "-"],
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
                <strong>${__("القيد المتوقع")}:</strong><br>
                ${__("مدين")} ${this.esc(preview.paid_to)} — ${this.formatMoney(preview.amount, preview.account_currency)}<br>
                ${__("دائن")} ${this.esc(preview.paid_from)} — ${this.formatMoney(preview.amount, preview.account_currency)}
            </div>
        `;
    }

    renderInternalTransfers(rows) {
        const body = (rows || []).length
            ? rows.map((row) => {
                const docstatus = Number(row.docstatus || 0);
                const badgeClass = docstatus === 1
                    ? "tmv3-badge-on"
                    : "tmv3-badge-off";
                const canApprove = this.canApproveInternalTransfer
                    && docstatus === 0
                    && Boolean(row.can_current_user_approve);
                const submitButton = canApprove
                    ? `<button class="tmv3-action-btn tmv3-action-success tmv3-transfer-submit" data-payment-entry="${this.esc(row.name)}">${__("اعتماد وتنفيذ")}</button>`
                    : "";
                const separationNote = this.canApproveInternalTransfer
                    && docstatus === 0
                    && !Boolean(row.can_current_user_approve)
                    ? `<small class="text-muted">${__("ينتظر مديرًا مختلفًا عن طالب التحويل")}</small>`
                    : "";
                const canOpenDocument = this.canManageInternalTransfer || this.canApproveInternalTransfer;
                const documentLabel = canOpenDocument
                    ? `<a href="/app/payment-entry/${encodeURIComponent(row.name)}">${this.esc(row.name)}</a>`
                    : this.esc(row.name);
                const openButton = canOpenDocument
                    ? `<a class="tmv3-action-btn" href="/app/payment-entry/${encodeURIComponent(row.name)}">${__("فتح")}</a>`
                    : "";
                return `
                    <tr>
                        <td>${documentLabel}</td>
                        <td>${this.esc(row.posting_date || "-")}</td>
                        <td>${this.esc(row.paid_from || "-")}</td>
                        <td>${this.esc(row.paid_to || "-")}</td>
                        <td>${this.formatMoney(row.paid_amount, row.account_currency)}</td>
                        <td>${this.esc(row.reference_no || "-")}</td>
                        <td><span class="tmv3-badge ${badgeClass}">${this.esc(row.display_status || row.status || "-")}</span></td>
                        <td>${this.esc(row.requested_by || row.owner || "-")}<br><small>${this.esc(row.requested_at || "-")}</small></td>
                        <td>${this.esc(row.approved_by || "-")}<br><small>${this.esc(row.approved_at || "-")}</small></td>
                        <td><div class="tmv3-actions">
                            ${openButton}
                            ${submitButton}
                        </div>${separationNote}</td>
                    </tr>
                `;
            }).join("")
            : `<tr><td colspan="10" class="tmv3-empty">${__("لا توجد تحويلات داخلية مسجلة حتى الآن.")}</td></tr>`;

        return `
            <div class="tmv3-section">
                <h4>${__("التحويلات بين الخزائن والبنوك")}</h4>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table" style="min-width:1450px;">
                        <thead><tr>
                            <th>${__("Payment Entry")}</th><th>${__("التاريخ")}</th>
                            <th>${__("من")}</th><th>${__("إلى")}</th><th>${__("المبلغ")}</th>
                            <th>${__("المرجع")}</th><th>${__("الحالة")}</th>
                            <th>${__("طلب بواسطة")}</th><th>${__("اعتمد بواسطة")}</th><th>${__("إجراءات")}</th>
                        </tr></thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
                <div class="tmv3-preview-note">${__("المشغل ينشئ الطلب كمسودة، ولا ينشأ الأثر المحاسبي إلا بعد اعتماد مدير خزينة مختلف. System Manager فقط يملك تجاوز الطوارئ المسجل.")}</div>
            </div>
        `;
    }

    bindInternalTransferActions() {
        this.$main.find(".tmv3-transfer-submit")
            .off("click.tmv3-transfer")
            .on("click.tmv3-transfer", (event) => {
                const paymentEntry = $(event.currentTarget).attr("data-payment-entry");
                frappe.confirm(
                    `${__("سيتم اعتماد وتنفيذ التحويل وإنشاء أثره المحاسبي. هل تريد المتابعة؟")}<br><br><strong>${this.esc(paymentEntry)}</strong>`,
                    async () => {
                        const response = await frappe.call({
                            method:
                                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.submit_internal_transfer",
                            args: { payment_entry_name: paymentEntry },
                            freeze: true,
                            freeze_message: __("جاري اعتماد التحويل المالي..."),
                        });
                        frappe.show_alert({
                            message: response.message?.message || __("تم اعتماد التحويل"),
                            indicator: "green",
                        });
                        await this.refresh();
                    },
                );
            });
    }

    render(data) {
        this.$main.html(`
            <div class="tmv3">
                <div class="tmv3-hero">
                    <h2>${__("إدارة الخزائن والبنوك ووسائل الدفع")}</h2>
                    <p>
                        ${__("يمكن إدارة الخزائن والبنوك ووسائل الدفع والتحويلات وحركات الوردية والمصروفات والمقبوضات العامة مع المراجعة والاعتماد.")}
                    </p>
                    <div class="tmv3-status">
                        <span>●</span>
                        ${frappe.utils.escape_html(
                            data.message || __("Page is ready"),
                        )}
                    </div>
                    <div class="tmv3-preview-note" style="margin-top:12px;">
                        <strong>${__("مستوى الصلاحية")}:</strong>
                        ${this.esc((data.access_profile || {}).role_label || "-")}
                        — ${this.esc(data.user || "-")}
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
                    ${this.card(__("التحويلات المالية"), data.internal_transfers, __("Internal Transfer"))}
                    ${this.card(__("طلبات تحويل مسودة"), data.draft_internal_transfers, __("Awaiting Approval"))}
                    ${this.card(__("حركات نقدية"), data.shift_cash_movements, __("Shift Cash Movement"))}
                    ${this.card(__("حركات تنتظر الاعتماد"), data.draft_shift_cash_movements, __("Pending Approval"))}
                    ${this.card(__("مستندات الخزينة العامة"), data.treasury_vouchers, __("Treasury Voucher"))}
                    ${this.card(__("مستندات عامة تنتظر الاعتماد"), data.draft_treasury_vouchers, __("Pending Approval"))}
                </div>

                ${this.renderPendingDashboard(data.pending_dashboard || {})}
                ${this.renderDrawers(data.drawers || [])}
                ${this.renderBanks(data.banks || [])}
                ${this.renderTerminals(data.terminals || [])}
                ${this.renderPaymentSetups(data.payment_setups || [])}
                ${this.renderShiftCashMovements(this.shiftCashMovementData)}
                ${this.renderTreasuryVouchers(data.treasury_voucher_rows || [])}
                ${this.renderInternalTransfers(data.internal_transfer_rows || [])}
                ${this.renderUnlinkedBankLedgers(data.unlinked_bank_ledgers || [])}
                ${this.renderWarnings(data.account_warnings || [])}
            </div>
        `);
    }


    renderPendingDashboard(data) {
        const summary = data.summary || {};
        const currency = data.currency || "";
        const alerts = data.alerts || [];
        const accounts = data.accounts || [];
        const cardBatches = data.open_card_batches || [];
        const reconciliations = data.open_reconciliations || [];

        const severityLabel = (severity) => ({
            critical: __("حرج"),
            warning: __("مراجعة"),
            info: __("معلّق"),
        }[severity] || __("تنبيه"));
        const severityIcon = (severity) => ({
            critical: "●",
            warning: "▲",
            info: "●",
        }[severity] || "●");
        const routeForAlert = (row) => {
            if (row.doctype === "Card Settlement Batch") {
                return `/app/card-settlement-batch/${encodeURIComponent(row.document || "")}`;
            }
            if (row.doctype === "Shift Payment Reconciliation") {
                return `/app/shift-payment-reconciliation/${encodeURIComponent(row.document || "")}`;
            }
            if (row.account) {
                return `/app/account/${encodeURIComponent(row.account)}`;
            }
            return "";
        };

        const alertsHtml = alerts.length
            ? `<div class="tmv3-alerts">${alerts.map((row) => {
                const route = routeForAlert(row);
                return `
                    <div class="tmv3-alert tmv3-alert-${this.esc(row.severity || "info")}">
                        <div class="tmv3-alert-icon">${severityIcon(row.severity)}</div>
                        <div>
                            <div class="tmv3-alert-title">${this.esc(row.title || severityLabel(row.severity))}</div>
                            <div class="tmv3-alert-message">${this.esc(row.message || "")}</div>
                        </div>
                        <div class="tmv3-actions">
                            ${route ? `<a class="tmv3-action-btn" href="${route}">${__("فتح")}</a>` : ""}
                            ${this.canPrepareSettlement && row.doctype === "Shift Payment Reconciliation"
                                ? `<button class="tmv3-action-btn tmv3-action-success tmv3-settle-reconciliation" data-reconciliation="${this.esc(row.document || "")}">${__("تسوية")}</button>`
                                : ""}
                            ${this.canPrepareSettlement && row.doctype === "Card Settlement Batch"
                                ? `<button class="tmv3-action-btn tmv3-action-success tmv3-settle-card-batch" data-batch="${this.esc(row.document || "")}">${__("تسوية بنكية")}</button>`
                                : ""}
                        </div>
                    </div>
                `;
            }).join("")}</div>`
            : `<div class="tmv3-dashboard-ok">${__("لا توجد تنبيهات حرجة أو تسويات متأخرة حاليًا.")}</div>`;

        const accountRows = accounts.length
            ? accounts.map((row) => {
                const difference = Number(row.unmatched_balance || 0);
                const differenceClass = Math.abs(difference) <= 0.01
                    ? "tmv3-balance-positive"
                    : "tmv3-balance-review";
                const overdueBadge = Number(row.overdue_document_count || 0) > 0
                    ? `<span class="tmv3-badge tmv3-badge-off">${this.esc(row.overdue_document_count)} ${__("متأخرة")}</span>`
                    : `<span class="tmv3-badge tmv3-badge-on">${__("لا توجد متأخرات")}</span>`;
                return `
                    <tr>
                        <td><a href="/app/account/${encodeURIComponent(row.account || "")}">${this.esc(row.account || "-")}</a></td>
                        <td>${this.esc(row.source_label || "-")}</td>
                        <td>${this.esc(row.destination_label || "-")}</td>
                        <td>${this.formatMoney(row.current_balance, row.currency || currency)}</td>
                        <td>${this.formatMoney(row.documented_pending, row.currency || currency)}</td>
                        <td class="${differenceClass}">${this.formatMoney(row.unmatched_balance, row.currency || currency)}</td>
                        <td>${this.esc(row.open_document_count || 0)}</td>
                        <td>${overdueBadge}<br><small>${this.esc(row.oldest_pending_days || 0)} ${__("يوم")}</small></td>
                        <td>${this.esc((row.last_movement || {}).posting_date || "-")}</td>
                    </tr>
                `;
            }).join("")
            : `<tr><td colspan="9" class="tmv3-empty">${__("لا توجد حسابات Clearing مرتبطة بالإعدادات الحالية.")}</td></tr>`;

        const cardRows = cardBatches.length
            ? cardBatches.map((row) => `
                <tr>
                    <td><a href="/app/card-settlement-batch/${encodeURIComponent(row.name || "")}">${this.esc(row.name || "-")}</a></td>
                    <td>${this.esc(row.pos_terminal || "-")}</td>
                    <td>${this.esc(row.status || "-")}</td>
                    <td>${this.esc(row.close_time || "-")}</td>
                    <td>${this.formatMoney(row.outstanding_amount, currency)}</td>
                    <td>${this.esc(row.age_days || 0)} ${__("يوم")}</td>
                    <td><span class="tmv3-badge ${row.overdue ? "tmv3-badge-off" : "tmv3-badge-on"}">${row.overdue ? __("متأخرة") : __("معلّقة اليوم")}</span></td>
                    <td>
                        ${this.canPrepareSettlement
                            ? `<button class="tmv3-action-btn tmv3-action-success tmv3-settle-card-batch" data-batch="${this.esc(row.name || "")}">${__("تسوية بنكية")}</button>`
                            : ""}
                    </td>
                </tr>
            `).join("")
            : `<tr><td colspan="8" class="tmv3-empty">${__("لا توجد دفعات فيزا غير مسوّاة.")}</td></tr>`;

        const reconciliationRows = reconciliations.length
            ? reconciliations.map((row) => `
                <tr>
                    <td><a href="/app/shift-payment-reconciliation/${encodeURIComponent(row.name || "")}">${this.esc(row.name || "-")}</a></td>
                    <td>${this.esc(row.mode_of_payment || "-")}</td>
                    <td>${this.esc(row.shift_reference || "-")}</td>
                    <td>${this.esc(row.status || "-")}</td>
                    <td>${this.formatMoney(row.pending_amount, currency)}</td>
                    <td>${this.esc(row.to_time || "-")}</td>
                    <td>${this.esc(row.age_days || 0)} ${__("يوم")}</td>
                    <td><span class="tmv3-badge ${row.overdue ? "tmv3-badge-off" : "tmv3-badge-on"}">${row.overdue ? __("متأخرة") : __("معلّقة اليوم")}</span></td>
                    <td>
                        ${this.canPrepareSettlement
                            ? `<button class="tmv3-action-btn tmv3-action-success tmv3-settle-reconciliation" data-reconciliation="${this.esc(row.name || "")}">${__("تسوية")}</button>`
                            : ""}
                    </td>
                </tr>
            `).join("")
            : `<tr><td colspan="9" class="tmv3-empty">${__("لا توجد تسويات دفع إلكتروني مفتوحة.")}</td></tr>`;

        return `
            <div class="tmv3-section">
                <h4>${__("لوحة الأرصدة المعلّقة والتنبيهات والتسويات المتأخرة")}</h4>
                <div class="tmv3-dashboard-note">
                    <span>${__("الرصيد المعلّق هو رصيد حساب Clearing الفعلي، والمبلغ الموثق هو إجمالي المستندات المفتوحة المرتبطة به.")}</span>
                    <span>${__("تاريخ اللوحة")}: ${this.esc(data.generated_on || "-")}</span>
                </div>

                <div class="tmv3-grid">
                    ${this.card(__("إجمالي أرصدة Clearing"), this.formatMoney(summary.total_clearing_balance, currency), __("Unique Clearing Accounts"))}
                    ${this.card(__("موثق بمستندات مفتوحة"), this.formatMoney(summary.total_documented_pending, currency), __("Open Settlements"))}
                    ${this.card(__("فرق يحتاج مراجعة"), this.formatMoney(summary.total_unmatched_balance, currency), `${this.esc(summary.accounts_needing_review || 0)} ${__("حساب")}`)}
                    ${this.card(__("دفعات فيزا مفتوحة"), summary.open_card_batch_count || 0, this.formatMoney(summary.open_card_batch_amount, currency))}
                    ${this.card(__("تسويات دفع مفتوحة"), summary.open_reconciliation_count || 0, this.formatMoney(summary.open_reconciliation_amount, currency))}
                    ${this.card(__("تسويات متأخرة"), Number(summary.overdue_card_batch_count || 0) + Number(summary.overdue_reconciliation_count || 0), this.formatMoney(Number(summary.overdue_card_batch_amount || 0) + Number(summary.overdue_reconciliation_amount || 0), currency))}
                    ${this.card(__("تنبيهات حرجة"), summary.critical_alert_count || 0, __("Critical"))}
                    ${this.card(__("تنبيهات مراجعة"), summary.warning_alert_count || 0, __("Warnings"))}
                </div>

                ${alertsHtml}

                <h5>${__("أرصدة حسابات Clearing")}</h5>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table" style="min-width:1250px;">
                        <thead><tr>
                            <th>${__("حساب Clearing")}</th><th>${__("المصدر")}</th><th>${__("الحساب النهائي")}</th>
                            <th>${__("الرصيد الفعلي")}</th><th>${__("موثق بمستندات")}</th><th>${__("الفرق")}</th>
                            <th>${__("مستندات مفتوحة")}</th><th>${__("التأخير")}</th><th>${__("آخر حركة")}</th>
                        </tr></thead>
                        <tbody>${accountRows}</tbody>
                    </table>
                </div>

                <h5 style="margin-top:18px;">${__("دفعات الفيزا غير المسوّاة")}</h5>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table">
                        <thead><tr>
                            <th>${__("الدفعة")}</th><th>${__("الماكينة")}</th><th>${__("الحالة")}</th>
                            <th>${__("وقت الإغلاق")}</th><th>${__("المتبقي")}</th><th>${__("العمر")}</th><th>${__("التصنيف")}</th><th>${__("إجراءات")}</th>
                        </tr></thead>
                        <tbody>${cardRows}</tbody>
                    </table>
                </div>

                <h5 style="margin-top:18px;">${__("تسويات الدفع الإلكتروني المفتوحة")}</h5>
                <div class="tmv3-table-wrap">
                    <table class="tmv3-table">
                        <thead><tr>
                            <th>${__("التسوية")}</th><th>${__("طريقة الدفع")}</th><th>${__("الوردية")}</th><th>${__("الحالة")}</th>
                            <th>${__("المبلغ المعلّق")}</th><th>${__("حتى")}</th><th>${__("العمر")}</th><th>${__("التصنيف")}</th><th>${__("إجراءات")}</th>
                        </tr></thead>
                        <tbody>${reconciliationRows}</tbody>
                    </table>
                </div>

                <div class="tmv3-preview-note">
                    <strong>${__("قاعدة التأخير")}:</strong>
                    ${__("يُصنف المستند كمتأخر عندما يظل مفتوحًا بعد تاريخ الإغلاق أو نهاية الفترة. مستندات اليوم تظهر كمعلّقة وليست متأخرة.")}
                </div>
            </div>
        `;
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

    bindSettlementActions() {
        this.$main
            .find(".tmv3-settle-reconciliation")
            .off("click.tmv3-settlement")
            .on("click.tmv3-settlement", (event) => {
                const reconciliation = $(event.currentTarget).attr("data-reconciliation");
                this.openReconciliationSettlementDialog(reconciliation);
            });
        this.$main
            .find(".tmv3-settle-card-batch")
            .off("click.tmv3-card-settlement")
            .on("click.tmv3-card-settlement", (event) => {
                const batch = $(event.currentTarget).attr("data-batch");
                this.openCardBankSettlementDialog(batch);
            });
    }

    openCardSettlementPicker() {
        const dialog = new frappe.ui.Dialog({
            title: __("اختيار دفعة فيزا للتسوية البنكية"),
            fields: [
                {
                    fieldname: "batch_name",
                    fieldtype: "Link",
                    options: "Card Settlement Batch",
                    label: __("دفعة فيزا مفتوحة"),
                    reqd: 1,
                    get_query: () => ({
                        filters: {
                            docstatus: 1,
                            status: ["in", ["Awaiting Bank Settlement", "Partially Settled", "Disputed"]],
                            outstanding_amount: [">", 0.005],
                        },
                    }),
                },
            ],
            primary_action_label: __("متابعة"),
            primary_action: (values) => {
                dialog.hide();
                this.openCardBankSettlementDialog(values.batch_name);
            },
        });
        dialog.show();
    }

    async openCardBankSettlementDialog(batchName) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_card_bank_settlement_options",
            args: { batch_name: batchName },
            freeze: true,
            freeze_message: __("جاري تحميل دفعات الفيزا المتوافقة..."),
        });
        const data = response.message || {};
        const batches = data.batches || [];
        if (!batches.length) {
            frappe.msgprint(__("لا توجد دفعات فيزا مفتوحة ومتوافقة مع هذه الدفعة."));
            return;
        }
        const batchRows = batches.map((row) => `
            <tr class="tmv3-card-allocation-row" data-batch="${this.esc(row.name || "")}">
                <td><input type="checkbox" class="tmv3-card-allocation-check" ${row.selected ? "checked" : ""}></td>
                <td><a href="/app/card-settlement-batch/${encodeURIComponent(row.name || "")}" target="_blank">${this.esc(row.name || "-")}</a></td>
                <td>${this.esc(row.pos_terminal || "-")}</td>
                <td>${this.esc(row.shift_reference || "-")}</td>
                <td>${this.esc(row.close_time || "-")}</td>
                <td>${this.esc(row.status || "-")}</td>
                <td>${this.formatMoney(row.outstanding_amount, data.currency)}</td>
                <td><input type="number" class="form-control input-xs tmv3-card-allocation-amount" min="0.01" step="0.01" max="${this.esc(row.outstanding_amount)}" value="${this.esc(row.outstanding_amount)}" ${row.selected ? "" : "disabled"}></td>
            </tr>
        `).join("");

        const dialog = new frappe.ui.Dialog({
            title: `${__("تنفيذ Card Bank Settlement")}: ${this.esc(data.bank || data.destination_bank_account || "")}`,
            size: "extra-large",
            fields: [
                {
                    fieldtype: "HTML",
                    options: `
                        <div style="direction:rtl;text-align:right;">
                            <div class="tmv3-preview" style="margin-bottom:14px;">
                                <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الشركة")}</div><div class="tmv3-preview-value">${this.esc(data.company || "-")}</div></div>
                                <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("حساب Clearing")}</div><div class="tmv3-preview-value">${this.esc(data.clearing_account || "-")}</div></div>
                                <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الحساب البنكي النهائي")}</div><div class="tmv3-preview-value">${this.esc(data.destination_bank_account || "-")}</div></div>
                                <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("Bank Account")}</div><div class="tmv3-preview-value">${this.esc(data.bank_account_name || data.bank_account || "-")}</div></div>
                                <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("رصيد Clearing الحالي")}</div><div class="tmv3-preview-value">${this.formatMoney(data.clearing_balance, data.currency)}</div></div>
                            </div>
                            <div class="tmv3-table-wrap"><table class="tmv3-table" style="min-width:1150px;">
                                <thead><tr>
                                    <th>${__("اختيار")}</th><th>${__("الدفعة")}</th><th>${__("الماكينة")}</th><th>${__("الوردية")}</th>
                                    <th>${__("وقت الإغلاق")}</th><th>${__("الحالة")}</th><th>${__("المتاح")}</th><th>${__("مبلغ التسوية")}</th>
                                </tr></thead>
                                <tbody>${batchRows}</tbody>
                            </table></div>
                            <div class="tmv3-preview-note">${__("يمكن جمع عدة دفعات في تسوية بنكية واحدة بشرط استخدام نفس حساب Clearing ونفس الحساب البنكي النهائي.")}</div>
                        </div>
                    `,
                },
                {
                    fieldname: "settlement_date",
                    fieldtype: "Date",
                    label: __("تاريخ وصول التسوية للبنك"),
                    default: data.settlement_date || frappe.datetime.get_today(),
                    reqd: 1,
                },
                {
                    fieldname: "bank_reference",
                    fieldtype: "Data",
                    label: __("مرجع البنك"),
                    reqd: 1,
                },
                {
                    fieldname: "fee_amount",
                    fieldtype: "Currency",
                    label: __("إجمالي عمولة البنك"),
                    default: 0,
                    non_negative: 1,
                    description: `${__("حساب الرسوم")}: ${this.esc(data.fee_account || "-")}`,
                },
                {
                    fieldname: "statement_attachment",
                    fieldtype: "Attach",
                    label: __("كشف أو إثبات التسوية"),
                },
                {
                    fieldname: "notes",
                    fieldtype: "Small Text",
                    label: __("ملاحظات"),
                },
            ],
            primary_action_label: __("معاينة التسوية"),
            primary_action: async (values) => {
                const allocations = this.collectCardSettlementAllocations(dialog);
                const args = {
                    batch_name: data.seed_batch,
                    allocations: JSON.stringify(allocations),
                    ...values,
                };
                const previewResponse = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.preview_card_bank_settlement",
                    args,
                    freeze: true,
                    freeze_message: __("جاري مراجعة الدفعات والحسابات..."),
                });
                this.showCardBankSettlementConfirmation(dialog, args, previewResponse.message || {});
            },
        });
        dialog.show();
        dialog.$wrapper
            .find(".tmv3-card-allocation-check")
            .on("change", (event) => {
                const $row = $(event.currentTarget).closest(".tmv3-card-allocation-row");
                $row.find(".tmv3-card-allocation-amount").prop("disabled", !event.currentTarget.checked);
            });
    }

    collectCardSettlementAllocations(dialog) {
        const allocations = [];
        dialog.$wrapper.find(".tmv3-card-allocation-row").each((index, element) => {
            const $row = $(element);
            if (!$row.find(".tmv3-card-allocation-check").prop("checked")) return;
            allocations.push({
                card_settlement_batch: $row.attr("data-batch"),
                allocated_amount: flt($row.find(".tmv3-card-allocation-amount").val()),
            });
        });
        if (!allocations.length) {
            frappe.throw(__("اختر دفعة واحدة على الأقل للتسوية."));
        }
        return allocations;
    }

    showCardBankSettlementConfirmation(sourceDialog, sourceValues, preview) {
        const canExecute = this.canExecuteSettlement;
        const allocationRows = (preview.allocations || []).map((row) => `
            <tr>
                <td>${this.esc(row.card_settlement_batch || "-")}</td>
                <td>${this.esc(row.pos_terminal || "-")}</td>
                <td>${this.esc(row.shift_reference || "-")}</td>
                <td>${this.formatMoney(row.available_amount, preview.currency)}</td>
                <td>${this.formatMoney(row.allocated_amount, preview.currency)}</td>
            </tr>
        `).join("");
        const confirmDialog = new frappe.ui.Dialog({
            title: canExecute
                ? __("تأكيد التسوية البنكية لدفعات الفيزا")
                : __("معاينة التسوية البنكية لدفعات الفيزا"),
            size: "extra-large",
            fields: [{
                fieldtype: "HTML",
                options: `
                    <div style="direction:rtl;text-align:right;">
                        <div class="tmv3-preview" style="margin-bottom:14px;">
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("مرجع البنك")}</div><div class="tmv3-preview-value">${this.esc(preview.bank_reference || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("تاريخ التسوية")}</div><div class="tmv3-preview-value">${this.esc(preview.settlement_date || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الإجمالي")}</div><div class="tmv3-preview-value">${this.formatMoney(preview.gross_amount, preview.currency)}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("عمولة البنك")}</div><div class="tmv3-preview-value">${this.formatMoney(preview.fee_amount, preview.currency)}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("صافي البنك")}</div><div class="tmv3-preview-value">${this.formatMoney(preview.net_amount, preview.currency)}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("رصيد Clearing قبل / بعد")}</div><div class="tmv3-preview-value">${this.formatMoney(preview.clearing_balance_before, preview.currency)} → ${this.formatMoney(preview.clearing_balance_after, preview.currency)}</div></div>
                        </div>
                        <div class="tmv3-table-wrap"><table class="tmv3-table">
                            <thead><tr><th>${__("الدفعة")}</th><th>${__("الماكينة")}</th><th>${__("الوردية")}</th><th>${__("المتاح")}</th><th>${__("المخصص")}</th></tr></thead>
                            <tbody>${allocationRows}</tbody>
                        </table></div>
                        <div class="tmv3-preview-note"><strong>${__("مهم")}:</strong> ${canExecute
                            ? __("سيتم إنشاء واعتماد Card Bank Settlement، وسيقوم المستند بإنشاء Journal Entry وتحديث المبالغ المتبقية وحالة كل Batch تلقائيًا.")
                            : __("هذه معاينة فقط. يلزم Treasury Manager أو Accounts Manager لتنفيذ التسوية وإنشاء القيد المحاسبي.")}</div>
                    </div>
                `,
            }],
            primary_action_label: canExecute ? __("تنفيذ التسوية البنكية") : __("إغلاق المعاينة"),
            primary_action: async () => {
                if (!canExecute) {
                    confirmDialog.hide();
                    return;
                }
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.execute_card_bank_settlement",
                    args: sourceValues,
                    freeze: true,
                    freeze_message: __("جاري إنشاء واعتماد التسوية البنكية..."),
                });
                const result = response.message || {};
                confirmDialog.hide();
                sourceDialog.hide();
                frappe.msgprint({
                    title: __("تمت تسوية دفعات الفيزا"),
                    indicator: "green",
                    message: `
                        <div style="direction:rtl;text-align:right;">
                            <div>${this.esc(result.message || __("تمت التسوية بنجاح"))}</div>
                            <div><strong>${__("Card Bank Settlement")}:</strong> <a href="/app/card-bank-settlement/${encodeURIComponent(result.card_bank_settlement || "")}">${this.esc(result.card_bank_settlement || "-")}</a></div>
                            <div><strong>${__("Journal Entry")}:</strong> <a href="/app/journal-entry/${encodeURIComponent(result.journal_entry || "")}">${this.esc(result.journal_entry || "-")}</a></div>
                            <div><strong>${__("Gross / Fee / Net")}:</strong> ${this.formatMoney(result.gross_amount, "")} / ${this.formatMoney(result.fee_amount, "")} / ${this.formatMoney(result.net_amount, "")}</div>
                        </div>
                    `,
                });
                await this.refresh();
            },
        });
        confirmDialog.show();
    }

    async openReconciliationSettlementDialog(reconciliation) {
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.get_payment_reconciliation_settlement_details",
            args: { reconciliation_name: reconciliation },
            freeze: true,
            freeze_message: __("جاري تحميل بيانات التسوية..."),
        });
        const data = response.message || {};
        const currency = data.currency || "";
        const dialog = new frappe.ui.Dialog({
            title: `${__("تنفيذ تسوية الدفع")}: ${this.esc(data.reconciliation || reconciliation)}`,
            size: "large",
            fields: [
                {
                    fieldtype: "HTML",
                    options: `
                        <div class="tmv3-preview" style="margin-bottom:14px;">
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("طريقة الدفع")}</div><div class="tmv3-preview-value">${this.esc(data.mode_of_payment || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الوردية")}</div><div class="tmv3-preview-value">${this.esc(data.shift_reference || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("حساب Clearing")}</div><div class="tmv3-preview-value">${this.esc(data.clearing_account || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("الحساب النهائي")}</div><div class="tmv3-preview-value">${this.esc(data.destination_account || "-")}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("المبلغ")}</div><div class="tmv3-preview-value">${this.formatMoney(data.reviewed_amount, currency)}</div></div>
                            <div class="tmv3-preview-row"><div class="tmv3-preview-label">${__("رصيد Clearing الحالي")}</div><div class="tmv3-preview-value">${this.formatMoney(data.clearing_balance, currency)}</div></div>
                        </div>
                    `,
                },
                {
                    fieldname: "settlement_action",
                    fieldtype: "Select",
                    label: __("طريقة تنفيذ التسوية"),
                    options: "Create New Journal Entry\nLink Existing Journal Entry",
                    default: "Create New Journal Entry",
                    reqd: 1,
                },
                {
                    fieldname: "posting_date",
                    fieldtype: "Date",
                    label: __("تاريخ القيد"),
                    default: data.posting_date || frappe.datetime.get_today(),
                    reqd: 1,
                },
                {
                    fieldname: "fee_amount",
                    fieldtype: "Currency",
                    label: __("رسوم التحويل"),
                    default: Number(data.fee_amount || 0),
                    non_negative: 1,
                },
                {
                    fieldname: "bank_reference",
                    fieldtype: "Data",
                    label: __("مرجع البنك أو المحفظة"),
                    description: __("إلزامي عند إنشاء قيد جديد."),
                },
                {
                    fieldname: "existing_journal_entry",
                    fieldtype: "Link",
                    options: "Journal Entry",
                    label: __("Journal Entry موجود"),
                    depends_on: "eval:doc.settlement_action=='Link Existing Journal Entry'",
                    mandatory_depends_on: "eval:doc.settlement_action=='Link Existing Journal Entry'",
                    get_query: () => ({
                        filters: {
                            company: data.company,
                            docstatus: 1,
                        },
                    }),
                },
                {
                    fieldname: "notes",
                    fieldtype: "Small Text",
                    label: __("ملاحظات"),
                    default: data.notes || "",
                },
            ],
            primary_action_label: __("معاينة التسوية"),
            primary_action: async (values) => {
                await this.previewReconciliationSettlement(dialog, data, values);
            },
        });
        dialog.show();
    }

    async previewReconciliationSettlement(sourceDialog, details, values) {
        const args = {
            reconciliation_name: details.reconciliation,
            ...values,
        };
        const response = await frappe.call({
            method:
                "pharma_erp.pharma_erp.page.treasury_management.treasury_management.preview_payment_reconciliation_settlement",
            args,
            freeze: true,
            freeze_message: __("جاري مراجعة التسوية والقيد..."),
        });
        this.showReconciliationSettlementConfirmation(
            sourceDialog,
            args,
            response.message || {},
        );
    }

    showReconciliationSettlementConfirmation(sourceDialog, sourceValues, preview) {
        const canExecute = this.canExecuteSettlement;
        const createNew = preview.settlement_action === "Create New Journal Entry";
        const rows = [
            [__("التسوية"), preview.reconciliation],
            [__("طريقة الدفع"), preview.mode_of_payment],
            [__("طريقة التنفيذ"), createNew ? __("إنشاء Journal Entry جديد") : __("ربط Journal Entry موجود")],
            [__("Journal Entry الموجود"), preview.existing_journal_entry || "-"],
            [__("تاريخ القيد"), preview.posting_date],
            [__("مرجع البنك أو المحفظة"), preview.bank_reference || "-"],
            [__("حساب Clearing"), preview.clearing_account],
            [__("الحساب النهائي"), preview.destination_account],
            [__("المبلغ الإجمالي"), this.formatMoney(preview.reviewed_amount, "")],
            [__("الرسوم"), this.formatMoney(preview.fee_amount, "")],
            [__("صافي التحويل"), this.formatMoney(preview.net_transfer_amount, "")],
            [__("رصيد Clearing قبل"), this.formatMoney(preview.clearing_balance_before, "")],
            [__("رصيد Clearing بعد"), this.formatMoney(preview.clearing_balance_after, "")],
        ];
        const confirmDialog = new frappe.ui.Dialog({
            title: canExecute ? __("تأكيد تنفيذ التسوية") : __("معاينة تسوية الدفع"),
            size: "large",
            fields: [{
                fieldtype: "HTML",
                options: `
                    <div class="tmv3-preview">
                        ${rows.map(([label, value]) => `
                            <div class="tmv3-preview-row">
                                <div class="tmv3-preview-label">${this.esc(label)}</div>
                                <div class="tmv3-preview-value">${this.esc(value ?? "-")}</div>
                            </div>
                        `).join("")}
                    </div>
                    <div class="tmv3-preview-note">
                        <strong>${__("مهم")}:</strong>
                        ${canExecute
                            ? (createNew
                                ? __("سيتم إنشاء واعتماد قيد محاسبي، ثم ربطه بمستند التسوية وإغلاق التنبيه.")
                                : __("لن يتم إنشاء قيد جديد. سيتم التحقق من القيد الموجود وربطه بالمستند فقط لمنع التكرار."))
                            : __("هذه معاينة فقط. يلزم Treasury Manager أو Accounts Manager لتنفيذ التسوية.")}
                    </div>
                `,
            }],
            primary_action_label: canExecute ? __("تنفيذ التسوية") : __("إغلاق المعاينة"),
            primary_action: async () => {
                if (!canExecute) {
                    confirmDialog.hide();
                    return;
                }
                const response = await frappe.call({
                    method:
                        "pharma_erp.pharma_erp.page.treasury_management.treasury_management.execute_payment_reconciliation_settlement",
                    args: sourceValues,
                    freeze: true,
                    freeze_message: __("جاري تنفيذ التسوية المحاسبية..."),
                });
                confirmDialog.hide();
                sourceDialog.hide();
                const result = response.message || {};
                frappe.msgprint({
                    title: __("تم تنفيذ التسوية"),
                    indicator: "green",
                    message: `
                        <div style="direction:rtl;text-align:right;">
                            <div>${this.esc(result.message || __("تمت التسوية بنجاح"))}</div>
                            <div><strong>${__("التسوية")}:</strong> ${this.esc(result.reconciliation || "-")}</div>
                            <div><strong>${__("Journal Entry")}:</strong> <a href="/app/journal-entry/${encodeURIComponent(result.journal_entry || "")}">${this.esc(result.journal_entry || "-")}</a></div>
                        </div>
                    `,
                });
                await this.refresh();
            },
        });
        confirmDialog.show();
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

    formatDateTime(value) {
        const clean = String(value || "").split(".")[0].replace("T", " ");
        const match = clean.match(/^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}:\d{2}:\d{2}))?$/);
        if (!match) return clean || "-";
        return `${match[3]}-${match[2]}-${match[1]}${match[4] ? ` ${match[4]}` : ""}`;
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
