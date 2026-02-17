"""Technical Trend (TF) algorithm.

Follows confirmed trends using a triple-confirmation approach:

1. **SMA Cross** -- golden cross (20 > 50) or dead cross (20 < 50)
2. **MACD Confirm** -- histogram aligned with the cross direction
3. **Volume Confirm** -- current volume exceeds the 20-period average

ATR-based stop-loss distance is included in the signal details to
guide downstream position sizing.

Best suited for:
    * Clear up / down trends
    * Large-cap stocks with adequate volume

Config keys (``algorithms.technical_trend``)::

    entry_conditions.sma_cross       -- require SMA cross
    entry_conditions.macd_confirm    -- require MACD alignment
    entry_conditions.volume_confirm  -- require volume surge
    atr_stop_multiplier              -- ATR multiple for stop distance
    exit_conditions.sma_reverse      -- exit on SMA reversal
"""

from __future__ import annotations

from statistics import mean as _mean

from ..base_algorithm import BaseAlgorithm
from ..indicators import compute_atr, compute_macd, sma
from ...models.signal import AlgorithmContext, Signal


class TechnicalTrend(BaseAlgorithm):
    """SMA cross + MACD confirm + volume confirm trend follower."""

    @property
    def name(self) -> str:
        return "technical_trend"

    def required_data(self) -> list[str]:
        return ["price_bars"]

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        bars = ctx.price_bars
        cfg = self.config

        if len(bars) < 51:
            return self._hold(ctx, ["INSUFFICIENT_BARS"])

        closes = [float(b["close"]) for b in bars]
        volumes = [float(b["volume"]) for b in bars]

        # --- SMA Cross ------------------------------------------------
        sma_short = sma(closes, 20)
        sma_long = sma(closes, 50)
        sma_cross = "golden" if sma_short > sma_long else "dead"

        sma_short_prev = sma(closes[:-1], 20)
        sma_long_prev = sma(closes[:-1], 50)
        sma_prev = "golden" if sma_short_prev > sma_long_prev else "dead"
        sma_just_crossed = sma_cross != sma_prev

        # --- MACD Confirm ---------------------------------------------
        macd_line, signal_line, histogram = compute_macd(closes, 12, 26, 9)
        # For a golden cross we want bullish MACD (histogram > 0)
        macd_bullish = histogram > 0

        # --- Volume Confirm -------------------------------------------
        vol_avg = _mean(volumes[-20:]) if len(volumes) >= 20 else _mean(volumes)
        vol_confirm = volumes[-1] > vol_avg * 1.5

        # --- Build entry check list -----------------------------------
        entry_cfg = cfg.get("entry_conditions", {})
        entry_checks: list[bool] = []

        if entry_cfg.get("sma_cross", True):
            entry_checks.append(sma_just_crossed)
        if entry_cfg.get("macd_confirm", True):
            if sma_cross == "golden":
                entry_checks.append(macd_bullish)
            else:
                entry_checks.append(not macd_bullish)
        if entry_cfg.get("volume_confirm", True):
            entry_checks.append(vol_confirm)

        all_confirmed = all(entry_checks) if entry_checks else False

        # --- ATR stop-loss distance -----------------------------------
        atr_mult: float = cfg.get("atr_stop_multiplier", 2.0)
        atr = compute_atr(bars, 14)
        stop_distance = atr * atr_mult

        # --- Entry signals --------------------------------------------
        if all_confirmed and sma_cross == "golden":
            reason_codes = ["SMA_GOLDEN_CROSS"]
            if entry_cfg.get("macd_confirm", True):
                reason_codes.append("MACD_CONFIRM")
            if vol_confirm:
                reason_codes.append("VOLUME_CONFIRM")

            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="BUY",
                score=0.7,
                confidence=0.8 if vol_confirm else 0.6,
                algorithm=self.name,
                reason_codes=reason_codes,
                details={
                    "sma_20": round(sma_short, 4),
                    "sma_50": round(sma_long, 4),
                    "macd_histogram": round(histogram, 4),
                    "volume_ratio": round(volumes[-1] / vol_avg, 2) if vol_avg else 0,
                    "stop_loss_distance": round(stop_distance, 4),
                    "atr": round(atr, 4),
                },
            )

        if all_confirmed and sma_cross == "dead":
            reason_codes = ["SMA_DEAD_CROSS"]
            if entry_cfg.get("macd_confirm", True):
                reason_codes.append("MACD_CONFIRM")
            if vol_confirm:
                reason_codes.append("VOLUME_CONFIRM")

            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="SELL",
                score=-0.7,
                confidence=0.8 if vol_confirm else 0.6,
                algorithm=self.name,
                reason_codes=reason_codes,
                details={
                    "sma_20": round(sma_short, 4),
                    "sma_50": round(sma_long, 4),
                    "macd_histogram": round(histogram, 4),
                    "volume_ratio": round(volumes[-1] / vol_avg, 2) if vol_avg else 0,
                    "stop_loss_distance": round(stop_distance, 4),
                    "atr": round(atr, 4),
                },
            )

        # --- Exit check for existing positions ------------------------
        exit_cfg = cfg.get("exit_conditions", {})
        if ctx.position and exit_cfg.get("sma_reverse", True):
            if sma_cross == "dead" and ctx.position.get("side") == "long":
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="SELL",
                    score=-0.5,
                    confidence=0.6,
                    algorithm=self.name,
                    reason_codes=["SMA_REVERSE_EXIT"],
                    details={
                        "sma_20": round(sma_short, 4),
                        "sma_50": round(sma_long, 4),
                    },
                )
            if sma_cross == "golden" and ctx.position.get("side") == "short":
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="BUY",
                    score=0.5,
                    confidence=0.6,
                    algorithm=self.name,
                    reason_codes=["SMA_REVERSE_EXIT"],
                    details={
                        "sma_20": round(sma_short, 4),
                        "sma_50": round(sma_long, 4),
                    },
                )

        return self._hold(ctx, ["NO_TREND_SIGNAL"])

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
