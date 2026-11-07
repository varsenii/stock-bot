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


@dataclass(frozen=True)
class ScanFailure:
    """Record of a ticker that could not be priced, with a human-readable reason."""

    symbol: str
    reason: str
