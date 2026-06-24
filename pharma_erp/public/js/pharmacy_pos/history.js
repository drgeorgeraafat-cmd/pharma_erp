window.HistoryManager = {
    init() {},

    async open() {
        const customer = PharmacyPOS.state.customer;
        if (!customer) {
            frappe.msgprint(__("Select a customer first."));
            return;
        }

        const dialog = new frappe.ui.Dialog({
            title: `${__("Customer History")}: ${customer.customer_name || customer.name}`,
            size: "extra-large",
            fields: [{ fieldtype: "HTML", fieldname: "history_html" }]
        });
        dialog.show();
        dialog.get_field("history_html").$wrapper.html(this.shell());
        dialog.$wrapper.addClass("pharmacy-history-dialog");
        this.dialog = dialog;
        this.bind(dialog);
        await this.loadInvoices(dialog);
    },

    shell() {
        return `
            <div class="history-shell">
                <div class="history-tabs">
                    <button class="history-tab is-active" data-tab="invoices">Invoices</button>
                    <button class="history-tab" data-tab="purchased">Purchased Items</button>
                    <button class="history-tab" data-tab="account">Account & Credit</button>
                </div>
                <div class="history-content">
                    <div class="history-view" data-view="invoices">
                        <div class="history-split">
                            <div class="history-invoice-list" id="history-invoice-list"><div class="loading-state">Loading...</div></div>
                            <div class="history-invoice-detail" id="history-invoice-detail"><div class="empty-state">Select an invoice.</div></div>
                        </div>
                    </div>
                    <div class="history-view is-hidden" data-view="purchased">
                        <div class="history-toolbar">
                            <input id="purchased-search" type="text" class="form-control" placeholder="Search purchased items">
                            <select id="purchased-period" class="form-control">
                                <option value="0">All time</option>
                                <option value="30">Last 30 days</option>
                                <option value="90">Last 3 months</option>
                                <option value="365">Last year</option>
                            </select>
                        </div>
                        <div id="purchased-items-holder"><div class="loading-state">Open this tab to load items.</div></div>
                    </div>
                    <div class="history-view is-hidden" data-view="account">
                        <div id="history-account-holder"></div>
                    </div>
                </div>
            </div>`;
    },

    bind(dialog) {
        const root = dialog.get_field("history_html").$wrapper[0];
        root.querySelectorAll(".history-tab").forEach(button => {
            button.addEventListener("click", async () => {
                root.querySelectorAll(".history-tab").forEach(item => item.classList.remove("is-active"));
                button.classList.add("is-active");
                root.querySelectorAll(".history-view").forEach(view => view.classList.add("is-hidden"));
                root.querySelector(`[data-view="${button.dataset.tab}"]`)?.classList.remove("is-hidden");
                if (button.dataset.tab === "purchased") await this.loadPurchased(dialog);
                if (button.dataset.tab === "account") this.renderAccount(dialog);
            });
        });

        root.querySelector("#purchased-period")?.addEventListener("change", () => this.loadPurchased(dialog, true));
        root.querySelector("#purchased-search")?.addEventListener("input", event => this.filterPurchased(dialog, event.target.value));
    },

    async loadInvoices(dialog) {
        const root = dialog.get_field("history_html").$wrapper[0];
        const holder = root.querySelector("#history-invoice-list");
        const rows = await PharmacyAPI.getCustomerHistory(PharmacyPOS.state.customer.name, 50) || [];
        dialog.__historyInvoices = rows;
        if (!rows.length) {
            holder.innerHTML = '<div class="empty-state">No invoices found.</div>';
            return;
        }
        holder.innerHTML = rows.map((row, index) => `
            <button class="history-invoice-card ${index === 0 ? "is-active" : ""}" data-index="${index}">
                <div><strong>${frappe.utils.escape_html(row.name)}</strong><small>${frappe.utils.escape_html(row.posting_date || "")}</small></div>
                <div><span>${frappe.utils.escape_html(row.custom_order_type || (row.is_return ? "Return" : ""))}</span><strong>${format_currency(row.grand_total || 0)}</strong></div>
            </button>`).join("");
        holder.querySelectorAll("[data-index]").forEach(button => {
            button.addEventListener("click", () => {
                holder.querySelectorAll(".history-invoice-card").forEach(card => card.classList.remove("is-active"));
                button.classList.add("is-active");
                this.loadInvoiceDetails(dialog, rows[cint(button.dataset.index)]);
            });
        });
        await this.loadInvoiceDetails(dialog, rows[0]);
    },

    async loadInvoiceDetails(dialog, row) {
        const root = dialog.get_field("history_html").$wrapper[0];
        const holder = root.querySelector("#history-invoice-detail");
        holder.innerHTML = '<div class="loading-state">Loading invoice...</div>';
        const details = await PharmacyAPI.getInvoiceHistoryDetails(row.name);
        const items = details?.items || [];
        holder.innerHTML = `
            <div class="history-detail-header">
                <div><h4>${frappe.utils.escape_html(details.name)}</h4><span>${frappe.utils.escape_html(details.posting_date || "")} · ${frappe.utils.escape_html(details.status || "")}</span></div>
                <div><strong>${format_currency(details.grand_total || 0)}</strong><a class="btn btn-sm btn-default" target="_blank" href="/app/sales-invoice/${encodeURIComponent(details.name)}">Open Invoice</a></div>
            </div>
            ${flt(details.delivery_fee || 0) > 0 || details.delivery_zone ? `<div class="history-delivery-summary"><span>Zone: <strong>${frappe.utils.escape_html(details.delivery_zone || "")}</strong></span><span>Fee: <strong>${format_currency(details.delivery_fee || 0)}</strong></span><span>${frappe.utils.escape_html(details.delivery_fee_rule || "")}</span></div>` : ""}
            <div class="table-responsive">
                <table class="table table-bordered compact-table">
                    <thead><tr><th>Item</th><th>Boxes</th><th>Units</th><th>Batch</th><th>Rate</th><th>Disc %</th><th>Total</th><th></th></tr></thead>
                    <tbody>${items.map(item => `
                        <tr>
                            <td><button class="link-button history-item-info" data-item="${frappe.utils.escape_html(item.item_code)}"><strong>${frappe.utils.escape_html(item.item_name || item.item_code)}</strong></button><small>${frappe.utils.escape_html(item.item_code)}</small></td>
                            <td>${flt(item.box_qty, 2)}</td><td>${flt(item.unit_qty, 2)}</td><td>${frappe.utils.escape_html(item.batch_no || "")}</td>
                            <td>${format_currency(item.rate || 0)}</td><td>${flt(item.discount_percentage || 0, 2)}</td><td>${format_currency(item.amount || 0)}</td>
                            <td><button class="btn btn-sm btn-primary add-history-item" data-item="${frappe.utils.escape_html(item.item_code)}">Add Again</button></td>
                        </tr>`).join("")}</tbody>
                </table>
            </div>`;
        holder.querySelectorAll(".add-history-item").forEach(button => button.addEventListener("click", async () => {
            await InvoiceManager.addItem(button.dataset.item);
            frappe.show_alert({ message: __("Item added to invoice"), indicator: "green" });
        }));
        holder.querySelectorAll(".history-item-info").forEach(button => button.addEventListener("click", () => ItemInfoManager.open(button.dataset.item)));
    },

    async loadPurchased(dialog, force = false) {
        const root = dialog.get_field("history_html").$wrapper[0];
        const holder = root.querySelector("#purchased-items-holder");
        if (dialog.__purchasedLoaded && !force) return;
        holder.innerHTML = '<div class="loading-state">Loading purchased items...</div>';
        const days = cint(root.querySelector("#purchased-period")?.value || 0);
        const rows = await PharmacyAPI.getCustomerPurchasedItems(PharmacyPOS.state.customer.name, days, 300) || [];
        dialog.__purchasedItems = rows;
        dialog.__purchasedLoaded = true;
        this.renderPurchased(dialog, rows);
    },

    renderPurchased(dialog, rows) {
        const root = dialog.get_field("history_html").$wrapper[0];
        const holder = root.querySelector("#purchased-items-holder");
        if (!rows.length) {
            holder.innerHTML = '<div class="empty-state">No purchased items found.</div>';
            return;
        }
        holder.innerHTML = `
            <table class="table table-bordered compact-table purchased-table">
                <thead><tr><th>Item</th><th>Net Qty</th><th>Times</th><th>Last Purchase</th><th>Last Rate</th><th></th></tr></thead>
                <tbody>${rows.map(row => {
                    const pack = flt(row.pack_size || 1) || 1;
                    const qty = flt(row.net_qty || 0);
                    const boxes = Math.floor(qty + 1e-9);
                    const units = flt((qty - boxes) * pack, 2);
                    return `<tr data-search="${frappe.utils.escape_html(`${row.item_name || ""} ${row.item_code || ""}`.toLowerCase())}">
                        <td><button class="link-button purchased-item-info" data-item="${frappe.utils.escape_html(row.item_code)}"><strong>${frappe.utils.escape_html(row.item_name || row.item_code)}</strong></button><small>${frappe.utils.escape_html(row.item_code)}</small></td>
                        <td>${boxes} Box${units ? ` + ${units} Unit` : ""}</td><td>${cint(row.purchase_count || 0)}</td><td>${frappe.utils.escape_html(row.last_purchase_date || "")}</td><td>${format_currency(row.last_rate || 0)}</td>
                        <td><button class="btn btn-sm btn-primary add-purchased-item" data-item="${frappe.utils.escape_html(row.item_code)}">Add</button></td></tr>`;
                }).join("")}</tbody>
            </table>`;
        holder.querySelectorAll(".add-purchased-item").forEach(button => button.addEventListener("click", async () => {
            await InvoiceManager.addItem(button.dataset.item);
            frappe.show_alert({ message: __("Item added to invoice"), indicator: "green" });
        }));
        holder.querySelectorAll(".purchased-item-info").forEach(button => button.addEventListener("click", () => ItemInfoManager.open(button.dataset.item)));
    },

    filterPurchased(dialog, text) {
        const root = dialog.get_field("history_html").$wrapper[0];
        const query = (text || "").trim().toLowerCase();
        root.querySelectorAll(".purchased-table tbody tr").forEach(row => row.classList.toggle("is-hidden", query && !row.dataset.search.includes(query)));
    },

    renderAccount(dialog) {
        const root = dialog.get_field("history_html").$wrapper[0];
        const holder = root.querySelector("#history-account-holder");
        const context = PharmacyPOS.state.paymentContext || {};
        const loyalty = context.loyalty || {};
        const advances = context.advances || [];
        const credits = context.credits || [];
        holder.innerHTML = `
            <div class="account-summary-cards">
                <div><span>Loyalty Points</span><strong>${flt(loyalty.available_points || 0, 2)}</strong></div>
                <div><span>Advance</span><strong>${format_currency(context.advance_total || 0)}</strong></div>
                <div><span>Customer Credit</span><strong>${format_currency(context.credit_total || 0)}</strong></div>
            </div>
            <div class="account-columns">
                <div><h5>Advance Payments</h5>${this.balanceTable(advances, "Payment Entry")}</div>
                <div><h5>Credit Notes</h5>${this.balanceTable(credits, "Sales Invoice")}</div>
            </div>`;
    },

    balanceTable(rows, type) {
        if (!rows.length) return '<div class="empty-state">None</div>';
        return `<table class="table table-bordered compact-table"><thead><tr><th>Reference</th><th>Date</th><th>Available</th></tr></thead><tbody>${rows.map(row => `<tr><td><a target="_blank" href="/app/${type === "Payment Entry" ? "payment-entry" : "sales-invoice"}/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(row.name)}</a></td><td>${frappe.utils.escape_html(row.posting_date || "")}</td><td>${format_currency(row.available_amount || 0)}</td></tr>`).join("")}</tbody></table>`;
    }
};
