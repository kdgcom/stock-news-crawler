"""Price bar models for the Stock Trading System.

Defines PriceBar5m and PriceBar1d dataclasses that map to the BigQuery
tables market_5m_bars and market_1d_bars respectively.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class PriceBar5m:
    """Five-minute OHLCV bar with derived fields.

    Maps to BigQuery ``stock_trading.market_5m_bars``.
    Partitioned by DATE(ts_event), clustered by (market, symbol).
    """

    ts_event: datetime
    symbol: str
    market: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float
    spread_pct: float | None = None
    # -- derived fields (computed from 1-min bars) --
    high_minute: int | None = None   # minute offset within the 5-min bar where high occurred
    low_minute: int | None = None    # minute offset within the 5-min bar where low occurred
    intra_stddev: float | None = None  # intra-bar standard deviation of 1-min closes
    volume_skew: float | None = None   # skewness of per-minute volume distribution
    bar_trend: int | None = None       # +1 bullish, -1 bearish, 0 doji

    def to_dict(self) -> dict:
        """Serialize to a dict suitable for BigQuery row insertion."""
        return {
            "ts_event": self.ts_event.isoformat()
            if isinstance(self.ts_event, datetime)
            else self.ts_event,
            "symbol": self.symbol,
            "market": self.market,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "vwap": self.vwap,
            "spread_pct": self.spread_pct,
            "high_minute": self.high_minute,
            "low_minute": self.low_minute,
            "intra_stddev": self.intra_stddev,
            "volume_skew": self.volume_skew,
            "bar_trend": self.bar_trend,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PriceBar5m:
        """Deserialize from a BigQuery row dict."""
        ts = data["ts_event"]
        return cls(
            ts_event=ts if isinstance(ts, datetime) else datetime.fromisoformat(ts),
            symbol=data["symbol"],
            market=data["market"],
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=int(data["volume"]),
            vwap=float(data["vwap"]),
            spread_pct=data.get("spread_pct"),
            high_minute=data.get("high_minute"),
            low_minute=data.get("low_minute"),
            intra_stddev=data.get("intra_stddev"),
            volume_skew=data.get("volume_skew"),
            bar_trend=data.get("bar_trend"),
        )


@dataclass(frozen=True, slots=True)
class PriceBar1d:
    """Daily OHLCV bar aggregated from 5-minute bars.

    Maps to BigQuery ``stock_trading.market_1d_bars``.
    Partitioned by trade_date, clustered by (market, symbol).
    """

    trade_date: date
    symbol: str
    market: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float

    def to_dict(self) -> dict:
        """Serialize to a dict suitable for BigQuery row insertion."""
        return {
            "trade_date": self.trade_date.isoformat()
            if isinstance(self.trade_date, date)
            else self.trade_date,
            "symbol": self.symbol,
            "market": self.market,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "vwap": self.vwap,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PriceBar1d:
        """Deserialize from a BigQuery row dict."""
        td = data["trade_date"]
        return cls(
            trade_date=td if isinstance(td, date) else date.fromisoformat(td),
            symbol=data["symbol"],
            market=data["market"],
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=int(data["volume"]),
            vwap=float(data["vwap"]),
        )
