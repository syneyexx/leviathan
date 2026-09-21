"""Point-in-time market regime features.

A strategy is not "good" or "bad" in the abstract. It behaves differently in trending
versus sideways markets, and in quiet versus stressed volatility. This module turns a
closed OHLCV window that is already available at decision time into a small, interpretable
feature vector. Nothing here may look at a bar after the decision.

OHLCV-only datasets produce only OHLCV-derived features. Volume is used when present;
liquidity, cross-asset correlation and order-book stress are left unavailable rather than
invented.

Windows are documented constants, not fitted hyperparameters. Insufficient history is an
explicit result, not a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from trading_lab.features import realized_volatility, sma

TREND_FAST = 8
TREND_SLOW = 20
VOL_WINDOW = 20
VOL_HISTORY = 60
SIDEWAYS_BAND = 0.012
STRESS_VOL_MULTIPLE = 2.0
STRESS_DRAWDOWN = 0.08

TREND_LABELS = ("trending_up", "trending_down", "sideways")
VOL_LABELS = ("volatility_low", "volatility_medium", "volatility_high")
STRESS_LABELS = ("normal", "stress")


@dataclass(frozen=True)
class RegimeSnapshot:
    """Interpretable regime at one decision. All fields are computed or explicitly missing."""

    trend: str | None
    volatility: str | None
    stress: str | None
    trend_strength: float | None
    realized_vol: float | None
    vol_percentile: float | None
    volume_state: str | None
    drawdown_from_peak: float | None
    available: bool
    unavailable_reason: str = ""
    lookback_bars: int = 0
    features: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        if not self.available:
            return "unavailable"
        return f"{self.trend or 'unknown'}|{self.volatility or 'unknown'}|{self.stress or 'unknown'}"

    def as_json(self) -> dict[str, Any]:
        return {
            "trend": self.trend,
            "volatility": self.volatility,
            "stress": self.stress,
            "trend_strength": self.trend_strength,
            "realized_vol": self.realized_vol,
            "vol_percentile": self.vol_percentile,
            "volume_state": self.volume_state,
            "drawdown_from_peak": self.drawdown_from_peak,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "lookback_bars": self.lookback_bars,
            "key": self.key,
            "features": self.features,
        }


def classify_closes(
    closes: Sequence[float],
    *,
    volumes: Sequence[float] | None = None,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
) -> RegimeSnapshot:
    """Classify the regime of the *last* bar using only values at or before that bar.

    ``closes[i]`` is the close of bar *i*. Index ``-1`` is the decision bar. No future
    close is accepted; callers must slice the series first.
    """
    series = [float(value) for value in closes if value is not None]
    count = len(series)
    if count < TREND_SLOW:
        return RegimeSnapshot(
            trend=None,
            volatility=None,
            stress=None,
            trend_strength=None,
            realized_vol=None,
            vol_percentile=None,
            volume_state=None,
            drawdown_from_peak=None,
            available=False,
            unavailable_reason=f"insufficient_history:{count}_bars_need_{TREND_SLOW}",
            lookback_bars=count,
        )

    slow = sma(series, TREND_SLOW)
    fast = sma(series, TREND_FAST)
    last_slow = slow[-1]
    last_fast = fast[-1]
    last_price = series[-1]
    if last_slow is None or last_slow == 0 or last_fast is None:
        return RegimeSnapshot(
            trend=None,
            volatility=None,
            stress=None,
            trend_strength=None,
            realized_vol=None,
            vol_percentile=None,
            volume_state=None,
            drawdown_from_peak=None,
            available=False,
            unavailable_reason="sma_not_ready",
            lookback_bars=count,
        )

    gap = (last_price / last_slow) - 1.0
    fast_gap = (last_fast / last_slow) - 1.0
    strength = abs(gap)
    if strength < SIDEWAYS_BAND and abs(fast_gap) < SIDEWAYS_BAND:
        trend = "sideways"
    elif gap > 0 and fast_gap >= 0:
        trend = "trending_up"
    elif gap < 0 and fast_gap <= 0:
        trend = "trending_down"
    else:
        trend = "sideways"

    vol = realized_volatility(series, VOL_WINDOW)
    history: list[float] = []
    start = max(VOL_WINDOW, count - VOL_HISTORY)
    for index in range(start, count + 1):
        sample = realized_volatility(series[:index], VOL_WINDOW)
        if sample is not None:
            history.append(sample)
    percentile = _percentile_rank(history[:-1] if len(history) > 1 else [], vol) if vol is not None else None
    if vol is None or percentile is None:
        volatility = None
        vol_reason = "insufficient_volatility_history"
    elif percentile < 1.0 / 3.0:
        volatility = "volatility_low"
        vol_reason = ""
    elif percentile > 2.0 / 3.0:
        volatility = "volatility_high"
        vol_reason = ""
    else:
        volatility = "volatility_medium"
        vol_reason = ""

    peak = max(series)
    drawdown = 0.0 if peak <= 0 else (series[-1] / peak) - 1.0
    median_vol = _median(history[:-1]) if len(history) > 1 else None
    stressed = False
    if median_vol is not None and vol is not None and median_vol > 0 and vol >= STRESS_VOL_MULTIPLE * median_vol:
        stressed = True
    if abs(drawdown) >= STRESS_DRAWDOWN:
        stressed = True
    stress = "stress" if stressed else "normal"

    volume_state = None
    if volumes and len(volumes) >= VOL_WINDOW:
        recent = list(volumes)[-VOL_WINDOW:]
        median_volume = _median([float(item) for item in recent[:-1]]) if len(recent) > 1 else None
        last_volume = float(recent[-1])
        if median_volume and median_volume > 0:
            if last_volume >= 1.5 * median_volume:
                volume_state = "volume_high"
            elif last_volume <= 0.6 * median_volume:
                volume_state = "volume_low"
            else:
                volume_state = "volume_normal"

    available = volatility is not None
    return RegimeSnapshot(
        trend=trend,
        volatility=volatility,
        stress=stress if available else None,
        trend_strength=strength,
        realized_vol=vol,
        vol_percentile=percentile,
        volume_state=volume_state,
        drawdown_from_peak=drawdown,
        available=available,
        unavailable_reason="" if available else vol_reason,
        lookback_bars=count,
        features={
            "price_vs_slow_sma": gap,
            "fast_vs_slow_sma": fast_gap,
            "windows": {"trend_fast": TREND_FAST, "trend_slow": TREND_SLOW, "vol": VOL_WINDOW},
            "highs_used": bool(highs),
            "lows_used": bool(lows),
        },
    )


def regime_matches(snapshot: RegimeSnapshot, required: dict[str, Any] | None) -> tuple[bool, str]:
    """Return whether a declared filter matches a point-in-time snapshot."""
    if not required:
        return True, "no_filter"
    if not snapshot.available:
        return False, snapshot.unavailable_reason or "regime_unavailable"
    for field_name, expected in required.items():
        if expected in (None, "", "*", "any"):
            continue
        actual = getattr(snapshot, field_name, None)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False, f"regime_filter_miss:{field_name}={actual}_not_in_{list(expected)}"
        elif actual != expected:
            return False, f"regime_filter_miss:{field_name}={actual}_want_{expected}"
    return True, "matched"


def _percentile_rank(history: Sequence[float], value: float | None) -> float | None:
    if value is None or not history:
        return None
    below = sum(1 for item in history if item <= value)
    return below / len(history)


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


__all__ = [
    "RegimeSnapshot",
    "SIDEWAYS_BAND",
    "STRESS_DRAWDOWN",
    "STRESS_LABELS",
    "STRESS_VOL_MULTIPLE",
    "TREND_FAST",
    "TREND_LABELS",
    "TREND_SLOW",
    "VOL_HISTORY",
    "VOL_LABELS",
    "VOL_WINDOW",
    "classify_closes",
    "regime_matches",
]
