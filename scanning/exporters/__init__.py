"""
Result exporters for the scanning package.

To add a new format, create a module here, subclass BaseExporter, and
register it in this file.
"""

from .base import BaseExporter
from .excel import ExcelExporter

__all__ = [
    "BaseExporter",
    "ExcelExporter",
]
