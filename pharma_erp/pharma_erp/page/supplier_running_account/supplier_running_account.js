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
                @media(max-width: 1100px) { .sra-filters, .sra-cards { grid-template-columns:repeat(2,minmax(180px,1fr)); } }
                @media(max-width: 760px) { .sra-filters, .sra-cards { grid-template-columns:1fr; } }
            </style>
        `);
    }

    render() {
        this.$main.empty().append(`
            <div class="sra">
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
        this.rows = data.rows || [];
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

    renderRows() {
        const $table = this.$main.find("#sra-table");
        if (!this.rows.length) {
            $table.html(`<tbody><tr><td><div class="sra-empty">${__("No rows to display.")}</div></td></tr></tbody>`);
            return;
        }
        const header = `
            <thead><tr>
                <th>${__("Date")}</th>
                <th>${__("Type")}</th>
                <th>${__("Document")}</th>
                <th>${__("Supplier Invoice No")}</th>
                <th>${__("Settlement Classification")}</th>
                <th>${__("Debit")}</th>
                <th>${__("Credit")}</th>
                <th>${__("Net Supplier Balance / صافي المورد")}</th>
                <th>${__("Status")}</th>
                <th>${__("Return Case")}</th>
                <th>${__("Supplier Claim")}</th>
                <th>${__("Notes")}</th>
            </tr></thead>`;
        const body = [
            this.renderBalanceRow(__("Opening Supplier Net / رصيد أول المدة"), this.summary.opening_balance, this.controls.from_date.get_value()),
            this.rows.map(row => this.renderRow(row)).join(""),
            this.renderBalanceRow(__("Closing Supplier Net / صافي المورد النهائي"), this.summary.closing_balance, this.controls.to_date.get_value(), true),
        ].join("");
        $table.html(`${header}<tbody>${body}</tbody>`);
        $table.find("[data-doctype][data-name]").on("click", (event) => {
            event.preventDefault();
            const $link = $(event.currentTarget);
            frappe.set_route("Form", $link.data("doctype"), $link.data("name"));
        });
    }


    rowTypeKey(row) {
        const text = String((row && row.type) || '').toLowerCase();
        if (!row || !row.affects_balance) return 'context';
        if (text.includes('purchase return') || text.includes('debit note') || text.includes('return')) return 'return';
        if (text.includes('supplier refund') || text.includes('refund')) return 'refund';
        if (text.includes('payment')) return 'payment';
        if (text.includes('journal') || text.includes('adjustment')) return 'journal';
        if (text.includes('invoice')) return 'invoice';
        return '';
    }

    rowTypeClass(row) {
        const key = this.rowTypeKey(row);
        return key ? `sra-row-${key}` : '';
    }

    rowPillClass(row) {
        const key = this.rowTypeKey(row);
        return key ? `sra-pill-${key}` : '';
    }

    balanceClass(value) {
        const amount = flt(value || 0, 2);
        if (amount < 0) return 'sra-balance-negative';
        return 'sra-balance-positive';
    }

    renderBalanceRow(label, value, dateValue, isClosing=false) {
        const note = isClosing
            ? __("Final net after all displayed official movements.")
            : __("Net before the first displayed movement.");
        return `<tr class="sra-balance-row sra-row-balance">
            <td>${dateValue ? frappe.datetime.str_to_user(dateValue) : ""}</td>
            <td><span class="sra-pill sra-pill-balance">${this.esc(label)}</span></td>
            <td colspan="5"><span class="sra-balance-label">${this.esc(note)}</span></td>
            <td class="sra-amount ${this.balanceClass(value || 0)}">${this.money(value || 0)}</td>
            <td colspan="4">${isClosing ? this.esc(__("Positive = payable to supplier; negative = credit/refund due to pharmacy.")) : ""}</td>
        </tr>`;
    }

    renderRow(row) {
        const classes = [this.rowTypeClass(row), !row.affects_balance ? "sra-row-context" : "", row.is_cancelled ? "sra-row-cancelled" : ""].filter(Boolean).join(" ");
        return `<tr class="${classes}">
            <td>${frappe.datetime.str_to_user(row.posting_date || "")}</td>
            <td><span class="sra-pill ${this.rowPillClass(row)}">${this.esc(row.type || "")}</span></td>
            <td>${this.docLink(row.document_type, row.document)}</td>
            <td>${this.esc(row.supplier_invoice_no || "")}</td>
            <td>${this.esc(row.settlement_classification || "")}</td>
            <td class="sra-amount sra-debit-amount">${this.money(row.debit || 0)}</td>
            <td class="sra-amount sra-credit-amount">${this.money(row.credit || 0)}</td>
            <td class="sra-amount ${row.running_balance === null || row.running_balance === undefined ? "" : this.balanceClass(row.running_balance || 0)}">${row.running_balance === null || row.running_balance === undefined ? `<span class="sra-pill sra-pill-muted sra-pill-context">${__("Context")}</span>` : this.money(row.running_balance || 0)}</td>
            <td>${this.esc(row.status || "")}</td>
            <td>${this.docLink("Pharmacy Return Case", row.related_return_case)}</td>
            <td>${this.docLink("Supplier Claim", row.related_supplier_claim)}</td>
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

    openSupplier() {
        const supplier = this.controls.supplier.get_value();
        if (supplier) frappe.set_route("Form", "Supplier", supplier);
    }

    exportCsv() {
        if (!this.rows.length) {
            frappe.msgprint(__("Load a statement first."));
            return;
        }
        const headers = ["Date", "Type", "Document Type", "Document", "Supplier Invoice No", "Settlement Classification", "Debit", "Credit", "Net Supplier Balance", "Status", "Related Return Case", "Related Supplier Claim", "Notes"];
        const lines = [headers].concat(this.rows.map(row => [
            row.posting_date || "", row.type || "", row.document_type || "", row.document || "", row.supplier_invoice_no || "",
            row.settlement_classification || "", row.debit || 0, row.credit || 0, row.running_balance ?? "", row.status || "", row.related_return_case || "", row.related_supplier_claim || "", row.notes || ""
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
