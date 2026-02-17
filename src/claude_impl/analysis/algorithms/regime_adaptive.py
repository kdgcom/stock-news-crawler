"""Regime-Adaptive (RA) algorithm.

First detects the current market regime (trending up/down, sideways,
volatile, low volatility) and then delegates to the algorithm that
performs best in that regime.

Regime detection uses SMA-50 slope for trend and a short/long
volatility ratio for the volatility state.

Regime -> optimal algorithm mapping (configurable):

    trending_up    -> technical_trend
    trending_down  -> technical_trend
    sideways       -> mean_reversion
    volatile       -> event_catalyst
    low_volatility -> sentiment_momentum

Config keys (``algorithms.regime_adaptive``)::

    regime_detection.trend_window       -- SMA period for trend (50)
    regime_detection.volatility_window  -- short-term vol window (20)
    regime_algorithm_map                -- regime -> algorithm name
"""

from __future__ import annotations

import logging

from ..base_algorithm import BaseAlgorithm
from ..indicators import sma, stdev
from ...models.signal import AlgorithmContext, Signal

logger = logging.getLogger(__name__)

# Default regime-to-algorithm map
_DEFAULT_REGIME_MAP: dict[str, str] = {
    "trending_up": "technical_trend",
    "trending_down": "technical_trend",
    "sideways": "mean_reversion",
    "volatile": "event_catalyst",
    "low_volatility": "sentiment_momentum",
}


class RegimeAdaptive(BaseAlgorithm):
    """Regime detection then delegation to the optimal sub-algorithm."""

    def __init__(self, config: dict, algorithms: dict | None = None) -> None:
        super().__init__(config)
        # ``algorithms`` is a dict[str, BaseAlgorithm] injected by the
        # router so that delegation works without circular imports.
        self._algorithms: dict = algorithms or {}

    @property
    def name(self) -> str:
        return "regime_adaptive"

    def required_data(self) -> list[str]:
        return ["price_bars", "daily_bars", "news_events",
                "sentiment_current", "sentiment_previous"]

    def set_algorithms(self, algorithms: dict) -> None:
        """Late-bind the algorithm registry after construction."""
        self._algorithms = algorithms

    # ------------------------------------------------------------------
    # Regime detection
    # ------------------------------------------------------------------

    def _detect_regime(self, daily_bars: list[dict]) -> str:
        """Classify the market regime from daily bar data."""
        if len(daily_bars) < 50:
            return "sideways"

        closes = [float(b["close"]) for b in daily_bars]
        rd = self.config.get("regime_detection", {})
        trend_window: int = rd.get("trend_window", 50)
        vol_window: int = rd.get("volatility_window", 20)

        sma_current = sma(closes, trend_window)
        sma_prev = sma(closes[:-5], trend_window)
        trend_slope = (sma_current - sma_prev) / sma_current if sma_current else 0

        vol_short = stdev(closes[-vol_window:])
        vol_long = stdev(closes[-trend_window:])
        vol_ratio = vol_short / vol_long if vol_long > 0 else 1.0

        if vol_ratio > 1.5:
            return "volatile"
        if vol_ratio < 0.6:
            return "low_volatility"
        if trend_slope > 0.002:
            return "trending_up"
        if trend_slope < -0.002:
            return "trending_down"
        return "sideways"

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        regime = self._detect_regime(ctx.daily_bars)

        regime_map: dict[str, str] = self.config.get(
            "regime_algorithm_map", _DEFAULT_REGIME_MAP,
        )
        algo_name = regime_map.get(regime, "sentiment_momentum")
        delegate = self._algorithms.get(algo_name)

        if delegate is None:
            logger.warning(
                "RegimeAdaptive: delegate '%s' not found, returning HOLD.", algo_name,
            )
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="HOLD",
                score=0.0,
                confidence=0.2,
                algorithm=self.name,
                reason_codes=["DELEGATE_NOT_FOUND"],
                details={"regime": regime, "missing_delegate": algo_name},
            )

        signal = delegate.generate_signal(ctx)

        # Annotate the signal with regime metadata
        signal.details["regime"] = regime
        signal.details["delegate_algorithm"] = algo_name
        signal.reason_codes.insert(0, f"REGIME_{regime.upper()}")
        # Keep the algorithm attribution on this wrapper
        signal.algorithm = self.name

        return signal
