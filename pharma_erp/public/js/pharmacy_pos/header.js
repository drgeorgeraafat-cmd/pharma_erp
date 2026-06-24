window.HeaderManager = {
    timers: {},

    init() {
        this.orderType = document.getElementById("order-type");
        this.corporateRow = document.getElementById("corporate-row");
        this.deliveryRow = document.getElementById("delivery-row");
        this.contractInput = document.getElementById("contract-search");
        this.contractResults = document.getElementById("contract-results");
        this.beneficiaryInput = document.getElementById("beneficiary-search");
        this.beneficiaryResults = document.getElementById("beneficiary-results");
        this.employeeCode = document.getElementById("employee-code");
        this.billingType = document.getElementById("billing-type");

        this.orderType?.addEventListener("change", () => this.applyOrderType(this.orderType.value));
        this.contractInput?.addEventListener("input", () => this.debounce("contract", () => this.searchContracts(this.contractInput.value)));
        this.contractInput?.addEventListener("focus", () => this.searchContracts(this.contractInput.value));
        this.beneficiaryInput?.addEventListener("input", () => this.debounce("beneficiary", () => this.searchBeneficiaries(this.beneficiaryInput.value)));
        this.beneficiaryInput?.addEventListener("focus", () => {
            if (PharmacyPOS.state.contract) this.searchBeneficiaries(this.beneficiaryInput.value);
        });

        document.addEventListener("click", event => {
            if (!event.target.closest(".contract-group")) this.contractResults.innerHTML = "";
            if (!event.target.closest(".beneficiary-group")) this.beneficiaryResults.innerHTML = "";
        });
    },

    debounce(key, callback, delay = 250) {
        clearTimeout(this.timers[key]);
        this.timers[key] = setTimeout(callback, delay);
    },

    async applyOrderType(orderType, initial = false) {
        PharmacyPOS.state.orderType = orderType;
        this.orderType.value = orderType;

        const isCorporate = orderType === "Corporate";
        const isDelivery = orderType === "Home Delivery";
        this.corporateRow.classList.toggle("is-hidden", !isCorporate);
        this.deliveryRow.classList.toggle("is-hidden", !isDelivery);
        CustomerManager.setManualSelectionEnabled(!isCorporate);

        if (!isCorporate) {
            this.clearCorporate();
            PaymentManager.setEnabled(true);
        } else {
            CustomerManager.clearCustomer();
            PaymentManager.setEnabled(true);
        }

        if (!isDelivery) DeliveryManager.clear();
        PaymentManager.setOrderType(orderType, PharmacyPOS.state.contract?.billing_type || "");
        DeliveryManager.onOrderTypeChange(orderType);
        InvoiceManager?.render?.();

        if (!initial) PharmacyPOS.setStatus(orderType, "neutral");
    },

    clearCorporate() {
        PharmacyPOS.state.contract = null;
        PharmacyPOS.state.beneficiary = null;
        if (this.contractInput) this.contractInput.value = "";
        if (this.beneficiaryInput) {
            this.beneficiaryInput.value = "";
            this.beneficiaryInput.disabled = true;
        }
        if (this.employeeCode) this.employeeCode.value = "";
        if (this.billingType) this.billingType.value = "";
        if (this.contractResults) this.contractResults.innerHTML = "";
        if (this.beneficiaryResults) this.beneficiaryResults.innerHTML = "";
        InvoiceManager?.recalculateContractPrices?.();
    },

    async searchContracts(txt = "") {
        try { this.renderContracts(await PharmacyAPI.searchContracts((txt || "").trim()) || []); }
        catch (error) { console.error(error); }
    },

    renderContracts(rows) {
        if (!rows.length) {
            this.contractResults.innerHTML = '<div class="autocomplete-empty">No contracts found</div>';
            return;
        }
        this.contractResults.innerHTML = rows.map(row => {
            const title = row.contract_name || row.customer_name || row.name;
            const subtitle = [row.customer_name, row.billing_type].filter(Boolean).join(" • ");
            return `<button type="button" class="autocomplete-option" data-contract="${frappe.utils.escape_html(row.name)}"><strong>${frappe.utils.escape_html(title)}</strong><small>${frappe.utils.escape_html(subtitle)}</small></button>`;
        }).join("");
        this.contractResults.querySelectorAll("[data-contract]").forEach((button, index) => button.addEventListener("click", () => this.selectContract(rows[index])));
    },

    async selectContract(row) {
        const details = await PharmacyAPI.getContractDetails(row.name);
        PharmacyPOS.state.contract = Object.assign({}, row, details || {});
        PharmacyPOS.state.beneficiary = null;
        this.contractInput.value = PharmacyPOS.state.contract.contract_name || PharmacyPOS.state.contract.customer_name || row.name;
        this.contractResults.innerHTML = "";
        this.beneficiaryInput.value = "";
        this.beneficiaryInput.disabled = false;
        this.employeeCode.value = "";
        this.billingType.value = PharmacyPOS.state.contract.billing_type || "";
        CustomerManager.clearCustomer();
        PaymentManager.setOrderType("Corporate", PharmacyPOS.state.contract.billing_type || "");
        await InvoiceManager.recalculateContractPrices();
        this.beneficiaryInput.focus();
    },

    async searchBeneficiaries(txt = "") {
        const contract = PharmacyPOS.state.contract;
        if (!contract) return;
        try { this.renderBeneficiaries(await PharmacyAPI.searchBeneficiaries((txt || "").trim(), contract.name) || []); }
        catch (error) { console.error(error); }
    },

    renderBeneficiaries(rows) {
        if (!rows.length) {
            this.beneficiaryResults.innerHTML = '<div class="autocomplete-empty">No beneficiaries found</div>';
            return;
        }
        this.beneficiaryResults.innerHTML = rows.map(row => {
            const title = row.customer_name || row.customer || row.name;
            const subtitle = [row.employee_code, row.card_number, row.external_id].filter(Boolean).join(" • ");
            return `<button type="button" class="autocomplete-option" data-beneficiary="${frappe.utils.escape_html(row.name)}"><strong>${frappe.utils.escape_html(title)}</strong><small>${frappe.utils.escape_html(subtitle)}</small></button>`;
        }).join("");
        this.beneficiaryResults.querySelectorAll("[data-beneficiary]").forEach((button, index) => button.addEventListener("click", () => this.selectBeneficiary(rows[index])));
    },

    async selectBeneficiary(row) {
        const details = await PharmacyAPI.getBeneficiaryDetails(row.name);
        PharmacyPOS.state.beneficiary = Object.assign({}, row, details || {});
        this.beneficiaryInput.value = PharmacyPOS.state.beneficiary.customer_name || row.customer_name || row.customer || row.name;
        this.beneficiaryResults.innerHTML = "";
        this.employeeCode.value = PharmacyPOS.state.beneficiary.employee_code || row.name;

        const contract = PharmacyPOS.state.contract;
        if (contract.billing_type === "Cash Discount") {
            await CustomerManager.selectCustomer({
                name: PharmacyPOS.state.beneficiary.customer,
                customer_name: PharmacyPOS.state.beneficiary.customer_name || row.customer_name || row.customer,
                mobile_no: PharmacyPOS.state.beneficiary.mobile_no || ""
            }, true);
            PaymentManager.setEnabled(true);
        } else {
            await CustomerManager.selectCustomer({
                name: contract.customer,
                customer_name: contract.customer_name || contract.contract_name || contract.customer,
                mobile_no: ""
            }, true);
            PaymentManager.setEnabled(false);
        }
        PaymentManager.setOrderType("Corporate", contract.billing_type || "");
        await InvoiceManager.recalculateContractPrices();
        document.getElementById("item-search")?.focus();
    }
};
