frappe.ui.form.on("Online Order Notification Delivery Settings", {
    refresh(frm) {
        frm.add_custom_button(__("Check Delivery Readiness"), async () => {
            const response = await frappe.call({
                method: "pharma_erp.customer_notification_delivery.get_delivery_readiness",
                args: { record_check: 1 },
                freeze: true,
                freeze_message: __("Checking Step 4F customer delivery readiness…"),
            });
            const result = response.message || {};
            const blockers = (result.blockers || [])
                .map((item) => `<li>${frappe.utils.escape_html(item)}</li>`)
                .join("");
            frappe.msgprint({
                title: __("Step 4F Delivery Readiness"),
                indicator: result.activation_ready ? "green" : "orange",
                wide: true,
                message: `
                    <p><strong>${__("Status")}:</strong>
                        ${frappe.utils.escape_html(result.readiness_status || "")}</p>
                    <p><strong>${__("Activation Ready")}:</strong>
                        ${result.activation_ready ? __("Yes") : __("No")}</p>
                    <p><strong>${__("Customer Active")}:</strong>
                        ${result.customer_active ? __("Yes") : __("No")}</p>
                    <p><strong>${__("Automatic Dispatch Active")}:</strong>
                        ${result.auto_dispatch_active ? __("Yes") : __("No")}</p>
                    <p><strong>${__("Customer Dispatches Today")}:</strong>
                        ${result.customer_dispatches_today || 0} /
                        ${result.daily_customer_dispatch_limit || 0}</p>
                    <p><strong>${__("Protected Legacy Deferred")}:</strong>
                        ${result.protected_legacy_deferred || 0}</p>
                    <p><strong>${__("Eligible Post-Cutover")}:</strong>
                        ${result.eligible_post_cutover || 0}</p>
                    ${blockers ? `<ul>${blockers}</ul>` : ""}
                `,
            });
            frm.reload_doc();
        }, __("Step 4F"));

        if (frm.doc.delivery_mode !== "Controlled Customer") {
            frm.add_custom_button(__("Activate Controlled Customer"), () => {
                const dialog = new frappe.ui.Dialog({
                    title: __("Activate Step 4F Controlled Customer"),
                    fields: [
                        {
                            fieldname: "confirmation_text",
                            fieldtype: "Data",
                            label: __("Type ACTIVATE STEP 4F CUSTOMER"),
                            reqd: 1,
                        },
                    ],
                    primary_action_label: __("Activate"),
                    async primary_action(values) {
                        dialog.hide();
                        const response = await frappe.call({
                            method: "pharma_erp.customer_notification_delivery.activate_customer_dispatch",
                            args: values,
                            freeze: true,
                            freeze_message: __("Activating controlled customer delivery…"),
                        });
                        const result = response.message || {};
                        frappe.msgprint({
                            title: __("Controlled Customer Active"),
                            indicator: "green",
                            message: `
                                <p><strong>${__("Cutover At")}:</strong>
                                    ${frappe.utils.escape_html(result.customer_dispatch_cutover_at || "")}</p>
                                <p><strong>${__("Protected Legacy Deferred")}:</strong>
                                    ${result.protected_legacy_deferred || 0}</p>
                                <p>${__("Automatic dispatch remains disabled until separately enabled.")}</p>
                            `,
                        });
                        frm.reload_doc();
                    },
                });
                dialog.show();
            }, __("Step 4F"));
        }

        if (frm.doc.delivery_mode === "Controlled Customer") {
            frm.add_custom_button(__("Deactivate Controlled Customer"), () => {
                const dialog = new frappe.ui.Dialog({
                    title: __("Deactivate Step 4F Controlled Customer"),
                    fields: [
                        {
                            fieldname: "confirmation_text",
                            fieldtype: "Data",
                            label: __("Type DEACTIVATE STEP 4F CUSTOMER"),
                            reqd: 1,
                        },
                    ],
                    primary_action_label: __("Deactivate"),
                    async primary_action(values) {
                        dialog.hide();
                        await frappe.call({
                            method: "pharma_erp.customer_notification_delivery.deactivate_customer_dispatch",
                            args: values,
                            freeze: true,
                            freeze_message: __("Deactivating controlled customer delivery…"),
                        });
                        frappe.show_alert({
                            message: __("Controlled Customer mode is inactive."),
                            indicator: "green",
                        });
                        frm.reload_doc();
                    },
                });
                dialog.show();
            }, __("Step 4F"));

            if (!frm.doc.automatic_customer_dispatch_enabled) {
                frm.add_custom_button(__("Enable Automatic Dispatch"), () => {
                    const dialog = new frappe.ui.Dialog({
                        title: __("Enable Step 4F Automatic Dispatch"),
                        fields: [
                            {
                                fieldname: "confirmation_text",
                                fieldtype: "Data",
                                label: __("Type ENABLE STEP 4F AUTO"),
                                reqd: 1,
                            },
                        ],
                        primary_action_label: __("Enable"),
                        async primary_action(values) {
                            dialog.hide();
                            await frappe.call({
                                method: "pharma_erp.customer_notification_delivery.enable_automatic_customer_dispatch",
                                args: values,
                                freeze: true,
                                freeze_message: __("Enabling automatic customer dispatch…"),
                            });
                            frappe.show_alert({
                                message: __("Automatic customer dispatch is active."),
                                indicator: "green",
                            });
                            frm.reload_doc();
                        },
                    });
                    dialog.show();
                }, __("Step 4F"));
            } else {
                frm.add_custom_button(__("Disable Automatic Dispatch"), () => {
                    const dialog = new frappe.ui.Dialog({
                        title: __("Disable Step 4F Automatic Dispatch"),
                        fields: [
                            {
                                fieldname: "confirmation_text",
                                fieldtype: "Data",
                                label: __("Type DISABLE STEP 4F AUTO"),
                                reqd: 1,
                            },
                        ],
                        primary_action_label: __("Disable"),
                        async primary_action(values) {
                            dialog.hide();
                            await frappe.call({
                                method: "pharma_erp.customer_notification_delivery.disable_automatic_customer_dispatch",
                                args: values,
                                freeze: true,
                                freeze_message: __("Disabling automatic customer dispatch…"),
                            });
                            frappe.show_alert({
                                message: __("Automatic customer dispatch is disabled."),
                                indicator: "green",
                            });
                            frm.reload_doc();
                        },
                    });
                    dialog.show();
                }, __("Step 4F"));
            }
        }

        // Preserve Step 4E pilot controls for future isolated diagnostics.
        if (frm.doc.delivery_mode !== "Controlled Customer") {
            frm.add_custom_button(__("Activate Controlled Pilot"), () => {
                const dialog = new frappe.ui.Dialog({
                    title: __("Activate Step 4E Controlled Pilot"),
                    fields: [
                        {
                            fieldname: "pilot_recipient",
                            fieldtype: "Data",
                            options: "Email",
                            label: __("Pilot Recipient Email"),
                            reqd: 1,
                        },
                        {
                            fieldname: "confirmation_text",
                            fieldtype: "Data",
                            label: __("Type ACTIVATE STEP 4E PILOT"),
                            reqd: 1,
                        },
                    ],
                    primary_action_label: __("Activate"),
                    async primary_action(values) {
                        dialog.hide();
                        const response = await frappe.call({
                            method: "pharma_erp.customer_notification_delivery.activate_pilot_dispatch",
                            args: values,
                            freeze: true,
                            freeze_message: __("Activating controlled pilot…"),
                        });
                        const result = response.message || {};
                        frappe.msgprint({
                            title: __("Controlled Pilot Active"),
                            indicator: "green",
                            message: `
                                <p><strong>${__("Pilot Recipient")}:</strong>
                                    ${frappe.utils.escape_html(result.pilot_recipient_masked || "")}</p>
                                <p>${__("Actual customer recipients remain disabled.")}</p>
                            `,
                        });
                        frm.reload_doc();
                    },
                });
                dialog.show();
            }, __("Step 4E Pilot"));
        }

        if (frm.doc.delivery_mode === "Controlled Pilot") {
            frm.add_custom_button(__("Deactivate Controlled Pilot"), () => {
                const dialog = new frappe.ui.Dialog({
                    title: __("Deactivate Step 4E Controlled Pilot"),
                    fields: [
                        {
                            fieldname: "confirmation_text",
                            fieldtype: "Data",
                            label: __("Type DEACTIVATE STEP 4E PILOT"),
                            reqd: 1,
                        },
                    ],
                    primary_action_label: __("Deactivate"),
                    async primary_action(values) {
                        dialog.hide();
                        await frappe.call({
                            method: "pharma_erp.customer_notification_delivery.deactivate_pilot_dispatch",
                            args: values,
                            freeze: true,
                            freeze_message: __("Deactivating controlled pilot…"),
                        });
                        frappe.show_alert({
                            message: __("Controlled Pilot is inactive."),
                            indicator: "green",
                        });
                        frm.reload_doc();
                    },
                });
                dialog.show();
            }, __("Step 4E Pilot"));
        }
    },
});
