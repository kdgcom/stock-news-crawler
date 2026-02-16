from __future__ import annotations

from statistics import mean

from .models import NewsEvent


def classify_change(change: float) -> str:
    if change >= 0.15:
        return "POSITIVE"
    if change <= -0.15:
        return "NEGATIVE"
    return "NEUTRAL"


def pre_market_sentiment_change(overnight_news: list[NewsEvent], previous_baseline: float) -> dict:
    """05-pre-market.md simplified overnight sentiment briefing."""
    if not overnight_news:
        return {"change": 0.0, "signal": "NO_NEWS", "article_count": 0}
    current = mean(n.sentiment_score for n in overnight_news)
    change = current - previous_baseline
    return {
        "change": round(change, 4),
        "signal": classify_change(change),
        "article_count": len(overnight_news),
    }


def build_watchlist_candidates(items: list[dict], threshold: float = 0.3, top_n: int = 10) -> list[dict]:
    candidates = [x for x in items if x.get("score", 0.0) >= threshold]
    return sorted(candidates, key=lambda x: x["score"], reverse=True)[:top_n]
