"""
AnalysisConfig — configuration for the LLM-based stock analysis pipeline.

Mirrors the scanning.config.ScanConfig pattern: a plain dataclass that
captures every tunable parameter, loadable from YAML or constructed
programmatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LLMConfig:
    """Configuration for the LLM backend."""

    provider: str = "ollama"
    model: str = "qwen3:8b"
    host: str = "http://localhost:11434"
    temperature: float = 0.3
    num_predict: int = 2048
    num_ctx: int = 32768


@dataclass
class SearchConfig:
    """Configuration for the web-search provider."""

    provider: str = "duckduckgo"
    max_results: int = 8
    region: str = "wt-wt"


@dataclass
class AnalysisConfig:
    """All parameters controlling a single analysis run."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    search: SearchConfig = field(default_factory=SearchConfig)

    # Number of records to process.  None = process every entry.
    max_records: int | None = None

    # Directory containing scan output files (.xlsx).
    input_dir: Path = field(default_factory=lambda: Path("output"))

    # Directory where markdown reports will be saved.
    output_dir: Path = field(default_factory=lambda: Path("reports"))

    # Prompt overrides keyed by role name.
    # e.g. {"price_decline_analyst": {"system": "..."}}
    prompts: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.input_dir = Path(self.input_dir)
        self.output_dir = Path(self.output_dir)
