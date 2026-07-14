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
        this.openDraftControls = {};
        this.recentControls = {};
        this.openProcurementDrafts = { drafts: [], counts: {}, total: 0 };
        this.draftName = null;
        this.attachmentUrl = "";
        this.lastSavedTotals = null;
        this.isSaving = false;
        this.activeRowIndex = null;
        this.recentPanelOpen = false;
        this.openDraftsPanelOpen = false;
        this.wideMode = false;
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
        this.procurementLinks = this.loadProcurementLinks();
        this.procurementMatchPreview = null;
        this.printIdentityCache = {};
        this.supplierSettlementContext = null;
        this.supplierSettlementLoading = false;

        this.addStyles();
        this.setupLayoutControls();
        this.page.set_primary_action(__("Save Draft"), () => this.saveDraft(), "save");
        this.page.add_inner_button(__("New Draft"), () => this.resetInvoice(), __("Invoice"));
        this.$openButton = this.page.add_inner_button(
            __("Open Official Document"),
            () => this.openOfficialDocument(),
            __("Invoice")
        );
        this.$openButton.prop("disabled", true);
        this.$loadPurchaseRequestButton = this.page.add_inner_button(
            __("Load Purchase Request"),
            () => this.openProcurementSourcePicker("purchase_request"),
            __("Procurement")
        );
        this.$loadPurchaseOrderButton = this.page.add_inner_button(
            __("Load Purchase Order"),
            () => this.openProcurementSourcePicker("purchase_order"),
            __("Procurement")
        );
        this.$loadPurchaseReceiptButton = this.page.add_inner_button(
            __("Load Purchase Receipt"),
            () => this.openProcurementSourcePicker("purchase_receipt"),
            __("Procurement")
        );
        this.$purchaseRequestButton = this.page.add_inner_button(
            __("Create Purchase Request Draft"),
            () => this.createPurchaseRequestDraft(),
            __("Procurement")
        );
        this.$purchaseOrderButton = this.page.add_inner_button(
            __("Create Purchase Order Draft"),
            () => this.createPurchaseOrderDraft(),
            __("Procurement")
        );
        this.$purchaseReceiptButton = this.page.add_inner_button(
            __("Create Purchase Receipt Draft"),
            () => this.createPurchaseReceiptDraft(),
            __("Procurement")
        );
        this.$purchaseInvoiceButton = this.page.add_inner_button(
            __("Create Purchase Invoice Draft"),
            () => this.createPurchaseInvoiceDraft(),
            __("Procurement")
        );
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
                .pimv1 { direction: rtl; text-align: right; padding: 0 0 38px; width: auto; min-width: 0; max-width: 100%; overflow-x: clip; }
                .pimv1, .pimv1 * { box-sizing: border-box; }
                .pimv1-layout-wide { flex: 1 1 0 !important; width: auto !important; min-width: 0 !important; max-width: 100% !important; }
                .pimv1-container-wide { width: auto !important; max-width: none !important; margin-left: 0 !important; margin-right: 0 !important; padding-left: 14px !important; padding-right: 14px !important; }
                .pimv1-main-wide { width: auto !important; min-width: 0 !important; max-width: 100% !important; }
                .pimv1-fullscreen-target:fullscreen { background: var(--bg-color); overflow: auto; padding: 10px; }
                .pimv1-fullscreen-target:fullscreen .layout-main-section-wrapper,
                .pimv1-fullscreen-target:fullscreen .layout-main-section { width: 100% !important; max-width: none !important; }
                .pimv1-hero {
                    display: flex; justify-content: space-between; align-items: flex-start; gap: 18px;
                    border: 1px solid var(--border-color); border-radius: 16px; padding: 16px 18px;
                    background: linear-gradient(135deg, var(--card-bg), var(--control-bg)); margin-bottom: 12px;
                }
                .pimv1-hero-copy { min-width: 240px; }
                .pimv1-hero h2 { margin: 0 0 6px; font-weight: 800; }
                .pimv1-hero p { margin: 0; color: var(--text-muted); max-width: 760px; }
                .pimv1-hero-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
                .pimv1-primary-actions, .pimv1-context-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
                .pimv1-primary-actions {
                    padding: 6px; border: 1px solid var(--border-color); border-radius: 12px;
                    background: var(--card-bg); box-shadow: 0 1px 3px rgba(0, 0, 0, .06);
                }
                .pimv1-primary-actions .btn {
                    min-width: 124px; min-height: 36px; padding: 7px 13px; border-radius: 8px;
                    font-weight: 800; font-size: 12px;
                }
                .pimv1-new-draft-btn {
                    background: var(--blue-100) !important; color: var(--blue-700) !important;
                    border-color: var(--border-color) !important;
                }
                .pimv1-save-draft-btn {
                    background: var(--control-bg) !important; color: var(--text-color) !important;
                    border: 1px solid var(--border-color) !important;
                }
                .pimv1-save-submit-btn { box-shadow: 0 1px 2px rgba(0, 0, 0, .16); }
                .pimv1-context-actions .btn { font-weight: 700; }
                .pimv1-settlement-section { padding: 13px 14px; }
                .pimv1-settlement-grid { display:grid; grid-template-columns:repeat(6,minmax(135px,1fr)); gap:9px; margin-top:10px; }
                .pimv1-settlement-card { border:1px solid var(--border-color); border-radius:12px; padding:10px 11px; background:var(--control-bg); min-width:0; }
                .pimv1-settlement-label { color:var(--text-muted); font-size:11px; }
                .pimv1-settlement-value { font-size:16px; font-weight:900; margin-top:4px; overflow-wrap:anywhere; }
                .pimv1-settlement-note { color:var(--text-muted); font-size:11px; margin-top:4px; line-height:1.4; }
                .pimv1-settlement-actions { display:flex; gap:7px; flex-wrap:wrap; margin-top:11px; }
                .pimv1-settlement-actions .btn { font-weight:800; }
                .pimv1-settlement-status { display:inline-flex; border-radius:999px; padding:4px 9px; background:#eef4ff; color:#175cd3; border:1px solid #b7ccff; font-size:11px; font-weight:900; }
                .pimv1-settlement-status.is-paid { background:#eaf7ee; color:#1f7a3f; border-color:#bde5c8; }
                .pimv1-settlement-status.is-attention { background:#fff7e6; color:#9a6500; border-color:#ffd591; }
                .pimv1-settlement-warning { margin-top:10px; padding:9px 11px; border-radius:10px; background:#fff7e6; border:1px solid #ffd591; color:#8a5a12; font-size:12px; line-height:1.5; }
                .pimv1-settlement-empty { padding:14px; border:1px dashed var(--border-color); border-radius:12px; background:var(--control-bg); color:var(--text-muted); }
                .pimv1-settlement-return-table { width:100%; border-collapse:collapse; font-size:12px; }
                .pimv1-settlement-return-table th,.pimv1-settlement-return-table td { padding:6px; border-bottom:1px solid var(--border-color); text-align:right; }
                @media(max-width:1150px){.pimv1-settlement-grid{grid-template-columns:repeat(3,minmax(150px,1fr));}}
                @media(max-width:700px){.pimv1-settlement-grid{grid-template-columns:1fr;}}
                .pimv1-doc-badge { border-radius: 999px; padding: 7px 12px; background: var(--blue-100); color: var(--blue-700); font-weight: 700; white-space: nowrap; }
                .pimv1-workflow-section { padding: 13px 14px; }
                .pimv1-workflow-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }
                .pimv1-workflow-step { border: 1px solid var(--border-color); border-radius: 12px; padding: 10px; background: var(--control-bg); min-width: 0; }
                .pimv1-workflow-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
                .pimv1-workflow-index { width: 25px; height: 25px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 25px; background: var(--blue-100); color: var(--blue-700); font-weight: 900; }
                .pimv1-workflow-title { font-weight: 900; line-height: 1.2; }
                .pimv1-workflow-note { color: var(--text-muted); font-size: 10px; margin-top: 2px; line-height: 1.35; }
                .pimv1-workflow-actions { display: flex; gap: 6px; flex-wrap: wrap; }
                .pimv1-workflow-actions .btn { flex: 1 1 92px; min-width: 0; font-weight: 700; }
                .pimv1-metrics { grid-template-columns: repeat(6, minmax(135px, 1fr)); margin-top: 12px; }
                .pimv1-metrics .pimv1-card { padding: 11px 12px; min-height: 78px; }
                .pimv1-metrics .pimv1-card-value { font-size: 18px; margin-top: 5px; }
                .pimv1-grid { display: grid; gap: 12px; }
                .pimv1-grid-4 { grid-template-columns: repeat(4, minmax(170px, 1fr)); }
                .pimv1-grid-3 { grid-template-columns: repeat(3, minmax(190px, 1fr)); }
                .pimv1-grid-2 { grid-template-columns: repeat(2, minmax(240px, 1fr)); }
                .pimv1-card, .pimv1-section { border: 1px solid var(--border-color); background: var(--card-bg); border-radius: 14px; }
                .pimv1-card { padding: 14px; min-height: 96px; }
                .pimv1-card-label { color: var(--text-muted); font-size: 12px; }
                .pimv1-card-value { font-size: 22px; font-weight: 800; margin-top: 8px; word-break: break-word; }
                .pimv1-card-note { color: var(--text-muted); font-size: 11px; margin-top: 5px; }
                .pimv1-match-docs { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
                .pimv1-match-doc { border: 1px solid var(--border-color); border-radius: 999px; padding: 6px 10px; background: var(--control-bg); font-size: 12px; }
                .pimv1-match-doc strong { margin-inline-start: 4px; }
                .pimv1-match-grid { display: grid; grid-template-columns: repeat(3, minmax(180px, 1fr)); gap: 10px; margin-top: 10px; }
                .pimv1-match-box { border: 1px solid var(--border-color); border-radius: 12px; padding: 10px; background: var(--card-bg); }
                .pimv1-match-label { color: var(--text-muted); font-size: 11px; }
                .pimv1-match-value { font-weight: 800; font-size: 16px; margin-top: 4px; }
                .pimv1-match-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }
                .pimv1-match-table th, .pimv1-match-table td { border-bottom: 1px solid var(--border-color); padding: 6px; text-align: right; }
                .pimv1-match-muted { color: var(--text-muted); }
                .pimv1-match-status { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 7px 12px; font-weight: 800; font-size: 12px; }
                .pimv1-status-matched { background: #eaf7ee; color: #1f7a3f; border: 1px solid #bde5c8; }
                .pimv1-status-planning { background: #eef4ff; color: #175cd3; border: 1px solid #b7ccff; }
                .pimv1-stage-summary { display: grid; grid-template-columns: repeat(4, minmax(190px, 1fr)); gap: 10px; margin-top: 12px; }
                .pimv1-stage-card { border: 1px solid var(--border-color); background: var(--card-bg); border-radius: 14px; padding: 11px 12px; min-height: 88px; }
                .pimv1-stage-title { color: var(--text-muted); font-size: 11px; margin-bottom: 6px; }
                .pimv1-stage-value { font-weight: 900; font-size: 14px; display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 4px 9px; }
                .pimv1-stage-note { color: var(--text-muted); font-size: 11px; line-height: 1.5; margin-top: 7px; }
                .pimv1-stage-open .pimv1-stage-value { background: #eef4ff; color: #175cd3; border: 1px solid #b7ccff; }
                .pimv1-stage-progress .pimv1-stage-value { background: #fff7e6; color: #9a6500; border: 1px solid #ffd591; }
                .pimv1-stage-done .pimv1-stage-value { background: #eaf7ee; color: #1f7a3f; border: 1px solid #bde5c8; }
                .pimv1-stage-attention .pimv1-stage-value { background: #fdeeee; color: #c92a2a; border: 1px solid #f3b6b6; }
                .pimv1-stage-muted .pimv1-stage-value { background: var(--control-bg); color: var(--text-muted); border: 1px solid var(--border-color); }
                @media (max-width: 1100px) { .pimv1-stage-summary { grid-template-columns: repeat(2, minmax(180px, 1fr)); } }
                @media (max-width: 700px) { .pimv1-stage-summary { grid-template-columns: 1fr; } }
                .pimv1-next-step-note { margin-top: 10px; padding: 10px 12px; border-radius: 12px; border: 1px solid var(--border-color); background: var(--control-bg); color: var(--text-color); line-height: 1.55; font-size: 12px; clear: both; }
                .pimv1-next-step-note strong { font-weight: 800; }
                .pimv1-next-step-muted { background: var(--control-bg); border-color: var(--border-color); }
                .pimv1-next-step-info { background: #eef4ff; border-color: #b7ccff; color: #175cd3; }
                .pimv1-next-step-warning { background: #fff9e6; border-color: #ffd591; color: #8a5a00; }
                .pimv1-next-step-danger { background: #fdeeee; border-color: #f3b6b6; color: #c92a2a; }
                .pimv1-next-step-success { background: #eaf7ee; border-color: #bde5c8; color: #1f7a3f; }
                .pimv1-status-warning { background: #fff7e6; color: #9a6500; border: 1px solid #ffd58a; }
                .pimv1-status-mismatch { background: #fdecec; color: #b42318; border: 1px solid #f5b5b0; }
                .pimv1-issues { margin-top: 10px; border: 1px solid var(--border-color); border-radius: 12px; overflow: hidden; }
                .pimv1-issue { display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px; border-bottom: 1px solid var(--border-color); background: var(--card-bg); }
                .pimv1-issue:last-child { border-bottom: 0; }
                .pimv1-issue-severity { font-weight: 800; min-width: 72px; }
                .pimv1-issue.warning .pimv1-issue-severity { color: #9a6500; }
                .pimv1-issue.mismatch .pimv1-issue-severity { color: #b42318; }
                .pimv1-row-status { font-weight: 800; border-radius: 999px; padding: 3px 8px; font-size: 11px; white-space: nowrap; }
                .pimv1-stock-recheck { display:block; margin-top:4px; font-size:11px; font-weight:700; }
                .pimv1-stock-recheck.covered { color:#1f7a3f; }
                .pimv1-stock-recheck.partial { color:#9a6500; }
                .pimv1-source-context { border: 1px solid #b7ccff; background: #eef4ff; color: #175cd3; border-radius: 12px; padding: 10px 12px; margin: 12px 0; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
                .pimv1-source-context .pimv1-source-pill { border: 1px solid #b7ccff; background: var(--card-bg); border-radius: 999px; padding: 4px 9px; font-weight: 700; }
                .pimv1-match-details { margin-top: 10px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--control-bg); overflow: hidden; }
                .pimv1-match-details > summary { cursor: pointer; padding: 10px 12px; font-weight: 800; list-style-position: inside; user-select: none; }
                .pimv1-match-details[open] > summary { border-bottom: 1px solid var(--border-color); background: var(--subtle-fg); }
                .pimv1-match-details-body { padding: 0 12px 12px; }
                .pimv1-match-table-wrap { width: 100%; overflow-x: auto; }
                .pimv1-match-table { min-width: 1040px; }
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
                .pimv1-open-drafts-section { margin-bottom: 12px; }
                .pimv1-open-drafts-panel { display: none; margin-top: 14px; }
                .pimv1-open-drafts-panel.is-open { display: block; }
                .pimv1-open-drafts-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
                .pimv1-open-drafts-summary { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 8px; margin-bottom: 12px; }
                .pimv1-open-draft-count { border: 1px solid var(--border-color); border-radius: 11px; padding: 9px 11px; background: var(--control-bg); display: flex; justify-content: space-between; align-items: center; gap: 8px; }
                .pimv1-open-draft-count strong { font-size: 18px; font-weight: 900; }
                .pimv1-open-draft-count span { color: var(--text-muted); font-size: 11px; font-weight: 700; }
                .pimv1-open-drafts-filters { display: grid; grid-template-columns: minmax(165px, .75fr) minmax(175px, .8fr) minmax(220px, 1fr) minmax(190px, .9fr) auto; gap: 10px; align-items: end; padding: 11px; border: 1px solid var(--border-color); border-radius: 11px; background: var(--control-bg); }
                .pimv1-open-drafts-filter-actions { display: flex; align-items: center; gap: 7px; padding-bottom: 4px; flex-wrap: wrap; }
                .pimv1-open-drafts-status { color: var(--text-muted); font-size: 11px; margin-top: 8px; }
                .pimv1-open-drafts-results { margin-top: 10px; overflow: auto; max-height: 380px; border: 1px solid var(--border-color); border-radius: 10px; }
                .pimv1-open-drafts-table { width: 100%; border-collapse: collapse; min-width: 1280px; }
                .pimv1-open-drafts-table th, .pimv1-open-drafts-table td { padding: 9px; border-bottom: 1px solid var(--border-color); text-align: right; vertical-align: middle; }
                .pimv1-open-drafts-table th { color: var(--text-muted); font-size: 11px; white-space: nowrap; position: sticky; top: 0; background: var(--card-bg); z-index: 1; }
                .pimv1-open-draft-stage { display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 9px; font-size: 11px; font-weight: 900; border: 1px solid var(--border-color); }
                .pimv1-open-draft-stage.purchase_request { background: var(--blue-100); color: var(--blue-700); }
                .pimv1-open-draft-stage.purchase_order { background: var(--yellow-100); color: var(--yellow-700); }
                .pimv1-open-draft-stage.purchase_receipt { background: var(--green-100); color: var(--green-700); }
                .pimv1-open-draft-stage.purchase_invoice { background: var(--purple-100); color: var(--purple-700); }
                .pimv1-open-draft-age { display: inline-flex; border-radius: 999px; padding: 3px 7px; font-size: 10px; font-weight: 800; background: var(--control-bg); border: 1px solid var(--border-color); }
                .pimv1-open-draft-age.stale { background: var(--orange-100); color: var(--orange-700); }
                .pimv1-open-draft-progress { display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 8px; font-size: 10px; font-weight: 900; border: 1px solid var(--border-color); white-space: nowrap; }
                .pimv1-open-draft-progress.open { background: var(--blue-100); color: var(--blue-700); }
                .pimv1-open-draft-progress.partial { background: var(--yellow-100); color: var(--yellow-700); }
                .pimv1-open-draft-progress.done { background: var(--green-100); color: var(--green-700); }
                .pimv1-open-draft-chain { font-size: 11px; line-height: 1.55; min-width: 180px; }
                .pimv1-open-draft-chain strong { color: var(--text-color); }
                .pimv1-open-draft-actions { display: flex; gap: 6px; flex-wrap: wrap; min-width: 210px; }
                .pimv1-open-draft-next { font-weight: 800; }
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

                /* v0.7.61.1 corrective responsive layout containment */
                .pimv1-fullscreen-target,
                .pimv1-fullscreen-target .page-body,
                .pimv1-fullscreen-target .page-content,
                .pimv1-fullscreen-target .layout-main,
                .pimv1-fullscreen-target .layout-main-section-wrapper,
                .pimv1-fullscreen-target .layout-main-section,
                .pimv1-fullscreen-target .container,
                .pimv1 {
                    min-width: 0 !important;
                }
                .pimv1-fullscreen-target,
                .pimv1-fullscreen-target .page-body,
                .pimv1-fullscreen-target .page-content {
                    max-width: 100% !important;
                    overflow-x: clip !important;
                }
                .pimv1-fullscreen-target .layout-main,
                .pimv1-fullscreen-target .layout-main-section-wrapper,
                .pimv1-fullscreen-target .layout-main-section {
                    max-width: 100% !important;
                }
                .pimv1-layout-wide {
                    flex: 1 1 0 !important;
                    width: auto !important;
                    min-width: 0 !important;
                    max-width: 100% !important;
                }
                .pimv1-container-wide {
                    width: auto !important;
                    max-width: none !important;
                    margin-inline: 0 !important;
                    padding-inline: 14px !important;
                }
                .pimv1-main-wide {
                    width: auto !important;
                    min-width: 0 !important;
                    max-width: 100% !important;
                }
                .pimv1 > *,
                .pimv1-grid,
                .pimv1-section,
                .pimv1-card,
                .pimv1-hero,
                .pimv1-hero-copy,
                .pimv1-hero-actions,
                .pimv1-workflow-section,
                .pimv1-workflow-grid,
                .pimv1-workflow-step,
                .pimv1-section-title,
                .pimv1-section-title > *,
                .pimv1-match-content,
                .pimv1-match-docs,
                .pimv1-stage-summary,
                .pimv1-open-drafts-section,
                .pimv1-open-drafts-panel,
                .pimv1-open-drafts-toolbar,
                .pimv1-open-drafts-summary,
                .pimv1-open-drafts-filters,
                .pimv1-open-drafts-filters > *,
                .pimv1-recent-panel,
                .pimv1-recent-filters,
                .pimv1-summary,
                .pimv1-summary > * {
                    min-width: 0;
                    max-width: 100%;
                }
                .pimv1 > *,
                .pimv1-section,
                .pimv1-workflow-section,
                .pimv1-hero {
                    width: auto;
                }
                .pimv1-hero-copy {
                    min-width: 0;
                    flex: 1 1 360px;
                }
                .pimv1-hero-actions {
                    min-width: 0;
                    flex: 1 1 520px;
                }
                .pimv1-grid-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
                .pimv1-grid-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
                .pimv1-grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                .pimv1 h2,
                .pimv1 h4,
                .pimv1 p,
                .pimv1 .text-muted,
                .pimv1-help,
                .pimv1-workflow-note,
                .pimv1-stage-note,
                .pimv1-next-step-note,
                .pimv1-summary-row,
                .pimv1-validation-panel {
                    overflow-wrap: anywhere;
                    word-break: normal;
                }
                .pimv1-summary-row {
                    flex-wrap: wrap;
                }
                .pimv1-match-docs {
                    width: 100%;
                    align-items: stretch;
                }
                .pimv1-match-doc {
                    min-width: 0;
                    max-width: 100%;
                    white-space: normal;
                    overflow-wrap: anywhere;
                    line-height: 1.35;
                }
                .pimv1-match-details,
                .pimv1-match-table-wrap,
                .pimv1-table-wrap,
                .pimv1-open-drafts-results,
                .pimv1-recent-results,
                .pimv1-history {
                    width: auto;
                    max-width: 100%;
                    min-width: 0;
                    overflow-x: auto !important;
                    overscroll-behavior-inline: contain;
                    scrollbar-gutter: stable;
                }
                .pimv1-table-wrap { overflow-y: hidden; }
                .pimv1-items-list { min-width: 1180px; }
                .pimv1-open-drafts-results { overflow-y: auto !important; }
                .pimv1-open-drafts-table {
                    width: max-content;
                    min-width: max(100%, 1280px);
                }
                .pimv1-open-drafts-table th,
                .pimv1-open-drafts-table td { max-width: 260px; }
                .pimv1-open-draft-chain,
                .pimv1-open-draft-actions { min-width: 0; }
                .pimv1-open-draft-actions .btn { white-space: normal; }
                .pimv1-collapsible-title > div {
                    min-width: 0;
                    max-width: 100%;
                }
                .pimv1-collapsible-meta {
                    flex: 0 0 auto;
                    white-space: nowrap;
                }
                .pimv1-print-preview-shell { direction: rtl; text-align: right; color: var(--text-color); background: var(--card-bg); padding: 14px; border: 1px solid var(--border-color); border-radius: 12px; max-height: 68vh; overflow: auto; }
                .pimv1-print-identity { display: flex; align-items: center; gap: 12px; padding-bottom: 10px; margin-bottom: 12px; border-bottom: 1px solid var(--border-color); }
                .pimv1-print-identity img { width: 80px; max-height: 64px; object-fit: contain; }
                .pimv1-print-title { font-size: 19px; font-weight: 900; margin: 0 0 3px; }
                .pimv1-print-subtitle { color: var(--text-muted); font-size: 11px; }
                .pimv1-print-meta, .pimv1-print-totals { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; margin: 10px 0; }
                .pimv1-print-box { border: 1px solid var(--border-color); border-radius: 8px; padding: 8px; min-width: 0; }
                .pimv1-print-box b { display: block; color: var(--text-muted); font-size: 10px; margin-bottom: 3px; }
                .pimv1-print-stage-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; margin: 10px 0; }
                .pimv1-print-stage { border: 1px solid var(--border-color); border-radius: 8px; padding: 8px; min-width: 0; }
                .pimv1-print-stage h5 { margin: 0 0 5px; font-weight: 900; }
                .pimv1-print-table { width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 8px; }
                .pimv1-print-table th, .pimv1-print-table td { border: 1px solid var(--border-color); padding: 6px; text-align: right; vertical-align: top; }
                .pimv1-print-table th { background: var(--control-bg); white-space: nowrap; }
                .pimv1-print-status { display: inline-flex; padding: 3px 7px; border-radius: 999px; font-size: 10px; font-weight: 900; border: 1px solid var(--border-color); }
                .pimv1-print-status.matched, .pimv1-print-status.done { background: var(--green-100); color: var(--green-700); }
                .pimv1-print-status.warning, .pimv1-print-status.partial { background: var(--yellow-100); color: var(--yellow-700); }
                .pimv1-print-status.mismatch, .pimv1-print-status.cancelled { background: var(--red-100); color: var(--red-700); }
                .pimv1-print-status.direct, .pimv1-print-status.open { background: var(--blue-100); color: var(--blue-700); }
                .pimv1-print-section { margin-top: 12px; }
                .pimv1-print-section h4 { margin: 0 0 6px; font-weight: 900; }
                .pimv1-print-warning { border: 1px solid var(--yellow-300); background: var(--yellow-50); border-radius: 8px; padding: 9px; margin-top: 8px; }
                @media (max-width: 980px) {
                    .pimv1-print-meta, .pimv1-print-totals, .pimv1-print-stage-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                }
                @media (max-width: 1450px) {
                    .pimv1-hero { align-items: flex-start; }
                    .pimv1-open-drafts-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
                    .pimv1-open-drafts-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                    .pimv1-open-drafts-filter-actions { grid-column: 1 / -1; }
                }
                @media (max-width: 980px) {
                    .pimv1-section,
                    .pimv1-workflow-section { padding: 12px; }
                    .pimv1-section-title {
                        align-items: flex-start;
                        flex-direction: column;
                    }
                    .pimv1-section-title .pimv1-actions { width: 100%; }
                    .pimv1-barcode {
                        flex: 1 1 240px;
                        min-width: 0;
                    }
                    .pimv1-match-doc { flex: 1 1 220px; }
                }
                @media (max-width: 760px) {
                    .pimv1-container-wide { padding-inline: 8px !important; }
                    .pimv1-collapsible-title { align-items: flex-start; }
                    .pimv1-collapsible-meta { white-space: normal; }
                    .pimv1-open-drafts-summary { grid-template-columns: 1fr 1fr; }
                    .pimv1-match-doc { flex-basis: 100%; }
                }

                @media (max-width: 1250px) {
                    .pimv1-metrics { grid-template-columns: repeat(3, minmax(150px, 1fr)); }
                    .pimv1-workflow-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                }
                @media (max-width: 1100px) {
                    .pimv1-grid-4, .pimv1-grid-3 { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
                    .pimv1-summary { grid-template-columns: 1fr; }
                    .pimv1-open-drafts-summary { grid-template-columns: repeat(3, minmax(120px, 1fr)); }
                    .pimv1-open-drafts-filters { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
                    .pimv1-recent-filters { grid-template-columns: repeat(2, minmax(180px, 1fr)); }
                }
                @media (max-width: 760px) {
                    .pimv1-hero { align-items: flex-start; flex-direction: column; }
                    .pimv1-hero-actions { width: 100%; justify-content: flex-start; }
                    .pimv1-primary-actions { width: 100%; }
                    .pimv1-primary-actions .btn { flex: 1 1 145px; }
                    .pimv1-workflow-grid, .pimv1-metrics { grid-template-columns: 1fr; }
                    .pimv1-grid-4, .pimv1-grid-3, .pimv1-grid-2 { grid-template-columns: 1fr; }
                    .pimv1-barcode { min-width: 100%; }
                    .pimv1-open-drafts-summary { grid-template-columns: repeat(2, minmax(110px, 1fr)); }
                    .pimv1-open-drafts-filters { grid-template-columns: 1fr; }
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
                    <div class="pimv1-hero-copy">
                        <h2>${__("Purchase & Invoice Management")}</h2>
                        <p>${__("Create purchase drafts in a clear four-step flow, then review and submit the supplier invoice from the same page.")}</p>
                    </div>
                    <div class="pimv1-hero-actions">
                        <div class="pimv1-doc-badge" data-role="draft-badge">${__("Unsaved Invoice")}</div>
                        <div class="pimv1-context-actions">
                            <button type="button" class="btn btn-default btn-sm" data-action="supplier-running-account">${__("Supplier Account")}</button>
                            <button type="button" class="btn btn-default btn-sm" data-action="returns-management">${__("Returns")}</button>
                            <button type="button" class="btn btn-default btn-sm" data-action="preview-procurement-summary">${__("Summary / Print")}</button>
                        </div>
                        <div class="pimv1-primary-actions" aria-label="${__("Invoice Actions")}">
                            <button type="button" class="btn btn-default btn-sm pimv1-new-draft-btn" data-action="page-new-draft">＋ ${__("New Draft")}</button>
                            <button type="button" class="btn btn-default btn-sm pimv1-save-draft-btn" data-action="page-save-draft">${__("Save Draft")}</button>
                            <button type="button" class="btn btn-primary btn-sm pimv1-save-submit-btn" data-action="page-save-submit">${__("Save & Submit")}</button>
                        </div>
                    </div>
                </div>

                <div class="pimv1-section pimv1-workflow-section">
                    <div class="pimv1-section-title">
                        <h4>${__("Procurement Workflow")}</h4>
                        <span class="text-muted">${__("Drafts are created in the background without opening another page.")}</span>
                    </div>
                    <div class="pimv1-workflow-grid">
                        <div class="pimv1-workflow-step">
                            <div class="pimv1-workflow-head">
                                <span class="pimv1-workflow-index">1</span>
                                <div><div class="pimv1-workflow-title">${__("Request")}</div><div class="pimv1-workflow-note">${__("Shortage list before selecting the supplier")}</div></div>
                            </div>
                            <div class="pimv1-workflow-actions">
                                <button type="button" class="btn btn-default btn-sm" data-action="load-purchase-request">${__("Load")}</button>
                                <button type="button" class="btn btn-default btn-sm" data-action="create-purchase-request-draft">${__("Create Draft")}</button>
                            </div>
                        </div>
                        <div class="pimv1-workflow-step">
                            <div class="pimv1-workflow-head">
                                <span class="pimv1-workflow-index">2</span>
                                <div><div class="pimv1-workflow-title">${__("Order")}</div><div class="pimv1-workflow-note">${__("Supplier and quantities actually ordered")}</div></div>
                            </div>
                            <div class="pimv1-workflow-actions">
                                <button type="button" class="btn btn-default btn-sm" data-action="load-purchase-order">${__("Load")}</button>
                                <button type="button" class="btn btn-default btn-sm" data-action="create-purchase-order-draft">${__("Create Draft")}</button>
                            </div>
                        </div>
                        <div class="pimv1-workflow-step">
                            <div class="pimv1-workflow-head">
                                <span class="pimv1-workflow-index">3</span>
                                <div><div class="pimv1-workflow-title">${__("Receipt")}</div><div class="pimv1-workflow-note">${__("What physically arrived from the supplier")}</div></div>
                            </div>
                            <div class="pimv1-workflow-actions">
                                <button type="button" class="btn btn-default btn-sm" data-action="load-purchase-receipt">${__("Load")}</button>
                                <button type="button" class="btn btn-default btn-sm" data-action="create-purchase-receipt-draft">${__("Create Draft")}</button>
                            </div>
                        </div>
                        <div class="pimv1-workflow-step">
                            <div class="pimv1-workflow-head">
                                <span class="pimv1-workflow-index">4</span>
                                <div><div class="pimv1-workflow-title">${__("Invoice")}</div><div class="pimv1-workflow-note">${__("Supplier invoice and final submit guard")}</div></div>
                            </div>
                            <div class="pimv1-workflow-actions">
                                <button type="button" class="btn btn-primary btn-sm" data-action="create-purchase-invoice-draft">${__("Create Invoice Draft")}</button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="pimv1-section pimv1-open-drafts-section" data-role="open-procurement-drafts-section">
                    <button type="button" class="pimv1-collapsible-title" data-action="toggle-open-drafts">
                        <div>
                            <h4>${__("Procurement Drafts Review")}</h4>
                            <span class="text-muted">${__("Hidden by default for normal invoice entry. Open it only when you need to review or continue the four-stage procurement cycle.")}</span>
                        </div>
                        <span class="pimv1-collapsible-meta"><span data-role="open-drafts-count">${Number((this.bootstrap.open_procurement_drafts || {}).total || 0)}</span> ${__("active drafts")} <span class="pimv1-collapsible-icon">⌄</span></span>
                    </button>
                    <div class="pimv1-open-drafts-panel" data-role="open-drafts-panel">
                        <div class="pimv1-open-drafts-toolbar">
                            <span class="text-muted">${__("Review operational progress, reopen linked stages and continue only the drafts that still have remaining quantities.")}</span>
                            <button type="button" class="btn btn-default btn-sm" data-action="refresh-open-drafts">${__("Refresh Drafts")}</button>
                        </div>
                        <div class="pimv1-open-drafts-summary" data-role="open-drafts-summary"></div>
                        <div class="pimv1-open-drafts-filters">
                            <div class="pimv1-field" data-open-draft-field="stage"></div>
                            <div class="pimv1-field" data-open-draft-field="progress_status"></div>
                            <div class="pimv1-field" data-open-draft-field="supplier"></div>
                            <div class="pimv1-field" data-open-draft-field="search_text"></div>
                            <div class="pimv1-open-drafts-filter-actions">
                                <button type="button" class="btn btn-primary btn-sm" data-action="search-open-drafts">${__("Apply Filters")}</button>
                                <button type="button" class="btn btn-default btn-sm" data-action="clear-open-drafts">${__("Clear")}</button>
                            </div>
                        </div>
                        <div class="pimv1-open-drafts-status" data-role="open-drafts-status">${__("Showing active stages by default. Use Operational Status to include completed stages.")}</div>
                        <div class="pimv1-open-drafts-results" data-role="open-drafts-results"></div>
                    </div>
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

                <div class="pimv1-grid pimv1-metrics">
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Supplier Balance")}</div><div class="pimv1-card-value" data-role="supplier-balance">—</div><div class="pimv1-card-note" data-role="supplier-type">${__("Select supplier")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Items")}</div><div class="pimv1-card-value" data-role="items-count">0</div><div class="pimv1-card-note" data-role="bonus-count">${__("Bonus lines: 0")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Estimated Net Before Added Tax")}</div><div class="pimv1-card-value" data-role="estimated-net">0.00</div><div class="pimv1-card-note">${__("After discounts")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Estimated VAT / Tax")}</div><div class="pimv1-card-value" data-role="estimated-tax">0.00</div><div class="pimv1-card-note" data-role="estimated-tax-note">${__("Live estimate")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Estimated Grand Total")}</div><div class="pimv1-card-value" data-role="estimated-grand">0.00</div><div class="pimv1-card-note">${__("Before final ERP confirmation")}</div></div>
                    <div class="pimv1-card"><div class="pimv1-card-label">${__("Saved Tax / Grand Total")}</div><div class="pimv1-card-value" data-role="saved-grand">—</div><div class="pimv1-card-note" data-role="saved-status">${__("Not saved yet")}</div></div>
                </div>

                <div class="pimv1-section" data-role="procurement-match-preview">
                    <div class="pimv1-section-title">
                        <div><h4>${__("Procurement Match Preview")}</h4><span class="text-muted">${__("Next Step and stage status stay visible; detailed quantities are collapsed by default.")}</span></div>
                        <div class="pimv1-actions">
                            <button type="button" class="btn btn-default btn-sm" data-action="preview-procurement-summary">${__("Preview / Print")}</button>
                            <button type="button" class="btn btn-default btn-sm" data-action="refresh-procurement-match">${__("Refresh Match")}</button>
                            <button type="button" class="btn btn-default btn-sm" data-action="clear-procurement-links">${__("Clear Links")}</button>
                        </div>
                    </div>
                    <div class="pimv1-match-content" data-role="procurement-match-content"></div>
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

                <div class="pimv1-section pimv1-settlement-section">
                    <div class="pimv1-section-title">
                        <div>
                            <h4>${__("Supplier Settlement")}</h4>
                            <span class="text-muted">${__("Use the established Supplier Running Account rules without duplicating payment or claim accounting logic.")}</span>
                        </div>
                        <button type="button" class="btn btn-default btn-sm" data-action="refresh-supplier-settlement">${__("Refresh Settlement")}</button>
                    </div>
                    <div data-role="supplier-settlement"></div>
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

        this.openProcurementDrafts = this.bootstrap.open_procurement_drafts || { drafts: [], counts: {}, total: 0 };
        this.makeControls();
        this.makeOpenDraftControls();
        this.makeRecentControls();
        this.bindEvents();
        this.applyWideMode(this.wideMode);
        this.renderShortcutHint();
        this.renderRows();
        this.renderOpenProcurementDrafts(this.openProcurementDrafts);
        this.renderRecentInvoices(this.bootstrap.recent_invoices || []);
        this.refreshCards();
        this.renderSupplierSettlement();
        this.renderProcurementMatchPreview();
        this.fetchProcurementMatchPreview();
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

    makeOpenDraftControl(fieldname, df, value) {
        const parent = this.$main.find(`[data-open-draft-field="${fieldname}"]`).get(0);
        const control = frappe.ui.form.make_control({
            parent,
            df: { fieldname: `open_draft_${fieldname}`, ...df },
            render_input: true,
        });
        if (value !== undefined && value !== null) control.set_value(value);
        this.openDraftControls[fieldname] = control;
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
            label: __("Settlement Classification"), fieldtype: "Select",
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

    makeOpenDraftControls() {
        this.makeOpenDraftControl("stage", {
            label: __("Stage"), fieldtype: "Select",
            options: `
purchase_request
purchase_order
purchase_receipt
purchase_invoice`,
        }, "");
        this.makeOpenDraftControl("progress_status", {
            label: __("Operational Status"), fieldtype: "Select",
            options: `active
open
partial
done
all`,
        }, "active");
        this.makeOpenDraftControl("supplier", { label: __("Supplier"), fieldtype: "Link", options: "Supplier" }, "");
        this.makeOpenDraftControl("search_text", { label: __("Document No"), fieldtype: "Data", placeholder: __("Search by document number") }, "");
        const progressControl = this.openDraftControls.progress_status;
        if (progressControl && progressControl.$input) {
            progressControl.$input.find('option[value="active"]').text(__("Active Only (Open + Partial)"));
            progressControl.$input.find('option[value="open"]').text(__("Open Only"));
            progressControl.$input.find('option[value="partial"]').text(__("Partial Only"));
            progressControl.$input.find('option[value="done"]').text(__("Done / Continued"));
            progressControl.$input.find('option[value="all"]').text(__("All Statuses"));
        }
        const stageControl = this.openDraftControls.stage;
        if (stageControl && stageControl.$input) {
            stageControl.$input.find('option[value=""]').text(__("All Stages"));
            stageControl.$input.find('option[value="purchase_request"]').text(__("Request"));
            stageControl.$input.find('option[value="purchase_order"]').text(__("Order"));
            stageControl.$input.find('option[value="purchase_receipt"]').text(__("Receipt"));
            stageControl.$input.find('option[value="purchase_invoice"]').text(__("Invoice"));
        }
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
        this.$main.on("click.pimv1", "[data-action='page-new-draft']", () => this.resetInvoice());
        this.$main.on("click.pimv1", "[data-action='page-save-draft']", () => this.saveDraft());
        this.$main.on("click.pimv1", "[data-action='page-save-submit']", () => this.saveAndSubmit());
        this.$main.on("click.pimv1", "[data-action='supplier-running-account']", () => this.openSupplierRunningAccount());
        this.$main.on("click.pimv1", "[data-action='refresh-supplier-settlement']", () => this.refreshSupplierSettlement());
        this.$main.on("click.pimv1", "[data-action='create-settlement-payment']", () => this.openSettlementPaymentDraftDialog());
        this.$main.on("click.pimv1", "[data-action='create-settlement-claim']", () => this.openSettlementClaimDraftDialog());
        this.$main.on("click.pimv1", "[data-action='use-settlement-advance']", () => this.openSettlementAdvanceDialog());
        this.$main.on("click.pimv1", "[data-action='open-linked-supplier-claim']", (event) => {
            const name = $(event.currentTarget).data("name");
            if (name) frappe.set_route("Form", "Supplier Claim", name);
        });
        this.$main.on("click.pimv1", "[data-action='returns-management']", () => this.openReturnsManagement());
        this.$main.on("click.pimv1", "[data-action='preview-procurement-summary']", (event) => {
            const invoiceName = $(event.currentTarget).data("name") || this.draftName || "";
            this.openProcurementSummaryPreview(invoiceName);
        });
        this.$main.on("click.pimv1", "[data-action='load-purchase-request']", () => this.openProcurementSourcePicker("purchase_request"));
        this.$main.on("click.pimv1", "[data-action='load-purchase-order']", () => this.openProcurementSourcePicker("purchase_order"));
        this.$main.on("click.pimv1", "[data-action='load-purchase-receipt']", () => this.openProcurementSourcePicker("purchase_receipt"));
        this.$main.on("click.pimv1", "[data-action='create-purchase-request-draft']", () => this.createPurchaseRequestDraft());
        this.$main.on("click.pimv1", "[data-action='create-purchase-order-draft']", () => this.createPurchaseOrderDraft());
        this.$main.on("click.pimv1", "[data-action='create-purchase-receipt-draft']", () => this.createPurchaseReceiptDraft());
        this.$main.on("click.pimv1", "[data-action='create-purchase-invoice-draft']", () => this.createPurchaseInvoiceDraft());
        this.$main.on("click.pimv1", "[data-action='refresh-procurement-match']", () => this.fetchProcurementMatchPreview(true));
        this.$main.on("click.pimv1", "[data-action='clear-procurement-links']", () => this.clearProcurementLinks());
        this.$main.on("click.pimv1", "[data-action='open-procurement-doc']", (event) => this.openLinkedProcurementDoc(event));
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
        this.$main.on("click.pimv1", "[data-action='toggle-open-drafts']", () => this.toggleOpenDraftsPanel());
        this.$main.on("click.pimv1", "[data-action='refresh-open-drafts']", () => this.refreshOpenProcurementDrafts());
        this.$main.on("click.pimv1", "[data-action='search-open-drafts']", () => this.refreshOpenProcurementDrafts());
        this.$main.on("click.pimv1", "[data-action='clear-open-drafts']", () => this.clearOpenProcurementDraftFilters());
        this.$main.on("click.pimv1", "[data-action='continue-open-draft']", (event) => this.continueOpenProcurementDraft(event));
        this.$main.on("click.pimv1", "[data-action='open-procurement-official']", (event) => {
            const doctype = $(event.currentTarget).data("doctype");
            const name = $(event.currentTarget).data("name");
            if (doctype && name) frappe.set_route("Form", doctype, name);
        });
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
            } else {
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
            // v0.7.61.2: manual VAT amounts still need one ERP tax-account template.
            // Resolve it automatically when the company has one unambiguous template;
            // the entered VAT Per Unit / Total VAT remains the source of the amount.
            if(values.tax_entry_mode!=="No VAT"&&!values.item_tax_template){
                const resolvedTemplate=this.resolveTaxTemplateForRow(values,context);
                if(!resolvedTemplate){
                    frappe.msgprint({
                        title:__("Select VAT Account Template"),
                        message:__("Select an Item Tax Template to identify the VAT account. The manual VAT amount will not be recalculated."),
                        indicator:"orange"
                    });
                    return;
                }
                values.item_tax_template=resolvedTemplate;
            }
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
            // v0.7.61.2 bonus VAT uses the inherited VAT Per Unit.
            // Total VAT for Line belongs to the purchased row and must never be copied
            // as the bonus row total. The bonus row unit cost is the already-calculated
            // VAT Per Unit from the purchased row.
            if(mode==="VAT Per Unit"||mode==="Total VAT for Line") vatPerUnit=Math.max(0,flt(values.vat_per_unit));
            else if(mode==="Auto by VAT %") vatPerUnit=taxableBase*vatRate/100;
            const totalVat=vatPerUnit*qty;
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

    resolveTaxTemplateForRow(row = {}, context = {}) {
        const current = row.item_tax_template || context.default_item_tax_template || "";
        if (current) return current;
        const mode = row.tax_entry_mode || "No VAT";
        if (mode === "No VAT") return "";

        const templates = (this.bootstrap.item_tax_templates || []).filter((entry) => entry && entry.name);
        const targetRate = Math.max(0, flt(row.vat_rate || context.default_item_tax_rate));
        if (targetRate > 0) {
            const matching = templates.filter((entry) => Math.abs(flt(entry.rate) - targetRate) < 0.0001);
            if (matching.length === 1) return matching[0].name;
        }

        // v0.7.61.2: manual VAT prefers the uniquely VAT-labelled account template.
        // Manual amounts can be invoice-specific and therefore must not be forced
        // to equal the configured percentage. The template only identifies the
        // accounting VAT account; VAT Per Unit / Total VAT for Line stay unchanged.
        const isManual = mode === "VAT Per Unit" || mode === "Total VAT for Line";
        const hasManualAmount = flt(row.vat_per_unit) > 0 || flt(row.total_vat) > 0;
        if (isManual && hasManualAmount) {
            const vatLabel = /(^|[^a-z])vat([^a-z]|$)|value\s*added|ضريبة\s*القيمة/i;
            const labelled = templates.filter((entry) => {
                const accounts = Array.isArray(entry.tax_accounts) ? entry.tax_accounts : [];
                return vatLabel.test([entry.name, ...accounts].join(" "));
            });
            if (labelled.length === 1) return labelled[0].name;
        }

        return templates.length === 1 ? templates[0].name : "";
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
            this.supplierContext.supplier_settlement_policy || this.supplierContext.custom_purchase_payment_model,
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
        if (!this.value("payment_classification")) errors.push({ message: __("Settlement Classification is required."), field: "payment_classification" });
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
            if (!cint(row.is_bonus) && row.tax_entry_mode !== "No VAT" && !row.item_tax_template) {
                const resolvedTemplate = this.resolveTaxTemplateForRow(row);
                if (resolvedTemplate) row.item_tax_template = resolvedTemplate;
                else errors.push({ message: __("Select an Item Tax Template to identify the VAT account on taxable row {0}. Manual VAT values will remain unchanged.", [index + 1]), row:index });
            }
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


    procurementStorageKey() {
        return "pharma_erp_purchase_management_procurement_links_v0_7_51";
    }

    loadProcurementLinks() {
        try {
            const raw = window.localStorage.getItem(this.procurementStorageKey());
            return raw ? JSON.parse(raw) || {} : {};
        } catch (error) {
            console.warn("Unable to load procurement links", error);
            return {};
        }
    }

    saveProcurementLinks() {
        try {
            window.localStorage.setItem(this.procurementStorageKey(), JSON.stringify(this.procurementLinks || {}));
        } catch (error) {
            console.warn("Unable to save procurement links", error);
        }
    }

    recordProcurementLink(kind, document) {
        if (!document || !document.name) return;
        const mapping = {
            purchase_request: "purchase_request",
            purchase_order: "purchase_order",
            purchase_receipt: "purchase_receipt",
            purchase_invoice: "purchase_invoice",
        };
        const key = mapping[kind];
        if (!key) return;
        this.procurementLinks = this.procurementLinks || {};
        this.procurementLinks[key] = document.name;
        this.procurementLinks[`${key}_doctype`] = document.doctype;
        this.procurementLinks.updated_at = frappe.datetime.now_datetime();
        this.saveProcurementLinks();
        this.renderProcurementMatchPreview();
    }

    applyProcurementChain(linkedDocuments, options = {}) {
        const replace = options.replace !== false;
        const nextLinks = replace ? {} : { ...(this.procurementLinks || {}) };
        const doctypes = {
            purchase_request: "Material Request",
            purchase_order: "Purchase Order",
            purchase_receipt: "Purchase Receipt",
            purchase_invoice: "Purchase Invoice",
        };
        ["purchase_request", "purchase_order", "purchase_receipt", "purchase_invoice"].forEach((key) => {
            const document = linkedDocuments && linkedDocuments[key];
            if (!document || !document.name) return;
            nextLinks[key] = document.name;
            nextLinks[`${key}_doctype`] = document.doctype || doctypes[key];
        });
        nextLinks.updated_at = frappe.datetime.now_datetime();
        this.procurementLinks = nextLinks;
        this.procurementMatchPreview = null;
        this.saveProcurementLinks();
        this.renderProcurementMatchPreview();
    }

    clearProcurementLinks() {
        this.procurementLinks = {};
        this.procurementMatchPreview = null;
        this.saveProcurementLinks();
        this.renderProcurementMatchPreview();
        frappe.show_alert({ message: __("Procurement links cleared."), indicator: "green" }, 4);
    }

    openLinkedProcurementDoc(event) {
        const doctype = $(event.currentTarget).data("doctype");
        const name = $(event.currentTarget).data("name");
        if (doctype && name) frappe.set_route("Form", doctype, name);
    }

    async fetchProcurementMatchPreview(showAlert) {
        const links = this.procurementLinks || {};
        const hasLinks = ["purchase_request", "purchase_order", "purchase_receipt", "purchase_invoice"].some((key) => links[key]);
        if (!hasLinks) {
            this.procurementMatchPreview = null;
            this.renderProcurementMatchPreview();
            return null;
        }
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_procurement_match_preview",
                args: { links: JSON.stringify(links) },
            });
            this.procurementMatchPreview = response.message || null;
            this.renderProcurementMatchPreview();
            if (showAlert) frappe.show_alert({ message: __("Procurement match preview refreshed."), indicator: "green" }, 4);
            return this.procurementMatchPreview;
        } catch (error) {
            console.error("Unable to load procurement match preview", error);
            if (showAlert) {
                frappe.msgprint({
                    title: __("Procurement Match Preview"),
                    message: this.escape(error.message || error),
                    indicator: "red",
                });
            }
            return null;
        }
    }

    renderProcurementMatchPreview() {
        const $target = this.$main.find("[data-role='procurement-match-content']");
        if (!$target.length) return;
        const links = this.procurementLinks || {};
        const docTypes = {
            purchase_request: "Material Request",
            purchase_order: "Purchase Order",
            purchase_receipt: "Purchase Receipt",
            purchase_invoice: "Purchase Invoice",
        };
        const labels = {
            purchase_request: __("Purchase Request"),
            purchase_order: __("Purchase Order"),
            purchase_receipt: __("Purchase Receipt"),
            purchase_invoice: __("Purchase Invoice"),
        };
        const keys = ["purchase_request", "purchase_order", "purchase_receipt", "purchase_invoice"];
        const hasLinks = keys.some((key) => links[key]);
        if (!hasLinks) {
            $target.html(`<div class="pimv1-help">${__("No linked procurement documents yet. Create Purchase Request / Order / Receipt / Invoice drafts from this page to build the matching preview.")}</div>`);
            return;
        }

        const docsHtml = keys.map((key) => {
            const name = links[key];
            const doctype = links[`${key}_doctype`] || docTypes[key];
            if (!name) return `<span class="pimv1-match-doc pimv1-match-muted">${labels[key]}: —</span>`;
            return `<button type="button" class="btn btn-xs btn-default pimv1-match-doc" data-action="open-procurement-doc" data-doctype="${this.escape(doctype)}" data-name="${this.escape(name)}">${labels[key]} <strong>${this.escape(name)}</strong></button>`;
        }).join("");

        const preview = this.procurementMatchPreview;
        if (!preview) {
            $target.html(`<div class="pimv1-match-docs">${docsHtml}</div><div class="pimv1-help" style="margin-top:10px;">${__("Click Refresh Match to load quantities and amounts from the linked official drafts.")}</div>`);
            return;
        }

        const summary = preview.summary || {};
        const rows = preview.rows || [];
        const requestOnly = !!(links.purchase_request && !links.purchase_order && !links.purchase_receipt && !links.purchase_invoice);
        const status = requestOnly ? "planning" : (summary.match_status || "matched").toLowerCase();
        const statusLabel = requestOnly ? __("Request Loaded") : (summary.status_label || (status === "mismatch" ? __("Mismatch") : status === "warning" ? __("Warning") : __("Matched")));
        const statusIcon = status === "mismatch" ? "✖" : status === "warning" ? "⚠" : status === "planning" ? "●" : "✓";
        const statusHtml = `<span class="pimv1-match-status pimv1-status-${this.escape(status)}">${statusIcon} ${this.escape(statusLabel)}</span>`;
        const issues = requestOnly ? [] : (summary.issues || []);
        const issuesHtml = requestOnly ? `<div class="pimv1-help" style="margin-top:10px;">${__("Purchase Request is loaded. Create or load a Purchase Order to start ordered/received/invoiced matching.")}</div>` : (issues.length ? `
            <div class="pimv1-issues" data-role="three-way-match-issues">
                ${issues.map((issue) => `
                    <div class="pimv1-issue ${this.escape(issue.severity || "warning")}">
                        <div class="pimv1-issue-severity">${this.escape((issue.severity || "warning").toUpperCase())}</div>
                        <div><strong>${this.escape(issue.item_name || issue.item_code || "")}</strong><br>${this.escape(issue.message || issue.code || "")}</div>
                    </div>
                `).join("")}
            </div>` : `<div class="pimv1-help" style="margin-top:10px;">${__("All linked Purchase Order / Receipt / Invoice quantities and amounts are currently matched.")}</div>`);

        const rowStatus = (row) => {
            const rowStatus = (row.status || "matched").toLowerCase();
            const label = rowStatus === "mismatch" ? __("Mismatch") : rowStatus === "warning" ? __("Warning") : __("Matched");
            return `<span class="pimv1-row-status pimv1-status-${this.escape(rowStatus)}">${label}</span>`;
        };
        const rowsHtml = rows.length ? rows.map((row) => `
            <tr>
                <td>${rowStatus(row)}</td>
                <td>${this.escape(row.item_name || row.item_code)}</td>
                <td>${this.number(row.ordered_qty)}</td>
                <td>${this.number(row.received_qty)}</td>
                <td>${this.number(row.invoiced_qty)}</td>
                <td>${this.money(row.ordered_rate)}</td>
                <td>${this.money(row.invoiced_rate)}</td>
                <td>${this.number(row.ordered_vs_received_qty)}</td>
                <td>${this.number(row.received_vs_invoiced_qty)}</td>
                <td>${this.money(row.ordered_amount)}</td>
                <td>${this.money(row.invoiced_amount)}</td>
            </tr>`).join("") : `<tr><td colspan="11" class="pimv1-match-muted">${__("No item rows loaded yet.")}</td></tr>`;

        const missing = (preview.missing || []).length
            ? `<div class="text-warning" style="margin-top:8px;">${__("Some linked documents could not be loaded. Clear links or recreate drafts if needed.")}</div>`
            : "";

        $target.html(`
            <div class="pimv1-match-docs">${docsHtml}${statusHtml}</div>
            ${this.renderProcurementSimpleNextStep(preview, links)}
            ${this.renderProcurementStageStatusSummary(preview, links)}
            ${issuesHtml}
            <details class="pimv1-match-details">
                <summary>${__("Show quantities and item-level matching details")}</summary>
                <div class="pimv1-match-details-body">
                    <div class="pimv1-match-grid">
                        <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Ordered Qty")}</div><div class="pimv1-match-value">${this.number(summary.ordered_qty)}</div></div>
                        <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Received Qty")}</div><div class="pimv1-match-value">${this.number(summary.received_qty)}</div></div>
                        <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Invoiced Qty")}</div><div class="pimv1-match-value">${this.number(summary.invoiced_qty)}</div></div>
                        <div class="pimv1-match-box"><div class="pimv1-match-label">${__("PO vs Receipt Qty")}</div><div class="pimv1-match-value">${this.number(summary.ordered_vs_received_qty)}</div></div>
                        <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Receipt vs Invoice Qty")}</div><div class="pimv1-match-value">${this.number(summary.received_vs_invoiced_qty)}</div></div>
                        <div class="pimv1-match-box"><div class="pimv1-match-label">${__("PO vs Invoice Amount")}</div><div class="pimv1-match-value">${this.money(summary.ordered_vs_invoiced_amount)}</div></div>
                    </div>
                    <div class="pimv1-match-table-wrap">
                        <table class="pimv1-match-table">
                            <thead><tr><th>${__("Status")}</th><th>${__("Item")}</th><th>${__("Ordered")}</th><th>${__("Received")}</th><th>${__("Invoiced")}</th><th>${__("PO Rate")}</th><th>${__("Invoice Rate")}</th><th>${__("PO-Receipt")}</th><th>${__("Receipt-Invoice")}</th><th>${__("PO Amount")}</th><th>${__("Invoice Amount")}</th></tr></thead>
                            <tbody>${rowsHtml}</tbody>
                        </table>
                    </div>
                    ${missing}
                </div>
            </details>
        `);
    }




    renderProcurementSimpleNextStep(preview, links) {
        const summary = (preview && preview.summary) || {};
        links = links || this.procurementLinks || {};
        const hasRequest = !!links.purchase_request;
        const hasOrder = !!links.purchase_order;
        const hasReceipt = !!links.purchase_receipt;
        const hasInvoice = !!links.purchase_invoice;
        const matchStatus = String(summary.match_status || "matched").toLowerCase();

        let level = "info";
        let title = __("Next Step");
        let body = "";

        // Stage progression must win over warning status.
        // Example: an order without receipt is a normal waiting-receipt stage,
        // even if the match engine flags "ordered item not received yet" as warning.
        if (!hasRequest && !hasOrder && !hasReceipt && !hasInvoice) {
            level = "muted";
            body = __("Create or load a Purchase Request / Order / Receipt / Invoice to build the procurement cycle.");
        } else if (hasRequest && !hasOrder) {
            level = "info";
            body = __("Create Purchase Order Draft from this Purchase Request after choosing the supplier and the quantities you want to order.");
        } else if (hasOrder && !hasReceipt) {
            level = "info";
            body = __("Create Purchase Receipt Draft from this Purchase Order when the supplier sends the goods.");
        } else if (hasReceipt && !hasInvoice) {
            level = "info";
            body = __("Create Purchase Invoice Draft from this Purchase Receipt when you receive or enter the supplier invoice.");
        } else if (matchStatus === "mismatch") {
            level = "danger";
            body = __("Fix the mismatch before submit. Usually this means the invoice quantity is higher than the received quantity, or linked documents need correction.");
        } else if (matchStatus === "warning") {
            level = "warning";
            body = __("Review the warnings before submit. Warnings can be operationally acceptable, for example when the supplier sent an actual extra/wrong item. Enter the invoice as-is, then handle return/credit note if needed.");
        } else if (hasInvoice && matchStatus === "matched") {
            level = "success";
            body = __("The linked procurement documents are matched. Review the draft invoice, then submit when ready, or start a new draft.");
        } else {
            level = "info";
            body = __("Review the procurement stage summary, then continue with the next operational document.");
        }

        return `
            <div class="pimv1-next-step-note pimv1-next-step-${this.escape(level)}" data-role="procurement-simple-next-step">
                <strong>${this.escape(title)}:</strong> ${this.escape(body)}
            </div>`;
    }
    renderProcurementStageStatusSummary(preview, links) {
        const summary = (preview && preview.summary) || {};
        links = links || this.procurementLinks || {};
        const hasRequest = !!links.purchase_request;
        const hasOrder = !!links.purchase_order;
        const hasReceipt = !!links.purchase_receipt;
        const hasInvoice = !!links.purchase_invoice;

        const requestedQty = flt(summary.requested_qty || 0);
        const orderedQty = flt(summary.ordered_qty || 0);
        const receivedQty = flt(summary.received_qty || 0);
        const invoicedQty = flt(summary.invoiced_qty || 0);
        const remainingToOrder = Math.max(0, requestedQty - orderedQty);
        const remainingToReceive = Math.max(0, orderedQty - receivedQty);
        const remainingToInvoice = Math.max(0, receivedQty - invoicedQty);
        const overOrdered = Math.max(0, orderedQty - requestedQty);
        const overReceived = Math.max(0, receivedQty - orderedQty);
        const overInvoiced = Math.max(0, invoicedQty - receivedQty);
        const matchStatus = String(summary.match_status || "matched").toLowerCase();
        const requestOnly = !!(hasRequest && !hasOrder && !hasReceipt && !hasInvoice);

        const stageCard = (title, value, note, level) => `
            <div class="pimv1-stage-card pimv1-stage-${this.escape(level || "open")}">
                <div class="pimv1-stage-title">${this.escape(title)}</div>
                <div class="pimv1-stage-value">${this.escape(value)}</div>
                <div class="pimv1-stage-note">${note}</div>
            </div>`;

        let requestValue = __("No Request");
        let requestLevel = "muted";
        if (hasRequest) {
            if (!hasOrder) {
                requestValue = __("Open Request");
                requestLevel = "open";
            } else if (overOrdered > 0.0001) {
                requestValue = __("Over Ordered");
                requestLevel = "attention";
            } else if (remainingToOrder > 0.0001) {
                requestValue = __("Partially Ordered");
                requestLevel = "progress";
            } else {
                requestValue = __("Fully Ordered");
                requestLevel = "done";
            }
        }

        let orderValue = __("No Order");
        let orderLevel = "muted";
        if (hasOrder) {
            if (!hasReceipt && receivedQty <= 0) {
                orderValue = __("Waiting Receipt");
                orderLevel = "open";
            } else if (overReceived > 0.0001) {
                orderValue = __("Over Received");
                orderLevel = "attention";
            } else if (remainingToReceive > 0.0001) {
                orderValue = __("Partially Received");
                orderLevel = "progress";
            } else {
                orderValue = __("Fully Received");
                orderLevel = "done";
            }
        }

        let receiptValue = __("No Receipt");
        let receiptLevel = "muted";
        if (hasReceipt) {
            if (!hasInvoice && invoicedQty <= 0) {
                receiptValue = __("Waiting Invoice");
                receiptLevel = "open";
            } else if (overInvoiced > 0.0001) {
                receiptValue = __("Over Invoiced");
                receiptLevel = "attention";
            } else if (remainingToInvoice > 0.0001) {
                receiptValue = __("Partially Invoiced");
                receiptLevel = "progress";
            } else {
                receiptValue = __("Fully Invoiced");
                receiptLevel = "done";
            }
        }

        let overallValue = __("Open");
        let overallLevel = "open";
        if (matchStatus === "mismatch") {
            overallValue = __("Needs Attention");
            overallLevel = "attention";
        } else if (matchStatus === "warning") {
            overallValue = __("Needs Review");
            overallLevel = "progress";
        } else if (requestOnly) {
            overallValue = __("Request Loaded");
            overallLevel = "open";
        } else if (hasInvoice && matchStatus === "matched") {
            overallValue = __("Completed / Matched");
            overallLevel = "done";
        } else if (hasReceipt) {
            overallValue = __("Receipt Stage");
            overallLevel = remainingToInvoice > 0 ? "progress" : "open";
        } else if (hasOrder) {
            overallValue = __("Order Stage");
            overallLevel = remainingToReceive > 0 ? "progress" : "open";
        } else if (hasRequest) {
            overallValue = __("Request Stage");
            overallLevel = "open";
        }

        const requestNote = hasRequest
            ? `${__("Requested")}: <strong>${this.number(requestedQty)}</strong> · ${__("Ordered")}: <strong>${this.number(orderedQty)}</strong> · ${__("Remaining")}: <strong>${this.number(remainingToOrder)}</strong>`
            : __("No shortage/request source is linked to this cycle.");
        const orderNote = hasOrder
            ? `${__("Ordered")}: <strong>${this.number(orderedQty)}</strong> · ${__("Received")}: <strong>${this.number(receivedQty)}</strong> · ${__("Remaining")}: <strong>${this.number(remainingToReceive)}</strong>`
            : __("Create or load a Purchase Order to choose supplier and ordered qty.");
        const receiptNote = hasReceipt
            ? `${__("Received")}: <strong>${this.number(receivedQty)}</strong> · ${__("Invoiced")}: <strong>${this.number(invoicedQty)}</strong> · ${__("Remaining")}: <strong>${this.number(remainingToInvoice)}</strong>`
            : __("Create or load a Purchase Receipt to record what actually arrived.");
        const overallNote = summary.status_label
            ? this.escape(summary.status_label)
            : __("Stage status is read-only and based on linked Request / Order / Receipt / Invoice quantities.");

        return `
            <div class="pimv1-stage-summary" data-role="procurement-stage-status-summary">
                ${stageCard(__("Request"), requestValue, requestNote, requestLevel)}
                ${stageCard(__("Order"), orderValue, orderNote, orderLevel)}
                ${stageCard(__("Receipt"), receiptValue, receiptNote, receiptLevel)}
                ${stageCard(__("Overall"), overallValue, overallNote, overallLevel)}
            </div>`;
    }

    procurementSourceConfig(sourceType) {
        const configs = {
            purchase_request: {
                label: __("Purchase Request"),
                doctype: "Material Request",
                linkKey: "purchase_request",
                targetKind: "purchase_order",
                nextLabel: __("Purchase Order Draft"),
            },
            purchase_order: {
                label: __("Purchase Order"),
                doctype: "Purchase Order",
                linkKey: "purchase_order",
                targetKind: "purchase_receipt",
                nextLabel: __("Purchase Receipt Draft"),
            },
            purchase_receipt: {
                label: __("Purchase Receipt"),
                doctype: "Purchase Receipt",
                linkKey: "purchase_receipt",
                targetKind: "purchase_invoice",
                nextLabel: __("Purchase Invoice Draft"),
            },
        };
        return configs[sourceType] || configs.purchase_request;
    }

    async openProcurementSourcePicker(sourceType, preselectedName = "") {
        const config = this.procurementSourceConfig(sourceType);
        let loaded = null;
        const dialog = new frappe.ui.Dialog({
            title: __("Load From {0}", [config.label]),
            size: "extra-large",
            fields: [
                {
                    fieldname: "source_name",
                    fieldtype: "Link",
                    label: config.label,
                    options: config.doctype,
                    reqd: 1,
                    get_query: () => ({ filters: { docstatus: ["<", 2] } }),
                },
                {
                    fieldname: "replace_rows",
                    fieldtype: "Check",
                    label: __("Replace current purchase rows"),
                    default: this.rows.length ? 1 : 0,
                },
                { fieldname: "source_items_html", fieldtype: "HTML" },
            ],
            primary_action_label: __("Load Items"),
            primary_action: async () => {
                if (!loaded) {
                    await loadSource();
                    dialog.set_primary_action_label(__("Apply Selected Items"));
                    return;
                }
                await applySelected();
            },
            secondary_action_label: __("Cancel"),
            secondary_action: () => dialog.hide(),
        });

        const renderEmpty = (message) => {
            dialog.fields_dict.source_items_html.$wrapper.html(`<div class="pimv1-help" style="margin-top:12px;">${this.escape(message)}</div>`);
        };
        const renderRows = () => {
            const rows = loaded.items || [];
            if (!rows.length) {
                renderEmpty(__("No source item rows were found."));
                return;
            }
            const sourceDoc = (loaded && loaded.document) || {};
            dialog.fields_dict.source_items_html.$wrapper.html(`
                <div class="pimv1-source-context">
                    <span>${__("Selected Source")}</span>
                    <span class="pimv1-source-pill">${this.escape(config.label)}: ${this.escape(sourceDoc.name || "")}</span>
                    <span>${__("Next Operation")}</span>
                    <span class="pimv1-source-pill">${this.escape(config.nextLabel)}</span>
                </div>
                <div class="pimv1-help" style="margin:12px 0;">
                    ${__("Select the rows and quantities to continue into {0}. You can split one request/order into multiple later documents by loading only part of the quantity.", [config.nextLabel])}
                </div>
                <div style="max-height:420px; overflow:auto; border:1px solid var(--border-color); border-radius:10px;">
                    <table class="table table-bordered table-sm" style="margin:0; font-size:12px;">
                        <thead>
                            <tr>
                                <th style="width:45px;">${__("Use")}</th>
                                <th>${__("Item")}</th>
                                <th style="width:105px;">${__("Source Qty")}</th>
                                <th style="width:110px;">${__("Already Used")}</th>
                                <th style="width:105px;">${__("Remaining")}</th>
                                                                <th style="width:110px;">${__("Current Stock")}</th>
                                <th style="width:110px;">${__("Suggested Qty")}</th>
                                <th style="width:130px;">${__("Qty to Load")}</th>
                                <th style="width:90px;">${__("UOM")}</th>
                                <th style="width:120px;">${__("Rate")}</th>
                                <th>${__("Warehouse")}</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${rows.map((row, index) => {
                                const remainingQty = flt(row.remaining_qty);

                                const currentStockQty = flt(row.current_stock_qty || 0);
                                const suggestedQty = Math.max(0, Math.min(remainingQty, flt(row.suggested_qty_to_load !== undefined ? row.suggested_qty_to_load : remainingQty)));
                                const stockLevel = row.stock_recheck_level || "none";
                                const stockMessage = row.stock_recheck_message || "";
                                const fullyConsumed = remainingQty <= 0;
                                return `
                                <tr data-source-index="${index}" class="${fullyConsumed ? "text-muted" : ""}">
                                    <td><input type="checkbox" data-role="source-select" data-index="${index}" ${fullyConsumed ? "disabled" : "checked"}></td>
                                    <td><strong>${this.escape(row.item_name || row.item_code)}</strong><br><span class="text-muted">${this.escape(row.item_code || "")}</span>${fullyConsumed ? `<br><span class="badge badge-default">${__("Fully Used")}</span>` : ""}</td>
                                    <td>${this.number(row.source_qty || 0)}</td>
                                    <td>${this.number(row.already_used_qty || 0)}</td>
                                    <td><strong>${this.number(remainingQty)}</strong>${stockMessage ? `<span class="pimv1-stock-recheck ${this.escape(stockLevel)}">${this.escape(stockMessage)}</span>` : ""}</td>
                                    <td>${this.number(currentStockQty)}</td>
                                    <td><strong>${this.number(suggestedQty)}</strong></td>
                                    <td><input class="form-control input-xs" type="number" step="0.001" min="0" max="${remainingQty}" data-role="source-qty" data-index="${index}" value="${fullyConsumed ? 0 : suggestedQty}" ${fullyConsumed ? "disabled" : ""}></td>
                                    <td>${this.escape(row.uom || "")}</td>
                                    <td>${this.money(row.net_rate || row.supplier_base_price || 0)}</td>
                                    <td>${this.escape(row.warehouse || "")}</td>
                                </tr>`;
                            }).join("")}
                        </tbody>
                    </table>
                </div>
            `);
        };

        const loadSource = async () => {
            const sourceName = dialog.get_value("source_name");
            if (!sourceName) {
                frappe.msgprint({ title: config.label, message: __("Select a source document first."), indicator: "orange" });
                return;
            }
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_procurement_source_items",
                args: { source_type: sourceType, source_name: sourceName },
                freeze: true,
                freeze_message: __("Loading {0} items...", [config.label]),
            });
            loaded = response.message || null;
            renderRows();
        };

        const applySelected = async () => {
            if (!loaded) return;
            const selected = [];
            const $wrapper = dialog.fields_dict.source_items_html.$wrapper;
            $wrapper.find("[data-role='source-select']").each((_, checkbox) => {
                const $checkbox = $(checkbox);
                if (!$checkbox.prop("checked")) return;
                const index = Number($checkbox.data("index"));
                const row = { ...(loaded.items[index] || {}) };
                const qty = flt($wrapper.find(`[data-role='source-qty'][data-index='${index}']`).val());
                const remainingQty = flt(row.remaining_qty);
                if (!row.item_code || qty <= 0) return;
                if (remainingQty <= 0) return;
                if (qty > remainingQty + 0.0001) {
                    frappe.throw(__("Qty exceeds remaining quantity for {0}. Remaining: {1}", [row.item_name || row.item_code, remainingQty]));
                }
                row.qty = qty;
                row.source_qty = flt(row.source_qty || remainingQty || row.qty);
                row.already_used_qty = flt(row.already_used_qty || 0);
                row.remaining_qty = remainingQty;
                row.row_id = row.row_id || this.makeRowId();
                this.recalculateRow(row);
                selected.push(row);
            });
            if (!selected.length) {
                frappe.msgprint({ title: config.label, message: __("Select at least one item row with quantity greater than zero."), indicator: "orange" });
                return;
            }

            const replaceRows = cint(dialog.get_value("replace_rows"));
            if (loaded.company && this.controls.company) await this.controls.company.set_value(loaded.company);
            if (loaded.supplier && this.controls.supplier) await this.controls.supplier.set_value(loaded.supplier);
            if (loaded.warehouse && this.controls.warehouse) await this.controls.warehouse.set_value(loaded.warehouse);
            this.rows = replaceRows ? selected : (this.rows || []).concat(selected);
            this.applyProcurementChain(loaded.linked_documents || {}, { replace: true });
            this.recordProcurementLink(config.linkKey, loaded.document);
            this.renderRows();
            this.refreshCards();
            await this.fetchProcurementMatchPreview();
            dialog.hide();
            frappe.show_alert({ message: __("Loaded {0} item rows from {1}.", [selected.length, loaded.document.name]), indicator: "green" }, 6);
        };

        renderEmpty(__("Select a source document, then click Load Items."));
        dialog.show();
        if (preselectedName) {
            await dialog.set_value("source_name", preselectedName);
            await loadSource();
            dialog.set_primary_action_label(__("Apply Selected Items"));
        }
    }

    procurementDraftPayload() {
        const payload = this.payload();
        payload.required_by_date = this.value("due_date") || this.value("posting_date") || frappe.datetime.get_today();
        payload.items = (this.rows || [])
            .filter((row) => row && row.item_code && flt(row.qty) > 0)
            .map((row) => ({ ...row }));
        return payload;
    }

    validateProcurementDraft(kind) {
        const titleByKind = {
            purchase_request: __("Purchase Request Draft"),
            purchase_order: __("Purchase Order Draft"),
            purchase_receipt: __("Purchase Receipt Draft"),
            purchase_invoice: __("Purchase Invoice Draft"),
        };
        const title = titleByKind[kind] || __("Procurement Draft");
        const needsSupplier = kind === "purchase_order" || kind === "purchase_receipt" || kind === "purchase_invoice";
        const needsRate = kind === "purchase_order" || kind === "purchase_receipt" || kind === "purchase_invoice";
        const errors = [];

        if (!this.value("company")) errors.push(__("Company is required."));
        if (needsSupplier && !this.value("supplier")) errors.push(__("Supplier is required for {0}.", [title]));
        if (!this.value("warehouse")) errors.push(__("Receiving Warehouse is required."));
        if (!this.rows.length) errors.push(__("Add at least one purchase item."));

        (this.rows || []).forEach((row, index) => {
            if (!row.item_code) errors.push(__("Item is required on row {0}.", [index + 1]));
            if (flt(row.qty) <= 0) errors.push(__("Quantity must be greater than zero on row {0}.", [index + 1]));
            if (needsRate && !cint(row.is_bonus) && flt(row.net_rate || row.supplier_base_price) <= 0) {
                errors.push(__("Purchase rate is required on row {0} for {1}.", [index + 1, title]));
            }
        });

        if (errors.length) {
            frappe.msgprint({
                title,
                message: `<ul>${errors.map((message) => `<li>${this.escape(message)}</li>`).join("")}</ul>`,
                indicator: "orange",
            });
            return false;
        }
        return true;
    }

    async createProcurementDraft(kind) {
        const labelByKind = {
            purchase_request: __("Purchase Request Draft"),
            purchase_order: __("Purchase Order Draft"),
            purchase_receipt: __("Purchase Receipt Draft"),
            purchase_invoice: __("Purchase Invoice Draft"),
        };
        const methodByKind = {
            purchase_request: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.create_purchase_request_draft",
            purchase_order: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.create_purchase_order_draft",
            purchase_receipt: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.create_purchase_receipt_draft",
            purchase_invoice: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.create_purchase_invoice_draft",
        };
        const label = labelByKind[kind] || __("Procurement Draft");
        const method = methodByKind[kind];
        if (!method) {
            frappe.msgprint({ title: label, message: __("Unsupported procurement draft type."), indicator: "red" });
            return null;
        }

        if (!this.validateProcurementDraft(kind)) return null;

        try {
            const response = await frappe.call({
                method,
                args: { payload: JSON.stringify(this.procurementDraftPayload()) },
                freeze: true,
                freeze_message: __("Creating {0}...", [label]),
            });
            const message = response.message || {};
            const document = message.document || {};
            if (!document.name) {
                frappe.msgprint({
                    title: label,
                    message: __("Draft was not created. No document name was returned."),
                    indicator: "red",
                });
                return null;
            }
            frappe.show_alert({
                message: __("Created {0}: {1}", [label, document.name]),
                indicator: "green",
            }, 7);
            this.recordProcurementLink(kind, document);
            await this.fetchProcurementMatchPreview();
            // v0.7.58: keep the operator on Purchase & Invoice Management.
            // Drafts are created in the background, linked to the current procurement cycle,
            // and the match preview is refreshed instead of opening the ERPNext Form page.
            const linkKeyByKind = {
                purchase_request: "purchase_request",
                purchase_order: "purchase_order",
                purchase_receipt: "purchase_receipt",
                purchase_invoice: "purchase_invoice",
            };

            if (typeof this.recordProcurementLink === "function" && linkKeyByKind[kind]) {
                this.recordProcurementLink(linkKeyByKind[kind], document);
            }

            if (kind === "purchase_invoice" && message.invoice) {
                this.draftName = message.invoice.name || document.name;
                if (typeof this.applySavedInvoiceState === "function") {
                    this.applySavedInvoiceState(message.invoice);
                } else if (typeof this.setSavedInvoice === "function") {
                    this.setSavedInvoice(message.invoice);
                } else {
                    this.currentInvoice = message.invoice;
                    this.savedInvoice = message.invoice;
                }
            }

            if (typeof this.refreshCards === "function") {
                this.refreshCards();
            }
            if (typeof this.renderRows === "function") {
                this.renderRows();
            }
            if (typeof this.fetchProcurementMatchPreview === "function") {
                await this.fetchProcurementMatchPreview(true);
            }
            await this.refreshOpenProcurementDrafts({ silent: true });
            return document;
        } catch (error) {
            console.error("Purchase procurement draft creation failed", error);
            const message = error && error.message ? error.message : __("Draft creation failed. Check the browser console/server log for details.");
            frappe.msgprint({
                title: label,
                message: this.escape(message),
                indicator: "red",
            });
            return null;
        }
    }

    createPurchaseRequestDraft() {
        return this.createProcurementDraft("purchase_request");
    }

    createPurchaseOrderDraft() {
        return this.createProcurementDraft("purchase_order");
    }

    createPurchaseReceiptDraft() {
        return this.createProcurementDraft("purchase_receipt");
    }

    createPurchaseInvoiceDraft() {
        return this.createProcurementDraft("purchase_invoice");
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
            procurement_links: { ...(this.procurementLinks || {}) },
            items: this.rows,
        };
    }


    renderSupplierSettlement() {
        const $container = this.$main.find("[data-role='supplier-settlement']");
        if (!$container.length) return;
        if (this.supplierSettlementLoading) {
            $container.html(`<div class="pimv1-settlement-empty">${__("Loading supplier settlement...")}</div>`);
            return;
        }
        if (!this.draftName) {
            $container.html(`<div class="pimv1-settlement-empty">${__("Save the Purchase Invoice first. Settlement actions become available after the invoice is submitted.")}</div>`);
            return;
        }
        const c = this.supplierSettlementContext;
        if (!c || c.invoice !== this.draftName) {
            $container.html(`<div class="pimv1-settlement-empty">${__("Settlement information has not been loaded yet.")} <button type="button" class="btn btn-xs btn-default" data-action="refresh-supplier-settlement">${__("Load")}</button></div>`);
            return;
        }
        const actions = c.actions || {};
        const statusClass = c.settlement_status === "Paid" ? "is-paid" : (["Draft", "Cancelled"].includes(c.settlement_status) ? "is-attention" : "");
        const claimLink = c.linked_supplier_claim
            ? `<span class="pimv1-link" data-action="open-linked-supplier-claim" data-name="${this.escape(c.linked_supplier_claim)}">${this.escape(c.linked_supplier_claim)}</span>`
            : "—";
        const actionButtons = [
            actions.create_payment_draft ? `<button type="button" class="btn btn-primary btn-sm" data-action="create-settlement-payment">${__("Create Payment Draft")}</button>` : "",
            actions.create_claim_draft ? `<button type="button" class="btn btn-primary btn-sm" data-action="create-settlement-claim">${__("Create Supplier Claim Draft")}</button>` : "",
            actions.use_existing_advance ? `<button type="button" class="btn btn-warning btn-sm" data-action="use-settlement-advance">${__("Use Existing Advance")}</button>` : "",
            actions.open_supplier_account ? `<button type="button" class="btn btn-default btn-sm" data-action="supplier-running-account">${__("Open Supplier Account")}</button>` : "",
        ].filter(Boolean).join("");
        const settlementDocstatus = cint(c.docstatus);
        const documentNote = settlementDocstatus === 0
            ? `<div class="pimv1-settlement-warning">${__("The invoice must be submitted before payment, claim or advance-allocation actions are available.")}</div>`
            : (settlementDocstatus === 2
                ? `<div class="pimv1-settlement-warning">${__("This invoice is cancelled. Settlement actions are not available.")}</div>`
                : "");
        const claimNote = c.classification === "Claim Invoice" && c.linked_supplier_claim
            ? `<div class="pimv1-settlement-warning">${__("This invoice is already linked to Supplier Claim {0}. Payment or advance allocation requires intentional review in the Supplier Account.", [c.linked_supplier_claim])}</div>`
            : "";
        $container.html(`
            <div class="pimv1-settlement-grid">
                <div class="pimv1-settlement-card"><div class="pimv1-settlement-label">${__("Settlement Status")}</div><div class="pimv1-settlement-value"><span class="pimv1-settlement-status ${statusClass}">${this.escape(c.settlement_status || "—")}</span></div><div class="pimv1-settlement-note">${this.escape(c.invoice_status || "")}</div></div>
                <div class="pimv1-settlement-card"><div class="pimv1-settlement-label">${__("Classification")}</div><div class="pimv1-settlement-value">${this.escape(c.classification || "—")}</div><div class="pimv1-settlement-note">${__("Controls the recommended settlement action")}</div></div>
                <div class="pimv1-settlement-card"><div class="pimv1-settlement-label">${__("Outstanding")}</div><div class="pimv1-settlement-value">${this.money(c.outstanding_amount)}</div><div class="pimv1-settlement-note">${__("Paid")}: ${this.money(c.paid_amount)}</div></div>
                <div class="pimv1-settlement-card"><div class="pimv1-settlement-label">${__("Supplier Balance")}</div><div class="pimv1-settlement-value">${this.money(c.supplier_balance)}</div><div class="pimv1-settlement-note">${this.escape(c.supplier_name || c.supplier || "")}</div></div>
                <div class="pimv1-settlement-card"><div class="pimv1-settlement-label">${__("Unallocated Advances")}</div><div class="pimv1-settlement-value">${this.money(c.unallocated_advance_total)}</div><div class="pimv1-settlement-note">${(c.unallocated_advances || []).length} ${__("available payment(s)")}</div></div>
                <div class="pimv1-settlement-card"><div class="pimv1-settlement-label">${__("Supplier Claim")}</div><div class="pimv1-settlement-value">${claimLink}</div><div class="pimv1-settlement-note">${this.escape(c.linked_supplier_claim_status || "")}</div></div>
            </div>
            ${documentNote}${claimNote}
            <div class="pimv1-settlement-actions">${actionButtons || `<span class="text-muted">${__("No settlement action is currently available.")}</span>`}</div>
        `);
    }

    async refreshSupplierSettlement(options = {}) {
        if (!this.draftName) {
            this.supplierSettlementContext = null;
            this.renderSupplierSettlement();
            return null;
        }
        this.supplierSettlementLoading = true;
        this.renderSupplierSettlement();
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_invoice_settlement_context",
                args: { name: this.draftName },
                freeze: !options.silent,
                freeze_message: __("Loading supplier settlement..."),
            });
            this.supplierSettlementContext = response.message || null;
            return this.supplierSettlementContext;
        } catch (error) {
            this.supplierSettlementContext = null;
            if (!options.silent) throw error;
            console.warn("Unable to load supplier settlement", error);
            return null;
        } finally {
            this.supplierSettlementLoading = false;
            this.renderSupplierSettlement();
        }
    }

    async settlementContextOrRefresh() {
        if (!this.draftName) {
            frappe.msgprint(__("Save the Purchase Invoice first."));
            return null;
        }
        if (this.supplierSettlementContext && this.supplierSettlementContext.invoice === this.draftName) {
            return this.supplierSettlementContext;
        }
        return await this.refreshSupplierSettlement();
    }

    async openSettlementPaymentDraftDialog() {
        const c = await this.settlementContextOrRefresh();
        if (!c || !c.actions || !c.actions.create_payment_draft) {
            frappe.msgprint(__("A Payment Draft is not available for this invoice classification or status."));
            return;
        }
        const defaultsResponse = await frappe.call({
            method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.get_supplier_payment_defaults",
            args: { company: c.company, supplier: c.supplier },
        });
        const d = defaultsResponse.message || {};
        const dialog = new frappe.ui.Dialog({
            title: __("Create Payment Draft for {0}", [c.invoice]),
            fields: [
                { fieldname: "posting_date", fieldtype: "Date", label: __("Posting Date"), default: frappe.datetime.get_today(), reqd: 1 },
                { fieldname: "amount", fieldtype: "Currency", label: __("Payment Amount"), default: c.outstanding_amount, reqd: 1, description: __("Any amount above the invoice allocation remains an unallocated supplier advance.") },
                { fieldname: "allocated_amount", fieldtype: "Currency", label: __("Allocate to This Invoice"), default: c.outstanding_amount, reqd: 1 },
                { fieldtype: "Column Break" },
                { fieldname: "mode_of_payment", fieldtype: "Link", label: __("Mode of Payment"), options: "Mode of Payment", default: d.mode_of_payment || "" },
                { fieldname: "paid_from", fieldtype: "Link", label: __("Paid From Account"), options: "Account", default: d.paid_from || "", reqd: 1, get_query: () => ({ filters: { company: c.company, is_group: 0 } }) },
                { fieldname: "reference_no", fieldtype: "Data", label: __("Reference No") },
                { fieldtype: "Section Break" },
                { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks"), default: __("Draft payment for Purchase Invoice {0} created from Purchase & Invoice Management.", [c.invoice]) },
            ],
            primary_action_label: __("Create Draft"),
            primary_action: async (values) => {
                const amount = flt(values.amount || 0);
                const allocated = flt(values.allocated_amount || 0);
                if (amount <= 0 || allocated <= 0 || allocated - amount > 0.005 || allocated - flt(c.outstanding_amount) > 0.005) {
                    frappe.msgprint(__("Enter valid payment and allocation amounts. Allocation cannot exceed the payment or invoice outstanding."));
                    return;
                }
                dialog.hide();
                const response = await frappe.call({
                    method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.create_supplier_payment_draft",
                    args: { args: {
                        company: c.company,
                        supplier: c.supplier,
                        posting_date: values.posting_date,
                        amount,
                        mode_of_payment: values.mode_of_payment || "",
                        paid_from: values.paid_from,
                        allocation_mode: "Selected Invoices",
                        invoices: [{ invoice: c.invoice, allocated_amount: allocated }],
                        reference_no: values.reference_no || "",
                        remarks: values.remarks || "",
                    } },
                    freeze: true,
                    freeze_message: __("Creating draft Payment Entry..."),
                });
                const out = response.message || {};
                if (out.name) {
                    frappe.show_alert({ message: __("Draft Payment Entry created: {0}", [out.name]), indicator: "green" }, 7);
                    frappe.set_route("Form", "Payment Entry", out.name);
                }
            },
        });
        dialog.show();
    }

    async openSettlementClaimDraftDialog() {
        const c = await this.settlementContextOrRefresh();
        if (!c || !c.actions || !c.actions.create_claim_draft) {
            frappe.msgprint(__("A Supplier Claim Draft is not available for this invoice classification or status."));
            return;
        }
        const fromDate = c.expected_claim_period_from || c.posting_date || frappe.datetime.get_today();
        const toDate = c.expected_claim_period_to || c.due_date || frappe.datetime.get_today();
        const candidateResponse = await frappe.call({
            method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.get_supplier_claim_draft_candidates",
            args: { company: c.company, supplier: c.supplier, from_date: fromDate, to_date: toDate, limit: 500 },
            freeze: true,
            freeze_message: __("Loading claim invoices and return credits..."),
        });
        const candidates = candidateResponse.message || [];
        const returnCredits = candidates.filter((row) => cint(row.is_return)).map((row) => ({ ...row, selected: false, selected_amount: Math.abs(flt(row.included_amount || row.outstanding_amount || 0)) }));
        const dialog = new frappe.ui.Dialog({
            title: __("Create Supplier Claim Draft for {0}", [c.invoice]),
            fields: [
                { fieldname: "period_from", fieldtype: "Date", label: __("Period From"), default: fromDate, reqd: 1 },
                { fieldname: "period_to", fieldtype: "Date", label: __("Period To"), default: toDate, reqd: 1 },
                { fieldname: "invoice_amount", fieldtype: "Currency", label: __("Current Invoice Included Amount"), default: c.outstanding_amount, reqd: 1 },
                { fieldtype: "Column Break" },
                { fieldname: "net_amount_to_pay", fieldtype: "Currency", label: __("Net Amount To Pay"), default: c.outstanding_amount, reqd: 1 },
                { fieldname: "payment_due_date", fieldtype: "Date", label: __("Payment Due Date"), default: c.due_date || "" },
                { fieldtype: "Section Break", label: __("Available Return Credits") },
                { fieldname: "return_credits_html", fieldtype: "HTML" },
                { fieldtype: "Section Break" },
                { fieldname: "notes", fieldtype: "Small Text", label: __("Notes"), default: __("Draft Supplier Claim created from Purchase & Invoice Management. Review before Submit.") },
            ],
            primary_action_label: __("Create Draft"),
            primary_action: async (values) => {
                const invoiceAmount = flt(values.invoice_amount || 0);
                if (invoiceAmount <= 0 || invoiceAmount - flt(c.outstanding_amount) > 0.005) {
                    frappe.msgprint(__("Current invoice included amount must be greater than zero and cannot exceed its outstanding amount."));
                    return;
                }
                const selectedReturns = returnCredits.filter((row) => row.selected && flt(row.selected_amount) > 0).map((row) => ({ purchase_invoice: row.purchase_invoice, included_amount: -Math.abs(flt(row.selected_amount)) }));
                const returnTotal = selectedReturns.reduce((sum, row) => sum + Math.abs(flt(row.included_amount)), 0);
                const systemTotal = invoiceAmount - returnTotal;
                const net = flt(values.net_amount_to_pay || 0);
                if (systemTotal < -0.005 || net < -0.005 || net - systemTotal > 0.005) {
                    frappe.msgprint(__("Return credits cannot exceed the invoice amount, and Net Amount To Pay must be between zero and the system claim total."));
                    return;
                }
                dialog.hide();
                const response = await frappe.call({
                    method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.create_supplier_claim_draft",
                    args: { args: {
                        company: c.company,
                        supplier: c.supplier,
                        period_from: values.period_from,
                        period_to: values.period_to,
                        payment_due_date: values.payment_due_date || "",
                        net_amount_to_pay: net,
                        invoices: [{ purchase_invoice: c.invoice, included_amount: invoiceAmount }, ...selectedReturns],
                        notes: values.notes || "",
                    } },
                    freeze: true,
                    freeze_message: __("Creating draft Supplier Claim..."),
                });
                const out = response.message || {};
                if (out.name) {
                    frappe.show_alert({ message: __("Draft Supplier Claim created: {0}", [out.name]), indicator: "green" }, 7);
                    await this.refreshSupplierSettlement({ silent: true });
                    frappe.set_route("Form", "Supplier Claim", out.name);
                }
            },
        });
        dialog.__autoNetAmount = true;
        const selectedReturnTotal = () => returnCredits
            .filter((row) => row.selected)
            .reduce((sum, row) => sum + Math.abs(flt(row.selected_amount || 0)), 0);
        const syncClaimNetAmount = () => {
            if (!dialog.__autoNetAmount) return;
            const invoiceAmount = flt(dialog.get_value("invoice_amount") || 0);
            dialog.set_value("net_amount_to_pay", Math.max(invoiceAmount - selectedReturnTotal(), 0));
        };
        const renderReturns = () => {
            const field = dialog.fields_dict.return_credits_html;
            if (!returnCredits.length) {
                field.$wrapper.html(`<div class="pimv1-settlement-empty">${__("No open Return Credits / Debit Notes are available in this claim period.")}</div>`);
                return;
            }
            field.$wrapper.html(`<div class="pimv1-settlement-warning">${__("Return credits are never selected automatically. Tick only the credits reviewed for this claim. Selected credit total")}: <strong data-role="selected-return-total">${this.money(selectedReturnTotal())}</strong></div><table class="pimv1-settlement-return-table"><thead><tr><th>${__("Use")}</th><th>${__("Document")}</th><th>${__("Outstanding Credit")}</th><th>${__("Include")}</th></tr></thead><tbody>${returnCredits.map((row, index) => `<tr><td><input type="checkbox" class="pimv1-claim-return-use" data-index="${index}" ${row.selected ? "checked" : ""}></td><td>${this.escape(row.purchase_invoice)}</td><td>${this.money(Math.abs(flt(row.outstanding_amount)))}</td><td><input type="number" step="0.01" min="0" class="form-control input-sm pimv1-claim-return-amount" data-index="${index}" value="${flt(row.selected_amount)}"></td></tr>`).join("")}</tbody></table>`);
            field.$wrapper.find(".pimv1-claim-return-use").on("change", (event) => {
                const row = returnCredits[Number($(event.currentTarget).data("index"))];
                if (row) row.selected = Boolean(event.currentTarget.checked);
                field.$wrapper.find("[data-role='selected-return-total']").text(this.money(selectedReturnTotal()));
                syncClaimNetAmount();
            });
            field.$wrapper.find(".pimv1-claim-return-amount").on("change input", (event) => {
                const row = returnCredits[Number($(event.currentTarget).data("index"))];
                if (row) row.selected_amount = Math.min(Math.abs(flt(event.currentTarget.value || 0)), Math.abs(flt(row.outstanding_amount || 0)));
                field.$wrapper.find("[data-role='selected-return-total']").text(this.money(selectedReturnTotal()));
                syncClaimNetAmount();
            });
        };
        dialog.show();
        renderReturns();
        if (dialog.fields_dict.invoice_amount && dialog.fields_dict.invoice_amount.$input) {
            dialog.fields_dict.invoice_amount.$input.on("change input", syncClaimNetAmount);
        }
        if (dialog.fields_dict.net_amount_to_pay && dialog.fields_dict.net_amount_to_pay.$input) {
            dialog.fields_dict.net_amount_to_pay.$input.on("change input", () => { dialog.__autoNetAmount = false; });
        }
    }

    async openSettlementAdvanceDialog() {
        const c = await this.refreshSupplierSettlement();
        if (!c || !c.actions || !c.actions.use_existing_advance) {
            frappe.msgprint(__("No usable supplier advance is currently available."));
            return;
        }
        const advances = c.unallocated_advances || [];
        const options = advances.map((row) => row.payment_entry).join("\n");
        const dialog = new frappe.ui.Dialog({
            title: __("Use Existing Supplier Advance"),
            fields: [
                { fieldname: "payment_entry", fieldtype: "Select", label: __("Payment Entry"), options, default: advances[0] ? advances[0].payment_entry : "", reqd: 1 },
                { fieldname: "available_advance", fieldtype: "Currency", label: __("Available Advance"), read_only: 1, default: advances[0] ? advances[0].unallocated_amount : 0 },
                { fieldname: "allocated_amount", fieldtype: "Currency", label: __("Allocate to Invoice"), default: Math.min(flt(c.outstanding_amount), advances[0] ? flt(advances[0].unallocated_amount) : 0), reqd: 1 },
                { fieldtype: "Section Break" },
                { fieldname: "safety_note", fieldtype: "HTML", options: `<div class="pimv1-settlement-warning">${__("This is an explicit reconciliation action. Review the Payment Entry, invoice outstanding and any Supplier Claim link before applying.")}</div>` },
            ],
            primary_action_label: __("Preview & Apply"),
            primary_action: async (values) => {
                const amount = flt(values.allocated_amount || 0);
                if (amount <= 0 || amount - flt(values.available_advance) > 0.005 || amount - flt(c.outstanding_amount) > 0.005) {
                    frappe.msgprint(__("Allocation must be greater than zero and cannot exceed the available advance or invoice outstanding."));
                    return;
                }
                const args = {
                    company: c.company,
                    supplier: c.supplier,
                    payment_entry: values.payment_entry,
                    invoices: [{ invoice: c.invoice, allocated_amount: amount }],
                    include_claim_linked: c.linked_supplier_claim ? 1 : 0,
                };
                const previewResponse = await frappe.call({
                    method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.preview_supplier_advance_allocation",
                    args: { args },
                    freeze: true,
                    freeze_message: __("Validating advance allocation..."),
                });
                const preview = previewResponse.message || {};
                const warning = preview.linked_claim_count
                    ? `<div class="text-danger"><strong>${__("Warning")}: ${__("This invoice is linked to a Supplier Claim. Continue only after intentional review.")}</strong></div>`
                    : "";
                frappe.confirm(`${warning}<div style="line-height:1.8"><div>${__("Payment Entry")}: <strong>${this.escape(values.payment_entry)}</strong></div><div>${__("Allocate")}: <strong>${this.money(preview.allocated_total)}</strong></div><div>${__("Remaining Advance")}: <strong>${this.money(preview.remaining_advance)}</strong></div></div>`, async () => {
                    dialog.hide();
                    const response = await frappe.call({
                        method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.reconcile_supplier_advance_against_invoices",
                        args: { args: { ...args, confirm_claim_linked: preview.linked_claim_count ? 1 : 0 } },
                        freeze: true,
                        freeze_message: __("Applying supplier advance..."),
                    });
                    const out = response.message || {};
                    frappe.show_alert({ message: __("Supplier advance applied from {0}.", [out.payment_entry || values.payment_entry]), indicator: "green" }, 8);
                    await this.refreshSupplierSettlement({ silent: true });
                });
            },
        });
        const updateAdvance = () => {
            const selected = advances.find((row) => row.payment_entry === dialog.get_value("payment_entry"));
            const available = selected ? flt(selected.unallocated_amount) : 0;
            dialog.set_value("available_advance", available);
            dialog.set_value("allocated_amount", Math.min(flt(c.outstanding_amount), available));
        };
        dialog.show();
        if (dialog.fields_dict.payment_entry && dialog.fields_dict.payment_entry.$input) {
            dialog.fields_dict.payment_entry.$input.on("change", updateAdvance);
        }
    }

    openSupplierRunningAccount() {
        frappe.route_options = {
            company: this.value("company"),
            supplier: this.value("supplier"),
            purchase_invoice: this.draftName || "",
            settlement_classification: this.value("payment_classification") || "",
        };
        frappe.set_route("supplier-running-account");
    }

    openReturnsManagement() {
        if (this.draftName && this.lastSavedTotals && cint(this.lastSavedTotals.docstatus) === 1) {
            frappe.route_options = {
                return_type: "Return Against Invoice",
                purchase_invoice: this.draftName,
            };
        } else {
            frappe.route_options = null;
        }
        frappe.set_route("purchase-returns-management");
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
            await this.refreshOpenProcurementDrafts({ silent: true });
            await this.refreshSupplierSettlement({ silent: true });
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
        const reset = async () => {
            this.rows = [];
            this.activeRowIndex = null;
            this.draftName = null;
            this.attachmentUrl = "";
            this.lastSavedTotals = null;
            this.supplierInvoiceTotalManual = false;
            this.supplierInvoiceTotalAutoUpdating = true;
            this.lastAutoSupplierInvoiceTotal = 0;
            this.procurementLinks = {};
            this.procurementMatchPreview = null;
            this.supplierSettlementContext = null;
            this.supplierSettlementLoading = false;
            this.saveProcurementLinks();
            this.clearLocalDraft();

            const clearFields = [
                "supplier", "bill_no", "payment_classification", "taxes_and_charges",
                "additional_charge_account", "remarks"
            ];
            const zeroFields = [
                "invoice_discount_percentage", "additional_charge_amount",
                "supplier_invoice_total", "fraction_adjustment"
            ];
            for (const field of clearFields) {
                if (this.controls[field]) await this.controls[field].set_value("");
            }
            for (const field of zeroFields) {
                if (this.controls[field]) await this.controls[field].set_value(0);
            }
            if (this.controls.tax_included_in_print_rate) {
                await this.controls.tax_included_in_print_rate.set_value(1);
            }

            const today = this.bootstrap.posting_date || frappe.datetime.get_today();
            for (const field of ["posting_date", "bill_date", "due_date"]) {
                if (this.controls[field]) await this.controls[field].set_value(today);
            }
            this.supplierInvoiceTotalAutoUpdating = false;
            this.supplierContext = {};

            this.$main.find("[data-role='attachment-name']").text(__("No file attached"));
            this.$main.find("[data-role='draft-badge']").text(__("Unsaved Invoice"));
            this.$main.find("[data-role='saved-grand']").text("—");
            this.$main.find("[data-role='saved-status']").text(__("Not saved yet"));
            this.$openButton.prop("disabled", true);
            this.$submitButton.prop("disabled", true);
            this.$cancelButton.prop("disabled", true);
            this.$main.find("[data-action='page-save-draft']").prop("disabled", false);
            this.$main.find("[data-action='page-save-submit']").prop("disabled", false);

            this.renderRows();
            this.refreshCards();
            this.renderSupplierSettlement();
            this.renderProcurementMatchPreview();
            window.scrollTo({ top: 0, behavior: "smooth" });
            frappe.show_alert({
                message: __("New invoice started. Current invoice data and procurement links were cleared."),
                indicator: "blue",
            }, 5);
        };
        if (this.rows.length || this.draftName || Object.keys(this.procurementLinks || {}).length) {
            frappe.confirm(__("Start a new invoice and clear all current page data and procurement links?"), reset);
        } else {
            reset();
        }
    }


    activeProcurementLinksForSubmit(invoiceName) {
        const links = Object.assign({}, this.procurementLinks || {});
        if (invoiceName) {
            links.purchase_invoice = invoiceName;
            links.purchase_invoice_doctype = "Purchase Invoice";
        }
        return links;
    }

    procurementLinksNeedSubmitGuard(links) {
        links = links || {};
        return !!(links.purchase_order || links.purchase_receipt || links.purchase_invoice);
    }

    procurementIssuesMarkup(preview) {
        const summary = (preview && preview.summary) || {};
        const issues = summary.issues || [];
        if (!issues.length) {
            return `<div class="text-muted">${__("No detailed issue rows were returned.")}</div>`;
        }
        return `
            <ul style="padding-inline-start: 18px; margin: 8px 0; line-height: 1.7;">
                ${issues.map((issue) => `
                    <li>
                        <strong>${this.escape((issue.severity || "warning").toUpperCase())}</strong>
                        ${issue.item_name || issue.item_code ? ` — ${this.escape(issue.item_name || issue.item_code)}` : ""}<br>
                        <span>${this.escape(issue.message || issue.code || "")}</span>
                    </li>
                `).join("")}
            </ul>`;
    }

    procurementDecisionSummaryMarkup(preview) {
        const summary = (preview && preview.summary) || {};
        return `
            <div class="pimv1-match-grid" style="margin-top: 8px;">
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Ordered Qty")}</div><div class="pimv1-match-value">${this.number(summary.ordered_qty)}</div></div>
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Received Qty")}</div><div class="pimv1-match-value">${this.number(summary.received_qty)}</div></div>
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Invoiced Qty")}</div><div class="pimv1-match-value">${this.number(summary.invoiced_qty)}</div></div>
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("PO vs Receipt")}</div><div class="pimv1-match-value">${this.number(summary.ordered_vs_received_qty)}</div></div>
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Receipt vs Invoice")}</div><div class="pimv1-match-value">${this.number(summary.received_vs_invoiced_qty)}</div></div>
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("PO vs Invoice Amount")}</div><div class="pimv1-match-value">${this.money(summary.ordered_vs_invoiced_amount)}</div></div>
            </div>`;
    }

    async logProcurementMatchDecision(invoiceName, preview, links, reason) {
        const summary = (preview && preview.summary) || {};
        await frappe.call({
            method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.log_procurement_match_decision",
            args: {
                payload: JSON.stringify({
                    purchase_invoice: invoiceName,
                    decision: "accepted_warning",
                    match_status: summary.match_status || "warning",
                    reason: reason || "",
                    links: links || {},
                    summary: summary,
                    issues: summary.issues || [],
                }),
            },
            freeze: true,
            freeze_message: __("Recording procurement match decision..."),
        });
    }

    promptProcurementWarningDecision(invoiceName, preview, links) {
        return new Promise((resolve) => {
            let resolved = false;
            const dialog = new frappe.ui.Dialog({
                title: __("Accept Procurement Match Warning"),
                fields: [
                    {
                        fieldtype: "HTML",
                        fieldname: "warning_html",
                        options: `
                            <div style="line-height:1.7">
                                <div class="text-warning"><strong>${__("This purchase invoice has procurement match warnings.")}</strong></div>
                                ${this.procurementDecisionSummaryMarkup(preview)}
                                <div style="margin-top:10px;"><strong>${__("Warnings")}</strong></div>
                                ${this.procurementIssuesMarkup(preview)}
                                <div class="text-muted">${__("Enter the operational reason for accepting this difference before submitting.")}</div>
                            </div>`,
                    },
                    {
                        fieldtype: "Small Text",
                        fieldname: "reason",
                        label: __("Reason for accepting difference"),
                        reqd: 1,
                    },
                ],
                primary_action_label: __("Accept Difference & Continue"),
                primary_action: async (values) => {
                    const reason = (values && values.reason ? values.reason : "").trim();
                    if (!reason) {
                        frappe.msgprint(__("Reason is required."));
                        return;
                    }
                    try {
                        await this.logProcurementMatchDecision(invoiceName, preview, links, reason);
                        resolved = true;
                        dialog.hide();
                        frappe.show_alert({ message: __("Procurement match decision recorded."), indicator: "orange" }, 5);
                        resolve(true);
                    } catch (error) {
                        console.error("Unable to log procurement match decision", error);
                        frappe.msgprint({
                            title: __("Procurement Match Decision"),
                            message: this.escape(error.message || error),
                            indicator: "red",
                        });
                    }
                },
            });
            dialog.onhide = () => {
                if (!resolved) resolve(false);
            };
            dialog.show();
        });
    }

    async ensureProcurementSubmitDecision(invoiceName) {
        const links = this.activeProcurementLinksForSubmit(invoiceName);
        if (!this.procurementLinksNeedSubmitGuard(links)) return true;

        this.procurementLinks = links;
        this.saveProcurementLinks();
        const preview = await this.fetchProcurementMatchPreview(false);
        if (!preview || !preview.summary) {
            frappe.msgprint({
                title: __("Procurement Match Guard"),
                message: __("Unable to refresh Procurement Match Preview. Please refresh the match before submitting."),
                indicator: "red",
            });
            return false;
        }

        const summary = preview.summary || {};
        const status = (summary.match_status || "matched").toLowerCase();
        if (status === "matched") return true;

        if (status === "mismatch") {
            frappe.msgprint({
                title: __("Procurement Match Mismatch"),
                message: `
                    <div style="line-height:1.7">
                        <div class="text-danger"><strong>${__("Submit blocked because there is a serious procurement mismatch.")}</strong></div>
                        ${this.procurementDecisionSummaryMarkup(preview)}
                        <div style="margin-top:10px;"><strong>${__("Mismatch details")}</strong></div>
                        ${this.procurementIssuesMarkup(preview)}
                        <div class="text-muted" style="margin-top:10px;">${__("Fix the Purchase Order / Receipt / Invoice quantities first, then refresh the match.")}</div>
                    </div>`,
                indicator: "red",
            });
            return false;
        }

        return await this.promptProcurementWarningDecision(invoiceName, preview, links);
    }



    activeProcurementLinksForSubmitV59(invoiceName) {
        const links = Object.assign({}, this.procurementLinks || {});
        if (invoiceName) {
            links.purchase_invoice = invoiceName;
            links.purchase_invoice_doctype = "Purchase Invoice";
        }
        return links;
    }

    procurementHasUpstreamSourceV59(links) {
        links = links || {};
        return !!(links.purchase_request || links.material_request || links.purchase_order || links.purchase_receipt);
    }

    procurementIssueListHtmlV59(preview) {
        const summary = (preview && preview.summary) || {};
        const issues = summary.issues || [];
        if (!issues.length) {
            return `<div class="text-muted">${__("No detailed issue rows were returned.")}</div>`;
        }
        return `
            <ul style="padding-inline-start:18px; margin:8px 0; line-height:1.7;">
                ${issues.map((issue) => `
                    <li>
                        <strong>${this.escape((issue.severity || "warning").toUpperCase())}</strong>
                        ${issue.item_name || issue.item_code ? ` — ${this.escape(issue.item_name || issue.item_code)}` : ""}<br>
                        <span>${this.escape(issue.message || issue.code || "")}</span>
                    </li>
                `).join("")}
            </ul>`;
    }

    procurementSubmitSummaryHtmlV59(preview) {
        const summary = (preview && preview.summary) || {};
        return `
            <div class="pimv1-match-grid" style="margin-top:8px;">
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Ordered Qty")}</div><div class="pimv1-match-value">${this.number(summary.ordered_qty)}</div></div>
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Received Qty")}</div><div class="pimv1-match-value">${this.number(summary.received_qty)}</div></div>
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Invoiced Qty")}</div><div class="pimv1-match-value">${this.number(summary.invoiced_qty)}</div></div>
                <div class="pimv1-match-box"><div class="pimv1-match-label">${__("Receipt vs Invoice")}</div><div class="pimv1-match-value">${this.number(summary.received_vs_invoiced_qty)}</div></div>
            </div>`;
    }

    async logProcurementSubmitReviewV59(invoiceName, preview, links, reason) {
        const summary = (preview && preview.summary) || {};
        await frappe.call({
            method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.log_procurement_match_decision",
            args: {
                payload: JSON.stringify({
                    purchase_invoice: invoiceName,
                    decision: "accepted_warning_before_submit",
                    match_status: summary.match_status || "warning",
                    reason: reason || "",
                    links: links || {},
                    summary: summary,
                    issues: summary.issues || [],
                }),
            },
            freeze: true,
            freeze_message: __("Recording procurement submit review..."),
        });
    }

    promptProcurementWarningSubmitV59(invoiceName, preview, links) {
        return new Promise((resolve) => {
            let accepted = false;
            const dialog = new frappe.ui.Dialog({
                title: __("Review Procurement Warnings Before Submit"),
                fields: [
                    {
                        fieldtype: "HTML",
                        fieldname: "warning_html",
                        options: `
                            <div style="line-height:1.7; max-width:780px;">
                                <div class="text-warning"><strong>${__("This invoice has procurement warnings.")}</strong></div>
                                <div class="text-muted">${__("Warnings may be operationally acceptable. Example: the supplier sent a real lower quantity, extra item, or wrong item. Enter the invoice as-is only if this is the real supplier invoice, then handle return/credit note if needed.")}</div>
                                ${this.procurementSubmitSummaryHtmlV59(preview)}
                                <div style="margin-top:10px;"><strong>${__("Warnings")}</strong></div>
                                ${this.procurementIssueListHtmlV59(preview)}
                            </div>`,
                    },
                    {
                        fieldtype: "Small Text",
                        fieldname: "reason",
                        label: __("Operational reason for continuing"),
                        reqd: 1,
                        description: __("This reason will be saved in the Purchase Invoice timeline before submit."),
                    },
                ],
                primary_action_label: __("Accept Warning & Continue Submit"),
                primary_action: async (values) => {
                    const reason = (values && values.reason ? values.reason : "").trim();
                    if (!reason) {
                        frappe.msgprint(__("Reason is required."));
                        return;
                    }
                    try {
                        await this.logProcurementSubmitReviewV59(invoiceName, preview, links, reason);
                        accepted = true;
                        dialog.hide();
                        frappe.show_alert({ message: __("Procurement warning review recorded."), indicator: "orange" }, 5);
                        resolve(true);
                    } catch (error) {
                        console.error("Unable to record procurement submit review", error);
                        frappe.msgprint({
                            title: __("Procurement Submit Review"),
                            message: this.escape(error.message || error),
                            indicator: "red",
                        });
                    }
                },
            });
            dialog.onhide = () => {
                if (!accepted) resolve(false);
            };
            dialog.show();
        });
    }

    async ensureProcurementSubmitDecisionV59(invoiceName) {
        const links = this.activeProcurementLinksForSubmitV59(invoiceName);

        // Direct supplier invoice outside the shortage/procurement cycle is allowed.
        // It should not be blocked just because a draft Purchase Invoice exists.
        if (!this.procurementHasUpstreamSourceV59(links)) {
            frappe.show_alert({
                message: __("Direct Purchase Invoice: no linked Purchase Request / Order / Receipt was found."),
                indicator: "blue",
            }, 5);
            return true;
        }

        this.procurementLinks = links;
        this.saveProcurementLinks();

        const preview = await this.fetchProcurementMatchPreview(false);
        if (!preview || !preview.summary) {
            frappe.msgprint({
                title: __("Procurement Submit Guard"),
                message: __("Unable to refresh Procurement Match Preview. Please refresh the match before submitting."),
                indicator: "red",
            });
            return false;
        }

        const summary = preview.summary || {};
        const status = String(summary.match_status || "matched").toLowerCase();

        if (status === "matched") {
            frappe.show_alert({ message: __("Procurement match confirmed. Invoice can be submitted."), indicator: "green" }, 5);
            return true;
        }

        if (status === "mismatch") {
            frappe.msgprint({
                title: __("Procurement Mismatch"),
                message: `
                    <div style="line-height:1.7; max-width:780px;">
                        <div class="text-danger"><strong>${__("Submit blocked because there is a serious procurement mismatch.")}</strong></div>
                        <div class="text-muted">${__("Fix the quantities or linked documents first, then refresh the match and submit again.")}</div>
                        ${this.procurementSubmitSummaryHtmlV59(preview)}
                        <div style="margin-top:10px;"><strong>${__("Mismatch details")}</strong></div>
                        ${this.procurementIssueListHtmlV59(preview)}
                    </div>`,
                indicator: "red",
            });
            return false;
        }

        return await this.promptProcurementWarningSubmitV59(invoiceName, preview, links);
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
            const decisionOk = await this.ensureProcurementSubmitDecisionV59(saved.name);
            if (!decisionOk) return;
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
        await this.refreshOpenProcurementDrafts({ silent: true });
        await this.refreshSupplierSettlement({ silent: true });
        const submittedProcurement = Array.isArray(message.submitted_procurement)
            ? message.submitted_procurement
            : [];
        const submittedChainText = submittedProcurement.length
            ? __(" Linked procurement stages submitted: {0}.", [
                submittedProcurement.map((row) => row.name).join(" → "),
            ])
            : "";
        frappe.show_alert({
            message: __("Purchase Invoice {0} submitted successfully.", [invoice.name || this.draftName]) + submittedChainText,
            indicator: "green",
        }, 9);
        return invoice;
    }

    async submitInvoice() {
        if (!this.draftName || !this.validateAndReport()) return;
        const decisionOk = await this.ensureProcurementSubmitDecisionV59(this.draftName);
        if (!decisionOk) return;
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
            await this.refreshOpenProcurementDrafts({ silent: true });
            await this.refreshSupplierSettlement({ silent: true });
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
                    freeze_message: __("Loading Purchase Invoice..."),
                });
                const message = response.message || {};
                const invoice = message.invoice || {};
                await this.applyLoadedInvoice(message.payload || {}, invoice, message.procurement_links || {});
                this.toggleRecentPanel(false);
                const readOnly = cint(invoice.docstatus) !== 0 || cint(message.read_only);
                frappe.show_alert({
                    message: readOnly
                        ? __("Invoice {0} opened in read-only settlement mode.", [invoiceName])
                        : __("Draft {0} loaded into the purchase page.", [invoiceName]),
                    indicator: readOnly ? "blue" : "green",
                }, 7);
            } catch (error) {
                console.error("Unable to open Purchase Invoice", error);
                frappe.msgprint({
                    title: __("Unable to Open Invoice"),
                    message: __("Purchase Invoice {0} could not be opened. Refresh the page and try again.", [invoiceName]),
                    indicator: "red",
                });
            }
        };

        if ((this.rows.length || this.draftName) && this.draftName !== invoiceName) {
            frappe.confirm(__("Open invoice {0} and replace the current page data?", [invoiceName]), load);
        } else {
            await load();
        }
    }

    async applyLoadedInvoice(payload, invoice, procurementLinks = {}) {
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
        this.applyProcurementChain(procurementLinks || {}, { replace: true });
        await this.fetchProcurementMatchPreview(false);
        await this.refreshSupplierSettlement({ silent: true });
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

    openDraftValue(fieldname) {
        return this.openDraftControls[fieldname] ? this.openDraftControls[fieldname].get_value() : "";
    }

    openDraftStageLabel(stage) {
        const labels = {
            purchase_request: __("Request"),
            purchase_order: __("Order"),
            purchase_receipt: __("Receipt"),
            purchase_invoice: __("Invoice"),
        };
        return labels[stage] || stage || __("Draft");
    }

    renderOpenProcurementDrafts(payload) {
        const data = payload || { drafts: [], counts: {}, progress_counts: {}, total: 0, all_status_total: 0 };
        const drafts = data.drafts || [];
        const counts = data.counts || {};
        const progressCounts = data.progress_counts || {};
        const total = Number(data.total !== undefined ? data.total : drafts.length) || 0;
        const allStatusTotal = Number(data.all_status_total !== undefined ? data.all_status_total : total) || 0;
        this.$main.find("[data-role='open-drafts-count']").text(total);
        const countCard = (label, value) => `<div class="pimv1-open-draft-count"><span>${this.escape(label)}</span><strong>${Number(value || 0)}</strong></div>`;
        this.$main.find("[data-role='open-drafts-summary']").html([
            countCard(__("Filtered Results"), total),
            countCard(__("All Statuses"), allStatusTotal),
            countCard(__("Open"), progressCounts.open),
            countCard(__("Partial"), progressCounts.partial),
            countCard(__("Done"), progressCounts.done),
            countCard(__("Requests"), counts.purchase_request),
            countCard(__("Orders"), counts.purchase_order),
            countCard(__("Receipts"), counts.purchase_receipt),
            countCard(__("Invoices"), counts.purchase_invoice),
        ].join(""));

        const $results = this.$main.find("[data-role='open-drafts-results']");
        if (!drafts.length) {
            $results.html(`<div class="pimv1-empty">${__("No procurement drafts match the current filters.")}</div>`);
            return;
        }

        $results.html(`
            <table class="pimv1-open-drafts-table">
                <thead><tr>
                    <th>${__("Stage")}</th><th>${__("Document")}</th><th>${__("Operational Status")}</th>
                    <th>${__("Linked Next Stage")}</th><th>${__("Supplier")}</th><th>${__("Date")}</th>
                    <th>${__("Items / Qty")}</th><th>${__("Continued / Remaining")}</th><th>${__("Total")}</th>
                    <th>${__("Open Age")}</th><th>${__("Next Action")}</th><th>${__("Actions")}</th>
                </tr></thead>
                <tbody>${drafts.map((row) => {
                    const stage = row.stage || "";
                    const progress = row.operational_status || "open";
                    const daysOpen = Number(row.days_open || 0);
                    const supplier = row.supplier_name || row.supplier || __("Not selected yet");
                    const totalValue = stage === "purchase_request" ? "—" : this.money(row.grand_total || 0);
                    const nextCount = Number(row.next_documents_count || 0);
                    const nextDocument = row.next_document_name
                        ? `<div class="pimv1-open-draft-chain"><strong>${this.escape(this.openDraftStageLabel(row.next_document_stage))}</strong><br>${this.escape(row.next_document_name)}${nextCount > 1 ? `<br><span class="text-muted">+${nextCount - 1} ${__("more linked document(s)")}</span>` : ""}</div>`
                        : `<span class="text-muted">—</span>`;

                    let continueAction = "";
                    if (stage === "purchase_invoice") {
                        continueAction = `<button type="button" class="btn btn-xs btn-primary pimv1-open-draft-next" data-action="continue-open-draft" data-stage="${this.escape(stage)}" data-name="${this.escape(row.name)}">${__("Open in Page")}</button>`;
                    } else if (progress === "done" && row.next_document_name && row.next_document_stage) {
                        continueAction = `<button type="button" class="btn btn-xs btn-primary pimv1-open-draft-next" data-action="continue-open-draft" data-stage="${this.escape(row.next_document_stage)}" data-name="${this.escape(row.next_document_name)}">${this.escape(row.next_action || __("Open Linked Stage"))}</button>`;
                    } else {
                        continueAction = `<button type="button" class="btn btn-xs btn-primary pimv1-open-draft-next" data-action="continue-open-draft" data-stage="${this.escape(stage)}" data-name="${this.escape(row.name)}">${this.escape(row.next_action || __("Continue"))}</button>`;
                    }

                    return `<tr>
                        <td><span class="pimv1-open-draft-stage ${this.escape(stage)}">${this.escape(row.stage_label || this.openDraftStageLabel(stage))}</span></td>
                        <td><strong>${this.escape(row.name || "")}</strong><br><span class="text-muted">${this.escape(row.status || __("Draft"))}</span></td>
                        <td><span class="pimv1-open-draft-progress ${this.escape(progress)}">${this.escape(row.operational_status_label || progress)}</span></td>
                        <td>${nextDocument}</td>
                        <td>${this.escape(supplier)}</td>
                        <td>${this.escape(row.date || "—")}</td>
                        <td>${Number(row.items_count || 0)} / ${this.number(row.total_qty || 0)}</td>
                        <td>${this.number(row.used_qty || 0)} / <strong>${this.number(row.remaining_qty || 0)}</strong></td>
                        <td>${totalValue}</td>
                        <td><span class="pimv1-open-draft-age ${daysOpen >= 7 ? "stale" : ""}">${daysOpen === 0 ? __("Today") : __("{0} day(s)", [daysOpen])}</span></td>
                        <td>${this.escape(row.next_action || "")}</td>
                        <td><div class="pimv1-open-draft-actions">
                            ${continueAction}
                            <button type="button" class="btn btn-xs btn-default" data-action="open-procurement-official" data-doctype="${this.escape(row.doctype)}" data-name="${this.escape(row.name)}">${__("Official Document")}</button>
                        </div></td>
                    </tr>`;
                }).join("")}</tbody>
            </table>
        `);
    }

    async refreshOpenProcurementDrafts(options = {}) {
        const $status = this.$main.find("[data-role='open-drafts-status']");
        if (!options.silent) $status.text(__("Loading open procurement drafts..."));
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_open_procurement_drafts",
                args: {
                    company: this.value("company") || this.bootstrap.company || "",
                    supplier: this.openDraftValue("supplier") || "",
                    stage: this.openDraftValue("stage") || "",
                    progress_status: this.openDraftValue("progress_status") || "active",
                    search_text: this.openDraftValue("search_text") || "",
                    limit: 60,
                },
            });
            this.openProcurementDrafts = response.message || { drafts: [], counts: {}, total: 0 };
            this.bootstrap.open_procurement_drafts = this.openProcurementDrafts;
            this.renderOpenProcurementDrafts(this.openProcurementDrafts);
            $status.text(__("{0} result(s) shown from {1} draft stage(s). Completed stages remain available through Operational Status = All or Done.", [this.openProcurementDrafts.total || 0, this.openProcurementDrafts.all_status_total || this.openProcurementDrafts.total || 0]));
            return this.openProcurementDrafts;
        } catch (error) {
            $status.text(__("Could not load open procurement drafts."));
            if (!options.silent) throw error;
            return null;
        }
    }

    async clearOpenProcurementDraftFilters() {
        const tasks = Object.entries(this.openDraftControls).map(([fieldname, control]) =>
            control.set_value(fieldname === "progress_status" ? "active" : "")
        );
        await Promise.all(tasks);
        return this.refreshOpenProcurementDrafts();
    }

    continueOpenProcurementDraft(event) {
        const $button = $(event.currentTarget);
        const stage = String($button.data("stage") || "");
        const name = String($button.data("name") || "");
        if (!name) return;
        if (stage === "purchase_invoice") {
            this.loadDraftInvoice(name);
            return;
        }
        if (["purchase_request", "purchase_order", "purchase_receipt"].includes(stage)) {
            this.openProcurementSourcePicker(stage, name);
        }
    }

    openOfficialDocument() {
        if (this.draftName) frappe.set_route("Form", "Purchase Invoice", this.draftName);
    }

    toggleOpenDraftsPanel(forceOpen = null) {
        this.openDraftsPanelOpen = forceOpen === null ? !this.openDraftsPanelOpen : Boolean(forceOpen);
        this.$main.find("[data-role='open-drafts-panel']").toggleClass("is-open", this.openDraftsPanelOpen);
        this.$main.find("[data-action='toggle-open-drafts']").toggleClass("is-open", this.openDraftsPanelOpen);
        if (this.openDraftsPanelOpen) this.refreshOpenProcurementDrafts({ silent: true });
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
                    <button type="button" class="btn btn-xs btn-primary" data-action="load-draft" data-name="${this.escape(row.name)}">${__("Open in Page")}</button>
                    ${cint(row.docstatus) === 1 && !cint(row.is_return) ? `<button type="button" class="btn btn-xs btn-warning" data-action="create-purchase-return" data-name="${this.escape(row.name)}">${__("Create Return")}</button>` : ""}
                    <button type="button" class="btn btn-xs btn-default" data-action="preview-procurement-summary" data-name="${this.escape(row.name)}">${__("Summary / Print")}</button>
                    <button type="button" class="btn btn-xs btn-default" data-action="open-invoice" data-name="${this.escape(row.name)}">${__("Official Document")}</button>
                </div></td>
            </tr>`).join("")}
            </tbody></table>
        `);
    }

    async getPrintIdentity(company) {
        const key = company || "__default__";
        if (this.printIdentityCache[key]) return this.printIdentityCache[key];
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.print_settings.get_print_identity",
                args: { company: company || "" },
            });
            this.printIdentityCache[key] = response.message || {};
        } catch (error) {
            console.warn("Unable to load print identity", error);
            this.printIdentityCache[key] = {
                company: company || "",
                name_lines: [company || ""].filter(Boolean),
                display_title: company || "",
            };
        }
        return this.printIdentityCache[key];
    }

    procurementPrintHeaderHtml(identity = {}, invoice = {}) {
        const nameLines = Array.isArray(identity.name_lines) && identity.name_lines.length
            ? identity.name_lines
            : [identity.display_title || invoice.company || ""].filter(Boolean);
        const logo = identity.logo || "";
        const contactLines = [
            identity.phone ? `${__("Phone")}: ${identity.phone}` : "",
            identity.address || "",
        ].filter(Boolean);
        return `
            <div class="pimv1-print-identity">
                ${logo ? `<img src="${this.escape(logo)}" alt="">` : ""}
                <div>
                    ${nameLines.map((line) => `<div style="font-size:17px;font-weight:900;line-height:1.3">${this.escape(line)}</div>`).join("")}
                    ${contactLines.map((line) => `<div class="pimv1-print-subtitle">${this.escape(line)}</div>`).join("")}
                    ${identity.footer_note ? `<div class="pimv1-print-subtitle">${this.escape(identity.footer_note)}</div>` : ""}
                </div>
            </div>`;
    }

    procurementPrintDate(value) {
        if (!value) return "—";
        try { return frappe.datetime.str_to_user(value); } catch (error) { return String(value); }
    }

    procurementSummaryContent(data, identity = {}) {
        const invoice = data.invoice || {};
        const totals = data.totals || {};
        const match = data.match || {};
        const matchSummary = match.summary || {};
        const rows = match.rows || [];
        const decision = data.decision || {};
        const status = String(matchSummary.match_status || (data.is_direct_invoice ? "direct" : "matched")).toLowerCase();
        const statusLabel = matchSummary.status_label || (data.is_direct_invoice ? __("Direct Invoice") : __("Matched"));
        const statusBadge = `<span class="pimv1-print-status ${this.escape(status)}">${this.escape(statusLabel)}</span>`;
        const stageHtml = (data.stages || []).map((stage) => {
            const docs = stage.documents || [];
            const documentsHtml = docs.length ? docs.map((doc) => `
                <div style="margin-top:5px;line-height:1.55">
                    <strong>${this.escape(doc.name)}</strong><br>
                    <span class="pimv1-print-status ${this.escape(doc.operational_status || "open")}">${this.escape(doc.operational_status_label || doc.status || "")}</span>
                    <div class="pimv1-print-subtitle">${this.escape(this.procurementPrintDate(doc.date))} · ${__("Qty")}: ${this.number(doc.total_qty)}${doc.remaining_qty > 0 ? ` · ${__("Remaining")}: ${this.number(doc.remaining_qty)}` : ""}</div>
                </div>`).join("") : `<div class="pimv1-print-subtitle">${__("Not linked")}</div>`;
            return `<div class="pimv1-print-stage"><h5>${this.escape(stage.stage_label || stage.stage || "")}</h5>${documentsHtml}</div>`;
        }).join("");

        const issueRows = (matchSummary.issues || []).map((issue) => `<li><strong>${this.escape((issue.severity || "warning").toUpperCase())}</strong>${issue.item_name || issue.item_code ? ` — ${this.escape(issue.item_name || issue.item_code)}` : ""}: ${this.escape(issue.message || issue.code || "")}</li>`).join("");
        const itemsHtml = rows.length ? rows.map((row, index) => `
            <tr>
                <td>${index + 1}</td>
                <td><strong>${this.escape(row.item_name || row.item_code || "")}</strong><div class="pimv1-print-subtitle">${this.escape(row.item_code || "")}</div></td>
                <td>${this.number(row.requested_qty)}</td>
                <td>${this.number(row.ordered_qty)}</td>
                <td>${this.number(row.received_qty)}</td>
                <td>${this.number(row.invoiced_qty)}</td>
                <td><span class="pimv1-print-status ${this.escape(row.status || status)}">${this.escape(row.status === "direct" ? __("Direct") : (row.status || statusLabel))}</span>${row.issues_text ? `<div class="pimv1-print-subtitle">${this.escape(row.issues_text)}</div>` : ""}</td>
            </tr>`).join("") : `<tr><td colspan="7">${__("No item rows were found.")}</td></tr>`;

        const totalBoxes = [
            [__("Supplier Invoice Gross"), totals.supplier_invoice_gross],
            [__("Supplier Discount"), totals.supplier_discount],
            [__("Additional Line Discount"), totals.additional_line_discount],
            [__("Net Before VAT"), totals.net_before_vat],
            [__("Item VAT"), totals.item_vat],
            [__("Bonus VAT"), totals.bonus_vat],
            [__("Shipping / Charges"), totals.shipping],
            [__("Invoice Discount"), totals.invoice_discount],
            [__("Fraction Adjustment"), totals.fraction_adjustment],
            [__("Grand Total"), totals.grand_total],
            [__("Supplier Invoice Total"), totals.supplier_invoice_total],
            [__("Outstanding"), totals.outstanding_amount],
        ].map(([label, value]) => `<div class="pimv1-print-box"><b>${this.escape(label)}</b><strong>${this.money(value || 0)}</strong></div>`).join("");

        return `
            ${this.procurementPrintHeaderHtml(identity, invoice)}
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
                <div><div class="pimv1-print-title">${__("Operational Procurement Summary")}</div><div class="pimv1-print-subtitle">${data.is_direct_invoice ? __("Direct purchase invoice without an upstream procurement cycle.") : __("Request → Order → Receipt → Invoice")}</div></div>
                <div>${statusBadge}</div>
            </div>
            <div class="pimv1-print-meta">
                <div class="pimv1-print-box"><b>${__("Purchase Invoice")}</b><strong>${this.escape(invoice.name || "—")}</strong></div>
                <div class="pimv1-print-box"><b>${__("Supplier")}</b><strong>${this.escape(invoice.supplier_name || invoice.supplier || "—")}</strong></div>
                <div class="pimv1-print-box"><b>${__("Supplier Bill")}</b><strong>${this.escape(invoice.bill_no || "—")}</strong></div>
                <div class="pimv1-print-box"><b>${__("Status")}</b><strong>${this.escape(invoice.status || "—")}</strong></div>
                <div class="pimv1-print-box"><b>${__("Posting Date")}</b><strong>${this.escape(this.procurementPrintDate(invoice.posting_date))}</strong></div>
                <div class="pimv1-print-box"><b>${__("Due Date")}</b><strong>${this.escape(this.procurementPrintDate(invoice.due_date))}</strong></div>
                <div class="pimv1-print-box"><b>${__("Warehouse")}</b><strong>${this.escape(invoice.warehouse || "—")}</strong></div>
                <div class="pimv1-print-box"><b>${__("Classification")}</b><strong>${this.escape(invoice.payment_classification || "—")}</strong></div>
            </div>
            <div class="pimv1-print-section"><h4>${__("Procurement Stages")}</h4><div class="pimv1-print-stage-grid">${stageHtml}</div></div>
            <div class="pimv1-print-section"><h4>${__("Quantity Match")}</h4>
                <table class="pimv1-print-table"><thead><tr><th>#</th><th>${__("Item")}</th><th>${__("Requested")}</th><th>${__("Ordered")}</th><th>${__("Received")}</th><th>${__("Invoiced")}</th><th>${__("Match")}</th></tr></thead><tbody>${itemsHtml}</tbody></table>
            </div>
            ${(issueRows || decision.reason) ? `<div class="pimv1-print-section pimv1-print-warning"><h4>${__("Operational Review")}</h4>${issueRows ? `<ul style="margin:5px 0;padding-inline-start:18px">${issueRows}</ul>` : ""}${decision.reason ? `<div><strong>${__("Accepted Warning Reason")}:</strong> ${this.escape(decision.reason)}</div><div class="pimv1-print-subtitle">${this.escape(decision.user || "")} · ${this.escape(this.procurementPrintDate(decision.creation))}</div>` : ""}</div>` : ""}
            <div class="pimv1-print-section"><h4>${__("Invoice Totals")}</h4><div class="pimv1-print-totals">${totalBoxes}</div></div>
            ${invoice.remarks ? `<div class="pimv1-print-section"><h4>${__("Notes")}</h4><div class="pimv1-print-box">${this.escape(invoice.remarks)}</div></div>` : ""}
            <div class="pimv1-print-generated">${__("Generated by")}: ${this.escape((data.generated || {}).by || "")} · ${this.escape(this.procurementPrintDate((data.generated || {}).at))}</div>`;
    }

    procurementPrintDocument(data, identity) {
        const popup = window.open("", "_blank");
        if (!popup) {
            frappe.msgprint(__("Please allow popups to print."));
            return;
        }
        const content = this.procurementSummaryContent(data, identity);
        const html = `<!doctype html><html><head><meta charset="utf-8"><title>${this.escape((data.invoice || {}).name || __("Operational Procurement Summary"))}</title><style>
            @page{size:A4 portrait;margin:7mm}html,body{font-family:Arial,Tahoma,sans-serif;color:#111;margin:0;font-size:10.5px;direction:rtl;text-align:right}.pimv1-print-identity{display:flex;align-items:center;gap:12px;padding-bottom:8px;margin-bottom:9px;border-bottom:1px solid #ccc}.pimv1-print-identity img{width:28mm;max-height:20mm;object-fit:contain}.pimv1-print-title{font-size:18px;font-weight:900;margin-bottom:2px}.pimv1-print-subtitle{color:#555;font-size:9.5px;line-height:1.35}.pimv1-print-meta,.pimv1-print-totals{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin:7px 0}.pimv1-print-box,.pimv1-print-stage{border:1px solid #ccc;border-radius:5px;padding:5px;min-width:0}.pimv1-print-box b{display:block;color:#555;font-size:9px;margin-bottom:2px}.pimv1-print-stage-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin:6px 0}.pimv1-print-stage h5{margin:0 0 3px;font-size:11px}.pimv1-print-table{width:100%;border-collapse:collapse;font-size:9.5px;margin-top:5px}.pimv1-print-table th,.pimv1-print-table td{border:1px solid #ccc;padding:4px;text-align:right;vertical-align:top}.pimv1-print-table th{background:#f2f2f2;white-space:nowrap}.pimv1-print-status{display:inline-block;padding:2px 5px;border:1px solid #bbb;border-radius:999px;font-weight:800;font-size:8.5px}.pimv1-print-status.matched,.pimv1-print-status.done{background:#e8f7ee}.pimv1-print-status.warning,.pimv1-print-status.partial{background:#fff4d6}.pimv1-print-status.mismatch,.pimv1-print-status.cancelled{background:#fde8e8}.pimv1-print-status.direct,.pimv1-print-status.open{background:#e8f1ff}.pimv1-print-section{margin-top:8px;page-break-inside:avoid}.pimv1-print-section h4{margin:0 0 4px;font-size:12px}.pimv1-print-warning{border:1px solid #e0b84f;background:#fff9e8;border-radius:5px;padding:6px}.pimv1-print-totals .pimv1-print-box strong{white-space:nowrap}.pimv1-print-page{padding-bottom:9mm}.pimv1-print-generated{margin-top:6px;padding-top:3px;border-top:1px solid #ddd;color:#555;font-size:8.5px;line-height:1.2;text-align:right}@media print{html,body{height:auto!important;overflow:visible!important}body{-webkit-print-color-adjust:exact;print-color-adjust:exact}.pimv1-print-generated{position:fixed;right:0;left:0;bottom:0;margin:0;padding:3px 0 0;background:#fff;border-top:1px solid #ddd}.pimv1-print-section{break-inside:avoid;page-break-inside:avoid}}
        </style></head><body onload="setTimeout(function(){window.focus();window.print();},300)"><main class="pimv1-print-page">${content}</main></body></html>`;
        popup.document.open();
        popup.document.write(html);
        popup.document.close();
    }

    async openProcurementSummaryPreview(invoiceName = "") {
        invoiceName = String(invoiceName || this.draftName || "").trim();
        if (!invoiceName) {
            frappe.msgprint({
                title: __("Operational Procurement Summary"),
                message: __("Save the Purchase Invoice as a Draft first, then open Summary / Print. The summary uses official saved documents and links."),
                indicator: "orange",
            });
            return;
        }
        try {
            const response = await frappe.call({
                method: "pharma_erp.pharma_erp.page.purchase_invoice_management.purchase_invoice_management.get_procurement_operational_summary",
                args: { invoice_name: invoiceName },
                freeze: true,
                freeze_message: __("Preparing operational procurement summary..."),
            });
            const data = response.message || {};
            const identity = await this.getPrintIdentity((data.invoice || {}).company || this.value("company"));
            const dialog = new frappe.ui.Dialog({
                title: __("Operational Procurement Summary"),
                size: "extra-large",
                fields: [{ fieldtype: "HTML", fieldname: "summary_preview" }],
                primary_action_label: __("Print A4"),
                primary_action: () => this.procurementPrintDocument(data, identity),
                secondary_action_label: __("Close"),
                secondary_action: () => dialog.hide(),
            });
            dialog.fields_dict.summary_preview.$wrapper.html(`<div class="pimv1-print-preview-shell">${this.procurementSummaryContent(data, identity)}</div>`);
            dialog.show();
        } catch (error) {
            console.error("Unable to prepare procurement summary", error);
            frappe.msgprint({
                title: __("Operational Procurement Summary"),
                message: this.escape(error.message || error),
                indicator: "red",
            });
        }
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
