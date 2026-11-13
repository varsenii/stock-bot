"""
Analyzer — orchestrates the LLM-powered stock analysis pipeline.

For each stock record from the latest scan output:

  1. Search the web for recent news / context (DuckDuckGo).
  2. Build a structured prompt with stock data + search results.
  3. Send to the LLM for analysis.
  4. Write a per-company markdown report.

The Analyzer is decoupled from specific LLM or search backends — swap
them by passing different implementations.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import AnalysisConfig
from .llm.base import BaseLLM
from .prompts import (
    DEFAULT_PRICE_DECLINE_SYSTEM_PROMPT,
    ROLE_PRICE_DECLINE_ANALYST,
    build_price_decline_user_prompt,
)
from .reader import StockRecord, find_latest_scan_file, load_records
from .reporter import write_report
from .search.base import BaseSearchProvider, SearchResult
from .search.duckduckgo import build_search_query


def _format_search_results(results: list[SearchResult]) -> str:
    """Render search results as markdown text suitable for an LLM prompt."""
    if not results:
        return "_No recent news found for this company._"

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        date_part = f" ({r.date})" if r.date else ""
        source_part = f" — {r.source}" if r.source else ""
        lines.append(f"{i}. **{r.title}**{date_part}{source_part}")
        lines.append(f"   {r.snippet}")
        lines.append(f"   Source: {r.url}")
        lines.append("")

    return "\n".join(lines)


class Analyzer:
    """
    Orchestrates a full analysis run over the latest scan results.

    Parameters
    ----------
    llm:
        The language model backend to use.
    search_provider:
        The web-search backend for gathering context.
    config:
        All tunable parameters for this analysis run.
    """

    def __init__(
        self,
        llm: BaseLLM,
        search_provider: BaseSearchProvider,
        config: AnalysisConfig,
    ) -> None:
        self._llm = llm
        self._search = search_provider
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> list[Path]:
        """
        Execute the full analysis pipeline.

        Returns
        -------
        list[Path]
            Paths to the generated markdown reports.
        """
        scan_file = find_latest_scan_file(self._config.input_dir)
        logging.info("Using scan file: %s", scan_file)

        records = load_records(scan_file, self._config.max_records)
        if not records:
            logging.warning("No records found in %s", scan_file)
            return []

        logging.info("Processing %d record(s)…", len(records))

        system_prompt = self._resolve_system_prompt()

        reports: list[Path] = []
        failures = 0

        for i, record in enumerate(records, 1):
            logging.info(
                "[%d/%d] Analysing %s (%s) — drawdown: %.1f%%",
                i,
                len(records),
                record.name,
                record.symbol,
                record.drawdown_pct,
            )
            try:
                path = self._analyze_single(record, system_prompt)
                reports.append(path)
            except Exception:
                failures += 1
                logging.exception(
                    "Failed to analyse %s (%s)",
                    record.name,
                    record.symbol,
                )

        self._log_summary(len(records), len(reports), failures)
        return reports

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_system_prompt(self) -> str:
        """Return the system prompt, preferring config override over default."""
        role_cfg = self._config.prompts.get(ROLE_PRICE_DECLINE_ANALYST) or {}
        return role_cfg.get("system", DEFAULT_PRICE_DECLINE_SYSTEM_PROMPT)

    def _analyze_single(self, record: StockRecord, system_prompt: str) -> Path:
        # 1. Web search for context.
        query = build_search_query(record.name, record.symbol)
        search_results = self._search.search(query)
        search_text = _format_search_results(search_results)
        logging.info(
            "  Web search returned %d result(s) for '%s'",
            len(search_results),
            query,
        )

        # 2. Build the prompt (stock data + search results).
        user_prompt = build_price_decline_user_prompt(
            name=record.name,
            symbol=record.symbol,
            currency=record.currency,
            current_close=record.current_close,
            high_52w=record.high_52w,
            low_52w=record.low_52w,
            drawdown_pct=record.drawdown_pct,
            pe_ratio=record.pe_ratio,
            dividend_yield=record.dividend_yield,
            market_cap=record.market_cap,
            sector=record.sector,
            industry=record.industry,
            search_results_text=search_text,
        )

        # 3. LLM analysis.
        analysis = self._llm.generate(system_prompt, user_prompt)

        # 4. Write report.
        return write_report(
            output_dir=self._config.output_dir,
            company_name=record.name,
            symbol=record.symbol,
            drawdown_pct=record.drawdown_pct,
            currency=record.currency,
            current_close=record.current_close,
            high_52w=record.high_52w,
            analysis_text=analysis,
        )

    @staticmethod
    def _log_summary(total: int, succeeded: int, failed: int) -> None:
        sep = "-" * 52
        logging.info(sep)
        logging.info("ANALYSIS SUMMARY")
        logging.info(sep)
        logging.info("  Total records     : %4d", total)
        logging.info("  Reports generated : %4d", succeeded)
        logging.info("  Failed            : %4d", failed)
        logging.info(sep)
