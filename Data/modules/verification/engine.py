from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol

from Data.modules.evidence.types import EvidenceKind, EvidenceRecord, EvidenceStatus

from .types import (
    RequirementResult,
    VerificationOutcome,
    VerificationReport,
    VerificationRequirement,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EvidenceLister(Protocol):
    def list(self, *, status=None, run_id=None, limit: int = 100): ...


class VerificationEngine:
    """Evaluate completion requirements against Evidence — never against model text.

    Invariant: UNMEASURED is not PASSED.
    """

    def __init__(self, evidence_store: EvidenceLister) -> None:
        self.evidence_store = evidence_store

    def verify(
        self,
        requirements: list[VerificationRequirement] | tuple[VerificationRequirement, ...],
        *,
        run_id: str | None = None,
        job_id: str | None = None,
        evidence: list[EvidenceRecord] | None = None,
    ) -> VerificationReport:
        reqs = list(requirements)
        if not reqs:
            return VerificationReport(
                report_id=str(uuid.uuid4()),
                outcome=VerificationOutcome.UNMEASURED,
                created_at=utc_now(),
                run_id=run_id,
                job_id=job_id,
                requirements=(),
                metadata={"reason": "no_requirements"},
            )

        pool = evidence
        if pool is None:
            pool = list(self.evidence_store.list(run_id=run_id, limit=500))
            if job_id:
                pool = [item for item in pool if item.job_id == job_id or item.job_id is None]

        results: list[RequirementResult] = []
        for req in reqs:
            results.append(self._check_requirement(req, pool))

        if any(item.outcome == VerificationOutcome.FAILED for item in results):
            outcome = VerificationOutcome.FAILED
        elif any(item.outcome == VerificationOutcome.UNMEASURED for item in results):
            outcome = VerificationOutcome.UNMEASURED
        elif all(item.outcome == VerificationOutcome.PASSED for item in results):
            outcome = VerificationOutcome.PASSED
        else:
            outcome = VerificationOutcome.UNMEASURED

        return VerificationReport(
            report_id=str(uuid.uuid4()),
            outcome=outcome,
            created_at=utc_now(),
            run_id=run_id,
            job_id=job_id,
            requirements=tuple(results),
            metadata={"evidence_considered": len(pool)},
        )

    def _check_requirement(
        self,
        req: VerificationRequirement,
        pool: list[EvidenceRecord],
    ) -> RequirementResult:
        matches: list[EvidenceRecord] = []
        for item in pool:
            if item.status != EvidenceStatus.VERIFIED:
                continue
            if req.evidence_kind and item.kind.value != req.evidence_kind:
                continue
            if req.artifact_id and item.artifact_id != req.artifact_id:
                continue
            if req.path and item.path != req.path:
                continue
            if req.observation_id and item.observation_id != req.observation_id:
                continue
            matches.append(item)

        if len(matches) >= req.min_verified:
            return RequirementResult(
                requirement_id=req.requirement_id,
                outcome=VerificationOutcome.PASSED,
                matched_evidence_ids=tuple(m.evidence_id for m in matches),
                detail=f"matched {len(matches)} verified evidence record(s)",
            )

        # Distinguish "no evidence of right kind" (UNMEASURED) vs "failed evidence exists".
        related_failed = [
            item
            for item in pool
            if item.status == EvidenceStatus.FAILED
            and (not req.evidence_kind or item.kind.value == req.evidence_kind)
            and (not req.artifact_id or item.artifact_id == req.artifact_id)
            and (not req.path or item.path == req.path)
            and (not req.observation_id or item.observation_id == req.observation_id)
        ]
        if related_failed:
            return RequirementResult(
                requirement_id=req.requirement_id,
                outcome=VerificationOutcome.FAILED,
                matched_evidence_ids=tuple(m.evidence_id for m in related_failed),
                detail="related evidence exists but verification failed",
            )
        return RequirementResult(
            requirement_id=req.requirement_id,
            outcome=VerificationOutcome.UNMEASURED,
            matched_evidence_ids=(),
            detail="no matching verified evidence — unmeasured is not passed",
        )

    @staticmethod
    def require_artifact(artifact_id: str, *, requirement_id: str | None = None) -> VerificationRequirement:
        return VerificationRequirement(
            requirement_id=requirement_id or f"artifact:{artifact_id}",
            description=f"Verified artifact hash for {artifact_id}",
            evidence_kind=EvidenceKind.ARTIFACT_HASH.value,
            artifact_id=artifact_id,
        )

    @staticmethod
    def require_file(path: str, *, requirement_id: str | None = None) -> VerificationRequirement:
        return VerificationRequirement(
            requirement_id=requirement_id or f"file:{path}",
            description=f"File exists: {path}",
            evidence_kind=EvidenceKind.FILE_EXISTS.value,
            path=path,
        )
