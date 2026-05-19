"""
IPCA fetcher — Brazil's official inflation index.

Source: Banco Central do Brasil (BCB) open data API.
  Series 13522 — IPCA accumulated over the last 12 months (%).
  No authentication required.

Published monthly by IBGE (~9th of the following month).
Cache key is per-month so the rate is refreshed once a month.
Falls back to IPCA_RATE from config.py if the API is unreachable.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date
from typing import Optional

import requests

from config import IPCA_RATE as _FALLBACK_RATE

_URL     = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados/ultimos/1?formato=json"
_HEADERS = {"User-Agent": "b3-graham-classifier/1.0", "Accept": "application/json"}
_TIMEOUT = 10

_CACHE_DIR = pathlib.Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)


def fetch_rate() -> float:
    """Return the latest 12-month accumulated IPCA rate as a decimal (e.g. 0.0439).

    Uses a monthly cache — the BCB publishes a new value once per month.
    Returns the fallback from config.py if the API is unreachable.
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        pct = float(data[0]["valor"])   # e.g. 4.39 (percent)
        rate = pct / 100.0              # → 0.0439
    except Exception:
        return _FALLBACK_RATE

    _save_cache(rate)
    return rate


# ── cache (monthly) ───────────────────────────────────────────────────────────

def _month_key() -> str:
    today = date.today()
    return f"{today.year}M{today.month:02d}"


def _cache_path() -> pathlib.Path:
    return _CACHE_DIR / f"ipca_{_month_key()}.json"


def _load_cache() -> Optional[float]:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if isinstance(data, (int, float)):
            return float(data)
        return None
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(rate: float) -> None:
    _cache_path().write_text(json.dumps(rate))


def flush_cache() -> bool:
    """Delete this month's IPCA cache. Returns True if a file was removed."""
    path = _cache_path()
    if path.exists():
        path.unlink()
        return True
    return False
