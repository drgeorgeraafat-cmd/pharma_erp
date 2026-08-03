
frappe.ui.form.on("Online Order Customer Notification", {
    refresh(frm) {
        if (frm.is_new()) return;

        frm.add_custom_button(__("Preview Email"), async () => {
            const response = await frappe.call({
                method: "pharma_erp.customer_notification_delivery.preview_notification",
                args: { notification_name: frm.doc.name },
                freeze: true,
                freeze_message: __("Preparing secure email preview…"),
            });
            const preview = response.message || {};
            frappe.msgprint({
                title: __("Secure Email Preview"),
                indicator: "green",
                wide: true,
                message: `
                    <div dir="rtl">
                        <p><strong>${__("Recipient")}:</strong>
                            ${frappe.utils.escape_html(preview.recipient_masked || "")}</p>
                        <p><strong>${__("Recipient Hash Match")}:</strong>
                            ${preview.recipient_hash_matches ? __("Yes") : __("No")}</p>
                        <hr>
                        ${preview.body_html || ""}
                        <hr>
                        <p class="text-muted">${__("No external email was sent.")}</p>
                    </div>
                `,
            });
            frm.reload_doc();
        }, __("Step 4E"));

        frm.add_custom_button(__("Queue Pilot Email"), () => {
            const dialog = new frappe.ui.Dialog({
                title: __("Queue Controlled Pilot Email"),
                fields: [
                    {
                        fieldname: "confirmation_text",
                        fieldtype: "Data",
                        label: __("Type QUEUE STEP 4E PILOT"),
                        reqd: 1,
                    },
                ],
                primary_action_label: __("Queue Pilot Email"),
                async primary_action(values) {
                    dialog.hide();
                    const response = await frappe.call({
                        method: "pharma_erp.customer_notification_delivery.queue_pilot_notification",
                        args: {
                            notification_name: frm.doc.name,
                            confirmation_text: values.confirmation_text,
                        },
                        freeze: true,
                        freeze_message: __("Creating controlled pilot Email Queue…"),
                    });
                    const result = response.message || {};
                    frappe.msgprint({
                        title: __("Pilot Email Queued"),
                        indicator: "green",
                        message: `
                            <p><strong>${__("Email Queue")}:</strong>
                                ${frappe.utils.escape_html(result.email_queue || "")}</p>
                            <p><strong>${__("Recipient")}:</strong>
                                ${frappe.utils.escape_html(result.pilot_recipient_masked || "")}</p>
                            <p>${__("The actual customer recipient was not used.")}</p>
                        `,
                    });
                    frm.reload_doc();
                },
            });
            dialog.show();
        }, __("Step 4E"));

        frm.add_custom_button(__("Refresh Dispatch Status"), async () => {
            const response = await frappe.call({
                method: "pharma_erp.customer_notification_delivery.refresh_dispatch_status",
                args: { notification_name: frm.doc.name },
                freeze: true,
                freeze_message: __("Reading Frappe Email Queue status…"),
            });
            const result = response.message?.result || {};
            frappe.msgprint({
                title: __("Dispatch Status"),
                indicator: result.status === "Sent" ? "green" : "orange",
                message: `
                    <p><strong>${__("Notification Status")}:</strong>
                        ${frappe.utils.escape_html(result.status || "")}</p>
                    <p><strong>${__("Email Queue Status")}:</strong>
                        ${frappe.utils.escape_html(result.queue_status || "")}</p>
                `,
            });
            frm.reload_doc();
        }, __("Step 4E"));

        frm.add_custom_button(__("Test Customer Delivery Guard"), async () => {
            const response = await frappe.call({
                method: "pharma_erp.customer_notification_delivery.request_controlled_delivery",
                args: { notification_name: frm.doc.name },
                freeze: true,
                freeze_message: __("Checking customer-recipient guard…"),
            });
            const result = response.message || {};
            frappe.msgprint({
                title: __("Customer Delivery Blocked"),
                indicator: "orange",
                message: frappe.utils.escape_html(result.reason || ""),
            });
            frm.reload_doc();
        }, __("Step 4E"));
    },
});
