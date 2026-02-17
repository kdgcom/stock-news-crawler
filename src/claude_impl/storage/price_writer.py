"""BigQuery writer for 5-minute price bars via GCS staging.

Pipeline per batch
------------------
1. Convert bars to JSONL text.
2. Upload to ``gs://<bucket>/price_data/{date}/{timestamp}.jsonl``.
3. Trigger a BigQuery load job from the GCS object.
4. Cache the latest bars in Redis for real-time consumers.

See ``md/plan_detail/04-data-storage.md`` for the ``market_5m_bars`` schema.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# BigQuery target
_BQ_DATASET = "stock_trading"
_BQ_TABLE = "market_5m_bars"

# Redis key helpers
_PRICE_CACHE_PREFIX = "price_cache"
_MAX_CACHED_BARS = 200
_BAR_TTL_SECONDS = 86_400  # 24 hours


class PriceWriter:
    """Write 5-minute price bars to BigQuery (via GCS) and cache in Redis.

    Parameters
    ----------
    gcs_client:
        A ``GCSClient`` exposing ``upload_blob(bucket, path, data, content_type)``
        and ``bucket_name`` attribute.
    bigquery_client:
        A ``BigQueryClient`` exposing ``load_from_gcs(uri, dataset, table, **kw)``
        or a ``client`` property returning a ``google.cloud.bigquery.Client``.
    redis_client:
        Optional ``RedisClient`` for caching.  When ``None`` caching is skipped.
    """

    def __init__(
        self,
        gcs_client: Any,
        bigquery_client: Any,
        redis_client: Any | None = None,
    ) -> None:
        self._gcs = gcs_client
        self._bq = bigquery_client
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_bars(self, bars: list[dict]) -> bool:
        """Persist a batch of 5-minute bars.

        Steps:
        1. Serialize to JSONL.
        2. Upload to GCS.
        3. Kick off a BigQuery load job.
        4. Cache latest bars in Redis.

        Returns ``True`` when all steps that could run succeeded.
        """
        if not bars:
            logger.debug("write_bars called with empty list -- nothing to do")
            return True

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        ts_str = now.strftime("%Y%m%dT%H%M%S")
        gcs_path = f"price_data/{date_str}/{ts_str}.jsonl"

        # 1. Convert to JSONL
        jsonl_content = self._to_jsonl(bars)
        if not jsonl_content:
            return False

        # 2. Upload to GCS
        gcs_uri = self._upload_to_gcs(gcs_path, jsonl_content)
        if gcs_uri is None:
            return False

        # 3. BigQuery load
        bq_ok = self._load_into_bigquery(gcs_uri)

        # 4. Cache in Redis (best-effort)
        self._cache_bars(bars)

        logger.info(
            "write_bars: %d bars -> %s (bq_load=%s)",
            len(bars), gcs_path, bq_ok,
        )
        return bq_ok

    def cache_bar(self, bar: dict) -> None:
        """Cache a single bar in Redis under ``price_cache:{symbol}``.

        The key stores a capped list of the most recent *MAX_CACHED_BARS* bars
        serialised as JSON strings.
        """
        if self._redis is None:
            return

        symbol = bar.get("symbol")
        if not symbol:
            logger.warning("cache_bar: bar missing 'symbol' field")
            return

        key = f"{_PRICE_CACHE_PREFIX}:{symbol}"

        try:
            self._redis.lpush(key, json.dumps(bar, default=str))
            self._redis.ltrim(key, 0, _MAX_CACHED_BARS - 1)
            self._redis.expire(key, _BAR_TTL_SECONDS)
            logger.debug("Cached bar for %s", symbol)
        except Exception:
            logger.warning("Failed to cache bar for %s", symbol, exc_info=True)

    def get_cached_bars(self, symbol: str, count: int = 200) -> list[dict]:
        """Retrieve up to *count* recent bars from the Redis cache.

        Returns newest-first order.  An empty list is returned when Redis is
        unavailable or the key does not exist.
        """
        if self._redis is None:
            logger.debug("get_cached_bars: no Redis client configured")
            return []

        key = f"{_PRICE_CACHE_PREFIX}:{symbol}"
        effective_count = min(count, _MAX_CACHED_BARS)

        try:
            raw_items: list[bytes | str] = self._redis.lrange(key, 0, effective_count - 1)
            bars: list[dict] = []
            for item in raw_items:
                try:
                    text = item.decode("utf-8") if isinstance(item, bytes) else item
                    bars.append(json.loads(text))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.debug("Skipping unparseable cached bar for %s", symbol)
            logger.debug("get_cached_bars(%s): returned %d bars", symbol, len(bars))
            return bars
        except Exception:
            logger.warning("Failed to read cached bars for %s", symbol, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_jsonl(bars: list[dict]) -> str:
        """Serialize a list of bar dicts to newline-delimited JSON."""
        try:
            lines: list[str] = []
            for bar in bars:
                lines.append(json.dumps(bar, default=str))
            return "\n".join(lines) + "\n"
        except (TypeError, ValueError) as exc:
            logger.error("JSONL serialization failed: %s", exc)
            return ""

    def _upload_to_gcs(self, path: str, content: str) -> str | None:
        """Upload JSONL content to GCS and return the ``gs://`` URI."""
        try:
            bucket_name = self._gcs.bucket_name
            data = io.BytesIO(content.encode("utf-8"))
            self._gcs.upload_blob(
                bucket_name,
                path,
                data,
                content_type="application/jsonl",
            )
            uri = f"gs://{bucket_name}/{path}"
            logger.debug("Uploaded %d bytes to %s", len(content), uri)
            return uri
        except Exception:
            logger.error("GCS upload failed for %s", path, exc_info=True)
            return None

    def _load_into_bigquery(self, gcs_uri: str) -> bool:
        """Trigger a BigQuery load job from the staged GCS object.

        Uses WRITE_APPEND with NEWLINE_DELIMITED_JSON format so new rows
        are appended to the partitioned ``market_5m_bars`` table.
        """
        try:
            from google.cloud import bigquery

            client: bigquery.Client = self._bq.client
            table_ref = f"{client.project}.{_BQ_DATASET}.{_BQ_TABLE}"

            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                # Schema auto-detect off -- table already exists with DDL schema
                autodetect=False,
            )

            load_job = client.load_table_from_uri(
                gcs_uri,
                table_ref,
                job_config=job_config,
            )
            load_job.result()  # block until complete

            logger.info(
                "BigQuery load job %s completed: %d rows loaded",
                load_job.job_id, load_job.output_rows or 0,
            )
            return True

        except ImportError:
            logger.warning(
                "google-cloud-bigquery not installed -- skipping BigQuery load"
            )
            return False
        except Exception:
            logger.error("BigQuery load from %s failed", gcs_uri, exc_info=True)
            return False

    def _cache_bars(self, bars: list[dict]) -> None:
        """Cache each bar in the batch via :meth:`cache_bar`."""
        for bar in bars:
            self.cache_bar(bar)
