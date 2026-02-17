"""Redis-backed position tracking.

Maintains real-time position state in Redis so that every component
(risk gate, portfolio analyser, execution engine) can read the latest
open positions without a database round-trip.

Redis key schema::

    position:{market}:{symbol}   -- JSON blob with position details

The :class:`PositionManager` is used by both the :class:`PaperExecutor`
(Phase 1-2) and the live broker adapters (Phase 3).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


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


class PositionManager:
    """Track open positions via Redis.

    Each position is stored as a JSON blob under the key
    ``position:{market}:{symbol}`` and contains average cost, quantity,
    peak price (for trailing-stop calculations), and unrealised P&L.

    Parameters
    ----------
    redis_client:
        A :class:`~claude_impl.infrastructure.redis_client.RedisClient`
        instance (or any object exposing ``get``, ``set``, ``get_json``,
        ``set_json``, ``delete``, ``keys``).
    config:
        Application configuration dict.  Currently used for:

        - ``position.stop_loss_pct`` (default ``0.05`` = -5%)
        - ``position.trailing_stop_pct`` (default ``0.03`` = -3% from peak)
    """

    def __init__(self, redis_client: Any, config: dict | None = None) -> None:
        self._redis = redis_client
        self._config = config or {}
        self._stop_loss_pct: float = float(
            _nested_get(self._config, "position.stop_loss_pct", 0.05)
        )
        self._trailing_stop_pct: float = float(
            _nested_get(self._config, "position.trailing_stop_pct", 0.03)
        )

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(market: str, symbol: str) -> str:
        """Return the Redis key for a position."""
        return f"position:{market}:{symbol}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_position(
        self,
        symbol: str,
        market: str,
        quantity: int,
        price: float,
    ) -> None:
        """Create or add to an existing position.

        If a position already exists for this symbol/market pair, the
        average cost is recalculated and the quantity is incremented.
        Otherwise a brand-new position record is created.

        Parameters
        ----------
        symbol:
            Ticker or stock code.
        market:
            ``"KR"`` or ``"US"``.
        quantity:
            Number of shares purchased.
        price:
            Fill price per share (after slippage).
        """
        key = self._key(market, symbol)
        existing = self._redis.get_json(key)

        now_iso = datetime.now(timezone.utc).isoformat()

        if existing is not None:
            # Update existing position with new average cost.
            old_qty = int(existing.get("quantity", 0))
            old_avg = float(existing.get("avg_cost", 0.0))
            new_qty = old_qty + quantity
            new_avg = ((old_avg * old_qty) + (price * quantity)) / new_qty if new_qty else 0.0

            existing["quantity"] = new_qty
            existing["avg_cost"] = round(new_avg, 4)
            existing["current_price"] = price
            existing["peak_price"] = max(
                float(existing.get("peak_price", price)), price
            )
            existing["unrealized_pnl"] = round(
                (price - new_avg) * new_qty, 4
            )
            existing["unrealized_pnl_pct"] = (
                round((price - new_avg) / new_avg, 6) if new_avg else 0.0
            )
            existing["stop_loss_price"] = round(
                new_avg * (1.0 - self._stop_loss_pct), 4
            )
            existing["trailing_stop"] = round(
                float(existing["peak_price"]) * (1.0 - self._trailing_stop_pct), 4
            )
            existing["updated_at"] = now_iso

            self._redis.set_json(key, existing)
            logger.info(
                "Position updated %s:%s -- qty=%d avg_cost=%.4f",
                market, symbol, new_qty, new_avg,
            )
        else:
            # Brand-new position.
            position: dict = {
                "symbol": symbol,
                "market": market,
                "quantity": quantity,
                "avg_cost": round(price, 4),
                "current_price": price,
                "peak_price": price,
                "opened_at": now_iso,
                "updated_at": now_iso,
                "unrealized_pnl": 0.0,
                "unrealized_pnl_pct": 0.0,
                "stop_loss_price": round(
                    price * (1.0 - self._stop_loss_pct), 4
                ),
                "trailing_stop": round(
                    price * (1.0 - self._trailing_stop_pct), 4
                ),
            }
            self._redis.set_json(key, position)
            logger.info(
                "Position opened %s:%s -- qty=%d @ %.4f",
                market, symbol, quantity, price,
            )

    def close_position(
        self,
        symbol: str,
        market: str,
        quantity: int,
        price: float,
    ) -> dict:
        """Reduce or fully close an existing position.

        Parameters
        ----------
        symbol:
            Ticker or stock code.
        market:
            ``"KR"`` or ``"US"``.
        quantity:
            Number of shares to sell.
        price:
            Fill price per share (after slippage).

        Returns
        -------
        dict
            ``{"realized_pnl": float, "realized_pnl_pct": float}``
            representing the profit/loss for the sold shares.

        Raises
        ------
        ValueError
            If there is no open position, or if *quantity* exceeds the
            currently held shares.
        """
        key = self._key(market, symbol)
        existing = self._redis.get_json(key)

        if existing is None:
            raise ValueError(
                f"No open position for {market}:{symbol} -- cannot close."
            )

        held_qty = int(existing.get("quantity", 0))
        if quantity > held_qty:
            raise ValueError(
                f"Cannot sell {quantity} shares of {market}:{symbol} -- "
                f"only {held_qty} held."
            )

        avg_cost = float(existing.get("avg_cost", 0.0))
        realized_pnl = round((price - avg_cost) * quantity, 4)
        realized_pnl_pct = (
            round((price - avg_cost) / avg_cost, 6) if avg_cost else 0.0
        )

        remaining_qty = held_qty - quantity
        now_iso = datetime.now(timezone.utc).isoformat()

        if remaining_qty == 0:
            # Fully closed -- remove from Redis.
            self._redis.delete(key)
            logger.info(
                "Position closed %s:%s -- sold %d @ %.4f | PnL=%.4f (%.4f%%)",
                market, symbol, quantity, price,
                realized_pnl, realized_pnl_pct * 100,
            )
        else:
            # Partial close -- update remaining quantity.
            existing["quantity"] = remaining_qty
            existing["current_price"] = price
            existing["unrealized_pnl"] = round(
                (price - avg_cost) * remaining_qty, 4
            )
            existing["unrealized_pnl_pct"] = (
                round((price - avg_cost) / avg_cost, 6) if avg_cost else 0.0
            )
            existing["peak_price"] = max(
                float(existing.get("peak_price", price)), price
            )
            existing["trailing_stop"] = round(
                float(existing["peak_price"]) * (1.0 - self._trailing_stop_pct), 4
            )
            existing["updated_at"] = now_iso
            self._redis.set_json(key, existing)
            logger.info(
                "Position reduced %s:%s -- sold %d @ %.4f, remaining=%d | PnL=%.4f (%.4f%%)",
                market, symbol, quantity, price, remaining_qty,
                realized_pnl, realized_pnl_pct * 100,
            )

        return {
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
        }

    def update_prices(
        self,
        symbol: str,
        market: str,
        current_price: float,
    ) -> None:
        """Update the live price, peak price, and unrealised P&L for a
        position.

        Call this periodically (e.g. on every price tick or every N
        seconds) so that trailing-stop and portfolio analytics stay
        fresh.

        Parameters
        ----------
        symbol:
            Ticker or stock code.
        market:
            ``"KR"`` or ``"US"``.
        current_price:
            Latest market price.
        """
        key = self._key(market, symbol)
        existing = self._redis.get_json(key)
        if existing is None:
            return  # no open position -- nothing to update

        avg_cost = float(existing.get("avg_cost", 0.0))
        qty = int(existing.get("quantity", 0))
        old_peak = float(existing.get("peak_price", current_price))
        new_peak = max(old_peak, current_price)

        existing["current_price"] = current_price
        existing["peak_price"] = new_peak
        existing["unrealized_pnl"] = round(
            (current_price - avg_cost) * qty, 4
        )
        existing["unrealized_pnl_pct"] = (
            round((current_price - avg_cost) / avg_cost, 6) if avg_cost else 0.0
        )
        existing["trailing_stop"] = round(
            new_peak * (1.0 - self._trailing_stop_pct), 4
        )
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()

        self._redis.set_json(key, existing)

    def get_position(self, market: str, symbol: str) -> dict | None:
        """Return the current position for a symbol, or ``None``.

        Parameters
        ----------
        market:
            ``"KR"`` or ``"US"``.
        symbol:
            Ticker or stock code.

        Returns
        -------
        dict | None
            The position blob, or ``None`` if no position exists.
        """
        return self._redis.get_json(self._key(market, symbol))

    def get_all_positions(self) -> list[dict]:
        """Return all open positions across all markets.

        Returns
        -------
        list[dict]
            A list of position dicts, one per open position.
        """
        keys = self._redis.keys("position:*")
        positions: list[dict] = []
        for key in keys:
            data = self._redis.get_json(key)
            if data is not None:
                positions.append(data)
        return positions

    def get_portfolio_state(self, total_capital: float) -> dict:
        """Build a portfolio-state summary compatible with risk-gate and
        analysis contexts.

        Parameters
        ----------
        total_capital:
            Total account capital (cash + positions value).

        Returns
        -------
        dict
            A :class:`PortfolioState`-compatible dict with keys:

            - ``total_capital``
            - ``invested_amount`` -- sum of (avg_cost * qty) across positions
            - ``cash_amount`` -- total_capital - invested_amount
            - ``cash_ratio`` -- cash_amount / total_capital
            - ``position_count`` -- number of open positions
            - ``total_unrealized_pnl``
            - ``total_unrealized_pnl_pct``
            - ``positions`` -- full list of position dicts
        """
        positions = self.get_all_positions()

        invested_amount = sum(
            float(p.get("avg_cost", 0)) * int(p.get("quantity", 0))
            for p in positions
        )
        cash_amount = total_capital - invested_amount
        cash_ratio = cash_amount / total_capital if total_capital > 0 else 1.0

        total_unrealized_pnl = sum(
            float(p.get("unrealized_pnl", 0)) for p in positions
        )
        total_unrealized_pnl_pct = (
            total_unrealized_pnl / invested_amount if invested_amount > 0 else 0.0
        )

        return {
            "total_capital": total_capital,
            "invested_amount": round(invested_amount, 4),
            "cash_amount": round(cash_amount, 4),
            "cash_ratio": round(cash_ratio, 6),
            "position_count": len(positions),
            "total_unrealized_pnl": round(total_unrealized_pnl, 4),
            "total_unrealized_pnl_pct": round(total_unrealized_pnl_pct, 6),
            "positions": positions,
        }
