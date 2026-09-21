"""Executable coding-job control contract (Milestone 2 / delivery 1).

Single source of truth for job lifecycle transitions and cooperative
checkpoints. Status changes alone are not resume/pause evidence — a worker
must reach a checkpoint (or fail to start) before pause/cancel become durable.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


JobStatus = Literal[
    "queued",
    "running",
    "pause_requested",
    "paused",
    "cancel_requested",
    "cancelled",
    "interrupted",
    "verified",
    "failed",
    "completed",
    "tests_failed",
    "no_change",
    "implementation_missing",
    "model_output_invalid",
    "model_unavailable",
]

TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "cancelled",
        "interrupted",
        "verified",
        "failed",
        "completed",
        "tests_failed",
        "no_change",
        "implementation_missing",
        "model_output_invalid",
        "model_unavailable",
    }
)

CONTROL_OWNER = {
    "queued": "CodingJobStore (accepted; waiting for worker claim)",
    "running": "Worker (lease held; executing runner)",
    "pause_requested": "CodingJobStore + ExecutionLeaseStore (user/API request)",
    "paused": "Worker checkpoint (lease released; checkpoint persisted)",
    "cancel_requested": "CodingJobStore (user/API request)",
    "cancelled": "Worker or pre-start gate (no further actions)",
    "interrupted": "CodingJobStore.recover_stale (worker loss)",
    "verified": "Runner result",
    "failed": "Runner/error path",
    "completed": "Runner result",
    "tests_failed": "Runner result",
    "no_change": "Runner result (mutation required but no material change)",
    "implementation_missing": "Runner result (no valid applied edits)",
    "model_output_invalid": "Runner result (structured output parse/schema failure)",
    "model_unavailable": "Runner result (no usable Coding model)",
}

# Allowed status transitions. pause_requested/cancel_requested may also live as
# flags while status stays running/queued until a checkpoint materializes them.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset(
        {
            "running",
            "pause_requested",
            "paused",
            "cancel_requested",
            "cancelled",
            "interrupted",
            "failed",
            "model_unavailable",
        }
    ),
    "running": frozenset(
        {
            "pause_requested",
            "paused",
            "cancel_requested",
            "cancelled",
            "interrupted",
            "verified",
            "failed",
            "completed",
            "tests_failed",
            "no_change",
            "implementation_missing",
            "model_output_invalid",
            "model_unavailable",
        }
    ),
    "pause_requested": frozenset({"paused", "running", "cancel_requested", "cancelled", "interrupted", "failed"}),
    "paused": frozenset({"queued", "cancel_requested", "cancelled", "interrupted"}),
    "cancel_requested": frozenset({"cancelled", "interrupted", "failed"}),
    "cancelled": frozenset(),
    "interrupted": frozenset({"queued", "cancelled"}),  # recover → re-queue or abandon
    "verified": frozenset(),
    "failed": frozenset(),
    "completed": frozenset(),
    "tests_failed": frozenset(),
    "no_change": frozenset(),
    "implementation_missing": frozenset(),
    "model_output_invalid": frozenset(),
    "model_unavailable": frozenset(),
}

InstructionStatus = Literal["received", "processed"]


class CodingJobCancelled(Exception):
    """Explicit cancellation — must not be treated as a generic investigate error."""

    def __init__(self, message: str = "cancel_requested", *, phase: str | None = None) -> None:
        super().__init__(message)
        self.phase = phase
        self.kind = "cancelled"


class CodingJobPaused(Exception):
    """Worker reached a cooperative pause checkpoint and must stop."""

    def __init__(self, message: str = "pause_checkpoint", *, checkpoint: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.checkpoint = checkpoint or {}
        self.kind = "paused"


@dataclass
class JobInstruction:
    version: int
    note: str
    received_at: float
    status: InstructionStatus = "received"
    processed_at: float | None = None
    effective_from_action: int | None = None
    effective_from_checkpoint: str | None = None
    id: str = field(default_factory=lambda: f"instr_{uuid.uuid4().hex[:10]}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "JobInstruction":
        return cls(
            version=int(raw.get("version") or 1),
            note=str(raw.get("note") or ""),
            received_at=float(raw.get("received_at") or time.time()),
            status=str(raw.get("status") or "received"),  # type: ignore[arg-type]
            processed_at=raw.get("processed_at"),
            effective_from_action=raw.get("effective_from_action"),
            effective_from_checkpoint=raw.get("effective_from_checkpoint"),
            id=str(raw.get("id") or f"instr_{uuid.uuid4().hex[:10]}"),
        )


def validate_transition(current: str, target: str) -> dict[str, Any]:
    cur = (current or "").strip() or "queued"
    tgt = (target or "").strip()
    if cur == tgt:
        return {"ok": True, "noop": True, "from": cur, "to": tgt}
    allowed = ALLOWED_TRANSITIONS.get(cur, frozenset())
    if tgt not in allowed:
        return {
            "ok": False,
            "from": cur,
            "to": tgt,
            "reason": "invalid_transition",
            "allowed": sorted(allowed),
            "owner_current": CONTROL_OWNER.get(cur),
            "owner_target": CONTROL_OWNER.get(tgt),
        }
    return {
        "ok": True,
        "from": cur,
        "to": tgt,
        "owner": CONTROL_OWNER.get(tgt),
    }


def is_terminal(status: str | None) -> bool:
    return str(status or "") in TERMINAL_STATUSES


def merge_goal_with_instructions(original_goal: str, instructions: list[dict[str, Any] | JobInstruction]) -> str:
    """Keep original goal; append processed + pending notes without dropping history."""
    goal = (original_goal or "").strip()
    lines: list[str] = []
    for item in instructions:
        raw = item.to_dict() if isinstance(item, JobInstruction) else dict(item)
        note = str(raw.get("note") or "").strip()
        if not note:
            continue
        ver = raw.get("version")
        st = raw.get("status") or "received"
        lines.append(f"[v{ver} {st}] {note}")
    if not lines:
        return goal
    return goal + "\n\nUser instructions (versioned):\n- " + "\n- ".join(lines)


def empty_checkpoint(*, phase: str = "init") -> dict[str, Any]:
    return {
        "phase": phase,
        "action_index": 0,
        "investigate_step": 0,
        "processed_instruction_version": 0,
        "work_root": None,
        "baseline_commit": None,
        "strategy": None,
        "saved_at": time.time(),
        "evidence": "checkpoint_initialized",
    }


def interpret_job_poll(
    snapshot: dict[str, Any] | None,
    *,
    poll_error: str | None = None,
    timed_out: bool = False,
) -> dict[str, Any]:
    """Map a job poll result to UI/runtime interpretation.

    Adversarial contract: HTTP/client poll timeout is NEVER completion evidence.
    Only an explicit terminal status from the store may be treated as done.
    """
    if timed_out or poll_error in {"timeout", "poll_timeout", "observation_timeout"}:
        return {
            "complete": False,
            "status": (snapshot or {}).get("status") if snapshot else "unknown",
            "reason": "poll_timeout_not_completion",
            "continue_observing": True,
            "false_success_rejected": True,
        }
    if snapshot is None:
        return {
            "complete": False,
            "status": "unknown",
            "reason": poll_error or "missing_snapshot",
            "continue_observing": True,
            "false_success_rejected": True,
        }
    status = str(snapshot.get("status") or "")
    terminal = is_terminal(status)
    return {
        "complete": terminal,
        "status": status,
        "reason": "terminal_status" if terminal else "in_progress",
        "continue_observing": not terminal,
        "false_success_rejected": False,
        "is_terminal": terminal,
        "worker_live": bool(snapshot.get("worker_live")),
    }


def control_contract_doc() -> dict[str, Any]:
    return {
        "owner_by_status": dict(CONTROL_OWNER),
        "allowed_transitions": {k: sorted(v) for k, v in ALLOWED_TRANSITIONS.items()},
        "terminal_statuses": sorted(TERMINAL_STATUSES),
        "notes": [
            "pause_requested becomes paused only at a cooperative checkpoint (or pre-start gate).",
            "resume must dispatch a worker from persisted execution payload; status=queued alone is insufficient.",
            "cancel_requested becomes cancelled without starting new model/edit/test actions.",
            "interrupted jobs are recoverable when execution_payload is complete.",
            "poll/observation timeout is never completion; only terminal store status is done.",
        ],
    }
