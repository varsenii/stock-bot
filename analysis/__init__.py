"""
analysis — LLM-powered stock analysis package.

Reads scan output, searches the web for context (DuckDuckGo), and uses
a local LLM (via Ollama) to explain why each stock's price declined.

Public API surface:

    from analysis import Analyzer, AnalysisConfig
    from analysis.llm import OllamaLLM
    from analysis.search import DuckDuckGoSearch
"""

from .analyzer import Analyzer
from .config import AnalysisConfig, LLMConfig, SearchConfig

__all__ = [
    "Analyzer",
    "AnalysisConfig",
    "LLMConfig",
    "SearchConfig",
]
