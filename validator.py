"""
Cross-validation layer — compares Brapi, Fundamentus, and Status Invest.

A discrepancy is flagged when two sources disagree beyond the allowed
tolerance. On divergence, Fundamentus is preferred (audited balance sheets);
Status Invest is used to fill gaps when both Brapi and Fundamentus are missing.

Tolerances:
  PRICE_TOL     = 2%   — intraday vs end-of-day spread
  RATIO_TOL     = 5%   — rounding differences between providers
  FUNDAMENT_TOL = 10%  — balance-sheet figures
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from brapi import RawQuote
from fundamentus import FundamentusQuote
from statusinvest import StatusInvestQuote

# Tolerance thresholds
PRICE_TOL = 0.02
RATIO_TOL = 0.05
FUNDAMENT_TOL = 0.10


@dataclass
class FieldCheck:
    field: str
    brapi_value: Optional[float]
    fundamentus_value: Optional[float]
    si_value: Optional[float]          # Status Invest value
    divergence: Optional[float]        # absolute relative difference (Brapi vs Fundamentus)
    tolerance: float
    status: str                        # "OK" | "DIVERGED" | "BRAPI_ONLY" | "FUND_ONLY" | "SI_ONLY" | "BOTH_MISSING"
    resolved: Optional[float]          # value to use after validation


@dataclass
class ValidationReport:
    ticker: str
    checks: list[FieldCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Reference timestamps from each provider
    brapi_price_date: Optional[str] = None
    brapi_balance_date: Optional[str] = None
    fundamentus_balance_date: Optional[str] = None

    # Resolved values — use these instead of raw Brapi values
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
             si: Optional[StatusInvestQuote] = None) -> ValidationReport:
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

    checks = [
        _check("price", brapi.price, fund.price, si_price, PRICE_TOL),
        _check("eps",   brapi.eps,   fund.lpa,   si_lpa,   RATIO_TOL),
        _check("bvps",  brapi.bvps,  fund.vpa,   si_vpa,   RATIO_TOL),
        _check("pe",    brapi.pe,    fund.pl,    si_pl,    RATIO_TOL),
        _check("pb",    brapi.pb,    fund.pvp,   si_pvp,   RATIO_TOL),
    ]
    report.checks = checks

    for c in checks:
        if c.status == "DIVERGED":
            si_note = f" / SI={_fmt(c.si_value)}" if c.si_value is not None else ""
            report.warnings.append(
                f"{c.field.upper()}: Brapi={_fmt(c.brapi_value)} vs "
                f"Fundamentus={_fmt(c.fundamentus_value)}{si_note} "
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
           c: Optional[float], tol: float) -> FieldCheck:
    """Compare Brapi (a) vs Fundamentus (b); c = Status Invest (tiebreak/fill)."""
    if a is None and b is None:
        # Both primary sources missing — fall back to Status Invest
        status = "SI_ONLY" if c is not None else "BOTH_MISSING"
        return FieldCheck(field, a, b, c, None, tol, status, c)
    if a is None:
        return FieldCheck(field, a, b, c, None, tol, "FUND_ONLY", b)
    if b is None:
        # Brapi has it, Fundamentus doesn't — use SI as tiebreak if available
        resolved = a
        if c is not None:
            div = abs(a - c) / max(abs(c), 1e-9)
            if div > tol:
                resolved = c  # SI likely more reliable when Fundamentus is missing
        return FieldCheck(field, a, b, c, None, tol, "BRAPI_ONLY", resolved)

    div = abs(a - b) / max(abs(b), 1e-9)
    if div <= tol:
        return FieldCheck(field, a, b, c, div, tol, "OK", a)

    # Diverged: prefer Fundamentus (audited), but if SI agrees with one side use that
    resolved = b
    if c is not None:
        div_b = abs(b - c) / max(abs(c), 1e-9)
        div_a = abs(a - c) / max(abs(c), 1e-9)
        if div_a < div_b:
            resolved = a  # SI agrees with Brapi — go with Brapi
    return FieldCheck(field, a, b, c, div, tol, "DIVERGED", resolved)


def _resolve(field: str, checks: list[FieldCheck],
             brapi_val: Optional[float], fund_val: Optional[float]) -> Optional[float]:
    for c in checks:
        if c.field == field:
            return c.resolved
    return brapi_val


def _fmt(v: Optional[float]) -> str:
    return f"{v:.4f}" if v is not None else "—"
