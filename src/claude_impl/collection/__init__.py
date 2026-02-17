"""Data collection package for the stock trading system.

Re-exports the main collector and normaliser classes for convenient access::

    from claude_impl.collection import (
        BaseCollector,
        NaverFinanceCollector,
        DartCollector,
        AlpacaNewsCollector,
        SECEdgarCollector,
        KRPriceCollector,
        USPriceCollector,
        NewsNormalizer,
        PriceNormalizer,
    )
"""

from .base_collector import BaseCollector
from .kr_news_collector import DartCollector, NaverFinanceCollector
from .kr_price_collector import KRPriceCollector
from .normalizer import NewsNormalizer, PriceNormalizer
from .us_news_collector import AlpacaNewsCollector, SECEdgarCollector
from .us_price_collector import USPriceCollector

__all__ = [
    "BaseCollector",
    "NaverFinanceCollector",
    "DartCollector",
    "AlpacaNewsCollector",
    "SECEdgarCollector",
    "KRPriceCollector",
    "USPriceCollector",
    "NewsNormalizer",
    "PriceNormalizer",
]
