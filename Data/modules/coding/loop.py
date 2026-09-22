"""CodingLoop — bounded tool loop with XML capability parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from Data.modules.common.paths import PathEscapeError
from Data.modules.execution.types import CapabilityRequest, CapabilityStatus, SideEffect
from Data.modules.function_runtime.types import SideEffect as FRSideEffect

from .parser import extract_capabilities, strip_capabilities
from .planner import build_initial_plan
from .prompts import CODING_SYSTEM_PROMPT
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

        if session.round_count >= self.max_rounds:
            return self._finish_verify(session, reason="max_rounds")

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
                SessionStatus.CANCELLED,
                SessionStatus.DISABLED,
                SessionStatus.WAITING_APPROVAL,
            }:
                break
            if last.session.round_count >= limit:
                last = self._finish_verify(last.session, reason="max_rounds")
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

    def _finish_verify(self, session: CodingSession, *, reason: str) -> LoopResult:
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

        # ENFORCE-5: FIX/TEST need a successful coding.run_tests observation.
        if session.mission in {Mission.FIX, Mission.TEST} and not test_steps:
            session = self.store.update_session(
                session.session_id,
                status=SessionStatus.UNVERIFIED,
                error="FIX/TEST requires coding.run_tests observation before COMPLETED",
            )
            self.store.add_step(
                session.session_id,
                kind=StepKind.VERIFY,
                status=StepStatus.FAILED,
                error="missing coding.run_tests",
                output={"reason": reason},
            )
            return LoopResult(
                session=session,
                status=SessionStatus.UNVERIFIED,
                rounds=session.round_count,
                error=session.error,
            )

        verification_payload: dict[str, Any] | None = None
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
                    session = self.store.update_session(
                        session.session_id,
                        status=SessionStatus.UNVERIFIED,
                        verification_id=getattr(report, "report_id", None),
                        error=f"Verification {outcome}",
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
                        status=SessionStatus.UNVERIFIED,
                        rounds=session.round_count,
                        verification=verification_payload,
                        error=session.error,
                    )
                session = self.store.update_session(
                    session.session_id,
                    status=SessionStatus.COMPLETED,
                    verification_id=getattr(report, "report_id", None),
                    error=None,
                )
                self.store.add_step(
                    session.session_id,
                    kind=StepKind.VERIFY,
                    status=StepStatus.COMPLETED,
                    output=verification_payload,
                )
                return LoopResult(
                    session=session,
                    status=SessionStatus.COMPLETED,
                    rounds=session.round_count,
                    verification=verification_payload,
                )

        # No gated writes → completed if we produced an answer; still honest about verify.
        if completed_writes and self.verification is None:
            session = self.store.update_session(
                session.session_id,
                status=SessionStatus.UNVERIFIED,
                error="Writes occurred but VerificationEngine unavailable (UNMEASURED)",
            )
            return LoopResult(
                session=session,
                status=SessionStatus.UNVERIFIED,
                rounds=session.round_count,
                error=session.error,
            )

        session = self.store.update_session(
            session.session_id,
            status=SessionStatus.COMPLETED,
            error=None,
        )
        self.store.add_step(
            session.session_id,
            kind=StepKind.RESPOND,
            status=StepStatus.COMPLETED,
            output={"reason": reason},
        )
        return LoopResult(session=session, status=SessionStatus.COMPLETED, rounds=session.round_count)

    def _build_messages(self, session: CodingSession) -> list[dict[str, str]]:
        history = self.store.list_turns(session.session_id)
        plan_bullets = build_initial_plan(session.user_goal, session.mission)
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
                    history=[{"role": t.role if t.role in {"user", "assistant"} else "user", "content": t.content} for t in history],
                    knowledge=[],
                    plan=plan,
                    mode="coding",
                    constraints=CODING_SYSTEM_PROMPT,
                    token_budget=getattr(getattr(self.settings, "coding", None), "token_budget", None),
                )
                return list(pack.messages)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": CODING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Mission={session.mission.value}\n"
                    f"Goal={session.user_goal}\n"
                    f"Plan:\n- " + "\n- ".join(plan_bullets)
                ),
            },
        ]
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
