from __future__ import annotations

import uuid
from typing import Any, Protocol

from Data.modules.evidence.types import EvidenceStatus
from Data.modules.verification import VerificationEngine, VerificationOutcome

from .types import EvalCase, EvalCaseResult, EvalOutcome, EvalReport


class CatalogLike(Protocol):
    def __contains__(self, capability_id: str) -> bool: ...


class EvidenceLike(Protocol):
    def get(self, evidence_id: str): ...


class EvaluationHarness:
    """Small honest evaluation runner. UNMEASURED ≠ PASSED."""

    def __init__(
        self,
        *,
        catalog: CatalogLike | None = None,
        evidence: EvidenceLike | None = None,
        verification: VerificationEngine | None = None,
    ) -> None:
        self.catalog = catalog
        self.evidence = evidence
        self.verification = verification

    def run_suite(self, name: str, cases: list[EvalCase] | tuple[EvalCase, ...]) -> EvalReport:
        results: list[EvalCaseResult] = []
        for case in cases:
            results.append(self._run_case(case))
        summary = {
            "passed": sum(1 for r in results if r.outcome == EvalOutcome.PASSED),
            "failed": sum(1 for r in results if r.outcome == EvalOutcome.FAILED),
            "unmeasured": sum(1 for r in results if r.outcome == EvalOutcome.UNMEASURED),
            "error": sum(1 for r in results if r.outcome == EvalOutcome.ERROR),
            "total": len(results),
        }
        return EvalReport(
            suite_id=str(uuid.uuid4()),
            name=name,
            results=tuple(results),
            summary=summary,
        )

    def default_foundation_suite(self) -> list[EvalCase]:
        return [
            EvalCase(
                case_id="cap-file-read",
                name="file.read capability registered",
                description="Catalog must expose file.read",
                check="capability_exists",
                params={"capability_id": "file.read"},
            ),
            EvalCase(
                case_id="cap-knowledge",
                name="knowledge.search capability registered",
                description="Catalog must expose knowledge.search",
                check="capability_exists",
                params={"capability_id": "knowledge.search"},
            ),
            EvalCase(
                case_id="embedding-quality",
                name="Embedding quality",
                description="No embedding quality gate without measured provider",
                check="always_unmeasured",
                params={"reason": "NullEmbeddingProvider — quality unmeasured"},
            ),
        ]

    def neuro_ablation_suite(
        self,
        *,
        residual_supported: bool,
        cortex_enabled: bool,
        memory_tiers_enabled: bool,
        critic_enabled: bool,
    ) -> list[EvalCase]:
        """Ablation checks. Missing residual hardware ⇒ UNMEASURED, not PASSED."""
        return [
            EvalCase(
                case_id="neuro-residual-port",
                name="Residual port availability",
                description="Residual-capable runtime present",
                check="neuro_residual",
                params={"supported": residual_supported},
            ),
            EvalCase(
                case_id="neuro-ablate-cortex",
                name="Cortex flag posture",
                description="Cortex engagement flag state (informational)",
                check="neuro_flag",
                params={"enabled": cortex_enabled, "name": "cortex"},
            ),
            EvalCase(
                case_id="neuro-ablate-memory-tiers",
                name="Memory tiers flag posture",
                description="Memory tiers flag state (informational)",
                check="neuro_flag",
                params={"enabled": memory_tiers_enabled, "name": "memory_tiers"},
            ),
            EvalCase(
                case_id="neuro-ablate-critic",
                name="Process critic flag posture",
                description="Process critic flag state (informational)",
                check="neuro_flag",
                params={"enabled": critic_enabled, "name": "process_critic"},
            ),
            EvalCase(
                case_id="neuro-contrastive-embeddings",
                name="Contrastive embedding quality",
                description="Contrastive vector retrieval requires measured embeddings",
                check="always_unmeasured",
                params={"reason": "Contrastive vector head unmeasured without EmbeddingProvider"},
            ),
        ]

    def _run_case(self, case: EvalCase) -> EvalCaseResult:
        try:
            if case.check == "capability_exists":
                cap_id = str(case.params.get("capability_id") or "")
                if self.catalog is None:
                    return EvalCaseResult(case.case_id, EvalOutcome.UNMEASURED, "no catalog")
                if cap_id in self.catalog:
                    return EvalCaseResult(case.case_id, EvalOutcome.PASSED, f"found {cap_id}")
                return EvalCaseResult(case.case_id, EvalOutcome.FAILED, f"missing {cap_id}")
            if case.check == "evidence_verified":
                if self.evidence is None:
                    return EvalCaseResult(case.case_id, EvalOutcome.UNMEASURED, "no evidence store")
                evidence_id = str(case.params.get("evidence_id") or "")
                record = self.evidence.get(evidence_id)
                if record is None:
                    return EvalCaseResult(case.case_id, EvalOutcome.UNMEASURED, "evidence missing")
                if record.status == EvidenceStatus.VERIFIED:
                    return EvalCaseResult(case.case_id, EvalOutcome.PASSED, "verified")
                if record.status == EvidenceStatus.FAILED:
                    return EvalCaseResult(case.case_id, EvalOutcome.FAILED, "evidence failed")
                return EvalCaseResult(case.case_id, EvalOutcome.UNMEASURED, record.status.value)
            if case.check == "verification_report":
                if self.verification is None:
                    return EvalCaseResult(case.case_id, EvalOutcome.UNMEASURED, "no verification engine")
                # Empty requirements → UNMEASURED by design
                report = self.verification.verify([])
                if report.outcome == VerificationOutcome.PASSED:
                    return EvalCaseResult(case.case_id, EvalOutcome.PASSED, "passed")
                if report.outcome == VerificationOutcome.FAILED:
                    return EvalCaseResult(case.case_id, EvalOutcome.FAILED, "failed")
                return EvalCaseResult(case.case_id, EvalOutcome.UNMEASURED, "unmeasured")
            if case.check == "neuro_residual":
                supported = bool(case.params.get("supported"))
                if not supported:
                    return EvalCaseResult(
                        case.case_id,
                        EvalOutcome.UNMEASURED,
                        "residual runtime unsupported — ablation UNMEASURED not PASSED",
                    )
                return EvalCaseResult(case.case_id, EvalOutcome.PASSED, "residual runtime supports hooks")
            if case.check == "neuro_flag":
                enabled = bool(case.params.get("enabled"))
                name = str(case.params.get("name") or "flag")
                return EvalCaseResult(
                    case.case_id,
                    EvalOutcome.PASSED,
                    f"{name}={'ON' if enabled else 'OFF'} (posture recorded)",
                )
            if case.check == "always_unmeasured":
                return EvalCaseResult(
                    case.case_id,
                    EvalOutcome.UNMEASURED,
                    str(case.params.get("reason") or "unmeasured"),
                )
            return EvalCaseResult(case.case_id, EvalOutcome.ERROR, f"unknown check: {case.check}")
        except Exception as exc:  # noqa: BLE001
            return EvalCaseResult(case.case_id, EvalOutcome.ERROR, str(exc))
