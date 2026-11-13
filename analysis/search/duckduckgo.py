"""
DuckDuckGo web-search provider.

Uses the ``duckduckgo-search`` library — free, no API key required.
Results are a mix of recent news and general web pages so the LLM gets
both timely and background context.
"""

from __future__ import annotations

import logging
import re

from ddgs import DDGS

from ..config import SearchConfig
from .base import BaseSearchProvider, SearchResult

# Legal / corporate suffixes that clutter search queries.
_CORP_SUFFIXES = re.compile(
    r"\b(N\.V\.|PLC|Plc|plc|Ltd\.?|Inc\.?|Corp\.?|S\.A\.?|AG|SE|ASA|AB"
    r"|OYJ|S\.p\.A\.?|GmbH)\b",
    re.IGNORECASE,
)


def _clean_company_name(name: str) -> str:
    """Strip corporate suffixes for better search results."""
    return _CORP_SUFFIXES.sub("", name).strip().rstrip(",").strip()


def build_search_query(name: str, symbol: str) -> str:
    """
    Construct a search query for a stock's price decline.

    Strips corporate suffixes from the company name so search engines
    match on the real company name rather than legal boilerplate.
    """
    clean = _clean_company_name(name)
    return f"{clean} {symbol} stock price decline reason"


class DuckDuckGoSearch(BaseSearchProvider):
    """
    Search provider backed by DuckDuckGo (no API key needed).

    Combines news and general web results for richer context.

    Parameters
    ----------
    config:
        Search settings (max results, region, etc.).
    """

    def __init__(self, config: SearchConfig) -> None:
        self._config = config

    def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        limit = max_results or self._config.max_results
        results: list[SearchResult] = []

        try:
            results.extend(self._search_news(query, limit))
            remaining = limit - len(results)
            if remaining > 0:
                results.extend(self._search_text(query, remaining))
        except Exception as exc:
            logging.warning("Web search failed for '%s': %s", query, exc)

        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _search_news(self, query: str, max_results: int) -> list[SearchResult]:
        hits: list[SearchResult] = []
        try:
            for r in DDGS().news(
                query, max_results=max_results, region=self._config.region,
            ):
                hits.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("body", ""),
                        source=r.get("source"),
                        date=r.get("date"),
                    )
                )
        except Exception as exc:
            logging.debug("DuckDuckGo news search error: %s", exc)
        return hits

    def _search_text(self, query: str, max_results: int) -> list[SearchResult]:
        hits: list[SearchResult] = []
        try:
            for r in DDGS().text(
                query, max_results=max_results, region=self._config.region,
            ):
                hits.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                    )
                )
        except Exception as exc:
            logging.debug("DuckDuckGo text search error: %s", exc)
        return hits
