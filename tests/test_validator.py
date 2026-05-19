"""Tests for validator.py — cross-validation logic and source preference."""

import pytest
from validator import validate, _check, _fmt, FieldCheck
from brapi import RawQuote
from fundamentus import FundamentusQuote
from statusinvest import StatusInvestQuote


# ── fixtures ──────────────────────────────────────────────────────────────────

def _brapi(**kwargs) -> RawQuote:
    defaults = dict(
        symbol="TEST3", price=50.0, eps=2.0, bvps=10.0, pe=10.0, pb=1.2,
        price_updated_at="2026-03-31", balance_updated_at="2026-03-31",
    )
    defaults.update(kwargs)
    return RawQuote(**defaults)


def _fund(**kwargs) -> FundamentusQuote:
    defaults = dict(
        ticker="TEST3", price=50.5, lpa=2.0, vpa=10.1, pl=10.0, pvp=1.2,
        balance_updated_at="2026-03-31",
    )
    defaults.update(kwargs)
    return FundamentusQuote(**defaults)


def _si(**kwargs) -> StatusInvestQuote:
    defaults = dict(ticker="TEST3", price=50.2, lpa=2.0, vpa=10.0, pl=10.0, pvp=1.2)
    defaults.update(kwargs)
    return StatusInvestQuote(**defaults)


# ── _check ─────────────────────────────────────────────────────────────────────

class TestCheck:
    def test_ok_within_tolerance(self):
        c = _check("price", 100.0, 101.0, None, tol=0.02)
        assert c.status == "OK"
        assert c.resolved == pytest.approx(100.0)

    def test_diverged_beyond_tolerance(self):
        c = _check("eps", 2.0, 3.0, None, tol=0.05)
        assert c.status == "DIVERGED"
        assert c.divergence == pytest.approx(abs(2.0 - 3.0) / 3.0)

    def test_diverged_prefers_fundamentus(self):
        c = _check("eps", 2.0, 3.0, None, tol=0.05)
        assert c.resolved == pytest.approx(3.0)

    def test_si_tiebreaker_sides_with_brapi(self):
        # Brapi=2.0, Fund=3.0, SI=2.1 → SI agrees with Brapi → use Brapi
        c = _check("eps", 2.0, 3.0, 2.1, tol=0.05)
        assert c.status == "DIVERGED"
        assert c.resolved == pytest.approx(2.0)

    def test_si_tiebreaker_confirms_fundamentus(self):
        # Brapi=2.0, Fund=3.0, SI=3.1 → SI agrees with Fund → use Fund
        c = _check("eps", 2.0, 3.0, 3.1, tol=0.05)
        assert c.resolved == pytest.approx(3.0)

    def test_brapi_only(self):
        c = _check("bvps", 10.0, None, None, tol=0.05)
        assert c.status == "BRAPI_ONLY"
        assert c.resolved == pytest.approx(10.0)

    def test_fund_only(self):
        c = _check("bvps", None, 10.0, None, tol=0.05)
        assert c.status == "FUND_ONLY"
        assert c.resolved == pytest.approx(10.0)

    def test_si_only_when_both_missing(self):
        c = _check("bvps", None, None, 10.0, tol=0.05)
        assert c.status == "SI_ONLY"
        assert c.resolved == pytest.approx(10.0)

    def test_both_missing(self):
        c = _check("bvps", None, None, None, tol=0.05)
        assert c.status == "BOTH_MISSING"
        assert c.resolved is None


# ── validate ──────────────────────────────────────────────────────────────────

class TestValidate:
    def test_resolved_values_present(self):
        v = validate(_brapi(), _fund())
        assert v.price is not None
        assert v.eps is not None
        assert v.bvps is not None

    def test_no_warnings_when_sources_agree(self):
        v = validate(_brapi(price=50.0), _fund(price=50.5))
        eps_warn = [w for w in v.warnings if "EPS" in w or "PRICE" in w.upper()]
        assert not eps_warn

    def test_warning_on_divergence(self):
        v = validate(_brapi(eps=2.0), _fund(lpa=4.0))  # 100% divergence
        assert any("EPS" in w for w in v.warnings)

    def test_warning_includes_si_value(self):
        v = validate(_brapi(eps=2.0), _fund(lpa=4.0), _si(lpa=3.9))
        warning = next(w for w in v.warnings if "EPS" in w)
        assert "SI=" in warning

    def test_balance_date_mismatch_warning(self):
        v = validate(
            _brapi(balance_updated_at="2025-12-31"),
            _fund(balance_updated_at="2026-03-31"),
        )
        assert any("BALANCE DATE" in w for w in v.warnings)

    def test_no_balance_date_mismatch_when_equal(self):
        v = validate(
            _brapi(balance_updated_at="2026-03-31"),
            _fund(balance_updated_at="2026-03-31"),
        )
        assert not any("BALANCE DATE" in w for w in v.warnings)

    def test_timestamps_recorded(self):
        v = validate(_brapi(), _fund())
        assert v.brapi_price_date == "2026-03-31"
        assert v.brapi_balance_date == "2026-03-31"
        assert v.fundamentus_balance_date == "2026-03-31"

    def test_diverged_fields_property(self):
        v = validate(_brapi(eps=2.0), _fund(lpa=4.0))
        assert "eps" in v.diverged_fields

    def test_has_warnings_property(self):
        v = validate(_brapi(eps=2.0), _fund(lpa=4.0))
        assert v.has_warnings is True

    def test_no_warnings_property(self):
        v = validate(_brapi(), _fund())
        assert v.has_warnings is False

    def test_fundamentus_fills_missing_brapi(self):
        v = validate(_brapi(eps=None), _fund(lpa=3.5))
        assert v.eps == pytest.approx(3.5)

    def test_si_fills_when_both_missing(self):
        v = validate(_brapi(bvps=None), _fund(vpa=None), _si(vpa=15.0))
        assert v.bvps == pytest.approx(15.0)
