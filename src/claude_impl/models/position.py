"""Position and portfolio state models for the Stock Trading System.

Defines Position (individual holding) and PortfolioState (aggregate view)
dataclasses used for risk management, sell recommendation, and portfolio
context in algorithm evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Position:
    """Represents a single open position (holding) in the portfolio.

    Attributes:
        symbol: Ticker symbol (e.g. "005930", "AAPL").
        market: Market identifier ("KR" or "US").
        quantity: Number of shares held (positive integer).
        avg_cost: Volume-weighted average cost per share.
        current_price: Latest market price per share.
        peak_price: Highest price since position was opened (for trailing stop).
        opened_at: Timestamp when the position was first established.
        unrealized_pnl: Current unrealized profit/loss in currency units.
        unrealized_pnl_pct: Unrealized PnL as a percentage of cost basis.
        stop_loss_price: Fixed stop-loss price, or None if not set.
        trailing_stop: Trailing stop distance (absolute price), or None if not set.
    """

    symbol: str
    market: str
    quantity: int
    avg_cost: float
    current_price: float
    peak_price: float
    opened_at: datetime
    unrealized_pnl: float
    unrealized_pnl_pct: float
    stop_loss_price: float | None = None
    trailing_stop: float | None = None

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError(f"quantity must be non-negative, got {self.quantity}")
        if self.avg_cost < 0:
            raise ValueError(f"avg_cost must be non-negative, got {self.avg_cost}")

    @property
    def market_value(self) -> float:
        """Current market value of this position."""
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        """Total cost basis of this position."""
        return self.quantity * self.avg_cost

    @property
    def trailing_stop_price(self) -> float | None:
        """Effective trailing stop price based on peak_price and trailing_stop distance.

        Returns None if trailing_stop is not set.
        """
        if self.trailing_stop is None:
            return None
        return self.peak_price - self.trailing_stop

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for Redis or JSON storage."""
        return {
            "symbol": self.symbol,
            "market": self.market,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "peak_price": self.peak_price,
            "opened_at": self.opened_at.isoformat()
            if isinstance(self.opened_at, datetime)
            else self.opened_at,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "stop_loss_price": self.stop_loss_price,
            "trailing_stop": self.trailing_stop,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Position:
        """Deserialize from a dict (e.g. Redis hash or JSON)."""
        opened_at = data["opened_at"]
        return cls(
            symbol=data["symbol"],
            market=data["market"],
            quantity=int(data["quantity"]),
            avg_cost=float(data["avg_cost"]),
            current_price=float(data["current_price"]),
            peak_price=float(data["peak_price"]),
            opened_at=opened_at
            if isinstance(opened_at, datetime)
            else datetime.fromisoformat(opened_at),
            unrealized_pnl=float(data["unrealized_pnl"]),
            unrealized_pnl_pct=float(data["unrealized_pnl_pct"]),
            stop_loss_price=data.get("stop_loss_price"),
            trailing_stop=data.get("trailing_stop"),
        )


@dataclass(slots=True)
class PortfolioState:
    """Aggregate portfolio state used for risk management and algorithm context.

    Attributes:
        total_value: Total portfolio value (cash + positions market value).
        cash: Available cash balance.
        cash_pct: Cash as a percentage of total_value (0.0 ~ 1.0).
        positions: List of all open Position objects.
        position_count: Number of open positions.
        daily_pnl_pct: Today's realized + unrealized PnL as a percentage.
        weekly_pnl_pct: This week's cumulative PnL as a percentage.
        max_drawdown_pct: Maximum drawdown from peak portfolio value (negative).
    """

    total_value: float
    cash: float
    cash_pct: float
    positions: list[Position] = field(default_factory=list)
    position_count: int = 0
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0

    def __post_init__(self) -> None:
        if self.position_count == 0 and self.positions:
            self.position_count = len(self.positions)

    def get_position(self, symbol: str, market: str) -> Position | None:
        """Look up a position by symbol and market.

        Args:
            symbol: Ticker symbol.
            market: Market identifier ("KR" or "US").

        Returns:
            The matching Position, or None if not found.
        """
        for pos in self.positions:
            if pos.symbol == symbol and pos.market == market:
                return pos
        return None

    @property
    def total_unrealized_pnl(self) -> float:
        """Sum of unrealized PnL across all positions."""
        return sum(p.unrealized_pnl for p in self.positions)

    @property
    def total_market_value(self) -> float:
        """Sum of market values across all positions."""
        return sum(p.market_value for p in self.positions)

    def position_weight(self, symbol: str, market: str) -> float:
        """Calculate the portfolio weight of a specific position.

        Args:
            symbol: Ticker symbol.
            market: Market identifier.

        Returns:
            Weight as a fraction of total_value (0.0 ~ 1.0), or 0.0 if not found.
        """
        pos = self.get_position(symbol, market)
        if pos is None or self.total_value <= 0:
            return 0.0
        return pos.market_value / self.total_value

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "total_value": self.total_value,
            "cash": self.cash,
            "cash_pct": self.cash_pct,
            "positions": [p.to_dict() for p in self.positions],
            "position_count": self.position_count,
            "daily_pnl_pct": self.daily_pnl_pct,
            "weekly_pnl_pct": self.weekly_pnl_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PortfolioState:
        """Deserialize from a dict."""
        positions = [Position.from_dict(p) for p in data.get("positions", [])]
        return cls(
            total_value=float(data["total_value"]),
            cash=float(data["cash"]),
            cash_pct=float(data["cash_pct"]),
            positions=positions,
            position_count=int(data.get("position_count", len(positions))),
            daily_pnl_pct=float(data.get("daily_pnl_pct", 0.0)),
            weekly_pnl_pct=float(data.get("weekly_pnl_pct", 0.0)),
            max_drawdown_pct=float(data.get("max_drawdown_pct", 0.0)),
        )
