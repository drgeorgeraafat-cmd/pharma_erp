frappe.pages["near-expiry-action-center"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Near Expiry Action Center"),
        single_column: true,
    });

    page.main.empty();
    new NearExpiryActionCenter(page, wrapper);
};

class NearExpiryActionCenter {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = wrapper;
        this.bootstrap = null;
        this.controls = {};
        this.loading = false;
        this.initializing = false;
        this.methodBase = "pharma_erp.pharma_erp.page.near_expiry_action_center.near_expiry_action_center";
        this.mount();
        this.initialize();
    }

    mount() {
        this.page.main.html(`
            <style>
                .nea-wide-page .layout-main-section-wrapper,
                .nea-wide-page .layout-main-section { max-width:none !important; width:100% !important; }
                .nea-wide-page .page-body .container { max-width:none !important; width:100% !important; padding-left:18px; padding-right:18px; }
                .nea-shell { width:100%; max-width:none; padding:8px 0 28px; }
                .nea-note { margin:0 0 12px; color:var(--text-muted); font-size:12px; }
                .nea-filter-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px 10px; align-items:end; margin-bottom:12px; }
                .nea-filter-box { min-width:0; }
                .nea-actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
                .nea-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); gap:8px; margin:12px 0; }
                .nea-card { border:1px solid var(--border-color); border-radius:8px; padding:10px 11px; background:var(--card-bg); min-height:68px; }
                .nea-card-label { color:var(--text-muted); font-size:10px; text-transform:uppercase; letter-spacing:.03em; }
                .nea-card-value { font-size:18px; font-weight:600; margin-top:4px; overflow-wrap:anywhere; }
                .nea-warning { border-left:3px solid var(--yellow-500); background:var(--yellow-50); padding:8px 10px; margin:6px 0; border-radius:4px; }
                .nea-table-wrap { overflow:visible; border:0; background:transparent; }
                .nea-result-list { display:grid; gap:10px; width:100%; }
                .nea-result-card { border:1px solid var(--border-color); border-radius:9px; background:var(--card-bg); padding:10px 12px; min-width:0; }
                .nea-result-card:hover { background:var(--fg-hover-color); }
                .nea-result-head { display:grid; grid-template-columns:minmax(180px,1.4fr) minmax(125px,.9fr) minmax(115px,.8fr) minmax(145px,1fr) minmax(130px,.9fr); gap:8px 12px; align-items:start; }
                .nea-result-metrics { display:grid; grid-template-columns:repeat(8,minmax(95px,1fr)); gap:8px; margin-top:10px; padding-top:9px; border-top:1px solid var(--border-color); }
                .nea-field { min-width:0; overflow-wrap:anywhere; }
                .nea-field-label { color:var(--text-muted); font-size:9px; text-transform:uppercase; letter-spacing:.035em; margin-bottom:2px; }
                .nea-field-value { font-size:12px; line-height:1.35; }
                .nea-field-sub { color:var(--text-muted); font-size:10px; line-height:1.3; margin-top:2px; }
                .nea-status { display:inline-block; border-radius:999px; padding:2px 8px; font-size:11px; font-weight:600; }
                .nea-status-expired { background:var(--red-100); color:var(--red-700); }
                .nea-status-critical { background:var(--orange-100); color:var(--orange-700); }
                .nea-status-urgent { background:var(--yellow-100); color:var(--yellow-700); }
                .nea-status-near { background:var(--blue-100); color:var(--blue-700); }
                .nea-blockers { color:var(--text-muted); font-size:10px; }
                .nea-row-actions { display:flex; gap:5px; flex-wrap:wrap; margin-top:10px; padding-top:9px; border-top:1px solid var(--border-color); }
                .nea-empty { padding:26px; text-align:center; color:var(--text-muted); border:1px solid var(--border-color); border-radius:8px; background:var(--card-bg); }
                .nea-meta { font-size:11px; color:var(--text-muted); margin:8px 0; }
                @media (max-width:1200px) {
                    .nea-result-head { grid-template-columns:repeat(3,minmax(0,1fr)); }
                    .nea-result-metrics { grid-template-columns:repeat(4,minmax(0,1fr)); }
                }
                @media (max-width:768px) {
                    .nea-filter-grid { grid-template-columns:1fr; }
                    .nea-result-head { grid-template-columns:1fr 1fr; }
                    .nea-result-metrics { grid-template-columns:1fr 1fr; }
                    .nea-wide-page .page-body .container { padding-left:10px; padding-right:10px; }
                }
            </style>
            <div class="nea-shell">
                <div class="nea-note">
                    ${__("Read-only operational view. Warehouse / Stock Ledger remain the stock truth; this page never posts stock automatically.")}
                </div>
                <div class="nea-filter-grid" data-role="filters"></div>
                <div class="nea-actions">
                    <button class="btn btn-primary btn-sm" data-action="refresh">${__("Refresh")}</button>
                    <button class="btn btn-default btn-sm" data-action="reset">${__("Reset Filters")}</button>
                </div>
                <div class="nea-meta" data-role="meta"></div>
                <div data-role="warnings"></div>
                <div class="nea-cards" data-role="cards"></div>
                <div class="nea-table-wrap" data-role="table"></div>
            </div>
        `);

        this.$root = this.page.main.find(".nea-shell");
        this.$pageContainer = $(this.wrapper).closest(".page-container");
        if (!this.$pageContainer.length) this.$pageContainer = $(this.wrapper);
        this.$pageContainer.addClass("nea-wide-page");
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
            if (selectedBranch) {
                await this.refresh();
            } else {
                this.renderEmpty(__("Select a Branch, then press Refresh."));
            }
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
        const $box = $('<div class="nea-filter-box"></div>').appendTo(this.$filters);
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
            } catch (error) {
                this.showError(error);
            }
        };

        this.makeControl("warehouse", {
            fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Select", options: warehouseOptions,
        }, "");

        const defaultHorizon = cint(this.bootstrap.default_horizon_days) || 180;
        const defaultPreset = [30, 60, 90, 180].includes(defaultHorizon) ? String(defaultHorizon) : "Custom";
        const horizon = this.makeControl("horizon_preset", {
            fieldname: "horizon_preset", label: __("Expiry Horizon"), fieldtype: "Select",
            options: "30\n60\n90\n180\nCustom",
        }, defaultPreset);
        horizon.df.onchange = () => this.syncCustomHorizonVisibility();

        this.makeControl("custom_horizon_days", {
            fieldname: "custom_horizon_days", label: __("Custom Horizon (days)"), fieldtype: "Int", min: 1,
        }, this.bootstrap.default_horizon_days || 180);

        this.makeControl("critical_days", {
            fieldname: "critical_days", label: __("Critical ≤ days"), fieldtype: "Int", min: 0,
        }, this.bootstrap.default_critical_days || 30);

        this.makeControl("urgent_days", {
            fieldname: "urgent_days", label: __("Urgent ≤ days"), fieldtype: "Int", min: 0,
        }, this.bootstrap.default_urgent_days || 60);

        this.makeControl("status", {
            fieldname: "status", label: __("Status"), fieldtype: "Select",
            options: "\nExpired\nCritical\nUrgent\nNear Expiry",
        }, "");

        this.makeControl("item_group", {
            fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group",
        }, "");
        this.makeControl("item_code", {
            fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item",
        }, "");
        this.makeControl("batch_no", {
            fieldname: "batch_no", label: __("Batch"), fieldtype: "Link", options: "Batch",
        }, "");

        this.syncCustomHorizonVisibility();
    }

    rebuildWarehouseControl() {
        const control = this.controls.warehouse;
        if (!control) return;
        control.df.options = ["", ...(this.bootstrap.warehouses || []).map((r) => r.warehouse)].join("\n");
        control.set_value("");
        control.refresh();
    }

    syncCustomHorizonVisibility() {
        const isCustom = (this.controls.horizon_preset?.get_value() || "") === "Custom";
        const control = this.controls.custom_horizon_days;
        if (!control) return;
        control.$wrapper.toggle(isCustom);
    }

    horizonDays() {
        const preset = this.controls.horizon_preset?.get_value() || "";
        if (preset === "Custom") return cint(this.controls.custom_horizon_days?.get_value()) || 1;
        return cint(preset) || cint(this.bootstrap.default_horizon_days) || 180;
    }

    filters() {
        return {
            branch: this.controls.branch?.get_value() || "",
            warehouse: this.controls.warehouse?.get_value() || "",
            horizon_days: this.horizonDays(),
            critical_days: cint(this.controls.critical_days?.get_value()),
            urgent_days: cint(this.controls.urgent_days?.get_value()),
            status: this.controls.status?.get_value() || "",
            item_group: this.controls.item_group?.get_value() || "",
            item_code: this.controls.item_code?.get_value() || "",
            batch_no: this.controls.batch_no?.get_value() || "",
        };
    }

    async refresh() {
        if (this.loading) return;
        const filters = this.filters();
        if (!filters.branch) {
            frappe.msgprint(__("Select a Branch first."));
            return;
        }
        this.loading = true;
        this.page.set_indicator(__("Loading"), "orange");
        this.$table.html(`<div class="nea-empty">${__("Loading Near Expiry stock...")}</div>`);
        try {
            const data = await this.call("get_action_center", filters);
            this.render(data);
            this.page.set_indicator(__("Read only"), "blue");
        } catch (error) {
            this.page.clear_indicator();
            this.showError(error);
        } finally {
            this.loading = false;
        }
    }

    async resetFilters() {
        const branch = this.controls.branch?.get_value() || this.bootstrap.selected_branch || "";
        this.initializing = true;
        try {
            await this.loadBootstrap(branch);
            this.buildFilters();
            if (branch && this.controls.branch) {
                await Promise.resolve(this.controls.branch.set_value(branch));
            }
        } finally {
            this.initializing = false;
        }
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
            `${__("As of")}: ${data.as_of_date || "—"} • ${__("Horizon")}: ${f.horizon_days || "—"} ${__("days")} • ` +
            `${__("Critical")}: ≤${f.critical_days ?? "—"} • ${__("Urgent")}: ≤${f.urgent_days ?? "—"} • ${__("Mode")}: ${data.mode || "read_only_action_center"}`
        );
    }

    renderWarnings(warnings) {
        if (!warnings.length) {
            this.$warnings.empty();
            return;
        }
        this.$warnings.html(warnings.map((message) => `<div class="nea-warning">${this.esc(message)}</div>`).join(""));
    }

    renderCards(summary, currency) {
        const money = (value) => this.money(value, currency);
        const cards = [
            [__("Expired Batches"), summary.expired_batches ?? 0],
            [__("Critical Batches"), summary.critical_batches ?? 0],
            [__("Urgent Batches"), summary.urgent_batches ?? 0],
            [__("Near Expiry Batches"), summary.near_expiry_batches ?? 0],
            [__("Physical Qty at Risk"), this.qty(summary.physical_qty_at_risk || 0)],
            [__("Retail Exposure"), money(summary.retail_exposure || 0)],
            [__("At-Risk Cost"), money(summary.at_risk_cost || 0)],
            [__("Rows"), summary.rows ?? 0],
        ];
        this.$cards.html(cards.map(([label, value]) => `
            <div class="nea-card"><div class="nea-card-label">${this.esc(label)}</div><div class="nea-card-value">${this.esc(value)}</div></div>
        `).join(""));
    }

    renderTable(rows, currency) {
        if (!rows.length) {
            this.renderEmpty(__("No stock with expiry inside the selected horizon was found for the current filters."));
            return;
        }

        const body = rows.map((row) => {
            const statusClass = this.statusClass(row.expiry_status);
            const blockers = (row.availability_blockers || []).join(", ") || "—";
            const retailPrice = row.retail_price === null || row.retail_price === undefined ? __("Unresolved") : this.money(row.retail_price, currency);
            const retailExposure = row.retail_exposure === null || row.retail_exposure === undefined ? __("Unresolved") : this.money(row.retail_exposure, currency);
            const valuationRate = row.valuation_rate === null || row.valuation_rate === undefined ? __("Unresolved") : this.money(row.valuation_rate, currency);
            const atRiskCost = row.at_risk_cost === null || row.at_risk_cost === undefined ? __("Unresolved") : this.money(row.at_risk_cost, currency);
            const itemGroup = row.item_group || "—";
            const expiryDetail = `${row.expiry_date || "—"} · ${row.days_remaining ?? "—"} ${__("days")}`;
            const locationDetail = `${row.branch || "—"} · ${row.warehouse || "—"}`;
            return `
                <div class="nea-result-card">
                    <div class="nea-result-head">
                        <div class="nea-field">
                            <div class="nea-field-label">${__("Item")}</div>
                            <div class="nea-field-value"><strong>${this.esc(row.item_name || row.item_code)}</strong></div>
                            <div class="nea-field-sub">${this.esc(row.item_code)} · ${this.esc(itemGroup)}</div>
                        </div>
                        <div class="nea-field">
                            <div class="nea-field-label">${__("Batch")}</div>
                            <div class="nea-field-value">${this.esc(row.batch_no)}</div>
                        </div>
                        <div class="nea-field">
                            <div class="nea-field-label">${__("Status")}</div>
                            <div class="nea-field-value"><span class="nea-status ${statusClass}">${this.esc(row.expiry_status)}</span></div>
                        </div>
                        <div class="nea-field">
                            <div class="nea-field-label">${__("Expiry / Days Left")}</div>
                            <div class="nea-field-value">${this.esc(expiryDetail)}</div>
                        </div>
                        <div class="nea-field">
                            <div class="nea-field-label">${__("Branch / Warehouse")}</div>
                            <div class="nea-field-value">${this.esc(locationDetail)}</div>
                        </div>
                    </div>
                    <div class="nea-result-metrics">
                        <div class="nea-field"><div class="nea-field-label">${__("Physical Qty")}</div><div class="nea-field-value">${this.qty(row.physical_qty)} ${this.esc(row.stock_uom || "")}</div></div>
                        <div class="nea-field"><div class="nea-field-label">${__("Sellable Qty")}</div><div class="nea-field-value">${this.qty(row.sellable_qty)} ${this.esc(row.stock_uom || "")}</div></div>
                        <div class="nea-field"><div class="nea-field-label">${__("Blockers")}</div><div class="nea-field-value nea-blockers">${this.esc(blockers)}</div></div>
                        <div class="nea-field"><div class="nea-field-label">${__("Retail Price")}</div><div class="nea-field-value">${this.esc(retailPrice)}</div><div class="nea-field-sub">${this.esc(row.retail_price_source || "")}</div></div>
                        <div class="nea-field"><div class="nea-field-label">${__("Retail Exposure")}</div><div class="nea-field-value">${this.esc(retailExposure)}</div></div>
                        <div class="nea-field"><div class="nea-field-label">${__("Valuation Rate")}</div><div class="nea-field-value">${this.esc(valuationRate)}</div><div class="nea-field-sub">${this.esc(row.valuation_source || "")}</div></div>
                        <div class="nea-field"><div class="nea-field-label">${__("At-Risk Cost")}</div><div class="nea-field-value">${this.esc(atRiskCost)}</div></div>
                        <div class="nea-field"><div class="nea-field-label">${__("Action Status")}</div><div class="nea-field-value">${this.esc(row.action_status || "—")}</div></div>
                    </div>
                    <div class="nea-row-actions">
                        <button class="btn btn-xs btn-default" data-row-action="batch" data-batch="${this.attr(row.batch_no)}">${__("Batch")}</button>
                        <button class="btn btn-xs btn-default" data-row-action="item" data-item="${this.attr(row.item_code)}">${__("Item")}</button>
                        <button class="btn btn-xs btn-default" data-row-action="ledger" data-item="${this.attr(row.item_code)}" data-batch="${this.attr(row.batch_no)}" data-warehouse="${this.attr(row.warehouse)}">${__("Stock Ledger")}</button>
                        <button class="btn btn-xs btn-primary" data-row-action="return" data-item="${this.attr(row.item_code)}" data-batch="${this.attr(row.batch_no)}" data-warehouse="${this.attr(row.warehouse)}">${__("Expired Drugs Return")}</button>
                    </div>
                </div>`;
        }).join("");

        this.$table.html(`<div class="nea-result-list">${body}</div>`);
    }

    renderEmpty(message) {
        this.$cards.empty();
        this.$warnings.empty();
        this.$table.html(`<div class="nea-empty">${this.esc(message)}</div>`);
    }

    handleRowAction(event) {
        const $button = $(event.currentTarget);
        const action = $button.data("row-action");
        const item = String($button.data("item") || "");
        const batch = String($button.data("batch") || "");
        const warehouse = String($button.data("warehouse") || "");

        if (action === "batch" && batch) {
            frappe.set_route("Form", "Batch", batch);
            return;
        }
        if (action === "item" && item) {
            frappe.set_route("Form", "Item", item);
            return;
        }
        if (action === "ledger") {
            frappe.set_route("query-report", "Stock Ledger", {
                item_code: item,
                warehouse,
                batch_no: batch,
            });
            return;
        }
        if (action === "return") {
            frappe.show_alert({
                message: __("Review Item {0}, Batch {1}, Warehouse {2} in the existing Expired Drugs Return workflow.", [item, batch, warehouse]),
                indicator: "blue",
            }, 8);
            frappe.set_route("purchase-returns-management");
        }
    }

    statusClass(status) {
        if (status === "Expired") return "nea-status-expired";
        if (status === "Critical") return "nea-status-critical";
        if (status === "Urgent") return "nea-status-urgent";
        return "nea-status-near";
    }

    money(value, currency) {
        const amount = flt(value || 0);
        const code = String(currency || "").trim().toUpperCase();
        const formatted = amount.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
        return code ? `${code} ${formatted}` : formatted;
    }

    qty(value) {
        return flt(value || 0, 6).toLocaleString(undefined, { maximumFractionDigits: 6 });
    }

    esc(value) {
        return frappe.utils.escape_html(String(value ?? ""));
    }

    attr(value) {
        return this.esc(value).replace(/"/g, "&quot;");
    }

    showError(error) {
        console.error(error);
        frappe.msgprint({
            title: __("Near Expiry Action Center"),
            message: frappe.utils.escape_html(String(error?.message || error || __("Unexpected error"))),
            indicator: "red",
        });
    }
}
