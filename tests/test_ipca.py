"""Tests for ipca.py — BCB rate fetch, cache, and fallback."""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import date

import ipca
from ipca import fetch_rate, _month_key, flush_cache


class TestMonthKey:
    def test_format(self):
        with patch("ipca.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 19)
            assert _month_key() == "2026M05"

    def test_single_digit_month_padded(self):
        with patch("ipca.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 15)
            assert _month_key() == "2026M01"


class TestFetchRate:
    def test_returns_float_from_api(self, tmp_path, monkeypatch, requests_mock):
        monkeypatch.setattr(ipca, "_CACHE_DIR", tmp_path)
        requests_mock.get(ipca._URL, json=[{"data": "01/04/2026", "valor": "4.39"}])
        assert fetch_rate() == pytest.approx(0.0439)

    def test_converts_percent_to_decimal(self, tmp_path, monkeypatch, requests_mock):
        monkeypatch.setattr(ipca, "_CACHE_DIR", tmp_path)
        requests_mock.get(ipca._URL, json=[{"data": "01/04/2026", "valor": "5.00"}])
        assert fetch_rate() == pytest.approx(0.05)

    def test_falls_back_on_network_error(self, tmp_path, monkeypatch, requests_mock):
        monkeypatch.setattr(ipca, "_CACHE_DIR", tmp_path)
        import requests as req
        requests_mock.get(ipca._URL, exc=req.ConnectionError)
        assert fetch_rate() == pytest.approx(ipca._FALLBACK_RATE)

    def test_falls_back_on_bad_response(self, tmp_path, monkeypatch, requests_mock):
        monkeypatch.setattr(ipca, "_CACHE_DIR", tmp_path)
        requests_mock.get(ipca._URL, status_code=500)
        assert fetch_rate() == pytest.approx(ipca._FALLBACK_RATE)

    def test_uses_cache_when_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ipca, "_CACHE_DIR", tmp_path)
        cache_file = tmp_path / f"ipca_{_month_key()}.json"
        cache_file.write_text(json.dumps(0.0512))

        with patch("ipca.requests.get") as mock_get:
            rate = fetch_rate()
            mock_get.assert_not_called()

        assert rate == pytest.approx(0.0512)

    def test_saves_to_cache_after_fetch(self, tmp_path, monkeypatch, requests_mock):
        monkeypatch.setattr(ipca, "_CACHE_DIR", tmp_path)
        requests_mock.get(ipca._URL, json=[{"data": "01/04/2026", "valor": "4.39"}])

        fetch_rate()

        cache_file = tmp_path / f"ipca_{_month_key()}.json"
        assert cache_file.exists()
        assert json.loads(cache_file.read_text()) == pytest.approx(0.0439)


class TestFlushCache:
    def test_flush_removes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ipca, "_CACHE_DIR", tmp_path)
        cache_file = tmp_path / f"ipca_{_month_key()}.json"
        cache_file.write_text(json.dumps(0.04))

        assert flush_cache() is True
        assert not cache_file.exists()

    def test_flush_returns_false_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ipca, "_CACHE_DIR", tmp_path)
        assert flush_cache() is False
