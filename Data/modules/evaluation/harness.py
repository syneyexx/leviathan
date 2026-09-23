from __future__ import annotations

import uuid
from typing import Any, Protocol

from Data.modules.evidence.types import EvidenceStatus
from Data.modules.verification import VerificationEngine, VerificationOutcome

from .types import (
    EvalCase,
    EvalCaseResult,
    EvalOutcome,
    EvalReport,
    JudgmentKind,
    MeasurementState,
    outcome_to_measurement,
)


class CatalogLike(Protocol):
    def __contains__(self, capability_id: str) -> bool: ...


class EvidenceLike(Protocol):
    def get(self, evidence_id: str): ...


class EvaluationHarness:
    """Honest evaluation runner. UNMEASURED ≠ PASSED (Wave 2 vocabulary)."""

    def __init__(
        self,
        *,
        catalog: CatalogLike | None = None,
        evidence: EvidenceLike | None = None,
        verification: VerificationEngine | None = None,
        model_revision: str | None = None,
        runtime_revision: str | None = None,
    ) -> None:
        self.catalog = catalog
        self.evidence = evidence
        self.verification = verification
        self.model_revision = model_revision
        self.runtime_revision = runtime_revision

    def run_suite(
        self,
        name: str,
        cases: list[EvalCase] | tuple[EvalCase, ...],
        *,
        suite_id: str | None = None,
        suite_version: str = "1",
        system_level: bool = False,
        artifact_refs: tuple[str, ...] = (),
    ) -> EvalReport:
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
        components = tuple(
            sorted({r.component for r in results if r.component})
        )
        resolved_suite = suite_id or (
            cases[0].suite_id if cases and cases[0].suite_id else str(uuid.uuid4())
        )
        return EvalReport(
            suite_id=resolved_suite,
            name=name,
            results=tuple(results),
            summary=summary,
            suite_version=suite_version,
            component_scope=components,
            system_level=system_level or any(c.system_level for c in cases),
            artifact_refs=artifact_refs,
        )

    def default_foundation_suite(self) -> list[EvalCase]:
        return [
            EvalCase(
                case_id="cap-file-read",
                name="file.read capability registered",
                description="Catalog must expose file.read",
                check="capability_exists",
                params={"capability_id": "file.read"},
                version="2",
                suite_id="foundation",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="execution",
                system_level=True,
                tags=("foundation", "capabilities"),
            ),
            EvalCase(
                case_id="cap-knowledge",
                name="knowledge.search capability registered",
                description="Catalog must expose knowledge.search",
                check="capability_exists",
                params={"capability_id": "knowledge.search"},
                version="2",
                suite_id="foundation",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="knowledge",
                system_level=True,
                tags=("foundation", "capabilities"),
            ),
            EvalCase(
                case_id="embedding-quality",
                name="Embedding quality",
                description="No embedding quality gate without measured provider",
                check="always_unmeasured",
                params={"reason": "NullEmbeddingProvider — quality unmeasured"},
                version="2",
                suite_id="foundation",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="knowledge",
                system_level=True,
                tags=("foundation", "honesty"),
            ),
        ]

    def default_regression_suite(self) -> list[EvalCase]:
        """Sealed regression cases when store corpus is empty (U325)."""
        return [
            EvalCase(
                case_id="reg-unmeasured-invariant",
                name="UNMEASURED ≠ PASS",
                description="Regression: missing measurement stays UNMEASURED",
                check="always_unmeasured",
                params={"reason": "sealed regression — unmeasured quality gate"},
                version="1",
                suite_id="regression",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="evaluation",
                system_level=True,
                sealed=True,
                tags=("regression", "honesty"),
            ),
            EvalCase(
                case_id="reg-file-read-exists",
                name="file.read registered",
                description="Regression: catalog must expose file.read",
                check="capability_exists",
                params={"capability_id": "file.read"},
                version="1",
                suite_id="regression",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="execution",
                sealed=True,
                tags=("regression", "capabilities"),
            ),
        ]

    def serving_conformance_suite(
        self,
        *,
        managed_load_ok: bool,
        stream_cancel_ok: bool,
        dead_worker_honest: bool,
        multi_model_route_ok: bool,
        measured_route_recorded: bool,
    ) -> list[EvalCase]:
        """Wave 3 serving conformance before production-capable claims (U035)."""
        return [
            EvalCase(
                case_id="serving-managed-load",
                name="Managed load/unload path",
                description="Managed adapter can load and unload a local model residency",
                check="serving_flag",
                params={"ok": managed_load_ok, "name": "managed_load", "runtime_probed": True},
                version="1",
                suite_id="serving_conformance",
                judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                component="model_runtime",
                system_level=True,
                tags=("serving", "conformance"),
            ),
            EvalCase(
                case_id="serving-stream-cancel",
                name="True stream cancellation",
                description="Token stream honors cooperative cancel without fabricating SSE",
                check="serving_flag",
                params={"ok": stream_cancel_ok, "name": "stream_cancel", "runtime_probed": True},
                version="1",
                suite_id="serving_conformance",
                judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                component="model_runtime",
                tags=("serving", "streaming"),
            ),
            EvalCase(
                case_id="serving-dead-worker",
                name="Killed worker honest recovery",
                description="Dead serving worker is DEAD/OFFLINE, never READY",
                check="serving_flag",
                params={"ok": dead_worker_honest, "name": "dead_worker", "runtime_probed": True},
                version="1",
                suite_id="serving_conformance",
                judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                component="models",
                tags=("serving", "recovery"),
            ),
            EvalCase(
                case_id="serving-multi-route",
                name="Multi-model route",
                description="Router can select among multiple registered local models",
                check="serving_flag",
                params={"ok": multi_model_route_ok, "name": "multi_route", "runtime_probed": True},
                version="1",
                suite_id="serving_conformance",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="models",
                tags=("serving", "routing"),
            ),
            EvalCase(
                case_id="serving-measured-audit",
                name="Measured route audit recorded",
                description="Route decisions persist candidates/scores for replay",
                check="serving_flag",
                params={"ok": measured_route_recorded, "name": "measured_audit", "runtime_probed": True},
                version="1",
                suite_id="serving_conformance",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="models",
                tags=("serving", "routing"),
            ),
            EvalCase(
                case_id="serving-batching-qos",
                name="Continuous batching QoS",
                description="Interactive vs background admission under load — not claimed without measured scheduler",
                check="always_unmeasured",
                params={"reason": "Continuous batching / KV scheduler not instrumented in this build"},
                version="1",
                suite_id="serving_conformance",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="model_runtime",
                tags=("serving", "honesty"),
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
                version="1",
                suite_id="neuro_ablation",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="neuro",
                tags=("neuro", "ablation"),
            ),
            EvalCase(
                case_id="neuro-ablate-cortex",
                name="Cortex flag posture",
                description="Cortex engagement flag state (informational)",
                check="neuro_flag",
                params={"enabled": cortex_enabled, "name": "cortex"},
                version="1",
                suite_id="neuro_ablation",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="neuro",
                tags=("neuro", "ablation"),
            ),
            EvalCase(
                case_id="neuro-ablate-memory-tiers",
                name="Memory tiers flag posture",
                description="Memory tiers flag state (informational)",
                check="neuro_flag",
                params={"enabled": memory_tiers_enabled, "name": "memory_tiers"},
                version="1",
                suite_id="neuro_ablation",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="neuro",
                tags=("neuro", "ablation"),
            ),
            EvalCase(
                case_id="neuro-ablate-critic",
                name="Process critic flag posture",
                description="Process critic flag state (informational)",
                check="neuro_flag",
                params={"enabled": critic_enabled, "name": "process_critic"},
                version="1",
                suite_id="neuro_ablation",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="neuro",
                tags=("neuro", "ablation"),
            ),
            EvalCase(
                case_id="neuro-contrastive-embeddings",
                name="Contrastive embedding quality",
                description="Contrastive vector retrieval requires measured embeddings",
                check="always_unmeasured",
                params={"reason": "Contrastive vector head unmeasured without EmbeddingProvider"},
                version="1",
                suite_id="neuro_ablation",
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="neuro",
                tags=("neuro", "honesty"),
            ),
        ]

    def _enrich(self, case: EvalCase, result: EvalCaseResult) -> EvalCaseResult:
        measurement = result.measurement or outcome_to_measurement(result.outcome)
        return EvalCaseResult(
            case_id=result.case_id,
            outcome=result.outcome,
            detail=result.detail,
            judgment_kind=result.judgment_kind or case.judgment_kind,
            measurement=measurement,
            artifact_refs=result.artifact_refs,
            evidence_refs=result.evidence_refs,
            model_revision=result.model_revision or self.model_revision,
            runtime_revision=result.runtime_revision or self.runtime_revision,
            sample_size=result.sample_size,
            effect_size=result.effect_size,
            confidence_interval=result.confidence_interval,
            paired_with=result.paired_with,
            component=result.component or case.component,
        )

    def _run_case(self, case: EvalCase) -> EvalCaseResult:
        try:
            if case.check == "capability_exists":
                cap_id = str(case.params.get("capability_id") or "")
                if self.catalog is None:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.UNMEASURED,
                            "no catalog",
                            judgment_kind=case.judgment_kind,
                            measurement=MeasurementState.UNMEASURED,
                        ),
                    )
                if cap_id in self.catalog:
                    # Registry presence ≠ operational probe. Mark as UNMEASURED
                    # unless an explicit runtime probe param is provided.
                    if case.params.get("runtime_probed") is True:
                        return self._enrich(
                            case,
                            EvalCaseResult(
                                case.case_id,
                                EvalOutcome.PASSED,
                                f"probed {cap_id}",
                                judgment_kind=case.judgment_kind,
                                measurement=MeasurementState.PASS,
                            ),
                        )
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.UNMEASURED,
                            f"registered {cap_id} — registration is not operational proof",
                            judgment_kind=case.judgment_kind,
                            measurement=MeasurementState.UNMEASURED,
                        ),
                    )
                return self._enrich(
                    case,
                    EvalCaseResult(
                        case.case_id,
                        EvalOutcome.FAILED,
                        f"missing {cap_id}",
                        judgment_kind=case.judgment_kind,
                        measurement=MeasurementState.FAIL,
                    ),
                )
            if case.check == "evidence_verified":
                if self.evidence is None:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.UNMEASURED,
                            "no evidence store",
                            judgment_kind=JudgmentKind.RETRIEVAL_EVIDENCE,
                            measurement=MeasurementState.UNMEASURED,
                        ),
                    )
                evidence_id = str(case.params.get("evidence_id") or "")
                record = self.evidence.get(evidence_id)
                if record is None:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.UNMEASURED,
                            "evidence missing",
                            judgment_kind=JudgmentKind.RETRIEVAL_EVIDENCE,
                            measurement=MeasurementState.UNMEASURED,
                        ),
                    )
                if record.status == EvidenceStatus.VERIFIED:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.PASSED,
                            "verified",
                            judgment_kind=JudgmentKind.RETRIEVAL_EVIDENCE,
                            measurement=MeasurementState.PASS,
                            evidence_refs=(evidence_id,),
                        ),
                    )
                if record.status == EvidenceStatus.FAILED:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.FAILED,
                            "evidence failed",
                            judgment_kind=JudgmentKind.RETRIEVAL_EVIDENCE,
                            measurement=MeasurementState.FAIL,
                            evidence_refs=(evidence_id,),
                        ),
                    )
                return self._enrich(
                    case,
                    EvalCaseResult(
                        case.case_id,
                        EvalOutcome.UNMEASURED,
                        record.status.value,
                        judgment_kind=JudgmentKind.RETRIEVAL_EVIDENCE,
                        measurement=MeasurementState.UNMEASURED,
                        evidence_refs=(evidence_id,),
                    ),
                )
            if case.check == "verification_report":
                if self.verification is None:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.UNMEASURED,
                            "no verification engine",
                            judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                            measurement=MeasurementState.UNMEASURED,
                        ),
                    )
                # Empty requirements → UNMEASURED by design
                report = self.verification.verify([])
                if report.outcome == VerificationOutcome.PASSED:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.PASSED,
                            "passed",
                            judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                            measurement=MeasurementState.PASS,
                        ),
                    )
                if report.outcome == VerificationOutcome.FAILED:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.FAILED,
                            "failed",
                            judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                            measurement=MeasurementState.FAIL,
                        ),
                    )
                return self._enrich(
                    case,
                    EvalCaseResult(
                        case.case_id,
                        EvalOutcome.UNMEASURED,
                        "unmeasured",
                        judgment_kind=JudgmentKind.EXECUTABLE_VERIFIER,
                        measurement=MeasurementState.UNMEASURED,
                    ),
                )
            if case.check == "neuro_residual":
                supported = bool(case.params.get("supported"))
                if not supported:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.UNMEASURED,
                            "residual runtime unsupported — ablation UNMEASURED not PASSED",
                            judgment_kind=case.judgment_kind,
                            measurement=MeasurementState.UNMEASURED,
                        ),
                    )
                return self._enrich(
                    case,
                    EvalCaseResult(
                        case.case_id,
                        EvalOutcome.PASSED,
                        "residual runtime supports hooks",
                        judgment_kind=case.judgment_kind,
                        measurement=MeasurementState.PASS,
                    ),
                )
            if case.check == "neuro_flag":
                enabled = bool(case.params.get("enabled"))
                name = str(case.params.get("name") or "flag")
                # Feature-flag posture is informational — never PASS.
                return self._enrich(
                    case,
                    EvalCaseResult(
                        case.case_id,
                        EvalOutcome.UNMEASURED,
                        f"{name}={'ON' if enabled else 'OFF'} (flag posture — not operational proof)",
                        judgment_kind=case.judgment_kind,
                        measurement=MeasurementState.UNMEASURED,
                    ),
                )
            if case.check == "serving_flag":
                # Serving flags without a real probe are UNMEASURED, never PASS.
                ok = case.params.get("ok")
                name = str(case.params.get("name") or "serving")
                probed = case.params.get("runtime_probed") is True
                if not probed:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.UNMEASURED,
                            f"{name} unprobed — configuration is not a serving measurement",
                            judgment_kind=case.judgment_kind,
                            measurement=MeasurementState.UNMEASURED,
                        ),
                    )
                if ok:
                    return self._enrich(
                        case,
                        EvalCaseResult(
                            case.case_id,
                            EvalOutcome.PASSED,
                            f"{name}=ok (probed)",
                            judgment_kind=case.judgment_kind,
                            measurement=MeasurementState.PASS,
                        ),
                    )
                return self._enrich(
                    case,
                    EvalCaseResult(
                        case.case_id,
                        EvalOutcome.FAILED,
                        f"{name}=failed (probed)",
                        judgment_kind=case.judgment_kind,
                        measurement=MeasurementState.FAIL,
                    ),
                )
            if case.check == "always_unmeasured":
                return self._enrich(
                    case,
                    EvalCaseResult(
                        case.case_id,
                        EvalOutcome.UNMEASURED,
                        str(case.params.get("reason") or "unmeasured"),
                        judgment_kind=case.judgment_kind,
                        measurement=MeasurementState.UNMEASURED,
                    ),
                )
            return self._enrich(
                case,
                EvalCaseResult(
                    case.case_id,
                    EvalOutcome.ERROR,
                    f"unknown check: {case.check}",
                    judgment_kind=case.judgment_kind,
                    measurement=MeasurementState.FAIL,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._enrich(
                case,
                EvalCaseResult(
                    case.case_id,
                    EvalOutcome.ERROR,
                    str(exc),
                    judgment_kind=case.judgment_kind,
                    measurement=MeasurementState.FAIL,
                ),
            )
