"""AnalysisState TypedDict shared across all LangGraph nodes.

This single state object flows through every node in the analysis
graph.  Each node reads the fields it needs and writes back only the
fields it is responsible for.

Fields are grouped by stage:

* **Input**      -- symbol, market, context
* **Numeric**    -- output of the ensemble / numeric engine
* **Trigger**    -- whether the agent overlay is needed
* **Agent**      -- results from the 4 specialist agents
* **Fusion**     -- blended score
* **Decision**   -- final BUY / SELL / HOLD
* **Risk Gate**  -- post-decision risk check
* **Meta**       -- traceability (UUID, timestamp, cumulative errors)
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class AnalysisState(TypedDict, total=False):
    """Full graph state for the hybrid analysis pipeline."""

    # --- Input --------------------------------------------------------
    symbol: str
    market: str
    context: dict  # serialised AlgorithmContext

    # --- Numeric Stage ------------------------------------------------
    numeric_score: float          # ensemble score in [-1, +1]
    numeric_decision: str         # BUY / SELL / HOLD
    numeric_confidence: float
    member_signals: list[dict]    # per-algorithm results

    # --- Trigger Check ------------------------------------------------
    agent_required: bool
    trigger_reasons: list[str]

    # --- Agent Stage --------------------------------------------------
    agent_news_result: dict | None
    agent_technical_result: dict | None
    agent_regime_result: dict | None
    agent_portfolio_result: dict | None
    agent_score: float | None
    agent_confidence: float | None

    # --- Fusion -------------------------------------------------------
    alpha: float                  # dynamic alpha for blending
    final_score: float
    final_decision: str
    final_confidence: float

    # --- Risk Gate ----------------------------------------------------
    risk_passed: bool
    risk_reason: str
    action: str                   # EXECUTE / HOLD / BLOCKED

    # --- Meta ---------------------------------------------------------
    decision_id: str              # UUID for audit trail
    created_at: str               # ISO 8601
    errors: Annotated[list[str], operator.add]  # cumulative errors
