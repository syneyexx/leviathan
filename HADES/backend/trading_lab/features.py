"""Deterministic feature helpers shared by strategies, models and evaluation.

Pure functions over ``list[float]``. No lookahead: every series returns ``None`` for indices
where the window is not yet complete, and index ``i`` only ever depends on values at or
before ``i``.
"""

from __future__ import annotations

import math
from typing import Sequence


def sma(values: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 0:
        return out
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        if index >= window - 1:
            out[index] = total / window
    return out


def ema(values: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 0 or not values:
        return out
    alpha = 2.0 / (window + 1.0)
    current: float | None = None
    for index, value in enumerate(values):
        current = value if current is None else (alpha * value + (1 - alpha) * current)
        if index >= window - 1:
            out[index] = current
    return out


def rolling_std(values: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 1:
        return out
    for index in range(window - 1, len(values)):
        chunk = values[index - window + 1 : index + 1]
        mean = sum(chunk) / window
        variance = sum((item - mean) ** 2 for item in chunk) / (window - 1)
        out[index] = math.sqrt(max(0.0, variance))
    return out


def zscore(values: Sequence[float], window: int) -> list[float | None]:
    means = sma(values, window)
    stds = rolling_std(values, window)
    out: list[float | None] = [None] * len(values)
    for index in range(len(values)):
        mean, std = means[index], stds[index]
        if mean is None or std is None or std <= 1e-12:
            continue
        out[index] = (values[index] - mean) / std
    return out


def simple_returns(values: Sequence[float]) -> list[float]:
    out: list[float] = []
    for index in range(1, len(values)):
        previous = values[index - 1]
        if previous == 0:
            out.append(0.0)
            continue
        out.append((values[index] - previous) / abs(previous))
    return out


def log_returns(values: Sequence[float]) -> list[float]:
    out: list[float] = []
    for index in range(1, len(values)):
        previous, current = values[index - 1], values[index]
        if previous <= 0 or current <= 0:
            out.append(0.0)
            continue
        out.append(math.log(current / previous))
    return out


def donchian(highs: Sequence[float], lows: Sequence[float], window: int) -> tuple[list[float | None], list[float | None]]:
    """Highest high and lowest low of the ``window`` bars **before** each index."""
    upper: list[float | None] = [None] * len(highs)
    lower: list[float | None] = [None] * len(lows)
    for index in range(len(highs)):
        if index < window:
            continue
        upper[index] = max(highs[index - window : index])
        lower[index] = min(lows[index - window : index])
    return upper, lower


def average_true_range(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], window: int
) -> list[float | None]:
    ranges: list[float] = [0.0]
    for index in range(1, len(closes)):
        previous_close = closes[index - 1]
        ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - previous_close),
                abs(lows[index] - previous_close),
            )
        )
    return sma(ranges, window)


def realized_volatility(values: Sequence[float], window: int) -> float | None:
    returns = log_returns(values)
    if len(returns) < window or window <= 1:
        return None
    chunk = returns[-window:]
    mean = sum(chunk) / len(chunk)
    variance = sum((item - mean) ** 2 for item in chunk) / (len(chunk) - 1)
    return math.sqrt(max(0.0, variance))


def ols_beta(y: Sequence[float], x: Sequence[float]) -> float | None:
    """Slope of a simple regression of ``y`` on ``x``."""
    length = min(len(y), len(x))
    if length < 3:
        return None
    ys, xs = y[-length:], x[-length:]
    mean_x = sum(xs) / length
    mean_y = sum(ys) / length
    denominator = sum((value - mean_x) ** 2 for value in xs)
    if denominator <= 1e-12:
        return None
    numerator = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(length))
    return numerator / denominator


def percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


__all__ = [
    "average_true_range",
    "donchian",
    "ema",
    "log_returns",
    "ols_beta",
    "percentile",
    "realized_volatility",
    "rolling_std",
    "simple_returns",
    "sma",
    "zscore",
]
