"""Monitoring package for Stock Trading System.

Provides Prometheus metric definitions, alert management, and daily/weekly
report generation.  See the 09-monitoring design document for full details.
"""

from claude_impl.monitoring.alerts import AlertManager
from claude_impl.monitoring.daily_report import ReportGenerator
from claude_impl.monitoring.metrics import (
    bigquery_load_latency,
    collection_errors,
    collection_latency,
    daily_pnl,
    hybrid_agent_trigger,
    hybrid_fallback_numeric,
    llm_daily_cost,
    news_collected,
    orders_executed,
    price_collected,
    redis_memory_used,
    risk_blocks,
    sell_recommendation_approved,
    sell_recommendation_generated,
    signals_generated,
    total_positions,
    trade_ledger_buy,
    trade_ledger_sell,
)

__all__ = [
    # Alert management
    "AlertManager",
    # Report generation
    "ReportGenerator",
    # Data collection metrics
    "news_collected",
    "price_collected",
    "collection_latency",
    "collection_errors",
    # Trading metrics
    "signals_generated",
    "orders_executed",
    "risk_blocks",
    "daily_pnl",
    "total_positions",
    # System metrics
    "bigquery_load_latency",
    "redis_memory_used",
    "llm_daily_cost",
    # Hybrid metrics
    "hybrid_agent_trigger",
    "hybrid_fallback_numeric",
    "sell_recommendation_generated",
    "sell_recommendation_approved",
    "trade_ledger_buy",
    "trade_ledger_sell",
]
