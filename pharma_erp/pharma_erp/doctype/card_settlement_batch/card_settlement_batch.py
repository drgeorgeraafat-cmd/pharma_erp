import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now


class CardSettlementBatch(Document):
    def before_submit(self):
        if not self.items:
            frappe.throw(_("The card batch has no transactions."))

        system_total = sum(flt(row.amount) for row in self.items)
        self.transaction_count = len(self.items)
        self.system_total = flt(system_total)
        self.difference = flt(self.machine_total) - flt(self.system_total)
        self.outstanding_amount = flt(self.system_total) - flt(self.settled_amount)

        if abs(flt(self.difference)) > 0.01:
            frappe.throw(_("Machine Total must equal System Total before submission."))

        row_names = tuple(
            row.payment_row_name
            for row in self.items
            if row.payment_row_name
        )

        if row_names:
            duplicates = frappe.db.sql(
                """
                SELECT item.payment_row_name
                FROM `tabCard Settlement Batch Item` item
                INNER JOIN `tabCard Settlement Batch` batch
                    ON batch.name = item.parent
                WHERE item.payment_row_name IN %(row_names)s
                  AND batch.name != %(batch_name)s
                  AND batch.docstatus != 2
                LIMIT 1
                """,
                {
                    "row_names": row_names,
                    "batch_name": self.name,
                },
            )

            if duplicates:
                frappe.throw(_("A card transaction is already included in another batch."))

        self.status = "Awaiting Bank Settlement"
        self.reviewed_by = frappe.session.user
        self.reviewed_at = now()

    def before_cancel(self):
        if flt(self.settled_amount) > 0:
            frappe.throw(_("A settled or partially settled card batch cannot be cancelled."))
