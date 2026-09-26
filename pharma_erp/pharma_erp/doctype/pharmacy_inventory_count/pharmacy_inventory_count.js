frappe.ui.form.on("Pharmacy Inventory Count", {
    setup(frm) {
        frm.set_query("warehouse", () => ({
            filters: {
                company: frm.doc.company,
                is_group: 0,
                disabled: 0,
            },
        }));
        frm.set_query("scope_location", () => {
            const filters = { warehouse: frm.doc.warehouse, disabled: 0 };
            if (["Zone", "Aisle", "Shelf", "Bin"].includes(frm.doc.scope_type)) {
                filters.location_type = frm.doc.scope_type;
            }
            return { filters };
        });
        frm.set_query("item_code", () => ({ filters: { disabled: 0, is_stock_item: 1 } }));
        frm.set_query("batch_no", () => ({
            filters: frm.doc.item_code ? { item: frm.doc.item_code, disabled: 0 } : { disabled: 0 },
        }));
    },

    refresh(frm) {
        set_scope_visibility(frm);
        configure_grid(frm);
        add_actions(frm);

        if (!frm.is_new() && frm.doc.status === "Counting" && frm.doc.blind_count) {
            frm.set_intro(__("Blind Count is active. Expected quantities remain hidden until counting is completed."), "blue");
        } else if (!frm.is_new() && frm.doc.status === "Posted") {
            frm.set_intro(__("Posted. ERPNext Stock Ledger remains the official warehouse stock source."), "green");
        }
    },

    scope_type(frm) {
        set_scope_visibility(frm);
        frm.set_value("scope_location", null);
        if (frm.doc.scope_type !== "Item") frm.set_value("item_code", null);
        if (frm.doc.scope_type !== "Item Group") frm.set_value("item_group", null);
        if (frm.doc.scope_type !== "Batch") frm.set_value("batch_no", null);
    },

    warehouse(frm) {
        if (!frm.doc.warehouse) return;
        frappe.db.get_value("Pharmacy Warehouse Profile", { warehouse: frm.doc.warehouse }, "branch").then((r) => {
            if (r.message && r.message.branch && frm.doc.branch !== r.message.branch) {
                frm.set_value("branch", r.message.branch);
            }
        });
    },

    item_code(frm) {
        if (frm.doc.scope_type === "Batch" && frm.doc.item_code) {
            frm.set_query("batch_no", () => ({ filters: { item: frm.doc.item_code, disabled: 0 } }));
        }
    },

    blind_count(frm) {
        configure_grid(frm);
    },
});

frappe.ui.form.on("Pharmacy Inventory Count Item", {
    entry_mode(frm, cdt, cdn) {
        if (frm.doc.status !== "Counting") return;
        const row = locals[cdt][cdn];
        if (row.entry_mode === "Box / Unit") {
            update_pack_actual(cdt, cdn);
        }
    },

    actual_boxes(frm, cdt, cdn) {
        if (frm.doc.status !== "Counting") return;
        update_pack_actual(cdt, cdn);
    },

    actual_loose_units(frm, cdt, cdn) {
        if (frm.doc.status !== "Counting") return;
        update_pack_actual(cdt, cdn);
    },

    actual_qty(frm, cdt, cdn) {
        if (frm.doc.status !== "Counting") return;
        const row = locals[cdt][cdn];
        frappe.model.set_value(cdt, cdn, "count_entered", 1);
        if (flt(row.actual_qty) <= 0) {
            frappe.model.set_value(cdt, cdn, "resolution_status", "Confirmed Zero");
        } else if (["Pending", "Confirmed Zero", ""].includes(row.resolution_status || "")) {
            frappe.model.set_value(cdt, cdn, "resolution_status", "Counted");
        }
    },

    resolution_status(frm, cdt, cdn) {
        if (frm.doc.status !== "Counting") return;
        const row = locals[cdt][cdn];
        if (row.resolution_status === "Confirmed Zero") {
            frappe.model.set_value(cdt, cdn, "actual_qty", 0);
            frappe.model.set_value(cdt, cdn, "count_entered", 1);
        }
        if (row.resolution_status === "Found Elsewhere") {
            frappe.model.set_value(cdt, cdn, "count_entered", 1);
        }
    },

    posting_batch_no(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code) return;
        frm.fields_dict.items.grid.get_field("posting_batch_no").get_query = () => ({
            filters: { item: row.item_code, disabled: 0 },
        });
    },
});


function update_pack_actual(cdt, cdn) {
    const row = locals[cdt][cdn];
    const pack = flt(row.pack_size || 1) || 1;
    const boxes = cint(row.actual_boxes || 0);
    const units = cint(row.actual_loose_units || 0);
    if (row.box_only && units > 0) {
        frappe.msgprint(__("This Item is Box Only; loose units are not allowed."));
        frappe.model.set_value(cdt, cdn, "actual_loose_units", 0);
        return;
    }
    frappe.model.set_value(cdt, cdn, "count_entered", 1);
    frappe.model.set_value(cdt, cdn, "actual_qty", flt(boxes + (units / pack), 6));
}

function set_scope_visibility(frm) {
    const type = frm.doc.scope_type;
    const locked = ![undefined, null, "", "Draft"].includes(frm.doc.status);
    const locationScope = ["Zone", "Aisle", "Shelf", "Bin"].includes(type);

    frm.toggle_display("warehouse", type !== "Branch");
    frm.toggle_display("scope_location", locationScope);
    frm.toggle_display("item_code", ["Item", "Batch"].includes(type));
    frm.toggle_display("item_group", type === "Item Group");
    frm.toggle_display("batch_no", type === "Batch");

    ["company", "branch", "scope_type", "warehouse", "scope_location", "item_code", "item_group", "batch_no"]
        .forEach((fieldname) => frm.set_df_property(fieldname, "read_only", locked ? 1 : 0));
}

function configure_grid(frm) {
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    if (!grid) return;
    const counting = frm.doc.status === "Counting";
    const review = ["Count Completed", "Under Review"].includes(frm.doc.status);
    const blind = counting && cint(frm.doc.blind_count);

    ["snapshot_qty", "warehouse_snapshot_qty", "expected_qty_at_count", "variance_qty", "variance_value", "valuation_rate_snapshot"]
        .forEach((fieldname) => grid.update_docfield_property(fieldname, "hidden", blind ? 1 : 0));

    grid.update_docfield_property("actual_qty", "read_only", counting ? 0 : 1);
    grid.update_docfield_property("entry_mode", "read_only", counting ? 0 : 1);
    grid.update_docfield_property("actual_boxes", "read_only", counting ? 0 : 1);
    grid.update_docfield_property("actual_loose_units", "read_only", counting ? 0 : 1);
    grid.update_docfield_property("resolution_status", "read_only", counting ? 0 : 1);
    grid.update_docfield_property("found_location", "read_only", counting ? 0 : 1);
    grid.update_docfield_property("found_elsewhere_qty", "read_only", counting ? 0 : 1);

    ["reason_code", "reason_note", "posting_batch_no", "observed_batch_no"]
        .forEach((fieldname) => grid.update_docfield_property(fieldname, "read_only", (counting || review) ? 0 : 1));

    grid.refresh();
}

function selected_item_rows(frm) {
    const selected = frm.get_selected ? frm.get_selected() : {};
    return (selected && selected.items) || [];
}

function add_actions(frm) {
    if (frm.is_new()) return;

    if (frm.doc.status === "Draft") {
        frm.add_custom_button(__("Start Count"), () => {
            frm.save().then(() => frm.call({ method: "start_count", freeze: true, freeze_message: __("Creating inventory snapshot...") }))
                .then(() => frm.reload_doc());
        }).addClass("btn-primary");
    }

    if (frm.doc.status === "Counting") {
        frm.add_custom_button(__("Add Found Item"), () => show_found_item_dialog(frm), __("Counting"));
        frm.add_custom_button(__("Authorize Exclusion"), () => authorize_exclusion(frm), __("Counting"));
        frm.add_custom_button(__("Complete Count"), () => {
            frm.save().then(() => frm.call({ method: "complete_count", freeze: true, freeze_message: __("Checking count completeness...") }))
                .then((r) => {
                    const result = r.message || {};
                    if (!result.completed) {
                        show_missing_review(result);
                    }
                    return frm.reload_doc();
                });
        }).addClass("btn-primary");
    }

    if (frm.doc.status === "Count Completed") {
        frm.add_custom_button(__("Begin Review"), () => {
            frm.call({ method: "begin_review", freeze: true }).then(() => frm.reload_doc());
        }).addClass("btn-primary");
        frm.add_custom_button(__("Request Recount"), () => request_recount(frm));
    }

    if (frm.doc.status === "Under Review") {
        frm.add_custom_button(__("Request Recount"), () => request_recount(frm));
        frm.add_custom_button(__("Approve Count"), () => {
            frm.save().then(() => frm.call({ method: "approve_count", freeze: true, freeze_message: __("Validating approval...") }))
                .then(() => frm.reload_doc());
        }).addClass("btn-primary");
    }

    if (frm.doc.status === "Approved") {
        frm.add_custom_button(__("Post Count"), () => {
            frappe.confirm(
                __("Post approved variances now? Warehouse differences will use ERPNext Stock Reconciliation."),
                () => frm.call({ method: "post_count", freeze: true, freeze_message: __("Posting inventory variances...") })
                    .then(() => frm.reload_doc())
            );
        }).addClass("btn-primary");
    }

    if (!["Cancelled"].includes(frm.doc.status)) {
        frm.add_custom_button(__("Cancel Count"), () => cancel_count(frm), __("Actions"));
    }
}

function show_found_item_dialog(frm) {
    const fields = [
        { fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("Item"), reqd: 1, get_query: () => ({ filters: { disabled: 0, is_stock_item: 1 } }) },
    ];
    if (frm.doc.scope_type === "Branch") {
        fields.push({ fieldname: "warehouse", fieldtype: "Link", options: "Warehouse", label: __("Warehouse"), reqd: 1, get_query: () => ({ filters: { company: frm.doc.company, is_group: 0, disabled: 0 } }) });
    }
    if (["Zone", "Aisle", "Shelf", "Bin"].includes(frm.doc.scope_type)) {
        fields.push({ fieldname: "location", fieldtype: "Link", options: "Pharmacy Storage Location", label: __("Location"), default: frm.doc.scope_location, reqd: 1, get_query: () => ({ filters: { warehouse: frm.doc.warehouse, disabled: 0 } }) });
    }
    fields.push({ fieldname: "batch_no", fieldtype: "Link", options: "Batch", label: __("Batch (optional only for explicit physical batch)"), get_query: () => ({ filters: { item: dialog.get_value("item_code"), disabled: 0 } }) });

    const dialog = new frappe.ui.Dialog({
        title: __("Add Found Item"),
        fields,
        primary_action_label: __("Add"),
        primary_action(values) {
            dialog.hide();
            frm.call({
                method: "add_found_item",
                args: values,
                freeze: true,
                freeze_message: __("Adding physical item..."),
            }).then(() => frm.reload_doc());
        },
    });
    dialog.show();
}

function show_missing_review(result) {
    const rows = (result.missing || []).slice(0, 50);
    const body = rows.map((row) => {
        const location = row.location ? ` — ${frappe.utils.escape_html(row.location)}` : "";
        return `<li><b>${frappe.utils.escape_html(row.item_code)}</b>${location}</li>`;
    }).join("");
    frappe.msgprint({
        title: __("Missing Expected Items Review"),
        indicator: "orange",
        message: `<p>${__("{0} expected item(s) are still unresolved. Blank does not mean zero. Count them or explicitly confirm/resolve them before completion.", [result.missing_count])}</p><ul>${body}</ul>`,
    });
}

function request_recount(frm) {
    const rows = selected_item_rows(frm);
    if (!rows.length) {
        frappe.msgprint(__("Select one or more Count Lines using the grid checkboxes, then request Recount."));
        return;
    }
    frappe.confirm(
        __("Request a new physical count for {0} selected row(s)? Previous count evidence will remain in the event log.", [rows.length]),
        () => frm.call({ method: "request_recount", args: { row_names: JSON.stringify(rows) }, freeze: true })
            .then(() => frm.reload_doc())
    );
}

function authorize_exclusion(frm) {
    const rows = selected_item_rows(frm);
    if (!rows.length) {
        frappe.msgprint(__("Select one or more Count Lines first."));
        return;
    }
    frappe.prompt(
        [{ fieldname: "reason", fieldtype: "Small Text", label: __("Authorized Exclusion Reason"), reqd: 1 }],
        (values) => frm.call({
            method: "authorize_exclusion",
            args: { row_names: JSON.stringify(rows), reason: values.reason },
            freeze: true,
        }).then(() => frm.reload_doc()),
        __("Authorize Exclusion"),
        __("Confirm")
    );
}

function cancel_count(frm) {
    frappe.prompt(
        [{ fieldname: "reason", fieldtype: "Small Text", label: __("Cancellation Reason"), reqd: 1 }],
        (values) => {
            frappe.confirm(
                frm.doc.status === "Posted"
                    ? __("This will reverse the linked Stock Reconciliation / Location adjustments. Continue?")
                    : __("Cancel this Inventory Count?"),
                () => {
                    frm.call("cancel_count", { reason: values.reason })
                        .then(() => {
                            frappe.show_alert({
                                message: __("Inventory Count cancelled and linked stock effects reversed."),
                                indicator: "green",
                            });
                            window.location.reload();
                        });
                }
            );
        },
        __("Cancel Inventory Count"),
        __("Continue")
    );
}
