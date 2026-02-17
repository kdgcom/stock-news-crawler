"""Level 2 dynamic risk -- adjusts position sizing and order eligibility
based on current market conditions.

These checks sit between the hard limits (Level 1) and AI validation
(Level 3).  Unlike hard limits they are *context-sensitive*: the same
order that passes in a calm market may be blocked or reduced when
volatility spikes, after consecutive losses, or around major events.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _cfg(config: dict, key: str, default: Any = None) -> Any:
    return config.get(key, default)


class DynamicRiskChecker:
    """Level 2 risk gate -- market-condition-aware checks.

    Parameters
    ----------
    config:
        The ``risk.dynamic`` section from the application config, e.g.::

            {
                "consecutive_loss_cooldown_hours": 1,
                "consecutive_loss_count": 3,
                "post_event_blackout_seconds": 30,
                "max_spread_pct": 0.005,
                "volatility_reduce_threshold": 0.8,
            }
    """

    def __init__(self, config: dict) -> None:
        self._consecutive_loss_cooldown_hours: float = _cfg(
            config, "consecutive_loss_cooldown_hours", 1.0
        )
        self._consecutive_loss_count: int = _cfg(
            config, "consecutive_loss_count", 3
        )
        self._post_event_blackout_seconds: int = _cfg(
            config, "post_event_blackout_seconds", 30
        )
        self._max_spread_pct: float = _cfg(config, "max_spread_pct", 0.005)
        self._volatility_reduce_threshold: float = _cfg(
            config, "volatility_reduce_threshold", 0.80
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def check(self, order: dict, market_state: dict) -> tuple[bool, str]:
        """Run all dynamic risk checks.

        Returns ``(True, "ALL_PASSED")`` when every check passes, or
        ``(False, "<REASON_CODE>")`` on the first failure.

        Parameters
        ----------
        order:
            Proposed order dict.  Expected keys:

            - ``side`` -- ``"buy"`` or ``"sell"``
            - ``spread_pct`` -- current bid-ask spread as a decimal
              (e.g. ``0.003`` for 0.3 %).  May be ``None``.
            - ``event_ts`` -- ISO-8601 timestamp of the triggering event,
              or ``None`` if not event-driven.

        market_state:
            Current market snapshot.  Expected keys:

            - ``volatility_percentile`` -- current volatility as a
              percentile (0.0 -- 1.0).
            - ``consecutive_losses`` -- number of consecutive losing
              trades (int).
            - ``last_loss_ts`` -- ISO-8601 timestamp of the most recent
              loss, or ``None``.
            - ``circuit_breaker_active`` -- ``True`` if a market-wide
              circuit breaker is in effect.
        """
        checks: list[tuple[bool, str]] = [
            self._check_circuit_breaker(market_state),
            self._check_volatility(market_state),
            self._check_consecutive_loss(market_state, order),
            self._check_post_event_blackout(order),
            self._check_spread(order),
        ]
        for passed, reason in checks:
            if not passed:
                logger.warning("Dynamic risk check failed: %s", reason)
                return False, reason
        return True, "ALL_PASSED"

    # ------------------------------------------------------------------
    # Position-size modifier
    # ------------------------------------------------------------------

    def get_position_size_modifier(self, market_state: dict) -> float:
        """Return a multiplier to apply to the proposed position size.

        * ``1.0`` -- normal sizing
        * ``0.5`` -- halved (high-volatility regime)
        * ``0.0`` -- full block (circuit breaker)

        The caller is responsible for applying this modifier to the
        order quantity / amount before submission.
        """
        if market_state.get("circuit_breaker_active", False):
            return 0.0

        vol_pct: float = market_state.get("volatility_percentile", 0.0)
        if vol_pct >= self._volatility_reduce_threshold:
            # Linearly scale down between threshold and 1.0.
            # At the threshold itself the modifier is 0.5; at the 100th
            # percentile it drops to 0.25.
            remaining = 1.0 - self._volatility_reduce_threshold
            if remaining <= 0:
                return 0.5
            excess = vol_pct - self._volatility_reduce_threshold
            scale = 0.5 - 0.25 * (excess / remaining)
            return max(round(scale, 4), 0.25)

        return 1.0

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_volatility(self, market_state: dict) -> tuple[bool, str]:
        """When volatility is in the top 20 % (>= threshold), log a
        warning but do **not** block the order outright -- position size
        reduction is handled via :meth:`get_position_size_modifier`.

        This check only *blocks* at the extreme (100th percentile) to
        guard against data errors.
        """
        vol_pct: float = market_state.get("volatility_percentile", 0.0)
        if vol_pct >= 1.0:
            return (
                False,
                f"EXTREME_VOLATILITY: percentile {vol_pct:.2%} -- "
                "order blocked for safety",
            )
        if vol_pct >= self._volatility_reduce_threshold:
            modifier = self.get_position_size_modifier(market_state)
            logger.info(
                "High volatility (%.1f%% percentile) -- position size "
                "modifier %.2f applied",
                vol_pct * 100,
                modifier,
            )
        return True, "VOLATILITY_OK"

    def _check_consecutive_loss(
        self, market_state: dict, order: dict
    ) -> tuple[bool, str]:
        """After N consecutive losses, impose a buy cooldown period.

        Sell orders are always permitted so that the system can still
        exit positions.
        """
        side: str = order.get("side", "buy")
        if side != "buy":
            return True, "CONSECUTIVE_LOSS_OK"

        consecutive: int = market_state.get("consecutive_losses", 0)
        if consecutive < self._consecutive_loss_count:
            return True, "CONSECUTIVE_LOSS_OK"

        # Check cooldown elapsed since last loss.
        last_loss_ts: str | None = market_state.get("last_loss_ts")
        if last_loss_ts is None:
            # No timestamp recorded -- conservatively block.
            return (
                False,
                f"CONSECUTIVE_LOSS_COOLDOWN: {consecutive} consecutive losses, "
                "no last_loss_ts -- blocking buy",
            )

        try:
            last_loss_dt = datetime.fromisoformat(last_loss_ts)
            if last_loss_dt.tzinfo is None:
                last_loss_dt = last_loss_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return (
                False,
                "CONSECUTIVE_LOSS_COOLDOWN: unparseable last_loss_ts",
            )

        now_utc = datetime.now(tz=timezone.utc)
        elapsed_hours = (now_utc - last_loss_dt).total_seconds() / 3600.0
        if elapsed_hours < self._consecutive_loss_cooldown_hours:
            remaining_min = (
                self._consecutive_loss_cooldown_hours - elapsed_hours
            ) * 60
            return (
                False,
                f"CONSECUTIVE_LOSS_COOLDOWN: {consecutive} consecutive losses, "
                f"cooldown remaining {remaining_min:.0f} min",
            )

        return True, "CONSECUTIVE_LOSS_OK"

    def _check_post_event_blackout(self, order: dict) -> tuple[bool, str]:
        """No orders within *blackout_seconds* of a major event.

        The triggering event timestamp is expected in ``order["event_ts"]``
        as an ISO-8601 string.  If absent the check passes (the order is
        not event-driven).
        """
        event_ts_raw: str | None = order.get("event_ts")
        if event_ts_raw is None:
            return True, "POST_EVENT_BLACKOUT_OK"

        try:
            event_dt = datetime.fromisoformat(event_ts_raw)
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return True, "POST_EVENT_BLACKOUT_OK"

        now_utc = datetime.now(tz=timezone.utc)
        elapsed = (now_utc - event_dt).total_seconds()
        if elapsed < self._post_event_blackout_seconds:
            return (
                False,
                f"POST_EVENT_BLACKOUT: only {elapsed:.1f}s since event, "
                f"need {self._post_event_blackout_seconds}s",
            )
        return True, "POST_EVENT_BLACKOUT_OK"

    def _check_spread(self, order: dict) -> tuple[bool, str]:
        """Block entry orders when the bid-ask spread is too wide.

        Only buy orders are blocked -- sell (exit) orders are always
        allowed so the system can close positions even in illiquid
        conditions.
        """
        side: str = order.get("side", "buy")
        if side != "buy":
            return True, "SPREAD_OK"

        spread_pct: float | None = order.get("spread_pct")
        if spread_pct is None:
            return True, "SPREAD_OK"

        if spread_pct > self._max_spread_pct:
            return (
                False,
                f"SPREAD_TOO_WIDE: {spread_pct:.4%} > "
                f"limit {self._max_spread_pct:.4%}",
            )
        return True, "SPREAD_OK"

    def _check_circuit_breaker(self, market_state: dict) -> tuple[bool, str]:
        """If a market-wide circuit breaker is active, block all orders."""
        if market_state.get("circuit_breaker_active", False):
            return False, "CIRCUIT_BREAKER_ACTIVE: all orders halted"
        return True, "CIRCUIT_BREAKER_OK"
