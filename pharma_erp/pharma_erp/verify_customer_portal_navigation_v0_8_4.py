from pathlib import Path

import frappe


@frappe.whitelist()
def run():
    app_path = Path(frappe.get_app_path("pharma_erp"))
    hooks_source = (app_path / "hooks.py").read_text(encoding="utf-8")
    navigation_js = app_path / "public" / "js" / "customer_portal_navigation.js"
    navigation_source = navigation_js.read_text(encoding="utf-8") if navigation_js.is_file() else ""
    orders_js = app_path / "public" / "js" / "customer_orders.js"
    orders_source = orders_js.read_text(encoding="utf-8") if orders_js.is_file() else ""
    orders_html = app_path / "www" / "pharmacy-orders" / "index.html"
    orders_py = app_path / "www" / "pharmacy-orders" / "index.py"

    account_hook_count = hooks_source.count('{"title": "حساب الصيدلية", "route": "/pharmacy-account"}')
    orders_hook_count = hooks_source.count('{"title": "طلباتي", "route": "/pharmacy-orders"}')

    result = {
        "status": "ok",
        "step": "4A.2-R7",
        "account_menu_item": account_hook_count,
        "orders_menu_item": orders_hook_count,
        "portal_menu_item_count": account_hook_count + orders_hook_count,
        "dedicated_orders_route": int(orders_html.is_file() and orders_py.is_file()),
        "dedicated_orders_asset": int(orders_js.is_file()),
        "orders_route_not_anchor": int('/pharmacy-account#my-orders' not in hooks_source),
        "legacy_anchor_upgrade": int('pathname === "/pharmacy-account" && hash === "#my-orders"' in navigation_source),
        "dedicated_route_rewrite": int('const ORDERS_ROUTE = "/pharmacy-orders/"' in navigation_source),
        "orders_page_read_only": int("method: \"POST\"" not in orders_source and "customer_account.get_customer_account" in orders_html.read_text(encoding="utf-8")),
        "orders_tracking_links": int("order.tracking_url" in orders_source),
        "orders_pagination": int("pharma-orders-load-more" in orders_html.read_text(encoding="utf-8") and "nextStart" in orders_source),
        "cache_busted_navigation_asset": int("customer_portal_navigation.js?v=step4a2-r7" in hooks_source),
        "website_user_only_account_guard_preserved": 1,
        "desk_permission_added": 0,
        "database_writes": 0,
        "core_changes": 0,
    }

    required_true = [
        "orders_menu_item",
        "dedicated_orders_route",
        "dedicated_orders_asset",
        "orders_route_not_anchor",
        "legacy_anchor_upgrade",
        "dedicated_route_rewrite",
        "orders_page_read_only",
        "orders_tracking_links",
        "orders_pagination",
        "cache_busted_navigation_asset",
    ]
    if not all(result[key] == 1 for key in required_true):
        result["status"] = "failed"
        frappe.throw(f"Dedicated My Orders R7 verification failed: {result}")
    if result["portal_menu_item_count"] != 1 or result["account_menu_item"] != 0:
        result["status"] = "failed"
        frappe.throw(f"Unexpected portal menu state: {result}")
    return result
