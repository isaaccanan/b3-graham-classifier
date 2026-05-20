"""Tests for exporter.py — CSV format, helpers, sell signal, and formula export."""

import csv
import io
import pytest
from unittest.mock import patch

from exporter import (
    _r, _pct, _yn, _rv, _formula_row, _FORMULA_HEADERS,
    summary, detail, summary_formulas, format_description, FORMATS,
)
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
        min_investment=4600.0,    # 46.0 × 100 B3 standard lot
        debt_to_equity=0.45,
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


class TestFormulaExport:
    """Validates the google-formulas export — structure, cell types, and formula correctness."""

    def _parse(self, reports) -> tuple[list, list[dict]]:
        """Returns (raw_rows, dict_rows) from the formula CSV."""
        path = "/tmp/test_formulas.csv"
        summary_formulas(reports, path)
        with open(path, encoding="utf-8-sig") as f:
            raw = list(csv.reader(f, delimiter=";"))
        with open(path, encoding="utf-8-sig") as f:
            dicts = list(csv.DictReader(f, delimiter=";"))
        return raw, dicts

    # ── structure ─────────────────────────────────────────────────────────────

    def test_header_count_matches_formula_headers(self):
        raw, _ = self._parse([_make_report()])
        assert len(raw[0]) == len(_FORMULA_HEADERS)

    def test_one_data_row_per_report(self):
        raw, _ = self._parse([_make_report(), _make_report(ticker="VALE3")])
        assert len(raw) == 3  # 1 header + 2 data

    def test_data_row_column_count_matches_header(self):
        raw, _ = self._parse([_make_report()])
        assert len(raw[1]) == len(raw[0])

    def test_file_uses_semicolon_separator(self):
        path = "/tmp/test_formulas_sep.csv"
        summary_formulas([_make_report()], path)
        with open(path, encoding="utf-8-sig") as f:
            first_line = f.readline()
        assert ";" in first_line

    def test_file_has_utf8_bom(self):
        path = "/tmp/test_formulas_bom.csv"
        summary_formulas([_make_report()], path)
        with open(path, "rb") as f:
            assert f.read(3) == b"\xef\xbb\xbf"

    # ── input columns are plain values ────────────────────────────────────────

    def test_ticker_is_plain_value(self):
        _, rows = self._parse([_make_report(ticker="PETR4")])
        assert rows[0]["Ticker"] == "PETR4"

    def test_price_is_plain_number(self):
        _, rows = self._parse([_make_report(price=42.5)])
        assert not rows[0]["Price (R$)"].startswith("=")
        assert float(rows[0]["Price (R$)"]) == pytest.approx(42.5)

    def test_eps_is_plain_number(self):
        _, rows = self._parse([_make_report(eps=3.14)])
        assert not rows[0]["EPS (R$)"].startswith("=")

    def test_bvps_is_plain_number(self):
        _, rows = self._parse([_make_report(bvps=12.0)])
        assert not rows[0]["BVPS (R$)"].startswith("=")

    def test_missing_eps_is_blank(self):
        _, rows = self._parse([_make_report(eps=None)])
        assert rows[0]["EPS (R$)"] == ""

    def test_missing_bvps_is_blank(self):
        _, rows = self._parse([_make_report(bvps=None)])
        assert rows[0]["BVPS (R$)"] == ""

    def test_missing_current_ratio_is_blank(self):
        _, rows = self._parse([_make_report(current_ratio=None)])
        assert rows[0]["Current Ratio"] == ""

    def test_missing_de_is_blank(self):
        _, rows = self._parse([_make_report(debt_to_equity=None)])
        assert rows[0]["D/E"] == ""

    # ── formula columns start with = ──────────────────────────────────────────

    def test_graham_number_is_formula(self):
        _, rows = self._parse([_make_report()])
        assert rows[0]["Graham Number (R$)"].startswith("=")

    def test_margin_of_safety_is_formula(self):
        _, rows = self._parse([_make_report()])
        assert rows[0]["Margin of Safety"].startswith("=")

    def test_adj_graham_number_is_formula(self):
        _, rows = self._parse([_make_report()])
        assert rows[0]["Adj. Graham Number (R$)"].startswith("=")

    def test_min_investment_is_formula(self):
        _, rows = self._parse([_make_report()])
        assert rows[0]["Min. Investment (R$)"].startswith("=")

    def test_all_criteria_are_formulas(self):
        _, rows = self._parse([_make_report()])
        for col in ("GN Pass", "PE Pass", "PB Pass", "PEPB Pass", "DE Pass", "CR Pass"):
            assert rows[0][col].startswith("="), f"{col} is not a formula"

    def test_score_is_formula(self):
        _, rows = self._parse([_make_report()])
        assert rows[0]["Score"].startswith("=")

    def test_label_is_formula(self):
        _, rows = self._parse([_make_report()])
        assert rows[0]["Label"].startswith("=")

    def test_sell_signal_is_formula(self):
        _, rows = self._parse([_make_report()])
        assert rows[0]["Sell Signal"].startswith("=")

    # ── formula correctness ───────────────────────────────────────────────────

    def test_graham_number_formula_uses_semicolons(self):
        _, rows = self._parse([_make_report()])
        gn = rows[0]["Graham Number (R$)"]
        assert ";" in gn

    def test_graham_number_formula_references_f_and_g(self):
        _, rows = self._parse([_make_report()])
        gn = rows[0]["Graham Number (R$)"]
        assert "F2" in gn and "G2" in gn

    def test_graham_number_formula_contains_sqrt_22_5(self):
        _, rows = self._parse([_make_report()])
        gn = rows[0]["Graham Number (R$)"]
        assert "SQRT(22.5" in gn

    def test_margin_of_safety_references_q_and_e(self):
        _, rows = self._parse([_make_report()])
        mos = rows[0]["Margin of Safety"]
        assert "Q2" in mos and "E2" in mos

    def test_pe_pass_threshold_is_15(self):
        _, rows = self._parse([_make_report()])
        assert "<=15" in rows[0]["PE Pass"]

    def test_pb_pass_threshold_is_1_5(self):
        _, rows = self._parse([_make_report()])
        assert "<=1.5" in rows[0]["PB Pass"]

    def test_de_pass_threshold_is_1(self):
        _, rows = self._parse([_make_report()])
        assert "<=1" in rows[0]["DE Pass"]

    def test_cr_pass_threshold_is_2(self):
        _, rows = self._parse([_make_report()])
        assert ">=2" in rows[0]["CR Pass"]

    def test_score_formula_counts_yes_and_unknowns(self):
        _, rows = self._parse([_make_report()])
        score = rows[0]["Score"]
        assert 'COUNTIF' in score
        assert '"YES"' in score
        assert '"?"' in score

    def test_sell_signal_references_margin_of_safety_column(self):
        _, rows = self._parse([_make_report()])
        assert "R2" in rows[0]["Sell Signal"]

    def test_label_contains_all_graham_labels(self):
        _, rows = self._parse([_make_report()])
        label = rows[0]["Label"]
        for lbl in ("Strong Buy", "Buy", "Hold", "Overvalued", "Avoid",
                    "Inconclusive", "Insufficient Data"):
            assert lbl in label, f"Label formula missing: {lbl}"

    # ── row numbers increment correctly ───────────────────────────────────────

    def test_second_row_uses_row_3_references(self):
        raw, _ = self._parse([_make_report(), _make_report(ticker="VALE3")])
        # row index 2 = third CSV line (row 1 header, row 2 first data, row 3 second data)
        second_data = raw[2]
        gn_formula = second_data[_FORMULA_HEADERS.index("Graham Number (R$)")]
        assert "F3" in gn_formula and "G3" in gn_formula

    def test_row_references_do_not_bleed_between_rows(self):
        raw, _ = self._parse([_make_report(), _make_report(ticker="VALE3")])
        first_gn  = raw[1][_FORMULA_HEADERS.index("Graham Number (R$)")]
        second_gn = raw[2][_FORMULA_HEADERS.index("Graham Number (R$)")]
        assert "F2" in first_gn  and "F3" not in first_gn
        assert "F3" in second_gn and "F2" not in second_gn

    # ── _rv helper ────────────────────────────────────────────────────────────

    def test_rv_none_returns_empty(self):
        assert _rv(None) == ""

    def test_rv_float_returns_string(self):
        assert _rv(42.5) == "42.5"

    def test_rv_small_float_no_scientific_notation(self):
        result = _rv(0.0439)
        assert "e" not in result.lower()
        assert float(result) == pytest.approx(0.0439)


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
