"""Emergency kill switch -- immediately halts all trading activity.

The kill switch is backed by Redis so that the state is visible across
all processes.  **Deactivation is manual-only** -- automatic reset is
explicitly not supported to ensure a human reviews the situation before
trading resumes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class _RedisLike(Protocol):
    """Minimal interface expected from the Redis client."""

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int | None = None) -> None: ...
    def delete(self, key: str) -> None: ...


class KillSwitch:
    """Emergency kill switch for the trading system.

    State is stored in Redis under the ``kill_switch:*`` key namespace:

    - ``kill_switch:active`` -- ``"true"`` when activated
    - ``kill_switch:reason`` -- human-readable activation reason
    - ``kill_switch:activated_at`` -- ISO-8601 UTC timestamp
    - ``kill_switch:deactivated_by`` -- who deactivated (after reset)

    Parameters
    ----------
    redis_client:
        An object exposing ``.get()``, ``.set()``, and ``.delete()``
        methods (e.g. :class:`~claude_impl.infrastructure.redis_client.RedisClient`).
    config:
        The ``risk.kill_switch`` section from the application config.
    """

    # ------------------------------------------------------------------
    # Auto-trigger conditions
    # ------------------------------------------------------------------

    AUTO_TRIGGERS: list[str] = [
        "daily_loss_exceeded",
        "mdd_exceeded",
        "api_consecutive_failures",
        "data_gap_minutes",
    ]

    # Redis key constants
    _KEY_ACTIVE = "kill_switch:active"
    _KEY_REASON = "kill_switch:reason"
    _KEY_ACTIVATED_AT = "kill_switch:activated_at"
    _KEY_DEACTIVATED_BY = "kill_switch:deactivated_by"

    def __init__(self, redis_client: Any, config: dict | None = None) -> None:
        self._redis: _RedisLike = redis_client
        self._config = config or {}
        # Parse auto-trigger thresholds from config if present.
        auto_triggers_cfg: list[str] = self._config.get("auto_triggers", [])
        self._auto_trigger_thresholds = self._parse_trigger_thresholds(
            auto_triggers_cfg
        )

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def activate(self, reason: str) -> None:
        """Activate the kill switch.

        This:
        1. Sets ``kill_switch:active`` to ``"true"`` in Redis.
        2. Records the reason and activation timestamp.
        3. Logs a CRITICAL-level message.

        Callers are responsible for cancelling pending orders and sending
        alerts (e.g. Telegram) -- this class focuses purely on the
        state flag.
        """
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        self._redis.set(self._KEY_ACTIVE, "true")
        self._redis.set(self._KEY_REASON, reason)
        self._redis.set(self._KEY_ACTIVATED_AT, now_iso)
        # Clear any prior deactivation record.
        self._redis.delete(self._KEY_DEACTIVATED_BY)

        logger.critical(
            "KILL SWITCH ACTIVATED -- reason: %s -- at: %s",
            reason,
            now_iso,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def is_active(self) -> bool:
        """Return ``True`` if the kill switch is currently engaged."""
        return self._redis.get(self._KEY_ACTIVE) == "true"

    def get_reason(self) -> str | None:
        """Return the activation reason, or ``None`` if not active."""
        if not self.is_active():
            return None
        return self._redis.get(self._KEY_REASON)

    def get_status(self) -> dict[str, str | None]:
        """Return a full status snapshot for monitoring / briefing."""
        return {
            "active": self._redis.get(self._KEY_ACTIVE),
            "reason": self._redis.get(self._KEY_REASON),
            "activated_at": self._redis.get(self._KEY_ACTIVATED_AT),
            "deactivated_by": self._redis.get(self._KEY_DEACTIVATED_BY),
        }

    # ------------------------------------------------------------------
    # Deactivation (manual only)
    # ------------------------------------------------------------------

    def deactivate(self, confirmed_by: str) -> None:
        """Manually deactivate the kill switch.

        Parameters
        ----------
        confirmed_by:
            Identifier of the person who confirmed the deactivation
            (e.g. username, email, or Telegram handle).  This is
            recorded for audit purposes.

        Raises
        ------
        RuntimeError
            If the kill switch is not currently active.
        """
        if not self.is_active():
            raise RuntimeError(
                "Cannot deactivate kill switch -- it is not currently active."
            )

        previous_reason = self._redis.get(self._KEY_REASON)
        activated_at = self._redis.get(self._KEY_ACTIVATED_AT)
        now_iso = datetime.now(tz=timezone.utc).isoformat()

        self._redis.set(self._KEY_ACTIVE, "false")
        self._redis.set(self._KEY_DEACTIVATED_BY, confirmed_by)

        logger.warning(
            "KILL SWITCH DEACTIVATED -- confirmed_by: %s -- "
            "was active since: %s -- reason was: %s -- deactivated at: %s",
            confirmed_by,
            activated_at,
            previous_reason,
            now_iso,
        )

    # ------------------------------------------------------------------
    # Auto-trigger evaluation
    # ------------------------------------------------------------------

    def check_auto_triggers(
        self, portfolio: dict, system_state: dict
    ) -> None:
        """Evaluate automatic trigger conditions and activate if any are met.

        This method is meant to be called periodically (e.g. every
        health-check cycle).  If the kill switch is already active it
        returns immediately.

        Parameters
        ----------
        portfolio:
            Portfolio state dict with at least:

            - ``daily_pnl_pct`` -- decimal (e.g. ``-0.04``)
            - ``drawdown_pct`` -- decimal (e.g. ``-0.16``)

        system_state:
            System health dict with at least:

            - ``api_consecutive_failures`` -- int
            - ``data_gap_minutes`` -- float, minutes since last data
        """
        if self.is_active():
            return

        # -- daily_loss_exceeded ------------------------------------------
        daily_pnl: float = portfolio.get("daily_pnl_pct", 0.0)
        threshold_daily: float = self._auto_trigger_thresholds.get(
            "daily_loss_exceeded", -0.03
        )
        if daily_pnl <= threshold_daily:
            self.activate(
                f"daily_loss_exceeded: daily PnL {daily_pnl:.2%} "
                f"<= {threshold_daily:.2%}"
            )
            return

        # -- mdd_exceeded -------------------------------------------------
        drawdown: float = portfolio.get("drawdown_pct", 0.0)
        threshold_mdd: float = self._auto_trigger_thresholds.get(
            "mdd_exceeded", -0.15
        )
        if drawdown <= threshold_mdd:
            self.activate(
                f"mdd_exceeded: drawdown {drawdown:.2%} "
                f"<= {threshold_mdd:.2%}"
            )
            return

        # -- api_consecutive_failures -------------------------------------
        api_failures: int = system_state.get("api_consecutive_failures", 0)
        threshold_api: int = int(
            self._auto_trigger_thresholds.get(
                "api_consecutive_failures", 5
            )
        )
        if api_failures >= threshold_api:
            self.activate(
                f"api_consecutive_failures: {api_failures} >= {threshold_api}"
            )
            return

        # -- data_gap_minutes ---------------------------------------------
        data_gap: float = system_state.get("data_gap_minutes", 0.0)
        threshold_gap: float = float(
            self._auto_trigger_thresholds.get("data_gap_minutes", 30)
        )
        if data_gap >= threshold_gap:
            self.activate(
                f"data_gap_minutes: {data_gap:.1f} min >= {threshold_gap:.1f} min"
            )
            return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_trigger_thresholds(
        trigger_list: list[str],
    ) -> dict[str, float]:
        """Parse the YAML auto_triggers list into a threshold dict.

        Entries can be plain names (``"daily_loss_exceeded"``) or
        ``"key: value"`` pairs (``"api_consecutive_failures: 5"``).
        Plain names receive their default thresholds.
        """
        defaults: dict[str, float] = {
            "daily_loss_exceeded": -0.03,
            "mdd_exceeded": -0.15,
            "api_consecutive_failures": 5,
            "data_gap_minutes": 30,
        }
        result: dict[str, float] = dict(defaults)
        for entry in trigger_list:
            if ":" in entry:
                key, _, val = entry.partition(":")
                key = key.strip()
                try:
                    result[key] = float(val.strip())
                except ValueError:
                    logger.warning(
                        "Ignoring unparseable auto_trigger value: %s", entry
                    )
            # else: use default -- already in *result*
        return result
