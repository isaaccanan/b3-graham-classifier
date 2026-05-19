"""Tests for brapi.py — ticker validation and override guards."""

import math
import pytest

from brapi import _validate_ticker, _safe_override_float, _f


# ── ticker validation ─────────────────────────────────────────────────────────

class TestValidateTicker:
    def test_valid_4_digit(self):
        assert _validate_ticker("PETR4") == "PETR4"

    def test_valid_lowercase_normalized(self):
        assert _validate_ticker("petr4") == "PETR4"

    def test_valid_unit_suffix(self):
        assert _validate_ticker("KLBN11") == "KLBN11"

    def test_valid_f_suffix(self):
        assert _validate_ticker("PETR4F") == "PETR4F"

    def test_valid_b_suffix(self):
        assert _validate_ticker("PETR4B") == "PETR4B"

    def test_invalid_too_short(self):
        with pytest.raises(ValueError):
            _validate_ticker("PET4")

    def test_invalid_no_digits(self):
        with pytest.raises(ValueError):
            _validate_ticker("PETRO")

    def test_invalid_path_traversal(self):
        with pytest.raises(ValueError):
            _validate_ticker("../../admin")

    def test_invalid_query_injection(self):
        with pytest.raises(ValueError):
            _validate_ticker("PETR4?evil=1")

    def test_invalid_special_chars(self):
        with pytest.raises(ValueError):
            _validate_ticker("PETR4!")

    def test_invalid_empty(self):
        with pytest.raises(ValueError):
            _validate_ticker("")


# ── override value guard ──────────────────────────────────────────────────────

class TestSafeOverrideFloat:
    def test_valid_float(self):
        assert _safe_override_float(32.55, "vpa") == pytest.approx(32.55)

    def test_valid_string_float(self):
        assert _safe_override_float("32.55", "vpa") == pytest.approx(32.55)

    def test_none_returns_none(self):
        assert _safe_override_float(None, "vpa") is None

    def test_infinity_rejected(self):
        assert _safe_override_float(float("inf"), "vpa") is None

    def test_nan_rejected(self):
        assert _safe_override_float(float("nan"), "vpa") is None

    def test_negative_rejected(self):
        assert _safe_override_float(-5.0, "vpa") is None

    def test_zero_rejected(self):
        assert _safe_override_float(0.0, "vpa") is None

    def test_unreasonably_large_rejected(self):
        assert _safe_override_float(2_000_000.0, "vpa") is None

    def test_string_inf_rejected(self):
        assert _safe_override_float("inf", "vpa") is None

    def test_non_numeric_string_rejected(self):
        assert _safe_override_float("not_a_number", "vpa") is None


# ── _f helper ─────────────────────────────────────────────────────────────────

class TestFHelper:
    def test_normal_float(self):
        assert _f({"key": 3.14}, "key") == pytest.approx(3.14)

    def test_missing_key(self):
        assert _f({}, "key") is None

    def test_none_value(self):
        assert _f({"key": None}, "key") is None

    def test_nan_returns_none(self):
        assert _f({"key": float("nan")}, "key") is None

    def test_inf_returns_none(self):
        assert _f({"key": float("inf")}, "key") is None

    def test_string_number(self):
        assert _f({"key": "42.5"}, "key") == pytest.approx(42.5)

    def test_non_numeric_returns_none(self):
        assert _f({"key": "N/A"}, "key") is None
