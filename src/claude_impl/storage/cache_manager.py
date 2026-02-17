"""Unified Redis cache manager for the stock trading system.

Key spaces
----------
``price_cache:{symbol}``     -- list of recent bar JSON strings (newest first)
``sentiment:{symbol}``       -- latest aggregated sentiment JSON
``position:{market}:{symbol}`` -- current position JSON
``universe:{tier}``          -- set of symbol strings for a tier
``config:{key}``             -- arbitrary config string values

All TTLs are configurable via the *config* dict passed at init time.
Defaults follow the design doc (``md/plan_detail/04-data-storage.md``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---- Default TTLs (seconds) ----
_DEFAULT_PRICE_TTL = 86_400       # 24 hours
_DEFAULT_SENTIMENT_TTL = 1_800    # 30 minutes
_DEFAULT_POSITION_TTL = 86_400    # 24 hours
_DEFAULT_UNIVERSE_TTL = 3_600     # 1 hour
_DEFAULT_CONFIG_TTL = 0           # 0 = no expiry

# ---- Key prefixes ----
_PRICE_PREFIX = "price_cache"
_SENTIMENT_PREFIX = "sentiment"
_POSITION_PREFIX = "position"
_UNIVERSE_PREFIX = "universe"
_CONFIG_PREFIX = "config"

_MAX_PRICE_HISTORY = 200


class CacheManager:
    """Centralised, fault-tolerant Redis cache for all real-time data.

    Parameters
    ----------
    redis_client:
        A ``RedisClient`` (or compatible ``redis.Redis`` instance).
    config:
        Optional overrides for TTLs and limits.  Recognised keys:

        * ``price_ttl``     -- TTL for price cache keys (default 86400).
        * ``sentiment_ttl`` -- TTL for sentiment keys (default 1800).
        * ``position_ttl``  -- TTL for position keys (default 86400).
        * ``universe_ttl``  -- TTL for universe keys (default 3600).
        * ``config_ttl``    -- TTL for config keys (default 0 = no expiry).
        * ``max_price_history`` -- max bars per symbol (default 200).
    """

    def __init__(self, redis_client: Any, config: dict | None = None) -> None:
        self._redis = redis_client
        cfg = config or {}

        self._price_ttl: int = cfg.get("price_ttl", _DEFAULT_PRICE_TTL)
        self._sentiment_ttl: int = cfg.get("sentiment_ttl", _DEFAULT_SENTIMENT_TTL)
        self._position_ttl: int = cfg.get("position_ttl", _DEFAULT_POSITION_TTL)
        self._universe_ttl: int = cfg.get("universe_ttl", _DEFAULT_UNIVERSE_TTL)
        self._config_ttl: int = cfg.get("config_ttl", _DEFAULT_CONFIG_TTL)
        self._max_price_history: int = cfg.get("max_price_history", _MAX_PRICE_HISTORY)

    # ==================================================================
    # Price cache
    # ==================================================================

    def set_price(self, symbol: str, bar: dict) -> None:
        """Push a new bar onto the price list for *symbol*.

        The list is capped to :pyattr:`_max_price_history` entries and the
        key receives the configured ``price_ttl``.
        """
        key = f"{_PRICE_PREFIX}:{symbol}"
        try:
            self._redis.lpush(key, json.dumps(bar, default=str))
            self._redis.ltrim(key, 0, self._max_price_history - 1)
            if self._price_ttl > 0:
                self._redis.expire(key, self._price_ttl)
        except Exception:
            logger.warning("set_price failed for %s", symbol, exc_info=True)

    def get_price(self, symbol: str) -> dict | None:
        """Return the most recent bar for *symbol*, or ``None``."""
        key = f"{_PRICE_PREFIX}:{symbol}"
        try:
            raw = self._redis.lindex(key, 0)
            if raw is None:
                return None
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return json.loads(text)
        except Exception:
            logger.warning("get_price failed for %s", symbol, exc_info=True)
            return None

    def get_price_history(self, symbol: str, count: int = 200) -> list[dict]:
        """Return up to *count* recent bars for *symbol* (newest first)."""
        key = f"{_PRICE_PREFIX}:{symbol}"
        effective_count = min(count, self._max_price_history)
        try:
            raw_items: list[bytes | str] = self._redis.lrange(
                key, 0, effective_count - 1,
            )
            results: list[dict] = []
            for item in raw_items:
                try:
                    text = item.decode("utf-8") if isinstance(item, bytes) else item
                    results.append(json.loads(text))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.debug("Skipping unparseable bar in price history for %s",
                                 symbol)
            return results
        except Exception:
            logger.warning("get_price_history failed for %s", symbol, exc_info=True)
            return []

    # ==================================================================
    # Sentiment cache
    # ==================================================================

    def set_sentiment(self, symbol: str, data: dict, ttl: int = 1800) -> None:
        """Cache an aggregated sentiment payload for *symbol*.

        Parameters
        ----------
        ttl:
            Override for this specific call.  Falls back to configured
            ``sentiment_ttl`` when caller passes the default ``1800``.
        """
        key = f"{_SENTIMENT_PREFIX}:{symbol}"
        effective_ttl = ttl if ttl != 1800 else self._sentiment_ttl
        try:
            self._redis.set(
                key,
                json.dumps(data, default=str),
                ex=effective_ttl if effective_ttl > 0 else None,
            )
        except Exception:
            logger.warning("set_sentiment failed for %s", symbol, exc_info=True)

    def get_sentiment(self, symbol: str) -> dict | None:
        """Return cached sentiment for *symbol*, or ``None`` if absent/expired."""
        key = f"{_SENTIMENT_PREFIX}:{symbol}"
        try:
            raw = self._redis.get(key)
            if raw is None:
                return None
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return json.loads(text)
        except Exception:
            logger.warning("get_sentiment failed for %s", symbol, exc_info=True)
            return None

    # ==================================================================
    # Position cache
    # ==================================================================

    def set_position(self, market: str, symbol: str, position: dict) -> None:
        """Cache the current position for *market*/*symbol*."""
        key = f"{_POSITION_PREFIX}:{market}:{symbol}"
        try:
            self._redis.set(
                key,
                json.dumps(position, default=str),
                ex=self._position_ttl if self._position_ttl > 0 else None,
            )
        except Exception:
            logger.warning("set_position failed for %s:%s", market, symbol,
                           exc_info=True)

    def get_position(self, market: str, symbol: str) -> dict | None:
        """Return the cached position for *market*/*symbol*, or ``None``."""
        key = f"{_POSITION_PREFIX}:{market}:{symbol}"
        try:
            raw = self._redis.get(key)
            if raw is None:
                return None
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return json.loads(text)
        except Exception:
            logger.warning("get_position failed for %s:%s", market, symbol,
                           exc_info=True)
            return None

    def get_all_positions(self) -> list[dict]:
        """Scan for all cached positions and return them as a list.

        .. warning:: Uses ``SCAN`` to iterate -- safe for production but
           may be slow when the keyspace is very large.
        """
        pattern = f"{_POSITION_PREFIX}:*"
        positions: list[dict] = []
        try:
            cursor: int = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=pattern, count=100)
                for key in keys:
                    try:
                        raw = self._redis.get(key)
                        if raw is None:
                            continue
                        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                        position = json.loads(text)

                        # Derive market/symbol from key if not present in payload
                        key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                        parts = key_str.split(":")
                        if len(parts) >= 3:
                            position.setdefault("market", parts[1])
                            position.setdefault("symbol", parts[2])

                        positions.append(position)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        logger.debug("Skipping unparseable position key: %s", key)
                if cursor == 0:
                    break
        except Exception:
            logger.warning("get_all_positions scan failed", exc_info=True)

        logger.debug("get_all_positions: found %d positions", len(positions))
        return positions

    # ==================================================================
    # Universe cache
    # ==================================================================

    def set_universe(self, tier: str, symbols: list[str]) -> None:
        """Replace the symbol set for a universe *tier*."""
        key = f"{_UNIVERSE_PREFIX}:{tier}"
        try:
            pipe = self._redis.pipeline()
            pipe.delete(key)
            if symbols:
                pipe.sadd(key, *symbols)
            if self._universe_ttl > 0:
                pipe.expire(key, self._universe_ttl)
            pipe.execute()
        except Exception:
            logger.warning("set_universe failed for tier %s", tier, exc_info=True)

    def get_universe(self, tier: str) -> list[str]:
        """Return the list of symbols in a universe *tier*."""
        key = f"{_UNIVERSE_PREFIX}:{tier}"
        try:
            members: set[bytes | str] = self._redis.smembers(key)
            result = []
            for m in members:
                result.append(m.decode("utf-8") if isinstance(m, bytes) else m)
            return sorted(result)
        except Exception:
            logger.warning("get_universe failed for tier %s", tier, exc_info=True)
            return []

    # ==================================================================
    # Config cache
    # ==================================================================

    def set_config(self, key: str, value: str) -> None:
        """Store a configuration value under ``config:{key}``."""
        redis_key = f"{_CONFIG_PREFIX}:{key}"
        try:
            self._redis.set(
                redis_key,
                value,
                ex=self._config_ttl if self._config_ttl > 0 else None,
            )
        except Exception:
            logger.warning("set_config failed for %s", key, exc_info=True)

    def get_config(self, key: str) -> str | None:
        """Retrieve a configuration value, or ``None`` if absent."""
        redis_key = f"{_CONFIG_PREFIX}:{key}"
        try:
            raw = self._redis.get(redis_key)
            if raw is None:
                return None
            return raw.decode("utf-8") if isinstance(raw, bytes) else raw
        except Exception:
            logger.warning("get_config failed for %s", key, exc_info=True)
            return None
