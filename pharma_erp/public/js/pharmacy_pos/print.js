window.PrintManager = {
    init() {
        this.reprintButton = document.getElementById("btn-reprint");
        const settings = PharmacyPOS.state.settings || {};
        const info = document.getElementById("pos-print-info");
        if (info) {
            const format = settings.default_print_format || "Standard";
            const width = settings.receipt_paper_width || "80 mm";
            info.textContent = `${format} • ${width}`;
        }
        if (this.reprintButton) {
            this.reprintButton.classList.toggle("is-hidden", !cint(settings.enable_reprint ?? 1));
            this.reprintButton.addEventListener("click", () => this.openReprint());
        }
    },

    printUrl(invoice, triggerPrint = true) {
        const settings = PharmacyPOS.state.settings || {};
        const params = new URLSearchParams({
            doctype: "Sales Invoice",
            name: invoice,
            trigger_print: triggerPrint ? "1" : "0"
        });
        if (settings.default_print_format) params.set("format", settings.default_print_format);
        return `/printview?${params.toString()}`;
    },

    printInvoice(invoice, triggerPrint = true) {
        if (!invoice) return;
        window.open(this.printUrl(invoice, triggerPrint), "_blank");
    },

    async openReprint() {
        if (!cint(PharmacyPOS.state.settings.enable_reprint ?? 1)) return;
        const dialog = new frappe.ui.Dialog({
            title: __("Reprint Sales Invoice"),
            size: "extra-large",
            fields: [{ fieldtype: "HTML", fieldname: "reprint_html" }],
            primary_action_label: __("Print Selected"),
            primary_action: () => {
                const root = dialog.get_field("reprint_html").$wrapper[0];
                const selected = [...root.querySelectorAll(".reprint-select:checked")].map(input => input.value);
                if (!selected.length) {
                    frappe.msgprint(__("Select at least one invoice."));
                    return;
                }
                selected.forEach(invoice => this.printInvoice(invoice, true));
                dialog.hide();
            }
        });
        dialog.show();
        const wrapper = dialog.get_field("reprint_html").$wrapper;
        wrapper.html(`
            <div class="reprint-shell">
                <div class="reprint-toolbar">
                    <input id="reprint-search" class="form-control" placeholder="Invoice, customer, mobile, date or amount">
                    <span>Format: <strong>${frappe.utils.escape_html(PharmacyPOS.state.settings.default_print_format || "Standard")}</strong></span>
                    <span>Copies: <strong>${cint(PharmacyPOS.state.settings.default_print_copies || 1)}</strong></span>
                </div>
                <div id="reprint-results"><div class="loading-state">Loading invoices...</div></div>
            </div>`);
        const root = wrapper[0];
        const input = root.querySelector("#reprint-search");
        const search = frappe.utils.debounce(() => this.searchReprint(dialog, input.value), 250);
        input.addEventListener("input", search);
        input.addEventListener("keydown", event => {
            if (event.key === "Enter") { event.preventDefault(); this.searchReprint(dialog, input.value); }
        });
        await this.searchReprint(dialog, "");
        input.focus();
    },

    async searchReprint(dialog, text) {
        const root = dialog.get_field("reprint_html").$wrapper[0];
        const holder = root.querySelector("#reprint-results");
        holder.innerHTML = '<div class="loading-state">Loading invoices...</div>';
        const rows = await PharmacyAPI.searchSalesInvoices(text || "", "", 50) || [];
        if (!rows.length) {
            holder.innerHTML = '<div class="empty-state">No invoices found.</div>';
            return;
        }
        holder.innerHTML = `<table class="table table-bordered compact-table reprint-table">
            <thead><tr><th><input id="reprint-select-all" type="checkbox"></th><th>Invoice</th><th>Customer</th><th>Date</th><th>Total</th><th>Outstanding</th><th></th></tr></thead>
            <tbody>${rows.map(row => `<tr>
                <td><input class="reprint-select" type="checkbox" value="${frappe.utils.escape_html(row.name)}"></td>
                <td><strong>${frappe.utils.escape_html(row.name)}</strong></td>
                <td>${frappe.utils.escape_html(row.customer_name || row.customer || "")}</td>
                <td>${frappe.utils.escape_html(row.posting_date || "")}</td>
                <td>${format_currency(row.grand_total || 0)}</td>
                <td>${format_currency(row.outstanding_amount || 0)}</td>
                <td><button class="btn btn-sm btn-default reprint-preview" data-invoice="${frappe.utils.escape_html(row.name)}">Preview</button></td>
            </tr>`).join("")}</tbody>
        </table>`;
        holder.querySelector("#reprint-select-all")?.addEventListener("change", event => {
            holder.querySelectorAll(".reprint-select").forEach(input => { input.checked = event.target.checked; });
        });
        holder.querySelectorAll(".reprint-preview").forEach(button => button.addEventListener("click", () => this.printInvoice(button.dataset.invoice, false)));
    }
};
