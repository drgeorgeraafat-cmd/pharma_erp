frappe.query_reports["Online Catalog Publishing Readiness"] = {
	filters: [
		{
			fieldname: "show_online_scope",
			label: __("Item Scope"),
			fieldtype: "Select",
			options: [
				"Show Online Only",
				"All Items",
				"Not Selected Only",
			],
			default: "Show Online Only",
		},
		{
			fieldname: "readiness_status",
			label: __("Readiness Status"),
			fieldtype: "Select",
			options: [
				"",
				"Ready",
				"Warning",
				"Not Ready",
				"Not Selected",
			],
		},
		{
			fieldname: "online_category",
			label: __("Online Category"),
			fieldtype: "Link",
			options: "Online Category",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "include_disabled",
			label: __("Include Disabled Items"),
			fieldtype: "Check",
			default: 0,
		},
	],
};
