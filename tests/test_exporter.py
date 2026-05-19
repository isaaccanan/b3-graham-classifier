"""Tests for exporter.py — CSV format, helpers, and sell signal column."""

import csv
import io
import pytest
from unittest.mock import patch

from exporter import _r, _pct, _yn, summary, detail, format_description, FORMATS
from classifier import GrahamReport


# ── helpers ───────────────────────────────────────────────────────────────────

class TestFormatHelpers:
    def test_r_none(self):
        assert _r(None) == "N/A"

    def test_r_float(self):
        assert _r(3.14159) == "3.14"

    def test_r_zero(self):
        assert _r(0.0) == "0.00"

    def test_pct_none(self):
        assert _pct(None) == "N/A"

    def test_pct_converts_decimal(self):
        assert _pct(0.435) == "43.50%"

    def test_pct_negative(self):
        assert _pct(-0.376) == "-37.60%"

    def test_yn_none(self):
        assert _yn(None) == "?"

    def test_yn_true(self):
        assert _yn(True) == "YES"

    def test_yn_false(self):
        assert _yn(False) == "NO"


# ── format registry ───────────────────────────────────────────────────────────

class TestFormats:
    def test_all_formats_present(self):
        assert "google" in FORMATS
        assert "numbers" in FORMATS
        assert "excel" in FORMATS

    def test_google_uses_semicolon(self):
        assert FORMATS["google"].separator == ";"

    def test_numbers_uses_comma(self):
        assert FORMATS["numbers"].separator == ","

    def test_google_has_bom(self):
        assert FORMATS["google"].encoding == "utf-8-sig"

    def test_numbers_no_bom(self):
        assert FORMATS["numbers"].encoding == "utf-8"

    def test_format_description(self):
        assert "Google" in format_description("google")
        assert "Numbers" in format_description("numbers")
        assert "Excel" in format_description("excel")

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError):
            format_description("unknown_fmt")


# ── CSV output ────────────────────────────────────────────────────────────────

def _make_report(**kwargs) -> GrahamReport:
    defaults = dict(
        ticker="TEST3", company_name="Test Co", sector="Tech",
        price=46.0, eps=2.0, bvps=10.0,
        total_assets_m=1000.0, total_liabilities_m=400.0,
        current_assets_m=300.0, current_liabilities_m=150.0,
        shares_outstanding_m=500.0,
        last_updated="2026-03-31",
        pe=10.0, pb=1.25, current_ratio=2.5,
        graham_number=21.2, intrinsic_value=21.2,
        margin_of_safety=-1.17,   # price > GN → sell signal
        dividend_history=[], avg_div_yield_3y=None,
        ipca_rate=0.045, real_earnings_yield=None,
        adjusted_graham_number=22.15,
        criteria={
            "Graham Number": False, "P/E ≤ 15": True, "P/B ≤ 1.5": True,
            "P/E×P/B ≤ 22.5": True, "D/E ≤ 1.0": True, "C/R ≥ 2.0": True,
        },
        score=5, max_score=6, label="Overvalued", errors=[],
    )
    defaults.update(kwargs)
    return GrahamReport(**defaults)


class TestSummaryCSV:
    def _parse_summary(self, reports, fmt="google") -> list[dict]:
        path = "/tmp/test_summary.csv"
        summary(reports, path, fmt=fmt)
        sep = FORMATS[fmt].separator
        with open(path, encoding=FORMATS[fmt].encoding) as f:
            return list(csv.DictReader(f, delimiter=sep))

    def test_one_row_per_report(self):
        rows = self._parse_summary([_make_report(), _make_report(ticker="VALE3")])
        assert len(rows) == 2

    def test_ticker_column(self):
        rows = self._parse_summary([_make_report(ticker="PETR4")])
        assert rows[0]["Ticker"] == "PETR4"

    def test_sell_signal_column_present(self):
        rows = self._parse_summary([_make_report()])
        assert "Sell Signal" in rows[0]

    def test_sell_signal_yes_when_price_above_gn(self):
        # margin_of_safety < 0 → price > GN → sell = True
        rows = self._parse_summary([_make_report(margin_of_safety=-0.1)])
        assert rows[0]["Sell Signal"] == "YES"

    def test_sell_signal_no_when_price_below_gn(self):
        rows = self._parse_summary([_make_report(margin_of_safety=0.43)])
        assert rows[0]["Sell Signal"] == "NO"

    def test_sell_signal_unknown_when_no_gn(self):
        rows = self._parse_summary([_make_report(graham_number=None, margin_of_safety=None)])
        assert rows[0]["Sell Signal"] == "?"

    def test_numbers_format_uses_comma_separator(self):
        path = "/tmp/test_summary_numbers.csv"
        summary([_make_report()], path, fmt="numbers")
        with open(path, encoding="utf-8") as f:
            header = f.readline()
        assert "," in header
        assert ";" not in header


class TestDetailCSV:
    def _parse_detail(self, report) -> list[dict]:
        path = "/tmp/test_detail.csv"
        detail([report], path, fmt="google")
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))

    def test_contains_company_info_section(self):
        rows = self._parse_detail(_make_report())
        sections = {r["Section"] for r in rows}
        assert "Company Info" in sections

    def test_contains_graham_score_section(self):
        rows = self._parse_detail(_make_report())
        sections = {r["Section"] for r in rows}
        assert "Graham Score" in sections

    def test_sell_signal_in_detail(self):
        rows = self._parse_detail(_make_report(margin_of_safety=-0.1))
        sell_row = next(
            (r for r in rows if r["Field"] == "Sell Signal"), None
        )
        assert sell_row is not None
        assert sell_row["Value"] == "YES"

    def test_sell_signal_note_present(self):
        rows = self._parse_detail(_make_report(margin_of_safety=-0.1))
        sell_row = next(r for r in rows if r["Field"] == "Sell Signal")
        assert "Graham Number" in sell_row["Notes"]
