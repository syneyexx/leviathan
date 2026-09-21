"""Provider health, failure memory and bounded performance metrics."""

from __future__ import annotations

from typing import Any

from .policy import plugin_health_state
from .store import load_metrics, record_failure, upsert_metric
from .taxonomy import normalize_health


def health_from_plugin(plugin: dict[str, Any] | None) -> str:
    return normalize_health(plugin_health_state(plugin))


def remember_failure(
    db: Any,
    *,
    mission_id: str,
    provider_id: str,
    capability_id: str,
    kind: str,
    detail: str = "",
) -> None:
    if db is None:
        return
    record_failure(
        db,
        mission_id=mission_id,
        provider_id=provider_id,
        capability_id=capability_id,
        kind=kind,
        detail=detail,
    )
    upsert_metric(
        db,
        f"{provider_id}:{capability_id}",
        {
            "provider_id": provider_id,
            "capability_id": capability_id,
            "attempts": 1,
            "failures": 1,
            "timeouts": 1 if kind == "timeout" else 0,
            "last_failure": kind,
        },
    )


def record_outcome(
    db: Any,
    *,
    provider_id: str,
    capability_id: str,
    version: str = "",
    domain: str = "",
    execution_success: bool,
    verified_success: bool,
    latency_ms: int | None = None,
    model_calls: int = 0,
    tokens: dict[str, int | None] | None = None,
) -> None:
    """Persist observed metrics. Missing token counts stay unknown (NULL)."""
    if db is None:
        return
    tokens = tokens or {}
    upsert_metric(
        db,
        f"{provider_id}:{capability_id}:{version}:{domain}",
        {
            "provider_id": provider_id,
            "capability_id": capability_id,
            "version": version,
            "domain": domain,
            "attempts": 1,
            "execution_successes": 1 if execution_success else 0,
            "verified_successes": 1 if verified_success else 0,
            "failures": 0 if execution_success else 1,
            "latency_ms_sum": int(latency_ms or 0),
            "model_calls": int(model_calls or 0),
            "input_tokens": tokens.get("input"),
            "output_tokens": tokens.get("output"),
            "cached_tokens": tokens.get("cached"),
        },
    )


def metrics_by_capability(db: Any) -> dict[str, dict[str, Any]]:
    if db is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in load_metrics(db):
        out[str(row.get("capability_id") or "")] = row
    return out
