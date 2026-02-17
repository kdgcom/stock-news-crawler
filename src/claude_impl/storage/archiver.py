"""Archive manager for aging-out old data from hot stores.

Responsibilities
----------------
* Compress and upload old raw news events from MongoDB to GCS as ``.jsonl.gz``.
* Mark archived documents so they are not re-processed.
* Generate SQL for deleting old 5-minute bars from BigQuery.
* Report archive vs. active document counts.

See ``md/plan_detail/04-data-storage.md`` -- *Archive Process* and
*Retention Policy* sections.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# GCS archive path template
_NEWS_ARCHIVE_PATH = "news_archive/{year_month}.jsonl.gz"

# BigQuery identifiers
_BQ_DATASET = "stock_trading"
_BQ_5M_TABLE = "market_5m_bars"

# Batch size for MongoDB reads during archival
_ARCHIVE_BATCH_SIZE = 500


class Archiver:
    """Manages lifecycle archival and cleanup for the trading system's data.

    Parameters
    ----------
    gcs_client:
        A ``GCSClient`` exposing ``upload_blob(bucket, path, data, content_type)``
        and a ``bucket_name`` attribute.
    mongodb_client:
        A ``MongoDBClient`` exposing a ``db`` property that returns a
        ``pymongo.database.Database``.
    config:
        Optional overrides.  Recognised keys:

        * ``archive_batch_size`` -- documents per MongoDB cursor batch
          (default 500).
        * ``gcs_bucket`` -- override for the archive bucket name.  When
          omitted, ``gcs_client.bucket_name`` is used.
    """

    def __init__(
        self,
        gcs_client: Any,
        mongodb_client: Any,
        config: dict | None = None,
    ) -> None:
        self._gcs = gcs_client
        self._mongo = mongodb_client
        self._db = mongodb_client.db
        cfg = config or {}

        self._batch_size: int = cfg.get("archive_batch_size", _ARCHIVE_BATCH_SIZE)
        self._bucket: str = cfg.get("gcs_bucket", getattr(gcs_client, "bucket_name", ""))

    # ------------------------------------------------------------------
    # News archival
    # ------------------------------------------------------------------

    def archive_old_news(self, cutoff_days: int = 90) -> dict[str, int]:
        """Compress raw news older than *cutoff_days* and upload to GCS.

        Steps
        -----
        1. Query ``raw_news_events`` for documents with
           ``ingested_at_utc < cutoff`` **and** ``archived != True``.
        2. Serialize matching documents as JSONL, gzip-compress, and upload
           to GCS under ``news_archive/{YYYYMM}.jsonl.gz``.
        3. Set ``{"archived": True}`` on the processed documents so they
           will not be re-archived (MongoDB TTL index handles actual deletion).

        Returns a summary dict with keys ``archived_count`` and
        ``gcs_path``.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
        collection = self._db["raw_news_events"]

        query = {
            "ingested_at_utc": {"$lt": cutoff},
            "archived": {"$ne": True},
        }

        try:
            cursor = collection.find(query).batch_size(self._batch_size)
            documents: list[dict] = []
            event_ids: list[str] = []

            for doc in cursor:
                # Remove MongoDB ObjectId for JSON serialization
                doc.pop("_id", None)
                documents.append(doc)
                eid = doc.get("event_id")
                if eid:
                    event_ids.append(eid)

            if not documents:
                logger.info("archive_old_news: no documents older than %d days", cutoff_days)
                return {"archived_count": 0, "gcs_path": ""}

            # Build compressed JSONL
            year_month = cutoff.strftime("%Y%m")
            gcs_path = _NEWS_ARCHIVE_PATH.format(year_month=year_month)
            compressed = self._compress_jsonl(documents)

            # Upload to GCS
            self._gcs.upload_blob(
                self._bucket,
                gcs_path,
                io.BytesIO(compressed),
                content_type="application/gzip",
            )
            logger.info(
                "Uploaded %d documents (%d bytes compressed) to gs://%s/%s",
                len(documents), len(compressed), self._bucket, gcs_path,
            )

            # Mark as archived in MongoDB
            if event_ids:
                result = collection.update_many(
                    {"event_id": {"$in": event_ids}},
                    {"$set": {"archived": True, "archived_at_utc": datetime.now(timezone.utc)}},
                )
                logger.info(
                    "Marked %d documents as archived in MongoDB",
                    result.modified_count,
                )

            return {
                "archived_count": len(documents),
                "gcs_path": f"gs://{self._bucket}/{gcs_path}",
            }

        except Exception:
            logger.error("archive_old_news failed", exc_info=True)
            return {"archived_count": 0, "gcs_path": "", "error": True}

    # ------------------------------------------------------------------
    # BigQuery cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def cleanup_old_price_bars(months: int = 12) -> str:
        """Generate a BigQuery SQL statement to delete 5-min bars older than *months*.

        .. note::
           This method **does not execute** the SQL.  It returns the statement
           string so that an operator can review it before running it via the
           BigQuery console or a separate execution path.

        Returns
        -------
        str
            A ``DELETE`` statement targeting partitions older than the cutoff.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
        cutoff_str = cutoff.strftime("%Y-%m-%d")

        sql = (
            f"-- Auto-generated cleanup SQL for 5-minute bars\n"
            f"-- Deletes partitions older than {months} months (cutoff: {cutoff_str})\n"
            f"-- Review carefully before executing.\n"
            f"\n"
            f"DELETE FROM `{_BQ_DATASET}.{_BQ_5M_TABLE}`\n"
            f"WHERE DATE(ts_event) < '{cutoff_str}';"
        )

        logger.info(
            "Generated cleanup SQL for %s (cutoff=%s)",
            _BQ_5M_TABLE, cutoff_str,
        )
        return sql

    # ------------------------------------------------------------------
    # Archive statistics
    # ------------------------------------------------------------------

    def get_archive_stats(self) -> dict:
        """Return counts of active vs. archived documents across collections.

        Returns a dict with structure::

            {
                "raw_news_events": {
                    "total": <int>,
                    "active": <int>,
                    "archived": <int>,
                },
                "enriched_news_events": {
                    "total": <int>,
                },
            }
        """
        stats: dict[str, dict[str, int]] = {}

        try:
            raw = self._db["raw_news_events"]
            total_raw = raw.count_documents({})
            archived_raw = raw.count_documents({"archived": True})
            active_raw = total_raw - archived_raw

            stats["raw_news_events"] = {
                "total": total_raw,
                "active": active_raw,
                "archived": archived_raw,
            }
        except Exception:
            logger.warning("Failed to count raw_news_events", exc_info=True)
            stats["raw_news_events"] = {"total": 0, "active": 0, "archived": 0}

        try:
            enriched = self._db["enriched_news_events"]
            total_enriched = enriched.count_documents({})

            stats["enriched_news_events"] = {
                "total": total_enriched,
            }
        except Exception:
            logger.warning("Failed to count enriched_news_events", exc_info=True)
            stats["enriched_news_events"] = {"total": 0}

        logger.info("Archive stats: %s", stats)
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compress_jsonl(documents: list[dict]) -> bytes:
        """Serialize *documents* as gzip-compressed JSONL.

        Returns the raw compressed bytes suitable for uploading to GCS.
        """
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            for doc in documents:
                line = json.dumps(doc, default=str, ensure_ascii=False) + "\n"
                gz.write(line.encode("utf-8"))
        return buf.getvalue()
