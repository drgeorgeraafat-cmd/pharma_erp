frappe.pages["customer-reservation-operations"].on_page_load = function (wrapper) {
    new CustomerReservationOperations(wrapper);
};

class CustomerReservationOperations {
    constructor(wrapper) {
        this.wrapper = wrapper;
        this.page = frappe.ui.make_app_page({
            parent: wrapper,
            title: __("Customer Reservation Operations"),
            single_column: true
        });
        this.rows = [];
        this.build();
        this.refresh();
    }

    build() {
        this.page.set_primary_action(__("New Reservation"), () => this.newReservation(), "add");
        this.page.add_inner_button(__("Refresh"), () => this.refresh());
        this.statusField = this.page.add_field({
            fieldname: "reservation_status",
            label: __("Status"),
            fieldtype: "Select",
            options: "\nActive\nReview Required\nPartially Fulfilled\nPicked Up\nSent for Delivery\nFulfilled\nReleased\nCancelled",
            change: () => this.refresh()
        });
        this.branchField = this.page.add_field({
            fieldname: "branch",
            label: __("Branch"),
            fieldtype: "Link",
            options: "Branch",
            change: () => this.refresh()
        });
        this.customerField = this.page.add_field({
            fieldname: "customer",
            label: __("Customer"),
            fieldtype: "Link",
            options: "Customer",
            change: () => this.refresh()
        });
        this.body = $("<div class='customer-reservation-operations'></div>").appendTo(this.page.main);
        this.body.append(`<style>
            .customer-reservation-summary{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:12px;margin:14px 0}
            .customer-reservation-kpi{background:var(--card-bg);border:1px solid var(--border-color);border-radius:10px;padding:12px}
            .customer-reservation-kpi strong{display:block;font-size:22px;margin-top:4px}
            .customer-reservation-card{background:var(--card-bg);border:1px solid var(--border-color);border-radius:10px;padding:14px;margin-bottom:12px}
            .customer-reservation-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
            .customer-reservation-meta,.customer-reservation-items{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:10px;color:var(--text-muted)}
            .customer-reservation-items{color:var(--text-color)}
            .customer-reservation-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
            .reservation-badge{display:inline-block;border-radius:999px;padding:4px 9px;font-weight:600;background:var(--subtle-fg)}
            .reservation-badge.review-required{background:var(--yellow-100);color:var(--yellow-800)}
            .reservation-badge.active{background:var(--green-100);color:var(--green-800)}
            .reservation-badge.released,.reservation-badge.cancelled{background:var(--gray-200);color:var(--gray-700)}
            @media(max-width:900px){.customer-reservation-summary{grid-template-columns:repeat(2,1fr)}}
        </style>`);
        this.content = $("<div></div>").appendTo(this.body);
    }

    call(method, args = {}) {
        return frappe.call({
            method: `pharma_erp.pharma_erp.customer_reservation_service.${method}`,
            args,
            freeze: false
        }).then(result => result.message);
    }

    async refresh() {
        this.content.html(`<div class="text-muted">${__("Loading reservations...")}</div>`);
        try {
            this.rows = await this.call("list_customer_reservations", {
                status: this.statusField.get_value() || "",
                branch: this.branchField.get_value() || "",
                customer: this.customerField.get_value() || "",
                limit: 300
            }) || [];
            this.render();
        } catch (error) {
            console.error(error);
            this.content.html(`<div class="alert alert-danger">${__("Unable to load Customer Reservations.")}</div>`);
        }
    }

    render() {
        const counts = this.rows.reduce((result, row) => {
            result[row.operational_status] = (result[row.operational_status] || 0) + 1;
            return result;
        }, {});
        const summary = `
            <div class="customer-reservation-summary">
                <div class="customer-reservation-kpi"><span>${__("Active")}</span><strong>${counts.Active || 0}</strong></div>
                <div class="customer-reservation-kpi"><span>${__("Review Required")}</span><strong>${counts["Review Required"] || 0}</strong></div>
                <div class="customer-reservation-kpi"><span>${__("Partially Fulfilled")}</span><strong>${counts["Partially Fulfilled"] || 0}</strong></div>
                <div class="customer-reservation-kpi"><span>${__("Total")}</span><strong>${this.rows.length}</strong></div>
            </div>`;
        const cards = this.rows.length
            ? this.rows.map(row => this.card(row)).join("")
            : `<div class="text-muted text-center" style="padding:50px 0">${__("No Customer Reservations match the selected filters.")}</div>`;
        this.content.html(summary + cards);
        this.bindActions();
    }

    card(row) {
        const esc = frappe.utils.escape_html;
        const badgeClass = String(row.operational_status || "").toLowerCase().replaceAll(" ", "-");
        const items = (row.items || []).map(item =>
            `<span><strong>${esc(item.item_name || item.item_code)}</strong> — ${item.remaining_qty} ${esc(item.stock_uom || "")} ${__("remaining")}</span>`
        ).join("");
        const canAct = ["Active", "Review Required", "Partially Fulfilled"].includes(row.operational_status);
        return `
            <section class="customer-reservation-card" data-order="${esc(row.sales_order)}">
                <div class="customer-reservation-head">
                    <div><button class="btn btn-link p-0 open-order"><strong>${esc(row.sales_order)}</strong></button><br>
                        <span>${esc(row.customer_name || row.customer)} • ${esc(row.contact_mobile || "")}</span></div>
                    <span class="reservation-badge ${badgeClass}">${esc(row.operational_status || "")}</span>
                </div>
                <div class="customer-reservation-meta">
                    <span>${__("Branch")}: <strong>${esc(row.branch || "")}</strong></span>
                    <span>${__("Review")}: <strong>${esc(String(row.review_at || ""))}</strong></span>
                    <span>${__("Mode")}: <strong>${esc(row.fulfilment_mode || "Undecided")}</strong></span>
                    ${row.last_contact_outcome ? `<span>${__("Last contact")}: <strong>${esc(row.last_contact_outcome)}</strong></span>` : ""}
                </div>
                <div class="customer-reservation-items">${items}</div>
                ${row.notes ? `<div class="small text-muted mt-2">${esc(row.notes)}</div>` : ""}
                <div class="customer-reservation-actions">
                    ${canAct ? `<button class="btn btn-primary btn-sm open-pos">${__("Open in Pharmacy POS")}</button>
                    <button class="btn btn-default btn-sm contact-customer">${__("Record Contact")}</button>
                    <button class="btn btn-default btn-sm release-reservation">${__("Release")}</button>` : ""}
                    ${row.fulfilment_invoice ? `<button class="btn btn-default btn-sm open-invoice" data-invoice="${esc(row.fulfilment_invoice)}">${__("Open Invoice")}</button>` : ""}
                </div>
            </section>`;
    }

    bindActions() {
        this.content.find(".customer-reservation-card").each((_, element) => {
            const order = element.dataset.order;
            const row = this.rows.find(item => item.sales_order === order);
            element.querySelector(".open-order")?.addEventListener("click", () => frappe.set_route("Form", "Sales Order", order));
            element.querySelector(".open-pos")?.addEventListener("click", () => this.openPOS(row));
            element.querySelector(".contact-customer")?.addEventListener("click", () => this.recordContact(row));
            element.querySelector(".release-reservation")?.addEventListener("click", () => this.release(row));
            element.querySelector(".open-invoice")?.addEventListener("click", event => frappe.set_route("Form", "Sales Invoice", event.currentTarget.dataset.invoice));
        });
    }

    newReservation() {
        const dialog = new frappe.ui.Dialog({
            title: __("New Customer Reservation"),
            fields: [
                {fieldtype: "Link", fieldname: "customer", label: __("Customer"), options: "Customer", reqd: 1},
                {fieldtype: "Data", fieldname: "contact_mobile", label: __("Contact Mobile")},
                {fieldtype: "Column Break"},
                {fieldtype: "Link", fieldname: "branch", label: __("Branch"), options: "Branch", reqd: 1, default: this.branchField.get_value() || "Main Branch"},
                {fieldtype: "Section Break", label: __("Reserved Item")},
                {fieldtype: "Link", fieldname: "item_code", label: __("Item"), options: "Item", reqd: 1, get_query: () => ({filters: {is_stock_item: 1, disabled: 0}})},
                {fieldtype: "Float", fieldname: "qty", label: __("Quantity in Stock UOM"), reqd: 1, default: 1},
                {fieldtype: "Column Break"},
                {fieldtype: "Select", fieldname: "fulfilment_mode", label: __("Fulfilment Mode"), options: "Undecided\nPickup\nHome Delivery", default: "Undecided"},
                {fieldtype: "Datetime", fieldname: "review_at", label: __("Review At"), reqd: 1},
                {fieldtype: "Section Break"},
                {fieldtype: "Small Text", fieldname: "notes", label: __("Notes")}
            ],
            primary_action_label: __("Create and Reserve"),
            primary_action: async values => {
                try {
                    dialog.get_primary_btn().prop("disabled", true);
                    const result = await this.call("create_customer_reservation", {
                        data: JSON.stringify({...values, request_token: `${Date.now()}-${Math.random()}`})
                    });
                    dialog.hide();
                    frappe.show_alert({message: `${__("Reservation created")}: ${result.sales_order}`, indicator: "green"});
                    await this.refresh();
                } catch (error) {
                    console.error(error);
                } finally {
                    dialog.get_primary_btn().prop("disabled", false);
                }
            }
        });
        dialog.show();
    }

    recordContact(row) {
        const dialog = new frappe.ui.Dialog({
            title: `${__("Record Customer Contact")}: ${row.sales_order}`,
            fields: [
                {fieldtype: "Select", fieldname: "outcome", label: __("Outcome"), options: "Still Needed\nConfirmed Pickup\nConfirmed Delivery\nNo Answer\nDeclined\nOther", reqd: 1},
                {fieldtype: "Datetime", fieldname: "next_review_at", label: __("Next Review At")},
                {fieldtype: "Small Text", fieldname: "notes", label: __("Contact Notes")}
            ],
            primary_action_label: __("Save Outcome"),
            primary_action: async values => {
                try {
                    dialog.get_primary_btn().prop("disabled", true);
                    await this.call("record_customer_contact", {sales_order: row.sales_order, ...values});
                    dialog.hide();
                    await this.refresh();
                } catch (error) {
                    console.error(error);
                } finally {
                    dialog.get_primary_btn().prop("disabled", false);
                }
            }
        });
        dialog.show();
    }

    release(row) {
        frappe.prompt(
            [{fieldtype: "Small Text", fieldname: "reason", label: __("Release Reason"), reqd: 1}],
            async values => {
                await this.call("release_customer_reservation", {sales_order: row.sales_order, reason: values.reason});
                frappe.show_alert({message: __("Reservation released"), indicator: "orange"});
                await this.refresh();
            },
            __("Release Customer Reservation"),
            __("Release")
        );
    }

    async openPOS(row) {
        let mode = row.fulfilment_mode || "Undecided";
        if (mode === "Undecided") {
            mode = await new Promise(resolve => {
                const dialog = new frappe.ui.Dialog({
                    title: __("Choose Fulfilment Mode"),
                    fields: [{fieldtype: "Select", fieldname: "mode", label: __("Mode"), options: "Pickup\nHome Delivery", reqd: 1, default: "Pickup"}],
                    primary_action_label: __("Open Pharmacy POS"),
                    primary_action: values => { dialog.hide(); resolve(values.mode); }
                });
                dialog.onhide = () => resolve("");
                dialog.show();
            });
            if (!mode) return;
            await this.call("set_customer_reservation_mode", {sales_order: row.sales_order, fulfilment_mode: mode});
        }
        const query = new URLSearchParams({customer_reservation: row.sales_order, fulfilment_mode: mode});
        window.location.assign(`/app/pharmacy-pos?${query.toString()}`);
    }
}
