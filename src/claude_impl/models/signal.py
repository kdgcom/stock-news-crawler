"""Signal and algorithm context models for the Stock Trading System.

Defines the Signal dataclass (output of every algorithm) and the
AlgorithmContext dataclass (common input context for all algorithms).
Also provides serialize/deserialize helpers for passing context through
LangGraph state boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(slots=True)
class Signal:
    """A trading signal produced by an algorithm or ensemble.

    Attributes:
        symbol: Ticker symbol (e.g. "005930", "AAPL").
        market: Market identifier ("KR" or "US").
        decision: One of "BUY", "SELL", or "HOLD".
        score: Continuous score from -1.0 (strong sell) to +1.0 (strong buy).
        confidence: How confident the algorithm is in this signal (0.0 ~ 1.0).
        algorithm: Identifier of the algorithm that produced this signal.
        reason_codes: Machine-readable list of reasons (e.g. ["SMA_GOLDEN_CROSS"]).
        details: Algorithm-specific details (free-form dict).
    """

    symbol: str
    market: str
    decision: Literal["BUY", "SELL", "HOLD"]
    score: float  # -1.0 ~ +1.0
    confidence: float  # 0.0 ~ 1.0
    algorithm: str
    reason_codes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not -1.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [-1, 1], got {self.score}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if self.decision not in ("BUY", "SELL", "HOLD"):
            raise ValueError(f"decision must be BUY/SELL/HOLD, got {self.decision}")

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "symbol": self.symbol,
            "market": self.market,
            "decision": self.decision,
            "score": self.score,
            "confidence": self.confidence,
            "algorithm": self.algorithm,
            "reason_codes": self.reason_codes,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Signal:
        """Deserialize from a plain dict."""
        return cls(
            symbol=data["symbol"],
            market=data["market"],
            decision=data["decision"],
            score=float(data["score"]),
            confidence=float(data["confidence"]),
            algorithm=data["algorithm"],
            reason_codes=data.get("reason_codes", []),
            details=data.get("details", {}),
        )


@dataclass(slots=True)
class AlgorithmContext:
    """Common context passed to every algorithm's ``generate_signal`` method.

    Aggregates data from Redis (price cache, positions), BigQuery (daily bars),
    and MongoDB (enriched news) into a single object.

    Attributes:
        symbol: Ticker symbol.
        market: Market identifier.
        price_bars: Recent 5-minute bars (dicts) from Redis cache.
        daily_bars: Recent daily bars (dicts) from BigQuery.
        news_events: Recent enriched news events (dicts) from MongoDB.
        sentiment_current: Latest weighted sentiment score for the symbol.
        sentiment_previous: Sentiment score from the previous cycle.
        position: Current position dict from Redis, or None if no position.
        portfolio: Portfolio state dict (cash, total_value, positions, etc.).
        regime: Detected market regime string
            (trending_up|trending_down|sideways|volatile|low_volatility).
    """

    symbol: str
    market: str
    price_bars: list[dict] = field(default_factory=list)
    daily_bars: list[dict] = field(default_factory=list)
    news_events: list[dict] = field(default_factory=list)
    sentiment_current: float = 0.0
    sentiment_previous: float = 0.0
    position: dict | None = None
    portfolio: dict = field(default_factory=dict)
    regime: str = "sideways"

    def to_dict(self) -> dict:
        """Serialize to a plain dict (JSON-compatible)."""
        return {
            "symbol": self.symbol,
            "market": self.market,
            "price_bars": self.price_bars,
            "daily_bars": self.daily_bars,
            "news_events": self.news_events,
            "sentiment_current": self.sentiment_current,
            "sentiment_previous": self.sentiment_previous,
            "position": self.position,
            "portfolio": self.portfolio,
            "regime": self.regime,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AlgorithmContext:
        """Deserialize from a plain dict."""
        return cls(
            symbol=data["symbol"],
            market=data["market"],
            price_bars=data.get("price_bars", []),
            daily_bars=data.get("daily_bars", []),
            news_events=data.get("news_events", []),
            sentiment_current=float(data.get("sentiment_current", 0.0)),
            sentiment_previous=float(data.get("sentiment_previous", 0.0)),
            position=data.get("position"),
            portfolio=data.get("portfolio", {}),
            regime=data.get("regime", "sideways"),
        )


def serialize_context(ctx: AlgorithmContext) -> dict:
    """Serialize an AlgorithmContext for embedding in LangGraph state.

    Converts the context to a JSON-serializable dict so it can be stored
    in the graph state and passed between nodes.

    Args:
        ctx: The AlgorithmContext to serialize.

    Returns:
        A plain dict with all datetime objects converted to ISO strings.
    """
    data = ctx.to_dict()
    return _make_json_safe(data)


def deserialize_context(data: dict) -> AlgorithmContext:
    """Deserialize an AlgorithmContext from LangGraph state.

    Args:
        data: The serialized dict (from serialize_context or a JSON payload).

    Returns:
        A fully reconstituted AlgorithmContext instance.
    """
    return AlgorithmContext.from_dict(data)


def _make_json_safe(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable types to strings.

    Handles datetime objects and other common types that appear in
    price bars and news events.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(item) for item in obj]
    if isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    # Fallback: convert to string representation
    return str(obj)
