"""Korean market price collector using the KIS (Korea Investment Securities) API.

Fetches 1-minute bars, aggregates them to 5-minute bars, and computes
the derived fields required by the ``market_5m_bars`` BigQuery schema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from .base_collector import BaseCollector
from .normalizer import PriceNormalizer

logger = logging.getLogger(__name__)


class KRPriceCollector(BaseCollector):
    """Collect 5-minute price bars for Korean stocks via KIS REST API.

    Config keys (nested under ``broker.kr``)::

        broker:
          kr:
            app_key: "..."
            app_secret: "..."
            access_token: "..."      # obtained via token issuance API
            account_no: "..."
            base_url: "https://openapi.koreainvestment.com:9443"
            symbols:
              - "005930"
              - "000660"

    The collector:
    1. Fetches the last 5 one-minute bars for each symbol.
    2. Aggregates them into a single 5-minute bar.
    3. Computes derived fields: vwap, high_minute, low_minute,
       intra_stddev, volume_skew, bar_trend.
    """

    SOURCE_NAME = "kis"
    # KIS API path for minute-level price inquiry
    MINUTE_PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        broker_cfg: dict[str, Any] = config.get("broker", {}).get("kr", {})

        self.app_key: str = broker_cfg.get("app_key", "")
        self.app_secret: str = broker_cfg.get("app_secret", "")
        self.access_token: str = broker_cfg.get("access_token", "")
        self.account_no: str = broker_cfg.get("account_no", "")
        self.base_url: str = broker_cfg.get(
            "base_url", "https://openapi.koreainvestment.com:9443"
        )
        self.symbols: list[str] = broker_cfg.get("symbols", [])

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Content-Type": "application/json; charset=utf-8",
                "authorization": f"Bearer {self.access_token}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            }
        )
        self._normalizer = PriceNormalizer()

    # ------------------------------------------------------------------
    # BaseCollector hooks
    # ------------------------------------------------------------------

    def fetch(self) -> list[dict[str, Any]]:
        """Fetch 1-minute bars and aggregate to 5-minute bars."""
        results: list[dict[str, Any]] = []

        for symbol in self.symbols:
            bars_1m = self._fetch_1m_bars(symbol, count=5)
            if len(bars_1m) < 1:
                logger.warning(
                    "KRPriceCollector: no 1-min bars for %s, skipping.", symbol
                )
                continue

            bar_5m = self._normalizer.aggregate_1m_to_5m(
                bars_1m, symbol=symbol, market="KR"
            )
            results.append(bar_5m)

        logger.info(
            "KRPriceCollector.fetch: aggregated %d 5-min bars.", len(results)
        )
        return results

    def normalize(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The aggregation step already produces normalised data.

        This method applies final type coercion / validation only.
        """
        normalised: list[dict[str, Any]] = []
        for bar in raw:
            # Ensure all numeric fields are present
            bar.setdefault("spread_pct", None)
            normalised.append(bar)
        return normalised

    def store(self, normalised: list[dict[str, Any]]) -> None:
        """Persist 5-minute bars."""
        logger.info(
            "KRPriceCollector.store: %d bars ready for persistence.", len(normalised)
        )
        # TODO: write JSONL to GCS -> BigQuery batch load
        # TODO: cache latest bars in Redis

    # ------------------------------------------------------------------
    # KIS API helpers
    # ------------------------------------------------------------------

    def _fetch_1m_bars(
        self,
        symbol: str,
        count: int = 5,
    ) -> list[dict[str, Any]]:
        """Fetch recent 1-minute bars from KIS for a single symbol.

        Parameters
        ----------
        symbol:
            KRX stock code (e.g. ``"005930"``).
        count:
            Number of 1-minute bars to retrieve.

        Returns
        -------
        A list of dicts with keys: ``timestamp``, ``open``, ``high``,
        ``low``, ``close``, ``volume``.
        """
        now_hhmm = datetime.now(timezone.utc).strftime("%H%M%S")

        url = f"{self.base_url}{self.MINUTE_PRICE_PATH}"
        headers = {
            "tr_id": "FHKST03010200",  # 국내주식 분봉 조회
        }

        params: dict[str, str] = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",  # J = 주식
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_HOUR_1": now_hhmm,
            "FID_PW_DATA_INCU_YN": "N",
        }

        try:
            resp = self._session.get(
                url, headers=headers, params=params, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.error(
                "KRPriceCollector._fetch_1m_bars(%s) failed: %s", symbol, exc
            )
            return []

        output2 = data.get("output2", [])
        bars: list[dict[str, Any]] = []

        for entry in output2[:count]:
            try:
                bar: dict[str, Any] = {
                    "timestamp": self._parse_kis_datetime(
                        entry.get("stck_bsop_date", ""),
                        entry.get("stck_cntg_hour", ""),
                    ),
                    "open": float(entry.get("stck_oprc", 0)),
                    "high": float(entry.get("stck_hgpr", 0)),
                    "low": float(entry.get("stck_lwpr", 0)),
                    "close": float(entry.get("stck_prpr", 0)),
                    "volume": int(entry.get("cntg_vol", 0)),
                }
                bars.append(bar)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Skipping malformed 1-min bar for %s: %s", symbol, exc
                )

        # KIS returns most recent first – reverse for chronological order
        bars.reverse()
        return bars

    @staticmethod
    def _parse_kis_datetime(date_str: str, time_str: str) -> str:
        """Convert KIS date/time strings to ISO-8601.

        KIS uses ``YYYYMMDD`` for dates and ``HHMMSS`` for times.
        """
        if len(date_str) == 8 and len(time_str) >= 6:
            iso = (
                f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                f"T{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}+09:00"
            )
            return iso
        return datetime.now(timezone.utc).isoformat()
