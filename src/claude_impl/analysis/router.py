"""Algorithm router -- selects and executes the active algorithm(s).

The router reads the ``algorithms`` section of the configuration and:

1. Instantiates only the algorithms whose ``enabled`` flag is true.
2. Routes ``run()`` to either a single algorithm or the
   ``EnsembleRunner`` depending on ``algorithms.active``.

Usage::

    router = AlgorithmRouter(config)
    signal = router.run(ctx)
"""

from __future__ import annotations

import logging
from typing import Any

from .algorithms import (
    EventCatalyst,
    MeanReversion,
    OvernightGap,
    RegimeAdaptive,
    SectorCorrelation,
    SentimentMomentum,
    TechnicalTrend,
    VolumePriceDivergence,
)
from .base_algorithm import BaseAlgorithm
from .ensemble import EnsembleRunner
from ..models.signal import AlgorithmContext, Signal

logger = logging.getLogger(__name__)

# Canonical registry of algorithm name -> class
_REGISTRY: dict[str, type[BaseAlgorithm]] = {
    "sentiment_momentum": SentimentMomentum,
    "technical_trend": TechnicalTrend,
    "mean_reversion": MeanReversion,
    "event_catalyst": EventCatalyst,
    "volume_price": VolumePriceDivergence,
    "overnight_gap": OvernightGap,
    "sector_correlation": SectorCorrelation,
    "regime_adaptive": RegimeAdaptive,
}


class AlgorithmRouter:
    """Load enabled algorithms from config and route analysis requests.

    Parameters
    ----------
    config:
        Full system configuration dict.  The ``algorithms`` sub-dict
        is used to determine which algorithms are active.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.algorithms: dict[str, BaseAlgorithm] = self._load_algorithms()

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def _load_algorithms(self) -> dict[str, BaseAlgorithm]:
        """Instantiate all algorithms whose ``enabled`` flag is true."""
        algo_section: dict[str, Any] = self.config.get("algorithms", {})
        loaded: dict[str, BaseAlgorithm] = {}

        for name, cls in _REGISTRY.items():
            algo_config: dict[str, Any] = algo_section.get(name, {})
            if not algo_config.get("enabled", False):
                continue

            if name == "regime_adaptive":
                # RegimeAdaptive needs a reference to the other algorithms;
                # we pass an empty dict here and patch it after loading.
                instance = cls(algo_config, algorithms={})
            else:
                instance = cls(algo_config)

            loaded[name] = instance

        # Provide RegimeAdaptive with the full algorithm map
        ra = loaded.get("regime_adaptive")
        if ra is not None and hasattr(ra, "set_algorithms"):
            ra.set_algorithms(loaded)  # type: ignore[attr-defined]

        logger.info("AlgorithmRouter loaded %d algorithms: %s",
                     len(loaded), list(loaded.keys()))
        return loaded

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, ctx: AlgorithmContext) -> Signal:
        """Execute the active algorithm (or ensemble) and return a signal.

        Raises ``ValueError`` if the configured active algorithm is not
        found in the loaded set.
        """
        algo_section: dict[str, Any] = self.config.get("algorithms", {})
        active: str = algo_section.get("active", "ensemble")

        if active == "ensemble":
            return self._run_ensemble(ctx)

        if active in self.algorithms:
            return self.algorithms[active].generate_signal(ctx)

        raise ValueError(
            f"Unknown or disabled algorithm '{active}'. "
            f"Loaded: {list(self.algorithms.keys())}"
        )

    # ------------------------------------------------------------------
    # Ensemble delegation
    # ------------------------------------------------------------------

    def _run_ensemble(self, ctx: AlgorithmContext) -> Signal:
        """Delegate to the ``EnsembleRunner``."""
        algo_section: dict[str, Any] = self.config.get("algorithms", {})
        ensemble_cfg: dict[str, Any] = algo_section.get("ensemble", {})

        runner = EnsembleRunner(ensemble_cfg, self.algorithms, ctx)
        return runner.run()
