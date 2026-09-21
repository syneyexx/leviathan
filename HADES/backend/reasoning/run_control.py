"""Run control helpers: pause/resume/redirect with plan-version binding."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ControlAction = Literal[
    "status",
    "cancel",
    "pause",
    "resume",
    "redirect",
    "retry_step",
]


@dataclass(slots=True)
class RunControlCommand:
    action: ControlAction
    run_id: str
    plan_version: int | None = None
    instruction: str | None = None
    step_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RedirectEffect:
    accepted: bool
    plan_version: int
    reused_step_ids: list[str]
    invalidated_step_ids: list[str]
    new_instruction: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SAFE_PAUSE_PHASES = {
    "planned",
    "step_completed",
    "waiting_for_input",
    "verification_pending",
    "paused",
}


def can_pause_safely(phase: str | None, *, inflight_side_effects: bool = False) -> bool:
    """Paused must not be shown while unmanaged new actions keep starting."""
    if inflight_side_effects:
        return False
    return (phase or "") in SAFE_PAUSE_PHASES or phase in {None, "", "queued"}


def apply_redirect(
    *,
    current_plan_version: int,
    command_plan_version: int | None,
    steps: list[dict[str, Any]],
    completed_ids: set[str],
    new_instruction: str,
    target_step_ids: set[str] | None = None,
) -> RedirectEffect:
    """Bind redirect to plan version; reuse still-valid completed work."""
    if command_plan_version is not None and command_plan_version != current_plan_version:
        return RedirectEffect(
            accepted=False,
            plan_version=current_plan_version,
            reused_step_ids=sorted(completed_ids),
            invalidated_step_ids=[],
            new_instruction=new_instruction,
            reason="stale_plan_version",
        )

    # Default: invalidate incomplete steps; keep completed unless explicitly targeted.
    invalidated: set[str] = set()
    for index, step in enumerate(steps):
        sid = str(step.get("step_id") or step.get("id") or f"step-{index + 1}")
        status = str(step.get("status") or "pending")
        if target_step_ids and sid in target_step_ids:
            invalidated.add(sid)
            continue
        if status != "completed":
            invalidated.add(sid)

    reused = sorted(completed_ids - invalidated)
    return RedirectEffect(
        accepted=True,
        plan_version=current_plan_version + 1,
        reused_step_ids=reused,
        invalidated_step_ids=sorted(invalidated),
        new_instruction=new_instruction.strip(),
        reason="redirect_applied",
    )


def crash_recovery_notes(
    *,
    steps: list[dict[str, Any]],
    uncertain_external_actions: list[str] | None = None,
) -> dict[str, Any]:
    """After crash: restore known state; do not blindly replay uncertain side effects."""
    reset: list[str] = []
    completed: list[str] = []
    for index, step in enumerate(steps):
        sid = str(step.get("step_id") or step.get("id") or f"step-{index + 1}")
        status = str(step.get("status") or "pending")
        if status == "running":
            reset.append(sid)
        elif status == "completed":
            completed.append(sid)
    return {
        "requeued_uncertain_steps": reset,
        "completed_reusable": completed,
        "external_actions_unconfirmed": list(uncertain_external_actions or []),
        "note": "Externe acties met onzekere bijwerkingen worden niet blind herhaald.",
    }


def resume_after_browser_disconnect(
    *,
    status: str | None,
    worker_live: bool,
    dispatch_token: str | None = None,
) -> dict[str, Any]:
    """Browser refresh/reconnect must not start a second worker when one is live."""
    from reasoning.long_task_resume import is_worker_live

    info = is_worker_live(status=status, worker_live=worker_live)
    if info["worker_live"]:
        return {
            **info,
            "action": "observe_only",
            "start_worker": False,
            "dispatch_token": dispatch_token,
            "ui_note": "Bestaande worker loopt nog; vernieuwen start geen tweede worker.",
        }
    if info["status_label_stale"]:
        return {
            **info,
            "action": "recover_stale_then_resume",
            "start_worker": True,
            "dispatch_token": None,
            "ui_note": "Status 'running' zonder live process — hervatten na reclaim.",
        }
    return {
        **info,
        "action": "resume_if_paused_or_interrupted",
        "start_worker": str(status or "") in {"paused", "interrupted", "queued"},
        "dispatch_token": dispatch_token,
    }


def bind_run_identity(
    *,
    mission_id: str | None = None,
    task_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    artifact_ids: list[str] | None = None,
    fence_token: str | None = None,
    plan_version: int = 1,
    generation: int = 1,
) -> dict[str, Any]:
    from reasoning.long_task_resume import RunIdentity

    identity = RunIdentity(
        mission_id=mission_id,
        task_id=task_id,
        run_id=run_id,
        step_id=step_id,
        artifact_ids=list(artifact_ids or []),
        fence_token=fence_token,
        plan_version=plan_version,
        generation=generation,
    )
    return identity.to_dict()
