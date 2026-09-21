"""Authoritative linked Work status for conversation working-state projections.

Conversation completion must never invent Work completion. Work Runtime +
verified checkpoint / ``decide_work_task_completion`` own completion.
"""

from __future__ import annotations

from typing import Any, Mapping

from run_lifecycle import decide_work_task_completion


# Task statuses that remain represented in open_work (not removed).
_OPEN_REPRESENTATION = frozenset(
    {"queued", "running", "failed", "cancelled", "blocked", "partial", "paused"}
)


def resolve_linked_work_truth(
    *,
    linked_task_id: str,
    task: Mapping[str, Any] | None,
    checkpoint_state: Mapping[str, Any] | None = None,
    steps: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve whether a linked task may leave open_work.

    Returns:
      {
        "task_id": str,
        "status": str,           # authoritative or retained projection status
        "may_remove": bool,      # True only when verified completion allows it
        "reason": str,
        "missing": bool,
      }
    """
    task_id = str(linked_task_id or "").strip()
    if not task_id:
        return {
            "task_id": task_id,
            "status": "unknown",
            "may_remove": False,
            "reason": "missing_task_id",
            "missing": True,
        }

    if not task:
        return {
            "task_id": task_id,
            "status": "unknown",
            "may_remove": False,
            "reason": "linked_task_not_found",
            "missing": True,
        }

    status = str(task.get("status") or "").strip().lower() or "unknown"
    if status != "completed":
        # Failed/cancelled/queued/running stay represented — never invent completed.
        return {
            "task_id": task_id,
            "status": status if status in _OPEN_REPRESENTATION or status == "completed" else status,
            "may_remove": False,
            "reason": f"task_status:{status}",
            "missing": False,
        }

    decision = decide_work_task_completion(
        checkpoint_state=checkpoint_state,
        steps=list(steps or []),
        cancelled=False,
    )
    if not decision.may_complete:
        return {
            "task_id": task_id,
            "status": "completed",  # DB claims completed but gate denies verified completion
            "may_remove": False,
            "reason": decision.reason,
            "missing": False,
            "checkpoint_phase": decision.checkpoint_phase,
            "blockers": list(decision.blockers),
        }

    return {
        "task_id": task_id,
        "status": "completed",
        "may_remove": True,
        "reason": "verified_checkpoint",
        "missing": False,
        "checkpoint_phase": decision.checkpoint_phase,
    }
