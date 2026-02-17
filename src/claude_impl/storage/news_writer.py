"""MongoDB writer for raw and enriched news events.

Responsibilities
----------------
* Upsert individual events (idempotent by ``event_id``).
* Batch-insert raw events, silently skipping duplicates.
* Query recent enriched news for a symbol/market.
* Return event counts for rate-limiting or de-duplication checks.

Collections
-----------
* ``raw_news_events``      -- ingested articles / disclosures / SNS posts
* ``enriched_news_events`` -- sentiment-scored, entity-linked, summarised

See ``md/plan_detail/04-data-storage.md`` for full schema details.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

logger = logging.getLogger(__name__)


class NewsWriter:
    """Read/write interface for news event collections in MongoDB.

    Parameters
    ----------
    mongodb_client:
        A ``MongoDBClient`` (or any object exposing a ``db`` property that
        returns a ``pymongo.database.Database``).
    redis_client:
        Optional ``RedisClient`` for cache invalidation on writes.  When
        ``None`` caching is simply skipped.
    """

    # MongoDB collection names
    RAW_COLLECTION = "raw_news_events"
    ENRICHED_COLLECTION = "enriched_news_events"

    def __init__(self, mongodb_client: Any, redis_client: Any | None = None) -> None:
        self._mongo = mongodb_client
        self._redis = redis_client
        self._db = mongodb_client.db

        self._raw = self._db[self.RAW_COLLECTION]
        self._enriched = self._db[self.ENRICHED_COLLECTION]

        self._ensure_indexes()

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _ensure_indexes(self) -> None:
        """Create indexes idempotently on first use."""
        try:
            # raw_news_events indexes
            self._raw.create_index("event_id", unique=True, background=True)
            self._raw.create_index(
                [("market", 1), ("symbol", 1), ("published_at_utc", -1)],
                background=True,
            )

            # enriched_news_events indexes
            self._enriched.create_index("event_id", unique=True, background=True)
            self._enriched.create_index(
                [("affected_symbols", 1), ("analyzed_at_utc", -1)],
                background=True,
            )

            logger.info("NewsWriter indexes ensured for %s and %s",
                        self.RAW_COLLECTION, self.ENRICHED_COLLECTION)
        except Exception:
            logger.warning("Failed to ensure indexes -- will retry on next restart",
                           exc_info=True)

    # ------------------------------------------------------------------
    # Single-document writes
    # ------------------------------------------------------------------

    def save_raw(self, event: dict) -> bool:
        """Upsert a single raw news event (idempotent by *event_id*).

        Returns ``True`` when the document was inserted or modified.
        """
        event_id = event.get("event_id")
        if not event_id:
            logger.error("save_raw called with event missing 'event_id'")
            return False

        try:
            # Set ingested_at_utc only on first insert
            update_doc: dict[str, Any] = {
                "$set": event,
                "$setOnInsert": {
                    "ingested_at_utc": datetime.now(timezone.utc),
                },
            }
            result = self._raw.update_one(
                {"event_id": event_id},
                update_doc,
                upsert=True,
            )
            modified = result.upserted_id is not None or result.modified_count > 0
            if modified:
                logger.debug("Saved raw event %s (upserted=%s)", event_id,
                             result.upserted_id is not None)
            return modified
        except Exception:
            logger.error("Failed to save raw event %s", event_id, exc_info=True)
            return False

    def save_enriched(self, event: dict) -> bool:
        """Upsert a single enriched news event (idempotent by *event_id*).

        Returns ``True`` when the document was inserted or modified.
        """
        event_id = event.get("event_id")
        if not event_id:
            logger.error("save_enriched called with event missing 'event_id'")
            return False

        try:
            update_doc: dict[str, Any] = {
                "$set": event,
                "$setOnInsert": {
                    "analyzed_at_utc": datetime.now(timezone.utc),
                },
            }
            result = self._enriched.update_one(
                {"event_id": event_id},
                update_doc,
                upsert=True,
            )
            modified = result.upserted_id is not None or result.modified_count > 0
            if modified:
                logger.debug("Saved enriched event %s", event_id)
                self._invalidate_sentiment_cache(event)
            return modified
        except Exception:
            logger.error("Failed to save enriched event %s", event_id, exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Batch writes
    # ------------------------------------------------------------------

    def save_batch_raw(self, events: list[dict]) -> int:
        """Batch-insert raw events, skipping duplicates via ``ordered=False``.

        Returns the number of successfully inserted documents.
        """
        if not events:
            return 0

        now = datetime.now(timezone.utc)
        operations: list[UpdateOne] = []
        for event in events:
            event_id = event.get("event_id")
            if not event_id:
                logger.warning("Skipping event without event_id in batch")
                continue
            operations.append(
                UpdateOne(
                    {"event_id": event_id},
                    {
                        "$set": event,
                        "$setOnInsert": {"ingested_at_utc": now},
                    },
                    upsert=True,
                )
            )

        if not operations:
            return 0

        try:
            result = self._raw.bulk_write(operations, ordered=False)
            inserted = result.upserted_count
            modified = result.modified_count
            logger.info(
                "Batch raw: %d events submitted, %d inserted, %d modified",
                len(operations), inserted, modified,
            )
            return inserted + modified
        except BulkWriteError as exc:
            # Some writes may have succeeded despite the error
            write_errors = exc.details.get("writeErrors", [])
            succeeded = len(operations) - len(write_errors)
            logger.warning(
                "Batch raw partial success: %d/%d succeeded (%d duplicate-key skips)",
                succeeded, len(operations), len(write_errors),
            )
            return max(succeeded, 0)
        except Exception:
            logger.error("Batch raw insert failed", exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_recent_news(
        self,
        symbol: str,
        market: str,
        hours: int = 12,
    ) -> list[dict]:
        """Return enriched news for *symbol* in *market* from the last *hours*.

        Results are ordered by ``analyzed_at_utc`` descending (newest first).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        try:
            cursor = self._enriched.find(
                {
                    "affected_symbols": symbol,
                    "market": market,
                    "analyzed_at_utc": {"$gte": cutoff},
                },
                {"_id": 0},
            ).sort("analyzed_at_utc", -1)

            results = list(cursor)
            logger.debug(
                "get_recent_news(%s, %s, %dh): %d results",
                symbol, market, hours, len(results),
            )
            return results
        except Exception:
            logger.error("Failed to query recent news for %s/%s",
                         symbol, market, exc_info=True)
            return []

    def get_news_count(self, symbol: str, days: int = 1) -> int:
        """Return the number of enriched news events for *symbol* in the last *days*."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        try:
            count = self._enriched.count_documents(
                {
                    "affected_symbols": symbol,
                    "analyzed_at_utc": {"$gte": cutoff},
                },
            )
            logger.debug("get_news_count(%s, %dd): %d", symbol, days, count)
            return count
        except Exception:
            logger.error("Failed to count news for %s", symbol, exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _invalidate_sentiment_cache(self, event: dict) -> None:
        """Invalidate cached sentiment scores for symbols affected by *event*.

        Best-effort -- failures are logged but do not propagate.
        """
        if self._redis is None:
            return

        symbols = event.get("affected_symbols", [])
        for sym in symbols:
            try:
                key = f"sentiment:{sym}"
                self._redis.delete(key)
                logger.debug("Invalidated sentiment cache for %s", sym)
            except Exception:
                logger.debug("Could not invalidate cache key sentiment:%s", sym)
