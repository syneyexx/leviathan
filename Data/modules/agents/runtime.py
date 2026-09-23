from __future__ import annotations

from typing import Any, Protocol

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway
from Data.modules.jobs import JobRuntime, JobState
from Data.modules.verification import VerificationEngine, VerificationRequirement

from .planner import StructuredAgentPlan, StructuredAgentPlanner
from .types import AgentKind, AgentResult, AgentStep, AgentStepKind


class RunFactory(Protocol):
    def create_run(self, *, user_request: str, conversation_id: str | None = None): ...


class AgentRuntime:
    """Strategy layer over shared Run / Job / Gateway / Verification infrastructure.

    Agents never execute side effects directly — only via ExecutionGateway or JobRuntime.
    """

    def __init__(
        self,
        *,
        gateway: ExecutionGateway,
        jobs: JobRuntime | None = None,
        verification: VerificationEngine | None = None,
        runs: RunFactory | None = None,
        agents_enabled: bool = False,
        coding: Any | None = None,
        coding_enabled: bool = False,
        planner: StructuredAgentPlanner | None = None,
    ) -> None:
        self.gateway = gateway
        self.jobs = jobs
        self.verification = verification
        self.runs = runs
        self.agents_enabled = agents_enabled
        self.coding = coding
        self.coding_enabled = coding_enabled
        self.planner = planner or StructuredAgentPlanner()

    def plan(self, request: str, *, kind: AgentKind = AgentKind.GENERIC) -> list[AgentStep]:
        """Return structured plan steps (U142). Prefer ``plan_structured`` for full schema."""
        return list(self.plan_structured(request, kind=kind).steps)

    def plan_structured(
        self,
        request: str,
        *,
        kind: AgentKind = AgentKind.GENERIC,
    ) -> StructuredAgentPlan:
        available: list[str] = []
        try:
            available = [item.id for item in self.gateway.catalog.list()]
        except Exception:  # noqa: BLE001
            available = []
        return self.planner.plan(request, kind=kind, available_capabilities=available)

    def execute(
        self,
        request: str,
        *,
        kind: AgentKind = AgentKind.GENERIC,
        steps: list[AgentStep] | None = None,
        run_id: str | None = None,
        conversation_id: str | None = None,
        use_jobs: bool = False,
        verify_requirements: list[VerificationRequirement] | None = None,
        capability_overrides: dict[str, dict[str, Any]] | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> AgentResult:
        if not self.agents_enabled:
            return AgentResult(
                agent_kind=kind,
                run_id=run_id,
                status="DISABLED",
                error="Agents feature flag is OFF (LEVIATHAN_FEATURE_AGENTS)",
            )

        # When coding is enabled, delegate CODING executes to the control plane
        # without blocking the caller for a full LLM loop (wake worker only).
        if kind == AgentKind.CODING and self.coding_enabled and self.coding is not None:
            session = self.coding.create_session(
                goal=request,
                conversation_id=conversation_id,
            )
            if session.status.value != "DISABLED":
                self.coding.start_turn(session.session_id, message=request)
            return AgentResult(
                agent_kind=kind,
                run_id=session.run_id or run_id,
                status=session.status.value,
                output=f"coding session {session.session_id}",
                steps=[
                    {
                        "kind": "PLAN",
                        "note": "Delegated to CodingControlPlane (non-blocking worker)",
                        "status": "OK",
                        "session_id": session.session_id,
                    }
                ],
                error=session.error,
            )

        created_run_id = run_id
        if created_run_id is None and self.runs is not None:
            run = self.runs.create_run(user_request=request, conversation_id=conversation_id)
            created_run_id = getattr(run, "run_id", None)

        structured = self.plan_structured(request, kind=kind)
        plan = steps if steps is not None else list(structured.steps)
        result = AgentResult(agent_kind=kind, run_id=created_run_id, status="RUNNING")
        overrides = capability_overrides or {}
        tool_budget = int((structured.budget or {}).get("max_tool_calls") or 8)
        tools_used = 0

        for step in plan:
            step_record = step.public_dict()
            if step.kind == AgentStepKind.CAPABILITY:
                if tools_used >= tool_budget:
                    step_record["status"] = "SKIPPED"
                    step_record["error"] = "agent tool budget exhausted"
                    result.steps.append(step_record)
                    continue
                if not step.capability_id:
                    step_record["status"] = "SKIPPED"
                    step_record["error"] = "missing capability_id"
                    result.steps.append(step_record)
                    continue
                args = dict(step.arguments)
                if step.capability_id in overrides:
                    args.update(overrides[step.capability_id])
                if step.capability_id == "file.read" and "path" not in args:
                    step_record["status"] = "SKIPPED"
                    step_record["error"] = "file.read requires path"
                    result.steps.append(step_record)
                    continue

                tools_used += 1
                if use_jobs and self.jobs is not None:
                    job = self.jobs.enqueue(
                        capability_id=step.capability_id,
                        arguments=args,
                        approval_id=step.approval_id,
                        run_id=created_run_id,
                        requested_by=f"agent:{kind.value.lower()}",
                        trace_id=trace_id,
                        idempotency_key=(
                            f"{idempotency_key}:{step.capability_id}" if idempotency_key else None
                        ),
                    )
                    done = self.jobs.process_next()
                    result.job_ids.append(job.job_id)
                    step_record["job_id"] = job.job_id
                    step_record["status"] = (done.state.value if done else JobState.QUEUED.value)
                    if done and done.result:
                        step_record["result"] = done.result
                    if done and done.error:
                        step_record["error"] = done.error
                else:
                    cap = self.gateway.execute(
                        CapabilityRequest(
                            capability_id=step.capability_id,
                            arguments=args,
                            approval_id=step.approval_id,
                            run_id=created_run_id,
                            requested_by=f"agent:{kind.value.lower()}",
                            trace_id=trace_id,
                            idempotency_key=(
                                f"{idempotency_key}:{step.capability_id}"
                                if idempotency_key
                                else None
                            ),
                        )
                    )
                    step_record["status"] = cap.status.value
                    step_record["result"] = cap.public_dict()
                    if cap.status != CapabilityStatus.COMPLETED:
                        step_record["error"] = cap.error
            else:
                step_record["status"] = "OK"
            result.steps.append(step_record)

        if verify_requirements and self.verification is not None:
            report = self.verification.verify(
                verify_requirements,
                run_id=created_run_id,
            )
            result.verification = report.public_dict()
            if report.outcome.value != "PASSED":
                result.status = "UNVERIFIED"
                result.error = f"Verification {report.outcome.value}"
                return result

        failed = any(step.get("status") in {"FAILED", "REJECTED", "TIMEOUT"} for step in result.steps)
        result.status = "FAILED" if failed else "COMPLETED"
        result.output = f"{kind.value} agent finished with {len(result.steps)} step(s)"
        return result
