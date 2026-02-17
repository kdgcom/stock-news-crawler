"""MongoDB (PyMongo) client wrapper with graceful fallback.

Configuration keys consumed from the *config* dict::

    mongodb.atlas_uri   -- MongoDB Atlas connection string
    mongodb.database    -- database name (default ``stock_news``)

If ``pymongo`` is not installed **or** the connection fails, every public
method logs a warning and returns a safe default (empty list, ``0``, or
``None``).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional import
# ---------------------------------------------------------------------------
try:
    import pymongo
    from pymongo.collection import Collection

    _HAS_PYMONGO = True
except ImportError:
    _HAS_PYMONGO = False
    logger.warning(
        "pymongo is not installed. "
        "MongoDBClient will return empty results for all operations."
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


class MongoDBClient:
    """Thin wrapper around :class:`pymongo.MongoClient`.

    All public methods are safe to call even when pymongo is missing or
    the connection is down -- they log a warning and return safe defaults.
    """

    def __init__(self, config: dict) -> None:
        self._atlas_uri: str = _nested_get(config, "mongodb.atlas_uri", "")
        self._database_name: str = _nested_get(config, "mongodb.database", "stock_news")
        self._client: Any | None = None
        self._db: Any | None = None

        if not _HAS_PYMONGO:
            logger.warning("MongoDBClient initialised without pymongo.")
            return

        if not self._atlas_uri:
            logger.warning(
                "MongoDBClient: mongodb.atlas_uri is empty. "
                "Connection will not be attempted."
            )
            return

        try:
            self._client = pymongo.MongoClient(
                self._atlas_uri,
                serverSelectionTimeoutMS=5_000,
                connectTimeoutMS=5_000,
                socketTimeoutMS=10_000,
                retryWrites=True,
                w="majority",
            )
            # Force a round-trip to verify connectivity.
            self._client.admin.command("ping")
            self._db = self._client[self._database_name]
            logger.info(
                "MongoDBClient connected to database=%s",
                self._database_name,
            )
        except Exception:
            logger.warning(
                "Failed to connect to MongoDB Atlas. "
                "All MongoDB operations will return empty results.",
                exc_info=True,
            )
            self._client = None
            self._db = None

    # -- helpers -------------------------------------------------------------

    @property
    def _available(self) -> bool:
        return self._db is not None

    # -- public API ----------------------------------------------------------

    def get_collection(self, name: str) -> Collection | None:
        """Return the raw :class:`~pymongo.collection.Collection` object.

        Returns ``None`` when the client is unavailable.
        """
        if not self._available:
            logger.warning(
                "get_collection(%s) skipped: MongoDB client not available.",
                name,
            )
            return None
        return self._db[name]

    def upsert(self, collection: str, filter_dict: dict, doc: dict) -> bool:
        """Upsert (update-or-insert) a single document.

        Returns ``True`` on success, ``False`` on failure or when the
        client is unavailable.
        """
        if not self._available:
            logger.warning(
                "upsert skipped for collection=%s: MongoDB client not available.",
                collection,
            )
            return False

        try:
            result = self._db[collection].update_one(
                filter_dict,
                {"$set": doc},
                upsert=True,
            )
            logger.debug(
                "upsert collection=%s matched=%d modified=%d upserted_id=%s",
                collection,
                result.matched_count,
                result.modified_count,
                result.upserted_id,
            )
            return True
        except Exception:
            logger.warning(
                "MongoDB upsert failed for collection=%s",
                collection,
                exc_info=True,
            )
            return False

    def find(
        self,
        collection: str,
        query: dict,
        sort: list | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Find documents matching *query*.

        Parameters
        ----------
        collection:
            Name of the MongoDB collection.
        query:
            MongoDB query filter dict.
        sort:
            Optional list of ``(field, direction)`` tuples, e.g.
            ``[("published_at_utc", -1)]``.
        limit:
            Maximum number of documents to return.  ``None`` means no
            limit.
        """
        if not self._available:
            logger.warning(
                "find skipped for collection=%s: MongoDB client not available.",
                collection,
            )
            return []

        try:
            cursor = self._db[collection].find(query)
            if sort is not None:
                cursor = cursor.sort(sort)
            if limit is not None:
                cursor = cursor.limit(limit)
            results = list(cursor)
            logger.debug(
                "find collection=%s query=%s returned %d docs",
                collection,
                query,
                len(results),
            )
            return results
        except Exception:
            logger.warning(
                "MongoDB find failed for collection=%s",
                collection,
                exc_info=True,
            )
            return []

    def insert_many(self, collection: str, docs: list[dict]) -> int:
        """Insert multiple documents into *collection*.

        Returns the number of documents successfully inserted, or ``0``
        on failure.
        """
        if not self._available:
            logger.warning(
                "insert_many skipped for collection=%s: MongoDB client not available.",
                collection,
            )
            return 0

        if not docs:
            return 0

        try:
            result = self._db[collection].insert_many(docs, ordered=False)
            count = len(result.inserted_ids)
            logger.debug(
                "insert_many collection=%s inserted %d docs",
                collection,
                count,
            )
            return count
        except Exception:
            logger.warning(
                "MongoDB insert_many failed for collection=%s",
                collection,
                exc_info=True,
            )
            return 0

    def count(self, collection: str, query: dict) -> int:
        """Return the number of documents matching *query*.

        Returns ``0`` when the client is unavailable.
        """
        if not self._available:
            logger.warning(
                "count skipped for collection=%s: MongoDB client not available.",
                collection,
            )
            return 0

        try:
            n = self._db[collection].count_documents(query)
            logger.debug(
                "count collection=%s query=%s => %d",
                collection,
                query,
                n,
            )
            return n
        except Exception:
            logger.warning(
                "MongoDB count failed for collection=%s",
                collection,
                exc_info=True,
            )
            return 0
