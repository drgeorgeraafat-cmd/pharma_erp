from __future__ import annotations

from pathlib import Path

BEGIN = "# BEGIN ONLINE ORDER SALES INVOICE STEP 2C HOOKS"
END = "# END ONLINE ORDER SALES INVOICE STEP 2C HOOKS"

BLOCK = r'''

# BEGIN ONLINE ORDER SALES INVOICE STEP 2C HOOKS

def _online_order_merge_hook(mapping, key, handler):
    current = mapping.get(key)
    if not current:
        mapping[key] = handler
    elif isinstance(current, str):
        if current != handler:
            mapping[key] = [current, handler]
    elif handler not in current:
        current.append(handler)


_online_order_sales_invoice_hooks = {
    "validate": "pharma_erp.online_order_sales_invoice_events.validate_linked_online_order_invoice",
    "before_submit": "pharma_erp.online_order_sales_invoice_events.before_submit_linked_online_order_invoice",
    "on_submit": "pharma_erp.online_order_sales_invoice_events.on_submit_linked_online_order_invoice",
    "on_update_after_submit": "pharma_erp.online_order_sales_invoice_events.sync_online_order_after_invoice_update",
    "before_cancel": "pharma_erp.online_order_sales_invoice_events.before_cancel_linked_online_order_invoice",
    "on_cancel": "pharma_erp.online_order_sales_invoice_events.on_cancel_linked_online_order_invoice",
}

_online_order_sales_invoice_events = doc_events.setdefault("Sales Invoice", {})
for _online_order_event, _online_order_handler in _online_order_sales_invoice_hooks.items():
    _online_order_merge_hook(
        _online_order_sales_invoice_events,
        _online_order_event,
        _online_order_handler,
    )

# END ONLINE ORDER SALES INVOICE STEP 2C HOOKS
'''


def apply():
    hooks_path = Path(__file__).resolve().parent / "hooks.py"
    text = hooks_path.read_text()
    if BEGIN in text and END in text:
        print(f"Hooks patch already present: {hooks_path}")
        return 0
    if "doc_events" not in text:
        raise RuntimeError("doc_events was not found in hooks.py")
    hooks_path.write_text(text.rstrip() + BLOCK + "\n")
    print(f"Hooks patch applied: {hooks_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(apply())
