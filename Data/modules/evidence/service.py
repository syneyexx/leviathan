from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .store import EvidenceStore
from .types import EvidenceKind, EvidenceRecord, EvidenceStatus


class ArtifactVerifier(Protocol):
    def get(self, artifact_id: str) -> Any: ...

    def verify_hash(self, artifact_id: str) -> bool: ...


class ObservationLookup(Protocol):
    def get_observation(self, observation_id: str) -> Any: ...


class EvidenceService:
    """Create and verify evidence without elevating observations to proof."""

    def __init__(
        self,
        store: EvidenceStore,
        *,
        artifacts: ArtifactVerifier | None = None,
        observations: ObservationLookup | None = None,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.observations = observations

    def claim_artifact_hash(
        self,
        *,
        artifact_id: str,
        claim: str | None = None,
        observation_id: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        verify_now: bool = True,
    ) -> EvidenceRecord:
        if self.artifacts is None:
            raise RuntimeError("Artifact verifier not configured")
        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            raise KeyError(f"Unknown artifact: {artifact_id}")
        record = self.store.create(
            kind=EvidenceKind.ARTIFACT_HASH,
            claim=claim or f"Artifact {artifact_id} content hash matches stored digest",
            status=EvidenceStatus.UNVERIFIED,
            artifact_id=artifact_id,
            observation_id=observation_id,
            run_id=run_id or getattr(artifact, "run_id", None),
            job_id=job_id or getattr(artifact, "job_id", None),
            content_hash=getattr(artifact, "content_hash", None),
            path=getattr(artifact, "path", None),
        )
        if verify_now:
            return self.verify(record.evidence_id)
        return record

    def claim_observation_ref(
        self,
        *,
        observation_id: str,
        claim: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
    ) -> EvidenceRecord:
        """Record that an observation exists — not that its outputs are true.

        Status stays UNVERIFIED unless the observation record is found; finding
        the row only proves existence of the observation, marked VERIFIED with
        kind OBSERVATION_REF (existence only).
        """
        if self.observations is None:
            raise RuntimeError("Observation lookup not configured")
        obs = self.observations.get_observation(observation_id)
        if obs is None:
            return self.store.create(
                kind=EvidenceKind.OBSERVATION_REF,
                claim=claim or f"Observation {observation_id} exists",
                status=EvidenceStatus.FAILED,
                observation_id=observation_id,
                run_id=run_id,
                job_id=job_id,
                error="Observation not found",
            )
        return self.store.create(
            kind=EvidenceKind.OBSERVATION_REF,
            claim=claim or f"Observation {observation_id} exists in store",
            status=EvidenceStatus.VERIFIED,
            observation_id=observation_id,
            run_id=run_id or getattr(obs, "run_id", None),
            job_id=job_id or getattr(obs, "job_id", None),
            metadata={
                "observation_status": getattr(obs, "status", None),
                "existence_only": True,
            },
        )

    def claim_file_exists(
        self,
        *,
        path: str,
        claim: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        observation_id: str | None = None,
    ) -> EvidenceRecord:
        target = Path(path)
        exists = target.is_file()
        return self.store.create(
            kind=EvidenceKind.FILE_EXISTS,
            claim=claim or f"File exists: {path}",
            status=EvidenceStatus.VERIFIED if exists else EvidenceStatus.FAILED,
            path=str(target),
            run_id=run_id,
            job_id=job_id,
            observation_id=observation_id,
            error=None if exists else "File does not exist",
        )

    def verify(self, evidence_id: str) -> EvidenceRecord:
        record = self.store.get(evidence_id)
        if record is None:
            raise KeyError(f"Unknown evidence: {evidence_id}")
        if record.kind == EvidenceKind.ARTIFACT_HASH:
            if self.artifacts is None or not record.artifact_id:
                updated = self.store.set_status(
                    evidence_id,
                    EvidenceStatus.FAILED,
                    error="Cannot verify artifact hash without artifact binding",
                )
                assert updated is not None
                return updated
            try:
                ok = self.artifacts.verify_hash(record.artifact_id)
            except Exception as exc:  # noqa: BLE001
                updated = self.store.set_status(
                    evidence_id,
                    EvidenceStatus.FAILED,
                    error=str(exc),
                )
                assert updated is not None
                return updated
            status = EvidenceStatus.VERIFIED if ok else EvidenceStatus.FAILED
            updated = self.store.set_status(
                evidence_id,
                status,
                error=None if ok else "Artifact content hash mismatch",
                content_hash=record.content_hash,
            )
            assert updated is not None
            return updated
        if record.kind == EvidenceKind.FILE_EXISTS:
            exists = bool(record.path and Path(record.path).is_file())
            updated = self.store.set_status(
                evidence_id,
                EvidenceStatus.VERIFIED if exists else EvidenceStatus.FAILED,
                error=None if exists else "File does not exist",
            )
            assert updated is not None
            return updated
        # OBSERVATION_REF / COMPOSITE — leave as stored (existence already decided).
        return record
