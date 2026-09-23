"""Measured routing policy + durable route audit (U041–U042, U039, U060).

Selection ≠ permission. Router never grants capability authority.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from Data.modules.model_runtime.serving import InferenceJobClass
from Data.modules.models.contracts import (
    CapabilityState,
    ModelDescriptor,
    ModelRequest,
    RouteDecision,
)
from Data.modules.models.store import ModelStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class RouteCandidateScore:
    model_id: str
    score: float | None  # None = unmeasured features only
    features: dict[str, Any] = field(default_factory=dict)
    disqualified: bool = False
    disqualify_reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "score": self.score,
            "features": dict(self.features),
            "disqualified": self.disqualified,
            "disqualify_reason": self.disqualify_reason,
            "truth": {"unmeasured_score_is_visible": self.score is None},
        }


@dataclass
class MeasuredRouteDecision:
    decision: RouteDecision
    job_class: InferenceJobClass
    candidates: tuple[RouteCandidateScore, ...]
    recorded_at: str
    policy_id: str = "measured_v1"
    override_reason: str | None = None
    user_explicit: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.public_dict(),
            "job_class": self.job_class.value,
            "candidates": [c.public_dict() for c in self.candidates],
            "recorded_at": self.recorded_at,
            "policy_id": self.policy_id,
            "override_reason": self.override_reason,
            "user_explicit": self.user_explicit,
            "truth": {
                "selection_is_not_permission": True,
                "router_does_not_grant_capability_authority": True,
                "unmeasured_is_not_passed": True,
            },
        }


def score_candidate(
    model: ModelDescriptor,
    request: ModelRequest,
    *,
    health_score: float | None = None,
    latency_ms: float | None = None,
    job_class: InferenceJobClass = InferenceJobClass.INTERACTIVE,
) -> RouteCandidateScore:
    """Deterministic measured features. Missing measurements stay visible as None."""
    features: dict[str, Any] = {
        "lifecycle": model.lifecycle_state.value,
        "health": model.health.value,
        "source": model.source.value,
        "context_window": model.context_window,
        "job_class": job_class.value,
        "provider_health_score": health_score,
        "latency_ms": latency_ms,
    }
    if model.lifecycle_state.value in {"error", "offline"}:
        return RouteCandidateScore(
            model_id=model.id,
            score=None,
            features=features,
            disqualified=True,
            disqualify_reason=f"lifecycle={model.lifecycle_state.value}",
        )
    for cap in request.required_capabilities:
        attr = {
            "chat": "chat",
            "streaming": "streaming",
            "tool_calling": "tool_calling",
            "toolCalling": "tool_calling",
            "structured_output": "structured_output",
            "structuredOutput": "structured_output",
            "vision": "vision",
            "embeddings": "embeddings",
            "reasoning": "reasoning",
            "coding": "coding",
        }.get(cap, cap)
        state = getattr(model.capabilities, attr, CapabilityState.UNKNOWN)
        if state == CapabilityState.UNSUPPORTED:
            return RouteCandidateScore(
                model_id=model.id,
                score=None,
                features=features,
                disqualified=True,
                disqualify_reason=f"unsupported capability {cap}",
            )
    if request.locality == "local_only" and model.source.value not in {
        "local",
        "imported",
        "downloaded",
    }:
        return RouteCandidateScore(
            model_id=model.id,
            score=None,
            features=features,
            disqualified=True,
            disqualify_reason="local_only locality",
        )

    # Measured composite when we have signals; else None (UNMEASURED, not 0).
    parts: list[float] = []
    if health_score is not None:
        parts.append(max(0.0, min(1.0, health_score)))
    if latency_ms is not None and latency_ms > 0:
        # Lower latency → higher score; uncapped soft scale.
        parts.append(max(0.0, min(1.0, 1.0 - (latency_ms / 5000.0))))
    if model.loaded:
        parts.append(0.85)
    elif model.lifecycle_state.value in {"available", "active", "discovered"}:
        parts.append(0.5)
    score = sum(parts) / len(parts) if parts else None
    # Interactive QoS: prefer already-loaded models under background pressure.
    if job_class == InferenceJobClass.INTERACTIVE and model.loaded and score is not None:
        score = min(1.0, score + 0.1)
    return RouteCandidateScore(
        model_id=model.id,
        score=score,
        features=features,
        disqualified=False,
    )


class MeasuredRouter:
    """Wraps ModelRouter.resolve with scored candidates + durable audit (U041–U042)."""

    def __init__(self, store: ModelStore, resolve_fn) -> None:
        self.store = store
        self._resolve_fn = resolve_fn

    def resolve_measured(
        self,
        request: ModelRequest | None = None,
        *,
        models: list[ModelDescriptor],
        job_class: InferenceJobClass = InferenceJobClass.INTERACTIVE,
        health_by_model: dict[str, float | None] | None = None,
        latency_by_model: dict[str, float | None] | None = None,
        persist: bool = True,
    ) -> MeasuredRouteDecision:
        request = request or ModelRequest()
        health_by_model = health_by_model or {}
        latency_by_model = latency_by_model or {}
        candidates = tuple(
            score_candidate(
                model,
                request,
                health_score=health_by_model.get(model.id),
                latency_ms=latency_by_model.get(model.id),
                job_class=job_class,
            )
            for model in models
        )
        decision = self._resolve_fn(request)
        # Enrich decision with measured fields when contract supports them.
        if hasattr(decision, "score_features") or True:
            decision = RouteDecision(
                model_id=decision.model_id,
                reason=decision.reason,
                fallback_used=decision.fallback_used,
                fallback_reason=decision.fallback_reason,
                candidates_tried=list(decision.candidates_tried),
                trace_id=decision.trace_id or str(uuid.uuid4()),
                job_class=job_class.value,
                candidate_scores=[c.public_dict() for c in candidates],
                policy_id="measured_v1",
            )
        measured = MeasuredRouteDecision(
            decision=decision,
            job_class=job_class,
            candidates=candidates,
            recorded_at=_utc_now(),
            user_explicit=bool(request.explicit_model_id),
            override_reason="explicit" if request.explicit_model_id else None,
        )
        if persist:
            self.store.record_route_decision(measured.public_dict())
        return measured
