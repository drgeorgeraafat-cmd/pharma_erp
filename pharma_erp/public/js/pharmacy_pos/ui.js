window.PharmacyPOS = {
    state: {
        settings: {},
        orderType: "Walk In",
        customer: null,
        customerAddress: null,
        customerAddresses: [],
        contract: null,
        beneficiary: null,
        deliveryBoy: null,
        deliveryZone: null,
        deliveryFee: 0,
        deliveryFeeRule: "",
        estimatedDeliveryTime: 0,
        deliveryValidationError: "",
        items: [],
        payments: [],
        loyaltyRedemption: { points: 0, amount: 0 },
        advanceAllocations: [],
        paymentContext: null,
        keepExcessAsCredit: false,
        quickCash: true,
        autoPrint: false,
        currentDraftName: null,
        isAddOn: false,
        parentDeliveryInvoice: null,
        skipDeliveryFee: false,
        addOnContext: null,
        fullscreen: false
    },

    async init(container) {
        this.container = container;
        this.render();

        try {
            this.state.settings = await PharmacyAPI.getSettings();
            window.POS_SETTINGS = this.state.settings;
            this.state.quickCash = cint(this.state.settings.quick_cash_default ?? 1) === 1;
            this.state.autoPrint = cint(this.state.settings.auto_print_after_submit || 0) === 1;

            HeaderManager.init();
            CustomerManager.init();
            InvoiceManager.init();
            PaymentManager.init();
            DeliveryManager.init();
            ReturnsManager.init();
            HistoryManager.init();
            ItemInfoManager.init();
            ItemHoverManager.init();
            HoldManager.init();
            PrintManager.init();
            ScreenManager.init();
            ShortcutManager.init();
            SearchManager.init();

            const addOnRoute = this.getAddOnRoute();

            if (addOnRoute.parentInvoice) {
                await this.loadAddOnContext(addOnRoute.parentInvoice);
            } else {
                await HeaderManager.applyOrderType("Walk In", true);

                if (this.state.settings.default_customer) {
                    await CustomerManager.selectCustomer({
                        name: this.state.settings.default_customer,
                        customer_name: this.state.settings.default_customer,
                        mobile_no: ""
                    });
                }
            }

            if (this.state.settings.auto_focus_search) {
                document.getElementById("item-search")?.focus();
            }
        } catch (error) {
            console.error(error);
            const errorMessage =
                error?.message ||
                error?.exc_type ||
                __("Failed to initialize Pharmacy POS.");

            frappe.msgprint({
                title: __("POS Error"),
                message: frappe.utils.escape_html(String(errorMessage)),
                indicator: "red"
            });
        }
    },

    getAddOnRoute() {
        const params = new URLSearchParams(window.location.search || "");
        const enabled = ["1", "true", "yes"].includes(
            String(params.get("add_on") || "").toLowerCase()
        );

        return {
            enabled,
            parentInvoice: enabled ? (params.get("parent") || "").trim() : ""
        };
    },

    async loadAddOnContext(parentInvoice) {
        if (!parentInvoice) {
            frappe.throw(__("Parent Delivery Invoice is required for Add-on mode."));
        }

        PharmacyPOS.setStatus(__("Loading Add-on order..."), "working");
        const context = await PharmacyAPI.getAddOnContext(parentInvoice);

        this.state.isAddOn = true;
        this.state.parentDeliveryInvoice = context.parent_invoice;
        this.state.skipDeliveryFee = true;
        this.state.addOnContext = context;

        await HeaderManager.applyOrderType("Home Delivery", true);

        if (context.customer) {
            await CustomerManager.selectCustomer(context.customer, true);
        }

        if (context.customer_address && context.customer?.name) {
            await CustomerManager.loadAddresses(
                context.customer.name,
                context.customer_address
            );
        }

        PharmacyPOS.state.deliveryBoy = context.delivery_boy || null;
        if (DeliveryManager.input) {
            DeliveryManager.input.value = context.delivery_boy
                ? (context.delivery_boy.employee_name || context.delivery_boy.name)
                : "";
        }

        this.lockAddOnFields();
        this.renderAddOnBanner();
        DeliveryManager.recalculateFee();
        InvoiceManager.render();
        PharmacyPOS.setStatus(__("Add-on mode"), "success");
    },

    lockAddOnFields() {
        if (!this.state.isAddOn) return;

        const orderType = document.getElementById("order-type");
        const address = document.getElementById("customer-address");
        const deliveryBoy = document.getElementById("delivery-boy");

        if (orderType) orderType.disabled = true;
        if (address) address.disabled = true;
        if (deliveryBoy) deliveryBoy.disabled = true;

        CustomerManager.setManualSelectionEnabled(false);
    },

    unlockAddOnFields() {
        const orderType = document.getElementById("order-type");
        const address = document.getElementById("customer-address");
        const deliveryBoy = document.getElementById("delivery-boy");

        if (orderType) orderType.disabled = false;
        if (address) address.disabled = false;
        if (deliveryBoy) deliveryBoy.disabled = false;

        if (window.CustomerManager?.setManualSelectionEnabled) {
            CustomerManager.setManualSelectionEnabled(true);
        }
    },

    renderAddOnBanner() {
        const banner = document.getElementById("add-on-banner");
        if (!banner) return;

        const context = this.state.addOnContext || {};
        banner.classList.toggle("is-hidden", !this.state.isAddOn);
        document.getElementById("pharmacy-pos")?.classList.toggle(
            "is-add-on-mode",
            Boolean(this.state.isAddOn)
        );

        if (!this.state.isAddOn) {
            banner.innerHTML = "";
            return;
        }

        banner.innerHTML = `
            <div>
                <strong>➕ ADD-ON ORDER</strong>
                <span>Parent: ${frappe.utils.escape_html(
                    this.state.parentDeliveryInvoice || ""
                )}</span>
            </div>
            <div class="add-on-banner-meta">
                <span>Original Total: <strong>${format_currency(
                    context.group_grand_total || context.parent_grand_total || 0
                )}</strong></span>
                <span>Current Outstanding: <strong>${format_currency(
                    context.group_outstanding_amount || context.parent_outstanding_amount || 0
                )}</strong></span>
                <span>No additional delivery fee</span>
            </div>
        `;
    },

    render() {
        this.container.empty();
        this.container.append(`
            <div id="pharmacy-pos">
                <div class="pos-command-bar">
                    <div class="pos-command-title">
                        <strong>Pharmacy POS</strong>
                        <span id="pos-print-info">Receipt: Default</span>
                    </div>
                    <div class="pos-command-actions">
                        <button id="btn-reprint" class="secondary-btn">🖨 Reprint</button>
                        <button id="btn-fullscreen" class="secondary-btn">⛶ Full Screen</button>
                    </div>
                </div>

                <div id="add-on-banner" class="add-on-banner is-hidden"></div>

                <header id="header">
                    <div class="header-row header-main-row">
                        <div class="field-group order-type-group">
                            <label>Order Type</label>
                            <select id="order-type">
                                <option value="Walk In">Walk In</option>
                                <option value="Home Delivery">Home Delivery</option>
                                <option value="Corporate">Corporate</option>
                            </select>
                        </div>

                        <div class="field-group customer-code-group">
                            <label>Customer Code</label>
                            <input id="customer-code" type="text" placeholder="Code + Enter" autocomplete="off">
                        </div>

                        <div class="field-group customer-search-group">
                            <label>Customer</label>
                            <div class="autocomplete-wrap">
                                <input id="customer-name" type="text" placeholder="Name, mobile or code (F3)" autocomplete="off">
                                <div id="customer-results" class="autocomplete-results"></div>
                            </div>
                        </div>

                        <div class="field-group mobile-group">
                            <label>Mobile</label>
                            <input id="customer-mobile" type="text" placeholder="Mobile" readonly>
                        </div>

                        <div class="field-group address-group">
                            <label>Address</label>
                            <select id="customer-address"><option value="">Select Address</option></select>
                        </div>

                        <div class="customer-action-buttons">
                            <button id="btn-new-customer" class="secondary-btn" type="button">＋ Customer</button>
                            <button id="btn-add-address" class="secondary-btn" type="button" disabled>＋ Address</button>
                            <button id="btn-history" class="secondary-btn" type="button">📜 History</button>
                        </div>
                    </div>

                    <div id="customer-finance-row" class="customer-finance-row is-hidden">
                        <span>⭐ Loyalty: <strong id="customer-loyalty-points">0</strong></span>
                        <span>💰 Advance: <strong id="customer-advance-total">0.00</strong></span>
                        <span>↩ Credit: <strong id="customer-credit-total">0.00</strong></span>
                    </div>

                    <div id="corporate-row" class="header-row corporate-row is-hidden">
                        <div class="field-group contract-group">
                            <label>Pharmacy Contract</label>
                            <div class="autocomplete-wrap">
                                <input id="contract-search" type="text" placeholder="Search contract" autocomplete="off">
                                <div id="contract-results" class="autocomplete-results"></div>
                            </div>
                        </div>
                        <div class="field-group beneficiary-group">
                            <label>Contract Beneficiary</label>
                            <div class="autocomplete-wrap">
                                <input id="beneficiary-search" type="text" placeholder="Employee name or code" autocomplete="off" disabled>
                                <div id="beneficiary-results" class="autocomplete-results"></div>
                            </div>
                        </div>
                        <div class="field-group employee-code-group">
                            <label>Employee Code</label>
                            <input id="employee-code" type="text" readonly>
                        </div>
                        <div class="field-group billing-type-group">
                            <label>Billing Type</label>
                            <input id="billing-type" type="text" readonly>
                        </div>
                    </div>

                    <div id="delivery-row" class="header-row delivery-row is-hidden">
                        <div class="field-group delivery-boy-group">
                            <label>Delivery Boy <small>(Optional)</small></label>
                            <div class="autocomplete-wrap">
                                <input id="delivery-boy" type="text" placeholder="Unassigned - assign later" autocomplete="off">
                                <div id="delivery-boy-results" class="autocomplete-results"></div>
                            </div>
                        </div>
                        <div class="delivery-zone-summary">
                            <span>Zone: <strong id="delivery-zone-label">Select Address</strong></span>
                            <span>Fee: <strong id="delivery-fee-label">0.00</strong></span>
                            <span>ETA: <strong id="delivery-eta-label">—</strong></span>
                            <span id="delivery-rule-label" class="delivery-rule-badge">—</span>
                        </div>
                        <div id="delivery-warning" class="delivery-warning is-hidden"></div>
                    </div>
                </header>

                <main id="content">
                    <section id="search-panel">
                        <div class="panel-title-row">
                            <div class="panel-title">🔍 Item Search</div>
                            <button id="btn-toggle-search" class="icon-btn" title="Collapse search">⇤</button>
                        </div>
                        <input id="item-search" type="text" placeholder="Barcode, item, Arabic name or active ingredient (F2)" autocomplete="off">
                        <div id="search-results"></div>
                    </section>

                    <section id="invoice-panel">
                        <div class="panel-title-row">
                            <div class="panel-title">🧾 Invoice</div>
                            <div id="invoice-status" class="status-badge">Ready</div>
                        </div>
                        <div class="table-wrap">
                            <table id="invoice-table">
                                <thead>
                                    <tr>
                                        <th>#</th><th>Item</th><th>Stock</th><th>Batch</th><th>Boxes</th><th>Units</th><th>Price</th><th>Disc %</th><th>Total</th><th></th>
                                    </tr>
                                </thead>
                                <tbody id="invoice-body"></tbody>
                            </table>
                        </div>
                    </section>
                </main>

                <footer id="footer">
                    <div class="footer-info">
                        <span>Total <strong id="lbl-total">0.00</strong></span>
                        <span>Discount <strong id="lbl-discount">0.00</strong></span>
                        <span>Tax <strong id="lbl-tax">0.00</strong></span>
                        <span>Net <strong id="lbl-net">0.00</strong></span>
                    </div>

                    <div id="payment-area" class="payment-area">
                        <label id="quick-cash-label" class="quick-cash-toggle">
                            <input id="quick-cash" type="checkbox">
                            <span class="quick-cash-box">✓</span>
                            <span id="quick-cash-text">Quick Cash ON</span>
                        </label>
                        <button id="btn-payment" class="payment-btn">💳 Payment (F4)</button>
                        <button id="btn-keep-change" class="secondary-btn keep-change-btn" type="button">💰 Keep Change</button>
                        <button id="btn-add-balance" class="secondary-btn add-balance-btn" type="button">＋ Add Balance</button>
                        <span>Paid <strong id="lbl-paid">0.00</strong></span>
                        <span>Remaining <strong id="lbl-remaining">0.00</strong></span>
                        <span><span id="change-label-text">Change</span> <strong id="lbl-change">0.00</strong></span>
                    </div>

                    <div class="footer-options">
                        <label class="quick-check"><input id="auto-print" type="checkbox"> Print after Submit</label>
                    </div>

                    <div class="footer-buttons">
                        <button id="btn-return" class="secondary-btn">↩ Return (F10)</button>
                        <button id="btn-hold" class="secondary-btn">⏸ Hold (F7)</button>
                        <button id="btn-recall" class="secondary-btn">📂 Recall (F8)</button>
                        <button id="btn-clear" class="secondary-btn">Clear</button>
                        <button id="btn-save" class="secondary-btn">💾 Save Draft</button>
                        <button id="btn-submit" class="primary-btn">✅ Submit (F12)</button>
                        <button id="btn-print" class="secondary-btn" disabled>🖨 Print</button>
                    </div>
                </footer>
            </div>
            <div id="item-info-drawer" class="item-info-drawer is-hidden"></div>
            <div id="item-hover-card" class="item-hover-card is-hidden"></div>
        `);

        document.getElementById("btn-toggle-search")?.addEventListener("click", () => {
            document.getElementById("pharmacy-pos")?.classList.toggle("search-collapsed");
        });
    },

    setStatus(message, type = "neutral") {
        const badge = document.getElementById("invoice-status");
        if (!badge) return;
        badge.textContent = message;
        badge.className = `status-badge status-${type}`;
    },

    resetState() {
        this.state.orderType = "Walk In";
        this.state.customer = null;
        this.state.customerAddress = null;
        this.state.customerAddresses = [];
        this.state.contract = null;
        this.state.beneficiary = null;
        this.state.deliveryBoy = null;
        this.state.deliveryZone = null;
        this.state.deliveryFee = 0;
        this.state.deliveryFeeRule = "";
        this.state.estimatedDeliveryTime = 0;
        this.state.deliveryValidationError = "";
        this.state.items = [];
        this.state.payments = [];
        this.state.loyaltyRedemption = { points: 0, amount: 0 };
        this.state.advanceAllocations = [];
        this.state.paymentContext = null;
        this.state.keepExcessAsCredit = false;
        this.state.quickCash = cint(this.state.settings.quick_cash_default ?? 1) === 1;
        this.state.autoPrint = cint(this.state.settings.auto_print_after_submit || 0) === 1;
        this.state.currentDraftName = null;
        this.state.isAddOn = false;
        this.state.parentDeliveryInvoice = null;
        this.state.skipDeliveryFee = false;
        this.state.addOnContext = null;
        this.unlockAddOnFields();
        this.renderAddOnBanner();
    }
};
