from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime

from pharma_erp.pharma_erp.inventory_count_service import (
    APPROVER_ROLES,
    COUNTER_ROLES,
    COUNT_DOCTYPE,
    EPSILON,
    POSTER_ROLES,
    REVIEWER_ROLES,
    RESOLVED_STATES,
    assert_no_overlap,
    auto_resolve_movements,
    build_reconciliation_targets,
    build_snapshot_rows,
    clean,
    create_stock_reconciliation,
    create_expired_stock_transfer,
    execute_batch_reconciliation_plans,
    current_expected_qty,
    get_settings,
    inventory_count_enabled,
    location_followup_required,
    log_event,
    post_location_variances,
    require_any_role,
    require_feature_enabled,
    require_high_variance_role,
    reverse_location_movements,
    reverse_batch_reconciliation_execution,
    sync_counted_rows,
    unresolved_rows,
    update_totals,
    validate_batch_breakdown_posting,
    validate_for_approval,
    validate_posting_batch,
    validate_scope,
)


class PharmacyInventoryCount(Document):
    def validate(self):
        validate_scope(self)
        self._validate_state_mutations()
        if self.status == "Counting":
            sync_counted_rows(self)
        else:
            # Preserve captured count data outside Counting, but keep totals current
            # for reviewer-only fields such as reason / batch resolution.
            for row in self.items or []:
                if cint(row.count_entered):
                    row.high_variance = cint(row.high_variance)
        update_totals(self)

    def _validate_state_mutations(self):
        if self.is_new():
            if not self.status:
                self.status = "Draft"
            return

        previous = frappe.get_doc(self.doctype, self.name)

        # Scope is immutable after Start Count.
        if previous.status != "Draft":
            protected = [
                "company",
                "branch",
                "scope_type",
                "warehouse",
                "scope_location",
                "item_code",
                "item_group",
                "batch_no",
            ]
            for fieldname in protected:
                if clean(previous.get(fieldname)) != clean(self.get(fieldname)):
                    frappe.throw(_("{0} cannot be changed after Start Count.").format(self.meta.get_label(fieldname)))

        # Count quantities may only change while Counting.
        if self.status != "Counting" and previous.status != "Counting":
            old_rows = {row.name: row for row in previous.items or []}
            for row in self.items or []:
                old = old_rows.get(row.name)
                if not old:
                    continue
                if flt(old.actual_qty, 6) != flt(row.actual_qty, 6) or cint(old.count_entered) != cint(row.count_entered):
                    frappe.throw(_("Actual Count quantities can only be changed while status is Counting."))

        if previous.status in {"Approved", "Posted", "Cancelled"}:
            old_rows = {row.name: row for row in previous.items or []}
            immutable_fields = [
                "actual_qty",
                "count_entered",
                "resolution_status",
                "found_location",
                "found_elsewhere_qty",
                "reason_code",
                "reason_note",
                "posting_batch_no",
                "count_round",
            ]
            for row in self.items or []:
                old = old_rows.get(row.name)
                if not old:
                    frappe.throw(_("Rows cannot be added after approval."))
                for fieldname in immutable_fields:
                    old_value = old.get(fieldname)
                    new_value = row.get(fieldname)
                    if isinstance(old_value, (int, float)) or isinstance(new_value, (int, float)):
                        if flt(old_value, 6) != flt(new_value, 6):
                            frappe.throw(_("Approved/Posted Inventory Count rows are immutable."))
                    elif clean(old_value) != clean(new_value):
                        frappe.throw(_("Approved/Posted Inventory Count rows are immutable."))

    @frappe.whitelist()
    def start_count(self):
        require_feature_enabled()
        require_any_role(COUNTER_ROLES, _("Inventory Counter"))
        if self.is_new():
            frappe.throw(_("Save the Inventory Count before starting."))
        if self.status != "Draft":
            frappe.throw(_("Only Draft Inventory Count can be started."))
        validate_scope(self)
        if self.items:
            frappe.throw(_("Draft Inventory Count already contains rows. Clear them before Start Count."))

        snapshot_rows = build_snapshot_rows(self)
        assert_no_overlap(self.name, snapshot_rows)
        if not snapshot_rows and self.scope_type not in {"Item", "Batch"}:
            frappe.throw(_("No expected stock was found in the selected Count Scope."))

        self.snapshot_datetime = now_datetime()
        self.started_by = frappe.session.user
        self.started_at = self.snapshot_datetime
        self.count_round = 1
        self.status = "Counting"
        settings = get_settings()
        if self.blind_count is None:
            self.blind_count = cint(settings.get("blind_count_default") or 1)

        self.set("items", [])
        for row in snapshot_rows:
            row.pop("snapshot_datetime", None)
            self.append("items", row)
        self.save(ignore_permissions=True)
        log_event(
            self.name,
            "Started",
            details=_("Inventory Count snapshot created."),
            payload={"scope_type": self.scope_type, "rows": len(self.items), "snapshot_datetime": self.snapshot_datetime},
            count_round=self.count_round,
        )
        return {
            "status": self.status,
            "row_count": len(self.items),
            "snapshot_datetime": self.snapshot_datetime,
            "blind_count": cint(self.blind_count),
        }

    @frappe.whitelist()
    def add_found_item(self, item_code: str, warehouse: str | None = None, location: str | None = None, batch_no: str | None = None):
        require_feature_enabled()
        require_any_role(COUNTER_ROLES, _("Inventory Counter"))
        if self.status != "Counting":
            frappe.throw(_("Found Items can only be added while Counting."))

        from pharma_erp.pharma_erp.inventory_count_service import _item_meta, _line_dict, _warehouse_company
        from pharma_erp.pharma_erp.location_service import validate_location

        item_code = clean(item_code)
        _item_meta(item_code)
        warehouse = clean(warehouse) or clean(self.warehouse)
        if not warehouse:
            frappe.throw(_("Warehouse is required for a Found Item."))
        if _warehouse_company(warehouse) != self.company:
            frappe.throw(_("Found Item Warehouse belongs to another Company."))

        count_basis = "Location" if self.scope_type in {"Zone", "Aisle", "Shelf", "Bin"} else "Warehouse"
        if count_basis == "Location":
            location = clean(location) or clean(self.scope_location)
            if not location:
                frappe.throw(_("Location is required for Found Item in Location Count."))
            validate_location(location, warehouse)
        else:
            location = None

        batch_no = clean(batch_no) or None
        if batch_no:
            validate_posting_batch(item_code, batch_no)

        line_key = "|".join([warehouse, location or "", item_code, batch_no or ""])
        assert_no_overlap(self.name, [{"warehouse": warehouse, "item_code": item_code, "batch_no": batch_no}])
        for existing in self.items or []:
            if clean(existing.warehouse) != warehouse or clean(existing.item_code) != item_code:
                continue
            existing_batch = clean(existing.batch_no)
            if not batch_no or not existing_batch or existing_batch == batch_no:
                frappe.throw(_("Item already exists in this Count Scope."))

        row_data = _line_dict(
            warehouse=warehouse,
            location=location,
            item_code=item_code,
            batch_no=batch_no,
            snapshot_qty=0,
            count_basis=count_basis,
            unexpected=1,
        )
        row = self.append("items", row_data)
        self.save(ignore_permissions=True)
        log_event(
            self.name,
            "Found Item Added",
            row=row,
            details=_("Unexpected physical item added during count."),
            payload={"warehouse": warehouse, "location": location, "batch_no": batch_no},
        )
        return {"row_name": row.name, "item_code": row.item_code, "status": self.status}

    @frappe.whitelist()
    def authorize_exclusion(self, row_names, reason: str):
        require_feature_enabled()
        require_any_role(REVIEWER_ROLES, _("Inventory Reviewer"))
        if self.status != "Counting":
            frappe.throw(_("Authorized Exclusion is only available while Counting."))
        if isinstance(row_names, str):
            row_names = json.loads(row_names or "[]")
        row_names = set(row_names or [])
        if not row_names:
            frappe.throw(_("Select at least one row for Authorized Exclusion."))
        if not clean(reason):
            frappe.throw(_("Authorized Exclusion reason is required."))

        changed = []
        for row in self.items or []:
            if row.name not in row_names:
                continue
            expected = current_expected_qty(row)
            row.count_entered = 1
            row.actual_qty = expected
            row.expected_qty_at_count = expected
            row.variance_qty = 0
            row.variance_value = 0
            row.counted_at = now_datetime()
            row.counted_by = frappe.session.user
            row.resolution_status = "Authorized Exclusion"
            row.reason_code = "Other"
            row.reason_note = clean(reason)
            row.high_variance = 0
            changed.append(row.name)
            log_event(
                self.name,
                "Authorized Exclusion",
                row=row,
                details=reason,
                payload={"expected_qty": expected},
            )
        if not changed:
            frappe.throw(_("Selected rows were not found."))
        self.save(ignore_permissions=True)
        return {"excluded_rows": changed}

    @frappe.whitelist()
    def complete_count(self):
        require_feature_enabled()
        require_any_role(COUNTER_ROLES | REVIEWER_ROLES, _("Inventory Counter / Reviewer"))
        if self.status != "Counting":
            frappe.throw(_("Only a Counting Inventory Count can be completed."))

        resolved_by_movement = auto_resolve_movements(self)
        self.save(ignore_permissions=True)
        missing = unresolved_rows(self)
        if missing:
            log_event(
                self.name,
                "Missing Review Required",
                details=_("Expected items remain unresolved."),
                payload={"missing": missing},
                count_round=self.count_round,
            )
            return {
                "completed": False,
                "missing_count": len(missing),
                "missing": missing,
                "resolved_by_movement": resolved_by_movement,
            }

        self.status = "Count Completed"
        self.completed_by = frappe.session.user
        self.completed_at = now_datetime()
        update_totals(self)
        self.save(ignore_permissions=True)
        log_event(
            self.name,
            "Count Completed",
            details=_("Physical counting completed with no unresolved expected items."),
            payload={"resolved_by_movement": resolved_by_movement},
            count_round=self.count_round,
        )
        return {"completed": True, "status": self.status, "resolved_by_movement": resolved_by_movement}

    @frappe.whitelist()
    def begin_review(self):
        require_feature_enabled()
        require_any_role(REVIEWER_ROLES, _("Inventory Reviewer"))
        if self.status != "Count Completed":
            frappe.throw(_("Only Count Completed can enter Under Review."))
        self.status = "Under Review"
        self.reviewed_by = frappe.session.user
        self.reviewed_at = now_datetime()
        self.save(ignore_permissions=True)
        log_event(self.name, "Under Review", details=_("Inventory Count entered reviewer stage."), count_round=self.count_round)
        return {"status": self.status}

    @frappe.whitelist()
    def request_recount(self, row_names):
        require_feature_enabled()
        require_any_role(REVIEWER_ROLES, _("Inventory Reviewer"))
        if self.status not in {"Count Completed", "Under Review"}:
            frappe.throw(_("Recount can only be requested after Count Completed."))
        if isinstance(row_names, str):
            row_names = json.loads(row_names or "[]")
        selected = set(row_names or [])
        if not selected:
            frappe.throw(_("Select one or more Inventory Count rows for Recount."))

        changed = []
        for row in self.items or []:
            if row.name not in selected:
                continue
            log_event(
                self.name,
                "Recount Requested",
                row=row,
                details=_("Reviewer requested a new physical count."),
                payload={
                    "previous_actual_qty": row.actual_qty,
                    "previous_expected_qty": row.expected_qty_at_count,
                    "previous_variance_qty": row.variance_qty,
                    "previous_resolution_status": row.resolution_status,
                },
                count_round=row.count_round,
            )
            row.count_round = cint(row.count_round or 1) + 1
            row.count_entered = 0
            row.actual_qty = 0
            row.expected_qty_at_count = 0
            row.variance_qty = 0
            row.variance_value = 0
            row.counted_at = None
            row.counted_by = None
            row.resolution_status = "Pending"
            row.found_location = None
            row.found_elsewhere_qty = 0
            row.reason_code = None
            row.reason_note = None
            row.posting_batch_no = None
            row.high_variance = 0
            changed.append(row.name)

        if not changed:
            frappe.throw(_("Selected rows were not found."))
        self.status = "Counting"
        self.count_round = max([cint(row.count_round or 1) for row in self.items or []] or [1])
        self.completed_by = None
        self.completed_at = None
        self.reviewed_by = None
        self.reviewed_at = None
        self.save(ignore_permissions=True)
        return {"status": self.status, "recount_rows": changed, "count_round": self.count_round}

    @frappe.whitelist()
    def approve_count(self):
        require_feature_enabled()
        require_any_role(APPROVER_ROLES, _("Inventory Approver"))
        if self.status != "Under Review":
            frappe.throw(_("Only Under Review Inventory Count can be approved."))

        validate_for_approval(self)
        update_totals(self)
        if cint(self.high_variance):
            require_high_variance_role()

        self.status = "Approved"
        self.approved_by = frappe.session.user
        self.approved_at = now_datetime()
        self.save(ignore_permissions=True)
        log_event(
            self.name,
            "Approved",
            details=_("Inventory variances approved for controlled posting."),
            payload={
                "net_variance_qty": self.net_variance_qty,
                "absolute_variance_qty": self.absolute_variance_qty,
                "total_variance_value": self.total_variance_value,
                "high_variance": cint(self.high_variance),
            },
            count_round=self.count_round,
        )
        return {"status": self.status, "high_variance": cint(self.high_variance)}

    @frappe.whitelist()
    def post_count(self):
        require_feature_enabled()
        require_any_role(POSTER_ROLES, _("Inventory Stock Poster"))
        if self.status == "Posted":
            return {
                "status": self.status,
                "stock_reconciliation": self.stock_reconciliation,
                "idempotent": True,
            }
        if self.status != "Approved":
            frappe.throw(_("Only Approved Inventory Count can be posted."))

        validate_for_approval(self)
        validate_batch_breakdown_posting(self)

        # Short critical section: lock existing Bin rows before calculating delta-based targets.
        from pharma_erp.pharma_erp.inventory_count_service import _lock_bins

        _lock_bins(self.items or [])

        batch_execution = execute_batch_reconciliation_plans(self)
        location_movements = post_location_variances(self)
        targets = list(batch_execution.get("targets") or [])
        targets.extend(build_reconciliation_targets(self, skip_row_names=batch_execution.get("handled_rows") or []))
        reconciliation = create_stock_reconciliation(self, targets)
        expired_stock_entry = create_expired_stock_transfer(self, batch_execution.get("expired_targets") or [])

        self.stock_reconciliation = reconciliation
        self.posted_by = frappe.session.user
        self.posted_at = now_datetime()
        self.status = "Posted"

        followup_rows = []
        for row in self.items or []:
            needs_followup = location_followup_required(row)
            row.location_followup_required = cint(needs_followup)
            if needs_followup:
                followup_rows.append(row.name)

        self.save(ignore_permissions=True)
        log_event(
            self.name,
            "Posted",
            details=_("Inventory Count posted atomically through controlled location adjustments and ERPNext Stock Reconciliation."),
            payload={
                "stock_reconciliation": reconciliation,
                "reconciliation_targets": targets,
                "batch_reconciliation_execution": batch_execution,
                "expired_stock_entry": expired_stock_entry,
                "location_movements": location_movements,
                "location_followup_rows": followup_rows,
            },
            count_round=self.count_round,
        )
        return {
            "status": self.status,
            "stock_reconciliation": reconciliation,
            "reconciliation_rows": len(targets),
            "batch_reconciliation_rows": len(batch_execution.get("handled_rows") or []),
            "created_batches": batch_execution.get("created_batches") or [],
            "expired_stock_entry": expired_stock_entry,
            "location_movements": len(location_movements),
            "location_followup_rows": followup_rows,
            "idempotent": False,
        }

    @frappe.whitelist()
    def cancel_count(self, reason: str):
        require_feature_enabled()
        require_any_role(POSTER_ROLES | REVIEWER_ROLES, _("Inventory Reviewer / Stock Poster"))
        if self.status == "Cancelled":
            return {"status": self.status, "idempotent": True}
        if not clean(reason):
            frappe.throw(_("Cancellation reason is required."))

        previous_status = self.status
        reversed_movements = []
        cancelled_reconciliation = None

        batch_reconciliation_reversal = None
        if self.status == "Posted":
            batch_reconciliation_reversal = reverse_batch_reconciliation_execution(self)
            if cint((batch_reconciliation_reversal or {}).get("handled")):
                cancelled_reconciliation = (batch_reconciliation_reversal or {}).get("cancelled_stock_reconciliation")
            elif self.stock_reconciliation:
                reco = frappe.get_doc("Stock Reconciliation", self.stock_reconciliation)
                if reco.docstatus == 1:
                    reco.flags.ignore_permissions = True
                    reco.cancel()
                    cancelled_reconciliation = reco.name
            reversed_movements = reverse_location_movements(self)
        elif self.status not in {"Draft", "Counting", "Count Completed", "Under Review", "Approved"}:
            frappe.throw(_("Inventory Count cannot be cancelled from status {0}.").format(self.status))

        self.status = "Cancelled"
        self.cancelled_by = frappe.session.user
        self.cancelled_at = now_datetime()
        self.cancellation_reason = clean(reason)
        self.save(ignore_permissions=True)
        log_event(
            self.name,
            "Cancelled",
            details=reason,
            payload={
                "previous_status": previous_status,
                "cancelled_stock_reconciliation": cancelled_reconciliation,
                "batch_reconciliation_reversal": batch_reconciliation_reversal,
                "reversed_location_movements": reversed_movements,
            },
            count_round=self.count_round,
        )
        return {
            "status": self.status,
            "cancelled_stock_reconciliation": cancelled_reconciliation,
            "batch_reconciliation_reversal": batch_reconciliation_reversal,
            "reversed_location_movements": reversed_movements,
            "idempotent": False,
        }

    @frappe.whitelist()
    def refresh_review_totals(self):
        require_feature_enabled()
        if self.status not in {"Count Completed", "Under Review"}:
            frappe.throw(_("Review totals are available only after count completion."))
        update_totals(self)
        self.save(ignore_permissions=True)
        return {
            "total_snapshot_qty": self.total_snapshot_qty,
            "total_actual_qty": self.total_actual_qty,
            "net_variance_qty": self.net_variance_qty,
            "absolute_variance_qty": self.absolute_variance_qty,
            "total_variance_value": self.total_variance_value,
            "high_variance": cint(self.high_variance),
        }
