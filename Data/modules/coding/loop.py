"""CodingLoop — bounded tool loop with XML capability parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from Data.modules.common.paths import PathEscapeError
from Data.modules.execution.types import CapabilityRequest, CapabilityStatus, SideEffect
from Data.modules.function_runtime.types import SideEffect as FRSideEffect

from .cognition import CodingCognitiveStrategy, CodingPhase, CodingTaskType
from .parser import extract_capabilities, strip_capabilities
from .planner import build_initial_plan
from .prompts import CODING_COGNITIVE_OVERLAY, CODING_SYSTEM_PROMPT
from .store import CodingStore
from .tools import GATED_CAPS, READ_CAPS, enforce_capability, mark_read
from .types import (
    CodingError,
    CodingSession,
    LoopResult,
    Mission,
    SessionStatus,
    StepKind,
    StepStatus,
)
from .workspace import confine, resolve_root


class ChatClient(Protocol):
    """Minimal sync chat interface (real LLM or fake queue)."""

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        model_id: str | None = None,
    ) -> tuple[str, str | None]:
        """Return (assistant_text, model_id)."""
        ...


@dataclass
class FakeLLM:
    """Scriptable queue of assistant strings for unit tests."""

    queue: list[str] = field(default_factory=list)
    temperature_seen: list[float] = field(default_factory=list)
    calls: int = 0

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        model_id: str | None = None,
    ) -> tuple[str, str | None]:
        self.calls += 1
        self.temperature_seen.append(temperature)
        if not self.queue:
            return ("(fake LLM queue empty — stopping)", model_id or "fake")
        return (self.queue.pop(0), model_id or "fake")

    def push(self, *texts: str) -> None:
        self.queue.extend(texts)


class CodingLoop:
    """Synchronous round runner; the worker thread drives multiple rounds."""

    def __init__(
        self,
        store: CodingStore,
        *,
        gateway: Any,
        approvals: Any | None = None,
        llm: ChatClient | None = None,
        context_builder: Any | None = None,
        reasoning: Any | None = None,
        neuro: Any | None = None,
        verification: Any | None = None,
        settings: Any | None = None,
        agents_enabled: bool = False,
        coding_enabled: bool = False,
        brain_access: Any | None = None,
        behavior_store: Any | None = None,
        strategy: CodingCognitiveStrategy | None = None,
    ) -> None:
        self.store = store
        self.gateway = gateway
        self.approvals = approvals
        self.llm = llm
        self.context_builder = context_builder
        self.reasoning = reasoning
        self.neuro = neuro
        self.verification = verification
        self.settings = settings
        self.agents_enabled = agents_enabled
        self.coding_enabled = coding_enabled
        self.brain_access = brain_access
        self.behavior_store = behavior_store
        self.strategy = strategy or CodingCognitiveStrategy()

    @property
    def max_rounds(self) -> int:
        coding = getattr(self.settings, "coding", None) if self.settings else None
        return int(getattr(coding, "max_rounds", 12) or 12)

    @property
    def temperature(self) -> float:
        coding = getattr(self.settings, "coding", None) if self.settings else None
        return float(getattr(coding, "temperature", 0.1) or 0.1)

    def run_round(self, session_id: str, *, approval_ids: list[str] | None = None) -> LoopResult:
        """Execute one model round (or resume a pending approval). Fake-LLM friendly."""
        session = self.store.get_session(session_id)
        if session is None:
            raise CodingError("SESSION_NOT_FOUND", f"Unknown session: {session_id}", http_status=404)

        if not self.agents_enabled or not self.coding_enabled:
            flag = "LEVIATHAN_FEATURE_AGENTS" if not self.agents_enabled else "LEVIATHAN_FEATURE_CODING"
            session = self.store.update_session(
                session_id,
                status=SessionStatus.DISABLED,
                error=f"Coding disabled ({flag}=false)",
            )
            return LoopResult(session=session, status=SessionStatus.DISABLED, error=session.error)

        if session.cancel_requested:
            session = self.store.update_session(session_id, status=SessionStatus.CANCELLED, error="cancelled")
            return LoopResult(session=session, status=SessionStatus.CANCELLED, error="cancelled")

        workspace = Path(session.workspace_root)
        read_paths = set(session.read_paths)

        # Resume pending capability with provided approval.
        if session.status == SessionStatus.WAITING_APPROVAL and session.pending_capability:
            return self._resume_pending(session, approval_ids=approval_ids or [], read_paths=read_paths)

        if session.status not in {SessionStatus.RUNNING, SessionStatus.CREATED}:
            return LoopResult(session=session, status=session.status, rounds=session.round_count)

        session = self._ensure_cognition_state(session)

        if session.round_count >= self.max_rounds:
            return self._finish_verify(session, reason="max_rounds", budget_exhausted=True)

        if self.llm is None:
            session = self.store.update_session(
                session_id,
                status=SessionStatus.FAILED,
                error="LLM client not configured",
            )
            return LoopResult(session=session, status=SessionStatus.FAILED, error=session.error)

        messages = self._build_messages(session)
        try:
            assistant_raw, model_id = self.llm.complete(
                messages,
                temperature=self.temperature,
                model_id=session.model_id,
            )
        except Exception as exc:  # noqa: BLE001
            session = self.store.update_session(
                session_id,
                status=SessionStatus.FAILED,
                error=f"LLMUnavailable: {exc}",
            )
            return LoopResult(session=session, status=SessionStatus.FAILED, error=session.error)

        if model_id:
            self.store.update_session(session_id, model_id=model_id)

        caps = extract_capabilities(assistant_raw)
        visible = strip_capabilities(assistant_raw)
        self.store.add_turn(
            session_id,
            role="assistant",
            content=visible or "(capability call)",
            content_raw=assistant_raw,
            token_estimate=max(1, len(assistant_raw) // 4),
        )

        if not caps:
            session = self.store.update_session(
                session_id,
                round_count=session.round_count + 1,
                status=SessionStatus.RUNNING,
            )
            return self._finish_verify(session, reason="no_tools")

        writes = 0
        for parsed in caps:
            if session.cancel_requested or self.store.get_session(session_id).cancel_requested:  # type: ignore[union-attr]
                session = self.store.update_session(session_id, status=SessionStatus.CANCELLED, error="cancelled")
                return LoopResult(session=session, status=SessionStatus.CANCELLED, error="cancelled")

            try:
                args = enforce_capability(
                    parsed.capability_id,
                    parsed.arguments,
                    workspace_root=workspace,
                    read_paths=read_paths,
                    mission=session.mission,
                    writes_this_round=writes,
                )
            except CodingError as exc:
                step = self.store.add_step(
                    session_id,
                    kind=StepKind.CAPABILITY,
                    status=StepStatus.REJECTED,
                    capability_id=parsed.capability_id,
                    arguments=parsed.arguments,
                    error=f"{exc.code}: {exc.message}",
                    output={"code": exc.code, "details": exc.details},
                )
                self.store.add_turn(
                    session_id,
                    role="user",
                    content=(
                        f"CAPABILITY RESULT id={parsed.capability_id} status=REJECTED "
                        f"step_id={step.step_id}\n{exc.code}: {exc.message}"
                    ),
                )
                if parsed.capability_id in GATED_CAPS:
                    writes += 1
                continue

            rel_path = args.pop("_rel_path", None)
            needs_approval = parsed.capability_id in GATED_CAPS

            if needs_approval:
                approval_id = None
                if approval_ids:
                    approval_id = approval_ids.pop(0)
                if not approval_id and self.approvals is not None:
                    # Create PENDING approval and pause.
                    side_effects = self._side_effects_for(parsed.capability_id)
                    record = self.approvals.request(
                        capability_id=parsed.capability_id,
                        side_effects=side_effects,
                        requested_by="agent:coding",
                        reason=f"coding session {session_id}",
                        run_id=session.run_id,
                        arguments=args,
                        metadata={"session_id": session_id, "rel_path": rel_path},
                    )
                    approval_id = record.approval_id
                    # If not yet APPROVED, pause.
                    if getattr(record, "status", None) and getattr(record.status, "value", "") != "APPROVED":
                        if not self.approvals.is_approved(
                            approval_id,
                            capability_id=parsed.capability_id,
                            side_effects=tuple(
                                FRSideEffect(s) if isinstance(s, str) else s for s in side_effects
                            ),
                        ):
                            pending = {
                                "capability_id": parsed.capability_id,
                                "arguments": args,
                                "approval_id": approval_id,
                                "rel_path": rel_path,
                            }
                            self.store.add_step(
                                session_id,
                                kind=StepKind.WAIT_APPROVAL,
                                status=StepStatus.PENDING,
                                capability_id=parsed.capability_id,
                                arguments=args,
                                approval_id=approval_id,
                            )
                            session = self.store.update_session(
                                session_id,
                                status=SessionStatus.WAITING_APPROVAL,
                                pending_capability=pending,
                                read_paths=sorted(read_paths),
                                round_count=session.round_count + 1,
                            )
                            return LoopResult(
                                session=session,
                                status=SessionStatus.WAITING_APPROVAL,
                                rounds=session.round_count,
                            )

                if not approval_id:
                    # No approvals service — reject gated call honestly.
                    step = self.store.add_step(
                        session_id,
                        kind=StepKind.CAPABILITY,
                        status=StepStatus.REJECTED,
                        capability_id=parsed.capability_id,
                        arguments=args,
                        error="approval_required",
                    )
                    self.store.add_turn(
                        session_id,
                        role="user",
                        content=(
                            f"CAPABILITY RESULT id={parsed.capability_id} status=REJECTED "
                            f"step_id={step.step_id}\napproval_required"
                        ),
                    )
                    writes += 1
                    continue

                result = self._execute(session, parsed.capability_id, args, approval_id=approval_id)
                writes += 1
            else:
                result = self._execute(session, parsed.capability_id, args, approval_id=None)

            # Track reads
            if parsed.capability_id == "file.read" and result.get("status") == CapabilityStatus.COMPLETED.value:
                path_val = rel_path or args.get("path")
                if path_val:
                    mark_read(read_paths, str(path_val))
                    mark_read(read_paths, str(args.get("path") or ""))

            # Persist patches on successful write/patch
            if (
                parsed.capability_id in {"file.patch", "file.write"}
                and result.get("status") == CapabilityStatus.COMPLETED.value
            ):
                output = result.get("output") or {}
                self.store.add_patch(
                    session_id,
                    path=str(rel_path or args.get("path") or ""),
                    diff_unified=str(args.get("unified_diff") or args.get("content") or "")[:50_000],
                    hash_before=output.get("hash_before"),
                    hash_after=output.get("hash_after") or output.get("content_hash"),
                    applied=True,
                    approval_id=result.get("approval_id"),
                )

        session = self.store.update_session(
            session_id,
            status=SessionStatus.RUNNING,
            read_paths=sorted(read_paths),
            round_count=session.round_count + 1,
            pending_capability=None,
        )
        return LoopResult(session=session, status=SessionStatus.RUNNING, rounds=session.round_count)

    def run_until_idle(
        self,
        session_id: str,
        *,
        approval_ids: list[str] | None = None,
        max_rounds: int | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> LoopResult:
        """Drive rounds until terminal / waiting / cancel / max."""
        limit = max_rounds if max_rounds is not None else self.max_rounds
        approvals = list(approval_ids or [])
        last: LoopResult | None = None
        for _ in range(limit + 1):
            if should_stop and should_stop():
                break
            session = self.store.get_session(session_id)
            if session is None:
                break
            if session.status in {
                SessionStatus.COMPLETED,
                SessionStatus.FAILED,
                SessionStatus.UNVERIFIED,
                SessionStatus.PARTIAL,
                SessionStatus.RESOURCE_EXHAUSTED,
                SessionStatus.CANCELLED,
                SessionStatus.DISABLED,
                SessionStatus.WAITING_APPROVAL,
            }:
                # Still allow WAITING_APPROVAL resume when approvals provided.
                if session.status != SessionStatus.WAITING_APPROVAL or not approvals:
                    last = LoopResult(session=session, status=session.status, rounds=session.round_count)
                    break
            last = self.run_round(session_id, approval_ids=approvals)
            approvals = []  # only first round consumes provided approvals
            if last.status in {
                SessionStatus.COMPLETED,
                SessionStatus.FAILED,
                SessionStatus.UNVERIFIED,
                SessionStatus.PARTIAL,
                SessionStatus.RESOURCE_EXHAUSTED,
                SessionStatus.CANCELLED,
                SessionStatus.DISABLED,
                SessionStatus.WAITING_APPROVAL,
            }:
                break
            if last.session.round_count >= limit:
                last = self._finish_verify(last.session, reason="max_rounds", budget_exhausted=True)
                break
        assert last is not None
        return last

    # --- internals ----------------------------------------------------------

    def _resume_pending(
        self,
        session: CodingSession,
        *,
        approval_ids: list[str],
        read_paths: set[str],
    ) -> LoopResult:
        pending = dict(session.pending_capability or {})
        capability_id = str(pending.get("capability_id") or "")
        args = dict(pending.get("arguments") or {})
        approval_id = approval_ids[0] if approval_ids else pending.get("approval_id")
        if not approval_id:
            return LoopResult(session=session, status=SessionStatus.WAITING_APPROVAL, rounds=session.round_count)

        # If denied / not approved → reject step, clear pending, stay recoverable.
        if self.approvals is not None:
            side_effects = self._side_effects_for(capability_id)
            if not self.approvals.is_approved(
                str(approval_id),
                capability_id=capability_id,
                side_effects=tuple(FRSideEffect(s) if isinstance(s, str) else s for s in side_effects),
            ):
                self.store.add_step(
                    session.session_id,
                    kind=StepKind.CAPABILITY,
                    status=StepStatus.REJECTED,
                    capability_id=capability_id,
                    arguments=args,
                    approval_id=str(approval_id),
                    error="approval_denied",
                )
                session = self.store.update_session(
                    session.session_id,
                    status=SessionStatus.RUNNING,
                    pending_capability=None,
                    error="approval denied — not written",
                )
                return LoopResult(session=session, status=SessionStatus.RUNNING, rounds=session.round_count)

        result = self._execute(session, capability_id, args, approval_id=str(approval_id))
        if capability_id == "file.read" and result.get("status") == CapabilityStatus.COMPLETED.value:
            path_val = pending.get("rel_path") or args.get("path")
            if path_val:
                mark_read(read_paths, str(path_val))
        if (
            capability_id in {"file.patch", "file.write"}
            and result.get("status") == CapabilityStatus.COMPLETED.value
        ):
            output = result.get("output") or {}
            self.store.add_patch(
                session.session_id,
                path=str(pending.get("rel_path") or args.get("path") or ""),
                diff_unified=str(args.get("unified_diff") or args.get("content") or "")[:50_000],
                hash_before=output.get("hash_before"),
                hash_after=output.get("hash_after") or output.get("content_hash"),
                applied=True,
                approval_id=str(approval_id),
            )
        session = self.store.update_session(
            session.session_id,
            status=SessionStatus.RUNNING,
            pending_capability=None,
            read_paths=sorted(read_paths),
            error=None,
        )
        return LoopResult(session=session, status=SessionStatus.RUNNING, rounds=session.round_count)

    def _execute(
        self,
        session: CodingSession,
        capability_id: str,
        arguments: dict[str, Any],
        *,
        approval_id: str | None,
    ) -> dict[str, Any]:
        step = self.store.add_step(
            session.session_id,
            kind=StepKind.CAPABILITY,
            status=StepStatus.RUNNING,
            capability_id=capability_id,
            arguments=arguments,
            approval_id=approval_id,
        )
        try:
            result = self.gateway.execute(
                CapabilityRequest(
                    capability_id=capability_id,
                    arguments={k: v for k, v in arguments.items() if not str(k).startswith("_")},
                    approval_id=approval_id,
                    run_id=session.run_id,
                    requested_by="agent:coding",
                )
            )
        except Exception as exc:  # noqa: BLE001
            self.store.update_step(step.step_id, status=StepStatus.FAILED, error=str(exc))
            self.store.add_turn(
                session.session_id,
                role="user",
                content=f"CAPABILITY RESULT id={capability_id} status=FAILED step_id={step.step_id}\n{exc}",
            )
            return {"status": CapabilityStatus.FAILED.value, "error": str(exc)}

        status = result.status
        step_status = {
            CapabilityStatus.COMPLETED: StepStatus.COMPLETED,
            CapabilityStatus.FAILED: StepStatus.FAILED,
            CapabilityStatus.REJECTED: StepStatus.REJECTED,
            CapabilityStatus.TIMEOUT: StepStatus.TIMEOUT,
            CapabilityStatus.CANCELLED: StepStatus.FAILED,
        }.get(status, StepStatus.FAILED)

        observation_id = None
        if getattr(result, "telemetry", None):
            observation_id = result.telemetry.get("observation_id")
        # Effect ledger may attach observation via gateway side channel
        effect_id = None
        if self.gateway.effect_ledger:
            last = self.gateway.effect_ledger[-1]
            if last.request_id == result.request_id:
                effect_id = last.effect_id
                observation_id = observation_id or last.observation_id

        output = result.output if isinstance(result.output, dict) else {"value": result.output}
        self.store.update_step(
            step.step_id,
            status=step_status,
            output=output or {},
            error=result.error,
            observation_id=observation_id,
            effect_id=effect_id,
            approval_id=approval_id,
        )
        body = json.dumps(output or {}, ensure_ascii=False)[:4000]
        self.store.add_turn(
            session.session_id,
            role="user",
            content=(
                f"CAPABILITY RESULT id={capability_id} status={status.value} "
                f"observation_id={observation_id or '-'} step_id={step.step_id}\n{body}"
            ),
        )
        return {
            "status": status.value,
            "output": output,
            "error": result.error,
            "approval_id": approval_id,
            "observation_id": observation_id,
            "step_id": step.step_id,
        }

    def _ensure_cognition_state(self, session: CodingSession) -> CodingSession:
        meta = dict(session.metadata or {})
        cognition = dict(meta.get("cognition") or {})
        if cognition.get("task_type") and cognition.get("plan"):
            return session
        understand = self.strategy.understand(None, text=session.user_goal)
        plan = self.strategy.plan(None, understand)
        phase = self.strategy.initial_phase(understand)
        cognition.update(
            {
                "task_type": understand.task_type,
                "phase": phase.value,
                "role": "implementer",
                "acceptance": list(understand.acceptance_criteria),
                "constraints": list(understand.constraints),
                "risk": understand.risk,
                "plan": plan.public_dict(),
                "hypotheses": [h.public_dict() for h in plan.hypotheses],
                "strategy": self.strategy.preferred_strategy(understand).value
                if hasattr(self.strategy.preferred_strategy(understand), "value")
                else str(self.strategy.preferred_strategy(understand)),
            }
        )
        meta["cognition"] = cognition
        return self.store.update_session(session.session_id, metadata=meta)

    def _behavior_prompt(self) -> str:
        if self.behavior_store is not None:
            try:
                return self.behavior_store.get_effective().composed_system_prompt()
            except Exception:  # noqa: BLE001
                pass
        try:
            from Data.modules.settings.seed import SEED_SYSTEM_PROMPT

            return SEED_SYSTEM_PROMPT
        except Exception:  # noqa: BLE001
            from Data.modules.settings.seed import SEED_ASSISTANT_DISPLAY_NAME

            return f"You are {SEED_ASSISTANT_DISPLAY_NAME}."

    def _gather_brain_context(self, session: CodingSession) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        meta = dict(session.metadata or {})
        cognition = dict(meta.get("cognition") or {})
        if self.brain_access is None:
            return [], [], [], {"status": "unavailable", "dropped": ["brain_access_unwired"]}
        understand = self.strategy.understand(None, text=session.user_goal)
        overrides = self.strategy.enrich_context_request(None, understand)
        try:
            from Data.modules.brain.contracts import BrainContextRequest

            request = BrainContextRequest(
                goal=session.user_goal,
                domain="coding",
                role=str(cognition.get("role") or "implementer"),
                run_id=session.run_id,
                conversation_id=session.conversation_id,
                workspace_root=session.workspace_root,
                queries=list(overrides.get("queries") or [session.user_goal]),
                symbols=list(overrides.get("symbols") or []),
                files=list(overrides.get("files") or []),
                entities=list(overrides.get("entities") or []),
                include_evidence=bool(overrides.get("include_evidence", True)),
                include_experience=bool(overrides.get("include_experience", True)),
                include_capabilities=False,
                token_budget=int(overrides.get("token_budget") or 1200),
                result_limits=dict(overrides.get("result_limits") or {}),
                task_semantics=dict(overrides.get("task_semantics") or {}),
            )
            brain_ctx = self.brain_access.gather(request)
            summary = {
                "status": "ok",
                "knowledgeHits": len(brain_ctx.knowledge),
                "memoryHits": len(brain_ctx.memory),
                "evidenceHits": len(brain_ctx.evidence),
                "experienceHits": len(brain_ctx.experience),
                "tokenEstimate": brain_ctx.token_estimate,
                "dropped": list(brain_ctx.dropped),
                "selectionTrace": dict(brain_ctx.selection_trace),
                "provenance": [p.public_dict() for p in brain_ctx.provenance[:20]],
            }
            cognition["brain_context"] = summary
            cognition["phase"] = CodingPhase.RETRIEVING_CONTEXT.value
            meta["cognition"] = cognition
            self.store.update_session(session.session_id, metadata=meta)
            return (
                brain_ctx.knowledge_dicts(),
                brain_ctx.memory_dicts(),
                brain_ctx.evidence_dicts(),
                summary,
            )
        except Exception as exc:  # noqa: BLE001
            summary = {"status": "error", "error": str(exc)}
            cognition["brain_context"] = summary
            meta["cognition"] = cognition
            self.store.update_session(session.session_id, metadata=meta)
            return [], [], [], summary

    def _finish_verify(
        self,
        session: CodingSession,
        *,
        reason: str,
        budget_exhausted: bool = False,
    ) -> LoopResult:
        steps = self.store.list_steps(session.session_id)
        completed_writes = [
            s
            for s in steps
            if s.capability_id in {"file.write", "file.patch", "file.delete"}
            and s.status == StepStatus.COMPLETED
        ]
        test_steps = [
            s
            for s in steps
            if s.capability_id == "coding.run_tests" and s.status == StepStatus.COMPLETED
        ]
        read_steps = [
            s
            for s in steps
            if s.capability_id in {"file.read", "workspace.search", "workspace.list"}
            and s.status == StepStatus.COMPLETED
        ]
        search_hits = any(
            s.capability_id == "workspace.search" and s.status == StepStatus.COMPLETED for s in steps
        )

        # ENFORCE-5: FIX/TEST need a successful coding.run_tests observation.
        if session.mission in {Mission.FIX, Mission.TEST} and not test_steps:
            status = (
                SessionStatus.RESOURCE_EXHAUSTED
                if budget_exhausted
                else SessionStatus.UNVERIFIED
            )
            session = self.store.update_session(
                session.session_id,
                status=status,
                error="FIX/TEST requires coding.run_tests observation before COMPLETED",
                metadata=self._cognition_meta(
                    session,
                    phase=CodingPhase.PARTIAL.value if not budget_exhausted else CodingPhase.RESOURCE_EXHAUSTED.value,
                    acceptance={"status": status.value, "reason": reason, "unmet": ["coding.run_tests"]},
                ),
            )
            self.store.add_step(
                session.session_id,
                kind=StepKind.VERIFY,
                status=StepStatus.FAILED,
                error="missing coding.run_tests",
                output={"reason": reason, "budget_exhausted": budget_exhausted},
            )
            return LoopResult(
                session=session,
                status=status,
                rounds=session.round_count,
                error=session.error,
            )

        verification_payload: dict[str, Any] | None = None
        verification_passed = False
        verification_unavailable = self.verification is None and bool(completed_writes)

        if self.verification is not None and completed_writes:
            from Data.modules.verification import VerificationEngine
            from Data.modules.verification.types import VerificationRequirement
            import uuid as _uuid

            reqs = []
            for step in completed_writes:
                path = (step.arguments or {}).get("path")
                if path:
                    reqs.append(VerificationEngine.require_file(str(path)))
            for step in test_steps:
                if step.observation_id:
                    reqs.append(
                        VerificationRequirement(
                            requirement_id=str(_uuid.uuid4()),
                            description="coding.run_tests observation",
                            evidence_kind="OBSERVATION_REF",
                            observation_id=step.observation_id,
                        )
                    )
            if reqs:
                report = self.verification.verify(reqs, run_id=session.run_id)
                verification_payload = report.public_dict()
                outcome = getattr(report.outcome, "value", str(report.outcome))
                if outcome != "PASSED":
                    status = (
                        SessionStatus.RESOURCE_EXHAUSTED
                        if budget_exhausted
                        else SessionStatus.UNVERIFIED
                    )
                    session = self.store.update_session(
                        session.session_id,
                        status=status,
                        verification_id=getattr(report, "report_id", None),
                        error=f"Verification {outcome}",
                        metadata=self._cognition_meta(
                            session,
                            phase=CodingPhase.REPAIRING.value,
                            acceptance={"status": status.value, "verification": outcome, "reason": reason},
                        ),
                    )
                    self.store.add_step(
                        session.session_id,
                        kind=StepKind.VERIFY,
                        status=StepStatus.FAILED,
                        output=verification_payload,
                        error=f"Verification {outcome}",
                    )
                    return LoopResult(
                        session=session,
                        status=status,
                        rounds=session.round_count,
                        verification=verification_payload,
                        error=session.error,
                    )
                verification_passed = True

        if completed_writes and self.verification is None:
            status = (
                SessionStatus.RESOURCE_EXHAUSTED
                if budget_exhausted
                else SessionStatus.UNVERIFIED
            )
            session = self.store.update_session(
                session.session_id,
                status=status,
                error="Writes occurred but VerificationEngine unavailable (UNMEASURED)",
                metadata=self._cognition_meta(
                    session,
                    phase=CodingPhase.PARTIAL.value,
                    acceptance={"status": status.value, "reason": reason},
                ),
            )
            return LoopResult(
                session=session,
                status=status,
                rounds=session.round_count,
                error=session.error,
            )

        # Acceptance-criteria evaluation via CodingCognitiveStrategy.
        understand = self.strategy.understand(None, text=session.user_goal)
        eval_state = {
            "completed_writes": len(completed_writes),
            "completed_tests": len(test_steps),
            "reads": len(read_steps) + len(session.read_paths),
            "search_hits": search_hits,
            "cancelled": False,
            "budget_exhausted": budget_exhausted,
            "verification_passed": verification_passed,
            "verification_unavailable": verification_unavailable,
            "goal_addressed": bool(self.store.list_turns(session.session_id)),
        }
        decision = self.strategy.verify(state=eval_state, understand=understand)
        status_name = str(decision.get("status") or "PARTIAL")
        # Max rounds must never invent COMPLETED when criteria unmet.
        if budget_exhausted and status_name == "COMPLETED" and decision.get("unmet"):
            status_name = "RESOURCE_EXHAUSTED"
        if budget_exhausted and status_name == "PARTIAL":
            status_name = "RESOURCE_EXHAUSTED"
        try:
            final_status = SessionStatus(status_name)
        except ValueError:
            final_status = SessionStatus.PARTIAL if decision.get("unmet") else SessionStatus.COMPLETED

        if final_status == SessionStatus.COMPLETED and verification_passed and completed_writes:
            session = self.store.update_session(
                session.session_id,
                status=SessionStatus.COMPLETED,
                verification_id=(verification_payload or {}).get("report_id")
                if isinstance(verification_payload, dict)
                else session.verification_id,
                error=None,
                metadata=self._cognition_meta(
                    session,
                    phase=CodingPhase.COMPLETED.value,
                    acceptance=decision,
                ),
            )
            self.store.add_step(
                session.session_id,
                kind=StepKind.VERIFY,
                status=StepStatus.COMPLETED,
                output={"reason": reason, "acceptance": decision, "verification": verification_payload},
            )
            return LoopResult(
                session=session,
                status=SessionStatus.COMPLETED,
                rounds=session.round_count,
                verification=verification_payload,
            )

        if final_status == SessionStatus.COMPLETED and not completed_writes:
            session = self.store.update_session(
                session.session_id,
                status=SessionStatus.COMPLETED,
                error=None,
                metadata=self._cognition_meta(
                    session,
                    phase=CodingPhase.COMPLETED.value,
                    acceptance=decision,
                ),
            )
            self.store.add_step(
                session.session_id,
                kind=StepKind.RESPOND,
                status=StepStatus.COMPLETED,
                output={"reason": reason, "acceptance": decision},
            )
            return LoopResult(session=session, status=SessionStatus.COMPLETED, rounds=session.round_count)

        # Honest non-success terminals.
        phase_map = {
            SessionStatus.RESOURCE_EXHAUSTED: CodingPhase.RESOURCE_EXHAUSTED.value,
            SessionStatus.PARTIAL: CodingPhase.PARTIAL.value,
            SessionStatus.UNVERIFIED: CodingPhase.VERIFYING.value,
            SessionStatus.FAILED: CodingPhase.FAILED.value,
        }
        error = None
        if final_status == SessionStatus.RESOURCE_EXHAUSTED:
            error = f"Resource exhausted before acceptance criteria met ({reason})"
        elif final_status == SessionStatus.PARTIAL:
            error = f"Partial completion: unmet={decision.get('unmet')}"
        elif final_status == SessionStatus.UNVERIFIED:
            error = f"Unverified: unmet={decision.get('unmet')}"
        session = self.store.update_session(
            session.session_id,
            status=final_status,
            error=error,
            metadata=self._cognition_meta(
                session,
                phase=phase_map.get(final_status, CodingPhase.PARTIAL.value),
                acceptance=decision,
            ),
        )
        self.store.add_step(
            session.session_id,
            kind=StepKind.VERIFY,
            status=StepStatus.FAILED if final_status != SessionStatus.COMPLETED else StepStatus.COMPLETED,
            output={"reason": reason, "acceptance": decision, "budget_exhausted": budget_exhausted},
            error=error,
        )
        return LoopResult(
            session=session,
            status=final_status,
            rounds=session.round_count,
            verification=verification_payload,
            error=error,
        )

    def _cognition_meta(
        self,
        session: CodingSession,
        *,
        phase: str | None = None,
        acceptance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = dict(session.metadata or {})
        cognition = dict(meta.get("cognition") or {})
        if phase:
            cognition["phase"] = phase
        if acceptance is not None:
            cognition["acceptance"] = acceptance
        meta["cognition"] = cognition
        return meta

    def _build_messages(self, session: CodingSession) -> list[dict[str, str]]:
        history = self.store.list_turns(session.session_id)
        cognition = dict((session.metadata or {}).get("cognition") or {})
        plan_dict = cognition.get("plan") if isinstance(cognition.get("plan"), dict) else {}
        plan_bullets = list(plan_dict.get("publicBullets") or []) or build_initial_plan(
            session.user_goal, session.mission
        )
        knowledge, memory, evidence, brain_summary = self._gather_brain_context(session)
        behavior_prompt = self._behavior_prompt()

        if self.context_builder is not None:
            try:
                from Data.modules.reasoning import ReasoningPlan

                plan = ReasoningPlan(
                    intent="coding",
                    complexity="medium",
                    use_knowledge=True,
                    steps=tuple(plan_bullets),
                )
            except Exception:  # noqa: BLE001
                plan = None
            if plan is not None:
                pack = self.context_builder.build(
                    history=[
                        {
                            "role": t.role if t.role in {"user", "assistant"} else "user",
                            "content": t.content,
                        }
                        for t in history
                    ],
                    knowledge=knowledge,
                    memory=memory,
                    evidence=evidence,
                    plan=plan,
                    mode="coding",
                    constraints=CODING_COGNITIVE_OVERLAY,
                    behavior_profile_prompt=behavior_prompt,
                    token_budget=getattr(getattr(self.settings, "coding", None), "token_budget", None),
                )
                # Annotate system content with plan/task type for the model (bounded).
                messages = list(pack.messages)
                if messages and messages[0].get("role") == "system":
                    extra = (
                        f"\n\nCoding task_type={cognition.get('task_type') or session.mission.value}\n"
                        f"Phase={cognition.get('phase') or 'INVESTIGATING'}\n"
                        f"BrainContext={brain_summary.get('status')} "
                        f"knowledge={brain_summary.get('knowledgeHits', 0)} "
                        f"memory={brain_summary.get('memoryHits', 0)}\n"
                        f"Public plan:\n- " + "\n- ".join(plan_bullets)
                    )
                    messages[0] = {
                        "role": "system",
                        "content": str(messages[0].get("content") or "") + extra,
                    }
                return messages

        # Fallback path still includes shared BehaviorProfile identity + coding overlay.
        system = f"{behavior_prompt}\n\n## Coding Cognitive Overlay\n{CODING_COGNITIVE_OVERLAY}"
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Mission={session.mission.value}\n"
                    f"TaskType={cognition.get('task_type') or session.mission.value}\n"
                    f"Goal={session.user_goal}\n"
                    f"Plan:\n- " + "\n- ".join(plan_bullets)
                ),
            },
        ]
        if knowledge:
            blob = "\n".join(
                f"- {item.get('title') or item.get('id')}: {(item.get('content') or item.get('text') or '')[:400]}"
                for item in knowledge[:4]
            )
            messages.append({"role": "user", "content": f"Brain knowledge:\n{blob}"})
        for turn in history:
            role = turn.role if turn.role in {"user", "assistant"} else "user"
            messages.append({"role": role, "content": turn.content_raw or turn.content})
        return messages

    def _side_effects_for(self, capability_id: str) -> tuple[str, ...]:
        definition = self.gateway.get_capability(capability_id) if self.gateway else None
        if definition is None:
            if capability_id == "file.delete":
                return (FRSideEffect.DELETE.value, FRSideEffect.DESTRUCTIVE.value)
            if capability_id == "coding.run_tests":
                return (FRSideEffect.EXECUTE.value,)
            return (FRSideEffect.WRITE.value,)
        return tuple(e.value for e in definition.side_effects)
