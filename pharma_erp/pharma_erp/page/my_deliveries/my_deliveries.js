frappe.pages["my-deliveries"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("My Deliveries"),
        single_column: true
    });

    const myDeliveriesPage = new MyDeliveriesPage(wrapper, page);
    page.set_primary_action(__("Refresh"), () => myDeliveriesPage.load_orders(), "refresh");
};


class MyDeliveriesPage {
    constructor(wrapper, page) {
        this.wrapper = wrapper;
        this.page = page;
        this.$main = $(wrapper).find(".layout-main-section");
        this.orders = [];
        this.trips = [];
        this.employee = null;
        this.expandedOrders = new Set();
        this.expandedTrips = new Set();

        this.setup_page();
        this.setup_events();
        this.load_orders();
    }

    setup_page() {
        this.$main.html(`
            <div class="my-deliveries-page" dir="rtl">
                <div class="md-loading text-muted">جاري تحميل أوردراتك...</div>
                <div class="md-error" style="display:none;"></div>

                <div class="md-content" style="display:none;">
                    <div class="md-driver-header">
                        <div>
                            <div class="md-small-label">الطيار</div>
                            <div class="md-driver-name"></div>
                        </div>
                        <div class="md-live-badge">مباشر</div>
                    </div>

                    <div class="md-trips"></div>
                    <div class="md-summary"></div>

                    <div class="md-board">
                        ${this.board_section("ready", "جاهز للاستلام")}
                        ${this.board_section("out", "خرج للتوصيل")}
                        ${this.board_section("returning", "راجع / عاد للصيدلية")}
                        ${this.board_section("delivered", "تم التسليم اليوم")}
                    </div>
                </div>
            </div>
        `);
        this.add_styles();
    }

    board_section(name, label) {
        return `
            <section class="md-section ${name}">
                <div class="md-section-header">
                    <span>${label}</span>
                    <span class="md-count" data-count="${name}">0</span>
                </div>
                <div class="md-orders" data-column="${name}"></div>
            </section>
        `;
    }

    add_styles() {
        if ($("#my-deliveries-styles").length) return;

        $("head").append(`
            <style id="my-deliveries-styles">
                .my-deliveries-page { padding-top:10px; max-width:1200px; margin:0 auto; }
                .md-loading,.md-error {
                    background:#fff; border:1px solid #e5e7eb; border-radius:14px;
                    padding:28px; text-align:center; font-size:15px;
                }
                .md-error { color:#b42318; background:#fffbfa; border-color:#fecdca; }
                .md-driver-header {
                    display:flex; align-items:center; justify-content:space-between; gap:12px;
                    padding:16px 18px; margin-bottom:14px; background:#fff;
                    border:1px solid #e5e7eb; border-radius:14px;
                }
                .md-small-label { color:#667085; font-size:12px; margin-bottom:3px; }
                .md-driver-name { color:#101828; font-size:20px; font-weight:800; }
                .md-live-badge {
                    color:#027a48; background:#ecfdf3; border:1px solid #abefc6;
                    border-radius:999px; padding:5px 11px; font-size:12px; font-weight:700;
                }

                .md-trips {
                    display:grid; grid-template-columns:repeat(2,minmax(280px,1fr));
                    gap:12px; margin-bottom:14px;
                }
                .md-trip-card {
                    background:#fff; border:1px solid #e5e7eb; border-inline-start:5px solid #2e90fa;
                    border-radius:14px; padding:14px;
                }
                .md-trip-card.out { border-inline-start-color:#7a5af8; }
                .md-trip-card.returning { border-inline-start-color:#f79009; }
                .md-trip-card.completed { border-inline-start-color:#12b76a; }
                .md-trip-top {
                    display:flex; justify-content:space-between; align-items:center; gap:8px;
                }
                .md-trip-head-main { display:flex; align-items:center; gap:8px; min-width:0; }
                .md-toggle-trip,.md-toggle-order {
                    border:0; background:transparent; color:#475467; padding:3px 5px;
                    cursor:pointer; line-height:1; font-size:15px;
                }
                .md-trip-card.expanded .md-toggle-trip,.md-order-card.expanded .md-toggle-order { transform:rotate(90deg); }
                .md-trip-details,.md-order-details { display:none; margin-top:10px; }
                .md-trip-card.expanded .md-trip-details,.md-order-card.expanded .md-order-details { display:block; }
                .md-trip-name { color:#175cd3; font-size:16px; font-weight:800; }
                .md-trip-badge {
                    background:#f2f4f7; border-radius:999px; padding:5px 9px;
                    font-size:11px; font-weight:700;
                }
                .md-trip-stops { margin-top:10px; border-top:1px dashed #d0d5dd; padding-top:8px; }
                .md-trip-stops-title { color:#475467; font-size:12px; font-weight:800; margin-bottom:6px; }
                .md-trip-stop {
                    display:flex; justify-content:space-between; align-items:center; gap:8px;
                    padding:7px 8px; margin-top:5px; border-radius:8px; background:#f8fafc;
                    font-size:12px;
                }
                .md-trip-stop-invoice { color:#175cd3; font-weight:800; direction:ltr; }
                .md-trip-stop-status { color:#344054; font-weight:700; }
                .md-trip-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:10px; }
                .md-trip-actions .btn { width:100%; }
                .md-trip-primary { grid-column:1/-1; min-height:42px; font-weight:800; }

                .md-summary {
                    display:grid; grid-template-columns:repeat(3,minmax(130px,1fr));
                    gap:10px; margin-bottom:16px;
                }
                .md-summary-card {
                    background:#fff; border:1px solid #e5e7eb; border-radius:14px;
                    padding:14px; text-align:center;
                }
                .md-summary-label { color:#667085; font-size:12px; margin-bottom:6px; }
                .md-summary-value { color:#101828; font-size:24px; font-weight:800; }

                .md-board {
                    display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr));
                    gap:14px; align-items:start;
                }
                .md-section {
                    background:#f8f9fa; border:1px solid #e5e7eb; border-radius:14px;
                    overflow:hidden; min-height:280px;
                }
                .md-section-header {
                    display:flex; align-items:center; justify-content:space-between;
                    gap:10px; padding:14px; background:#fff; font-weight:800;
                    border-bottom:3px solid #d0d5dd;
                }
                .md-section.ready .md-section-header { border-bottom-color:#2e90fa; }
                .md-section.out .md-section-header { border-bottom-color:#7a5af8; }
                .md-section.delivered .md-section-header { border-bottom-color:#12b76a; }
                .md-count {
                    display:inline-flex; align-items:center; justify-content:center;
                    min-width:28px; height:28px; padding:0 7px; border-radius:20px;
                    background:#f2f4f7; font-size:13px;
                }
                .md-orders { padding:10px; }
                .md-order-card {
                    background:#fff; border:1px solid #e5e7eb; border-radius:12px;
                    padding:14px; margin-bottom:10px; box-shadow:0 1px 2px rgba(16,24,40,.05);
                }
                .md-order-top {
                    display:flex; justify-content:space-between; align-items:center; gap:8px;
                }
                .md-order-head-main { display:flex; align-items:center; gap:6px; min-width:0; }
                .md-order-compact-meta {
                    display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-top:8px;
                    color:#475467; font-size:11px;
                }
                .md-compact-pill,.md-payment-badge {
                    display:inline-flex; align-items:center; border-radius:999px; padding:4px 8px;
                    background:#f2f4f7; color:#344054; font-size:11px; font-weight:700;
                }
                .md-payment-badge.confirmed { background:#ecfdf3; color:#027a48; }
                .md-payment-badge.pending { background:#fffaeb; color:#b54708; }
                .md-payment-badge.rejected { background:#fef3f2; color:#b42318; }
                .md-invoice-name { color:#175cd3; font-size:15px; font-weight:800; word-break:break-all; }
                .md-order-time { color:#667085; font-size:12px; direction:ltr; }
                .md-customer { color:#101828; font-size:16px; font-weight:800; margin-bottom:8px; }
                .md-info-row {
                    display:flex; justify-content:space-between; gap:10px;
                    padding:6px 0; border-bottom:1px dashed #eaecf0; font-size:13px;
                }
                .md-info-label { color:#667085; }
                .md-info-value { color:#101828; font-weight:600; text-align:left; }
                .md-card-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:12px; }
                .md-card-actions .btn { width:100%; min-height:38px; }
                .md-primary-action { grid-column:1/-1; font-weight:800; }
                .md-workflow-note,.md-trip-note {
                    grid-column:1/-1; padding:9px 10px; border-radius:8px;
                    font-size:12px; font-weight:700; text-align:center;
                }
                .md-workflow-note { background:#fff7e6; border:1px solid #f5c26b; color:#7a4b00; }
                .md-trip-note { background:#eff8ff; border:1px solid #b2ddff; color:#175cd3; }
                .md-delivered-meta {
                    margin-top:10px; padding:8px; border-radius:8px;
                    background:#ecfdf3; color:#027a48; font-size:12px; font-weight:700; text-align:center;
                }
                .md-empty { padding:35px 10px; text-align:center; color:#98a2b3; font-size:13px; }

                @media (max-width:900px) {
                    .md-trips,.md-board { grid-template-columns:1fr; }
                }
                @media (max-width:600px) {
                    .md-summary { grid-template-columns:1fr; }
                    .md-summary-card { display:flex; justify-content:space-between; align-items:center; text-align:right; }
                    .md-summary-label { margin-bottom:0; }
                    .md-summary-value { font-size:22px; }
                    .md-card-actions { grid-template-columns:1fr; }
                    .md-primary-action { grid-column:auto; }
                }
            </style>
        `);
    }

    setup_events() {
        this.$main.off(".myDeliveries");

        this.$main.on("click.myDeliveries", ".md-change-status", (event) => {
            const $button = $(event.currentTarget);
            this.confirm_status_change(
                $button.attr("data-invoice"),
                $button.attr("data-next-status")
            );
        });

        this.$main.on("click.myDeliveries", ".md-record-collection", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            const order = this.orders.find((row) => row.name === invoiceName);
            if (order) this.open_collection_dialog(order);
        });

        this.$main.on("click.myDeliveries", ".md-request-addon", (event) => {
            this.open_add_on_request_dialog($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.myDeliveries", ".md-customer-return", (event) => {
            this.open_customer_return_dialog($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.myDeliveries", ".md-partial-return", (event) => {
            this.open_partial_return_dialog($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.myDeliveries", ".md-driver-returned", (event) => {
            this.confirm_driver_returned($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.myDeliveries", ".md-return-pharmacy", (event) => {
            this.confirm_return_to_pharmacy($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.myDeliveries", ".md-start-trip", (event) => {
            this.confirm_start_trip($(event.currentTarget).attr("data-trip"));
        });

        this.$main.on("click.myDeliveries", ".md-return-trip", (event) => {
            this.confirm_return_trip($(event.currentTarget).attr("data-trip"));
        });

        this.$main.on("click.myDeliveries", ".md-toggle-order", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            if (!invoiceName) return;
            if (this.expandedOrders.has(invoiceName)) this.expandedOrders.delete(invoiceName);
            else this.expandedOrders.add(invoiceName);
            $(event.currentTarget).closest(".md-order-card").toggleClass("expanded");
        });

        this.$main.on("click.myDeliveries", ".md-toggle-trip", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const tripName = $(event.currentTarget).attr("data-trip");
            if (!tripName) return;
            if (this.expandedTrips.has(tripName)) this.expandedTrips.delete(tripName);
            else this.expandedTrips.add(tripName);
            $(event.currentTarget).closest(".md-trip-card").toggleClass("expanded");
        });

    }

    load_orders() {
        this.$main.find(".md-loading").show().text("جاري تحميل أوردراتك...");
        this.$main.find(".md-error").hide();
        this.$main.find(".md-content").hide();

        frappe.call({
            method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.get_my_deliveries",
            callback: (response) => {
                const result = response.message || {};
                this.employee = result.employee || null;
                this.orders = result.orders || [];
                this.trips = result.trips || [];

                const orderNames = new Set(this.orders.map((order) => order.name));
                this.expandedOrders = new Set(
                    [...this.expandedOrders].filter((name) => orderNames.has(name))
                );
                const tripNames = new Set(this.trips.map((trip) => trip.name));
                this.expandedTrips = new Set(
                    [...this.expandedTrips].filter((name) => tripNames.has(name))
                );

                if (!this.employee) {
                    this.show_error(result.message || "المستخدم الحالي غير مربوط بموظف.");
                    return;
                }
                this.render();
            },
            error: () => this.show_error("حدث خطأ أثناء تحميل أوردراتك.")
        });
    }

    show_error(message) {
        this.$main.find(".md-loading").hide();
        this.$main.find(".md-error").text(message).show();
        this.$main.find(".md-content").hide();
    }

    confirm_start_trip(tripName) {
        if (!tripName) return;
        frappe.confirm(
            __("هل استلمت كل أوردرات الرحلة وخرجت للتوصيل؟"),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.start_my_delivery_trip",
                args: { trip_name: tripName },
                freeze: true,
                freeze_message: __("جاري تسجيل خروج الرحلة..."),
                callback: () => {
                    frappe.show_alert({ message: __("تم تسجيل خروج الرحلة."), indicator: "green" });
                    this.load_orders();
                }
            })
        );
    }

    confirm_return_trip(tripName) {
        if (!tripName) return;
        frappe.confirm(
            __("هل رجعت إلى الصيدلية بعد إنهاء كل أوردرات الرحلة؟"),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.return_my_delivery_trip",
                args: { trip_name: tripName },
                freeze: true,
                freeze_message: __("جاري تسجيل رجوع الرحلة..."),
                callback: (response) => {
                    const result = response.message || {};
                    frappe.show_alert({ message: __("تم تسجيل رجوع الرحلة للصيدلية."), indicator: "green" });
                    if (result.custom_trip_duration_mins) {
                        frappe.msgprint({
                            title: __("مدة الرحلة"),
                            message: `${__("مدة الرحلة")}: ${result.custom_trip_duration_mins} ${__("دقيقة")}`,
                            indicator: "green"
                        });
                    }
                    this.load_orders();
                }
            })
        );
    }

    confirm_status_change(invoiceName, nextStatus) {
        if (!invoiceName || !nextStatus) return;

        const order = this.orders.find((row) => row.name === invoiceName) || {};
        const isPickup = nextStatus === "Out for Delivery";

        if (!isPickup) {
            const expected = this.get_collectible_amount(order);
            if (expected > 0.01) {
                this.open_collection_dialog(order);
                return;
            }
        }

        frappe.confirm(
            isPickup
                ? __("هل استلمت الأوردر وخرجت للتوصيل؟")
                : __("هل تم تسليم الأوردر للعميل؟ لا يوجد مبلغ مطلوب تحصيله."),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.update_my_delivery_status",
                args: { invoice_name: invoiceName, new_status: nextStatus },
                freeze: true,
                freeze_message: isPickup ? __("جاري تسجيل خروجك...") : __("جاري تسجيل التسليم..."),
                callback: (response) => {
                    const result = response.message || {};
                    frappe.show_alert({
                        message: isPickup ? __("تم تسجيل خروج الأوردر.") : __("تم تسجيل تسليم الأوردر."),
                        indicator: "green"
                    });
                    if (!isPickup && result.duration_in_mins) {
                        frappe.msgprint({
                            title: __("مدة التوصيل"),
                            message: `${__("مدة التوصيل")}: ${result.duration_in_mins} ${__("دقيقة")}.`,
                            indicator: "green"
                        });
                    }
                    this.load_orders();
                }
            })
        );
    }

    async open_collection_dialog(order) {
        if (!order || !order.name) return;

        let terminalRows = [];
        try {
            const terminalResponse = await frappe.call({
                method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.get_my_delivery_card_terminals",
                args: { invoice_name: order.name }
            });
            terminalRows = terminalResponse.message || [];
        } catch (error) {
            console.error(error);
        }

        const terminalOptions = terminalRows
            .map((row) => row.name)
            .join("\n");
        const terminalDescription = terminalRows
            .map((row) => {
                const label = row.terminal_name || row.name;
                const bank = row.bank_label ? ` — ${row.bank_label}` : "";
                return `${row.name}: ${label}${bank}`;
            })
            .join("<br>");
        const defaultTerminal =
            order.custom_delivery_card_pos_terminal ||
            (terminalRows.length === 1 ? terminalRows[0].name : "");

        const expected = this.get_collectible_amount(order);
        const dialog = new frappe.ui.Dialog({
            title: order.custom_delivery_status === "Delivered"
                ? __("تسجيل تحصيل أوردر تم تسليمه")
                : __("تأكيد التسليم وتسجيل التحصيل"),
            fields: [
                {
                    fieldname: "invoice_name",
                    fieldtype: "Data",
                    label: __("رقم الفاتورة"),
                    default: order.name,
                    read_only: 1
                },
                {
                    fieldname: "expected_amount",
                    fieldtype: "Currency",
                    label: __("المطلوب من العميل"),
                    default: expected,
                    read_only: 1
                },
                {
                    fieldname: "payment_method",
                    fieldtype: "Select",
                    label: __("طريقة دفع العميل"),
                    options: "Cash\nInstaPay\nMobile Wallet\nCard\nBank Transfer",
                    default: order.custom_driver_reported_customer_payment_method || "Cash",
                    reqd: 1
                },
                {
                    fieldname: "card_pos_terminal",
                    fieldtype: "Select",
                    label: __("ماكينة الفيزا"),
                    options: terminalOptions,
                    default: defaultTerminal,
                    depends_on: 'eval:doc.payment_method=="Card"',
                    mandatory_depends_on: 'eval:doc.payment_method=="Card"',
                    description: terminalDescription || __("لا توجد ماكينات فيزا مفعلة.")
                },
                {
                    fieldname: "collected_amount",
                    fieldtype: "Currency",
                    label: __("المبلغ المستلم"),
                    default: Number(order.custom_driver_reported_collected_amount || expected),
                    reqd: 1
                },
                {
                    fieldname: "reference",
                    fieldtype: "Data",
                    label: __("رقم العملية / المرجع"),
                    default: order.custom_driver_collection_reference || "",
                    description: __("مطلوب في التحصيلات غير النقدية.")
                },
                {
                    fieldname: "collection_proof",
                    fieldtype: "Attach Image",
                    label: __("صورة التحويل / إيصال الدفع"),
                    default: order.custom_driver_collection_proof || "",
                    depends_on: 'eval:doc.payment_method!="Cash"',
                    mandatory_depends_on: 'eval:doc.payment_method=="InstaPay" || doc.payment_method=="Mobile Wallet" || doc.payment_method=="Bank Transfer"',
                    description: __("من الموبايل اضغط رفع الصورة ثم اختر الكاميرا وصوّر شاشة التحويل أو الإيصال بوضوح.")
                },
                {
                    fieldname: "notes",
                    fieldtype: "Small Text",
                    label: __("ملاحظات التحصيل"),
                    default: order.custom_driver_collection_notes || ""
                }
            ],
            primary_action_label: order.custom_delivery_status === "Delivered"
                ? __("حفظ التحصيل")
                : __("تم التسليم وحفظ التحصيل"),
            primary_action: (values) => {
                const amount = Number(values.collected_amount || 0);
                if (amount <= 0) {
                    frappe.msgprint(__("المبلغ المستلم يجب أن يكون أكبر من صفر."));
                    return;
                }
                if (amount > expected + 0.01) {
                    frappe.msgprint(__("المبلغ المستلم لا يمكن أن يتجاوز المطلوب من العميل."));
                    return;
                }
                if (values.payment_method !== "Cash" && !String(values.reference || "").trim()) {
                    frappe.msgprint(__("رقم العملية مطلوب في التحصيلات غير النقدية."));
                    return;
                }
                const proofRequired = ["InstaPay", "Mobile Wallet", "Bank Transfer"].includes(values.payment_method);
                if (proofRequired && !String(values.collection_proof || "").trim()) {
                    frappe.msgprint(__("صورة التحويل مطلوبة. صوّر التحويل من الموبايل وارفع الصورة."));
                    return;
                }
                if (values.payment_method === "Card" && !String(values.card_pos_terminal || "").trim()) {
                    frappe.msgprint(__("اختر ماكينة الفيزا التي استقبلت العملية."));
                    return;
                }

                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.declare_my_delivery_collection",
                    args: {
                        invoice_name: order.name,
                        payment_method: values.payment_method,
                        collected_amount: amount,
                        reference: values.reference || "",
                        notes: values.notes || "",
                        card_pos_terminal: values.card_pos_terminal || "",
                        collection_proof: values.payment_method === "Cash"
                            ? ""
                            : (values.collection_proof || "")
                    },
                    freeze: true,
                    freeze_message: __("جاري تسجيل التسليم والتحصيل..."),
                    callback: (response) => {
                        const result = response.message || {};
                        dialog.hide();
                        this.expandedOrders.add(order.name);
                        frappe.show_alert({
                            message: result.verification_status === "Confirmed"
                                ? __("تم تسجيل التحصيل وتأكيده.")
                                : __("تم تسجيل التحصيل وينتظر تأكيد مدير الشيفت."),
                            indicator: result.verification_status === "Confirmed"
                                ? "green"
                                : "orange"
                        });
                        if (result.duration_in_mins) {
                            frappe.msgprint({
                                title: __("مدة التوصيل"),
                                message: `${__("مدة التوصيل")}: ${result.duration_in_mins} ${__("دقيقة")}.`,
                                indicator: "green"
                            });
                        }
                        this.load_orders();
                    },
                    error: () => $button.prop("disabled", false)
                });
            }
        });
        dialog.show();

        // Attach Image uses the device file picker. On mobile browsers this
        // hint limits the picker to images and offers the rear camera directly.
        const proofField = dialog.get_field("collection_proof");
        if (proofField && proofField.$wrapper) {
            proofField.$wrapper.find('input[type="file"]')
                .attr("accept", "image/*")
                .attr("capture", "environment");
        }
    }

    open_partial_return_dialog(invoiceName) {
        if (!invoiceName) return;
        frappe.call({
            method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.get_my_partial_return_items",
            args: { invoice_name: invoiceName },
            freeze: true,
            freeze_message: __("جاري تحميل أصناف الفاتورة..."),
            callback: (response) => {
                const data = response.message || {};
                const items = data.items || [];
                if (!items.length) {
                    frappe.msgprint({ title: __("لا توجد أصناف"), message: __("لا توجد أصناف متاحة للمرتجع الجزئي."), indicator: "orange" });
                    return;
                }
                const rows = items.map((item, index) => {
                    const packSize = Math.max(1, Number(item.pack_size || 1) || 1);
                    const maxUnits = packSize > 1 ? Math.max(0, Math.ceil(packSize) - 1) : 0;
                    const availableBoxes = Number(item.returnable_boxes || 0);
                    const availableUnits = Number(item.returnable_units || 0);
                    const availableLabel = packSize > 1
                        ? `${availableBoxes} ${__("علبة")} + ${availableUnits} ${__("وحدة")}`
                        : Number(item.returnable_qty || 0).toFixed(3);
                    return `
                    <tr data-index="${index}">
                        <td><input type="checkbox" class="md-pr-check"></td>
                        <td><strong>${this.escape(item.item_name || item.item_code)}</strong><br><small>${this.escape(item.item_code)}</small><br><small><b>${item.source_invoice_type === "Add-on" ? __("فاتورة إضافة") : __("الفاتورة الأصلية")}</b>: ${this.escape(item.source_invoice || "")}</small><br><small>${__("حجم العبوة")}: ${packSize} ${__("وحدة")}</small></td>
                        <td>${this.escape(availableLabel)}</td>
                        <td><input type="number" class="form-control md-pr-boxes" min="0" step="1" value="0"></td>
                        <td><input type="number" class="form-control md-pr-units" min="0" max="${maxUnits}" step="1" value="0" ${packSize <= 1 ? "disabled" : ""}></td>
                        <td>${this.escape(this.format_money(item.rate || 0))}</td>
                    </tr>
                `;
                }).join("");
                const dialog = new frappe.ui.Dialog({
                    title: __("مرتجع جزئي من الأوردر"),
                    size: "large",
                    fields: [
                        { fieldtype: "HTML", fieldname: "items_html", options: `
                            <div class="alert alert-info">${__("حدد الأصناف التي رجعها العميل. باقي الأوردر سيظل تم تسليمه، وخدمة التوصيل لن تُرجع تلقائيًا.")}</div>
                            <table class="table table-bordered"><thead><tr><th></th><th>${__("الصنف")}</th><th>${__("المتاح")}</th><th>${__("علب")}</th><th>${__("وحدات")}</th><th>${__("السعر")}</th></tr></thead><tbody>${rows}</tbody></table>
                            <div class="text-muted md-pr-total"></div>
                        ` },
                        { fieldtype: "Select", fieldname: "reason", label: __("سبب المرتجع"), reqd: 1, options: ["Item Rejected by Customer", "Wrong Item", "Damaged Item", "Payment Problem", "Other"].join("\n") },
                        { fieldtype: "Small Text", fieldname: "notes", label: __("ملاحظات") }
                    ],
                    primary_action_label: __("تسجيل المرتجع الجزئي"),
                    primary_action: (values) => {
                        const wrapper = dialog.get_field("items_html").$wrapper[0];
                        const selected = [];
                        wrapper.querySelectorAll("tbody tr").forEach((row) => {
                            if (!row.querySelector(".md-pr-check")?.checked) return;
                            const item = items[Number(row.dataset.index || 0)];
                            const boxQty = Number(row.querySelector(".md-pr-boxes")?.value || 0);
                            const unitQty = Number(row.querySelector(".md-pr-units")?.value || 0);
                            const packSize = Math.max(1, Number(item.pack_size || 1) || 1);
                            if (!Number.isInteger(boxQty) || !Number.isInteger(unitQty) || boxQty < 0 || unitQty < 0) {
                                frappe.throw(`${__("عدد العلب والوحدات يجب أن يكون رقمًا صحيحًا")}: ${item.item_code}`);
                            }
                            if (packSize > 1 && unitQty >= packSize) {
                                frappe.throw(`${__("عدد الوحدات يجب أن يكون أقل من حجم العبوة")}: ${item.item_code} (${packSize})`);
                            }
                            if (packSize <= 1 && unitQty > 0) {
                                frappe.throw(`${__("هذا الصنف لا يسمح بإدخال وحدات منفصلة؛ استخدم خانة العلب")}: ${item.item_code}`);
                            }
                            const qty = Number((boxQty + unitQty / packSize).toFixed(6));
                            if (qty > Number(item.returnable_qty || 0) + 0.000001) {
                                frappe.throw(`${__("كمية المرتجع أكبر من المتاح للصنف")}: ${item.item_code}`);
                            }
                            if (qty > 0) selected.push({ source_invoice: item.source_invoice, source_item: item.source_item, box_qty: boxQty, unit_qty: unitQty, pack_size: packSize, qty });
                        });
                        if (!selected.length) {
                            frappe.msgprint({ title: __("حدد الأصناف"), message: __("اختر صنفًا واحدًا على الأقل واكتب كمية المرتجع."), indicator: "orange" });
                            return;
                        }
                        if (values.reason === "Other" && !(values.notes || "").trim()) {
                            frappe.msgprint({ title: __("الملاحظات مطلوبة"), message: __("اكتب سبب المرتجع الجزئي."), indicator: "orange" });
                            return;
                        }
                        const $button = dialog.get_primary_btn();
                        $button.prop("disabled", true);
                        frappe.call({
                            method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.request_my_partial_return",
                            args: { invoice_name: invoiceName, items: JSON.stringify(selected), reason: values.reason, notes: values.notes || "" },
                            freeze: true,
                            freeze_message: __("جاري تسجيل المرتجع الجزئي..."),
                            callback: (r) => {
                                dialog.hide();
                                const result = r.message || {};
                                frappe.msgprint({
                                    title: __("تم تسجيل المرتجع الجزئي"),
                                    indicator: "green",
                                    message: `${__("قيمة المرتجع التقديرية")}: ${this.format_money(result.estimated_return_amount || 0)}<br>${__("المطلوب تحصيله بعد المرتجع")}: ${this.format_money(result.remaining_collectible || 0)}<br>${__("بعد تسجيل صافي التحصيل، اضغط رجعت الصيدلية لتسليم الصنف المرتجع.")}`
                                });
                                this.load_orders();
                            },
                            error: () => $button.prop("disabled", false)
                        });
                    }
                });
                dialog.show();
                const partialWrapper = dialog.get_field("items_html").$wrapper[0];
                const updateEstimatedReturn = () => {
                    let total = 0;
                    let invalid = false;
                    partialWrapper.querySelectorAll("tbody tr").forEach((row) => {
                        if (!row.querySelector(".md-pr-check")?.checked) return;
                        const item = items[Number(row.dataset.index || 0)];
                        const boxQty = Number(row.querySelector(".md-pr-boxes")?.value || 0);
                        const unitQty = Number(row.querySelector(".md-pr-units")?.value || 0);
                        const packSize = Math.max(1, Number(item.pack_size || 1) || 1);
                        const qty = boxQty + unitQty / packSize;
                        if (
                            !Number.isInteger(boxQty)
                            || !Number.isInteger(unitQty)
                            || boxQty < 0
                            || unitQty < 0
                            || (packSize > 1 && unitQty >= packSize)
                            || (packSize <= 1 && unitQty > 0)
                            || qty > Number(item.returnable_qty || 0) + 0.000001
                        ) {
                            invalid = true;
                            return;
                        }
                        total += qty * Number(item.rate || 0);
                    });
                    const totalNode = partialWrapper.querySelector(".md-pr-total");
                    if (totalNode) {
                        totalNode.innerHTML = invalid
                            ? `<span class="text-danger">${__("راجع كمية العلب والوحدات المدخلة.")}</span>`
                            : `${__("قيمة المرتجع التقديرية")}: ${this.format_money(total)}`;
                    }
                };
                partialWrapper.addEventListener("input", (event) => {
                    if (event.target.matches(".md-pr-boxes, .md-pr-units")) {
                        const row = event.target.closest("tr");
                        const checkbox = row?.querySelector(".md-pr-check");
                        if (checkbox && Number(event.target.value || 0) > 0) checkbox.checked = true;
                    }
                    updateEstimatedReturn();
                });
                partialWrapper.addEventListener("change", updateEstimatedReturn);
                updateEstimatedReturn();
            }
        });
    }

    open_customer_return_dialog(invoiceName) {
        if (!invoiceName) return;
        const dialog = new frappe.ui.Dialog({
            title: __("رجوع الأوردر للصيدلية"),
            fields: [
                {
                    fieldname: "invoice_name",
                    fieldtype: "Data",
                    label: __("رقم الفاتورة"),
                    default: invoiceName,
                    read_only: 1
                },
                {
                    fieldname: "reason",
                    fieldtype: "Select",
                    label: __("سبب عدم التسليم"),
                    options: [
                        "Customer Cancelled Order",
                        "Customer Refused Order",
                        "Customer Not Answering",
                        "Wrong Address",
                        "Payment Problem",
                        "Other"
                    ].join("\n"),
                    default: "Customer Cancelled Order",
                    reqd: 1
                },
                {
                    fieldname: "notes",
                    fieldtype: "Small Text",
                    label: __("الملاحظات"),
                    description: __("اكتب أي تفاصيل يحتاجها مدير الشيفت، والملاحظات إلزامية عند اختيار Other.")
                },
                {
                    fieldname: "workflow_note",
                    fieldtype: "HTML",
                    options: `
                        <div class="alert alert-warning">
                            لن يتم إلغاء الفاتورة من صفحة الطيار. سيتم تسجيل الأوردر كراجع للصيدلية، وبعد وصولك يؤكد مدير الشيفت استلام البضاعة وينشئ مرتجع المبيعات.
                        </div>
                    `
                }
            ],
            primary_action_label: __("تأكيد رجوع الأوردر"),
            primary_action: (values) => {
                if (values.reason === "Other" && !String(values.notes || "").trim()) {
                    frappe.msgprint(__("اكتب سبب رجوع الأوردر في الملاحظات."));
                    return;
                }
                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.request_my_customer_return",
                    args: {
                        invoice_name: invoiceName,
                        reason: values.reason,
                        notes: values.notes || ""
                    },
                    freeze: true,
                    freeze_message: __("جاري تسجيل رجوع الأوردر..."),
                    callback: () => {
                        dialog.hide();
                        frappe.show_alert({
                            message: __("تم تسجيل الأوردر كراجع للصيدلية."),
                            indicator: "orange"
                        });
                        this.load_orders();
                    },
                    error: () => $button.prop("disabled", false)
                });
            }
        });
        dialog.show();
    }

    confirm_driver_returned(invoiceName) {
        if (!invoiceName) return;
        frappe.confirm(
            __("هل رجعت إلى الصيدلية بالفعل ومعك أي بضاعة مرتجعة تخص هذا الأوردر؟"),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.mark_my_driver_returned",
                args: { invoice_name: invoiceName },
                freeze: true,
                freeze_message: __("جاري تسجيل الرجوع للصيدلية..."),
                callback: (response) => {
                    const result = response.message || {};
                    frappe.show_alert({
                        message: result.delivery_status === "Returned to Pharmacy"
                            ? __("تم تسجيل وصول المرتجع للصيدلية وينتظر مراجعة المدير.")
                            : __("تم تسجيل رجوعك للصيدلية."),
                        indicator: "green"
                    });
                    this.load_orders();
                }
            })
        );
    }

    open_add_on_request_dialog(invoiceName) {
        if (!invoiceName) return;
        const dialog = new frappe.ui.Dialog({
            title: __("العميل طلب إضافة أصناف"),
            fields: [
                {
                    fieldname: "invoice_name",
                    fieldtype: "Data",
                    label: __("رقم الفاتورة"),
                    default: invoiceName,
                    read_only: 1
                },
                {
                    fieldname: "notes",
                    fieldtype: "Small Text",
                    label: __("الأصناف الإضافية المطلوبة"),
                    description: __("اكتب أسماء الأصناف والكميات التي طلبها العميل."),
                    reqd: 1
                }
            ],
            primary_action_label: __("سجّل طلب الإضافة"),
            primary_action: (values) => {
                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.request_my_add_on_return",
                    args: { invoice_name: invoiceName, notes: values.notes },
                    freeze: true,
                    freeze_message: __("جاري تسجيل طلب الإضافة..."),
                    callback: () => {
                        dialog.hide();
                        frappe.show_alert({
                            message: __("تم تسجيل طلب الإضافة. أكمل باقي أوردرات الرحلة ثم ارجع للصيدلية."),
                            indicator: "orange"
                        });
                        this.load_orders();
                    },
                    error: () => $button.prop("disabled", false)
                });
            }
        });
        dialog.show();
    }

    confirm_return_to_pharmacy(invoiceName) {
        if (!invoiceName) return;
        frappe.confirm(
            __("هل وصلت إلى الصيدلية بالفعل؟"),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.my_deliveries.my_deliveries.mark_my_returned_to_pharmacy",
                args: { invoice_name: invoiceName },
                freeze: true,
                freeze_message: __("جاري تسجيل الرجوع للصيدلية..."),
                callback: (response) => {
                    const result = response.message || {};
                    frappe.show_alert({ message: __("تم تسجيل وصولك للصيدلية."), indicator: "green" });
                    if (result.total_attempt_duration_mins) {
                        frappe.msgprint({
                            title: __("تم إغلاق محاولة التوصيل"),
                            message: `${__("مدة المحاولة")}: ${result.total_attempt_duration_mins} ${__("دقيقة")}.`,
                            indicator: "green"
                        });
                    }
                    this.load_orders();
                }
            })
        );
    }

    get_collectible_amount(order) {
        const partialReturnRequest = order?.partial_return_request || null;
        if (partialReturnRequest && partialReturnRequest.remaining_collectible !== undefined) {
            return Number(partialReturnRequest.remaining_collectible || 0);
        }
        return Number(order?.group_outstanding_amount ?? order?.outstanding_amount ?? 0);
    }

    get_group(order) {
        const status = order.custom_delivery_status || "";
        const partialReturnRequest = order.partial_return_request || null;
        const requestStatus = partialReturnRequest?.status || "";
        const partialReturnOpen = Boolean(
            partialReturnRequest
            && !["Partial Return Completed", "Full Return Completed", "Cancelled"].includes(requestStatus)
        );

        // Delivery of the accepted items is complete, but the operational job
        // is not complete until the pharmacy receives and reviews the rejected item.
        if (partialReturnOpen) return "returning";
        if (status === "Out for Delivery") return "out";
        if (["Returning to Pharmacy", "Returned to Pharmacy"].includes(status)) return "returning";
        if (status === "Delivered") return "delivered";
        return "ready";
    }

    render() {
        const groups = { ready: [], out: [], returning: [], delivered: [] };
        this.orders.forEach((order) => groups[this.get_group(order)].push(order));

        this.$main.find(".md-driver-name").text(this.employee.employee_name || this.employee.name);
        this.render_trips();
        this.render_summary(groups);
        Object.keys(groups).forEach((name) => this.render_column(name, groups[name]));

        this.$main.find(".md-loading,.md-error").hide();
        this.$main.find(".md-content").show();
    }

    render_trips() {
        const $container = this.$main.find(".md-trips");
        const visible = this.trips.filter((trip) => {
            const status = trip.custom_operational_status || "Ready";
            return status !== "Cancelled";
        });
        if (!visible.length) {
            $container.empty();
            return;
        }
        $container.html(visible.map((trip) => this.trip_card(trip)).join(""));
    }

    trip_card(trip) {
        const status = trip.custom_operational_status || "Ready";
        const cssClass = status === "Completed"
            ? "completed"
            : status === "Returning to Pharmacy"
                ? "returning"
                : status === "Out for Delivery" || status === "Partially Delivered"
                    ? "out"
                    : "";
        const name = this.escape(trip.name);
        const expanded = this.expandedTrips.has(trip.name);
        const startButton = trip.can_start
            ? `<button type="button" class="btn btn-primary md-start-trip md-trip-primary" data-trip="${name}">🛵 استلمت الرحلة وخرجت</button>`
            : "";
        const returnButton = trip.can_return
            ? `<button type="button" class="btn btn-warning md-return-trip md-trip-primary" data-trip="${name}">🏪 رجعت الصيدلية</button>`
            : "";
        const stops = (trip.stops || []).map((stop) => `
            <div class="md-trip-stop">
                <span class="md-trip-stop-invoice">${this.escape(stop.invoice || `Stop ${stop.idx || ""}`)}</span>
                <span class="md-trip-stop-status">${this.escape(this.get_stop_status_label(stop.status))}</span>
            </div>
        `).join("");
        const stopsBlock = stops
            ? `<div class="md-trip-stops"><div class="md-trip-stops-title">أوردرات الرحلة</div>${stops}</div>`
            : "";

        return `
            <div class="md-trip-card ${cssClass} ${expanded ? "expanded" : ""}" data-trip-card="${name}">
                <div class="md-trip-top">
                    <div class="md-trip-head-main">
                        <button type="button" class="md-toggle-trip" data-trip="${name}" aria-label="فتح تفاصيل الرحلة">▶</button>
                        <div class="md-trip-name">${name}</div>
                    </div>
                    <div class="md-trip-badge">${this.escape(this.get_trip_status_label(status))}</div>
                </div>
                <div class="md-order-compact-meta">
                    <span class="md-compact-pill">${this.escape(trip.custom_total_stops || (trip.invoice_names || []).length || 0)} أوردر</span>
                    <span class="md-compact-pill">${this.escape(trip.custom_delivered_stops || 0)} تم</span>
                    <span class="md-compact-pill">${this.escape(this.format_money(trip.custom_expected_collection || 0))}</span>
                </div>
                <div class="md-trip-details">
                    ${this.info_row("عدد الأوردرات", trip.custom_total_stops || (trip.invoice_names || []).length || 0)}
                    ${this.info_row("تم التسليم", trip.custom_delivered_stops || 0)}
                    ${this.info_row("المتبقي", trip.custom_pending_stops || 0)}
                    ${this.info_row("المدفوع مسبقًا", this.format_money(trip.custom_prepaid_total || 0))}
                    ${this.info_row("المطلوب تحصيله", this.format_money(trip.custom_expected_collection || 0))}
                    ${stopsBlock}
                    <div class="md-trip-actions">
                        ${startButton}
                        ${returnButton}
                    </div>
                </div>
            </div>
        `;
    }

    render_summary(groups) {
        this.$main.find(".md-summary").html(`
            ${this.summary_card("جاهز للاستلام", groups.ready.length)}
            ${this.summary_card("خارج للتوصيل", groups.out.length)}
            ${this.summary_card("راجع / عاد", groups.returning.length)}
            ${this.summary_card("تم التسليم اليوم", groups.delivered.length)}
        `);
    }

    summary_card(label, value) {
        return `
            <div class="md-summary-card">
                <div class="md-summary-label">${this.escape(label)}</div>
                <div class="md-summary-value">${this.escape(value)}</div>
            </div>
        `;
    }

    render_column(groupName, orders) {
        const $column = this.$main.find(`.md-orders[data-column="${groupName}"]`);
        this.$main.find(`.md-count[data-count="${groupName}"]`).text(orders.length);
        if (!orders.length) {
            $column.html(`<div class="md-empty">لا توجد أوردرات في هذه الحالة</div>`);
            return;
        }
        $column.html(orders.map((order) => this.order_card(order)).join(""));
    }

    order_card(order) {
        const status = order.custom_delivery_status || "";
        const addOnStatus = order.custom_add_on_order_status || "";
        const addOnNotes = order.custom_add_on_request_notes || "";
        const prepaidStatus = order.custom_prepaid_verification_status || "Not Declared";
        const prepaidTiming = order.custom_delivery_payment_timing || "Collect on Delivery";
        const hasPrepaidPayment = ["Prepaid", "Partially Prepaid"].includes(prepaidTiming);
        const collectionStatus = order.custom_collection_verification_status || "Not Required";
        const driverReturnStatus = order.custom_driver_return_status || "Not Required";
        const deliveryReturnStatus = order.custom_delivery_return_status || "Not Required";
        const deliveryReturnReason = order.custom_delivery_return_reason || "";
        const deliveryReturnNotes = order.custom_delivery_return_notes || "";
        const partialReturnRequest = order.partial_return_request || null;
        const displayOutstanding = partialReturnRequest
            ? Number(partialReturnRequest.remaining_collectible || 0)
            : Number(order.group_outstanding_amount ?? order.outstanding_amount ?? 0);
        const reportedMethod = order.custom_driver_reported_customer_payment_method || "";
        const reportedAmount = Number(order.custom_driver_reported_collected_amount || 0);
        const collectionProof = order.custom_driver_collection_proof || "";
        const activeTrip = Boolean(order.delivery_trip_active);
        const tripName = order.custom_delivery_trip || "";
        const invoiceName = this.escape(order.name);
        const expanded = this.expandedOrders.has(order.name);
        const phone = order.contact_mobile || "";
        const address = order.shipping_address_name || order.customer_address || "";

        const phoneButton = phone
            ? `<a class="btn btn-default btn-sm" href="tel:${this.escape(phone)}">📞 اتصال</a>`
            : "";
        const mapButton = address
            ? `<a class="btn btn-default btn-sm" target="_blank" rel="noopener noreferrer" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}">📍 الخريطة</a>`
            : "";

        let primaryAction = "";
        let secondaryAction = "";
        let returnAction = "";
        let workflowNote = "";
        const tripNote = tripName
            ? `<div class="md-trip-note">🚚 الرحلة ${this.escape(tripName)} — ${this.escape(this.get_trip_status_label(order.trip_operational_status))}</div>`
            : "";

        if (status === "Ready for Delivery") {
            if (hasPrepaidPayment && prepaidStatus === "Awaiting Confirmation") {
                workflowNote = `<div class="md-workflow-note">💳 التحويل في انتظار تأكيد الصيدلية. لا تستلم الأوردر قبل التأكيد.</div>`;
            } else if (addOnStatus === "Returned to Pharmacy") {
                workflowNote = `<div class="md-workflow-note">⏳ في انتظار تجهيز واعتماد فاتورة الإضافة</div>`;
            } else if (addOnStatus === "Driver Returning") {
                workflowNote = activeTrip
                    ? `<div class="md-workflow-note">🏪 أكمل باقي أوردرات الرحلة ثم اضغط رجعت الصيدلية من بطاقة الرحلة</div>`
                    : `<div class="md-workflow-note">🏪 مسجل أنك راجع للصيدلية</div>`;
            } else if (activeTrip) {
                workflowNote = `<div class="md-workflow-note">ابدأ كل أوردرات الرحلة معًا من زر استلمت الرحلة وخرجت</div>`;
            } else {
                primaryAction = `<button type="button" class="btn btn-primary md-change-status md-primary-action" data-invoice="${invoiceName}" data-next-status="Out for Delivery">🛵 استلمت الأوردر وخرجت</button>`;
            }
        }

        if (status === "Out for Delivery") {
            if (addOnStatus === "Driver Returning") {
                if (activeTrip) {
                    workflowNote = `<div class="md-workflow-note">الأصناف المطلوبة: ${this.escape(addOnNotes || "تم تسجيل طلب إضافة أصناف")}<br>أكمل باقي الرحلة، ثم سجّل الرجوع من بطاقة الرحلة.</div>`;
                } else {
                    primaryAction = `<button type="button" class="btn btn-primary md-return-pharmacy md-primary-action" data-invoice="${invoiceName}">🏪 رجعت الصيدلية</button>`;
                    workflowNote = `<div class="md-workflow-note">الأصناف المطلوبة: ${this.escape(addOnNotes || "تم تسجيل طلب إضافة أصناف")}</div>`;
                }
            } else {
                primaryAction = `<button type="button" class="btn btn-success md-change-status md-primary-action" data-invoice="${invoiceName}" data-next-status="Delivered">✅ تم التسليم</button>`;
                secondaryAction = `
                    <button type="button" class="btn btn-default btn-sm md-request-addon" data-invoice="${invoiceName}">➕ العميل طلب إضافة أصناف</button>
                    <button type="button" class="btn btn-warning btn-sm md-partial-return" data-invoice="${invoiceName}">↩️ العميل رجّع صنف</button>
                    <button type="button" class="btn btn-danger btn-sm md-customer-return" data-invoice="${invoiceName}">❌ العميل ألغى الأوردر بالكامل</button>
                `;
            }
        }

        if (status === "Out for Delivery" && partialReturnRequest) {
            const remaining = Number(partialReturnRequest.remaining_collectible || 0);
            primaryAction = remaining > 0.01
                ? `<button type="button" class="btn btn-warning md-record-collection md-primary-action" data-invoice="${invoiceName}">💰 تسجيل صافي التحصيل (${this.escape(this.format_money(remaining))})</button>`
                : `<button type="button" class="btn btn-success md-change-status md-primary-action" data-invoice="${invoiceName}" data-next-status="Delivered">✅ تم تسليم باقي الأوردر</button>`;
            secondaryAction = "";
            workflowNote = `<div class="md-workflow-note">↩️ مرتجع جزئي ${this.escape(partialReturnRequest.name || "")} بقيمة ${this.escape(this.format_money(partialReturnRequest.estimated_return_amount || 0))}. سجّل صافي التحصيل ثم ارجع بالصنف للصيدلية.</div>`;
        }

        if (status === "Returning to Pharmacy") {
            if (activeTrip) {
                workflowNote = `<div class="md-workflow-note">🏪 أكمل باقي أوردرات الرحلة ثم اضغط رجعت الصيدلية من بطاقة الرحلة.</div>`;
            } else {
                primaryAction = `<button type="button" class="btn btn-warning md-driver-returned md-primary-action" data-invoice="${invoiceName}">🏪 رجعت الصيدلية</button>`;
                workflowNote = `<div class="md-workflow-note">السبب: ${this.escape(deliveryReturnReason || "رجوع الأوردر")}<br>${this.escape(deliveryReturnNotes || "")}</div>`;
            }
        }

        if (status === "Returned to Pharmacy") {
            workflowNote = `<div class="md-workflow-note">📦 تم إرجاع البضاعة للصيدلية وينتظر الأوردر مراجعة مدير الشيفت وإنشاء مرتجع المبيعات.</div>`;
        }

        if (status === "Delivered") {
            const outstanding = displayOutstanding;
            if (collectionStatus === "Awaiting Confirmation") {
                workflowNote = `<div class="md-workflow-note">💰 تم تسجيل ${this.escape(this.format_money(reportedAmount))} عن طريق ${this.escape(reportedMethod || "—")} وينتظر تأكيد مدير الشيفت.</div>`;
            } else if (collectionStatus === "Confirmed") {
                workflowNote = `<div class="md-workflow-note">✅ تم تأكيد التحصيل.</div>`;
            } else if (outstanding > 0.01) {
                primaryAction = `<button type="button" class="btn btn-warning md-record-collection md-primary-action" data-invoice="${invoiceName}">💰 تسجيل التحصيل</button>`;
                workflowNote = `<div class="md-workflow-note">⚠️ تم تسليم الأوردر لكن التحصيل لم يُسجل بعد.</div>`;
            }
            if (!activeTrip && driverReturnStatus !== "Returned to Pharmacy") {
                returnAction = `<button type="button" class="btn btn-warning md-driver-returned md-primary-action" data-invoice="${invoiceName}">🏪 رجعت الصيدلية</button>`;
            } else if (driverReturnStatus === "Returned to Pharmacy") {
                workflowNote += partialReturnRequest
                    ? `<div class="md-workflow-note">📦 تم تسجيل رجوع الصنف الجزئي للصيدلية وينتظر مراجعة مدير الشيفت وإنشاء المرتجع.</div>`
                    : `<div class="md-workflow-note">🏪 تم تسجيل رجوع الطيار للصيدلية.</div>`;
            }
        }

        const deliveredMeta = status === "Delivered"
            ? `<div class="md-delivered-meta">تم التسليم${order.custom_duration_in_mins ? ` خلال ${this.escape(order.custom_duration_in_mins)} دقيقة` : ""}</div>`
            : "";

        return `
            <article class="md-order-card ${expanded ? "expanded" : ""}" data-order-card="${invoiceName}">
                <div class="md-order-top">
                    <div class="md-order-head-main">
                        <button type="button" class="md-toggle-order" data-invoice="${invoiceName}" aria-label="فتح تفاصيل الأوردر">▶</button>
                        <div class="md-invoice-name">${invoiceName}</div>
                    </div>
                    <div class="md-order-time">${this.escape(order.creation ? moment(order.creation).format("hh:mm A") : "")}</div>
                </div>
                <div class="md-order-compact-meta">
                    <span class="md-compact-pill">${this.escape(order.customer_name || order.customer || "بدون اسم")}</span>
                    <span class="md-compact-pill">${this.escape(this.format_money(displayOutstanding))}</span>
                    <span class="md-compact-pill">${this.escape(this.get_status_label(status))}</span>
                    ${this.prepaid_badge(order)}
                </div>

                <div class="md-order-details">
                    <div class="md-customer">${this.escape(order.customer_name || order.customer || "بدون اسم")}</div>
                    ${this.info_row("الموبايل", phone || "—")}
                    ${this.info_row("العنوان", address || "—")}
                    ${this.info_row("المطلوب تحصيله", this.format_money(displayOutstanding))}
                    ${hasPrepaidPayment && order.custom_prepaid_amount ? this.info_row("مدفوع مسبقًا", this.format_money(order.custom_prepaid_amount)) : ""}
                    ${hasPrepaidPayment && order.custom_prepaid_method ? this.info_row("طريقة الدفع المسبق", order.custom_prepaid_method) : ""}
                    ${hasPrepaidPayment ? this.info_row("حالة الدفع المسبق", this.get_prepaid_status_label(prepaidStatus)) : ""}
                    ${reportedMethod ? this.info_row("طريقة دفع العميل", reportedMethod) : ""}
                    ${reportedAmount ? this.info_row("المبلغ المعلن", this.format_money(reportedAmount)) : ""}
                    ${collectionProof ? this.info_row("إثبات التحصيل", "تم إرفاق صورة") : ""}
                    ${this.info_row("حالة التحصيل", this.get_collection_status_label(collectionStatus))}
                    ${order.custom_delivery_card_pos_terminal ? this.info_row("ماكينة الفيزا", order.custom_delivery_card_pos_terminal) : ""}
                    ${this.info_row("حالة الأوردر", this.get_status_label(status))}
                    ${driverReturnStatus !== "Not Required" ? this.info_row("حالة رجوع الطيار", this.get_driver_return_status_label(driverReturnStatus)) : ""}
                    ${order.custom_delivery_return_type && order.custom_delivery_return_type !== "Not Required" ? this.info_row("نوع المرتجع", order.custom_delivery_return_type) : ""}
                    ${partialReturnRequest ? this.info_row("طلب المرتجع", partialReturnRequest.name || "") : ""}
                    ${deliveryReturnStatus !== "Not Required" ? this.info_row("حالة المرتجع", this.get_delivery_return_status_label(deliveryReturnStatus)) : ""}
                    ${deliveryReturnReason ? this.info_row("سبب الرجوع", deliveryReturnReason) : ""}
                    ${addOnStatus ? this.info_row("حالة الإضافة", this.get_add_on_status_label(addOnStatus)) : ""}
                    ${order.custom_delivery_attempt_count ? this.info_row("محاولات التوصيل", order.custom_delivery_attempt_count) : ""}
                    ${order.custom_delivery_trip_stop_sequence ? this.info_row("ترتيب الوقفة", order.custom_delivery_trip_stop_sequence) : ""}
                    ${order.add_on_count ? this.info_row("إضافات على الأوردر", `${order.add_on_count} فاتورة إضافية`) : ""}
                    ${deliveredMeta}
                    <div class="md-card-actions">
                        ${tripNote}
                        ${workflowNote}
                        ${primaryAction}
                        ${returnAction}
                        ${secondaryAction}
                        ${collectionProof ? `<a class="btn btn-default btn-sm" href="${this.escape(collectionProof)}" target="_blank" rel="noopener noreferrer">📷 عرض صورة التحويل</a>` : ""}
                        ${phoneButton}
                        ${mapButton}
                    </div>
                </div>
            </article>
        `;
    }

    prepaid_badge(order) {
        const timing = order.custom_delivery_payment_timing || "Collect on Delivery";
        if (!["Prepaid", "Partially Prepaid"].includes(timing)) return "";
        const status = order.custom_prepaid_verification_status || "Not Declared";
        const amount = Number(order.custom_prepaid_amount || 0);
        if (status === "Confirmed") {
            return `<span class="md-payment-badge confirmed">مدفوع ${this.escape(this.format_money(amount))}</span>`;
        }
        if (status === "Awaiting Confirmation") {
            return `<span class="md-payment-badge pending">تحويل غير مؤكد</span>`;
        }
        if (status === "Rejected") {
            return `<span class="md-payment-badge rejected">الدفع مرفوض</span>`;
        }
        return `<span class="md-payment-badge">تحصيل عند التسليم</span>`;
    }

    get_prepaid_status_label(status) {
        return ({
            "Not Declared": "غير مسجل",
            "Awaiting Confirmation": "في انتظار تأكيد الصيدلية",
            "Confirmed": "مؤكد",
            "Rejected": "مرفوض"
        })[status] || status || "غير مسجل";
    }

    get_collection_status_label(status) {
        return ({
            "Not Required": "غير مطلوب",
            "Pending Driver Declaration": "ينتظر إعلان الطيار",
            "Awaiting Confirmation": "في انتظار تأكيد المدير",
            "Confirmed": "مؤكد",
            "Disputed": "يوجد اعتراض"
        })[status] || status || "غير مسجل";
    }

    get_status_label(status) {
        return ({
            "Ready for Delivery": "جاهز للاستلام",
            "Out for Delivery": "خرج للتوصيل",
            "Returning to Pharmacy": "راجع للصيدلية",
            "Returned to Pharmacy": "عاد للصيدلية - بانتظار المراجعة",
            "Cancelled": "ملغي / مرتجع مكتمل",
            "Delivered": "تم التسليم"
        })[status] || status || "—";
    }

    get_driver_return_status_label(status) {
        return ({
            "Not Required": "غير مطلوب",
            "Out With Driver": "الطيار خارج الصيدلية",
            "Returning to Pharmacy": "الطيار راجع للصيدلية",
            "Returned to Pharmacy": "الطيار عاد للصيدلية"
        })[status] || status || "—";
    }

    get_delivery_return_status_label(status) {
        return ({
            "Not Required": "غير مطلوب",
            "Returning to Pharmacy": "راجع للصيدلية",
            "Awaiting Manager Review": "ينتظر مراجعة المدير",
            "Credit Note Draft": "تم إنشاء مسودة مرتجع",
            "Return Completed": "اكتمل المرتجع",
            "Partial Return Requested": "مرتجع جزئي مسجل",
            "Partial Return Returning": "مرتجع جزئي عائد للصيدلية",
            "Partial Return Awaiting Review": "مرتجع جزئي بانتظار المراجعة",
            "Partial Credit Note Draft": "مسودة مرتجع جزئي",
            "Partial Return Completed": "اكتمل المرتجع الجزئي"
        })[status] || status || "—";
    }

    get_stop_status_label(status) {
        return ({
            "Ready": "جاهز",
            "Out for Delivery": "خرج للتوصيل",
            "Delivered": "تم التسليم",
            "Returning for Add-on": "راجع لإضافة أصناف",
            "Returned to Pharmacy": "عاد للصيدلية",
            "Failed": "فشل التوصيل",
            "Cancelled": "ملغي"
        })[status] || status || "—";
    }

    get_trip_status_label(status) {
        return ({
            "Ready": "جاهزة للخروج",
            "Out for Delivery": "خرجت للتوصيل",
            "Partially Delivered": "تم تسليم جزء من الرحلة",
            "Returning to Pharmacy": "راجعة للصيدلية",
            "Completed": "مكتملة",
            "Cancelled": "ملغاة"
        })[status] || status || "—";
    }

    get_add_on_status_label(status) {
        return ({
            "Requested": "تم طلب إضافة أصناف",
            "Driver Returning": "الطيار راجع للصيدلية",
            "Returned to Pharmacy": "عاد للصيدلية - بانتظار التجهيز",
            "Add-on Invoice Created": "تم إنشاء فاتورة الإضافة",
            "Ready for Redelivery": "جاهز للخروج مرة أخرى",
            "Completed": "اكتملت الإضافة"
        })[status] || status || "—";
    }

    format_money(value) {
        return `${Number(value || 0).toFixed(2)} ج.م`;
    }

    info_row(label, value) {
        return `
            <div class="md-info-row">
                <span class="md-info-label">${this.escape(label)}</span>
                <span class="md-info-value">${this.escape(value === 0 || value ? value : "—")}</span>
            </div>
        `;
    }

    escape(value) {
        return frappe.utils.escape_html(String(value ?? ""));
    }
}
