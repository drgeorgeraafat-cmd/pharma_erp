frappe.query_reports["Online Order Operations Funnel"] = {
  filters: [
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.add_days(frappe.datetime.get_today(), -7)
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      reqd: 1,
      default: frappe.datetime.get_today()
    },
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      reqd: 1,
      default: frappe.defaults.get_user_default("Company")
    },
    {
      fieldname: "branch",
      label: __("Branch"),
      fieldtype: "Link",
      options: "Branch"
    },
    {
      fieldname: "status",
      label: __("Status"),
      fieldtype: "Data"
    },
    {
      fieldname: "fulfilment_type",
      label: __("Fulfilment Type"),
      fieldtype: "Data"
    },
    {
      fieldname: "payment_method",
      label: __("Payment Method"),
      fieldtype: "Link",
      options: "Mode of Payment"
    },
    {
      fieldname: "page",
      label: __("Page"),
      fieldtype: "Int",
      default: 1
    },
    {
      fieldname: "page_size",
      label: __("Page Size"),
      fieldtype: "Int",
      default: 50
    }
  ]
};
