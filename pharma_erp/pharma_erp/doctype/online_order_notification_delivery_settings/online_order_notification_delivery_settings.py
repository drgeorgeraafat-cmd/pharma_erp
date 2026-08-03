import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class OnlineOrderNotificationDeliverySettings(Document):
    def validate(self):
        controlled = bool(
            getattr(self.flags, "step4e_controlled_update", False)
            or getattr(self.flags, "step4f_controlled_update", False)
        )

        active_requested = bool(
            cint(self.outbound_email_enabled)
            or cint(self.pilot_mode_enabled)
            or cint(self.customer_mode_enabled)
            or cint(self.automatic_customer_dispatch_enabled)
            or cint(self.allow_actual_customer_recipient)
            or self.delivery_mode in ("Controlled Pilot", "Controlled Customer")
            or self.activation_status == "Active"
        )
        if active_requested and not controlled:
            frappe.throw(
                _(
                    "Notification delivery activation must be performed using "
                    "the controlled Step 4E/4F actions."
                )
            )

        allowed_modes = {
            "Disabled",
            "Preview Only",
            "Controlled Pilot",
            "Controlled Customer",
        }
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
        self.daily_customer_dispatch_limit = max(
            1, min(cint(self.daily_customer_dispatch_limit or 20), 200)
        )
        self.require_recipient_hash_match = 1
        self.customer_dispatch_scope = "Post-Cutover Events Only"

        pilot_active = bool(
            self.delivery_mode == "Controlled Pilot"
            and cint(self.outbound_email_enabled)
            and cint(self.pilot_mode_enabled)
            and not cint(self.customer_mode_enabled)
            and self.activation_status == "Active"
        )
        customer_active = bool(
            self.delivery_mode == "Controlled Customer"
            and cint(self.outbound_email_enabled)
            and cint(self.customer_mode_enabled)
            and cint(self.allow_actual_customer_recipient)
            and not cint(self.pilot_mode_enabled)
            and self.activation_status == "Active"
        )

        if pilot_active:
            self.customer_mode_enabled = 0
            self.automatic_customer_dispatch_enabled = 0
            self.allow_actual_customer_recipient = 0
        elif customer_active:
            self.pilot_mode_enabled = 0
            if not self.customer_dispatch_cutover_at:
                frappe.throw(
                    _(
                        "Controlled Customer mode requires a permanent "
                        "post-cutover timestamp."
                    )
                )
        else:
            self.pilot_mode_enabled = 0
            self.customer_mode_enabled = 0
            self.automatic_customer_dispatch_enabled = 0
            self.allow_actual_customer_recipient = 0
            if self.delivery_mode not in ("Disabled", "Preview Only"):
                self.delivery_mode = "Preview Only"
            if self.activation_status == "Active":
                self.activation_status = "Inactive"

        if cint(self.automatic_customer_dispatch_enabled) and not customer_active:
            frappe.throw(
                _(
                    "Automatic customer dispatch requires active Controlled "
                    "Customer mode."
                )
            )
