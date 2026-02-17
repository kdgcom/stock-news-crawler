"""US market news collectors.

* ``AlpacaNewsCollector`` – fetches news from the Alpaca News API.
* ``SECEdgarCollector``   – fetches SEC EDGAR filings / full-text search.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from .base_collector import BaseCollector
from .normalizer import NewsNormalizer

logger = logging.getLogger(__name__)


# ======================================================================
# Alpaca News API collector
# ======================================================================

class AlpacaNewsCollector(BaseCollector):
    """Collect news from the Alpaca News API (free tier).

    Endpoint::

        GET https://data.alpaca.markets/v1beta1/news

    Authentication is via ``APCA-API-KEY-ID`` and ``APCA-API-SECRET-KEY``
    headers.
    """

    SOURCE_NAME = "alpaca_news"
    BASE_URL = "https://data.alpaca.markets/v1beta1/news"

    def __init__(
        self,
        config: dict[str, Any],
        api_key: str,
        api_secret: str,
    ) -> None:
        self.config = config
        self.api_key = api_key
        self.api_secret = api_secret

        self._session = requests.Session()
        self._session.headers.update(
            {
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
            }
        )
        self._normalizer = NewsNormalizer()

    # ------------------------------------------------------------------
    # BaseCollector hooks
    # ------------------------------------------------------------------

    def fetch(self) -> list[dict[str, Any]]:
        """Fetch recent news articles from Alpaca."""
        symbols: list[str] = self.config.get("symbols", [])
        limit: int = self.config.get("limit", 50)

        params: dict[str, Any] = {
            "limit": limit,
            "sort": "desc",
        }
        if symbols:
            params["symbols"] = ",".join(symbols)

        # Optional: filter by start time
        start_time = self.config.get("start_time")
        if start_time:
            params["start"] = start_time

        try:
            resp = self._session.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error("AlpacaNewsCollector.fetch failed: %s", exc)
            raise

        news_list: list[dict[str, Any]] = data.get("news", [])
        logger.info(
            "AlpacaNewsCollector.fetch: %d articles retrieved.", len(news_list)
        )
        return news_list

    def normalize(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalise Alpaca news articles to the standard schema."""
        normalised: list[dict[str, Any]] = []

        for item in raw:
            # Alpaca returns symbols as a list; take first or join
            symbols = item.get("symbols", [])
            symbol = symbols[0] if symbols else ""

            mapped: dict[str, Any] = {
                "title": item.get("headline", ""),
                "url": item.get("url", ""),
                "published_at": item.get("created_at", ""),
                "symbol": symbol,
                "market": "US",
                "language": "en",
                "source_name": item.get("source", "Alpaca"),
                "source_type": "news",
                "body": item.get("summary", ""),
            }

            record = self._normalizer.normalize(mapped, source=self.SOURCE_NAME)
            normalised.append(record)

        return normalised

    def store(self, normalised: list[dict[str, Any]]) -> None:
        """Persist normalised Alpaca news articles."""
        logger.info(
            "AlpacaNewsCollector.store: %d records ready for persistence.",
            len(normalised),
        )
        # TODO: upsert into MongoDB raw_news_events by event_id


# ======================================================================
# SEC EDGAR collector
# ======================================================================

class SECEdgarCollector(BaseCollector):
    """Collect SEC filings from the EDGAR full-text search API.

    Endpoint::

        GET https://efts.sec.gov/LATEST/search-index
            ?q=<query>&forms=8-K&dateRange=custom&...

    The SEC asks that automated requests include a descriptive
    ``User-Agent`` header with a contact email.
    """

    SOURCE_NAME = "sec_edgar"
    SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
    RSS_URL = "https://www.sec.gov/cgi-bin/browse-edgar"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._session = requests.Session()

        # SEC requires a descriptive User-Agent
        user_agent = config.get(
            "user_agent",
            "StockNewsBot/1.0 (contact@example.com)",
        )
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )
        self._normalizer = NewsNormalizer()

    # ------------------------------------------------------------------
    # BaseCollector hooks
    # ------------------------------------------------------------------

    def fetch(self) -> list[dict[str, Any]]:
        """Query EDGAR full-text search or latest filings RSS.

        The query, form types and date range are read from *config*.
        """
        query: str = self.config.get("query", "")
        forms: str = self.config.get("forms", "8-K")
        start_date: str = self.config.get(
            "start_date",
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )
        end_date: str = self.config.get(
            "end_date",
            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )

        params: dict[str, Any] = {
            "q": query,
            "forms": forms,
            "dateRange": "custom",
            "startdt": start_date,
            "enddt": end_date,
        }

        try:
            resp = self._session.get(self.SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error("SECEdgarCollector.fetch failed: %s", exc)
            raise

        hits: list[dict[str, Any]] = data.get("hits", {}).get("hits", [])
        filings = [h.get("_source", {}) for h in hits]
        logger.info("SECEdgarCollector.fetch: %d filings retrieved.", len(filings))
        return filings

    def normalize(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalise EDGAR filings to the standard news event schema."""
        normalised: list[dict[str, Any]] = []

        for item in raw:
            file_num = item.get("file_num", "")
            accession_no = item.get("accession_no", "")
            url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&filenum={file_num}&type=&dateb=&owner=include&count=10"
            )
            if accession_no:
                clean_accession = accession_no.replace("-", "")
                url = (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{clean_accession}/{accession_no}-index.htm"
                )

            # Map to the standard schema input
            mapped: dict[str, Any] = {
                "title": item.get("form_type", "") + " – " + item.get("display_names", [""])[0]
                if item.get("display_names")
                else item.get("form_type", ""),
                "url": url,
                "published_at": item.get("file_date", ""),
                "symbol": item.get("ticker", ""),
                "market": "US",
                "language": "en",
                "source_name": "SEC EDGAR",
                "source_type": "disclosure",
                "body": item.get("form_type", ""),
            }

            record = self._normalizer.normalize(mapped, source=self.SOURCE_NAME)
            normalised.append(record)

        return normalised

    def store(self, normalised: list[dict[str, Any]]) -> None:
        """Persist normalised EDGAR filings."""
        logger.info(
            "SECEdgarCollector.store: %d records ready for persistence.",
            len(normalised),
        )
        # TODO: upsert into MongoDB raw_news_events by event_id
