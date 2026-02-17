"""Mean Reversion (MR) algorithm.

Exploits the tendency of prices to revert to their statistical mean.
Buys when price is oversold (RSI low + near lower Bollinger Band) and
sells when overbought (RSI high + near upper Bollinger Band).  Volume
divergence is used as a confirmation filter to distinguish true
exhaustion from continued momentum.

Best suited for:
    * Range-bound / sideways markets
    * Periods of stable volatility

Config keys (``algorithms.mean_reversion``)::

    rsi_oversold              -- RSI threshold for oversold (default 30)
    rsi_overbought            -- RSI threshold for overbought (default 70)
    bollinger_entry           -- % proximity to band required for entry
    require_volume_divergence -- boolean: enforce volume divergence check
"""

from __future__ import annotations

from ..base_algorithm import BaseAlgorithm
from ..indicators import compute_bollinger, compute_rsi
from ...models.signal import AlgorithmContext, Signal


class MeanReversion(BaseAlgorithm):
    """RSI + Bollinger Bands + volume divergence mean-reversion strategy."""

    @property
    def name(self) -> str:
        return "mean_reversion"

    def required_data(self) -> list[str]:
        return ["price_bars"]

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        bars = ctx.price_bars
        cfg = self.config

        if len(bars) < 21:
            return self._hold(ctx, ["INSUFFICIENT_BARS"])

        closes = [float(b["close"]) for b in bars]
        volumes = [float(b["volume"]) for b in bars]

        rsi = compute_rsi(closes, 14)
        bb_upper, bb_middle, bb_lower = compute_bollinger(closes, 20, 2.0)
        current_price = closes[-1]

        rsi_oversold: float = cfg.get("rsi_oversold", 30)
        rsi_overbought: float = cfg.get("rsi_overbought", 70)
        bollinger_entry: float = cfg.get("bollinger_entry", 1.0)
        require_vol_div: bool = cfg.get("require_volume_divergence", True)

        # --- BUY: oversold + lower band approach + volume divergence --
        is_oversold = rsi < rsi_oversold
        near_lower = current_price <= bb_lower * (1 + bollinger_entry * 0.01)

        if require_vol_div and len(closes) >= 4 and len(volumes) >= 4:
            vol_divergence = (
                closes[-1] < closes[-3] and volumes[-1] < volumes[-3]
            )
        else:
            vol_divergence = True

        if is_oversold and near_lower and vol_divergence:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="BUY",
                score=0.6,
                confidence=0.7,
                algorithm=self.name,
                reason_codes=["RSI_OVERSOLD", "BOLLINGER_LOWER", "VOLUME_DIVERGENCE"],
                details={
                    "rsi": round(rsi, 2),
                    "bb_lower": round(bb_lower, 4),
                    "bb_middle": round(bb_middle, 4),
                    "bb_upper": round(bb_upper, 4),
                    "target": round(bb_middle, 4),
                    "current_price": current_price,
                },
            )

        # --- SELL: overbought + upper band approach --------------------
        is_overbought = rsi > rsi_overbought
        near_upper = current_price >= bb_upper * (1 - bollinger_entry * 0.01)

        if is_overbought and near_upper:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="SELL",
                score=-0.6,
                confidence=0.7,
                algorithm=self.name,
                reason_codes=["RSI_OVERBOUGHT", "BOLLINGER_UPPER"],
                details={
                    "rsi": round(rsi, 2),
                    "bb_upper": round(bb_upper, 4),
                    "bb_middle": round(bb_middle, 4),
                    "bb_lower": round(bb_lower, 4),
                    "target": round(bb_middle, 4),
                    "current_price": current_price,
                },
            )

        # --- EXIT: price reverted to middle band ----------------------
        if ctx.position:
            if bb_middle > 0 and abs(current_price - bb_middle) / bb_middle < 0.005:
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="SELL",
                    score=-0.3,
                    confidence=0.6,
                    algorithm=self.name,
                    reason_codes=["MEAN_REVERSION_TARGET"],
                    details={
                        "rsi": round(rsi, 2),
                        "bb_middle": round(bb_middle, 4),
                        "current_price": current_price,
                    },
                )

        return self._hold(ctx, ["NO_REVERSION_SIGNAL"])

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
