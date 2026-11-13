"""
Reader — loads stock data from the most recent scan output file.

Looks for ``stock_scan_*.xlsx`` files in the configured input directory,
picks the latest one by filename date, and returns a list of lightweight
``StockRecord`` objects suitable for the analysis pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class StockRecord:
    """A single row from the scan output, carrying the fields needed for analysis."""

    name: str
    symbol: str
    currency: str | None = None
    current_close: float = 0.0
    high_52w: float = 0.0
    low_52w: float | None = None
    drawdown_pct: float = 0.0
    pe_ratio: float | None = None
    dividend_yield: float | None = None
    market_cap: int | None = None
    sector: str | None = None
    industry: str | None = None


def find_latest_scan_file(input_dir: Path) -> Path:
    """
    Return the most recent ``stock_scan_*.xlsx`` file in *input_dir*.

    Files are sorted lexicographically by name; because the date stamp is
    ISO-8601 (``YYYY-MM-DD``), this is equivalent to chronological order.

    Raises
    ------
    FileNotFoundError
        If no matching files exist.
    """
    xlsx_files = sorted(input_dir.glob("stock_scan_*.xlsx"))
    if not xlsx_files:
        raise FileNotFoundError(
            f"No stock_scan_*.xlsx files found in {input_dir.resolve()}"
        )
    return xlsx_files[-1]


def load_records(
    path: Path, max_records: int | None = None
) -> list[StockRecord]:
    """
    Read the candidates sheet (first sheet) from an Excel scan file.

    Parameters
    ----------
    path:
        Path to the ``.xlsx`` workbook produced by the scanner.
    max_records:
        If set, only return the first *max_records* rows.

    Returns
    -------
    list[StockRecord]
    """
    df = pd.read_excel(path, sheet_name=0)

    if max_records is not None and max_records > 0:
        df = df.head(max_records)

    records: list[StockRecord] = []
    for _, row in df.iterrows():
        records.append(
            StockRecord(
                name=str(row.get("Company Name", "")),
                symbol=str(row.get("Symbol", "")),
                currency=_opt_str(row, "Currency"),
                current_close=float(row.get("Current Close", 0)),
                high_52w=float(row.get("52-Week High", 0)),
                low_52w=_opt_float(row, "52-Week Low"),
                drawdown_pct=float(row.get("Drawdown %", 0)),
                pe_ratio=_opt_float(row, "P/E Ratio"),
                dividend_yield=_opt_float(row, "Dividend Yield %"),
                market_cap=_opt_int(row, "Market Cap"),
                sector=_opt_str(row, "Sector"),
                industry=_opt_str(row, "Industry"),
            )
        )

    logging.info("Loaded %d records from %s", len(records), path.name)
    return records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opt_str(row: pd.Series, col: str) -> str | None:
    val = row.get(col)
    return str(val) if pd.notna(val) else None


def _opt_float(row: pd.Series, col: str) -> float | None:
    val = row.get(col)
    return float(val) if pd.notna(val) else None


def _opt_int(row: pd.Series, col: str) -> int | None:
    val = row.get(col)
    return int(val) if pd.notna(val) else None
