window.PharmacyAPI = {
    call(method, args = {}) {
        return new Promise((resolve, reject) => {
            frappe.call({
                method,
                args,
                freeze: false,
                callback(r) { resolve(r.message); },
                error(err) {
                    console.error(err);
                    frappe.msgprint({
                        title: __("Error"),
                        message: err.message || __("Server Error"),
                        indicator: "red"
                    });
                    reject(err);
                }
            });
        });
    },

    getSettings() { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_settings"); },
    searchItems(txt, warehouse = "") { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.search_items", { txt, warehouse }); },
    getItem(item_code, warehouse = "") { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_item", { item_code, warehouse }); },
    getReturnItem(item_code, warehouse = "") { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_return_item", { item_code, warehouse }); },
    searchCustomer(txt = "") { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.search_customer", { txt }); },
    getCustomerByCode(customer_code) { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_customer_by_code", { customer_code }); },
    ensureCustomerCode(customer) { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.ensure_customer_code", { customer }); },
    createPosCustomer(data) { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.create_pos_customer", { data: JSON.stringify(data) }); },
    addPosCustomerAddress(data) { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.add_pos_customer_address", { data: JSON.stringify(data) }); },
    searchDeliveryEmployees(txt = "") { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.search_delivery_employees", { txt }); },
    searchContracts(txt = "") { return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.search_contracts", { txt }); },
    searchBeneficiaries(txt = "", pharmacy_contract = "") {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.search_beneficiaries", { txt, pharmacy_contract });
    },
    getContractDetails(pharmacy_contract) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_contract_details", { pharmacy_contract });
    },
    getBeneficiaryDetails(beneficiary) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_beneficiary_details", { beneficiary });
    },
    getCustomerAddresses(customer) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_customer_addresses", { customer });
    },
    getDeliveryZoneDetails(delivery_zone) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_delivery_zone_details", { delivery_zone });
    },
    getCustomerHistory(customer, limit = 20) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_customer_history", { customer, limit });
    },
    getInvoiceHistoryDetails(invoice) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_invoice_history_details", { invoice });
    },
    getCustomerPurchasedItems(customer, days = 0, limit = 200) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_customer_purchased_items", { customer, days, limit });
    },
    getItemMovement(item_code, warehouse = "", limit = 20, offset = 0) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_item_movement", { item_code, warehouse, limit, offset });
    },
    getPaymentModes(company = "") {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_payment_modes", { company });
    },
    getCustomerPaymentContext(customer, company = "") {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_customer_payment_context", { customer, company });
    },
    createCustomerBalance(data) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.create_customer_balance", { data: JSON.stringify(data) });
    },
    getAddOnContext(parent_invoice) {
        return this.call(
            "pharma_erp.pharma_erp.page.pharmacy_pos.api.get_add_on_context",
            { parent_invoice }
        );
    },
    saveInvoice(data) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.save_invoice", { data: JSON.stringify(data) });
    },
    searchHeldInvoices(limit = 50) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.search_held_invoices", { limit });
    },
    getHeldInvoice(invoice) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_held_invoice", { invoice });
    },
    searchSalesInvoices(txt = "", customer = "", limit = 20) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.search_sales_invoices", { txt, customer, limit });
    },
    getReturnableInvoice(invoice, return_request = "") {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.get_returnable_invoice", { invoice, return_request });
    },
    createSalesReturn(data) {
        return this.call("pharma_erp.pharma_erp.page.pharmacy_pos.api.create_sales_return", { data: JSON.stringify(data) });
    }
};
