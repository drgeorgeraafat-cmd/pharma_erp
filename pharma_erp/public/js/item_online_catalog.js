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

		load_publishing_buttons(frm);
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

async function load_publishing_buttons(frm) {
	const response = await frappe.call({
		method:
			"pharma_erp.website_item_publishing."
			+ "get_website_item_publishing_status",
		args: {
			item_name: frm.doc.name,
		},
	});

	const status = response.message || {};

	frm.add_custom_button(
		status.exists
			? __("Sync Website Item")
			: __("Create Website Item"),
		() => run_publishing_action(
			frm,
			"create_or_sync_website_item",
			__("Synchronizing Website Item...")
		),
		__("Online Catalog")
	);

	if (status.exists && !status.published) {
		frm.add_custom_button(
			__("Publish Online"),
			() => confirm_publish(frm, status),
			__("Online Catalog")
		);
	}

	if (status.exists && status.published) {
		frm.add_custom_button(
			__("Unpublish Online"),
			() => confirm_unpublish(frm),
			__("Online Catalog")
		);
	}

	if (status.exists && status.website_item) {
		frm.add_custom_button(
			__("Open Website Item"),
			() => frappe.set_route(
				"Form",
				"Website Item",
				status.website_item
			),
			__("Online Catalog")
		);
	}

	if (status.published && status.route) {
		frm.add_custom_button(
			__("View on Website"),
			() => window.open(`/${status.route}`, "_blank"),
			__("Online Catalog")
		);
	}
}

function confirm_publish(frm, status) {
	const warnings = (status.issues || [])
		.filter((issue) => issue.severity === "Warning")
		.map((issue) => frappe.utils.escape_html(issue.message))
		.join("<br>");

	const message = warnings
		? `${__("Publish this item online?")}<br><br>${warnings}`
		: __("Publish this item online?");

	frappe.confirm(
		message,
		() => run_publishing_action(
			frm,
			"publish_website_item",
			__("Publishing item online...")
		)
	);
}

function confirm_unpublish(frm) {
	frappe.confirm(
		__("Unpublish this item from the website?"),
		() => run_publishing_action(
			frm,
			"unpublish_website_item",
			__("Unpublishing item...")
		)
	);
}

async function run_publishing_action(
	frm,
	method,
	freeze_message
) {
	const response = await frappe.call({
		method: `pharma_erp.website_item_publishing.${method}`,
		args: {
			item_name: frm.doc.name,
		},
		freeze: true,
		freeze_message,
	});

	const result = response.message || {};
	show_publishing_result(result);
	await frm.reload_doc();
}

function show_publishing_result(result) {
	const issues = (result.issues || [])
		.map(
			(issue) =>
				`<li>${frappe.utils.escape_html(issue.message)}</li>`
		)
		.join("");

	const issue_html = issues
		? `<ul style="margin-top: 10px;">${issues}</ul>`
		: "";

	frappe.msgprint({
		title: __("Website Item Publishing"),
		indicator: result.published ? "green" : "blue",
		message: `
			<p><strong>${__("Action")}:</strong>
				${frappe.utils.escape_html(result.action || "")}
			</p>
			<p><strong>${__("Website Item")}:</strong>
				${frappe.utils.escape_html(result.website_item || "")}
			</p>
			<p><strong>${__("Published")}:</strong>
				${result.published ? __("Yes") : __("No")}
			</p>
			<p><strong>${__("Readiness")}:</strong>
				${frappe.utils.escape_html(
					result.readiness_status || ""
				)}
				(${result.readiness_score || 0} / 100)
			</p>
			${issue_html}
		`,
	});
}

async function check_online_readiness(frm) {
	const response = await frappe.call({
		method:
			"pharma_erp.online_catalog_readiness."
			+ "get_item_readiness",
		args: {
			item_name: frm.doc.name,
		},
		freeze: true,
		freeze_message: __(
			"Checking online publishing readiness..."
		),
	});

	const result = response.message || {};
	const issues = (result.issues || [])
		.map(
			(issue) =>
				`<li>${frappe.utils.escape_html(issue.message)}</li>`
		)
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
				${frappe.utils.escape_html(
					result.readiness_status || ""
				)}
			</p>
			<p><strong>${__("Score")}:</strong>
				${result.readiness_score || 0} / 100
			</p>
			<p><strong>${__("Effective Price")}:</strong>
				${format_currency(result.effective_price || 0)}
				${result.price_source
					? `(${frappe.utils.escape_html(
						result.price_source
					)})`
					: ""}
			</p>
			${issue_html}
		`,
	});
}
