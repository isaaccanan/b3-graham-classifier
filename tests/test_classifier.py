"""Tests for classifier.py — Graham calculations, scoring, and labels."""

import math
import pytest
from unittest.mock import patch

from classifier import (
    GrahamReport, DividendYear,
    classify, _graham_number, _label, _debt_equity, _dividend_summary,
    LABEL_ORDER,
)
from brapi import RawQuote


# ── helpers ───────────────────────────────────────────────────────────────────

def _quote(**kwargs) -> RawQuote:
    defaults = dict(
        symbol="TEST3", company_name="Test Co", sector="Tech",
        price=10.0, eps=1.0, bvps=8.0, pe=10.0, pb=1.25,
        current_ratio=2.5, debt_to_equity=0.5,
        total_assets=1_000_000, total_liabilities=400_000,
        current_assets=500_000, current_liabilities=200_000,
        shares_outstanding=1_000_000, dividends=[],
    )
    defaults.update(kwargs)
    return RawQuote(**defaults)


# ── Graham Number ─────────────────────────────────────────────────────────────

class TestGrahamNumber:
    def test_normal(self):
        gn = _graham_number(eps=2.0, bvps=10.0)
        assert gn == pytest.approx(math.sqrt(22.5 * 2.0 * 10.0))

    def test_none_eps(self):
        assert _graham_number(eps=None, bvps=10.0) is None

    def test_none_bvps(self):
        assert _graham_number(eps=2.0, bvps=None) is None

    def test_both_none(self):
        assert _graham_number(eps=None, bvps=None) is None

    def test_negative_eps(self):
        # product becomes negative → sqrt not possible → None
        assert _graham_number(eps=-1.0, bvps=10.0) is None

    def test_zero_bvps(self):
        assert _graham_number(eps=2.0, bvps=0.0) is None


# ── Label assignment ──────────────────────────────────────────────────────────

class TestLabel:
    def test_strong_buy(self):
        assert _label(6, 6, True, 50.0) == "Strong Buy"

    def test_strong_buy_requires_gn_pass(self):
        result = _label(5, 6, False, 50.0)
        assert result != "Strong Buy"

    def test_buy(self):
        assert _label(4, 6, True, 50.0) == "Buy"

    def test_hold(self):
        assert _label(3, 6, False, 50.0) == "Hold"

    def test_overvalued(self):
        assert _label(2, 6, False, 50.0) == "Overvalued"

    def test_avoid(self):
        assert _label(0, 6, False, 50.0) == "Avoid"

    def test_inconclusive_when_no_gn(self):
        assert _label(4, 6, None, None) == "Inconclusive"

    def test_insufficient_data_when_no_criteria(self):
        assert _label(0, 0, None, None) == "Insufficient Data"

    def test_label_order_is_complete(self):
        labels = {"Strong Buy", "Buy", "Hold", "Overvalued", "Avoid",
                  "Inconclusive", "Insufficient Data"}
        assert set(LABEL_ORDER) == labels


# ── Sell signal ───────────────────────────────────────────────────────────────

class TestSellSignal:
    def test_sell_when_price_above_gn(self):
        q = _quote(price=90.0, eps=2.0, bvps=10.0)  # GN ≈ 21.2
        report = classify(q)
        assert report.sell_signal is True

    def test_no_sell_when_price_below_gn(self):
        q = _quote(price=10.0, eps=2.0, bvps=10.0)  # GN ≈ 21.2
        report = classify(q)
        assert report.sell_signal is False

    def test_sell_at_exact_gn(self):
        gn = math.sqrt(22.5 * 2.0 * 10.0)
        q = _quote(price=gn, eps=2.0, bvps=10.0)
        report = classify(q)
        assert report.sell_signal is True  # MoS == 0 → sell

    def test_sell_none_when_no_gn(self):
        q = _quote(eps=None, bvps=None)
        report = classify(q)
        assert report.sell_signal is None


# ── Classify full report ──────────────────────────────────────────────────────

class TestClassify:
    def test_returns_graham_report(self):
        report = classify(_quote())
        assert isinstance(report, GrahamReport)

    def test_graham_number_computed(self):
        report = classify(_quote(eps=2.0, bvps=10.0))
        assert report.graham_number == pytest.approx(math.sqrt(22.5 * 2.0 * 10.0))

    def test_margin_of_safety(self):
        q = _quote(price=10.0, eps=2.0, bvps=10.0)
        report = classify(q)
        expected_mos = (report.graham_number - 10.0) / report.graham_number
        assert report.margin_of_safety == pytest.approx(expected_mos)

    def test_pe_derived_when_missing(self):
        q = _quote(pe=None, price=20.0, eps=2.0)
        report = classify(q)
        assert report.pe == pytest.approx(10.0)

    def test_pb_derived_when_missing(self):
        q = _quote(pb=None, price=10.0, bvps=8.0)
        report = classify(q)
        assert report.pb == pytest.approx(1.25)

    def test_balance_sheet_converted_to_millions(self):
        q = _quote(total_assets=5_000_000_000)
        report = classify(q)
        assert report.total_assets_m == pytest.approx(5000.0)

    def test_insufficient_data_when_all_none(self):
        q = _quote(price=None, eps=None, bvps=None, pe=None, pb=None,
                   current_ratio=None, debt_to_equity=None,
                   total_assets=None, total_liabilities=None,
                   current_assets=None, current_liabilities=None)
        report = classify(q)
        assert report.label == "Insufficient Data"
        assert report.score == 0
        assert report.max_score == 0

    def test_pe_criterion(self):
        report_pass = classify(_quote(pe=14.0, pb=None, eps=None, bvps=None))
        assert report_pass.criteria["P/E ≤ 15"] is True

        report_fail = classify(_quote(pe=16.0, pb=None, eps=None, bvps=None))
        assert report_fail.criteria["P/E ≤ 15"] is False

    def test_current_ratio_criterion(self):
        report_pass = classify(_quote(current_ratio=2.5))
        assert report_pass.criteria["C/R ≥ 2.0"] is True

        report_fail = classify(_quote(current_ratio=1.5))
        assert report_fail.criteria["C/R ≥ 2.0"] is False


# ── Debt/Equity ───────────────────────────────────────────────────────────────

class TestDebtEquity:
    def test_uses_direct_ratio(self):
        q = _quote(debt_to_equity=0.8, total_assets=None, total_liabilities=None)
        assert _debt_equity(q) == pytest.approx(0.8)

    def test_derives_from_balance_sheet(self):
        q = _quote(debt_to_equity=None, total_assets=1000.0, total_liabilities=400.0)
        # equity = 600, de = 400/600 ≈ 0.667
        assert _debt_equity(q) == pytest.approx(400 / 600)

    def test_none_when_no_data(self):
        q = _quote(debt_to_equity=None, total_assets=None, total_liabilities=None)
        assert _debt_equity(q) is None
