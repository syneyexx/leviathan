"""Sim-to-real gap report foundation (T8 / G30).

Compares paper-forward fills vs simulator fills on shared intents.
Cost-model calibration data must be disjoint from evaluation data.
"""

from __future__ import annotations

import uuid
from typing import Any, Sequence


def _match_key(fill: dict[str, Any]) -> str:
    return "|".join(
        [
            str(fill.get("client_order_id") or fill.get("intent_id") or ""),
            str(fill.get("side") or ""),
            str(fill.get("ts") or fill.get("as_of") or ""),
        ]
    )


def compute_sim_real_gap(
    *,
    sim_fills: Sequence[dict[str, Any]],
    paper_fills: Sequence[dict[str, Any]],
    calibration_source_ids: Sequence[str] | None = None,
    evaluation_source_ids: Sequence[str] | None = None,
    created_at: str,
) -> dict[str, Any]:
    """Build a gap report: fill price delta, missed fills, slippage, latency."""
    sim_by = {_match_key(f): f for f in sim_fills if _match_key(f).strip("|")}
    paper_by = {_match_key(f): f for f in paper_fills if _match_key(f).strip("|")}
    keys = sorted(set(sim_by) | set(paper_by))

    price_deltas: list[float] = []
    slippage_deltas: list[float] = []
    latency_deltas: list[float] = []
    missed_in_paper = 0
    missed_in_sim = 0
    matched = 0

    for key in keys:
        s = sim_by.get(key)
        p = paper_by.get(key)
        if s is None:
            missed_in_sim += 1
            continue
        if p is None:
            missed_in_paper += 1
            continue
        matched += 1
        sp = float(s.get("price") or 0.0)
        pp = float(p.get("price") or 0.0)
        price_deltas.append(pp - sp)
        slippage_deltas.append(float(p.get("slippage") or 0.0) - float(s.get("slippage") or 0.0))
        # Latency in bars or ms when present
        s_lat = s.get("latency_ms")
        p_lat = p.get("latency_ms")
        if s_lat is not None and p_lat is not None:
            latency_deltas.append(float(p_lat) - float(s_lat))

    def _mean(xs: list[float]) -> float | None:
        return (sum(xs) / len(xs)) if xs else None

    calib = [str(x) for x in (calibration_source_ids or [])]
    evals = [str(x) for x in (evaluation_source_ids or [])]
    disjoint = not (set(calib) & set(evals)) if (calib or evals) else True

    return {
        "report_id": str(uuid.uuid4()),
        "matched_fills": matched,
        "missed_in_paper": missed_in_paper,
        "missed_in_sim": missed_in_sim,
        "fill_price_delta_mean": _mean(price_deltas),
        "fill_price_deltas": price_deltas[:200],
        "slippage_delta_mean": _mean(slippage_deltas),
        "latency_delta_mean_ms": _mean(latency_deltas),
        "calibration_source_ids": calib,
        "evaluation_source_ids": evals,
        "created_at": created_at,
        "truth": {
            "sim_to_real_gap": True,
            "calibration_disjoint_from_evaluation": disjoint,
            "foundation_only": True,
            "not_a_live_broker_claim": True,
        },
    }
