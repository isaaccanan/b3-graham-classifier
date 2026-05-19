"""
Graham valuation classifier — produces the full analysis table.

Matches the layout the user described:
  Company Info | Financial Inputs (TTM) | Valuation Metrics
  Dividend History | Inflation Adjustments (IPCA)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from brapi import RawQuote
from config import CR_MIN, DE_MAX, DIVIDEND_YEARS, PE_MAX, PB_MAX, PEPB_MAX
import ipca as _ipca_module


@dataclass
class DividendYear:
    year: int
    paid: float
    payout_ratio: Optional[float]


@dataclass
class GrahamReport:
    # Company info
    ticker: str
    company_name: str
    sector: str

    # Financial inputs (TTM)
    price: Optional[float]
    eps: Optional[float]
    bvps: Optional[float]
    total_assets_m: Optional[float]       # millions R$
    total_liabilities_m: Optional[float]
    current_assets_m: Optional[float]
    current_liabilities_m: Optional[float]
    shares_outstanding_m: Optional[float]
    last_updated: str

    # Valuation metrics
    pe: Optional[float]
    pb: Optional[float]
    current_ratio: Optional[float]
    graham_number: Optional[float]
    intrinsic_value: Optional[float]      # = graham_number (base estimate)
    margin_of_safety: Optional[float]     # (GN - price) / GN
    min_investment: Optional[float]       # price × 100 (B3 standard lot)

    # Dividend history
    dividend_history: list[DividendYear] = field(default_factory=list)
    avg_div_yield_3y: Optional[float] = None

    # Inflation adjustments (IPCA)
    ipca_rate: float = 0.0
    real_earnings_yield: Optional[float] = None   # EPS/price - IPCA
    adjusted_graham_number: Optional[float] = None  # GN × (1 + IPCA)

    # Graham criteria pass/fail
    criteria: dict[str, Optional[bool]] = field(default_factory=dict)
    score: int = 0
    max_score: int = 0
    label: str = "N/A"

    # Raw errors from the API
    errors: list[str] = field(default_factory=list)

    @property
    def sell_signal(self) -> Optional[bool]:
        """True when price ≥ Graham Number (margin of safety ≤ 0%)."""
        if self.margin_of_safety is None:
            return None
        return self.margin_of_safety <= 0


LABEL_ORDER = ["Strong Buy", "Buy", "Hold", "Overvalued", "Avoid", "Inconclusive", "Insufficient Data"]

_B3_LOT = 100  # standard lot size (lote padrão) on B3 for all equities


def classify(q: RawQuote) -> GrahamReport:
    ipca_rate = _ipca_module.fetch_rate()

    gn = _graham_number(q.eps, q.bvps)
    mos = (gn - q.price) / gn if (gn and q.price) else None

    pe = q.pe or (q.price / q.eps if q.price and q.eps else None)
    pb = q.pb or (q.price / q.bvps if q.price and q.bvps else None)
    cr = q.current_ratio or (
        q.current_assets / q.current_liabilities
        if q.current_assets and q.current_liabilities else None
    )
    de = _debt_equity(q)

    adj_gn = gn * (1 + ipca_rate) if gn else None
    real_ey = (q.eps / q.price - ipca_rate) if (q.eps and q.price) else None

    div_history, avg_yield = _dividend_summary(q)
    min_investment = q.price * _B3_LOT if q.price else None

    # ── criteria ──────────────────────────────────────────────────────────────
    pepb = (pe * pb) if (pe and pb) else None
    criteria = {
        "Graham Number":  _pass(q.price < gn if (q.price and gn) else None),
        "P/E ≤ 15":       _pass(pe <= PE_MAX if pe else None),
        "P/B ≤ 1.5":      _pass(pb <= PB_MAX if pb else None),
        "P/E×P/B ≤ 22.5": _pass(pepb <= PEPB_MAX if pepb else None),
        "D/E ≤ 1.0":      _pass(de <= DE_MAX if de else None),
        "C/R ≥ 2.0":      _pass(cr >= CR_MIN if cr else None),
    }

    scored = [v for v in criteria.values() if v is not None]
    score = sum(1 for v in scored if v)
    max_score = len(scored)
    label = _label(score, max_score, criteria.get("Graham Number"), gn)

    to_m = 1_000_000
    return GrahamReport(
        ticker=q.symbol,
        company_name=q.company_name,
        sector=q.sector,
        price=q.price,
        eps=q.eps,
        bvps=q.bvps,
        total_assets_m=q.total_assets / to_m if q.total_assets else None,
        total_liabilities_m=q.total_liabilities / to_m if q.total_liabilities else None,
        current_assets_m=q.current_assets / to_m if q.current_assets else None,
        current_liabilities_m=q.current_liabilities / to_m if q.current_liabilities else None,
        shares_outstanding_m=q.shares_outstanding / to_m if q.shares_outstanding else None,
        last_updated=datetime.today().strftime("%Y-%m-%d"),
        pe=pe,
        pb=pb,
        current_ratio=cr,
        graham_number=gn,
        intrinsic_value=gn,
        margin_of_safety=mos,
        min_investment=min_investment,
        dividend_history=div_history,
        avg_div_yield_3y=avg_yield,
        ipca_rate=ipca_rate,
        real_earnings_yield=real_ey,
        adjusted_graham_number=adj_gn,
        criteria=criteria,
        score=score,
        max_score=max_score,
        label=label,
        errors=q.errors,
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _graham_number(eps: Optional[float], bvps: Optional[float]) -> Optional[float]:
    if eps is None or bvps is None:
        return None
    product = 22.5 * eps * bvps
    return math.sqrt(product) if product > 0 else None


def _debt_equity(q: RawQuote) -> Optional[float]:
    # Prefer the value returned directly by financialData module
    if q.debt_to_equity is not None:
        return q.debt_to_equity
    # Fallback: derive from balance sheet if available
    if q.total_assets and q.total_liabilities:
        equity = q.total_assets - q.total_liabilities
        if equity > 0:
            return q.total_liabilities / equity
    return None


def _dividend_summary(q: RawQuote) -> tuple[list[DividendYear], Optional[float]]:
    if not q.dividends or not q.price:
        return [], None

    by_year: dict[int, float] = {}
    for d in q.dividends:
        raw_date = d.get("paymentDate") or d.get("approvedOn") or ""
        try:
            year = int(str(raw_date)[:4])
        except ValueError:
            continue
        amount = float(d.get("rate") or d.get("value") or 0)
        by_year[year] = by_year.get(year, 0.0) + amount

    cutoff = datetime.today().year - DIVIDEND_YEARS
    recent = {y: v for y, v in by_year.items() if y > cutoff}

    history = []
    for year in sorted(recent.keys()):
        paid = recent[year]
        payout = paid / q.eps if q.eps and q.eps > 0 else None
        history.append(DividendYear(year=year, paid=paid, payout_ratio=payout))

    total_paid = sum(d.paid for d in history)
    avg_yield = (total_paid / DIVIDEND_YEARS) / q.price if q.price and history else None

    return history, avg_yield


def _pass(condition: Optional[bool]) -> Optional[bool]:
    return condition


def _label(score: int, max_score: int, gn_pass: Optional[bool],
           graham_number: Optional[float]) -> str:
    if max_score == 0:
        return "Insufficient Data"
    # Graham Number is the core formula — without it the analysis is incomplete
    if graham_number is None:
        return "Inconclusive"
    ratio = score / max_score
    if ratio >= 0.83 and gn_pass:
        return "Strong Buy"
    if ratio >= 0.66 and gn_pass is not False:
        return "Buy"
    if ratio >= 0.50:
        return "Hold"
    if ratio >= 0.33:
        return "Overvalued"
    return "Avoid"
