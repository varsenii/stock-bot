"""
DEPRECATED — this file is kept only for backward compatibility.

The scanning logic has been refactored into the `scanning` package:

    scanning/
    ├── config.py               ScanConfig dataclass
    ├── models.py               StockResult, ScanFailure
    ├── scanner.py              Scanner orchestrator
    ├── providers/
    │   ├── base.py             UniverseProvider, PriceProvider ABCs
    │   └── yahoo.py            YahooProvider (default implementation)
    └── exporters/
        ├── base.py             BaseExporter ABC
        └── excel.py            ExcelExporter (formatted .xlsx output)

Entry points:
    python -m stock_bot [options]      # preferred
    python stock_bot/cli.py [options]  # direct script

This shim will be removed in a future version.
"""

import warnings

warnings.warn(
    "stock_bot/scanner.py is deprecated. "
    "Use 'python -m stock_bot' or 'python stock_bot/cli.py' instead.",
    DeprecationWarning,
    stacklevel=1,
)

from cli import main  # noqa: E402
import sys            # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
