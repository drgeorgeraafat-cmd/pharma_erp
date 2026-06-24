window.CustomerManager = {
    timer: null,
    addressRows: [],

    init() {
        this.codeInput = document.getElementById("customer-code");
        this.input = document.getElementById("customer-name");
        this.mobile = document.getElementById("customer-mobile");
        this.results = document.getElementById("customer-results");
        this.address = document.getElementById("customer-address");
        this.newCustomerButton = document.getElementById("btn-new-customer");
        this.addAddressButton = document.getElementById("btn-add-address");
        this.historyButton = document.getElementById("btn-history");
        this.financeRow = document.getElementById("customer-finance-row");
        this.loyaltyPoints = document.getElementById("customer-loyalty-points");
        this.advanceTotal = document.getElementById("customer-advance-total");
        this.creditTotal = document.getElementById("customer-credit-total");

        this.codeInput?.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                event.preventDefault();
                this.selectByCode(this.codeInput.value);
            }
        });
        this.codeInput?.addEventListener("blur", () => {
            const typed = this.normalizeCode(this.codeInput.value);
            const selected = this.normalizeCode(PharmacyPOS.state.customer?.custom_customer_code || "");
            if (typed && typed !== selected && !PharmacyPOS.state.customer) this.selectByCode(typed, false);
        });
        this.input?.addEventListener("input", () => {
            if (PharmacyPOS.state.orderType === "Corporate") return;
            clearTimeout(this.timer);
            this.timer = setTimeout(() => this.search(this.input.value), 220);
        });
        this.input?.addEventListener("focus", () => {
            if (PharmacyPOS.state.orderType !== "Corporate") this.search(this.input.value);
        });
        this.address?.addEventListener("change", () => {
            const addressName = this.address.value || "";
            PharmacyPOS.state.customerAddress = addressName || null;
            const row = this.addressRows.find(item => item.name === addressName) || null;
            DeliveryManager.selectAddress(row);
        });
        this.newCustomerButton?.addEventListener("click", () => this.openNewCustomerDialog());
        this.addAddressButton?.addEventListener("click", () => this.openAddressDialog());
        this.historyButton?.addEventListener("click", () => HistoryManager.open());
        document.addEventListener("click", event => {
            if (!event.target.closest(".customer-search-group")) this.results.innerHTML = "";
        });
    },

    setManualSelectionEnabled(enabled) {
        [this.codeInput, this.input].forEach(input => {
            if (!input) return;
            input.readOnly = !enabled;
            input.classList.toggle("is-readonly", !enabled);
        });
        document.querySelector(".customer-code-group")?.classList.toggle("is-hidden", !enabled);
        this.newCustomerButton?.classList.toggle("is-hidden", !enabled);
        this.addAddressButton?.classList.toggle("is-hidden", !enabled);
        this.input.placeholder = enabled ? "Name, mobile or code (F3)" : "Selected automatically from contract";
    },


    normalizeCode(value) {
        const raw = String(value || "").trim();
        return /^\d+$/.test(raw) ? raw.padStart(6, "0") : raw;
    },

    async selectByCode(value, showMessage = true) {
        const code = this.normalizeCode(value);
        if (this.codeInput) this.codeInput.value = code;
        if (!code || PharmacyPOS.state.orderType === "Corporate") return;
        try {
            const customer = await PharmacyAPI.getCustomerByCode(code);
            if (customer) {
                await this.selectCustomer(customer);
                document.getElementById("item-search")?.focus();
                return;
            }
            if (showMessage) {
                frappe.msgprint({
                    title: __("Customer Code Not Found"),
                    indicator: "orange",
                    message: `${__("No customer was found with code")} <strong>${frappe.utils.escape_html(code)}</strong>.<br>${__("Use + Customer to register a new customer.")}`
                });
            }
        } catch (error) { console.error(error); }
    },

    async search(txt = "") {
        try { this.render(await PharmacyAPI.searchCustomer((txt || "").trim()) || [], txt); }
        catch (error) { console.error(error); }
    },

    render(rows, searchText = "") {
        const createButton = PharmacyPOS.state.orderType !== "Corporate"
            ? `<button type="button" class="autocomplete-option create-customer-option"><strong>＋ ${__("Create New Customer")}</strong><small>${frappe.utils.escape_html(searchText || "")}</small></button>`
            : "";
        if (!rows.length) {
            this.results.innerHTML = `<div class="autocomplete-empty">${__("No customers found")}</div>${createButton}`;
            this.results.querySelector(".create-customer-option")?.addEventListener("click", () => this.openNewCustomerDialog(searchText));
            return;
        }
        this.results.innerHTML = rows.map(row => `
            <button type="button" class="autocomplete-option" data-customer="${frappe.utils.escape_html(row.name)}">
                <strong>${frappe.utils.escape_html(row.customer_name || row.name)}</strong>
                <small>${frappe.utils.escape_html([row.custom_customer_code, row.mobile_no, row.name].filter(Boolean).join(" • "))}</small>
            </button>`).join("") + createButton;
        this.results.querySelectorAll("[data-customer]").forEach((button, index) => button.addEventListener("click", () => this.selectCustomer(rows[index])));
        this.results.querySelector(".create-customer-option")?.addEventListener("click", () => this.openNewCustomerDialog(searchText));
    },

    async selectCustomer(customer, keepReadonly = false) {
        if (!customer?.name) return;
        if (!customer.custom_customer_code) {
            try {
                const result = await PharmacyAPI.ensureCustomerCode(customer.name);
                customer.custom_customer_code = result?.customer_code || "";
            } catch (error) { console.error(error); }
        }
        PharmacyPOS.state.customer = customer;
        this.codeInput.value = customer.custom_customer_code || "";
        this.input.value = customer.customer_name || customer.name || "";
        this.mobile.value = customer.mobile_no || "";
        this.results.innerHTML = "";
        this.addAddressButton.disabled = false;
        if (!keepReadonly && PharmacyPOS.state.orderType !== "Corporate") this.setManualSelectionEnabled(true);
        await Promise.all([this.loadAddresses(customer.name), PaymentManager.loadCustomerContext(customer.name)]);
    },

    async loadAddresses(customer, selectAddress = "") {
        this.address.innerHTML = '<option value="">Select Address</option>';
        this.addressRows = [];
        PharmacyPOS.state.customerAddresses = [];
        PharmacyPOS.state.customerAddress = null;
        DeliveryManager.clearZone();
        if (!customer) return;
        try {
            const rows = await PharmacyAPI.getCustomerAddresses(customer) || [];
            this.addressRows = rows;
            PharmacyPOS.state.customerAddresses = rows;
            rows.forEach(row => {
                const option = document.createElement("option");
                option.value = row.name;
                const zoneLabel = row.zone_name_ar || row.zone_name || row.delivery_zone || "";
                option.textContent = [row.address_title, row.address_line1, row.city, zoneLabel].filter(Boolean).join(" - ");
                if (row.delivery_zone && !cint(row.zone_is_active ?? 1)) option.disabled = true;
                this.address.appendChild(option);
            });
            const target = selectAddress || (rows.length === 1 ? rows[0].name : "");
            if (target) {
                const selected = rows.find(row => row.name === target);
                if (selected) {
                    this.address.value = selected.name;
                    PharmacyPOS.state.customerAddress = selected.name;
                    DeliveryManager.selectAddress(selected);
                }
            }
        } catch (error) { console.error(error); }
    },

    newCustomerDialogFields(prefill = "") {
        const homeDelivery = PharmacyPOS.state.orderType === "Home Delivery";
        const looksLikeMobile = /^\+?[0-9\s-]{7,}$/.test((prefill || "").trim());
        return [
            { fieldtype: "Section Break", label: __("Customer Details") },
            { fieldtype: "Data", fieldname: "customer_name", label: __("Customer Name"), reqd: 1, default: looksLikeMobile ? "" : prefill },
            { fieldtype: "Column Break" },
            { fieldtype: "Data", fieldname: "mobile_no", label: __("Mobile Number"), reqd: 1, default: looksLikeMobile ? prefill : "" },
            { fieldtype: "Section Break", label: __("Delivery Address") },
            { fieldtype: "Data", fieldname: "address_title", label: __("Address Title"), default: __("Home") },
            { fieldtype: "Data", fieldname: "address_line1", label: __("Address Line 1"), reqd: homeDelivery ? 1 : 0 },
            { fieldtype: "Data", fieldname: "address_line2", label: __("Address Line 2") },
            { fieldtype: "Column Break" },
            { fieldtype: "Data", fieldname: "city", label: __("City"), reqd: homeDelivery ? 1 : 0, default: "Cairo" },
            { fieldtype: "Data", fieldname: "state", label: __("State / Governorate") },
            { fieldtype: "Data", fieldname: "pincode", label: __("Postal Code") },
            { fieldtype: "Link", fieldname: "country", label: __("Country"), options: "Country", reqd: 1, default: "Egypt" },
            { fieldtype: "Link", fieldname: "delivery_zone", label: __("Delivery Zone"), options: "Delivery Zone", reqd: homeDelivery ? 1 : 0, get_query: () => ({ filters: { is_active: 1 } }) }
        ];
    },

    openNewCustomerDialog(prefill = "") {
        if (PharmacyPOS.state.orderType === "Corporate") return;
        const dialog = new frappe.ui.Dialog({
            title: __("New Customer"),
            fields: this.newCustomerDialogFields(prefill),
            primary_action_label: __("Create and Select"),
            primary_action: async values => {
                try {
                    dialog.get_primary_btn().prop("disabled", true);
                    const result = await PharmacyAPI.createPosCustomer({
                        ...values,
                        require_delivery_zone: PharmacyPOS.state.orderType === "Home Delivery" ? 1 : 0
                    });
                    dialog.hide();
                    await this.selectCustomer(result.customer);
                    if (result.address) await this.loadAddresses(result.customer.name, result.address);
                    frappe.show_alert({
                        message: result.created ? `${__("Customer created")}: ${result.customer_code || ""}` : __("Existing customer selected by mobile number"),
                        indicator: result.created ? "green" : "orange"
                    });
                    document.getElementById("item-search")?.focus();
                } catch (error) { console.error(error); }
                finally { dialog.get_primary_btn().prop("disabled", false); }
            }
        });
        dialog.show();
    },

    openAddressDialog() {
        const customer = PharmacyPOS.state.customer;
        if (!customer) {
            frappe.msgprint(__("Select a customer first."));
            return;
        }
        const homeDelivery = PharmacyPOS.state.orderType === "Home Delivery";
        const dialog = new frappe.ui.Dialog({
            title: `${__("Add Address")}: ${customer.customer_name || customer.name}`,
            fields: [
                { fieldtype: "Data", fieldname: "address_title", label: __("Address Title"), default: __("Home") },
                { fieldtype: "Data", fieldname: "address_line1", label: __("Address Line 1"), reqd: 1 },
                { fieldtype: "Data", fieldname: "address_line2", label: __("Address Line 2") },
                { fieldtype: "Column Break" },
                { fieldtype: "Data", fieldname: "city", label: __("City"), reqd: 1, default: "Cairo" },
                { fieldtype: "Data", fieldname: "state", label: __("State / Governorate") },
                { fieldtype: "Data", fieldname: "pincode", label: __("Postal Code") },
                { fieldtype: "Link", fieldname: "country", label: __("Country"), options: "Country", reqd: 1, default: "Egypt" },
                { fieldtype: "Link", fieldname: "delivery_zone", label: __("Delivery Zone"), options: "Delivery Zone", reqd: homeDelivery ? 1 : 0, get_query: () => ({ filters: { is_active: 1 } }) }
            ],
            primary_action_label: __("Save Address"),
            primary_action: async values => {
                try {
                    dialog.get_primary_btn().prop("disabled", true);
                    const result = await PharmacyAPI.addPosCustomerAddress({
                        ...values,
                        customer: customer.name,
                        phone: customer.mobile_no || this.mobile.value || "",
                        require_delivery_zone: homeDelivery ? 1 : 0
                    });
                    dialog.hide();
                    await this.loadAddresses(customer.name, result.address);
                    frappe.show_alert({ message: __("Address added"), indicator: "green" });
                } catch (error) { console.error(error); }
                finally { dialog.get_primary_btn().prop("disabled", false); }
            }
        });
        dialog.show();
    },

    updateFinanceSummary(context) {
        PharmacyPOS.state.paymentContext = context || null;
        this.financeRow?.classList.toggle("is-hidden", !context);
        if (!context) return;
        const isDefaultCustomer = PharmacyPOS.state.customer?.name === PharmacyPOS.state.settings.default_customer;
        this.loyaltyPoints.closest("span")?.classList.toggle("is-hidden", isDefaultCustomer);
        this.loyaltyPoints.textContent = isDefaultCustomer ? 0 : flt(context.loyalty?.available_points || 0, 2);
        this.advanceTotal.textContent = format_currency(context.advance_total || 0);
        this.creditTotal.textContent = format_currency(context.credit_total || 0);
        PaymentManager?.syncKeepChangeUI?.();
    },

    clearCustomer() {
        PharmacyPOS.state.customer = null;
        PharmacyPOS.state.customerAddress = null;
        PharmacyPOS.state.customerAddresses = [];
        PharmacyPOS.state.paymentContext = null;
        PharmacyPOS.state.payments = [];
        PharmacyPOS.state.loyaltyRedemption = { points: 0, amount: 0 };
        PharmacyPOS.state.advanceAllocations = [];
        this.addressRows = [];
        if (this.codeInput) this.codeInput.value = "";
        if (this.input) this.input.value = "";
        if (this.mobile) this.mobile.value = "";
        if (this.results) this.results.innerHTML = "";
        if (this.address) this.address.innerHTML = '<option value="">Select Address</option>';
        if (this.addAddressButton) this.addAddressButton.disabled = true;
        this.financeRow?.classList.add("is-hidden");
        DeliveryManager?.clearZone?.();
        PaymentManager?.refreshSummary?.();
    }
};
