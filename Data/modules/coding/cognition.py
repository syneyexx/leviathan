"""Coding Cognitive Strategy — specialized software cognition under One Brain.

Not a second CognitiveRuntime. Not a private RAG/model/prompt identity.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from Data.modules.cognition.domain_strategy import (
    DomainHypothesis,
    DomainUnderstandResult,
)
from Data.modules.cognition.task_model import TaskModel
from Data.modules.cognition.types import ReasoningStrategy

from .planner import mission_from_text
from .types import Mission


class CodingTaskType(str, Enum):
    ANSWER_CODE_QUESTION = "ANSWER_CODE_QUESTION"
    INVESTIGATE = "INVESTIGATE"
    DEBUG = "DEBUG"
    FIX = "FIX"
    IMPLEMENT_FEATURE = "IMPLEMENT_FEATURE"
    REFACTOR = "REFACTOR"
    WRITE_TESTS = "WRITE_TESTS"
    REVIEW = "REVIEW"
    MIGRATE = "MIGRATE"
    SCAFFOLD = "SCAFFOLD"
    PERFORMANCE = "PERFORMANCE"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    ARCHITECTURE_CHANGE = "ARCHITECTURE_CHANGE"
    GENERIC = "GENERIC"


class CodingPhase(str, Enum):
    UNDERSTANDING = "UNDERSTANDING"
    RETRIEVING_CONTEXT = "RETRIEVING_CONTEXT"
    INVESTIGATING = "INVESTIGATING"
    PLANNING = "PLANNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"


@dataclass
class CodingPlan:
    goal: str
    task_type: str
    assumptions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    files_to_inspect: list[str] = field(default_factory=list)
    symbols_to_inspect: list[str] = field(default_factory=list)
    hypotheses: list[DomainHypothesis] = field(default_factory=list)
    affected_files: list[str] = field(default_factory=list)
    planned_changes: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    expected_tests: list[str] = field(default_factory=list)
    expected_checks: list[str] = field(default_factory=list)
    risk: str = "LOW"
    rollback_strategy: str = "revert session patches via workspace transaction when available"
    public_bullets: list[str] = field(default_factory=list)
    plan_delta_reason: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "taskType": self.task_type,
            "assumptions": list(self.assumptions),
            "constraints": list(self.constraints),
            "invariants": list(self.invariants),
            "filesToInspect": list(self.files_to_inspect),
            "symbolsToInspect": list(self.symbols_to_inspect),
            "hypotheses": [h.public_dict() for h in self.hypotheses],
            "affectedFiles": list(self.affected_files),
            "plannedChanges": list(self.planned_changes),
            "dependencies": list(self.dependencies),
            "acceptanceCriteria": list(self.acceptance_criteria),
            "expectedTests": list(self.expected_tests),
            "expectedChecks": list(self.expected_checks),
            "risk": self.risk,
            "rollbackStrategy": self.rollback_strategy,
            "publicBullets": list(self.public_bullets),
            "planDeltaReason": self.plan_delta_reason,
        }


_PATH_RE = re.compile(
    r"(?:[\w.-]+/)+[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|toml|json|md|yml|yaml|cfg|ini)"
)
_SYMBOL_RE = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}|(?:[a-z_][a-z0-9_]{2,}))\b")


def classify_coding_task(text: str, mission: Mission | None = None) -> CodingTaskType:
    raw = (text or "").strip()
    lower = raw.lower()
    mission = mission or mission_from_text(raw)

    if any(tok in lower for tok in ("security review", "owasp", "cve", "xss", "sqli")):
        return CodingTaskType.SECURITY_REVIEW
    if any(tok in lower for tok in ("architecture", "redesign module", "split package")):
        return CodingTaskType.ARCHITECTURE_CHANGE
    if any(tok in lower for tok in ("migrate", "migration", "upgrade from")):
        return CodingTaskType.MIGRATE
    if any(tok in lower for tok in ("performance", "slow", "latency", "optimize")):
        return CodingTaskType.PERFORMANCE
    if any(tok in lower for tok in ("scaffold", "bootstrap", "create project", "new package")):
        return CodingTaskType.SCAFFOLD
    if any(tok in lower for tok in ("review", "code review", "look over")):
        return CodingTaskType.REVIEW
    if any(tok in lower for tok in ("write test", "add test", "unit test", "pytest", "coverage")):
        return CodingTaskType.WRITE_TESTS
    if any(tok in lower for tok in ("refactor", "rename", "extract function", "cleanup")):
        return CodingTaskType.REFACTOR
    if any(tok in lower for tok in ("implement", "feature", "add support", "add endpoint", "build")):
        return CodingTaskType.IMPLEMENT_FEATURE
    if any(tok in lower for tok in ("debug", "reproduce", "stacktrace", "traceback", "bisect")):
        return CodingTaskType.DEBUG
    if mission == Mission.FIX or any(
        tok in lower for tok in ("fix", "bug", "broken", "fails", "error", "regression")
    ):
        return CodingTaskType.FIX
    if any(tok in lower for tok in ("investigate", "why does", "root cause", "where is the bug")):
        return CodingTaskType.INVESTIGATE
    if mission == Mission.REVIEW:
        return CodingTaskType.REVIEW
    if mission == Mission.TEST:
        return CodingTaskType.WRITE_TESTS
    if mission == Mission.SCAFFOLD:
        return CodingTaskType.SCAFFOLD
    # Question-like without mutation verbs.
    if ("?" in raw or lower.startswith(("where ", "what ", "how ", "which ", "wanneer ", "waar "))) and not any(
        tok in lower for tok in ("fix", "implement", "add", "write", "patch", "create", "delete")
    ):
        return CodingTaskType.ANSWER_CODE_QUESTION
    return CodingTaskType.GENERIC


def extract_paths(text: str) -> list[str]:
    return list(dict.fromkeys(_PATH_RE.findall(text or "")))[:20]


def extract_symbols(text: str) -> list[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "into",
        "file",
        "code",
        "test",
        "tests",
        "please",
        "fix",
        "implement",
        "where",
        "what",
        "when",
        "how",
        "should",
        "would",
        "could",
        "must",
        "need",
        "make",
        "update",
        "change",
        "function",
        "class",
        "module",
        "agent",
        "coding",
        "leviathan",
    }
    found: list[str] = []
    for match in _SYMBOL_RE.finditer(text or ""):
        sym = match.group(1)
        if sym.lower() in stop:
            continue
        if len(sym) < 3:
            continue
        if sym not in found:
            found.append(sym)
        if len(found) >= 24:
            break
    return found


class CodingCognitiveStrategy:
    """Domain strategy for software engineering tasks."""

    domain = "coding"

    def understand(self, task: TaskModel | None = None, *, text: str | None = None) -> DomainUnderstandResult:
        goal = (text or (task.goal if task is not None else "") or "").strip()
        mission = mission_from_text(goal)
        task_type = classify_coding_task(goal, mission)
        paths = extract_paths(goal)
        symbols = extract_symbols(goal)

        acceptance: list[str] = []
        required_evidence: list[str] = []
        constraints = [
            "workspace confinement",
            "read-before-write",
            "ExecutionGateway for side effects",
            "approvals for gated writes",
            "no unrestricted shell",
        ]
        invariants = ["preserve unrelated operator changes", "prefer minimal diffs"]
        risk = "LOW"
        ambiguities: list[str] = []

        if task_type == CodingTaskType.ANSWER_CODE_QUESTION:
            acceptance = [
                "relevant files or symbols identified from repository state",
                "answer references inspected evidence",
                "no writes performed",
            ]
            required_evidence = ["inspection_or_search_observation"]
        elif task_type in {CodingTaskType.FIX, CodingTaskType.DEBUG}:
            acceptance = [
                "failure understood or reproduction attempted",
                "root cause hypothesis supported or weakened by evidence",
                "minimal patch applied when fixing",
                "targeted verification executed when tooling available",
            ]
            required_evidence = ["coding.run_tests_or_equivalent", "patch_observation"]
            risk = "MEDIUM"
            ambiguities.append("reproduction path may be unavailable")
        elif task_type in {
            CodingTaskType.IMPLEMENT_FEATURE,
            CodingTaskType.REFACTOR,
            CodingTaskType.MIGRATE,
            CodingTaskType.ARCHITECTURE_CHANGE,
        }:
            acceptance = [
                "requested behavior addressed",
                "required files changed intentionally",
                "unexpected scope avoided",
                "relevant checks executed",
                "verification evidence exists",
            ]
            required_evidence = ["patch_observation", "verification_report"]
            risk = "HIGH" if task_type == CodingTaskType.ARCHITECTURE_CHANGE else "MEDIUM"
        elif task_type in {CodingTaskType.WRITE_TESTS, CodingTaskType.REVIEW, CodingTaskType.SECURITY_REVIEW}:
            acceptance = [
                "review or tests cover the requested target",
                "findings or test results recorded as evidence",
            ]
            required_evidence = ["review_or_test_observation"]
            risk = "MEDIUM" if task_type == CodingTaskType.SECURITY_REVIEW else "LOW"
        elif task_type == CodingTaskType.SCAFFOLD:
            acceptance = ["requested scaffold paths created", "no forbidden path writes"]
            required_evidence = ["write_observation"]
        else:
            acceptance = ["goal addressed with honest status", "side effects only via gateway"]
            required_evidence = ["capability_observation_if_mutated"]

        if not paths and not symbols and task_type != CodingTaskType.SCAFFOLD:
            ambiguities.append("no explicit file/symbol hints in request")

        return DomainUnderstandResult(
            task_type=task_type.value,
            goal=goal,
            acceptance_criteria=acceptance,
            constraints=constraints,
            invariants=invariants,
            risk=risk,
            ambiguities=ambiguities,
            required_evidence=required_evidence,
            metadata={
                "mission": mission.value,
                "paths": paths,
                "symbols": symbols,
                "writes_expected": task_type
                not in {
                    CodingTaskType.ANSWER_CODE_QUESTION,
                    CodingTaskType.INVESTIGATE,
                    CodingTaskType.REVIEW,
                    CodingTaskType.SECURITY_REVIEW,
                },
            },
        )

    def enrich_context_request(self, task: TaskModel | None, understand: DomainUnderstandResult) -> dict[str, Any]:
        meta = understand.metadata or {}
        paths = list(meta.get("paths") or [])
        symbols = list(meta.get("symbols") or [])
        queries = [understand.goal]
        queries.extend(symbols[:6])
        queries.extend(paths[:4])
        if understand.task_type in {CodingTaskType.FIX.value, CodingTaskType.DEBUG.value}:
            queries.append(f"{understand.goal} failure root cause")
        return {
            "domain": self.domain,
            "role": "coding",
            "queries": [q for q in queries if q],
            "symbols": symbols,
            "files": paths,
            "entities": symbols[:8],
            "include_evidence": True,
            "include_experience": True,
            "include_capabilities": True,
            "token_budget": 1600 if understand.risk in {"MEDIUM", "HIGH"} else 1000,
            "result_limits": {"knowledge": 6, "memory": 3, "evidence": 3, "experience": 3, "capabilities": 14},
            "task_semantics": {
                "taskType": understand.task_type,
                "acceptanceCriteria": list(understand.acceptance_criteria),
                "risk": understand.risk,
            },
        }

    def plan(
        self,
        task: TaskModel | None,
        understand: DomainUnderstandResult,
        *,
        observations: list[dict[str, Any]] | None = None,
        prior_plan: CodingPlan | dict[str, Any] | None = None,
    ) -> CodingPlan:
        meta = understand.metadata or {}
        paths = list(meta.get("paths") or [])
        symbols = list(meta.get("symbols") or [])
        bullets = self._public_bullets(understand)

        if prior_plan is not None:
            return self._plan_delta(prior_plan, understand, observations or [])

        hypotheses: list[DomainHypothesis] = []
        if understand.task_type in {CodingTaskType.FIX.value, CodingTaskType.DEBUG.value}:
            hypotheses.append(
                DomainHypothesis(
                    id=f"h_{uuid.uuid4().hex[:8]}",
                    statement="Reported failure is localized to mentioned symbols/files",
                    test_action="workspace.search + file.read around mentioned symbols",
                    status="OPEN",
                )
            )
            hypotheses.append(
                DomainHypothesis(
                    id=f"h_{uuid.uuid4().hex[:8]}",
                    statement="Failure is caused by missing/incorrect test or assertion wiring",
                    test_action="locate related tests and inspect expectations",
                    status="OPEN",
                )
            )

        expected_checks: list[str] = []
        expected_tests: list[str] = []
        if understand.task_type in {
            CodingTaskType.FIX.value,
            CodingTaskType.DEBUG.value,
            CodingTaskType.WRITE_TESTS.value,
            CodingTaskType.IMPLEMENT_FEATURE.value,
        }:
            expected_checks.append("targeted_tests")
            expected_tests.append("coding.run_tests")
        if understand.risk in {"MEDIUM", "HIGH"}:
            expected_checks.extend(["lint_if_available", "typecheck_if_available"])

        planned_changes: list[str] = []
        if meta.get("writes_expected"):
            planned_changes.append("apply minimal patch to affected files after inspection")

        return CodingPlan(
            goal=understand.goal,
            task_type=understand.task_type,
            assumptions=["repository tooling discovery will determine available checks"],
            constraints=list(understand.constraints),
            invariants=list(understand.invariants),
            files_to_inspect=paths,
            symbols_to_inspect=symbols,
            hypotheses=hypotheses,
            affected_files=list(paths),
            planned_changes=planned_changes,
            acceptance_criteria=list(understand.acceptance_criteria),
            expected_tests=expected_tests,
            expected_checks=expected_checks,
            risk=understand.risk,
            public_bullets=bullets,
        )

    def propose_actions(
        self,
        task: TaskModel | None,
        understand: DomainUnderstandResult,
        plan: CodingPlan | dict[str, Any],
        *,
        phase: str | None = None,
    ) -> list[dict[str, Any]]:
        phase_name = (phase or CodingPhase.INVESTIGATING.value).upper()
        actions: list[dict[str, Any]] = []
        if phase_name in {CodingPhase.UNDERSTANDING.value, CodingPhase.RETRIEVING_CONTEXT.value}:
            actions.append({"kind": "RETRIEVE_BRAIN", "reason": "one_brain_context"})
            actions.append({"kind": "SEARCH_WORKSPACE", "reason": "locate_targets"})
        elif phase_name == CodingPhase.INVESTIGATING.value:
            actions.append({"kind": "READ_FILES", "reason": "inspect_before_edit"})
            if understand.task_type in {CodingTaskType.FIX.value, CodingTaskType.DEBUG.value}:
                actions.append({"kind": "FORM_HYPOTHESES", "reason": "debug_loop"})
        elif phase_name == CodingPhase.IMPLEMENTING.value:
            actions.append({"kind": "PATCH", "reason": "minimal_change"})
        elif phase_name in {CodingPhase.TESTING.value, CodingPhase.VERIFYING.value}:
            actions.append({"kind": "RUN_CHECKS", "reason": "adaptive_verification"})
        elif phase_name == CodingPhase.REPAIRING.value:
            actions.append({"kind": "CLASSIFY_FAILURE", "reason": "repair_loop"})
            actions.append({"kind": "MINIMAL_REPAIR", "reason": "information_gain"})
        _ = task, plan
        return actions

    def observe(self, observation: dict[str, Any], *, state: dict[str, Any]) -> dict[str, Any]:
        updated = dict(state)
        obs_list = list(updated.get("observations") or [])
        obs_list.append(observation)
        updated["observations"] = obs_list[-50:]
        hyp_id = observation.get("hypothesis_id")
        verdict = str(observation.get("hypothesis_verdict") or "").upper()
        if hyp_id and verdict:
            hyps = list(updated.get("hypotheses") or [])
            for hyp in hyps:
                if str(hyp.get("id")) == str(hyp_id):
                    hyp["status"] = verdict
                    if verdict == "SUPPORTED":
                        hyp.setdefault("supporting", []).append(str(observation.get("summary") or "support"))
                    elif verdict in {"WEAKENED", "REJECTED"}:
                        hyp.setdefault("contradicting", []).append(str(observation.get("summary") or "contradict"))
            updated["hypotheses"] = hyps
        return updated

    def evaluate(self, *, state: dict[str, Any], understand: DomainUnderstandResult) -> dict[str, Any]:
        criteria = list(understand.acceptance_criteria)
        met: list[str] = []
        unmet: list[str] = []
        writes = int(state.get("completed_writes") or 0)
        tests = int(state.get("completed_tests") or 0)
        reads = int(state.get("reads") or 0)
        cancelled = bool(state.get("cancelled"))
        budget_exhausted = bool(state.get("budget_exhausted"))
        verification_passed = bool(state.get("verification_passed"))
        verification_unavailable = bool(state.get("verification_unavailable"))

        for criterion in criteria:
            cl = criterion.lower()
            ok = False
            if "no writes" in cl:
                ok = writes == 0
            elif "files or symbols" in cl or "identified" in cl:
                ok = reads > 0 or bool(state.get("search_hits"))
            elif "patch" in cl or "files changed" in cl or "scaffold" in cl:
                ok = writes > 0
            elif "verification" in cl or "checks executed" in cl or "tests" in cl:
                ok = tests > 0 or verification_passed
            elif "honest" in cl:
                ok = True
            else:
                ok = bool(state.get("goal_addressed"))
            (met if ok else unmet).append(criterion)

        if cancelled:
            status = "CANCELLED"
        elif budget_exhausted and unmet:
            status = "RESOURCE_EXHAUSTED"
        elif unmet and writes > 0 and not verification_passed:
            status = "UNVERIFIED"
        elif unmet:
            status = "PARTIAL"
        elif writes > 0 and verification_unavailable:
            status = "UNVERIFIED"
        else:
            status = "COMPLETED"

        return {
            "status": status,
            "met": met,
            "unmet": unmet,
            "acceptanceCriteria": criteria,
        }

    def verify(self, *, state: dict[str, Any], understand: DomainUnderstandResult) -> dict[str, Any]:
        evaluation = self.evaluate(state=state, understand=understand)
        return {
            **evaluation,
            "requiredEvidence": list(understand.required_evidence),
            "truth": {
                "max_rounds_is_not_success": True,
                "unavailable_is_not_passed": True,
                "completion_requires_acceptance": True,
            },
        }

    def completion_requirements(self, understand: DomainUnderstandResult) -> list[str]:
        return list(understand.acceptance_criteria)

    def preferred_strategy(self, understand: DomainUnderstandResult) -> ReasoningStrategy:
        if understand.task_type in {CodingTaskType.FIX.value, CodingTaskType.DEBUG.value}:
            return ReasoningStrategy.CODING_REPAIR
        if understand.task_type == CodingTaskType.ANSWER_CODE_QUESTION:
            return ReasoningStrategy.RETRIEVE_THEN_ANSWER
        if understand.risk == "HIGH":
            return ReasoningStrategy.HIGH_RISK_VERIFY
        return ReasoningStrategy.PLAN_EXECUTE_VERIFY

    def initial_phase(self, understand: DomainUnderstandResult) -> CodingPhase:
        if understand.task_type == CodingTaskType.ANSWER_CODE_QUESTION:
            return CodingPhase.INVESTIGATING
        return CodingPhase.UNDERSTANDING

    def _public_bullets(self, understand: DomainUnderstandResult) -> list[str]:
        bullets = [
            f"Understand: {understand.task_type.replace('_', ' ').title()}",
            "Inspect repository targets before any edit",
        ]
        if understand.metadata.get("writes_expected"):
            bullets.append("Apply minimal patch and verify with available tooling")
        else:
            bullets.append("Answer from inspected evidence without writes")
        return bullets[:3]

    def _plan_delta(
        self,
        prior_plan: CodingPlan | dict[str, Any],
        understand: DomainUnderstandResult,
        observations: list[dict[str, Any]],
    ) -> CodingPlan:
        plan = self._coerce_plan(prior_plan, understand)

        invalid_core = any(bool(o.get("invalidates_plan")) for o in observations)
        stale_file = any("stale" in str(o.get("error") or "").lower() for o in observations)
        if invalid_core:
            fresh = self.plan(None, understand, observations=None, prior_plan=None)
            fresh.plan_delta_reason = "core_assumption_invalid"
            return fresh
        if stale_file:
            plan.plan_delta_reason = "stale_file_refresh"
            plan.planned_changes = [c for c in plan.planned_changes if "stale" not in c.lower()]
            plan.planned_changes.append("refresh file hash and rebase patch")
            return plan
        failed_step = next((o for o in observations if o.get("failed_step")), None)
        if failed_step:
            plan.plan_delta_reason = "repair_step"
            step = str(failed_step.get("failed_step"))
            plan.planned_changes.append(f"repair step: {step}")
            return plan
        plan.plan_delta_reason = "plan_remains_valid"
        return plan

    def _coerce_plan(
        self,
        prior_plan: CodingPlan | dict[str, Any],
        understand: DomainUnderstandResult,
    ) -> CodingPlan:
        if isinstance(prior_plan, CodingPlan):
            return CodingPlan(
                goal=prior_plan.goal,
                task_type=prior_plan.task_type,
                assumptions=list(prior_plan.assumptions),
                constraints=list(prior_plan.constraints),
                invariants=list(prior_plan.invariants),
                files_to_inspect=list(prior_plan.files_to_inspect),
                symbols_to_inspect=list(prior_plan.symbols_to_inspect),
                hypotheses=list(prior_plan.hypotheses),
                affected_files=list(prior_plan.affected_files),
                planned_changes=list(prior_plan.planned_changes),
                dependencies=list(prior_plan.dependencies),
                acceptance_criteria=list(prior_plan.acceptance_criteria),
                expected_tests=list(prior_plan.expected_tests),
                expected_checks=list(prior_plan.expected_checks),
                risk=prior_plan.risk,
                rollback_strategy=prior_plan.rollback_strategy,
                public_bullets=list(prior_plan.public_bullets),
                plan_delta_reason=prior_plan.plan_delta_reason,
            )
        hyps = [
            DomainHypothesis(
                id=str(h.get("id") or uuid.uuid4().hex[:8]),
                statement=str(h.get("statement") or ""),
                supporting=list(h.get("supporting") or h.get("supportingObservations") or []),
                contradicting=list(h.get("contradicting") or h.get("contradictingObservations") or []),
                test_action=str(h.get("testAction") or h.get("test_action") or ""),
                status=str(h.get("status") or "OPEN"),
            )
            for h in (prior_plan.get("hypotheses") or [])
        ]
        return CodingPlan(
            goal=str(prior_plan.get("goal") or understand.goal),
            task_type=str(prior_plan.get("taskType") or prior_plan.get("task_type") or understand.task_type),
            assumptions=list(prior_plan.get("assumptions") or []),
            constraints=list(prior_plan.get("constraints") or understand.constraints),
            invariants=list(prior_plan.get("invariants") or understand.invariants),
            files_to_inspect=list(prior_plan.get("filesToInspect") or prior_plan.get("files_to_inspect") or []),
            symbols_to_inspect=list(prior_plan.get("symbolsToInspect") or prior_plan.get("symbols_to_inspect") or []),
            hypotheses=hyps,
            affected_files=list(prior_plan.get("affectedFiles") or prior_plan.get("affected_files") or []),
            planned_changes=list(prior_plan.get("plannedChanges") or prior_plan.get("planned_changes") or []),
            dependencies=list(prior_plan.get("dependencies") or []),
            acceptance_criteria=list(
                prior_plan.get("acceptanceCriteria")
                or prior_plan.get("acceptance_criteria")
                or understand.acceptance_criteria
            ),
            expected_tests=list(prior_plan.get("expectedTests") or prior_plan.get("expected_tests") or []),
            expected_checks=list(prior_plan.get("expectedChecks") or prior_plan.get("expected_checks") or []),
            risk=str(prior_plan.get("risk") or understand.risk),
            rollback_strategy=str(
                prior_plan.get("rollbackStrategy")
                or prior_plan.get("rollback_strategy")
                or "revert session patches via workspace transaction when available"
            ),
            public_bullets=list(prior_plan.get("publicBullets") or prior_plan.get("public_bullets") or []),
            plan_delta_reason=prior_plan.get("planDeltaReason") or prior_plan.get("plan_delta_reason"),
        )
