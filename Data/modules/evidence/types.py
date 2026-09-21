from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceKind(str, Enum):
    ARTIFACT_HASH = "ARTIFACT_HASH"
    OBSERVATION_REF = "OBSERVATION_REF"
    FILE_EXISTS = "FILE_EXISTS"
    COMPOSITE = "COMPOSITE"


class EvidenceStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class EvidenceRecord:
    """Verified (or failed) proof that something concrete holds.

    Invariant: ToolObservation is not Evidence. Evidence may reference an
    observation or artifact, but must carry its own verification outcome.
    """

    evidence_id: str
    kind: EvidenceKind
    status: EvidenceStatus
    claim: str
    created_at: str
    verified_at: str | None = None
    observation_id: str | None = None
    artifact_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    content_hash: str | None = None
    path: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "claim": self.claim,
            "created_at": self.created_at,
            "verified_at": self.verified_at,
            "observation_id": self.observation_id,
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "content_hash": self.content_hash,
            "path": self.path,
            "error": self.error,
            "metadata": self.metadata,
            "truth": {
                "observation_is_not_evidence": True,
                "model_output_is_not_evidence": True,
            },
        }
