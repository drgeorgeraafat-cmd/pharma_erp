frappe.ui.form.on("Delivery Handover", {
    setup(frm) {
        frm.set_query(
            "delivery_settlement",
            function () {
                return {
                    filters: {
                        docstatus: 0,
                        settlement_status: [
                            "not in",
                            ["Settled", "Cancelled"]
                        ]
                    }
                };
            }
        );

        frm.set_query(
            "handover_method",
            function () {
                return {
                    filters: {
                        enabled: 1
                    }
                };
            }
        );
    },

    onload(frm) {
        if (
            frm.doc.delivery_settlement
            && frm.doc.docstatus === 0
        ) {
            load_handover_settlement(frm);
        }
    },

    refresh(frm) {
        toggle_reference_requirement(frm);

        if (
            frm.doc.delivery_settlement
            && frm.doc.docstatus === 0
        ) {
            load_handover_settlement(frm);
        }
    },

    delivery_settlement(frm) {
        load_handover_settlement(frm);
    },

    handover_type(frm) {
        if (
            frm.doc.handover_type ===
            "Final Settlement"
            && frm._remaining_before_handover
                !== undefined
        ) {
            frm.set_value(
                "amount",
                Math.max(
                    0,
                    flt(
                        frm
                            ._remaining_before_handover
                    )
                )
            );
        }
    },

    handover_method(frm) {
        toggle_reference_requirement(frm);
    },

    validate(frm) {
        const amount =
            flt(frm.doc.amount);

        if (amount <= 0) {
            frappe.throw(
                __("المبلغ يجب أن يكون أكبر من صفر.")
            );
        }

        const remaining =
            flt(
                frm._remaining_before_handover
            );

        if (
            frm.doc.handover_type ===
                "Partial Handover"
            && amount > remaining + 0.01
        ) {
            frappe.throw(
                __(
                    "مبلغ التوريد الجزئي أكبر من المبلغ الموجود مع الطيار."
                )
            );
        }

        if (
            frm.doc.handover_method !==
                "Cash"
            && !frm.doc.reference_number
        ) {
            frappe.throw(
                __(
                    "رقم المرجع مطلوب في التوريدات غير النقدية."
                )
            );
        }

        if (
            frm.doc.handover_type ===
            "Final Settlement"
        ) {
            const difference =
                amount - remaining;

            if (
                Math.abs(difference) > 0.01
                && !frm.doc.notes
            ) {
                frappe.throw(
                    __(
                        "قيمة التسوية النهائية مختلفة عن المتبقي. برجاء كتابة سبب الفرق في الملاحظات."
                    )
                );
            }
        }
    }
});


function load_handover_settlement(frm) {
    if (!frm.doc.delivery_settlement) {
        return;
    }

    frappe.db.get_value(
        "Delivery Settlement",
        frm.doc.delivery_settlement,
        [
            "delivery_boy",
            "shift_reference",
            "remaining_with_driver",
            "settlement_status"
        ]
    ).then(function (r) {
        const data = r.message || {};

        if (
            ["Settled", "Cancelled"].includes(
                data.settlement_status
            )
        ) {
            frappe.throw(
                __(
                    "لا يمكن إضافة توريد إلى تسوية منتهية أو ملغاة."
                )
            );
        }

        frm.set_value(
            "delivery_boy",
            data.delivery_boy
        );

        frm.set_value(
            "shift_reference",
            data.shift_reference
        );

        frm.set_value(
            "received_by",
            frappe.session.user
        );

        if (!frm.doc.received_at) {
            frm.set_value(
                "received_at",
                frappe.datetime.now_datetime()
            );
        }

        frm._remaining_before_handover =
            flt(data.remaining_with_driver);

        if (
            frm.doc.handover_type ===
                "Final Settlement"
            && !flt(frm.doc.amount)
        ) {
            frm.set_value(
                "amount",
                Math.max(
                    0,
                    frm
                        ._remaining_before_handover
                )
            );
        }
    });
}


function toggle_reference_requirement(frm) {
    const requiresReference =
        Boolean(
            frm.doc.handover_method
            && frm.doc.handover_method !==
                "Cash"
        );

    frm.toggle_reqd(
        "reference_number",
        requiresReference
    );
}