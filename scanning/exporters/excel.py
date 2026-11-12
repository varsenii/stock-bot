"""
Excel exporter — writes a formatted .xlsx workbook with three sheets:

    1. Candidates (≥N% DD)  — stocks meeting the drawdown threshold
    2. All Scanned           — every successfully priced stock
    3. Failures              — tickers that could not be priced

Formatting applied to data sheets:
  - Bold white headers on a dark-blue background
  - Frozen top row
  - Alternating light-blue row fills
  - Number formats: percentage for drawdown, 6-decimal for prices
  - Green→Yellow→Red colour scale on the Drawdown % column
  - Auto-fitted column widths

Requires: openpyxl (listed in requirements.txt).
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ..config import ScanConfig
from ..models import ScanFailure, StockResult
from .base import BaseExporter


# ---------------------------------------------------------------------------
# Styling constants
# ---------------------------------------------------------------------------

_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill(fill_type="solid", fgColor="1F4E79")   # dark navy
_ALT_ROW_FILL = PatternFill(fill_type="solid", fgColor="DCE6F1")  # light blue

# Maps internal field names → human-readable column headers.
# Order here controls the column order in the workbook.
_COLUMN_LABELS: dict[str, str] = {
    "name": "Company Name",
    "symbol": "Symbol",
    "currency": "Currency",
    "sector": "Sector",
    "industry": "Industry",
    "latest_price_date": "Latest Price Date",
    "current_close": "Current Close",
    "high_52w": "52-Week High",
    "low_52w": "52-Week Low",
    "drawdown_pct": "Drawdown %",
    "pe_ratio": "P/E Ratio",
    "dividend_yield": "Dividend Yield %",
    "market_cap": "Market Cap",
    # Earnings dates (from screener quote)
    "last_earnings_date": "Last Earnings",
    "next_earnings_date": "Next Earnings",
    "is_earnings_estimate": "Est.",
    # Cash flow (TTM)
    "fcf": "FCF (TTM)",
    "lfcf": "LFCF (TTM)",
    "p_fcf": "P/FCF",
    "p_lfcf": "P/LFCF",
    "fcf_cagr": "FCF CAGR %",
    "fcf_cv": "FCF CV %",
    "fcf_decline_streak": "FCF Decline Streak",
    "revenue_cagr": "Rev CAGR %",
    "revenue_cv": "Rev CV %",
    "revenue_decline_streak": "Rev Decline Streak",
    # Debt (MRQ balance sheet, except net_debt_to_ebitda which is MRQ/TTM)
    "total_debt": "Total Debt (MRQ)",
    "net_debt": "Net Debt (MRQ)",
    "total_debt_to_equity": "Debt/Equity (MRQ)",
    "net_debt_to_ebitda": "Net Debt/EBITDA (MRQ/TTM)",
    # Liquidity
    "avg_volume_3m": "Avg Vol (3M)",
    "avg_volume_10d": "Avg Vol (10D)",
    "bid": "Bid",
    "ask": "Ask",
    "bid_ask_spread": "Bid-Ask Spread",
    "bid_ask_spread_pct": "Spread %",
    "avg_daily_value": "Avg Daily Value (3M)",
    "today_value": "Today's Value",
}

_DRAWDOWN_COL = "Drawdown %"
_PRICE_COLS = ("Current Close", "52-Week High", "52-Week Low", "Bid", "Ask", "Bid-Ask Spread")
_RATIO_COLS = ("P/E Ratio",)
_PCT_COLS = ("Dividend Yield %", "Spread %")
_RATIO_COLS_FCF = ("P/FCF", "P/LFCF", "FCF CAGR %", "FCF CV %", "Rev CAGR %", "Rev CV %")
_RATIO_COLS_DEBT = ("Debt/Equity (MRQ)", "Net Debt/EBITDA (MRQ/TTM)")
_LARGE_NUM_COLS = ("Market Cap", "FCF (TTM)", "LFCF (TTM)", "Total Debt (MRQ)", "Net Debt (MRQ)", "Avg Vol (3M)", "Avg Vol (10D)", "Avg Daily Value (3M)", "Today's Value")


# ---------------------------------------------------------------------------
# Private formatting helpers
# ---------------------------------------------------------------------------

def _apply_header_style(ws: Worksheet) -> None:
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 20


def _apply_alternating_rows(ws: Worksheet) -> None:
    for row_idx, row in enumerate(ws.iter_rows(min_row=2), start=2):
        if row_idx % 2 == 0:
            for cell in row:
                cell.fill = _ALT_ROW_FILL


def _apply_number_formats(ws: Worksheet) -> None:
    """Apply number formats based on column header names."""
    col_index: dict[str, int] = {
        str(cell.value): cell.column for cell in ws[1]
    }

    if _DRAWDOWN_COL in col_index:
        letter = get_column_letter(col_index[_DRAWDOWN_COL])
        for cell in ws[letter][1:]:
            cell.number_format = '0.00"%"'

    for col_name in _PRICE_COLS:
        if col_name in col_index:
            letter = get_column_letter(col_index[col_name])
            for cell in ws[letter][1:]:
                cell.number_format = "#,##0.000000"

    for col_name in _RATIO_COLS_FCF:
        if col_name in col_index:
            letter = get_column_letter(col_index[col_name])
            for cell in ws[letter][1:]:
                cell.number_format = "0.00"

    for col_name in _RATIO_COLS:
        if col_name in col_index:
            letter = get_column_letter(col_index[col_name])
            for cell in ws[letter][1:]:
                cell.number_format = "0.00"

    for col_name in _RATIO_COLS_DEBT:
        if col_name in col_index:
            letter = get_column_letter(col_index[col_name])
            for cell in ws[letter][1:]:
                cell.number_format = "0.00"

    for col_name in _PCT_COLS:
        if col_name in col_index:
            letter = get_column_letter(col_index[col_name])
            for cell in ws[letter][1:]:
                cell.number_format = '0.00"%"'

    for col_name in _LARGE_NUM_COLS:
        if col_name in col_index:
            letter = get_column_letter(col_index[col_name])
            for cell in ws[letter][1:]:
                cell.number_format = '#,##0'


def _apply_drawdown_colour_scale(ws: Worksheet, num_data_rows: int) -> None:
    """Add a green→yellow→red colour scale to the Drawdown % column."""
    if num_data_rows < 2:
        return
    col_index: dict[str, int] = {
        str(cell.value): cell.column for cell in ws[1]
    }
    if _DRAWDOWN_COL not in col_index:
        return
    letter = get_column_letter(col_index[_DRAWDOWN_COL])
    rule = ColorScaleRule(
        start_type="min",        start_color="63BE7B",   # green  (least negative)
        mid_type="percentile",   mid_value=50,
                                 mid_color="FFEB84",     # yellow
        end_type="max",          end_color="F8696B",     # red    (most negative)
    )
    ws.conditional_formatting.add(f"{letter}2:{letter}{ws.max_row}", rule)


def _auto_fit_columns(ws: Worksheet, max_width: int = 40) -> None:
    for col_cells in ws.columns:
        width = max(
            (len(str(cell.value)) if cell.value is not None else 0)
            for cell in col_cells
        )
        ws.column_dimensions[
            get_column_letter(col_cells[0].column)
        ].width = min(max(width + 3, 10), max_width)


def _format_data_sheet(ws: Worksheet, num_data_rows: int) -> None:
    _apply_header_style(ws)
    _apply_alternating_rows(ws)
    _apply_number_formats(ws)
    _apply_drawdown_colour_scale(ws, num_data_rows)
    _auto_fit_columns(ws)


def _format_failures_sheet(ws: Worksheet) -> None:
    _apply_header_style(ws)
    _auto_fit_columns(ws, max_width=60)


# ---------------------------------------------------------------------------
# Public exporter class
# ---------------------------------------------------------------------------

class ExcelExporter(BaseExporter):
    """Exports scan results to a formatted multi-sheet Excel workbook."""

    def export(
        self,
        candidates: list[StockResult],
        all_scanned: list[StockResult],
        failures: list[ScanFailure],
        config: ScanConfig,
    ) -> Path:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().astimezone().date().isoformat()
        path = config.output_dir / f"stock_scan_{today}.xlsx"

        candidates_df = _to_df(candidates)
        all_scanned_df = _to_df(all_scanned)
        failures_df = _failures_to_df(failures)

        candidates_sheet = f"Candidates (≥{config.min_drawdown:.0f}% DD)"

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            candidates_df.to_excel(writer, sheet_name=candidates_sheet, index=False)
            all_scanned_df.to_excel(writer, sheet_name="All Scanned", index=False)
            failures_df.to_excel(writer, sheet_name="Failures", index=False)

            wb = writer.book
            _format_data_sheet(wb[candidates_sheet], len(candidates))
            _format_data_sheet(wb["All Scanned"], len(all_scanned))
            _format_failures_sheet(wb["Failures"])

        logging.info("Output workbook: %s", path.resolve())
        return path.resolve()


# ---------------------------------------------------------------------------
# DataFrame conversion helpers
# ---------------------------------------------------------------------------

def _to_df(results: list[StockResult]) -> pd.DataFrame:
    """Convert a list of StockResult to a renamed DataFrame ready for export."""
    if not results:
        return pd.DataFrame(columns=list(_COLUMN_LABELS.values()))
    rows = [dataclasses.asdict(r) for r in results]
    return pd.DataFrame(rows).rename(columns=_COLUMN_LABELS)


def _failures_to_df(failures: list[ScanFailure]) -> pd.DataFrame:
    if not failures:
        return pd.DataFrame(columns=["Symbol", "Reason"])
    rows = [dataclasses.asdict(f) for f in failures]
    return pd.DataFrame(rows).rename(columns={"symbol": "Symbol", "reason": "Reason"})
