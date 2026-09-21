"""Dependent/parallel work-step scheduling with plan validation.

Keep SQLite transactions short: never wait on model/network/tool I/O inside a write txn.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


class PlanValidationError(ValueError):
    """Raised when a work plan is structurally invalid."""

    def __init__(self, message: str, *, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or {}


StepStatus = Literal[
    "pending",
    "ready",
    "queued",
    "running",
    "completed",
    "failed",
    "blocked",
    "cancelled",
]

TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled", "blocked"})
DONE_STATUSES = frozenset({"completed"})
ACTIVE_STATUSES = frozenset({"pending", "ready", "queued", "running"})


@dataclass(slots=True)
class ScheduledStep:
    step_id: str
    title: str
    instruction: str
    agent_id: str
    kind: str = "work"
    depends_on: list[str] = field(default_factory=list)
    expected_evidence: list[str] = field(default_factory=list)
    status: str = "pending"
    input_refs: list[str] = field(default_factory=list)
    output_schema: dict[str, Any] = field(default_factory=dict)
    required_capability: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ValidatedPlan:
    goal: str
    acceptance_criteria: list[str]
    steps: list[ScheduledStep]
    version: int = 1
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "acceptance_criteria": list(self.acceptance_criteria),
            "steps": [step.to_dict() for step in self.steps],
            "version": self.version,
            "notes": list(self.notes),
        }


def _step_key(step: dict[str, Any] | ScheduledStep, index: int) -> str:
    if isinstance(step, ScheduledStep):
        return step.step_id or f"step-{index + 1}"
    return str(step.get("step_id") or step.get("id") or f"step-{index + 1}")


def validate_plan(
    raw: dict[str, Any] | list[Any],
    *,
    allowed_agents: set[str],
    max_steps: int = 8,
    max_dependency_depth: int = 6,
    default_agent: str = "executor",
    require_executable_path: bool = True,
    enforce_capabilities: bool = True,
) -> ValidatedPlan:
    """Validate references, reject cycles, check agents and capability ownership.

    A plan must not start unless:
    - every dependency references an existing step
    - there is at least one root step with no unresolved dependencies
    - no dependency cycles exist
    - every step has a valid executor/capability
    - every required executor actually exists and owns the required capability
    - the graph contains at least one executable path
    """
    from .work_capabilities import (
        executor_supports,
        infer_required_capability,
        validate_step_capability_assignment,
    )

    if isinstance(raw, list):
        goal = ""
        criteria: list[str] = []
        raw_steps = raw
        version = 1
        notes: list[str] = []
    else:
        goal = str(raw.get("goal") or "")
        criteria = [str(item).strip()[:500] for item in (raw.get("acceptance_criteria") or []) if str(item).strip()][:12]
        raw_steps = raw.get("steps") or []
        version = int(raw.get("version") or 1)
        notes = [str(item) for item in (raw.get("notes") or [])][:20]

    if not isinstance(raw_steps, list):
        raise PlanValidationError("steps must be a list")
    if not raw_steps:
        raise PlanValidationError("plan has no steps", diagnostics={"missing_executors": [], "cycle_detected": False})
    if len(raw_steps) > max_steps:
        raise PlanValidationError(f"plan exceeds max_steps={max_steps}")

    steps: list[ScheduledStep] = []
    ids: list[str] = []
    missing_executors: list[str] = []
    capability_mismatches: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise PlanValidationError(f"step {index} is not an object")
        instruction = str(raw_step.get("instruction") or "").strip()
        if not instruction:
            raise PlanValidationError(f"step {index} missing instruction")
        step_id = _step_key(raw_step, index)
        if step_id in ids:
            raise PlanValidationError(f"duplicate step_id '{step_id}'")
        agent_id = str(raw_step.get("agent_id") or default_agent).strip()
        if agent_id not in allowed_agents:
            missing_executors.append(agent_id or f"<empty:{step_id}>")
            if default_agent in allowed_agents:
                # Still record the missing executor; remapping is only allowed when
                # require_executable_path is false (legacy callers).
                if require_executable_path:
                    raise PlanValidationError(
                        f"agent '{agent_id}' not allowed for step '{step_id}'",
                        diagnostics={"missing_executors": missing_executors, "step_id": step_id},
                    )
                agent_id = default_agent
            else:
                raise PlanValidationError(
                    f"agent '{agent_id}' not allowed",
                    diagnostics={"missing_executors": missing_executors},
                )
        depends = raw_step.get("depends_on") or []
        if not isinstance(depends, list):
            raise PlanValidationError(f"step '{step_id}' depends_on must be a list")
        depends_on = [str(item) for item in depends]
        status = str(raw_step.get("status") or "pending")
        if status == "queued":
            status = "pending"
        kind = str(raw_step.get("kind") or "work")[:40]
        title = str(raw_step.get("title") or f"Stap {index + 1}")[:160]
        required_capability = str(raw_step.get("required_capability") or "").strip()
        if not required_capability:
            required_capability = infer_required_capability(instruction, title=title, kind=kind) or ""
        if enforce_capabilities and required_capability:
            mismatch = validate_step_capability_assignment(
                step_id=step_id,
                agent_id=agent_id,
                required_capability=required_capability,
            )
            if mismatch:
                capability_mismatches.append(mismatch)
                raise PlanValidationError(
                    f"step '{step_id}' executor '{agent_id}' lacks required capability '{required_capability}'",
                    diagnostics={
                        "capability_mismatches": capability_mismatches,
                        "step_id": step_id,
                        "required_capability": required_capability,
                        "assigned_executor": agent_id,
                        "executor_capability_mismatch": True,
                    },
                )
            if not executor_supports(agent_id, required_capability):
                raise PlanValidationError(
                    f"step '{step_id}' capability mismatch for '{required_capability}'",
                    diagnostics={"capability_mismatches": capability_mismatches},
                )
        steps.append(
            ScheduledStep(
                step_id=step_id,
                title=title,
                instruction=instruction[:20_000],
                agent_id=agent_id,
                kind=kind,
                depends_on=depends_on,
                expected_evidence=[str(item) for item in (raw_step.get("expected_evidence") or [])][:12],
                status=status,
                input_refs=[str(item) for item in (raw_step.get("input_refs") or [])][:24],
                output_schema=dict(raw_step.get("output_schema") or {}) if isinstance(raw_step.get("output_schema"), dict) else {},
                required_capability=required_capability,
            )
        )
        ids.append(step_id)

    id_set = set(ids)
    for step in steps:
        for dep in step.depends_on:
            if dep not in id_set:
                raise PlanValidationError(
                    f"step '{step.step_id}' depends on unknown '{dep}'",
                    diagnostics={"unknown_dependency": dep, "step_id": step.step_id},
                )
            if dep == step.step_id:
                raise PlanValidationError(f"step '{step.step_id}' cannot depend on itself")

    # Cycle detection via DFS
    graph = {step.step_id: list(step.depends_on) for step in steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, depth: int) -> None:
        if depth > max_dependency_depth:
            raise PlanValidationError(f"dependency depth exceeds {max_dependency_depth}")
        if node in visiting:
            raise PlanValidationError(
                "cyclic dependencies are not allowed",
                diagnostics={"cycle_detected": True, "node": node},
            )
        if node in visited:
            return
        visiting.add(node)
        for parent in graph.get(node, []):
            dfs(parent, depth + 1)
        visiting.remove(node)
        visited.add(node)

    for step_id in ids:
        dfs(step_id, 0)

    roots = [step.step_id for step in steps if not step.depends_on]
    if require_executable_path and not roots:
        raise PlanValidationError(
            "plan has no root step with empty depends_on",
            diagnostics={"cycle_detected": False, "roots": []},
        )

    # At least one executable path: a non-empty ready set from a fresh pending plan.
    if require_executable_path:
        ready = ready_steps(steps, completed_ids=set(), failed_ids=set())
        if not ready:
            raise PlanValidationError(
                "plan has no executable path (no ready root steps)",
                diagnostics=diagnose_deadlock(steps),
            )

    if not criteria:
        criteria = [
            "De oorspronkelijke opdracht is volledig beantwoord.",
            "Belangrijke aannames, fouten en afhankelijkheden zijn gecontroleerd.",
            "Het eindresultaat doet geen onbewezen claim dat iets werkt of klaar is.",
        ]

    return ValidatedPlan(goal=goal, acceptance_criteria=criteria, steps=steps, version=version, notes=notes)


def _normalize_steps(steps: list[ScheduledStep] | list[dict[str, Any]]) -> list[ScheduledStep]:
    normalized: list[ScheduledStep] = []
    for index, step in enumerate(steps):
        if isinstance(step, ScheduledStep):
            normalized.append(step)
        else:
            status = str(step.get("status") or "pending")
            if status == "queued":
                status = "pending"
            schema = dict(step.get("output_schema") or {}) if isinstance(step.get("output_schema"), dict) else {}
            required_capability = str(step.get("required_capability") or schema.get("required_capability") or "")
            normalized.append(
                ScheduledStep(
                    step_id=_step_key(step, index),
                    title=str(step.get("title") or f"Stap {index + 1}"),
                    instruction=str(step.get("instruction") or ""),
                    agent_id=str(step.get("agent_id") or "executor"),
                    kind=str(step.get("kind") or "work"),
                    depends_on=[str(item) for item in (step.get("depends_on") or [])],
                    status=status,
                    input_refs=[str(item) for item in (step.get("input_refs") or [])],
                    output_schema=schema,
                    required_capability=required_capability,
                )
            )
    return normalized


def evaluate_dependency_states(
    steps: list[ScheduledStep] | list[dict[str, Any]],
    *,
    completed_ids: set[str] | None = None,
    failed_ids: set[str] | None = None,
    cancelled_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Deterministic per-step dependency evaluation."""
    normalized = _normalize_steps(steps)
    completed = set(completed_ids or set())
    failed = set(failed_ids or set())
    cancelled = set(cancelled_ids or set())
    blocked_ids: set[str] = set()
    for step in normalized:
        if step.status == "completed":
            completed.add(step.step_id)
        elif step.status == "failed":
            failed.add(step.step_id)
        elif step.status == "blocked":
            blocked_ids.add(step.step_id)
        elif step.status == "cancelled":
            cancelled.add(step.step_id)

    dependency_states: dict[str, dict[str, Any]] = {}
    for step in normalized:
        deps = list(step.depends_on)
        dep_completed = [d for d in deps if d in completed]
        dep_failed = [d for d in deps if d in failed or d in cancelled or d in blocked_ids]
        dep_pending = [d for d in deps if d not in completed and d not in failed and d not in cancelled and d not in blocked_ids]
        blocked = bool(dep_failed) or step.status == "blocked"
        ready = (
            step.status in {"pending", "ready", "queued"}
            and not blocked
            and step.status != "blocked"
            and all(d in completed for d in deps)
            and step.step_id not in completed
            and step.step_id not in failed
            and step.step_id not in cancelled
        )
        dependency_states[step.step_id] = {
            "status": step.status,
            "depends_on": deps,
            "deps_completed": dep_completed,
            "deps_failed": dep_failed,
            "deps_pending": dep_pending,
            "blocked": blocked,
            "ready": ready,
            "agent_id": step.agent_id,
        }
    return {
        "completed_ids": sorted(completed),
        "failed_ids": sorted(failed),
        "cancelled_ids": sorted(cancelled),
        "dependency_states": dependency_states,
    }


def apply_blocked_statuses(
    steps: list[ScheduledStep] | list[dict[str, Any]],
    *,
    completed_ids: set[str] | None = None,
    failed_ids: set[str] | None = None,
    cancelled_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return step dicts with blocked status when a required dependency failed/cancelled."""
    evaluation = evaluate_dependency_states(
        steps,
        completed_ids=completed_ids,
        failed_ids=failed_ids,
        cancelled_ids=cancelled_ids,
    )
    states = evaluation["dependency_states"]
    out: list[dict[str, Any]] = []
    for index, step in enumerate(_normalize_steps(steps)):
        payload = step.to_dict()
        state = states.get(step.step_id) or {}
        if state.get("blocked") and step.status in {"pending", "ready", "queued"}:
            payload["status"] = "blocked"
        elif state.get("ready") and step.status in {"pending", "queued"}:
            payload["status"] = "ready"
        out.append(payload)
    return out


def ready_steps(
    steps: list[ScheduledStep] | list[dict[str, Any]],
    *,
    completed_ids: set[str] | None = None,
    failed_ids: set[str] | None = None,
    cancelled_ids: set[str] | None = None,
) -> list[str]:
    """Return step ids that are executable now.

    A step is executable only when:
    status in {pending, ready, queued}
    AND all required dependencies == completed
    AND no required dependency == failed/cancelled/blocked
    """
    evaluation = evaluate_dependency_states(
        steps,
        completed_ids=completed_ids,
        failed_ids=failed_ids,
        cancelled_ids=cancelled_ids,
    )
    ready: list[str] = []
    for step_id, state in evaluation["dependency_states"].items():
        if state.get("ready") and not state.get("blocked"):
            if state.get("status") in {"pending", "ready", "queued"}:
                ready.append(step_id)
    return ready


def detect_cycle(steps: list[ScheduledStep] | list[dict[str, Any]]) -> bool:
    normalized = _normalize_steps(steps)
    graph = {step.step_id: list(step.depends_on) for step in normalized}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for parent in graph.get(node, []):
            if dfs(parent):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(dfs(step.step_id) for step in normalized)


def diagnose_deadlock(
    steps: list[ScheduledStep] | list[dict[str, Any]],
    *,
    completed_ids: set[str] | None = None,
    failed_ids: set[str] | None = None,
    cancelled_ids: set[str] | None = None,
    allowed_agents: set[str] | None = None,
) -> dict[str, Any]:
    """Explain why no executable steps exist, including capability mismatches."""
    from .work_capabilities import executor_supports, infer_required_capability

    normalized = _normalize_steps(steps)
    evaluation = evaluate_dependency_states(
        normalized,
        completed_ids=completed_ids,
        failed_ids=failed_ids,
        cancelled_ids=cancelled_ids,
    )
    states = evaluation["dependency_states"]
    status_by_id = {step.step_id: step.status for step in normalized}
    for sid, st in states.items():
        status_by_id[sid] = str(st.get("status") or status_by_id.get(sid) or "pending")

    pending_steps = [sid for sid, st in states.items() if st["status"] in {"pending", "ready", "queued"}]
    blocked_steps = [
        sid
        for sid, st in states.items()
        if st["status"] == "blocked" or st.get("blocked")
    ]
    for sid, st in states.items():
        if st.get("blocked") and sid not in blocked_steps:
            blocked_steps.append(sid)
    failed_steps = list(evaluation["failed_ids"])
    missing_executors: list[str] = []
    capability_mismatches: list[dict[str, Any]] = []
    step_diagnostics: list[dict[str, Any]] = []

    for step in normalized:
        required = step.required_capability or infer_required_capability(
            step.instruction, title=step.title, kind=step.kind
        ) or ""
        supports = executor_supports(step.agent_id, required) if required else True
        if allowed_agents is not None and step.agent_id not in allowed_agents:
            missing_executors.append(f"{step.step_id}:{step.agent_id}")
        dep_statuses = {
            dep: status_by_id.get(dep, "missing")
            for dep in step.depends_on
        }
        blocked = bool(states.get(step.step_id, {}).get("blocked"))
        blocking_reason = None
        if not supports and required:
            blocking_reason = "executor_capability_mismatch"
            capability_mismatches.append(
                {
                    "step_id": step.step_id,
                    "assigned_executor": step.agent_id,
                    "required_capability": required,
                    "executor_supports_capability": False,
                }
            )
        elif any(status_by_id.get(dep) == "failed" for dep in step.depends_on):
            blocking_reason = "dependency_failed"
        elif any(status_by_id.get(dep) in {"cancelled", "blocked"} for dep in step.depends_on):
            blocking_reason = "dependency_blocked"
        elif step.depends_on and not all(status_by_id.get(dep) == "completed" for dep in step.depends_on):
            blocking_reason = "dependencies_unsatisfied"
        step_diagnostics.append(
            {
                "step_id": step.step_id,
                "status": step.status,
                "depends_on": list(step.depends_on),
                "dependency_statuses": dep_statuses,
                "assigned_executor": step.agent_id,
                "required_capability": required or None,
                "executor_supports_capability": supports,
                "blocked": blocked or blocking_reason is not None and step.status in {"pending", "ready", "queued", "blocked"},
                "blocking_reason": blocking_reason,
            }
        )

    ready = ready_steps(
        normalized,
        completed_ids=set(evaluation["completed_ids"]),
        failed_ids=set(evaluation["failed_ids"]),
        cancelled_ids=set(evaluation["cancelled_ids"]),
    )
    reasons: list[str] = []
    if detect_cycle(normalized):
        reasons.append("cycle_detected")
    if blocked_steps:
        reasons.append("blocked_by_failed_dependency")
    if missing_executors:
        reasons.append("missing_executors")
    if capability_mismatches:
        reasons.append("executor_capability_mismatch")
    if pending_steps and not ready and not blocked_steps and not detect_cycle(normalized):
        reasons.append("unsatisfied_dependencies")
    if not pending_steps and not ready:
        reasons.append("no_pending_steps")

    return {
        "pending_steps": pending_steps,
        "blocked_steps": blocked_steps,
        "failed_steps": failed_steps,
        "ready_steps": ready,
        "dependency_states": states,
        "missing_executors": missing_executors,
        "capability_mismatches": capability_mismatches,
        "step_diagnostics": step_diagnostics,
        "cycle_detected": detect_cycle(normalized),
        "reasons": reasons,
    }


def format_deadlock_error(diagnostics: dict[str, Any]) -> str:
    """Human-readable deadlock message with per-step blocking detail."""
    import json

    lines: list[str] = ["Work-plan vastgelopen: geen uitvoerbare stappen."]
    for item in diagnostics.get("step_diagnostics") or []:
        if not item.get("blocked") and item.get("blocking_reason") is None:
            continue
        sid = item.get("step_id")
        reason = item.get("blocking_reason") or "blocked"
        lines.append(
            f"Step {sid} blocked: "
            f"dependency statuses={item.get('dependency_statuses')}; "
            f"required capability={item.get('required_capability')}; "
            f"assigned executor={item.get('assigned_executor')}; "
            f"executor capability mismatch={not bool(item.get('executor_supports_capability'))}; "
            f"reason={reason}"
        )
    payload = {
        "pending_steps": diagnostics.get("pending_steps") or [],
        "blocked_steps": diagnostics.get("blocked_steps") or [],
        "failed_steps": diagnostics.get("failed_steps") or [],
        "dependency_states": diagnostics.get("dependency_states") or {},
        "missing_executors": diagnostics.get("missing_executors") or [],
        "capability_mismatches": diagnostics.get("capability_mismatches") or [],
        "step_diagnostics": diagnostics.get("step_diagnostics") or [],
        "cycle_detected": bool(diagnostics.get("cycle_detected")),
        "reasons": diagnostics.get("reasons") or [],
    }
    lines.append(f"diagnostics={json.dumps(payload, ensure_ascii=False)}")
    return " ".join(lines)


def execution_waves(
    steps: list[ScheduledStep] | list[dict[str, Any]],
    *,
    completed_ids: set[str] | None = None,
) -> list[list[str]]:
    """Partition remaining work into parallel waves (independent steps together)."""
    normalized = _normalize_steps(steps)

    completed = set(completed_ids or set())
    for step in normalized:
        if step.status == "completed":
            completed.add(step.step_id)

    waves: list[list[str]] = []
    safety = len(normalized) + 2
    while safety > 0:
        safety -= 1
        pending = [
            step
            for step in normalized
            if step.step_id not in completed and step.status not in {"cancelled", "failed", "blocked"}
        ]
        if not pending:
            break
        for step in pending:
            if step.status not in {"running"}:
                step.status = "pending"
        wave = ready_steps(pending, completed_ids=completed)
        if not wave:
            break
        waves.append(wave)
        completed.update(wave)
    return waves


def steps_invalidated_by_redirect(
    steps: list[dict[str, Any]],
    *,
    completed_ids: set[str],
    changed_step_ids: set[str],
) -> set[str]:
    """Future dependents of changed steps become invalid; completed unrelated work stays."""
    depends: dict[str, list[str]] = {}
    for index, step in enumerate(steps):
        sid = _step_key(step, index)
        depends[sid] = [str(item) for item in (step.get("depends_on") or [])]

    invalidated = set(changed_step_ids)
    changed = True
    while changed:
        changed = False
        for sid, deps in depends.items():
            if sid in invalidated:
                continue
            if any(dep in invalidated for dep in deps):
                invalidated.add(sid)
                changed = True
    # Completed steps not in invalidated remain reusable.
    return {sid for sid in invalidated if sid not in completed_ids or sid in changed_step_ids}


# Recovery strategy taxonomy for changed state (WP3).
RECOVERY_STRATEGIES = frozenset(
    {
        "retry",
        "retry_with_params",
        "alternate_tool",
        "replace_subplan",
        "redesign_mission",
        "ask_user",
    }
)


def steps_invalidated_by_input_change(
    steps: list[dict[str, Any]],
    *,
    completed_ids: set[str] | None = None,
    changed_input_refs: set[str] | frozenset[str],
) -> dict[str, Any]:
    """Invalidate only branches that consume a changed input (and their dependents).

    Independent completed branches whose input_refs do not overlap remain reusable.
    Also invalidates verification/check steps that declare dependence on invalidated work.
    """
    completed_ids = set(completed_ids or [])
    changed_inputs = {str(x) for x in changed_input_refs if str(x).strip()}
    depends: dict[str, list[str]] = {}
    input_map: dict[str, set[str]] = {}
    for index, step in enumerate(steps):
        sid = _step_key(step, index)
        depends[sid] = [str(item) for item in (step.get("depends_on") or [])]
        refs = {str(item) for item in (step.get("input_refs") or []) if str(item).strip()}
        # Accept inputs declared under io.inputs as well.
        io = step.get("io") if isinstance(step.get("io"), dict) else {}
        for item in io.get("inputs") or []:
            refs.add(str(item))
        input_map[sid] = refs

    directly_hit = {sid for sid, refs in input_map.items() if refs & changed_inputs}
    invalidated = set(directly_hit)
    changed = True
    while changed:
        changed = False
        for sid, deps in depends.items():
            if sid in invalidated:
                continue
            if any(dep in invalidated for dep in deps):
                invalidated.add(sid)
                changed = True

    reusable = {
        sid
        for sid in completed_ids
        if sid not in invalidated
    }
    requeue = sorted(invalidated)
    return {
        "changed_inputs": sorted(changed_inputs),
        "directly_hit": sorted(directly_hit),
        "invalidated_step_ids": requeue,
        "reusable_step_ids": sorted(reusable),
        "preserved_completed": sorted(reusable),
        "note": "Only hit branches and dependent checks are re-run; unrelated results stay.",
    }


def choose_recovery_strategy(
    *,
    cause: str,
    attempts: int = 0,
    max_retries: int = 2,
    alternate_tool_available: bool = False,
    params_adjustable: bool = False,
    subplan_replaceable: bool = False,
    user_choice_required: bool = False,
) -> dict[str, Any]:
    """Pick an explicit recovery strategy — never a silent infinite retry."""
    cause_l = str(cause or "").strip().lower()
    if user_choice_required or cause_l in {"permission", "ambiguous_goal", "irreconcilable"}:
        strategy = "ask_user"
    elif cause_l in {"provider_down", "model_unavailable"} and alternate_tool_available:
        strategy = "alternate_tool"
    elif cause_l in {"unexpected_result", "verification_failed"} and subplan_replaceable and attempts >= max_retries:
        strategy = "replace_subplan"
    elif cause_l in {"goal_changed", "requirements_changed"}:
        strategy = "redesign_mission"
    elif params_adjustable and attempts >= 1:
        strategy = "retry_with_params"
    elif attempts < max_retries:
        strategy = "retry"
    elif alternate_tool_available:
        strategy = "alternate_tool"
    elif subplan_replaceable:
        strategy = "replace_subplan"
    else:
        strategy = "ask_user"
    assert strategy in RECOVERY_STRATEGIES
    return {
        "strategy": strategy,
        "cause": cause_l,
        "attempts": attempts,
        "max_retries": max_retries,
    }
