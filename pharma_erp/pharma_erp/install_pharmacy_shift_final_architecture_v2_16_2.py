"""Verification hotfix for Pharmacy Shift Final Architecture V2.16.2."""

from pharma_erp.pharma_erp.install_pharmacy_shift_final_architecture_v2_16 import (
    install as _install,
    repair_duplicate_fields,
    verify as _verify,
)


def install():
    """Run the idempotent final architecture installer."""
    return _install()


def repair():
    """Repair duplicate field metadata if an older customization left any."""
    result = repair_duplicate_fields()
    print("Duplicate field repair completed.")
    print(result)
    return result


def verify():
    """Verify the installation without referencing install-local variables."""
    return _verify()
