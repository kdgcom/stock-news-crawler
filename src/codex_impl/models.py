from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Decision = Literal["BUY", "SELL", "HOLD"]
RecommendationAction = Literal["SELL", "REDUCE", "HOLD"]
Side = Literal["BUY", "SELL"]


@dataclass
class NewsEvent:
    event_id: str
    symbol: str
    market: str
    sentiment_score: float
    novelty_score: float = 0.0
    reliability_score: float = 0.0
    event_type: str = "news"
    confidence: float = 0.5
    analyzed_at_utc: datetime = field(default_factory=datetime.utcnow)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class PriceBar:
    symbol: str
    market: str
    ts_event: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class AlgorithmContext:
    symbol: str
    market: str
    price_bars: list[PriceBar]
    daily_bars: list[PriceBar]
    news_events: list[NewsEvent]
    sentiment_current: float = 0.0
    sentiment_previous: float = 0.0
    position: dict[str, Any] | None = None
    portfolio: dict[str, Any] = field(default_factory=dict)
    regime: str = "normal"


@dataclass
class Signal:
    symbol: str
    market: str
    decision: Decision
    score: float
    confidence: float
    algorithm: str
    reason_codes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskCheckResult:
    passed: bool
    level: int
    blocker: str = "ALL_PASSED"
    checks: list[dict[str, str]] = field(default_factory=list)


@dataclass
class OrderRequest:
    user_id: str
    account_id: str
    symbol: str
    market: str
    side: Side
    quantity: int
    decision_id: str


@dataclass
class TradeLedgerEntry:
    trade_id: str
    user_id: str
    account_id: str
    symbol: str
    market: str
    side: Side
    quantity: int
    price: float
    fee: float = 0.0
    tax: float = 0.0
    source: str = "manual_input"
    order_id: str = ""
    executed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SellRecommendation:
    recommendation_id: str
    user_id: str
    account_id: str
    symbol: str
    market: str
    action: RecommendationAction
    score: float
    confidence: float
    target_reduce_pct: float
    reason_codes: list[str]
    evidence: dict[str, Any]
    requires_confirmation: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
