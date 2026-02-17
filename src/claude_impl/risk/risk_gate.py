"""Unified 3-layer risk gate.

This is the **single entry point** that the execution engine calls
before placing any order.  It orchestrates:

1. **Kill Switch** -- if active, block immediately.
2. **Level 1: Hard Limits** -- absolute, unconditional limits.
3. **Level 2: Dynamic Risk** -- market-condition-aware checks.

Level 3 (AI validation) is handled separately in the analysis engine
and is not part of this module.
"""

from __future__ import annotations

import logging
from typing import Any

from claude_impl.risk.dynamic_risk import DynamicRiskChecker
from claude_impl.risk.hard_limits import HardLimitChecker
from claude_impl.risk.kill_switch import KillSwitch
from claude_impl.risk.stop_loss import StopLossChecker

logger = logging.getLogger(__name__)


def _section(config: dict, *keys: str) -> dict:
    """Drill into nested config dicts, returning ``{}`` if any key is
    missing."""
    current: Any = config
    for k in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(k, {})
    return current if isinstance(current, dict) else {}


class RiskGate:
    """Unified risk gate composing all risk-management layers.

    Parameters
    ----------
    config:
        The **full** application config (or at least the ``risk`` top-level
        section).  Sub-sections ``hard_limits``, ``dynamic``, ``stop_loss``,
        and ``kill_switch`` are extracted automatically.

    redis_client:
        A Redis-compatible client for the :class:`KillSwitch`.  If
        ``None``, a lightweight in-memory fallback is used (suitable
        for testing).
    """

    def __init__(
        self,
        config: dict,
        redis_client: Any | None = None,
    ) -> None:
        risk_cfg = _section(config, "risk")

        # If the caller already passed the ``risk`` sub-dict directly,
        # fall back gracefully.
        if not risk_cfg and any(
            k in config
            for k in ("hard_limits", "dynamic", "stop_loss", "kill_switch")
        ):
            risk_cfg = config

        self._hard_limit_checker = HardLimitChecker(
            _section(risk_cfg, "hard_limits")
        )
        self._dynamic_risk_checker = DynamicRiskChecker(
            _section(risk_cfg, "dynamic")
        )
        self._stop_loss_checker = StopLossChecker(
            _section(risk_cfg, "stop_loss")
        )

        # Kill switch requires a Redis-like store.  Build a minimal
        # in-memory fallback if none was provided.
        if redis_client is None:
            redis_client = _InMemoryRedis()
        self._kill_switch = KillSwitch(
            redis_client,
            _section(risk_cfg, "kill_switch"),
        )

    # -- Expose sub-components for direct access --------------------------

    @property
    def hard_limits(self) -> HardLimitChecker:
        return self._hard_limit_checker

    @property
    def dynamic_risk(self) -> DynamicRiskChecker:
        return self._dynamic_risk_checker

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    @property
    def stop_loss(self) -> StopLossChecker:
        return self._stop_loss_checker

    # ------------------------------------------------------------------
    # Main risk check
    # ------------------------------------------------------------------

    def check(
        self,
        signal: dict,
        portfolio: dict,
        market_state: dict | None = None,
    ) -> tuple[bool, str]:
        """Run the full 3-layer risk check pipeline.

        Returns ``(True, "ALL_PASSED")`` if every layer approves, or
        ``(False, "<REASON_CODE>")`` on the first blocking condition.

        Parameters
        ----------
        signal:
            The trading signal / proposed order dict.  Must contain at
            least the keys expected by
            :meth:`HardLimitChecker.check` (``market``, ``amount``,
            ``symbol``, ``sector``) **and**
            :meth:`DynamicRiskChecker.check` (``side``, ``spread_pct``,
            ``event_ts``).

        portfolio:
            Current portfolio state -- see :class:`HardLimitChecker` for
            the expected schema.

        market_state:
            Current market conditions -- see
            :class:`DynamicRiskChecker` for the expected schema.  If
            ``None``, Level 2 checks are skipped (useful during
            out-of-hours processing).
        """
        # Layer 0: Kill Switch
        if self._kill_switch.is_active():
            reason = self._kill_switch.get_reason() or "UNKNOWN"
            logger.warning(
                "Risk gate BLOCKED by kill switch: %s", reason
            )
            return False, f"KILL_SWITCH_ACTIVE: {reason}"

        # Layer 1: Hard Limits
        passed, reason = self._hard_limit_checker.check(signal, portfolio)
        if not passed:
            logger.warning("Risk gate BLOCKED by hard limit: %s", reason)
            return False, reason

        # Layer 2: Dynamic Risk
        if market_state is not None:
            passed, reason = self._dynamic_risk_checker.check(
                signal, market_state
            )
            if not passed:
                logger.warning(
                    "Risk gate BLOCKED by dynamic risk: %s", reason
                )
                return False, reason

        return True, "ALL_PASSED"

    # ------------------------------------------------------------------
    # Stop-loss sweep
    # ------------------------------------------------------------------

    def check_stop_losses(
        self, positions: list[dict]
    ) -> list[dict[str, str]]:
        """Check all positions for stop-loss triggers.

        Parameters
        ----------
        positions:
            List of position dicts -- each must satisfy the schema
            expected by :meth:`StopLossChecker.check`.

        Returns
        -------
        list[dict[str, str]]
            A list of dicts ``{"symbol": ..., "market": ...,
            "stop_type": ...}`` for every position that triggered a
            stop.  Empty list if nothing triggered.
        """
        triggered: list[dict[str, str]] = []
        for pos in positions:
            stop_type = self._stop_loss_checker.check(pos)
            if stop_type is not None:
                triggered.append(
                    {
                        "symbol": pos.get("symbol", "UNKNOWN"),
                        "market": pos.get("market", "unknown"),
                        "stop_type": stop_type,
                    }
                )
        return triggered

    # ------------------------------------------------------------------
    # Status summary
    # ------------------------------------------------------------------

    def get_risk_status(self, portfolio: dict) -> dict:
        """Return a summary dict suitable for daily briefings or dashboards.

        Parameters
        ----------
        portfolio:
            Current portfolio state.

        Returns
        -------
        dict
            Keys include ``kill_switch``, ``daily_pnl_pct``,
            ``weekly_pnl_pct``, ``drawdown_pct``, ``open_positions``,
            ``cash_reserve_pct``, and ``position_size_modifier``.
        """
        total_value: float = portfolio.get("total_value", 0.0)
        cash: float = portfolio.get("cash", 0.0)
        cash_pct = (cash / total_value) if total_value > 0 else 0.0

        return {
            "kill_switch": self._kill_switch.get_status(),
            "daily_pnl_pct": portfolio.get("daily_pnl_pct", 0.0),
            "weekly_pnl_pct": portfolio.get("weekly_pnl_pct", 0.0),
            "drawdown_pct": portfolio.get("drawdown_pct", 0.0),
            "open_positions": portfolio.get("open_position_count", 0),
            "max_positions": self._hard_limit_checker._max_total_positions,
            "cash_reserve_pct": round(cash_pct, 4),
            "min_cash_reserve_pct": self._hard_limit_checker._min_cash_reserve_pct,
        }


# ======================================================================
# In-memory Redis fallback (for testing / single-process use)
# ======================================================================


class _InMemoryRedis:
    """Minimal in-memory store that satisfies the :class:`KillSwitch`
    interface.  Used when no real Redis client is provided."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._store[key] = value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
