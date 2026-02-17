"""3-Tier stock universe management.

Implements the universe structure from the 10-stock-universe design document:

- **Tier 1** (KR 30 + US 30): 5-minute price+news, full analysis, signal
  generation.
- **Tier 2** (KR 50 + US 50): 5-minute price, keyword-only news scan,
  promotion candidates.
- **Tier 3** (full market): daily bar screening after market close.

Universe state is persisted in Redis (for fast look-up) and BigQuery
(``stock_universe`` table for audit trail and history).

Configuration keys consumed::

    universe.tier1.kr.symbols   -- manual Tier 1 KR symbol list
    universe.tier1.us.symbols   -- manual Tier 1 US symbol list
    universe.tier2.kr.symbols   -- manual Tier 2 KR symbol list
    universe.tier2.us.symbols   -- manual Tier 2 US symbol list
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


# Redis key templates
_REDIS_KEY_TIER1 = "universe:{market}:tier1"
_REDIS_KEY_TIER2 = "universe:{market}:tier2"
_REDIS_KEY_HISTORY = "universe:{market}:history"

# BigQuery table name
_BQ_TABLE = "stock_universe"


class TierManager:
    """Manage the 3-tier stock universe.

    Parameters
    ----------
    config:
        System configuration dict.
    bigquery_client:
        An object exposing ``.insert_rows(table, rows)`` and
        ``.query(sql, params)`` methods (matching
        :class:`~claude_impl.infrastructure.bigquery_client.BigQueryClient`).
        If ``None``, BigQuery persistence is skipped.
    redis_client:
        An object exposing ``.get_json(key)``, ``.set_json(key, value, ttl)``
        methods (matching
        :class:`~claude_impl.infrastructure.redis_client.RedisClient`).
        If ``None``, in-memory dicts are used.
    """

    def __init__(
        self,
        config: dict,
        bigquery_client: Any | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self._config = config
        self._bq = bigquery_client
        self._redis = redis_client

        # In-memory fallback when Redis is not available
        self._mem_tier1: dict[str, list[str]] = {"KR": [], "US": []}
        self._mem_tier2: dict[str, list[str]] = {"KR": [], "US": []}

        # Initialise from config (manual symbol lists)
        self._init_from_config()

    # -- initialisation ------------------------------------------------------

    def _init_from_config(self) -> None:
        """Seed tier lists from configuration ``symbols`` arrays.

        If ``symbols`` is empty or absent, the tier starts empty (to be
        populated by auto-selection or promotion logic).
        """
        for market in ("KR", "US"):
            tier1_symbols: list[str] = _nested_get(
                self._config,
                f"universe.tier1.{market.lower()}.symbols",
                [],
            )
            tier2_symbols: list[str] = _nested_get(
                self._config,
                f"universe.tier2.{market.lower()}.symbols",
                [],
            )

            if tier1_symbols:
                self._set_tier(market, 1, tier1_symbols)
            if tier2_symbols:
                self._set_tier(market, 2, tier2_symbols)

    # -- Redis helpers -------------------------------------------------------

    def _redis_key(self, market: str, tier: int) -> str:
        """Return the Redis key for a given market and tier."""
        template = _REDIS_KEY_TIER1 if tier == 1 else _REDIS_KEY_TIER2
        return template.format(market=market.upper())

    def _get_tier(self, market: str, tier: int) -> list[str]:
        """Read the symbol list for a tier from Redis or memory."""
        market = market.upper()
        if self._redis is not None:
            key = self._redis_key(market, tier)
            data = self._redis.get_json(key)
            if data is not None and isinstance(data, list):
                return data

        # Fallback to in-memory
        store = self._mem_tier1 if tier == 1 else self._mem_tier2
        return list(store.get(market, []))

    def _set_tier(self, market: str, tier: int, symbols: list[str]) -> None:
        """Write the symbol list for a tier to Redis and memory."""
        market = market.upper()
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for s in symbols:
            if s not in seen:
                seen.add(s)
                unique.append(s)

        store = self._mem_tier1 if tier == 1 else self._mem_tier2
        store[market] = unique

        if self._redis is not None:
            key = self._redis_key(market, tier)
            # No TTL -- universe data should persist until explicitly changed
            self._redis.set_json(key, unique)

    # -- BigQuery persistence ------------------------------------------------

    def _record_change(
        self,
        symbol: str,
        market: str,
        old_tier: int,
        new_tier: int,
        reason: str,
    ) -> None:
        """Write a tier-change record to BigQuery for audit trail."""
        if self._bq is None:
            logger.debug(
                "Tier change not recorded (no BigQuery client): "
                "%s %s tier %d -> %d (%s)",
                market,
                symbol,
                old_tier,
                new_tier,
                reason,
            )
            return

        row = {
            "symbol": symbol,
            "market": market.upper(),
            "tier": new_tier,
            "previous_tier": old_tier,
            "promote_reason": reason,
            "tier_changed_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        errors = self._bq.insert_rows(_BQ_TABLE, [row])
        if errors:
            logger.error(
                "Failed to record tier change in BigQuery: %s",
                errors,
            )
        else:
            logger.info(
                "Recorded tier change: %s %s tier %d -> %d (%s)",
                market,
                symbol,
                old_tier,
                new_tier,
                reason,
            )

    # -- public API ----------------------------------------------------------

    def get_tier1_symbols(self, market: str) -> list[str]:
        """Return the Tier 1 symbol list for *market*.

        Tier 1 symbols receive full 5-minute price+news collection,
        full analysis, and signal generation.
        """
        return self._get_tier(market, 1)

    def get_tier2_symbols(self, market: str) -> list[str]:
        """Return the Tier 2 symbol list for *market*.

        Tier 2 symbols receive 5-minute price collection and keyword-only
        news scanning.  They are candidates for promotion to Tier 1.
        """
        return self._get_tier(market, 2)

    def get_all_tracked_symbols(self, market: str) -> list[str]:
        """Return all tracked symbols (Tier 1 + Tier 2) for *market*."""
        tier1 = self.get_tier1_symbols(market)
        tier2 = self.get_tier2_symbols(market)

        # Merge without duplicates, Tier 1 first
        seen: set[str] = set(tier1)
        combined = list(tier1)
        for s in tier2:
            if s not in seen:
                seen.add(s)
                combined.append(s)

        return combined

    def promote(self, symbol: str, market: str, reason: str) -> None:
        """Promote a symbol from Tier 2 to Tier 1.

        If the symbol is not currently in Tier 2, it is added directly
        to Tier 1.  If it is already in Tier 1, this is a no-op.

        Parameters
        ----------
        symbol:
            Ticker or stock code.
        market:
            ``"KR"`` or ``"US"``.
        reason:
            Machine-readable promotion reason (e.g. ``"NEWS_SPIKE"``).
        """
        market = market.upper()
        tier1 = self._get_tier(market, 1)
        tier2 = self._get_tier(market, 2)

        if symbol in tier1:
            logger.debug("%s already in Tier 1 for %s, skipping promote.", symbol, market)
            return

        # Remove from Tier 2 if present
        if symbol in tier2:
            tier2 = [s for s in tier2 if s != symbol]
            self._set_tier(market, 2, tier2)

        # Add to Tier 1
        tier1.append(symbol)
        self._set_tier(market, 1, tier1)

        self._record_change(symbol, market, old_tier=2, new_tier=1, reason=reason)
        logger.info(
            "Promoted %s to Tier 1 in %s market (reason: %s)",
            symbol,
            market,
            reason,
        )

    def demote(self, symbol: str, market: str, reason: str) -> None:
        """Demote a symbol from Tier 1 to Tier 2.

        If the symbol is not currently in Tier 1, it is added directly
        to Tier 2.  If it is already in Tier 2, this is a no-op.

        Parameters
        ----------
        symbol:
            Ticker or stock code.
        market:
            ``"KR"`` or ``"US"``.
        reason:
            Machine-readable demotion reason (e.g. ``"NO_SIGNAL_30D"``).
        """
        market = market.upper()
        tier1 = self._get_tier(market, 1)
        tier2 = self._get_tier(market, 2)

        if symbol in tier2 and symbol not in tier1:
            logger.debug("%s already in Tier 2 for %s, skipping demote.", symbol, market)
            return

        # Remove from Tier 1 if present
        if symbol in tier1:
            tier1 = [s for s in tier1 if s != symbol]
            self._set_tier(market, 1, tier1)

        # Add to Tier 2
        if symbol not in tier2:
            tier2.append(symbol)
            self._set_tier(market, 2, tier2)

        self._record_change(symbol, market, old_tier=1, new_tier=2, reason=reason)
        logger.info(
            "Demoted %s to Tier 2 in %s market (reason: %s)",
            symbol,
            market,
            reason,
        )

    def update_universe(
        self,
        market: str,
        promotions: list[dict],
        demotions: list[dict],
    ) -> None:
        """Apply a batch of promotions and demotions.

        Parameters
        ----------
        market:
            ``"KR"`` or ``"US"``.
        promotions:
            List of dicts, each with ``symbol`` and ``reason`` keys.
        demotions:
            List of dicts, each with ``symbol`` and ``reason`` keys.

        Demotions are applied first so that a symbol can be demoted and
        then re-promoted within the same batch if needed.
        """
        for item in demotions:
            symbol = item.get("symbol", "")
            reason = item.get("reason", "BATCH_DEMOTION")
            if symbol:
                self.demote(symbol, market, reason)

        for item in promotions:
            symbol = item.get("symbol", "")
            reason = item.get("reason", "BATCH_PROMOTION")
            if symbol:
                self.promote(symbol, market, reason)

        logger.info(
            "Universe update for %s: %d promotions, %d demotions",
            market,
            len(promotions),
            len(demotions),
        )

    def get_universe_snapshot(self) -> dict:
        """Return a snapshot of the current universe state.

        Returns
        -------
        dict
            Nested dict with structure::

                {
                    "timestamp": "2026-02-16T12:00:00+00:00",
                    "KR": {
                        "tier1": ["005930", ...],
                        "tier2": ["000270", ...],
                        "tier1_count": 30,
                        "tier2_count": 50,
                        "total_tracked": 80,
                    },
                    "US": { ... },
                }
        """
        snapshot: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }

        for market in ("KR", "US"):
            tier1 = self.get_tier1_symbols(market)
            tier2 = self.get_tier2_symbols(market)
            snapshot[market] = {
                "tier1": tier1,
                "tier2": tier2,
                "tier1_count": len(tier1),
                "tier2_count": len(tier2),
                "total_tracked": len(tier1) + len(tier2),
            }

        return snapshot
