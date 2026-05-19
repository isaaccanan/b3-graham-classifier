"""Tests for cvm.py — quarter key, balance sheet parsing, M BRL conversion."""

import csv
import io
import json
import zipfile
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

import cvm
from cvm import (
    CvmQuote, _quarter_key, _parse_zip, _sum_optional,
    _build, _TICKER_TO_CVM, fetch,
)


# ── quarter key ───────────────────────────────────────────────────────────────

class TestQuarterKey:
    def _key(self, month: int) -> str:
        with patch("cvm.date") as mock_date:
            mock_date.today.return_value = date(2026, month, 15)
            return _quarter_key()

    def test_q1(self):
        assert self._key(1) == "2026Q1"
        assert self._key(3) == "2026Q1"

    def test_q2(self):
        assert self._key(4) == "2026Q2"
        assert self._key(6) == "2026Q2"

    def test_q3(self):
        assert self._key(7) == "2026Q3"
        assert self._key(9) == "2026Q3"

    def test_q4(self):
        assert self._key(10) == "2026Q4"
        assert self._key(12) == "2026Q4"


# ── _sum_optional ─────────────────────────────────────────────────────────────

class TestSumOptional:
    def test_both_values(self):
        assert _sum_optional(100.0, 200.0) == pytest.approx(300.0)

    def test_first_none(self):
        assert _sum_optional(None, 200.0) == pytest.approx(200.0)

    def test_second_none(self):
        assert _sum_optional(100.0, None) == pytest.approx(100.0)

    def test_both_none(self):
        assert _sum_optional(None, None) is None


# ── _parse_zip ────────────────────────────────────────────────────────────────

def _make_zip(bpa_rows: list[dict], bpp_rows: list[dict]) -> bytes:
    """Build a minimal in-memory ITR ZIP with BPA and BPP CSVs."""
    fieldnames = [
        "CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM",
        "GRUPO_DFP", "MOEDA", "ESCALA_MOEDA", "ORDEM_EXERC",
        "DT_FIM_EXERC", "CD_CONTA", "DS_CONTA", "VL_CONTA", "ST_CONTA_FIXA",
    ]

    def _csv_bytes(rows):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames, delimiter=";")
        w.writeheader()
        for row in rows:
            full = {f: row.get(f, "") for f in fieldnames}
            w.writerow(full)
        return buf.getvalue().encode("latin-1")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("itr_cia_aberta_BPA_con_2026.csv", _csv_bytes(bpa_rows))
        zf.writestr("itr_cia_aberta_BPP_con_2026.csv", _csv_bytes(bpp_rows))
    return buf.getvalue()


def _row(cd_cvm, cd_conta, vl_conta, ordem="ÚLTIMO", escala="MIL", dt="2026-03-31"):
    return {
        "CD_CVM": cd_cvm, "CD_CONTA": cd_conta, "VL_CONTA": str(vl_conta),
        "ORDEM_EXERC": ordem, "ESCALA_MOEDA": escala, "DT_FIM_EXERC": dt,
        "DENOM_CIA": "TEST CIA",
    }


class TestParseZip:
    CVM_CODE = "009512"

    def _zip(self, bpa=None, bpp=None):
        bpa = bpa or [
            _row(self.CVM_CODE, "1",    1_000_000),   # 1,000,000 thousand = 1,000,000 M BRL? No: 1,000,000 × 1000 / 1,000,000 = 1,000 M BRL
            _row(self.CVM_CODE, "1.01",   200_000),
        ]
        bpp = bpp or [
            _row(self.CVM_CODE, "2.01",   150_000),
            _row(self.CVM_CODE, "2.02",   600_000),
        ]
        return _make_zip(bpa, bpp)

    def test_total_assets_converted_to_millions(self):
        result = _parse_zip(self._zip(), self.CVM_CODE)
        # 1,000,000 thousands × 1000 / 1_000_000 = 1,000 M BRL
        assert result["total_assets_m"] == pytest.approx(1000.0)

    def test_current_assets(self):
        result = _parse_zip(self._zip(), self.CVM_CODE)
        assert result["current_assets_m"] == pytest.approx(200.0)

    def test_current_liabilities(self):
        result = _parse_zip(self._zip(), self.CVM_CODE)
        assert result["current_liabilities_m"] == pytest.approx(150.0)

    def test_total_liabilities_is_current_plus_noncurrent(self):
        result = _parse_zip(self._zip(), self.CVM_CODE)
        assert result["total_liabilities_m"] == pytest.approx(750.0)  # 150 + 600

    def test_unidade_scale(self):
        bpa = [_row(self.CVM_CODE, "1", 1_000_000_000, escala="UNIDADE")]
        bpp = [_row(self.CVM_CODE, "2.01", 0), _row(self.CVM_CODE, "2.02", 0)]
        result = _parse_zip(_make_zip(bpa, bpp), self.CVM_CODE)
        # 1,000,000,000 units / 1,000,000 = 1,000 M BRL
        assert result["total_assets_m"] == pytest.approx(1000.0)

    def test_ignores_penultimo(self):
        bpa = [
            _row(self.CVM_CODE, "1", 999_999, ordem="PENÚLTIMO"),
            _row(self.CVM_CODE, "1", 1_000_000, ordem="ÚLTIMO"),
        ]
        bpp = [_row(self.CVM_CODE, "2.01", 0), _row(self.CVM_CODE, "2.02", 0)]
        result = _parse_zip(_make_zip(bpa, bpp), self.CVM_CODE)
        assert result["total_assets_m"] == pytest.approx(1000.0)

    def test_ignores_other_company(self):
        bpa = [_row("999999", "1", 1_000_000)]  # different CD_CVM
        bpp = [_row("999999", "2.01", 0), _row("999999", "2.02", 0)]
        result = _parse_zip(_make_zip(bpa, bpp), self.CVM_CODE)
        assert result is None

    def test_reference_date_captured(self):
        result = _parse_zip(self._zip(), self.CVM_CODE)
        assert result["reference_date"] == "2026-03-31"


# ── ticker mapping ────────────────────────────────────────────────────────────

class TestTickerMapping:
    def test_petr4_mapped(self):
        assert "PETR4" in _TICKER_TO_CVM

    def test_vale3_mapped(self):
        assert "VALE3" in _TICKER_TO_CVM

    def test_bbas3_mapped(self):
        assert "BBAS3" in _TICKER_TO_CVM

    def test_all_values_are_six_digit_strings(self):
        for ticker, code in _TICKER_TO_CVM.items():
            assert code.isdigit(), f"{ticker} has non-digit code: {code}"
            assert len(code) == 6, f"{ticker} code not 6 digits: {code}"


# ── fetch (with mocked network) ───────────────────────────────────────────────

class TestFetch:
    def test_unknown_ticker_returns_error(self):
        q = fetch("XXXX9")
        assert q.total_assets_m is None
        assert any("no CD_CVM" in e for e in q.errors)

    def test_uses_cache_when_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cvm, "_CACHE_DIR", tmp_path)
        cached = {
            "total_assets_m": 500.0, "total_liabilities_m": 200.0,
            "current_assets_m": 100.0, "current_liabilities_m": 50.0,
            "reference_date": "2026-03-31",
        }
        cache_file = tmp_path / f"PETR4_cvm_{_quarter_key()}.json"
        cache_file.write_text(json.dumps(cached))

        q = fetch("PETR4")
        assert q.total_assets_m == pytest.approx(500.0)
        assert q.reference_date == "2026-03-31"
