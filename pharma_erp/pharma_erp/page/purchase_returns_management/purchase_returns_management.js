/* Purchase Returns Management v0.7.34 - wide consolidated picker and invoice-aware search */
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
        this.recentCases = [];
        this.recentSearch = "";
        this.recentFilter = "open";
        this.recentFromDate = "";
        this.recentToDate = "";
        this.printPaperSize = "A4";
        this.printMode = "Case Summary";
        this.recentDateControls = {};
        this.recentExpanded = false;
        this.caseName = null;
        this.purchaseReturn = null;
        this.purchaseReturnDocstatus = null;
        this.purchaseReturnStatus = null;
        this.quarantineStockEntry = null;
        this.handoverStockEntry = null;
        this.rejectionReturnStockEntry = null;
        this.rejectedQtyDestination = "";
        this.rejectedDestinationWarehouse = "";
        this.approvedDebitNote = null;
        this.approvedDebitNoteDocstatus = null;
        this.approvedDebitNoteStatus = null;
        this.approvedDebitNoteAmount = 0;
        this.approvedDebitNoteOutstanding = 0;
        this.supplierClaim = null;
        this.settlementStatus = "Pending Settlement";
        this.claimUtilizationStatus = "Not Applied";
        this.claimSettlementDate = null;
        this.plannedClaimDeduction = 0;
        this.claimDeductionAmount = 0;
        this.settledAmount = 0;
        this.remainingSettlementAmount = 0;
        this.approvedReturnValue = 0;
        this.refundPaymentEntry = null;
        this.refundPaymentEntryStatus = null;
        this.refundAmount = 0;
        this.refundEntriesCount = 0;
        this.hasOpenRefundDraft = false;
        this.refundPayments = [];
        this.quarantineDocstatus = null;
        this.handoverDocstatus = null;
        this.rejectionReturnDocstatus = null;
        this.currency = frappe.defaults.get_default("currency") || "EGP";
        this.render();
        this.makeControls();
        this.makeRecentDateControls();
        setTimeout(() => this.makeRecentDateControls(), 250);
        this.bindEvents();
        this.loadBootstrap();
    }

    render() {
        this.$main = $(this.page.main).html(`
            <style>
                .prm-shell{padding:16px 24px;max-width:none;width:min(100%,1900px);margin:0 auto}.prm-hero{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;background:linear-gradient(135deg,var(--blue-50),var(--bg-color));border:1px solid var(--border-color);border-radius:14px;padding:18px;margin-bottom:14px}.prm-hero h3{margin:0 0 5px}.prm-muted{color:var(--text-muted)}.prm-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.prm-types{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.prm-type{border:1px solid var(--border-color);border-radius:12px;padding:13px;background:var(--card-bg);cursor:pointer}.prm-type.active{border-color:var(--primary);box-shadow:0 0 0 2px var(--blue-100)}.prm-type.disabled{opacity:.62;cursor:default}.prm-type strong{display:block;margin-bottom:4px}.prm-panel{border:1px solid var(--border-color);background:var(--card-bg);border-radius:12px;padding:14px;margin-bottom:14px}.prm-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.prm-control .control-label{font-weight:600}.prm-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px}.prm-status{border-radius:999px;padding:7px 11px;background:var(--gray-100);font-weight:700}.prm-table-wrap{overflow:auto}.prm-table{width:100%;border-collapse:collapse;min-width:2200px}.prm-table th,.prm-table td{border-bottom:1px solid var(--border-color);padding:8px;vertical-align:middle;white-space:nowrap}.prm-table th{font-size:12px;color:var(--text-muted);background:var(--subtle-fg)}.prm-table input,.prm-table select{min-width:90px}.prm-total{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}.prm-total>div{padding:11px;border:1px solid var(--border-color);border-radius:10px}.prm-total strong{display:block;font-size:18px}.prm-empty{text-align:center;padding:28px;color:var(--text-muted)}.prm-recent{width:100%;border-collapse:collapse}.prm-recent th,.prm-recent td{padding:8px;border-bottom:1px solid var(--border-color);vertical-align:top}.prm-recent-header{display:block}.prm-recent-title h4{margin:0 0 4px}.prm-recent-filters{width:100%;display:flex;flex-direction:column;gap:8px;margin-top:10px}.prm-filter-counts{display:flex;gap:8px;justify-content:flex-end;align-items:center;flex-wrap:wrap}.prm-filter-row{display:grid;grid-template-columns:minmax(180px,240px) minmax(260px,1fr);gap:8px;align-items:center}.prm-date-row{display:grid;grid-template-columns:minmax(180px,1fr) minmax(180px,1fr) auto;gap:8px;align-items:end}.prm-filter-actions{display:flex;gap:8px;justify-content:flex-end;align-items:center;flex-wrap:wrap}.prm-recent-filters .form-control{width:100%;min-width:0}.prm-recent-filters .prm-date-filter{min-width:0}.prm-recent-filters .prm-date-filter .form-group{margin-bottom:0}.prm-recent-filters .prm-date-filter .control-label{display:none}.prm-recent-filters .prm-date-filter .frappe-control{margin-bottom:0}.prm-recent-filters .prm-date-filter input{width:100%;min-width:0}.prm-recent-filters .input-with-feedback{width:100%}.prm-date-row .btn{white-space:nowrap}.prm-date-row{display:grid !important;grid-template-columns:minmax(160px,1fr) minmax(160px,1fr) !important;gap:8px !important;align-items:end !important;width:100% !important}.prm-date-row .prm-date-filter{min-width:0 !important;width:100% !important}.prm-date-row .control-input-wrapper,.prm-date-row .frappe-control,.prm-date-row .form-group{width:100% !important}.prm-date-row input{width:100% !important;min-width:0 !important}.prm-recent-filters{width:100% !important}.prm-native-date-wrap{position:relative;display:flex !important;gap:6px;align-items:center;width:100%;min-width:0}.prm-native-date-wrap .prm-date-text{flex:1 1 auto;min-width:0;width:100%}.prm-date-picker-btn{flex:0 0 auto;padding:3px 7px}.prm-native-date-input{position:absolute;right:0;bottom:0;width:1px;height:1px;opacity:.01;pointer-events:none}.prm-date-row{display:grid !important;grid-template-columns:minmax(180px,1fr) minmax(180px,1fr) !important;gap:8px !important;align-items:center !important}.prm-print-note{padding:8px 10px;border:1px solid var(--yellow-200);background:var(--yellow-50);border-radius:8px;margin-bottom:8px}.prm-print-summary{font-family:Arial, sans-serif;color:#111}.prm-print-summary h2,.prm-print-summary h3{margin:0 0 8px}.prm-print-summary table{width:100%;border-collapse:collapse;margin-top:8px}.prm-print-summary th,.prm-print-summary td{border:1px solid #ddd;padding:6px;text-align:left}.prm-print-summary .muted{color:#666}.prm-print-summary .section{margin-top:12px}.prm-counter{border:1px solid var(--border-color);border-radius:999px;padding:6px 10px;background:var(--subtle-fg);font-weight:700;white-space:nowrap}.prm-counter.open{border-color:var(--yellow-300);background:var(--yellow-50)}.prm-counter.closed{border-color:var(--green-300);background:var(--green-50)}.prm-recent-body{display:none;margin-top:12px}.prm-recent-body.expanded{display:block}.prm-supplier-invoice{font-size:12px;color:var(--text-muted);margin-top:3px}.prm-print-dropdown{position:relative;display:inline-block}.prm-print-menu{display:none;position:absolute;right:0;top:100%;min-width:230px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;box-shadow:var(--shadow-md);z-index:50;padding:6px}.prm-print-dropdown.open .prm-print-menu{display:block}.prm-print-menu a{display:block;padding:6px 8px;border-radius:6px;color:var(--text-color);text-decoration:none;cursor:pointer;white-space:nowrap}.prm-print-menu a:hover{background:var(--subtle-fg)}.prm-print-menu .disabled{color:var(--text-muted);cursor:not-allowed;pointer-events:none}.prm-link{color:var(--primary);cursor:pointer;font-weight:600}.prm-note{padding:11px;border-radius:10px;background:var(--yellow-50);border:1px solid var(--yellow-200)}.prm-toolbar .btn[data-not-ready="1"]{opacity:.72}.prm-vat-yes{font-weight:700}.prm-vat-no{color:var(--text-muted)}.prm-workflow{display:none;margin-bottom:12px;padding:12px;border:1px solid var(--border-color);border-radius:12px;background:var(--subtle-fg)}.prm-workflow-steps{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.prm-workflow-step{padding:9px 10px;border:1px solid var(--border-color);border-radius:9px;background:var(--card-bg);font-size:12px}.prm-workflow-step strong{display:block;font-size:13px}.prm-workflow-step.done{border-color:var(--green-300);background:var(--green-50)}.prm-workflow-step.active{border-color:var(--primary);box-shadow:0 0 0 2px var(--blue-100)}.prm-next-step{margin-top:10px;font-weight:700}.prm-stage-table{min-width:900px}.prm-stage-table.prm-stage-pricing{min-width:1250px}.prm-picker-table{width:100%;min-width:1280px;border-collapse:collapse}.prm-picker-table th,.prm-picker-table td{border-bottom:1px solid var(--border-color);padding:7px;vertical-align:middle}.prm-picker-table th{font-size:12px;background:var(--subtle-fg);color:var(--text-muted)}.prm-picker-search{margin-bottom:10px}.prm-picker-dialog .modal-dialog{width:min(96vw,1450px);max-width:1450px}.prm-picker-dialog .modal-body{max-height:78vh;overflow:auto}.prm-control[data-control-name="original_purchase_invoice"] .awesomplete>ul,.prm-control[data-control-name="return_item_to_add"] .awesomplete>ul{min-width:560px!important;max-width:min(90vw,760px)!important;max-height:360px!important;overflow:auto!important}.prm-control[data-control-name="return_item_to_add"] .awesomplete>ul{min-width:650px!important}.prm-wide-table-note{font-size:12px;color:var(--text-muted);margin-top:4px}
                @media(max-width:900px){.prm-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.prm-types{grid-template-columns:1fr}.prm-hero{flex-direction:column}.prm-actions{justify-content:flex-start}.prm-workflow-steps{grid-template-columns:1fr 1fr}.prm-filter-row{grid-template-columns:1fr}.prm-date-row{grid-template-columns:1fr 1fr}}@media(max-width:560px){.prm-grid,.prm-total{grid-template-columns:1fr}.prm-date-row{grid-template-columns:1fr}}
            </style>
            <div class="prm-shell">
                <div class="prm-hero">
                    <div><h3>${__("Pharmacy Returns Control")}</h3><div class="prm-muted">${__("Invoice returns, regulatory batch recalls, and expired-drug returns in one operational system.")}</div></div>
                    <div class="prm-actions">
                        <span class="prm-status" data-role="case-status">${__("New Case")}</span>
                        <button class="btn btn-default btn-sm" data-action="purchase-page">${__("Purchase Management")}</button>
                        <button class="btn btn-default btn-sm" data-action="new-case">${__("New Case")}</button>
                        <button class="btn btn-primary btn-sm" data-action="save-case">${__("Save Case Draft")}</button>
                        <button class="btn btn-warning btn-sm" data-action="create-primary">${__("Create & Submit Purchase Return")}</button>
                        <button class="btn btn-default btn-sm" data-action="print-current-case" disabled>${__("Print Case")}</button>
                    </div>
                </div>
                <div class="prm-types">
                    <div class="prm-type active" data-type="Return Against Invoice"><strong>${__("Return Against Invoice")}</strong><span class="prm-muted">${__("Partial or full return linked to a submitted Purchase Invoice.")}</span></div>
                    <div class="prm-type" data-type="Regulatory Batch Recall"><strong>${__("Regulatory Batch Recall")}</strong><span class="prm-muted">${__("Load a recalled batch, quarantine its stock, then hand it to the receiving distributor.")}</span></div>
                    <div class="prm-type" data-type="Expired Drugs Return"><strong>${__("Expired Drugs Return")}</strong><span class="prm-muted">${__("Isolate expired or near-expiry batches, hand them to the supplier, then settle the approved value.")}</span></div>
                </div>
                <div class="prm-panel">
                    <div class="prm-workflow" data-role="recall-workflow">
                        <div class="prm-workflow-steps" data-role="workflow-steps"></div>
                        <div class="prm-next-step" data-role="next-step"></div>
                    </div>
                    <div class="prm-grid" data-role="controls"></div>
                    <div class="prm-toolbar">
                        <button class="btn btn-primary btn-sm" data-action="load-invoice">${__("Add Selected Item")}</button>
                        <button class="btn btn-default btn-sm" data-action="pick-invoice-items">${__("Pick Items From Invoice")}</button>
                        <button class="btn btn-default btn-sm" data-action="load-invoice-all">${__("Load All Invoice Items")}</button>
                        <button class="btn btn-default btn-sm" data-action="load-batch">${__("Add Item / Batch to Recall")}</button>
                        <button class="btn btn-default btn-sm" data-action="attach-notice">${__("Attach Authority Notice")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-original" disabled>${__("Open Original Invoice")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-return" disabled>${__("Open Purchase Return")}</button>
                        <button class="btn btn-danger btn-sm" data-action="delete-return-draft">${__("Delete Purchase Return Draft")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-quarantine" disabled>${__("Open Quarantine Transfer")}</button>
                        <button type="button" class="btn btn-danger btn-sm" data-action="cancel-quarantine">${__("Cancel Quarantine Transfer")}</button>
                        <button class="btn btn-success btn-sm" data-action="submit-quarantine">${__("Create & Submit Quarantine Transfer")}</button>
                        <button class="btn btn-info btn-sm" data-action="create-handover">${__("Create Supplier Handover Draft")}</button>
                        <button class="btn btn-success btn-sm" data-action="submit-handover">${__("Create & Submit Supplier Handover")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-handover" disabled>${__("Open Supplier Handover")}</button>
                        <button type="button" class="btn btn-danger btn-sm" data-action="cancel-handover">${__("Cancel Supplier Handover")}</button>
                        <button class="btn btn-default btn-sm" data-action="attach-handover">${__("Attach Handover Receipt")}</button>
                        <button class="btn btn-default btn-sm" data-action="attach-response">${__("Attach Supplier Response")}</button>
                        <button class="btn btn-success btn-sm" data-action="save-response">${__("Save Supplier Response")}</button>
                        <button type="button" class="btn btn-danger btn-sm" data-action="create-rejection-return">${__("Create Rejected Qty Destination Draft")}</button>
                        <button type="button" class="btn btn-success btn-sm" data-action="submit-rejection-return">${__("Create & Submit Rejected Qty Destination")}</button>
                        <button type="button" class="btn btn-default btn-sm" data-action="open-rejection-return" disabled>${__("Open Rejected Qty Document")}</button>
                        <button type="button" class="btn btn-danger btn-sm" data-action="cancel-rejection-return">${__("Cancel Rejected Qty Document")}</button>
                        <button class="btn btn-primary btn-sm" data-action="create-approved-debit-note">${__("Create Approved Debit Note Draft")}</button>
                        <button class="btn btn-success btn-sm" data-action="submit-approved-debit-note">${__("Create & Submit Approved Debit Note")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-approved-debit-note" disabled>${__("Open Approved Debit Note")}</button>
                        <button type="button" class="btn btn-danger btn-sm" data-action="cancel-approved-debit-note">${__("Cancel Approved Debit Note")}</button>
                        <button class="btn btn-warning btn-sm" data-action="create-claim-deduction">${__("Create / Link Supplier Claim Draft")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-supplier-claim" disabled>${__("Open Supplier Claim")}</button>
                        <button type="button" class="btn btn-danger btn-sm" data-action="remove-claim-deduction">${__("Remove Draft Claim Deduction")}</button>
                        <button type="button" class="btn btn-danger btn-sm" data-action="reverse-claim-deduction">${__("Reverse Supplier Claim Deduction")}</button>
                        <button class="btn btn-success btn-sm" data-action="create-refund-payment">${__("Create Supplier Refund Draft")}</button>
                        <button class="btn btn-success btn-sm" data-action="submit-refund-payment">${__("Create & Submit Supplier Refund")}</button>
                        <button class="btn btn-default btn-sm" data-action="open-refund-payment" disabled>${__("Open Latest Refund Payment")}</button>
                        <button type="button" class="btn btn-danger btn-sm" data-action="cancel-refund-payment">${__("Cancel Latest Refund Payment")}</button>
                        <span class="prm-muted" data-role="invoice-summary"></span>
                    </div>
                </div>
                <div class="prm-panel"><div class="prm-note" data-role="context-note">${__("The company/distributor receiving the goods is the same party responsible for payment or deduction from its supplier claim.")}</div></div>
                <div class="prm-panel">
                    <div class="prm-table-wrap" data-role="items"></div>
                    <div class="prm-total">
                        <div data-role="total-qty-card"><span class="prm-muted" data-role="qty-label">${__("Selected Quantity")}</span><strong data-role="total-qty">0</strong></div>
                        <div data-role="stock-value-card"><span class="prm-muted">${__("Stock Value Quarantined")}</span><strong data-role="total-stock-value">0.00</strong></div>
                        <div data-role="requested-net-card"><span class="prm-muted">${__("Requested Net Value")}</span><strong data-role="total-net-value">0.00</strong></div>
                        <div data-role="requested-vat-card"><span class="prm-muted">${__("Requested VAT")}</span><strong data-role="total-vat-value">0.00</strong></div>
                        <div data-role="requested-total-card"><span class="prm-muted" data-role="value-label">${__("Requested Total Credit")}</span><strong data-role="total-value">0.00</strong></div>
                        <div data-role="difference-card"><span class="prm-muted">${__("Expected Difference")}</span><strong data-role="total-difference">0.00</strong></div>
                        <div data-role="total-lines-card"><span class="prm-muted">${__("Selected Lines")}</span><strong data-role="total-lines">0</strong></div>
                        <div data-role="handover-qty-card"><span class="prm-muted">${__("Supplier Handover Qty")}</span><strong data-role="total-handover-qty">0</strong></div>
                        <div data-role="accepted-qty-card"><span class="prm-muted">${__("Accepted Qty")}</span><strong data-role="total-accepted-qty">0</strong></div>
                        <div data-role="rejected-qty-card"><span class="prm-muted">${__("Rejected Qty")}</span><strong data-role="total-rejected-qty">0</strong></div>
                        <div data-role="pending-response-card"><span class="prm-muted">${__("Pending Supplier Response")}</span><strong data-role="total-pending-response">0</strong></div>
                        <div data-role="approved-value-card"><span class="prm-muted">${__("Approved Value")}</span><strong data-role="total-approved-value">0.00</strong></div>
                        <div data-role="debit-note-amount-card"><span class="prm-muted">${__("Debit Note Amount")}</span><strong data-role="debit-note-amount">0.00</strong></div>
                        <div data-role="debit-note-outstanding-card"><span class="prm-muted">${__("Supplier Credit Outstanding")}</span><strong data-role="debit-note-outstanding">0.00</strong></div>
                        <div data-role="debit-note-status-card"><span class="prm-muted">${__("Debit Note Status")}</span><strong data-role="debit-note-status">—</strong></div>
                        <div data-role="settlement-status-card"><span class="prm-muted">${__("Settlement Status")}</span><strong data-role="settlement-status">Pending Settlement</strong></div>
                        <div data-role="claim-utilization-card"><span class="prm-muted">${__("Supplier Credit Utilization")}</span><strong data-role="claim-utilization-status">Not Applied</strong></div>
                        <div data-role="claim-settlement-date-card"><span class="prm-muted">${__("Claim Settlement Date")}</span><strong data-role="claim-settlement-date">—</strong></div>
                        <div data-role="planned-claim-card"><span class="prm-muted">${__("Planned Claim Deduction")}</span><strong data-role="planned-claim-deduction">0.00</strong></div>
                        <div data-role="claim-deduction-card"><span class="prm-muted">${__("Confirmed Claim Deduction")}</span><strong data-role="claim-deduction-amount">0.00</strong></div>
                        <div data-role="refund-amount-card"><span class="prm-muted">${__("Confirmed Cash / Bank Refund")}</span><strong data-role="refund-amount">0.00</strong></div>
                        <div data-role="refund-status-card"><span class="prm-muted">${__("Latest Refund Payment Status")}</span><strong data-role="refund-payment-status">—</strong></div>
                        <div data-role="remaining-settlement-card"><span class="prm-muted">${__("Remaining Settlement")}</span><strong data-role="remaining-settlement">0.00</strong></div>
                    </div>
                </div>
                <div class="prm-panel prm-recent-panel">
                    <div class="prm-recent-header">
                        <div class="prm-recent-title">
                            <h4>${__("Return Cases")}</h4>
                            <div class="prm-muted">${__("Search by return case, purchase return, Debit Note, Supplier Invoice No, and date period.")}</div>
                        </div>
                        <div class="prm-recent-filters">
                            <div class="prm-filter-counts">
                                <span class="prm-counter open">${__("Open")}: <strong data-role="recent-open-count">0</strong></span>
                                <span class="prm-counter closed">${__("Closed")}: <strong data-role="recent-closed-count">0</strong></span>
                            </div>
                            <div class="prm-filter-row">
                                <select class="form-control input-sm" data-role="recent-filter">
                                    <option value="open">${__("Open / Needs Closing")}</option>
                                    <option value="closed">${__("Closed / Finished")}</option>
                                    <option value="all">${__("All Cases")}</option>
                                </select>
                                <input class="form-control input-sm" data-role="recent-search" placeholder="${__("Smart Search: case, invoice, SIN%55%, s n v 55")}">
                            </div>
                            <div class="prm-date-row" data-role="recent-date-row">
                                <div class="prm-native-date-wrap" data-role="recent-from-date-wrap">
                                    <input class="form-control input-sm prm-date-text" data-role="recent-from-date" placeholder="${__("From DD/MM/YYYY")}" autocomplete="off">
                                    <button type="button" class="btn btn-default btn-sm prm-date-picker-btn" data-action="open-recent-date-picker" data-target="recent-from-date">📅</button>
                                    <input type="date" class="prm-native-date-input" data-role="recent-from-date-native" tabindex="-1">
                                </div>
                                <div class="prm-native-date-wrap" data-role="recent-to-date-wrap">
                                    <input class="form-control input-sm prm-date-text" data-role="recent-to-date" placeholder="${__("To DD/MM/YYYY")}" autocomplete="off">
                                    <button type="button" class="btn btn-default btn-sm prm-date-picker-btn" data-action="open-recent-date-picker" data-target="recent-to-date">📅</button>
                                    <input type="date" class="prm-native-date-input" data-role="recent-to-date-native" tabindex="-1">
                                </div>
                            </div>
                            <div class="prm-filter-actions">
                                <button type="button" class="btn btn-default btn-sm" data-action="refresh-recent-list">${__("Search")}</button>
                                <button type="button" class="btn btn-default btn-sm" data-action="clear-recent-filters">${__("Clear")}</button>
                                <button type="button" class="btn btn-default btn-sm" data-action="toggle-recent-list">${__("Show List")}</button>
                            </div>
                        </div>
                    </div>
                    <div class="prm-recent-body" data-role="recent-body"><div data-role="recent"></div></div>
                </div>
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

    makeRecentDateControls() {
        const ensureWrap = (role, placeholder, targetLabel) => {
            let $input = this.$main.find(`[data-role="${role}"]`).first();
            if (!$input.length) return $();

            let $wrap = $input.closest(".prm-native-date-wrap");
            if (!$wrap.length) {
                $wrap = $(`<div class="prm-native-date-wrap" data-role="${role}-wrap"></div>`);
                $input.before($wrap);
                $wrap.append($input.detach());
            }

            $input = $wrap.find(`[data-role="${role}"]`).first();
            $input.addClass("prm-date-text form-control input-sm").attr("autocomplete", "off");
            if (!$input.attr("placeholder")) $input.attr("placeholder", placeholder);

            if (!$wrap.find(`[data-action="open-recent-date-picker"][data-target="${role}"]`).length) {
                $wrap.append(`<button type="button" class="btn btn-default btn-sm prm-date-picker-btn" data-action="open-recent-date-picker" data-target="${role}" title="${targetLabel}">📅</button>`);
            }
            if (!$wrap.find(`[data-role="${role}-native"]`).length) {
                $wrap.append(`<input type="date" class="prm-native-date-input" data-role="${role}-native" tabindex="-1">`);
            }
            return $wrap;
        };

        const $fromWrap = ensureWrap("recent-from-date", __("From DD/MM/YYYY"), __("Choose From Date"));
        const $toWrap = ensureWrap("recent-to-date", __("To DD/MM/YYYY"), __("Choose To Date"));

        if ($fromWrap.length && $toWrap.length) {
            let $row = this.$main.find('[data-role="recent-date-row"]').first();
            if (!$row.length || !$fromWrap.parent().is($row) || !$toWrap.parent().is($row)) {
                $row = $(`<div class="prm-date-row" data-role="recent-date-row"></div>`);
                $fromWrap.before($row);
                $row.append($fromWrap.detach());
                $row.append($toWrap.detach());
            }
        }

        const bindDate = (role, prop) => {
            const $input = this.$main.find(`[data-role="${role}"]`).first();
            const $native = this.$main.find(`[data-role="${role}-native"]`).first();
            if (!$input.length || !$native.length || $input.data("native-date-ready")) return;
            $input.data("native-date-ready", 1);

            const openPicker = () => {
                const native = $native.get(0);
                if (!native) return;
                try {
                    if (native.showPicker) native.showPicker();
                    else { native.focus(); native.click(); }
                } catch(e) {
                    try { native.focus(); native.click(); } catch(_) {}
                }
            };

            const applyTyped = (opts={}) => {
                const raw = $input.val() || "";
                const parsed = this.parseDisplayDate(raw);
                if (!parsed && String(raw).trim()) {
                    // Keep partial/short text while the user is typing.
                    return;
                }
                this[prop] = parsed || "";
                $input.val(this.formatDateDisplay(this[prop]) || "");
                $native.val(this[prop] || "");
                if (!opts.silent) {
                    this.setRecentExpanded(true);
                    this.refreshRecent();
                }
            };

            $input.off("focus.prmdate click.prmdate keydown.prmdate change.prmdate blur.prmdate");
            $native.off("change.prmdate");
            $input.on("focus.prmdate click.prmdate", () => openPicker());
            $input.on("keydown.prmdate", (e) => {
                if (e.key === "Enter") {
                    e.preventDefault();
                    applyTyped();
                }
            });
            $input.on("change.prmdate blur.prmdate", frappe.utils.debounce(() => applyTyped(), 120));
            $native.on("change.prmdate", () => {
                const iso = $native.val() || "";
                this[prop] = iso;
                $input.val(this.formatDateDisplay(iso) || "");
                this.setRecentExpanded(true);
                this.refreshRecent();
            });
        };

        this.$main.off("click.prmdatepicker", "[data-action='open-recent-date-picker']");
        this.$main.on("click.prmdatepicker", "[data-action='open-recent-date-picker']", (e) => {
            e.preventDefault();
            const role = $(e.currentTarget).data("target");
            const native = this.$main.find(`[data-role="${role}-native"]`).get(0);
            if (!native) return;
            try {
                if (native.showPicker) native.showPicker();
                else { native.focus(); native.click(); }
            } catch(err) {
                try { native.focus(); native.click(); } catch(_) {}
            }
        });

        bindDate("recent-from-date", "recentFromDate");
        bindDate("recent-to-date", "recentToDate");
    }

    setRecentDateControlValue(role, value) {
        const display = this.formatDateDisplay(value) || "";
        this.$main.find(`[data-role="${role}"]`).val(display).data("manual-raw-value", display);
        this.$main.find(`[data-role="${role}-native"]`).val(value || "");
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
        this.makeControl("returns_with_supplier_warehouse", {label:__("Returns With Supplier Warehouse"), fieldtype:"Link", options:"Warehouse", get_query:()=>({filters:{company:this.value("company")||undefined,is_group:0,disabled:0}})});
        this.makeControl("handover_date", {label:__("Supplier Handover Date"), fieldtype:"Date"});
        this.makeControl("handover_reference", {label:__("Supplier Handover Receipt Number"), fieldtype:"Data"});
        this.makeControl("handover_attachment", {label:__("Supplier Handover Receipt Attachment"), fieldtype:"Attach", description:__("Attach the supplier handover receipt image or PDF.")});
        this.makeControl("supplier_response_date", {label:__("Supplier Response Date"), fieldtype:"Date"});
        this.makeControl("supplier_response_reference", {label:__("Supplier Response Reference"), fieldtype:"Data"});
        this.makeControl("supplier_response_attachment", {label:__("Supplier Response Attachment"), fieldtype:"Attach", description:__("Attach the supplier response document image or PDF.")});
        this.makeControl("supplier_response_notes", {label:__("Supplier Response Notes"), fieldtype:"Small Text"});
        this.makeControl("rejected_qty_destination", {label:__("Rejected Qty Destination"), fieldtype:"Select", options:"\nReturn to Saleable Warehouse\nMove to Expired Disposal Warehouse\nDestruction / Documented Destruction"});
        this.makeControl("rejected_destination_warehouse", {label:__("Rejected Destination Warehouse"), fieldtype:"Link", options:"Warehouse", get_query:()=>({filters:{company:this.value("company")||undefined,is_group:0,disabled:0}})});
        this.makeControl("rejected_destruction_date", {label:__("Destruction Date"), fieldtype:"Date"});
        this.makeControl("rejected_destruction_reference", {label:__("Destruction Reference"), fieldtype:"Data"});
        this.makeControl("rejected_destruction_attachment", {label:__("Destruction Attachment"), fieldtype:"Attach", description:__("Attach destruction certificate or disposal document if available.")});
        this.makeControl("rejected_destruction_notes", {label:__("Destruction / Destination Notes"), fieldtype:"Small Text"});
        this.makeControl("approved_debit_note_posting_date", {label:__("Approved Debit Note Posting Date"), fieldtype:"Date"});
        this.makeControl("supplier_claim", {label:__("Supplier Claim"), fieldtype:"Link", options:"Supplier Claim", get_query:()=>({filters:{company:this.value("company")||undefined,supplier:this.value("supplier")||undefined,docstatus:0}})});
        this.makeControl("refund_posting_date", {label:__("Refund Posting Date"), fieldtype:"Date"});
        this.makeControl("refund_mode_of_payment", {label:__("Refund Mode of Payment"), fieldtype:"Link", options:"Mode of Payment"});
        this.makeControl("refund_account", {label:__("Refund Receiving Account"), fieldtype:"Link", options:"Account", get_query:()=>({filters:{company:this.value("company")||undefined,is_group:0,disabled:0,account_type:["in",["Bank","Cash"]]}})});
        this.makeControl("refund_request_amount", {label:__("Refund Amount to Receive"), fieldtype:"Currency"});
        this.makeControl("refund_reference_no", {label:__("Refund Transaction Reference"), fieldtype:"Data"});
        this.makeControl("refund_reference_date", {label:__("Refund Reference Date"), fieldtype:"Date"});
        this.makeControl("refund_notes", {label:__("Refund Notes"), fieldtype:"Small Text"});
        this.makeControl("supplier_credit_note_no", {label:__("Supplier Credit Note No"), fieldtype:"Data"});
        this.makeControl("supplier_credit_note_date", {label:__("Supplier Credit Note Date"), fieldtype:"Date"});
        this.makeControl("supplier_credit_note_attachment", {label:__("Supplier Credit Note Attachment"), fieldtype:"Attach", description:__("Attach the supplier credit note image or PDF.")});
        this.makeControl("original_purchase_invoice", {label:__("Purchase Invoice to Add"), fieldtype:"Link", options:"Purchase Invoice", get_query:()=>({filters:{docstatus:1,is_return:0,company:this.value("company")||undefined,supplier:this.value("supplier")||undefined}})});
        this.makeControl("return_item_to_add", {
            label:__("Item / Barcode to Add"),
            fieldtype:"Link",
            options:"Item",
            description:__("Type item code, barcode, or part of item name. Only matching rows from the selected invoice will be loaded."),
            get_query:()=>({
                query:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.search_invoice_return_items",
                filters:{
                    purchase_invoice:this.value("original_purchase_invoice")||"",
                    company:this.value("company")||"",
                    supplier:this.value("supplier")||""
                }
            })
        });
        this.makeControl("return_batch_no_to_add", {label:__("Batch No to Add (Optional)"), fieldtype:"Data", description:__("Use this when the same item exists in more than one batch inside the selected invoice.")});
        this.makeControl("settlement_method", {label:__("Settlement Method"), fieldtype:"Select", options:"Pending Settlement\nDeduct from Supplier Claim\nCash / Bank Refund\nMixed Settlement", reqd:1}, "Pending Settlement");
        this.makeControl("authority_notification_no", {label:__("Authority Notification Number"), fieldtype:"Data"});
        this.makeControl("authority_notification_date", {label:__("Authority Notification Date"), fieldtype:"Date"});
        this.makeControl("authority_notification_attachment", {label:__("Authority Notice Attachment"), fieldtype:"Attach", description:__("Attach the authority notice image or PDF.")});
        this.makeControl("remarks", {label:__("Return Notes"), fieldtype:"Small Text"});
        this.makeControl("case_reference", {label:__("Case Reference"), fieldtype:"Data", read_only:1});
        this.controls.return_type.df.onchange = () => this.refreshReturnTypeUI(this.value("return_type"), true);
        this.controls.original_purchase_invoice.df.onchange = () => this.syncButtons();
        this.controls.return_item_to_add.df.onchange = () => this.syncButtons();
        this.controls.return_batch_no_to_add.df.onchange = () => this.syncButtons();
        this.controls.supplier_credit_note_no.df.onchange = () => this.syncButtons();
        this.controls.settlement_method.df.onchange = () => {
            this.refreshSettlementUI();
            this.syncButtons();
            this.refreshProgressiveUI();
        };
        this.controls.company.df.onchange = () => this.applyCompanyDefaults();
        this.controls.recall_source_warehouse.df.onchange = async () => {
            await this.setValue("recall_item_code", "");
            await this.setValue("recall_batch_no", "");
            this.clearRecallRows();
            this.syncButtons();
        };
        this.controls.recall_item_code.df.onchange = async () => {
            await this.setValue("recall_batch_no", "");
            this.syncButtons();
        };
        this.controls.recall_batch_no.df.onchange = () => this.syncButtons();
        this.controls.recall_quarantine_warehouse.df.onchange = () => this.syncButtons();
        this.controls.rejected_qty_destination.df.onchange = async () => {
            await this.applyRejectedDestinationDefault();
            this.refreshProgressiveUI();
            this.syncButtons();
        };
        this.controls.rejected_destination_warehouse.df.onchange = () => this.syncButtons();
        this.controls.rejected_destruction_date.df.onchange = () => this.syncButtons();
        this.controls.rejected_destruction_notes.df.onchange = () => this.syncButtons();
    }

    controlValue(name){
        const control=this.controls[name];
        if(!control) return "";
        let value = control.get_value ? control.get_value() : (control.value || "");
        if(value) return value;
        const candidates = [];
        try{ candidates.push(control.$input?.val?.()); }catch(e){}
        try{ candidates.push(control.$input_area?.find?.("input").val?.()); }catch(e){}
        try{ candidates.push(control.$wrapper?.find?.("input").val?.()); }catch(e){}
        const domValue = candidates.find(v=>String(v||"").trim());
        return domValue || "";
    }

    value(name){
        if(name==="rejected_qty_destination"){
            return this.controlValue(name) || this.rejectedQtyDestination || "";
        }
        if(name==="rejected_destination_warehouse"){
            let value = this.controlValue(name) || this.rejectedDestinationWarehouse || "";
            const destination = this.controlValue("rejected_qty_destination") || this.rejectedQtyDestination || "";
            if(!value && destination==="Move to Expired Disposal Warehouse"){
                value = this.bootstrap?.special_warehouses?.disposal || "";
            }else if(!value && destination==="Return to Saleable Warehouse"){
                value = this.controlValue("recall_source_warehouse") || this.bootstrap?.default_warehouse || "";
            }
            return value;
        }
        return this.controlValue(name);
    }
    async setValue(name,value){if(this.controls[name]) await this.controls[name].set_value(value||"");}
    money(value){return format_currency(flt(value), this.currency);}
    esc(value){return frappe.utils.escape_html(String(value??""));}
    showControl(name, show){if(this.controls[name]?.$host)this.controls[name].$host.toggle(Boolean(show));}

    refundMethodSelected(){
        return ["Cash / Bank Refund","Mixed Settlement"].includes(this.value("settlement_method"));
    }

    recallTotals(){
        const delivered=this.rows.reduce((total,row)=>total+flt(row.delivered_qty),0);
        const accepted=this.rows.reduce((total,row)=>total+flt(row.accepted_qty),0);
        const rejected=this.rows.reduce((total,row)=>total+flt(row.rejected_qty),0);
        return {delivered,accepted,rejected,pending:Math.max(0,delivered-accepted-rejected)};
    }

    isProgressiveReturnType(type=this.value("return_type")){
        return ["Regulatory Batch Recall","Expired Drugs Return"].includes(type);
    }

    getProgressiveLabel(){
        return this.value("return_type")==="Expired Drugs Return" ? __("expired return") : __("recall");
    }

    isRejectedDestructionDestination(destination=this.value("rejected_qty_destination")){
        return destination==="Destruction / Documented Destruction";
    }

    rejectedDestinationNeedsWarehouse(destination=this.value("rejected_qty_destination")){
        return ["Return to Saleable Warehouse","Move to Expired Disposal Warehouse"].includes(destination);
    }

    rejectedDestinationControls(){
        const destination=this.value("rejected_qty_destination");
        const controls=["rejected_qty_destination"];
        if(this.rejectedDestinationNeedsWarehouse(destination)) controls.push("rejected_destination_warehouse");
        if(this.isRejectedDestructionDestination(destination)){
            controls.push("rejected_destruction_date","rejected_destruction_reference","rejected_destruction_attachment","rejected_destruction_notes");
        }
        return controls;
    }

    async applyRejectedDestinationDefault(){
        const destination=this.value("rejected_qty_destination");
        if(destination==="Return to Saleable Warehouse"){
            if(!this.value("rejected_destination_warehouse")){
                await this.setValue("rejected_destination_warehouse", this.value("recall_source_warehouse") || this.bootstrap?.default_warehouse || "");
            }
        }else if(destination==="Move to Expired Disposal Warehouse"){
            if(!this.value("rejected_destination_warehouse")){
                await this.setValue("rejected_destination_warehouse", this.bootstrap?.special_warehouses?.disposal || "");
            }
        }else if(destination==="Destruction / Documented Destruction"){
            await this.setValue("rejected_destination_warehouse", "");
            if(!this.value("rejected_destruction_date")) await this.setValue("rejected_destruction_date", frappe.datetime.get_today());
        }
    }

    rejectedDestinationSummary(){
        const destination=this.value("rejected_qty_destination")||__("not selected");
        if(this.rejectedDestinationNeedsWarehouse()) return `${destination} → ${this.value("rejected_destination_warehouse")||__("warehouse not selected")}`;
        if(this.isRejectedDestructionDestination()) return `${destination} • ${this.value("rejected_destruction_date")||__("date not selected")}`;
        return destination;
    }

    rejectedDestinationBlockedReason(totalRejected=null, totalPending=null, rejectedDestinationIncomplete=null){
        const rejected = totalRejected===null ? this.rows.reduce((total,row)=>total+flt(row.rejected_qty),0) : flt(totalRejected);
        const pending = totalPending===null ? this.rows.reduce((total,row)=>total+Math.max(0,flt(row.delivered_qty)-flt(row.accepted_qty)-flt(row.rejected_qty)),0) : flt(totalPending);
        const incomplete = rejectedDestinationIncomplete===null
            ? (rejected>0 && (
                !this.value("rejected_qty_destination")
                || (this.rejectedDestinationNeedsWarehouse() && !this.value("rejected_destination_warehouse"))
                || (this.isRejectedDestructionDestination() && !this.value("rejected_destruction_notes"))
            ))
            : Boolean(rejectedDestinationIncomplete);
        if(this.handoverDocstatus!==1) return __("Submit the Supplier Handover Stock Entry first.");
        if(rejected<=0) return __("There is no rejected quantity to process.");
        if(pending>0.000001) return __("Complete Accepted and Rejected quantities first. Pending quantity: {0}.",[pending]);
        if(incomplete){
            if(!this.value("rejected_qty_destination")) return __("Select the Rejected Qty Destination first.");
            if(this.rejectedDestinationNeedsWarehouse()&&!this.value("rejected_destination_warehouse")) return __("Select the Rejected Destination Warehouse first.");
            if(this.isRejectedDestructionDestination()&&!this.value("rejected_destruction_notes")) return __("Enter destruction notes/details first.");
            return __("Complete the rejected quantity destination details first.");
        }
        if(this.rejectionReturnDocstatus===1) return __("The rejected quantity destination document is already submitted.");
        return "";
    }

    getRecallWorkflowStage(){
        if(!this.isProgressiveReturnType())return null;
        if(this.quarantineDocstatus===0)return "quarantine_draft";
        if(this.quarantineDocstatus!==1)return "selection";
        if(this.handoverDocstatus===0)return "handover_draft";
        if(this.handoverDocstatus!==1)return "handover";

        const totals=this.recallTotals();
        if(totals.delivered<=0.000001||totals.pending>0.000001)return "response";
        if(totals.rejected>0.000001&&this.rejectionReturnDocstatus!==1)return "rejection";
        if(totals.accepted<=0.000001)return "complete_no_credit";
        if(this.approvedDebitNoteDocstatus===0)return "debit_note_draft";
        if(this.approvedDebitNoteDocstatus===1){
            if(this.remainingSettlementAmount<=0.01&&["Settled","Settled Through Supplier Claim"].includes(this.settlementStatus))return "complete";
            return "settlement";
        }
        return "pricing";
    }

    recallStageNumber(stage){
        if(["selection","quarantine_draft"].includes(stage))return 1;
        if(["handover","handover_draft"].includes(stage))return 2;
        if(["response","rejection"].includes(stage))return 3;
        if(["pricing","debit_note_draft"].includes(stage))return 4;
        return 5;
    }

    setControlReadOnly(name,readOnly){
        const control=this.controls[name];
        if(!control)return;
        control.df.read_only=readOnly?1:0;
        if(control.refresh)control.refresh();
    }

    renderRecallWorkflow(stage){
        const labels=[
            [__("1. Quarantine"),__("Select stock and isolate it")],
            [__("2. Supplier Handover"),__("Transfer isolated stock")],
            [__("3. Supplier Decision"),__("Accepted or rejected quantities")],
            [__("4. Approved Value"),__("Price, discount and VAT")],
            [__("5. Financial Settlement"),__("Supplier credit, claim or refund")],
        ];
        const active=this.recallStageNumber(stage);
        this.$main.find('[data-role="workflow-steps"]').html(labels.map((row,index)=>{
            const number=index+1;
            const cls=number<active?"done":number===active?"active":"";
            return `<div class="prm-workflow-step ${cls}"><strong>${row[0]}</strong><span class="prm-muted">${row[1]}</span></div>`;
        }).join(""));
        const nextMessages={
            selection:__("Current step: select the item, batch and quantity, then create the Quarantine Transfer Draft or Create & Submit it directly."),
            quarantine_draft:__("Current step: open the Quarantine Transfer for review or submit it directly from this page."),
            handover:__("Next step: enter the handover details, then create a draft or Create & Submit the Supplier Handover transfer."),
            handover_draft:__("Current step: open the Supplier Handover for review or submit it directly from this page."),
            response:__("Next step: record the supplier accepted and rejected quantities."),
            rejection:__("Next step: select the rejected quantity destination, then Create & Submit the rejected-stock movement before financial approval."),
            pricing:__("Next step: enter either the approved Discount % or approved Net Unit Value, then create a draft or Create & Submit the Approved Debit Note."),
            debit_note_draft:__("Current step: open the Approved Debit Note for review or submit it directly from this page."),
            settlement:__("Final step: choose the financial settlement method and complete the supplier account settlement."),
            complete_no_credit:__("The supplier rejected all quantities. The stock workflow is complete and there is no financial credit."),
            complete:__("This return case is financially settled."),
        };
        this.$main.find('[data-role="next-step"]').text(nextMessages[stage]||"");
    }

    refreshProgressiveUI(){
        const type=this.value("return_type");
        const recallMode=this.isProgressiveReturnType(type);
        const expiredMode=type==="Expired Drugs Return";
        this.$main.find('[data-role="recall-workflow"]').toggle(recallMode);
        if(!recallMode){
            const progressiveActions=[
                "load-batch","attach-notice","open-quarantine","submit-quarantine","create-handover","submit-handover","open-handover","attach-handover",
                "attach-response","save-response","create-rejection-return","submit-rejection-return","open-rejection-return",
                "create-approved-debit-note","submit-approved-debit-note","open-approved-debit-note","create-claim-deduction","open-supplier-claim",
                "create-refund-payment","submit-refund-payment","open-refund-payment","cancel-quarantine","cancel-handover","cancel-rejection-return","cancel-approved-debit-note","remove-claim-deduction","cancel-refund-payment"
            ];
            progressiveActions.forEach(action=>this.$main.find(`[data-action="${action}"]`).hide().prop("disabled",true));
            ["return_type","company","posting_date","supplier"].forEach(name=>this.setControlReadOnly(name,false));
            ["total-qty-card","requested-net-card","requested-vat-card","requested-total-card","total-lines-card","approved-value-card","settlement-status-card","claim-deduction-card","refund-amount-card","refund-status-card","remaining-settlement-card"].forEach(role=>this.$main.find(`[data-role="${role}"]`).show());
            this.$main.find('[data-role="context-note"]').text(__("Add one or more Purchase Invoices from the same supplier under the same Supplier Credit Note. Each official Purchase Return is created against its own original invoice."));
            return;
        }

        const stage=this.getRecallWorkflowStage();
        this.renderRecallWorkflow(stage);

        const stageControls=[
            "recall_source_warehouse","recall_item_code","recall_batch_no","recall_quarantine_warehouse",
            "authority_notification_no","authority_notification_date","authority_notification_attachment",
            "returns_with_supplier_warehouse","handover_date","handover_reference","handover_attachment",
            "supplier_response_date","supplier_response_reference","supplier_response_attachment","supplier_response_notes",
            "rejected_qty_destination","rejected_destination_warehouse","rejected_destruction_date",
            "rejected_destruction_reference","rejected_destruction_attachment","rejected_destruction_notes",
            "approved_debit_note_posting_date","supplier_claim","settlement_method",
            "refund_posting_date","refund_mode_of_payment","refund_account","refund_request_amount",
            "refund_reference_no","refund_reference_date","refund_notes"
        ];
        stageControls.forEach(name=>this.showControl(name,false));
        ["return_type","company","posting_date","supplier","remarks","case_reference"].forEach(name=>this.showControl(name,true));
        this.showControl("case_reference",Boolean(this.caseName));

        const actions=[
            "load-batch","attach-notice","open-quarantine","submit-quarantine","create-handover","submit-handover","open-handover","attach-handover",
            "attach-response","save-response","create-rejection-return","submit-rejection-return","open-rejection-return",
            "create-approved-debit-note","submit-approved-debit-note","open-approved-debit-note","create-claim-deduction","open-supplier-claim",
            "create-refund-payment","submit-refund-payment","open-refund-payment","cancel-quarantine","cancel-handover","cancel-rejection-return","cancel-approved-debit-note","remove-claim-deduction","cancel-refund-payment"
        ];
        actions.forEach(action=>this.$main.find(`[data-action="${action}"]`).hide());
        this.$main.find('[data-action="create-primary"]').hide();

        const permanentlyReadOnly=new Set(["case_reference"]);
        const showControls=(names,readOnly=false)=>names.forEach(name=>{
            this.showControl(name,true);
            this.setControlReadOnly(name,readOnly||permanentlyReadOnly.has(name));
        });
        const showActions=(names)=>names.forEach(action=>this.$main.find(`[data-action="${action}"]`).show());

        const selectionControls=expiredMode
            ? ["recall_source_warehouse","recall_item_code","recall_batch_no","recall_quarantine_warehouse"]
            : ["recall_source_warehouse","recall_item_code","recall_batch_no","recall_quarantine_warehouse","authority_notification_no","authority_notification_date","authority_notification_attachment"];
        const handoverControls=["returns_with_supplier_warehouse","handover_date","handover_reference","handover_attachment"];
        const responseControls=["supplier_response_date","supplier_response_reference","supplier_response_attachment","supplier_response_notes"];
        ["return_type","company","posting_date","supplier"].forEach(name=>this.setControlReadOnly(name,stage!=="selection"));

        if(stage==="selection"){
            showControls(selectionControls,false);
            showActions(expiredMode?["load-batch"]:["load-batch","attach-notice"]);
            this.$main.find('[data-action="create-primary"]').show().text(__("Create & Submit Quarantine Transfer"));
        }else if(stage==="quarantine_draft"){
            showControls(selectionControls,true);
            showActions(["open-quarantine","submit-quarantine"]);
        }else if(stage==="handover"){
            showControls(handoverControls,false);
            showActions(["open-quarantine","attach-handover","submit-handover"]);
        }else if(stage==="handover_draft"){
            showControls(handoverControls,true);
            showActions(["open-quarantine","open-handover","submit-handover"]);
        }else if(stage==="response"){
            showControls(responseControls,false);
            showActions(["open-handover","attach-response","save-response"]);
        }else if(stage==="rejection"){
            showControls(responseControls,true);
            showControls(this.rejectedDestinationControls(), this.rejectionReturnDocstatus===1);
            showActions(["open-handover","submit-rejection-return"]);
            if(this.rejectionReturnStockEntry)showActions(["open-rejection-return"]);
        }else if(stage==="pricing"){
            showControls(["approved_debit_note_posting_date"],false);
            if(this.rejectionReturnStockEntry)showActions(["open-rejection-return"]);
            showActions(["submit-approved-debit-note"]);
        }else if(stage==="debit_note_draft"){
            showControls(["approved_debit_note_posting_date"],true);
            showActions(["open-approved-debit-note","submit-approved-debit-note"]);
        }else if(stage==="settlement"){
            showControls(["settlement_method"],false);
            showActions(["open-approved-debit-note"]);
            const method=this.value("settlement_method");
            if(["Deduct from Supplier Claim","Mixed Settlement"].includes(method)||this.supplierClaim){
                showControls(["supplier_claim"],false);
                showActions(["create-claim-deduction"]);
                if(this.supplierClaim)showActions(["open-supplier-claim","reverse-claim-deduction"]);
            }
            if(["Cash / Bank Refund","Mixed Settlement"].includes(method)||this.refundPaymentEntry){
                showControls(["refund_posting_date","refund_mode_of_payment","refund_account","refund_request_amount","refund_reference_no","refund_reference_date","refund_notes"],false);
                if(!this.refundPaymentEntry||this.remainingSettlementAmount>0.01)showActions(["submit-refund-payment"]);
                if(this.refundPaymentEntry)showActions(["open-refund-payment","submit-refund-payment"]);
            }
        }else{
            if(this.approvedDebitNote)showActions(["open-approved-debit-note"]);
            if(this.supplierClaim)showActions(["open-supplier-claim"]);
            if(this.refundPaymentEntry)showActions(["open-refund-payment"]);
            if(this.rejectionReturnStockEntry)showActions(["open-rejection-return"]);
        }

        // Reversal actions remain available whenever their linked document exists.
        if(this.quarantineStockEntry && this.quarantineDocstatus!==2)showActions(["cancel-quarantine"]);
        if(this.handoverStockEntry && this.handoverDocstatus!==2)showActions(["cancel-handover"]);
        if(this.rejectionReturnStockEntry && this.rejectionReturnDocstatus!==2)showActions(["cancel-rejection-return"]);
        if(this.approvedDebitNote && this.approvedDebitNoteDocstatus!==2)showActions(["cancel-approved-debit-note"]);
        if(this.supplierClaim && this.supplierClaimDocstatus===0)showActions(["remove-claim-deduction"]);
        if(this.supplierClaim && this.supplierClaimDocstatus!==0)showActions(["reverse-claim-deduction"]);
        if(this.refundPaymentEntry && this.refundPaymentEntryDocstatus!==2)showActions(["cancel-refund-payment"]);

        const cardRoles=[
            "total-qty-card","stock-value-card","requested-net-card","requested-vat-card","requested-total-card","difference-card","total-lines-card",
            "handover-qty-card","accepted-qty-card","rejected-qty-card","pending-response-card","approved-value-card",
            "debit-note-amount-card","debit-note-outstanding-card","debit-note-status-card","settlement-status-card","claim-utilization-card","claim-settlement-date-card","planned-claim-card",
            "claim-deduction-card","refund-amount-card","refund-status-card","remaining-settlement-card"
        ];
        cardRoles.forEach(role=>this.$main.find(`[data-role="${role}"]`).hide());
        const showCards=(roles)=>roles.forEach(role=>this.$main.find(`[data-role="${role}"]`).show());
        if(["selection","quarantine_draft"].includes(stage))showCards(["total-qty-card","stock-value-card","total-lines-card"]);
        else if(["handover","handover_draft"].includes(stage))showCards(["total-qty-card","handover-qty-card","stock-value-card","total-lines-card"]);
        else if(["response","rejection","complete_no_credit"].includes(stage))showCards(["handover-qty-card","accepted-qty-card","rejected-qty-card","pending-response-card","total-lines-card"]);
        else if(["pricing","debit_note_draft"].includes(stage))showCards(["accepted-qty-card","approved-value-card","debit-note-amount-card","debit-note-status-card","total-lines-card"]);
        else showCards(["approved-value-card","debit-note-amount-card","debit-note-outstanding-card","debit-note-status-card","settlement-status-card","claim-utilization-card","claim-settlement-date-card","planned-claim-card","claim-deduction-card","refund-amount-card","refund-status-card","remaining-settlement-card"]);

        const contextMessages={
            selection:__("Only the quarantine fields are shown. Later stages remain hidden until the Quarantine Transfer is submitted."),
            quarantine_draft:__("Submit the Quarantine Transfer first. Supplier handover and financial fields remain locked and hidden."),
            handover:__("Only supplier handover fields are shown. Supplier response fields will appear after the handover transfer is submitted."),
            handover_draft:__("Submit the Supplier Handover transfer. Supplier decision fields will appear afterwards."),
            response:__("Enter the supplier response only: accepted quantity, rejected quantity and rejection reason. Accepted + Rejected must equal Handed Over."),
            rejection:__("The supplier response is recorded. Select the rejected quantity destination: saleable warehouse, expired disposal warehouse, or documented destruction."),
            pricing:__("Enter either Approved Discount % or Approved Net Unit Value. The other value is calculated automatically. VAT is included only for VAT-taxable items."),
            debit_note_draft:__("Submit the Approved Debit Note. Financial settlement options will appear only after submission."),
            settlement:__("Choose how the approved supplier credit will be settled. Cash / Bank Refund remains available as an exceptional option."),
            complete_no_credit:__("All handed-over quantity was rejected; no supplier credit is due."),
            complete:__("All operational and financial stages are complete."),
        };
        this.$main.find('[data-role="context-note"]').text(contextMessages[stage]||"");
    }

    refreshSettlementUI(){
        const returnType=this.value("return_type");
        const invoiceMode=returnType==="Return Against Invoice";
        const recallMode=this.isProgressiveReturnType(returnType);
        const stage=recallMode?this.getRecallWorkflowStage():null;
        const supported=invoiceMode||(recallMode&&["settlement","complete"].includes(stage));
        const refundSelected=supported&&this.refundMethodSelected();
        const showRefundFields=supported&&(refundSelected||Boolean(this.refundPaymentEntry));
        ["refund_posting_date","refund_mode_of_payment","refund_account","refund_request_amount","refund_reference_no","refund_reference_date","refund_notes"].forEach(name=>this.showControl(name,showRefundFields));
        this.$main.find('[data-action="open-refund-payment"]').toggle(supported&&Boolean(this.refundPaymentEntry));
    }

    roundNumber(value,precision=6){
        const factor=10**precision;
        return Math.round((flt(value)+Number.EPSILON)*factor)/factor;
    }

    inputNumber(value,precision=6){
        return String(this.roundNumber(value,precision));
    }

    clampDiscount(value){return this.roundNumber(Math.min(100,Math.max(0,flt(value))),6);}

    pricingPair(baseValue,discountValue,netValue,mode){
        let base=this.roundNumber(Math.max(0,flt(baseValue)),6);
        let discount=this.clampDiscount(discountValue);
        let net=this.roundNumber(Math.max(0,flt(netValue)),6);
        const inputMode=["Discount Percentage","Net Unit Value"].includes(mode)?mode:"Discount Percentage";
        if(base<=0&&net>0)base=net;
        if(inputMode==="Net Unit Value"){
            if(base>0){
                net=this.roundNumber(Math.min(net,base),6);
                discount=this.clampDiscount(((base-net)/base)*100);
            }else discount=0;
        }else net=this.roundNumber(base*(1-discount/100),6);
        return {base,discount,net,mode:inputMode};
    }

    pricingPairVatAware(baseValue,discountValue,netValue,mode,vatRate,isVatTaxable){
        let base=this.roundNumber(Math.max(0,flt(baseValue)),6);
        let discount=this.clampDiscount(discountValue);
        let net=this.roundNumber(Math.max(0,flt(netValue)),6);
        const inputMode=["Discount Percentage","Net Unit Value"].includes(mode)?mode:"Discount Percentage";
        const vat=this.roundNumber(Math.max(0,flt(vatRate)),6);
        const vatFactor=cint(isVatTaxable)&&vat>0?this.roundNumber(1+(vat/100),6):1;
        if(base<=0&&net>0)base=this.roundNumber(net*vatFactor,6);
        if(inputMode==="Net Unit Value"){
            if(base>0){
                const maxNet=this.roundNumber(base/vatFactor,6);
                net=this.roundNumber(Math.min(net,maxNet),6);
                const grossEquivalent=this.roundNumber(net*vatFactor,6);
                discount=this.clampDiscount(((base-grossEquivalent)/base)*100);
            }else discount=0;
        }else{
            const grossAfterDiscount=this.roundNumber(base*(1-discount/100),6);
            net=this.roundNumber(grossAfterDiscount/vatFactor,6);
        }
        return {base,discount,net,mode:inputMode};
    }

    recalculateRow(row){
        const requested=this.pricingPair(row.base_rate,row.discount_percentage,row.rate,row.pricing_input_mode);
        row.base_rate=requested.base;
        row.discount_percentage=requested.discount;
        row.rate=requested.net;
        row.pricing_input_mode=requested.mode;
        row.is_vat_taxable=cint(row.is_vat_taxable)?1:0;
        row.vat_rate=row.is_vat_taxable?Math.max(0,flt(row.vat_rate)):0;
        row.net_return_amount=flt(row.return_qty)*row.rate;
        row.tax_amount=row.net_return_amount*row.vat_rate/100;
        row.return_amount=row.net_return_amount+row.tax_amount;

        const approvedEntered=flt(row.accepted_qty)>0||flt(row.approved_rate)>0||flt(row.approved_discount_percentage)>0;
        if(approvedEntered){
            const approved=this.pricingPairVatAware(row.base_rate,row.approved_discount_percentage,row.approved_rate,row.approved_pricing_input_mode,row.vat_rate,row.is_vat_taxable);
            row.approved_discount_percentage=approved.discount;
            row.approved_rate=approved.net;
            row.approved_pricing_input_mode=approved.mode;
        }else{
            row.approved_discount_percentage=0;
            row.approved_rate=0;
            row.approved_pricing_input_mode="Discount Percentage";
        }
        row.approved_net_amount=flt(row.accepted_qty)*flt(row.approved_rate);
        row.approved_tax_amount=row.approved_net_amount*row.vat_rate/100;
        row.approved_total_credit=row.approved_net_amount+row.approved_tax_amount;
        row.accepted_amount=row.approved_total_credit;
        return row;
    }

    vatLabel(row){
        const rate=flt(row.vat_rate);
        if(!cint(row.is_vat_taxable) || rate < 0.01){
            return `<span class="prm-vat-no">${__("Exempt / No VAT")}</span>`;
        }
        const clean=this.roundNumber(rate,2);
        return `<span class="prm-vat-yes">${this.esc(`${clean}%`)}</span>`;
    }

    clearRecallRows(){
        if(!this.isProgressiveReturnType()) return;
        this.rows=[];
        this.$main.find('[data-role="invoice-summary"]').text("");
        this.renderItems();
    }

    runPageAction(e, actionName, fn){
        if(e){
            e.preventDefault();
            e.stopPropagation();
        }
        const $button = e ? $(e.currentTarget) : $();
        const notReadyReason = $button.length ? ($button.attr("data-not-ready-reason") || "") : "";
        if($button.length && $button.attr("data-not-ready")==="1"){
            frappe.show_alert({message:notReadyReason || __("This action is not ready yet. Complete the required fields first."), indicator:"orange"}, 6);
            return;
        }
        if($button.length && $button.prop("disabled")){
            frappe.show_alert({message:notReadyReason || __("This action is not ready yet. Complete the required fields first."), indicator:"orange"}, 6);
            return;
        }
        if(this._runningAction){
            frappe.show_alert({message:__("Please wait until the current action finishes."), indicator:"orange"}, 5);
            return;
        }
        this._runningAction = actionName || "action";
        if($button.length) $button.prop("disabled", true).attr("aria-busy","true");
        Promise.resolve()
            .then(fn)
            .catch(error => {
                console.error(`[Purchase Returns Management] ${actionName || "Action"} failed`, error);
                let message = error?.message || error?.exc || error || __("Unknown error");
                if(error?._server_messages){
                    try{
                        message = JSON.parse(error._server_messages).map(row => JSON.parse(row).message).join("<br>");
                    }catch(parseError){
                        message = error._server_messages;
                    }
                }
                frappe.msgprint({
                    title:__("Action Failed"),
                    message: message,
                    indicator:"red"
                });
            })
            .finally(() => {
                this._runningAction = null;
                if($button.length) $button.prop("disabled", false).removeAttr("aria-busy");
                this.syncButtons();
            });
    }

    bindEvents() {
        this.$main.on("click", "[data-action='purchase-page']", ()=>frappe.set_route("purchase-invoice-management"));
        this.$main.on("click", "[data-action='new-case']", ()=>this.newCase());
        this.$main.on("click", "[data-action='load-invoice']", ()=>this.loadInvoice(false));
        this.$main.on("click", "[data-action='load-invoice-all']", ()=>this.loadInvoice(true));
        this.$main.on("click", "[data-action='pick-invoice-items']", ()=>this.openInvoiceItemPicker());
        this.$main.on("click", "[data-action='load-batch']", ()=>this.loadBatchStock());
        this.$main.on("click", "[data-action='attach-notice']", ()=>this.attachAuthorityNotice());
        this.$main.on("click", "[data-action='attach-handover']", ()=>this.attachHandoverReceipt());
        this.$main.on("click", "[data-action='attach-response']", ()=>this.attachSupplierResponse());
        this.$main.on("click", "[data-action='save-response']", ()=>this.saveSupplierResponse());
        this.$main.on("click", "[data-action='create-handover']", ()=>this.createSupplierHandoverDraft());
        this.$main.on("click", "[data-action='submit-quarantine']", ()=>this.createAndSubmitQuarantineTransfer());
        this.$main.on("click", "[data-action='submit-handover']", ()=>this.createAndSubmitSupplierHandover());
        this.$main.on("click", "[data-action='create-rejection-return']", e=>this.runPageAction(e, "create-rejection-return", ()=>this.createRejectedQuantityReturnDraft()));
        this.$main.on("click", "[data-action='submit-rejection-return']", e=>this.runPageAction(e, "submit-rejection-return", ()=>this.createAndSubmitRejectedQuantityReturn()));
        this.$main.on("click", "[data-action='create-approved-debit-note']", ()=>this.createApprovedDebitNoteDraft());
        this.$main.on("click", "[data-action='submit-approved-debit-note']", ()=>this.createAndSubmitApprovedDebitNote());
        this.$main.on("click", "[data-action='create-claim-deduction']", ()=>this.createOrLinkSupplierClaimDeduction());
        this.$main.on("click", "[data-action='create-refund-payment']", ()=>this.createSupplierRefundPaymentDraft());
        this.$main.on("click", "[data-action='submit-refund-payment']", ()=>this.createAndSubmitSupplierRefundPayment());
        this.$main.on("click", "[data-action='save-case']", ()=>this.saveCase());
        this.$main.on("click", "[data-action='create-primary']", ()=>this.createPrimaryDraft());
        this.$main.on("click", "[data-action='open-original']", ()=>{const n=this.value("original_purchase_invoice");if(n)frappe.set_route("Form","Purchase Invoice",n);});
        this.$main.on("click", "[data-action='open-return']", ()=>{if(this.purchaseReturn)frappe.set_route("Form","Purchase Invoice",this.purchaseReturn);});
        this.$main.on("click", "[data-action='delete-return-draft']", ()=>this.deletePurchaseReturnDraft());
        this.$main.on("click", "[data-action='open-quarantine']", ()=>{if(this.quarantineStockEntry)frappe.set_route("Form","Stock Entry",this.quarantineStockEntry);});
        this.$main.on("click", "[data-action='open-handover']", ()=>{if(this.handoverStockEntry)frappe.set_route("Form","Stock Entry",this.handoverStockEntry);});
        this.$main.on("click", "[data-action='open-rejection-return']", ()=>{if(this.rejectionReturnStockEntry)frappe.set_route("Form","Stock Entry",this.rejectionReturnStockEntry);});
        this.$main.on("click", "[data-action='open-approved-debit-note']", ()=>{if(this.approvedDebitNote)frappe.set_route("Form","Purchase Invoice",this.approvedDebitNote);});
        this.$main.on("click", "[data-action='open-supplier-claim']", ()=>{if(this.supplierClaim)frappe.set_route("Form","Supplier Claim",this.supplierClaim);});
        this.$main.on("click", "[data-action='open-refund-payment']", ()=>{if(this.refundPaymentEntry)frappe.set_route("Form","Payment Entry",this.refundPaymentEntry);});
        this.$main.on("click", "[data-action='cancel-quarantine']", e=>this.runPageAction(e, "cancel-quarantine", ()=>this.cancelQuarantineTransfer()));
        this.$main.on("click", "[data-action='cancel-handover']", e=>this.runPageAction(e, "cancel-handover", ()=>this.cancelSupplierHandover()));
        this.$main.on("click", "[data-action='cancel-rejection-return']", e=>this.runPageAction(e, "cancel-rejection-return", ()=>this.cancelRejectedQuantityDestination()));
        this.$main.on("click", "[data-action='cancel-approved-debit-note']", e=>this.runPageAction(e, "cancel-approved-debit-note", ()=>this.cancelApprovedDebitNote()));
        this.$main.on("click", "[data-action='remove-claim-deduction']", e=>this.runPageAction(e, "remove-claim-deduction", ()=>this.removeDraftClaimDeduction()));
        this.$main.on("click", "[data-action='reverse-claim-deduction']", e=>this.runPageAction(e, "reverse-claim-deduction", ()=>this.reverseSupplierClaimDeduction()));
        this.$main.on("click", "[data-action='cancel-refund-payment']", e=>this.runPageAction(e, "cancel-refund-payment", ()=>this.cancelSupplierRefundPayment()));
        this.$main.on("click", ".prm-type:not(.disabled)", e=>this.setReturnType($(e.currentTarget).data("type")));
        this.$main.on("change", "[data-row-field]", e=>this.updateRow(e));
        this.$main.on("click", "[data-action='remove-recall-row']", e=>this.removeRecallRow(Number($(e.currentTarget).data("index"))));
        this.$main.on("click", "[data-action='open-case-page']", e=>this.loadCase($(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-case-document']", e=>frappe.set_route("Form","Pharmacy Return Case",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-original']", e=>frappe.set_route("Form","Purchase Invoice",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-original-row']", e=>{const name=$(e.currentTarget).data("name"); if(name) frappe.set_route("Form","Purchase Invoice",name);});
        this.$main.on("click", "[data-action='open-recent-return']", e=>frappe.set_route("Form","Purchase Invoice",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-quarantine']", e=>frappe.set_route("Form","Stock Entry",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-handover']", e=>frappe.set_route("Form","Stock Entry",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-rejection']", e=>frappe.set_route("Form","Stock Entry",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-debit-note']", e=>frappe.set_route("Form","Purchase Invoice",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-claim']", e=>frappe.set_route("Form","Supplier Claim",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='open-recent-refund']", e=>frappe.set_route("Form","Payment Entry",$(e.currentTarget).data("name")));
        this.$main.on("click", "[data-action='toggle-recent-list']", ()=>this.toggleRecentList());
        this.$main.on("input", "[data-role='recent-search']", e=>{this.recentSearch=$(e.currentTarget).val()||"";if(this.recentSearch)this.setRecentExpanded(true);this.renderRecent();});
        this.$main.on("change", "[data-role='recent-filter']", e=>{this.recentFilter=$(e.currentTarget).val()||"open";this.setRecentExpanded(true);this.renderRecent();});
        this.$main.on("change", "[data-role='recent-from-date']", e=>{const parsed=this.parseDisplayDate($(e.currentTarget).val()||"");this.recentFromDate=parsed||"";this.setRecentDateControlValue("recent-from-date",this.recentFromDate);this.setRecentExpanded(true);this.refreshRecent();});
        this.$main.on("change", "[data-role='recent-to-date']", e=>{const parsed=this.parseDisplayDate($(e.currentTarget).val()||"");this.recentToDate=parsed||"";this.setRecentDateControlValue("recent-to-date",this.recentToDate);this.setRecentExpanded(true);this.refreshRecent();});
        this.$main.on("click", "[data-action='refresh-recent-list']", ()=>{this.recentFromDate=this.parseDisplayDate(this.$main.find('[data-role="recent-from-date"]').val()||"");this.recentToDate=this.parseDisplayDate(this.$main.find('[data-role="recent-to-date"]').val()||"");this.setRecentDateControlValue("recent-from-date",this.recentFromDate);this.setRecentDateControlValue("recent-to-date",this.recentToDate);this.setRecentExpanded(true);this.refreshRecent();});
        this.$main.on("click", "[data-action='open-date-range-dialog']", ()=>this.openRecentDateRangeDialog());
        this.$main.on("click", "[data-action='clear-recent-filters']", ()=>{this.recentSearch="";this.recentFilter="open";this.recentFromDate="";this.recentToDate="";this.$main.find('[data-role="recent-search"]').val("");this.$main.find('[data-role="recent-filter"]').val("open");this.setRecentDateControlValue("recent-from-date","");this.setRecentDateControlValue("recent-to-date","");this.setRecentExpanded(true);this.refreshRecent();});
        this.$main.on("click", "[data-action='toggle-print-menu']", e=>{e.preventDefault();e.stopPropagation();const $d=$(e.currentTarget).closest('.prm-print-dropdown');this.$main.find('.prm-print-dropdown').not($d).removeClass('open');$d.toggleClass('open');});
        this.$main.on("click", "[data-action='print-doc']", e=>{e.preventDefault();e.stopPropagation();this.$main.find('.prm-print-dropdown').removeClass('open');this.printDocument($(e.currentTarget).data("doctype"),$(e.currentTarget).data("name"));});
        this.$main.on("click", "[data-action='print-current-case']", ()=>{if(this.caseName)this.printDocument("Pharmacy Return Case",this.caseName);});
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
            const quarantineDefault=this.value("return_type")==="Expired Drugs Return" ? this.bootstrap.special_warehouses.expired : this.bootstrap.special_warehouses.recall;
            if(!this.value("recall_quarantine_warehouse") && quarantineDefault) await this.setValue("recall_quarantine_warehouse",quarantineDefault);
            if(!this.value("returns_with_supplier_warehouse")) await this.setValue("returns_with_supplier_warehouse",this.bootstrap.special_warehouses.supplier);
            await this.applyRejectedDestinationDefault();
            return;
        }
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_bootstrap",args:{company}});
        const data=r.message||{};
        if(!this.value("recall_source_warehouse") && data.default_warehouse) await this.setValue("recall_source_warehouse",data.default_warehouse);
        const quarantineDefault=this.value("return_type")==="Expired Drugs Return" ? data.special_warehouses?.expired : data.special_warehouses?.recall;
        if(quarantineDefault) await this.setValue("recall_quarantine_warehouse",quarantineDefault);
        if(data.special_warehouses?.supplier) await this.setValue("returns_with_supplier_warehouse",data.special_warehouses.supplier);
        if(!this.bootstrap) this.bootstrap={};
        if(data.default_warehouse) this.bootstrap.default_warehouse=data.default_warehouse;
        if(data.special_warehouses) this.bootstrap.special_warehouses=data.special_warehouses;
        await this.applyRejectedDestinationDefault();
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
        if(type==="Expired Drugs Return" && this.bootstrap?.special_warehouses?.expired) {
            await this.setValue("recall_quarantine_warehouse", this.bootstrap.special_warehouses.expired);
        } else if(type==="Regulatory Batch Recall" && this.bootstrap?.special_warehouses?.recall) {
            await this.setValue("recall_quarantine_warehouse", this.bootstrap.special_warehouses.recall);
        }
        this.refreshReturnTypeUI(type, notify);
    }

    refreshReturnTypeUI(type, notify=false){
        type=type||"Return Against Invoice";
        this.$main.find(".prm-type").removeClass("active");
        this.$main.find(`.prm-type[data-type="${type}"]`).addClass("active");
        const invoiceMode=type==="Return Against Invoice";
        const recallMode=this.isProgressiveReturnType(type);
        const expiredMode=type==="Expired Drugs Return";
        ["supplier_credit_note_no","supplier_credit_note_date","supplier_credit_note_attachment","original_purchase_invoice","return_item_to_add","return_batch_no_to_add"].forEach(name=>this.showControl(name,invoiceMode));
        ["recall_source_warehouse","recall_item_code","recall_batch_no","recall_quarantine_warehouse","authority_notification_no","authority_notification_date","authority_notification_attachment","returns_with_supplier_warehouse","handover_date","handover_reference","handover_attachment","supplier_response_date","supplier_response_reference","supplier_response_attachment","supplier_response_notes","rejected_qty_destination","rejected_destination_warehouse","rejected_destruction_date","rejected_destruction_reference","rejected_destruction_attachment","rejected_destruction_notes","approved_debit_note_posting_date","supplier_claim"].forEach(name=>this.showControl(name,false));
        this.$main.find("[data-action='load-invoice'],[data-action='pick-invoice-items'],[data-action='load-invoice-all']").toggle(invoiceMode);
        this.$main.find("[data-action='open-original'],[data-action='open-return'],[data-action='delete-return-draft']").toggle(invoiceMode);
        this.$main.find("[data-action='load-batch'],[data-action='attach-notice'],[data-action='open-quarantine'],[data-action='submit-quarantine'],[data-action='submit-handover'],[data-action='open-handover'],[data-action='attach-handover'],[data-action='attach-response'],[data-action='save-response'],[data-action='submit-rejection-return'],[data-action='open-rejection-return'],[data-action='submit-approved-debit-note'],[data-action='open-approved-debit-note'],[data-action='create-claim-deduction'],[data-action='open-supplier-claim']").toggle(recallMode);
        this.$main.find("[data-action='attach-notice']").toggle(recallMode&&!expiredMode);
        this.refreshSettlementUI();
        this.$main.find("[data-action='create-primary']").text(invoiceMode?__("Create & Submit Supplier Credit Note Return"):__("Create & Submit Quarantine Transfer"));
        this.$main.find('[data-role="qty-label"]').text(recallMode?(expiredMode?__("Expired Return Quantity"):__("Recall Quantity")):__("Selected Quantity"));
        this.$main.find('[data-role="value-label"]').text(recallMode?__("Expected Supplier Credit incl. VAT"):__("Requested Total Credit incl. VAT"));
        this.$main.find('[data-role="context-note"]').text(recallMode
            ?(expiredMode
                ?__("Expired Drugs Return is active: select physical batch stock, isolate it, hand it to the supplier, then record accepted/rejected quantities and approved value.")
                :__("Enter either Discount % or Net Unit Value; the other value is calculated automatically. VAT is calculated only when the item is VAT taxable, and the VAT field cannot be added manually."))
            :__("Select a Purchase Invoice, type the item/barcode to return, then add only the matching line. Use Load All only when you really need all invoice rows."));
        this.$main.find('[data-role="stock-value-card"],[data-role="difference-card"],[data-role="handover-qty-card"],[data-role="accepted-qty-card"],[data-role="rejected-qty-card"],[data-role="pending-response-card"],[data-role="debit-note-amount-card"],[data-role="debit-note-outstanding-card"],[data-role="debit-note-status-card"],[data-role="planned-claim-card"]').toggle(recallMode);
        this.$main.find('[data-role="approved-value-card"],[data-role="settlement-status-card"],[data-role="claim-deduction-card"],[data-role="refund-amount-card"],[data-role="refund-status-card"],[data-role="remaining-settlement-card"]').toggle(invoiceMode||recallMode);
        if(notify && type==="Expired Drugs Return") frappe.show_alert({message:__("Expired Drugs Return workflow is active."),indicator:"green"},6);
        this.renderItems();
        this.syncButtons();
        this.refreshProgressiveUI();
    }

    async openInvoiceItemPicker(){
        // v0.7.35: tolerant picker search for Purchase Invoice / Supplier Invoice fragments (00074, p0074, PINV74).
        if(this.purchaseReturnDocstatus===1){
            frappe.msgprint({title:__("Purchase Return Submitted"),message:__("Submitted Purchase Return documents are locked. Create a new Return Case for additional supplier credit note lines."),indicator:"orange"});
            return;
        }
        const name=this.value("original_purchase_invoice");
        if(!name){frappe.msgprint({title:__("Original Invoice Required"),message:__("Select a submitted Purchase Invoice first."),indicator:"orange"});return;}
        const response=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_invoice_for_return",
            args:{name, selected_only:0},
            freeze:true,
            freeze_message:__("Loading invoice items...")
        });
        const invoice=response.message||{};
        const rows=(invoice.items||[]).filter(row=>flt(row.available_to_return_qty)>0);
        if(!rows.length){
            frappe.msgprint({title:__("No Returnable Stock"),message:__("No returnable rows with physical stock are available for this Purchase Invoice."),indicator:"orange"});
            return;
        }
        const html=`
            <div class="prm-picker-search">
                <input type="text" class="form-control input-sm" data-role="picker-search" placeholder="${__("Search item, code, batch, purchase invoice no, or supplier invoice no")}">
            </div>
            <div style="max-height:68vh;overflow:auto">
                <table class="prm-picker-table">
                    <thead><tr>
                        <th style="width:36px">${__("Select")}</th>
                        <th>${__("Purchase Invoice")}</th>
                        <th>${__("Supplier Inv No")}</th>
                        <th>${__("Item")}</th>
                        <th>${__("Batch")}</th>
                        <th>${__("Expiry")}</th>
                        <th>${__("Purchased")}</th>
                        <th>${__("Returned")}</th>
                        <th>${__("Physical")}</th>
                        <th>${__("Returnable")}</th>
                        <th style="width:110px">${__("Return Qty")}</th>
                    </tr></thead>
                    <tbody data-role="picker-rows"></tbody>
                </table>
            </div>`;
        const dialog=new frappe.ui.Dialog({
            title:__("Pick Items From Invoice {0}",[name]),
            fields:[{fieldtype:"HTML", fieldname:"picker_html", options:html}],
            primary_action_label:__("Add Selected Lines"),
            primary_action:async()=>{
                const selected=[];
                dialog.$wrapper.find("tbody [data-row-index]").each((idx, tr)=>{
                    const $tr=$(tr);
                    if(!$tr.find('[data-role="pick-check"]').prop("checked")) return;
                    const source=rows[cint($tr.attr("data-row-index"))];
                    const qty=flt($tr.find('[data-role="pick-qty"]').val());
                    if(qty<=0) return;
                    const max=flt(source.available_to_return_qty);
                    if(qty>max){
                        frappe.msgprint({title:__("Invalid Quantity"),message:__("Return Qty for {0} cannot exceed {1}.",[source.item_code, max]),indicator:"orange"});
                        return false;
                    }
                    selected.push({...source, return_qty:qty});
                });
                if(!selected.length){
                    frappe.msgprint({title:__("No Lines Selected"),message:__("Select at least one invoice row and enter Return Qty."),indicator:"orange"});
                    return;
                }
                const payload={...invoice, items:selected};
                await this.applyInvoice(payload, {itemQuery:"picker"});
                dialog.hide();
            }
        });
        const normalizePickerSearch=(value)=>String(value||"").toLowerCase().replace(/[^a-z0-9\u0600-\u06ff]+/g, "");
        const pickerSearchTokens=(row)=>{
            const invoice=String(row.original_purchase_invoice||name||"");
            const supplierInvoice=String(row.original_supplier_invoice_no||"");
            const invoiceDigits=invoice.replace(/\D/g, "");
            const invoiceTail5=invoiceDigits.slice(-5);
            const invoiceTail4=invoiceDigits.slice(-4);
            const invoiceTailNoZero=invoiceTail5.replace(/^0+/, "")||invoiceTail5;
            const base=[
                invoice, supplierInvoice, row.item_code, row.item_name, row.batch_no, row.description,
                invoiceDigits, invoiceTail5, invoiceTail4, invoiceTailNoZero,
                `p${invoiceTail5}`, `p${invoiceTail4}`, `p${invoiceTailNoZero}`,
                `pinv${invoiceTail5}`, `pinv${invoiceTail4}`, `pinv${invoiceTailNoZero}`,
                `inv${invoiceTail5}`, `inv${invoiceTail4}`, `inv${invoiceTailNoZero}`
            ];
            return base.map(normalizePickerSearch).filter(Boolean).join(" ");
        };
        const renderPickerRows=(filterText="")=>{
            const text=normalizePickerSearch(filterText);
            const $tbody=dialog.$wrapper.find('[data-role="picker-rows"]');
            $tbody.empty();
            rows.forEach((row, idx)=>{
                const haystack=pickerSearchTokens(row);
                if(text && !haystack.includes(text)) return;
                const alreadyLoaded=this.rows.some(current=>current.original_purchase_invoice_item===row.original_purchase_invoice_item);
                const disabled=alreadyLoaded?"disabled":"";
                const muted=alreadyLoaded?`<div class="text-muted">${__("Already loaded")}</div>`:"";
                $tbody.append(`
                    <tr data-row-index="${idx}" class="${alreadyLoaded?"text-muted":""}">
                        <td><input type="checkbox" data-role="pick-check" ${disabled}></td>
                        <td><span class="prm-link" data-invoice-name="${frappe.utils.escape_html(row.original_purchase_invoice||"")}">${frappe.utils.escape_html(row.original_purchase_invoice||name||"—")}</span></td>
                        <td>${frappe.utils.escape_html(row.original_supplier_invoice_no||"—")}</td>
                        <td><b>${frappe.utils.escape_html(row.item_name||row.item_code||"")}</b><br><span class="text-muted">${frappe.utils.escape_html(row.item_code||"")}</span>${muted}</td>
                        <td>${frappe.utils.escape_html(row.batch_no||"—")}</td>
                        <td>${frappe.utils.escape_html(row.expiry_date||"—")}</td>
                        <td>${flt(row.original_qty)}</td>
                        <td>${flt(row.already_returned_qty)}</td>
                        <td>${flt(row.physical_stock_qty)}</td>
                        <td>${flt(row.available_to_return_qty)}</td>
                        <td><input type="number" class="form-control input-sm" data-role="pick-qty" min="0" step="any" max="${flt(row.available_to_return_qty)}" value="0" ${disabled}></td>
                    </tr>`);
            });
            if(!$tbody.children().length){
                $tbody.append(`<tr><td colspan="11" class="text-muted text-center">${__("No matching rows")}</td></tr>`);
            }
        };
        dialog.show();
        dialog.$wrapper.addClass("prm-picker-dialog");
        renderPickerRows();
        dialog.$wrapper.on("input", '[data-role="picker-search"]', frappe.utils.debounce(e=>renderPickerRows($(e.currentTarget).val()),120));
        dialog.$wrapper.on("click", '[data-invoice-name]', e=>{
            const invoiceName=$(e.currentTarget).attr("data-invoice-name");
            if(invoiceName) frappe.set_route("Form", "Purchase Invoice", invoiceName);
        });
        dialog.$wrapper.on("change", '[data-role="pick-check"]', e=>{
            const $tr=$(e.currentTarget).closest("tr");
            const idx=cint($tr.attr("data-row-index"));
            if($(e.currentTarget).prop("checked") && flt($tr.find('[data-role="pick-qty"]').val())<=0){
                $tr.find('[data-role="pick-qty"]').val(flt(rows[idx].available_to_return_qty));
            }
        });
        dialog.$wrapper.on("input", '[data-role="pick-qty"]', e=>{
            const $tr=$(e.currentTarget).closest("tr");
            if(flt($(e.currentTarget).val())>0){
                $tr.find('[data-role="pick-check"]').prop("checked", true);
            }
        });
    }

    async loadInvoice(loadAll=false){
        if(this.purchaseReturnDocstatus===1){
            frappe.msgprint({title:__("Purchase Return Submitted"),message:__("Submitted Purchase Return documents are locked. Create a new Return Case for additional supplier credit note lines."),indicator:"orange"});
            return;
        }
        const name=this.value("original_purchase_invoice");
        if(!name){frappe.msgprint({title:__("Original Invoice Required"),message:__("Select a submitted Purchase Invoice first."),indicator:"orange"});return;}
        const itemQuery=(this.value("return_item_to_add")||"").trim();
        const batchNo=(this.value("return_batch_no_to_add")||"").trim();
        if(!loadAll && !itemQuery){
            frappe.msgprint({title:__("Item Required"),message:__("Type the item code, barcode, or item name to add only the required invoice line. Use Load All Invoice Items only when needed."),indicator:"orange"});
            return;
        }
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_invoice_for_return",
            args:{name,item_query:loadAll?"":itemQuery,batch_no:loadAll?"":batchNo,selected_only:loadAll?0:1},
            freeze:true,
            freeze_message:loadAll?__("Loading all invoice items..."):__("Loading selected invoice item...")
        });
        await this.applyInvoice(r.message||{}, {loadAll, itemQuery, batchNo});
        if(!loadAll && (r.message||{}).items && (r.message||{}).items.length){
            await this.setValue("return_item_to_add","");
            await this.setValue("return_batch_no_to_add","");
        }
    }

    async applyInvoice(invoice, options={}){
        await this.setReturnType("Return Against Invoice",false);
        if(this.rows.length && this.value("supplier") && invoice.supplier && this.value("supplier") !== invoice.supplier){
            frappe.msgprint({title:__("Different Supplier"),message:__("All invoices inside one Supplier Credit Note must belong to the same supplier."),indicator:"red"});
            return;
        }
        if(this.value("company") && invoice.company && this.value("company") !== invoice.company){
            frappe.msgprint({title:__("Different Company"),message:__("All invoices inside one Supplier Credit Note must belong to the same company."),indicator:"red"});
            return;
        }
        await this.setValue("company",invoice.company);
        await this.setValue("supplier",invoice.supplier);
        if(!this.value("original_purchase_invoice")) await this.setValue("original_purchase_invoice",invoice.name);
        else await this.setValue("original_purchase_invoice",invoice.name);
        this.currency=invoice.currency||this.currency;
        let added=0;
        (invoice.items||[]).forEach(row=>{
            const existing=this.rows.some(current=>current.original_purchase_invoice_item===row.original_purchase_invoice_item);
            if(existing) return;
            this.rows.push(this.recalculateRow({
                ...row,
                original_purchase_invoice:row.original_purchase_invoice||invoice.name,
                original_supplier_invoice_no:row.original_supplier_invoice_no||invoice.bill_no||"",
                return_qty:flt(row.return_qty),
                invoice_returnable_qty:flt(row.invoice_returnable_qty),
                physical_stock_qty:flt(row.physical_stock_qty),
                available_to_return_qty:flt(row.available_to_return_qty),
                base_rate:flt(row.base_rate),
                discount_percentage:flt(row.discount_percentage),
                rate:flt(row.rate),
                is_vat_taxable:cint(row.is_vat_taxable),
                vat_rate:flt(row.vat_rate),
                approved_discount_percentage:flt(row.approved_discount_percentage),
                approved_rate:flt(row.approved_rate)
            }));
            added+=1;
        });
        const invoices=[...new Set(this.rows.map(r=>r.original_purchase_invoice).filter(Boolean))];
        this.$main.find('[data-role="invoice-summary"]').text(__("{0} invoice(s), {1} line(s) selected for Supplier Credit Note {2}.",[invoices.length,this.rows.length,this.value("supplier_credit_note_no")||"—"]));
        if(!added){
            frappe.show_alert({message:options.itemQuery?__("No new matching rows were added from invoice {0}.",[invoice.name]):__("All returnable rows from invoice {0} are already loaded.",[invoice.name]),indicator:"orange"},6);
        }else{
            frappe.show_alert({message:options.itemQuery?__("{0} selected line(s) added from invoice {1}.",[added,invoice.name]):__("{0} line(s) added from invoice {1}.",[added,invoice.name]),indicator:"green"},5);
        }
        this.renderItems();this.syncButtons();this.refreshProgressiveUI();
    }

    async loadBatchStock(){
        const sourceWarehouse=this.value("recall_source_warehouse");
        const itemCode=this.value("recall_item_code");
        const batchNo=this.value("recall_batch_no");
        if(!sourceWarehouse){frappe.msgprint({title:__("Source Warehouse Required"),message:__("Select the source warehouse first."),indicator:"orange"});return;}
        if(!itemCode){frappe.msgprint({title:__("Item Required"),message:__("Select the item first."),indicator:"orange"});return;}
        if(!batchNo){frappe.msgprint({title:__("Batch Required"),message:__("Select a batch belonging to the selected item."),indicator:"orange"});return;}
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.get_batch_stock_for_recall",
            args:{batch_no:batchNo,item_code:itemCode,source_warehouse:sourceWarehouse,company:this.value("company"),supplier:this.value("supplier")},
            freeze:true,
            freeze_message:__("Loading batch stock...")
        });
        const data=r.message||{};
        const incoming=(data.rows||[]).map(row=>this.recalculateRow({
            ...row,
            return_qty:flt(row.return_qty),
            stock_valuation_rate:flt(row.stock_valuation_rate),
            stock_value:flt(row.return_qty)*flt(row.stock_valuation_rate)
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
                message:__("This item, batch and warehouse are already included in the return list."),
                indicator:"orange"
            },6);
        }else{
            frappe.show_alert({
                message:__("{0} return line(s) added.",[added]),
                indicator:"green"
            },5);
        }

        await this.setValue("recall_item_code","");
        await this.setValue("recall_batch_no","");
        this.$main.find('[data-role="invoice-summary"]').text(
            __("{0} selected return line(s)",[this.rows.length])
        );
        this.renderItems();
    }

    removeRecallRow(index){
        if(this.quarantineDocstatus===1){
            frappe.show_alert({message:__("Recalled lines are locked after the quarantine transfer is submitted."),indicator:"orange"},6);
            return;
        }
        if(!Number.isInteger(index)||index<0||index>=this.rows.length)return;
        this.rows.splice(index,1);
        this.$main.find('[data-role="invoice-summary"]').text(
            __("{0} selected return line(s)",[this.rows.length])
        );
        this.renderItems();
    }

    attachAuthorityNotice(){
        new frappe.ui.FileUploader({
            allow_multiple:false,
            restrictions:{allowed_file_types:["image/*","application/pdf"]},
            on_success: async file=>{
                await this.setValue("authority_notification_attachment",file.file_url);
                if(this.controls.authority_notification_attachment?.refresh) this.controls.authority_notification_attachment.refresh();
                frappe.show_alert({message:__("Authority notice attached. Press Save Case Draft to store it on the case."),indicator:"green"},6);
            }
        });
    }

    attachHandoverReceipt(){
        new frappe.ui.FileUploader({
            allow_multiple:false,
            restrictions:{allowed_file_types:["image/*","application/pdf"]},
            on_success: async file=>{
                await this.setValue("handover_attachment",file.file_url);
                if(this.controls.handover_attachment?.refresh) this.controls.handover_attachment.refresh();
                frappe.show_alert({message:__("Supplier handover receipt attached. Press Create/Submit Handover or Save Case Draft to store it on the case."),indicator:"green"},6);
            }
        });
    }

    attachSupplierResponse(){
        new frappe.ui.FileUploader({
            allow_multiple:false,
            restrictions:{allowed_file_types:["image/*","application/pdf"]},
            on_success: async file=>{
                await this.setValue("supplier_response_attachment",file.file_url);
                if(this.controls.supplier_response_attachment?.refresh) this.controls.supplier_response_attachment.refresh();
                frappe.show_alert({message:__("Supplier response attached. Press Save Supplier Response to store it on the case."),indicator:"green"},6);
            }
        });
    }

    async saveSupplierResponse(){
        if(this.handoverDocstatus!==1){
            frappe.msgprint({
                title:__("Submitted Supplier Handover Required"),
                message:__("Submit the Supplier Handover Stock Entry before recording the supplier response."),
                indicator:"orange"
            });
            return;
        }
        const doc=await this.saveCase(true);
        this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${doc.operational_status||__("Awaiting Supplier Approval")}`);
        this.renderItems();
        this.refreshProgressiveUI();
        frappe.show_alert({message:__("Supplier response saved for {0}.",[doc.name]),indicator:"green"},7);
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
        this.purchaseReturnDocstatus=doc.purchase_return_docstatus;
        this.purchaseReturnStatus=doc.purchase_return_status||null;
        this.quarantineStockEntry=doc.quarantine_stock_entry||null;
        this.handoverStockEntry=doc.handover_stock_entry||null;
        this.rejectionReturnStockEntry=doc.rejection_return_stock_entry||null;
        this.approvedDebitNote=doc.approved_debit_note||null;
        this.approvedDebitNoteDocstatus=doc.approved_debit_note_docstatus;
        this.approvedDebitNoteStatus=doc.approved_debit_note_status||null;
        this.approvedDebitNoteAmount=flt(doc.approved_debit_note_amount);
        this.approvedDebitNoteOutstanding=flt(doc.approved_debit_note_outstanding);
        this.supplierClaim=doc.supplier_claim||null;
        this.supplierClaimDocstatus=doc.supplier_claim_docstatus;
        this.supplierClaimStatus=doc.supplier_claim_status||null;
        this.supplierClaimAccountingStatus=doc.supplier_claim_accounting_settlement_status||null;
        this.settlementStatus=doc.settlement_status||"Pending Settlement";
        this.claimUtilizationStatus=doc.claim_utilization_status||"Not Applied";
        this.claimSettlementDate=doc.claim_settlement_date||null;
        this.plannedClaimDeduction=flt(doc.planned_claim_deduction_amount);
        this.claimDeductionAmount=flt(doc.claim_deduction_amount);
        this.settledAmount=flt(doc.settled_amount);
        this.remainingSettlementAmount=flt(doc.remaining_settlement_amount);
        this.approvedReturnValue=flt(doc.approved_return_value);
        this.refundPaymentEntry=doc.refund_payment_entry||null;
        this.refundPaymentEntryStatus=doc.refund_payment_entry_status||null;
        this.refundPaymentEntryDocstatus=doc.refund_payment_entry_docstatus;
        this.refundAmount=flt(doc.refund_amount);
        this.refundEntriesCount=cint(doc.refund_entries_count);
        this.hasOpenRefundDraft=Boolean(doc.has_open_refund_draft);
        this.refundPayments=doc.refund_payments||[];
        this.quarantineDocstatus=doc.quarantine_docstatus;
        this.handoverDocstatus=doc.handover_docstatus;
        this.rejectionReturnDocstatus=doc.rejection_return_docstatus;
        this.rejectedQtyDestination=doc.rejected_qty_destination||"";
        this.rejectedDestinationWarehouse=doc.rejected_destination_warehouse||"";
        await this.setReturnType(doc.return_type||"Return Against Invoice",false);
        await this.setValue("company",doc.company);
        await this.applyCompanyDefaults();
        await this.setValue("posting_date",doc.posting_date);
        await this.setValue("supplier",doc.supplier);
        await this.setValue("supplier_credit_note_no",doc.supplier_credit_note_no);
        await this.setValue("supplier_credit_note_date",doc.supplier_credit_note_date);
        await this.setValue("supplier_credit_note_attachment",doc.supplier_credit_note_attachment);
        await this.setValue("original_purchase_invoice",doc.original_purchase_invoice);
        await this.setValue("settlement_method",doc.settlement_method||"Pending Settlement");
        await this.setValue("authority_notification_no",doc.authority_notification_no);
        await this.setValue("authority_notification_date",doc.authority_notification_date);
        await this.setValue("authority_notification_attachment",doc.authority_notification_attachment);
        await this.setValue("recall_source_warehouse",doc.recall_source_warehouse||doc.items?.[0]?.warehouse||"");
        await this.setValue("recall_item_code","");
        await this.setValue(
            "recall_quarantine_warehouse",
            doc.recall_quarantine_warehouse || this.value("recall_quarantine_warehouse") || ""
        );
        await this.setValue(
            "returns_with_supplier_warehouse",
            doc.returns_with_supplier_warehouse
                || this.value("returns_with_supplier_warehouse")
                || this.bootstrap?.special_warehouses?.supplier
                || ""
        );
        await this.setValue("handover_date",doc.handover_date);
        await this.setValue("handover_reference",doc.handover_reference);
        await this.setValue("handover_attachment",doc.handover_attachment);
        await this.setValue("supplier_response_date",doc.supplier_response_date);
        await this.setValue("supplier_response_reference",doc.supplier_response_reference);
        await this.setValue("supplier_response_attachment",doc.supplier_response_attachment);
        await this.setValue("supplier_response_notes",doc.supplier_response_notes);
        await this.setValue("rejected_qty_destination",doc.rejected_qty_destination);
        await this.setValue("rejected_destination_warehouse",doc.rejected_destination_warehouse);
        await this.setValue("rejected_destruction_date",doc.rejected_destruction_date);
        await this.setValue("rejected_destruction_reference",doc.rejected_destruction_reference);
        await this.setValue("rejected_destruction_attachment",doc.rejected_destruction_attachment);
        await this.setValue("rejected_destruction_notes",doc.rejected_destruction_notes);
        await this.applyRejectedDestinationDefault();
        await this.setValue(
            "approved_debit_note_posting_date",
            doc.approved_debit_note_posting_date || doc.supplier_response_date || frappe.datetime.get_today()
        );
        await this.setValue("supplier_claim",doc.supplier_claim);
        await this.setValue("refund_posting_date",doc.refund_posting_date||frappe.datetime.get_today());
        await this.setValue("refund_mode_of_payment",doc.refund_mode_of_payment);
        await this.setValue("refund_account",doc.refund_account);
        await this.setValue("refund_request_amount",doc.refund_request_amount);
        await this.setValue("refund_reference_no",doc.refund_reference_no);
        await this.setValue("refund_reference_date",doc.refund_reference_date);
        await this.setValue("refund_notes",doc.refund_notes);
        await this.setValue("recall_batch_no","");
        await this.setValue("remarks",doc.remarks||"");
        await this.setValue("case_reference",doc.name);
        this.rows=(doc.items||[]).map(row=>this.recalculateRow({
            ...row,
            return_qty:flt(row.return_qty),
            invoice_returnable_qty:flt(row.invoice_returnable_qty),
            physical_stock_qty:flt(row.physical_stock_qty),
            available_to_return_qty:flt(row.available_to_return_qty),
            quarantined_qty:flt(row.quarantined_qty),
            delivered_qty:flt(row.delivered_qty),
            accepted_qty:flt(row.accepted_qty),
            rejected_qty:flt(row.rejected_qty),
            base_rate:flt(row.base_rate)||flt(row.rate),
            discount_percentage:flt(row.discount_percentage),
            rate:flt(row.rate),
            is_vat_taxable:cint(row.is_vat_taxable),
            vat_rate:flt(row.vat_rate),
            approved_discount_percentage:flt(row.approved_discount_percentage),
            approved_rate:flt(row.approved_rate),
            rejected_returned_qty:flt(row.rejected_returned_qty),
            stock_valuation_rate:flt(row.stock_valuation_rate),
            stock_value:flt(row.stock_value)||flt(row.return_qty)*flt(row.stock_valuation_rate)
        }));
        this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${doc.operational_status||__("Draft")}`);
        const summaryReference = doc.approved_debit_note || doc.purchase_return || doc.original_purchase_invoice || doc.authority_notification_no || "";
        const summaryAmount = doc.approved_debit_note
            ? flt(doc.approved_debit_note_amount)
            : (doc.purchase_return ? (flt(doc.approved_return_value) || flt(doc.requested_return_value)) : flt(doc.requested_return_value));
        this.$main.find('[data-role="invoice-summary"]').text([doc.supplier||"",summaryReference,this.money(summaryAmount)].filter(Boolean).join(" • "));
        this.refreshSettlementUI();
        this.renderItems();this.syncButtons();this.refreshProgressiveUI();window.scrollTo({top:0,behavior:"smooth"});
        frappe.show_alert({message:__("Return Case {0} opened in the page.",[doc.name]),indicator:"green"},5);
    }

    renderRecallItems(stage){
        const rows=this.rows;
        const identity=(r,i)=>`<td>${i+1}</td><td><strong>${this.esc(r.item_name||r.item_code)}</strong><div class="prm-muted">${this.esc(r.item_code)}</div></td><td>${this.esc(r.batch_no||"—")}</td>`;
        if(["selection","quarantine_draft"].includes(stage)){
            const locked=stage!=="selection"?"disabled":"";
            return `<table class="prm-table prm-stage-table"><thead><tr><th>#</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Expiry")}</th><th>${__("Source Warehouse")}</th><th>${__("Physical Stock")}</th><th>${__("Recall Qty")}</th><th>${__("Action")}</th></tr></thead><tbody>${rows.map((r,i)=>`${`<tr>${identity(r,i)}`}<td>${this.esc(r.expiry_date||"—")}</td><td>${this.esc(r.warehouse||"")}</td><td>${flt(r.available_to_return_qty)}</td><td><input class="form-control input-sm" type="number" min="0" max="${flt(r.available_to_return_qty)}" step="any" data-row-field="return_qty" data-index="${i}" value="${flt(r.return_qty)}" ${locked}></td><td>${stage==="selection"?`<button type="button" class="btn btn-xs btn-danger" data-action="remove-recall-row" data-index="${i}">${__("Remove")}</button>`:"—"}</td></tr>`).join("")}</tbody></table>`;
        }
        if(["handover","handover_draft"].includes(stage)){
            const locked=stage!=="handover"?"disabled":"";
            return `<table class="prm-table prm-stage-table"><thead><tr><th>#</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Quarantined Qty")}</th><th>${__("Handover Qty")}</th></tr></thead><tbody>${rows.map((r,i)=>{const quarantined=flt(r.quarantined_qty)||flt(r.return_qty);return `<tr>${identity(r,i)}<td>${quarantined}</td><td><input class="form-control input-sm" type="number" min="0" max="${quarantined}" step="any" data-row-field="delivered_qty" data-index="${i}" value="${flt(r.delivered_qty)||quarantined}" ${locked}></td></tr>`;}).join("")}</tbody></table>`;
        }
        if(["response","rejection","complete_no_credit"].includes(stage)){
            const locked=stage!=="response"?"disabled":"";
            return `<table class="prm-table prm-stage-table"><thead><tr><th>#</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Handed Over")}</th><th>${__("Accepted Qty")}</th><th>${__("Rejected Qty")}</th><th>${__("Pending")}</th><th>${__("Rejection Reason")}</th><th>${__("Rejected Returned")}</th></tr></thead><tbody>${rows.map((r,i)=>{const delivered=flt(r.delivered_qty);const accepted=flt(r.accepted_qty);const rejected=flt(r.rejected_qty);const pending=Math.max(0,delivered-accepted-rejected);return `<tr>${identity(r,i)}<td>${delivered}</td><td><input class="form-control input-sm" type="number" min="0" max="${Math.max(0,delivered-rejected)}" step="any" data-row-field="accepted_qty" data-index="${i}" value="${accepted}" ${locked}></td><td><input class="form-control input-sm" type="number" min="0" max="${Math.max(0,delivered-accepted)}" step="any" data-row-field="rejected_qty" data-index="${i}" value="${rejected}" ${locked}></td><td data-row-pending="${i}">${pending}</td><td><input class="form-control input-sm" type="text" data-row-field="rejection_reason" data-index="${i}" value="${this.esc(r.rejection_reason||"")}" ${locked}></td><td>${flt(r.rejected_returned_qty)}</td></tr>`;}).join("")}</tbody></table>`;
        }
        const pricingLocked=stage!=="pricing"?"disabled":"";
        return `<table class="prm-table prm-stage-table prm-stage-pricing"><thead><tr><th>#</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Accepted Qty")}</th><th>${__("Base Price")}</th><th>${__("Approved Discount %")}</th><th>${__("Approved Net Unit")}</th><th>${__("VAT")}</th><th>${__("Approved Net")}</th><th>${__("Approved VAT")}</th><th>${__("Approved Total Credit")}</th></tr></thead><tbody>${rows.map((r,i)=>`<tr>${identity(r,i)}<td>${flt(r.accepted_qty)}</td><td><input class="form-control input-sm" type="number" min="0" step="any" data-row-field="base_rate" data-index="${i}" value="${this.inputNumber(r.base_rate)}" ${pricingLocked}></td><td><input class="form-control input-sm" type="number" min="0" max="100" step="any" data-row-field="approved_discount_percentage" data-index="${i}" value="${this.inputNumber(r.approved_discount_percentage)}" ${pricingLocked}></td><td><input class="form-control input-sm" type="number" min="0" step="any" data-row-field="approved_rate" data-index="${i}" value="${this.inputNumber(r.approved_rate)}" ${pricingLocked}></td><td title="${this.esc(r.vat_source||"")}">${this.vatLabel(r)}</td><td data-row-approved-net="${i}">${this.money(r.approved_net_amount)}</td><td data-row-approved-tax="${i}">${this.money(r.approved_tax_amount)}</td><td data-row-approved-value="${i}">${this.money(r.approved_total_credit)}</td></tr>`).join("")}</tbody></table>`;
    }

    renderItems(){
        const $host=this.$main.find('[data-role="items"]');
        const recallMode=this.isProgressiveReturnType();
        if(!this.rows.length){
            $host.html(`<div class="prm-empty">${recallMode?__("Select an item and a positive-stock batch, then add it to the return list."):__("Add one or more submitted Purchase Invoices from the same supplier, then enter return quantities.")}</div>`);
            this.refreshTotals();
            if(recallMode)this.refreshProgressiveUI();
            return;
        }
        this.rows.forEach(row=>this.recalculateRow(row));
        if(recallMode){
            $host.html(this.renderRecallItems(this.getRecallWorkflowStage()));
        }else{
            const reasons=["Normal Return","Near Expiry","Expired","Damaged","Wrong Item","Wrong Quantity","Supplier Error","Health Authority Recall","Other"];
            $host.html(`<table class="prm-table"><thead><tr>
                <th>#</th><th>${__("Invoice")}</th><th>${__("Supplier Inv No")}</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Expiry")}</th><th>${__("Warehouse")}</th>
                <th>${__("Purchased")}</th><th>${__("Returned")}</th><th>${__("Remaining Against Invoice")}</th><th>${__("Physical Stock")}</th><th>${__("Returnable Qty")}</th><th>${__("Return Qty")}</th><th>${__("Reason")}</th>
                <th>${__("Base Price")}</th><th>${__("Discount %")}</th><th>${__("Net Unit Value")}</th><th>${__("VAT")}</th><th>${__("Net Return Value")}</th><th>${__("VAT Amount")}</th><th>${__("Total Credit")}</th>
            </tr></thead><tbody>${this.rows.map((r,i)=>{
                const returnQtyControl=this.purchaseReturn
                    ? `<strong>${flt(r.return_qty)}</strong>`
                    : `<input class="form-control input-sm" type="number" min="0" max="${flt(r.available_to_return_qty)}" step="any" data-row-field="return_qty" data-index="${i}" value="${flt(r.return_qty)}">`;
                const reasonControl=this.purchaseReturn
                    ? this.esc(r.return_reason||"Normal Return")
                    : `<select class="form-control input-sm" data-row-field="return_reason" data-index="${i}">${reasons.map(x=>`<option ${x===(r.return_reason||"Normal Return")?"selected":""}>${this.esc(x)}</option>`).join("")}</select>`;
                return `<tr>
                    <td>${i+1}</td><td><span class="prm-link" data-action="open-original-row" data-name="${this.esc(r.original_purchase_invoice||"")}">${this.esc(r.original_purchase_invoice||this.value("original_purchase_invoice")||"—")}</span></td><td>${this.esc(r.original_supplier_invoice_no||"")}</td><td><strong>${this.esc(r.item_name||r.item_code)}</strong><div class="prm-muted">${this.esc(r.item_code)}</div>${r.purchase_return?`<div class="prm-muted">${__("Return")}: ${this.esc(r.purchase_return)}</div>`:""}</td>
                    <td>${this.esc(r.batch_no||"—")}</td><td>${this.esc(r.expiry_date||"—")}</td><td>${this.esc(r.warehouse||"")}</td>
                    <td>${flt(r.original_qty)}</td><td>${flt(r.already_returned_qty)}</td><td>${flt(r.invoice_returnable_qty)}</td><td>${flt(r.physical_stock_qty)}</td><td>${flt(r.available_to_return_qty)}</td><td>${returnQtyControl}</td><td>${reasonControl}</td>
                    <td>${this.money(r.base_rate)}</td><td>${flt(r.discount_percentage)}%</td><td>${this.money(r.rate)}</td><td title="${this.esc(r.vat_source||"")}">${this.vatLabel(r)}</td>
                    <td data-row-net-value="${i}">${this.money(r.net_return_amount)}</td><td data-row-tax-value="${i}">${this.money(r.tax_amount)}</td><td data-row-amount="${i}">${this.money(r.return_amount)}</td>
                </tr>`;
            }).join("")}</tbody></table>`);
        }
        this.refreshTotals();
        this.refreshProgressiveUI();
    }

    updateRow(event){
        const $el=$(event.currentTarget),index=Number($el.data("index")),field=$el.data("row-field"),row=this.rows[index];if(!row)return;
        if(field==="return_qty"){
            if(this.purchaseReturn||this.quarantineDocstatus===1){$el.val(flt(row.return_qty));return;}
            let qty=Math.max(0,flt($el.val()));const max=flt(row.available_to_return_qty);if(qty>max){qty=max;$el.val(max);frappe.show_alert({message:__("Quantity was limited to the current physical stock and invoice-returnable quantity."),indicator:"orange"},5);}row.return_qty=qty;
        }else if(field==="delivered_qty"){
            if(this.quarantineDocstatus!==1||this.handoverDocstatus===1){$el.val(flt(row.delivered_qty));return;}
            const max=flt(row.quarantined_qty)||flt(row.return_qty);let qty=Math.max(0,flt($el.val()));if(qty>max){qty=max;$el.val(max);frappe.show_alert({message:__("Handover quantity was limited to the quarantined quantity."),indicator:"orange"},5);}row.delivered_qty=qty;
        }else if(field==="accepted_qty"){
            if(this.handoverDocstatus!==1||this.rejectionReturnDocstatus===1||[0,1].includes(this.approvedDebitNoteDocstatus)){$el.val(flt(row.accepted_qty));return;}
            const max=Math.max(0,flt(row.delivered_qty)-flt(row.rejected_qty));let qty=Math.max(0,flt($el.val()));if(qty>max){qty=max;$el.val(max);frappe.show_alert({message:__("Accepted quantity was limited to the remaining handed-over quantity."),indicator:"orange"},5);}row.accepted_qty=qty;
            if(qty>0&&flt(row.approved_rate)<=0&&flt(row.approved_discount_percentage)<=0){row.approved_rate=flt(row.rate);row.approved_discount_percentage=flt(row.discount_percentage);row.approved_pricing_input_mode="Net Unit Value";}
        }else if(field==="rejected_qty"){
            if(this.handoverDocstatus!==1||this.rejectionReturnDocstatus===1||[0,1].includes(this.approvedDebitNoteDocstatus)){$el.val(flt(row.rejected_qty));return;}
            const max=Math.max(0,flt(row.delivered_qty)-flt(row.accepted_qty));let qty=Math.max(0,flt($el.val()));if(qty>max){qty=max;$el.val(max);frappe.show_alert({message:__("Rejected quantity was limited to the remaining handed-over quantity."),indicator:"orange"},5);}row.rejected_qty=qty;
        }else if(field==="base_rate"){
            if([0,1].includes(this.approvedDebitNoteDocstatus)){$el.val(flt(row.base_rate));return;}row.base_rate=Math.max(0,flt($el.val()));
        }else if(field==="discount_percentage"){
            if([0,1].includes(this.approvedDebitNoteDocstatus)){$el.val(flt(row.discount_percentage));return;}row.discount_percentage=this.clampDiscount($el.val());row.pricing_input_mode="Discount Percentage";
        }else if(field==="rate"){
            if([0,1].includes(this.approvedDebitNoteDocstatus)){$el.val(flt(row.rate));return;}row.rate=Math.max(0,flt($el.val()));row.pricing_input_mode="Net Unit Value";
        }else if(field==="approved_discount_percentage"){
            if(this.handoverDocstatus!==1||[0,1].includes(this.approvedDebitNoteDocstatus)){$el.val(this.inputNumber(row.approved_discount_percentage));return;}row.approved_discount_percentage=this.clampDiscount($el.val());row.approved_pricing_input_mode="Discount Percentage";
        }else if(field==="approved_rate"){
            if(this.handoverDocstatus!==1||[0,1].includes(this.approvedDebitNoteDocstatus)){$el.val(this.inputNumber(row.approved_rate));return;}row.approved_rate=this.roundNumber(Math.max(0,flt($el.val())),6);row.approved_pricing_input_mode="Net Unit Value";
        }else row[field]=$el.val();

        this.recalculateRow(row);
        this.$main.find(`[data-row-field="base_rate"][data-index="${index}"]`).val(this.inputNumber(row.base_rate));
        this.$main.find(`[data-row-field="discount_percentage"][data-index="${index}"]`).val(this.inputNumber(row.discount_percentage));
        this.$main.find(`[data-row-field="rate"][data-index="${index}"]`).val(this.inputNumber(row.rate));
        this.$main.find(`[data-row-field="approved_discount_percentage"][data-index="${index}"]`).val(this.inputNumber(row.approved_discount_percentage));
        this.$main.find(`[data-row-field="approved_rate"][data-index="${index}"]`).val(this.inputNumber(row.approved_rate));
        this.$main.find(`[data-row-stock-value="${index}"]`).text(this.money(flt(row.return_qty)*flt(row.stock_valuation_rate)));
        this.$main.find(`[data-row-net-value="${index}"]`).text(this.money(row.net_return_amount));
        this.$main.find(`[data-row-tax-value="${index}"]`).text(this.money(row.tax_amount));
        this.$main.find(`[data-row-amount="${index}"]`).text(this.money(row.return_amount));
        this.$main.find(`[data-row-difference="${index}"]`).text(this.money(row.return_amount-flt(row.return_qty)*flt(row.stock_valuation_rate)));
        this.$main.find(`[data-row-pending="${index}"]`).text(Math.max(0,flt(row.delivered_qty)-flt(row.accepted_qty)-flt(row.rejected_qty)));
        this.$main.find(`[data-row-approved-net="${index}"]`).text(this.money(row.approved_net_amount));
        this.$main.find(`[data-row-approved-tax="${index}"]`).text(this.money(row.approved_tax_amount));
        this.$main.find(`[data-row-approved-value="${index}"]`).text(this.money(row.approved_total_credit));
        this.refreshTotals();
    }

    refreshTotals(){
        const selected=this.rows.filter(r=>flt(r.return_qty)>0);
        selected.forEach(row=>this.recalculateRow(row));
        const qty=selected.reduce((a,r)=>a+flt(r.return_qty),0);
        const netValue=selected.reduce((a,r)=>a+flt(r.net_return_amount),0);
        const vatValue=selected.reduce((a,r)=>a+flt(r.tax_amount),0);
        const value=selected.reduce((a,r)=>a+flt(r.return_amount),0);
        const stockValue=selected.reduce((a,r)=>a+flt(r.return_qty)*flt(r.stock_valuation_rate),0);
        this.$main.find('[data-role="total-qty"]').text(qty);
        this.$main.find('[data-role="total-stock-value"]').text(this.money(stockValue));
        this.$main.find('[data-role="total-net-value"]').text(this.money(netValue));
        this.$main.find('[data-role="total-vat-value"]').text(this.money(vatValue));
        this.$main.find('[data-role="total-value"]').text(this.money(value));
        this.$main.find('[data-role="total-difference"]').text(this.money(value-stockValue));
        this.$main.find('[data-role="total-lines"]').text(selected.length);
        const handed=this.rows.reduce((total,row)=>total+flt(row.delivered_qty),0);
        const accepted=this.rows.reduce((total,row)=>total+flt(row.accepted_qty),0);
        const rejected=this.rows.reduce((total,row)=>total+flt(row.rejected_qty),0);
        const approvedValue=this.value("return_type")==="Return Against Invoice"
            ? flt(this.approvedReturnValue)
            : this.rows.reduce((total,row)=>total+flt(row.approved_total_credit),0);
        this.$main.find('[data-role="total-handover-qty"]').text(handed);
        this.$main.find('[data-role="total-accepted-qty"]').text(accepted);
        this.$main.find('[data-role="total-rejected-qty"]').text(rejected);
        this.$main.find('[data-role="total-pending-response"]').text(Math.max(0,handed-accepted-rejected));
        this.$main.find('[data-role="total-approved-value"]').text(this.money(approvedValue));
        this.$main.find('[data-role="debit-note-amount"]').text(this.money(this.approvedDebitNoteAmount));
        this.$main.find('[data-role="debit-note-outstanding"]').text(this.money(this.approvedDebitNoteOutstanding));
        this.$main.find('[data-role="debit-note-status"]').text(this.approvedDebitNoteStatus||"—");
        this.$main.find('[data-role="settlement-status"]').text(this.settlementStatus||"Pending Settlement");
        this.$main.find('[data-role="claim-utilization-status"]').text(this.claimUtilizationStatus||"Not Applied");
        this.$main.find('[data-role="claim-settlement-date"]').text(this.claimSettlementDate||"—");
        this.$main.find('[data-role="planned-claim-deduction"]').text(this.money(this.plannedClaimDeduction));
        this.$main.find('[data-role="claim-deduction-amount"]').text(this.money(this.claimDeductionAmount));
        this.$main.find('[data-role="refund-amount"]').text(this.money(this.refundAmount));
        this.$main.find('[data-role="refund-payment-status"]').text(this.refundPaymentEntryStatus||"—");
        this.$main.find('[data-role="remaining-settlement"]').text(this.money(this.remainingSettlementAmount));
    }

    payload(){return {
        name:this.caseName,return_type:this.value("return_type"),company:this.value("company"),posting_date:this.value("posting_date"),supplier:this.value("supplier"),supplier_credit_note_no:this.value("supplier_credit_note_no"),supplier_credit_note_date:this.value("supplier_credit_note_date"),supplier_credit_note_attachment:this.value("supplier_credit_note_attachment"),original_purchase_invoice:this.value("original_purchase_invoice"),settlement_method:this.value("settlement_method"),authority_notification_no:this.value("authority_notification_no"),authority_notification_date:this.value("authority_notification_date"),authority_notification_attachment:this.value("authority_notification_attachment"),recall_source_warehouse:this.value("recall_source_warehouse"),recall_item_code:this.value("recall_item_code"),recall_quarantine_warehouse:this.value("recall_quarantine_warehouse"),returns_with_supplier_warehouse:this.value("returns_with_supplier_warehouse"),handover_date:this.value("handover_date"),handover_reference:this.value("handover_reference"),handover_attachment:this.value("handover_attachment"),supplier_response_date:this.value("supplier_response_date"),supplier_response_reference:this.value("supplier_response_reference"),supplier_response_attachment:this.value("supplier_response_attachment"),supplier_response_notes:this.value("supplier_response_notes"),rejected_qty_destination:this.value("rejected_qty_destination"),rejected_destination_warehouse:this.value("rejected_destination_warehouse"),rejected_destruction_date:this.value("rejected_destruction_date"),rejected_destruction_reference:this.value("rejected_destruction_reference"),rejected_destruction_attachment:this.value("rejected_destruction_attachment"),rejected_destruction_notes:this.value("rejected_destruction_notes"),approved_debit_note_posting_date:this.value("approved_debit_note_posting_date"),supplier_claim:this.value("supplier_claim"),refund_posting_date:this.value("refund_posting_date"),refund_mode_of_payment:this.value("refund_mode_of_payment"),refund_account:this.value("refund_account"),refund_request_amount:flt(this.value("refund_request_amount")),refund_reference_no:this.value("refund_reference_no"),refund_reference_date:this.value("refund_reference_date"),refund_notes:this.value("refund_notes"),remarks:this.value("remarks"),items:this.rows
    };}

    async saveCase(silent=false){
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.save_case",args:{payload:this.payload()},freeze:true,freeze_message:__("Saving return case...")});
        const doc=r.message||{};this.caseName=doc.name;this.purchaseReturn=doc.purchase_return||null;this.purchaseReturnDocstatus=doc.purchase_return_docstatus;this.purchaseReturnStatus=doc.purchase_return_status||null;this.quarantineStockEntry=doc.quarantine_stock_entry||null;this.handoverStockEntry=doc.handover_stock_entry||null;this.rejectionReturnStockEntry=doc.rejection_return_stock_entry||null;this.approvedDebitNote=doc.approved_debit_note||null;this.approvedDebitNoteDocstatus=doc.approved_debit_note_docstatus;this.approvedDebitNoteStatus=doc.approved_debit_note_status||null;this.approvedDebitNoteAmount=flt(doc.approved_debit_note_amount);this.approvedDebitNoteOutstanding=flt(doc.approved_debit_note_outstanding);this.supplierClaim=doc.supplier_claim||null;this.supplierClaimDocstatus=doc.supplier_claim_docstatus;this.supplierClaimStatus=doc.supplier_claim_status||null;this.supplierClaimAccountingStatus=doc.supplier_claim_accounting_settlement_status||null;this.settlementStatus=doc.settlement_status||"Pending Settlement";this.claimUtilizationStatus=doc.claim_utilization_status||"Not Applied";this.claimSettlementDate=doc.claim_settlement_date||null;this.plannedClaimDeduction=flt(doc.planned_claim_deduction_amount);this.claimDeductionAmount=flt(doc.claim_deduction_amount);this.settledAmount=flt(doc.settled_amount);this.remainingSettlementAmount=flt(doc.remaining_settlement_amount);this.approvedReturnValue=flt(doc.approved_return_value);this.refundPaymentEntry=doc.refund_payment_entry||null;this.refundPaymentEntryStatus=doc.refund_payment_entry_status||null;this.refundPaymentEntryDocstatus=doc.refund_payment_entry_docstatus;this.refundAmount=flt(doc.refund_amount);this.refundEntriesCount=cint(doc.refund_entries_count);this.hasOpenRefundDraft=Boolean(doc.has_open_refund_draft);this.refundPayments=doc.refund_payments||[];this.quarantineDocstatus=doc.quarantine_docstatus;this.handoverDocstatus=doc.handover_docstatus;this.rejectionReturnDocstatus=doc.rejection_return_docstatus;this.rejectedQtyDestination=doc.rejected_qty_destination||"";this.rejectedDestinationWarehouse=doc.rejected_destination_warehouse||"";await this.setValue("case_reference",doc.name);this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${doc.operational_status||__("Draft")}`);this.refreshSettlementUI();this.renderItems();this.syncButtons();this.refreshProgressiveUI();if(!silent)frappe.show_alert({message:__("Return Case {0} saved.",[doc.name]),indicator:"green"},6);await this.refreshRecent();return doc;
    }

    async createPrimaryDraft(){
        if(this.isProgressiveReturnType())return this.createAndSubmitQuarantineTransfer();
        return this.createAndSubmitPurchaseReturn();
    }

    async createReturnDraft(){
        const doc=await this.saveCase(true);
        const answer=await new Promise(resolve=>frappe.confirm(__("Create an official Purchase Return draft for case {0}? The official document will remain Draft for review.",[doc.name]),()=>resolve(true),()=>resolve(false)));
        if(!answer)return;
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_purchase_return_draft",args:{case_name:doc.name},freeze:true,freeze_message:__("Creating Purchase Return draft...")});
        this.purchaseReturn=r.message.purchase_return;this.purchaseReturnDocstatus=0;this.purchaseReturnStatus="Draft";this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${__("Purchase Return Draft Created")}`);this.syncButtons();frappe.show_alert({message:__("Purchase Return {0} created as Draft.",[this.purchaseReturn]),indicator:"green"},8);await this.refreshRecent();
    }


    async createAndSubmitPurchaseReturn(){
        if(!this.rows.some(row=>flt(row.return_qty)>0)){
            frappe.msgprint({title:__("Return Quantity Required"),message:__("Load the invoice items and enter at least one positive Return Qty before submitting."),indicator:"orange"});
            return;
        }
        const doc=await this.saveCase(true);
        const answer=await new Promise(resolve=>frappe.confirm(
            __("Create and submit the official Purchase Return now? Stock and supplier credit will be updated immediately."),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_and_submit_purchase_return",
            args:{case_name:doc.name},
            freeze:true,
            freeze_message:__("Creating and submitting Purchase Return...")
        });
        await this.loadCase(doc.name);
        await this.refreshRecent();
        const submitted=(r.message.purchase_returns||[r.message.purchase_return]).filter(Boolean);
        frappe.show_alert({
            message:__("{0} Purchase Return document(s) submitted for this Supplier Credit Note. Outstanding: {1}.",[submitted.length,this.money(r.message.outstanding)]),
            indicator:"green"
        },8);
    }

    async deletePurchaseReturnDraft(){
        if(!this.caseName||!this.purchaseReturn||this.purchaseReturnDocstatus!==0)return;
        const draftName=this.purchaseReturn;
        const answer=await new Promise(resolve=>frappe.confirm(
            __("Delete Draft Purchase Return {0} and return case {1} to Under Review? No submitted stock or accounting entry will be affected.",[draftName,this.caseName]),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;
        await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.delete_purchase_return_draft",
            args:{case_name:this.caseName},
            freeze:true,
            freeze_message:__("Deleting Purchase Return draft...")
        });
        this.purchaseReturn=null;
        this.purchaseReturnDocstatus=null;
        this.purchaseReturnStatus=null;
        this.$main.find('[data-role="case-status"]').text(`${this.caseName} • ${__("Under Review")}`);
        this.syncButtons();
        await this.loadCase(this.caseName);
        await this.refreshRecent();
        frappe.show_alert({message:__("Draft Purchase Return {0} deleted safely.",[draftName]),indicator:"green"},8);
    }

    async createQuarantineDraft(){
        const doc=await this.saveCase(true);
        const answer=await new Promise(resolve=>frappe.confirm(__("Create a Material Transfer draft to move the selected batch stock into quarantine/expired warehouse? Stock remains sellable until the Stock Entry is submitted."),()=>resolve(true),()=>resolve(false)));
        if(!answer)return;
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_quarantine_transfer_draft",args:{case_name:doc.name},freeze:true,freeze_message:__("Creating quarantine transfer draft...")});
        this.quarantineStockEntry=r.message.stock_entry;this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${__("Quarantine Transfer Draft Created")}`);this.syncButtons();frappe.show_alert({message:__("Stock Entry {0} created as Draft.",[this.quarantineStockEntry]),indicator:"green"},8);await this.refreshRecent();
    }

    async createAndSubmitQuarantineTransfer(){
        if(!this.rows.some(row=>flt(row.return_qty)>0)){
            frappe.msgprint({title:__("Return Line Required"),message:__("Add at least one positive-stock item/batch line before creating the Quarantine Transfer."),indicator:"orange"});
            return;
        }
        const doc=await this.saveCase(true);
        const answer=await new Promise(resolve=>frappe.confirm(
            __("Create and submit the Quarantine Transfer now? Stock will move immediately to the quarantine/expired warehouse."),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_and_submit_quarantine_transfer",
            args:{case_name:doc.name},
            freeze:true,
            freeze_message:__("Creating and submitting quarantine transfer...")
        });
        await this.loadCase(doc.name);
        await this.refreshRecent();
        frappe.show_alert({message:__("Quarantine Transfer {0} submitted successfully.",[r.message.stock_entry]),indicator:"green"},8);
    }

    async createSupplierHandoverDraft(){
        const doc=await this.saveCase(true);
        if(doc.quarantine_docstatus!==1){
            frappe.msgprint({
                title:__("Submitted Quarantine Transfer Required"),
                message:__("Submit the quarantine Stock Entry before creating supplier handover."),
                indicator:"orange"
            });
            return;
        }
        const answer=await new Promise(resolve=>frappe.confirm(
            __("Create a Material Transfer draft from Recall Quarantine to Returns With Supplier for case {0}?",[doc.name]),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_supplier_handover_draft",
            args:{case_name:doc.name},
            freeze:true,
            freeze_message:__("Creating supplier handover draft...")
        });
        this.handoverStockEntry=r.message.stock_entry;
        this.handoverDocstatus=0;
        this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${__("Handover Transfer Draft Created")}`);
        this.syncButtons();
        frappe.show_alert({message:__("Supplier Handover Stock Entry {0} created as Draft.",[this.handoverStockEntry]),indicator:"green"},8);
        await this.refreshRecent();
    }

    async createAndSubmitSupplierHandover(){
        const doc=await this.saveCase(true);
        if(doc.quarantine_docstatus!==1){
            frappe.msgprint({title:__("Submitted Quarantine Transfer Required"),message:__("Submit the quarantine Stock Entry before supplier handover."),indicator:"orange"});
            return;
        }
        const answer=await new Promise(resolve=>frappe.confirm(
            __("Create and submit the Supplier Handover transfer now? Stock will move immediately to Returns With Supplier."),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_and_submit_supplier_handover",
            args:{case_name:doc.name},
            freeze:true,
            freeze_message:__("Creating and submitting supplier handover...")
        });
        await this.loadCase(doc.name);
        await this.refreshRecent();
        frappe.show_alert({message:__("Supplier Handover {0} submitted successfully.",[r.message.stock_entry]),indicator:"green"},8);
    }

    async createRejectedQuantityReturnDraft(){
        const doc=await this.saveCase(true);
        if(doc.handover_docstatus!==1){
            frappe.msgprint({
                title:__("Submitted Supplier Handover Required"),
                message:__("Submit the Supplier Handover Stock Entry before processing rejected quantity."),
                indicator:"orange"
            });
            return;
        }
        if(flt(doc.pending_response_quantity)>0){
            frappe.msgprint({
                title:__("Incomplete Supplier Response"),
                message:__("Complete Accepted and Rejected quantities for all handed-over stock first. Pending quantity: {0}.",[doc.pending_response_quantity]),
                indicator:"orange"
            });
            return;
        }
        if(flt(doc.rejected_quantity)<=0){
            frappe.msgprint({
                title:__("No Rejected Quantity"),
                message:__("All quantities are accepted; no rejected-stock movement is required."),
                indicator:"blue"
            });
            return;
        }
        if(!this.value("rejected_qty_destination")){
            frappe.msgprint({title:__("Rejected Destination Required"),message:__("Select where the rejected quantity will go before creating the stock document."),indicator:"orange"});
            return;
        }
        if(this.rejectedDestinationNeedsWarehouse()&&!this.value("rejected_destination_warehouse")){
            frappe.msgprint({title:__("Destination Warehouse Required"),message:__("Select the warehouse that will receive the rejected quantity."),indicator:"orange"});
            return;
        }
        if(this.isRejectedDestructionDestination()&&!this.value("rejected_destruction_notes")){
            frappe.msgprint({title:__("Destruction Details Required"),message:__("Enter the destruction reason/details before creating the destruction document."),indicator:"orange"});
            return;
        }
        const answer=await new Promise(resolve=>frappe.confirm(
            __("Create a rejected-stock draft for {0}?",[this.rejectedDestinationSummary()]),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_rejected_quantity_return_draft",
            args:{case_name:doc.name},
            freeze:true,
            freeze_message:__("Creating rejected-stock destination draft...")
        });
        this.rejectionReturnStockEntry=r.message.stock_entry;
        this.rejectionReturnDocstatus=0;
        this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${__("Rejection Return Draft Created")}`);
        this.syncButtons();
        frappe.show_alert({message:__("Rejected-stock document {0} created as Draft.",[this.rejectionReturnStockEntry]),indicator:"green"},8);
        await this.refreshRecent();
    }

    async createAndSubmitRejectedQuantityReturn(){
        frappe.show_alert({message:__("Preparing rejected-stock destination..."), indicator:"blue"}, 3);
        const doc=await this.saveCase(true);
        const destination = doc.rejected_qty_destination || this.value("rejected_qty_destination");
        const destinationWarehouse = doc.rejected_destination_warehouse || this.value("rejected_destination_warehouse");
        const destructionNotes = doc.rejected_destruction_notes || this.value("rejected_destruction_notes");
        if(doc.handover_docstatus!==1){
            frappe.msgprint({title:__("Submitted Supplier Handover Required"),message:__("Submit the Supplier Handover Stock Entry before processing rejected quantity."),indicator:"orange"});
            return;
        }
        if(flt(doc.pending_response_quantity)>0){
            frappe.msgprint({title:__("Incomplete Supplier Response"),message:__("Complete Accepted and Rejected quantities first. Pending quantity: {0}.",[doc.pending_response_quantity]),indicator:"orange"});
            return;
        }
        if(flt(doc.rejected_quantity)<=0){
            frappe.msgprint({title:__("No Rejected Quantity"),message:__("All quantities are accepted; no rejected-stock movement is required."),indicator:"blue"});
            return;
        }
        if(!destination){
            frappe.msgprint({title:__("Rejected Destination Required"),message:__("Select where the rejected quantity will go before submitting the stock document."),indicator:"orange"});
            return;
        }
        if(this.rejectedDestinationNeedsWarehouse(destination)&&!destinationWarehouse){
            frappe.msgprint({title:__("Destination Warehouse Required"),message:__("Select the warehouse that will receive the rejected quantity."),indicator:"orange"});
            return;
        }
        if(this.isRejectedDestructionDestination(destination)&&!destructionNotes){
            frappe.msgprint({title:__("Destruction Details Required"),message:__("Enter the destruction reason/details before submitting the destruction document."),indicator:"orange"});
            return;
        }
        const summary = this.rejectedDestinationNeedsWarehouse(destination)
            ? `${destination} → ${destinationWarehouse || __("warehouse not selected")}`
            : (this.isRejectedDestructionDestination(destination) ? `${destination} • ${doc.rejected_destruction_date || this.value("rejected_destruction_date") || __("date not selected")}` : destination);
        const answer=await new Promise(resolve=>frappe.confirm(
            __("Create and submit the rejected-stock document now for {0}?",[summary]),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_and_submit_rejected_quantity_return",
            args:{case_name:doc.name},
            freeze:true,
            freeze_message:__("Creating and submitting rejected-stock destination...")
        });
        await this.loadCase(doc.name);
        await this.refreshRecent();
        frappe.show_alert({message:__("Rejected-stock document {0} submitted successfully.",[r.message.stock_entry]),indicator:"green"},8);
    }

    async createApprovedDebitNoteDraft(){
        const doc=await this.saveCase(true);
        if(doc.handover_docstatus!==1){
            frappe.msgprint({
                title:__("Submitted Supplier Handover Required"),
                message:__("Submit the Supplier Handover Stock Entry first."),
                indicator:"orange"
            });
            return;
        }
        if(flt(doc.pending_response_quantity)>0){
            frappe.msgprint({
                title:__("Incomplete Supplier Response"),
                message:__("Complete the supplier response first. Pending quantity: {0}.",[doc.pending_response_quantity]),
                indicator:"orange"
            });
            return;
        }
        if(flt(doc.accepted_quantity)<=0){
            frappe.msgprint({
                title:__("No Accepted Quantity"),
                message:__("There is no accepted quantity for a supplier debit note."),
                indicator:"blue"
            });
            return;
        }
        if(flt(doc.rejected_quantity)>0 && doc.rejection_return_docstatus!==1){
            frappe.msgprint({
                title:__("Submitted Rejected Qty Destination Required"),
                message:__("Submit the rejected quantity destination document before creating the Approved Debit Note."),
                indicator:"orange"
            });
            return;
        }

        const answer=await new Promise(resolve=>frappe.confirm(
            __("Create an Approved Purchase Debit Note for {0}? Update Stock will be enabled and accepted quantities will leave Returns With Supplier warehouse.",[this.money(doc.approved_return_value)]),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;

        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_approved_debit_note_draft",
            args:{case_name:doc.name},
            freeze:true,
            freeze_message:__("Creating approved supplier debit note...")
        });

        this.approvedDebitNote=r.message.purchase_invoice;
        this.approvedDebitNoteDocstatus=0;
        this.approvedDebitNoteStatus="Draft";
        this.approvedDebitNoteAmount=flt(r.message.approved_value);
        this.approvedDebitNoteOutstanding=flt(r.message.approved_value);
        this.$main.find('[data-role="case-status"]').text(`${doc.name} • ${__("Approved Debit Note Draft Created")}`);
        this.refreshTotals();
        this.syncButtons();
        frappe.show_alert({
            message:__("Approved Debit Note {0} created as Draft.",[this.approvedDebitNote]),
            indicator:"green"
        },8);
        await this.refreshRecent();
    }

    async createAndSubmitApprovedDebitNote(){
        const doc=await this.saveCase(true);
        if(doc.handover_docstatus!==1){
            frappe.msgprint({title:__("Submitted Supplier Handover Required"),message:__("Submit the Supplier Handover Stock Entry first."),indicator:"orange"});
            return;
        }
        if(flt(doc.pending_response_quantity)>0){
            frappe.msgprint({title:__("Incomplete Supplier Response"),message:__("Complete the supplier response first. Pending quantity: {0}.",[doc.pending_response_quantity]),indicator:"orange"});
            return;
        }
        if(flt(doc.accepted_quantity)<=0){
            frappe.msgprint({title:__("No Accepted Quantity"),message:__("There is no accepted quantity for a supplier debit note."),indicator:"blue"});
            return;
        }
        if(flt(doc.rejected_quantity)>0 && doc.rejection_return_docstatus!==1){
            frappe.msgprint({title:__("Submitted Rejected Qty Destination Required"),message:__("Submit the rejected quantity destination document before submitting the Approved Debit Note."),indicator:"orange"});
            return;
        }
        const answer=await new Promise(resolve=>frappe.confirm(
            __("Create and submit the Approved Supplier Debit Note now? Accepted quantities will leave Returns With Supplier warehouse and supplier credit will become available."),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_and_submit_approved_debit_note",
            args:{case_name:doc.name},
            freeze:true,
            freeze_message:__("Creating and submitting approved supplier debit note...")
        });
        await this.loadCase(doc.name);
        await this.refreshRecent();
        frappe.show_alert({message:__("Approved Debit Note {0} submitted successfully. Outstanding: {1}.",[r.message.purchase_invoice,this.money(r.message.outstanding)]),indicator:"green"},8);
    }

    async createOrLinkSupplierClaimDeduction(){
        const doc=await this.saveCase(true);
        if(doc.approved_debit_note_docstatus!==1){frappe.msgprint({title:__("Submitted Approved Debit Note Required"),message:__("Submit the Approved Supplier Debit Note first."),indicator:"orange"});return;}
        const selectedClaim=this.value("supplier_claim")||null;
        const question=selectedClaim?__("Add Approved Debit Note {0} to Supplier Claim {1}?",[doc.approved_debit_note,selectedClaim]):__("Create a new Draft Supplier Claim and add Approved Debit Note {0} as a deduction?",[doc.approved_debit_note]);
        const answer=await new Promise(resolve=>frappe.confirm(question,()=>resolve(true),()=>resolve(false)));
        if(!answer)return;
        const r=await frappe.call({method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_or_link_supplier_claim_deduction",args:{case_name:doc.name,supplier_claim:selectedClaim},freeze:true,freeze_message:__("Preparing supplier claim deduction...")});
        this.supplierClaim=r.message.supplier_claim;this.settlementStatus=r.message.docstatus===1?"Claim Deduction Confirmed":"Claim Deduction Draft";this.claimUtilizationStatus=r.message.docstatus===1?"Confirmed in Submitted Claim":"Planned in Draft Claim";this.plannedClaimDeduction=flt(r.message.planned_deduction);this.claimDeductionAmount=r.message.docstatus===1?flt(r.message.planned_deduction):0;this.remainingSettlementAmount=Math.max(0,flt(doc.approved_return_value)-this.claimDeductionAmount);
        await this.setValue("supplier_claim",this.supplierClaim);this.refreshTotals();this.syncButtons();frappe.show_alert({message:__("Supplier Claim {0} prepared with deduction {1}.",[this.supplierClaim,this.money(this.plannedClaimDeduction)]),indicator:"green"},8);await this.refreshRecent();
    }

    async createSupplierRefundPaymentDraft(){
        const caseName=this.caseName;
        if(!caseName){
            frappe.msgprint({title:__("Return Case Required"),message:__("Open or save the return case before creating a supplier refund."),indicator:"orange"});
            return;
        }
        const amount=flt(this.value("refund_request_amount"));
        const postingDate=this.value("refund_posting_date")||frappe.datetime.get_today();
        const modeOfPayment=this.value("refund_mode_of_payment");
        const refundAccount=this.value("refund_account");
        const referenceNo=this.value("refund_reference_no");
        const referenceDate=this.value("refund_reference_date");
        const notes=this.value("refund_notes");

        if(amount<=0){
            frappe.msgprint({title:__("Refund Amount Required"),message:__("Enter a refund amount greater than zero."),indicator:"orange"});
            return;
        }
        if(amount>flt(this.remainingSettlementAmount)+0.01){
            frappe.msgprint({title:__("Refund Exceeds Remaining"),message:__("Refund amount cannot exceed the remaining settlement amount."),indicator:"red"});
            return;
        }
        if(!modeOfPayment||!refundAccount){
            frappe.msgprint({title:__("Refund Payment Details Required"),message:__("Select the Mode of Payment and the receiving Bank / Cash account."),indicator:"orange"});
            return;
        }

        const answer=await new Promise(resolve=>frappe.confirm(
            __("Create a Supplier Refund Payment Entry Draft for {0}?",[this.money(amount)]),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;

        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_supplier_refund_payment_draft",
            args:{
                case_name:caseName,
                amount,
                posting_date:postingDate,
                mode_of_payment:modeOfPayment,
                refund_account:refundAccount,
                reference_no:referenceNo,
                reference_date:referenceDate,
                notes
            },
            freeze:true,
            freeze_message:__("Creating supplier refund payment draft...")
        });

        this.refundPaymentEntry=r.message.payment_entry;
        this.refundPaymentEntryStatus="Draft";
        this.hasOpenRefundDraft=true;
        this.$main.find('[data-role="case-status"]').text(`${caseName} • ${__("Refund Payment Draft Created")}`);
        this.refreshTotals();
        this.syncButtons();
        frappe.show_alert({message:__("Supplier Refund Payment {0} created as Draft.",[this.refundPaymentEntry]),indicator:"green"},8);
        await this.refreshRecent();
    }

    async createAndSubmitSupplierRefundPayment(){
        const caseName=this.caseName;
        if(!caseName){
            frappe.msgprint({title:__("Return Case Required"),message:__("Open or save the return case before creating a supplier refund."),indicator:"orange"});
            return;
        }
        const amount=flt(this.value("refund_request_amount"));
        const postingDate=this.value("refund_posting_date")||frappe.datetime.get_today();
        const modeOfPayment=this.value("refund_mode_of_payment");
        const refundAccount=this.value("refund_account");
        const referenceNo=this.value("refund_reference_no");
        const referenceDate=this.value("refund_reference_date");
        const notes=this.value("refund_notes");

        if(amount<=0 && !this.hasOpenRefundDraft){
            frappe.msgprint({title:__("Refund Amount Required"),message:__("Enter a refund amount greater than zero."),indicator:"orange"});
            return;
        }
        if(amount>flt(this.remainingSettlementAmount)+0.01 && !this.hasOpenRefundDraft){
            frappe.msgprint({title:__("Refund Exceeds Remaining"),message:__("Refund amount cannot exceed the remaining settlement amount."),indicator:"red"});
            return;
        }
        if((!modeOfPayment||!refundAccount) && !this.hasOpenRefundDraft){
            frappe.msgprint({title:__("Refund Payment Details Required"),message:__("Select the Mode of Payment and the receiving Bank / Cash account."),indicator:"orange"});
            return;
        }

        const answer=await new Promise(resolve=>frappe.confirm(
            this.hasOpenRefundDraft
                ? __("Submit the existing Supplier Refund Payment draft now?")
                : __("Create and submit a Supplier Refund Payment Entry for {0}?",[this.money(amount)]),
            ()=>resolve(true),
            ()=>resolve(false)
        ));
        if(!answer)return;

        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.create_and_submit_supplier_refund_payment",
            args:{
                case_name:caseName,
                amount,
                posting_date:postingDate,
                mode_of_payment:modeOfPayment,
                refund_account:refundAccount,
                reference_no:referenceNo,
                reference_date:referenceDate,
                notes
            },
            freeze:true,
            freeze_message:__("Creating and submitting supplier refund payment...")
        });
        await this.loadCase(caseName);
        await this.refreshRecent();
        frappe.show_alert({message:__("Supplier Refund Payment {0} submitted successfully. Amount: {1}.",[r.message.payment_entry,this.money(r.message.amount)]),indicator:"green"},8);
    }

    async cancelLinkedDocument({method,args,question,freezeMessage,successMessage}){
        if(!this.caseName){
            frappe.msgprint({title:__("Return Case Required"),message:__("Open the return case first."),indicator:"orange"});
            return;
        }
        const answer=await new Promise(resolve=>frappe.confirm(question,()=>resolve(true),()=>resolve(false)));
        if(!answer)return;
        const r=await frappe.call({method,args,freeze:true,freeze_message:freezeMessage});
        const caseName=(r.message&&r.message.case)||this.caseName;
        await this.loadCase(caseName);
        await this.refreshRecent();
        frappe.show_alert({message:successMessage(r.message||{}),indicator:"green"},8);
    }

    async cancelQuarantineTransfer(){
        return this.cancelLinkedDocument({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.cancel_quarantine_transfer",
            args:{case_name:this.caseName},
            question:__("Cancel/delete the Quarantine Transfer for case {0}? This is allowed only before Supplier Handover.",[this.caseName]),
            freezeMessage:__("Cancelling quarantine transfer..."),
            successMessage:(m)=>__("Quarantine Transfer {0} reversed. Case status: {1}.",[m.document||"",m.operational_status||""])
        });
    }

    async cancelSupplierHandover(){
        return this.cancelLinkedDocument({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.cancel_supplier_handover",
            args:{case_name:this.caseName},
            question:__("Cancel/delete the Supplier Handover for case {0}? Supplier response quantities will be cleared.",[this.caseName]),
            freezeMessage:__("Cancelling supplier handover..."),
            successMessage:(m)=>__("Supplier Handover {0} reversed. Case status: {1}.",[m.document||"",m.operational_status||""])
        });
    }

    async cancelRejectedQuantityDestination(){
        return this.cancelLinkedDocument({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.cancel_rejected_quantity_destination",
            args:{case_name:this.caseName},
            question:__("Cancel/delete the rejected-stock document for case {0}? The rejected quantity will become pending destination again.",[this.caseName]),
            freezeMessage:__("Cancelling rejected quantity destination..."),
            successMessage:(m)=>__("Rejected Qty Document {0} reversed. Case status: {1}.",[m.document||"",m.operational_status||""])
        });
    }

    async cancelApprovedDebitNote(){
        return this.cancelLinkedDocument({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.cancel_approved_debit_note",
            args:{case_name:this.caseName},
            question:__("Cancel/delete the Approved Debit Note for case {0}? Supplier credit and accepted-stock finalization will be reversed.",[this.caseName]),
            freezeMessage:__("Cancelling approved debit note..."),
            successMessage:(m)=>__("Approved Debit Note {0} reversed. Remaining settlement: {1}.",[m.purchase_invoice||"",this.money(m.remaining_settlement||0)])
        });
    }

    async removeDraftClaimDeduction(){
        return this.cancelLinkedDocument({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.remove_draft_supplier_claim_deduction",
            args:{case_name:this.caseName},
            question:__("Remove the draft Supplier Claim deduction for case {0}? Submitted claims must be cancelled from the Supplier Claim document.",[this.caseName]),
            freezeMessage:__("Removing draft supplier claim deduction..."),
            successMessage:(m)=>__("Supplier Claim deduction reversed. Remaining settlement: {0}.",[this.money(m.remaining_settlement||0)])
        });
    }

    async reverseSupplierClaimDeduction(){
        return this.cancelLinkedDocument({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.reverse_supplier_claim_deduction",
            args:{case_name:this.caseName},
            question:__("Refresh/reverse the Supplier Claim deduction for case {0}? If the claim is submitted, cancel it from the Supplier Claim document first.",[this.caseName]),
            freezeMessage:__("Reversing supplier claim deduction..."),
            successMessage:(m)=>__("Supplier Claim deduction checked. Action: {0}. Remaining settlement: {1}.",[m.action||"synced",this.money(m.remaining_settlement||0)])
        });
    }

    async cancelSupplierRefundPayment(){
        return this.cancelLinkedDocument({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.cancel_supplier_refund_payment",
            args:{case_name:this.caseName,payment_entry:this.refundPaymentEntry},
            question:__("Cancel/delete the latest Supplier Refund Payment for case {0}? Remaining settlement will be recalculated.",[this.caseName]),
            freezeMessage:__("Cancelling supplier refund payment..."),
            successMessage:(m)=>__("Supplier Refund Payment {0} reversed. Remaining settlement: {1}.",[m.payment_entry||"",this.money(m.remaining_settlement||0)])
        });
    }

    syncButtons(){
        ["create-handover","create-rejection-return","create-approved-debit-note","create-refund-payment","cancel-quarantine","cancel-handover","cancel-rejection-return","cancel-approved-debit-note","remove-claim-deduction","reverse-claim-deduction","cancel-refund-payment"].forEach(action=>{
            this.$main.find(`[data-action="${action}"]`).hide().prop("disabled",true);
        });
        const returnType=this.value("return_type");
        const invoiceMode=returnType==="Return Against Invoice";
        const recallMode=this.isProgressiveReturnType(returnType);
        const recallStage=recallMode?this.getRecallWorkflowStage():null;
        const selectedReturnRows=this.rows.filter(row=>flt(row.return_qty)>0);
        const hasSelectedRows=selectedReturnRows.length>0;
        const batchSelectionReady=recallMode
            && recallStage==="selection"
            && Boolean(this.value("recall_source_warehouse"))
            && Boolean(this.value("recall_item_code"))
            && Boolean(this.value("recall_batch_no"))
            && Boolean(this.value("recall_quarantine_warehouse"));
        const primaryReady=(invoiceMode
                && hasSelectedRows
                && this.purchaseReturnDocstatus!==1)
            || (recallMode
                && recallStage==="selection"
                && hasSelectedRows
                && this.quarantineDocstatus!==1);
        this.$main.find('[data-action="load-batch"]').prop("disabled",!batchSelectionReady);
        this.$main.find('[data-action="create-primary"]').prop("disabled",!primaryReady);
        this.$main.find('[data-action="print-current-case"]').prop("disabled",!this.caseName);
        this.$main.find('[data-action="open-original"]').prop("disabled",!this.value("original_purchase_invoice"));
        this.$main.find('[data-action="open-return"]').prop("disabled",!this.purchaseReturn);
        this.$main.find('[data-action="delete-return-draft"]')
            .prop("disabled",!this.purchaseReturn||this.purchaseReturnDocstatus!==0)
            .toggle(Boolean(this.purchaseReturn)&&this.purchaseReturnDocstatus===0&&this.value("return_type")==="Return Against Invoice");
        this.$main.find('[data-action="open-quarantine"]').prop("disabled",!this.quarantineStockEntry);
        this.$main.find('[data-action="open-handover"]').prop("disabled",!this.handoverStockEntry);
        this.$main.find('[data-action="open-rejection-return"]').prop("disabled",!this.rejectionReturnStockEntry);
        this.$main.find('[data-action="open-approved-debit-note"]').prop("disabled",!this.approvedDebitNote);
        this.$main.find('[data-action="open-supplier-claim"]').prop("disabled",!this.supplierClaim);
        this.$main.find('[data-action="open-refund-payment"]')
            .prop("disabled",!this.refundPaymentEntry)
            .toggle(Boolean(this.refundPaymentEntry));
        const refundComplete=this.remainingSettlementAmount<=0.01||["Settled","Settled Through Supplier Claim"].includes(this.settlementStatus);
        const refundMethodSelected=this.refundMethodSelected();
        const settlementReady=this.approvedReturnValue>0.01&&this.remainingSettlementAmount>0.01;
        this.$main.find('[data-action="create-refund-payment"]')
            .prop(
                "disabled",
                !this.caseName
                    || !refundMethodSelected
                    || !settlementReady
                    || refundComplete
                    || this.hasOpenRefundDraft
            )
            .toggle(refundMethodSelected&&!refundComplete);
        this.$main.find('[data-action="submit-refund-payment"]')
            .prop(
                "disabled",
                !this.caseName
                    || !refundMethodSelected
                    || refundComplete
                    || (!settlementReady && !this.hasOpenRefundDraft)
            )
            .toggle(refundMethodSelected&&!refundComplete);
        this.$main.find('[data-action="create-claim-deduction"]').prop("disabled",this.approvedDebitNoteDocstatus!==1||["Claim Deduction Confirmed","Settled Through Supplier Claim","Settled"].includes(this.settlementStatus));
        this.$main.find('[data-action="save-response"]').prop("disabled",this.handoverDocstatus!==1||this.rejectionReturnDocstatus===1);
        const totalRejected=this.rows.reduce((total,row)=>total+flt(row.rejected_qty),0);
        const totalPending=this.rows.reduce((total,row)=>total+Math.max(0,flt(row.delivered_qty)-flt(row.accepted_qty)-flt(row.rejected_qty)),0);
        const missingRejectedDestination=totalRejected>0&&!this.value("rejected_qty_destination");
        const missingRejectedWarehouse=totalRejected>0&&this.rejectedDestinationNeedsWarehouse()&&!this.value("rejected_destination_warehouse");
        const missingDestructionDetails=totalRejected>0&&this.isRejectedDestructionDestination()&&!this.value("rejected_destruction_notes");
        const rejectedDestinationIncomplete=missingRejectedDestination||missingRejectedWarehouse||missingDestructionDetails;
        const rejectionBlockedReason = this.rejectedDestinationBlockedReason(totalRejected, totalPending, rejectedDestinationIncomplete);
        ["create-rejection-return","submit-rejection-return"].forEach(action=>{
            const $button=this.$main.find(`[data-action="${action}"]`);
            const blocked=Boolean(rejectionBlockedReason);
            // Keep these buttons clickable even when prerequisites are incomplete so the user gets a clear reason instead of a dead button.
            $button.prop("disabled", false)
                .attr("data-not-ready", blocked ? "1" : "0")
                .attr("data-not-ready-reason", rejectionBlockedReason || "")
                .attr("title", rejectionBlockedReason || "");
        });
        const totalAccepted=this.rows.reduce((total,row)=>total+flt(row.accepted_qty),0);
        const rejectionReady=totalRejected<=0||this.rejectionReturnDocstatus===1;
        this.$main.find('[data-action="create-approved-debit-note"]').prop(
            "disabled",
            !this.isProgressiveReturnType()
                || this.handoverDocstatus!==1
                || totalAccepted<=0
                || totalPending>0.000001
                || !rejectionReady
                || this.approvedDebitNoteDocstatus===1
                || this.approvedDebitNoteDocstatus===0
        );
        this.$main.find('[data-action="submit-approved-debit-note"]').prop(
            "disabled",
            !this.isProgressiveReturnType()
                || this.handoverDocstatus!==1
                || totalAccepted<=0
                || totalPending>0.000001
                || !rejectionReady
                || this.approvedDebitNoteDocstatus===1
        );
        this.$main.find('[data-action="save-response"]').prop(
            "disabled",
            this.handoverDocstatus!==1
                || this.rejectionReturnDocstatus===1
                || [0,1].includes(this.approvedDebitNoteDocstatus)
        );
        this.$main.find('[data-action="create-handover"]').prop(
            "disabled",
            !this.isProgressiveReturnType()
                || !this.caseName
                || this.quarantineDocstatus!==1
                || this.handoverDocstatus===1
        );
        this.$main.find('[data-action="submit-handover"]').prop(
            "disabled",
            !this.isProgressiveReturnType()
                || !this.caseName
                || this.quarantineDocstatus!==1
                || this.handoverDocstatus===1
        );
        this.$main.find('[data-action="submit-quarantine"]').prop(
            "disabled",
            !this.isProgressiveReturnType()
                || !hasSelectedRows
                || this.quarantineDocstatus===1
        );
        const activeClaim=Boolean(this.supplierClaim)&&this.supplierClaimDocstatus!==2;
        const activeRefund=Boolean(this.refundPaymentEntry)&&this.refundPaymentEntryDocstatus!==2;
        this.$main.find('[data-action="cancel-quarantine"]').prop(
            "disabled",
            !this.quarantineStockEntry || this.handoverDocstatus===0 || this.handoverDocstatus===1
        );
        this.$main.find('[data-action="cancel-handover"]').prop(
            "disabled",
            !this.handoverStockEntry || this.rejectionReturnDocstatus===0 || this.rejectionReturnDocstatus===1 || this.approvedDebitNoteDocstatus===0 || this.approvedDebitNoteDocstatus===1
        );
        this.$main.find('[data-action="cancel-rejection-return"]').prop(
            "disabled",
            !this.rejectionReturnStockEntry || this.approvedDebitNoteDocstatus===0 || this.approvedDebitNoteDocstatus===1
        );
        this.$main.find('[data-action="cancel-approved-debit-note"]').prop(
            "disabled",
            !this.approvedDebitNote || activeClaim || activeRefund
        );
        this.$main.find('[data-action="remove-claim-deduction"]').prop(
            "disabled",
            !this.supplierClaim || this.supplierClaimDocstatus!==0
        );
        this.$main.find('[data-action="reverse-claim-deduction"]').prop(
            "disabled",
            !this.supplierClaim || this.supplierClaimDocstatus===0
        );
        this.$main.find('[data-action="cancel-refund-payment"]').prop(
            "disabled",
            !this.refundPaymentEntry || this.refundPaymentEntryDocstatus===2
        );

        this.refreshProgressiveUI();
    }

    async refreshRecent(){
        const r=await frappe.call({
            method:"pharma_erp.pharma_erp.page.purchase_returns_management.purchase_returns_management.list_recent_cases",
            args:{company:this.value("company"),limit:300,search_text:this.recentSearch||"",from_date:this.recentFromDate||"",to_date:this.recentToDate||""}
        });
        this.renderRecent(r.message||[]);
    }

    setRecentExpanded(expanded){
        this.recentExpanded=Boolean(expanded);
        this.$main.find('[data-role="recent-body"]').toggleClass("expanded",this.recentExpanded);
        this.$main.find('[data-action="toggle-recent-list"]').text(this.recentExpanded ? __("Hide List") : __("Show List"));
    }

    toggleRecentList(){
        this.setRecentExpanded(!this.recentExpanded);
    }

    caseIsClosed(row){
        const remaining=flt(row?.remaining_settlement_amount);
        const settlement=String(row?.settlement_status||"").toLowerCase();
        const operational=String(row?.operational_status||"").toLowerCase();
        const utilization=String(row?.claim_utilization_status||"").toLowerCase();
        const terminal=["financially settled","settled through supplier claim","settled","claim deduction confirmed","refund confirmed","mixed settlement confirmed"];
        const hasTerminal=terminal.some(s=>settlement.includes(s)||operational.includes(s));
        return remaining<=0.000001 && (hasTerminal || utilization.includes("fully utilized"));
    }

    normalizeSearchText(value){
        return String(value||"").toLowerCase().replace(/[^a-z0-9؀-ۿ]+/g,"");
    }

    searchTokens(value){
        return String(value||"").toLowerCase().split(/[^a-z0-9؀-ۿ]+/g).filter(Boolean);
    }

    withoutEnglishVowels(value){
        return String(value||"").replace(/[aeiou]/g,"");
    }

    smartMatchesSearch(row,query){
        const raw=String(query||"").trim().toLowerCase();
        if(!raw)return true;
        const hay=this.recentHaystack(row);
        const compactHay=this.normalizeSearchText(hay);
        const compactQuery=this.normalizeSearchText(raw);
        const hayNoVowels=this.withoutEnglishVowels(compactHay);
        const queryNoVowels=this.withoutEnglishVowels(compactQuery);
        const tokens=this.searchTokens(raw);
        if(hay.includes(raw))return true;
        if(compactQuery && compactHay.includes(compactQuery))return true;
        if(queryNoVowels && hayNoVowels.includes(queryNoVowels))return true;
        if(tokens.length){
            const tokenMatch=tokens.every(token=>{
                const c=this.normalizeSearchText(token);
                const cv=this.withoutEnglishVowels(c);
                return hay.includes(token) || (c && compactHay.includes(c)) || (cv && hayNoVowels.includes(cv));
            });
            if(tokenMatch)return true;
        }
        if(compactQuery){
            let pos=0;
            const ordered=[...compactQuery].every(ch=>{
                const found=compactHay.indexOf(ch,pos);
                if(found<0)return false;
                pos=found+1;
                return true;
            });
            if(ordered)return true;
        }
        if(queryNoVowels){
            let pos=0;
            const ordered=[...queryNoVowels].every(ch=>{
                const found=hayNoVowels.indexOf(ch,pos);
                if(found<0)return false;
                pos=found+1;
                return true;
            });
            if(ordered)return true;
        }
        return false;
    }

    normalizeDateDigits(value){
        const arabic="٠١٢٣٤٥٦٧٨٩";
        const eastern="۰۱۲۳۴۵۶۷۸۹";
        return String(value||"").replace(/[٠-٩]/g,ch=>String(arabic.indexOf(ch))).replace(/[۰-۹]/g,ch=>String(eastern.indexOf(ch)));
    }

    parseDisplayDate(value){
        const raw=this.normalizeDateDigits(value).trim();
        if(!raw)return "";
        let text=raw.replace(/[\.\-\s]+/g,"/");
        let m=text.match(/^(\d{1,2})[\/](\d{1,2})[\/](\d{2}|\d{4})$/);
        if(m){
            const day=m[1].padStart(2,"0");
            const month=m[2].padStart(2,"0");
            let year=m[3];
            if(year.length===2){
                const yy=cint(year);
                year=String(yy>=70 ? 1900+yy : 2000+yy);
            }
            const iso=`${year}-${month}-${day}`;
            return this.isValidISODate(iso) ? iso : "";
        }
        m=raw.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
        if(m){
            const iso=`${m[1]}-${m[2].padStart(2,"0")}-${m[3].padStart(2,"0")}`;
            return this.isValidISODate(iso) ? iso : "";
        }
        return "";
    }

    isValidISODate(value){
        const m=String(value||"").match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if(!m)return false;
        const d=new Date(Number(m[1]),Number(m[2])-1,Number(m[3]));
        return d.getFullYear()===Number(m[1]) && d.getMonth()===Number(m[2])-1 && d.getDate()===Number(m[3]);
    }

    formatDateDisplay(value){
        const text=String(value||"").trim();
        const m=text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if(!m)return text;
        return `${m[3]}/${m[2]}/${m[1]}`;
    }

    openRecentDateRangeDialog(){
        const dialog=new frappe.ui.Dialog({
            title:__("Return Cases Date Range"),
            fields:[
                {label:__("From Date"),fieldname:"from_date",fieldtype:"Date",default:this.recentFromDate||""},
                {label:__("To Date"),fieldname:"to_date",fieldtype:"Date",default:this.recentToDate||""},
                {fieldtype:"HTML",fieldname:"hint",options:`<div class="prm-print-note">${__("You can use the calendar picker, or type dates like 1/4/26, 01/04/2026, or 2026-04-01.")}</div>`},
            ],
            primary_action_label:__("Apply"),
            primary_action:(values)=>{
                this.recentFromDate=this.parseDisplayDate(values.from_date||"") || (values.from_date||"");
                this.recentToDate=this.parseDisplayDate(values.to_date||"") || (values.to_date||"");
                this.setRecentDateControlValue("recent-from-date", this.recentFromDate);
                this.setRecentDateControlValue("recent-to-date", this.recentToDate);
                this.setRecentExpanded(true);
                dialog.hide();
                this.refreshRecent();
            }
        });
        dialog.show();
    }

    recentHaystack(row){
        return [
            row.name,row.posting_date,row.return_type,row.supplier,row.original_purchase_invoice,row.purchase_return,
            row.quarantine_stock_entry,row.handover_stock_entry,row.rejection_return_stock_entry,
            row.approved_debit_note,row.supplier_claim,row.refund_payment_entry,
            row.original_supplier_invoice_no,row.return_supplier_invoice_no,row.debit_note_supplier_invoice_no,
            row.operational_status,row.settlement_status
        ].map(v=>String(v||"").toLowerCase()).join(" | ");
    }

    getFilteredRecentCases(){
        const q=String(this.recentSearch||"").trim().toLowerCase();
        const filter=this.recentFilter||"open";
        return (this.recentCases||[]).filter(row=>{
            const closed=this.caseIsClosed(row);
            if(filter==="open" && closed) return false;
            if(filter==="closed" && !closed) return false;
            if(this.recentFromDate && String(row.posting_date||"") < this.recentFromDate) return false;
            if(this.recentToDate && String(row.posting_date||"") > this.recentToDate) return false;
            if(q && !this.smartMatchesSearch(row,q)) return false;
            return true;
        });
    }

    printDocument(doctype,name){
        if(!doctype||!name)return;
        this.showPrintOptions(doctype,name);
    }

    findCaseForPrint(doctype,name){
        const rows=this.recentCases||[];
        const fields=["name","purchase_return","quarantine_stock_entry","handover_stock_entry","rejection_return_stock_entry","approved_debit_note","supplier_claim","refund_payment_entry"];
        return rows.find(r=>fields.some(f=>String(r[f]||"")===String(name))) || (this.caseName===name?this.currentCaseAsRow():null);
    }

    currentCaseAsRow(){
        return {
            name:this.caseName, company:this.value("company"), posting_date:this.value("posting_date"), return_type:this.value("return_type"), supplier:this.value("supplier"),
            original_purchase_invoice:this.value("original_purchase_invoice"), purchase_return:this.purchaseReturn, quarantine_stock_entry:this.quarantineStockEntry,
            handover_stock_entry:this.handoverStockEntry, rejection_return_stock_entry:this.rejectionReturnStockEntry, approved_debit_note:this.approvedDebitNote,
            supplier_claim:this.supplierClaim, refund_payment_entry:this.refundPaymentEntry, operational_status:this.$main.find('[data-role="case-status"]').text(),
            settlement_status:this.settlementStatus, approved_return_value:this.approvedReturnValue, claim_deduction_amount:this.claimDeductionAmount,
            planned_claim_deduction_amount:this.plannedClaimDeduction, refund_amount:this.refundAmount, remaining_settlement_amount:this.remainingSettlementAmount,
            rejected_qty_destination:this.value("rejected_qty_destination"), rejected_destination_warehouse:this.value("rejected_destination_warehouse"),
            rejected_destruction_date:this.value("rejected_destruction_date"), rejected_destruction_reference:this.value("rejected_destruction_reference"),
            rejected_destruction_notes:this.value("rejected_destruction_notes")
        };
    }

    showPrintOptions(doctype,name){
        const row=this.findCaseForPrint(doctype,name) || this.currentCaseAsRow();
        const isCaseLike=Boolean(row) || doctype==="Pharmacy Return Case";
        if(!isCaseLike){
            this.printOfficialDocument(doctype,name,{paper_size:"A4",print_format:"Standard",no_letterhead:0});
            return;
        }
        const dialog=new frappe.ui.Dialog({
            title:__("Print Summary"),
            fields:[
                {fieldtype:"HTML",fieldname:"printer_note",options:`<div class="prm-print-note">${__("This prints a short operational summary, not the full ERPNext form. Printer selection still happens in the browser print dialog.")}</div>`},
                {label:__("Document"),fieldname:"document_label",fieldtype:"Data",read_only:1,default:`${row.name || name}`},
                {label:__("Summary Type"),fieldname:"print_mode",fieldtype:"Select",options:"Case Summary\nSupplier Handover Receipt\nSupplier Decision Summary\nFinancial Summary",default:(this.printMode && this.printMode!=="Official ERPNext Print View")?this.printMode:"Case Summary"},
                {label:__("Paper Size"),fieldname:"paper_size",fieldtype:"Select",options:"A4\nReceipt 80mm",default:this.printPaperSize||"A4"},
                {fieldtype:"HTML",fieldname:"official_hint",options:`<div class="prm-muted">${__("Use Open Document if you need the full official ERPNext print format.")}</div>`},
            ],
            primary_action_label:__("Print Summary"),
            primary_action:(values)=>{
                this.printPaperSize=values.paper_size||"A4";
                this.printMode=values.print_mode||"Case Summary";
                dialog.hide();
                this.printCaseSummary(row,values);
            }
        });
        dialog.show();
    }

    printOfficialDocument(doctype,name,opts={}){
        const format=opts.print_format||"Standard";
        const noLetterhead=cint(opts.no_letterhead)?1:0;
        const paperSize=opts.paper_size||"A4";
        const url="/printview?doctype="+encodeURIComponent(doctype)+"&name="+encodeURIComponent(name)+"&format="+encodeURIComponent(format)+"&no_letterhead="+noLetterhead+"&trigger_print=1&settings=%7B%7D&paper_size="+encodeURIComponent(paperSize);
        window.open(url,"_blank");
    }

    caseStageDocuments(row){
        return [
            [__("Original Purchase Invoice"),"Purchase Invoice",row.original_purchase_invoice],
            [__("Purchase Return"),"Purchase Invoice",row.purchase_return],
            [__("Quarantine Transfer"),"Stock Entry",row.quarantine_stock_entry],
            [__("Supplier Handover"),"Stock Entry",row.handover_stock_entry],
            [__("Rejected Qty Destination"),"Stock Entry",row.rejection_return_stock_entry],
            [__("Approved Debit Note"),"Purchase Invoice",row.approved_debit_note],
            [__("Supplier Claim"),"Supplier Claim",row.supplier_claim],
            [__("Supplier Refund"),"Payment Entry",row.refund_payment_entry],
        ].filter(d=>d[2]);
    }

    printHeaderTitle(row){
        return this.value("company") || (row&&row.company) || (frappe.boot&&frappe.boot.sysdefaults&&frappe.boot.sysdefaults.company) || "";
    }

    printRowsForCurrentCase(){
        return (this.caseName && Array.isArray(this.rows)) ? this.rows : [];
    }

    printCaseSummary(row,opts={}){
        const paper=opts.paper_size||"A4";
        const receipt=paper==="Receipt 80mm";
        const mode=opts.print_mode||"Case Summary";
        const w=window.open("","_blank");
        if(!w){frappe.msgprint(__("Please allow popups to print."));return;}
        const header=this.printHeaderTitle(row);
        const items=(this.caseName===row.name ? this.printRowsForCurrentCase() : []);
        const qtyOf=(r)=>flt(r.return_qty)||flt(r.delivered_qty)||flt(r.accepted_qty)||flt(r.recall_qty)||0;
        const compactItems=items.map((r,i)=>`<tr><td>${i+1}</td><td>${this.esc(r.item_name||r.item_code)}<div class="muted">${this.esc(r.item_code||"")}</div></td><td>${this.esc(r.batch_no||"—")}</td><td>${this.esc(r.expiry_date||"—")}</td><td>${qtyOf(r)}</td></tr>`).join("");
        const decisionItems=items.map((r,i)=>`<tr><td>${i+1}</td><td>${this.esc(r.item_name||r.item_code)}<div class="muted">${this.esc(r.item_code||"")}</div></td><td>${this.esc(r.batch_no||"—")}</td><td>${flt(r.delivered_qty)||flt(r.return_qty)}</td><td>${flt(r.accepted_qty)}</td><td>${flt(r.rejected_qty)}</td><td>${this.money(r.approved_total_credit||0)}</td></tr>`).join("");
        const stages=this.caseStageDocuments(row).map(d=>`<tr><td>${this.esc(d[0])}</td><td>${this.esc(d[2])}</td></tr>`).join("");
        const rejectedDestination=row.rejected_qty_destination||this.value("rejected_qty_destination")||"";
        const rejectedDestinationWarehouse=row.rejected_destination_warehouse||this.value("rejected_destination_warehouse")||"";
        const rejectedDestructionDate=row.rejected_destruction_date||this.value("rejected_destruction_date")||"";
        const rejectedDestinationText=[rejectedDestination,rejectedDestinationWarehouse||rejectedDestructionDate].filter(Boolean).join(" → ");
        const title = mode==="Supplier Handover Receipt" ? __("Supplier Handover Receipt") : mode==="Supplier Decision Summary" ? __("Supplier Decision Summary") : mode==="Financial Summary" ? __("Financial Summary") : __("Purchase Return Case Summary");
        let body="";
        if(mode==="Supplier Handover Receipt"){
            body=`<div class="meta"><div class="box"><b>${__("Case")}</b><br>${this.esc(row.name||"")}</div><div class="box"><b>${__("Supplier")}</b><br>${this.esc(row.supplier||"")}</div><div class="box"><b>${__("Date")}</b><br>${this.esc(this.formatDateDisplay(row.posting_date)||"")}</div></div>
            <div class="section"><h3>${__("Delivered Items")}</h3><table><tr><th>#</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Expiry")}</th><th>${__("Qty")}</th></tr>${compactItems||`<tr><td colspan="5">${__("No loaded item rows on this page.")}</td></tr>`}</table></div>
            <div class="signature"><div>${__("Receiver Name / Signature")}: __________________</div><div>${__("Pharmacy Signature")}: __________________</div></div>`;
        }else if(mode==="Supplier Decision Summary"){
            body=`<div class="meta"><div class="box"><b>${__("Case")}</b><br>${this.esc(row.name||"")}</div><div class="box"><b>${__("Supplier")}</b><br>${this.esc(row.supplier||"")}</div><div class="box"><b>${__("Status")}</b><br>${this.esc(row.operational_status||"")}</div></div>
            ${rejectedDestinationText?`<div class="section"><h3>${__("Rejected Qty Destination")}</h3><table><tr><th>${__("Destination")}</th><th>${__("Reference / Notes")}</th></tr><tr><td>${this.esc(rejectedDestinationText)}</td><td>${this.esc(row.rejected_destruction_reference||this.value("rejected_destruction_reference")||row.rejected_destruction_notes||this.value("rejected_destruction_notes")||"—")}</td></tr></table></div>`:""}
            <div class="section"><h3>${__("Supplier Decision")}</h3><table><tr><th>#</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Handover")}</th><th>${__("Accepted")}</th><th>${__("Rejected")}</th><th>${__("Approved")}</th></tr>${decisionItems||`<tr><td colspan="7">${__("No loaded item rows on this page.")}</td></tr>`}</table></div>`;
        }else if(mode==="Financial Summary"){
            body=`<div class="meta"><div class="box"><b>${__("Case")}</b><br>${this.esc(row.name||"")}</div><div class="box"><b>${__("Supplier")}</b><br>${this.esc(row.supplier||"")}</div><div class="box"><b>${__("Settlement")}</b><br>${this.esc(row.settlement_status||"")}</div></div>
            <div class="section"><table><tr><th>${__("Approved Value")}</th><th>${__("Claim Deduction")}</th><th>${__("Refund")}</th><th>${__("Remaining")}</th></tr><tr><td>${this.money(row.approved_return_value)}</td><td>${this.money(row.claim_deduction_amount||row.planned_claim_deduction_amount)}</td><td>${this.money(row.refund_amount)}</td><td>${this.money(row.remaining_settlement_amount)}</td></tr></table></div>
            ${stages?`<div class="section"><h3>${__("Linked Documents")}</h3><table><tr><th>${__("Stage")}</th><th>${__("Document")}</th></tr>${stages}</table></div>`:""}`;
        }else{
            body=`<div class="meta"><div class="box"><b>${__("Case")}</b><br>${this.esc(row.name||"")}</div><div class="box"><b>${__("Type")}</b><br>${this.esc(row.return_type||"")}</div><div class="box"><b>${__("Supplier")}</b><br>${this.esc(row.supplier||"")}</div><div class="box"><b>${__("Status")}</b><br>${this.esc(row.operational_status||"")}</div></div>
            <div class="section"><h3>${__("Items")}</h3><table><tr><th>#</th><th>${__("Item")}</th><th>${__("Batch")}</th><th>${__("Expiry")}</th><th>${__("Qty")}</th></tr>${compactItems||`<tr><td colspan="5">${__("No loaded item rows on this page.")}</td></tr>`}</table></div>
            <div class="section"><h3>${__("Financial")}</h3><table><tr><th>${__("Approved")}</th><th>${__("Claim")}</th><th>${__("Refund")}</th><th>${__("Remaining")}</th></tr><tr><td>${this.money(row.approved_return_value)}</td><td>${this.money(row.claim_deduction_amount||row.planned_claim_deduction_amount)}</td><td>${this.money(row.refund_amount)}</td><td>${this.money(row.remaining_settlement_amount)}</td></tr></table></div>
            ${stages?`<div class="section"><h3>${__("Documents")}</h3><table><tr><th>${__("Stage")}</th><th>${__("Document")}</th></tr>${stages}</table></div>`:""}`;
        }
        const pageCss=receipt ? "80mm 200mm" : "A4 portrait";
        const html=`<!doctype html><html><head><meta charset="utf-8"><title>${this.esc(row.name||"Return Case")}</title><style>
            @page{size:${pageCss};margin:${receipt?"3mm":"12mm"};}
            html,body{font-family:Arial,sans-serif;color:#111;margin:0;font-size:${receipt?"10.5px":"13px"};width:${receipt?"74mm":"auto"};max-width:${receipt?"74mm":"none"};}
            body{padding:${receipt?"2mm":"0"};box-sizing:border-box;}
            h2,h3{margin:0 0 7px;line-height:1.2}.muted{color:#666;font-size:${receipt?"9px":"12px"}}.section{margin-top:${receipt?"8px":"12px"}}.line{border-top:1px solid #ddd;margin:7px 0}
            table{width:100%;border-collapse:collapse;margin-top:5px;table-layout:${receipt?"fixed":"auto"}}th,td{border:1px solid #ddd;padding:${receipt?"2px":"6px"};text-align:left;vertical-align:top;word-break:break-word}th{background:#f5f5f5}
            .meta{display:grid;grid-template-columns:${receipt?"1fr":"repeat(4,1fr)"};gap:${receipt?"4px":"6px"}}.box{border:1px solid #ddd;padding:${receipt?"4px":"6px"};border-radius:6px}.signature{display:grid;grid-template-columns:${receipt?"1fr":"1fr 1fr"};gap:24px;margin-top:22px}
            @media screen{body{margin:${receipt?"0 auto":"0"};}.print-paper-note{display:block;color:#777;font-size:11px;margin-bottom:6px}}@media print{.print-paper-note{display:none}}
        </style></head><body onload="setTimeout(function(){window.focus();window.print();},300)">
            ${receipt?`<div class="print-paper-note">${this.esc(__("Receipt 80mm layout. In the browser print dialog, choose the 80mm receipt printer/paper if it is not selected automatically."))}</div>`:""}
            <h2>${this.esc(header)}</h2><h3>${title}</h3><div class="muted">${this.esc(this.formatDateDisplay(row.posting_date)||"")}</div><div class="line"></div>${body}
        </body></html>`;
        w.document.open();w.document.write(html);w.document.close();
    }

    printMenu(row){
        const docs=[
            ["Pharmacy Return Case",row.name,__("Print Case")],
            ["Purchase Invoice",row.purchase_return,__("Print Purchase Return")],
            ["Stock Entry",row.quarantine_stock_entry,__("Print Quarantine Transfer")],
            ["Stock Entry",row.handover_stock_entry,__("Print Supplier Handover")],
            ["Stock Entry",row.rejection_return_stock_entry,__("Print Rejected Qty Return")],
            ["Purchase Invoice",row.approved_debit_note,__("Print Approved Debit Note")],
            ["Supplier Claim",row.supplier_claim,__("Print Supplier Claim")],
            ["Payment Entry",row.refund_payment_entry,__("Print Supplier Refund")],
        ].filter(d=>d[1]);
        const links=docs.length?docs.map(d=>`<a data-action="print-doc" data-doctype="${this.esc(d[0])}" data-name="${this.esc(d[1])}">${this.esc(d[2])}</a>`).join(""):`<a class="disabled">${__("No printable document yet")}</a>`;
        return `<div class="prm-print-dropdown"><button type="button" class="btn btn-default btn-xs" data-action="toggle-print-menu">${__("Print")}</button><div class="prm-print-menu">${links}</div></div>`;
    }

    renderRecent(rows=null){
        if(Array.isArray(rows)) this.recentCases=rows;
        this.$main.find('[data-role="recent-filter"]').val(this.recentFilter||"open");
        this.$main.find('[data-role="recent-search"]').val(this.recentSearch||"");
        this.makeRecentDateControls();
        this.setRecentDateControlValue("recent-from-date", this.recentFromDate);
        this.setRecentDateControlValue("recent-to-date", this.recentToDate);
        const openCount=(this.recentCases||[]).filter(r=>!this.caseIsClosed(r)).length;
        const closedCount=(this.recentCases||[]).filter(r=>this.caseIsClosed(r)).length;
        this.$main.find('[data-role="recent-open-count"]').text(openCount);
        this.$main.find('[data-role="recent-closed-count"]').text(closedCount);
        this.setRecentExpanded(this.recentExpanded);
        const filtered=this.getFilteredRecentCases();
        const $h=this.$main.find('[data-role="recent"]');
        if(!filtered.length){$h.html(`<div class="prm-empty">${__("No return cases match the current filter.")}</div>`);return;}
        $h.html(`<div class="prm-table-wrap"><table class="prm-recent"><thead><tr><th>${__("Case")}</th><th>${__("Date")}</th><th>${__("Receiving Company")}</th><th>${__("Supplier Invoice No")}</th><th>${__("Debit Note")}</th><th>${__("Supplier Claim")}</th><th>${__("Refund Payment")}</th><th>${__("Operational Status")}</th><th>${__("Settlement Status")}</th><th>${__("Approved Value")}</th><th>${__("Claim Deduction")}</th><th>${__("Refund")}</th><th>${__("Remaining")}</th><th>${__("Actions")}</th></tr></thead><tbody>${filtered.map(r=>{
            const debitNote=r.approved_debit_note||r.purchase_return||"—";
            const claim=r.supplier_claim||"—";
            const refund=r.refund_payment_entry||"—";
            const supplierInvoice=[r.original_supplier_invoice_no,r.return_supplier_invoice_no,r.debit_note_supplier_invoice_no].filter(Boolean).join(" / ")||"—";
            const caseClosed=this.caseIsClosed(r);
            return `<tr><td><strong>${this.esc(r.name)}</strong><div class="prm-supplier-invoice">${this.esc(r.return_type||"")}</div></td><td>${this.esc(this.formatDateDisplay(r.posting_date)||"")}</td><td>${this.esc(r.supplier||"")}</td><td>${this.esc(supplierInvoice)}</td><td>${debitNote!=="—"?`<span class="prm-link" data-action="open-recent-debit-note" data-name="${this.esc(debitNote)}">${this.esc(debitNote)}</span>`:this.esc(debitNote)}</td><td>${r.supplier_claim?`<span class="prm-link" data-action="open-recent-claim" data-name="${this.esc(claim)}">${this.esc(claim)}</span>`:this.esc(claim)}</td><td>${r.refund_payment_entry?`<span class="prm-link" data-action="open-recent-refund" data-name="${this.esc(refund)}">${this.esc(refund)}</span>`:this.esc(refund)}</td><td>${this.esc(r.operational_status||"")}<div class="prm-supplier-invoice">${caseClosed?__("Closed"):__("Open / Needs Closing")}</div></td><td>${this.esc(["Regulatory Batch Recall","Expired Drugs Return"].includes(r.return_type)&&!r.approved_debit_note?__("Not Applicable Yet"):(r.settlement_status||"Pending Settlement"))}</td><td>${this.money(r.approved_return_value)}</td><td>${this.money(r.claim_deduction_amount||r.planned_claim_deduction_amount)}</td><td>${this.money(r.refund_amount)}</td><td>${this.money(r.remaining_settlement_amount)}</td><td><div class="prm-actions" style="justify-content:flex-start;min-width:300px"><button type="button" class="btn btn-primary btn-xs" data-action="open-case-page" data-name="${this.esc(r.name)}">${__("Open in Page")}</button><button type="button" class="btn btn-default btn-xs" data-action="open-case-document" data-name="${this.esc(r.name)}">${__("Open Document")}</button>${this.printMenu(r)}</div></td></tr>`;
        }).join("")}</tbody></table></div>`);
    }

    async newCase(){
        this.caseName=null;this.purchaseReturn=null;this.purchaseReturnDocstatus=null;this.purchaseReturnStatus=null;this.quarantineStockEntry=null;this.handoverStockEntry=null;this.rejectionReturnStockEntry=null;this.rejectedQtyDestination="";this.rejectedDestinationWarehouse="";this.approvedDebitNote=null;this.approvedDebitNoteDocstatus=null;this.approvedDebitNoteStatus=null;this.approvedDebitNoteAmount=0;this.approvedDebitNoteOutstanding=0;this.supplierClaim=null;this.supplierClaimDocstatus=null;this.supplierClaimStatus=null;this.supplierClaimAccountingStatus=null;this.settlementStatus="Pending Settlement";this.claimUtilizationStatus="Not Applied";this.claimSettlementDate=null;this.plannedClaimDeduction=0;this.claimDeductionAmount=0;this.settledAmount=0;this.remainingSettlementAmount=0;this.approvedReturnValue=0;this.refundPaymentEntry=null;this.refundPaymentEntryStatus=null;this.refundPaymentEntryDocstatus=null;this.refundAmount=0;this.refundEntriesCount=0;this.hasOpenRefundDraft=false;this.refundPayments=[];this.quarantineDocstatus=null;this.handoverDocstatus=null;this.rejectionReturnDocstatus=null;this.rows=[];
        await this.setReturnType("Return Against Invoice",false);
        await this.setValue("supplier","");await this.setValue("supplier_credit_note_no","");await this.setValue("supplier_credit_note_date","");await this.setValue("supplier_credit_note_attachment","");await this.setValue("original_purchase_invoice","");await this.setValue("return_item_to_add","");await this.setValue("return_batch_no_to_add","");await this.setValue("settlement_method","Pending Settlement");await this.setValue("authority_notification_no","");await this.setValue("authority_notification_date","");await this.setValue("authority_notification_attachment","");await this.setValue("recall_item_code","");await this.setValue("recall_batch_no","");await this.setValue("recall_source_warehouse","");await this.applyCompanyDefaults();await this.setValue("remarks","");await this.setValue("supplier_claim","");await this.setValue("refund_posting_date",frappe.datetime.get_today());await this.setValue("refund_mode_of_payment","");await this.setValue("refund_account","");await this.setValue("refund_request_amount","");await this.setValue("refund_reference_no","");await this.setValue("refund_reference_date","");await this.setValue("refund_notes","");await this.setValue("rejected_qty_destination","");await this.setValue("rejected_destination_warehouse","");await this.setValue("rejected_destruction_date","");await this.setValue("rejected_destruction_reference","");await this.setValue("rejected_destruction_attachment","");await this.setValue("rejected_destruction_notes","");await this.setValue("case_reference","");
        this.$main.find('[data-role="case-status"]').text(__("New Case"));this.$main.find('[data-role="invoice-summary"]').text("");this.renderItems();this.syncButtons();this.refreshProgressiveUI();
    }
}
