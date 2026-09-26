"""Canonical MarketState — deterministic, evidence-backed market snapshot.

Separates MEASURED feature facts from any later model/neuro hypothesis layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .causality import MarketView, SimulationClock
from .epistemic import compare_ts
from .features import FEATURE_PIPELINE_VERSION, FeatureEngine, FeatureValue
from .types import Bar, CausalityViolation, MarketSimError


TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1D": 86400,
    "1d": 86400,
}


@dataclass
class MarketState:
    """Point-in-time market understanding for one instrument/timeframe."""

    instrument: str
    venue: str
    asset_class: str
    timeframe: str
    as_of: str

    price: dict[str, Any] = field(default_factory=dict)
    trend: dict[str, Any] = field(default_factory=dict)
    momentum: dict[str, Any] = field(default_factory=dict)
    volatility: dict[str, Any] = field(default_factory=dict)
    volume: dict[str, Any] = field(default_factory=dict)
    structure: dict[str, Any] = field(default_factory=dict)
    relative: dict[str, Any] = field(default_factory=dict)
    events: dict[str, Any] = field(default_factory=dict)
    regime: dict[str, Any] = field(default_factory=dict)
    portfolio: dict[str, Any] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "identity": {
                "instrument": self.instrument,
                "venue": self.venue,
                "asset_class": self.asset_class,
                "timeframe": self.timeframe,
                "as_of": self.as_of,
            },
            "price": self.price,
            "trend": self.trend,
            "momentum": self.momentum,
            "volatility": self.volatility,
            "volume": self.volume,
            "structure": self.structure,
            "relative": self.relative,
            "events": self.events,
            "regime": self.regime,
            "portfolio": self.portfolio,
            "features": self.features,
            "provenance": self.provenance,
            "truth": {
                "deterministic_features_are_facts": True,
                "neural_interpretation_is_hypothesis": True,
                "ohlcv_is_not_orderbook": True,
                "feature_pipeline_version": FEATURE_PIPELINE_VERSION,
            },
        }

    def summary_features(self) -> dict[str, Any]:
        """Compact dict compatible with StrategyMemory / regime matching."""
        return {
            "regime": self.regime.get("label", "unknown"),
            "trend": self.trend.get("direction", "flat"),
            "volatility": self.volatility.get("label", "low"),
            "return_pct": self.price.get("return_pct"),
            "vol_pct": self.volatility.get("realized_vol_pct"),
            "breakout": self.structure.get("breakout"),
            "rsi": (self.momentum.get("rsi") or {}).get("value"),
            "as_of": self.as_of,
            "timeframe": self.timeframe,
        }


def build_market_state(
    view: MarketView,
    *,
    venue: str = "",
    asset_class: str = "",
    portfolio: Mapping[str, Any] | None = None,
    events: Mapping[str, Any] | None = None,
    benchmark_view: MarketView | None = None,
    lookback: int = 120,
    engine: FeatureEngine | None = None,
) -> MarketState:
    """Build MarketState from a causal MarketView (never future bars)."""
    if view.index < 0 or view.as_of is None:
        raise CausalityViolation("Cannot build MarketState before clock starts")
    as_of = view.as_of
    bars = view.history(min(lookback, view.index + 1))
    if not bars:
        raise CausalityViolation("No visible bars for MarketState")
    engine = engine or FeatureEngine()
    cur = bars[-1]

    # --- price ---
    ret_1 = engine.compute(bars, "return", as_of=as_of, period=1)
    ret_n = engine.compute(bars, "return", as_of=as_of, period=min(20, max(1, len(bars) - 1)))
    gap = None
    if len(bars) >= 2 and bars[-2].close > 0:
        gap = (cur.open - bars[-2].close) / bars[-2].close
    price = {
        "open": cur.open,
        "high": cur.high,
        "low": cur.low,
        "close": cur.close,
        "range": cur.high - cur.low,
        "gap": gap,
        "return_1": ret_1.public_dict(),
        "return_pct": (ret_n.value * 100.0) if ret_n.value is not None else None,
        "return_window": ret_n.public_dict(),
    }

    # --- trend ---
    sma_fast = engine.compute(bars, "sma", as_of=as_of, period=10)
    sma_slow = engine.compute(bars, "sma", as_of=as_of, period=30)
    slope = engine.compute(bars, "trend_slope", as_of=as_of, period=20)
    adx_v = engine.compute(bars, "adx", as_of=as_of, period=14)
    direction = "flat"
    if sma_fast.value is not None and sma_slow.value is not None:
        if sma_fast.value > sma_slow.value * 1.001:
            direction = "up"
        elif sma_fast.value < sma_slow.value * 0.999:
            direction = "down"
    strength = abs(slope.value) if slope.value is not None else None
    trend = {
        "direction": direction,
        "strength": strength,
        "sma_fast": sma_fast.public_dict(),
        "sma_slow": sma_slow.public_dict(),
        "slope": slope.public_dict(),
        "adx": adx_v.public_dict(),
        "ma_relationship": (
            "bullish"
            if direction == "up"
            else ("bearish" if direction == "down" else "neutral")
        ),
    }

    # --- momentum ---
    rsi_v = engine.compute(bars, "rsi", as_of=as_of, period=14)
    mom = engine.compute(bars, "momentum", as_of=as_of, period=10)
    roc = engine.compute(bars, "roc", as_of=as_of, period=10)
    momentum = {
        "rsi": rsi_v.public_dict(),
        "momentum": mom.public_dict(),
        "roc": roc.public_dict(),
    }

    # --- volatility ---
    atr_v = engine.compute(bars, "atr", as_of=as_of, period=14)
    rvol = engine.compute(bars, "realized_vol", as_of=as_of, period=20)
    vol_pctile = engine.compute(bars, "vol_percentile", as_of=as_of, period=20, lookback=min(100, max(20, len(bars) - 21)))
    bb_u = engine.compute(bars, "bollinger_upper", as_of=as_of, period=20)
    bb_l = engine.compute(bars, "bollinger_lower", as_of=as_of, period=20)
    realized_pct = (rvol.value * 100.0) if rvol.value is not None else None
    vol_label = "low"
    if realized_pct is not None:
        if realized_pct > 3:
            vol_label = "high"
        elif realized_pct > 1:
            vol_label = "medium"
    volatility = {
        "atr": atr_v.public_dict(),
        "realized_vol": rvol.public_dict(),
        "realized_vol_pct": realized_pct,
        "percentile": vol_pctile.public_dict(),
        "bollinger_upper": bb_u.public_dict(),
        "bollinger_lower": bb_l.public_dict(),
        "label": vol_label,
        "regime": vol_label,
    }

    # --- volume ---
    vavg = engine.compute(bars, "volume_avg", as_of=as_of, period=20)
    vz = engine.compute(bars, "volume_z", as_of=as_of, period=20)
    vwap_v = engine.compute(bars, "vwap", as_of=as_of, period=min(20, len(bars)))
    rel_vol = None
    if vavg.value and vavg.value > 0:
        rel_vol = cur.volume / vavg.value
    volume = {
        "last": cur.volume,
        "average": vavg.public_dict(),
        "zscore": vz.public_dict(),
        "relative_volume": rel_vol,
        "vwap": vwap_v.public_dict(),
        "spike": bool(vz.value is not None and vz.value >= 2.0),
    }

    # --- structure ---
    rh = engine.compute(bars, "rolling_high", as_of=as_of, period=20)
    rl = engine.compute(bars, "rolling_low", as_of=as_of, period=20)
    brk = engine.compute(bars, "breakout", as_of=as_of, period=20)
    dd = engine.compute(bars, "drawdown", as_of=as_of, period=min(60, len(bars)))
    structure = {
        "swing_high": rh.public_dict(),
        "swing_low": rl.public_dict(),
        "support": rl.value,
        "resistance": rh.value,
        "breakout": brk.value,
        "breakout_detail": brk.public_dict(),
        "drawdown": dd.public_dict(),
        "channel_mid": ((rh.value + rl.value) / 2.0) if rh.value is not None and rl.value is not None else None,
    }

    # --- relative ---
    relative: dict[str, Any] = {"available": False}
    if benchmark_view is not None and benchmark_view.as_of is not None:
        # Align benchmark to same as_of causally
        if compare_ts(benchmark_view.as_of, as_of) > 0:
            raise CausalityViolation("Benchmark MarketView is ahead of primary as_of")
        b_bars = benchmark_view.history(min(lookback, benchmark_view.index + 1))
        # Truncate both to common length from the end
        n = min(len(bars), len(b_bars))
        if n >= 5:
            a = bars[-n:]
            b = b_bars[-n:]
            corr = engine.compute(a, "correlation", as_of=as_of, period=min(20, n), benchmark_bars=b)
            beta = engine.compute(a, "beta", as_of=as_of, period=min(20, max(2, n - 1)), benchmark_bars=b)
            rs = engine.compute(a, "relative_strength", as_of=as_of, period=min(20, n - 1), benchmark_bars=b)
            sp = engine.compute(a, "spread", as_of=as_of, benchmark_bars=b)
            relative = {
                "available": True,
                "benchmark_instrument": benchmark_view.instrument,
                "correlation": corr.public_dict(),
                "beta": beta.public_dict(),
                "relative_strength": rs.public_dict(),
                "spread": sp.public_dict(),
            }

    # --- regime (deterministic labels only) ---
    regime_label = f"{direction}_{vol_label}"
    uncertainty = 0.5
    if adx_v.value is not None:
        # Higher ADX → more confident trend regime
        uncertainty = max(0.1, min(0.9, 1.0 - (adx_v.value / 100.0)))
    regime = {
        "label": regime_label,
        "trend": direction,
        "volatility": vol_label,
        "uncertainty": uncertainty,
        "deterministic": True,
        "note": "label is feature-derived; not a neural classification",
    }

    feature_pack = {
        "sma_10": sma_fast.public_dict(),
        "sma_30": sma_slow.public_dict(),
        "rsi_14": rsi_v.public_dict(),
        "atr_14": atr_v.public_dict(),
        "adx_14": adx_v.public_dict(),
        "realized_vol_20": rvol.public_dict(),
        "breakout_20": brk.public_dict(),
        "trend_slope_20": slope.public_dict(),
    }

    state = MarketState(
        instrument=view.instrument or "",
        venue=venue,
        asset_class=asset_class,
        timeframe=view.timeframe or "",
        as_of=as_of,
        price=price,
        trend=trend,
        momentum=momentum,
        volatility=volatility,
        volume=volume,
        structure=structure,
        relative=relative,
        events=dict(events or {"available": False}),
        regime=regime,
        portfolio=dict(portfolio or {}),
        features=feature_pack,
        provenance={
            "feature_pipeline_version": FEATURE_PIPELINE_VERSION,
            "visible_bar_count": len(bars),
            "lookback_requested": lookback,
            "source": "MarketView",
            "first_ts": bars[0].ts,
            "last_ts": bars[-1].ts,
            "deterministic": True,
            "neural_interpretation_excluded": True,
        },
    )
    return state


@dataclass
class MultiTimeframeView:
    """Causal multi-timeframe observation bound to a shared as_of.

    Higher timeframes may be supplied as separate views or synthesized by
    aggregating a base view's visible bars. Future bars are never accessible.
    """

    base: MarketView
    frames: dict[str, MarketView] = field(default_factory=dict)
    engine: FeatureEngine = field(default_factory=FeatureEngine)

    @property
    def as_of(self) -> str | None:
        return self.base.as_of

    def timeframe(self, tf: str) -> MarketView:
        key = tf.strip()
        if key == self.base.timeframe or key == "base":
            return self.base
        if key not in self.frames:
            raise MarketSimError("TIMEFRAME_UNAVAILABLE", f"No causal view for timeframe {key}", http_status=404)
        view = self.frames[key]
        if self.as_of and view.as_of and compare_ts(view.as_of, self.as_of) > 0:
            raise CausalityViolation(
                f"Timeframe {key} as_of {view.as_of} ahead of base as_of {self.as_of}"
            )
        return view

    def feature(self, name: str, *, timeframe: str | None = None, period: int | None = None) -> FeatureValue:
        view = self.timeframe(timeframe) if timeframe else self.base
        if view.as_of is None:
            raise CausalityViolation("No feature before clock starts")
        bars = view.visible_bars()
        return self.engine.compute(bars, name, as_of=view.as_of, period=period)

    def states(
        self,
        *,
        portfolio: Mapping[str, Any] | None = None,
        lookback: int = 120,
    ) -> dict[str, MarketState]:
        out: dict[str, MarketState] = {
            self.base.timeframe or "base": build_market_state(
                self.base, portfolio=portfolio, lookback=lookback, engine=self.engine
            )
        }
        for tf, view in self.frames.items():
            out[tf] = build_market_state(view, portfolio=portfolio, lookback=lookback, engine=self.engine)
        return out

    def public_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "base": self.base.public_dict(),
            "timeframes": {k: v.public_dict() for k, v in self.frames.items()},
            "truth": {"shared_as_of": True, "no_future_frames": True},
        }

    def multi_horizon_pack(
        self,
        *,
        portfolio: Mapping[str, Any] | None = None,
        lookback: int = 120,
        feature_names: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """W14 — aligned multi-horizon state pack with incomplete higher-TF honesty."""
        return build_multi_horizon_state(
            self,
            portfolio=portfolio,
            lookback=lookback,
            feature_names=feature_names,
        )


def build_multi_horizon_state(
    view: MultiTimeframeView,
    *,
    portfolio: Mapping[str, Any] | None = None,
    lookback: int = 120,
    feature_names: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Shared as_of multi-TF pack: per-frame states + cross-TF feature alignment."""
    names = list(feature_names or ("return", "realized_volatility"))
    states = view.states(portfolio=portfolio, lookback=lookback)
    aligned: dict[str, dict[str, Any]] = {}
    incomplete: list[str] = []
    for tf, state in states.items():
        row: dict[str, Any] = {}
        for name in names:
            feat = state.features.get(name) if isinstance(state.features, dict) else None
            if feat is None:
                try:
                    fv = view.feature(name, timeframe=None if tf in {view.base.timeframe, "base"} else tf)
                    row[name] = fv.public_dict() if hasattr(fv, "public_dict") else {"value": fv.value, "status": fv.status}
                except Exception:  # noqa: BLE001 — honest gap
                    row[name] = {"status": "UNMEASURED", "reason": "feature_unavailable"}
            else:
                row[name] = feat
        aligned[tf] = row
        bar_count = int((state.provenance or {}).get("bar_count") or 0)
        if tf != (view.base.timeframe or "base") and bar_count and bar_count < max(3, lookback // 8):
            incomplete.append(tf)
    agreement: dict[str, Any] = {"status": "UNMEASURED", "pairs": []}
    base_key = view.base.timeframe or "base"
    base_ret = aligned.get(base_key, {}).get("return")
    if isinstance(base_ret, dict) and base_ret.get("value") is not None:
        pairs = []
        for tf, row in aligned.items():
            if tf == base_key:
                continue
            other = row.get("return")
            if isinstance(other, dict) and other.get("value") is not None:
                same = (float(base_ret["value"]) >= 0) == (float(other["value"]) >= 0)
                pairs.append({"base": base_key, "other": tf, "sameSign": same})
        if pairs:
            agreement = {
                "status": "MEASURED",
                "pairs": pairs,
                "allAgree": all(p["sameSign"] for p in pairs),
            }
    return {
        "asOf": view.as_of,
        "states": {k: v.public_dict() for k, v in states.items()},
        "alignedFeatures": aligned,
        "incompleteHigherTf": incomplete,
        "crossTfAgreement": agreement,
        "truth": {
            "shared_as_of": True,
            "incomplete_higher_tf_labelled": True,
            "ohlcv_is_not_orderbook": True,
        },
    }


def aggregate_bars(bars: Sequence[Bar], *, target_seconds: int) -> list[Bar]:
    """Aggregate finer bars into coarser OHLCV buckets (causal, left-closed)."""
    if target_seconds < 1:
        raise ValueError("target_seconds must be >= 1")
    if not bars:
        return []
    from datetime import datetime, timezone

    def _epoch(ts: str) -> int:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())

    buckets: dict[int, list[Bar]] = {}
    order: list[int] = []
    for bar in bars:
        key = (_epoch(bar.ts) // target_seconds) * target_seconds
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(bar)

    out: list[Bar] = []
    for key in order:
        group = buckets[key]
        out.append(
            Bar(
                ts=group[-1].ts,  # bar completes at last constituent's ts (causal)
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=group[-1].close,
                volume=sum(b.volume for b in group),
            )
        )
    return out


def synthesize_higher_timeframe(
    base: MarketView,
    *,
    target_timeframe: str,
    instrument: str | None = None,
) -> MarketView:
    """Build a causal higher-TF MarketView from visible base bars only."""
    if base.as_of is None or base.index < 0:
        raise CausalityViolation("Cannot synthesize timeframe before clock starts")
    target_sec = TIMEFRAME_SECONDS.get(target_timeframe)
    base_sec = TIMEFRAME_SECONDS.get(base.timeframe or "", 0)
    if target_sec is None:
        raise MarketSimError("UNKNOWN_TIMEFRAME", target_timeframe, http_status=400)
    if base_sec and target_sec <= base_sec:
        raise MarketSimError(
            "INVALID_AGGREGATION",
            f"Cannot aggregate {base.timeframe} up to equal/lower {target_timeframe}",
            http_status=400,
        )
    visible = base.visible_bars()
    agg = aggregate_bars(visible, target_seconds=target_sec)
    if not agg:
        raise CausalityViolation("No aggregated bars available yet")
    clock = SimulationClock(bars=agg, index=len(agg) - 1)
    return MarketView(
        clock=clock,
        instrument=instrument or base.instrument,
        timeframe=target_timeframe,
    )
