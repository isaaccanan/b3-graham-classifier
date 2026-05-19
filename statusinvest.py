"""
Status Invest scraper — tertiary data source for cross-validation.

Fetches VPA, LPA, P/L, P/VP, Cotação, D.Y and Liq. corrente from
https://statusinvest.com.br/acoes/<ticker>

No authentication required. Results are cached per calendar day.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup

_BASE_URL = "https://statusinvest.com.br/acoes"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
_TIMEOUT = 15
_CACHE_DIR = pathlib.Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)


@dataclass
class StatusInvestQuote:
    ticker: str
    price: Optional[float] = None
    lpa: Optional[float] = None           # LPA — Lucro por Ação (EPS)
    vpa: Optional[float] = None           # VPA — Valor Patrimonial por Ação (BVPS)
    pl: Optional[float] = None            # P/L (P/E)
    pvp: Optional[float] = None           # P/VP (P/B)
    div_yield: Optional[float] = None     # D.Y as a decimal (e.g. 0.068)
    current_ratio: Optional[float] = None # Liq. corrente
    sector: Optional[str] = None
    errors: list[str] = field(default_factory=list)


def fetch(ticker: str) -> StatusInvestQuote:
    """Scrape Status Invest for one ticker. Results cached per calendar day."""
    cached = _load_cache(ticker)
    if cached is not None:
        return _from_cache(cached, ticker)

    url = f"{_BASE_URL}/{ticker.lower()}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        q = StatusInvestQuote(ticker=ticker)
        q.errors.append(f"Status Invest fetch error: {exc}")
        return q

    data = _parse(resp.text)
    if not data:
        q = StatusInvestQuote(ticker=ticker)
        q.errors.append("Status Invest: could not parse page — ticker may not exist")
        return q

    _save_cache(ticker, data)
    return _build(ticker, data)


# ── parsing ───────────────────────────────────────────────────────────────────

def _parse(html: str) -> dict[str, str]:
    """Extract key indicators from Status Invest's detail page."""
    soup = BeautifulSoup(html, "html.parser")
    data: dict[str, str] = {}

    # Price: find "Valor atual" label → walk up to find strong.value
    for text_node in soup.find_all(string=lambda s: s and "Valor atual" in s):
        parent = text_node.parent
        for _ in range(6):
            if parent is None:
                break
            val_el = parent.find("strong", class_=lambda x: x and "value" in x if x else False)
            if val_el:
                data["price"] = val_el.get_text(strip=True)
                break
            parent = parent.parent
        if "price" in data:
            break

    # Per-indicator fields via h3.title labels
    _LABEL_MAP = {
        "VPA": "vpa",
        "LPA": "lpa",
        "P/L": "pl",
        "P/VP": "pvp",
        "D.Y": "div_yield",
        "Liq. corrente": "current_ratio",
    }
    for h3 in soup.find_all("h3", class_="title"):
        label = h3.get_text(strip=True)
        key = _LABEL_MAP.get(label)
        if key and key not in data:
            parent = h3.parent
            for _ in range(6):
                if parent is None:
                    break
                val_el = parent.find("strong", class_=lambda x: x and "value" in x if x else False)
                if val_el:
                    data[key] = val_el.get_text(strip=True)
                    break
                parent = parent.parent

    # Sector: "Setor de Atuação" text → next sibling (strip icon text)
    for text_node in soup.find_all(string=lambda s: s and "Setor de Atuação" in s):
        ns = text_node.parent.find_next_sibling()
        if ns:
            raw = ns.get_text(strip=True)
            data["sector"] = re.sub(r"arrow_forward.*", "", raw).strip()
        break

    return data


def _build(ticker: str, d: dict[str, str]) -> StatusInvestQuote:
    q = StatusInvestQuote(ticker=ticker)
    q.price         = _parse_br_float(d.get("price"))
    q.lpa           = _parse_br_float(d.get("lpa"))
    q.vpa           = _parse_br_float(d.get("vpa"))
    q.pl            = _parse_br_float(d.get("pl"))
    q.pvp           = _parse_br_float(d.get("pvp"))
    q.current_ratio = _parse_br_float(d.get("current_ratio"))
    q.sector        = d.get("sector")
    raw_dy = _parse_br_float(d.get("div_yield"))
    q.div_yield = raw_dy / 100 if raw_dy is not None else None
    return q


def _from_cache(data: dict, ticker: str) -> StatusInvestQuote:
    return _build(ticker, data)


# ── cache ─────────────────────────────────────────────────────────────────────

def _cache_path(ticker: str) -> pathlib.Path:
    return _CACHE_DIR / f"{ticker}_statusinvest_{date.today()}.json"


def _load_cache(ticker: str) -> Optional[dict]:
    path = _cache_path(ticker)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None
    return None


def _save_cache(ticker: str, data: dict) -> None:
    _cache_path(ticker).write_text(json.dumps(data))


def flush_cache(tickers: list[str]) -> list[str]:
    """Delete today's Status Invest cached files for the given tickers."""
    flushed = []
    for ticker in tickers:
        path = _cache_path(ticker)
        if path.exists():
            path.unlink()
            flushed.append(ticker)
    return flushed


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_br_float(value: Optional[str]) -> Optional[float]:
    """Convert Brazilian number format (1.234,56 or 1.234,56%) to float."""
    if not value or value == "-":
        return None
    try:
        cleaned = value.replace(".", "").replace(",", ".").replace("%", "").strip()
        return float(cleaned)
    except ValueError:
        return None
