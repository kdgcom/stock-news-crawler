"""Overnight Gap (OG) algorithm.

Reacts to opening gaps with two possible strategies:

* **Gap Fill** -- trade against the gap direction, expecting reversion
  to the previous close.
* **Gap & Go** -- follow the gap direction when news sentiment confirms
  the move.

The ``sentiment_confirm`` config controls whether sentiment alignment
is required.

Best suited for:
    * Gaps detected during the pre-market routine (05-pre-market)
    * First 10 -- 120 minutes after market open

Config keys (``algorithms.overnight_gap``)::

    entry_delay_bars    -- bars to wait after open before acting
    max_hold_bars       -- max bars after open to keep the gap trade
    min_gap_pct         -- minimum absolute gap size
    sentiment_confirm   -- whether to require sentiment alignment
    gap_fill_mode       -- True = gap fill, False = gap & go
"""

from __future__ import annotations

from ..base_algorithm import BaseAlgorithm
from ...models.signal import AlgorithmContext, Signal


class OvernightGap(BaseAlgorithm):
    """Gap fill vs gap-and-go with optional sentiment confirmation."""

    @property
    def name(self) -> str:
        return "overnight_gap"

    def required_data(self) -> list[str]:
        return ["price_bars", "daily_bars", "sentiment_current"]

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        cfg = self.config
        bars = ctx.price_bars
        daily = ctx.daily_bars

        if not bars or not daily or len(daily) < 2:
            return self._hold(ctx, ["INSUFFICIENT_DATA"])

        entry_delay: int = cfg.get("entry_delay_bars", 2)
        max_hold: int = cfg.get("max_hold_bars", 24)
        min_gap_pct: float = cfg.get("min_gap_pct", 0.01)

        # Estimate bars since open from the number of intraday bars
        bars_since_open = len(bars)

        if bars_since_open < entry_delay:
            return self._hold(ctx, ["GAP_DELAY_PERIOD"])

        if bars_since_open > max_hold:
            return self._hold(ctx, ["GAP_WINDOW_EXPIRED"])

        # Previous close from daily bars; today's open from first intraday bar
        prev_close = float(daily[-1]["close"])
        open_price = float(bars[0]["open"])

        if prev_close == 0:
            return self._hold(ctx, ["INVALID_PREV_CLOSE"])

        gap_pct = (open_price - prev_close) / prev_close

        if abs(gap_pct) < min_gap_pct:
            return self._hold(ctx, ["GAP_TOO_SMALL"])

        gap_direction = "up" if gap_pct > 0 else "down"

        # --- Sentiment confirmation -----------------------------------
        sentiment_confirm_enabled: bool = cfg.get("sentiment_confirm", True)
        sentiment_aligned = False

        if sentiment_confirm_enabled:
            if gap_direction == "up" and ctx.sentiment_current > 0.3:
                sentiment_aligned = True
            elif gap_direction == "down" and ctx.sentiment_current < -0.3:
                sentiment_aligned = True
        else:
            sentiment_aligned = True  # always pass when disabled

        details = {
            "gap_pct": round(gap_pct, 4),
            "gap_direction": gap_direction,
            "prev_close": prev_close,
            "open_price": open_price,
            "sentiment_aligned": sentiment_aligned,
            "bars_since_open": bars_since_open,
        }

        gap_fill_mode: bool = cfg.get("gap_fill_mode", False)

        if gap_fill_mode:
            # Trade against the gap when sentiment does NOT confirm
            if gap_direction == "up" and not sentiment_aligned:
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="SELL",
                    score=-0.5,
                    confidence=0.6,
                    algorithm=self.name,
                    reason_codes=["GAP_FILL_SHORT"],
                    details=details,
                )
            if gap_direction == "down" and not sentiment_aligned:
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="BUY",
                    score=0.5,
                    confidence=0.6,
                    algorithm=self.name,
                    reason_codes=["GAP_FILL_LONG"],
                    details=details,
                )
        else:
            # Follow the gap when sentiment confirms
            if gap_direction == "up" and sentiment_aligned:
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="BUY",
                    score=0.6,
                    confidence=0.7,
                    algorithm=self.name,
                    reason_codes=["GAP_AND_GO_LONG"],
                    details=details,
                )
            if gap_direction == "down" and sentiment_aligned:
                return Signal(
                    symbol=ctx.symbol,
                    market=ctx.market,
                    decision="SELL",
                    score=-0.6,
                    confidence=0.7,
                    algorithm=self.name,
                    reason_codes=["GAP_AND_GO_SHORT"],
                    details=details,
                )

        return self._hold(ctx, ["GAP_NO_CONFIRMATION"])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _hold(self, ctx: AlgorithmContext, reasons: list[str]) -> Signal:
        return Signal(
            symbol=ctx.symbol,
            market=ctx.market,
            decision="HOLD",
            score=0.0,
            confidence=0.2,
            algorithm=self.name,
            reason_codes=reasons,
            details={},
        )
