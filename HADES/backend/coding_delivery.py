"""CodingDeliveryV1 — versioned delivery artifact for Coding Agent runs.

Required fields encode understanding, changes/findings, checks, uncertainties,
and a concrete next step when incomplete. Status cannot honestly be ``completed``
without required outputs for the task mode.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CODING_DELIVERY_VERSION = "coding_delivery_v1"

WORKFLOW_PHASES = (
    "understand",
    "read_repo_instructions",
    "investigate",
    "lock_scope",
    "prepare_workspace",
    "implement_or_report",
    "run_checks",
    "review_diff",
    "independent_judge",
    "delivery_artifact",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_coding_delivery(
    *,
    goal: str,
    task_type: str | None = None,
    understanding: str | None = None,
    changed_files: list[str] | None = None,
    findings: list[dict[str, Any]] | None = None,
    diff_text: str | None = None,
    checks_run: list[dict[str, Any]] | None = None,
    test_results: list[dict[str, Any]] | None = None,
    uncertainties: list[str] | None = None,
    next_step: str | None = None,
    work_root: str | None = None,
    baseline_commit: str | None = None,
    branch: str | None = None,
    autonomy_profile: str | None = None,
    scope: list[str] | None = None,
    out_of_scope_changes: list[str] | None = None,
    phases_completed: list[str] | None = None,
    status: str = "incomplete",
    run_id: str | None = None,
    model_id: str | None = None,
    extra: dict[str, Any] | None = None,
    user_facing: dict[str, Any] | None = None,
    frontier_status: str | None = None,
    requirement_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required = ["understanding", "checks_run", "uncertainties"]
    tt = (task_type or "bugfix").lower()
    if tt in {"bugfix", "feature"}:
        required.extend(["changed_files", "diff_text", "test_results"])
    elif tt == "regression":
        required.append("findings")
    elif tt == "review":
        required.append("findings")

    payload: dict[str, Any] = {
        "schema": CODING_DELIVERY_VERSION,
        "created_at": utc_now(),
        "run_id": run_id,
        "goal": (goal or "").strip(),
        "task_type": tt,
        "understanding": (understanding or goal or "").strip(),
        "changed_files": list(changed_files or []),
        "findings": list(findings or []),
        "diff_text": diff_text or "",
        "checks_run": list(checks_run or []),
        "test_results": list(test_results or []),
        "uncertainties": list(uncertainties or []),
        "next_step": next_step,
        "work_root": work_root,
        "baseline_commit": baseline_commit,
        "branch": branch,
        "autonomy_profile": autonomy_profile,
        "scope": list(scope or []),
        "out_of_scope_changes": list(out_of_scope_changes or []),
        "phases_completed": list(phases_completed or []),
        "workflow_phases": list(WORKFLOW_PHASES),
        "status": status,
        "frontier_status": frontier_status,
        "user_facing": dict(user_facing or {}),
        "requirement_map": dict(requirement_map or {}),
        "model_id": model_id,
        "extra": dict(extra or {}),
    }
    missing: list[str] = []
    for field in required:
        value = payload.get(field)
        if field == "uncertainties":
            # Empty list is a valid "no open uncertainties" signal; only absence is missing.
            if value is None:
                missing.append(field)
            continue
        if field == "understanding":
            if not str(value or "").strip():
                missing.append(field)
            continue
        if value is None or value == "":
            missing.append(field)
    # Special-case: empty list fields that are required count as missing.
    for f in ("changed_files", "findings", "checks_run", "test_results"):
        if f in required and isinstance(payload.get(f), list) and len(payload[f]) == 0:
            if f not in missing:
                missing.append(f)
    if tt in {"bugfix", "feature"} and not (payload.get("diff_text") or "").strip():
        if "diff_text" not in missing:
            missing.append("diff_text")

    complete = len(missing) == 0 and status in {"completed", "verified", "ready_for_review"}
    if status in {"completed", "verified"} and missing:
        # Honest: cannot claim completed with missing required outputs.
        payload["status"] = "incomplete"
        complete = False
        payload["demoted_from"] = status
        payload["demotion_reason"] = "missing_required_outputs"

    payload["required_fields"] = required
    payload["missing_fields"] = missing
    payload["complete"] = complete and not missing
    return payload


def write_delivery_artifact(work_root: Path | str, delivery: dict[str, Any]) -> Path:
    root = Path(work_root)
    out_dir = root / "artifacts" if root.is_dir() else root.parent
    # Prefer sibling artifacts under work_root
    art = Path(work_root) / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    path = art / "coding_delivery.json"
    path.write_text(json.dumps(delivery, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def validate_delivery_for_completion(delivery: dict[str, Any]) -> dict[str, Any]:
    """Gate: incomplete deliveries must not be marked completed."""
    missing = list(delivery.get("missing_fields") or [])
    status = str(delivery.get("status") or "")
    ok = delivery.get("complete") is True and status in {"completed", "verified", "ready_for_review"}
    return {
        "allowed": ok,
        "missing_fields": missing,
        "status": status,
        "schema": delivery.get("schema") or CODING_DELIVERY_VERSION,
    }
