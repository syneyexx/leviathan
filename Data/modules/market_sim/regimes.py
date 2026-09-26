"""Causal regime library with synthetic ground-truth fixtures (W14).

Deterministic labels only by default. Optional HMM is FEATURE_GATED until a
proven dependency/state machine is wired — never silently claimed MEASURED.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


REGIME_DETECTOR_VERSION = "regime_lib-1"


class RegimeKind(str, Enum):
    VOLATILITY = "volatility"
    TREND = "trend"
    CORRELATION = "correlation"
    CHANGEPOINT = "changepoint"
    HMM = "hmm"  # FEATURE_GATED


@dataclass(frozen=True)
class RegimeLabel:
    ts: str
    kind: RegimeKind
    label: str
    value: float | None
    status: str  # MEASURED | UNMEASURED | FEATURE_GATED
    provenance: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "kind": self.kind.value,
            "label": self.label,
            "value": self.value,
            "status": self.status,
            "provenance": self.provenance,
            "detector_version": REGIME_DETECTOR_VERSION,
        }


@dataclass
class RegimeSeries:
    kind: RegimeKind
    labels: list[RegimeLabel] = field(default_factory=list)
    detector_version: str = REGIME_DETECTOR_VERSION

    def public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "detector_version": self.detector_version,
            "labels": [l.public_dict() for l in self.labels],
            "n": len(self.labels),
        }


def _realized_vol(closes: Sequence[float], window: int) -> float | None:
    if len(closes) < window + 1:
        return None
    rets = []
    for i in range(len(closes) - window, len(closes)):
        prev = closes[i - 1]
        if prev == 0:
            continue
        rets.append(math.log(closes[i] / prev))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def detect_volatility_regime(
    closes: Sequence[float],
    *,
    ts: str,
    window: int = 20,
    low_threshold: float = 0.005,
    high_threshold: float = 0.02,
) -> RegimeLabel:
    vol = _realized_vol(closes, window)
    if vol is None:
        return RegimeLabel(ts, RegimeKind.VOLATILITY, "unknown", None, "UNMEASURED", "insufficient_bars")
    if vol < low_threshold:
        label = "low"
    elif vol > high_threshold:
        label = "high"
    else:
        label = "medium"
    return RegimeLabel(ts, RegimeKind.VOLATILITY, label, vol, "MEASURED", f"realized_vol_w{window}")


def detect_trend_regime(
    closes: Sequence[float],
    *,
    ts: str,
    fast: int = 10,
    slow: int = 30,
) -> RegimeLabel:
    if len(closes) < slow:
        return RegimeLabel(ts, RegimeKind.TREND, "unknown", None, "UNMEASURED", "insufficient_bars")
    sma_fast = sum(closes[-fast:]) / fast
    sma_slow = sum(closes[-slow:]) / slow
    slope = (sma_fast - sma_slow) / sma_slow if sma_slow else 0.0
    if sma_fast > sma_slow * 1.001:
        label = "bull"
    elif sma_fast < sma_slow * 0.999:
        label = "bear"
    else:
        label = "flat"
    return RegimeLabel(ts, RegimeKind.TREND, label, slope, "MEASURED", f"sma_{fast}_{slow}")


def detect_correlation_regime(
    series_a: Sequence[float],
    series_b: Sequence[float],
    *,
    ts: str,
    window: int = 30,
) -> RegimeLabel:
    n = min(len(series_a), len(series_b))
    if n < window:
        return RegimeLabel(ts, RegimeKind.CORRELATION, "unknown", None, "UNMEASURED", "insufficient_bars")
    a = series_a[-window:]
    b = series_b[-window:]
    ma = sum(a) / window
    mb = sum(b) / window
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (window - 1)
    va = sum((x - ma) ** 2 for x in a) / (window - 1)
    vb = sum((y - mb) ** 2 for y in b) / (window - 1)
    if va <= 0 or vb <= 0:
        return RegimeLabel(ts, RegimeKind.CORRELATION, "unknown", None, "UNMEASURED", "zero_variance")
    corr = cov / math.sqrt(va * vb)
    if corr > 0.5:
        label = "high_positive"
    elif corr < -0.5:
        label = "high_negative"
    else:
        label = "low"
    return RegimeLabel(ts, RegimeKind.CORRELATION, label, corr, "MEASURED", f"pearson_w{window}")


def detect_changepoints(
    closes: Sequence[float],
    *,
    timestamps: Sequence[str],
    window: int = 20,
    z_threshold: float = 3.0,
) -> list[RegimeLabel]:
    """Simple mean-shift changepoint detector — causal, uses only past window."""
    out: list[RegimeLabel] = []
    if len(closes) != len(timestamps) or len(closes) < window * 2:
        return out
    for i in range(window * 2, len(closes)):
        prev = closes[i - 2 * window : i - window]
        cur = closes[i - window : i]
        mp = sum(prev) / len(prev)
        mc = sum(cur) / len(cur)
        var = sum((x - mp) ** 2 for x in prev) / max(1, len(prev) - 1)
        sd = math.sqrt(var) if var > 0 else 0.0
        if sd <= 0:
            continue
        z = abs(mc - mp) / sd
        if z >= z_threshold:
            out.append(
                RegimeLabel(
                    timestamps[i],
                    RegimeKind.CHANGEPOINT,
                    "shift",
                    z,
                    "MEASURED",
                    f"mean_shift_w{window}_z{z_threshold}",
                )
            )
    return out


def hmm_regime_capability() -> dict[str, Any]:
    return {
        "kind": RegimeKind.HMM.value,
        "status": "FEATURE_GATED",
        "reason": "HMM regime detector requires explicit dependency/state wiring before MEASURED",
        "truth": {"not_silently_measured": True},
    }


def synthetic_known_regime_fixture(*, n: int = 120, seed: int = 7) -> dict[str, Any]:
    """Ground-truth synthetic series: low-vol flat → high-vol bear → bull trend.

    Used to validate detectors — never as a profitability claim.
    """
    import random

    rng = random.Random(seed)
    closes: list[float] = []
    truths: list[str] = []
    price = 100.0
    for i in range(n):
        if i < n // 3:
            truth = "low_flat"
            price *= 1.0 + rng.uniform(-0.001, 0.001)
        elif i < 2 * n // 3:
            truth = "high_bear"
            price *= 1.0 + rng.uniform(-0.03, 0.01)
        else:
            truth = "bull"
            price *= 1.0 + rng.uniform(-0.005, 0.02)
        closes.append(price)
        truths.append(truth)
    ts = [f"2020-01-01T00:{i // 60:02d}:{i % 60:02d}Z" for i in range(n)]
    mid = n // 2
    vol = detect_volatility_regime(closes[: mid + 1], ts=ts[mid], window=15, low_threshold=0.002, high_threshold=0.01)
    trend_end = detect_trend_regime(closes, ts=ts[-1], fast=5, slow=15)
    return {
        "closes": closes,
        "timestamps": ts,
        "ground_truth_segments": truths,
        "detector_vol_mid": vol.public_dict(),
        "detector_trend_end": trend_end.public_dict(),
        "truth": {
            "synthetic_fixture": True,
            "not_a_profit_claim": True,
            "known_ground_truth": True,
        },
    }
