"""Alert rules and notification dispatch for the Stock Trading System.

Implements the alert rules defined in the 09-monitoring design document:

- **Data health**: collection gap > 15 minutes triggers a warning.
- **Trading health**: daily loss > -2% warning, > -3% kill-switch trigger.
- **System health**: Redis memory > 200 MB warning, LLM cost > $7/day
  model-switch warning.
- **Trade signals and risk warnings** are formatted and forwarded to
  a Telegram notifier.
- **Kill-switch alerts** always send (bypass quiet hours).

The ``AlertManager`` expects an optional Telegram client that exposes
``.send(message)`` and ``.send_alert(message)`` methods (matching
:class:`claude_impl.infrastructure.telegram_client.TelegramNotifier`).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# KST = UTC+9
_KST = timezone(timedelta(hours=9))


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


class AlertManager:
    """Evaluate alert rules and dispatch notifications.

    Parameters
    ----------
    config:
        System configuration dict.  Keys consumed:

        - ``alerts.data_gap_minutes`` -- collection gap threshold
          (default 15).
        - ``alerts.daily_loss_warning_pct`` -- daily loss warning
          threshold (default -2.0).
        - ``alerts.daily_loss_kill_pct`` -- daily loss kill-switch
          threshold (default -3.0).
        - ``alerts.redis_memory_warning_mb`` -- Redis memory warning
          threshold (default 200).
        - ``alerts.llm_daily_cost_warning_usd`` -- LLM cost warning
          threshold (default 7.0).
    telegram_client:
        An object with ``.send()`` and ``.send_alert()`` methods.
        If ``None``, alerts are logged but not dispatched.
    """

    def __init__(
        self,
        config: dict,
        telegram_client: Any | None = None,
    ) -> None:
        self._config = config
        self._telegram = telegram_client

        # Thresholds (with sensible defaults from the design doc)
        self._data_gap_minutes: float = float(
            _nested_get(config, "alerts.data_gap_minutes", 15)
        )
        self._daily_loss_warning_pct: float = float(
            _nested_get(config, "alerts.daily_loss_warning_pct", -2.0)
        )
        self._daily_loss_kill_pct: float = float(
            _nested_get(config, "alerts.daily_loss_kill_pct", -3.0)
        )
        self._redis_memory_warning_mb: float = float(
            _nested_get(config, "alerts.redis_memory_warning_mb", 200)
        )
        self._llm_cost_warning_usd: float = float(
            _nested_get(config, "alerts.llm_daily_cost_warning_usd", 7.0)
        )

    # -- internal dispatch ---------------------------------------------------

    def _send(self, message: str) -> bool:
        """Send a routine message (respects quiet hours)."""
        if self._telegram is not None:
            return self._telegram.send(message)
        logger.info("Alert (no telegram): %s", message)
        return False

    def _send_alert(self, message: str) -> bool:
        """Send an urgent alert (bypasses quiet hours)."""
        if self._telegram is not None:
            return self._telegram.send_alert(message)
        logger.warning("Urgent alert (no telegram): %s", message)
        return False

    # -- data health ---------------------------------------------------------

    def check_data_health(self, last_collection_times: dict[str, datetime]) -> list[str]:
        """Check for stale data collection sources.

        Parameters
        ----------
        last_collection_times:
            Mapping of source identifier (e.g. ``"KR_news"``, ``"US_price"``)
            to the :class:`~datetime.datetime` of their last successful
            collection.

        Returns
        -------
        list[str]
            List of alert messages that were dispatched.
        """
        now = datetime.now(tz=timezone.utc)
        alerts: list[str] = []

        for source, last_time in last_collection_times.items():
            # Ensure timezone-aware comparison
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)

            gap_minutes = (now - last_time).total_seconds() / 60.0

            if gap_minutes > self._data_gap_minutes:
                gap_formatted = f"{gap_minutes:.1f}"
                msg = (
                    f"\u26a0\ufe0f Data Collection Alert\n"
                    f"Source: {source}\n"
                    f"Last collection: {gap_formatted}min ago\n"
                    f"Threshold: {self._data_gap_minutes:.0f}min\n"
                    f"Action: Check collector health"
                )
                self._send(msg)
                alerts.append(msg)
                logger.warning(
                    "Data gap alert: %s last collected %.1f minutes ago",
                    source,
                    gap_minutes,
                )

        return alerts

    # -- trading health ------------------------------------------------------

    def check_trading_health(self, portfolio: dict) -> list[str]:
        """Check portfolio for daily loss thresholds.

        Parameters
        ----------
        portfolio:
            Dict with at least ``daily_pnl_pct`` (float), and optionally
            ``position_count`` (int) and ``pending_orders`` (int).

        Returns
        -------
        list[str]
            List of alert messages that were dispatched.
        """
        daily_pnl_pct: float = float(portfolio.get("daily_pnl_pct", 0.0))
        position_count: int = int(portfolio.get("position_count", 0))
        alerts: list[str] = []

        # Kill switch: daily loss exceeds kill threshold
        if daily_pnl_pct <= self._daily_loss_kill_pct:
            reason = (
                f"Daily loss limit exceeded ({daily_pnl_pct:+.1f}%, "
                f"limit {self._daily_loss_kill_pct:+.1f}%)"
            )
            self.send_kill_switch_alert(reason)
            alerts.append(reason)
            return alerts

        # Warning: daily loss exceeds warning threshold
        if daily_pnl_pct <= self._daily_loss_warning_pct:
            remaining = self._daily_loss_kill_pct - daily_pnl_pct
            msg = (
                f"\u26a0\ufe0f Daily Loss Warning\n"
                f"Daily P&L: {daily_pnl_pct:+.1f}% "
                f"(limit {self._daily_loss_kill_pct:+.1f}%)\n"
                f"Remaining: {remaining:+.1f}%\n"
                f"Positions: {position_count}"
            )
            self._send(msg)
            alerts.append(msg)
            logger.warning(
                "Trading health warning: daily PnL %.1f%%",
                daily_pnl_pct,
            )

        return alerts

    # -- system health -------------------------------------------------------

    def check_system_health(self, system_state: dict) -> list[str]:
        """Check system resource usage.

        Parameters
        ----------
        system_state:
            Dict with optional keys:

            - ``redis_memory_mb`` (float)
            - ``llm_daily_cost_usd`` (float)

        Returns
        -------
        list[str]
            List of alert messages that were dispatched.
        """
        alerts: list[str] = []

        # Redis memory
        redis_mb = float(system_state.get("redis_memory_mb", 0.0))
        if redis_mb > self._redis_memory_warning_mb:
            msg = (
                f"\u26a0\ufe0f Redis Memory Warning\n"
                f"Current: {redis_mb:.0f} MB\n"
                f"Threshold: {self._redis_memory_warning_mb:.0f} MB\n"
                f"Action: Consider evicting stale cache entries"
            )
            self._send(msg)
            alerts.append(msg)
            logger.warning("Redis memory warning: %.0f MB", redis_mb)

        # LLM daily cost
        llm_cost = float(system_state.get("llm_daily_cost_usd", 0.0))
        if llm_cost > self._llm_cost_warning_usd:
            msg = (
                f"\u26a0\ufe0f LLM Cost Warning\n"
                f"Today's cost: ${llm_cost:.2f}\n"
                f"Threshold: ${self._llm_cost_warning_usd:.2f}\n"
                f"Action: Consider switching to a cheaper model"
            )
            self._send(msg)
            alerts.append(msg)
            logger.warning("LLM cost warning: $%.2f", llm_cost)

        return alerts

    # -- trade signal --------------------------------------------------------

    def send_trade_signal(self, signal: dict) -> bool:
        """Format and send a trade signal notification.

        Parameters
        ----------
        signal:
            Dict with keys: ``decision``, ``symbol``, ``name`` (optional),
            ``score``, ``confidence``, ``sentiment``, ``technical``,
            ``size_display``, ``size_pct``.

        Returns
        -------
        bool
            ``True`` if the message was dispatched.
        """
        decision = signal.get("decision", "HOLD")
        symbol = signal.get("symbol", "???")
        name = signal.get("name", "")
        score = float(signal.get("score", 0.0))
        confidence = float(signal.get("confidence", 0.0))
        sentiment = float(signal.get("sentiment", 0.0))
        technical = float(signal.get("technical", 0.0))
        size_display = signal.get("size_display", "")
        size_pct = signal.get("size_pct", 0)

        # Emoji based on decision type
        emoji_map = {"BUY": "\U0001f7e2", "SELL": "\U0001f534", "HOLD": "\u26aa"}
        emoji = emoji_map.get(decision, "\u2753")

        name_part = f" {name}" if name else ""
        msg = (
            f"{emoji} {decision} {symbol}{name_part}\n"
            f"Score: {score:.2f} | Confidence: {confidence:.2f}\n"
            f"Sentiment: {sentiment:+.2f} | Technical: {technical:+.2f}\n"
            f"Size: {size_display} ({size_pct}%)"
        )
        return self._send(msg)

    # -- risk warning --------------------------------------------------------

    def send_risk_warning(self, warning: dict) -> bool:
        """Format and send a risk warning notification.

        Parameters
        ----------
        warning:
            Dict with keys: ``daily_pnl_pct``, ``daily_limit_pct``,
            ``remaining_pct``, ``position_count``.

        Returns
        -------
        bool
            ``True`` if the message was dispatched.
        """
        daily_pnl_pct = float(warning.get("daily_pnl_pct", 0.0))
        daily_limit_pct = float(warning.get("daily_limit_pct", -3.0))
        remaining_pct = float(warning.get("remaining_pct", 0.0))
        position_count = int(warning.get("position_count", 0))

        msg = (
            f"\u26a0\ufe0f Risk Warning\n"
            f"Daily P&L: {daily_pnl_pct:+.1f}% "
            f"(limit {daily_limit_pct:+.1f}%)\n"
            f"Remaining: {remaining_pct:.1f}%\n"
            f"Positions: {position_count}"
        )
        return self._send(msg)

    # -- kill switch ---------------------------------------------------------

    def send_kill_switch_alert(self, reason: str) -> bool:
        """Send an urgent kill-switch notification.

        This alert **always** sends, bypassing quiet hours, because it
        indicates a critical state requiring immediate operator attention.

        Parameters
        ----------
        reason:
            Human-readable description of why the kill switch was triggered.

        Returns
        -------
        bool
            ``True`` if the message was dispatched.
        """
        msg = (
            f"\U0001f6a8 KILL SWITCH ACTIVATED\n"
            f"Reason: {reason}\n"
            f"Action: All pending orders cancelled\n"
            f"Status: New trades fully blocked\n"
            f"Recovery: Manual confirmation required"
        )
        logger.critical("Kill switch triggered: %s", reason)
        return self._send_alert(msg)
