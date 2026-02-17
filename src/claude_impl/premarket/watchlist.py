"""Daily watchlist generation based on overnight sentiment and events.

Implements the watchlist scoring algorithm from the 05-pre-market design
document::

    score = abs(sentiment_change) * 0.4
          + volume_signal        * 0.3
          + event_today          * 0.3

Symbols with ``score > 0.3`` are included; the top 10 are returned
sorted by score descending.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default scoring weights (overridable via config)
_DEFAULT_WEIGHTS: dict[str, float] = {
    "sentiment_change": 0.4,
    "volume_signal": 0.3,
    "event_today": 0.3,
}

_DEFAULT_SCORE_THRESHOLD: float = 0.3
_DEFAULT_MAX_WATCHLIST_SIZE: int = 10


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


class WatchlistGenerator:
    """Scores and ranks symbols for the daily pre-market watchlist.

    Parameters
    ----------
    config:
        Application configuration dict.  Recognised keys:

        * ``premarket.watchlist.weights.sentiment_change`` (float)
        * ``premarket.watchlist.weights.volume_signal`` (float)
        * ``premarket.watchlist.weights.event_today`` (float)
        * ``premarket.watchlist.score_threshold`` (float)
        * ``premarket.watchlist.max_size`` (int)
    """

    def __init__(self, config: dict) -> None:
        weights_cfg = _nested_get(config, "premarket.watchlist.weights", {})
        self._weights: dict[str, float] = {
            "sentiment_change": float(
                weights_cfg.get("sentiment_change", _DEFAULT_WEIGHTS["sentiment_change"])
            ),
            "volume_signal": float(
                weights_cfg.get("volume_signal", _DEFAULT_WEIGHTS["volume_signal"])
            ),
            "event_today": float(
                weights_cfg.get("event_today", _DEFAULT_WEIGHTS["event_today"])
            ),
        }
        self._score_threshold: float = float(
            _nested_get(config, "premarket.watchlist.score_threshold", _DEFAULT_SCORE_THRESHOLD)
        )
        self._max_size: int = int(
            _nested_get(config, "premarket.watchlist.max_size", _DEFAULT_MAX_WATCHLIST_SIZE)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        market: str,
        sentiment_changes: list[dict],
        events: list[dict] | None = None,
    ) -> list[dict]:
        """Generate the daily watchlist for *market*.

        Parameters
        ----------
        market:
            ``"KR"`` or ``"US"``.
        sentiment_changes:
            List of dicts with at least ``symbol``, ``change``, and
            optionally ``volume_signal`` (0.0--1.0).  Typically produced
            by ``PreMarketRoutine.compute_overnight_sentiment``.
        events:
            Optional list of event-calendar entries.  Each dict should
            contain a ``symbols`` key (list of symbols the event applies
            to) and a ``description`` field.

        Returns
        -------
        list[dict]
            Up to 10 entries sorted by score descending.  Each entry::

                {
                    "symbol": str,
                    "score": float,
                    "sentiment": dict,   # the matching sentiment_changes entry
                    "event": dict | None,
                }
        """
        events = events or []
        event_symbol_map = self._build_event_map(events)

        candidates: list[dict] = []
        for entry in sentiment_changes:
            symbol: str = entry.get("symbol", "")
            if not symbol:
                continue

            sentiment_change_abs = abs(entry.get("change", 0.0))
            volume_signal = float(entry.get("volume_signal", 0.0))
            has_event = symbol in event_symbol_map

            score = (
                sentiment_change_abs * self._weights["sentiment_change"]
                + volume_signal * self._weights["volume_signal"]
                + (1.0 if has_event else 0.0) * self._weights["event_today"]
            )

            if score <= self._score_threshold:
                continue

            candidates.append({
                "symbol": symbol,
                "score": round(score, 4),
                "sentiment": entry,
                "event": event_symbol_map.get(symbol),
            })

        # Sort by score descending, take top N
        candidates.sort(key=lambda c: c["score"], reverse=True)
        watchlist = candidates[: self._max_size]

        logger.info(
            "Watchlist for %s: %d candidates scored, %d passed threshold, returning top %d.",
            market,
            len(sentiment_changes),
            len(candidates),
            len(watchlist),
        )
        return watchlist

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_event_map(events: list[dict]) -> dict[str, dict]:
        """Build a symbol -> first matching event lookup dict.

        Each event dict is expected to have a ``symbols`` key containing
        a list of ticker strings.  If multiple events affect the same
        symbol, the first one encountered wins.
        """
        event_map: dict[str, dict] = {}
        for event in events:
            symbols = event.get("symbols", [])
            if isinstance(symbols, str):
                symbols = [symbols]
            for sym in symbols:
                if sym and sym not in event_map:
                    event_map[sym] = event
        return event_map
