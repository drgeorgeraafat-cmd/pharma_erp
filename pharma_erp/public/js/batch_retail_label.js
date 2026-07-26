function pharma_print_stock_source_label(sourceType, sourceName) {
    frappe.call({
        method: "pharma_erp.pharma_erp.page.pharmacy_pos.api.get_stock_source_label_data",
        args: { source_type: sourceType, source_name: sourceName },
        freeze: true,
        freeze_message: __("Preparing label..."),
        callback: response => {
            const data = response.message;
            if (!data) return;
            const popup = window.open("", "_blank", "width=520,height=720");
            if (!popup) {
                frappe.msgprint(__("Allow pop-ups to print the label."));
                return;
            }
            const expiry = data.expiry_date
                ? `<div><strong>${__("Expiry")}:</strong> ${frappe.utils.escape_html(data.expiry_date)}</div>`
                : "";
            const qr = data.qr_data_uri
                ? `<img class="qr" src="${data.qr_data_uri}" alt="QR">`
                : "";
            popup.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${frappe.utils.escape_html(data.source_name)}</title>
                <style>
                    @page { size: 58mm 40mm; margin: 2mm; }
                    body { font-family: Arial, sans-serif; margin: 0; color: #111; }
                    .label { width: 54mm; min-height: 36mm; display: grid; grid-template-columns: 1fr 18mm; gap: 2mm; align-items: center; }
                    h1 { font-size: 11pt; margin: 0 0 1mm; }
                    .meta { font-size: 8pt; line-height: 1.35; }
                    .price { font-size: 14pt; font-weight: 700; margin: 1mm 0; }
                    .barcode svg { width: 100%; height: 11mm; }
                    .code { font-size: 7pt; text-align: center; letter-spacing: .5px; word-break: break-all; }
                    .qr { width: 18mm; height: 18mm; image-rendering: pixelated; }
                    @media print { .print-btn { display: none; } }
                </style></head><body>
                <div class="label">
                    <div>
                        <h1>${frappe.utils.escape_html(data.item_name)}</h1>
                        <div class="meta"><strong>${frappe.utils.escape_html(data.source_label)}:</strong> ${frappe.utils.escape_html(data.source_name)}</div>
                        <div class="meta"><strong>${__("Item")}:</strong> ${frappe.utils.escape_html(data.item_code)}</div>
                        ${expiry}
                        <div class="price">${format_currency(data.retail_price || 0)}</div>
                        <div class="barcode">${data.barcode_svg || ""}</div>
                        <div class="code">${frappe.utils.escape_html(data.barcode_value || "")}</div>
                    </div>
                    <div>${qr}<div class="code">${frappe.utils.escape_html(data.qr_value || "")}</div></div>
                </div>
                <button class="print-btn" onclick="window.print()">${__("Print")}</button>
                <script>window.onload=()=>setTimeout(()=>window.print(),250);<\/script>
                </body></html>`);
            popup.document.close();
        }
    });
}

frappe.ui.form.on("Batch", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Print Barcode / QR Label"), () => {
                pharma_print_stock_source_label("batch", frm.doc.name);
            }, __("Pharmacy"));
        }
    }
});
