const LOCATION_ITEM_SEARCH_QUERY =
    "pharma_erp.pharma_erp.location_item_search.search_items";

frappe.ui.form.on("Pharmacy Location Transfer", {
    setup(frm) {
        frm.set_query("from_location", "items", () => ({
            filters: {
                warehouse: frm.doc.warehouse || "",
                disabled: 0
            }
        }));
        frm.set_query("to_location", "items", () => ({
            filters: {
                warehouse: frm.doc.warehouse || "",
                disabled: 0
            }
        }));
        frm.set_query("item_code", "items", () => ({
            query: LOCATION_ITEM_SEARCH_QUERY
        }));
    }
});

frappe.ui.form.on("Pharmacy Location Transfer Item", {
    from_location: show_available,
    item_code: show_available,
    batch_no: show_available
});

function show_available(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!frm.doc.warehouse || !row.from_location || !row.item_code) return;

    frappe.call({
        method: "pharma_erp.pharma_erp.location_service.get_location_qty",
        args: {
            warehouse: frm.doc.warehouse,
            location: row.from_location,
            item_code: row.item_code,
            batch_no: row.batch_no || null
        },
        callback(r) {
            if (r.message) {
                frappe.show_alert({
                    message: __("Available at source: {0}", [r.message.qty]),
                    indicator: "blue"
                }, 4);
            }
        }
    });
}
