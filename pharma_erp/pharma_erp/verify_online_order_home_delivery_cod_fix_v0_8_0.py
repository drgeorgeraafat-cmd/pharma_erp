from types import SimpleNamespace

import frappe

from pharma_erp.pharma_erp.doctype.online_order.online_order import (
    _home_delivery_collection_state,
)


class _Invoice:
    outstanding_amount = 110
    grand_total = 110

    def __init__(self, collection_status="", confirmed_method=""):
        self.values = {
            "custom_collection_verification_status": collection_status,
            "custom_confirmed_customer_payment_method": confirmed_method,
            "custom_prepaid_verification_status": "",
            "custom_collection_payment_entry": "",
            "custom_prepaid_payment_entry": "",
        }

    def get(self, key):
        return self.values.get(key)


def _state(payment_timing, collection_status="", confirmed_method=""):
    order = SimpleNamespace(
        payment_timing=payment_timing,
        payment_status="Pending Collection",
        payment_entry="",
        grand_total=110,
    )
    invoice = _Invoice(collection_status, confirmed_method)
    return _home_delivery_collection_state(order, invoice)


def verify():
    cod_default = _state("Collect on Delivery", "Not Required", "")
    no_collection_order = _state("No Collection Required", "Not Required", "")
    explicit_no_collection = _state("Collect on Delivery", "", "No Collection")
    prepaid_default = _state("Prepaid", "Not Required", "")

    result = {
        "cod_default_not_required_is_not_bypass": (
            cod_default["no_collection"] is False
            and cod_default["payment_status"] == "Pending Collection"
        ),
        "no_collection_timing_is_respected": (
            no_collection_order["no_collection"] is True
            and no_collection_order["payment_status"] == "No Collection Required"
        ),
        "explicit_no_collection_method_is_respected": (
            explicit_no_collection["no_collection"] is True
        ),
        "prepaid_default_not_required_is_not_bypass": (
            prepaid_default["no_collection"] is False
        ),
    }
    result["ok"] = all(result.values())

    print(result)
    print(frappe.as_json(result))
    return result
