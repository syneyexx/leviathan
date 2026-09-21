"""Complexity-aware coding task DAG, uncertainty, and specialist selection.

Reuses reasoning.plan_scheduler for acyclic validation. Trivial tasks skip heavy plans.
"""

from __future__ import annotations

import re
from typing import Any

from reasoning.budgets import ExecutionBudget
from reasoning.plan_scheduler import validate_plan
from reasoning.resource_awareness import classify_task_complexity

EPISTEMIC = (
    "KNOWN",
    "OBSERVED",
    "INFERRED",
    "ASSUMED",
    "UNKNOWN",
    "PROPOSED",
    "VERIFIED",
    "FALSIFIED",
)

CODING_SPECIALISTS = (
    "coding_investigator",
    "coding_planner",
    "coding_editor",
    "coding_test_engineer",
    "coding_debugger",
    "coding_security_reviewer",
    "coding_api_reviewer",
    "coding_final_reviewer",
)


def estimate_coding_complexity(
    *,
    goal: str,
    file_count: int = 0,
    languages: list[str] | None = None,
    hits: int = 0,
    has_failures: bool = False,
) -> dict[str, Any]:
    base = classify_task_complexity(goal, has_files=file_count > 3 or hits > 6)
    score = 0
    lower = (goal or "").lower()
    if file_count >= 4:
        score += 2
    if hits >= 8:
        score += 1
    if has_failures:
        score += 2
    if any(k in lower for k in ("migrat", "refactor", "api", "concurren", "security", "schema")):
        score += 2
    if languages and len(languages) > 1:
        score += 1
    if any(k in lower for k in ("typo", "rename variable", "one line")):
        score -= 2
    # Tiny classic arithmetic fix.
    if re.search(r"\badd\b", lower) and file_count <= 3:
        score -= 1
    if score <= 0:
        level = "trivial"
        plan = False
    elif score >= 3 or base.get("complexity") == "complex":
        level = "complex"
        plan = True
    else:
        level = "standard"
        plan = base.get("use_planner", True)
    return {
        "level": level,
        "use_planner": plan,
        "use_candidates": level == "complex",
        "use_specialists": level == "complex",
        "base": base,
        "score": score,
    }


def coding_budgets(complexity: dict[str, Any], *, caller_max_attempts: int = 3) -> ExecutionBudget:
    level = complexity.get("level")
    if level == "trivial":
        return ExecutionBudget(
            max_model_calls=2,
            max_tool_rounds=6,
            max_replans=0,
            max_repair_attempts=min(2, max(1, caller_max_attempts)),
        )
    if level == "complex":
        return ExecutionBudget(
            max_model_calls=12,
            max_tool_rounds=24,
            max_replans=2,
            max_repair_attempts=max(2, caller_max_attempts),
        )
    return ExecutionBudget(
        max_model_calls=6,
        max_tool_rounds=12,
        max_replans=1,
        max_repair_attempts=max(2, min(4, caller_max_attempts)),
    )


def build_coding_dag(
    *,
    goal: str,
    complexity: dict[str, Any],
    has_failures: bool = False,
    report_only: bool = False,
) -> dict[str, Any]:
    if report_only:
        raw_steps = [
            _step("investigate", "Investigate repository evidence", [], "findings"),
            _step("report", "Write grounded report", ["investigate"], "report_artifact"),
            _step("review", "Independent review of report", ["report"], "review"),
        ]
    elif not complexity.get("use_planner"):
        raw_steps = [
            _step("implement", "Apply minimal evidence-gated edit", [], "edits"),
            _step("verify", "Run targeted tests", ["implement"], "test_results"),
        ]
    else:
        raw_steps = [
            _step("investigate", "Map relevant symbols and tests", [], "findings"),
            _step("reproduce", "Reproduce failing behavior", ["investigate"], "failure_object", optional=not has_failures),
            _step("design", "Lock implementation area and risks", ["investigate"], "plan"),
            _step("edit", "Apply transactional edits in isolated worktree", ["design"], "diff"),
            _step("targeted_verify", "Run impacted tests", ["edit"], "test_results"),
            _step("repair", "Failure-driven repair if needed", ["targeted_verify"], "repair_log"),
            _step("regression", "Run broader checks when risk is high", ["repair"], "regression"),
            _step("review", "Independent review", ["regression"], "review"),
        ]
        if not has_failures:
            raw_steps = [s for s in raw_steps if s["step_id"] != "reproduce"]
    plan = {
        "goal": goal,
        "acceptance_criteria": ["Isolated worktree only until approval", "No test weakening", "Honest status"],
        "steps": raw_steps,
        "version": 1,
        "notes": [f"complexity={complexity.get('level')}"],
    }
    from reasoning.plan_scheduler import ready_steps as ready_step_ids

    try:
        validated = validate_plan(
            plan,
            allowed_agents={"build", "executor"},
            max_steps=12,
            default_agent="build",
            require_executable_path=True,
            enforce_capabilities=True,
        )
        ready = ready_step_ids(validated.steps)
        plan_payload = validated.to_dict()
    except Exception as exc:
        plan_payload = {**plan, "validation_error": str(exc), "status": "unvalidated_fallback"}
        ready = [raw_steps[0]["step_id"]]
    return {
        "plan": plan_payload,
        "complexity": complexity,
        "ready_step_ids": list(ready) if ready else [raw_steps[0]["step_id"]],
        "revisable": True,
        "note": "Discard this plan when evidence falsifies its assumptions.",
    }


def _step(step_id: str, title: str, depends: list[str], output: str, *, optional: bool = False) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "title": title,
        "instruction": title,
        "agent_id": "build",
        "kind": "work",
        "required_capability": "code.build",
        "depends_on": depends,
        "expected_evidence": [output],
        "status": "pending",
        "optional": optional,
    }


def make_claim(text: str, status: str, *, evidence: str = "", next_test: str = "") -> dict[str, Any]:
    st = (status or "UNKNOWN").upper()
    if st not in EPISTEMIC:
        st = "UNKNOWN"
    return {
        "claim": text,
        "status": st,
        "evidence": evidence,
        "next_test": next_test,
        "note": "Assumptions are not facts. Falsified claims must not be retried unchanged.",
    }


def update_claim(claim: dict[str, Any], *, status: str, evidence: str = "") -> dict[str, Any]:
    updated = dict(claim)
    st = (status or "").upper()
    if st not in EPISTEMIC:
        raise ValueError(f"invalid_epistemic_status:{status}")
    if claim.get("status") == "FALSIFIED" and st in {"KNOWN", "VERIFIED", "ASSUMED"}:
        raise ValueError("falsified_claim_cannot_become_fact")
    updated["status"] = st
    if evidence:
        updated["evidence"] = evidence
    return updated


def select_specialists(complexity: dict[str, Any], *, task_type: str, files: list[str]) -> list[str]:
    if not complexity.get("use_specialists"):
        return ["build"]
    chosen = ["coding_investigator", "coding_planner", "coding_editor", "coding_test_engineer", "coding_final_reviewer"]
    blob = " ".join(files).lower() + task_type
    if any(x in blob for x in ("auth", "secret", "permission", "exec", "shell")):
        chosen.append("coding_security_reviewer")
    if any(x in blob for x in ("route", "api", "schema", "openapi")):
        chosen.append("coding_api_reviewer")
    if task_type in {"bugfix", "regression"}:
        chosen.append("coding_debugger")
    return list(dict.fromkeys(chosen))
