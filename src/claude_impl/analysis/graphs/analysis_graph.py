"""LangGraph ``AnalysisGraph`` -- hybrid analysis pipeline.

Orchestrates the full analysis flow as a LangGraph ``StateGraph``:

    START -> numeric -> trigger -+--> agent_news ----+
                                |    agent_technical |
                                |    agent_regime    +--> agent_fan_in -> fusion -> decision -> risk_gate -> END
                                |    agent_portfolio |
                                +--> (skip) --------+--> fusion -> decision -> risk_gate -> END

Nodes
-----
numeric_node        Run the numeric ensemble engine.
trigger_node        Decide if agents are needed.
agent_news          LLM-based news analysis.
agent_technical     LLM-based technical pattern interpretation.
agent_regime        LLM-based market regime assessment.
agent_portfolio     LLM-based portfolio-aware judgment.
agent_fan_in        Aggregate the 4 agent results into one score.
fusion_node         Blend numeric + agent scores.
decision_node       Map final score to BUY / SELL / HOLD.
risk_gate_node      Apply risk-management checks.

The graph is built by ``build_analysis_graph(config)`` and compiled
with an optional SQLite checkpointer.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, Field

from .state import AnalysisState
from ..hybrid import compute_dynamic_alpha, fuse_scores
from ..router import AlgorithmRouter
from ...models.signal import AlgorithmContext

logger = logging.getLogger(__name__)


# ======================================================================
# Pydantic model for structured LLM output
# ======================================================================

class AgentJudgment(BaseModel):
    """Structured judgment returned by each specialist agent."""

    direction: str = Field(description="BUY / SELL / HOLD")
    score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""
    key_factors: list[str] = Field(default_factory=list)


# ======================================================================
# Context serialisation helpers
# ======================================================================

def serialize_context(ctx: AlgorithmContext) -> dict:
    """Convert an ``AlgorithmContext`` dataclass to a plain dict."""
    return asdict(ctx)


def deserialize_context(d: dict) -> AlgorithmContext:
    """Reconstruct an ``AlgorithmContext`` from a dict."""
    return AlgorithmContext(**d)


# ======================================================================
# Node functions
# ======================================================================

def numeric_node(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """Run the AlgorithmRouter / EnsembleRunner and emit numeric scores."""
    cfg = config or {}
    try:
        ctx = deserialize_context(state["context"])
        router = AlgorithmRouter(cfg)
        signal = router.run(ctx)

        member_signals: list[dict] = []
        raw_members = signal.details.get("member_signals", [])
        for item in raw_members:
            if isinstance(item, (list, tuple)) and len(item) == 3:
                member_signals.append({
                    "algorithm": item[0],
                    "decision": "",
                    "score": item[1],
                    "weight": item[2],
                })
            elif isinstance(item, dict):
                member_signals.append(item)

        return {
            "numeric_score": signal.score,
            "numeric_decision": signal.decision,
            "numeric_confidence": signal.confidence,
            "member_signals": member_signals,
        }
    except Exception as exc:
        logger.exception("numeric_node failed")
        return {
            "numeric_score": 0.0,
            "numeric_decision": "HOLD",
            "numeric_confidence": 0.0,
            "member_signals": [],
            "errors": [f"NUMERIC_NODE_ERROR: {exc}"],
        }


def trigger_node(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """Decide whether the agent overlay is needed."""
    cfg = config or {}
    score = state.get("numeric_score", 0.0)
    reasons: list[str] = []

    analysis_cfg = cfg.get("analysis", {})
    signal_cfg = analysis_cfg.get("signal", {})
    hybrid_cfg = analysis_cfg.get("hybrid", {})
    trigger_cfg = hybrid_cfg.get("agent_trigger", {})

    buy_th: float = signal_cfg.get("buy_threshold", 0.6)
    sell_th: float = signal_cfg.get("sell_threshold", -0.6)
    margin: float = trigger_cfg.get("near_threshold_margin", 0.12)

    if abs(score - buy_th) < margin:
        reasons.append("NEAR_BUY_THRESHOLD")
    if abs(score - sell_th) < margin:
        reasons.append("NEAR_SELL_THRESHOLD")

    # Signal conflict: sentiment vs technical
    members = state.get("member_signals", [])
    sm = next((m for m in members if m.get("algorithm") == "sentiment_momentum"), None)
    tf = next((m for m in members if m.get("algorithm") == "technical_trend"), None)
    if sm and tf and sm.get("score", 0) * tf.get("score", 0) < 0:
        reasons.append("SIGNAL_CONFLICT")

    # High-impact event detection
    high_impact_types: list[str] = trigger_cfg.get(
        "high_impact_event_types",
        ["earnings", "m_and_a", "regulation", "lawsuit"],
    )
    ctx_dict = state.get("context", {})
    for news in ctx_dict.get("news_events", []):
        if news.get("event_type") in high_impact_types:
            reasons.append(f"HIGH_IMPACT:{news['event_type'].upper()}")
            break

    return {
        "agent_required": len(reasons) > 0,
        "trigger_reasons": reasons,
    }


# ------------------------------------------------------------------
# Agent nodes
# ------------------------------------------------------------------

def _safe_agent(
    state: AnalysisState,
    result_key: str,
    error_prefix: str,
    *,
    config: dict[str, Any] | None = None,
) -> dict:
    """Base skeleton for an agent node.

    In production, each agent would build a prompt, call an LLM via
    LangChain, and parse the structured output into ``AgentJudgment``.
    This implementation provides the wiring and graceful error handling
    while keeping LLM calls behind a pluggable interface.
    """
    cfg = config or {}
    llm_runner = cfg.get("_llm_runner")

    if llm_runner is None:
        # No LLM configured -- return a neutral placeholder so the
        # rest of the graph can proceed.
        return {
            result_key: None,
            "errors": [f"{error_prefix}: NO_LLM_CONFIGURED"],
        }

    try:
        ctx = deserialize_context(state["context"])
        judgment: AgentJudgment = llm_runner(
            agent_type=error_prefix.lower(),
            state=state,
            ctx=ctx,
            config=cfg,
        )
        return {result_key: judgment.model_dump()}
    except Exception as exc:
        logger.exception("%s failed", error_prefix)
        return {
            result_key: None,
            "errors": [f"{error_prefix}: {exc}"],
        }


def agent_news(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """LLM-based news context analysis."""
    return _safe_agent(state, "agent_news_result", "NEWS_AGENT_ERROR", config=config)


def agent_technical(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """LLM-based technical pattern interpretation."""
    return _safe_agent(state, "agent_technical_result", "TECH_AGENT_ERROR", config=config)


def agent_regime(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """LLM-based market regime assessment."""
    return _safe_agent(state, "agent_regime_result", "REGIME_AGENT_ERROR", config=config)


def agent_portfolio(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """LLM-based portfolio-aware judgment."""
    return _safe_agent(state, "agent_portfolio_result", "PORT_AGENT_ERROR", config=config)


# ------------------------------------------------------------------
# Fan-in
# ------------------------------------------------------------------

def agent_fan_in(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """Aggregate the 4 agent results into a single agent_score."""
    cfg = config or {}
    langgraph_cfg = cfg.get("analysis", {}).get("langgraph", {})
    weights: dict[str, float] = langgraph_cfg.get("agent_weights", {
        "news": 0.30,
        "technical": 0.30,
        "regime": 0.20,
        "portfolio": 0.20,
    })

    results: list[tuple[float, float, float]] = []
    for key, weight_key in [
        ("agent_news_result", "news"),
        ("agent_technical_result", "technical"),
        ("agent_regime_result", "regime"),
        ("agent_portfolio_result", "portfolio"),
    ]:
        result = state.get(key)
        if result is not None:
            results.append((
                result.get("score", 0.0),
                result.get("confidence", 0.5),
                weights.get(weight_key, 0.25),
            ))

    if not results:
        return {
            "agent_score": None,
            "agent_confidence": None,
            "errors": ["ALL_AGENTS_FAILED"],
        }

    weighted_sum = sum(s * c * w for s, c, w in results)
    total_weight = sum(c * w for _, c, w in results)
    agent_score = weighted_sum / total_weight if total_weight > 0 else 0.0

    weight_total = sum(w for _, _, w in results)
    agent_confidence = (
        sum(c * w for _, c, w in results) / weight_total
        if weight_total > 0 else 0.0
    )

    return {
        "agent_score": round(agent_score, 4),
        "agent_confidence": round(agent_confidence, 4),
    }


# ------------------------------------------------------------------
# Fusion
# ------------------------------------------------------------------

def fusion_node(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """Blend numeric_score and agent_score."""
    cfg = config or {}
    numeric = state.get("numeric_score", 0.0)
    numeric_conf = state.get("numeric_confidence", 0.0)

    if not state.get("agent_required") or state.get("agent_score") is None:
        return {
            "alpha": 1.0,
            "final_score": numeric,
            "final_confidence": numeric_conf,
        }

    hybrid_cfg = cfg.get("analysis", {}).get("hybrid", {})
    alpha = compute_dynamic_alpha(state, hybrid_cfg)
    agent = state.get("agent_score", 0.0) or 0.0
    agent_conf = state.get("agent_confidence", 0.0) or 0.0

    final_score = fuse_scores(numeric, agent, alpha)
    final_confidence = alpha * numeric_conf + (1.0 - alpha) * agent_conf

    return {
        "alpha": round(alpha, 4),
        "final_score": round(final_score, 4),
        "final_confidence": round(final_confidence, 4),
    }


# ------------------------------------------------------------------
# Decision
# ------------------------------------------------------------------

def decision_node(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """Map final_score to BUY / SELL / HOLD."""
    cfg = config or {}
    score = state.get("final_score", 0.0)

    signal_cfg = cfg.get("analysis", {}).get("signal", {})
    buy_th: float = signal_cfg.get("buy_threshold", 0.6)
    sell_th: float = signal_cfg.get("sell_threshold", -0.6)

    if score >= buy_th:
        decision = "BUY"
    elif score <= sell_th:
        decision = "SELL"
    else:
        decision = "HOLD"

    return {"final_decision": decision}


# ------------------------------------------------------------------
# Risk gate
# ------------------------------------------------------------------

def risk_gate_node(state: AnalysisState, *, config: dict[str, Any] | None = None) -> dict:
    """Apply the 3-layer risk check from 07-risk-management.

    A pluggable ``risk_gate.check(signal, portfolio)`` function is
    expected in the config.  When it is absent the node defaults to
    passing all non-HOLD decisions.
    """
    cfg = config or {}

    if state.get("final_decision") == "HOLD":
        return {
            "risk_passed": True,
            "risk_reason": "HOLD_NO_CHECK",
            "action": "HOLD",
        }

    risk_check_fn = cfg.get("_risk_check_fn")
    if risk_check_fn is None:
        # No risk module wired -- default pass-through
        return {
            "risk_passed": True,
            "risk_reason": "NO_RISK_MODULE",
            "action": "EXECUTE",
        }

    ctx_dict = state.get("context", {})
    signal_dict = {
        "symbol": state.get("symbol", ""),
        "market": state.get("market", ""),
        "decision": state.get("final_decision", "HOLD"),
        "score": state.get("final_score", 0.0),
    }
    portfolio = ctx_dict.get("portfolio", {})

    try:
        passed, reason = risk_check_fn(signal_dict, portfolio)
    except Exception as exc:
        logger.exception("risk_gate_node: risk check failed")
        return {
            "risk_passed": False,
            "risk_reason": f"RISK_CHECK_ERROR: {exc}",
            "action": "BLOCKED",
            "errors": [f"RISK_GATE_ERROR: {exc}"],
        }

    return {
        "risk_passed": passed,
        "risk_reason": reason,
        "action": "EXECUTE" if passed else "BLOCKED",
    }


# ======================================================================
# Graph builder
# ======================================================================

def build_analysis_graph(config: dict[str, Any]) -> Any:
    """Construct and compile the full analysis ``StateGraph``.

    Parameters
    ----------
    config:
        Full system configuration dict.  LangGraph-specific settings
        live under ``config["langgraph"]``.

    Returns
    -------
    A compiled ``StateGraph`` (``CompiledGraph``).  When LangGraph is
    not installed the function raises ``ImportError`` with a clear
    message.

    The compiled graph is invoked with::

        result = graph.invoke({
            "symbol": "005930",
            "market": "KR",
            "context": serialize_context(ctx),
            "decision_id": str(uuid4()),
            "created_at": datetime.utcnow().isoformat(),
            "errors": [],
        })
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise ImportError(
            "langgraph is required for build_analysis_graph(). "
            "Install it with: pip install langgraph"
        ) from exc

    graph = StateGraph(AnalysisState)

    # Bind config into each node via a closure
    def _numeric(state: AnalysisState) -> dict:
        return numeric_node(state, config=config)

    def _trigger(state: AnalysisState) -> dict:
        return trigger_node(state, config=config)

    def _agent_news(state: AnalysisState) -> dict:
        return agent_news(state, config=config)

    def _agent_technical(state: AnalysisState) -> dict:
        return agent_technical(state, config=config)

    def _agent_regime(state: AnalysisState) -> dict:
        return agent_regime(state, config=config)

    def _agent_portfolio(state: AnalysisState) -> dict:
        return agent_portfolio(state, config=config)

    def _agent_fan_in(state: AnalysisState) -> dict:
        return agent_fan_in(state, config=config)

    def _fusion(state: AnalysisState) -> dict:
        return fusion_node(state, config=config)

    def _decision(state: AnalysisState) -> dict:
        return decision_node(state, config=config)

    def _risk_gate(state: AnalysisState) -> dict:
        return risk_gate_node(state, config=config)

    # --- Register nodes -----------------------------------------------
    graph.add_node("numeric", _numeric)
    graph.add_node("trigger", _trigger)
    graph.add_node("agent_news", _agent_news)
    graph.add_node("agent_technical", _agent_technical)
    graph.add_node("agent_regime", _agent_regime)
    graph.add_node("agent_portfolio", _agent_portfolio)
    graph.add_node("agent_fan_in", _agent_fan_in)
    graph.add_node("fusion", _fusion)
    graph.add_node("decision", _decision)
    graph.add_node("risk_gate", _risk_gate)

    # --- Edges --------------------------------------------------------
    graph.add_edge(START, "numeric")
    graph.add_edge("numeric", "trigger")

    # Conditional: trigger -> agents or skip to fusion
    graph.add_conditional_edges(
        "trigger",
        lambda s: "agent" if s.get("agent_required") else "skip",
        {
            "agent": "agent_news",
            "skip": "fusion",
        },
    )

    # Agent fan-out: trigger -> 4 agents in parallel -> fan-in
    # LangGraph executes nodes with the same source concurrently when
    # edges are added from the same parent.
    for agent_node_name in ["agent_news", "agent_technical", "agent_regime", "agent_portfolio"]:
        graph.add_edge(agent_node_name, "agent_fan_in")

    # After conditional edge to agent_news, we also need edges from
    # trigger to the other 3 agents for parallel dispatch.
    graph.add_conditional_edges(
        "trigger",
        lambda s: "agent" if s.get("agent_required") else "skip",
        {
            "agent": "agent_technical",
            "skip": "fusion",
        },
    )
    graph.add_conditional_edges(
        "trigger",
        lambda s: "agent" if s.get("agent_required") else "skip",
        {
            "agent": "agent_regime",
            "skip": "fusion",
        },
    )
    graph.add_conditional_edges(
        "trigger",
        lambda s: "agent" if s.get("agent_required") else "skip",
        {
            "agent": "agent_portfolio",
            "skip": "fusion",
        },
    )

    graph.add_edge("agent_fan_in", "fusion")
    graph.add_edge("fusion", "decision")
    graph.add_edge("decision", "risk_gate")
    graph.add_edge("risk_gate", END)

    # --- Compile with optional checkpointer --------------------------
    checkpointer = None
    lg_cfg = config.get("langgraph", {})
    checkpoint_cfg = lg_cfg.get("checkpoint", {})
    backend = checkpoint_cfg.get("backend", "")

    if backend == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            db_path = checkpoint_cfg.get("path", "data/langgraph_checkpoints.db")
            checkpointer = SqliteSaver.from_conn_string(db_path)
        except ImportError:
            logger.warning("langgraph sqlite checkpointer not available, running without.")

    compiled = graph.compile(checkpointer=checkpointer)
    return compiled
