"""Korean market news collectors.

* ``NaverFinanceCollector`` – scrapes Naver Finance article lists.
* ``DartCollector``         – fetches disclosures from the DART OpenAPI.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .base_collector import BaseCollector
from .normalizer import NewsNormalizer

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; StockNewsBot/1.0; "
    "+https://github.com/kdgcom/stock-news-crawler)"
)

_NAVER_FINANCE_ROBOTS_URL = "https://finance.naver.com/robots.txt"


# ======================================================================
# Naver Finance news collector
# ======================================================================

class NaverFinanceCollector(BaseCollector):
    """Collect per-symbol news from Naver Finance.

    URL pattern::

        https://finance.naver.com/item/news.naver?code={symbol}

    The collector parses the article list table to extract titles, dates
    and detail links.  It respects ``robots.txt`` by default.
    """

    SOURCE_NAME = "naver_finance"
    BASE_URL = "https://finance.naver.com/item/news.naver"
    REQUEST_DELAY: float = 1.5  # seconds between requests

    def __init__(self, config: dict[str, Any], symbols: list[str]) -> None:
        self.config = config
        self.symbols = symbols
        self.user_agent: str = config.get("user_agent", _DEFAULT_USER_AGENT)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent})
        self._normalizer = NewsNormalizer()

        # Robots.txt parser (best-effort)
        self._robots: RobotFileParser | None = self._load_robots()

    # ------------------------------------------------------------------
    # robots.txt
    # ------------------------------------------------------------------

    def _load_robots(self) -> RobotFileParser | None:
        """Parse Naver Finance robots.txt.  Returns *None* on failure."""
        try:
            rp = RobotFileParser()
            rp.set_url(_NAVER_FINANCE_ROBOTS_URL)
            rp.read()
            return rp
        except Exception:
            logger.warning("Could not load robots.txt from Naver Finance.")
            return None

    def _is_allowed(self, url: str) -> bool:
        if self._robots is None:
            return True
        return self._robots.can_fetch(self.user_agent, url)

    # ------------------------------------------------------------------
    # BaseCollector hooks
    # ------------------------------------------------------------------

    def fetch(self) -> list[dict[str, Any]]:
        """Fetch article metadata for every symbol."""
        all_articles: list[dict[str, Any]] = []

        for symbol in self.symbols:
            url = f"{self.BASE_URL}?code={symbol}"
            if not self._is_allowed(url):
                logger.info("Skipping %s – disallowed by robots.txt.", url)
                continue

            try:
                resp = self._session.get(url, timeout=15)
                resp.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("Failed to fetch %s: %s", url, exc)
                continue

            articles = self._parse_news_list(resp.text, symbol)
            all_articles.extend(articles)

            # Polite crawl delay
            time.sleep(self.REQUEST_DELAY)

        logger.info(
            "NaverFinanceCollector.fetch: %d articles for %d symbols.",
            len(all_articles),
            len(self.symbols),
        )
        return all_articles

    def normalize(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalise raw Naver articles to the standard news schema."""
        normalised: list[dict[str, Any]] = []
        seen_event_ids: set[str] = set()

        for article in raw:
            record = self._normalizer.normalize(article, source=self.SOURCE_NAME)
            eid = record["event_id"]
            if eid in seen_event_ids:
                continue
            seen_event_ids.add(eid)
            normalised.append(record)

        return normalised

    def store(self, normalised: list[dict[str, Any]]) -> None:
        """Persist normalised articles.

        The concrete storage back-end (MongoDB, etc.) should be injected
        via *config* or overridden in a subclass.  The default
        implementation logs the count as a placeholder.
        """
        logger.info(
            "NaverFinanceCollector.store: %d records ready for persistence.",
            len(normalised),
        )
        # TODO: upsert into MongoDB raw_news_events by event_id

    # ------------------------------------------------------------------
    # HTML parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_news_list(html: str, symbol: str) -> list[dict[str, Any]]:
        """Extract article metadata from a Naver Finance news list page.

        Expected table structure inside ``<table class="type5">``::

            <tr>
                <td class="title">
                    <a href="/item/news_read.naver?...">제목</a>
                </td>
                <td class="info">매일경제</td>
                <td class="date"> 2026.02.17 09:30</td>
            </tr>
        """
        soup = BeautifulSoup(html, "html.parser")
        articles: list[dict[str, Any]] = []

        rows = soup.select("table.type5 tr")
        for row in rows:
            title_cell = row.select_one("td.title a")
            info_cell = row.select_one("td.info")
            date_cell = row.select_one("td.date")

            if not title_cell:
                continue

            title = title_cell.get_text(strip=True)
            href = title_cell.get("href", "")
            article_url = urljoin("https://finance.naver.com", href)
            publisher = info_cell.get_text(strip=True) if info_cell else ""
            date_str = date_cell.get_text(strip=True) if date_cell else ""

            # Parse Korean date format "2026.02.17 09:30"
            published_at: datetime | None = None
            for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d"):
                try:
                    published_at = datetime.strptime(date_str, fmt).replace(
                        tzinfo=timezone.utc,
                    )
                    break
                except ValueError:
                    continue

            articles.append(
                {
                    "title": title,
                    "url": article_url,
                    "published_at": published_at.isoformat() if published_at else "",
                    "symbol": symbol,
                    "market": "KR",
                    "language": "ko",
                    "source_name": publisher or "네이버금융",
                    "source_type": "news",
                    "body": "",  # body is fetched separately if needed
                }
            )

        return articles


# ======================================================================
# DART disclosure collector
# ======================================================================

class DartCollector(BaseCollector):
    """Collect corporate disclosures from the DART OpenAPI.

    Endpoint::

        https://opendart.fss.or.kr/api/list.json

    Requires a DART API key (free tier, 10 000 requests / day).
    """

    SOURCE_NAME = "dart"
    API_URL = "https://opendart.fss.or.kr/api/list.json"

    def __init__(self, config: dict[str, Any], api_key: str) -> None:
        self.config = config
        self.api_key = api_key
        self._session = requests.Session()
        self._normalizer = NewsNormalizer()

    # ------------------------------------------------------------------
    # BaseCollector hooks
    # ------------------------------------------------------------------

    def fetch(self) -> list[dict[str, Any]]:
        """Fetch recent disclosures from DART."""
        today = datetime.now(timezone.utc).strftime("%Y%m%d")

        params: dict[str, Any] = {
            "crtfc_key": self.api_key,
            "bgn_de": today,
            "end_de": today,
            "page_count": 100,
            "page_no": 1,
        }

        # Add optional corp_code filter from config
        corp_code = self.config.get("corp_code")
        if corp_code:
            params["corp_code"] = corp_code

        try:
            resp = self._session.get(self.API_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error("DartCollector.fetch failed: %s", exc)
            raise

        status = data.get("status", "")
        if status == "013":
            # "013" means no data found – not an error
            logger.info("DartCollector.fetch: no disclosures for %s.", today)
            return []

        if status != "000":
            msg = data.get("message", "Unknown DART error")
            raise RuntimeError(f"DART API error (status={status}): {msg}")

        raw_list = data.get("list", [])
        logger.info("DartCollector.fetch: %d disclosures retrieved.", len(raw_list))
        return raw_list

    def normalize(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert DART disclosures to the standard news event schema."""
        normalised: list[dict[str, Any]] = []

        for item in raw:
            # Build a pseudo-URL for deduplication
            rcept_no = item.get("rcept_no", "")
            url = f"https://dart.fss.or.kr/dsaf001/main.do?rcept_no={rcept_no}"

            # Parse receipt date "20260217"
            rcept_dt = item.get("rcept_dt", "")
            published_at = ""
            if rcept_dt and len(rcept_dt) == 8:
                try:
                    dt = datetime.strptime(rcept_dt, "%Y%m%d").replace(
                        tzinfo=timezone.utc,
                    )
                    published_at = dt.isoformat()
                except ValueError:
                    pass

            mapped: dict[str, Any] = {
                "title": item.get("report_nm", ""),
                "url": url,
                "published_at": published_at,
                "symbol": item.get("stock_code", ""),
                "market": "KR",
                "language": "ko",
                "source_name": "DART",
                "source_type": "disclosure",
                "body": item.get("report_nm", ""),
            }

            record = self._normalizer.normalize(mapped, source=self.SOURCE_NAME)
            normalised.append(record)

        return normalised

    def store(self, normalised: list[dict[str, Any]]) -> None:
        """Persist normalised DART disclosures."""
        logger.info(
            "DartCollector.store: %d records ready for persistence.",
            len(normalised),
        )
        # TODO: upsert into MongoDB raw_news_events by event_id
