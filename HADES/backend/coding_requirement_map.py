"""Coding task contract + requirement ↔ code ↔ verification mapping.

Extends existing CodingAgentService / BuildAgentService without a second workspace manager.
Mappings must be evidence-based — never link every requirement to every changed file.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

CONTRACT_VERSION = "coding_task_contract_v2"

HONEST_STATUSES = (
    "COMPLETED_VERIFIED",
    "COMPLETED_PARTIALLY_VERIFIED",
    "FAILED_VERIFICATION",
    "BLOCKED",
    "AWAITING_APPROVAL",
    "CANCELLED",
    "INTERRUPTED",
    "CONFLICT",
    "RUNNING",
    "INCOMPLETE",
)

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def build_coding_task_contract(
    *,
    goal: str,
    source_repo: str,
    base_revision: str | None = None,
    project_id: str | None = None,
    requirements: list[str] | list[dict[str, Any]] | None = None,
    acceptance_criteria: list[str] | None = None,
    constraints: list[str] | None = None,
    non_goals: list[str] | None = None,
    assumptions: list[dict[str, Any]] | None = None,
    unknowns: list[str] | None = None,
    risk_level: str = "medium",
    target_files: list[str] | None = None,
    suspected_files: list[str] | None = None,
    protected_paths: list[str] | None = None,
    verification_requirements: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    approval_requirements: list[str] | None = None,
    budget: dict[str, Any] | None = None,
    parent_task: str | None = None,
    subtasks: list[dict[str, Any]] | None = None,
    dependencies: list[str] | None = None,
    artifacts: list[str] | None = None,
    autonomy_profile: str | None = None,
    status: str = "RUNNING",
    task_id: str | None = None,
) -> dict[str, Any]:
    reqs = _normalize_requirements(requirements, goal)
    criteria = list(acceptance_criteria or [])
    if not criteria:
        criteria = [
            "Source workspace unchanged until explicit apply approval",
            "Tests are not weakened to obtain a green result",
            "Status is honest given executed verification",
        ]
    approvals = list(approval_requirements or ["apply_to_source"])
    tools = list(allowed_tools or ["rg", "ast", "lsp", "git", "unittest", "pytest"])
    return {
        "schema": CONTRACT_VERSION,
        "task_id": task_id or f"ctask_{uuid.uuid4().hex[:12]}",
        "project_id": project_id,
        "repository": source_repo,
        "base_revision": base_revision,
        "goal": (goal or "").strip(),
        "requirements": reqs,
        "acceptance_criteria": criteria,
        "constraints": list(constraints or ["Do not modify protected user paths", "Isolated worktree mutation only"]),
        "non_goals": list(non_goals or ["publish", "push", "force-reset user work"]),
        "assumptions": [dict(a) for a in (assumptions or [])],
        "unknowns": list(unknowns or []),
        "risk_level": risk_level,
        "target_files": list(target_files or []),
        "suspected_files": list(suspected_files or []),
        "protected_paths": list(protected_paths or []),
        "verification_requirements": list(verification_requirements or ["unit"]),
        "allowed_tools": tools,
        "approval_requirements": approvals,
        "budget": dict(budget or {}),
        "status": status if status in HONEST_STATUSES else "RUNNING",
        "parent_task": parent_task,
        "subtasks": list(subtasks or []),
        "dependencies": list(dependencies or []),
        "artifacts": list(artifacts or []),
        "autonomy_profile": autonomy_profile,
        "trace": [],
    }


def _normalize_requirements(requirements: list[Any] | None, goal: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if requirements:
        for index, raw in enumerate(requirements):
            if isinstance(raw, dict):
                rows.append(
                    {
                        "id": str(raw.get("id") or f"req_{index + 1}"),
                        "text": str(raw.get("text") or raw.get("requirement") or raw.get("title") or ""),
                        "files": list(raw.get("files") or []),
                        "tests": list(raw.get("tests") or []),
                    }
                )
            else:
                rows.append({"id": f"req_{index + 1}", "text": str(raw), "files": [], "tests": []})
        return rows
    bullets = re.split(r"(?:^|\n)\s*(?:[-*]|\d+\.)\s+", goal or "")
    parts = [p.strip() for p in bullets if p.strip() and p.strip() != (goal or "").strip()]
    if len(parts) >= 2:
        for index, text in enumerate(parts[:12]):
            rows.append({"id": f"req_{index + 1}", "text": text, "files": [], "tests": []})
        return rows
    text = (goal or "").strip()
    if text:
        rows.append({"id": "req_1", "text": text, "files": [], "tests": []})
    return rows


def _tokens(text: str) -> set[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "fix",
        "add",
        "test",
        "file",
        "code",
        "make",
        "should",
        "must",
        "repareer",
        "fout",
    }
    return {t.lower() for t in _WORD.findall(text or "") if t.lower() not in stop and len(t) > 2}


def _score_file_for_requirement(req_text: str, path: str, *, diff_text: str = "", file_tokens: set[str] | None = None) -> tuple[float, str]:
    req = _tokens(req_text)
    if not req:
        return 0.0, "no_requirement_tokens"
    path_tokens = _tokens(path.replace("/", " ").replace("_", " ").replace(".", " "))
    overlap = req & path_tokens
    score = 2.0 * len(overlap)
    reason = f"path_overlap:{','.join(sorted(overlap))}" if overlap else ""
    extra = file_tokens or set()
    file_overlap = req & extra
    if file_overlap:
        score += 1.5 * len(file_overlap)
        reason = (reason + f";symbol:{','.join(sorted(file_overlap)[:6])}").strip(";")
    if diff_text:
        # Only credit a file when the diff hunk header or path appears next to requirement tokens.
        if path.replace("\\", "/") in diff_text.replace("\\", "/"):
            blob_tokens = _tokens(diff_text)
            shared = req & blob_tokens
            if shared:
                score += 1.0
                reason = (reason + ";diff_tokens").strip(";")
    return score, reason or "insufficient_evidence"


def build_requirement_verification_map(
    *,
    requirements: list[str] | list[dict[str, Any]],
    changed_files: list[str] | None = None,
    test_results: dict[str, Any] | None = None,
    base_revision: str | None = None,
    workspace_kind: str = "worktree",
    protected_user_paths: list[str] | None = None,
    diff_text: str | None = None,
    file_evidence: dict[str, list[str]] | None = None,
    min_score: float = 2.0,
) -> dict[str, Any]:
    """Explicit mapping: requirement → touched files → verification status.

    Files are linked only when path/symbol/diff evidence supports the requirement.
    """
    rows: list[dict[str, Any]] = []
    files = list(changed_files or [])
    tests = dict(test_results or {})
    protected = set(protected_user_paths or [])
    touched_protected = sorted(protected & set(files))
    evidence = {k.replace("\\", "/"): set(v) for k, v in (file_evidence or {}).items()}
    diff = diff_text or ""
    executed_tests = list(tests.get("tests") or [])
    test_passed = bool(tests.get("passed") or tests.get("ok") or str(tests.get("status") or "").lower() == "passed")

    for index, raw in enumerate(requirements or []):
        if isinstance(raw, dict):
            req_id = str(raw.get("id") or f"req_{index + 1}")
            text = str(raw.get("text") or raw.get("requirement") or raw.get("title") or "")
            explicit_files = [str(p) for p in (raw.get("files") or []) if p]
            explicit_tests = list(raw.get("tests") or [])
        else:
            req_id = f"req_{index + 1}"
            text = str(raw)
            explicit_files = []
            explicit_tests = []

        linked: list[dict[str, Any]] = []
        if explicit_files:
            for path in explicit_files:
                if path in files or not files:
                    linked.append({"path": path, "reason": "requirement_declared_file", "score": 10.0})
        else:
            for path in files:
                score, reason = _score_file_for_requirement(
                    text,
                    path,
                    diff_text=diff,
                    file_tokens=evidence.get(path.replace("\\", "/"), set()),
                )
                if score >= min_score:
                    linked.append({"path": path, "reason": reason, "score": round(score, 2)})

        linked_paths = [item["path"] for item in linked]
        linked_tests = list(explicit_tests)
        if not linked_tests:
            req_tok = _tokens(text)
            for tname in executed_tests:
                if req_tok & _tokens(str(tname)):
                    linked_tests.append(str(tname))
        verified = bool(linked_paths) and test_passed and (not executed_tests or bool(linked_tests) or test_passed)
        if not files:
            status = "unverified"
        elif not linked_paths:
            status = "unmapped"
            verified = False
        elif tests and not test_passed:
            status = "failed"
        elif tests and test_passed and linked_paths:
            status = "passed" if (linked_tests or not executed_tests) else "partial"
        else:
            status = "unverified"

        rows.append(
            {
                "requirement_id": req_id,
                "requirement": text,
                "changed_files": linked_paths,
                "file_evidence": linked,
                "verification": {
                    "tests": linked_tests,
                    "passed": test_passed if tests else None,
                    "status": status,
                    "evidence_based": True,
                },
            }
        )
    return {
        "map_version": "coding_requirement_map_v2",
        "base_revision": base_revision,
        "workspace_kind": workspace_kind,
        "requirements": rows,
        "protected_user_paths": sorted(protected),
        "protected_paths_touched": touched_protected,
        "user_files_preserved": len(touched_protected) == 0,
        "unmapped_changed_files": sorted(set(files) - {p for row in rows for p in row.get("changed_files") or []}),
        "honest_limits": [
            "Automatic repair rounds remain bounded by CodingAgentService max_attempts.",
            "Tests may change only when the contract intentionally changes.",
            "Publish/push/merge still require existing user authorization.",
            "Requirement-to-file links require path/symbol/diff evidence.",
        ],
    }


def attach_requirement_trace(
    contract: dict[str, Any],
    *,
    path: str,
    requirement_id: str,
    reason: str,
    verification: str | None = None,
) -> dict[str, Any]:
    """Record why a file changed. Call only with evidence."""
    updated = dict(contract)
    trace = list(updated.get("trace") or [])
    trace.append(
        {
            "path": path,
            "requirement_id": requirement_id,
            "reason": reason,
            "verification": verification,
        }
    )
    updated["trace"] = trace
    reqs = []
    for row in updated.get("requirements") or []:
        item = dict(row) if isinstance(row, dict) else {"id": "req_1", "text": str(row), "files": []}
        if str(item.get("id") or item.get("requirement_id")) == requirement_id:
            files = list(item.get("files") or [])
            if path not in files:
                files.append(path)
            item["files"] = files
        reqs.append(item)
    updated["requirements"] = reqs
    return updated


def failed_repair_delivery(
    *,
    diagnosis: str,
    partial_diff: str | None = None,
    test_results: dict[str, Any] | None = None,
    requirement_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Honest partial delivery when repair fails — no fake success."""
    return {
        "status": "failed_repair",
        "diagnosis": (diagnosis or "").strip()[:4000],
        "partial_diff": partial_diff,
        "test_results": dict(test_results or {}),
        "requirement_map": requirement_map,
        "completed": False,
        "note": "Repair did not fully succeed; partial result and diagnosis are preserved.",
    }


def honest_frontier_status(
    *,
    runner_status: str,
    tests_passed: bool,
    review_status: str | None = None,
    required_unverified: bool = False,
    awaiting_approval: bool = False,
    conflict: bool = False,
    cancelled: bool = False,
    interrupted: bool = False,
) -> str:
    if cancelled:
        return "CANCELLED"
    if interrupted:
        return "INTERRUPTED"
    if conflict:
        return "CONFLICT"
    if awaiting_approval and tests_passed:
        return "AWAITING_APPROVAL"
    rs = (runner_status or "").lower()
    if rs in {"tests_failed", "failed"} or (not tests_passed and rs not in {"ready_for_review"}):
        if rs in {"running"}:
            return "RUNNING"
        if rs in {"incomplete", "blocked"}:
            return "BLOCKED"
        if rs in {"ready_for_review"} and not tests_passed:
            return "AWAITING_APPROVAL"
        return "FAILED_VERIFICATION"
    if review_status == "reject":
        return "FAILED_VERIFICATION"
    if tests_passed and required_unverified:
        return "COMPLETED_PARTIALLY_VERIFIED"
    if tests_passed and rs in {"verified", "completed"}:
        return "COMPLETED_VERIFIED"
    if rs in {"ready_for_review"}:
        return "AWAITING_APPROVAL"
    if rs in {"verified"}:
        return "COMPLETED_VERIFIED" if tests_passed else "FAILED_VERIFICATION"
    return "INCOMPLETE"


def user_facing_result(
    *,
    goal: str,
    changed_files: list[str],
    why: list[str] | None = None,
    verification_executed: list[str],
    verification_passed: list[str],
    verification_not_run: list[str],
    limitations: list[str],
    remaining_risks: list[str],
    approval_required: list[str],
    status: str,
) -> dict[str, Any]:
    return {
        "what_was_requested": goal,
        "what_changed": list(changed_files),
        "why": list(why or []),
        "files_changed": list(changed_files),
        "verification_executed": list(verification_executed),
        "verification_passed": list(verification_passed),
        "verification_not_run": list(verification_not_run),
        "known_limitations": list(limitations),
        "remaining_risks": list(remaining_risks),
        "approval_action_required": list(approval_required),
        "status": status,
    }


def contract_fingerprint(contract: dict[str, Any]) -> str:
    blob = f"{contract.get('task_id')}:{contract.get('goal')}:{contract.get('base_revision')}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
