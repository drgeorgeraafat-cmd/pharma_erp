frappe.pages["customer-product-request-operations"].on_page_load = function (wrapper) {
    new CustomerProductRequestOperations(wrapper);
};

class CustomerProductRequestOperations {
    constructor(wrapper) {
        this.page = frappe.ui.make_app_page({parent: wrapper, title: __("Customer Product Request Operations"), single_column: true});
        this.rows = [];
        this.build();
        this.refresh();
    }

    build() {
        this.page.set_primary_action(__("New Product Request"), () => this.newRequest(), "add");
        this.page.add_inner_button(__("Evaluate Availability"), async () => { await this.call("evaluate_customer_product_requests"); await this.refresh(); });
        this.page.add_inner_button(__("Refresh"), () => this.refresh());
        this.status = this.page.add_field({fieldname:"request_status",label:__("Status"),fieldtype:"Select",options:"\nWaiting for Stock\nPartially Available\nAvailable for Contact\nContact Attempted\nStill Interested\nConverted to Reservation\nDeclined\nClosed\nCancelled",change:()=>this.refresh()});
        this.branch = this.page.add_field({fieldname:"branch",label:__("Branch"),fieldtype:"Link",options:"Branch",change:()=>this.refresh()});
        this.customer = this.page.add_field({fieldname:"customer",label:__("Customer"),fieldtype:"Link",options:"Customer",change:()=>this.refresh()});
        this.body = $("<div class='step2d-operations'></div>").appendTo(this.page.main);
        this.body.append(`<style>
          .step2d-summary{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:12px;margin:14px 0}.step2d-kpi,.step2d-card{background:var(--card-bg);border:1px solid var(--border-color);border-radius:10px;padding:13px}.step2d-kpi strong{display:block;font-size:22px;margin-top:4px}.step2d-card{margin-bottom:12px}.step2d-head{display:flex;justify-content:space-between;gap:12px}.step2d-meta,.step2d-items,.step2d-actions{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:10px}.step2d-meta{color:var(--text-muted)}.step2d-badge{border-radius:999px;padding:4px 9px;font-weight:600;background:var(--gray-200)}.step2d-badge.available-for-contact{background:var(--green-100);color:var(--green-800)}.step2d-badge.partially-available{background:var(--yellow-100);color:var(--yellow-800)}@media(max-width:900px){.step2d-summary{grid-template-columns:repeat(2,1fr)}}
        </style>`);
        this.content = $("<div></div>").appendTo(this.body);
    }

    call(method, args={}) { return frappe.call({method:`pharma_erp.pharma_erp.customer_product_request_service.${method}`,args}).then(r=>r.message); }
    async refresh() {
        this.content.html(`<div class="text-muted">${__("Loading product requests...")}</div>`);
        this.rows = await this.call("list_customer_product_requests", {status:this.status.get_value()||"",branch:this.branch.get_value()||"",customer:this.customer.get_value()||""}) || [];
        this.render();
    }
    render() {
        const counts = this.rows.reduce((a,r)=>(a[r.status]=(a[r.status]||0)+1,a),{});
        const summary = `<div class="step2d-summary"><div class="step2d-kpi">${__("Waiting")}<strong>${counts["Waiting for Stock"]||0}</strong></div><div class="step2d-kpi">${__("Available for Contact")}<strong>${counts["Available for Contact"]||0}</strong></div><div class="step2d-kpi">${__("Partially Available")}<strong>${counts["Partially Available"]||0}</strong></div><div class="step2d-kpi">${__("Total")}<strong>${this.rows.length}</strong></div></div>`;
        this.content.html(summary + (this.rows.length ? this.rows.map(r=>this.card(r)).join("") : `<div class="text-muted text-center p-5">${__("No product requests match the selected filters.")}</div>`));
        this.bind();
    }
    card(row) {
        const e=frappe.utils.escape_html, active=["Waiting for Stock","Partially Available","Available for Contact","Contact Attempted","Still Interested"].includes(row.status);
        const items=row.items.map(i=>`<span><strong>${e(i.item_name||i.item_code)}</strong>: ${i.matched_qty}/${i.remaining_qty} ${e(i.stock_uom||"")} ${__("matched")}${i.customer_reservation?` • <a data-route="${e(i.customer_reservation)}">${e(i.customer_reservation)}</a>`:""}</span>`).join("");
        return `<section class="step2d-card" data-request="${e(row.request)}"><div class="step2d-head"><div><button class="btn btn-link p-0 open-request"><strong>${e(row.request)}</strong></button><br>${e(row.customer_name||row.customer)} • ${e(row.contact_mobile||"")}</div><span class="step2d-badge ${e(row.status.toLowerCase().replaceAll(" ","-"))}">${e(row.status)}</span></div><div class="step2d-meta"><span>${__("Branch")}: <strong>${e(row.branch)}</strong></span><span>${__("Requested")}: <strong>${e(String(row.requested_at||""))}</strong></span>${row.last_contact_outcome?`<span>${__("Last contact")}: <strong>${e(row.last_contact_outcome)}</strong></span>`:""}</div><div class="step2d-items">${items}</div><div class="step2d-actions">${active?`<button class="btn btn-primary btn-sm contact">${__("Record Contact / Convert")}</button><button class="btn btn-default btn-sm evaluate">${__("Evaluate")}</button><button class="btn btn-default btn-sm close-request">${__("Close")}</button>`:""}</div></section>`;
    }
    bind() {
        this.content.find(".step2d-card").each((_,el)=>{const name=el.dataset.request,row=this.rows.find(r=>r.request===name);el.querySelector(".open-request")?.addEventListener("click",()=>frappe.set_route("Form","Customer Product Request",name));el.querySelector(".evaluate")?.addEventListener("click",async()=>{await this.call("evaluate_customer_product_requests",{item_codes:JSON.stringify(row.items.map(i=>i.item_code))});await this.refresh();});el.querySelector(".contact")?.addEventListener("click",()=>this.contact(row));el.querySelector(".close-request")?.addEventListener("click",()=>this.close(row));el.querySelectorAll("[data-route]").forEach(a=>a.addEventListener("click",()=>frappe.set_route("Form","Sales Order",a.dataset.route)));});
    }
    newRequest() {
        const d=new frappe.ui.Dialog({title:__("New Customer Product Request"),fields:[{fieldtype:"Link",fieldname:"customer",label:__("Customer"),options:"Customer",reqd:1},{fieldtype:"Data",fieldname:"contact_mobile",label:__("Contact Mobile")},{fieldtype:"Column Break"},{fieldtype:"Link",fieldname:"branch",label:__("Branch"),options:"Branch",reqd:1,default:this.branch.get_value()||"Main Branch"},{fieldtype:"Select",fieldname:"source",label:__("Source"),options:"Phone\nIn Person\nPharmacy POS\nOther",default:"Phone"},{fieldtype:"Section Break",label:__("Requested Items")},{fieldtype:"Table",fieldname:"items",label:__("Items"),reqd:1,cannot_add_rows:false,in_place_edit:true,data:[],fields:[{fieldtype:"Link",fieldname:"item_code",label:__("Item"),options:"Item",in_list_view:1,reqd:1,get_query:()=>({filters:{is_stock_item:1,disabled:0}})},{fieldtype:"Float",fieldname:"requested_qty",label:__("Quantity"),default:1,in_list_view:1,reqd:1}]},{fieldtype:"Small Text",fieldname:"notes",label:__("Notes")}],primary_action_label:__("Create Request"),primary_action:async v=>{d.get_primary_btn().prop("disabled",true);try{const r=await this.call("create_customer_product_request",{data:JSON.stringify({...v,request_token:`${Date.now()}-${Math.random()}`})});d.hide();frappe.show_alert({message:`${__("Product request created")}: ${r.request}`,indicator:"green"});await this.refresh();}finally{d.get_primary_btn().prop("disabled",false);}}});d.show();
    }
    contact(row) {
        const d=new frappe.ui.Dialog({title:`${__("Record Customer Contact")}: ${row.request}`,fields:[{fieldtype:"Select",fieldname:"outcome",label:__("Outcome"),options:"No Answer\nStill Interested\nConfirmed Pickup\nConfirmed Delivery\nDeclined",reqd:1},{fieldtype:"Check",fieldname:"allow_partial",label:__("Explicitly allow partial conversion"),default:0},{fieldtype:"Small Text",fieldname:"notes",label:__("Notes")}],primary_action_label:__("Save Outcome"),primary_action:async v=>{d.get_primary_btn().prop("disabled",true);try{const r=await this.call("record_customer_product_request_contact",{request:row.request,...v});d.hide();if(r.reservations?.length){frappe.show_alert({message:`${__("Created reservations")}: ${r.reservations.join(", ")}`,indicator:"green"});}await this.refresh();}finally{d.get_primary_btn().prop("disabled",false);}}});d.show();
    }
    close(row) { frappe.prompt([{fieldtype:"Small Text",fieldname:"reason",label:__("Close Reason"),reqd:1}],async v=>{await this.call("close_customer_product_request",{request:row.request,reason:v.reason});await this.refresh();},__("Close Product Request"),__("Close")); }
}
