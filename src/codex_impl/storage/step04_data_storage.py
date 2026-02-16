from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from ..models import NewsEvent, SellRecommendation, TradeLedgerEntry


@dataclass
class InMemoryStorage:
    """04-data-storage.md in-memory replacement for BQ/Mongo/Redis."""

    raw_news_events: dict[str, NewsEvent] = field(default_factory=dict)
    enriched_news_events: dict[str, NewsEvent] = field(default_factory=dict)
    decision_logs: list[dict] = field(default_factory=list)
    trade_ledger: list[TradeLedgerEntry] = field(default_factory=list)
    sell_recommendations: list[SellRecommendation] = field(default_factory=list)

    def upsert_news(self, event: NewsEvent, enriched: bool = False) -> None:
        bucket = self.enriched_news_events if enriched else self.raw_news_events
        bucket[event.event_id] = event

    def append_decision_log(self, log: dict) -> None:
        self.decision_logs.append(log)

    def append_trade(self, trade: TradeLedgerEntry) -> None:
        self.trade_ledger.append(trade)

    def append_recommendation(self, recommendation: SellRecommendation) -> None:
        self.sell_recommendations.append(recommendation)

    def list_news(self, symbol: str, enriched: bool = True) -> list[NewsEvent]:
        bucket = self.enriched_news_events if enriched else self.raw_news_events
        return [e for e in bucket.values() if e.symbol == symbol]

    def current_holdings(self, user_id: str, account_id: str) -> dict[str, dict]:
        aggregates: dict[tuple[str, str], dict] = {}
        for trade in self.trade_ledger:
            if trade.user_id != user_id or trade.account_id != account_id:
                continue
            key = (trade.market, trade.symbol)
            row = aggregates.setdefault(
                key,
                {
                    "market": trade.market,
                    "symbol": trade.symbol,
                    "buy_qty": 0,
                    "sell_qty": 0,
                    "last_price": trade.price,
                    "updated_at": trade.executed_at,
                },
            )
            if trade.side == "BUY":
                row["buy_qty"] += trade.quantity
            else:
                row["sell_qty"] += trade.quantity
            row["last_price"] = trade.price
            row["updated_at"] = max(row["updated_at"], trade.executed_at)

        holdings: dict[str, dict] = {}
        for row in aggregates.values():
            net_qty = row["buy_qty"] - row["sell_qty"]
            if net_qty > 0:
                holdings[row["symbol"]] = {
                    "market": row["market"],
                    "symbol": row["symbol"],
                    "net_quantity": net_qty,
                    "last_price": row["last_price"],
                    "updated_at": row["updated_at"],
                }
        return holdings

    def portfolio_freshness_hours(self, user_id: str, account_id: str) -> float:
        candidates = [t.executed_at for t in self.trade_ledger if t.user_id == user_id and t.account_id == account_id]
        if not candidates:
            return 9999.0
        return (datetime.utcnow() - max(candidates)).total_seconds() / 3600.0


def holdings_only_symbols(storage: InMemoryStorage, user_id: str, account_id: str) -> set[str]:
    return set(storage.current_holdings(user_id=user_id, account_id=account_id).keys())
