"""Evidence-driven coding experience and failure memory via ProjectContinuity.

Does not create a second memory database. Inferred lessons stay assumptions, never facts.
"""

from __future__ import annotations

import json
from typing import Any


def record_coding_lesson(
    continuity: Any,
    project_id: str,
    *,
    title: str,
    body: str,
    provenance: str = "inferred",
    invalidation: str = "git_revision_change",
    revision: str | None = None,
) -> dict[str, Any] | None:
    if continuity is None or not project_id:
        return None
    if provenance not in {"user_explicit", "observed", "inferred", "proposal"}:
        provenance = "inferred"
    payload = {
        "lesson": body,
        "invalidation": invalidation,
        "revision": revision,
        "kind": "coding_experience",
    }
    try:
        return continuity.add_item(
            project_id,
            kind="assumption",
            title=title[:160],
            body=json.dumps(payload, ensure_ascii=False)[:4000],
            provenance=provenance,
        )
    except Exception:
        return None


def record_failure_signature(
    continuity: Any,
    project_id: str,
    *,
    signature: str,
    root_cause: str,
    successful_repair: str | None = None,
    repo_version: str | None = None,
    verification: str | None = None,
) -> dict[str, Any] | None:
    if continuity is None or not project_id:
        return None
    payload = {
        "signature": signature,
        "root_cause": root_cause,
        "successful_repair": successful_repair,
        "repo_version": repo_version,
        "verification": verification,
        "use_as": "hypothesis_only",
    }
    try:
        return continuity.add_item(
            project_id,
            kind="assumption",
            title=f"failure:{signature[:80]}",
            body=json.dumps(payload, ensure_ascii=False)[:4000],
            provenance="observed" if successful_repair else "inferred",
        )
    except Exception:
        return None


def recall_failure_hypotheses(continuity: Any, project_id: str, *, signature_tokens: list[str]) -> list[dict[str, Any]]:
    if continuity is None or not project_id:
        return []
    try:
        package = continuity.context_package(project_id)
    except Exception:
        return []
    hits: list[dict[str, Any]] = []
    for item in package.get("assumptions") or []:
        blob = f"{item.get('title') or ''} {item.get('body') or ''}".lower()
        if "failure:" not in blob and "coding_experience" not in blob:
            continue
        if signature_tokens and not any(tok.lower() in blob for tok in signature_tokens if tok):
            continue
        hits.append(
            {
                "title": item.get("title"),
                "body": item.get("body"),
                "provenance": item.get("provenance"),
                "status": "HYPOTHESIS",
                "note": "Retrieved failure memory is a hypothesis, not unquestioned truth.",
            }
        )
    return hits[:8]
