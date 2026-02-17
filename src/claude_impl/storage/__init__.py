"""Storage layer for the stock trading system.

Provides modules that write and read data across the four backing stores:

- **MongoDB**  -- news events (raw + enriched)
- **BigQuery** -- time-series price bars, analytics tables (via GCS batch load)
- **Redis**    -- real-time caches (prices, sentiment, positions, universe, config)
- **GCS**      -- batch-load buffer for BigQuery and long-term compressed archives

Each writer/manager degrades gracefully when its backing service is unavailable,
logging warnings and returning safe defaults rather than crashing.
"""

from __future__ import annotations

from .archiver import Archiver
from .cache_manager import CacheManager
from .news_writer import NewsWriter
from .price_writer import PriceWriter

__all__ = [
    "Archiver",
    "CacheManager",
    "NewsWriter",
    "PriceWriter",
]
