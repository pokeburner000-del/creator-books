"""Federal tax math for a sole proprietor: SE tax, QBI, income tax, safe harbor, S-corp screen.

Simplifications (stated in every packet): federal only; ordinary income only (no
capital gains, credits, or AMT); standard deduction; one business; no self-employed
health insurance or retirement deductions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import tax_tables as T


def r2(x: float) -> float:
    return round(x + 0.0, 2)


def bracket_tax(taxable: float, brackets: list[tuple[float, float]]) -> float:
    tax, lower = 0.0, 0.0
    for upper, rate in brackets:
        if taxable <= lower:
            break
        tax += (min(taxable, upper) - lower) * rate
        lower = upper
    return tax


def marginal_rate(taxable: float, brackets: list[tuple[float, float]]) -> float:
    for upper, rate in brackets:
        if taxable <= upper:
            return rate
    return brackets[-1][1]


@dataclass
class SETax:
    net_earnings: float
    social_security: float
    medicare: float
    additional_medicare: float
    total: float  # SE tax proper (SS + Medicare), Schedule SE
    deductible_half: float


def se_tax(net_profit: float, w2_wages: float, ty: T.TaxYear, status: str) -> SETax:
    ne = max(0.0, net_profit) * T.SE_NET_EARNINGS_FACTOR
    if ne < T.SE_MINIMUM:
        return SETax(r2(ne), 0, 0, 0, 0, 0)
    ss_room = max(0.0, ty.ss_wage_base - w2_wages)
    ss = T.SS_RATE * min(ne, ss_room)
    med = T.MEDICARE_RATE * ne
    thresh_room = max(0.0, ty.addl_medicare_threshold[status] - w2_wages)
    addl = T.ADDL_MEDICARE_RATE * max(0.0, ne - thresh_room)
    total = ss + med
    return SETax(r2(ne), r2(ss), r2(med), r2(addl), r2(total), r2(total / 2))


@dataclass
class QBIResult:
    qbi: float
    deduction: float
    method: str
    note: str


def qbi_deduction(qbi: float, taxable_before_qbi: float, ty: T.TaxYear, status: str,
                  sstb_share: float = 0.0, w2_wages_paid: float = 0.0) -> QBIResult:
    """Section 199A for one sole proprietorship with no W-2 employees or UBIA by default.

    sstb_share: fraction of QBI that is specified-service income (e.g. endorsement fees).
    """
    if qbi <= 0:
        return QBIResult(r2(qbi), 0.0, "none", "No positive qualified business income.")
    threshold = ty.qbi_threshold[status]
    phase = ty.qbi_phase_range[status]
    overall_cap = T.QBI_RATE * max(0.0, taxable_before_qbi)
    tentative = T.QBI_RATE * qbi

    if taxable_before_qbi <= threshold:
        ded = min(tentative, overall_cap)
        method, note = "simplified (Form 8995)", "Taxable income is under the threshold, so no wage or SSTB limits apply."
    else:
        excess = min(1.0, (taxable_before_qbi - threshold) / phase)
        # SSTB portion shrinks to zero across the phase-in range
        applicable = 1.0 - excess
        non_sstb = qbi * (1 - sstb_share)
        sstb = qbi * sstb_share * applicable
        comp = 0.0
        for part, wages in ((non_sstb, w2_wages_paid * (1 - sstb_share)), (sstb, w2_wages_paid * sstb_share * applicable)):
            if part <= 0:
                continue
            full = T.QBI_RATE * part
            wage_limit = 0.5 * wages
            if full > wage_limit:
                comp += full - (full - wage_limit) * excess
            else:
                comp += full
        ded = min(comp, overall_cap)
        method = "limited (Form 8995-A)"
        note = (f"Taxable income is {excess:.0%} of the way through the phase-in range, "
                "so the W-2 wage limit (and SSTB rule, if any) reduce the deduction.")

    if ty.qbi_minimum and qbi >= ty.qbi_minimum_floor and sstb_share < 1.0 and ded < ty.qbi_minimum:
        ded = ty.qbi_minimum
        method += " + $400 minimum"
        note += " The OBBBA $400 minimum deduction applies (assumes material participation)."
    return QBIResult(r2(qbi), r2(ded), method, note)


@dataclass
class TaxSummary:
    tax_year: int
    filing_status: str
    gross_receipts: float
    total_expenses: float
    net_profit: float
    se: SETax
    w2_wages: float
    other_income: float
    agi: float
    standard_deduction: float
    taxable_before_qbi: float
    qbi: QBIResult
    taxable_income: float
    income_tax: float
    marginal_rate: float
    total_tax: float
    withholding: float
    balance_after_withholding: float
    effective_rate_on_profit: float

    def to_dict(self) -> dict:
        return asdict(self)


def compute(tax_year: int, status: str, gross_receipts: float, total_expenses: float,
            w2_wages: float = 0.0, other_income: float = 0.0, withholding: float = 0.0,
            sstb_share: float = 0.0) -> TaxSummary:
    ty = T.get_year(tax_year)
    if status not in ty.standard_deduction:
        raise ValueError("filing_status must be 'single' or 'mfj'")
    profit = gross_receipts - total_expenses
    se = se_tax(profit, w2_wages, ty, status)
    agi = w2_wages + other_income + profit - se.deductible_half
    std = ty.standard_deduction[status]
    tbq = max(0.0, agi - std)
    qbi_amount = profit - se.deductible_half
    q = qbi_deduction(qbi_amount, tbq, ty, status, sstb_share)
    taxable = max(0.0, tbq - q.deduction)
    inc_tax = bracket_tax(taxable, ty.brackets[status])
    total = inc_tax + se.total + se.additional_medicare
    return TaxSummary(
        tax_year=tax_year, filing_status=status,
        gross_receipts=r2(gross_receipts), total_expenses=r2(total_expenses), net_profit=r2(profit),
        se=se, w2_wages=r2(w2_wages), other_income=r2(other_income), agi=r2(agi),
        standard_deduction=std, taxable_before_qbi=r2(tbq), qbi=q, taxable_income=r2(taxable),
        income_tax=r2(inc_tax), marginal_rate=marginal_rate(taxable, ty.brackets[status]),
        total_tax=r2(total), withholding=r2(withholding),
        balance_after_withholding=r2(total - withholding),
        effective_rate_on_profit=r2(total / profit) if profit > 0 else 0.0,
    )


# ---------- estimated payments ----------

def required_annual_payment(current_total_tax: float, prior_total_tax: float | None,
                            prior_agi: float | None, status: str) -> tuple[float, str]:
    """IRC §6654(d): lesser of 90% of this year's tax or 100% (110% if prior AGI > $150k) of last year's."""
    ninety = 0.9 * current_total_tax
    if prior_total_tax is None:
        return r2(ninety), "90% of this year's projected tax (prior-year tax not provided)"
    mult = 1.10 if (prior_agi or 0) > T.SAFE_HARBOR_HIGH_AGI[status] else 1.00
    prior = prior_total_tax * mult
    if prior < ninety:
        return r2(prior), f"{int(mult*100)}% of last year's tax (smaller than 90% of this year's)"
    return r2(ninety), "90% of this year's projected tax (smaller than the prior-year amount)"


def quarterly_schedule(tax_year: int, required: float, withholding: float,
                       payments: list[tuple], as_of=None) -> list[dict]:
    """Cumulative required vs. paid at each due date. payments: [(date, amount)]."""
    ty = T.get_year(tax_year)
    rows = []
    for i, due in enumerate(ty.estimate_due_dates, start=1):
        req_cum = required * i / 4
        paid_cum = withholding * i / 4 + sum(a for d, a in payments if d <= due)
        paid_this = sum(a for d, a in payments
                        if d <= due and (i == 1 or d > ty.estimate_due_dates[i - 2]))
        status = "future" if as_of and due > as_of else ("ok" if paid_cum + 0.5 >= req_cum else "short")
        rows.append({
            "quarter": f"Q{i}", "due": due.isoformat(), "installment": r2(required / 4),
            "paid_this_period": r2(paid_this), "required_to_date": r2(req_cum),
            "paid_to_date": r2(paid_cum), "shortfall": r2(max(0.0, req_cum - paid_cum)),
            "status": status,
        })
    return rows


# ---------- S-corp screen ----------

def s_corp_screen(tax_year: int, status: str, gross_receipts: float, total_expenses: float,
                  salary_pct: float = 0.40, admin_cost: float = 2_500.0,
                  w2_wages: float = 0.0, other_income: float = 0.0) -> dict:
    """Rough federal comparison of a sole proprietorship vs. an S-corp paying a salary.

    Ignores state franchise taxes, unemployment taxes, and the reasonable-compensation
    facts and circumstances test. It is a screen, not advice.
    """
    ty = T.get_year(tax_year)
    sole = compute(tax_year, status, gross_receipts, total_expenses, w2_wages, other_income)
    profit = gross_receipts - total_expenses
    if profit <= 0:
        return {"sole_prop_total": sole.total_tax, "s_corp_total": None, "savings": 0.0,
                "salary": 0.0, "verdict": "No profit, so an S-corp can't save payroll tax.", "break_even_profit": None}

    salary = profit * salary_pct
    # FICA on salary, both halves (employer half is a business deduction)
    ss_room = max(0.0, ty.ss_wage_base - w2_wages)
    ss = 0.062 * min(salary, ss_room)
    med = 0.0145 * salary
    employer_fica = ss + med
    employee_fica = ss + med
    addl = T.ADDL_MEDICARE_RATE * max(0.0, salary + w2_wages - ty.addl_medicare_threshold[status])
    k1 = profit - salary - employer_fica - admin_cost
    agi = w2_wages + salary + other_income + k1
    std = ty.standard_deduction[status]
    tbq = max(0.0, agi - std)
    q = qbi_deduction(k1, tbq, ty, status, w2_wages_paid=salary)
    taxable = max(0.0, tbq - q.deduction)
    inc = bracket_tax(taxable, ty.brackets[status])
    s_total = inc + employer_fica + employee_fica + addl + admin_cost
    savings = sole.total_tax - s_total

    # search for the profit where savings cross zero (same salary %, same admin cost)
    break_even = None
    for p in range(5_000, 400_001, 1_000):
        a = s_corp_screen_quick(tax_year, status, p, salary_pct, admin_cost, w2_wages, other_income)
        if a > 0:
            break_even = p
            break

    if savings > 1_000:
        verdict = "Worth a conversation with a CPA: an S-corp could save meaningful federal tax at this profit."
    elif savings > 0:
        verdict = "Marginal: savings are small once payroll and extra filing costs are counted."
    else:
        verdict = "Not yet: payroll costs and the extra return outweigh the savings at this profit."
    return {
        "salary": r2(salary), "salary_pct": salary_pct, "admin_cost": admin_cost,
        "sole_prop_total": r2(sole.total_tax), "s_corp_total": r2(s_total),
        "s_corp_breakdown": {"income_tax": r2(inc), "payroll_tax": r2(employer_fica + employee_fica + addl),
                             "admin_cost": admin_cost, "qbi_deduction": q.deduction},
        "savings": r2(savings), "break_even_profit": break_even, "verdict": verdict,
    }


def s_corp_screen_quick(tax_year, status, profit, salary_pct, admin_cost, w2_wages, other_income) -> float:
    ty = T.get_year(tax_year)
    sole = compute(tax_year, status, profit, 0.0, w2_wages, other_income).total_tax
    salary = profit * salary_pct
    ss = 0.062 * min(salary, max(0.0, ty.ss_wage_base - w2_wages))
    fica = 2 * (ss + 0.0145 * salary)
    k1 = profit - salary - fica / 2 - admin_cost
    agi = w2_wages + salary + other_income + k1
    tbq = max(0.0, agi - ty.standard_deduction[status])
    q = qbi_deduction(k1, tbq, ty, status, w2_wages_paid=salary)
    inc = bracket_tax(max(0.0, tbq - q.deduction), ty.brackets[status])
    return sole - (inc + fica + admin_cost)
