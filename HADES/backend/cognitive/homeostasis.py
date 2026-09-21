"""Pillar 7 — Cognitive Homeostasis.

Detect unhealthy cognitive-runtime envelopes and apply bounded corrective
actions. Failures are recorded, never silently hidden.
"""

from __future__ import annotations

from typing import Any

from .contracts import AdaptiveDecision, new_id, utc_now
from .modes import CognitiveMode, mode_allows_influence


# Healthy operating envelopes (conservative defaults).
DEFAULT_ENVELOPES: dict[str, dict[str, float]] = {
    "context_tokens": {"warn": 12_000, "critical": 24_000},
    "retrieval_calls": {"warn": 12, "critical": 30},
    "tool_calls": {"warn": 40, "critical": 80},
    "model_calls": {"warn": 30, "critical": 60},
    "agent_fanout": {"warn": 4, "critical": 8},
    "retry_count": {"warn": 3, "critical": 6},
    "latency_ms": {"warn": 30_000, "critical": 90_000},
    "verification_failure_rate": {"warn": 0.35, "critical": 0.6},
    "ram_pressure": {"warn": 0.85, "critical": 0.95},
    "vram_pressure": {"warn": 0.85, "critical": 0.95},
    "neural_interference": {"warn": 0.4, "critical": 0.7},
}


CORRECTIVE_ACTIONS: dict[str, dict[str, str]] = {
    "context_saturation": {
        "action": "summarize_and_retrieve_selectively",
        "reason_code": "HOMEOSTASIS_CONTEXT_COMPRESS",
    },
    "retrieval_explosion": {
        "action": "bound_retrieval",
        "reason_code": "HOMEOSTASIS_RETRIEVAL_BOUND",
    },
    "agent_explosion": {
        "action": "reduce_fanout",
        "reason_code": "HOMEOSTASIS_REDUCE_FANOUT",
    },
    "model_call_explosion": {
        "action": "throttle_model_calls",
        "reason_code": "HOMEOSTASIS_THROTTLE_MODEL",
    },
    "tool_call_explosion": {
        "action": "throttle_tool_calls",
        "reason_code": "HOMEOSTASIS_THROTTLE_TOOL",
    },
    "neural_instability": {
        "action": "neural_fallback",
        "reason_code": "HOMEOSTASIS_NEURAL_FALLBACK",
    },
    "vram_pressure": {
        "action": "select_cheaper_path",
        "reason_code": "HOMEOSTASIS_CHEAPER_PATH",
    },
    "ram_pressure": {
        "action": "reduce_concurrency",
        "reason_code": "HOMEOSTASIS_REDUCE_CONCURRENCY",
    },
    "provider_instability": {
        "action": "fallback_provider",
        "reason_code": "HOMEOSTASIS_PROVIDER_FALLBACK",
    },
    "verification_collapse": {
        "action": "stop_autonomous_execution",
        "reason_code": "HOMEOSTASIS_STOP_AUTONOMY",
    },
    "latency_spike": {
        "action": "degrade_gracefully",
        "reason_code": "HOMEOSTASIS_DEGRADE",
    },
    "retry_storm": {
        "action": "circuit_break_retries",
        "reason_code": "HOMEOSTASIS_CIRCUIT_BREAK",
    },
}


def evaluate_signals(
    metrics: dict[str, Any],
    *,
    envelopes: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """Compare metrics against healthy envelopes; return degradation signals."""
    env = envelopes or DEFAULT_ENVELOPES
    signals: list[dict[str, Any]] = []

    def _check(metric_key: str, signal_name: str) -> None:
        if metric_key not in metrics or metrics[metric_key] is None:
            return
        try:
            value = float(metrics[metric_key])
        except (TypeError, ValueError):
            return
        bounds = env.get(metric_key) or {}
        warn = float(bounds.get("warn", 1e18))
        critical = float(bounds.get("critical", 1e18))
        if value >= critical:
            signals.append(
                {
                    "signal": signal_name,
                    "metric": metric_key,
                    "value": value,
                    "severity": "critical",
                    "threshold": critical,
                }
            )
        elif value >= warn:
            signals.append(
                {
                    "signal": signal_name,
                    "metric": metric_key,
                    "value": value,
                    "severity": "warn",
                    "threshold": warn,
                }
            )

    _check("context_tokens", "context_saturation")
    _check("retrieval_calls", "retrieval_explosion")
    _check("agent_fanout", "agent_explosion")
    _check("model_calls", "model_call_explosion")
    _check("tool_calls", "tool_call_explosion")
    _check("neural_interference", "neural_instability")
    _check("vram_pressure", "vram_pressure")
    _check("ram_pressure", "ram_pressure")
    _check("verification_failure_rate", "verification_collapse")
    _check("latency_ms", "latency_spike")
    _check("retry_count", "retry_storm")

    if metrics.get("provider_failures"):
        signals.append(
            {
                "signal": "provider_instability",
                "metric": "provider_failures",
                "value": metrics.get("provider_failures"),
                "severity": "critical" if int(metrics.get("provider_failures") or 0) >= 3 else "warn",
                "threshold": 3,
            }
        )
    if metrics.get("neural_degraded") or metrics.get("neural_oom"):
        signals.append(
            {
                "signal": "neural_instability",
                "metric": "neural_degraded",
                "value": 1,
                "severity": "critical",
                "threshold": 1,
            }
        )
    return signals


def corrective_plan(
    signals: list[dict[str, Any]],
    *,
    mode: CognitiveMode = CognitiveMode.SHADOW,
) -> dict[str, Any]:
    """Map degradation signals to bounded corrective actions."""
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sig in sorted(signals, key=lambda s: 0 if s.get("severity") == "critical" else 1):
        name = str(sig.get("signal") or "")
        if name in seen:
            continue
        seen.add(name)
        policy = CORRECTIVE_ACTIONS.get(name)
        if not policy:
            continue
        actions.append(
            {
                "signal": name,
                "severity": sig.get("severity"),
                "action": policy["action"],
                "reason_code": policy["reason_code"],
                "metric": sig.get("metric"),
                "value": sig.get("value"),
                "recorded": True,  # never hide failures
            }
        )

    influence = mode_allows_influence(mode)
    applied = [a for a in actions] if influence else []
    primary = actions[0] if actions else None
    decision = AdaptiveDecision(
        controller="cognitive.homeostasis",
        decision=(primary["action"] if primary and influence else "observe_only"),
        reason_code=primary["reason_code"] if primary else "HEALTHY",
        mode=mode.value,
        fallback="record_only" if not influence else None,
    )
    healthy = not actions
    return {
        "healthy": healthy,
        "signals": signals,
        "recommended_actions": actions,
        "applied_actions": applied,
        "influence": influence,
        "decision": decision.to_dict(),
        "generated_at": utc_now(),
    }


def assess_homeostasis(
    metrics: dict[str, Any],
    *,
    mode: CognitiveMode = CognitiveMode.SHADOW,
    envelopes: dict[str, dict[str, float]] | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    signals = evaluate_signals(metrics, envelopes=envelopes)
    plan = corrective_plan(signals, mode=mode)
    if store is not None:
        for action in plan["recommended_actions"]:
            store.append_homeostasis_event(
                {
                    "id": new_id("homeo"),
                    "signal": action["signal"],
                    "severity": action["severity"],
                    "action": action["action"],
                    "reason_code": action["reason_code"],
                    "value": action.get("value"),
                    "mode": mode.value,
                    "applied": mode_allows_influence(mode),
                }
            )
    return plan
