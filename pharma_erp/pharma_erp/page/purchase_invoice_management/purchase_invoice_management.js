frappe.pages["purchase-invoice-management"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Purchase & Invoice Management"),
        single_column: true,
    });

    new PurchaseInvoiceManagementPageV1(page, wrapper);
};


class PurchaseInvoiceManagementPageV1 {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$main = page.main ? $(page.main) : $(wrapper).find(".layout-main-section");
        this.bootstrap = {};
        this.supplierContext = {};
        this.rows = [];
        this.controls = {};
        this.recentControls = {};
        this.draftName = null;
        this.attachmentUrl = "";
        this.lastSavedTotals = null;
        this.isSaving = false;
        this.activeRowIndex = null;
        this.recentPanelOpen = false;
        this.wideMode = true;

        this.addStyles();
        this.setupLayoutControls();
        this.page.set_primary_action(__("Save Draft"), () => this.saveDraft(), "save");
        this.page.add_inner_button(__("New Invoice"), () => this.resetInvoice(), __("Invoice"));
        this.$openButton = this.page.add_inner_button(
            __("Open Official Document"),
            () => this.openOfficialDocument(),
            __("Invoice")
        );
        this.$openButton.prop("disabled", true);
        this.page.add_inner_button(__("Refresh"), () => this.loadBootstrap(), __("Actions"));
        this.$wideButton = this.page.add_inner_button(__("Normal Width"), () => this.toggleWideMode(), __("View"));
        this.$fullscreenButton = this.page.add_inner_button(__("Full Screen"), () => this.toggleFullScreen(), __("View"));

        this.renderLoading();
        this.loadBootstrap();
    }

    addStyles() {
        if ($("#purchase-invoice-management-v1-style").length) return;
        $("head").append(`
            <style id="purchase-invoice-management-v1-style">
                .pimv1 { direction: rtl; text-align: right; padding: 0 0 38px; width: 100%; max-width: none; }
                .pimv1 * { box-sizing: border-box; }
                .pimv1-layout-wide { width: 100% !important; max-width: none !important; }
                .pimv1-container-wide { width: 100% !important; max-width: none !important; padding-left: 14px !important; padding-right: 14px !important; }
                .pimv1-main-wide { width: 100% !important; max-width: none !important; }
                .pimv1-fullscreen-target:fullscreen { background: var(--bg-color); overflow: auto; padding: 10px; }
                .pimv1-fullscreen-target:fullscreen .layout-main-section-wrapper,
                .pimv1-fullscreen-target:fullscreen .layout-main-section { width: 100% !important; max-width: none !important; }
                .pimv1-hero {
                    display: flex; justify-content: space-between; align-items: center; gap: 18px;
                    border: 1px solid var(--border-color); border-radius: 16px; padding: 20px;
                    background: linear-gradient(135deg, var(--card-bg), var(--control-bg)); margin-bottom: 14px;
                }
                .pimv1-hero h2 { margin: 0 0 6px; font-weight: 800; }
                .pimv1-hero p { margin: 0; color: var(--text-muted); }
                .pimv1-doc-badge { border-radius: 999px; padding: 7px 12px; background: var(--blue-100); color: var(--blue-700); font-weight: 700; white-space: nowrap; }
                .pimv1-grid { display: grid; gap: 12px; }
                .pimv1-grid-4 { grid-template-columns: repeat(4, minmax(170px, 1fr)); }
                .pimv1-grid-3 { grid-template-columns: repeat(3, minmax(190px, 1fr)); }
                .pimv1-grid-2 { grid-template-columns: repeat(2, minmax(240px, 1fr)); }
                .pimv1-card, .pimv1-section { border: 1px solid var(--border-color); background: var(--card-bg); border-radius: 14px; }
                .pimv1-card { padding: 14px; min-height: 96px; }
                .pimv1-card-label { color: var(--text-muted); font-size: 12px; }
                .pimv1-card-value { font-size: 22px; font-weight: 800; margin-top: 8px; word-break: break-word; }
                .pimv1-card-note { color: var(--text-muted); font-size: 11px; margin-top: 5px; }
                .pimv1-section { padding: 16px; margin-top: 14px; }
                .pimv1-section-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 13px; }
                .pimv1-section-title h4 { margin: 0; font-weight: 800; }
                .pimv1-field .form-group { margin-bottom: 0; }
                .pimv1-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
                .pimv1-barcode { min-width: 260px; direction: ltr; }
                .pimv1-table-wrap { overflow: hidden; border: 1px solid var(--border-color); border-radius: 12px; }
                .pimv1-items-list { display: block; width: 100%; }
                .pimv1-items-header,
                .pimv1-row-grid {
                    display: grid;
                    grid-template-columns: 34px 1.65fr .55fr .72fr .78fr .70fr .70fr .68fr .80fr .80fr .82fr .84fr 1.15fr .72fr;
                    gap: 5px;
                    align-items: center;
                    width: 100%;
                    min-width: 0;
                }
                .pimv1-items-header {
                    padding: 7px 6px;
                    background: var(--subtle-fg);
                    border-bottom: 1px solid var(--border-color);
                    color: var(--text-muted);
                    font-size: 10px;
                    font-weight: 800;
                    line-height: 1.15;
                }
                .pimv1-items-header > div { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: center; }
                .pimv1-item-row {
                    border: 0;
                    border-bottom: 1px solid var(--border-color);
                    border-radius: 0;
                    padding: 5px 6px;
                    background: var(--card-bg);
                    transition: background .15s ease, box-shadow .15s ease;
                }
                .pimv1-item-row:last-child { border-bottom: 0; }
                .pimv1-item-row.is-active { background: var(--blue-50); box-shadow: inset -3px 0 0 var(--primary); }
                .pimv1-row-field { min-width: 0; overflow: hidden; }
                .pimv1-row-number { display: inline-flex; align-items: center; justify-content: center; width: 25px; height: 25px; border-radius: 50%; background: var(--control-bg); font-size: 11px; font-weight: 800; }
                .pimv1-item-one-line { display: flex; align-items: center; gap: 4px; min-width: 0; }
                .pimv1-item-name { font-weight: 700; font-size: 11px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .pimv1-item-code { color: var(--text-muted); font-size: 9px; direction: ltr; white-space: nowrap; flex: 0 0 auto; }
                .pimv1-qty-wrap { display: flex; align-items: center; gap: 3px; min-width: 0; }
                .pimv1-uom-inline { color: var(--text-muted); font-size: 9px; white-space: nowrap; }
                .pimv1-pill { display: inline-flex; padding: 4px 8px; border-radius: 999px; font-size: 10px; font-weight: 800; }
                .pimv1-pill-normal { background: var(--blue-100); color: var(--blue-700); }
                .pimv1-pill-bonus { background: var(--green-100); color: var(--green-700); }
                .pimv1-empty { padding: 30px 16px; text-align: center; color: var(--text-muted); }
                .pimv1-row-actions { display: flex; justify-content: center; gap: 3px; }
                .pimv1-icon-btn { border: 1px solid var(--border-color); background: var(--control-bg); color: var(--text-color); border-radius: 6px; width: 28px; height: 28px; padding: 0; cursor: pointer; font-size: 16px; line-height: 26px; text-align: center; }
                .pimv1-icon-btn:hover { background: var(--subtle-fg); }
                .pimv1-danger { color: var(--red-600); }
                .pimv1-inline-input, .pimv1-inline-select {
                    width: 100%; min-width: 0; height: 28px; padding: 3px 4px; border: 1px solid var(--border-color);
                    border-radius: 5px; background: var(--control-bg); color: var(--text-color); direction: ltr; font-size: 11px;
                }
                .pimv1-readonly-cell { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: center; }
                .pimv1-pill { padding: 3px 5px; font-size: 9px; justify-content: center; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .pimv1-inline-wide, .pimv1-inline-tax { min-width: 0; }
                .pimv1-shortcuts-hint { margin-top: 8px; color: var(--text-muted); font-size: 11px; }
                .pimv1-readonly-cell { font-weight: 700; }
                .pimv1-tax-note { margin-top: 8px; color: var(--text-muted); font-size: 11px; }
                .pimv1-summary { display: grid; grid-template-columns: 1.4fr .9fr; gap: 12px; margin-top: 14px; }
                .pimv1-summary-box { border: 1px solid var(--border-color); border-radius: 12px; overflow: hidden; }
                .pimv1-summary-row { display: flex; justify-content: space-between; gap: 16px; padding: 9px 12px; border-bottom: 1px solid var(--border-color); }
                .pimv1-summary-row:last-child { border-bottom: 0; }
                .pimv1-summary-row strong { font-size: 15px; }
                .pimv1-summary-grand { background: var(--green-50); }
                .pimv1-help { padding: 12px; border-radius: 10px; background: var(--yellow-50); border: 1px solid var(--yellow-200); color: var(--text-color); }
                .pimv1-recent { width: 100%; border-collapse: collapse; }
                .pimv1-recent th, .pimv1-recent td { padding: 9px; border-bottom: 1px solid var(--border-color); text-align: right; }
                .pimv1-recent th { color: var(--text-muted); font-size: 11px; }
                .pimv1-link { color: var(--primary); font-weight: 700; cursor: pointer; }
                .pimv1-loading, .pimv1-error { padding: 36px; text-align: center; }
                .pimv1-attachment { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
                .pimv1-file-name { color: var(--text-muted); max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .pimv1-history { direction: rtl; margin-top: 10px; font-size: 12px; }
                .pimv1-history table { width: 100%; border-collapse: collapse; }
                .pimv1-history td, .pimv1-history th { padding: 5px; border-bottom: 1px solid var(--border-color); text-align: right; }
                .pimv1-item-snapshot-fixed {
                    height: 190px;
                    min-height: 190px;
                    overflow: auto;
                    border-radius: 10px;
                }
                .pimv1-item-snapshot-fixed > .pimv1-help {
                    min-height: 100%;
                    margin: 0;
                    overflow: auto;
                }
                .pimv1-item-snapshot-fixed .pimv1-history {
                    max-height: 125px;
                    overflow: auto;
                    margin-top: 7px;
                }
                .pimv1-item-snapshot-fixed .pimv1-history thead th {
                    position: sticky;
                    top: 0;
                    z-index: 2;
                    background: var(--yellow-50);
                }
                .pimv1-field[data-field="tax_included_in_print_rate"] .checkbox label {
                    display: flex !important;
                    align-items: flex-start !important;
                    gap: 8px !important;
                    padding: 0 !important;
                    margin: 0 !important;
                    white-space: normal !important;
                    line-height: 1.35 !important;
                }
                .pimv1-field[data-field="tax_included_in_print_rate"] .checkbox input[type="checkbox"] {
                    position: static !important;
                    flex: 0 0 auto !important;
                    margin: 2px 0 0 0 !important;
                }
                .pimv1-field[data-field="tax_included_in_print_rate"] .checkbox .label-area {
                    margin: 0 !important;
                    padding: 0 !important;
                }
                .pimv1-field[data-field="tax_included_in_print_rate"] .help-box {
                    margin-top: 5px !important;
                    padding: 0 !important;
                }
                .pimv1-collapsible-title { width: 100%; border: 0; background: transparent; color: var(--text-color); display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0; cursor: pointer; text-align: right; }
                .pimv1-collapsible-title h4 { margin: 0; font-weight: 800; }
                .pimv1-collapsible-meta { color: var(--text-muted); font-size: 12px; display: inline-flex; align-items: center; gap: 8px; }
                .pimv1-collapsible-icon { display: inline-block; transition: transform .18s ease; font-size: 15px; }
                .pimv1-collapsible-title.is-open .pimv1-collapsible-icon { transform: rotate(180deg); }
                .pimv1-recent-panel { display: none; margin-top: 14px; }
                .pimv1-recent-panel.is-open { display: block; }
                .pimv1-recent-filters { display: grid; grid-template-columns: repeat(4, minmax(180px, 1fr)); gap: 10px; align-items: end; padding: 12px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--control-bg); }
                .pimv1-recent-filter-actions { display: flex; gap: 8px; align-items: center; justify-content: flex-start; margin-top: 10px; flex-wrap: wrap; }
                .pimv1-recent-status { color: var(--text-muted); font-size: 12px; margin-inline-start: auto; }
                .pimv1-recent-results { margin-top: 10px; overflow-x: auto; }
                @media (max-width: 1100px) {
                    .pimv1-grid-4, .pimv1-grid-3 { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
                    .pimv1-summary { grid-template-columns: 1fr; }
                    .pimv1-recent-filters { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
                }
                @media (max-width: 650px) {
                    .pimv1-hero { align-items: flex-start; flex-direction: column; }
                    .pimv1-grid-4, .pimv1-grid-3, .pimv1-grid-2 { grid-template-columns: 1fr; }
                    .pimv1-barcode { min-width: 100%; }
                    .pimv1-recent-filters { grid-template-columns: 1fr; }
                }
            </style>
        `);
    }

    setupLayoutControls() {
        this.$pageRoot = $(this.wrapper).addClass("pimv1-fullscreen-target");
        this.$layoutWrapper = this.$main.closest(".layout-main-section-wrapper");
        this.$layoutContainer = this.$main.closest(".container");
        $(document).off("fullscreenchange.pimv1").on("fullscreenchange.pimv1", () => {
            if (this.$fullscreenButton) {
                this.$fullscreenButton.text(document.fullscreenElement ? __("Exit Full Screen") : __("Full Screen"));
            }
        });
    }

    applyWideMode(enabled) {
        this.wideMode = Boolean(enabled);
        this.$layoutWrapper.toggleClass("pimv1-layout-wide", this.wideMode);
        this.$layoutContainer.toggleClass("pimv1-container-wide", this.wideMode);
        this.$main.toggleClass("pimv1-main-wide", this.wideMode);
        if (this.$wideButton) this.$wideButton.text(this.wideMode ? __("Normal Width") : __("Wide View"));
    }

    toggleWideMode() {
        this.applyWideMode(!this.wideMode);
    }

    async toggleFullScreen() {
        try {
            if (!document.fullscreenElement) {
                const target = this.wrapper && this.wrapper.requestFullscreen ? this.wrapper : this.$pageRoot.get(0);
                if (target && target.requestFullscreen) await target.requestFullscreen();
            } else {
                await document.exitFullscreen();
            }
        } catch (error) {
            frappe.show_alert({ message: __("Full screen is not available in this browser window."), indicator: "orange" }, 5);
        }
    }

    renderLoading() {
        this.$main.html(`<div class="pimv1-loading">${__("Loading Purchase Management...")}</div>`);
    }

    async loadBootstrap() {
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_bootstrap",
                freeze: true,
                freeze_message: __("Loading purchase settings..."),
            });
            this.bootstrap = response.message || {};
            this.render();
        } catch (error) {
            this.$main.html(`<div class="pimv1-error text-danger">${this.escape(error.message || error)}</div>`);
        }
    }

    render() {
        this.$main.html(`
            <div class="pimv1">
                <div class="pimv1-hero">
                    <div>
                        <h2>${__("Purchase & Invoice Management")}</h2>
                        <p>${__("Operational purchase entry with Purchase Invoice, stock and accounting in the background.")}</p>
                    </div>
                    <div class="pimv1-doc-badge" data-role="draft-badge">${__("New Draft")}</div>
                </div>

                <div class="pimv1-grid pimv1-grid-4">
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Supplier Balance")}</div><div class="pimv1-card-value" data-role="supplier-balance">—</div><div class="pimv1-card-note" data-role="supplier-type">${__("Select supplier")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Items")}</div><div class="pimv1-card-value" data-role="items-count">0</div><div class="pimv1-card-note" data-role="bonus-count">${__("Bonus lines: 0")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Estimated Net Before Added Tax")}</div><div class="pimv1-card-value" data-role="estimated-net">0.00</div><div class="pimv1-card-note">${__("After line and invoice discounts")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Estimated VAT / Tax")}</div><div class="pimv1-card-value" data-role="estimated-tax">0.00</div><div class="pimv1-card-note" data-role="estimated-tax-note">${__("Live estimate from item tax templates")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Estimated Grand Total")}</div><div class="pimv1-card-value" data-role="estimated-grand">0.00</div><div class="pimv1-card-note">${__("ERPNext confirms the actual value on save")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Saved Tax / Grand Total")}</div><div class="pimv1-card-value" data-role="saved-grand">—</div><div class="pimv1-card-note" data-role="saved-status">${__("Not saved yet")}</div></div>
                </div>

                <div class="pimv1-section">
                    <div class="pimv1-section-title"><h4>${__("Invoice Header")}</h4><span class="text-muted">${__("Quick Invoice & Receipt")}</span></div>
                    <div class="pimv1-grid pimv1-grid-4">
                        <div class="pimv1-field" data-field="company"></div>
                        <div class="pimv1-field" data-field="supplier"></div>
                        <div class="pimv1-field" data-field="warehouse"></div>
                        <div class="pimv1-field" data-field="payment_classification"></div>
                        <div class="pimv1-field" data-field="posting_date"></div>
                        <div class="pimv1-field" data-field="bill_no"></div>
                        <div class="pimv1-field" data-field="bill_date"></div>
                        <div class="pimv1-field" data-field="due_date"></div>
                        <div class="pimv1-field" data-field="taxes_and_charges"></div>
                        <div class="pimv1-field" data-field="tax_included_in_print_rate"></div>
                        <div class="pimv1-field" data-field="invoice_discount_percentage"></div>
                        <div class="pimv1-field" data-field="additional_charge_account"></div>
                        <div class="pimv1-field" data-field="additional_charge_amount"></div>
                    </div>
                    <div class="pimv1-grid pimv1-grid-2" style="margin-top: 12px;">
                        <div class="pimv1-field" data-field="remarks"></div>
                        <div>
                            <label class="control-label">${__("Supplier Invoice Attachment")}</label>
                            <div class="pimv1-attachment">
                                <button class="btn btn-default btn-sm" data-action="attach">${__("Attach Invoice")}</button>
                                <span class="pimv1-file-name" data-role="attachment-name">${__("No file attached")}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="pimv1-section">
                    <div class="pimv1-section-title">
                        <h4>${__("Purchase Items")}</h4>
                        <div class="pimv1-actions">
                            <input type="text" class="form-control pimv1-barcode" data-role="barcode" placeholder="${__("Scan barcode or enter item code")}">
                            <button class="btn btn-default btn-sm" data-action="barcode-add">${__("Add Barcode")}</button>
                            <button class="btn btn-primary btn-sm" data-action="add-item">${__("Add Item")}</button>
                        </div>
                    </div>
                    <div class="pimv1-table-wrap">
                        <div class="pimv1-items-list" data-role="items-body"></div>
                    </div>
                    <div class="pimv1-shortcuts-hint" data-role="shortcuts-hint"></div>

                    <div class="pimv1-summary">
                        <div class="pimv1-help">
                            <strong>${__("Foundation rules are active")}</strong><br>
                            ${__("Bonus is saved as a separate zero-value row. Batch, expiry, supplier discount, additional discount and printed retail price are validated by the Pharma ERP backend.")}
                        </div>
                        <div class="pimv1-summary-box" data-role="summary"></div>
                    </div>
                </div>

                <div class="pimv1-section">
                    <button type="button" class="pimv1-collapsible-title" data-action="toggle-recent">
                        <h4>${__("Recent Purchase Invoices")}</h4>
                        <span class="pimv1-collapsible-meta"><span data-role="recent-count">${(this.bootstrap.recent_invoices || []).length}</span> ${__("results")} <span class="pimv1-collapsible-icon">⌄</span></span>
                    </button>
                    <div class="pimv1-recent-panel" data-role="recent-panel">
                        <div class="pimv1-recent-filters">
                            <div class="pimv1-field" data-recent-field="from_date"></div>
                            <div class="pimv1-field" data-recent-field="to_date"></div>
                            <div class="pimv1-field" data-recent-field="supplier"></div>
                            <div class="pimv1-field" data-recent-field="item_code"></div>
                        </div>
                        <div class="pimv1-recent-filter-actions">
                            <button class="btn btn-primary btn-sm" type="button" data-action="search-recent">${__("Search Invoices")}</button>
                            <button class="btn btn-default btn-sm" type="button" data-action="clear-recent">${__("Clear Filters")}</button>
                            <span class="pimv1-recent-status" data-role="recent-status">${__("Latest invoices are shown until filters are applied.")}</span>
                        </div>
                        <div class="pimv1-recent-results" data-role="recent-invoices"></div>
                    </div>
                </div>
            </div>
        `);

        this.makeControls();
        this.makeRecentControls();
        this.bindEvents();
        this.applyWideMode(this.wideMode);
        this.renderShortcutHint();
        this.renderRows();
        this.renderRecentInvoices(this.bootstrap.recent_invoices || []);
        this.refreshCards();
    }

    makeControl(fieldname, df, value, onchange) {
        const parent = this.$main.find(`[data-field="${fieldname}"]`).get(0);
        const control = frappe.ui.form.make_control({
            parent,
            df: { fieldname, ...df, onchange: () => onchange && onchange(control.get_value()) },
            render_input: true,
        });
        if (value !== undefined && value !== null) control.set_value(value);
        this.controls[fieldname] = control;
        return control;
    }

    makeRecentControl(fieldname, df, value) {
        const parent = this.$main.find(`[data-recent-field="${fieldname}"]`).get(0);
        const control = frappe.ui.form.make_control({
            parent,
            df: { fieldname: `recent_${fieldname}`, ...df },
            render_input: true,
        });
        if (value !== undefined && value !== null) control.set_value(value);
        this.recentControls[fieldname] = control;
        return control;
    }

    makeControls() {
        const company = this.bootstrap.company || "";
        const today = this.bootstrap.posting_date || frappe.datetime.get_today();
        this.makeControl("company", { label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, read_only: 1 }, company);
        this.makeControl("supplier", { label: __("Supplier"), fieldtype: "Link", options: "Supplier", reqd: 1 }, "", () => this.onSupplierChange());
        this.makeControl("warehouse", {
            label: __("Receiving Warehouse"), fieldtype: "Link", options: "Warehouse", reqd: 1,
            get_query: () => ({ filters: { company: this.value("company"), is_group: 0, disabled: 0 } }),
        }, this.bootstrap.default_warehouse || "");
        this.makeControl("payment_classification", {
            label: __("Payment Classification"), fieldtype: "Select",
            options: "\nCash Invoice\nClaim Invoice\nCredit Invoice Outside Claim",
        }, "", () => this.refreshSupplierClassification());
        this.makeControl("posting_date", { label: __("Posting Date"), fieldtype: "Date", reqd: 1 }, today);
        this.makeControl("bill_no", { label: __("Supplier Invoice No"), fieldtype: "Data", reqd: 1 }, "");
        this.makeControl("bill_date", { label: __("Supplier Invoice Date"), fieldtype: "Date" }, today);
        this.makeControl("due_date", { label: __("Due Date"), fieldtype: "Date" }, today);
        this.makeControl("taxes_and_charges", {
            label: __("Invoice Tax Template (Optional)"), fieldtype: "Link", options: "Purchase Taxes and Charges Template",
            get_query: () => ({ filters: { company: this.value("company"), disabled: 0 } }),
        }, "", () => this.refreshCards());
        this.makeControl("tax_included_in_print_rate", {
            label: __("Tax Included in Rate"),
            fieldtype: "Check",
            description: __("Sets included_in_print_rate on the official Purchase Invoice tax rows. Disable it only when VAT must be added above the entered net purchase rate."),
        }, 1, () => this.refreshCards());
        this.makeControl("invoice_discount_percentage", { label: __("Additional Invoice Discount %"), fieldtype: "Percent" }, 0, () => this.refreshCards());
        this.makeControl("additional_charge_account", {
            label: __("Shipping / Charge Account"), fieldtype: "Link", options: "Account",
            get_query: () => ({ filters: { company: this.value("company"), is_group: 0, root_type: "Expense", disabled: 0 } }),
        }, "");
        this.makeControl("additional_charge_amount", { label: __("Shipping / Additional Charges"), fieldtype: "Currency" }, 0, () => this.refreshCards());
        this.makeControl("remarks", { label: __("Purchase Notes"), fieldtype: "Small Text" }, "");
    }

    makeRecentControls() {
        this.makeRecentControl("from_date", { label: __("From Date"), fieldtype: "Date" }, "");
        this.makeRecentControl("to_date", { label: __("To Date"), fieldtype: "Date" }, "");
        this.makeRecentControl("supplier", { label: __("Supplier"), fieldtype: "Link", options: "Supplier" }, "");
        this.makeRecentControl("item_code", {
            label: __("Item"), fieldtype: "Link", options: "Item",
            get_query: () => ({ filters: { disabled: 0, is_purchase_item: 1 } }),
        }, "");
    }

    bindEvents() {
        this.$main.off(".pimv1");
        this.$main.on("click.pimv1", "[data-action='add-item']", () => this.openItemDialog());
        this.$main.on("click.pimv1", "[data-action='barcode-add']", () => this.addByBarcode());
        this.$main.on("keypress.pimv1", "[data-role='barcode']", (event) => {
            if (event.which === 13) { event.preventDefault(); this.addByBarcode(); }
        });
        this.$main.on("click.pimv1", "[data-action='attach']", () => this.openUploader());
        this.$main.on("click.pimv1", "[data-action='edit-row']", (event) => this.openItemDialog(Number($(event.currentTarget).data("index"))));
        this.$main.on("click.pimv1", "[data-action='delete-row']", (event) => this.deleteRow(Number($(event.currentTarget).data("index"))));
        this.$main.on("change.pimv1", "[data-inline-field]", (event) => this.onInlineChange(event));
        this.$main.on("focusin.pimv1 click.pimv1", "[data-row-index]", (event) => {
            this.setActiveRow(Number($(event.currentTarget).data("row-index")));
        });
        this.$main.on("keydown.pimv1", "[data-inline-field]", (event) => {
            if (event.key !== "Enter" || !cint(this.shortcutSetting("enter_moves_to_next_row", 1))) return;
            event.preventDefault();
            const $field = $(event.currentTarget);
            const index = Number($field.data("index"));
            const fieldname = $field.data("inline-field");
            const applied = this.applyInlineValue($field);
            if (applied === false) return;
            window.setTimeout(() => this.focusSameFieldInNextRow(index, fieldname), 0);
        });
        this.$main.on("click.pimv1", "[data-action='open-invoice']", (event) => frappe.set_route("Form", "Purchase Invoice", $(event.currentTarget).data("name")));
        this.$main.on("click.pimv1", "[data-action='toggle-recent']", () => this.toggleRecentPanel());
        this.$main.on("click.pimv1", "[data-action='search-recent']", () => this.searchRecentInvoices());
        this.$main.on("click.pimv1", "[data-action='clear-recent']", () => this.clearRecentFilters());
        this.bindGlobalShortcuts();
    }

    shortcutSetting(fieldname, fallback = "") {
        const settings = this.bootstrap.purchase_settings || {};
        const value = settings[fieldname];
        return value === undefined || value === null || value === "" ? fallback : value;
    }

    normalizeShortcut(value) {
        return String(value || "").trim().toUpperCase().replace(/\s+/g, "");
    }

    eventShortcut(event) {
        const parts = [];
        if (event.ctrlKey || event.metaKey) parts.push("CTRL");
        if (event.altKey) parts.push("ALT");
        if (event.shiftKey) parts.push("SHIFT");
        let key = String(event.key || "").toUpperCase();
        if (key === " ") key = "SPACE";
        if (key === "ESCAPE") key = "ESC";
        if (key === "ARROWDOWN") key = "DOWN";
        if (key === "ARROWUP") key = "UP";
        if (!["CONTROL", "ALT", "SHIFT", "META"].includes(key)) parts.push(key);
        return parts.join("+");
    }

    shortcutMatches(event, configured) {
        const expected = this.normalizeShortcut(configured);
        return Boolean(expected) && this.eventShortcut(event) === expected;
    }

    bindGlobalShortcuts() {
        $(document).off("keydown.pimv1-shortcuts").on("keydown.pimv1-shortcuts", (event) => {
            if (!this.$main.is(":visible") || !cint(this.shortcutSetting("enable_purchase_shortcuts", 1))) return;
            const $target = $(event.target);
            const typing = $target.is("input, textarea, select") || $target.attr("contenteditable") === "true";
            const actions = [
                ["shortcut_add_item", "F1", () => this.openItemDialog()],
                ["shortcut_focus_item_search", "F2", () => this.focusItemSearch()],
                ["shortcut_delete_row", "CTRL+DELETE", () => this.deleteActiveRow()],
                ["shortcut_save_draft", "CTRL+S", () => this.saveDraft()],
                ["shortcut_new_invoice", "CTRL+N", () => this.resetInvoice()],
                ["shortcut_open_official_document", "CTRL+O", () => this.openOfficialDocument()],
            ];
            for (const [fieldname, fallback, handler] of actions) {
                const configured = this.shortcutSetting(fieldname, fallback);
                if (!this.shortcutMatches(event, configured)) continue;
                if (typing && !event.ctrlKey && !event.altKey && !event.metaKey && !/^F\d+$/i.test(event.key || "")) return;
                event.preventDefault();
                event.stopPropagation();
                handler();
                return;
            }
        });
    }

    renderShortcutHint() {
        const $hint = this.$main.find("[data-role='shortcuts-hint']");
        if (!cint(this.shortcutSetting("enable_purchase_shortcuts", 1))) {
            $hint.text(__("Purchase keyboard shortcuts are disabled in Pharmacy Purchase Settings."));
            return;
        }
        const parts = [
            `${this.shortcutSetting("shortcut_add_item", "F1")}: ${__("Add Item")}`,
            `${this.shortcutSetting("shortcut_focus_item_search", "F2")}: ${__("Focus Search")}`,
            `${this.shortcutSetting("shortcut_delete_row", "CTRL+DELETE")}: ${__("Delete Active Row")}`,
            `${this.shortcutSetting("shortcut_save_draft", "CTRL+S")}: ${__("Save Draft")}`,
        ];
        $hint.text(parts.join(" • "));
    }

    focusItemSearch() {
        const $input = this.$main.find("[data-role='barcode']");
        $input.trigger("focus").select();
    }

    setActiveRow(index) {
        if (!Number.isInteger(index) || !this.rows[index]) return;
        this.activeRowIndex = index;
        this.$main.find("[data-row-index]").removeClass("is-active");
        this.$main.find(`[data-row-index="${index}"]`).addClass("is-active");
    }

    deleteActiveRow() {
        if (!Number.isInteger(this.activeRowIndex) || !this.rows[this.activeRowIndex]) {
            frappe.show_alert({ message: __("Select an item row first."), indicator: "orange" }, 4);
            return;
        }
        this.deleteRow(this.activeRowIndex);
    }

    focusSameFieldInNextRow(index, fieldname) {
        const nextIndex = index + 1;
        if (this.rows[nextIndex]) {
            const $next = this.$main.find(`[data-inline-field="${fieldname}"][data-index="${nextIndex}"]`);
            if ($next.length) {
                this.setActiveRow(nextIndex);
                $next.trigger("focus").select();
                return;
            }
        }
        this.focusItemSearch();
    }

    value(fieldname) {
        return this.controls[fieldname] ? this.controls[fieldname].get_value() : null;
    }

    async onSupplierChange() {
        const supplier = this.value("supplier");
        if (!supplier) {
            this.supplierContext = {};
            this.controls.payment_classification.set_value("");
            this.refreshCards();
            return;
        }
        const response = await frappe.call({
            method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_supplier_context",
            args: { supplier, company: this.value("company") },
        });
        this.supplierContext = response.message || {};
        if (this.supplierContext.default_payment_classification) {
            await this.controls.payment_classification.set_value(this.supplierContext.default_payment_classification);
        }
        this.refreshCards();
    }

    refreshSupplierClassification() {
        this.refreshCards();
    }

    async addByBarcode() {
        const input = this.$main.find("[data-role='barcode']");
        const searchValue = (input.val() || "").trim();
        if (!searchValue) return;
        try {
            const context = await this.fetchItemContext(null, searchValue);
            const row = this.rowFromItemContext(context);
            this.rows.push(row);
            const index = this.rows.length - 1;
            input.val("");
            this.renderRows();
            this.refreshCards();
            this.setActiveRow(index);
            window.setTimeout(() => {
                const $target = this.$main.find(`[data-inline-field="qty"][data-index="${index}"]`);
                if ($target.length) $target.trigger("focus").select();
                else this.focusItemSearch();
            }, 0);
            frappe.show_alert({
                message: __("{0} added directly. Complete batch and expiry on the row.", [context.item_name || context.item_code]),
                indicator: "green",
            }, 4);
        } catch (error) {
            frappe.msgprint({ title: __("Item Not Found"), message: this.escape(error.message || error), indicator: "red" });
        }
    }

    rowFromItemContext(context) {
        const latest = context.latest_supplier_purchase || context.latest_purchase || {};
        const printed = flt(context.custom_customer_price || latest.printed_retail_price || 0);
        return this.rowFromDialog({
            item_code: context.item_code,
            qty: 1,
            uom: context.purchase_uom || context.stock_uom || "",
            printed_retail_price: printed,
            supplier_discount: flt(latest.supplier_discount || 0),
            additional_discount: flt(latest.additional_discount || 0),
            batch_no: "",
            expiry_date: "",
            item_tax_template: context.default_item_tax_template || "",
            is_bonus: 0,
            auto_batch_reason: "",
        }, context);
    }

    async fetchItemContext(itemCode, searchValue) {
        const response = await frappe.call({
            method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_item_context",
            args: {
                item_code: itemCode || "",
                search_value: searchValue || "",
                company: this.value("company"),
                warehouse: this.value("warehouse"),
                supplier: this.value("supplier"),
            },
            freeze: true,
            freeze_message: __("Loading item purchase data..."),
        });
        return response.message || {};
    }

    openItemDialog(index = null, initialContext = null) {
        const editing = Number.isInteger(index) && this.rows[index];
        const existing = editing ? this.rows[index] : {};
        let context = initialContext || (editing ? existing : {});
        const dialog = new frappe.ui.Dialog({
            title: editing ? __("Edit Purchase Line") : __("Add Purchase Item"),
            size: "extra-large",
            fields: [
                { fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item", reqd: 1, default: existing.item_code || context.item_code || "", get_query: () => ({
                    query: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.search_purchase_items",
                    filters: { warehouse: this.value("warehouse") || "" },
                }) },
                { fieldname: "item_snapshot", fieldtype: "HTML" },
                { fieldname: "item_movement", label: __("Item Movement"), fieldtype: "Button" },
                { fieldname: "qty", label: __("Quantity"), fieldtype: "Float", reqd: 1, default: existing.qty || 1 },
                { fieldname: "uom", label: __("Purchase UOM"), fieldtype: "Link", options: "UOM", reqd: 1, hidden: 1, default: existing.uom || context.purchase_uom || context.stock_uom || "" },
                { fieldname: "column_1", fieldtype: "Column Break" },
                { fieldname: "printed_retail_price", label: __("Printed Retail Price"), fieldtype: "Currency", reqd: 1, default: existing.printed_retail_price || context.custom_customer_price || 0 },
                { fieldname: "supplier_discount", label: __("Supplier / Base Discount %"), fieldtype: "Percent", default: existing.supplier_discount || 0 },
                { fieldname: "additional_discount", label: __("Additional Line Discount %"), fieldtype: "Percent", default: existing.additional_discount || 0 },
                { fieldname: "discount_preview", fieldtype: "HTML" },
                { fieldname: "batch_section", label: __("Batch & Tax"), fieldtype: "Section Break" },
                { fieldname: "batch_no", label: __("Supplier Batch Number"), fieldtype: "Data", default: existing.batch_no || "" },
                { fieldname: "expiry_date", label: __("Expiry Date"), fieldtype: "Data", placeholder: "DD/MM/YYYY", description: __("Example: 31/1/29 becomes 31/01/2029"), default: this.formatDateForInput(existing.expiry_date || "") },
                { fieldname: "item_tax_template", label: __("Item Tax Template"), fieldtype: "Link", options: "Item Tax Template", default: existing.item_tax_template || context.default_item_tax_template || "", get_query: () => ({ filters: { company: this.value("company"), disabled: 0 } }) },
                { fieldname: "column_2", fieldtype: "Column Break" },
                { fieldname: "is_bonus", label: __("This is a Bonus Line"), fieldtype: "Check", default: existing.is_bonus || 0 },
                { fieldname: "auto_batch_reason", label: __("Auto Batch Reason"), fieldtype: "Small Text", default: existing.auto_batch_reason || "" },
                { fieldname: "bonus_section", label: __("Create Separate Bonus Line"), fieldtype: "Section Break", depends_on: "eval:!doc.is_bonus" },
                { fieldname: "bonus_qty", label: __("Bonus Quantity"), fieldtype: "Float", default: 0, depends_on: "eval:!doc.is_bonus" },
                { fieldname: "bonus_batch_no", label: __("Bonus Batch Number"), fieldtype: "Data", depends_on: "eval:!doc.is_bonus" },
                { fieldname: "bonus_expiry_date", label: __("Bonus Expiry Date"), fieldtype: "Data", placeholder: "DD/MM/YYYY", description: __("Example: 31/1/29 becomes 31/01/2029"), depends_on: "eval:!doc.is_bonus" },
            ],
            primary_action_label: editing ? __("Update Line") : __("Add Line"),
            primary_action: (values) => {
                const expiryDate = this.parseFlexibleDate(values.expiry_date);
                const bonusExpiryDate = this.parseFlexibleDate(values.bonus_expiry_date);
                if ((values.expiry_date || "").trim() && !expiryDate) {
                    frappe.msgprint({ title: __("Invalid Expiry Date"), message: __("Enter Expiry Date as DD/MM/YYYY, for example 31/1/29."), indicator: "red" });
                    return;
                }
                if ((values.bonus_expiry_date || "").trim() && !bonusExpiryDate) {
                    frappe.msgprint({ title: __("Invalid Bonus Expiry Date"), message: __("Enter Bonus Expiry Date as DD/MM/YYYY, for example 31/1/29."), indicator: "red" });
                    return;
                }
                values.expiry_date = expiryDate || "";
                values.bonus_expiry_date = bonusExpiryDate || "";
                const row = this.rowFromDialog(values, context);
                if (editing) this.rows[index] = row;
                else this.rows.push(row);

                if (!values.is_bonus && flt(values.bonus_qty) > 0) {
                    this.rows.push({
                        ...row,
                        row_id: this.makeRowId(),
                        qty: flt(values.bonus_qty),
                        is_bonus: 1,
                        supplier_discount: 0,
                        additional_discount: 0,
                        effective_discount: 100,
                        net_rate: 0,
                        amount: 0,
                        batch_no: values.bonus_batch_no || values.batch_no || "",
                        expiry_date: values.bonus_expiry_date || values.expiry_date || "",
                    });
                }
                dialog.hide();
                this.renderRows();
                this.refreshCards();
            },
        });

        dialog.fields_dict.item_snapshot.$wrapper
            .addClass("pimv1-item-snapshot-fixed")
            .html(`
                <div class="pimv1-help" style="display:flex;align-items:center;justify-content:center;text-align:center">
                    <span>${__("Select an item to view stock and purchase history.")}</span>
                </div>
            `);

        const refreshPreview = () => {
            const values = dialog.get_values(true) || {};
            const preview = this.calculateLine(values);
            dialog.fields_dict.discount_preview.$wrapper.html(`
                <div class="pimv1-help" style="margin-top:8px">
                    ${__("Effective Discount")}: <strong>${this.number(preview.effective_discount)}%</strong>
                    &nbsp; | &nbsp; ${__("Net Rate")}: <strong>${this.money(preview.net_rate)}</strong>
                </div>
            `);
        };
        const updateSnapshot = () => {
            const latest = context.latest_supplier_purchase || context.latest_purchase;
            const history = context.purchase_history || [];
            const historyHtml = history.length ? `
                <div class="pimv1-history"><table><thead><tr><th>${__("Date")}</th><th>${__("Supplier")}</th><th>${__("Printed")}</th><th>${__("Net Disc.")}</th><th>${__("Final Net Rate")}</th></tr></thead><tbody>
                ${history.map((row) => `<tr><td>${this.escape(row.posting_date || "")}</td><td>${this.escape(row.supplier_name || row.supplier || "")}</td><td>${this.money(row.printed_retail_price)}</td><td>${this.number(row.net_discount_after_tax)}%</td><td>${this.money(row.final_net_rate)}</td></tr>`).join("")}
                </tbody></table></div>` : "";
            dialog.fields_dict.item_snapshot.$wrapper.html(`
                <div class="pimv1-help">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:8px">
                        <div>
                            <strong>${this.escape(context.item_name || context.item_code || "")}</strong>
                            &nbsp; | &nbsp; ${__("Stock")}: ${this.number(context.actual_qty)} ${this.escape(context.stock_uom || "")}
                            &nbsp; | &nbsp; ${__("Current Printed Price")}: ${this.money(context.custom_customer_price)}
                            &nbsp; | &nbsp; ${__("Last Purchase")}: ${latest ? this.money(latest.rate) : "—"}
                        </div>
                        <button type="button" class="btn btn-sm btn-default pimv1-item-movement-visible">
                            ${__("Sales & Purchase Movement")}
                        </button>
                    </div>
                    ${historyHtml}
                </div>
            `);
            dialog.fields_dict.item_snapshot.$wrapper
                .off("click.pimv1-visible-movement")
                .on("click.pimv1-visible-movement", ".pimv1-item-movement-visible", () => {
                    const itemCode = dialog.get_value("item_code");
                    if (!itemCode) {
                        frappe.show_alert({ message: __("Select an item first."), indicator: "orange" }, 4);
                        return;
                    }
                    this.openItemMovement(itemCode);
                });
        };

        const loadSelectedItem = async () => {
            const itemCode = dialog.get_value("item_code");
            if (!itemCode) return;
            context = await this.fetchItemContext(itemCode, null);
            dialog.set_value("uom", context.purchase_uom || context.stock_uom || "");
            if (!flt(dialog.get_value("printed_retail_price"))) dialog.set_value("printed_retail_price", context.custom_customer_price || 0);
            if (!dialog.get_value("item_tax_template")) dialog.set_value("item_tax_template", context.default_item_tax_template || "");
            updateSnapshot();
            refreshPreview();
        };

        dialog.fields_dict.item_code.df.onchange = loadSelectedItem;
        ["printed_retail_price", "supplier_discount", "additional_discount", "is_bonus"].forEach((fieldname) => {
            dialog.fields_dict[fieldname].df.onchange = refreshPreview;
        });
        // Keep the field for backward compatibility, but the visible movement action is rendered
        // beside stock and last-purchase information in the item snapshot.
        dialog.fields_dict.item_movement.$wrapper.hide();
        dialog.show();
        if (context.item_code || existing.item_code) {
            updateSnapshot();
            refreshPreview();
            if (existing.item_code && !context.purchase_uom && !context.stock_uom) {
                loadSelectedItem();
            }
        }
    }

    async openItemMovement(itemCode) {
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_item_movement",
                args: { item_code: itemCode, warehouse: this.value("warehouse") || "", limit: 150 },
                freeze: true,
                freeze_message: __("Loading item movement..."),
            });
            const data = response.message || {};
            const movements = data.movements || [];
            const operationLabel = (operation) => ({
                "Sale": __("Sale"),
                "Sales Return": __("Sales Return"),
                "Purchase": __("Purchase"),
                "Purchase Return": __("Purchase Return"),
                "Purchase Receipt": __("Purchase Receipt"),
                "Purchase Receipt Return": __("Purchase Receipt Return"),
                "Delivery": __("Delivery"),
                "Delivery Return": __("Delivery Return"),
                "Stock In": __("Stock In"),
                "Stock Out": __("Stock Out"),
            }[operation] || operation || "");
            const rowsHtml = movements.length ? movements.map((row) => `
                <tr>
                    <td>${this.escape(row.posting_date || "")} ${this.escape(String(row.posting_time || "").slice(0, 8))}</td>
                    <td>${this.escape(operationLabel(row.operation))}</td>
                    <td class="text-success">${this.number(row.qty_in)}</td>
                    <td class="text-danger">${this.number(row.qty_out)}</td>
                    <td><strong>${this.number(row.qty_after_transaction)}</strong></td>
                    <td>${this.escape(row.warehouse || "")}</td>
                    <td>${this.escape(row.batch_no || row.serial_and_batch_bundle || "—")}</td>
                    <td>${this.money(row.valuation_rate)}</td>
                    <td><button type="button" class="btn btn-xs btn-default" data-movement-voucher-type="${this.escape(row.voucher_type || "")}" data-movement-voucher-no="${this.escape(row.voucher_no || "")}">${this.escape(row.voucher_no || "—")}</button></td>
                </tr>`).join("") : `<tr><td colspan="9" class="text-muted text-center">${__("No stock movement found.")}</td></tr>`;
            const movementDialog = new frappe.ui.Dialog({
                title: __("Item Movement: {0}", [data.item_name || itemCode]),
                size: "extra-large",
                fields: [{ fieldname: "movement_html", fieldtype: "HTML" }],
            });
            movementDialog.fields_dict.movement_html.$wrapper.html(`
                <div class="pimv1-help" style="margin-bottom:12px">
                    <strong>${this.escape(data.item_name || itemCode)}</strong>
                    &nbsp; | &nbsp; ${__("Warehouse")}: ${this.escape(data.warehouse || __("All Warehouses"))}
                    &nbsp; | &nbsp; ${__("Current Stock")}: <strong>${this.number(data.current_qty)} ${this.escape(data.stock_uom || "")}</strong>
                </div>
                <div class="pimv1-history" style="max-height:55vh;overflow:auto">
                    <table><thead><tr>
                        <th>${__("Date")}</th><th>${__("Movement")}</th><th>${__("In")}</th><th>${__("Out")}</th><th>${__("Balance")}</th><th>${__("Warehouse")}</th><th>${__("Batch")}</th><th>${__("Valuation")}</th><th>${__("Reference")}</th>
                    </tr></thead><tbody>${rowsHtml}</tbody></table>
                </div>
            `);
            movementDialog.$wrapper.off("click.pimv1-voucher").on("click.pimv1-voucher", "[data-movement-voucher-no]", (event) => {
                const $button = $(event.currentTarget);
                const voucherType = $button.data("movement-voucher-type");
                const voucherNo = $button.data("movement-voucher-no");
                if (voucherType && voucherNo) frappe.set_route("Form", voucherType, voucherNo);
            });
            movementDialog.show();
        } catch (error) {
            frappe.msgprint({ title: __("Unable to Load Item Movement"), message: this.escape(error.message || error), indicator: "red" });
        }
    }

    rowFromDialog(values, context) {
        const calculated = this.calculateLine(values);
        return {
            row_id: this.makeRowId(),
            item_code: values.item_code,
            item_name: context.item_name || values.item_code,
            qty: flt(values.qty),
            uom: values.uom || context.purchase_uom || context.stock_uom,
            conversion_factor: flt(context.conversion_factor) || 1,
            printed_retail_price: flt(values.printed_retail_price),
            supplier_discount: flt(values.supplier_discount),
            additional_discount: flt(values.additional_discount),
            effective_discount: calculated.effective_discount,
            net_rate: calculated.net_rate,
            amount: calculated.amount,
            batch_no: values.batch_no || "",
            expiry_date: values.expiry_date || "",
            item_tax_template: values.item_tax_template || "",
            item_tax_rate: this.taxRateForTemplate(values.item_tax_template || context.default_item_tax_template || "") || flt(context.default_item_tax_rate),
            is_bonus: cint(values.is_bonus),
            auto_batch_reason: values.auto_batch_reason || "",
            has_batch_no: cint(context.has_batch_no),
            has_expiry_date: cint(context.has_expiry_date),
        };
    }

    calculateLine(values) {
        const printed = flt(values.printed_retail_price);
        const qty = flt(values.qty);
        if (cint(values.is_bonus)) return { effective_discount: 100, net_rate: 0, amount: 0 };
        const supplierDiscount = Math.max(0, Math.min(100, flt(values.supplier_discount)));
        const additionalDiscount = Math.max(0, Math.min(100, flt(values.additional_discount)));
        const effectiveDiscount = 100 * (1 - (1 - supplierDiscount / 100) * (1 - additionalDiscount / 100));
        const netRate = printed * (1 - effectiveDiscount / 100);
        return { effective_discount: effectiveDiscount, net_rate: netRate, amount: qty * netRate };
    }

    taxRateForTemplate(templateName) {
        const match = (this.bootstrap.item_tax_templates || []).find((row) => row.name === templateName);
        return match ? flt(match.rate) : 0;
    }

    taxTemplateOptions(selected) {
        const options = [`<option value="">${__("No Item Tax")}</option>`];
        (this.bootstrap.item_tax_templates || []).forEach((row) => {
            const isSelected = row.name === selected ? " selected" : "";
            options.push(`<option value="${this.escape(row.name)}"${isSelected}>${this.escape(row.name)} (${this.number(row.rate)}%)</option>`);
        });
        return options.join("");
    }

    recalculateRow(row) {
        const calculated = this.calculateLine(row);
        row.effective_discount = calculated.effective_discount;
        row.net_rate = calculated.net_rate;
        row.amount = calculated.amount;
        row.item_tax_rate = this.taxRateForTemplate(row.item_tax_template);
        return row;
    }

    applyInlineValue($field) {
        const index = Number($field.data("index"));
        const fieldname = $field.data("inline-field");
        const row = this.rows[index];
        if (!row || !fieldname) return false;
        const numericFields = new Set(["qty", "printed_retail_price", "supplier_discount", "additional_discount"]);
        if (fieldname === "expiry_date") {
            const entered = ($field.val() || "").trim();
            const parsed = this.parseFlexibleDate(entered);
            if (entered && !parsed) {
                frappe.show_alert({ message: __("Invalid date. Use DD/MM/YYYY, for example 31/1/29."), indicator: "red" }, 7);
                $field.addClass("has-error").focus();
                return false;
            }
            row.expiry_date = parsed || "";
        } else {
            row[fieldname] = numericFields.has(fieldname) ? flt($field.val()) : $field.val();
        }
        this.recalculateRow(row);
        this.activeRowIndex = index;
        this.renderRows();
        this.refreshCards();
        return true;
    }

    onInlineChange(event) {
        this.applyInlineValue($(event.currentTarget));
    }

    renderRows() {
        const $body = this.$main.find("[data-role='items-body']");
        if (!this.rows.length) {
            this.activeRowIndex = null;
            $body.html(`<div class="pimv1-empty">${__("No purchase items yet. Scan a barcode or add an item.")}</div>`);
            this.renderSummary();
            return;
        }
        if (!Number.isInteger(this.activeRowIndex) || !this.rows[this.activeRowIndex]) this.activeRowIndex = 0;
        const header = `
            <div class="pimv1-items-header">
                <div>${__("No.")}</div>
                <div>${__("Item")}</div>
                <div>${__("Type")}</div>
                <div>${__("Qty / UOM")}</div>
                <div>${__("Printed Price")}</div>
                <div>${__("Supplier Disc.")}</div>
                <div>${__("Additional Disc.")}</div>
                <div>${__("Effective Disc.")}</div>
                <div>${__("Net Rate")}</div>
                <div>${__("Amount")}</div>
                <div>${__("Batch")}</div>
                <div>${__("Expiry")}</div>
                <div>${__("Item Tax Template")}</div>
                <div>${__("Actions")}</div>
            </div>`;
        const rows = this.rows.map((row, index) => `
            <div class="pimv1-item-row ${index === this.activeRowIndex ? "is-active" : ""}" data-row-index="${index}">
                <div class="pimv1-row-grid">
                    <div class="pimv1-row-field"><span class="pimv1-row-number">${index + 1}</span></div>
                    <div class="pimv1-row-field"><div class="pimv1-item-one-line" title="${this.escape(row.item_name || row.item_code)}"><span class="pimv1-item-name">${this.escape(row.item_name || row.item_code)}</span><span class="pimv1-item-code">${this.escape(row.item_code)}</span></div></div>
                    <div class="pimv1-row-field"><span class="pimv1-pill ${row.is_bonus ? "pimv1-pill-bonus" : "pimv1-pill-normal"}">${row.is_bonus ? __("Bonus") : __("Purchase")}</span></div>
                    <div class="pimv1-row-field"><div class="pimv1-qty-wrap"><input class="pimv1-inline-input" type="number" min="0.001" step="0.001" value="${this.number(row.qty)}" data-index="${index}" data-inline-field="qty"><span class="pimv1-uom-inline">${this.escape(row.uom || "")}</span></div></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="number" min="0" step="0.01" value="${this.number(row.printed_retail_price)}" data-index="${index}" data-inline-field="printed_retail_price"></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="number" min="0" max="100" step="0.01" value="${this.number(row.supplier_discount)}" data-index="${index}" data-inline-field="supplier_discount" ${row.is_bonus ? "disabled" : ""}></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="number" min="0" max="100" step="0.01" value="${this.number(row.additional_discount)}" data-index="${index}" data-inline-field="additional_discount" ${row.is_bonus ? "disabled" : ""}></div>
                    <div class="pimv1-row-field"><div class="pimv1-readonly-cell">${this.number(row.effective_discount)}%</div></div>
                    <div class="pimv1-row-field"><div class="pimv1-readonly-cell">${this.money(row.net_rate)}</div></div>
                    <div class="pimv1-row-field"><div class="pimv1-readonly-cell">${this.money(row.amount)}</div></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="text" value="${this.escape(row.batch_no || "")}" placeholder="AUTO" data-index="${index}" data-inline-field="batch_no"></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="text" inputmode="numeric" value="${this.escape(this.formatDateForInput(row.expiry_date || ""))}" placeholder="DD/MM/YYYY" data-index="${index}" data-inline-field="expiry_date"></div>
                    <div class="pimv1-row-field"><select class="pimv1-inline-select" data-index="${index}" data-inline-field="item_tax_template">${this.taxTemplateOptions(row.item_tax_template || "")}</select></div>
                    <div class="pimv1-row-field"><div class="pimv1-row-actions"><button class="pimv1-icon-btn" type="button" title="${__("More")}" aria-label="${__("More")}" data-action="edit-row" data-index="${index}">⋯</button><button class="pimv1-icon-btn pimv1-danger" type="button" title="${__("Delete")}" aria-label="${__("Delete")}" data-action="delete-row" data-index="${index}">×</button></div></div>
                </div>
            </div>
        `).join("");
        $body.html(header + rows);
        this.renderSummary();
    }

    deleteRow(index) {
        if (!this.rows[index]) return;
        frappe.confirm(__("Delete this purchase line?"), () => {
            this.rows.splice(index, 1);
            if (!this.rows.length) this.activeRowIndex = null;
            else this.activeRowIndex = Math.min(index, this.rows.length - 1);
            this.renderRows();
            this.refreshCards();
        });
    }

    totals() {
        const normal = this.rows.filter((row) => !row.is_bonus);
        const bonus = this.rows.filter((row) => row.is_bonus);
        const gross = normal.reduce((sum, row) => sum + flt(row.qty) * flt(row.printed_retail_price), 0);
        const net = normal.reduce((sum, row) => sum + flt(row.amount), 0);
        const lineDiscount = gross - net;
        const bonusValue = bonus.reduce((sum, row) => sum + flt(row.qty) * flt(row.printed_retail_price), 0);
        const invoiceDiscountPct = Math.max(0, Math.min(100, flt(this.value("invoice_discount_percentage"))));
        const invoiceDiscount = net * invoiceDiscountPct / 100;
        const netAfterDiscount = net - invoiceDiscount;
        const invoiceDiscountFactor = 1 - invoiceDiscountPct / 100;
        const taxIncluded = cint(this.value("tax_included_in_print_rate"));
        const estimatedTax = normal.reduce((sum, row) => {
            const taxableAmount = flt(row.amount) * invoiceDiscountFactor;
            const rate = flt(row.item_tax_rate || this.taxRateForTemplate(row.item_tax_template));
            if (!rate) return sum;
            return sum + (taxIncluded ? taxableAmount * rate / (100 + rate) : taxableAmount * rate / 100);
        }, 0);
        const estimatedTaxAdded = taxIncluded ? 0 : estimatedTax;
        const estimatedTaxIncluded = taxIncluded ? estimatedTax : 0;
        const charges = flt(this.value("additional_charge_amount"));
        const estimatedBeforeTax = netAfterDiscount + charges;
        const estimatedGrand = estimatedBeforeTax + estimatedTaxAdded;
        return { gross, net, lineDiscount, bonusValue, invoiceDiscountPct, invoiceDiscount, netAfterDiscount, taxIncluded, estimatedTax, estimatedTaxAdded, estimatedTaxIncluded, charges, estimatedBeforeTax, estimatedGrand };
    }

    renderSummary() {
        const totals = this.totals();
        const savedTax = this.lastSavedTotals ? flt(this.lastSavedTotals.total_taxes_and_charges) : null;
        const invoiceTaxTemplate = this.value("taxes_and_charges");
        this.$main.find("[data-role='summary']").html(`
            <div class="pimv1-summary-row"><span>${__("Printed Retail Gross")}</span><span>${this.money(totals.gross)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Line Discounts")}</span><span>-${this.money(totals.lineDiscount)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Purchase Net Before Invoice Discount")}</span><span>${this.money(totals.net)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Additional Invoice Discount")}</span><span>-${this.money(totals.invoiceDiscount)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Net After Invoice Discount")}</span><span>${this.money(totals.netAfterDiscount)}</span></div>
            <div class="pimv1-summary-row"><span>${totals.taxIncluded ? __("Estimated VAT Included in Purchase Rate") : __("Estimated VAT Added to Invoice")}</span><span>${totals.taxIncluded ? "" : "+"}${this.money(totals.estimatedTax)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Shipping / Additional Charges")}</span><span>+${this.money(totals.charges)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Bonus Retail Value")}</span><span>${this.money(totals.bonusValue)}</span></div>
            ${savedTax !== null ? `<div class="pimv1-summary-row"><span>${__("Actual Taxes and Charges After Save")}</span><span>${this.money(savedTax)}</span></div>` : ""}
            <div class="pimv1-summary-row pimv1-summary-grand"><strong>${__("Estimated Grand Total")}</strong><strong>${this.money(totals.estimatedGrand)}</strong></div>
            <div class="pimv1-tax-note">${invoiceTaxTemplate ? `${__("Invoice tax template")}: ${this.escape(invoiceTaxTemplate)}. ` : ""}${totals.taxIncluded ? __("Tax is included in the entered purchase rate and is not added again to the estimated grand total.") : __("Tax is added above the entered purchase rate.")} ${__("ERPNext is the accounting source of truth after Save Draft.")}</div>
        `);
    }

    refreshCards() {
        const totals = this.totals();
        const balance = this.supplierContext.balance;
        this.$main.find("[data-role='supplier-balance']").text(balance === undefined ? "—" : this.money(Math.abs(balance)));
        this.$main.find("[data-role='supplier-type']").text([
            this.supplierContext.custom_purchase_supplier_type,
            this.supplierContext.custom_purchase_payment_model,
        ].filter(Boolean).join(" • ") || __("Select supplier"));
        this.$main.find("[data-role='items-count']").text(this.rows.length);
        this.$main.find("[data-role='bonus-count']").text(__("Bonus lines: {0}", [this.rows.filter((row) => row.is_bonus).length]));
        this.$main.find("[data-role='estimated-net']").text(this.money(totals.estimatedBeforeTax));
        this.$main.find("[data-role='estimated-tax']").text(this.money(totals.estimatedTax));
        this.$main.find("[data-role='estimated-tax-note']").text(totals.taxIncluded ? __("Included in purchase rate") : __("Added above purchase rate"));
        this.$main.find("[data-role='estimated-grand']").text(this.money(totals.estimatedGrand));
        this.renderSummary();
    }

    validatePage() {
        const errors = [];
        if (!this.value("supplier")) errors.push(__("Supplier is required."));
        if (!this.value("warehouse")) errors.push(__("Receiving Warehouse is required."));
        if (!this.value("bill_no")) errors.push(__("Supplier Invoice Number is required."));
        if (!this.rows.length) errors.push(__("Add at least one purchase item."));
        this.rows.forEach((row, index) => {
            if (!row.item_code || flt(row.qty) <= 0) errors.push(__("Invalid item or quantity on row {0}.", [index + 1]));
            if (!row.is_bonus && flt(row.printed_retail_price) <= 0) errors.push(__("Printed Retail Price is required on row {0}.", [index + 1]));
            if (row.has_expiry_date && !row.expiry_date) errors.push(__("Expiry Date is required on row {0}.", [index + 1]));
        });
        if (errors.length) {
            frappe.msgprint({ title: __("Complete Purchase Invoice"), message: `<ul>${errors.map((error) => `<li>${this.escape(error)}</li>`).join("")}</ul>`, indicator: "orange" });
            return false;
        }
        return true;
    }

    payload() {
        return {
            name: this.draftName,
            company: this.value("company"),
            supplier: this.value("supplier"),
            warehouse: this.value("warehouse"),
            payment_classification: this.value("payment_classification"),
            exclude_from_claim: this.value("payment_classification") === "Cash Invoice" ? 1 : 0,
            posting_date: this.value("posting_date"),
            bill_no: this.value("bill_no"),
            bill_date: this.value("bill_date"),
            due_date: this.value("due_date"),
            taxes_and_charges: this.value("taxes_and_charges"),
            tax_included_in_print_rate: cint(this.value("tax_included_in_print_rate")),
            invoice_discount_percentage: flt(this.value("invoice_discount_percentage")),
            additional_charge_account: this.value("additional_charge_account"),
            additional_charge_amount: flt(this.value("additional_charge_amount")),
            additional_charge_description: __("Shipping / Additional Purchase Charges"),
            attachment: this.attachmentUrl,
            remarks: this.value("remarks"),
            buying_price_list: this.bootstrap.buying_price_list,
            items: this.rows,
        };
    }

    async saveDraft() {
        if (this.isSaving || !this.validatePage()) return;
        this.isSaving = true;
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.save_draft",
                args: { payload: JSON.stringify(this.payload()) },
                freeze: true,
                freeze_message: __("Saving Purchase Invoice Draft..."),
            });
            const message = response.message || {};
            const invoice = message.invoice || {};
            this.draftName = invoice.name;
            this.lastSavedTotals = invoice;
            this.bootstrap.recent_invoices = message.recent_invoices || [];
            this.$main.find("[data-role='draft-badge']").text(invoice.name || __("Saved Draft"));
            this.$main.find("[data-role='saved-grand']").text(`${this.money(invoice.total_taxes_and_charges)} / ${this.money(invoice.grand_total)}`);
            this.$main.find("[data-role='saved-status']").text(`${invoice.status || __("Draft")} • ${__("Tax / Grand")}`);
            this.renderSummary();
            this.$openButton.prop("disabled", false);
            this.renderRecentInvoices(this.bootstrap.recent_invoices);
            frappe.show_alert({ message: __("Purchase Invoice {0} saved as Draft.", [invoice.name]), indicator: "green" }, 7);
        } finally {
            this.isSaving = false;
        }
    }

    openUploader() {
        new frappe.ui.FileUploader({
            allow_multiple: false,
            restrictions: { allowed_file_types: ["image/*", ".pdf"] },
            on_success: (file) => {
                this.attachmentUrl = file.file_url;
                this.$main.find("[data-role='attachment-name']").text(file.file_name || file.file_url);
                frappe.show_alert({ message: __("Supplier invoice attached."), indicator: "green" });
            },
        });
    }

    resetInvoice() {
        const reset = () => {
            this.rows = [];
            this.activeRowIndex = null;
            this.draftName = null;
            this.attachmentUrl = "";
            this.lastSavedTotals = null;
            ["supplier", "bill_no", "payment_classification", "taxes_and_charges", "additional_charge_account", "remarks"].forEach((field) => this.controls[field] && this.controls[field].set_value(""));
            ["invoice_discount_percentage", "additional_charge_amount"].forEach((field) => this.controls[field] && this.controls[field].set_value(0));
            if (this.controls.tax_included_in_print_rate) this.controls.tax_included_in_print_rate.set_value(1);
            const today = this.bootstrap.posting_date || frappe.datetime.get_today();
            this.controls.posting_date.set_value(today);
            this.controls.bill_date.set_value(today);
            this.controls.due_date.set_value(today);
            this.supplierContext = {};
            this.$main.find("[data-role='attachment-name']").text(__("No file attached"));
            this.$main.find("[data-role='draft-badge']").text(__("New Draft"));
            this.$main.find("[data-role='saved-grand']").text("—");
            this.$main.find("[data-role='saved-status']").text(__("Not saved yet"));
            this.$openButton.prop("disabled", true);
            this.renderRows();
            this.refreshCards();
        };
        if (this.rows.length || this.draftName) frappe.confirm(__("Start a new invoice and clear current data?"), reset);
        else reset();
    }

    openOfficialDocument() {
        if (this.draftName) frappe.set_route("Form", "Purchase Invoice", this.draftName);
    }

    toggleRecentPanel(forceOpen = null) {
        this.recentPanelOpen = forceOpen === null ? !this.recentPanelOpen : Boolean(forceOpen);
        this.$main.find("[data-role='recent-panel']").toggleClass("is-open", this.recentPanelOpen);
        this.$main.find("[data-action='toggle-recent']").toggleClass("is-open", this.recentPanelOpen);
    }

    recentValue(fieldname) {
        return this.recentControls[fieldname] ? this.recentControls[fieldname].get_value() : "";
    }

    async searchRecentInvoices() {
        const fromDate = this.recentValue("from_date");
        const toDate = this.recentValue("to_date");
        if (fromDate && toDate && fromDate > toDate) {
            frappe.msgprint({ title: __("Invalid Date Range"), message: __("From Date cannot be after To Date."), indicator: "orange" });
            return;
        }
        const $status = this.$main.find("[data-role='recent-status']");
        $status.text(__("Searching purchase invoices..."));
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.search_purchase_invoices",
                args: {
                    company: this.value("company"),
                    from_date: fromDate || "",
                    to_date: toDate || "",
                    supplier: this.recentValue("supplier") || "",
                    item_code: this.recentValue("item_code") || "",
                    limit: 50,
                },
            });
            const invoices = response.message || [];
            this.renderRecentInvoices(invoices);
            $status.text(__("{0} invoice(s) found.", [invoices.length]));
            this.toggleRecentPanel(true);
        } catch (error) {
            $status.text(__("Could not load invoice results."));
            throw error;
        }
    }

    async clearRecentFilters() {
        await Promise.all(Object.values(this.recentControls).map((control) => control.set_value("")));
        const invoices = this.bootstrap.recent_invoices || [];
        this.renderRecentInvoices(invoices);
        this.$main.find("[data-role='recent-status']").text(__("Latest invoices are shown until filters are applied."));
        this.toggleRecentPanel(true);
    }

    renderRecentInvoices(invoices) {
        const $container = this.$main.find("[data-role='recent-invoices']");
        this.$main.find("[data-role='recent-count']").text((invoices || []).length);
        if (!invoices || !invoices.length) {
            $container.html(`<div class="pimv1-empty">${__("No recent Purchase Invoices.")}</div>`);
            return;
        }
        $container.html(`
            <table class="pimv1-recent"><thead><tr><th>${__("Invoice")}</th><th>${__("Supplier")}</th><th>${__("Supplier Bill")}</th><th>${__("Date")}</th><th>${__("Status")}</th><th>${__("Grand Total")}</th><th>${__("Outstanding")}</th></tr></thead><tbody>
            ${invoices.map((row) => `<tr>
                <td><span class="pimv1-link" data-action="open-invoice" data-name="${this.escape(row.name)}">${this.escape(row.name)}</span></td>
                <td>${this.escape(row.supplier_name || row.supplier || "")}</td>
                <td>${this.escape(row.bill_no || "—")}</td>
                <td>${this.escape(row.posting_date || "")}</td>
                <td>${this.escape(row.status || (row.docstatus === 0 ? __("Draft") : ""))}</td>
                <td>${this.money(row.grand_total)}</td>
                <td>${this.money(row.outstanding_amount)}</td>
            </tr>`).join("")}
            </tbody></table>
        `);
    }

    parseFlexibleDate(value) {
        const raw = String(value || "").trim();
        if (!raw) return "";
        const isoMatch = raw.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
        let year, month, day;
        if (isoMatch) {
            year = Number(isoMatch[1]); month = Number(isoMatch[2]); day = Number(isoMatch[3]);
        } else {
            const match = raw.replace(/[.\-]/g, "/").match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/);
            if (!match) return null;
            day = Number(match[1]); month = Number(match[2]); year = Number(match[3]);
            if (year < 100) year += 2000;
        }
        const date = new Date(Date.UTC(year, month - 1, day));
        if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
        return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    }

    formatDateForInput(value) {
        const iso = this.parseFlexibleDate(value);
        if (!iso) return "";
        const [year, month, day] = iso.split("-");
        return `${day}/${month}/${year}`;
    }

    makeRowId() {
        return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    }

    escape(value) {
        return frappe.utils.escape_html(String(value === null || value === undefined ? "" : value));
    }

    number(value) {
        return format_number(flt(value), null, 2);
    }

    money(value) {
        return `${this.number(value)} ج.م`;
    }
}
