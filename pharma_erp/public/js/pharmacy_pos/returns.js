window.ReturnsManager = {
    init() {
        this.button = document.getElementById("btn-return");
        this.button?.addEventListener("click", () => this.open());
    },

    async open(options = {}) {
        if (!PaymentManager.modes.length) await PaymentManager.loadModes();
        const dialog = new frappe.ui.Dialog({
            title: __("Sales Return"),
            size: "extra-large",
            fields: [{ fieldtype: "HTML", fieldname: "return_html" }],
            primary_action_label: __("Create Return"),
            primary_action: async () => {
                try {
                    const data = this.collect(dialog);
                    dialog.get_primary_btn().prop("disabled", true);
                    const result = await PharmacyAPI.createSalesReturn(data);
                    dialog.hide();

                    // Stay on Pharmacy POS. Opening the standard Sales Invoice
                    // form is now optional instead of automatic.
                    if (result.customer && PharmacyPOS.state.customer?.name === result.customer) {
                        await PaymentManager.loadCustomerContext(result.customer);
                    }

                    const creditMessage = result.keep_as_credit
                        ? `<p><strong>${__("Customer Credit Added")}:</strong> ${format_currency(result.credit_amount || 0)}</p>`
                        : "";

                    const creditNotes = result.credit_notes || result.names || (result.name ? [result.name] : []);
                    const creditNoteLinks = creditNotes.map(name => `<li><a href="/app/sales-invoice/${encodeURIComponent(name)}" target="_blank">${frappe.utils.escape_html(name)}</a></li>`).join("");
                    frappe.msgprint({
                        title: __("Return Created"),
                        indicator: "green",
                        message: `
                            <p>${creditNotes.length > 1 ? __("The return was split into Credit Notes according to the source invoices.") : __("The return was created successfully.")}</p>
                            ${creditNoteLinks ? `<ul>${creditNoteLinks}</ul>` : ""}
                            ${creditMessage}
                        `
                    });
                } catch (error) { console.error(error); }
                finally { dialog.get_primary_btn().prop("disabled", false); }
            }
        });
        dialog.__deliveryReturnRequest = options.returnRequest || window.__pharmacy_pos_return_request || "";
        dialog.show();
        const wrapper = dialog.get_field("return_html").$wrapper;
        wrapper.html(this.baseHtml());
        dialog.__returnMode = "against_invoice";
        dialog.__manualItems = [];
        this.bind(dialog);
        await this.searchInvoices(dialog, "");
    },

    baseHtml() {
        return `<div class="return-dialog-content">
            <div class="return-mode-tabs">
                <button type="button" class="return-mode-tab is-active" data-mode="against_invoice">Against Invoice</button>
                <button type="button" class="return-mode-tab" data-mode="without_invoice">Without Invoice</button>
            </div>
            <div class="return-mode-view" data-return-view="against_invoice">
                <div class="return-search-row">
                    <input id="return-invoice-search" class="form-control" type="text" placeholder="Invoice number, last digits, customer or mobile">
                    <label class="checkbox-label"><input id="return-only-customer" type="checkbox"> Selected customer only</label>
                    <button type="button" id="return-search-btn" class="btn btn-default">Search</button>
                </div>
                <div id="return-search-results" class="return-search-results"></div>
                <div id="return-invoice-details"></div>
            </div>
            <div class="return-mode-view is-hidden" data-return-view="without_invoice">
                <div class="manual-return-header">
                    <div class="field-group"><label>Customer</label><input id="manual-return-customer" class="form-control" value="${frappe.utils.escape_html(PharmacyPOS.state.customer?.customer_name || PharmacyPOS.state.customer?.name || "")}" readonly></div>
                    <div class="field-group manual-return-item-group"><label>Item</label><div class="autocomplete-wrap"><input id="manual-return-item-search" class="form-control" placeholder="Search item"><div id="manual-return-item-results" class="autocomplete-results"></div></div></div>
                    <div class="field-group"><label>Reason</label><input id="manual-return-reason" class="form-control" placeholder="Required reason"></div>
                </div>
                <div id="manual-return-items"></div>
                <div id="manual-return-settlement"></div>
            </div>
        </div>`;
    },

    bind(dialog) {
        const root = dialog.get_field("return_html").$wrapper[0];
        root.querySelectorAll(".return-mode-tab").forEach(button => button.addEventListener("click", async () => {
            root.querySelectorAll(".return-mode-tab").forEach(tab => tab.classList.remove("is-active"));
            button.classList.add("is-active");
            dialog.__returnMode = button.dataset.mode;
            root.querySelectorAll(".return-mode-view").forEach(view => view.classList.add("is-hidden"));
            root.querySelector(`[data-return-view="${button.dataset.mode}"]`)?.classList.remove("is-hidden");
            if (button.dataset.mode === "without_invoice") this.renderManualItems(dialog);
        }));

        const invoiceInput = root.querySelector("#return-invoice-search");
        const runSearch = () => this.searchInvoices(dialog, invoiceInput.value);
        root.querySelector("#return-search-btn")?.addEventListener("click", runSearch);
        invoiceInput?.addEventListener("input", frappe.utils.debounce(runSearch, 250));
        invoiceInput?.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); runSearch(); } });
        root.querySelector("#return-only-customer")?.addEventListener("change", runSearch);

        const itemInput = root.querySelector("#manual-return-item-search");
        itemInput?.addEventListener("input", frappe.utils.debounce(() => this.searchManualItems(dialog, itemInput.value), 250));
        itemInput?.addEventListener("focus", () => this.searchManualItems(dialog, itemInput.value));
    },

    async searchInvoices(dialog, txt) {
        const root = dialog.get_field("return_html").$wrapper[0];
        const resultBox = root.querySelector("#return-search-results");
        const onlyCustomer = root.querySelector("#return-only-customer")?.checked;
        const customer = onlyCustomer ? (PharmacyPOS.state.customer?.name || "") : "";
        const rows = await PharmacyAPI.searchSalesInvoices(txt || "", customer, 30);
        if (!rows?.length) { resultBox.innerHTML = '<div class="autocomplete-empty">No invoices found</div>'; return; }
        resultBox.innerHTML = rows.map((row, index) => `<button type="button" class="return-invoice-option" data-index="${index}"><strong>${frappe.utils.escape_html(row.name)}</strong><span>${frappe.utils.escape_html(row.customer_name || row.customer || "")}</span><span>${frappe.utils.escape_html(row.posting_date || "")}</span><span>${format_currency(row.grand_total || 0)}</span></button>`).join("");
        resultBox.querySelectorAll("[data-index]").forEach(button => button.addEventListener("click", () => this.selectInvoice(dialog, rows[cint(button.dataset.index)])));
    },

    async selectInvoice(dialog, invoiceRow) {
        const root = dialog.get_field("return_html").$wrapper[0];
        const details = await PharmacyAPI.getReturnableInvoice(invoiceRow.name, dialog.__deliveryReturnRequest || "");
        dialog.__returnInvoice = details;
        root.querySelector("#return-search-results").innerHTML = "";
        root.querySelector("#return-invoice-search").value = invoiceRow.name;
        this.renderInvoiceDetails(dialog, details);
    },

    renderInvoiceDetails(dialog, details) {
        const root = dialog.get_field("return_html").$wrapper[0];
        const holder = root.querySelector("#return-invoice-details");
        const lockedRequest = Boolean(details.delivery_return_request);
        const rows = (details.items || []).map(item => `<tr class="return-item-row" data-source-item="${frappe.utils.escape_html(item.source_item)}" data-source-invoice="${frappe.utils.escape_html(item.source_invoice || details.name)}">
            <td>${frappe.utils.escape_html(item.item_name || item.item_code)}<small>${frappe.utils.escape_html(item.item_code)}</small><small><b>${item.source_invoice_type === "Add-on" ? __("Add-on Invoice") : __("Original Invoice")}</b>: ${frappe.utils.escape_html(item.source_invoice || details.name)}</small></td><td>${frappe.utils.escape_html(item.batch_no || "")}</td>
            <td>${flt(item.sold_qty, 3)}</td><td>${flt(item.returned_qty, 3)}</td><td>${flt(item.returnable_qty, 3)}</td>
            <td><input class="return-boxes form-control" type="number" min="0" step="1" value="${lockedRequest ? flt(item.requested_box_qty || 0, 3) : 0}" ${lockedRequest ? "readonly" : ""}></td>
            <td><input class="return-units form-control" type="number" min="0" step="1" max="${Math.max(0, flt(item.pack_size) - 1)}" value="${lockedRequest ? flt(item.requested_unit_qty || 0, 3) : 0}" ${lockedRequest ? "readonly" : ""}></td>
            <td>${format_currency(item.rate || 0)}</td></tr>`).join("");
        const requestBadge = details.delivery_return_request
            ? `<div class="alert alert-warning"><strong>${__("Partial Delivery Return")}</strong>: ${frappe.utils.escape_html(details.delivery_return_request)} — ${__("Only the requested items can be returned. Delivery fee is not included.")}</div>`
            : "";
        holder.innerHTML = `${requestBadge}<div class="selected-return-invoice"><h5>${frappe.utils.escape_html(details.name)} — ${frappe.utils.escape_html(details.customer_name || details.customer)}</h5>
            <table class="table table-bordered compact-table"><thead><tr><th>Item</th><th>Batch</th><th>Sold</th><th>Returned</th><th>Available</th><th>Boxes</th><th>Units</th><th>Rate</th></tr></thead><tbody>${rows}</tbody></table></div>
            ${this.settlementHtml()}`;
        holder.querySelectorAll(".return-boxes, .return-units").forEach(input => input.addEventListener("input", () => this.updateReturnTotal(dialog)));
        this.bindSettlement(holder, dialog);
        this.updateReturnTotal(dialog);
    },

    async searchManualItems(dialog, txt) {
        const root = dialog.get_field("return_html").$wrapper[0];
        const box = root.querySelector("#manual-return-item-results");
        const allRows = await PharmacyAPI.searchItems(txt || "", PharmacyPOS.state.settings.default_warehouse || "") || [];
        const feeItem = PharmacyPOS.state.settings.delivery_fee_item || "";
        const rows = allRows.filter(row => (row.item_code || row.name) !== feeItem);
        if (!rows.length) { box.innerHTML = '<div class="autocomplete-empty">No items found</div>'; return; }
        box.innerHTML = rows.map((row, index) => `<button class="autocomplete-option" data-index="${index}"><strong>${frappe.utils.escape_html(row.item_name || row.item_code)}</strong><small>${frappe.utils.escape_html(row.item_code || row.name)}</small></button>`).join("");
        box.querySelectorAll("[data-index]").forEach(button => button.addEventListener("click", async () => {
            const selected = rows[cint(button.dataset.index)];
            const item = await PharmacyAPI.getReturnItem(selected.item_code || selected.name, PharmacyPOS.state.settings.default_warehouse || "");
            if (!dialog.__manualItems.find(row => row.item_code === item.item_code)) {
                dialog.__manualItems.push({
                    item_code: item.item_code || item.name,
                    item_name: item.item_name || item.item_code,
                    has_batch_no: cint(item.has_batch_no),
                    batches: item.return_batches || [],
                    batch_no: "",
                    pack_size: flt(item.custom_pack_size || 1) || 1,
                    box_only: cint(item.custom_box_only),
                    box_qty: 1,
                    unit_qty: 0,
                    rate: flt(item.custom_customer_price || 0)
                });
            }
            root.querySelector("#manual-return-item-search").value = "";
            box.innerHTML = "";
            this.renderManualItems(dialog);
        }));
    },

    renderManualItems(dialog) {
        const root = dialog.get_field("return_html").$wrapper[0];
        const holder = root.querySelector("#manual-return-items");
        if (!dialog.__manualItems.length) {
            holder.innerHTML = '<div class="empty-state">Search and add returned items.</div>';
            root.querySelector("#manual-return-settlement").innerHTML = this.settlementHtml();
            this.bindSettlement(root.querySelector("#manual-return-settlement"), dialog);
            return;
        }
        holder.innerHTML = `<table class="table table-bordered compact-table"><thead><tr><th>Item</th><th>Batch</th><th>Boxes</th><th>Units</th><th>Rate</th><th></th></tr></thead><tbody>${dialog.__manualItems.map((item, index) => `<tr data-index="${index}"><td>${frappe.utils.escape_html(item.item_name)}<small>${frappe.utils.escape_html(item.item_code)}</small></td><td><select class="manual-batch form-control" ${item.has_batch_no ? "" : "disabled"}><option value="">${item.has_batch_no ? "Select batch" : "N/A"}</option>${(item.batches || []).map(batch => `<option value="${frappe.utils.escape_html(batch.name)}" ${batch.name === item.batch_no ? "selected" : ""}>${frappe.utils.escape_html(batch.name)}${batch.expiry_date ? ` - ${frappe.utils.escape_html(batch.expiry_date)}` : ""}</option>`).join("")}</select></td><td><input class="manual-boxes form-control" type="number" min="0" step="1" value="${item.box_qty}"></td><td><input class="manual-units form-control" type="number" min="0" step="1" value="${item.unit_qty}" ${item.box_only ? "disabled" : ""}></td><td><input class="manual-rate form-control" type="number" min="0" step="0.01" value="${item.rate}"></td><td><button class="btn btn-danger btn-sm remove-manual-item">×</button></td></tr>`).join("")}</tbody></table>`;
        holder.querySelectorAll("tr[data-index]").forEach(tr => {
            const item = dialog.__manualItems[cint(tr.dataset.index)];
            tr.querySelector(".manual-batch")?.addEventListener("change", e => item.batch_no = e.target.value);
            tr.querySelector(".manual-boxes")?.addEventListener("input", e => { item.box_qty = flt(e.target.value); this.updateReturnTotal(dialog); });
            tr.querySelector(".manual-units")?.addEventListener("input", e => { item.unit_qty = flt(e.target.value); this.updateReturnTotal(dialog); });
            tr.querySelector(".manual-rate")?.addEventListener("input", e => { item.rate = flt(e.target.value); this.updateReturnTotal(dialog); });
            tr.querySelector(".remove-manual-item")?.addEventListener("click", () => { dialog.__manualItems.splice(cint(tr.dataset.index), 1); this.renderManualItems(dialog); });
        });
        root.querySelector("#manual-return-settlement").innerHTML = this.settlementHtml();
        this.bindSettlement(root.querySelector("#manual-return-settlement"), dialog);
        this.updateReturnTotal(dialog);
    },

    settlementHtml() {
        return `<div class="payment-section return-settlement-section"><label class="checkbox-label"><input class="keep-return-credit" type="checkbox" checked> Keep refund as Customer Credit</label><div class="return-refund-area is-hidden"><div class="payment-section-title"><h5>Refund Methods</h5><button type="button" class="add-refund-row btn btn-sm btn-default">+ Add Method</button></div><table class="table table-bordered compact-table"><thead><tr><th>Mode</th><th>Amount</th><th></th></tr></thead><tbody class="refund-rows"></tbody></table></div><div class="return-total-line">Estimated Return: <strong class="estimated-return-total">0.00</strong></div></div>`;
    },

    bindSettlement(holder, dialog) {
        if (!holder) return;
        const keep = holder.querySelector(".keep-return-credit");
        const area = holder.querySelector(".return-refund-area");
        keep?.addEventListener("change", () => area.classList.toggle("is-hidden", keep.checked));
        holder.querySelector(".add-refund-row")?.addEventListener("click", () => this.addRefundRow(holder));
        this.addRefundRow(holder);
    },

    addRefundRow(holder) {
        const tbody = holder.querySelector(".refund-rows");
        if (!tbody || tbody.children.length) return;
        const tr = document.createElement("tr");
        tr.className = "refund-row";
        tr.innerHTML = `<td><select class="refund-mode form-control">${PaymentManager.modeOptions("")}</select></td><td><input class="refund-amount form-control" type="number" min="0" step="0.01"></td><td><button type="button" class="remove-refund-row btn btn-sm btn-danger">×</button></td>`;
        tbody.appendChild(tr);
        tr.querySelector(".remove-refund-row")?.addEventListener("click", () => tr.remove());
    },

    updateReturnTotal(dialog) {
        const root = dialog.get_field("return_html").$wrapper[0];
        let total = 0;
        if (dialog.__returnMode === "against_invoice" && dialog.__returnInvoice) {
            root.querySelectorAll(".return-item-row").forEach(row => {
                const source = dialog.__returnInvoice.items.find(item => item.source_item === row.dataset.sourceItem);
                const qty = flt(row.querySelector(".return-boxes")?.value || 0) + flt(row.querySelector(".return-units")?.value || 0) / (flt(source.pack_size || 1) || 1);
                total += qty * flt(source.rate || 0);
            });
        } else {
            total = (dialog.__manualItems || []).reduce((sum, item) => sum + (flt(item.box_qty) + flt(item.unit_qty) / (flt(item.pack_size) || 1)) * flt(item.rate), 0);
        }
        root.querySelectorAll(".estimated-return-total").forEach(el => el.textContent = format_currency(total));
    },

    collect(dialog) {
        const root = dialog.get_field("return_html").$wrapper[0];
        let items = [];
        let invoice = "";
        if (dialog.__returnMode === "against_invoice") {
            const details = dialog.__returnInvoice;
            if (!details) frappe.throw(__("Select the original invoice."));
            invoice = details.name;
            items = [...root.querySelectorAll(".return-item-row")].map(row => {
                const source = details.items.find(item => item.source_item === row.dataset.sourceItem);
                const box_qty = flt(row.querySelector(".return-boxes")?.value || 0);
                const unit_qty = flt(row.querySelector(".return-units")?.value || 0);
                const qty = flt(box_qty + unit_qty / (flt(source.pack_size || 1) || 1), 6);
                if (qty - flt(source.returnable_qty) > 1e-9) frappe.throw(__("Return quantity exceeds available quantity."));
                return { source_invoice: source.source_invoice || row.dataset.sourceInvoice || details.name, source_item: source.source_item, box_qty, unit_qty, qty };
            }).filter(row => row.qty > 0);
        } else {
            const reason = root.querySelector("#manual-return-reason")?.value?.trim() || "";
            if (!reason) frappe.throw(__("Return reason is required."));
            items = (dialog.__manualItems || []).map(item => ({ ...item, qty: flt(flt(item.box_qty) + flt(item.unit_qty) / (flt(item.pack_size) || 1), 6) })).filter(row => row.qty > 0);
            if (!items.length) frappe.throw(__("Add at least one return item."));
            dialog.__manualReason = reason;
        }
        if (!items.length) frappe.throw(__("Enter a return quantity for at least one item."));
        const view = root.querySelector(`[data-return-view="${dialog.__returnMode}"]`);
        const settlement = view.querySelector(".return-settlement-section");
        const keepAsCredit = settlement.querySelector(".keep-return-credit")?.checked ? 1 : 0;
        const payments = keepAsCredit ? [] : [...settlement.querySelectorAll(".refund-row")].map(row => ({ mode_of_payment: row.querySelector(".refund-mode")?.value || "", amount: flt(row.querySelector(".refund-amount")?.value || 0) })).filter(row => row.mode_of_payment && row.amount > 0);
        if (!keepAsCredit && !payments.length) frappe.throw(__("Add a refund method or keep it as customer credit."));
        return {
            mode: dialog.__returnMode,
            invoice,
            delivery_return_request: dialog.__deliveryReturnRequest || dialog.__returnInvoice?.delivery_return_request || "",
            customer: PharmacyPOS.state.customer?.name || PharmacyPOS.state.settings.default_customer || "",
            company: PharmacyPOS.state.settings.company || "",
            warehouse: PharmacyPOS.state.settings.default_warehouse || "",
            reason: dialog.__manualReason || "",
            items,
            keep_as_credit: keepAsCredit,
            payments,
            submit: 1
        };
    }
};
