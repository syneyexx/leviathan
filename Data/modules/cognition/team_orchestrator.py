"""TEAM orchestrator — quality-driven follow-up graphs over existing agents/jobs.

Uses MultiAgentCoordinator for DAG execution (acyclic). Iterative collaboration
is modeled as successive graph revisions / scheduled follow-up DAGs — never a
dependency cycle forced into the DAG executor.

Only this authorized orchestration layer schedules child work. Agents must not
recursively create unbounded teams.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from Data.modules.verification.quality_contract import (
    AcceptanceOutcome,
    AcceptanceRecord,
    CriterionApplicability,
    CriterionVerdict,
    CriterionVerdictStatus,
    EvidenceClass,
    QualityContract,
    aggregate_acceptance,
    criterion_progress,
    invalidate_verdicts_for_revision,
)

from .team_strategy import (
    LIGHTWEIGHT_CATEGORIES,
    NON_SUCCESS_ACTIVE,
    TERMINAL_TEAM_STATUSES,
    TeamAssignment,
    TeamBlocker,
    TeamExecutionPolicy,
    TeamRole,
    TeamRunStatus,
    TeamSpecialistResult,
    assert_transition,
    build_default_contract_for_request,
    new_assignment_id,
    new_blocker_id,
    select_roles_for_task,
)
from .team_task_profile import TeamTaskProfile, build_team_task_profile

# External live-price / earnings style claims — require evidence on any category.
_MATERIAL_EXTERNAL_CLAIM = re.compile(
    r"(?i)\b("
    r"current price|huidige prijs|\$\s?\d|€\s?\d|"
    r"trading live real.?money|live real-money|"
    r"earnings (?:were|are|of)|kwartaalresultaten"
    r")\b"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TeamProgressDelta:
    iteration: int
    criteria_satisfied_before: int
    criteria_satisfied_after: int
    new_evidence_ids: list[str] = field(default_factory=list)
    new_questions: list[str] = field(default_factory=list)
    repaired_artifacts: list[str] = field(default_factory=list)
    meaningful: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "criteria_satisfied_before": self.criteria_satisfied_before,
            "criteria_satisfied_after": self.criteria_satisfied_after,
            "new_evidence_ids": list(self.new_evidence_ids),
            "new_questions": list(self.new_questions),
            "repaired_artifacts": list(self.repaired_artifacts),
            "meaningful": self.meaningful,
            "truth": {
                "token_generation_is_not_progress": True,
                "agent_agreement_is_not_progress": True,
            },
        }


@dataclass
class TeamRunState:
    run_id: str
    status: TeamRunStatus
    contract: QualityContract
    policy: TeamExecutionPolicy
    artifact_revision: str
    graph_revision: int = 1
    iteration: int = 0
    assignments: list[TeamAssignment] = field(default_factory=list)
    verdicts: list[CriterionVerdict] = field(default_factory=list)
    acceptance: AcceptanceRecord | None = None
    blockers: list[TeamBlocker] = field(default_factory=list)
    progress_deltas: list[TeamProgressDelta] = field(default_factory=list)
    activity: list[dict[str, Any]] = field(default_factory=list)
    provisional_artifact: dict[str, Any] | None = None
    final_artifact: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""
    started_at: float = 0.0
    no_progress_streak: int = 0
    cancelled: bool = False
    pause_requested: bool = False
    superseded_graph_revisions: set[int] = field(default_factory=set)
    events: list[dict[str, Any]] = field(default_factory=list)
    event_seq: int = 0
    task_profile: dict[str, Any] | None = None
    request_text: str = ""
    last_progress_fingerprint: str = ""
    progress_reasons: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        progress = criterion_progress(
            self.contract,
            self.verdicts,
            artifact_revision=self.artifact_revision,
        )
        quality_label = None
        if self.status == TeamRunStatus.COMPLETED:
            quality_label = "accepted"
        elif self.status == TeamRunStatus.BLOCKED:
            quality_label = "blocked"
        elif self.status in {
            TeamRunStatus.WAITING_FOR_INPUT,
            TeamRunStatus.WAITING_FOR_RESOURCE,
        }:
            quality_label = self.status.value
        elif self.status == TeamRunStatus.REVISING:
            quality_label = "revising"
        elif self.status in {TeamRunStatus.RUNNING, TeamRunStatus.VERIFYING, TeamRunStatus.PLANNING}:
            quality_label = "running"
        elif self.status in {TeamRunStatus.FAILED, TeamRunStatus.CANCELLED}:
            quality_label = self.status.value
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "quality_label": quality_label,
            "contract": self.contract.public_dict(),
            "policy": self.policy.public_dict(),
            "artifact_revision": self.artifact_revision,
            "graph_revision": self.graph_revision,
            "iteration": self.iteration,
            "assignments": [a.public_dict() for a in self.assignments],
            "verdicts": [v.public_dict() for v in self.verdicts if v.status.value != "stale"],
            "acceptance": self.acceptance.public_dict() if self.acceptance else None,
            "blockers": [b.public_dict() for b in self.blockers],
            "progress": progress,
            "activity": list(self.activity[-50:]),
            "provisional_artifact": self.provisional_artifact,
            "final_artifact": self.final_artifact,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "no_progress_streak": self.no_progress_streak,
            "task_profile": dict(self.task_profile) if self.task_profile else None,
            "progress_reasons": list(self.progress_reasons[-20:]),
            "truth": {
                "completed_means_quality_accepted": True,
                "blocked_paused_cancelled_are_not_success": True,
                "open_ended_iteration_count": True,
                "team_is_not_direct": True,
            },
        }

    def emit(self, kind: str, summary: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.event_seq += 1
        event = {
            "event_id": f"evt:{self.run_id}:{self.event_seq}",
            "seq": self.event_seq,
            "run_id": self.run_id,
            "schema_version": 1,
            "kind": kind,
            "summary": summary,
            "payload": dict(payload or {}),
            "artifact_revision": self.artifact_revision,
            "graph_revision": self.graph_revision,
            "contract_version": self.contract.version,
            "ts": _utc_now(),
        }
        self.events.append(event)
        self.activity.append({"kind": kind, "summary": summary, "seq": self.event_seq})
        return event


SpecialistExecutor = Callable[[TeamAssignment, TeamRunState], dict[str, Any]]


class TeamOrchestrator:
    """Quality-directed collaboration over canonical agents + verification."""

    def __init__(
        self,
        *,
        specialist_executor: SpecialistExecutor | None = None,
        quality_store: Any | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._executor = specialist_executor or self._default_fixture_executor
        self.quality_store = quality_store
        self._clock = clock or time.monotonic
        self._runs: dict[str, TeamRunState] = {}

    def get(self, run_id: str) -> TeamRunState | None:
        return self._runs.get(run_id)

    def start(
        self,
        *,
        request_text: str,
        run_id: str | None = None,
        request_ref: str | None = None,
        task_category: str = "general",
        requires_research: bool = False,
        requires_coding: bool = False,
        requires_tools: bool = False,
        policy: TeamExecutionPolicy | None = None,
        contract: QualityContract | None = None,
        parent_capabilities: Sequence[str] | None = None,
        artifact_revision: str | None = None,
        profile: TeamTaskProfile | None = None,
    ) -> TeamRunState:
        rid = run_id or f"team:{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        resolved_profile = profile
        if resolved_profile is None and contract is None:
            # Prefer explicit category flags from callers; otherwise profile the request.
            if task_category == "general" and not requires_research and not requires_coding:
                resolved_profile = build_team_task_profile(request_text)
            elif task_category and task_category != "general":
                resolved_profile = TeamTaskProfile(
                    category=task_category,
                    answer_kind="caller_specified",
                    requires_external_research=requires_research,
                    requires_code_execution=requires_coding,
                    requires_tools=requires_tools,
                    lightweight=task_category in LIGHTWEIGHT_CATEGORIES,
                    verification_intensity=(
                        "light" if task_category in LIGHTWEIGHT_CATEGORIES else "standard"
                    ),
                )
        effective_category = (
            resolved_profile.category if resolved_profile is not None else task_category
        )
        qc = contract or build_default_contract_for_request(
            run_id=rid,
            request_ref=request_ref or rid,
            request_text=request_text,
            task_category=effective_category,
            requires_research=requires_research
            or (resolved_profile.requires_external_research if resolved_profile else False),
            requires_coding=requires_coding
            or (resolved_profile.requires_code_execution if resolved_profile else False),
            created_at=now,
            profile=resolved_profile,
        )
        state = TeamRunState(
            run_id=rid,
            status=TeamRunStatus.QUEUED,
            contract=qc,
            policy=policy or TeamExecutionPolicy.team_default(),
            artifact_revision=artifact_revision or f"rev:{uuid.uuid4().hex[:10]}",
            created_at=now,
            updated_at=now,
            started_at=self._clock(),
            task_profile=resolved_profile.public_dict() if resolved_profile else {
                "category": effective_category,
                "answer_kind": "caller_specified",
            },
            request_text=request_text or "",
        )
        self._runs[rid] = state
        if self.quality_store is not None:
            self.quality_store.save_contract(qc)
        state.emit(
            "team_started",
            "TEAM run queued",
            {
                "request_ref": qc.request_ref,
                "task_profile": state.task_profile,
                "contract_version": qc.version,
            },
        )
        self._set_status(state, TeamRunStatus.PLANNING)
        roles = select_roles_for_task(
            task_category=effective_category,
            requires_research=requires_research
            or (resolved_profile.requires_external_research if resolved_profile else False),
            requires_coding=requires_coding
            or (resolved_profile.requires_code_execution if resolved_profile else False),
            requires_tools=requires_tools
            or (resolved_profile.requires_tools if resolved_profile else False),
            profile=resolved_profile,
        )
        caps = list(parent_capabilities or [])
        state.assignments = self._plan_assignments(state, roles, allowed_capabilities=caps)
        state.emit(
            "plan_ready",
            f"Planned {len(state.assignments)} specialist assignments",
            {
                "roles": [r.value for r in roles],
                "criteria": [c.criterion_id for c in qc.criteria],
                "task_category": qc.task_category,
                "lightweight": bool((state.task_profile or {}).get("lightweight")),
            },
        )
        return state

    def advance(self, run_id: str, *, max_steps: int = 1) -> TeamRunState:
        state = self._require(run_id)
        if state.status in TERMINAL_TEAM_STATUSES:
            return state
        if state.cancelled:
            self._set_status(state, TeamRunStatus.CANCELLING)
            self._set_status(state, TeamRunStatus.CANCELLED)
            state.emit("cancelled", "TEAM run cancelled")
            return state
        if state.pause_requested and state.status not in NON_SUCCESS_ACTIVE:
            self._set_status(state, TeamRunStatus.PAUSED)
            state.emit("paused", "TEAM run paused by user")
            return state
        if state.status == TeamRunStatus.PAUSED:
            return state
        if state.status in {
            TeamRunStatus.WAITING_FOR_INPUT,
            TeamRunStatus.BLOCKED,
            TeamRunStatus.WAITING_FOR_RESOURCE,
        }:
            return state

        for _ in range(max(1, max_steps)):
            if state.status in TERMINAL_TEAM_STATUSES | NON_SUCCESS_ACTIVE:
                break
            if state.cancelled:
                self._set_status(state, TeamRunStatus.CANCELLING)
                self._set_status(state, TeamRunStatus.CANCELLED)
                break

            # Optional user caps → incomplete, never green success.
            cap_hit = self._check_user_caps(state)
            if cap_hit:
                self._block(
                    state,
                    kind="user_cap_reached",
                    summary=cap_hit,
                    criterion_id=None,
                    remedies=["raise optional user cap", "relax scope with user acceptance"],
                )
                break

            if state.status in {TeamRunStatus.PLANNING, TeamRunStatus.REVISING}:
                self._set_status(state, TeamRunStatus.RUNNING)

            if state.status == TeamRunStatus.RUNNING:
                self._execute_ready_assignments(state)
                self._set_status(state, TeamRunStatus.VERIFYING)

            if state.status == TeamRunStatus.VERIFYING:
                before_fp = self._progress_fingerprint(state)
                before = criterion_progress(
                    state.contract, state.verdicts, artifact_revision=state.artifact_revision
                )["mandatory_satisfied"]
                self._collect_verdicts_from_assignments(state)
                after = criterion_progress(
                    state.contract, state.verdicts, artifact_revision=state.artifact_revision
                )["mandatory_satisfied"]
                after_fp = self._progress_fingerprint(state)
                progress_reason = self._explain_progress(before_fp, after_fp, before, after)
                meaningful = bool(progress_reason)
                delta = TeamProgressDelta(
                    iteration=state.iteration,
                    criteria_satisfied_before=before,
                    criteria_satisfied_after=after,
                    new_evidence_ids=list(
                        self._evidence_ids_from_state(state) - set(before_fp.get("evidence", ()))
                    ),
                    repaired_artifacts=(
                        [state.artifact_revision]
                        if progress_reason == "first_artifact"
                        else []
                    ),
                    meaningful=meaningful,
                )
                state.progress_deltas.append(delta)
                state.last_progress_fingerprint = after_fp.get("digest", "")
                if meaningful:
                    state.no_progress_streak = 0
                    state.progress_reasons.append(progress_reason)
                    state.emit(
                        "progress",
                        f"Meaningful progress: {progress_reason}",
                        {
                            "reason": progress_reason,
                            "mandatory_satisfied": after,
                            "no_progress_streak": state.no_progress_streak,
                        },
                    )
                else:
                    state.no_progress_streak += 1
                    state.emit(
                        "no_progress_tick",
                        "No meaningful criterion/artifact/evidence progress",
                        {
                            "no_progress_streak": state.no_progress_streak,
                            "mandatory_satisfied": after,
                        },
                    )

                record = aggregate_acceptance(
                    state.contract,
                    state.verdicts,
                    artifact_revision=state.artifact_revision,
                    created_at=_utc_now(),
                )
                state.acceptance = record
                if self.quality_store is not None:
                    self.quality_store.save_acceptance(record)
                    for v in state.verdicts:
                        self.quality_store.save_verdict(v, contract_id=state.contract.contract_id)

                if record.outcome == AcceptanceOutcome.ACCEPTED:
                    state.final_artifact = state.provisional_artifact or {
                        "revision": state.artifact_revision,
                        "status": "accepted",
                    }
                    self._set_status(state, TeamRunStatus.COMPLETED)
                    state.emit(
                        "accepted",
                        "All mandatory criteria satisfied for current revision",
                        {
                            **record.public_dict(),
                            "task_profile": state.task_profile,
                            "final_outcome": "completed",
                        },
                    )
                    break

                # Failed mandatory → schedule follow-up, never complete.
                if state.no_progress_streak >= state.policy.no_progress_window:
                    self._handle_no_progress(state, record)
                    break

                scheduled = self._schedule_followups(state, record)
                if not scheduled:
                    # No legitimate remediation — block immediately with truthful kind.
                    self._handle_no_progress(state, record, force_kind="verification_failed")
                    break
                self._set_status(state, TeamRunStatus.REVISING)
                state.iteration += 1
                state.emit(
                    "revising",
                    f"Iteration {state.iteration}; blockers={list(record.blockers)[:6]}",
                    {"blockers": list(record.blockers)},
                )

        state.updated_at = _utc_now()
        return state

    def run_until_terminal(
        self,
        run_id: str,
        *,
        max_iterations: int | None = None,
    ) -> TeamRunState:
        """Drive TEAM until terminal/blocked. Fixture-friendly; respects policy caps."""
        state = self._require(run_id)
        hard = max_iterations
        if hard is None and state.policy.user_caps.max_iterations is not None:
            hard = state.policy.user_caps.max_iterations
        # Safety rail for callers — not a TEAM success gate. None → large fixture bound.
        safety = hard if hard is not None else 10_000
        steps = 0
        while (
            state.status not in TERMINAL_TEAM_STATUSES
            and state.status not in NON_SUCCESS_ACTIVE
            and steps < safety
        ):
            state = self.advance(run_id, max_steps=1)
            steps += 1
        return state

    def pause(self, run_id: str) -> TeamRunState:
        state = self._require(run_id)
        state.pause_requested = True
        if state.status == TeamRunStatus.RUNNING:
            self._set_status(state, TeamRunStatus.PAUSED)
            state.emit("paused", "TEAM run paused")
        return state

    def resume(self, run_id: str, *, supply_input: dict[str, Any] | None = None) -> TeamRunState:
        state = self._require(run_id)
        state.pause_requested = False
        if supply_input:
            state.emit("input_supplied", "User supplied missing dependency", supply_input)
            # Clear input blockers when input arrives.
            state.blockers = [b for b in state.blockers if b.kind != "missing_input"]
        if state.status in {
            TeamRunStatus.PAUSED,
            TeamRunStatus.WAITING_FOR_INPUT,
            TeamRunStatus.BLOCKED,
            TeamRunStatus.WAITING_FOR_RESOURCE,
        }:
            self._set_status(state, TeamRunStatus.RUNNING)
            state.emit("resumed", "TEAM run resumed")
        return state

    def cancel(self, run_id: str) -> TeamRunState:
        state = self._require(run_id)
        state.cancelled = True
        if state.status not in TERMINAL_TEAM_STATUSES:
            self._set_status(state, TeamRunStatus.CANCELLING)
            # Mark in-flight assignments cancelled; reject late results later.
            for a in state.assignments:
                if a.status in {"pending", "running"}:
                    a.status = "cancelled"
            self._set_status(state, TeamRunStatus.CANCELLED)
            state.emit("cancelled", "TEAM run cancelled; descendants settled")
        return state

    def steer(
        self,
        run_id: str,
        instruction: str,
        *,
        material_scope_change: bool = False,
        user_accepted_relaxation: bool = False,
    ) -> TeamRunState:
        state = self._require(run_id)
        from .steering import classify_steer

        classification = classify_steer(instruction)
        state.emit(
            "steer",
            classification.detail,
            classification.public_dict(),
        )
        if material_scope_change or classification.replaces_goal:
            # Invalidate stale verdicts; bump contract/artifact where needed.
            state.verdicts = invalidate_verdicts_for_revision(
                state.verdicts,
                artifact_revision=state.artifact_revision,
                contract_version=state.contract.version,
            )
            new_rev = f"rev:{uuid.uuid4().hex[:10]}"
            state.artifact_revision = new_rev
            note = f"steering: {instruction[:200]}"
            if classification.replaces_goal:
                state.contract = state.contract.revise(
                    scope=instruction,
                    revised_at=_utc_now(),
                    revision_note=note,
                    user_accepted_relaxation=user_accepted_relaxation,
                )
            state.graph_revision += 1
            state.acceptance = None
            if state.status not in TERMINAL_TEAM_STATUSES:
                self._set_status(state, TeamRunStatus.REVISING)
            if self.quality_store is not None:
                self.quality_store.save_contract(state.contract)
        return state

    def apply_specialist_result(
        self,
        run_id: str,
        task_id: str,
        result: dict[str, Any] | TeamSpecialistResult,
        *,
        graph_revision: int,
    ) -> TeamRunState:
        """Apply a specialist result; reject stale/cancelled revisions."""
        state = self._require(run_id)
        if state.status in {TeamRunStatus.CANCELLED, TeamRunStatus.CANCELLING}:
            state.emit("stale_result_rejected", f"ignored result for {task_id} after cancel")
            return state
        if graph_revision != state.graph_revision or graph_revision in state.superseded_graph_revisions:
            state.emit(
                "stale_result_rejected",
                f"ignored result for {task_id} from superseded graph_revision={graph_revision}",
            )
            return state
        for a in state.assignments:
            if a.task_id == task_id:
                if a.status == "cancelled":
                    state.emit("stale_result_rejected", f"ignored cancelled assignment {task_id}")
                    return state
                # Validate structured result boundary — coerce TeamSpecialistResult.
                if isinstance(result, TeamSpecialistResult):
                    result = result.to_dict()
                if not isinstance(result, dict):
                    a.status = "failed"
                    a.error = "malformed_result_not_object"
                    state.emit("malformed_result", a.error, {"task_id": task_id})
                    return state
                typed = TeamSpecialistResult.from_mapping(result)
                if typed.role and str(typed.role) != a.role.value:
                    a.status = "failed"
                    a.error = "role_mismatch"
                    state.emit("malformed_result", a.error, {"task_id": task_id})
                    return state
                normalized = typed.to_dict()
                normalized["role"] = a.role.value
                a.result = normalized
                a.status = "completed"
                art = normalized.get("provisional_artifact") or normalized.get("artifact_candidate")
                if art and isinstance(art, dict):
                    text = str(art.get("text") or art.get("content") or "").strip()
                    if text:
                        payload = dict(art)
                        payload["provisional"] = True
                        payload["text"] = text
                        payload["revision"] = state.artifact_revision
                        payload["from_role"] = a.role.value
                        # Prefer synthesizer/analyst candidate as current revision artifact.
                        if (
                            state.provisional_artifact is None
                            or a.role in {TeamRole.SYNTHESIZER, TeamRole.ANALYST}
                            or len(text) >= len(
                                str((state.provisional_artifact or {}).get("text") or "")
                            )
                        ):
                            state.provisional_artifact = payload
                            state.emit(
                                "artifact_updated",
                                f"provisional artifact from {a.role.value}",
                                {
                                    "task_id": task_id,
                                    "chars": len(text),
                                    "artifact_revision": state.artifact_revision,
                                },
                            )
                if typed.evidence_ids or typed.evidence_refs:
                    state.emit(
                        "evidence_added",
                        "specialist attached evidence refs",
                        {
                            "task_id": task_id,
                            "evidence_ids": list(typed.evidence_ids or typed.evidence_refs)[:12],
                        },
                    )
                return state
        state.emit("stale_result_rejected", f"unknown task_id {task_id}")
        return state

    def export_artifact(self, run_id: str, *, provisional_ok: bool = True) -> dict[str, Any]:
        state = self._require(run_id)
        if state.status == TeamRunStatus.COMPLETED and state.final_artifact:
            return {
                "status": "accepted",
                "provisional": False,
                "artifact": state.final_artifact,
                "artifact_revision": state.artifact_revision,
                "acceptance": state.acceptance.public_dict() if state.acceptance else None,
            }
        if provisional_ok and state.provisional_artifact:
            return {
                "status": "provisional",
                "provisional": True,
                "artifact": state.provisional_artifact,
                "artifact_revision": state.artifact_revision,
                "acceptance": None,
                "watermark": "PROVISIONAL — quality contract not accepted",
            }
        return {
            "status": "unavailable",
            "provisional": True,
            "artifact": None,
            "artifact_revision": state.artifact_revision,
            "watermark": "PROVISIONAL — no artifact yet",
        }

    # --- internals ---

    def _require(self, run_id: str) -> TeamRunState:
        state = self._runs.get(run_id)
        if state is None:
            raise KeyError(f"unknown TEAM run_id: {run_id}")
        return state

    def _set_status(self, state: TeamRunState, target: TeamRunStatus) -> None:
        assert_transition(state.status, target)
        state.status = target
        state.updated_at = _utc_now()

    def _plan_assignments(
        self,
        state: TeamRunState,
        roles: Sequence[TeamRole],
        *,
        allowed_capabilities: Sequence[str],
    ) -> list[TeamAssignment]:
        assignments: list[TeamAssignment] = []
        prev: str | None = None
        criterion_ids = [c.criterion_id for c in state.contract.mandatory_applicable()]
        for role in roles:
            if role == TeamRole.ORCHESTRATOR:
                continue  # orchestrator is this layer
            tid = new_assignment_id()
            deps = [prev] if prev else []
            # Verifier should not see synthesizer conclusions first when independent check matters.
            objective = f"{role.value}: advance criteria {criterion_ids}"
            if role == TeamRole.VERIFIER:
                objective = (
                    "Independently verify primary evidence for mandatory criteria "
                    "before accepting other agents' conclusions"
                )
            assignments.append(
                TeamAssignment(
                    task_id=tid,
                    parent_run_id=state.run_id,
                    role=role,
                    objective=objective,
                    criterion_ids=list(criterion_ids),
                    allowed_capabilities=list(allowed_capabilities),
                    dependencies=deps,
                    graph_revision=state.graph_revision,
                )
            )
            prev = tid
        # Fan-out bound
        max_fan = state.policy.resource_bounds.max_fan_out
        if len(assignments) > max_fan:
            assignments = assignments[:max_fan]
        return assignments

    def _execute_ready_assignments(self, state: TeamRunState) -> None:
        completed_ids = {a.task_id for a in state.assignments if a.status == "completed"}
        sequential = state.policy.single_model_sequential or not state.policy.allow_parallel_workers
        for a in state.assignments:
            if a.status not in {"pending", "ready"}:
                continue
            if a.graph_revision != state.graph_revision:
                a.status = "superseded"
                continue
            if any(d not in completed_ids for d in a.dependencies):
                continue
            a.status = "running"
            state.emit("assignment_started", f"{a.role.value} started", {"task_id": a.task_id})
            try:
                result = self._executor(a, state)
                self.apply_specialist_result(
                    state.run_id, a.task_id, result, graph_revision=state.graph_revision
                )
            except Exception as exc:  # noqa: BLE001
                a.status = "failed"
                a.error = str(exc)
                state.emit("assignment_failed", str(exc), {"task_id": a.task_id})
            if sequential:
                # Single local model: one role at a time.
                completed_ids = {x.task_id for x in state.assignments if x.status == "completed"}

    def _collect_verdicts_from_assignments(self, state: TeamRunState) -> None:
        """Build verdicts from specialist results + deterministic artifact inspection.

        Fail closed without real receipts for research/coding/calc. For conversational
        tasks, a non-empty provisional response artifact is inspectable evidence —
        LLM ``artifact_ok`` alone is never proof.
        """
        evidence_pool: list[str] = []
        claims_ok = False
        citation_ok = False
        tests_ok = False
        synthesis_clean = True
        uncertainty_ok = False
        calc_ok = False
        requirements_ok = False
        new_claim_introduced = False
        material_claims: list[dict[str, Any]] = []
        schema_error = False

        for a in state.assignments:
            if a.status != "completed" or not a.result:
                continue
            if a.graph_revision != state.graph_revision:
                continue
            res = a.result
            if res.get("schema") != "TeamSpecialistResult.v1" and not any(
                k in res
                for k in (
                    "provisional_artifact",
                    "artifact_candidate",
                    "evidence_ids",
                    "tests_passed",
                    "supported_uncertainty",
                )
            ):
                # Empty/malformed producer payload — track for blocker classification.
                if not res.get("notes") and not res.get("summary"):
                    schema_error = True
            for eid in res.get("evidence_ids") or res.get("evidence_refs") or []:
                evidence_pool.append(str(eid))
            for claim in res.get("material_claims") or []:
                if isinstance(claim, dict):
                    material_claims.append(claim)
            # Receipt-backed signals only.
            if res.get("claims_supported") is True and (res.get("evidence_ids") or res.get("evidence_refs")):
                claims_ok = True
            if res.get("citation_audit_passed") is True and (res.get("evidence_ids") or res.get("evidence_refs")):
                citation_ok = True
            test_receipt = res.get("test_receipt_id") or (
                (res.get("test_receipts") or [None])[0]
            )
            if res.get("tests_passed") is True and test_receipt:
                tests_ok = True
                evidence_pool.append(str(test_receipt))
            if res.get("unsupported_new_claim") is True:
                new_claim_introduced = True
                synthesis_clean = False
            if res.get("supported_uncertainty") is True:
                uncertainty_ok = True
            if res.get("calculation_receipt_id"):
                calc_ok = True
                evidence_pool.append(str(res["calculation_receipt_id"]))
            if res.get("requirements_addressed") is True and (
                state.provisional_artifact or res.get("provisional_artifact")
            ):
                requirements_ok = True
            # Majority agreement on unsupported claim must not pass.
            if res.get("agents_agree_unsupported") is True:
                claims_ok = False
                synthesis_clean = False

        # Deterministic artifact inspection — never trust model artifact_ok alone.
        artifact_text = self._artifact_text(state)
        artifact_present = bool(artifact_text)
        if artifact_present:
            evidence_pool.append(f"artifact:inspect:{state.artifact_revision}")

        lightweight = self._is_lightweight(state)
        request_addressed = False
        if artifact_present:
            if lightweight:
                request_addressed = self._response_addresses_request(
                    state.request_text or state.contract.scope,
                    artifact_text,
                )
            else:
                request_addressed = True  # non-light: deliverable presence is the inspection gate

        # Conversational synthesis: no material external claims → system receipt.
        artifact_has_material_external = bool(_MATERIAL_EXTERNAL_CLAIM.search(artifact_text or ""))
        unsupported_material_in_artifact = artifact_has_material_external and not (
            claims_ok or calc_ok or tests_ok
        )
        if unsupported_material_in_artifact and lightweight:
            new_claim_introduced = True
            synthesis_clean = False

        # Independent origin collapse: many URLs one origin → one evidence origin.
        origins = []
        for a in state.assignments:
            if a.result and a.graph_revision == state.graph_revision:
                for o in a.result.get("evidence_origins") or []:
                    origins.append(str(o))
        independent_origins = sorted(set(origins))

        def _add_verdict(
            criterion_id: str,
            status: CriterionVerdictStatus,
            *,
            evidence_ids: Sequence[str] = (),
            justification: str = "",
            verifier: str = "team.verifier",
        ) -> None:
            # SATISFIED requires evidence — fail closed.
            ev = tuple(evidence_ids)
            if status == CriterionVerdictStatus.SATISFIED and not ev:
                status = CriterionVerdictStatus.UNVERIFIABLE
                justification = justification or "satisfied attempted without evidence"
            verdict = CriterionVerdict(
                criterion_id=criterion_id,
                contract_version=state.contract.version,
                artifact_revision=state.artifact_revision,
                status=status,
                verifier_identity=verifier,
                verifier_type="deterministic_team_aggregator",
                evidence_ids=ev,
                public_justification=justification,
                created_at=_utc_now(),
            )
            state.verdicts.append(verdict)
            state.emit(
                "criterion_verdict",
                f"{criterion_id} → {status.value}",
                {
                    "criterion_id": criterion_id,
                    "status": status.value,
                    "evidence_count": len(ev),
                    "applicability": "applicable",
                },
            )

        if schema_error and not artifact_present:
            state.emit(
                "internal_result_schema_error",
                "Specialist results lacked usable artifact/evidence schema",
                {"iteration": state.iteration},
            )

        for crit in state.contract.criteria:
            cid = crit.criterion_id
            if crit.applicability == CriterionApplicability.NOT_APPLICABLE:
                _add_verdict(
                    cid,
                    CriterionVerdictStatus.NOT_APPLICABLE,
                    justification=crit.applicability_justification or "marked not applicable on contract",
                    evidence_ids=["contract:not_applicable"],
                )
                continue
            if crit.evidence_class == EvidenceClass.TEST_RECEIPT:
                _add_verdict(
                    cid,
                    CriterionVerdictStatus.SATISFIED if tests_ok else CriterionVerdictStatus.UNSATISFIED,
                    evidence_ids=[e for e in evidence_pool if e.startswith("test:")] or (
                        [evidence_pool[0]] if tests_ok and evidence_pool else []
                    ),
                    justification="trusted test receipt" if tests_ok else "missing trusted test receipt",
                )
            elif crit.evidence_class == EvidenceClass.CLAIM_SUPPORT:
                ok = claims_ok and bool(evidence_pool)
                _add_verdict(
                    cid,
                    CriterionVerdictStatus.SATISFIED if ok else CriterionVerdictStatus.UNSATISFIED,
                    evidence_ids=evidence_pool[:8] if ok else (),
                    justification=(
                        f"claims supported; independent_origins={len(independent_origins)}"
                        if ok
                        else "claims lack inspectable support"
                    ),
                )
            elif crit.evidence_class == EvidenceClass.CITATION_AUDIT:
                ok = citation_ok and bool(evidence_pool)
                _add_verdict(
                    cid,
                    CriterionVerdictStatus.SATISFIED if ok else CriterionVerdictStatus.UNSATISFIED,
                    evidence_ids=evidence_pool[:4] if ok else (),
                    justification="citation audit passed" if ok else "citation audit missing/failed",
                )
            elif crit.evidence_class == EvidenceClass.CALCULATION_RECEIPT:
                _add_verdict(
                    cid,
                    CriterionVerdictStatus.SATISFIED if calc_ok else CriterionVerdictStatus.UNSATISFIED,
                    evidence_ids=[e for e in evidence_pool if e.startswith("calc:")] if calc_ok else (),
                    justification="calculation receipt present" if calc_ok else "no calculation receipt",
                )
            elif crit.evidence_class == EvidenceClass.UNCERTAINTY_STATEMENT:
                _add_verdict(
                    cid,
                    CriterionVerdictStatus.SATISFIED if uncertainty_ok else CriterionVerdictStatus.UNSATISFIED,
                    evidence_ids=["uncertainty:statement"] if uncertainty_ok else (),
                    justification="supported uncertainty statement" if uncertainty_ok else "uncertainty not supported",
                )
            elif crit.evidence_class == EvidenceClass.ARTIFACT_INSPECTION:
                if cid == "crit:request_addressed":
                    ok = artifact_present and request_addressed
                    _add_verdict(
                        cid,
                        CriterionVerdictStatus.SATISFIED if ok else CriterionVerdictStatus.UNSATISFIED,
                        evidence_ids=[f"artifact:scope:{state.artifact_revision}"] if ok else (),
                        justification=(
                            "response addresses request scope"
                            if ok
                            else "response missing or does not address request"
                        ),
                    )
                else:
                    # Deliverable / requirements: inspect real artifact state.
                    ok = artifact_present or requirements_ok
                    # Ignore bare LLM artifact_ok without inspectable text.
                    _add_verdict(
                        cid,
                        CriterionVerdictStatus.SATISFIED if ok else CriterionVerdictStatus.UNSATISFIED,
                        evidence_ids=[f"artifact:inspect:{state.artifact_revision}"] if ok else (),
                        justification=(
                            "artifact inspected from provisional response"
                            if ok
                            else "artifact missing/uninspected"
                        ),
                    )
            elif cid == "crit:synthesis_rechecked":
                if new_claim_introduced or unsupported_material_in_artifact:
                    _add_verdict(
                        cid,
                        CriterionVerdictStatus.UNSATISFIED,
                        justification="synthesis introduced unsupported new claim — gate reopened",
                    )
                elif synthesis_clean and artifact_present and lightweight and not material_claims:
                    # Deterministic conversational synthesis receipt — no invented citations.
                    _add_verdict(
                        cid,
                        CriterionVerdictStatus.SATISFIED,
                        evidence_ids=[f"synthesis:conversational_clean:{state.artifact_revision}"],
                        justification="conversational synthesis: no unsupported material claims detected",
                    )
                elif synthesis_clean and (
                    claims_ok
                    or tests_ok
                    or calc_ok
                    or uncertainty_ok
                    or requirements_ok
                    or (artifact_present and not lightweight and not artifact_has_material_external)
                ):
                    _add_verdict(
                        cid,
                        CriterionVerdictStatus.SATISFIED,
                        evidence_ids=evidence_pool[:4] or [
                            f"synthesis:clean:{state.artifact_revision}"
                        ],
                        justification="post-synthesis recheck clean",
                    )
                elif synthesis_clean and artifact_present and not artifact_has_material_external:
                    _add_verdict(
                        cid,
                        CriterionVerdictStatus.SATISFIED,
                        evidence_ids=[f"synthesis:artifact_clean:{state.artifact_revision}"],
                        justification="artifact present without unsupported material claims",
                    )
                else:
                    _add_verdict(
                        cid,
                        CriterionVerdictStatus.PENDING,
                        justification="awaiting synthesis material",
                    )
            else:
                _add_verdict(
                    cid,
                    CriterionVerdictStatus.PENDING,
                    justification="no verifier result yet",
                )

    def _schedule_followups(self, state: TeamRunState, record: AcceptanceRecord) -> bool:
        """Schedule a new acyclic follow-up DAG targeting unresolved criteria.

        Returns False when no legitimate remediation exists (caller should block).
        """
        crit_ids: list[str] = []
        for b in record.blockers:
            parts = b.split(":")
            # formats: missing_verdict:crit:x | unsatisfied:crit:x | pending:crit:x
            if len(parts) >= 3 and parts[1] == "crit":
                crit_ids.append("crit:" + parts[2])
            elif len(parts) >= 2 and parts[-1].startswith("crit"):
                crit_ids.append(parts[-1] if parts[-1].startswith("crit:") else "crit:" + parts[-1])
        if not crit_ids:
            crit_ids = [c.criterion_id for c in state.contract.mandatory_applicable()]

        lightweight = self._is_lightweight(state)
        cat = (state.contract.task_category or "").lower()

        # Choose remediation roles that can actually change the failed criteria.
        if any(c in {"crit:behavior_works", "crit:regression_preserved"} or "test" in c for c in crit_ids):
            follow_roles = [TeamRole.ANALYST, TeamRole.VERIFIER]
        elif any(c in {"crit:claims_supported", "crit:citation_audit"} for c in crit_ids) or cat in {
            "research",
            "factual",
        }:
            follow_roles = [TeamRole.RESEARCHER, TeamRole.VERIFIER]
        elif any("calc" in c or "reproducible" in c for c in crit_ids) or cat == "quantitative":
            follow_roles = [TeamRole.ANALYST, TeamRole.VERIFIER]
        elif any("synthesis" in c for c in crit_ids):
            follow_roles = [TeamRole.CRITIC, TeamRole.SYNTHESIZER, TeamRole.VERIFIER]
        elif lightweight or any(
            c in {"crit:deliverable_present", "crit:request_addressed"} for c in crit_ids
        ):
            # Produce/refine the conversational artifact, then verify.
            if not self._artifact_text(state):
                follow_roles = [TeamRole.SYNTHESIZER, TeamRole.VERIFIER]
            else:
                follow_roles = [TeamRole.ANALYST, TeamRole.SYNTHESIZER, TeamRole.VERIFIER]
        else:
            follow_roles = [TeamRole.ANALYST, TeamRole.VERIFIER]

        # Detect identical repeated follow-up with same unresolved set → no remediation.
        prior_objectives = [
            a.objective
            for a in state.assignments
            if a.graph_revision == state.graph_revision - 0  # current graph
        ]
        remedy = (
            f"Resolve {crit_ids}: "
            f"prior blockers={list(record.blockers)[:4]}; "
            f"missing={'artifact' if not self._artifact_text(state) else 'evidence/receipts'}; "
            f"produce typed TeamSpecialistResult with inspectable artifact/receipts"
        )
        if state.no_progress_streak >= 1 and any(remedy[:40] in (o or "") for o in prior_objectives):
            # Still allow one structured retry with explicit remediation goal below.
            pass

        state.superseded_graph_revisions.add(state.graph_revision)
        state.graph_revision += 1

        new_assignments = self._plan_assignments(
            state,
            [TeamRole.ORCHESTRATOR, *follow_roles],
            allowed_capabilities=state.assignments[0].allowed_capabilities if state.assignments else [],
        )
        if not new_assignments:
            return False
        for a in new_assignments:
            a.criterion_ids = list(crit_ids)
            a.objective = remedy
            a.revision_preconditions = list(record.blockers)[:8]
            a.graph_revision = state.graph_revision
            a.context_refs = [
                f"artifact_revision:{state.artifact_revision}",
                f"failed:{','.join(crit_ids)}",
            ]
        state.assignments.extend(new_assignments)
        state.emit(
            "followup_scheduled",
            f"Follow-up graph revision {state.graph_revision}",
            {
                "criterion_ids": crit_ids,
                "tasks": [a.task_id for a in new_assignments],
                "roles": [a.role.value for a in new_assignments],
                "remediation": remedy[:240],
            },
        )
        return True

    def _handle_no_progress(
        self,
        state: TeamRunState,
        record: AcceptanceRecord,
        *,
        force_kind: str | None = None,
    ) -> None:
        kind = force_kind or self._classify_blocker_kind(state, record)
        summaries = {
            "internal_result_schema_error": (
                "Internal specialist result schema never produced inspectable artifact/evidence; "
                "orchestration defect — not a user content failure"
            ),
            "contract_mismatch": (
                "Quality contract requires evidence the executor cannot produce for this task profile"
            ),
            "evidence_unavailable": (
                "Required evidence/receipts are unavailable; cannot satisfy mandatory criteria"
            ),
            "verification_failed": (
                "Verification failed and no further legitimate remediation is available"
            ),
            "missing_capability": (
                "Required capability/specialist is unavailable for mandatory evidence"
            ),
            "repeated_no_progress": (
                f"No meaningful criterion/evidence progress over "
                f"{state.no_progress_streak} iterations; work checkpointed"
            ),
            "no_progress": (
                f"No meaningful criterion/evidence progress over "
                f"{state.no_progress_streak} iterations; work checkpointed"
            ),
        }
        summary = summaries.get(kind, summaries["repeated_no_progress"])
        remedies = [
            "change query/source/tool/hypothesis",
            "decompose differently",
            "request missing input",
        ]
        if kind == "internal_result_schema_error":
            remedies = ["fix specialist result contract", "retry with TeamSpecialistResult schema"]
        self._block(
            state,
            kind=kind,
            summary=summary,
            criterion_id=None,
            remedies=remedies,
            needed_input=(
                None
                if kind in {"internal_result_schema_error", "contract_mismatch"}
                else "Provide alternative source, constraint clarification, or capability"
            ),
            needed_capability=(
                "evidence_or_test_receipt"
                if kind in {"evidence_unavailable", "missing_capability"}
                else None
            ),
        )
        state.emit(
            "no_progress_blocker",
            state.blockers[-1].summary,
            {
                "blockers": list(record.blockers),
                "remedies": remedies,
                "blocker_kind": kind,
                "task_profile": state.task_profile,
                "final_outcome": state.status.value,
            },
        )

    def _classify_blocker_kind(self, state: TeamRunState, record: AcceptanceRecord) -> str:
        completed = [
            a
            for a in state.assignments
            if a.status == "completed" and a.graph_revision == state.graph_revision
        ]
        has_artifact = bool(self._artifact_text(state))
        any_schema = any(
            (a.result or {}).get("schema") == "TeamSpecialistResult.v1" for a in completed
        )
        if completed and not has_artifact and not any_schema:
            return "internal_result_schema_error"
        cat = (state.contract.task_category or "").lower()
        if cat in {"research", "factual", "coding", "repair", "quantitative"} and not has_artifact:
            # Strict tasks without receipts after retries.
            if any("test" in b or "claim" in b or "calc" in b or "citation" in b for b in record.blockers):
                return "evidence_unavailable"
        if any("unverifiable" in b for b in record.blockers):
            return "verification_failed"
        return "repeated_no_progress"

    @staticmethod
    def _artifact_text(state: TeamRunState) -> str:
        art = state.provisional_artifact or state.final_artifact or {}
        if not isinstance(art, dict):
            return ""
        return str(art.get("text") or art.get("content") or "").strip()

    @staticmethod
    def _is_lightweight(state: TeamRunState) -> bool:
        profile = state.task_profile or {}
        if profile.get("lightweight"):
            return True
        cat = (state.contract.task_category or profile.get("category") or "").lower()
        return cat in LIGHTWEIGHT_CATEGORIES

    @staticmethod
    def _response_addresses_request(request_text: str, response_text: str) -> bool:
        """Deterministic lightweight scope check — not semantic entailment."""
        req = (request_text or "").strip()
        resp = (response_text or "").strip()
        if not resp or len(resp) < 2:
            return False
        if not req:
            return True
        # Extremely short acknowledgements still count for greetings.
        if len(req.split()) <= 4 and len(resp) >= 2:
            return True
        # Identity / capability questions need more than a single punctuation mark.
        if len(resp) < 8 and ("?" in req or len(req.split()) > 4):
            return False
        return True

    def _evidence_ids_from_state(self, state: TeamRunState) -> set[str]:
        out: set[str] = set()
        for v in state.verdicts:
            if v.artifact_revision != state.artifact_revision:
                continue
            if v.status == CriterionVerdictStatus.STALE:
                continue
            out.update(str(e) for e in v.evidence_ids)
        for a in state.assignments:
            if a.result and a.graph_revision == state.graph_revision:
                for e in a.result.get("evidence_ids") or []:
                    out.add(str(e))
        return out

    def _progress_fingerprint(self, state: TeamRunState) -> dict[str, Any]:
        progress = criterion_progress(
            state.contract, state.verdicts, artifact_revision=state.artifact_revision
        )
        art = self._artifact_text(state)
        art_hash = hashlib.sha256(art.encode("utf-8")).hexdigest()[:16] if art else ""
        evidence = tuple(sorted(self._evidence_ids_from_state(state)))
        verdict_sig = tuple(
            sorted(
                (v.criterion_id, v.status.value)
                for v in state.verdicts
                if v.artifact_revision == state.artifact_revision
                and v.status != CriterionVerdictStatus.STALE
            )
        )
        digest = hashlib.sha256(
            f"{progress.get('mandatory_satisfied')}|{art_hash}|{evidence}|{verdict_sig}".encode()
        ).hexdigest()[:20]
        return {
            "digest": digest,
            "mandatory_satisfied": int(progress.get("mandatory_satisfied") or 0),
            "art_hash": art_hash,
            "had_artifact": bool(art_hash),
            "evidence": evidence,
            "verdict_sig": verdict_sig,
        }

    def _explain_progress(
        self,
        before: dict[str, Any],
        after: dict[str, Any],
        sat_before: int,
        sat_after: int,
    ) -> str:
        if sat_after > sat_before:
            return "criterion_satisfied_increase"
        before_ev = set(before.get("evidence") or ())
        after_ev = set(after.get("evidence") or ())
        if after_ev - before_ev:
            return "new_evidence"
        if not before.get("had_artifact") and after.get("had_artifact"):
            return "first_artifact"
        # Verdict transition without yet increasing mandatory_satisfied (e.g. failed→pending)
        if before.get("verdict_sig") != after.get("verdict_sig") and sat_after >= sat_before:
            # Only count if a status improved toward satisfied / away from unsatisfied.
            before_map = dict(before.get("verdict_sig") or ())
            after_map = dict(after.get("verdict_sig") or ())
            rank = {
                "unsatisfied": 0,
                "unverifiable": 1,
                "pending": 2,
                "satisfied": 3,
                "not_applicable": 3,
            }
            for cid, status in after_map.items():
                if rank.get(status, 0) > rank.get(before_map.get(cid, "pending"), 0):
                    return "verdict_improved"
        # Pure rewording (art_hash change alone) is NOT progress.
        return ""

    def _block(
        self,
        state: TeamRunState,
        *,
        kind: str,
        summary: str,
        criterion_id: str | None,
        remedies: Sequence[str],
        needed_input: str | None = None,
        needed_capability: str | None = None,
    ) -> None:
        blocker = TeamBlocker(
            blocker_id=new_blocker_id(),
            criterion_id=criterion_id,
            kind=kind,
            summary=summary,
            attempted_remedies=list(remedies),
            needed_input=needed_input,
            needed_capability=needed_capability,
        )
        state.blockers.append(blocker)
        if kind == "missing_input":
            self._set_status(state, TeamRunStatus.WAITING_FOR_INPUT)
        elif kind == "resource":
            self._set_status(state, TeamRunStatus.WAITING_FOR_RESOURCE)
        else:
            self._set_status(state, TeamRunStatus.BLOCKED)

    def _check_user_caps(self, state: TeamRunState) -> str | None:
        caps = state.policy.user_caps
        if caps.max_iterations is not None and state.iteration >= caps.max_iterations:
            return f"optional max_iterations={caps.max_iterations} reached; criteria unmet"
        if caps.max_wall_time_seconds is not None:
            elapsed = self._clock() - state.started_at
            if elapsed >= caps.max_wall_time_seconds:
                return f"optional max_wall_time_seconds={caps.max_wall_time_seconds} reached"
        return None

    @staticmethod
    def _default_fixture_executor(assignment: TeamAssignment, state: TeamRunState) -> dict[str, Any]:
        """Deterministic fixture executor for tests — not a production model."""
        # Production wiring replaces this with model/tool-backed specialists.
        return {
            "role": assignment.role.value,
            "evidence_ids": [],
            "notes": "default fixture produced no evidence",
            "fixture": True,
        }


def evidence_origin_key(url_or_locator: str) -> str:
    """Collapse dependent URLs sharing one press-release origin."""
    raw = (url_or_locator or "").strip().lower()
    # Strip tracking queries and www.
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.removeprefix("www.")
    host = raw.split("/", 1)[0]
    return host or raw
