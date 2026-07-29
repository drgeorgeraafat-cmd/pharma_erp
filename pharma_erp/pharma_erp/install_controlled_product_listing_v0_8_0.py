from __future__ import annotations

from pathlib import Path

import frappe

REQUIRED_WEBSITE_ITEM_FIELDS = (
    "custom_pharma_managed",
    "custom_online_category",
    "custom_requires_prescription",
    "custom_featured_product",
    "custom_online_availability_status",
    "custom_online_sort_order",
    "custom_pharma_readiness_status",
    "custom_pharma_readiness_score",
    "custom_online_description_ar",
    "custom_online_description_en",
)


def execute() -> dict:
    installed_apps = set(frappe.get_installed_apps())
    required_apps = {"pharma_erp", "webshop"}
    missing_apps = sorted(required_apps - installed_apps)
    if missing_apps:
        frappe.throw(f"Missing required apps: {', '.join(missing_apps)}")

    if not frappe.db.exists("DocType", "Website Item"):
        frappe.throw("Website Item DocType is missing. Install Webshop first.")

    website_item_meta = frappe.get_meta("Website Item")
    missing_fields = [field for field in REQUIRED_WEBSITE_ITEM_FIELDS if not website_item_meta.has_field(field)]
    if missing_fields:
        frappe.throw(
            "Step 3B.1 must be installed first. Missing Website Item fields: "
            + ", ".join(missing_fields)
        )

    app_path = Path(frappe.get_app_path("pharma_erp"))
    required_files = (
        app_path / "controlled_product_listing.py",
        app_path / "www" / "pharmacy-shop" / "index.py",
        app_path / "www" / "pharmacy-shop" / "index.html",
        app_path / "www" / "pharmacy-product" / "index.py",
        app_path / "www" / "pharmacy-product" / "index.html",
        app_path / "public" / "js" / "controlled_product_listing.js",
        app_path / "public" / "css" / "controlled_product_listing.css",
    )
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        frappe.throw("Controlled listing source files are missing: " + ", ".join(missing_files))

    # Cache clearing is performed explicitly by the deployment command after build.
    # Keep this installer compatible with Frappe v15, where clear_website_cache is
    # exposed through bench rather than as frappe.clear_website_cache().
    frappe.clear_cache()

    return {
        "status": "ok",
        "step": "3B.2",
        "catalog_route": "/pharmacy-shop/",
        "product_route": "/pharmacy-product/?item=<ITEM_CODE>",
        "required_apps": sorted(required_apps),
        "verified_website_item_fields": len(REQUIRED_WEBSITE_ITEM_FIELDS),
        "read_only_catalog": 1,
        "core_changes": 0,
    }
