"""Tax math checked against hand calculations."""

from datetime import date

import pytest

from creator_books import tax as tx
from creator_books.tax_tables import get_year


def test_bracket_tax_2026_single():
    # 12,400 * 10% + (50,400 - 12,400) * 12% + (60,000 - 50,400) * 22%
    expected = 1_240 + 4_560 + 2_112
    assert tx.bracket_tax(60_000, get_year(2026).brackets["single"]) == pytest.approx(expected)


def test_se_tax_basic():
    se = tx.se_tax(50_000, 0, get_year(2026), "single")
    ne = 50_000 * 0.9235
    assert se.net_earnings == pytest.approx(ne, abs=0.01)
    assert se.total == pytest.approx(ne * 0.153, abs=0.01)
    assert se.deductible_half == pytest.approx(ne * 0.153 / 2, abs=0.01)
    assert se.additional_medicare == 0


def test_se_tax_under_400_is_zero():
    assert tx.se_tax(400, 0, get_year(2026), "single").total == 0


def test_se_tax_wage_base_shared_with_w2():
    ty = get_year(2026)
    se = tx.se_tax(100_000, 150_000, ty, "single")
    ss_room = ty.ss_wage_base - 150_000  # 34,500
    assert se.social_security == pytest.approx(0.124 * ss_room, abs=0.01)
    # additional Medicare on SE earnings above the $200k threshold less wages
    ne = 100_000 * 0.9235
    assert se.additional_medicare == pytest.approx(0.009 * (ne - 50_000), abs=0.01)


def test_full_compute_matches_hand_calc():
    s = tx.compute(2026, "single", gross_receipts=60_000, total_expenses=10_000)
    ne = 50_000 * 0.9235
    se_total = ne * 0.153
    half = se_total / 2
    agi = 50_000 - half
    tbq = agi - 16_100
    qbi = min(0.2 * (50_000 - half), 0.2 * tbq)
    taxable = tbq - qbi
    inc = tx.bracket_tax(taxable, get_year(2026).brackets["single"])
    assert s.qbi.deduction == pytest.approx(qbi, abs=0.01)
    assert s.income_tax == pytest.approx(inc, abs=0.01)
    assert s.total_tax == pytest.approx(inc + se_total, abs=0.02)


def test_qbi_minimum_400_in_2026_not_2025():
    # tiny profit: 20% cap on taxable income would give less than $400
    q26 = tx.qbi_deduction(1_500, 1_000, get_year(2026), "single")
    assert q26.deduction == 400
    q25 = tx.qbi_deduction(1_500, 1_000, get_year(2025), "single")
    assert q25.deduction == 200


def test_qbi_sstb_fully_phased_out_above_range():
    ty = get_year(2026)
    top = ty.qbi_threshold["single"] + ty.qbi_phase_range["single"] + 1
    q = tx.qbi_deduction(300_000, top, ty, "single", sstb_share=1.0)
    assert q.deduction == 0


def test_qbi_non_sstb_no_wages_phases_linearly():
    ty = get_year(2026)
    mid = ty.qbi_threshold["single"] + ty.qbi_phase_range["single"] / 2
    q = tx.qbi_deduction(100_000, mid, ty, "single")
    assert q.deduction == pytest.approx(0.2 * 100_000 * 0.5, abs=0.01)


def test_safe_harbor_prior_year_110_percent():
    req, basis = tx.required_annual_payment(20_000, 10_000, 200_000, "single")
    assert req == 11_000 and "110%" in basis
    req, _ = tx.required_annual_payment(8_000, 10_000, 50_000, "single")
    assert req == pytest.approx(7_200)


def test_quarterly_schedule_statuses():
    rows = tx.quarterly_schedule(2026, 4_000, 0, [(date(2026, 4, 10), 1_000)], as_of=date(2026, 9, 27))
    assert [r["status"] for r in rows] == ["ok", "short", "short", "future"]
    assert rows[2]["shortfall"] == 2_000


def test_s_corp_not_worth_it_at_low_profit():
    s = tx.s_corp_screen(2026, "single", 20_000, 0)
    assert s["savings"] < 0
    s_big = tx.s_corp_screen(2026, "single", 150_000, 0)
    assert s_big["savings"] > 0
