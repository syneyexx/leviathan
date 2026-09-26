from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

from Data.modules.evidence.types import EvidenceKind, EvidenceRecord, EvidenceStatus

from .claims import (
    ClaimAssessment,
    ClaimSupportStatus,
    ClaimVerifier,
    VerificationPool,
)
from .types import (
    RequirementResult,
    VerificationOutcome,
    VerificationReport,
    VerificationRequirement,
    VerificationTier,
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
                metadata={
                    "reason": "no_requirements",
                    "verification_tier": VerificationTier.DETERMINISTIC_VERIFICATION.value,
                    "truth": {
                        "deterministic_evidence_checks": True,
                        "unmeasured_is_not_passed": True,
                        "same_model_critique_is_not_independent_verification": True,
                    },
                },
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
            metadata={
                "evidence_considered": len(pool),
                "verification_tier": VerificationTier.DETERMINISTIC_VERIFICATION.value,
                "truth": {
                    "deterministic_evidence_checks": True,
                    "same_model_critique_is_not_independent_verification": True,
                },
            },
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

    def verify_claim_assessments(
        self,
        claims: Sequence[ClaimAssessment] | Sequence[Mapping[str, Any]],
        *,
        run_id: str | None = None,
        job_id: str | None = None,
        evidence: list[EvidenceRecord] | None = None,
        tool_receipt_ids: Sequence[str] | None = None,
        tool_receipts: Sequence[Any] | None = None,
        source_refs: Sequence[str] | None = None,
        artifact_ids: Sequence[str] | None = None,
        telemetry: Mapping[str, Any] | None = None,
        fresh_source_refs: Sequence[str] | None = None,
        model_verified_flags: Mapping[str, bool] | None = None,
    ) -> VerificationReport:
        """Evaluate claim assessments against the evidence pool.

        Invariants:
        - Invented evidence_refs (not in the pool) never produce PASSED.
        - Critic/model ``verified=true`` flags are not verification.
        - Claim CONFLICTED/UNSUPPORTED map to FAILED; UNMEASURED stays UNMEASURED.
        """
        pool_evidence = evidence
        if pool_evidence is None:
            pool_evidence = list(self.evidence_store.list(run_id=run_id, limit=500))
            if job_id:
                pool_evidence = [
                    item
                    for item in pool_evidence
                    if item.job_id == job_id or item.job_id is None
                ]

        pool = VerificationPool.from_inputs(
            evidence=pool_evidence,
            tool_receipts=tool_receipts,
            tool_receipt_ids=tool_receipt_ids,
            source_refs=source_refs,
            artifact_ids=artifact_ids,
            telemetry=telemetry,
            fresh_source_refs=fresh_source_refs,
        )

        normalized: list[ClaimAssessment] = []
        proposed_evidence: dict[str, tuple[str, ...]] = {}
        proposed_tools: dict[str, tuple[str, ...]] = {}
        for raw in claims:
            claim = self._coerce_claim(raw)
            normalized.append(claim)
            # Critic may supply refs on the claim itself — still validated against pool.
            if claim.evidence_refs:
                proposed_evidence[claim.claim_id] = claim.evidence_refs
            if claim.tool_receipt_refs:
                proposed_tools[claim.claim_id] = claim.tool_receipt_refs

        verifier = ClaimVerifier()
        assessed = verifier.verify(
            normalized,
            pool,
            proposed_evidence_refs=proposed_evidence,
            proposed_tool_receipt_refs=proposed_tools,
            model_verified_flags=model_verified_flags,
        )

        results: list[RequirementResult] = []
        for item in assessed:
            outcome = self._claim_status_to_outcome(item.status)
            # Extra hard rule: any rejected invented refs → never PASSED.
            if item.reason == "invented_evidence_refs_rejected":
                outcome = (
                    VerificationOutcome.FAILED
                    if item.contradiction_refs
                    else VerificationOutcome.UNMEASURED
                )
            results.append(
                RequirementResult(
                    requirement_id=item.claim_id,
                    outcome=outcome,
                    matched_evidence_ids=tuple(
                        ref for ref in item.evidence_refs if ref in pool.evidence_ids
                    ),
                    detail=item.reason or item.status.value,
                )
            )

        if not results:
            report_outcome = VerificationOutcome.UNMEASURED
        elif any(r.outcome == VerificationOutcome.FAILED for r in results):
            report_outcome = VerificationOutcome.FAILED
        elif any(r.outcome == VerificationOutcome.UNMEASURED for r in results):
            report_outcome = VerificationOutcome.UNMEASURED
        elif all(r.outcome == VerificationOutcome.PASSED for r in results):
            report_outcome = VerificationOutcome.PASSED
        else:
            report_outcome = VerificationOutcome.UNMEASURED

        return VerificationReport(
            report_id=str(uuid.uuid4()),
            outcome=report_outcome,
            created_at=utc_now(),
            run_id=run_id,
            job_id=job_id,
            requirements=tuple(results),
            metadata={
                "evidence_considered": len(pool_evidence),
                "claim_assessments": [a.public_dict() for a in assessed],
                "truth": {
                    "invented_evidence_refs_rejected": True,
                    "model_verified_flag_is_not_verification": True,
                    "unmeasured_is_not_passed": True,
                },
            },
        )

    @staticmethod
    def _claim_status_to_outcome(status: ClaimSupportStatus) -> VerificationOutcome:
        if status in {
            ClaimSupportStatus.SUPPORTED,
            ClaimSupportStatus.TOOL_VERIFIED,
            ClaimSupportStatus.SOURCE_SUPPORTED,
            ClaimSupportStatus.CORROBORATED,
        }:
            return VerificationOutcome.PASSED
        if status in {
            ClaimSupportStatus.CONFLICTED,
            ClaimSupportStatus.UNSUPPORTED,
        }:
            return VerificationOutcome.FAILED
        # UNMEASURED / INFERRED / MODEL_PRIOR / UNAVAILABLE → not PASSED
        return VerificationOutcome.UNMEASURED

    @staticmethod
    def _coerce_claim(raw: ClaimAssessment | Mapping[str, Any]) -> ClaimAssessment:
        if isinstance(raw, ClaimAssessment):
            return raw
        from .claims import ClaimKind

        kind_raw = raw.get("claim_kind") or raw.get("kind") or ClaimKind.ORDINARY_FACTUAL
        status_raw = raw.get("status") or ClaimSupportStatus.UNMEASURED
        kind = kind_raw if isinstance(kind_raw, ClaimKind) else ClaimKind(str(kind_raw))
        status = (
            status_raw
            if isinstance(status_raw, ClaimSupportStatus)
            else ClaimSupportStatus(str(status_raw))
        )
        return ClaimAssessment(
            claim_id=str(raw.get("claim_id") or f"claim:{uuid.uuid4().hex[:12]}"),
            claim_text=str(raw.get("claim_text") or raw.get("text") or ""),
            claim_kind=kind,
            status=status,
            source_refs=tuple(raw.get("source_refs") or ()),
            tool_receipt_refs=tuple(raw.get("tool_receipt_refs") or ()),
            evidence_refs=tuple(raw.get("evidence_refs") or ()),
            artifact_refs=tuple(raw.get("artifact_refs") or ()),
            freshness_requirement=raw.get("freshness_requirement"),
            as_of=raw.get("as_of"),
            confidence=raw.get("confidence"),
            contradiction_refs=tuple(raw.get("contradiction_refs") or ()),
            reason=raw.get("reason"),
        )

    def self_critique(
        self,
        *,
        text: str,
        run_id: str | None = None,
        critic_findings: Sequence[Mapping[str, Any]] | None = None,
    ) -> VerificationReport:
        """Same-model / same-role critique path — NEVER labelled independent verification."""
        findings = list(critic_findings or [])
        high = [f for f in findings if str(f.get("severity") or "").lower() == "high"]
        if high:
            outcome = VerificationOutcome.FAILED
            detail = str(high[0].get("message") or "self-critique high severity")
        elif findings:
            outcome = VerificationOutcome.PARTIAL
            detail = f"{len(findings)} self-critique finding(s) — not independent verification"
        elif not (text or "").strip():
            outcome = VerificationOutcome.UNMEASURED
            detail = "empty text — self-critique unmeasured"
        else:
            outcome = VerificationOutcome.UNMEASURED
            detail = "self-critique without structured findings remains UNMEASURED"

        return VerificationReport(
            report_id=str(uuid.uuid4()),
            outcome=outcome,
            created_at=utc_now(),
            run_id=run_id,
            requirements=(),
            metadata={
                "verification_tier": VerificationTier.SELF_CRITIQUE.value,
                "detail": detail,
                "finding_count": len(findings),
                "truth": {
                    "self_critique_is_not_independent_verification": True,
                    "same_model_critique_is_not_cross_model": True,
                    "unmeasured_is_not_passed": True,
                },
            },
        )

    def cross_model_verify(
        self,
        *,
        run_id: str | None = None,
        secondary_model_available: bool = False,
        secondary_agrees: bool | None = None,
        requirements: list[VerificationRequirement] | None = None,
    ) -> VerificationReport:
        """Cross-model tier — requires a different model/family when available."""
        if not secondary_model_available:
            return VerificationReport(
                report_id=str(uuid.uuid4()),
                outcome=VerificationOutcome.UNMEASURED,
                created_at=utc_now(),
                run_id=run_id,
                requirements=(),
                metadata={
                    "verification_tier": VerificationTier.CROSS_MODEL_VERIFICATION.value,
                    "detail": "no distinct secondary model/family available",
                    "truth": {
                        "cross_model_requires_different_model": True,
                        "unmeasured_is_not_passed": True,
                    },
                },
            )
        if secondary_agrees is True and not requirements:
            outcome = VerificationOutcome.PASSED
            detail = "secondary model agreed (no deterministic requirements attached)"
        elif secondary_agrees is False:
            outcome = VerificationOutcome.FAILED
            detail = "secondary model disagreed"
        else:
            outcome = VerificationOutcome.UNMEASURED
            detail = "secondary agreement UNMEASURED"
        return VerificationReport(
            report_id=str(uuid.uuid4()),
            outcome=outcome,
            created_at=utc_now(),
            run_id=run_id,
            requirements=(),
            metadata={
                "verification_tier": VerificationTier.CROSS_MODEL_VERIFICATION.value,
                "detail": detail,
                "truth": {
                    "cross_model_requires_different_model": True,
                    "self_critique_is_not_cross_model": True,
                },
            },
        )
