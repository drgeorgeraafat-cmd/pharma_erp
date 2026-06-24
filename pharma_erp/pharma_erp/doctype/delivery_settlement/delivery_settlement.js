frappe.ui.form.on("Delivery Settlement", {
    onload: function (frm) {
        frm.set_query("shift_reference", function () {
            return {
                filters: {
                    status: "Open",
                    docstatus: 0
                }
            };
        });

        frm.set_query("delivery_boy", function () {
            return {
                filters: {
                    status: "Active"
                }
            };
        });

        if (frm.is_new() && !frm.doc.shift_reference) {
            set_current_open_shift(frm);
        }
    },

    refresh: function (frm) {
        add_settlement_buttons(frm);
        recalculate_local_totals(frm);
    },

    delivery_boy: function (frm) {
        if (frm.doc.delivery_boy && frm.doc.shift_reference) {
            load_settlement_collections(frm);
        }
    },

    shift_reference: function (frm) {
        if (frm.doc.delivery_boy && frm.doc.shift_reference) {
            load_settlement_collections(frm);
        }
    },

    pilot_float: function (frm) {
        recalculate_local_totals(frm);
    },

    before_submit: function (frm) {
        if (["Settled", "Disputed"].indexOf(frm.doc.settlement_status) === -1) {
            frappe.throw(__("لا يمكن اعتماد التسوية قبل تنفيذ التسوية النهائية."));
        }

        if (
            Math.abs(flt(frm.doc.final_difference)) > 0.01 &&
            !frm.doc.difference_reason
        ) {
            frappe.throw(__("يوجد فرق في التسوية. برجاء كتابة سبب الفرق."));
        }
    }
});

function add_settlement_buttons(frm) {
    if (frm.doc.docstatus === 0) {
        frm.add_custom_button(
            __("🔄 تحديث تحصيلات الطيار"),
            function () {
                if (!frm.doc.delivery_boy) {
                    frappe.msgprint(__("برجاء تحديد الطيار."));
                    return;
                }

                if (!frm.doc.shift_reference) {
                    frappe.msgprint(__("برجاء تحديد الشيفت."));
                    return;
                }

                load_settlement_collections(frm);
            },
            __("إجراءات التسوية")
        );
    }

    if (
        frm.doc.docstatus === 0 &&
        !frm.is_new() &&
        ["Settled", "Cancelled"].indexOf(frm.doc.settlement_status) === -1
    ) {
        frm.add_custom_button(
            __("💵 استلام مبلغ جزئي"),
            function () {
                create_handover(frm, "Partial Handover");
            },
            __("إجراءات التسوية")
        );

        frm.add_custom_button(
            __("✅ تسوية نهائية"),
            function () {
                start_final_settlement(frm);
            },
            __("إجراءات التسوية")
        );
    }

    if (!frm.is_new()) {
        frm.add_custom_button(
            __("📋 عرض التوريدات"),
            function () {
                frappe.route_options = {
                    delivery_settlement: frm.doc.name
                };
                frappe.set_route("List", "Delivery Handover");
            },
            __("إجراءات التسوية")
        );
    }
}

function set_current_open_shift(frm) {
    frappe.db.get_list("Pharmacy Shift Closing", {
        filters: {
            status: "Open",
            docstatus: 0
        },
        fields: ["name", "start_time"],
        order_by: "start_time desc",
        limit: 1
    }).then(function (rows) {
        if (rows && rows.length) {
            frm.set_value("shift_reference", rows[0].name).then(function () {
                add_settlement_buttons(frm);
            });
        }
    });
}

function load_settlement_collections(frm) {
    if (!frm.doc.delivery_boy) {
        frappe.msgprint(__("برجاء تحديد الطيار."));
        return;
    }

    if (!frm.doc.shift_reference) {
        frappe.msgprint(__("برجاء تحديد الشيفت."));
        return;
    }

    frappe.call({
        method: "pharma_erp.pharma_erp.doctype.delivery_settlement.delivery_settlement.get_delivery_settlement_data",
        args: {
            delivery_boy: frm.doc.delivery_boy,
            shift_reference: frm.doc.shift_reference,
            settlement_name: frm.is_new() ? "" : frm.doc.name
        },
        freeze: true,
        freeze_message: __("جاري تجميع تحصيلات الطيار..."),
        callback: function (r) {
            var result = r.message || {};
            var items = result.items || [];

            frm.clear_table("invoices");

            items.forEach(function (item) {
                var row = frm.add_child("invoices");
                row.invoice_number = item.invoice_number;
                row.customer_name = item.customer_name;
                row.amount = flt(item.amount);
                row.mode_of_payment = item.mode_of_payment;
                row.collection_received_by = item.collection_received_by;
                row.payment_entry = item.payment_entry;
                row.confirmed_collection_amount = flt(
                    item.confirmed_collection_amount
                );
                row.collection_status = item.collection_status;
                row.delivery_trip = item.delivery_trip;
                row.collected_at = item.collected_at;
            });

            frm.refresh_field("invoices");

            frm.set_value(
                "total_collected_by_driver",
                flt(result.total_collected)
            );
            frm.set_value(
                "total_handed_over",
                flt(result.total_handed_over)
            );
            frm.set_value("paid_cash", flt(result.paid_cash));
            frm.set_value("paid_visa", flt(result.paid_non_cash));
            frm.set_value("handover_count", cint(result.handover_count));
            frm.set_value(
                "last_handover_at",
                result.last_handover_at || null
            );

            recalculate_local_totals(frm);

            if (items.length) {
                frappe.show_alert({
                    message: __("تم تحديث تحصيلات الطيار بنجاح."),
                    indicator: "green"
                });
            } else {
                frappe.msgprint(
                    __(
                        "لا توجد تحصيلات مؤكدة مستلمة بواسطة الطيار داخل هذا الشيفت."
                    )
                );
            }
        },
        error: function () {
            frappe.msgprint(__("حدث خطأ أثناء جلب تحصيلات الطيار."));
        }
    });
}

function recalculate_local_totals(frm) {
    var collected = 0;

    (frm.doc.invoices || []).forEach(function (row) {
        if (
            row.collection_status === "Confirmed" &&
            row.collection_received_by === "Delivery Boy"
        ) {
            collected += flt(
                row.confirmed_collection_amount || row.amount
            );
        }
    });

    var expected = collected + flt(frm.doc.pilot_float);
    var handed_over = flt(frm.doc.total_handed_over);
    var remaining = expected - handed_over;

    frm.set_value("total_collected_by_driver", collected);
    frm.set_value("total_expected", expected);
    frm.set_value("remaining_with_driver", remaining);

    if (frm.doc.settlement_status !== "Cancelled") {
        if (
            cint(frm.doc.handover_count) > 0 &&
            ["Settled", "Disputed"].indexOf(frm.doc.settlement_status) === -1
        ) {
            frm.set_value("settlement_status", "Partial Handover");
        } else if (
            cint(frm.doc.handover_count) === 0 &&
            ["Settled", "Disputed"].indexOf(frm.doc.settlement_status) === -1
        ) {
            frm.set_value("settlement_status", "Open");
        }
    }
}

function create_handover(frm, handover_type) {
    if (frm.is_new() || frm.is_dirty()) {
        frappe.msgprint(
            __("برجاء حفظ التسوية أولًا قبل تسجيل التوريد.")
        );
        return;
    }

    frappe.new_doc("Delivery Handover", {
        delivery_settlement: frm.doc.name,
        delivery_boy: frm.doc.delivery_boy,
        shift_reference: frm.doc.shift_reference,
        handover_type: handover_type,
        amount:
            handover_type === "Final Settlement"
                ? Math.max(0, flt(frm.doc.remaining_with_driver))
                : 0
    });
}

function start_final_settlement(frm) {
    if (frm.is_new() || frm.is_dirty()) {
        frappe.msgprint(__("برجاء حفظ التسوية أولًا."));
        return;
    }

    var remaining = flt(frm.doc.remaining_with_driver);

    if (remaining > 0.01) {
        create_handover(frm, "Final Settlement");
        return;
    }

    var difference =
        flt(frm.doc.total_handed_over) - flt(frm.doc.total_expected);

    frm.set_value("final_difference", difference);
    frm.set_value(
        "settlement_status",
        Math.abs(difference) <= 0.01 ? "Settled" : "Disputed"
    );

    frappe.msgprint(
        __(
            "لا يوجد مبلغ متبقٍ مع الطيار. احفظ المستند ثم اضغط Submit لإتمام التسوية النهائية."
        )
    );
}
