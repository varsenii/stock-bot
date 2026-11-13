# Stock Bot

A daily European/UK stock scanner with LLM-powered price-decline analysis.

1. **Scan** — finds stocks trading ≥ 20 % below their 52-week high using Yahoo
   Finance's screener API.
2. **Analyse** — for each candidate, searches the web (DuckDuckGo) for recent
   news and asks a local LLM (Ollama) to explain why the price dropped.
   Results are written as per-company markdown reports.

## Quick start (Docker)

```bash
# 1. Build the image (installs Python deps + Ollama)
./docker/build.sh

# 2. Enter the container (starts Ollama, pulls the model on first run)
./docker/run.sh

# Inside the container:
python3 __main__.py scan                     # run the screener
python3 __main__.py analyze                  # analyse all candidates
python3 __main__.py analyze --max-records 5  # analyse the first 5 only
```

The container mounts the project directory, so code edits are reflected
immediately — no rebuild needed (only rebuild after `requirements.txt`
changes).

### What happens on `./docker/run.sh`

1. Ollama server starts in the background.
2. The model from `analysis_config.yaml` is pulled if not already cached
   (stored in a Docker volume, so it's a one-time download).
3. You're dropped into an interactive bash shell.

### GPU access

`run.sh` passes `--gpus all` to Docker.
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
must be installed on the host.

## Quick start (venv)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install Ollama (https://ollama.com/download)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:8b

python3 __main__.py scan
python3 __main__.py analyze
```

## How the scanner works

```
Yahoo screener  (server-side filters: region, volume, price, P/E, FCF, Net Debt/EBITDA)
      ↓
Paginated quotes  (250 per page — price, 52w range, fundamentals, liquidity)
      ↓
Local drawdown filter  (current price / 52w HIGH − 1  ≤  −min_drawdown_pct%)
Local P/E filter       (discard if EPS unknown or negative)
      ↓
Parallel Ticker.info   (FCF, LFCF, historical FCF, debt, sector, industry)
Local FCF filter       (discard if TTM FCF unavailable)
Local FCF CAGR filter  (discard if CAGR < min_fcf_cagr)
      ↓
Excel workbook  →  output/stock_scan_YYYY-MM-DD.xlsx
```

## How the analyser works

```
Latest .xlsx from output/
      ↓
For each candidate:
      ↓
DuckDuckGo search  (news + web results for "{company} {ticker} stock decline")
      ↓
Prompt = stock data + search results
      ↓
Local LLM (Ollama, qwen3:8b)  →  structured analysis
      ↓
Markdown report  →  reports/<Company_Name>_<TICKER>.md
```

The LLM receives the stock's metrics and recent search results in its prompt,
then produces a structured analysis with primary causes, contributing factors,
and market context.

## Configuration

### `scan_config.yaml` — scanner settings

```yaml
regions:
  - eu
  - gb

max_results: 250
min_drawdown_pct: 20

filters:
  min_avg_daily_volume: 1000
  max_price: 100
  max_pe_ratio: 20
  min_fcf: 0
  max_net_debt_to_ebitda: 2

local_filters:
  min_fcf_cagr: 0

sort:
  field: avgdailyvol3m
  ascending: false

output_dir: output
```

### `analysis_config.yaml` — LLM analysis settings

```yaml
llm:
  provider: ollama
  model: qwen3:8b          # change model here
  host: http://localhost:11434
  temperature: 0.3
  num_predict: 2048
  num_ctx: 32768

search:
  provider: duckduckgo
  max_results: 8
  region: wt-wt

analysis:
  max_records: null         # null = process all; set a number to limit
  input_dir: output
  output_dir: reports
```

#### Recommended models (RTX 3080 Laptop, 16 GB VRAM)

| Model | VRAM | Notes |
|---|---|---|
| `qwen3:8b` | ~5 GB | Default. Good reasoning, fast |
| `qwen3:14b` | ~9 GB | Stronger reasoning, still fits |
| `mistral-nemo` | ~8 GB | Good alternative |
| `llama3.1:8b` | ~5 GB | Maximum VRAM headroom |

#### Custom system prompt

Override the built-in prompt in `analysis_config.yaml`:

```yaml
prompts:
  price_decline_analyst:
    system: |
      You are a financial analyst.  …your instructions here…
```

### CLI overrides

```bash
# Scanner
python3 __main__.py scan --min-drawdown 30
python3 __main__.py scan --regions de,fr,nl
python3 __main__.py scan --max-results 1000

# Analyser
python3 __main__.py analyze --max-records 10
python3 __main__.py analyze --model qwen3:14b
python3 __main__.py analyze --output-dir /tmp/reports
```

## Project structure

```
stock-bot/
├── __main__.py                  Entry point
├── cli.py                       CLI: scan + analyze subcommands
├── scan_config.yaml             Scanner configuration
├── analysis_config.yaml         LLM analysis configuration
├── requirements.txt
├── .ollama_api_key              Ollama API key (gitignored)
│
├── scanning/                    Stock screening package
│   ├── config.py                ScanConfig dataclass
│   ├── models.py                StockResult, ScanFailure
│   ├── scanner.py               Scanner orchestrator
│   ├── filters.py               Screener filter registry
│   ├── providers/
│   │   ├── base.py              UniverseProvider, PriceProvider ABCs
│   │   └── yahoo.py             Yahoo Finance implementation
│   └── exporters/
│       ├── base.py              BaseExporter ABC
│       └── excel.py             Formatted Excel exporter
│
├── analysis/                    LLM analysis package
│   ├── config.py                AnalysisConfig, LLMConfig, SearchConfig
│   ├── analyzer.py              Analysis orchestrator
│   ├── reader.py                Reads latest scan .xlsx
│   ├── prompts.py               System/user prompt templates
│   ├── reporter.py              Markdown report writer
│   ├── llm/
│   │   ├── base.py              BaseLLM ABC
│   │   └── ollama.py            Ollama backend
│   └── search/
│       ├── base.py              BaseSearchProvider ABC
│       └── duckduckgo.py        DuckDuckGo search
│
├── docker/
│   ├── Dockerfile
│   ├── build.sh
│   ├── run.sh
│   └── entrypoint.sh
│
├── output/                      Scan results (.xlsx)
└── reports/                     Analysis reports (.md)
```

## Output columns (Excel)

| Column | Description |
|---|---|
| Company Name | Full company name |
| Symbol | Ticker (e.g. `VOD.L`, `ENEL.MI`) |
| Currency | Trading currency (`EUR`, `GBp`, `NOK`) |
| Sector / Industry | Classification |
| Current Close | Last closing price |
| 52-Week High / Low | Price range |
| Drawdown % | Drop from 52-week high (negative) |
| P/E Ratio | Trailing P/E (TTM) |
| Dividend Yield % | Annual yield |
| Market Cap | In local currency |
| Last / Next Earnings | Earnings dates |
| FCF / LFCF (TTM) | Free cash flow metrics |
| P/FCF, P/LFCF | Valuation ratios |
| FCF CAGR %, FCF CV % | Cash flow growth and stability |
| Rev CAGR %, Rev CV % | Revenue growth and stability |
| Total Debt, Net Debt | Balance sheet (MRQ) |
| Debt/Equity, Net Debt/EBITDA | Leverage ratios |
| Avg Vol, Bid/Ask, Spread | Liquidity metrics |

## Server-side filter keys

| Key | Description | Direction |
|---|---|---|
| `min_avg_daily_volume` | 3-month avg daily volume | min |
| `min_price` / `max_price` | Stock price | min / max |
| `max_pe_ratio` | P/E ratio (TTM) | max |
| `min_fcf` | Free Cash Flow (TTM) | min |
| `min_levered_fcf` | Levered FCF (TTM) | min |
| `max_net_debt_to_ebitda` | Net Debt / EBITDA (TTM) | max |
| `max_price_to_book` | Price-to-book (quarterly) | max |
| `max_debt_to_equity` | Total debt / equity (TTM) | max |
| `min_return_on_equity` | Return on equity (TTM) | min |
| `min_market_cap` / `max_market_cap` | Market cap | min / max |

## Extending

### New search provider

1. Subclass `BaseSearchProvider` in `analysis/search/`.
2. Implement `search()` returning `list[SearchResult]`.
3. Wire it up in `cli.py`.

### New LLM backend

1. Subclass `BaseLLM` in `analysis/llm/`.
2. Implement `generate()` and `is_available()`.
3. Wire it up in `cli.py`.

### New analyst role

1. Add a system prompt constant and user prompt builder in `analysis/prompts.py`.
2. Reference it in the Analyzer or a future role registry.

### New screener filter

1. Add an entry to `FILTER_REGISTRY` in `scanning/filters.py`.
2. Add the key to `filters:` in `scan_config.yaml`.

## Important limitations

- Yahoo Finance's screener API is **unofficial** and can change or rate-limit.
- The drawdown filter is applied **locally** — increase `max_results` to scan
  more of the catalogue.
- **UK prices** are in GBp (pence). `max_price: 100` = 100p = £1.
- **DuckDuckGo search** may return no results for very obscure companies.
  The LLM will still produce an analysis from the stock data alone.
- **LLM analysis** is only as good as the model and the search results.
  Always verify with primary sources.
- Intended for personal research. Not financial advice.

## Run daily (cron)

```cron
# Scan after European market close, then analyse
30 20 * * 1-5 cd /path/to/stock-bot && ./docker/run.sh -c 'python3 __main__.py scan && python3 __main__.py analyze' >> bot.log 2>&1
```
