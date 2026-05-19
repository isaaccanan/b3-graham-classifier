"""
Brapi REST client.

Docs: https://brapi.dev/docs
Rate limits and usage rules apply per your plan.
"""

from __future__ import annotations

import json
import math
import pathlib
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import requests

_TICKER_RE = re.compile(r'^[A-Z]{4}[0-9]{1,2}[BF]?$')


def _validate_ticker(ticker: str) -> str:
    """Raise ValueError if ticker doesn't match B3 format (e.g. PETR4, BBAS3, BOVA11)."""
    if not _TICKER_RE.match(ticker.upper()):
        raise ValueError(f"Invalid ticker format: {ticker!r}")
    return ticker.upper()

from config import BRAPI_BASE_URL, BRAPI_TOKEN

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "b3-graham-classifier/1.0"})

_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = 2.0  # seconds

_CACHE_DIR = pathlib.Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(ticker: str) -> pathlib.Path:
    return _CACHE_DIR / f"{ticker}_{date.today()}.json"


def _load_cache(ticker: str) -> Optional[dict]:
    path = _cache_path(ticker)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(ticker: str, data: dict) -> None:
    _cache_path(ticker).write_text(json.dumps(data))


def flush_cache(tickers: list[str]) -> list[str]:
    """Delete today's cached files for the given tickers.
    Returns the list of tickers whose cache was actually removed.
    """
    flushed = []
    for ticker in tickers:
        path = _cache_path(ticker)
        if path.exists():
            path.unlink()
            flushed.append(ticker)
    return flushed


_OVERRIDES_PATH = pathlib.Path(__file__).parent / "overrides.json"


def _load_overrides() -> dict:
    if not _OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(_OVERRIDES_PATH.read_text())
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except (json.JSONDecodeError, OSError):
        return {}


def _safe_override_float(value: Any, name: str) -> Optional[float]:
    """Parse and validate an override float — must be finite and positive."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f <= 0 or f > 1_000_000:
        return None
    return f


def _apply_overrides(quote: RawQuote) -> None:
    """Fill missing fields from overrides.json using VPA/LPA terminology."""
    overrides = _load_overrides()
    entry = overrides.get(quote.symbol.upper())
    if not entry:
        return
    if quote.bvps is None:
        quote.bvps = _safe_override_float(entry.get("vpa"), "vpa")
    if quote.eps is None:
        quote.eps = _safe_override_float(entry.get("lpa"), "lpa")


def validate_tickers(tickers: list[str]) -> tuple[list[str], list[str]]:
    """Check tickers against Brapi's /api/quote/list endpoint.

    Returns (valid, invalid) — invalid tickers are skipped before any
    expensive quote fetch is attempted.
    """
    valid, invalid = [], []
    for ticker in tickers:
        try:
            ticker = _validate_ticker(ticker)
        except ValueError:
            invalid.append(ticker)
            continue
        try:
            resp = _SESSION.get(
                f"{BRAPI_BASE_URL}/quote/list",
                params={"token": BRAPI_TOKEN, "search": ticker, "limit": 5},
                timeout=10,
            )
            if not resp.ok:
                # Can't validate (plan restriction) — assume valid, let fetch decide
                valid.append(ticker)
                continue
            stocks = resp.json().get("stocks") or []
            matched = any(s.get("stock", "").upper() == ticker.upper() for s in stocks)
            (valid if matched else invalid).append(ticker)
        except requests.RequestException:
            valid.append(ticker)  # network error — don't discard, let fetch decide
    return valid, invalid


@dataclass
class RawQuote:
    symbol: str
    company_name: str = ""
    sector: str = ""
    price: Optional[float] = None
    eps: Optional[float] = None
    bvps: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    current_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    shares_outstanding: Optional[float] = None
    dividends: list[dict] = field(default_factory=list)
    # Reference timestamps
    price_updated_at: Optional[str] = None    # last market price timestamp
    balance_updated_at: Optional[str] = None  # most recent balance sheet quarter
    errors: list[str] = field(default_factory=list)


_MODULES_FULL = "financialData,defaultKeyStatistics,balanceSheetHistory,summaryProfile"
_MODULES_LITE = "summaryProfile"


def fetch_quote(ticker: str) -> RawQuote:
    """Fetch fundamentals + dividends for one B3 ticker.

    Tries the full modules request first. Falls back to a lightweight request
    (summaryProfile only) for financial-sector tickers where the heavy modules
    are not supported by Brapi (returns 400).

    Results are cached locally for the current calendar day.
    """
    ticker = _validate_ticker(ticker)
    quote = RawQuote(symbol=ticker)

    data = _load_cache(ticker)
    if data is None:
        url = f"{BRAPI_BASE_URL}/quote/{ticker}"

        data = _get(url, {"token": BRAPI_TOKEN, "modules": _MODULES_FULL, "dividends": "true"}, quote)

        if data is None and any("400" in e for e in quote.errors):
            # Heavy modules unsupported (e.g. banks) — retry lite + dividends
            quote.errors.clear()
            data = _get(url, {"token": BRAPI_TOKEN, "modules": _MODULES_LITE, "dividends": "true"}, quote)

        if data is None and any("403" in e for e in quote.errors):
            # Dividends endpoint not available on current plan — retry without
            quote.errors.clear()
            data = _get(url, {"token": BRAPI_TOKEN, "modules": _MODULES_LITE}, quote)

        if data is not None:
            _save_cache(ticker, data)

    if data is None:
        return quote

    results = data.get("results", [])
    if not results:
        quote.errors.append("Empty results from Brapi")
        return quote

    r = results[0]

    # ── company info ──────────────────────────────────────────────────────────
    profile = r.get("summaryProfile") or {}
    quote.company_name = r.get("longName") or r.get("shortName") or ""
    quote.sector = profile.get("sector") or r.get("sector") or ""

    # ── reference timestamps ──────────────────────────────────────────────────
    raw_time = r.get("regularMarketTime")
    if raw_time:
        quote.price_updated_at = str(raw_time)[:10]  # keep date part only

    # ── price & basic ratios (default response) ───────────────────────────────
    quote.price = _f(r, "regularMarketPrice")
    quote.pe = _f(r, "priceEarnings")

    # ── defaultKeyStatistics ──────────────────────────────────────────────────
    stats = r.get("defaultKeyStatistics") or {}
    balance_date = stats.get("mostRecentQuarter") or stats.get("lastFiscalYearEnd")
    if balance_date:
        quote.balance_updated_at = str(balance_date)[:10]
    quote.eps = _f(stats, "trailingEps") or _f(r, "earningsPerShare") or _f(r, "eps")
    quote.bvps = _f(stats, "bookValue") or _f(r, "bookValue")
    quote.pb = _f(stats, "priceToBook")
    shares = _f(stats, "sharesOutstanding") or _f(stats, "floatShares")
    # fallback: derive shares from marketCap / price
    if shares is None:
        mktcap = _f(r, "marketCap")
        if mktcap and quote.price:
            shares = mktcap / quote.price
    quote.shares_outstanding = shares

    # ── financialData ─────────────────────────────────────────────────────────
    fin = r.get("financialData") or {}
    quote.current_ratio = _f(fin, "currentRatio")
    quote.debt_to_equity = _f(fin, "debtToEquity")  # already a ratio, not a percentage

    # ── balanceSheetHistory (most recent yearly entry) ────────────────────────
    bal_history = r.get("balanceSheetHistory") or {}
    statements = bal_history if isinstance(bal_history, list) else (
        bal_history.get("balanceSheetStatements") or []
    )
    bal = statements[0] if statements else {}

    quote.total_assets = _f(bal, "totalAssets")
    quote.total_liabilities = _f(bal, "totalLiab") or _f(bal, "totalLiabilities")
    quote.current_assets = _f(bal, "totalCurrentAssets")
    # Brapi uses "currentLiabilities" (not "totalCurrentLiabilities") in B3 statements
    quote.current_liabilities = (
        _f(bal, "currentLiabilities") or _f(bal, "totalCurrentLiabilities")
    )

    # fallback P/B if not in stats
    if quote.pb is None and quote.price and quote.bvps and quote.bvps > 0:
        quote.pb = quote.price / quote.bvps

    # ── dividends ─────────────────────────────────────────────────────────────
    div_data = r.get("dividendsData") or {}
    quote.dividends = div_data.get("cashDividends") or []

    _apply_overrides(quote)
    return quote


def _get(url: str, params: dict, quote: RawQuote) -> Optional[dict[str, Any]]:
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            resp = _SESSION.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                wait = _RETRY_BACKOFF * (attempt + 1)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == _RETRY_ATTEMPTS - 1:
                quote.errors.append(f"HTTP error: {exc}")
    return None


def _f(obj: dict, key: str) -> Optional[float]:
    val = obj.get(key)
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None
