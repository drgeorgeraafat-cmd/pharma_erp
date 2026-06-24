import hashlib

import frappe
from frappe import _
from frappe.utils import cint


SERVER_SCRIPT_HASHES = {'Card POS Terminal - Validate': '70450325267ddf3b80e25c3e4e08b485272e16398acd632a5c0f2cde7d1d5245', 'Card Settlement Batch - Before Submit': 'c18ad740c5d383fc5438b14a9fafaf09559dacd57168bc3c825e84c0f0ec8c66', 'Card Settlement Batch - Before Cancel': '331b93ddea7c40a3416c998a4e2a12fd8fb01acf93111d2e7c0ae2de67a4c579', 'Card Bank Settlement - Before Submit': 'e125fd49306700b539fe4bd11332a11a8d24302cefa7e53885cba5b86f68d939', 'Card Bank Settlement - After Submit': '5c6c247abbd3de915a33e0556f1b3472cd79dca547739222a06c4d91fa0de266', 'Card Bank Settlement - Before Cancel': '7235121b95b4ba6a543b9b87ae3e2958038cd2158dd0f65b3d193bd7d08b5962', 'Card Bank Settlement - After Cancel': '958807f0e4d6d4c72e2fd7182a5164b07a08acc6ed7356b86d9ff08fbde1b176', 'Shift Cash Movement - Before Submit': '95d878711e0c3c023ce97b5b1c0568e91e176cb8d578bd446a70de6011983115', 'Shift Cash Movement - After Submit': '0eaf9b112e9416a796fb30582009d138c5cbfd640039ddb6a73f05c65c627f05', 'Shift Cash Movement - Before Cancel': 'cbf05338c33ef6bbe78ebd265f9d735809d3392813798eda896910d023607b49', 'Shift Payment Reconciliation - Before Submit': '7f713c2940cd761307f563f93d669328d7e18743935be4f28f0c5b3176f797d3', 'Shift Payment Reconciliation - After Submit': 'ef108cca8f62c8695cc8ea25e96724d220877736f86e1f78dc640eb699820591', 'Shift Payment Reconciliation - Before Cancel': 'cbf05338c33ef6bbe78ebd265f9d735809d3392813798eda896910d023607b49'}

CLIENT_SCRIPT_HASHES = {'Card Settlement Batch - Client': '9abd5ef2d6b83b71b5a8e0543dc2fa0f79b3b78104f7a0a723f27e1cb29b01b4', 'Card Bank Settlement - Client': '30bfe60b30581f41799d4532a0cde71c7b5d5d3946620720a4a6a256b75ce747'}


def _sha256(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _disable_server_script(name, expected_hash):
    if not frappe.db.exists("Server Script", name):
        return

    row = frappe.db.get_value(
        "Server Script",
        name,
        ["script", "disabled"],
        as_dict=True,
    )

    if cint(row.disabled):
        return

    actual_hash = _sha256(row.script)
    if actual_hash != expected_hash:
        frappe.throw(
            _("Migration stopped because Server Script content changed: {0}").format(name)
        )

    frappe.db.set_value(
        "Server Script",
        name,
        "disabled",
        1,
        update_modified=False,
    )


def _disable_client_script(name, expected_hash):
    if not frappe.db.exists("Client Script", name):
        return

    row = frappe.db.get_value(
        "Client Script",
        name,
        ["script", "enabled"],
        as_dict=True,
    )

    if not cint(row.enabled):
        return

    actual_hash = _sha256(row.script)
    if actual_hash != expected_hash:
        frappe.throw(
            _("Migration stopped because Client Script content changed: {0}").format(name)
        )

    frappe.db.set_value(
        "Client Script",
        name,
        "enabled",
        0,
        update_modified=False,
    )


def execute():
    for name, expected_hash in SERVER_SCRIPT_HASHES.items():
        _disable_server_script(name, expected_hash)

    for name, expected_hash in CLIENT_SCRIPT_HASHES.items():
        _disable_client_script(name, expected_hash)

    frappe.clear_cache()
