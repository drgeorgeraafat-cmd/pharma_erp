
frappe.ui.form.on("Online Order Notification Delivery Settings", {
    refresh(frm) {
        frm.add_custom_button(__("Check Delivery Readiness"), async () => {
            const response = await frappe.call({
                method: "pharma_erp.customer_notification_delivery.get_delivery_readiness",
                args: { record_check: 1 },
                freeze: true,
                freeze_message: __("Checking email delivery readiness…"),
            });
            const result = response.message || {};
            const blockers = (result.blockers || [])
                .map((item) => `<li>${frappe.utils.escape_html(item)}</li>`)
                .join("");
            frappe.msgprint({
                title: __("Step 4D Delivery Readiness"),
                indicator: result.external_delivery_ready ? "green" : "orange",
                wide: true,
                message: `
                    <p><strong>${__("Status")}:</strong>
                        ${frappe.utils.escape_html(result.readiness_status || "")}</p>
                    <p><strong>${__("Preview Ready")}:</strong>
                        ${result.preview_ready ? __("Yes") : __("No")}</p>
                    <p><strong>${__("External Delivery Ready")}:</strong>
                        ${result.external_delivery_ready ? __("Yes") : __("No")}</p>
                    ${blockers ? `<ul>${blockers}</ul>` : ""}
                    <p class="text-muted">
                        ${__("Step 4D never sends an external email.")}
                    </p>
                `,
            });
            frm.reload_doc();
        });
    },
});
