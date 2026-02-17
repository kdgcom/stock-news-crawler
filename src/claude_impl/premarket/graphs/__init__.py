"""LangGraph-based pre-market briefing pipeline.

This sub-package implements the BriefingGraph -- a LangGraph StateGraph
that orchestrates parallel data collection, LLM-powered sentiment
analysis, watchlist generation, and briefing delivery as a single
checkpointed workflow.

Modules:
    state          -- BriefingState TypedDict shared across all nodes
    briefing_graph -- node functions and ``build_briefing_graph()`` factory
"""

from __future__ import annotations
