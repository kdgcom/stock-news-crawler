"""LangGraph graph definitions for the analysis engine.

Provides the ``AnalysisGraph`` compiled graph that orchestrates the
full hybrid analysis pipeline (numeric -> trigger -> agents -> fusion
-> decision -> risk gate).
"""

from __future__ import annotations
