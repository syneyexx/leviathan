"""Canonical typed Trading Research perception pack.

Primary source is structured market truth (OHLCV / FeatureEngine / regimes) —
NOT chart imagery. Every value carries provenance + measurement state.
Never fabricate numbers; never expose future bars past ``as_of``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .epistemic import compare_ts
from .features import FEATURE_PIPELINE_VERSION, FeatureEngine, FeatureStatus, FeatureValue
from .types import Bar, CausalityViolation, MarketSimError, MetricStatus


RESEARCH_PERCEPTION_VERSION = "research_perception-1"


class MeasurementStatus(str, Enum):
    MEASURED = "MEASURED"
    UNMEASURED = "UNMEASURED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class MeasuredValue:
    """Typed measured/unmeasured/invalid scalar or structured value."""

    value: Any = None
    status: str = MeasurementStatus.UNMEASURED.value
    provenance: dict[str, Any] = field(default_factory=dict)
    version: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status,
            "provenance": dict(self.provenance),
            "version": self.version,
            "truth": {
                "unmeasured_is_not_zero": self.status == MeasurementStatus.UNMEASURED.value,
                "invalid_is_not_measured": self.status == MeasurementStatus.INVALID.value,
                "fabricated_numbers_forbidden": True,
            },
        }


def _unmeasured(
    *,
    reason: str,
    version: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> MeasuredValue:
    prov: dict[str, Any] = {"reason": reason, "source": "research_perception"}
    if extra:
        prov.update(dict(extra))
    return MeasuredValue(
        value=None,
        status=MeasurementStatus.UNMEASURED.value,
        provenance=prov,
        version=version,
    )


def _invalid(
    *,
    reason: str,
    version: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> MeasuredValue:
    prov: dict[str, Any] = {"reason": reason, "source": "research_perception"}
    if extra:
        prov.update(dict(extra))
    return MeasuredValue(
        value=None,
        status=MeasurementStatus.INVALID.value,
        provenance=prov,
        version=version,
    )


def _measured(
    value: Any,
    *,
    provenance: Mapping[str, Any] | None = None,
    version: str | None = None,
) -> MeasuredValue:
    return MeasuredValue(
        value=value,
        status=MeasurementStatus.MEASURED.value,
        provenance=dict(provenance or {}),
        version=version,
    )


def _from_feature(fv: FeatureValue | None, *, version: str | None = None) -> MeasuredValue:
    """Map FeatureEngine FeatureValue → MeasuredValue (never invent)."""
    if fv is None:
        return _unmeasured(reason="feature_missing", version=version)
    status = str(fv.status or "")
    prov = dict(fv.provenance or {})
    prov.setdefault("feature_name", fv.name)
    prov.setdefault("params", dict(fv.params or {}))
    prov.setdefault("as_of", fv.as_of)
    prov.setdefault("lookback_used", fv.lookback_used)
    if status == FeatureStatus.MEASURED.value or status == MetricStatus.MEASURED.value:
        return MeasuredValue(
            value=fv.value,
            status=MeasurementStatus.MEASURED.value,
            provenance=prov,
            version=version or FEATURE_PIPELINE_VERSION,
        )
    if status in {
        FeatureStatus.INSUFFICIENT_HISTORY.value,
        FeatureStatus.UNMEASURED.value,
        MetricStatus.UNMEASURED.value,
        FeatureStatus.NOT_IMPLEMENTED.value,
    }:
        return MeasuredValue(
            value=None,
            status=MeasurementStatus.UNMEASURED.value,
            provenance={**prov, "feature_status": status},
            version=version or FEATURE_PIPELINE_VERSION,
        )
    return MeasuredValue(
        value=None,
        status=MeasurementStatus.INVALID.value,
        provenance={**prov, "feature_status": status, "reason": "unexpected_feature_status"},
        version=version or FEATURE_PIPELINE_VERSION,
    )


def _coerce_bar(raw: Any) -> Bar | None:
    if isinstance(raw, Bar):
        return raw
    if not isinstance(raw, Mapping):
        return None
    ts = str(raw.get("ts") or raw.get("timestamp") or raw.get("time") or "").strip()
    if not ts:
        return None
    try:
        return Bar(
            ts=ts,
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=float(raw.get("volume") or 0.0),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _coerce_bars(raw_bars: Sequence[Any] | None) -> list[Bar]:
    out: list[Bar] = []
    for item in raw_bars or []:
        bar = _coerce_bar(item)
        if bar is not None:
            out.append(bar)
    return out


def _filter_causal(bars: Sequence[Bar], as_of: str) -> list[Bar]:
    """Keep bars with ts <= as_of; refuse any bar with ts > as_of in the input window."""
    visible: list[Bar] = []
    for bar in bars:
        cmp = compare_ts(bar.ts, as_of)
        if cmp > 0:
            raise CausalityViolation(
                f"Research perception refused future bar {bar.ts} (as_of={as_of})"
            )
        visible.append(bar)
    return visible


def _safe_compute(
    engine: FeatureEngine,
    bars: Sequence[Bar],
    name: str,
    *,
    as_of: str,
    period: int | None = None,
) -> MeasuredValue:
    if not bars:
        return _unmeasured(
            reason="empty_bars",
            version=FEATURE_PIPELINE_VERSION,
            extra={"feature": name},
        )
    try:
        fv = engine.compute(bars, name, as_of=as_of, period=period)
        return _from_feature(fv, version=FEATURE_PIPELINE_VERSION)
    except Exception as exc:  # noqa: BLE001 — features must never invent on failure
        return _unmeasured(
            reason=f"feature_engine_error:{type(exc).__name__}",
            version=FEATURE_PIPELINE_VERSION,
            extra={"feature": name, "detail": str(exc)[:240]},
        )


def _ohlcv_summary(bars: Sequence[Bar], *, as_of: str) -> MeasuredValue:
    if not bars:
        return _unmeasured(reason="empty_bars", version=RESEARCH_PERCEPTION_VERSION)
    cur = bars[-1]
    return _measured(
        {
            "open": cur.open,
            "high": cur.high,
            "low": cur.low,
            "close": cur.close,
            "volume": cur.volume,
            "bar_count": len(bars),
            "first_ts": bars[0].ts,
            "last_ts": cur.ts,
        },
        provenance={
            "source": "ohlcv_visible_window",
            "as_of": as_of,
            "last_ts": cur.ts,
        },
        version=RESEARCH_PERCEPTION_VERSION,
    )


def _volume_state(engine: FeatureEngine, bars: Sequence[Bar], as_of: str) -> MeasuredValue:
    if not bars:
        return _unmeasured(reason="empty_bars", version=FEATURE_PIPELINE_VERSION)
    avg = _safe_compute(engine, bars, "volume_avg", as_of=as_of, period=20)
    z = _safe_compute(engine, bars, "volume_z", as_of=as_of, period=20)
    last = bars[-1].volume
    payload: dict[str, Any] = {
        "last": last,
        "average": avg.public_dict(),
        "zscore": z.public_dict(),
    }
    if avg.status == MeasurementStatus.MEASURED.value and avg.value not in (None, 0):
        try:
            payload["relative_volume"] = float(last) / float(avg.value)
        except (TypeError, ValueError, ZeroDivisionError):
            payload["relative_volume"] = None
    else:
        payload["relative_volume"] = None
    if z.status == MeasurementStatus.MEASURED.value and z.value is not None:
        payload["spike"] = bool(float(z.value) >= 2.0)
        return _measured(
            payload,
            provenance={"source": "FeatureEngine.volume", "as_of": as_of},
            version=FEATURE_PIPELINE_VERSION,
        )
    # Partial measurement still honest — last volume is MEASURED from OHLCV.
    return _measured(
        payload,
        provenance={
            "source": "ohlcv_last_volume",
            "as_of": as_of,
            "note": "derived_volume_stats_may_be_unmeasured",
        },
        version=FEATURE_PIPELINE_VERSION,
    )


def _mas(engine: FeatureEngine, bars: Sequence[Bar], as_of: str) -> MeasuredValue:
    if not bars:
        return _unmeasured(reason="empty_bars", version=FEATURE_PIPELINE_VERSION)
    fast = _safe_compute(engine, bars, "sma", as_of=as_of, period=10)
    slow = _safe_compute(engine, bars, "sma", as_of=as_of, period=30)
    if (
        fast.status != MeasurementStatus.MEASURED.value
        and slow.status != MeasurementStatus.MEASURED.value
    ):
        return _unmeasured(
            reason="insufficient_history_for_mas",
            version=FEATURE_PIPELINE_VERSION,
            extra={"sma_10": fast.public_dict(), "sma_30": slow.public_dict()},
        )
    return _measured(
        {"sma_10": fast.public_dict(), "sma_30": slow.public_dict()},
        provenance={"source": "FeatureEngine.sma", "as_of": as_of},
        version=FEATURE_PIPELINE_VERSION,
    )


def _trend_pack(engine: FeatureEngine, bars: Sequence[Bar], as_of: str) -> MeasuredValue:
    if not bars:
        return _unmeasured(reason="empty_bars", version=FEATURE_PIPELINE_VERSION)
    fast = _safe_compute(engine, bars, "sma", as_of=as_of, period=10)
    slow = _safe_compute(engine, bars, "sma", as_of=as_of, period=30)
    slope = _safe_compute(engine, bars, "trend_slope", as_of=as_of, period=20)
    direction = "flat"
    if (
        fast.status == MeasurementStatus.MEASURED.value
        and slow.status == MeasurementStatus.MEASURED.value
        and fast.value is not None
        and slow.value is not None
    ):
        if float(fast.value) > float(slow.value) * 1.001:
            direction = "up"
        elif float(fast.value) < float(slow.value) * 0.999:
            direction = "down"
        return _measured(
            {
                "direction": direction,
                "sma_fast": fast.public_dict(),
                "sma_slow": slow.public_dict(),
                "slope": slope.public_dict(),
            },
            provenance={"source": "FeatureEngine.trend", "as_of": as_of},
            version=FEATURE_PIPELINE_VERSION,
        )
    if slope.status == MeasurementStatus.MEASURED.value and slope.value is not None:
        if float(slope.value) > 0:
            direction = "up"
        elif float(slope.value) < 0:
            direction = "down"
        return _measured(
            {
                "direction": direction,
                "sma_fast": fast.public_dict(),
                "sma_slow": slow.public_dict(),
                "slope": slope.public_dict(),
            },
            provenance={"source": "FeatureEngine.trend_slope_fallback", "as_of": as_of},
            version=FEATURE_PIPELINE_VERSION,
        )
    return _unmeasured(
        reason="insufficient_history_for_trend",
        version=FEATURE_PIPELINE_VERSION,
        extra={"sma_fast": fast.public_dict(), "sma_slow": slow.public_dict(), "slope": slope.public_dict()},
    )


def _regime_labels(bars: Sequence[Bar], as_of: str) -> MeasuredValue:
    if not bars:
        return _unmeasured(reason="empty_bars", version=None)
    try:
        from .regimes import (
            REGIME_DETECTOR_VERSION,
            detect_changepoints,
            detect_trend_regime,
            detect_volatility_regime,
            hmm_regime_capability,
        )
    except Exception as exc:  # noqa: BLE001
        return _unmeasured(
            reason=f"regimes_unavailable:{type(exc).__name__}",
            extra={"detail": str(exc)[:200]},
        )
    closes = [b.close for b in bars]
    timestamps = [b.ts for b in bars]
    vol = detect_volatility_regime(closes, ts=as_of)
    trend = detect_trend_regime(closes, ts=as_of)
    cps = detect_changepoints(closes, timestamps=timestamps)
    latest_cp = cps[-1].public_dict() if cps else None
    return _measured(
        {
            "volatility": vol.public_dict(),
            "trend": trend.public_dict(),
            "changepoint_latest": latest_cp,
            "changepoint_count": len(cps),
            "hmm": hmm_regime_capability(),
        },
        provenance={
            "source": "regimes",
            "detector_version": REGIME_DETECTOR_VERSION,
            "as_of": as_of,
        },
        version=REGIME_DETECTOR_VERSION,
    )


def _changepoint(bars: Sequence[Bar], as_of: str) -> MeasuredValue:
    if not bars:
        return _unmeasured(reason="empty_bars")
    try:
        from .regimes import REGIME_DETECTOR_VERSION, detect_changepoints
    except Exception as exc:  # noqa: BLE001
        return _unmeasured(reason=f"regimes_unavailable:{type(exc).__name__}")
    cps = detect_changepoints([b.close for b in bars], timestamps=[b.ts for b in bars])
    if not cps:
        return _unmeasured(
            reason="no_changepoint_detected",
            version=REGIME_DETECTOR_VERSION,
            extra={"as_of": as_of, "bar_count": len(bars)},
        )
    # Only report changepoints with ts <= as_of (already causal by construction).
    causal = [c for c in cps if compare_ts(c.ts, as_of) <= 0]
    if not causal:
        return _unmeasured(reason="no_causal_changepoint", version=REGIME_DETECTOR_VERSION)
    last = causal[-1]
    return _measured(
        last.public_dict(),
        provenance={"source": "regimes.detect_changepoints", "as_of": as_of},
        version=REGIME_DETECTOR_VERSION,
    )


def _session_calendar(*, as_of: str, symbol: str) -> MeasuredValue:
    """Session/calendar context — UNMEASURED unless venue calendar resolves."""
    try:
        from .exchange_calendars import EXCHANGE_VENUES
    except Exception as exc:  # noqa: BLE001
        return _unmeasured(reason=f"calendar_unavailable:{type(exc).__name__}")
    # Without an explicit venue we cannot honestly claim session state.
    return _unmeasured(
        reason="venue_not_specified",
        version="exchange_calendars-1",
        extra={
            "as_of": as_of,
            "symbol": symbol,
            "known_venues": sorted(EXCHANGE_VENUES.keys())[:12],
            "note": "session_state_requires_explicit_venue",
        },
    )


def _spread_l1() -> MeasuredValue:
    """L1 spread only when measured — OHLCV alone never fabricates spread."""
    return _unmeasured(
        reason="ohlcv_is_not_orderbook",
        version=FEATURE_PIPELINE_VERSION,
        extra={"truth": {"l1_requires_quotes": True}},
    )


def _wrap_cost_assumptions(raw: dict[str, Any] | None) -> MeasuredValue:
    if not raw:
        return _unmeasured(reason="no_cost_assumptions_provided", version="cost_pack-1")
    # Caller-supplied cost packs are recorded as present assumptions — not market MEASURED.
    return MeasuredValue(
        value=dict(raw),
        status=MeasurementStatus.MEASURED.value,
        provenance={
            "source": "caller_cost_assumptions",
            "assumption_status": MetricStatus.ASSUMED.value,
            "note": "assumed_is_not_market_measured",
        },
        version=str(raw.get("version") or "cost_pack-1"),
    )


def _wrap_optional_dict(
    raw: dict[str, Any] | None,
    *,
    empty_reason: str,
    version: str | None = None,
) -> MeasuredValue:
    if not raw:
        return _unmeasured(reason=empty_reason, version=version)
    return _measured(
        dict(raw),
        provenance={"source": "caller"},
        version=version,
    )


def _wrap_list(
    raw: list[Any] | None,
    *,
    empty_reason: str,
) -> MeasuredValue:
    if not raw:
        return _unmeasured(reason=empty_reason)
    return _measured(
        list(raw),
        provenance={"source": "caller", "count": len(raw)},
    )


def _try_market_state(
    market_view: Any,
    *,
    engine: FeatureEngine,
    portfolio_context: dict[str, Any] | None,
) -> MeasuredValue:
    if market_view is None:
        return _unmeasured(reason="no_market_view")
    try:
        from .market_state import build_market_state
    except Exception as exc:  # noqa: BLE001
        return _unmeasured(reason=f"market_state_unavailable:{type(exc).__name__}")
    try:
        state = build_market_state(
            market_view,
            portfolio=portfolio_context,
            engine=engine,
        )
        return _measured(
            state.public_dict(),
            provenance=dict(state.provenance or {}),
            version=FEATURE_PIPELINE_VERSION,
        )
    except Exception as exc:  # noqa: BLE001
        return _unmeasured(
            reason=f"build_market_state_failed:{type(exc).__name__}",
            version=FEATURE_PIPELINE_VERSION,
            extra={"detail": str(exc)[:240]},
        )


@dataclass
class ResearchPerceptionSnapshot:
    """Point-in-time Trading Research perception — numeric truth primary."""

    symbol: str
    timeframe: str
    as_of: str
    dataset_id: MeasuredValue
    dataset_version: MeasuredValue
    dataset_hash: MeasuredValue
    source_id: MeasuredValue
    split_role: MeasuredValue
    visible_bar_range: MeasuredValue
    ohlcv_summary: MeasuredValue
    returns: MeasuredValue
    momentum: MeasuredValue
    trend: MeasuredValue
    realized_vol: MeasuredValue
    volume_state: MeasuredValue
    rsi: MeasuredValue
    mas: MeasuredValue
    adx: MeasuredValue
    atr: MeasuredValue
    relative_strength: MeasuredValue
    correlation: MeasuredValue
    changepoint: MeasuredValue
    regime_labels: MeasuredValue
    session_calendar: MeasuredValue
    spread_l1: MeasuredValue
    transaction_cost_assumptions: MeasuredValue
    data_health: MeasuredValue
    portfolio_context: MeasuredValue
    prior_evidence_refs: MeasuredValue
    prior_negative_experience: MeasuredValue
    hypothesis_ref: MeasuredValue
    market_state: MeasuredValue = field(
        default_factory=lambda: _unmeasured(reason="not_computed")
    )
    feature_pipeline_version: str = FEATURE_PIPELINE_VERSION
    perception_version: str = RESEARCH_PERCEPTION_VERSION
    provenance: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "as_of": self.as_of,
            "dataset_id": self.dataset_id.public_dict(),
            "dataset_version": self.dataset_version.public_dict(),
            "dataset_hash": self.dataset_hash.public_dict(),
            "source_id": self.source_id.public_dict(),
            "split_role": self.split_role.public_dict(),
            "visible_bar_range": self.visible_bar_range.public_dict(),
            "ohlcv_summary": self.ohlcv_summary.public_dict(),
            "returns": self.returns.public_dict(),
            "momentum": self.momentum.public_dict(),
            "trend": self.trend.public_dict(),
            "realized_vol": self.realized_vol.public_dict(),
            "volume_state": self.volume_state.public_dict(),
            "rsi": self.rsi.public_dict(),
            "mas": self.mas.public_dict(),
            "adx": self.adx.public_dict(),
            "atr": self.atr.public_dict(),
            "relative_strength": self.relative_strength.public_dict(),
            "correlation": self.correlation.public_dict(),
            "changepoint": self.changepoint.public_dict(),
            "regime_labels": self.regime_labels.public_dict(),
            "session_calendar": self.session_calendar.public_dict(),
            "spread_l1": self.spread_l1.public_dict(),
            "transaction_cost_assumptions": self.transaction_cost_assumptions.public_dict(),
            "data_health": self.data_health.public_dict(),
            "portfolio_context": self.portfolio_context.public_dict(),
            "prior_evidence_refs": self.prior_evidence_refs.public_dict(),
            "prior_negative_experience": self.prior_negative_experience.public_dict(),
            "hypothesis_ref": self.hypothesis_ref.public_dict(),
            "market_state": self.market_state.public_dict(),
            "feature_pipeline_version": self.feature_pipeline_version,
            "perception_version": self.perception_version,
            "provenance": dict(self.provenance),
            "truth": {
                "no_future_bars": True,
                "numeric_primary": True,
                "chart_advisory_only": True,
                "fabricated_features_forbidden": True,
                "spread_l1_only_when_measured": True,
            },
        }


def build_research_perception(
    *,
    bars: list[dict] | None = None,
    market_view: Any = None,
    as_of: str,
    symbol: str = "",
    timeframe: str = "",
    dataset_id: str | None = None,
    dataset_version: str | None = None,
    dataset_hash: str | None = None,
    source_id: str | None = None,
    split_role: str | None = None,
    cost_assumptions: dict | None = None,
    data_health: dict | None = None,
    portfolio_context: dict | None = None,
    prior_evidence_refs: list[str] | None = None,
    prior_negative_experience: list[dict] | None = None,
    hypothesis_ref: str | None = None,
    feature_engine: Any = None,
) -> ResearchPerceptionSnapshot:
    """Build a causal research perception snapshot from structured market truth."""
    if not as_of or not str(as_of).strip():
        raise MarketSimError("INVALID_AS_OF", "as_of is required for research perception")

    as_of_s = str(as_of).strip()
    sym = symbol or (getattr(market_view, "instrument", None) or "")
    tf = timeframe or (getattr(market_view, "timeframe", None) or "")

    # Resolve visible bars — prefer MarketView (already causal), else caller bars.
    resolved: list[Bar] = []
    if market_view is not None:
        try:
            # Align clock if caller supplied as_of matching a bar.
            if hasattr(market_view, "visible_bars"):
                view_as_of = getattr(market_view, "as_of", None)
                if view_as_of is not None and compare_ts(view_as_of, as_of_s) > 0:
                    raise CausalityViolation(
                        f"MarketView as_of {view_as_of} ahead of perception as_of {as_of_s}"
                    )
                resolved = list(market_view.visible_bars())
            elif hasattr(market_view, "history") and hasattr(market_view, "index"):
                idx = int(market_view.index)
                if idx >= 0:
                    resolved = list(market_view.history(idx + 1))
        except CausalityViolation:
            raise
        except Exception:  # noqa: BLE001
            resolved = []

    if not resolved and bars is not None:
        resolved = _coerce_bars(bars)

    # Enforce causality on whatever we resolved.
    visible = _filter_causal(resolved, as_of_s) if resolved else []
    # Also drop any bar that somehow equals future after string edge cases — already filtered.
    visible = [b for b in visible if compare_ts(b.ts, as_of_s) <= 0]

    engine = feature_engine if feature_engine is not None else FeatureEngine()

    if visible:
        first_ts, last_ts = visible[0].ts, visible[-1].ts
        bar_range = _measured(
            {"start_ts": first_ts, "end_ts": last_ts, "bar_count": len(visible)},
            provenance={"source": "visible_ohlcv", "as_of": as_of_s},
            version=RESEARCH_PERCEPTION_VERSION,
        )
        ohlcv = _ohlcv_summary(visible, as_of=as_of_s)
        returns = _safe_compute(engine, visible, "return", as_of=as_of_s, period=1)
        momentum = _safe_compute(engine, visible, "momentum", as_of=as_of_s, period=10)
        trend = _trend_pack(engine, visible, as_of_s)
        realized_vol = _safe_compute(engine, visible, "realized_vol", as_of=as_of_s, period=20)
        volume_state = _volume_state(engine, visible, as_of_s)
        rsi = _safe_compute(engine, visible, "rsi", as_of=as_of_s, period=14)
        mas = _mas(engine, visible, as_of_s)
        adx = _safe_compute(engine, visible, "adx", as_of=as_of_s, period=14)
        atr = _safe_compute(engine, visible, "atr", as_of=as_of_s, period=14)
        # Relative strength / correlation require benchmark — remain UNMEASURED without one.
        relative_strength = _unmeasured(
            reason="benchmark_bars_required",
            version=FEATURE_PIPELINE_VERSION,
        )
        correlation = _unmeasured(
            reason="benchmark_bars_required",
            version=FEATURE_PIPELINE_VERSION,
        )
        changepoint = _changepoint(visible, as_of_s)
        regime_labels = _regime_labels(visible, as_of_s)
    else:
        empty = _unmeasured(reason="empty_bars", version=FEATURE_PIPELINE_VERSION)
        bar_range = empty
        ohlcv = empty
        returns = empty
        momentum = empty
        trend = empty
        realized_vol = empty
        volume_state = empty
        rsi = empty
        mas = empty
        adx = empty
        atr = empty
        relative_strength = empty
        correlation = empty
        changepoint = empty
        regime_labels = empty

    def _id_field(val: str | None, reason: str) -> MeasuredValue:
        if val is None or str(val).strip() == "":
            return _unmeasured(reason=reason)
        return _measured(str(val), provenance={"source": "caller"})

    snapshot = ResearchPerceptionSnapshot(
        symbol=str(sym or ""),
        timeframe=str(tf or ""),
        as_of=as_of_s,
        dataset_id=_id_field(dataset_id, "dataset_id_not_provided"),
        dataset_version=_id_field(dataset_version, "dataset_version_not_provided"),
        dataset_hash=_id_field(dataset_hash, "dataset_hash_not_provided"),
        source_id=_id_field(source_id, "source_id_not_provided"),
        split_role=_id_field(split_role, "split_role_not_provided"),
        visible_bar_range=bar_range,
        ohlcv_summary=ohlcv,
        returns=returns,
        momentum=momentum,
        trend=trend,
        realized_vol=realized_vol,
        volume_state=volume_state,
        rsi=rsi,
        mas=mas,
        adx=adx,
        atr=atr,
        relative_strength=relative_strength,
        correlation=correlation,
        changepoint=changepoint,
        regime_labels=regime_labels,
        session_calendar=_session_calendar(as_of=as_of_s, symbol=str(sym or "")),
        spread_l1=_spread_l1(),
        transaction_cost_assumptions=_wrap_cost_assumptions(cost_assumptions),
        data_health=_wrap_optional_dict(data_health, empty_reason="data_health_not_provided"),
        portfolio_context=_wrap_optional_dict(
            portfolio_context, empty_reason="portfolio_context_not_provided"
        ),
        prior_evidence_refs=_wrap_list(
            prior_evidence_refs, empty_reason="no_prior_evidence_refs"
        ),
        prior_negative_experience=_wrap_list(
            prior_negative_experience, empty_reason="no_prior_negative_experience"
        ),
        hypothesis_ref=_id_field(hypothesis_ref, "hypothesis_ref_not_provided"),
        market_state=_try_market_state(
            market_view, engine=engine, portfolio_context=portfolio_context
        ),
        feature_pipeline_version=FEATURE_PIPELINE_VERSION,
        perception_version=RESEARCH_PERCEPTION_VERSION,
        provenance={
            "as_of": as_of_s,
            "visible_bar_count": len(visible),
            "feature_pipeline_version": FEATURE_PIPELINE_VERSION,
            "perception_version": RESEARCH_PERCEPTION_VERSION,
            "source": "MarketView" if market_view is not None else "bars",
            "deterministic": True,
            "chart_advisory_only": True,
        },
    )
    assert_causal_perception(snapshot, as_of_s)
    return snapshot


def _iter_measured_values(obj: Any) -> list[MeasuredValue]:
    out: list[MeasuredValue] = []
    if isinstance(obj, MeasuredValue):
        out.append(obj)
        return out
    if isinstance(obj, ResearchPerceptionSnapshot):
        for name in obj.__dataclass_fields__:  # type: ignore[attr-defined]
            out.extend(_iter_measured_values(getattr(obj, name)))
        return out
    if isinstance(obj, Mapping):
        for v in obj.values():
            out.extend(_iter_measured_values(v))
        return out
    if isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_iter_measured_values(v))
    return out


def _timestamps_in_value(value: Any) -> list[str]:
    found: list[str] = []
    if value is None:
        return found
    if isinstance(value, str):
        # Heuristic: ISO-like timestamps only
        if "T" in value and len(value) >= 10 and value[0:4].isdigit():
            found.append(value)
        return found
    if isinstance(value, Mapping):
        for key, val in value.items():
            key_l = str(key).lower()
            if key_l in {
                "ts",
                "timestamp",
                "as_of",
                "start_ts",
                "end_ts",
                "first_ts",
                "last_ts",
                "visible_timestamp",
            } and val:
                found.append(str(val))
            else:
                found.extend(_timestamps_in_value(val))
        return found
    if isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_timestamps_in_value(item))
    return found


def assert_causal_perception(snapshot: ResearchPerceptionSnapshot | Mapping[str, Any], as_of: str) -> None:
    """Raise CausalityViolation if any visible bar / feature uses timestamp > as_of."""
    as_of_s = str(as_of).strip()
    if not as_of_s:
        raise MarketSimError("INVALID_AS_OF", "as_of required for assert_causal_perception")

    payloads: list[Any] = []
    if isinstance(snapshot, ResearchPerceptionSnapshot):
        if compare_ts(snapshot.as_of, as_of_s) > 0:
            raise CausalityViolation(
                f"Snapshot as_of {snapshot.as_of} exceeds assert as_of {as_of_s}"
            )
        for mv in _iter_measured_values(snapshot):
            payloads.append(mv.value)
            if mv.provenance:
                payloads.append(mv.provenance)
        payloads.append(snapshot.provenance)
    elif isinstance(snapshot, Mapping):
        snap_as_of = snapshot.get("as_of")
        if snap_as_of and compare_ts(str(snap_as_of), as_of_s) > 0:
            raise CausalityViolation(
                f"Snapshot as_of {snap_as_of} exceeds assert as_of {as_of_s}"
            )
        payloads.append(snapshot)
    else:
        raise MarketSimError("INVALID_SNAPSHOT", "Unsupported snapshot type for causal assert")

    for payload in payloads:
        for ts in _timestamps_in_value(payload):
            try:
                if compare_ts(ts, as_of_s) > 0:
                    raise CausalityViolation(
                        f"Perception feature/bar timestamp {ts} exceeds as_of {as_of_s}"
                    )
            except MarketSimError as exc:
                # Non-parseable stamps are not future leaks; skip unless clearly ISO.
                if exc.code == "INVALID_TIMESTAMP":
                    continue
                raise
