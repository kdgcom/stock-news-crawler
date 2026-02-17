"""Daily and weekly report generation for the Stock Trading System.

Generates formatted text reports suitable for delivery via Telegram.
The report format matches the 09-monitoring design document specification.

Daily reports include: performance summary, trade log, signal statistics,
portfolio snapshot, and next-day outlook.

Weekly reports provide an aggregated performance summary across all
trading days in the week.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# KST = UTC+9
_KST = timezone(timedelta(hours=9))

# Market-specific currency formatting
_CURRENCY_MAP: dict[str, dict[str, str]] = {
    "KR": {"symbol": "\u20a9", "prefix": "\u20a9", "name": "KRW"},
    "US": {"symbol": "$", "prefix": "$", "name": "USD"},
}


def _nested_get(d: dict, dotted_key: str, default: Any = None) -> Any:
    """Retrieve a value from a nested dict using a dotted key path."""
    keys = dotted_key.split(".")
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(k)
        if current is None:
            return default
    return current


def _fmt_currency(value: float, market: str) -> str:
    """Format a monetary value with the appropriate currency symbol."""
    info = _CURRENCY_MAP.get(market, _CURRENCY_MAP["US"])
    if market == "KR":
        return f"{info['prefix']}{value:,.0f}"
    return f"{info['prefix']}{value:,.2f}"


def _fmt_pct(value: float) -> str:
    """Format a percentage value with sign."""
    return f"{value:+.1f}%"


class ReportGenerator:
    """Generate daily and weekly trading reports as formatted text.

    Parameters
    ----------
    config:
        System configuration dict.  Keys consumed:

        - ``report.market_names`` -- mapping of market codes to display
          names (default ``{"KR": "KR", "US": "US"}``).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._market_names: dict[str, str] = _nested_get(
            config,
            "report.market_names",
            {"KR": "KR", "US": "US"},
        )

    def _market_label(self, market: str) -> str:
        """Return the display name for a market code."""
        return self._market_names.get(market, market)

    # -- daily report --------------------------------------------------------

    def generate_daily_report(self, market: str, data: dict) -> str:
        """Generate a daily performance report.

        Parameters
        ----------
        market:
            Market identifier (``"KR"`` or ``"US"``).
        data:
            Dict with the following structure::

                {
                    "date": "2026-02-16",      # report date string
                    "performance": {
                        "daily_pnl_pct": 1.2,
                        "realized_pnl": 120000,
                        "unrealized_pnl": 350000,
                    },
                    "trades": [
                        {
                            "side": "BUY",
                            "symbol": "005930",
                            "name": "Samsung Electronics",
                            "quantity": 100,
                            "price": 58200,
                            "pnl_pct": None,     # None for buys
                        },
                        ...
                    ],
                    "signals": {
                        "total": 78,
                        "buy": 5,
                        "sell": 2,
                        "hold": 71,
                        "risk_blocked": 1,
                        "risk_blocked_reason": "spread exceeded",
                    },
                    "portfolio": {
                        "total_value": 50600000,
                        "total_pnl_pct": 1.2,
                        "position_count": 8,
                        "cash_pct": 60,
                        "mdd_pct": -2.3,
                        "mdd_limit_pct": -15,
                    },
                    "outlook": [
                        "Samsung Electronics earnings (D-2)",
                        "FOMC minutes release impact",
                    ],
                }

        Returns
        -------
        str
            Formatted text suitable for Telegram delivery.
        """
        report_date = data.get("date", datetime.now(tz=_KST).strftime("%Y-%m-%d"))
        label = self._market_label(market)

        perf = data.get("performance", {})
        trades = data.get("trades", [])
        signals = data.get("signals", {})
        portfolio = data.get("portfolio", {})
        outlook = data.get("outlook", [])

        lines: list[str] = []

        # Header
        lines.append(f"\U0001f4c8 {label} Daily Report ({report_date})")
        lines.append("\u2501" * 30)
        lines.append("")

        # Performance section
        daily_pnl_pct = float(perf.get("daily_pnl_pct", 0.0))
        realized = float(perf.get("realized_pnl", 0.0))
        unrealized = float(perf.get("unrealized_pnl", 0.0))

        lines.append("\u25a0 Performance")
        lines.append(f"  Daily return: {_fmt_pct(daily_pnl_pct)}")
        lines.append(f"  Realized P&L: {_fmt_currency(realized, market)}")
        lines.append(f"  Unrealized P&L: {_fmt_currency(unrealized, market)}")
        lines.append("")

        # Trades section
        lines.append("\u25a0 Trades")
        if trades:
            for trade in trades:
                side = trade.get("side", "?")
                symbol = trade.get("symbol", "?")
                name = trade.get("name", "")
                qty = trade.get("quantity", 0)
                price = trade.get("price", 0)
                pnl_pct = trade.get("pnl_pct")

                price_str = _fmt_currency(price, market)
                name_part = f" {name}" if name else ""
                pnl_part = f" ({_fmt_pct(pnl_pct)})" if pnl_pct is not None else ""

                lines.append(
                    f"  {side:<4} {symbol}{name_part} "
                    f"{qty}sh @ {price_str}{pnl_part}"
                )
        else:
            lines.append("  No trades today")
        lines.append("")

        # Signal statistics
        sig_total = int(signals.get("total", 0))
        sig_buy = int(signals.get("buy", 0))
        sig_sell = int(signals.get("sell", 0))
        sig_hold = int(signals.get("hold", 0))
        sig_blocked = int(signals.get("risk_blocked", 0))
        sig_blocked_reason = signals.get("risk_blocked_reason", "")

        lines.append("\u25a0 Signal Statistics")
        lines.append(
            f"  Generated: {sig_total} | "
            f"BUY: {sig_buy} | SELL: {sig_sell} | HOLD: {sig_hold}"
        )
        if sig_blocked > 0:
            reason_part = f" ({sig_blocked_reason})" if sig_blocked_reason else ""
            lines.append(f"  Risk blocked: {sig_blocked}{reason_part}")
        lines.append("")

        # Portfolio snapshot
        total_value = float(portfolio.get("total_value", 0.0))
        total_pnl_pct = float(portfolio.get("total_pnl_pct", 0.0))
        pos_count = int(portfolio.get("position_count", 0))
        cash_pct = float(portfolio.get("cash_pct", 0.0))
        mdd_pct = float(portfolio.get("mdd_pct", 0.0))
        mdd_limit = float(portfolio.get("mdd_limit_pct", -15.0))

        lines.append("\u25a0 Portfolio")
        lines.append(
            f"  Total: {_fmt_currency(total_value, market)} "
            f"({_fmt_pct(total_pnl_pct)})"
        )
        lines.append(f"  Positions: {pos_count} | Cash: {cash_pct:.0f}%")
        lines.append(f"  MDD: {_fmt_pct(mdd_pct)} (limit {_fmt_pct(mdd_limit)})")
        lines.append("")

        # Tomorrow's outlook
        if outlook:
            lines.append("\u25a0 Outlook")
            for item in outlook:
                lines.append(f"  - {item}")
            lines.append("")

        return "\n".join(lines)

    # -- weekly report -------------------------------------------------------

    def generate_weekly_report(self, data: dict) -> str:
        """Generate a weekly performance summary report.

        Parameters
        ----------
        data:
            Dict with the following structure::

                {
                    "week": "2026-W07",           # ISO week string
                    "period": "2026-02-10 ~ 02-16",
                    "markets": {
                        "KR": {
                            "weekly_pnl_pct": 2.5,
                            "realized_pnl": 450000,
                            "trade_count": 12,
                            "win_rate_pct": 66.7,
                            "best_trade": {
                                "symbol": "005930",
                                "name": "Samsung",
                                "pnl_pct": 5.2,
                            },
                            "worst_trade": {
                                "symbol": "035720",
                                "name": "Kakao Bank",
                                "pnl_pct": -1.8,
                            },
                        },
                        "US": { ... },
                    },
                    "combined": {
                        "weekly_pnl_pct": 1.8,
                        "total_value": 51200000,
                        "position_count": 10,
                        "cash_pct": 55,
                        "mdd_pct": -2.3,
                        "signals_total": 540,
                        "risk_blocks": 3,
                        "llm_cost_usd": 28.50,
                    },
                }

        Returns
        -------
        str
            Formatted text suitable for Telegram delivery.
        """
        week_label = data.get("week", "")
        period = data.get("period", "")
        markets = data.get("markets", {})
        combined = data.get("combined", {})

        lines: list[str] = []

        # Header
        lines.append(f"\U0001f4ca Weekly Report ({week_label})")
        lines.append(f"Period: {period}")
        lines.append("\u2501" * 30)
        lines.append("")

        # Per-market breakdown
        for market_code, mdata in markets.items():
            label = self._market_label(market_code)
            weekly_pnl = float(mdata.get("weekly_pnl_pct", 0.0))
            realized = float(mdata.get("realized_pnl", 0.0))
            trade_count = int(mdata.get("trade_count", 0))
            win_rate = float(mdata.get("win_rate_pct", 0.0))

            lines.append(f"\u25a0 {label} Market")
            lines.append(f"  Weekly return: {_fmt_pct(weekly_pnl)}")
            lines.append(f"  Realized P&L: {_fmt_currency(realized, market_code)}")
            lines.append(f"  Trades: {trade_count} | Win rate: {win_rate:.1f}%")

            best = mdata.get("best_trade")
            if best:
                b_sym = best.get("symbol", "?")
                b_name = best.get("name", "")
                b_pnl = float(best.get("pnl_pct", 0.0))
                name_part = f" {b_name}" if b_name else ""
                lines.append(f"  Best: {b_sym}{name_part} ({_fmt_pct(b_pnl)})")

            worst = mdata.get("worst_trade")
            if worst:
                w_sym = worst.get("symbol", "?")
                w_name = worst.get("name", "")
                w_pnl = float(worst.get("pnl_pct", 0.0))
                name_part = f" {w_name}" if w_name else ""
                lines.append(f"  Worst: {w_sym}{name_part} ({_fmt_pct(w_pnl)})")

            lines.append("")

        # Combined summary
        comb_pnl = float(combined.get("weekly_pnl_pct", 0.0))
        total_value = float(combined.get("total_value", 0.0))
        pos_count = int(combined.get("position_count", 0))
        cash_pct = float(combined.get("cash_pct", 0.0))
        mdd_pct = float(combined.get("mdd_pct", 0.0))
        sig_total = int(combined.get("signals_total", 0))
        risk_blocks_count = int(combined.get("risk_blocks", 0))
        llm_cost = float(combined.get("llm_cost_usd", 0.0))

        lines.append("\u25a0 Combined")
        lines.append(f"  Weekly return: {_fmt_pct(comb_pnl)}")
        lines.append(f"  Portfolio: {_fmt_currency(total_value, 'KR')}")
        lines.append(f"  Positions: {pos_count} | Cash: {cash_pct:.0f}%")
        lines.append(f"  MDD: {_fmt_pct(mdd_pct)}")
        lines.append(f"  Signals: {sig_total} | Risk blocks: {risk_blocks_count}")
        lines.append(f"  LLM cost: ${llm_cost:.2f}")
        lines.append("")

        return "\n".join(lines)
