"""Sector Correlation (SC) algorithm.

Detects leader-lagger patterns within the same sector.  When a sector
leader moves significantly and the target symbol lags, it signals a
catch-up opportunity.

Best suited for:
    * Sector-wide news (semiconductor super-cycle, auto tariffs, etc.)
    * Sector rotation phases

Config keys (``algorithms.sector_correlation``)::

    sector_momentum_window     -- bar count for measuring peer momentum
    leader_lag_bars            -- bar count to measure the lagger response
    min_correlation            -- minimum historical correlation threshold
    min_lag_gap_pct            -- minimum leader - lagger return gap
    sector_map                 -- dict mapping sector name -> list of symbols
"""

from __future__ import annotations

import logging
from statistics import mean as _mean

from ..base_algorithm import BaseAlgorithm
from ...models.signal import AlgorithmContext, Signal

logger = logging.getLogger(__name__)


def _compute_correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient between two equal-length series.

    Returns 0.0 when inputs are too short or when standard deviation
    is zero (constant series).
    """
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    xs, ys = xs[:n], ys[:n]
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    std_x = (sum((x - mean_x) ** 2 for x in xs)) ** 0.5
    std_y = (sum((y - mean_y) ** 2 for y in ys)) ** 0.5
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)


class SectorCorrelation(BaseAlgorithm):
    """Leader-lagger pattern detection within sectors."""

    @property
    def name(self) -> str:
        return "sector_correlation"

    def required_data(self) -> list[str]:
        return ["price_bars", "daily_bars"]

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, ctx: AlgorithmContext) -> Signal:
        cfg = self.config
        symbol = ctx.symbol

        sector_map: dict[str, list[str]] = cfg.get("sector_map", {})
        sector_momentum_window: int = cfg.get("sector_momentum_window", 10)
        leader_lag_bars: int = cfg.get("leader_lag_bars", 5)
        min_correlation: float = cfg.get("min_correlation", 0.6)
        min_lag_gap: float = cfg.get("min_lag_gap_pct", 0.01)

        # Identify the sector this symbol belongs to
        sector: str | None = None
        sector_peers: list[str] = []
        for sec_name, members in sector_map.items():
            if symbol in members:
                sector = sec_name
                sector_peers = [m for m in members if m != symbol]
                break

        if not sector or not sector_peers:
            return self._hold(ctx, ["NO_SECTOR_DATA"])

        # Use daily bars to compute peer momentum and correlation
        # The context carries the target symbol's bars; peer data is
        # expected inside ``portfolio.peer_bars`` (a dict of symbol -> bars).
        peer_bars_map: dict[str, list[dict]] = ctx.portfolio.get("peer_bars", {})
        if not peer_bars_map:
            return self._hold(ctx, ["NO_PEER_BARS"])

        # Calculate momentum for each peer
        leader_momentum: dict[str, float] = {}
        for peer in sector_peers:
            p_bars = peer_bars_map.get(peer)
            if not p_bars or len(p_bars) < sector_momentum_window:
                continue
            window = p_bars[-sector_momentum_window:]
            first_close = float(window[0]["close"])
            if first_close == 0:
                continue
            ret = (float(window[-1]["close"]) - first_close) / first_close
            leader_momentum[peer] = ret

        if not leader_momentum:
            return self._hold(ctx, ["NO_PEER_MOMENTUM"])

        # Leader = peer with largest absolute move
        leader = max(leader_momentum, key=lambda k: abs(leader_momentum[k]))
        leader_return = leader_momentum[leader]

        # Correlation check (using daily close series)
        leader_bars = peer_bars_map.get(leader, [])
        my_daily = ctx.daily_bars
        if len(leader_bars) >= 20 and len(my_daily) >= 20:
            my_closes = [float(b["close"]) for b in my_daily[-60:]]
            leader_closes = [float(b["close"]) for b in leader_bars[-60:]]
            corr = _compute_correlation(my_closes, leader_closes)
        else:
            corr = 0.0

        if abs(corr) < min_correlation:
            return self._hold(ctx, ["LOW_CORRELATION"])

        # My recent return over the lag window
        my_bars = ctx.price_bars
        if len(my_bars) < leader_lag_bars:
            return self._hold(ctx, ["INSUFFICIENT_LAG_BARS"])

        lag_window = my_bars[-leader_lag_bars:]
        first_close = float(lag_window[0]["close"])
        if first_close == 0:
            return self._hold(ctx, ["INVALID_PRICE"])

        my_return = (float(lag_window[-1]["close"]) - first_close) / first_close
        lag_gap = leader_return - my_return

        if abs(lag_gap) < min_lag_gap:
            return self._hold(ctx, ["LAG_GAP_TOO_SMALL"])

        details = {
            "sector": sector,
            "leader": leader,
            "leader_return": round(leader_return, 4),
            "my_return": round(my_return, 4),
            "gap": round(lag_gap, 4),
            "correlation": round(corr, 4),
        }

        # Score is proportional to the gap, capped at 0.7
        raw_score = lag_gap * 10
        if lag_gap > 0:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="BUY",
                score=min(raw_score, 0.7),
                confidence=min(abs(lag_gap) * 5, 0.8),
                algorithm=self.name,
                reason_codes=["SECTOR_LAG_BUY"],
                details=details,
            )
        else:
            return Signal(
                symbol=ctx.symbol,
                market=ctx.market,
                decision="SELL",
                score=max(raw_score, -0.7),
                confidence=min(abs(lag_gap) * 5, 0.8),
                algorithm=self.name,
                reason_codes=["SECTOR_LAG_SELL"],
                details=details,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _hold(self, ctx: AlgorithmContext, reasons: list[str]) -> Signal:
        return Signal(
            symbol=ctx.symbol,
            market=ctx.market,
            decision="HOLD",
            score=0.0,
            confidence=0.2,
            algorithm=self.name,
            reason_codes=reasons,
            details={},
        )
