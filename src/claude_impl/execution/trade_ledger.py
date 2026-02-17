"""Trade ledger for recording all buy/sell events.

Every execution -- paper or live -- is recorded through the
:class:`TradeLedger`.  The primary persistence target is BigQuery
(table ``trade_ledger``); when BigQuery is unavailable, trades are
stored in an in-memory list so that the system keeps running and the
data can be reconciled later.

The ledger also provides convenience queries for net-quantity
calculations, holdings snapshots, and pre-sell validation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"symbol", "market", "side", "quantity", "price"}
)


class TradeLedger:
    """Immutable, append-only trade record store.

    Parameters
    ----------
    bigquery_client:
        An optional :class:`~claude_impl.infrastructure.bigquery_client.BigQueryClient`.
        When ``None`` or unavailable, trades are kept in-memory only.
    config:
        Application configuration dict.  Currently uses:

        - ``execution.trade_ledger_table`` (default ``"trade_ledger"``)
    """

    def __init__(
        self,
        bigquery_client: Any | None = None,
        config: dict | None = None,
    ) -> None:
        self._bq = bigquery_client
        self._config = config or {}
        self._table: str = (
            self._config.get("execution", {})
            .get("trade_ledger_table", "trade_ledger")
        )
        # In-memory fallback / local buffer.
        self._trades: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, trade: dict) -> dict:
        """Validate and persist a trade record.

        Parameters
        ----------
        trade:
            A dict containing **at minimum** the keys ``symbol``,
            ``market``, ``side``, ``quantity``, and ``price``.

            Optional but recommended: ``source``, ``reason_codes``,
            ``recommendation_id``, ``realized_pnl``.

        Returns
        -------
        dict
            The enriched trade record (with ``trade_id``, ``executed_at``,
            etc.) as actually stored.

        Raises
        ------
        ValueError
            If any of the required fields are missing.
        """
        # Validate required fields.
        missing = _REQUIRED_FIELDS - trade.keys()
        if missing:
            raise ValueError(
                f"Trade record missing required fields: {sorted(missing)}"
            )

        # Enrich the record.
        enriched: dict = {**trade}
        enriched.setdefault("trade_id", str(uuid.uuid4()))
        enriched.setdefault(
            "executed_at", datetime.now(timezone.utc).isoformat()
        )
        enriched["quantity"] = int(enriched["quantity"])
        enriched["price"] = float(enriched["price"])

        # Persist to BigQuery.
        bq_ok = False
        if self._bq is not None:
            try:
                errors = self._bq.insert_rows(self._table, [enriched])
                if not errors:
                    bq_ok = True
                else:
                    logger.warning(
                        "BigQuery insert errors for trade %s: %s",
                        enriched["trade_id"],
                        errors,
                    )
            except Exception:
                logger.warning(
                    "BigQuery insert failed for trade %s, using in-memory fallback.",
                    enriched["trade_id"],
                    exc_info=True,
                )

        # Always keep a local copy.
        self._trades.append(enriched)

        if bq_ok:
            logger.info(
                "Trade recorded (BQ) %s %s:%s %s x%d @ %.4f",
                enriched["trade_id"][:8],
                enriched["market"],
                enriched["symbol"],
                enriched["side"],
                enriched["quantity"],
                enriched["price"],
            )
        else:
            logger.info(
                "Trade recorded (mem) %s %s:%s %s x%d @ %.4f",
                enriched["trade_id"][:8],
                enriched["market"],
                enriched["symbol"],
                enriched["side"],
                enriched["quantity"],
                enriched["price"],
            )

        return enriched

    def get_trades(
        self,
        symbol: str | None = None,
        market: str | None = None,
    ) -> list[dict]:
        """Return stored trades, optionally filtered by symbol and/or market.

        Parameters
        ----------
        symbol:
            If provided, only trades for this symbol are returned.
        market:
            If provided, only trades in this market are returned.

        Returns
        -------
        list[dict]
            Matching trade records ordered by insertion time.
        """
        result: list[dict] = self._trades
        if symbol is not None:
            result = [t for t in result if t.get("symbol") == symbol]
        if market is not None:
            result = [t for t in result if t.get("market") == market]
        return result

    def get_net_quantity(self, symbol: str, market: str) -> int:
        """Calculate net held quantity for a symbol.

        ``net_quantity = SUM(BUY quantities) - SUM(SELL quantities)``

        Parameters
        ----------
        symbol:
            Ticker or stock code.
        market:
            ``"KR"`` or ``"US"``.

        Returns
        -------
        int
            Net held shares.  Can be zero but should never be negative
            in a well-behaved system.
        """
        trades = self.get_trades(symbol=symbol, market=market)
        buy_qty = sum(
            int(t["quantity"])
            for t in trades
            if t.get("side") == "BUY"
        )
        sell_qty = sum(
            int(t["quantity"])
            for t in trades
            if t.get("side") == "SELL"
        )
        return buy_qty - sell_qty

    def get_current_holdings(self) -> dict[str, int]:
        """Return a snapshot of all symbols with positive net quantity.

        Returns
        -------
        dict[str, int]
            ``{"{market}:{symbol}": net_quantity, ...}`` for every
            symbol where ``net_quantity > 0``.
        """
        # Collect all unique (market, symbol) pairs.
        pairs: set[tuple[str, str]] = set()
        for t in self._trades:
            m = t.get("market", "")
            s = t.get("symbol", "")
            if m and s:
                pairs.add((m, s))

        holdings: dict[str, int] = {}
        for market, symbol in pairs:
            net = self.get_net_quantity(symbol, market)
            if net > 0:
                holdings[f"{market}:{symbol}"] = net
        return holdings

    def validate_sell(
        self,
        symbol: str,
        market: str,
        quantity: int,
    ) -> None:
        """Pre-validate a sell order against the ledger.

        Raises
        ------
        ValueError
            If ``net_quantity <= 0`` (no open position) or if
            ``quantity > net_quantity`` (over-sell).
        """
        net = self.get_net_quantity(symbol, market)
        if net <= 0:
            raise ValueError(
                f"NO_OPEN_POSITION: {market}:{symbol} net_quantity={net}"
            )
        if quantity > net:
            raise ValueError(
                f"OVERSELL: cannot sell {quantity} shares of "
                f"{market}:{symbol} -- only {net} held."
            )
