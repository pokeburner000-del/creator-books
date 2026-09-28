"""Federal tax parameters by tax year.

Sources:
- 2026: IRS IR-2025-103 / Rev. Proc. 2025-32 (brackets, standard deduction, §199A
  thresholds); SSA 2026 contribution and benefit base ($184,500); OBBBA (P.L. 119-21)
  §70105 (QBI permanent, $75k/$150k phase-in, $400 minimum) and §§70432-70433
  (1099-K $20,000 / 200 transactions; 1099-NEC/MISC $2,000).
- 2025: Rev. Proc. 2024-40 as amended by OBBBA (standard deduction $15,750 single).

Only single and married-filing-jointly are supported. Update this file each year.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

INF = float("inf")


@dataclass(frozen=True)
class TaxYear:
    year: int
    standard_deduction: dict[str, float]
    brackets: dict[str, list[tuple[float, float]]]  # (upper bound, rate)
    ss_wage_base: float
    addl_medicare_threshold: dict[str, float]
    qbi_threshold: dict[str, float]
    qbi_phase_range: dict[str, float]
    qbi_minimum: float  # 0 when the minimum deduction does not apply
    qbi_minimum_floor: float  # QBI needed to claim the minimum
    nec_threshold: float
    k_threshold_amount: float
    k_threshold_count: int
    estimate_due_dates: tuple[date, date, date, date]


TAX_YEARS: dict[int, TaxYear] = {
    2025: TaxYear(
        year=2025,
        standard_deduction={"single": 15_750, "mfj": 31_500},
        brackets={
            "single": [(11_925, 0.10), (48_475, 0.12), (103_350, 0.22), (197_300, 0.24),
                       (250_525, 0.32), (626_350, 0.35), (INF, 0.37)],
            "mfj": [(23_850, 0.10), (96_950, 0.12), (206_700, 0.22), (394_600, 0.24),
                    (501_050, 0.32), (751_600, 0.35), (INF, 0.37)],
        },
        ss_wage_base=176_100,
        addl_medicare_threshold={"single": 200_000, "mfj": 250_000},
        qbi_threshold={"single": 197_300, "mfj": 394_600},
        qbi_phase_range={"single": 50_000, "mfj": 100_000},
        qbi_minimum=0,
        qbi_minimum_floor=0,
        nec_threshold=600,
        k_threshold_amount=20_000,
        k_threshold_count=200,
        estimate_due_dates=(date(2025, 4, 15), date(2025, 6, 16), date(2025, 9, 15), date(2026, 1, 15)),
    ),
    2026: TaxYear(
        year=2026,
        standard_deduction={"single": 16_100, "mfj": 32_200},
        brackets={
            "single": [(12_400, 0.10), (50_400, 0.12), (105_700, 0.22), (201_775, 0.24),
                       (256_225, 0.32), (640_600, 0.35), (INF, 0.37)],
            "mfj": [(24_800, 0.10), (100_800, 0.12), (211_400, 0.22), (403_550, 0.24),
                    (512_450, 0.32), (768_700, 0.35), (INF, 0.37)],
        },
        ss_wage_base=184_500,
        addl_medicare_threshold={"single": 200_000, "mfj": 250_000},
        qbi_threshold={"single": 201_750, "mfj": 403_500},
        qbi_phase_range={"single": 75_000, "mfj": 150_000},
        qbi_minimum=400,
        qbi_minimum_floor=1_000,
        nec_threshold=2_000,
        k_threshold_amount=20_000,
        k_threshold_count=200,
        estimate_due_dates=(date(2026, 4, 15), date(2026, 6, 15), date(2026, 9, 15), date(2027, 1, 15)),
    ),
}

SE_NET_EARNINGS_FACTOR = 0.9235
SS_RATE = 0.124
MEDICARE_RATE = 0.029
ADDL_MEDICARE_RATE = 0.009
SE_MINIMUM = 400
QBI_RATE = 0.20
MEALS_DEDUCTIBLE = 0.50
HOME_OFFICE_RATE = 5.0  # simplified method, Rev. Proc. 2013-13
HOME_OFFICE_MAX_SQFT = 300
SAFE_HARBOR_HIGH_AGI = {"single": 150_000, "mfj": 150_000}
PENALTY_DE_MINIMIS = 1_000


def get_year(year: int) -> TaxYear:
    if year not in TAX_YEARS:
        raise ValueError(f"No tax tables for {year}. Supported: {sorted(TAX_YEARS)}")
    return TAX_YEARS[year]
