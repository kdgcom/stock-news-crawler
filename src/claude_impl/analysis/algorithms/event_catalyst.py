"""Event Catalyst (EC) algorithm.

Scores specific event types (earnings, M&A, regulation, product
launch, etc.) with time decay and confidence weighting.  Only events
within the ``reaction_window_minutes`` and above
``min_event_confidence`` are considered.

Best suited for:
    * Earnings season
    * M&A / regulatory / product-launch announcements

Config keys (``algorithms.event_catalyst``)::

    reaction_window_minutes   -- max event age in minutes
    min_event_confidence      -- minimum confidence on the event itself
    event_weights             -- dict mapping event_type -> base weight
    fade_after_hours          -- hours until the event effect fully fades
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..base_algorithm import BaseAlgorithm
from ...models.signal import AlgorithmContext, Signal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventCatalyst(BaseAlgorithm):
    """Event type scoring with time decay and confidence weighting."""

    @property
    def name(self) -> str:
        return "event_catalyst"

    def required_data(self) -> list[str]:
        return ["news_events"]

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        cfg = self.config
        now = _utcnow()

        reaction_window: float = cfg.get("reaction_window_minutes", 120)
        min_confidence: float = cfg.get("min_event_confidence", 0.5)

        # Filter to recent, high-confidence events
        recent_events: list[dict] = []
        for e in ctx.news_events:
            analyzed_at = e.get("analyzed_at_utc")
            if analyzed_at is None:
                continue
            if isinstance(analyzed_at, str):
                try:
                    analyzed_at = datetime.fromisoformat(analyzed_at)
                except ValueError:
                    continue
            if analyzed_at.tzinfo is None:
                analyzed_at = analyzed_at.replace(tzinfo=timezone.utc)

            minutes_ago = (now - analyzed_at).total_seconds() / 60
            if minutes_ago <= reaction_window and e.get("confidence", 0) >= min_confidence:
                recent_events.append(e)

        if not recent_events:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="HOLD",
                score=0.0,
                confidence=0.2,
                algorithm=self.name,
                reason_codes=["NO_RECENT_EVENT"],
                details={},
            )

        # --- Score each event -----------------------------------------
        event_weights: dict[str, float] = cfg.get("event_weights", {})
        fade_hours: float = cfg.get("fade_after_hours", 4.0)

        event_scores: list[dict] = []
        for event in recent_events:
            event_type: str = event.get("event_type", "unknown")
            base_weight = event_weights.get(event_type, 0.0)
            if base_weight == 0.0:
                continue

            analyzed_at = event.get("analyzed_at_utc")
            if isinstance(analyzed_at, str):
                analyzed_at = datetime.fromisoformat(analyzed_at)
            if analyzed_at.tzinfo is None:  # type: ignore[union-attr]
                analyzed_at = analyzed_at.replace(tzinfo=timezone.utc)  # type: ignore[union-attr]

            minutes_ago = (now - analyzed_at).total_seconds() / 60  # type: ignore[operator]
            time_factor = max(0.0, 1.0 - minutes_ago / (fade_hours * 60))

            score = base_weight * time_factor * event.get("confidence", 0.5)
            event_scores.append({
                "type": event_type,
                "score": round(score, 4),
                "event_id": event.get("event_id", ""),
            })

        if not event_scores:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="HOLD",
                score=0.0,
                confidence=0.3,
                algorithm=self.name,
                reason_codes=["NO_SCORED_EVENTS"],
                details={},
            )

        total_score = sum(e["score"] for e in event_scores)
        strongest = max(event_scores, key=lambda e: abs(e["score"]))

        details = {"events": event_scores, "total_score": round(total_score, 4)}

        if total_score > 0.3:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="BUY",
                score=min(total_score, 1.0),
                confidence=min(abs(total_score), 1.0),
                algorithm=self.name,
                reason_codes=[f"EVENT_{strongest['type'].upper()}"],
                details=details,
            )

        if total_score < -0.3:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="SELL",
                score=max(total_score, -1.0),
                confidence=min(abs(total_score), 1.0),
                algorithm=self.name,
                reason_codes=[f"EVENT_{strongest['type'].upper()}"],
                details=details,
            )

        return Signal(
            symbol=ctx.symbol,
            market=ctx.market,
            decision="HOLD",
            score=total_score,
            confidence=min(abs(total_score), 1.0),
            algorithm=self.name,
            reason_codes=["EVENT_SCORE_NEUTRAL"],
            details=details,
        )
