"""Frontier reasoning evaluation suite + ablations (F16 / R24).

Deterministic probes — no live LLM required. UNMEASURED ≠ PASS.
Feature flags alone are not ablation results.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from Data.modules.evaluation.ablations import AblationConditionResult, AblationReport
from Data.modules.evaluation.types import (
    EvalCase,
    EvalCaseResult,
    EvalOutcome,
    EvalReport,
    JudgmentKind,
    MeasurementState,
)


FRONTIER_SUITE_ID = "frontier_reasoning"
FRONTIER_ABLATION_SUITE_ID = "frontier_ablation"

FRONTIER_ABLATION_FEATURES = (
    "belief",
    "experience_learning",
    "trajectory_export",
    "candidate_lifecycle",
)


def frontier_reasoning_suite() -> list[EvalCase]:
    """EvalCase list for EvaluationHarness.run_suite (check=frontier_probe)."""
    probes = (
        ("sole_runtime", "CognitiveRuntime remains sole orchestration owner"),
        ("experience_admission", "Unverified experience is not training truth"),
        ("trajectory_no_private_cot", "Trajectory export scrubs private CoT"),
        ("candidate_govern_before_ingest", "Candidate ingest requires govern"),
        ("two_axis_neural_budgets", "NeuralComputeBudget two-axis present"),
        ("active_learning_no_auto_promote", "Active learning never auto-promotes"),
        ("hypothesis_board_public", "HypothesisBoard is public structured state"),
        ("capability_state_matrix", "CapabilityState matrix blocks denied axes"),
    )
    cases: list[EvalCase] = []
    for probe_id, name in probes:
        cases.append(
            EvalCase(
                case_id=f"frontier-{probe_id}",
                name=name,
                description=f"Frontier reasoning probe: {probe_id}",
                check="frontier_probe",
                params={"probe_id": probe_id},
                version="1",
                suite_id=FRONTIER_SUITE_ID,
                judgment_kind=JudgmentKind.DETERMINISTIC,
                component="cognition",
                system_level=True,
                tags=("frontier_reasoning", "cognition"),
            )
        )
    return cases


def run_frontier_probe(probe_id: str) -> EvalCaseResult:
    """Execute one deterministic frontier probe."""
    runners: dict[str, Callable[[], tuple[bool, str]]] = {
        "sole_runtime": _probe_sole_runtime,
        "experience_admission": _probe_experience_admission,
        "trajectory_no_private_cot": _probe_trajectory_scrub,
        "candidate_govern_before_ingest": _probe_candidate_lifecycle,
        "two_axis_neural_budgets": _probe_two_axis,
        "active_learning_no_auto_promote": _probe_active_learning,
        "hypothesis_board_public": _probe_hypothesis_board,
        "capability_state_matrix": _probe_capability_state,
    }
    runner = runners.get(probe_id)
    if runner is None:
        return EvalCaseResult(
            f"frontier-{probe_id}",
            EvalOutcome.UNMEASURED,
            f"unknown frontier probe: {probe_id}",
            judgment_kind=JudgmentKind.DETERMINISTIC,
            measurement=MeasurementState.UNMEASURED,
        )
    try:
        ok, detail = runner()
    except Exception as exc:  # noqa: BLE001
        return EvalCaseResult(
            f"frontier-{probe_id}",
            EvalOutcome.ERROR,
            f"{type(exc).__name__}: {exc}",
            judgment_kind=JudgmentKind.DETERMINISTIC,
            measurement=MeasurementState.FAIL,
        )
    if ok:
        return EvalCaseResult(
            f"frontier-{probe_id}",
            EvalOutcome.PASSED,
            detail,
            judgment_kind=JudgmentKind.DETERMINISTIC,
            measurement=MeasurementState.PASS,
        )
    return EvalCaseResult(
        f"frontier-{probe_id}",
        EvalOutcome.FAILED,
        detail,
        judgment_kind=JudgmentKind.DETERMINISTIC,
        measurement=MeasurementState.FAIL,
    )


def run_frontier_reasoning_suite() -> EvalReport:
    """Convenience runner that does not require EvaluationHarness wiring."""
    results = [run_frontier_probe(c.params["probe_id"]) for c in frontier_reasoning_suite()]
    # Align case_ids from suite definitions.
    aligned: list[EvalCaseResult] = []
    for case, result in zip(frontier_reasoning_suite(), results, strict=True):
        aligned.append(
            EvalCaseResult(
                case.case_id,
                result.outcome,
                result.detail,
                judgment_kind=result.judgment_kind,
                measurement=result.measurement,
                component=case.component,
            )
        )
    summary = {
        "passed": sum(1 for r in aligned if r.outcome == EvalOutcome.PASSED),
        "failed": sum(1 for r in aligned if r.outcome == EvalOutcome.FAILED),
        "unmeasured": sum(1 for r in aligned if r.outcome == EvalOutcome.UNMEASURED),
        "error": sum(1 for r in aligned if r.outcome == EvalOutcome.ERROR),
        "total": len(aligned),
    }
    return EvalReport(
        suite_id=FRONTIER_SUITE_ID,
        name="frontier_reasoning",
        results=tuple(aligned),
        summary=summary,
        suite_version="1",
        component_scope=("cognition",),
        system_level=True,
    )


def run_frontier_feature_ablation(feature: str) -> AblationReport:
    feature = (feature or "").strip().lower()
    if feature not in FRONTIER_ABLATION_FEATURES:
        raise ValueError(
            f"Unknown frontier ablation feature: {feature}. "
            f"Expected one of {FRONTIER_ABLATION_FEATURES}"
        )
    with_on = _run_frontier_condition(feature, enabled=True)
    with_off = _run_frontier_condition(feature, enabled=False)
    delta = int(with_on.success) - int(with_off.success)
    return AblationReport(
        report_id=f"fr_abl_{uuid.uuid4().hex[:12]}",
        feature=feature,
        with_feature=with_on,
        without_feature=with_off,
        delta_success=delta,
    )


def run_all_frontier_ablations() -> list[AblationReport]:
    return [run_frontier_feature_ablation(f) for f in FRONTIER_ABLATION_FEATURES]


def frontier_ablation_public_bundle() -> dict[str, Any]:
    reports = run_all_frontier_ablations()
    return {
        "suite_id": FRONTIER_ABLATION_SUITE_ID,
        "ablations": [r.public_dict() for r in reports],
        "truth": {
            "feature_flag_is_not_ablation_result": True,
            "paired_with_without_required": True,
            "frontier_reasoning_ablations": True,
            "unmeasured_is_not_pass": True,
        },
    }


# --- probes ---


def _probe_sole_runtime() -> tuple[bool, str]:
    from Data.modules import cognition as cog

    ok = hasattr(cog, "CognitiveRuntime") and callable(cog.CognitiveRuntime)
    # Forbidden parallel runtime names must not exist as cognition exports.
    forbidden = ("CognitionV2", "FrontierRuntime", "ReasoningRuntime2")
    leaked = [n for n in forbidden if hasattr(cog, n)]
    return (ok and not leaked), f"CognitiveRuntime={ok} leaked={leaked}"


def _probe_experience_admission() -> tuple[bool, str]:
    from Data.modules.cognition.experience import ExperienceStore
    from Data.modules.cognition.task_model import TaskModelBuilder
    from Data.modules.cognition.types import CognitiveRunStatus, ReasoningStrategy

    store = ExperienceStore()
    task = TaskModelBuilder().build("hello")
    exp = store.build_from_run(
        task=task,
        status=CognitiveRunStatus.COMPLETED_UNVERIFIED,
        strategy=ReasoningStrategy.DIRECT,
        action_summaries=["RESPOND"],
        verification_status="UNMEASURED",
    )
    admitted = store.admit(exp)
    return (not admitted.admitted), f"admitted={admitted.admitted} reason={admitted.admission_reason}"


def _probe_trajectory_scrub() -> tuple[bool, str]:
    from Data.modules.cognition.trajectory_export import (
        build_trajectory_from_run_snapshot,
        scrub_private_fields,
    )

    cleaned = scrub_private_fields({"reasoning_content": "SECRET", "ok": True})
    if "reasoning_content" in cleaned or cleaned.get("ok") is not True:
        return False, "scrub_failed"
    traj = build_trajectory_from_run_snapshot(
        {
            "run_id": "r",
            "goal": "g",
            "status": "FAILED",
            "response_text": "x",
            "verification_passed": False,
            "thinking": "PRIVATE",
        }
    )
    blob = str(traj.public_dict())
    return ("PRIVATE" not in blob and traj.public_dict()["truth"]["no_private_cot"]), "scrub_ok"


def _probe_candidate_lifecycle() -> tuple[bool, str]:
    from Data.modules.training import CandidateTrainingLifecycle

    life = CandidateTrainingLifecycle()
    created = life.accept_export_bundle(
        {
            "sft_records": [
                {
                    "id": "t1",
                    "messages": [
                        {"role": "user", "content": "q"},
                        {"role": "assistant", "content": "a"},
                    ],
                    "labels": {"export_class": "verified_sft", "verification_status": "PASSED"},
                    "metadata": {"run_id": "r1", "auto_promote_forbidden": True},
                }
            ],
            "preference_seeds": [],
            "active_learning": [],
            "trajectories": [],
        }
    )
    cid = created[0].candidate_id
    try:
        life.mark_ingested(cid, operator="ops")
        return False, "ingest_allowed_before_govern"
    except ValueError:
        pass
    life.govern(cid, operator="ops")
    life.mark_ingested(cid, operator="ops")
    return True, "govern_then_ingest_ok"


def _probe_two_axis() -> tuple[bool, str]:
    from Data.modules.cognition.neural_compute import NeuralComputeBudget, neural_budget_for_mode
    from Data.modules.cognition.types import ReasoningMode

    budget = neural_budget_for_mode(ReasoningMode.DEEP)
    pub = budget.public_dict()
    ok = isinstance(budget, NeuralComputeBudget) and "native_effort" in pub
    return ok, f"native_effort={pub.get('native_effort')}"


def _probe_active_learning() -> tuple[bool, str]:
    from Data.modules.cognition.experience import ExperienceStore

    store = ExperienceStore()
    cand = store.record_active_learning_candidate(
        {"reason": "verification_failed", "kind": "failure", "run_id": "r"}
    )
    ok = bool(cand.get("auto_promote_forbidden")) and bool(
        cand.get("requires_human_or_policy_approval")
    )
    return ok, "auto_promote_forbidden"


def _probe_hypothesis_board() -> tuple[bool, str]:
    from Data.modules.cognition.hypotheses import HypothesisBoard

    board = HypothesisBoard()
    board.add("testable claim", prior_plausibility=0.4)
    pub = board.public_dict()
    ok = pub.get("truth", {}).get("hypothesis_board_is_public") or "items" in pub
    return bool(ok), "hypothesis_board_public"


def _probe_capability_state() -> tuple[bool, str]:
    from Data.modules.cognition.capability_state import (
        AxisState,
        CapabilityAxis,
        CapabilityState,
    )

    cs = CapabilityState(network=AxisState.DENIED)
    ok = cs.blocks(CapabilityAxis.NETWORK) and not cs.allows(CapabilityAxis.NETWORK)
    return ok, f"network={cs.network.value}"


# --- ablations ---


def _run_frontier_condition(feature: str, *, enabled: bool) -> AblationConditionResult:
    evidence: dict[str, Any] = {"feature": feature, "enabled": enabled}
    if feature == "belief":
        return _ablate_belief(enabled, evidence)
    if feature == "experience_learning":
        return _ablate_experience_learning(enabled, evidence)
    if feature == "trajectory_export":
        return _ablate_trajectory_export(enabled, evidence)
    if feature == "candidate_lifecycle":
        return _ablate_candidate_lifecycle(enabled, evidence)
    raise ValueError(feature)


def _ablate_belief(enabled: bool, evidence: dict[str, Any]) -> AblationConditionResult:
    from Data.modules.cognition import CognitiveRuntime

    runtime = CognitiveRuntime(
        enabled=True,
        shadow=True,
        belief_enabled=enabled,
        iterative=False,
        model_caller=lambda **k: "ok",
    )
    status = runtime.submit("What is 2+2?", run=False)
    state = runtime._require(status["run_id"])
    pub = state.public_status()
    evidence["belief_enabled"] = runtime.belief_enabled
    evidence["has_belief_counts"] = "belief_counts" in pub
    # When beliefs enabled, uncertainty comes from BeliefState; counts present.
    if enabled:
        ok = runtime.belief_enabled and isinstance(pub.get("belief_counts"), dict)
    else:
        ok = (not runtime.belief_enabled) and pub.get("uncertainty") is not None
    return AblationConditionResult(
        feature="belief",
        enabled=enabled,
        success=ok,
        detail=f"belief_enabled={enabled}",
        raw_evidence=evidence,
    )


def _ablate_experience_learning(
    enabled: bool, evidence: dict[str, Any]
) -> AblationConditionResult:
    from Data.modules.cognition import CognitiveRuntime
    from Data.modules.cognition.experience import ExperienceStore
    from Data.modules.cognition.meta_controller import MetaDecision
    from Data.modules.cognition.types import CognitiveBudgets, ReasoningMode, ReasoningStrategy

    store = ExperienceStore()
    runtime = CognitiveRuntime(
        enabled=True,
        shadow=False,
        iterative=False,
        experience_learning=enabled,
        experience_store=store,
        model_caller=lambda **k: "done",
    )
    status = runtime.submit("Fix reconnect race with tests", run=False)
    state = runtime._require(status["run_id"])
    state.decision = MetaDecision(
        mode=ReasoningMode.STANDARD,
        strategy=ReasoningStrategy.CODING_REPAIR,
        budgets=CognitiveBudgets(),
        value_scores={},
        notes=(),
    )
    state.verification_passed = True
    state.response_text = "fixed"
    runtime._finalize(state)
    evidence["experience_present"] = state.experience is not None
    evidence["admitted_count"] = len(store.list_admitted())
    if enabled:
        ok = state.experience is not None and bool(state.experience.get("admitted"))
    else:
        ok = state.experience is None and len(store.list_admitted()) == 0
    return AblationConditionResult(
        feature="experience_learning",
        enabled=enabled,
        success=ok,
        detail=f"experience_learning={enabled}",
        raw_evidence=evidence,
    )


def _ablate_trajectory_export(
    enabled: bool, evidence: dict[str, Any]
) -> AblationConditionResult:
    """Ablation: recording trajectories only when experience learning path is on."""
    from Data.modules.cognition import CognitiveRuntime
    from Data.modules.cognition.experience import ExperienceStore
    from Data.modules.cognition.meta_controller import MetaDecision
    from Data.modules.cognition.types import CognitiveBudgets, ReasoningMode, ReasoningStrategy

    store = ExperienceStore()
    runtime = CognitiveRuntime(
        enabled=True,
        shadow=False,
        iterative=False,
        experience_learning=enabled,
        experience_store=store,
        model_caller=lambda **k: "done",
    )
    status = runtime.submit("Explain gravity briefly", run=False)
    state = runtime._require(status["run_id"])
    state.decision = MetaDecision(
        mode=ReasoningMode.FAST,
        strategy=ReasoningStrategy.DIRECT,
        budgets=CognitiveBudgets(),
        value_scores={},
        notes=(),
    )
    state.verification_passed = True
    state.response_text = "g = GM/r^2"
    runtime._finalize(state)
    traj_n = len(store.trajectory_bridge.list_trajectories())
    evidence["trajectory_count"] = traj_n
    if enabled:
        ok = traj_n >= 1
    else:
        ok = traj_n == 0
    return AblationConditionResult(
        feature="trajectory_export",
        enabled=enabled,
        success=ok,
        detail=f"trajectories={traj_n}",
        raw_evidence=evidence,
    )


def _ablate_candidate_lifecycle(
    enabled: bool, evidence: dict[str, Any]
) -> AblationConditionResult:
    """Ablation: with lifecycle, export sync creates pending; without, no registry."""
    from Data.modules.cognition import CognitiveRuntime
    from Data.modules.cognition.experience import ExperienceStore
    from Data.modules.cognition.meta_controller import MetaDecision
    from Data.modules.cognition.types import CognitiveBudgets, ReasoningMode, ReasoningStrategy
    from Data.modules.training import CandidateTrainingLifecycle

    store = ExperienceStore()
    runtime = CognitiveRuntime(
        enabled=True,
        shadow=False,
        iterative=False,
        experience_learning=True,
        experience_store=store,
        model_caller=lambda **k: "done",
    )
    status = runtime.submit("Fix reconnect race with tests", run=False)
    state = runtime._require(status["run_id"])
    state.decision = MetaDecision(
        mode=ReasoningMode.DEEP,
        strategy=ReasoningStrategy.CODING_REPAIR,
        budgets=CognitiveBudgets(),
        value_scores={},
        notes=(),
    )
    state.verification_passed = True
    state.response_text = "locked reconnect"
    runtime._finalize(state)

    if enabled:
        life = CandidateTrainingLifecycle()
        out = runtime.sync_training_candidates(life)
        evidence["created"] = len(out.get("created") or [])
        evidence["summary"] = out.get("summary")
        ok = evidence["created"] >= 1 and out["truth"]["wired_from_cognition_trajectories"]
    else:
        # Without lifecycle, export still works but nothing is registered.
        bundle = runtime.export_training_bundle()
        evidence["sft_record_count"] = bundle.get("sft_record_count")
        ok = int(bundle.get("sft_record_count") or 0) >= 1
    return AblationConditionResult(
        feature="candidate_lifecycle",
        enabled=enabled,
        success=ok,
        detail=f"lifecycle_enabled={enabled}",
        raw_evidence=evidence,
    )
