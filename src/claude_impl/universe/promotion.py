"""Promotion and demotion logic for universe tier transitions.

Evaluates per-symbol statistics against threshold rules defined in the
10-stock-universe design document to decide whether a symbol should be
promoted (Tier 2 -> Tier 1) or demoted (Tier 1 -> Tier 2).

Promotion reasons:

- ``NEWS_SPIKE``:      24h news count > 30d average * 3
- ``VOLUME_SPIKE``:    today volume > 5d average * 3
- ``VOLATILITY_JUMP``: volatility rank <= 10%
- ``EARNINGS_SOON``:   days to earnings <= 7
- ``SENTIMENT_SHIFT``: abs(sentiment change 24h) > 0.5

Demotion reasons:

- ``NO_SIGNAL_30D``:       0 signals in 30 days
- ``LOW_VOLUME``:          below threshold for 10 consecutive days
- ``POST_CLOSE_COOLDOWN``: position closed within 7 days

Configuration keys consumed::

    promotion.news_spike_multiplier         -- default 3.0
    promotion.volume_spike_multiplier       -- default 3.0
    promotion.volatility_rank_threshold     -- default 10 (percent)
    promotion.earnings_days_threshold       -- default 7
    promotion.sentiment_shift_threshold     -- default 0.5
    demotion.no_signal_days                 -- default 30
    demotion.low_volume_consecutive_days    -- default 10
    demotion.post_close_cooldown_days       -- default 7
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


class PromotionChecker:
    """Evaluate promotion and demotion criteria for individual symbols.

    Parameters
    ----------
    config:
        System configuration dict.
    """

    def __init__(self, config: dict) -> None:
        self._config = config

        # Promotion thresholds
        self._news_spike_multiplier: float = float(
            _nested_get(config, "promotion.news_spike_multiplier", 3.0)
        )
        self._volume_spike_multiplier: float = float(
            _nested_get(config, "promotion.volume_spike_multiplier", 3.0)
        )
        self._volatility_rank_threshold: float = float(
            _nested_get(config, "promotion.volatility_rank_threshold", 10)
        )
        self._earnings_days_threshold: int = int(
            _nested_get(config, "promotion.earnings_days_threshold", 7)
        )
        self._sentiment_shift_threshold: float = float(
            _nested_get(config, "promotion.sentiment_shift_threshold", 0.5)
        )

        # Demotion thresholds
        self._no_signal_days: int = int(
            _nested_get(config, "demotion.no_signal_days", 30)
        )
        self._low_volume_consecutive_days: int = int(
            _nested_get(config, "demotion.low_volume_consecutive_days", 10)
        )
        self._post_close_cooldown_days: int = int(
            _nested_get(config, "demotion.post_close_cooldown_days", 7)
        )

    def check_promotion(
        self,
        symbol: str,
        market: str,
        stats: dict,
    ) -> str | None:
        """Check whether a symbol qualifies for promotion to Tier 1.

        Parameters
        ----------
        symbol:
            Ticker or stock code.
        market:
            ``"KR"`` or ``"US"``.
        stats:
            Dict containing the statistics needed for evaluation::

                {
                    "news_count_24h": 15,
                    "avg_news_count_30d": 3.0,
                    "volume_today": 5000000,
                    "avg_volume_5d": 1200000,
                    "volatility_rank_pct": 8.0,
                    "days_to_earnings": 5,
                    "sentiment_change_24h": 0.6,
                }

        Returns
        -------
        str | None
            The promotion reason string if any criterion is met, or
            ``None`` if the symbol does not qualify.  Only the **first**
            matching reason is returned (checked in priority order).
        """
        # 1. NEWS_SPIKE: 24h news count > 30d avg * multiplier
        news_24h = float(stats.get("news_count_24h", 0))
        avg_news_30d = float(stats.get("avg_news_count_30d", 0))
        if avg_news_30d > 0 and news_24h > avg_news_30d * self._news_spike_multiplier:
            logger.info(
                "Promotion %s (%s): NEWS_SPIKE (24h=%d, avg30d=%.1f, threshold=%.1f)",
                symbol,
                market,
                news_24h,
                avg_news_30d,
                avg_news_30d * self._news_spike_multiplier,
            )
            return "NEWS_SPIKE"

        # 2. VOLUME_SPIKE: today volume > 5d avg * multiplier
        volume_today = float(stats.get("volume_today", 0))
        avg_volume_5d = float(stats.get("avg_volume_5d", 0))
        if avg_volume_5d > 0 and volume_today > avg_volume_5d * self._volume_spike_multiplier:
            logger.info(
                "Promotion %s (%s): VOLUME_SPIKE (today=%d, avg5d=%.0f, threshold=%.0f)",
                symbol,
                market,
                volume_today,
                avg_volume_5d,
                avg_volume_5d * self._volume_spike_multiplier,
            )
            return "VOLUME_SPIKE"

        # 3. VOLATILITY_JUMP: volatility rank <= threshold (top N%)
        volatility_rank = stats.get("volatility_rank_pct")
        if volatility_rank is not None:
            volatility_rank = float(volatility_rank)
            if volatility_rank <= self._volatility_rank_threshold:
                logger.info(
                    "Promotion %s (%s): VOLATILITY_JUMP (rank=%.1f%%, threshold=%.1f%%)",
                    symbol,
                    market,
                    volatility_rank,
                    self._volatility_rank_threshold,
                )
                return "VOLATILITY_JUMP"

        # 4. EARNINGS_SOON: days to earnings <= threshold
        days_to_earnings = stats.get("days_to_earnings")
        if days_to_earnings is not None:
            days_to_earnings = int(days_to_earnings)
            if 0 <= days_to_earnings <= self._earnings_days_threshold:
                logger.info(
                    "Promotion %s (%s): EARNINGS_SOON (D-%d, threshold=D-%d)",
                    symbol,
                    market,
                    days_to_earnings,
                    self._earnings_days_threshold,
                )
                return "EARNINGS_SOON"

        # 5. SENTIMENT_SHIFT: abs(sentiment change 24h) > threshold
        sentiment_change = stats.get("sentiment_change_24h")
        if sentiment_change is not None:
            sentiment_change = float(sentiment_change)
            if abs(sentiment_change) > self._sentiment_shift_threshold:
                logger.info(
                    "Promotion %s (%s): SENTIMENT_SHIFT (change=%.2f, threshold=%.2f)",
                    symbol,
                    market,
                    sentiment_change,
                    self._sentiment_shift_threshold,
                )
                return "SENTIMENT_SHIFT"

        return None

    def check_demotion(
        self,
        symbol: str,
        market: str,
        stats: dict,
    ) -> str | None:
        """Check whether a symbol should be demoted from Tier 1 to Tier 2.

        Parameters
        ----------
        symbol:
            Ticker or stock code.
        market:
            ``"KR"`` or ``"US"``.
        stats:
            Dict containing the statistics needed for evaluation::

                {
                    "signal_count_30d": 0,
                    "low_volume_consecutive_days": 12,
                    "days_since_position_closed": 3,
                }

        Returns
        -------
        str | None
            The demotion reason string if any criterion is met, or
            ``None`` if the symbol should remain in Tier 1.  Only the
            **first** matching reason is returned.
        """
        # 1. NO_SIGNAL_30D: zero signals in the configured period
        signal_count = stats.get("signal_count_30d")
        if signal_count is not None:
            signal_count = int(signal_count)
            if signal_count == 0:
                logger.info(
                    "Demotion %s (%s): NO_SIGNAL_30D (0 signals in %d days)",
                    symbol,
                    market,
                    self._no_signal_days,
                )
                return "NO_SIGNAL_30D"

        # 2. LOW_VOLUME: below threshold for N consecutive days
        low_vol_days = stats.get("low_volume_consecutive_days")
        if low_vol_days is not None:
            low_vol_days = int(low_vol_days)
            if low_vol_days >= self._low_volume_consecutive_days:
                logger.info(
                    "Demotion %s (%s): LOW_VOLUME (%d consecutive days, threshold=%d)",
                    symbol,
                    market,
                    low_vol_days,
                    self._low_volume_consecutive_days,
                )
                return "LOW_VOLUME"

        # 3. POST_CLOSE_COOLDOWN: position closed within cooldown period
        days_since_closed = stats.get("days_since_position_closed")
        if days_since_closed is not None:
            days_since_closed = int(days_since_closed)
            if 0 <= days_since_closed <= self._post_close_cooldown_days:
                logger.info(
                    "Demotion %s (%s): POST_CLOSE_COOLDOWN (closed %d days ago, cooldown=%d)",
                    symbol,
                    market,
                    days_since_closed,
                    self._post_close_cooldown_days,
                )
                return "POST_CLOSE_COOLDOWN"

        return None
