"""Shadow-ledger reconciliation, drift bands, and data-quality watchdog (T9 / G33)."""

from __future__ import annotations

import uuid
from typing import Any, Sequence


def reconcile_shadow_ledger(
    *,
    primary_fills: Sequence[dict[str, Any]],
    shadow_fills: Sequence[dict[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    """Compare primary paper fills vs independent shadow ledger."""

    def _key(f: dict[str, Any]) -> str:
        return "|".join(
            [
                str(f.get("client_order_id") or f.get("order_id") or ""),
                str(f.get("side") or ""),
                str(f.get("qty") or ""),
            ]
        )

    primary = {_key(f): f for f in primary_fills}
    shadow = {_key(f): f for f in shadow_fills}
    keys = set(primary) | set(shadow)
    matched = 0
    qty_mismatches = 0
    price_deltas: list[float] = []
    missing_primary = 0
    missing_shadow = 0
    for key in keys:
        p = primary.get(key)
        s = shadow.get(key)
        if p is None:
            missing_primary += 1
            continue
        if s is None:
            missing_shadow += 1
            continue
        matched += 1
        if float(p.get("qty") or 0) != float(s.get("qty") or 0):
            qty_mismatches += 1
        pp = float(p.get("fill_price") or p.get("price") or 0)
        sp = float(s.get("fill_price") or s.get("price") or 0)
        price_deltas.append(pp - sp)
    return {
        "reconciliation_id": str(uuid.uuid4()),
        "matched": matched,
        "missing_in_primary": missing_primary,
        "missing_in_shadow": missing_shadow,
        "qty_mismatches": qty_mismatches,
        "price_delta_mean": (sum(price_deltas) / len(price_deltas)) if price_deltas else None,
        "created_at": created_at,
        "truth": {
            "independent_shadow_ledger": True,
            "not_blind_trust_of_broker": True,
        },
    }


def drift_vs_backtest(
    *,
    paper_equity: Sequence[float],
    backtest_equity: Sequence[float],
    band_pct: float = 5.0,
    created_at: str,
) -> dict[str, Any]:
    """Compare paper-forward equity path vs backtest within drift bands."""
    n = min(len(paper_equity), len(backtest_equity))
    breaches = 0
    max_abs_pct = 0.0
    for i in range(n):
        b = float(backtest_equity[i])
        p = float(paper_equity[i])
        if b == 0:
            continue
        pct = abs(p - b) / abs(b) * 100.0
        max_abs_pct = max(max_abs_pct, pct)
        if pct > band_pct:
            breaches += 1
    within = breaches == 0 and n > 0
    return {
        "drift_id": str(uuid.uuid4()),
        "points_compared": n,
        "band_pct": band_pct,
        "breaches": breaches,
        "max_abs_drift_pct": max_abs_pct,
        "within_band": within,
        "created_at": created_at,
        "truth": {"drift_vs_backtest": True},
    }


def data_quality_watchdog(
    *,
    feed_status: str,
    feed_latency_ms: float | None,
    max_latency_ms: float = 5_000.0,
    stale: bool = False,
) -> dict[str, Any]:
    """Pause/halt recommendation when feed is stale or unhealthy."""
    action = "ok"
    reasons: list[str] = []
    status = str(feed_status or "unknown").lower()
    if status.startswith("error") or status in {"disconnected", "unknown"}:
        action = "pause"
        reasons.append(f"feed_status={feed_status}")
    if stale:
        action = "halt" if action == "pause" else "pause"
        reasons.append("stale_feed")
    if feed_latency_ms is not None and float(feed_latency_ms) > max_latency_ms:
        action = "pause"
        reasons.append(f"latency_ms={feed_latency_ms}>{max_latency_ms}")
    return {
        "action": action,
        "reasons": reasons,
        "truth": {"data_quality_watchdog": True, "can_pause_or_halt": True},
    }
