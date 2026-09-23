"""Integrity gates before publishing trained artifacts to the model registry (U294)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import ArtifactRecord, DurableTrainingJob


@dataclass
class IntegrityCheck:
    name: str
    passed: bool
    detail: str

    def public_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class IntegrityReport:
    artifact_id: str
    passed: bool
    checks: list[IntegrityCheck] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "passed": self.passed,
            "checks": [c.public_dict() for c in self.checks],
            "truth": {
                "registry_publish_requires_integrity": True,
                "no_silent_production_replace": True,
            },
        }


def verify_artifact_integrity(
    artifact: ArtifactRecord,
    *,
    job: DurableTrainingJob | None = None,
    require_mixture_hash: bool = False,
) -> IntegrityReport:
    checks: list[IntegrityCheck] = []
    path = Path(artifact.path) if artifact.path else None
    exists = bool(path and path.exists())
    checks.append(
        IntegrityCheck(
            name="artifact_path_exists",
            passed=exists,
            detail=str(path) if exists else f"missing path: {artifact.path}",
        )
    )
    hash_ok = False
    if exists and artifact.content_hash:
        assert path is not None
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hash_ok = digest == artifact.content_hash
        else:
            # Directory artifacts often hash a primary file (adapter_config.json), not the tree.
            candidates = [
                path / "adapter_config.json",
                path / "MODEL_CARD.md",
                path / "manifest.json",
            ]
            digests = []
            for child in candidates:
                if child.is_file():
                    digests.append(hashlib.sha256(child.read_bytes()).hexdigest())
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    digests.append(hashlib.sha256(child.read_bytes()).hexdigest())
            hash_ok = artifact.content_hash in digests
        checks.append(
            IntegrityCheck(
                name="content_hash_matches",
                passed=hash_ok,
                detail="ok" if hash_ok else "content_hash not found among artifact files",
            )
        )
    elif not artifact.content_hash:
        checks.append(
            IntegrityCheck(
                name="content_hash_matches",
                passed=False,
                detail="artifact content_hash missing",
            )
        )
    else:
        checks.append(
            IntegrityCheck(
                name="content_hash_matches",
                passed=False,
                detail="cannot hash missing path",
            )
        )

    if job is not None and job.config_hash and artifact.config_hash:
        config_ok = job.config_hash == artifact.config_hash
        checks.append(
            IntegrityCheck(
                name="config_hash_matches_job",
                passed=config_ok,
                detail="ok" if config_ok else "job/artifact config_hash mismatch",
            )
        )

    if require_mixture_hash or (job and (job.config or {}).get("mixture_id")):
        mixture_hash = (job.config or {}).get("mixture_content_hash") if job else None
        if not mixture_hash:
            checks.append(
                IntegrityCheck(
                    name="mixture_hash_present",
                    passed=False,
                    detail="training job missing mixture_content_hash",
                )
            )
        else:
            checks.append(
                IntegrityCheck(
                    name="mixture_hash_present",
                    passed=True,
                    detail=str(mixture_hash)[:16],
                )
            )

    passed = all(c.passed for c in checks)
    return IntegrityReport(artifact_id=artifact.artifact_id, passed=passed, checks=checks)
