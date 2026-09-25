"""Deterministic causal feature primitives for OHLCV bars.

Features are MEASURED facts with provenance — never neural hypotheses.
OHLCV is not an L2 order book: imbalance / queue / depth are NOT_IMPLEMENTED.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Sequence

from .types import Bar, CausalityViolation, MetricStatus, MarketSimError

FEATURE_PIPELINE_VERSION = "market_features-2"

# Names that must never be claimed from OHLCV alone.
FORBIDDEN_OHLCV_FEATURES = frozenset(
    {
        "order_book_imbalance",
        "queue_position",
        "bid_ask_depth",
        "bid_depth",
        "ask_depth",
        "l2_imbalance",
        "microprice",
    }
)


class FeatureStatus(str, Enum):
    MEASURED = MetricStatus.MEASURED.value
    UNMEASURED = MetricStatus.UNMEASURED.value
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


@dataclass(frozen=True)
class FeatureValue:
    name: str
    value: float | None
    status: str
    params: dict[str, Any] = field(default_factory=dict)
    as_of: str | None = None
    lookback_used: int = 0
    provenance: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "status": self.status,
            "params": self.params,
            "as_of": self.as_of,
            "lookback_used": self.lookback_used,
            "provenance": self.provenance,
            "truth": {
                "deterministic": True,
                "not_neural_hypothesis": True,
                "pipeline_version": FEATURE_PIPELINE_VERSION,
            },
        }


def _provenance(*, as_of: str | None, bar_count: int, first_ts: str | None, last_ts: str | None) -> dict[str, Any]:
    return {
        "pipeline_version": FEATURE_PIPELINE_VERSION,
        "as_of": as_of,
        "bar_count": bar_count,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "source": "ohlcv_causal_window",
    }


def _insuff(name: str, *, params: dict[str, Any], as_of: str | None, need: int, have: int) -> FeatureValue:
    return FeatureValue(
        name=name,
        value=None,
        status=FeatureStatus.INSUFFICIENT_HISTORY.value,
        params=params,
        as_of=as_of,
        lookback_used=have,
        provenance={
            "pipeline_version": FEATURE_PIPELINE_VERSION,
            "required_bars": need,
            "available_bars": have,
            "as_of": as_of,
        },
    )


def _measured(
    name: str,
    value: float,
    *,
    params: dict[str, Any],
    bars: Sequence[Bar],
    as_of: str | None,
) -> FeatureValue:
    return FeatureValue(
        name=name,
        value=float(value),
        status=FeatureStatus.MEASURED.value,
        params=params,
        as_of=as_of,
        lookback_used=len(bars),
        provenance=_provenance(
            as_of=as_of,
            bar_count=len(bars),
            first_ts=bars[0].ts if bars else None,
            last_ts=bars[-1].ts if bars else None,
        ),
    )


def sma(values: Sequence[float], period: int) -> float | None:
    if period < 1 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def ema(values: Sequence[float], period: int) -> float | None:
    if period < 1 or len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    # Seed with SMA of first `period` points in the lookback window used.
    seed = values[-period:]
    acc = sum(seed[:period]) / period
    for v in seed[period:]:
        acc = alpha * v + (1.0 - alpha) * acc
    # Recompute properly over full series ending at last value, seeded by SMA of first period.
    if len(values) == period:
        return acc
    # Full EMA walk from start of provided series for determinism.
    start = values[0]
    acc = start
    # Better: seed with SMA of first period then walk remainder
    if len(values) >= period:
        acc = sum(values[:period]) / period
        for v in values[period:]:
            acc = alpha * v + (1.0 - alpha) * acc
        return acc
    return None


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    if period < 1 or len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    # Wilder-style seed over first `period` changes
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss <= 1e-12:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(bars: Sequence[Bar], period: int = 14) -> float | None:
    if period < 1 or len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    # Wilder smoothing
    acc = sum(trs[:period]) / period
    for tr in trs[period:]:
        acc = (acc * (period - 1) + tr) / period
    return acc


def true_range_series(bars: Sequence[Bar]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        out.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return out


def adx(bars: Sequence[Bar], period: int = 14) -> float | None:
    """Average Directional Index (Wilder). Returns None if insufficient history."""
    if period < 1 or len(bars) < period * 2 + 1:
        return None
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs = true_range_series(bars)
    for i in range(1, len(bars)):
        up = bars[i].high - bars[i - 1].high
        down = bars[i - 1].low - bars[i].low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    if len(trs) < period:
        return None

    def wilder(series: list[float]) -> list[float]:
        out: list[float] = []
        acc = sum(series[:period])
        out.append(acc)
        for v in series[period:]:
            acc = acc - (acc / period) + v
            out.append(acc)
        return out

    atr_w = wilder(trs)
    plus_w = wilder(plus_dm)
    minus_w = wilder(minus_dm)
    dx_vals: list[float] = []
    for i in range(len(atr_w)):
        if atr_w[i] <= 1e-12:
            dx_vals.append(0.0)
            continue
        pdi = 100.0 * plus_w[i] / atr_w[i]
        mdi = 100.0 * minus_w[i] / atr_w[i]
        denom = pdi + mdi
        dx_vals.append(0.0 if denom <= 1e-12 else 100.0 * abs(pdi - mdi) / denom)
    if len(dx_vals) < period:
        return None
    adx_acc = sum(dx_vals[:period]) / period
    for v in dx_vals[period:]:
        adx_acc = (adx_acc * (period - 1) + v) / period
    return adx_acc


def bollinger(
    closes: Sequence[float], period: int = 20, num_std: float = 2.0
) -> tuple[float, float, float] | None:
    if period < 2 or len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    std = math.sqrt(var)
    return mid - num_std * std, mid, mid + num_std * std


def rolling_zscore(closes: Sequence[float], period: int = 20) -> float | None:
    if period < 2 or len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    std = math.sqrt(var)
    if std <= 1e-12:
        return 0.0
    return (closes[-1] - mean) / std


def rate_of_change(closes: Sequence[float], period: int = 10) -> float | None:
    if period < 1 or len(closes) < period + 1:
        return None
    base = closes[-(period + 1)]
    if abs(base) <= 1e-12:
        return None
    return (closes[-1] - base) / base


def rolling_return(closes: Sequence[float], period: int = 1) -> float | None:
    if period < 1 or len(closes) < period + 1:
        return None
    base = closes[-(period + 1)]
    if abs(base) <= 1e-12:
        return None
    return (closes[-1] - base) / base


def realized_volatility(closes: Sequence[float], period: int = 20) -> float | None:
    """Stdev of simple returns over ``period`` returns (needs period+1 closes)."""
    if period < 2 or len(closes) < period + 1:
        return None
    rets: list[float] = []
    for i in range(len(closes) - period, len(closes)):
        prev = closes[i - 1]
        if abs(prev) <= 1e-12:
            continue
        rets.append((closes[i] - prev) / prev)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return math.sqrt(var)


def volatility_percentile(
    closes: Sequence[float], period: int = 20, lookback: int = 100
) -> float | None:
    """Percentile of current realized vol vs trailing window of realized vols."""
    need = lookback + period
    if len(closes) < need:
        return None
    vols: list[float] = []
    for end in range(period + 1, len(closes) + 1):
        v = realized_volatility(closes[:end], period=period)
        if v is not None:
            vols.append(v)
    if len(vols) < lookback:
        return None
    window = vols[-lookback:]
    current = window[-1]
    below = sum(1 for v in window if v <= current)
    return 100.0 * below / len(window)


def rolling_high(bars: Sequence[Bar], period: int) -> float | None:
    if period < 1 or len(bars) < period:
        return None
    return max(b.high for b in bars[-period:])


def rolling_low(bars: Sequence[Bar], period: int) -> float | None:
    if period < 1 or len(bars) < period:
        return None
    return min(b.low for b in bars[-period:])


def donchian(bars: Sequence[Bar], period: int = 20) -> tuple[float, float, float] | None:
    hi = rolling_high(bars, period)
    lo = rolling_low(bars, period)
    if hi is None or lo is None:
        return None
    return lo, (hi + lo) / 2.0, hi


def momentum(closes: Sequence[float], period: int = 10) -> float | None:
    if period < 1 or len(closes) < period + 1:
        return None
    return closes[-1] - closes[-(period + 1)]


def relative_strength(closes_a: Sequence[float], closes_b: Sequence[float], period: int = 20) -> float | None:
    """Ratio ROC of A vs B over period — both series must be aligned & causal."""
    if period < 1 or len(closes_a) < period + 1 or len(closes_b) < period + 1:
        return None
    ra = rate_of_change(closes_a, period)
    rb = rate_of_change(closes_b, period)
    if ra is None or rb is None:
        return None
    return ra - rb


def vwap(bars: Sequence[Bar], period: int | None = None) -> float | None:
    window = bars if period is None else bars[-period:]
    if period is not None and len(bars) < period:
        return None
    if not window:
        return None
    num = 0.0
    den = 0.0
    for b in window:
        typical = (b.high + b.low + b.close) / 3.0
        num += typical * b.volume
        den += b.volume
    if den <= 1e-12:
        return None
    return num / den


def volume_average(bars: Sequence[Bar], period: int = 20) -> float | None:
    if period < 1 or len(bars) < period:
        return None
    return sum(b.volume for b in bars[-period:]) / period


def volume_zscore(bars: Sequence[Bar], period: int = 20) -> float | None:
    if period < 2 or len(bars) < period:
        return None
    vols = [b.volume for b in bars[-period:]]
    mean = sum(vols) / period
    var = sum((v - mean) ** 2 for v in vols) / period
    std = math.sqrt(var)
    if std <= 1e-12:
        return 0.0
    return (bars[-1].volume - mean) / std


def breakout_state(bars: Sequence[Bar], period: int = 20) -> float | None:
    """+1 close above Donchian high of prior period, -1 below low, else 0.

    Uses prior window (excluding current bar) to avoid same-bar tautology.
    """
    if period < 1 or len(bars) < period + 1:
        return None
    prior = bars[-(period + 1) : -1]
    hi = max(b.high for b in prior)
    lo = min(b.low for b in prior)
    close = bars[-1].close
    if close > hi:
        return 1.0
    if close < lo:
        return -1.0
    return 0.0


def trend_slope(closes: Sequence[float], period: int = 20) -> float | None:
    """OLS slope of closes vs index over period, normalized by mean price."""
    if period < 2 or len(closes) < period:
        return None
    ys = closes[-period:]
    n = float(period)
    xs = list(range(period))
    mean_x = (n - 1.0) / 2.0
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den <= 1e-12 or abs(mean_y) <= 1e-12:
        return 0.0
    return (num / den) / mean_y


def drawdown(closes: Sequence[float], period: int | None = None) -> float | None:
    """Current drawdown from peak within window (0 = at peak, positive fraction)."""
    window = closes if period is None else closes[-period:]
    if period is not None and len(closes) < period:
        return None
    if not window:
        return None
    peak = window[0]
    max_dd = 0.0
    for v in window:
        if v > peak:
            peak = v
        if peak > 1e-12:
            max_dd = max(max_dd, (peak - v) / peak)
    # Return current drawdown from running peak (not max historical in window)
    peak = window[0]
    for v in window:
        if v > peak:
            peak = v
    if peak <= 1e-12:
        return 0.0
    return (peak - window[-1]) / peak


def pearson_correlation(a: Sequence[float], b: Sequence[float], period: int = 20) -> float | None:
    if period < 2 or len(a) < period or len(b) < period:
        return None
    xs = a[-period:]
    ys = b[-period:]
    mean_x = sum(xs) / period
    mean_y = sum(ys) / period
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x <= 1e-12 or den_y <= 1e-12:
        return 0.0
    return num / (den_x * den_y)


def rolling_beta(asset: Sequence[float], benchmark: Sequence[float], period: int = 20) -> float | None:
    """Beta of asset simple returns vs benchmark returns."""
    if period < 2 or len(asset) < period + 1 or len(benchmark) < period + 1:
        return None
    ra: list[float] = []
    rb: list[float] = []
    for i in range(len(asset) - period, len(asset)):
        if abs(asset[i - 1]) <= 1e-12 or abs(benchmark[i - 1]) <= 1e-12:
            continue
        ra.append((asset[i] - asset[i - 1]) / asset[i - 1])
        rb.append((benchmark[i] - benchmark[i - 1]) / benchmark[i - 1])
    if len(ra) < 2:
        return None
    mean_a = sum(ra) / len(ra)
    mean_b = sum(rb) / len(rb)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb)) / len(ra)
    var_b = sum((y - mean_b) ** 2 for y in rb) / len(rb)
    if var_b <= 1e-12:
        return 0.0
    return cov / var_b


def spread(closes_a: Sequence[float], closes_b: Sequence[float]) -> float | None:
    if not closes_a or not closes_b:
        return None
    return closes_a[-1] - closes_b[-1]


class FeatureEngine:
    """Compute named features from a causal bar window only."""

    version = FEATURE_PIPELINE_VERSION

    def compute(
        self,
        bars: Sequence[Bar],
        name: str,
        *,
        as_of: str | None = None,
        period: int | None = None,
        benchmark_bars: Sequence[Bar] | None = None,
        num_std: float = 2.0,
        lookback: int | None = None,
    ) -> FeatureValue:
        key = name.strip().lower()
        if key in FORBIDDEN_OHLCV_FEATURES:
            return FeatureValue(
                name=key,
                value=None,
                status=FeatureStatus.NOT_IMPLEMENTED.value,
                params={"reason": "OHLCV_is_not_orderbook"},
                as_of=as_of,
                provenance={
                    "pipeline_version": FEATURE_PIPELINE_VERSION,
                    "truth": {"ohlcv_is_not_orderbook": True},
                },
            )

        as_of_ts = as_of or (bars[-1].ts if bars else None)
        closes = [b.close for b in bars]
        p = int(period) if period is not None else self._default_period(key)

        if key in {"sma", "sma_close"}:
            need = p
            if len(closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            val = sma(closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "ema":
            need = p
            if len(closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            val = ema(closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "rsi":
            need = p + 1
            if len(closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            val = rsi(closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "atr":
            need = p + 1
            if len(bars) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(bars))
            val = atr(bars, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "adx":
            need = p * 2 + 1
            if len(bars) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(bars))
            val = adx(bars, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"bollinger", "bollinger_mid", "bollinger_upper", "bollinger_lower", "bollinger_pct_b"}:
            need = p
            if len(closes) < need:
                return _insuff(key, params={"period": p, "num_std": num_std}, as_of=as_of_ts, need=need, have=len(closes))
            band = bollinger(closes, p, num_std)
            assert band is not None
            lower, mid, upper = band
            if key == "bollinger_lower":
                return _measured(key, lower, params={"period": p, "num_std": num_std}, bars=bars, as_of=as_of_ts)
            if key == "bollinger_upper":
                return _measured(key, upper, params={"period": p, "num_std": num_std}, bars=bars, as_of=as_of_ts)
            if key == "bollinger_pct_b":
                width = upper - lower
                pct_b = 0.5 if width <= 1e-12 else (closes[-1] - lower) / width
                return _measured(key, pct_b, params={"period": p, "num_std": num_std}, bars=bars, as_of=as_of_ts)
            # bollinger / bollinger_mid
            return _measured("bollinger_mid" if key == "bollinger" else key, mid, params={"period": p, "num_std": num_std}, bars=bars, as_of=as_of_ts)

        if key in {"zscore", "rolling_zscore"}:
            need = p
            if len(closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            val = rolling_zscore(closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"roc", "rate_of_change"}:
            need = p + 1
            if len(closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            val = rate_of_change(closes, p)
            if val is None:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"return", "rolling_return"}:
            need = p + 1
            if len(closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            val = rolling_return(closes, p)
            if val is None:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"realized_vol", "realized_volatility"}:
            need = p + 1
            if len(closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            val = realized_volatility(closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"vol_percentile", "volatility_percentile"}:
            lb = int(lookback or 100)
            need = lb + p
            if len(closes) < need:
                return _insuff(key, params={"period": p, "lookback": lb}, as_of=as_of_ts, need=need, have=len(closes))
            val = volatility_percentile(closes, p, lb)
            assert val is not None
            return _measured(key, val, params={"period": p, "lookback": lb}, bars=bars, as_of=as_of_ts)

        if key == "rolling_high":
            need = p
            if len(bars) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(bars))
            val = rolling_high(bars, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "rolling_low":
            need = p
            if len(bars) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(bars))
            val = rolling_low(bars, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"donchian_high", "donchian_mid", "donchian_low", "donchian"}:
            need = p
            if len(bars) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(bars))
            band = donchian(bars, p)
            assert band is not None
            lo, mid, hi = band
            mapping = {"donchian_low": lo, "donchian_mid": mid, "donchian_high": hi, "donchian": mid}
            return _measured(key, mapping[key], params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "momentum":
            need = p + 1
            if len(closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            val = momentum(closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "vwap":
            need = p if period is not None else 1
            use_period = p if period is not None else None
            if use_period is not None and len(bars) < use_period:
                return _insuff(key, params={"period": use_period}, as_of=as_of_ts, need=use_period, have=len(bars))
            val = vwap(bars, use_period)
            if val is None:
                return FeatureValue(
                    name=key,
                    value=None,
                    status=FeatureStatus.UNMEASURED.value,
                    params={"period": use_period, "reason": "zero_volume"},
                    as_of=as_of_ts,
                )
            return _measured(key, val, params={"period": use_period}, bars=bars, as_of=as_of_ts)

        if key in {"volume_avg", "volume_average"}:
            need = p
            if len(bars) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(bars))
            val = volume_average(bars, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"volume_z", "volume_zscore"}:
            need = p
            if len(bars) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(bars))
            val = volume_zscore(bars, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"breakout", "breakout_state"}:
            need = p + 1
            if len(bars) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(bars))
            val = breakout_state(bars, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"trend_slope", "slope"}:
            need = p
            if len(closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=len(closes))
            val = trend_slope(closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "drawdown":
            need = p if period is not None else 1
            use_period = p if period is not None else None
            if use_period is not None and len(closes) < use_period:
                return _insuff(key, params={"period": use_period}, as_of=as_of_ts, need=use_period, have=len(closes))
            val = drawdown(closes, use_period)
            assert val is not None
            return _measured(key, val, params={"period": use_period}, bars=bars, as_of=as_of_ts)

        if key in {"correlation", "corr"}:
            if benchmark_bars is None:
                raise MarketSimError("FEATURE_NEEDS_BENCHMARK", f"{key} requires benchmark_bars")
            need = p
            b_closes = [b.close for b in benchmark_bars]
            if len(closes) < need or len(b_closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=min(len(closes), len(b_closes)))
            val = pearson_correlation(closes, b_closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "beta":
            if benchmark_bars is None:
                raise MarketSimError("FEATURE_NEEDS_BENCHMARK", "beta requires benchmark_bars")
            need = p + 1
            b_closes = [b.close for b in benchmark_bars]
            if len(closes) < need or len(b_closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=min(len(closes), len(b_closes)))
            val = rolling_beta(closes, b_closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key == "spread":
            if benchmark_bars is None:
                raise MarketSimError("FEATURE_NEEDS_BENCHMARK", "spread requires benchmark_bars")
            b_closes = [b.close for b in benchmark_bars]
            val = spread(closes, b_closes)
            if val is None:
                return _insuff(key, params={}, as_of=as_of_ts, need=1, have=0)
            return _measured(key, val, params={}, bars=bars, as_of=as_of_ts)

        if key == "relative_strength":
            if benchmark_bars is None:
                raise MarketSimError("FEATURE_NEEDS_BENCHMARK", "relative_strength requires benchmark_bars")
            need = p + 1
            b_closes = [b.close for b in benchmark_bars]
            if len(closes) < need or len(b_closes) < need:
                return _insuff(key, params={"period": p}, as_of=as_of_ts, need=need, have=min(len(closes), len(b_closes)))
            val = relative_strength(closes, b_closes, p)
            assert val is not None
            return _measured(key, val, params={"period": p}, bars=bars, as_of=as_of_ts)

        if key in {"market_breadth"}:
            return FeatureValue(
                name=key,
                value=None,
                status=FeatureStatus.NOT_IMPLEMENTED.value,
                params={"reason": "requires_universe_data"},
                as_of=as_of_ts,
                provenance={"pipeline_version": FEATURE_PIPELINE_VERSION},
            )

        raise MarketSimError("UNKNOWN_FEATURE", f"Unsupported feature: {name}", http_status=400)

    def _default_period(self, key: str) -> int:
        defaults = {
            "sma": 20,
            "sma_close": 20,
            "ema": 20,
            "rsi": 14,
            "atr": 14,
            "adx": 14,
            "bollinger": 20,
            "bollinger_mid": 20,
            "bollinger_upper": 20,
            "bollinger_lower": 20,
            "bollinger_pct_b": 20,
            "zscore": 20,
            "rolling_zscore": 20,
            "roc": 10,
            "rate_of_change": 10,
            "return": 1,
            "rolling_return": 1,
            "realized_vol": 20,
            "realized_volatility": 20,
            "vol_percentile": 20,
            "volatility_percentile": 20,
            "rolling_high": 20,
            "rolling_low": 20,
            "donchian": 20,
            "donchian_high": 20,
            "donchian_mid": 20,
            "donchian_low": 20,
            "momentum": 10,
            "vwap": 20,
            "volume_avg": 20,
            "volume_average": 20,
            "volume_z": 20,
            "volume_zscore": 20,
            "breakout": 20,
            "breakout_state": 20,
            "trend_slope": 20,
            "slope": 20,
            "drawdown": 20,
            "correlation": 20,
            "corr": 20,
            "beta": 20,
            "relative_strength": 20,
        }
        return int(defaults.get(key, 20))

    def list_supported(self) -> list[str]:
        return sorted(
            {
                "sma",
                "ema",
                "rsi",
                "atr",
                "adx",
                "bollinger_mid",
                "bollinger_upper",
                "bollinger_lower",
                "bollinger_pct_b",
                "zscore",
                "roc",
                "return",
                "realized_vol",
                "vol_percentile",
                "rolling_high",
                "rolling_low",
                "donchian_high",
                "donchian_mid",
                "donchian_low",
                "momentum",
                "vwap",
                "volume_avg",
                "volume_z",
                "breakout",
                "trend_slope",
                "drawdown",
                "correlation",
                "beta",
                "spread",
                "relative_strength",
            }
        )


def assert_bars_causal(bars: Sequence[Bar], as_of: str) -> None:
    """Fail hard if any bar timestamp is after as_of."""
    from .epistemic import compare_ts

    for b in bars:
        if compare_ts(b.ts, as_of) > 0:
            raise CausalityViolation(f"Feature input bar {b.ts} is after as_of {as_of}")
