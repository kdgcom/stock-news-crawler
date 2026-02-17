"""Execution package for the stock trading system.

Handles paper trading (Phase 1-2), broker integration (Phase 3),
position management, and trade ledger recording.

Main classes:
    - PaperExecutor     -- simulated order execution without real API calls
    - PositionManager   -- Redis-backed position tracking
    - TradeLedger       -- trade record keeping with BigQuery persistence
    - BaseBroker        -- abstract broker interface for Phase 3 live trading
    - KISBroker         -- Korean Investment Securities API stub
    - AlpacaBroker      -- Alpaca API stub
"""

from __future__ import annotations

from .broker_base import AlpacaBroker, BaseBroker, KISBroker
from .paper_executor import PaperExecutor
from .position_manager import PositionManager
from .trade_ledger import TradeLedger

__all__ = [
    "PaperExecutor",
    "PositionManager",
    "TradeLedger",
    "BaseBroker",
    "KISBroker",
    "AlpacaBroker",
]
