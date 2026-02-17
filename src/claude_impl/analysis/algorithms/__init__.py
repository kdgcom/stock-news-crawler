"""Trading algorithm implementations.

Exposes all eight concrete algorithm classes so they can be imported
from a single location::

    from claude_impl.analysis.algorithms import (
        SentimentMomentum,
        TechnicalTrend,
        MeanReversion,
        EventCatalyst,
        VolumePriceDivergence,
        OvernightGap,
        SectorCorrelation,
        RegimeAdaptive,
    )
"""

from __future__ import annotations

from .event_catalyst import EventCatalyst
from .mean_reversion import MeanReversion
from .overnight_gap import OvernightGap
from .regime_adaptive import RegimeAdaptive
from .sector_correlation import SectorCorrelation
from .sentiment_momentum import SentimentMomentum
from .technical_trend import TechnicalTrend
from .volume_price import VolumePriceDivergence

__all__ = [
    "EventCatalyst",
    "MeanReversion",
    "OvernightGap",
    "RegimeAdaptive",
    "SectorCorrelation",
    "SentimentMomentum",
    "TechnicalTrend",
    "VolumePriceDivergence",
]
