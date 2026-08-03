
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
                        <p class="text-muted">
                            ${__("No external email was sent.")}
                        </p>
                    </div>
                `,
            });
            frm.reload_doc();
        }, __("Step 4D"));

        frm.add_custom_button(__("Test Delivery Guard"), async () => {
            const response = await frappe.call({
                method: "pharma_erp.customer_notification_delivery.request_controlled_delivery",
                args: { notification_name: frm.doc.name },
                freeze: true,
                freeze_message: __("Checking controlled delivery guard…"),
            });
            const result = response.message || {};
            frappe.msgprint({
                title: __("External Delivery Blocked"),
                indicator: "orange",
                message: frappe.utils.escape_html(result.reason || ""),
            });
            frm.reload_doc();
        }, __("Step 4D"));
    },
});
