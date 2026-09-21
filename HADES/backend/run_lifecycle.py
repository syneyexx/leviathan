"""Single ownership map for run/task/mission/workflow status (A12).

Surfaces must not independently invent terminal success:

- **Work Runtime** (`TaskRunner`) owns Work task status. Completion requires a
  verified checkpoint (or an explicit no-verification path documented below).
- **Mission Control** mirrors Work Runtime via ``sync_mission_from_task`` and
  may *downgrade* claimed completion when acceptance evidence fails. It does
  not invent completion without a Work Runtime terminal signal.
- **Workflows** own workflow-run status only (product/heritage executors).
  They do not rewrite Work task or Mission status.
- **Coding jobs** use ``coding_job_control.CONTROL_OWNER`` (unchanged).

SQLite remains the persistence store. This module is typed contracts + helpers
only — not a second orchestration engine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

LifecycleSurface = Literal[
    "work_runtime",
    "mission_control",
    "workflow",
    "coding_job",
    "artifact",
    "policy",
    "model_gateway",
]

WorkTaskStatus = Literal[
    "queued",
    "running",
    "paused",
    "cancelled",
    "failed",
    "completed",
]

# One clear owner per surface for terminal / lifecycle decisions.
SURFACE_OWNERS: dict[LifecycleSurface, str] = {
    "work_runtime": "TaskRunner (Work task rows in core SQLite)",
    "mission_control": "Gen2Services.sync_mission_from_task (mirrors Work; evidence gate)",
    "workflow": "workflow_executor / heritage workflows (workflow run rows only)",
    "coding_job": "CodingJobStore + coding_job_control.CONTROL_OWNER",
    "artifact": "ArtifactService.verify_ready (bytes + status)",
    "policy": "policy_enforcement.enforce_tool_invocation_policies (deterministic)",
    "model_gateway": "reasoning.model_gateway.ModelGateway (shared capacity)",
}

# Who may set each Work task status.
WORK_STATUS_OWNER: dict[str, str] = {
    "queued": "API / scheduler (accepted; waiting for TaskRunner claim)",
    "running": "TaskRunner worker",
    "paused": "TaskRunner pause checkpoint",
    "cancelled": "TaskRunner cancel path (user/API request materialized)",
    "failed": "TaskRunner error / verification failure",
    "completed": "TaskRunner after decide_work_task_completion allows it",
}

MISSION_STATUS_OWNER = (
    "Mission Control mirrors Work Runtime; evidence-based downgrade of "
    "completed→failed is allowed; independent completed invent is forbidden."
)

WORKFLOW_STATUS_OWNER = (
    "Workflow executor owns workflow run status only; must not mutate Work/Mission "
    "completion rows."
)


@runtime_checkable
class ArtifactVerifier(Protocol):
    """Stable interface for deliverable verification (wraps ArtifactService)."""

    def verify_ready(self, artifact_id: str, **kwargs: Any) -> Mapping[str, Any]:
        ...


@runtime_checkable
class PolicyGate(Protocol):
    """Stable interface for deterministic tool/policy checks."""

    def __call__(self, **kwargs: Any) -> Mapping[str, Any]:
        ...


@runtime_checkable
class ModelAccess(Protocol):
    """Stable interface for shared model calls (wraps ModelGateway.chat)."""

    async def chat(self, *args: Any, **kwargs: Any) -> Any:
        ...


@dataclass(slots=True)
class WorkCompletionDecision:
    """Whether TaskRunner may mark a Work task ``completed``."""

    may_complete: bool
    reason: str
    owner: str = WORK_STATUS_OWNER["completed"]
    checkpoint_phase: str | None = None
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ownership_snapshot() -> dict[str, Any]:
    """Machine-readable ownership map for docs, demos, and /api introspection."""
    return {
        "surfaces": dict(SURFACE_OWNERS),
        "work_status_owner": dict(WORK_STATUS_OWNER),
        "mission_status_owner": MISSION_STATUS_OWNER,
        "workflow_status_owner": WORKFLOW_STATUS_OWNER,
        "rule": (
            "One owner per lifecycle surface. Mission Control and Workflows must not "
            "independently declare Work-task completion."
        ),
        "persistence": "sqlite",
    }


def decide_work_task_completion(
    *,
    checkpoint_state: Mapping[str, Any] | None,
    steps: list[Mapping[str, Any]] | None = None,
    cancelled: bool = False,
    required_tools_succeeded: bool | None = None,
    required_persistence_verified: bool | None = None,
) -> WorkCompletionDecision:
    """Gate Work Runtime ``completed`` on verification evidence.

    TaskRunner must call this before ``database.update_task(..., status=completed)``.
    Mission Control still re-checks acceptance when mirroring.

    Optional tool/persistence guards: when provided (not None), they must be True.
    The LLM cannot bypass these guards via checkpoint prose.
    """
    if cancelled:
        return WorkCompletionDecision(
            may_complete=False,
            reason="task_cancelled",
            checkpoint_phase=None,
            blockers=["cancelled"],
        )

    state = dict(checkpoint_state or {})
    phase = str(state.get("phase") or "").strip() or None
    blockers: list[str] = []

    if phase != "verified":
        blockers.append(f"checkpoint_phase:{phase or 'missing'}")
    if state.get("passed") is False:
        blockers.append("checkpoint_passed_false")

    step_rows = list(steps or [])
    if step_rows:
        failed = [s for s in step_rows if str(s.get("status") or "") == "failed"]
        blocked_steps = [s for s in step_rows if str(s.get("status") or "") == "blocked"]
        pending = [
            s
            for s in step_rows
            if str(s.get("status") or "") in {"pending", "queued", "ready", "running", ""}
        ]
        if failed:
            blockers.append(f"failed_steps:{len(failed)}")
        if blocked_steps:
            blockers.append(f"blocked_steps:{len(blocked_steps)}")
        if pending:
            blockers.append(f"pending_steps:{len(pending)}")

    if required_tools_succeeded is False:
        blockers.append("required_tools_not_succeeded")
    if required_persistence_verified is False:
        blockers.append("required_persistence_not_verified")

    # Model-authored checkpoint fields must not invent completion.
    for forbidden in ("knowledge_updated", "memory_updated", "tool_executed", "task_completed"):
        if state.get(forbidden) is True and phase != "verified":
            blockers.append(f"untrusted_model_flag:{forbidden}")

    if blockers:
        return WorkCompletionDecision(
            may_complete=False,
            reason="completion_blocked:" + ",".join(blockers),
            checkpoint_phase=phase,
            blockers=blockers,
        )

    return WorkCompletionDecision(
        may_complete=True,
        reason="verified_checkpoint",
        checkpoint_phase=phase,
        blockers=[],
    )


def mission_may_invent_completion() -> bool:
    """Mission Control never invents completion without a Work Runtime signal."""
    return False


def mission_may_downgrade(current_or_requested: str, proposed: str) -> bool:
    """Mission Control may only mutate a completion claim downward.

    Allowed: completed → failed (false-completion evidence).
    Forbidden: failed/cancelled → completed, or any invent of completion.
    """
    current = str(current_or_requested or "").strip().lower()
    target = str(proposed or "").strip().lower()
    return current == "completed" and target == "failed"


def reconcile_work_claimed_status(
    *,
    claimed_status: str,
    checkpoint_state: Mapping[str, Any] | None = None,
    steps: list[Mapping[str, Any]] | None = None,
    cancelled: bool = False,
    required_tools_succeeded: bool | None = None,
    required_persistence_verified: bool | None = None,
) -> tuple[str, WorkCompletionDecision | None]:
    """If a task claims ``completed`` without evidence, force ``failed``.

    Non-completed claims pass through unchanged. Callers must persist the
    returned status — completed+failed evidence must not stay completed.
    """
    claimed = str(claimed_status or "").strip().lower()
    if claimed != "completed":
        return claimed, None
    decision = decide_work_task_completion(
        checkpoint_state=checkpoint_state,
        steps=steps,
        cancelled=cancelled,
        required_tools_succeeded=required_tools_succeeded,
        required_persistence_verified=required_persistence_verified,
    )
    if decision.may_complete:
        return "completed", decision
    return "failed", decision


def work_control_transition_allowed(
    action: str,
    *,
    status: str,
    control_state: str | None = None,
) -> bool:
    """Whether pause / resume / cancel is a valid Work Runtime transition."""
    act = str(action or "").strip().lower()
    st = str(status or "").strip().lower()
    cs = str(control_state or "active").strip().lower()
    if act == "cancel":
        return st in {"queued", "running"}
    if act == "pause":
        return st == "running" and cs in {"active", "pause_requested", "paused"}
    if act == "resume":
        return st == "running" and cs in {"paused", "pause_requested"}
    return False


def workflow_owns_work_tasks() -> bool:
    """Workflows must not rewrite Work task completion."""
    return False
