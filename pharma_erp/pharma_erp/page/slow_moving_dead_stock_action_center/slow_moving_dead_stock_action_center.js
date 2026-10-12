frappe.pages["slow-moving-dead-stock-action-center"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Slow Moving & Dead Stock Action Center"),
        single_column: true,
    });
    page.main.empty();
    new SlowMovingDeadStockActionCenter(page, wrapper);
};

class SlowMovingDeadStockActionCenter {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.bootstrap = null;
        this.controls = {};
        this.loading = false;
        this.initializing = false;
        this.methodBase = "pharma_erp.pharma_erp.page.slow_moving_dead_stock_action_center.slow_moving_dead_stock_action_center";
        this.mount();
        this.initialize();
    }

    mount() {
        this.page.main.html(`
            <style>
                .smds-wide-page .layout-main-section-wrapper,
                .smds-wide-page .layout-main-section { max-width:none !important; width:100% !important; }
                .smds-wide-page .page-body .container { max-width:none !important; width:100% !important; padding-left:18px; padding-right:18px; }
                .smds-shell { width:100%; max-width:none; padding:8px 0 28px; }
                .smds-note { margin:0 0 12px; color:var(--text-muted); font-size:12px; }
                .smds-filter-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(155px,1fr)); gap:8px 10px; align-items:end; margin-bottom:12px; }
                .smds-filter-box { min-width:0; }
                .smds-actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
                .smds-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); gap:8px; margin:12px 0; }
                .smds-card { border:1px solid var(--border-color); border-radius:8px; padding:10px 11px; background:var(--card-bg); min-height:68px; }
                .smds-card-label { color:var(--text-muted); font-size:10px; text-transform:uppercase; letter-spacing:.03em; }
                .smds-card-value { font-size:18px; font-weight:600; margin-top:4px; overflow-wrap:anywhere; }
                .smds-warning { border-left:3px solid var(--yellow-500); background:var(--yellow-50); padding:8px 10px; margin:6px 0; border-radius:4px; }
                .smds-result-list { display:grid; gap:10px; width:100%; }
                .smds-result-card { border:1px solid var(--border-color); border-radius:9px; background:var(--card-bg); padding:10px 12px; min-width:0; }
                .smds-result-card:hover { background:var(--fg-hover-color); }
                .smds-result-head { display:grid; grid-template-columns:minmax(180px,1.4fr) minmax(135px,.9fr) minmax(120px,.8fr) minmax(150px,1fr) minmax(155px,1fr); gap:8px 12px; align-items:start; }
                .smds-result-metrics { display:grid; grid-template-columns:repeat(6,minmax(105px,1fr)); gap:8px; margin-top:10px; padding-top:9px; border-top:1px solid var(--border-color); }
                .smds-field { min-width:0; overflow-wrap:anywhere; }
                .smds-field-label { color:var(--text-muted); font-size:9px; text-transform:uppercase; letter-spacing:.035em; margin-bottom:2px; }
                .smds-field-value { font-size:12px; line-height:1.35; }
                .smds-field-sub { color:var(--text-muted); font-size:10px; line-height:1.3; margin-top:2px; }
                .smds-status { display:inline-block; border-radius:999px; padding:2px 8px; font-size:11px; font-weight:600; }
                .smds-no-movement { background:var(--red-100); color:var(--red-700); }
                .smds-low-movement { background:var(--orange-100); color:var(--orange-700); }
                .smds-recent-stock { background:var(--blue-100); color:var(--blue-700); }
                .smds-not-sellable { background:var(--gray-200); color:var(--gray-700); }
                .smds-normal { background:var(--green-100); color:var(--green-700); }
                .smds-unresolved { background:var(--yellow-100); color:var(--yellow-700); }
                .smds-row-actions { display:flex; gap:5px; flex-wrap:wrap; margin-top:10px; padding-top:9px; border-top:1px solid var(--border-color); }
                .smds-empty { padding:26px; text-align:center; color:var(--text-muted); border:1px solid var(--border-color); border-radius:8px; background:var(--card-bg); }
                .smds-meta { font-size:11px; color:var(--text-muted); margin:8px 0; }
                .smds-history-table { width:100%; border-collapse:collapse; font-size:12px; }
                .smds-history-table th,.smds-history-table td { border-bottom:1px solid var(--border-color); padding:6px 8px; text-align:left; }
                @media (max-width:1200px) {
                    .smds-result-head { grid-template-columns:repeat(3,minmax(0,1fr)); }
                    .smds-result-metrics { grid-template-columns:repeat(3,minmax(0,1fr)); }
                }
                @media (max-width:768px) {
                    .smds-filter-grid { grid-template-columns:1fr; }
                    .smds-result-head { grid-template-columns:1fr 1fr; }
                    .smds-result-metrics { grid-template-columns:1fr 1fr; }
                    .smds-wide-page .page-body .container { padding-left:10px; padding-right:10px; }
                }
            </style>
            <div class="smds-shell">
                <div class="smds-note">
                    ${__("Read-only operational view. Blank Warehouse means Sellable Warehouses only. Movement uses Sales Invoice stock_qty; the production catalog contract is Box. ERPNext Warehouse / Stock Ledger remain stock truth.")}
                </div>
                <div class="smds-filter-grid" data-role="filters"></div>
                <div class="smds-actions">
                    <button class="btn btn-primary btn-sm" data-action="refresh">${__("Refresh")}</button>
                    <button class="btn btn-default btn-sm" data-action="reset">${__("Reset Filters")}</button>
                </div>
                <div class="smds-meta" data-role="meta"></div>
                <div data-role="warnings"></div>
                <div class="smds-cards" data-role="cards"></div>
                <div data-role="table"></div>
            </div>
        `);

        this.$root = this.page.main.find(".smds-shell");
        this.$pageContainer = $(this.wrapper).closest(".page-container");
        if (!this.$pageContainer.length) this.$pageContainer = $(this.wrapper);
        this.$pageContainer.addClass("smds-wide-page");
        this.$pageContainer.find(".layout-main-section-wrapper, .layout-main-section").css({ maxWidth: "none", width: "100%" });
        this.$pageContainer.find(".page-body .container").css({ maxWidth: "none", width: "100%" });
        this.page.main.css({ maxWidth: "none", width: "100%" });
        this.$filters = this.$root.find('[data-role="filters"]');
        this.$warnings = this.$root.find('[data-role="warnings"]');
        this.$cards = this.$root.find('[data-role="cards"]');
        this.$table = this.$root.find('[data-role="table"]');
        this.$meta = this.$root.find('[data-role="meta"]');
        this.$root.on("click", '[data-action="refresh"]', () => this.refresh());
        this.$root.on("click", '[data-action="reset"]', () => this.resetFilters());
        this.$root.on("click", "[data-row-action]", (event) => this.handleRowAction(event));
    }

    async initialize() {
        this.initializing = true;
        try {
            await this.loadBootstrap();
            this.buildFilters();
            const selectedBranch = this.bootstrap.selected_branch || "";
            if (selectedBranch && this.controls.branch) {
                await Promise.resolve(this.controls.branch.set_value(selectedBranch));
            }
            this.initializing = false;
            if (selectedBranch) await this.refresh();
            else this.renderEmpty(__("Select a Branch, then press Refresh."));
        } catch (error) {
            this.initializing = false;
            this.showError(error);
        }
    }

    async call(method, args = {}) {
        const response = await frappe.call({ method: `${this.methodBase}.${method}`, args });
        return response.message || {};
    }

    async loadBootstrap(branch = "") {
        this.bootstrap = await this.call("get_bootstrap", { branch });
        return this.bootstrap;
    }

    makeControl(fieldname, df, value = null) {
        const $box = $('<div class="smds-filter-box"></div>').appendTo(this.$filters);
        const control = frappe.ui.form.make_control({ parent: $box, df, render_input: true });
        control.refresh();
        if (value !== null && value !== undefined) control.set_value(value);
        this.controls[fieldname] = control;
        return control;
    }

    buildFilters() {
        this.$filters.empty();
        this.controls = {};
        const branchOptions = ["", ...(this.bootstrap.branches || [])].join("\n");
        const warehouseOptions = ["", ...(this.bootstrap.warehouses || []).map((r) => r.warehouse)].join("\n");

        const branch = this.makeControl("branch", {
            fieldname: "branch", label: __("Branch"), fieldtype: "Select", options: branchOptions, reqd: 1,
        }, this.bootstrap.selected_branch || "");
        branch.df.onchange = async () => {
            if (this.initializing) return;
            const value = branch.get_value() || "";
            try {
                await this.loadBootstrap(value);
                this.rebuildWarehouseControl();
                if (value) await this.refresh();
            } catch (error) { this.showError(error); }
        };

        this.makeControl("warehouse", {
            fieldname: "warehouse", label: __("Warehouse (blank = sellable only)"), fieldtype: "Select", options: warehouseOptions,
        }, "");

        const lookbackDefault = cint(this.bootstrap.default_lookback_days) || 30;
        const lookbackPreset = [30, 60, 90, 180].includes(lookbackDefault) ? String(lookbackDefault) : "Custom";
        const lookback = this.makeControl("lookback_preset", {
            fieldname: "lookback_preset", label: __("Sales Lookback"), fieldtype: "Select", options: "30\n60\n90\n180\nCustom",
        }, lookbackPreset);
        lookback.df.onchange = () => this.syncCustomVisibility();

        this.makeControl("custom_lookback_days", {
            fieldname: "custom_lookback_days", label: __("Custom Lookback (days)"), fieldtype: "Int", min: 1,
        }, lookbackDefault);

        const maxDefault = flt(this.bootstrap.default_maximum_movement_qty || 0);
        const maxPreset = [0, 1, 2, 5].includes(maxDefault) ? String(maxDefault) : "Custom";
        const maxMovement = this.makeControl("movement_preset", {
            fieldname: "movement_preset", label: __("Maximum Net Movement (Boxes)"), fieldtype: "Select", options: "0\n1\n2\n5\nCustom",
        }, maxPreset);
        maxMovement.df.onchange = () => this.syncCustomVisibility();

        this.makeControl("custom_maximum_movement_qty", {
            fieldname: "custom_maximum_movement_qty", label: __("Custom Maximum Boxes"), fieldtype: "Float", min: 0,
        }, maxDefault);

        const ageDefault = cint(this.bootstrap.default_minimum_stock_age_days) || 90;
        const agePreset = [30, 60, 90, 180].includes(ageDefault) ? String(ageDefault) : "Custom";
        const minAge = this.makeControl("age_preset", {
            fieldname: "age_preset", label: __("Minimum Stock Age"), fieldtype: "Select", options: "30\n60\n90\n180\nCustom",
        }, agePreset);
        minAge.df.onchange = () => this.syncCustomVisibility();

        this.makeControl("custom_minimum_stock_age_days", {
            fieldname: "custom_minimum_stock_age_days", label: __("Custom Minimum Age (days)"), fieldtype: "Int", min: 1,
        }, ageDefault);

        this.makeControl("status", {
            fieldname: "status", label: __("Movement Status"), fieldtype: "Select",
            options: "\nNo Movement\nLow Movement\nRecent Stock\nNot Sellable\nNormal",
        }, "");
        this.makeControl("item_group", {
            fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group",
        }, "");
        this.makeControl("item_code", {
            fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item",
        }, "");
        this.syncCustomVisibility();
    }

    rebuildWarehouseControl() {
        const control = this.controls.warehouse;
        if (!control) return;
        control.df.options = ["", ...(this.bootstrap.warehouses || []).map((r) => r.warehouse)].join("\n");
        control.set_value("");
        control.refresh();
    }

    syncCustomVisibility() {
        this.controls.custom_lookback_days?.$wrapper.toggle((this.controls.lookback_preset?.get_value() || "") === "Custom");
        this.controls.custom_maximum_movement_qty?.$wrapper.toggle((this.controls.movement_preset?.get_value() || "") === "Custom");
        this.controls.custom_minimum_stock_age_days?.$wrapper.toggle((this.controls.age_preset?.get_value() || "") === "Custom");
    }

    lookbackDays() {
        const value = this.controls.lookback_preset?.get_value() || "";
        return value === "Custom" ? (cint(this.controls.custom_lookback_days?.get_value()) || 1) : (cint(value) || 30);
    }

    maximumMovementQty() {
        const value = this.controls.movement_preset?.get_value() || "";
        return value === "Custom" ? (flt(this.controls.custom_maximum_movement_qty?.get_value()) || 0) : flt(value);
    }

    minimumStockAgeDays() {
        const value = this.controls.age_preset?.get_value() || "";
        return value === "Custom" ? (cint(this.controls.custom_minimum_stock_age_days?.get_value()) || 1) : (cint(value) || 90);
    }

    filters() {
        return {
            branch: this.controls.branch?.get_value() || "",
            warehouse: this.controls.warehouse?.get_value() || "",
            lookback_days: this.lookbackDays(),
            maximum_movement_qty: this.maximumMovementQty(),
            minimum_stock_age_days: this.minimumStockAgeDays(),
            status: this.controls.status?.get_value() || "",
            item_group: this.controls.item_group?.get_value() || "",
            item_code: this.controls.item_code?.get_value() || "",
        };
    }

    async refresh() {
        if (this.loading) return;
        const filters = this.filters();
        if (!filters.branch) { frappe.msgprint(__("Select a Branch first.")); return; }
        this.loading = true;
        this.page.set_indicator(__("Loading"), "orange");
        this.$table.html(`<div class="smds-empty">${__("Loading Slow Moving stock...")}</div>`);
        try {
            const data = await this.call("get_action_center", filters);
            this.render(data);
            this.page.set_indicator(__("Read only"), "blue");
        } catch (error) {
            this.page.clear_indicator();
            this.showError(error);
        } finally { this.loading = false; }
    }

    async resetFilters() {
        const branch = this.controls.branch?.get_value() || this.bootstrap.selected_branch || "";
        this.initializing = true;
        try {
            await this.loadBootstrap(branch);
            this.buildFilters();
            if (branch && this.controls.branch) await Promise.resolve(this.controls.branch.set_value(branch));
        } finally { this.initializing = false; }
        if (branch) await this.refresh();
    }

    render(data) {
        this.renderMeta(data);
        this.renderWarnings(data.warnings || []);
        this.renderCards(data.summary || {}, data.currency || this.bootstrap.currency || "");
        this.renderTable(data.rows || [], data.currency || this.bootstrap.currency || "");
    }

    renderMeta(data) {
        const f = data.filters || {};
        this.$meta.text(
            `${__("As of")}: ${data.as_of_date || "—"} • ${__("Lookback")}: ${f.lookback_days || "—"} ${__("days")} • ` +
            `${__("Max Net Movement")}: ${f.maximum_movement_qty ?? "—"} ${__("Boxes")} • ` +
            `${__("Min Stock Age")}: ${f.minimum_stock_age_days || "—"} ${__("days")} • ${__("Scope")}: ${f.default_scope || "—"}`
        );
    }

    renderWarnings(warnings) {
        if (!warnings.length) { this.$warnings.empty(); return; }
        this.$warnings.html(warnings.map((message) => `<div class="smds-warning">${this.esc(message)}</div>`).join(""));
    }

    renderCards(summary, currency) {
        const cards = [
            [__("No Movement"), summary.no_movement_rows ?? 0],
            [__("Low Movement"), summary.low_movement_rows ?? 0],
            [__("Recent Stock"), summary.recent_stock_rows ?? 0],
            [__("Not Sellable"), summary.not_sellable_rows ?? 0],
            [__("Box Physical Qty"), this.qty(summary.box_physical_qty || 0)],
            [__("Net Box Movement"), this.qty(summary.box_net_movement_qty || 0)],
            [__("Retail Exposure"), this.money(summary.retail_exposure || 0, currency)],
            [__("Cost Exposure"), this.money(summary.cost_exposure || 0, currency)],
            [__("Non-Box Legacy Rows"), summary.non_box_rows ?? 0],
            [__("Rows"), summary.rows ?? 0],
        ];
        this.$cards.html(cards.map(([label, value]) =>
            `<div class="smds-card"><div class="smds-card-label">${this.esc(label)}</div><div class="smds-card-value">${this.esc(value)}</div></div>`
        ).join(""));
    }

    renderTable(rows, currency) {
        if (!rows.length) { this.renderEmpty(__("No positive stock rows matched the current Slow Moving filters.")); return; }
        const body = rows.map((row) => {
            const age = row.average_stock_age_days == null ? __("Unresolved") : `${this.qty(row.average_stock_age_days)} ${__("days")}`;
            const lastSale = row.last_sale_date ? `${row.last_sale_date} · ${row.days_since_last_sale ?? "—"} ${__("days ago")}` : __("No recorded sale");
            const blockers = (row.availability_blockers || []).join(", ") || "—";
            return `
                <div class="smds-result-card">
                    <div class="smds-result-head">
                        <div class="smds-field"><div class="smds-field-label">${__("Item")}</div><div class="smds-field-value"><strong>${this.esc(row.item_name || row.item_code)}</strong></div><div class="smds-field-sub">${this.esc(row.item_code)} · ${this.esc(row.item_group || "—")}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Status")}</div><div class="smds-field-value"><span class="smds-status ${this.statusClass(row.movement_status)}">${this.esc(row.movement_status)}</span></div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Package")}</div><div class="smds-field-value">${this.esc(row.package_definition || row.stock_uom || "—")}</div><div class="smds-field-sub">${__("Stock UOM")}: ${this.esc(row.stock_uom || "—")}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Branch / Warehouse")}</div><div class="smds-field-value">${this.esc(`${row.branch || "—"} · ${row.warehouse || "—"}`)}</div><div class="smds-field-sub">${this.esc(row.warehouse_operational_class || "—")}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Last Sale")}</div><div class="smds-field-value">${this.esc(lastSale)}</div></div>
                    </div>
                    <div class="smds-result-metrics">
                        <div class="smds-field"><div class="smds-field-label">${__("Physical Qty")}</div><div class="smds-field-value">${this.qty(row.physical_qty)} ${this.esc(row.stock_uom || "")}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Sellable Qty")}</div><div class="smds-field-value">${this.qty(row.sellable_qty)} ${this.esc(row.stock_uom || "")}</div><div class="smds-field-sub">${this.esc(blockers)}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Gross Movement")}</div><div class="smds-field-value">${this.qty(row.gross_movement_qty)} ${this.esc(row.stock_uom || "")}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Returned")}</div><div class="smds-field-value">${this.qty(row.returned_movement_qty)} ${this.esc(row.stock_uom || "")}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Net Movement")}</div><div class="smds-field-value">${this.qty(row.net_movement_qty)} ${this.esc(row.stock_uom || "")}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Movement Ratio")}</div><div class="smds-field-value">${this.qty(row.movement_ratio_percent)}%</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Average Stock Age")}</div><div class="smds-field-value">${this.esc(age)}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Oldest / Youngest")}</div><div class="smds-field-value">${this.esc(`${row.oldest_remaining_stock_age_days ?? "—"} / ${row.youngest_remaining_stock_age_days ?? "—"} days`)}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Last Inward")}</div><div class="smds-field-value">${this.esc(row.last_inward_date || "—")}</div><div class="smds-field-sub">${__("PR")}: ${this.esc(row.last_purchase_receipt_date || "—")}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Retail Price")}</div><div class="smds-field-value">${row.retail_price == null ? __("Unresolved") : this.money(row.retail_price, currency)}</div><div class="smds-field-sub">${this.esc(row.retail_price_source || "")}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Retail Exposure")}</div><div class="smds-field-value">${row.retail_exposure == null ? __("Unresolved") : this.money(row.retail_exposure, currency)}</div></div>
                        <div class="smds-field"><div class="smds-field-label">${__("Cost Exposure")}</div><div class="smds-field-value">${row.cost_exposure == null ? __("Unresolved") : this.money(row.cost_exposure, currency)}</div><div class="smds-field-sub">${row.valuation_rate == null ? "" : this.money(row.valuation_rate, currency)}</div></div>
                    </div>
                    <div class="smds-row-actions">
                        <button class="btn btn-xs btn-default" data-row-action="item" data-item="${this.attr(row.item_code)}">${__("Open Item")}</button>
                        <button class="btn btn-xs btn-default" data-row-action="ledger" data-item="${this.attr(row.item_code)}" data-warehouse="${this.attr(row.warehouse)}">${__("Stock Ledger")}</button>
                        <button class="btn btn-xs btn-default" data-row-action="sales" data-item="${this.attr(row.item_code)}" data-warehouse="${this.attr(row.warehouse)}">${__("Sales History")}</button>
                        <button class="btn btn-xs btn-default" data-row-action="inward" data-item="${this.attr(row.item_code)}" data-warehouse="${this.attr(row.warehouse)}">${__("Purchase / Inward History")}</button>
                    </div>
                </div>`;
        }).join("");
        this.$table.html(`<div class="smds-result-list">${body}</div>`);
    }

    async handleRowAction(event) {
        const $button = $(event.currentTarget);
        const action = String($button.data("row-action") || "");
        const item = String($button.data("item") || "");
        const warehouse = String($button.data("warehouse") || "");
        if (action === "item" && item) { frappe.set_route("Form", "Item", item); return; }
        if (action === "ledger") { frappe.set_route("query-report", "Stock Ledger", { item_code: item, warehouse }); return; }
        if (action === "sales") { await this.showHistory(item, warehouse, "sales"); return; }
        if (action === "inward") await this.showHistory(item, warehouse, "inward");
    }

    async showHistory(item, warehouse, historyType) {
        try {
            const data = await this.call("get_history", { item_code: item, warehouse, history_type: historyType, limit: 50 });
            const rows = data.rows || [];
            const isSales = data.history_type === "sales";
            const headers = isSales
                ? [__("Date"), __("Invoice"), __("Type"), __("Qty"), __("Stock Qty"), __("UOM"), __("Customer")]
                : [__("Date"), __("Voucher Type"), __("Voucher"), __("Inward Qty"), __("Balance Qty"), __("Batch")];
            const body = rows.map((row) => {
                if (isSales) {
                    return `<tr><td>${this.esc(row.posting_date || "")}</td><td>${this.esc(row.voucher_no || "")}</td><td>${this.esc(cint(row.is_return) ? __("Return") : __("Sale"))}</td><td>${this.qty(row.qty)}</td><td>${this.qty(row.stock_qty)} ${this.esc(row.stock_uom || "")}</td><td>${this.esc(row.uom || "")}</td><td>${this.esc(row.customer_name || row.customer || "")}</td></tr>`;
                }
                return `<tr><td>${this.esc(row.posting_date || "")}</td><td>${this.esc(row.voucher_type || "")}</td><td>${this.esc(row.voucher_no || "")}</td><td>${this.qty(row.actual_qty)}</td><td>${this.qty(row.qty_after_transaction)}</td><td>${this.esc(row.batch_no || "")}</td></tr>`;
            }).join("");
            const table = rows.length
                ? `<div style="max-height:460px;overflow:auto;"><table class="smds-history-table"><thead><tr>${headers.map((h) => `<th>${this.esc(h)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`
                : `<div class="text-muted">${__("No history found.")}</div>`;
            frappe.msgprint({ title: `${isSales ? __("Sales History") : __("Purchase / Inward History")} — ${item}`, message: table, wide: true });
        } catch (error) { this.showError(error); }
    }

    renderEmpty(message) {
        this.$cards.empty();
        this.$warnings.empty();
        this.$table.html(`<div class="smds-empty">${this.esc(message)}</div>`);
    }

    statusClass(status) {
        if (status === "No Movement") return "smds-no-movement";
        if (status === "Low Movement") return "smds-low-movement";
        if (status === "Recent Stock") return "smds-recent-stock";
        if (status === "Not Sellable") return "smds-not-sellable";
        if (status === "Normal") return "smds-normal";
        return "smds-unresolved";
    }

    money(value, currency) {
        const amount = flt(value || 0);
        const code = String(currency || "").trim().toUpperCase();
        const formatted = amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return code ? `${code} ${formatted}` : formatted;
    }

    qty(value) {
        return flt(value || 0, 6).toLocaleString(undefined, { maximumFractionDigits: 6 });
    }

    esc(value) { return frappe.utils.escape_html(String(value ?? "")); }
    attr(value) { return this.esc(value).replace(/"/g, "&quot;"); }

    showError(error) {
        console.error(error);
        frappe.msgprint({
            title: __("Slow Moving & Dead Stock Action Center"),
            message: frappe.utils.escape_html(String(error?.message || error || __("Unexpected error"))),
            indicator: "red",
        });
    }
}
