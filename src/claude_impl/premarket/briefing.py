"""Briefing text generation for KR morning and US evening routines.

Produces human-readable briefings in the format specified by the
05-pre-market design document and delivers them as plain-text (suitable
for Telegram or other messaging channels).

Briefing template sections:
    1. Market close summary (US for KR morning, KR for US evening)
    2. Overnight / pre-market key news
    3. Daily watchlist (sentiment-change leaders)
    4. Current positions overview
    5. Risk status
    6. Event calendar
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Day-of-week labels in Korean
_KR_WEEKDAYS: list[str] = ["월", "화", "수", "목", "금", "토", "일"]

_SECTION_SEPARATOR = "━" * 36


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


def _sign(value: float) -> str:
    """Return a signed string representation (``+0.8%``, ``-1.2%``)."""
    return f"+{value}" if value >= 0 else f"{value}"


def _sentiment_label(score: float) -> str:
    """Map a sentiment score to a Korean label."""
    if score >= 0.3:
        return "긍정"
    if score <= -0.3:
        return "부정"
    return "중립"


def _change_arrow(change: float) -> str:
    """Return an arrow character indicating direction."""
    if change > 0.05:
        return "↑"
    if change < -0.05:
        return "↓"
    return "→"


class BriefingGenerator:
    """Generates formatted briefing text for pre-market routines.

    Parameters
    ----------
    config:
        Application configuration dict.
    """

    def __init__(self, config: dict) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_kr_morning(self, data: dict) -> str:
        """Generate the KR Morning Briefing text.

        Parameters
        ----------
        data:
            Dict with keys:
            ``run_date`` (str), ``us_close`` (dict), ``news_items`` (list),
            ``watchlist`` (list), ``positions`` (dict), ``risk_status`` (dict),
            ``events`` (list).

        Returns
        -------
        str
            The formatted briefing text ready for sending.
        """
        run_date = data.get("run_date", datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"))
        sections: dict[str, str] = {
            "market_close": self._format_us_close(data.get("us_close", {})),
            "news": self._format_news(data.get("news_items", []), market="KR"),
            "watchlist": self._format_watchlist(data.get("watchlist", [])),
            "positions": self._format_positions(data.get("positions", {})),
            "risk": self._format_risk(data.get("risk_status", {})),
            "events": self._format_events(data.get("events", [])),
        }
        return self._format_briefing(market="KR", date=run_date, sections=sections)

    def generate_us_evening(self, data: dict) -> str:
        """Generate the US Evening Briefing text.

        Parameters
        ----------
        data:
            Dict with keys:
            ``run_date`` (str), ``kr_close`` (dict), ``news_items`` (list),
            ``watchlist`` (list), ``positions`` (dict), ``risk_status`` (dict),
            ``events`` (list).

        Returns
        -------
        str
            The formatted briefing text ready for sending.
        """
        run_date = data.get("run_date", datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"))
        sections: dict[str, str] = {
            "market_close": self._format_kr_close(data.get("kr_close", {})),
            "news": self._format_news(data.get("news_items", []), market="US"),
            "watchlist": self._format_watchlist(data.get("watchlist", [])),
            "positions": self._format_positions(data.get("positions", {})),
            "risk": self._format_risk(data.get("risk_status", {})),
            "events": self._format_events(data.get("events", [])),
        }
        return self._format_briefing(market="US", date=run_date, sections=sections)

    # ------------------------------------------------------------------
    # Master formatter
    # ------------------------------------------------------------------

    def _format_briefing(self, market: str, date: str, sections: dict) -> str:
        """Assemble all sections into the final briefing text.

        Parameters
        ----------
        market:
            ``"KR"`` or ``"US"``.
        date:
            Run date string ``YYYY-MM-DD``.
        sections:
            Dict mapping section keys (``market_close``, ``news``,
            ``watchlist``, ``positions``, ``risk``, ``events``) to
            their pre-formatted text bodies.

        Returns
        -------
        str
            Complete briefing text.
        """
        # Derive weekday label
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            weekday = _KR_WEEKDAYS[dt.weekday()]
        except (ValueError, IndexError):
            weekday = ""

        if market == "KR":
            title = f"KR Morning Briefing ({date} {weekday})"
            close_header = "US 시장 마감"
            news_header = "야간 주요 뉴스 (KR Tier 1)"
        else:
            title = f"US Evening Briefing ({date} {weekday})"
            close_header = "KR 시장 마감"
            news_header = "프리마켓 주요 뉴스 (US Tier 1)"

        lines: list[str] = [
            f"  {title}",
            _SECTION_SEPARATOR,
            "",
            f"  {close_header}",
            sections.get("market_close", "  데이터 없음"),
            "",
            f"  {news_header}",
            sections.get("news", "  뉴스 없음"),
            "",
            "  오늘의 Watchlist (감성 변화 상위)",
            sections.get("watchlist", "  해당 종목 없음"),
            "",
            "  기존 포지션 현황",
            sections.get("positions", "  포지션 없음"),
            "",
            "  리스크 상태",
            sections.get("risk", "  데이터 없음"),
            "",
            "  이벤트 캘린더",
            sections.get("events", "  예정 이벤트 없음"),
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section formatters
    # ------------------------------------------------------------------

    @staticmethod
    def _format_us_close(us_close: dict) -> str:
        """Format the US market close section."""
        if not us_close:
            return "  데이터 수집 실패 (수동 확인 필요)"

        sp500 = us_close.get("sp500", {})
        nasdaq = us_close.get("nasdaq", {})
        vix = us_close.get("vix", {})

        lines: list[str] = []

        if sp500:
            price = sp500.get("close", "N/A")
            change_pct = sp500.get("change_pct", 0.0)
            lines.append(f"  S&P 500: {price:>10} ({_sign(change_pct)}%)")

        if nasdaq:
            price = nasdaq.get("close", "N/A")
            change_pct = nasdaq.get("change_pct", 0.0)
            lines.append(f"  NASDAQ:  {price:>10} ({_sign(change_pct)}%)")

        if vix:
            close_val = vix.get("close", "N/A")
            change_val = vix.get("change", 0.0)
            lines.append(f"  VIX:     {close_val:>10} ({_sign(change_val)})")

        # Additional US Tier 1 symbols, if present
        tier1 = us_close.get("tier1_symbols", [])
        for sym_data in tier1:
            symbol = sym_data.get("symbol", "")
            price = sym_data.get("close", "N/A")
            change_pct = sym_data.get("change_pct", 0.0)
            lines.append(f"  {symbol:<8} {price:>10} ({_sign(change_pct)}%)")

        return "\n".join(lines) if lines else "  데이터 없음"

    @staticmethod
    def _format_kr_close(kr_close: dict) -> str:
        """Format the KR market close section."""
        if not kr_close:
            return "  데이터 수집 실패 (수동 확인 필요)"

        kospi = kr_close.get("kospi", {})
        kosdaq = kr_close.get("kosdaq", {})

        lines: list[str] = []

        if kospi:
            price = kospi.get("close", "N/A")
            change_pct = kospi.get("change_pct", 0.0)
            lines.append(f"  KOSPI:   {price:>10} ({_sign(change_pct)}%)")

        if kosdaq:
            price = kosdaq.get("close", "N/A")
            change_pct = kosdaq.get("change_pct", 0.0)
            lines.append(f"  KOSDAQ:  {price:>10} ({_sign(change_pct)}%)")

        tier1 = kr_close.get("tier1_symbols", [])
        for sym_data in tier1:
            symbol = sym_data.get("symbol", "")
            price = sym_data.get("close", "N/A")
            change_pct = sym_data.get("change_pct", 0.0)
            lines.append(f"  {symbol:<8} {price:>10} ({_sign(change_pct)}%)")

        return "\n".join(lines) if lines else "  데이터 없음"

    @staticmethod
    def _format_news(news_items: list[dict], market: str) -> str:
        """Format the overnight / pre-market news section.

        Selects the top news items (by absolute sentiment score) and
        displays each with a sentiment label, symbol, headline, and
        score.
        """
        if not news_items:
            return "  뉴스 없음"

        # Sort by absolute sentiment score descending, take top 10
        scored = [
            n for n in news_items
            if isinstance(n.get("sentiment_score"), (int, float))
        ]
        scored.sort(key=lambda n: abs(n.get("sentiment_score", 0.0)), reverse=True)
        top_news = scored[:10]

        lines: list[str] = []
        for item in top_news:
            label = _sentiment_label(item.get("sentiment_score", 0.0))
            symbols = item.get("symbols", [])
            symbol_str = symbols[0] if symbols else "N/A"
            headline = item.get("title", item.get("headline", ""))
            score = item.get("sentiment_score", 0.0)
            lines.append(f"  [{label}] {symbol_str} - {headline} (감성 {_sign(score)})")

        # Include unsorted items without sentiment as neutral
        unsorted = [n for n in news_items if n not in scored]
        for item in unsorted[:5]:
            symbols = item.get("symbols", [])
            symbol_str = symbols[0] if symbols else "N/A"
            headline = item.get("title", item.get("headline", ""))
            lines.append(f"  [중립] {symbol_str} - {headline}")

        return "\n".join(lines) if lines else "  뉴스 없음"

    @staticmethod
    def _format_watchlist(watchlist: list[dict]) -> str:
        """Format the watchlist section."""
        if not watchlist:
            return "  해당 종목 없음"

        lines: list[str] = []
        for idx, entry in enumerate(watchlist, 1):
            symbol = entry.get("symbol", "N/A")
            score = entry.get("score", 0.0)
            sentiment = entry.get("sentiment", {})
            change = sentiment.get("change", 0.0)
            arrow = _change_arrow(change)
            event = entry.get("event")

            reason_parts: list[str] = []
            if abs(change) > 0.01:
                reason_parts.append(f"감성 {_sign(round(change, 2))}")
            if event:
                desc = event.get("description", "이벤트")
                reason_parts.append(desc)
            if not reason_parts:
                reason_parts.append("변동 없음")

            reason = ", ".join(reason_parts)
            lines.append(f"  {idx:>2}. {symbol:<10} {arrow} {reason}")

        return "\n".join(lines)

    @staticmethod
    def _format_positions(positions: dict) -> str:
        """Format the positions overview section."""
        if not positions:
            return "  포지션 없음"

        lines: list[str] = []

        total_assets = positions.get("total_assets")
        holdings_count = positions.get("holdings_count", 0)
        cash_pct = positions.get("cash_pct")

        if total_assets is not None:
            currency = positions.get("currency", "")
            lines.append(
                f"  총 자산: {currency}{total_assets:,.0f}"
                f" | 보유 {holdings_count}종목"
                + (f" | 현금 {cash_pct:.0%}" if cash_pct is not None else "")
            )

        holdings = positions.get("holdings", [])
        for h in holdings:
            symbol = h.get("symbol", "N/A")
            name = h.get("name", "")
            pnl_pct = h.get("pnl_pct", 0.0)
            price = h.get("current_price")
            display_name = f"{symbol} {name}" if name else symbol
            price_str = f" ({currency}{price:,.0f})" if price is not None else ""
            lines.append(f"  {display_name}: {_sign(round(pnl_pct, 1))}%{price_str}")

        return "\n".join(lines) if lines else "  포지션 없음"

    @staticmethod
    def _format_risk(risk_status: dict) -> str:
        """Format the risk status section."""
        if not risk_status:
            return "  데이터 없음"

        lines: list[str] = []

        daily_limit = risk_status.get("daily_loss_limit_pct")
        daily_used = risk_status.get("daily_loss_used_pct", 0.0)
        if daily_limit is not None:
            lines.append(
                f"  일일 손실 여력: {daily_limit:+.1%} (사용 {daily_used:+.1%})"
            )

        weekly_limit = risk_status.get("weekly_loss_limit_pct")
        weekly_used = risk_status.get("weekly_loss_used_pct", 0.0)
        if weekly_limit is not None:
            lines.append(
                f"  주간 손실 여력: {weekly_limit:+.1%} (사용 {weekly_used:+.1%})"
            )

        can_trade = risk_status.get("can_open_new_position")
        if can_trade is not None:
            lines.append(f"  신규 매매 가능: {'YES' if can_trade else 'NO'}")

        return "\n".join(lines) if lines else "  데이터 없음"

    @staticmethod
    def _format_events(events: list[dict]) -> str:
        """Format the event calendar section."""
        if not events:
            return "  예정 이벤트 없음"

        lines: list[str] = []
        for event in events:
            description = event.get("description", "이벤트")
            date_info = event.get("date_info", "")
            symbols = event.get("symbols", [])
            symbol_str = ", ".join(symbols) if symbols else ""

            parts: list[str] = []
            if symbol_str:
                parts.append(symbol_str)
            parts.append(description)
            if date_info:
                parts.append(f"({date_info})")

            lines.append(f"  - {' '.join(parts)}")

        return "\n".join(lines)
