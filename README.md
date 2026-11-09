# European Stock Scanner — v2

A daily end-of-day scanner that finds European/UK shares trading at least 20%
below their 52-week high.  It runs entirely from Yahoo Finance's screener API —
no price-history downloads, minimal rate-limiting risk.

## How it works

```
Yahoo screener  (server-side filters: region, volume, price, P/E, FCF, Net Debt/EBITDA)
      ↓
Paginated quotes  (250 per page — price, 52w range, fundamentals, liquidity)
      ↓
Local drawdown filter  (current price / 52w HIGH − 1  ≤  −min_drawdown_pct%)
Local P/E filter       (discard if EPS unknown or negative)
      ↓
Parallel Ticker.info   (FCF, LFCF, historical FCF, debt, sector, industry — one call per candidate)
Local FCF filter       (discard if TTM FCF data unavailable)
Local FCF CAGR filter  (discard if CAGR < min_fcf_cagr and CAGR is computable)
      ↓
Excel workbook    (candidates, all scanned, failures)
```

1. Sends a filtered screener query to Yahoo Finance.  Region, volume, price,
   P/E, FCF > 0, and Net Debt/EBITDA filters are evaluated **server-side**.
2. Paginates through results (250 per page).  Every quote contains current
   price, currency, 52-week range, fundamentals, and liquidity data.
3. Applies the drawdown filter **locally** using `fiftyTwoWeekHighChangePercent`
   (precise drop from the 52-week high).  Stocks with unknown P/E are discarded.
4. Fetches FCF, Levered FCF, historical annual FCF (for CAGR), total debt,
   net debt, sector, and industry via parallel `Ticker.info` calls.
   Stocks with no TTM FCF data are discarded.
5. Optionally discards stocks where the FCF CAGR is computable and below the
   configured threshold (stocks with a negative first/last FCF are kept — CAGR
   is undefined for them).
6. Writes a formatted Excel workbook `output/stock_scan_YYYY-MM-DD.xlsx`.

## Output columns

| # | Column | Period | Description |
|---|---|---|---|
| 1 | Company Name | — | Full company name |
| 2 | Symbol | — | Ticker (e.g. `VOD.L`, `ENEL.MI`) |
| 3 | **Currency** | — | Trading currency (e.g. `EUR`, `GBp`, `NOK`) ¹ |
| 4 | Sector | — | e.g. "Basic Materials" |
| 5 | Industry | — | e.g. "Other Industrial Metals & Mining" |
| 6 | Latest Price Date | — | Date of the price data |
| 7 | Current Close | — | Last closing price |
| 8 | 52-Week High | — | Highest price in the last 52 weeks |
| 9 | 52-Week Low | — | Lowest price in the last 52 weeks |
| 10 | Drawdown % | — | Drop from 52-week high (negative = below high) |
| 11 | P/E Ratio | TTM | `price / EPS TTM` ² |
| 12 | Dividend Yield % | — | Annual dividend yield in % |
| 13 | Market Cap | — | Market capitalisation in local currency |
| 14 | FCF (TTM) | TTM | Free Cash Flow — operating CF − CapEx |
| 15 | LFCF (TTM) | TTM | Levered FCF — FCF after debt payments |
| 16 | P/FCF | TTM | `market_cap / FCF` (blank if FCF ≤ 0) |
| 17 | P/LFCF | TTM | `market_cap / LFCF` (blank if LFCF ≤ 0) |
| 18 | **FCF CAGR %** | Multi-yr | Annualised FCF growth rate ³ |
| 19 | Total Debt (MRQ) | MRQ | Total interest-bearing debt |
| 20 | Net Debt (MRQ) | MRQ | `totalDebt − totalCash` |
| 21 | Debt/Equity (MRQ) | MRQ | Total debt / equity (ratio, e.g. 1.47) |
| 22 | Net Debt/EBITDA (MRQ/TTM) | Mixed ⁴ | `Net Debt MRQ / EBITDA TTM` |
| 23 | Avg Vol (3M) | 3M avg | Average daily share volume |
| 24 | Avg Vol (10D) | 10D avg | Average daily share volume |
| 25 | Bid | — | Best bid price |
| 26 | Ask | — | Best ask price |
| 27 | Bid-Ask Spread | — | `ask − bid` (absolute) |
| 28 | Spread % | — | `(ask − bid) / mid × 100` |
| 29 | Avg Daily Value (3M) | 3M | ≈ ADTV: `50-day avg price × 3M avg volume` |
| 30 | Today's Value | Today | `current price × today's volume` |

¹ `GBp` = British pence (UK stocks). Price in pence, not pounds.

² For UK stocks (GBp vs GBP): the server-side P/E filter uses Yahoo's adjusted
value; the output column divides the pence price by 100 before computing.

³ **FCF CAGR:** `(FCF_last / FCF_first)^(1/n_years) − 1`.  Computed from the
oldest to most recent fiscal year in the annual cash flow statement (up to 5
years).  If either endpoint is negative or zero, CAGR is left blank (the stock
is still included).

⁴ **Net Debt/EBITDA period mismatch:** the output column uses MRQ net debt
divided by TTM EBITDA.  The server-side filter uses Yahoo's fully TTM figure.
Values may differ — the server-side filter is authoritative.

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

filters:                   # server-side Yahoo Finance filters
  min_avg_daily_volume: 1000
  max_price: 100           # note: UK stocks in GBp (pence)
  max_pe_ratio: 20
  min_fcf: 0               # FCF (unlevered, TTM) > 0
  max_net_debt_to_ebitda: 2

local_filters:             # applied after Ticker.info enrichment
  min_fcf_cagr: 0          # FCF CAGR ≥ 0% (non-declining); null = disable

sort:
  field: avgdailyvol3m    # most liquid stocks fetched first
  ascending: false

output_dir: output
```

### Server-side filter keys

| Key | Period | Description | Direction |
|---|---|---|---|
| `min_avg_daily_volume` | 3M | 3-month average daily volume | min |
| `min_price` | — | Stock price | min |
| `max_price` | — | Stock price | max |
| `max_pe_ratio` | TTM | P/E ratio | max |
| `min_fcf` | TTM | Free Cash Flow (unlevered) | min |
| `min_levered_fcf` | TTM | Levered Free Cash Flow | min |
| `max_net_debt_to_ebitda` | TTM | Net Debt / EBITDA | max |
| `max_price_to_book` | Quarterly | Price-to-book ratio | max |
| `max_debt_to_equity` | TTM | Total debt / equity | max |
| `min_return_on_equity` | TTM | Return on equity | min |
| `min_market_cap` | — | Market capitalisation | min |
| `max_market_cap` | — | Market capitalisation | max |

### Local post-filter keys

| Key | Description |
|---|---|
| `min_fcf_cagr` | FCF CAGR ≥ N%.  Stocks with undefined CAGR (negative endpoint) are **kept**.  Set to `null` to disable. |

> **UK price caveat:** UK stocks (`.L` tickers) are priced in **GBp (pence)**.
> `max_price: 100` = 100 pence = £1.  To include UK stocks up to £100, use
> `max_price: 10000`.

### Sort field options

| `sort.field` | Effect |
|---|---|
| `avgdailyvol3m` | Most liquid stocks first (default) |
| `intradaymarketcap` | Largest companies first |
| `intradayprice` | Highest-priced stocks first |
| `percentchange` | Biggest daily movers first |

### Understanding `max_results`

The drawdown filter is applied **locally**, so the scanner pages through the
screener catalogue.  `max_results` caps how many tickers are fetched.

With all default filters active, the screener returns a reduced universe.
At 20% drawdown, roughly 1 in 5 qualifying stocks make the cut, so:

| `max_results` | Approx. candidates |
|---|---|
| 500 | ~50–100 |
| 2500 | ~250–500 |
| 7000 | all available |

## Project structure

```
stock-bot/
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

- Yahoo Finance's screener endpoint is **unofficial**.
  The API can change, rate-limit, or block automated requests at any time.
- The drawdown filter is applied **locally**.  Increase `max_results` to scan
  more of the catalogue.
- **P/E Ratio** in the output is computed as `price / EPS TTM` and may be
  inaccurate for UK stocks (GBp vs GBP).  The server-side filter is accurate.
- **UK price filter:** `max_price: 100` = 100 pence, not £100.
- **Net Debt/EBITDA column** uses MRQ net debt; the filter uses TTM net debt.
- **FCF CAGR:** blank when either the first or last fiscal-year FCF is negative.
  The stock is still included — only the column is blank.
- **Avg Daily Value** is an approximation: `50-day avg price × 3M avg volume`.
- **Bid/Ask/Spread** are delayed (15 min) and may not be available after close.
- Intended for personal research.  Verify candidates with your broker.

## Setup

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```bash
cd stock-bot
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
30 20 * * 1-5 cd /path/to/stock-bot && .venv/bin/python cli.py >> scanner.log 2>&1
```

### Windows Task Scheduler

1. **Trigger:** Daily at 20:30 (after European market close).
2. **Program:** full path to `.venv\Scripts\python.exe`.
3. **Arguments:** `cli.py`.
4. **Start in:** `stock-bot/` folder.

## Extending the scanner

### Adding a new server-side screener filter

1. Add an entry to `FILTER_REGISTRY` in `scanning/filters.py`.
2. Add the key with a value (or `null`) to the `filters:` section of `scan_config.yaml`.

### Adding a new local post-filter

1. Add a field to `ScanConfig` in `scanning/config.py`.
2. Apply the filter in `_enrich_with_fcf()` in `scanning/providers/yahoo.py`.
3. Read the value from `local_filters:` in `scan_config.yaml` via `cli.py`.

### Adding a new data provider

1. Subclass `UniverseProvider` / `PriceProvider` in `scanning/providers/`.
2. Override `get_precomputed_results()` to return `StockResult` objects.
3. Replace `YahooProvider()` in `cli.py`.

## Calculation notes

| Column | Formula / Source |
|---|---|
| Drawdown % | `fiftyTwoWeekHighChangePercent × 100` |
| P/E Ratio | `price_in_reporting_currency / epsTrailingTwelveMonths` |
| Dividend Yield % | `dividendYield` (already in %, e.g. `7.60` = 7.60%) |
| Market Cap | `marketCap` in local currency units |
| FCF (TTM) | `freeCashflow` from `Ticker.info` (unlevered, TTM) |
| LFCF (TTM) | `leveredFreeCashFlow` from `Ticker.info` (TTM) |
| P/FCF | `marketCap / FCF` |
| P/LFCF | `marketCap / LFCF` |
| FCF CAGR % | `(FCF_last / FCF_first)^(1/n_years) − 1` × 100; blank if either endpoint ≤ 0 |
| Total Debt (MRQ) | `totalDebt` from `Ticker.info` (MRQ) |
| Net Debt (MRQ) | `totalDebt − totalCash` (both MRQ) |
| Debt/Equity (MRQ) | `debtToEquity / 100` (MRQ, converted from %) |
| Net Debt/EBITDA (MRQ/TTM) | `(totalDebt − totalCash) / ebitda` |
| Avg Daily Value (3M) | `fiftyDayAverage × averageDailyVolume3Month` |
| Today's Value | `regularMarketPrice × regularMarketVolume` |
| Bid-Ask Spread | `ask − bid` |
| Spread % | `(ask − bid) / ((ask + bid) / 2) × 100` |

## Suggested next versions

- Persistent cache to avoid re-querying unchanged data daily.
- Second independent data source for cross-verification.
- Alert only when a symbol **newly** crosses the threshold.
- AI-powered analysis layer for candidate ranking and commentary.
