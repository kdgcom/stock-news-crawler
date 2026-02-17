"""Pre-market routine package for the stock trading system.

Provides daily pre-market data collection, sentiment analysis,
watchlist generation, and briefing delivery for both KR and US markets.

Main classes:
    - PreMarketRoutine   -- orchestrates the full pre-market pipeline
    - WatchlistGenerator -- scores and ranks symbols for daily watchlists
    - BriefingGenerator  -- formats analysis results into human-readable briefings
"""

from __future__ import annotations

from .briefing import BriefingGenerator
from .routine import PreMarketRoutine
from .watchlist import WatchlistGenerator

__all__ = [
    "PreMarketRoutine",
    "WatchlistGenerator",
    "BriefingGenerator",
]
