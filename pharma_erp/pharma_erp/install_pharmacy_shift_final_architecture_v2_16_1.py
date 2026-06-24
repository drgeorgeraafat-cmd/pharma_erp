"""Hotfix installer for Pharmacy Shift Final Architecture V2.16.1."""

from pharma_erp.pharma_erp.install_pharmacy_shift_final_architecture_v2_16 import (
    install as _install,
    repair_duplicate_fields,
    verify as _verify,
)


def install():
    return _install()


def repair():
    result = repair_duplicate_fields()
    print("Duplicate field repair completed.")
    print(result)
    return result


def verify():
    return _verify()
