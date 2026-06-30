// Copyright (c) 2026, ZeePharaoh and contributors
// For license information, please see license.txt

const PURCHASE_SHORTCUT_FIELDS = [
    "shortcut_add_item",
    "shortcut_focus_item_search",
    "shortcut_delete_row",
    "shortcut_save_draft",
    "shortcut_new_invoice",
    "shortcut_open_official_document",
];

const PURCHASE_SHORTCUT_DEFAULTS = {
    shortcut_add_item: "F1",
    shortcut_focus_item_search: "F2",
    shortcut_delete_row: "CTRL+DELETE",
    shortcut_save_draft: "CTRL+S",
    shortcut_new_invoice: "CTRL+N",
    shortcut_open_official_document: "CTRL+O",
};

function normalize_purchase_shortcut(value) {
    return String(value || "").trim().toUpperCase().replace(/\s+/g, "");
}

frappe.ui.form.on("Pharmacy Purchase Settings", {
    setup(frm) {
        ["fraction_adjustment_account", "claim_settlement_discount_account"].forEach((fieldname) => {
            frm.set_query(fieldname, () => ({ filters: { is_group: 0, disabled: 0 } }));
        });
    },
    refresh(frm) {
        frm.set_intro(
            __("Controls pharmacy purchase invoices, supplier bills, batches, retail-price updates, and purchase-page keyboard shortcuts."),
            "blue"
        );

        frm.add_custom_button(__("Reset Purchase Shortcuts"), () => {
            Object.entries(PURCHASE_SHORTCUT_DEFAULTS).forEach(([fieldname, value]) => {
                frm.set_value(fieldname, value);
            });
        });
    },

    validate(frm) {
        const used = {};
        PURCHASE_SHORTCUT_FIELDS.forEach((fieldname) => {
            const normalized = normalize_purchase_shortcut(frm.doc[fieldname]);
            frm.doc[fieldname] = normalized;
            if (!normalized) return;
            if (used[normalized]) {
                frappe.throw(
                    __("Shortcut {0} is assigned to both {1} and {2}.", [
                        normalized,
                        frm.fields_dict[used[normalized]]?.df?.label || used[normalized],
                        frm.fields_dict[fieldname]?.df?.label || fieldname,
                    ])
                );
            }
            used[normalized] = fieldname;
        });
    },
});
