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
        const requestedSource = options.batch_no || options.retail_price_lot || "";
        const requestedMode = requestedSource || options.stock_source_mode === "manual"
            ? "manual"
            : "auto";
        const existing = !options.force_new_line
            ? PharmacyPOS.state.items.find(row => {
                const rowSource = row.batch_no || row.retail_price_lot || "";
                return row.item_code === itemCode
                    && (row.stock_source_mode || "auto") === requestedMode
                    && rowSource === requestedSource;
            })
            : null;

        if (existing) {
            const incrementBoxes = Object.prototype.hasOwnProperty.call(options, "box_qty")
                ? flt(options.box_qty)
                : (this.canSupplyFullBox(existing) ? 1 : 0);
            const incrementUnits = Object.prototype.hasOwnProperty.call(options, "unit_qty")
                ? flt(options.unit_qty)
                : 0;
            existing.box_qty = flt(existing.box_qty) + incrementBoxes;
            existing.unit_qty = flt(existing.unit_qty) + incrementUnits;
            this.recalculateRow(existing);
            this.selectBestBatch(existing);
            DeliveryManager.recalculateFee();
            this.render();
            if (!incrementBoxes && !incrementUnits) this.focusUnits(existing);
            return existing;
        }

        PharmacyPOS.setStatus(__("Loading item..."), "working");
        try {
            const warehouse = PharmacyPOS.state.settings.default_warehouse || "";
            const item = await PharmacyAPI.getItem(itemCode, warehouse);
            if (!item) return null;
            const basePrice = flt(item.custom_customer_price || item.customer_price || options.rate || 0);
            const row = {
                row_key: Math.random().toString(36).slice(2, 12),
                item_code: item.item_code || item.name,
                item_name: item.item_name || item.item_code || item.name,
                item_name_ar: item.custom_item_name_ar || item.item_name_ar || "",
                ingredient_summary: item.ingredient_summary || "",
                image: item.image || "",
                stock_uom: item.stock_uom || "",
                actual_qty: flt(item.actual_qty || 0),
                has_batch_no: cint(item.has_batch_no),
                batches: item.batches || [],
                retail_lots: item.retail_lots || [],
                stock_source_mode: requestedMode,
                batch_no: options.batch_no || "",
                retail_price_lot: options.retail_price_lot || "",
                pack_size: flt(item.custom_pack_size || item.pack_size || options.pack_size || 1) || 1,
                box_only: cint(item.custom_box_only || item.box_only),
                item_origin: item.custom_item_origin || item.item_origin || "",
                general_customer_price: basePrice,
                customer_price: basePrice,
                batch_price: 0,
                price_source: "Item Customer Price",
                price_integrity_error: 0,
                source_allocations: [],
                source_error: "",
                mixed_source_price: 0,
                price_list_rate: basePrice,
                discount_percentage: flt(options.discount_percentage || 0),
                rate: flt(options.rate || basePrice),
                box_qty: 0,
                unit_qty: flt(options.unit_qty || 0),
                qty: 0,
                total: 0,
                focus_units: 0
            };

            if (Object.prototype.hasOwnProperty.call(options, "box_qty")) {
                row.box_qty = flt(options.box_qty);
            } else {
                row.box_qty = this.canSupplyFullBox(row) ? 1 : 0;
                row.focus_units = row.box_qty ? 0 : 1;
            }

            if (!options.rate) this.applyContractPrice(row);
            this.recalculateRow(row);
            this.selectBestBatch(row);
            PharmacyPOS.state.items.push(row);
            DeliveryManager.recalculateFee();
            this.render();
            PharmacyPOS.setStatus(__("Ready"), "success");
            if (row.focus_units) this.focusUnits(row);
            return row;
        } catch (error) {
            console.error(error);
            PharmacyPOS.setStatus(__("Item error"), "error");
            return null;
        }
    },

    applyContractPrice(row, preserveDiscount = false) {
        const contract = PharmacyPOS.state.contract;
        row.price_list_rate = flt(
            row.customer_price
            || row.price_list_rate
            || row.rate
            || 0
        );

        if (PharmacyPOS.state.orderType !== "Corporate" || !contract) {
            if (!preserveDiscount) row.discount_percentage = 0;
            row.rate = flt(
                row.price_list_rate
                * (1 - flt(row.discount_percentage || 0) / 100),
                6
            );
            return;
        }

        const origin = String(row.item_origin || "").trim().toLowerCase();
        row.discount_percentage = flt(
            (contract.discounts || {})[origin]
            || 0
        );
        row.rate = flt(
            row.price_list_rate
            * (1 - row.discount_percentage / 100),
            6
        );
    },

    async recalculateContractPrices() {
        PharmacyPOS.state.items.forEach(row => {
            this.applySelectedBatchPrice(row, false);
            this.recalculateRow(row);
        });
        DeliveryManager.recalculateFee();
        this.render();
    },

    setRowDiscount(row, value) {
        row.discount_percentage = Math.min(100, Math.max(0, flt(value || 0)));
        row.rate = flt(flt(row.price_list_rate || row.customer_price || 0) * (1 - row.discount_percentage / 100), 6);
        this.recalculateRow(row);
    },

    recalculateRow(row) {
        row.box_qty = Math.max(0, Math.round(flt(row.box_qty)));
        row.unit_qty = row.box_only ? 0 : Math.max(0, Math.round(flt(row.unit_qty)));
        row.pack_size = flt(row.pack_size || 1) || 1;
        row.qty = flt(row.box_qty + row.unit_qty / row.pack_size, 6);
        row.total = flt(row.qty * flt(row.rate), 6);
    },

    getProductSubtotal() {
        return flt(PharmacyPOS.state.items.reduce((total, row) => total + flt(row.total || 0), 0), 6);
    },

    getSources(row) {
        if (row.has_batch_no) {
            return (row.batches || []).filter(source => flt(source.qty || 0) > 0).map(source => ({
                ...source,
                source_type: "batch",
                source_name: source.name || source.batch_no,
                available_qty: flt(source.qty || 0),
                customer_price: flt(source.customer_price || 0)
            }));
        }
        return (row.retail_lots || []).filter(source => flt(source.available_qty || 0) > 0).map(source => ({
            ...source,
            source_type: "retail_lot",
            source_name: source.name,
            available_qty: flt(source.available_qty || 0),
            customer_price: flt(source.retail_price || source.customer_price || 0)
        }));
    },

    selectedSourceName(row) {
        return row.has_batch_no ? (row.batch_no || "") : (row.retail_price_lot || "");
    },

    getSelectedSource(row) {
        const name = this.selectedSourceName(row);
        return this.getSources(row).find(source => source.source_name === name) || null;
    },

    getTotalSourceQty(row) {
        return flt(this.getSources(row).reduce((total, source) => total + flt(source.available_qty), 0), 6);
    },

    canSupplyFullBox(row) {
        const sources = this.getSources(row);
        if (!sources.length) return flt(row.actual_qty || 0) >= 1;
        if ((row.stock_source_mode || "auto") === "manual") {
            return flt(this.getSelectedSource(row)?.available_qty || 0) >= 1;
        }
        return sources.some(source => flt(source.available_qty) >= 1);
    },

    getSourceAllocations(row) {
        const allSources = this.getSources(row);
        const selected = this.getSelectedSource(row);
        const manual = (row.stock_source_mode || "auto") === "manual";
        const sources = manual
            ? (selected ? [selected] : [])
            : allSources;
        const available = new Map(sources.map(source => [source.source_name, flt(source.available_qty)]));
        const allocated = new Map(sources.map(source => [source.source_name, 0]));
        let remainingBoxes = Math.max(0, Math.round(flt(row.box_qty)));

        sources.forEach(source => {
            if (remainingBoxes <= 0) return;
            const name = source.source_name;
            const fullBoxes = Math.floor(Math.max(0, available.get(name) || 0));
            if (!fullBoxes) return;
            const qty = Math.min(fullBoxes, remainingBoxes);
            allocated.set(name, flt((allocated.get(name) || 0) + qty, 6));
            available.set(name, flt((available.get(name) || 0) - qty, 6));
            remainingBoxes -= qty;
        });

        let remainingUnitQty = flt(flt(row.unit_qty || 0) / (flt(row.pack_size || 1) || 1), 6);
        sources.forEach(source => {
            if (remainingUnitQty <= 1e-9) return;
            const name = source.source_name;
            const qty = Math.min(flt(available.get(name) || 0), remainingUnitQty);
            if (qty <= 0) return;
            allocated.set(name, flt((allocated.get(name) || 0) + qty, 6));
            available.set(name, flt((available.get(name) || 0) - qty, 6));
            remainingUnitQty = flt(remainingUnitQty - qty, 6);
        });

        const allocations = sources
            .filter(source => flt(allocated.get(source.source_name) || 0) > 1e-9)
            .map(source => ({
                source,
                qty: flt(allocated.get(source.source_name), 6)
            }));

        return {
            allocations,
            remainingBoxes,
            remainingUnitQty,
            manual,
            sourceMissing: manual && !selected
        };
    },

    applySelectedBatchPrice(row, preserveDiscount = true) {
        const generalPrice = flt(
            row.general_customer_price
            || row.customer_price
            || row.price_list_rate
            || row.rate
            || 0
        );
        row.general_customer_price = generalPrice;
        row.source_error = "";
        row.price_integrity_error = 0;

        const sources = this.getSources(row);
        if (!sources.length) {
            row.source_allocations = [];
            row.mixed_source_price = 0;
            row.customer_price = generalPrice;
            row.price_source = "Item Customer Price";
            this.applyContractPrice(row, preserveDiscount);
            return;
        }

        const pricing = this.getSourceAllocations(row);
        row.source_allocations = pricing.allocations;
        if (pricing.sourceMissing) {
            row.source_error = __("Select a valid stock source.");
        } else if (pricing.remainingBoxes > 0) {
            const selectedSource = this.getSelectedSource(row);
            if (pricing.manual && selectedSource) {
                const availableBoxes = Math.floor(Math.max(0, flt(selectedSource.available_qty || 0)));
                row.source_error = __("Selected stock source has {0} complete box(es), but {1} were requested. Reduce Boxes, choose Auto allocation, or add another line.")
                    .format(availableBoxes, Math.max(0, Math.round(flt(row.box_qty || 0))));
            } else {
                row.source_error = __("Requested complete boxes cannot be supplied from the available stock sources. Reduce Boxes or add another line.");
            }
        } else if (pricing.remainingUnitQty > 1e-9) {
            row.source_error = __("Insufficient loose-unit stock.");
        }

        const hasIntegrityError = pricing.allocations.some(allocation =>
            cint(allocation.source.price_integrity_error || 0)
            || flt(allocation.source.customer_price || 0) <= 0
        );
        row.price_integrity_error = cint(hasIntegrityError);

        const allocatedQty = flt(pricing.allocations.reduce(
            (total, allocation) => total + flt(allocation.qty || 0), 0
        ), 6);

        if (row.price_integrity_error) {
            row.customer_price = 0;
            row.price_source = "Stock Source Price Error";
            row.mixed_source_price = 0;
            this.applyContractPrice(row, preserveDiscount);
            return;
        }

        if (allocatedQty <= 1e-9) {
            const previewSource = this.getSelectedSource(row) || sources[0];
            row.customer_price = flt(previewSource?.customer_price || generalPrice);
            row.price_source = previewSource?.source_type === "batch"
                ? (previewSource.price_source || "Batch Price")
                : "Internal Retail Price Lot";
            row.mixed_source_price = 0;
            this.applyContractPrice(row, preserveDiscount);
            return;
        }

        const grossAmount = pricing.allocations.reduce(
            (total, allocation) => total
                + flt(allocation.qty || 0)
                * flt(allocation.source.customer_price || 0),
            0
        );
        row.customer_price = flt(grossAmount / allocatedQty, 6);
        const distinctPrices = [...new Set(pricing.allocations.map(
            allocation => flt(allocation.source.customer_price || 0, 6)
        ))];
        row.mixed_source_price = cint(distinctPrices.length > 1);
        row.price_source = row.mixed_source_price
            ? "Mixed Stock Source Prices"
            : (pricing.allocations[0].source.source_type === "batch"
                ? (pricing.allocations[0].source.price_source || "Batch Price")
                : "Internal Retail Price Lot");
        this.applyContractPrice(row, preserveDiscount);
    },

    selectBestBatch(row) {
        const sources = this.getSources(row);
        if (!sources.length) {
            row.stock_source_mode = "auto";
            row.batch_no = "";
            row.retail_price_lot = "";
            this.applySelectedBatchPrice(row, true);
            this.recalculateRow(row);
            return;
        }
        if ((row.stock_source_mode || "auto") !== "manual") {
            row.stock_source_mode = "auto";
            row.batch_no = "";
            row.retail_price_lot = "";
        }
        this.applySelectedBatchPrice(row, true);
        // Stock-source pricing may differ from the Item's current general price.
        // Recalculate immediately so totals never show the source-price difference
        // as a false customer discount.
        this.recalculateRow(row);
    },

    formatStock(row) {
        const qty = Math.max(0, flt(row.actual_qty || 0));
        const packSize = flt(row.pack_size || 1) || 1;
        const boxes = Math.floor(qty + 1e-9);
        const units = Math.max(0, Math.round((qty - boxes) * packSize));
        return `${boxes} ${boxes === 1 ? __("Box") : __("Boxes")} + ${units} ${units === 1 ? __("Unit") : __("Units")}`;
    },

    allocationSummary(row) {
        const allocations = row.source_allocations || [];
        if (row.source_error) return `<small class="source-error">${frappe.utils.escape_html(row.source_error)}</small>`;
        if (!allocations.length) {
            const hasTrackedSources = this.getSources(row).length > 0;
            if (!hasTrackedSources && !row.has_batch_no) {
                return `<small>${__("Item Customer Price applies to all stock")}</small>`;
            }
            return `<small>${(row.stock_source_mode || "auto") === "auto" ? __("Auto allocation • FEFO / oldest lot") : __("Manual source")}</small>`;
        }
        const details = allocations.map(allocation => {
            const source = allocation.source;
            const name = source.source_name;
            const units = flt(allocation.qty) * flt(row.pack_size || 1);
            return `${name}: ${flt(allocation.qty, 3)} Box (${flt(units, 2)} Units) @ ${format_currency(source.customer_price || 0)}`;
        });
        const heading = allocations.length > 1
            ? `${__("Auto")}: ${allocations.length} ${__("sources")}`
            : details[0];
        return `<details class="source-allocation-details" ${allocations.length > 1 ? "" : "open"}><summary>${frappe.utils.escape_html(heading)}</summary>${allocations.length > 1 ? `<small>${details.map(detail => frappe.utils.escape_html(detail)).join("<br>")}</small>` : ""}</details>`;
    },

    expiryWarning(row) {
        const source = this.getSelectedSource(row);
        if (!source?.expiry_date) return "";
        const expiry = new Date(`${source.expiry_date}T00:00:00`);
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
            this.body.innerHTML = deliveryRow || '<tr class="empty-row"><td colspan="10">Search for an item, Batch, Price Lot, Barcode, or QR.</td></tr>';
            this.updateTotals();
            return;
        }

        const productRows = items.map((row, index) => {
            const sources = this.getSources(row);
            const selectedName = this.selectedSourceName(row);
            const sourceOptions = sources.length
                ? `<option value="">${frappe.utils.escape_html(__("Auto allocation"))}</option>${sources.map(source => {
                    const name = source.source_name;
                    const typeLabel = source.source_type === "batch" ? __("Batch") : __("Lot");
                    const price = flt(source.customer_price || 0);
                    const integrityLabel = cint(source.price_integrity_error)
                        ? ` - ${__("PRICE ERROR")}`
                        : ` - ${format_currency(price)}`;
                    const expiry = source.expiry_date ? ` - ${source.expiry_date}` : "";
                    return `<option value="${frappe.utils.escape_html(name)}" ${name === selectedName ? "selected" : ""}>${frappe.utils.escape_html(typeLabel)} ${frappe.utils.escape_html(name)}${expiry} - ${__("Stock")}: ${flt(source.available_qty || 0, 3)}${integrityLabel}</option>`;
                }).join("")}`
                : '<option value="">N/A</option>';
            const lowStock = flt(row.actual_qty) < 1 ? '<span class="row-warning" title="Less than one full box">Loose only</span>' : "";
            const subtitle = row.item_name_ar || row.ingredient_summary || row.item_code;
            const priceHtml = row.mixed_source_price
                ? `<strong>${__("Mixed")}</strong><small>${format_currency(row.price_list_rate || 0)} ${__("effective")}</small>`
                : format_currency(row.price_list_rate || 0);
            return `<tr data-row="${index}" data-row-key="${frappe.utils.escape_html(row.row_key || "")}">
                <td>${index + 1}</td>
                <td><button type="button" class="link-button item-info-link item-hover-target"><strong>${frappe.utils.escape_html(row.item_name)}</strong></button><small class="item-code">${frappe.utils.escape_html(subtitle)}</small>${lowStock}</td>
                <td><span title="${flt(row.actual_qty, 3)} Box">${frappe.utils.escape_html(this.formatStock(row))}</span></td>
                <td><div class="batch-cell stock-source-cell"><select class="row-source" ${sources.length ? "" : "disabled"}>${sourceOptions}</select>${this.expiryWarning(row)}${this.allocationSummary(row)}</div></td>
                <td><input class="row-boxes" type="number" min="0" step="1" value="${row.box_qty}"></td>
                <td><input class="row-units" type="number" min="0" step="1" value="${row.unit_qty}" ${row.box_only ? "disabled" : ""}></td>
                <td>${priceHtml}</td>
                <td><input class="row-discount" type="number" min="0" max="100" step="0.01" value="${flt(row.discount_percentage || 0, 2)}"></td>
                <td><strong>${format_currency(row.total || 0)}</strong></td>
                <td><div class="row-actions"><button type="button" class="new-row" title="Add same item on a new line">＋</button><button type="button" class="remove-row" title="Remove">×</button></div></td>
            </tr>`;
        }).join("");
        this.body.innerHTML = productRows + this.deliveryRowHtml(items.length + 1);
        this.bindRowEvents();
        this.updateTotals();
    },

    focusUnits(row) {
        window.setTimeout(() => {
            const key = CSS.escape(row.row_key || "");
            this.body?.querySelector(`tr[data-row-key="${key}"] .row-units`)?.focus();
        }, 50);
    },

    bindRowEvents() {
        this.body.querySelectorAll("tr[data-row]").forEach(tr => {
            const index = cint(tr.dataset.row);
            const row = PharmacyPOS.state.items[index];
            const updateQty = () => {
                this.recalculateRow(row);
                this.selectBestBatch(row);
                DeliveryManager.recalculateFee();
                this.render();
            };
            tr.querySelector(".row-boxes")?.addEventListener("change", event => { row.box_qty = flt(event.target.value); updateQty(); });
            tr.querySelector(".row-units")?.addEventListener("change", event => { row.unit_qty = flt(event.target.value); updateQty(); });
            tr.querySelector(".row-discount")?.addEventListener("change", event => { this.setRowDiscount(row, event.target.value); DeliveryManager.recalculateFee(); this.render(); });
            tr.querySelector(".row-source")?.addEventListener("change", event => {
                const sourceName = event.target.value || "";
                row.stock_source_mode = sourceName ? "manual" : "auto";
                if (row.has_batch_no) {
                    row.batch_no = sourceName;
                    row.retail_price_lot = "";
                } else {
                    row.retail_price_lot = sourceName;
                    row.batch_no = "";
                }
                const selectedSource = this.getSelectedSource(row);
                if (sourceName && flt(selectedSource?.available_qty || 0) < 1 && flt(row.box_qty) > 0) {
                    row.box_qty = 0;
                    row.focus_units = 1;
                }
                this.applySelectedBatchPrice(row, true);
                this.recalculateRow(row);
                DeliveryManager.recalculateFee();
                this.render();
                if (row.focus_units) {
                    row.focus_units = 0;
                    this.focusUnits(row);
                }
            });
            tr.querySelector(".new-row")?.addEventListener("click", () => this.addItem(row.item_code, {
                force_new_line: true,
                box_qty: 0,
                unit_qty: 0,
                discount_percentage: row.discount_percentage
            }));
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
            this.selectBestBatch(row);
            const sources = this.getSources(row);
            if (sources.length) {
                const pricing = this.getSourceAllocations(row);
                if (row.source_error || pricing.remainingBoxes > 0 || pricing.remainingUnitQty > 1e-9) {
                    frappe.throw(`${row.item_name}: ${row.source_error || __("Stock source allocation is incomplete.")}`);
                }
                const allocated = flt(pricing.allocations.reduce((total, allocation) => total + flt(allocation.qty || 0), 0), 6);
                if (allocated + 1e-9 < flt(row.qty)) {
                    frappe.throw(__("Insufficient tracked stock for {0}. Required: {1}, allocated: {2}.").format(row.item_name, flt(row.qty, 3), flt(allocated, 3)));
                }
                if ((row.stock_source_mode || "auto") === "manual" && !this.selectedSourceName(row)) {
                    frappe.throw(__("Select a Batch or Retail Price Lot for {0}.").format(row.item_name));
                }
                if (cint(row.price_integrity_error)) {
                    frappe.throw(__("A selected stock source for {0} has a missing Customer Price.").format(row.item_name));
                }
            }
            if (flt(row.price_list_rate || 0) <= 0) {
                frappe.throw(__("Customer Price is missing for {0}.").format(row.item_name));
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
                item_code: row.item_code,
                row_key: row.row_key || "",
                stock_source_mode: row.stock_source_mode || "auto",
                batch_no: row.stock_source_mode === "manual" ? (row.batch_no || "") : "",
                retail_price_lot: row.stock_source_mode === "manual" ? (row.retail_price_lot || "") : "",
                box_qty: row.box_qty,
                unit_qty: row.unit_qty,
                pack_size: row.pack_size,
                qty: row.qty,
                price_list_rate: row.price_list_rate,
                discount_percentage: row.discount_percentage,
                rate: row.rate
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
