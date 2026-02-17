"""Normaliser utilities for news events and price bars.

Provides two classes:
    * ``NewsNormalizer``  – converts heterogeneous raw news dicts to the
      ``raw_news_events`` MongoDB schema.
    * ``PriceNormalizer`` – aggregates 1-minute OHLCV bars into 5-minute
      bars with derived fields matching the ``market_5m_bars`` BigQuery
      schema.
"""

from __future__ import annotations

import hashlib
import statistics
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any


# ======================================================================
# Helpers
# ======================================================================

def hash_event_id(source: str, url: str, published_at: str | datetime) -> str:
    """Deterministic event ID from source, URL and publication time.

    Returns a SHA-256 hex digest (first 32 chars) to keep IDs compact
    while retaining practical uniqueness.
    """
    if isinstance(published_at, datetime):
        published_at = published_at.isoformat()

    payload = f"{source}|{url}|{published_at}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


# ======================================================================
# News normaliser
# ======================================================================

class NewsNormalizer:
    """Transform raw news data into the ``raw_news_events`` schema.

    Standard output fields::

        event_id, market, symbol, headline, body, language,
        source_name, source_type, published_at_utc, ingested_at_utc, url
    """

    def normalize(self, raw: dict[str, Any], source: str) -> dict[str, Any]:
        """Convert a single raw news dict to the canonical schema.

        Parameters
        ----------
        raw:
            Must contain at least ``url``, ``published_at``, ``title``
            (or ``headline``), and ``symbol``.
        source:
            Identifier for the data source (e.g. ``"naver_finance"``,
            ``"alpaca_news"``).
        """
        url: str = raw.get("url", "")
        published_at = raw.get("published_at") or raw.get("published_at_utc", "")
        headline: str = raw.get("headline") or raw.get("title", "")

        event_id = hash_event_id(source, url, published_at)

        # Coerce published_at to a datetime object if it is a string
        if isinstance(published_at, str) and published_at:
            try:
                published_at_dt = datetime.fromisoformat(published_at)
            except ValueError:
                published_at_dt = _utcnow()
        elif isinstance(published_at, datetime):
            published_at_dt = published_at
        else:
            published_at_dt = _utcnow()

        # Ensure timezone-aware
        if published_at_dt.tzinfo is None:
            published_at_dt = published_at_dt.replace(tzinfo=timezone.utc)

        return {
            "event_id": event_id,
            "market": raw.get("market", ""),
            "symbol": raw.get("symbol", ""),
            "headline": headline,
            "body": raw.get("body") or raw.get("content", ""),
            "language": raw.get("language", ""),
            "source_name": raw.get("source_name", source),
            "source_type": raw.get("source_type", "news"),
            "published_at_utc": published_at_dt,
            "ingested_at_utc": _utcnow(),
            "url": url,
        }

    def is_duplicate(
        self,
        a: dict[str, Any],
        b: dict[str, Any],
        threshold: float = 0.85,
    ) -> bool:
        """Check whether two news items are duplicates.

        Uses ``SequenceMatcher`` on the headline for a fast, dependency-free
        similarity ratio.  Articles whose headlines exceed *threshold*
        similarity are considered duplicates.
        """
        title_a: str = a.get("headline") or a.get("title", "")
        title_b: str = b.get("headline") or b.get("title", "")

        if not title_a or not title_b:
            return False

        ratio = SequenceMatcher(None, title_a, title_b).ratio()
        return ratio >= threshold


# ======================================================================
# Price normaliser
# ======================================================================

class PriceNormalizer:
    """Aggregate 1-minute bars into a single 5-minute bar.

    Derived fields (matching ``market_5m_bars`` BigQuery schema):

    * **vwap** – volume-weighted average price
    * **high_minute** – 0-based index (0..4) of the bar with the highest high
    * **low_minute** – 0-based index (0..4) of the bar with the lowest low
    * **intra_stddev** – sample standard deviation of the 1-min close prices
    * **volume_skew** – ``(last_2_volume - first_2_volume) / total_volume``
    * **bar_trend** – ``+1`` (up), ``-1`` (down), or ``0`` (flat)
    """

    def aggregate_1m_to_5m(
        self,
        bars_1m: list[dict[str, Any]],
        symbol: str,
        market: str,
    ) -> dict[str, Any]:
        """Aggregate a list of 1-minute bars into one 5-minute bar.

        Parameters
        ----------
        bars_1m:
            Ordered list of 1-minute OHLCV dicts.  Each dict must contain
            at least: ``timestamp`` (or ``ts_event``), ``open``, ``high``,
            ``low``, ``close``, ``volume``.
        symbol:
            Ticker / stock code.
        market:
            Market identifier (``"KR"`` or ``"US"``).

        Returns
        -------
        A single dict conforming to the ``market_5m_bars`` schema.
        """
        if not bars_1m:
            raise ValueError("bars_1m must not be empty")

        opens = [float(b["open"]) for b in bars_1m]
        highs = [float(b["high"]) for b in bars_1m]
        lows = [float(b["low"]) for b in bars_1m]
        closes = [float(b["close"]) for b in bars_1m]
        volumes = [int(b["volume"]) for b in bars_1m]

        total_volume = sum(volumes)

        # VWAP: volume-weighted average price (use close of each bar)
        if total_volume > 0:
            vwap = sum(c * v for c, v in zip(closes, volumes)) / total_volume
        else:
            vwap = closes[-1]

        # Derived indices
        high_minute = highs.index(max(highs))
        low_minute = lows.index(min(lows))

        # Intra-bar standard deviation of 1-min closes
        intra_stddev = statistics.pstdev(closes) if len(closes) >= 2 else 0.0

        # Volume skew: (last 2 bars volume - first 2 bars volume) / total
        n = len(volumes)
        if total_volume > 0 and n >= 4:
            first_2 = sum(volumes[:2])
            last_2 = sum(volumes[-2:])
            volume_skew = (last_2 - first_2) / total_volume
        elif total_volume > 0 and n >= 2:
            first_half = sum(volumes[: n // 2])
            last_half = sum(volumes[n // 2 :])
            volume_skew = (last_half - first_half) / total_volume
        else:
            volume_skew = 0.0

        # Bar trend direction
        if closes[-1] > opens[0]:
            bar_trend = 1
        elif closes[-1] < opens[0]:
            bar_trend = -1
        else:
            bar_trend = 0

        ts_event = bars_1m[0].get("timestamp") or bars_1m[0].get("ts_event")

        return {
            "ts_event": ts_event,
            "symbol": symbol,
            "market": market,
            "open": opens[0],
            "high": max(highs),
            "low": min(lows),
            "close": closes[-1],
            "volume": total_volume,
            "vwap": round(vwap, 4),
            "high_minute": high_minute,
            "low_minute": low_minute,
            "intra_stddev": round(intra_stddev, 6),
            "volume_skew": round(volume_skew, 6),
            "bar_trend": bar_trend,
        }
