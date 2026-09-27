"""Causal regime library with synthetic ground-truth fixtures (W14).

Deterministic labels only by default. Optional HMM is FEATURE_GATED until a
proven dependency/state machine is wired — never silently claimed MEASURED.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


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


@dataclass
class RegimeEvaluationResult:
    regime_id: str
    methodology: str
    sample_count: int
    bar_count: int
    trade_count: int
    return_metrics: dict[str, Any]
    risk_metrics: dict[str, Any]
    drawdown: float | None
    turnover: float | None
    cost_sensitivity: float | None
    state: str  # MeasurementState-like
    passed: bool
    blockers: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "regimeId": self.regime_id,
            "methodology": self.methodology,
            "sampleCount": self.sample_count,
            "barCount": self.bar_count,
            "tradeCount": self.trade_count,
            "returnMetrics": dict(self.return_metrics),
            "riskMetrics": dict(self.risk_metrics),
            "drawdown": self.drawdown,
            "turnover": self.turnover,
            "costSensitivity": self.cost_sensitivity,
            "state": self.state,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "truth": {
                "strategy_metadata_is_not_regime_evidence": True,
                "hmm_not_invented": True,
            },
        }


def _bar_returns(closes: Sequence[float], returns: Sequence[float] | None) -> list[float | None]:
    """Per-bar return aligned to closes indices; index 0 has no prior close."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if returns is not None and len(returns) == n:
        return [float(r) for r in returns]  # type: ignore[return-value]
    if returns is not None and len(returns) == n - 1:
        out[0] = None
        for i, r in enumerate(returns):
            out[i + 1] = float(r)
        return out
    for i in range(1, n):
        prev = closes[i - 1]
        if prev == 0:
            out[i] = None
        else:
            out[i] = (closes[i] / prev) - 1.0
    return out


def _max_drawdown(rets: Sequence[float]) -> float | None:
    if not rets:
        return None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in rets:
        equity *= 1.0 + float(r)
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _map_trend_label(label: str) -> str:
    if label == "bull":
        return "up"
    if label == "bear":
        return "down"
    return label


def evaluate_regime_matrix(
    closes: Sequence[float],
    *,
    timestamps: Sequence[str] | None = None,
    returns: Sequence[float] | None = None,
    trade_count: int = 0,
    min_bars_per_regime: int = 10,
    policy: Mapping[str, Any] | None = None,
) -> list[RegimeEvaluationResult]:
    """Bucket bars by trend×vol labels and evaluate each non-empty cell.

    Uses existing causal detectors only. HMM is FEATURE_GATED when requested —
    never invented. Strategy metadata is never treated as regime-test evidence.
    """
    from .institutional_core.status import MeasurementState

    policy = dict(policy or {})
    results: list[RegimeEvaluationResult] = []

    # Honest FEATURE_GATED entry when HMM is requested — do not invent HMM paths.
    hmm_requested = bool(
        policy.get("hmm")
        or policy.get("include_hmm")
        or str(policy.get("methodology") or "").lower() == "hmm"
        or "hmm" in {str(x).lower() for x in (policy.get("detectors") or [])}
    )
    if hmm_requested:
        results.append(
            RegimeEvaluationResult(
                regime_id="hmm",
                methodology="hmm",
                sample_count=0,
                bar_count=len(closes),
                trade_count=int(trade_count),
                return_metrics={},
                risk_metrics={},
                drawdown=None,
                turnover=None,
                cost_sensitivity=None,
                state=MeasurementState.FEATURE_GATED.value,
                passed=False,
                blockers=["HMM_FEATURE_GATED"],
            )
        )

    n = len(closes)
    if n == 0:
        return results

    ts_list: list[str]
    if timestamps is not None and len(timestamps) == n:
        ts_list = [str(t) for t in timestamps]
    else:
        ts_list = [f"bar:{i}" for i in range(n)]

    vol_window = int(policy.get("vol_window") or 20)
    trend_fast = int(policy.get("trend_fast") or 10)
    trend_slow = int(policy.get("trend_slow") or 30)
    low_thr = float(policy.get("vol_low_threshold") or 0.005)
    high_thr = float(policy.get("vol_high_threshold") or 0.02)

    bar_rets = _bar_returns(closes, returns)
    buckets: dict[str, list[tuple[int, float | None]]] = {}

    for i in range(n):
        prefix = closes[: i + 1]
        ts = ts_list[i]
        vol = detect_volatility_regime(
            prefix,
            ts=ts,
            window=vol_window,
            low_threshold=low_thr,
            high_threshold=high_thr,
        )
        trend = detect_trend_regime(
            prefix,
            ts=ts,
            fast=trend_fast,
            slow=trend_slow,
        )
        if vol.status != "MEASURED" or trend.status != "MEASURED":
            continue
        trend_lbl = _map_trend_label(trend.label)
        vol_lbl = vol.label
        regime_id = f"trend:{trend_lbl}|vol:{vol_lbl}"
        buckets.setdefault(regime_id, []).append((i, bar_rets[i]))

    for regime_id in sorted(buckets.keys()):
        entries = buckets[regime_id]
        sample_count = len(entries)
        rets = [float(r) for _, r in entries if r is not None]
        blockers: list[str] = []
        if sample_count < min_bars_per_regime:
            state = MeasurementState.INSUFFICIENT_HISTORY.value
            passed = False
            blockers.append("INSUFFICIENT_BARS")
            return_metrics: dict[str, Any] = {
                "sum": sum(rets) if rets else None,
                "mean": (sum(rets) / len(rets)) if rets else None,
                "n_returns": len(rets),
            }
            risk_metrics: dict[str, Any] = {}
            if len(rets) >= 2:
                mean = sum(rets) / len(rets)
                var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
                risk_metrics["volatility"] = math.sqrt(var)
            dd = _max_drawdown(rets) if rets else None
            results.append(
                RegimeEvaluationResult(
                    regime_id=regime_id,
                    methodology="causal_vol_trend_bucket",
                    sample_count=sample_count,
                    bar_count=n,
                    trade_count=int(trade_count),
                    return_metrics=return_metrics,
                    risk_metrics=risk_metrics,
                    drawdown=dd,
                    turnover=None,
                    cost_sensitivity=None,
                    state=state,
                    passed=passed,
                    blockers=blockers,
                )
            )
            continue

        mean = sum(rets) / len(rets) if rets else None
        total = sum(rets) if rets else None
        risk_metrics = {}
        if len(rets) >= 2 and mean is not None:
            var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
            risk_metrics["volatility"] = math.sqrt(var)
        dd = _max_drawdown(rets) if rets else None
        state = MeasurementState.MEASURED.value if rets else MeasurementState.UNMEASURED.value
        passed = state == MeasurementState.MEASURED.value
        results.append(
            RegimeEvaluationResult(
                regime_id=regime_id,
                methodology="causal_vol_trend_bucket",
                sample_count=sample_count,
                bar_count=n,
                trade_count=int(trade_count),
                return_metrics={
                    "sum": total,
                    "mean": mean,
                    "n_returns": len(rets),
                },
                risk_metrics=risk_metrics,
                drawdown=dd,
                turnover=None,
                cost_sensitivity=None,
                state=state,
                passed=passed,
                blockers=blockers,
            )
        )

    return results


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
