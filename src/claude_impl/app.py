"""Application entry point for the Claude implementation.

Provides two execution modes:

* **server** -- runs as a long-lived process (Cloud Run / local) with
  scheduled collection, analysis, and pre-market routines.
* **once** -- runs a single analysis cycle and exits (useful for cron
  and Cloud Scheduler invocations).

Usage::

    # From main.py (--mode claude)
    from src.claude_impl.app import run
    run()

    # Or directly
    python -m src.claude_impl.app --help
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

from .config.loader import load_config
from .infrastructure.bigquery_client import BigQueryClient
from .infrastructure.gcs_client import GCSClient
from .infrastructure.mongodb_client import MongoDBClient
from .infrastructure.redis_client import RedisClient
from .infrastructure.telegram_client import TelegramNotifier
from .analysis.router import AlgorithmRouter
from .execution.paper_executor import PaperExecutor
from .execution.position_manager import PositionManager
from .execution.trade_ledger import TradeLedger
from .risk.risk_gate import RiskGate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Infrastructure bootstrapping
# ---------------------------------------------------------------------------

def _build_infra(config: dict) -> dict[str, Any]:
    """Instantiate infrastructure clients from configuration.

    Returns a dict keyed by service name so callers can pull what they
    need without coupling to concrete types.
    """
    gcp_cfg = config.get("gcp", {})
    mongo_cfg = config.get("mongodb", {})
    redis_cfg = config.get("redis", {})
    notif_cfg = config.get("notification", {})

    bq = BigQueryClient(
        project_id=gcp_cfg.get("project_id", ""),
        dataset=gcp_cfg.get("bigquery", {}).get("dataset", "stock_trading"),
        credentials_path=gcp_cfg.get("credentials_path"),
    )

    mongo = MongoDBClient(
        uri=mongo_cfg.get("atlas_uri", ""),
        database=mongo_cfg.get("database", "stock_news"),
    )

    redis = RedisClient(
        host=redis_cfg.get("host", "localhost"),
        port=int(redis_cfg.get("port", 6379)),
        password=redis_cfg.get("password", ""),
    )

    gcs = GCSClient(
        bucket=gcp_cfg.get("cloud_storage", {}).get("bucket", ""),
        credentials_path=gcp_cfg.get("credentials_path"),
    )

    telegram_cfg = notif_cfg.get("telegram", {})
    telegram = TelegramNotifier(
        bot_token=telegram_cfg.get("bot_token", ""),
        chat_id=telegram_cfg.get("chat_id", ""),
        quiet_start=notif_cfg.get("quiet_hours", {}).get("start", "00:00"),
        quiet_end=notif_cfg.get("quiet_hours", {}).get("end", "06:00"),
    )

    return {
        "bigquery": bq,
        "mongodb": mongo,
        "redis": redis,
        "gcs": gcs,
        "telegram": telegram,
    }


# ---------------------------------------------------------------------------
# Core components
# ---------------------------------------------------------------------------

def _build_components(config: dict, infra: dict[str, Any]) -> dict[str, Any]:
    """Instantiate the core trading system components."""
    redis_client = infra["redis"]
    bq_client = infra["bigquery"]

    position_mgr = PositionManager(redis_client, config)
    trade_ledger = TradeLedger(bq_client, config)
    risk_gate = RiskGate(config, redis_client)
    algorithm_router = AlgorithmRouter(config)
    paper_executor = PaperExecutor(
        position_manager=position_mgr,
        trade_ledger=trade_ledger,
        config=config,
    )

    return {
        "position_manager": position_mgr,
        "trade_ledger": trade_ledger,
        "risk_gate": risk_gate,
        "algorithm_router": algorithm_router,
        "paper_executor": paper_executor,
    }


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

def _run_once(config: dict, infra: dict, components: dict) -> None:
    """Execute a single analysis cycle and exit."""
    logger.info("Running single analysis cycle.")

    router: AlgorithmRouter = components["algorithm_router"]
    risk_gate: RiskGate = components["risk_gate"]
    position_mgr: PositionManager = components["position_manager"]
    paper_executor: PaperExecutor = components["paper_executor"]

    # Determine which markets are enabled
    markets_cfg = config.get("markets", {})
    for market_key in ("kr", "us"):
        market_cfg = markets_cfg.get(market_key, {})
        if not market_cfg.get("enabled", False):
            continue

        market = market_key.upper()
        tier1_symbols = (
            config.get("universe", {})
            .get("tier1", {})
            .get(market_key, {})
            .get("symbols", [])
        )

        if not tier1_symbols:
            logger.info("No Tier 1 symbols configured for %s; skipping.", market)
            continue

        logger.info("Analysing %d Tier 1 symbols for %s.", len(tier1_symbols), market)

        from .models.signal import AlgorithmContext

        for symbol in tier1_symbols:
            try:
                # Build context (in production this fetches live data)
                pos = position_mgr.get_position(market, symbol)
                portfolio = position_mgr.get_portfolio_state(
                    total_capital=config.get("portfolio", {}).get("total_capital", 100_000_000)
                )

                ctx = AlgorithmContext(
                    symbol=symbol,
                    market=market,
                    position=pos,
                    portfolio=portfolio,
                )

                # Generate signal
                signal = router.run(ctx)
                logger.info(
                    "Signal %s:%s -> %s (score=%.4f, conf=%.4f)",
                    market, symbol, signal.decision, signal.score, signal.confidence,
                )

                # Risk check
                if signal.decision != "HOLD":
                    signal_dict = {
                        "symbol": symbol,
                        "market": market,
                        "decision": signal.decision,
                        "score": signal.score,
                        "amount": config.get("risk", {}).get("hard_limits", {}).get(
                            "max_single_order_krw" if market == "KR" else "max_single_order_usd",
                            5_000_000,
                        ),
                        "side": signal.decision,
                    }
                    passed, reason = risk_gate.check(signal_dict, portfolio)
                    if passed:
                        paper_executor.execute(signal)
                    else:
                        logger.info(
                            "Risk gate blocked %s:%s %s -- %s",
                            market, symbol, signal.decision, reason,
                        )

            except Exception:
                logger.exception("Error analysing %s:%s", market, symbol)

    logger.info("Single analysis cycle completed.")


def _run_server(config: dict, infra: dict, components: dict) -> None:
    """Run as a long-lived process with periodic analysis cycles."""
    interval_minutes = config.get("collection", {}).get("price", {}).get("interval_minutes", 5)
    interval_seconds = interval_minutes * 60

    logger.info("Starting server mode (interval=%dm).", interval_minutes)

    running = True

    def _handle_signal(signum: int, frame: Any) -> None:
        nonlocal running
        logger.info("Received signal %d, shutting down gracefully.", signum)
        running = False

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while running:
        try:
            _run_once(config, infra, components)
        except Exception:
            logger.exception("Error in analysis cycle.")

        # Wait for next cycle
        for _ in range(interval_seconds):
            if not running:
                break
            time.sleep(1)

    logger.info("Server stopped.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(args: list[str] | None = None) -> None:
    """Main entry point for the Claude trading system.

    Called from ``main.py --mode claude`` or directly.
    """
    parser = argparse.ArgumentParser(
        description="Stock Trading System (Claude Implementation)",
    )
    parser.add_argument(
        "--run-mode",
        choices=["once", "server"],
        default="once",
        help="Execution mode: 'once' for single cycle, 'server' for continuous (default: once)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to base config YAML (default: config/settings.yaml)",
    )

    parsed = parser.parse_args(args)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, parsed.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("Stock Trading System (Claude) starting.")
    logger.info("Run mode: %s", parsed.run_mode)

    # Load configuration
    from pathlib import Path

    base_path = Path(parsed.config) if parsed.config else None
    config = load_config(base_path=base_path)
    logger.info("Configuration loaded.")

    # Bootstrap infrastructure
    infra = _build_infra(config)
    logger.info("Infrastructure clients initialized.")

    # Bootstrap components
    components = _build_components(config, infra)
    logger.info("Core components initialized.")

    # Execute
    if parsed.run_mode == "server":
        _run_server(config, infra, components)
    else:
        _run_once(config, infra, components)

    logger.info("Stock Trading System (Claude) finished.")
