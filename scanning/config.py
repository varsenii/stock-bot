"""
ScanConfig — a single dataclass that captures every tunable parameter for a
drawdown scan run.  Keeping configuration separate from logic means the CLI,
a future REST endpoint, or a Jupyter notebook can all build a ScanConfig and
hand it to the Scanner without touching argparse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScanConfig:
    """All parameters controlling a single drawdown scan."""

    # --- Universe ---
    regions: list[str] = field(default_factory=lambda: ["eu", "gb"])
    max_results: int = 2500
    symbols_file: Path | None = None          # overrides screener when set

    # --- Filtering ---
    min_drawdown: float = 20.0                # positive %; stocks this far below their high
    min_bars: int = 200                       # minimum daily observations required

    # --- Fetching ---
    batch_size: int = 80                      # symbols per yfinance download call
    pause: float = 1.0                        # seconds between batches

    # --- Output ---
    output_dir: Path = field(default_factory=lambda: Path("output"))

    def __post_init__(self) -> None:
        if self.min_drawdown < 0:
            raise ValueError("min_drawdown must be zero or a positive percentage.")
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1.")
        # Normalise path types so callers can pass plain strings if they like.
        self.output_dir = Path(self.output_dir)
        if self.symbols_file is not None:
            self.symbols_file = Path(self.symbols_file)

    @property
    def drawdown_threshold(self) -> float:
        """The raw (negative) drawdown_pct value that qualifies a stock."""
        return -abs(self.min_drawdown)
