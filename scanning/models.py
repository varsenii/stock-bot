"""
Data classes that form the shared vocabulary of the scanning package.

These are intentionally dependency-free so any layer of the application
can import them without pulling in heavy third-party libraries.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StockResult:
    """Drawdown metrics and key fundamentals for a single stock."""

    # --- Identity ---
    name: str                            # Company display name, e.g. "ASML Holding N.V."
    symbol: str

    # --- Price ---
    latest_price_date: str               # ISO-8601 date string, e.g. "2026-11-06"
    current_close: float
    high_52w: float
    low_52w: float | None = None         # 52-week low

    # --- Drawdown ---
    drawdown_pct: float = 0.0            # negative value: -32.5 means 32.5% below 52w high

    # --- Fundamentals (None when not available from the data source) ---
    pe_ratio: float | None = None        # Trailing P/E (price / EPS TTM); may be approximate
    dividend_yield: float | None = None  # Dividend yield % (e.g. 3.5 means 3.5%)
    market_cap: int | None = None        # Market capitalisation in local currency units
    sector: str | None = None            # e.g. "Financial Services"
    industry: str | None = None          # e.g. "Banks—Regional"
    fcf: int | None = None               # Free Cash Flow TTM (op. cash flow − capex)
    lfcf: int | None = None              # Levered Free Cash Flow TTM (FCF − net debt payments)
    p_fcf: float | None = None           # Price / FCF = market_cap / fcf
    p_lfcf: float | None = None          # Price / Levered FCF = market_cap / lfcf
    total_debt: int | None = None        # Total Debt MRQ (from balance sheet)
    net_debt: int | None = None          # Net Debt MRQ = totalDebt − totalCash
    total_debt_to_equity: float | None = None  # Total Debt / Equity MRQ (ratio, e.g. 1.47)
    net_debt_to_ebitda: float | None = None    # Net Debt MRQ / EBITDA TTM

    # --- Liquidity ---
    avg_volume_3m: int | None = None          # Avg daily share volume, 3-month window
    avg_volume_10d: int | None = None         # Avg daily share volume, 10-day window
    bid: float | None = None                  # Best bid price
    ask: float | None = None                  # Best ask price
    bid_ask_spread: float | None = None       # ask − bid (absolute)
    bid_ask_spread_pct: float | None = None   # (ask − bid) / mid_price × 100
    avg_daily_value: float | None = None      # 50-day avg price × 3M avg volume (approx ADTV)
    today_value: float | None = None          # current price × today's volume


@dataclass(frozen=True)
class ScanFailure:
    """Record of a ticker that could not be priced, with a human-readable reason."""

    symbol: str
    reason: str
