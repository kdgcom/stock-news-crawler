"""Redis client wrapper with in-memory fallback.

Configuration keys consumed from the *config* dict::

    redis.host      -- Redis server hostname  (default ``localhost``)
    redis.port      -- Redis server port      (default ``6379``)
    redis.password  -- optional authentication password

If ``redis`` (redis-py) is not installed **or** the connection fails, an
in-memory :class:`dict` is used as a best-effort local cache.  TTL
semantics are **not** honoured in the fallback implementation -- entries
persist until the process exits or they are explicitly deleted.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional import
# ---------------------------------------------------------------------------
try:
    import redis as _redis_lib

    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False
    logger.warning(
        "redis-py is not installed. "
        "RedisClient will use an in-memory dict as a fallback cache."
    )


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


class _InMemoryStore:
    """Minimal dict-backed store that mimics the subset of Redis
    operations used by :class:`RedisClient`.

    TTL entries are tracked and lazily evicted on access.
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}  # key -> epoch timestamp

    def _evict_if_expired(self, key: str) -> None:
        expire_at = self._expiry.get(key)
        if expire_at is not None and time.monotonic() >= expire_at:
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    def get(self, key: str) -> str | None:
        self._evict_if_expired(key)
        return self._data.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._data[key] = value
        if ttl is not None:
            self._expiry[key] = time.monotonic() + ttl
        else:
            self._expiry.pop(key, None)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._expiry.pop(key, None)

    def keys(self, pattern: str) -> list[str]:
        """Simple glob-style pattern matching (supports ``*`` only)."""
        import fnmatch

        # Lazily evict all expired keys before listing.
        now = time.monotonic()
        expired = [k for k, exp in self._expiry.items() if now >= exp]
        for k in expired:
            self._data.pop(k, None)
            self._expiry.pop(k, None)

        return [k for k in self._data if fnmatch.fnmatch(k, pattern)]


class RedisClient:
    """Thin wrapper around ``redis.Redis`` with automatic in-memory
    fallback.

    All public methods are safe to call regardless of whether the Redis
    server is reachable.
    """

    def __init__(self, config: dict) -> None:
        self._host: str = _nested_get(config, "redis.host", "localhost")
        self._port: int = int(_nested_get(config, "redis.port", 6379))
        self._password: str | None = _nested_get(config, "redis.password") or None
        self._redis: Any | None = None
        self._fallback: _InMemoryStore | None = None

        if not _HAS_REDIS:
            logger.warning(
                "RedisClient: redis-py unavailable, using in-memory fallback."
            )
            self._fallback = _InMemoryStore()
            return

        try:
            self._redis = _redis_lib.Redis(
                host=self._host,
                port=self._port,
                password=self._password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            # Force a round-trip to verify connectivity.
            self._redis.ping()
            logger.info(
                "RedisClient connected to %s:%s",
                self._host,
                self._port,
            )
        except Exception:
            logger.warning(
                "Failed to connect to Redis at %s:%s. "
                "Using in-memory fallback.",
                self._host,
                self._port,
                exc_info=True,
            )
            self._redis = None
            self._fallback = _InMemoryStore()

    # -- helpers -------------------------------------------------------------

    @property
    def _using_redis(self) -> bool:
        return self._redis is not None

    def _ensure_fallback(self) -> _InMemoryStore:
        if self._fallback is None:
            self._fallback = _InMemoryStore()
        return self._fallback

    # -- public API ----------------------------------------------------------

    def get(self, key: str) -> str | None:
        """Get the string value for *key*, or ``None`` if missing."""
        if self._using_redis:
            try:
                return self._redis.get(key)
            except Exception:
                logger.warning("Redis GET failed for key=%s, falling back.", key, exc_info=True)
                return self._ensure_fallback().get(key)
        return self._ensure_fallback().get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        """Set *key* to *value* with an optional TTL in seconds."""
        if self._using_redis:
            try:
                if ttl is not None:
                    self._redis.setex(key, ttl, value)
                else:
                    self._redis.set(key, value)
                return
            except Exception:
                logger.warning("Redis SET failed for key=%s, falling back.", key, exc_info=True)
        self._ensure_fallback().set(key, value, ttl)

    def get_json(self, key: str) -> dict | None:
        """Get and JSON-deserialise the value for *key*.

        Returns ``None`` if the key does not exist or the value is not
        valid JSON.
        """
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to decode JSON for key=%s", key)
            return None

    def set_json(self, key: str, value: dict, ttl: int | None = None) -> None:
        """JSON-serialise *value* and store it under *key*."""
        try:
            serialised = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            logger.warning("Failed to serialise value to JSON for key=%s", key)
            return
        self.set(key, serialised, ttl)

    def delete(self, key: str) -> None:
        """Delete *key*."""
        if self._using_redis:
            try:
                self._redis.delete(key)
                return
            except Exception:
                logger.warning("Redis DELETE failed for key=%s, falling back.", key, exc_info=True)
        self._ensure_fallback().delete(key)

    def keys(self, pattern: str) -> list[str]:
        """Return all keys matching the glob-style *pattern*.

        .. warning::
            On a production Redis server with many keys, prefer
            ``SCAN`` over ``KEYS``.  This wrapper uses ``KEYS`` for
            simplicity; swap to :pymethod:`redis.Redis.scan_iter` if the
            key space grows large.
        """
        if self._using_redis:
            try:
                return self._redis.keys(pattern)
            except Exception:
                logger.warning(
                    "Redis KEYS failed for pattern=%s, falling back.",
                    pattern,
                    exc_info=True,
                )
        return self._ensure_fallback().keys(pattern)
