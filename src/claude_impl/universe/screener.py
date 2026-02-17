"""Tier 3 daily screening for Tier 2 candidate discovery.

After each market close, the entire universe of daily bars is scanned
against a set of quantitative filters.  Symbols that pass any filter
are returned as Tier 2 candidates for the :class:`TierManager`.

Screening criteria (from 10-stock-universe design document):

- **VOLUME_BREAKOUT**: today's volume > 20-day average volume * 5
- **PRICE_BREAKOUT**: close at 52-week high or low
- **RSI_EXTREME**: 14-day RSI < 25 or > 75
- **GAP**: opening gap > 5% from previous close

Configuration keys consumed::

    screener.volume_breakout_multiplier  -- default 5.0
    screener.rsi_period                  -- default 14
    screener.rsi_low                     -- default 25
    screener.rsi_high                    -- default 75
    screener.gap_threshold_pct           -- default 5.0
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _nested_get(d: dict, dotted_key: str, default: Any = None) -> Any:
    """Retrieve a value from a nested dict using a dotted key path."""
    keys = dotted_key.split(".")
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(k)
        if current is None:
            return default
    return current


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute the Relative Strength Index from a list of closing prices.

    Requires at least ``period + 1`` data points.  Returns ``None`` if
    insufficient data is available.

    Uses the exponential (Wilder) smoothing method:
    - First average is simple mean of gains/losses over *period* bars.
    - Subsequent averages use ``prev_avg * (period - 1) + current) / period``.
    """
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Seed with simple average over the first *period* changes
    gains = [max(d, 0.0) for d in deltas[:period]]
    losses = [abs(min(d, 0.0)) for d in deltas[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder smoothing for the remaining deltas
    for delta in deltas[period:]:
        gain = max(delta, 0.0)
        loss = abs(min(delta, 0.0))
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0.0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class Screener:
    """Daily Tier 3 screening engine.

    Parameters
    ----------
    config:
        System configuration dict.
    """

    def __init__(self, config: dict) -> None:
        self._config = config

        self._volume_multiplier: float = float(
            _nested_get(config, "screener.volume_breakout_multiplier", 5.0)
        )
        self._rsi_period: int = int(
            _nested_get(config, "screener.rsi_period", 14)
        )
        self._rsi_low: float = float(
            _nested_get(config, "screener.rsi_low", 25)
        )
        self._rsi_high: float = float(
            _nested_get(config, "screener.rsi_high", 75)
        )
        self._gap_threshold_pct: float = float(
            _nested_get(config, "screener.gap_threshold_pct", 5.0)
        )

    def daily_screen(
        self,
        market: str,
        daily_bars: list[dict],
    ) -> list[tuple[str, str]]:
        """Screen daily bars and return Tier 2 candidates.

        Parameters
        ----------
        market:
            Market identifier (``"KR"`` or ``"US"``).
        daily_bars:
            List of per-symbol daily bar dicts.  Each dict should contain::

                {
                    "symbol": "005930",
                    "open": 58000,
                    "high": 59000,
                    "low": 57500,
                    "close": 58500,
                    "volume": 12000000,
                    "prev_close": 57800,       # previous day close
                    "avg_volume_20d": 2000000,  # 20-day avg volume
                    "high_52w": 65000,          # 52-week high
                    "low_52w": 45000,           # 52-week low
                    "closes": [...]             # recent closing prices
                                                # (at least rsi_period + 1)
                }

        Returns
        -------
        list[tuple[str, str]]
            List of ``(symbol, reason)`` tuples for symbols that pass
            at least one screening criterion.
        """
        candidates: list[tuple[str, str]] = []

        for bar in daily_bars:
            symbol = bar.get("symbol", "")
            if not symbol:
                continue

            matched_reasons = self._evaluate(bar)
            for reason in matched_reasons:
                candidates.append((symbol, reason))

        if candidates:
            logger.info(
                "Screener found %d candidate(s) in %s market",
                len(candidates),
                market,
            )
        else:
            logger.debug("Screener found no candidates in %s market", market)

        return candidates

    def _evaluate(self, bar: dict) -> list[str]:
        """Evaluate a single daily bar against all screening criteria.

        Returns a list of reason strings for each criterion met.  A symbol
        may trigger multiple reasons.
        """
        reasons: list[str] = []

        volume = float(bar.get("volume", 0))
        avg_volume_20d = float(bar.get("avg_volume_20d", 0))
        close = float(bar.get("close", 0))
        open_price = float(bar.get("open", 0))
        prev_close = float(bar.get("prev_close", 0))
        high_52w = float(bar.get("high_52w", 0))
        low_52w = float(bar.get("low_52w", 0))
        closes: list[float] = bar.get("closes", [])

        # 1. Volume breakout: today volume > 20d average * multiplier
        if avg_volume_20d > 0 and volume > avg_volume_20d * self._volume_multiplier:
            reasons.append("VOLUME_BREAKOUT")

        # 2. Price breakout: close at 52-week high or low
        if high_52w > 0 and close >= high_52w:
            reasons.append("PRICE_BREAKOUT")
        elif low_52w > 0 and close <= low_52w:
            reasons.append("PRICE_BREAKOUT")

        # 3. RSI extreme
        rsi = _compute_rsi(closes, self._rsi_period)
        if rsi is not None:
            if rsi < self._rsi_low or rsi > self._rsi_high:
                reasons.append("RSI_EXTREME")

        # 4. Gap: opening gap > threshold from previous close
        if prev_close > 0:
            gap_pct = abs(open_price - prev_close) / prev_close * 100.0
            if gap_pct > self._gap_threshold_pct:
                reasons.append("GAP")

        return reasons
