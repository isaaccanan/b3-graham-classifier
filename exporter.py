"""
Export GrahamReport objects to spreadsheet-compatible formats.

Format registry — adding a new target (Numbers, Excel, etc.) requires
only a new entry in FORMATS. The rest of the pipeline picks it up automatically.

To add a new format:
    FORMATS["numbers"] = ExportFormat(
        prefix="numbers",
        separator=",",
        encoding="utf-8",
        extension=".csv",
        description="Apple Numbers (macOS)",
    )
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import TextIO

from classifier import GrahamReport


@dataclass(frozen=True)
class ExportFormat:
    prefix: str
    separator: str
    encoding: str
    extension: str
    description: str


# ── format registry ───────────────────────────────────────────────────────────

FORMATS: dict[str, ExportFormat] = {
    "google": ExportFormat(
        prefix="google",
        separator=";",
        encoding="utf-8-sig",   # BOM required by Google Sheets
        extension=".csv",
        description="Google Sheets",
    ),
    "numbers": ExportFormat(
        prefix="numbers",
        separator=",",
        encoding="utf-8",       # Numbers handles plain UTF-8
        extension=".csv",
        description="Apple Numbers (macOS)",
    ),
    "excel": ExportFormat(
        prefix="excel",
        separator=";",
        encoding="utf-8-sig",   # BOM required by Excel for UTF-8
        extension=".csv",
        description="Microsoft Excel",
    ),
    "google-formulas": ExportFormat(
        prefix="google-formulas",
        separator=";",
        encoding="utf-8-sig",
        extension=".csv",
        description="Google Sheets with live Graham formulas",
    ),
}

DEFAULT_FORMAT = "google-formulas"


# ── public API ────────────────────────────────────────────────────────────────

def summary(reports: list[GrahamReport], path: str,
            fmt: str = DEFAULT_FORMAT) -> None:
    """Flat CSV — one row per stock. Best for filtering/sorting in spreadsheets."""
    f = _get_format(fmt)
    with open(path, "w", newline="", encoding=f.encoding) as out:
        writer = csv.writer(out, delimiter=f.separator, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([
            "Ticker", "Company", "Sector", "Label", "Score",
            "Price (R$)", "Graham Number (R$)", "Intrinsic Value (R$)",
            "Margin of Safety (%)", "Adj. Graham Number (R$)",
            "Min. Investment (R$)",
            "EPS (R$)", "BVPS (R$)", "P/E", "P/B", "Current Ratio",
            "Total Assets (M R$)", "Total Liabilities (M R$)",
            "Current Assets (M R$)", "Current Liabilities (M R$)",
            "Shares Outstanding (M)",
            "Avg Div Yield 3Y (%)", "Real Earnings Yield (%)",
            "IPCA Rate (%)", "Last Updated",
            "Graham No. Pass", "P/E Pass", "P/B Pass",
            "P/E×P/B Pass", "D/E Pass", "C/R Pass",
            "Sell Signal",
        ])
        for r in reports:
            writer.writerow([
                r.ticker, r.company_name, r.sector, r.label,
                f"{r.score}/{r.max_score}",
                _r(r.price), _r(r.graham_number), _r(r.intrinsic_value),
                _pct(r.margin_of_safety), _r(r.adjusted_graham_number),
                _r(r.min_investment),
                _r(r.eps), _r(r.bvps), _r(r.pe), _r(r.pb), _r(r.current_ratio),
                _r(r.total_assets_m), _r(r.total_liabilities_m),
                _r(r.current_assets_m), _r(r.current_liabilities_m),
                _r(r.shares_outstanding_m),
                _pct(r.avg_div_yield_3y), _pct(r.real_earnings_yield),
                _pct(r.ipca_rate), r.last_updated,
                _yn(r.criteria.get("Graham Number")),
                _yn(r.criteria.get("P/E ≤ 15")),
                _yn(r.criteria.get("P/B ≤ 1.5")),
                _yn(r.criteria.get("P/E×P/B ≤ 22.5")),
                _yn(r.criteria.get("D/E ≤ 1.0")),
                _yn(r.criteria.get("C/R ≥ 2.0")),
                _yn(r.sell_signal),
            ])


def detail(reports: list[GrahamReport], path: str,
           fmt: str = DEFAULT_FORMAT) -> None:
    """Section/Field/Value layout — full Graham table per stock."""
    f = _get_format(fmt)
    with open(path, "w", newline="", encoding=f.encoding) as out:
        writer = csv.writer(out, delimiter=f.separator, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["Section", "Field", "Value", "Notes"])
        for r in reports:
            writer.writerows(_detail_rows(r))
            writer.writerow([])


def format_description(fmt: str) -> str:
    return _get_format(fmt).description


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_format(fmt: str) -> ExportFormat:
    if fmt not in FORMATS:
        available = ", ".join(FORMATS)
        raise ValueError(f"Unknown export format '{fmt}'. Available: {available}")
    return FORMATS[fmt]


def _detail_rows(r: GrahamReport) -> list[list]:
    rows = []

    def add(section, field, value, notes=""):
        rows.append([section, field, value, notes])

    add("Company Info", "Ticker", r.ticker)
    add("Company Info", "Company Name", r.company_name)
    add("Company Info", "Sector", r.sector)
    add("Company Info", "Last Updated", r.last_updated)

    add("Financial Inputs (TTM)", "Current Price (R$)", _r(r.price))
    add("Financial Inputs (TTM)", "Min. Investment (R$)", _r(r.min_investment), "Price × 100 shares (B3 standard lot)")
    add("Financial Inputs (TTM)", "EPS (R$)", _r(r.eps))
    add("Financial Inputs (TTM)", "Book Value Per Share (R$)", _r(r.bvps))
    add("Financial Inputs (TTM)", "Total Assets (M R$)", _r(r.total_assets_m))
    add("Financial Inputs (TTM)", "Total Liabilities (M R$)", _r(r.total_liabilities_m))
    add("Financial Inputs (TTM)", "Current Assets (M R$)", _r(r.current_assets_m))
    add("Financial Inputs (TTM)", "Current Liabilities (M R$)", _r(r.current_liabilities_m))
    add("Financial Inputs (TTM)", "Shares Outstanding (M)", _r(r.shares_outstanding_m))

    add("Valuation Metrics", "P/E Ratio", _r(r.pe), f"Graham threshold ≤ 15")
    add("Valuation Metrics", "P/B Ratio", _r(r.pb), f"Graham threshold ≤ 1.5")
    add("Valuation Metrics", "Current Ratio", _r(r.current_ratio), f"Graham threshold ≥ 2.0")
    add("Valuation Metrics", "Graham Number (R$)", _r(r.graham_number), "√(22.5 × EPS × BVPS)")
    add("Valuation Metrics", "Intrinsic Value Est. (R$)", _r(r.intrinsic_value))
    add("Valuation Metrics", "Margin of Safety (%)", _pct(r.margin_of_safety))

    if r.dividend_history:
        for d in r.dividend_history:
            pr = _pct(d.payout_ratio) if d.payout_ratio else "N/A"
            add("Dividend History", str(d.year), _r(d.paid), f"Payout: {pr}")
    add("Dividend History", "Avg Yield 3Y (%)", _pct(r.avg_div_yield_3y))

    add("Inflation (IPCA)", "Target IPCA Rate (%)", _pct(r.ipca_rate))
    add("Inflation (IPCA)", "Real Earnings Yield (%)", _pct(r.real_earnings_yield), "EPS/Price − IPCA")
    add("Inflation (IPCA)", "Adjusted Graham Number (R$)", _r(r.adjusted_graham_number), "GN × (1 + IPCA)")

    add("Graham Score", "Score", f"{r.score}/{r.max_score}")
    add("Graham Score", "Label", r.label)
    add("Graham Score", "Sell Signal", _yn(r.sell_signal),
        "YES = price ≥ Graham Number — target reached, consider exiting")
    for crit, passed in r.criteria.items():
        add("Graham Criteria", crit, _yn(passed))

    return rows


def _r(val) -> str:
    return "N/A" if val is None else f"{val:.2f}"


def _pct(val) -> str:
    return "N/A" if val is None else f"{val * 100:.2f}%"


def _yn(val: bool | None) -> str:
    if val is None:
        return "?"
    return "YES" if val else "NO"


# ── Google Sheets formula export ──────────────────────────────────────────────
#
# Column layout (A–AD, row 1 = headers, data from row 2):
#
#  INPUT  (plain values — user can edit to recalculate)
#   A  Ticker            E  Price (R$)       I  D/E
#   B  Company           F  EPS (R$)         J  IPCA Rate
#   C  Sector            G  BVPS (R$)        K  Avg Div Yield 3Y
#   D  Last Updated      H  Current Ratio    L  Total Assets (M R$)
#                                             M  Total Liab (M R$)
#                                             N  Current Assets (M R$)
#                                             O  Current Liab (M R$)
#                                             P  Shares Outstanding (M)
#
#  FORMULA  (recalculate automatically when inputs change)
#   Q  Graham Number     V  GN Pass          AB  Score
#   R  Margin of Safety  W  PE Pass          AC  Label
#   S  Adj. Graham No.   X  PB Pass          AD  Sell Signal
#   T  Real EY           Y  PEPB Pass
#   U  Min. Investment   Z  DE Pass
#                        AA CR Pass
#
# Formulas use Brazilian Portuguese locale (semicolon as argument separator),
# matching the default locale for Brazilian Google Sheets accounts.

_FORMULA_HEADERS = [
    "Ticker", "Company", "Sector", "Last Updated",
    "Price (R$)", "EPS (R$)", "BVPS (R$)", "Current Ratio", "D/E",
    "IPCA Rate", "Avg Div Yield 3Y", "Total Assets (M R$)",
    "Total Liab (M R$)", "Current Assets (M R$)", "Current Liab (M R$)",
    "Shares Outstanding (M)",
    # ── formulas ──
    "Graham Number (R$)", "Margin of Safety", "Adj. Graham Number (R$)",
    "Real Earnings Yield", "Min. Investment (R$)",
    "GN Pass", "PE Pass", "PB Pass", "PEPB Pass", "DE Pass", "CR Pass",
    "Score", "Label", "Sell Signal",
]


def summary_formulas(reports: list[GrahamReport], path: str) -> None:
    """Google Sheets CSV where calculated fields are live Graham formulas.

    Input columns (price, EPS, BVPS, ratios) are plain values the user can
    edit. Formula columns (Graham Number, Score, Label, etc.) recalculate
    automatically when any input changes.
    """
    f = _get_format("google-formulas")
    with open(path, "w", newline="", encoding=f.encoding) as out:
        writer = csv.writer(out, delimiter=f.separator, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(_FORMULA_HEADERS)
        for i, r in enumerate(reports, start=2):
            writer.writerow(_formula_row(r, i))


def _formula_row(r: GrahamReport, row: int) -> list:
    n = row
    # Input values — empty string for missing (blank cell in Sheets)
    return [
        r.ticker,
        r.company_name,
        r.sector,
        r.last_updated,
        _rv(r.price),
        _rv(r.eps),
        _rv(r.bvps),
        _rv(r.current_ratio),
        _rv(r.debt_to_equity),
        _rv(r.ipca_rate),
        _rv(r.avg_div_yield_3y),
        _rv(r.total_assets_m),
        _rv(r.total_liabilities_m),
        _rv(r.current_assets_m),
        _rv(r.current_liabilities_m),
        _rv(r.shares_outstanding_m),
        # ── Graham Number: √(22.5 × EPS × BVPS), requires positive product ──
        f'=IFERROR(IF(F{n}*G{n}>0;SQRT(22.5*F{n}*G{n});"");"")' ,
        # ── Margin of Safety: (GN − Price) / GN ──
        f'=IFERROR((Q{n}-E{n})/Q{n};"")' ,
        # ── Adjusted Graham Number: GN × (1 + IPCA) ──
        f'=IFERROR(Q{n}*(1+J{n});"")' ,
        # ── Real Earnings Yield: EPS/Price − IPCA ──
        f'=IFERROR(IF(OR(F{n}="";E{n}="");"";F{n}/E{n}-J{n});"")' ,
        # ── Minimum Investment: Price × 100 shares (B3 standard lot) ──
        f'=IF(E{n}="";"";E{n}*100)' ,
        # ── Criteria ──
        f'=IFERROR(IF(OR(E{n}="";Q{n}="");"?";IF(E{n}<Q{n};"YES";"NO"));"?")' ,
        f'=IFERROR(IF(OR(E{n}="";F{n}="";F{n}=0);"?";IF(E{n}/F{n}<=15;"YES";"NO"));"?")' ,
        f'=IFERROR(IF(OR(E{n}="";G{n}="";G{n}=0);"?";IF(E{n}/G{n}<=1.5;"YES";"NO"));"?")' ,
        f'=IFERROR(IF(OR(E{n}="";F{n}="";G{n}="";F{n}=0;G{n}=0);"?";IF((E{n}/F{n})*(E{n}/G{n})<=22.5;"YES";"NO"));"?")' ,
        f'=IFERROR(IF(I{n}="";"?";IF(I{n}<=1;"YES";"NO"));"?")' ,
        f'=IFERROR(IF(H{n}="";"?";IF(H{n}>=2;"YES";"NO"));"?")' ,
        # ── Score: count YES / count evaluated criteria ──
        f'=COUNTIF(V{n}:AA{n};"YES")&"/"&(6-COUNTIF(V{n}:AA{n};"?"))' ,
        # ── Label: mirrors the Python _label() logic ──
        (
            f'=IFERROR('
            f'IF((6-COUNTIF(V{n}:AA{n};"?"))=0;"Insufficient Data";'
            f'IF(Q{n}="";"Inconclusive";'
            f'IF(AND(COUNTIF(V{n}:AA{n};"YES")/(6-COUNTIF(V{n}:AA{n};"?"))>=0.83;V{n}="YES");"Strong Buy";'
            f'IF(AND(COUNTIF(V{n}:AA{n};"YES")/(6-COUNTIF(V{n}:AA{n};"?"))>=0.66;V{n}<>"NO");"Buy";'
            f'IF(COUNTIF(V{n}:AA{n};"YES")/(6-COUNTIF(V{n}:AA{n};"?"))>=0.5;"Hold";'
            f'IF(COUNTIF(V{n}:AA{n};"YES")/(6-COUNTIF(V{n}:AA{n};"?"))>=0.33;"Overvalued";"Avoid")'
            f')))))));IF((6-COUNTIF(V{n}:AA{n};"?"))=0;"Insufficient Data";"Inconclusive"))'
        ),
        # ── Sell Signal: price ≥ Graham Number → MoS ≤ 0 ──
        f'=IFERROR(IF(R{n}<=0;"YES";"NO");"?")' ,
    ]


def _rv(val) -> str:
    """Plain numeric value for formula export — empty string for None."""
    return "" if val is None else f"{val:.6g}"
