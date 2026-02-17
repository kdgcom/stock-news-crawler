"""Analysis engine -- plugin algorithm architecture.

Re-exports the main classes so consumers can do::

    from claude_impl.analysis import (
        AlgorithmRouter,
        BaseAlgorithm,
        ComparisonRunner,
        EnsembleRunner,
    )

Individual algorithms are available from ``claude_impl.analysis.algorithms``.
Hybrid fusion helpers are in ``claude_impl.analysis.hybrid``.
LangGraph integration is in ``claude_impl.analysis.graphs``.
"""

from __future__ import annotations

from .base_algorithm import BaseAlgorithm
from .ensemble import ComparisonRunner, EnsembleRunner
from .router import AlgorithmRouter

__all__ = [
    "AlgorithmRouter",
    "BaseAlgorithm",
    "ComparisonRunner",
    "EnsembleRunner",
]
