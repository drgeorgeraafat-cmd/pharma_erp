frappe.query_reports["Shift Cash Integrity Summary"] = {
  filters: [
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      default: frappe.defaults.get_user_default("Company")
    },
    {
      fieldname: "branch",
      label: __("Branch"),
      fieldtype: "Link",
      options: "Branch"
    },
    {
      fieldname: "shift",
      label: __("Shift"),
      fieldtype: "Link",
      options: "Pharmacy Shift Closing",
      reqd: 1
    }
  ]
};
