# Copyright (c) 2026, ZeePharaoh and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class InternalRetailPriceLot(Document):
    def validate(self):
        if self.item_code:
            item = frappe.db.get_value(
                "Item",
                self.item_code,
                ["item_name", "has_batch_no", "custom_pack_size"],
                as_dict=True,
            ) or frappe._dict()
            if item.get("has_batch_no"):
                frappe.throw(
                    _("Internal Retail Price Lots are only for items without ERPNext Batch tracking.")
                )
            self.item_name = item.get("item_name") or self.item_name
            if not flt(self.pack_size):
                self.pack_size = flt(item.get("custom_pack_size") or 1) or 1

        self.opening_qty = flt(self.opening_qty, 6)
        self.received_qty = flt(self.received_qty, 6)
        self.returned_qty = flt(self.returned_qty, 6)
        self.adjustment_qty = flt(self.adjustment_qty, 6)
        self.sold_qty = flt(self.sold_qty, 6)
        self.available_qty = flt(
            self.opening_qty
            + self.received_qty
            + self.returned_qty
            + self.adjustment_qty
            - self.sold_qty,
            6,
        )

        if self.available_qty < -0.000001:
            frappe.throw(
                _("Retail Price Lot {0} cannot have negative available quantity.").format(
                    self.name or _("New")
                )
            )
        if abs(self.available_qty) <= 0.000001:
            self.available_qty = 0

        if not self.source_date:
            self.source_date = nowdate()
        if not self.barcode_value and self.name:
            self.barcode_value = self.name
        if not self.qr_value and self.name:
            self.qr_value = f"RPL:{self.name}"

        if self.disabled:
            self.status = "Disabled"
        elif self.available_qty <= 0:
            self.status = "Depleted"
        else:
            self.status = "Open"

    def after_insert(self):
        values = {}
        if not self.barcode_value:
            values["barcode_value"] = self.name
        if not self.qr_value:
            values["qr_value"] = f"RPL:{self.name}"
        if values:
            frappe.db.set_value(self.doctype, self.name, values, update_modified=False)
