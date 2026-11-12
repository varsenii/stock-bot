"""
Yahoo Finance implementation of UniverseProvider and PriceProvider.

Universe discovery uses yfinance 1.x's built-in ``yf.screen()`` function with
``EquityQuery`` and pagination (250 results per page).

Key notes
---------
- The old ``eu`` region code (from yfinance-screener) no longer exists.
  Pass ``--regions eu`` and it will be expanded to all European country codes
  that Yahoo Finance recognises.  Individual ISO-2 codes (``de``, ``fr``, etc.)
  are also accepted and passed through directly.
- Company names are captured for free from screener quotes (``longName`` /
  ``shortName``) so the price provider never needs a separate ``.info`` call
  for most tickers.
- Price data uses yfinance's bulk ``yf.download()`` (1 year of daily OHLCV).

To replace Yahoo Finance, create a new module in this directory that
implements ``UniverseProvider`` and/or ``PriceProvider`` and wire it up in
``cli.py``.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf
from yfinance import EquityQuery

from ..filters import ACTIVE_FILTERS, ScreenerFilter
from ..models import ScanFailure, StockResult
from .base import PriceProvider, UniverseProvider


# ---------------------------------------------------------------------------
# Region expansion
# ---------------------------------------------------------------------------

# Individual ISO-2 country codes that Yahoo Finance recognises as "European"
# (source: EQUITY_SCREENER_EQ_MAP['region'] in yfinance.const).
_EU_COUNTRY_CODES: list[str] = [
    "at", "be", "ch", "cz", "de", "dk", "ee", "es", "fi", "fr",
    "gb", "gr", "hu", "ie", "is", "it", "lt", "lv", "nl", "no",
    "pl", "pt", "ro", "se",
]

# Allow callers to pass convenient shorthands that expand to multiple codes.
_REGION_ALIASES: dict[str, list[str]] = {
    "eu": _EU_COUNTRY_CODES,
    "europe": _EU_COUNTRY_CODES,
}


def _expand_regions(regions: list[str]) -> list[str]:
    """
    Expand shorthand region aliases and return a deduplicated list of
    ISO-2 country codes understood by yfinance's EquityQuery.

    ``eu`` and ``europe`` expand to all European country codes.
    Any other value is passed through unchanged (e.g. ``gb``, ``de``).
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for r in regions:
        codes = _REGION_ALIASES.get(r.lower(), [r.lower()])
        for code in codes:
            if code not in seen:
                seen.add(code)
                expanded.append(code)
    return expanded


# ---------------------------------------------------------------------------
# Screener pagination helpers
# ---------------------------------------------------------------------------

_PAGE_SIZE = 250    # Yahoo Finance maximum per request


def _filter_to_query(f: ScreenerFilter) -> EquityQuery:
    """Convert a ``ScreenerFilter`` dataclass to a yfinance ``EquityQuery``."""
    if f.operator == "is-in":
        values = f.value if isinstance(f.value, list) else list(f.value)
        return EquityQuery(f.operator, [f.field] + values)
    return EquityQuery(f.operator, [f.field, f.value])


def _build_query(
    country_codes: list[str],
    min_drawdown: float | None = None,
) -> EquityQuery:
    """
    Build an EquityQuery from the region list, ``ACTIVE_FILTERS``, and an
    optional drawdown pre-filter.

    - Region clause restricts to the requested country codes.
    - ``ACTIVE_FILTERS`` (defined in ``scanning/filters.py``) are applied
      server-side; edit that file to add/remove/tune criteria.
    - When *min_drawdown* is provided, a ``fiftytwowkpercentchange`` clause is
      added as a loose proxy; the precise drawdown is re-checked locally.
    """
    operands: list[EquityQuery] = [
        EquityQuery("is-in", ["region"] + country_codes),
    ]

    # Apply all active filters from the centralized filters module.
    for f in ACTIVE_FILTERS:
        operands.append(_filter_to_query(f))

    return EquityQuery("and", operands)


def _fetch_page(
    query: EquityQuery,
    offset: int,
    size: int,
    sort_field: str = "avgdailyvol3m",
    sort_ascending: bool = False,
) -> dict:
    """Fetch one page from the Yahoo Finance screener."""
    return yf.screen(
        query,
        offset=offset,
        size=size,
        sortField=sort_field,
        sortAsc=sort_ascending,
    ) or {}


def _paginated_screener(
    country_codes: list[str],
    max_results: int,
    page_size: int = _PAGE_SIZE,
    inter_page_pause: float = 0.4,
    min_drawdown: float | None = None,
    sort_field: str = "avgdailyvol3m",
    sort_ascending: bool = False,
) -> tuple[list[str], dict[str, str], list[StockResult]]:
    """
    Page through the Yahoo Finance screener until *max_results* symbols are
    collected or the catalogue is exhausted.

    When *min_drawdown* is provided, an additional ``fiftytwowkpercentchange``
    filter is added to the query so Yahoo pre-filters on the server side,
    and each quote is converted to a ``StockResult`` using the ``fiftyTwoWeekHighChangePercent``
    field (actual drawdown from 52-week high) rather than downloading price history.

    Returns
    -------
    symbols : list[str]
        Deduplicated, upper-cased ticker symbols (all pages, unfiltered).
    names : dict[str, str]
        symbol → company display name.
    results : list[StockResult]
        Pre-computed drawdown results (populated only when *min_drawdown* is set).
    """
    query = _build_query(country_codes, min_drawdown=min_drawdown)
    symbols: list[str] = []
    names: dict[str, str] = {}
    results: list[StockResult] = []
    seen: set[str] = set()
    offset = 0
    page_num = 0
    total_available: int | None = None
    today = pd.Timestamp.now().date().isoformat()

    while len(symbols) < max_results:
        fetch_size = min(page_size, max_results - len(symbols))
        page_num += 1

        try:
            response = _fetch_page(query, offset, fetch_size, sort_field, sort_ascending)
        except Exception as exc:
            logging.warning(
                "Screener page %d failed: %s — stopping pagination.", page_num, exc
            )
            break

        if total_available is None:
            total_available = response.get("total", 0)
            logging.info(
                "Screener reports %d stocks matching active filters (region, volume, P/E).",
                total_available,
            )

        quotes: list[dict] = response.get("quotes", [])
        if not quotes:
            break

        page_new = 0
        for q in quotes:
            sym = str(q.get("symbol", "")).strip().upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            symbols.append(sym)
            page_new += 1
            name = q.get("longName") or q.get("shortName") or ""
            if name:
                names[sym] = name

            if min_drawdown is not None:
                current_close = float(q.get("regularMarketPrice") or 0)
                high_52w = float(q.get("fiftyTwoWeekHigh") or 0)
                low_52w_raw = q.get("fiftyTwoWeekLow")
                low_52w = round(float(low_52w_raw), 6) if low_52w_raw is not None else None

                # fiftyTwoWeekHighChangePercent is a decimal, e.g. -0.97 = -97%
                drawdown_raw = q.get("fiftyTwoWeekHighChangePercent")
                if drawdown_raw is None and high_52w > 0 and current_close > 0:
                    drawdown_raw = (current_close / high_52w) - 1.0
                drawdown_pct = round(float(drawdown_raw or 0) * 100, 2)

                # Apply precise local filter (screener used year-over-year as proxy)
                if drawdown_pct > -abs(min_drawdown):
                    continue  # Doesn't actually meet the drawdown threshold

                # P/E: computed from price / EPS TTM.
                # UK stocks trade in GBp (pence) while EPS is reported in GBP
                # (pounds). Dividing by 100 brings both to the same unit.
                # Discard stocks where P/E cannot be determined.
                eps = q.get("epsTrailingTwelveMonths")
                pe_ratio: float | None = None
                if eps is not None and float(eps) > 0 and current_close > 0:
                    price_for_pe = current_close
                    if q.get("currency") == "GBp":
                        price_for_pe = current_close / 100.0  # pence → pounds
                    pe_ratio = round(price_for_pe / float(eps), 2)

                if pe_ratio is None:
                    continue  # unknown P/E — discard

                div_raw = q.get("dividendYield")
                dividend_yield = round(float(div_raw), 4) if div_raw else None

                market_cap_raw = q.get("marketCap")
                market_cap = int(market_cap_raw) if market_cap_raw is not None else None

                # --- Liquidity fields ---
                avg_vol_3m_raw = q.get("averageDailyVolume3Month")
                avg_volume_3m = int(avg_vol_3m_raw) if avg_vol_3m_raw is not None else None

                avg_vol_10d_raw = q.get("averageDailyVolume10Day")
                avg_volume_10d = int(avg_vol_10d_raw) if avg_vol_10d_raw is not None else None

                bid_raw = q.get("bid")
                ask_raw = q.get("ask")
                bid = round(float(bid_raw), 6) if bid_raw is not None else None
                ask = round(float(ask_raw), 6) if ask_raw is not None else None

                bid_ask_spread: float | None = None
                bid_ask_spread_pct: float | None = None
                if bid is not None and ask is not None and bid > 0 and ask > 0:
                    bid_ask_spread = round(ask - bid, 6)
                    mid = (ask + bid) / 2
                    bid_ask_spread_pct = round((ask - bid) / mid * 100, 4)

                # Approx ADTV: 50-day avg price × 3-month avg volume
                fifty_day_avg = q.get("fiftyDayAverage")
                avg_daily_value: float | None = None
                if fifty_day_avg is not None and avg_volume_3m is not None:
                    avg_daily_value = round(float(fifty_day_avg) * avg_volume_3m, 2)

                # Today's traded value: current price × today's volume
                today_vol_raw = q.get("regularMarketVolume")
                today_value: float | None = None
                if today_vol_raw is not None and current_close > 0:
                    today_value = round(current_close * int(today_vol_raw), 2)

                currency = q.get("currency") or None

                # --- Earnings dates (from screener quote — no extra call) ---
                def _ts_to_date(ts) -> str | None:
                    """Convert a Unix timestamp to an ISO date string."""
                    try:
                        return pd.Timestamp(int(ts), unit="s").date().isoformat()
                    except Exception:
                        return None

                last_earn_ts = q.get("earningsTimestamp")
                next_earn_ts = q.get("earningsTimestampStart")
                is_estimate_raw = q.get("isEarningsDateEstimate")

                last_earnings_date = _ts_to_date(last_earn_ts)
                next_earnings_date = _ts_to_date(next_earn_ts)
                is_earnings_estimate = bool(is_estimate_raw) if is_estimate_raw is not None else None

                # Sanity checks: last earnings should be in the past (≤ today);
                # next earnings should be in the future (≥ today).
                if last_earnings_date is not None and last_earnings_date > today:
                    last_earnings_date = None
                if next_earnings_date is not None and next_earnings_date < today:
                    next_earnings_date = None
                    is_earnings_estimate = None

                results.append(
                    StockResult(
                        name=name,
                        symbol=sym,
                        latest_price_date=today,
                        currency=currency,
                        current_close=round(current_close, 6),
                        high_52w=round(high_52w, 6),
                        low_52w=low_52w,
                        drawdown_pct=drawdown_pct,
                        pe_ratio=pe_ratio,
                        dividend_yield=dividend_yield,
                        market_cap=market_cap,
                        last_earnings_date=last_earnings_date,
                        next_earnings_date=next_earnings_date,
                        is_earnings_estimate=is_earnings_estimate,
                        avg_volume_3m=avg_volume_3m,
                        avg_volume_10d=avg_volume_10d,
                        bid=bid,
                        ask=ask,
                        bid_ask_spread=bid_ask_spread,
                        bid_ask_spread_pct=bid_ask_spread_pct,
                        avg_daily_value=avg_daily_value,
                        today_value=today_value,
                    )
                )

        logging.info(
            "Screener page %d: +%d tickers  (collected: %d / %s)",
            page_num,
            page_new,
            len(symbols),
            total_available if total_available is not None else "?",
        )

        # Stop if we've received fewer results than requested (last page).
        if len(quotes) < fetch_size:
            break

        offset += len(quotes)
        if total_available is not None and offset >= total_available:
            break

        if inter_page_pause > 0:
            time.sleep(inter_page_pause)

    return symbols, names, results


# ---------------------------------------------------------------------------
# Price data helpers
# ---------------------------------------------------------------------------

def _extract_ticker_frame(
    downloaded: pd.DataFrame,
    ticker: str,
    batch: list[str],
) -> pd.DataFrame | None:
    """
    Pull a single ticker's OHLCV frame out of a yfinance batch download.

    yfinance returns flat columns for a single-ticker download and a
    MultiIndex for multi-ticker downloads — this handles both orientations.
    """
    if downloaded is None or downloaded.empty:
        return None

    if not isinstance(downloaded.columns, pd.MultiIndex):
        if len(batch) == 1 and batch[0] == ticker:
            return downloaded
        return None

    level0 = downloaded.columns.get_level_values(0)
    level1 = downloaded.columns.get_level_values(1)

    if ticker in level0:
        return downloaded[ticker].copy()
    if ticker in level1:
        return downloaded.xs(ticker, axis=1, level=1).copy()
    return None


def _fetch_name(symbol: str) -> str:
    """Fallback: fetch a company name via yfinance Ticker.info."""
    try:
        info = yf.Ticker(symbol).info
        return info.get("longName") or info.get("shortName") or ""
    except Exception:
        return ""


def _fetch_names_fallback(symbols: list[str], max_workers: int = 10) -> dict[str, str]:
    """Fetch names for symbols NOT in the screener cache (parallel)."""
    if not symbols:
        return {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(symbols))) as pool:
        futures = {pool.submit(_fetch_name, sym): sym for sym in symbols}
        return {futures[f]: f.result() for f in as_completed(futures)}


def _compute_fcf_decline_streak(fcf_series: "pd.Series") -> int | None:
    """
    Count consecutive annual FCF declines ending at the most recent year.

    Walks backwards from the latest year:
    - 0  → FCF grew (or was flat) in the most recent year-over-year period
    - 1  → one year of decline
    - 2  → two consecutive years of decline
    - etc.

    Returns None if fewer than 2 data points are available.
    NaN years are skipped (not counted as decline or growth).
    """
    clean = fcf_series.dropna().sort_index()   # oldest first
    if len(clean) < 2:
        return None

    streak = 0
    # Walk from most recent backwards
    values = list(clean.values)
    for i in range(len(values) - 1, 0, -1):
        if values[i] < values[i - 1]:
            streak += 1
        else:
            break   # streak broken
    return streak


def _compute_fcf_cv(fcf_series: "pd.Series") -> float | None:
    """
    Compute the Coefficient of Variation (CV%) for the FCF series.

    CV% = (sample std dev / mean) × 100

    Uses all available non-NaN data points (including negative years).
    Returns None if:
    - fewer than 2 data points (can't compute std dev)
    - the mean is ≤ 0 (CV would be undefined or misleading)
    """
    clean = fcf_series.dropna()
    if len(clean) < 2:
        return None
    mean = float(clean.mean())
    if mean <= 0:
        return None
    std = float(clean.std(ddof=1))   # sample std dev
    return round(std / mean * 100, 2)


def _compute_fcf_cagr(fcf_series: "pd.Series") -> float | None:
    """
    Compute annualised FCF CAGR (%) from a historical annual FCF Series.

    Uses the oldest and most recent available years.  If either endpoint is
    negative or zero the CAGR is mathematically undefined and None is returned
    — the stock will still be included in results but the column will be blank.

    Requires at least 2 data points with a positive first and last value.
    """
    clean = fcf_series.dropna().sort_index()   # oldest first
    if len(clean) < 2:
        return None

    start_val = float(clean.iloc[0])
    end_val = float(clean.iloc[-1])

    # Both endpoints must be positive; a negative start or end makes CAGR
    # meaningless (sign change mid-series = no real-number interpretation).
    if start_val <= 0 or end_val <= 0:
        return None

    n_years = clean.index[-1].year - clean.index[0].year
    if n_years <= 0:
        return None

    cagr = (end_val / start_val) ** (1.0 / n_years) - 1.0
    return round(cagr * 100, 2)   # e.g. 15.3 means 15.3 %/year


def _fetch_fcf(symbol: str) -> dict:
    """
    Fetch cash-flow, debt, sector, industry, and historical FCF series for a
    single symbol via ``yf.Ticker``.  Returns a dict or empty dict on failure.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Historical annual FCF for CAGR computation (up to 5 fiscal years)
        try:
            cf = ticker.cash_flow
            fcf_series = cf.loc["Free Cash Flow"] if "Free Cash Flow" in cf.index else None
        except Exception:
            fcf_series = None

        # Historical annual Total Revenue for revenue metrics
        try:
            stmt = ticker.income_stmt
            if not stmt.empty:
                rev_row = next(
                    (r for r in ("Total Revenue", "Revenue", "Net Revenue")
                     if r in stmt.index),
                    None,
                )
                revenue_series = stmt.loc[rev_row] if rev_row else None
            else:
                revenue_series = None
        except Exception:
            revenue_series = None

        return {
            # Cash flow (TTM)
            "fcf": info.get("freeCashflow"),          # op. CF − capex (TTM)
            "lfcf": info.get("leveredFreeCashFlow"),   # FCF − net debt payments (TTM)
            "fcf_series": fcf_series,                  # pd.Series of annual FCF
            "revenue_series": revenue_series,          # pd.Series of annual Total Revenue
            # Debt (MRQ balance sheet)
            "total_debt": info.get("totalDebt"),       # total interest-bearing debt (MRQ)
            "total_cash": info.get("totalCash"),       # cash & equivalents (MRQ)
            "debt_to_equity": info.get("debtToEquity"),  # % (MRQ), e.g. 147.7 = 1.477×
            # EBITDA for Net Debt/EBITDA ratio (TTM)
            "ebitda": info.get("ebitda"),
            # Classification
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except Exception:
        return {}


def _enrich_with_fcf(
    results: list[StockResult],
    max_workers: int = 15,
    min_fcf_cagr: float | None = None,
) -> list[StockResult]:
    """
    Fetch FCF metrics for all *results* in parallel and return a new list of
    ``StockResult`` objects enriched with FCF, LFCF, CAGR, debt, sector, and
    industry.

    *min_fcf_cagr* — if set, stocks where CAGR is not computable or falls
    below the threshold are discarded (local filter, not server-side).
    """
    if not results:
        return results

    symbols = [r.symbol for r in results]
    logging.info("Fetching FCF data for %d candidates (parallel)...", len(symbols))

    with ThreadPoolExecutor(max_workers=min(max_workers, len(symbols))) as pool:
        futures = {pool.submit(_fetch_fcf, sym): sym for sym in symbols}
        fcf_map: dict[str, dict] = {
            futures[f]: f.result() for f in as_completed(futures)
        }

    enriched: list[StockResult] = []
    discarded = 0
    for r in results:
        data = fcf_map.get(r.symbol, {})
        fcf_raw = data.get("fcf")
        lfcf_raw = data.get("lfcf")

        fcf = int(fcf_raw) if fcf_raw is not None else None
        lfcf = int(lfcf_raw) if lfcf_raw is not None else None

        # Discard stocks where FCF is unknown (data unavailable).
        # Stocks with negative FCF are kept — they appear with blank P/FCF.
        if fcf is None:
            discarded += 1
            continue

        p_fcf: float | None = None
        if fcf > 0 and r.market_cap is not None and r.market_cap > 0:
            p_fcf = round(r.market_cap / fcf, 2)

        p_lfcf: float | None = None
        if lfcf is not None and lfcf > 0 and r.market_cap is not None and r.market_cap > 0:
            p_lfcf = round(r.market_cap / lfcf, 2)

        sector = data.get("sector") or None
        industry = data.get("industry") or None

        # --- Debt metrics (MRQ) ---
        total_debt_raw = data.get("total_debt")
        total_cash_raw = data.get("total_cash")
        total_debt = int(total_debt_raw) if total_debt_raw is not None else None

        net_debt: int | None = None
        if total_debt is not None and total_cash_raw is not None:
            net_debt = int(total_debt_raw) - int(total_cash_raw)

        # debtToEquity is returned as % (e.g. 147.7 → ratio 1.477)
        dte_raw = data.get("debt_to_equity")
        total_debt_to_equity = round(float(dte_raw) / 100.0, 4) if dte_raw is not None else None

        # Net Debt MRQ / EBITDA TTM
        ebitda_raw = data.get("ebitda")
        net_debt_to_ebitda: float | None = None
        if net_debt is not None and ebitda_raw is not None and float(ebitda_raw) > 0:
            net_debt_to_ebitda = round(net_debt / float(ebitda_raw), 2)

        # --- FCF CAGR, CV, and decline streak (from historical annual cash flow) ---
        fcf_series = data.get("fcf_series")
        fcf_cagr: float | None = None
        fcf_cv: float | None = None
        fcf_decline_streak: int | None = None
        if fcf_series is not None:
            try:
                fcf_cagr = _compute_fcf_cagr(fcf_series)
            except Exception:
                fcf_cagr = None
            try:
                fcf_cv = _compute_fcf_cv(fcf_series)
            except Exception:
                fcf_cv = None
            try:
                fcf_decline_streak = _compute_fcf_decline_streak(fcf_series)
            except Exception:
                fcf_decline_streak = None

        # --- Revenue CAGR, CV, and decline streak (from annual income statement) ---
        revenue_series = data.get("revenue_series")
        revenue_cagr: float | None = None
        revenue_cv: float | None = None
        revenue_decline_streak: int | None = None
        if revenue_series is not None:
            try:
                revenue_cagr = _compute_fcf_cagr(revenue_series)      # same formula
            except Exception:
                revenue_cagr = None
            try:
                revenue_cv = _compute_fcf_cv(revenue_series)           # same formula
            except Exception:
                revenue_cv = None
            try:
                revenue_decline_streak = _compute_fcf_decline_streak(revenue_series)
            except Exception:
                revenue_decline_streak = None

        # Local FCF CAGR filter.
        # Only discard if CAGR is computable AND below the threshold.
        # If CAGR is None (endpoint was negative — undefined), keep the stock.
        if min_fcf_cagr is not None and fcf_cagr is not None:
            if fcf_cagr < min_fcf_cagr:
                discarded += 1
                continue

        enriched.append(dataclasses.replace(
            r,
            sector=sector,
            industry=industry,
            fcf=fcf,
            lfcf=lfcf,
            p_fcf=p_fcf,
            p_lfcf=p_lfcf,
            fcf_cagr=fcf_cagr,
            fcf_cv=fcf_cv,
            fcf_decline_streak=fcf_decline_streak,
            revenue_cagr=revenue_cagr,
            revenue_cv=revenue_cv,
            revenue_decline_streak=revenue_decline_streak,
            total_debt=total_debt,
            net_debt=net_debt,
            total_debt_to_equity=total_debt_to_equity,
            net_debt_to_ebitda=net_debt_to_ebitda,
        ))

    if discarded:
        logging.info("Discarded %d stocks with unknown FCF.", discarded)

    return enriched


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

class YahooUniverseProvider(UniverseProvider):
    """
    Fetches the scan universe from Yahoo Finance's screener, paginating
    through up to *max_results* symbols.

    ``eu`` / ``europe`` region codes are expanded to individual ISO-2 country
    codes before the query is built.  Company names from the screener are
    cached in ``_screener_names`` for use by the price provider.
    """

    def __init__(self) -> None:
        self._screener_names: dict[str, str] = {}

    def get_universe(self, regions: list[str], max_results: int) -> list[str]:
        country_codes = _expand_regions(regions)
        logging.info(
            "Querying Yahoo Finance screener  regions=%s → %d country codes  "
            "(max %d, %d per page)...",
            regions,
            len(country_codes),
            max_results,
            _PAGE_SIZE,
        )

        symbols, names, _ = _paginated_screener(country_codes, max_results)
        self._screener_names = names

        if not symbols:
            raise RuntimeError(
                "The Yahoo Finance screener returned no symbols. "
                "The API may have changed or blocked the request."
            )

        logging.info(
            "Universe: %d unique tickers  (%d company names from screener).",
            len(symbols),
            len(names),
        )
        return symbols

    def get_precomputed_results(
        self,
        regions: list[str],
        max_results: int,
        min_drawdown: float,
        sort_field: str = "avgdailyvol3m",
        sort_ascending: bool = False,
        min_fcf_cagr: float | None = None,
    ) -> list[StockResult] | None:
        """
        Return drawdown results computed directly from screener quotes —
        no price-history downloads needed.

        Each quote's ``fiftyTwoWeekHighChangePercent`` field (precise drawdown
        from 52-week high) is checked locally so only stocks that genuinely
        meet the threshold are returned.
        """
        country_codes = _expand_regions(regions)
        logging.info(
            "Screener-only scan  regions=%s → %d country codes  "
            "drawdown ≥ %.0f%%  sort=%s %s  (max %d, %d per page)...",
            regions,
            len(country_codes),
            min_drawdown,
            sort_field,
            "ASC" if sort_ascending else "DESC",
            max_results,
            _PAGE_SIZE,
        )

        symbols, names, results = _paginated_screener(
            country_codes,
            max_results,
            min_drawdown=min_drawdown,
            sort_field=sort_field,
            sort_ascending=sort_ascending,
        )
        self._screener_names = names

        if not symbols and not results:
            raise RuntimeError(
                "The Yahoo Finance screener returned no symbols. "
                "The API may have changed or blocked the request."
            )

        logging.info(
            "Screener: %d tickers scanned  →  %d meet the drawdown threshold.",
            len(symbols),
            len(results),
        )
        # Enrich candidates with FCF data and apply local filters.
        return _enrich_with_fcf(results, min_fcf_cagr=min_fcf_cagr)


class YahooPriceProvider(PriceProvider):
    """
    Downloads 1-year daily OHLCV data via yfinance batch download and
    computes 52-week-high drawdown metrics for each ticker.

    When used as ``YahooProvider`` (the combined subclass), company names
    already cached in ``_screener_names`` are used directly.  Only symbols
    absent from the cache trigger a parallel ``.info`` fallback lookup.
    """

    def fetch_batch(
        self,
        symbols: list[str],
        min_bars: int,
    ) -> tuple[list[StockResult], list[ScanFailure]]:
        logging.info("Downloading daily history for %d symbols...", len(symbols))

        try:
            prices = yf.download(
                tickers=symbols,
                period="1y",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                actions=False,
                threads=True,
                progress=False,
                timeout=30,
            )
        except Exception as exc:
            logging.exception("Batch download failed: %s", exc)
            return [], [
                ScanFailure(symbol=s, reason=f"batch download failed: {exc}")
                for s in symbols
            ]

        raw_results: list[StockResult] = []
        failures: list[ScanFailure] = []

        for symbol in symbols:
            frame = _extract_ticker_frame(prices, symbol, symbols)
            if frame is None or frame.empty:
                failures.append(ScanFailure(symbol, "no price history returned"))
                continue

            col_map = {str(c).lower(): c for c in frame.columns}
            high_col = col_map.get("high")
            close_col = col_map.get("close")

            if high_col is None or close_col is None:
                failures.append(ScanFailure(symbol, "missing High/Close columns"))
                continue

            data = frame[[high_col, close_col]].copy()
            data.columns = ["high", "close"]
            data["high"] = pd.to_numeric(data["high"], errors="coerce")
            data["close"] = pd.to_numeric(data["close"], errors="coerce")
            data = data.dropna(subset=["high", "close"])
            data = data[(data["high"] > 0) & (data["close"] > 0)]

            if len(data) < min_bars:
                failures.append(
                    ScanFailure(
                        symbol,
                        f"only {len(data)} daily bars; need {min_bars}",
                    )
                )
                continue

            # Use intraday highs (not closing prices) for the 52-week high.
            high_52w = float(data["high"].max())
            current_close = float(data["close"].iloc[-1])
            latest_date = pd.Timestamp(data.index[-1]).date().isoformat()
            drawdown_pct = (current_close / high_52w - 1.0) * 100.0

            raw_results.append(
                StockResult(
                    name="",
                    symbol=symbol,
                    latest_price_date=latest_date,
                    current_close=round(current_close, 6),
                    high_52w=round(high_52w, 6),
                    drawdown_pct=round(drawdown_pct, 2),
                )
            )

        # Prefer screener-cached names; fall back to .info only for gaps.
        screener_names: dict[str, str] = getattr(self, "_screener_names", {})
        missing = [r.symbol for r in raw_results if not screener_names.get(r.symbol)]
        if missing:
            logging.debug(
                "Fetching names via .info for %d uncached symbols.", len(missing)
            )
        fallback_names = _fetch_names_fallback(missing)
        all_names = {**screener_names, **fallback_names}

        results = [
            dataclasses.replace(r, name=all_names.get(r.symbol, ""))
            for r in raw_results
        ]
        return results, failures


class YahooProvider(YahooUniverseProvider, YahooPriceProvider):
    """
    Convenience class that combines universe discovery and price fetching
    under a single Yahoo Finance provider.

    ``_screener_names`` is populated during ``get_universe()`` and
    automatically consumed by ``fetch_batch()`` — no extra name lookups.

    Usage
    -----
    ::

        provider = YahooProvider()
        scanner  = Scanner(
            universe_provider=provider,
            price_provider=provider,
            exporter=ExcelExporter(),
            config=ScanConfig(),
        )
    """
