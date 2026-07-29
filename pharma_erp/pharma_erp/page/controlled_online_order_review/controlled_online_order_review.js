frappe.pages["controlled-online-order-review"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Controlled Online Order Review"),
        single_column: true,
    });

    const reviewPage = new ControlledOnlineOrderReviewPage(wrapper, page);
    page.set_primary_action(__("Refresh"), () => reviewPage.load_orders(), "refresh");
};


class ControlledOnlineOrderReviewPage {
    constructor(wrapper, page) {
        this.wrapper = wrapper;
        this.page = page;
        this.$main = $(wrapper).find(".layout-main-section");
        this.orders = [];
        this.setup_page();
        this.setup_events();
        this.load_orders();
    }

    setup_page() {
        this.statusField = this.page.add_field({
            label: __("Status"),
            fieldtype: "Select",
            fieldname: "status",
            options: [
                "",
                "Placed",
                "Under Review",
                "Prescription Review",
                "Stock Review",
                "Partially Available",
                "Awaiting Customer Decision",
                "Ready for Payment",
                "On Hold",
            ].join("\n"),
            change: () => this.load_orders(),
        });

        this.searchField = this.page.add_field({
            label: __("Search"),
            fieldtype: "Data",
            fieldname: "search",
            placeholder: __("Order, customer, mobile or website reference"),
            change: () => this.load_orders(),
        });

        this.$main.html(`
            <div class="coor-page" dir="rtl">
                <div class="coor-banner">
                    <div>
                        <div class="coor-banner-title">مراجعة طلبات الموقع قبل التأكيد</div>
                        <div class="coor-banner-subtitle">
                            مراجعة الوصفة والمخزون وربط العميل والعنوان ومنطقة التوصيل قبل التأكيد النهائي، بدون إنشاء مستندات مالية أو مخزنية.
                        </div>
                    </div>
                    <span class="indicator-pill blue">Step 3B.5</span>
                </div>
                <div class="coor-summary"></div>
                <div class="coor-loading text-muted">جاري تحميل طلبات الموقع...</div>
                <div class="coor-orders"></div>
            </div>
        `);
        this.add_styles();
    }

    add_styles() {
        if (document.getElementById("coor-page-styles")) return;
        $("<style id='coor-page-styles'>").text(`
            .coor-page { padding: 4px 0 28px; }
            .coor-banner {
                display:flex; align-items:center; justify-content:space-between; gap:16px;
                padding:18px 20px; border:1px solid var(--border-color); border-radius:12px;
                background:var(--fg-color); margin-bottom:16px;
            }
            .coor-banner-title { font-size:18px; font-weight:700; margin-bottom:4px; }
            .coor-banner-subtitle { color:var(--text-muted); line-height:1.7; }
            .coor-summary { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin-bottom:16px; }
            .coor-card { border:1px solid var(--border-color); border-radius:10px; background:var(--fg-color); padding:14px; }
            .coor-card-label { color:var(--text-muted); font-size:12px; }
            .coor-card-value { font-size:24px; font-weight:700; margin-top:4px; }
            .coor-table-wrap { overflow:auto; border:1px solid var(--border-color); border-radius:12px; background:var(--fg-color); }
            .coor-table { width:100%; min-width:1080px; border-collapse:collapse; }
            .coor-table th, .coor-table td { padding:11px 10px; border-bottom:1px solid var(--border-color); vertical-align:middle; text-align:right; }
            .coor-table th { background:var(--subtle-fg); font-weight:600; white-space:nowrap; }
            .coor-order-link { font-weight:700; }
            .coor-actions { display:flex; gap:6px; flex-wrap:wrap; }
            .coor-empty { padding:40px 20px; text-align:center; color:var(--text-muted); }
            .coor-rx { font-weight:700; }
            .coor-dialog-summary { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin-bottom:12px; }
            .coor-dialog-summary > div { padding:8px 10px; border-radius:8px; background:var(--subtle-fg); }
            .coor-blockers { margin:8px 0 0; padding-right:18px; }
            @media (max-width: 768px) {
                .coor-banner { align-items:flex-start; flex-direction:column; }
                .coor-dialog-summary { grid-template-columns:1fr; }
            }
        `).appendTo("head");
    }

    setup_events() {
        this.$main.on("click", ".coor-open-order", (event) => {
            frappe.set_route("Form", "Online Order", $(event.currentTarget).data("order"));
        });
        this.$main.on("click", ".coor-start-review", async (event) => {
            await this.start_review($(event.currentTarget).data("order"));
        });
        this.$main.on("click", ".coor-prescription-review", async (event) => {
            await this.open_prescription_dialog($(event.currentTarget).data("order"));
        });
        this.$main.on("click", ".coor-stock-review", async (event) => {
            await this.open_stock_dialog($(event.currentTarget).data("order"));
        });
        this.$main.on("click", ".coor-view-snapshot", async (event) => {
            await this.show_snapshot($(event.currentTarget).data("order"));
        });
        this.$main.on("click", ".coor-customer-resolution", async (event) => {
            await this.open_customer_resolution_dialog($(event.currentTarget).data("order"));
        });
        this.$main.on("click", ".coor-delivery-zone", async (event) => {
            await this.open_delivery_zone_dialog($(event.currentTarget).data("order"));
        });
        this.$main.on("click", ".coor-final-readiness", async (event) => {
            await this.verify_final_readiness($(event.currentTarget).data("order"));
        });
    }

    async call(method, args = {}) {
        const response = await frappe.call({ method, args, freeze: true });
        return response.message || {};
    }

    async load_orders() {
        this.$main.find(".coor-loading").show();
        this.$main.find(".coor-orders").empty();
        try {
            const result = await this.call(
                "pharma_erp.controlled_online_order_review.get_review_queue",
                {
                    status: this.statusField.get_value() || "",
                    search: this.searchField.get_value() || "",
                    page_length: 100,
                }
            );
            this.orders = result.orders || [];
            this.render_summary(result);
            this.render_orders();
        } finally {
            this.$main.find(".coor-loading").hide();
        }
    }

    render_summary(result) {
        const counts = result.counts || {};
        const cards = [
            ["إجمالي قائمة المراجعة", result.total || 0],
            ["طلبات جديدة", counts["Placed"] || 0],
            ["مراجعة وصفة", counts["Prescription Review"] || 0],
            ["مراجعة مخزون", counts["Stock Review"] || 0],
            ["قرار العميل", counts["Awaiting Customer Decision"] || 0],
            ["جاهز للمرحلة التالية", counts["Ready for Payment"] || 0],
        ];
        this.$main.find(".coor-summary").html(cards.map(([label, value]) => `
            <div class="coor-card">
                <div class="coor-card-label">${this.escape(label)}</div>
                <div class="coor-card-value">${this.escape(value)}</div>
            </div>
        `).join(""));
    }

    render_orders() {
        const $container = this.$main.find(".coor-orders");
        if (!this.orders.length) {
            $container.html(`<div class="coor-empty">لا توجد طلبات مطابقة لفلتر المراجعة الحالي.</div>`);
            return;
        }

        const rows = this.orders.map((order) => {
            const startButton = order.status === "Placed"
                ? `<button class="btn btn-default btn-xs coor-start-review" data-order="${this.escape(order.name)}">بدء المراجعة</button>`
                : "";
            const prescriptionButton = Number(order.prescription_required || 0)
                ? `<button class="btn btn-default btn-xs coor-prescription-review" data-order="${this.escape(order.name)}">مراجعة الوصفة</button>`
                : "";
            return `
                <tr>
                    <td><a href="#" class="coor-order-link coor-open-order" data-order="${this.escape(order.name)}">${this.escape(order.name)}</a></td>
                    <td>${this.status_badge(order.status)}</td>
                    <td>${this.escape(order.customer_name || "-")}<br><small>${this.escape(order.customer || order.customer_resolution_status || "Unresolved")}</small></td>
                    <td dir="ltr">${this.escape(order.mobile_no || "-")}</td>
                    <td>${this.escape(order.fulfilment_method || "-")}</td>
                    <td>${this.escape(this.money(order.grand_total, order.currency))}</td>
                    <td class="coor-rx">${Number(order.prescription_required || 0) ? "نعم" : "لا"}</td>
                    <td>${this.escape(order.prescription_review_status || "-")}</td>
                    <td>${this.escape(frappe.datetime.str_to_user(order.creation))}</td>
                    <td>
                        <div class="coor-actions">
                            ${startButton}
                            ${prescriptionButton}
                            <button class="btn btn-primary btn-xs coor-stock-review" data-order="${this.escape(order.name)}">مراجعة المخزون</button>
                            <button class="btn btn-default btn-xs coor-customer-resolution" data-order="${this.escape(order.name)}">ربط العميل</button>
                            <button class="btn btn-default btn-xs coor-delivery-zone" data-order="${this.escape(order.name)}">منطقة التوصيل</button>
                            <button class="btn btn-default btn-xs coor-view-snapshot" data-order="${this.escape(order.name)}">الجاهزية</button>
                            <button class="btn btn-success btn-xs coor-final-readiness" data-order="${this.escape(order.name)}">تأكيد الجاهزية</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");

        $container.html(`
            <div class="coor-table-wrap">
                <table class="coor-table">
                    <thead><tr>
                        <th>الطلب</th><th>الحالة</th><th>العميل</th><th>الموبايل</th>
                        <th>الاستلام</th><th>الإجمالي</th><th>وصفة</th><th>قرار الوصفة</th>
                        <th>وقت الطلب</th><th>الإجراءات</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `);
    }

    async start_review(orderName) {
        await this.call("pharma_erp.controlled_online_order_review.start_review", {
            online_order: orderName,
        });
        frappe.show_alert({ message: __("Controlled review started."), indicator: "green" });
        await this.load_orders();
    }

    async get_snapshot(orderName) {
        return this.call("pharma_erp.controlled_online_order_review.get_review_snapshot", {
            online_order: orderName,
        });
    }

    async show_snapshot(orderName) {
        const snapshot = await this.get_snapshot(orderName);
        const reviewBlockers = snapshot.review_blockers || [];
        const confirmationBlockers = snapshot.confirmation_blockers || [];
        const dialog = new frappe.ui.Dialog({
            title: `جاهزية ${snapshot.name}`,
            size: "large",
            fields: [{
                fieldname: "summary_html",
                fieldtype: "HTML",
            }],
        });
        dialog.fields_dict.summary_html.$wrapper.html(`
            <div dir="rtl">
                <div class="coor-dialog-summary">
                    <div><b>الحالة:</b> ${this.escape(snapshot.status)}</div>
                    <div><b>الإجمالي:</b> ${this.escape(this.money(snapshot.grand_total, snapshot.currency))}</div>
                    <div><b>الوصفة:</b> ${Number(snapshot.prescription_required) ? "مطلوبة" : "غير مطلوبة"}</div>
                    <div><b>قرار الوصفة:</b> ${this.escape(snapshot.prescription_review_status || "-")}</div>
                    <div><b>كود العميل:</b> ${this.escape(snapshot.customer || "غير مربوط")}</div>
                    <div><b>حالة الربط:</b> ${this.escape(snapshot.customer_resolution_status || "Unresolved")}</div>
                    <div><b>منطقة التوصيل:</b> ${this.escape(snapshot.delivery_zone || "غير محددة")}</div>
                    <div><b>رسوم التوصيل:</b> ${this.escape(this.money(snapshot.delivery_fee, snapshot.currency))}</div>
                    <div><b>الجاهزية النهائية:</b> ${this.escape(snapshot.final_confirmation_readiness_status || "Pending")}</div>
                </div>
                <h5>عوائق إكمال المراجعة</h5>
                ${this.blocker_list(reviewBlockers, "لا توجد عوائق مراجعة حالية.")}
                <h5>عوائق التأكيد اللاحقة</h5>
                ${this.blocker_list(confirmationBlockers, "الطلب جاهز للتأكيد بعد المراجعة.")}
            </div>
        `);
        dialog.show();
    }

    async open_prescription_dialog(orderName) {
        const snapshot = await this.get_snapshot(orderName);
        if (!Number(snapshot.prescription_required || 0)) {
            frappe.msgprint(__("This order does not require a prescription."));
            return;
        }

        const rows = (snapshot.items || [])
            .filter((row) => Number(row.requires_prescription || 0))
            .map((row) => ({
                child_name: row.name,
                item_code: row.item_code,
                item_name: row.item_name,
                decision: row.prescription_item_status === "Approved" ? "Approved" : "",
                alternative_item: row.alternative_item || "",
                notes: row.prescription_item_notes || "",
            }));

        const dialog = new frappe.ui.Dialog({
            title: `مراجعة وصفة ${snapshot.name}`,
            size: "extra-large",
            fields: [
                {
                    fieldname: "attachment_info",
                    fieldtype: "HTML",
                    options: snapshot.prescription_attachment
                        ? `<div class="alert alert-success">تم إرفاق الوصفة: <a href="${this.escape(snapshot.prescription_attachment)}" target="_blank">فتح الملف</a></div>`
                        : `<div class="alert alert-warning">لا يوجد مرفق وصفة. لا يمكن اعتماد Approved أو Partially Approved.</div>`,
                },
                {
                    fieldname: "decision",
                    label: __("Header Decision"),
                    fieldtype: "Select",
                    options: "Approved\nPartially Approved\nRejected\nReplacement Requested",
                    reqd: 1,
                    default: snapshot.prescription_review_status === "Approved" ? "Approved" : "",
                },
                {
                    fieldname: "item_decisions",
                    label: __("Prescription Items"),
                    fieldtype: "Table",
                    cannot_add_rows: true,
                    cannot_delete_rows: true,
                    data: rows,
                    fields: [
                        { fieldname: "child_name", fieldtype: "Data", hidden: 1 },
                        { fieldname: "item_code", label: __("Item Code"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2 },
                        { fieldname: "item_name", label: __("Item Name"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2 },
                        { fieldname: "decision", label: __("Decision"), fieldtype: "Select", options: "Approved\nRejected\nAlternative Suggested", reqd: 1, in_list_view: 1, columns: 2 },
                        { fieldname: "alternative_item", label: __("Alternative Item"), fieldtype: "Link", options: "Item", in_list_view: 1, columns: 2 },
                        { fieldname: "notes", label: __("Notes"), fieldtype: "Small Text", in_list_view: 1, columns: 2 },
                    ],
                },
                {
                    fieldname: "notes",
                    label: __("Review Notes"),
                    fieldtype: "Small Text",
                    default: snapshot.prescription_review_notes || "",
                },
            ],
            primary_action_label: __("Apply Prescription Review"),
            primary_action: async (values) => {
                await this.call("pharma_erp.controlled_online_order_review.apply_prescription_review", {
                    online_order: snapshot.name,
                    decision: values.decision,
                    notes: values.notes || "",
                    item_decisions: JSON.stringify(values.item_decisions || []),
                });
                dialog.hide();
                frappe.show_alert({ message: __("Prescription review saved."), indicator: "green" });
                await this.load_orders();
            },
        });
        dialog.show();
    }

    async open_stock_dialog(orderName) {
        const snapshot = await this.get_snapshot(orderName);
        const rows = (snapshot.items || []).map((row) => ({
            child_name: row.name,
            item_code: row.item_code,
            item_name: row.item_name,
            requested_qty: row.requested_qty,
            actual_qty: row.actual_qty,
            approved_qty: row.approved_qty,
            warehouse: row.warehouse || snapshot.warehouse || "",
            availability_status: row.display_availability_status === "Pending Review"
                ? "Available"
                : row.display_availability_status,
            alternative_item: row.alternative_item || "",
        }));

        const dialog = new frappe.ui.Dialog({
            title: `مراجعة مخزون ${snapshot.name}`,
            size: "extra-large",
            fields: [
                {
                    fieldname: "stock_help",
                    fieldtype: "HTML",
                    options: `<div class="alert alert-info">القيمة Actual Qty المعروضة حسب المخزن الحالي عند فتح النافذة. السيرفر يعيد التحقق من المخزون عند الحفظ.</div>`,
                },
                {
                    fieldname: "rows",
                    label: __("Order Items"),
                    fieldtype: "Table",
                    cannot_add_rows: true,
                    cannot_delete_rows: true,
                    data: rows,
                    fields: [
                        { fieldname: "child_name", fieldtype: "Data", hidden: 1 },
                        { fieldname: "item_code", label: __("Item"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 1 },
                        { fieldname: "item_name", label: __("Item Name"), fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2 },
                        { fieldname: "requested_qty", label: __("Requested"), fieldtype: "Float", read_only: 1, in_list_view: 1, columns: 1 },
                        { fieldname: "actual_qty", label: __("Actual Qty"), fieldtype: "Float", read_only: 1, in_list_view: 1, columns: 1 },
                        { fieldname: "approved_qty", label: __("Approved"), fieldtype: "Float", reqd: 1, in_list_view: 1, columns: 1 },
                        { fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", in_list_view: 1, columns: 2 },
                        { fieldname: "availability_status", label: __("Decision"), fieldtype: "Select", options: "Available\nPartially Available\nUnavailable\nRemoved\nAlternative Suggested", reqd: 1, in_list_view: 1, columns: 2 },
                        { fieldname: "alternative_item", label: __("Alternative"), fieldtype: "Link", options: "Item", in_list_view: 1, columns: 2 },
                    ],
                },
                {
                    fieldname: "notes",
                    label: __("Stock Review Notes"),
                    fieldtype: "Small Text",
                },
            ],
            primary_action_label: __("Apply Stock Review"),
            primary_action: async (values) => {
                await this.call("pharma_erp.controlled_online_order_review.apply_stock_review", {
                    online_order: snapshot.name,
                    rows: JSON.stringify(values.rows || []),
                    notes: values.notes || "",
                });
                dialog.hide();
                frappe.show_alert({ message: __("Stock review saved."), indicator: "green" });
                await this.load_orders();
            },
        });
        dialog.show();
    }


    async open_customer_resolution_dialog(orderName) {
        const context = await this.call(
            "pharma_erp.controlled_online_order_review.get_customer_resolution_context",
            { online_order: orderName }
        );
        const candidates = context.candidates || [];
        const candidateHtml = candidates.length
            ? `<div class="alert alert-info"><b>مطابقات مقترحة:</b><ul>${candidates.map((row) =>
                `<li>${this.escape(row.customer_code)} — ${this.escape(row.customer_name)} (${this.escape((row.match_methods || []).join(", "))})</li>`
            ).join("")}</ul></div>`
            : `<div class="alert alert-warning">لا توجد مطابقة فريدة تلقائية. يمكن اختيار العميل يدويًا بعد التحقق.</div>`;

        const dialog = new frappe.ui.Dialog({
            title: `ربط العميل ${context.online_order}`,
            size: "large",
            fields: [
                { fieldname: "candidate_info", fieldtype: "HTML", options: candidateHtml },
                {
                    fieldname: "customer",
                    label: __("Customer"),
                    fieldtype: "Link",
                    options: "Customer",
                    reqd: 1,
                    default: context.customer || (candidates.length === 1 ? candidates[0].name : ""),
                },
                {
                    fieldname: "resolution_method",
                    label: __("Resolution Method"),
                    fieldtype: "Select",
                    options: "Website User\nMobile\nEmail\nManual Confirmation",
                    reqd: 1,
                    default: context.customer_resolution_method || (
                        candidates.length === 1 && Number(candidates[0].website_user_match || 0)
                            ? "Website User"
                            : "Manual Confirmation"
                    ),
                },
                {
                    fieldname: "address_name",
                    label: __("Saved Address"),
                    fieldtype: "Select",
                    options: "",
                },
                {
                    fieldname: "notes",
                    label: __("Resolution Notes"),
                    fieldtype: "Small Text",
                },
            ],
            primary_action_label: __("Apply Customer Resolution"),
            primary_action: async (values) => {
                await this.call(
                    "pharma_erp.controlled_online_order_review.apply_customer_resolution",
                    {
                        online_order: context.online_order,
                        customer: values.customer,
                        resolution_method: values.resolution_method,
                        address_name: values.address_name || "",
                        notes: values.notes || "",
                    }
                );
                dialog.hide();
                frappe.show_alert({ message: __("Customer resolution saved."), indicator: "green" });
                await this.load_orders();
            },
        });

        const setAddresses = async (customer) => {
            const field = dialog.fields_dict.address_name;
            if (!customer) {
                field.df.options = "";
                field.refresh();
                return;
            }
            const profile = await this.call(
                "pharma_erp.controlled_online_order_review.get_customer_profile",
                { customer }
            );
            const addresses = profile.addresses || [];
            field.df.options = ["", ...addresses.map((row) => row.name)];
            field.refresh();
            if (context.customer === customer && context.customer_address) {
                field.set_value(context.customer_address);
            }
        };
        dialog.fields_dict.customer.df.onchange = async () => {
            await setAddresses(dialog.get_value("customer"));
        };
        dialog.show();
        await setAddresses(dialog.get_value("customer"));
    }

    async open_delivery_zone_dialog(orderName) {
        const context = await this.call(
            "pharma_erp.controlled_online_order_review.get_delivery_zone_context",
            { online_order: orderName }
        );
        if (context.fulfilment_method !== "Home Delivery") {
            frappe.msgprint(__("Delivery Zone is only used for Home Delivery orders."));
            return;
        }
        const zones = context.zones || [];
        if (!zones.length) {
            frappe.msgprint(__("No active Delivery Zone matches the reviewed Warehouse."));
            return;
        }
        const zoneMap = Object.fromEntries(zones.map((zone) => [zone.name, zone]));
        const dialog = new frappe.ui.Dialog({
            title: `منطقة توصيل ${context.online_order}`,
            size: "large",
            fields: [
                {
                    fieldname: "current_info",
                    fieldtype: "HTML",
                    options: `<div class="alert alert-info">المخزن المعتمد: <b>${this.escape(context.warehouse || "-")}</b> — إجمالي المنتجات: <b>${this.money(context.products_subtotal, "EGP")}</b></div>`,
                },
                {
                    fieldname: "delivery_zone",
                    label: __("Delivery Zone"),
                    fieldtype: "Select",
                    options: zones.map((zone) => zone.name),
                    reqd: 1,
                    default: context.delivery_zone || zones[0].name,
                },
                { fieldname: "zone_info", fieldtype: "HTML" },
                { fieldname: "notes", label: __("Notes"), fieldtype: "Small Text" },
            ],
            primary_action_label: __("Apply Delivery Zone"),
            primary_action: async (values) => {
                await this.call(
                    "pharma_erp.controlled_online_order_review.apply_delivery_zone",
                    {
                        online_order: context.online_order,
                        delivery_zone: values.delivery_zone,
                        notes: values.notes || "",
                    }
                );
                dialog.hide();
                frappe.show_alert({ message: __("Delivery Zone saved."), indicator: "green" });
                await this.load_orders();
            },
        });
        const showZone = () => {
            const zone = zoneMap[dialog.get_value("delivery_zone")] || {};
            dialog.fields_dict.zone_info.$wrapper.html(`
                <div class="coor-dialog-summary">
                    <div><b>المخزن:</b> ${this.escape(zone.warehouse || "-")}</div>
                    <div><b>الرسوم الأساسية:</b> ${this.money(zone.delivery_fee, "EGP")}</div>
                    <div><b>الحد الأدنى:</b> ${this.money(zone.minimum_order_amount, "EGP")}</div>
                    <div><b>التوصيل المجاني فوق:</b> ${this.money(zone.free_delivery_above, "EGP")}</div>
                    <div><b>الوقت المتوقع:</b> ${this.escape(zone.estimated_time_mins || 0)} دقيقة</div>
                </div>
            `);
        };
        dialog.fields_dict.delivery_zone.df.onchange = showZone;
        dialog.show();
        showZone();
    }

    async verify_final_readiness(orderName) {
        const snapshot = await this.get_snapshot(orderName);
        const blockers = [
            ...(snapshot.review_blockers || []),
            ...(snapshot.confirmation_blockers || []),
        ];
        if (blockers.length) {
            frappe.msgprint({
                title: __("Final Confirmation Readiness Blocked"),
                indicator: "orange",
                message: this.blocker_list(blockers, ""),
            });
            return;
        }
        const dialog = new frappe.ui.Dialog({
            title: `تأكيد الجاهزية النهائية ${snapshot.name}`,
            fields: [
                {
                    fieldname: "summary",
                    fieldtype: "HTML",
                    options: `<div class="alert alert-success">العميل والعنوان ومنطقة التوصيل والمخزون جاهزة. لن يتم إنشاء فاتورة أو قيد أو حركة مخزون.</div>`,
                },
                { fieldname: "notes", label: __("Readiness Notes"), fieldtype: "Small Text" },
            ],
            primary_action_label: __("Verify Final Readiness"),
            primary_action: async (values) => {
                await this.call(
                    "pharma_erp.controlled_online_order_review.verify_final_confirmation_readiness",
                    { online_order: snapshot.name, notes: values.notes || "" }
                );
                dialog.hide();
                frappe.show_alert({ message: __("Final readiness verified."), indicator: "green" });
                await this.load_orders();
            },
        });
        dialog.show();
    }

    blocker_list(items, emptyLabel) {
        if (!items || !items.length) {
            return `<div class="text-success">${this.escape(emptyLabel)}</div>`;
        }
        return `<ul class="coor-blockers">${items.map((item) => `<li>${this.escape(item)}</li>`).join("")}</ul>`;
    }

    status_badge(status) {
        const colour = {
            "Placed": "blue",
            "Under Review": "orange",
            "Prescription Review": "purple",
            "Stock Review": "yellow",
            "Partially Available": "orange",
            "Awaiting Customer Decision": "purple",
            "Ready for Payment": "green",
            "On Hold": "red",
        }[status] || "gray";
        return `<span class="indicator-pill ${colour}">${this.escape(status || "-")}</span>`;
    }

    money(value, currency) {
        return `${Number(value || 0).toFixed(2)} ${currency || "EGP"}`;
    }

    escape(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }
}
