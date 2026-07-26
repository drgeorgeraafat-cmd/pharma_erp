frappe.ui.form.on("Internal Retail Price Lot", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Print Barcode / QR Label"), () => {
                if (typeof pharma_print_stock_source_label === "function") {
                    pharma_print_stock_source_label("retail_lot", frm.doc.name);
                    return;
                }
                frappe.call({
                    method: "pharma_erp.pharma_erp.page.pharmacy_pos.api.get_stock_source_label_data",
                    args: { source_type: "retail_lot", source_name: frm.doc.name },
                    callback: response => {
                        const data = response.message;
                        if (!data) return;
                        const popup = window.open("", "_blank", "width=520,height=720");
                        if (!popup) return frappe.msgprint(__("Allow pop-ups to print the label."));
                        popup.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${frappe.utils.escape_html(data.source_name)}</title><style>@page{size:58mm 40mm;margin:2mm}body{font-family:Arial;margin:0}.label{width:54mm;display:grid;grid-template-columns:1fr 18mm;gap:2mm}.qr{width:18mm;height:18mm}.barcode svg{width:100%;height:11mm}.price{font-size:14pt;font-weight:700}.meta,.code{font-size:8pt}.code{word-break:break-all;text-align:center}@media print{button{display:none}}</style></head><body><div class="label"><div><strong>${frappe.utils.escape_html(data.item_name)}</strong><div class="meta">${frappe.utils.escape_html(data.source_label)}: ${frappe.utils.escape_html(data.source_name)}</div><div class="price">${format_currency(data.retail_price || 0)}</div><div class="barcode">${data.barcode_svg || ""}</div><div class="code">${frappe.utils.escape_html(data.barcode_value || "")}</div></div><div>${data.qr_data_uri ? `<img class="qr" src="${data.qr_data_uri}">` : ""}<div class="code">${frappe.utils.escape_html(data.qr_value || "")}</div></div></div><button onclick="window.print()">${__("Print")}</button><script>window.onload=()=>setTimeout(()=>window.print(),250);<\/script></body></html>`);
                        popup.document.close();
                    }
                });
            }, __("Pharmacy"));
        }
    }
});
