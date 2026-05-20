"""Tests for yfinance_source.py — fetch, cache, and fallback."""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import date

import yfinance_source
from yfinance_source import fetch, flush_cache, YFinanceQuote


def _mock_info(**kwargs):
    defaults = {
        "currentPrice": 30.0,
        "trailingEps": 2.0,
        "bookValue": 15.0,
        "trailingPE": 15.0,
        "priceToBook": 2.0,
        "currentRatio": 2.5,
        "debtToEquity": 50.0,  # 50.0 → ratio 0.50
    }
    defaults.update(kwargs)
    return defaults


def _patch_ticker(info: dict):
    mock_ticker = MagicMock()
    mock_ticker.info = info
    return patch("yfinance_source.yf.Ticker", return_value=mock_ticker)


class TestFetch:
    def test_returns_quote_with_correct_values(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        with _patch_ticker(_mock_info()):
            q = fetch("PETR4")
        assert q.ticker == "PETR4"
        assert q.price == pytest.approx(30.0)
        assert q.eps == pytest.approx(2.0)
        assert q.bvps == pytest.approx(15.0)
        assert q.pe == pytest.approx(15.0)
        assert q.pb == pytest.approx(2.0)
        assert q.current_ratio == pytest.approx(2.5)

    def test_de_divided_by_100(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        with _patch_ticker(_mock_info(debtToEquity=75.0)):
            q = fetch("VALE3")
        assert q.debt_to_equity == pytest.approx(0.75)

    def test_uses_fallback_price_field(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        info = _mock_info()
        del info["currentPrice"]
        info["regularMarketPrice"] = 28.5
        with _patch_ticker(info):
            q = fetch("BBAS3")
        assert q.price == pytest.approx(28.5)

    def test_returns_empty_quote_on_missing_price(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        with _patch_ticker({}):
            q = fetch("XPTO3")
        assert q.price is None
        assert q.eps is None

    def test_returns_empty_quote_on_exception(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        with patch("yfinance_source.yf.Ticker", side_effect=Exception("network")):
            q = fetch("PETR4")
        assert q.price is None

    def test_saves_to_cache_after_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        with _patch_ticker(_mock_info()):
            fetch("PETR4")
        cache_files = list(tmp_path.glob("PETR4_yfinance_*.json"))
        assert len(cache_files) == 1

    def test_uses_cache_on_second_call(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        with _patch_ticker(_mock_info()):
            fetch("PETR4")
        with patch("yfinance_source.yf.Ticker") as mock_ticker:
            q = fetch("PETR4")
            mock_ticker.assert_not_called()
        assert q.price == pytest.approx(30.0)

    def test_none_fields_when_missing_from_info(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        info = {"currentPrice": 20.0}
        with _patch_ticker(info):
            q = fetch("CSNA3")
        assert q.price == pytest.approx(20.0)
        assert q.eps is None
        assert q.bvps is None
        assert q.debt_to_equity is None

    def test_ticker_has_sa_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        with patch("yfinance_source.yf.Ticker") as mock_cls:
            mock_cls.return_value.info = _mock_info()
            fetch("VALE3")
        mock_cls.assert_called_once_with("VALE3.SA")


class TestFlushCache:
    def test_flush_removes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        cache_file = tmp_path / f"PETR4_yfinance_{date.today()}.json"
        cache_file.write_text(json.dumps({"price": 30.0}))
        assert flush_cache(["PETR4"]) == ["PETR4"]
        assert not cache_file.exists()

    def test_flush_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(yfinance_source, "_CACHE_DIR", tmp_path)
        assert flush_cache(["VALE3"]) == []
