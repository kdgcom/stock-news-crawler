"""Paper trading executor for Phase 1-2.

Simulates order execution without placing real orders through a broker API.
Uses Redis-cached prices with configurable slippage to approximate realistic
fill behaviour.  All trades are recorded to the :class:`TradeLedger` and
positions are tracked via :class:`PositionManager`.

Configuration keys consumed::

    execution.slippage_pct   -- slippage as a fraction (default ``0.001`` = 0.1%)
    execution.kill_switch_key -- Redis key for the kill switch
                                 (default ``kill_switch:active``)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .position_manager import PositionManager
    from .trade_ledger import TradeLedger

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


class PaperExecutor:
    """Simulated order executor -- no real API calls.

    Executes buy/sell signals against Redis-cached prices, applying a
    configurable slippage spread.  Every execution is tracked through
    the :class:`PositionManager` and persisted via the :class:`TradeLedger`.

    Parameters
    ----------
    config:
        Application configuration dict.
    redis_client:
        A :class:`~claude_impl.infrastructure.redis_client.RedisClient` instance.
    position_manager:
        A :class:`PositionManager` instance for tracking open positions.
    trade_ledger:
        A :class:`TradeLedger` instance for recording executed trades.
    """

    def __init__(
        self,
        config: dict,
        redis_client: Any,
        position_manager: PositionManager,
        trade_ledger: TradeLedger,
    ) -> None:
        self._config = config
        self._redis = redis_client
        self._position_manager = position_manager
        self._trade_ledger = trade_ledger

        self._slippage_pct: float = float(
            _nested_get(config, "execution.slippage_pct", 0.001)
        )
        self._kill_switch_key: str = str(
            _nested_get(config, "execution.kill_switch_key", "kill_switch:active")
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, signal: dict) -> dict:
        """Execute a trading signal in paper-trading mode.

        Parameters
        ----------
        signal:
            A dict with at least the following keys:

            - ``symbol`` (str): ticker / stock code
            - ``market`` (str): ``"KR"`` or ``"US"``
            - ``decision`` (str): ``"BUY"`` or ``"SELL"``
            - ``quantity`` (int): number of shares

            Optional keys:

            - ``price`` (float): override price (bypasses cache lookup)
            - ``algorithm`` (str): originating algorithm name
            - ``reason_codes`` (list[str]): machine-readable reason tags

        Returns
        -------
        dict
            ``{"status": "FILLED", "price": <fill_price>, ...}`` on success,
            or ``{"status": "BLOCKED", "reason": <reason>}`` when blocked.
        """
        symbol: str = signal["symbol"]
        market: str = signal.get("market", "KR")
        decision: str = signal["decision"]
        quantity: int = int(signal["quantity"])

        # 1. Kill switch check ------------------------------------------------
        if self._is_kill_switch_active():
            logger.warning(
                "KILL_SWITCH active -- blocking %s %s %s x%d",
                decision, market, symbol, quantity,
            )
            return {"status": "BLOCKED", "reason": "KILL_SWITCH"}

        # 2. Current price from Redis cache -----------------------------------
        current_price = self._get_current_price(signal)
        if current_price is None:
            reason = f"NO_PRICE_DATA: price_cache:{symbol}"
            logger.warning(
                "No cached price for %s:%s -- blocking trade.", market, symbol,
            )
            return {"status": "BLOCKED", "reason": reason}

        # 3. Apply slippage ---------------------------------------------------
        slippage = current_price * self._slippage_pct
        if decision == "BUY":
            fill_price = round(current_price + slippage, 4)
        elif decision == "SELL":
            fill_price = round(current_price - slippage, 4)
        else:
            reason = f"INVALID_DECISION: {decision}"
            logger.error("Invalid decision '%s' in signal for %s", decision, symbol)
            return {"status": "BLOCKED", "reason": reason}

        # 4. Position management ----------------------------------------------
        try:
            pnl_info: dict | None = None
            if decision == "BUY":
                self._position_manager.open_position(
                    symbol=symbol,
                    market=market,
                    quantity=quantity,
                    price=fill_price,
                )
            elif decision == "SELL":
                pnl_info = self._position_manager.close_position(
                    symbol=symbol,
                    market=market,
                    quantity=quantity,
                    price=fill_price,
                )
        except Exception:
            logger.exception(
                "Position management failed for %s %s %s x%d @ %.4f",
                decision, market, symbol, quantity, fill_price,
            )
            return {"status": "BLOCKED", "reason": "POSITION_MANAGER_ERROR"}

        # 5. Record to trade ledger -------------------------------------------
        trade_record: dict = {
            "symbol": symbol,
            "market": market,
            "side": decision,
            "quantity": quantity,
            "price": fill_price,
            "slippage_pct": self._slippage_pct,
            "source": signal.get("algorithm", "paper_executor"),
            "reason_codes": signal.get("reason_codes", []),
        }
        if pnl_info is not None:
            trade_record["realized_pnl"] = pnl_info.get("realized_pnl")
            trade_record["realized_pnl_pct"] = pnl_info.get("realized_pnl_pct")

        self._trade_ledger.record(trade_record)

        # 6. Log and return ---------------------------------------------------
        logger.info(
            "PAPER %s %s:%s x%d @ %.4f (slippage=%.4f%%)",
            decision,
            market,
            symbol,
            quantity,
            fill_price,
            self._slippage_pct * 100,
        )

        result: dict = {
            "status": "FILLED",
            "price": fill_price,
            "symbol": symbol,
            "market": market,
            "side": decision,
            "quantity": quantity,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
        if pnl_info is not None:
            result["realized_pnl"] = pnl_info.get("realized_pnl")
            result["realized_pnl_pct"] = pnl_info.get("realized_pnl_pct")

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_kill_switch_active(self) -> bool:
        """Return ``True`` if the global kill switch is engaged."""
        value = self._redis.get(self._kill_switch_key)
        if value is None:
            return False
        return str(value).strip().lower() in ("1", "true", "yes", "active")

    def _get_current_price(self, signal: dict) -> float | None:
        """Resolve the current price for the signal's symbol.

        Uses an explicit ``price`` field from the signal if present,
        otherwise falls back to the Redis ``price_cache:{symbol}`` key.
        """
        # Allow caller to provide an explicit price override.
        explicit = signal.get("price")
        if explicit is not None:
            try:
                return float(explicit)
            except (TypeError, ValueError):
                pass

        raw = self._redis.get(f"price_cache:{signal['symbol']}")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            logger.warning(
                "Non-numeric price_cache value for %s: %r",
                signal["symbol"],
                raw,
            )
            return None
