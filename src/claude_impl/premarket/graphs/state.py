"""Shared state definition for the BriefingGraph.

The ``BriefingState`` TypedDict is the single source of truth flowing
through every node in the briefing LangGraph pipeline.  Each node
receives the full state and returns a *partial* dict that is merged
back by the LangGraph runtime.

The ``errors`` field uses ``Annotated[list[str], operator.add]`` so that
errors produced by any node are *accumulated* (appended) rather than
overwritten.  This lets multiple parallel nodes report failures without
clobbering each other's error messages.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class BriefingState(TypedDict):
    """Shared state for the pre-market briefing graph.

    Attributes
    ----------
    market : str
        Target market identifier -- ``"KR"`` or ``"US"``.
    run_date : str
        ISO date string for the routine run (``"YYYY-MM-DD"``).
    run_id : str
        Unique run identifier (UUID4 string).

    us_close_data : dict | None
        US market close data (S&P 500, NASDAQ, DOW, VIX, Tier 1 US).
        ``None`` if collection failed.
    kr_news_data : list[dict] | None
        KR overnight / morning news articles.
        ``None`` if collection failed.
    dart_data : list[dict] | None
        DART after-market disclosures.
        ``None`` if collection failed.
    event_calendar : list[dict] | None
        Today's event-calendar entries (earnings, FOMC, etc.).
        ``None`` if collection failed.

    sentiment_analysis : list[dict]
        Per-symbol sentiment analysis results.
    overnight_changes : list[dict]
        Per-symbol overnight sentiment change dicts.
    watchlist : list[dict]
        Today's ranked watchlist entries.

    positions_summary : dict | None
        Current portfolio positions overview.
    risk_status : dict | None
        Current risk budget / limits status.

    briefing_text : str
        The final human-readable briefing text.
    briefing_sent : bool
        ``True`` if the briefing was successfully sent via Telegram.

    errors : Annotated[list[str], operator.add]
        Accumulated error messages from all nodes.  Uses ``operator.add``
        so that errors from parallel nodes are concatenated.
    """

    # --- Input ---
    market: str
    run_date: str
    run_id: str

    # --- Collection results (parallel fan-out) ---
    us_close_data: dict | None
    kr_news_data: list[dict] | None
    dart_data: list[dict] | None
    event_calendar: list[dict] | None

    # --- Analysis results ---
    sentiment_analysis: list[dict]
    overnight_changes: list[dict]
    watchlist: list[dict]

    # --- Position / Risk ---
    positions_summary: dict | None
    risk_status: dict | None

    # --- Briefing output ---
    briefing_text: str
    briefing_sent: bool

    # --- Meta (accumulative) ---
    errors: Annotated[list[str], operator.add]
