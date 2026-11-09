"""
Scanner — orchestrates a full drawdown scan run.

The Scanner is intentionally decoupled from any specific data source or
output format.  It delegates to:

  - UniverseProvider  to discover which tickers to scan
  - PriceProvider     to fetch OHLCV data and compute drawdown metrics
  - BaseExporter      to write results to disk

Swapping any of those three components requires no changes here.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd

from .config import ScanConfig
from .exporters.base import BaseExporter
from .models import ScanFailure, StockResult
from .providers.base import PriceProvider, UniverseProvider


class Scanner:
    """
    Orchestrates a full drawdown scan.

    Parameters
    ----------
    universe_provider:
        Responsible for returning the list of tickers to scan.
    price_provider:
        Responsible for fetching price data and computing drawdown metrics.
    exporter:
        Responsible for persisting the results.
    config:
        All tunable parameters for this scan run.

    Example
    -------
    ::

        from scanning import Scanner, ScanConfig
        from scanning.providers import YahooProvider
        from scanning.exporters import ExcelExporter

        provider = YahooProvider()
        scanner  = Scanner(
            universe_provider=provider,
            price_provider=provider,
            exporter=ExcelExporter(),
            config=ScanConfig(min_drawdown=25.0),
        )
        output_path = scanner.run()
    """

    def __init__(
        self,
        universe_provider: UniverseProvider,
        price_provider: PriceProvider,
        exporter: BaseExporter,
        config: ScanConfig,
    ) -> None:
        self._universe = universe_provider
        self._prices = price_provider
        self._exporter = exporter
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> Path:
        """
        Execute a full scan and export the results.

        If the universe provider implements ``get_precomputed_results()``
        (e.g. ``YahooUniverseProvider`` in screener-only mode), the Scanner
        uses those results directly and skips all price-history downloads.
        Otherwise it falls back to the normal batch-download flow.

        Returns
        -------
        Path
            The path returned by the exporter (e.g. the .xlsx file).
        """
        # --- Screener-only fast path ---
        precomputed = self._universe.get_precomputed_results(
            regions=self._config.regions,
            max_results=self._config.max_results,
            min_drawdown=self._config.min_drawdown,
            sort_field=self._config.sort_field,
            sort_ascending=self._config.sort_ascending,
            min_fcf_cagr=self._config.min_fcf_cagr,
        )

        if precomputed is not None:
            # All candidates already filtered and computed by the screener.
            candidates = sorted(precomputed, key=lambda r: r.drawdown_pct)
            all_scanned = candidates   # screener only returns qualifying stocks
            all_failures: list = []
            logging.info(
                "Screener-only mode: %d candidates returned (no price-history "
                "downloads).",
                len(candidates),
            )
            return self._exporter.export(
                candidates=candidates,
                all_scanned=all_scanned,
                failures=all_failures,
                config=self._config,
            )

        # --- Legacy batch-download path ---
        symbols = self._resolve_symbols()
        all_results, all_failures = self._fetch_all(symbols)

        if not all_results:
            raise RuntimeError(
                "No usable price histories were returned. "
                "Check connectivity and whether Yahoo Finance is rate-limiting."
            )

        sorted_results = sorted(all_results, key=lambda r: r.drawdown_pct)
        candidates = [
            r for r in sorted_results
            if r.drawdown_pct <= self._config.drawdown_threshold
        ]

        _log_summary(symbols, sorted_results, all_failures, candidates, self._config)

        return self._exporter.export(
            candidates=candidates,
            all_scanned=sorted_results,
            failures=all_failures,
            config=self._config,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_symbols(self) -> list[str]:
        """Return the ticker list from either a local file or the screener."""
        if self._config.symbols_file:
            symbols = _read_symbols_file(self._config.symbols_file)
            logging.info(
                "Loaded %s symbols from %s",
                len(symbols),
                self._config.symbols_file,
            )
            return symbols

        return self._universe.get_universe(
            regions=self._config.regions,
            max_results=self._config.max_results,
        )

    def _fetch_all(
        self, symbols: list[str]
    ) -> tuple[list[StockResult], list[ScanFailure]]:
        """Fetch price data in batches, respecting the configured pause interval."""
        batches = _make_batches(symbols, self._config.batch_size)
        all_results: list[StockResult] = []
        all_failures: list[ScanFailure] = []

        for idx, batch in enumerate(batches, start=1):
            logging.info("Batch %s/%s", idx, len(batches))
            results, failures = self._prices.fetch_batch(batch, self._config.min_bars)
            all_results.extend(results)
            all_failures.extend(failures)
            if idx < len(batches) and self._config.pause > 0:
                time.sleep(self._config.pause)

        return all_results, all_failures


# ---------------------------------------------------------------------------
# Module-level helpers (not part of the public Scanner API)
# ---------------------------------------------------------------------------

def _log_summary(
    symbols: list[str],
    all_scanned: list[StockResult],
    failures: list[ScanFailure],
    candidates: list[StockResult],
    config: ScanConfig,
) -> None:
    """Log a concise funnel summary so it is immediately clear where symbols go."""
    sep = "-" * 52
    logging.info(sep)
    logging.info("SCAN SUMMARY")
    logging.info(sep)
    logging.info("  Symbols from screener / file : %6d", len(symbols))
    logging.info("  Successfully priced          : %6d", len(all_scanned))
    logging.info("  Failed / filtered out        : %6d", len(failures))
    logging.info(
        "  Candidates (≥%.0f%% drawdown)  : %6d",
        config.min_drawdown,
        len(candidates),
    )
    logging.info(sep)

    # Break down failure reasons so the user can see the main bottleneck.
    if failures:
        from collections import Counter

        # Bucket reasons into short labels.
        def _bucket(reason: str) -> str:
            r = reason.lower()
            if "no price history" in r:
                return "no price history returned"
            if "daily bars" in r:
                return f"fewer than {config.min_bars} daily bars (--min-bars)"
            if "batch download failed" in r:
                return "batch download error (rate-limit / network)"
            if "missing high/close" in r:
                return "missing High/Close columns"
            return reason

        counts = Counter(_bucket(f.reason) for f in failures)
        logging.info("  Failure breakdown:")
        for reason, count in counts.most_common():
            logging.info("    %-45s %4d", reason, count)
        logging.info(sep)


def _make_batches(symbols: list[str], batch_size: int) -> list[list[str]]:
    return [symbols[i : i + batch_size] for i in range(0, len(symbols), batch_size)]


def _read_symbols_file(path: Path) -> list[str]:
    """Read a CSV file with a 'symbol' column and return normalised tickers."""
    frame = pd.read_csv(path)
    col = next((c for c in frame.columns if c.lower() == "symbol"), None)
    if col is None:
        raise ValueError(f"Symbols file '{path}' must contain a column named 'symbol'.")
    tickers = frame[col].dropna().astype(str).str.strip().str.upper().tolist()
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for t in tickers:
        if t and t not in seen:
            seen.add(t)
            unique.append(t)
    return unique
