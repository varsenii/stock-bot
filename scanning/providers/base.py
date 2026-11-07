"""
Abstract base classes for data providers.

The two concerns are intentionally separated so they can be mixed and matched:

- UniverseProvider  — answers "which tickers should we scan?"
- PriceProvider     — answers "what are the OHLCV figures for these tickers?"

To swap in a different data source (e.g. Bloomberg, Interactive Brokers,
a local database), create a new module under `providers/` that subclasses the
relevant ABC(s) and register it in `providers/__init__.py`.  No other part of
the codebase needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import ScanConfig

from ..models import ScanFailure, StockResult


class UniverseProvider(ABC):
    """Returns the list of ticker symbols to include in a scan."""

    def get_precomputed_results(
        self,
        regions: list[str],
        max_results: int,
        min_drawdown: float,
        sort_field: str = "avgdailyvol3m",
        sort_ascending: bool = False,
    ) -> list[StockResult] | None:
        """
        Optionally return fully-computed ``StockResult`` objects directly from
        the data source (e.g. a screener that already carries price/drawdown
        data in each quote), bypassing the separate price-history download step.

        Return ``None`` (the default) to signal that the ``Scanner`` should
        fall back to the normal ``PriceProvider.fetch_batch()`` flow.
        """
        return None

    @abstractmethod
    def get_universe(self, regions: list[str], max_results: int) -> list[str]:
        """
        Fetch and return a deduplicated list of ticker symbols.

        Parameters
        ----------
        regions:
            Market region codes understood by the underlying data source
            (e.g. ``["eu", "gb"]`` for Yahoo Finance).
        max_results:
            Upper bound on the number of symbols to return.

        Returns
        -------
        list[str]
            Upper-cased, deduplicated ticker symbols.

        Raises
        ------
        RuntimeError
            If the provider returns an empty universe.
        """
        ...


class PriceProvider(ABC):
    """Fetches OHLCV price history and computes drawdown metrics for a batch."""

    @abstractmethod
    def fetch_batch(
        self,
        symbols: list[str],
        min_bars: int,
    ) -> tuple[list[StockResult], list[ScanFailure]]:
        """
        Download price data for *symbols* and compute drawdown metrics.

        Parameters
        ----------
        symbols:
            Ticker symbols to fetch (should be a manageable batch size).
        min_bars:
            Minimum number of daily observations required; tickers with fewer
            bars are reported as failures.

        Returns
        -------
        results : list[StockResult]
            Successfully processed tickers with computed drawdown.
        failures : list[ScanFailure]
            Tickers that could not be processed, with a human-readable reason.
        """
        ...
