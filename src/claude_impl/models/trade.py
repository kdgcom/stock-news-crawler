"""Trade ledger and sell recommendation models for the Stock Trading System.

Defines TradeEntry (individual buy/sell execution record) and
SellRecommendation (system-generated sell/reduce proposal) dataclasses
that map to the BigQuery tables trade_ledger and sell_recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class TradeEntry:
    """A single trade execution record in the trade ledger.

    Maps to BigQuery ``stock_trading.trade_ledger``.
    Records both broker-filled and manually-input trades.

    Attributes:
        trade_id: Unique identifier for this trade (UUID).
        user_id: User who owns this trade.
        account_id: Brokerage account identifier.
        symbol: Ticker symbol (e.g. "005930", "AAPL").
        market: Market identifier ("KR" or "US").
        side: Trade direction - "BUY" or "SELL".
        quantity: Number of shares traded (positive integer).
        price: Execution price per share.
        fee: Transaction fee (brokerage commission).
        tax: Transaction tax (e.g. securities transaction tax in KR).
        executed_at: Timestamp of trade execution.
        source: Origin of the trade record - "broker_fill" or "manual_input".
        order_id: Broker-assigned order ID, or None for manual entries.
    """

    trade_id: str
    user_id: str
    account_id: str
    symbol: str
    market: str
    side: Literal["BUY", "SELL"]
    quantity: int
    price: float
    fee: float
    tax: float
    executed_at: datetime
    source: str = "broker_fill"  # "broker_fill" | "manual_input"
    order_id: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.price < 0:
            raise ValueError(f"price must be non-negative, got {self.price}")
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {self.side}")
        if self.source not in ("broker_fill", "manual_input"):
            raise ValueError(
                f"source must be broker_fill or manual_input, got {self.source}"
            )

    @property
    def total_cost(self) -> float:
        """Total cost of this trade including fees and taxes."""
        return self.quantity * self.price + self.fee + self.tax

    @property
    def net_amount(self) -> float:
        """Net cash impact: negative for BUY (cash outflow), positive for SELL."""
        gross = self.quantity * self.price
        if self.side == "BUY":
            return -(gross + self.fee + self.tax)
        else:
            return gross - self.fee - self.tax

    def to_dict(self) -> dict:
        """Serialize to a dict suitable for BigQuery row insertion."""
        return {
            "trade_id": self.trade_id,
            "user_id": self.user_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "market": self.market,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "fee": self.fee,
            "tax": self.tax,
            "executed_at": self.executed_at.isoformat()
            if isinstance(self.executed_at, datetime)
            else self.executed_at,
            "source": self.source,
            "order_id": self.order_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TradeEntry:
        """Deserialize from a BigQuery row dict."""
        executed_at = data["executed_at"]
        return cls(
            trade_id=data["trade_id"],
            user_id=data["user_id"],
            account_id=data["account_id"],
            symbol=data["symbol"],
            market=data["market"],
            side=data["side"],
            quantity=int(data["quantity"]),
            price=float(data["price"]),
            fee=float(data.get("fee", 0.0)),
            tax=float(data.get("tax", 0.0)),
            executed_at=executed_at
            if isinstance(executed_at, datetime)
            else datetime.fromisoformat(executed_at),
            source=data.get("source", "broker_fill"),
            order_id=data.get("order_id"),
        )


@dataclass(slots=True)
class SellRecommendation:
    """A system-generated recommendation to sell or reduce a holding.

    Maps to BigQuery ``stock_trading.sell_recommendations``.
    Requires user confirmation before execution (by default).

    Attributes:
        recommendation_id: Unique identifier (UUID).
        ts_utc: Timestamp when the recommendation was generated.
        user_id: Target user for this recommendation.
        symbol: Ticker symbol of the held position.
        market: Market identifier ("KR" or "US").
        action: Recommended action - "SELL" (full), "REDUCE" (partial), or "HOLD".
        score: Conviction score from -1.0 to +1.0.
        confidence: Confidence in the recommendation (0.0 ~ 1.0).
        target_reduce_pct: For REDUCE action, the percentage to reduce
            (e.g. 0.5 for 50%). None for SELL (100%) or HOLD actions.
        reason_codes: Machine-readable list of reasons for the recommendation.
        evidence: Supporting evidence dict (news summaries, indicator values, etc.).
        requires_confirmation: Whether user must approve before execution.
    """

    recommendation_id: str
    ts_utc: datetime
    user_id: str
    symbol: str
    market: str
    action: Literal["SELL", "REDUCE", "HOLD"]
    score: float
    confidence: float
    target_reduce_pct: float | None = None
    reason_codes: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = True

    def __post_init__(self) -> None:
        if self.action not in ("SELL", "REDUCE", "HOLD"):
            raise ValueError(f"action must be SELL/REDUCE/HOLD, got {self.action}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0, 1], got {self.confidence}"
            )
        if self.action == "REDUCE" and self.target_reduce_pct is not None:
            if not 0.0 < self.target_reduce_pct < 1.0:
                raise ValueError(
                    f"target_reduce_pct must be in (0, 1) for REDUCE, "
                    f"got {self.target_reduce_pct}"
                )

    def to_dict(self) -> dict:
        """Serialize to a dict suitable for BigQuery row insertion."""
        return {
            "recommendation_id": self.recommendation_id,
            "ts_utc": self.ts_utc.isoformat()
            if isinstance(self.ts_utc, datetime)
            else self.ts_utc,
            "user_id": self.user_id,
            "symbol": self.symbol,
            "market": self.market,
            "action": self.action,
            "score": self.score,
            "confidence": self.confidence,
            "target_reduce_pct": self.target_reduce_pct,
            "reason_codes": self.reason_codes,
            "evidence": self.evidence,
            "requires_confirmation": self.requires_confirmation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SellRecommendation:
        """Deserialize from a BigQuery row dict."""
        ts = data["ts_utc"]
        return cls(
            recommendation_id=data["recommendation_id"],
            ts_utc=ts if isinstance(ts, datetime) else datetime.fromisoformat(ts),
            user_id=data["user_id"],
            symbol=data["symbol"],
            market=data["market"],
            action=data["action"],
            score=float(data["score"]),
            confidence=float(data["confidence"]),
            target_reduce_pct=data.get("target_reduce_pct"),
            reason_codes=data.get("reason_codes", []),
            evidence=data.get("evidence", {}),
            requires_confirmation=data.get("requires_confirmation", True),
        )
