from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..agents.simple_agents import NewsAgent, PortfolioAgent, RegimeAgent, TechnicalAgent
from ..models import AlgorithmContext, Signal


class BaseAlgorithm(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        raise NotImplementedError


class SentimentMomentum(BaseAlgorithm):
    name = "sentiment_momentum"

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        if not ctx.news_events:
            return Signal(ctx.symbol, ctx.market, "HOLD", 0.0, 0.2, self.name, ["NO_NEWS"])
        current = sum(n.sentiment_score for n in ctx.news_events) / len(ctx.news_events)
        momentum = current - ctx.sentiment_previous
        if abs(momentum) < 0.05:
            return Signal(ctx.symbol, ctx.market, "HOLD", momentum, 0.4, self.name, ["LOW_SENTIMENT_MOMENTUM"])
        decision = "BUY" if momentum > 0 else "SELL"
        return Signal(ctx.symbol, ctx.market, decision, max(min(momentum, 1.0), -1.0), min(abs(momentum) * 2, 1.0), self.name, ["SENTIMENT_MOMENTUM"])


class TechnicalTrend(BaseAlgorithm):
    name = "technical_trend"

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        closes = [b.close for b in ctx.price_bars]
        if len(closes) < 5:
            return Signal(ctx.symbol, ctx.market, "HOLD", 0.0, 0.2, self.name, ["INSUFFICIENT_BARS"])
        short = sum(closes[-3:]) / 3
        long = sum(closes[-5:]) / 5
        score = (short - long) / max(long, 1e-6)
        score = max(min(score * 8, 1.0), -1.0)
        decision = "BUY" if score > 0.15 else "SELL" if score < -0.15 else "HOLD"
        return Signal(ctx.symbol, ctx.market, decision, score, min(abs(score) + 0.3, 1.0), self.name, ["TREND_CROSS"])


class MeanReversion(BaseAlgorithm):
    name = "mean_reversion"

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        closes = [b.close for b in ctx.price_bars]
        if len(closes) < 5:
            return Signal(ctx.symbol, ctx.market, "HOLD", 0.0, 0.2, self.name, ["INSUFFICIENT_BARS"])
        mean_price = sum(closes) / len(closes)
        z = (closes[-1] - mean_price) / max(mean_price, 1e-6)
        if z < -0.02:
            return Signal(ctx.symbol, ctx.market, "BUY", min(abs(z) * 8, 1.0), 0.55, self.name, ["MEAN_REVERT_BUY"])
        if z > 0.02:
            return Signal(ctx.symbol, ctx.market, "SELL", -min(abs(z) * 8, 1.0), 0.55, self.name, ["MEAN_REVERT_SELL"])
        return Signal(ctx.symbol, ctx.market, "HOLD", 0.0, 0.45, self.name, ["NO_EDGE"])


@dataclass
class EnsembleConfig:
    members: list[tuple[BaseAlgorithm, float]]
    min_agreement: float = 0.1
    buy_threshold: float = 0.6
    sell_threshold: float = -0.6


class EnsembleRunner:
    def __init__(self, config: EnsembleConfig) -> None:
        self.config = config

    def run(self, ctx: AlgorithmContext) -> Signal:
        parts: list[tuple[Signal, float]] = []
        for algo, weight in self.config.members:
            parts.append((algo.generate_signal(ctx), weight))

        total_weight = sum(w for _, w in parts) or 1.0
        score = sum(sig.score * weight for sig, weight in parts) / total_weight

        if abs(score) < self.config.min_agreement:
            decision = "HOLD"
        elif score >= self.config.buy_threshold:
            decision = "BUY"
        elif score <= self.config.sell_threshold:
            decision = "SELL"
        else:
            decision = "HOLD"

        return Signal(
            symbol=ctx.symbol,
            market=ctx.market,
            decision=decision,
            score=score,
            confidence=min(abs(score), 1.0),
            algorithm="ensemble",
            reason_codes=[f"{sig.algorithm}:{sig.decision}" for sig, _ in parts],
            details={"member_signals": [(sig.algorithm, sig.score, w) for sig, w in parts]},
        )


class AgentOverlayRunner:
    """Hybrid engine: numeric first, then agent overlay by trigger."""

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.news_agent = NewsAgent()
        self.technical_agent = TechnicalAgent()
        self.regime_agent = RegimeAgent()
        self.portfolio_agent = PortfolioAgent()

    def _is_high_impact_event(self, ctx: AlgorithmContext) -> bool:
        high_impact = set(self.settings["analysis"]["hybrid"]["agent_trigger"]["high_impact_event_types"])
        return any(n.event_type in high_impact for n in ctx.news_events)

    @staticmethod
    def _decision_sign(score: float) -> int:
        if score > 0:
            return 1
        if score < 0:
            return -1
        return 0

    def _has_signal_conflict(self, numeric_signal: Signal, tech_signal: Signal, news_signal: Signal) -> bool:
        expected = self._decision_sign(numeric_signal.score)
        return expected != 0 and (expected != self._decision_sign(tech_signal.score) or expected != self._decision_sign(news_signal.score))

    def should_trigger_agents(self, numeric_signal: Signal, ctx: AlgorithmContext) -> bool:
        cfg = self.settings["analysis"]["hybrid"]["agent_trigger"]
        b = self.settings["analysis"]["signal"]["buy_threshold"]
        s = self.settings["analysis"]["signal"]["sell_threshold"]
        margin = cfg["near_threshold_margin"]

        near_threshold = abs(numeric_signal.score - b) < margin or abs(numeric_signal.score - s) < margin
        if near_threshold:
            return True

        probe_news = self.news_agent.run(ctx)
        probe_tech = self.technical_agent.run(ctx)
        if cfg.get("conflict_required", False) and self._has_signal_conflict(numeric_signal, probe_tech, probe_news):
            return True

        return self._is_high_impact_event(ctx)

    def resolve_alpha(self, ctx: AlgorithmContext) -> float:
        hybrid_cfg = self.settings["analysis"]["hybrid"]
        if ctx.regime == "volatile":
            return float(hybrid_cfg["alpha_volatile"])
        if len(ctx.news_events) >= 5:
            return float(hybrid_cfg["alpha_news_spike"])
        return float(hybrid_cfg["alpha_default"])

    def run(self, numeric_signal: Signal, ctx: AlgorithmContext) -> Signal:
        if not self.should_trigger_agents(numeric_signal, ctx):
            numeric_signal.details["hybrid"] = {"triggered": False, "mode": "numeric_only"}
            return numeric_signal

        n = self.news_agent.run(ctx)
        t = self.technical_agent.run(ctx)
        r = self.regime_agent.run(ctx)
        p = self.portfolio_agent.run(ctx)

        agent_score = (n.score * 0.35) + (t.score * 0.30) + (r.score * 0.20) + (p.score * 0.15)
        alpha = self.resolve_alpha(ctx)
        final_score = alpha * numeric_signal.score + (1 - alpha) * agent_score

        b = self.settings["analysis"]["signal"]["buy_threshold"]
        s = self.settings["analysis"]["signal"]["sell_threshold"]
        if final_score >= b:
            decision = "BUY"
        elif final_score <= s:
            decision = "SELL"
        else:
            decision = "HOLD"

        return Signal(
            symbol=ctx.symbol,
            market=ctx.market,
            decision=decision,
            score=final_score,
            confidence=min(abs(final_score), 1.0),
            algorithm="hybrid",
            reason_codes=numeric_signal.reason_codes + ["AGENT_OVERLAY"],
            details={
                "hybrid": {
                    "triggered": True,
                    "alpha": alpha,
                    "numeric_score": numeric_signal.score,
                    "agent_score": agent_score,
                },
                "agents": {
                    "news": {"decision": n.decision, "score": n.score},
                    "technical": {"decision": t.decision, "score": t.score},
                    "regime": {"decision": r.decision, "score": r.score},
                    "portfolio": {"decision": p.decision, "score": p.score},
                },
            },
        )
