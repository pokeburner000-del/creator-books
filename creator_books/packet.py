"""Turn an analysis into a client packet (Markdown) and a classified-ledger CSV."""

from __future__ import annotations

import csv
import io

STANDARD_REQUESTS = [
    "Prior-year federal return (for the safe-harbor amount and any carryovers)",
    "All Forms 1099 (NEC, MISC, K) and any W-2s when they arrive in January",
    "Year-end statements from every payout platform (TikTok Shop, YouTube/AdSense, PayPal, others)",
    "Confirmation of each estimated tax payment made (date and amount)",
]


def m(x) -> str:
    if x is None:
        return "—"
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def document_requests(a: dict) -> list[str]:
    seen, out = set(), []
    for f in a["flags"]:
        r = f.get("request")
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    for r in STANDARD_REQUESTS:
        if r not in seen:
            out.append(r)
    return out


def to_markdown(a: dict) -> str:
    p, t, tot, per = a["profile"], a["tax"], a["totals"], a["period"]
    name = p.get("name") or "Client"
    mode = (f"Year to date through {per['through']}, projected to Dec 31"
            if per["in_progress"] else f"Full year {a['tax_year']}")
    L = [f"# Creator Books packet: {name}, tax year {a['tax_year']}", "",
         f"_{mode}. Filing status: {p['filing_status'].upper()}. Federal only._", ""]

    L += ["## Snapshot", "",
          "| | Year to date | Projected full year |", "| --- | ---: | ---: |",
          f"| Income | {m(tot['ytd_income'])} | {m(tot['projected_income'])} |",
          f"| Deductible expenses | {m(tot['ytd_expenses'])} | {m(tot['projected_expenses'])} |",
          f"| Net profit | {m(tot['ytd_profit'])} | {m(tot['projected_profit'])} |", "",
          f"**Projected federal tax: {m(t['total_tax'])}** "
          f"(self-employment tax {m(t['se']['total'] + t['se']['additional_medicare'])}, income tax {m(t['income_tax'])}). "
          f"Set aside about **{tot['set_aside_rate']:.0%} of profit**. "
          f"Estimated payments so far: {m(tot['estimates_paid'])}; still to pay: {m(tot['remaining_balance'])}.", ""]

    high = [f for f in a["flags"] if f["severity"] == "high"]
    if high:
        L += ["## Fix first", ""]
        L += [f"{i}. **{f['title']}.** {f['action'] or ''}".rstrip() for i, f in enumerate(high, 1)]
        L += [""]

    L += ["## Income and expenses", "", "| Category | Schedule C | Year to date | Projected |", "| --- | --- | ---: | ---: |"]
    for ln in a["lines"]:
        L.append(f"| {ln['label']} | {ln['schedule_c']} | {m(ln['ytd'])} | {m(ln['projected'])} |")
    L += [""]

    q = t["qbi"]
    L += ["## Tax projection", "", "| Step | Amount |", "| --- | ---: |",
          f"| Net profit (Schedule C) | {m(t['net_profit'])} |",
          f"| Self-employment tax (Schedule SE) | {m(t['se']['total'])} |",
          f"| Additional Medicare tax | {m(t['se']['additional_medicare'])} |",
          f"| Deductible half of SE tax | {m(-t['se']['deductible_half'])} |",
          f"| W-2 wages and other income | {m(t['w2_wages'] + t['other_income'])} |",
          f"| Adjusted gross income | {m(t['agi'])} |",
          f"| Standard deduction | {m(-t['standard_deduction'])} |",
          f"| QBI deduction ({q['method']}) | {m(-q['deduction'])} |",
          f"| Taxable income | {m(t['taxable_income'])} |",
          f"| Income tax ({t['marginal_rate']:.0%} marginal bracket) | {m(t['income_tax'])} |",
          f"| **Total federal tax** | **{m(t['total_tax'])}** |", "", q["note"], ""]

    sh = a["safe_harbor"]
    L += ["## Quarterly estimated payments", "",
          f"Safe-harbor target for the year: **{m(sh['required_annual'])}** ({sh['basis']}).", "",
          "| Quarter | Due | Required to date | Paid to date | Short | Status |", "| --- | --- | ---: | ---: | ---: | --- |"]
    for r in a["schedule"]:
        L.append(f"| {r['quarter']} | {r['due']} | {m(r['required_to_date'])} | {m(r['paid_to_date'])} | "
                 f"{m(r['shortfall'])} | {r['status']} |")
    L += [""]

    s = a["s_corp"]
    if s.get("s_corp_total") is not None:
        L += ["## S-corp check", "",
              f"Sole proprietor tax {m(s['sole_prop_total'])} vs. S-corp {m(s['s_corp_total'])} "
              f"with a {int(s['salary_pct']*100)}% salary and {m(s['admin_cost'])} in yearly costs: "
              f"**{'saves' if s['savings'] > 0 else 'costs'} {m(abs(s['savings']))}**. {s['verdict']}"
              + (f" Break-even profit at these assumptions: about {m(s['break_even_profit'])}." if s.get("break_even_profit") else ""),
              ""]

    L += ["## Review notes", ""]
    for f in a["flags"]:
        L.append(f"### [{f['severity'].upper()}] {f['title']}")
        L.append("")
        L.append(f["detail"])
        if f.get("action"):
            L.append(f"\n**Action:** {f['action']}")
        if f.get("reference"):
            L.append(f"\n_Reference: {f['reference']}_")
        L.append("")

    L += ["## Documents to gather", ""]
    L += [f"- [ ] {r}" for r in document_requests(a)]
    L += ["", "## Assumptions", "",
          "- Federal income tax and self-employment tax only; no state tax.",
          "- Standard deduction; no credits, capital gains, AMT, retirement or health-insurance deductions.",
          "- Recurring categories are projected at the year-to-date daily pace; one-off items are not projected.",
          "- This is a planning estimate for review by a tax professional, not a filed return or tax advice.", ""]
    return "\n".join(L)


def ledger_csv(a: dict) -> str:
    buf = io.StringIO()
    cols = ["id", "date", "source", "counterparty", "description", "amount", "fee", "category_label",
            "kind", "business_use_pct", "deductible_amount", "rule", "note"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for t in a["transactions"]:
        w.writerow(t)
    return buf.getvalue()
