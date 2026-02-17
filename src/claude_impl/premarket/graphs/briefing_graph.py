"""LangGraph briefing pipeline -- node functions and graph builder.

Implements the BriefingGraph described in the 05-pre-market LangGraph
design section.  The graph orchestrates:

    START -> 4 parallel collection nodes (fan-out)
          -> analyze_sentiment (fan-in)
          -> build_watchlist
          -> [fetch_positions, adjust_weights] (parallel)
          -> generate_briefing
          -> send_telegram
          -> END

Each collection node handles errors gracefully, returning ``None`` for
its data field plus an error string appended to ``errors``.  Downstream
analysis nodes operate on whatever data is available, enabling *partial
briefings* when one or more collectors fail.

Usage::

    graph = build_briefing_graph(config)
    result = graph.invoke(
        {
            "market": "KR",
            "run_date": "2026-02-17",
            "run_id": str(uuid4()),
            "errors": [],
        },
        config={"configurable": {"thread_id": "briefing-KR-2026-02-17"}},
    )
"""

from __future__ import annotations

import logging
from statistics import mean
from typing import Any

from .state import BriefingState

logger = logging.getLogger(__name__)


# =====================================================================
# Helper utilities
# =====================================================================

def _nested_get(d: dict, dotted_key: str, default: Any = None) -> Any:
    """Retrieve a value from a nested dict using a dotted key path."""
    keys = dotted_key.split(".")
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(k)
        if current is None:
            return default
    return current


def _classify_change(change: float) -> str:
    """Classify a sentiment change into POSITIVE / NEGATIVE / NEUTRAL."""
    if abs(change) < 0.1:
        return "NEUTRAL"
    return "POSITIVE" if change > 0 else "NEGATIVE"


# =====================================================================
# Node function factory
# =====================================================================
# Each ``make_*`` factory accepts the relevant dependency (collector,
# analyzer, etc.) and returns a node function that LangGraph will
# invoke with the shared ``BriefingState``.
#
# The factory pattern avoids global mutable state and makes unit
# testing straightforward.
# =====================================================================


def _make_collect_us_close(collector: Any):
    """Create the ``collect_us_close`` node function.

    Parameters
    ----------
    collector:
        Object with a ``fetch_close_data() -> dict`` method.
    """

    def collect_us_close(state: BriefingState) -> dict:
        """Collect US market close data (S&P 500, NASDAQ, DOW, VIX, Tier 1 US)."""
        try:
            logger.info("[collect_us_close] Fetching US close data.")
            data = collector.fetch_close_data()
            logger.info("[collect_us_close] Success.")
            return {"us_close_data": data}
        except Exception as exc:
            msg = f"US_CLOSE_FAIL: {exc}"
            logger.error("[collect_us_close] %s", msg, exc_info=True)
            return {"us_close_data": None, "errors": [msg]}

    return collect_us_close


def _make_collect_kr_news(collector: Any, config: dict):
    """Create the ``collect_kr_news`` node function.

    Parameters
    ----------
    collector:
        Object with a ``fetch_since(hours=int) -> list[dict]`` method.
    config:
        Application config dict (reads ``collection.news.pre_market_lookback_hours``).
    """
    lookback = int(_nested_get(config, "collection.news.pre_market_lookback_hours", 12))

    def collect_kr_news(state: BriefingState) -> dict:
        """Collect KR overnight/morning news (12-hour lookback)."""
        try:
            logger.info("[collect_kr_news] Fetching news (lookback=%dh).", lookback)
            articles = collector.fetch_since(hours=lookback)
            logger.info("[collect_kr_news] Collected %d articles.", len(articles))
            return {"kr_news_data": articles}
        except Exception as exc:
            msg = f"KR_NEWS_FAIL: {exc}"
            logger.error("[collect_kr_news] %s", msg, exc_info=True)
            return {"kr_news_data": None, "errors": [msg]}

    return collect_kr_news


def _make_collect_dart(collector: Any):
    """Create the ``collect_dart`` node function.

    Parameters
    ----------
    collector:
        Object with a ``fetch_after_market() -> list[dict]`` method.
    """

    def collect_dart(state: BriefingState) -> dict:
        """Collect DART after-market disclosures."""
        try:
            logger.info("[collect_dart] Fetching DART filings.")
            filings = collector.fetch_after_market()
            logger.info("[collect_dart] Collected %d filings.", len(filings))
            return {"dart_data": filings}
        except Exception as exc:
            msg = f"DART_FAIL: {exc}"
            logger.error("[collect_dart] %s", msg, exc_info=True)
            return {"dart_data": None, "errors": [msg]}

    return collect_dart


def _make_collect_events(collector: Any):
    """Create the ``collect_events`` node function.

    Parameters
    ----------
    collector:
        Object with a ``fetch_today(market: str) -> list[dict]`` method.
    """

    def collect_events(state: BriefingState) -> dict:
        """Collect today's event calendar (earnings, FOMC, etc.)."""
        try:
            market = state.get("market", "KR")
            logger.info("[collect_events] Fetching events for %s.", market)
            events = collector.fetch_today(market)
            logger.info("[collect_events] Collected %d events.", len(events))
            return {"event_calendar": events}
        except Exception as exc:
            msg = f"EVENTS_FAIL: {exc}"
            logger.error("[collect_events] %s", msg, exc_info=True)
            return {"event_calendar": None, "errors": [msg]}

    return collect_events


def _make_analyze_sentiment(sentiment_analyzer: Any, config: dict):
    """Create the ``analyze_sentiment`` node function.

    Parameters
    ----------
    sentiment_analyzer:
        Object with:
        - ``analyze_batch(articles, symbol) -> dict``
        - ``query_daily_sentiment(symbol, market, days_ago) -> float``
        - ``query_recent_news(symbol, market, hours) -> list[dict]``
    config:
        Application config dict.
    """
    lookback = int(_nested_get(config, "collection.news.pre_market_lookback_hours", 12))

    def _get_tier1_symbols(market: str) -> list[str]:
        key = f"universe.tier1.{market.lower()}.symbols"
        symbols = _nested_get(config, key, [])
        return symbols if isinstance(symbols, list) else []

    def analyze_sentiment(state: BriefingState) -> dict:
        """Analyse Tier 1 symbol sentiment + compute overnight changes."""
        news = state.get("kr_news_data") or []
        dart = state.get("dart_data") or []
        all_items = news + dart

        if not all_items:
            logger.warning("[analyze_sentiment] No news data available.")
            return {
                "sentiment_analysis": [],
                "overnight_changes": [],
                "errors": ["NO_NEWS_DATA_FOR_ANALYSIS"],
            }

        market = state.get("market", "KR")
        tier1 = _get_tier1_symbols(market)
        sentiments: list[dict] = []
        changes: list[dict] = []

        for symbol in tier1:
            related = [a for a in all_items if symbol in a.get("symbols", [])]
            if not related:
                continue

            # LLM-powered sentiment analysis (batch)
            try:
                sentiment_result = sentiment_analyzer.analyze_batch(related, symbol)
                sentiments.append({"symbol": symbol, **sentiment_result})
            except Exception as exc:
                logger.warning(
                    "[analyze_sentiment] Failed for %s: %s", symbol, exc,
                )

            # Overnight sentiment change
            try:
                prev = sentiment_analyzer.query_daily_sentiment(symbol, market, days_ago=1)
                overnight_news = sentiment_analyzer.query_recent_news(
                    symbol, market, hours=lookback,
                )
                if not overnight_news:
                    continue

                scores = [
                    n.get("sentiment_score", 0.0)
                    for n in overnight_news
                    if isinstance(n.get("sentiment_score"), (int, float))
                ]
                current = mean(scores) if scores else 0.0
                change = current - prev

                changes.append({
                    "symbol": symbol,
                    "previous": prev,
                    "current": round(current, 4),
                    "change": round(change, 4),
                    "article_count": len(overnight_news),
                    "signal": _classify_change(change),
                })
            except Exception as exc:
                logger.warning(
                    "[analyze_sentiment] Overnight change failed for %s: %s",
                    symbol, exc,
                )

        logger.info(
            "[analyze_sentiment] Completed: %d sentiments, %d changes.",
            len(sentiments), len(changes),
        )
        return {
            "sentiment_analysis": sentiments,
            "overnight_changes": changes,
        }

    return analyze_sentiment


def _make_build_watchlist(config: dict):
    """Create the ``build_watchlist`` node function."""
    from ..watchlist import WatchlistGenerator

    generator = WatchlistGenerator(config)

    def build_watchlist(state: BriefingState) -> dict:
        """Generate the daily watchlist from sentiment changes + events."""
        logger.info("[build_watchlist] Generating watchlist.")
        watchlist = generator.generate(
            market=state.get("market", "KR"),
            sentiment_changes=state.get("overnight_changes", []),
            events=state.get("event_calendar") or [],
        )
        logger.info("[build_watchlist] Generated %d entries.", len(watchlist))
        return {"watchlist": watchlist}

    return build_watchlist


def _make_fetch_positions(positions_provider: Any | None):
    """Create the ``fetch_positions`` node function.

    Parameters
    ----------
    positions_provider:
        Object with a ``get_summary(market: str) -> dict`` method, or
        ``None`` if no positions provider is configured.
    """

    def fetch_positions(state: BriefingState) -> dict:
        """Fetch current portfolio positions."""
        if positions_provider is None:
            logger.warning("[fetch_positions] No provider configured.")
            return {"positions_summary": None}

        try:
            market = state.get("market", "KR")
            logger.info("[fetch_positions] Fetching positions for %s.", market)
            summary = positions_provider.get_summary(market)
            return {"positions_summary": summary}
        except Exception as exc:
            msg = f"POSITIONS_FAIL: {exc}"
            logger.error("[fetch_positions] %s", msg, exc_info=True)
            return {"positions_summary": None, "errors": [msg]}

    return fetch_positions


def _make_adjust_weights(config: dict):
    """Create the ``adjust_weights`` node function.

    Adjusts daily signal weights based on market conditions (VIX level,
    earnings season, FOMC days).
    """
    normal_weights = _nested_get(config, "analysis.signal.weights.normal", {
        "sentiment": 0.4, "momentum": 0.3, "volume": 0.3,
    })
    volatile_weights = _nested_get(config, "analysis.signal.weights.volatile", {
        "sentiment": 0.2, "momentum": 0.4, "volume": 0.4,
    })
    earnings_weights = _nested_get(config, "analysis.signal.weights.earnings_season", {
        "sentiment": 0.5, "momentum": 0.2, "volume": 0.3,
    })

    def adjust_weights(state: BriefingState) -> dict:
        """Adjust signal weights based on today's market conditions."""
        logger.info("[adjust_weights] Evaluating market conditions.")

        events = state.get("event_calendar") or []
        us_close = state.get("us_close_data") or {}

        # Count earnings events
        earnings_count = sum(
            1 for e in events
            if "earnings" in e.get("type", "").lower()
            or "실적" in e.get("description", "")
        )

        # Check for FOMC
        fomc_today = any(
            "fomc" in e.get("type", "").lower()
            or "FOMC" in e.get("description", "")
            for e in events
        )

        # VIX level
        vix_data = us_close.get("vix", {})
        vix_level = vix_data.get("close", 0.0) if isinstance(vix_data, dict) else 0.0

        if earnings_count > 5:
            weights = earnings_weights
            reason = f"earnings_season (count={earnings_count})"
        elif vix_level > 25 or fomc_today:
            weights = volatile_weights
            reason = f"volatile (VIX={vix_level}, FOMC={fomc_today})"
        else:
            weights = normal_weights
            reason = "normal"

        logger.info("[adjust_weights] Selected: %s -> %s", reason, weights)
        return {"risk_status": {"adjusted_weights": weights, "weight_reason": reason}}

    return adjust_weights


def _make_generate_briefing(config: dict):
    """Create the ``generate_briefing`` node function."""
    from ..briefing import BriefingGenerator

    generator = BriefingGenerator(config)

    def generate_briefing(state: BriefingState) -> dict:
        """Generate the full briefing text from all collected/analysed data."""
        market = state.get("market", "KR")
        run_date = state.get("run_date", "")

        logger.info("[generate_briefing] Building %s briefing for %s.", market, run_date)

        briefing_data: dict[str, Any] = {
            "run_date": run_date,
            "us_close": state.get("us_close_data") or {},
            "kr_close": state.get("us_close_data") or {},  # reused when KR close is source
            "news_items": (state.get("kr_news_data") or []) + (state.get("dart_data") or []),
            "watchlist": state.get("watchlist", []),
            "positions": state.get("positions_summary") or {},
            "risk_status": state.get("risk_status") or {},
            "events": state.get("event_calendar") or [],
        }

        if market == "KR":
            text = generator.generate_kr_morning(briefing_data)
        else:
            text = generator.generate_us_evening(briefing_data)

        logger.info("[generate_briefing] Briefing generated (%d chars).", len(text))
        return {"briefing_text": text}

    return generate_briefing


def _make_send_telegram(notifier: Any | None):
    """Create the ``send_telegram`` node function.

    Parameters
    ----------
    notifier:
        Object with a ``send(text: str, parse_mode: str) -> None`` method,
        or ``None`` if Telegram is not configured.
    """

    def send_telegram(state: BriefingState) -> dict:
        """Send the generated briefing via Telegram."""
        if notifier is None:
            logger.warning("[send_telegram] No notifier configured; skipping.")
            return {"briefing_sent": False, "errors": ["TELEGRAM_NOT_CONFIGURED"]}

        text = state.get("briefing_text", "")
        if not text:
            logger.warning("[send_telegram] Empty briefing text; skipping.")
            return {"briefing_sent": False, "errors": ["EMPTY_BRIEFING_TEXT"]}

        try:
            logger.info("[send_telegram] Sending briefing (%d chars).", len(text))
            notifier.send(text, parse_mode="HTML")
            logger.info("[send_telegram] Briefing sent successfully.")
            return {"briefing_sent": True}
        except Exception as exc:
            msg = f"TELEGRAM_FAIL: {exc}"
            logger.error("[send_telegram] %s", msg, exc_info=True)
            return {"briefing_sent": False, "errors": [msg]}

    return send_telegram


# =====================================================================
# Graph builder
# =====================================================================

def build_briefing_graph(config: dict):
    """Build and compile the BriefingGraph.

    Parameters
    ----------
    config:
        Application configuration dict.  Expected structure::

            {
                "collectors": {
                    "us_market": <collector>,
                    "kr_news": <collector>,
                    "dart": <collector>,
                    "event_calendar": <collector>,
                },
                "analyzers": {
                    "sentiment": <analyzer>,
                },
                "positions_provider": <provider> | None,
                "notifier": <telegram_notifier> | None,
                "app": { ... },  # the main app config dict
                "langgraph": {
                    "checkpoint": {
                        "path": "data/langgraph_checkpoints.db",
                    },
                },
            }

    Returns
    -------
    CompiledGraph
        A LangGraph compiled graph ready for ``.invoke()`` or
        ``.stream()`` calls.
    """
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.sqlite import SqliteSaver

    # Extract dependencies from config
    collectors = config.get("collectors", {})
    analyzers = config.get("analyzers", {})
    app_config = config.get("app", {})
    positions_provider = config.get("positions_provider")
    notifier = config.get("notifier")

    checkpoint_path = _nested_get(
        config, "langgraph.checkpoint.path", "data/langgraph_checkpoints.db",
    )

    # Build node functions from factories
    collect_us_close_fn = _make_collect_us_close(collectors.get("us_market"))
    collect_kr_news_fn = _make_collect_kr_news(collectors.get("kr_news"), app_config)
    collect_dart_fn = _make_collect_dart(collectors.get("dart"))
    collect_events_fn = _make_collect_events(collectors.get("event_calendar"))
    analyze_sentiment_fn = _make_analyze_sentiment(analyzers.get("sentiment"), app_config)
    build_watchlist_fn = _make_build_watchlist(app_config)
    fetch_positions_fn = _make_fetch_positions(positions_provider)
    adjust_weights_fn = _make_adjust_weights(app_config)
    generate_briefing_fn = _make_generate_briefing(app_config)
    send_telegram_fn = _make_send_telegram(notifier)

    # Build the StateGraph
    graph = StateGraph(BriefingState)

    # --- Collection nodes (parallel fan-out from START) ---
    graph.add_node("collect_us_close", collect_us_close_fn)
    graph.add_node("collect_kr_news", collect_kr_news_fn)
    graph.add_node("collect_dart", collect_dart_fn)
    graph.add_node("collect_events", collect_events_fn)

    # --- Analysis nodes ---
    graph.add_node("analyze_sentiment", analyze_sentiment_fn)
    graph.add_node("build_watchlist", build_watchlist_fn)
    graph.add_node("fetch_positions", fetch_positions_fn)
    graph.add_node("adjust_weights", adjust_weights_fn)

    # --- Output nodes ---
    graph.add_node("generate_briefing", generate_briefing_fn)
    graph.add_node("send_telegram", send_telegram_fn)

    # --- Edges: START -> 4 collection nodes (parallel fan-out) ---
    for node in ["collect_us_close", "collect_kr_news", "collect_dart", "collect_events"]:
        graph.add_edge(START, node)

    # --- Edges: 4 collection nodes -> analyze_sentiment (fan-in) ---
    for node in ["collect_us_close", "collect_kr_news", "collect_dart", "collect_events"]:
        graph.add_edge(node, "analyze_sentiment")

    # --- Edges: analyze_sentiment -> build_watchlist ---
    graph.add_edge("analyze_sentiment", "build_watchlist")

    # --- Edges: build_watchlist -> [fetch_positions, adjust_weights] (parallel) ---
    graph.add_edge("build_watchlist", "fetch_positions")
    graph.add_edge("build_watchlist", "adjust_weights")

    # --- Edges: [fetch_positions, adjust_weights] -> generate_briefing (fan-in) ---
    graph.add_edge("fetch_positions", "generate_briefing")
    graph.add_edge("adjust_weights", "generate_briefing")

    # --- Edges: generate_briefing -> send_telegram -> END ---
    graph.add_edge("generate_briefing", "send_telegram")
    graph.add_edge("send_telegram", END)

    # --- Compile with SQLite checkpointer ---
    logger.info("Building BriefingGraph with checkpoint at: %s", checkpoint_path)
    checkpointer = SqliteSaver.from_conn_string(checkpoint_path)
    compiled = graph.compile(checkpointer=checkpointer)

    logger.info("BriefingGraph compiled successfully.")
    return compiled
