from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    run_id: str | None
    job_id: str | None
    artifact_type: str
    path: str
    content_hash: str
    size_bytes: int
    created_at: str
    producer: str
    verification_status: str
    metadata: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "type": self.artifact_type,
            "path": self.path,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "producer": self.producer,
            "verification_status": self.verification_status,
            "metadata": self.metadata,
        }
