"""Driver zero-balance close-flow hotfix for V2.16.3."""

from pharma_erp.pharma_erp.install_pharmacy_shift_final_architecture_v2_16_2 import (
    install as _install,
    repair as _repair,
    verify as _verify,
)


def install():
    """Run the idempotent final architecture installer."""
    return _install()


def repair():
    """Run duplicate-field metadata repair when required."""
    return _repair()


def verify():
    """Verify the final architecture installation."""
    result = _verify()
    if isinstance(result, dict):
        result["hotfix_version"] = "2.16.3"
    return result
