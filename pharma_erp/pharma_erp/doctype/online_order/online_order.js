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

            if (["Confirmed", "Preparing"].includes(frm.doc.status)) {
                addControlledSubmitButton(frm);
            }
        }
        if (frm.doc.payment_entry) {
            frm.add_custom_button(__("Open Payment Entry"), () => {
                frappe.set_route("Form", "Payment Entry", frm.doc.payment_entry);
            }, __("Links"));
        }
        if (
            frm.doc.fulfilment_method === "Pharmacy Pickup"
            && frm.doc.status === "Ready for Pickup"
            && frm.doc.sales_invoice
        ) {
            addPickupActions(frm);
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
        "Ready for Pickup": ["Cancelled"],
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
async function addControlledSubmitButton(frm) {
    const response = await frappe.db.get_value(
        "Sales Invoice",
        frm.doc.sales_invoice,
        ["docstatus", "grand_total", "update_stock"],
    );
    const invoice = response && response.message;
    if (!invoice || Number(invoice.docstatus || 0) !== 0) return;

    frm.add_custom_button(
        __("Submit Linked Sales Invoice"),
        () => submitLinkedSalesInvoice(frm),
        __("Conversion"),
    );
}

async function submitLinkedSalesInvoice(frm) {
    const confirmed = await new Promise((resolve) => {
        frappe.confirm(
            __(
                "Submit linked Sales Invoice {0}? This creates the normal accounting entries, keeps Update Stock disabled, and moves this order to its Ready status.",
                [frm.doc.sales_invoice],
            ),
            () => resolve(true),
            () => resolve(false),
        );
    });
    if (!confirmed) return;

    const response = await frappe.call({
        method: "pharma_erp.pharma_erp.doctype.online_order.online_order.submit_linked_sales_invoice",
        args: { order_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Validating and submitting linked Sales Invoice..."),
    });

    await frm.reload_doc();
    const result = response.message || {};
    frappe.show_alert({
        message: __("Sales Invoice {0} submitted. Online Order is now {1}.", [
            result.sales_invoice,
            result.online_order_status,
        ]),
        indicator: "green",
    });
}

async function addPickupActions(frm) {
    const response = await frappe.db.get_value(
        "Sales Invoice",
        frm.doc.sales_invoice,
        ["docstatus", "outstanding_amount", "grand_total"],
    );
    const invoice = response && response.message;
    if (!invoice || Number(invoice.docstatus || 0) !== 1) return;

    const outstanding = Number(invoice.outstanding_amount || 0);
    if (
        frm.doc.payment_timing !== "No Collection Required"
        && outstanding > 0.01
        && !frm.doc.payment_entry
    ) {
        frm.add_custom_button(
            __("Create Pickup Payment Draft"),
            () => createPickupPaymentDraft(frm, outstanding),
            __("Pickup"),
        );
    }

    frm.add_custom_button(
        __("Complete Pharmacy Pickup"),
        () => completePharmacyPickup(frm, outstanding),
        __("Pickup"),
    );
}

async function createPickupPaymentDraft(frm, outstanding) {
    const values = await new Promise((resolve) => {
        let submitted = false;
        const dialog = new frappe.ui.Dialog({
            title: __("Create Pickup Payment Draft"),
            fields: [
                {
                    fieldname: "mode_of_payment",
                    fieldtype: "Link",
                    options: "Mode of Payment",
                    label: __("Mode of Payment"),
                    reqd: 1,
                    default: frm.doc.mode_of_payment || "",
                },
                {
                    fieldname: "amount",
                    fieldtype: "Currency",
                    label: __("Collection Amount"),
                    reqd: 1,
                    default: outstanding,
                    description: __("Must equal the current Sales Invoice outstanding amount."),
                },
                {
                    fieldname: "reference_no",
                    fieldtype: "Data",
                    label: __("Reference No"),
                },
                {
                    fieldname: "collection_notes",
                    fieldtype: "Small Text",
                    label: __("Collection Notes"),
                },
            ],
            primary_action_label: __("Create Draft"),
            primary_action(data) {
                submitted = true;
                resolve(data);
                dialog.hide();
            },
        });
        dialog.onhide = () => {
            if (!submitted) resolve(null);
        };
        dialog.show();
    });
    if (!values) return;

    const response = await frappe.call({
        method: "pharma_erp.pharma_erp.doctype.online_order.online_order.create_pickup_payment_draft",
        args: {
            order_name: frm.doc.name,
            mode_of_payment: values.mode_of_payment,
            amount: values.amount,
            reference_no: values.reference_no || "",
            collection_notes: values.collection_notes || "",
        },
        freeze: true,
        freeze_message: __("Creating Pickup Payment Entry Draft..."),
    });

    await frm.reload_doc();
    const result = response.message || {};
    if (result.payment_entry) {
        frappe.show_alert({
            message: __("Payment Entry Draft {0} created. Review and submit it before completing pickup.", [result.payment_entry]),
            indicator: "green",
        });
        frappe.set_route("Form", "Payment Entry", result.payment_entry);
    }
}

async function completePharmacyPickup(frm, outstanding) {
    const noCollection = frm.doc.payment_timing === "No Collection Required";
    const message = noCollection
        ? __("Complete Pharmacy Pickup without collection for Online Order {0}?", [frm.doc.name])
        : outstanding > 0.01
            ? __("Sales Invoice still has outstanding amount {0}. Submit the linked Payment Entry first.", [format_currency(outstanding, frm.doc.currency)])
            : __("Confirm customer pickup and complete Online Order {0}?", [frm.doc.name]);

    if (!noCollection && outstanding > 0.01) {
        frappe.msgprint(message);
        return;
    }

    const values = await new Promise((resolve) => {
        frappe.prompt(
            [{
                fieldname: "pickup_notes",
                fieldtype: "Small Text",
                label: __("Pickup Completion Notes"),
            }],
            (data) => resolve(data),
            __("Complete Pharmacy Pickup"),
            __("Complete"),
        );
    });

    const confirmed = await new Promise((resolve) => {
        frappe.confirm(message, () => resolve(true), () => resolve(false));
    });
    if (!confirmed) return;

    const response = await frappe.call({
        method: "pharma_erp.pharma_erp.doctype.online_order.online_order.complete_pharmacy_pickup",
        args: {
            order_name: frm.doc.name,
            pickup_notes: (values && values.pickup_notes) || "",
        },
        freeze: true,
        freeze_message: __("Completing Pharmacy Pickup..."),
    });

    await frm.reload_doc();
    const result = response.message || {};
    frappe.show_alert({
        message: __("Online Order {0} completed. Payment status: {1}.", [result.online_order, result.payment_status]),
        indicator: "green",
    });
}
