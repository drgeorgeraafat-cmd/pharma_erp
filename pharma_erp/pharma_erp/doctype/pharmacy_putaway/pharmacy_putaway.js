const LOCATION_ITEM_SEARCH_QUERY =
    "pharma_erp.pharma_erp.location_item_search.search_items";

frappe.ui.form.on("Pharmacy Putaway", {
    setup(frm) {
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
