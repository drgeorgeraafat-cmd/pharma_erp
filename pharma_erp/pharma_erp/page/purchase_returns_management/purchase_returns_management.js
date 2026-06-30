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
        this.quarantineStockEntry = null;
        this.currency = frappe.defaults.get_default("currency") || "EGP";
        this.render();
        this.makeControls();
        this.bindEvents();
        this.loadBootstrap();
    }

    render() {
        this.$main = $(this.page.main).html(`
            <style>
                .prm-shell{padding:16px;max-width:1500px;margin:0 auto}.prm-hero{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;background:linear-gradient(135deg,var(--blue-50),var(--bg-color));border:1px solid var(--border-color);border-radius:14px;padding:18px;margin-bottom:14px}.prm-hero h3{margin:0 0 5px}.prm-muted{color:var(--text-muted)}.prm-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.prm-types{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.prm-type{border:1px solid var(--border-color);border-radius:12px;padding:13px;background:var(--card-bg);cursor:pointer}.prm-type.active{border-color:var(--primary);box-shadow:0 0 0 2px var(--blue-100)}.prm-type.disabled{opacity:.62;cursor:default}.prm-type strong{display:block;margin-bottom:4px}.prm-panel{border:1px solid var(--border-color);background:var(--card-bg);border-radius:12px;padding:14px;margin-bottom:14px}.prm-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.prm-control .control-label{font-weight:600}.prm-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}.prm-status{border-radius:999px;padding:7px 11px;background:var(--gray-100);font-weight:700}.prm-table-wrap{overflow:auto}.prm-table{width:100%;border-collapse:collapse;min-width:1200px}.prm-table th,.prm-table td{border-bottom:1px solid var(--border-color);padding:8px;vertical-align:middle}.prm-table th{font-size:12px;color:var(--text-muted);background:var(--subtle-fg)}.prm-table input,.prm-table select{min-width:90px}.prm-total{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}.prm-total>div{padding:11px;border:1px solid var(--border-color);border-radius:10px}.prm-total strong{display:block;font-size:18px}.prm-empty{text-align:center;padding:28px;color:var(--text-muted)}.prm-recent{width:100%;border-collapse:collapse}.prm-recent th,.prm-recent td{padding:8px;border-bottom:1px solid var(--border-color)}.prm-link{color:var(--primary);cursor:pointer;font-weight:600}.prm-note{padding:11px;border-radius:10px;background:var(--yellow-50);border:1px solid var(--yellow-200)}
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
                        <button class="btn btn-warning btn-sm" data-action="create-primary">${__("Create Purchase Return Draft")}</button>
                    </div>
                </div>
                <div class="prm-types">
                    <div class="prm-type active" data-type="Return Against Invoice"><strong>${__("Return Against Invoice")}</strong><span class="prm-muted">${__("Partial or full return linked to a submitted Purchase Invoice.")}</span></div>
                    <div class="prm-type" data-type="Regulatory Batch Recall"><strong>${__("Regulatory Batch Recall")}</strong><span class="prm-muted">${__("Load a recalled batch, quarantine its stock, then hand it to the receiving distributor.")}</span></div>
                    <div class="prm-type disabled" data-type="Expired Drugs Return"><strong>${__("Expired Drugs Return")}</strong><span class="prm-muted">${__("Supplier allowance calculation follows after recall testing.")}</span></div>
                </div>
                <div class="prm-panel">
                    <div class="prm-grid" data-role="controls"></div>
                    <div class="prm-toolbar">
                        <button class="btn btn-default btn-sm" data-action="load-invoice">${__("Load Invoice Items")}</button>
                        <button class="btn btn-default btn-sm" data-action="load-batch">${__("Add Item / Batch to Recall")}</button>
                        <button class="btn btn-default btn-sm" data-action="attach-notice">${__("Attach Authority Notice")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-original" disabled>${__("Open Original Invoice")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-return" disabled>${__("Open Purchase Return")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-quarantine" disabled>${__("Open Quarantine Transfer")}</button>
                        <span class="prm-muted" data-role="invoice-summary"></span>
                    </div>
                </div>
                <div class="prm-panel"><div class="prm-note" data-role="context-note">${__("The company/distributor receiving the goods is the same party responsible for payment or deduction from its supplier claim.")}</div></div>
                <div class="prm-panel">
                    <div class="prm-table-wrap" data-role="items"></div>
                    <div class="prm-total">
                        <div><span class="prm-muted" data-role="qty-label">${__("Selected Quantity")}</span><strong data-role="total-qty">0</strong></div>
                        <div data-role="stock-value-card"><span class="prm-muted">${__("Stock Value Quarantined")}</span><strong data-role="total-stock-value">0.00</strong></div>
                        <div><span class="prm-muted" data-role="value-label">${__("Requested Return Value")}</span><strong data-role="total-value">0.00</strong></div>
                        <div data-role="difference-card"><span class="prm-muted">${__("Expected Difference")}</span><strong data-role="total-difference">0.00</strong></div>
                        <div><span class="prm-muted">${__("Selected Lines")}</span><strong data-role="total-lines">0</strong></div>
                    </div>
                </div>
                <div class="prm-panel"><h4>${__("Recent Return Cases")}</h4><div data-role="recent"></div></div>
            </div>`);
    }

    makeControl(name, df, value="") {
        const $host = $('<div class="prm-control"></div>').attr('data-control-name', name).appendTo(this.$main.find('[data-role="controls"]'));
        const control = frappe.ui.form.make_control({parent:$host, df:{fieldname:name,...df}, render_input:true});
        control.set_value(value);
        control.$host = $host;
        this.controls[name] = control;
        return control;
    }

    makeControls() {
        this.makeControl("return_type", {label:__("Return Type"), fieldtype:"Select", options:"Return Against Invoice\nRegulatory Batch Recall\nExpired Drugs Return", reqd:1}, "Return Against Invoice");
        this.makeControl("company", {label:__("Company"), fieldtype:"Link", options:"Company", reqd:1});
        this.makeControl("posting_date", {label:__("Posting Date"), fieldtype:"Date", reqd:1});
        this.makeControl("supplier", {label:__("Receiving Company / Distributor"), fieldtype:"Link", options:"Supplier", reqd:1});
        this.makeControl("recall_source_warehouse", {label:__("Source Warehouse"), fieldtype:"Link", options:"Warehouse", get_query:()=>({filters:{company:this.value("company")||undefined,is_group:0,disabled:0}})});
        this.makeControl("recall_item_code", {
            label:__("Recalled Item"),
            fieldtype:"Link",
            options:"Item",
            get_query:()=>({
                query:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.search_recall_items",
                filters:{
                    warehouse:this.value("recall_source_warehouse")||"",
                    company:this.value("company")||""
                }
            })
        });
        this.makeControl("recall_batch_no", {
            label:__("Recalled Batch No"),
            fieldtype:"Link",
            options:"Batch",
            get_query:()=>({
                query:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.search_recall_batches",
                filters:{
                    item_code:this.value("recall_item_code")||"",
                    warehouse:this.value("recall_source_warehouse")||"",
                    company:this.value("company")||""
                }
            })
        });
        this.makeControl("recall_quarantine_warehouse", {label:__("Recall Quarantine Warehouse"), fieldtype:"Link", options:"Warehouse", get_query:()=>({filters:{company:this.value("company")||undefined,is_group:0,disabled:0}})});
        this.makeControl("original_purchase_invoice", {label:__("Original Purchase Invoice"), fieldtype:"Link", options:"Purchase Invoice", reqd:1, get_query:()=>({filters:{docstatus:1,is_return:0,company:this.value("company")||undefined}})});
        this.makeControl("settlement_method", {label:__("Settlement Method"), fieldtype:"Select", options:"Pending Settlement\nDeduct from Supplier Claim\nCash / Bank Refund\nMixed Settlement", reqd:1}, "Pending Settlement");
        this.makeControl("authority_notification_no", {label:__("Authority Notification Number"), fieldtype:"Data"});
        this.makeControl("authority_notification_date", {label:__("Authority Notification Date"), fieldtype:"Date"});
        this.makeControl("authority_notification_attachment", {label:__("Authority Notice Attachment"), fieldtype:"Data", read_only:1});
        this.makeControl("remarks", {label:__("Return Notes"), fieldtype:"Small Text"});
        this.makeControl("case_reference", {label:__("Case Reference"), fieldtype:"Data", read_only:1});
        this.controls.return_type.df.onchange = () => this.refreshReturnTypeUI(this.value("return_type"), true);
        this.controls.original_purchase_invoice.df.onchange = () => this.syncButtons();
        this.controls.company.df.onchange = () => this.applyCompanyDefaults();
        this.controls.recall_source_warehouse.df.onchange = async () => {
            await this.setValue("recall_item_code", "");
            await this.setValue("recall_batch_no", "");
            this.clearRecallRows();
        };
        this.controls.recall_item_code.df.onchange = async () => {
            await this.setValue("recall_batch_no", "");
        };
    }

    value(name){return this.controls[name] ? this.controls[name].get_value() : "";}
    async setValue(name,value){if(this.controls[name]) await this.controls[name].set_value(value||"");}
    money(value){return format_currency(flt(value), this.currency);}
    esc(value){return frappe.utils.escape_html(String(value??""));}
    showControl(name, show){if(this.controls[name]?.$host)this.controls[name].$host.toggle(Boolean(show));}

    clearRecallRows(){
        if(this.value("return_type")!=="Regulatory Batch Recall") return;
        this.rows=[];
        this.$main.find('[data-role="invoice-summary"]').text("");
        this.renderItems();
    }

    bindEvents() {
        this.$main.on("click", "[data-action='purchase-page']", ()=>frappe.set_route("purchase-invoice-management"));
        this.$main.on("click", "[data-action='new-case']", ()=>this.newCase());
        this.$main.on("click", "[data-action='load-invoice']", ()=>this.loadInvoice());
        this.$main.on("click", "[data-action='load-batch']", ()=>this.loadBatchStock());
        this.$main.on("click", "[data-action='attach-notice']", ()=>this.attachAuthorityNotice());
        this.$main.on("click", "[data-action='save-case']", ()=>this.saveCase());
        this.$main.on("click", "[data-action='create-primary']", ()=>this.createPrimaryDraft());
        this.$main.on("click", "[data-action='open-original']", ()=>{const n=this.value("original_purchase_invoice");if(n)frappe.set_route("Form","Purchase Invoice",n);});
        this.$main.on("click", "[data-action='open-return']", ()=>{if(this.purchaseReturn)frappe.set_route("Form","Purchase Invoice",this.purchaseReturn);});
        this.$main.on("click", "[data-action='open-quarantine']", ()=>{if(this.quarantineStockEntry)frappe.set_route("Form","Stock Entry",this.quarantineStockEntry);});
        this.$main.on("click", ".prm-type:not(.disabled)", e=>this.setReturnType($(e.currentTarget).data("type")));
        this.$main.on("input change", "[data-row-field]", e=>this.updateRow(e));
        this.$main.on("click", "[data-action='remove-recall-row']", e=>this.removeRecallRow(Number($(e.currentTarget).data("index"))));
        this.$main.on("click", "[data-action='open-case-page']", e=>this.loadCase($(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-case-document']", e=>frappe.set_route("Form","Pharmacy Return Case",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-original']", e=>frappe.set_route("Form","Purchase Invoice",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-return']", e=>frappe.set_route("Form","Purchase Invoice",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-quarantine']", e=>frappe.set_route("Form","Stock Entry",$(e.currentTarget).data("name")));
    }

    async loadBootstrap() {
        const routeInvoice = frappe.route_options && frappe.route_options.purchase_invoice;
        const response = await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_bootstrap",args:{purchase_invoice:routeInvoice||""},freeze:true,freeze_message:__("Loading returns management...")});
        this.bootstrap=response.message||{};
        await this.setValue("company",this.bootstrap.company);
        await this.setValue("posting_date",this.bootstrap.posting_date);
        await this.applyCompanyDefaults();
        this.renderRecent(this.bootstrap.recent_cases||[]);
        this.refreshReturnTypeUI("Return Against Invoice", false);
        if(this.bootstrap.invoice) await this.applyInvoice(this.bootstrap.invoice);
        await this.applyRouteOptions();
    }

    async applyCompanyDefaults(){
        const company=this.value("company");
        if(!company)return;
        if(this.bootstrap?.company===company && this.bootstrap.special_warehouses){
            if(!this.value("recall_source_warehouse") && this.bootstrap.default_warehouse) await this.setValue("recall_source_warehouse",this.bootstrap.default_warehouse);
            if(!this.value("recall_quarantine_warehouse")) await this.setValue("recall_quarantine_warehouse",this.bootstrap.special_warehouses.recall);
            return;
        }
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_bootstrap",args:{company}});
        const data=r.message||{};
        if(!this.value("recall_source_warehouse") && data.default_warehouse) await this.setValue("recall_source_warehouse",data.default_warehouse);
        if(data.special_warehouses?.recall) await this.setValue("recall_quarantine_warehouse",data.special_warehouses.recall);
    }

    async applyRouteOptions(){
        const options=frappe.route_options||{};
        if(options.return_type) await this.setReturnType(options.return_type,false);
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
        if(this.value("return_type")!==type) await this.setValue("return_type",type);
        this.refreshReturnTypeUI(type, notify);
    }

    refreshReturnTypeUI(type, notify=false){
        type=type||"Return Against Invoice";
        this.$main.find(".prm-type").removeClass("active");
        this.$main.find(`.prm-type[data-type="${type}"]`).addClass("active");
        const invoiceMode=type==="Return Against Invoice";
        const recallMode=type==="Regulatory Batch Recall";
        ["original_purchase_invoice"].forEach(name=>this.showControl(name,invoiceMode));
        ["recall_source_warehouse","recall_item_code","recall_batch_no","recall_quarantine_warehouse","authority_notification_no","authority_notification_date","authority_notification_attachment"].forEach(name=>this.showControl(name,recallMode));
        this.$main.find("[data-action='load-invoice']").toggle(invoiceMode);
        this.$main.find("[data-action='open-original'],[data-action='open-return']").toggle(invoiceMode);
        this.$main.find("[data-action='load-batch'],[data-action='attach-notice'],[data-action='open-quarantine']").toggle(recallMode);
        this.$main.find("[data-action='create-primary']").text(invoiceMode?__("Create Purchase Return Draft"):__("Create Quarantine Transfer Draft"));
        this.$main.find('[data-role="qty-label"]').text(recallMode?__("Recall Quantity"):__("Selected Quantity"));
        this.$main.find('[data-role="value-label"]').text(recallMode?__("Expected Supplier Credit"):__("Requested Return Value"));
        this.$main.find('[data-role="context-note"]').text(recallMode
            ?__("The quarantine transfer uses the stock valuation rate. Expected settlement rate is separate and remains editable for supplier credit estimation.")
            :__("The company/distributor receiving the goods is the same party responsible for payment or deduction from its supplier claim."));
        this.$main.find('[data-role="stock-value-card"],[data-role="difference-card"]').toggle(recallMode);
        if(notify && type==="Expired Drugs Return") frappe.show_alert({message:__("Expired Drugs Return will be activated after regulatory recall testing."),indicator:"blue"},7);
        this.renderItems();
        this.syncButtons();
    }

    async loadInvoice(){
        const name=this.value("original_purchase_invoice");
        if(!name){frappe.msgprint({title:__("Original Invoice Required"),message:__("Select a submitted Purchase Invoice first."),indicator:"orange"});return;}
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_invoice_for_return",args:{name},freeze:true,freeze_message:__("Loading invoice items...")});
        await this.applyInvoice(r.message||{});
    }

    async applyInvoice(invoice){
        await this.setReturnType("Return Against Invoice",false);
        await this.setValue("company",invoice.company);
        await this.setValue("supplier",invoice.supplier);
        await this.setValue("original_purchase_invoice",invoice.name);
        this.currency=invoice.currency||this.currency;
        this.rows=(invoice.items||[]).map(row=>({...row,return_qty:flt(row.return_qty),return_amount:flt(row.return_amount)}));
        this.$main.find('[data-role="invoice-summary"]').text(`${invoice.supplier_name||invoice.supplier||""} • ${invoice.bill_no||invoice.name||""} • ${this.money(invoice.grand_total)}`);
        this.renderItems();this.syncButtons();
    }

    async loadBatchStock(){
        const sourceWarehouse=this.value("recall_source_warehouse");
        const itemCode=this.value("recall_item_code");
        const batchNo=this.value("recall_batch_no");
        if(!sourceWarehouse){frappe.msgprint({title:__("Source Warehouse Required"),message:__("Select the source warehouse first."),indicator:"orange"});return;}
        if(!itemCode){frappe.msgprint({title:__("Item Required"),message:__("Select the recalled item first."),indicator:"orange"});return;}
        if(!batchNo){frappe.msgprint({title:__("Batch Required"),message:__("Select a batch belonging to the recalled item."),indicator:"orange"});return;}
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_batch_stock_for_recall",
            args:{batch_no:batchNo,item_code:itemCode,source_warehouse:sourceWarehouse,company:this.value("company")},
            freeze:true,
            freeze_message:__("Loading recalled batch stock...")
        });
        const data=r.message||{};
        const incoming=(data.rows||[]).map(row=>({
            ...row,
            return_qty:flt(row.return_qty),
            stock_valuation_rate:flt(row.stock_valuation_rate),
            stock_value:flt(row.return_qty)*flt(row.stock_valuation_rate),
            return_amount:flt(row.return_qty)*flt(row.rate)
        }));

        let added=0;
        incoming.forEach(row=>{
            const exists=this.rows.some(current=>
                current.item_code===row.item_code
                && current.batch_no===row.batch_no
                && current.warehouse===row.warehouse
            );
            if(exists)return;
            this.rows.push(row);
            added+=1;
        });

        if(!added){
            frappe.show_alert({
                message:__("This item, batch and warehouse are already included in the recall list."),
                indicator:"orange"
            },6);
        }else{
            frappe.show_alert({
                message:__("{0} recall line(s) added to the authority notice.",[added]),
                indicator:"green"
            },5);
        }

        await this.setValue("recall_item_code","");
        await this.setValue("recall_batch_no","");
        this.$main.find('[data-role="invoice-summary"]').text(
            __("{0} selected recall line(s) • Authority Notice {1}",[
                this.rows.length,
                this.value("authority_notification_no")||"—"
            ])
        );
        this.renderItems();
    }

    removeRecallRow(index){
        if(!Number.isInteger(index)||index<0||index>=this.rows.length)return;
        this.rows.splice(index,1);
        this.$main.find('[data-role="invoice-summary"]').text(
            __("{0} selected recall line(s) • Authority Notice {1}",[
                this.rows.length,
                this.value("authority_notification_no")||"—"
            ])
        );
        this.renderItems();
    }

    attachAuthorityNotice(){
        new frappe.ui.FileUploader({
            allow_multiple:false,
            restrictions:{allowed_file_types:["image/*","application/pdf"]},
            on_success: async file=>{
                await this.setValue("authority_notification_attachment",file.file_url);
                frappe.show_alert({message:__("Authority notice attached."),indicator:"green"},5);
            }
        });
    }

    async loadCase(name){
        if(!name)return;
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_case",args:{name},freeze:true,freeze_message:__("Loading return case...")});
        await this.applyCase(r.message||{});
    }

    async applyCase(doc){
        if(!doc.name)frappe.throw(__("Return Case could not be loaded."));
        this.caseName=doc.name;
        this.purchaseReturn=doc.purchase_return||null;
        this.quarantineStockEntry=doc.quarantine_stock_entry||null;
        await this.setReturnType(doc.return_type||"Return Against Invoice",false);
        await this.setValue("company",doc.company);
        await this.setValue("posting_date",doc.posting_date);
        await this.setValue("supplier",doc.supplier);
        await this.setValue("original_purchase_invoice",doc.original_purchase_invoice);
        await this.setValue("settlement_method",doc.settlement_method||"Pending Settlement");
        await this.setValue("authority_notification_no",doc.authority_notification_no);
        await this.setValue("authority_notification_date",doc.authority_notification_date);
        await this.setValue("authority_notification_attachment",doc.authority_notification_attachment);
        await this.setValue("recall_source_warehouse",doc.recall_source_warehouse||doc.items?.[0]?.warehouse||"");
        await this.setValue("recall_item_code","");
        await this.setValue("recall_quarantine_warehouse",doc.recall_quarantine_warehouse);
        await this.setValue("recall_batch_no","");
        await this.setValue("remarks",doc.remarks||"");
        await this.setValue("case_reference",doc.name);
        this.rows=(doc.items||[]).map(row=>({...row,return_qty:flt(row.return_qty),stock_valuation_rate:flt(row.stock_valuation_rate),stock_value:flt(row.stock_value)||flt(row.return_qty)*flt(row.stock_valuation_rate),return_amount:flt(row.return_amount)||flt(row.return_qty)*flt(row.rate)}));
        this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${doc.operational_status||__("Draft")}`);
        this.$main.find('[data-role="invoice-summary"]').text([doc.supplier||"",doc.original_purchase_invoice||doc.authority_notification_no||"",this.money(doc.requested_return_value)].filter(Boolean).join(" • "));
        this.renderItems();this.syncButtons();window.scrollTo({top:0,behavior:"smooth"});
        frappe.show_alert({message:__("Return Case {0} opened in the page.",[doc.name]),indicator:"green"},5);
    }

    renderItems(){
        const $host=this.$main.find('[data-role="items"]');
        const recallMode=this.value("return_type")==="Regulatory Batch Recall";
        if(!this.rows.length){
            $host.html(`<div class="prm-empty">${recallMode?__("Select an item and a positive-stock batch, then add it to the same authority notice. You can add multiple items and batches."):__("Load a submitted Purchase Invoice to select return quantities.")}</div>`);
            this.refreshTotals();return;
        }
        if(recallMode){
            $host.html(`<table class="prm-table"><thead><tr><th>#</th><th>${__("Source Warehouse")}</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Expiry")}</th><th>${__("Available Batch Qty")}</th><th>${__("Recall Qty")}</th><th>${__("Quarantine Warehouse")}</th><th>${__("Stock Valuation Rate")}</th><th>${__("Stock Value")}</th><th>${__("Expected Settlement Rate")}</th><th>${__("Expected Credit")}</th><th>${__("Expected Difference")}</th><th>${__("Action")}</th></tr></thead><tbody>${this.rows.map((r,i)=>{
                const stockValue=flt(r.return_qty)*flt(r.stock_valuation_rate);
                const expectedCredit=flt(r.return_qty)*flt(r.rate);
                return `<tr><td>${i+1}</td><td>${this.esc(r.warehouse||"")}</td><td><strong>${this.esc(r.item_name||r.item_code)}</strong><div class="prm-muted">${this.esc(r.item_code)}</div></td><td>${this.esc(r.batch_no||"—")}</td><td>${this.esc(r.expiry_date||"—")}</td><td>${flt(r.available_to_return_qty)}</td><td><input class="form-control input-sm" type="number" min="0" max="${flt(r.available_to_return_qty)}" step="any" data-row-field="return_qty" data-index="${i}" value="${flt(r.return_qty)}"></td><td>${this.esc(this.value("recall_quarantine_warehouse")||"")}</td><td>${this.money(r.stock_valuation_rate)}</td><td data-row-stock-value="${i}">${this.money(stockValue)}</td><td><input class="form-control input-sm" type="number" min="0" step="any" data-row-field="rate" data-index="${i}" value="${flt(r.rate)}"></td><td data-row-amount="${i}">${this.money(expectedCredit)}</td><td data-row-difference="${i}">${this.money(expectedCredit-stockValue)}</td><td><button type="button" class="btn btn-xs btn-danger" data-action="remove-recall-row" data-index="${i}">${__("Remove")}</button></td></tr>`;
            }).join("")}</tbody></table>`);
        }else{
            const reasons=["Normal Return","Near Expiry","Expired","Damaged","Wrong Item","Wrong Quantity","Supplier Error","Health Authority Recall","Other"];
            $host.html(`<table class="prm-table"><thead><tr><th>#</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Expiry")}</th><th>${__("Warehouse")}</th><th>${__("Purchased")}</th><th>${__("Returned")}</th><th>${__("Available")}</th><th>${__("Return Qty")}</th><th>${__("Reason")}</th><th>${__("Rate")}</th><th>${__("Return Value")}</th></tr></thead><tbody>${this.rows.map((r,i)=>`<tr><td>${i+1}</td><td><strong>${this.esc(r.item_name||r.item_code)}</strong><div class="prm-muted">${this.esc(r.item_code)}</div></td><td>${this.esc(r.batch_no||"—")}</td><td>${this.esc(r.expiry_date||"—")}</td><td>${this.esc(r.warehouse||"")}</td><td>${flt(r.original_qty)}</td><td>${flt(r.already_returned_qty)}</td><td>${flt(r.available_to_return_qty)}</td><td><input class="form-control input-sm" type="number" min="0" max="${flt(r.available_to_return_qty)}" step="any" data-row-field="return_qty" data-index="${i}" value="${flt(r.return_qty)}"></td><td><select class="form-control input-sm" data-row-field="return_reason" data-index="${i}">${reasons.map(x=>`<option ${x===(r.return_reason||"Normal Return")?"selected":""}>${this.esc(x)}</option>`).join("")}</select></td><td>${this.money(r.rate)}</td><td data-row-amount="${i}">${this.money(flt(r.return_qty)*flt(r.rate))}</td></tr>`).join("")}</tbody></table>`);
        }
        this.refreshTotals();
    }

    updateRow(event){
        const $el=$(event.currentTarget),index=Number($el.data("index")),field=$el.data("row-field"),row=this.rows[index];if(!row)return;
        if(field==="return_qty"){
            let qty=Math.max(0,flt($el.val()));const max=flt(row.available_to_return_qty);if(qty>max){qty=max;$el.val(max);frappe.show_alert({message:__("Quantity was limited to the available batch quantity."),indicator:"orange"},5);}row.return_qty=qty;
        }else if(field==="rate")row.rate=Math.max(0,flt($el.val()));
        else row[field]=$el.val();
        row.return_amount=flt(row.return_qty)*flt(row.rate);
        row.stock_value=flt(row.return_qty)*flt(row.stock_valuation_rate);
        this.$main.find(`[data-row-stock-value="${index}"]`).text(this.money(row.stock_value));
        this.$main.find(`[data-row-amount="${index}"]`).text(this.money(row.return_amount));
        this.$main.find(`[data-row-difference="${index}"]`).text(this.money(row.return_amount-row.stock_value));
        this.refreshTotals();
    }

    refreshTotals(){
        const selected=this.rows.filter(r=>flt(r.return_qty)>0);
        const qty=selected.reduce((a,r)=>a+flt(r.return_qty),0);
        const value=selected.reduce((a,r)=>a+flt(r.return_qty)*flt(r.rate),0);
        const stockValue=selected.reduce((a,r)=>a+flt(r.return_qty)*flt(r.stock_valuation_rate),0);
        this.$main.find('[data-role="total-qty"]').text(qty);
        this.$main.find('[data-role="total-stock-value"]').text(this.money(stockValue));
        this.$main.find('[data-role="total-value"]').text(this.money(value));
        this.$main.find('[data-role="total-difference"]').text(this.money(value-stockValue));
        this.$main.find('[data-role="total-lines"]').text(selected.length);
    }

    payload(){return {
        name:this.caseName,return_type:this.value("return_type"),company:this.value("company"),posting_date:this.value("posting_date"),supplier:this.value("supplier"),original_purchase_invoice:this.value("original_purchase_invoice"),settlement_method:this.value("settlement_method"),authority_notification_no:this.value("authority_notification_no"),authority_notification_date:this.value("authority_notification_date"),authority_notification_attachment:this.value("authority_notification_attachment"),recall_source_warehouse:this.value("recall_source_warehouse"),recall_item_code:this.value("recall_item_code"),recall_quarantine_warehouse:this.value("recall_quarantine_warehouse"),remarks:this.value("remarks"),items:this.rows
    };}

    async saveCase(silent=false){
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.save_case",args:{payload:this.payload()},freeze:true,freeze_message:__("Saving return case...")});
        const doc=r.message||{};this.caseName=doc.name;this.purchaseReturn=doc.purchase_return||null;this.quarantineStockEntry=doc.quarantine_stock_entry||null;await this.setValue("case_reference",doc.name);this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${doc.operational_status||__("Draft")}`);this.syncButtons();if(!silent)frappe.show_alert({message:__("Return Case {0} saved.",[doc.name]),indicator:"green"},6);await this.refreshRecent();return doc;
    }

    async createPrimaryDraft(){
        if(this.value("return_type")==="Regulatory Batch Recall")return this.createQuarantineDraft();
        return this.createReturnDraft();
    }

    async createReturnDraft(){
        const doc=await this.saveCase(true);
        const answer=await new Promise(resolve=>frappe.confirm(__("Create an official Purchase Return draft for case {0}? The official document will remain Draft for review.",[doc.name]),()=>resolve(true),()=>resolve(false)));
        if(!answer)return;
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_purchase_return_draft",args:{case_name:doc.name},freeze:true,freeze_message:__("Creating Purchase Return draft...")});
        this.purchaseReturn=r.message.purchase_return;this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${__("Purchase Return Draft Created")}`);this.syncButtons();frappe.show_alert({message:__("Purchase Return {0} created as Draft.",[this.purchaseReturn]),indicator:"green"},8);await this.refreshRecent();frappe.set_route("Form","Purchase Invoice",this.purchaseReturn);
    }

    async createQuarantineDraft(){
        const doc=await this.saveCase(true);
        const answer=await new Promise(resolve=>frappe.confirm(__("Create a Material Transfer draft to move the recalled batch into quarantine? Stock remains sellable until the Stock Entry is submitted."),()=>resolve(true),()=>resolve(false)));
        if(!answer)return;
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_quarantine_transfer_draft",args:{case_name:doc.name},freeze:true,freeze_message:__("Creating quarantine transfer draft...")});
        this.quarantineStockEntry=r.message.stock_entry;this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${__("Quarantine Transfer Draft Created")}`);this.syncButtons();frappe.show_alert({message:__("Stock Entry {0} created as Draft.",[this.quarantineStockEntry]),indicator:"green"},8);await this.refreshRecent();frappe.set_route("Form","Stock Entry",this.quarantineStockEntry);
    }

    syncButtons(){
        this.$main.find('[data-action="open-original"]').prop("disabled",!this.value("original_purchase_invoice"));
        this.$main.find('[data-action="open-return"]').prop("disabled",!this.purchaseReturn);
        this.$main.find('[data-action="open-quarantine"]').prop("disabled",!this.quarantineStockEntry);
    }

    async refreshRecent(){const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.list_recent_cases",args:{company:this.value("company")}});this.renderRecent(r.message||[]);}

    renderRecent(rows){
        const $h=this.$main.find('[data-role="recent"]');
        if(!rows.length){$h.html(`<div class="prm-empty">${__("No return cases yet.")}</div>`);return;}
        $h.html(`<div class="prm-table-wrap"><table class="prm-recent"><thead><tr><th>${__("Case")}</th><th>${__("Date")}</th><th>${__("Type")}</th><th>${__("Receiving Company")}</th><th>${__("Reference")}</th><th>${__("Official Movement")}</th><th>${__("Status")}</th><th>${__("Requested Value")}</th><th>${__("Actions")}</th></tr></thead><tbody>${rows.map(r=>{
            const ref=r.original_purchase_invoice||"—";
            const movement=r.purchase_return||r.quarantine_stock_entry||"—";
            const movementAction=r.purchase_return?"open-recent-return":r.quarantine_stock_entry?"open-recent-quarantine":"";
            return `<tr><td><strong>${this.esc(r.name)}</strong></td><td>${this.esc(r.posting_date||"")}</td><td>${this.esc(r.return_type||"")}</td><td>${this.esc(r.supplier||"")}</td><td>${r.original_purchase_invoice?`<span class="prm-link" data-action="open-recent-original" data-name="${this.esc(r.original_purchase_invoice)}">${this.esc(ref)}</span>`:this.esc(ref)}</td><td>${movementAction?`<span class="prm-link" data-action="${movementAction}" data-name="${this.esc(movement)}">${this.esc(movement)}</span>`:this.esc(movement)}</td><td>${this.esc(r.operational_status||"")}</td><td>${this.money(r.requested_return_value)}</td><td><div class="prm-actions" style="justify-content:flex-start;min-width:210px"><button type="button" class="btn btn-primary btn-xs" data-action="open-case-page" data-name="${this.esc(r.name)}">${__("Open in Page")}</button><button type="button" class="btn btn-default btn-xs" data-action="open-case-document" data-name="${this.esc(r.name)}">${__("Open Document")}</button></div></td></tr>`;
        }).join("")}</tbody></table></div>`);
    }

    async newCase(){
        this.caseName=null;this.purchaseReturn=null;this.quarantineStockEntry=null;this.rows=[];
        await this.setReturnType("Return Against Invoice",false);
        await this.setValue("supplier","");await this.setValue("original_purchase_invoice","");await this.setValue("settlement_method","Pending Settlement");await this.setValue("authority_notification_no","");await this.setValue("authority_notification_date","");await this.setValue("authority_notification_attachment","");await this.setValue("recall_item_code","");await this.setValue("recall_batch_no","");await this.setValue("recall_source_warehouse","");await this.applyCompanyDefaults();await this.setValue("remarks","");await this.setValue("case_reference","");
        this.$main.find('[data-role="case-status"]').text(__("New Case"));this.$main.find('[data-role="invoice-summary"]').text("");this.renderItems();this.syncButtons();
    }
}
