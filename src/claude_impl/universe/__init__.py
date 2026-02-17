"""Stock Universe management package for Stock Trading System.

Provides the 3-Tier universe management system described in the
10-stock-universe design document:

- **Tier 1** -- core tracked symbols with full analysis and signal generation.
- **Tier 2** -- watch-list symbols with price collection and keyword scanning.
- **Tier 3** -- entire market screened daily after close for Tier 2 candidates.
"""

from claude_impl.universe.promotion import PromotionChecker
from claude_impl.universe.screener import Screener
from claude_impl.universe.tier_manager import TierManager

__all__ = [
    "TierManager",
    "Screener",
    "PromotionChecker",
]
