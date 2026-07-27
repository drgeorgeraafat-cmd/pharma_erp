const ONLINE_ORDER_LOCKED_FIELDS = [
    "source_channel",
    "external_reference",
    "external_created_at",
    "company",
    "order_type",
    "fulfilment_method",
    "customer",
    "customer_name",
    "mobile_no",
    "email_id",
    "customer_resolution_status",
    "customer_address",
    "address_title",
    "address_line1",
    "address_line2",
    "city",
    "state",
    "country",
    "address_phone",
    "delivery_zone",
    "warehouse",
    "delivery_instructions",
    "currency",
    "price_list",
    "discount_amount",
    "prescription_attachment",
    "prescription_review_status",
    "prescription_review_notes",
    "payment_timing",
    "payment_method",
    "mode_of_payment",
    "declared_paid_amount",
    "transaction_reference",
    "payment_proof",
];

frappe.ui.form.on("Online Order", {
    refresh(frm) {
        frm.set_df_property("status", "read_only", 1);

        if (frm.is_new()) return;

        for (const target of statusTransitions(frm)) {
            frm.add_custom_button(__(target), () => changeStatus(frm, target), __("Status"));
        }

        const isLocked = Boolean(frm.doc.confirmed_at)
            || ["Completed", "Rejected", "Cancelled"].includes(frm.doc.status);

        if (isLocked) {
            lockConfirmedOrder(frm);
        }

        if (
            ["Confirmed", "Preparing"].includes(frm.doc.status)
            && !frm.doc.sales_order
            && !frm.doc.sales_invoice
        ) {
            frm.add_custom_button(
                __("Create Sales Invoice Draft"),
                () => createSalesInvoiceDraft(frm),
                __("Conversion"),
            );
        }

        if (frm.doc.sales_order) {
            frm.add_custom_button(__("Open Sales Order"), () => {
                frappe.set_route("Form", "Sales Order", frm.doc.sales_order);
            }, __("Links"));
        }
        if (frm.doc.sales_invoice) {
            frm.add_custom_button(__("Open Sales Invoice"), () => {
                frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice);
            }, __("Links"));
        }
    },
});

function statusTransitions(frm) {
    const transitions = {
        "Draft": ["Placed", "Cancelled"],
        "Placed": ["Under Review", "Cancelled"],
        "Under Review": ["Prescription Review", "Stock Review", "Ready for Payment", "On Hold", "Rejected", "Cancelled"],
        "Prescription Review": ["Stock Review", "Partially Available", "Awaiting Customer Decision", "On Hold", "Rejected", "Cancelled"],
        "Stock Review": ["Partially Available", "Awaiting Customer Decision", "Ready for Payment", "On Hold", "Rejected", "Cancelled"],
        "Partially Available": ["Awaiting Customer Decision", "Stock Review", "Ready for Payment", "Cancelled"],
        "Awaiting Customer Decision": ["Stock Review", "Ready for Payment", "Cancelled"],
        "Ready for Payment": ["Payment Verification", "Confirmed", "On Hold", "Cancelled"],
        "Payment Verification": ["Confirmed", "Payment Failed", "On Hold", "Cancelled"],
        "Payment Failed": ["Ready for Payment", "Cancelled"],
        "Confirmed": ["Preparing", "Cancelled"],
        "Preparing": [
            frm.doc.fulfilment_method === "Pharmacy Pickup"
                ? "Ready for Pickup"
                : "Ready for Delivery",
            "On Hold",
            "Cancelled",
        ],
        "Ready for Delivery": ["Out for Delivery", "Cancelled"],
        "Ready for Pickup": ["Completed", "Cancelled"],
        "Out for Delivery": ["Delivered", "Returned"],
        "Delivered": ["Completed", "Returned"],
        "Returned": ["Completed"],
        "On Hold": ["Under Review", "Prescription Review", "Stock Review", "Ready for Payment", "Preparing", "Rejected", "Cancelled"],
    };
    return transitions[frm.doc.status] || [];
}

function lockConfirmedOrder(frm) {
    for (const fieldname of ONLINE_ORDER_LOCKED_FIELDS) {
        if (frm.fields_dict[fieldname]) {
            frm.set_df_property(fieldname, "read_only", 1);
        }
    }

    frm.set_df_property("items", "read_only", 1);

    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    if (grid) {
        grid.cannot_add_rows = true;
        grid.cannot_delete_rows = true;
        grid.only_sortable = false;
        grid.refresh();
    }

    frm.disable_save();
    frm.dashboard.set_headline_alert(
        __("Confirmed order data is locked. Use Status actions or controlled conversion operations."),
        "blue",
    );
}

async function createSalesInvoiceDraft(frm) {
    const confirmed = await new Promise((resolve) => {
        frappe.confirm(
            __("Create one non-stock Draft Sales Invoice from Online Order {0}?", [frm.doc.name]),
            () => resolve(true),
            () => resolve(false),
        );
    });
    if (!confirmed) return;

    const response = await frappe.call({
        method: "pharma_erp.pharma_erp.doctype.online_order.online_order.create_sales_invoice_draft",
        args: { order_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Creating Sales Invoice Draft..."),
    });

    await frm.reload_doc();
    const invoiceName = response.message && response.message.sales_invoice;
    if (invoiceName) {
        frappe.show_alert({
            message: __("Sales Invoice Draft {0} created.", [invoiceName]),
            indicator: "green",
        });
        frappe.set_route("Form", "Sales Invoice", invoiceName);
    }
}

async function changeStatus(frm, target) {
    const needsReason = ["Cancelled", "Rejected", "On Hold"].includes(target);
    let reason = "";

    if (needsReason) {
        reason = await new Promise((resolve) => {
            frappe.prompt(
                [{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
                (values) => resolve(values.reason || ""),
                __(target),
                __("Continue"),
            );
        });
    }

    await frappe.call({
        method: "pharma_erp.pharma_erp.doctype.online_order.online_order.transition_status",
        args: {
            order_name: frm.doc.name,
            target_status: target,
            reason,
        },
        freeze: true,
        freeze_message: __("Updating Online Order..."),
    });
    await frm.reload_doc();
}
