"""Review rules: reconciliation to 1099s and the creator-specific issues preparers miss.

Each check returns zero or more Flags. Every flag says why, cites the rule, and says
what to do, so a reviewer can accept or override it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from . import tax_tables as T
from .models import CATEGORIES, Flag, Transaction, category_kind

SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def money(x: float) -> str:
    return f"${x:,.2f}" if abs(x) < 100 else f"${x:,.0f}"


def _tokens(s: str) -> set[str]:
    stop = {"inc", "llc", "co", "corp", "the", "ltd", "com", "usa", "us", "payments", "pte"}
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in stop and len(w) > 1}


def payer_key(t: Transaction) -> str:
    """Who would issue the information return for this income."""
    if t.source in ("tiktok_shop", "tiktok_rewards"):
        return "TikTok"
    if t.source == "youtube":
        return "Google"
    return t.counterparty or "Unknown"


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def item_list(rows, limit: int = 6) -> str:
    """'Home internet ($70.00) x9; Gaming PC ($2,850)' - repeats grouped."""
    groups: dict[str, list] = {}
    for t in rows:
        groups.setdefault(t.description or t.counterparty, []).append(t)
    parts = []
    for name, g in list(groups.items())[:limit]:
        amt = money(-g[0].amount)
        parts.append(f"{name} ({amt})" + (f" x{len(g)}" if len(g) > 1 else ""))
    more = len(groups) - limit
    return "; ".join(parts) + (f"; and {more} more" if more > 0 else "")


def slug(s: str) -> str:
    return re.sub('[^a-z0-9]+', '-', s.lower()).strip('-')


def next_business_day(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


class Context:
    def __init__(self, txns, profile, forms, estimates, tax, schedule, scorp, projected, in_progress, through, ty):
        self.txns: list[Transaction] = txns
        self.profile = profile
        self.forms = forms
        self.estimates = estimates
        self.tax = tax
        self.schedule = schedule
        self.scorp = scorp
        self.projected = projected  # dict of full-year totals
        self.in_progress = in_progress
        self.through: date = through
        self.ty: T.TaxYear = ty

    def by_cat(self, *cats):
        return [t for t in self.txns if t.category in cats]


# ---------- checks ----------

def check_needs_review(c: Context) -> list[Flag]:
    flags = []
    unrev = c.by_cat("needs_review")
    inflows = [t for t in unrev if t.amount > 0]
    outflows = [t for t in unrev if t.amount < 0]
    if inflows:
        amt = sum(t.amount for t in inflows)
        flags.append(Flag(
            "unclassified-inflows", "high", f"{plural(len(inflows), 'incoming payment')} not yet classified",
            f"{money(amt)} came in from people or businesses the rules couldn't identify "
            f"({', '.join(sorted({t.counterparty for t in inflows}))}). They are left out of income until "
            "someone decides. If any were for a shoutout, promo, or other content work, they are taxable income.",
            "IRC §61 (gross income includes income from any source)", amt, [t.id for t in inflows],
            "Mark each one as business income or a personal transfer.",
            "Explanation for each unidentified incoming payment"))
    if outflows:
        amt = -sum(t.amount for t in outflows)
        flags.append(Flag(
            "unclassified-expenses", "medium", f"{plural(len(outflows), 'expense')} not yet classified",
            f"{money(amt)} of spending didn't match any rule and isn't deducted yet.",
            "IRC §162 (ordinary and necessary business expenses)", amt, [t.id for t in outflows],
            "Assign a category or mark as personal.", "Receipts or a business purpose for unclassified expenses"))
    return flags


def check_marked_for_review(c: Context) -> list[Flag]:
    rows = [t for t in c.txns if t.extra.get("review") and t.category not in ("gifted_product",)]
    if not rows:
        return []
    return [Flag(
        "rule-review", "low", f"{plural(len(rows), 'item')} classified with low confidence",
        "These matched a rule that usually needs a human look: " +
        "; ".join(f"{t.counterparty} ({CATEGORIES[t.category]['label'].lower()})" for t in rows[:6]) +
        ("…" if len(rows) > 6 else "") + ".",
        "", None, [t.id for t in rows], "Confirm or change each category.")]


def check_gifted(c: Context) -> list[Flag]:
    flags = []
    kept = c.by_cat("gifted_product")
    if kept:
        amt = sum(t.amount for t in kept)
        flags.append(Flag(
            "gifted-income", "high", f"Gifted products worth {money(amt)} are taxable income",
            f"{plural(len(kept), 'PR item')} received from brands and kept are income at fair market value, "
            "even with no cash and no 1099. They're included in income here. Items actually used to make "
            "content can then be deducted (or depreciated) as business property, which offsets part of it.",
            "IRC §61; Treas. Reg. §1.61-1(a) (income realized in any form, including property)", amt,
            [t.id for t in kept],
            "Confirm fair market value (retail price on the date received) and which items are used in content.",
            "PR package log with brand, item, date received, and retail value"))
        given = [t for t in kept if t.extra.get("review")]
        if given:
            flags.append(Flag(
                "gifted-given-away", "low", f"{plural(len(given), 'gifted item')} given away",
                "Items given to followers as giveaways are still income when received; the giveaway itself "
                "may be deductible as promotion.",
                "IRC §61; §162", sum(t.amount for t in given), [t.id for t in given],
                "Keep giveaway records (post link, winner, date)."))
    return flags


def check_mixed_use(c: Context) -> list[Flag]:
    rows = [t for t in c.txns if t.extra.get("mixed_use") and t.business_use_pct is None and t.amount < 0]
    flags = []
    if rows:
        amt = -sum(t.amount for t in rows)
        flags.append(Flag(
            "mixed-use-missing-pct", "high", f"{plural(len(rows), 'mixed-use item')} need{'s' if len(rows) == 1 else ''} a business-use percentage",
            f"{money(amt)} of phones, computers, or service plans are used for both content and personal life. "
            "Only the business share is deductible, so they're held at $0 until a percentage is set. "
            "Items: " + item_list(rows) + ".",
            "IRC §162 and §262 (personal expenses not deductible); allocate by business-use percentage",
            amt, [t.id for t in rows],
            "Estimate business use from a typical week (hours editing/filming vs. personal) and write down how.",
            "Business-use estimate for each phone, computer, and service plan"))
    set_rows = [t for t in c.txns if t.extra.get("mixed_use") and t.business_use_pct is not None]
    if set_rows:
        flags.append(Flag(
            "mixed-use-documented", "info", f"{plural(len(set_rows), 'mixed-use item')} deducted at the percentage given",
            "Deducted at the stated business share. Keep a note of how each percentage was estimated.",
            "IRC §274(d) substantiation", None, [t.id for t in set_rows]))
    return flags


def check_equipment(c: Context) -> list[Flag]:
    big = [t for t in c.by_cat("equipment") if -t.amount > 2_500]
    if not big:
        return []
    return [Flag(
        "equipment-capitalize", "medium", f"{plural(len(big), 'equipment purchase')} over $2,500",
        "Items over the $2,500 de minimis safe harbor can't just be expensed as supplies. They can usually "
        "still be written off in full this year through a Section 179 election or 100% bonus depreciation "
        "(restored for property acquired after Jan. 19, 2025), reported on Form 4562. "
        "Items: " + item_list(big) + ".",
        "Treas. Reg. §1.263(a)-1(f) (de minimis safe harbor); IRC §179; IRC §168(k)",
        -sum(t.amount for t in big), [t.id for t in big],
        "Choose Section 179 or bonus depreciation on Form 4562.",
        "Invoices for equipment over $2,500 (date placed in service)")]


COLLECTION_RE = re.compile(r"\b(kept|keep|collection|personal|psa|grade|graded|pc|slab)\b", re.I)


def check_collectibles(c: Context) -> list[Flag]:
    rows = [t for t in c.by_cat("content_inventory")
            if COLLECTION_RE.search(f"{t.description} {t.note}") and t.amount < 0]
    flags = []
    if rows:
        amt = -sum(t.amount for t in rows)
        flags.append(Flag(
            "collectibles-personal", "medium", f"{plural(len(rows), 'card or collectible purchase')} look{'s' if len(rows) == 1 else ''} personal",
            f"{money(amt)} of cards were bought for videos but notes say they were kept, graded, or added to a "
            "personal collection. Items kept as collectibles are personal, not a business expense; if sold "
            "later, gains are taxed as collectibles (up to 28%). They're still deducted here until you decide.",
            "IRC §262; IRC §1(h)(4) (collectibles gain)", amt, [t.id for t in rows],
            "Move kept or graded items to Personal. Keep opened-on-camera product as a business expense.",
            "List of cards pulled on camera that were kept vs. sold vs. given away"))
    all_cards = c.by_cat("content_inventory")
    if all_cards:
        flags.append(Flag(
            "content-inventory-resale", "info", "If you resell cards, track them as inventory",
            "Cards bought to open on camera are a supplies expense. Cards bought to resell are inventory: "
            "you deduct their cost only when sold (cost of goods sold, Schedule C Part III).",
            "IRC §471; Schedule C Part III", None, [t.id for t in all_cards]))
    return flags


def check_contractors(c: Context) -> list[Flag]:
    by_payee = defaultdict(list)
    for t in c.by_cat("contractor"):
        by_payee[t.counterparty].append(t)
    flags = []
    due = next_business_day(date(c.ty.year + 1, 1, 31))
    for payee, rows in by_payee.items():
        total = -sum(t.amount for t in rows)
        projected = total
        if c.in_progress:
            days = (c.through - date(c.ty.year, 1, 1)).days + 1
            projected = total * 365 / days
        if projected >= c.ty.nec_threshold:
            flags.append(Flag(
                f"issue-1099-{slug(payee)}", "high",
                f"You may need to send {payee} a Form 1099-NEC",
                f"You paid {payee} {money(total)} so far ({'on pace for ' + money(projected) if c.in_progress else 'for the year'}), "
                f"above the {money(c.ty.nec_threshold)} reporting threshold for {c.ty.year}. File Form 1099-NEC "
                f"and send a copy by {due:%b %d, %Y}. Exception: if every payment went through PayPal Goods & "
                "Services or a card, PayPal reports it on a 1099-K and you don't file a 1099-NEC.",
                "IRC §6041A; Form 1099-NEC instructions (third-party network payments excluded)", total,
                [t.id for t in rows], f"Get a Form W-9 from {payee} now; confirm how each payment was sent.",
                f"Form W-9 from {payee}"))
    return flags


def check_1099s(c: Context) -> list[Flag]:
    flags = []
    income = [t for t in c.txns if category_kind(t.category) == "income" and t.source != "gifted"]
    ledger = defaultdict(float)
    for t in income:
        ledger[payer_key(t)] += t.amount
    paypal_gross = sum(t.amount for t in c.txns if t.source == "paypal" and t.amount > 0)

    if not c.forms:
        if c.in_progress:
            expected = []
            days = (c.through - date(c.ty.year, 1, 1)).days + 1
            for payer, amt in sorted(ledger.items(), key=lambda kv: -kv[1]):
                pace = amt * 365 / days if payer in ("TikTok", "Google") else amt
                if pace >= c.ty.nec_threshold:
                    expected.append(f"{payer} (~{money(pace)})")
            n_pp = sum(1 for t in c.txns if t.source == "paypal" and t.amount > 0)
            k_note = ""
            if paypal_gross * 365 / days > c.ty.k_threshold_amount and n_pp * 365 / days > c.ty.k_threshold_count:
                k_note = " PayPal is also on pace to send a 1099-K."
            flags.append(Flag(
                "expected-1099s", "info", "1099s to expect in January",
                "Based on the pace so far, expect forms from: " + (", ".join(expected) or "no one yet") + "." + k_note +
                f" Payers under {money(c.ty.nec_threshold)} don't have to send a form, but that income is still taxable.",
                "IRC §6041; OBBBA §70433 ($2,000 threshold from 2026)", None, [],
                "Watch for forms in January and upload them to reconcile.",
                "All Forms 1099 received (NEC, MISC, K) when they arrive"))
        return flags

    matched_payers = set()
    for f in c.forms:
        if f.form == "1099-K" and "paypal" in f.payer.lower():
            book, label = paypal_gross, "gross PayPal receipts"
        else:
            fk = _tokens(f.payer)
            best, score = None, 0
            for payer in ledger:
                s = len(fk & _tokens(payer))
                if s > score:
                    best, score = payer, s
            if best is None:
                flags.append(Flag(
                    f"1099-unmatched-{len(flags)}", "high", f"{f.form} from {f.payer} doesn't match any income",
                    f"The form reports {money(f.amount)}, but no income from this payer is in the files. The IRS "
                    "will expect it on the return.", "IRC §6041", f.amount, [],
                    "Find the deposits for this payer or ask them for a corrected form.",
                    f"Payment records from {f.payer}"))
                continue
            matched_payers.add(best)
            book, label = ledger[best], f"income from {best}"
        diff = f.amount - book
        tol = max(25.0, 0.01 * f.amount)
        if abs(diff) > tol:
            flags.append(Flag(
                f"1099-mismatch-{slug(f.payer)}", "high",
                f"{f.form} from {f.payer} is {money(abs(diff))} {'higher' if diff > 0 else 'lower'} than the books",
                f"Form shows {money(f.amount)}; the files show {money(book)} of {label}. "
                + ("A higher form amount often means refunds or chargebacks were netted in the books but not on "
                   "the form, or fees were subtracted before recording. Report the form amount as gross receipts "
                   "and deduct the difference separately, so the return ties to the form."
                   if diff > 0 else
                   "A lower form amount can mean some payments were sent outside this payer or in a different year. "
                   "All of it is still reportable."),
                "IRC §6041; Schedule C line 1 instructions", abs(diff), [],
                "Tie out the difference before filing.", f"Monthly statements from {f.payer}"))
        else:
            flags.append(Flag(
                f"1099-ok-{slug(f.payer)}", "info",
                f"{f.form} from {f.payer} ties to the books", f"Form {money(f.amount)} vs. books {money(book)}.",
                "", None, []))

    has_paypal_k = any(fm.form == "1099-K" and "paypal" in fm.payer.lower() for fm in c.forms)
    via_paypal = {payer_key(t) for t in income if t.source == "paypal"}
    no_form = [(p, a) for p, a in ledger.items()
               if p not in matched_payers and a > 0 and not (has_paypal_k and p in via_paypal)]
    if no_form:
        amt = sum(a for _, a in no_form)
        flags.append(Flag(
            "income-no-1099", "medium", f"{money(amt)} of income arrived with no 1099",
            "No form covers income from: " + ", ".join(f"{p} ({money(a)})" for p, a in no_form) +
            ". That's normal below the reporting threshold, and it's still taxable income. It's included here.",
            "IRC §61", amt, [], "Keep the deposit records that support these amounts."))
    if any(f.form == "1099-K" for f in c.forms) and any(f.form == "1099-NEC" for f in c.forms):
        flags.append(Flag(
            "k-nec-overlap", "medium", "Watch for the same income on a 1099-K and a 1099-NEC",
            "A brand that paid through PayPal and also sent a 1099-NEC can make one payment show up on two forms. "
            "Report it once, and keep a reconciliation showing the overlap.",
            "IRS Form 1099-K FAQs", None, []))
    return flags


def check_personal_inflows(c: Context) -> list[Flag]:
    rows = [t for t in c.by_cat("personal_transfer") if t.amount > 0]
    if not rows:
        return []
    return [Flag(
        "personal-inflows", "low", f"{plural(len(rows), 'incoming payment')} treated as personal",
        f"{money(sum(t.amount for t in rows))} from friends or family is left out of income. If PayPal includes "
        "these on a 1099-K, report the gross and back them out as personal, with a note.",
        "IRS Form 1099-K guidance (personal reimbursements aren't income)", sum(t.amount for t in rows),
        [t.id for t in rows], "Confirm none were for content work.")]


def check_meals(c: Context) -> list[Flag]:
    rows = c.by_cat("meals")
    if not rows:
        return []
    total = -sum(t.amount for t in rows)
    return [Flag(
        "meals-50", "low", "Business meals are limited to 50%",
        f"{money(total)} of meals, deducted at {money(total/2)}. Each needs who you ate with and the business purpose. "
        "Coffee or food bought alone on an ordinary workday is personal; move those rows to Personal.",
        "IRC §274(k) and (n)", total, [t.id for t in rows], "Add attendees and purpose to each receipt.")]


def check_home_office(c: Context) -> list[Flag]:
    sq = c.profile.home_office_sqft
    if sq > 0:
        ded = min(sq, T.HOME_OFFICE_MAX_SQFT) * T.HOME_OFFICE_RATE
        return [Flag(
            "home-office", "info", f"Home office: {money(ded)} using the simplified method",
            f"{sq:g} sq ft × $5 (capped at 300 sq ft). The space must be used regularly and only for the business "
            "(a desk in a shared bedroom doesn't count).",
            "IRC §280A(c); Rev. Proc. 2013-13", ded, [], "Measure the space and take a photo of the setup.",
            "Home office square footage and total home square footage")]
    return [Flag(
        "home-office-missing", "low", "No home office entered",
        "If a room or area is used only for filming or editing, the simplified method allows $5 per sq ft up to "
        "$1,500 a year.", "IRC §280A(c); Rev. Proc. 2013-13", None, [],
        "Add square footage to the profile if a dedicated space exists.")]


def check_hobby(c: Context) -> list[Flag]:
    if c.tax.net_profit <= 0 or c.profile.years_with_losses >= 2:
        return [Flag(
            "hobby-loss", "medium", "Hobby-loss risk",
            "The activity shows a loss" + (f" and has {c.profile.years_with_losses} prior loss years" if c.profile.years_with_losses else "") +
            ". If the IRS treats it as a hobby, income stays taxable but expenses aren't deductible. A profit in 3 of 5 "
            "years creates a presumption that it's a business.",
            "IRC §183; Treas. Reg. §1.183-2(b) (nine factors)", None, [],
            "Keep a business plan, separate account, and records showing effort to make a profit.",
            "Business plan or documentation of profit motive")]
    return []


def check_estimates(c: Context, required: float, basis: str) -> list[Flag]:
    flags = []
    owe = c.tax.balance_after_withholding
    if owe < T.PENALTY_DE_MINIMIS:
        flags.append(Flag(
            "estimates-not-needed", "info", "Estimated payments likely not required",
            f"Projected tax after withholding is {money(owe)}, under the $1,000 threshold.",
            "IRC §6654(e)(1)", None, []))
        return flags
    past = [q for q in c.schedule if q["status"] == "short"]
    if past:
        worst = past[-1]
        flags.append(Flag(
            "estimates-short", "high", f"Estimated payments are {money(worst['shortfall'])} behind",
            f"By the {worst['quarter']} due date ({worst['due']}) you needed {money(worst['required_to_date'])} paid "
            f"({basis}) and had paid {money(worst['paid_to_date'])}. The underpayment penalty works like interest "
            "from each missed due date until paid, so catching up sooner costs less.",
            "IRC §6654; Form 2210", worst["shortfall"], [],
            "Make a catch-up payment now through IRS Direct Pay, then keep paying each quarter."))
    nxt = next((q for q in c.schedule if q["status"] == "future"), None)
    if nxt:
        catch_up = max(0.0, nxt["required_to_date"] - nxt["paid_to_date"])
        flags.append(Flag(
            "estimates-next", "info", f"Next estimated payment: {money(catch_up)} by {nxt['due']}",
            f"This brings total payments to {money(nxt['required_to_date'])}, the safe-harbor amount through {nxt['quarter']} ({basis}).",
            "IRC §6654(d)", catch_up, []))
    return flags


def check_sstb(c: Context) -> list[Flag]:
    spons = sum(t.amount for t in c.by_cat("sponsorship"))
    if spons <= 0:
        return []
    near = c.tax.taxable_before_qbi > c.ty.qbi_threshold[c.profile.filing_status] - 25_000
    if not near:
        return []
    return [Flag(
        "qbi-sstb", "medium", "Sponsorship income could limit the QBI deduction",
        f"Taxable income is near the {money(c.ty.qbi_threshold[c.profile.filing_status])} threshold. Above it, fees for "
        "endorsing products or using your name or likeness count as a specified service business, and that part of "
        "the 20% deduction phases out. Affiliate and ad revenue generally aren't affected.",
        "IRC §199A(d)(2); Treas. Reg. §1.199A-5(b)(2)(xiv)", spons, [t.id for t in c.by_cat("sponsorship")],
        "Separate endorsement fees from other income in the books.")]


def check_scorp(c: Context) -> list[Flag]:
    s = c.scorp
    if not s or s.get("savings", 0) <= 0:
        return []
    return [Flag(
        "s-corp", "info", f"S-corp election could save about {money(s['savings'])}",
        f"{s['verdict']} This assumes a {int(s['salary_pct']*100)}% salary ({money(s['salary'])}) and "
        f"{money(s['admin_cost'])} a year for payroll and the extra return. Federal only.",
        "IRC §1362; reasonable compensation (Rev. Rul. 74-44)", s["savings"], [],
        "Talk to a CPA before electing; state taxes and the salary level change the answer.")]


def check_refunds(c: Context) -> list[Flag]:
    rows = [t for t in c.txns if t.source == "tiktok_shop" and t.amount < 0]
    if not rows:
        return []
    return [Flag(
        "affiliate-refunds", "info", f"{plural(len(rows), 'refunded affiliate order')} netted",
        f"{money(-sum(t.amount for t in rows))} of commissions were clawed back on refunded orders. If TikTok's 1099 "
        "reports commissions before refunds, report the form amount and deduct the refunds as returns.",
        "Schedule C line 2 (returns and allowances)", -sum(t.amount for t in rows), [t.id for t in rows])]


def check_tax_payments_in_books(c: Context) -> list[Flag]:
    rows = c.by_cat("tax_payment")
    if not rows:
        return []
    recorded = {(e.date, round(e.amount, 2)) for e in c.estimates}
    missing = [t for t in rows if (t.date, round(-t.amount, 2)) not in recorded]
    if not missing:
        return []
    return [Flag(
        "tax-payments-unrecorded", "medium", f"{plural(len(missing), 'tax payment')} in the books missing from the estimates list",
        "Payments to the IRS aren't a business expense, but they count toward estimated tax. Add them to the "
        "estimated payments file so the schedule credits them.",
        "IRC §6654", -sum(t.amount for t in missing), [t.id for t in missing],
        "Add each payment to estimated_payments.csv.", "IRS payment confirmations")]


def check_personal_expenses(c: Context) -> list[Flag]:
    rows = [t for t in c.by_cat("personal") if t.amount < 0]
    if not rows:
        return []
    return [Flag(
        "personal-excluded", "info", f"{plural(len(rows), 'personal expense')} excluded",
        f"{money(-sum(t.amount for t in rows))} of personal spending (streaming, groceries, etc.) isn't deducted. "
        "A separate business account keeps these out of the books.",
        "IRC §262", None, [t.id for t in rows])]


def run_all(c: Context, required: float, basis: str) -> list[Flag]:
    flags: list[Flag] = []
    for fn in (check_needs_review, check_gifted, check_mixed_use, check_contractors, check_1099s,
               check_equipment, check_collectibles, check_hobby, check_sstb, check_tax_payments_in_books,
               check_marked_for_review, check_personal_inflows, check_meals, check_home_office,
               check_refunds, check_scorp, check_personal_expenses):
        flags += fn(c)
    flags += check_estimates(c, required, basis)
    flags.sort(key=lambda f: SEV_ORDER.get(f.severity, 9))
    return flags
