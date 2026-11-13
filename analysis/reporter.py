"""
Reporter — writes per-company markdown analysis reports.

Each report is a standalone ``.md`` file named after the company and its
ticker, stored in the configured output directory.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path


def sanitize_filename(text: str) -> str:
    """
    Convert an arbitrary string to a filesystem-safe component.

    Strips characters that are illegal or inconvenient in filenames on
    Linux, macOS, and Windows, then collapses whitespace to underscores.
    """
    sanitized = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s]+", "_", sanitized.strip())


def write_report(
    output_dir: Path,
    company_name: str,
    symbol: str,
    drawdown_pct: float,
    currency: str | None,
    current_close: float,
    high_52w: float,
    analysis_text: str,
) -> Path:
    """
    Write a markdown report for a single company.

    Returns
    -------
    Path
        Absolute path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(company_name)
    safe_symbol = sanitize_filename(symbol)
    filename = f"{safe_name}_{safe_symbol}.md"
    path = output_dir / filename

    today = datetime.now().astimezone().date().isoformat()
    cur = currency or ""

    content = (
        f"# {company_name} ({symbol})\n"
        f"\n"
        f"**Analysis Date:** {today}  \n"
        f"**Current Price:** {current_close:.2f} {cur}  \n"
        f"**52-Week High:** {high_52w:.2f} {cur}  \n"
        f"**Drawdown:** {drawdown_pct:.2f}%\n"
        f"\n"
        f"---\n"
        f"\n"
        f"## Why Did the Price Drop?\n"
        f"\n"
        f"{analysis_text}\n"
        f"\n"
        f"---\n"
        f"\n"
        f"*This report was generated automatically by stock-bot using "
        f"LLM analysis with web search context.*\n"
    )

    path.write_text(content, encoding="utf-8")
    logging.info("Report written: %s", path)
    return path
