# European Stock Scanner — v2

A daily end-of-day scanner that finds European/UK shares trading at least 20%
below their 52-week high.  It runs entirely from Yahoo Finance's screener API —
no price-history downloads, minimal rate-limiting risk.

## How it works

```
Yahoo screener  (server-side filters: region, volume, P/E)
      ↓
Paginated quotes  (250 per page — price, 52w range, fundamentals, liquidity)
      ↓
Local drawdown filter  (current price / 52w HIGH − 1  ≤  −min_drawdown_pct%)
Local P/E filter       (discard if EPS unknown or negative)
      ↓
Excel workbook    (candidates, all scanned, failures)
```

1. Sends a filtered screener query to Yahoo Finance.  Region, volume, and P/E
   filters are evaluated **server-side**.  Results are sorted by the configured
   `sort.field` before pagination.
2. Paginates through results (250 per page).  Every quote already contains
   current price, 52-week range, fundamentals, and liquidity data —
   **no extra API requests needed**.
3. Applies the drawdown filter **locally** using `fiftyTwoWeekHighChangePercent`
   — the precise percentage drop from the **52-week high** (not from 52 weeks
   ago).  Stocks with unknown P/E are also discarded at this stage.
4. Writes a single formatted Excel workbook `output/stock_scan_YYYY-MM-DD.xlsx`
   with three sheets:
   - **Candidates (≥N% DD)** — stocks meeting the drawdown threshold
   - **All Scanned** — every stock returned by the screener
   - **Failures** — empty in screener mode

## Output columns

| Column | Description |
|---|---|
| Company Name | Full company name |
| Symbol | Ticker (e.g. `VOD.L`, `ENEL.MI`) |
| Latest Price Date | Date of the price data |
| Current Close | Last closing price |
| 52-Week High | Highest price in the last 52 weeks |
| 52-Week Low | Lowest price in the last 52 weeks |
| Drawdown % | Drop from 52-week high (negative = below high) |
| P/E Ratio | Trailing P/E computed as `price / EPS TTM` ¹ |
| Dividend Yield % | Annual dividend yield in % |
| Market Cap | Market capitalisation in local currency |
| Avg Vol (3M) | Average daily share volume, 3-month window |
| Avg Vol (10D) | Average daily share volume, 10-day window |
| Bid | Best bid price |
| Ask | Best ask price |
| Bid-Ask Spread | `ask − bid` (absolute) |
| Spread % | `(ask − bid) / mid × 100` (relative cost of trading) |
| Avg Daily Value (3M) | ≈ ADTV in currency: `50-day avg price × 3M avg volume` |
| Today's Value | `current price × today's volume` |

¹ For UK stocks priced in GBp (pence) with EPS in GBP, the P/E may be ~100×
off. The server-side P/E filter (`max_pe_ratio`) uses Yahoo's correctly-adjusted
value.

The workbook is formatted with bold headers, frozen panes, alternating row
fills, number formats per column type, and a green→yellow→red colour scale on
the Drawdown % column.

## Configuration — `scan_config.yaml`

**This is the only file you need to edit.**  No code changes, no CLI flags.

```yaml
regions:
  - eu      # expands to all 24 European country codes
  - gb

max_results: 2500          # max tickers to fetch from screener

min_drawdown_pct: 20       # stocks at least this % below 52-week high

filters:
  min_avg_daily_volume: 1000   # removes illiquid instruments
  max_pe_ratio: 20             # set to null to include all companies

sort:
  field: avgdailyvol3m    # most liquid stocks fetched first
  ascending: false        # false = highest value first

output_dir: output
```

### Filter keys

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

### Sort field options

| `sort.field` | Effect |
|---|---|
| `avgdailyvol3m` | Most liquid stocks first (default) |
| `intradaymarketcap` | Largest companies first |
| `intradayprice` | Highest-priced stocks first |
| `percentchange` | Biggest daily movers first |

### Understanding `max_results`

The drawdown filter is applied **locally** (not by Yahoo's server), so the
scanner pages through the screener catalogue to find qualifying stocks.
`max_results` caps how many tickers are fetched.

The screener returns ~6,700 liquid profitable European stocks (with the default
filters).  At 20% drawdown, roughly 1 in 5 stocks qualify, so:

| `max_results` | Tickers scanned | Approx. candidates |
|---|---|---|
| 500 | 500 (8%) | ~88 |
| 2500 | 2,500 (37%) | ~440 |
| 7000 | 6,700 (100%) | ~1,200 |

Set `max_results: 7000` to scan the entire available catalogue.

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

## Important limitations

- Yahoo Finance's screener endpoint is **unofficial** for this use.
  The API can change, rate-limit, or block automated requests at any time.
- The drawdown filter is applied **locally** using `fiftyTwoWeekHighChangePercent`
  (drop from the 52-week high).  There is no server-side drawdown filter.
  Increase `max_results` to scan more of the catalogue.
- **P/E Ratio** in the output is computed locally as `price / EPS TTM` and
  may be inaccurate for UK stocks (GBp vs GBP currency mismatch).
- **Avg Daily Value** is an approximation: `50-day avg price × 3-month avg volume`.
  It is not a direct market data point.
- **Bid/Ask/Spread** are delayed (15 min for most European exchanges) and may
  not be available after market close.
- `eu` expands to 24 individual country codes.  This is not a certified
  complete directory of every European listing.
- Intended for personal research.  Verify candidates with your broker.
  Check data providers' terms before commercial use.

## Setup

Use Python 3.10 or newer.

**Windows (PowerShell)**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
cd stock_bot
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
python cli.py
```

The scanner reads all parameters from `scan_config.yaml`.

### Optional CLI overrides

```bash
python cli.py --min-drawdown 30
python cli.py --regions de,fr,nl
python cli.py --max-results 1000
python cli.py --output-dir /data/scans
python cli.py --symbols-file my_symbols.csv   # bypasses screener
```

## Run daily

### Linux / macOS cron

```cron
30 20 * * 1-5 cd /path/to/stock_bot && .venv/bin/python cli.py >> scanner.log 2>&1
```

### Windows Task Scheduler

1. **Trigger:** Daily at 20:30 (after European market close).
2. **Program:** full path to `.venv\Scripts\python.exe`.
3. **Arguments:** `cli.py`.
4. **Start in:** `stock_bot/` folder.

## Extending the scanner

### Adding a new screener filter

1. Add an entry to `FILTER_REGISTRY` in `scanning/filters.py`.
2. Add the key with a value (or `null`) to `scan_config.yaml`.

### Adding a new data provider

1. Subclass `UniverseProvider` / `PriceProvider` in a new file under `scanning/providers/`.
2. Override `get_precomputed_results()` to return `StockResult` objects directly.
3. Replace `YahooProvider()` in `cli.py`.

### Adding a new output format

1. Subclass `BaseExporter` in a new file under `scanning/exporters/`.
2. Register it in `scanning/exporters/__init__.py`.
3. Replace `ExcelExporter()` in `cli.py`.

## Calculation notes

| Column | Formula |
|---|---|
| Drawdown % | `fiftyTwoWeekHighChangePercent × 100` |
| P/E Ratio | `regularMarketPrice / epsTrailingTwelveMonths` |
| Dividend Yield % | `dividendYield` (already in %, e.g. `7.60` = 7.60%) |
| Market Cap | `marketCap` in local currency units |
| Avg Daily Value (3M) | `fiftyDayAverage × averageDailyVolume3Month` |
| Today's Value | `regularMarketPrice × regularMarketVolume` |
| Bid-Ask Spread | `ask − bid` |
| Spread % | `(ask − bid) / ((ask + bid) / 2) × 100` |

## Suggested next versions

- Fundamental filters (P/FCF, revenue trend, margins, Altman Z-score).
- Persistent cache to avoid re-querying unchanged data daily.
- Second independent data source for cross-verification.
- Alert only when a symbol **newly** crosses the threshold.
- AI-powered analysis layer for candidate ranking and commentary.
