"""LangGraph sell-approval workflow with Human-in-the-loop.

Implements the full lifecycle of a sell recommendation:

    START -> validate_holding -> notify_user -> wait_approval (interrupt)
          -> process_decision -> risk_recheck -> execute_sell
          -> record_ledger -> END

The ``wait_approval`` node uses :func:`langgraph.types.interrupt` to
pause graph execution and persist state to a SQLite checkpoint.  The
graph is resumed via :class:`langgraph.types.Command` when the user
responds (approve / reject / modify) or when the timeout batch expires
stale recommendations.

Usage::

    graph = build_sell_approval_graph(config)
    thread_id = f"sell-{recommendation_id}"

    # Start the workflow (pauses at interrupt).
    graph.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})

    # Resume after user approval.
    from langgraph.types import Command
    graph.invoke(
        Command(resume={"decision": "APPROVE", "approved_at": "..."}),
        config={"configurable": {"thread_id": thread_id}},
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .state import SellApprovalState

logger = logging.getLogger(__name__)


# =====================================================================
# Node functions
# =====================================================================

def validate_holding(state: SellApprovalState) -> dict:
    """Check that the target symbol is held and the sell quantity is valid.

    Reads the trade ledger to determine the net quantity for the symbol.
    If the position does not exist or the target quantity exceeds holdings,
    the workflow will short-circuit at the next conditional edge.
    """
    from ..trade_ledger import TradeLedger

    # The trade_ledger instance is injected via the graph config at build
    # time; for portability we also support creating a lightweight one here.
    symbol = state["symbol"]
    market = state["market"]
    target_qty = state.get("target_quantity", 0)

    try:
        # Attempt to use a module-level ledger reference set at build time.
        ledger: TradeLedger = _get_trade_ledger()
        net_qty = ledger.get_net_quantity(symbol, market)
    except Exception as exc:
        logger.warning("validate_holding: ledger lookup failed: %s", exc)
        return {
            "net_quantity": 0,
            "holding_valid": False,
            "validation_reason": f"LEDGER_ERROR: {exc}",
        }

    if net_qty <= 0:
        return {
            "net_quantity": net_qty,
            "holding_valid": False,
            "validation_reason": "NO_OPEN_POSITION",
        }

    if target_qty > net_qty:
        return {
            "net_quantity": net_qty,
            "holding_valid": False,
            "validation_reason": (
                f"OVERSELL: target={target_qty} > held={net_qty}"
            ),
        }

    return {
        "net_quantity": net_qty,
        "holding_valid": True,
        "validation_reason": "OK",
    }


def notify_user(state: SellApprovalState) -> dict:
    """Send a Telegram notification to the user about the sell proposal.

    If the holding validation failed, no notification is sent and the
    node simply records ``user_notified = False``.
    """
    if not state.get("holding_valid", False):
        return {"user_notified": False}

    rec_id = state.get("recommendation_id", "unknown")[:8]
    symbol = state["symbol"]
    market = state["market"]
    action = state.get("action", "SELL")
    target_qty = state.get("target_quantity", 0)
    reason = state.get("reason", "N/A")
    confidence = state.get("confidence", 0.0)
    net_qty = state.get("net_quantity", 0)

    message = (
        f"[SELL PROPOSAL] #{rec_id}\n"
        f"Symbol: {symbol} ({market})\n"
        f"Action: {action} {target_qty} shares\n"
        f"Reason: {reason}\n"
        f"Confidence: {confidence:.0%}\n"
        f"Held: {net_qty} shares\n"
        f"\n"
        f"/approve_{rec_id}  Approve\n"
        f"/reject_{rec_id}   Reject\n"
        f"/modify_{rec_id}   Modify quantity"
    )

    try:
        _send_notification(message)
    except Exception as exc:
        logger.warning("notify_user: notification failed: %s", exc)
        return {
            "user_notified": False,
            "errors": [f"NOTIFICATION_FAILED: {exc}"],
        }

    logger.info("Sell proposal notification sent for %s:%s (#%s)", market, symbol, rec_id)
    return {"user_notified": True}


def wait_for_approval(state: SellApprovalState) -> dict:
    """Pause execution and wait for user input via LangGraph interrupt.

    If the holding was invalid, auto-reject immediately without pausing.
    Otherwise, the graph checkpoints its state and returns control to the
    caller.  The workflow is resumed when :func:`Command(resume=...)` is
    invoked with the user's decision.
    """
    if not state.get("holding_valid", False):
        return {"user_decision": "AUTO_REJECT", "expired": False}

    try:
        from langgraph.types import interrupt
    except ImportError:
        logger.error(
            "langgraph is not installed -- cannot interrupt for approval."
        )
        return {
            "user_decision": "AUTO_REJECT",
            "expired": False,
            "errors": ["LANGGRAPH_NOT_INSTALLED"],
        }

    # --- interrupt: graph pauses here, checkpoint saved ---
    user_input: dict = interrupt(
        {
            "question": (
                f"{state['symbol']} {state.get('action', 'SELL')} "
                f"{state.get('target_quantity', 0)} shares -- approve?"
            ),
            "recommendation_id": state.get("recommendation_id", ""),
        }
    )

    # --- resume: user_input is populated by Command(resume=...) ---
    decision = user_input.get("decision", "REJECT")
    modified_qty = user_input.get("modified_quantity")
    approved_at = user_input.get(
        "approved_at", datetime.now(timezone.utc).isoformat()
    )

    return {
        "user_decision": decision,
        "user_modified_quantity": modified_qty,
        "approved_at": approved_at,
    }


def process_decision(state: SellApprovalState) -> dict:
    """Apply the user's decision to the workflow state.

    For ``MODIFY`` decisions, validate and apply the user-specified
    quantity.  ``APPROVE`` is a pass-through.
    """
    decision = state.get("user_decision", "REJECT")

    if decision == "MODIFY":
        new_qty = state.get("user_modified_quantity")
        if new_qty is None:
            return {"errors": ["MODIFY_WITHOUT_QUANTITY"]}

        net_qty = state.get("net_quantity", 0)
        if new_qty > net_qty:
            return {
                "errors": [
                    f"MODIFIED_QTY_EXCEEDS_HOLDING: {new_qty} > {net_qty}"
                ],
            }
        return {"target_quantity": new_qty}

    # APPROVE -- nothing extra to do.
    return {}


def risk_recheck(state: SellApprovalState) -> dict:
    """Re-run a lightweight risk check at approval time.

    Between recommendation creation and user approval, market conditions
    may have changed.  This node ensures the sell is still safe to
    execute.
    """
    symbol = state["symbol"]
    market = state["market"]
    target_qty = state.get("target_quantity", 0)

    try:
        passed, reason = _check_risk(symbol, market, target_qty)
    except Exception as exc:
        logger.warning("risk_recheck failed: %s", exc)
        return {
            "risk_recheck_passed": False,
            "risk_recheck_reason": f"RISK_CHECK_ERROR: {exc}",
        }

    return {
        "risk_recheck_passed": passed,
        "risk_recheck_reason": reason,
    }


def execute_sell(state: SellApprovalState) -> dict:
    """Execute the approved sell order through the configured executor.

    Uses the :class:`PaperExecutor` in Phase 1-2 and a broker adapter in
    Phase 3.
    """
    try:
        executor = _get_executor()
        result = executor.execute(
            {
                "symbol": state["symbol"],
                "market": state["market"],
                "decision": "SELL",
                "quantity": state.get("target_quantity", 0),
                "price": state.get("target_price"),
            }
        )
    except Exception as exc:
        logger.exception("execute_sell failed for %s:%s", state["market"], state["symbol"])
        return {
            "execution_result": {"status": "ERROR", "reason": str(exc)},
            "errors": [f"EXECUTION_ERROR: {exc}"],
        }

    return {"execution_result": result}


def record_ledger(state: SellApprovalState) -> dict:
    """Write the execution result to the trade ledger.

    Only records if the execution status is ``"FILLED"``.
    """
    result = state.get("execution_result")
    if result is None or result.get("status") != "FILLED":
        return {
            "ledger_recorded": False,
            "errors": ["EXECUTION_NOT_FILLED"],
        }

    try:
        ledger = _get_trade_ledger()
        ledger.record(
            {
                "symbol": state["symbol"],
                "market": state["market"],
                "side": "SELL",
                "quantity": state.get("target_quantity", 0),
                "price": result["price"],
                "source": "sell_recommendation",
                "recommendation_id": state.get("recommendation_id", ""),
            }
        )
    except Exception as exc:
        logger.exception("record_ledger failed")
        return {
            "ledger_recorded": False,
            "errors": [f"LEDGER_RECORD_ERROR: {exc}"],
        }

    logger.info(
        "Trade ledger recorded for %s:%s SELL x%d @ %.4f",
        state["market"],
        state["symbol"],
        state.get("target_quantity", 0),
        result["price"],
    )
    return {"ledger_recorded": True}


# =====================================================================
# Graph builder
# =====================================================================

def build_sell_approval_graph(config: dict) -> Any:
    """Construct and compile the sell-approval LangGraph.

    Parameters
    ----------
    config:
        Application configuration dict.  Used to configure:

        - Checkpoint storage path (``execution.checkpoint_db``,
          default ``"data/langgraph_checkpoints.db"``).
        - Trade ledger and executor references (stored in module-level
          variables for node access).

    Returns
    -------
    CompiledGraph
        A compiled LangGraph ready to be invoked with
        ``.invoke()`` / ``Command(resume=...)``.
    """
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise ImportError(
            "langgraph and langgraph-checkpoint-sqlite are required for "
            "the sell-approval workflow.  Install them with:\n"
            "  pip install langgraph langgraph-checkpoint-sqlite"
        ) from exc

    # Store config for node functions to access.
    _set_config(config)

    checkpoint_path: str = (
        config.get("execution", {})
        .get("checkpoint_db", "data/langgraph_checkpoints.db")
    )

    graph = StateGraph(SellApprovalState)

    # --- Register nodes ---------------------------------------------------
    graph.add_node("validate_holding", validate_holding)
    graph.add_node("notify_user", notify_user)
    graph.add_node("wait_approval", wait_for_approval)
    graph.add_node("process_decision", process_decision)
    graph.add_node("risk_recheck", risk_recheck)
    graph.add_node("execute_sell", execute_sell)
    graph.add_node("record_ledger", record_ledger)

    # --- Edges ------------------------------------------------------------
    graph.add_edge(START, "validate_holding")
    graph.add_edge("validate_holding", "notify_user")
    graph.add_edge("notify_user", "wait_approval")

    # After user decision: proceed only on APPROVE or MODIFY.
    graph.add_conditional_edges(
        "wait_approval",
        _route_after_approval,
        {
            "proceed": "process_decision",
            "end": END,
        },
    )

    graph.add_edge("process_decision", "risk_recheck")

    # After risk re-check: execute only if passed.
    graph.add_conditional_edges(
        "risk_recheck",
        _route_after_risk_recheck,
        {
            "execute": "execute_sell",
            "end": END,
        },
    )

    graph.add_edge("execute_sell", "record_ledger")
    graph.add_edge("record_ledger", END)

    # --- Compile with checkpointer ----------------------------------------
    checkpointer = SqliteSaver.from_conn_string(checkpoint_path)
    compiled = graph.compile(checkpointer=checkpointer)

    logger.info(
        "SellApprovalGraph compiled with checkpoint at %s", checkpoint_path,
    )
    return compiled


# =====================================================================
# Routing functions (used by conditional edges)
# =====================================================================

def _route_after_approval(state: SellApprovalState) -> str:
    """Route after the user approval/reject/modify decision."""
    decision = state.get("user_decision")
    if decision in ("APPROVE", "MODIFY"):
        return "proceed"
    return "end"


def _route_after_risk_recheck(state: SellApprovalState) -> str:
    """Route after the risk re-check node."""
    if state.get("risk_recheck_passed"):
        return "execute"
    return "end"


# =====================================================================
# Timeout / stale recommendation expiry
# =====================================================================

def expire_stale_recommendations(
    config: dict,
    graph: Any,
    *,
    max_hours: float | None = None,
) -> list[str]:
    """Resume and auto-expire sell workflows that have been waiting too long.

    This function is intended to be called periodically (e.g. by a Cloud
    Scheduler job every hour) to clean up recommendations that the user
    never acted upon.

    Parameters
    ----------
    config:
        Application configuration dict.
    graph:
        The compiled sell-approval graph (from :func:`build_sell_approval_graph`).
    max_hours:
        Maximum hours to wait for approval.  Defaults to
        ``config["sell_recommendation"]["approval_timeout_hours"]`` or 48.

    Returns
    -------
    list[str]
        Thread IDs that were expired.
    """
    if max_hours is None:
        max_hours = float(
            config.get("sell_recommendation", {})
            .get("approval_timeout_hours", 48)
        )

    try:
        from langgraph.types import Command
    except ImportError:
        logger.error("langgraph not installed -- cannot expire recommendations.")
        return []

    expired_threads: list[str] = []
    pending = _get_pending_sell_workflows(config)

    for workflow in pending:
        created_at_str = workflow.get("created_at", "")
        thread_id = workflow.get("thread_id", "")

        if not created_at_str or not thread_id:
            continue

        try:
            created_at = datetime.fromisoformat(created_at_str)
            # Ensure timezone-aware comparison.
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            elapsed_hours = (
                datetime.now(timezone.utc) - created_at
            ).total_seconds() / 3600.0
        except (ValueError, TypeError):
            logger.warning(
                "Cannot parse created_at for thread %s: %s",
                thread_id,
                created_at_str,
            )
            continue

        if elapsed_hours > max_hours:
            try:
                graph.invoke(
                    Command(
                        resume={
                            "decision": "TIMEOUT",
                            "approved_at": datetime.now(timezone.utc).isoformat(),
                        }
                    ),
                    config={"configurable": {"thread_id": thread_id}},
                )
                expired_threads.append(thread_id)
                logger.info(
                    "Expired stale sell workflow thread=%s (%.1f hours old)",
                    thread_id,
                    elapsed_hours,
                )
            except Exception:
                logger.exception(
                    "Failed to expire sell workflow thread=%s", thread_id,
                )

    return expired_threads


# =====================================================================
# Module-level service locators
#
# These are set by ``build_sell_approval_graph`` so that node functions
# (which receive only the state dict) can access shared services.
# =====================================================================

_module_config: dict = {}
_module_trade_ledger: Any | None = None
_module_executor: Any | None = None


def _set_config(config: dict) -> None:
    """Store the application config for node access."""
    global _module_config  # noqa: PLW0603
    _module_config = config


def _get_trade_ledger() -> Any:
    """Return the shared TradeLedger, creating one if needed."""
    global _module_trade_ledger  # noqa: PLW0603
    if _module_trade_ledger is None:
        from ..trade_ledger import TradeLedger

        _module_trade_ledger = TradeLedger(config=_module_config)
    return _module_trade_ledger


def _get_executor() -> Any:
    """Return the shared PaperExecutor, creating one if needed."""
    global _module_executor  # noqa: PLW0603
    if _module_executor is None:
        from ..paper_executor import PaperExecutor
        from ..position_manager import PositionManager

        # Lazy-import infrastructure.
        try:
            from ...infrastructure.redis_client import RedisClient
            redis_client = RedisClient(_module_config)
        except Exception:
            # Fallback: create a minimal redis client config.
            from ...infrastructure.redis_client import RedisClient
            redis_client = RedisClient({})

        position_manager = PositionManager(redis_client, _module_config)
        trade_ledger = _get_trade_ledger()
        _module_executor = PaperExecutor(
            config=_module_config,
            redis_client=redis_client,
            position_manager=position_manager,
            trade_ledger=trade_ledger,
        )
    return _module_executor


def set_trade_ledger(ledger: Any) -> None:
    """Allow external callers to inject a TradeLedger instance.

    Useful for testing and when the ledger is already constructed by the
    application bootstrap.
    """
    global _module_trade_ledger  # noqa: PLW0603
    _module_trade_ledger = ledger


def set_executor(executor: Any) -> None:
    """Allow external callers to inject an executor instance.

    Useful for testing and when the executor is already constructed by
    the application bootstrap.
    """
    global _module_executor  # noqa: PLW0603
    _module_executor = executor


def _send_notification(message: str) -> None:
    """Send a notification message (Telegram stub).

    In production, this will delegate to a
    :class:`TelegramNotifier` configured via ``_module_config``.
    For now it simply logs the message.
    """
    logger.info("NOTIFICATION (stub): %s", message)


def _check_risk(
    symbol: str,
    market: str,
    quantity: int,
) -> tuple[bool, str]:
    """Perform a lightweight risk check for a sell order.

    In production, this will call the full risk gate with the current
    portfolio state.  The stub always passes.
    """
    # TODO(Phase 2+): integrate with risk_gate.check()
    logger.info(
        "Risk re-check (stub) for %s:%s SELL x%d -- PASSED",
        market, symbol, quantity,
    )
    return True, "OK"


def _get_pending_sell_workflows(config: dict) -> list[dict]:
    """Return a list of sell workflows currently waiting for approval.

    In production, this queries the LangGraph checkpoint store for
    threads in the interrupted state.  The stub returns an empty list.
    """
    # TODO(Phase 2+): query SqliteSaver for interrupted threads whose
    # state indicates ``user_decision is None``.
    logger.debug("get_pending_sell_workflows (stub): returning empty list")
    return []
