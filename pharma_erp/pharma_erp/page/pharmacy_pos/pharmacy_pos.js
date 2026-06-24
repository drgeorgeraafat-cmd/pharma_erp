frappe.pages["pharmacy-pos"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Pharmacy POS",
        single_column: true
    });

    frappe.require([
        "/assets/pharma_erp/css/pharmacy_pos/pharmacy_pos.css",
        "/assets/pharma_erp/js/pharmacy_pos/api.js",
        "/assets/pharma_erp/js/pharmacy_pos/ui.js",
        "/assets/pharma_erp/js/pharmacy_pos/header.js",
        "/assets/pharma_erp/js/pharmacy_pos/search.js",
        "/assets/pharma_erp/js/pharmacy_pos/customer.js",
        "/assets/pharma_erp/js/pharmacy_pos/invoice.js",
        "/assets/pharma_erp/js/pharmacy_pos/payment.js",
        "/assets/pharma_erp/js/pharmacy_pos/delivery.js",
        "/assets/pharma_erp/js/pharmacy_pos/returns.js",
        "/assets/pharma_erp/js/pharmacy_pos/history.js",
        "/assets/pharma_erp/js/pharmacy_pos/item_info.js",
        "/assets/pharma_erp/js/pharmacy_pos/item_hover.js",
        "/assets/pharma_erp/js/pharmacy_pos/hold.js",
        "/assets/pharma_erp/js/pharmacy_pos/print.js",
        "/assets/pharma_erp/js/pharmacy_pos/screen.js",
        "/assets/pharma_erp/js/pharmacy_pos/shortcuts.js"
    ], function () {
        page.main.empty();
        Promise.resolve(PharmacyPOS.init(page.main)).then(() => {
            open_return_from_query();
        });
    });
};

function wait_for_element(getter, timeout = 12000, interval = 100) {
    return new Promise((resolve, reject) => {
        const started = Date.now();
        const check = () => {
            const value = getter();
            if (value) return resolve(value);
            if (Date.now() - started >= timeout) {
                return reject(new Error("Timed out waiting for Pharmacy POS return dialog."));
            }
            setTimeout(check, interval);
        };
        check();
    });
}

async function open_return_from_query() {
    const url = new URL(window.location.href);
    const invoice = (url.searchParams.get("return_invoice") || "").trim();
    const returnRequest = (url.searchParams.get("return_request") || "").trim();
    if (!invoice) return;
    window.__pharmacy_pos_return_request = returnRequest;

    // Remove one-time parameters before opening the dialog so refresh/back does
    // not repeatedly create another return workflow.
    url.searchParams.delete("return_invoice");
    url.searchParams.delete("delivery_return");
    url.searchParams.delete("return_request");
    window.history.replaceState({}, document.title, `${url.pathname}${url.search}${url.hash}`);

    try {
        await wait_for_element(() => window.ReturnsManager && typeof ReturnsManager.open === "function");
        await ReturnsManager.open({ returnRequest });

        const input = await wait_for_element(() => {
            return [...document.querySelectorAll("#return-invoice-search")]
                .find((element) => element.offsetParent !== null);
        });
        input.value = invoice;

        const root = input.closest(".modal") || document;
        const searchButton = root.querySelector("#return-search-btn");
        if (!searchButton) throw new Error("Return search button was not found.");
        searchButton.click();

        const option = await wait_for_element(() => {
            return [...root.querySelectorAll(".return-invoice-option")].find((button) => {
                const name = button.querySelector("strong")?.textContent?.trim() || "";
                return name === invoice;
            });
        });
        option.click();
        frappe.show_alert({
            message: `تم فتح مرتجع الفاتورة ${frappe.utils.escape_html(invoice)}`,
            indicator: "green"
        });
    } catch (error) {
        console.error(error);
        frappe.msgprint({
            title: __("تعذر فتح المرتجع تلقائيًا"),
            indicator: "red",
            message: __("افتح نافذة Sales Return وابحث عن الفاتورة {0} يدويًا.", [invoice])
        });
    }
}
