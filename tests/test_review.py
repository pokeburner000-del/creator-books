"""Every planted issue in the sample data sets must be caught."""

from pathlib import Path

import pytest

from creator_books.engine import Options, analyze
from creator_books.importers import Dataset, load_dir, parse_money

ROOT = Path(__file__).resolve().parents[1] / "sample_data"


@pytest.fixture(scope="module")
def a26():
    return analyze(load_dir(str(ROOT / "maya_2026")))


@pytest.fixture(scope="module")
def a25():
    return analyze(load_dir(str(ROOT / "maya_2025")))


def ids(a):
    return {f["id"] for f in a["flags"]}


def txn(a, counterparty, contains=""):
    return [t for t in a["transactions"] if t["counterparty"] == counterparty and contains in t["description"]]


def test_2026_planted_flags(a26):
    got = ids(a26)
    for fid in ["unclassified-inflows", "gifted-income", "gifted-given-away", "mixed-use-missing-pct",
                "issue-1099-alex-chen", "estimates-short", "estimates-next", "unclassified-expenses",
                "equipment-capitalize", "collectibles-personal", "tax-payments-unrecorded",
                "rule-review", "personal-inflows", "meals-50", "home-office", "affiliate-refunds",
                "expected-1099s", "personal-excluded"]:
        assert fid in got, fid


def test_2026_classification(a26):
    assert txn(a26, "Sam Rivera")[0]["category"] == "needs_review"
    kit = txn(a26, "Kitsune Snacks", "Campaign")[0]
    assert kit["category"] == "sponsorship" and kit["extra"]["review"]
    assert all(t["category"] == "sponsorship" for t in txn(a26, "Pixel Forge Games LLC"))
    assert txn(a26, "Jordan Lee")[0]["category"] == "personal_transfer"
    assert txn(a26, "Glowdesk")[0]["category"] == "returned_gift"
    assert all(t["category"] == "personal" for t in txn(a26, "Netflix"))
    pc = txn(a26, "Best Buy")[0]
    assert pc["category"] == "equipment" and pc["deductible_amount"] == 0  # mixed use, no % yet
    iphone = txn(a26, "Apple Store")[0]
    assert iphone["deductible_amount"] == pytest.approx(1199 * 0.6)


def test_2026_is_in_progress_and_projects(a26):
    assert a26["period"]["in_progress"] and a26["period"]["through"] == "2026-09-27"
    assert a26["totals"]["projected_income"] > a26["totals"]["ytd_income"]
    # one-off items are not extrapolated
    spons = next(l for l in a26["lines"] if l["category"] == "sponsorship")
    assert spons["ytd"] == spons["projected"] == 7_000


def test_what_if_multiplier_raises_tax(a26):
    ds = load_dir(str(ROOT / "maya_2026"))
    hi = analyze(ds, Options(rest_of_year_multiplier=2.0))
    assert hi["tax"]["total_tax"] > a26["tax"]["total_tax"]
    assert hi["totals"]["ytd_income"] == a26["totals"]["ytd_income"]


def test_override_clears_flag():
    ds = load_dir(str(ROOT / "maya_2026"))
    sam = next(t for t in ds.transactions if t.counterparty == "Sam Rivera")
    a = analyze(ds, Options(overrides={sam.id: {"category": "sponsorship"}}))
    assert "unclassified-inflows" not in ids(a)
    base = analyze(ds)
    assert a["totals"]["ytd_income"] == pytest.approx(base["totals"]["ytd_income"] + 400)


def test_2025_reconciliation(a25):
    got = ids(a25)
    assert "1099-mismatch-tiktok-inc" in got
    assert "1099-ok-google-llc" in got
    assert "1099-ok-pixel-forge-games-llc" in got
    assert "issue-1099-alex-chen" in got  # $900 > $600 threshold in 2025
    assert "estimates-short" in got
    assert "tax-payments-unrecorded" not in got  # both IRS payments are in the estimates file
    assert not a25["period"]["in_progress"]


def test_unrecognized_file_warns():
    ds = Dataset()
    ds.add_file("mystery.csv", "foo,bar\n1,2\n")
    assert ds.warnings and not ds.transactions


def test_parse_money():
    assert parse_money("$1,234.50") == 1234.5
    assert parse_money("(45.00)") == -45.0
    assert parse_money("") == 0.0
