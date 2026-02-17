"""Hybrid fusion logic for blending numeric and agent scores.

The hybrid system overlays an LLM-agent layer on top of the
numeric ensemble engine.  The ``alpha`` parameter controls how
much weight is given to each:

    final_score = alpha * numeric_score + (1 - alpha) * agent_score

``alpha`` is dynamically adjusted based on:

* **Market volatility** -- higher volatility shifts weight toward the
  agent (alpha decreases).
* **News spike** -- a surge in news articles shifts weight toward the
  agent.
* **Agent confidence** -- low agent confidence shifts weight back
  toward the numeric engine (alpha increases).

Functions
---------
compute_dynamic_alpha   Compute alpha from the current state + config.
fuse_scores             Blend numeric and agent scores.
"""

from __future__ import annotations

from typing import Any


def compute_dynamic_alpha(state: dict[str, Any], config: dict[str, Any]) -> float:
    """Determine the blending alpha based on market conditions.

    Parameters
    ----------
    state:
        The ``AnalysisState`` (or equivalent dict) containing at least:
        ``context`` (serialised ``AlgorithmContext``),
        ``agent_confidence``.
    config:
        The ``analysis.hybrid`` sub-dict from settings.yaml.
        Expected keys: ``alpha_default``, ``alpha_volatile``,
        ``alpha_news_spike``.

    Returns
    -------
    float in ``[0.0, 1.0]``.  Higher values favour the numeric engine.
    """
    alpha: float = config.get("alpha_default", 0.7)

    # --- Volatility adjustment ----------------------------------------
    ctx: dict[str, Any] = state.get("context", {})
    regime: str = ctx.get("regime", "sideways")

    if regime == "volatile":
        alpha = min(alpha, config.get("alpha_volatile", 0.5))

    # --- News spike adjustment ----------------------------------------
    news_events = ctx.get("news_events", [])
    if len(news_events) > 10:
        alpha = min(alpha, config.get("alpha_news_spike", 0.4))

    # --- Low agent confidence → trust numeric more --------------------
    agent_confidence: float = state.get("agent_confidence", 0.0) or 0.0
    if agent_confidence < 0.4:
        alpha = max(alpha, 0.85)

    return alpha


def fuse_scores(
    numeric: float,
    agent: float | None,
    alpha: float,
) -> float:
    """Blend numeric and agent scores.

    When ``agent`` is ``None`` (agent timeout / failure), the numeric
    score is returned unchanged (effectively alpha = 1.0).

    Parameters
    ----------
    numeric:
        Score from the ensemble / numeric engine ([-1, +1]).
    agent:
        Score from the agent overlay ([-1, +1]), or ``None``.
    alpha:
        Blending weight for the numeric score.

    Returns
    -------
    Fused score in ``[-1.0, +1.0]``.
    """
    if agent is None:
        return numeric

    return alpha * numeric + (1.0 - alpha) * agent
