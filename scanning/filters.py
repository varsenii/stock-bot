"""
Screener filter registry.

This module defines the mapping between the human-readable keys used in
``scan_config.yaml`` and the yfinance ``EquityQuery`` field names and operators
that Yahoo Finance's screener understands.

To add a new filterable criterion:
  1. Add an entry to ``FILTER_REGISTRY`` below.
  2. Add the corresponding key (with a sensible default or ``null``) to the
     ``filters:`` section of ``scan_config.yaml``.

``ACTIVE_FILTERS`` is built at runtime by ``build_active_filters()``; it is
populated by ``cli.py`` when the YAML config is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScreenerFilter:
    """A single server-side filter clause passed to Yahoo Finance's EquityQuery."""

    field: str        # EQUITY_SCREENER_FIELDS field name
    operator: str     # "gt" | "gte" | "lt" | "lte" | "eq" | "is-in"
    value: Any        # threshold value (or list of values for "is-in")
    description: str = ""


# ---------------------------------------------------------------------------
# Filter registry — maps YAML config keys → (yfinance field, operator, label)
# ---------------------------------------------------------------------------
# Each entry:  yaml_key → (yfinance_field, operator, human_description)

_FilterSpec = tuple[str, str, str]  # (field, operator, description)

FILTER_REGISTRY: dict[str, _FilterSpec] = {
    # key in scan_config.yaml           yfinance field name                operator  description
    "min_avg_daily_volume":    ("avgdailyvol3m",                    "gt",   "3-month avg daily volume (min)"),
    "max_pe_ratio":            ("peratio.lasttwelvemonths",          "lte",  "P/E ratio TTM (max)"),
    "max_price_to_book":       ("pricebookratio.quarterly",          "lte",  "Price-to-book ratio (max)"),
    "max_debt_to_equity":      ("totaldebtequity.lasttwelvemonths",  "lte",  "Total debt / equity (max)"),
    "min_return_on_equity":    ("returnonequity.lasttwelvemonths",   "gte",  "Return on equity (min)"),
    "min_market_cap":          ("intradaymarketcap",                 "gte",  "Market cap (min)"),
    "max_market_cap":          ("intradaymarketcap",                 "lte",  "Market cap (max)"),
}


# ---------------------------------------------------------------------------
# Runtime list — populated by build_active_filters(), consumed by yahoo.py
# ---------------------------------------------------------------------------

ACTIVE_FILTERS: list[ScreenerFilter] = []


def build_active_filters(filters_cfg: dict[str, Any]) -> list[ScreenerFilter]:
    """
    Build a list of ``ScreenerFilter`` objects from the ``filters:`` section
    of ``scan_config.yaml``.

    Keys not present in ``FILTER_REGISTRY`` are silently ignored.
    Values set to ``null`` / ``None`` are skipped (filter disabled).

    Parameters
    ----------
    filters_cfg:
        Dictionary parsed from the ``filters:`` block in ``scan_config.yaml``.

    Returns
    -------
    list[ScreenerFilter]
        Filters to apply server-side in the Yahoo Finance screener query.
    """
    result: list[ScreenerFilter] = []
    for key, value in filters_cfg.items():
        if value is None:
            continue  # explicitly disabled in YAML
        if key not in FILTER_REGISTRY:
            import logging
            logging.warning("scan_config.yaml: unknown filter key '%s' — skipped.", key)
            continue
        field, operator, description = FILTER_REGISTRY[key]
        result.append(ScreenerFilter(field=field, operator=operator, value=value, description=description))
    return result
