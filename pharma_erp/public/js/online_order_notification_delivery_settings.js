
frappe.ui.form.on("Online Order Notification Delivery Settings", {
    refresh(frm) {
        frm.add_custom_button(__("Check Delivery Readiness"), async () => {
            const response = await frappe.call({
                method: "pharma_erp.customer_notification_delivery.get_delivery_readiness",
                args: { record_check: 1 },
                freeze: true,
                freeze_message: __("Checking controlled pilot readiness…"),
            });
            const result = response.message || {};
            const blockers = (result.blockers || [])
                .map((item) => `<li>${frappe.utils.escape_html(item)}</li>`)
                .join("");
            frappe.msgprint({
                title: __("Step 4E Delivery Readiness"),
                indicator: result.activation_ready ? "green" : "orange",
                wide: true,
                message: `
                    <p><strong>${__("Status")}:</strong>
                        ${frappe.utils.escape_html(result.readiness_status || "")}</p>
                    <p><strong>${__("Activation Ready")}:</strong>
                        ${result.activation_ready ? __("Yes") : __("No")}</p>
                    <p><strong>${__("Pilot Active")}:</strong>
                        ${result.pilot_active ? __("Yes") : __("No")}</p>
                    <p><strong>${__("Dispatches Today")}:</strong>
                        ${result.dispatches_today || 0} / ${result.daily_dispatch_limit || 0}</p>
                    ${blockers ? `<ul>${blockers}</ul>` : ""}
                `,
            });
            frm.reload_doc();
        });

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
        });

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
        });
    },
});
