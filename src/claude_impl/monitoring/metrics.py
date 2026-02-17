"""Prometheus metric definitions for the Stock Trading System.

Metrics are grouped into four categories as specified in the 09-monitoring
design document:

1. **Data collection** -- news/price ingestion rates, latencies, and errors.
2. **Trading** -- signal generation, order execution, risk blocks, P&L.
3. **System** -- BigQuery load latency, Redis memory, LLM cost.
4. **Hybrid** -- agent triggers, fallback counts, sell recommendations,
   trade ledger counters.

If ``prometheus_client`` is not installed, lightweight dummy metric objects
are used so that call-sites can freely call ``.inc()``, ``.observe()``,
and ``.set()`` without guarding imports.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional import of prometheus_client with dummy fallbacks
# ---------------------------------------------------------------------------

try:
    from prometheus_client import Counter, Gauge, Histogram

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False
    logger.info(
        "prometheus_client is not installed. "
        "Metrics will use no-op dummy counters."
    )


# ---------------------------------------------------------------------------
# Dummy metric classes used when prometheus_client is absent
# ---------------------------------------------------------------------------

class _DummyChild:
    """Minimal stand-in for a labelled metric child."""

    def inc(self, amount: float = 1) -> None:  # noqa: ARG002
        pass

    def observe(self, amount: float) -> None:  # noqa: ARG002
        pass

    def set(self, value: float) -> None:  # noqa: ARG002
        pass


class _DummyMetric:
    """Minimal stand-in for a Prometheus metric.

    Supports both unlabelled usage (``metric.inc()``) and labelled usage
    (``metric.labels(market="KR").inc()``).
    """

    _child = _DummyChild()

    def __init__(self, name: str, doc: str, labelnames: list[str] | None = None) -> None:  # noqa: ARG002
        self._name = name

    def labels(self, *args: Any, **kwargs: Any) -> _DummyChild:  # noqa: ARG002
        return self._child

    # Unlabelled convenience methods
    def inc(self, amount: float = 1) -> None:  # noqa: ARG002
        pass

    def observe(self, amount: float) -> None:  # noqa: ARG002
        pass

    def set(self, value: float) -> None:  # noqa: ARG002
        pass


# ---------------------------------------------------------------------------
# Metric factory helpers
# ---------------------------------------------------------------------------

def _counter(name: str, doc: str, labelnames: list[str] | None = None) -> Any:
    """Create a Counter (real or dummy)."""
    if _HAS_PROMETHEUS:
        return Counter(name, doc, labelnames or [])
    return _DummyMetric(name, doc, labelnames)


def _histogram(name: str, doc: str, labelnames: list[str] | None = None) -> Any:
    """Create a Histogram (real or dummy)."""
    if _HAS_PROMETHEUS:
        return Histogram(name, doc, labelnames or [])
    return _DummyMetric(name, doc, labelnames)


def _gauge(name: str, doc: str, labelnames: list[str] | None = None) -> Any:
    """Create a Gauge (real or dummy)."""
    if _HAS_PROMETHEUS:
        return Gauge(name, doc, labelnames or [])
    return _DummyMetric(name, doc, labelnames)


# ===================================================================
# 1. Data collection metrics
# ===================================================================

news_collected: Any = _counter(
    "news_collected_total",
    "Total number of news articles collected",
    ["market", "source"],
)

price_collected: Any = _counter(
    "price_collected_total",
    "Total number of price bars collected",
    ["market"],
)

collection_latency: Any = _histogram(
    "collection_latency_seconds",
    "Time spent collecting data",
    ["market", "type"],
)

collection_errors: Any = _counter(
    "collection_errors_total",
    "Total number of data collection errors",
    ["market", "source"],
)

# ===================================================================
# 2. Trading metrics
# ===================================================================

signals_generated: Any = _counter(
    "signals_total",
    "Total number of trading signals generated",
    ["market", "decision"],
)

orders_executed: Any = _counter(
    "orders_total",
    "Total number of orders executed",
    ["market", "side"],
)

risk_blocks: Any = _counter(
    "risk_blocks_total",
    "Total number of trades blocked by risk management",
    ["level", "reason"],
)

daily_pnl: Any = _gauge(
    "daily_pnl_pct",
    "Daily profit and loss percentage",
)

total_positions: Any = _gauge(
    "total_positions",
    "Current number of open positions",
)

# ===================================================================
# 3. System metrics
# ===================================================================

bigquery_load_latency: Any = _histogram(
    "bq_load_seconds",
    "BigQuery batch load latency in seconds",
)

redis_memory_used: Any = _gauge(
    "redis_memory_bytes",
    "Redis memory usage in bytes",
)

llm_daily_cost: Any = _gauge(
    "llm_daily_cost_usd",
    "LLM daily cost in USD",
)

# ===================================================================
# 4. Hybrid metrics (added 2026-02-16)
# ===================================================================

hybrid_agent_trigger: Any = _counter(
    "hybrid_agent_trigger_total",
    "Total number of hybrid agent invocations",
)

hybrid_fallback_numeric: Any = _counter(
    "hybrid_fallback_numeric_total",
    "Total number of fallbacks from agent to numeric pipeline",
)

sell_recommendation_generated: Any = _counter(
    "sell_recommendation_generated_total",
    "Total number of sell recommendations generated",
)

sell_recommendation_approved: Any = _counter(
    "sell_recommendation_approved_total",
    "Total number of sell recommendations approved by user",
)

trade_ledger_buy: Any = _counter(
    "trade_ledger_buy_total",
    "Total number of buy entries recorded in trade ledger",
)

trade_ledger_sell: Any = _counter(
    "trade_ledger_sell_total",
    "Total number of sell entries recorded in trade ledger",
)
