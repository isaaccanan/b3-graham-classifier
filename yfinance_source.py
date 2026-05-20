"""
Yahoo Finance data source for B3 stocks (cross-validation).

Uses the unofficial yfinance library. Tickers require the .SA suffix
on Yahoo Finance (e.g. PETR4 → PETR4.SA).

Note: yfinance returns debtToEquity as a percentage value
(e.g. 45.2 means D/E ratio = 0.452). Divided by 100 on ingest
to match the ratio format used by all other sources.

Daily cache — same cadence as Brapi and Fundamentus.
"""

from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass
from datetime import date
from typing import Optional

import yfinance as yf

_CACHE_DIR = pathlib.Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)


@dataclass
class YFinanceQuote:
    ticker: str
    price: Optional[float] = None
    eps: Optional[float] = None
    bvps: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    current_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None


def fetch(ticker: str) -> YFinanceQuote:
    """Return fundamentals for a B3 ticker from Yahoo Finance."""
    quote = YFinanceQuote(ticker=ticker)

    cached = _load_cache(ticker)
    if cached is not None:
        return _from_dict(ticker, cached)

    try:
        info = yf.Ticker(f"{ticker}.SA").info or {}

        if not (_f(info, "currentPrice") or _f(info, "regularMarketPrice")):
            _save_cache(ticker, {})
            return quote

        quote.price         = _f(info, "currentPrice") or _f(info, "regularMarketPrice")
        quote.eps           = _f(info, "trailingEps")
        quote.bvps          = _f(info, "bookValue")
        quote.pe            = _f(info, "trailingPE")
        quote.pb            = _f(info, "priceToBook")
        quote.current_ratio = _f(info, "currentRatio")

        de_raw = _f(info, "debtToEquity")
        quote.debt_to_equity = de_raw / 100.0 if de_raw is not None else None

        _save_cache(ticker, _to_dict(quote))
    except Exception:
        pass

    return quote


def flush_cache(tickers: list[str]) -> list[str]:
    """Delete today's cached files. Returns tickers whose cache was removed."""
    flushed = []
    for ticker in tickers:
        path = _cache_path(ticker)
        if path.exists():
            path.unlink()
            flushed.append(ticker)
    return flushed


# ── cache ─────────────────────────────────────────────────────────────────────

def _cache_path(ticker: str) -> pathlib.Path:
    return _CACHE_DIR / f"{ticker}_yfinance_{date.today()}.json"


def _load_cache(ticker: str) -> Optional[dict]:
    path = _cache_path(ticker)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(ticker: str, data: dict) -> None:
    _cache_path(ticker).write_text(json.dumps(data))


def _to_dict(q: YFinanceQuote) -> dict:
    fields = ("price", "eps", "bvps", "pe", "pb", "current_ratio", "debt_to_equity")
    return {f: getattr(q, f) for f in fields}


def _from_dict(ticker: str, d: dict) -> YFinanceQuote:
    fields = ("price", "eps", "bvps", "pe", "pb", "current_ratio", "debt_to_equity")
    return YFinanceQuote(ticker=ticker, **{k: d.get(k) for k in fields})


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(obj: dict, key: str) -> Optional[float]:
    val = obj.get(key)
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None
