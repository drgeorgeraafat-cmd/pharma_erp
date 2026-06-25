frappe.query_reports["Treasury Daily Review"] = {
    filters: [
        {
            fieldname: "company",
            label: __("الشركة"),
            fieldtype: "Link",
            options: "Company",
            reqd: 1,
            default: frappe.defaults.get_user_default("Company"),
            on_change() {
                frappe.query_report.set_filter_value("account", "");
            },
        },
        {
            fieldname: "from_date",
            label: __("من تاريخ"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.get_today(),
        },
        {
            fieldname: "to_date",
            label: __("إلى تاريخ"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.get_today(),
        },
        {
            fieldname: "account_type",
            label: __("نوع الحساب"),
            fieldtype: "Select",
            options: "\nCash\nBank",
            on_change() {
                frappe.query_report.set_filter_value("account", "");
            },
        },
        {
            fieldname: "account",
            label: __("الخزنة أو البنك"),
            fieldtype: "Link",
            options: "Account",
            get_query() {
                const filters = {
                    company: frappe.query_report.get_filter_value("company"),
                    root_type: "Asset",
                    is_group: 0,
                    disabled: 0,
                    account_type: ["in", ["Cash", "Bank"]],
                };
                const accountType = frappe.query_report.get_filter_value("account_type");
                if (accountType) filters.account_type = accountType;
                return { filters };
            },
        },
        {
            fieldname: "movement_family",
            label: __("نوع الحركة"),
            fieldtype: "Select",
            options: [
                "",
                "Shift Cash Movement",
                "General Expense",
                "General Receipt",
                "Internal Transfer",
                "Customer Receipt",
                "Supplier Payment",
                "POS / Sales",
                "Sales Return",
                "Card Settlement",
                "Electronic Settlement",
                "Other Journal Entry",
                "Other",
            ].join("\n"),
        },
        {
            fieldname: "direction",
            label: __("الاتجاه"),
            fieldtype: "Select",
            options: "\nIn\nOut",
        },
        {
            fieldname: "reference_no",
            label: __("رقم المرجع"),
            fieldtype: "Data",
        },
    ],

    onload(report) {
        report.page.add_inner_button(
            __("فتح إدارة الخزينة"),
            () => frappe.set_route("treasury-management"),
            __("الخزينة"),
        );
    },
};
