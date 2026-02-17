"""Ensemble and comparison runners for multi-algorithm aggregation.

``EnsembleRunner``
    Combines signals from multiple algorithms using one of three
    aggregation modes: ``weighted_vote``, ``majority_vote``, or
    ``best_confidence``.

``ComparisonRunner``
    Runs a *champion* strategy (live) alongside a *challenger*
    strategy (shadow / paper) so that performance can be compared
    before switching.
"""

from __future__ import annotations

import logging
from typing import Any

from .base_algorithm import BaseAlgorithm
from ..models.signal import AlgorithmContext, Signal

logger = logging.getLogger(__name__)


class EnsembleRunner:
    """Aggregate signals from multiple algorithms.

    Parameters
    ----------
    config:
        The ``algorithms.ensemble`` sub-dict from settings.yaml.
        Expected keys: ``mode``, ``members``, ``min_agreement``.
    algorithms:
        Dict of loaded ``BaseAlgorithm`` instances keyed by name.
    ctx:
        The ``AlgorithmContext`` to pass to each member algorithm.
    """

    def __init__(
        self,
        config: dict[str, Any],
        algorithms: dict[str, BaseAlgorithm],
        ctx: AlgorithmContext,
    ) -> None:
        self.config = config
        self.algorithms = algorithms
        self.ctx = ctx

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> Signal:
        """Execute all member algorithms and aggregate their signals."""
        members: list[dict[str, Any]] = self.config.get("members", [])
        results: list[tuple[Signal, float]] = []

        for member in members:
            algo_name: str = member.get("algorithm", "")
            weight: float = member.get("weight", 0.0)
            algo = self.algorithms.get(algo_name)
            if algo is None:
                logger.warning("Ensemble: algorithm '%s' not loaded, skipping.", algo_name)
                continue
            try:
                signal = algo.generate_signal(self.ctx)
                results.append((signal, weight))
            except Exception:
                logger.exception("Ensemble: algorithm '%s' raised an error.", algo_name)

        if not results:
            return Signal(
                symbol=self.ctx.symbol,
                market=self.ctx.market,
                decision="HOLD",
                score=0.0,
                confidence=0.0,
                algorithm="ensemble",
                reason_codes=["NO_MEMBER_RESULTS"],
                details={},
            )

        mode: str = self.config.get("mode", "weighted_vote")

        if mode == "weighted_vote":
            return self._weighted_vote(results)
        if mode == "majority_vote":
            return self._majority_vote(results)
        if mode == "best_confidence":
            return self._best_confidence(results)

        logger.warning("Ensemble: unknown mode '%s', defaulting to weighted_vote.", mode)
        return self._weighted_vote(results)

    # ------------------------------------------------------------------
    # Aggregation strategies
    # ------------------------------------------------------------------

    def _weighted_vote(self, results: list[tuple[Signal, float]]) -> Signal:
        """Score = sum(signal.score * weight) / sum(weight)."""
        weighted_score = sum(s.score * w for s, w in results)
        total_weight = sum(w for _, w in results)
        normalized = weighted_score / total_weight if total_weight > 0 else 0.0

        min_agreement: float = self.config.get("min_agreement", 0.5)

        if abs(normalized) < min_agreement:
            decision = "HOLD"
        elif normalized > 0:
            decision = "BUY"
        else:
            decision = "SELL"

        return Signal(
            symbol=self.ctx.symbol,
            market=self.ctx.market,
            decision=decision,
            score=round(normalized, 4),
            confidence=round(abs(normalized), 4),
            algorithm="ensemble",
            reason_codes=[f"{s.algorithm}:{s.decision}" for s, _ in results],
            details={
                "mode": "weighted_vote",
                "member_signals": [
                    (s.algorithm, s.score, w) for s, w in results
                ],
            },
        )

    def _majority_vote(self, results: list[tuple[Signal, float]]) -> Signal:
        """BUY/SELL decision by counting votes weighted by *weight*."""
        buy_weight = sum(w for s, w in results if s.decision == "BUY")
        sell_weight = sum(w for s, w in results if s.decision == "SELL")
        hold_weight = sum(w for s, w in results if s.decision == "HOLD")

        if buy_weight > sell_weight and buy_weight > hold_weight:
            decision = "BUY"
        elif sell_weight > buy_weight and sell_weight > hold_weight:
            decision = "SELL"
        else:
            decision = "HOLD"

        # Average score of the winning direction
        winners = [(s, w) for s, w in results if s.decision == decision]
        avg_score = (
            sum(s.score * w for s, w in winners) / sum(w for _, w in winners)
            if winners else 0.0
        )

        return Signal(
            symbol=self.ctx.symbol,
            market=self.ctx.market,
            decision=decision,
            score=round(avg_score, 4),
            confidence=round(abs(avg_score), 4),
            algorithm="ensemble",
            reason_codes=[f"{s.algorithm}:{s.decision}" for s, _ in results],
            details={
                "mode": "majority_vote",
                "buy_weight": round(buy_weight, 4),
                "sell_weight": round(sell_weight, 4),
                "hold_weight": round(hold_weight, 4),
                "member_signals": [
                    (s.algorithm, s.score, w) for s, w in results
                ],
            },
        )

    def _best_confidence(self, results: list[tuple[Signal, float]]) -> Signal:
        """Take the signal with the highest confidence."""
        best_signal, best_weight = max(results, key=lambda pair: pair[0].confidence)

        return Signal(
            symbol=self.ctx.symbol,
            market=self.ctx.market,
            decision=best_signal.decision,
            score=best_signal.score,
            confidence=best_signal.confidence,
            algorithm="ensemble",
            reason_codes=[
                f"BEST:{best_signal.algorithm}",
                *[f"{s.algorithm}:{s.decision}" for s, _ in results],
            ],
            details={
                "mode": "best_confidence",
                "selected": best_signal.algorithm,
                "member_signals": [
                    (s.algorithm, s.score, w) for s, w in results
                ],
            },
        )


# ======================================================================
# Champion / Challenger comparison
# ======================================================================

class ComparisonRunner:
    """Run champion (live) and challenger (shadow) strategies in parallel.

    The champion signal is returned for actual execution.  The
    challenger signal is logged for later performance comparison.

    Parameters
    ----------
    champion:
        The strategy currently used for live trading.
    challenger:
        The candidate strategy running in shadow mode.
    config:
        The ``algorithms.comparison`` sub-dict from settings.yaml.
    log_fn:
        Callable that persists a shadow signal for later analysis.
        Defaults to logger.info if not provided.
    """

    def __init__(
        self,
        champion: BaseAlgorithm | EnsembleRunner,
        challenger: BaseAlgorithm | EnsembleRunner,
        config: dict[str, Any],
        log_fn: Any | None = None,
    ) -> None:
        self.champion = champion
        self.challenger = challenger
        self.config = config
        self._log_fn = log_fn or (lambda sig: logger.info("Shadow signal: %s", sig))

    def run(self, ctx: AlgorithmContext) -> Signal:
        """Execute both strategies; return champion, log challenger."""
        # Champion -- the result that drives actual execution
        if isinstance(self.champion, EnsembleRunner):
            champion_signal = self.champion.run()
        else:
            champion_signal = self.champion.generate_signal(ctx)

        # Challenger -- shadow run (errors are swallowed)
        try:
            if isinstance(self.challenger, EnsembleRunner):
                challenger_signal = self.challenger.run()
            else:
                challenger_signal = self.challenger.generate_signal(ctx)
            self._log_fn(challenger_signal)
        except Exception:
            logger.exception("ComparisonRunner: challenger raised an error.")

        return champion_signal
