from __future__ import annotations

from pathlib import Path

BEGIN = "# BEGIN ONLINE ORDER PAYMENT ENTRY STEP 2D HOOKS"
END = "# END ONLINE ORDER PAYMENT ENTRY STEP 2D HOOKS"

BLOCK = r'''

# BEGIN ONLINE ORDER PAYMENT ENTRY STEP 2D HOOKS

_online_order_payment_entry_hooks = {
    "validate": "pharma_erp.online_order_payment_entry_events.validate_linked_online_order_payment",
    "on_submit": "pharma_erp.online_order_payment_entry_events.on_submit_linked_online_order_payment",
    "before_cancel": "pharma_erp.online_order_payment_entry_events.before_cancel_linked_online_order_payment",
    "on_cancel": "pharma_erp.online_order_payment_entry_events.on_cancel_linked_online_order_payment",
    "on_trash": "pharma_erp.online_order_payment_entry_events.on_trash_linked_online_order_payment",
}

_online_order_payment_entry_events = doc_events.setdefault("Payment Entry", {})
for _online_order_event, _online_order_handler in _online_order_payment_entry_hooks.items():
    _online_order_merge_hook(
        _online_order_payment_entry_events,
        _online_order_event,
        _online_order_handler,
    )

# END ONLINE ORDER PAYMENT ENTRY STEP 2D HOOKS
'''


def apply():
    hooks_path = Path(__file__).resolve().parent / "hooks.py"
    text = hooks_path.read_text()
    if BEGIN in text and END in text:
        print(f"Payment hooks patch already present: {hooks_path}")
        return 0
    if "_online_order_merge_hook" not in text:
        raise RuntimeError(
            "Step 2C Online Order hook merge helper was not found in hooks.py"
        )
    hooks_path.write_text(text.rstrip() + BLOCK + "\n")
    print(f"Payment hooks patch applied: {hooks_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(apply())
