const LOCATION_ITEM_SEARCH_QUERY =
    "pharma_erp.pharma_erp.location_item_search.search_items";

frappe.ui.form.on("Pharmacy Item Location Rule", {
    setup(frm) {
        frm.set_query("item_code", () => ({
            query: LOCATION_ITEM_SEARCH_QUERY
        }));

        frm.set_query("primary_location", () => ({
            filters: {
                warehouse: frm.doc.warehouse || "",
                disabled: 0
            }
        }));

        frm.set_query("overflow_location", () => ({
            filters: {
                warehouse: frm.doc.warehouse || "",
                disabled: 0
            }
        }));
    }
});
