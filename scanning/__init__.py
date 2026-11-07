"""
scanning — drawdown scan package for the stock bot.

Public API surface:

    from scanning import Scanner, ScanConfig
    from scanning.models import StockResult, ScanFailure
    from scanning.providers import YahooProvider
    from scanning.exporters import ExcelExporter
"""

from .config import ScanConfig
from .models import ScanFailure, StockResult
from .scanner import Scanner

__all__ = [
    "Scanner",
    "ScanConfig",
    "StockResult",
    "ScanFailure",
]
