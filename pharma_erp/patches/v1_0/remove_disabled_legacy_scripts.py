import frappe
from frappe.utils import cint


DISABLED_SERVER_SCRIPTS = (
    "Auto Create Driver Shortage After Final Handover",
    "Recalculate Settlement After Handover Cancel",
    "Settlement After Handover",
    "Validate Delivery Handover",
    "Pharmacy Shift ClosinG",
    "Delivery Settlement Recalculate",
    "Process Delivery Settlement",
    "POS_Clean_Bundle",
    "POS Auto FEFO Batch",
    "uto Split Batches",
)


DISABLED_CLIENT_SCRIPTS = (
    "Pharmacy Shift Closing",
    "Delivery Settlement Logic",
    "GPT 2",
    "GPT",
    "Mixed Quantity Automation",
)


def execute():
    """Remove obsolete scripts only when they are already disabled."""

    for script_name in DISABLED_SERVER_SCRIPTS:
        if not frappe.db.exists("Server Script", script_name):
            continue

        disabled = cint(
            frappe.db.get_value(
                "Server Script",
                script_name,
                "disabled",
            )
        )

        # Do not delete a script if somebody enabled it again.
        if disabled:
            frappe.delete_doc(
                "Server Script",
                script_name,
                force=True,
                ignore_permissions=True,
            )

    for script_name in DISABLED_CLIENT_SCRIPTS:
        if not frappe.db.exists("Client Script", script_name):
            continue

        enabled = cint(
            frappe.db.get_value(
                "Client Script",
                script_name,
                "enabled",
            )
        )

        # Delete only scripts that remain disabled.
        if not enabled:
            frappe.delete_doc(
                "Client Script",
                script_name,
                force=True,
                ignore_permissions=True,
            )

    frappe.clear_cache()
