"""Pure-function technical indicator calculations.

Every function in this module is stateless and depends only on the
Python standard library -- no external TA library required.

Functions
---------
sma             Simple Moving Average
ema             Exponential Moving Average
stdev           Sample standard deviation
compute_rsi     Relative Strength Index
compute_macd    MACD (line, signal, histogram)
compute_bollinger   Bollinger Bands (upper, middle, lower)
compute_atr     Average True Range
compute_obv     On-Balance Volume series
weighted_avg    Volume-Weighted Average Price (VWAP)
volume_skew     Volume distribution skew
trend_direction Trend direction (+1, -1, 0)
"""

from __future__ import annotations

import math
from statistics import mean


# ------------------------------------------------------------------
# Basic statistics
# ------------------------------------------------------------------

def sma(values: list[float], period: int) -> float:
    """Simple Moving Average of the last *period* values.

    Returns 0.0 when *values* is empty or *period* <= 0.
    """
    if not values or period <= 0:
        return 0.0
    window = values[-period:]
    return sum(window) / len(window)


def ema(values: list[float], period: int) -> float:
    """Exponential Moving Average of *values* over *period*.

    Uses the standard multiplier ``k = 2 / (period + 1)`` and seeds
    with the SMA of the first *period* elements.
    """
    if not values or period <= 0:
        return 0.0
    if len(values) < period:
        return sma(values, len(values))

    k = 2.0 / (period + 1)
    result = sma(values[:period], period)
    for v in values[period:]:
        result = v * k + result * (1.0 - k)
    return result


def stdev(values: list[float]) -> float:
    """Population standard deviation of *values*.

    Returns 0.0 for fewer than 2 data points.
    """
    n = len(values)
    if n < 2:
        return 0.0
    avg = sum(values) / n
    variance = sum((v - avg) ** 2 for v in values) / n
    return math.sqrt(variance)


# ------------------------------------------------------------------
# Oscillators
# ------------------------------------------------------------------

def compute_rsi(closes: list[float], period: int = 14) -> float:
    """Relative Strength Index (Wilder smoothing).

    Returns 50.0 (neutral) when there is insufficient data.
    """
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ------------------------------------------------------------------
# MACD
# ------------------------------------------------------------------

def _ema_series(values: list[float], period: int) -> list[float]:
    """Full EMA series (internal helper)."""
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1)
    result: list[float] = [sma(values[:period], period)]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1.0 - k))
    return result


def compute_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float, float]:
    """MACD calculation.

    Returns ``(macd_line, signal_line, histogram)`` as the most recent
    values.  Falls back to ``(0.0, 0.0, 0.0)`` on insufficient data.
    """
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0

    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)

    # Align lengths -- fast EMA starts earlier than slow EMA
    offset = slow - fast
    macd_line_series = [
        ema_fast[offset + i] - ema_slow[i] for i in range(len(ema_slow))
    ]

    if len(macd_line_series) < signal:
        return macd_line_series[-1] if macd_line_series else 0.0, 0.0, 0.0

    signal_series = _ema_series(macd_line_series, signal)

    macd_val = macd_line_series[-1]
    signal_val = signal_series[-1]
    histogram = macd_val - signal_val

    return macd_val, signal_val, histogram


# ------------------------------------------------------------------
# Bollinger Bands
# ------------------------------------------------------------------

def compute_bollinger(
    closes: list[float],
    period: int = 20,
    std_mult: float = 2.0,
) -> tuple[float, float, float]:
    """Bollinger Bands.

    Returns ``(upper, middle, lower)``.  Falls back to
    ``(close, close, close)`` when there is insufficient data.
    """
    if not closes:
        return 0.0, 0.0, 0.0
    if len(closes) < period:
        mid = sma(closes, len(closes))
        return mid, mid, mid

    window = closes[-period:]
    mid = sum(window) / period
    sd = stdev(window)

    upper = mid + std_mult * sd
    lower = mid - std_mult * sd

    return upper, mid, lower


# ------------------------------------------------------------------
# ATR
# ------------------------------------------------------------------

def compute_atr(bars: list[dict], period: int = 14) -> float:
    """Average True Range.

    Each bar dict must contain ``high``, ``low``, and ``close`` keys.
    Returns 0.0 when there is insufficient data.
    """
    if len(bars) < 2:
        return 0.0

    true_ranges: list[float] = []
    for i in range(1, len(bars)):
        high = float(bars[i]["high"])
        low = float(bars[i]["low"])
        prev_close = float(bars[i - 1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return mean(true_ranges) if true_ranges else 0.0

    # Wilder smoothing
    atr = mean(true_ranges[:period])
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


# ------------------------------------------------------------------
# OBV
# ------------------------------------------------------------------

def compute_obv(bars: list[dict]) -> list[float]:
    """On-Balance Volume cumulative series.

    Each bar dict must have ``close`` and ``volume`` keys.
    Returns an empty list for empty input.
    """
    if not bars:
        return []

    obv: list[float] = [float(bars[0]["volume"])]
    for i in range(1, len(bars)):
        vol = float(bars[i]["volume"])
        if bars[i]["close"] > bars[i - 1]["close"]:
            obv.append(obv[-1] + vol)
        elif bars[i]["close"] < bars[i - 1]["close"]:
            obv.append(obv[-1] - vol)
        else:
            obv.append(obv[-1])
    return obv


# ------------------------------------------------------------------
# Derived helpers
# ------------------------------------------------------------------

def weighted_avg(bars: list[dict]) -> float:
    """Volume-Weighted Average Price (VWAP) over a bar series.

    Each bar dict must have ``close`` and ``volume`` keys.
    Returns the last close when total volume is zero.
    """
    if not bars:
        return 0.0
    total_vol = sum(float(b["volume"]) for b in bars)
    if total_vol == 0:
        return float(bars[-1]["close"])
    return sum(float(b["close"]) * float(b["volume"]) for b in bars) / total_vol


def volume_skew(bars: list[dict]) -> float:
    """Volume distribution skew.

    Compares the volume in the second half of the window to the first
    half.  Positive values indicate back-loaded volume (buying into
    the close), negative values indicate front-loaded selling.

    Returns a value in ``[-1.0, +1.0]``.  Returns 0.0 for empty input
    or zero total volume.
    """
    if len(bars) < 2:
        return 0.0
    total_vol = sum(float(b["volume"]) for b in bars)
    if total_vol == 0:
        return 0.0
    mid = len(bars) // 2
    first_half = sum(float(b["volume"]) for b in bars[:mid])
    second_half = sum(float(b["volume"]) for b in bars[mid:])
    return (second_half - first_half) / total_vol


def trend_direction(bars: list[dict]) -> int:
    """Determine the overall trend from a bar series.

    Uses a simple comparison of the first and last closing prices with
    a small noise filter (0.1 %).

    Returns ``1`` (up), ``-1`` (down), or ``0`` (flat).
    """
    if len(bars) < 2:
        return 0
    first_close = float(bars[0]["close"])
    last_close = float(bars[-1]["close"])
    if first_close == 0:
        return 0
    pct_change = (last_close - first_close) / first_close
    if pct_change > 0.001:
        return 1
    if pct_change < -0.001:
        return -1
    return 0
