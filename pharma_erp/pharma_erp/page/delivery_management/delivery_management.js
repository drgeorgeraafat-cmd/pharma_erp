frappe.pages["delivery-management"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Delivery Management"),
        single_column: true
    });

    const deliveryPage = new DeliveryManagementPage(wrapper, page);
    page.set_primary_action(__("Refresh"), () => deliveryPage.load_orders(), "refresh");
};


class DeliveryManagementPage {
    constructor(wrapper, page) {
        this.wrapper = wrapper;
        this.page = page;
        this.$main = $(wrapper).find(".layout-main-section");
        this.orders = [];
        this.trips = [];
        this.tripDefaults = {};
        this.selectedOrders = new Set();
        this.expandedOrders = new Set();
        this.expandedTrips = new Set();

        this.setup_page();
        this.setup_events();
        this.load_orders();
    }

    setup_page() {
        this.$main.html(`
            <div class="delivery-management-page" dir="rtl">
                <div class="dm-loading text-muted">جاري تحميل أوردرات الدليفري...</div>

                <div class="dm-content" style="display:none;">
                    <div class="dm-summary"></div>

                    <div class="dm-trip-toolbar">
                        <div>
                            <div class="dm-toolbar-title">تجهيز رحلة توصيل</div>
                            <div class="dm-toolbar-help">
                                حدد الأوردرات الجاهزة لنفس الطيار، ثم أنشئ رحلة واحدة لها.
                            </div>
                        </div>
                        <div class="dm-toolbar-actions">
                            <span class="dm-selected-count">تم تحديد 0</span>
                            <button type="button" class="btn btn-default btn-sm dm-clear-selection">
                                إلغاء التحديد
                            </button>
                            <button type="button" class="btn btn-primary btn-sm dm-create-trip" disabled>
                                🚚 إنشاء رحلة للأوردرات المحددة
                            </button>
                        </div>
                    </div>

                    <div class="dm-trips"></div>

                    <div class="dm-board">
                        ${this.board_column("pending", "في الانتظار")}
                        ${this.board_column("assigned", "تم تعيين الطيار")}
                        ${this.board_column("out", "خرج / راجع للصيدلية")}
                        ${this.board_column("delivered", "تم التسليم")}
                    </div>
                </div>
            </div>
        `);

        this.add_styles();
    }

    board_column(name, label) {
        return `
            <div class="dm-column">
                <div class="dm-column-header ${name}">
                    <span>${label}</span>
                    <span class="dm-count" data-count="${name}">0</span>
                </div>
                <div class="dm-orders" data-column="${name}"></div>
            </div>
        `;
    }

    add_styles() {
        if ($("#delivery-management-styles").length) return;

        $("head").append(`
            <style id="delivery-management-styles">
                .delivery-management-page { padding-top: 10px; }
                .dm-loading {
                    background:#fff; border:1px solid #e5e7eb; border-radius:12px;
                    padding:30px; text-align:center; font-size:15px;
                }
                .dm-summary {
                    display:grid; grid-template-columns:repeat(5,minmax(150px,1fr));
                    gap:12px; margin-bottom:14px;
                }
                .dm-summary-card,
                .dm-trip-toolbar,
                .dm-trip-card {
                    background:#fff; border:1px solid #e5e7eb; border-radius:12px;
                }
                .dm-summary-card { padding:16px; }
                .dm-summary-label { font-size:13px; color:#667085; margin-bottom:8px; }
                .dm-summary-value { font-size:24px; font-weight:800; color:#101828; }

                .dm-trip-toolbar {
                    display:flex; justify-content:space-between; align-items:center;
                    gap:16px; padding:14px 16px; margin-bottom:12px;
                }
                .dm-toolbar-title { font-size:15px; font-weight:800; color:#101828; }
                .dm-toolbar-help { font-size:12px; color:#667085; margin-top:3px; }
                .dm-toolbar-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
                .dm-selected-count {
                    background:#f2f4f7; border-radius:999px; padding:5px 10px;
                    color:#344054; font-size:12px; font-weight:700;
                }

                .dm-trips {
                    display:grid; grid-template-columns:repeat(3,minmax(250px,1fr));
                    gap:10px; margin-bottom:14px;
                }
                .dm-trip-card { padding:13px; border-inline-start:4px solid #2e90fa; }
                .dm-trip-card.out { border-inline-start-color:#7a5af8; }
                .dm-trip-card.returning { border-inline-start-color:#f79009; }
                .dm-trip-card.completed { border-inline-start-color:#12b76a; }
                .dm-trip-top {
                    display:flex; justify-content:space-between; align-items:center;
                    gap:8px;
                }
                .dm-trip-head-main { display:flex; align-items:center; gap:8px; min-width:0; }
                .dm-toggle-trip,.dm-toggle-order {
                    border:0; background:transparent; color:#475467; padding:2px 4px;
                    font-size:14px; cursor:pointer; line-height:1;
                }
                .dm-trip-card.expanded .dm-toggle-trip,.dm-order-card.expanded .dm-toggle-order { transform:rotate(90deg); }
                .dm-trip-details,.dm-order-details { display:none; margin-top:9px; }
                .dm-trip-card.expanded .dm-trip-details,.dm-order-card.expanded .dm-order-details { display:block; }
                .dm-trip-name { color:#175cd3; font-weight:800; cursor:pointer; }
                .dm-trip-badge {
                    background:#f2f4f7; border-radius:999px; padding:4px 8px;
                    font-size:11px; font-weight:700;
                }
                .dm-trip-compact { color:#475467; font-size:11px; display:flex; gap:6px; flex-wrap:wrap; }
                .dm-trip-stops { margin-top:9px; padding-top:8px; border-top:1px dashed #d0d5dd; }
                .dm-trip-stop {
                    display:flex; justify-content:space-between; gap:8px; padding:6px 8px;
                    margin-top:5px; border-radius:7px; background:#f8fafc; font-size:11px;
                }
                .dm-trip-stop-name { color:#175cd3; font-weight:800; direction:ltr; }
                .dm-trip-stop-status { color:#344054; font-weight:700; }
                .dm-trip-actions { display:grid; grid-template-columns:1fr 1fr; gap:7px; margin-top:10px; }
                .dm-trip-actions .btn { width:100%; }
                .dm-trip-primary { grid-column:1/-1; }

                .dm-board {
                    display:grid; grid-template-columns:repeat(4,minmax(260px,1fr));
                    gap:14px; align-items:start; overflow-x:auto; padding-bottom:15px;
                }
                .dm-column {
                    background:#f8f9fa; border:1px solid #e5e7eb; border-radius:12px;
                    min-height:450px; overflow:hidden;
                }
                .dm-column-header {
                    display:flex; justify-content:space-between; align-items:center;
                    padding:14px; font-weight:800; background:#fff; border-bottom:3px solid #d0d5dd;
                }
                .dm-column-header.pending { border-bottom-color:#f79009; }
                .dm-column-header.assigned { border-bottom-color:#2e90fa; }
                .dm-column-header.out { border-bottom-color:#7a5af8; }
                .dm-column-header.delivered { border-bottom-color:#12b76a; }
                .dm-count {
                    display:inline-flex; align-items:center; justify-content:center;
                    min-width:28px; height:28px; padding:0 7px; border-radius:20px;
                    background:#f2f4f7; font-size:13px;
                }
                .dm-orders { padding:10px; }
                .dm-order-card {
                    background:#fff; border:1px solid #e5e7eb; border-radius:10px;
                    padding:13px; margin-bottom:10px; box-shadow:0 1px 2px rgba(16,24,40,.05);
                }
                .dm-order-card.selected { border-color:#2e90fa; box-shadow:0 0 0 2px rgba(46,144,250,.12); }
                .dm-order-top {
                    display:flex; align-items:center; justify-content:space-between; gap:8px;
                }
                .dm-order-compact { display:flex; align-items:center; gap:8px; min-width:0; flex-wrap:wrap; }
                .dm-order-compact-meta {
                    display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-inline-start:auto;
                    color:#475467; font-size:11px;
                }
                .dm-compact-pill,.dm-payment-badge {
                    display:inline-flex; align-items:center; border-radius:999px; padding:3px 7px;
                    background:#f2f4f7; color:#344054; font-size:11px; font-weight:700;
                }
                .dm-payment-badge.confirmed { background:#ecfdf3; color:#027a48; }
                .dm-payment-badge.pending { background:#fffaeb; color:#b54708; }
                .dm-payment-badge.rejected { background:#fef3f2; color:#b42318; }
                .dm-payment-actions { grid-column:1/-1; display:grid; grid-template-columns:repeat(2,1fr); gap:8px; }
                .dm-payment-actions .btn { width:100%; }
                .dm-order-ident { display:flex; align-items:center; gap:8px; min-width:0; }
                .dm-select-order { width:17px; height:17px; margin:0; cursor:pointer; }
                .dm-invoice-name { font-weight:800; color:#175cd3; cursor:pointer; word-break:break-all; }
                .dm-order-time { font-size:12px; color:#667085; direction:ltr; }
                .dm-customer { font-size:15px; font-weight:800; color:#101828; margin-bottom:8px; }
                .dm-info-row {
                    display:flex; justify-content:space-between; gap:10px;
                    padding:5px 0; border-bottom:1px dashed #eaecf0; font-size:13px;
                }
                .dm-info-label { color:#667085; }
                .dm-info-value { color:#101828; font-weight:600; text-align:left; }
                .dm-card-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:12px; }
                .dm-card-actions .btn { width:100%; margin:0; }
                .dm-status-action { grid-column:1/-1; }
                .dm-workflow-note {
                    grid-column:1/-1; padding:9px 10px; border-radius:8px;
                    background:#fff7e6; border:1px solid #f5c26b; color:#7a4b00;
                    font-size:12px; font-weight:700; text-align:center;
                }
                .dm-trip-note {
                    grid-column:1/-1; padding:8px 10px; border-radius:8px;
                    background:#eff8ff; border:1px solid #b2ddff; color:#175cd3;
                    font-size:12px; font-weight:700; text-align:center;
                }
                .dm-empty { padding:35px 10px; text-align:center; color:#98a2b3; font-size:13px; }

                @media (max-width:1200px) {
                    .dm-summary { grid-template-columns:repeat(2,minmax(150px,1fr)); }
                    .dm-trips { grid-template-columns:repeat(2,minmax(240px,1fr)); }
                    .dm-board { grid-template-columns:repeat(4,280px); }
                }
                @media (max-width:700px) {
                    .dm-trip-toolbar { align-items:flex-start; flex-direction:column; }
                    .dm-trips { grid-template-columns:1fr; }
                }
            </style>
        `);
    }

    setup_events() {
        this.$main.off(".deliveryManagement");

        this.$main.on("click.deliveryManagement", ".dm-open-invoice, .dm-invoice-name", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            if (invoiceName) frappe.set_route("Form", "Sales Invoice", invoiceName);
        });

        this.$main.on("click.deliveryManagement", ".dm-open-trip", (event) => {
            const tripName = $(event.currentTarget).attr("data-trip");
            if (tripName) frappe.set_route("Form", "Delivery Trip", tripName);
        });

        this.$main.on("click.deliveryManagement", ".dm-toggle-order", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            if (!invoiceName) return;
            if (this.expandedOrders.has(invoiceName)) this.expandedOrders.delete(invoiceName);
            else this.expandedOrders.add(invoiceName);
            $(event.currentTarget).closest(".dm-order-card").toggleClass("expanded");
        });

        this.$main.on("click.deliveryManagement", ".dm-toggle-trip", (event) => {
            event.preventDefault();
            event.stopPropagation();
            const tripName = $(event.currentTarget).attr("data-trip");
            if (!tripName) return;
            if (this.expandedTrips.has(tripName)) this.expandedTrips.delete(tripName);
            else this.expandedTrips.add(tripName);
            $(event.currentTarget).closest(".dm-trip-card").toggleClass("expanded");
        });

        this.$main.on("change.deliveryManagement", ".dm-select-order", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            if (!invoiceName) return;
            if (event.currentTarget.checked) this.selectedOrders.add(invoiceName);
            else this.selectedOrders.delete(invoiceName);
            this.update_selection_ui();
            $(event.currentTarget).closest(".dm-order-card").toggleClass("selected", event.currentTarget.checked);
        });

        this.$main.on("click.deliveryManagement", ".dm-clear-selection", () => {
            this.selectedOrders.clear();
            this.$main.find(".dm-select-order").prop("checked", false);
            this.$main.find(".dm-order-card").removeClass("selected");
            this.update_selection_ui();
        });

        this.$main.on("click.deliveryManagement", ".dm-create-trip", () => this.open_create_trip_dialog());

        this.$main.on("click.deliveryManagement", ".dm-assign-driver", (event) => {
            const $button = $(event.currentTarget);
            this.open_assign_driver_dialog(
                $button.attr("data-invoice"),
                $button.attr("data-current-driver") || ""
            );
        });

        this.$main.on("click.deliveryManagement", ".dm-transfer-shift", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            const order = this.orders.find((row) => row.name === invoiceName);
            if (order) this.open_transfer_shift_dialog(order);
        });

        this.$main.on("click.deliveryManagement", ".dm-manager-addon-request", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            if (invoiceName) this.open_manager_add_on_request_dialog(invoiceName);
        });

        this.$main.on("click.deliveryManagement", ".dm-cancel-addon-return", (event) => {
            const $button = $(event.currentTarget);
            const invoiceName = $button.attr("data-invoice");
            const addOnStatus = $button.attr("data-addon-status") || "";
            if (invoiceName) this.open_cancel_add_on_request_dialog(invoiceName, addOnStatus);
        });

        this.$main.on("click.deliveryManagement", ".dm-manager-partial-return", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            if (invoiceName) this.open_manager_partial_return_dialog(invoiceName);
        });

        this.$main.on("click.deliveryManagement", ".dm-redeliver-returned", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            if (invoiceName) this.open_redelivery_dialog(invoiceName);
        });

        this.$main.on("click.deliveryManagement", ".dm-create-return-credit", (event) => {
            this.create_return_credit_note($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.deliveryManagement", ".dm-fix-incomplete-return", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            if (!invoiceName) return;
            const url = `/app/pharmacy-pos?return_invoice=${encodeURIComponent(invoiceName)}&delivery_return=1`;
            window.location.assign(url);
        });

        this.$main.on("click.deliveryManagement", ".dm-complete-return", (event) => {
            this.complete_return_review($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.deliveryManagement", ".dm-create-addon", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            if (!invoiceName) return;
            window.open(`/app/pharmacy-pos?add_on=1&parent=${encodeURIComponent(invoiceName)}`, "_blank");
        });

        this.$main.on("click.deliveryManagement", ".dm-change-status", (event) => {
            const $button = $(event.currentTarget);
            this.confirm_delivery_status_change(
                $button.attr("data-invoice"),
                $button.attr("data-next-status")
            );
        });

        this.$main.on("click.deliveryManagement", ".dm-start-trip", (event) => {
            this.confirm_start_trip($(event.currentTarget).attr("data-trip"));
        });

        this.$main.on("click.deliveryManagement", ".dm-return-trip", (event) => {
            this.confirm_return_trip($(event.currentTarget).attr("data-trip"));
        });

        this.$main.on("click.deliveryManagement", ".dm-register-prepaid", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            const order = this.orders.find((row) => row.name === invoiceName);
            if (order) this.open_prepaid_dialog(order);
        });

        this.$main.on("click.deliveryManagement", ".dm-confirm-prepaid", (event) => {
            this.confirm_prepaid($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.deliveryManagement", ".dm-reject-prepaid", (event) => {
            this.reject_prepaid($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.deliveryManagement", ".dm-confirm-collection", (event) => {
            const invoiceName = $(event.currentTarget).attr("data-invoice");
            const order = this.orders.find((row) => row.name === invoiceName);
            if (order) this.confirm_collection(order);
        });

        this.$main.on("click.deliveryManagement", ".dm-reject-collection", (event) => {
            this.reject_collection($(event.currentTarget).attr("data-invoice"));
        });

        this.$main.on("click.deliveryManagement", ".dm-open-payment-entry", (event) => {
            const paymentEntry = $(event.currentTarget).attr("data-payment-entry");
            if (paymentEntry) frappe.set_route("Form", "Payment Entry", paymentEntry);
        });
    }

    load_orders() {
        this.$main.find(".dm-loading").show().text("جاري تحميل أوردرات الدليفري...");
        this.$main.find(".dm-content").hide();

        frappe.call({
            method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.get_delivery_orders",
            freeze: false,
            callback: (response) => {
                const payload = response.message || {};
                if (Array.isArray(payload)) {
                    this.orders = payload;
                    this.trips = [];
                    this.tripDefaults = {};
                } else {
                    this.orders = payload.orders || [];
                    this.trips = payload.trips || [];
                    this.tripDefaults = payload.trip_defaults || {};
                }

                const available = new Set(this.orders.map((order) => order.name));
                this.selectedOrders = new Set(
                    [...this.selectedOrders].filter((name) => available.has(name))
                );
                this.expandedOrders = new Set(
                    [...this.expandedOrders].filter((name) => available.has(name))
                );
                const tripNames = new Set(this.trips.map((trip) => trip.name));
                this.expandedTrips = new Set(
                    [...this.expandedTrips].filter((name) => tripNames.has(name))
                );
                this.render();
            },
            error: () => {
                this.$main.find(".dm-loading").show().text("حدث خطأ أثناء تحميل أوردرات الدليفري.");
            }
        });
    }

    update_selection_ui() {
        const count = this.selectedOrders.size;
        this.$main.find(".dm-selected-count").text(`تم تحديد ${count}`);
        this.$main.find(".dm-create-trip").prop("disabled", count === 0);
    }

    open_create_trip_dialog() {
        const names = [...this.selectedOrders];
        if (!names.length) return;

        const selected = this.orders.filter((order) => names.includes(order.name));
        const drivers = [...new Set(selected.map((order) => order.custom_delivery_boy).filter(Boolean))];
        if (drivers.length !== 1) {
            frappe.msgprint({
                title: __("لا يمكن إنشاء الرحلة"),
                message: __("كل الأوردرات المحددة يجب أن تكون لنفس الطيار."),
                indicator: "red"
            });
            return;
        }

        const driverName = selected[0].delivery_boy_name || drivers[0];
        const currentShift = this.tripDefaults.shift_reference || "";
        if (!currentShift) {
            frappe.msgprint({
                title: __("لا يوجد شيفت مفتوح"),
                message: __("افتح Pharmacy Shift Closing أولًا، ثم اضغط Refresh وأعد إنشاء الرحلة."),
                indicator: "orange"
            });
            return;
        }
        const dialog = new frappe.ui.Dialog({
            title: __("إنشاء رحلة توصيل"),
            fields: [
                {
                    fieldname: "orders_count",
                    fieldtype: "Int",
                    label: __("عدد الأوردرات"),
                    default: names.length,
                    read_only: 1
                },
                {
                    fieldname: "driver_name",
                    fieldtype: "Data",
                    label: __("الطيار"),
                    default: driverName,
                    read_only: 1
                },
                {
                    fieldname: "vehicle",
                    fieldtype: "Link",
                    options: "Vehicle",
                    label: __("Vehicle"),
                    default: this.tripDefaults.vehicle || "CURE-DELIVERY-VEHICLE",
                    reqd: 1
                },
                {
                    fieldname: "delivery_method",
                    fieldtype: "Select",
                    label: __("طريقة التوصيل"),
                    options: "Motorcycle\nCar\nBicycle\nWalking\nOther",
                    default: this.tripDefaults.delivery_method || "Motorcycle",
                    reqd: 1
                },
                {
                    fieldname: "shift_reference",
                    fieldtype: "Link",
                    options: "Pharmacy Shift Closing",
                    label: __("الشيفت المفتوح حاليًا"),
                    default: currentShift,
                    read_only: 1,
                    reqd: 1
                }
            ],
            primary_action_label: __("إنشاء الرحلة"),
            primary_action: (values) => {
                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);

                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.create_delivery_trip",
                    args: {
                        invoice_names: JSON.stringify(names),
                        vehicle: values.vehicle,
                        shift_reference: values.shift_reference || "",
                        delivery_method: values.delivery_method
                    },
                    freeze: true,
                    freeze_message: __("جاري إنشاء رحلة التوصيل..."),
                    callback: (response) => {
                        const result = response.message || {};
                        dialog.hide();
                        this.selectedOrders.clear();
                        frappe.show_alert({
                            message: `${__("تم إنشاء الرحلة")}: ${result.name || ""}`,
                            indicator: "green"
                        });
                        this.load_orders();
                    },
                    error: () => $button.prop("disabled", false)
                });
            }
        });
        dialog.show();
    }

    open_transfer_shift_dialog(order) {
        const targetShift = order.active_delivery_shift || "";
        const currentShift = order.current_delivery_shift || order.custom_delivery_shift || order.custom_pharmacy_shift || "";
        const salesShift = order.sales_shift || order.custom_pharmacy_shift || "";

        if (!targetShift) {
            frappe.msgprint({
                title: __("لا توجد وردية نشطة"),
                message: __("افتح وردية Active أولًا ثم أعد تحميل الصفحة."),
                indicator: "orange"
            });
            return;
        }

        const dialog = new frappe.ui.Dialog({
            title: __("نقل الأوردر إلى الوردية النشطة"),
            fields: [
                {
                    fieldname: "invoice",
                    fieldtype: "Data",
                    label: __("رقم الفاتورة"),
                    default: order.name,
                    read_only: 1
                },
                {
                    fieldname: "sales_shift",
                    fieldtype: "Link",
                    options: "Pharmacy Shift Closing",
                    label: __("وردية البيع الأصلية"),
                    default: salesShift,
                    read_only: 1
                },
                {
                    fieldname: "current_delivery_shift",
                    fieldtype: "Link",
                    options: "Pharmacy Shift Closing",
                    label: __("وردية التوصيل الحالية"),
                    default: currentShift,
                    read_only: 1
                },
                {
                    fieldname: "target_delivery_shift",
                    fieldtype: "Link",
                    options: "Pharmacy Shift Closing",
                    label: __("وردية التوصيل الجديدة"),
                    default: targetShift,
                    read_only: 1
                },
                {
                    fieldname: "reason",
                    fieldtype: "Small Text",
                    label: __("سبب النقل"),
                    default: __("أوردر غير معيّن لطيار وتم ترحيله إلى الوردية النشطة"),
                    reqd: 1
                }
            ],
            primary_action_label: __("تأكيد النقل"),
            primary_action: (values) => {
                dialog.disable_primary_action();
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.transfer_order_to_active_shift",
                    args: {
                        invoice_name: order.name,
                        reason: values.reason
                    },
                    freeze: true,
                    freeze_message: __("جاري نقل الأوردر..."),
                    callback: (response) => {
                        const result = response.message || {};
                        dialog.hide();
                        frappe.show_alert({
                            message: __("تم نقل {0} من {1} إلى {2}", [
                                result.invoice || order.name,
                                result.from_shift || currentShift,
                                result.to_shift || targetShift
                            ]),
                            indicator: "green"
                        }, 7);
                        this.load_orders();
                    },
                    error: () => {
                        dialog.enable_primary_action();
                    }
                });
            }
        });

        dialog.show();
    }

    open_assign_driver_dialog(invoiceName, currentDriver) {
        if (!invoiceName) return;
        const isChange = Boolean(currentDriver);
        const dialog = new frappe.ui.Dialog({
            title: isChange ? __("تغيير الطيار") : __("تعيين الطيار"),
            fields: [
                {
                    fieldname: "invoice_name",
                    fieldtype: "Data",
                    label: __("رقم الفاتورة"),
                    default: invoiceName,
                    read_only: 1
                },
                {
                    fieldname: "employee",
                    fieldtype: "Link",
                    options: "Employee",
                    label: __("الطيار"),
                    default: currentDriver || null,
                    reqd: 1,
                    get_query: () => ({
                        query: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.delivery_driver_query"
                    })
                }
            ],
            primary_action_label: isChange ? __("حفظ تغيير الطيار") : __("تعيين الطيار"),
            primary_action: (values) => {
                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.assign_delivery_driver",
                    args: { invoice_name: invoiceName, employee: values.employee },
                    freeze: true,
                    freeze_message: __("جاري تعيين الطيار..."),
                    callback: (response) => {
                        const result = response.message || {};
                        dialog.hide();
                        frappe.show_alert({
                            message: `${__("تم تعيين الطيار")}: ${result.employee_name || values.employee}`,
                            indicator: "green"
                        });
                        this.load_orders();
                    },
                    error: () => $button.prop("disabled", false)
                });
            }
        });
        dialog.show();
    }

    open_prepaid_dialog(order) {
        const invoiceName = order.name;
        const dialog = new frappe.ui.Dialog({
            title: __("تسجيل دفع مسبق"),
            fields: [
                {
                    fieldname: "invoice_name",
                    fieldtype: "Data",
                    label: __("رقم الفاتورة"),
                    default: invoiceName,
                    read_only: 1
                },
                {
                    fieldname: "outstanding",
                    fieldtype: "Currency",
                    label: __("المتبقي الحالي على الفاتورة"),
                    default: Number(order.outstanding_amount || 0),
                    read_only: 1
                },
                {
                    fieldname: "amount",
                    fieldtype: "Currency",
                    label: __("المبلغ المدفوع مسبقًا"),
                    default: Number(order.custom_prepaid_amount || order.outstanding_amount || 0),
                    reqd: 1
                },
                {
                    fieldname: "prepaid_method",
                    fieldtype: "Select",
                    label: __("طريقة الدفع"),
                    options: "InstaPay\nMobile Wallet\nCard Payment Link\nBank Transfer\nCash at Pharmacy\nOther",
                    default: order.custom_prepaid_method || "InstaPay",
                    reqd: 1
                },
                {
                    fieldname: "transaction_reference",
                    fieldtype: "Data",
                    label: __("رقم العملية / المرجع"),
                    default: order.custom_prepaid_transaction_reference || ""
                },
                {
                    fieldname: "payment_proof",
                    fieldtype: "Attach",
                    label: __("صورة التحويل"),
                    default: order.custom_prepaid_payment_proof || ""
                }
            ],
            primary_action_label: __("حفظ وإرسال للمراجعة"),
            primary_action: (values) => {
                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.register_prepaid_payment",
                    args: {
                        invoice_name: invoiceName,
                        amount: values.amount,
                        prepaid_method: values.prepaid_method,
                        transaction_reference: values.transaction_reference || "",
                        payment_proof: values.payment_proof || ""
                    },
                    freeze: true,
                    freeze_message: __("جاري تسجيل الدفع المسبق..."),
                    callback: () => {
                        dialog.hide();
                        this.expandedOrders.add(invoiceName);
                        frappe.show_alert({
                            message: __("تم تسجيل الدفع المسبق وينتظر التأكيد."),
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

    confirm_prepaid(invoiceName) {
        if (!invoiceName) return;
        const order = this.orders.find((row) => row.name === invoiceName) || {};
        const message = `
            <div style="line-height:1.9">
                <b>${this.escape(invoiceName)}</b><br>
                ${__("المبلغ")}: ${this.escape(this.format_money(order.custom_prepaid_amount || 0))}<br>
                ${__("الطريقة")}: ${this.escape(order.custom_prepaid_method || "—")}<br>
                ${__("المرجع")}: ${this.escape(order.custom_prepaid_transaction_reference || "—")}<br><br>
                ${__("سيتم إنشاء واعتماد Payment Entry وتقليل المبلغ المطلوب تحصيله.")}
            </div>
        `;
        frappe.confirm(message, () => {
            frappe.call({
                method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.confirm_prepaid_payment",
                args: { invoice_name: invoiceName },
                freeze: true,
                freeze_message: __("جاري تأكيد الدفع وإنشاء Payment Entry..."),
                callback: (response) => {
                    const result = response.message || {};
                    this.expandedOrders.add(invoiceName);
                    frappe.show_alert({
                        message: `${__("تم تأكيد الدفع")}${result.custom_prepaid_payment_entry ? `: ${result.custom_prepaid_payment_entry}` : ""}`,
                        indicator: "green"
                    });
                    this.load_orders();
                }
            });
        });
    }

    reject_prepaid(invoiceName) {
        if (!invoiceName) return;
        const dialog = new frappe.ui.Dialog({
            title: __("رفض الدفع المسبق"),
            fields: [
                {
                    fieldname: "reason",
                    fieldtype: "Small Text",
                    label: __("سبب الرفض"),
                    reqd: 1
                }
            ],
            primary_action_label: __("رفض"),
            primary_action: (values) => {
                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.reject_prepaid_payment",
                    args: { invoice_name: invoiceName, reason: values.reason },
                    freeze: true,
                    callback: () => {
                        dialog.hide();
                        this.expandedOrders.add(invoiceName);
                        frappe.show_alert({ message: __("تم رفض الدفع المسبق."), indicator: "red" });
                        this.load_orders();
                    },
                    error: () => $button.prop("disabled", false)
                });
            }
        });
        dialog.show();
    }

    async confirm_collection(order) {
        if (!order || !order.name) return;

        let terminalRows = [];
        try {
            const terminalResponse = await frappe.call({
                method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.get_delivery_card_terminals",
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

        const reported = Number(order.custom_driver_reported_collected_amount || 0);
        const expected = order.partial_return_request
            ? Number(order.partial_return_request.remaining_collectible || 0)
            : Number(order.group_outstanding_amount ?? order.outstanding_amount ?? 0);
        const reportedMethod = order.custom_driver_reported_customer_payment_method || "—";
        const collectionProof = order.custom_driver_collection_proof || "";
        const collectionProofHtml = collectionProof
            ? `
                <div style="padding:8px 0">
                    <a href="${this.escape(collectionProof)}" target="_blank" rel="noopener noreferrer">
                        <img src="${this.escape(collectionProof)}" alt="إثبات التحصيل" style="max-width:100%;max-height:260px;border:1px solid #d1d8dd;border-radius:8px;object-fit:contain">
                    </a>
                    <div style="margin-top:6px">
                        <a href="${this.escape(collectionProof)}" target="_blank" rel="noopener noreferrer">فتح الصورة بالحجم الكامل</a>
                    </div>
                </div>`
            : `<div class="text-muted" style="padding:8px 0">لم يرفق الطيار صورة للتحصيل.</div>`;
        const dialog = new frappe.ui.Dialog({
            title: __("مراجعة تحصيل الطيار"),
            fields: [
                {
                    fieldname: "invoice_name",
                    fieldtype: "Data",
                    label: __("رقم الفاتورة"),
                    default: order.name,
                    read_only: 1
                },
                {
                    fieldname: "payment_method",
                    fieldtype: "Data",
                    label: __("طريقة دفع العميل"),
                    default: reportedMethod,
                    read_only: 1
                },
                {
                    fieldname: "card_pos_terminal",
                    fieldtype: "Select",
                    label: __("ماكينة الفيزا"),
                    options: terminalOptions,
                    default: defaultTerminal,
                    depends_on: `eval:doc.payment_method=="Card"`,
                    mandatory_depends_on: `eval:doc.payment_method=="Card"`,
                    description: terminalDescription || __("لا توجد ماكينات فيزا مفعلة.")
                },
                {
                    fieldname: "expected_amount",
                    fieldtype: "Currency",
                    label: __("المتبقي على الأوردر"),
                    default: expected,
                    read_only: 1
                },
                {
                    fieldname: "reported_amount",
                    fieldtype: "Currency",
                    label: __("المبلغ الذي أعلنه الطيار"),
                    default: reported,
                    read_only: 1
                },
                {
                    fieldname: "collection_proof_preview",
                    fieldtype: "HTML",
                    label: __("صورة التحويل / إيصال الدفع"),
                    options: collectionProofHtml,
                    depends_on: `eval:doc.payment_method!="Cash"`
                },
                {
                    fieldname: "confirmed_amount",
                    fieldtype: "Currency",
                    label: __("المبلغ المؤكد"),
                    default: reported,
                    reqd: 1
                },
                {
                    fieldname: "reason",
                    fieldtype: "Small Text",
                    label: __("ملاحظات المراجعة / سبب الفرق"),
                    default: order.custom_collection_review_notes || ""
                }
            ],
            primary_action_label: __("تأكيد التحصيل"),
            primary_action: (values) => {
                const amount = Number(values.confirmed_amount || 0);
                if (amount <= 0) {
                    frappe.msgprint(__("المبلغ المؤكد يجب أن يكون أكبر من صفر."));
                    return;
                }
                if (amount > expected + 0.01) {
                    frappe.msgprint(__("المبلغ المؤكد لا يمكن أن يتجاوز المتبقي الحالي."));
                    return;
                }
                if (Math.abs(amount - expected) > 0.01 && !String(values.reason || "").trim()) {
                    frappe.msgprint(__("يوجد فرق عن المطلوب. برجاء كتابة سبب الفرق."));
                    return;
                }
                if (reportedMethod === "Card" && !String(values.card_pos_terminal || "").trim()) {
                    frappe.msgprint(__("اختر ماكينة الفيزا التي استقبلت العملية."));
                    return;
                }

                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.confirm_delivery_collection",
                    args: {
                        invoice_name: order.name,
                        confirmed_amount: amount,
                        reason: values.reason || "",
                        card_pos_terminal: values.card_pos_terminal || ""
                    },
                    freeze: true,
                    freeze_message: __("جاري تأكيد التحصيل..."),
                    callback: (response) => {
                        const result = response.message || {};
                        dialog.hide();
                        this.expandedOrders.add(order.name);
                        frappe.show_alert({
                            message: __("تم تأكيد التحصيل بنجاح."),
                            indicator: "green"
                        });
                        this.load_orders();
                    },
                    error: () => $button.prop("disabled", false)
                });
            }
        });
        dialog.show();
    }

    reject_collection(invoiceName) {
        if (!invoiceName) return;
        const dialog = new frappe.ui.Dialog({
            title: __("اعتراض على تحصيل الطيار"),
            fields: [
                {
                    fieldname: "reason",
                    fieldtype: "Small Text",
                    label: __("سبب الاعتراض"),
                    reqd: 1
                }
            ],
            primary_action_label: __("تسجيل الاعتراض"),
            primary_action: (values) => {
                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.reject_delivery_collection",
                    args: { invoice_name: invoiceName, reason: values.reason },
                    freeze: true,
                    callback: () => {
                        dialog.hide();
                        this.expandedOrders.add(invoiceName);
                        frappe.show_alert({ message: __("تم تسجيل الاعتراض."), indicator: "red" });
                        this.load_orders();
                    },
                    error: () => $button.prop("disabled", false)
                });
            }
        });
        dialog.show();
    }

    open_manager_add_on_request_dialog(invoiceName) {
        if (!invoiceName) return;

        const dialog = new frappe.ui.Dialog({
            title: __("إضافة أصناف بطلب من العميل"),
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
                    description: __("اكتب أسماء الأصناف والكميات. سيظهر الطلب فورًا للطيار كراجع للصيدلية لإضافة الأصناف."),
                    reqd: 1
                }
            ],
            primary_action_label: __("تسجيل طلب الإضافة"),
            primary_action: (values) => {
                const notes = String(values.notes || "").trim();
                if (!notes) {
                    frappe.msgprint(__("اكتب الأصناف والكميات التي طلب العميل إضافتها."));
                    return;
                }

                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.request_manager_add_on_return",
                    args: { invoice_name: invoiceName, notes },
                    freeze: true,
                    freeze_message: __("جاري تسجيل طلب إضافة الأصناف..."),
                    callback: () => {
                        dialog.hide();
                        frappe.show_alert({
                            message: __("تم تسجيل طلب الإضافة. أبلغ الطيار باستكمال أوردرات الرحلة ثم الرجوع للصيدلية."),
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

    open_cancel_add_on_request_dialog(invoiceName, addOnStatus) {
        if (!invoiceName) return;

        const driverStillOutside = addOnStatus === "Driver Returning";
        const dialog = new frappe.ui.Dialog({
            title: driverStillOutside
                ? __("إلغاء الإضافة واستكمال التوصيل")
                : __("إلغاء الإضافة وإعادة إرسال الأوردر"),
            fields: [
                {
                    fieldtype: "Select",
                    fieldname: "reason",
                    label: __("سبب الإلغاء"),
                    reqd: 1,
                    options: [
                        "العميل ألغى طلب الإضافة",
                        "تم تسجيل الرجوع للإضافة بالخطأ",
                        "أخرى"
                    ]
                },
                {
                    fieldtype: "Small Text",
                    fieldname: "notes",
                    label: __("ملاحظات")
                },
                {
                    fieldtype: "HTML",
                    fieldname: "explanation",
                    options: driverStillOutside
                        ? `<div class="alert alert-info">سيتم إلغاء طلب الإضافة ويستمر الطيار في نفس محاولة التوصيل بدون الرجوع للصيدلية.</div>`
                        : `<div class="alert alert-info">سيتم إلغاء طلب الإضافة ويصبح الأوردر جاهزًا للخروج مرة أخرى. المحاولة السابقة ستظل محفوظة.</div>`
                }
            ],
            primary_action_label: driverStillOutside
                ? __("إلغاء الإضافة واستكمال التوصيل")
                : __("إلغاء الإضافة وتجهيز الأوردر"),
            primary_action: (values) => {
                let reason = String(values.reason || "").trim();
                const notes = String(values.notes || "").trim();
                if (!reason) {
                    frappe.msgprint(__("اختر سبب إلغاء طلب الإضافة."));
                    return;
                }
                if (reason === "أخرى" && !notes) {
                    frappe.msgprint(__("اكتب ملاحظات عند اختيار أخرى."));
                    return;
                }
                if (notes) reason = `${reason}: ${notes}`;

                dialog.get_primary_btn().prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.cancel_manager_add_on_request",
                    args: { invoice_name: invoiceName, reason },
                    freeze: true,
                    freeze_message: __("جاري إلغاء طلب الإضافة..."),
                    callback: (response) => {
                        dialog.hide();
                        const result = response.message || {};
                        frappe.show_alert({
                            message: result.mode === "continue_current_attempt"
                                ? __("تم إلغاء الإضافة واستمر الطيار في نفس محاولة التوصيل.")
                                : __("تم إلغاء الإضافة وأصبح الأوردر جاهزًا للخروج مرة أخرى."),
                            indicator: "green"
                        }, 6);
                        this.load_orders();
                    },
                    always: () => dialog.get_primary_btn().prop("disabled", false)
                });
            }
        });
        dialog.show();
    }

    open_manager_partial_return_dialog(invoiceName) {
        if (!invoiceName) return;
        frappe.call({
            method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.get_manager_partial_return_items",
            args: { invoice_name: invoiceName },
            freeze: true,
            freeze_message: __("جاري تحميل أصناف الفاتورة..."),
            callback: (response) => {
                const data = response.message || {};
                const items = data.items || [];
                if (!items.length) {
                    frappe.msgprint({
                        title: __("لا توجد أصناف"),
                        message: __("لا توجد أصناف متاحة للمرتجع الجزئي."),
                        indicator: "orange"
                    });
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
                        <td><input type="checkbox" class="dm-pr-check"></td>
                        <td>
                            <strong>${this.escape(item.item_name || item.item_code)}</strong>
                            <br><small>${this.escape(item.item_code)}</small>
                            <br><small><b>${item.source_invoice_type === "Add-on" ? __("فاتورة إضافة") : __("الفاتورة الأصلية")}</b>: ${this.escape(item.source_invoice || "")}</small>
                            ${item.batch_no ? `<br><small>${__("Batch")}: ${this.escape(item.batch_no)}</small>` : ""}
                            <br><small>${__("حجم العبوة")}: ${packSize} ${__("وحدة")}</small>
                        </td>
                        <td>${this.escape(availableLabel)}</td>
                        <td><input type="number" class="form-control dm-pr-boxes" min="0" step="1" value="0"></td>
                        <td><input type="number" class="form-control dm-pr-units" min="0" max="${maxUnits}" step="1" value="0" ${packSize <= 1 ? "disabled" : ""}></td>
                        <td>${this.escape(this.format_money(item.rate || 0))}</td>
                    </tr>
                `;
                }).join("");

                const dialog = new frappe.ui.Dialog({
                    title: __("تسجيل مرتجع جزئي بواسطة مدير الشيفت"),
                    size: "large",
                    fields: [
                        {
                            fieldtype: "HTML",
                            fieldname: "manager_help",
                            options: `
                                <div class="alert alert-info">
                                    <strong>${__("الطيار ما زال عند العميل.")}</strong><br>
                                    ${__("حدد الصنف والكمية التي سيعيدها الطيار. سيظهر صافي المبلغ المطلوب تحصيله له فورًا، لكن المخزون لن يرجع إلا بعد وصول الصنف للصيدلية ومراجعته.")}
                                </div>
                            `
                        },
                        {
                            fieldtype: "HTML",
                            fieldname: "items_html",
                            options: `
                                <table class="table table-bordered">
                                    <thead><tr>
                                        <th></th><th>${__("الصنف")}</th><th>${__("المتاح")}</th>
                                        <th>${__("علب")}</th><th>${__("وحدات")}</th><th>${__("السعر")}</th>
                                    </tr></thead>
                                    <tbody>${rows}</tbody>
                                </table>
                                <div class="dm-pr-total text-muted" style="font-weight:600;"></div>
                            `
                        },
                        {
                            fieldtype: "Select",
                            fieldname: "reason",
                            label: __("سبب المرتجع"),
                            reqd: 1,
                            options: [
                                "Item Rejected by Customer",
                                "Wrong Item",
                                "Damaged Item",
                                "Payment Problem",
                                "Other"
                            ].join("\n")
                        },
                        {
                            fieldtype: "Small Text",
                            fieldname: "notes",
                            label: __("ملاحظات الطيار / العميل")
                        }
                    ],
                    primary_action_label: __("اعتماد المرتجع وإظهار صافي التحصيل"),
                    primary_action: (values) => {
                        const wrapper = dialog.get_field("items_html").$wrapper[0];
                        const selected = [];
                        let estimated = 0;
                        wrapper.querySelectorAll("tbody tr").forEach((row) => {
                            if (!row.querySelector(".dm-pr-check")?.checked) return;
                            const item = items[Number(row.dataset.index || 0)];
                            const boxQty = Number(row.querySelector(".dm-pr-boxes")?.value || 0);
                            const unitQty = Number(row.querySelector(".dm-pr-units")?.value || 0);
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
                            if (qty > 0) {
                                selected.push({
                                    source_invoice: item.source_invoice,
                                    source_item: item.source_item,
                                    box_qty: boxQty,
                                    unit_qty: unitQty,
                                    pack_size: packSize,
                                    qty
                                });
                                estimated += qty * Number(item.rate || 0);
                            }
                        });

                        if (!selected.length) {
                            frappe.msgprint({
                                title: __("حدد الأصناف"),
                                message: __("اختر صنفًا واحدًا على الأقل واكتب كمية المرتجع."),
                                indicator: "orange"
                            });
                            return;
                        }
                        if (values.reason === "Other" && !(values.notes || "").trim()) {
                            frappe.msgprint({
                                title: __("الملاحظات مطلوبة"),
                                message: __("اكتب سبب المرتجع الجزئي."),
                                indicator: "orange"
                            });
                            return;
                        }

                        frappe.confirm(
                            `${__("قيمة المرتجع التقديرية")}: ${this.format_money(estimated)}<br>${__("لن يرجع المخزون الآن؛ سيعود بعد استلام الصنف فعليًا بالصيدلية.")}`,
                            () => {
                                const $button = dialog.get_primary_btn();
                                $button.prop("disabled", true);
                                frappe.call({
                                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.create_manager_partial_return_request",
                                    args: {
                                        invoice_name: invoiceName,
                                        items: JSON.stringify(selected),
                                        reason: values.reason,
                                        notes: values.notes || ""
                                    },
                                    freeze: true,
                                    freeze_message: __("جاري تسجيل المرتجع الجزئي..."),
                                    callback: (r) => {
                                        dialog.hide();
                                        const result = r.message || {};
                                        frappe.msgprint({
                                            title: __("تم اعتماد المرتجع الجزئي"),
                                            indicator: "green",
                                            message: `${__("رقم الطلب")}: ${this.escape(result.name || "")}<br>${__("قيمة المرتجع")}: ${this.format_money(result.estimated_return_amount || 0)}<br>${__("المطلوب من الطيار تحصيله")}: ${this.format_money(result.remaining_collectible || 0)}<br>${__("بعد رجوع الطيار، راجع الصنف وأنشئ Credit Note من Pharmacy POS.")}`
                                        });
                                        this.expandedOrders.add(invoiceName);
                                        this.load_orders();
                                    },
                                    error: () => $button.prop("disabled", false)
                                });
                            }
                        );
                    }
                });
                dialog.show();
                const partialWrapper = dialog.get_field("items_html").$wrapper[0];
                const updateEstimatedReturn = () => {
                    let total = 0;
                    let invalid = false;
                    partialWrapper.querySelectorAll("tbody tr").forEach((row) => {
                        if (!row.querySelector(".dm-pr-check")?.checked) return;
                        const item = items[Number(row.dataset.index || 0)];
                        const boxQty = Number(row.querySelector(".dm-pr-boxes")?.value || 0);
                        const unitQty = Number(row.querySelector(".dm-pr-units")?.value || 0);
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
                    const totalNode = partialWrapper.querySelector(".dm-pr-total");
                    if (totalNode) {
                        totalNode.innerHTML = invalid
                            ? `<span class="text-danger">${__("راجع كمية العلب والوحدات المدخلة.")}</span>`
                            : `${__("قيمة المرتجع التقديرية")}: ${this.format_money(total)}`;
                    }
                };
                partialWrapper.addEventListener("input", (event) => {
                    if (event.target.matches(".dm-pr-boxes, .dm-pr-units")) {
                        const row = event.target.closest("tr");
                        const checkbox = row?.querySelector(".dm-pr-check");
                        if (checkbox && Number(event.target.value || 0) > 0) checkbox.checked = true;
                    }
                    updateEstimatedReturn();
                });
                partialWrapper.addEventListener("change", updateEstimatedReturn);
                updateEstimatedReturn();
            }
        });
    }

    create_return_credit_note(invoiceName) {
        if (!invoiceName) return;
        frappe.confirm(
            __("هل استلم مدير الشيفت البضاعة المرتجعة فعليًا؟ سيتم فتح مرتجع الفاتورة داخل Pharmacy POS."),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.confirm_delivery_return_received",
                args: { invoice_name: invoiceName },
                freeze: true,
                freeze_message: __("جاري تأكيد استلام البضاعة المرتجعة..."),
                callback: (response) => {
                    const result = response.message || {};
                    const requestName = result.name || result.request || "";
                    const requestPart = requestName ? `&return_request=${encodeURIComponent(requestName)}` : "";
                    const url = `/app/pharmacy-pos?return_invoice=${encodeURIComponent(invoiceName)}&delivery_return=1${requestPart}`;
                    window.location.assign(url);
                }
            })
        );
    }

    complete_return_review(invoiceName) {
        if (!invoiceName) return;
        frappe.confirm(
            __("هل تم اعتماد مرتجع المبيعات وإعادة البضاعة للمخزن؟"),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.complete_delivery_return",
                args: { invoice_name: invoiceName },
                freeze: true,
                freeze_message: __("جاري إكمال مراجعة المرتجع..."),
                callback: (response) => {
                    const result = response.message || {};
                    frappe.show_alert({
                        message: result.credit_note
                            ? `${__("اكتمل المرتجع")}: ${result.credit_note}`
                            : __("اكتمل المرتجع."),
                        indicator: "green"
                    });
                    this.load_orders();
                }
            })
        );
    }

    open_redelivery_dialog(invoiceName) {
        if (!invoiceName) return;
        const dialog = new frappe.ui.Dialog({
            title: __("إعادة إرسال الأوردر"),
            fields: [
                {
                    fieldname: "message",
                    fieldtype: "HTML",
                    options: `
                        <div class="alert alert-warning" style="margin-bottom: 0;">
                            ${__("سيتم إلغاء طلب المرتجع المفتوح فقط، مع الاحتفاظ به وبمحاولة التوصيل السابقة في السجل. لن يتم إلغاء الفاتورة أو أي Payment Entry معتمد.")}
                        </div>
                    `
                },
                {
                    fieldname: "notes",
                    fieldtype: "Small Text",
                    label: __("سبب إعادة الإرسال"),
                    reqd: 1,
                    default: __("العميل اتصل وطلب إعادة إرسال الأوردر.")
                }
            ],
            primary_action_label: __("إلغاء المرتجع وتجهيز الأوردر للتوصيل"),
            primary_action: (values) => {
                const $button = dialog.get_primary_btn();
                $button.prop("disabled", true);
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.redeliver_returned_order",
                    args: {
                        invoice_name: invoiceName,
                        notes: values.notes
                    },
                    freeze: true,
                    freeze_message: __("جاري تجهيز الأوردر لإعادة التوصيل..."),
                    callback: (response) => {
                        const result = response.message || {};
                        dialog.hide();
                        this.expandedOrders.add(invoiceName);
                        frappe.msgprint({
                            title: __("الأوردر جاهز لإعادة التوصيل"),
                            message: `${__("تم إلغاء طلب المرتجع")}: ${this.escape(result.cancelled_return_request || "—")}<br>
                                ${__("المطلوب الحالي من العميل")}: ${this.escape(this.format_money(result.outstanding_amount || 0))}<br>
                                ${result.delivery_boy ? __("يمكن الإبقاء على نفس الطيار أو تغييره قبل الخروج.") : __("عيّن طيارًا قبل خروج الأوردر.")}`,
                            indicator: "green"
                        });
                        this.load_orders();
                    },
                    error: () => $button.prop("disabled", false)
                });
            }
        });
        dialog.show();
    }

    confirm_start_trip(tripName) {
        if (!tripName) return;
        frappe.confirm(
            __("هل استلم الطيار كل أوردرات الرحلة وخرج للتوصيل؟"),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.start_delivery_trip",
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
            __("هل رجع الطيار بالصيدلية بعد إنهاء كل أوردرات الرحلة؟"),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.return_delivery_trip",
                args: { trip_name: tripName },
                freeze: true,
                freeze_message: __("جاري إغلاق الرحلة..."),
                callback: (response) => {
                    const result = response.message || {};
                    frappe.show_alert({ message: __("تم تسجيل رجوع الرحلة."), indicator: "green" });
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

    confirm_delivery_status_change(invoiceName, nextStatus) {
        if (!invoiceName || !nextStatus) return;
        const isOut = nextStatus === "Out for Delivery";
        frappe.confirm(
            isOut
                ? __("هل أنت متأكد أن الطيار استلم الأوردر وخرج للتوصيل؟")
                : __("هل أنت متأكد أن الأوردر تم تسليمه للعميل؟"),
            () => frappe.call({
                method: "pharma_erp.pharma_erp.page.delivery_management.delivery_management.update_delivery_status",
                args: { invoice_name: invoiceName, new_status: nextStatus },
                freeze: true,
                freeze_message: isOut ? __("جاري تسجيل خروج الأوردر...") : __("جاري تسجيل التسليم..."),
                callback: (response) => {
                    const result = response.message || {};
                    frappe.show_alert({
                        message: isOut ? __("تم تسجيل خروج الأوردر للتوصيل.") : __("تم تسجيل تسليم الأوردر بنجاح."),
                        indicator: "green"
                    });
                    if (!isOut && result.duration_in_mins) {
                        frappe.msgprint({
                            title: __("مدة التوصيل"),
                            message: `${__("تم تسليم الأوردر خلال")} ${result.duration_in_mins} ${__("دقيقة")}.`,
                            indicator: "green"
                        });
                    }
                    this.load_orders();
                }
            })
        );
    }

    get_order_group(order) {
        const status = order.custom_delivery_status || "";
        const partialReturnRequest = order.partial_return_request || null;
        const requestStatus = partialReturnRequest?.status || "";
        const partialReturnOpen = Boolean(
            partialReturnRequest
            && !["Partial Return Completed", "Full Return Completed", "Cancelled"].includes(requestStatus)
        );

        // The sale can be delivered while the rejected item is still moving
        // back to the pharmacy. Keep it on the operational board until review.
        if (partialReturnOpen) return "out";
        if (status === "Delivered") return "delivered";
        if (["Out for Delivery", "Returning to Pharmacy"].includes(status)) return "out";
        if (status === "Returned to Pharmacy") return "assigned";
        if (order.custom_delivery_boy) return "assigned";
        return "pending";
    }

    get_status_label(status) {
        return ({
            "Draft": "في الانتظار",
            "Ready for Delivery": "جاهز للتوصيل",
            "Out for Delivery": "خرج للتوصيل",
            "Returning to Pharmacy": "راجع للصيدلية",
            "Returned to Pharmacy": "عاد للصيدلية - بانتظار المراجعة",
            "Cancelled": "ملغي / مرتجع مكتمل",
            "Delivered": "تم التسليم"
        })[status] || status || "في الانتظار";
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
            "Credit Note Draft": "مسودة Credit Note",
            "Return Completed": "اكتمل المرتجع",
            "Partial Return Requested": "مرتجع جزئي مسجل",
            "Partial Return Returning": "مرتجع جزئي عائد للصيدلية",
            "Partial Return Awaiting Review": "مرتجع جزئي بانتظار المراجعة",
            "Partial Credit Note Draft": "مسودة مرتجع جزئي",
            "Partial Return Completed": "اكتمل المرتجع الجزئي"
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

    render() {
        const groups = { pending: [], assigned: [], out: [], delivered: [] };
        this.orders.forEach((order) => groups[this.get_order_group(order)].push(order));

        this.render_summary(groups);
        this.render_trips();
        Object.keys(groups).forEach((name) => this.render_column(name, groups[name]));
        this.update_selection_ui();

        this.$main.find(".dm-loading").hide();
        this.$main.find(".dm-content").show();
    }

    render_summary(groups) {
        const totalAmount = this.orders.reduce(
            (total, order) => total + Number(order.group_grand_total ?? order.grand_total ?? 0), 0
        );
        const outstanding = this.orders.reduce((total, order) => {
            const collectible = order.partial_return_request
                ? Number(order.partial_return_request.remaining_collectible || 0)
                : Number(order.group_outstanding_amount ?? order.outstanding_amount ?? 0);
            return total + collectible;
        }, 0);
        this.$main.find(".dm-summary").html(`
            ${this.summary_card("إجمالي أوردرات اليوم", this.orders.length)}
            ${this.summary_card("في الانتظار", groups.pending.length)}
            ${this.summary_card("خارج / مرتجع جاري", groups.out.length)}
            ${this.summary_card("إجمالي قيمة الأوردرات", this.format_money(totalAmount))}
            ${this.summary_card("المطلوب تحصيله", this.format_money(outstanding))}
        `);
    }

    summary_card(label, value) {
        return `
            <div class="dm-summary-card">
                <div class="dm-summary-label">${this.escape(label)}</div>
                <div class="dm-summary-value">${this.escape(value)}</div>
            </div>
        `;
    }

    render_trips() {
        const $container = this.$main.find(".dm-trips");
        if (!this.trips.length) {
            $container.empty();
            return;
        }

        const sorted = [...this.trips].sort((a, b) => String(b.creation || "").localeCompare(String(a.creation || "")));
        $container.html(sorted.map((trip) => this.trip_card(trip)).join(""));
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
            ? `<button type="button" class="btn btn-primary btn-sm dm-start-trip dm-trip-primary" data-trip="${name}">🛵 خرجت الرحلة للتوصيل</button>`
            : "";
        const returnButton = trip.can_return
            ? `<button type="button" class="btn btn-warning btn-sm dm-return-trip dm-trip-primary" data-trip="${name}">🏪 رجعت الرحلة للصيدلية</button>`
            : "";
        const stops = (trip.stops || []).map((stop) => `
            <div class="dm-trip-stop">
                <span class="dm-trip-stop-name">${this.escape(stop.invoice || `Stop ${stop.idx || ""}`)}</span>
                <span class="dm-trip-stop-status">${this.escape(this.get_stop_status_label(stop.status))}</span>
            </div>
        `).join("");

        return `
            <div class="dm-trip-card ${cssClass} ${expanded ? "expanded" : ""}" data-trip-card="${name}">
                <div class="dm-trip-top">
                    <div class="dm-trip-head-main">
                        <button type="button" class="dm-toggle-trip" data-trip="${name}" aria-label="فتح تفاصيل الرحلة">▶</button>
                        <div class="dm-trip-name" data-trip="${name}">${name}</div>
                    </div>
                    <div class="dm-trip-badge">${this.escape(this.get_trip_status_label(status))}</div>
                </div>
                <div class="dm-trip-compact">
                    <span class="dm-compact-pill">${this.escape(trip.driver_name || trip.employee || "—")}</span>
                    <span class="dm-compact-pill">${this.escape(trip.custom_total_stops || (trip.invoice_names || []).length || 0)} أوردر</span>
                    <span class="dm-compact-pill">${this.escape(this.format_money(trip.custom_expected_collection || 0))}</span>
                </div>
                <div class="dm-trip-details">
                    ${this.info_row("الطيار", trip.driver_name || trip.employee || "—")}
                    ${this.info_row("عدد الوقفات", trip.custom_total_stops || (trip.invoice_names || []).length || 0)}
                    ${this.info_row("تم التسليم", trip.custom_delivered_stops || 0)}
                    ${this.info_row("المتبقي", trip.custom_pending_stops || 0)}
                    ${this.info_row("المدفوع مسبقًا", this.format_money(trip.custom_prepaid_total || 0))}
                    ${this.info_row("المطلوب تحصيله", this.format_money(trip.custom_expected_collection || 0))}
                    ${stops ? `<div class="dm-trip-stops">${stops}</div>` : ""}
                    <div class="dm-trip-actions">
                        ${startButton}
                        ${returnButton}
                        <button type="button" class="btn btn-default btn-sm dm-open-trip" data-trip="${name}">فتح الرحلة</button>
                    </div>
                </div>
            </div>
        `;
    }

    render_column(groupName, orders) {
        const $column = this.$main.find(`.dm-orders[data-column="${groupName}"]`);
        this.$main.find(`.dm-count[data-count="${groupName}"]`).text(orders.length);
        if (!orders.length) {
            $column.html(`<div class="dm-empty">لا توجد أوردرات في هذه الحالة</div>`);
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
        const prepaidPending = hasPrepaidPayment && prepaidStatus === "Awaiting Confirmation";
        const collectionStatus = order.custom_collection_verification_status || "Not Required";
        const driverReturnStatus = order.custom_driver_return_status || "Not Required";
        const deliveryReturnStatus = order.custom_delivery_return_status || "Not Required";
        const deliveryReturnReason = order.custom_delivery_return_reason || "";
        const deliveryReturnNotes = order.custom_delivery_return_notes || "";
        const returnCreditNote = order.custom_delivery_return_credit_note || "";
        const partialReturnRequest = order.partial_return_request || null;
        const partialRequestStatus = partialReturnRequest?.status || "";
        const partialRequestCreditNotes = Array.isArray(partialReturnRequest?.credit_notes)
            ? partialReturnRequest.credit_notes.filter(Boolean)
            : [];
        const deliveryReturnType = order.custom_delivery_return_type || "Not Required";
        const displayOutstanding = partialReturnRequest
            ? Number(partialReturnRequest.remaining_collectible || 0)
            : Number(order.group_outstanding_amount ?? order.outstanding_amount ?? 0);
        const reportedMethod = order.custom_driver_reported_customer_payment_method || "";
        const reportedAmount = Number(order.custom_driver_reported_collected_amount || 0);
        const collectionProof = order.custom_driver_collection_proof || "";
        const invoiceName = this.escape(order.name);
        const activeTrip = Boolean(order.delivery_trip_active);
        const tripName = order.custom_delivery_trip || "";
        const selected = this.selectedOrders.has(order.name);
        const expanded = this.expandedOrders.has(order.name);
        const unresolvedReturnBalance = ["Cancelled"].includes(status)
            && Math.abs(Number(order.group_outstanding_amount ?? order.outstanding_amount ?? 0)) > 0.01;
        const displayStatusLabel = unresolvedReturnBalance
            ? "مرتجع يحتاج تسوية مالية"
            : this.get_status_label(status);
        const selectable = status === "Ready for Delivery"
            && Boolean(order.custom_delivery_boy)
            && !activeTrip
            && order.can_depart !== false
            && addOnStatus !== "Driver Returning"
            && addOnStatus !== "Returned to Pharmacy";

        const checkbox = selectable
            ? `<input type="checkbox" class="dm-select-order" data-invoice="${invoiceName}" ${selected ? "checked" : ""}>`
            : "";
        const canAssign = !["Out for Delivery", "Delivered", "Returning to Pharmacy", "Returned to Pharmacy", "Cancelled"].includes(status) && !activeTrip;
        const assignButton = canAssign
            ? `<button type="button" class="btn btn-primary btn-sm dm-assign-driver" data-invoice="${invoiceName}" data-current-driver="${this.escape(order.custom_delivery_boy || "")}">${order.custom_delivery_boy ? "تغيير الطيار" : "تعيين الطيار"}</button>`
            : "";

        const transferButton = order.can_transfer_to_active_shift
            ? `<button type="button" class="btn btn-default btn-sm dm-transfer-shift dm-status-action" data-invoice="${invoiceName}">🔄 نقل إلى الوردية النشطة (${this.escape(order.active_delivery_shift || "")})</button>`
            : "";

        const canRequestAddOnFromManager = status === "Out for Delivery"
            && Boolean(order.custom_delivery_boy)
            && !partialReturnRequest
            && deliveryReturnType !== "Full Order Cancellation"
            && !["Driver Returning", "Returned to Pharmacy"].includes(addOnStatus);
        const canCreateAddOn = !["Delivered", "Out for Delivery", "Returning to Pharmacy", "Returned to Pharmacy", "Cancelled"].includes(status)
            && addOnStatus !== "Driver Returning";
        const addOnButton = canRequestAddOnFromManager
            ? `<button type="button" class="btn btn-default btn-sm dm-manager-addon-request" data-invoice="${invoiceName}">➕ إضافة أصناف</button>`
            : (canCreateAddOn
                ? `<button type="button" class="btn btn-default btn-sm dm-create-addon" data-invoice="${invoiceName}">${addOnStatus === "Returned to Pharmacy" ? "➕ فتح فاتورة الإضافة" : "➕ إضافة أصناف"}</button>`
                : "");

        const canCancelAddOnRequest = ["Driver Returning", "Returned to Pharmacy"].includes(addOnStatus)
            && !partialReturnRequest
            && deliveryReturnType !== "Full Order Cancellation";
        const cancelAddOnButton = canCancelAddOnRequest
            ? `<button type="button" class="btn btn-warning btn-sm dm-cancel-addon-return dm-status-action" data-invoice="${invoiceName}" data-addon-status="${this.escape(addOnStatus)}">${addOnStatus === "Driver Returning" ? "↩️ إلغاء الإضافة واستكمال التوصيل" : "↩️ إلغاء الإضافة وإعادة إرسال الأوردر"}</button>`
            : "";

        const managerPartialReturnButton = (
            status === "Out for Delivery"
            && Boolean(order.custom_delivery_boy)
            && !partialReturnRequest
            && deliveryReturnType !== "Full Order Cancellation"
            && addOnStatus !== "Driver Returning"
        )
            ? `<button type="button" class="btn btn-warning btn-sm dm-manager-partial-return dm-status-action" data-invoice="${invoiceName}">↩️ مدير الشيفت: تسجيل مرتجع جزئي</button>`
            : "";

        const canRedeliverReturnedOrder = Boolean(
            partialReturnRequest
            && driverReturnStatus === "Returned to Pharmacy"
            && !activeTrip
            && ["Full Order Cancellation", "Partial Item Return"].includes(deliveryReturnType)
            && ![
                "Credit Note Draft",
                "Partial Return Completed",
                "Full Return Completed",
                "Cancelled"
            ].includes(partialRequestStatus)
            && !partialReturnRequest.credit_note
            && partialRequestCreditNotes.length === 0
            && !["Awaiting Confirmation", "Disputed"].includes(collectionStatus)
        );
        const redeliveryButton = canRedeliverReturnedOrder
            ? `<button type="button" class="btn btn-primary btn-sm dm-redeliver-returned dm-status-action" data-invoice="${invoiceName}">🔁 إعادة إرسال الأوردر</button>`
            : "";

        let statusButton = "";
        let returnAction = "";
        let workflowNote = "";
        let tripNote = "";

        if (activeTrip) {
            tripNote = `<div class="dm-trip-note">🚚 ضمن الرحلة ${this.escape(tripName)} — ${this.escape(this.get_trip_status_label(order.trip_operational_status))}</div>`;
        }

        if (status === "Ready for Delivery" && order.custom_delivery_boy) {
            if (prepaidPending) {
                workflowNote = `<div class="dm-workflow-note">💳 الدفع المسبق في انتظار التأكيد. لا يمكن خروج الأوردر قبل المراجعة.</div>`;
            } else if (addOnStatus === "Returned to Pharmacy") {
                workflowNote = `<div class="dm-workflow-note">⏳ الطيار عاد للصيدلية. أنشئ واعتمد فاتورة الإضافة أولًا.</div>`;
            } else if (addOnStatus === "Driver Returning") {
                workflowNote = `<div class="dm-workflow-note">🏪 الطيار مسجل أنه راجع للصيدلية</div>`;
            } else if (!activeTrip && order.can_depart !== false) {
                statusButton = `<button type="button" class="btn btn-primary btn-sm dm-change-status dm-status-action" data-invoice="${invoiceName}" data-next-status="Out for Delivery">🛵 خرج للتوصيل</button>`;
            }
        }

        if (status === "Out for Delivery") {
            if (addOnStatus === "Driver Returning") {
                workflowNote = `<div class="dm-workflow-note">🏪 الطيار راجع للصيدلية لإضافة أصناف${addOnNotes ? `<br>${this.escape(addOnNotes)}` : ""}</div>`;
            } else if (displayOutstanding > 0.01) {
                workflowNote = `<div class="dm-workflow-note">💰 الطيار يسجل التسليم وطريقة الدفع والمبلغ من صفحة My Deliveries.</div>`;
            } else {
                statusButton = `<button type="button" class="btn btn-success btn-sm dm-change-status dm-status-action" data-invoice="${invoiceName}" data-next-status="Delivered">✅ تم التسليم</button>`;
            }
        }

        if (status === "Returning to Pharmacy") {
            workflowNote = `<div class="dm-workflow-note">🏪 الطيار راجع بالصيدلية ومعه البضاعة. السبب: ${this.escape(deliveryReturnReason || "رجوع الأوردر")}${deliveryReturnNotes ? `<br>${this.escape(deliveryReturnNotes)}` : ""}</div>`;
        }

        if (partialReturnRequest && deliveryReturnType === "Partial Item Return") {
            const managerReviewReady = (
                driverReturnStatus === "Returned to Pharmacy"
                && !["Credit Note Draft", "Partial Return Completed", "Full Return Completed", "Cancelled"].includes(partialRequestStatus)
            );
            if (
                deliveryReturnStatus === "Partial Return Awaiting Review"
                || partialRequestStatus === "Awaiting Manager Review"
                || managerReviewReady
            ) {
                workflowNote = `<div class="dm-workflow-note">📦 الطيار رجع بالصنف الجزئي. أكد الاستلام وافتح المرتجع المحدد في Pharmacy POS.</div>`;
                returnAction = `<button type="button" class="btn btn-warning btn-sm dm-create-return-credit dm-status-action" data-invoice="${invoiceName}">📦 استلام المرتجع الجزئي وفتحه في Pharmacy POS</button>`;
            } else if (
                deliveryReturnStatus === "Partial Credit Note Draft"
                || partialRequestStatus === "Credit Note Draft"
            ) {
                workflowNote = `<div class="dm-workflow-note">🧾 تم إنشاء مسودة مرتجع جزئي ${this.escape(returnCreditNote || partialReturnRequest.credit_note || "")}. اعتمدها ثم أكمل المراجعة.</div>`;
                returnAction = `
                    ${(returnCreditNote || partialReturnRequest.credit_note) ? `<button type="button" class="btn btn-default btn-sm dm-open-invoice" data-invoice="${this.escape(returnCreditNote || partialReturnRequest.credit_note)}">فتح مرتجع المبيعات</button>` : ""}
                    <button type="button" class="btn btn-success btn-sm dm-complete-return dm-status-action" data-invoice="${invoiceName}">✅ إكمال المرتجع الجزئي</button>
                `;
            } else if (
                deliveryReturnStatus === "Partial Return Completed"
                || partialRequestStatus === "Partial Return Completed"
            ) {
                workflowNote = `<div class="dm-workflow-note">✅ اكتمل المرتجع الجزئي. الأوردر يظل تم تسليمه، والمتبقي المالي حسب الفاتورة.</div>`;
            }
        }

        if (unresolvedReturnBalance) {
            returnAction = `<button type="button" class="btn btn-warning btn-sm dm-fix-incomplete-return dm-status-action" data-invoice="${invoiceName}">🧾 استكمال مرتجع المبلغ المتبقي</button>`;
        }

        if (status === "Returned to Pharmacy" && deliveryReturnType !== "Partial Item Return") {
            if (deliveryReturnStatus === "Awaiting Manager Review") {
                workflowNote = `<div class="dm-workflow-note">📦 تم رجوع البضاعة فعليًا. أكد الاستلام وأنشئ مرتجع المبيعات.</div>`;
                returnAction = `<button type="button" class="btn btn-warning btn-sm dm-create-return-credit dm-status-action" data-invoice="${invoiceName}">📦 استلام المرتجع وفتحه في Pharmacy POS</button>`;
            } else if (deliveryReturnStatus === "Credit Note Draft") {
                workflowNote = `<div class="dm-workflow-note">🧾 تم إنشاء مسودة مرتجع ${this.escape(returnCreditNote || "")}. اعتمدها ثم أكمل مراجعة المرتجع.</div>`;
                returnAction = `
                    ${returnCreditNote ? `<button type="button" class="btn btn-default btn-sm dm-open-invoice" data-invoice="${this.escape(returnCreditNote)}">فتح مرتجع المبيعات</button>` : ""}
                    <button type="button" class="btn btn-success btn-sm dm-complete-return dm-status-action" data-invoice="${invoiceName}">✅ إكمال المرتجع بعد اعتماد Credit Note</button>
                `;
            }
        }

        const paymentActions = this.prepaid_action_block(order, status);
        const collectionActions = this.collection_action_block(order, status);
        const paymentProof = order.custom_prepaid_payment_proof
            ? `<a class="btn btn-default btn-sm" href="${this.escape(order.custom_prepaid_payment_proof)}" target="_blank" rel="noopener noreferrer">عرض صورة التحويل</a>`
            : "";
        const paymentEntryButton = order.custom_prepaid_payment_entry
            ? `<button type="button" class="btn btn-default btn-sm dm-open-payment-entry" data-payment-entry="${this.escape(order.custom_prepaid_payment_entry)}">فتح Payment Entry</button>`
            : "";

        return `
            <div class="dm-order-card ${selected ? "selected" : ""} ${expanded ? "expanded" : ""}" data-order-card="${invoiceName}">
                <div class="dm-order-top">
                    <div class="dm-order-compact">
                        ${checkbox}
                        <button type="button" class="dm-toggle-order" data-invoice="${invoiceName}" aria-label="فتح تفاصيل الفاتورة">▶</button>
                        <div class="dm-invoice-name" data-invoice="${invoiceName}">${invoiceName}</div>
                    </div>
                    <div class="dm-order-time">${this.escape(order.creation ? moment(order.creation).format("hh:mm A") : "")}</div>
                </div>
                <div class="dm-order-compact-meta">
                    <span class="dm-compact-pill">${this.escape(order.customer_name || order.customer || "بدون اسم")}</span>
                    <span class="dm-compact-pill">${this.escape(this.format_money(displayOutstanding))}</span>
                    <span class="dm-compact-pill">${this.escape(displayStatusLabel)}</span>
                    ${this.prepaid_badge(order)}
                </div>

                <div class="dm-order-details">
                    <div class="dm-customer">${this.escape(order.customer_name || order.customer || "بدون اسم")}</div>
                    ${this.info_row("الموبايل", order.contact_mobile || "—")}
                    ${this.info_row("العنوان", order.shipping_address_name || order.customer_address || "—")}
                    ${this.info_row("قيمة الفاتورة", this.format_money(order.group_grand_total ?? order.grand_total))}
                    ${this.info_row("المطلوب", this.format_money(displayOutstanding))}
                    ${this.info_row("الطيار", order.delivery_boy_name || "لم يتم التعيين")}
                    ${this.info_row("الحالة", displayStatusLabel)}
                    ${driverReturnStatus !== "Not Required" ? this.info_row("حالة رجوع الطيار", this.get_driver_return_status_label(driverReturnStatus)) : ""}
                    ${deliveryReturnType !== "Not Required" ? this.info_row("نوع المرتجع", deliveryReturnType) : ""}
                    ${partialReturnRequest ? this.info_row("طلب المرتجع", partialReturnRequest.name || "") : ""}
                    ${deliveryReturnStatus !== "Not Required" ? this.info_row("حالة المرتجع", this.get_delivery_return_status_label(deliveryReturnStatus)) : ""}
                    ${deliveryReturnReason ? this.info_row("سبب الرجوع", deliveryReturnReason) : ""}
                    ${returnCreditNote ? this.info_row("مرتجع المبيعات", returnCreditNote) : ""}
                    ${order.sales_shift || order.custom_pharmacy_shift ? this.info_row("وردية البيع", order.sales_shift || order.custom_pharmacy_shift) : ""}
                    ${order.current_delivery_shift || order.custom_delivery_shift ? this.info_row("وردية التوصيل", order.current_delivery_shift || order.custom_delivery_shift) : ""}
                    ${addOnStatus ? this.info_row("حالة الإضافة", this.get_add_on_status_label(addOnStatus)) : ""}
                    ${order.custom_delivery_attempt_count ? this.info_row("محاولات التوصيل", order.custom_delivery_attempt_count) : ""}
                    ${order.add_on_count ? this.info_row("فواتير الإضافة", `${order.add_on_count} (${(order.add_on_invoices || []).join(", ")})`) : ""}
                    ${tripName ? this.info_row("رحلة التوصيل", tripName) : ""}
                    ${hasPrepaidPayment && order.custom_prepaid_amount ? this.info_row("الدفع المسبق", this.format_money(order.custom_prepaid_amount)) : ""}
                    ${hasPrepaidPayment && order.custom_prepaid_method ? this.info_row("طريقة الدفع المسبق", order.custom_prepaid_method) : ""}
                    ${hasPrepaidPayment && order.custom_prepaid_transaction_reference ? this.info_row("مرجع العملية", order.custom_prepaid_transaction_reference) : ""}
                    ${hasPrepaidPayment ? this.info_row("حالة الدفع المسبق", this.get_prepaid_status_label(prepaidStatus)) : ""}
                    ${reportedMethod ? this.info_row("طريقة دفع العميل", reportedMethod) : ""}
                    ${reportedAmount ? this.info_row("المبلغ المعلن من الطيار", this.format_money(reportedAmount)) : ""}
                    ${collectionProof ? this.info_row("إثبات التحصيل", "تم إرفاق صورة") : ""}
                    ${this.info_row("حالة التحصيل", this.get_collection_status_label(collectionStatus))}
                    ${order.custom_delivery_card_pos_terminal ? this.info_row("ماكينة الفيزا", order.custom_delivery_card_pos_terminal) : ""}
                    ${order.custom_collection_difference ? this.info_row("فرق التحصيل", this.format_money(order.custom_collection_difference)) : ""}

                    <div class="dm-card-actions">
                        ${unresolvedReturnBalance ? `<div class="dm-workflow-note">⚠️ المرتجع لم يُسوَّ بالكامل. المتبقي على الفاتورة ${this.escape(this.format_money(displayOutstanding))}. أنشئ Credit Note لباقي البنود قبل إغلاق الأوردر.</div>` : ""}
                        ${workflowNote}
                        ${tripNote}
                        ${statusButton}
                        ${redeliveryButton}
                        ${cancelAddOnButton}
                        ${managerPartialReturnButton}
                        ${returnAction}
                        ${paymentActions}
                        ${collectionActions}
                        ${collectionProof ? `<a class="btn btn-default btn-sm" href="${this.escape(collectionProof)}" target="_blank" rel="noopener noreferrer">📷 عرض إثبات التحصيل</a>` : ""}
                        ${paymentProof}
                        ${paymentEntryButton}
                        ${transferButton}
                        ${assignButton}
                        ${addOnButton}
                        <button type="button" class="btn btn-default btn-sm dm-open-invoice" data-invoice="${invoiceName}">فتح الفاتورة</button>
                    </div>
                </div>
            </div>
        `;
    }

    prepaid_badge(order) {
        const timing = order.custom_delivery_payment_timing || "Collect on Delivery";
        if (!["Prepaid", "Partially Prepaid"].includes(timing)) return "";
        const status = order.custom_prepaid_verification_status || "Not Declared";
        const amount = Number(order.custom_prepaid_amount || 0);
        if (status === "Confirmed") {
            return `<span class="dm-payment-badge confirmed">مدفوع مسبقًا ${this.escape(this.format_money(amount))}</span>`;
        }
        if (status === "Awaiting Confirmation") {
            return `<span class="dm-payment-badge pending">بانتظار تأكيد ${this.escape(this.format_money(amount))}</span>`;
        }
        if (status === "Rejected") {
            return `<span class="dm-payment-badge rejected">الدفع مرفوض</span>`;
        }
        return `<span class="dm-payment-badge">غير مدفوع مسبقًا</span>`;
    }

    prepaid_action_block(order, deliveryStatus) {
        if (["Out for Delivery", "Delivered"].includes(deliveryStatus)) return "";
        const status = order.custom_prepaid_verification_status || "Not Declared";
        const invoiceName = this.escape(order.name);
        if (status === "Awaiting Confirmation") {
            return `
                <div class="dm-payment-actions">
                    <button type="button" class="btn btn-success btn-sm dm-confirm-prepaid" data-invoice="${invoiceName}">✅ تأكيد الدفع</button>
                    <button type="button" class="btn btn-danger btn-sm dm-reject-prepaid" data-invoice="${invoiceName}">❌ رفض الدفع</button>
                </div>
            `;
        }
        if (status === "Confirmed") return "";
        const label = status === "Rejected" ? "💳 إعادة تسجيل الدفع" : "💳 تسجيل دفع مسبق";
        return `<button type="button" class="btn btn-default btn-sm dm-register-prepaid" data-invoice="${invoiceName}">${label}</button>`;
    }

    collection_action_block(order, deliveryStatus) {
        if (deliveryStatus !== "Delivered") return "";
        const status = order.custom_collection_verification_status || "Not Required";
        const invoiceName = this.escape(order.name);
        if (status === "Awaiting Confirmation") {
            return `
                <div class="dm-payment-actions">
                    <button type="button" class="btn btn-success btn-sm dm-confirm-collection" data-invoice="${invoiceName}">✅ تأكيد التحصيل</button>
                    <button type="button" class="btn btn-danger btn-sm dm-reject-collection" data-invoice="${invoiceName}">❌ اعتراض</button>
                </div>
            `;
        }
        if (status === "Confirmed") {
            const paymentEntry = order.custom_collection_payment_entry || "";
            return paymentEntry
                ? `<button type="button" class="btn btn-default btn-sm dm-open-payment-entry" data-payment-entry="${this.escape(paymentEntry)}">فتح Payment Entry التحصيل</button>`
                : `<div class="dm-workflow-note">✅ التحصيل مؤكد.</div>`;
        }
        if (status === "Disputed") {
            return `<div class="dm-workflow-note">⚠️ يوجد اعتراض على التحصيل. اطلب من الطيار إعادة تسجيله.</div>`;
        }
        return "";
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

    get_prepaid_status_label(status) {
        return ({
            "Not Declared": "غير مسجل",
            "Awaiting Confirmation": "في انتظار التأكيد",
            "Confirmed": "مؤكد",
            "Rejected": "مرفوض"
        })[status] || status || "غير مسجل";
    }

    info_row(label, value) {
        return `
            <div class="dm-info-row">
                <span class="dm-info-label">${this.escape(label)}</span>
                <span class="dm-info-value">${this.escape(value === 0 || value ? value : "—")}</span>
            </div>
        `;
    }

    escape(value) {
        return frappe.utils.escape_html(String(value ?? ""));
    }
}
