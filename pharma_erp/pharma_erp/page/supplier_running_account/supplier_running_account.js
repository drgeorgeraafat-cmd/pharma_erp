frappe.pages["supplier-running-account"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Supplier Running Account"),
        single_column: true,
    });
    new SupplierRunningAccountPage(page, wrapper);
};

class SupplierRunningAccountPage {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.$main = page.main ? $(page.main) : $(wrapper).find(".layout-main-section");
        this.controls = {};
        this.rows = [];
        this.summary = {};
        this.currency = null;
        this.addStyles();
        this.render();
        this.page.set_primary_action(__("Load Statement"), () => this.loadStatement(), "refresh");
        this.page.add_inner_button(__("Export CSV"), () => this.exportCsv(), __("Actions"));
        this.page.add_inner_button(__("Open Supplier"), () => this.openSupplier(), __("Actions"));
        this.page.add_inner_button(__("Create Payment Draft"), () => this.openPaymentDraftDialog(), __("Actions"));
        this.page.add_inner_button(__("Use Existing Advance"), () => this.openUseExistingAdvanceDialog(), __("Actions"));
        this.page.add_inner_button(__("Create Supplier Claim Draft"), () => this.openSupplierClaimDraftDialog(), __("Actions"));
        this.loadBootstrap();
    }

    addStyles() {
        if ($("#supplier-running-account-style").length) return;
        $("head").append(`
            <style id="supplier-running-account-style">
                .sra { direction: rtl; text-align: right; padding-bottom: 34px; }
                .sra * { box-sizing: border-box; }
                .sra-hero { display:flex; justify-content:space-between; align-items:flex-start; gap:14px; padding:18px; border:1px solid var(--border-color); border-radius:16px; background:linear-gradient(135deg, var(--card-bg), var(--control-bg)); margin-bottom:14px; }
                .sra-hero h2 { margin:0 0 6px; font-weight:800; }
                .sra-muted { color:var(--text-muted); }
                .sra-filters { display:grid; grid-template-columns:repeat(4, minmax(180px,1fr)); gap:10px; border:1px solid var(--border-color); border-radius:14px; background:var(--card-bg); padding:14px; margin-bottom:14px; }
                .sra-checkboxes { display:flex; align-items:center; justify-content:flex-start; gap:10px; flex-wrap:wrap; grid-column:1 / -1; padding-top:8px; direction:rtl; }
                .sra-checkboxes .frappe-control { margin:0 !important; }
                .sra-checkboxes .checkbox { margin:0 !important; padding:7px 11px; border:1px solid var(--border-color); border-radius:10px; background:var(--control-bg); min-width:170px; }
                .sra-checkboxes .checkbox label { display:flex; align-items:center; gap:7px; margin:0 !important; font-weight:650; color:var(--text-color); line-height:1.2; }
                .sra-checkboxes .checkbox input[type="checkbox"] { margin:0 !important; transform:scale(1.08); }
                .sra-checkboxes .checkbox .label-area { padding:0 !important; }
                .sra-cards { display:grid; grid-template-columns:repeat(4, minmax(160px,1fr)); gap:10px; margin-bottom:14px; }
                .sra-card { border:1px solid var(--border-color); border-radius:14px; background:var(--card-bg); padding:13px; min-height:88px; }
                .sra-card-label { color:var(--text-muted); font-size:12px; }
                .sra-card-value { font-size:20px; font-weight:800; margin-top:7px; direction:ltr; text-align:right; }
                .sra-table-wrap { border:1px solid var(--border-color); border-radius:14px; overflow:auto; background:var(--card-bg); }
                .sra-table { width:100%; border-collapse:separate; border-spacing:0; min-width:1250px; }
                .sra-table th { position:sticky; top:0; z-index:1; background:var(--subtle-fg); color:var(--text-muted); font-size:11px; font-weight:800; padding:9px 8px; border-bottom:1px solid var(--border-color); text-align:right; white-space:nowrap; }
                .sra-table td { padding:10px 8px; border-bottom:1px solid var(--border-color); font-size:12px; vertical-align:top; }
                .sra-table tbody tr:hover td { filter:brightness(0.99); }
                .sra-table tr:last-child td { border-bottom:0; }
                .sra-balance-row td { background:#f5f7fa; font-weight:800; border-top:1px solid var(--border-color); border-bottom:1px solid var(--border-color); }
                .sra-balance-row .sra-balance-label { color:var(--text-muted); font-weight:800; }
                .sra-amount { direction:ltr; text-align:left; font-weight:700; white-space:nowrap; }
                .sra-credit-amount { color:#8a5a12; }
                .sra-debit-amount { color:#0b6e4f; }
                .sra-balance-positive { color:#1f2937; }
                .sra-balance-negative { color:#0b6e4f; }
                .sra-doclink { direction:ltr; display:inline-block; font-weight:700; }
                .sra-pill { display:inline-flex; border-radius:999px; padding:3px 8px; font-size:11px; font-weight:700; background:var(--control-bg); border:1px solid var(--border-color); }
                .sra-pill-muted { color:var(--text-muted); }
                .sra-pill-balance { background:#eef2f7; border-color:#d8e0ea; color:#425466; }
                .sra-pill-invoice { background:#fff4df; border-color:#f4d6a1; color:#8a5a12; }
                .sra-pill-return { background:#e8f7ff; border-color:#b6def3; color:#0f5f8a; }
                .sra-pill-payment { background:#eaf8ef; border-color:#bfe1c9; color:#0b6e4f; }
                .sra-pill-refund { background:#eefcff; border-color:#c8e9f1; color:#0b7285; }
                .sra-pill-journal { background:#f4efff; border-color:#d8c9f0; color:#6b46c1; }
                .sra-pill-context { background:#fff8db; border-color:#f2e3a0; color:#8a6d1d; }
                .sra-action-badge { display:inline-flex; align-items:center; border-radius:999px; padding:3px 8px; font-size:11px; font-weight:800; white-space:nowrap; border:1px solid var(--border-color); background:var(--control-bg); }
                .sra-action-direct { background:#eaf8ef; border-color:#bfe1c9; color:#0b6e4f; }
                .sra-action-claim { background:#fff4df; border-color:#f4d6a1; color:#8a5a12; }
                .sra-action-linked { background:#f4efff; border-color:#d8c9f0; color:#6b46c1; }
                .sra-action-settled { background:#eef2f7; border-color:#d8e0ea; color:#425466; }
                .sra-action-return { background:#e8f7ff; border-color:#b6def3; color:#0f5f8a; }
                .sra-action-other { background:#f7f7f7; border-color:#e0e0e0; color:#666; }
                .sra-filter-help { color:var(--text-muted); font-size:11px; margin-top:4px; }
                .sra-row-context td { background:var(--yellow-50); }
                .sra-row-invoice td { background:#fffbf3; }
                .sra-row-return td { background:#f4fbff; }
                .sra-row-payment td { background:#f4fcf6; }
                .sra-row-refund td { background:#f2fcff; }
                .sra-row-journal td { background:#faf7ff; }
                .sra-row-balance td { background:#f5f7fa; }
                .sra-row-cancelled { opacity:.68; text-decoration:line-through; }
                .sra-empty { padding:34px; text-align:center; color:var(--text-muted); }
                .sra-note { margin:10px 0 0; padding:10px 12px; border-radius:12px; background:var(--control-bg); color:var(--text-muted); font-size:12px; }
                body[data-route="supplier-running-account"] .page-container,
                body[data-route="supplier-running-account"] .page-content,
                body[data-route="supplier-running-account"] .page-body,
                body[data-route="supplier-running-account"] .standard-page,
                body[data-route="supplier-running-account"] .container,
                body[data-route="supplier-running-account"] .layout-main-section-wrapper,
                body[data-route="supplier-running-account"] .layout-main-section {
                    max-width:none !important;
                    width:100% !important;
                    margin-left:0 !important;
                    margin-right:0 !important;
                    padding-left:6px !important;
                    padding-right:6px !important;
                }
                body[data-route="supplier-running-account"] .sra {
                    width:calc(100vw - 28px) !important;
                    max-width:none !important;
                    margin-left:0 !important;
                    margin-right:0 !important;
                }
                .sra-full-table-mode { max-width:none !important; width:100% !important; }
                .sra-table-wrap { width:100% !important; overflow-x:hidden !important; }
                .sra-table { width:100% !important; min-width:0 !important; table-layout:fixed !important; }
                .sra-table th { font-size:10px !important; padding:7px 4px !important; white-space:normal !important; line-height:1.15 !important; }
                .sra-table td { font-size:11px !important; padding:8px 4px !important; white-space:normal !important; overflow-wrap:anywhere !important; word-break:break-word !important; line-height:1.25 !important; }
                .sra-amount { text-align:right !important; font-size:11px !important; }
                .sra-pill, .sra-action-badge { white-space:normal !important; justify-content:center; text-align:center; line-height:1.15; padding:3px 6px !important; font-size:10px !important; }
                .sra-doclink { max-width:100%; overflow-wrap:anywhere; }
                .sra-payment-draft-dialog .modal-dialog {
                    width:min(1220px, 96vw) !important;
                    max-width:96vw !important;
                }
                .sra-payment-draft-dialog .modal-body {
                    max-height:78vh;
                    overflow:auto;
                }
                .sra-payment-draft-dialog .grid-heading-row,
                .sra-payment-draft-dialog .grid-row {
                    min-width:920px;
                }
                .sra-payment-draft-dialog .grid-body {
                    overflow-x:auto;
                }
                .sra-payment-draft-dialog .data-row .row-index {
                    min-width:34px;
                }
                .sra-payment-draft-dialog .grid-static-col,
                .sra-payment-draft-dialog .data-row .grid-static-col {
                    padding-left:6px !important;
                    padding-right:6px !important;
                }
                .sra-payment-draft-dialog .sra-dialog-help {
                    color:var(--text-muted);
                    font-size:12px;
                    margin-top:6px;
                    margin-bottom:8px;
                    line-height:1.35;
                }
                .sra-payment-selected-invoices-wide { display:block; }
                .sra-payment-filter-row { display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] { display:none !important; }
                .sra-candidate-list-wrap { margin-top:10px; border:1px solid var(--border-color); border-radius:10px; overflow:auto; max-height:300px; background:var(--card-bg); }
                .sra-candidate-list { width:100%; min-width:980px; border-collapse:separate; border-spacing:0; }
                .sra-candidate-list th { position:sticky; top:0; z-index:1; background:var(--subtle-fg); color:var(--text-muted); font-size:11px; padding:8px 7px; border-bottom:1px solid var(--border-color); text-align:right; white-space:nowrap; }
                .sra-candidate-list td { font-size:12px; padding:7px; border-bottom:1px solid var(--border-color); vertical-align:middle; }
                .sra-candidate-list tr:last-child td { border-bottom:0; }
                .sra-candidate-list .sra-pay-invoice { direction:ltr; font-weight:800; }
                .sra-candidate-list .sra-pay-amount { direction:ltr; text-align:right; font-weight:800; white-space:nowrap; }
                .sra-candidate-list .sra-pay-alloc-input { width:120px; direction:ltr; text-align:right; }
                .sra-candidate-empty { padding:14px; color:var(--text-muted); background:var(--control-bg); border-radius:10px; margin-top:10px; }
                .sra-settlement-badge { display:inline-flex; align-items:center; justify-content:center; border-radius:999px; padding:3px 8px; font-size:11px; font-weight:800; border:1px solid var(--border-color); white-space:nowrap; }
                .sra-settlement-claim { background:#fff4df; border-color:#f4d6a1; color:#8a5a12; }
                .sra-settlement-cash { background:#eaf8ef; border-color:#bfe1c9; color:#0b6e4f; }
                .sra-settlement-credit { background:#e8f7ff; border-color:#b6def3; color:#0f5f8a; }
                .sra-settlement-other { background:#eef2f7; border-color:#d8e0ea; color:#425466; }
                .sra-candidate-summary { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:8px 0; padding:8px 10px; border:1px solid var(--border-color); border-radius:10px; background:var(--control-bg); font-size:12px; }
                .sra-candidate-summary span { display:inline-flex; gap:4px; align-items:center; white-space:nowrap; }
                .sra-candidate-summary strong { color:var(--text-color); }
                .sra-candidate-advance { color:#8a5a12; font-weight:800; }
                .sra-candidate-over { color:#b42318; font-weight:800; }
                .sra-candidate-ok { color:#0b6e4f; font-weight:800; }
                .sra-payment-draft-dialog [data-fieldname="invoice_search_section"] { clear:both; width:100%; }
                .sra-payment-draft-dialog [data-fieldname="candidate_search"] input { font-weight:700; }
                .sra-payment-draft-dialog [data-fieldname="selected_invoices_section"] { clear:both; width:100%; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] { width:100% !important; max-width:none !important; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-wrapper { width:100% !important; max-width:none !important; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-heading-row,
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-row { min-width:1120px !important; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-body,
                .sra-payment-draft-dialog [data-fieldname="invoices"] .form-grid { overflow-x:auto !important; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-static-col,
                .sra-payment-draft-dialog [data-fieldname="invoices"] .data-row .grid-static-col { white-space:normal !important; overflow-wrap:anywhere !important; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-static-col[data-fieldname="invoice"] { min-width:230px !important; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-static-col[data-fieldname="supplier_invoice_no"] { min-width:160px !important; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-static-col[data-fieldname="outstanding_amount"] { min-width:150px !important; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-static-col[data-fieldname="settlement_classification"] { min-width:150px !important; }
                .sra-payment-draft-dialog [data-fieldname="invoices"] .grid-static-col[data-fieldname="allocated_amount"] { min-width:150px !important; }
                .sra-claim-draft-dialog .modal-dialog {
                    width:min(1260px, 97vw) !important;
                    max-width:97vw !important;
                }
                .sra-claim-draft-dialog .modal-body {
                    max-height:80vh;
                    overflow:auto;
                }
                .sra-claim-summary { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:8px 0 10px; padding:9px 10px; border:1px solid var(--border-color); border-radius:10px; background:var(--control-bg); font-size:12px; }
                .sra-claim-summary span { display:inline-flex; gap:4px; align-items:center; white-space:nowrap; }
                .sra-claim-summary strong { color:var(--text-color); }
                .sra-claim-summary .sra-claim-net { font-size:13px; font-weight:900; }
                .sra-claim-help { color:var(--text-muted); font-size:12px; margin:8px 0; line-height:1.45; }
                .sra-claim-candidate-list-wrap { margin-top:8px; border:1px solid var(--border-color); border-radius:10px; overflow:auto; max-height:360px; background:var(--card-bg); }
                .sra-claim-candidate-list { width:100%; min-width:1120px; border-collapse:separate; border-spacing:0; }
                .sra-claim-candidate-list th { position:sticky; top:0; z-index:1; background:var(--subtle-fg); color:var(--text-muted); font-size:11px; padding:8px 7px; border-bottom:1px solid var(--border-color); text-align:right; white-space:nowrap; }
                .sra-claim-candidate-list td { font-size:12px; padding:7px; border-bottom:1px solid var(--border-color); vertical-align:middle; }
                .sra-claim-candidate-list tr:last-child td { border-bottom:0; }
                .sra-claim-candidate-list .sra-claim-doc { direction:ltr; font-weight:800; }
                .sra-claim-candidate-list .sra-claim-money { direction:ltr; text-align:right; font-weight:800; white-space:nowrap; }
                .sra-claim-candidate-list .sra-claim-amount-input { width:120px; direction:ltr; text-align:right; }
                .sra-claim-empty { padding:14px; color:var(--text-muted); background:var(--control-bg); border-radius:10px; margin-top:10px; }
                @media(max-width: 1100px) { .sra-filters, .sra-cards { grid-template-columns:repeat(2,minmax(180px,1fr)); } }
                @media(max-width: 760px) { .sra-filters, .sra-cards { grid-template-columns:1fr; } }
            </style>
        `);
    }

    render() {
        this.$main.empty().append(`
            <div class="sra sra-full-table-mode">
                <div class="sra-hero">
                    <div>
                        <h2>${__("Supplier Running Account")}</h2>
                        <div class="sra-muted">${__("Read-only supplier statement from official ERPNext documents and GL Entry.")}</div>
                    </div>
                    <div class="sra-muted">${__("Phase 1: no GL creation, no reconciliation, no document mutation.")}</div>
                </div>
                <div class="sra-filters" id="sra-filters"></div>
                <div class="sra-cards" id="sra-cards"></div>
                <div class="sra-note" id="sra-note"></div>
                <div class="sra-table-wrap"><table class="sra-table" id="sra-table"></table></div>
            </div>
        `);
        this.makeControls();
        this.renderCards();
        this.renderRows();
    }

    makeControls() {
        const $filters = this.$main.find("#sra-filters");
        this.controls.company = this.makeControl($filters, {
            fieldtype: "Link", fieldname: "company", label: __("Company"), options: "Company", reqd: 1,
            change: () => this.loadStatement()
        });
        this.controls.supplier = this.makeControl($filters, {
            fieldtype: "Link", fieldname: "supplier", label: __("Supplier"), options: "Supplier", reqd: 1,
            change: () => this.loadStatement()
        });
        this.controls.from_date = this.makeControl($filters, {
            fieldtype: "Date", fieldname: "from_date", label: __("From Date"), change: () => this.loadStatement()
        });
        this.controls.to_date = this.makeControl($filters, {
            fieldtype: "Date", fieldname: "to_date", label: __("To Date"), change: () => this.loadStatement()
        });
        this.controls.statement_view = this.makeControl($filters, {
            fieldtype: "Select",
            fieldname: "statement_view",
            label: __("Statement View"),
            options: [
                "All Movements",
                "Outstanding Invoices",
                "Direct Pay Candidates",
                "Claim Candidates",
                "Linked to Claim",
                "Unallocated Advances",
                "Cash Invoices",
                "Claim Invoices",
                "Credit Outside Claim",
            ].join("\n"),
            default: "All Movements",
            change: () => this.renderRows(),
        });
        const $checks = $(`<div class="sra-checkboxes"></div>`).appendTo($filters);
        this.controls.include_cancelled = this.makeControl($checks, {
            fieldtype: "Check", fieldname: "include_cancelled", label: __("Include Cancelled"), change: () => this.loadStatement()
        });
        this.controls.include_drafts = this.makeControl($checks, {
            fieldtype: "Check", fieldname: "include_drafts", label: __("Include Drafts / Context"), change: () => this.loadStatement()
        });
        this.controls.only_outstanding = this.makeControl($checks, {
            fieldtype: "Check", fieldname: "only_outstanding", label: __("Only Outstanding"), change: () => this.loadStatement()
        });
    }

    makeControl(parent, df) {
        const control = frappe.ui.form.make_control({ parent, df, render_input: true });
        control.refresh();
        if (df.fieldtype === "Check" && control.$wrapper) {
            control.$wrapper.addClass("sra-check-control");
        }
        return control;
    }

    async loadBootstrap() {
        const routeOptions = frappe.route_options || {};
        frappe.route_options = null;
        const r = await frappe.call({
            method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.get_bootstrap"
        });
        const data = r.message || {};
        this.currency = data.currency;
        this.controls.company.set_value(routeOptions.company || data.company || "");
        this.controls.supplier.set_value(routeOptions.supplier || "");
        this.controls.from_date.set_value(routeOptions.from_date || data.from_date || "");
        this.controls.to_date.set_value(routeOptions.to_date || data.to_date || "");
        if (this.controls.supplier.get_value()) this.loadStatement();
    }

    values() {
        return {
            company: this.controls.company.get_value(),
            supplier: this.controls.supplier.get_value(),
            from_date: this.controls.from_date.get_value(),
            to_date: this.controls.to_date.get_value(),
            include_cancelled: this.controls.include_cancelled.get_value() ? 1 : 0,
            include_drafts: this.controls.include_drafts.get_value() ? 1 : 0,
            only_outstanding: this.controls.only_outstanding.get_value() ? 1 : 0,
        };
    }

    async loadStatement() {
        const args = this.values();
        if (!args.company || !args.supplier) {
            this.rows = [];
            this.summary = {};
            this.renderCards();
            this.renderRows();
            this.$main.find("#sra-note").text(__("Select Company and Supplier to load the statement."));
            return;
        }
        this.$main.find("#sra-note").text(__("Loading..."));
        const r = await frappe.call({
            method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.get_statement",
            args,
            freeze: true,
            freeze_message: __("Loading Supplier Running Account...")
        });
        const data = r.message || {};
        this.currency = data.currency || this.currency;
        this.summary = data.summary || {};
        this.rows = this.normalizeStatementRows(data.rows);
        this.__last_statement_rows = this.rows;
        this.renderCards();
        this.renderRows();
        this.$main.find("#sra-note").text(data.balance_note || "");
    }

    renderCards() {
        const s = this.summary || {};
        const cards = [
            [__("Opening Balance"), s.opening_balance],
            [__("Total Invoices"), s.total_invoices],
            [__("Total Payments"), s.total_payments],
            [__("Returns / Credits"), s.total_returns_credits],
            [__("Claim Deductions"), s.total_claim_deductions],
            [__("Supplier Refunds"), s.total_refunds],
            [__("Unallocated Advances"), s.total_unallocated_advances],
            [__("Adjustments / Rounding"), s.adjustments_rounding],
            [__("Closing Balance"), s.closing_balance],
        ];
        this.$main.find("#sra-cards").html(cards.map(([label, value]) => `
            <div class="sra-card">
                <div class="sra-card-label">${frappe.utils.escape_html(label)}</div>
                <div class="sra-card-value">${this.money(value || 0)}</div>
            </div>
        `).join(""));
    }

    normalizeStatementRows(rows) {
        if (Array.isArray(rows)) return rows;
        if (!rows) return [];
        if (typeof rows === "string") {
            try {
                const parsed = JSON.parse(rows);
                return this.normalizeStatementRows(parsed);
            } catch (e) {
                console.warn("Supplier Running Account rows could not be parsed", e);
                return [];
            }
        }
        if (typeof rows === "object") {
            return Object.values(rows);
        }
        return [];
    }

    visibleRows() {
        const rows = this.normalizeStatementRows ? this.normalizeStatementRows(this.rows || []) : (Array.isArray(this.rows) ? this.rows : []);
        const control = this.controls && this.controls.statement_view;
        const rawView = control && control.get_value ? control.get_value() : "";
        const view = String(rawView || "All Movements").trim();

        if (!view || view === "All Movements" || view.toLowerCase().includes("all movement")) {
            return rows;
        }

        const hasOutstanding = (row) => Math.abs(flt(row.outstanding_amount || 0, 2)) > 0.005;
        const isInvoice = (row) => row.document_type === "Purchase Invoice" && !cint(row.is_purchase_return);
        const classification = (row) => String(row.settlement_classification || "").trim();
        const isLinkedToClaim = (row) => !!String(row.related_supplier_claim || "").trim();

        if (view === "Outstanding Invoices") {
            return rows.filter(row => isInvoice(row) && hasOutstanding(row));
        }
        if (view === "Direct Pay Candidates") {
            return rows.filter(row => isInvoice(row) && hasOutstanding(row) && !isLinkedToClaim(row)
                && classification(row) !== "Claim Invoice");
        }
        if (view === "Claim Candidates") {
            return rows.filter(row => isInvoice(row) && hasOutstanding(row) && !isLinkedToClaim(row)
                && classification(row) === "Claim Invoice");
        }
        if (view === "Linked to Claim") {
            return rows.filter(row => isLinkedToClaim(row));
        }
        if (view === "Cash Invoices") {
            return rows.filter(row => classification(row) === "Cash Invoice");
        }
        if (view === "Claim Invoices") {
            return rows.filter(row => classification(row) === "Claim Invoice");
        }
        if (view === "Credit Outside Claim") {
            return rows.filter(row => classification(row) === "Credit Invoice Outside Claim");
        }

        console.warn("Supplier Running Account: empty filtered view fallback for unknown view", view);
        return rows;
    }

    nextActionKey(row) {
        const outstanding = Math.abs(flt(row.outstanding_amount || 0, 2));
        const classification = String(row.settlement_classification || "").trim();
        const linkedClaim = !!String(row.related_supplier_claim || "").trim();
        if (row.document_type === "Purchase Invoice" && cint(row.is_purchase_return)) return "return";
        if (row.document_type !== "Purchase Invoice") {
            if (row.document_type === "Supplier Claim") return "linked";
            if (row.document_type === "Payment Entry" || row.document_type === "Journal Entry") return "other";
            return "other";
        }
        if (outstanding <= 0.005) return "settled";
        if (linkedClaim) return "linked";
        if (classification === "Claim Invoice") return "claim";
        return "direct";
    }

    nextActionLabel(row) {
        const key = this.nextActionKey(row);
        const labels = {
            direct: __("Direct Pay Candidate"),
            claim: __("Claim Candidate"),
            linked: __("Linked / Claim Flow"),
            settled: __("Settled"),
            return: __("Return / Credit"),
            other: __("Context"),
        };
        return labels[key] || __("Context");
    }

    actionBadge(row) {
        const key = this.nextActionKey(row);
        return `<span class="sra-action-badge sra-action-${this.esc(key)}">${this.esc(this.nextActionLabel(row))}</span>`;
    }

    outstandingClass(row) {
        const amount = flt(row.outstanding_amount || 0, 2);
        return amount < 0 ? "sra-balance-negative" : "sra-balance-positive";
    }

    renderColgroup() {
        return `<colgroup>
            <col style="width:5%">
            <col style="width:7%">
            <col style="width:8%">
            <col style="width:7%">
            <col style="width:8%">
            <col style="width:7%">
            <col style="width:6%">
            <col style="width:6%">
            <col style="width:8%">
            <col style="width:6%">
            <col style="width:6%">
            <col style="width:7%">
            <col style="width:7%">
            <col style="width:12%">
        </colgroup>`;
    }

    renderRows() {
        const $table = this.$main.find("#sra-table");
        const allRows = this.normalizeStatementRows ? this.normalizeStatementRows(this.rows || []) : (Array.isArray(this.rows) ? this.rows : []);
        this.rows = allRows;

        if (!allRows.length) {
            const expectedRows = cint((this.summary || {}).displayed_rows || (this.summary || {}).official_rows || 0);
            const msg = expectedRows > 0
                ? __("Server returned rows but the browser did not receive them. Reload the statement.")
                : __("No rows to display.");
            $table.html(`<tbody><tr><td><div class="sra-empty">${msg}</div></td></tr></tbody>`);
            return;
        }

        let view = "All Movements";
        if (this.controls && this.controls.statement_view && this.controls.statement_view.get_value) {
            view = String(this.controls.statement_view.get_value() || "All Movements").trim();
        }
        if (!view) view = "All Movements";

        const hasOutstanding = (row) => Math.abs(flt(row.outstanding_amount || 0, 2)) > 0.005;
        const isInvoice = (row) => row.document_type === "Purchase Invoice" && !cint(row.is_purchase_return);
        const classification = (row) => String(row.settlement_classification || "").trim();
        const linkedClaim = (row) => !!String(row.related_supplier_claim || "").trim();
        const isUnallocatedAdvance = (row) => row.document_type === "Payment Entry" && flt(row.outstanding_amount || 0) > 0.005;

        let displayRows = allRows;
        if (view === "Outstanding Invoices") {
            displayRows = allRows.filter(row => isInvoice(row) && hasOutstanding(row));
        } else if (view === "Direct Pay Candidates") {
            displayRows = allRows.filter(row => isInvoice(row) && hasOutstanding(row) && !linkedClaim(row) && classification(row) !== "Claim Invoice");
        } else if (view === "Claim Candidates") {
            displayRows = allRows.filter(row => isInvoice(row) && hasOutstanding(row) && !linkedClaim(row) && classification(row) === "Claim Invoice");
        } else if (view === "Linked to Claim") {
            displayRows = allRows.filter(row => linkedClaim(row));
        } else if (view === "Unallocated Advances") {
            displayRows = allRows.filter(row => isUnallocatedAdvance(row));
        } else if (view === "Cash Invoices") {
            displayRows = allRows.filter(row => classification(row) === "Cash Invoice");
        } else if (view === "Claim Invoices") {
            displayRows = allRows.filter(row => classification(row) === "Claim Invoice");
        } else if (view === "Credit Outside Claim") {
            displayRows = allRows.filter(row => classification(row) === "Credit Invoice Outside Claim");
        } else {
            displayRows = allRows;
        }

        // Safety net: if All Movements is selected or an unknown/stale value is selected,
        // never hide a statement that has backend rows.
        if ((!displayRows || !displayRows.length) && allRows.length && (!view || view === "All Movements" || ![
            "Outstanding Invoices",
            "Direct Pay Candidates",
            "Claim Candidates",
            "Linked to Claim",
            "Unallocated Advances",
            "Cash Invoices",
            "Claim Invoices",
            "Credit Outside Claim"
        ].includes(view))) {
            displayRows = allRows;
        }

        if (!displayRows.length) {
            $table.html(`<tbody><tr><td><div class="sra-empty">${__("No rows match the selected statement view.")} ${this.esc(view || "")}</div></td></tr></tbody>`);
            return;
        }

        const header = `
            <thead><tr>
                <th>${__("Notes")}</th>
                <th>${__("Next Action")}</th>
                <th>${__("Supplier Claim")}</th>
                <th>${__("Return Case")}</th>
                <th>${__("Status")}</th>
                <th>${__("صافي المورد / Net Supplier Balance")}</th>
                <th>${__("Credit")}</th>
                <th>${__("Debit")}</th>
                <th>${__("Outstanding")}</th>
                <th>${__("Settlement Classification")}</th>
                <th>${__("Supplier Invoice No")}</th>
                <th>${__("Document")}</th>
                <th>${__("Type")}</th>
                <th>${__("Date")}</th>
            </tr></thead>`;

        const body = displayRows.map(row => this.renderRow(row)).join("");
        const colgroup = this.renderColgroup ? this.renderColgroup() : "";
        $table.html(`${colgroup}${header}<tbody>${body}</tbody>`);

        $table.find("[data-doctype][data-name]").off("click").on("click", (event) => {
            event.preventDefault();
            const $link = $(event.currentTarget);
            frappe.set_route("Form", $link.data("doctype"), $link.data("name"));
        });

        this.$main.find("#sra-note").text(
            `${this.summary && this.summary.balance_note ? this.summary.balance_note : ""} ` +
            __("Displayed rows: {0}", [displayRows.length])
        );
    }

    rowTypeKey(row) {
        const text = String((row && (row.type || row.document_type || row.voucher_type)) || "").toLowerCase();
        if (!row) return "other";
        if (!row.affects_balance) return "context";
        if (text.includes("purchase return") || text.includes("debit note") || text.includes("credit note") || text.includes("return")) return "return";
        if (text.includes("supplier refund") || text.includes("refund")) return "refund";
        if (text.includes("payment")) {
            const paymentType = String(row.payment_type || "").toLowerCase();
            return paymentType === "receive" ? "refund" : "payment";
        }
        if (text.includes("journal") || text.includes("adjustment")) return "journal";
        if (text.includes("claim")) return "claim";
        if (text.includes("invoice")) return "invoice";
        return "other";
    }

    rowTypeClass(row) {
        const key = this.rowTypeKey(row);
        return key ? `sra-row-${key}` : "";
    }

    rowPillClass(row) {
        const key = this.rowTypeKey(row);
        return key ? `sra-pill-${key}` : "";
    }

    balanceClass(value) {
        const amount = flt(value || 0, 2);
        if (amount < -0.005) return "sra-balance-negative";
        return "sra-balance-positive";
    }

    settlementBadge(classification) {
        const value = String(classification || "");
        const lower = value.toLowerCase();
        let cls = "sra-settlement-other";
        if (lower.includes("claim")) cls = "sra-settlement-claim";
        else if (lower.includes("cash")) cls = "sra-settlement-cash";
        else if (lower.includes("credit")) cls = "sra-settlement-credit";
        return `<span class="sra-settlement-badge ${cls}">${this.esc(value || __("Not Set"))}</span>`;
    }

    renderRow(row) {
        const safeRowTypeClass = (r) => {
            if (typeof this.rowTypeClass === "function") {
                return this.rowTypeClass(r);
            }
            const docType = String(r.document_type || r.voucher_type || "").trim().toLowerCase();
            const type = String(r.type || "").trim().toLowerCase();
            const paymentType = String(r.payment_type || "").trim().toLowerCase();

            if (docType === "purchase invoice" && cint(r.is_purchase_return)) return "sra-row-return";
            if (type.includes("return") || type.includes("debit note") || type.includes("credit note")) return "sra-row-return";

            if (docType === "payment entry" || type.includes("payment entry")) {
                if (paymentType === "receive" || type.includes("refund")) return "sra-row-refund";
                return "sra-row-payment";
            }
            if (type.includes("supplier refund")) return "sra-row-refund";

            if (docType === "journal entry" || type.includes("journal entry")) return "sra-row-journal";
            if (docType === "supplier claim" || type.includes("supplier claim")) return "sra-row-claim";
            if (docType === "purchase invoice" || type.includes("purchase invoice")) return "sra-row-invoice";

            return "sra-row-other";
        };
        const classes = [safeRowTypeClass(row), !row.affects_balance ? "sra-row-context" : "", row.is_cancelled ? "sra-row-cancelled" : ""].filter(Boolean).join(" ");
        return `<tr class="${classes}">
            <td>${frappe.datetime.str_to_user(row.posting_date || "")}</td>
            <td><span class="sra-pill ${(typeof this.rowPillClass === "function" ? this.rowPillClass(row) : "")}">${this.esc(row.type || "")}</span></td>
            <td>${this.docLink(row.document_type, row.document)}</td>
            <td>${this.esc(row.supplier_invoice_no || "")}</td>
            <td>${this.settlementBadge(row.settlement_classification)}</td>
            <td class="sra-amount ${this.outstandingClass(row)}">${this.money(row.outstanding_amount || 0)}</td>
            <td class="sra-amount sra-debit-amount">${this.money(row.debit || 0)}</td>
            <td class="sra-amount sra-credit-amount">${this.money(row.credit || 0)}</td>
            <td class="sra-amount ${row.running_balance === null || row.running_balance === undefined ? "" : this.balanceClass(row.running_balance || 0)}">${row.running_balance === null || row.running_balance === undefined ? `<span class="sra-pill sra-pill-muted sra-pill-context">${__("Context")}</span>` : this.money(row.running_balance || 0)}</td>
            <td>${this.esc(row.status || "")}</td>
            <td>${this.docLink("Pharmacy Return Case", row.related_return_case)}</td>
            <td>${this.docLink("Supplier Claim", row.related_supplier_claim)}</td>
            <td>${this.actionBadge(row)}</td>
            <td>${this.esc(row.notes || "")}</td>
        </tr>`;
    }

    docLink(doctype, name) {
        if (!doctype || !name) return "";
        const names = String(name).split(",").map(x => x.trim()).filter(Boolean);
        return names.map(n => `<a href="#" class="sra-doclink" data-doctype="${this.esc(doctype)}" data-name="${this.esc(n)}">${this.esc(n)}</a>`).join("<br>");
    }

    money(value) {
        const amount = flt(value || 0, 2);
        const abs = Math.abs(amount);
        const formatted = abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return `${amount < 0 ? "-" : ""}${formatted} ج.م`;
    }

    esc(value) {
        return frappe.utils.escape_html(String(value || ""));
    }


    async openPaymentDraftDialog() {
        const supplier = this.controls.supplier.get_value();
        const company = this.controls.company.get_value();
        if (!company || !supplier) {
            frappe.msgprint(__("Select Company and Supplier first."));
            return;
        }

        const defaults = await frappe.call({
            method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.get_supplier_payment_defaults",
            args: { company, supplier }
        });
        const d = defaults.message || {};
        const dialog = new frappe.ui.Dialog({
            title: __("Create Supplier Payment Draft"),
            fields: [
                { fieldname: "company", fieldtype: "Link", label: __("Company"), options: "Company", default: company, reqd: 1, read_only: 1 },
                { fieldname: "supplier", fieldtype: "Link", label: __("Supplier"), options: "Supplier", default: supplier, reqd: 1, read_only: 1 },
                { fieldname: "posting_date", fieldtype: "Date", label: __("Posting Date"), default: frappe.datetime.get_today(), reqd: 1 },
                { fieldname: "amount", fieldtype: "Currency", label: __("Amount"), reqd: 1, description: __("Payment Entry will be saved as Draft only. Submit manually after review.") },
                { fieldtype: "Column Break" },
                { fieldname: "mode_of_payment", fieldtype: "Link", label: __("Mode of Payment"), options: "Mode of Payment", default: d.mode_of_payment || "" },
                { fieldname: "paid_from", fieldtype: "Link", label: __("Paid From Account"), options: "Account", default: d.paid_from || "", reqd: 1, get_query: () => ({ filters: { company, is_group: 0 } }) },
                { fieldname: "allocation_mode", fieldtype: "Select", label: __("Allocation Mode"), default: "Oldest Outstanding First", options: ["Oldest Outstanding First", "Selected Invoices", "Unallocated Advance"].join("\n"), reqd: 1 },
                { fieldtype: "Section Break", label: __("Allocation") },
                { fieldname: "include_claim_linked", fieldtype: "Check", label: __("Include invoices already linked to Supplier Claim"), default: 0, description: __("Keep off unless you intentionally want to pay invoices already tied to a claim.") },
                { fieldtype: "Section Break", fieldname: "invoice_search_section", label: __("Find Invoices") },
                { fieldname: "candidate_from_date", fieldtype: "Date", label: __("From Invoice Date"), default: this.controls.from_date ? this.controls.from_date.get_value() : "" },
                { fieldname: "candidate_to_date", fieldtype: "Date", label: __("To Invoice Date"), default: this.controls.to_date ? this.controls.to_date.get_value() : "" },
                { fieldtype: "Column Break" },
                { fieldname: "candidate_search", fieldtype: "Data", label: __("Invoice No / Supplier Invoice No"), description: __("Search by ERPNext Purchase Invoice number or supplier invoice number.") },
                { fieldname: "load_candidates", fieldtype: "Button", label: __("Load / Add Matching Invoices") },
                { fieldtype: "Column Break" },
                { fieldname: "auto_allocate_candidates", fieldtype: "Button", label: __("Auto Allocate Amount") },
                { fieldname: "clear_allocations", fieldtype: "Button", label: __("Clear Allocations") },
                { fieldname: "set_amount_allocated", fieldtype: "Button", label: __("Set Amount = Allocated") },
                { fieldtype: "Section Break", fieldname: "selected_invoices_section", label: __("Selected Invoices") },
                {
                    fieldname: "invoices",
                    fieldtype: "Table",
                    label: __("Selected Invoices"),
                    cannot_add_rows: true,
                    in_place_edit: true,
                    depends_on: "eval:doc.allocation_mode=='Selected Invoices'",
                    fields: [
                        { fieldtype: "Link", fieldname: "invoice", label: __("Invoice"), options: "Purchase Invoice", in_list_view: 1, read_only: 1, columns: 3 },
                        { fieldtype: "Data", fieldname: "supplier_invoice_no", label: __("Supplier Inv No"), in_list_view: 1, read_only: 1, columns: 2 },
                        { fieldtype: "Currency", fieldname: "outstanding_amount", label: __("Outstanding"), in_list_view: 1, read_only: 1, columns: 2 },
                        { fieldtype: "Data", fieldname: "settlement_classification", label: __("Settlement Type"), in_list_view: 1, read_only: 1, columns: 2 },
                        { fieldtype: "Currency", fieldname: "allocated_amount", label: __("Allocate"), in_list_view: 1, columns: 2 },
                    ],
                    data: []
                },
                { fieldname: "invoice_candidates_html", fieldtype: "HTML" },
                { fieldtype: "Section Break", label: __("Reference / Notes") },
                { fieldname: "reference_no", fieldtype: "Data", label: __("Reference No") },
                { fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") },
            ],
            primary_action_label: __("Create Draft"),
            primary_action: async (values) => {
                if (!values.amount || flt(values.amount) <= 0) {
                    frappe.msgprint(__("Enter a valid payment amount."));
                    return;
                }
                const rows = dialog.__sra_get_selected_rows ? dialog.__sra_get_selected_rows() : (values.invoices || []).filter(row => flt(row.allocated_amount || 0) > 0);
                dialog.hide();
                const r = await frappe.call({
                    method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.create_supplier_payment_draft",
                    args: { args: { ...values, invoices: rows } },
                    freeze: true,
                    freeze_message: __("Creating draft Payment Entry...")
                });
                const out = r.message || {};
                if (out.name) {
                    frappe.show_alert({ message: __("Draft Payment Entry created: {0}", [out.name]), indicator: "green" });
                    frappe.set_route("Form", "Payment Entry", out.name);
                }
            }
        });

        dialog.$wrapper.addClass("sra-payment-draft-dialog");
        dialog.$wrapper.addClass("sra-payment-selected-invoices-wide");
        if (dialog.fields_dict.invoices && dialog.fields_dict.invoices.$wrapper) {
            dialog.fields_dict.invoices.$wrapper.before(
                `<div class="sra-dialog-help">${__("For Selected Invoices, load invoices by date range or invoice number, then enter Allocated Amount. Use Auto Allocate to fill oldest loaded invoices up to the entered amount.")}</div>`
            );
        }

        dialog.__sra_invoice_candidates = [];
        dialog.__sra_get_selected_rows = () => {
            return (dialog.__sra_invoice_candidates || [])
                .map(row => ({
                    invoice: row.invoice,
                    supplier_invoice_no: row.supplier_invoice_no || "",
                    outstanding_amount: row.outstanding_amount || 0,
                    settlement_classification: row.settlement_classification || "",
                    allocated_amount: flt(row.allocated_amount || 0),
                }))
                .filter(row => flt(row.allocated_amount || 0) > 0);
        };

        const candidateSummaryHtml = (rows) => {
            rows = rows || [];
            const loadedOutstanding = rows.reduce((sum, row) => sum + flt(row.outstanding_amount || 0), 0);
            const allocated = rows.reduce((sum, row) => sum + flt(row.allocated_amount || 0), 0);
            const paymentAmount = flt(dialog.get_value("amount") || 0);
            const difference = paymentAmount - allocated;
            let diffClass = "sra-candidate-ok";
            let diffLabel = __("Unallocated Difference");
            if (difference > 0.005) {
                diffClass = "sra-candidate-advance";
                diffLabel = __("Unallocated / Advance");
            } else if (difference < -0.005) {
                diffClass = "sra-candidate-over";
                diffLabel = __("Over Allocated");
            }
            return `
                <span><strong>${__("Loaded Outstanding")}:</strong> ${this.money(loadedOutstanding)}</span>
                <span><strong>${__("Allocated Total")}:</strong> ${this.money(allocated)}</span>
                <span class="${diffClass}"><strong>${diffLabel}:</strong> ${this.money(difference)}</span>
            `;
        };

        const updateCandidateTotals = () => {
            const field = dialog.fields_dict.invoice_candidates_html;
            if (!field || !field.$wrapper) return;
            const rows = dialog.__sra_invoice_candidates || [];
            field.$wrapper.find(".sra-candidate-summary").html(candidateSummaryHtml(rows));
        };

        const renderInvoiceCandidatesHtml = (rows) => {
            rows = rows || [];
            dialog.__sra_invoice_candidates = rows;
            const field = dialog.fields_dict.invoice_candidates_html;
            if (!field || !field.$wrapper) return;
            if (!rows.length) {
                field.$wrapper.html(`<div class="sra-candidate-empty">${__("No loaded invoice candidates yet. Use date range or invoice number, then click Load / Add Matching Invoices.")}</div>`);
                return;
            }
            const settlementBadge = (classification) => {
                const value = String(classification || "");
                const lower = value.toLowerCase();
                let cls = "sra-settlement-other";
                if (lower.includes("claim")) cls = "sra-settlement-claim";
                else if (lower.includes("cash")) cls = "sra-settlement-cash";
                else if (lower.includes("credit")) cls = "sra-settlement-credit";
                return `<span class="sra-settlement-badge ${cls}">${this.esc(value || __("Not Set"))}</span>`;
            };
            const html = `
                <div class="sra-candidate-summary">${candidateSummaryHtml(rows)}</div>
                <div class="sra-dialog-help">${__("Settlement Type shows Claim / Cash / Credit classification. Enter Allocate amount only for invoices you want to pay. If Amount is greater than Allocated Total, the difference will remain unallocated / advance on the supplier draft payment.")}</div>
                <div class="sra-candidate-list-wrap">
                    <table class="sra-candidate-list">
                        <thead><tr>
                            <th>${__("Invoice")}</th>
                            <th>${__("Supplier Inv No")}</th>
                            <th>${__("Date")}</th>
                            <th>${__("Outstanding")}</th>
                            <th>${__("Settlement Type")}</th>
                            <th>${__("Allocate")}</th>
                        </tr></thead>
                        <tbody>
                            ${rows.map((row, idx) => `
                                <tr>
                                    <td class="sra-pay-invoice">${this.esc(row.invoice || "")}</td>
                                    <td>${this.esc(row.supplier_invoice_no || "")}</td>
                                    <td>${row.posting_date ? frappe.datetime.str_to_user(row.posting_date) : ""}</td>
                                    <td class="sra-pay-amount">${this.money(row.outstanding_amount || 0)}</td>
                                    <td>${this.esc(row.settlement_classification || "")}</td>
                                    <td><input class="form-control sra-pay-alloc-input" data-idx="${idx}" value="${flt(row.allocated_amount || 0) || ""}" /></td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                </div>`;
            field.$wrapper.html(html);
        };

        dialog.$wrapper.on("change input", ".sra-pay-alloc-input", (event) => {
            const idx = cint($(event.currentTarget).data("idx"));
            const row = (dialog.__sra_invoice_candidates || [])[idx];
            if (!row) return;
            let value = flt($(event.currentTarget).val() || 0);
            const outstanding = flt(row.outstanding_amount || 0);
            if (value < 0) value = 0;
            if (value > outstanding) value = outstanding;
            row.allocated_amount = value;
            updateCandidateTotals();
        });

        const loadCandidates = async () => {
            const values = dialog.get_values() || {};
            const r = await frappe.call({
                method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.get_supplier_payment_candidates",
                args: {
                    company,
                    supplier,
                    include_claim_linked: values.include_claim_linked ? 1 : 0,
                    from_date: values.candidate_from_date || "",
                    to_date: values.candidate_to_date || "",
                    search: values.candidate_search || "",
                    limit: 500,
                },
                freeze: true,
                freeze_message: __("Loading invoice candidates...")
            });
            const rows = (r.message || []).map(row => ({
                invoice: row.name,
                supplier_invoice_no: row.supplier_invoice_no || "",
                outstanding_amount: row.outstanding_amount || 0,
                settlement_classification: row.settlement_classification || "",
                allocated_amount: 0,
            }));
            dialog.fields_dict.invoices.df.data = rows;
            dialog.fields_dict.invoices.df.hidden = true;
            dialog.fields_dict.invoices.refresh();
            dialog.fields_dict.invoices.grid.refresh();
            renderInvoiceCandidatesHtml(rows);
            if (!rows.length) {
                frappe.msgprint(__("No matching outstanding invoices found for the selected filters."));
            } else {
                frappe.show_alert({ message: __("Loaded {0} invoice candidate(s).", [rows.length]), indicator: "blue" });
            }
        };

        const autoAllocateCandidates = () => {
            const values = dialog.get_values() || {};
            const amount = flt(values.amount || 0);
            if (amount <= 0) {
                frappe.msgprint(__("Enter Amount first."));
                return;
            }
            const grid = dialog.fields_dict.invoices;
            const rows = (grid.df.data || []);
            if (!rows.length) {
                frappe.msgprint(__("Load invoice candidates first."));
                return;
            }
            let remaining = amount;
            rows.forEach(row => {
                const outstanding = flt(row.outstanding_amount || 0);
                const allocated = remaining > 0 ? Math.min(outstanding, remaining) : 0;
                row.allocated_amount = allocated;
                remaining -= allocated;
            });
            dialog.__sra_invoice_candidates = rows;
            grid.grid.refresh();
            renderInvoiceCandidatesHtml(rows);
            if (remaining > 0.005) {
                frappe.show_alert({
                    message: __("Amount exceeds loaded outstanding by {0}", [format_currency(remaining)]),
                    indicator: "orange"
                });
            }
        };

        const clearAllocations = () => {
            const grid = dialog.fields_dict.invoices;
            (grid.df.data || []).forEach(row => row.allocated_amount = 0);
            dialog.__sra_invoice_candidates = grid.df.data || [];
            grid.grid.refresh();
            renderInvoiceCandidatesHtml(grid.df.data || []);
        };

        if (dialog.fields_dict.amount && dialog.fields_dict.amount.$input) {
            dialog.fields_dict.amount.$input.on("change input", () => updateCandidateTotals());
        }
        dialog.fields_dict.load_candidates.$input.on("click", loadCandidates);
        dialog.fields_dict.auto_allocate_candidates.$input.on("click", autoAllocateCandidates);
        dialog.fields_dict.clear_allocations.$input.on("click", clearAllocations);
        dialog.fields_dict.set_amount_allocated.$input.on("click", () => {
            const rows = dialog.__sra_invoice_candidates || [];
            const allocated = rows.reduce((sum, row) => sum + flt(row.allocated_amount || 0), 0);
            if (allocated <= 0.005) {
                frappe.msgprint(__("Enter allocated amounts first or click Auto Allocate Amount."));
                return;
            }
            dialog.set_value("amount", allocated);
            updateCandidateTotals();
        });
        dialog.fields_dict.allocation_mode.df.onchange = () => {
            const mode = dialog.get_value("allocation_mode");
            dialog.fields_dict.invoices.df.hidden = mode !== "Selected Invoices";
            dialog.fields_dict.invoices.refresh();
            if (mode === "Selected Invoices") {
                dialog.fields_dict.invoices.df.hidden = false;
                dialog.fields_dict.invoices.refresh();
            }
        };
        dialog.show();
        renderInvoiceCandidatesHtml([]);
    }


    async openUseExistingAdvanceDialog() {
        const supplier = this.controls.supplier.get_value();
        const company = this.controls.company.get_value();
        if (!company || !supplier) {
            frappe.msgprint(__("Select Company and Supplier first."));
            return;
        }

        const money = (value) => this.money(flt(value || 0));
        const dialog = new frappe.ui.Dialog({
            title: __("Use Existing Supplier Advance"),
            fields: [
                { fieldname: "company", fieldtype: "Link", label: __("Company"), options: "Company", default: company, reqd: 1, read_only: 1 },
                { fieldname: "supplier", fieldtype: "Link", label: __("Supplier"), options: "Supplier", default: supplier, reqd: 1, read_only: 1 },
                { fieldname: "payment_entry", fieldtype: "Link", label: __("Advance Payment Entry"), options: "Payment Entry", reqd: 1, description: __("Select a submitted supplier Payment Entry with unallocated amount."), get_query: () => ({ filters: { company, party_type: "Supplier", party: supplier, docstatus: 1, payment_type: "Pay" } }) },
                { fieldname: "available_advance", fieldtype: "Currency", label: __("Available Advance"), read_only: 1 },
                { fieldtype: "Column Break" },
                { fieldname: "advance_from_date", fieldtype: "Date", label: __("Advance From"), default: this.controls.from_date ? this.controls.from_date.get_value() : "" },
                { fieldname: "advance_to_date", fieldtype: "Date", label: __("Advance To"), default: this.controls.to_date ? this.controls.to_date.get_value() : "" },
                { fieldname: "advance_search", fieldtype: "Data", label: __("Advance Search") },
                { fieldname: "load_advances", fieldtype: "Button", label: __("Load Advances") },
                { fieldtype: "Section Break", label: __("Outstanding Invoices") },
                { fieldname: "include_claim_linked", fieldtype: "Check", label: __("Include invoices already linked to Supplier Claim"), default: 0 },
                { fieldname: "candidate_from_date", fieldtype: "Date", label: __("From Invoice Date"), default: this.controls.from_date ? this.controls.from_date.get_value() : "" },
                { fieldname: "candidate_to_date", fieldtype: "Date", label: __("To Invoice Date"), default: this.controls.to_date ? this.controls.to_date.get_value() : "" },
                { fieldtype: "Column Break" },
                { fieldname: "candidate_search", fieldtype: "Data", label: __("Invoice No / Supplier Invoice No") },
                { fieldname: "load_invoices", fieldtype: "Button", label: __("Load Invoices") },
                { fieldname: "auto_allocate", fieldtype: "Button", label: __("Auto Allocate Advance") },
                { fieldname: "clear_allocations", fieldtype: "Button", label: __("Clear Allocations") },
                { fieldtype: "Section Break", label: __("Allocation Review") },
                { fieldname: "advance_allocation_html", fieldtype: "HTML" },
            ],
            primary_action_label: __("Apply Reconciliation"),
            primary_action: async () => {
                const values = dialog.get_values() || {};
                const rows = getSelectedInvoiceRows();
                if (!values.payment_entry) {
                    frappe.msgprint(__("Select an Advance Payment Entry first."));
                    return;
                }
                if (!rows.length) {
                    frappe.msgprint(__("Select at least one invoice and enter allocation amount."));
                    return;
                }
                const preview = await frappe.call({
                    method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.preview_supplier_advance_allocation",
                    args: { args: { company, supplier, payment_entry: values.payment_entry, include_claim_linked: values.include_claim_linked ? 1 : 0, invoices: rows } },
                    freeze: true,
                    freeze_message: __("Validating advance allocation...")
                });
                const p = preview.message || {};
                await new Promise((resolve) => {
                    frappe.confirm(
                        `<b>${__("Apply Supplier Advance Reconciliation?")}</b><br><br>` +
                        `${__("Payment Entry")}: <b>${frappe.utils.escape_html(values.payment_entry)}</b><br>` +
                        `${__("Allocated Total")}: <b>${money(p.allocated_total)}</b><br>` +
                        `${__("Remaining Advance")}: <b>${money(p.remaining_advance)}</b><br><br>` +
                        `<span class="text-muted">${__("This uses ERPNext Payment Reconciliation. No new payment draft is created, but invoice/payment allocation state will be updated immediately.")}</span>`,
                        () => resolve(true),
                        () => resolve(false)
                    );
                }).then(async (confirmed) => {
                    if (!confirmed) return;
                    dialog.hide();
                    const r = await frappe.call({
                        method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.reconcile_supplier_advance_against_invoices",
                        args: { args: { company, supplier, payment_entry: values.payment_entry, include_claim_linked: values.include_claim_linked ? 1 : 0, invoices: rows } },
                        freeze: true,
                        freeze_message: __("Applying ERPNext Payment Reconciliation...")
                    });
                    const out = r.message || {};
                    frappe.show_alert({ message: __("Supplier advance reconciled: {0}", [values.payment_entry]), indicator: "green" }, 8);
                    this.loadStatement();
                    if (out.payment_entry) frappe.set_route("Form", "Payment Entry", out.payment_entry);
                });
            }
        });

        dialog.$wrapper.addClass("sra-payment-draft-dialog");
        dialog.__sra_advances = [];
        dialog.__sra_invoice_candidates = [];

        const getSelectedInvoiceRows = () => (dialog.__sra_invoice_candidates || [])
            .map(row => ({
                invoice: row.invoice,
                supplier_invoice_no: row.supplier_invoice_no || "",
                outstanding_amount: row.outstanding_amount || 0,
                settlement_classification: row.settlement_classification || "",
                allocated_amount: flt(row.allocated_amount || 0),
            }))
            .filter(row => flt(row.allocated_amount || 0) > 0.005);

        const summaryHtml = () => {
            const advance = flt(dialog.get_value("available_advance") || 0);
            const loadedOutstanding = (dialog.__sra_invoice_candidates || []).reduce((sum, row) => sum + flt(row.outstanding_amount || 0), 0);
            const allocated = getSelectedInvoiceRows().reduce((sum, row) => sum + flt(row.allocated_amount || 0), 0);
            const remaining = advance - allocated;
            const cls = remaining < -0.005 ? "sra-candidate-over" : (remaining > 0.005 ? "sra-candidate-advance" : "sra-candidate-ok");
            return `<div class="sra-candidate-summary">
                <span><strong>${__("Available Advance")}:</strong> ${money(advance)}</span>
                <span><strong>${__("Loaded Outstanding")}:</strong> ${money(loadedOutstanding)}</span>
                <span><strong>${__("Allocated Total")}:</strong> ${money(allocated)}</span>
                <span class="${cls}"><strong>${__("Remaining Advance")}:</strong> ${money(remaining)}</span>
            </div>`;
        };

        const render = () => {
            const field = dialog.fields_dict.advance_allocation_html;
            if (!field || !field.$wrapper) return;
            const advances = dialog.__sra_advances || [];
            const invoices = dialog.__sra_invoice_candidates || [];
            const advancesHtml = advances.length ? `
                <div class="sra-dialog-help">${__("Choose one unallocated Payment Entry advance, then allocate it against outstanding supplier invoices.")}</div>
                <div class="sra-candidate-list-wrap"><table class="sra-candidate-list">
                    <thead><tr><th>${__("Use")}</th><th>${__("Payment Entry")}</th><th>${__("Date")}</th><th>${__("Paid")}</th><th>${__("Unallocated")}</th><th>${__("Reference")}</th></tr></thead>
                    <tbody>${advances.map((row, idx) => `
                        <tr>
                            <td><button class="btn btn-xs btn-default sra-use-advance" data-idx="${idx}">${__("Use")}</button></td>
                            <td>${this.docLink("Payment Entry", row.payment_entry)}</td>
                            <td>${row.posting_date ? frappe.datetime.str_to_user(row.posting_date) : ""}</td>
                            <td class="sra-pay-amount">${money(row.paid_amount)}</td>
                            <td class="sra-pay-amount sra-candidate-advance">${money(row.unallocated_amount)}</td>
                            <td>${this.esc(row.reference_no || "")}</td>
                        </tr>`).join("")}</tbody>
                </table></div>` : `<div class="sra-candidate-empty">${__("No loaded advances yet. Click Load Advances.")}</div>`;
            const invoicesHtml = invoices.length ? `
                <div class="sra-candidate-list-wrap"><table class="sra-candidate-list">
                    <thead><tr><th>${__("Invoice")}</th><th>${__("Supplier Inv No")}</th><th>${__("Date")}</th><th>${__("Outstanding")}</th><th>${__("Settlement Type")}</th><th>${__("Allocate")}</th></tr></thead>
                    <tbody>${invoices.map((row, idx) => `
                        <tr>
                            <td>${this.docLink("Purchase Invoice", row.invoice)}</td>
                            <td>${this.esc(row.supplier_invoice_no || "")}</td>
                            <td>${row.posting_date ? frappe.datetime.str_to_user(row.posting_date) : ""}</td>
                            <td class="sra-pay-amount">${money(row.outstanding_amount || 0)}</td>
                            <td>${this.settlementBadge(row.settlement_classification || "")}</td>
                            <td><input class="form-control sra-adv-alloc-input" data-idx="${idx}" value="${flt(row.allocated_amount || 0) || ""}" /></td>
                        </tr>`).join("")}</tbody>
                </table></div>` : `<div class="sra-candidate-empty">${__("No loaded invoices yet. Click Load Invoices.")}</div>`;
            field.$wrapper.html(`${summaryHtml()}${advancesHtml}<hr>${invoicesHtml}`);
        };

        dialog.$wrapper.on("click", ".sra-use-advance", (e) => {
            const idx = cint($(e.currentTarget).data("idx"));
            const row = (dialog.__sra_advances || [])[idx];
            if (!row) return;
            dialog.set_value("payment_entry", row.payment_entry);
            dialog.set_value("available_advance", flt(row.unallocated_amount || 0));
            render();
        });
        dialog.$wrapper.on("change input", ".sra-adv-alloc-input", (e) => {
            const idx = cint($(e.currentTarget).data("idx"));
            const row = (dialog.__sra_invoice_candidates || [])[idx];
            if (!row) return;
            let value = flt($(e.currentTarget).val() || 0);
            const outstanding = flt(row.outstanding_amount || 0);
            if (value < 0) value = 0;
            if (value > outstanding) value = outstanding;
            row.allocated_amount = value;
            render();
        });

        const loadAdvances = async () => {
            const values = dialog.get_values() || {};
            const r = await frappe.call({
                method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.get_supplier_unallocated_advances",
                args: { company, supplier, from_date: values.advance_from_date || "", to_date: values.advance_to_date || "", search: values.advance_search || "", limit: 200 },
                freeze: true,
                freeze_message: __("Loading supplier advances...")
            });
            dialog.__sra_advances = r.message || [];
            render();
            if (!dialog.__sra_advances.length) frappe.msgprint(__("No unallocated supplier advances found for the selected filters."));
        };
        const loadInvoices = async () => {
            const values = dialog.get_values() || {};
            const r = await frappe.call({
                method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.get_supplier_payment_candidates",
                args: { company, supplier, include_claim_linked: values.include_claim_linked ? 1 : 0, from_date: values.candidate_from_date || "", to_date: values.candidate_to_date || "", search: values.candidate_search || "", limit: 500 },
                freeze: true,
                freeze_message: __("Loading invoice candidates...")
            });
            dialog.__sra_invoice_candidates = (r.message || []).map(row => ({
                invoice: row.name,
                supplier_invoice_no: row.supplier_invoice_no || "",
                posting_date: row.posting_date,
                outstanding_amount: row.outstanding_amount || 0,
                settlement_classification: row.settlement_classification || "",
                allocated_amount: 0,
            }));
            render();
            if (!dialog.__sra_invoice_candidates.length) frappe.msgprint(__("No matching outstanding invoices found for the selected filters."));
        };
        const autoAllocate = () => {
            const advance = flt(dialog.get_value("available_advance") || 0);
            if (advance <= 0.005) {
                frappe.msgprint(__("Select an advance first."));
                return;
            }
            if (!(dialog.__sra_invoice_candidates || []).length) {
                frappe.msgprint(__("Load invoices first."));
                return;
            }
            let remaining = advance;
            (dialog.__sra_invoice_candidates || []).forEach(row => {
                const outstanding = flt(row.outstanding_amount || 0);
                const allocated = remaining > 0 ? Math.min(outstanding, remaining) : 0;
                row.allocated_amount = allocated;
                remaining -= allocated;
            });
            render();
        };

        dialog.fields_dict.load_advances.$input.on("click", loadAdvances);
        dialog.fields_dict.load_invoices.$input.on("click", loadInvoices);
        dialog.fields_dict.auto_allocate.$input.on("click", autoAllocate);
        dialog.fields_dict.clear_allocations.$input.on("click", () => {
            (dialog.__sra_invoice_candidates || []).forEach(row => row.allocated_amount = 0);
            render();
        });
        dialog.fields_dict.payment_entry.df.onchange = async () => {
            const pe = dialog.get_value("payment_entry");
            const found = (dialog.__sra_advances || []).find(row => row.payment_entry === pe);
            if (found) {
                dialog.set_value("available_advance", flt(found.unallocated_amount || 0));
                render();
            }
        };

        dialog.show();
        render();
    }

    async openSupplierClaimDraftDialog() {
        const supplier = this.controls.supplier.get_value();
        const company = this.controls.company.get_value();
        if (!company || !supplier) {
            frappe.msgprint(__("Select Company and Supplier first."));
            return;
        }

        const money = (value) => this.money(flt(value || 0));
        const dialog = new frappe.ui.Dialog({
            title: __("Create Supplier Claim Draft"),
            fields: [
                { fieldname: "period_from", fieldtype: "Date", label: __("Period From"), default: this.controls.from_date ? this.controls.from_date.get_value() : "", reqd: 1 },
                { fieldname: "period_to", fieldtype: "Date", label: __("Period To"), default: this.controls.to_date ? this.controls.to_date.get_value() : frappe.datetime.get_today(), reqd: 1 },
                { fieldname: "payment_due_date", fieldtype: "Date", label: __("Payment Due Date") },
                { fieldname: "search", fieldtype: "Data", label: __("Invoice / Debit Note / Return Case"), description: __("Search by Purchase Invoice, Supplier Invoice No, or Return Case.") },
                { fieldname: "load_candidates", fieldtype: "Button", label: __("Load Claim Candidates") },
                { fieldname: "select_all", fieldtype: "Button", label: __("Select Claim Invoices") },
                { fieldname: "clear_selection", fieldtype: "Button", label: __("Clear Selection") },
                { fieldname: "net_amount_to_pay", fieldtype: "Currency", label: __("Net Amount To Pay"), description: __("Leave equal to System Claim Total unless there is a settlement discount.") },
                { fieldname: "claim_candidates_html", fieldtype: "HTML" },
                { fieldname: "notes", fieldtype: "Small Text", label: __("Notes"), default: __("Draft Supplier Claim created from Supplier Running Account. Review before Submit.") },
            ],
            primary_action_label: __("Create Draft"),
            primary_action: async () => {
                const selected = selectedRows();
                const summary = getSummary();
                const values = dialog.get_values() || {};
                if (!selected.length) {
                    frappe.msgprint(__("Select at least one Claim Invoice or Return Credit / Debit Note."));
                    return;
                }
                if (summary.system < -0.005) {
                    frappe.msgprint(__("Selected Return Credits exceed selected Claim Invoices. Add invoices first or reduce credit amounts."));
                    return;
                }
                if (summary.net < -0.005 || summary.net - summary.system > 0.005) {
                    frappe.msgprint(__("Net Amount To Pay must be between zero and the System Claim Total."));
                    return;
                }

                const confirmHtml = `
                    <div style="text-align:right; direction:rtl; line-height:1.7">
                        <b>${__("Review Supplier Claim Draft before saving")}</b><br>
                        ${__("Gross Invoices")}: <b>${money(summary.gross)}</b><br>
                        ${__("Returns / Credits")}: <b>${money(summary.returns)}</b><br>
                        ${__("System Claim Total")}: <b>${money(summary.system)}</b><br>
                        ${__("Settlement Discount")}: <b>${money(summary.discount)}</b><br>
                        ${__("Net Amount To Pay")}: <b>${money(summary.net)}</b><br>
                        <span class="text-muted">${__("The Supplier Claim will be saved as Draft only. No Submit, no GL, and no automatic accounting reconciliation.")}</span>
                    </div>`;
                frappe.confirm(confirmHtml, async () => {
                    const r = await frappe.call({
                        method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.create_supplier_claim_draft",
                        args: {
                            args: {
                                company,
                                supplier,
                                period_from: values.period_from,
                                period_to: values.period_to,
                                payment_due_date: values.payment_due_date || "",
                                supplier_printed_claim_total: summary.system,
                                net_amount_to_pay: summary.net,
                                notes: values.notes || "",
                                invoices: selected.map(row => ({
                                    purchase_invoice: row.purchase_invoice,
                                    included_amount: flt(row.included_amount || 0),
                                })),
                            }
                        },
                        freeze: true,
                        freeze_message: __("Creating draft Supplier Claim...")
                    });
                    const out = r.message || {};
                    dialog.hide();
                    frappe.show_alert({ message: __("Draft Supplier Claim created: {0}", [out.name]), indicator: "green" }, 8);
                    frappe.set_route("Form", "Supplier Claim", out.name);
                    this.loadStatement();
                });
            },
        });

        dialog.$wrapper.addClass("sra-claim-draft-dialog");
        dialog.__sra_claim_candidates = [];
        dialog.__sra_claim_auto_net = true;

        const selectedRows = () => (dialog.__sra_claim_candidates || []).filter(row => row.__sra_selected === true && Math.abs(flt(row.included_amount || 0)) > 0.005);

        const calculateClaimGrossReturns = (rows) => {
            const gross = rows.filter(row => flt(row.included_amount) > 0).reduce((sum, row) => sum + flt(row.included_amount), 0);
            const returns = Math.abs(rows.filter(row => flt(row.included_amount) < 0).reduce((sum, row) => sum + flt(row.included_amount), 0));
            return { gross, returns };
        };

        const getSummary = () => {
            const rows = selectedRows();
            const totals = calculateClaimGrossReturns(rows);
            const gross = totals.gross;
            const returns = totals.returns;
            const system = gross - returns;
            const currentNet = dialog.get_value("net_amount_to_pay");
            const suggestedNet = Math.max(system, 0);
            const net = currentNet === null || currentNet === undefined || currentNet === "" ? suggestedNet : flt(currentNet);
            const discount = Math.max(system - net, 0);
            const excess_credit = Math.max(returns - gross, 0);
            return { gross, returns, system, net, discount, excess_credit };
        };

        const summaryHtml = (summary) => {
            const discountClass = summary.discount > 0.005 ? "sra-candidate-advance" : "sra-candidate-ok";
            const systemClass = summary.system < -0.005 ? "sra-candidate-over" : "sra-candidate-ok";
            const excessHtml = summary.excess_credit > 0.005
                ? `<span>${__("Excess Credits")}: <strong class="sra-candidate-over">${money(summary.excess_credit)}</strong></span>`
                : "";
            return `
                <span>${__("Gross Invoices")}: <strong>${money(summary.gross)}</strong></span>
                <span>${__("Returns / Credits")}: <strong>${money(summary.returns)}</strong></span>
                <span>${__("System Claim Total")}: <strong class="${systemClass}">${money(summary.system)}</strong></span>
                <span>${__("Settlement Discount")}: <strong class="${discountClass}">${money(summary.discount)}</strong></span>
                ${excessHtml}
                <span>${__("Net Amount To Pay")}: <strong class="sra-claim-net">${money(summary.net)}</strong></span>`;
        };

        const refreshNetIfAuto = () => {
            const rows = selectedRows();
            const totals = calculateClaimGrossReturns(rows);
            const system = Math.max(totals.gross - totals.returns, 0);
            if (dialog.__sra_claim_auto_net) {
                dialog.set_value("net_amount_to_pay", system);
            }
        };

        const updateSummaryOnly = () => {
            const field = dialog.fields_dict.claim_candidates_html;
            field.$wrapper.find(".sra-claim-summary").html(summaryHtml(getSummary()));
        };

        const renderClaimCandidates = (rows) => {
            dialog.__sra_claim_candidates = rows || [];
            refreshNetIfAuto();
            const field = dialog.fields_dict.claim_candidates_html;
            const summary = getSummary();
            if (!dialog.__sra_claim_candidates.length) {
                field.$wrapper.html(`<div class="sra-claim-empty">${__("No loaded claim candidates yet. Choose period/search then click Load Claim Candidates.")}</div>`);
                return;
            }
            const body = dialog.__sra_claim_candidates.map((row, idx) => {
                const isReturn = cint(row.is_return);
                const typeBadge = isReturn
                    ? `<span class="sra-settlement-badge sra-settlement-credit">${__("Return Credit")}</span>`
                    : `<span class="sra-settlement-badge sra-settlement-claim">${__("Claim Invoice")}</span>`;
                return `
                    <tr data-idx="${idx}">
                        <td><input type="checkbox" class="sra-claim-select" data-idx="${idx}" ${row.__sra_selected === true ? "checked" : ""}></td>
                        <td>${typeBadge}</td>
                        <td class="sra-claim-doc">${this.docLink("Purchase Invoice", row.purchase_invoice)}</td>
                        <td>${this.esc(row.supplier_invoice_no || "")}</td>
                        <td>${this.esc(row.supplier_invoice_date || "")}</td>
                        <td class="sra-claim-money">${money(row.outstanding_amount)}</td>
                        <td><input class="form-control input-sm sra-claim-amount-input" data-idx="${idx}" value="${flt(row.included_amount || 0)}"></td>
                        <td>${this.settlementBadge(row.settlement_classification || (isReturn ? __("Return Credit") : __("Claim Invoice")))}</td>
                        <td>${this.docLink("Pharmacy Return Case", row.related_return_case)}</td>
                        <td>${this.esc(row.invoice_status || "")}</td>
                    </tr>`;
            }).join("");
            field.$wrapper.html(`
                <div class="sra-claim-summary">${summaryHtml(summary)}</div>
                <div class="sra-claim-help">${__("Loaded rows are not selected automatically. Use Select Claim Invoices for payable invoices only, then manually tick the Return Credits / Debit Notes you want to deduct. The draft will not be submitted automatically.")}</div>
                <div class="sra-claim-candidate-list-wrap">
                    <table class="sra-claim-candidate-list">
                        <thead><tr>
                            <th>${__("Use")}</th>
                            <th>${__("Type")}</th>
                            <th>${__("Document")}</th>
                            <th>${__("Supplier Inv No")}</th>
                            <th>${__("Supplier Date")}</th>
                            <th>${__("Outstanding")}</th>
                            <th>${__("Included")}</th>
                            <th>${__("Classification")}</th>
                            <th>${__("Return Case")}</th>
                            <th>${__("Status")}</th>
                        </tr></thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>`);
            field.$wrapper.find(".sra-claim-select").each((idx, el) => {
                const row = dialog.__sra_claim_candidates[cint($(el).data("idx"))];
                el.checked = !!(row && row.__sra_selected === true);
            });
            field.$wrapper.find(".sra-claim-select").on("change", (e) => {
                const idx = cint($(e.currentTarget).data("idx"));
                const row = dialog.__sra_claim_candidates[idx];
                if (row) row.__sra_selected = !!e.currentTarget.checked;
                refreshNetIfAuto();
                updateSummaryOnly();
            });
            field.$wrapper.find(".sra-claim-amount-input").on("change input", (e) => {
                const idx = cint($(e.currentTarget).data("idx"));
                const row = dialog.__sra_claim_candidates[idx];
                if (!row) return;
                const value = flt(e.currentTarget.value || 0);
                row.included_amount = cint(row.is_return) ? -Math.abs(value) : Math.abs(value);
                e.currentTarget.value = row.included_amount;
                refreshNetIfAuto();
                updateSummaryOnly();
            });
        };

        const loadCandidates = async () => {
            const values = dialog.get_values() || {};
            const r = await frappe.call({
                method: "pharma_erp.pharma_erp.page.supplier_running_account.supplier_running_account.get_supplier_claim_draft_candidates",
                args: {
                    company,
                    supplier,
                    from_date: values.period_from || "",
                    to_date: values.period_to || "",
                    search: values.search || "",
                    limit: 500,
                },
                freeze: true,
                freeze_message: __("Loading claim candidates...")
            });
            const rows = (r.message || []).map(row => ({ ...row, selected: false, __sra_selected: false }));
            dialog.__sra_claim_auto_net = true;
            renderClaimCandidates(rows);
            if (!rows.length) {
                frappe.msgprint(__("No open Claim Candidates or Return Credits were found for the selected filters."));
            } else {
                frappe.show_alert({ message: __("Loaded {0} claim candidate(s). Select the invoices and credits you want to include.", [rows.length]), indicator: "blue" }, 6);
            }
        };

        dialog.fields_dict.load_candidates.$input.on("click", loadCandidates);
        dialog.fields_dict.select_all.$input.on("click", () => {
            (dialog.__sra_claim_candidates || []).forEach(row => row.__sra_selected = flt(row.included_amount || 0) > 0);
            dialog.__sra_claim_auto_net = true;
            renderClaimCandidates(dialog.__sra_claim_candidates || []);
        });
        dialog.fields_dict.clear_selection.$input.on("click", () => {
            (dialog.__sra_claim_candidates || []).forEach(row => row.__sra_selected = false);
            dialog.__sra_claim_auto_net = true;
            renderClaimCandidates(dialog.__sra_claim_candidates || []);
        });
        if (dialog.fields_dict.net_amount_to_pay && dialog.fields_dict.net_amount_to_pay.$input) {
            dialog.fields_dict.net_amount_to_pay.$input.on("change input", () => {
                dialog.__sra_claim_auto_net = false;
                updateSummaryOnly();
            });
        }

        dialog.show();
        renderClaimCandidates([]);
    }

    openSupplier() {
        const supplier = this.controls.supplier.get_value();
        if (supplier) frappe.set_route("Form", "Supplier", supplier);
    }

    exportCsv() {
        if (!this.rows.length) {
            frappe.msgprint(__("Load a statement first."));
            return;
        }
        const rows = this.visibleRows();
        const headers = ["Date", "Type", "Document Type", "Document", "Supplier Invoice No", "Settlement Classification", "Outstanding", "Debit", "Credit", "Net Supplier Balance", "Status", "Related Return Case", "Related Supplier Claim", "Next Action", "Notes"];
        const lines = [headers].concat(rows.map(row => [
            row.posting_date || "", row.type || "", row.document_type || "", row.document || "", row.supplier_invoice_no || "",
            row.settlement_classification || "", row.outstanding_amount || 0, row.debit || 0, row.credit || 0, row.running_balance ?? "", row.status || "", row.related_return_case || "", row.related_supplier_claim || "", this.nextActionLabel(row), row.notes || ""
        ]));
        const csv = lines.map(cols => cols.map(value => `"${String(value).replace(/"/g, '""')}"`).join(",")).join("\n");
        const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `supplier-running-account-${this.controls.supplier.get_value() || "supplier"}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
}

// Safety fallback for older cached page instances / patched renderRow calls.
SupplierRunningAccountPage.prototype.rowTypeClass = SupplierRunningAccountPage.prototype.rowTypeClass || function (row) {
    const docType = String(row.document_type || row.voucher_type || "").trim().toLowerCase();
    const type = String(row.type || "").trim().toLowerCase();
    const paymentType = String(row.payment_type || "").trim().toLowerCase();

    if (docType === "purchase invoice" && cint(row.is_purchase_return)) return "sra-row-return";
    if (type.includes("return") || type.includes("debit note") || type.includes("credit note")) return "sra-row-return";

    if (docType === "payment entry" || type.includes("payment entry")) {
        if (paymentType === "receive" || type.includes("refund")) return "sra-row-refund";
        return "sra-row-payment";
    }
    if (type.includes("supplier refund")) return "sra-row-refund";

    if (docType === "journal entry" || type.includes("journal entry")) return "sra-row-journal";
    if (docType === "supplier claim" || type.includes("supplier claim")) return "sra-row-claim";
    if (docType === "purchase invoice" || type.includes("purchase invoice")) return "sra-row-invoice";

    return "sra-row-other";
};

// Safety fallbacks for older cached page instances / patched renderRow calls.
SupplierRunningAccountPage.prototype.rowTypeKey = SupplierRunningAccountPage.prototype.rowTypeKey || function (row) {
    const text = String((row && (row.type || row.document_type || row.voucher_type)) || "").toLowerCase();
    if (!row) return "other";
    if (!row.affects_balance) return "context";
    if (text.includes("purchase return") || text.includes("debit note") || text.includes("credit note") || text.includes("return")) return "return";
    if (text.includes("supplier refund") || text.includes("refund")) return "refund";
    if (text.includes("payment")) {
        const paymentType = String(row.payment_type || "").toLowerCase();
        return paymentType === "receive" ? "refund" : "payment";
    }
    if (text.includes("journal") || text.includes("adjustment")) return "journal";
    if (text.includes("claim")) return "claim";
    if (text.includes("invoice")) return "invoice";
    return "other";
};

SupplierRunningAccountPage.prototype.rowTypeClass = SupplierRunningAccountPage.prototype.rowTypeClass || function (row) {
    const key = this.rowTypeKey(row);
    return key ? `sra-row-${key}` : "";
};

SupplierRunningAccountPage.prototype.rowPillClass = SupplierRunningAccountPage.prototype.rowPillClass || function (row) {
    const key = this.rowTypeKey(row);
    return key ? `sra-pill-${key}` : "";
};

SupplierRunningAccountPage.prototype.balanceClass = SupplierRunningAccountPage.prototype.balanceClass || function (value) {
    const amount = flt(value || 0, 2);
    if (amount < -0.005) return "sra-balance-negative";
    return "sra-balance-positive";
};

// Safety fallback for main statement settlement badges.
SupplierRunningAccountPage.prototype.settlementBadge = SupplierRunningAccountPage.prototype.settlementBadge || function (classification) {
    const value = String(classification || "");
    const lower = value.toLowerCase();
    let cls = "sra-settlement-other";
    if (lower.includes("claim")) cls = "sra-settlement-claim";
    else if (lower.includes("cash")) cls = "sra-settlement-cash";
    else if (lower.includes("credit")) cls = "sra-settlement-credit";
    return `<span class="sra-settlement-badge ${cls}">${this.esc(value || __("Not Set"))}</span>`;
};

