from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class MetricRegistry:
    """09-monitoring.md metrics mirror."""

    counters: Counter[str] = field(default_factory=Counter)
    gauges: dict[str, float] = field(default_factory=dict)

    def inc(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def set_gauge(self, name: str, value: float) -> None:
        self.gauges[name] = value

    def snapshot(self) -> dict:
        return {
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
        }


def register_trade_ledger_metrics(registry: MetricRegistry, side: str) -> None:
    if side == "BUY":
        registry.inc("trade_ledger_buy_total")
    elif side == "SELL":
        registry.inc("trade_ledger_sell_total")


def register_hybrid_metrics(registry: MetricRegistry, triggered: bool, fallback_numeric: bool) -> None:
    if triggered:
        registry.inc("hybrid_agent_trigger_total")
    if fallback_numeric:
        registry.inc("hybrid_fallback_numeric_total")
