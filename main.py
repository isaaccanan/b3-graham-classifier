"""
B3 Graham Classifier — CLI

Usage:
    python main.py                              # scan all Ibovespa tickers
    python main.py --tickers PETR4 VALE3        # specific tickers
    python main.py --filter "Strong Buy"        # show only one label
    python main.py --summary results.csv        # flat CSV for Google Sheets
    python main.py --detail detail.csv          # full Graham table per stock
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date

from tabulate import tabulate

import brapi
import classifier as clf
import cvm as cvm_module
import exporter
import fundamentus
import ipca as ipca_module
import menu as interactive_menu
import statusinvest as si_module
import validator as val
import yfinance_source as yf_module
from tickers import IBOVESPA_TICKERS

# ── logging setup ─────────────────────────────────────────────────────────────
_LOG_DIR = pathlib.Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_handler = logging.handlers.RotatingFileHandler(
    _LOG_DIR / "classifier.log",
    maxBytes=1_000_000,   # 1 MB per file
    backupCount=5,        # keep last 5 rotated files
    encoding="utf-8",
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(message)s"))

log = logging.getLogger("graham")
log.setLevel(logging.DEBUG if __import__("os").getenv("GRAHAM_DEBUG") else logging.INFO)
log.addHandler(_handler)

LABEL_ORDER = clf.LABEL_ORDER

_DISCLAIMER = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                          INVESTMENT DISCLAIMER                               ║
║                                                                              ║
║  This tool is for informational and educational purposes only.               ║
║  It does NOT constitute financial advice or a recommendation to buy,         ║
║  sell, or hold any security.                                                 ║
║                                                                              ║
║  All outputs are based on publicly available data and quantitative           ║
║  models. Data accuracy is not guaranteed. Past metrics do not predict        ║
║  future performance.                                                         ║
║                                                                              ║
║  Always consult a qualified financial advisor before making any              ║
║  investment decision. Use at your own risk.                                  ║
║                                                                    MIT © 2026║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

LABEL_COLOR = {
    "Strong Buy":        "\033[92m",
    "Buy":               "\033[32m",
    "Hold":              "\033[33m",
    "Overvalued":        "\033[91m",
    "Avoid":             "\033[31m",
    "Inconclusive":      "\033[35m",  # magenta — missing core data
    "Insufficient Data": "\033[90m",
}
RESET = "\033[0m"


def _fetch_and_validate(ticker: str) -> tuple[clf.GrahamReport, val.ValidationReport]:
    snap = brapi.fetch_quote(ticker)
    fund = fundamentus.fetch(ticker)
    si   = si_module.fetch(ticker)
    yf   = yf_module.fetch(ticker)
    cvm  = cvm_module.fetch(ticker)
    v    = val.validate(snap, fund, si, yf)

    # Apply validated/resolved values back into the quote before classifying
    snap.price = v.price or snap.price
    snap.eps   = v.eps   or snap.eps
    snap.bvps  = v.bvps  or snap.bvps
    snap.pe    = v.pe    or snap.pe
    snap.pb    = v.pb    or snap.pb

    # Fill balance sheet fields from CVM when Brapi is missing
    if snap.total_assets is None and cvm.total_assets_m is not None:
        snap.total_assets = cvm.total_assets_m * 1_000_000
    if snap.total_liabilities is None and cvm.total_liabilities_m is not None:
        snap.total_liabilities = cvm.total_liabilities_m * 1_000_000
    if snap.current_assets is None and cvm.current_assets_m is not None:
        snap.current_assets = cvm.current_assets_m * 1_000_000
    if snap.current_liabilities is None and cvm.current_liabilities_m is not None:
        snap.current_liabilities = cvm.current_liabilities_m * 1_000_000

    report = clf.classify(snap)
    return report, v


def run(tickers: list[str], label_filter: str | None,
        summary_path: str | None, detail_path: str | None,
        workers: int, no_color: bool, export_format: str = exporter.DEFAULT_FORMAT) -> None:

    run_id = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info("=== RUN STARTED | tickers=%s | filter=%s ===", tickers, label_filter)

    print(f"Validating {len(tickers)} ticker(s)…")
    valid, invalid = brapi.validate_tickers(tickers)
    if invalid:
        print(f"  Skipped (not found on B3): {', '.join(invalid)}")
        log.warning("Invalid tickers skipped: %s", invalid)
    tickers = valid
    if not tickers:
        print("No valid tickers to process.")
        log.warning("No valid tickers — run aborted")
        return
    print(f"  {len(tickers)} valid ticker(s)\n")

    print(f"Fetching & cross-validating {len(tickers)} ticker(s)…\n")

    reports: list[clf.GrahamReport] = []
    validations: dict[str, val.ValidationReport] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_and_validate, t): t for t in tickers}
        for i, future in enumerate(as_completed(futures), 1):
            report, v = future.result()
            reports.append(report)
            validations[report.ticker] = v

            cached = brapi._load_cache(report.ticker) is not None
            source = "CACHED" if cached else "API   "
            warn = f"  ⚠  diverged: {', '.join(v.diverged_fields)}" if v.diverged_fields else ""
            fund_err = f"  ✗ Fundamentus: {v.warnings[0][:60]}" if not warn and v.has_warnings else ""
            print(f"  [{i:>3}/{len(tickers)}] [{source}] {report.ticker:<10} {report.label}{warn}{fund_err}", flush=True)

            log.info(
                "RESULT | %s | label=%-15s | score=%d/%d | price=%.2f | GN=%s | MoS=%s | source=%s",
                report.ticker, report.label, report.score, report.max_score,
                report.price or 0,
                f"{report.graham_number:.2f}" if report.graham_number else "N/A",
                f"{report.margin_of_safety:.1%}" if report.margin_of_safety is not None else "N/A",
                source.strip(),
            )
            for w in v.warnings:
                log.warning("VALIDATION | %s | %s", report.ticker, w)

    # Print timestamps + divergence warnings summary
    print("\nReference dates (price date | Brapi balance | Fundamentus balance):")
    for ticker in sorted(validations):
        v = validations[ticker]
        pd  = v.brapi_price_date         or "—"
        bd  = v.brapi_balance_date       or "—"
        fd  = v.fundamentus_balance_date or "—"
        flag = " ⚠ dates differ" if bd != fd and bd != "—" and fd != "—" else ""
        print(f"  {ticker:<10} {pd}  |  {bd}  |  {fd}{flag}")
        log.info("DATES | %s | price=%s | brapi_bal=%s | fund_bal=%s", ticker, pd, bd, fd)

    all_warnings = [(t, w) for t, v in validations.items() for w in v.warnings]
    if all_warnings:
        print("\n⚠  Validation warnings:")
        for ticker, w in all_warnings:
            print(f"   {ticker}: {w}")

    reports.sort(key=lambda r: (LABEL_ORDER.index(r.label), r.ticker))

    if label_filter:
        reports = [r for r in reports if r.label == label_filter]

    _print_table(reports, no_color)

    if summary_path:
        out = _prefixed_path(summary_path, "summary", export_format)
        if export_format == "google-formulas":
            exporter.summary_formulas(reports, out)
        else:
            exporter.summary(reports, out, fmt=export_format)
        print(f"\nSummary CSV saved → {out}  [{exporter.format_description(export_format)}]")
        if export_format in ("google", "google-formulas"):
            print("Google Sheets: File → Import → Upload → select file → Replace spreadsheet")
        if export_format == "google-formulas":
            print("Tip: edit EPS (F), BVPS (G), Current Ratio (H), or D/E (I) cells to")
            print("     recalculate Graham Number, Score, Label, and all criteria live.")
            print("     Requires English locale: File → Settings → General → Locale → United States")
        log.info("Summary CSV exported → %s [%s]", out, export_format)

    if detail_path:
        fmt = "google" if export_format == "google-formulas" else export_format
        out = _prefixed_path(detail_path, "detail", export_format)
        exporter.detail(reports, out, fmt=fmt)
        print(f"Detail  CSV saved → {out}  [{exporter.format_description(export_format)}]")
        log.info("Detail CSV exported → %s [%s]", out, export_format)

    log.info("=== RUN COMPLETE | %d ticker(s) processed ===", len(reports))



_EXPORTS_DIR = pathlib.Path(__file__).parent / "exports"
_EXPORTS_DIR.mkdir(exist_ok=True)


def _prefixed_path(path: str, file_type: str, fmt: str) -> str:
    """Build output filename as exports/<format>_<type>_<date>_<basename>.csv

    Examples:
      "results.csv", "summary", "google"  → exports/google_summary_20260519_results.csv
      "results.csv", "detail",  "numbers" → exports/numbers_detail_20260519_results.csv
    """
    p = pathlib.Path(path)
    today = date.today().strftime("%Y%m%d")
    stem = p.stem if p.suffix else p.name
    suffix = exporter.FORMATS.get(fmt, exporter.FORMATS[exporter.DEFAULT_FORMAT]).extension
    new_name = f"{fmt}_{file_type}_{today}_{stem}{suffix}"
    # Always write to exports/ — ignore any directory component in the user input
    return str(_EXPORTS_DIR / new_name)


_SELL_COLOR  = "\033[91m"   # bright red
_HOLD_COLOR  = "\033[32m"   # green

def _fmt_sell(sell: bool | None, no_color: bool) -> str:
    if sell is None:
        return "—"
    if sell:
        return f"{_SELL_COLOR}YES{RESET}" if not no_color else "YES"
    return f"{_HOLD_COLOR}NO{RESET}" if not no_color else "NO"


def _print_table(reports: list[clf.GrahamReport], no_color: bool) -> None:
    rows = []
    for r in reports:
        price = f"R${r.price:.2f}" if r.price else "—"
        gn = f"R${r.graham_number:.2f}" if r.graham_number else "—"
        mos = f"{r.margin_of_safety:.1%}" if r.margin_of_safety is not None else "—"
        criteria_str = _fmt_criteria(r)
        score_str = f"{r.score}/{r.max_score}"
        label = r.label
        if not no_color:
            color = LABEL_COLOR.get(label, "")
            label = f"{color}{label}{RESET}"
        sell = _fmt_sell(r.sell_signal, no_color)
        min_inv = f"R${r.min_investment:,.2f}" if r.min_investment else "—"
        rows.append([r.ticker, price, gn, mos, criteria_str, score_str, label, sell, min_inv])

    headers = ["Ticker", "Price", "Graham No.", "Margin of Safety",
               "GN/PE/PB/PEPB/DE/CR", "Score", "Label", "Sell?", "Min. Investment (100 shares)"]
    print("\n" + tabulate(rows, headers=headers, tablefmt="rounded_outline"))
    print(f"\n{len(reports)} stock(s) shown.")
    _print_legend()


def _print_legend() -> None:
    print("""
─── Graham Criteria Legend ──────────────────────────────────────────────────────
  GN   Graham Number      Price < √(22.5 × EPS × BVPS)
                          The stock trades below Graham's estimate of intrinsic
                          value. Core criterion — without it the label is
                          Inconclusive regardless of other scores.

  PE   Price / Earnings   P/E ≤ 15
                          Earnings are not overpriced. Graham viewed P/E > 15
                          as speculative. Lower is more conservative.

  PB   Price / Book       P/B ≤ 1.5
                          Price is close to or below net asset value.
                          Indicates asset-backed pricing with limited downside.

  PEPB P/E × P/B         P/E × P/B ≤ 22.5
                          Combined multiplier allowing a trade-off: a stock with
                          P/E 12 and P/B 1.9 passes even though P/B alone fails.
                          Graham's own formula for balanced valuation.

  DE   Debt / Equity      D/E ≤ 1.0
                          Total liabilities do not exceed shareholders' equity.
                          Low leverage reduces bankruptcy risk in downturns.

  CR   Current Ratio      C/R ≥ 2.0
                          Current assets are at least twice current liabilities.
                          Confirms the company can meet short-term obligations.

  ✓ = passes threshold   ✗ = fails threshold   ? = data unavailable
────────────────────────────────────────────────────────────────────────────────""")


def _fmt_criteria(r: clf.GrahamReport) -> str:
    keys = ["Graham Number", "P/E ≤ 15", "P/B ≤ 1.5",
            "P/E×P/B ≤ 22.5", "D/E ≤ 1.0", "C/R ≥ 2.0"]
    return "/".join(
        ("✓" if r.criteria.get(k) else ("✗" if r.criteria.get(k) is False else "?"))
        for k in keys
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify B3 stocks using Benjamin Graham valuation principles."
    )
    parser.add_argument(
        "--tickers", nargs="+", metavar="TICKER",
        help="B3 tickers (without .SA). Defaults to full Ibovespa list.",
    )
    parser.add_argument(
        "--filter", metavar="LABEL", choices=LABEL_ORDER,
        help="Show only stocks with this label.",
    )
    parser.add_argument(
        "--summary", metavar="FILE",
        help="Save flat summary CSV (one row per stock) — best for Google Sheets.",
    )
    parser.add_argument(
        "--detail", metavar="FILE",
        help="Save full Graham detail CSV (one section block per stock).",
    )
    parser.add_argument(
        "--workers", type=int, default=4, metavar="N", choices=range(1, 17),
        help="Parallel fetch threads 1–16 (default: 4). Keep low on free Brapi plans.",
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI colour output.",
    )
    parser.add_argument(
        "--format", metavar="FORMAT",
        choices=list(exporter.FORMATS),
        default=exporter.DEFAULT_FORMAT,
        help=(
            "Export format: "
            + ", ".join(f"{k} ({v.description})" for k, v in exporter.FORMATS.items())
            + f". Default: {exporter.DEFAULT_FORMAT}"
        ),
    )
    parser.add_argument(
        "--flush", nargs="*", metavar="TICKER",
        help=(
            "Force re-fetch by clearing today's cache. "
            "Pass specific tickers (--flush PETR4 VALE3) or no value (--flush) to flush all requested tickers."
        ),
    )

    args = parser.parse_args()

    # No arguments → launch interactive menu
    if len(sys.argv) == 1:
        print(_DISCLAIMER)
        interactive_menu.start(run)
        return

    print(_DISCLAIMER)
    tickers = [t.upper() for t in args.tickers] if args.tickers else IBOVESPA_TICKERS

    # ── cache flush ───────────────────────────────────────────────────────────
    if args.flush is not None:
        targets = [t.upper() for t in args.flush] if args.flush else tickers
        b_flushed = brapi.flush_cache(targets)
        f_flushed = fundamentus.flush_cache(targets)
        s_flushed = si_module.flush_cache(targets)
        y_flushed = yf_module.flush_cache(targets)
        c_flushed = cvm_module.flush_cache(targets)
        all_flushed = sorted(set(b_flushed) | set(f_flushed) | set(s_flushed) | set(y_flushed) | set(c_flushed))
        if all_flushed:
            print(f"Cache flushed for: {', '.join(all_flushed)}")
            log.info("Cache flushed for: %s", all_flushed)
        else:
            print("No cache files found to flush for the given tickers.")

    try:
        run(
            tickers=tickers,
            label_filter=args.filter,
            summary_path=args.summary,
            detail_path=args.detail,
            workers=args.workers,
            no_color=args.no_color,
            export_format=args.format,
        )
    except KeyError as exc:
        print(f"\nError: missing environment variable {exc}")
        print("Copy .env.example to .env and add your BRAPI_TOKEN.")
        sys.exit(1)


if __name__ == "__main__":
    main()
