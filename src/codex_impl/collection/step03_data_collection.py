from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable

from ..models import NewsEvent, PriceBar


class BaseCollector(ABC):
    @abstractmethod
    def collect(self, symbol: str, market: str) -> Iterable[dict]:
        raise NotImplementedError


class NewsCollector(BaseCollector):
    """03-data-collection.md minimal collector stub."""

    def collect(self, symbol: str, market: str) -> Iterable[dict]:
        now = datetime.utcnow()
        yield {
            "event_id": f"{market}:{symbol}:{int(now.timestamp())}",
            "symbol": symbol,
            "market": market,
            "sentiment_score": 0.1,
            "novelty_score": 0.5,
            "reliability_score": 0.8,
            "event_type": "news",
            "analyzed_at_utc": now,
        }

    def collect_news(self, symbol: str, market: str) -> list[NewsEvent]:
        return [NewsEvent(**item) for item in self.collect(symbol, market)]


class PriceCollector(BaseCollector):
    def collect(self, symbol: str, market: str) -> Iterable[dict]:
        now = datetime.utcnow()
        yield {
            "symbol": symbol,
            "market": market,
            "ts_event": now,
            "open": 100.0,
            "high": 101.0,
            "low": 99.5,
            "close": 100.5,
            "volume": 10000,
        }

    def collect_bars(self, symbol: str, market: str) -> list[PriceBar]:
        return [PriceBar(**item) for item in self.collect(symbol, market)]
