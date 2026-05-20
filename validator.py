"""
Cross-validation layer — compares Brapi, Fundamentus, Status Invest, Yahoo Finance.

A discrepancy is flagged when two primary sources disagree beyond tolerance.
On divergence, tiebreakers (SI + YF) vote: the side with more agreement wins.
On a tie, Fundamentus is preferred (audited balance sheets).

Tolerances:
  PRICE_TOL     = 2%   — intraday vs end-of-day spread
  RATIO_TOL     = 5%   — rounding differences between providers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from brapi import RawQuote
from fundamentus import FundamentusQuote
from statusinvest import StatusInvestQuote
from yfinance_source import YFinanceQuote

PRICE_TOL = 0.02
RATIO_TOL = 0.05


@dataclass
class FieldCheck:
    field: str
    brapi_value: Optional[float]
    fundamentus_value: Optional[float]
    si_value: Optional[float]
    yf_value: Optional[float]
    divergence: Optional[float]
    tolerance: float
    status: str       # "OK" | "DIVERGED" | "BRAPI_ONLY" | "FUND_ONLY" | "BOTH_MISSING"
    resolved: Optional[float]


@dataclass
class ValidationReport:
    ticker: str
    checks: list[FieldCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    brapi_price_date: Optional[str] = None
    brapi_balance_date: Optional[str] = None
    fundamentus_balance_date: Optional[str] = None

    price: Optional[float] = None
    eps: Optional[float] = None
    bvps: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    @property
    def diverged_fields(self) -> list[str]:
        return [c.field for c in self.checks if c.status == "DIVERGED"]


def validate(brapi: RawQuote, fund: FundamentusQuote,
             si: Optional[StatusInvestQuote] = None,
             yf: Optional[YFinanceQuote] = None) -> ValidationReport:
    report = ValidationReport(ticker=brapi.symbol)

    # ── timestamps ────────────────────────────────────────────────────────────
    report.brapi_price_date         = brapi.price_updated_at
    report.brapi_balance_date       = brapi.balance_updated_at
    report.fundamentus_balance_date = fund.balance_updated_at

    if (report.brapi_balance_date and report.fundamentus_balance_date
            and report.brapi_balance_date != report.fundamentus_balance_date):
        report.warnings.append(
            f"BALANCE DATE mismatch: Brapi={report.brapi_balance_date} "
            f"vs Fundamentus={report.fundamentus_balance_date} — values may reflect different quarters"
        )

    si_price = si.price if si else None
    si_lpa   = si.lpa   if si else None
    si_vpa   = si.vpa   if si else None
    si_pl    = si.pl    if si else None
    si_pvp   = si.pvp   if si else None

    yf_price = yf.price if yf else None
    yf_eps   = yf.eps   if yf else None
    yf_bvps  = yf.bvps  if yf else None
    yf_pe    = yf.pe    if yf else None
    yf_pb    = yf.pb    if yf else None

    checks = [
        _check("price", brapi.price, fund.price, si_price, yf_price, PRICE_TOL),
        _check("eps",   brapi.eps,   fund.lpa,   si_lpa,   yf_eps,   RATIO_TOL),
        _check("bvps",  brapi.bvps,  fund.vpa,   si_vpa,   yf_bvps,  RATIO_TOL),
        _check("pe",    brapi.pe,    fund.pl,    si_pl,    yf_pe,    RATIO_TOL),
        _check("pb",    brapi.pb,    fund.pvp,   si_pvp,   yf_pb,    RATIO_TOL),
    ]
    report.checks = checks

    for c in checks:
        if c.status == "DIVERGED":
            extras = []
            if c.si_value is not None:
                extras.append(f"SI={_fmt(c.si_value)}")
            if c.yf_value is not None:
                extras.append(f"YF={_fmt(c.yf_value)}")
            extra_str = " / " + " / ".join(extras) if extras else ""
            report.warnings.append(
                f"{c.field.upper()}: Brapi={_fmt(c.brapi_value)} vs "
                f"Fundamentus={_fmt(c.fundamentus_value)}{extra_str} "
                f"(diff {c.divergence:.1%} > tolerance {c.tolerance:.0%})"
            )

    report.price = _resolve("price", checks, brapi.price, fund.price)
    report.eps   = _resolve("eps",   checks, brapi.eps,   fund.lpa)
    report.bvps  = _resolve("bvps",  checks, brapi.bvps,  fund.vpa)
    report.pe    = _resolve("pe",    checks, brapi.pe,    fund.pl)
    report.pb    = _resolve("pb",    checks, brapi.pb,    fund.pvp)

    return report


# ── helpers ───────────────────────────────────────────────────────────────────

def _check(field: str, a: Optional[float], b: Optional[float],
           c: Optional[float], d: Optional[float],
           tol: float) -> FieldCheck:
    """Compare Brapi (a) vs Fundamentus (b); c=SI and d=YF are tiebreakers."""
    if a is None and b is None:
        resolved = c if c is not None else d
        status = "BOTH_MISSING" if resolved is None else "SI_ONLY"
        return FieldCheck(field, a, b, c, d, None, tol, status, resolved)
    if a is None:
        return FieldCheck(field, a, b, c, d, None, tol, "FUND_ONLY", b)
    if b is None:
        resolved = a
        tiebreakers = [x for x in (c, d) if x is not None]
        if tiebreakers:
            avg_tie = sum(tiebreakers) / len(tiebreakers)
            if abs(a - avg_tie) / max(abs(avg_tie), 1e-9) > tol:
                resolved = avg_tie
        return FieldCheck(field, a, b, c, d, None, tol, "BRAPI_ONLY", resolved)

    div = abs(a - b) / max(abs(b), 1e-9)
    if div <= tol:
        return FieldCheck(field, a, b, c, d, div, tol, "OK", a)

    # Diverged — majority vote among tiebreakers (c=SI, d=YF)
    tiebreakers = [x for x in (c, d) if x is not None]
    votes_a = sum(1 for x in tiebreakers if abs(a - x) / max(abs(x), 1e-9) <= tol)
    votes_b = sum(1 for x in tiebreakers if abs(b - x) / max(abs(x), 1e-9) <= tol)
    resolved = a if votes_a > votes_b else b  # Fundamentus wins on tie (audited)
    return FieldCheck(field, a, b, c, d, div, tol, "DIVERGED", resolved)


def _resolve(field: str, checks: list[FieldCheck],
             brapi_val: Optional[float], fund_val: Optional[float]) -> Optional[float]:
    for c in checks:
        if c.field == field:
            return c.resolved
    return brapi_val


def _fmt(v: Optional[float]) -> str:
    return f"{v:.4f}" if v is not None else "—"
