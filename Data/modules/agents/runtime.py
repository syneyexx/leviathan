from __future__ import annotations

from typing import Any, Protocol

from Data.modules.execution import CapabilityRequest, CapabilityStatus, ExecutionGateway
from Data.modules.jobs import JobRuntime, JobState
from Data.modules.verification import VerificationEngine, VerificationRequirement

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
    ) -> None:
        self.gateway = gateway
        self.jobs = jobs
        self.verification = verification
        self.runs = runs
        self.agents_enabled = agents_enabled

    def plan(self, request: str, *, kind: AgentKind = AgentKind.GENERIC) -> list[AgentStep]:
        text = request.strip()
        steps: list[AgentStep] = [
            AgentStep(kind=AgentStepKind.PLAN, note=f"{kind.value} plan for: {text[:120]}")
        ]
        lowered = text.lower()
        if "search" in lowered or "find" in lowered or kind == AgentKind.RESEARCH:
            steps.append(
                AgentStep(
                    kind=AgentStepKind.CAPABILITY,
                    capability_id="knowledge.search",
                    arguments={"query": text, "limit": 5},
                    note="Retrieve knowledge via capability gateway",
                )
            )
        if kind == AgentKind.CODING and ("read" in lowered or "file" in lowered):
            # Coding agent still must go through capabilities — no private FS.
            steps.append(
                AgentStep(
                    kind=AgentStepKind.CAPABILITY,
                    capability_id="file.read",
                    arguments={},
                    note="Coding file read requires path argument from caller",
                )
            )
        steps.append(AgentStep(kind=AgentStepKind.RESPOND, note="Return structured agent result"))
        return steps

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
    ) -> AgentResult:
        if not self.agents_enabled:
            return AgentResult(
                agent_kind=kind,
                run_id=run_id,
                status="DISABLED",
                error="Agents feature flag is OFF (LEVIATHAN_FEATURE_AGENTS)",
            )

        created_run_id = run_id
        if created_run_id is None and self.runs is not None:
            run = self.runs.create_run(user_request=request, conversation_id=conversation_id)
            created_run_id = getattr(run, "run_id", None)

        plan = steps if steps is not None else self.plan(request, kind=kind)
        result = AgentResult(agent_kind=kind, run_id=created_run_id, status="RUNNING")
        overrides = capability_overrides or {}

        for step in plan:
            step_record = step.public_dict()
            if step.kind == AgentStepKind.CAPABILITY:
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

                if use_jobs and self.jobs is not None:
                    job = self.jobs.enqueue(
                        capability_id=step.capability_id,
                        arguments=args,
                        approval_id=step.approval_id,
                        run_id=created_run_id,
                        requested_by=f"agent:{kind.value.lower()}",
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
