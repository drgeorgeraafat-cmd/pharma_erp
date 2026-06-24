window.ItemInfoManager = {
    init() {
        this.drawer = document.getElementById("item-info-drawer");
    },

    async open(itemCode) {
        if (!itemCode) return;
        this.itemCode = itemCode;
        this.offset = 0;
        this.drawer.classList.remove("is-hidden");
        this.drawer.innerHTML = '<div class="drawer-loading">Loading item movement...</div>';
        await this.load(true);
    },

    close() {
        this.drawer?.classList.add("is-hidden");
        if (this.drawer) this.drawer.innerHTML = "";
    },

    async load(reset = false) {
        if (reset) this.offset = 0;
        const warehouse = PharmacyPOS.state.settings.default_warehouse || "";
        const data = await PharmacyAPI.getItemMovement(this.itemCode, warehouse, 20, this.offset);
        if (reset) {
            this.data = data;
            this.render(data);
        } else {
            this.data.movements = [...(this.data.movements || []), ...(data.movements || [])];
            this.data.has_more = data.has_more;
            this.renderMovements();
        }
    },

    render(data) {
        const item = data.item || {};
        const available = (data.warehouses || []).reduce((total, row) => total + flt(row.actual_qty || 0) - flt(row.reserved_qty || 0), 0);
        this.drawer.innerHTML = `
            <div class="drawer-header">
                <div><h3>${frappe.utils.escape_html(item.item_name || item.item_code || item.name)}</h3><small>${frappe.utils.escape_html(item.item_code || item.name || "")}</small></div>
                <button id="close-item-drawer" class="drawer-close">×</button>
            </div>
            <div class="drawer-summary">
                <div><span>Current Stock</span><strong>${flt(item.actual_qty || 0, 2)}</strong></div>
                <div><span>Available</span><strong>${flt(available, 2)}</strong></div>
                <div><span>Last Purchase Rate</span><strong>${format_currency(data.last_purchase_rate || 0)}</strong></div>
                <div><span>Last Sales Rate</span><strong>${format_currency(data.last_sales_rate || 0)}</strong></div>
            </div>
            <div class="drawer-tabs">
                <button class="drawer-tab is-active" data-tab="movements">Movements</button>
                <button class="drawer-tab" data-tab="alternatives">Alternatives</button>
                <button class="drawer-tab" data-tab="warehouses">Warehouses</button>
                <button class="drawer-tab" data-tab="batches">Batches</button>
            </div>
            <div class="drawer-body">
                <div class="drawer-view" data-view="movements"><div id="item-movement-holder"></div></div>
                <div class="drawer-view is-hidden" data-view="alternatives">${this.alternativesTable(data.alternatives || [])}</div>
                <div class="drawer-view is-hidden" data-view="warehouses">${this.warehouseTable(data.warehouses || [])}</div>
                <div class="drawer-view is-hidden" data-view="batches">${this.batchTable(data.batches || [])}</div>
            </div>`;
        this.drawer.querySelector("#close-item-drawer")?.addEventListener("click", () => this.close());
        this.drawer.querySelectorAll(".drawer-tab").forEach(button => button.addEventListener("click", () => {
            this.drawer.querySelectorAll(".drawer-tab").forEach(tab => tab.classList.remove("is-active"));
            button.classList.add("is-active");
            this.drawer.querySelectorAll(".drawer-view").forEach(view => view.classList.add("is-hidden"));
            this.drawer.querySelector(`[data-view="${button.dataset.tab}"]`)?.classList.remove("is-hidden");
        }));
        this.drawer.querySelectorAll(".add-alternative-item").forEach(button => button.addEventListener("click", async () => {
            await InvoiceManager.addItem(button.dataset.item);
            frappe.show_alert({ message: __("Alternative item added"), indicator: "green" });
        }));
        this.renderMovements();
    },

    movementLabel(row) {
        const qty = flt(row.actual_qty || 0);
        if (row.voucher_type === "Purchase Receipt" || row.voucher_type === "Purchase Invoice") return "Purchase";
        if (row.voucher_type === "Sales Invoice" || row.voucher_type === "Delivery Note") return qty < 0 ? "Sale" : "Sales Return";
        return row.description || row.voucher_type || "Movement";
    },

    renderMovements() {
        const holder = this.drawer.querySelector("#item-movement-holder");
        if (!holder) return;
        const rows = this.data?.movements || [];
        holder.innerHTML = rows.length ? `
            <div class="movement-list">${rows.map(row => `
                <div class="movement-card">
                    <div class="movement-main">
                        <strong>${frappe.utils.escape_html(this.movementLabel(row))}</strong>
                        <span class="${flt(row.actual_qty) >= 0 ? "qty-positive" : "qty-negative"}">${flt(row.actual_qty, 3) >= 0 ? "+" : ""}${flt(row.actual_qty, 3)}</span>
                    </div>
                    <div class="movement-meta"><span>${frappe.utils.escape_html(`${row.posting_date || ""} ${row.posting_time || ""}`)}</span><span>${frappe.utils.escape_html(row.warehouse || "")}</span><span>Balance: ${flt(row.qty_after_transaction || 0, 3)}</span></div>
                    <div class="movement-ref"><a target="_blank" href="/app/${(row.voucher_type || "").toLowerCase().replace(/\s+/g, "-")}/${encodeURIComponent(row.voucher_no)}">${frappe.utils.escape_html(row.voucher_no || "")}</a>${row.party_name ? `<span>${frappe.utils.escape_html(row.party_type + ": " + row.party_name)}</span>` : ""}${row.batch_no ? `<span>Batch: ${frappe.utils.escape_html(row.batch_no)}</span>` : ""}</div>
                </div>`).join("")}</div>
            ${this.data.has_more ? '<button id="load-more-movements" class="btn btn-default btn-sm drawer-load-more">Load More</button>' : ""}` : '<div class="empty-state">No movements found.</div>';
        holder.querySelector("#load-more-movements")?.addEventListener("click", async () => {
            this.offset += 20;
            await this.load(false);
        });
    },

    alternativesTable(rows) {
        if (!rows.length) return '<div class="empty-state">No exact alternatives found with the same active ingredients and strengths.</div>';
        return `<div class="alternative-list">${rows.map(row => `
            <div class="alternative-card">
                <div class="alternative-image">${row.image ? `<img src="${frappe.utils.escape_html(row.image)}" alt="">` : "💊"}</div>
                <div class="alternative-content">
                    <strong>${frappe.utils.escape_html(row.item_name || row.item_code)}</strong>
                    ${row.item_name_ar ? `<small>${frappe.utils.escape_html(row.item_name_ar)}</small>` : ""}
                    <small>${frappe.utils.escape_html(row.ingredient_summary || "")}</small>
                    <div><span>Stock: ${flt(row.actual_qty || 0, 2)}</span><span>${format_currency(row.customer_price || 0)}</span></div>
                </div>
                <button class="btn btn-sm btn-primary add-alternative-item" data-item="${frappe.utils.escape_html(row.item_code)}">Add</button>
            </div>`).join("")}</div>`;
    },

    warehouseTable(rows) {
        if (!rows.length) return '<div class="empty-state">No warehouse stock.</div>';
        return `<table class="table table-bordered compact-table"><thead><tr><th>Warehouse</th><th>Stock</th><th>Reserved</th><th>Projected</th></tr></thead><tbody>${rows.map(row => `<tr><td>${frappe.utils.escape_html(row.warehouse)}</td><td>${flt(row.actual_qty, 3)}</td><td>${flt(row.reserved_qty, 3)}</td><td>${flt(row.projected_qty, 3)}</td></tr>`).join("")}</tbody></table>`;
    },

    batchTable(rows) {
        if (!rows.length) return '<div class="empty-state">No available batches.</div>';
        return `<table class="table table-bordered compact-table"><thead><tr><th>Batch</th><th>Expiry</th><th>Qty</th></tr></thead><tbody>${rows.map(row => `<tr><td>${frappe.utils.escape_html(row.name || row.batch_no)}</td><td>${frappe.utils.escape_html(row.expiry_date || "")}</td><td>${flt(row.qty, 3)}</td></tr>`).join("")}</tbody></table>`;
    }
};
