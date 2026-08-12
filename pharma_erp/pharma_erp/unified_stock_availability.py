"""Shadow-only unified stock availability service for Pharma ERP v0.9.2.

Step2A is deliberately read-only.  This module does not reserve, release,
consume, submit, cancel, update a Bin, or change channel behaviour.  It applies
the approved canonical Branch/Warehouse contract and exposes one quantity
definition for later channel adapters.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, getdate, nowdate

from erpnext.stock.doctype.batch.batch import get_batch_qty

from pharma_erp.pharma_erp.availability_math import (
    compute_availability_metrics,
    normalized_qty,
)


CONTRACT_VERSION = "v0.9.2-step2a-r2"
MODE = "shadow_read_only"
SELLABLE_ROLES = frozenset({"Sales", "POS", "Online Fulfilment", "Pickup"})
ACTIVE_SRE_STATUSES = ("Partially Reserved", "Reserved", "Partially Delivered")
LOT_DOCTYPE = "Internal Retail Price Lot"


def _clean(value: Any) -> str:
    return cstr(value or "").strip()


def _doctype_exists(doctype: str) -> bool:
    return bool(frappe.db.exists("DocType", doctype))


def _require_read_permissions() -> None:
    for doctype in ("Item", "Warehouse"):
        if not frappe.has_permission(doctype, "read"):
            frappe.throw(
                _("You do not have permission to read {0}.").format(doctype),
                frappe.PermissionError,
            )


def _canonical_context(
    *, branch: str, operational_role: str, submitted_warehouse: str = ""
) -> frappe._dict:
    branch = _clean(branch)
    role = _clean(operational_role)
    submitted_warehouse = _clean(submitted_warehouse)

    if not branch:
        frappe.throw(_("Branch is required for unified stock availability."))
    if role not in SELLABLE_ROLES:
        frappe.throw(
            _("Operational role {0} is not a sellable Step2A role.").format(
                frappe.bold(role or _("(blank)"))
            )
        )

    profile_name = frappe.db.get_value(
        "Pharmacy Branch Profile", {"branch": branch, "disabled": 0}, "name"
    )
    if not profile_name:
        frappe.throw(
            _("Branch {0} has no active Pharmacy Branch Profile.").format(
                frappe.bold(branch)
            )
        )

    branch_profile = frappe.db.get_value(
        "Pharmacy Branch Profile",
        profile_name,
        ["branch", "company", "allow_reservation"],
        as_dict=True,
    )
    mappings = frappe.get_all(
        "Pharmacy Branch Warehouse Role",
        filters={
            "parent": profile_name,
            "parenttype": "Pharmacy Branch Profile",
            "operational_role": role,
        },
        fields=["warehouse"],
        order_by="idx asc, name asc",
    )
    if len(mappings) != 1:
        frappe.throw(
            _("Branch {0} must have exactly one canonical warehouse for role {1}; found {2}.").format(
                frappe.bold(branch), frappe.bold(role), len(mappings)
            )
        )

    warehouse = _clean(mappings[0].warehouse)
    if submitted_warehouse and submitted_warehouse != warehouse:
        frappe.throw(
            _("Warehouse {0} conflicts with canonical warehouse {1} for Branch {2} and role {3}.").format(
                frappe.bold(submitted_warehouse),
                frappe.bold(warehouse),
                frappe.bold(branch),
                frappe.bold(role),
            )
        )

    warehouse_row = frappe.db.get_value(
        "Warehouse",
        warehouse,
        ["company", "is_group", "disabled"],
        as_dict=True,
    )
    if not warehouse_row:
        frappe.throw(_("Canonical Warehouse {0} does not exist.").format(frappe.bold(warehouse)))
    if cint(warehouse_row.is_group) or cint(warehouse_row.disabled):
        frappe.throw(_("Canonical Warehouse {0} is disabled or a group.").format(frappe.bold(warehouse)))
    if _clean(warehouse_row.company) != _clean(branch_profile.company):
        frappe.throw(_("Canonical Branch and Warehouse company values do not match."))

    warehouse_profile_name = frappe.db.get_value(
        "Pharmacy Warehouse Profile", {"warehouse": warehouse}, "name"
    )
    if not warehouse_profile_name:
        frappe.throw(
            _("Warehouse {0} has no Pharmacy Warehouse Profile.").format(
                frappe.bold(warehouse)
            )
        )
    warehouse_profile = frappe.db.get_value(
        "Pharmacy Warehouse Profile",
        warehouse_profile_name,
        [
            "warehouse",
            "branch",
            "company",
            "disabled",
            "physicality",
            "operational_class",
            "is_sellable",
            "allow_online",
            "include_projected",
            "allow_reservation",
        ],
        as_dict=True,
    )
    if (
        cint(warehouse_profile.disabled)
        or _clean(warehouse_profile.branch) != branch
        or _clean(warehouse_profile.company) != _clean(branch_profile.company)
    ):
        frappe.throw(_("Canonical Warehouse profile is disabled or conflicts with Branch/Company."))
    if not cint(warehouse_profile.is_sellable):
        frappe.throw(
            _("Warehouse {0} is not configured as sellable.").format(frappe.bold(warehouse))
        )
    if role == "Online Fulfilment" and not cint(warehouse_profile.allow_online):
        frappe.throw(
            _("Warehouse {0} is not enabled for Online Fulfilment.").format(
                frappe.bold(warehouse)
            )
        )

    if _doctype_exists("Pharmacy Warehouse Allowed Operation"):
        allowed_operation_meta = frappe.get_meta("Pharmacy Warehouse Allowed Operation")
        operation_field = next(
            (
                fieldname
                for fieldname in ("operation", "operational_role")
                if allowed_operation_meta.has_field(fieldname)
            ),
            None,
        )
        if not operation_field:
            frappe.throw(
                _("Pharmacy Warehouse Allowed Operation has no supported operation field.")
            )
        allowed_roles = {
            _clean(row.get(operation_field))
            for row in frappe.get_all(
                "Pharmacy Warehouse Allowed Operation",
                filters={
                    "parent": warehouse_profile_name,
                    "parenttype": "Pharmacy Warehouse Profile",
                },
                fields=[operation_field],
            )
        }
        if allowed_roles and role not in allowed_roles:
            frappe.throw(
                _("Warehouse {0} does not allow operation {1}.").format(
                    frappe.bold(warehouse), frappe.bold(role)
                )
            )

    return frappe._dict(
        branch=branch,
        branch_profile=profile_name,
        company=_clean(branch_profile.company),
        operational_role=role,
        warehouse=warehouse,
        warehouse_profile=warehouse_profile_name,
        physicality=_clean(warehouse_profile.physicality),
        operational_class=_clean(warehouse_profile.operational_class),
        allow_reservation=bool(
            cint(branch_profile.allow_reservation)
            and cint(warehouse_profile.allow_reservation)
        ),
        include_projected=bool(cint(warehouse_profile.include_projected)),
    )


def _item_row(item_code: str) -> frappe._dict:
    item = frappe.db.get_value(
        "Item",
        item_code,
        [
            "item_name",
            "disabled",
            "is_stock_item",
            "has_serial_no",
            "has_batch_no",
            "stock_uom",
            "safety_stock",
        ],
        as_dict=True,
    )
    if not item:
        frappe.throw(_("Item {0} was not found.").format(frappe.bold(item_code)))
    return item


def _bin_row(item_code: str, warehouse: str) -> frappe._dict:
    row = frappe.db.get_value(
        "Bin",
        {"item_code": item_code, "warehouse": warehouse},
        [
            "actual_qty",
            "projected_qty",
            "reserved_qty",
            "reserved_stock",
            "stock_uom",
        ],
        as_dict=True,
    )
    return row or frappe._dict(
        actual_qty=0,
        projected_qty=0,
        reserved_qty=0,
        reserved_stock=0,
        stock_uom="",
    )


def _active_sre_rows(item_code: str, warehouse: str) -> list[frappe._dict]:
    if not _doctype_exists("Stock Reservation Entry"):
        return []
    return frappe.get_all(
        "Stock Reservation Entry",
        filters={
            "docstatus": 1,
            "item_code": item_code,
            "warehouse": warehouse,
            "status": ("in", ACTIVE_SRE_STATUSES),
        },
        fields=[
            "name",
            "reserved_qty",
            "delivered_qty",
            "reservation_based_on",
        ],
        order_by="name asc",
    )


def _remaining_reservation(row: frappe._dict) -> float:
    return normalized_qty(flt(row.reserved_qty) - flt(row.delivered_qty))


def _batch_reserved_qty(sre_rows: list[frappe._dict], batch_no: str) -> float:
    serial_batch_sres = [
        row.name
        for row in sre_rows
        if _clean(row.reservation_based_on) == "Serial and Batch"
    ]
    if not serial_batch_sres:
        return 0.0
    entries = frappe.get_all(
        "Serial and Batch Entry",
        filters={
            "parent": ("in", serial_batch_sres),
            "parenttype": "Stock Reservation Entry",
            "batch_no": batch_no,
        },
        fields=["qty", "delivered_qty"],
    )
    return normalized_qty(
        sum(max(0.0, flt(row.qty) - flt(row.delivered_qty)) for row in entries)
    )


def _batch_rows(
    item_code: str,
    warehouse: str,
    *,
    sre_rows: list[frappe._dict],
    as_of_date,
) -> list[frappe._dict]:
    """Return physical batch rows before subtracting active SRE quantities."""

    ignore_reservations = [row.name for row in sre_rows]
    raw_rows = get_batch_qty(
        item_code=item_code,
        warehouse=warehouse,
        ignore_voucher_nos=ignore_reservations,
    ) or []
    if not isinstance(raw_rows, (list, tuple)):
        return []

    quantities: dict[str, float] = {}
    for row in raw_rows:
        batch_no = _clean(row.get("batch_no") if hasattr(row, "get") else "")
        if not batch_no:
            continue
        quantities[batch_no] = normalized_qty(
            quantities.get(batch_no, 0) + flt(row.get("qty"))
        )

    if not quantities:
        return []

    metadata = {
        row.name: row
        for row in frappe.get_all(
            "Batch",
            filters={"name": ("in", sorted(quantities))},
            fields=["name", "item", "disabled", "expiry_date"],
        )
    }
    result = []
    for batch_no in sorted(quantities):
        batch = metadata.get(batch_no)
        disabled = bool(cint(batch.disabled)) if batch else True
        expiry_date = getdate(batch.expiry_date) if batch and batch.expiry_date else None
        expired = bool(expiry_date and expiry_date < as_of_date)
        item_mismatch = bool(batch and _clean(batch.item) != item_code)
        result.append(
            frappe._dict(
                batch_no=batch_no,
                physical_qty=quantities[batch_no],
                disabled=disabled,
                expiry_date=expiry_date,
                expired=expired,
                item_mismatch=item_mismatch,
                sellable=not disabled and not expired and not item_mismatch,
            )
        )
    return result


def _effective_safety_floor(item_code: str, warehouse: str, item: frappe._dict) -> frappe._dict:
    reorder_level = frappe.db.get_value(
        "Item Reorder",
        {"parent": item_code, "parenttype": "Item", "warehouse": warehouse},
        "warehouse_reorder_level",
    )
    item_safety = normalized_qty(item.safety_stock)
    warehouse_reorder = normalized_qty(reorder_level)
    return frappe._dict(
        item_safety_stock=item_safety,
        warehouse_reorder_level=warehouse_reorder,
        effective_safety_floor=max(item_safety, warehouse_reorder),
    )


def _approved_unissued_transfer_qty(item_code: str, warehouse: str) -> frappe._dict:
    if not (_doctype_exists("Material Request") and _doctype_exists("Material Request Item")):
        return frappe._dict(qty=0.0, state="doctype_unavailable")
    mr_meta = frappe.get_meta("Material Request")
    row_meta = frappe.get_meta("Material Request Item")
    required_parent = {"material_request_type", "status"}
    required_row = {"item_code", "from_warehouse", "stock_qty", "ordered_qty"}
    if not all(mr_meta.has_field(field) for field in required_parent) or not all(
        row_meta.has_field(field) for field in required_row
    ):
        return frappe._dict(qty=0.0, state="metadata_unavailable")

    qty = frappe.db.sql(
        """
        SELECT COALESCE(SUM(GREATEST(mri.stock_qty - mri.ordered_qty, 0)), 0)
          FROM `tabMaterial Request` mr
          JOIN `tabMaterial Request Item` mri ON mri.parent = mr.name
         WHERE mr.docstatus = 1
           AND mr.material_request_type = 'Material Transfer'
           AND mr.status NOT IN ('Stopped', 'Cancelled', 'Transferred')
           AND mri.item_code = %(item_code)s
           AND mri.from_warehouse = %(warehouse)s
        """,
        {"item_code": item_code, "warehouse": warehouse},
    )[0][0]
    return frappe._dict(qty=normalized_qty(qty), state="material_request_outstanding")


def _canonical_transit_qty(item_code: str, branch_profile: str) -> frappe._dict:
    mappings = frappe.get_all(
        "Pharmacy Branch Warehouse Role",
        filters={
            "parent": branch_profile,
            "parenttype": "Pharmacy Branch Profile",
            "operational_role": "Transit",
        },
        fields=["warehouse"],
    )
    if len(mappings) != 1:
        return frappe._dict(qty=None, state="not_attributable", warehouse=None)
    transit_warehouse = _clean(mappings[0].warehouse)
    qty = frappe.db.get_value(
        "Bin", {"item_code": item_code, "warehouse": transit_warehouse}, "actual_qty"
    )
    return frappe._dict(
        qty=normalized_qty(qty),
        state="canonical_transit_mapping",
        warehouse=transit_warehouse,
    )


def _retail_lot_source(
    *, source_name: str, item_code: str, warehouse: str, item_sellable_qty: float, as_of_date
) -> frappe._dict:
    if not _doctype_exists(LOT_DOCTYPE):
        frappe.throw(_("Internal Retail Price Lot is not installed."))
    lot = frappe.db.get_value(
        LOT_DOCTYPE,
        source_name,
        ["name", "item_code", "warehouse", "status", "disabled", "expiry_date", "available_qty"],
        as_dict=True,
    )
    if not lot:
        frappe.throw(_("Retail Price Lot {0} was not found.").format(frappe.bold(source_name)))
    if _clean(lot.item_code) != item_code or _clean(lot.warehouse) != warehouse:
        frappe.throw(_("Retail Price Lot item or warehouse conflicts with the canonical request."))

    blockers = []
    expiry_date = getdate(lot.expiry_date) if lot.expiry_date else None
    if cint(lot.disabled):
        blockers.append("retail_lot_disabled")
    if _clean(lot.status) != "Open":
        blockers.append("retail_lot_not_open")
    if expiry_date and expiry_date < as_of_date:
        blockers.append("retail_lot_expired")

    physical = normalized_qty(lot.available_qty)
    sellable = 0.0 if blockers else normalized_qty(min(physical, item_sellable_qty))
    return frappe._dict(
        physical_qty=physical,
        sellable_qty=sellable,
        reserved_qty=0.0,
        reservation_scope="item_warehouse",
        blockers=blockers,
        metadata={
            "status": _clean(lot.status),
            "expiry_date": cstr(expiry_date) if expiry_date else None,
        },
    )


def get_unified_stock_availability(
    *,
    item_code: str,
    branch: str,
    operational_role: str = "Sales",
    warehouse: str = "",
    source_type: str = "stock",
    source_name: str = "",
    as_of_date=None,
    enforce_permissions: bool = True,
) -> dict[str, Any]:
    """Return the approved Step2A metrics without changing persistent state."""

    if enforce_permissions:
        _require_read_permissions()

    item_code = _clean(item_code)
    if not item_code:
        frappe.throw(_("Item Code is required."))
    source_type = _clean(source_type).lower() or "stock"
    source_name = _clean(source_name)
    if source_type in {"lot", "retail lot"}:
        source_type = "retail_lot"
    if source_type not in {"stock", "batch", "retail_lot"}:
        frappe.throw(_("Unsupported stock source type {0}.").format(frappe.bold(source_type)))

    effective_date = getdate(as_of_date or nowdate())
    context = _canonical_context(
        branch=branch,
        operational_role=operational_role,
        submitted_warehouse=warehouse,
    )
    item = _item_row(item_code)
    bin_row = _bin_row(item_code, context.warehouse)
    physical_qty = normalized_qty(bin_row.actual_qty)
    projected_qty = round(flt(bin_row.projected_qty), 6)
    blockers = []
    if cint(item.disabled):
        blockers.append("item_disabled")
    if not cint(item.is_stock_item):
        blockers.append("item_not_stock")

    sre_rows = _active_sre_rows(item_code, context.warehouse)
    item_reserved_qty = normalized_qty(sum(_remaining_reservation(row) for row in sre_rows))
    batches = []
    if cint(item.has_batch_no):
        batches = _batch_rows(
            item_code,
            context.warehouse,
            sre_rows=sre_rows,
            as_of_date=effective_date,
        )
        item_sellable_qty = normalized_qty(
            min(
                physical_qty,
                sum(row.physical_qty for row in batches if row.sellable),
            )
        )
        blocked_qty = normalized_qty(physical_qty - item_sellable_qty)
    else:
        item_sellable_qty = physical_qty
        blocked_qty = 0.0

    if blockers:
        item_sellable_qty = 0.0
        blocked_qty = physical_qty

    source_physical_qty = physical_qty
    source_sellable_qty = item_sellable_qty
    source_reserved_qty = item_reserved_qty
    reservation_scope = "item_warehouse"
    source_blockers: list[str] = []
    source_metadata: dict[str, Any] = {}

    if source_type == "batch":
        if not cint(item.has_batch_no):
            frappe.throw(_("Item {0} is not batch-controlled.").format(frappe.bold(item_code)))
        if not source_name:
            frappe.throw(_("Batch source requires Source Name."))
        batch = next((row for row in batches if row.batch_no == source_name), None)
        if not batch:
            source_physical_qty = 0.0
            source_sellable_qty = 0.0
            source_blockers.append("batch_not_available_in_warehouse")
            source_metadata = {"expiry_date": None}
        else:
            source_physical_qty = batch.physical_qty
            source_sellable_qty = batch.physical_qty if batch.sellable and not blockers else 0.0
            if batch.disabled:
                source_blockers.append("batch_disabled")
            if batch.expired:
                source_blockers.append("batch_expired")
            if batch.item_mismatch:
                source_blockers.append("batch_item_mismatch")
            source_metadata = {
                "expiry_date": cstr(batch.expiry_date) if batch.expiry_date else None
            }
        source_reserved_qty = _batch_reserved_qty(sre_rows, source_name)
        reservation_scope = "batch_warehouse"
    elif source_type == "retail_lot":
        if not source_name:
            frappe.throw(_("Retail Price Lot source requires Source Name."))
        lot_source = _retail_lot_source(
            source_name=source_name,
            item_code=item_code,
            warehouse=context.warehouse,
            item_sellable_qty=item_sellable_qty,
            as_of_date=effective_date,
        )
        source_physical_qty = lot_source.physical_qty
        source_sellable_qty = lot_source.sellable_qty
        source_reserved_qty = lot_source.reserved_qty
        reservation_scope = lot_source.reservation_scope
        source_blockers.extend(lot_source.blockers)
        source_metadata = lot_source.metadata

    safety = _effective_safety_floor(item_code, context.warehouse, item)
    transfer = _approved_unissued_transfer_qty(item_code, context.warehouse)
    transit = _canonical_transit_qty(item_code, context.branch_profile)
    metrics = compute_availability_metrics(
        item_sellable_qty=item_sellable_qty,
        source_sellable_qty=source_sellable_qty,
        item_reserved_qty=item_reserved_qty,
        source_reserved_qty=source_reserved_qty,
        safety_floor=safety.effective_safety_floor,
        approved_unissued_transfer_qty=transfer.qty,
    )

    return {
        "contract_version": CONTRACT_VERSION,
        "mode": MODE,
        "as_of_date": cstr(effective_date),
        "item": {
            "item_code": item_code,
            "item_name": _clean(item.item_name),
            "stock_uom": _clean(item.stock_uom or bin_row.stock_uom),
            "has_batch_no": bool(cint(item.has_batch_no)),
            "has_serial_no": bool(cint(item.has_serial_no)),
        },
        "canonical_context": dict(context),
        "source": {
            "type": source_type,
            "name": source_name or None,
            "reservation_scope": reservation_scope,
            "metadata": source_metadata,
        },
        "quantities": {
            "physical_qty": physical_qty,
            "item_sellable_qty": item_sellable_qty,
            "source_physical_qty": source_physical_qty,
            "source_sellable_qty": source_sellable_qty,
            "blocked_qty": blocked_qty,
            "item_reserved_qty": item_reserved_qty,
            "source_reserved_qty": source_reserved_qty,
            "item_safety_stock": safety.item_safety_stock,
            "warehouse_reorder_level": safety.warehouse_reorder_level,
            "safety_floor": safety.effective_safety_floor,
            "approved_unissued_transfer_qty": transfer.qty,
            "projected_qty": projected_qty,
            "in_transit_qty": transit.qty,
            **metrics,
        },
        "states": {
            "reservation_enabled": context.allow_reservation,
            "transfer_commitment": transfer.state,
            "transit_attribution": transit.state,
            "transit_warehouse": transit.warehouse,
            "projected_included_in_atp": False,
            "transit_included_in_atp": False,
            "persistent_writes_performed": False,
        },
        "blockers": sorted(set(blockers + source_blockers)),
        "shadow_comparison": {
            "legacy_bin_actual_qty": physical_qty,
            "unified_available_to_promise": metrics["available_to_promise"],
            "delta_vs_legacy_actual": round(
                metrics["available_to_promise"] - physical_qty, 6
            ),
        },
    }


@frappe.whitelist()
def get_unified_stock_availability_api(
    item_code: str,
    branch: str,
    operational_role: str = "Sales",
    warehouse: str = "",
    source_type: str = "stock",
    source_name: str = "",
) -> dict[str, Any]:
    """Authenticated read-only endpoint; no channel calls it during Step2A."""

    return get_unified_stock_availability(
        item_code=item_code,
        branch=branch,
        operational_role=operational_role,
        warehouse=warehouse,
        source_type=source_type,
        source_name=source_name,
        enforce_permissions=True,
    )
