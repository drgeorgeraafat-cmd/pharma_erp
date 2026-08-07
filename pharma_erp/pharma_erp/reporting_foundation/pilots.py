from __future__ import annotations

import inspect
from collections import Counter
from typing import Any, Iterable, Mapping

import frappe
from frappe import _
from frappe.utils import flt

from .contracts import (
    ColumnSpec,
    ExecutionMode,
    ExecutionRequest,
    PermissionContext,
    ReportDefinition,
    RunnerResult,
    ValidationError,
    PermissionDenied,
)
from .execution import ReportRegistry, execute as execute_foundation


NOT_ATTRIBUTABLE_BRANCH = "__NOT_ATTRIBUTABLE__"

DAILY_REPORT_ID = "daily_branch_operations_summary"
SHIFT_REPORT_ID = "shift_cash_integrity_summary"
ONLINE_REPORT_ID = "online_order_operations_funnel"

PILOT_REPORT_NAMES = {
    DAILY_REPORT_ID: "Daily Branch Operations Summary",
    SHIFT_REPORT_ID: "Shift Cash Integrity Summary",
    ONLINE_REPORT_ID: "Online Order Operations Funnel",
}

BRANCH_FIELDS = ("branch", "custom_branch", "pharmacy_branch", "custom_pharmacy_branch")
FULFILMENT_FIELDS = (
    "custom_order_type",
    "fulfilment_method",
    "fulfilment_type",
    "fulfillment_type",
    "custom_fulfilment_type",
    "custom_fulfillment_type",
    "order_type",
)
SALES_CHANNEL_FIELDS = ("sales_channel", "custom_sales_channel", "order_source", "custom_order_source")
SHIFT_LINK_FIELDS = (
    "custom_pharmacy_shift",
    "pharmacy_shift",
    "custom_sales_shift",
    "sales_shift",
    "shift_reference",
)
ONLINE_SI_FIELDS = (
    "sales_invoice",
    "linked_sales_invoice",
    "sales_invoice_reference",
    "custom_sales_invoice",
)
ONLINE_DATE_FIELDS = ("order_date", "transaction_date", "posting_date", "creation")
ONLINE_PAYMENT_FIELDS = (
    "payment_method",
    "mode_of_payment",
    "custom_payment_method",
    "custom_mode_of_payment",
)
SI_ONLINE_ORDER_FIELDS = ("custom_online_order", "online_order", "online_order_reference")

SHIFT_FIELD_ALIASES = {
    "opening_float": (
        "opening_float", "opening_cash", "opening_balance", "cash_opening_balance",
        "opening_amount",
    ),
    "direct_till_cash": (
        "direct_till_cash", "cash_sales_entering_till", "cash_sales", "direct_cash_sales",
        "till_cash_sales",
    ),
    "total_cash_sales": (
        "total_cash_sales", "total_cash_collected_sales", "cash_sales_total",
    ),
    "delivery_cash_in_transit": (
        "delivery_cash_in_transit", "cash_in_transit", "driver_cash_in_transit",
        "remaining_with_driver",
    ),
    "driver_expected_cash": (
        "driver_expected_cash", "expected_driver_cash", "delivery_expected_cash",
        "driver_expected", "expected_with_driver", "total_expected",
        "total_collected_by_driver",
    ),
    "driver_handed_over_cash": (
        "driver_handed_over_cash", "driver_handover", "driver_handover_cash",
        "handed_over_cash", "total_handed_over", "total_collected_by_driver",
        "delivery_handover_cash", "driver_cash_deposits",
    ),
    "expected_cash": (
        "expected_cash", "cash_drawer_expected_balance", "expected_balance",
        "expected_closing_cash", "expected_till_cash",
    ),
    "counted_cash": (
        "counted_cash", "actual_cash", "actual_cash_count", "closing_cash",
        "counted_amount", "actual_closing_cash",
    ),
    "cash_difference": (
        "cash_difference", "difference", "cash_variance", "variance",
    ),
    "posted_gl_balance": (
        "posted_gl_balance", "gl_balance", "cash_drawer_gl_balance",
        "custom_review_gl_balance", "review_gl_balance",
    ),
    "pending_posting": (
        "pending_posting", "pending_posting_amount", "unposted_amount",
    ),
}


def _meta(doctype: str):
    if not frappe.db.exists("DocType", doctype):
        return None
    return frappe.get_meta(doctype)


def _field(doctype: str, candidates: Iterable[str]) -> str | None:
    meta = _meta(doctype)
    if not meta:
        return None
    for name in candidates:
        if name == "creation" or meta.has_field(name):
            return name
    return None


def _column(doctype: str, candidates: Iterable[str], fallback: str | None = None) -> str | None:
    found = _field(doctype, candidates)
    return found or fallback


def _require_source_read(doctype: str) -> None:
    if not frappe.has_permission(doctype, ptype="read", user=frappe.session.user):
        frappe.throw(_("You do not have permission to read {0}.").format(doctype), frappe.PermissionError)


def _require_named_doc_read(doctype: str, name: str) -> None:
    if not name:
        return
    doc = frappe.get_doc(doctype, name)
    if not frappe.has_permission(doctype, ptype="read", doc=doc, user=frappe.session.user):
        frappe.throw(_("You do not have permission to read {0} {1}.").format(doctype, name), frappe.PermissionError)


def _resolve_company(requested: str | None) -> str:
    if requested:
        _require_named_doc_read("Company", requested)
        return requested
    default = frappe.defaults.get_user_default("Company")
    if default:
        _require_named_doc_read("Company", default)
        return default
    companies = frappe.get_list("Company", pluck="name", limit_page_length=2)
    if len(companies) == 1:
        return companies[0]
    raise ValidationError("Company is required")


def _resolve_branch(company: str, requested: str | None, source_doctype: str) -> tuple[str, str | None, dict[str, str]]:
    branch_field = _field(source_doctype, BRANCH_FIELDS)

    if requested in ("All Branches", "__ALL_PERMITTED_BRANCHES__"):
        raise ValidationError(
            "All Branches is intentionally disabled in A.5 until canonical multi-branch permission mapping is implemented."
        )

    if requested:
        if not frappe.db.exists("DocType", "Branch"):
            raise ValidationError("Branch filter is unavailable because Branch DocType is not installed")
        _require_named_doc_read("Branch", requested)
        if not branch_field:
            raise ValidationError(
                f"{source_doctype} has no canonical Branch field at the current checkpoint; branch filtering cannot be guessed."
            )
        branch_company = _field("Branch", ("company",))
        if branch_company:
            actual_company = frappe.db.get_value("Branch", requested, branch_company)
            if actual_company and actual_company != company:
                raise ValidationError("Selected Branch does not belong to selected Company")
        return requested, branch_field, {requested: company}

    # A.5 is allowed to operate company-wide only when the source cannot yet be
    # canonically attributed to Branch. This is explicit, not an inferred branch.
    if branch_field:
        meta = _meta(source_doctype)
        if meta and meta.has_field("company"):
            distinct = frappe.db.sql(
                f"""select distinct `{branch_field}`
                    from `tab{source_doctype}`
                    where company=%s and coalesce(`{branch_field}`, '') != ''
                    limit 2""",
                (company,),
                pluck=True,
            )
        else:
            distinct = frappe.db.sql(
                f"""select distinct `{branch_field}`
                    from `tab{source_doctype}`
                    where coalesce(`{branch_field}`, '') != ''
                    limit 2""",
                pluck=True,
            )
        if len(distinct) > 1:
            raise ValidationError(
                "Branch is required because more than one canonical Branch is present in this Company."
            )
        if len(distinct) == 1:
            branch = distinct[0]
            try:
                _require_named_doc_read("Branch", branch)
            except Exception:
                raise ValidationError("The only detected Branch is not readable by the current user")
            return branch, branch_field, {branch: company}

    return NOT_ATTRIBUTABLE_BRANCH, branch_field, {NOT_ATTRIBUTABLE_BRANCH: company}


def _permission_context(report_id: str, company: str, branch: str) -> PermissionContext:
    capability = {
        DAILY_REPORT_ID: "OPERATIONAL_REPORTING",
        SHIFT_REPORT_ID: "SHIFT_CASH_CONTROL_REPORTING",
        ONLINE_REPORT_ID: "DELIVERY_ONLINE_REPORTING",
    }[report_id]
    return PermissionContext(
        user=frappe.session.user,
        allowed_companies=(company,),
        allowed_branches=(branch,),
        allowed_warehouses=(),
        capabilities=frozenset({"REPORT_ACCESS", capability}),
    )


def _sql_conditions(
    *,
    doctype: str,
    company: str | None = None,
    branch: str | None = None,
    branch_field: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    date_field: str | None = None,
    docstatus: int | None = None,
    alias: str = "t",
) -> tuple[list[str], dict[str, Any]]:
    conditions: list[str] = []
    params: dict[str, Any] = {}

    meta = _meta(doctype)
    if company and meta and meta.has_field("company"):
        conditions.append(f"`{alias}`.`company` = %(company)s")
        params["company"] = company

    if branch and branch != NOT_ATTRIBUTABLE_BRANCH:
        if not branch_field:
            raise ValidationError(f"{doctype} does not have canonical Branch attribution")
        conditions.append(f"`{alias}`.`{branch_field}` = %(branch)s")
        params["branch"] = branch

    if from_date and to_date and date_field:
        conditions.append(f"`{alias}`.`{date_field}` between %(from_date)s and %(to_date)s")
        params.update({"from_date": from_date, "to_date": to_date})

    if docstatus is not None and meta and meta.has_field("docstatus"):
        conditions.append(f"`{alias}`.`docstatus` = %(docstatus)s")
        params["docstatus"] = docstatus

    return conditions, params


def _where(conditions: list[str]) -> str:
    return (" where " + " and ".join(conditions)) if conditions else ""


def _daily_definition() -> ReportDefinition:
    return ReportDefinition(
        report_id=DAILY_REPORT_ID,
        name=PILOT_REPORT_NAMES[DAILY_REPORT_ID],
        required_capability="OPERATIONAL_REPORTING",
        columns=(
            ColumnSpec("posting_date", "Posting Date", "Date"),
            ColumnSpec("invoice", "Sales Invoice", "Link"),
            ColumnSpec("classification", "Classification"),
            ColumnSpec("branch", "Branch"),
            ColumnSpec("fulfilment_type", "Fulfilment Type"),
            ColumnSpec("amount", "Amount", "Currency"),
        ),
        require_date_range=True,
        max_date_range_days=31,
        default_page_size=50,
        max_page_size=200,
        export_row_limit=10000,
        print_row_limit=1000,
    )


def _online_definition() -> ReportDefinition:
    return ReportDefinition(
        report_id=ONLINE_REPORT_ID,
        name=PILOT_REPORT_NAMES[ONLINE_REPORT_ID],
        required_capability="DELIVERY_ONLINE_REPORTING",
        columns=(
            ColumnSpec("order_date", "Order Date", "Datetime"),
            ColumnSpec("order", "Online Order", "Link"),
            ColumnSpec("stage", "Canonical Stage"),
            ColumnSpec("status", "Source Status"),
            ColumnSpec("branch", "Branch"),
            ColumnSpec("fulfilment_type", "Fulfilment Type"),
            ColumnSpec("sales_invoice", "Sales Invoice", "Link"),
        ),
        require_date_range=True,
        max_date_range_days=31,
        default_page_size=50,
        max_page_size=200,
        export_row_limit=10000,
        print_row_limit=1000,
    )


def _shift_definition() -> ReportDefinition:
    return ReportDefinition(
        report_id=SHIFT_REPORT_ID,
        name=PILOT_REPORT_NAMES[SHIFT_REPORT_ID],
        required_capability="SHIFT_CASH_CONTROL_REPORTING",
        columns=(
            ColumnSpec("metric", "Metric"),
            ColumnSpec("classification", "Classification"),
            ColumnSpec("value", "Value", "Currency"),
            ColumnSpec("status", "Status"),
            ColumnSpec("source", "Source"),
        ),
        require_date_range=False,
        default_page_size=50,
        max_page_size=50,
        export_row_limit=200,
        print_row_limit=200,
    )


def _sales_amount_fields() -> dict[str, str]:
    return {
        "amount": _column("Sales Invoice", ("base_grand_total", "grand_total"), "grand_total"),
        "discount": _column("Sales Invoice", ("base_discount_amount", "discount_amount"), "discount_amount"),
        "tax": _column(
            "Sales Invoice",
            ("base_total_taxes_and_charges", "total_taxes_and_charges"),
            "total_taxes_and_charges",
        ),
    }


def _online_mapping() -> dict[str, str | None]:
    return {
        "date": _field("Online Order", ONLINE_DATE_FIELDS),
        "branch": _field("Online Order", BRANCH_FIELDS),
        "fulfilment": _field("Online Order", FULFILMENT_FIELDS),
        "payment": _field("Online Order", ONLINE_PAYMENT_FIELDS),
        "sales_invoice": _field("Online Order", ONLINE_SI_FIELDS),
    }


def _cash_modes() -> set[str]:
    if not frappe.db.exists("DocType", "Mode of Payment"):
        return set()
    type_field = _field("Mode of Payment", ("type",))
    if not type_field:
        return set()
    return set(
        frappe.get_all(
            "Mode of Payment",
            filters={type_field: "Cash"},
            pluck="name",
            limit_page_length=0,
        )
    )


def _card_modes() -> set[str]:
    modes: set[str] = set()

    # A Card POS Terminal is itself a canonical card mapping source.
    if frappe.db.exists("DocType", "Card POS Terminal"):
        mop_field = _field(
            "Card POS Terminal",
            ("mode_of_payment", "payment_method", "mode_of_payment_name"),
        )
        if mop_field:
            for value in frappe.get_all(
                "Card POS Terminal",
                pluck=mop_field,
                limit_page_length=0,
            ):
                if value:
                    modes.add(value)

    # Generic clearing setup is accepted only when a category explicitly says Card.
    if frappe.db.exists("DocType", "Payment Method Clearing Setup"):
        mop_field = _field(
            "Payment Method Clearing Setup",
            ("mode_of_payment", "payment_method", "mode_of_payment_name"),
        )
        category_field = _field(
            "Payment Method Clearing Setup",
            ("payment_category", "category", "tender_type", "method_type", "payment_type"),
        )
        if mop_field and category_field:
            rows = frappe.get_all(
                "Payment Method Clearing Setup",
                fields=[mop_field, category_field],
                limit_page_length=0,
            )
            for row in rows:
                if str(row.get(category_field) or "").strip().casefold() == "card":
                    value = row.get(mop_field)
                    if value:
                        modes.add(value)
    return modes


def _payment_sum_for_modes(
    *,
    modes: set[str],
    company: str,
    branch: str,
    branch_field: str | None,
    from_date: str,
    to_date: str,
    exclude_home_delivery: bool,
    payment_method_filter: str | None,
) -> float | None:
    if not modes:
        return None
    if not frappe.db.exists("DocType", "Sales Invoice Payment"):
        return None

    payment_amount = _field("Sales Invoice Payment", ("base_amount", "amount"))
    mode_field = _field("Sales Invoice Payment", ("mode_of_payment",))
    if not payment_amount or not mode_field:
        return None

    fulfilment_field = _field("Sales Invoice", FULFILMENT_FIELDS)
    if exclude_home_delivery and not fulfilment_field:
        # Direct till cash cannot safely be calculated without excluding driver cash.
        return None

    conditions, params = _sql_conditions(
        doctype="Sales Invoice",
        company=company,
        branch=branch,
        branch_field=branch_field,
        from_date=from_date,
        to_date=to_date,
        date_field="posting_date",
        docstatus=1,
        alias="si",
    )
    conditions.append("coalesce(`si`.`is_return`, 0) = 0")

    effective_modes = set(modes)
    if payment_method_filter:
        if payment_method_filter not in effective_modes:
            return 0.0
        effective_modes = {payment_method_filter}

    placeholders = []
    for idx, mode in enumerate(sorted(effective_modes)):
        key = f"mop_{idx}"
        params[key] = mode
        placeholders.append(f"%({key})s")
    conditions.append(f"`p`.`{mode_field}` in ({', '.join(placeholders)})")

    if exclude_home_delivery:
        conditions.append(
            f"lower(trim(coalesce(`si`.`{fulfilment_field}`, ''))) != 'home delivery'"
        )

    value = frappe.db.sql(
        f"""
        select coalesce(sum(`p`.`{payment_amount}`), 0)
        from `tabSales Invoice Payment` p
        inner join `tabSales Invoice` si on si.name = p.parent
        {_where(conditions)}
        """,
        params,
    )[0][0]
    return flt(value)


def _online_sales_invoice_names(
    *,
    company: str,
    branch: str,
    from_date: str,
    to_date: str,
) -> tuple[set[str] | None, dict[str, Any]]:
    if not frappe.db.exists("DocType", "Online Order"):
        return set(), {"status": "Online Order DocType unavailable"}

    mapping = _online_mapping()
    si_field = mapping["sales_invoice"]
    date_field = mapping["date"]
    branch_field = mapping["branch"]
    if not si_field or not date_field:
        return None, {"status": "Online Order → Sales Invoice canonical link/date mapping unavailable"}

    conditions, params = _sql_conditions(
        doctype="Online Order",
        company=company,
        branch=branch,
        branch_field=branch_field,
        from_date=from_date,
        to_date=to_date,
        date_field=date_field,
        alias="o",
    )
    conditions.append(f"coalesce(`o`.`{si_field}`, '') != ''")
    names = set(
        frappe.db.sql(
            f"select distinct `o`.`{si_field}` from `tabOnline Order` o {_where(conditions)}",
            params,
            pluck=True,
        )
    )
    return names, {"status": "Mapped", "field": si_field, "date_field": date_field}


def _daily_runner(context) -> RunnerResult:
    company = context.scope.company
    branch = context.scope.branches[0]
    f = dict(context.scope.normalized_filters)
    from_date, to_date = f["from_date"], f["to_date"]

    amount_fields = _sales_amount_fields()
    branch_field = _field("Sales Invoice", BRANCH_FIELDS)
    fulfilment_field = _field("Sales Invoice", FULFILMENT_FIELDS)
    payment_method_filter = f.get("payment_method")

    conditions, params = _sql_conditions(
        doctype="Sales Invoice",
        company=company,
        branch=branch,
        branch_field=branch_field,
        from_date=from_date,
        to_date=to_date,
        date_field="posting_date",
        docstatus=1,
        alias="si",
    )

    if f.get("fulfilment_type"):
        if not fulfilment_field:
            raise ValidationError("Sales Invoice has no canonical Fulfilment Type field")
        conditions.append(f"`si`.`{fulfilment_field}` = %(fulfilment_type)s")
        params["fulfilment_type"] = f["fulfilment_type"]

    # Payment Method filter narrows the invoice population using a canonical child payment row.
    if payment_method_filter:
        if not frappe.db.exists("DocType", "Sales Invoice Payment"):
            raise ValidationError("Sales Invoice Payment is unavailable for Payment Method filtering")
        conditions.append(
            """exists (
                select 1 from `tabSales Invoice Payment` pm
                where pm.parent = si.name and pm.mode_of_payment = %(payment_method)s
            )"""
        )
        params["payment_method"] = payment_method_filter

    where_sql = _where(conditions)
    amount = amount_fields["amount"]
    discount = amount_fields["discount"]
    tax = amount_fields["tax"]

    aggregate = frappe.db.sql(
        f"""
        select
          sum(case when coalesce(si.is_return,0)=0 then greatest(coalesce(si.`{amount}`,0),0) else 0 end) as gross_sales,
          sum(case when coalesce(si.is_return,0)=1 then abs(coalesce(si.`{amount}`,0)) else 0 end) as returns,
          sum(case when coalesce(si.is_return,0)=0 then coalesce(si.`{discount}`,0) else 0 end) as discounts,
          sum(coalesce(si.`{tax}`,0)) as vat,
          sum(case when coalesce(si.is_return,0)=0 then 1 else 0 end) as invoice_count,
          sum(case when coalesce(si.is_return,0)=1 then 1 else 0 end) as return_count
        from `tabSales Invoice` si
        {where_sql}
        """,
        params,
        as_dict=True,
    )[0]
    gross = flt(aggregate.gross_sales)
    returns = flt(aggregate.returns)
    net = gross - returns

    total_rows = frappe.db.sql(
        f"select count(*) from `tabSales Invoice` si {where_sql}",
        params,
    )[0][0]

    select_branch = (
        f"`si`.`{branch_field}`" if branch_field else "%(not_attr)s"
    )
    params["not_attr"] = "Not Attributable"
    select_fulfilment = (
        f"`si`.`{fulfilment_field}`" if fulfilment_field else "NULL"
    )
    rows = frappe.db.sql(
        f"""
        select
          si.posting_date,
          si.name as invoice,
          case when coalesce(si.is_return,0)=1 then 'Return' else 'Sale' end as classification,
          {select_branch} as branch,
          {select_fulfilment} as fulfilment_type,
          si.`{amount}` as amount
        from `tabSales Invoice` si
        {where_sql}
        order by si.posting_date desc, si.name desc
        limit %(limit)s offset %(offset)s
        """,
        {**params, "limit": context.limit, "offset": context.offset},
        as_dict=True,
    )

    home_delivery_count = None
    pickup_count = None
    if fulfilment_field:
        count_rows = frappe.db.sql(
            f"""
            select lower(trim(coalesce(si.`{fulfilment_field}`, ''))) as fulfilment, count(*) as c
            from `tabSales Invoice` si
            {where_sql}
              {"and" if conditions else "where"} coalesce(si.is_return,0)=0
            group by lower(trim(coalesce(si.`{fulfilment_field}`, '')))
            """,
            params,
            as_dict=True,
        )
        fc = {r.fulfilment: int(r.c) for r in count_rows}
        home_delivery_count = fc.get("home delivery", 0)
        pickup_count = fc.get("pharmacy pickup", 0) + fc.get("pickup", 0)

    online_mapping = {"status": "Not Attributable"}
    online_sales = None
    order_count = None
    si_online_field = _field("Sales Invoice", SI_ONLINE_ORDER_FIELDS)
    if si_online_field:
        online_sales = flt(
            frappe.db.sql(
                f"""
                select coalesce(sum(si.`{amount}`), 0)
                from `tabSales Invoice` si
                {where_sql}
                  {"and" if conditions else "where"} coalesce(si.is_return,0)=0
                  and coalesce(si.`{si_online_field}`, '') != ''
                """,
                params,
            )[0][0]
        )
        online_mapping = {"status": "Mapped", "sales_invoice_field": si_online_field}

    if frappe.db.exists("DocType", "Online Order"):
        om = _online_mapping()
        if om["date"]:
            oc, op = _sql_conditions(
                doctype="Online Order",
                company=company,
                branch=branch,
                branch_field=om["branch"],
                from_date=from_date,
                to_date=to_date,
                date_field=om["date"],
                alias="o",
            )
            order_count = int(
                frappe.db.sql(
                    f"select count(distinct o.name) from `tabOnline Order` o {_where(oc)}",
                    op,
                )[0][0]
            )

    direct_till_cash = _payment_sum_for_modes(
        modes=_cash_modes(),
        company=company,
        branch=branch,
        branch_field=branch_field,
        from_date=from_date,
        to_date=to_date,
        exclude_home_delivery=True,
        payment_method_filter=payment_method_filter,
    )
    card_modes = _card_modes()
    card_sales = _payment_sum_for_modes(
        modes=card_modes,
        company=company,
        branch=branch,
        branch_field=branch_field,
        from_date=from_date,
        to_date=to_date,
        exclude_home_delivery=False,
        payment_method_filter=payment_method_filter,
    )

    summary = {
        "gross_sales": gross,
        "returns": returns,
        "net_sales": net,
        "discounts": flt(aggregate.discounts),
        "vat": flt(aggregate.vat),
        "invoice_count": int(aggregate.invoice_count or 0),
        "return_count": int(aggregate.return_count or 0),
        "online_sales": online_sales,
        "online_order_count": order_count,
        "home_delivery_count": home_delivery_count,
        "pickup_count": pickup_count,
        "direct_till_cash": direct_till_cash,
        "card_sales": card_sales,
        "card_mapping_status": "Mapped" if card_modes else "Not Configured",
        "online_mapping_status": online_mapping.get("status"),
        "branch_attribution": branch if branch != NOT_ATTRIBUTABLE_BRANCH else "Not Attributable",
        "amount_basis": amount,
    }
    totals = {
        "gross_sales": gross,
        "returns": returns,
        "net_sales": net,
    }
    return RunnerResult(rows=rows, total_rows=int(total_rows), summary=summary, totals=totals)


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.append((path, item))
            out.extend(_flatten(item, path))
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            path = f"{prefix}[{idx}]"
            out.extend(_flatten(item, path))
    return out


def _normalized_key(path: str) -> str:
    tail = path.split(".")[-1]
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in tail).strip("_")


def _extract_alias(flat: list[tuple[str, Any]], aliases: Iterable[str]) -> tuple[Any, str | None]:
    wanted = {a.casefold() for a in aliases}
    matches: list[tuple[int, str, Any]] = []
    for path, value in flat:
        key = _normalized_key(path).casefold()
        if key in wanted and isinstance(value, (int, float, str)):
            try:
                numeric = flt(value)
            except Exception:
                continue
            matches.append((path.count(".") + path.count("["), path, numeric))
    if not matches:
        return None, None
    matches.sort(key=lambda x: (x[0], len(x[1])))
    _, path, value = matches[0]
    return value, path


def _adaptive_call(func, shift_name: str):
    sig = inspect.signature(func)
    kwargs: dict[str, Any] = {}
    supported = {"shift_name", "shift", "name", "shift_id", "shift_reference"}
    required_unknown = []
    for pname, p in sig.parameters.items():
        if pname in supported:
            kwargs[pname] = shift_name
        elif p.default is inspect._empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY):
            required_unknown.append(pname)
    if required_unknown:
        raise TypeError(f"unsupported required parameters: {required_unknown}")
    return func(**kwargs)


def _shift_doc_fallback(shift_name: str) -> tuple[dict[str, Any], dict[str, str]]:
    doc = frappe.get_doc("Pharmacy Shift Closing", shift_name)
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for metric, aliases in SHIFT_FIELD_ALIASES.items():
        field = _field("Pharmacy Shift Closing", aliases)
        if field:
            values[metric] = flt(doc.get(field))
            sources[metric] = f"Pharmacy Shift Closing.{field}"
    return values, sources


def canonical_shift_snapshot(shift_name: str) -> dict[str, Any]:
    """Return a historical, read-only shift snapshot.

    Closed-shift cash figures are read from Pharmacy Shift Closing fields that
    were frozen at review/final close. Driver figures reuse the existing
    `_delivery_driver_summaries(shift)` logic directly, avoiding the whitelisted
    System Manager-only wrapper and avoiding any current/open-shift dashboard.
    """
    _require_named_doc_read("Pharmacy Shift Closing", shift_name)
    shift_doc = frappe.get_doc("Pharmacy Shift Closing", shift_name)

    values, sources = _shift_doc_fallback(shift_name)

    driver_rows = []
    driver_error = None
    try:
        from pharma_erp.pharma_erp import payment_card_management as pcm
        if hasattr(pcm, "_delivery_driver_summaries"):
            driver_rows = list(pcm._delivery_driver_summaries(shift_doc) or [])
    except Exception as exc:
        driver_error = f"{type(exc).__name__}: {exc}"

    if driver_rows:
        expected = flt(sum(flt(row.get("expected_amount")) for row in driver_rows))
        handed = flt(sum(flt(row.get("handed_over_amount")) for row in driver_rows))
        remaining = flt(sum(flt(row.get("remaining_amount")) for row in driver_rows))

        values["driver_expected_cash"] = expected
        values["driver_handed_over_cash"] = handed
        values["delivery_cash_in_transit"] = remaining

        sources["driver_expected_cash"] = (
            "payment_card_management._delivery_driver_summaries:sum(expected_amount)"
        )
        sources["driver_handed_over_cash"] = (
            "payment_card_management._delivery_driver_summaries:sum(handed_over_amount)"
        )
        sources["delivery_cash_in_transit"] = (
            "payment_card_management._delivery_driver_summaries:sum(remaining_amount)"
        )

    # Pharmacy Shift Closing.total_cash_sales is the frozen total cash sales
    # population, including Home Delivery cash.  It is NOT Direct Till Cash.
    # Direct Till Cash must exclude the shift-scoped driver cash population.
    total_cash_sales = values.get("total_cash_sales")
    if total_cash_sales is not None:
        if driver_error:
            # Do not guess when the canonical driver summary could not be read.
            values.pop("direct_till_cash", None)
            sources.pop("direct_till_cash", None)
        else:
            driver_expected = flt(values.get("driver_expected_cash") or 0)
            direct_till = flt(total_cash_sales) - driver_expected
            if direct_till < -0.005:
                values.pop("direct_till_cash", None)
                sources.pop("direct_till_cash", None)
            else:
                values["direct_till_cash"] = max(0.0, flt(direct_till))
                sources["direct_till_cash"] = (
                    "Derived: Pharmacy Shift Closing.total_cash_sales "
                    "- payment_card_management._delivery_driver_summaries:sum(expected_amount)"
                )

    expected = values.get("expected_cash")
    counted = values.get("counted_cash")
    if "cash_difference" not in values and expected is not None and counted is not None:
        values["cash_difference"] = flt(counted) - flt(expected)
        sources["cash_difference"] = "Derived: Counted Cash - Expected Cash"

    difference = values.get("cash_difference")
    if difference is None:
        reconciliation = "Incomplete Mapping"
    elif abs(flt(difference)) <= 0.005:
        reconciliation = "Control Balanced"
    else:
        reconciliation = "Review Required"

    return {
        "shift": shift_name,
        "metrics": values,
        "sources": sources,
        "reconciliation_status": reconciliation,
        "driver_summary_count": len(driver_rows),
        "driver_summary_error": driver_error,
    }


def _shift_runner(context) -> RunnerResult:
    filters = dict(context.scope.normalized_filters)
    shift_name = filters.get("shift")
    if not shift_name:
        raise ValidationError("Shift is required")
    snapshot = canonical_shift_snapshot(shift_name)

    specs = [
        ("opening_float", "Opening Float", "Control"),
        ("direct_till_cash", "Direct Till Cash", "Operational Control"),
        ("delivery_cash_in_transit", "Delivery Cash In Transit", "Control / Expected"),
        ("driver_expected_cash", "Driver Expected Cash", "Control / Expected"),
        ("driver_handed_over_cash", "Driver Handed Over Cash", "Operational / Control"),
        ("expected_cash", "Cash Drawer Expected Balance", "Control / Expected"),
        ("counted_cash", "Counted Cash", "Control / Actual"),
        ("cash_difference", "Cash Difference", "Control"),
        ("posted_gl_balance", "Posted GL Balance", "Accounting"),
        ("pending_posting", "Pending Posting", "Pending Posting"),
    ]
    rows = []
    for key, label, classification in specs:
        value = snapshot["metrics"].get(key)
        source = snapshot["sources"].get(key, "Not mapped at current checkpoint")
        rows.append(
            {
                "metric": label,
                "classification": classification,
                "value": value,
                "status": "Mapped" if value is not None else "Not Attributable",
                "source": source,
            }
        )
    rows.append(
        {
            "metric": "Reconciliation Status",
            "classification": "Control",
            "value": None,
            "status": snapshot["reconciliation_status"],
            "source": "Derived from canonical control values",
        }
    )
    return RunnerResult(
        rows=rows,
        total_rows=len(rows),
        summary={
            **snapshot["metrics"],
            "reconciliation_status": snapshot["reconciliation_status"],
            "shift": shift_name,
        },
        totals={},
    )


def _canonical_online_stage(status: str, has_invoice: bool) -> str:
    raw = (status or "").strip().casefold()
    if raw in {"cancelled", "canceled", "rejected", "payment failed"}:
        return "Cancelled"
    if raw in {"delivered", "completed"}:
        return "Delivered / Completed"
    if raw in {"out for delivery", "out_for_delivery"}:
        return "Out for Delivery"
    if has_invoice or raw in {"invoiced", "invoice submitted"}:
        return "Invoiced"
    if raw in {"confirmed"}:
        return "Confirmed"
    if raw in {"ready for payment"}:
        return "Ready for Payment"
    if raw in {"under review", "prescription review", "stock review", "review"}:
        return "Under Review"
    if raw in {"draft", "placed"}:
        return "Placed"
    return "Other"


def _online_runner(context) -> RunnerResult:
    if not frappe.db.exists("DocType", "Online Order"):
        raise ValidationError("Online Order DocType is unavailable")
    mapping = _online_mapping()
    if not mapping["date"]:
        raise ValidationError("Online Order has no canonical date field")

    company = context.scope.company
    branch = context.scope.branches[0]
    f = dict(context.scope.normalized_filters)
    conditions, params = _sql_conditions(
        doctype="Online Order",
        company=company,
        branch=branch,
        branch_field=mapping["branch"],
        from_date=f["from_date"],
        to_date=f["to_date"],
        date_field=mapping["date"],
        alias="o",
    )

    if f.get("status"):
        conditions.append("`o`.`status` = %(status)s")
        params["status"] = f["status"]
    if f.get("fulfilment_type"):
        if not mapping["fulfilment"]:
            raise ValidationError("Online Order has no canonical Fulfilment Type field")
        conditions.append(f"`o`.`{mapping['fulfilment']}` = %(fulfilment_type)s")
        params["fulfilment_type"] = f["fulfilment_type"]
    if f.get("payment_method"):
        if not mapping["payment"]:
            raise ValidationError("Online Order has no canonical Payment Method field")
        conditions.append(f"`o`.`{mapping['payment']}` = %(payment_method)s")
        params["payment_method"] = f["payment_method"]

    where_sql = _where(conditions)
    total_rows = int(
        frappe.db.sql(
            f"select count(distinct o.name) from `tabOnline Order` o {where_sql}",
            params,
        )[0][0]
    )

    select_branch = (
        f"`o`.`{mapping['branch']}`" if mapping["branch"] else "%(not_attr)s"
    )
    params["not_attr"] = "Not Attributable"
    select_fulfilment = (
        f"`o`.`{mapping['fulfilment']}`" if mapping["fulfilment"] else "NULL"
    )
    select_invoice = (
        f"`o`.`{mapping['sales_invoice']}`" if mapping["sales_invoice"] else "NULL"
    )

    raw_rows = frappe.db.sql(
        f"""
        select
          `o`.`{mapping['date']}` as order_date,
          o.name as `order`,
          o.status,
          {select_branch} as branch,
          {select_fulfilment} as fulfilment_type,
          {select_invoice} as sales_invoice
        from `tabOnline Order` o
        {where_sql}
        order by `o`.`{mapping['date']}` desc, o.name desc
        limit %(limit)s offset %(offset)s
        """,
        {**params, "limit": context.limit, "offset": context.offset},
        as_dict=True,
    )

    # Full population stage counts are intentionally calculated independently of
    # the paged detail rows so cards reconcile to source count.
    all_stage_source = frappe.db.sql(
        f"""
        select o.status,
               {select_invoice} as sales_invoice
        from `tabOnline Order` o
        {where_sql}
        """,
        params,
        as_dict=True,
    )
    stages = Counter(
        _canonical_online_stage(r.status, bool(r.sales_invoice))
        for r in all_stage_source
    )

    rows = []
    for r in raw_rows:
        rows.append(
            {
                "order_date": r.order_date,
                "order": r.order,
                "stage": _canonical_online_stage(r.status, bool(r.sales_invoice)),
                "status": r.status,
                "branch": r.branch,
                "fulfilment_type": r.fulfilment_type,
                "sales_invoice": r.sales_invoice,
            }
        )

    return RunnerResult(
        rows=rows,
        total_rows=total_rows,
        summary={
            "total_orders": total_rows,
            "stages": dict(stages),
            "branch_attribution": branch if branch != NOT_ATTRIBUTABLE_BRANCH else "Not Attributable",
            "mapping": mapping,
        },
        totals={},
    )


def _registry() -> ReportRegistry:
    reg = ReportRegistry()
    reg.register(_daily_definition(), _daily_runner)
    reg.register(_shift_definition(), _shift_runner)
    reg.register(_online_definition(), _online_runner)
    return reg


def _execute_report(report_id: str, filters: Mapping[str, Any] | None):
    filters = dict(filters or {})
    source_doctype = {
        DAILY_REPORT_ID: "Sales Invoice",
        SHIFT_REPORT_ID: "Pharmacy Shift Closing",
        ONLINE_REPORT_ID: "Online Order",
    }[report_id]
    _require_source_read(source_doctype)

    if report_id == SHIFT_REPORT_ID:
        shift_name = filters.get("shift")
        if not shift_name:
            raise ValidationError("Shift is required")
        shift_doc = frappe.get_doc("Pharmacy Shift Closing", shift_name)
        company_field = _field("Pharmacy Shift Closing", ("company",))
        company = filters.get("company") or (shift_doc.get(company_field) if company_field else None)
        company = _resolve_company(company)
        branch_field = _field("Pharmacy Shift Closing", BRANCH_FIELDS)
        detected_branch = shift_doc.get(branch_field) if branch_field else None
        requested_branch = filters.get("branch") or detected_branch
        branch, _, branch_map = _resolve_branch(company, requested_branch, "Pharmacy Shift Closing")
        filters["company"] = company
        filters["branch"] = branch
        filters.setdefault("page", 1)
        filters.setdefault("page_size", 50)
        permission = _permission_context(report_id, company, branch)
        request = ExecutionRequest(
            report_id=report_id,
            filters=filters,
            page=int(filters.get("page") or 1),
            page_size=int(filters.get("page_size") or 50),
            mode=ExecutionMode.SCREEN,
        )
        return execute_foundation(
            registry=_registry(),
            request=request,
            permission=permission,
            branch_company_map=branch_map,
        )

    company = _resolve_company(filters.get("company"))
    branch, _, branch_map = _resolve_branch(company, filters.get("branch"), source_doctype)
    filters["company"] = company
    filters["branch"] = branch
    filters.setdefault("page", 1)
    filters.setdefault("page_size", 50)
    permission = _permission_context(report_id, company, branch)
    request = ExecutionRequest(
        report_id=report_id,
        filters=filters,
        page=int(filters.get("page") or 1),
        page_size=int(filters.get("page_size") or 50),
        mode=ExecutionMode.SCREEN,
    )
    return execute_foundation(
        registry=_registry(),
        request=request,
        permission=permission,
        branch_company_map=branch_map,
    )


def _execute_report_ui(report_id: str, filters: Mapping[str, Any] | None):
    """Desk-facing adapter that preserves foundation guards without Server Error UX."""
    try:
        return _execute_report(report_id, filters)
    except PermissionDenied as exc:
        frappe.throw(
            str(exc),
            title=_("Report Permission Denied"),
            exc=frappe.PermissionError,
        )
    except ValidationError as exc:
        frappe.throw(
            str(exc),
            title=_("Invalid Report Filters"),
            exc=frappe.ValidationError,
        )


def _currency(value: Any, currency: str | None = None) -> dict[str, Any]:
    return {
        "value": flt(value),
        "indicator": "Blue",
        "datatype": "Currency",
        "currency": currency,
    }


def _number(value: Any, indicator: str = "Blue") -> dict[str, Any]:
    return {"value": int(value or 0), "indicator": indicator, "datatype": "Int"}


def daily_report(filters=None):
    result = _execute_report_ui(DAILY_REPORT_ID, filters)
    s = dict(result.summary)
    company = result.applied_filters.get("company")
    currency = frappe.db.get_value("Company", company, "default_currency") if company else None

    columns = [
        {"fieldname": "posting_date", "label": _("Posting Date"), "fieldtype": "Date", "width": 105},
        {"fieldname": "invoice", "label": _("Sales Invoice"), "fieldtype": "Link", "options": "Sales Invoice", "width": 180},
        {"fieldname": "classification", "label": _("Classification"), "fieldtype": "Data", "width": 100},
        {"fieldname": "branch", "label": _("Branch"), "fieldtype": "Data", "width": 130},
        {"fieldname": "fulfilment_type", "label": _("Fulfilment Type"), "fieldtype": "Data", "width": 135},
        {"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "options": "currency", "width": 120},
    ]

    summary = [
        {**_currency(s.get("gross_sales"), currency), "label": _("Gross Sales")},
        {**_currency(s.get("returns"), currency), "label": _("Returns"), "indicator": "Orange"},
        {**_currency(s.get("net_sales"), currency), "label": _("Net Sales"), "indicator": "Green"},
        {**_number(s.get("invoice_count")), "label": _("Invoice Count")},
    ]
    if s.get("online_order_count") is not None:
        summary.append({**_number(s.get("online_order_count")), "label": _("Online Orders")})
    if s.get("home_delivery_count") is not None:
        summary.append({**_number(s.get("home_delivery_count")), "label": _("Home Delivery")})
    if s.get("pickup_count") is not None:
        summary.append({**_number(s.get("pickup_count")), "label": _("Pharmacy Pickup")})
    if s.get("direct_till_cash") is not None:
        summary.append({**_currency(s["direct_till_cash"], currency), "label": _("Direct Till Cash")})
    if s.get("card_sales") is not None:
        summary.append({**_currency(s["card_sales"], currency), "label": _("Card Sales")})

    message = _(
        "Branch attribution: {0}. Amount basis: {1}. Card mapping: {2}. "
        "Showing page {3}; total source rows: {4}."
    ).format(
        s.get("branch_attribution"),
        s.get("amount_basis"),
        s.get("card_mapping_status"),
        result.metadata.page,
        result.metadata.total_rows,
    )

    chart = {
        "data": {
            "labels": [_("Invoices"), _("Returns"), _("Online Orders"), _("Home Delivery"), _("Pickup")],
            "datasets": [{
                "name": _("Count"),
                "values": [
                    s.get("invoice_count") or 0,
                    s.get("return_count") or 0,
                    s.get("online_order_count") or 0,
                    s.get("home_delivery_count") or 0,
                    s.get("pickup_count") or 0,
                ],
            }],
        },
        "type": "bar",
    }
    return columns, list(result.rows), message, chart, summary


def shift_report(filters=None):
    result = _execute_report_ui(SHIFT_REPORT_ID, filters)
    s = dict(result.summary)
    company = result.applied_filters.get("company")
    currency = frappe.db.get_value("Company", company, "default_currency") if company else None
    columns = [
        {"fieldname": "metric", "label": _("Metric"), "fieldtype": "Data", "width": 210},
        {"fieldname": "classification", "label": _("Classification"), "fieldtype": "Data", "width": 150},
        {"fieldname": "value", "label": _("Value"), "fieldtype": "Currency", "options": "currency", "width": 125},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 140},
        {"fieldname": "source", "label": _("Source"), "fieldtype": "Data", "width": 360},
    ]
    summary = []
    for key, label in [
        ("opening_float", _("Opening Float")),
        ("direct_till_cash", _("Direct Till Cash")),
        ("driver_expected_cash", _("Driver Expected Cash")),
        ("driver_handed_over_cash", _("Driver Handed Over")),
        ("expected_cash", _("Expected Cash")),
        ("counted_cash", _("Counted Cash")),
        ("cash_difference", _("Difference")),
    ]:
        if s.get(key) is not None:
            indicator = "Green" if key == "cash_difference" and abs(flt(s[key])) <= 0.005 else "Blue"
            summary.append({**_currency(s[key], currency), "label": label, "indicator": indicator})
    message = _("Shift {0} — reconciliation: {1}. Unmapped values are explicitly shown as Not Attributable.").format(
        s.get("shift"), s.get("reconciliation_status")
    )
    return columns, list(result.rows), message, None, summary


def online_report(filters=None):
    result = _execute_report_ui(ONLINE_REPORT_ID, filters)
    s = dict(result.summary)
    stages = s.get("stages") or {}
    columns = [
        {"fieldname": "order_date", "label": _("Order Date"), "fieldtype": "Datetime", "width": 145},
        {"fieldname": "order", "label": _("Online Order"), "fieldtype": "Link", "options": "Online Order", "width": 175},
        {"fieldname": "stage", "label": _("Canonical Stage"), "fieldtype": "Data", "width": 160},
        {"fieldname": "status", "label": _("Source Status"), "fieldtype": "Data", "width": 145},
        {"fieldname": "branch", "label": _("Branch"), "fieldtype": "Data", "width": 130},
        {"fieldname": "fulfilment_type", "label": _("Fulfilment Type"), "fieldtype": "Data", "width": 145},
        {"fieldname": "sales_invoice", "label": _("Sales Invoice"), "fieldtype": "Link", "options": "Sales Invoice", "width": 180},
    ]

    ordered_stages = [
        "Placed", "Under Review", "Ready for Payment", "Confirmed",
        "Invoiced", "Out for Delivery", "Delivered / Completed", "Cancelled", "Other",
    ]
    summary = [
        {**_number(s.get("total_orders")), "label": _("Total Orders")},
        {**_number(stages.get("Delivered / Completed"), "Green"), "label": _("Delivered / Completed")},
        {**_number(stages.get("Out for Delivery"), "Orange"), "label": _("Out for Delivery")},
        {**_number(stages.get("Cancelled"), "Red"), "label": _("Cancelled")},
    ]
    chart = {
        "data": {
            "labels": [stage for stage in ordered_stages if stages.get(stage)],
            "datasets": [{
                "name": _("Orders"),
                "values": [stages.get(stage, 0) for stage in ordered_stages if stages.get(stage)],
            }],
        },
        "type": "bar",
    }
    message = _("Stage buckets reconcile to {0} scoped Online Orders. Branch attribution: {1}.").format(
        s.get("total_orders"), s.get("branch_attribution")
    )
    return columns, list(result.rows), message, chart, summary


def runtime_mapping_snapshot() -> dict[str, Any]:
    return {
        "sales_invoice": {
            "branch": _field("Sales Invoice", BRANCH_FIELDS),
            "fulfilment": _field("Sales Invoice", FULFILMENT_FIELDS),
            "sales_channel": _field("Sales Invoice", SALES_CHANNEL_FIELDS),
            "shift": _field("Sales Invoice", SHIFT_LINK_FIELDS),
            **_sales_amount_fields(),
        },
        "online_order": _online_mapping() if frappe.db.exists("DocType", "Online Order") else None,
        "cash_modes_count": len(_cash_modes()),
        "card_modes_count": len(_card_modes()),
        "shift_dashboard_function": True,
    }
