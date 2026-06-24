window.DeliveryManager = {
    timer: null,

    init() {
        this.input = document.getElementById("delivery-boy");
        this.results = document.getElementById("delivery-boy-results");
        this.zoneLabel = document.getElementById("delivery-zone-label");
        this.feeLabel = document.getElementById("delivery-fee-label");
        this.etaLabel = document.getElementById("delivery-eta-label");
        this.ruleLabel = document.getElementById("delivery-rule-label");
        this.warning = document.getElementById("delivery-warning");

        this.input?.addEventListener("input", () => {
            PharmacyPOS.state.deliveryBoy = null;
            clearTimeout(this.timer);
            this.timer = setTimeout(() => this.search(this.input.value), 250);
        });
        this.input?.addEventListener("focus", () => this.search(this.input.value));
        document.addEventListener("click", event => {
            if (!event.target.closest(".delivery-boy-group")) this.results.innerHTML = "";
        });
        this.renderZoneSummary();
    },

    async search(txt = "") {
        try { this.render(await PharmacyAPI.searchDeliveryEmployees((txt || "").trim()) || []); }
        catch (error) { console.error(error); }
    },

    render(rows) {
        const unassigned = `<button type="button" class="autocomplete-option" data-unassigned="1"><strong>Unassigned</strong><small>Assign later from Delivery Board</small></button>`;
        this.results.innerHTML = unassigned + rows.map(row => `
            <button type="button" class="autocomplete-option" data-employee="${frappe.utils.escape_html(row.name)}">
                <strong>${frappe.utils.escape_html(row.employee_name || row.name)}</strong>
                <small>${frappe.utils.escape_html([row.name, row.cell_number].filter(Boolean).join(" • "))}</small>
            </button>`).join("");
        this.results.querySelector("[data-unassigned]")?.addEventListener("click", () => this.clear());
        this.results.querySelectorAll("[data-employee]").forEach((button, index) => button.addEventListener("click", () => this.select(rows[index])));
    },

    select(row) {
        PharmacyPOS.state.deliveryBoy = row;
        this.input.value = row.employee_name || row.name;
        this.results.innerHTML = "";
    },

    async selectAddress(row) {
        if (PharmacyPOS.state.orderType !== "Home Delivery") {
            this.clearZone();
            return;
        }
        if (!row) {
            this.clearZone();
            PharmacyPOS.state.deliveryValidationError = "Select a delivery address.";
            this.renderZoneSummary();
            InvoiceManager?.render?.();
            return;
        }
        if (!row.delivery_zone) {
            this.clearZone();
            PharmacyPOS.state.deliveryValidationError = "The selected address has no Delivery Zone.";
            this.renderZoneSummary();
            InvoiceManager?.render?.();
            return;
        }

        let zone = row;
        if (row.delivery_fee === undefined || row.delivery_fee === null) {
            const details = await PharmacyAPI.getDeliveryZoneDetails(row.delivery_zone);
            zone = Object.assign({}, row, details || {});
        }
        PharmacyPOS.state.deliveryZone = {
            name: zone.delivery_zone || zone.name,
            zone_name: zone.zone_name || "",
            zone_name_ar: zone.zone_name_ar || "",
            is_active: cint(zone.zone_is_active ?? zone.is_active ?? 1),
            warehouse: zone.zone_warehouse || zone.warehouse || "",
            delivery_fee: flt(zone.delivery_fee || 0),
            small_order_threshold: flt(zone.small_order_threshold || 0),
            small_order_delivery_fee: flt(zone.small_order_delivery_fee || 0),
            minimum_order_amount: flt(zone.minimum_order_amount || 0),
            free_delivery_above: flt(zone.free_delivery_above || 0),
            estimated_time_mins: cint(zone.estimated_time_mins || 0)
        };
        this.recalculateFee();
        InvoiceManager?.render?.();
    },

    onOrderTypeChange(orderType) {
        if (orderType !== "Home Delivery") {
            this.clearZone();
            return;
        }
        const row = (PharmacyPOS.state.customerAddresses || []).find(item => item.name === PharmacyPOS.state.customerAddress) || null;
        this.selectAddress(row);
    },

    recalculateFee() {
        const state = PharmacyPOS.state;
        state.deliveryValidationError = "";
        if (state.orderType !== "Home Delivery" || !state.deliveryZone) {
            state.deliveryFee = 0;
            state.deliveryFeeRule = "";
            state.estimatedDeliveryTime = 0;
            this.renderZoneSummary();
            return 0;
        }

        const zone = state.deliveryZone;
        const warehouse = state.settings.default_warehouse || "";
        if (!zone.is_active) state.deliveryValidationError = "The selected Delivery Zone is inactive.";
        if (!state.deliveryValidationError && zone.warehouse && warehouse && zone.warehouse !== warehouse) {
            state.deliveryValidationError = `Zone belongs to ${zone.warehouse}, not ${warehouse}.`;
        }

        const subtotal = InvoiceManager?.getProductSubtotal?.() || 0;
        state.estimatedDeliveryTime = cint(zone.estimated_time_mins || 0);

        if (state.isAddOn && state.skipDeliveryFee) {
            state.deliveryFee = 0;
            state.deliveryFeeRule = "Add-on – No Additional Delivery Fee";
            this.renderZoneSummary();
            return 0;
        }

        if (subtotal <= 0) {
            state.deliveryFee = 0;
            state.deliveryFeeRule = "Add Items";
        } else if (flt(zone.minimum_order_amount) > 0 && subtotal + 1e-9 < flt(zone.minimum_order_amount)) {
            state.deliveryFee = flt(zone.small_order_delivery_fee || zone.delivery_fee || 0);
            state.deliveryFeeRule = "Below Minimum";
            state.deliveryValidationError = `Minimum order is ${format_currency(zone.minimum_order_amount)}.`;
        } else if (flt(zone.free_delivery_above) > 0 && subtotal + 1e-9 >= flt(zone.free_delivery_above)) {
            state.deliveryFee = 0;
            state.deliveryFeeRule = "Free Delivery";
        } else if (flt(zone.small_order_threshold) > 0 && subtotal + 1e-9 < flt(zone.small_order_threshold)) {
            state.deliveryFee = flt(zone.small_order_delivery_fee || zone.delivery_fee || 0);
            state.deliveryFeeRule = "Small Order";
        } else {
            state.deliveryFee = flt(zone.delivery_fee || 0);
            state.deliveryFeeRule = "Standard Delivery";
        }
        this.renderZoneSummary();
        return state.deliveryFee;
    },

    renderZoneSummary() {
        const state = PharmacyPOS.state;
        const zone = state.deliveryZone;
        if (this.zoneLabel) this.zoneLabel.textContent = zone ? (zone.zone_name_ar || zone.zone_name || zone.name) : "Select Address";
        if (this.feeLabel) this.feeLabel.textContent = format_currency(state.deliveryFee || 0);
        if (this.etaLabel) this.etaLabel.textContent = state.estimatedDeliveryTime ? `${state.estimatedDeliveryTime} min` : "—";
        if (this.ruleLabel) {
            this.ruleLabel.textContent = state.deliveryFeeRule || "—";
            const isFree = state.deliveryFeeRule === "Free Delivery";
            const isAddOn = String(state.deliveryFeeRule || "").startsWith("Add-on");
            this.ruleLabel.className = `delivery-rule-badge ${isFree ? "is-free" : ""} ${isAddOn ? "is-add-on" : ""}`;
        }
        if (this.warning) {
            this.warning.textContent = state.deliveryValidationError || "";
            this.warning.classList.toggle("is-hidden", !state.deliveryValidationError);
        }
    },

    validate() {
        if (PharmacyPOS.state.orderType !== "Home Delivery") return;
        if (!PharmacyPOS.state.customerAddress) frappe.throw(__("Select a delivery address."));
        if (!PharmacyPOS.state.deliveryZone) frappe.throw(__("The selected address has no Delivery Zone."));
        this.recalculateFee();
        if (PharmacyPOS.state.deliveryValidationError) frappe.throw(__(PharmacyPOS.state.deliveryValidationError));
    },

    clearZone() {
        PharmacyPOS.state.deliveryZone = null;
        PharmacyPOS.state.deliveryFee = 0;
        PharmacyPOS.state.deliveryFeeRule = "";
        PharmacyPOS.state.estimatedDeliveryTime = 0;
        PharmacyPOS.state.deliveryValidationError = "";
        this.renderZoneSummary();
    },

    clear() {
        PharmacyPOS.state.deliveryBoy = null;
        if (this.input) this.input.value = "";
        if (this.results) this.results.innerHTML = "";
    }
};
