"""Telegram notification client for monitoring and alerting.

Configuration keys consumed from the *config* dict::

    notification.telegram.bot_token     -- Telegram Bot API token
    notification.telegram.chat_id       -- target chat / channel ID
    notification.telegram.quiet_hours   -- dict with ``start`` and ``end``
                                           times in ``"HH:MM"`` format (KST)

Based on the 09-monitoring design document.  Uses ``httpx`` for HTTP
calls; falls back to ``urllib`` from the standard library if httpx is
not installed.

Quiet hours (default 00:00 -- 06:00 KST) suppress regular messages.
Critical alerts sent via :meth:`send_alert` **always** go through
regardless of quiet hours (e.g. kill-switch notifications).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# KST = UTC+9
_KST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# Conditional import of httpx (preferred) with urllib fallback
# ---------------------------------------------------------------------------
try:
    import httpx

    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False
    logger.info(
        "httpx is not installed. TelegramNotifier will use urllib as a fallback."
    )


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


def _post_with_urllib(url: str, payload: dict) -> int:
    """Send a POST request using only the standard library.

    Returns the HTTP status code, or ``0`` on failure.
    """
    import json
    import urllib.request
    import urllib.error

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        logger.warning("Telegram API HTTP error: %s", exc)
        return exc.code
    except Exception:
        logger.warning("Telegram API request failed (urllib).", exc_info=True)
        return 0


class TelegramNotifier:
    """Send messages via the Telegram Bot API.

    Handles quiet-hours suppression for routine messages and provides a
    separate :meth:`send_alert` path that bypasses quiet hours for
    urgent notifications (kill switch, system failures, cost warnings).
    """

    # Telegram Bot API imposes a per-message limit of 4096 characters.
    _MAX_MESSAGE_LENGTH = 4096

    def __init__(self, config: dict) -> None:
        self._bot_token: str = _nested_get(
            config, "notification.telegram.bot_token", ""
        )
        self._chat_id: str = str(
            _nested_get(config, "notification.telegram.chat_id", "")
        )
        quiet = _nested_get(config, "notification.telegram.quiet_hours", {})
        self._quiet_start: str = quiet.get("start", "00:00") if isinstance(quiet, dict) else "00:00"
        self._quiet_end: str = quiet.get("end", "06:00") if isinstance(quiet, dict) else "06:00"

        self._base_url: str = f"https://api.telegram.org/bot{self._bot_token}"

        if not self._bot_token:
            logger.warning(
                "TelegramNotifier: bot_token is empty. Messages will not be sent."
            )
        if not self._chat_id:
            logger.warning(
                "TelegramNotifier: chat_id is empty. Messages will not be sent."
            )

    # -- helpers -------------------------------------------------------------

    @property
    def _configured(self) -> bool:
        return bool(self._bot_token) and bool(self._chat_id)

    def _is_quiet_hours(self) -> bool:
        """Check whether the current KST time falls within quiet hours.

        Quiet hours wrap around midnight when *start* > *end* (e.g.
        23:00 -- 06:00).
        """
        try:
            now_kst = datetime.now(tz=_KST)
            current = now_kst.hour * 60 + now_kst.minute

            sh, sm = (int(x) for x in self._quiet_start.split(":"))
            eh, em = (int(x) for x in self._quiet_end.split(":"))
            start_minutes = sh * 60 + sm
            end_minutes = eh * 60 + em

            if start_minutes <= end_minutes:
                # e.g. 00:00 -- 06:00
                return start_minutes <= current < end_minutes
            else:
                # wraps midnight, e.g. 23:00 -- 06:00
                return current >= start_minutes or current < end_minutes
        except Exception:
            logger.warning("Failed to evaluate quiet hours.", exc_info=True)
            return False

    def _do_send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Low-level send that posts to the Telegram Bot API.

        Returns ``True`` on success.
        """
        if not self._configured:
            logger.warning("TelegramNotifier: not configured, message dropped.")
            return False

        # Truncate overly long messages to stay within Telegram limits.
        if len(message) > self._MAX_MESSAGE_LENGTH:
            truncation_notice = "\n\n... [message truncated]"
            max_body = self._MAX_MESSAGE_LENGTH - len(truncation_notice)
            message = message[:max_body] + truncation_notice

        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }

        try:
            if _HAS_HTTPX:
                response = httpx.post(url, json=payload, timeout=10.0)
                status = response.status_code
            else:
                status = _post_with_urllib(url, payload)

            if 200 <= status < 300:
                logger.debug("Telegram message sent successfully (status=%d).", status)
                return True
            else:
                logger.warning(
                    "Telegram API returned non-2xx status: %d", status
                )
                return False
        except Exception:
            logger.warning("Failed to send Telegram message.", exc_info=True)
            return False

    # -- public API ----------------------------------------------------------

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message, respecting quiet hours.

        During quiet hours the message is silently dropped (logged at
        DEBUG level).  Returns ``True`` if the message was actually
        sent.
        """
        if self._is_quiet_hours():
            logger.debug(
                "TelegramNotifier: quiet hours active, message suppressed."
            )
            return False

        return self._do_send(message, parse_mode)

    def send_alert(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send an urgent alert that **bypasses** quiet hours.

        Use this for kill-switch activations, system failures, and cost
        warnings -- anything that must reach the operator immediately.
        """
        return self._do_send(message, parse_mode)
