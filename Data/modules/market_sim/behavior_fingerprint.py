"""Deterministic strategy behavioral fingerprints (W17/W9).

Hashes are content-addressed via canonical JSON + sha256. Similarity never
fabricates agreement from missing evidence — UNMEASURED when data is absent.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_value(value: Any) -> str:
    return _sha(_canon(value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_list(seq: Sequence[Any] | None) -> list[Any]:
    if seq is None:
        return []
    return list(seq)


def compute_behavior_fingerprint(
    *,
    strategy_id: str,
    strategy_version: int,
    dataset_version_id: str,
    signals: Sequence[Any] | None = None,
    positions: Sequence[Any] | None = None,
    trade_timestamps: Sequence[str] | None = None,
    returns: Sequence[float] | None = None,
    feature_set: Sequence[str] | None = None,
    regime_response: Mapping[str, Any] | None = None,
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute a row-shaped behavior fingerprint for persistence/comparison."""
    signal_hash = _hash_value(_as_list(signals))
    position_hash = _hash_value(_as_list(positions))
    trade_timing_hash = _hash_value(_as_list(trade_timestamps))
    return_series_hash = _hash_value(_as_list(returns))
    feature_set_hash = _hash_value(_as_list(feature_set))
    regime_response_hash = _hash_value(dict(regime_response) if regime_response is not None else {})

    summary_out: dict[str, Any] = dict(summary or {})
    # Preserve evidence needed for similarity when caller supplied series.
    if returns is not None and "returns" not in summary_out:
        summary_out["returns"] = [float(r) for r in returns]
    if positions is not None and "positions" not in summary_out:
        summary_out["positions"] = list(positions)
    if trade_timestamps is not None and "trade_timestamps" not in summary_out:
        summary_out["trade_timestamps"] = list(trade_timestamps)
    if feature_set is not None and "feature_set" not in summary_out:
        summary_out["feature_set"] = list(feature_set)
    if regime_response is not None and "regime_response" not in summary_out:
        summary_out["regime_response"] = dict(regime_response)

    summary_json = _canon(summary_out)
    fingerprint_id = _sha(
        _canon(
            {
                "strategy_id": strategy_id,
                "strategy_version": int(strategy_version),
                "dataset_version_id": dataset_version_id,
                "signal_hash": signal_hash,
                "position_hash": position_hash,
                "trade_timing_hash": trade_timing_hash,
                "return_series_hash": return_series_hash,
                "feature_set_hash": feature_set_hash,
                "regime_response_hash": regime_response_hash,
            }
        )
    )
    return {
        "fingerprint_id": fingerprint_id,
        "strategy_id": strategy_id,
        "strategy_version": int(strategy_version),
        "dataset_version_id": dataset_version_id,
        "signal_hash": signal_hash,
        "position_hash": position_hash,
        "trade_timing_hash": trade_timing_hash,
        "return_series_hash": return_series_hash,
        "feature_set_hash": feature_set_hash,
        "regime_response_hash": regime_response_hash,
        "summary_json": summary_json,
        "created_at": _utc_now(),
    }


def _summary_of(fp: Mapping[str, Any]) -> dict[str, Any]:
    raw = fp.get("summary")
    if isinstance(raw, Mapping):
        return dict(raw)
    sj = fp.get("summary_json")
    if isinstance(sj, Mapping):
        return dict(sj)
    if isinstance(sj, str) and sj.strip():
        try:
            parsed = json.loads(sj)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _metric(value: Any, state: str) -> dict[str, Any]:
    return {"value": value, "state": state}


def _jaccard(a: Sequence[Any], b: Sequence[Any]) -> float:
    sa = {_canon(x) for x in a}
    sb = {_canon(x) for x in b}
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


def _pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 2:
        return None
    xs = [float(a[i]) for i in range(n)]
    ys = [float(b[i]) for i in range(n)]
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)
    vx = sum((x - mx) ** 2 for x in xs) / (n - 1)
    vy = sum((y - my) ** 2 for y in ys) / (n - 1)
    if vx <= 0.0 or vy <= 0.0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def similarity(fp_a: Mapping[str, Any], fp_b: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic pairwise similarity; missing evidence stays UNMEASURED."""
    from .institutional_core.status import MeasurementState

    sa = _summary_of(fp_a)
    sb = _summary_of(fp_b)

    # signal_agreement — hash equality only (always measurable when hashes present)
    ha = fp_a.get("signal_hash")
    hb = fp_b.get("signal_hash")
    if ha is None or hb is None or ha == "" or hb == "":
        signal_agreement = _metric(None, MeasurementState.UNMEASURED.value)
    else:
        signal_agreement = _metric(
            1.0 if ha == hb else 0.0,
            MeasurementState.MEASURED.value,
        )

    # return_correlation — requires returns in both summaries
    ra = sa.get("returns")
    rb = sb.get("returns")
    if not isinstance(ra, Sequence) or not isinstance(rb, Sequence) or isinstance(ra, (str, bytes)):
        return_correlation = _metric(None, MeasurementState.UNMEASURED.value)
    elif not isinstance(rb, Sequence) or isinstance(rb, (str, bytes)):
        return_correlation = _metric(None, MeasurementState.UNMEASURED.value)
    else:
        corr = _pearson(list(ra), list(rb))
        if corr is None:
            return_correlation = _metric(None, MeasurementState.UNMEASURED.value)
        else:
            return_correlation = _metric(float(corr), MeasurementState.MEASURED.value)

    def _overlap(key: str, hash_key: str) -> dict[str, Any]:
        va = sa.get(key)
        vb = sb.get(key)
        if isinstance(va, Sequence) and isinstance(vb, Sequence) and not isinstance(va, (str, bytes)) and not isinstance(
            vb, (str, bytes)
        ):
            return _metric(_jaccard(list(va), list(vb)), MeasurementState.MEASURED.value)
        # Hashes alone cannot yield partial overlap — only equality is knowable,
        # and that is not fabricated as overlap without set evidence.
        _ = hash_key  # reserved for future hash-only diagnostics
        return _metric(None, MeasurementState.UNMEASURED.value)

    position_overlap = _overlap("positions", "position_hash")
    trade_timestamp_overlap = _overlap("trade_timestamps", "trade_timing_hash")
    feature_set_overlap = _overlap("feature_set", "feature_set_hash")

    # regime_response_similarity
    rra = sa.get("regime_response")
    rrb = sb.get("regime_response")
    if isinstance(rra, Mapping) and isinstance(rrb, Mapping):
        keys_a = set(rra.keys())
        keys_b = set(rrb.keys())
        if not keys_a and not keys_b:
            regime_response_similarity = _metric(1.0, MeasurementState.MEASURED.value)
        else:
            union = keys_a | keys_b
            agree = sum(1 for k in union if rra.get(k) == rrb.get(k))
            regime_response_similarity = _metric(
                agree / len(union) if union else 1.0,
                MeasurementState.MEASURED.value,
            )
    else:
        ha_r = fp_a.get("regime_response_hash")
        hb_r = fp_b.get("regime_response_hash")
        if ha_r and hb_r and ha_r == hb_r:
            # Exact hash match without payload still does not prove structured similarity.
            regime_response_similarity = _metric(None, MeasurementState.UNMEASURED.value)
        else:
            regime_response_similarity = _metric(None, MeasurementState.UNMEASURED.value)

    return {
        "return_correlation": return_correlation,
        "signal_agreement": signal_agreement,
        "position_overlap": position_overlap,
        "trade_timestamp_overlap": trade_timestamp_overlap,
        "feature_set_overlap": feature_set_overlap,
        "regime_response_similarity": regime_response_similarity,
    }
