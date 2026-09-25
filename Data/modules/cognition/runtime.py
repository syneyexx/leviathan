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
from .completion import CompletionEngine
from .context_v3 import ContextBuilderV3
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
from .loop_detection import LoopDetector
from .meta_controller import MetaController, MetaDecision
from .perception import PerceptionService, PerceptionSnapshot
from .planner import CognitivePlanner
from .steering import SteerKind, classify_steer
from .store import CognitionStore
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

    def public_status(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task.task_id,
            "status": self.status.value,
            "stage": self.status.value,
            "mode": self.decision.mode.value if self.decision else None,
            "strategy": self.decision.strategy.value if self.decision else None,
            "goal": self.task.goal,
            "domain": self.task.domain,
            "uncertainty": self.beliefs.uncertainty(),
            "belief_counts": self.beliefs.counts(),
            "working_memory_count": len(self.working_memory.items),
            "working_memory_saturation": self.working_memory.saturation(),
            "budgets": self.decision.budgets.public_dict() if self.decision else None,
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
        execution_gateway: Any | None = None,
        observability: Any | None = None,
        resource_pressure_fn: Callable[[], float] | None = None,
        behavior_resolver: Any | None = None,
    ) -> None:
        self.enabled = enabled
        self.shadow_default = shadow
        self.iterative = iterative
        self.belief_enabled = belief_enabled
        self.neuro_enabled = neuro_enabled
        self.adaptive_depth = adaptive_depth
        self.delegation_enabled = delegation_enabled
        self.experience_learning = experience_learning

        self.task_builder = task_builder or TaskModelBuilder()
        self.perception = perception or PerceptionService(neuro_advisor=neuro_advisor)
        if meta is not None:
            self.meta = meta
            if policy is not None and hasattr(self.meta, "set_policy"):
                self.meta.set_policy(policy)
        elif policy is not None:
            self.meta = MetaController(policy=policy)
        else:
            self.meta = MetaController()
        self.planner = planner or CognitivePlanner()
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
        self.execution_gateway = execution_gateway
        self.observability = observability
        self.resource_pressure_fn = resource_pressure_fn or (lambda: 0.0)
        # Canonical BehaviorSettingsResolver — resolve current persisted profile
        # at each new submit/operation. Do not cache identity on the runtime.
        self.behavior_resolver = behavior_resolver

        self._runs: dict[str, CognitiveRunState] = {}
        self._loops: dict[str, LoopDetector] = {}

    def _apply_current_behavior_snapshot(
        self,
        meta_payload: dict[str, Any],
        *,
        message: str,
        history: list[dict[str, str]] | None,
    ) -> None:
        """Resolve current persisted BehaviorProfile into task metadata.

        Conversation objects must never own reusable behavioral authority.
        Rules:
        - If the caller already supplied ``behavior_system_prompt`` for this
          operation (e.g. Chat resolved once for the turn), keep it so the
          whole turn shares one immutable snapshot.
        - If missing, resolve the current persisted profile now (direct
          cognition API / workers / incomplete callers).
        - ``behavior_operation_pin`` keeps a long-running job's starting snapshot.
        """
        if meta_payload.get("behavior_operation_pin"):
            return
        if str(meta_payload.get("behavior_system_prompt") or "").strip():
            # Provenance fill-only when caller already pinned this turn's prompt.
            if not meta_payload.get("behavior_profile_hash") and meta_payload.get("behavior_hash"):
                meta_payload["behavior_profile_hash"] = meta_payload.get("behavior_hash")
            return
        if self.behavior_resolver is None:
            return
        recent_user = [
            str(m.get("content") or "")
            for m in (history or [])
            if m.get("role") == "user" and m.get("content")
        ]
        try:
            snap = self.behavior_resolver.resolve(
                latest_user_message=message,
                recent_user_messages=recent_user[:-1] if recent_user else [],
            )
        except Exception:  # noqa: BLE001 — never fail cognition on behavior resolve
            return
        meta_payload["behavior_system_prompt"] = snap.system_prompt
        meta_payload["behavior_hash"] = snap.settings_hash
        meta_payload["behavior_profile_id"] = snap.profile.id
        meta_payload["behavior_profile_version"] = snap.version
        meta_payload["behavior_profile_hash"] = snap.settings_hash
        if not meta_payload.get("response_language"):
            meta_payload["response_language"] = snap.language.response_language
            meta_payload["language_source"] = snap.language.source

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
    ) -> dict[str, Any]:
        if not self.enabled:
            raise CognitionFeatureDisabled("LEVIATHAN_FEATURE_COGNITION is disabled")
        use_shadow = self.shadow_default if shadow is None else shadow
        meta_payload = dict(metadata or {})
        if user_requested_depth:
            meta_payload["user_requested_depth"] = str(user_requested_depth)
        # Fresh BehaviorSnapshot per independent cognition operation.
        # Long-running jobs may set behavior_operation_pin=True to keep a
        # caller-supplied snapshot for the duration of one logical execution.
        self._apply_current_behavior_snapshot(
            meta_payload,
            message=message,
            history=history,
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
        self._runs[run_id] = state
        self._loops[run_id] = LoopDetector()
        self._persist_create(state)
        self._emit(state, "task_created", {"task": task.public_dict()})
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
            self._emit(state, "plan_created", state.plan.public_dict())

            if not self.iterative or decision.mode == ReasoningMode.FAST:
                return self._fast_path(state, history=history)

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
        state = self._require(run_id)
        text = (instruction or "").strip()
        if not text:
            return state.public_status()
        classified = classify_steer(text)
        state.steering.append(text)
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
        elif classified.kind == SteerKind.NEW_CONSTRAINT:
            state.task.constraints.append(text)
            state.working_memory.upsert("constraint", text, priority=0.95, verified=True)
        elif classified.kind == SteerKind.CORRECTION:
            state.task.constraints.append(f"correction:{text}")
            state.working_memory.upsert("constraint", f"correction:{text}", priority=0.9)
        else:
            state.task.constraints.append(f"steer:{text}")
            state.working_memory.upsert("constraint", text, priority=0.88)
        if state.plan is not None and classified.kind != SteerKind.STATUS_REQUEST:
            self.planner.mark_stale(state.plan, reason=f"user_steer:{classified.kind.value}:{text[:80]}")
        self._emit(state, "user_steering", classified.public_dict())
        state.observations.append(
            CognitiveObservation(
                kind=CognitiveObservationKind.USER_STEERING,
                observation_id=str(uuid.uuid4()),
                summary=text,
                source_type=EpistemicType.USER_STATEMENT,
                success=True,
                payload=classified.public_dict(),
            )
        )
        return {
            **state.public_status(),
            "steering_classification": classified.public_dict(),
        }

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
        if state.status == CognitiveRunStatus.WAITING_APPROVAL:
            self._transition(state, CognitiveRunStatus.REASONING)
        elif state.status == CognitiveRunStatus.BLOCKED:
            # Reopen blocked as replanning only when explicitly resumed.
            state.status = CognitiveRunStatus.REPLANNING
        self._emit(state, "resumed", {"from": state.status.value, "hydrated": True})
        return self.run(run_id, history=history)

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
            "truth": {
                "cognition_does_not_bypass_gateway": True,
                "neuro_is_advisory": True,
                "hydrate_reconstructs_live_state": True,
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

    def _fast_path(self, state: CognitiveRunState, *, history: list[dict[str, str]] | None) -> dict[str, Any]:
        ctx = self.context_builder.build(
            task=state.task,
            working_memory=state.working_memory,
            beliefs=state.beliefs if self.belief_enabled else None,
            perception=state.perception,
            plan=state.plan,
            history=history,
            token_budget=state.decision.budgets.max_context_tokens if state.decision else None,
        )
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

    def _iterative_loop(self, state: CognitiveRunState, *, history: list[dict[str, str]] | None) -> dict[str, Any]:
        detector = self._loops[state.run_id]
        while True:
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
            action = self.actions.select(
                task=state.task,
                decision=state.decision,  # type: ignore[arg-type]
                plan=state.plan,
                beliefs=state.beliefs,
                working_memory=state.working_memory,
                observations=state.observations,
                budgets_remaining=remaining,
                cancel_requested=state.cancel_requested,
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
                    payload={
                        "action_id": action.action_id,
                        "capability_id": capability_id,
                        "result": result_dict,
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
            ctx = self.context_builder.build(
                task=state.task,
                working_memory=state.working_memory,
                beliefs=state.beliefs if self.belief_enabled else None,
                perception=state.perception,
                plan=state.plan,
                capability_shortlist=shortlist,
                history=history,
                token_budget=state.decision.budgets.max_context_tokens if state.decision else None,
            )
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
        try:
            result = self.model_caller(
                system_prompt=system_prompt,
                messages=messages,
                role=role,
                run_id=state.run_id,
                trace_id=state.trace_id,
                max_tokens=max_tokens,
            )
            usage: dict[str, Any] = {}
            usage_source = "unavailable"
            if isinstance(result, tuple):
                text = result[0]
            elif isinstance(result, dict):
                text = result.get("text") or result.get("content")
                usage = result.get("usage") or {}
                usage_source = str(result.get("usage_source") or "unavailable")
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

    def _verify(self, state: CognitiveRunState) -> bool:
        if self.verification_engine is None:
            # Without VerificationEngine, never claim verified.
            return False
        try:
            from Data.modules.verification import VerificationRequirement

            evidence_ids = [
                ref
                for o in state.observations
                for ref in o.evidence_refs
            ]
            requirements: list[Any] = []
            for req_kind in state.task.required_evidence:
                kind = str(req_kind).strip()
                if not kind:
                    continue
                requirements.append(
                    VerificationRequirement(
                        requirement_id=f"required:{kind}",
                        description=f"Required evidence: {kind}",
                        evidence_kind=kind if kind.isupper() or "_" in kind else None,
                        min_verified=1,
                    )
                )
            # Observation-linked evidence refs become OBSERVATION_REF requirements.
            for ref in evidence_ids:
                if ref.startswith("obs:") or ref.startswith("observation:"):
                    requirements.append(
                        VerificationRequirement(
                            requirement_id=f"obs:{ref}",
                            description=f"Observation evidence {ref}",
                            evidence_kind="OBSERVATION_REF",
                            observation_id=ref.split(":", 1)[-1],
                            min_verified=1,
                        )
                    )
                elif ref.startswith("artifact:") or ref.startswith("art:"):
                    requirements.append(
                        VerificationRequirement(
                            requirement_id=f"art:{ref}",
                            description=f"Artifact evidence {ref}",
                            evidence_kind="ARTIFACT_HASH",
                            artifact_id=ref.split(":", 1)[-1],
                            min_verified=1,
                        )
                    )
            if not requirements:
                # No typed requirements → cannot claim PASSED.
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
        recommend = "continue"
        reason = "ok"
        # Repeated failures
        fail_obs = [o for o in state.observations if o.success is False]
        if len(fail_obs) >= 2:
            recommend = "replan"
            reason = "repeated failures"
        elif state.plan and state.plan.stale:
            recommend = "replan"
            reason = "stale plan"
        elif self.belief_enabled and state.beliefs.uncertainty() > 0.75:
            recommend = "retrieve"
            reason = "high uncertainty"
        elif state.working_memory.saturation() > 0.9:
            recommend = "compact"
            reason = "working memory saturated"
        out = {"recommend": recommend, "reason": reason}
        self._transition(state, CognitiveRunStatus.REASONING)
        return out

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
        }:
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
            )
            admitted = self.experience_store.admit(exp)
            state.experience = admitted.public_dict()
            self._emit(state, "experience_admitted" if admitted.admitted else "experience_rejected", state.experience)

        # Active-learning candidates on high uncertainty or verification failure — never auto-train.
        uncertainty = (
            state.beliefs.uncertainty()
            if self.belief_enabled
            else float(getattr(state.task, "initial_uncertainty", 0.5) or 0.5)
        )
        verification_failed = state.verification_passed is False
        high_uncertainty = uncertainty >= 0.75
        if verification_failed or high_uncertainty or decision.status == CognitiveRunStatus.FAILED:
            reason = (
                "verification_failed"
                if verification_failed
                else "run_failed"
                if decision.status == CognitiveRunStatus.FAILED
                else "high_uncertainty"
            )
            candidate = {
                "run_id": state.run_id,
                "task_id": state.task.task_id,
                "domain": state.task.domain,
                "goal": state.task.goal[:300],
                "status": decision.status.value,
                "uncertainty": uncertainty,
                "verification_status": (
                    "FAILED"
                    if verification_failed
                    else "PASSED"
                    if state.verification_passed is True
                    else "UNMEASURED"
                ),
                "reason": reason,
                "kind": "failure" if verification_failed or decision.status == CognitiveRunStatus.FAILED else "uncertainty",
                "auto_promote_forbidden": True,
                "requires_human_or_policy_approval": True,
            }
            if hasattr(self.experience_store, "record_active_learning_candidate"):
                candidate = self.experience_store.record_active_learning_candidate(candidate)
            self._emit(state, "active_learning_candidate", candidate)

        self._persist_update(state, final=True)

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
