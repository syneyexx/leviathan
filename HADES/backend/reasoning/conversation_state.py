"""Compact conversation working state derived from history (correctable).

Raw messages remain the source of truth. Assistant completions are NOT automatic
user decisions. Corrections supersede prior constraints/decisions.
"""

from __future__ import annotations

import re
from typing import Any


_DECISION_MARKERS = (
    "besluit:",
    "afspraak:",
    "we kiezen",
    "we gaan",
    "voortaan",
    "from now on",
    "decision:",
    "agreed:",
)
_CORRECTION_MARKERS = (
    "corrigeer",
    "correctie",
    "niet meer",
    "in plaats van",
    "vergeet",
    "herzien",
    "actually",
    "correction:",
    "instead of",
)
_PROPOSAL_MARKERS = (
    "zullen we",
    "misschien",
    "voorstel",
    "ik stel voor",
    "could we",
    "suggestion:",
)


def _unique_keep_order(items: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item.strip())
    return result[-limit:]


def _is_user_decision(text: str) -> bool:
    lower = text.lower().strip()
    if any(marker in lower for marker in _DECISION_MARKERS):
        return True
    # Explicit imperative project agreements: "Gebruik X als ..."
    if re.match(r"^(gebruik|kies|stel in|gebruik voortaan)\b", lower):
        return True
    return False


def _is_correction(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _CORRECTION_MARKERS)


def _is_proposal(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _PROPOSAL_MARKERS)


def _apply_constraint_corrections(constraints: list[str], user_text: str) -> list[str]:
    """A new instruction may replace an old agreement without wiping unrelated goals."""
    if not _is_correction(user_text) and not _is_user_decision(user_text):
        return constraints
    lower = user_text.lower()
    kept: list[str] = []
    for item in constraints:
        item_l = item.lower()
        # Drop constraints that the correction clearly targets (shared keywords).
        shared = set(re.findall(r"[a-zA-Z0-9]{4,}", item_l)) & set(re.findall(r"[a-zA-Z0-9]{4,}", lower))
        if len(shared) >= 2 and (_is_correction(user_text) or "in plaats van" in lower or "instead of" in lower):
            continue
        kept.append(item)
    return kept


def _resolve_questions(open_questions: list[str], user_text: str, assistant_text: str, status: str | None) -> list[str]:
    remaining: list[str] = []
    user_l = user_text.lower()
    for question in open_questions:
        q_tokens = set(re.findall(r"[a-zA-Z0-9]{4,}", question.lower()))
        answered = bool(q_tokens & set(re.findall(r"[a-zA-Z0-9]{4,}", user_l))) and "?" not in user_text
        if answered:
            continue
        remaining.append(question)
    if "?" in user_text and status in {"partial", "failed", "blocked"}:
        q = user_text.strip()[:240]
        if q not in remaining:
            remaining.append(q)
    # If assistant fully answered and status completed, drop questions heavily overlapping the answer.
    if status == "completed" and assistant_text:
        answer_tokens = set(re.findall(r"[a-zA-Z0-9]{4,}", assistant_text.lower()))
        filtered: list[str] = []
        for question in remaining:
            q_tokens = set(re.findall(r"[a-zA-Z0-9]{4,}", question.lower()))
            if q_tokens and len(q_tokens & answer_tokens) >= max(2, len(q_tokens) // 2):
                continue
            filtered.append(question)
        remaining = filtered
    return remaining[-8:]


def _dedupe_artifacts(artifacts: list[str]) -> list[str]:
    return _unique_keep_order(artifacts, limit=12)


def build_conversation_working_state(
    *,
    previous: dict[str, Any] | None,
    user_text: str,
    assistant_text: str,
    request_spec: dict[str, Any] | None,
    route: dict[str, Any] | None,
    executed: dict[str, Any] | None,
    linked_task_id: str | None = None,
    linked_work_truth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive a compact state snapshot. Raw messages remain authoritative.

    ``linked_work_truth`` must come from the Work Runtime authority
    (``resolve_linked_work_truth`` / ``database.get_task`` + verified checkpoint).
    Chat ``status == completed`` and ``work_runtime_called`` alone never complete Work.
    """
    prior = dict(previous or {})
    status = (executed or {}).get("status")

    constraints = list(prior.get("constraints") or [])
    constraints = _apply_constraint_corrections(constraints, user_text)
    for item in (request_spec or {}).get("constraints") or []:
        if item not in constraints:
            constraints.append(item)
    if _is_user_decision(user_text) or _is_correction(user_text):
        # Store the latest user instruction as an active constraint when it looks binding.
        snippet = user_text.strip()[:240]
        if snippet and snippet not in constraints:
            constraints.append(snippet)
    constraints = _unique_keep_order(constraints, limit=12)

    decisions = list(prior.get("decisions") or [])
    proposals = list(prior.get("proposals") or [])
    # Corrections invalidate overlapping prior decisions.
    if _is_correction(user_text):
        lower = user_text.lower()
        kept_decisions: list[dict[str, Any]] = []
        for decision in decisions:
            summary = str((decision or {}).get("summary") or "").lower()
            shared = set(re.findall(r"[a-zA-Z0-9]{4,}", summary)) & set(re.findall(r"[a-zA-Z0-9]{4,}", lower))
            if len(shared) >= 2:
                continue
            kept_decisions.append(decision)
        decisions = kept_decisions
        decisions.append(
            {
                "summary": user_text.strip()[:180],
                "goal": (request_spec or {}).get("goal") or prior.get("goal"),
                "source": "user_correction",
                "message_role": "user",
            }
        )
    elif _is_user_decision(user_text):
        decisions.append(
            {
                "summary": user_text.strip()[:180],
                "goal": (request_spec or {}).get("goal") or prior.get("goal"),
                "source": "user_decision",
                "message_role": "user",
            }
        )
    # Assistant text may be a proposal, never an automatic decision.
    if assistant_text and _is_proposal(assistant_text):
        proposals.append({"summary": assistant_text[:180], "status": "proposed"})
    decisions = decisions[-8:]
    proposals = proposals[-8:]

    open_questions = _resolve_questions(
        list(prior.get("open_questions") or []),
        user_text,
        assistant_text,
        status if isinstance(status, str) else None,
    )

    # Topic change updates goal but does not wipe open_work / project artifacts.
    new_goal = (request_spec or {}).get("goal") or prior.get("goal")
    open_work = list(prior.get("open_work") or [])
    if linked_task_id:
        # Completed chat reply does not mean linked tasks are done.
        # Authority: Work task row + verified checkpoint / completion gate only.
        existing = next((item for item in open_work if item.get("task_id") == linked_task_id), None)
        truth = linked_work_truth if isinstance(linked_work_truth, dict) else None
        if truth is None:
            # Fail closed: without authoritative truth, retain/project as running.
            task_status = (existing or {}).get("status") or "running"
            open_work = [item for item in open_work if item.get("task_id") != linked_task_id]
            open_work.append({"task_id": linked_task_id, "status": task_status, "truth": "unverified"})
        elif truth.get("may_remove"):
            open_work = [item for item in open_work if item.get("task_id") != linked_task_id]
        else:
            projected = str(truth.get("status") or (existing or {}).get("status") or "running")
            if truth.get("missing"):
                # Do not invent completed; keep prior entry or mark unknown.
                projected = (existing or {}).get("status") or "unknown"
            open_work = [item for item in open_work if item.get("task_id") != linked_task_id]
            entry: dict[str, Any] = {"task_id": linked_task_id, "status": projected}
            if truth.get("reason"):
                entry["reason"] = truth.get("reason")
            open_work.append(entry)

    artifacts = list(prior.get("artifact_refs") or [])
    if linked_task_id:
        artifacts.append(f"task:{linked_task_id}")
    artifacts = _dedupe_artifacts(artifacts)

    answered = list(prior.get("answered_questions") or [])
    # Track newly closed questions
    prior_open = set(prior.get("open_questions") or [])
    for question in prior_open:
        if question not in open_questions and question not in answered:
            answered.append(question)
    answered = answered[-8:]

    recent_failures = list(prior.get("recent_failures") or [])
    if isinstance(status, str) and status in {"failed", "blocked", "partial", "cancelled"}:
        note = f"{status}:{(assistant_text or user_text or '')[:160]}".strip()
        if note and note not in recent_failures:
            recent_failures.append(note)
        recent_failures = recent_failures[-5:]
    elif status == "completed":
        recent_failures = []

    preserved_pins = prior.get("pins") if isinstance(prior.get("pins"), dict) else None
    preserved_summary_cache = prior.get("summary_cache") if isinstance(prior.get("summary_cache"), dict) else None
    preserved_budget = prior.get("run_budget") if isinstance(prior.get("run_budget"), dict) else None
    executed_budget = (executed or {}).get("budget") if isinstance(executed, dict) else None
    run_budget = executed_budget if isinstance(executed_budget, dict) else preserved_budget
    attempt_log = (executed or {}).get("attempt_log") if isinstance(executed, dict) else None
    if not isinstance(attempt_log, list):
        attempt_log = list(prior.get("attempt_log") or [])

    return {
        "goal": new_goal,
        "constraints": constraints,
        "decisions": decisions,
        "proposals": proposals,
        "open_questions": open_questions,
        "answered_questions": answered,
        "open_work": open_work[-8:],
        "artifact_refs": artifacts,
        "last_route": route,
        "last_executed": executed,
        "last_assistant": (assistant_text or "")[:500] if assistant_text else prior.get("last_assistant"),
        "recent_failures": recent_failures,
        # Conversation pins are operator-owned; preserve across derived state rebuilds.
        "pins": preserved_pins,
        "summary_cache": preserved_summary_cache,
        "run_budget": run_budget,
        "attempt_log": attempt_log[-24:] if isinstance(attempt_log, list) else [],
        "derived": True,
        "correctable": True,
        "note": "Samenvattende toestand; ruwe berichten blijven leidend bij conflict.",
    }
