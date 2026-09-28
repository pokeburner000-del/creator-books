"""Run the full pipeline: classify → total → project → tax → schedule → review → packet data."""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from . import tax as tx
from . import tax_tables as T
from .classifier import classify, load_rules
from .importers import Dataset
from .models import CATEGORIES, category_kind
from .review import Context, run_all


@dataclass
class Options:
    overrides: dict = field(default_factory=dict)  # txn_id -> {category, business_use_pct}
    rest_of_year_multiplier: float = 1.0  # pace of recurring income for the rest of the year
    extra_income: float = 0.0  # expected one-off income still to come (e.g. a signed brand deal)
    extra_expenses: float = 0.0
    salary_pct: float = 0.40  # S-corp screen
    admin_cost: float = 2_500.0
    sstb_share: float | None = None  # None = use sponsorship share of income
    as_of: date | None = None  # defaults to the latest transaction date


def _r(x: float) -> float:
    return round(x + 0.0, 2)


def analyze(ds: Dataset, opts: Options | None = None, rules: dict | None = None) -> dict:
    opts = opts or Options()
    p = ds.profile
    ty = T.get_year(p.tax_year)
    year_start, year_end = date(ty.year, 1, 1), date(ty.year, 12, 31)

    txns = classify(copy.deepcopy(ds.transactions), rules or load_rules(), opts.overrides)
    warnings = list(ds.warnings)
    outside = [t for t in txns if not (year_start <= t.date <= year_end)]
    if outside:
        warnings.append(f"{len(outside)} transaction(s) fall outside {ty.year} and were left out.")
    txns = [t for t in txns if year_start <= t.date <= year_end]

    through = opts.as_of or (max((t.date for t in txns), default=year_end))
    through = min(through, year_end)
    in_progress = through < year_end
    days_elapsed = (through - year_start).days + 1
    days_remaining = (year_end - through).days

    # ---- actuals by category ----
    actual = defaultdict(float)
    for t in txns:
        kind = category_kind(t.category)
        if kind == "income":
            actual[t.category] += t.amount
        elif kind == "expense":
            actual[t.category] += t.deductible_amount

    home_office = min(p.home_office_sqft, T.HOME_OFFICE_MAX_SQFT) * T.HOME_OFFICE_RATE

    monthly = [{"month": f"{ty.year}-{m:02d}", "income": 0.0, "expenses": 0.0} for m in range(1, 13)]
    for t in txns:
        kind = category_kind(t.category)
        if kind == "income":
            monthly[t.date.month - 1]["income"] += t.amount
        elif kind == "expense":
            monthly[t.date.month - 1]["expenses"] += t.deductible_amount
    monthly = [{**r, "income": _r(r["income"]), "expenses": _r(r["expenses"])}
               for r in monthly[: through.month]]

    # ---- full-year projection ----
    projected = {}
    for cat, amt in actual.items():
        meta = CATEGORIES[cat]
        full = amt
        if in_progress and meta.get("recurring"):
            rate = amt / days_elapsed * days_remaining
            if meta["kind"] == "income":
                rate *= opts.rest_of_year_multiplier
            full = amt + rate
        projected[cat] = full

    def tot(d, kind):
        return sum(v for k, v in d.items() if CATEGORIES[k]["kind"] == kind)

    ytd_income = tot(actual, "income")
    ytd_expenses = tot(actual, "expense") + home_office * days_elapsed / 365
    full_income = tot(projected, "income") + opts.extra_income
    full_expenses = tot(projected, "expense") + home_office + opts.extra_expenses

    spons = projected.get("sponsorship", 0.0)
    sstb_share = opts.sstb_share if opts.sstb_share is not None else (spons / full_income if full_income > 0 else 0.0)

    tax = tx.compute(ty.year, p.filing_status, full_income, full_expenses,
                     p.w2_wages, p.other_income, p.withholding, sstb_share)

    required, basis = tx.required_annual_payment(tax.total_tax, p.prior_year_total_tax, p.prior_year_agi, p.filing_status)
    pays = [(e.date, e.amount) for e in ds.estimates]
    schedule = tx.quarterly_schedule(ty.year, required, p.withholding, pays, as_of=through if in_progress else None)
    # an unpaid balance only matters if total due after withholding is $1,000+
    if tax.balance_after_withholding < T.PENALTY_DE_MINIMIS:
        for q in schedule:
            if q["status"] == "short":
                q["status"] = "ok"

    scorp = tx.s_corp_screen(ty.year, p.filing_status, full_income, full_expenses,
                             opts.salary_pct, opts.admin_cost, p.w2_wages, p.other_income)

    ctx = Context(txns, p, ds.forms, ds.estimates, tax, schedule, scorp, projected, in_progress, through, ty)
    flags = run_all(ctx, required, basis)

    # ---- what's owed now ----
    paid_total = sum(a for _, a in pays)
    remaining_balance = tax.total_tax - p.withholding - paid_total

    lines = []
    for cat, meta in CATEGORIES.items():
        if meta["kind"] in ("income", "expense") and (cat in actual or cat in projected):
            lines.append({
                "category": cat, "label": meta["label"], "kind": meta["kind"],
                "ytd": _r(actual.get(cat, 0.0)), "projected": _r(projected.get(cat, 0.0)),
                "recurring": bool(meta.get("recurring")), "schedule_c": meta.get("sched_c", "Line 1 gross receipts" if meta["kind"] == "income" else ""),
            })
    if home_office:
        lines.append({"category": "home_office", "label": "Home office (simplified method)", "kind": "expense",
                      "ytd": _r(home_office * days_elapsed / 365), "projected": _r(home_office),
                      "recurring": True, "schedule_c": "Line 30"})

    return {
        "profile": p.__dict__,
        "tax_year": ty.year,
        "period": {"start": year_start.isoformat(), "through": through.isoformat(),
                   "in_progress": in_progress, "days_elapsed": days_elapsed, "days_remaining": days_remaining},
        "files": ds.files,
        "warnings": warnings,
        "options": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in opts.__dict__.items() if k != "overrides"},
        "totals": {
            "ytd_income": _r(ytd_income), "ytd_expenses": _r(ytd_expenses), "ytd_profit": _r(ytd_income - ytd_expenses),
            "projected_income": _r(full_income), "projected_expenses": _r(full_expenses),
            "projected_profit": _r(full_income - full_expenses),
            "estimates_paid": _r(paid_total), "remaining_balance": _r(remaining_balance),
            "set_aside_rate": _r(tax.total_tax / (full_income - full_expenses)) if full_income > full_expenses else 0.0,
        },
        "lines": lines,
        "monthly": monthly,
        "tax": tax.to_dict(),
        "safe_harbor": {"required_annual": required, "basis": basis},
        "schedule": schedule,
        "s_corp": scorp,
        "flags": [f.to_dict() for f in flags],
        "transactions": [t.to_dict() for t in sorted(txns, key=lambda t: (t.date, t.id))],
        "categories": {k: {"label": v["label"], "kind": v["kind"]} for k, v in CATEGORIES.items()},
    }
