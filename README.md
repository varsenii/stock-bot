# European Stock Scanner — v2

A daily end-of-day scanner that finds European/UK shares trading at least 20%
below their 52-week high.  It runs entirely from Yahoo Finance's screener API —
no price-history downloads, minimal rate-limiting risk.

## How it works

```
Yahoo screener  (server-side filters: region, volume, P/E, drawdown proxy)
      ↓
Paginated quotes  (250 per page — price, fundamentals, 52w range all included)
      ↓
Local refinement  (precise drawdown = current / 52w-high − 1)
      ↓
Excel workbook    (candidates, all scanned, failures)
```

1. Sends a filtered screener query to Yahoo Finance.  All criteria in
   `scan_config.yaml` (regions, volume, P/E, drawdown) are evaluated
   **server-side** — only matching stocks are returned.
2. Paginates through results (250 per page).  Every quote already contains
   price, 52-week range, fundamentals, and market cap — **no extra requests**.
3. Re-checks each quote's precise `fiftyTwoWeekHighChangePercent` locally
   (the server-side drawdown filter uses year-over-year change as a proxy).
4. Writes a single formatted Excel workbook `output/stock_scan_YYYY-MM-DD.xlsx`
   with three sheets:
   - **Candidates (≥N% DD)** — stocks meeting the drawdown threshold
   - **All Scanned** — every stock returned by the screener
   - **Failures** — empty in screener mode

   **Output columns:**
   Company Name · Symbol · Latest Price Date · Current Close ·
   52-Week High · 52-Week Low · Drawdown % · P/E Ratio ·
   Dividend Yield % · Market Cap

   The workbook is formatted with bold headers, frozen panes, alternating row
   fills, and a green→yellow→red colour scale on the Drawdown % column.

## Configuration — `scan_config.yaml`

**This is the only file you need to edit.**  No code changes, no CLI flags.

```yaml
# Regions to scan ('eu' expands to all 24 European country codes)
regions:
  - eu
  - gb

max_results: 2500          # max tickers to fetch from screener
min_drawdown_pct: 20       # stocks at least this % below 52-week high

filters:
  min_avg_daily_volume: 1000   # removes illiquid instruments
  max_pe_ratio: 20             # set to null to include all companies

output_dir: output
```

### Available filter keys

| Key | Description | Direction |
|---|---|---|
| `min_avg_daily_volume` | 3-month average daily volume | min |
| `max_pe_ratio` | P/E ratio (trailing twelve months) | max |
| `max_price_to_book` | Price-to-book ratio | max |
| `max_debt_to_equity` | Total debt / equity | max |
| `min_return_on_equity` | Return on equity | min |
| `min_market_cap` | Market capitalisation | min |
| `max_market_cap` | Market capitalisation | max |

Set any value to `null` to disable that filter.

## Project structure

```
stock_bot/
├── scan_config.yaml         ← edit this to change scan parameters
├── __main__.py              Entry point (python -m stock_bot)
├── cli.py                   CLI argument parsing and component wiring
├── scanner.py               Deprecated shim (backward compat only)
├── requirements.txt
├── README.md
└── scanning/                Core scanning package
    ├── __init__.py          Public API
    ├── config.py            ScanConfig dataclass
    ├── filters.py           Filter registry (YAML keys → yfinance fields)
    ├── models.py            StockResult, ScanFailure dataclasses
    ├── scanner.py           Scanner orchestrator
    ├── providers/
    │   ├── base.py          UniverseProvider + PriceProvider ABCs
    │   └── yahoo.py         Yahoo Finance implementation
    └── exporters/
        ├── base.py          BaseExporter ABC
        └── excel.py         Formatted Excel exporter
```

The scanning logic is split along three pluggable seams:

| Concern | Interface | Default implementation |
|---|---|---|
| Universe / screener | `UniverseProvider` | `YahooUniverseProvider` |
| Price / OHLCV data | `PriceProvider` | `YahooPriceProvider` (fallback only) |
| Output format | `BaseExporter` | `ExcelExporter` |

## Important limitations

- Yahoo Finance's screener endpoint is **unofficial** for this use.
  The API can change, rate-limit, or block automated requests at any time.
- The drawdown filter uses `fiftytwowkpercentchange` (year-over-year change)
  as a **server-side proxy**.  The precise drawdown is re-checked locally from
  `fiftyTwoWeekHighChangePercent`.  A stock that briefly hit a new high and
  then fell may be missed if its year-over-year change is small.
- **P/E Ratio** is computed locally as `price / EPS TTM`.  For UK stocks
  priced in GBp (pence) with EPS reported in GBP (pounds), the computed P/E
  may be ~100× higher than the true value.  Treat it as an approximation.
- `eu` expands to 24 individual country codes.  This is not a certified
  complete directory of every European listing.
- Yahoo data can be delayed or unavailable for some symbols.  Verify any
  candidate against the exchange/broker before acting.
- This version screens **price only**.  It does not assess fundamentals beyond
  the filter criteria.
- Intended for personal research.  Check data providers' terms before
  commercial use or redistribution.

## Setup

Use Python 3.10 or newer.

**Windows (PowerShell)**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Run

```bash
cd stock_bot
source .venv/bin/activate   # or .venv\Scripts\Activate.ps1 on Windows
python cli.py
```

The scanner reads all parameters from `scan_config.yaml`.  Edit that file to
change regions, thresholds, or filters, then re-run.

### Optional CLI overrides

For one-off runs without editing the YAML:

```bash
python cli.py --min-drawdown 30
python cli.py --regions de,fr,nl
python cli.py --max-results 1000
python cli.py --output-dir /data/scans
```

Scan a hand-maintained list (bypasses screener, uses price-history downloads):

```bash
python cli.py --symbols-file my_symbols.csv
```

## Run daily

### Windows Task Scheduler

1. Open **Task Scheduler** → **Create Basic Task**.
2. Trigger: **Daily**, e.g. 20:30 local time (Europe/Rome).
3. Action: **Start a program** — full path to `.venv\Scripts\python.exe`.
4. Arguments: `cli.py`.
5. Start in: `stock_bot/` folder.

### Linux / macOS cron

```cron
30 20 * * 1-5 cd /path/to/stock_bot && .venv/bin/python cli.py >> scanner.log 2>&1
```

Output filenames are date-stamped so each run creates a separate snapshot.

## Extending the scanner

### Adding a new screener filter

1. Add an entry to `FILTER_REGISTRY` in `scanning/filters.py`.
2. Add the key with a value (or `null`) to `scan_config.yaml`.

### Adding a new data provider

1. Create `scanning/providers/my_provider.py`, subclass `UniverseProvider`
   and/or `PriceProvider`.
2. Override `get_precomputed_results()` to return `StockResult` objects
   directly from the data source (skips price downloads).
3. In `cli.py`, replace `YahooProvider()` with `MyProvider()`.

### Adding a new output format

1. Create `scanning/exporters/my_exporter.py`, subclass `BaseExporter`.
2. Register in `scanning/exporters/__init__.py`.
3. In `cli.py`, replace `ExcelExporter()` with `MyExporter()`.

## Calculation notes

- **Drawdown %** = `fiftyTwoWeekHighChangePercent × 100` from Yahoo's quote
  data (`current_price / 52w_high − 1`).
- **P/E Ratio** = `current_close / epsTrailingTwelveMonths`.  May be
  inaccurate for UK stocks (GBp vs GBP currency mismatch).
- **Dividend Yield %** = `dividendYield × 100` from Yahoo's quote data.
- **Market Cap** = `marketCap` in local currency units from Yahoo's quote.

## Suggested next versions

- Fundamental filters (P/FCF, revenue trend, margins, Altman Z-score).
- Persistent cache to avoid re-querying unchanged data daily.
- Second independent data source for cross-verification.
- Alert only when a symbol **newly** crosses the threshold.
- AI-powered analysis layer for candidate ranking and commentary.
