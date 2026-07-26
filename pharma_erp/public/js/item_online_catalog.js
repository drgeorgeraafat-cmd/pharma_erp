frappe.ui.form.on("Item", {
	setup(frm) {
		frm.set_query("custom_online_category", () => ({
			filters: {
				is_group: 0,
				enabled: 1,
			},
		}));
	},

	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(
			__("Check Online Readiness"),
			() => check_online_readiness(frm),
			__("Online Catalog")
		);
	},

	custom_show_online(frm) {
		if (
			frm.doc.custom_show_online
			&& !frm.doc.custom_online_category
		) {
			frappe.show_alert({
				message: __(
					"Select an enabled leaf Online Category before saving."
				),
				indicator: "orange",
			});
		}
	},
});

async function check_online_readiness(frm) {
	const response = await frappe.call({
		method: "pharma_erp.online_catalog_readiness.get_item_readiness",
		args: {
			item_name: frm.doc.name,
		},
		freeze: true,
		freeze_message: __("Checking online publishing readiness..."),
	});

	const result = response.message || {};
	const issues = (result.issues || [])
		.map((issue) => `<li>${frappe.utils.escape_html(issue.message)}</li>`)
		.join("");

	const issue_html = issues
		? `<ul style="margin-top: 10px;">${issues}</ul>`
		: `<p>${__("No readiness issues were found.")}</p>`;

	frappe.msgprint({
		title: __("Online Publishing Readiness"),
		indicator:
			result.readiness_status === "Ready"
				? "green"
				: result.readiness_status === "Warning"
					? "orange"
					: result.readiness_status === "Not Selected"
						? "blue"
						: "red",
		message: `
			<p><strong>${__("Status")}:</strong>
				${frappe.utils.escape_html(result.readiness_status || "")}
			</p>
			<p><strong>${__("Score")}:</strong>
				${result.readiness_score || 0} / 100
			</p>
			<p><strong>${__("Effective Price")}:</strong>
				${format_currency(result.effective_price || 0)}
				${result.price_source
					? `(${frappe.utils.escape_html(result.price_source)})`
					: ""}
			</p>
			${issue_html}
		`,
	});
}
