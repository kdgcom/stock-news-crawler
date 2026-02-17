"""Volume-Price Divergence (VP) algorithm.

Detects accumulation / distribution patterns and OBV divergence.
Volume leads price -- when volume surges without price movement, smart
money may be accumulating (or distributing).

Best suited for:
    * Pre-breakout consolidation phases
    * Large-cap quiet accumulation periods

Config keys (``algorithms.volume_price``)::

    accumulation.consecutive_bars     -- number of recent bars to check
    accumulation.price_change_max_pct -- max average price change (flat price)
    accumulation.volume_surge_ratio   -- volume / 20-bar avg threshold
    distribution.volume_decline_ratio -- declining volume ratio threshold
    obv_divergence_bars               -- lookback bars for OBV divergence
"""

from __future__ import annotations

from statistics import mean as _mean

from ..base_algorithm import BaseAlgorithm
from ..indicators import compute_obv
from ...models.signal import AlgorithmContext, Signal


class VolumePriceDivergence(BaseAlgorithm):
    """Accumulation/distribution detection + OBV divergence."""

    @property
    def name(self) -> str:
        return "volume_price"

    def required_data(self) -> list[str]:
        return ["price_bars"]

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        bars = ctx.price_bars
        cfg = self.config

        if len(bars) < 20:
            return self._hold(ctx, ["INSUFFICIENT_BARS"])

        # --- Accumulation detection -----------------------------------
        acc_cfg = cfg.get("accumulation", {})
        consecutive: int = acc_cfg.get("consecutive_bars", 5)
        price_max_pct: float = acc_cfg.get("price_change_max_pct", 0.005)
        vol_surge_ratio: float = acc_cfg.get("volume_surge_ratio", 1.5)

        if len(bars) >= consecutive:
            recent = bars[-consecutive:]
            price_changes = [
                abs(float(b["close"]) - float(b["open"])) / float(b["open"])
                for b in recent
                if float(b["open"]) > 0
            ]
            avg_price_change = _mean(price_changes) if price_changes else 0.0

            vol_avg_20 = _mean([float(b["volume"]) for b in bars[-20:]])
            vol_recent = _mean([float(b["volume"]) for b in recent])

            is_accumulation = (
                avg_price_change < price_max_pct
                and vol_avg_20 > 0
                and vol_recent > vol_avg_20 * vol_surge_ratio
            )

            if is_accumulation:
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="BUY",
                    score=0.5,
                    confidence=0.65,
                    algorithm=self.name,
                    reason_codes=["ACCUMULATION_DETECTED"],
                    details={
                        "avg_price_change": round(avg_price_change, 6),
                        "volume_ratio": round(vol_recent / vol_avg_20, 2) if vol_avg_20 > 0 else 0,
                    },
                )

        # --- Distribution detection -----------------------------------
        dist_cfg = cfg.get("distribution", {})
        vol_decline_ratio: float = dist_cfg.get("volume_decline_ratio", 0.7)

        if len(bars) >= 8:
            price_up = float(bars[-1]["close"]) > float(bars[-5]["close"])
            recent_3_vol = _mean([float(b["volume"]) for b in bars[-3:]])
            earlier_5_vol = _mean([float(b["volume"]) for b in bars[-8:-3]])

            vol_decline = (
                earlier_5_vol > 0
                and recent_3_vol < earlier_5_vol * vol_decline_ratio
            )

            if price_up and vol_decline:
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="SELL",
                    score=-0.5,
                    confidence=0.6,
                    algorithm=self.name,
                    reason_codes=["DISTRIBUTION_DETECTED"],
                    details={
                        "recent_vol": round(recent_3_vol, 2),
                        "earlier_vol": round(earlier_5_vol, 2),
                    },
                )

        # --- OBV divergence -------------------------------------------
        obv_bars: int = cfg.get("obv_divergence_bars", 10)
        lookback = min(obv_bars, len(bars))
        if lookback >= 3:
            obv_window = bars[-lookback:]
            obv = compute_obv(obv_window)
            price_trend = float(obv_window[-1]["close"]) - float(obv_window[0]["close"])
            obv_trend = obv[-1] - obv[0]

            if price_trend < 0 and obv_trend > 0:
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="BUY",
                    score=0.4,
                    confidence=0.55,
                    algorithm=self.name,
                    reason_codes=["OBV_BULLISH_DIVERGENCE"],
                    details={
                        "price_trend": round(price_trend, 4),
                        "obv_trend": round(obv_trend, 2),
                    },
                )

            if price_trend > 0 and obv_trend < 0:
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="SELL",
                    score=-0.4,
                    confidence=0.55,
                    algorithm=self.name,
                    reason_codes=["OBV_BEARISH_DIVERGENCE"],
                    details={
                        "price_trend": round(price_trend, 4),
                        "obv_trend": round(obv_trend, 2),
                    },
                )

        return self._hold(ctx, ["NO_VP_SIGNAL"])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _hold(self, ctx: AlgorithmContext, reasons: list[str]) -> Signal:
        return Signal(
            symbol=ctx.symbol,
            market=ctx.market,
            decision="HOLD",
            score=0.0,
            confidence=0.3,
            algorithm=self.name,
            reason_codes=reasons,
            details={},
        )
