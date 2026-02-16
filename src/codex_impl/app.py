from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from .analysis.step06_analysis_engine import (
    AgentOverlayRunner,
    EnsembleConfig,
    EnsembleRunner,
    MeanReversion,
    SentimentMomentum,
    TechnicalTrend,
)
from .collection.step03_data_collection import NewsCollector, PriceCollector
from .models import AlgorithmContext
from .step00_overview import SystemOverview
from .step01_config import ConfigLoader
from .step02_infrastructure import InfrastructurePlan
from .step07_risk_management import RiskGate
from .step08_execution import PaperExecutor
from .step09_monitoring import MetricRegistry, register_hybrid_metrics, register_trade_ledger_metrics
from .step10_stock_universe import UniverseManager
from .storage.step04_data_storage import InMemoryStorage


@dataclass
class TradingSystem:
    """00->10 wired system implementation."""

    config_loader: ConfigLoader = ConfigLoader()

    def __post_init__(self) -> None:
        self.overview = SystemOverview()
        self.settings = self.config_loader.load()
        self.infrastructure = InfrastructurePlan()
        self.infrastructure.validate()

        self.storage = InMemoryStorage()
        self.news_collector = NewsCollector()
        self.price_collector = PriceCollector()

        self.ensemble = EnsembleRunner(
            EnsembleConfig(
                members=[
                    (SentimentMomentum(), 0.35),
                    (TechnicalTrend(), 0.40),
                    (MeanReversion(), 0.25),
                ],
                min_agreement=0.10,
                buy_threshold=self.settings["analysis"]["signal"]["buy_threshold"],
                sell_threshold=self.settings["analysis"]["signal"]["sell_threshold"],
            )
        )
        self.hybrid = AgentOverlayRunner(self.settings)
        self.risk_gate = RiskGate(self.settings)
        self.executor = PaperExecutor(storage=self.storage, risk_gate=self.risk_gate)
        self.metrics = MetricRegistry()
        self.universe = UniverseManager()

    def build_context(self, symbol: str, market: str, user_id: str, account_id: str) -> AlgorithmContext:
        news = self.news_collector.collect_news(symbol=symbol, market=market)
        bars = self.price_collector.collect_bars(symbol=symbol, market=market)
        holdings = self.storage.current_holdings(user_id=user_id, account_id=account_id)
        position = holdings.get(symbol)
        return AlgorithmContext(
            symbol=symbol,
            market=market,
            price_bars=bars,
            daily_bars=bars,
            news_events=news,
            sentiment_current=(sum(n.sentiment_score for n in news) / len(news)) if news else 0.0,
            sentiment_previous=0.0,
            position=position,
            portfolio={"open_positions": len(holdings), "daily_pnl_pct": 0.0, "drawdown_pct": 0.0},
            regime="normal",
        )

    def run_symbol(self, symbol: str, market: str, user_id: str = "demo", account_id: str = "paper") -> dict:
        ctx = self.build_context(symbol=symbol, market=market, user_id=user_id, account_id=account_id)
        numeric_signal = self.ensemble.run(ctx)
        final_signal = self.hybrid.run(numeric_signal, ctx)

        register_hybrid_metrics(
            self.metrics,
            triggered=bool(final_signal.details.get("hybrid", {}).get("triggered", False)),
            fallback_numeric=not bool(final_signal.details.get("hybrid", {}).get("triggered", False)),
        )

        quantity = 1
        price = ctx.price_bars[-1].close if ctx.price_bars else 0.0
        result = self.executor.execute_signal(
            signal=final_signal,
            user_id=user_id,
            account_id=account_id,
            quantity=quantity,
            price=price,
            portfolio=ctx.portfolio,
            market_state={"spread_pct": 0.001, "api_failures": 0},
        )

        if result.status == "FILLED":
            register_trade_ledger_metrics(self.metrics, side=final_signal.decision)

        sell_rec = self.executor.generate_sell_recommendation(
            user_id=user_id,
            account_id=account_id,
            signal=final_signal,
            min_confidence=float(self.settings["sell_recommendation"]["min_confidence"]),
        )

        decision_id = str(uuid4())
        self.storage.append_decision_log(
            {
                "decision_id": decision_id,
                "ts_utc": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "market": market,
                "decision": final_signal.decision,
                "score": final_signal.score,
                "algorithm": final_signal.algorithm,
                "reason_codes": final_signal.reason_codes,
                "details": final_signal.details,
                "order_result": result.status,
            }
        )

        return {
            "decision_id": decision_id,
            "signal": final_signal,
            "execution": result,
            "sell_recommendation": sell_rec,
            "metrics": self.metrics.snapshot(),
        }
