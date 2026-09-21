"""Adaptive best-of-N coding candidates.

Previous unused experiments were removed. This module is an active, verification-driven
candidate search: isolated worktrees via BuildAgentService, scored by tests — not LLM taste.
Trivial edits must not pay 3× inference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from build_agent import BuildAgentService, FileEdit
from coding_verification import detect_test_weakening


def should_search_candidates(
    *,
    complexity_level: str,
    risk_level: str = "medium",
    ambiguous: bool = False,
    has_model: bool = False,
    already_verified: bool = False,
) -> bool:
    if already_verified or not has_model:
        return False
    if complexity_level == "trivial":
        return False
    if complexity_level == "complex" and (ambiguous or risk_level in {"high", "critical"}):
        return True
    return bool(ambiguous and complexity_level == "standard" and risk_level == "high")


def candidate_count(complexity_level: str, *, risk_level: str = "medium") -> int:
    if complexity_level == "complex" and risk_level in {"high", "critical"}:
        return 3
    if complexity_level == "complex":
        return 2
    return 1


def score_candidate(
    *,
    test_result: dict[str, Any],
    diff_text: str,
    applied: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = str(test_result.get("status") or "") == "passed"
    weaken = detect_test_weakening(diff_text)
    size = len(diff_text or "")
    files = len({item.get("path") for item in applied if item.get("path")})
    score = 0.0
    if passed:
        score += 100.0
    if weaken.get("weakened"):
        score -= 80.0
    score -= min(20.0, files * 1.5)
    score -= min(10.0, size / 4000.0)
    return {
        "score": round(score, 3),
        "passed": passed,
        "weakened": bool(weaken.get("weakened")),
        "files": files,
        "diff_chars": size,
        "method": "verification_and_minimality",
    }


def run_candidate_search(
    build: BuildAgentService,
    source_repo: Path,
    proposals: list[list[FileEdit]],
    *,
    test_suite: str = "unittest",
    test_args: list[str] | None = None,
    goal: str = "",
) -> dict[str, Any]:
    """Apply each proposal in its own isolated worktree and pick the strongest verified candidate."""
    if len(proposals) <= 1:
        return {"used": False, "reason": "single_proposal", "candidates": []}
    ranked: list[dict[str, Any]] = []
    for index, edits in enumerate(proposals):
        if not edits:
            ranked.append({"id": f"cand_{index}", "status": "empty", "score": -1e9})
            continue
        work, _commit, _hashes = build.prepare_workspace(source_repo)
        try:
            applied, diff = build.apply_edits_in_workspace(work, edits)
            test = build.run_tests(work, suite=test_suite, extra_args=test_args)
            scored = score_candidate(test_result=test, diff_text=diff, applied=applied)
            ranked.append(
                {
                    "id": f"cand_{index}",
                    "work_root": str(work),
                    "applied": applied,
                    "diff_text": diff,
                    "test": {"status": test.get("status"), "exit_code": test.get("exit_code")},
                    **scored,
                    "goal": goal,
                }
            )
        except Exception as exc:
            ranked.append({"id": f"cand_{index}", "status": "failed", "error": str(exc), "score": -1e9})
    ranked.sort(key=lambda item: float(item.get("score") or -1e9), reverse=True)
    winner = ranked[0] if ranked else None
    return {
        "used": True,
        "candidates": ranked,
        "selected": None if winner is None else winner.get("id"),
        "winner": winner,
        "note": "Selection is verification-driven; LLM preference is not used as a tie-breaker.",
    }


Generator = Callable[[int], list[FileEdit]]
