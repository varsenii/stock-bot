"""
Command-line interface for the stock bot.

Provides two sub-commands:

    python -m stock_bot scan     — run the drawdown screener
    python -m stock_bot analyze  — LLM analysis of the latest scan output

Configuration is loaded from YAML files next to this script.  CLI
arguments override individual YAML values when explicitly provided.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

# ── Shared helpers ────────────────────────────────────────────────────────

_SCAN_CONFIG_FILE = Path(__file__).parent / "scan_config.yaml"
_ANALYSIS_CONFIG_FILE = Path(__file__).parent / "analysis_config.yaml"


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


# ═════════════════════════════════════════════════════════════════════════
# SCAN sub-command
# ═════════════════════════════════════════════════════════════════════════

def _add_scan_args(parser: argparse.ArgumentParser) -> None:
    """Register CLI arguments for the ``scan`` sub-command."""
    parser.add_argument(
        "--config",
        type=Path,
        default=_SCAN_CONFIG_FILE,
        help=f"Path to the scan YAML config file. Default: {_SCAN_CONFIG_FILE}",
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
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--min-bars", type=int, default=200)
    parser.add_argument("--pause", type=float, default=1.0)


def _build_scan_config(yaml_cfg: dict, args: argparse.Namespace):
    """Merge YAML config with CLI overrides to produce a ``ScanConfig``."""
    from scanning import ScanConfig

    if args.regions is not None:
        regions = [r.strip().lower() for r in args.regions.split(",") if r.strip()]
    else:
        raw = yaml_cfg.get("regions", ["eu", "gb"])
        regions = [str(r).strip().lower() for r in raw]

    min_drawdown = (
        args.min_drawdown
        if args.min_drawdown is not None
        else float(yaml_cfg.get("min_drawdown_pct", 20.0))
    )
    max_results = (
        args.max_results
        if args.max_results is not None
        else int(yaml_cfg.get("max_results", 2500))
    )
    output_dir = (
        args.output_dir
        if args.output_dir is not None
        else Path(yaml_cfg.get("output_dir", "output"))
    )

    sort_cfg: dict = yaml_cfg.get("sort", {}) or {}
    sort_field: str = str(sort_cfg.get("field", "avgdailyvol3m"))
    sort_ascending: bool = bool(sort_cfg.get("ascending", False))

    local_filters: dict = yaml_cfg.get("local_filters", {}) or {}
    min_fcf_cagr_raw = local_filters.get("min_fcf_cagr")
    min_fcf_cagr: float | None = (
        float(min_fcf_cagr_raw) if min_fcf_cagr_raw is not None else None
    )

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


def _apply_yaml_filters(yaml_cfg: dict) -> None:
    """Populate ``scanning.filters.ACTIVE_FILTERS`` from the YAML config."""
    import scanning.filters as filters_module
    from scanning.filters import build_active_filters

    filters_cfg: dict = yaml_cfg.get("filters", {})
    active = build_active_filters(filters_cfg)
    filters_module.ACTIVE_FILTERS.clear()
    filters_module.ACTIVE_FILTERS.extend(active)

    if active:
        logging.info("Active screener filters (%d):", len(active))
        for f in active:
            logging.info("  %-35s %s %s", f.description, f.operator.upper(), f.value)
    else:
        logging.info("No additional screener filters active.")


def scan_main(args: argparse.Namespace) -> int:
    """Entry point for the ``scan`` sub-command."""
    from scanning import Scanner
    from scanning.exporters import ExcelExporter
    from scanning.providers import YahooProvider

    yaml_cfg = load_yaml_config(args.config)

    try:
        config = _build_scan_config(yaml_cfg, args)
    except ValueError as exc:
        logging.error("Configuration error: %s", exc)
        return 2

    _apply_yaml_filters(yaml_cfg)

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


# ═════════════════════════════════════════════════════════════════════════
# ANALYZE sub-command
# ═════════════════════════════════════════════════════════════════════════

def _add_analyze_args(parser: argparse.ArgumentParser) -> None:
    """Register CLI arguments for the ``analyze`` sub-command."""
    parser.add_argument(
        "--config",
        type=Path,
        default=_ANALYSIS_CONFIG_FILE,
        help=f"Path to the analysis YAML config file. Default: {_ANALYSIS_CONFIG_FILE}",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the LLM model from config (e.g. qwen3:14b).",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N records. Overrides analysis_config.yaml.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Directory with scan .xlsx files. Overrides analysis_config.yaml.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for markdown reports. Overrides analysis_config.yaml.",
    )


def _build_analysis_config(yaml_cfg: dict, args: argparse.Namespace):
    """Merge YAML config with CLI overrides to produce an ``AnalysisConfig``."""
    from analysis.config import AnalysisConfig, LLMConfig, SearchConfig

    llm_cfg: dict = yaml_cfg.get("llm", {}) or {}
    search_cfg: dict = yaml_cfg.get("search", {}) or {}
    analysis_cfg: dict = yaml_cfg.get("analysis", {}) or {}

    llm = LLMConfig(
        provider=llm_cfg.get("provider", "ollama"),
        model=args.model or llm_cfg.get("model", "qwen3:8b"),
        host=llm_cfg.get("host", "http://localhost:11434"),
        temperature=float(llm_cfg.get("temperature", 0.3)),
        num_predict=int(llm_cfg.get("num_predict", 2048)),
        num_ctx=int(llm_cfg.get("num_ctx", 32768)),
    )

    search = SearchConfig(
        provider=search_cfg.get("provider", "duckduckgo"),
        max_results=int(search_cfg.get("max_results", 8)),
        region=search_cfg.get("region", "wt-wt"),
    )

    max_records_raw = (
        args.max_records
        if args.max_records is not None
        else analysis_cfg.get("max_records")
    )
    max_records: int | None = int(max_records_raw) if max_records_raw is not None else None

    input_dir = (
        args.input_dir
        if args.input_dir is not None
        else Path(analysis_cfg.get("input_dir", "output"))
    )
    output_dir = (
        args.output_dir
        if args.output_dir is not None
        else Path(analysis_cfg.get("output_dir", "reports"))
    )

    prompts: dict = yaml_cfg.get("prompts", {}) or {}

    return AnalysisConfig(
        llm=llm,
        search=search,
        max_records=max_records,
        input_dir=input_dir,
        output_dir=output_dir,
        prompts=prompts,
    )


def analyze_main(args: argparse.Namespace) -> int:
    """Entry point for the ``analyze`` sub-command."""
    from analysis import Analyzer
    from analysis.llm import OllamaLLM
    from analysis.search import DuckDuckGoSearch

    yaml_cfg = load_yaml_config(args.config)

    try:
        config = _build_analysis_config(yaml_cfg, args)
    except (ValueError, TypeError) as exc:
        logging.error("Configuration error: %s", exc)
        return 2

    # Wire up the LLM backend.
    if config.llm.provider != "ollama":
        logging.error("Unsupported LLM provider: '%s'", config.llm.provider)
        return 2

    llm = OllamaLLM(config.llm)

    if not llm.is_available():
        logging.error(
            "Cannot reach Ollama at %s. "
            "Make sure the server is running (ollama serve).",
            config.llm.host,
        )
        return 1

    llm.ensure_model_pulled()

    # Wire up the search provider.
    if config.search.provider != "duckduckgo":
        logging.error("Unsupported search provider: '%s'", config.search.provider)
        return 2

    search = DuckDuckGoSearch(config.search)

    analyzer = Analyzer(llm=llm, search_provider=search, config=config)

    try:
        analyzer.run()
        return 0
    except Exception as exc:
        logging.error("%s", exc)
        return 1


# ═════════════════════════════════════════════════════════════════════════
# Main entry point
# ═════════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    setup_logging()

    parser = argparse.ArgumentParser(
        prog="stock_bot",
        description="Stock bot — screen European equities and analyse price declines.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # scan
    scan_parser = subparsers.add_parser(
        "scan",
        help="Run the drawdown screener and export results to Excel.",
    )
    _add_scan_args(scan_parser)

    # analyze
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Use an LLM to explain why each stock's price declined.",
    )
    _add_analyze_args(analyze_parser)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "scan":
        return scan_main(args)

    if args.command == "analyze":
        return analyze_main(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
