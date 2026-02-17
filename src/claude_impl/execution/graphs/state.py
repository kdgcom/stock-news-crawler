"""State definition for the sell-approval LangGraph workflow.

:class:`SellApprovalState` is a :class:`~typing.TypedDict` that captures
the full lifecycle of a sell recommendation -- from initial proposal
through user approval, risk re-check, execution, and ledger recording.

The ``errors`` field uses :func:`operator.add` as its reducer so that
errors from any node are accumulated rather than overwritten.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class SellApprovalState(TypedDict, total=False):
    """Complete state for the sell-approval Human-in-the-loop workflow.

    Fields are grouped by lifecycle phase.  All fields use ``total=False``
    so that only the relevant subset needs to be provided at graph
    invocation time.

    Lifecycle phases
    ----------------
    1. **Input** -- set by the caller when the graph is first invoked.
    2. **Holding validation** -- populated by the ``validate_holding`` node.
    3. **User approval** -- populated by ``notify_user`` and
       ``wait_for_approval`` (interrupt/resume).
    4. **Risk re-check** -- populated by ``risk_recheck`` after user
       approves.
    5. **Execution** -- populated by ``execute_sell`` and ``record_ledger``.
    6. **Meta** -- bookkeeping fields.
    """

    # --- Input ----------------------------------------------------------------
    recommendation_id: str
    """Unique identifier for the sell recommendation."""

    symbol: str
    """Ticker or stock code (e.g. ``"005930"``, ``"AAPL"``)."""

    market: str
    """Market identifier (``"KR"`` or ``"US"``)."""

    action: str
    """Sell action type: ``"SELL"`` (full) or ``"REDUCE"`` (partial)."""

    target_quantity: int
    """Number of shares proposed for sale."""

    target_price: float | None
    """Target price.  ``None`` means market order."""

    reason: str
    """Human-readable sell reason (e.g. ``"TRAILING_STOP_HIT"``)."""

    score: float
    """Analysis score that triggered the recommendation."""

    confidence: float
    """Confidence level of the analysis (0.0 -- 1.0)."""

    # --- Holding validation ---------------------------------------------------
    net_quantity: int
    """Current net held quantity from the trade ledger."""

    holding_valid: bool
    """Whether the holding passed validation (net_quantity > 0, no oversell)."""

    validation_reason: str
    """Validation result detail (``"OK"``, ``"NO_OPEN_POSITION"``, etc.)."""

    # --- User approval --------------------------------------------------------
    user_notified: bool
    """Whether the user has been notified (e.g. via Telegram)."""

    user_decision: str | None
    """User's decision: ``"APPROVE"``, ``"REJECT"``, ``"MODIFY"``, or ``None``
    while waiting."""

    user_modified_quantity: int | None
    """If the user chose ``"MODIFY"``, the new target quantity."""

    approved_at: str | None
    """ISO-8601 timestamp of when the user approved/rejected."""

    # --- Risk re-check --------------------------------------------------------
    risk_recheck_passed: bool | None
    """Whether the approval-time risk gate check passed."""

    risk_recheck_reason: str | None
    """Detail from the risk re-check (``"OK"`` or failure reason)."""

    # --- Execution ------------------------------------------------------------
    execution_result: dict | None
    """Result dict from the executor (``{"status": "FILLED", ...}``)."""

    ledger_recorded: bool
    """Whether the trade was successfully written to the trade ledger."""

    # --- Meta -----------------------------------------------------------------
    created_at: str
    """ISO-8601 timestamp of when the recommendation was created."""

    expired: bool
    """Whether the recommendation timed out before user action."""

    errors: Annotated[list[str], operator.add]
    """Accumulated error messages from any node (uses ``operator.add``
    reducer so errors are appended, never overwritten)."""
