
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class OnlineOrderNotificationDeliverySettings(Document):
    def validate(self):
        controlled = bool(
            getattr(self.flags, "step4e_controlled_update", False)
        )

        if (
            cint(self.outbound_email_enabled)
            or cint(self.pilot_mode_enabled)
            or self.delivery_mode == "Controlled Pilot"
            or self.activation_status == "Active"
        ) and not controlled:
            frappe.throw(
                _(
                    "Controlled Pilot activation must be performed using the "
                    "Step 4E activation action."
                )
            )

        allowed_modes = {"Disabled", "Preview Only", "Controlled Pilot"}
        if self.delivery_mode not in allowed_modes:
            frappe.throw(_("Unsupported notification delivery mode."))

        self.max_batch_size = max(
            1, min(cint(self.max_batch_size or 20), 100)
        )
        self.max_attempts = max(
            1, min(cint(self.max_attempts or 3), 10)
        )
        self.retry_delay_minutes = max(
            1, min(cint(self.retry_delay_minutes or 15), 1440)
        )
        self.daily_dispatch_limit = max(
            1, min(cint(self.daily_dispatch_limit or 5), 50)
        )
        self.require_recipient_hash_match = 1
        self.allow_actual_customer_recipient = 0
