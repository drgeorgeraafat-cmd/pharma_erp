frappe.listview_settings["Online Order"] = {
    add_fields: ["status", "grand_total", "currency"],
    get_indicator(doc) {
        const colours = {
            "Draft": "grey",
            "Placed": "blue",
            "Under Review": "orange",
            "Prescription Review": "orange",
            "Stock Review": "orange",
            "Partially Available": "yellow",
            "Awaiting Customer Decision": "yellow",
            "Ready for Payment": "purple",
            "Payment Verification": "purple",
            "Payment Failed": "red",
            "Confirmed": "green",
            "Preparing": "blue",
            "Ready for Delivery": "blue",
            "Ready for Pickup": "blue",
            "Out for Delivery": "orange",
            "Delivered": "green",
            "Completed": "green",
            "Returned": "red",
            "On Hold": "yellow",
            "Rejected": "red",
            "Cancelled": "red",
        };
        return [__(doc.status), colours[doc.status] || "grey", `status,=,${doc.status}`];
    },
};
