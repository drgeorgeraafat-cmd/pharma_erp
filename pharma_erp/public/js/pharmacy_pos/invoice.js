window.InvoiceManager = {
    saving: false,
    lastInvoice: null,

    init() {
        this.body = document.getElementById("invoice-body");
        this.saveButton = document.getElementById("btn-save");
        this.submitButton = document.getElementById("btn-submit");
        this.clearButton = document.getElementById("btn-clear");
        this.printButton = document.getElementById("btn-print");

        this.saveButton?.addEventListener("click", () => this.save(false));
        this.submitButton?.addEventListener("click", () => this.save(true));
        this.clearButton?.addEventListener("click", () => this.clearInvoice(true));
        this.printButton?.addEventListener("click", () => this.print());
        this.render();
    },

    async addItem(itemCode, options = {}) {
        const existing = PharmacyPOS.state.items.find(row => row.item_code === itemCode && (!options.batch_no || row.batch_no === options.batch_no));
        if (existing) {
            existing.box_qty = flt(existing.box_qty) + flt(options.box_qty || 1);
            existing.unit_qty = flt(existing.unit_qty) + flt(options.unit_qty || 0);
            this.recalculateRow(existing);
            this.selectBestBatch(existing);
            DeliveryManager.recalculateFee();
            this.render();
            return existing;
        }

        PharmacyPOS.setStatus(__("Loading item..."), "working");
        try {
            const warehouse = PharmacyPOS.state.settings.default_warehouse || "";
            const item = await PharmacyAPI.getItem(itemCode, warehouse);
            if (!item) return null;
            const basePrice = flt(item.custom_customer_price || item.customer_price || options.rate || 0);
            const row = {
                item_code: item.item_code || item.name,
                item_name: item.item_name || item.item_code || item.name,
                item_name_ar: item.custom_item_name_ar || item.item_name_ar || "",
                ingredient_summary: item.ingredient_summary || "",
                image: item.image || "",
                stock_uom: item.stock_uom || "",
                actual_qty: flt(item.actual_qty || 0),
                has_batch_no: cint(item.has_batch_no),
                batches: item.batches || [],
                batch_no: options.batch_no || "",
                pack_size: flt(item.custom_pack_size || item.pack_size || options.pack_size || 1) || 1,
                box_only: cint(item.custom_box_only || item.box_only),
                item_origin: item.custom_item_origin || item.item_origin || "",
                customer_price: basePrice,
                price_list_rate: basePrice,
                discount_percentage: flt(options.discount_percentage || 0),
                rate: flt(options.rate || basePrice),
                box_qty: flt(options.box_qty || 1),
                unit_qty: flt(options.unit_qty || 0),
                qty: 0,
                total: 0
            };
            if (!options.rate) this.applyContractPrice(row);
            this.recalculateRow(row);
            this.selectBestBatch(row);
            PharmacyPOS.state.items.push(row);
            DeliveryManager.recalculateFee();
            this.render();
            PharmacyPOS.setStatus(__("Ready"), "success");
            return row;
        } catch (error) {
            console.error(error);
            PharmacyPOS.setStatus(__("Item error"), "error");
            return null;
        }
    },

    applyContractPrice(row) {
        const contract = PharmacyPOS.state.contract;
        row.price_list_rate = flt(row.customer_price || row.price_list_rate || row.rate || 0);
        if (PharmacyPOS.state.orderType !== "Corporate" || !contract) {
            row.discount_percentage = 0;
            row.rate = row.price_list_rate;
            return;
        }
        const origin = String(row.item_origin || "").trim().toLowerCase();
        row.discount_percentage = flt((contract.discounts || {})[origin] || 0);
        row.rate = flt(row.price_list_rate * (1 - row.discount_percentage / 100), 6);
    },

    async recalculateContractPrices() {
        PharmacyPOS.state.items.forEach(row => { this.applyContractPrice(row); this.recalculateRow(row); });
        DeliveryManager.recalculateFee();
        this.render();
    },

    setRowDiscount(row, value) {
        row.discount_percentage = Math.min(100, Math.max(0, flt(value || 0)));
        row.rate = flt(flt(row.price_list_rate || row.customer_price || 0) * (1 - row.discount_percentage / 100), 6);
        this.recalculateRow(row);
    },

    recalculateRow(row) {
        row.box_qty = Math.max(0, flt(row.box_qty));
        row.unit_qty = row.box_only ? 0 : Math.max(0, flt(row.unit_qty));
        row.pack_size = flt(row.pack_size || 1) || 1;
        row.qty = flt(row.box_qty + row.unit_qty / row.pack_size, 6);
        row.total = flt(row.qty * flt(row.rate), 6);
    },

    getProductSubtotal() {
        return flt(PharmacyPOS.state.items.reduce((total, row) => total + flt(row.total || 0), 0), 6);
    },

    getBatchQty(row, batchNo) {
        return flt((row.batches || []).find(item => (item.name || item.batch_no) === batchNo)?.qty || 0, 6);
    },
    getTotalBatchQty(row) { return flt((row.batches || []).reduce((total, batch) => total + flt(batch.qty || 0), 0), 6); },

    selectBestBatch(row) {
        if (!row.has_batch_no) { row.batch_no = ""; row.batch_qty = 0; return; }
        if (!cint(PharmacyPOS.state.settings.auto_batch_selection)) return;
        const batches = (row.batches || []).filter(batch => flt(batch.qty || 0) > 0);
        if (!batches.length) { row.batch_no = ""; row.batch_qty = 0; return; }
        const currentQty = this.getBatchQty(row, row.batch_no);
        if (row.batch_no && currentQty + 1e-9 >= flt(row.qty)) { row.batch_qty = currentQty; return; }
        const selected = batches.find(batch => flt(batch.qty || 0) + 1e-9 >= flt(row.qty)) || batches[0];
        row.batch_no = selected.name || selected.batch_no;
        row.batch_qty = flt(selected.qty || 0, 6);
    },

    expiryWarning(row) {
        const batch = (row.batches || []).find(item => (item.name || item.batch_no) === row.batch_no);
        if (!batch?.expiry_date) return "";
        const expiry = new Date(`${batch.expiry_date}T00:00:00`);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const days = Math.ceil((expiry.getTime() - today.getTime()) / 86400000);
        return days >= 0 && days <= 90 ? `<span class="row-warning" title="Expires in ${days} days">⚠ ${days}d</span>` : "";
    },

    deliveryRowHtml(index) {
        if (PharmacyPOS.state.orderType !== "Home Delivery" || !PharmacyPOS.state.deliveryZone) return "";
        const fee = flt(PharmacyPOS.state.deliveryFee || 0);
        const zone = PharmacyPOS.state.deliveryZone;
        const title = PharmacyPOS.state.isAddOn
            ? "Delivery Service (included in parent invoice)"
            : "Delivery Service";
        return `<tr class="delivery-fee-row ${PharmacyPOS.state.isAddOn ? "is-add-on" : ""}">
            <td>${index}</td>
            <td><strong>${title}</strong><small>${frappe.utils.escape_html(zone.zone_name_ar || zone.zone_name || zone.name || "")}</small></td>
            <td>—</td><td>—</td><td>1</td><td>0</td>
            <td>${format_currency(fee)}</td><td>0</td><td><strong>${format_currency(fee)}</strong></td><td></td>
        </tr>`;
    },

    render() {
        if (!this.body) return;
        DeliveryManager.recalculateFee();
        const items = PharmacyPOS.state.items;
        if (!items.length) {
            const deliveryRow = this.deliveryRowHtml(1);
            this.body.innerHTML = deliveryRow || '<tr class="empty-row"><td colspan="10">Search for an item or scan a barcode.</td></tr>';
            this.updateTotals();
            return;
        }

        const productRows = items.map((row, index) => {
            const batchOptions = row.has_batch_no
                ? `<option value="">Select batch</option>${(row.batches || []).map(batch => {
                    const name = batch.name || batch.batch_no;
                    return `<option value="${frappe.utils.escape_html(name)}" ${name === row.batch_no ? "selected" : ""}>${frappe.utils.escape_html(name)}${batch.expiry_date ? ` - ${frappe.utils.escape_html(batch.expiry_date)}` : ""} - Stock: ${flt(batch.qty || 0, 2)}</option>`;
                }).join("")}`
                : '<option value="">N/A</option>';
            const lowStock = flt(row.actual_qty) <= Math.max(1, flt(row.pack_size)) ? '<span class="row-warning" title="Low stock">Low</span>' : "";
            const subtitle = row.item_name_ar || row.ingredient_summary || row.item_code;
            return `<tr data-row="${index}">
                <td>${index + 1}</td>
                <td><button type="button" class="link-button item-info-link item-hover-target"><strong>${frappe.utils.escape_html(row.item_name)}</strong></button><small class="item-code">${frappe.utils.escape_html(subtitle)}</small>${lowStock}</td>
                <td>${flt(row.actual_qty, 2)}</td>
                <td><div class="batch-cell"><select class="row-batch" ${row.has_batch_no ? "" : "disabled"}>${batchOptions}</select>${this.expiryWarning(row)}</div></td>
                <td><input class="row-boxes" type="number" min="0" step="1" value="${row.box_qty}"></td>
                <td><input class="row-units" type="number" min="0" step="1" value="${row.unit_qty}" ${row.box_only ? "disabled" : ""}></td>
                <td>${format_currency(row.price_list_rate || 0)}</td>
                <td><input class="row-discount" type="number" min="0" max="100" step="0.01" value="${flt(row.discount_percentage || 0, 2)}"></td>
                <td><strong>${format_currency(row.total || 0)}</strong></td>
                <td><button type="button" class="remove-row" title="Remove">×</button></td>
            </tr>`;
        }).join("");
        this.body.innerHTML = productRows + this.deliveryRowHtml(items.length + 1);
        this.bindRowEvents();
        this.updateTotals();
    },

    bindRowEvents() {
        this.body.querySelectorAll("tr[data-row]").forEach(tr => {
            const index = cint(tr.dataset.row);
            const row = PharmacyPOS.state.items[index];
            const updateQty = () => { this.recalculateRow(row); this.selectBestBatch(row); DeliveryManager.recalculateFee(); this.render(); };
            tr.querySelector(".row-boxes")?.addEventListener("change", event => { row.box_qty = flt(event.target.value); updateQty(); });
            tr.querySelector(".row-units")?.addEventListener("change", event => { row.unit_qty = flt(event.target.value); updateQty(); });
            tr.querySelector(".row-discount")?.addEventListener("change", event => { this.setRowDiscount(row, event.target.value); DeliveryManager.recalculateFee(); this.render(); });
            tr.querySelector(".row-batch")?.addEventListener("change", event => { row.batch_no = event.target.value || ""; row.batch_qty = this.getBatchQty(row, row.batch_no); });
            tr.querySelector(".remove-row")?.addEventListener("click", () => { PharmacyPOS.state.items.splice(index, 1); DeliveryManager.recalculateFee(); this.render(); });
            const link = tr.querySelector(".item-info-link");
            link?.addEventListener("click", () => ItemInfoManager.open(row.item_code));
            ItemHoverManager.bind(link, row);
        });
    },

    getTotals() {
        let gross = 0, net = 0;
        PharmacyPOS.state.items.forEach(row => {
            gross += flt(row.qty) * flt(row.price_list_rate || row.rate);
            net += flt(row.total);
        });
        const deliveryFee = PharmacyPOS.state.orderType === "Home Delivery" ? flt(PharmacyPOS.state.deliveryFee || 0) : 0;
        gross += deliveryFee;
        net += deliveryFee;
        return { gross: flt(gross, 6), discount: flt(gross - net, 6), tax: 0, net: flt(net, 6), deliveryFee };
    },

    updateTotals() {
        const totals = this.getTotals();
        document.getElementById("lbl-total").textContent = format_currency(totals.gross);
        document.getElementById("lbl-discount").textContent = format_currency(totals.discount);
        document.getElementById("lbl-tax").textContent = format_currency(totals.tax);
        document.getElementById("lbl-net").textContent = format_currency(totals.net);
        PaymentManager?.updateFromTotal?.(totals.net);
    },

    validate(submit = false) {
        if (!PharmacyPOS.state.items.length) frappe.throw(__("Add at least one item."));
        if (!PharmacyPOS.state.customer) frappe.throw(__("Select Customer."));
        if (PharmacyPOS.state.isAddOn && !PharmacyPOS.state.parentDeliveryInvoice) {
            frappe.throw(__("Parent Delivery Invoice is required in Add-on mode."));
        }
        if (PharmacyPOS.state.orderType === "Corporate") {
            if (!PharmacyPOS.state.contract) frappe.throw(__("Select Pharmacy Contract."));
            if (!PharmacyPOS.state.beneficiary) frappe.throw(__("Select Contract Beneficiary."));
        }
        if (PharmacyPOS.state.orderType === "Home Delivery") DeliveryManager.validate();
        PharmacyPOS.state.items.forEach(row => {
            if (row.qty <= 0) frappe.throw(__("Item quantity must be greater than zero."));
            if (row.discount_percentage < 0 || row.discount_percentage > 100) frappe.throw(__("Discount must be between 0 and 100."));
            if (row.has_batch_no) {
                this.selectBestBatch(row);
                const available = this.getTotalBatchQty(row);
                if (available + 1e-9 < flt(row.qty)) frappe.throw(__("Insufficient batch stock for {0}. Required: {1}, available: {2}.").format(row.item_name, flt(row.qty, 2), flt(available, 2)));
                if (!row.batch_no) frappe.throw(__("No available batch for {0}.").format(row.item_name));
            }
        });
        if (submit) PaymentManager.validateForSubmit();
    },

    buildPayload(submit, options = {}) {
        return {
            submit: submit ? 1 : 0,
            hold: options.hold ? 1 : 0,
            draft_name: PharmacyPOS.state.currentDraftName || "",
            company: PharmacyPOS.state.settings.company || "",
            warehouse: PharmacyPOS.state.settings.default_warehouse || "",
            price_list: PharmacyPOS.state.settings.default_price_list || "",
            update_stock: 1,
            order_type: PharmacyPOS.state.orderType,
            customer: PharmacyPOS.state.customer?.name || "",
            customer_address: PharmacyPOS.state.customerAddress || "",
            pharmacy_contract: PharmacyPOS.state.contract?.name || "",
            contract_beneficiary: PharmacyPOS.state.beneficiary?.name || "",
            delivery_boy: PharmacyPOS.state.deliveryBoy?.name || "",
            is_add_on_delivery_invoice: PharmacyPOS.state.isAddOn ? 1 : 0,
            parent_delivery_invoice: PharmacyPOS.state.parentDeliveryInvoice || "",
            skip_delivery_fee: PharmacyPOS.state.skipDeliveryFee ? 1 : 0,
            payments: PharmacyPOS.state.payments || [],
            loyalty_redemption: PharmacyPOS.state.loyaltyRedemption || {},
            advance_allocations: PharmacyPOS.state.advanceAllocations || [],
            keep_excess_as_credit: PharmacyPOS.state.keepExcessAsCredit ? 1 : 0,
            items: PharmacyPOS.state.items.map(row => ({
                item_code: row.item_code, batch_no: row.batch_no || "", box_qty: row.box_qty, unit_qty: row.unit_qty,
                pack_size: row.pack_size, qty: row.qty, price_list_rate: row.price_list_rate,
                discount_percentage: row.discount_percentage, rate: row.rate
            }))
        };
    },

    async save(submit, options = {}) {
        if (this.saving) return;
        try {
            this.validate(false);
            if (submit) {
                const ready = await PaymentManager.prepareForSubmit();
                if (!ready) return;
                this.validate(true);
            }
            this.saving = true;
            this.toggleButtons(true);
            PharmacyPOS.setStatus(options.hold ? __("Holding...") : (submit ? __("Submitting...") : __("Saving...")), "working");
            const result = await PharmacyAPI.saveInvoice(this.buildPayload(submit, options));
            this.lastInvoice = result;
            PharmacyPOS.state.currentDraftName = result.docstatus === 0 ? result.name : null;
            PharmacyPOS.setStatus(`${result.name} ${options.hold ? __("Held") : (submit ? __("Submitted") : __("Saved"))}`, "success");
            this.printButton.disabled = false;
            frappe.show_alert({
                message: result.is_add_on
                    ? `${result.name} ${__("created as Add-on for")} ${result.parent_delivery_invoice}`
                    : `${result.name} ${options.hold ? __("held") : (submit ? __("submitted") : __("saved"))}`,
                indicator: "green"
            });

            if (submit && result.is_add_on) {
                const cleanUrl = `${window.location.origin}${window.location.pathname}`;
                window.history.replaceState({}, document.title, cleanUrl);

                frappe.msgprint({
                    title: __("Add-on Invoice Created"),
                    indicator: "green",
                    message: `${__("Add-on Invoice")}: <strong>${frappe.utils.escape_html(result.name)}</strong><br>${__("Parent Delivery Invoice")}: <strong>${frappe.utils.escape_html(result.parent_delivery_invoice || "")}</strong><br>${__("No additional delivery fee was added.")}`
                });
            }
            if (flt(result.customer_credit_added || 0) > 0) {
                frappe.msgprint({
                    title: __("Customer Credit Added"),
                    indicator: "green",
                    message: `${__("Invoice")}: <strong>${frappe.utils.escape_html(result.name)}</strong><br>${__("Customer Credit")}: <strong>${format_currency(result.customer_credit_added)}</strong>`
                });
            }

            if (submit && PharmacyPOS.state.autoPrint) this.print();
            if (options.clearAfter || submit) setTimeout(() => this.clearInvoice(false), submit && PharmacyPOS.state.autoPrint ? 1200 : 500);
        } catch (error) {
            console.error(error);
            PharmacyPOS.setStatus(__("Save failed"), "error");
        } finally {
            this.saving = false;
            this.toggleButtons(false);
        }
    },

    toggleButtons(disabled) {
        [this.saveButton, this.submitButton, document.getElementById("btn-hold")].forEach(button => { if (button) button.disabled = disabled; });
    },

    async loadDraft(data) {
        await this.clearInvoice(false);
        PharmacyPOS.state.currentDraftName = data.name;
        await HeaderManager.applyOrderType(data.order_type || "Walk In", true);
        document.getElementById("order-type").value = data.order_type || "Walk In";
        if (data.pharmacy_contract) {
            await HeaderManager.selectContract({ name: data.pharmacy_contract });
            if (data.contract_beneficiary) await HeaderManager.selectBeneficiary({ name: data.contract_beneficiary });
        } else if (data.customer) {
            await CustomerManager.selectCustomer(data.customer);
        }
        if (data.customer_address) {
            document.getElementById("customer-address").value = data.customer_address;
            PharmacyPOS.state.customerAddress = data.customer_address;
            const addressRow = CustomerManager.addressRows.find(row => row.name === data.customer_address) || null;
            await DeliveryManager.selectAddress(addressRow);
        }
        PharmacyPOS.state.items = data.items || [];
        PharmacyPOS.state.payments = data.payments || [];
        PharmacyPOS.state.loyaltyRedemption = data.loyalty_redemption || { points: 0, amount: 0 };
        DeliveryManager.recalculateFee();
        this.render();
        PharmacyPOS.setStatus(`${data.name} ${__("Recalled")}`, "success");
    },

    clearInvoice(confirmClear = false) {
        const action = async () => {
            PharmacyPOS.resetState();
            CustomerManager.clearCustomer();
            DeliveryManager.clear();
            HeaderManager.clearCorporate();
            await HeaderManager.applyOrderType("Walk In", true);
            document.getElementById("order-type").value = "Walk In";
            PaymentManager.reset();
            this.lastInvoice = null;
            this.printButton.disabled = true;
            this.render();
            PharmacyPOS.setStatus(__("Ready"), "neutral");
            if (PharmacyPOS.state.settings.default_customer) {
                await CustomerManager.selectCustomer({
                    name: PharmacyPOS.state.settings.default_customer,
                    customer_name: PharmacyPOS.state.settings.default_customer,
                    mobile_no: ""
                });
            }
            document.getElementById("item-search")?.focus();
        };
        if (confirmClear && PharmacyPOS.state.items.length) frappe.confirm(__("Clear the current invoice?"), action); else return action();
    },

    print() {
        if (!this.lastInvoice?.name) return;
        PrintManager.printInvoice(this.lastInvoice.name, true);
    }
};
