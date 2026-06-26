function sync_purchase_entry_mode(frm) {
    if (
        frm.doc.custom_purchase_entry_mode === "Quick Invoice & Receipt" &&
        !frm.doc.update_stock
    ) {
        return frm.set_value("update_stock", 1);
    }
    return Promise.resolve();
}

async function sync_supplier_payment_classification(frm, force = false) {
    if (!frm.doc.supplier) {
        if (force) {
            await frm.set_value("custom_payment_classification", "");
            await frm.set_value("custom_exclude_from_supplier_claim", 0);
        }
        return;
    }

    if (!force && frm.doc.custom_payment_classification) {
        return;
    }

    const r = await frappe.db.get_value(
        "Supplier",
        frm.doc.supplier,
        [
            "custom_purchase_supplier_type",
            "custom_purchase_payment_model",
            "custom_exclude_cash_invoices_from_claim",
        ]
    );

    const supplier = (r && r.message) || {};
    let classification = "";

    if (supplier.custom_purchase_payment_model === "Cash") {
        classification = "Cash Invoice";
    } else if (
        supplier.custom_purchase_payment_model === "Credit Claim" ||
        supplier.custom_purchase_payment_model === "Mixed"
    ) {
        classification = "Claim Invoice";
    } else if (supplier.custom_purchase_supplier_type === "Distribution Company") {
        classification = "Claim Invoice";
    }

    if (classification) {
        await frm.set_value("custom_payment_classification", classification);
    }

    if (classification === "Cash Invoice") {
        await frm.set_value(
            "custom_exclude_from_supplier_claim",
            supplier.custom_exclude_cash_invoices_from_claim ? 1 : 0
        );
    } else if (classification === "Claim Invoice") {
        await frm.set_value("custom_exclude_from_supplier_claim", 0);
    }
}

function make_printed_retail_price_editable(frm) {
    if (!frm.fields_dict.items || !frm.fields_dict.items.grid) return;
    const field = frm.fields_dict.items.grid.get_field("custom_selling_price");
    if (!field) return;
    field.df.read_only = frm.doc.docstatus === 0 ? 0 : 1;
    frm.fields_dict.items.grid.refresh();
}

async function populate_printed_retail_price(cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row || !row.item_code || flt(row.custom_selling_price)) return;

    const r = await frappe.db.get_value(
        "Item",
        row.item_code,
        "custom_customer_price"
    );
    const currentPrice = flt(
        r && r.message ? r.message.custom_customer_price : 0
    );
    if (currentPrice) {
        await frappe.model.set_value(
            cdt,
            cdn,
            "custom_selling_price",
            currentPrice
        );
    }
}

async function calculate_pharmacy_purchase_rate(cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row) return;

    if (row.custom_is_bonus_item) {
        const printedPrice = flt(row.custom_selling_price);
        await frappe.model.set_value(cdt, cdn, "is_free_item", 1);
        await frappe.model.set_value(cdt, cdn, "custom_supplier_discount_percentage", 0);
        await frappe.model.set_value(cdt, cdn, "custom_additional_discount", 0);
        await frappe.model.set_value(cdt, cdn, "custom_effective_discount_percentage", 100);
        await frappe.model.set_value(cdt, cdn, "discount_percentage", 100);
        await frappe.model.set_value(cdt, cdn, "discount_amount", printedPrice);
        await frappe.model.set_value(cdt, cdn, "rate", 0);
        await frappe.model.set_value(cdt, cdn, "allow_zero_valuation_rate", 1);
        return;
    }

    const printedPrice = flt(row.custom_selling_price);
    if (!printedPrice) return;

    const basicDiscount = Math.min(
        100,
        Math.max(0, flt(row.custom_supplier_discount_percentage))
    );
    const additionalDiscount = Math.min(
        100,
        Math.max(0, flt(row.custom_additional_discount))
    );
    const effectiveDiscount =
        100 *
        (1 -
            (1 - basicDiscount / 100) *
                (1 - additionalDiscount / 100));
    const finalRate = printedPrice * (1 - effectiveDiscount / 100);
    const totalDiscountAmount = printedPrice - finalRate;

    await frappe.model.set_value(cdt, cdn, "price_list_rate", printedPrice);
    await frappe.model.set_value(
        cdt,
        cdn,
        "custom_effective_discount_percentage",
        effectiveDiscount
    );
    await frappe.model.set_value(
        cdt,
        cdn,
        "discount_percentage",
        effectiveDiscount
    );
    await frappe.model.set_value(
        cdt,
        cdn,
        "discount_amount",
        totalDiscountAmount
    );
    await frappe.model.set_value(cdt, cdn, "rate", finalRate);
}

function queue_pharmacy_rate_calculation(cdt, cdn) {
    window.setTimeout(() => {
        calculate_pharmacy_purchase_rate(cdt, cdn);
    }, 80);
}

frappe.ui.form.on("Purchase Invoice", {
    async onload_post_render(frm) {
        await sync_purchase_entry_mode(frm);
        await sync_supplier_payment_classification(frm, false);
        make_printed_retail_price_editable(frm);
    },

    async refresh(frm) {
        make_printed_retail_price_editable(frm);

        if (frm.is_new()) {
            await sync_purchase_entry_mode(frm);
            await sync_supplier_payment_classification(frm, false);
        }

        const can_review =
            frappe.user.has_role("Purchase Manager") ||
            frappe.user.has_role("Accounts Manager") ||
            frappe.user.has_role("System Manager");

        if (
            frm.doc.docstatus === 1 &&
            frm.doc.custom_retail_price_review_status === "Pending Review" &&
            can_review
        ) {
            frm.add_custom_button(
                __("Update Current Retail Prices"),
                () => {
                    frappe.confirm(
                        __(
                            "Update Item current retail prices and the configured selling price list from this invoice? Batch-specific prices will remain unchanged."
                        ),
                        () => {
                            frappe.call({
                                method: "pharma_erp.purchase_management.apply_retail_price_updates",
                                args: { invoice_name: frm.doc.name },
                                freeze: true,
                                freeze_message: __("Updating retail prices..."),
                            }).then((r) => {
                                frappe.show_alert({
                                    message: __("Updated {0} item price(s).", [
                                        r.message || 0,
                                    ]),
                                    indicator: "green",
                                });
                                frm.reload_doc();
                            });
                        }
                    );
                },
                __("Purchase Management")
            );
        }
    },

    async supplier(frm) {
        await sync_supplier_payment_classification(frm, true);
    },

    async custom_purchase_entry_mode(frm) {
        await sync_purchase_entry_mode(frm);
    },

    async custom_payment_classification(frm) {
        if (frm.doc.custom_payment_classification === "Cash Invoice") {
            await frm.set_value("custom_exclude_from_supplier_claim", 1);
        } else if (frm.doc.custom_payment_classification === "Claim Invoice") {
            await frm.set_value("custom_exclude_from_supplier_claim", 0);
        }
    },
});

frappe.ui.form.on("Purchase Invoice Item", {
    async item_code(frm, cdt, cdn) {
        await populate_printed_retail_price(cdt, cdn);
        queue_pharmacy_rate_calculation(cdt, cdn);
    },

    custom_selling_price(frm, cdt, cdn) {
        queue_pharmacy_rate_calculation(cdt, cdn);
    },

    custom_supplier_discount_percentage(frm, cdt, cdn) {
        queue_pharmacy_rate_calculation(cdt, cdn);
    },

    custom_additional_discount(frm, cdt, cdn) {
        queue_pharmacy_rate_calculation(cdt, cdn);
    },

    qty(frm, cdt, cdn) {
        queue_pharmacy_rate_calculation(cdt, cdn);
    },

    custom_is_bonus_item(frm, cdt, cdn) {
        queue_pharmacy_rate_calculation(cdt, cdn);
    },
});
