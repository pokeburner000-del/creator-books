"""Assign a category to every transaction using the editable rules in rules.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Transaction, category_kind

RULES_PATH = Path(__file__).with_name("rules.json")


def load_rules(path: Path | str = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    biz = cfg.get("business_name_pattern", "")
    for r in cfg["rules"]:
        pat = r["pattern"].replace("@business_name", biz)
        r["_re"] = re.compile(pat, re.IGNORECASE)
    return cfg


def _field_text(t: Transaction, field: str) -> str:
    if field == "counterparty":
        return t.counterparty
    if field == "description":
        return t.description
    if field == "type":
        return t.extra.get("type", "")
    return f"{t.counterparty} {t.description} {t.note}"


def classify(txns: list[Transaction], cfg: dict | None = None,
             overrides: dict[str, dict] | None = None) -> list[Transaction]:
    """Classify in place and return the list plus derived fee rows.

    overrides: {txn_id: {"category": ..., "business_use_pct": ...}} applied last,
    so a reviewer's decision always beats the rules.
    """
    cfg = cfg or load_rules()
    defaults = cfg.get("source_defaults", {})
    out: list[Transaction] = []

    for t in txns:
        t.category, t.rule = "needs_review", "unmatched"

        if t.source in defaults:
            t.category, t.rule = defaults[t.source], f"source:{t.source}"
            if t.source == "gifted":
                status = t.extra.get("status", "").lower()
                if "return" in status:
                    t.category, t.rule = "returned_gift", "gifted:returned"
                elif "given" in status or "donat" in status:
                    t.extra["review"] = True
        else:
            for r in cfg["rules"]:
                if r.get("source") and r["source"] != t.source:
                    continue
                if r.get("sign") == "inflow" and t.amount <= 0:
                    continue
                if r.get("sign") == "outflow" and t.amount >= 0:
                    continue
                if r["_re"].search(_field_text(t, r["field"])):
                    t.category, t.rule = r["category"], r["name"]
                    if r.get("mixed_use"):
                        t.extra["mixed_use"] = True
                    if r.get("review"):
                        t.extra["review"] = True
                    break

            # an inflow can't be an expense and an outflow can't be income
            kind = category_kind(t.category)
            if (kind == "expense" and t.amount > 0) or (kind == "income" and t.amount < 0 and t.source == "paypal"):
                t.category, t.rule = "needs_review", f"{t.rule}:sign-mismatch"

        ov = (overrides or {}).get(t.id)
        if ov:
            if ov.get("category"):
                t.category, t.rule = ov["category"], "reviewer override"
            if ov.get("business_use_pct") is not None:
                t.business_use_pct = float(ov["business_use_pct"])
            t.extra.pop("review", None)
        out.append(t)

        # fees withheld from business income become a deductible expense row
        if t.fee and category_kind(t.category) == "income":
            out.append(Transaction(
                id=f"{t.id}-fee", date=t.date, source=t.source, counterparty=t.source.title(),
                description=f"Fee withheld on {t.counterparty}", amount=-t.fee,
                category="platform_fees", rule="derived:fee",
            ))
    return out
