from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNMEASURED = "UNMEASURED"


@dataclass(frozen=True)
class VerificationRequirement:
    requirement_id: str
    description: str
    evidence_kind: str | None = None  # ARTIFACT_HASH | FILE_EXISTS | OBSERVATION_REF | …
    min_verified: int = 1
    artifact_id: str | None = None
    path: str | None = None
    observation_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "description": self.description,
            "evidence_kind": self.evidence_kind,
            "min_verified": self.min_verified,
            "artifact_id": self.artifact_id,
            "path": self.path,
            "observation_id": self.observation_id,
        }


@dataclass(frozen=True)
class RequirementResult:
    requirement_id: str
    outcome: VerificationOutcome
    matched_evidence_ids: tuple[str, ...] = ()
    detail: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "outcome": self.outcome.value,
            "matched_evidence_ids": list(self.matched_evidence_ids),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class VerificationReport:
    report_id: str
    outcome: VerificationOutcome
    created_at: str
    run_id: str | None = None
    job_id: str | None = None
    requirements: tuple[RequirementResult, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "outcome": self.outcome.value,
            "created_at": self.created_at,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "requirements": [item.public_dict() for item in self.requirements],
            "metadata": self.metadata,
            "truth": {
                "unmeasured_is_not_passed": True,
                "model_output_is_not_evidence": True,
                "dispatch_is_not_completion": True,
            },
        }
