"""Pre-market routine orchestration for KR and US markets.

Implements the daily pre-market pipeline described in the 05-pre-market
design document.  Each routine collects market data, analyses overnight
news sentiment, generates a watchlist, and delivers a briefing via
Telegram.

Typical usage::

    routine = PreMarketRoutine(
        config=config,
        collectors={
            "us_market": us_market_collector,
            "kr_news": kr_news_collector,
            "dart": dart_collector,
            "event_calendar": event_calendar,
        },
        storage={
            "news_writer": news_bq_writer,
            "price_writer": price_bq_writer,
            "cache": redis_client,
        },
        analyzers={
            "sentiment": sentiment_analyzer,
            "notifier": telegram_notifier,
        },
    )
    summary = routine.run_kr_morning()
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from .briefing import BriefingGenerator
from .watchlist import WatchlistGenerator

logger = logging.getLogger(__name__)


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


class PreMarketRoutine:
    """Orchestrates the full pre-market data collection and analysis pipeline.

    Parameters
    ----------
    config:
        Application configuration dict (loaded from settings.yaml).
    collectors:
        Dict of collector instances keyed by role:
        ``us_market``, ``kr_news``, ``dart``, ``event_calendar``.
    storage:
        Dict of storage instances keyed by role:
        ``news_writer``, ``price_writer``, ``cache``.
    analyzers:
        Dict of analysis / notification instances keyed by role:
        ``sentiment``, ``notifier``.
    """

    def __init__(
        self,
        config: dict,
        collectors: dict,
        storage: dict,
        analyzers: dict,
    ) -> None:
        self._config = config
        self._collectors = collectors
        self._storage = storage
        self._analyzers = analyzers

        self._watchlist_gen = WatchlistGenerator(config)
        self._briefing_gen = BriefingGenerator(config)

        self._lookback_hours: int = int(
            _nested_get(config, "collection.news.pre_market_lookback_hours", 12)
        )

    # ------------------------------------------------------------------
    # KR Morning Routine (07:30 KST)
    # ------------------------------------------------------------------

    def run_kr_morning(self) -> dict:
        """Execute the KR morning pre-market routine.

        Steps
        -----
        1. Collect US close data (S&P 500, NASDAQ, DOW, VIX, Tier 1 US).
        2. Collect KR overnight / morning news (12-hour lookback).
        3. Collect DART after-market disclosures.
        4. Analyse news sentiment for Tier 1 KR symbols.
        5. Compute overnight sentiment changes.
        6. Generate the daily watchlist.
        7. Build and send the KR Morning Briefing.

        Returns
        -------
        dict
            Summary with keys ``us_close``, ``news_items``, ``dart_items``,
            ``sentiment_results``, ``overnight_changes``, ``watchlist``,
            ``briefing_sent``, ``errors``.
        """
        logger.info("KR morning routine started.")
        errors: list[str] = []
        run_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        # Step 1 -- US close data
        us_close: dict | None = None
        try:
            logger.info("[1/7] Collecting US close data.")
            us_market_collector = self._collectors.get("us_market")
            if us_market_collector is not None:
                us_close = us_market_collector.fetch_close_data()
                logger.info("US close data collected successfully.")
            else:
                logger.warning("us_market collector not configured; skipping.")
        except Exception as exc:
            msg = f"US_CLOSE_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 2 -- KR overnight / morning news
        news_items: list[dict] = []
        try:
            logger.info("[2/7] Collecting KR overnight/morning news (%dh lookback).", self._lookback_hours)
            kr_news_collector = self._collectors.get("kr_news")
            if kr_news_collector is not None:
                news_items = kr_news_collector.fetch_since(hours=self._lookback_hours)
                logger.info("Collected %d KR news articles.", len(news_items))
            else:
                logger.warning("kr_news collector not configured; skipping.")
        except Exception as exc:
            msg = f"KR_NEWS_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 3 -- DART disclosures
        dart_items: list[dict] = []
        try:
            logger.info("[3/7] Collecting DART after-market disclosures.")
            dart_collector = self._collectors.get("dart")
            if dart_collector is not None:
                dart_items = dart_collector.fetch_after_market()
                logger.info("Collected %d DART disclosures.", len(dart_items))
            else:
                logger.warning("dart collector not configured; skipping.")
        except Exception as exc:
            msg = f"DART_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 4 -- Sentiment analysis for Tier 1 KR symbols
        all_items = news_items + dart_items
        sentiment_results: list[dict] = []
        try:
            logger.info("[4/7] Analysing sentiment for Tier 1 KR symbols.")
            sentiment_analyzer = self._analyzers.get("sentiment")
            if sentiment_analyzer is not None and all_items:
                tier1_symbols = self._get_tier1_symbols("KR")
                for symbol in tier1_symbols:
                    related = [
                        a for a in all_items if symbol in a.get("symbols", [])
                    ]
                    if not related:
                        continue
                    result = sentiment_analyzer.analyze_batch(related, symbol)
                    sentiment_results.append({"symbol": symbol, **result})
                logger.info("Sentiment analysis completed for %d symbols.", len(sentiment_results))
            elif not all_items:
                logger.warning("No news/DART items available for sentiment analysis.")
            else:
                logger.warning("sentiment analyzer not configured; skipping.")
        except Exception as exc:
            msg = f"SENTIMENT_ANALYSIS_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 5 -- Overnight sentiment changes
        overnight_changes: list[dict] = []
        try:
            logger.info("[5/7] Computing overnight sentiment changes.")
            tier1_symbols = self._get_tier1_symbols("KR")
            for symbol in tier1_symbols:
                change = self.compute_overnight_sentiment(symbol, "KR")
                if change["signal"] != "NO_NEWS":
                    overnight_changes.append({"symbol": symbol, **change})
            logger.info("Computed overnight changes for %d symbols.", len(overnight_changes))
        except Exception as exc:
            msg = f"OVERNIGHT_SENTIMENT_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 6 -- Watchlist generation
        events = self._collect_events("KR", errors)
        watchlist: list[dict] = []
        try:
            logger.info("[6/7] Generating daily watchlist.")
            watchlist = self._watchlist_gen.generate(
                market="KR",
                sentiment_changes=overnight_changes,
                events=events,
            )
            logger.info("Watchlist generated with %d entries.", len(watchlist))
        except Exception as exc:
            msg = f"WATCHLIST_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 7 -- Briefing
        briefing_sent = False
        try:
            logger.info("[7/7] Generating and sending KR Morning Briefing.")
            briefing_data: dict[str, Any] = {
                "run_date": run_date,
                "us_close": us_close or {},
                "news_items": news_items + dart_items,
                "watchlist": watchlist,
                "positions": self._fetch_positions("KR"),
                "risk_status": self._fetch_risk_status("KR"),
                "events": events,
            }
            briefing_text = self._briefing_gen.generate_kr_morning(briefing_data)

            notifier = self._analyzers.get("notifier")
            if notifier is not None:
                notifier.send(briefing_text, parse_mode="HTML")
                briefing_sent = True
                logger.info("KR Morning Briefing sent successfully.")
            else:
                logger.warning("notifier not configured; briefing generated but not sent.")
        except Exception as exc:
            msg = f"BRIEFING_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        summary = {
            "market": "KR",
            "run_date": run_date,
            "us_close": us_close,
            "news_items": len(news_items),
            "dart_items": len(dart_items),
            "sentiment_results": sentiment_results,
            "overnight_changes": overnight_changes,
            "watchlist": watchlist,
            "briefing_sent": briefing_sent,
            "errors": errors,
        }
        logger.info("KR morning routine completed. Errors: %d", len(errors))
        return summary

    # ------------------------------------------------------------------
    # US Evening Routine (22:00 KST)
    # ------------------------------------------------------------------

    def run_us_evening(self) -> dict:
        """Execute the US evening pre-market routine.

        Steps
        -----
        1. Collect KR close data (KOSPI, KOSDAQ, Tier 1 KR positions PnL).
        2. Collect US pre-market news (lookback from KR close).
        3. Collect SEC EDGAR after-market filings.
        4. Analyse news sentiment for Tier 1 US symbols.
        5. Compute overnight sentiment changes.
        6. Generate the daily watchlist.
        7. Build and send the US Evening Briefing.

        Returns
        -------
        dict
            Summary dict matching the same schema as ``run_kr_morning``.
        """
        logger.info("US evening routine started.")
        errors: list[str] = []
        run_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        # Step 1 -- KR close data
        kr_close: dict | None = None
        try:
            logger.info("[1/7] Collecting KR close data.")
            kr_market_collector = self._collectors.get("kr_market")
            if kr_market_collector is not None:
                kr_close = kr_market_collector.fetch_close_data()
                logger.info("KR close data collected successfully.")
            else:
                logger.warning("kr_market collector not configured; skipping.")
        except Exception as exc:
            msg = f"KR_CLOSE_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 2 -- US pre-market news
        news_items: list[dict] = []
        try:
            logger.info("[2/7] Collecting US pre-market news (%dh lookback).", self._lookback_hours)
            us_news_collector = self._collectors.get("us_news")
            if us_news_collector is not None:
                news_items = us_news_collector.fetch_since(hours=self._lookback_hours)
                logger.info("Collected %d US news articles.", len(news_items))
            else:
                logger.warning("us_news collector not configured; skipping.")
        except Exception as exc:
            msg = f"US_NEWS_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 3 -- SEC EDGAR filings
        sec_items: list[dict] = []
        try:
            logger.info("[3/7] Collecting SEC EDGAR after-market filings.")
            sec_collector = self._collectors.get("sec_edgar")
            if sec_collector is not None:
                sec_items = sec_collector.fetch_after_market()
                logger.info("Collected %d SEC filings.", len(sec_items))
            else:
                logger.warning("sec_edgar collector not configured; skipping.")
        except Exception as exc:
            msg = f"SEC_EDGAR_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 4 -- Sentiment analysis for Tier 1 US symbols
        all_items = news_items + sec_items
        sentiment_results: list[dict] = []
        try:
            logger.info("[4/7] Analysing sentiment for Tier 1 US symbols.")
            sentiment_analyzer = self._analyzers.get("sentiment")
            if sentiment_analyzer is not None and all_items:
                tier1_symbols = self._get_tier1_symbols("US")
                for symbol in tier1_symbols:
                    related = [
                        a for a in all_items if symbol in a.get("symbols", [])
                    ]
                    if not related:
                        continue
                    result = sentiment_analyzer.analyze_batch(related, symbol)
                    sentiment_results.append({"symbol": symbol, **result})
                logger.info("Sentiment analysis completed for %d symbols.", len(sentiment_results))
            elif not all_items:
                logger.warning("No news/SEC items available for sentiment analysis.")
            else:
                logger.warning("sentiment analyzer not configured; skipping.")
        except Exception as exc:
            msg = f"SENTIMENT_ANALYSIS_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 5 -- Overnight sentiment changes
        overnight_changes: list[dict] = []
        try:
            logger.info("[5/7] Computing overnight sentiment changes.")
            tier1_symbols = self._get_tier1_symbols("US")
            for symbol in tier1_symbols:
                change = self.compute_overnight_sentiment(symbol, "US")
                if change["signal"] != "NO_NEWS":
                    overnight_changes.append({"symbol": symbol, **change})
            logger.info("Computed overnight changes for %d symbols.", len(overnight_changes))
        except Exception as exc:
            msg = f"OVERNIGHT_SENTIMENT_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 6 -- Watchlist generation
        events = self._collect_events("US", errors)
        watchlist: list[dict] = []
        try:
            logger.info("[6/7] Generating daily watchlist.")
            watchlist = self._watchlist_gen.generate(
                market="US",
                sentiment_changes=overnight_changes,
                events=events,
            )
            logger.info("Watchlist generated with %d entries.", len(watchlist))
        except Exception as exc:
            msg = f"WATCHLIST_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        # Step 7 -- Briefing
        briefing_sent = False
        try:
            logger.info("[7/7] Generating and sending US Evening Briefing.")
            briefing_data: dict[str, Any] = {
                "run_date": run_date,
                "kr_close": kr_close or {},
                "news_items": news_items + sec_items,
                "watchlist": watchlist,
                "positions": self._fetch_positions("US"),
                "risk_status": self._fetch_risk_status("US"),
                "events": events,
            }
            briefing_text = self._briefing_gen.generate_us_evening(briefing_data)

            notifier = self._analyzers.get("notifier")
            if notifier is not None:
                notifier.send(briefing_text, parse_mode="HTML")
                briefing_sent = True
                logger.info("US Evening Briefing sent successfully.")
            else:
                logger.warning("notifier not configured; briefing generated but not sent.")
        except Exception as exc:
            msg = f"BRIEFING_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)

        summary = {
            "market": "US",
            "run_date": run_date,
            "kr_close": kr_close,
            "news_items": len(news_items),
            "sec_items": len(sec_items),
            "sentiment_results": sentiment_results,
            "overnight_changes": overnight_changes,
            "watchlist": watchlist,
            "briefing_sent": briefing_sent,
            "errors": errors,
        }
        logger.info("US evening routine completed. Errors: %d", len(errors))
        return summary

    # ------------------------------------------------------------------
    # Overnight Sentiment Computation
    # ------------------------------------------------------------------

    def compute_overnight_sentiment(self, symbol: str, market: str) -> dict:
        """Compare previous day's sentiment with overnight news sentiment.

        Parameters
        ----------
        symbol:
            Ticker symbol (e.g. ``"005930"`` for KR, ``"AAPL"`` for US).
        market:
            ``"KR"`` or ``"US"``.

        Returns
        -------
        dict
            Keys: ``previous`` (float), ``current`` (float), ``change`` (float),
            ``article_count`` (int), ``signal`` (str -- ``POSITIVE``,
            ``NEGATIVE``, or ``NEUTRAL``).  When no overnight news exists,
            ``signal`` is ``"NO_NEWS"`` and ``change`` is ``0``.
        """
        cache = self._storage.get("cache")

        # Previous day's aggregated sentiment from cache/BigQuery
        previous_sentiment = self._query_previous_sentiment(symbol, market)

        # Overnight news from MongoDB / cache
        overnight_news = self._query_overnight_news(symbol, market)

        if not overnight_news:
            return {
                "previous": previous_sentiment,
                "current": 0.0,
                "change": 0.0,
                "article_count": 0,
                "signal": "NO_NEWS",
            }

        scores = [
            n.get("sentiment_score", 0.0)
            for n in overnight_news
            if isinstance(n.get("sentiment_score"), (int, float))
        ]
        current = mean(scores) if scores else 0.0
        change = current - previous_sentiment

        return {
            "previous": previous_sentiment,
            "current": round(current, 4),
            "change": round(change, 4),
            "article_count": len(overnight_news),
            "signal": self._classify_change(change),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_tier1_symbols(self, market: str) -> list[str]:
        """Return the Tier 1 symbol list for *market* from config."""
        key = f"universe.tier1.{market.lower()}.symbols"
        symbols = _nested_get(self._config, key, [])
        return symbols if isinstance(symbols, list) else []

    def _query_previous_sentiment(self, symbol: str, market: str) -> float:
        """Fetch the previous trading day's aggregated sentiment score.

        Tries the cache first, falls back to BigQuery.
        """
        cache = self._storage.get("cache")
        if cache is not None:
            cached = cache.get(f"sentiment:{market}:{symbol}:prev_day")
            if cached is not None:
                try:
                    return float(cached)
                except (TypeError, ValueError):
                    pass

        # Fall back to BigQuery via the sentiment analyzer
        sentiment_analyzer = self._analyzers.get("sentiment")
        if sentiment_analyzer is not None and hasattr(sentiment_analyzer, "query_daily_sentiment"):
            try:
                return sentiment_analyzer.query_daily_sentiment(symbol, market, days_ago=1)
            except Exception:
                logger.warning(
                    "Failed to query previous sentiment for %s/%s; defaulting to 0.0",
                    symbol, market,
                )
        return 0.0

    def _query_overnight_news(self, symbol: str, market: str) -> list[dict]:
        """Fetch news articles for *symbol* from the past ``_lookback_hours``."""
        cache = self._storage.get("cache")
        if cache is not None and hasattr(cache, "get_recent_news"):
            try:
                articles = cache.get_recent_news(symbol, market, hours=self._lookback_hours)
                if articles:
                    return articles
            except Exception:
                logger.debug("Cache miss for overnight news %s/%s.", symbol, market)

        # Fall back to the sentiment analyzer's news store
        sentiment_analyzer = self._analyzers.get("sentiment")
        if sentiment_analyzer is not None and hasattr(sentiment_analyzer, "query_recent_news"):
            try:
                return sentiment_analyzer.query_recent_news(
                    symbol, market, hours=self._lookback_hours,
                )
            except Exception:
                logger.warning(
                    "Failed to query overnight news for %s/%s.",
                    symbol, market,
                    exc_info=True,
                )
        return []

    def _collect_events(self, market: str, errors: list[str]) -> list[dict]:
        """Collect today's event calendar entries."""
        events: list[dict] = []
        try:
            event_collector = self._collectors.get("event_calendar")
            if event_collector is not None:
                events = event_collector.fetch_today(market)
                logger.info("Collected %d events for %s.", len(events), market)
            else:
                logger.warning("event_calendar collector not configured; skipping.")
        except Exception as exc:
            msg = f"EVENTS_FAIL: {exc}"
            logger.error(msg, exc_info=True)
            errors.append(msg)
        return events

    def _fetch_positions(self, market: str) -> dict:
        """Fetch current positions summary from cache or storage."""
        cache = self._storage.get("cache")
        if cache is not None:
            try:
                positions = cache.get(f"positions:{market}")
                if positions is not None:
                    return positions if isinstance(positions, dict) else {}
            except Exception:
                logger.debug("Cache miss for positions %s.", market)
        return {}

    def _fetch_risk_status(self, market: str) -> dict:
        """Fetch current risk status from cache or storage."""
        cache = self._storage.get("cache")
        if cache is not None:
            try:
                risk = cache.get(f"risk_status:{market}")
                if risk is not None:
                    return risk if isinstance(risk, dict) else {}
            except Exception:
                logger.debug("Cache miss for risk_status %s.", market)
        return {}

    @staticmethod
    def _classify_change(change: float) -> str:
        """Classify a sentiment change value into a signal label.

        Thresholds:
            * ``|change| < 0.1``  -> ``NEUTRAL``
            * ``change >= 0.1``   -> ``POSITIVE``
            * ``change <= -0.1``  -> ``NEGATIVE``
        """
        if abs(change) < 0.1:
            return "NEUTRAL"
        return "POSITIVE" if change > 0 else "NEGATIVE"
