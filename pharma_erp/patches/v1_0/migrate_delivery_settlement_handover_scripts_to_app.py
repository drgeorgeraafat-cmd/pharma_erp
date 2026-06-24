import hashlib

import frappe


SERVER_SCRIPTS = {
    "Cancel Delivery Handover Journal": "7235121b95b4ba6a543b9b87ae3e2958038cd2158dd0f65b3d193bd7d08b5962",
    "Get Delivery Settlement Data": "2f947886dfceff8d8e077c2e7c0e1c8c03d4bb2d6d71d0f75b0d3d1b631cc718",
    "Clear Settlement Links After Cancel": "a04c1872de1aff406c81faaedcf521ac367dd35a1e4fb7c71c0761ea5b0d28e1",
    "Validate Delivery Settlement Cancel": "a12ae941b5744f084fc546ca35e33b0f388188a9a1f3d2158cab699a1de97e7b",
    "Validate Final Delivery Settlement": "d0a4faef6c23dd425acb4967555ae4a638966e7f118a73bf14dfd11167f86026",
}

CLIENT_SCRIPTS = {
    "Delivery Settlement v2": "76c97f0ce6fa84b2f16cb280be91c73640a72cee0af4835f4ca5658d401f8237",
    "Delivery Handover": "1a1fb5643d18141f272d3c789f4d7db17d78246a261f202503774e74ada3ebec",
}


def execute():
    """Disable database scripts after their logic has moved into app code."""
    for name, expected_hash in SERVER_SCRIPTS.items():
        row = frappe.db.get_value(
            "Server Script",
            name,
            ["script", "disabled"],
            as_dict=True,
        )
        if not row:
            continue

        _validate_script(name, row.script, expected_hash)
        if not row.disabled:
            frappe.db.set_value(
                "Server Script",
                name,
                "disabled",
                1,
                update_modified=False,
            )

    for name, expected_hash in CLIENT_SCRIPTS.items():
        row = frappe.db.get_value(
            "Client Script",
            name,
            ["script", "enabled"],
            as_dict=True,
        )
        if not row:
            continue

        _validate_script(name, row.script, expected_hash)
        if row.enabled:
            frappe.db.set_value(
                "Client Script",
                name,
                "enabled",
                0,
                update_modified=False,
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
