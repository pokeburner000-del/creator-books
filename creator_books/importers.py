"""Read raw export files into Transactions.

Each importer is chosen by the file's header row, not its name, so users can drop in
files however they are named. The column layouts here are Creator Books' own sample
formats; real platform exports can be supported by adding an importer with its
headers to IMPORTERS.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from typing import Callable, Iterable

from .models import EstimatedPayment, Form1099, Profile, Transaction


# ---------- parsing helpers ----------

def parse_money(value: str | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^0-9.\-]", "", s)
    if s in ("", "-", "."):
        return 0.0
    v = float(s)
    return -abs(v) if neg else v


def parse_date(value: str) -> date:
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%b %d, %Y", "%Y-%m"):
        try:
            d = datetime.strptime(s, fmt).date()
            if fmt == "%Y-%m":  # monthly rows land on the last day of the month
                nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
                d = date.fromordinal(nxt.toordinal() - 1)
            return d
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date: {value!r}")


def parse_pct(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value).strip().rstrip("%"))


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


def read_rows(text: str) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = [_norm(h) for h in (reader.fieldnames or [])]
    rows = []
    for raw in reader:
        rows.append({_norm(k): (v or "").strip() for k, v in raw.items() if k is not None})
    return headers, rows


# ---------- importers ----------

def import_tiktok_shop(rows: list[dict], fname: str) -> list[Transaction]:
    out = []
    for i, r in enumerate(rows):
        amt = parse_money(r.get("settled_commission"))
        status = r.get("status", "").lower()
        if "refund" in status and amt > 0:
            amt = -amt
        out.append(Transaction(
            id=f"tts-{i+1:04d}", date=parse_date(r["settlement_date"]), source="tiktok_shop",
            counterparty=r.get("shop_name") or "TikTok Shop",
            description=f"{r.get('product_name', '')} ({r.get('status', '')})".strip(),
            amount=amt, extra={"order_id": r.get("order_id", ""), "status": r.get("status", "")},
        ))
    return out


def import_tiktok_rewards(rows: list[dict], fname: str) -> list[Transaction]:
    return [Transaction(
        id=f"ttr-{i+1:04d}", date=parse_date(r["month"]), source="tiktok_rewards",
        counterparty="TikTok", description=r.get("program", "Creator Rewards"),
        amount=parse_money(r.get("estimated_rewards_usd") or r.get("amount")),
    ) for i, r in enumerate(rows)]


def import_youtube(rows: list[dict], fname: str) -> list[Transaction]:
    return [Transaction(
        id=f"yt-{i+1:04d}", date=parse_date(r["month"]), source="youtube",
        counterparty="Google (YouTube AdSense)",
        description=f"AdSense revenue {r.get('channel', '')}".strip(),
        amount=parse_money(r.get("estimated_revenue_usd")),
        extra={"payment_date": r.get("payment_date", "")},
    ) for i, r in enumerate(rows)]


def import_paypal(rows: list[dict], fname: str) -> list[Transaction]:
    out = []
    for i, r in enumerate(rows):
        if r.get("status", "Completed").lower() not in ("completed", ""):
            continue
        gross = parse_money(r.get("gross"))
        fee = abs(parse_money(r.get("fee")))
        out.append(Transaction(
            id=f"pp-{i+1:04d}", date=parse_date(r["date"]), source="paypal",
            counterparty=r.get("name", ""), description=f"{r.get('type', '')}: {r.get('note', '')}".strip(": "),
            amount=gross, fee=fee,
            extra={"type": r.get("type", ""), "note": r.get("note", ""), "transaction_id": r.get("transaction_id", "")},
        ))
    return out


def import_expenses(rows: list[dict], fname: str) -> list[Transaction]:
    out = []
    for i, r in enumerate(rows):
        amt = parse_money(r.get("amount"))
        out.append(Transaction(
            id=f"ex-{i+1:04d}", date=parse_date(r["date"]), source="expenses",
            counterparty=r.get("merchant", ""), description=r.get("description", ""),
            amount=-abs(amt), business_use_pct=parse_pct(r.get("business_use")),
            note=r.get("notes", ""),
        ))
    return out


def import_gifted(rows: list[dict], fname: str) -> list[Transaction]:
    out = []
    for i, r in enumerate(rows):
        out.append(Transaction(
            id=f"gf-{i+1:04d}", date=parse_date(r["date_received"]), source="gifted",
            counterparty=r.get("brand", ""), description=r.get("item", ""),
            amount=parse_money(r.get("estimated_fmv")),
            extra={"status": r.get("status", ""), "featured": r.get("featured_in_content", "")},
        ))
    return out


# (required header set, kind, function)
IMPORTERS: list[tuple[set[str], str, Callable]] = [
    ({"settlement_date", "settled_commission"}, "tiktok_shop", import_tiktok_shop),
    ({"month", "program"}, "tiktok_rewards", import_tiktok_rewards),
    ({"month", "estimated_revenue_usd"}, "youtube", import_youtube),
    ({"date", "name", "type", "gross", "fee", "net"}, "paypal", import_paypal),
    ({"date", "merchant", "amount"}, "expenses", import_expenses),
    ({"date_received", "brand", "estimated_fmv"}, "gifted", import_gifted),
]


def detect_kind(headers: Iterable[str]) -> str | None:
    hs = set(headers)
    if {"form", "payer", "amount"} <= hs:
        return "forms_1099"
    if {"date", "amount"} <= hs and hs <= {"date", "amount", "type", "notes"} and "merchant" not in hs:
        return "estimated_payments"
    for req, kind, _ in IMPORTERS:
        if req <= hs:
            return kind
    return None


class Dataset:
    """Everything loaded for one client and tax year."""

    def __init__(self) -> None:
        self.transactions: list[Transaction] = []
        self.forms: list[Form1099] = []
        self.estimates: list[EstimatedPayment] = []
        self.profile = Profile()
        self.files: list[dict] = []  # what was loaded
        self.warnings: list[str] = []

    def add_file(self, filename: str, content: str) -> None:
        if filename.lower().endswith(".json"):
            self.profile = Profile.from_dict(json.loads(content))
            self.files.append({"file": filename, "kind": "profile", "rows": 1})
            return
        headers, rows = read_rows(content)
        kind = detect_kind(headers)
        if kind is None:
            self.warnings.append(f"{filename}: couldn't recognize this file's columns ({', '.join(headers)}). Skipped.")
            self.files.append({"file": filename, "kind": "unrecognized", "rows": len(rows)})
            return
        if kind == "forms_1099":
            self.forms += [Form1099(form=r["form"].upper(), payer=r["payer"], amount=parse_money(r["amount"]), box=r.get("box", "")) for r in rows]
        elif kind == "estimated_payments":
            self.estimates += [EstimatedPayment(date=parse_date(r["date"]), amount=parse_money(r["amount"])) for r in rows]
        else:
            fn = next(f for req, k, f in IMPORTERS if k == kind)
            txns = fn(rows, filename)
            # keep ids unique across multiple files of the same kind
            existing = {t.id for t in self.transactions}
            for t in txns:
                base, n = t.id, 1
                while t.id in existing:
                    n += 1
                    t.id = f"{base}-{n}"
                existing.add(t.id)
            self.transactions += txns
        self.files.append({"file": filename, "kind": kind, "rows": len(rows)})


def load_dir(path: str) -> Dataset:
    import os
    ds = Dataset()
    for name in sorted(os.listdir(path)):
        if name.lower().endswith((".csv", ".json")) and not name.startswith("_"):
            with open(os.path.join(path, name), encoding="utf-8") as fh:
                ds.add_file(name, fh.read())
    return ds
