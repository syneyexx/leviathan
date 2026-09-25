"""CognitiveRuntime — bounded iterative orchestration authority.

External-first: heavy domain work is delegated; Core owns authority/state.
No private chain-of-thought persistence.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .action_selector import ActionSelector
from .belief_state import BeliefState
from .capability_broker import CapabilityBroker
from .capability_state import (
    AxisState,
    CapabilityAxis,
    CapabilityState,
    capability_state_from_mapping,
    derive_capability_state,
)
from .completion import CompletionEngine
from .context_v3 import ContextBuilderV3
from .critic_mesh import CriticMesh, CriticMeshReport
from .delegation import DelegateRequest, DelegateResult, DelegationService
from .errors import (
    CognitionCancelled,
    CognitionFeatureDisabled,
    CognitionLoopDetected,
    CognitionTransitionInvalid,
)
from .experience import ExperienceStore
from .failure import FailureCategory, classify_failure, should_blind_retry
from .hydration import (
    action_from_dict,
    beliefs_from_dict,
    decision_from_parts,
    observation_from_dict,
    plan_from_dict,
    status_from_value,
    task_from_dict,
    usage_from_dict,
    working_memory_from_dict,
)
from .hypotheses import HypothesisBoard, HypothesisStatus, hypothesis_board_from_mapping
from .loop_detection import LoopDetector
from .meta_controller import MetaController, MetaDecision
from .perception import PerceptionService, PerceptionSnapshot
from .planner import CognitivePlanner
from .steering import InvalidationScope, SteerKind, classify_steer
from .store import CognitionStore
from .structured_state import StructuredReasoningState, structured_state_from_mapping
from .task_model import TaskModel, TaskModelBuilder
from .types import (
    BeliefCategory,
    BeliefStatus,
    BudgetUsage,
    CognitiveAction,
    CognitiveActionKind,
    CognitiveObservation,
    CognitiveObservationKind,
    CognitivePlan,
    CognitiveRunStatus,
    EpistemicType,
    ReasoningMode,
    RiskClass,
    TERMINAL_STATUSES,
    validate_transition,
)
from .working_memory import WorkingMemory


ModelCaller = Callable[..., Any]


@dataclass
class CognitiveRunState:
    run_id: str
    task: TaskModel
    status: CognitiveRunStatus
    decision: MetaDecision | None = None
    plan: CognitivePlan | None = None
    beliefs: BeliefState = field(default_factory=BeliefState)
    working_memory: WorkingMemory = field(default_factory=lambda: WorkingMemory(capacity=32))
    perception: PerceptionSnapshot | None = None
    observations: list[CognitiveObservation] = field(default_factory=list)
    actions: list[CognitiveAction] = field(default_factory=list)
    usage: BudgetUsage = field(default_factory=BudgetUsage)
    events: list[dict[str, Any]] = field(default_factory=list)
    response_text: str | None = None
    cancel_requested: bool = False
    cancel_acknowledged: bool = False
    shadow: bool = False
    error: str | None = None
    verification_passed: bool | None = None
    context_public: dict[str, Any] | None = None
    completion: dict[str, Any] | None = None
    experience: dict[str, Any] | None = None
    steering: list[str] = field(default_factory=list)
    trace_id: str | None = None
    # Effective BehaviorProfile identity for this run (same plane as Chat).
    behavior_profile_prompt: str | None = None
    behavior_profile_id: str | None = None
    behavior_profile_version: str | None = None
    behavior_settings_hash: str | None = None
    behavior_source: str | None = None
    # Public structured reasoning surface (no private CoT).
    reasoning_state: StructuredReasoningState = field(default_factory=StructuredReasoningState)
    # Run-owned public hypothesis set (deep-branched; not private CoT).
    hypothesis_board: HypothesisBoard = field(default_factory=HypothesisBoard)
    # Last named-domain critic mesh report (public signals only).
    last_critic_report: dict[str, Any] | None = None
    # Cognitive capability matrix (generate / execute / network / …).
    capability_state: CapabilityState = field(default_factory=CapabilityState)
    # Durable worker externalization (cognition.advance).
    pending_advance_job_id: str | None = None

    def public_status(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task.task_id,
            "status": self.status.value,
            "stage": self.status.value,
            "mode": self.decision.mode.value if self.decision else None,
            "requested_mode": (
                self.decision.requested_mode.value
                if self.decision and self.decision.requested_mode
                else (self.decision.mode.value if self.decision else None)
            ),
            "effective_mode": (
                self.decision.effective_mode.value
                if self.decision and self.decision.effective_mode
                else (self.decision.mode.value if self.decision else None)
            ),
            "clamp_reason": self.decision.clamp_reason if self.decision else None,
            "strategy": self.decision.strategy.value if self.decision else None,
            "goal": self.task.goal,
            "domain": self.task.domain,
            "uncertainty": self.beliefs.uncertainty(),
            "belief_counts": self.beliefs.counts(),
            "working_memory_count": len(self.working_memory.items),
            "working_memory_saturation": self.working_memory.saturation(),
            "budgets": self.decision.budgets.public_dict() if self.decision else None,
            "neural_budgets": (
                self.decision.neural_budgets.public_dict()
                if self.decision and self.decision.neural_budgets
                else None
            ),
            "capability_profile": (
                self.decision.capability_profile.public_dict()
                if self.decision and self.decision.capability_profile
                else None
            ),
            "capability_state": self.capability_state.public_dict(),
            "pending_advance_job_id": self.pending_advance_job_id,
            "expected_gain": self.decision.expected_gain if self.decision else None,
            "neural_adaptation": self.decision.neural_adaptation if self.decision else None,
            "reasoning_state": self.reasoning_state.public_dict(),
            "hypothesis_board": self.hypothesis_board.public_dict(),
            "critic_report": self.last_critic_report,
            "usage": self.usage.public_dict(),
            "plan": self.plan.public_dict() if self.plan else None,
            "observations": [o.public_dict() for o in self.observations[-12:]],
            "actions": [a.public_dict() for a in self.actions[-12:]],
            "cancel_requested": self.cancel_requested,
            "cancel_acknowledged": self.cancel_acknowledged,
            "shadow": self.shadow,
            "error": self.error,
            "verification_passed": self.verification_passed,
            "completion": self.completion,
            "response_preview": (self.response_text or "")[:400],
            # Full response only when this run owns the user-visible answer (not shadow).
            "response": None if self.shadow else self.response_text,
            "response_ownership": "none" if self.shadow else ("cognition" if self.response_text else "none"),
            "active_agents": [
                o.payload.get("agent_kind")
                for o in self.observations
                if o.kind == CognitiveObservationKind.AGENT_RESULT
            ],
            "truth": {
                "no_private_cot": True,
                "status_is_backend_backed": True,
                "progress_not_fabricated_percent": True,
                "shadow_does_not_own_final_response": True,
                "reasoning_state_is_public_contract": True,
                "hypothesis_board_is_public": True,
                "critic_mesh_is_named_domain_critics": True,
                "capability_state_is_cognition_matrix": True,
                "cognition_advance_externalizable": True,
            },
        }


class CognitiveRuntime:
    """Public API: submit / run / cancel / steer / status / events / resume."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        shadow: bool = False,
        iterative: bool = True,
        belief_enabled: bool = True,
        neuro_enabled: bool = False,
        adaptive_depth: bool = True,
        delegation_enabled: bool = True,
        experience_learning: bool = False,
        task_builder: TaskModelBuilder | None = None,
        perception: PerceptionService | None = None,
        meta: MetaController | None = None,
        policy: Any | None = None,
        planner: CognitivePlanner | None = None,
        actions: ActionSelector | None = None,
        context_builder: ContextBuilderV3 | None = None,
        completion: CompletionEngine | None = None,
        broker: CapabilityBroker | None = None,
        delegation: DelegationService | None = None,
        experience_store: ExperienceStore | None = None,
        store: CognitionStore | None = None,
        model_caller: ModelCaller | None = None,
        neuro_advisor: Any | None = None,
        verification_engine: Any | None = None,
        evidence_service: Any | None = None,
        receipt_store: Any | None = None,
        research_lookup: Any | None = None,
        execution_gateway: Any | None = None,
        observability: Any | None = None,
        resource_pressure_fn: Callable[[], float] | None = None,
        behavior_resolver: Any | None = None,
        network_outbound_allowed: bool = False,
        job_runtime: Any | None = None,
        externalize_deep: bool = True,
    ) -> None:
        self.enabled = enabled
        self.shadow_default = shadow
        self.iterative = iterative
        self.belief_enabled = belief_enabled
        self.neuro_enabled = neuro_enabled
        self.adaptive_depth = adaptive_depth
        self.delegation_enabled = delegation_enabled
        self.experience_learning = experience_learning

        self.task_builder = task_builder or self._default_task_builder(model_caller)
        self.perception = perception or PerceptionService(neuro_advisor=neuro_advisor)
        if meta is not None:
            self.meta = meta
            if policy is not None and hasattr(self.meta, "set_policy"):
                self.meta.set_policy(policy)
        elif policy is not None:
            self.meta = MetaController(policy=policy)
        else:
            self.meta = MetaController()
        self.planner = planner or self._default_planner(model_caller)
        self.broker = broker or CapabilityBroker()
        self.actions = actions or ActionSelector(self.broker, meta=self.meta)
        self.context_builder = context_builder or ContextBuilderV3()
        self.completion_engine = completion or CompletionEngine()
        self.delegation = delegation or DelegationService()
        self.experience_store = experience_store or ExperienceStore(store=store)
        self.store = store
        self.model_caller = model_caller
        self.neuro_advisor = neuro_advisor
        self.verification_engine = verification_engine
        self.evidence_service = evidence_service
        self.receipt_store = receipt_store
        self.research_lookup = research_lookup
        self.execution_gateway = execution_gateway
        self.observability = observability
        self.resource_pressure_fn = resource_pressure_fn or (lambda: 0.0)
        # Settings Control Plane — same BehaviorProfile plane as Chat.
        self.behavior_resolver = behavior_resolver
        self.network_outbound_allowed = bool(network_outbound_allowed)
        self.job_runtime = job_runtime
        self.externalize_deep = bool(externalize_deep)
        # Named domain critic mesh (public critique signals, not private CoT).
        self.critic_mesh = CriticMesh()

        self._runs: dict[str, CognitiveRunState] = {}
        self._loops: dict[str, LoopDetector] = {}

    @staticmethod
    def _default_task_builder(model_caller: ModelCaller | None) -> TaskModelBuilder:
        """Deterministic builder + heuristic advisor (model advisor opt-in via custom builder)."""
        from .neural_advisors import HeuristicTaskAdvisor

        # Heuristic only by default — model-backed advisors are explicit/opt-in to
        # avoid surprise extra inference calls on every submit.
        _ = model_caller
        return TaskModelBuilder(advisor=HeuristicTaskAdvisor())

    @staticmethod
    def _default_planner(model_caller: ModelCaller | None) -> CognitivePlanner:
        from .neural_advisors import HeuristicPlanAdvisor

        _ = model_caller
        return CognitivePlanner(advisor=HeuristicPlanAdvisor())

    def _record_plan_advice(self, state: CognitiveRunState, plan: CognitivePlan | None) -> None:
        if plan is None:
            return
        advisory = [
            s for s in plan.steps if isinstance(s.resource_estimate, dict) and s.resource_estimate.get("advisory")
        ]
        if advisory:
            state.reasoning_state.notes.append(f"plan_advisory_steps={len(advisory)}")
        for assumption in plan.assumptions:
            if str(assumption).startswith("plan_advice_"):
                state.reasoning_state.notes.append(str(assumption)[:200])

    # --- public API ---

    def submit(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        history: list[dict[str, str]] | None = None,
        has_knowledge: bool = False,
        shadow: bool | None = None,
        constraints: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        user_requested_depth: str | None = None,
        run: bool = True,
        behavior_profile_prompt: str | None = None,
        behavior_profile_id: str | None = None,
        behavior_profile_version: str | None = None,
        behavior_settings_hash: str | None = None,
        behavior_source: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise CognitionFeatureDisabled("LEVIATHAN_FEATURE_COGNITION is disabled")
        use_shadow = self.shadow_default if shadow is None else shadow
        meta_payload = dict(metadata or {})
        if user_requested_depth:
            meta_payload["user_requested_depth"] = str(user_requested_depth)
        identity = self._resolve_behavior_identity(
            message=message,
            history=history,
            behavior_profile_prompt=behavior_profile_prompt,
            behavior_profile_id=behavior_profile_id,
            behavior_profile_version=behavior_profile_version,
            behavior_settings_hash=behavior_settings_hash,
            behavior_source=behavior_source,
        )
        task = self.task_builder.build(
            message,
            has_knowledge=has_knowledge,
            conversation_id=conversation_id,
            constraints=constraints,
            metadata=meta_payload,
        )
        run_id = str(uuid.uuid4())
        task.run_id = run_id
        state = CognitiveRunState(
            run_id=run_id,
            task=task,
            status=CognitiveRunStatus.CREATED,
            shadow=use_shadow,
            trace_id=str(uuid.uuid4()),
            behavior_profile_prompt=identity.get("prompt"),
            behavior_profile_id=identity.get("profile_id"),
            behavior_profile_version=identity.get("version"),
            behavior_settings_hash=identity.get("settings_hash"),
            behavior_source=identity.get("source"),
        )
        state.working_memory.set_goal(task.goal)
        # Pin hard constraints so they survive compaction / retrieval / research.
        hard = list(getattr(task, "hard_constraints", None) or []) or [
            c for c in task.constraints if c
        ]
        if hasattr(state.working_memory, "pin_constraints"):
            state.working_memory.pin_constraints(hard)
        else:
            for c in hard:
                state.working_memory.upsert("constraint", c, priority=1.0, verified=True)
        for c in task.success_criteria:
            state.working_memory.upsert("criteria", c, priority=0.9, verified=True)
        for u in task.unknowns:
            state.working_memory.upsert("question", u, priority=0.55)
        for a in getattr(task, "assumptions", None) or []:
            state.working_memory.upsert(
                "hypothesis",
                a,
                priority=0.4,
                source_type=EpistemicType.HYPOTHESIS,
            )
        # Seed public structured reasoning state (goal + unknowns — not private CoT).
        state.reasoning_state.seed_from_goal(task.goal)
        for u in task.unknowns:
            state.reasoning_state.seed_from_goal(u, source="task_unknown")
        for a in getattr(task, "assumptions", None) or []:
            state.reasoning_state.add_claim(
                a,
                status="asserted",
                confidence_band="weak",
                source="task_assumption",
            )
        advice_meta = (task.metadata or {}).get("task_advice")
        if isinstance(advice_meta, dict):
            state.reasoning_state.notes.append(
                f"task_advice_accepted={bool(advice_meta.get('accepted'))}"
            )
            if advice_meta.get("rejected_fields"):
                state.reasoning_state.notes.append(
                    "task_advice_rejected=" + ",".join(map(str, advice_meta.get("rejected_fields") or []))
                )
        # Seed public HypothesisBoard from task assumptions / unknowns (deep-branchable).
        seeded = state.hypothesis_board.seed_from_task(
            assumptions=getattr(task, "assumptions", None) or [],
            unknowns=task.unknowns,
            domain=task.domain or "general",
        )
        state.capability_state = self._derive_capability_state(state)
        self._runs[run_id] = state
        self._loops[run_id] = LoopDetector()
        self._persist_create(state)
        self._emit(state, "task_created", {"task": task.public_dict()})
        self._emit(
            state,
            "reasoning_state",
            state.reasoning_state.public_dict(),
        )
        self._emit(state, "capability_state", state.capability_state.public_dict())
        if seeded:
            self._emit(state, "hypothesis_board", state.hypothesis_board.public_dict())
        if run:
            return self.run(run_id, history=history)
        return state.public_status()

    def run(self, run_id: str, *, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        state = self._require(run_id)
        if state.status in TERMINAL_STATUSES:
            return state.public_status()
        state.usage.started_monotonic = time.monotonic()
        try:
            self._transition(state, CognitiveRunStatus.PERCEIVING)
            self._perceive(state, history=history)

            decision = self._meta_decide(state)
            state.decision = decision
            self._emit(state, "meta_decision", decision.public_dict())

            if state.shadow:
                # Shadow: produce structured plan/decisions without changing user-visible actions.
                plan = self.planner.plan(state.task, decision)
                state.plan = plan
                self._record_plan_advice(state, plan)
                self._emit(state, "plan_created", plan.public_dict())
                self._transition(state, CognitiveRunStatus.SHADOW)
                state.completion = {
                    "status": "SHADOW",
                    "reason": "shadow mode — no side effects, no user-visible answer replacement",
                }
                self._persist_update(state)
                return state.public_status()

            self._transition(state, CognitiveRunStatus.REASONING)
            state.plan = self.planner.plan(state.task, decision)
            self._record_plan_advice(state, state.plan)
            self._emit(state, "plan_created", state.plan.public_dict())

            if not self.iterative or decision.mode == ReasoningMode.FAST:
                return self._fast_path(state, history=history)

            from .advance import should_externalize_advance

            if should_externalize_advance(
                mode=decision.mode.value if decision.mode else None,
                externalize_deep=self.externalize_deep,
                job_runtime_bound=self.job_runtime is not None,
            ):
                return self._externalize_iterative(state)

            return self._iterative_loop(state, history=history)
        except CognitionCancelled:
            self._transition(state, CognitiveRunStatus.CANCELLED)
            state.cancel_acknowledged = True
            self._finalize(state, cancelled=True)
            return state.public_status()
        except CognitionLoopDetected as exc:
            state.error = exc.message
            self._emit(state, "loop_detected", exc.details)
            self._finalize(state, failed_reason=exc.message)
            return state.public_status()
        except Exception as exc:  # noqa: BLE001
            state.error = f"{type(exc).__name__}: {exc}"
            self._emit(state, "error", {"error": state.error})
            try:
                self._transition(state, CognitiveRunStatus.FAILED)
            except CognitionTransitionInvalid:
                state.status = CognitiveRunStatus.FAILED
            self._finalize(state, failed_reason=state.error)
            return state.public_status()

    def cancel(self, run_id: str) -> dict[str, Any]:
        state = self._require(run_id)
        state.cancel_requested = True
        self._emit(state, "cancellation_requested", {})
        if state.status in TERMINAL_STATUSES:
            state.cancel_acknowledged = True
            return state.public_status()
        # Cooperative cancel — loop checks flag; mark acknowledged.
        state.cancel_acknowledged = True
        if state.status not in TERMINAL_STATUSES:
            try:
                self._transition(state, CognitiveRunStatus.CANCELLED)
            except CognitionTransitionInvalid:
                state.status = CognitiveRunStatus.CANCELLED
        self._finalize(state, cancelled=True)
        return state.public_status()

    def steer(self, run_id: str, instruction: str) -> dict[str, Any]:
        state = self._require(run_id, hydrate=True)
        text = (instruction or "").strip()
        if not text:
            return state.public_status()
        classified = classify_steer(text)
        state.steering.append(text)
        scope = classified.invalidation

        # Preserve existing constraints unless goal replacement explicitly supersedes one.
        if classified.kind == SteerKind.STATUS_REQUEST:
            self._emit(state, "user_steering", classified.public_dict())
            return {
                **state.public_status(),
                "steering_classification": classified.public_dict(),
            }

        if classified.kind == SteerKind.GOAL_REPLACEMENT and classified.replaces_goal:
            state.task.goal = text[:240]
            state.working_memory.set_goal(state.task.goal)
            if scope.open_hypotheses:
                # Park open hypotheses as unresolved notes — do not invent facts.
                for hyp in list(state.hypothesis_board.open_items()):
                    hyp.metadata = {
                        **dict(hyp.metadata or {}),
                        "superseded_by_goal_steer": True,
                    }
                state.reasoning_state.add_unresolved("goal_replaced_by_steer")
        elif classified.kind == SteerKind.NEW_CONSTRAINT:
            state.task.constraints.append(text)
            if hasattr(state.working_memory, "pin_constraints"):
                state.working_memory.pin_constraints([text])
            else:
                state.working_memory.upsert("constraint", text, priority=0.95, verified=True)
        elif classified.kind == SteerKind.CORRECTION:
            state.task.constraints.append(f"correction:{text}")
            state.working_memory.upsert("constraint", f"correction:{text}", priority=0.9)
            state.reasoning_state.add_critique(f"user_correction:{text[:160]}")
        elif classified.kind == SteerKind.CLARIFICATION:
            state.working_memory.upsert("question", text, priority=0.7)
            state.reasoning_state.seed_from_goal(text, source="user_clarification")
        else:
            state.task.constraints.append(f"steer:{text}")
            state.working_memory.upsert("constraint", text, priority=0.88)

        applied = self._apply_steer_invalidation(state, scope, classified)
        self._emit(
            state,
            "user_steering",
            {**classified.public_dict(), "applied_invalidation": applied},
        )
        state.observations.append(
            CognitiveObservation(
                kind=CognitiveObservationKind.USER_STEERING,
                observation_id=str(uuid.uuid4()),
                summary=text,
                source_type=EpistemicType.USER_STATEMENT,
                success=True,
                payload={**classified.public_dict(), "applied_invalidation": applied},
            )
        )
        self._persist_update(state)
        return {
            **state.public_status(),
            "steering_classification": classified.public_dict(),
            "applied_invalidation": applied,
        }

    def _apply_steer_invalidation(
        self,
        state: CognitiveRunState,
        scope: InvalidationScope,
        classified: Any,
    ) -> dict[str, Any]:
        """Apply scoped invalidation — never a blind full reset."""
        applied: dict[str, Any] = {"scopes": scope.public_dict()}
        if scope.plan and state.plan is not None:
            self.planner.mark_stale(
                state.plan,
                reason=f"user_steer:{classified.kind.value}:{classified.text[:80]}",
            )
            applied["plan_stale"] = True
        if scope.current_action and state.plan is not None:
            # Only reopen in-flight / ready steps — completed steps stay done.
            # PlanStep is frozen; rebuild list.
            reset = 0
            new_steps = []
            for step in state.plan.steps:
                if step.status in {"READY", "RUNNING", "IN_PROGRESS", "PENDING", ""}:
                    from dataclasses import replace as _dc_replace

                    new_steps.append(_dc_replace(step, status="READY"))
                    reset += 1
                else:
                    new_steps.append(step)
            state.plan.steps = new_steps
            applied["plan_steps_reset"] = reset
        if scope.response_draft and state.response_text:
            # Drop unverified draft; keep as observation preview only.
            applied["response_draft_cleared"] = True
            applied["prior_response_preview"] = state.response_text[:200]
            state.response_text = None
        if scope.pending_worker and state.pending_advance_job_id:
            applied["pending_worker_superseded"] = state.pending_advance_job_id
            state.pending_advance_job_id = None
            # Cursor bump so next enqueue_advance uses a fresh idempotency key.
            state.usage.iterations = int(state.usage.iterations or 0) + 1
            if state.status == CognitiveRunStatus.WAITING_WORKER:
                try:
                    self._transition(state, CognitiveRunStatus.REASONING)
                except CognitionTransitionInvalid:
                    state.status = CognitiveRunStatus.REASONING
        if scope.open_hypotheses:
            applied["open_hypotheses_marked"] = len(state.hypothesis_board.open_items())
        applied["truth"] = {
            "invalidation_is_scoped": True,
            "not_blind_full_reset": True,
            "constraints_preserved": not scope.constraints,
        }
        return applied

    def status(self, run_id: str) -> dict[str, Any]:
        return self._require(run_id).public_status()

    def events(self, run_id: str) -> list[dict[str, Any]]:
        state = self._require(run_id)
        if self.store is not None:
            try:
                return self.store.list_events(run_id)
            except Exception:  # noqa: BLE001
                pass
        return list(state.events)

    def resume(self, run_id: str, *, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        state = self._require(run_id, hydrate=True)
        if state.status in TERMINAL_STATUSES and state.status != CognitiveRunStatus.BLOCKED:
            return state.public_status()
        prior = state.status
        if state.status == CognitiveRunStatus.WAITING_APPROVAL:
            self._transition(state, CognitiveRunStatus.REASONING)
        elif state.status == CognitiveRunStatus.BLOCKED:
            # Reopen blocked as replanning only when explicitly resumed.
            state.status = CognitiveRunStatus.REPLANNING
        elif state.status == CognitiveRunStatus.WAITING_WORKER:
            # Restart-safe: re-enqueue durable advance if no pending job, else continue.
            self._emit(
                state,
                "resumed",
                {
                    "from": prior.value,
                    "hydrated": True,
                    "waiting_worker": True,
                    "pending_advance_job_id": state.pending_advance_job_id,
                    "truth": {"restart_safe_waiting_worker": True},
                },
            )
            if self.job_runtime is not None:
                if not state.pending_advance_job_id or not self._advance_job_still_active(
                    state.pending_advance_job_id
                ):
                    return self.enqueue_advance(run_id, max_iterations=1)
                # Job still queued/running — leave WAITING_WORKER.
                self._persist_update(state)
                return state.public_status()
            # No job runtime — advance inline bounded batch.
            return self.advance_external(run_id, max_iterations=1, requeue=False, history=history)

        self._emit(state, "resumed", {"from": prior.value, "hydrated": True})
        # Interrupted-by-restart REASONING with externalize → prefer durable advance.
        from .advance import should_externalize_advance

        if (
            should_externalize_advance(
                mode=state.decision.mode.value if state.decision and state.decision.mode else "DEEP",
                externalize_deep=self.externalize_deep,
                job_runtime_bound=self.job_runtime is not None,
            )
            and state.decision
            and state.decision.mode
            and state.decision.mode.value in {"DEEP", "MAXIMUM"}
        ):
            return self.enqueue_advance(run_id, max_iterations=1)
        return self.run(run_id, history=history)

    def _advance_job_still_active(self, job_id: str) -> bool:
        if self.job_runtime is None:
            return False
        store = getattr(self.job_runtime, "store", None)
        if store is None or not hasattr(store, "get"):
            return False
        try:
            job = store.get(job_id)
        except Exception:  # noqa: BLE001
            return False
        if job is None:
            return False
        state = str(getattr(getattr(job, "state", None), "value", getattr(job, "state", "")) or "")
        return state.upper() in {"QUEUED", "PENDING", "LEASED", "RUNNING", "RETRY"}

    def hydrate(self, run_id: str) -> dict[str, Any]:
        """Load durable cognitive state into the in-process runtime (U122)."""
        state = self._hydrate_from_store(run_id)
        self._runs[run_id] = state
        self._emit(state, "hydrated", {"status": state.status.value})
        return state.public_status()

    def health(self) -> dict[str, Any]:
        active = [
            s for s in self._runs.values() if s.status not in TERMINAL_STATUSES
        ]
        return {
            "enabled": self.enabled,
            "shadow_default": self.shadow_default,
            "iterative": self.iterative,
            "belief_enabled": self.belief_enabled,
            "neuro_enabled": self.neuro_enabled,
            "delegation_enabled": self.delegation_enabled,
            "experience_learning": self.experience_learning,
            "active_runs": len(active),
            "tracked_runs": len(self._runs),
            "delegation_handlers": self.delegation.available(),
            "gateway_wired": self.execution_gateway is not None,
            "behavior_resolver_wired": self.behavior_resolver is not None,
            "truth": {
                "cognition_does_not_bypass_gateway": True,
                "neuro_is_advisory": True,
                "hydrate_reconstructs_live_state": True,
                "behavior_profile_is_canonical_identity": True,
                "no_independent_cognition_identity": True,
            },
        }

    # --- internals ---

    def _require(self, run_id: str, *, hydrate: bool = False) -> CognitiveRunState:
        state = self._runs.get(run_id)
        if state is not None:
            return state
        if self.store is not None:
            row = self.store.get_run(run_id)
            if row is None:
                raise KeyError(f"Unknown cognitive run: {run_id}")
            if hydrate:
                state = self._hydrate_from_store(run_id)
                self._runs[run_id] = state
                return state
            raise KeyError(
                f"Cognitive run {run_id} exists in DB but is not loaded in this process; "
                "call hydrate()/resume() to reconstruct live state"
            )
        raise KeyError(f"Unknown cognitive run: {run_id}")

    def _hydrate_from_store(self, run_id: str) -> CognitiveRunState:
        if self.store is None:
            raise KeyError(f"Unknown cognitive run: {run_id}")
        row = self.store.get_run(run_id)
        if row is None:
            raise KeyError(f"Unknown cognitive run: {run_id}")
        result = dict(row.get("result") or {})
        checkpoint = dict(result.get("checkpoint") or {})
        task = task_from_dict(row.get("task"), run_id=run_id)
        decision = decision_from_parts(
            mode=row.get("mode"),
            strategy=row.get("strategy"),
            budgets=row.get("budgets"),
            decision_blob=checkpoint.get("decision") or result.get("decision"),
        )
        beliefs = self.store.load_beliefs(run_id)
        if not beliefs.items and row.get("beliefs"):
            beliefs = beliefs_from_dict(row.get("beliefs"))
        working_memory = working_memory_from_dict(row.get("working_memory"))
        plan = plan_from_dict(row.get("plan"))
        observations = [
            observation_from_dict(item)
            for item in (checkpoint.get("observations") or result.get("observations") or [])
            if isinstance(item, dict)
        ]
        actions = [
            action_from_dict(item)
            for item in (checkpoint.get("actions") or result.get("actions") or [])
            if isinstance(item, dict)
        ]
        usage = usage_from_dict(row.get("usage") or checkpoint.get("usage"))
        status = status_from_value(row.get("status"))
        # Interrupted non-terminal runs remain resumable; reconcile_interrupted may mark FAILED.
        state = CognitiveRunState(
            run_id=run_id,
            task=task,
            status=status,
            decision=decision,
            plan=plan,
            beliefs=beliefs,
            working_memory=working_memory,
            observations=observations,
            actions=actions,
            usage=usage,
            response_text=result.get("response_text"),
            cancel_requested=bool(checkpoint.get("cancel_requested") or False),
            cancel_acknowledged=bool(checkpoint.get("cancel_acknowledged") or False),
            shadow=bool(row.get("shadow")),
            error=row.get("error"),
            verification_passed=checkpoint.get("verification_passed", result.get("verification_passed")),
            context_public=result.get("context"),
            completion=result.get("completion"),
            experience=result.get("experience"),
            steering=list(checkpoint.get("steering") or []),
            trace_id=row.get("trace_id"),
            reasoning_state=structured_state_from_mapping(
                checkpoint.get("reasoning_state")
                or result.get("reasoning_state")
            ),
            hypothesis_board=hypothesis_board_from_mapping(
                checkpoint.get("hypothesis_board")
                or result.get("hypothesis_board")
            ),
            last_critic_report=(
                dict(checkpoint["critic_report"])
                if isinstance(checkpoint.get("critic_report"), dict)
                else (
                    dict(result["critic_report"])
                    if isinstance(result.get("critic_report"), dict)
                    else None
                )
            ),
            capability_state=capability_state_from_mapping(
                checkpoint.get("capability_state")
                or result.get("capability_state")
            ),
            pending_advance_job_id=(
                str(checkpoint["pending_advance_job_id"])
                if checkpoint.get("pending_advance_job_id")
                else (
                    str(result["pending_advance_job_id"])
                    if result.get("pending_advance_job_id")
                    else None
                )
            ),
        )
        events = self.store.list_events(run_id)
        state.events = list(events)
        return state

    def _transition(self, state: CognitiveRunState, target: CognitiveRunStatus) -> None:
        if not validate_transition(state.status, target):
            raise CognitionTransitionInvalid(
                f"Invalid transition {state.status.value} → {target.value}",
                details={"from": state.status.value, "to": target.value},
            )
        prev = state.status
        state.status = target
        self._emit(state, "status_transition", {"from": prev.value, "to": target.value})
        self._persist_update(state)

    def _perceive(self, state: CognitiveRunState, *, history: list[dict[str, str]] | None) -> None:
        snap = self.perception.perceive(
            state.task.raw_request,
            history=history,
            conversation_id=(state.task.metadata or {}).get("conversation_id"),
            run_id=state.run_id,
            include_neuro=self.neuro_enabled,
            experience_learning=self.experience_learning,
            domain=state.task.domain,
            system_state={
                "resource_pressure": self.resource_pressure_fn(),
                "delegation_handlers": self.delegation.available(),
            },
        )
        state.perception = snap
        self._emit(state, "perception_updated", snap.public_dict())
        if self.belief_enabled:
            for item in snap.by_type(EpistemicType.EXACT_FACT)[:5]:
                state.beliefs.add(
                    item.summary,
                    category=BeliefCategory.FACT,
                    confidence=item.confidence,
                    source_type=EpistemicType.EXACT_FACT,
                    status=BeliefStatus.SUPPORTED,
                    support_refs=[item.source_ref or item.item_id],
                )
            for item in snap.by_type(EpistemicType.EVIDENCE)[:5]:
                state.beliefs.add(
                    item.summary,
                    category=BeliefCategory.FACT,
                    confidence=item.confidence,
                    source_type=EpistemicType.EVIDENCE,
                    status=BeliefStatus.SUPPORTED
                    if item.verification_status in {"VERIFIED", "verified"}
                    else BeliefStatus.PARTIALLY_SUPPORTED,
                    support_refs=[item.source_ref or item.item_id],
                )
            for item in snap.by_type(EpistemicType.NEURAL_ASSOCIATION)[:3]:
                # Advisory only — never FACT.
                state.beliefs.add(
                    item.summary,
                    category=BeliefCategory.HYPOTHESIS,
                    confidence=min(0.4, item.confidence),
                    source_type=EpistemicType.NEURAL_ASSOCIATION,
                    status=BeliefStatus.INFERRED,
                )
                state.working_memory.upsert(
                    "neuro",
                    item.summary,
                    source_type=EpistemicType.NEURAL_ASSOCIATION,
                    priority=0.25,
                )
            # Procedural experience CONTEXT — advisory HYPOTHESIS only, never FACT.
            for item in snap.by_type(EpistemicType.HYPOTHESIS)[:3]:
                if not (item.payload or {}).get("kind") == "procedural_experience_context":
                    continue
                state.beliefs.add(
                    item.summary,
                    category=BeliefCategory.HYPOTHESIS,
                    confidence=min(0.35, item.confidence),
                    source_type=EpistemicType.HYPOTHESIS,
                    status=BeliefStatus.INFERRED,
                )
                state.working_memory.upsert(
                    "experience",
                    item.summary,
                    source_type=EpistemicType.HYPOTHESIS,
                    priority=0.2,
                )
            self._emit(state, "belief_revised", state.beliefs.public_dict())

    def _meta_decide(self, state: CognitiveRunState) -> MetaDecision:
        evidence_items = 0
        if state.perception:
            evidence_items = len(state.perception.by_type(EpistemicType.EVIDENCE)) + len(
                state.perception.by_type(EpistemicType.KNOWLEDGE_SOURCE)
            )
        coverage = min(1.0, evidence_items / 5.0)
        contradictions = len(state.beliefs.contradiction_pairs)
        density = min(1.0, contradictions / 3.0)
        depth = (state.task.metadata or {}).get("user_requested_depth")
        if not depth and self.adaptive_depth:
            policy = getattr(self.meta, "policy", None)
            policy_default = getattr(policy, "default_mode", None) if policy is not None else None
            depth = str(policy_default) if policy_default else "ADAPTIVE"
        # Recent information gain heuristic from observation novelty.
        info_gain = None
        if state.observations:
            recent = state.observations[-3:]
            successes = sum(1 for o in recent if o.success)
            info_gain = successes / max(1, len(recent))
        tool_failures = sum(
            1
            for o in state.observations
            if o.kind.value in {"TOOL_RESULT", "ERROR", "AGENT_RESULT"} and o.success is False
        )
        plan_progress = 0.0
        if state.plan and state.plan.steps:
            done = sum(1 for s in state.plan.steps if s.status in {"DONE", "COMPLETED"})
            plan_progress = done / len(state.plan.steps)
        previous_mode = state.decision.mode if state.decision else None
        policy = getattr(self.meta, "policy", None)
        override = None
        if policy is not None:
            raw_override = getattr(policy, "reasoning_capability_override", None)
            if isinstance(raw_override, dict) and raw_override:
                override = dict(raw_override)
        return self.meta.decide(
            state.task,
            uncertainty=state.beliefs.uncertainty() if self.belief_enabled else state.task.initial_uncertainty,
            evidence_coverage=coverage,
            contradiction_density=density,
            resource_pressure=self.resource_pressure_fn(),
            working_memory_saturation=state.working_memory.saturation(),
            model_available=self.model_caller is not None,
            user_requested_depth=depth,
            previous_mode=previous_mode,
            information_gain_recent=info_gain,
            plan_progress=plan_progress,
            tool_failures=tool_failures,
            repeated_actions=0,
            settings_capability_override=override,
        )

    def _budgets_remaining(self, state: CognitiveRunState) -> dict[str, int]:
        b = state.decision.budgets if state.decision else None
        u = state.usage
        if b is None:
            return {"iterations": 0}
        elapsed = time.monotonic() - (u.started_monotonic or time.monotonic())
        wall_left = b.max_wall_time_seconds - elapsed
        # Token budget depletes from measured usage when available; otherwise
        # from the estimate. Never re-offer the full original max as remaining
        # after consumption.
        tokens_used = u.model_tokens
        if u.input_tokens or u.output_tokens:
            tokens_used = max(tokens_used, u.input_tokens + u.output_tokens)
        return {
            "iterations": max(0, b.max_iterations - u.iterations),
            "model_calls": max(0, b.max_model_calls - u.model_calls),
            "tool_calls": max(0, b.max_tool_calls - u.tool_calls),
            "agent_delegations": max(0, b.max_agent_delegations - u.agent_delegations),
            "replans": max(0, b.max_replans - u.replans),
            "retries": max(0, b.max_retries - u.retries),
            "retrieval_rounds": max(0, b.max_retrieval_rounds - u.retrieval_rounds),
            "critic_passes": max(0, b.max_critic_passes - u.critic_passes),
            "model_tokens": max(0, b.max_model_tokens - tokens_used),
            "wall_ok": 1 if wall_left > 0 else 0,
        }

    def enqueue_advance(
        self,
        run_id: str,
        *,
        max_iterations: int = 1,
        parent_job_id: str | None = None,
    ) -> dict[str, Any]:
        """Enqueue a durable cognition.advance job (API or worker continuation)."""
        from .advance import enqueue_cognition_advance

        state = self._require(run_id, hydrate=True)
        job = enqueue_cognition_advance(
            self.job_runtime,
            run_id=run_id,
            max_iterations=max_iterations,
            cursor_iteration=state.usage.iterations,
            trace_id=state.trace_id,
            parent_job_id=parent_job_id,
        )
        job_id = getattr(job, "job_id", None) or (job.get("job_id") if isinstance(job, dict) else None)
        state.pending_advance_job_id = str(job_id) if job_id else None
        if state.status not in {
            CognitiveRunStatus.WAITING_WORKER,
            *TERMINAL_STATUSES,
        }:
            try:
                if validate_transition(state.status, CognitiveRunStatus.WAITING_WORKER):
                    self._transition(state, CognitiveRunStatus.WAITING_WORKER)
                else:
                    self._persist_update(state)
            except CognitionTransitionInvalid:
                self._persist_update(state)
        else:
            self._persist_update(state)
        self._emit(
            state,
            "cognition_advance_enqueued",
            {
                "job_id": state.pending_advance_job_id,
                "cursor_iteration": state.usage.iterations,
                "max_iterations": max_iterations,
                "truth": {
                    "cognition_advance_is_externalized": True,
                    "not_a_second_runtime": True,
                },
            },
        )
        return {
            **state.public_status(),
            "enqueued_job_id": state.pending_advance_job_id,
        }

    def advance_external(
        self,
        run_id: str,
        *,
        max_iterations: int = 1,
        history: list[dict[str, str]] | None = None,
        requeue: bool = True,
        parent_job_id: str | None = None,
    ) -> dict[str, Any]:
        """Worker entry: advance a bounded batch; optionally re-enqueue if not terminal.

        CognitiveRuntime remains authority — this is not a second runtime.
        """
        from .advance import AdvanceJobResult

        state = self._require(run_id, hydrate=True)
        if state.status in TERMINAL_STATUSES:
            return AdvanceJobResult(
                run_id=run_id,
                status=state.status.value,
                terminal=True,
                iterations_advanced=0,
                pending_job_id=None,
            ).public_dict()

        if state.status == CognitiveRunStatus.WAITING_WORKER:
            try:
                self._transition(state, CognitiveRunStatus.REASONING)
            except CognitionTransitionInvalid:
                state.status = CognitiveRunStatus.REASONING

        if state.decision is None:
            state.decision = self._meta_decide(state)
        if state.plan is None:
            state.plan = self.planner.plan(state.task, state.decision)
            self._record_plan_advice(state, state.plan)

        before = state.usage.iterations
        status = self._iterative_loop(
            state,
            history=history,
            max_iterations=max(1, int(max_iterations)),
        )
        advanced = max(0, state.usage.iterations - before)
        terminal = state.status in TERMINAL_STATUSES
        pending_job_id = None
        if (not terminal) and requeue and self.job_runtime is not None:
            enq = self.enqueue_advance(
                run_id,
                max_iterations=max_iterations,
                parent_job_id=parent_job_id,
            )
            pending_job_id = enq.get("enqueued_job_id") or state.pending_advance_job_id
        elif terminal:
            state.pending_advance_job_id = None
            self._persist_update(state, final=True)

        result = AdvanceJobResult(
            run_id=run_id,
            status=state.status.value,
            terminal=terminal,
            iterations_advanced=advanced,
            pending_job_id=pending_job_id,
        )
        out = result.public_dict()
        out["public_status"] = status
        return out

    def _externalize_iterative(self, state: CognitiveRunState) -> dict[str, Any]:
        """Hand iterative work to cognition.advance worker pool."""
        if self.job_runtime is None:
            return self._iterative_loop(state, history=None)
        return self.enqueue_advance(state.run_id, max_iterations=1)

    def _fast_path(self, state: CognitiveRunState, *, history: list[dict[str, str]] | None) -> dict[str, Any]:
        ctx = self._build_context(state, history=history)
        state.context_public = ctx.public_dict()
        self._emit(state, "context_built", ctx.pack.public_dict())
        text = self._call_model(state, ctx.pack.system_prompt, list(ctx.pack.messages), role="responder")
        state.response_text = text
        state.observations.append(
            CognitiveObservation(
                kind=CognitiveObservationKind.MODEL_RESULT,
                observation_id=str(uuid.uuid4()),
                summary=(text or "")[:500],
                source_type=EpistemicType.MODEL_INFERENCE,
                success=bool(text),
            )
        )
        self._finalize(state)
        return state.public_status()

    def _iterative_loop(
        self,
        state: CognitiveRunState,
        *,
        history: list[dict[str, str]] | None,
        max_iterations: int | None = None,
    ) -> dict[str, Any]:
        detector = self._loops.setdefault(state.run_id, LoopDetector())
        batch = 0
        while True:
            if max_iterations is not None and batch >= max_iterations:
                # Yield to worker continuation — durable externalization checkpoint.
                self._persist_update(state)
                if state.status not in TERMINAL_STATUSES and state.status != CognitiveRunStatus.WAITING_WORKER:
                    try:
                        if validate_transition(state.status, CognitiveRunStatus.WAITING_WORKER):
                            self._transition(state, CognitiveRunStatus.WAITING_WORKER)
                    except CognitionTransitionInvalid:
                        pass
                return state.public_status()
            if state.cancel_requested:
                raise CognitionCancelled("cancellation requested")
            remaining = self._budgets_remaining(state)
            if remaining.get("wall_ok", 1) <= 0 or remaining.get("iterations", 0) <= 0:
                self._finalize(state, budget_exhausted=True)
                return state.public_status()

            # Continuous adaptive re-decision (escalation / de-escalation).
            if self.adaptive_depth and state.usage.iterations > 0:
                prior = state.decision
                state.decision = self._meta_decide(state)
                if prior is None or state.decision.mode != prior.mode or state.decision.escalation:
                    self._emit(state, "meta_decision", state.decision.public_dict())

            state.usage.iterations += 1
            batch += 1
            # Refresh capability matrix each iteration (affordances may change).
            state.capability_state = self._derive_capability_state(state)
            action = self.actions.select(
                task=state.task,
                decision=state.decision,  # type: ignore[arg-type]
                plan=state.plan,
                beliefs=state.beliefs,
                working_memory=state.working_memory,
                observations=state.observations,
                budgets_remaining=remaining,
                cancel_requested=state.cancel_requested,
                capability_state=state.capability_state,
            )
            state.actions.append(action)
            self._emit(state, "action_requested", action.public_dict())

            loop_info = detector.observe(action)
            if loop_info["loop_detected"]:
                # Prefer replan before hard fail when budget remains.
                if remaining.get("replans", 0) > 0 and state.plan is not None:
                    self._emit(state, "loop_replan", loop_info)
                    state.plan.stale = True
                    state.usage.replans += 1
                    replan_action = CognitiveAction(
                        kind=CognitiveActionKind.REPLAN,
                        action_id=str(uuid.uuid4()),
                        rationale="loop detected — level-3 replan",
                        arguments={"reason": "loop_detected", "level": 3},
                    )
                    state.actions.append(replan_action)
                    self._execute_action(state, replan_action, history=history)
                    detector = LoopDetector()
                    self._loops[state.run_id] = detector
                    continue
                raise CognitionLoopDetected(
                    "repeated ineffective action signature",
                    details=loop_info,
                )

            obs = self._execute_action(state, action, history=history)
            if obs is not None:
                state.observations.append(obs)
                state.working_memory.add_observation(obs.summary, source_type=obs.source_type)
                self._emit(state, "observation_added", obs.public_dict())
                # Link observation evidence into the public hypothesis board.
                touched = state.hypothesis_board.apply_observation_evidence(
                    observation_id=obs.observation_id,
                    summary=obs.summary or "",
                    success=obs.success,
                    evidence_refs=list(obs.evidence_refs or []),
                )
                if touched:
                    self._emit(
                        state,
                        "hypothesis_board",
                        {
                            **state.hypothesis_board.public_dict(),
                            "touched_ids": touched,
                        },
                    )
                # Advance plan step if action referenced one.
                step_id = (action.arguments or {}).get("step_id")
                if step_id and state.plan is not None:
                    for step in state.plan.steps:
                        if step.step_id == step_id:
                            step.status = "DONE" if obs.success is not False else "FAILED"
                if self.belief_enabled and obs.success is False:
                    state.beliefs.add(
                        f"action failed: {action.kind.value}",
                        category=BeliefCategory.UNKNOWN,
                        confidence=0.3,
                        source_type=EpistemicType.TOOL_OBSERVATION,
                        status=BeliefStatus.UNVERIFIED,
                        support_refs=[obs.observation_id],
                    )
                # Research agent results become evidence-linked beliefs / response seed.
                if (
                    obs.kind == CognitiveObservationKind.AGENT_RESULT
                    and obs.success
                    and obs.payload.get("metadata", {}).get("report_excerpt")
                ):
                    excerpt = obs.payload["metadata"]["report_excerpt"]
                    if not state.response_text:
                        state.response_text = excerpt
                    if self.belief_enabled:
                        state.beliefs.add(
                            excerpt[:400],
                            category=BeliefCategory.HYPOTHESIS,
                            confidence=0.55,
                            source_type=EpistemicType.EVIDENCE,
                            status=BeliefStatus.PARTIALLY_SUPPORTED,
                            support_refs=list(obs.evidence_refs),
                            provenance={"research_project": obs.payload.get("metadata", {}).get("project_id")},
                        )

            if action.kind in {CognitiveActionKind.COMPLETE, CognitiveActionKind.FAIL, CognitiveActionKind.ASK_USER}:
                if action.kind == CognitiveActionKind.ASK_USER:
                    self._transition(state, CognitiveRunStatus.BLOCKED)
                    state.completion = {
                        "status": "BLOCKED",
                        "reason": "awaiting user clarification",
                        "questions": action.arguments.get("questions"),
                    }
                    self._persist_update(state)
                    return state.public_status()
                self._finalize(
                    state,
                    failed_reason=action.arguments.get("status") if action.kind == CognitiveActionKind.FAIL else None,
                    budget_exhausted=action.arguments.get("status") == "RESOURCE_EXHAUSTED",
                    cancelled=action.arguments.get("status") == "CANCELLED",
                )
                return state.public_status()

            # Critic pass (targeted — DEEP/MAXIMUM, high risk, contradictions)
            critic_justified = bool(
                state.decision
                and remaining.get("critic_passes", 0) > 0
                and (
                    state.decision.value_scores.get("critic", 0) >= 0.4
                    or state.decision.mode.value in {"DEEP", "MAXIMUM"}
                    or state.task.risk_class in {RiskClass.HIGH, RiskClass.CRITICAL}
                )
                and state.usage.iterations >= 2
            )
            if critic_justified:
                state.usage.critic_passes += 1
                critic = self._process_critic(state)
                self._emit(state, "critic_triggered", critic)
                if critic.get("recommend") == "replan" and remaining.get("replans", 0) > 0:
                    action = CognitiveAction(
                        kind=CognitiveActionKind.REPLAN,
                        action_id=str(uuid.uuid4()),
                        rationale="critic recommended replan",
                        arguments={"reason": critic.get("reason", "critic"), "level": 2},
                    )
                    state.actions.append(action)
                    self._execute_action(state, action, history=history)

            if state.response_text and state.verification_passed is True:
                self._finalize(state)
                return state.public_status()
            if state.response_text and state.task.task_type == "simple_chat":
                self._finalize(state)
                return state.public_status()

    def _execute_action(
        self,
        state: CognitiveRunState,
        action: CognitiveAction,
        *,
        history: list[dict[str, str]] | None,
    ) -> CognitiveObservation | None:
        # Enforce cognitive CapabilityState before privileged kinds.
        blocked = self._capability_block_observation(state, action)
        if blocked is not None:
            return blocked
        kind = action.kind
        if kind == CognitiveActionKind.RETRIEVE:
            self._transition(state, CognitiveRunStatus.PERCEIVING)
            state.usage.retrieval_rounds += 1
            self._perceive(state, history=history)
            self._transition(state, CognitiveRunStatus.REASONING)
            return CognitiveObservation(
                kind=CognitiveObservationKind.RETRIEVAL_RESULT,
                observation_id=str(uuid.uuid4()),
                summary=f"retrieved {len(state.perception.items) if state.perception else 0} perception items",
                source_type=EpistemicType.SYSTEM_STATE,
                success=True,
                payload=state.perception.public_dict() if state.perception else {},
            )

        if kind == CognitiveActionKind.SEARCH_CAPABILITY:
            short = self.broker.shortlist_for_task(goal=state.task.goal, domain=state.task.domain)
            for cid in short.capability_ids:
                state.working_memory.upsert("capability", cid, priority=0.45)
            self._emit(state, "capability_searched", short.public_dict())
            return CognitiveObservation(
                kind=CognitiveObservationKind.SYSTEM_STATE,
                observation_id=str(uuid.uuid4()),
                summary=f"shortlisted {len(short.capability_ids)} capabilities",
                success=True,
                payload=short.public_dict(),
            )

        if kind == CognitiveActionKind.REPLAN:
            state.usage.replans += 1
            self._transition(state, CognitiveRunStatus.REPLANNING)
            decision = self._meta_decide(state)
            state.decision = decision
            state.plan = self.planner.replan(
                state.task,
                decision,
                previous=state.plan,
                reason=str(action.arguments.get("reason", "replan")),
                observations=state.observations,
            )
            self._emit(state, "plan_revised", state.plan.public_dict())
            self._transition(state, CognitiveRunStatus.REASONING)
            return CognitiveObservation(
                kind=CognitiveObservationKind.SYSTEM_STATE,
                observation_id=str(uuid.uuid4()),
                summary=f"replanned strategy={state.plan.strategy.value}",
                success=True,
            )

        if kind == CognitiveActionKind.DELEGATE_AGENT:
            if not self.delegation_enabled:
                return CognitiveObservation(
                    kind=CognitiveObservationKind.ERROR,
                    observation_id=str(uuid.uuid4()),
                    summary="delegation feature disabled",
                    success=False,
                    error="COGNITION_DELEGATION_DISABLED",
                )
            agent_kind = str(action.arguments.get("agent_kind") or "generic")
            goal = str(action.arguments.get("goal") or state.task.goal)
            # Idempotent: do not re-create irreversible specialist side effects.
            prior_agent = next(
                (
                    o
                    for o in state.observations
                    if o.kind == CognitiveObservationKind.AGENT_RESULT
                    and (o.payload or {}).get("metadata", {}).get("side_effect_duplicated") is False
                    and (
                        agent_kind.lower() in str((o.payload or {}).get("metadata", {})).lower()
                        or goal[:80] in (o.summary or "")
                        or any(agent_kind in ref for ref in o.artifact_refs)
                        or any(
                            str((o.payload or {}).get("metadata", {}).get(k) or "")
                            for k in ("session_id", "project_id")
                        )
                    )
                    and o.success is not False
                ),
                None,
            )
            # Stronger idempotency: same agent_kind already produced an artifact ref.
            prior_same_kind = next(
                (
                    o
                    for o in state.observations
                    if o.kind == CognitiveObservationKind.AGENT_RESULT
                    and o.success is not False
                    and (
                        any(
                            ref.startswith("coding_session:")
                            for ref in o.artifact_refs
                        )
                        and agent_kind.lower().startswith("coding")
                    )
                    or (
                        any(
                            ref.startswith("research_project:")
                            for ref in o.artifact_refs
                        )
                        and agent_kind.lower().startswith("research")
                    )
                ),
                None,
            )
            reuse = prior_same_kind or prior_agent
            if reuse is not None:
                return CognitiveObservation(
                    kind=CognitiveObservationKind.AGENT_RESULT,
                    observation_id=str(uuid.uuid4()),
                    summary=f"idempotent reuse of prior delegation: {reuse.summary}",
                    source_type=EpistemicType.TOOL_OBSERVATION,
                    success=True,
                    evidence_refs=reuse.evidence_refs,
                    artifact_refs=reuse.artifact_refs,
                    payload={
                        **(reuse.payload or {}),
                        "idempotent_reuse": True,
                        "side_effect_duplicated": False,
                    },
                )
            state.usage.agent_delegations += 1
            self._transition(state, CognitiveRunStatus.EXECUTING)
            meta = {
                "conversation_id": (state.task.metadata or {}).get("conversation_id"),
                "research_mode": action.arguments.get("research_mode")
                or getattr(state.task, "research_mode", "none"),
                "allow_web": bool(
                    action.arguments.get("allow_web")
                    if "allow_web" in action.arguments
                    else getattr(state.task, "requires_current_information", False)
                ),
                "hard_constraints": list(
                    action.arguments.get("hard_constraints")
                    or getattr(state.task, "hard_constraints", None)
                    or state.task.constraints
                ),
                "run_now": bool(
                    getattr(state.task, "research_mode", "none") in {"assisted", "deep", "maximum"}
                    or getattr(state.task, "requires_research", False)
                ),
            }
            # Pass prior IDs if present in working memory for resume.
            for item in state.working_memory.items.values():
                if item.kind == "artifact" and item.content.startswith("coding_session:"):
                    meta["existing_session_id"] = item.content.split(":", 1)[-1]
                if item.kind == "artifact" and item.content.startswith("research_project:"):
                    meta["existing_project_id"] = item.content.split(":", 1)[-1]
            req = self.delegation.build_request(
                goal=goal,
                agent_kind=agent_kind,
                task_ref=state.task.task_id,
                success_criteria=list(action.arguments.get("success_criteria") or state.task.success_criteria),
                authority_ceiling=str(action.arguments.get("authority_ceiling") or state.task.risk_class.value),
                budget=state.decision.budgets.public_dict() if state.decision else {},
                parent_trace_id=state.trace_id,
                required_evidence=list(state.task.required_evidence),
            )
            req.metadata.update(meta)
            self._emit(state, "agent_delegated", req.public_dict())
            result = self.delegation.delegate(req)
            for ref in result.artifact_refs:
                state.working_memory.upsert("artifact", ref, priority=0.7, verified=True)
            self._transition(state, CognitiveRunStatus.OBSERVING)
            category = None
            if result.error or result.status in {"FAILED", "UNAVAILABLE"}:
                category = classify_failure(
                    error=result.error,
                    observation_summary=result.summary,
                    payload=result.public_dict(),
                )
            return CognitiveObservation(
                kind=CognitiveObservationKind.AGENT_RESULT,
                observation_id=str(uuid.uuid4()),
                summary=result.summary,
                source_type=EpistemicType.TOOL_OBSERVATION,
                success=result.status
                in {
                    "COMPLETED",
                    "COMPLETED_VERIFIED",
                    "OK",
                    "SUCCESS",
                    "PARTIAL",
                    "ACCEPTED",
                    "RUNNING",
                    "WAITING_APPROVAL",
                    "QUEUED",
                },
                error=result.error,
                evidence_refs=tuple(result.evidence_refs),
                artifact_refs=tuple(result.artifact_refs),
                payload={
                    **result.public_dict(),
                    "failure_category": category.value if category else None,
                    "blind_retry_forbidden": (
                        category is not None and not should_blind_retry(category)
                    ),
                },
            )

        if kind == CognitiveActionKind.INVOKE_CAPABILITY:
            if self.execution_gateway is None:
                return CognitiveObservation(
                    kind=CognitiveObservationKind.ERROR,
                    observation_id=str(uuid.uuid4()),
                    summary="ExecutionGateway unavailable",
                    success=False,
                    error="COGNITION_CAPABILITY_UNAVAILABLE",
                )
            capability_id = action.capability_id or str(action.arguments.get("capability_id") or "")
            if not capability_id:
                return CognitiveObservation(
                    kind=CognitiveObservationKind.ERROR,
                    observation_id=str(uuid.uuid4()),
                    summary="INVOKE_CAPABILITY missing capability_id",
                    success=False,
                    error="COGNITION_CAPABILITY_ID_REQUIRED",
                )
            # Idempotent replay: if this action_id already produced a TOOL_RESULT, reuse it.
            prior = next(
                (
                    o
                    for o in state.observations
                    if o.kind == CognitiveObservationKind.TOOL_RESULT
                    and o.payload.get("action_id") == action.action_id
                    and o.payload.get("capability_id") == capability_id
                ),
                None,
            )
            if prior is not None:
                self._emit(
                    state,
                    "capability_idempotent_replay",
                    {"action_id": action.action_id, "capability_id": capability_id},
                )
                return prior

            state.usage.tool_calls += 1
            self._transition(state, CognitiveRunStatus.EXECUTING)
            try:
                from Data.modules.execution import CapabilityRequest

                request = CapabilityRequest(
                    capability_id=capability_id,
                    arguments=dict(action.arguments),
                    request_id=action.action_id,
                    run_id=state.run_id,
                    requested_by="cognition",
                    trace_id=state.trace_id,
                    idempotency_key=f"cog:{state.run_id}:{action.action_id}",
                    approval_id=action.arguments.get("approval_id"),
                )
                self._emit(
                    state,
                    "capability_invoked",
                    {
                        "capability_id": capability_id,
                        "request_id": action.action_id,
                        "trace_id": state.trace_id,
                    },
                )
                result = self.execution_gateway.execute(request)
                result_dict = result.public_dict() if hasattr(result, "public_dict") else dict(result)
                status_value = str(result_dict.get("status") or "")
                success = status_value in {"COMPLETED", "OK", "SUCCESS"}
                telemetry = result_dict.get("telemetry") if isinstance(result_dict.get("telemetry"), dict) else {}
                receipt_id = telemetry.get("receipt_id") if isinstance(telemetry, dict) else None
                evidence_refs: list[str] = []
                artifact_refs: list[str] = []
                if receipt_id:
                    evidence_refs.append(f"receipt:{receipt_id}")
                # Surface file/artifact refs from capability output when present.
                output = result_dict.get("output") if isinstance(result_dict.get("output"), dict) else {}
                for key in ("artifact_id", "artifact_ref"):
                    if output.get(key):
                        raw = str(output[key])
                        artifact_refs.append(raw if ":" in raw else f"artifact:{raw}")
                for key in ("path", "file_path", "written_path"):
                    if output.get(key):
                        evidence_refs.append(f"file:{output[key]}")
                self._transition(state, CognitiveRunStatus.OBSERVING)
                return CognitiveObservation(
                    kind=CognitiveObservationKind.TOOL_RESULT,
                    observation_id=str(uuid.uuid4()),
                    summary=(
                        f"capability {capability_id} → {status_value}"
                        if status_value
                        else f"capability {capability_id} executed"
                    ),
                    source_type=EpistemicType.TOOL_OBSERVATION,
                    success=success,
                    error=result_dict.get("error"),
                    evidence_refs=tuple(evidence_refs),
                    artifact_refs=tuple(artifact_refs),
                    payload={
                        "action_id": action.action_id,
                        "capability_id": capability_id,
                        "result": result_dict,
                        "receipt_id": receipt_id,
                        "idempotency_key": f"cog:{state.run_id}:{action.action_id}",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._transition(state, CognitiveRunStatus.OBSERVING)
                return CognitiveObservation(
                    kind=CognitiveObservationKind.ERROR,
                    observation_id=str(uuid.uuid4()),
                    summary=f"capability invoke failed: {exc}",
                    success=False,
                    error=str(exc),
                    payload={"action_id": action.action_id, "capability_id": capability_id},
                )

        if kind == CognitiveActionKind.VERIFY:
            self._transition(state, CognitiveRunStatus.VERIFYING)
            self._emit(state, "verification_started", {"criteria": action.arguments.get("criteria")})
            passed = self._verify(state)
            state.verification_passed = passed
            self._emit(
                state,
                "verification_passed" if passed else "verification_failed",
                {"passed": passed},
            )
            return CognitiveObservation(
                kind=CognitiveObservationKind.VERIFICATION_RESULT,
                observation_id=str(uuid.uuid4()),
                summary=f"verification_passed={passed}",
                success=passed,
                payload={"passed": passed},
            )

        if kind in {CognitiveActionKind.MODEL_CALL, CognitiveActionKind.RESPOND}:
            self._transition(state, CognitiveRunStatus.REASONING)
            shortlist = [i.content for i in state.working_memory.list_by_kind("capability")]
            ctx = self._build_context(state, history=history, capability_shortlist=shortlist)
            state.context_public = ctx.public_dict()
            role = str(action.arguments.get("role") or "responder")
            text = self._call_model(state, ctx.pack.system_prompt, list(ctx.pack.messages), role=role)
            state.response_text = text
            if action.arguments.get("purpose") == "hypothesis" and text and self.belief_enabled:
                state.beliefs.add(
                    text[:400],
                    category=BeliefCategory.HYPOTHESIS,
                    confidence=0.55,
                    source_type=EpistemicType.MODEL_INFERENCE,
                    status=BeliefStatus.INFERRED,
                )
                self._emit(state, "belief_added", {"proposition": text[:200]})
            if action.arguments.get("purpose") == "hypothesis" and text:
                parent_id = action.arguments.get("parent_hypothesis_id")
                if parent_id:
                    hyp = state.hypothesis_board.branch(
                        str(parent_id),
                        text[:500],
                        prior_plausibility=0.5,
                        domain=state.task.domain or "general",
                        metadata={"source": "model_hypothesis"},
                    )
                else:
                    hyp = state.hypothesis_board.add(
                        text[:500],
                        prior_plausibility=0.5,
                        domain=state.task.domain or "general",
                        metadata={"source": "model_hypothesis"},
                    )
                if hyp is not None:
                    self._emit(
                        state,
                        "hypothesis_board",
                        {
                            **state.hypothesis_board.public_dict(),
                            "added_id": hyp.hypothesis_id,
                        },
                    )
            return CognitiveObservation(
                kind=CognitiveObservationKind.MODEL_RESULT,
                observation_id=str(uuid.uuid4()),
                summary=(text or "")[:500],
                source_type=EpistemicType.MODEL_INFERENCE,
                success=bool(text),
                payload={"role": role},
            )

        if kind == CognitiveActionKind.REQUEST_APPROVAL:
            self._transition(state, CognitiveRunStatus.WAITING_APPROVAL)
            return CognitiveObservation(
                kind=CognitiveObservationKind.APPROVAL_RESULT,
                observation_id=str(uuid.uuid4()),
                summary="approval required — not auto-approved",
                success=None,
                payload={"requires_approval": True},
            )

        if kind == CognitiveActionKind.WAIT:
            return CognitiveObservation(
                kind=CognitiveObservationKind.SYSTEM_STATE,
                observation_id=str(uuid.uuid4()),
                summary="wait",
                success=True,
            )

        return None

    def _resolve_behavior_identity(
        self,
        *,
        message: str,
        history: list[dict[str, str]] | None,
        behavior_profile_prompt: str | None,
        behavior_profile_id: str | None,
        behavior_profile_version: str | None,
        behavior_settings_hash: str | None,
        behavior_source: str | None,
    ) -> dict[str, Any]:
        """Resolve the same effective BehaviorProfile plane as Chat.

        Caller-supplied snapshot wins. Otherwise use Settings resolver when wired.
        Seed is only the first-install/default when neither is available.
        """
        prompt = (behavior_profile_prompt or "").strip()
        if prompt:
            return {
                "prompt": prompt,
                "profile_id": behavior_profile_id,
                "version": behavior_profile_version,
                "settings_hash": behavior_settings_hash,
                "source": behavior_source or "caller",
            }
        resolver = self.behavior_resolver
        if resolver is not None and hasattr(resolver, "resolve"):
            recent = [
                str(m.get("content") or "")
                for m in (history or [])
                if m.get("role") == "user" and m.get("content")
            ]
            try:
                snap = resolver.resolve(
                    latest_user_message=message,
                    recent_user_messages=recent[-6:],
                )
            except Exception:  # noqa: BLE001 — never invent a second identity on resolver failure
                snap = None
            if snap is not None:
                profile = getattr(snap, "profile", None)
                return {
                    "prompt": str(getattr(snap, "system_prompt", "") or "").strip() or None,
                    "profile_id": getattr(profile, "id", None) if profile is not None else None,
                    "version": str(getattr(snap, "version", "") or getattr(profile, "version", "") or "")
                    or None,
                    "settings_hash": getattr(snap, "settings_hash", None),
                    "source": getattr(snap, "source", None) or "behavior_resolver",
                }
        return {
            "prompt": None,
            "profile_id": behavior_profile_id,
            "version": behavior_profile_version,
            "settings_hash": behavior_settings_hash,
            "source": behavior_source or "seed_default",
        }

    def _build_context(
        self,
        state: CognitiveRunState,
        *,
        history: list[dict[str, str]] | None,
        capability_shortlist: list[str] | None = None,
    ) -> Any:
        return self.context_builder.build(
            task=state.task,
            working_memory=state.working_memory,
            beliefs=state.beliefs if self.belief_enabled else None,
            perception=state.perception,
            plan=state.plan,
            capability_shortlist=capability_shortlist,
            history=history,
            token_budget=state.decision.budgets.max_context_tokens if state.decision else None,
            behavior_profile_prompt=state.behavior_profile_prompt,
            behavior_profile_id=state.behavior_profile_id,
            behavior_profile_version=state.behavior_profile_version,
            behavior_settings_hash=state.behavior_settings_hash,
            behavior_source=state.behavior_source,
        )

    def _call_model(
        self,
        state: CognitiveRunState,
        system_prompt: str,
        messages: list[dict[str, str]],
        *,
        role: str,
    ) -> str | None:
        remaining = self._budgets_remaining(state)
        if remaining.get("model_calls", 0) <= 0:
            return state.response_text
        if remaining.get("model_tokens", 1) <= 0:
            self._emit(state, "token_budget_exhausted", {"role": role})
            return state.response_text
        state.usage.model_calls += 1
        if self.model_caller is None:
            # Honest unavailable — do not fabricate answer.
            self._emit(state, "model_unavailable", {"role": role})
            return None
        # Pass remaining token budget, not the original full ceiling.
        remaining_tokens = remaining.get("model_tokens")
        if remaining_tokens is None and state.decision:
            remaining_tokens = state.decision.budgets.max_model_tokens
        max_tokens = int(remaining_tokens or 2000)
        neural_budget = state.decision.neural_budgets if state.decision else None
        capability_profile = state.decision.capability_profile if state.decision else None
        reasoning_mode = state.decision.mode.value if state.decision else None
        remaining_calls = remaining.get("model_calls")
        override = None
        policy = getattr(self.meta, "policy", None)
        if policy is not None:
            raw_override = getattr(policy, "reasoning_capability_override", None)
            if isinstance(raw_override, dict) and raw_override:
                override = dict(raw_override)
        try:
            result = self.model_caller(
                system_prompt=system_prompt,
                messages=messages,
                role=role,
                run_id=state.run_id,
                trace_id=state.trace_id,
                max_tokens=max_tokens,
                neural_budget=neural_budget,
                capability_profile=capability_profile,
                reasoning_mode=reasoning_mode,
                settings_capability_override=override,
                remaining_model_calls=remaining_calls,
            )
            usage: dict[str, Any] = {}
            usage_source = "unavailable"
            if isinstance(result, tuple):
                text = result[0]
            elif isinstance(result, dict):
                text = result.get("text") or result.get("content")
                usage = result.get("usage") or {}
                usage_source = str(result.get("usage_source") or "unavailable")
                # Account for TTC multi-candidate fan-out (we already counted 1).
                consumed = int(result.get("model_calls_consumed") or 1)
                if consumed > 1:
                    state.usage.model_calls += consumed - 1
                # Public telemetry only — never private CoT.
                inference_meta = result.get("inference_compute")
                if isinstance(inference_meta, dict):
                    state.reasoning_state.ingest_inference_compute(inference_meta)
                    self._emit(
                        state,
                        "inference_compute",
                        {
                            "path": inference_meta.get("path"),
                            "native_effort_requested": inference_meta.get("native_effort_requested"),
                            "native_effort_effective": inference_meta.get("native_effort_effective"),
                            "reasoning_tokens": inference_meta.get("reasoning_tokens"),
                            "reasoning_tokens_status": inference_meta.get(
                                "reasoning_tokens_status", "UNMEASURED"
                            ),
                            "provider_hints_sent": inference_meta.get("provider_hints_sent"),
                            "model_calls_consumed": inference_meta.get("model_calls_consumed"),
                            "ttc": inference_meta.get("ttc"),
                            "truth": inference_meta.get("truth"),
                        },
                    )
                    self._emit(
                        state,
                        "reasoning_state",
                        state.reasoning_state.public_dict(),
                    )
            else:
                text = result
            text_s = str(text) if text is not None else None
            self._record_token_usage(state, text_s, usage=usage, usage_source=usage_source)
            return text_s
        except Exception as exc:  # noqa: BLE001
            self._emit(state, "model_error", {"error": f"{type(exc).__name__}: {exc}"})
            return None

    def _record_token_usage(
        self,
        state: CognitiveRunState,
        text: str | None,
        *,
        usage: dict[str, Any],
        usage_source: str,
    ) -> None:
        """Prefer provider usage; fall back to estimate with honest source label."""
        in_tok = usage.get("input_tokens") or usage.get("prompt_tokens")
        out_tok = usage.get("output_tokens") or usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if usage_source == "provider" and (in_tok is not None or out_tok is not None or total is not None):
            inp = int(in_tok or 0)
            out = int(out_tok or 0)
            tot = int(total) if total is not None else inp + out
            state.usage.input_tokens += inp
            state.usage.output_tokens += out
            state.usage.model_tokens += max(tot, inp + out)
            state.usage.token_usage_source = "provider"
            return
        if text:
            # Heuristic only — never labeled as provider usage.
            estimate = max(1, len(text) // 4)
            state.usage.output_tokens += estimate
            state.usage.model_tokens += estimate
            if state.usage.token_usage_source != "provider":
                state.usage.token_usage_source = "estimate"

    def _derive_capability_state(self, state: CognitiveRunState) -> CapabilityState:
        return derive_capability_state(
            task=state.task,
            model_available=self.model_caller is not None,
            execution_gateway_available=self.execution_gateway is not None,
            delegation_enabled=self.delegation_enabled,
            network_outbound_allowed=self.network_outbound_allowed,
            cognition_enabled=self.enabled,
        )

    def _capability_block_observation(
        self,
        state: CognitiveRunState,
        action: CognitiveAction,
    ) -> CognitiveObservation | None:
        """Return an error observation when CapabilityState blocks the action."""
        cs = state.capability_state
        kind = action.kind
        axis: CapabilityAxis | None = None
        if kind in {CognitiveActionKind.MODEL_CALL, CognitiveActionKind.RESPOND}:
            axis = CapabilityAxis.GENERATE
        elif kind == CognitiveActionKind.INVOKE_CAPABILITY:
            axis = CapabilityAxis.EXECUTE
            # Filesystem writes additionally need write_filesystem axis.
            side = str(action.arguments.get("side_effect") or "").lower()
            caps = str(action.capability_id or action.arguments.get("capability_id") or "").lower()
            if "filesystem" in side or "write" in caps or "fs." in caps:
                if cs.blocks(CapabilityAxis.WRITE_FILESYSTEM) and not cs.allows(
                    CapabilityAxis.WRITE_FILESYSTEM
                ):
                    if cs.axis(CapabilityAxis.WRITE_FILESYSTEM) == AxisState.REQUIRES_APPROVAL:
                        if not action.arguments.get("approval_id"):
                            self._emit(
                                state,
                                "capability_state_blocked",
                                {
                                    "action": kind.value,
                                    "axis": "write_filesystem",
                                    "state": cs.write_filesystem.value,
                                },
                            )
                            return CognitiveObservation(
                                kind=CognitiveObservationKind.APPROVAL_RESULT,
                                observation_id=str(uuid.uuid4()),
                                summary="filesystem write requires approval (capability_state)",
                                success=None,
                                payload={
                                    "requires_approval": True,
                                    "axis": "write_filesystem",
                                    "capability_state": cs.public_dict(),
                                },
                            )
                    elif cs.blocks(CapabilityAxis.WRITE_FILESYSTEM):
                        self._emit(
                            state,
                            "capability_state_blocked",
                            {
                                "action": kind.value,
                                "axis": "write_filesystem",
                                "state": cs.write_filesystem.value,
                            },
                        )
                        return CognitiveObservation(
                            kind=CognitiveObservationKind.ERROR,
                            observation_id=str(uuid.uuid4()),
                            summary="filesystem write denied by capability_state",
                            success=False,
                            error="COGNITION_CAPABILITY_WRITE_DENIED",
                            payload={"capability_state": cs.public_dict()},
                        )
        elif kind == CognitiveActionKind.DELEGATE_AGENT:
            axis = CapabilityAxis.DELEGATE
            if bool(action.arguments.get("allow_web")):
                if cs.blocks(CapabilityAxis.NETWORK):
                    self._emit(
                        state,
                        "capability_state_blocked",
                        {
                            "action": kind.value,
                            "axis": "network",
                            "state": cs.network.value,
                        },
                    )
                    return CognitiveObservation(
                        kind=CognitiveObservationKind.ERROR,
                        observation_id=str(uuid.uuid4()),
                        summary="outbound network denied by capability_state",
                        success=False,
                        error="COGNITION_CAPABILITY_NETWORK_DENIED",
                        payload={"capability_state": cs.public_dict()},
                    )
        elif kind == CognitiveActionKind.RETRIEVE:
            # Retrieval may be local; only block when task requires current info and network denied
            # and retrieval explicitly requested web — otherwise allow local Knowledge path.
            if bool(action.arguments.get("allow_web")) and cs.blocks(CapabilityAxis.NETWORK):
                self._emit(
                    state,
                    "capability_state_blocked",
                    {"action": kind.value, "axis": "network", "state": cs.network.value},
                )
                return CognitiveObservation(
                    kind=CognitiveObservationKind.ERROR,
                    observation_id=str(uuid.uuid4()),
                    summary="web retrieval denied by capability_state",
                    success=False,
                    error="COGNITION_CAPABILITY_NETWORK_DENIED",
                    payload={"capability_state": cs.public_dict()},
                )
            return None

        if axis is None:
            return None

        state_axis = cs.axis(axis)
        if state_axis == AxisState.ALLOWED:
            return None
        if state_axis == AxisState.REQUIRES_APPROVAL:
            if action.arguments.get("approval_id"):
                return None
            self._emit(
                state,
                "capability_state_blocked",
                {"action": kind.value, "axis": axis.value, "state": state_axis.value},
            )
            return CognitiveObservation(
                kind=CognitiveObservationKind.APPROVAL_RESULT,
                observation_id=str(uuid.uuid4()),
                summary=f"{axis.value} requires approval (capability_state)",
                success=None,
                payload={
                    "requires_approval": True,
                    "axis": axis.value,
                    "capability_state": cs.public_dict(),
                },
            )
        # DENIED / UNAVAILABLE / UNKNOWN → hard block for privileged kinds
        if state_axis in {AxisState.DENIED, AxisState.UNAVAILABLE}:
            self._emit(
                state,
                "capability_state_blocked",
                {"action": kind.value, "axis": axis.value, "state": state_axis.value},
            )
            return CognitiveObservation(
                kind=CognitiveObservationKind.ERROR,
                observation_id=str(uuid.uuid4()),
                summary=f"{axis.value} blocked by capability_state ({state_axis.value})",
                success=False,
                error=f"COGNITION_CAPABILITY_{axis.value.upper()}_BLOCKED",
                payload={"capability_state": cs.public_dict(), "axis": axis.value},
            )
        return None

    def _verify(self, state: CognitiveRunState) -> bool:
        if self.verification_engine is None:
            # Without VerificationEngine, never claim verified.
            return False
        try:
            from .verification_bridge import (
                build_verification_plan,
                collapse_or_groups,
                materialize_evidence_claims,
            )

            plan = build_verification_plan(
                required_evidence=getattr(state.task, "required_evidence", None) or [],
                observations=state.observations,
            )
            collected = plan["collected"]
            requirements = list(plan["requirements"])
            or_groups = dict(plan.get("or_groups") or {})

            # Materialize research/file/receipt evidence into the Evidence store when available.
            materialize_evidence_claims(
                collected,
                evidence_service=self.evidence_service,
                run_id=state.run_id,
                receipt_lookup=self.receipt_store,
                research_lookup=self.research_lookup,
            )
            self._emit(
                state,
                "verification_plan",
                {
                    "collected": collected.public_dict(),
                    "requirement_count": len(requirements),
                    "or_groups": {k: list(v) for k, v in or_groups.items()},
                    "truth": plan.get("truth"),
                },
            )

            if not requirements:
                self._emit(
                    state,
                    "verification_unmeasured",
                    {"reason": "no_typed_requirements"},
                )
                return False

            if not hasattr(self.verification_engine, "verify"):
                self._emit(
                    state,
                    "verification_protocol_error",
                    {"error": "VerificationEngine missing verify()"},
                )
                return False

            report = self.verification_engine.verify(
                requirements,
                run_id=state.run_id,
            )
            if or_groups:
                report = collapse_or_groups(report, or_groups)
            outcome = getattr(report, "outcome", None)
            outcome_s = str(getattr(outcome, "value", outcome)).upper()
            self._emit(
                state,
                "verification_report",
                report.public_dict() if hasattr(report, "public_dict") else {"outcome": outcome_s},
            )
            return outcome_s == "PASSED"
        except Exception as exc:  # noqa: BLE001
            self._emit(state, "verification_error", {"error": str(exc)})
        return False

    def _process_critic(self, state: CognitiveRunState) -> dict[str, Any]:
        self._transition(state, CognitiveRunStatus.CRITIQUING)
        ctx = self._critic_context(state)
        report: CriticMeshReport = self.critic_mesh.evaluate(ctx)
        out = report.public_dict()
        state.last_critic_report = out
        # Mirror mesh findings into public structured critiques (not private CoT).
        for finding in report.findings:
            state.reasoning_state.add_critique(
                f"{finding.critic_id}:{finding.finding}"
            )
        self._emit(state, "critic_mesh", out)
        self._transition(state, CognitiveRunStatus.REASONING)
        return out

    def _critic_context(self, state: CognitiveRunState) -> dict[str, Any]:
        evidence_items = 0
        if state.perception:
            evidence_items = len(state.perception.by_type(EpistemicType.EVIDENCE)) + len(
                state.perception.by_type(EpistemicType.KNOWLEDGE_SOURCE)
            )
        coverage = min(1.0, evidence_items / 5.0)
        contradictions = len(state.beliefs.contradiction_pairs) if self.belief_enabled else 0
        density = min(1.0, contradictions / 3.0)
        plan_progress = 0.0
        if state.plan and state.plan.steps:
            done = sum(1 for s in state.plan.steps if s.status in {"DONE", "COMPLETED"})
            plan_progress = done / len(state.plan.steps)
        unresolved = sum(
            1
            for h in state.hypothesis_board.items.values()
            if h.current_status == HypothesisStatus.UNRESOLVED
        )
        fail_obs = sum(1 for o in state.observations if o.success is False)
        risk = getattr(state.task, "risk_class", None)
        risk_s = str(getattr(risk, "value", risk) or "LOW")
        side_effects = list(getattr(state.task, "side_effect_expectations", None) or [])
        return {
            "evidence_coverage": coverage,
            "contradiction_density": density,
            "requires_research": bool(getattr(state.task, "requires_research", False)),
            "requires_current_information": bool(
                getattr(state.task, "requires_current_information", False)
            ),
            "open_hypothesis_count": len(state.hypothesis_board.open_items()),
            "unresolved_hypothesis_count": unresolved,
            "risk_class": risk_s,
            "verification_passed": state.verification_passed,
            "has_side_effects": bool(side_effects)
            or any(
                a.kind
                in {
                    CognitiveActionKind.INVOKE_CAPABILITY,
                    CognitiveActionKind.DELEGATE_AGENT,
                }
                for a in state.actions
            ),
            "success_criteria_count": len(state.task.success_criteria or []),
            "has_response": bool(state.response_text),
            "plan_progress": plan_progress,
            "failure_observation_count": fail_obs,
            "working_memory_saturation": state.working_memory.saturation(),
            "plan_stale": bool(state.plan and state.plan.stale),
            "belief_uncertainty": (
                state.beliefs.uncertainty() if self.belief_enabled else 0.0
            ),
        }

    def _finalize(
        self,
        state: CognitiveRunState,
        *,
        cancelled: bool = False,
        budget_exhausted: bool = False,
        failed_reason: str | None = None,
        timed_out: bool = False,
    ) -> None:
        decision = self.completion_engine.evaluate(
            state.task,
            observations=state.observations,
            verification_passed=state.verification_passed,
            cancelled=cancelled,
            budget_exhausted=budget_exhausted,
            timed_out=timed_out,
            failed_reason=failed_reason,
            response_text=state.response_text,
        )
        state.completion = decision.public_dict()
        # Close public open questions with the public answer preview (not CoT).
        if state.response_text:
            state.reasoning_state.answer_open_questions(state.response_text)
            # Record a single public answer claim when we produced a response.
            if not any(c.source == "model_public_answer" for c in state.reasoning_state.claims):
                state.reasoning_state.add_claim(
                    state.response_text,
                    status="asserted",
                    confidence_band=(
                        "strong" if state.verification_passed is True else "moderate"
                    ),
                    source="model_public_answer",
                )
            if state.verification_passed is False:
                state.reasoning_state.add_unresolved("verification_failed")
                state.reasoning_state.add_critique("verification_engine_rejected_claims")
        # Transition to terminal if possible
        if state.status not in TERMINAL_STATUSES:
            try:
                if validate_transition(state.status, decision.status):
                    self._transition(state, decision.status)
                else:
                    # Force terminal honesty
                    state.status = decision.status
                    self._emit(state, "status_forced_terminal", {"status": decision.status.value})
            except CognitionTransitionInvalid:
                state.status = decision.status

        if self.experience_learning and decision.status in {
            CognitiveRunStatus.COMPLETED_VERIFIED,
            CognitiveRunStatus.COMPLETED_UNVERIFIED,
            CognitiveRunStatus.PARTIAL,
            CognitiveRunStatus.FAILED,
            CognitiveRunStatus.TIMEOUT,
            CognitiveRunStatus.RESOURCE_EXHAUSTED,
        }:
            mode_s = None
            neural_effort = None
            expected_gain = None
            if state.decision is not None:
                mode_s = state.decision.mode.value if state.decision.mode else None
                expected_gain = state.decision.expected_gain
                nb = state.decision.neural_budgets
                if nb is not None and getattr(nb, "native_effort", None) is not None:
                    neural_effort = nb.native_effort.value
            exp = self.experience_store.build_from_run(
                task=state.task,
                status=decision.status,
                strategy=state.decision.strategy if state.decision else "UNKNOWN",
                action_summaries=[a.kind.value for a in state.actions],
                evidence_refs=[ref for o in state.observations for ref in o.evidence_refs],
                verification_status=(
                    "PASSED"
                    if state.verification_passed is True
                    else "FAILED"
                    if state.verification_passed is False
                    else "UNMEASURED"
                ),
                resource_usage=state.usage.public_dict(),
                failures=[o.error for o in state.observations if o.error],
                mode=mode_s,
                neural_effort=neural_effort,
                expected_gain=expected_gain,
            )
            admitted = self.experience_store.admit(exp)
            state.experience = admitted.public_dict()
            self._emit(state, "experience_admitted" if admitted.admitted else "experience_rejected", state.experience)

        # Active-learning candidates from full trigger set — never auto-train.
        if self.experience_learning and hasattr(
            self.experience_store, "capture_active_learning_from_context"
        ):
            al_ctx = self._active_learning_context(
                state,
                decision_status=decision.status,
                budget_exhausted=budget_exhausted,
                timed_out=timed_out,
            )
            captured = self.experience_store.capture_active_learning_from_context(
                al_ctx,
                run_id=state.run_id,
                task_id=state.task.task_id,
                domain=state.task.domain,
                goal=state.task.goal,
            )
            for candidate in captured:
                self._emit(state, "active_learning_candidate", candidate)

        self._persist_update(state, final=True)

    def _active_learning_context(
        self,
        state: CognitiveRunState,
        *,
        decision_status: CognitiveRunStatus,
        budget_exhausted: bool = False,
        timed_out: bool = False,
    ) -> dict[str, Any]:
        """Public run snapshot for active-learning trigger evaluation (no private CoT)."""
        critic_ctx = self._critic_context(state)
        uncertainty = (
            state.beliefs.uncertainty()
            if self.belief_enabled
            else float(getattr(state.task, "initial_uncertainty", 0.5) or 0.5)
        )
        capability_blocks = sum(
            1
            for ev in state.events
            if ev.get("event_type") == "capability_state_blocked"
        )
        if capability_blocks == 0:
            capability_blocks = sum(
                1
                for o in state.observations
                if o.error and str(o.error).startswith("COGNITION_CAPABILITY_")
            )
        user_corrections = sum(
            1
            for c in (state.task.constraints or [])
            if str(c).startswith("correction:")
        )
        if user_corrections == 0:
            user_corrections = sum(
                1
                for crit in state.reasoning_state.critique_notes
                if str(crit).startswith("user_correction:")
            )
        open_unresolved = int(critic_ctx.get("unresolved_hypothesis_count") or 0) + int(
            critic_ctx.get("open_hypothesis_count") or 0
        )
        return {
            "uncertainty": uncertainty,
            "verification_passed": state.verification_passed,
            "status": decision_status.value,
            "contradiction_density": float(critic_ctx.get("contradiction_density") or 0.0),
            "evidence_coverage": float(critic_ctx.get("evidence_coverage") or 0.0),
            "requires_research": bool(critic_ctx.get("requires_research")),
            "budget_exhausted": budget_exhausted
            or decision_status == CognitiveRunStatus.RESOURCE_EXHAUSTED,
            "critic_replan_count": int(state.usage.critic_passes) + int(state.usage.replans),
            "user_correction_count": user_corrections,
            "capability_block_count": capability_blocks,
            "open_unresolved_hypothesis_count": open_unresolved,
            "timed_out": timed_out or decision_status == CognitiveRunStatus.TIMEOUT,
        }

    def _emit(self, state: CognitiveRunState, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "event_id": str(uuid.uuid4()),
            "run_id": state.run_id,
            "event_type": event_type,
            "stage": state.status.value,
            "payload": payload,
            "created_at": time.time(),
        }
        state.events.append(event)
        if self.store is not None:
            try:
                self.store.add_event(state.run_id, event_type, payload, stage=state.status.value)
            except Exception:  # noqa: BLE001
                pass
        if self.observability is not None:
            try:
                self.observability.emit("cognition", event_type, payload=payload, level="info")
            except Exception:  # noqa: BLE001
                pass

    def _persist_create(self, state: CognitiveRunState) -> None:
        if self.store is None:
            return
        try:
            self.store.create_run(
                run_id=state.run_id,
                task_id=state.task.task_id,
                status=state.status,
                conversation_id=(state.task.metadata or {}).get("conversation_id"),
                task_json=state.task.public_dict(),
                shadow=state.shadow,
                trace_id=state.trace_id,
            )
        except Exception:  # noqa: BLE001
            pass

    def _persist_update(self, state: CognitiveRunState, *, final: bool = False) -> None:
        if self.store is None:
            return
        try:
            checkpoint = {
                "observations": [o.public_dict() for o in state.observations],
                "actions": [a.public_dict() for a in state.actions],
                "decision": state.decision.public_dict() if state.decision else None,
                "cancel_requested": state.cancel_requested,
                "cancel_acknowledged": state.cancel_acknowledged,
                "verification_passed": state.verification_passed,
                "steering": list(state.steering),
                "usage": state.usage.public_dict(),
                "cursor_iteration": state.usage.iterations,
                "reasoning_state": state.reasoning_state.public_dict(),
                "hypothesis_board": state.hypothesis_board.public_dict(),
                "critic_report": state.last_critic_report,
                "capability_state": state.capability_state.public_dict(),
                "pending_advance_job_id": state.pending_advance_job_id,
            }
            result_json = {
                "response_text": state.response_text,
                "completion": state.completion,
                "experience": state.experience,
                "context": state.context_public,
                "checkpoint": checkpoint,
                "observations": checkpoint["observations"],
                "actions": checkpoint["actions"],
                "decision": checkpoint["decision"],
                "verification_passed": state.verification_passed,
                "reasoning_state": checkpoint["reasoning_state"],
                "hypothesis_board": checkpoint["hypothesis_board"],
                "critic_report": checkpoint["critic_report"],
                "capability_state": checkpoint["capability_state"],
                "pending_advance_job_id": state.pending_advance_job_id,
            }
            self.store.update_run(
                state.run_id,
                status=state.status,
                plan_json=state.plan.public_dict() if state.plan else None,
                belief_json=state.beliefs.public_dict() if self.belief_enabled else None,
                working_memory_json=state.working_memory.public_dict(),
                budgets_json=state.decision.budgets.public_dict() if state.decision else None,
                usage_json=state.usage.public_dict(),
                result_json=result_json,
                mode=state.decision.mode.value if state.decision else None,
                strategy=state.decision.strategy.value if state.decision else None,
                error=state.error,
            )
            if self.belief_enabled:
                self.store.save_beliefs(state.run_id, state.beliefs)
        except Exception:  # noqa: BLE001
            pass
