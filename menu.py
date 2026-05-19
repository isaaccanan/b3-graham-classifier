"""
Interactive terminal menu — shown when main.py is run with no arguments.
"""

from __future__ import annotations

import pathlib
import re
import sys
from datetime import date

import exporter

# ── colours ───────────────────────────────────────────────────────────────────
_BOLD   = "\033[1m"
_CYAN   = "\033[96m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_GREY   = "\033[90m"
_RESET  = "\033[0m"

_LOG_FILE = pathlib.Path(__file__).parent / "logs" / "classifier.log"

# ── entry point ───────────────────────────────────────────────────────────────

def start(run_fn) -> None:
    """Launch the interactive menu. run_fn is main.run()."""
    _clear()
    while True:
        _main_menu(run_fn)


# ── menus ─────────────────────────────────────────────────────────────────────

def _main_menu(run_fn) -> None:
    _header("MAIN MENU")
    _opt("1", "Run Analysis")
    _opt("2", "View Logs")
    _opt("3", "Help")
    _opt("0", "Exit", color=_RED)
    choice = _prompt()

    if choice == "1":
        _run_menu(run_fn)
    elif choice == "2":
        _log_menu()
    elif choice == "3":
        _help_menu()
    elif choice == "0":
        _goodbye()
    else:
        _invalid()


def _run_menu(run_fn) -> None:
    _clear()
    _header("RUN ANALYSIS")

    # ── tickers ───────────────────────────────────────────────────────────────
    print(f"  {_GREY}Leave blank to scan the full Ibovespa list (~80 tickers){_RESET}")
    raw = _prompt("Tickers (space-separated, e.g. PETR4 VALE3 BBAS3)").strip()
    from tickers import IBOVESPA_TICKERS
    tickers = [t.upper() for t in raw.split()] if raw else IBOVESPA_TICKERS

    # ── export format ─────────────────────────────────────────────────────────
    print()
    _header("EXPORT FORMAT")
    for i, (key, fmt) in enumerate(exporter.FORMATS.items(), 1):
        _opt(str(i), f"{fmt.description}  {_GREY}[{key}]{_RESET}")
    _opt("0", "No export — terminal only")
    fmt_choice = _prompt()
    fmt_keys = list(exporter.FORMATS.keys())
    export_fmt = fmt_keys[int(fmt_choice) - 1] if fmt_choice.isdigit() and 1 <= int(fmt_choice) <= len(fmt_keys) else None

    # ── output file base name ─────────────────────────────────────────────────
    summary_path = detail_path = None
    if export_fmt:
        print()
        raw_name = _prompt("Base filename (e.g. results)  [default: results]").strip() or "results"
        print()
        _header("FILE TYPE")
        _opt("1", "Summary  — one row per stock (best for Sheets)")
        _opt("2", "Detail   — full Graham table per stock")
        _opt("3", "Both")
        file_choice = _prompt()
        if file_choice in ("1", "3"):
            summary_path = raw_name
        if file_choice in ("2", "3"):
            detail_path = raw_name

    # ── label filter ──────────────────────────────────────────────────────────
    print()
    _header("FILTER BY LABEL  (optional)")
    from classifier import LABEL_ORDER
    for i, label in enumerate(LABEL_ORDER, 1):
        _opt(str(i), label)
    _opt("0", "Show all labels")
    lf_choice = _prompt()
    label_filter = LABEL_ORDER[int(lf_choice) - 1] if lf_choice.isdigit() and 1 <= int(lf_choice) <= len(LABEL_ORDER) else None

    # ── cache flush ───────────────────────────────────────────────────────────
    print()
    flush_input = _prompt("Flush cache for specific tickers before run? (space-separated, blank = no)").strip()
    flush_tickers = [t.upper() for t in flush_input.split()] if flush_input else None

    # ── run ───────────────────────────────────────────────────────────────────
    print()
    if flush_tickers:
        import brapi, fundamentus as fund_module, statusinvest as si_module, cvm as cvm_module
        b = brapi.flush_cache(flush_tickers)
        f = fund_module.flush_cache(flush_tickers)
        s = si_module.flush_cache(flush_tickers)
        c = cvm_module.flush_cache(flush_tickers)
        flushed = sorted(set(b) | set(f) | set(s) | set(c))
        if flushed:
            print(f"{_YELLOW}Cache flushed for: {', '.join(flushed)}{_RESET}\n")

    try:
        run_fn(
            tickers=tickers,
            label_filter=label_filter,
            summary_path=summary_path,
            detail_path=detail_path,
            workers=4,
            no_color=False,
            export_format=export_fmt or "google",
        )
    except Exception as exc:
        print(f"\n{_RED}Error during run: {exc}{_RESET}")

    _back_prompt()


def _log_menu() -> None:
    while True:
        _clear()
        _header("VIEW LOGS")
        _opt("1", "All entries  (last 50 lines)")
        _opt("2", "Warnings & errors only")
        _opt("3", "Filter by ticker")
        _opt("4", "Filter by label")
        _opt("5", "Show last N runs")
        _opt("0", "Back to main menu", color=_GREY)
        choice = _prompt()

        if choice == "0":
            break
        elif choice == "1":
            _show_log(tail=50)
        elif choice == "2":
            _show_log(level="WARNING")
        elif choice == "3":
            ticker = _prompt("Enter ticker (e.g. PETR4)").strip().upper()
            _show_log(grep=ticker)
        elif choice == "4":
            from classifier import LABEL_ORDER
            for i, label in enumerate(LABEL_ORDER, 1):
                _opt(str(i), label)
            lf = _prompt()
            if lf.isdigit() and 1 <= int(lf) <= len(LABEL_ORDER):
                _show_log(grep=f"label={LABEL_ORDER[int(lf)-1]}")
        elif choice == "5":
            n = _prompt("How many runs to show? [default: 5]").strip()
            n = int(n) if n.isdigit() else 5
            _show_runs(n)
        else:
            _invalid()
            continue

        _back_prompt()


def _help_menu() -> None:
    _clear()
    _header("HELP MANUAL")
    print(f"""
{_BOLD}ABOUT{_RESET}
  B3 Graham Classifier screens Brazilian B3 stocks using Benjamin Graham's
  value investing framework. It fetches data from two independent sources
  (Brapi and Fundamentus), cross-validates them, and assigns a classification.

{_BOLD}CLASSIFICATION LABELS{_RESET}
  {_GREEN}Strong Buy{_RESET}      Price well below Graham Number. Most criteria pass.
  {_GREEN}Buy{_RESET}             Price below Graham Number. Several criteria pass.
  {_YELLOW}Hold{_RESET}            Mixed signals. Neither clearly cheap nor expensive.
  {_RED}Overvalued{_RESET}      Trading above fair value by most Graham criteria.
  {_RED}Avoid{_RESET}           Fails most Graham criteria. Not a value opportunity.
  {_YELLOW}Inconclusive{_RESET}    Some criteria pass but Graham Number can't be calculated.
  {_GREY}Insufficient Data{_RESET}  Not enough data from either source to classify.

{_BOLD}GRAHAM CRITERIA CHECKED{_RESET}
  GN   Graham Number     Price < √(22.5 × EPS × BVPS)
  PE   P/E Ratio         ≤ 15
  PB   P/B Ratio         ≤ 1.5
  PEPB P/E × P/B         ≤ 22.5  (Graham's combined rule)
  DE   Debt / Equity     ≤ 1.0
  CR   Current Ratio     ≥ 2.0

{_BOLD}DATA SOURCES{_RESET}
  Primary    Brapi (brapi.dev) — live market data via REST API
  Secondary  Fundamentus (fundamentus.com.br) — scraped fundamentals
  Tertiary   Status Invest (statusinvest.com.br) — cross-validation tiebreaker
  Official   CVM (dados.cvm.gov.br) — audited balance sheet (Total/Current Assets & Liabilities)
  Override   overrides.json — manual VPA/LPA for banks and missing data

{_BOLD}CROSS-VALIDATION{_RESET}
  Values from three sources are compared against tolerance thresholds:
    Price:      ±2%   (intraday vs end-of-day spread)
    Ratios:     ±5%   (rounding differences)
  Divergences are flagged as warnings and logged. On divergence,
  Fundamentus values are preferred (audited balance sheets).
  Status Invest acts as tiebreaker when Brapi and Fundamentus disagree.

{_BOLD}CACHE{_RESET}
  Each ticker is cached once per calendar day (Brapi + Fundamentus).
  Use --flush <TICKER> or the Run Analysis menu to force a refresh.
  Cache files live in: cache/

{_BOLD}EXPORT FORMATS{_RESET}
  google   Semicolon-separated, UTF-8 BOM  → Google Sheets
  numbers  Comma-separated, UTF-8          → Apple Numbers (macOS)
  excel    Semicolon-separated, UTF-8 BOM  → Microsoft Excel

{_BOLD}OUTPUT FILES{_RESET}
  summary  One row per stock — best for filtering and pivot tables
  detail   Section/Field/Value layout — full Graham table per company
  Filename pattern: <format>_<type>_<YYYYMMDD>_<basename>.csv

{_BOLD}COMMAND LINE (advanced){_RESET}
  python main.py --tickers PETR4 VALE3
  python main.py --filter "Strong Buy" --summary results.csv
  python main.py --format numbers --summary results.csv
  python main.py --tickers PETR4 --flush
  python main.py --help

{_BOLD}DISCLAIMER{_RESET}
  {_GREY}This tool is for informational purposes only. It does not constitute
  financial advice. Always consult a qualified financial advisor before
  making any investment decision. MIT License © 2026{_RESET}
""")
    _back_prompt()


# ── log helpers ───────────────────────────────────────────────────────────────

def _show_log(tail: int = 0, level: str = "", grep: str = "") -> None:
    if not _LOG_FILE.exists():
        print(f"\n{_GREY}No log file found yet. Run an analysis first.{_RESET}")
        return

    lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()

    if level:
        lines = [l for l in lines if level in l]
    if grep:
        lines = [l for l in lines if grep.upper() in l.upper()]
    if tail:
        lines = lines[-tail:]

    print()
    if not lines:
        print(f"  {_GREY}No matching log entries.{_RESET}")
        return

    for line in lines:
        if "WARNING" in line or "ERROR" in line:
            print(f"  {_YELLOW}{line}{_RESET}")
        elif "RUN STARTED" in line or "RUN COMPLETE" in line:
            print(f"  {_CYAN}{line}{_RESET}")
        else:
            print(f"  {_GREY}{line}{_RESET}")
    print(f"\n  {_GREY}{len(lines)} line(s) shown{_RESET}")


def _show_runs(n: int) -> None:
    if not _LOG_FILE.exists():
        print(f"\n{_GREY}No log file found yet.{_RESET}")
        return

    lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()
    starts = [i for i, l in enumerate(lines) if "RUN STARTED" in l]
    starts = starts[-n:]

    print()
    for idx in starts:
        end = next((i for i in range(idx + 1, len(lines)) if "RUN COMPLETE" in lines[i]), len(lines) - 1)
        block = lines[idx:end + 1]
        for line in block:
            if "WARNING" in line:
                print(f"  {_YELLOW}{line}{_RESET}")
            elif "RUN STARTED" in line or "RUN COMPLETE" in line:
                print(f"  {_CYAN}{line}{_RESET}")
            else:
                print(f"  {_GREY}{line}{_RESET}")
        print()


# ── UI primitives ─────────────────────────────────────────────────────────────

def _clear() -> None:
    print("\033[2J\033[H", end="")


def _header(title: str) -> None:
    width = 62
    bar = "─" * width
    print(f"\n  {_CYAN}{_BOLD}┌{bar}┐")
    print(f"  │  {title:<{width - 2}}│")
    print(f"  └{bar}┘{_RESET}\n")


def _opt(key: str, label: str, color: str = _GREEN) -> None:
    print(f"  {color}{_BOLD}[{key}]{_RESET}  {label}")


def _prompt(question: str = "Choice") -> str:
    try:
        return input(f"\n  {_CYAN}▶ {question}: {_RESET}").strip()
    except (KeyboardInterrupt, EOFError):
        _goodbye()


def _back_prompt() -> None:
    input(f"\n  {_GREY}Press Enter to return to the menu…{_RESET}")
    _clear()


def _invalid() -> None:
    print(f"  {_RED}Invalid option. Please try again.{_RESET}")


def _goodbye() -> None:
    print(f"\n  {_CYAN}Goodbye.{_RESET}\n")
    sys.exit(0)
