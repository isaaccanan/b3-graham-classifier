# B3 Graham Classifier

A command-line tool that screens Brazilian B3 stocks using Benjamin Graham's value investing framework. It fetches data from three independent sources, cross-validates them, and classifies each stock with a buy/hold/sell signal.

> **Disclaimer:** This tool is for informational and educational purposes only. It does not constitute financial advice. Always consult a qualified financial advisor before making any investment decision. MIT License © 2026.

---

## Features

- Graham Number, P/E, P/B, P/E×P/B, D/E and Current Ratio criteria
- IPCA inflation adjustment (Adjusted Graham Number, Real Earnings Yield)
- Three-source cross-validation: Brapi + Fundamentus + Status Invest
- Divergence warnings when sources disagree — Fundamentus preferred (audited)
- **Sell signal** column: YES when price ≥ Graham Number
- Daily cache — never fetches the same ticker twice in one day
- Export to Google Sheets, Apple Numbers, and Excel (CSV)
- Rotating log file with per-run history
- Interactive terminal menu when run with no arguments

---

## Requirements

- Python 3.10+
- A free [Brapi](https://brapi.dev) account and API token

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Setup

1. Copy the example env file and add your token:

```bash
cp .env.example .env
```

2. Edit `.env`:

```
BRAPI_TOKEN=your_token_here
IPCA_RATE=0.045
# GRAHAM_DEBUG=1   # uncomment to enable DEBUG-level logging
```

> **Never commit `.env`** — it is gitignored.

---

## Usage

### Interactive menu (no arguments)

```bash
python main.py
```

Launches a guided menu with options to run analysis, view logs, and read the help manual.

### Command line

```bash
# Scan all Ibovespa tickers (~80)
python main.py

# Specific tickers
python main.py --tickers PETR4 VALE3 BBAS3

# Filter output by label
python main.py --filter "Strong Buy"

# Export summary CSV for Google Sheets
python main.py --tickers PETR4 VALE3 --summary results

# Export full detail CSV for Apple Numbers
python main.py --tickers PETR4 VALE3 --detail results --format numbers

# Export both summary and detail
python main.py --summary results --detail results --format excel

# Force cache refresh for specific tickers
python main.py --tickers PETR4 --flush PETR4

# Flush all requested tickers before running
python main.py --tickers PETR4 VALE3 --flush
```

### All options

| Flag | Description |
|---|---|
| `--tickers TICKER ...` | B3 tickers to analyse. Defaults to full Ibovespa list. |
| `--filter LABEL` | Show only stocks with this label. |
| `--summary FILE` | Save flat summary CSV (one row per stock). |
| `--detail FILE` | Save full Graham detail CSV (one section block per stock). |
| `--format FORMAT` | Export format: `google`, `numbers`, `excel`. Default: `google`. |
| `--flush [TICKER ...]` | Clear today's cache. Pass tickers or leave blank to flush all. |
| `--workers N` | Parallel fetch threads (default: 4). |
| `--no-color` | Disable ANSI colour output. |

---

## Output

### Terminal table

```
╭──────────┬─────────┬──────────────┬────────────────────┬───────────────────────┬─────────┬────────────┬─────────╮
│ Ticker   │ Price   │ Graham No.   │ Margin of Safety   │ GN/PE/PB/PEPB/DE/CR   │ Score   │ Label      │ Sell?   │
├──────────┼─────────┼──────────────┼────────────────────┼───────────────────────┼─────────┼────────────┼─────────┤
│ BBAS3    │ R$20.16 │ R$42.87      │ 53.0%              │ ✓/✓/✓/✓/?/?           │ 4/4     │ Strong Buy │ NO      │
│ PETR4    │ R$46.03 │ R$80.82      │ 43.0%              │ ✓/✓/✓/✓/✗/✗           │ 4/6     │ Buy        │ NO      │
│ VALE3    │ R$81.25 │ R$59.04      │ -37.6%             │ ✗/✗/✗/✗/✓/✗           │ 1/6     │ Avoid      │ YES     │
╰──────────┴─────────┴──────────────┴────────────────────┴───────────────────────┴─────────┴────────────┴─────────╯
```

### Labels

| Label | Meaning |
|---|---|
| **Strong Buy** | Price well below Graham Number. ≥ 83% of criteria pass. |
| **Buy** | Price below Graham Number. ≥ 66% of criteria pass. |
| **Hold** | Mixed signals. Neither clearly cheap nor expensive. |
| **Overvalued** | Trading above fair value by most Graham criteria. |
| **Avoid** | Fails most Graham criteria. Not a value opportunity. |
| **Inconclusive** | Some criteria pass but Graham Number cannot be calculated. |
| **Insufficient Data** | Not enough data from any source to classify. |

### Sell signal

| Sell? | Meaning |
|---|---|
| **NO** | Price < Graham Number — still undervalued, no exit signal. |
| **YES** | Price ≥ Graham Number — fair value reached, consider exiting. |
| **—** | Graham Number unavailable, signal cannot be determined. |

### Graham criteria

| Column | Criterion | Threshold |
|---|---|---|
| GN | Graham Number | Price < √(22.5 × EPS × BVPS) |
| PE | P/E Ratio | ≤ 15 |
| PB | P/B Ratio | ≤ 1.5 |
| PEPB | P/E × P/B | ≤ 22.5 |
| DE | Debt / Equity | ≤ 1.0 |
| CR | Current Ratio | ≥ 2.0 |

---

## Data sources

| Source | Role | URL |
|---|---|---|
| **Brapi** | Primary — live market data via REST API | brapi.dev |
| **Fundamentus** | Secondary — scraped fundamentals (audited balance sheets) | fundamentus.com.br |
| **Status Invest** | Tertiary — tiebreaker on divergence | statusinvest.com.br |
| **CVM** | Official — audited quarterly balance sheet (Total/Current Assets & Liabilities) | dados.cvm.gov.br |
| **overrides.json** | Manual fallback for banks with missing BVPS/EPS | local file |

### Cross-validation tolerances

| Field | Tolerance |
|---|---|
| Price | ±2% |
| Ratios (P/E, P/B, EPS, BVPS) | ±5% |

On divergence between Brapi and Fundamentus, Fundamentus is preferred unless Status Invest agrees with Brapi — in which case Brapi wins.

---

## Export formats

| Format | Separator | Encoding | Best for |
|---|---|---|---|
| `google` | `;` | UTF-8 BOM | Google Sheets |
| `numbers` | `,` | UTF-8 | Apple Numbers (macOS) |
| `excel` | `;` | UTF-8 BOM | Microsoft Excel |

All exports are saved to the `exports/` folder with the pattern:
```
exports/<format>_<type>_<YYYYMMDD>_<basename>.csv
```

**Google Sheets import:** File → Import → Upload → select file → Replace spreadsheet.

---

## Cache

Each ticker is cached once per calendar day (Brapi, Fundamentus, and Status Invest separately). Cache files live in `cache/`.

Force a refresh:
```bash
# Specific tickers
python main.py --tickers PETR4 --flush PETR4

# All tickers in the run
python main.py --tickers PETR4 VALE3 --flush
```

---

## Logs

Rotating log file at `logs/classifier.log` (1 MB per file, 5 backups).

View logs from the interactive menu (option 2) or inspect directly:
```bash
tail -50 logs/classifier.log
```

---

## Project structure

```
b3-graham-classifier/
├── main.py           # CLI entry point and table output
├── menu.py           # Interactive terminal menu
├── brapi.py          # Primary data source (Brapi REST API)
├── fundamentus.py    # Secondary data source (Fundamentus scraper)
├── statusinvest.py   # Tertiary data source (Status Invest scraper)
├── validator.py      # Three-source cross-validation
├── classifier.py     # Graham calculations and scoring
├── exporter.py       # CSV export (google / numbers / excel)
├── config.py         # Thresholds, constants, env loading
├── tickers.py        # Ibovespa ticker list
├── overrides.json    # Manual VPA/LPA overrides for banks
├── exports/          # All generated CSV files (gitignored)
├── cache/            # Daily cache files (gitignored)
├── logs/             # Rotating log files (gitignored)
├── .env              # Your BRAPI_TOKEN (gitignored — never commit)
├── .env.example      # Template for .env
└── requirements.txt
```

---

## License

MIT License © 2026 Isaac Canan — see [LICENSE](LICENSE) for full terms including the investment disclaimer.
