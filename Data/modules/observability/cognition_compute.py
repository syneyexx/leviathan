"""Two-axis cognition compute observability (F17 / R26).

Surfaces orchestration mode + neural effort / token fields from public
cognition status — never private CoT.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping


def cognition_compute_snapshot(
    *,
    runtime: Any | None = None,
    run_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a public two-axis compute snapshot for telemetry/status surfaces."""
    status: dict[str, Any] = dict(run_status or {})
    if not status and runtime is not None and hasattr(runtime, "health"):
        try:
            health = runtime.health()
        except Exception:  # noqa: BLE001
            health = {}
        status = {
            "health": health if isinstance(health, dict) else {},
        }
        # Prefer the most recent tracked run public status when available.
        runs = getattr(runtime, "_runs", None)
        if isinstance(runs, dict) and runs:
            try:
                latest = max(runs.values(), key=lambda s: getattr(s, "usage", None) and s.usage.iterations or 0)
                if hasattr(latest, "public_status"):
                    status = {**status, **latest.public_status()}
            except Exception:  # noqa: BLE001
                pass

    neural = status.get("neural_budgets")
    if not isinstance(neural, Mapping):
        neural = {}
    reasoning_state = status.get("reasoning_state")
    if not isinstance(reasoning_state, Mapping):
        reasoning_state = {}

    return {
        "orchestration": {
            "mode": status.get("mode"),
            "requested_mode": status.get("requested_mode"),
            "effective_mode": status.get("effective_mode"),
            "clamp_reason": status.get("clamp_reason"),
            "strategy": status.get("strategy"),
            "budgets": status.get("budgets"),
            "usage": status.get("usage"),
        },
        "neural": {
            "native_effort": neural.get("native_effort")
            or reasoning_state.get("native_effort_effective"),
            "max_reasoning_tokens": neural.get("max_reasoning_tokens"),
            "candidate_count": neural.get("candidate_count"),
            "max_parallel_candidates": neural.get("max_parallel_candidates"),
            "diversity_temperature": neural.get("diversity_temperature"),
            "reasoning_tokens_status": reasoning_state.get("reasoning_tokens_status"),
            "inference_path": reasoning_state.get("inference_path"),
            "model_calls_consumed": reasoning_state.get("model_calls_consumed"),
            "expected_gain": status.get("expected_gain"),
            "neural_adaptation": status.get("neural_adaptation"),
        },
        "run_id": status.get("run_id"),
        "status": status.get("status"),
        "truth": {
            "two_axis_compute_observability": True,
            "no_private_cot": True,
            "orchestration_axis_separate_from_neural_axis": True,
            "unmeasured_fields_remain_null": True,
        },
    }


def attach_cognition_compute_provider(
    observability: Any,
    provider: Callable[[], Mapping[str, Any] | None],
) -> None:
    """Attach a lazy provider so hub.snapshot() can include cognition compute."""
    if observability is None:
        return
    setattr(observability, "_cognition_compute_provider", provider)
