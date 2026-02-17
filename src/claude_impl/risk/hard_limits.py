"""Level 1 hard limits -- absolute limits that cannot be overridden.

These checks enforce unconditional safety boundaries defined in the
``risk.hard_limits`` section of ``config/settings.yaml``.  If **any**
single check fails the entire order is rejected immediately.

Every check method returns ``tuple[bool, str]`` where the string is a
machine-readable reason code (e.g. ``"DAILY_LOSS_EXCEEDED"``).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _cfg(config: dict, key: str, default: Any = None) -> Any:
    """Retrieve *key* from a flat config dict with an optional *default*."""
    return config.get(key, default)


class HardLimitChecker:
    """Level 1 risk gate -- absolute hard limits.

    Parameters
    ----------
    config:
        The ``risk.hard_limits`` section from the application config, e.g.::

            {
                "max_single_order_krw": 5_000_000,
                "max_single_order_usd": 3_000,
                "max_orders_per_day": 50,
                ...
            }
    """

    def __init__(self, config: dict) -> None:
        self._max_single_order_krw: float = _cfg(config, "max_single_order_krw", 5_000_000)
        self._max_single_order_usd: float = _cfg(config, "max_single_order_usd", 3_000)
        self._max_orders_per_day: int = _cfg(config, "max_orders_per_day", 50)
        self._max_daily_loss_pct: float = _cfg(config, "max_daily_loss_pct", -0.03)
        self._max_weekly_loss_pct: float = _cfg(config, "max_weekly_loss_pct", -0.05)
        self._max_drawdown_pct: float = _cfg(config, "max_drawdown_pct", -0.15)
        self._max_single_stock_pct: float = _cfg(config, "max_single_stock_pct", 0.10)
        self._max_sector_pct: float = _cfg(config, "max_sector_pct", 0.30)
        self._max_total_positions: int = _cfg(config, "max_total_positions", 20)
        self._min_cash_reserve_pct: float = _cfg(config, "min_cash_reserve_pct", 0.20)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def check(self, order: dict, portfolio: dict) -> tuple[bool, str]:
        """Run **all** hard-limit checks sequentially.

        Returns ``(True, "ALL_PASSED")`` if every check passes, or
        ``(False, "<REASON_CODE>")`` on the first failure.

        Parameters
        ----------
        order:
            Proposed order dict.  Expected keys:

            - ``market`` -- ``"kr"`` or ``"us"``
            - ``amount`` -- order amount in local currency (KRW or USD)
            - ``symbol`` -- ticker symbol
            - ``sector`` -- sector name / code  (optional, may be ``None``)

        portfolio:
            Current portfolio state dict.  Expected keys:

            - ``orders_today`` -- number of orders placed today
            - ``daily_pnl_pct`` -- realised + unrealised PnL today (decimal)
            - ``weekly_pnl_pct`` -- PnL for the current week (decimal)
            - ``drawdown_pct`` -- current drawdown from peak (decimal, negative)
            - ``total_value`` -- total portfolio value
            - ``positions`` -- list of position dicts, each with at least
              ``symbol``, ``market_value``, ``sector``
            - ``open_position_count`` -- number of open positions
            - ``cash`` -- available cash
        """
        checks: list[tuple[bool, str]] = [
            self._check_order_size(order),
            self._check_daily_orders(portfolio),
            self._check_daily_loss(portfolio),
            self._check_weekly_loss(portfolio),
            self._check_drawdown(portfolio),
            self._check_position_concentration(order, portfolio),
            self._check_sector_concentration(order, portfolio),
            self._check_total_positions(portfolio),
            self._check_cash_reserve(order, portfolio),
        ]
        for passed, reason in checks:
            if not passed:
                logger.warning("Hard limit violated: %s", reason)
                return False, reason
        return True, "ALL_PASSED"

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_order_size(self, order: dict) -> tuple[bool, str]:
        """Single order amount must not exceed the per-market limit."""
        market: str = order.get("market", "kr")
        amount: float = order.get("amount", 0.0)

        if market == "kr":
            if amount > self._max_single_order_krw:
                return (
                    False,
                    f"ORDER_SIZE_EXCEEDED: {amount:,.0f} KRW > "
                    f"limit {self._max_single_order_krw:,.0f} KRW",
                )
        else:
            if amount > self._max_single_order_usd:
                return (
                    False,
                    f"ORDER_SIZE_EXCEEDED: {amount:,.2f} USD > "
                    f"limit {self._max_single_order_usd:,.2f} USD",
                )
        return True, "ORDER_SIZE_OK"

    def _check_daily_orders(self, portfolio: dict) -> tuple[bool, str]:
        """Number of orders placed today must be below the daily cap."""
        orders_today: int = portfolio.get("orders_today", 0)
        if orders_today >= self._max_orders_per_day:
            return (
                False,
                f"MAX_DAILY_ORDERS_REACHED: {orders_today} >= "
                f"limit {self._max_orders_per_day}",
            )
        return True, "DAILY_ORDERS_OK"

    def _check_daily_loss(self, portfolio: dict) -> tuple[bool, str]:
        """Daily PnL must not breach the maximum daily loss threshold."""
        daily_pnl_pct: float = portfolio.get("daily_pnl_pct", 0.0)
        if daily_pnl_pct <= self._max_daily_loss_pct:
            return (
                False,
                f"DAILY_LOSS_EXCEEDED: {daily_pnl_pct:.2%} <= "
                f"limit {self._max_daily_loss_pct:.2%}",
            )
        return True, "DAILY_LOSS_OK"

    def _check_weekly_loss(self, portfolio: dict) -> tuple[bool, str]:
        """Weekly PnL must not breach the maximum weekly loss threshold."""
        weekly_pnl_pct: float = portfolio.get("weekly_pnl_pct", 0.0)
        if weekly_pnl_pct <= self._max_weekly_loss_pct:
            return (
                False,
                f"WEEKLY_LOSS_EXCEEDED: {weekly_pnl_pct:.2%} <= "
                f"limit {self._max_weekly_loss_pct:.2%}",
            )
        return True, "WEEKLY_LOSS_OK"

    def _check_drawdown(self, portfolio: dict) -> tuple[bool, str]:
        """Maximum drawdown from peak must not breach the MDD limit."""
        drawdown_pct: float = portfolio.get("drawdown_pct", 0.0)
        if drawdown_pct <= self._max_drawdown_pct:
            return (
                False,
                f"MDD_EXCEEDED: {drawdown_pct:.2%} <= "
                f"limit {self._max_drawdown_pct:.2%}",
            )
        return True, "DRAWDOWN_OK"

    def _check_position_concentration(
        self, order: dict, portfolio: dict
    ) -> tuple[bool, str]:
        """A single stock must not exceed the maximum portfolio weight."""
        total_value: float = portfolio.get("total_value", 0.0)
        if total_value <= 0:
            return True, "POSITION_CONCENTRATION_OK"

        symbol: str = order.get("symbol", "")
        order_amount: float = order.get("amount", 0.0)

        # Sum existing exposure for the same symbol.
        existing_value: float = 0.0
        for pos in portfolio.get("positions", []):
            if pos.get("symbol") == symbol:
                existing_value += pos.get("market_value", 0.0)

        projected_pct = (existing_value + order_amount) / total_value
        if projected_pct > self._max_single_stock_pct:
            return (
                False,
                f"POSITION_CONCENTRATION_EXCEEDED: {symbol} would be "
                f"{projected_pct:.2%} > limit {self._max_single_stock_pct:.2%}",
            )
        return True, "POSITION_CONCENTRATION_OK"

    def _check_sector_concentration(
        self, order: dict, portfolio: dict
    ) -> tuple[bool, str]:
        """A single sector must not exceed the maximum portfolio weight."""
        total_value: float = portfolio.get("total_value", 0.0)
        if total_value <= 0:
            return True, "SECTOR_CONCENTRATION_OK"

        sector: str | None = order.get("sector")
        if sector is None:
            # If sector info is unavailable we cannot enforce the limit.
            return True, "SECTOR_CONCENTRATION_OK"

        order_amount: float = order.get("amount", 0.0)

        existing_sector_value: float = 0.0
        for pos in portfolio.get("positions", []):
            if pos.get("sector") == sector:
                existing_sector_value += pos.get("market_value", 0.0)

        projected_pct = (existing_sector_value + order_amount) / total_value
        if projected_pct > self._max_sector_pct:
            return (
                False,
                f"SECTOR_CONCENTRATION_EXCEEDED: {sector} would be "
                f"{projected_pct:.2%} > limit {self._max_sector_pct:.2%}",
            )
        return True, "SECTOR_CONCENTRATION_OK"

    def _check_total_positions(self, portfolio: dict) -> tuple[bool, str]:
        """Number of open positions must not exceed the cap."""
        count: int = portfolio.get("open_position_count", 0)
        if count >= self._max_total_positions:
            return (
                False,
                f"MAX_POSITIONS_REACHED: {count} >= "
                f"limit {self._max_total_positions}",
            )
        return True, "TOTAL_POSITIONS_OK"

    def _check_cash_reserve(self, order: dict, portfolio: dict) -> tuple[bool, str]:
        """Cash remaining after the order must stay above the minimum reserve."""
        cash: float = portfolio.get("cash", 0.0)
        total_value: float = portfolio.get("total_value", 0.0)
        order_amount: float = order.get("amount", 0.0)

        if total_value <= 0:
            return True, "CASH_RESERVE_OK"

        projected_cash = cash - order_amount
        projected_pct = projected_cash / total_value
        if projected_pct < self._min_cash_reserve_pct:
            return (
                False,
                f"CASH_RESERVE_INSUFFICIENT: remaining cash would be "
                f"{projected_pct:.2%} < limit {self._min_cash_reserve_pct:.2%}",
            )
        return True, "CASH_RESERVE_OK"
