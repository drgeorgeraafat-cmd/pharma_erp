
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class OnlineOrderNotificationDeliverySettings(Document):
    def validate(self):
        if cint(self.outbound_email_enabled):
            frappe.throw(
                _(
                    "Outbound email activation is not available in Step 4D. "
                    "Use Preview Only until Step 4E is installed and accepted."
                )
            )

        allowed_modes = {"Disabled", "Preview Only"}
        if self.delivery_mode not in allowed_modes:
            frappe.throw(_("Step 4D supports Disabled or Preview Only mode."))

        self.max_batch_size = max(1, min(cint(self.max_batch_size or 20), 100))
        self.max_attempts = max(1, min(cint(self.max_attempts or 3), 10))
        self.retry_delay_minutes = max(
            1, min(cint(self.retry_delay_minutes or 15), 1440)
        )
        self.require_recipient_hash_match = 1
