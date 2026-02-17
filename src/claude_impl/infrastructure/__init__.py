"""Infrastructure client wrappers for the stock trading system.

Provides unified, fault-tolerant access to external services:
- BigQuery (analytics / time-series storage)
- MongoDB  (news / event document storage)
- Redis    (real-time cache, with in-memory fallback)
- GCS      (archive / batch-load buffer)
- Telegram (monitoring & alerting)

Each client gracefully degrades when its backing library is missing or
the remote service is unreachable -- the system logs a warning and
returns safe defaults (empty lists, ``None``, etc.) instead of crashing.
"""

from __future__ import annotations

from .bigquery_client import BigQueryClient
from .gcs_client import GCSClient
from .mongodb_client import MongoDBClient
from .redis_client import RedisClient
from .telegram_client import TelegramNotifier

__all__ = [
    "BigQueryClient",
    "GCSClient",
    "MongoDBClient",
    "RedisClient",
    "TelegramNotifier",
]
