"""
Fundamentus scraper — secondary data source for cross-validation.

Fetches VPA, LPA, P/L, P/VP, Cotação, Div. Yield and sector
from https://fundamentus.com.br/detalhes.php?papel=<TICKER>

No authentication required. Respect the site — results are cached
for the same calendar day alongside Brapi cache.
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

_BASE_URL = "https://fundamentus.com.br/detalhes.php"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; b3-graham-classifier/1.0)"}
_TIMEOUT = 15
_CACHE_DIR = pathlib.Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)


@dataclass
class FundamentusQuote:
    ticker: str
    price: Optional[float] = None
    lpa: Optional[float] = None       # Lucro por Ação (EPS)
    vpa: Optional[float] = None       # Valor Patrimonial por Ação (BVPS)
    pl: Optional[float] = None        # P/L (P/E)
    pvp: Optional[float] = None       # P/VP (P/B)
    div_yield: Optional[float] = None
    sector: Optional[str] = None
    balance_updated_at: Optional[str] = None  # Últ balanço processado → YYYY-MM-DD
    errors: list[str] = field(default_factory=list)


def fetch(ticker: str) -> FundamentusQuote:
    """Scrape Fundamentus for one ticker. Results cached per calendar day."""
    quote = FundamentusQuote(ticker=ticker)

    cached = _load_cache(ticker)
    if cached is not None:
        return _from_cache(cached, ticker)

    try:
        resp = requests.get(
            _BASE_URL,
            params={"papel": ticker},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        quote.errors.append(f"Fundamentus fetch error: {exc}")
        return quote

    metrics = _parse(resp.text)
    if not metrics:
        quote.errors.append("Fundamentus: could not parse page — ticker may not exist")
        return quote

    _save_cache(ticker, metrics)
    return _build(ticker, metrics)


# ── parsing ───────────────────────────────────────────────────────────────────

def _parse(html: str) -> dict[str, str]:
    """Extract all label→value pairs from the Fundamentus detail page."""
    soup = BeautifulSoup(html, "html.parser")
    metrics: dict[str, str] = {}

    rows = soup.find_all("td", class_="label")
    for label_td in rows:
        label_span = label_td.find("span", class_="txt")
        if not label_span:
            continue
        label = label_span.get_text(strip=True)

        value_td = label_td.find_next_sibling("td")
        if not value_td:
            continue
        value_span = value_td.find("span", class_="txt")
        value = value_span.get_text(strip=True) if value_span else value_td.get_text(strip=True)

        if label and value:
            metrics[label] = value

    return metrics


def _build(ticker: str, m: dict[str, str]) -> FundamentusQuote:
    q = FundamentusQuote(ticker=ticker)
    q.price = _parse_float(m.get("Cotação"))
    q.lpa = _parse_float(m.get("LPA"))
    q.vpa = _parse_float(m.get("VPA"))
    q.pl = _parse_float(m.get("P/L"))
    q.pvp = _parse_float(m.get("P/VP"))
    q.div_yield = _parse_pct(m.get("Div. Yield"))
    q.sector = m.get("Setor") or m.get("Subsetor")
    q.balance_updated_at = _parse_date_br(m.get("Últ balanço processado"))
    return q


def _from_cache(data: dict, ticker: str) -> FundamentusQuote:
    return _build(ticker, data)


# ── cache ─────────────────────────────────────────────────────────────────────

def _cache_path(ticker: str) -> pathlib.Path:
    return _CACHE_DIR / f"{ticker}_fundamentus_{date.today()}.json"


def _load_cache(ticker: str) -> Optional[dict]:
    path = _cache_path(ticker)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
    return None


def _save_cache(ticker: str, metrics: dict) -> None:
    _cache_path(ticker).write_text(json.dumps(metrics))


def flush_cache(tickers: list[str]) -> list[str]:
    """Delete today's Fundamentus cached files for the given tickers."""
    flushed = []
    for ticker in tickers:
        path = _cache_path(ticker)
        if path.exists():
            path.unlink()
            flushed.append(ticker)
    return flushed


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_float(value: Optional[str]) -> Optional[float]:
    """Convert Brazilian number format (1.234,56) to float."""
    if not value:
        return None
    try:
        cleaned = value.replace(".", "").replace(",", ".").replace("%", "").strip()
        return float(cleaned)
    except ValueError:
        return None


def _parse_pct(value: Optional[str]) -> Optional[float]:
    """Convert '6,80%' → 0.068"""
    f = _parse_float(value)
    return f / 100 if f is not None else None


def _parse_date_br(value: Optional[str]) -> Optional[str]:
    """Convert Brazilian date '31/03/2026' → ISO '2026-03-31'."""
    if not value:
        return None
    parts = value.strip().split("/")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return value
