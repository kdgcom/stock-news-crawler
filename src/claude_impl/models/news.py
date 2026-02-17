"""News event models for the Stock Trading System.

Defines RawNewsEvent and EnrichedNewsEvent dataclasses that map to the
MongoDB collections raw_news_events and enriched_news_events respectively.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime


def hash_event_id(source: str, url: str, published_at: datetime) -> str:
    """Generate a deterministic event_id from source, url, and published_at.

    Uses SHA-256 to produce a hex digest that serves as the unique key
    across both raw_news_events and enriched_news_events collections.

    Args:
        source: The source name (e.g. "naver_finance", "alpaca_news").
        url: The full URL of the news article.
        published_at: The publication timestamp.

    Returns:
        A 64-character lowercase hex string (SHA-256 digest).
    """
    payload = f"{source}|{url}|{published_at.isoformat()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RawNewsEvent:
    """Represents a raw news event as ingested from a source.

    Maps to the MongoDB ``raw_news_events`` collection.
    The ``event_id`` is the unique index (hash of source + url + published_at).

    Indexes:
        - { event_id: 1 } (unique)
        - { market: 1, symbol: 1, published_at_utc: -1 }
        - TTL: { ingested_at_utc: 1 }, expireAfterSeconds: 90 days
    """

    event_id: str
    market: str
    symbol: str
    headline: str
    body: str
    language: str
    source_name: str
    source_type: str  # "news" | "disclosure" | "sns"
    published_at_utc: datetime
    ingested_at_utc: datetime
    url: str

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for MongoDB insertion."""
        return {
            "event_id": self.event_id,
            "market": self.market,
            "symbol": self.symbol,
            "headline": self.headline,
            "body": self.body,
            "language": self.language,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "published_at_utc": self.published_at_utc,
            "ingested_at_utc": self.ingested_at_utc,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RawNewsEvent:
        """Deserialize from a MongoDB document dict."""
        return cls(
            event_id=data["event_id"],
            market=data["market"],
            symbol=data["symbol"],
            headline=data["headline"],
            body=data["body"],
            language=data["language"],
            source_name=data["source_name"],
            source_type=data["source_type"],
            published_at_utc=data["published_at_utc"]
            if isinstance(data["published_at_utc"], datetime)
            else datetime.fromisoformat(data["published_at_utc"]),
            ingested_at_utc=data["ingested_at_utc"]
            if isinstance(data["ingested_at_utc"], datetime)
            else datetime.fromisoformat(data["ingested_at_utc"]),
            url=data["url"],
        )

    @classmethod
    def create(
        cls,
        *,
        market: str,
        symbol: str,
        headline: str,
        body: str,
        language: str,
        source_name: str,
        source_type: str,
        published_at_utc: datetime,
        ingested_at_utc: datetime,
        url: str,
    ) -> RawNewsEvent:
        """Factory that auto-generates the event_id from source, url, and published_at."""
        event_id = hash_event_id(source_name, url, published_at_utc)
        return cls(
            event_id=event_id,
            market=market,
            symbol=symbol,
            headline=headline,
            body=body,
            language=language,
            source_name=source_name,
            source_type=source_type,
            published_at_utc=published_at_utc,
            ingested_at_utc=ingested_at_utc,
            url=url,
        )


@dataclass(frozen=True, slots=True)
class EnrichedNewsEvent:
    """Represents an enriched (analyzed) news event.

    Maps to the MongoDB ``enriched_news_events`` collection.
    Shares the same ``event_id`` as the corresponding RawNewsEvent.

    Indexes:
        - { event_id: 1 } (unique)
        - { affected_symbols: 1, analyzed_at_utc: -1 }
        - No TTL (permanent retention)
    """

    event_id: str
    event_type: str  # e.g. "earnings", "m_and_a", "regulation"
    sentiment_score: float  # -1.0 ~ +1.0
    confidence: float  # 0.0 ~ 1.0
    impact_horizon: str  # "short_term" | "medium_term" | "long_term"
    novelty_score: float  # 0.0 ~ 1.0
    reliability_score: float  # 0.0 ~ 1.0
    cluster_id: str | None
    entities: list[dict] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    affected_symbols: list[str] = field(default_factory=list)
    summary: str = ""
    analyzed_by: str = ""  # e.g. "rule_v1", "llm_haiku_v1"
    analyzed_at_utc: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for MongoDB insertion."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "sentiment_score": self.sentiment_score,
            "confidence": self.confidence,
            "impact_horizon": self.impact_horizon,
            "novelty_score": self.novelty_score,
            "reliability_score": self.reliability_score,
            "cluster_id": self.cluster_id,
            "entities": self.entities,
            "topic_tags": self.topic_tags,
            "affected_symbols": self.affected_symbols,
            "summary": self.summary,
            "analyzed_by": self.analyzed_by,
            "analyzed_at_utc": self.analyzed_at_utc,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EnrichedNewsEvent:
        """Deserialize from a MongoDB document dict."""
        analyzed_at = data.get("analyzed_at_utc", datetime.utcnow())
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            sentiment_score=float(data["sentiment_score"]),
            confidence=float(data["confidence"]),
            impact_horizon=data["impact_horizon"],
            novelty_score=float(data["novelty_score"]),
            reliability_score=float(data["reliability_score"]),
            cluster_id=data.get("cluster_id"),
            entities=data.get("entities", []),
            topic_tags=data.get("topic_tags", []),
            affected_symbols=data.get("affected_symbols", []),
            summary=data.get("summary", ""),
            analyzed_by=data.get("analyzed_by", ""),
            analyzed_at_utc=analyzed_at
            if isinstance(analyzed_at, datetime)
            else datetime.fromisoformat(analyzed_at),
        )
