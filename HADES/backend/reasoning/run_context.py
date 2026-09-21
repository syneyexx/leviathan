"""Shared run context — single contract across chat, coding, Work, Committee, Gen2.

Adapters wrap existing subsystems; this is not a second TaskRunner.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RunKind = Literal["chat", "work", "coding", "committee", "mission", "eval", "research"]


@dataclass(slots=True)
class RunContext:
    """Observable execution context shared across HADES surfaces."""

    run_id: str
    kind: RunKind
    goal: str
    constraints: list[str] = field(default_factory=list)
    selected_sources: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    terminal_status: str | None = None
    approach_summary: str = ""
    decisions: list[str] = field(default_factory=list)
    open_criteria: list[str] = field(default_factory=list)
    failed_attempts: list[dict[str, Any]] = field(default_factory=list)
    parent_run_id: str | None = None
    mission_id: str | None = None
    task_id: str | None = None
    model_id: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunContext":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        payload = {k: v for k, v in (data or {}).items() if k in known}
        if "kind" not in payload:
            payload["kind"] = "chat"
        if "run_id" not in payload:
            payload["run_id"] = "unknown"
        if "goal" not in payload:
            payload["goal"] = ""
        return cls(**payload)


def adapt_from_working_state(
    *,
    run_id: str,
    kind: RunKind,
    goal: str,
    working_state: dict[str, Any] | None = None,
    config_snapshot: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    model_id: str | None = None,
    task_id: str | None = None,
    mission_id: str | None = None,
) -> RunContext:
    state = dict(working_state or {})
    return RunContext(
        run_id=run_id,
        kind=kind,
        goal=str(state.get("goal") or goal or "").strip(),
        constraints=list(state.get("constraints") or []),
        decisions=list(state.get("decisions") or []),
        open_criteria=list(state.get("open_work") or state.get("open_criteria") or []),
        artifacts=list(state.get("artifact_refs") or state.get("artifacts") or []),
        selected_sources=list(state.get("selected_sources") or []),
        config_snapshot=dict(config_snapshot or {}),
        budget=dict(budget or {}),
        model_id=model_id,
        task_id=task_id,
        mission_id=mission_id,
        approach_summary=str(state.get("approach_summary") or ""),
        progress=dict(state.get("progress") or {}),
    )


def adapt_from_coding(coding_payload: dict[str, Any], *, run_id: str) -> RunContext:
    ctx = dict((coding_payload or {}).get("context") or {})
    return RunContext(
        run_id=run_id,
        kind="coding",
        goal=str(ctx.get("goal") or ""),
        constraints=[],
        selected_sources=[{"path": p} for p in (ctx.get("change_scope") or [])],
        config_snapshot={
            "source_repo": ctx.get("source_repo"),
            "branch": ctx.get("branch"),
            "commit": ctx.get("commit"),
            "test_suite": ctx.get("test_suite"),
            "test_args": ctx.get("test_args"),
            "config_version": ctx.get("config_version"),
            "dirty_files": ctx.get("dirty_files"),
            "instruction_files": ctx.get("instruction_files"),
        },
        budget={},
        artifacts=list((coding_payload or {}).get("artifacts") or []),
        verification={"status": (coding_payload or {}).get("status")},
        terminal_status=str((coding_payload or {}).get("status") or "") or None,
        model_id=ctx.get("model_id"),
        approach_summary=str((coding_payload or {}).get("summary") or ""),
        progress={"explore": (coding_payload or {}).get("explore")},
    )


def adapt_from_mission(mission: dict[str, Any]) -> RunContext:
    return RunContext(
        run_id=str(mission.get("execution_id") or mission.get("id") or "mission"),
        kind="mission",
        goal=str(mission.get("goal") or mission.get("title") or ""),
        constraints=list(mission.get("acceptance_criteria") or []),
        open_criteria=list(mission.get("acceptance_criteria") or []),
        plan=dict(mission.get("ir") or {}),
        budget=dict(mission.get("budgets") or {}),
        verification=dict(mission.get("verification") or {}),
        terminal_status=str(mission.get("status") or "") or None,
        mission_id=str(mission.get("id") or "") or None,
        task_id=str(mission.get("task_id") or "") or None,
        progress={"gates": mission.get("gates"), "status": mission.get("status")},
    )


def merge_tool_result(ctx: RunContext, observation: dict[str, Any]) -> RunContext:
    tools = list(ctx.tool_results)
    tools.append(dict(observation))
    ctx.tool_results = tools[-100:]
    return ctx


def record_failed_attempt(ctx: RunContext, *, reason: str, detail: dict[str, Any] | None = None) -> RunContext:
    attempts = list(ctx.failed_attempts)
    attempts.append({"reason": reason, **(detail or {})})
    ctx.failed_attempts = attempts[-50:]
    return ctx


def compact_for_summary(ctx: RunContext) -> dict[str, Any]:
    """Long-run summary fields that must survive context compaction (E5)."""
    return {
        "goal": ctx.goal,
        "constraints": ctx.constraints,
        "decisions": ctx.decisions,
        "open_criteria": ctx.open_criteria,
        "failed_attempts": ctx.failed_attempts,
        "artifact_refs": [a.get("id") or a.get("path") or a for a in ctx.artifacts][:40],
        "verification": ctx.verification,
        "terminal_status": ctx.terminal_status,
        "config_snapshot_keys": sorted(ctx.config_snapshot.keys()),
        "version": ctx.version,
    }
