"""
Prompt templates for stock analysis.

Each analyst role gets its own system prompt and a builder function for
the user prompt.  The system prompt can be overridden from
``analysis_config.yaml`` via the ``prompts:`` section.

Adding a new role:
  1. Define a ``DEFAULT_<ROLE>_SYSTEM_PROMPT`` constant.
  2. Write a ``build_<role>_user_prompt(...)`` helper.
  3. Reference both in the Analyzer (or a future role registry).
"""

from __future__ import annotations


# ── Role identifier ───────────────────────────────────────────────────────

ROLE_PRICE_DECLINE_ANALYST = "price_decline_analyst"


# ── Price-decline analyst — system prompt ─────────────────────────────────

DEFAULT_PRICE_DECLINE_SYSTEM_PROMPT = """\
You are a financial analyst specializing in European equity markets.

Your task: analyse why the given company's stock price has declined
significantly from its 52-week high.  You will receive the company's
key metrics together with recent news and web search results.

Provide a clear, evidence-based analysis grounded in the information
provided.

Structure your response as:
1. **Primary Cause(s)** — the main driver(s) of the decline
2. **Contributing Factors** — secondary factors that amplified the drop
3. **Market Context** — broader market or sector trends relevant to this stock

Cite specific events and sources when available.  If the information
is insufficient to determine the cause, state that clearly rather than
speculating.
"""


# ── Price-decline analyst — user prompt builder ───────────────────────────

def build_price_decline_user_prompt(
    *,
    name: str,
    symbol: str,
    currency: str | None,
    current_close: float,
    high_52w: float,
    low_52w: float | None,
    drawdown_pct: float,
    pe_ratio: float | None,
    dividend_yield: float | None,
    market_cap: int | None,
    sector: str | None,
    industry: str | None,
    search_results_text: str,
) -> str:
    """Build the user prompt for the price-decline analyst role."""

    cur = currency or "N/A"

    def _f(val: float | None, fmt: str = ".2f") -> str:
        return f"{val:{fmt}}" if val is not None else "N/A"

    def _fi(val: int | None) -> str:
        return f"{val:,}" if val is not None else "N/A"

    return (
        f"Analyse why the following company's stock price has declined.\n"
        f"\n"
        f"**Company:** {name} ({symbol})\n"
        f"\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Current Price | {_f(current_close)} {cur} |\n"
        f"| 52-Week High | {_f(high_52w)} {cur} |\n"
        f"| 52-Week Low | {_f(low_52w)} {cur} |\n"
        f"| Drawdown from 52W High | {drawdown_pct:.2f}% |\n"
        f"| P/E Ratio | {_f(pe_ratio)} |\n"
        f"| Dividend Yield | {_f(dividend_yield)}% |\n"
        f"| Market Cap | {_fi(market_cap)} {cur} |\n"
        f"| Sector | {sector or 'N/A'} |\n"
        f"| Industry | {industry or 'N/A'} |\n"
        f"\n"
        f"### Recent News and Web Search Results\n"
        f"{search_results_text}\n"
        f"\n"
        f"---\n"
        f"\n"
        f"Based on the stock data and recent news above, analyse why "
        f"**{name}** ({symbol}) has declined **{abs(drawdown_pct):.1f}%** "
        f"from its 52-week high.\n"
    )
