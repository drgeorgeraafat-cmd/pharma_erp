window.PharmacyInventoryCountApp = {
    api: "pharma_erp.pharma_erp.page.pharmacy_inventory_count_workstation.api",
    state: {
        context: null,
        count: null,
        selectedItem: null,
        scopeOptions: [],
        selectedScopeValue: "",
        itemGroupHierarchy: null,
        selectedMainItemGroup: "",
        itemGroupSummary: null,
        searchRows: [],
        searchIndex: -1,
        searchTimer: null,
        showAllExpected: false,
        showUncountedOnly: false,
        revealedRows: [],
    },

    async call(method, args = {}) {
        const response = await frappe.call({ method: `${this.api}.${method}`, args, freeze: false });
        return response.message;
    },

    async init(container) {
        this.container = container;

        // Frappe keeps page objects in memory. Never carry a previously viewed
        // terminal count into a fresh workstation initialization.
        this.state.count = null;
        this.state.selectedItem = null;
        this.state.scopeOptions = [];
        this.state.selectedScopeValue = "";
        this.state.itemGroupHierarchy = null;
        this.state.selectedMainItemGroup = "";
        this.state.itemGroupSummary = null;
        this.state.searchRows = [];
        this.state.searchIndex = -1;
        this.state.showAllExpected = false;
        this.state.showUncountedOnly = false;
        this.state.revealedRows = [];
        clearTimeout(this.state.searchTimer);
        this.state.searchTimer = null;
        this.state.showAllExpected = false;
        this.state.showUncountedOnly = false;
        this.state.revealedRows = [];

        this.state.context = await this.call("get_context");
        this.renderShell();
        this.bindShell();
        this.applyContext();
        await this.onScopeChange();

        const params = new URLSearchParams(window.location.search || "");
        const countName = (params.get("count") || "").trim();
        if (countName) {
            await this.loadCount(countName);
        } else {
            this.renderCount();
        }

        setTimeout(() => document.getElementById("ic-item-search")?.focus(), 80);
    },

    renderShell() {
        this.container.html(`
            <div id="inventory-count-workstation">
                <div class="ic-topbar">
                    <div class="ic-field"><label>${__("Company")}</label><input id="ic-company" disabled></div>
                    <div class="ic-field"><label>${__("Branch")}</label><select id="ic-branch"></select></div>
                    <div class="ic-field"><label>${__("Warehouse")}</label><select id="ic-warehouse"></select></div>
                    <div class="ic-field ic-field-small"><label>${__("Scope")}</label><select id="ic-scope">
                        <option value="Item">${__("Item")}</option>
                        <option value="Warehouse">${__("Warehouse")}</option>
                        <option value="Branch">${__("Branch")}</option>
                        <option value="Zone">${__("Zone")}</option>
                        <option value="Aisle">${__("Aisle")}</option>
                        <option value="Shelf">${__("Shelf")}</option>
                        <option value="Bin">${__("Bin")}</option>
                        <option value="Item Group">${__("Item Group")}</option>
                        <option value="Batch">${__("Batch")}</option>
                    </select></div>
                    <label class="ic-check"><input id="ic-blind" type="checkbox"> <span>${__("Blind Count")}</span></label>
                    <div class="ic-status-wrap"><span id="ic-feature-status" class="ic-badge"></span><span id="ic-count-status" class="ic-badge"></span></div>
                </div>

                <div class="ic-body">
                    <aside class="ic-search-panel">
                        <div class="ic-panel-title">🔍 ${__("Item Search")}</div>
                        <input id="ic-item-search" class="ic-search-input" type="text" autocomplete="off" placeholder="${__("Item, Arabic name, barcode, ingredient, batch...")}">
                        <div id="ic-search-results" class="ic-search-results"></div>
                        <div id="ic-selected-item" class="ic-selected-item"></div>
                        <button id="ic-create-count" class="btn btn-primary btn-sm ic-wide" type="button">${__("Create Draft")}</button>
                        <button id="ic-new-count" class="btn btn-primary btn-sm ic-wide is-hidden" type="button">${__("New Count")}</button>
                        <button id="ic-open-doctype" class="btn btn-default btn-sm ic-wide is-hidden" type="button">${__("Open Doctype")}</button>
                    </aside>

                    <main class="ic-main-panel">
                        <div class="ic-toolbar">
                            <div>
                                <strong id="ic-count-name">${__("New Inventory Count")}</strong>
                                <small id="ic-count-meta"></small>
                            </div>
                            <div id="ic-actions" class="ic-actions"></div>
                        </div>

                        <div id="ic-summary" class="ic-summary"></div>
                        <div id="ic-missing-banner" class="ic-missing-banner is-hidden"></div>
                        <div class="ic-table-wrap">
                            <table class="table table-bordered ic-table">
                                <thead id="ic-table-head"></thead>
                                <tbody id="ic-table-body"></tbody>
                            </table>
                        </div>
                    </main>
                </div>
            </div>
        `);
    },

    bindShell() {
        const branch = document.getElementById("ic-branch");
        branch.addEventListener("change", async () => {
            this.state.context = await this.call("get_context", { branch: branch.value });
            this.applyContext({ preserveBranch: true });
            this.clearSearch();
            await this.onScopeContextChange();
        });
        document.getElementById("ic-warehouse").addEventListener("change", async () => {
            this.clearSearch();
            await this.onScopeContextChange();
        });
        document.getElementById("ic-blind").addEventListener("change", () => this.clearSearch());
        document.getElementById("ic-scope").addEventListener("change", async () => this.onScopeChange());
        document.getElementById("ic-create-count").addEventListener("click", () => this.createDraft());
        document.getElementById("ic-new-count").addEventListener("click", () => this.resetForNewCount());
        document.getElementById("ic-open-doctype").addEventListener("click", () => {
            if (this.state.count?.name) frappe.set_route("Form", "Pharmacy Inventory Count", this.state.count.name);
        });

        const search = document.getElementById("ic-item-search");
        search.addEventListener("input", () => {
            clearTimeout(this.state.searchTimer);
            this.state.searchTimer = setTimeout(() => this.searchItems(search.value), 220);
        });
        search.addEventListener("keydown", (event) => {
            if (event.key === "ArrowDown") { event.preventDefault(); this.moveSearch(1); }
            if (event.key === "ArrowUp") { event.preventDefault(); this.moveSearch(-1); }
            if (event.key === "Enter") { event.preventDefault(); this.selectSearch(); }
            if (event.key === "Escape") this.clearSearch();
        });
    },

    applyContext(options = {}) {
        const context = this.state.context || {};
        document.getElementById("ic-company").value = context.company || "";
        const branch = document.getElementById("ic-branch");
        const previous = options.preserveBranch ? branch.value : "";
        branch.innerHTML = (context.branches || []).map(name => `<option value="${frappe.utils.escape_html(name)}">${frappe.utils.escape_html(name)}</option>`).join("");
        branch.value = context.branch || previous || (context.branches || [])[0] || "";

        const warehouse = document.getElementById("ic-warehouse");
        warehouse.innerHTML = (context.warehouses || []).map(row => `<option value="${frappe.utils.escape_html(row.warehouse)}">${frappe.utils.escape_html(row.warehouse)}${row.operational_class ? ` — ${frappe.utils.escape_html(row.operational_class)}` : ""}</option>`).join("");
        if (!warehouse.value && context.warehouses?.length) warehouse.value = context.warehouses[0].warehouse;

        const blind = document.getElementById("ic-blind");
        if (!this.state.count) blind.checked = cint(context.blind_count_default ?? 1) === 1;
        const feature = document.getElementById("ic-feature-status");
        const enabled = cint(context.feature_enabled) === 1;
        feature.textContent = enabled ? __("Inventory Count ON") : __("Inventory Count OFF");
        feature.className = `ic-badge ${enabled ? "ic-green" : "ic-red"}`;
        document.getElementById("ic-create-count").disabled = !enabled;
    },

    scopeNeedsWarehouse(scope = null) {
        scope = scope || document.getElementById("ic-scope")?.value || "Item";
        return scope !== "Branch";
    },

    isLocationScope(scope = null) {
        scope = scope || document.getElementById("ic-scope")?.value || "";
        return ["Zone", "Aisle", "Shelf", "Bin"].includes(scope);
    },

    updateScopeControls() {
        const scope = document.getElementById("ic-scope")?.value || "Item";
        const warehouse = document.getElementById("ic-warehouse");
        if (warehouse && !this.state.count) warehouse.disabled = !this.scopeNeedsWarehouse(scope);

        const search = document.getElementById("ic-item-search");
        if (search) {
            search.placeholder = scope === "Batch"
                ? __("Search item first, then choose Batch")
                : __("Item, Arabic name, barcode, ingredient, batch...");
        }
    },

    async onScopeContextChange() {
        if (this.state.count) return;
        this.state.selectedScopeValue = "";
        this.state.itemGroupSummary = null;
        if ((document.getElementById("ic-scope")?.value || "") === "Item Group") {
            await this.loadItemGroupHierarchy();
        } else {
            await this.loadScopeOptions();
        }
        this.updateScopeControls();
        this.renderSelectedItem();
    },

    async onScopeChange() {
        if (this.state.count) return;
        const scope = document.getElementById("ic-scope").value;
        this.state.selectedScopeValue = "";
        this.state.scopeOptions = [];
        this.state.itemGroupSummary = null;
        if (scope !== "Item Group") this.state.selectedMainItemGroup = "";
        if (!["Item", "Batch"].includes(scope)) this.state.selectedItem = null;
        this.clearSearch();
        if (scope === "Item Group") {
            await this.loadItemGroupHierarchy();
        } else {
            await this.loadScopeOptions();
        }
        this.updateScopeControls();
        this.renderSelectedItem();
    },

    async loadScopeOptions(preferredValue = "") {
        const scope = document.getElementById("ic-scope")?.value || "Item";
        if (!["Zone", "Aisle", "Shelf", "Bin", "Item Group", "Batch"].includes(scope)) {
            this.state.scopeOptions = [];
            this.state.selectedScopeValue = "";
            return;
        }

        if (scope === "Batch" && !this.state.selectedItem?.item_code) {
            this.state.scopeOptions = [];
            this.state.selectedScopeValue = "";
            return;
        }

        try {
            const rows = await this.call("get_scope_options", {
                scope_type: scope,
                warehouse: document.getElementById("ic-warehouse")?.value || "",
                item_code: this.state.selectedItem?.item_code || "",
            }) || [];
            this.state.scopeOptions = rows;
            const values = new Set(rows.map(row => row.value));
            if (preferredValue && values.has(preferredValue)) {
                this.state.selectedScopeValue = preferredValue;
            } else if (!values.has(this.state.selectedScopeValue)) {
                this.state.selectedScopeValue = rows[0]?.value || "";
            }
        } catch (error) {
            console.error(error);
            this.state.scopeOptions = [];
            this.state.selectedScopeValue = "";
        }
    },

    async loadItemGroupHierarchy(preferredMain = "", preferredScope = "") {
        try {
            if (!this.state.itemGroupHierarchy) {
                this.state.itemGroupHierarchy = await this.call("get_item_group_hierarchy") || { main_groups: [], descendants: {} };
            }
            const mains = this.state.itemGroupHierarchy.main_groups || [];
            const mainValues = new Set(mains.map(row => row.value));
            if (preferredMain && mainValues.has(preferredMain)) this.state.selectedMainItemGroup = preferredMain;
            else if (!mainValues.has(this.state.selectedMainItemGroup)) this.state.selectedMainItemGroup = mains[0]?.value || "";

            const main = this.state.selectedMainItemGroup;
            const descendants = (this.state.itemGroupHierarchy.descendants || {})[main] || [];
            const scopeValues = new Set([main, ...descendants.map(row => row.value)]);
            if (preferredScope && scopeValues.has(preferredScope)) this.state.selectedScopeValue = preferredScope;
            else if (!scopeValues.has(this.state.selectedScopeValue)) this.state.selectedScopeValue = main;
            await this.refreshItemGroupSummary();
        } catch (error) {
            console.error(error);
            this.state.itemGroupHierarchy = { main_groups: [], descendants: {} };
            this.state.selectedMainItemGroup = "";
            this.state.selectedScopeValue = "";
            this.state.itemGroupSummary = null;
        }
    },

    itemGroupMainSelect() {
        const mains = this.state.itemGroupHierarchy?.main_groups || [];
        if (!mains.length) return `<div class="ic-selection-empty">${__("No Main Item Groups found")}</div>`;
        const options = mains.map(row => `<option value="${frappe.utils.escape_html(row.value)}" ${row.value === this.state.selectedMainItemGroup ? "selected" : ""}>${frappe.utils.escape_html(row.label || row.value)}</option>`).join("");
        return `<div class="ic-field"><label>${__("Main Item Group")}</label><select id="ic-main-item-group">${options}</select></div>`;
    },

    itemGroupScopeSelect() {
        const main = this.state.selectedMainItemGroup;
        if (!main) return `<div class="ic-selection-empty">${__("Select a Main Item Group first")}</div>`;
        const descendants = (this.state.itemGroupHierarchy?.descendants || {})[main] || [];
        const rows = [{ value: main, label: `${__("All")} ${main}`, depth: 0, is_all: true }, ...descendants];
        const options = rows.map(row => {
            const indent = row.is_all ? "" : `${"  ".repeat(Math.max(0, cint(row.depth || 1) - 1))}↳ `;
            return `<option value="${frappe.utils.escape_html(row.value)}" ${row.value === this.state.selectedScopeValue ? "selected" : ""}>${indent}${frappe.utils.escape_html(row.label || row.value)}</option>`;
        }).join("");
        return `<div class="ic-field"><label>${__("Count Scope")}</label><select id="ic-item-group-scope">${options}</select></div>`;
    },

    async refreshItemGroupSummary() {
        const warehouse = document.getElementById("ic-warehouse")?.value || "";
        const itemGroup = this.state.selectedScopeValue || "";
        if (!warehouse || !itemGroup) { this.state.itemGroupSummary = null; return; }
        try {
            this.state.itemGroupSummary = await this.call("get_item_group_scope_summary", { warehouse, item_group: itemGroup });
        } catch (error) {
            console.error(error);
            this.state.itemGroupSummary = null;
        }
    },

    itemGroupSummaryHtml() {
        const summary = this.state.itemGroupSummary;
        if (!summary) return `<div class="ic-selection-empty">${__("Scope preview unavailable")}</div>`;
        return `<div class="ic-selection-card" style="margin-top:8px">
            <strong>${__("Selected Scope")}: ${frappe.utils.escape_html(this.state.selectedMainItemGroup)} → ${frappe.utils.escape_html(this.state.selectedScopeValue)}</strong>
            <small>${__("Warehouse")}: ${frappe.utils.escape_html(summary.warehouse || "")}</small>
            <small>${__("Expected items with stock")}: ${cint(summary.expected_items_with_stock || 0)}</small>
        </div>`;
    },

    scopeOptionSelect(label) {
        const options = this.state.scopeOptions || [];
        if (!options.length) {
            return `<div class="ic-selection-empty">${__("No matching options found for this scope")}</div>`;
        }
        const html = options.map(row => {
            let suffix = "";
            if (row.expiry_date) suffix += ` • ${__("Expiry")}: ${frappe.utils.escape_html(row.expiry_date)}`;
            if (row.qty !== undefined) suffix += ` • ${__("Qty")}: ${flt(row.qty || 0, 3)}`;
            if (row.parent) suffix += ` • ${frappe.utils.escape_html(row.parent)}`;
            return `<option value="${frappe.utils.escape_html(row.value)}" ${row.value === this.state.selectedScopeValue ? "selected" : ""}>${frappe.utils.escape_html(row.label || row.value)}${suffix}</option>`;
        }).join("");
        return `<div class="ic-field"><label>${frappe.utils.escape_html(label)}</label><select id="ic-scope-value">${html}</select></div>`;
    },

    async searchItems(value) {
        const keyword = (value || "").trim();
        const warehouse = document.getElementById("ic-warehouse").value;
        if (!keyword || !warehouse) { this.clearSearch(false); return; }
        try {
            const rows = await this.call("search_items", {
                txt: keyword,
                warehouse,
                blind_count: document.getElementById("ic-blind").checked ? 1 : 0,
            }) || [];
            this.state.searchRows = rows;
            this.state.searchIndex = rows.length ? 0 : -1;
            this.renderSearch();
        } catch (error) {
            console.error(error);
            this.state.searchRows = [];
            this.renderSearch();
        }
    },

    renderSearch() {
        const box = document.getElementById("ic-search-results");
        const rows = this.state.searchRows || [];
        if (!rows.length) {
            box.innerHTML = `<div class="ic-search-empty">${__("No items found")}</div>`;
            return;
        }
        const blind = document.getElementById("ic-blind").checked;
        box.innerHTML = rows.map((item, index) => {
            const image = item.image
                ? `<img src="${frappe.utils.escape_html(item.image)}" alt="">`
                : `<span class="ic-search-placeholder">💊</span>`;
            const subtitle = item.item_name_ar || item.ingredient_summary || item.item_code || "";
            const ingredient = item.item_name_ar && item.ingredient_summary
                ? `<small>${frappe.utils.escape_html(item.ingredient_summary)}</small>` : "";
            const source = item.has_batch_no
                ? `<small class="ic-source-line">${__("Batch / price selection opens after choosing the item")}</small>`
                : "";
            const stock = !blind && item.actual_qty !== undefined
                ? `<span>${__("Stock")}: ${flt(item.actual_qty || 0, 2)}</span>` : `<span>${frappe.utils.escape_html(item.stock_uom || "")}</span>`;
            return `<button type="button" class="ic-search-item ${index === this.state.searchIndex ? "is-active" : ""}" data-index="${index}">
                <div class="ic-search-image">${image}</div>
                <div class="ic-search-text"><strong>${frappe.utils.escape_html(item.item_name || item.item_code)}</strong><small>${frappe.utils.escape_html(subtitle)}</small>${ingredient}${source}</div>
                <div class="ic-search-meta">${stock}</div>
            </button>`;
        }).join("");
        box.querySelectorAll("[data-index]").forEach(button => button.addEventListener("click", () => {
            this.state.searchIndex = cint(button.dataset.index);
            this.selectSearch();
        }));
    },

    moveSearch(direction) {
        const rows = this.state.searchRows || [];
        if (!rows.length) return;
        this.state.searchIndex = (this.state.searchIndex + direction + rows.length) % rows.length;
        this.renderSearch();
        document.querySelector("#ic-search-results .is-active")?.scrollIntoView({ block: "nearest" });
    },

    async selectSearch() {
        const item = this.state.searchRows?.[this.state.searchIndex];
        if (!item) return;

        if (this.state.count?.status === "Counting") {
            let line = (this.state.count.items || []).find(row => row.item_code === item.item_code && !row.batch_no);
            if (line) {
                await this.openCountLine(line, item);
                this.clearSearch();
                return;
            }
            frappe.confirm(
                __("This item is not in the current snapshot. Add it as an unexpected physical item?"),
                async () => {
                    const result = await this.call("add_found_item", {
                        name: this.state.count.name,
                        item_code: item.item_code,
                        warehouse: this.state.count.warehouse,
                        batch_no: "",
                    });
                    this.state.count = result.count;
                    line = (this.state.count.items || []).find(row => row.item_code === item.item_code && cint(row.unexpected_item));
                    if (line) await this.openCountLine(line, item);
                    this.clearSearch();
                }
            );
            return;
        }

        this.state.selectedItem = item;
        const scope = document.getElementById("ic-scope").value;
        if (scope === "Batch") {
            this.state.selectedScopeValue = "";
            await this.loadScopeOptions();
        } else {
            document.getElementById("ic-scope").value = "Item";
            this.state.scopeOptions = [];
            this.state.selectedScopeValue = "";
        }
        this.updateScopeControls();
        this.renderSelectedItem();
        this.clearSearch();
    },

    revealRow(rowName) {
        if (!rowName) return;
        if (!this.state.revealedRows.includes(rowName)) this.state.revealedRows.push(rowName);
    },

    formatBoxUnit(qty, packSize) {
        const pack = Math.max(1, flt(packSize || 1));
        const value = Math.max(0, flt(qty || 0));
        const boxes = Math.floor(value + 1e-9);
        const units = Math.max(0, Math.round((value - boxes) * pack));
        return `${boxes} ${boxes === 1 ? __("Box") : __("Boxes")} + ${units} ${units === 1 ? __("Unit") : __("Units")}`;
    },

    async openCountLine(line, item = null) {
        this.revealRow(line.name);
        this.state.showUncountedOnly = false;
        if (cint(line.has_batch_no)) {
            await this.openBatchCountDialog(line, item);
            return;
        }
        this.renderTable();
        setTimeout(() => document.querySelector(`[data-row-name="${CSS.escape(line.name)}"] .ic-boxes`)?.focus(), 30);
        frappe.show_alert({ message: `${line.item_name || line.item_code} — ${__("count line selected")}`, indicator: "blue" });
    },

    priceGroupKey(value) {
        return flt(value || 0, 6).toFixed(6);
    },

    makeBatchPriceGroupState(line, context) {
        const state = new Map();
        const savedGroups = line.batch_price_groups || [];
        const savedSegments = line.batch_breakdown || [];
        const savedByKey = new Map(savedGroups.map(group => [this.priceGroupKey(group.customer_price), group]));
        const segmentByKey = new Map();
        savedSegments.forEach(segment => {
            const key = this.priceGroupKey(segment.customer_price);
            if (!segmentByKey.has(key)) segmentByKey.set(key, []);
            segmentByKey.get(key).push({ ...segment });
        });

        (context.price_groups || []).forEach(group => {
            const key = this.priceGroupKey(group.customer_price);
            const saved = savedByKey.get(key) || {};
            const segments = segmentByKey.get(key) || [];
            state.set(key, {
                key,
                customer_price: flt(group.customer_price || 0, 6),
                expected: 1,
                status: saved.status || (segments.length ? "Counted" : "Pending"),
                segments,
                source_count: cint(group.source_count || 0),
                price_integrity_error: cint(group.price_integrity_error || 0),
            });
        });

        savedGroups.forEach(group => {
            const key = this.priceGroupKey(group.customer_price);
            if (state.has(key)) return;
            const segments = segmentByKey.get(key) || [];
            state.set(key, {
                key,
                customer_price: flt(group.customer_price || 0, 6),
                expected: cint(group.expected || 0),
                status: group.status || (segments.length ? "Counted" : "Pending"),
                segments,
                source_count: 0,
                price_integrity_error: 0,
            });
        });

        segmentByKey.forEach((segments, key) => {
            if (state.has(key)) return;
            state.set(key, {
                key,
                customer_price: flt(segments[0]?.customer_price || 0, 6),
                expected: 0,
                status: "Counted",
                segments,
                source_count: 0,
                price_integrity_error: 0,
            });
        });
        return state;
    },

    batchDialogRowsHtml(line, context, groupState) {
        const pack = Math.max(1, flt(line.pack_size || context.pack_size || 1));
        const groups = [...groupState.values()].sort((a, b) => flt(a.customer_price) - flt(b.customer_price));
        const expected = groups.filter(group => cint(group.expected));
        const resolved = expected.filter(group => group.status !== "Pending").length;
        let html = `<div class="ic-batch-dialog" data-pack-size="${pack}">`;
        html += `<div class="alert alert-info" style="margin-bottom:10px"><strong>${__("Physical count by retail price")}</strong><br>${__("Choose each available price, then enter only the Batch / Expiry lots physically found. Existing system Batches stay hidden during Blind Count.")}</div>`;
        if (expected.length) {
            html += `<div style="margin-bottom:8px"><strong>${__("Resolved Price Groups")}: ${resolved} / ${expected.length}</strong></div>`;
        } else {
            html += `<div class="alert alert-warning">${__("No positive system price group is currently available. If physical stock exists, add the price found on the shelf.")}</div>`;
        }
        html += `<table class="table table-bordered table-condensed"><thead><tr><th>${__("Price")}</th><th>${__("Status")}</th><th>${__("Physical Count")}</th><th>${__("Actions")}</th></tr></thead><tbody>`;
        groups.forEach(group => {
            const total = (group.segments || []).reduce((sum, row) => sum + flt(row.qty || (flt(row.boxes) + flt(row.units) / pack)), 0);
            const summary = group.status === "Counted"
                ? `${this.formatBoxUnit(total, pack)}${group.segments.length ? ` • ${group.segments.length} ${__("lot(s)")}` : ""}`
                : group.status === "Confirmed Zero" ? __("Zero confirmed") : __("Not counted");
            const statusClass = group.status === "Counted" ? "green" : group.status === "Confirmed Zero" ? "orange" : "gray";
            const expectedLabel = cint(group.expected) ? "" : ` <span class="indicator-pill blue">${__("Unexpected price")}</span>`;
            const priceLabel = flt(group.customer_price) > 0 ? format_currency(flt(group.customer_price)) : __("Price unavailable");
            html += `<tr class="ic-price-group" data-price-key="${group.key}">
                <td><strong>${priceLabel}</strong>${expectedLabel}${group.price_integrity_error ? `<small style="display:block;color:var(--red-600)">${__("Price integrity review required")}</small>` : ""}</td>
                <td><span class="indicator-pill ${statusClass}">${frappe.utils.escape_html(group.status || "Pending")}</span></td>
                <td>${frappe.utils.escape_html(summary)}</td>
                <td><button type="button" class="btn btn-primary btn-xs ic-count-price">${__("Count")}</button>${cint(group.expected) ? ` <button type="button" class="btn btn-default btn-xs ic-zero-price">${__("Confirm Zero")}</button>` : ` <button type="button" class="btn btn-danger btn-xs ic-remove-price">×</button>`}</td>
            </tr>`;
        });
        html += `</tbody></table><button type="button" class="btn btn-default btn-sm" id="ic-add-physical-price">+ ${__("Different / New Price Found")}</button>`;
        html += `<small style="display:block;margin-top:8px">${__("Batch No is optional. If it is blank, the later reconciliation phase will request an AUTO Batch. Expiry is required for an AUTO/new physical Batch.")}</small></div>`;
        return html;
    },

    formatExpiryDMY(value) {
        const raw = String(value || "").trim();
        if (!raw) return "";

        let match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (match) {
            return `${match[3]}/${match[2]}/${match[1]}`;
        }

        match = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
        if (match) return raw;

        return raw;
    },

    normalizeExpiryISO(value) {
        const raw = String(value || "").trim();
        if (!raw) return "";

        let day;
        let month;
        let year;

        let match = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
        if (match) {
            day = Number(match[1]);
            month = Number(match[2]);
            year = Number(match[3]);
        } else {
            match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
            if (!match) return null;

            year = Number(match[1]);
            month = Number(match[2]);
            day = Number(match[3]);
        }

        const check = new Date(Date.UTC(year, month - 1, day));
        if (
            check.getUTCFullYear() !== year ||
            check.getUTCMonth() !== month - 1 ||
            check.getUTCDate() !== day
        ) {
            return null;
        }

        return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    },

    physicalLotRowHtml(row, pack, line) {
        const expiryDisplay = this.formatExpiryDMY(row.expiry_date || "");
        return `<tr class="ic-physical-lot-row">
            <td><input class="form-control input-sm ic-physical-batch" value="${frappe.utils.escape_html(row.batch_no || "")}" placeholder="${__("Optional / AUTO")}"></td>
            <td><input class="form-control input-sm ic-physical-expiry" type="text" inputmode="numeric" maxlength="10" placeholder="DD/MM/YYYY" value="${frappe.utils.escape_html(expiryDisplay)}"></td>
            <td><input class="form-control input-sm ic-physical-boxes" type="number" min="0" step="1" value="${row.boxes === undefined || row.boxes === null ? "" : cint(row.boxes)}"></td>
            <td><input class="form-control input-sm ic-physical-units" type="number" min="0" step="1" max="${Math.max(0, Math.ceil(pack) - 1)}" value="${row.units === undefined || row.units === null ? "" : cint(row.units)}" ${cint(line.box_only) ? "disabled" : ""}></td>
            <td><button type="button" class="btn btn-danger btn-xs ic-remove-physical-lot">×</button></td>
        </tr>`;
    },

    collectPhysicalLots(dialog, line, price) {
        const pack = Math.max(1, flt(line.pack_size || 1));
        const segments = [];
        let invalid = "";
        dialog.$wrapper.find(".ic-physical-lot-row").each((_, el) => {
            const boxesRaw = el.querySelector(".ic-physical-boxes")?.value ?? "";
            const unitsRaw = el.querySelector(".ic-physical-units")?.value ?? "";
            const boxes = boxesRaw === "" ? 0 : cint(boxesRaw);
            const units = unitsRaw === "" ? 0 : cint(unitsRaw);
            if (!boxes && !units) return;
            const batch = (el.querySelector(".ic-physical-batch")?.value || "").trim();
            const expiryRaw = (el.querySelector(".ic-physical-expiry")?.value || "").trim();
            const expiry = this.normalizeExpiryISO(expiryRaw);
            if (!expiryRaw) {
                invalid = __("Expiry is required for every physical Batch lot.");
            } else if (!expiry) {
                invalid = __("Enter Expiry in DD/MM/YYYY format, for example 01/05/2028.");
            }
            if (pack > 1 && units >= pack) invalid = __("Units must be less than Pack Size {0}.", [pack]);
            segments.push({
                batch_no: batch,
                expiry_date: expiry,
                observed_price: flt(price || 0, 6),
                customer_price: flt(price || 0, 6),
                boxes,
                units,
                qty: flt(boxes + units / pack, 6),
            });
        });
        return { segments, invalid };
    },

    openPriceGroupEditor(line, group, onSave, allowPriceEdit = false) {
        const pack = Math.max(1, flt(line.pack_size || 1));
        const rows = (group.segments || []).length ? group.segments : [{}];
        const dialog = new frappe.ui.Dialog({
            title: `${line.item_name || line.item_code} — ${__("Physical Price Group")}`,
            size: "large",
            fields: [
                { fieldname: "observed_price", fieldtype: "Currency", label: __("Observed Retail Price"), default: flt(group.customer_price || 0), read_only: allowPriceEdit ? 0 : 1, reqd: allowPriceEdit ? 1 : 0 },
                { fieldname: "lots_html", fieldtype: "HTML" },
            ],
            primary_action_label: __("Save Price Group"),
            primary_action: () => {
                const price = flt(dialog.get_value("observed_price") || 0, 6);
                if (allowPriceEdit && price < 0) { frappe.msgprint(__("Enter a valid observed price.")); return; }
                const collected = this.collectPhysicalLots(dialog, line, price);
                if (collected.invalid) { frappe.msgprint(collected.invalid); return; }
                if (!collected.segments.length) { frappe.msgprint(__("Enter at least one physical Box / Unit quantity.")); return; }
                const accepted = onSave({
                    ...group,
                    key: this.priceGroupKey(price),
                    customer_price: price,
                    status: "Counted",
                    segments: collected.segments,
                });
                if (accepted !== false) dialog.hide();
            },
        });
        const drawLots = () => {
            const body = rows.map(row => this.physicalLotRowHtml(row, pack, line)).join("");
            dialog.fields_dict.lots_html.$wrapper.html(`<table class="table table-bordered table-condensed"><thead><tr><th>${__("Batch No")}</th><th>${__("Expiry")}</th><th>${__("Boxes")}</th><th>${__("Units")}</th><th></th></tr></thead><tbody id="ic-physical-lots-body">${body}</tbody></table><button type="button" class="btn btn-default btn-xs" id="ic-add-physical-lot">+ ${__("Add another Batch / Expiry")}</button>`);
        };
        drawLots();
        dialog.$wrapper.on("click", "#ic-add-physical-lot", () => {
            dialog.$wrapper.find("#ic-physical-lots-body").append(this.physicalLotRowHtml({}, pack, line));
        });
        dialog.$wrapper.on("click", ".ic-remove-physical-lot", event => {
            const tableRows = dialog.$wrapper.find(".ic-physical-lot-row");
            if (tableRows.length <= 1) {
                event.currentTarget.closest("tr")?.querySelectorAll("input").forEach(input => input.value = "");
            } else {
                event.currentTarget.closest("tr")?.remove();
            }
        });

        dialog.$wrapper.on("input", ".ic-physical-expiry", event => {
            const input = event.currentTarget;
            const digits = String(input.value || "")
                .replace(/\D/g, "")
                .slice(0, 8);

            let formatted = digits;

            if (digits.length > 4) {
                formatted = `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
            } else if (digits.length > 2) {
                formatted = `${digits.slice(0, 2)}/${digits.slice(2)}`;
            }

            input.value = formatted;
        });

        dialog.show();
        setTimeout(() => dialog.$wrapper.find(".ic-physical-batch").first().focus(), 80);
    },

    async openBatchCountDialog(line, item = null) {
        const context = await this.call("get_count_stock_sources", {
            item_code: line.item_code,
            warehouse: line.warehouse || this.state.count.warehouse,
            blind_count: cint(this.state.count.blind_count),
        });
        const groupState = this.makeBatchPriceGroupState(line, context);
        const dialog = new frappe.ui.Dialog({
            title: `${line.item_name || line.item_code} — ${__("Price Group Physical Count")}`,
            size: "extra-large",
            fields: [{ fieldname: "batch_html", fieldtype: "HTML" }],
            primary_action_label: __("Save Item Count"),
            primary_action: async () => {
                const groups = [...groupState.values()];
                const pending = groups.filter(group => cint(group.expected) && group.status === "Pending");
                if (pending.length) {
                    frappe.msgprint(__("Resolve every available Price Group first: Count it or Confirm Zero."));
                    return;
                }
                if (!groups.length) {
                    frappe.msgprint(__("No system Price Group exists. Add the physical price found, or close this dialog and use Confirm Zero for the whole item."));
                    return;
                }
                const segments = groups.flatMap(group => group.status === "Counted" ? (group.segments || []) : []);
                const priceGroups = groups
                    .filter(group => group.status !== "Pending")
                    .map(group => ({
                        customer_price: flt(group.customer_price || 0, 6),
                        status: group.status,
                        expected: cint(group.expected),
                    }));
                const result = await this.call("save_batch_breakdown", {
                    name: this.state.count.name,
                    row_name: line.name,
                    segments: JSON.stringify(segments),
                    price_groups: JSON.stringify(priceGroups),
                });
                this.state.count = result.count;
                this.revealRow(line.name);
                this.renderCount();
                dialog.hide();
                frappe.show_alert({ message: `${line.item_name || line.item_code}: ${__("physical price-group count saved")}`, indicator: "green" });
                setTimeout(() => document.getElementById("ic-item-search")?.focus(), 50);
            },
        });

        const renderMain = () => {
            dialog.fields_dict.batch_html.$wrapper.html(this.batchDialogRowsHtml(line, context, groupState));
        };
        renderMain();

        dialog.$wrapper.on("click", ".ic-count-price", event => {
            const key = event.currentTarget.closest(".ic-price-group")?.dataset.priceKey;
            const group = groupState.get(key);
            if (!group) return;
            this.openPriceGroupEditor(line, group, updated => {
                groupState.delete(key);
                groupState.set(updated.key, updated);
                renderMain();
            }, false);
        });
        dialog.$wrapper.on("click", ".ic-zero-price", event => {
            const key = event.currentTarget.closest(".ic-price-group")?.dataset.priceKey;
            const group = groupState.get(key);
            if (!group) return;
            group.status = "Confirmed Zero";
            group.segments = [];
            renderMain();
        });
        dialog.$wrapper.on("click", ".ic-remove-price", event => {
            const key = event.currentTarget.closest(".ic-price-group")?.dataset.priceKey;
            if (!key) return;
            groupState.delete(key);
            renderMain();
        });
        dialog.$wrapper.on("click", "#ic-add-physical-price", () => {
            const draft = { key: "", customer_price: 0, expected: 0, status: "Pending", segments: [] };
            this.openPriceGroupEditor(line, draft, updated => {
                if (groupState.has(updated.key)) {
                    frappe.msgprint(__("This Price Group already exists. Use its Count button instead."));
                    return false;
                }
                updated.expected = 0;
                groupState.set(updated.key, updated);
                renderMain();
            }, true);
        });
        dialog.show();
    },

    renderSelectedItem() {
        const holder = document.getElementById("ic-selected-item");
        const scope = document.getElementById("ic-scope").value;
        const item = this.state.selectedItem;

        if (scope === "Branch") {
            holder.innerHTML = `<div class="ic-selection-card"><strong>${__("Branch Count")}</strong><small>${__("All expected stock items across physical warehouses in the selected branch will be snapshotted.")}</small></div>`;
            return;
        }

        if (scope === "Warehouse") {
            holder.innerHTML = `<div class="ic-selection-card"><strong>${__("Warehouse Count")}</strong><small>${__("All expected stock items in the selected warehouse will be snapshotted.")}</small></div>`;
            return;
        }

        if (this.isLocationScope(scope)) {
            holder.innerHTML = `<div class="ic-selection-card"><strong>${frappe.utils.escape_html(scope)} ${__("Count")}</strong><small>${__("Only expected items inside the selected storage location and its descendants are included.")}</small>${this.scopeOptionSelect(__("Storage Location"))}</div>`;
            holder.querySelector("#ic-scope-value")?.addEventListener("change", event => {
                this.state.selectedScopeValue = event.target.value;
            });
            return;
        }

        if (scope === "Item Group") {
            holder.innerHTML = `<div class="ic-selection-card">
                <strong>${__("Item Group Count")}</strong>
                <small>${__("Choose a Main Item Group first, then count all descendants or a specific nested group.")}</small>
                ${this.itemGroupMainSelect()}
                ${this.itemGroupScopeSelect()}
                ${this.itemGroupSummaryHtml()}
            </div>`;
            holder.querySelector("#ic-main-item-group")?.addEventListener("change", async event => {
                this.state.selectedMainItemGroup = event.target.value;
                this.state.selectedScopeValue = event.target.value;
                this.state.itemGroupSummary = null;
                await this.loadItemGroupHierarchy(this.state.selectedMainItemGroup, this.state.selectedScopeValue);
                this.renderSelectedItem();
            });
            holder.querySelector("#ic-item-group-scope")?.addEventListener("change", async event => {
                this.state.selectedScopeValue = event.target.value;
                this.state.itemGroupSummary = null;
                await this.refreshItemGroupSummary();
                this.renderSelectedItem();
            });
            return;
        }

        if (scope === "Batch") {
            if (!item) {
                holder.innerHTML = `<div class="ic-selection-empty">${__("Search and select the Item first, then choose the Batch.")}</div>`;
                return;
            }
            holder.innerHTML = `<div class="ic-selection-card"><strong>${frappe.utils.escape_html(item.item_name || item.item_code)}</strong><small>${frappe.utils.escape_html(item.item_code)} • ${__("Explicit Batch Count")}</small>${this.scopeOptionSelect(__("Batch"))}</div>`;
            holder.querySelector("#ic-scope-value")?.addEventListener("change", event => {
                this.state.selectedScopeValue = event.target.value;
            });
            return;
        }

        if (!item) {
            holder.innerHTML = `<div class="ic-selection-empty">${__("Search and select an item")}</div>`;
            return;
        }
        holder.innerHTML = `<div class="ic-selection-card"><strong>${frappe.utils.escape_html(item.item_name || item.item_code)}</strong><small>${frappe.utils.escape_html(item.item_code)}${item.has_batch_no ? ` • ${__("Batch controlled")}` : ""}</small></div>`;
    },

    clearSearch(clearInput = true) {
        this.state.searchRows = [];
        this.state.searchIndex = -1;
        document.getElementById("ic-search-results").innerHTML = "";
        if (clearInput) document.getElementById("ic-item-search").value = "";
    },

    async resetForNewCount() {
        const count = this.state.count;
        if (count && !["Posted", "Cancelled"].includes(count.status)) {
            frappe.msgprint(__("Finish or cancel the current Inventory Count before starting a new one."));
            return;
        }

        this.state.count = null;
        this.state.selectedItem = null;
        this.state.scopeOptions = [];
        this.state.selectedScopeValue = "";
        this.state.itemGroupHierarchy = null;
        this.state.selectedMainItemGroup = "";
        this.state.itemGroupSummary = null;
        this.state.searchRows = [];
        this.state.searchIndex = -1;
        clearTimeout(this.state.searchTimer);
        this.state.searchTimer = null;

        const url = new URL(window.location.href);
        url.searchParams.delete("count");
        window.history.replaceState({}, document.title, `${url.pathname}${url.search}`);

        ["ic-branch", "ic-warehouse", "ic-scope", "ic-blind"].forEach(id => {
            const field = document.getElementById(id);
            if (field) field.disabled = false;
        });

        document.getElementById("ic-new-count")?.classList.add("is-hidden");
        document.getElementById("ic-open-doctype")?.classList.add("is-hidden");
        document.getElementById("ic-create-count")?.classList.remove("is-hidden");

        const branch = document.getElementById("ic-branch")?.value || "";
        this.state.context = await this.call("get_context", { branch });
        this.applyContext({ preserveBranch: true });
        this.clearSearch();
        await this.onScopeChange();
        this.renderCount();
        setTimeout(() => document.getElementById("ic-item-search")?.focus(), 50);
    },

    async createDraft() {
        if (this.state.count && !["Posted", "Cancelled"].includes(this.state.count.status)) {
            frappe.msgprint(__("Finish or cancel the current Inventory Count before creating another from this workstation."));
            return;
        }

        const scope = document.getElementById("ic-scope").value;
        const warehouse = document.getElementById("ic-warehouse").value;

        if (this.scopeNeedsWarehouse(scope) && !warehouse) {
            frappe.msgprint(__("Select a Warehouse first."));
            return;
        }
        if (scope === "Item" && !this.state.selectedItem) {
            frappe.msgprint(__("Select an item first."));
            return;
        }
        if (this.isLocationScope(scope) && !this.state.selectedScopeValue) {
            frappe.msgprint(__("Select the Storage Location for this count."));
            return;
        }
        if (scope === "Item Group" && (!this.state.selectedMainItemGroup || !this.state.selectedScopeValue)) {
            frappe.msgprint(__("Select a Main Item Group and Count Scope first."));
            return;
        }
        if (scope === "Batch" && (!this.state.selectedItem || !this.state.selectedScopeValue)) {
            frappe.msgprint(__("Select the Item and Batch first."));
            return;
        }

        const args = {
            company: document.getElementById("ic-company").value,
            branch: document.getElementById("ic-branch").value,
            warehouse: scope === "Branch" ? "" : warehouse,
            scope_type: scope,
            item_code: ["Item", "Batch"].includes(scope) ? (this.state.selectedItem?.item_code || "") : "",
            scope_location: this.isLocationScope(scope) ? this.state.selectedScopeValue : "",
            item_group: scope === "Item Group" ? this.state.selectedScopeValue : "",
            batch_no: scope === "Batch" ? this.state.selectedScopeValue : "",
            blind_count: document.getElementById("ic-blind").checked ? 1 : 0,
        };
        const result = await this.call("create_count", args);
        await this.loadCount(result.name, true);
        frappe.show_alert({ message: `${__("Draft created")}: ${result.name}`, indicator: "green" });
    },

    async loadCount(name, updateUrl = false) {
        this.state.count = await this.call("get_count", { name });
        if (updateUrl) {
            const url = new URL(window.location.href);
            url.searchParams.set("count", name);
            window.history.replaceState({}, document.title, `${url.pathname}${url.search}`);
        }

        const count = this.state.count;
        const allScopes = ["Branch", "Warehouse", "Zone", "Aisle", "Shelf", "Bin", "Item", "Item Group", "Batch"];
        document.getElementById("ic-company").value = count.company || "";
        document.getElementById("ic-branch").value = count.branch || "";
        document.getElementById("ic-warehouse").value = count.warehouse || "";
        document.getElementById("ic-scope").value = allScopes.includes(count.scope_type) ? count.scope_type : "Item";
        document.getElementById("ic-blind").checked = cint(count.blind_count) === 1;

        if (["Item", "Batch"].includes(count.scope_type) && count.item_code) {
            this.state.selectedItem = {
                item_code: count.item_code,
                item_name: (count.items || []).find(row => row.item_code === count.item_code)?.item_name || count.item_code,
                has_batch_no: cint((count.items || []).find(row => row.item_code === count.item_code)?.has_batch_no || 0),
            };
        } else {
            this.state.selectedItem = null;
        }

        this.state.selectedScopeValue =
            count.scope_location || count.item_group || count.batch_no || "";
        if (count.scope_type === "Item Group") {
            await this.loadItemGroupHierarchy();
            const target = count.item_group || "";
            const mains = this.state.itemGroupHierarchy?.main_groups || [];
            const descendants = this.state.itemGroupHierarchy?.descendants || {};
            let owner = mains.find(row => row.value === target)?.value || "";
            if (!owner) {
                for (const main of mains) {
                    if ((descendants[main.value] || []).some(row => row.value === target)) { owner = main.value; break; }
                }
            }
            await this.loadItemGroupHierarchy(owner || this.state.selectedMainItemGroup, target);
        } else {
            await this.loadScopeOptions(this.state.selectedScopeValue);
        }

        ["ic-branch", "ic-warehouse", "ic-scope", "ic-blind"].forEach(id => document.getElementById(id).disabled = true);
        document.getElementById("ic-create-count").classList.add("is-hidden");
        document.getElementById("ic-open-doctype").classList.remove("is-hidden");
        const terminal = ["Posted", "Cancelled"].includes(count.status);
        document.getElementById("ic-new-count").classList.toggle("is-hidden", !terminal);
        this.renderSelectedItem();
        this.renderCount();
    },

    renderCount() {
        const count = this.state.count;
        const name = document.getElementById("ic-count-name");
        const status = document.getElementById("ic-count-status");
        if (!count) {
            ["ic-branch", "ic-warehouse", "ic-scope", "ic-blind"].forEach(id => {
                const field = document.getElementById(id);
                if (field) field.disabled = false;
            });
            document.getElementById("ic-new-count")?.classList.add("is-hidden");
            document.getElementById("ic-open-doctype")?.classList.add("is-hidden");
            document.getElementById("ic-create-count")?.classList.remove("is-hidden");
            this.updateScopeControls();
            name.textContent = __("New Inventory Count");
            status.textContent = __("No active count");
            status.className = "ic-badge";
            document.getElementById("ic-count-meta").textContent = "";
            this.renderActions();
            this.renderSummary();
            this.renderTable();
            this.renderSelectedItem();
            return;
        }
        name.textContent = count.name;
        const scopeDetail = count.scope_location || count.item_group || count.batch_no || count.item_code || "";
        const warehousePart = count.warehouse ? ` • ${count.warehouse}` : "";
        document.getElementById("ic-count-meta").textContent = `${count.scope_type}${warehousePart}${scopeDetail ? ` • ${scopeDetail}` : ""}`;
        status.textContent = count.status;
        status.className = `ic-badge ${count.status === "Posted" ? "ic-green" : count.status === "Cancelled" ? "ic-red" : "ic-orange"}`;
        this.renderActions();
        this.renderSummary();
        this.renderTable();
    },

    renderActions() {
        const holder = document.getElementById("ic-actions");
        const count = this.state.count;
        if (!count) { holder.innerHTML = ""; return; }
        const rec = count.batch_reconciliation || {};
        const reconciliationRequired = cint(rec.required);
        const reconciliationPlanned = cint(rec.planned);
        const executionReady = cint(rec.execution_ready);
        const buttons = [];
        if (count.status === "Draft") buttons.push(["start_count", __("Start Count"), "btn-primary"]);
        if (count.status === "Counting") {
            buttons.push(["complete_count", __("Complete Count"), "btn-primary"]);
            buttons.push(["load_expected", __("Load Expected Items Now"), "btn-default"]);
            buttons.push(["review_uncounted", __("Review Uncounted Items"), "btn-default"]);
        }
        if (["Count Completed", "Under Review", "Approved"].includes(count.status) && reconciliationRequired) {
            buttons.push(["review_batch_reconciliation", reconciliationPlanned ? __("Review Batch Plan") : __("Review Batch Reconciliation"), "btn-warning"]);
        }
        if (count.status === "Count Completed") buttons.push(["begin_review", __("Begin Review"), "btn-primary"]);
        if (count.status === "Under Review" && (!reconciliationRequired || reconciliationPlanned)) {
            buttons.push(["approve_count", __("Approve"), "btn-primary"]);
        }
        if (count.status === "Approved" && (!reconciliationRequired || executionReady)) {
            buttons.push(["post_count", __("Post Count"), "btn-primary"]);
        }
        if (count.status === "Approved" && reconciliationRequired && reconciliationPlanned && !executionReady) {
            buttons.push(["execution_pending", __("Confirm R1.10 R2 Execution Plan"), "btn-default"]);
        }
        holder.innerHTML = buttons.map(([action, label, cls]) => `<button class="btn ${cls} btn-sm" data-action="${action}" ${action === "execution_pending" ? "disabled" : ""}>${label}</button>`).join("");
        holder.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => {
            const action = button.dataset.action;
            if (action === "load_expected") {
                this.state.showAllExpected = true;
                this.state.showUncountedOnly = false;
                this.renderTable();
                return;
            }
            if (action === "review_uncounted") {
                this.state.showAllExpected = false;
                this.state.showUncountedOnly = true;
                this.renderTable();
                return;
            }
            if (action === "review_batch_reconciliation") {
                this.openBatchReconciliationDialog();
                return;
            }
            if (action === "execution_pending") return;
            this.runAction(action);
        }));
    },

    async runAction(action) {
        const name = this.state.count?.name;
        if (!name) return;
        if (action === "post_count") {
            frappe.confirm(__("Execute the armed Batch/Expiry/Price target matrix and post the approved Inventory Count now? This may create AUTO Batches, correct reviewed Batch expiry metadata, submit Stock Reconciliation, and segregate expired stock."), () => this.executeAction(action));
            return;
        }
        await this.executeAction(action);
    },

    async executeAction(action) {
        try {
            const result = await this.call("run_action", { name: this.state.count.name, action });
            this.state.count = result.count;
            const actionResult = result.result || {};
            if (action === "start_count") {
                this.state.showAllExpected = ["Item", "Batch"].includes(this.state.count.scope_type);
                this.state.showUncountedOnly = false;
                this.state.revealedRows = [];
            }
            this.renderCount();
            if (action === "complete_count" && actionResult.completed === false) {
                const names = (actionResult.missing || []).map(row => row.item_name || row.item_code).slice(0, 8).join(", ");
                frappe.msgprint({
                    title: __("Missing Expected Items Review"),
                    indicator: "orange",
                    message: `${actionResult.missing_count} ${__("item(s) still need verification.")}<br>${frappe.utils.escape_html(names)}`
                });
            } else {
                frappe.show_alert({ message: `${__("Inventory Count")}: ${this.state.count.status}`, indicator: "green" });
            }
        } catch (error) {
            console.error(error);
        }
    },

    renderSummary() {
        const holder = document.getElementById("ic-summary");
        const banner = document.getElementById("ic-missing-banner");
        const count = this.state.count;
        if (!count) { holder.innerHTML = ""; banner.classList.add("is-hidden"); return; }
        const rows = count.items || [];
        const counted = rows.filter(row => cint(row.count_entered)).length;
        const pending = rows.length - counted;
        const zero = rows.filter(row => row.resolution_status === "Confirmed Zero").length;
        const rec = count.batch_reconciliation || {};
        const reconciliationExecuted = count.status === "Posted" && cint(rec.executed);
        const executionSummary = rec.execution_summary || {};
        const createdBatches = executionSummary.created_batches || [];
        const metadataChanges = executionSummary.metadata_changes || [];
        const expiryCorrections = metadataChanges.filter(change => change && change.field === "expiry_date");
        holder.innerHTML = `
            <div class="ic-summary-card"><span>${__("Expected Lines")}</span><strong>${rows.length}</strong></div>
            <div class="ic-summary-card"><span>${__("Counted")}</span><strong>${counted}</strong></div>
            <div class="ic-summary-card"><span>${__("Pending")}</span><strong>${pending}</strong></div>
            <div class="ic-summary-card"><span>${__("Confirmed Zero")}</span><strong>${zero}</strong></div>
            ${count.status !== "Counting" ? `<div class="ic-summary-card"><span>${__("Net Variance")}</span><strong>${flt(count.net_variance_qty || 0, 3)}</strong></div>` : ""}
            ${reconciliationExecuted && count.stock_reconciliation ? `<div class="ic-summary-card"><span>${__("Stock Reconciliation")}</span><strong>${frappe.utils.escape_html(count.stock_reconciliation)}</strong></div>` : ""}
            ${reconciliationExecuted && createdBatches.length ? `<div class="ic-summary-card"><span>${__("AUTO Batch Created")}</span><strong>${createdBatches.length}</strong></div>` : ""}
            ${reconciliationExecuted && expiryCorrections.length ? `<div class="ic-summary-card"><span>${__("Expiry Corrected")}</span><strong>${expiryCorrections.length}</strong></div>` : ""}
            ${!reconciliationExecuted && cint(rec.required) ? `<div class="ic-summary-card"><span>${__("AUTO Batch")}</span><strong>${cint(rec.auto_batch_requests)}</strong></div>` : ""}
            ${!reconciliationExecuted && cint(rec.required) ? `<div class="ic-summary-card"><span>${__("Expiry Mismatch")}</span><strong>${cint(rec.expiry_mismatches)}</strong></div>` : ""}
            ${!reconciliationExecuted && cint(rec.required) && cint(rec.price_mismatches) ? `<div class="ic-summary-card"><span>${__("Price Mismatch")}</span><strong>${cint(rec.price_mismatches)}</strong></div>` : ""}
        `;
        banner.style.background = "";
        banner.style.borderColor = "";
        if (count.status === "Counting" && pending > 0) {
            banner.classList.remove("is-hidden");
            banner.innerHTML = `<strong>${pending} ${__("expected item(s) not counted yet")}</strong><span>${__("Scan/Search to count progressively, use Load Expected Items Now for a small scope, or Review Uncounted Items when you finish. Blank never means zero.")}</span>`;
        } else if (reconciliationExecuted) {
            banner.classList.remove("is-hidden");
            banner.style.background = "var(--green-50, #ecfdf3)";
            banner.style.borderColor = "var(--green-300, #86efac)";
            const details = [];
            if (count.stock_reconciliation) details.push(`${__("Stock Reconciliation")}: ${frappe.utils.escape_html(count.stock_reconciliation)}`);
            if (createdBatches.length) details.push(`${__("AUTO Batch")}: ${createdBatches.map(batch => frappe.utils.escape_html(batch)).join(", ")}`);
            if (expiryCorrections.length) details.push(`${__("Expiry correction(s)")}: ${expiryCorrections.length}`);
            if ((executionSummary.expired_targets || []).length) details.push(`${__("Expired stock segregation")}: ${(executionSummary.expired_targets || []).length}`);
            banner.innerHTML = `<strong>${__("Batch Reconciliation Executed")}</strong><span>${details.join(" • ") || __("Controlled Batch target matrix posted successfully.")}</span>`;
        } else if (count.status !== "Counting" && cint(rec.required)) {
            banner.classList.remove("is-hidden");
            const state = cint(rec.planned) ? __("Reconciliation plan saved") : __("Reviewer plan required");
            const execution = cint(rec.planned) && !cint(rec.execution_ready) ? ` • ${__("Execution confirmation required: review the current Batch snapshot and save the R1.10 R2 plan")}` : cint(rec.execution_ready) ? ` • ${__("R1.10 R2 execution armed")}` : "";
            banner.innerHTML = `<strong>${__("Batch / Expiry / Price Composition Review Required")}</strong><span>${state} • ${cint(rec.composition_differences)} ${__("composition difference(s)")}${execution}</span>`;
        } else {
            banner.classList.add("is-hidden");
        }
    },

    renderTable() {
        const head = document.getElementById("ic-table-head");
        const body = document.getElementById("ic-table-body");
        const count = this.state.count;
        if (!count) {
            head.innerHTML = `<tr><th>${__("Item")}</th><th>${__("Actual Qty")}</th><th>${__("Status")}</th></tr>`;
            body.innerHTML = `<tr><td colspan="3" class="ic-empty">${__("Create a Draft to begin.")}</td></tr>`;
            return;
        }
        const review = count.status !== "Counting";
        head.innerHTML = `<tr>
            <th>${__("Item")}</th><th>${__("Location")}</th><th>${__("Entry")}</th><th>${__("Actual")}</th>
            ${review ? `<th>${__("Expected")}</th><th>${__("Variance")}</th>` : ""}
            <th>${__("Resolution")}</th>${review ? `<th>${__("Reason")}</th>` : ""}<th>${__("Actions")}</th>
        </tr>`;
        const allRows = count.items || [];
        let rows = allRows;
        if (count.status === "Counting") {
            if (this.state.showAllExpected) {
                rows = allRows;
            } else if (this.state.showUncountedOnly) {
                rows = allRows.filter(row => !cint(row.count_entered));
            } else {
                rows = allRows.filter(row => cint(row.count_entered) || cint(row.unexpected_item) || this.state.revealedRows.includes(row.name));
            }
        }
        if (!rows.length) {
            const message = count.status === "Draft"
                ? __("Start Count to create the snapshot.")
                : count.status === "Counting"
                    ? __("Snapshot is ready and hidden. Scan/Search an item to count, or use Load Expected Items Now.")
                    : __("No count lines");
            body.innerHTML = `<tr><td colspan="${review ? 9 : 6}" class="ic-empty">${message}</td></tr>`;
            return;
        }
        body.innerHTML = rows.map(row => this.rowHtml(row, review)).join("");
        this.bindRows();
    },

    rowHtml(row, review) {
        const editable = this.state.count.status === "Counting";
        const canReview = ["Count Completed", "Under Review"].includes(this.state.count.status);
        const mode = "Box / Unit";
        const actual = row.actual_qty === null || row.actual_qty === undefined ? null : flt(row.actual_qty, 6);
        const pack = Math.max(1, flt(row.pack_size || 1));
        const unitMax = Math.max(0, Math.ceil(pack) - 1);
        const breakdownCount = (row.batch_breakdown || []).length;
        const recRow = (this.state.count.batch_reconciliation?.rows || []).find(item => item.row_name === row.name);
        const recIssues = recRow && this.state.count.status === "Posted" && cint(recRow.executed)
            ? `<small style="display:block;margin-top:4px;color:var(--green-700,#15803d)">${__("Batch reconciliation executed")}${this.state.count.stock_reconciliation ? ` • ${__("Stock Reconciliation")}: ${frappe.utils.escape_html(this.state.count.stock_reconciliation)}` : ""}</small>`
            : recRow && cint(recRow.required)
                ? `<small style="display:block;margin-top:4px;color:var(--orange-600,#d97706)">${cint(recRow.planned) ? __("Batch reconciliation planned") : __("Batch reconciliation required")}${cint(recRow.expiry_mismatches) ? ` • ${cint(recRow.expiry_mismatches)} ${__("expiry mismatch")}` : ""}${cint(recRow.auto_batch_requests) ? ` • ${cint(recRow.auto_batch_requests)} ${__("AUTO batch")}` : ""}</small>`
                : "";
        const actualInput = cint(row.has_batch_no)
            ? `<div><button type="button" class="btn btn-default btn-xs ic-batch-count" ${editable ? "" : "disabled"}>${__("Count by Price")}</button><small style="display:block;margin-top:5px">${actual === null ? __("Not counted") : this.formatBoxUnit(actual, pack)}${breakdownCount ? ` • ${breakdownCount} ${__("Physical lot(s)")}` : ""}</small></div>`
            : `<div class="ic-box-unit"><input class="form-control ic-boxes" type="number" min="0" step="1" value="${cint(row.actual_boxes)}" ${editable ? "" : "disabled"}><span>Box</span><input class="form-control ic-units" type="number" min="0" step="1" max="${unitMax}" value="${cint(row.actual_loose_units)}" ${editable && !cint(row.box_only) ? "" : "disabled"}><span>Unit</span></div>`;
        const reasonOptions = ["", "Receiving Error", "Sale Not Posted", "Return Not Posted", "Wrong Location", "Damage", "Expired", "UOM Error", "Batch Allocation Difference", "Theft / Loss", "Data Entry Error", "Unexpected Stock", "Other"];
        const wrongLocationSelected = (row.reason_code || "") === "Wrong Location";
        const shortageMax = Math.max(0, Math.abs(flt(row.variance_qty || 0, 6)));
        const foundQtyValue = Math.max(0, flt(row.found_elsewhere_qty || 0, 6));
        let foundBoxes = Math.floor(foundQtyValue + 0.000000001);
        let foundUnits = Math.round((foundQtyValue - foundBoxes) * pack);
        if (foundUnits >= pack && pack > 0) {
            foundBoxes += Math.floor(foundUnits / pack);
            foundUnits = foundUnits % pack;
        }
        const reason = canReview ? `<div class="ic-review-fields">
            <select class="form-control ic-reason">${reasonOptions.map(v => `<option value="${frappe.utils.escape_html(v)}" ${v === (row.reason_code || "") ? "selected" : ""}>${frappe.utils.escape_html(v || __("Select reason"))}</option>`).join("")}</select>
            <input class="form-control ic-reason-note" placeholder="${__("Note")}" value="${frappe.utils.escape_html(row.reason_note || "")}">
            <div class="ic-wrong-location-fields" style="display:${wrongLocationSelected ? "grid" : "none"};grid-template-columns:minmax(180px,1fr) minmax(150px,.55fr);gap:6px;margin-top:6px">
                <select class="form-control ic-found-location" data-loaded="0"><option value="${frappe.utils.escape_html(row.found_location || "")}">${frappe.utils.escape_html(row.found_location || __("Select found location"))}</option></select>
                <div class="ic-box-unit ic-found-box-unit">
                    <input class="form-control ic-found-boxes" type="number" min="0" step="1" max="${Math.floor(shortageMax + 0.000000001)}" value="${foundBoxes}">
                    <span>Box</span>
                    <input class="form-control ic-found-units" type="number" min="0" step="1" max="${unitMax}" value="${foundUnits}" ${cint(row.box_only) || pack <= 1 ? "disabled" : ""}>
                    <span>Unit</span>
                </div>
                <small style="grid-column:1/-1;color:var(--text-muted)">${__("Enter Boxes / Units; Found Elsewhere Qty is calculated automatically. Wrong Location moves only the quantity physically found elsewhere; any remaining shortage becomes unallocated.")}</small>
            </div>
            ${row.has_batch_no && flt(row.variance_qty || 0) > 0 ? `<input class="form-control ic-posting-batch" placeholder="${__("Physical Batch for excess")}" value="${frappe.utils.escape_html(row.posting_batch_no || "")}">` : ""}
        </div>` : (row.reason_code ? frappe.utils.escape_html(row.reason_code) : "");
        return `<tr data-row-name="${frappe.utils.escape_html(row.name)}">
            <td><strong>${frappe.utils.escape_html(row.item_name || row.item_code)}</strong><small>${frappe.utils.escape_html(row.item_code)}${row.batch_no ? ` • Batch ${frappe.utils.escape_html(row.batch_no)}` : ""}</small></td>
            <td>${frappe.utils.escape_html(row.location || "—")}</td>
            <td>${cint(row.has_batch_no) ? __("Batch / Price + Box / Unit") : __("Box / Unit")}</td>
            <td>${actualInput}<small>${frappe.utils.escape_html(row.stock_uom || "")}${row.pack_size ? ` • Pack ${flt(row.pack_size, 3)}` : ""}</small>${recIssues}</td>
            ${review ? `<td>${flt(row.expected_qty_at_count || row.snapshot_qty || 0, 3)}</td><td class="${flt(row.variance_qty || 0) ? "ic-variance" : ""}">${flt(row.variance_qty || 0, 3)}</td>` : ""}
            <td><span class="ic-resolution">${frappe.utils.escape_html(row.resolution_status || "Pending")}</span></td>
            ${review ? `<td>${reason}</td>` : ""}
            <td class="ic-row-actions">${editable ? `<button class="btn btn-primary btn-xs ic-save-row">${__("Save")}</button><button class="btn btn-default btn-xs ic-zero-row">${__("Confirm Zero")}</button>` : canReview ? `<button class="btn btn-primary btn-xs ic-save-review">${__("Save Review")}</button><button class="btn btn-default btn-xs ic-recount">${__("Recount")}</button>` : ""}</td>
        </tr>`;
    },

    bindRows() {
        document.querySelectorAll("#ic-table-body tr[data-row-name]").forEach(tr => {
            tr.querySelector(".ic-batch-count")?.addEventListener("click", () => {
                const row = this.state.count.items.find(item => item.name === tr.dataset.rowName);
                this.openBatchCountDialog(row);
            });
            tr.querySelector(".ic-save-row")?.addEventListener("click", () => this.saveRow(tr));
            tr.querySelector(".ic-zero-row")?.addEventListener("click", () => this.confirmZero(tr.dataset.rowName));
            tr.querySelector(".ic-save-review")?.addEventListener("click", () => this.saveReview(tr));
            tr.querySelector(".ic-reason")?.addEventListener("change", () => this.syncWrongLocationFields(tr));
            if (tr.querySelector(".ic-reason")?.value === "Wrong Location") this.syncWrongLocationFields(tr);
            tr.querySelector(".ic-recount")?.addEventListener("click", () => this.requestRecount(tr.dataset.rowName));
        });
    },

    async saveRow(tr) {
        const row = this.state.count.items.find(item => item.name === tr.dataset.rowName);
        if (cint(row.has_batch_no)) {
            await this.openBatchCountDialog(row);
            return;
        }
        const args = {
            name: this.state.count.name,
            row_name: row.name,
            entry_mode: "Box / Unit",
            actual_boxes: tr.querySelector(".ic-boxes")?.value || 0,
            actual_loose_units: tr.querySelector(".ic-units")?.value || 0,
        };
        await this.call("save_line", args);
        await this.loadCount(this.state.count.name);
        this.revealRow(row.name);
        frappe.show_alert({ message: `${row.item_name || row.item_code}: ${__("Count saved")}`, indicator: "green" });
        setTimeout(() => document.getElementById("ic-item-search")?.focus(), 50);
    },

    async confirmZero(rowName) {
        frappe.confirm(__("You physically verified this expected item is not found. Confirm actual quantity = 0?"), async () => {
            await this.call("confirm_zero", { name: this.state.count.name, row_name: rowName });
            await this.loadCount(this.state.count.name);
        });
    },

    async openBatchReconciliationDialog() {
        const count = this.state.count;
        if (!count?.name) return;
        const preview = await this.call("get_batch_reconciliation_preview", { name: count.name });
        const rows = preview?.rows || [];
        if (!rows.length) {
            frappe.msgprint(__("No Batch/Expiry/Price composition differences require reconciliation."));
            return;
        }
        const esc = value => frappe.utils.escape_html(String(value ?? ""));
        const money = value => format_currency(flt(value || 0));
        const body = rows.map((row, rowIndex) => {
            const physical = (row.physical_segments || []).map(segment => {
                const options = (segment.allowed_actions || [segment.suggested_action]).map(action => `<option value="${esc(action)}" ${action === (segment.selected_action || segment.suggested_action) ? "selected" : ""}>${esc(action)}</option>`).join("");
                const flags = [
                    cint(segment.auto_batch_requested) ? __("AUTO Batch requested") : "",
                    cint(segment.expiry_mismatch) ? __("Expiry mismatch") : "",
                    cint(segment.price_mismatch) ? __("Price mismatch") : "",
                    cint(segment.expired) ? __("Expired physical stock") : "",
                ].filter(Boolean).join(" • ");
                return `<tr>
                    <td>${money(segment.customer_price)}</td>
                    <td>${esc(segment.batch_no || __("AUTO on Post"))}</td>
                    <td>${esc(segment.expiry_date || "—")}</td>
                    <td>${esc(segment.boxes)} + ${esc(segment.units)}</td>
                    <td>${esc(flags || __("Composition review"))}</td>
                    <td><select class="form-control input-sm ic-rec-action" data-row-index="${rowIndex}" data-segment-index="${segment.segment_index}">${options}</select></td>
                </tr>`;
            }).join("");
            const system = (row.system_sources || []).map(source => `<tr><td>${esc(source.batch_no)}</td><td>${esc(source.expiry_date || "—")}</td><td>${money(source.customer_price)}</td><td>${flt(source.available_qty, 3)}</td><td>${esc(source.status || "")}</td></tr>`).join("");
            const targets = (row.execution_targets || []).map(target => `<tr><td>${esc(target.batch_no)}</td><td>${flt(target.current_qty || 0, 3)}</td><td><strong>${flt(target.target_qty || 0, 3)}</strong></td><td>${flt((target.target_qty || 0) - (target.current_qty || 0), 3)}</td><td>${esc(target.kind || "")}</td></tr>`).join("");
            return `<section class="ic-rec-section" data-row-name="${esc(row.row_name)}" data-fingerprint="${esc(row.breakdown_fingerprint)}" style="margin-bottom:18px">
                <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:8px">
                    <div><strong>${esc(row.item_name || row.item_code)}</strong><div class="text-muted">${esc(row.item_code)} • ${esc(row.warehouse)}</div></div>
                    <div><strong>${__("Physical")}: ${flt(row.actual_qty,3)}</strong> • ${__("Expected")}: ${flt(row.expected_qty,3)} • ${__("Variance")}: ${flt(row.variance_qty,3)}</div>
                </div>
                <div class="alert alert-warning" style="padding:8px 10px;margin-bottom:8px">${cint(row.auto_batch_requests)} ${__("AUTO Batch request(s)")} • ${cint(row.expiry_mismatches)} ${__("expiry mismatch(es)")} • ${cint(row.price_mismatches)} ${__("price mismatch(es)")} • ${cint(row.composition_differences)} ${__("composition difference(s)")}</div>
                <div style="font-weight:600;margin:6px 0">${__("Physical Observation → Planned Action")}</div>
                <div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr><th>${__("Price")}</th><th>${__("Physical Batch")}</th><th>${__("Expiry")}</th><th>${__("Box + Unit")}</th><th>${__("Issue")}</th><th>${__("Action")}</th></tr></thead><tbody>${physical}</tbody></table></div>
                <div style="font-weight:600;margin:10px 0 6px">${__("Final Batch Target Matrix (preview)")}</div>
                <div class="alert ${cint(row.movement_safe) ? "alert-success" : "alert-danger"}" style="padding:7px 10px;margin-bottom:6px">${cint(row.movement_safe) ? __("Movement safety check passed: current Warehouse total still matches the quantity captured when this Item was counted.") : __("Stock moved after this Item was counted. Execution cannot be armed; recount is required.")}</div>
                <div class="table-responsive"><table class="table table-bordered table-sm"><thead><tr><th>${__("Target Batch")}</th><th>${__("Current Qty")}</th><th>${__("Final Target Qty")}</th><th>${__("Delta")}</th><th>${__("Action")}</th></tr></thead><tbody>${targets}</tbody></table></div>
                <details style="margin-top:8px"><summary>${__("System Batch snapshot used for comparison")} (${(row.system_sources || []).length})</summary><div class="table-responsive" style="margin-top:6px"><table class="table table-bordered table-sm"><thead><tr><th>${__("Batch")}</th><th>${__("Expiry")}</th><th>${__("Price")}</th><th>${__("Qty")}</th><th>${__("Status")}</th></tr></thead><tbody>${system || `<tr><td colspan="5">${__("No positive system Batch stock")}</td></tr>`}</tbody></table></div></details>
            </section>`;
        }).join("");

        const dialog = new frappe.ui.Dialog({
            title: __("Batch / Expiry / Price Reconciliation"),
            size: "extra-large",
            fields: [{ fieldname: "body", fieldtype: "HTML" }],
            primary_action_label: __("Arm R1.10 R2 Execution Plan"),
            primary_action: async () => {
                const plans = rows.map((row, rowIndex) => ({
                    row_name: row.row_name,
                    breakdown_fingerprint: row.breakdown_fingerprint,
                    decisions: (row.physical_segments || []).map(segment => ({
                        segment_index: segment.segment_index,
                        action: dialog.$wrapper.find(`.ic-rec-action[data-row-index="${rowIndex}"][data-segment-index="${segment.segment_index}"]`).val() || segment.suggested_action,
                    })),
                }));
                const result = await this.call("save_batch_reconciliation_plan", { name: count.name, plans: JSON.stringify(plans) });
                this.state.count = result.count;
                dialog.hide();
                this.renderCount();
                frappe.show_alert({ message: __("R1.10 R2 execution plan armed"), indicator: "green" });
            },
        });
        dialog.fields_dict.body.$wrapper.html(`<div class="alert alert-info" style="padding:9px 12px"><strong>${__("R1.10 R2 controlled execution")}</strong><br>${__("Review the physical observations, actions, current System Batch snapshot, and Final Batch Target Matrix. Saving arms the plan but still does not change stock. Posting performs all changes atomically. If Batch stock changes after arming, posting is blocked and a recount is required.")}</div>${body}`);
        dialog.show();
    },

    async syncWrongLocationFields(tr) {
        const row = this.state.count.items.find(item => item.name === tr.dataset.rowName);
        const reason = tr.querySelector(".ic-reason")?.value || "";
        const wrapper = tr.querySelector(".ic-wrong-location-fields");
        const select = tr.querySelector(".ic-found-location");
        if (!wrapper || !row) return;
        const active = reason === "Wrong Location";
        wrapper.style.display = active ? "grid" : "none";
        if (!active || !select || select.dataset.loaded === "1") return;
        select.disabled = true;
        try {
            const locations = await frappe.db.get_list("Pharmacy Storage Location", {
                fields: ["name", "location_code", "location_name"],
                filters: { warehouse: row.warehouse, disabled: 0 },
                order_by: "location_code asc, name asc",
                limit: 2000,
            });
            const current = row.found_location || select.value || "";
            const options = (locations || []).filter(location => location.name !== row.location);
            select.innerHTML = `<option value="">${__("Select found location")}</option>` + options.map(location => {
                const label = [location.location_code || location.name, location.location_name].filter(Boolean).join(" — ");
                return `<option value="${frappe.utils.escape_html(location.name)}">${frappe.utils.escape_html(label)}</option>`;
            }).join("");
            select.value = current;
            select.dataset.loaded = "1";
        } catch (error) {
            console.error(error);
            frappe.msgprint({ title: __("Wrong Location"), message: __("Could not load active Storage Locations for this Warehouse."), indicator: "red" });
        } finally {
            select.disabled = false;
        }
    },

    async saveReview(tr) {
        const row = this.state.count.items.find(item => item.name === tr.dataset.rowName);
        const reason = tr.querySelector(".ic-reason")?.value || "";
        let foundLocation = "";
        let foundQty = 0;
        if (reason === "Wrong Location") {
            await this.syncWrongLocationFields(tr);
            foundLocation = tr.querySelector(".ic-found-location")?.value || "";
            const pack = Math.max(1, flt(row?.pack_size || 1));
            const boxesRaw = Number(tr.querySelector(".ic-found-boxes")?.value || 0);
            const unitsRaw = Number(tr.querySelector(".ic-found-units")?.value || 0);

            if (!Number.isInteger(boxesRaw) || boxesRaw < 0 || !Number.isInteger(unitsRaw) || unitsRaw < 0) {
                frappe.msgprint({
                    title: __("Wrong Location"),
                    message: __("Found Elsewhere Boxes and Units must be non-negative whole numbers."),
                    indicator: "red"
                });
                return;
            }

            if (cint(row?.box_only) && unitsRaw > 0) {
                frappe.msgprint({
                    title: __("Wrong Location"),
                    message: __("This Item is Box Only; loose Units are not allowed."),
                    indicator: "red"
                });
                return;
            }

            if (unitsRaw >= pack) {
                frappe.msgprint({
                    title: __("Wrong Location"),
                    message: __("Found Elsewhere Units must be less than Pack Size {0}.").replace("{0}", pack),
                    indicator: "red"
                });
                return;
            }

            foundQty = flt(boxesRaw + (unitsRaw / pack), 6);
            const shortage = Math.abs(flt(row?.variance_qty || 0, 6));
            if (!foundLocation) {
                frappe.msgprint({ title: __("Wrong Location"), message: __("Select the Location where the missing quantity was physically found."), indicator: "red" });
                return;
            }
            if (foundLocation === (row?.location || "")) {
                frappe.msgprint({ title: __("Wrong Location"), message: __("Found Location must be different from the counted Location."), indicator: "red" });
                return;
            }
            if (foundQty <= 0 || foundQty > shortage + 0.000001) {
                frappe.msgprint({ title: __("Wrong Location"), message: __("Found Elsewhere Qty must be greater than zero and cannot exceed the counted shortage ({0}).").replace("{0}", shortage), indicator: "red" });
                return;
            }
        }
        await this.call("save_review_line", {
            name: this.state.count.name,
            row_name: tr.dataset.rowName,
            reason_code: reason,
            reason_note: tr.querySelector(".ic-reason-note")?.value || "",
            posting_batch_no: tr.querySelector(".ic-posting-batch")?.value || "",
            found_location: foundLocation,
            found_elsewhere_qty: foundQty,
        });
        await this.loadCount(this.state.count.name);
        frappe.show_alert({ message: __("Review saved"), indicator: "green" });
    },

    async requestRecount(rowName) {
        frappe.confirm(__("Request recount for this line? Previous evidence will remain in the audit log."), async () => {
            const result = await this.call("request_recount", {
                name: this.state.count.name,
                row_names: JSON.stringify([rowName]),
            });
            this.state.count = result.count;
            this.renderCount();
        });
    },
};
