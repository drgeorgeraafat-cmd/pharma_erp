window.PaymentManager = {
    enabled: true,
    modes: [],
    net: 0,

    init() {
        this.area = document.getElementById("payment-area");
        this.button = document.getElementById("btn-payment");
        this.quickCash = document.getElementById("quick-cash");
        this.autoPrint = document.getElementById("auto-print");
        this.paidLabel = document.getElementById("lbl-paid");
        this.remainingLabel = document.getElementById("lbl-remaining");
        this.changeLabel = document.getElementById("lbl-change");
        this.changeLabelText = document.getElementById("change-label-text");
        this.keepChangeButton = document.getElementById("btn-keep-change");
        this.addBalanceButton = document.getElementById("btn-add-balance");
        this.quickCashLabel = document.getElementById("quick-cash-label");
        this.quickCashText = document.getElementById("quick-cash-text");

        this.shiftOpen = cint(
            PharmacyPOS.state.settings?.has_open_shift || 0,
        ) === 1;
        this.openShift = PharmacyPOS.state.settings?.open_shift || "";

        if (this.quickCash) this.quickCash.checked = Boolean(PharmacyPOS.state.quickCash);
        if (this.autoPrint) this.autoPrint.checked = Boolean(PharmacyPOS.state.autoPrint);
        this.syncQuickCashUI();
        this.syncShiftGuard();

        this.button?.addEventListener("click", () => this.open());
        this.addBalanceButton?.addEventListener("click", () => this.openAddBalance());
        this.keepChangeButton?.addEventListener("click", () => {
            if (this.isDefaultCashCustomer()) {
                frappe.msgprint(__("Select or create the actual customer before storing change as customer credit."));
                return;
            }
            PharmacyPOS.state.keepExcessAsCredit = !PharmacyPOS.state.keepExcessAsCredit;
            if (PharmacyPOS.state.keepExcessAsCredit) {
                PharmacyPOS.state.quickCash = false;
                this.syncQuickCashUI();
                this.open();
            }
            this.syncKeepChangeUI();
            this.refreshSummary();
        });
        this.quickCash?.addEventListener("change", () => {
            PharmacyPOS.state.quickCash = this.quickCash.checked;
            if (!this.quickCash.checked) PharmacyPOS.state.payments = [];
            this.syncQuickCashUI();
            this.refreshSummary();
        });
        this.autoPrint?.addEventListener("change", () => {
            PharmacyPOS.state.autoPrint = this.autoPrint.checked;
        });
        this.loadModes();
        this.syncKeepChangeUI();
        this.refreshSummary();
    },


    syncShiftGuard() {
        if (this.shiftOpen) {
            this.removeShiftGate();
            return;
        }

        if (this.button) {
            this.button.disabled = true;
            this.button.title = "افتح وردية أولًا";
        }
        if (this.quickCash) this.quickCash.disabled = true;
        if (this.addBalanceButton) this.addBalanceButton.disabled = true;
        if (this.keepChangeButton) this.keepChangeButton.disabled = true;

        this.renderShiftGate();
    },

    renderShiftGate(attempt = 0) {
        const mount =
            this.area?.closest(".layout-main-section") ||
            document.querySelector(
                '[data-page-route="pharmacy-pos"] .layout-main-section',
            ) ||
            document.querySelector(".layout-main-section");

        if (!mount) {
            if (attempt < 20) {
                window.setTimeout(
                    () => this.renderShiftGate(attempt + 1),
                    100,
                );
            }
            return;
        }

        if (document.getElementById("pharmacy-pos-shift-gate")) return;

        mount.style.position = "relative";

        const gate = document.createElement("div");
        gate.id = "pharmacy-pos-shift-gate";
        gate.innerHTML = `
            <div class="pharmacy-pos-shift-gate-card">
                <div class="pharmacy-pos-shift-gate-icon">🔒</div>
                <h2>لا توجد وردية نشطة</h2>
                <p>
                    Pharmacy POS متوقف مؤقتًا حتى يتم فتح وردية جديدة.
                    لن يتم تحميل شاشة البيع أو تسجيل أي فاتورة قبل ربطها بورديتها.
                </p>
                <div class="pharmacy-pos-shift-gate-actions">
                    <button type="button" class="btn btn-primary" data-action="open-shift-page">
                        فتح صفحة إدارة الوردية
                    </button>
                    <button type="button" class="btn btn-default" data-action="reload-pos">
                        تحديث بعد فتح الوردية
                    </button>
                </div>
            </div>
        `;

        if (!document.getElementById("pharmacy-pos-shift-gate-style")) {
            const style = document.createElement("style");
            style.id = "pharmacy-pos-shift-gate-style";
            style.textContent = `
                #pharmacy-pos-shift-gate {
                    position: absolute;
                    inset: 0;
                    z-index: 500;
                    min-height: calc(100vh - 120px);
                    display: flex;
                    align-items: flex-start;
                    justify-content: center;
                    padding: 70px 24px 40px;
                    background: var(--bg-color, #f8f9fa);
                    direction: rtl;
                    text-align: center;
                }
                .pharmacy-pos-shift-gate-card {
                    width: min(560px, 100%);
                    border: 1px solid var(--border-color, #dfe3e8);
                    border-radius: 18px;
                    background: var(--card-bg, #fff);
                    padding: 36px 30px;
                    box-shadow: 0 12px 35px rgba(0, 0, 0, 0.08);
                }
                .pharmacy-pos-shift-gate-icon {
                    font-size: 46px;
                    margin-bottom: 12px;
                }
                .pharmacy-pos-shift-gate-card h2 {
                    margin: 0 0 12px;
                    font-size: 25px;
                    font-weight: 800;
                }
                .pharmacy-pos-shift-gate-card p {
                    margin: 0 auto 24px;
                    max-width: 460px;
                    color: var(--text-muted, #6c757d);
                    line-height: 1.8;
                }
                .pharmacy-pos-shift-gate-actions {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 10px;
                    justify-content: center;
                }
            `;
            document.head.appendChild(style);
        }

        mount.appendChild(gate);

        gate
            .querySelector('[data-action="open-shift-page"]')
            ?.addEventListener("click", () => {
                window.location.href = "/app/pharmacy-shift-management";
            });

        gate
            .querySelector('[data-action="reload-pos"]')
            ?.addEventListener("click", () => {
                window.location.reload();
            });
    },

    removeShiftGate() {
        document.getElementById("pharmacy-pos-shift-gate")?.remove();
    },

    assertOpenShift() {
        if (!this.shiftOpen) {
            frappe.throw(__("لا يمكن البيع بدون وردية مفتوحة. افتح وردية من صفحة إدارة الوردية ثم أعد تحميل Pharmacy POS."));
        }
    },


    isDefaultCashCustomer() {
        return Boolean(PharmacyPOS.state.customer?.name) &&
            PharmacyPOS.state.customer.name === PharmacyPOS.state.settings.default_customer;
    },

    syncKeepChangeUI() {
        const unavailable = !this.enabled || !PharmacyPOS.state.customer || this.isDefaultCashCustomer();
        if (unavailable) PharmacyPOS.state.keepExcessAsCredit = false;
        this.keepChangeButton?.classList.toggle("is-active", Boolean(PharmacyPOS.state.keepExcessAsCredit));
        if (this.keepChangeButton) {
            this.keepChangeButton.disabled = unavailable;
            this.keepChangeButton.textContent = PharmacyPOS.state.keepExcessAsCredit
                ? "✓ Keep Change as Credit"
                : "💰 Keep Change";
        }
        if (this.changeLabelText) {
            this.changeLabelText.textContent = PharmacyPOS.state.keepExcessAsCredit ? "Customer Credit" : "Change";
        }
        if (this.addBalanceButton) {
            this.addBalanceButton.disabled = unavailable;
            this.addBalanceButton.title = unavailable
                ? "Select or create an actual customer first"
                : "Add money to the customer's balance without an invoice";
        }
    },

    syncQuickCashUI() {
        const enabled = Boolean(PharmacyPOS.state.quickCash) && this.enabled;
        if (this.quickCash) this.quickCash.checked = enabled;
        this.quickCashLabel?.classList.toggle("is-active", enabled);
        this.quickCashLabel?.classList.toggle("is-disabled", !this.enabled);
        if (this.quickCashText) this.quickCashText.textContent = enabled ? "Quick Cash ON" : "Quick Cash OFF";
    },

    async loadModes() {
        try { this.modes = await PharmacyAPI.getPaymentModes(PharmacyPOS.state.settings.company || "") || []; }
        catch (error) { console.error(error); this.modes = []; }
    },

    async loadCustomerContext(customer) {
        if (!customer) {
            PharmacyPOS.state.paymentContext = null;
            CustomerManager.updateFinanceSummary(null);
            return;
        }
        try {
            const context = await PharmacyAPI.getCustomerPaymentContext(customer, PharmacyPOS.state.settings.company || "");
            PharmacyPOS.state.paymentContext = context || null;
            CustomerManager.updateFinanceSummary(context || null);
            PharmacyPOS.state.loyaltyRedemption = { points: 0, amount: 0 };
            PharmacyPOS.state.advanceAllocations = [];
            PharmacyPOS.state.payments = [];
            PharmacyPOS.state.keepExcessAsCredit = false;
            this.syncKeepChangeUI();
            this.refreshSummary();
        } catch (error) { console.error(error); }
    },

    setEnabled(enabled) {
        this.enabled = Boolean(enabled) && Boolean(this.shiftOpen);
        if (this.button) {
            this.button.disabled = !this.enabled;
            this.button.title = this.enabled ? "" : "Monthly Claim is charged to the company";
        }
        if (this.quickCash) this.quickCash.disabled = !this.enabled;
        if (!this.enabled) {
            PharmacyPOS.state.payments = [];
            PharmacyPOS.state.loyaltyRedemption = { points: 0, amount: 0 };
            PharmacyPOS.state.advanceAllocations = [];
            PharmacyPOS.state.quickCash = false;
        }
        this.syncQuickCashUI();
        this.syncKeepChangeUI();
        this.refreshSummary();
    },

    setOrderType(orderType, billingType = "") {
        const monthlyClaim = orderType === "Corporate" && billingType === "Monthly Claim";
        this.setEnabled(!monthlyClaim);
        const defaultQuick = orderType === "Walk In" || (orderType === "Corporate" && billingType === "Cash Discount");
        PharmacyPOS.state.quickCash = !monthlyClaim && defaultQuick;
        this.syncQuickCashUI();
        this.refreshSummary();
    },

    updateFromTotal(net) {
        this.net = flt(net || 0, 6);
        this.refreshSummary();
    },

    paymentTotal() {
        return flt((PharmacyPOS.state.payments || []).reduce((total, row) => total + flt(row.amount || 0), 0), 6);
    },
    loyaltyAmount() { return flt(PharmacyPOS.state.loyaltyRedemption?.amount || 0, 6); },
    allocationTotal() {
        return flt((PharmacyPOS.state.advanceAllocations || []).reduce((total, row) => total + flt(row.allocated_amount || 0), 0), 6);
    },
    appliedTotal() { return flt(this.paymentTotal() + this.loyaltyAmount() + this.allocationTotal(), 6); },

    refreshSummary() {
        const applied = this.enabled ? this.appliedTotal() : 0;
        const nonCash = this.loyaltyAmount() + this.allocationTotal();
        const direct = this.paymentTotal();
        const directDue = Math.max(0, this.net - nonCash);
        const remaining = Math.max(0, this.net - applied);
        const change = Math.max(0, direct - directDue);
        if (this.paidLabel) this.paidLabel.textContent = format_currency(applied);
        if (this.remainingLabel) this.remainingLabel.textContent = format_currency(remaining);
        if (this.changeLabel) this.changeLabel.textContent = format_currency(change);
    },

    modeOptions(selected = "") {
        const defaultMode = PharmacyPOS.state.settings.default_mode_of_payment || "Cash";
        return (this.modes || []).map(mode => {
            const value = mode.name;
            const isSelected = value === selected || (!selected && value === defaultMode);
            const suffix = mode.configured ? "" : " (No Account)";
            return `<option value="${frappe.utils.escape_html(value)}" ${isSelected ? "selected" : ""} ${mode.configured ? "" : "disabled"}>${frappe.utils.escape_html(value + suffix)}</option>`;
        }).join("");
    },

    cardTerminals() {
        const mode = (this.modes || []).find(row => row.name === "Credit Card");
        return mode?.terminals || [];
    },

    terminalOptions(selected = "") {
        return [
            `<option value="">${__("Select Terminal")}</option>`,
            ...this.cardTerminals().map(terminal => {
                const label = `${terminal.terminal_name} - ${terminal.bank_label || ""}`;
                return `<option value="${frappe.utils.escape_html(terminal.name)}" ${terminal.name === selected ? "selected" : ""}>${frappe.utils.escape_html(label)}</option>`;
            }),
        ].join("");
    },

    defaultCashMode() {
        return (this.modes || []).find(row => row.type === "Cash" && row.configured)?.name
            || (this.modes || []).find(row => row.name === (PharmacyPOS.state.settings.default_mode_of_payment || "Cash") && row.configured)?.name
            || "";
    },

    async prepareQuickCash() {
        if (!this.enabled || !PharmacyPOS.state.quickCash) return;
        if (!PharmacyPOS.state.customer) frappe.throw(__("Select Customer."));
        if (!PharmacyPOS.state.paymentContext) await this.loadCustomerContext(PharmacyPOS.state.customer.name);
        if (!this.modes.length) await this.loadModes();

        const loyaltyAmount = this.loyaltyAmount(); // Loyalty remains manual only.
        const manualAdvances = (PharmacyPOS.state.advanceAllocations || []).filter(row => row.reference_type === "Payment Entry");
        let remaining = Math.max(0, flt(this.net - loyaltyAmount - manualAdvances.reduce((sum, row) => sum + flt(row.allocated_amount), 0), 6));
        const credits = PharmacyPOS.state.paymentContext?.credits || [];
        const autoCredits = [];
        for (const credit of credits) {
            if (remaining <= 0.009) break;
            const amount = Math.min(remaining, flt(credit.available_amount || 0));
            if (amount > 0) {
                autoCredits.push({
                    reference_type: "Sales Invoice",
                    reference_name: credit.name,
                    available_amount: flt(credit.available_amount || 0),
                    allocated_amount: flt(amount, 6)
                });
                remaining = flt(remaining - amount, 6);
            }
        }
        PharmacyPOS.state.advanceAllocations = [...manualAdvances, ...autoCredits];

        const cashDue = Math.max(0, flt(this.net - loyaltyAmount - this.allocationTotal(), 6));
        const cashMode = this.defaultCashMode();
        if (cashDue > 0.009 && !cashMode) frappe.throw(__("No configured Cash Mode of Payment was found."));
        PharmacyPOS.state.payments = cashDue > 0.009 ? [{ mode_of_payment: cashMode, amount: cashDue }] : [];
        this.refreshSummary();
    },

    requiresFullPayment() {
        const type = PharmacyPOS.state.orderType;
        const billing = PharmacyPOS.state.contract?.billing_type || "";
        return type === "Walk In" || (type === "Corporate" && billing === "Cash Discount");
    },

    async prepareForSubmit() {
        this.assertOpenShift();
        if (!this.enabled) return true;
        if (PharmacyPOS.state.quickCash) {
            await this.prepareQuickCash();
            return true;
        }
        if (this.requiresFullPayment() && this.appliedTotal() + 1e-9 < this.net) {
            await this.open();
            return false;
        }
        return true;
    },

    async openAddBalance() {
        this.assertOpenShift();
        if (!PharmacyPOS.state.customer || this.isDefaultCashCustomer()) {
            frappe.msgprint(__("Select or create the actual customer before adding balance."));
            return;
        }
        if (!this.modes.length) await this.loadModes();

        const dialog = new frappe.ui.Dialog({
            title: __("Add Customer Balance"),
            fields: [
                {
                    fieldtype: "Currency",
                    fieldname: "amount",
                    label: __("Amount"),
                    reqd: 1
                },
                {
                    fieldtype: "Select",
                    fieldname: "mode_of_payment",
                    label: __("Mode of Payment"),
                    options: (this.modes || [])
                        .filter(row => row.configured)
                        .map(row => row.name)
                        .join("\n"),
                    default: PharmacyPOS.state.settings.default_mode_of_payment || "Cash",
                    reqd: 1
                },
                {
                    fieldtype: "Select",
                    fieldname: "card_pos_terminal",
                    label: __("Card POS Terminal"),
                    options: this.cardTerminals().map(row => row.name).join("\n"),
                    depends_on: 'eval:doc.mode_of_payment=="Credit Card"',
                    mandatory_depends_on: 'eval:doc.mode_of_payment=="Credit Card"'
                },
                {
                    fieldtype: "Data",
                    fieldname: "reference_no",
                    label: __("Reference No"),
                    description: __("Optional for cash; recommended for card, wallet or transfer.")
                },
                {
                    fieldtype: "Small Text",
                    fieldname: "remarks",
                    label: __("Notes")
                }
            ],
            primary_action_label: __("Add Balance"),
            primary_action: async values => {
                if (flt(values.amount || 0) <= 0) {
                    frappe.msgprint(__("Enter an amount greater than zero."));
                    return;
                }
                try {
                    dialog.get_primary_btn().prop("disabled", true);
                    const result = await PharmacyAPI.createCustomerBalance({
                        customer: PharmacyPOS.state.customer.name,
                        company: PharmacyPOS.state.settings.company || "",
                        amount: flt(values.amount),
                        mode_of_payment: values.mode_of_payment,
                        card_pos_terminal: values.card_pos_terminal || "",
                        reference_no: values.reference_no || "",
                        remarks: values.remarks || ""
                    });
                    await this.loadCustomerContext(PharmacyPOS.state.customer.name);
                    dialog.hide();
                    frappe.msgprint({
                        title: __("Customer Balance Added"),
                        indicator: "green",
                        message: `${__("Payment Entry")}: <strong>${frappe.utils.escape_html(result.payment_entry)}</strong><br>${__("Amount")}: <strong>${format_currency(result.amount)}</strong>`
                    });
                } catch (error) {
                    console.error(error);
                } finally {
                    dialog.get_primary_btn().prop("disabled", false);
                }
            }
        });
        dialog.show();
    },

    async open() {
        this.assertOpenShift();
        if (!this.enabled) {
            frappe.msgprint(__("Payment is not required for Monthly Claim."));
            return;
        }
        if (!PharmacyPOS.state.customer) {
            frappe.msgprint(__("Select a customer first."));
            return;
        }
        if (!this.modes.length) await this.loadModes();
        if (!PharmacyPOS.state.paymentContext) await this.loadCustomerContext(PharmacyPOS.state.customer.name);

        const context = PharmacyPOS.state.paymentContext || { loyalty: {}, advances: [], credits: [] };
        const dialog = new frappe.ui.Dialog({
            title: __("Payment"),
            size: "extra-large",
            fields: [{ fieldtype: "HTML", fieldname: "payment_html" }],
            primary_action_label: __("Apply Payment"),
            primary_action: () => {
                const values = this.collectDialogValues(dialog);
                PharmacyPOS.state.payments = values.payments;
                PharmacyPOS.state.loyaltyRedemption = values.loyalty;
                PharmacyPOS.state.advanceAllocations = values.allocations;
                PharmacyPOS.state.keepExcessAsCredit = values.keep_excess_as_credit;
                PharmacyPOS.state.quickCash = false;
                this.syncQuickCashUI();
                this.syncKeepChangeUI();
                this.refreshSummary();
                dialog.hide();
            }
        });
        dialog.show();
        const wrapper = dialog.get_field("payment_html").$wrapper;
        wrapper.html(this.paymentDialogHtml(context));
        this.bindPaymentDialog(dialog, context);
    },

    paymentDialogHtml(context) {
        const payments = PharmacyPOS.state.payments?.length ? PharmacyPOS.state.payments : [{ mode_of_payment: PharmacyPOS.state.settings.default_mode_of_payment || "Cash", amount: 0 }];
        const loyalty = context.loyalty || {};
        const currentPoints = flt(PharmacyPOS.state.loyaltyRedemption?.points || 0);
        const sources = [
            ...(context.advances || []).map(row => ({ reference_type: "Payment Entry", reference_name: row.name, date: row.posting_date, available_amount: row.available_amount, label: `Advance ${row.name}` })),
            ...(context.credits || []).map(row => ({ reference_type: "Sales Invoice", reference_name: row.name, date: row.posting_date, available_amount: row.available_amount, label: `Credit Note ${row.name}` }))
        ];
        const existing = new Map((PharmacyPOS.state.advanceAllocations || []).map(row => [`${row.reference_type}:${row.reference_name}`, flt(row.allocated_amount)]));
        const allocationRows = sources.map(row => {
            const amount = existing.get(`${row.reference_type}:${row.reference_name}`) || 0;
            return `<tr class="allocation-row" data-reference-type="${frappe.utils.escape_html(row.reference_type)}" data-reference-name="${frappe.utils.escape_html(row.reference_name)}" data-available="${flt(row.available_amount)}"><td>${frappe.utils.escape_html(row.label)}</td><td>${frappe.utils.escape_html(row.date || "")}</td><td>${format_currency(row.available_amount || 0)}</td><td><input class="allocation-amount form-control" type="number" min="0" max="${flt(row.available_amount)}" step="0.01" value="${amount || ""}"></td></tr>`;
        }).join("");

        return `<div class="payment-dialog-content">
            <div class="payment-section"><div class="payment-section-title"><h5>💳 Payment Methods</h5><button type="button" id="add-payment-row" class="btn btn-sm btn-default">+ Add Method</button></div><table class="table table-bordered compact-table"><thead><tr><th>Mode</th><th>Terminal</th><th>Amount</th><th>Reference</th><th></th></tr></thead><tbody id="payment-rows">${payments.map(row => this.paymentRowHtml(row)).join("")}</tbody></table></div>
            ${loyalty.available_points > 0 ? `<div class="payment-section"><h5>⭐ Loyalty Points <small>(used only when entered here)</small></h5><div class="loyalty-grid"><span>Available: <strong>${flt(loyalty.available_points, 2)}</strong></span><span>Value: <strong>${format_currency(loyalty.available_amount || 0)}</strong></span><label>Points to redeem <input id="redeem-loyalty-points" type="number" min="0" max="${flt(loyalty.available_points)}" step="1" value="${currentPoints}"></label></div></div>` : ""}
            ${allocationRows ? `<div class="payment-section"><h5>💰 Customer Advance / Credit</h5><table class="table table-bordered compact-table"><thead><tr><th>Source</th><th>Date</th><th>Available</th><th>Use</th></tr></thead><tbody>${allocationRows}</tbody></table></div>` : ""}
            ${!this.isDefaultCashCustomer() ? `<div class="payment-section keep-credit-section"><label class="checkbox-label"><input id="keep-excess-credit" type="checkbox" ${PharmacyPOS.state.keepExcessAsCredit ? "checked" : ""}> Keep excess/change as Customer Credit</label><small>The excess amount will be saved as an unallocated customer advance for future invoices.</small></div>` : ""}
            <div class="payment-summary-box"><span>Invoice Net <strong>${format_currency(this.net)}</strong></span><span>Applied <strong id="dialog-applied">0.00</strong></span><span>Remaining <strong id="dialog-remaining">0.00</strong></span><span><span id="dialog-change-title">Change</span> <strong id="dialog-change">0.00</strong></span></div>
        </div>`;
    },

    paymentRowHtml(row = {}) {
        const cardSelected = (row.mode_of_payment || "") === "Credit Card";
        return `<tr class="payment-row"><td><select class="payment-mode form-control">${this.modeOptions(row.mode_of_payment || "")}</select></td><td><select class="payment-terminal form-control" ${cardSelected ? "" : "disabled"}>${this.terminalOptions(row.card_pos_terminal || "")}</select></td><td><input class="payment-amount form-control" type="number" min="0" step="0.01" value="${flt(row.amount || 0) || ""}"></td><td><input class="payment-reference form-control" type="text" value="${frappe.utils.escape_html(row.reference_no || "")}" placeholder="Optional reference"></td><td><button type="button" class="remove-payment-row btn btn-sm btn-danger">×</button></td></tr>`;
    },

    bindPaymentDialog(dialog, context) {
        const root = dialog.get_field("payment_html").$wrapper[0];
        const bindRow = row => {
            const syncTerminal = () => {
                const mode = row.querySelector(".payment-mode")?.value || "";
                const terminal = row.querySelector(".payment-terminal");
                if (!terminal) return;
                terminal.disabled = mode !== "Credit Card";
                if (mode !== "Credit Card") terminal.value = "";
            };
            row.querySelector(".payment-mode")?.addEventListener("change", syncTerminal);
            syncTerminal();
            row.querySelectorAll("input, select").forEach(element => {
                element.addEventListener("input", () => this.recalculateDialog(root, context));
                element.addEventListener("change", () => this.recalculateDialog(root, context));
            });
            row.querySelector(".remove-payment-row")?.addEventListener("click", () => { row.remove(); this.recalculateDialog(root, context); });
        };
        root.querySelectorAll(".payment-row").forEach(bindRow);
        root.querySelectorAll(".allocation-amount, #redeem-loyalty-points, #keep-excess-credit").forEach(element => {
            element.addEventListener("input", () => this.recalculateDialog(root, context));
            element.addEventListener("change", () => this.recalculateDialog(root, context));
        });
        root.querySelector("#add-payment-row")?.addEventListener("click", () => {
            const tbody = root.querySelector("#payment-rows");
            const holder = document.createElement("tbody");
            holder.innerHTML = this.paymentRowHtml({});
            const row = holder.firstElementChild;
            tbody.appendChild(row);
            bindRow(row);
            this.recalculateDialog(root, context);
        });
        this.recalculateDialog(root, context);
    },

    collectDialogValues(dialog) {
        const root = dialog.get_field("payment_html").$wrapper[0];
        const context = PharmacyPOS.state.paymentContext || { loyalty: {} };
        const payments = [...root.querySelectorAll(".payment-row")].map(row => ({
            mode_of_payment: row.querySelector(".payment-mode")?.value || "",
            card_pos_terminal: row.querySelector(".payment-terminal")?.value || "",
            amount: flt(row.querySelector(".payment-amount")?.value || 0),
            reference_no: row.querySelector(".payment-reference")?.value?.trim() || ""
        })).filter(row => row.mode_of_payment && row.amount > 0);
        payments.forEach(row => {
            if (row.mode_of_payment === "Credit Card" && !row.card_pos_terminal) frappe.throw(__("Select Card POS Terminal for each Credit Card payment."));
        });
        const points = Math.max(0, flt(root.querySelector("#redeem-loyalty-points")?.value || 0));
        if (points - flt(context.loyalty?.available_points || 0) > 1e-9) frappe.throw(__("Loyalty points exceed the available balance."));
        const loyaltyAmount = flt(points * flt(context.loyalty?.conversion_factor || 0), 6);
        const allocations = [...root.querySelectorAll(".allocation-row")].map(row => ({
            reference_type: row.dataset.referenceType,
            reference_name: row.dataset.referenceName,
            available_amount: flt(row.dataset.available),
            allocated_amount: flt(row.querySelector(".allocation-amount")?.value || 0)
        })).filter(row => row.allocated_amount > 0);
        allocations.forEach(row => { if (row.allocated_amount - row.available_amount > 1e-9) frappe.throw(__("Allocated amount exceeds the available customer balance.")); });
        const keepExcessAsCredit = Boolean(root.querySelector("#keep-excess-credit")?.checked);
        return { payments, loyalty: { points, amount: loyaltyAmount }, allocations, keep_excess_as_credit: keepExcessAsCredit };
    },

    recalculateDialog(root, context) {
        const paymentTotal = [...root.querySelectorAll(".payment-amount")].reduce((total, input) => total + flt(input.value || 0), 0);
        const points = flt(root.querySelector("#redeem-loyalty-points")?.value || 0);
        const loyaltyAmount = flt(points * flt(context.loyalty?.conversion_factor || 0), 6);
        const allocationTotal = [...root.querySelectorAll(".allocation-amount")].reduce((total, input) => total + flt(input.value || 0), 0);
        const applied = flt(paymentTotal + loyaltyAmount + allocationTotal, 6);
        const remaining = Math.max(0, this.net - applied);
        const change = Math.max(0, paymentTotal - Math.max(0, this.net - loyaltyAmount - allocationTotal));
        const set = (selector, value) => { const element = root.querySelector(selector); if (element) element.textContent = format_currency(value); };
        set("#dialog-applied", applied); set("#dialog-remaining", remaining); set("#dialog-change", change);
        const changeTitle = root.querySelector("#dialog-change-title");
        if (changeTitle) changeTitle.textContent = root.querySelector("#keep-excess-credit")?.checked ? "Customer Credit" : "Change";
    },

    validateForSubmit() {
        if (!this.enabled) return;
        if (this.requiresFullPayment() && this.appliedTotal() + 1e-9 < this.net) frappe.throw(__("Payment is incomplete."));
    },

    reset() {
        PharmacyPOS.state.payments = [];
        PharmacyPOS.state.loyaltyRedemption = { points: 0, amount: 0 };
        PharmacyPOS.state.advanceAllocations = [];
        PharmacyPOS.state.keepExcessAsCredit = false;
        PharmacyPOS.state.quickCash = cint(PharmacyPOS.state.settings.quick_cash_default ?? 1) === 1;
        this.syncQuickCashUI();
        this.syncKeepChangeUI();
        this.refreshSummary();
    }
};
