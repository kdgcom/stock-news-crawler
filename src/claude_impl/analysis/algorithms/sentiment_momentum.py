"""Sentiment Momentum (SM) algorithm.

Tracks the **direction and speed of change** in news sentiment rather
than the absolute sentiment level.  A rising sentiment trend triggers
BUY; a falling trend triggers SELL.

Best suited for:
    * Event-driven markets (earnings, M&A, policy changes)
    * Symbols with high news frequency

Config keys (``algorithms.sentiment_momentum``)::

    min_articles         -- minimum articles to produce a confident signal
    decay_factor         -- hourly exponential decay for time-weighting
    weight_sentiment     -- weight of sentiment_score in article score
    weight_novelty       -- weight of novelty_score in article score
    weight_reliability   -- weight of reliability_score in article score
    change_threshold     -- minimum |momentum| to trigger BUY/SELL
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..base_algorithm import BaseAlgorithm
from ...models.signal import AlgorithmContext, Signal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SentimentMomentum(BaseAlgorithm):
    """Time-weighted sentiment scoring with momentum detection."""

    @property
    def name(self) -> str:
        return "sentiment_momentum"

    def required_data(self) -> list[str]:
        return ["news_events", "sentiment_current", "sentiment_previous"]

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        cfg = self.config
        news = ctx.news_events

        # Insufficient data -- low confidence HOLD
        min_articles: int = cfg.get("min_articles", 3)
        if len(news) < min_articles:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="HOLD",
                score=0.0,
                confidence=0.2,
                algorithm=self.name,
                reason_codes=["INSUFFICIENT_NEWS"],
                details={"article_count": len(news), "min_required": min_articles},
            )

        # --- Time-weighted sentiment score --------------------------------
        decay_factor: float = cfg.get("decay_factor", 0.95)
        w_sentiment: float = cfg.get("weight_sentiment", 0.6)
        w_novelty: float = cfg.get("weight_novelty", 0.2)
        w_reliability: float = cfg.get("weight_reliability", 0.2)

        weighted_score = 0.0
        total_weight = 0.0
        now = _utcnow()

        for article in news:
            analyzed_at = article.get("analyzed_at_utc")
            if analyzed_at is None:
                continue

            if isinstance(analyzed_at, str):
                try:
                    analyzed_at = datetime.fromisoformat(analyzed_at)
                except ValueError:
                    continue

            if analyzed_at.tzinfo is None:
                analyzed_at = analyzed_at.replace(tzinfo=timezone.utc)

            hours_ago = max((now - analyzed_at).total_seconds() / 3600, 0)
            time_weight = decay_factor ** hours_ago

            article_score = (
                article.get("sentiment_score", 0.0) * w_sentiment
                + article.get("novelty_score", 0.0) * w_novelty
                + article.get("reliability_score", 0.0) * w_reliability
            )

            weighted_score += article_score * time_weight
            total_weight += time_weight

        current = weighted_score / total_weight if total_weight > 0 else 0.0

        # --- Momentum = current - previous cycle -------------------------
        momentum = current - ctx.sentiment_previous

        change_threshold: float = cfg.get("change_threshold", 0.15)

        if abs(momentum) < change_threshold:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="HOLD",
                score=momentum,
                confidence=min(abs(momentum) * 2, 1.0),
                algorithm=self.name,
                reason_codes=["SENTIMENT_FLAT"],
                details={
                    "current_score": round(current, 4),
                    "momentum": round(momentum, 4),
                    "article_count": len(news),
                },
            )

        if momentum > 0:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="BUY",
                score=min(momentum, 1.0),
                confidence=min(abs(momentum) * 2, 1.0),
                algorithm=self.name,
                reason_codes=["SENTIMENT_MOMENTUM_UP"],
                details={
                    "current_score": round(current, 4),
                    "momentum": round(momentum, 4),
                    "article_count": len(news),
                },
            )

        return Signal(
            symbol=ctx.symbol,
            market=ctx.market,
            decision="SELL",
            score=max(momentum, -1.0),
            confidence=min(abs(momentum) * 2, 1.0),
            algorithm=self.name,
            reason_codes=["SENTIMENT_MOMENTUM_DOWN"],
            details={
                "current_score": round(current, 4),
                "momentum": round(momentum, 4),
                "article_count": len(news),
            },
        )
