"""
Abstract base class for web-search providers.

The analysis pipeline searches for recent news about a company before
sending the prompt to the LLM, so it has real-world context to work with.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    """A single search hit (news article, web page, etc.)."""

    title: str
    url: str
    snippet: str
    source: str | None = None
    date: str | None = None


class BaseSearchProvider(ABC):
    """Contract for web-search backends."""

    @abstractmethod
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        """
        Execute a web search and return results.

        Parameters
        ----------
        query:
            Free-text search query.
        max_results:
            Upper bound on the number of hits to return.

        Returns
        -------
        list[SearchResult]
        """
        ...
