"""Stop-loss strategies -- fixed, trailing, and time-based.

Each position is evaluated against three independent stop conditions.
The first triggered stop (if any) dictates the exit reason.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _cfg(config: dict, key: str, default: Any = None) -> Any:
    return config.get(key, default)


class StopLossChecker:
    """Evaluate stop-loss conditions for individual positions.

    Parameters
    ----------
    config:
        The ``risk.stop_loss`` section from the application config::

            {
                "fixed_pct": -0.05,
                "trailing_pct": -0.03,
                "time_days": 5,
                "time_loss_pct": -0.02,
            }
    """

    def __init__(self, config: dict) -> None:
        self._fixed_pct: float = _cfg(config, "fixed_pct", -0.05)
        self._trailing_pct: float = _cfg(config, "trailing_pct", -0.03)
        self._time_days: int = _cfg(config, "time_days", 5)
        self._time_loss_pct: float = _cfg(config, "time_loss_pct", -0.02)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, position: dict) -> str | None:
        """Check whether *position* triggers any stop-loss condition.

        Returns the stop type string on the first match, or ``None``
        if no stop is triggered.

        Parameters
        ----------
        position:
            A dict describing the current position.  Expected keys:

            - ``symbol`` -- ticker symbol (for logging)
            - ``entry_price`` -- average cost / entry price
            - ``current_price`` -- latest market price
            - ``peak_price`` -- highest price observed while holding
            - ``opened_at`` -- ISO-8601 timestamp when the position was
              opened

        Returns
        -------
        str | None
            One of ``"FIXED_STOP"``, ``"TRAILING_STOP"``,
            ``"TIME_STOP"``, or ``None``.
        """
        symbol: str = position.get("symbol", "UNKNOWN")
        entry_price: float = position.get("entry_price", 0.0)
        current_price: float = position.get("current_price", 0.0)
        peak_price: float = position.get("peak_price", 0.0)

        if entry_price <= 0 or current_price <= 0:
            logger.warning(
                "StopLossChecker: invalid prices for %s "
                "(entry=%.4f, current=%.4f) -- skipping",
                symbol,
                entry_price,
                current_price,
            )
            return None

        # -- Fixed stop: current vs entry ---------------------------------
        pnl_pct = (current_price - entry_price) / entry_price
        if pnl_pct <= self._fixed_pct:
            logger.info(
                "FIXED_STOP triggered for %s: pnl %.2f%% <= %.2f%%",
                symbol,
                pnl_pct * 100,
                self._fixed_pct * 100,
            )
            return "FIXED_STOP"

        # -- Trailing stop: current vs peak -------------------------------
        if peak_price > 0:
            drop_from_peak = (current_price - peak_price) / peak_price
            if drop_from_peak <= self._trailing_pct:
                logger.info(
                    "TRAILING_STOP triggered for %s: drop from peak "
                    "%.2f%% <= %.2f%%",
                    symbol,
                    drop_from_peak * 100,
                    self._trailing_pct * 100,
                )
                return "TRAILING_STOP"

        # -- Time stop: held too long with a loss -------------------------
        opened_at_raw: str | None = position.get("opened_at")
        if opened_at_raw is not None:
            try:
                opened_dt = datetime.fromisoformat(opened_at_raw)
                if opened_dt.tzinfo is None:
                    opened_dt = opened_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                opened_dt = None

            if opened_dt is not None:
                now_utc = datetime.now(tz=timezone.utc)
                days_held = (now_utc - opened_dt).days
                if days_held >= self._time_days and pnl_pct <= self._time_loss_pct:
                    logger.info(
                        "TIME_STOP triggered for %s: held %d days "
                        "(>= %d) with pnl %.2f%% (<= %.2f%%)",
                        symbol,
                        days_held,
                        self._time_days,
                        pnl_pct * 100,
                        self._time_loss_pct * 100,
                    )
                    return "TIME_STOP"

        return None

    # ------------------------------------------------------------------
    # Price calculation helper
    # ------------------------------------------------------------------

    def calculate_stop_prices(
        self, entry_price: float, peak_price: float
    ) -> dict[str, float]:
        """Compute the absolute stop prices for a given entry and peak.

        Returns
        -------
        dict
            ``{"fixed_stop_price": ..., "trailing_stop_price": ...}``

            Either value may be ``0.0`` if the input is invalid.
        """
        fixed_stop: float = 0.0
        trailing_stop: float = 0.0

        if entry_price > 0:
            fixed_stop = round(entry_price * (1.0 + self._fixed_pct), 4)

        if peak_price > 0:
            trailing_stop = round(peak_price * (1.0 + self._trailing_pct), 4)

        return {
            "fixed_stop_price": fixed_stop,
            "trailing_stop_price": trailing_stop,
        }
