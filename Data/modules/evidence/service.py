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

    def claim_capability_receipt(
        self,
        *,
        receipt_id: str,
        claim: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        observation_id: str | None = None,
        receipt_lookup: Any | None = None,
        receipt_status: str | None = None,
        side_effects: list[str] | None = None,
    ) -> EvidenceRecord:
        """Record that a capability-call receipt exists — not that outputs are true.

        VERIFIED only when the receipt is found and status is a successful terminal.
        """
        status_s = (receipt_status or "").upper()
        found = False
        error: str | None = None
        meta: dict[str, Any] = {"existence_only": True}
        if side_effects:
            meta["side_effects"] = list(side_effects)[:16]

        lookup = receipt_lookup
        if lookup is not None and hasattr(lookup, "get"):
            try:
                receipt = lookup.get(receipt_id)
            except Exception as exc:  # noqa: BLE001
                receipt = None
                error = str(exc)
            if receipt is not None:
                found = True
                status_s = str(
                    getattr(receipt, "status", None)
                    or (receipt.get("status") if isinstance(receipt, dict) else status_s)
                    or status_s
                ).upper()
                meta["capability_id"] = getattr(receipt, "capability_id", None) or (
                    receipt.get("capability_id") if isinstance(receipt, dict) else None
                )
                se = getattr(receipt, "side_effects", None)
                if se is None and isinstance(receipt, dict):
                    se = receipt.get("side_effects")
                if se:
                    meta["side_effects"] = [str(x) for x in list(se)[:16]]
                run_id = run_id or getattr(receipt, "run_id", None) or (
                    receipt.get("run_id") if isinstance(receipt, dict) else None
                )
        elif status_s:
            # Caller attested receipt fields (e.g. from observation telemetry).
            found = True
            meta["attested_from_observation"] = True

        ok_statuses = {"COMPLETED", "OK", "SUCCESS", "COMPLETED_VERIFIED"}
        if found and status_s in ok_statuses:
            ev_status = EvidenceStatus.VERIFIED
        elif found:
            ev_status = EvidenceStatus.FAILED
            error = error or f"receipt status not successful: {status_s or 'unknown'}"
        else:
            ev_status = EvidenceStatus.FAILED
            error = error or "capability receipt not found"

        return self.store.create(
            kind=EvidenceKind.CAPABILITY_RECEIPT,
            claim=claim or f"Capability receipt {receipt_id} recorded",
            status=ev_status,
            run_id=run_id,
            job_id=job_id,
            observation_id=observation_id,
            error=error,
            metadata={**meta, "receipt_id": receipt_id},
        )

    def claim_research_source(
        self,
        *,
        research_evidence_id: str,
        claim: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        observation_id: str | None = None,
        project_id: str | None = None,
        source_id: str | None = None,
        research_lookup: Any | None = None,
        attested: bool = False,
    ) -> EvidenceRecord:
        """Record that a research evidence id resolves to a source — not that the claim is true.

        VERIFIED only when lookup resolves citation → evidence → source, or when the
        run observation already attested a research evidence row (existence only).
        """
        meta: dict[str, Any] = {
            "existence_only": True,
            "research_evidence_id": research_evidence_id,
        }
        if project_id:
            meta["project_id"] = project_id
        resolved = False
        error: str | None = None

        if research_lookup is not None:
            try:
                if hasattr(research_lookup, "resolve_citation") and project_id:
                    resolution = research_lookup.resolve_citation(
                        project_id, f"e:{research_evidence_id}"
                    )
                    resolved = bool(getattr(resolution, "resolved", False))
                    if not resolved:
                        error = str(getattr(resolution, "reason", None) or "unresolved")
                    else:
                        meta["source_id"] = getattr(resolution, "source_id", source_id)
                elif hasattr(research_lookup, "get_evidence"):
                    ev = research_lookup.get_evidence(research_evidence_id)
                    if ev is not None:
                        sid = getattr(ev, "source_id", None) or (
                            ev.get("source_id") if isinstance(ev, dict) else None
                        )
                        if sid and hasattr(research_lookup, "get_source"):
                            src = research_lookup.get_source(sid)
                            resolved = src is not None
                            meta["source_id"] = sid
                            if not resolved:
                                error = "source_not_found"
                        else:
                            resolved = bool(sid)
                            meta["source_id"] = sid
                            if not resolved:
                                error = "source_id_missing"
                    else:
                        error = "evidence_not_found"
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
        elif attested and research_evidence_id:
            # Observation-attested research evidence id (ledger listed it in-run).
            resolved = True
            meta["attested_from_observation"] = True
            if source_id:
                meta["source_id"] = source_id

        return self.store.create(
            kind=EvidenceKind.RESEARCH_SOURCE,
            claim=claim or f"Research evidence {research_evidence_id} resolves to a source",
            status=EvidenceStatus.VERIFIED if resolved else EvidenceStatus.FAILED,
            run_id=run_id,
            job_id=job_id,
            observation_id=observation_id,
            error=None if resolved else (error or "research evidence not resolved"),
            metadata=meta,
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
        # CAPABILITY_RECEIPT / RESEARCH_SOURCE / OBSERVATION_REF / COMPOSITE —
        # existence already decided at claim time.
        return record
