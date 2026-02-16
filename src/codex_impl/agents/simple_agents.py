from __future__ import annotations

from dataclasses import dataclass

from ..models import AlgorithmContext, Signal


@dataclass
class BaseAgent:
    name: str

    def run(self, ctx: AlgorithmContext) -> Signal:
        raise NotImplementedError


class NewsAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="news_agent")

    def run(self, ctx: AlgorithmContext) -> Signal:
        if not ctx.news_events:
            return Signal(ctx.symbol, ctx.market, "HOLD", 0.0, 0.2, self.name, ["NO_NEWS"])
        weighted = sum((n.sentiment_score * 0.6 + n.novelty_score * 0.2 + n.reliability_score * 0.2) for n in ctx.news_events)
        score = max(min(weighted / len(ctx.news_events), 1.0), -1.0)
        decision = "BUY" if score > 0.2 else "SELL" if score < -0.2 else "HOLD"
        return Signal(ctx.symbol, ctx.market, decision, score, min(abs(score) + 0.3, 1.0), self.name, ["NEWS_AGENT"])


class TechnicalAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="technical_agent")

    def run(self, ctx: AlgorithmContext) -> Signal:
        closes = [bar.close for bar in ctx.price_bars]
        if len(closes) < 3:
            return Signal(ctx.symbol, ctx.market, "HOLD", 0.0, 0.2, self.name, ["INSUFFICIENT_BARS"])
        drift = (closes[-1] - closes[0]) / max(closes[0], 1e-6)
        score = max(min(drift * 5, 1.0), -1.0)
        decision = "BUY" if score > 0.2 else "SELL" if score < -0.2 else "HOLD"
        return Signal(ctx.symbol, ctx.market, decision, score, min(abs(score) + 0.25, 1.0), self.name, ["TECH_AGENT"])


class RegimeAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="regime_agent")

    def run(self, ctx: AlgorithmContext) -> Signal:
        if ctx.regime == "volatile":
            return Signal(ctx.symbol, ctx.market, "HOLD", -0.15, 0.7, self.name, ["REGIME_VOLATILE"])
        if ctx.regime == "trending_up":
            return Signal(ctx.symbol, ctx.market, "BUY", 0.35, 0.65, self.name, ["REGIME_TRENDING_UP"])
        if ctx.regime == "trending_down":
            return Signal(ctx.symbol, ctx.market, "SELL", -0.35, 0.65, self.name, ["REGIME_TRENDING_DOWN"])
        return Signal(ctx.symbol, ctx.market, "HOLD", 0.0, 0.5, self.name, ["REGIME_NORMAL"])


class PortfolioAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(name="portfolio_agent")

    def run(self, ctx: AlgorithmContext) -> Signal:
        position = ctx.position or {}
        qty = int(position.get("net_quantity", 0))
        if qty <= 0:
            return Signal(ctx.symbol, ctx.market, "HOLD", 0.0, 0.5, self.name, ["NO_POSITION"])
        unrealized_pct = float(position.get("unrealized_pnl_pct", 0.0))
        if unrealized_pct <= -0.05:
            return Signal(ctx.symbol, ctx.market, "SELL", -0.6, 0.8, self.name, ["LOSS_CUT_ZONE"])
        if unrealized_pct >= 0.08:
            return Signal(ctx.symbol, ctx.market, "SELL", -0.2, 0.6, self.name, ["TAKE_PROFIT_ZONE"])
        return Signal(ctx.symbol, ctx.market, "HOLD", 0.0, 0.55, self.name, ["POSITION_STABLE"])

