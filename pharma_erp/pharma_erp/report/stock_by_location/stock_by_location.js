frappe.query_reports["Stock by Location"] = {
    filters: [
        {fieldname:"warehouse",label:__("Warehouse"),fieldtype:"Link",options:"Warehouse"},
        {fieldname:"item_code",label:__("Item"),fieldtype:"Link",options:"Item"},
        {fieldname:"item_group",label:__("Item Group"),fieldtype:"Link",options:"Item Group"},
        {fieldname:"location",label:__("Location"),fieldtype:"Link",options:"Pharmacy Storage Location"},
        {fieldname:"batch_no",label:__("Batch"),fieldtype:"Link",options:"Batch"},
        {fieldname:"only_variance",label:__("Only With Unallocated / Variance"),fieldtype:"Check",default:0}
    ]
};
