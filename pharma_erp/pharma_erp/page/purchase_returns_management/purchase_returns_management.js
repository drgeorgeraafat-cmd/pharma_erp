frappe.pages["purchase-returns-management"].on_page_load = function (wrapper) {
    frappe.purchase_returns_management = new PharmacyPurchaseReturnsManagement(wrapper);
};

frappe.pages["purchase-returns-management"].on_page_show = function () {
    if (frappe.purchase_returns_management) frappe.purchase_returns_management.applyRouteOptions();
};

class PharmacyPurchaseReturnsManagement {
    constructor(wrapper) {
        this.wrapper = wrapper;
        this.page = frappe.ui.make_app_page({ parent: wrapper, title: __("Purchase Returns Management"), single_column: true });
        this.controls = {};
        this.rows = [];
        this.caseName = null;
        this.purchaseReturn = null;
        this.currency = frappe.defaults.get_default("currency") || "EGP";
        this.render();
        this.makeControls();
        this.bindEvents();
        this.loadBootstrap();
    }

    render() {
        this.$main = $(this.page.main).html(`
            <style>
                .prm-shell{padding:16px;max-width:1500px;margin:0 auto}.prm-hero{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;background:linear-gradient(135deg,var(--blue-50),var(--bg-color));border:1px solid var(--border-color);border-radius:14px;padding:18px;margin-bottom:14px}.prm-hero h3{margin:0 0 5px}.prm-muted{color:var(--text-muted)}.prm-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.prm-types{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.prm-type{border:1px solid var(--border-color);border-radius:12px;padding:13px;background:var(--card-bg);cursor:pointer}.prm-type.active{border-color:var(--primary);box-shadow:0 0 0 2px var(--blue-100)}.prm-type.disabled{opacity:.62;cursor:default}.prm-type strong{display:block;margin-bottom:4px}.prm-panel{border:1px solid var(--border-color);background:var(--card-bg);border-radius:12px;padding:14px;margin-bottom:14px}.prm-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.prm-control .control-label{font-weight:600}.prm-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}.prm-status{border-radius:999px;padding:7px 11px;background:var(--gray-100);font-weight:700}.prm-table-wrap{overflow:auto}.prm-table{width:100%;border-collapse:collapse;min-width:1200px}.prm-table th,.prm-table td{border-bottom:1px solid var(--border-color);padding:8px;vertical-align:middle}.prm-table th{font-size:12px;color:var(--text-muted);background:var(--subtle-fg)}.prm-table input,.prm-table select{min-width:90px}.prm-total{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}.prm-total>div{padding:11px;border:1px solid var(--border-color);border-radius:10px}.prm-total strong{display:block;font-size:18px}.prm-empty{text-align:center;padding:28px;color:var(--text-muted)}.prm-recent{width:100%;border-collapse:collapse}.prm-recent th,.prm-recent td{padding:8px;border-bottom:1px solid var(--border-color)}.prm-link{color:var(--primary);cursor:pointer;font-weight:600}.prm-note{padding:11px;border-radius:10px;background:var(--yellow-50);border:1px solid var(--yellow-200)}
                @media(max-width:900px){.prm-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.prm-types{grid-template-columns:1fr}.prm-hero{flex-direction:column}.prm-actions{justify-content:flex-start}}@media(max-width:560px){.prm-grid,.prm-total{grid-template-columns:1fr}}
            </style>
            <div class="prm-shell">
                <div class="prm-hero">
                    <div><h3>${__("Pharmacy Returns Control")}</h3><div class="prm-muted">${__("Invoice returns, regulatory batch recalls, and expired-drug returns in one operational system.")}</div></div>
                    <div class="prm-actions">
                        <span class="prm-status" data-role="case-status">${__("New Case")}</span>
                        <button class="btn btn-default btn-sm" data-action="purchase-page">${__("Purchase Management")}</button>
                        <button class="btn btn-default btn-sm" data-action="new-case">${__("New Case")}</button>
                        <button class="btn btn-primary btn-sm" data-action="save-case">${__("Save Case Draft")}</button>
                        <button class="btn btn-warning btn-sm" data-action="create-return">${__("Create Purchase Return Draft")}</button>
                    </div>
                </div>
                <div class="prm-types">
                    <div class="prm-type active" data-type="Return Against Invoice"><strong>${__("Return Against Invoice")}</strong><span class="prm-muted">${__("Partial or full return linked to a submitted Purchase Invoice.")}</span></div>
                    <div class="prm-type disabled" data-type="Regulatory Batch Recall"><strong>${__("Regulatory Batch Recall")}</strong><span class="prm-muted">${__("Foundation prepared. Batch quarantine and handover follows after invoice return testing.")}</span></div>
                    <div class="prm-type disabled" data-type="Expired Drugs Return"><strong>${__("Expired Drugs Return")}</strong><span class="prm-muted">${__("Foundation prepared. Supplier allowance calculation follows in the next stage.")}</span></div>
                </div>
                <div class="prm-panel">
                    <div class="prm-grid" data-role="controls"></div>
                    <div class="prm-toolbar">
                        <button class="btn btn-default btn-sm" data-action="load-invoice">${__("Load Invoice Items")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-original" disabled>${__("Open Original Invoice")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-return" disabled>${__("Open Purchase Return")}</button>
                        <span class="prm-muted" data-role="invoice-summary"></span>
                    </div>
                </div>
                <div class="prm-panel"><div class="prm-note">${__("The company/distributor receiving the goods is the same party responsible for payment or deduction from its supplier claim.")}</div></div>
                <div class="prm-panel">
                    <div class="prm-table-wrap" data-role="items"></div>
                    <div class="prm-total">
                        <div><span class="prm-muted">${__("Selected Quantity")}</span><strong data-role="total-qty">0</strong></div>
                        <div><span class="prm-muted">${__("Requested Return Value")}</span><strong data-role="total-value">0.00</strong></div>
                        <div><span class="prm-muted">${__("Selected Lines")}</span><strong data-role="total-lines">0</strong></div>
                    </div>
                </div>
                <div class="prm-panel"><h4>${__("Recent Return Cases")}</h4><div data-role="recent"></div></div>
            </div>`);
    }

    makeControl(name, df, value="") {
        const $host = $('<div class="prm-control"></div>').appendTo(this.$main.find('[data-role="controls"]'));
        const control = frappe.ui.form.make_control({parent:$host, df:{fieldname:name,...df}, render_input:true});
        control.set_value(value);
        this.controls[name] = control;
        return control;
    }

    makeControls() {
        this.makeControl("return_type", {label:__("Return Type"), fieldtype:"Select", options:"Return Against Invoice\nRegulatory Batch Recall\nExpired Drugs Return", reqd:1}, "Return Against Invoice");
        this.makeControl("company", {label:__("Company"), fieldtype:"Link", options:"Company", reqd:1});
        this.makeControl("posting_date", {label:__("Posting Date"), fieldtype:"Date", reqd:1});
        this.makeControl("supplier", {label:__("Receiving Company / Distributor"), fieldtype:"Link", options:"Supplier", reqd:1});
        this.makeControl("original_purchase_invoice", {label:__("Original Purchase Invoice"), fieldtype:"Link", options:"Purchase Invoice", reqd:1, get_query:()=>({filters:{docstatus:1,is_return:0,company:this.value("company")||undefined}})});
        this.makeControl("settlement_method", {label:__("Settlement Method"), fieldtype:"Select", options:"Pending Settlement\nDeduct from Supplier Claim\nCash / Bank Refund\nMixed Settlement", reqd:1}, "Pending Settlement");
        this.makeControl("remarks", {label:__("Return Notes"), fieldtype:"Small Text"});
        this.makeControl("case_reference", {label:__("Case Reference"), fieldtype:"Data", read_only:1});
        this.controls.return_type.df.onchange = () => this.refreshReturnTypeUI(this.value("return_type"), true);
        this.controls.original_purchase_invoice.df.onchange = () => this.syncOriginalButtons();
    }

    value(name){return this.controls[name] ? this.controls[name].get_value() : "";}
    async setValue(name,value){if(this.controls[name]) await this.controls[name].set_value(value||"");}
    money(value){return format_currency(flt(value), this.currency);}
    esc(value){return frappe.utils.escape_html(String(value??""));}

    bindEvents() {
        this.$main.on("click", "[data-action='purchase-page']", ()=>frappe.set_route("purchase-invoice-management"));
        this.$main.on("click", "[data-action='new-case']", ()=>this.newCase());
        this.$main.on("click", "[data-action='load-invoice']", ()=>this.loadInvoice());
        this.$main.on("click", "[data-action='save-case']", ()=>this.saveCase());
        this.$main.on("click", "[data-action='create-return']", ()=>this.createReturnDraft());
        this.$main.on("click", "[data-action='open-original']", ()=>{const n=this.value("original_purchase_invoice");if(n)frappe.set_route("Form","Purchase Invoice",n);});
        this.$main.on("click", "[data-action='open-return']", ()=>{if(this.purchaseReturn)frappe.set_route("Form","Purchase Invoice",this.purchaseReturn);});
        this.$main.on("click", ".prm-type:not(.disabled)", e=>this.setReturnType($(e.currentTarget).data("type")));
        this.$main.on("input change", "[data-row-field]", e=>this.updateRow(e));
        this.$main.on("click", "[data-action='open-case'],[data-action='open-case-page']", e=>this.loadCase($(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-case-document']", e=>frappe.set_route("Form","Pharmacy Return Case",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-original']", e=>frappe.set_route("Form","Purchase Invoice",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-return']", e=>frappe.set_route("Form","Purchase Invoice",$(e.currentTarget).data("name")));
    }

    async loadBootstrap() {
        const routeInvoice = frappe.route_options && frappe.route_options.purchase_invoice;
        const response = await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_bootstrap",args:{purchase_invoice:routeInvoice||""},freeze:true,freeze_message:__("Loading returns management...")});
        this.bootstrap=response.message||{};
        await this.setValue("company",this.bootstrap.company);
        await this.setValue("posting_date",this.bootstrap.posting_date);
        this.renderRecent(this.bootstrap.recent_cases||[]);
        if(this.bootstrap.invoice) await this.applyInvoice(this.bootstrap.invoice);
        await this.applyRouteOptions();
    }

    async applyRouteOptions(){
        const options=frappe.route_options||{};
        if(options.return_type) await this.setValue("return_type",options.return_type);
        if(options.return_case){
            await this.loadCase(options.return_case);
        }else if(options.purchase_invoice && options.purchase_invoice!==this.value("original_purchase_invoice")){
            await this.setValue("original_purchase_invoice",options.purchase_invoice);
            if(this.bootstrap) await this.loadInvoice();
        }
        frappe.route_options=null;
    }

    async setReturnType(type, notify=true){
        type=type||"Return Against Invoice";
        if(this.value("return_type")!==type){
            await this.setValue("return_type",type);
        }
        this.refreshReturnTypeUI(type, notify);
    }

    refreshReturnTypeUI(type, notify=false){
        type=type||"Return Against Invoice";
        this.$main.find(".prm-type").removeClass("active");
        this.$main.find(`.prm-type[data-type="${type}"]`).addClass("active");
        const invoiceMode=type==="Return Against Invoice";
        this.$main.find("[data-action='load-invoice'],[data-action='create-return']").prop("disabled",!invoiceMode);
        if(notify && !invoiceMode){
            frappe.show_alert({message:__("This return type is prepared in the data model and will be activated after invoice-return testing."),indicator:"blue"},7);
        }
    }

    async loadInvoice(){
        const name=this.value("original_purchase_invoice");
        if(!name){frappe.msgprint({title:__("Original Invoice Required"),message:__("Select a submitted Purchase Invoice first."),indicator:"orange"});return;}
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_invoice_for_return",args:{name},freeze:true,freeze_message:__("Loading invoice items...")});
        await this.applyInvoice(r.message||{});
    }

    async applyInvoice(invoice){
        await this.setValue("company",invoice.company);
        await this.setValue("supplier",invoice.supplier);
        await this.setValue("original_purchase_invoice",invoice.name);
        this.currency=invoice.currency||this.currency;
        this.rows=(invoice.items||[]).map(row=>({...row,return_qty:flt(row.return_qty),return_amount:flt(row.return_amount)}));
        this.$main.find('[data-role="invoice-summary"]').text(`${invoice.supplier_name||invoice.supplier||""} • ${invoice.bill_no||invoice.name||""} • ${this.money(invoice.grand_total)}`);
        this.renderItems();this.syncOriginalButtons();
    }

    async loadCase(name){
        if(!name)return;
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_case",
            args:{name},
            freeze:true,
            freeze_message:__("Loading return case...")
        });
        await this.applyCase(r.message||{});
    }

    async applyCase(doc){
        if(!doc.name){
            frappe.throw(__("Return Case could not be loaded."));
        }
        this.caseName=doc.name;
        this.purchaseReturn=doc.purchase_return||null;
        await this.setReturnType(doc.return_type||"Return Against Invoice",false);
        await this.setValue("company",doc.company);
        await this.setValue("posting_date",doc.posting_date);
        await this.setValue("supplier",doc.supplier);
        await this.setValue("original_purchase_invoice",doc.original_purchase_invoice);
        await this.setValue("settlement_method",doc.settlement_method||"Pending Settlement");
        await this.setValue("remarks",doc.remarks||"");
        await this.setValue("case_reference",doc.name);
        this.rows=(doc.items||[]).map(row=>({
            ...row,
            return_qty:flt(row.return_qty),
            return_amount:flt(row.return_amount)||flt(row.return_qty)*flt(row.rate)
        }));
        this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${doc.operational_status||__("Draft")}`);
        this.$main.find('[data-role="invoice-summary"]').text([
            doc.supplier||"",
            doc.original_purchase_invoice||"",
            this.money(doc.requested_return_value)
        ].filter(Boolean).join(" • "));
        this.renderItems();
        this.syncOriginalButtons();
        window.scrollTo({top:0,behavior:"smooth"});
        frappe.show_alert({message:__("Return Case {0} opened in the page.",[doc.name]),indicator:"green"},5);
    }

    renderItems(){
        const $host=this.$main.find('[data-role="items"]');
        if(!this.rows.length){$host.html(`<div class="prm-empty">${__("Load a submitted Purchase Invoice to select return quantities.")}</div>`);this.refreshTotals();return;}
        const reasons=["Normal Return","Near Expiry","Expired","Damaged","Wrong Item","Wrong Quantity","Supplier Error","Health Authority Recall","Other"];
        $host.html(`<table class="prm-table"><thead><tr><th>#</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Expiry")}</th><th>${__("Warehouse")}</th><th>${__("Purchased")}</th><th>${__("Returned")}</th><th>${__("Available")}</th><th>${__("Return Qty")}</th><th>${__("Reason")}</th><th>${__("Rate")}</th><th>${__("Return Value")}</th></tr></thead><tbody>${this.rows.map((r,i)=>`<tr><td>${i+1}</td><td><strong>${this.esc(r.item_name||r.item_code)}</strong><div class="prm-muted">${this.esc(r.item_code)}</div></td><td>${this.esc(r.batch_no||"—")}</td><td>${this.esc(r.expiry_date||"—")}</td><td>${this.esc(r.warehouse||"")}</td><td>${flt(r.original_qty)}</td><td>${flt(r.already_returned_qty)}</td><td>${flt(r.available_to_return_qty)}</td><td><input class="form-control input-sm" type="number" min="0" max="${flt(r.available_to_return_qty)}" step="any" data-row-field="return_qty" data-index="${i}" value="${flt(r.return_qty)}"></td><td><select class="form-control input-sm" data-row-field="return_reason" data-index="${i}">${reasons.map(x=>`<option ${x===(r.return_reason||"Normal Return")?"selected":""}>${this.esc(x)}</option>`).join("")}</select></td><td>${this.money(r.rate)}</td><td data-row-amount="${i}">${this.money(flt(r.return_qty)*flt(r.rate))}</td></tr>`).join("")}</tbody></table>`);
        this.refreshTotals();
    }

    updateRow(event){
        const $el=$(event.currentTarget),index=Number($el.data("index")),field=$el.data("row-field"),row=this.rows[index];if(!row)return;
        if(field==="return_qty"){
            let qty=Math.max(0,flt($el.val()));const max=flt(row.available_to_return_qty);if(qty>max){qty=max;$el.val(max);frappe.show_alert({message:__("Return quantity was limited to the available quantity."),indicator:"orange"},5);}row.return_qty=qty;row.return_amount=qty*flt(row.rate);this.$main.find(`[data-row-amount="${index}"]`).text(this.money(row.return_amount));
        }else row[field]=$el.val();this.refreshTotals();
    }

    refreshTotals(){
        const selected=this.rows.filter(r=>flt(r.return_qty)>0),qty=selected.reduce((a,r)=>a+flt(r.return_qty),0),value=selected.reduce((a,r)=>a+flt(r.return_qty)*flt(r.rate),0);
        this.$main.find('[data-role="total-qty"]').text(qty);
        this.$main.find('[data-role="total-value"]').text(this.money(value));
        this.$main.find('[data-role="total-lines"]').text(selected.length);
    }

    payload(){return {name:this.caseName,return_type:this.value("return_type"),company:this.value("company"),posting_date:this.value("posting_date"),supplier:this.value("supplier"),original_purchase_invoice:this.value("original_purchase_invoice"),settlement_method:this.value("settlement_method"),remarks:this.value("remarks"),items:this.rows};}

    async saveCase(silent=false){
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.save_case",args:{payload:this.payload()},freeze:true,freeze_message:__("Saving return case...")});
        const doc=r.message||{};this.caseName=doc.name;this.purchaseReturn=doc.purchase_return||null;await this.setValue("case_reference",doc.name);this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${doc.operational_status||__("Draft")}`);this.syncOriginalButtons();if(!silent)frappe.show_alert({message:__("Return Case {0} saved.",[doc.name]),indicator:"green"},6);await this.refreshRecent();return doc;
    }

    async createReturnDraft(){
        if(this.value("return_type")!=="Return Against Invoice")return;
        const doc=await this.saveCase(true);
        const answer=await new Promise(resolve=>frappe.confirm(__("Create an official Purchase Return draft for case {0}? The official document will remain Draft for review.",[doc.name]),()=>resolve(true),()=>resolve(false)));
        if(!answer)return;
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_purchase_return_draft",args:{case_name:doc.name},freeze:true,freeze_message:__("Creating Purchase Return draft...")});
        this.purchaseReturn=r.message.purchase_return;this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${__("Purchase Return Draft Created")}`);this.syncOriginalButtons();frappe.show_alert({message:__("Purchase Return {0} created as Draft.",[this.purchaseReturn]),indicator:"green"},8);await this.refreshRecent();frappe.set_route("Form","Purchase Invoice",this.purchaseReturn);
    }

    syncOriginalButtons(){this.$main.find('[data-action="open-original"]').prop("disabled",!this.value("original_purchase_invoice"));this.$main.find('[data-action="open-return"]').prop("disabled",!this.purchaseReturn);}
    async refreshRecent(){const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.list_recent_cases",args:{company:this.value("company")}});this.renderRecent(r.message||[]);}
    renderRecent(rows){
        const $h=this.$main.find('[data-role="recent"]');
        if(!rows.length){
            $h.html(`<div class="prm-empty">${__("No return cases yet.")}</div>`);
            return;
        }
        $h.html(`<div class="prm-table-wrap"><table class="prm-recent"><thead><tr><th>${__("Case")}</th><th>${__("Date")}</th><th>${__("Type")}</th><th>${__("Receiving Company")}</th><th>${__("Original Invoice")}</th><th>${__("Purchase Return")}</th><th>${__("Status")}</th><th>${__("Requested Value")}</th><th>${__("Actions")}</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${this.esc(r.name)}</strong></td><td>${this.esc(r.posting_date||"")}</td><td>${this.esc(r.return_type||"")}</td><td>${this.esc(r.supplier||"")}</td><td>${r.original_purchase_invoice?`<span class="prm-link" data-action="open-recent-original" data-name="${this.esc(r.original_purchase_invoice)}">${this.esc(r.original_purchase_invoice)}</span>`:"—"}</td><td>${r.purchase_return?`<span class="prm-link" data-action="open-recent-return" data-name="${this.esc(r.purchase_return)}">${this.esc(r.purchase_return)}</span>`:"—"}</td><td>${this.esc(r.operational_status||"")}</td><td>${this.money(r.requested_return_value)}</td><td><div class="prm-actions" style="justify-content:flex-start;min-width:210px"><button type="button" class="btn btn-primary btn-xs" data-action="open-case-page" data-name="${this.esc(r.name)}">${__("Open in Page")}</button><button type="button" class="btn btn-default btn-xs" data-action="open-case-document" data-name="${this.esc(r.name)}">${__("Open Document")}</button></div></td></tr>`).join("")}</tbody></table></div>`);
    }

    async newCase(){this.caseName=null;this.purchaseReturn=null;this.rows=[];await this.setReturnType("Return Against Invoice",false);await this.setValue("supplier","");await this.setValue("original_purchase_invoice","");await this.setValue("settlement_method","Pending Settlement");await this.setValue("remarks","");await this.setValue("case_reference","");this.$main.find('[data-role="case-status"]').text(__("New Case"));this.$main.find('[data-role="invoice-summary"]').text("");this.renderItems();this.syncOriginalButtons();}
}
