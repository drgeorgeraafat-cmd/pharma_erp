window.HoldManager = {
    init() {
        this.holdButton = document.getElementById("btn-hold");
        this.recallButton = document.getElementById("btn-recall");
        this.holdButton?.addEventListener("click", () => InvoiceManager.save(false, { hold: true, clearAfter: true }));
        this.recallButton?.addEventListener("click", () => this.openRecall());
    },

    async openRecall() {
        const rows = await PharmacyAPI.searchHeldInvoices(100) || [];
        const dialog = new frappe.ui.Dialog({
            title: __("Recall Held Invoice"),
            size: "large",
            fields: [{ fieldtype: "HTML", fieldname: "held_html" }]
        });
        dialog.show();
        const wrapper = dialog.get_field("held_html").$wrapper;
        wrapper.html(rows.length ? `
            <div class="held-list">${rows.map((row, index) => `
                <button class="held-card" data-index="${index}">
                    <div><strong>${frappe.utils.escape_html(row.name)}</strong><small>${frappe.utils.escape_html(row.modified || "")}</small></div>
                    <div><span>${frappe.utils.escape_html(row.customer_name || row.customer || "")}</span><strong>${format_currency(row.grand_total || 0)}</strong></div>
                </button>`).join("")}</div>` : '<div class="empty-state">No held invoices.</div>');
        wrapper.find("[data-index]").on("click", async event => {
            const index = cint(event.currentTarget.dataset.index);
            const data = await PharmacyAPI.getHeldInvoice(rows[index].name);
            await InvoiceManager.loadDraft(data);
            dialog.hide();
        });
    }
};
