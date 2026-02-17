"""Model classes for the Stock Trading System.

Re-exports all model dataclasses for convenient access::

    from src.claude_impl.models import Signal, AlgorithmContext, Position
"""

from src.claude_impl.models.news import (
    EnrichedNewsEvent,
    RawNewsEvent,
    hash_event_id,
)
from src.claude_impl.models.position import (
    PortfolioState,
    Position,
)
from src.claude_impl.models.price import (
    PriceBar1d,
    PriceBar5m,
)
from src.claude_impl.models.signal import (
    AlgorithmContext,
    Signal,
    deserialize_context,
    serialize_context,
)
from src.claude_impl.models.trade import (
    SellRecommendation,
    TradeEntry,
)

__all__ = [
    # news
    "RawNewsEvent",
    "EnrichedNewsEvent",
    "hash_event_id",
    # price
    "PriceBar5m",
    "PriceBar1d",
    # signal
    "Signal",
    "AlgorithmContext",
    "serialize_context",
    "deserialize_context",
    # position
    "Position",
    "PortfolioState",
    # trade
    "TradeEntry",
    "SellRecommendation",
]
