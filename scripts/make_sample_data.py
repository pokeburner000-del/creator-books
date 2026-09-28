"""Generate the synthetic 'Maya Torres' creator data sets.

Maya is a fictional gaming and trading-card creator. Two data sets are written:

  sample_data/maya_2025/  full year, with 1099s (year-end review)
  sample_data/maya_2026/  Jan 1 to Sep 27, 2026, no 1099s yet (mid-year planning)

Every issue the review engine should catch is planted on purpose and listed in
_PLANTED_ISSUES.md inside each folder. Output is deterministic (fixed seed).

Run:  python scripts/make_sample_data.py
"""

from __future__ import annotations

import calendar
import csv
import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PRODUCTS = [
    ("Gamer Gear Hub", "RGB mechanical keyboard"), ("Gamer Gear Hub", "Wireless gaming mouse"),
    ("CardVault Supply", "Toploaders 100-pack"), ("CardVault Supply", "9-pocket binder"),
    ("CardVault Supply", "Magnetic one-touch holders"), ("Pixel Peripherals", "Retro handheld console"),
    ("Pixel Peripherals", "Controller charging dock"), ("Snack Attack Co", "Anime snack box"),
    ("Pixel Peripherals", "LED desk light bar"), ("Gamer Gear Hub", "Headset stand"),
]


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def month_days(year: int, month: int, through: date) -> range:
    last = calendar.monthrange(year, month)[1]
    if date(year, month, 1) > through:
        return range(0)
    if year == through.year and month == through.month:
        last = through.day
    return range(1, last + 1)


def build(year: int, through: date, scale: float, out: Path, seed: int, cfg: dict) -> dict:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    months = [m for m in range(1, 13) if date(year, m, 1) <= through]

    # ---- TikTok Shop affiliate ----
    rows, oid = [], 700000 + year
    refunds = 0.0
    for m in months:
        days = list(month_days(year, m, through))
        n = int((55 + 5 * m) * scale * (len(days) / calendar.monthrange(year, m)[1]))
        for _ in range(n):
            shop, prod = rng.choice(PRODUCTS)
            comm = round(rng.uniform(14, 52), 2)
            status = "Settled"
            if rng.random() < 0.05:
                status, refunds = "Refunded", refunds + comm
            oid += 1
            rows.append([f"{oid}", date(year, m, rng.choice(days)).isoformat(), prod, shop,
                         f"{rng.choice([8, 10, 12, 15])}%", f"{comm:.2f}", status])
    rows.sort(key=lambda r: r[1])
    write_csv(out / "tiktok_shop_affiliate.csv",
              ["Order ID", "Settlement Date", "Product Name", "Shop Name", "Commission Rate", "Settled Commission", "Status"], rows)

    # ---- TikTok Creator Rewards (monthly) and YouTube AdSense (monthly) ----
    full_months = [m for m in months if date(year, m, calendar.monthrange(year, m)[1]) <= through]
    write_csv(out / "tiktok_creator_rewards.csv", ["Month", "Program", "Estimated Rewards (USD)"],
              [[f"{year}-{m:02d}", "Creator Rewards Program", f"{rng.uniform(280, 520) * scale:.2f}"] for m in full_months])
    write_csv(out / "youtube_adsense.csv", ["Month", "Channel", "Estimated Revenue (USD)", "Payment Date"],
              [[f"{year}-{m:02d}", "Maya Plays", f"{rng.uniform(520, 880) * scale:.2f}",
                date(year + (m == 12), m % 12 + 1, 21).isoformat()] for m in full_months])

    # ---- PayPal ----
    pp = []
    tid = 1000
    def pp_row(d, name, typ, gross, fee, note):
        nonlocal tid
        tid += 1
        net = gross - fee if gross > 0 else gross
        pp.append([d, name, typ, "Completed", "USD", f"{gross:.2f}", f"{-fee:.2f}" if fee else "0.00", f"{net:.2f}", f"PP{year}{tid}", note])
    for d, name, gross, note in cfg["brand_deals"]:
        pp_row(d, name, "Payment Received", gross, round(gross * 0.0349 + 0.49, 2), note)
    for d, name, gross, note in cfg["personal_in"]:
        pp_row(d, name, "Payment Received", gross, 0.0, note)
    for m in months:
        if m in cfg["editor_months"]:
            pp_row(date(year, m, min(28, through.day if m == through.month else 28)).isoformat(),
                   cfg["editor"], "Payment Sent", -cfg["editor_rate"], 0.0, "video edit")
        pp_row(date(year, m, 1 if m == through.month else 25).isoformat(), "Bank of America", "Transfer to Bank",
               -round(rng.uniform(900, 1800), 2), 0.0, "")
    for d, name, gross, note in cfg.get("extra_paypal", []):
        pp_row(d, name, "Payment Sent" if gross < 0 else "Payment Received", gross, 0.0, note)
    pp.sort(key=lambda r: r[0])
    write_csv(out / "paypal_activity.csv",
              ["Date", "Name", "Type", "Status", "Currency", "Gross", "Fee", "Net", "Transaction ID", "Note"], pp)

    # ---- Expenses (card / bank export, annotated) ----
    ex = []
    for m in months:
        d = lambda day: date(year, m, min(day, max(month_days(year, m, through)))).isoformat()
        ex += [[d(3), "Adobe", "Creative Cloud subscription", "59.99", "", ""],
               [d(5), "CapCut", "CapCut Pro", "9.99", "", ""],
               [d(8), "Verizon", "Phone bill", "85.00", "50", ""],
               [d(12), "Spectrum", "Home internet", "70.00", "", ""],
               [d(14), "Netflix", "Streaming", "15.49", "", ""],
               [d(15), "Spotify", "Music subscription", "11.99", "", ""],
               [d(rng.randint(1, 27)), "TCGplayer", "Booster boxes for pack opening videos", f"{rng.uniform(140, 260) * scale:.2f}", "", ""],
               [d(rng.randint(1, 27)), "Starbucks", "Coffee", f"{rng.uniform(5, 8):.2f}", "", ""]]
        if m % 2 == 0:
            ex.append([d(rng.randint(1, 27)), "Pokemon Center", "Elite Trainer Box for opening video", "54.99", "", ""])
    ex += cfg["one_off_expenses"]
    ex.sort(key=lambda r: r[0])
    write_csv(out / "expenses.csv", ["Date", "Merchant", "Description", "Amount", "Business Use %", "Notes"], ex)

    # ---- Gifted products ----
    write_csv(out / "gifted_products.csv",
              ["Date Received", "Brand", "Item", "Estimated FMV", "Status", "Featured in Content"], cfg["gifted"])

    # ---- Estimated payments, 1099s, profile ----
    write_csv(out / "estimated_payments.csv", ["Date", "Amount", "Type"],
              [[d, f"{a:.2f}", "Federal estimated tax"] for d, a in cfg["estimates"]])
    with open(out / "profile.json", "w", encoding="utf-8") as fh:
        json.dump(cfg["profile"], fh, indent=2)
    (out / "_PLANTED_ISSUES.md").write_text(cfg["planted"], encoding="utf-8")
    return {"refunds": refunds}


def maya_2025(out: Path) -> None:
    y = 2025
    cfg = {
        "brand_deals": [("2025-10-06", "Pixel Forge Games LLC", 1200.00, "Sponsored integration - October")],
        "personal_in": [("2025-07-04", "Jordan Lee", 45.00, "pizza split")],
        "editor": "Alex Chen", "editor_rate": 150.00, "editor_months": [7, 8, 9, 10, 11, 12],
        "one_off_expenses": [
            ["2025-03-02", "Amazon", "Shure MV7 microphone", "249.00", "", ""],
            ["2025-03-02", "Amazon", "Ring light and tripod", "62.40", "", ""],
            ["2025-04-14", "IRS", "IRS Direct Pay estimated tax", "500.00", "", ""],
            ["2025-06-13", "IRS", "IRS Direct Pay estimated tax", "500.00", "", ""],
            ["2025-11-20", "Chipotle", "Lunch w/ Alex (editor) - planning Q1 series", "31.20", "", ""],
        ],
        "gifted": [
            ["2025-09-10", "HyperWave Audio", "HW-3 gaming headset", "129.99", "Kept", "Y"],
            ["2025-11-02", "Glowdesk", "LED strip kit", "39.99", "Returned", "N"],
        ],
        "estimates": [("2025-04-14", 500.00), ("2025-06-13", 500.00)],
        "profile": {"name": "Maya Torres (sample)", "tax_year": 2025, "filing_status": "single",
                    "w2_wages": 0, "withholding": 0, "other_income": 0,
                    "prior_year_total_tax": 2100, "prior_year_agi": 21000,
                    "home_office_sqft": 110, "years_with_losses": 0},
        "planted": "",
    }
    info = build(y, date(2025, 12, 31), 0.6, out, seed=25, cfg=cfg)

    # 1099s: TikTok reports commissions BEFORE refunds (planted mismatch); Google ties;
    # Pixel Forge ties; the $45 personal payment gets no form.
    from creator_books.importers import load_dir
    ds = load_dir(str(out))
    tiktok = sum(t.amount for t in ds.transactions if t.source in ("tiktok_shop", "tiktok_rewards"))
    google = sum(t.amount for t in ds.transactions if t.source == "youtube")
    write_csv(out / "forms_1099.csv", ["Form", "Payer", "Box", "Amount"], [
        ["1099-NEC", "TikTok Inc.", "1", f"{tiktok + info['refunds']:.2f}"],
        ["1099-MISC", "Google LLC", "3", f"{google:.2f}"],
        ["1099-NEC", "Pixel Forge Games LLC", "1", "1200.00"],
    ])
    (out / "_PLANTED_ISSUES.md").write_text(f"""# Planted issues: Maya 2025 (full year)

1. **TikTok 1099-NEC is higher than the books** by ${info['refunds']:,.2f}: the form reports commissions before
   refunds; the books net refunded orders. Expect a 1099 mismatch flag.
2. **Gifted headset** ($129.99) kept and featured: taxable at fair market value. A returned LED strip is not income.
3. **Editor Alex Chen** paid $900 (6 x $150) through PayPal: over the $600 1099-NEC threshold for 2025.
4. **Spectrum internet** has no business-use %: mixed-use flag, held at $0.
5. **Estimated payments** stopped after Q2: underpayment flag.
6. **IRS payments** appear in the expense export: excluded from expenses, matched to the estimates file.
7. **Jordan Lee $45 "pizza split"** is personal, not income.
8. Netflix and Spotify are personal and excluded.
""", encoding="utf-8")


def maya_2026(out: Path, prior_tax: float, prior_agi: float) -> None:
    y, through = 2026, date(2026, 9, 27)
    cfg = {
        "brand_deals": [
            ("2026-02-14", "Pixel Forge Games LLC", 3500.00, "Sponsored integration - Feb"),
            ("2026-05-03", "Kitsune Snacks", 1500.00, "Campaign - 2 TikToks"),
            ("2026-07-20", "Pixel Forge Games LLC", 2000.00, "Summer launch video"),
        ],
        "personal_in": [
            ("2026-03-09", "Jordan Lee", 60.00, "concert tix"),
            ("2026-06-11", "Sam Rivera", 400.00, ""),
            ("2026-08-02", "Diana Torres", 200.00, "happy birthday!"),
        ],
        "editor": "Alex Chen", "editor_rate": 250.00, "editor_months": list(range(1, 10)),
        "extra_paypal": [("2026-04-18", "Alex Chen", -300.00, "thumbnail pack")],
        "one_off_expenses": [
            ["2026-01-18", "Best Buy", "Gaming PC build (RTX 5080)", "2849.99", "", ""],
            ["2026-02-07", "Apple Store", "iPhone 17 Pro", "1199.00", "60", ""],
            ["2026-02-07", "Amazon", "Shure MV7+ microphone", "279.00", "", ""],
            ["2026-02-07", "Amazon", "Elgato Key Light", "199.99", "", ""],
            ["2026-03-21", "TCGplayer", "Chase cards from opening - kept, PSA submission", "340.00", "", "personal collection"],
            ["2026-04-02", "PSA", "PSA grading fees (5 cards)", "125.00", "", "personal collection"],
            ["2026-04-14", "IRS", "IRS Direct Pay estimated tax", "1200.00", "", ""],
            ["2026-06-12", "IRS", "IRS Direct Pay estimated tax", "1200.00", "", ""],
            ["2026-05-09", "Steam", "Game for Let's Play series", "59.99", "", ""],
            ["2026-08-14", "Steam", "Game for stream", "69.99", "", ""],
            ["2026-06-19", "Southwest", "Flight to VidCon", "312.40", "", ""],
            ["2026-06-19", "Marriott", "Hotel - VidCon (2 nights)", "486.22", "", ""],
            ["2026-05-22", "Chipotle", "Lunch w/ Alex (editor) - planning summer series", "28.40", "", ""],
            ["2026-03-30", "USPS", "Shipping giveaway prizes", "18.50", "", ""],
            ["2026-05-12", "USPS", "Shipping giveaway prizes", "22.75", "", ""],
            ["2026-07-03", "SQ *RETRO RELICS", "misc", "120.00", "", ""],
            ["2026-08-29", "Staples", "Desk chair for editing setup", "229.00", "", ""],
            ["2026-09-02", "Epidemic Sound", "Music licensing (annual)", "179.88", "", ""],
        ],
        "gifted": [
            ["2026-02-02", "HyperWave Audio", "HW-5 Pro wireless headset", "249.99", "Kept", "Y"],
            ["2026-03-15", "ProPad", "Elite controller", "69.99", "Kept", "Y"],
            ["2026-04-22", "Kitsune Snacks", "Snack variety box", "45.00", "Given away", "Y"],
            ["2026-07-08", "Glowdesk", "LED strip kit v2", "39.99", "Returned", "N"],
            ["2026-08-19", "Pixel Forge Games", "Early-access merch bundle (hoodie, pins)", "85.00", "Kept", "Y"],
        ],
        "estimates": [("2026-04-14", 1200.00)],
        "profile": {"name": "Maya Torres (sample)", "tax_year": 2026, "filing_status": "single",
                    "w2_wages": 0, "withholding": 0, "other_income": 0,
                    "prior_year_total_tax": round(prior_tax, 2), "prior_year_agi": round(prior_agi, 2),
                    "home_office_sqft": 110, "years_with_losses": 0},
        "planted": """# Planted issues: Maya 2026 (Jan 1 - Sep 27)

1. **Sam Rivera $400**, no note: actually a paid shoutout. Should show as an unclassified inflow.
2. **Kitsune Snacks $1,500**: brand deal from a payer without "LLC/Inc" in its name, below the $2,000
   1099-NEC threshold, so no 1099 will come. Caught by the note ("campaign"), marked low confidence.
3. **Gifted products**: headset, controller, merch kept = income at FMV; snack box given away (review);
   LED strip returned = not income.
4. **Gaming PC ($2,849.99)**: no business-use %, and over the $2,500 de minimis limit.
5. **Spectrum internet**: no business-use %. Verizon (50%) and iPhone (60%) have one.
6. **Cards kept for a personal collection** and **PSA grading fees**: personal, not content costs.
7. **Editor Alex Chen**: $2,550 so far via PayPal, over the 2026 $2,000 1099-NEC threshold.
8. **Estimated payments**: estimates file only shows April; the June IRS payment is in the bank export
   but not the estimates file. Q3 (Sep 15) was skipped. Expect short + unrecorded-payment flags.
9. **SQ *RETRO RELICS $120 "misc"**: unclassified expense.
10. Steam games and a Staples chair: classified with low confidence.
11. Netflix and Spotify: personal. Jordan Lee and Diana Torres payments: personal transfers.
12. Refunded TikTok Shop orders are netted against commissions.
""",
    }
    build(y, through, 1.0, out, seed=26, cfg=cfg)


if __name__ == "__main__":
    from creator_books.engine import analyze
    from creator_books.importers import load_dir

    base = ROOT / "sample_data"
    maya_2025(base / "maya_2025")
    a25 = analyze(load_dir(str(base / "maya_2025")))
    maya_2026(base / "maya_2026", a25["tax"]["total_tax"], a25["tax"]["agi"])
    print(f"2025: profit {a25['tax']['net_profit']:,.0f}, total tax {a25['tax']['total_tax']:,.0f}")
    a26 = analyze(load_dir(str(base / "maya_2026")))
    print(f"2026: projected profit {a26['tax']['net_profit']:,.0f}, total tax {a26['tax']['total_tax']:,.0f}")
