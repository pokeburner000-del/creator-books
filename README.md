# Creator Books

Tax and bookkeeping copilot for content creators. Drop in payout exports from TikTok Shop, YouTube,
PayPal, and your card statements. Creator Books sorts every line, flags what creators usually get
wrong, projects federal tax and quarterly payments, and builds a packet a preparer can work from.

Everything runs locally. Uploaded files are held in memory only and never leave your machine.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and load a sample creator, or upload your own files.

```bash
pytest                                # tax math + every planted issue in the samples
python scripts/make_sample_data.py    # regenerate the sample data sets
```

## What it does

1. **Classifies** every transaction with editable rules (`creator_books/rules.json`): affiliate
   commissions, ad revenue, sponsorships, gifted products, software, content props, contractors,
   mixed-use bills, personal items, and transfers. Anything it can't place is marked for review.
   You can recategorize or set a business-use % in the Ledger tab. A business % set on one bill
   applies to every other bill from that payee that doesn't have one yet.
2. **Reviews** the year against creator-specific rules, with a citation and an action for each flag:
   - 1099 reconciliation (form vs. books), or which 1099s to expect in January
   - gifted PR products as income at fair market value
   - mixed-use phones, computers, and internet with no business-use %
   - equipment over the $2,500 de minimis limit (Section 179 / bonus depreciation)
   - trading cards kept for a personal collection vs. opened for content
   - contractors you must send a 1099-NEC (and the PayPal/card exception)
   - unexplained incoming payments, personal transfers, 50% meals, home office, hobby-loss risk
   - QBI limits on endorsement income near the threshold
   - estimated payments behind the safe-harbor schedule
3. **Projects** federal tax: Schedule C profit, SE tax, QBI deduction (including the 2026 $400
   minimum), income tax, and the quarterly safe-harbor schedule. Mid-year, recurring income and
   expenses are projected to Dec 31 at the year-to-date pace. A what-if slider changes that pace.
4. **Screens an S-corp election** at an adjustable salary % and admin cost, with a break-even profit.
5. **Builds the packet**: snapshot, fix-first list, category totals mapped to Schedule C lines, tax
   walk, quarterly schedule, review notes, and a document request checklist (Markdown), plus the
   classified ledger (CSV).

## Input files

Files are recognized by their column headers, not their names. The sample formats:

| File | Required columns |
| --- | --- |
| TikTok Shop affiliate | `Settlement Date, Settled Commission` (+ `Order ID, Product Name, Shop Name, Status`) |
| TikTok Creator Rewards | `Month, Program, Estimated Rewards (USD)` |
| YouTube AdSense | `Month, Estimated Revenue (USD)` |
| PayPal activity | `Date, Name, Type, Gross, Fee, Net` (+ `Status, Note`) |
| Expenses (card/bank) | `Date, Merchant, Amount` (+ `Description, Business Use %, Notes`) |
| Gifted products | `Date Received, Brand, Estimated FMV` (+ `Item, Status`) |
| 1099s received | `Form, Payer, Amount` |
| Estimated payments | `Date, Amount` |
| `profile.json` | filing status, tax year, prior-year tax and AGI, W-2 wages, withholding, home office sq ft |

These are Creator Books' own layouts. Real platform exports use different columns. Supporting one
means adding an importer with its headers to `IMPORTERS` in `creator_books/importers.py`.

## Sample data

`sample_data/` holds two synthetic data sets for **Maya Torres**, a fictional gaming and trading-card
creator. Each folder has a `_PLANTED_ISSUES.md` listing the problems hidden in it on purpose.

- `maya_2026/`: Jan 1 to Sep 27, 2026. Mid-year planning, no 1099s yet.
- `maya_2025/`: full year 2025 with 1099s, including a TikTok form that doesn't tie to the books.

## Scope and limits

- Federal only. No state tax.
- Single and married filing jointly; tax years 2025 and 2026 (`creator_books/tax_tables.py`).
- Standard deduction; no credits, capital gains, AMT, retirement, or health-insurance deductions.
- One sole proprietorship; the S-corp check is a rough federal screen.
- It is a planning tool for review by a tax professional, not a filed return or tax advice.

## Layout

```
creator_books/   engine: importers, classifier + rules.json, tax math, review checks, packet
app/             FastAPI server + static front end (no build step)
sample_data/     synthetic creators with planted issues
scripts/         sample data generator
tests/           pytest suite
```
