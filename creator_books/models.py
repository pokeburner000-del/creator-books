"""Core data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


# Category metadata: kind is income / expense / excluded.
# recurring = extrapolated when projecting the rest of an in-progress year.
CATEGORIES: dict[str, dict] = {
    # income
    "affiliate_commission": {"kind": "income", "label": "Affiliate commissions", "recurring": True},
    "ad_revenue": {"kind": "income", "label": "Ad revenue (AdSense)", "recurring": True},
    "platform_bonus": {"kind": "income", "label": "Creator rewards / platform bonuses", "recurring": True},
    "sponsorship": {"kind": "income", "label": "Sponsorships and brand deals", "recurring": False},
    "gifted_product": {"kind": "income", "label": "Gifted products (fair market value)", "recurring": False},
    "other_income": {"kind": "income", "label": "Other business income", "recurring": False},
    # expenses (Schedule C)
    "equipment": {"kind": "expense", "label": "Equipment (cameras, PCs, mics)", "recurring": False, "sched_c": "Line 13 / 22 (depreciation or de minimis)"},
    "software": {"kind": "expense", "label": "Software and subscriptions", "recurring": True, "sched_c": "Line 18 / 27a"},
    "content_inventory": {"kind": "expense", "label": "Content props (cards, games, merch for videos)", "recurring": True, "sched_c": "Line 22 supplies"},
    "phone_internet": {"kind": "expense", "label": "Phone and internet (business share)", "recurring": True, "sched_c": "Line 25 utilities"},
    "contractor": {"kind": "expense", "label": "Contract labor (editors, thumbnail artists)", "recurring": True, "sched_c": "Line 11"},
    "platform_fees": {"kind": "expense", "label": "Payment and platform fees", "recurring": True, "sched_c": "Line 10 / 27a"},
    "meals": {"kind": "expense", "label": "Business meals (50%)", "recurring": True, "sched_c": "Line 24b"},
    "travel": {"kind": "expense", "label": "Travel", "recurring": False, "sched_c": "Line 24a"},
    "advertising": {"kind": "expense", "label": "Advertising and promotion", "recurring": True, "sched_c": "Line 8"},
    "shipping": {"kind": "expense", "label": "Shipping and postage", "recurring": True, "sched_c": "Line 27a"},
    "office": {"kind": "expense", "label": "Office supplies and furniture", "recurring": False, "sched_c": "Line 18"},
    "gifted_product_use": {"kind": "expense", "label": "Gifted products used in the business", "recurring": False, "sched_c": "Line 22 / 13"},
    # excluded
    "personal": {"kind": "excluded", "label": "Personal (not deductible)"},
    "personal_transfer": {"kind": "excluded", "label": "Personal transfers (not income)"},
    "returned_gift": {"kind": "excluded", "label": "Returned gifted product (not income)"},
    "owner_transfer": {"kind": "excluded", "label": "Transfers between own accounts"},
    "tax_payment": {"kind": "excluded", "label": "Tax payments"},
    "needs_review": {"kind": "excluded", "label": "Needs review"},
}


def category_kind(cat: str) -> str:
    return CATEGORIES.get(cat, {}).get("kind", "excluded")


@dataclass
class Transaction:
    id: str
    date: date
    source: str  # tiktok_shop, tiktok_rewards, youtube, paypal, expenses, gifted
    counterparty: str
    description: str
    amount: float  # signed: + inflow / income, - outflow / expense (gross, before fees)
    fee: float = 0.0  # fee withheld by the platform (positive number)
    category: str = "needs_review"
    business_use_pct: float | None = None  # 0-100; None = not provided
    rule: str = ""  # which rule classified it
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def deductible_amount(self) -> float:
        """Positive deductible amount for expense rows (after business-use and meal limits)."""
        if category_kind(self.category) != "expense" or self.amount >= 0:
            return 0.0
        if self.business_use_pct is None:
            # mixed-use items with no business-use % are held at zero until the client supplies one
            pct = 0.0 if self.extra.get("mixed_use") else 100.0
        else:
            pct = self.business_use_pct
        base = -self.amount * pct / 100.0
        if self.category == "meals":
            base *= 0.5
        return round(base, 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        d["kind"] = category_kind(self.category)
        d["category_label"] = CATEGORIES.get(self.category, {}).get("label", self.category)
        d["deductible_amount"] = self.deductible_amount
        return d


@dataclass
class Form1099:
    form: str  # 1099-NEC, 1099-MISC, 1099-K
    payer: str
    amount: float
    box: str = ""


@dataclass
class EstimatedPayment:
    date: date
    amount: float


@dataclass
class Profile:
    name: str = "Client"
    tax_year: int = 2026
    filing_status: str = "single"  # single | mfj
    w2_wages: float = 0.0  # expected full-year W-2 wages
    withholding: float = 0.0  # expected full-year federal withholding
    other_income: float = 0.0  # interest, etc. (ordinary)
    prior_year_total_tax: float | None = None
    prior_year_agi: float | None = None
    home_office_sqft: float = 0.0
    years_with_losses: int = 0  # prior years this activity showed a loss
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Flag:
    id: str
    severity: str  # high | medium | low | info
    title: str
    detail: str
    reference: str = ""
    amount: float | None = None
    txn_ids: list[str] = field(default_factory=list)
    action: str = ""  # what the client or preparer should do
    request: str = ""  # document to request from client, if any

    def to_dict(self) -> dict:
        return asdict(self)
