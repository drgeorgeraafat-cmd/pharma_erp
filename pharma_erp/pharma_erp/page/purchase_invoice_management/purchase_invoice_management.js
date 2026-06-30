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
        this.initialRenderComplete = false;
        this.supplierInvoiceTotalManual = false;
        this.supplierInvoiceTotalAutoUpdating = false;
        this.lastAutoSupplierInvoiceTotal = 0;
        this.cameraScanner = null;
        this.cameraScannerDialog = null;
        this.cameraScannerStarting = false;
        this.cameraScanLocked = false;
        this.lastCameraBarcode = "";
        this.lastCameraBarcodeAt = 0;
        this.loadingInvoice = false;

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
        this.$validateButton = this.page.add_inner_button(__("Validate Invoice"), () => this.validateAndReport(), __("Actions"));
        this.$saveSubmitButton = this.page.add_inner_button(__("Save & Submit"), () => this.saveAndSubmit(), __("Invoice"));
        this.$submitButton = this.page.add_inner_button(__("Submit Saved Draft"), () => this.submitInvoice(), __("Invoice"));
        this.$cancelButton = this.page.add_inner_button(__("Cancel"), () => this.cancelInvoice(), __("Invoice"));
        this.$submitButton.prop("disabled", true);
        this.$cancelButton.prop("disabled", true);
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
                .pimv1-hero-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
                .pimv1-lifecycle-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
                .pimv1-lifecycle-actions .btn { min-width: 112px; font-weight: 700; }
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
                    grid-template-columns: 32px 1.45fr .48fr .60fr .68fr .68fr .62fr .62fr .62fr .70fr .70fr .72fr .72fr 1.00fr .62fr;
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
                .pimv1-item-search-box { border:1px solid var(--border-color); border-radius:10px; padding:10px; background:var(--card-bg); }
                .pimv1-item-search-results { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin-top:8px; max-height:260px; overflow:auto; }
                .pimv1-search-card { border:1px solid var(--border-color); border-radius:10px; padding:10px; cursor:pointer; background:var(--control-bg); text-align:right; }
                .pimv1-search-card:hover { border-color:var(--primary); background:var(--blue-50); }
                .pimv1-search-card.is-keyboard-active {
                    border-color: var(--primary);
                    background: var(--blue-50);
                    box-shadow: 0 0 0 2px rgba(59, 130, 246, .18);
                }
                .pimv1-search-card-title { font-weight:800; display:flex; justify-content:space-between; gap:8px; }
                .pimv1-search-card-meta { color:var(--text-muted); font-size:11px; margin-top:4px; }
                .pimv1-risk-badges { display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }
                .pimv1-risk-badge { border-radius:999px; padding:2px 7px; font-size:10px; font-weight:700; }
                .pimv1-risk-warning { background:var(--orange-100); color:var(--orange-700); }
                .pimv1-risk-critical { background:var(--red-100); color:var(--red-700); }
                .pimv1-risk-ok { background:var(--green-100); color:var(--green-700); }
                .pimv1-item-row.status-critical { background:var(--red-50); box-shadow:inset -3px 0 0 var(--red-500); }
                .pimv1-item-row.status-warning { background:var(--orange-50); box-shadow:inset -3px 0 0 var(--orange-500); }
                .pimv1-item-risk-dot { margin-inline-start:4px; }
                .pimv1-camera-button { display:inline-flex; align-items:center; gap:6px; }
                .pimv1-camera-reader {
                    width:100%; min-height:260px; border:1px solid var(--border-color);
                    border-radius:12px; overflow:hidden; background:#111; position:relative;
                }
                .pimv1-camera-reader video { width:100% !important; max-height:62vh; object-fit:cover; }
                .pimv1-camera-status {
                    margin-top:10px; padding:10px 12px; border-radius:9px;
                    background:var(--subtle-fg); color:var(--text-muted); font-size:12px;
                }
                .pimv1-camera-status.is-success { background:var(--green-50); color:var(--green-700); }
                .pimv1-camera-status.is-error { background:var(--red-50); color:var(--red-700); }
                .pimv1-camera-help { margin-top:8px; color:var(--text-muted); font-size:11px; line-height:1.7; }

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
                .pimv1-recent-actions { display:flex; gap:6px; flex-wrap:wrap; min-width:170px; }
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
                    <div class="pimv1-hero-actions">
                        <div class="pimv1-doc-badge" data-role="draft-badge">${__("New Draft")}</div>
                        <div class="pimv1-lifecycle-actions">
                            <button type="button" class="btn btn-default btn-sm" data-action="returns-management">
                                ${__("Returns Management")}
                            </button>
                            <button type="button" class="btn btn-default btn-sm" data-action="page-save-draft">
                                ${__("Save Draft")}
                            </button>
                            <button type="button" class="btn btn-primary btn-sm" data-action="page-save-submit">
                                ${__("Save & Submit")}
                            </button>
                        </div>
                    </div>
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
                        <div class="pimv1-field" data-field="tax_included_in_print_rate" style="display:none"></div>
                        <div class="pimv1-field" data-field="invoice_discount_percentage"></div>
                        <div class="pimv1-field" data-field="additional_charge_account"></div>
                        <div class="pimv1-field" data-field="additional_charge_amount"></div>
                        <div class="pimv1-field" data-field="supplier_invoice_total"></div>
                        <div class="pimv1-field" data-field="fraction_adjustment"></div>
                        <div class="pimv1-field"><label class="control-label">${__("Expected Claim Period")}</label><div class="pimv1-claim-period" data-role="claim-period">—</div></div>
                    </div>
                    <div class="pimv1-validation-panel" data-role="validation-panel"></div>
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
                            <button class="btn btn-default btn-sm pimv1-camera-button" data-action="camera-scan" title="${__("Scan barcode with the mobile camera")}">
                                <span aria-hidden="true">📷</span><span>${__("Camera Scan")}</span>
                            </button>
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
        this.offerLocalDraftRestore();
        this.initialRenderComplete = true;
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
        this.makeControl("bill_date", { label: __("Supplier Invoice Date"), fieldtype: "Date" }, today, () => this.refreshClaimPeriod());
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
        const supplierInvoiceTotalControl = this.makeControl("supplier_invoice_total", {
            label: __("Supplier Invoice Total"),
            fieldtype: "Currency",
            reqd: cint((this.bootstrap.purchase_settings || {}).require_exact_supplier_invoice_total),
            description: __("Filled automatically from the system total. Edit only when the supplier invoice differs by a permitted rounding fraction.")
        }, 0, () => this.refreshCards());
        this.bindSupplierInvoiceTotalManualInput(supplierInvoiceTotalControl);
        this.makeControl("fraction_adjustment", { label: __("Fraction Adjustment"), fieldtype: "Currency", read_only: 1 }, 0);
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
        this.$main.on("click.pimv1", "[data-action='camera-scan']", () => this.openCameraScanner());
        this.$main.on("keypress.pimv1", "[data-role='barcode']", (event) => {
            if (event.which === 13) { event.preventDefault(); this.addByBarcode(); }
        });
        this.$main.on("click.pimv1", "[data-action='attach']", () => this.openUploader());
        this.$main.on("click.pimv1", "[data-action='page-save-draft']", () => this.saveDraft());
        this.$main.on("click.pimv1", "[data-action='page-save-submit']", () => this.saveAndSubmit());
        this.$main.on("click.pimv1", "[data-action='returns-management']", () => frappe.set_route("purchase-returns-management"));
        this.$main.on("click.pimv1", "[data-action='create-purchase-return']", (event) => {
            frappe.route_options = {
                return_type: "Return Against Invoice",
                purchase_invoice: $(event.currentTarget).data("name"),
            };
            frappe.set_route("purchase-returns-management");
        });
        this.$main.on("click.pimv1", "[data-action='edit-row']", (event) => this.openItemDialog(Number($(event.currentTarget).data("index"))));
        this.$main.on("click.pimv1", "[data-action='delete-row']", (event) => this.deleteRow(Number($(event.currentTarget).data("index"))));
        this.$main.on("change.pimv1", "[data-inline-field]", (event) => this.onInlineChange(event));
        this.$main.on("focusin.pimv1 click.pimv1", "[data-row-index]", (event) => {
            this.setActiveRow(Number($(event.currentTarget).data("row-index")));
        });
        this.$main.on("keydown.pimv1", "[data-inline-field]", (event) => {
            const isEnter = event.key === "Enter" && cint(this.shortcutSetting("enter_moves_to_next_row", 1));
            const isArrow = event.key === "ArrowDown" || event.key === "ArrowUp";
            if (!isEnter && !isArrow) return;

            event.preventDefault();
            event.stopPropagation();

            const $field = $(event.currentTarget);
            const index = Number($field.data("index"));
            const fieldname = $field.data("inline-field");
            const applied = this.applyInlineValue($field);
            if (applied === false) return;

            if (isEnter) {
                window.setTimeout(() => this.focusSameFieldInNextRow(index, fieldname), 0);
                return;
            }

            const direction = event.key === "ArrowDown" ? 1 : -1;
            window.setTimeout(() => this.focusSameFieldInAdjacentRow(index, fieldname, direction), 0);
        });
        this.$main.on("click.pimv1", "[data-action='open-invoice']", (event) => frappe.set_route("Form", "Purchase Invoice", $(event.currentTarget).data("name")));
        this.$main.on("click.pimv1", "[data-action='load-draft']", (event) => this.loadDraftInvoice($(event.currentTarget).data("name")));
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

    focusSameFieldInAdjacentRow(index, fieldname, direction) {
        const targetIndex = index + direction;
        if (!this.rows[targetIndex]) return;
        const $target = this.$main.find(`[data-inline-field="${fieldname}"][data-index="${targetIndex}"]`);
        if (!$target.length) return;
        this.setActiveRow(targetIndex);
        $target.trigger("focus").select();
    }

    focusSameFieldInNextRow(index, fieldname) {
        const nextIndex = index + 1;
        if (this.rows[nextIndex]) {
            this.focusSameFieldInAdjacentRow(index, fieldname, 1);
            return;
        }
        this.focusItemSearch();
    }

    value(fieldname) {
        return this.controls[fieldname] ? this.controls[fieldname].get_value() : null;
    }

    async onSupplierChange(options = {}) {
        if (this.loadingInvoice && !options.force) return;
        const supplier = this.value("supplier");
        if (!supplier) {
            this.supplierContext = {};
            if (!options.preserveClassification) this.controls.payment_classification.set_value("");
            this.refreshCards();
            return;
        }
        const response = await frappe.call({
            method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_supplier_context",
            args: { supplier, company: this.value("company") },
        });
        this.supplierContext = response.message || {};
        if (!options.preserveClassification) {
            if (this.supplierContext.default_payment_classification) {
                await this.controls.payment_classification.set_value(this.supplierContext.default_payment_classification);
            } else if (this.supplierContext.custom_purchase_payment_model === "Mixed") {
                await this.controls.payment_classification.set_value("");
            }
        }
        await this.refreshClaimPeriod();
        this.refreshCards();
    }

    refreshSupplierClassification() {
        this.refreshClaimPeriod();
        this.refreshCards();
    }

    async refreshClaimPeriod() {
        const supplier = this.value("supplier");
        const billDate = this.value("bill_date");
        const classification = this.value("payment_classification");
        const $target = this.$main.find("[data-role='claim-period']");
        if (!supplier || !billDate) { $target.text("—"); return; }
        if (classification === "Cash Invoice" || classification === "Credit Invoice Outside Claim") {
            $target.text(__("Excluded from supplier claims"));
            return;
        }
        const response = await frappe.call({
            method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_claim_period",
            args: { supplier, bill_date: billDate },
        });
        const period = response.message || {};
        if (period.period_from && period.period_to) {
            $target.text(`${frappe.datetime.str_to_user(period.period_from)} → ${frappe.datetime.str_to_user(period.period_to)} (${__("Supplier Invoice Date")})`);
        } else {
            $target.text(__("Set claim cycle days on the Supplier."));
        }
    }

    async ensureCameraScannerLibrary() {
        if (window.Html5Qrcode) return;
        await new Promise((resolve, reject) => {
            frappe.require(
                "/assets/pharma_erp/js/vendor/html5-qrcode/html5-qrcode.min.js",
                () => window.Html5Qrcode ? resolve() : reject(new Error(__("Camera scanner library could not be loaded.")))
            );
        });
    }

    cameraErrorMessage(error) {
        const name = String((error && error.name) || "");
        if (!window.isSecureContext || !navigator.mediaDevices) {
            return __("Camera access requires HTTPS. Open the ERP site through a secure HTTPS address on the mobile phone.");
        }
        if (name === "NotAllowedError" || name === "PermissionDeniedError") {
            return __("Camera permission was denied. Allow camera access for this site from the browser settings, then try again.");
        }
        if (name === "NotFoundError" || name === "DevicesNotFoundError") {
            return __("No camera was found on this device.");
        }
        if (name === "NotReadableError" || name === "TrackStartError") {
            return __("The camera is being used by another application or could not be started.");
        }
        return (error && error.message) ? error.message : __("The camera could not be started.");
    }

    setCameraStatus(message, state = "") {
        const dialog = this.cameraScannerDialog;
        if (!dialog) return;
        const $status = dialog.$wrapper.find("[data-role='camera-status']");
        $status.removeClass("is-success is-error");
        if (state === "success") $status.addClass("is-success");
        if (state === "error") $status.addClass("is-error");
        $status.text(message || "");
    }

    async openCameraScanner() {
        if (this.cameraScannerStarting) return;
        this.cameraScannerStarting = true;

        try {
            if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                frappe.msgprint({
                    title: __("Secure Connection Required"),
                    message: __("Mobile camera scanning requires HTTPS. The normal barcode input and USB scanner will continue to work."),
                    indicator: "orange",
                });
                return;
            }

            await this.ensureCameraScannerLibrary();
            await this.stopCameraScanner();

            const readerId = `pimv1-camera-reader-${Date.now()}`;
            const dialog = new frappe.ui.Dialog({
                title: __("Scan Barcode with Camera"),
                size: "large",
                fields: [{ fieldname: "camera_html", fieldtype: "HTML" }],
                primary_action_label: __("Close Camera"),
                primary_action: async () => {
                    await this.stopCameraScanner();
                    dialog.hide();
                },
            });

            this.cameraScannerDialog = dialog;
            dialog.fields_dict.camera_html.$wrapper.html(`
                <div class="pimv1-camera-reader" id="${readerId}"></div>
                <div class="pimv1-camera-status" data-role="camera-status">${__("Starting the rear camera…")}</div>
                <div class="pimv1-camera-help">
                    ${__("Place the product barcode horizontally inside the camera frame. The item will be added automatically after a successful read.")}
                </div>
            `);
            dialog.$wrapper.on("hide.bs.modal.pimv1camera", () => this.stopCameraScanner());
            dialog.show();

            this.cameraScanLocked = false;
            this.lastCameraBarcode = "";
            this.lastCameraBarcodeAt = 0;

            const formats = window.Html5QrcodeSupportedFormats ? [
                Html5QrcodeSupportedFormats.EAN_13,
                Html5QrcodeSupportedFormats.EAN_8,
                Html5QrcodeSupportedFormats.UPC_A,
                Html5QrcodeSupportedFormats.UPC_E,
                Html5QrcodeSupportedFormats.CODE_128,
                Html5QrcodeSupportedFormats.CODE_39,
                Html5QrcodeSupportedFormats.ITF,
                Html5QrcodeSupportedFormats.QR_CODE,
            ].filter((value) => value !== undefined) : undefined;

            this.cameraScanner = new Html5Qrcode(readerId, {
                formatsToSupport: formats,
                verbose: false,
                useBarCodeDetectorIfSupported: true,
            });

            await this.cameraScanner.start(
                { facingMode: "environment" },
                {
                    fps: 12,
                    qrbox: (viewfinderWidth, viewfinderHeight) => ({
                        width: Math.max(220, Math.min(viewfinderWidth - 32, 420)),
                        height: Math.max(90, Math.min(Math.round(viewfinderHeight * 0.28), 160)),
                    }),
                    aspectRatio: 1.777778,
                    disableFlip: true,
                },
                async (decodedText) => this.onCameraBarcodeDetected(decodedText),
                () => {}
            );

            this.setCameraStatus(__("Camera is ready. Point it at the product barcode."));
        } catch (error) {
            console.error("Purchase camera scanner error", error);
            this.setCameraStatus(this.cameraErrorMessage(error), "error");
            frappe.msgprint({
                title: __("Camera Scanner"),
                message: this.escape(this.cameraErrorMessage(error)),
                indicator: "red",
            });
        } finally {
            this.cameraScannerStarting = false;
        }
    }

    async onCameraBarcodeDetected(decodedText) {
        const barcode = String(decodedText || "").trim();
        if (!barcode || this.cameraScanLocked) return;

        const now = Date.now();
        if (barcode === this.lastCameraBarcode && now - this.lastCameraBarcodeAt < 1800) return;
        this.lastCameraBarcode = barcode;
        this.lastCameraBarcodeAt = now;
        this.cameraScanLocked = true;
        this.setCameraStatus(__("Barcode detected: {0}", [barcode]), "success");

        try {
            const added = await this.addByBarcode(barcode, { fromCamera: true });
            if (added) {
                if (navigator.vibrate) navigator.vibrate(120);
                this.playCameraScanBeep();
                await this.stopCameraScanner();
                if (this.cameraScannerDialog) this.cameraScannerDialog.hide();
            } else {
                this.setCameraStatus(__("Barcode {0} is not linked to an item. Try another barcode or use item search.", [barcode]), "error");
                window.setTimeout(() => { this.cameraScanLocked = false; }, 1600);
            }
        } catch (error) {
            this.setCameraStatus(this.cameraErrorMessage(error), "error");
            window.setTimeout(() => { this.cameraScanLocked = false; }, 1600);
        }
    }

    playCameraScanBeep() {
        try {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (!AudioContextClass) return;
            const context = new AudioContextClass();
            const oscillator = context.createOscillator();
            const gain = context.createGain();
            oscillator.type = "sine";
            oscillator.frequency.value = 920;
            gain.gain.setValueAtTime(0.06, context.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.12);
            oscillator.connect(gain);
            gain.connect(context.destination);
            oscillator.start();
            oscillator.stop(context.currentTime + 0.12);
            oscillator.onended = () => context.close();
        } catch (error) {
            // Audio feedback is optional.
        }
    }

    async stopCameraScanner() {
        const scanner = this.cameraScanner;
        this.cameraScanner = null;
        this.cameraScanLocked = false;
        if (!scanner) return;
        try {
            if (scanner.isScanning) await scanner.stop();
        } catch (error) {
            console.warn("Could not stop camera scanner", error);
        }
        try {
            await scanner.clear();
        } catch (error) {
            // The reader element may already be removed when the dialog closes.
        }
    }

    async addByBarcode(barcodeValue = null, options = {}) {
        const input = this.$main.find("[data-role='barcode']");
        const suppliedValue = typeof barcodeValue === "string" ? barcodeValue : "";
        const searchValue = (suppliedValue || input.val() || "").trim();
        if (!searchValue) return false;
        try {
            const context = await this.fetchItemContext(null, searchValue);
            const row = this.rowFromItemContext(context);
            const index = this.addOrMergeRow(row);
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
            return true;
        } catch (error) {
            if (!options.fromCamera) {
                frappe.msgprint({ title: __("Item Not Found"), message: this.escape(error.message || error), indicator: "red" });
            }
            return false;
        }
    }

    rowFromItemContext(context) {
        const latest=context.latest_supplier_purchase || context.latest_purchase || {};
        const customerPrice=flt(context.custom_customer_price || latest.printed_retail_price || 0);
        const taxRate=flt(context.default_item_tax_rate);
        const taxMode=taxRate ? ((this.bootstrap.purchase_settings||{}).default_tax_entry_mode || "Auto by VAT %") : "No VAT";
        const risk=this.evaluateRisk(context.risk || {},1,flt(context.conversion_factor)||1,"");
        return this.rowFromDialog({
            item_code:context.item_code,qty:1,uom:context.purchase_uom||context.stock_uom||"",customer_price:customerPrice,
            supplier_base_price:flt(latest.supplier_base_price || customerPrice),
            pricing_method:(this.bootstrap.purchase_settings||{}).default_pricing_method || "Discount From Customer Price",
            supplier_discount:flt(latest.supplier_discount||0),additional_discount:flt(latest.additional_discount||0),
            tax_entry_mode:taxMode,vat_inclusive:1,vat_rate:taxRate,net_before_vat:0,vat_per_unit:0,total_vat:0,net_rate:0,
            batch_no:"",expiry_date:"",item_tax_template:context.default_item_tax_template||"",is_bonus:0,auto_batch_reason:"",
            risk_level:risk.level,risk_flags:risk.flags,risk_confirmed:0,risk_confirmation_reason:"",
        },context);
    }

    addOrMergeRow(row) {
        const canMerge = cint((this.bootstrap.purchase_settings || {}).auto_merge_same_item_batch)
            && row.batch_no
            && row.expiry_date;
        if (canMerge) {
            const existingIndex = this.rows.findIndex((candidate) =>
                candidate.item_code === row.item_code
                && cint(candidate.is_bonus) === cint(row.is_bonus)
                && (candidate.batch_no || "") === (row.batch_no || "")
                && (candidate.expiry_date || "") === (row.expiry_date || "")
                && (candidate.item_tax_template || "") === (row.item_tax_template || "")
                && Math.abs(flt(candidate.net_rate) - flt(row.net_rate)) < 0.0001
            );
            if (existingIndex >= 0) {
                this.rows[existingIndex].qty = flt(this.rows[existingIndex].qty) + flt(row.qty);
                this.recalculateRow(this.rows[existingIndex]);
                return existingIndex;
            }
        }
        this.rows.push(row);
        return this.rows.length - 1;
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

    mergeRisks(...risks) {
        const rank={None:0,Warning:1,Critical:2};
        const flags=[]; const messages=[]; let level="None";
        risks.filter(Boolean).forEach((risk)=>{
            (risk.flags||[]).forEach((flag)=>{if(!flags.includes(flag))flags.push(flag)});
            (risk.messages||[]).forEach((message)=>{if(!messages.includes(message))messages.push(message)});
            if((rank[risk.level]||0)>(rank[level]||0))level=risk.level;
        });
        if(flags.length>=2 && level==="Warning")level="Critical";
        return {level,flags,messages};
    }

    expiryRisk(expiryDate) {
        const expiryIso=this.parseFlexibleDate(expiryDate);
        if(!expiryIso)return {level:"None",flags:[],messages:[]};
        const postingIso=this.parseFlexibleDate(this.value("posting_date")) || frappe.datetime.get_today();
        const expiry=new Date(`${expiryIso}T00:00:00Z`);
        const posting=new Date(`${postingIso}T00:00:00Z`);
        if(Number.isNaN(expiry.getTime())||Number.isNaN(posting.getTime()))return {level:"None",flags:[],messages:[]};
        const daysRemaining=Math.ceil((expiry-posting)/86400000);
        if(daysRemaining<0){
            return {level:"Critical",flags:["EXPIRED_ITEM"],messages:[__("Expired item: expiry date {0} is before the receipt date.",[this.formatDateForInput(expiryIso)])],days_remaining:daysRemaining};
        }
        const warningMonths=Math.max(1,cint((this.bootstrap.purchase_settings||{}).near_expiry_warning_months||6));
        const threshold=new Date(posting.getTime());
        threshold.setUTCMonth(threshold.getUTCMonth()+warningMonths);
        if(expiry<=threshold){
            return {level:"Warning",flags:["NEAR_EXPIRY"],messages:[__("Near expiry: {0} — {1} days remaining.",[this.formatDateForInput(expiryIso),daysRemaining])],days_remaining:daysRemaining};
        }
        return {level:"None",flags:[],messages:[],days_remaining:daysRemaining};
    }

    evaluateRisk(metrics, qty, conversionFactor=1, expiryDate="") {
        const settings=this.bootstrap.purchase_settings||{};
        const expiryRisk=this.expiryRisk(expiryDate);
        if (!cint(settings.enable_purchase_risk_alerts)) return expiryRisk;
        const projected=flt(metrics.current_qty)+flt(qty)*(flt(conversionFactor)||1);
        const avg=flt(metrics.avg_daily_sales); const coverage=avg>0?projected/avg:null;
        const flags=[]; const messages=[];
        if (Array.isArray(metrics.flags)) { metrics.flags.forEach((f)=>{if(!flags.includes(f)) flags.push(f);}); }
        if (Array.isArray(metrics.messages)) metrics.messages.forEach((m)=>messages.push(m));
        const minQty=flt(settings.minimum_stock_qty_for_warning||0); const maxCoverage=cint(settings.high_stock_coverage_days||90);
        if (projected>=minQty && (avg<=0 || (coverage!==null && coverage>=maxCoverage)) && !flags.includes("HIGH_STOCK_SLOW_MOVEMENT")) {
            flags.push("HIGH_STOCK_SLOW_MOVEMENT"); messages.push(__("Projected stock {0}; slow movement / high stock coverage.",[this.number(projected)]));
        }
        const movementLevel=flags.includes("DORMANT_ITEM")||flags.length>=2?"Critical":(flags.length?"Warning":"None");
        const merged=this.mergeRisks({level:movementLevel,flags,messages},expiryRisk);
        return {...merged,projected_qty:projected,coverage_days:coverage,days_remaining:expiryRisk.days_remaining};
    }

    riskHtml(risk) {
        if (!risk || risk.level==="None") return `<div class="pimv1-risk-badges"><span class="pimv1-risk-badge pimv1-risk-ok">✓ ${__("Normal movement")}</span></div>`;
        const cls=risk.level==="Critical"?"pimv1-risk-critical":"pimv1-risk-warning";
        return `<div class="pimv1-risk-badges">${(risk.messages||[]).map(m=>`<span class="pimv1-risk-badge ${cls}">${this.escape(m)}</span>`).join("")}</div>`;
    }

    async searchItemCards(dialog, text, selectItem) {
        const $results=dialog.fields_dict.item_search_ui.$wrapper.find("[data-role='item-search-results']");
        const query=(text||"").trim();
        if (!query) {
            $results.removeData("active-index").html(`<div class="text-muted">${__("Type item name, Arabic name, code or barcode.")}</div>`);
            return;
        }
        $results.removeData("active-index").html(`<div class="text-muted">${__("Searching...")}</div>`);
        const response=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.search_purchase_item_cards",
            args:{
                search_text:query,
                warehouse:this.value("warehouse"),
                supplier:this.value("supplier"),
                limit:cint((this.bootstrap.purchase_settings||{}).item_search_result_limit||10)
            }
        });
        const rows=response.message||[];
        $results.html(rows.length?rows.map((row,index)=>{
            const risk=row.risk||{};
            const cls=risk.level==="Critical"?"pimv1-risk-critical":(risk.level==="Warning"?"pimv1-risk-warning":"pimv1-risk-ok");
            return `<button type="button"
                class="pimv1-search-card ${index===0?"is-keyboard-active":""}"
                data-search-index="${index}"
                data-item-code="${this.escape(row.item_code)}">
                <div class="pimv1-search-card-title">
                    <span>${this.escape(row.item_name||row.item_code)}</span>
                    <span>${this.escape(row.item_code)}</span>
                </div>
                <div class="pimv1-search-card-meta">
                    ${__("Stock")}: <strong>${this.number(row.actual_qty)} ${this.escape(row.stock_uom||"")}</strong>
                    • ${__("Customer Price")}: ${this.money(row.customer_price)}
                    • ${__("Last Purchase")}: ${row.last_purchase_rate?this.money(row.last_purchase_rate):"—"}
                </div>
                <div class="pimv1-risk-badges">
                    <span class="pimv1-risk-badge ${cls}">
                        ${risk.level==="None"?"✓ "+__("Normal movement"):(risk.messages||[]).slice(0,2).map(x=>this.escape(x)).join(" • ")}
                    </span>
                </div>
            </button>`;
        }).join(""):`<div class="text-muted">${__("No matching items.")}</div>`);

        if (rows.length) $results.data("active-index",0);

        $results.off("click.pimv1-card").on("click.pimv1-card","[data-item-code]",(e)=>{
            const $card=$(e.currentTarget);
            $results.find(".pimv1-search-card").removeClass("is-keyboard-active");
            $card.addClass("is-keyboard-active");
            $results.data("active-index",Number($card.data("search-index"))||0);
            selectItem($card.data("item-code"));
        });
    }

    focusOpenItemDialogSearch(dialog = null, immediate = false) {
        const activeDialog = dialog || this.activeItemDialog;
        if (!activeDialog || !activeDialog.$wrapper || !activeDialog.fields_dict.item_search_ui) return;

        const $input = activeDialog.fields_dict.item_search_ui.$wrapper.find("[data-role='item-card-search']");
        if (!$input.length) return;

        const input = $input.get(0);
        const $modal = activeDialog.$wrapper.is(".modal")
            ? activeDialog.$wrapper
            : activeDialog.$wrapper.find(".modal").first();

        let userTyped = false;
        let userMovedElsewhere = false;
        let finalFocusApplied = false;

        $input.off("input.pimv1-focus-state").on("input.pimv1-focus-state", () => {
            userTyped = true;
        });

        activeDialog.$wrapper
            .off("pointerdown.pimv1-focus-cancel")
            .on("pointerdown.pimv1-focus-cancel", (event) => {
                if (event.target !== input && !$(event.target).closest("[data-role='item-card-search']").length) {
                    userMovedElsewhere = true;
                }
            });

        const applyFocus = ({ final = false } = {}) => {
            if (!activeDialog.$wrapper.is(":visible") || userMovedElsewhere) return;
            if (final && finalFocusApplied) return;

            try {
                input.focus({ preventScroll: true });
            } catch (_error) {
                $input.trigger("focus");
            }

            if (userTyped) {
                const end = String(input.value || "").length;
                if (typeof input.setSelectionRange === "function") {
                    input.setSelectionRange(end, end);
                }
            } else if (typeof input.select === "function") {
                input.select();
            }

            if (final) finalFocusApplied = true;
        };

        if (immediate) {
            applyFocus({ final: true });
            return;
        }

        // Give immediate visual feedback, then focus once more only after Bootstrap/Frappe
        // has completed the modal transition and its own first-field autofocus.
        window.requestAnimationFrame(() => applyFocus());

        const finalAfterShown = () => {
            window.requestAnimationFrame(() => {
                window.setTimeout(() => applyFocus({ final: true }), 0);
            });
        };

        ($modal.length ? $modal : activeDialog.$wrapper)
            .off("shown.bs.modal.pimv1-final-search-focus")
            .one("shown.bs.modal.pimv1-final-search-focus", finalAfterShown);

        // Fallback for themes/builds where shown.bs.modal is not emitted on the expected node.
        window.setTimeout(() => applyFocus({ final: true }), 650);
    }

    openItemDialog(index = null, initialContext = null) {
        if (!Number.isInteger(index) && !initialContext && this.activeItemDialog && this.activeItemDialog.$wrapper && this.activeItemDialog.$wrapper.is(":visible")) {
            this.focusOpenItemDialogSearch(this.activeItemDialog, true);
            return;
        }
        const editing=Number.isInteger(index)&&this.rows[index];
        const existing=editing?this.rows[index]:{};
        let context=initialContext||(editing?existing:{}), searchTimer=null, updating=false, pricingMethodTouched=!!editing, supplierPriceTouched=!!editing;
        const dialog=new frappe.ui.Dialog({title:editing?__("Edit Purchase Line"):__("Add Purchase Item"),size:"extra-large",fields:[
            {fieldname:"item_search_ui",fieldtype:"HTML"},{fieldname:"item_code",fieldtype:"Data",hidden:1,default:existing.item_code||context.item_code||""},
            {fieldname:"item_snapshot",fieldtype:"HTML"},{fieldname:"qty",label:__("Quantity"),fieldtype:"Float",reqd:1,default:existing.qty||1},
            {fieldname:"uom",fieldtype:"Data",hidden:1,default:existing.uom||context.purchase_uom||context.stock_uom||""},{fieldname:"column_1",fieldtype:"Column Break"},
            {fieldname:"customer_price",label:__("Customer Price"),fieldtype:"Currency",reqd:1,default:existing.customer_price||context.custom_customer_price||0},
            {fieldname:"pricing_method",label:__("Purchase Pricing Method"),fieldtype:"Select",options:"Discount From Customer Price\nDiscount From Supplier Base Price\nDirect Net Before VAT\nDirect Final Net Rate",default:existing.pricing_method||(this.bootstrap.purchase_settings||{}).default_pricing_method||"Discount From Customer Price"},
            {fieldname:"supplier_base_price",label:__("Supplier Invoice Price"),fieldtype:"Currency",default:existing.supplier_base_price||0},
            {fieldname:"supplier_discount",label:__("Supplier / Base Discount %"),fieldtype:"Percent",default:existing.supplier_discount||0},
            {fieldname:"additional_discount",label:__("Additional Line Discount %"),fieldtype:"Percent",default:existing.additional_discount||0},
            {fieldname:"tax_section",label:__("VAT & Final Cost"),fieldtype:"Section Break"},
            {fieldname:"item_tax_template",label:__("Item Tax Template"),fieldtype:"Link",options:"Item Tax Template",default:existing.item_tax_template||context.default_item_tax_template||"",get_query:()=>({filters:{company:this.value("company"),disabled:0}})},
            {fieldname:"tax_entry_mode",label:__("VAT Entry Mode"),fieldtype:"Select",options:"No VAT\nAuto by VAT %\nVAT Per Unit\nTotal VAT for Line",default:existing.tax_entry_mode||((this.bootstrap.purchase_settings||{}).default_tax_entry_mode)||"Auto by VAT %"},
            {fieldname:"vat_inclusive",label:__("VAT Included in Final Net Rate"),fieldtype:"Check",default:existing.vat_inclusive === undefined ? 1 : cint(existing.vat_inclusive),description:__("Enabled: entered VAT is already inside the discounted item total. Disabled: VAT is added above the discounted item total.")},
            {fieldname:"vat_rate",label:__("VAT Rate %"),fieldtype:"Percent",default:existing.vat_rate||context.default_item_tax_rate||0},
            {fieldname:"net_before_vat",label:__("Net Before VAT"),fieldtype:"Currency",default:existing.entered_net_before_vat||existing.net_before_vat||0,description:__("When Direct Net Before VAT is selected, this is the supplier net before the separate Additional Discount.")},
            {fieldname:"tax_column",fieldtype:"Column Break"},{fieldname:"vat_per_unit",label:__("VAT Per Unit"),fieldtype:"Currency",default:existing.vat_per_unit||0},
            {fieldname:"total_vat",label:__("Total VAT for Line"),fieldtype:"Currency",default:existing.total_vat||0},
            {fieldname:"net_rate",label:__("Final Net Rate"),fieldtype:"Currency",reqd:1,default:existing.net_rate||0},{fieldname:"discount_preview",fieldtype:"HTML"},
            {fieldname:"batch_section",label:__("Batch & Expiry"),fieldtype:"Section Break"},{fieldname:"batch_no",label:__("Supplier Batch Number"),fieldtype:"Data",default:existing.batch_no||""},
            {fieldname:"expiry_date",label:__("Expiry Date"),fieldtype:"Data",placeholder:"DD/MM/YYYY",default:this.formatDateForInput(existing.expiry_date||"")},
            {fieldname:"batch_column",fieldtype:"Column Break"},{fieldname:"is_bonus",label:__("This is a Bonus Line"),fieldtype:"Check",default:existing.is_bonus||0},
            {fieldname:"auto_batch_reason",label:__("Auto Batch Reason"),fieldtype:"Small Text",default:existing.auto_batch_reason||""},
            {fieldname:"risk_section",label:__("Purchase Risk Review"),fieldtype:"Section Break"},{fieldname:"risk_snapshot",fieldtype:"HTML"},
            {fieldname:"risk_confirmed",label:__("Confirm Item and Quantity"),fieldtype:"Check",default:existing.risk_confirmed||0},
            {fieldname:"risk_confirmation_reason",label:__("Confirmation Reason"),fieldtype:"Select",options:"\nRequested by Pharmacy\nCustomer Special Order\nApproved Promotion\nIntentional Stock Increase\nReplacement / Correction\nOther",default:existing.risk_confirmation_reason||""},
            {fieldname:"bonus_section",label:__("Create Separate Bonus Line"),fieldtype:"Section Break",depends_on:"eval:!doc.is_bonus"},
            {fieldname:"bonus_qty",label:__("Bonus Quantity"),fieldtype:"Float",default:0,depends_on:"eval:!doc.is_bonus"},{fieldname:"bonus_batch_no",label:__("Bonus Batch Number"),fieldtype:"Data",depends_on:"eval:!doc.is_bonus"},
            {fieldname:"bonus_expiry_date",label:__("Bonus Expiry Date"),fieldtype:"Data",placeholder:"DD/MM/YYYY",depends_on:"eval:!doc.is_bonus"},
        ],primary_action_label:editing?__("Update Line"):__("Add Line"),primary_action:(values)=>{
            if (!values.item_code) { frappe.show_alert({message:__("Select an item."),indicator:"red"},4); return; }
            const expiry=this.parseFlexibleDate(values.expiry_date), bonusExpiry=this.parseFlexibleDate(values.bonus_expiry_date);
            if ((values.expiry_date||"").trim()&&!expiry) { frappe.msgprint(__("Invalid Expiry Date.")); return; }
            values.expiry_date=expiry||""; values.bonus_expiry_date=bonusExpiry||"";
            const risk=this.evaluateRisk(context.risk||{},values.qty,context.conversion_factor||1,values.expiry_date);
            if (risk.level!=="None"&&cint((this.bootstrap.purchase_settings||{}).require_risk_confirmation)&&(!cint(values.risk_confirmed)||!values.risk_confirmation_reason)) { frappe.msgprint({title:__("Confirm Risk Item"),message:__("Confirm the item and quantity and select a reason."),indicator:"orange"}); return; }
            values.vat_inclusive=cint(dialog.get_value("vat_inclusive"));
            values.tax_entry_mode=dialog.get_value("tax_entry_mode")||"No VAT";
            values.vat_per_unit=flt(dialog.get_value("vat_per_unit"));
            values.total_vat=flt(dialog.get_value("total_vat"));
            const row=this.rowFromDialog(values,context); if(editing)this.rows[index]=row;else this.addOrMergeRow(row);
            if(!values.is_bonus&&flt(values.bonus_qty)>0){
                const bonusDraft={
                    ...row,
                    row_id:this.makeRowId(),
                    qty:flt(values.bonus_qty),
                    is_bonus:1,
                    // The taxable basis of an automatic bonus follows the purchased unit's
                    // net value before VAT. The item itself remains free; only VAT is payable.
                    supplier_base_price:flt(row.net_before_vat)||flt(row.supplier_base_price)||flt(row.customer_base_before_vat),
                    supplier_discount:100,
                    additional_discount:0,
                    net_before_vat:0,
                    batch_no:values.bonus_batch_no||values.batch_no||"",
                    expiry_date:values.bonus_expiry_date||values.expiry_date||"",
                    risk_level:"None",
                    risk_flags:[],
                    risk_confirmed:1
                };
                const bonusCalc=this.calculateLine(bonusDraft);
                Object.assign(bonusDraft,{
                    effective_discount:bonusCalc.effective_discount,
                    customer_base_before_vat:bonusCalc.customer_base_before_vat,
                    supplier_base_price:bonusCalc.supplier_base_price,
                    vat_rate:bonusCalc.vat_rate,
                    vat_per_unit:bonusCalc.vat_per_unit,
                    total_vat:bonusCalc.total_vat,
                    net_rate:bonusCalc.net_rate,
                    amount:bonusCalc.amount
                });
                this.addOrMergeRow(bonusDraft);
            }
            dialog.hide();this.renderRows();this.refreshCards();
        }});
        dialog.fields_dict.item_search_ui.$wrapper.html(`<div class="pimv1-item-search-box"><input class="form-control" data-role="item-card-search" placeholder="${__("Search English / Arabic name, code or barcode")}"><div class="pimv1-item-search-results" data-role="item-search-results"><div class="text-muted">${__("Start typing to search items.")}</div></div></div>`);
        const setIf=async(name,val)=>{if(String(dialog.get_value(name)||"")!==String(val??""))await dialog.set_value(name,val)};
        const refresh=async()=>{if(updating)return;updating=true;try{const v=dialog.get_values(true)||{};v.vat_inclusive=cint(dialog.get_value("vat_inclusive"));v.tax_entry_mode=dialog.get_value("tax_entry_mode")||"No VAT";v.vat_per_unit=flt(dialog.get_value("vat_per_unit"));v.total_vat=flt(dialog.get_value("total_vat"));if((v.pricing_method||"")==="Direct Net Before VAT")v.entered_net_before_vat=flt(dialog.get_value("net_before_vat"));const c=this.calculateLine(v);await setIf("supplier_discount",c.supplier_discount);if(!supplierPriceTouched)await setIf("supplier_base_price",c.supplier_base_price);await setIf("vat_rate",c.vat_rate);if((v.pricing_method||"")!=="Direct Net Before VAT")await setIf("net_before_vat",c.net_before_vat);await setIf("vat_per_unit",c.vat_per_unit);await setIf("total_vat",c.total_vat);await setIf("net_rate",c.net_rate);const directBreakdown=(v.pricing_method||"")==="Direct Net Before VAT"?` • ${__("Net Before VAT After Additional Disc.")}: <strong>${this.money(c.net_before_vat)}</strong>`:"";dialog.fields_dict.discount_preview.$wrapper.html(`<div class="pimv1-help">${__("Net Disc.")}: <strong>${this.number(c.effective_discount)}%</strong>${directBreakdown} • ${__("Final Net Rate")}: <strong>${this.money(c.net_rate)}</strong> • ${__("Line Total")}: <strong>${this.money(c.amount)}</strong></div>`);const risk=this.evaluateRisk(context.risk||{},v.qty,context.conversion_factor||1,v.expiry_date);dialog.fields_dict.risk_snapshot.$wrapper.html(this.riskHtml(risk));}finally{updating=false}};
        const snapshot=()=>{const latest=context.latest_supplier_purchase||context.latest_purchase;const history=context.purchase_history||[];dialog.fields_dict.item_snapshot.$wrapper.addClass("pimv1-item-snapshot-fixed").html(`<div class="pimv1-help"><div><strong>${this.escape(context.item_name||context.item_code||"")}</strong> • ${__("Stock")}: ${this.number(context.actual_qty)} ${this.escape(context.stock_uom||"")} • ${__("Customer Price")}: ${this.money(context.custom_customer_price)} • ${__("Last Purchase")}: ${latest?this.money(latest.final_net_rate||latest.rate):"—"} <button type="button" class="btn btn-xs btn-default pimv1-move">${__("Sales & Purchase Movement")}</button></div>${history.length?`<div class="pimv1-history"><table><thead><tr><th>${__("Date")}</th><th>${__("Supplier")}</th><th>${__("Printed")}</th><th>${__("Net Disc.")}</th><th>${__("Final Net Rate")}</th></tr></thead><tbody>${history.map(r=>`<tr><td>${this.escape(r.posting_date||"")}</td><td>${this.escape(r.supplier_name||r.supplier||"")}</td><td>${this.money(r.printed_retail_price)}</td><td>${this.number(r.net_discount_after_tax)}%</td><td>${this.money(r.final_net_rate)}</td></tr>`).join("")}</tbody></table></div>`:""}</div>`);dialog.fields_dict.item_snapshot.$wrapper.off("click.pimv1-move").on("click.pimv1-move",".pimv1-move",()=>this.openItemMovement(context.item_code));};
        const applyTaxTemplate = async () => {
            if (updating) return;
            updating = true;
            try {
                const template = dialog.get_value("item_tax_template") || "";
                const rate = template ? this.taxRateForTemplate(template) : 0;
                await setIf("tax_entry_mode", template ? "Auto by VAT %" : "No VAT");
                await setIf("vat_rate", rate);
                if (template && !pricingMethodTouched) {
                    await setIf("pricing_method", "Discount From Customer Price");
                }
                const customerPrice = flt(dialog.get_value("customer_price"));
                if (!supplierPriceTouched && (dialog.get_value("pricing_method") || "") === "Discount From Customer Price") {
                    await setIf("supplier_base_price", customerPrice);
                }
            } finally {
                updating = false;
            }
            await refresh();
        };
        const selectItem=async(code)=>{
            context=await this.fetchItemContext(code,null);
            updating=true;
            try {
                await setIf("item_code",code);
                await setIf("uom",context.purchase_uom||context.stock_uom||"");
                if(!editing){
                    const customerPrice=flt(context.custom_customer_price||0);
                    const template=context.default_item_tax_template||"";
                    const rate=flt(context.default_item_tax_rate||0);
                    await setIf("customer_price",customerPrice);
                    await setIf("item_tax_template",template);
                    await setIf("tax_entry_mode",template?"Auto by VAT %":"No VAT");
                    await setIf("vat_rate",rate);
                    // Pharmacy printed/customer prices are VAT-inclusive; use them as the default discount basis.
                    await setIf("pricing_method","Discount From Customer Price");
                    await setIf("supplier_base_price",customerPrice);
                    await setIf("vat_inclusive",1);
                    supplierPriceTouched=false;
                }
            } finally {
                updating=false;
            }
            snapshot();
            await refresh();
            dialog.fields_dict.item_search_ui.$wrapper.find("[data-role='item-card-search']").val(context.item_name||code);
        };
        const $search=dialog.fields_dict.item_search_ui.$wrapper.find("[data-role='item-card-search']");
        $search.on("input",()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>this.searchItemCards(dialog,$search.val(),selectItem),300)});

        let keyboardAdding=false;
        const activeSearchCard=()=>{
            const $results=dialog.fields_dict.item_search_ui.$wrapper.find("[data-role='item-search-results']");
            let $cards=$results.find(".pimv1-search-card");
            if(!$cards.length)return $();
            let index=Number($results.data("active-index"));
            if(!Number.isInteger(index)||index<0||index>=$cards.length)index=0;
            $cards.removeClass("is-keyboard-active");
            const $active=$cards.eq(index).addClass("is-keyboard-active");
            $results.data("active-index",index);
            return $active;
        };
        const moveSearchSelection=(direction)=>{
            const $results=dialog.fields_dict.item_search_ui.$wrapper.find("[data-role='item-search-results']");
            const $cards=$results.find(".pimv1-search-card");
            if(!$cards.length)return;
            let index=Number($results.data("active-index"));
            if(!Number.isInteger(index))index=0;
            index=(index+direction+$cards.length)%$cards.length;
            $results.data("active-index",index);
            $cards.removeClass("is-keyboard-active");
            const element=$cards.eq(index).addClass("is-keyboard-active").get(0);
            if(element)element.scrollIntoView({block:"nearest"});
        };
        const addActiveSearchResult=async()=>{
            if(keyboardAdding)return;
            const $active=activeSearchCard();
            if(!$active.length)return;
            const code=$active.data("item-code");
            if(!code)return;
            keyboardAdding=true;
            try{
                await selectItem(code);
                // Enter from the result list is a true keyboard quick-add.
                // The normal primary action still performs all validation and risk checks.
                dialog.get_primary_btn().trigger("click");
            }finally{
                keyboardAdding=false;
            }
        };
        $search.off("keydown.pimv1-search-nav").on("keydown.pimv1-search-nav",async(event)=>{
            if(event.key==="ArrowDown"){
                event.preventDefault();event.stopImmediatePropagation();moveSearchSelection(1);return;
            }
            if(event.key==="ArrowUp"){
                event.preventDefault();event.stopImmediatePropagation();moveSearchSelection(-1);return;
            }
            if(event.key==="Enter"){
                event.preventDefault();event.stopImmediatePropagation();await addActiveSearchResult();
            }
        });

        ["qty","customer_price","supplier_discount","additional_discount","tax_entry_mode","vat_inclusive","vat_rate","vat_per_unit","total_vat","is_bonus"].forEach(f=>{
            dialog.fields_dict[f].df.onchange=refresh;
        });
        dialog.fields_dict.supplier_base_price.df.onchange=async()=>{
            if(updating)return;
            supplierPriceTouched=true;
            pricingMethodTouched=true;
            const currentMethod=dialog.get_value("pricing_method")||"";
            if(!currentMethod.startsWith("Direct")){
                updating=true;
                try{await setIf("pricing_method","Discount From Supplier Base Price");}finally{updating=false;}
            }
            await refresh();
        };
        dialog.fields_dict.pricing_method.df.onchange=async()=>{
            if(updating)return;
            pricingMethodTouched=true;
            await refresh();
        };
        dialog.fields_dict.item_tax_template.df.onchange=applyTaxTemplate;
        dialog.fields_dict.net_before_vat.df.onchange=async()=>{
            if(updating)return;
            updating=true;
            try{await setIf("pricing_method","Direct Net Before VAT");}finally{updating=false;}
            await refresh();
        };
        dialog.fields_dict.net_rate.df.onchange=async()=>{
            if(updating)return;
            updating=true;
            try{await setIf("pricing_method","Direct Final Net Rate");}finally{updating=false;}
            await refresh();
        };

        this.activeItemDialog = dialog;
        dialog.$wrapper.off("hidden.bs.modal.pimv1-active-dialog").on("hidden.bs.modal.pimv1-active-dialog", () => {
            if (this.activeItemDialog === dialog) this.activeItemDialog = null;
        });
        dialog.show();
        this.focusOpenItemDialogSearch(dialog);
        dialog.$wrapper.off("keydown.pimv1-add-line-enter").on("keydown.pimv1-add-line-enter",(event)=>{
            if(event.key!=="Enter"||event.shiftKey||event.ctrlKey||event.altKey||event.metaKey)return;
            const $target=$(event.target);
            if($target.is("textarea,select")||$target.closest(".modal-footer").length)return;
            const $visibleAutocomplete=dialog.$wrapper.find(".awesomplete ul:visible, .autocomplete-items:visible");
            if($visibleAutocomplete.length)return;
            if($target.is("[data-role='item-card-search']"))return;
            if(!dialog.get_value("item_code"))return;
            event.preventDefault();
            event.stopPropagation();
            dialog.get_primary_btn().trigger("click");
        });
        if(existing.item_code)selectItem(existing.item_code);
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
        const calculated=this.calculateLine(values);
        const risk=this.evaluateRisk(context.risk||values.risk_metrics||{},flt(values.qty),flt(context.conversion_factor)||flt(values.conversion_factor)||1,values.expiry_date);
        return {
            row_id:values.row_id||this.makeRowId(),item_code:values.item_code,item_name:context.item_name||values.item_name||values.item_code,
            qty:flt(values.qty),uom:values.uom||context.purchase_uom||context.stock_uom,conversion_factor:flt(context.conversion_factor)||flt(values.conversion_factor)||1,
            customer_price:flt(values.customer_price),printed_retail_price:flt(values.customer_price),customer_base_before_vat:calculated.customer_base_before_vat,
            supplier_base_price:calculated.supplier_base_price,pricing_method:values.pricing_method||"Discount From Customer Price",
            entered_net_before_vat:(values.pricing_method||"")==="Direct Net Before VAT"?flt(values.net_before_vat):flt(calculated.entered_net_before_vat||0),
            supplier_discount:calculated.supplier_discount,additional_discount:flt(values.additional_discount),effective_discount:calculated.effective_discount,
            tax_entry_mode:values.tax_entry_mode||"No VAT",vat_inclusive:values.vat_inclusive===undefined?1:cint(values.vat_inclusive),vat_rate:calculated.vat_rate,net_before_vat:calculated.net_before_vat,
            vat_per_unit:calculated.vat_per_unit,total_vat:calculated.total_vat,net_rate:calculated.net_rate,amount:calculated.amount,
            batch_no:values.batch_no||"",expiry_date:values.expiry_date||"",item_tax_template:values.item_tax_template||"",item_tax_rate:calculated.vat_rate,
            is_bonus:cint(values.is_bonus),auto_batch_reason:values.auto_batch_reason||"",has_batch_no:cint(context.has_batch_no||values.has_batch_no),
            has_expiry_date:cint(context.has_expiry_date||values.has_expiry_date),current_customer_price:flt(context.custom_customer_price||values.current_customer_price),
            risk_level:risk.level,risk_flags:risk.flags,risk_messages:risk.messages,risk_confirmed:cint(values.risk_confirmed),
            risk_confirmation_reason:values.risk_confirmation_reason||"",risk_metrics:context.risk||values.risk_metrics||{},
        };
    }

    calculateLine(values) {
        const customerPrice=flt(values.customer_price||values.printed_retail_price);
        const qty=flt(values.qty)||1;
        const mode=values.tax_entry_mode||"No VAT";
        const vatInclusive=cint(values.vat_inclusive);
        const templateRate=this.taxRateForTemplate(values.item_tax_template);
        const vatRate=Math.max(0,flt(values.vat_rate)||(mode!=="No VAT"?templateRate:0));

        if (cint(values.is_bonus)) {
            const customerBase=(mode!=="No VAT"&&vatRate)?customerPrice/(1+vatRate/100):customerPrice;
            const taxableBase=Math.max(0,flt(values.supplier_base_price)||customerBase);
            let vatPerUnit=0;
            if(mode==="VAT Per Unit") vatPerUnit=Math.max(0,flt(values.vat_per_unit));
            else if(mode==="Total VAT for Line") vatPerUnit=Math.max(0,flt(values.total_vat))/qty;
            else if(mode==="Auto by VAT %") vatPerUnit=taxableBase*vatRate/100;
            const totalVat=mode==="Total VAT for Line"?Math.max(0,flt(values.total_vat)):vatPerUnit*qty;
            const finalRate=vatPerUnit;
            const effective=customerPrice?100*(1-finalRate/customerPrice):100;
            return {
                supplier_discount:100,
                effective_discount:effective,
                customer_base_before_vat:customerBase,
                supplier_base_price:taxableBase,
                net_before_vat:0,
                vat_rate:vatRate,
                vat_per_unit:vatPerUnit,
                total_vat:totalVat,
                net_rate:finalRate,
                amount:qty*finalRate
            };
        }

        const method=values.pricing_method||"Discount From Customer Price";
        const supplierInvoicePrice=Math.max(
            0,
            method==="Discount From Customer Price"
                ? customerPrice
                : (flt(values.supplier_base_price)||customerPrice)
        );
        const additional=Math.max(0,Math.min(100,flt(values.additional_discount)));
        let supplierDiscount=Math.max(0,Math.min(100,flt(values.supplier_discount)));
        let netBefore=0;
        let vatPerUnit=0;
        let finalRate=0;

        if(method==="Direct Final Net Rate"&&flt(values.net_rate)>0){
            finalRate=Math.max(0,flt(values.net_rate));
            if(mode==="VAT Per Unit") vatPerUnit=Math.max(0,flt(values.vat_per_unit));
            else if(mode==="Total VAT for Line") vatPerUnit=Math.max(0,flt(values.total_vat))/qty;
            else if(mode==="Auto by VAT %"&&vatRate) vatPerUnit=finalRate-finalRate/(1+vatRate/100);
            netBefore=Math.max(0,finalRate-vatPerUnit);

            const discountComparable=vatInclusive?finalRate:netBefore;
            const denominator=supplierInvoicePrice*Math.max(0.000001,1-additional/100);
            supplierDiscount=denominator?Math.max(0,Math.min(100,100*(1-discountComparable/denominator))):0;
        }else if(method==="Direct Net Before VAT"){
            const enteredNetBefore=Math.max(0,flt(values.entered_net_before_vat||values.net_before_vat));
            // The entered supplier net already reflects the base supplier discount.
            // Additional Discount is a second, separate discount applied afterwards.
            netBefore=enteredNetBefore*(1-additional/100);
            if(mode==="VAT Per Unit") vatPerUnit=Math.max(0,flt(values.vat_per_unit));
            else if(mode==="Total VAT for Line") vatPerUnit=Math.max(0,flt(values.total_vat))/qty;
            else if(mode==="Auto by VAT %") vatPerUnit=netBefore*vatRate/100;
            finalRate=netBefore+vatPerUnit;

            supplierDiscount=supplierInvoicePrice?Math.max(0,Math.min(100,100*(1-enteredNetBefore/supplierInvoicePrice))):0;
        }else{
            const discountedInvoicePrice=supplierInvoicePrice*(1-supplierDiscount/100)*(1-additional/100);

            if(mode==="No VAT"){
                netBefore=discountedInvoicePrice;
                vatPerUnit=0;
                finalRate=discountedInvoicePrice;
            }else if(mode==="Auto by VAT %"){
                if(vatInclusive){
                    finalRate=discountedInvoicePrice;
                    netBefore=vatRate?finalRate/(1+vatRate/100):finalRate;
                    vatPerUnit=finalRate-netBefore;
                }else{
                    netBefore=discountedInvoicePrice;
                    vatPerUnit=netBefore*vatRate/100;
                    finalRate=netBefore+vatPerUnit;
                }
            }else{
                if(mode==="VAT Per Unit") vatPerUnit=Math.max(0,flt(values.vat_per_unit));
                else if(mode==="Total VAT for Line") vatPerUnit=Math.max(0,flt(values.total_vat))/qty;

                if(vatInclusive){
                    finalRate=discountedInvoicePrice;
                    netBefore=Math.max(0,finalRate-vatPerUnit);
                }else{
                    netBefore=discountedInvoicePrice;
                    finalRate=netBefore+vatPerUnit;
                }
            }
        }

        const totalVat=mode==="Total VAT for Line"?Math.max(0,flt(values.total_vat)):vatPerUnit*qty;
        const effective=customerPrice?100*(1-finalRate/customerPrice):0;
        const customerBase=(mode!=="No VAT"&&vatRate&&vatInclusive)?supplierInvoicePrice/(1+vatRate/100):supplierInvoicePrice;

        return {
            supplier_discount:supplierDiscount,
            effective_discount:effective,
            customer_base_before_vat:customerBase,
            supplier_base_price:supplierInvoicePrice,
            entered_net_before_vat:method==="Direct Net Before VAT"?Math.max(0,flt(values.entered_net_before_vat||values.net_before_vat)):0,
            net_before_vat:netBefore,
            vat_rate:vatRate,
            vat_per_unit:vatPerUnit,
            total_vat:totalVat,
            net_rate:finalRate,
            amount:qty*finalRate
        };
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
        const c=this.calculateLine(row);Object.assign(row,{entered_net_before_vat:c.entered_net_before_vat||row.entered_net_before_vat||0,supplier_discount:c.supplier_discount,effective_discount:c.effective_discount,customer_base_before_vat:c.customer_base_before_vat,supplier_base_price:c.supplier_base_price,net_before_vat:c.net_before_vat,vat_rate:c.vat_rate,vat_per_unit:c.vat_per_unit,total_vat:c.total_vat,net_rate:c.net_rate,amount:c.amount});return row;
    }

    applyInlineValue($field) {
        const index = Number($field.data("index"));
        const fieldname = $field.data("inline-field");
        const row = this.rows[index];
        if (!row || !fieldname) return false;
        const numericFields = new Set(["qty", "customer_price", "printed_retail_price", "supplier_base_price", "supplier_discount", "additional_discount", "net_rate"]);
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
        if (fieldname === "item_tax_template") {
            const rate = row.item_tax_template ? this.taxRateForTemplate(row.item_tax_template) : 0;
            row.tax_entry_mode = row.item_tax_template ? "Auto by VAT %" : "No VAT";
            row.vat_rate = rate;
            if (!flt(row.supplier_base_price)) row.supplier_base_price = flt(row.customer_price);
        }
        if (fieldname === "net_rate") row.pricing_method = "Direct Final Net Rate";
        if (fieldname === "supplier_base_price" && !String(row.pricing_method||"").startsWith("Direct")) row.pricing_method = "Discount From Supplier Base Price";
        if (fieldname === "supplier_discount" && String(row.pricing_method||"").startsWith("Direct")) row.pricing_method = "Discount From Supplier Base Price";
        if (fieldname === "additional_discount" && row.pricing_method === "Direct Final Net Rate") row.pricing_method = "Discount From Supplier Base Price";
        this.recalculateRow(row);
        const refreshedRisk=this.evaluateRisk(row.risk_metrics||{},row.qty,row.conversion_factor||1,row.expiry_date);
        const previousFlags=JSON.stringify(row.risk_flags||[]);
        row.risk_level=refreshedRisk.level;
        row.risk_flags=refreshedRisk.flags;
        row.risk_messages=refreshedRisk.messages;
        if(previousFlags!==JSON.stringify(refreshedRisk.flags||[])){
            row.risk_confirmed=0;
            row.risk_confirmation_reason="";
        }

        const requiresNearExpiryConfirmation =
            fieldname === "expiry_date"
            && cint((this.bootstrap.purchase_settings || {}).require_risk_confirmation)
            && (refreshedRisk.flags || []).includes("NEAR_EXPIRY")
            && !cint(row.risk_confirmed);

        this.activeRowIndex = index;
        this.renderRows();
        this.refreshCards();

        if (requiresNearExpiryConfirmation) {
            frappe.show_alert({
                message: __("Near-expiry item requires confirmation and a reason."),
                indicator: "orange"
            }, 7);

            window.setTimeout(() => {
                this.openItemDialog(index);
            }, 120);
        }

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
                <div>${__("Customer Price")}</div>
                <div>${__("Supplier Price")}</div>
                <div>${__("Supplier Disc.")}</div>
                <div>${__("Additional Disc.")}</div>
                <div>${__("Net Disc.")}</div>
                <div>${__("Net Rate")}</div>
                <div>${__("Amount")}</div>
                <div>${__("Batch")}</div>
                <div>${__("Expiry")}</div>
                <div>${__("Item Tax Template")}</div>
                <div>${__("Actions")}</div>
            </div>`;
        const rows = this.rows.map((row, index) => `
            <div class="pimv1-item-row ${this.rowStatus(row)} ${index === this.activeRowIndex ? "is-active" : ""}" data-row-index="${index}">
                <div class="pimv1-row-grid">
                    <div class="pimv1-row-field"><span class="pimv1-row-number">${index + 1}</span></div>
                    <div class="pimv1-row-field"><div class="pimv1-item-one-line" title="${this.escape(row.item_name || row.item_code)}"><span class="pimv1-item-name">${this.escape(row.item_name || row.item_code)}${(()=>{const live=this.evaluateRisk(row.risk_metrics||{},row.qty,row.conversion_factor||1,row.expiry_date);return live.level!=="None"?`<span class="pimv1-item-risk-dot" title="${this.escape((live.messages||[]).join(" • "))}">${live.level==="Critical"?"⛔":"⚠"}</span>`:""})()}</span><span class="pimv1-item-code">${this.escape(row.item_code)}</span></div></div>
                    <div class="pimv1-row-field"><span class="pimv1-pill ${row.is_bonus ? "pimv1-pill-bonus" : "pimv1-pill-normal"}">${row.is_bonus ? __("Bonus") : __("Purchase")}</span></div>
                    <div class="pimv1-row-field"><div class="pimv1-qty-wrap"><input class="pimv1-inline-input" type="number" min="0.001" step="0.001" value="${this.number(row.qty)}" data-index="${index}" data-inline-field="qty"><span class="pimv1-uom-inline">${this.escape(row.uom || "")}</span></div></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="number" min="0" step="0.01" value="${this.number(row.customer_price || row.printed_retail_price)}" data-index="${index}" data-inline-field="customer_price"></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="number" min="0" step="0.01" value="${this.number(row.supplier_base_price)}" data-index="${index}" data-inline-field="supplier_base_price" ${row.is_bonus ? "disabled" : ""}></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="number" min="0" max="100" step="0.01" value="${this.number(row.supplier_discount)}" data-index="${index}" data-inline-field="supplier_discount" ${row.is_bonus ? "disabled" : ""}></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="number" min="0" max="100" step="0.01" value="${this.number(row.additional_discount)}" data-index="${index}" data-inline-field="additional_discount" ${row.is_bonus ? "disabled" : ""}></div>
                    <div class="pimv1-row-field"><div class="pimv1-readonly-cell">${this.number(row.effective_discount)}%</div></div>
                    <div class="pimv1-row-field"><input class="pimv1-inline-input" type="number" min="0" step="0.01" value="${this.number(row.net_rate)}" data-index="${index}" data-inline-field="net_rate" ${row.is_bonus ? "disabled" : ""}></div>
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

    rowStatus(row) {
        if (cint(row.is_bonus)) return "status-bonus";
        const liveRisk=this.evaluateRisk(row.risk_metrics||{},row.qty,row.conversion_factor||1,row.expiry_date);
        if (liveRisk.level === "Critical" && !cint(row.risk_confirmed)) return "status-critical";
        if (liveRisk.level === "Warning" && !cint(row.risk_confirmed)) return "status-warning";
        if (!row.item_code || flt(row.qty) <= 0 || flt(row.customer_price || row.printed_retail_price) <= 0 || flt(row.supplier_base_price) <= 0 || flt(row.net_rate) <= 0) return "status-error";
        if ((row.has_batch_no && !row.batch_no && !this.automaticBatchEnabled()) || (row.has_expiry_date && !row.expiry_date)) return "status-error";
        if (row.current_customer_price && Math.abs(flt(row.customer_price) - flt(row.current_customer_price)) > 0.001) return "status-warning";
        return "status-valid";
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

    automaticBatchEnabled() {
        return cint((this.bootstrap.purchase_settings || {}).enable_automatic_batch_generation);
    }

    bindSupplierInvoiceTotalManualInput(control) {
        const $input = control && control.$input && control.$input.length
            ? control.$input
            : (control && control.$wrapper ? control.$wrapper.find("input").first() : $());

        if (!$input.length) return;

        $input
            .off(".pimv1SupplierInvoiceTotal")
            .on("input.pimv1SupplierInvoiceTotal", (event) => {
                // Frappe set_value() also fires onchange. Only a real browser input event
                // is allowed to switch the field from automatic mode to manual mode.
                if (!this.initialRenderComplete || this.supplierInvoiceTotalAutoUpdating || !event.originalEvent) return;

                const rawValue = String($input.val() ?? "").replace(/,/g, "").trim();
                const numericValue = flt(rawValue);

                // Clearing the field returns it to automatic mode.
                if (!rawValue || Math.abs(numericValue) < 0.0001) {
                    this.supplierInvoiceTotalManual = false;
                    window.setTimeout(() => this.refreshCards(), 0);
                    return;
                }

                this.supplierInvoiceTotalManual = true;
                this.refreshCards();
            });
    }

    syncSupplierInvoiceTotal(systemTotal) {
        const control = this.controls.supplier_invoice_total;
        if (!control) return;

        if (!this.rows.length) {
            this.lastAutoSupplierInvoiceTotal = 0;
            if (!this.supplierInvoiceTotalManual && Math.abs(flt(this.value("supplier_invoice_total"))) > 0.0001) {
                this.supplierInvoiceTotalAutoUpdating = true;
                Promise.resolve(control.set_value(0)).finally(() => {
                    window.setTimeout(() => { this.supplierInvoiceTotalAutoUpdating = false; }, 50);
                });
            }
            return;
        }

        const rounded = Math.round(flt(systemTotal) * 100) / 100;
        const currentValue = flt(this.value("supplier_invoice_total"));

        // Recover automatically from the old race condition where a zero field
        // was incorrectly marked as a manual value.
        if (this.supplierInvoiceTotalManual && currentValue <= 0 && rounded > 0) {
            this.supplierInvoiceTotalManual = false;
        }

        if (this.supplierInvoiceTotalManual) return;

        this.lastAutoSupplierInvoiceTotal = rounded;
        if (Math.abs(currentValue - rounded) < 0.0001) return;

        this.supplierInvoiceTotalAutoUpdating = true;
        Promise.resolve(control.set_value(rounded)).finally(() => {
            window.setTimeout(() => {
                this.supplierInvoiceTotalAutoUpdating = false;
            }, 50);
        });
    }

    applySavedItemUpdates(savedItems) {
        if (!Array.isArray(savedItems) || !savedItems.length) return;
        savedItems.forEach((saved, index) => {
            const row = this.rows[index];
            if (!row || (saved.item_code && row.item_code !== saved.item_code)) return;
            if (saved.batch_no) row.batch_no = saved.batch_no;
            if (saved.expiry_date) row.expiry_date = saved.expiry_date;
            row.auto_batch_generated = cint(saved.auto_batch_generated);
            row.serial_and_batch_bundle = saved.serial_and_batch_bundle || row.serial_and_batch_bundle || "";
        });
        this.renderRows();
    }

    totals() {
        const normal=this.rows.filter(r=>!r.is_bonus),bonus=this.rows.filter(r=>r.is_bonus);
        const customerGross=normal.reduce((s,r)=>s+flt(r.qty)*flt(r.customer_price),0);

        // Commercial purchase breakdown is based on the supplier invoice price,
        // not the pharmacy's current customer price.
        const supplierInvoiceGross=normal.reduce((sum,row)=>{
            return sum+flt(row.qty)*flt(row.supplier_base_price);
        },0);

        const supplierDiscount=normal.reduce((sum,row)=>{
            const qty=flt(row.qty);
            const supplierPrice=flt(row.supplier_base_price);
            const supplierDiscountPct=Math.max(0,Math.min(100,flt(row.supplier_discount)));
            return sum+qty*supplierPrice*supplierDiscountPct/100;
        },0);

        const additionalLineDiscount=normal.reduce((sum,row)=>{
            const qty=flt(row.qty);
            const supplierPrice=flt(row.supplier_base_price);
            const supplierDiscountPct=Math.max(0,Math.min(100,flt(row.supplier_discount)));
            const additionalDiscountPct=Math.max(0,Math.min(100,flt(row.additional_discount)));
            const afterSupplierDiscount=supplierPrice*(1-supplierDiscountPct/100);
            return sum+qty*afterSupplierDiscount*additionalDiscountPct/100;
        },0);

        const netBeforeVat=normal.reduce((s,r)=>s+flt(r.qty)*flt(r.net_before_vat),0);
        const vat=this.rows.reduce((s,r)=>s+flt(r.total_vat),0);
        const normalFinal=normal.reduce((s,r)=>s+flt(r.amount),0);
        const bonusVatPayable=bonus.reduce((s,r)=>s+flt(r.amount),0);
        const finalNet=normalFinal+bonusVatPayable;
        const lineDiscount=customerGross-normalFinal;
        const bonusValue=bonus.reduce((s,r)=>s+flt(r.qty)*flt(r.customer_price),0);
        const invoiceDiscountPct=Math.max(0,Math.min(100,flt(this.value("invoice_discount_percentage"))));
        const invoiceDiscount=finalNet*invoiceDiscountPct/100;const netAfterDiscount=finalNet-invoiceDiscount;
        const charges=flt(this.value("additional_charge_amount"));const estimatedGrand=netAfterDiscount+charges;
        const enteredSupplierTotal=flt(this.value("supplier_invoice_total"));
        const supplierInvoiceTotal=(!this.supplierInvoiceTotalManual&&this.rows.length)?estimatedGrand:enteredSupplierTotal;
        const fractionAdjustment=supplierInvoiceTotal?supplierInvoiceTotal-estimatedGrand:0;
        return {
            customerGross,
            supplierGross:supplierInvoiceGross,
            supplierInvoiceGross,
            supplierDiscount,
            additionalLineDiscount,
            netBeforeVat,
            estimatedTax:vat,
            net:finalNet,
            lineDiscount,
            bonusValue,
            bonusVatPayable,
            invoiceDiscountPct,
            invoiceDiscount,
            netAfterDiscount,
            charges,
            estimatedBeforeTax:netBeforeVat,
            estimatedGrand,
            supplierInvoiceTotal,
            fractionAdjustment,
            taxIncluded:1
        };
    }

    renderSummary() {
        const t=this.totals();const savedTax=this.lastSavedTotals?flt(this.lastSavedTotals.total_taxes_and_charges):null;
        this.$main.find("[data-role='summary']").html(`
            <div class="pimv1-summary-row"><span>${__("Customer Price Gross")}</span><span>${this.money(t.customerGross)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Supplier Invoice Gross")}</span><span>${this.money(t.supplierInvoiceGross)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Supplier Discount")}</span><span>-${this.money(t.supplierDiscount)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Additional Line Discount")}</span><span>-${this.money(t.additionalLineDiscount)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Net Before VAT")}</span><span>${this.money(t.netBeforeVat)}</span></div>
            <div class="pimv1-summary-row"><span>${__("VAT from Item Lines")}</span><span>${this.money(t.estimatedTax)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Final Item Total")}</span><span>${this.money(t.net)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Additional Invoice Discount")}</span><span>-${this.money(t.invoiceDiscount)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Shipping / Additional Charges")}</span><span>+${this.money(t.charges)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Bonus Retail Value")}</span><span>${this.money(t.bonusValue)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Bonus VAT Payable")}</span><span>${this.money(t.bonusVatPayable)}</span></div>
            ${savedTax!==null?`<div class="pimv1-summary-row"><span>${__("Actual Taxes and Charges After Save")}</span><span>${this.money(savedTax)}</span></div>`:""}
            <div class="pimv1-summary-row"><span>${__("Supplier Invoice Total")}</span><span>${this.money(t.supplierInvoiceTotal)}</span></div>
            <div class="pimv1-summary-row"><span>${__("Fraction Adjustment")}</span><span>${this.money(t.fractionAdjustment)}</span></div>
            <div class="pimv1-summary-row pimv1-summary-grand"><strong>${__("Estimated Grand Total")}</strong><strong>${this.money(t.estimatedGrand+t.fractionAdjustment)}</strong></div>
            <div class="pimv1-tax-note">${__("Final Net Rate includes the VAT amount entered for each item. VAT is not added a second time to the invoice total.")}</div>
        `);
    }

    refreshCards() {
        const totals = this.totals();
        this.syncSupplierInvoiceTotal(totals.estimatedGrand);
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
        this.$main.find("[data-role='estimated-grand']").text(this.money(totals.estimatedGrand + totals.fractionAdjustment));
        if (this.controls.fraction_adjustment) this.controls.fraction_adjustment.set_value(totals.fractionAdjustment);
        this.renderValidationPanel();
        this.renderSummary();
    }

    validationIssues() {
        const errors = [];
        const warnings = [];
        if (!this.value("company")) errors.push({ message: __("Company is required."), field: "company" });
        if (!this.value("supplier")) errors.push({ message: __("Supplier is required."), field: "supplier" });
        if (!this.value("warehouse")) errors.push({ message: __("Receiving Warehouse is required."), field: "warehouse" });
        if (!this.value("bill_no")) errors.push({ message: __("Supplier Invoice Number is required."), field: "bill_no" });
        if (!this.value("bill_date")) errors.push({ message: __("Supplier Invoice Date is required."), field: "bill_date" });
        if (!this.value("payment_classification")) errors.push({ message: __("Payment Classification is required, especially for mixed suppliers."), field: "payment_classification" });
        const effectiveSupplierInvoiceTotal = flt(this.totals().supplierInvoiceTotal);
        if (cint((this.bootstrap.purchase_settings || {}).require_exact_supplier_invoice_total) && effectiveSupplierInvoiceTotal <= 0) errors.push({ message: __("Supplier Invoice Total is required."), field: "supplier_invoice_total" });
        if (!this.rows.length) errors.push({ message: __("Add at least one purchase item."), action: "add-item" });
        this.rows.forEach((row, index) => {
            if (!row.item_code || flt(row.qty) <= 0) errors.push({ message: __("Invalid item or quantity on row {0}.", [index + 1]), row: index });
            if (!row.is_bonus && flt(row.customer_price || row.printed_retail_price) <= 0) errors.push({ message: __("Customer Price is required on row {0}.", [index + 1]), row: index });
            if (!row.is_bonus && flt(row.supplier_base_price) <= 0) errors.push({ message: __("Supplier Base Price is required on row {0}.", [index + 1]), row: index });
            if (!row.is_bonus && flt(row.net_rate) <= 0) errors.push({ message: __("Net Rate is required on row {0}.", [index + 1]), row: index });
            if (row.has_batch_no && !row.batch_no && !this.automaticBatchEnabled()) errors.push({ message: __("Batch is required on row {0}.", [index + 1]), row: index });
            if (row.has_expiry_date && !row.expiry_date) errors.push({ message: __("Expiry Date is required on row {0}.", [index + 1]), row: index });
            const liveRisk=this.evaluateRisk(row.risk_metrics||{},row.qty,row.conversion_factor||1,row.expiry_date);
            if ((liveRisk.flags||[]).includes("EXPIRED_ITEM")) errors.push({ message: __("Expired item on row {0}: {1}", [index+1,(liveRisk.messages||[]).join(" • ")]), row:index });
            if (row.tax_entry_mode !== "No VAT" && !row.item_tax_template) errors.push({ message: __("Item Tax Template is required for taxable row {0}.", [index + 1]), row:index });
            const requireRiskConfirmation = cint((this.bootstrap.purchase_settings || {}).require_risk_confirmation);
            const nearExpiryPending =
                requireRiskConfirmation
                && (liveRisk.flags || []).includes("NEAR_EXPIRY")
                && (!cint(row.risk_confirmed) || !(row.risk_confirmation_reason || "").trim());

            if (nearExpiryPending) {
                errors.push({
                    message: __("Near-expiry confirmation and reason are required on row {0}: {1}", [index+1,(liveRisk.messages||[]).join(" • ")]),
                    row:index,
                    action:"review-risk"
                });
            } else if (liveRisk.level !== "None" && !cint(row.risk_confirmed)) {
                warnings.push({
                    message: __("Risk confirmation is pending on row {0}: {1}", [index+1,(liveRisk.messages||[]).join(" • ")]),
                    row:index,
                    action:"review-risk"
                });
            } else if (this.rowStatus(row) === "status-warning") {
                warnings.push({ message: __("Review price warning on row {0}.", [index + 1]), row: index });
            }
        });
        const totals = this.totals();
        const maxAdjustment = flt((this.bootstrap.purchase_settings || {}).max_fraction_adjustment || 0);
        if (totals.supplierInvoiceTotal && Math.abs(totals.fractionAdjustment) > maxAdjustment + 0.0001) errors.push({ message: __("Invoice difference {0} exceeds the permitted fraction adjustment {1}.", [this.money(totals.fractionAdjustment), this.money(maxAdjustment)]), field: "supplier_invoice_total" });
        return { errors, warnings };
    }

    renderValidationPanel() {
        const issues = this.validationIssues();
        const $panel = this.$main.find("[data-role='validation-panel']");
        const cls = issues.errors.length ? "has-errors" : (issues.warnings.length ? "has-warnings" : "is-ready");
        const title = issues.errors.length ? __("Invoice needs correction") : (issues.warnings.length ? __("Invoice has warnings") : __("Invoice Ready ✓"));
        const rows = [...issues.errors.map(x => ({...x, type:"error"})), ...issues.warnings.map(x => ({...x, type:"warning"}))];
        $panel.removeClass("is-ready has-errors has-warnings").addClass(cls).html(`<strong>${title}</strong>${rows.length ? `<div style="margin-top:6px">${rows.map((x,i)=>`<div class="pimv1-validation-issue" data-validation-index="${i}">• ${this.escape(x.message)}</div>`).join("")}</div>` : ""}`);
        $panel.data("issues", rows);
        $panel.off("click.pimv1-validation").on("click.pimv1-validation", "[data-validation-index]", (event) => {
            const issue = rows[Number($(event.currentTarget).data("validation-index"))];
            if (issue.action === "review-risk" && Number.isInteger(issue.row)) {
                this.openItemDialog(issue.row);
            } else if (issue.field && this.controls[issue.field]) {
                this.controls[issue.field].set_focus();
            } else if (Number.isInteger(issue.row)) {
                this.setActiveRow(issue.row);
                this.$main.find(`[data-row-index="${issue.row}"] input:enabled:first`).trigger("focus");
            } else if (issue.action === "add-item") {
                this.openItemDialog();
            }
        });
        return issues;
    }

    validateAndReport() {
        const issues = this.renderValidationPanel();
        frappe.show_alert({ message: issues.errors.length ? __("Fix validation errors before saving.") : __("Validation completed."), indicator: issues.errors.length ? "red" : (issues.warnings.length ? "orange" : "green") }, 5);
        return !issues.errors.length;
    }

    validatePage() {
        const issues = this.renderValidationPanel();
        if (issues.errors.length) {
            frappe.msgprint({
                title: __("Complete Purchase Invoice"),
                message: `<ul>${issues.errors.map((x) => `<li>${this.escape(x.message)}</li>`).join("")}</ul>`,
                indicator: "orange"
            });

            const riskIssue = issues.errors.find((issue) =>
                issue.action === "review-risk" && Number.isInteger(issue.row)
            );
            if (riskIssue) {
                window.setTimeout(() => this.openItemDialog(riskIssue.row), 180);
            }
            return false;
        }
        return true;
    }

    payload() {
        const totals = this.totals();
        return {
            name: this.draftName,
            company: this.value("company"),
            supplier: this.value("supplier"),
            warehouse: this.value("warehouse"),
            supplier_invoice_total: flt(totals.supplierInvoiceTotal),
            supplier_invoice_total_manual: cint(this.supplierInvoiceTotalManual),
            payment_classification: this.value("payment_classification"),
            exclude_from_claim: this.value("payment_classification") === "Cash Invoice" ? 1 : 0,
            posting_date: this.value("posting_date"),
            bill_no: this.value("bill_no"),
            bill_date: this.value("bill_date"),
            due_date: this.value("due_date"),
            taxes_and_charges: this.value("taxes_and_charges"),
            tax_included_in_print_rate: 1,
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

    async saveDraft(options = {}) {
        if (this.isSaving || !this.validatePage()) return null;
        this.isSaving = true;
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.save_draft",
                args: { payload: JSON.stringify(this.payload()) },
                freeze: true,
                freeze_message: options.freezeMessage || __("Saving Purchase Invoice Draft..."),
            });
            const message = response.message || {};
            const invoice = message.invoice || {};
            this.draftName = invoice.name;
            this.lastSavedTotals = invoice;
            this.applySavedItemUpdates(invoice.items || []);
            this.bootstrap.recent_invoices = message.recent_invoices || [];
            this.$main.find("[data-role='draft-badge']").text(invoice.name || __("Saved Draft"));
            this.$main.find("[data-role='saved-grand']").text(`${this.money(invoice.total_taxes_and_charges)} / ${this.money(invoice.grand_total)}`);
            this.$main.find("[data-role='saved-status']").text(`${invoice.status || __("Draft")} • ${__("Tax / Grand")}`);
            this.renderSummary();
            this.$openButton.prop("disabled", false);
            this.$submitButton.prop("disabled", invoice.docstatus !== 0);
            this.$cancelButton.prop("disabled", invoice.docstatus !== 1);
            this.$main.find("[data-action='page-save-draft']").prop("disabled", invoice.docstatus !== 0);
            this.$main.find("[data-action='page-save-submit']").prop("disabled", invoice.docstatus !== 0);
            this.clearLocalDraft();
            this.renderRecentInvoices(this.bootstrap.recent_invoices);
            if (!options.silent) {
                frappe.show_alert({ message: __("Purchase Invoice {0} saved as Draft.", [invoice.name]), indicator: "green" }, 7);
            }
            return invoice;
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
            this.supplierInvoiceTotalManual = false;
            this.supplierInvoiceTotalAutoUpdating = true;
            this.lastAutoSupplierInvoiceTotal = 0;
            ["supplier", "bill_no", "payment_classification", "taxes_and_charges", "additional_charge_account", "remarks"].forEach((field) => this.controls[field] && this.controls[field].set_value(""));
            ["invoice_discount_percentage", "additional_charge_amount", "supplier_invoice_total"].forEach((field) => this.controls[field] && this.controls[field].set_value(0));
            window.setTimeout(() => { this.supplierInvoiceTotalAutoUpdating = false; }, 0);
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
            this.$submitButton.prop("disabled", true);
            this.$cancelButton.prop("disabled", true);
            this.$main.find("[data-action='page-save-draft']").prop("disabled", false);
            this.$main.find("[data-action='page-save-submit']").prop("disabled", false);
            this.renderRows();
            this.refreshCards();
        };
        if (this.rows.length || this.draftName) frappe.confirm(__("Start a new invoice and clear current data?"), reset);
        else reset();
    }

    async saveAndSubmit() {
        if (this.isSaving || !this.validatePage()) return;
        const totals = this.totals();
        const supplierLabel = this.supplierContext.supplier_name || this.value("supplier") || "—";
        const message = `
            <div style="line-height:1.8">
                <div><strong>${__("Supplier")}:</strong> ${this.escape(supplierLabel)}</div>
                <div><strong>${__("Items")}:</strong> ${this.rows.length}</div>
                <div><strong>${__("Supplier Invoice Total")}:</strong> ${this.money(totals.supplierInvoiceTotal)}</div>
                <div class="text-danger" style="margin-top:8px">${__("Submitting creates stock and accounting entries and prevents normal editing.")}</div>
            </div>`;
        frappe.confirm(message, async () => {
            const saved = await this.saveDraft({
                silent: true,
                freezeMessage: __("Saving and validating Purchase Invoice..."),
            });
            if (!saved || !saved.name) return;
            await this.performSubmit();
        });
    }

    async performSubmit() {
        if (!this.draftName) return null;
        const response = await frappe.call({
            method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.submit_invoice",
            args: { name: this.draftName },
            freeze: true,
            freeze_message: __("Submitting Purchase Invoice..."),
        });
        const message = response.message || {};
        const invoice = message.invoice || {};
        this.lastSavedTotals = invoice;
        this.bootstrap.recent_invoices = message.recent_invoices || this.bootstrap.recent_invoices || [];
        this.$submitButton.prop("disabled", true);
        this.$cancelButton.prop("disabled", false);
        this.$main.find("[data-action='page-save-draft']").prop("disabled", true);
        this.$main.find("[data-action='page-save-submit']").prop("disabled", true);
        this.$main.find("[data-role='draft-badge']").text(`${invoice.name || this.draftName} • ${invoice.status || __("Submitted")}`);
        this.$main.find("[data-role='saved-status']").text(invoice.status || __("Submitted"));
        this.renderRecentInvoices(this.bootstrap.recent_invoices);
        frappe.show_alert({ message: __("Purchase Invoice {0} submitted successfully.", [invoice.name || this.draftName]), indicator: "green" }, 7);
        return invoice;
    }

    async submitInvoice() {
        if (!this.draftName || !this.validateAndReport()) return;
        frappe.confirm(__("Submit this saved Purchase Invoice? Stock and accounting entries will be created."), async () => {
            await this.performSubmit();
        });
    }

    async cancelInvoice() {
        if (!this.draftName) return;
        frappe.confirm(__("Cancel this Purchase Invoice and reverse stock/accounting entries?"), async () => {
            const response = await frappe.call({ method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.cancel_invoice", args: { name: this.draftName }, freeze: true, freeze_message: __("Cancelling Purchase Invoice...") });
            const message = response.message || {};
            const invoice = message.invoice || {};
            this.lastSavedTotals = invoice;
            this.bootstrap.recent_invoices = message.recent_invoices || this.bootstrap.recent_invoices || [];
            this.$cancelButton.prop("disabled", true);
            this.$main.find("[data-action='page-save-draft']").prop("disabled", true);
            this.$main.find("[data-action='page-save-submit']").prop("disabled", true);
            this.$main.find("[data-role='saved-status']").text(invoice.status || __("Cancelled"));
            this.$main.find("[data-role='draft-badge']").text(`${invoice.name || this.draftName} • ${invoice.status || __("Cancelled")}`);
            this.renderRecentInvoices(this.bootstrap.recent_invoices);
            frappe.show_alert({ message: __("Purchase Invoice cancelled."), indicator: "orange" }, 6);
        });
    }

    async loadDraftInvoice(name) {
        const invoiceName = String(name || "").trim();
        if (!invoiceName) return;

        const load = async () => {
            try {
                const response = await frappe.call({
                    method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.load_invoice",
                    args: { name: invoiceName },
                    freeze: true,
                    freeze_message: __("Loading Purchase Invoice Draft..."),
                });
                const message = response.message || {};
                await this.applyLoadedInvoice(message.payload || {}, message.invoice || {});
                this.toggleRecentPanel(false);
                frappe.show_alert({ message: __("Draft {0} loaded into the purchase page.", [invoiceName]), indicator: "green" }, 6);
            } catch (error) {
                frappe.msgprint({
                    title: __("Unable to Load Draft"),
                    message: this.escape(error.message || error),
                    indicator: "red",
                });
            }
        };

        if ((this.rows.length || this.draftName) && this.draftName !== invoiceName) {
            frappe.confirm(__("Open draft {0} and replace the current page data?", [invoiceName]), load);
        } else {
            await load();
        }
    }

    async applyLoadedInvoice(payload, invoice) {
        this.loadingInvoice = true;
        try {
            const headerFields = [
                "company", "warehouse", "supplier", "posting_date", "bill_no", "bill_date", "due_date",
                "taxes_and_charges", "tax_included_in_print_rate", "invoice_discount_percentage",
                "additional_charge_account", "additional_charge_amount", "supplier_invoice_total", "remarks"
            ];
            for (const fieldname of headerFields) {
                if (this.controls[fieldname] && payload[fieldname] !== undefined) {
                    await this.controls[fieldname].set_value(payload[fieldname]);
                }
            }
            if (this.controls.payment_classification) {
                await this.controls.payment_classification.set_value(payload.payment_classification || "");
            }

            this.rows = (payload.items || []).map((row) => ({ ...row, row_id: row.row_id || this.makeRowId() }));
            this.activeRowIndex = this.rows.length ? 0 : null;
            this.draftName = payload.name || invoice.name || null;
            this.attachmentUrl = payload.attachment || "";
            this.lastSavedTotals = invoice || null;
            this.supplierInvoiceTotalManual = cint(payload.supplier_invoice_total_manual);
            this.lastAutoSupplierInvoiceTotal = flt(payload.supplier_invoice_total || invoice.grand_total || 0);
        } finally {
            this.loadingInvoice = false;
        }

        await this.onSupplierChange({ preserveClassification: true, force: true });
        if (this.controls.payment_classification) {
            await this.controls.payment_classification.set_value(payload.payment_classification || "");
        }
        await this.refreshClaimPeriod();

        this.$main.find("[data-role='attachment-name']").text(this.attachmentUrl || __("No file attached"));
        this.$main.find("[data-role='draft-badge']").text(`${this.draftName} • ${invoice.status || __("Draft")}`);
        this.$main.find("[data-role='saved-grand']").text(`${this.money(invoice.total_taxes_and_charges)} / ${this.money(invoice.grand_total)}`);
        this.$main.find("[data-role='saved-status']").text(invoice.status || __("Draft"));
        this.$openButton.prop("disabled", !this.draftName);
        this.$submitButton.prop("disabled", cint(invoice.docstatus) !== 0);
        this.$cancelButton.prop("disabled", cint(invoice.docstatus) !== 1);
        this.$main.find("[data-action='page-save-draft']").prop("disabled", cint(invoice.docstatus) !== 0);
        this.$main.find("[data-action='page-save-submit']").prop("disabled", cint(invoice.docstatus) !== 0);
        this.clearLocalDraft();
        this.renderRows();
        this.refreshCards();
        this.renderSummary();
    }

    localDraftKey() {
        return `pharma_purchase_page:${frappe.session.user}:${this.value("company") || "default"}`;
    }

    persistLocalDraft() {
        if (!this.initialRenderComplete || !cint((this.bootstrap.purchase_settings || {}).enable_local_draft_recovery) || this.isSaving) return;
        try { localStorage.setItem(this.localDraftKey(), JSON.stringify({ saved_at: Date.now(), payload: this.payload() })); } catch (e) {}
    }

    offerLocalDraftRestore() {
        if (!cint((this.bootstrap.purchase_settings || {}).enable_local_draft_recovery)) return;
        let stored = null;
        try { stored = JSON.parse(localStorage.getItem(this.localDraftKey()) || "null"); } catch (e) {}
        const payload = stored && stored.payload;
        if (!payload || !(payload.items || []).length || payload.name) return;
        frappe.confirm(__("Restore the unsaved purchase invoice found in this browser?"), () => {
            this.supplierInvoiceTotalAutoUpdating = true;
            this.supplierInvoiceTotalManual = cint(payload.supplier_invoice_total_manual);

            ["supplier", "warehouse", "payment_classification", "posting_date", "bill_no", "bill_date", "due_date", "taxes_and_charges", "invoice_discount_percentage", "additional_charge_account", "additional_charge_amount", "supplier_invoice_total", "remarks"].forEach((fieldname) => {
                if (this.controls[fieldname] && payload[fieldname] !== undefined) this.controls[fieldname].set_value(payload[fieldname]);
            });
            if (this.controls.tax_included_in_print_rate) this.controls.tax_included_in_print_rate.set_value(cint(payload.tax_included_in_print_rate));

            this.rows = payload.items || [];
            this.attachmentUrl = payload.attachment || "";

            // Old browser drafts did not store the manual/automatic flag.
            if (payload.supplier_invoice_total_manual === undefined) {
                this.supplierInvoiceTotalManual = false;
                const systemTotal = flt(this.totals().estimatedGrand);
                const restoredTotal = flt(payload.supplier_invoice_total);
                this.supplierInvoiceTotalManual = restoredTotal > 0 && Math.abs(restoredTotal - systemTotal) > 0.005;
            }

            window.setTimeout(() => {
                this.supplierInvoiceTotalAutoUpdating = false;
                this.renderRows();
                this.refreshCards();
            }, 0);

            frappe.show_alert({ message: __("Unsaved purchase draft restored."), indicator: "green" }, 5);
        });
    }

    clearLocalDraft() {
        try { localStorage.removeItem(this.localDraftKey()); } catch (e) {}
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
            <table class="pimv1-recent"><thead><tr><th>${__("Invoice")}</th><th>${__("Supplier")}</th><th>${__("Supplier Bill")}</th><th>${__("Date")}</th><th>${__("Status")}</th><th>${__("Grand Total")}</th><th>${__("Outstanding")}</th><th>${__("Actions")}</th></tr></thead><tbody>
            ${invoices.map((row) => `<tr>
                <td><span class="pimv1-link" data-action="open-invoice" data-name="${this.escape(row.name)}">${this.escape(row.name)}</span></td>
                <td>${this.escape(row.supplier_name || row.supplier || "")}</td>
                <td>${this.escape(row.bill_no || "—")}</td>
                <td>${this.escape(row.posting_date || "")}</td>
                <td>${this.escape(row.status || (row.docstatus === 0 ? __("Draft") : ""))}</td>
                <td>${this.money(row.grand_total)}</td>
                <td>${this.money(row.outstanding_amount)}</td>
                <td><div class="pimv1-recent-actions">
                    ${cint(row.docstatus) === 0 ? `<button type="button" class="btn btn-xs btn-primary" data-action="load-draft" data-name="${this.escape(row.name)}">${__("Open in Page")}</button>` : ""}
                    ${cint(row.docstatus) === 1 && !cint(row.is_return) ? `<button type="button" class="btn btn-xs btn-warning" data-action="create-purchase-return" data-name="${this.escape(row.name)}">${__("Create Return")}</button>` : ""}
                    <button type="button" class="btn btn-xs btn-default" data-action="open-invoice" data-name="${this.escape(row.name)}">${__("Official Document")}</button>
                </div></td>
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
