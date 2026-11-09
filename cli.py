"""
Command-line interface for the stock drawdown scanner.

Configuration is loaded from ``scan_config.yaml`` (located next to this file).
CLI arguments override individual YAML values when explicitly provided.

Run with:
    python -m stock_bot [options]
    python stock_bot/cli.py [options]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

import scanning.filters as filters_module
from scanning import Scanner, ScanConfig
from scanning.exporters import ExcelExporter
from scanning.filters import build_active_filters
from scanning.providers import YahooProvider


# Default config file — lives next to cli.py inside the stock_bot/ directory.
_CONFIG_FILE = Path(__file__).parent / "scan_config.yaml"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_yaml_config(path: Path) -> dict:
    """Load and return the YAML configuration file."""
    if not path.exists():
        logging.warning("Config file not found: %s — using built-in defaults.", path)
        return {}
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def parse_args(yaml_cfg: dict, argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse CLI arguments, using YAML values as defaults.

    Any argument explicitly passed on the command line overrides the YAML.
    """
    parser = argparse.ArgumentParser(
        prog="stock_bot",
        description=(
            "Find European stocks at least X%% below their 52-week high. "
            "Default values are loaded from scan_config.yaml."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_CONFIG_FILE,
        help=f"Path to the YAML config file. Default: {_CONFIG_FILE}",
    )
    parser.add_argument(
        "--regions",
        default=None,
        help=(
            "Comma-separated region codes, overrides scan_config.yaml. "
            "'eu' expands to all 24 European country codes."
        ),
    )
    parser.add_argument(
        "--min-drawdown",
        type=float,
        default=None,
        metavar="PCT",
        help="Minimum %% below 52-week high, overrides scan_config.yaml.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Max tickers from screener, overrides scan_config.yaml.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the Excel workbook, overrides scan_config.yaml.",
    )
    parser.add_argument(
        "--symbols-file",
        type=Path,
        default=None,
        metavar="CSV",
        help="CSV file with a 'symbol' column. Bypasses the screener.",
    )
    # Fallback / symbols-file mode options
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--min-bars", type=int, default=200)
    parser.add_argument("--pause", type=float, default=1.0)
    return parser.parse_args(argv)


def build_config(yaml_cfg: dict, args: argparse.Namespace) -> ScanConfig:
    """
    Merge YAML config with CLI overrides to produce a ``ScanConfig``.
    CLI arguments take precedence over YAML values.
    """
    # Regions: CLI > YAML > default
    if args.regions is not None:
        regions = [r.strip().lower() for r in args.regions.split(",") if r.strip()]
    else:
        raw = yaml_cfg.get("regions", ["eu", "gb"])
        regions = [str(r).strip().lower() for r in raw]

    min_drawdown = args.min_drawdown if args.min_drawdown is not None \
        else float(yaml_cfg.get("min_drawdown_pct", 20.0))

    max_results = args.max_results if args.max_results is not None \
        else int(yaml_cfg.get("max_results", 2500))

    output_dir = args.output_dir if args.output_dir is not None \
        else Path(yaml_cfg.get("output_dir", "output"))

    sort_cfg: dict = yaml_cfg.get("sort", {}) or {}
    sort_field: str = str(sort_cfg.get("field", "avgdailyvol3m"))
    sort_ascending: bool = bool(sort_cfg.get("ascending", False))

    local_filters: dict = yaml_cfg.get("local_filters", {}) or {}
    min_fcf_cagr_raw = local_filters.get("min_fcf_cagr")
    min_fcf_cagr: float | None = float(min_fcf_cagr_raw) if min_fcf_cagr_raw is not None else None

    return ScanConfig(
        regions=regions,
        min_drawdown=min_drawdown,
        max_results=max_results,
        batch_size=args.batch_size,
        min_bars=args.min_bars,
        symbols_file=args.symbols_file,
        output_dir=output_dir,
        pause=args.pause,
        sort_field=sort_field,
        sort_ascending=sort_ascending,
        min_fcf_cagr=min_fcf_cagr,
    )


def apply_yaml_filters(yaml_cfg: dict) -> None:
    """
    Build the active screener filters from the ``filters:`` block in the YAML
    and write them into ``scanning.filters.ACTIVE_FILTERS`` so that
    ``yahoo.py`` picks them up when it constructs the EquityQuery.
    """
    filters_cfg: dict = yaml_cfg.get("filters", {})
    active = build_active_filters(filters_cfg)
    filters_module.ACTIVE_FILTERS.clear()
    filters_module.ACTIVE_FILTERS.extend(active)

    if active:
        logging.info(
            "Active screener filters (%d):", len(active)
        )
        for f in active:
            logging.info("  %-35s %s %s", f.description, f.operator.upper(), f.value)
    else:
        logging.info("No additional screener filters active.")


def main(argv: list[str] | None = None) -> int:
    setup_logging()

    # --- Load config file (may be overridden by --config arg) ---
    # Pre-parse just to find --config before full parse.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", type=Path, default=_CONFIG_FILE)
    pre_args, _ = pre.parse_known_args(argv)

    yaml_cfg = load_yaml_config(pre_args.config)
    args = parse_args(yaml_cfg, argv)

    # Reload if --config was explicitly passed and differs from default.
    if args.config != _CONFIG_FILE:
        yaml_cfg = load_yaml_config(args.config)

    try:
        config = build_config(yaml_cfg, args)
    except ValueError as exc:
        logging.error("Configuration error: %s", exc)
        return 2

    apply_yaml_filters(yaml_cfg)

    # Wire up providers and exporter.
    provider = YahooProvider()
    scanner = Scanner(
        universe_provider=provider,
        price_provider=provider,
        exporter=ExcelExporter(),
        config=config,
    )

    try:
        scanner.run()
        return 0
    except Exception as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
