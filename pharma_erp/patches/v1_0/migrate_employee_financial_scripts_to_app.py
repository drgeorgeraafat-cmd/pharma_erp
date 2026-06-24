import hashlib

import frappe


SERVER_SCRIPTS = {
    "Driver Shortage - Before Submit": "08f7b992966e3771bbd426ce25053bdf5e170691b2dbc6f305c7cd60a070b8a0",
    "Driver Shortage - After Submit": "7c9f104e19caaff08d94c26211823bb0ab1b3c34b0fb526988f1b0a84aa4a231",
    "Driver Shortage - Before Cancel": "0e460036ba2f2493fa3b3a5a9528843061a02ae7bc41f3e4cb9b8bedf95c146c",
    "Employee Cash Advance - Before Submit": "5c177332394808fb2e5d4d9d6615409b11111a43d796f5b61f3ea9df598bcf5c",
    "Employee Cash Advance - After Submit": "474a4237f5bd8f66b0dfada8f0b7cddd5266ee5285376e9ae9df1eb4364141a3",
    "Employee Cash Advance - Before Cancel": "521371529c74016663d299f7123ff414f5cd410aa993418a4669c425a928d931",
}

CLIENT_SCRIPTS = {
    "Driver Shortage - Client Script": "a49cf7aad32c969c0cdceb780a249ebd357008942f5f06207ce8c8abbb3f14bd",
    "Employee Cash Advance - Client Script": "4b51e1695f3be2503af27eddb541f4d2cdf73b8cede46fc23fccbb9acfd1b398",
}


def execute():
    """Disable database scripts after their logic has moved into app controllers."""
    for name, expected_hash in SERVER_SCRIPTS.items():
        row = frappe.db.get_value(
            "Server Script", name, ["script", "disabled"], as_dict=True
        )
        if not row:
            continue
        _validate_script(name, row.script, expected_hash)
        if not row.disabled:
            frappe.db.set_value(
                "Server Script", name, "disabled", 1, update_modified=False
            )

    for name, expected_hash in CLIENT_SCRIPTS.items():
        row = frappe.db.get_value(
            "Client Script", name, ["script", "enabled"], as_dict=True
        )
        if not row:
            continue
        _validate_script(name, row.script, expected_hash)
        if row.enabled:
            frappe.db.set_value(
                "Client Script", name, "enabled", 0, update_modified=False
            )

    frappe.clear_cache()


def _validate_script(name, script, expected_hash):
    normalized = (script or "").replace("\r\n", "\n")
    actual_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        frappe.throw(
            "Migration stopped because script content changed: "
            + name
            + ". Expected hash "
            + expected_hash
            + ", found "
            + actual_hash
        )
