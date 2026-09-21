from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolObservation:
    """Canonical observation of one capability execution.

    Invariant: observation records what happened — it is not completion authority
    and not evidence that requested artifacts exist unless separately verified.
    """

    observation_id: str
    request_id: str
    capability_id: str
    status: str
    side_effects: tuple[str, ...]
    created_at: str
    provider_kind: str | None = None
    provider_ref: str | None = None
    approval_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float | None = None
    effect_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "request_id": self.request_id,
            "capability_id": self.capability_id,
            "status": self.status,
            "side_effects": list(self.side_effects),
            "created_at": self.created_at,
            "provider_kind": self.provider_kind,
            "provider_ref": self.provider_ref,
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "effect_id": self.effect_id,
            "metadata": self.metadata,
            "truth": {
                "observation_is_not_evidence": True,
                "observation_is_not_completion_authority": True,
            },
        }


@dataclass(frozen=True)
class EffectRecord:
    effect_id: str
    request_id: str
    capability_id: str
    side_effects: tuple[str, ...]
    status: str
    recorded_at: str
    provider_kind: str | None = None
    provider_ref: str | None = None
    approval_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    observation_id: str | None = None
    error: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "request_id": self.request_id,
            "capability_id": self.capability_id,
            "side_effects": list(self.side_effects),
            "status": self.status,
            "recorded_at": self.recorded_at,
            "provider_kind": self.provider_kind,
            "provider_ref": self.provider_ref,
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "observation_id": self.observation_id,
            "error": self.error,
        }
