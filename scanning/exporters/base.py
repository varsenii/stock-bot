"""
Abstract base class for scan result exporters.

To add a new output format (CSV, Parquet, database, etc.), create a new
module in this directory, subclass BaseExporter, implement `export`, and
wire it up in cli.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..config import ScanConfig
from ..models import ScanFailure, StockResult


class BaseExporter(ABC):
    """Writes scan results to a persistent destination and returns the path."""

    @abstractmethod
    def export(
        self,
        candidates: list[StockResult],
        all_scanned: list[StockResult],
        failures: list[ScanFailure],
        config: ScanConfig,
    ) -> Path:
        """
        Persist the scan results.

        Parameters
        ----------
        candidates:
            Stocks that meet (or exceed) the configured drawdown threshold.
        all_scanned:
            Every stock for which a drawdown could be computed, sorted by
            ``drawdown_pct`` ascending (most negative first).
        failures:
            Tickers that could not be priced, with reasons.
        config:
            The ScanConfig used for this run (useful for embedding metadata
            such as the threshold or run date in the output).

        Returns
        -------
        Path
            Absolute path to the written file (or directory for multi-file
            exporters).
        """
        ...
