"""US market price collector using yfinance.

Fetches 1-minute or 5-minute bars via ``yfinance.download()`` and
computes derived fields for the ``market_5m_bars`` BigQuery schema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import yfinance as yf

from .base_collector import BaseCollector
from .normalizer import PriceNormalizer

logger = logging.getLogger(__name__)


class USPriceCollector(BaseCollector):
    """Collect 5-minute price bars for US stocks via yfinance.

    The collector:
    1. Downloads recent 1-minute bars (last 1 day) for each symbol.
    2. Groups them into 5-minute windows.
    3. Aggregates each window into a 5-minute bar with derived fields.

    Config keys::

        symbols:
          - "AAPL"
          - "TSLA"
          - "NVDA"
        interval: "1m"        # "1m" or "5m"
        period: "1d"          # yfinance period parameter
    """

    SOURCE_NAME = "yfinance"

    def __init__(
        self,
        config: dict[str, Any],
        symbols: list[str],
    ) -> None:
        self.config = config
        self.symbols = symbols
        self.interval: str = config.get("interval", "1m")
        self.period: str = config.get("period", "1d")
        self._normalizer = PriceNormalizer()

    # ------------------------------------------------------------------
    # BaseCollector hooks
    # ------------------------------------------------------------------

    def fetch(self) -> list[dict[str, Any]]:
        """Download bars and aggregate to 5-minute level."""
        all_bars: list[dict[str, Any]] = []

        for symbol in self.symbols:
            try:
                bars_1m = self._download_bars(symbol)
            except Exception as exc:
                logger.warning(
                    "USPriceCollector: failed to download %s: %s", symbol, exc
                )
                continue

            if not bars_1m:
                logger.info(
                    "USPriceCollector: no bars returned for %s.", symbol
                )
                continue

            # If the raw interval is already 5m we skip grouping
            if self.interval == "5m":
                for bar in bars_1m:
                    bar["symbol"] = symbol
                    bar["market"] = "US"
                all_bars.extend(bars_1m)
            else:
                # Group 1-min bars into 5-min windows and aggregate
                grouped = self._group_into_windows(bars_1m, window_size=5)
                for window in grouped:
                    bar_5m = self._normalizer.aggregate_1m_to_5m(
                        window, symbol=symbol, market="US"
                    )
                    all_bars.append(bar_5m)

        logger.info(
            "USPriceCollector.fetch: produced %d 5-min bars for %d symbols.",
            len(all_bars),
            len(self.symbols),
        )
        return all_bars

    def normalize(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply final validation to already-aggregated bars."""
        normalised: list[dict[str, Any]] = []
        for bar in raw:
            bar.setdefault("spread_pct", None)
            normalised.append(bar)
        return normalised

    def store(self, normalised: list[dict[str, Any]]) -> None:
        """Persist 5-minute bars."""
        logger.info(
            "USPriceCollector.store: %d bars ready for persistence.",
            len(normalised),
        )
        # TODO: write JSONL to GCS -> BigQuery batch load
        # TODO: cache latest bars in Redis

    # ------------------------------------------------------------------
    # yfinance helpers
    # ------------------------------------------------------------------

    def _download_bars(self, symbol: str) -> list[dict[str, Any]]:
        """Download OHLCV bars for a single symbol via yfinance.

        Returns a list of dicts sorted chronologically with keys:
        ``timestamp``, ``open``, ``high``, ``low``, ``close``, ``volume``.
        """
        df = yf.download(
            tickers=symbol,
            interval=self.interval,
            period=self.period,
            progress=False,
            auto_adjust=True,
        )

        if df is None or df.empty:
            return []

        bars: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            ts = idx
            # Convert pandas Timestamp to ISO string
            if hasattr(ts, "isoformat"):
                ts_str = ts.isoformat()
            else:
                ts_str = str(ts)

            bars.append(
                {
                    "timestamp": ts_str,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                }
            )

        return bars

    @staticmethod
    def _group_into_windows(
        bars: list[dict[str, Any]],
        window_size: int = 5,
    ) -> list[list[dict[str, Any]]]:
        """Split a flat list of bars into fixed-size windows.

        Incomplete trailing windows (fewer than *window_size* bars) are
        included so that no data is silently dropped.
        """
        windows: list[list[dict[str, Any]]] = []
        for i in range(0, len(bars), window_size):
            window = bars[i : i + window_size]
            if window:
                windows.append(window)
        return windows
