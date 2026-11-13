"""
Web search provider implementations.

To add a new search backend (SearXNG, Brave, Tavily, …):
  1. Create a module in this directory.
  2. Subclass ``BaseSearchProvider`` and implement ``search``.
  3. Wire it up in cli.py.
"""

from .base import BaseSearchProvider, SearchResult
from .duckduckgo import DuckDuckGoSearch

__all__ = ["BaseSearchProvider", "SearchResult", "DuckDuckGoSearch"]
