frappe.pages["pharmacy-inventory-count-workstation"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Pharmacy Inventory Count",
        single_column: true
    });

    frappe.require([
        "/assets/pharma_erp/css/inventory_count/inventory_count.css",
        "/assets/pharma_erp/js/inventory_count/app.js"
    ], function () {
        page.main.empty();
        Promise.resolve(PharmacyInventoryCountApp.init(page.main)).catch((error) => {
            console.error(error);
            frappe.msgprint({
                title: __("Inventory Count Error"),
                message: frappe.utils.escape_html(String(error?.message || error)),
                indicator: "red"
            });
        });
    });
};
